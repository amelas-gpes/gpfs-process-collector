"use strict";

// One file-intake transaction: pause, review, then either ask the file's own question at once
// (hooks.provisional, with the notes and the audited map completed in the background) or, where
// that is not available, commit the baseline first and ask once.
// UI and provider work are injected so ordering/cancellation can be tested offline.
(() => {
  class DocumentIntake {
    constructor(hooks) {this.hooks=hooks;this.sequence=0;this.snapshot={documents:[],uploading:0,mutating:0,uploadErrors:[]};this.reset();}
    get active() {return !["idle","ready"].includes(this.phase);}
    reset() {this.run?.abort();this.cycle?.abort();this.sequence++;this.run=null;this.cycle=null;this.phase="idle";this.error="";this.retryAvailable=false;this.batches=new Set();this.names=new Set();this.ids=new Set();this.signature="";this.intentSignature="";this.failedIntent=null;this.hooks.onStatus?.(this);}
    begin({batchId,names=[],documentId,resumed=false}={}) {
      if(!this.active){
        this.cycle=new AbortController();this.names=new Set();this.ids=new Set();this.batches=new Set();
        this.originalIds=new Set(this.snapshot.documents.map(file=>file.id));
        this.oldErrors=new Set((this.snapshot.uploadErrors||[]).map(error=>JSON.stringify(error)));
        this.phase="uploading";this.error="";
        this.hooks.onStatus?.(this);
        this.beginArgs={names,...(resumed?{resumed:true}:{}),...(documentId?{documentId}:{}),signal:this.cycle.signal};this.pause(false);
      }
      if(batchId)this.batches.add(batchId);
      names.forEach(name=>this.names.add(name));if(documentId)this.ids.add(documentId);
      this.failedIntent=null;this.invalidate();this.setPhase("uploading");
    }
    include(id) {if(this.active&&id)this.ids.add(id);}
    pause(retry) {
      this.pauseFailed=false;
      try {this.paused=Promise.resolve(this.hooks.onBegin?.({...this.beginArgs,retry}));}
      catch(error){this.paused=Promise.reject(error);}
      // A rejected pause must be observed even if an upload is still pending.
      const paused=this.paused,cycle=this.cycle;
      paused.catch(()=>{if(this.paused===paused&&this.cycle===cycle)this.pauseFailed=true;});
    }
    settle(batchId) {this.batches.delete(batchId);this.pump();}
    observe(snapshot) {
      if(this.active&&snapshot.generation!==this.snapshot.generation)this.batches.clear();
      this.snapshot=snapshot;
      // A new source or explicit file action can replace a failed intake. Status
      // polls, connection recovery and background review metadata cannot retry it.
      this.intentSignature=JSON.stringify([snapshot.scope,snapshot.generation,snapshot.documents
        .map(file=>[file.id,file.archived===true,file.analysis?.intent_version||0,file.analysis?.disposition||""])
        .sort((a,b)=>a[0].localeCompare(b[0]))]);
      // A file that can be asked about while its in-depth pass runs (askable) reports progress with
      // every batch. That progress changes nothing the question depends on, so it is not a change here:
      // it would cancel the question that is being asked and ask it again.
      const signature=JSON.stringify([snapshot.scope,snapshot.generation,snapshot.uploading,snapshot.mutating,
        (snapshot.uploadErrors||[]).filter(error=>!this.oldErrors?.has(JSON.stringify(error))),
        snapshot.documents.map(file=>[file.id,file.archived,file.status,file.chunk_count,file.analysis?.intent_version,
          ...(this.askable(file)||file.analysis?.question_ready===true&&file.analysis?.phase==="complete"&&!file.analysis?.error?["askable"]:[file.analysis?.version,file.analysis?.phase]),
          file.analysis?.disposition,file.analysis?.error])]);
      if(signature!==this.signature){this.signature=signature;if(this.active)this.invalidate();}
      if(this.active)this.pump();
    }
    invalidate() {this.sequence++;this.run?.abort();this.run=null;}
    // The file's own question can be asked once its first pass is in, when the server says so
    // (question_ready: its text is all indexed and no page or image waits for a reading). Its
    // in-depth pass goes on in the background. An 85-page PDF used to hold its first question back
    // for twelve requests in a row, 161 seconds. Only the question that is asked from the file's
    // excerpts at once can do this; a baseline built first still needs the whole review.
    askable(file) {
      return this.hooks.provisional?.()===true&&file.analysis?.question_ready===true&&file.analysis?.phase==="deep"&&
        !file.analysis?.review_stopped&&!file.analysis?.error&&["ready","partial"].includes(file.status)&&Number(file.chunk_count)>0;
    }
    setPhase(phase,error="",retryAvailable=false) {this.phase=phase;this.error=error;this.retryAvailable=retryAvailable;this.hooks.onStatus?.(this);}
    retry() {if(!this.active)return;this.failedIntent=null;this.invalidate();this.error="";if(this.pauseFailed)this.pause(true);this.pump();}
    async pump() {
      if(!this.active||this.run||this.failedIntent===this.intentSignature)return;
      const state=this.snapshot;
      if(this.batches.size||state.uploading){this.setPhase("uploading");return;}
      if(state.mutating){this.setPhase("reviewing");return;}
      if(state.connectionError){this.setPhase("error","Couldn’t check file status. Your interview is still available in this tab.",true);return;}
      const relevant=state.documents.filter(file=>!file.archived&&file.analysis?.disposition!=="parked");
      const newErrors=(state.uploadErrors||[]).filter(error=>!this.oldErrors.has(JSON.stringify(error)));
      const failed=relevant.filter(file=>file.status==="error"||file.analysis?.phase==="error"||file.analysis?.error);
      if(newErrors.length||failed.length){this.setPhase("error","Check the file issue in Assets. Your interview is still available in this tab.");return;}
      // phase complete is terminal even when extraction/review coverage is partial.
      // review_complete=false describes coverage, not a still-running job.
      const waiting=relevant.filter(file=>!this.askable(file)&&!file.analysis?.review_stopped&&!["error"].includes(file.status)&&file.analysis?.phase!=="error"&&file.analysis?.phase!=="complete");
      if(waiting.length){this.setPhase("reviewing");return;}
      const available=relevant.filter(file=>["ready","partial"].includes(file.status)&&(file.analysis?.phase==="complete"||this.askable(file))&&Number(file.chunk_count)>0);
      const run=new AbortController(),sequence=this.sequence;this.run=run;
      const valid=()=>this.active&&this.run===run&&this.sequence===sequence&&!run.signal.aborted;
      try {
        await this.paused;if(!valid())return;
        if(!available.some(file=>this.ids.has(file.id)||!this.originalIds.has(file.id))){const own=state.documents.filter(file=>this.ids.has(file.id)||!this.originalIds.has(file.id));
          const reason=!own.length?"empty":own.every(file=>file.archived||file.analysis?.disposition==="parked")?"parked":own.some(file=>file.analysis?.review_stopped)?"paused":"unreadable";
          this.hooks.onEmpty?.({reason});if(valid())this.setPhase("ready");return;}
        if(this.hooks.provisional?.()===true&&typeof this.hooks.askProvisional==="function"){
          // The question the file itself raises is asked as soon as the file has been read: a
          // participant used to wait one to seven minutes for the map and its audit before
          // seeing it. Whoever answers this hook completes the notes and the audited map in
          // the background, where a newer answer or a file change makes a late result stale.
          this.setPhase("question");
          const asked=await this.hooks.askProvisional({signal:run.signal,documents:available});if(!valid())return;
          this.hooks.onComplete(asked,available);if(valid())this.setPhase("ready");
          return;
        }
        this.setPhase("baseline");
        const baseline=await this.hooks.buildBaseline({signal:run.signal,documents:available});if(!valid())return;
        this.setPhase("question");
        const result=await this.hooks.askFollowup({signal:run.signal,baseline,documents:available});if(!valid())return;
        this.hooks.onComplete(result,available);if(valid())this.setPhase("ready");
      }catch(error){if(valid()){this.failedIntent=this.intentSignature;this.setPhase("error",error?.message||"Couldn’t complete the file review. Your interview is still available in this tab.",true);}}
      finally {if(this.run===run)this.run=null;}
    }
  }
  window.CollectorDocumentIntake=DocumentIntake;
})();
