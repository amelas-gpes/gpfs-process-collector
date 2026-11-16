/* One reviewed interviewer voice. Local audio capture -> transcript -> reviewed
 * interview response -> authorized playback. No direct model-to-speaker path. */
(function (global) {
  "use strict";
  const SILENCE_MS=1800, MIN_SILENCE_MS=1000, MAX_SILENCE_MS=5000, MIN_SPEECH_MS=550, MIN_VOICED_MS=250, MAX_SEGMENT_MS=90000, MAX_EMPTY_TRANSCRIPTS=3;
  // The noise gate. A frame at or above SPEECH_LEVEL (RMS) is voiced. A recording is taken for
  // speech with a quarter second of voiced audio, or with about half that when its loudest frame is
  // clearly speech (a one-word answer); a cough, a breath or an echo tail stays below both. The
  // short tail after the last voiced frame counts too, so a word's decay is not lost.
  const SPEECH_LEVEL=0.022, STRONG_LEVEL=SPEECH_LEVEL*3, SHORT_VOICED_MS=120, HANGOVER_MS=60, NEAR_MISS_MS=100;
  // The meter. A frame up to FRAME_CREDIT_MS after the last one counts as on time. One silent
  // reading vouches for at most QUIET_CREDIT_MS of silence. A silent recording with UNMEASURED_MS
  // or more that no reading covered is restarted with a notice.
  const CLIPPED_START_MS=150, CLIPPED_REPEAT_MS=10000;
  const FRAME_CREDIT_MS=100, QUIET_CREDIT_MS=1200, UNMEASURED_MS=3000, HIDDEN_FRAME_MS=250, FRAME_BACKUP_MS=1000, WIDE_WINDOW=32768;
  const MAX_RETRY_AUDIO=12*1024*1024, RETRY_AUDIO_MS=10*60*1000;
  const KINDS=new Set(["question","final_check","complete","pause","review_pending"]);
  const REVIEW_ACK="Let me check that I have everything before we finish.";
  const PARTIAL_REVIEW_ACK="Let me check what we have and keep the unanswered parts open.";
  const sourceSignature=value=>JSON.stringify([value?.context||{},value?.turns||[],value?.document_revision||""]);
  // Prepare an empty reader connection while the answer is transcribed. No
  // transcript or generated text is sent until the speech authorization passes.
  class CollectorSpeechPreparation {
    constructor(getSession,voice,{signal,WebSocket:Socket=global.WebSocket,setTimeout:later=(fn,ms)=>global.setTimeout(fn,ms),clearTimeout:unlater=id=>global.clearTimeout(id)}={}){
      this.voice=voice;this.socket=null;this.session=null;this.closed=false;this.consumed=false;
      this.ready=new Promise(resolve=>{this.resolve=resolve;});
      this.signal=signal;this.abort=()=>this.dispose();this.unlater=unlater;
      this.timer=later(()=>this.dispose(),12000);
      signal?.addEventListener("abort",this.abort,{once:true});
      if(signal?.aborted){this.dispose();return;}
      Promise.resolve().then(()=>getSession(voice,signal)).then(session=>{
        if(this.closed)return;
        if(session?.provider!=="openai"||session.transport!=="openai-realtime-websocket"||typeof session.client_secret!=="string"||typeof session.model!=="string")throw Error("Invalid reader session");
        this.session=session;
        this.socket=new Socket(`wss://api.openai.com/v1/realtime?model=${encodeURIComponent(session.model)}`,["realtime",`openai-insecure-api-key.${session.client_secret}`]);
        this.message=event=>{
          if(typeof event.data!=="string"||event.data.length>65536){this.dispose();return;}
          try{const packet=JSON.parse(event.data);if(packet.type==="session.created")this.resolve(this);else if(packet.type==="error")this.dispose();}catch{this.dispose();}
        };
        this.failed=()=>this.dispose();
        this.socket.addEventListener("message",this.message);
        this.socket.addEventListener("error",this.failed);
        this.socket.addEventListener("close",this.failed);
      }).catch(()=>this.dispose());
    }
    detach(){
      this.unlater(this.timer);this.signal?.removeEventListener("abort",this.abort);
      this.socket?.removeEventListener("message",this.message);
      this.socket?.removeEventListener("error",this.failed);
      this.socket?.removeEventListener("close",this.failed);
    }
    async take(voice){
      await this.ready;
      if(this.closed||this.consumed||voice!==this.voice||this.socket?.readyState!==1)return null;
      this.consumed=true;this.detach();
      const value={session:this.session,socket:this.socket};this.session=null;this.socket=null;return value;
    }
    dispose(){
      if(this.closed)return;this.closed=true;this.detach();
      try{this.socket?.close();}catch{}
      this.socket=null;this.session=null;this.resolve(null);
    }
  }
  class CollectorControlledVoice {
    constructor(options={}) {
      for(const key of ["request","getSnapshot","onAnswer","onResult","speak"]){if(typeof options[key]!=="function")throw new TypeError(`Controlled voice requires ${key}.`);}
      this.options=options;this.operation=null;this.sequence=0;this.status="idle";this.pendingAudio=null;this.pendingAudioTimer=null;this.unplayed=null;
      // The pause that ends a turn. A longer one adds directly to the wait for every reply.
      const pause=Number(options.silenceMs);this.silenceMs=Number.isFinite(pause)?Math.min(MAX_SILENCE_MS,Math.max(MIN_SILENCE_MS,Math.round(pause))):SILENCE_MS;
      this.mediaDevices=options.mediaDevices||global.navigator?.mediaDevices;
      this.Recorder=options.MediaRecorder||global.MediaRecorder;
      this.Context=options.AudioContext||global.AudioContext||global.webkitAudioContext;
      this.now=options.now||(()=>global.performance?.now?.()??Date.now());
      this.raf=options.requestAnimationFrame||(typeof global.requestAnimationFrame==="function"?fn=>global.requestAnimationFrame(fn):null);
      this.caf=options.cancelAnimationFrame||(id=>global.cancelAnimationFrame(id));
      this.later=options.setTimeout||((fn,ms)=>global.setTimeout(fn,ms));
      this.unlater=options.clearTimeout||(id=>global.clearTimeout(id));
      this.hide=()=>{this.discardPendingAudio();void this.stop({immediate:true});};
      global.addEventListener?.("pagehide",this.hide);
      // Switch the meter between animation frames and its timer at once when the page is hidden or shown.
      this.visibility=()=>{const op=this.operation;if(op?.frame&&op.frameFn&&this.current(op)){this.cancelFrame(op);this.schedule(op,op.frameFn);}};
      global.document?.addEventListener?.("visibilitychange",this.visibility);
    }
    get active(){return Boolean(this.operation&&!this.operation.closing);}
    get connected(){return Boolean(this.operation?.ready&&!this.operation.closing);}
    get hasPendingAudio(){return Boolean(this.pendingAudio);}
    // True while the answer is transcribed and the reply prepared with the microphone still open.
    get overlapOpen(){const op=this.operation;return Boolean(op&&this.current(op)&&op.processing&&op.overlap&&!op.muted);}
    // True while the app itself keeps the microphone closed: the opening question, the completion
    // review and playback. The participant has not muted it and cannot be heard.
    get microphoneHeld(){const op=this.operation;return Boolean(op&&this.current(op)&&op.ready&&op.processing&&!op.overlap&&!op.muted);}
    notify(name,value){try{this.options[name]?.(value);}catch{/* Display callbacks cannot bypass cleanup. */}}
    current(op){return this.operation===op&&!op.closing&&!op.controller.signal.aborted;}
    setStatus(status){this.status=status;global.CollectorRawTrace?.record("reviewed.status",{state:status});this.notify("onStatus",status);}
    tracks(op,enabled){op.stream?.getAudioTracks().forEach(track=>{
      track.enabled=enabled;global.CollectorRawTrace?.record("reviewed.track_enabled",{enabled:track.enabled});
    });}
    discardPendingAudio(){
      this.pendingAudio=null;if(this.pendingAudioTimer!==null)this.unlater(this.pendingAudioTimer);this.pendingAudioTimer=null;
      this.notify("onTranscriptionRecovery",{available:false});
    }
    retainAudio(blob,reason,message){
      this.discardPendingAudio();
      if(blob.size>MAX_RETRY_AUDIO)return false;
      this.pendingAudio={blob,basis:sourceSignature(this.options.getSnapshot()),reason};
      this.pendingAudioTimer=this.later(()=>this.discardPendingAudio(),RETRY_AUDIO_MS);
      this.notify("onTranscriptionRecovery",{available:true,reason,message});return true;
    }
    retryableAudio(){
      if(!this.pendingAudio)return null;
      if(this.pendingAudio.basis!==sourceSignature(this.options.getSnapshot())){
        this.discardPendingAudio();this.notify("onError","The interview changed after that recording. Please repeat the answer or type it so it is added in the right place.");return null;
      }
      return this.pendingAudio;
    }
    async retryTranscription(){
      const pending=this.retryableAudio();if(!pending)return false;
      if(!this.active){await this.start({retryTranscription:true});return !this.pendingAudio;}
      const op=this.operation;if(op.processing||op.muted)return false;
      this.discardSegment(op);
      await this.work(op,signal=>this.processAnswer(op,pending.blob,signal,pending.basis));
      return !this.pendingAudio;
    }
    async start(payload={}) {
      if(this.active)return false;
      if(!this.mediaDevices?.getUserMedia||!this.Recorder||!this.Context){this.notify("onError","This browser cannot start controlled voice. Continue by typing.");return false;}
      const op={id:++this.sequence,controller:new AbortController(),stream:null,context:null,source:null,analyser:null,frame:null,segment:null,ready:false,muted:false,processing:false,closing:false,workController:null,
        // overlap: capture stays open during this work. stage: what the work is doing. queue: recordings
        // waiting for it. continuing: more of the same answer is being spoken. openAnswer: the last
        // participant turn came from voice and has no reply yet.
        overlap:false,stage:null,queue:[],continuing:false,openAnswer:false};
      this.operation=op;this.setStatus("connecting");
      try{
        const stream=await this.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
        if(!this.current(op)){stream.getTracks().forEach(track=>track.stop());return false;}
        op.stream=stream;this.tracks(op,false);
        op.context=new this.Context();op.source=op.context.createMediaStreamSource(stream);op.analyser=op.context.createAnalyser();op.analyser.fftSize=1024;op.source.connect(op.analyser);op.samples=new Float32Array(op.analyser.fftSize);
        op.rate=op.context.sampleRate>0?op.context.sampleRate:48000;op.wide=op.analyser;op.wideSamples=op.samples;
        // The long window (about two thirds of a second) for frames that come late.
        try{const wide=op.context.createAnalyser();wide.fftSize=WIDE_WINDOW;op.source.connect(wide);op.wide=wide;op.wideSamples=new Float32Array(WIDE_WINDOW);}catch{/* Late frames then measure only the newest 21 ms. */}
        await op.context.resume?.();
        if(!this.current(op))return false;
        op.ready=true;this.measure(op);
        const replay=payload.retryTranscription?null:this.takeUnplayed();
        if(payload.retryTranscription){
          const pending=this.retryableAudio();
          if(pending)await this.work(op,signal=>this.processAnswer(op,pending.blob,signal,pending.basis));
          else this.listen(op);
        }else if(replay){
          // Approved, shown and never heard in this page session: read it now. Nothing is requested,
          // and no saved turn is spoken on trust.
          await this.work(op,signal=>this.speakApproved(op,replay.text,signal,{kind:replay.kind||"question",basis:replay.basis}));
        }else if(typeof this.options.opening==="function"){
          await this.work(op,async signal=>{
            const basis=sourceSignature(this.options.getSnapshot());
            const start=this.now();
            const result=await this.options.opening({...payload,signal});
            if(result)op.timing={speechEnd:null,endpoint:null,recordingReady:null,transcribed:start,questionReady:this.now(),started:null,kind:"opening"};
            if(result&&this.current(op)&&!signal.aborted&&!op.muted)await this.playReviewed(op,result,basis,signal);
          });
        }else this.listen(op);
        return this.current(op);
      }catch(error){if(this.current(op))await this.fail(op,"The microphone could not start. Check its access, or continue by typing.");return false;}
    }
    // The meter must not depend on animation frames: a hidden or covered page gets none. A hidden
    // page is metered by timer; a visible one by animation frame with a timer behind it, so the
    // meter keeps running whenever frames stop for a reason the page is not told about.
    schedule(op,frame){
      if(global.document?.hidden||!this.raf)op.frame={timer:this.later(frame,global.document?.hidden?HIDDEN_FRAME_MS:33)};
      else op.frame={raf:this.raf(frame),timer:this.later(frame,FRAME_BACKUP_MS)};
    }
    cancelFrame(op){
      const pending=op.frame;op.frame=null;if(!pending)return;
      if(pending.raf!==undefined)this.caf(pending.raf);
      this.unlater(pending.timer);
    }
    // One reading of the microphone. A frame that comes on time reads the newest 21 ms. A late one
    // (a busy, hidden or covered page) reads the long window in 21 ms blocks, so what was said in
    // between is measured, not guessed: how much of it was voiced and how long ago the voice began
    // and ended. A late frame used to count the whole gap as voiced time.
    read(op,elapsed){
      const late=elapsed>FRAME_CREDIT_MS,analyser=late?op.wide:op.analyser,samples=late?op.wideSamples:op.samples,size=op.samples.length,blockMs=size/op.rate*1000;
      // Only the part newer than the previous reading: audio already measured is not counted twice.
      const blocks=late?Math.min(Math.floor(samples.length/size),Math.ceil(elapsed/blockMs)):1,start=samples.length-blocks*size;
      analyser.getFloatTimeDomainData(samples);
      let level=0,voiced=0,first=-1,last=-1;
      for(let block=0;block<blocks;block++){
        let sum=0;for(let index=start+block*size,end=index+size;index<end;index++)sum+=samples[index]*samples[index];
        const rms=Math.sqrt(sum/size);if(rms>level)level=rms;
        if(rms>=SPEECH_LEVEL){voiced++;if(first<0)first=block;last=block;}
      }
      return{level,voicedMs:voiced*blockMs,windowMs:blocks*blockMs,firstAgo:first<0?null:(blocks-1-first)*blockMs,lastAgo:last<0?null:(blocks-1-last)*blockMs};
    }
    measure(op){
      if(!this.current(op)||!op.ready)return;
      const frame=()=>{
        this.cancelFrame(op);if(!this.current(op))return;
        let level=0;
        // Metering stops only while the app holds the microphone closed (playback, the opening
        // question, the completion review), not while an answer is transcribed and its reply prepared.
        if(!op.muted&&(!op.processing||op.overlap)){
          const segment=op.segment,now=this.now(),elapsed=op.frameAt===undefined?0:Math.max(0,now-op.frameAt);
          const reading=this.read(op,elapsed);level=reading.level;
          if(segment&&segment.firstSpeech===null&&!segment.quietHint&&now-segment.startedAt>12000){
            segment.quietHint=true;this.notify("onMicHint","I haven’t detected speech yet. Check the microphone input or speak a little closer.");
          }
          op.frameAt=now;
          if(segment&&!segment.finishing){
            // Time no reading covers is neither speech nor silence.
            const unmeasured=now-segment.readAt-reading.windowMs;segment.readAt=now;
            if(reading.lastAgo!==null){
              if(segment.firstSpeech===null){
                segment.firstSpeech=now-Math.min(reading.firstAgo,elapsed);this.armLimit(op,segment);
                segment.clipped=segment.openedAt!==null&&segment.firstSpeech-segment.openedAt<=CLIPPED_START_MS;
              }
              const tail=Math.min(reading.lastAgo,HANGOVER_MS);
              segment.lastSpeech=now-reading.lastAgo;segment.quietMs=reading.lastAgo;segment.tail=HANGOVER_MS-tail;
              segment.voicedMs+=elapsed>FRAME_CREDIT_MS?Math.min(elapsed,reading.voicedMs+tail):elapsed;
              segment.peak=Math.max(segment.peak,level);
            }else{
              if(segment.tail>0){const credit=Math.min(elapsed,segment.tail);segment.voicedMs+=credit;segment.tail-=credit;}
              // One reading vouches for a bounded stretch of silence, so a turn never ends on a
              // single reading taken after a gap.
              segment.quietMs+=Math.min(elapsed,QUIET_CREDIT_MS);
              if(unmeasured>=UNMEASURED_MS&&segment.firstSpeech===null)this.restartUnmeasured(op);
              // A part saved at the capture bound was not followed by more speech after all.
              else if(op.replyOwed&&!op.processing&&segment.firstSpeech===null&&segment.quietMs>=this.silenceMs){op.replyOwed=false;this.submit(op,signal=>this.requestReply(op,signal),{overlap:true});}
            }
            // The participant went on after the pause that ended the turn: the reply waits for the rest.
            if(op.processing&&!op.continuing&&this.speechLike(segment))this.continueAnswer(op);
            if(segment.firstSpeech!==null&&now-segment.firstSpeech>=MIN_SPEECH_MS&&segment.quietMs>=this.silenceMs){
              if(this.speechLike(segment)){if(!this.turnAwayClipped(op,segment))this.finishSegment(op);}
              else{
                // Too little to be a word. Something close to one is said to have been missed; a
                // click or a breath is dropped without comment. Nothing is sent for transcription.
                const nearMiss=segment.voicedMs>=NEAR_MISS_MS&&!op.processing;
                this.discardSegment(op);this.listen(op);
                if(nearMiss)this.notify("onNotice","I didn’t catch that. Please say a little more.");
              }
            }
          }
        }
        this.notify("onAudioFrame",{input:Math.min(1,level/0.15),output:0,inputActive:level>=SPEECH_LEVEL,outputActive:false,playbackActive:false,muted:op.muted,connected:op.ready});
        if(this.current(op))this.schedule(op,frame);
      };
      op.frameFn=frame;this.schedule(op,frame);
    }
    // A recording that holds only a stretch nobody measured (the page was frozen or its meter could
    // not run) is not sent for transcription and is not dropped in silence either.
    restartUnmeasured(op){
      this.discardSegment(op);this.listen(op);
      this.notify("onNotice","Listening paused while this window was in the background. If you answered then, it was not recorded: please say it again.");
    }
    // The capture bound runs from the first speech, not from when listening began, and it never
    // hands half an answer to the interviewer. At 90 s the participant is told and recording goes
    // on to the pause. After a second 90 s that part is saved and the rest is recorded as more of
    // the same answer: the reply is requested only when the participant pauses.
    armLimit(op,segment){
      segment.limit=this.later(()=>{
        if(!this.current(op)||op.segment!==segment||segment.finishing)return;
        if(!segment.extended){
          segment.extended=true;this.armLimit(op,segment);
          this.notify("onNotice","That’s 90 seconds without a pause. I’m still recording: pause when you’re ready and I’ll reply.");return;
        }
        segment.rolled=true;this.finishSegment(op);
        this.notify("onNotice","That’s three minutes without a pause, the most for one recording. That part is saved and I’m still listening: keep going.");
      },MAX_SEGMENT_MS);
    }
    // Speech already under way when the microphone opened (first heard within CLIPPED_START_MS of
    // it): the beginning was said while the app was not listening, so what was recorded is the tail
    // of an answer. It is not transcribed and the participant is asked to say it again, when that
    // is cheap and they have not just been told: the recorded speech spans at most
    // CLIPPED_REPEAT_MS and their previous start was a clean one. Otherwise it is kept, with a
    // notice that the beginning may be missing, so that someone who habitually starts early, or who
    // went on for a long time, is not turned away turn after turn. Returns true when turned away.
    turnAwayClipped(op,segment){
      if(segment.openedAt===null)return false;
      if(!segment.clipped){op.toldClipped=false;return false;}
      const repeat=!op.toldClipped&&segment.lastSpeech-segment.firstSpeech<=CLIPPED_REPEAT_MS;
      op.toldClipped=true;
      if(!repeat){this.notify("onNotice","You may have started before I was listening. If the beginning is missing, please add it.");return false;}
      this.discardSegment(op);this.listen(op);
      this.notify("onNotice","I wasn’t listening yet when you started, so I missed the beginning. Please say that again.");
      return true;
    }
    speechLike(segment){return segment.voicedMs>=MIN_VOICED_MS||(segment.voicedMs>=SHORT_VOICED_MS&&segment.peak>=STRONG_LEVEL);}
    // More of the same answer is being spoken. A transcription already under way is kept and its
    // text applied; a reply already requested is cancelled and asked for again with the whole answer.
    continueAnswer(op){
      op.continuing=true;
      if(op.stage==="asking")op.workController?.abort();
    }
    listen(op){
      if(!this.current(op)||!op.ready||op.draining||(op.processing&&!op.overlap))return;
      if(op.muted){this.tracks(op,false);this.setStatus("muted");return;}
      // A recording begun while the reply was prepared carries on as the listening one.
      if(op.segment){if(!op.processing)this.setStatus("listening");return;}
      // Only a recording that begins as the microphone reopens can have missed the start of an answer.
      const reopened=!op.stream.getAudioTracks().some(track=>track.enabled);
      this.tracks(op,true);
      try{
        const mime=["audio/webm;codecs=opus","audio/webm","audio/mp4","audio/ogg;codecs=opus"].find(type=>this.Recorder.isTypeSupported?.(type));
        const recorder=new this.Recorder(op.stream,mime?{mimeType:mime}:undefined);
        const segment={recorder,chunks:[],firstSpeech:null,lastSpeech:null,voicedMs:0,quietMs:0,peak:0,tail:0,readAt:this.now(),openedAt:reopened?this.now():null,clipped:false,finishing:false,discard:false,timer:null,limit:null};op.segment=segment;op.frameAt=undefined;
        recorder.addEventListener("dataavailable",event=>{if(!segment.discard&&event.data?.size)segment.chunks.push(event.data);});
        recorder.addEventListener("error",()=>{if(this.current(op))void this.fail(op,"Audio capture did not finish. Earlier answers are still here; continue by typing or reconnect.");});
        recorder.addEventListener("stop",()=>{
          this.unlater(segment.timer);this.unlater(segment.limit);if(op.segment===segment)op.segment=null;
          if(!this.current(op)||segment.discard)return;
          if(segment.firstSpeech===null){segment.chunks=[];this.listen(op);return;}
          const blob=new Blob(segment.chunks,{type:recorder.mimeType||mime||"audio/webm"});segment.chunks=[];
          if(!blob.size){void this.fail(op,"No audio was captured. Earlier answers are still here; continue by typing or reconnect.");return;}
          const timing={speechEnd:segment.lastSpeech,endpoint:segment.endpoint,recordingReady:this.now(),started:null};
          this.notify("onEndpoint");
          this.submit(op,signal=>{op.timing=timing;return this.processAnswer(op,blob,signal,null,{rolled:segment.rolled===true});},{overlap:true});
        });
        segment.startedAt=this.now();recorder.start(1000);
        // This timer only keeps an idle microphone from retaining unlimited silence: it replaces a
        // recorder in which nothing was said and never triggers provider work. Once speech has
        // begun, the bound armed by that speech applies instead (armLimit).
        segment.timer=this.later(()=>{
          if(!this.current(op)||op.segment!==segment||segment.firstSpeech!==null)return;
          if(this.now()-segment.readAt>=UNMEASURED_MS)this.restartUnmeasured(op);
          else this.finishSegment(op);
        },MAX_SEGMENT_MS);
        if(!op.processing)this.setStatus("listening");
      }catch{void this.fail(op,"Audio recording could not start. Continue by typing.");}
    }
    // The microphone is not closed here: it stays open until the reply is about to be spoken, so
    // that an answer continued after a pause is still captured (see work and holdMicrophone).
    finishSegment(op){
      const segment=op.segment;if(!this.current(op)||!segment||segment.finishing)return;
      segment.finishing=true;segment.endpoint=this.now();this.unlater(segment.timer);this.unlater(segment.limit);
      try{if(segment.recorder.state!=="inactive")segment.recorder.stop();}catch{void this.fail(op,"Audio capture could not finish. Earlier answers are still here.");}
    }
    discardSegment(op){
      const segment=op.segment;if(!segment)return;
      segment.discard=true;segment.chunks=[];this.unlater(segment.timer);this.unlater(segment.limit);op.segment=null;
      try{if(segment.recorder.state!=="inactive")segment.recorder.stop();}catch{}
    }
    // Playback must never pick up the microphone, and nothing said after the reply is committed can
    // still change it: capture closes here, an unfinished noise is dropped.
    holdMicrophone(op){op.overlap=false;op.stage="speaking";this.discardSegment(op);this.tracks(op,false);}
    // One recording is processed at a time; a later one waits its turn instead of being dropped.
    submit(op,task,options){if(op.processing)op.queue.push({task,options});else void this.work(op,task,options);}
    async work(op,task,{overlap=false}={}){
      if(!this.current(op)||op.processing||(op.muted&&!overlap))return;
      op.processing=true;op.overlap=overlap;op.stage=null;
      // An answer's own work keeps capturing (overlap); every other kind closes the microphone.
      if(overlap)this.listen(op);else this.tracks(op,false);
      this.setStatus("processing");
      const controller=new AbortController();op.workController=controller;
      const abort=()=>controller.abort();op.controller.signal.addEventListener("abort",abort,{once:true});
      try{await task(controller.signal);}
      catch(error){if(this.current(op)&&!controller.signal.aborted){if(op.timing)op.timing.failure=op.stage==="transcribing"?"transcription_failed":"reply_failed";await this.fail(op,error?.voiceMessage||"The review could not finish. "+(typeof error?.message==="string"&&error.message.trim()?error.message.trim()+" ":"")+"Your answers are still here. Continue by typing or reconnect.");}}
      finally{
        op.speechPreparation?.dispose();op.speechPreparation=null;
        if(op.timing){
          const t=op.timing,delta=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)?Math.max(0,Math.round(b-a)):null;
          this.notify("onTurnTiming",{endpoint_ms:delta(t.speechEnd,t.endpoint),recording_ms:delta(t.endpoint,t.recordingReady),
            transcription_ms:delta(t.transcriptionStart,t.transcribed),question_ms:delta(t.transcribed,t.questionReady),
            playback_preparation_ms:delta(t.questionReady,t.started),speech_end_to_meaningful_audio_ms:delta(t.speechEnd,t.started),
            playback_ms:delta(t.started,t.playbackEnd),outcome:t.failure||(t.playbackEnd!==undefined&&t.started!==null?"played":controller.signal.aborted?"cancelled":"incomplete"),
            kind:t.kind||"unknown",measurement:"browser_events",physical_audio_verified:false});
          op.timing=null;
        }
        op.controller.signal.removeEventListener("abort",abort);
        if(op.workController===controller){op.workController=null;op.processing=false;op.overlap=false;op.stage=null;}
        if(this.current(op)){const next=op.queue.shift();if(next)void this.work(op,next.task,next.options);else if(op.draining&&!op.segment?.finishing)op.drained?.();else this.listen(op);}
      }
    }
    recoverEmptyTranscript(op,blob){
      op.emptyTranscripts=(op.emptyTranscripts||0)+1;
      const message="I didn’t catch that. No speech was recognized in that recording. The microphone is still listening. Repeat your answer, retry the recording, or choose Stop talking and type it.";
      const retained=this.retainAudio(blob,"no_speech",message);
      if(op.emptyTranscripts>=MAX_EMPTY_TRANSCRIPTS){const error=new Error("Empty transcription");error.voiceMessage="I could not make out an answer several times in a row. Earlier answers are still here. Check the microphone and retry the recording, reconnect, or type it.";throw error;}
      this.notify("onNotice",retained?message:"No speech was recognized. This recording exceeds the in-memory retry limit. The microphone is still listening; repeat your answer or choose Stop talking and type it.");
    }
    async processAnswer(op,blob,signal,retryBasis=null,{rolled=false}={}){
      op.timing=op.timing||{speechEnd:null,endpoint:null,recordingReady:this.now(),started:null};
      op.timing.transcriptionStart=this.now();
      op.continuing=false;op.replyOwed=false;op.stage="transcribing";
      // A recording that follows an answer still waiting for its reply is more of that answer. If
      // it holds no words after all, the reply to what is already there must still be requested.
      const continuation=op.openAnswer&&!retryBasis;
      try{op.speechPreparation=this.options.prepareSpeech?.({signal});}catch{/* Preparation is optional. */}
      let transcript;
      op.currentAudio=blob;
      try{transcript=await this.options.request("/api/transcribe",blob,{signal});}
      catch(cause){
        if(!this.current(op)||signal.aborted)return;
        if(retryBasis&&retryBasis!==sourceSignature(this.options.getSnapshot())){
          this.discardPendingAudio();this.notify("onError","The interview changed while that recording was retried. Please repeat the answer or type it so it is added in the right place.");return;
        }
        const detail=String(cause?.message||""),noSpeech=/no speech was recognized|recording is empty or too short/i.test(detail);
        let message=noSpeech?"No speech was recognized in that recording. The microphone is still listening. Repeat your answer, retry the recording, or choose Stop talking and type it.":
          /no available API quota|credit.balance|insufficient.quota/i.test(detail)?"Transcription is unavailable because this API project has no available quota. Check its billing and usage limits, then retry the recording.":
          /rejected this key|project permissions|credentials/i.test(detail)?"The transcription key or its project permissions were rejected. Check the app's API configuration, then retry the recording.":
          /rate limit|requests are already processing/i.test(detail)?"Transcription was temporarily rate limited. Wait briefly, then retry the recording.":
          /configured model is unavailable/i.test(detail)?"The configured transcription model is unavailable to this API project. Check its model access, then retry the recording.":
          /timed out|network|connection|resolve|secure connection/i.test(detail)?"The transcription connection did not finish. Check the connection, then retry the recording.":
          "I could not transcribe that recording. Earlier transcript answers are retained. Retry the recording, repeat your answer, or type it.";
        if(noSpeech&&!continuation){this.recoverEmptyTranscript(op,blob);return;}
        if(!noSpeech){
          const retained=this.retainAudio(blob,"request_failed",message);
          if(!retained)message=message.replace(/retry the recording,?\s*(?:or\s*)?/gi,"")+" This recording exceeds the in-memory retry limit; please repeat it or type it.";
          const error=new Error("Transcription failed");error.voiceMessage=message;throw error;
        }
        transcript=null;
      }
      if(!this.current(op)||signal.aborted)return;
      op.currentAudio=null;
      if(retryBasis&&retryBasis!==sourceSignature(this.options.getSnapshot())){
        this.discardPendingAudio();this.notify("onError","The interview changed while that recording was retried. Please repeat the answer or type it so it is added in the right place.");return;
      }
      const text=typeof transcript?.text==="string"?transcript.text.trim():"";
      if(text){
        op.emptyTranscripts=0;
        if(this.options.reviewBeforeSending?.()){
          this.notify("onEditableAnswer",text);await this.stop({immediate:true});return;
        }
        this.options.onAnswer(text,{continuation});
        op.openAnswer=true;
        op.timing.transcribed=this.now();
        this.discardPendingAudio();
      }else if(!continuation){
        this.recoverEmptyTranscript(op,blob);return;
      }
      if(!this.current(op)||signal.aborted||op.muted||op.draining)return;
      // Still speaking: the recording in progress is transcribed next and the reply follows it.
      if(op.continuing)return;
      // Saved at the capture bound in mid-speech: the reply waits for the rest, or for the pause
      // that shows there is no more (measure requests it then).
      if(rolled){op.replyOwed=true;return;}
      await this.requestReply(op,signal);
    }
    async requestReply(op,signal){
      op.continuing=false;op.replyOwed=false;op.stage="asking";
      const snapshot=this.options.getSnapshot(),basis=sourceSignature(snapshot);
      const result=await this.options.request("/api/interview",{...snapshot,action:"answer"},{signal});
      if(op.timing)op.timing.questionReady=this.now();
      if(!this.current(op)||signal.aborted)return;
      if(op.muted){op.mutedReply={result,basis};return;}
      await this.playReviewed(op,result,basis,signal);
    }
    async playReviewed(op,result,basis,signal){
      if(!this.current(op)||signal.aborted||op.muted)return;
      const authorization=result?.speech_authorization;
      if(typeof result?.question!=="string"||!result.question.trim()||result.question.length>6000||authorization?.approved!==true||!KINDS.has(authorization.kind)||authorization.text!==result.question||typeof authorization.revision!=="string"||!/^[A-Za-z0-9_.:-]{1,128}$/.test(authorization.revision)){
        const error=new Error("Unapproved speech");error.voiceMessage="The response did not pass the speech check, so it was not spoken. Your answers are still here; continue by typing or reconnect.";throw error;
      }
      if((authorization.kind==="final_check"&&result.completion?.ready_for_final_check!==true)||
         (authorization.kind==="complete"&&(result.completion?.complete!==true||authorization.completion_allowed!==true))){
        const error=new Error("Inconsistent completion authorization");error.voiceMessage="The response did not pass the completion check, so it was not spoken. Your answers are still here; continue by typing or reconnect.";throw error;
      }
      if(authorization.kind==="review_pending"&&((result.question!==REVIEW_ACK&&!(result.review_purpose==="partial"&&result.question===PARTIAL_REVIEW_ACK))||typeof result.review_ticket!=="string"||!result.review_ticket||result.review_ticket.length>4096||result.coverage_verified===true||result.completion?.complete===true||result.completion?.ready_for_final_check===true))throw new Error("Invalid review acknowledgement");
      if(sourceSignature(this.options.getSnapshot())!==basis){const error=new Error("Stale response");error.voiceMessage="The conversation changed while the response was being reviewed. That earlier response was not spoken. Continue by typing or reconnect.";throw error;}
      this.holdMicrophone(op);
      this.options.onResult(result);op.openAnswer=false;
      // A courtesy after the completion line changed nothing: the line was spoken
      // when the account was completed and is not spoken again.
      if(authorization.kind==="complete"&&result.completion_retained===true){await this.stop({immediate:true});return;}
      const appliedBasis=sourceSignature(this.options.getSnapshot());
      if(!this.current(op)||signal.aborted||op.muted)return;
      // Only an ordinary question is worth reading again after a reconnect.
      const replayable=authorization.kind==="question"||authorization.kind==="final_check";
      await this.speakApproved(op,result.question,signal,{kind:authorization.kind,basis:replayable?appliedBasis:null});
      if(!this.current(op)||signal.aborted||op.muted)return;
      if(authorization.kind==="review_pending"){
        // The acknowledgement must be over (heard, or failed and left on screen) before the
        // specialist review starts. Keep the microphone closed throughout both stages.
        if(sourceSignature(this.options.getSnapshot())!==appliedBasis){const error=new Error("Stale acknowledgement");error.voiceMessage="The conversation changed before the review could start. Your answers are still here; continue by typing or reconnect.";throw error;}
        this.options.onReviewAcknowledged?.(result);
        const snapshot=this.options.getSnapshot(),reviewBasis=appliedBasis;
        this.setStatus("processing");
        const reviewed=typeof this.options.review==="function"?await this.options.review(result,{signal}):
          await this.options.request("/api/agent-team/review",{...snapshot,review_ticket:result.review_ticket},{signal});
        if(!this.current(op)||signal.aborted||op.muted)return;
        if(reviewed?.speech_authorization?.kind==="review_pending")throw new Error("Review did not return a decision");
        await this.playReviewed(op,reviewed,reviewBasis,signal);
        return;
      }
      if(authorization.kind==="complete"||authorization.kind==="pause")await this.stop({immediate:true});
    }
    // Reads text that passed the speech check and is already in the transcript. A failure here is a
    // playback problem only: the question has been asked on screen, so the participant is told why
    // it was not heard and the session goes on. A question that never became audible is remembered
    // (in this page session only) and read when voice is next started, if the interview has not
    // changed. Returns whether it was played to the end.
    async speakApproved(op,text,signal,{kind,basis=null}={}){
      global.CollectorRawTrace?.record("reviewed.playback_requested",{kind},{text});
      const pending=basis===null?null:{text,kind,basis,started:false};this.unplayed=pending;
      this.setStatus("speaking");
      try{
        if(op.timing)op.timing.kind=kind;
        const playback=this.options.speak(text,{signal,preparation:op.speechPreparation,onPlaybackStart:()=>{
          global.CollectorRawTrace?.record("reviewed.playback_started",{kind});
          if(pending)pending.started=true;
          // A review acknowledgement is filler, never meaningful-response latency.
          if(this.current(op)&&!signal.aborted&&op.timing&&kind!=="review_pending"&&op.timing.started===null)op.timing.started=this.now();
        }});
        if(!playback||typeof playback.then!=="function")throw new Error("Playback must report its completion");
        await playback;
        global.CollectorRawTrace?.record("reviewed.playback_completed",{kind});
        if(op.timing&&kind!=="review_pending")op.timing.playbackEnd=this.now();
        if(this.unplayed===pending)this.unplayed=null;
        return true;
      }catch(cause){
        global.CollectorRawTrace?.record("reviewed.playback_rejected",{kind,aborted:signal.aborted});
        // Stopped on purpose. What the participant heard begin is not read again.
        if(!this.current(op)||signal.aborted){if(pending?.started&&this.unplayed===pending)this.unplayed=null;return false;}
        // An acknowledgement that was not heard is on screen and is followed by the reviewed line.
        if(kind!=="review_pending"){
          if(op.timing)op.timing.failure="playback_failed";
          // Only wording written by the app is shown; a browser or provider detail is not.
          const reason=typeof cause?.voiceMessage==="string"&&cause.voiceMessage.trim()?cause.voiceMessage.trim():"The interviewer’s voice could not play this question; it is on screen.";
          this.notify(typeof this.options.onPlaybackProblem==="function"?"onPlaybackProblem":"onNotice",kind==="complete"||kind==="pause"?reason:reason+" I’m listening for your answer.");
        }
        return false;
      }
    }
    rememberUnplayed(result){
      const authorization=result?.speech_authorization,snapshot=this.options.getSnapshot();
      if(this.active||!["question","final_check"].includes(authorization?.kind)||authorization.approved!==true||
         typeof result.question!=="string"||!result.question.trim()||result.question.length>6000||authorization.text!==result.question||
         typeof authorization.revision!=="string"||!/^[A-Za-z0-9_.:-]{1,128}$/.test(authorization.revision)||
         authorization.kind==="final_check"&&result.completion?.ready_for_final_check!==true)return;
      const last=snapshot.turns?.at(-1);
      if(last?.role==="assistant"&&last.text===result.question)this.unplayed={text:result.question,kind:authorization.kind,basis:sourceSignature(snapshot),started:false};
    }
    takeUnplayed(){
      const pending=this.unplayed;this.unplayed=null;
      return pending&&pending.basis===sourceSignature(this.options.getSnapshot())?pending:null;
    }
    setMuted(muted){
      const op=this.operation;if(!this.current(op))return false;
      op.muted=Boolean(muted);
      if(op.muted){this.tracks(op,false);if(op.segment&&this.speechLike(op.segment))this.finishSegment(op);else this.discardSegment(op);this.setStatus("muted");}
      else if(op.ready&&!op.processing&&op.mutedReply){
        const {result,basis}=op.mutedReply;op.mutedReply=null;
        void this.work(op,signal=>this.playReviewed(op,result,basis,signal));
      }
      else if(op.ready&&!op.processing&&op.openAnswer)void this.work(op,signal=>this.requestReply(op,signal));
      else if(op.ready&&!op.processing)this.listen(op);
      else this.setStatus(op.ready?"processing":"connecting");
      return true;
    }
    toggleMute(){const op=this.operation;return op?this.setMuted(!op.muted):false;}
    appendContext(_text,{id,kind="document_findings"}={}){return Promise.resolve({id:id??null,kind,status:this.active?"acknowledged":"unavailable",reason:this.active?"server_snapshot_used":"session_inactive"});}
    async fail(op,message){if(!this.current(op))return;this.notify("onError",message);await this.stop({immediate:true});}
    async stop({immediate=false}={}){
      const op=this.operation;if(!op)return{finalized:true};
      if(!immediate&&(op.segment?.finishing||op.segment&&this.speechLike(op.segment)||op.stage==="transcribing"||op.queue.length)){
        if(op.stopPromise)return op.stopPromise;
        op.draining=true;this.tracks(op,false);this.setStatus("closing");
        let timer;
        const done=new Promise(resolve=>{op.drained=resolve;timer=this.later(()=>resolve(false),30000);});
        if(op.segment&&!op.segment.finishing){if(this.speechLike(op.segment))this.finishSegment(op);else this.discardSegment(op);}
        op.stopPromise=done.then(async finalized=>{
          this.unlater(timer);
          if(finalized===false&&op.currentAudio)this.retainAudio(op.currentAudio,"interrupted","The final recording can be retried before continuing.");
          if(this.operation===op)await this.stop({immediate:true});
          return {finalized:finalized!==false};
        });
        return op.stopPromise;
      }
      op.drained?.();
      op.closing=true;this.operation=null;op.controller.abort();op.workController?.abort();this.tracks(op,false);this.discardSegment(op);
      this.cancelFrame(op);
      try{this.options.stopPlayback?.();}catch{}
      op.stream?.getTracks().forEach(track=>track.stop());
      try{op.source?.disconnect();}catch{}
      try{await op.context?.close();}catch{}
      if(!this.operation){this.setStatus("idle");this.notify("onAudioFrame",{input:0,output:0,inputActive:false,outputActive:false,playbackActive:false,muted:false,connected:false});}
      return{finalized:true};
    }
    async dispose(){global.removeEventListener?.("pagehide",this.hide);global.document?.removeEventListener?.("visibilitychange",this.visibility);this.discardPendingAudio();return this.stop({immediate:true});}
  }
  global.CollectorControlledVoice=CollectorControlledVoice;
  global.CollectorSpeechPreparation=CollectorSpeechPreparation;
})(window);
