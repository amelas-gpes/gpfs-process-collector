/* One reviewed interviewer voice. Local audio capture -> transcript -> reviewed
 * interview response -> authorized playback. No direct model-to-speaker path. */
(function (global) {
  "use strict";
  // 1.8 s of silence ends a spoken answer: long enough to survive a mid-sentence
  // pause, short enough that the turn does not feel laggy. A segment with less
  // than MIN_VOICED_MS of actual voiced audio (a cough, a playback echo tail) is
  // dropped locally instead of being sent for transcription.
  const SILENCE_MS=1800, MIN_SPEECH_MS=550, MIN_VOICED_MS=250, MAX_SEGMENT_MS=90000, MAX_EMPTY_TRANSCRIPTS=3;
  const KINDS=new Set(["question","final_check","complete","pause","review_pending"]);
  const REVIEW_ACK="Let me check that I have everything before we finish.";
  const PARTIAL_REVIEW_ACK="Let me check what we have and keep the unanswered parts open.";
  // Staleness is about participant evidence: turns, files and the context the
  // participant supplied. The process title is set by the working map while a
  // turn is in flight, so it is not part of this basis.
  const sourceSignature=value=>JSON.stringify([{...(value?.context||{}),process_name:undefined},value?.turns||[],value?.document_revision||""]);
  class CollectorControlledVoice {
    constructor(options={}) {
      for(const key of ["request","getSnapshot","onAnswer","onResult","speak"]){if(typeof options[key]!=="function")throw new TypeError(`Controlled voice requires ${key}.`);}
      this.options=options;this.operation=null;this.sequence=0;this.status="idle";
      this.mediaDevices=options.mediaDevices||global.navigator?.mediaDevices;
      this.Recorder=options.MediaRecorder||global.MediaRecorder;
      this.Context=options.AudioContext||global.AudioContext||global.webkitAudioContext;
      this.now=options.now||(()=>global.performance?.now?.()??Date.now());
      this.raf=options.requestAnimationFrame||(fn=>global.requestAnimationFrame(fn));
      this.caf=options.cancelAnimationFrame||(id=>global.cancelAnimationFrame(id));
      this.later=options.setTimeout||((fn,ms)=>global.setTimeout(fn,ms));
      this.unlater=options.clearTimeout||(id=>global.clearTimeout(id));
      this.hide=()=>{void this.stop({immediate:true});};
      global.addEventListener?.("pagehide",this.hide);
    }
    get active(){return Boolean(this.operation&&!this.operation.closing);}
    get connected(){return Boolean(this.operation?.ready&&!this.operation.closing);}
    notify(name,value){try{this.options[name]?.(value);}catch{/* Display callbacks cannot bypass cleanup. */}}
    current(op){return this.operation===op&&!op.closing&&!op.controller.signal.aborted;}
    setStatus(status){this.status=status;this.notify("onStatus",status);}
    tracks(op,enabled){op.stream?.getAudioTracks().forEach(track=>{track.enabled=enabled;});}
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
        if(typeof this.options.opening==="function"){
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
      segment.finishing=true;this.unlater(segment.timer);this.tracks(op,false);
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
        op.controller.signal.removeEventListener("abort",abort);
        if(op.workController===controller){op.workController=null;op.processing=false;}
        if(this.current(op))this.listen(op);
      }
    }
    async processAnswer(op,blob,signal){
      let transcript;
      try{transcript=await this.options.request("/api/transcribe",blob,{signal});}
      catch{const error=new Error("Transcription failed");error.voiceMessage="I could not transcribe that answer. Earlier answers are saved. Please repeat it after reconnecting, or type it.";throw error;}
      if(!this.current(op)||signal.aborted||op.muted)return;
      const text=typeof transcript?.text==="string"?transcript.text.trim():"";
      if(!text){
        // Nothing intelligible was said (noise, an echo tail, a breath). Keep
        // listening rather than ending the session; only a run of empty
        // segments suggests a microphone problem worth stopping for.
        op.emptyTranscripts=(op.emptyTranscripts||0)+1;
        if(op.emptyTranscripts>=MAX_EMPTY_TRANSCRIPTS){const error=new Error("Empty transcription");error.voiceMessage="I could not make out an answer several times in a row. Earlier answers are saved. Check the microphone and reconnect, or type it.";throw error;}
        this.notify("onNotice","I didn’t catch that. Please say it again, or type it.");
        return;
      }
      op.emptyTranscripts=0;
      this.options.onAnswer(text);
      if(!this.current(op)||signal.aborted||op.muted)return;
      const snapshot=this.options.getSnapshot(),basis=sourceSignature(snapshot);
      const result=await this.options.request("/api/interview",{...snapshot,action:"answer"},{signal});
      if(!this.current(op)||signal.aborted||op.muted)return;
      await this.playReviewed(op,result,basis,signal);
    }
    async playReviewed(op,result,basis,signal){
      if(!this.current(op)||signal.aborted||op.muted)return;
      const authorization=result?.speech_authorization;
      if(typeof result?.question!=="string"||!result.question.trim()||result.question.length>6000||authorization?.approved!==true||!KINDS.has(authorization.kind)||authorization.text!==result.question||typeof authorization.revision!=="string"||!/^[A-Za-z0-9_.:-]{1,128}$/.test(authorization.revision)){
        const error=new Error("Unapproved speech");error.voiceMessage="The response did not pass the speech check, so it was not spoken. Your answers are saved; continue by typing or reconnect.";throw error;
      }
      if((authorization.kind==="final_check"&&result.completion?.ready_for_final_check!==true)||
         (authorization.kind==="complete"&&(result.completion?.complete!==true||authorization.completion_allowed!==true))){
        const error=new Error("Inconsistent completion authorization");error.voiceMessage="The response did not pass the completion check, so it was not spoken. Your answers are saved; continue by typing or reconnect.";throw error;
      }
      if(authorization.kind==="review_pending"&&((result.question!==REVIEW_ACK&&!(result.review_purpose==="partial"&&result.question===PARTIAL_REVIEW_ACK))||typeof result.review_ticket!=="string"||!result.review_ticket||result.review_ticket.length>4096||result.coverage_verified===true||result.completion?.complete===true||result.completion?.ready_for_final_check===true))throw new Error("Invalid review acknowledgement");
      if(sourceSignature(this.options.getSnapshot())!==basis){const error=new Error("Stale response");error.voiceMessage="The conversation changed while the response was being reviewed. That earlier response was not spoken. Continue by typing or reconnect.";throw error;}
      this.options.onResult(result);
      const appliedBasis=sourceSignature(this.options.getSnapshot());
      if(!this.current(op)||signal.aborted||op.muted)return;
      this.setStatus("speaking");
      try{
        const playback=this.options.speak(result.question,{signal});
        if(!playback||typeof playback.then!=="function")throw new Error("Playback must report its completion");
        await playback;
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
    async dispose(){global.removeEventListener?.("pagehide",this.hide);return this.stop({immediate:true});}
  }
  global.CollectorControlledVoice=CollectorControlledVoice;
})(window);
