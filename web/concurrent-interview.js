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
  const newId=()=>crypto.randomUUID().replaceAll("-","");
  const stale=()=>new DOMException("The conversation changed while this response was being prepared","AbortError");
  class CollectorConcurrentInterview {
    constructor(options={}){
      for(const key of ["request","getSnapshot","getGeneration","applyCapture"]){if(typeof options[key]!=="function")throw new TypeError(`Concurrent interview requires ${key}.`);}
      this.options=options;this.token=null;this.startId=null;this.pendingTurn=null;this.pendingSync=null;this.epoch=0;this.sequence=0;this.timer=null;this.pollController=null;this.controllers=new Set();this.appliedRevision=null;
      this.later=options.setTimeout||((fn,ms)=>global.setTimeout(fn,ms));this.unlater=options.clearTimeout||(id=>global.clearTimeout(id));this.pollMs=options.pollMs??650;
    }
    notify(value){try{this.options.onStatus?.(value);}catch{/* Advisory status cannot alter interview state. */}}
    stopPolling(){if(this.timer!==null)this.unlater(this.timer);this.timer=null;this.pollController?.abort();this.pollController=null;}
    reset({handoff=false}={}){
      const token=this.token||this.startId;
      this.epoch++;this.sequence++;this.stopPolling();
      for(const controller of this.controllers)controller.abort();
      this.controllers.clear();this.token=null;this.startId=null;this.pendingTurn=null;this.pendingSync=null;this.appliedRevision=null;
      if(token)void this.cancelSession(token,handoff);
      this.notify({state:"idle"});
    }
    async cancelSession(token,handoff){
      try{await this.options.request("/api/conversation/cancel",{conversation_token:token,...(handoff?{handoff:true}:{})},{});}
      catch{/* A closed transport can no longer deliver the disposal request. */}
    }
    operation(kind,snapshot){
      const key=JSON.stringify([snapshot.action||"answer",snapshot.context,snapshot.turns,snapshot.document_scope,
        snapshot.document_revision,snapshot.capture_token]);
      if(this[kind]?.key!==key)this[kind]={key,id:newId()};
      return this[kind].id;
    }
    current(captured){return captured.epoch===this.epoch&&captured.generation===this.options.getGeneration()&&captured.sequence===this.sequence&&captured.key===sourceKey(this.options.getSnapshot());}
    async send(path,payload,options={}){
      const controller=new AbortController(),abort=()=>controller.abort();this.controllers.add(controller);
      options.signal?.addEventListener("abort",abort,{once:true});if(options.signal?.aborted)abort();
      try{return await this.options.request(path,payload,{...options,signal:controller.signal});}
      finally{options.signal?.removeEventListener("abort",abort);this.controllers.delete(controller);}
    }
    capture(snapshot){return{snapshot:copy(snapshot),key:sourceKey(snapshot),epoch:this.epoch,generation:this.options.getGeneration(),sequence:++this.sequence};}
    withToken(snapshot){
      if(this.token)return {...snapshot,conversation_token:this.token};
      this.startId??=newId()+newId();
      return {...snapshot,conversation_start_id:this.startId};
    }
    rememberToken(result){if(typeof result?.conversation_token!=="string"||!result.conversation_token)throw new Error("The interviewer did not return its conversation session.");this.token=result.conversation_token;}
    async turn(snapshot,options={}){
      const captured=this.capture(snapshot);this.stopPolling();
      this.notify({state:'queued'});
      // Retain the logical turn until its response reaches this controller.
      // A later intentional Skip after delivery gets a new ID.
      const result=await this.send("/api/conversation/turn",{...this.withToken(captured.snapshot),
        operation_id:this.operation("pendingTurn",snapshot)},options);
      if(options.signal?.aborted||!this.current(captured))throw stale();
      this.rememberToken(result);
      if(result.sync_required===true){
        const reviewed=await this.sync(captured.snapshot,options);
        this.pendingTurn=null;return reviewed;
      }
      this.pendingTurn=null;
      if(result.speech_authorization?.kind==="pause"){
        if(result.analysis?.settling){this.notify({state:"working"});this.schedule(captured);}
        else this.notify({state:"idle"});
        return result;
      }
      this.notify({state:result.analysis?.state||"working",revision:result.revision});
      this.schedule(captured);
      return result;
    }
    schedule(captured){
      if(!this.current(captured))return;
      this.timer=this.later(()=>{this.timer=null;void this.poll(captured);},this.pollMs);
    }
    async poll(captured){
      if(!this.current(captured))return;
      const controller=new AbortController();this.pollController=controller;
      try{
        // Pin retrieval hints to the turn that queued this work. Applying its
        // citations may change current source preferences without changing the
        // participant's answer or active documents.
        const snapshot=copy(captured.snapshot);
        const result=await this.send("/api/conversation/status",this.withToken(snapshot),{signal:controller.signal});
        if(controller.signal.aborted||!this.current(captured))return;
        this.rememberToken(result);
        if(result.agent_team)this.notify({state:result.state,agent_team:result.agent_team});
        if(result.state==="paused"||result.capture?.preserve_capture){this.notify({state:"idle"});return;}
        if(result.state==="ready"){
          if(!result.capture||typeof result.capture!=="object")throw new Error("Background analysis finished without a capture.");
          const appliedKey=JSON.stringify([result.revision,Boolean(result.workflow_capture)]);
          if(appliedKey!==this.appliedRevision){
            this.options.applyCapture({...result.capture,...(result.workflow_capture?{workflow_capture:result.workflow_capture}:{})},{snapshot,revision:result.revision});this.appliedRevision=appliedKey;
          }
          if(["queued","working"].includes(result.workflow_state)){this.notify({state:"working",revision:result.revision});this.schedule(captured);return;}
          if(result.workflow_state==="error"){this.notify({state:"error",revision:result.revision,message:result.workflow_error||"Notes updated, but the workflow could not update. Wrap up retries the analysis."});return;}
          this.notify({state:"ready",revision:result.revision});return;
        }
        if(result.state==="error"){this.notify({state:"error",revision:result.revision,message:result.error||"Background notes could not update. Your conversation is retained."});return;}
        if(!["queued","working"].includes(result.state))throw new Error("Background analysis returned an invalid state.");
        this.notify({state:result.state,revision:result.revision});this.schedule(captured);
      }catch(error){if(!controller.signal.aborted&&this.current(captured))this.notify({state:"error",message:error.message||"Background notes could not update. Your conversation is retained."});}
      finally{if(this.pollController===controller)this.pollController=null;}
    }
    async sync(snapshot,options={}){
      const captured=this.capture(snapshot);this.stopPolling();this.notify({state:"syncing"});
      try{
        const result=await this.send("/api/conversation/sync",{...this.withToken(captured.snapshot),
          operation_id:this.operation("pendingSync",snapshot)},options);
        if(options.signal?.aborted||!this.current(captured))throw stale();
        this.rememberToken(result);this.pendingSync=null;this.notify({state:"ready",revision:result.revision});return result;
      }catch(error){if(error.name!=="AbortError"&&this.current(captured))this.notify({state:"error",message:error.message});throw error;}
    }
  }
  global.CollectorConcurrentInterview=CollectorConcurrentInterview;
})(window);
