/* Conversation turns and capture run independently. This controller never speaks
 * an analysis question and never grants completion authority. */
(function (global) {
  "use strict";
  const copy=value=>JSON.parse(JSON.stringify(value));
  function sourceKey(snapshot){
    const turns=[...(snapshot?.turns||[])];
    // The spoken question is appended after turn() returns. It changes no
    // participant evidence and must not hide the analysis of that answer.
    while(turns.at(-1)?.role==="assistant")turns.pop();
    return JSON.stringify([snapshot?.context||{},turns,snapshot?.document_revision||"",snapshot?.document_scope||""]);
  }
  const stale=()=>new DOMException("The conversation changed while this response was being prepared","AbortError");
  class CollectorConcurrentInterview {
    constructor(options={}){
      for(const key of ["request","getSnapshot","getGeneration","applyCapture"]){if(typeof options[key]!=="function")throw new TypeError(`Concurrent interview requires ${key}.`);}
      this.options=options;this.token=null;this.epoch=0;this.sequence=0;this.timer=null;this.pollController=null;this.controllers=new Set();this.appliedRevision=null;this.settling=0;
      this.later=options.setTimeout||((fn,ms)=>global.setTimeout(fn,ms));this.unlater=options.clearTimeout||(id=>global.clearTimeout(id));this.pollMs=options.pollMs??650;
    }
    // True while a turn, sync or status request is in flight or the next status poll is scheduled.
    // The last notified state is not enough: a turn that fails leaves it at "queued" with nothing running.
    // Also true while a status reply is being handled (settling): its progress notice and the notes it
    // applies reach listeners before the next poll is scheduled, and must not read as "nothing running".
    get active(){return this.timer!==null||this.controllers.size>0||this.settling>0;}
    notify(value){try{this.options.onStatus?.(value);}catch{/* Advisory status cannot alter interview state. */}}
    stopPolling(){if(this.timer!==null)this.unlater(this.timer);this.timer=null;this.pollController?.abort();this.pollController=null;}
    reset(){this.epoch++;this.sequence++;this.stopPolling();for(const controller of this.controllers)controller.abort();this.controllers.clear();this.token=null;this.appliedRevision=null;this.checkpointRevision=null;this.notify({state:"idle"});}
    current(captured){return captured.epoch===this.epoch&&captured.generation===this.options.getGeneration()&&captured.sequence===this.sequence&&captured.key===sourceKey(this.options.getSnapshot());}
    async send(path,payload,options={}){
      const controller=new AbortController(),abort=()=>controller.abort();this.controllers.add(controller);
      options.signal?.addEventListener("abort",abort,{once:true});if(options.signal?.aborted)abort();
      try{return await this.options.request(path,payload,{...options,signal:controller.signal});}
      finally{options.signal?.removeEventListener("abort",abort);this.controllers.delete(controller);}
    }
    capture(snapshot){return{snapshot:copy(snapshot),key:sourceKey(snapshot),epoch:this.epoch,generation:this.options.getGeneration(),sequence:++this.sequence};}
    withToken(snapshot){return{...snapshot,...(this.token?{conversation_token:this.token}:{})};}
    rememberToken(result){if(typeof result?.conversation_token!=="string"||!result.conversation_token)throw new Error("The interviewer did not return its conversation session.");this.token=result.conversation_token;}
    async turn(snapshot,options={}){
      const captured=this.capture(snapshot);this.stopPolling();
      this.notify({state:'queued'});
      let result;
      try{result=await this.send("/api/conversation/turn",this.withToken(captured.snapshot),options);}
      catch(error){if(error.name!=="AbortError"&&this.current(captured))this.notify({state:"error",message:error.message});throw error;}
      if(options.signal?.aborted||!this.current(captured))throw stale();
      this.rememberToken(result);if(result.sync_required===true)return this.sync(captured.snapshot,options);
      // Schedule before notifying, so a listener that reads `active` sees the poll that is coming.
      captured.revision=result.revision;captured.started=Date.now();
      this.schedule(captured);
      this.notify({state:result.analysis?.state||"working",revision:result.revision});
      return result;
    }
    schedule(captured,delay=this.pollMs){
      if(!this.current(captured))return;
      this.timer=this.later(()=>{this.timer=null;void this.poll(captured);},delay);
    }
    scheduleProgress(captured){
      if(this.pollMs && Date.now()-(captured.started||Date.now())>300000){
        this.notify({state:"error",message:"The notes are taking longer than expected. Your answers are still in this tab. Select Update notes to check again."});return;
      }
      captured.polls=(captured.polls||0)+1;
      // Allow the browser to round a hidden tab's next wake-up to the next second.
      this.schedule(captured,Math.min(3500,this.pollMs*(1+Math.floor(captured.polls/3))));
    }
    async poll(captured){
      if(!this.current(captured))return;
      const controller=new AbortController();this.pollController=controller;
      // The capture counts as running until this poll's outcome is known. settled() ends that just before
      // the notification that reports the outcome: after the next poll is scheduled, or when nothing follows.
      let open=true;this.settling++;const settled=()=>{if(open){open=false;this.settling--;}};
      try{
        // Pin retrieval hints to the turn that queued this work. Applying its
        // citations may change current source preferences without changing the
        // participant's answer or active documents.
        const snapshot=copy(captured.snapshot);
        const compact = typeof captured.revision==="string" && /^[a-f0-9]{64}$/.test(captured.revision);
        const query = compact ? {conversation_token:this.token,revision:captured.revision,
          ...(snapshot.document_scope?{document_scope:snapshot.document_scope}:{})} : this.withToken(snapshot);
        const result=await this.send("/api/conversation/status",query,{signal:controller.signal});
        if(controller.signal.aborted||!this.current(captured))return;
        this.rememberToken(result); captured.retryWait=0; captured.retryCount=0;
        const checkpoint=result.checkpoint;
        if(checkpoint && checkpoint.capture && Array.isArray(checkpoint.turns) && checkpoint.revision &&
           checkpoint.revision!==this.checkpointRevision && checkpoint.turns.length<snapshot.turns.length &&
           checkpoint.turns.every((turn,index)=>{
             const actual=snapshot.turns[index];
             return actual && turn.id===actual.id && turn.role===actual.role && turn.text===actual.text &&
               Boolean(turn.document_event)===Boolean(actual.document_event) && turn.document_id===actual.document_id;
           }) && checkpoint.turns.filter(turn=>turn.role==="user"&&!turn.document_event).at(-1)?.id===checkpoint.through_turn_id){
          this.options.applyCapture(checkpoint.capture,{snapshot:{...snapshot,turns:checkpoint.turns},revision:checkpoint.revision,checkpoint:true});
          this.checkpointRevision=checkpoint.revision;
        }
        if(result.agent_team)this.notify({state:result.state,agent_team:result.agent_team});
        if(result.state==="ready"){
          // A pause request settles its turn without new notes. The server says so
          // (capture_preserved) and sends no capture: the notes already applied
          // stay, and only a workflow update is passed on.
          const kept=result.capture_preserved===true;
          if(!kept&&(!result.capture||typeof result.capture!=="object"))throw new Error("Background analysis finished without a capture.");
          const appliedKey=JSON.stringify([result.revision,Boolean(result.workflow_capture)]);
          if(appliedKey!==this.appliedRevision){
            this.options.applyCapture({...(kept?{preserve_capture:true}:result.capture),...(result.workflow_capture?{workflow_capture:result.workflow_capture}:{})},{snapshot,revision:result.revision});this.appliedRevision=appliedKey;
          }
          if(["queued","working"].includes(result.workflow_state)){this.scheduleProgress(captured);settled();if(this.timer!==null)this.notify({state:"working",revision:result.revision});return;}
          settled();
          if(result.workflow_state==="error"){this.notify({state:"error",revision:result.revision,message:result.workflow_error||"Notes updated, but the workflow could not update. Wrap up retries the analysis."});return;}
          this.notify({state:"ready",revision:result.revision,...(kept?{kept:true}:{})});return;
        }
        if(result.state==="error"){settled();this.notify({state:"error",revision:result.revision,message:result.error||"Background notes could not update. Your conversation is retained."});return;}
        if(!["queued","working"].includes(result.state))throw new Error("Background analysis returned an invalid state.");
        this.scheduleProgress(captured);settled();if(this.timer!==null)this.notify({state:result.state,revision:result.revision});
      }catch(error){
        settled();
        if(controller.signal.aborted||!this.current(captured))return;
        const transient=error.transient===true || error.name==="TypeError" || error.status===429 || error.status>=500;
        const delay=Math.max(Number(error.retryAfter)||0,Math.min(5000,Math.max(650,this.pollMs)*2**(captured.retryCount||0)));
        if(transient && (captured.retryWait||0)+delay<=30000){
          captured.retryCount=(captured.retryCount||0)+1; captured.retryWait=(captured.retryWait||0)+delay;
          this.schedule(captured,delay); this.notify({state:"reconnecting"}); return;
        }
        if(error.code==="conversation_expired"){this.token=null;this.appliedRevision=null;this.checkpointRevision=null;}
        this.notify({state:"error",message:error.message||"Background notes could not update. Your conversation is retained."});
      }
      finally{settled();if(this.pollController===controller)this.pollController=null;}
    }
    async sync(snapshot,options={}){
      const captured=this.capture(snapshot);this.stopPolling();this.notify({state:"syncing"});
      try{
        const result=await this.send("/api/conversation/sync",this.withToken(captured.snapshot),options);
        if(options.signal?.aborted||!this.current(captured))throw stale();
        this.rememberToken(result);this.notify({state:"ready",revision:result.revision});return result;
      }catch(error){if(error.name!=="AbortError"&&this.current(captured))this.notify({state:"error",message:error.message});throw error;}
    }
  }
  global.CollectorConcurrentInterview=CollectorConcurrentInterview;
})(window);
