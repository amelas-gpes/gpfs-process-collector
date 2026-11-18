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
      this.options=options;this.token=null;this.startId=null;this.pendingTurn=null;this.pendingSync=null;this.epoch=0;this.sequence=0;this.timer=null;this.pollController=null;this.controllers=new Set();this.appliedRevision=null;this.settling=0;
      this.later=options.setTimeout||((fn,ms)=>global.setTimeout(fn,ms));this.unlater=options.clearTimeout||(id=>global.clearTimeout(id));this.pollMs=options.pollMs??650;
    }
    // True while a turn, sync or status request is in flight or the next status poll is scheduled.
    // The last notified state is not enough: a turn that fails leaves it at "queued" with nothing running.
    // Also true while a status reply is being handled (settling): its progress notice and the notes it
    // applies reach listeners before the next poll is scheduled, and must not read as "nothing running".
    get active(){return this.timer!==null||this.controllers.size>0||this.settling>0;}
    notify(value){
      global.CollectorRawTrace?.record("analysis.status",{state:value.state,revision:value.revision,kept:value.kept});
      try{this.options.onStatus?.(value);}catch{/* Advisory status cannot alter interview state. */}
    }
    notifyCheckError(result){
      this.notify({state:"error",scope:"workflow",revision:result.revision,
        message:result.workflow_check_error||"The workflow could not be checked against its sources. Your notes are up to date. Select Update workflow to try again."});
    }
    stopPolling(){if(this.timer!==null)this.unlater(this.timer);this.timer=null;this.pollController?.abort();this.pollController=null;}
    reset({handoff=false}={}){
      const token=this.token||this.startId;
      this.epoch++;this.sequence++;this.stopPolling();
      for(const controller of this.controllers)controller.abort();
      this.controllers.clear();this.token=null;this.startId=null;this.pendingTurn=null;this.pendingSync=null;
      this.appliedRevision=null;this.checkpointRevision=null;this.appliedMap=null;
      if(token)void this.cancelSession(token,handoff);
      this.notify({state:"idle"});
    }
    async cancelSession(token,handoff){
      try{await this.options.request("/api/conversation/cancel",{conversation_token:token,...(handoff?{handoff:true}:{})},{});}
      catch{/* Disposal is best effort after this page has left the session. */}
    }
    operation(kind,snapshot){
      const key=JSON.stringify([snapshot.action||"answer",snapshot.context,snapshot.turns,snapshot.document_scope,
        snapshot.document_revision,snapshot.capture_token,snapshot.session?.closure_requested]);
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
      let result;
      try{result=await this.send("/api/conversation/turn",{...this.withToken(captured.snapshot),operation_id:this.operation("pendingTurn",snapshot)},options);}
      catch(error){if(error.name!=="AbortError"&&this.current(captured))this.notify({state:"error",message:error.message});throw error;}
      if(options.signal?.aborted||!this.current(captured))throw stale();
      this.rememberToken(result);
      if(result.sync_required===true){
        const reviewed=await this.sync(captured.snapshot,options);
        this.pendingTurn=null;return reviewed;
      }
      this.pendingTurn=null;
      if(result.analysis?.state==="paused"&&!result.analysis.settling){
        this.notify({state:"ready",kept:true,revision:result.revision});return result;
      }
      // Schedule before notifying, so a listener that reads `active` sees the poll that is coming.
      captured.revision=result.revision;captured.started=Date.now();
      this.schedule(captured);
      this.notify({state:result.analysis?.settling?"working":result.analysis?.state||"working",revision:result.revision});
      return result;
    }
    schedule(captured,delay=this.pollMs){
      if(!this.current(captured))return;
      this.timer=this.later(()=>{this.timer=null;void this.poll(captured);},delay);
    }
    scheduleProgress(captured,checking=false){
      // Allow more time for a map check. If the page stops fetching, offer an explicit retry.
      if(checking&&this.pollMs&&Date.now()-(captured.started||Date.now())>900000){
        const message="The workflow update is taking longer than expected. Select Update workflow to try again.";
        if(captured.notesFailed)this.options.onWorkflowError?.(message);
        else this.notify({state:"error",scope:"workflow",message});
        return;
      }
      if(!checking&&this.pollMs && Date.now()-(captured.started||Date.now())>300000){
        // Once the notes are in, only the map is late: that is the map's own state, not a failure of the notes.
        this.notify(captured.mapOnly||captured.notesApplied?{state:"error",scope:"workflow",message:"The workflow is taking longer than expected. Your notes are up to date. Select Update workflow to try again."}
          :{state:"error",message:"The notes are taking longer than expected. Your answers are still in this tab. Select Update notes to check again."});return;
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
        if(controller.signal.aborted||!this.current(captured)){
          global.CollectorRawTrace?.record("analysis.poll_discarded",{revision:captured.revision,aborted:controller.signal.aborted});return;
        }
        this.rememberToken(result); captured.retryWait=0; captured.retryCount=0;
        if(result.state==="paused"){settled();this.notify({state:"ready",kept:true,revision:result.revision});return;}
        // Work that finished for an earlier answer is taken only when its turns are still the
        // beginning of this conversation, word for word, and it names the answer it goes through.
        const earlier=item=>Array.isArray(item.turns) && item.turns.length<snapshot.turns.length &&
           item.turns.every((turn,index)=>{
             const actual=snapshot.turns[index];
             return actual && turn.id===actual.id && turn.role===actual.role && turn.text===actual.text &&
               Boolean(turn.document_event)===Boolean(actual.document_event) && turn.document_id===actual.document_id;
           }) && item.turns.filter(turn=>turn.role==="user"&&!turn.document_event).at(-1)?.id===item.through_turn_id;
        // The map is drawn first and checked against its sources beside it. check says where that
        // stands for the map in this reply: "" (checked), "working" or "error".
        const mapCheck=result.workflow_checked===false?(result.workflow_check_state==="error"?"error":"working"):"";
        const mapKey=result.workflow_capture&&typeof result.workflow_capture==="object"?JSON.stringify([result.revision,result.workflow_version??0,mapCheck]):null;
        const behind=result.workflow_checkpoint;
        const hasCheckpoint=!mapKey && behind?.workflow_capture && behind.revision && earlier(behind);
        const visibleMap=hasCheckpoint?{workflow:"checkpoint"}:mapKey?{workflow:"ready"}:{};
        if(hasCheckpoint){
          // The map through an earlier answer, while the map of this answer is being drawn.
          const key=JSON.stringify([behind.revision,behind.version??0]);
          if(key!==this.appliedMap){
            this.options.applyWorkflow?.(behind.workflow_capture,{snapshot:{...snapshot,turns:behind.turns},revision:behind.revision,
              checkpoint:true,check:behind.checked===false?"working":""});
            global.CollectorRawTrace?.record("analysis.workflow_checkpoint_applied",{revision:behind.revision,through_turn_id:behind.through_turn_id});
            this.appliedMap=key;
          }
        }
        const checkpoint=result.checkpoint;
        if(!captured.mapOnly && checkpoint && checkpoint.capture && checkpoint.revision &&
           checkpoint.revision!==this.checkpointRevision && earlier(checkpoint)){
          this.options.applyCapture(checkpoint.capture,{snapshot:{...snapshot,turns:checkpoint.turns},revision:checkpoint.revision,checkpoint:true});
          global.CollectorRawTrace?.record("analysis.checkpoint_applied",{revision:checkpoint.revision,through_turn_id:checkpoint.through_turn_id});
          this.checkpointRevision=checkpoint.revision;
        }
        if(result.agent_team&&(captured.mapOnly||result.state!=="error")){
          this.notify({state:captured.mapOnly?"ready":result.state,agent_team:result.agent_team,
            ...(captured.mapOnly?{workflow:"working"}:{}),...visibleMap});
        }
        if(captured.mapOnly){
          // Wrap up has already released the synchronized notes of this revision. This poll
          // fetches the map that was not ready then, and takes nothing else from the reply:
          // background notes would replace what the review is working from.
          if(mapKey){
            if(mapKey!==this.appliedMap){
              this.options.applyWorkflow?.(result.workflow_capture,{snapshot,revision:result.revision,check:mapCheck});
              global.CollectorRawTrace?.record("analysis.workflow_applied",{revision:result.revision,check:mapCheck});
              this.appliedMap=mapKey;
            }
            // The map is on screen. While its source check runs the page keeps asking for the result.
            if(mapCheck==="working"){this.scheduleProgress(captured,true);settled();if(this.timer!==null)this.notify({state:"ready",revision:result.revision,workflow:"checking"});return;}
            settled();
            if(mapCheck==="error"){this.notifyCheckError(result);return;}
            this.notify({state:"ready",revision:result.revision,workflow:"ready"});return;
          }
          if(["queued","working"].includes(result.workflow_state)){this.scheduleProgress(captured);settled();return;}
          settled();
          this.notify({state:"error",scope:"workflow",revision:result.revision,message:result.workflow_error||"The workflow could not update. Your notes are up to date. Select Update workflow to try again."});return;
        }
        // The map of this answer can be drawn before its notes are captured: it is shown as soon as it is there.
        if(mapKey&&mapKey!==this.appliedMap&&result.state!=="ready"){
          this.options.applyWorkflow?.(result.workflow_capture,{snapshot,revision:result.revision,check:mapCheck});
          global.CollectorRawTrace?.record("analysis.workflow_applied",{revision:result.revision,check:mapCheck,before_notes:true});
          this.appliedMap=mapKey;
        }
        if(result.state==="ready"){
          // A pause request settles its turn without new notes. The server says so
          // (capture_preserved) and sends no capture: the notes already applied
          // stay, and only a workflow update is passed on.
          const kept=result.capture_preserved===true;
          if(!kept&&(!result.capture||typeof result.capture!=="object"))throw new Error("Background analysis finished without a capture.");
          const appliedKey=JSON.stringify([result.revision,Boolean(result.workflow_capture)]);
          if(appliedKey!==this.appliedRevision){
            this.options.applyCapture({...(kept?{preserve_capture:true}:result.capture),...(result.workflow_capture?{workflow_capture:result.workflow_capture}:{})},{snapshot,revision:result.revision,check:mapCheck});this.appliedRevision=appliedKey;
            if(mapKey)this.appliedMap=mapKey;
            global.CollectorRawTrace?.record("analysis.capture_applied",{revision:result.revision,kept,workflow:Boolean(result.workflow_capture)});
          }else if(mapKey&&mapKey!==this.appliedMap){
            // The notes are in; the map changed (its check finished, or Wrap up's second look replaced it).
            this.options.applyWorkflow?.(result.workflow_capture,{snapshot,revision:result.revision,check:mapCheck});
            global.CollectorRawTrace?.record("analysis.workflow_applied",{revision:result.revision,check:mapCheck});
            this.appliedMap=mapKey;
          }
          captured.notesApplied=true;
          if(["queued","working"].includes(result.workflow_state)){this.scheduleProgress(captured);settled();if(this.timer!==null)this.notify({state:"working",revision:result.revision,...visibleMap});return;}
          if(mapKey&&mapCheck==="working"){this.scheduleProgress(captured,true);settled();if(this.timer!==null)this.notify({state:"ready",revision:result.revision,workflow:"checking",...(kept?{kept:true}:{})});return;}
          settled();
          // The notes are in and only the map failed: scope says so, and the map keeps its own retry.
          if(result.workflow_state==="error"){this.notify({state:"error",scope:"workflow",revision:result.revision,message:result.workflow_error||"Notes updated, but the workflow could not update. Wrap up retries the analysis."});return;}
          this.notify({state:"ready",revision:result.revision,...(kept?{kept:true}:{})});return;
        }
        if(result.state==="error"){
          // Notes and the diagram have independent workers. Keep listening for the draw or its
          // check without replacing the original notes error on subsequent status replies.
          const announce=!captured.notesFailed;
          captured.notesFailed=true;
          if(["queued","working"].includes(result.workflow_state)||mapKey&&mapCheck==="working")this.scheduleProgress(captured,true);
          settled();
          if(announce)this.notify({state:"error",revision:result.revision,agent_team:result.agent_team,message:result.error||"Background notes could not update. Your conversation is retained."});
          if(result.workflow_state==="error")this.options.onWorkflowError?.(result.workflow_error||"The workflow could not update. Select Update workflow to try again.");
          return;
        }
        if(!["queued","working"].includes(result.state))throw new Error("Background analysis returned an invalid state.");
        this.scheduleProgress(captured);settled();if(this.timer!==null)this.notify({state:result.state,revision:result.revision,...visibleMap});
      }catch(error){
        settled();
        if(controller.signal.aborted||!this.current(captured))return;
        const transient=error.transient===true || error.name==="TypeError" || error.status===429 || error.status>=500;
        const delay=Math.max(Number(error.retryAfter)||0,Math.min(5000,Math.max(650,this.pollMs)*2**(captured.retryCount||0)));
        if(transient && (captured.retryWait||0)+delay<=30000){
          captured.retryCount=(captured.retryCount||0)+1; captured.retryWait=(captured.retryWait||0)+delay;
          this.schedule(captured,delay); if(!captured.notesFailed)this.notify({state:"reconnecting"}); return;
        }
        if(error.code==="conversation_expired"){this.startId=null;this.pendingTurn=null;this.pendingSync=null;this.token=null;this.appliedRevision=null;this.checkpointRevision=null;this.appliedMap=null;}
        if(captured.notesFailed){this.options.onWorkflowError?.("The workflow could not be checked. Select Update workflow to try again.");return;}
        this.notify(captured.mapOnly||captured.notesApplied?{state:"error",scope:"workflow",message:"The workflow could not be checked. Your notes are up to date. Select Update workflow to try again."}
          :{state:"error",message:error.message||"Background notes could not update. Your conversation is retained."});
      }
      finally{settled();if(this.pollController===controller)this.pollController=null;}
    }
    async sync(snapshot,options={}){
      const captured=this.capture(snapshot);this.stopPolling();this.notify({state:"syncing"});
      try{
        const result=await this.send("/api/conversation/sync",{...this.withToken(captured.snapshot),
          operation_id:this.operation("pendingSync",snapshot)},options);
        if(options.signal?.aborted||!this.current(captured))throw stale();
        this.rememberToken(result);this.pendingSync=null;
        // The notes are synchronized; the map may not be. It has its own state: a map still
        // being drawn is fetched by the status poll when it arrives, and a failed one is
        // reported as the map's failure, with the notes shown as they are (caught up).
        const revision=typeof result.revision==="string"&&/^[a-f0-9]{64}$/.test(result.revision);
        // A map released with its source check still running: the caller shows it, and the poll
        // brings the checked map (or the map Wrap up's second look put in its place).
        const checking=Boolean(result.workflow_capture)&&result.workflow_checked===false&&result.workflow_check_state==="working";
        if(result.workflow_capture)this.appliedMap=JSON.stringify([result.revision,result.workflow_version??0,result.workflow_checked===false?(result.workflow_check_state==="error"?"error":"working"):""]);
        if((result.workflow_pending===true&&!result.workflow_capture||checking)&&revision){
          captured.revision=result.revision;captured.started=Date.now();captured.mapOnly=true;
          this.schedule(captured);
          this.notify({state:"ready",revision:result.revision,workflow:checking?"checking":"working"});
        }else if(result.workflow_capture&&result.workflow_checked===false&&result.workflow_check_state==="error"){
          this.notifyCheckError(result);
        }else if(result.workflow_state==="error"&&!result.workflow_capture){
          this.notify({state:"error",scope:"workflow",revision:result.revision,message:result.workflow_error||"The workflow could not update. Your notes are up to date. Select Update workflow to try again."});
        }else this.notify({state:"ready",revision:result.revision});
        return result;
      }catch(error){if(error.name!=="AbortError"&&this.current(captured))this.notify({state:"error",message:error.message});throw error;}
    }
  }
  global.CollectorConcurrentInterview=CollectorConcurrentInterview;
})(window);
