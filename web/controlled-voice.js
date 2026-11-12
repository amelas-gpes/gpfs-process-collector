/* One reviewed interviewer voice. Local audio capture -> transcript -> reviewed
 * interview response -> authorized playback. No direct model-to-speaker path. */
(function (global) {
  "use strict";
  const SILENCE_MS=1800, MIN_SPEECH_MS=550, MIN_VOICED_MS=250, MAX_SEGMENT_MS=90000, MAX_EMPTY_TRANSCRIPTS=3;
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
      this.timer=later(()=>this.dispose(),60000);
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
      this.options=options;this.operation=null;this.sequence=0;this.status="idle";this.pendingAudio=null;this.pendingAudioTimer=null;
      this.mediaDevices=options.mediaDevices||global.navigator?.mediaDevices;
      this.Recorder=options.MediaRecorder||global.MediaRecorder;
      this.Context=options.AudioContext||global.AudioContext||global.webkitAudioContext;
      this.now=options.now||(()=>global.performance?.now?.()??Date.now());
      this.raf=options.requestAnimationFrame||(fn=>global.requestAnimationFrame(fn));
      this.caf=options.cancelAnimationFrame||(id=>global.cancelAnimationFrame(id));
      this.later=options.setTimeout||((fn,ms)=>global.setTimeout(fn,ms));
      this.unlater=options.clearTimeout||(id=>global.clearTimeout(id));
      this.hide=()=>{this.discardPendingAudio();void this.stop({immediate:true});};
      global.addEventListener?.("pagehide",this.hide);
    }
    get active(){return Boolean(this.operation&&!this.operation.closing);}
    get connected(){return Boolean(this.operation?.ready&&!this.operation.closing);}
    get hasPendingAudio(){return Boolean(this.pendingAudio);}
    notify(name,value){try{this.options[name]?.(value);}catch{/* Display callbacks cannot bypass cleanup. */}}
    current(op){return this.operation===op&&!op.closing&&!op.controller.signal.aborted;}
    setStatus(status){this.status=status;this.notify("onStatus",status);}
    tracks(op,enabled){op.stream?.getAudioTracks().forEach(track=>{track.enabled=enabled;});}
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
      const op={id:++this.sequence,controller:new AbortController(),stream:null,context:null,source:null,analyser:null,frame:null,segment:null,ready:false,muted:false,processing:false,closing:false,workController:null};
      this.operation=op;this.setStatus("connecting");
      try{
        const stream=await this.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
        if(!this.current(op)){stream.getTracks().forEach(track=>track.stop());return false;}
        op.stream=stream;this.tracks(op,false);
        op.context=new this.Context();op.source=op.context.createMediaStreamSource(stream);op.analyser=op.context.createAnalyser();op.analyser.fftSize=1024;op.source.connect(op.analyser);op.samples=new Float32Array(op.analyser.fftSize);
        await op.context.resume?.();
        if(!this.current(op))return false;
        op.ready=true;this.measure(op);
        if(payload.retryTranscription){
          const pending=this.retryableAudio();
          if(pending)await this.work(op,signal=>this.processAnswer(op,pending.blob,signal,pending.basis));
          else this.listen(op);
        }else if(typeof this.options.opening==="function"){
          await this.work(op,async signal=>{
            const basis=sourceSignature(this.options.getSnapshot());
            const result=await this.options.opening({...payload,signal});
            if(result&&this.current(op)&&!signal.aborted&&!op.muted)await this.playReviewed(op,result,basis,signal);
          });
        }else this.listen(op);
        return this.current(op);
      }catch(error){if(this.current(op))await this.fail(op,"The microphone could not start. Check its access, or continue by typing.");return false;}
    }
    measure(op){
      if(!this.current(op)||!op.ready)return;
      const frame=()=>{
        op.frame=null;if(!this.current(op))return;
        let level=0;
        if(!op.muted&&!op.processing){
          op.analyser.getFloatTimeDomainData(op.samples);
          level=Math.sqrt(op.samples.reduce((sum,value)=>sum+value*value,0)/op.samples.length);
          const segment=op.segment,now=this.now(),elapsed=op.frameAt===undefined?0:Math.max(0,now-op.frameAt);
          op.frameAt=now;
          if(segment&&!segment.finishing){
            if(level>=0.022){if(segment.firstSpeech===null)segment.firstSpeech=now;segment.lastSpeech=now;segment.voicedMs+=elapsed;}
            if(segment.firstSpeech!==null&&now-segment.firstSpeech>=MIN_SPEECH_MS&&now-segment.lastSpeech>=SILENCE_MS){
              if(segment.voicedMs>=MIN_VOICED_MS)this.finishSegment(op);
              else{this.discardSegment(op);this.listen(op);}
            }
          }
        }
        this.notify("onAudioFrame",{input:Math.min(1,level/0.15),output:0,inputActive:level>=0.022,outputActive:false,playbackActive:false,muted:op.muted,connected:op.ready});
        if(this.current(op))op.frame=this.raf(frame);
      };
      op.frame=this.raf(frame);
    }
    listen(op){
      if(!this.current(op)||!op.ready||op.processing)return;
      if(op.muted){this.tracks(op,false);this.setStatus("muted");return;}
      if(op.segment)return;
      this.tracks(op,true);
      try{
        const mime=["audio/webm;codecs=opus","audio/webm","audio/mp4","audio/ogg;codecs=opus"].find(type=>this.Recorder.isTypeSupported?.(type));
        const recorder=new this.Recorder(op.stream,mime?{mimeType:mime}:undefined);
        const segment={recorder,chunks:[],firstSpeech:null,lastSpeech:null,voicedMs:0,finishing:false,discard:false,timer:null};op.segment=segment;op.frameAt=undefined;
        recorder.addEventListener("dataavailable",event=>{if(!segment.discard&&event.data?.size)segment.chunks.push(event.data);});
        recorder.addEventListener("error",()=>{if(this.current(op))void this.fail(op,"Audio capture did not finish. Earlier answers are saved; continue by typing or reconnect.");});
        recorder.addEventListener("stop",()=>{
          this.unlater(segment.timer);if(op.segment===segment)op.segment=null;
          if(!this.current(op)||segment.discard)return;
          if(segment.firstSpeech===null){segment.chunks=[];this.listen(op);return;}
          const blob=new Blob(segment.chunks,{type:recorder.mimeType||mime||"audio/webm"});segment.chunks=[];
          if(!blob.size){void this.fail(op,"No audio was captured. Earlier answers are saved; continue by typing or reconnect.");return;}
          op.timing={speechEnd:segment.lastSpeech,endpoint:segment.endpoint,recordingReady:this.now(),started:null};
          void this.work(op,signal=>this.processAnswer(op,blob,signal));
        });
        recorder.start(1000);
        // A real capture bound also prevents an idle microphone from retaining
        // unlimited silence. It never triggers provider work without speech.
        segment.timer=this.later(()=>{if(this.current(op)&&op.segment===segment)this.finishSegment(op);},MAX_SEGMENT_MS);
        this.setStatus("listening");
      }catch{void this.fail(op,"Audio recording could not start. Continue by typing.");}
    }
    finishSegment(op){
      const segment=op.segment;if(!this.current(op)||!segment||segment.finishing||op.muted)return;
      segment.finishing=true;segment.endpoint=this.now();this.unlater(segment.timer);this.tracks(op,false);
      try{if(segment.recorder.state!=="inactive")segment.recorder.stop();}catch{void this.fail(op,"Audio capture could not finish. Earlier answers are saved.");}
    }
    discardSegment(op){
      const segment=op.segment;if(!segment)return;
      segment.discard=true;segment.chunks=[];this.unlater(segment.timer);op.segment=null;
      try{if(segment.recorder.state!=="inactive")segment.recorder.stop();}catch{}
    }
    async work(op,task){
      if(!this.current(op)||op.processing||op.muted)return;
      op.processing=true;this.tracks(op,false);this.setStatus("processing");
      const controller=new AbortController();op.workController=controller;
      const abort=()=>controller.abort();op.controller.signal.addEventListener("abort",abort,{once:true});
      try{await task(controller.signal);}
      catch(error){if(this.current(op)&&!controller.signal.aborted)await this.fail(op,error?.voiceMessage||"The review could not finish. "+(typeof error?.message==="string"&&error.message.trim()?error.message.trim()+" ":"")+"Your saved answers are retained. Continue by typing or reconnect.");}
      finally{
        op.speechPreparation?.dispose();op.speechPreparation=null;
        if(op.timing){
          const t=op.timing,delta=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)?Math.max(0,Math.round(b-a)):null;
          this.notify("onTurnTiming",{endpoint_ms:delta(t.speechEnd,t.endpoint),recording_ms:delta(t.endpoint,t.recordingReady),
            transcription_ms:delta(t.transcriptionStart,t.transcribed),question_ms:delta(t.transcribed,t.questionReady),
            playback_preparation_ms:delta(t.questionReady,t.started),speech_end_to_meaningful_audio_ms:delta(t.speechEnd,t.started),
            playback_ms:delta(t.started,t.playbackEnd),outcome:t.playbackEnd!==undefined&&t.started!==null?"played":controller.signal.aborted?"cancelled":"incomplete",
            kind:t.kind||"unknown",measurement:"browser_events",physical_audio_verified:false});
          op.timing=null;
        }
        op.controller.signal.removeEventListener("abort",abort);
        if(op.workController===controller){op.workController=null;op.processing=false;}
        if(this.current(op))this.listen(op);
      }
    }
    recoverEmptyTranscript(op,blob){
      op.emptyTranscripts=(op.emptyTranscripts||0)+1;
      const message="I didn’t catch that. No speech was recognized in that recording. The microphone is still listening. Repeat your answer, retry the recording, or stop voice and type it.";
      const retained=this.retainAudio(blob,"no_speech",message);
      if(op.emptyTranscripts>=MAX_EMPTY_TRANSCRIPTS){const error=new Error("Empty transcription");error.voiceMessage="I could not make out an answer several times in a row. Earlier answers are saved. Check the microphone and retry the recording, reconnect, or type it.";throw error;}
      this.notify("onNotice",retained?message:"No speech was recognized. This recording exceeds the in-memory retry limit. The microphone is still listening; repeat your answer or stop voice and type it.");
    }
    async processAnswer(op,blob,signal,retryBasis=null){
      op.timing=op.timing||{speechEnd:null,endpoint:null,recordingReady:this.now(),started:null};
      op.timing.transcriptionStart=this.now();
      try{op.speechPreparation=this.options.prepareSpeech?.({signal});}catch{/* Preparation is optional. */}
      let transcript;
      try{transcript=await this.options.request("/api/transcribe",blob,{signal});}
      catch(cause){
        if(!this.current(op)||signal.aborted||op.muted)return;
        if(retryBasis&&retryBasis!==sourceSignature(this.options.getSnapshot())){
          this.discardPendingAudio();this.notify("onError","The interview changed while that recording was retried. Please repeat the answer or type it so it is added in the right place.");return;
        }
        const detail=String(cause?.message||""),noSpeech=/no speech was recognized|recording is empty or too short/i.test(detail);
        let message=noSpeech?"No speech was recognized in that recording. The microphone is still listening. Repeat your answer, retry the recording, or stop voice and type it.":
          /no available API quota|credit.balance|insufficient.quota/i.test(detail)?"Transcription is unavailable because this API project has no available quota. Check its billing and usage limits, then retry the recording.":
          /rejected this key|project permissions|credentials/i.test(detail)?"The transcription key or its project permissions were rejected. Check the app's API configuration, then retry the recording.":
          /rate limit|requests are already processing/i.test(detail)?"Transcription was temporarily rate limited. Wait briefly, then retry the recording.":
          /configured model is unavailable/i.test(detail)?"The configured transcription model is unavailable to this API project. Check its model access, then retry the recording.":
          /timed out|network|connection|resolve|secure connection/i.test(detail)?"The transcription connection did not finish. Check the connection, then retry the recording.":
          "I could not transcribe that recording. Earlier transcript answers are retained. Retry the recording, repeat your answer, or type it.";
        if(noSpeech){this.recoverEmptyTranscript(op,blob);return;}
        const retained=this.retainAudio(blob,"request_failed",message);
        if(!retained)message=message.replace(/retry the recording,?\s*(?:or\s*)?/gi,"")+" This recording exceeds the in-memory retry limit; please repeat it or type it.";
        const error=new Error("Transcription failed");error.voiceMessage=message;throw error;
      }
      if(!this.current(op)||signal.aborted||op.muted)return;
      if(retryBasis&&retryBasis!==sourceSignature(this.options.getSnapshot())){
        this.discardPendingAudio();this.notify("onError","The interview changed while that recording was retried. Please repeat the answer or type it so it is added in the right place.");return;
      }
      const text=typeof transcript?.text==="string"?transcript.text.trim():"";
      if(!text){
        this.recoverEmptyTranscript(op,blob);return;
      }
      op.emptyTranscripts=0;
      this.options.onAnswer(text);
      op.timing.transcribed=this.now();
      this.discardPendingAudio();
      if(!this.current(op)||signal.aborted||op.muted)return;
      const snapshot=this.options.getSnapshot(),basis=sourceSignature(snapshot);
      const result=await this.options.request("/api/interview",{...snapshot,action:"answer"},{signal});
      op.timing.questionReady=this.now();
      if(!this.current(op)||signal.aborted||op.muted)return;
      await this.playReviewed(op,result,basis,signal);
    }
    static authorization(result){
      const authorization=result?.speech_authorization;
      if(typeof result?.question!=="string"||!result.question.trim()||result.question.length>6000||authorization?.approved!==true||!KINDS.has(authorization.kind)||authorization.text!==result.question||typeof authorization.revision!=="string"||!/^[A-Za-z0-9_.:-]{1,128}$/.test(authorization.revision)){
        const error=new Error("Unapproved speech");error.voiceMessage="The response did not pass the speech check, so it was not spoken. Your answers are saved; continue by typing or reconnect.";throw error;
      }
      if((["final_check","complete"].includes(authorization.kind)&&result.coverage_verified!==true)||
         (authorization.kind==="final_check"&&result.completion?.ready_for_final_check!==true)||
         (authorization.kind==="complete"&&(result.completion?.complete!==true||authorization.completion_allowed!==true))){
        const error=new Error("Inconsistent completion authorization");error.voiceMessage="The response did not pass the completion check, so it was not spoken. Your answers are saved; continue by typing or reconnect.";throw error;
      }
      if(authorization.kind==="review_pending"&&((result.question!==REVIEW_ACK&&!(result.review_purpose==="partial"&&result.question===PARTIAL_REVIEW_ACK))||typeof result.review_ticket!=="string"||!result.review_ticket||result.review_ticket.length>4096||result.coverage_verified===true||result.completion?.complete===true||result.completion?.ready_for_final_check===true))throw new Error("Invalid review acknowledgement");
      return authorization;
    }
    async playReviewed(op,result,basis,signal){
      if(!this.current(op)||signal.aborted||op.muted)return;
      const authorization=CollectorControlledVoice.authorization(result);
      if(sourceSignature(this.options.getSnapshot())!==basis){const error=new Error("Stale response");error.voiceMessage="The conversation changed while the response was being reviewed. That earlier response was not spoken. Continue by typing or reconnect.";throw error;}
      this.options.onResult(result);
      const appliedBasis=sourceSignature(this.options.getSnapshot());
      if(!this.current(op)||signal.aborted||op.muted)return;
      this.setStatus("speaking");
      try{
        if(op.timing)op.timing.kind=authorization.kind;
        const playback=this.options.speak(result.question,{signal,preparation:op.speechPreparation,onPlaybackStart:()=>{
          // A review acknowledgement is filler, never meaningful-response latency.
          if(this.current(op)&&!signal.aborted&&op.timing&&authorization.kind!=="review_pending"&&op.timing.started===null)op.timing.started=this.now();
        }});
        if(!playback||typeof playback.then!=="function")throw new Error("Playback must report its completion");
        await playback;
        if(op.timing&&authorization.kind!=="review_pending")op.timing.playbackEnd=this.now();
      }catch{const error=new Error("Playback failed");error.voiceMessage="The reviewed response is saved, but voice playback did not finish. Continue by typing or reconnect.";throw error;}
      if(!this.current(op)||signal.aborted||op.muted)return;
      if(authorization.kind==="review_pending"){
        // The acknowledgement must finish audibly before the specialist review
        // starts. Keep the microphone closed throughout both stages.
        if(sourceSignature(this.options.getSnapshot())!==appliedBasis){const error=new Error("Stale acknowledgement");error.voiceMessage="The conversation changed before the review could start. Your answers are saved; continue by typing or reconnect.";throw error;}
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
    setMuted(muted){
      const op=this.operation;if(!this.current(op))return false;
      op.muted=Boolean(muted);
      if(op.muted){this.tracks(op,false);this.discardSegment(op);op.workController?.abort();try{this.options.stopPlayback?.();}catch{}this.setStatus("muted");}
      else if(op.ready&&!op.processing)this.listen(op);
      else this.setStatus(op.ready?"processing":"connecting");
      return true;
    }
    toggleMute(){const op=this.operation;return op?this.setMuted(!op.muted):false;}
    appendContext(_text,{id,kind="document_findings"}={}){return Promise.resolve({id:id??null,kind,status:this.active?"acknowledged":"unavailable",reason:this.active?"server_snapshot_used":"session_inactive"});}
    async fail(op,message){if(!this.current(op))return;this.notify("onError",message);await this.stop({immediate:true});}
    async stop(_options={}){
      const op=this.operation;if(!op)return{finalized:true};
      op.closing=true;this.operation=null;op.controller.abort();op.workController?.abort();this.tracks(op,false);this.discardSegment(op);
      if(op.frame!==null)this.caf(op.frame);
      try{this.options.stopPlayback?.();}catch{}
      op.stream?.getTracks().forEach(track=>track.stop());
      try{op.source?.disconnect();}catch{}
      try{await op.context?.close();}catch{}
      if(!this.operation){this.setStatus("idle");this.notify("onAudioFrame",{input:0,output:0,inputActive:false,outputActive:false,playbackActive:false,muted:false,connected:false});}
      return{finalized:true};
    }
    async dispose(){global.removeEventListener?.("pagehide",this.hide);this.discardPendingAudio();return this.stop({immediate:true});}
  }
  global.CollectorSpeechAuthorization=CollectorControlledVoice.authorization;
  global.CollectorControlledVoice=CollectorControlledVoice;
  global.CollectorSpeechPreparation=CollectorSpeechPreparation;
})(window);
