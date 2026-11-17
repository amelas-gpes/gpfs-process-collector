"use strict";

// Document attachments are context to review, never automatically accepted process facts.
(() => {
  const MAX_FILE = 64 * 1024 * 1024, MAX_FILES = 20;
  const EXTENSIONS = new Set(["pdf","png","xlsx","xlsm","csv"]);
  // These notices describe what the background review sends (document_service.py): keep them true to it.
  const FILE_NOTICE = "Files are saved on this computer. The AI service can receive file names, the full extracted text (including hidden sheets), and pages or images for visual review. Large files pause for your choice before sending more. Files saved for later pause further background review. Remove stops further review and takes the file out of future interview requests. Use Permanently delete in Removed files to erase its local original and index. Excerpts in earlier saves or submissions remain. Confirm file details in the interview.";
  // The Assets panel says what is needed to add a file; the full limits and the notice are one click away.
  const FILE_FORMATS = "PDF, PNG, XLSX, XLSM or CSV · up to 64 MiB each";
  const EXTRACTION_LIMITS = "Extraction limits: 500 PDF pages, 100 sheets, 2 million populated cells, 40 megapixels per image, and 64 MiB of indexed text in up to 50,000 sections.";
  const FILE_LIMITS = FILE_FORMATS.replace("up to", "Up to") + ". " + EXTRACTION_LIMITS;
  const FILE_NOTICE_LEAD = "Saved on this computer and read by the AI service";
  const PARKED_REVIEW_NOTICE = "Further review is paused while this file is saved for later. A request already sent can finish.";
  // The reviewer's verdict on a file, in the words shown beside its reason.
  const RELEVANCE = {relevant:"related to this process",unclear:"not clearly related to this process",unrelated:"not related to this process"};
  // The same sentence as the interview's source dialog uses for such an excerpt.
  const AI_TRANSCRIPTION_NOTE = "AI visual transcription is unverified; inspect the original before relying on it.";
  const copy = value => JSON.parse(JSON.stringify(value));
  const abortError = () => new DOMException("Cancelled", "AbortError");
  const message = error => String(error?.message || "The file request could not be completed.").slice(0,600);
  const fileMessage = error => /interviewer|interview service|your answer is safe|failed to fetch|networkerror|load failed/i.test(message(error)) ? "Could not reach the local file service. Keep this interview open and try again." : message(error);
  const label = value => typeof value === "string" ? value : "";

  class Documents {
    constructor(options) {
      if (typeof options?.requestJSON !== "function") throw new TypeError("A same-origin JSON request function is required.");
      this.remoteIntents=new Map();this.channel=null;this.options=options;this.doc=options.document||window.document;this.generation=0;this.revision=0;this.scope=null;this.documents=[];
      this.uploads=[];this.uploadErrors=[];this.seen=new Map();this.pollFailures=0;this.pollTimer=null;this.polling=null;this.sessionPromise=null;
      this.unavailableWorkspaces=[];this.scopeUnavailable=false;this.reading=null;
      // The server's file store itself failed (code document_store_unavailable): the interview can go on
      // without these files, so the same "Start new file workspace" action is offered.
      this.storeUnavailable=false;
      // Files removed from this conversation: kept on this computer, unused, listed so they can be restored.
      this.removed=[];this.removedOpen=false;
      // The server's count of the files it keeps for this interview (removed ones included) and its maximum.
      this.limit=null;
      this.mutating=0;this.sequence=0;this.batchSequence=0;this.lifecycleStamp="";this.disposed=false;this.restoreFocus=true;this.connectionError="";this.lastError="";this.source=null;
      this.uploadQueue=Promise.resolve();this.controller=new AbortController();this.actions=new Set();this.actionErrors=new Map();this.expandedAssets=new Map();this.build();this.render();
      this.suspended=false;this.pagehide=()=>this.suspend();this.pageshow=event=>{if(event.persisted)this.resume();};
      this.visibilityChanged=()=>{if(this.doc.hidden){clearTimeout(this.pollTimer);this.pollTimer=null;}else if(this.scope)this.schedule(0);};
      this.doc.addEventListener?.("visibilitychange",this.visibilityChanged);
      window.addEventListener?.("pagehide",this.pagehide);window.addEventListener?.("pageshow",this.pageshow);
      this.buildDropZone();
    }
    node(tag,className,text) {const node=this.doc.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=String(text);return node;}
    button(text,className,fn) {const button=this.node("button",className,text);button.type="button";button.addEventListener("click",fn);return button;}
    control(button,document,action,identity="") {
      button.classList.add("document-control");button.dataset.documentControl=JSON.stringify([document.id,action,identity]);
      if(this.options.voiceActive?.()&&["review-now","retry-review","revisit"].includes(action)){
        button.title="Pauses voice while the file is reviewed. Select Continue talking when ready.";
        button.setAttribute("aria-label",button.textContent+". "+button.title);
      }
      return button;
    }
    visible(node) {for(let current=node;current;current=current.parentElement)if(current.hidden||(current.tagName==="DIALOG"&&!current.open))return false;return true;}
    focusDocumentFallback(id,scroll=false) {
      const card=this.body.querySelector?.(`[data-document-id="${this.safeId(id)}"]`)||this.body.querySelector?.(".documents-card");
      const target=card||(this.assets?this.attachButton:this.dialog?.querySelector?.(".documents-close"))||this.attachButton;
      if(target&&!target.disabled&&this.visible(target)){if(card)card.tabIndex=-1;target.focus?.({preventScroll:true});if(scroll)target.scrollIntoView?.({block:"nearest"});}
    }
    watchScope() {
      this.channel?.close();this.channel=null;
      if(!this.scope||typeof window.BroadcastChannel!=="function")return;
      try {
        this.channel=new window.BroadcastChannel("collector-files-"+this.scope);
        this.channel.onmessage=event=>{if(event.data==="changed"&&!this.doc.hidden)this.schedule(0);};
      }catch{/* Refresh on returning to the tab also checks the file workspace. */}
    }
    notifyWorkspace() {this.channel?.postMessage("changed");}
    emit(event) {this.options.onEvent?.(event);}
    lifecycle() {
      return {scope:this.scope,generation:this.generation,documents:copy(this.documents),uploading:this.uploads.length,mutating:this.mutating,
        connectionError:this.connectionError,uploadErrors:this.uploadErrors.map(error=>({name:error.name,message:error.message}))};
    }
    changed(emit=true) {
      const state=this.lifecycle(),stamp=JSON.stringify(state);
      if(stamp===this.lifecycleStamp)return;
      this.lifecycleStamp=stamp;
      if(emit)this.emit({type:"changed",state});
    }
    discuss(document,question) {
      const allowed=this.options.canDiscuss?.();
      if(allowed===false||typeof allowed==="string"){
        this.options.notice?.(typeof allowed==="string"?allowed:"Wait for the current reply to finish, then choose Discuss again. The file question is retained.");return;
      }
      this.close(false);this.options.onDiscuss?.();this.emit({type:"question",document:copy(document),question:copy(question)});
    }
    context() {const value=this.options.getContext?.()||{};return {context:value.context||{},turns:value.turns||[],focus:value.focus||"",current_question:value.current_question||""};}
    current(generation) {return !this.disposed&&generation===this.generation;}
    allowed() {return !this.disposed&&!this.suspended&&!this.scopeUnavailable&&(this.options.canUpload?.()!==false);}
    fileDrag(event) {return Array.from(event.dataTransfer?.types||[]).includes("Files");}
    dropInside(event) {
      const sheet=this.assets?.closest?.("dialog");
      return Boolean(this.dropTarget&&!this.dropTarget.hidden&&(this.dropTarget.contains(event.target)||this.assets?.contains(event.target)||sheet?.open&&sheet.contains(event.target)));
    }
    clearDrop() {this.dragDepth=0;if(this.dropOverlay){this.dropOverlay.hidden=true;if(this.dropOverlay.parentElement!==this.dropTarget)this.dropTarget.append(this.dropOverlay);}}
    buildDropZone() {
      this.dropTarget=this.options.dropTarget||this.doc.getElementById("interview-view");this.dragDepth=0;this.dropListeners=[];
      if(!this.dropTarget)return;
      this.dropTarget.classList.add("document-drop-zone");
      this.dropOverlay=this.node("div","document-drop-overlay");this.dropOverlay.hidden=true;
      this.dropOverlay.setAttribute("role","status");this.dropOverlay.setAttribute("aria-live","polite");this.dropOverlay.setAttribute("aria-atomic","true");
      const panel=this.node("div","document-drop-panel");this.dropTitle=this.node("strong");this.dropHelp=this.node("span");panel.append(this.dropTitle,this.dropHelp);this.dropOverlay.append(panel);this.dropTarget.append(this.dropOverlay);
      const listen=(target,name,fn)=>{target.addEventListener?.(name,fn);this.dropListeners.push([target,name,fn]);};
      const show=()=>{
        if(this.disposed||this.suspended||this.dropTarget.hidden)return this.clearDrop();
        const full=this.full(),allowed=this.allowed();
        this.dropTitle.textContent=!allowed?"Files can't be attached right now":full?(this.removed.length?`This interview has used its ${this.maximum()} file slots`:`This conversation has ${this.maximum()} files`):"Drop files into this conversation";
        this.dropHelp.textContent=!allowed?(this.options.uploadBlockedReason?.()||"Finish loading the interview, then try again."):full?(this.removed.length?"Removed files keep their slots. Restore one in Assets to use it again.":"The conversation file limit has been reached."):FILE_LIMITS;
        const sheet=this.assets?.closest?.("dialog");if(sheet?.open&&this.dropOverlay.parentElement!==sheet)sheet.append(this.dropOverlay);
        this.dropOverlay.hidden=false;
      };
      listen(this.dropTarget,"dragenter",event=>{if(!this.fileDrag(event))return;event.preventDefault();this.dragDepth++;show();});
      listen(this.dropTarget,"dragleave",event=>{
        if(!this.fileDrag(event)&&!this.dragDepth)return;
        this.dragDepth=Math.max(0,this.dragDepth-1);
        if(event.relatedTarget&&this.dropTarget.contains(event.relatedTarget))return;
        if(!this.dragDepth)this.clearDrop();
      });
      // The window guard also prevents an external drop outside the conversation from navigating
      // away from unsaved work. Only a drop inside the visible conversation can upload files.
      listen(window,"dragover",event=>{
        if(!this.fileDrag(event))return;event.preventDefault();
        const inside=this.dropInside(event);if(inside)show();else this.clearDrop();
        event.dataTransfer.dropEffect=inside&&this.allowed()&&!this.full()?"copy":"none";
      });
      listen(window,"drop",event=>{
        if(!this.fileDrag(event))return;
        event.preventDefault();const inside=this.dropInside(event);this.clearDrop();
        if(!inside)return;
        if(!this.allowed()){this.options.notice?.(this.options.uploadBlockedReason?.()||"Files can't be attached right now. Finish loading the interview, then try again.",true);return;}
        const items=Array.from(event.dataTransfer.items||[]);
        const directories=items.some(item=>{try{return item.webkitGetAsEntry?.()?.isDirectory===true;}catch{return false;}});
        if(directories){this.options.notice?.("Drop individual files rather than folders.",true);return;}
        const files=Array.from(event.dataTransfer.files||[]);
        if(!files.length){this.options.notice?.("The dropped files could not be read. Try Add files instead.",true);return;}
        void this.addFiles(files,{reveal:false});
      });
      listen(window,"dragend",()=>this.clearDrop());listen(window,"blur",()=>this.clearDrop());
      listen(window,"keydown",event=>{if(event.key==="Escape")this.clearDrop();});
    }
    build() {
      this.assets=this.doc.getElementById("document-assets");
      if(this.assets){this.buildAssets();return;}
      this.controls=this.doc.getElementById("document-controls");this.strip=this.doc.getElementById("document-strip");
      if(!this.controls||!this.strip)throw new Error("Document controls and strip mounts are required.");
      this.controls.classList.add("document-controls");this.strip.classList.add("document-strip");
      this.attachButton=this.button("", "document-attach",()=>this.attach());this.attachButton.title="Add files";this.attachButton.setAttribute("aria-label","Add files");
      const icon=this.doc.createElementNS("http://www.w3.org/2000/svg","svg");icon.setAttribute("viewBox","0 0 24 24");icon.setAttribute("aria-hidden","true");
      const clip=this.doc.createElementNS("http://www.w3.org/2000/svg","path");clip.setAttribute("d","M8 13.5 15.2 6.3a3.2 3.2 0 0 1 4.5 4.5l-9.2 9.3a5 5 0 0 1-7.1-7.1l9.3-9.3M6.8 15l8.4-8.4");clip.setAttribute("fill","none");clip.setAttribute("stroke","currentColor");clip.setAttribute("stroke-width","1.5");clip.setAttribute("stroke-linecap","round");icon.append(clip);this.attachButton.append(icon);
      this.countButton=this.button("Files", "document-count",()=>this.open());this.countButton.setAttribute("aria-haspopup","dialog");this.countButton.setAttribute("aria-controls","documents-dialog");
      this.input=this.node("input");this.input.type="file";this.input.accept=".pdf,.png,.xlsx,.xlsm,.csv";this.input.multiple=true;this.input.hidden=true;
      this.input.addEventListener("change",()=>{const files=Array.from(this.input.files||[]);this.input.value="";this.addFiles(files);});
      this.controls.replaceChildren(this.attachButton,this.countButton,this.input);
      this.dialog=this.doc.getElementById("documents-dialog");
      if(!this.dialog){this.dialog=this.node("dialog");this.dialog.id="documents-dialog";this.doc.body.append(this.dialog);}
      this.dialog.classList.add("documents-dialog");this.dialog.setAttribute("aria-labelledby","documents-title");
      const header=this.node("div","documents-heading"),title=this.node("h2","","Files for this conversation");title.id="documents-title";
      const close=this.button("×","documents-close",()=>this.close());close.setAttribute("aria-label","Close files");header.append(title,close);
      this.dialog.addEventListener("close",()=>{if(this.restoreFocus)this.returnFocus?.focus?.({preventScroll:true});});
      this.body=this.node("div","documents-body");this.body.setAttribute("aria-live","off");
      this.liveStatus=this.node("p","documents-live-status");this.liveStatus.setAttribute("role","status");this.liveStatus.setAttribute("aria-live","polite");this.liveStatus.setAttribute("aria-atomic","true");
      const footer=this.node("div","documents-footer"),add=this.button("Add files","documents-add",()=>this.attach());
      this.usage=this.node("p","documents-usage");this.usage.hidden=true;
      footer.append(add,this.usage,this.node("p","",FILE_LIMITS),this.node("p","",FILE_NOTICE));
      this.dialog.replaceChildren(header,this.liveStatus,this.body,footer);
    }
    buildAssets() {
      this.assets.classList.add("document-assets");
      const header=this.node("div","documents-assets-heading");
      this.attachButton=this.button("Add files","documents-add",()=>this.attach());
      this.input=this.node("input");this.input.type="file";this.input.accept=".pdf,.png,.xlsx,.xlsm,.csv";this.input.multiple=true;this.input.hidden=true;
      this.input.addEventListener("change",()=>{const files=Array.from(this.input.files||[]);this.input.value="";this.addFiles(files);});
      const formats=this.node("p","documents-assets-formats",FILE_FORMATS);
      this.usage=this.node("p","documents-assets-formats documents-usage");this.usage.id="documents-usage";this.usage.hidden=true;
      this.attachButton.setAttribute("aria-describedby","documents-usage");
      header.append(this.attachButton,this.input,formats,this.usage);
      this.liveStatus=this.node("p","documents-live-status");this.liveStatus.setAttribute("role","status");this.liveStatus.setAttribute("aria-live","polite");this.liveStatus.setAttribute("aria-atomic","true");
      this.body=this.node("div","documents-body");this.body.setAttribute("aria-live","off");this.body.setAttribute("aria-label","Uploaded files");
      const footer=this.node("details","documents-assets-privacy");
      footer.append(this.node("summary","",FILE_NOTICE_LEAD),this.node("p","",FILE_NOTICE),this.node("p","",EXTRACTION_LIMITS));
      this.assets.replaceChildren(header,this.liveStatus,this.body,footer);
    }
    attach() {if(!this.allowed())return;this.input.click();}
    open(documentId) {
      if(this.disposed)return;this.returnFocus=this.doc.activeElement;this.restoreFocus=true;
      if(this.assets){if(documentId){this.expandedAssets.set(documentId,true);this.render();}this.options.onOpen?.();}
      else if(!this.dialog.open)this.dialog.showModal();
      const card=documentId&&this.body.querySelector?.(`[data-document-id="${this.safeId(documentId)}"]`);
      if(card){card.scrollIntoView?.({block:"nearest"});if(this.assets)card.focus?.({preventScroll:true});}
    }
    safeId(id) {return String(id).replace(/[^a-zA-Z0-9_-]/g,"");}
    close(restoreFocus=true) {this.restoreFocus=restoreFocus;if(this.dialog?.open)this.dialog.close();}
    async ensureSession() {
      if(this.disposed||this.suspended)throw abortError();
      if(this.scope)return this.scope;
      if(this.sessionPromise)return this.sessionPromise;
      const generation=this.generation,signal=this.controller.signal;
      const task=(async()=>{
        const result=await this.options.requestJSON("/api/documents/session",this.context(),{signal,timeout:30000});
        if(!this.current(generation))throw abortError();
        if(typeof result?.scope!=="string"||!result.scope)throw new Error("The local file workspace could not be opened.");
        this.scope=result.scope;this.watchScope();this.setLimit(result.limit);this.setRemoved(result.removed);this.setDocuments(result.documents||[],false);this.options.onDirty?.();return this.scope;
      })();
      this.sessionPromise=task;
      try{return await task;}finally{if(this.sessionPromise===task)this.sessionPromise=null;}
    }
    async addFiles(files,{reveal=true}={}) {
      if(!this.allowed()||!files.length)return;
      const generation=this.generation;
      const available=Math.max(0,this.maximum()-this.used()),accepted=[],unreadable=this.unavailable();
      for(const file of files){
        const extension=String(file.name||"").split(".").pop().toLowerCase();
        const error=Array.from(file.name||"").length>250?"Rename this file to 250 characters or fewer.":!EXTENSIONS.has(extension)?"Choose a PDF, PNG, XLSX, XLSM or CSV file.":unreadable[extension]?unreadable[extension]:!Number.isFinite(file.size)||file.size<1?"This file is empty.":file.size>MAX_FILE?"This file exceeds the 64 MiB limit.":accepted.length>=available?`An interview can hold up to ${this.maximum()} files${this.removed.length?", and removed files keep their slots":""}.`:null;
        if(error){this.uploadErrors.push({name:file.name||"File",message:error});continue;}accepted.push(file);
      }
      this.uploadErrors=this.uploadErrors.slice(-20);
      if(!accepted.length){this.render();if(reveal)this.open();this.changed();return;}
      const batchId=`upload_${++this.batchSequence}`;
      const queued=accepted.map(file=>({key:++this.sequence,name:file.name,status:"Waiting to upload",file}));
      this.uploads.push(...queued);this.mutating++;this.revision++;
      this.emit({type:"upload_started",batchId,names:accepted.map(file=>file.name)});
      this.options.onDirty?.();this.render();this.changed();
      if(this.assets&&reveal&&this.options.revealUploads?.()!==false)this.open();
      const before=this.uploadQueue;
      let release;this.uploadQueue=new Promise(resolve=>{release=resolve;});
      try{
        await before;if(!this.current(generation))return;
        const scope=await this.ensureSession();
        for(const upload of queued){
          if(!this.current(generation))return;
          upload.status="Uploading";this.render();
          try{
            const response=await this.uploadFile(upload.file,scope);
            const result=await response.json().catch(()=>({}));
            if(!this.current(generation))return;
            if(!response.ok)throw new Error(result.error||"The file could not be saved. Please try again.");
            if(!result.document||typeof result.document.id!=="string")throw new Error("The local file response was incomplete.");
            const duplicate=result.duplicate_upload===true||result.document.duplicate_upload===true;
            const restored=result.restored_upload===true||result.document.restored_upload===true;
            if(duplicate){
              if(restored)this.removed=this.removed.filter(item=>item.id!==result.document.id);
              const record=result.document,version=record.analysis?.version;
              const count=!record.archived&&["ready","partial"].includes(record.status)?Number(record.chunk_count)||0:0;
              this.seen.set(record.id,(version??"indexed")+":"+count+":"+(record.analysis?.intent_version||0));
              this.options.notice?.(restored?upload.name+" was restored from Removed files.":upload.name+" is already in Assets. Its existing review was reused.");
            }
            this.upsert(result.document);this.notifyWorkspace();this.emit({type:duplicate?"duplicate":"received",restored,document:copy(result.document)});this.options.onDirty?.();
          }catch(error){
            if(!this.current(generation)||this.controller.signal.aborted)return;
            if(error.name==="TypeError")error=new Error("The file could not be sent. Check that the app is running, then choose Retry upload.");
            if(error.name==="AbortError")error=new Error("Uploading took too long. Check Files before trying again.");
            this.uploadErrors.push({name:upload.name,message:message(error),file:upload.file});this.reportError(error,true);
          }finally{
            if(this.current(generation)){this.uploads=this.uploads.filter(item=>item.key!==upload.key);this.render();this.changed();}
          }
        }
      }catch(error){if(this.current(generation)&&!this.controller.signal.aborted){
        if(error.name==="AbortError")error=new Error("Opening the file workspace took too long. Please try again.");
        this.uploadErrors.push(...queued.map(upload=>({name:upload.name,message:message(error),file:upload.file})));this.uploads=this.uploads.filter(item=>!queued.includes(item));this.reportError(error,true);this.render();
      }}finally{release();if(this.current(generation)){this.mutating=Math.max(0,this.mutating-1);this.revision++;this.changed();this.emit({type:"upload_settled",batchId});this.schedule(0);}}
    }
    async uploadFile(file,scope) {
      const controller=new AbortController(),outer=this.controller.signal,abort=()=>controller.abort();
      outer.addEventListener("abort",abort,{once:true});if(outer.aborted)abort();
      const timer=setTimeout(abort,120000);
      const token=()=>this.options.config?.()?.csrf_token||"";
      const send=sent=>(this.options.fetch||window.fetch.bind(window))("/api/documents/upload",{
        method:"POST",credentials:"same-origin",signal:controller.signal,body:file,
        headers:{...this.options.usageHeaders?.(),"Content-Type":"application/octet-stream","X-CSRF-Token":sent,
          "X-Document-Scope":scope,"X-Document-Filename":encodeURIComponent(file.name)}
      });
      try{
        const sent=token();
        let response=await send(sent);
        if(response.status===403&&this.options.renewToken){
          // The local app restarted and issued a new request token. Nothing of this upload was
          // processed, so it is sent again once. A 403 that names its own cause is left as it is.
          const rejected=typeof response.clone==="function"?await response.clone().json().catch(()=>({})):{};
          if((!rejected.code||rejected.code==="request_token_rejected")&&await this.options.renewToken(sent))response=await send(token());
        }
        return response;
      }finally{clearTimeout(timer);outer.removeEventListener("abort",abort);}
    }
    upsert(document) {this.remoteIntents.delete(document.id);const index=this.documents.findIndex(item=>item.id===document.id);if(index<0)this.documents.push(copy(document));else this.documents[index]=copy(document);this.connectionError="";this.render();this.changed();}
    setDocuments(documents,emit=true) {
      if(!Array.isArray(documents))throw new Error("The local file list was incomplete.");
      const next=documents.filter(item=>item&&typeof item.id==="string");
      const changed=JSON.stringify(next)!==JSON.stringify(this.documents),recovered=Boolean(this.connectionError);
      const previous=new Map(this.documents.map(file=>[file.id,file]));
      if(changed&&emit){
        const ids=new Set(next.map(file=>file.id));
        for(const file of this.documents)if(!ids.has(file.id)){
          this.seen.delete(file.id);this.remoteIntents.delete(file.id);
          this.emit({type:"remote_file",action:"removed",document:copy(file)});
        }
      }
      if(changed)this.documents=copy(next);
      this.connectionError="";this.lastError="";this.scopeUnavailable=false;this.storeUnavailable=false;
      for(const document of this.documents){
        const prior=previous.get(document.id),intent=document.analysis?.intent_version||0;
        if(!prior||(prior.analysis?.intent_version||0)!==intent){
          this.remoteIntents.set(document.id,intent);
          if(emit)this.emit({type:"remote_file",action:!prior?"added":document.analysis?.disposition==="parked"?"parked":"updated",document:copy(document)});
        }
        const version=document.analysis?.version;
        const available=!document.archived&&["ready","partial"].includes(document.status)&&Number(document.chunk_count)>0;
        if((version!==undefined&&version!==null)||available){
        // Native extraction can finish before the first model review. Publish
        // that availability once so the interview can use its exact text now.
        const key=`${version??"indexed"}:${available?document.chunk_count:0}:${document.analysis?.intent_version||0}`;
        if(this.seen.get(document.id)!==key){this.seen.set(document.id,key);if(emit)this.emit({type:"analysis",remote:this.remoteIntents.has(document.id),document:copy(document),analysis:copy(document.analysis||{})});}
      }}
      // Replacing unchanged native controls or excerpts interrupts composing and selecting text.
      if(changed||recovered)this.render();
      this.changed(emit);if(changed&&emit)this.options.onDirty?.();
    }
    setRemoved(removed) {
      // The server's list of removed files. A reply without one leaves the list as it is.
      if(!Array.isArray(removed))return;
      const next=removed.filter(item=>item&&typeof item.id==="string").map(item=>({id:item.id,name:label(item.name),kind:label(item.kind),size:Number(item.size)||0}));
      if(JSON.stringify(next)===JSON.stringify(this.removed))return;
      this.removed=next;this.render();
    }
    // File kinds this computer's Python cannot read (its reader package is missing), each with the server's
    // explanation, from /api/config. Such a file would only fail after upload, looking like a damaged file.
    unavailable() {
      const value=this.options.config?.()?.documents?.unavailable,kinds={};
      if(value&&typeof value==="object")for(const kind of EXTENSIONS)if(typeof value[kind]==="string"&&value[kind].trim())kinds[kind]=value[kind].slice(0,600);
      return kinds;
    }
    // Start over and opening another interview drop this page's reference to the files. Nothing in the app
    // deletes them from this computer, so the prompt and the notice say that they stay.
    keptFilesNote() {
      const kept=this.documents.length+this.removed.length;
      return kept?` The ${kept===1?"file":`${kept} files`} added to this interview ${kept===1?"stays":"stay"} on this computer: the app does not delete ${kept===1?"it":"them"}.`:"";
    }
    setLimit(limit) {
      // A reply without a count leaves the last one as it is.
      if(!limit||typeof limit!=="object")return;
      const whole=value=>Math.max(0,Math.floor(Number(value))||0);
      const next={maximum:whole(limit.maximum)||MAX_FILES,used:whole(limit.used),removed:whole(limit.removed)};
      if(JSON.stringify(next)===JSON.stringify(this.limit))return;
      this.limit=next;this.render();
    }
    maximum() {return this.limit?.maximum||MAX_FILES;}
    // Never fewer than the server counted, plus what this page has added since and is still sending.
    used() {return Math.max(this.limit?.used||0,this.documents.length+this.removed.length)+this.uploads.length;}
    full() {return this.used()>=this.maximum();}
    usageText() {
      const used=this.used(),removed=this.removed.length;
      if(!used)return "";
      const count=`${used} of ${this.maximum()} file slots used${removed?`, ${removed} by removed ${removed===1?"file":"files"}`:""}.`;
      if(!this.full())return count;
      return `${count} No more files can be added to this interview.${removed?" Removed files stay on this computer and keep their slots: restore one to use it again.":""}`;
    }
    // A file whose text has been read while its review has not reported a phase yet. The server reviews
    // every such file (document_service.listing schedules it), so its state is still about to change:
    // a poll that lands between "indexed" and "review started" must not be the last one.
    awaitingReview(item) {return !item.archived&&["ready","partial"].includes(item.status)&&!item.analysis?.phase&&!item.analysis?.review_stopped&&!this.needsReindex(item);}
    pending() {
      // The interview can be waiting on these files (a file intake in its reading stage). While it
      // says so, polling continues whatever state the last poll happened to report.
      if(this.uploads.length||this.options.reviewAwaited?.()===true&&this.documents.length)return true;
      return this.documents.some(item=>!this.reviewError(item)&&(this.reindexChecking(item)||["pending","indexing"].includes(item.status)||["quick","deep"].includes(item.analysis?.phase)||this.awaitingReview(item)));
    }
    schedule(delay) {
      clearTimeout(this.pollTimer);this.pollTimer=null;
      if(this.disposed||this.suspended||this.doc.hidden||this.scopeUnavailable||!this.scope||(delay===undefined&&!this.documents.length&&!this.uploads.length&&!this.removed.length))return;
      if(delay===undefined&&!this.connectionError&&!this.pending())return;
      const next=this.connectionError?Math.min(60000,2000*2**Math.min(this.pollFailures,5)):2000;
      // Refresh schedules its successor after the pending fetch finishes, resuming on visibility.
      this.pollTimer=setTimeout(()=>{this.pollTimer=null;this.refresh();},delay??next);
    }
    async refresh(emit=true) {
      if(this.disposed||this.suspended||!this.scope)return;
      if(this.polling)return this.polling;
      if(this.mutating){this.schedule();return;}
      const generation=this.generation,revision=this.revision,scope=this.scope;
      const task=(async()=>{
        try{
          const result=await this.options.requestJSON("/api/documents/status",{scope,...this.context()},{signal:this.controller.signal,timeout:30000});
          if(!this.current(generation)||scope!==this.scope||revision!==this.revision)return;
          this.pollFailures=0;this.setLimit(result.limit);this.setRemoved(result.removed);
          this.setDocuments(result.documents,emit);
        }catch(error){
          if(this.current(generation)&&scope===this.scope&&revision===this.revision&&error.name!=="AbortError"){
            const unavailable=error.code==="document_scope_unavailable",failed=error.code==="document_store_unavailable";
            this.pollFailures++;
            const detail=fileMessage(error),changed=this.connectionError!==detail||unavailable!==this.scopeUnavailable||failed!==this.storeUnavailable;
            this.scopeUnavailable=unavailable;this.storeUnavailable=failed;
            this.connectionError=detail;this.reportError(error,false,emit);
            if(changed)this.render();
            this.changed(emit);
          }
        }
        finally{if(this.current(generation))this.schedule();}
      })();this.polling=task;
      try{return await task;}finally{if(this.polling===task)this.polling=null;}
    }
    reportError(error,notify,emit=true) {
      const text=fileMessage(error);if(notify)this.options.notice?.(text,true);
      if(this.lastError!==text){this.lastError=text;if(emit)this.emit({type:"error",message:text});}
    }
    async action(document,action,purpose) {
      const key=document.id+":"+action;if(this.disposed||this.suspended||this.documentBusy(document.id)||!this.scope)return;
      const generation=this.generation,position=this.documents.findIndex(item=>item.id===document.id);this.actions.add(key);this.mutating++;this.revision++;
      this.render();this.changed();
      try{
        const result=await this.options.requestJSON("/api/documents/action",{scope:this.scope,id:document.id,action,...(purpose!==undefined?{purpose}:{})},{signal:this.controller.signal,timeout:30000});
        if(!this.current(generation))return;
        this.actionErrors.delete(document.id);
        const restoreCard=["remove","discard_failed"].includes(action)&&(this.doc.activeElement?.dataset?.documentId===document.id||this.doc.activeElement?.dataset?.documentControl?.includes(document.id));
        if(action==="remove"||action==="discard_failed"){this.documents=this.documents.filter(item=>item.id!==document.id);this.seen.delete(document.id);if(this.source?.documentId===document.id)this.source=null;}
        else if(action!=="purge"&&result.document)this.upsert(result.document);
        // Remove can be undone: the file moves to Removed files and Restore brings it back as it was.
        if(action==="remove"){this.removed=[...this.removed.filter(item=>item.id!==document.id),{id:document.id,name:label(document.name),kind:label(document.kind),size:Number(document.size)||0}];this.removedOpen=true;}
        if(action==="restore"||action==="purge")this.removed=this.removed.filter(item=>item.id!==document.id);
        if(["purge","discard_failed"].includes(action)&&this.limit){this.limit.used=Math.max(0,this.limit.used-1);this.limit.removed=this.removed.length;}
        this.options.onDirty?.();this.render();
        this.notifyWorkspace();
        if(["remove","park","revisit","restore","purge","discard_failed","purpose","use"].includes(action))this.emit({type:"disposition",action,document:copy(result.document||document)});
        if(restoreCard)this.focusDocumentFallback(this.documents[Math.min(position,this.documents.length-1)]?.id||"",true);
      }catch(error){if(this.current(generation)&&error.name!=="AbortError"){this.actionErrors.set(document.id,{action,purpose,message:fileMessage(error)});this.reportError(error,true);}}
      finally{if(this.current(generation)){this.actions.delete(key);this.mutating=Math.max(0,this.mutating-1);this.revision++;this.render();this.changed();this.schedule(0);}}
    }
    documentBusy(id) {return [...this.actions].some(key=>key.startsWith(id+":"));}
    // A file indexed by an earlier version of the app. The server first reads it again on this computer,
    // free of charge (reindex_check "pending"); only when its index then differs does it need the paid re-index.
    needsReindex(document) {return Boolean(document.extraction_needs_reindex);}
    reindexChecking(document) {return this.needsReindex(document)&&document.status!=="error"&&document.reindex_check?.outcome==="pending";}
    reindexMessage(document) {
      if(!this.needsReindex(document))return "";
      const updated="Process Collector was updated since this file was indexed.";
      if(this.reindexChecking(document))return `${updated} It is being read again on this computer to confirm that its saved index is still current. Nothing is sent to the AI provider for this check.`;
      if(document.status==="error")return `${updated} Choose Re-index and review to read it with the current version.`;
      const why=document.reindex_check?.outcome==="failed"?"it could not be read again on this computer":document.reindex_check?.outcome==="changed"?"the current version reads it differently":"its saved index predates the current completeness checks";
      return `${updated} Its earlier review does not count as a full review, because ${why}. Choose ${document.analysis?.disposition==="parked"?"Revisit this file":"Re-index and review"} to bring it up to date.`;
    }
    // What the notice after opening a saved interview adds about its files.
    attentionNote() {
      const checking=this.documents.filter(document=>this.reindexChecking(document)).length;
      const attention=this.documents.filter(document=>this.reviewError(document)).length;
      return (checking?` ${checking} saved ${checking===1?"file is":"files are"} being checked again on this computer after an app update.`:"")
        +(attention?` ${attention} saved ${attention===1?"file needs":"files need"} attention in Assets before the interview can be completed.`:"");
    }
    reviewNotice(message) {
      // Previous releases persisted service errors in both the warning and reading limits.
      if(typeof message!=="string"||!message.startsWith("Document review paused: "))return message;
      return message.replace("in OpenAI Platform","in the service’s project settings")
        .replace(/OpenAI (API key|project)/g,"$1").replace(/the OpenAI request/g,"the request to the AI service")
        .replace(/OpenAI/g,"the AI service");
    }
    reviewError(document) {return document.status==="error"||document.analysis?.phase==="error"||Boolean(document.analysis?.error)||(this.needsReindex(document)&&!this.reindexChecking(document));}
    status(document) {
      if(document.analysis?.disposition==="parked")return "Saved for later";
      if(document.status==="error")return "Could not read file";
      if(this.reindexChecking(document))return "Checking after update";
      if(this.needsReindex(document))return "Needs re-indexing";
      if(document.analysis?.phase==="error"||document.analysis?.error)return "Review paused";
      if(this.actionErrors.has(document.id))return "Action needs attention";
      if(document.analysis?.review_stopped)return "Review stopped";
      if(document.analysis?.disposition==="needs_reason")return "Needs your direction";
      if(["pending","indexing"].includes(document.status))return "Reading file";
      if(document.analysis?.phase==="deep")return "Reading in depth";
      if(document.analysis?.phase==="quick"||!document.analysis?.summary)return "Checking relevance";
      if(this.unread(document))return "Not yet read in this interview";
      if(document.status==="partial")return "Partly readable";
      return "Ready to review";
    }
    // The app reports which files the interviewer has received readable text from, how many the
    // latest request left out and which it carried. Until it does, cards keep their plain review status.
    // `carried` counts excerpts that are already cited and that the latest request could not read again.
    setReading(reading) {
      const next=reading?{read:[...new Set(reading.read||[])].sort(),omitted:Math.max(0,Number(reading.omitted)||0),
        sent:Array.isArray(reading.sent)?[...new Set(reading.sent)].sort():null,carried:Math.max(0,Math.floor(Number(reading.carried)||0))}:null;
      if(JSON.stringify(next)===JSON.stringify(this.reading))return;
      this.reading=next;this.render();
    }
    readable(document) {return !document.archived&&document.analysis?.disposition!=="parked"&&["ready","partial"].includes(document.status)&&Number(document.chunk_count)>0;}
    unread(document) {return Boolean(this.reading)&&this.readable(document)&&!this.reading.read.includes(document.id);}
    // A file read earlier that the latest update carried no text from: it was not selected, or it was
    // selected after the reading limit was used up. Known only once the app reports which files were carried.
    leftOut(document) {return Boolean(this.reading?.sent)&&this.readable(document)&&!this.unread(document)&&!this.reading.sent.includes(document.id);}
    stageDetail(document) {
      const analysis=document.analysis||{},parts=[];
      // An index from an earlier version counts for nothing until it is confirmed: "0/5 units indexed" beside
      // "1 of 1 sections reviewed" would describe that as two contradicting facts.
      if(this.needsReindex(document))return "Indexed by an earlier version; not counted until it is confirmed.";
      const indexed=Number(document.coverage?.indexed_units),total=Number(document.coverage?.total_units);
      if(Number.isFinite(indexed)&&Number.isFinite(total)&&total>0)parts.push(`${indexed}/${total} ${({pdf:"pages",png:"images",xls:"sheets",xlsx:"sheets",xlsm:"sheets",csv:"rows"})[document.kind]||"units"} indexed.`);
      const coverage=document.coverage||{};
      if(document.kind==="pdf"&&Number.isFinite(coverage.text_indexed_units)&&coverage.visual_pending_units>0)
        parts.push(coverage.text_indexed_units+" pages with indexed text; "+coverage.visual_pending_units+" pages still have unread visual content.");
      const reviewed=Number(analysis.reviewed_chunks),chunks=Number(analysis.total_chunks);
      if(Number.isFinite(reviewed)&&Number.isFinite(chunks)&&chunks>0)parts.push(`${reviewed} of ${chunks} sections reviewed.`);
      const requests=this.requestsLeft(document);
      if(requests&&this.reviewRunning(document))parts.push(`About ${requests} more review ${requests===1?"request":"requests"} to the AI service.`);
      else if(requests&&analysis.review_stopped&&!this.reviewError(document))parts.push(`Continuing would send about ${requests} more review ${requests===1?"request":"requests"} to the AI service.`);
      if(this.leftOut(document))parts.push("Left out of the latest update.");
      return parts.join(" ");
    }
    // A background review that is sending, or about to send, this file's text to the provider.
    reviewRunning(document) {return !this.reviewError(document)&&!document.analysis?.review_stopped&&(["pending","indexing"].includes(document.status)||["quick","deep"].includes(document.analysis?.phase));}
    // The first assessment says about how many requests reviewing the whole file takes; this is the share still to come.
    requestsLeft(document) {
      const analysis=document.analysis||{},estimate=Number(analysis.estimated_requests);
      if(!Number.isFinite(estimate)||estimate<1)return 0;
      const reviewed=Number(analysis.reviewed_chunks),chunks=Number(analysis.total_chunks);
      return Math.ceil(estimate*(Number.isFinite(reviewed)&&Number.isFinite(chunks)&&chunks>0?Math.min(1,Math.max(0,1-reviewed/chunks)):1));
    }
    relevanceNote(document) {
      // The verdict that decided whether the interview uses this file, with the reviewer's reason. Model text: shown as text.
      const analysis=document.analysis||{},verdict=RELEVANCE[analysis.relevance];
      if(!verdict&&!analysis.selected_by_participant)return null;
      const reason=typeof analysis.relevance_reason==="string"?analysis.relevance_reason.trim():"";
      const parts=verdict?[`The reviewer judged this file ${verdict}.`,...(reason?[`Its reason: ${reason}`]:[])]:[];
      if(analysis.selected_by_participant)parts.push(verdict&&analysis.relevance!=="relevant"?"You chose to use it in the interview anyway.":"You chose to use this file in the interview.");
      return this.node("p","documents-progress documents-relevance",parts.join(" "));
    }
    render() {
      if(this.disposed)return;
      const total=this.documents.length+this.uploads.length;
      const counts=new Map();this.documents.forEach(document=>{const status=this.status(document);counts.set(status,(counts.get(status)||0)+1);});
      const announcement=[`${total} ${total===1?"file":"files"}`,...[...counts].map(([status,count])=>`${count} ${status.toLowerCase()}`),...(this.uploads.length?[`${this.uploads.length} uploading`]:[]),...(this.uploadErrors.length?[`${this.uploadErrors.length} file ${this.uploadErrors.length===1?"issue":"issues"}`]:[]),...(this.removed.length?[`${this.removed.length} removed, can be restored`]:[])].join(". ");
      if(this.liveStatus.textContent!==announcement)this.liveStatus.textContent=announcement;
      this.attachButton.disabled=!this.allowed()||this.full();
      this.attachButton.title=!this.allowed()?(this.options.uploadBlockedReason?.()||"File uploads are unavailable."):"Add files";
      // "7 of 20 file slots used, 3 by removed files." and, at the limit, why Add files is unavailable.
      const usage=this.usageText();if(this.usage.textContent!==usage)this.usage.textContent=usage;this.usage.hidden=!usage;
      const needsAction=this.documents.filter(file=>!file.archived&&file.analysis?.disposition==="needs_reason").length;
      this.options.onCountChange?.({total,...(needsAction?{needsAction}:{}),issues:this.uploadErrors.length+this.documents.filter(document=>this.reviewError(document)||this.actionErrors.has(document.id)).length});
      if(this.strip){
      this.countButton.textContent=total?`Files ${total}`:"Files";this.countButton.hidden=!total&&!this.uploadErrors.length;
      this.strip.hidden=!total&&!this.uploadErrors.length;this.strip.replaceChildren();
      for(const document of this.documents){const chip=this.button("",`document-chip${this.reviewError(document)||this.actionErrors.has(document.id)?" document-chip-error":""}`,()=>this.open(document.id));
        chip.setAttribute("aria-label",`${document.name||"File"} · ${this.status(document)}`);chip.append(this.node("span","document-chip-name",document.name||"File"),this.node("span","document-chip-status",this.status(document)));this.strip.append(chip);
      }
      for(const upload of this.uploads)this.strip.append(this.node("span","document-chip document-chip-pending",`${upload.name} · ${upload.status}…`));
      if(this.uploadErrors.length){const errors=this.button(`${this.uploadErrors.length} file ${this.uploadErrors.length===1?"issue":"issues"}`,"document-chip document-chip-error",()=>this.open());this.strip.append(errors);}
      }
      // Preserve a purpose currently being typed across polling and upload progress renders.
      const drafts=new Map();this.body.querySelectorAll?.("[data-document-purpose]").forEach(input=>drafts.set(input.dataset.documentPurpose,input.value));
      const focused=this.doc.activeElement,purposeFocus=focused?.dataset?.documentPurpose,selection=purposeFocus?[focused.selectionStart,focused.selectionEnd]:null;
      const sourceFocus=focused?.dataset?.documentSourceHeading,cardFocus=focused?.dataset?.documentId,toggleFocus=focused?.dataset?.documentToggle,controlFocus=focused?.dataset?.documentControl,scrollTop=this.body.scrollTop;
      this.body.replaceChildren();
      if(this.connectionError){
        const error=this.node("div","documents-warning");
        error.append(this.node("p","",`Saved file details are retained. ${this.connectionError}`),this.button("Try again","documents-text-button",()=>this.refresh()));
        if(this.scopeUnavailable){
          // What app.js does on "workspace_replaced": keep this true to it.
          error.append(this.node("p","","To upload the originals here, start a new file workspace. Excerpts already saved with this interview stay with it as references. This computer cannot read their files, so those references are not sent with later updates and are left out of submissions."));
          const replace=this.button("Start new file workspace","documents-text-button",()=>this.startNewWorkspace());
          replace.disabled=Boolean(this.mutating);error.append(replace);
        }else if(this.storeUnavailable){
          error.append(this.node("p","","To continue without these files, start a new file workspace. Your saved references stay with the interview."));
          const replace=this.button("Start new file workspace","documents-text-button",()=>this.startNewWorkspace());
          replace.disabled=Boolean(this.mutating);error.append(replace);
        }
        this.body.append(error);
      }
      // A missing reader is said before anyone chooses a file, and the file picker stops offering that kind.
      const unreadable=this.unavailable(),reasons=[...new Set(Object.values(unreadable))];
      this.input.accept=[...EXTENSIONS].filter(kind=>!unreadable[kind]).map(kind=>"."+kind).join(",");
      if(reasons.length){const warning=this.node("div","documents-warning documents-unreadable-kinds");warning.setAttribute("role","status");for(const reason of reasons)warning.append(this.node("p","",reason));this.body.append(warning);}
      const priorFiles=this.unavailableWorkspaces.flatMap(workspace=>workspace.documents);
      if(priorFiles.length){
        const details=this.node("details","documents-limitations"),list=this.node("ul");
        details.append(this.node("summary","","Saved references from previous file workspaces"));
        for(const file of priorFiles)list.append(this.node("li","",file.name||"File"));
        details.append(list);this.body.append(details);
      }
      if(this.reading&&this.documents.length){const count=Math.max(this.reading.omitted,this.documents.filter(document=>this.leftOut(document)).length);if(count)this.body.append(this.node("p","documents-progress documents-reading-note",`${count} ${count===1?"file was":"files were"} left out of the latest update. Each update reads the files already cited, any file not yet read and up to six others, as far as the limit for one update allows.`));}
      if(this.reading?.carried&&this.documents.length){const count=this.reading.carried;this.body.append(this.node("p","documents-progress documents-reading-note",`${count} ${count===1?"excerpt that your notes or workflow cite was":"excerpts that your notes or workflow cite were"} not read again in the latest update, because the excerpts in use are more than one update can read. What cites ${count===1?"it":"them"} is kept as it is.`));}
      let issueParent=this.body;
      if(this.uploadErrors.length>2){
        const details=this.node("details","documents-limitations documents-upload-issues");
        details.append(this.node("summary","",this.uploadErrors.length+" upload issues"));
        details.append(this.button("Dismiss all issues","documents-text-button",()=>{this.uploadErrors=[];this.render();this.changed();}));
        this.body.append(details);issueParent=details;
      }
      const focusIssue=index=>{
        const buttons=[...(this.body.querySelectorAll?.(".document-upload-issue")||[])];
        const next=buttons[Math.min(index,buttons.length-1)]||this.attachButton;
        next?.focus?.({preventScroll:true});next?.scrollIntoView?.({block:"nearest"});
      };
      this.uploadErrors.forEach((error,index)=>{
        const item=this.node("div","documents-warning");item.append(this.node("strong","",error.name),this.node("p","",error.message));
        if(error.file){
          const retry=this.button("Retry upload","documents-text-button",()=>{if(!this.allowed())return;this.uploadErrors.splice(index,1);void this.addFiles([error.file]);focusIssue(index);});
          retry.disabled=!this.allowed();retry.setAttribute("aria-label","Retry upload for "+error.name);item.append(retry);
        }
        const dismiss=this.button("Dismiss issue","documents-text-button document-upload-issue",()=>{this.uploadErrors.splice(index,1);this.render();this.changed();focusIssue(index);});
        dismiss.setAttribute("aria-label","Dismiss issue for "+error.name);item.append(dismiss);issueParent.append(item);
      });
      if(!total&&!this.uploadErrors.length)this.body.append(this.node("p","documents-empty","Drop reference files anywhere in the interview."));
      for(const upload of this.uploads)this.body.append(this.node("p","documents-upload",`${upload.name} · ${upload.status}…`));
      for(const document of this.documents)this.renderDocument(document,drafts);
      this.renderRemoved();
      this.sourceHeading=null;if(this.source)this.renderSource();this.body.scrollTop=scrollTop;
      if(sourceFocus&&this.sourceHeading?.dataset.documentSourceHeading===sourceFocus&&this.visible(this.sourceHeading))this.sourceHeading.focus?.({preventScroll:true});
      if(cardFocus)this.focusDocumentFallback(cardFocus);
      if(toggleFocus){
        const toggle=[...this.body.querySelectorAll(".documents-detail-toggle")].find(button=>button.dataset.documentToggle===toggleFocus);
        if(toggle)toggle.focus?.({preventScroll:true});else this.focusDocumentFallback(toggleFocus);
      }
      if(controlFocus){const control=[...this.body.querySelectorAll(".document-control")].find(button=>button.dataset.documentControl===controlFocus);if(control&&!control.disabled&&this.visible(control))control.focus?.({preventScroll:true});else this.focusDocumentFallback(JSON.parse(controlFocus)[0]);}
      if(purposeFocus){const input=[...this.body.querySelectorAll("[data-document-purpose]")].find(node=>node.dataset.documentPurpose===purposeFocus);if(input){input.focus?.({preventScroll:true});if(selection&&input.setSelectionRange)input.setSelectionRange(...selection);}else this.focusDocumentFallback(purposeFocus);}
    }
    renderDocument(document,drafts) {
      const card=this.node("section","documents-card");card.dataset.documentId=this.safeId(document.id);
      if(this.assets){card.tabIndex=-1;card.setAttribute("aria-label",document.name||"File");}
      const head=this.node("div","documents-card-heading"),title=this.node("div");title.append(this.node("h3","",document.name||"File"),this.node("p","documents-file-meta",`${document.kind||"Document"} · ${this.size(document.size)}`));
      // The button says what it does. It does not erase: the original and its text index stay on this computer.
      const remove=this.control(this.button("Remove from interview","documents-text-button",()=>this.action(document,"remove")),document,"remove");remove.setAttribute("aria-label",`Remove ${document.name||"file"} from this conversation. It is kept on this computer.`);remove.title="Kept on this computer. It can be restored from Removed files.";head.append(title,remove);card.append(head);
      card.setAttribute("aria-busy",String(this.documentBusy(document.id)));
      const analysis=document.analysis||{};
      if(document.status==="error"&&!document.chunk_count){
        const discard=this.control(this.button("Discard failed upload","documents-text-button",()=>{
          if(window.confirm("Delete the failed upload "+document.name+" from this computer and free its file slot?"))void this.action(document,"discard_failed");
        }),document,"discard_failed");
        discard.disabled=this.documentBusy(document.id);card.append(discard);
      }
      const stage=this.node("div","documents-stage");stage.dataset.state=this.reviewError(document)||this.actionErrors.has(document.id)?"error":analysis.disposition==="parked"||analysis.review_stopped?"later":this.reindexChecking(document)||["pending","indexing"].includes(document.status)||["quick","deep"].includes(analysis.phase)?"working":"ready";
      stage.append(this.node("strong","documents-stage-label",this.status(document)));const detail=this.stageDetail(document);if(detail)stage.append(this.node("span","documents-stage-detail",detail));card.append(stage);
      // Save for later does not stop the background review; say so for as long as it is still running.
      if(analysis.disposition==="parked"&&this.reviewRunning(document))card.append(this.node("p","documents-progress documents-parked-review",PARKED_REVIEW_NOTICE));
      // Stop review ends the requests and keeps the file: indexed, searchable and readable by the interview. Remove takes it out.
      if(this.reviewRunning(document)){const stop=this.control(this.button("Stop review","documents-text-button",()=>this.action(document,"stop")),document,"stop-review");stop.setAttribute("aria-label",`Stop the background review of ${document.name||"this file"}`);card.append(stop);}
      else if(analysis.review_stopped&&!this.reviewError(document)){
        card.append(this.node("p","documents-progress documents-review-stopped","The background review of this file is stopped. Its text stays searchable and the interview can still read it."+(analysis.acknowledgement?" "+analysis.acknowledgement:"")));
        const resume=this.control(this.button("Continue review","documents-text-button",()=>this.action(document,"continue")),document,"continue-review");resume.setAttribute("aria-label",`Continue the background review of ${document.name||"this file"}`);card.append(resume);
      }
      // Pages or images whose reading returned nothing can be asked for again by themselves; the rest of the file is not sent again.
      const unread=Array.isArray(analysis.unreadable_sources)?analysis.unreadable_sources.length:0;
      if(unread&&!this.reviewError(document)&&!this.reviewRunning(document)&&!analysis.review_stopped){
        card.append(this.node("p","documents-progress documents-unread-pages",`${unread} ${unread===1?"page or image":"pages or images"} returned no reading in the last review and ${unread===1?"is":"are"} listed under Reading limits. Read again sends only ${unread===1?"that one":"those"} to the AI service.`));
        const again=this.control(this.button("Read again","documents-text-button",()=>this.action(document,"reread")),document,"read-again");again.setAttribute("aria-label",`Read the unread pages or images of ${document.name||"this file"} again`);card.append(again);
      }
      // A verdict that set the file aside, or asks for direction, is stated on the card itself, not only under its details.
      const relevance=this.relevanceNote(document),decided=analysis.disposition==="needs_reason"||(analysis.disposition==="parked"&&!analysis.parked_by_user);
      if(relevance&&decided)card.append(relevance);
      const failed=this.actionErrors.get(document.id);if(failed){const error=this.node("div","documents-warning");error.setAttribute("role","status");const retry=this.control(this.button("Retry action","documents-text-button",()=>this.action(document,failed.action,failed.purpose)),document,"retry-action",failed.action);retry.disabled=this.actions.has(document.id+":"+failed.action);error.append(this.node("p","",failed.message),retry);card.append(error);}
      if(document.error)card.append(this.node("p","documents-warning",typeof document.error==="string"?document.error:"Some content could not be read."));
      if(analysis.error)card.append(this.node("p","documents-warning",this.reviewNotice(typeof analysis.error==="string"?analysis.error:analysis.error.message)||"Review could not be completed. Try reviewing this file again."));
      if(analysis.phase==="error"&&!analysis.error)card.append(this.node("p","documents-warning","Review could not be completed. Your saved file is retained."));
      // Said in its own line, whatever error an earlier review left on the file.
      const outdated=this.reindexMessage(document);if(outdated)card.append(this.node("p",`${this.reindexChecking(document)?"documents-progress":"documents-warning"} documents-reindex-status`,outdated));
      if(document.indexed_by_newer_build)card.append(this.node("p","documents-progress documents-newer-index","Indexed by a newer version of Process Collector. This version uses that index as it is."));
      if(!this.reviewError(document)&&analysis.disposition!=="parked"){const awaiting=this.rereadStatus(document);if(awaiting)card.append(awaiting);}
      let content=card;
      if(this.assets){
        const expanded=this.expandedAssets.get(document.id)??analysis.disposition==="needs_reason";
        content=this.node("div","documents-detail-content");content.id=`document-details-${this.safeId(document.id)}`;content.hidden=!expanded;
        const toggle=this.button("Review details & sources","documents-detail-toggle",()=>{const open=content.hidden;content.hidden=!open;this.expandedAssets.set(document.id,open);toggle.setAttribute("aria-expanded",String(open));});
        toggle.dataset.documentToggle=document.id;toggle.setAttribute("aria-expanded",String(expanded));toggle.setAttribute("aria-controls",content.id);card.append(toggle,content);
      }
      if(analysis.summary){
        if(analysis.summary_basis==="initial_review"){
          const overview=this.node("section","documents-overview");overview.append(this.node("h4","","Initial overview"),this.node("p","documents-summary",analysis.summary));
          overview.append(this.node("p","documents-progress",analysis.summary_basis_note||"Written from the initial review selection. Current review status and limitations are shown separately."));content.append(overview);
        }else content.append(this.node("p","documents-summary",analysis.summary));
      }
      if(relevance&&!decided)content.append(relevance);
      if(document.coverage){
        const coverage=typeof document.coverage==="string"?document.coverage:document.coverage.summary||document.coverage.note;if(coverage)content.append(this.node("p","documents-progress",coverage));
      }
      const limitations=[document.coverage?.limitations,analysis.limitations].flatMap(value=>Array.isArray(value)?value:typeof value==="string"?[value]:[]).filter(value=>typeof value==="string"&&value.trim());
      if(limitations.length){const section=this.node("div","documents-limitations"),list=this.node("ul");section.append(this.node("h4","","Reading limits"));for(const limitation of new Set(limitations))list.append(this.node("li","",this.reviewNotice(limitation)));section.append(list);content.append(section);}
      if(document.inventory)this.renderInventory(content,document.inventory,document.kind);
      const primary=typeof analysis.question==="string"?analysis.question.trim():"";
      if(analysis.disposition==="needs_reason"&&!this.reviewError(document)){
        const form=this.node("form","documents-purpose"),input=this.node("input"),field=this.node("label","documents-purpose-field");
        input.type="text";input.autocomplete="off";input.dir="auto";input.required=true;input.maxLength=1000;input.placeholder="e.g. Check the approval thresholds";input.dataset.documentPurpose=document.id;input.value=drafts.get(document.id)||"";
        field.append(this.node("span","",primary||"What should I look for?"),input);
        const submit=this.control(this.node("button","documents-add","Review now"),document,"review-now");submit.type="submit";
        const updateSubmit=()=>{submit.disabled=!input.value.trim()||this.documentBusy(document.id);};
        input.addEventListener("input",updateSubmit);updateSubmit();
        form.append(field,submit,this.control(this.button("Save for later","documents-text-button",()=>this.action(document,"park")),document,"park"),this.useAnyway(document));
        form.addEventListener("submit",event=>{event.preventDefault();const purpose=input.value.trim();if(purpose)this.action(document,"purpose",purpose);});const costNote=card.querySelector(".documents-reread-status");card.insertBefore(form,costNote?costNote.nextSibling:stage.nextSibling||null);
      }
      if(this.reviewError(document)){
        // The button says what it does: for an index from an earlier version that is a re-index and a paid review.
        const retry=this.needsReindex(document)?"Re-index and review":"Retry review";
        const cost=this.reindexNote(document,retry);if(cost)card.append(cost);
        if(document.retryable!==false)card.append(this.control(this.button(retry,"documents-text-button",()=>this.action(document,"revisit")),document,"retry-review"));
        if(analysis.disposition!=="parked")card.append(this.control(this.button("Save for later","documents-text-button",()=>this.action(document,"park")),document,"park"));
      }
      else if(analysis.disposition==="parked"){
        const cost=this.reindexNote(document,"Revisit this file");if(cost)card.append(cost);
        card.append(this.control(this.button("Revisit this file","documents-text-button",()=>this.action(document,"revisit")),document,"revisit"));
        // Set aside by the reviewer's verdict, not by the participant: the participant may overrule it.
        if(!analysis.parked_by_user)card.append(this.useAnyway(document));
      }
      else if(analysis.disposition!=="needs_reason")content.append(this.control(this.button("Save for later","documents-text-button",()=>this.action(document,"park")),document,"park"));
      const listed=Array.isArray(analysis.questions)?analysis.questions.filter(item=>item&&typeof item.text==="string"&&item.text.trim()):[];
      const questions=(listed.length?listed:primary?[{id:"quick",text:primary,sources:analysis.sources||[]}]:[]).filter(item=>!(analysis.disposition==="needs_reason"&&item.text.trim()===primary));
      if(questions.length){const section=this.node("div","documents-questions");section.append(this.node("h4","",analysis.disposition==="parked"?"Questions for later":"Questions to explore"));
        for(const question of questions){if(!question?.text)continue;const identity=JSON.stringify([question.id||"",question.text]),row=this.node("div","documents-question");row.append(this.node("p","",question.text),this.control(this.button("Discuss","documents-text-button",()=>this.discuss(document,question)),document,"discuss",identity));this.renderSources(row,document,question.sources||[],identity);section.append(row);}content.append(section);
      }
      this.renderSources(content,document,analysis.sources||[]);
      if(this.assets&&!content.children.length){card.querySelector(".documents-detail-toggle").remove();content.remove();}
      if(this.documentBusy(document.id))card.querySelectorAll?.("button").forEach(button=>{if(!button.classList.contains("documents-source")&&!button.classList.contains("documents-detail-toggle"))button.disabled=true;});
      this.body.append(card);
    }
    useAnyway(document) {
      // Puts the file to use in the interview as the participant's own choice; the verdict stays on record beside it.
      const button=this.control(this.button("Use this file anyway","documents-text-button",()=>this.action(document,"use")),document,"use-anyway");
      button.setAttribute("aria-label",`Use ${document.name||"this file"} in the interview although the reviewer did not find it related`);return button;
    }
    reindexNote(document,actionLabel) {
      // Shown beside the button, before the click: this retry re-indexes the file or reads kept
      // transcriptions again, which costs provider credits and can replace searchable source text.
      const awaiting=this.awaitingReread(document);
      if(!document.extraction_needs_reindex&&!awaiting)return null;
      const stored=awaiting||(Array.isArray(document.inventory?.visual_transcribed_units)?document.inventory.visual_transcribed_units.length:0);
      const note=this.node("div","documents-limitations documents-reindex-note"),list=this.node("ul");
      note.append(this.node("h4","",`Before you choose ${actionLabel}`));
      const visual=["pdf","png"].includes(document.kind)?", including for every page or image that needs visual reading":"";
      list.append(this.node("li","",document.extraction_needs_reindex
        ?`${actionLabel} re-indexes this file and sends it to the AI provider for a new review. This is a paid re-read: it uses provider credits${visual}.`
        :`${actionLabel} sends this file to the AI provider for a new review. This is a paid re-read: it uses provider credits.`));
      if(stored){
        list.append(this.node("li","",`${stored} stored AI visual ${stored===1?"transcription is":"transcriptions are"} read again. A successful reading replaces the text used for future searches and citations. If a reading fails, the stored text stays available.`));
      }
      note.append(list);return note;
    }
    awaitingReread(document) {
      // The record maps each kept source that still awaits its new reading to the parser's sentence for it.
      const pending=document.visual_reread_pending;
      return pending&&typeof pending==="object"?Object.keys(pending).length:0;
    }
    rereadStatus(document) {
      // Without a retry button on screen, still say that kept transcriptions await a paid new reading,
      // so no later review of this file reads them again unannounced.
      const awaiting=this.awaitingReread(document);if(!awaiting)return null;
      const working=["pending","indexing"].includes(document.status)||["quick","deep"].includes(document.analysis?.phase);
      const subject=`${awaiting} stored AI visual ${awaiting===1?"transcription":"transcriptions"}`;
      const kept=`${awaiting===1?"It is":"Each one is"} kept as it is unless its new reading succeeds.`;
      return this.node("p","documents-progress documents-reread-status",working
        ?`${subject} ${awaiting===1?"is":"are"} being read again by the AI provider. This is a paid re-read. ${kept}`
        :`${subject} still ${awaiting===1?"awaits":"await"} a new reading, so this review is not complete. A new review of this file sends ${awaiting===1?"it":"them"} to the AI provider again. That is a paid re-read. ${kept}`);
    }
    renderRemoved() {
      if(!this.removed.length)return;
      const section=this.node("details","documents-limitations documents-removed"),list=this.node("ul");section.open=this.removedOpen;
      section.addEventListener("toggle",()=>{this.removedOpen=section.open;});
      section.append(this.node("summary","",`Removed files (${this.removed.length})`),
        this.node("p","","Removed files stay on this computer and are not used in the interview. Notes and steps that already cite one keep it as a saved excerpt. Restore puts a file back as it was; a review that had not finished continues."));
      for(const file of this.removed){
        // Restore only returns the file. Revisit, on a file's own card, is the action that reviews it again.
        const row=this.node("li"),restore=this.control(this.button("Restore","documents-text-button",()=>this.action(file,"restore")),file,"restore");
        restore.setAttribute("aria-label",`Restore ${file.name||"file"} to this conversation`);restore.disabled=this.documentBusy(file.id);
        const purge=this.control(this.button("Delete permanently","documents-text-button",()=>{
          if(window.confirm("Permanently delete "+(file.name||"this file")+" and its searchable text from this computer? Previously saved interviews or submissions can keep the excerpts they cited."))void this.action(file,"purge");
        }),file,"purge");
        purge.disabled=this.documentBusy(file.id);purge.setAttribute("aria-label","Permanently delete "+(file.name||"file"));
        row.append(this.node("span","",file.name||"File"),restore,purge);list.append(row);
      }
      section.append(list);this.body.append(section);
    }
    renderInventory(card,inventory,kind) {
      if(inventory&&typeof inventory==="object"&&!Array.isArray(inventory)){
        const parts=[],number=(value,word)=>{if(Number.isFinite(value))parts.push(value.toLocaleString()+" "+(value===1?word.replace(/^(pages|rows|sheets|formula cells|visual units)\b/,first=>first.slice(0,-1)):word));};
        if(kind==="pdf"){
          number(inventory.pages,"pages");number(inventory.text_pages,"pages with selectable text");
          if(Array.isArray(inventory.mixed_visual_pages))number(inventory.mixed_visual_pages.length,"pages containing both selectable text and visual content");
          if(Array.isArray(inventory.visual_transcribed_units))number(inventory.visual_transcribed_units.length,"visual units transcribed");
        }else if(["xls","xlsx","xlsm","csv"].includes(kind)){
          if(kind!=="csv"){
            number(inventory.sheet_count??inventory.sheets?.length,"sheets");
            const names=(Array.isArray(inventory.sheets)?inventory.sheets:[]).map(sheet=>typeof sheet==="string"?sheet:sheet.name).filter(Boolean);
            if(names.length)parts.push(names.slice(0,12).join(", ")+(names.length>12?" · "+(names.length-12)+" more listed":""));
          }
          number(inventory.rows,"rows");number(inventory.formula_cells,"formula cells");
        }else if(kind==="png"&&inventory.width&&inventory.height)parts.push(inventory.width+" × "+inventory.height+" pixels");
        if(parts.length){card.append(this.node("p","documents-progress",parts.join(" · ")));return;}
      }
      const parts=[];
      if(typeof inventory==="string")parts.push(inventory);
      else if(Array.isArray(inventory))inventory.slice(0,12).forEach(item=>parts.push(typeof item==="string"?item:item?.label||item?.name||""));
      else if(inventory&&typeof inventory==="object")for(const [key,value] of Object.entries(inventory)){if(typeof value==="number")parts.push(`${value} ${key.replaceAll("_"," ")}`);else if(typeof value==="string")parts.push(value);else if(Array.isArray(value)){
        parts.push(`${value.length} ${key.replaceAll("_"," ")}`);
        if(/sheet|tab/i.test(key)){const names=value.slice(0,12).map(item=>typeof item==="string"?item:item?.name||item?.label||"").filter(Boolean);if(names.length)parts.push(names.join(", ")+(value.length>12?` · ${value.length-12} more listed`:""));}
      }}
      if(parts.filter(Boolean).length)card.append(this.node("p","documents-progress",parts.filter(Boolean).join(" · ")));
    }
    renderSources(parent,document,sources,groupKey="file") {
      const valid=Array.isArray(sources)?sources.filter(source=>source&&typeof source.source_id==="string"):[];if(!valid.length)return;
      const group=this.node("div","documents-sources");
      for(const source of valid.slice(0,30)){
        const button=this.control(this.button(source.label||`${document.name} · Source`,"documents-source",()=>this.openSource(document,source,button.dataset.documentControl)),document,"source",JSON.stringify([groupKey,source.source_id]));
        button.setAttribute("aria-label",`Read source: ${document.name} · ${source.label||source.source_id}`);button.dataset.documentSource=`${document.id}:${source.source_id}`;group.append(button);
      }
      if(valid.length>30)group.append(this.node("span","documents-progress","Showing 30 of "+valid.length+" sources."));
      parent.append(group);
    }
    async openSource(document,source,originControl) {
      const generation=this.generation,scope=this.scope;if(this.disposed||this.suspended||!scope)return;
      if(this.assets)this.expandedAssets.set(document.id,true);
      const selected=this.source={documentId:document.id,sourceId:source.source_id,originControl,label:this.sourceTitle(document,source.label||source.source_id),text:"Loading source…",loading:true};this.render();if(this.assets)this.focusSource();
      try{
        const result=await this.options.requestJSON("/api/documents/source",{scope,id:document.id,source_id:source.source_id},{signal:this.controller.signal,timeout:30000});
        if(!this.current(generation)||this.source!==selected||!this.documents.some(item=>item.id===document.id))return;
        // Text a model read off an image is marked by the store (origin, verified); say so beside it.
        const transcribed=result.source?.origin==="ai_visual_transcription"||result.source?.verified===false;
        this.source={...selected,loading:false,transcribed,location:result.source?.location,label:this.sourceTitle(document,result.source?.label||source.label||source.source_id),text:label(result.source?.text)||"This source has no readable text."};this.render();if(!this.assets||this.doc.activeElement===this.sourceHeading)this.focusSource();
      }catch(error){if(this.current(generation)&&this.source===selected&&error.name!=="AbortError"){this.source={...selected,loading:false,text:message(error),error:true};this.render();if(!this.assets||this.doc.activeElement===this.sourceHeading)this.focusSource();}}
    }
    sourceTitle(document,reference) {const name=document.name||"File",text=label(reference);return text.includes(name)?text:`${name}${text?" · "+text:""}`;}
    focusSource() {
      if(this.assets&&!this.visible(this.assets))return;
      if(this.assets||this.dialog?.open){this.sourceHeading?.focus?.({preventScroll:true});this.sourceHeading?.scrollIntoView?.({block:"start"});}
    }
    renderSource() {
      const source=this.node("section","documents-source-preview"),heading=this.sourceHeading=this.node("h3","",this.source.label);heading.tabIndex=-1;heading.dataset.documentSourceHeading=`${this.source.documentId}:${this.source.sourceId}`;
      source.append(heading,this.button("Close source","documents-text-button",()=>this.closeSource()));
      if(this.source.transcribed)source.append(this.node("p","documents-source-origin",AI_TRANSCRIPTION_NOTE));
      const content=this.node("pre","documents-source-text",this.source.text);
      if(this.source.location?.sheet&&this.source.text&&!this.source.error){
        const wrap=this.node("div","documents-sheet-source"),table=this.node("table");
        wrap.tabIndex=0;wrap.setAttribute("aria-label","Cells from "+this.source.location.sheet+" "+(this.source.location.range||""));
        const head=this.node("tr");head.append(this.node("th","","Cell"),this.node("th","","Value"));table.append(head);
        // Parse exact cell boundaries recorded by the extractor. Cell values may contain
        // newlines, pipes or strings that look like an address.
        const chars=Array.from(this.source.text),lengths=this.source.location.cell_lengths;
        let offset=0,valid=Array.isArray(lengths)&&lengths.length>0&&lengths.length<=chars.length;
        for(const size of valid?lengths:[]){
          if(!Number.isSafeInteger(size)||size<2||offset+size>chars.length){valid=false;break;}
          const cell=chars.slice(offset,offset+size).join(""),address=cell.match(/^([A-Z]{1,3}[1-9]\d*)=/);
          if(!address){valid=false;break;}
          const row=this.node("tr"),ref=this.node("th","",address[1]);ref.setAttribute("scope","row");
          row.append(ref,this.node("td","",cell.slice(address[0].length)));table.append(row);offset+=size;
          if(offset<chars.length){
            if(chars[offset]==="\n")offset++;else if(chars.slice(offset,offset+3).join("")===" | ")offset+=3;else{valid=false;break;}
          }
        }
        if(valid&&offset===chars.length){wrap.append(table);source.append(wrap);const original=this.node("details");original.append(this.node("summary","","Original excerpt"),content);source.append(original);}
        else{
          // Older indexes lack exact lengths. Keep their saved excerpt visible; users may opt
          // into an address-based view whose boundaries cannot be guaranteed for literal pipes.
          source.append(content);
          const pieces=this.source.text.split(/(?: \| |\n)(?=[A-Z]{1,3}[1-9]\d*=)/);
          if(pieces.length&&pieces.every(piece=>/^[A-Z]{1,3}[1-9]\d*=/.test(piece))){
            const rows=this.node("table");rows.append(head);
            for(const piece of pieces){const split=piece.indexOf("="),row=this.node("tr"),ref=this.node("th","",piece.slice(0,split));
              ref.setAttribute("scope","row");row.append(ref,this.node("td","",piece.slice(split+1)));rows.append(row);}
            wrap.append(rows);const old=this.node("details");old.append(this.node("summary","","Group older excerpt by apparent cell address"),wrap);source.append(old);
          }
        }
      }else source.append(content);
      const fileDetails=this.assets&&this.body.querySelector?.(`[data-document-id="${this.safeId(this.source.documentId)}"]`)?.querySelector(".documents-detail-content");(fileDetails||this.body).append(source);
      if(this.source.error){const selected=this.source,document=this.documents.find(item=>item.id===selected.documentId);if(document)source.append(this.button("Retry source","documents-text-button",()=>this.openSource(document,{source_id:selected.sourceId,label:selected.label},selected.originControl)));}
    }
    closeSource() {
      const {documentId,sourceId,originControl}=this.source;
      this.source=null;this.render();
      const origin=[...this.body.querySelectorAll(".documents-source")].find(button=>originControl?
        button.dataset.documentControl===originControl:button.dataset.documentSource===`${documentId}:${sourceId}`);
      if(origin&&this.visible(origin)){origin.focus({preventScroll:true});origin.scrollIntoView?.({block:"nearest"});}
      else this.focusDocumentFallback(documentId,true);
    }
    size(bytes) {const value=Number(bytes)||0;return value>=1024*1024?`${(value/1024/1024).toFixed(1)} MiB`:value>=1024?`${Math.round(value/1024)} KiB`:`${value} bytes`;}
    startNewWorkspace() {
      if(!(this.scopeUnavailable||this.storeUnavailable)||!this.scope||this.mutating)return;
      const retained=[...this.unavailableWorkspaces,{scope:this.scope,documents:this.documents}];
      this.reset();
      this.unavailableWorkspaces=retained;this.render();this.open();this.attachButton.focus?.();
      // No file of the workspace that was left can be read here any more. The interview keeps the
      // excerpts it saved from them as references and stops citing them in what it sends (app.js).
      this.emit({type:"workspace_replaced"});
      this.emit({type:"changed",state:this.lifecycle()});this.options.onDirty?.();
    }
    // The scope and file records as they are, without the copy exportState() makes: for a caller that only
    // reads them on every control update (the draft's file signature in app.js). Never change what it returns.
    peekState() {return {scope:this.scopeUnavailable?null:this.scope,documents:this.scopeUnavailable?[]:this.documents};}
    exportState(includePrevious=false) {
      const saved={scope:this.scope,documents:copy(this.documents)};
      if(includePrevious&&this.unavailableWorkspaces.length)saved.unavailable_workspaces=copy(this.unavailableWorkspaces);
      return saved;
    }
    async restoreState(saved) {
      this.reset();if(!saved||typeof saved!=="object")return;
      if(Array.isArray(saved.unavailable_workspaces))this.unavailableWorkspaces=copy(saved.unavailable_workspaces);
      if(typeof saved.scope==="string"&&saved.scope){this.scope=saved.scope;this.watchScope();}
      if(Array.isArray(saved.documents))this.setDocuments(saved.documents,false);this.render();
      if(this.scope){await this.refresh(false);if(this.scopeUnavailable){this.options.notice?.("The saved files are unavailable on this computer. Open Assets and choose Start new file workspace to add files.",true);this.open();}}
    }
    cancel() {clearTimeout(this.pollTimer);this.pollTimer=null;this.controller.abort();}
    suspend() {
      if(this.disposed||this.suspended)return;
      this.clearDrop();
      this.suspended=true;this.generation++;this.revision++;this.cancel();
      this.uploadErrors.push(...this.uploads.map(upload=>({name:upload.name,file:upload.file,message:"Upload confirmation was interrupted. Check the saved files before retrying."})));
      this.uploadErrors=this.uploadErrors.slice(-MAX_FILES);this.uploads=[];this.polling=null;this.sessionPromise=null;this.mutating=0;this.actions.clear();
      if(this.source?.loading)this.source={...this.source,loading:false,error:true,text:"The source read was interrupted. Retry to load the saved source."};
    }
    resume() {
      if(this.disposed||!this.suspended)return;
      this.suspended=false;this.controller=new AbortController();this.render();this.changed();void this.refresh();
    }
    reset() {
      this.clearDrop();
      this.unavailableWorkspaces=[];this.scopeUnavailable=false;this.storeUnavailable=false;this.removed=[];this.removedOpen=false;this.limit=null;
      this.channel?.close();this.channel=null;this.remoteIntents.clear();this.cancel();this.uploadQueue=Promise.resolve();this.generation++;this.revision++;this.suspended=false;this.controller=new AbortController();this.scope=null;this.documents=[];this.uploads=[];this.uploadErrors=[];this.seen=new Map();this.sessionPromise=null;this.polling=null;this.mutating=0;this.actions.clear();this.actionErrors.clear();this.expandedAssets.clear();this.source=null;this.sourceHeading=null;this.connectionError="";this.lastError="";this.close(false);this.render();this.changed(false);
    }
    dispose() {if(this.disposed)return;this.reset();this.disposed=true;this.cancel();this.doc.removeEventListener?.("visibilitychange",this.visibilityChanged);window.removeEventListener?.("pagehide",this.pagehide);window.removeEventListener?.("pageshow",this.pageshow);for(const [target,name,fn] of this.dropListeners||[])target.removeEventListener?.(name,fn);this.dropListeners=[];this.dropOverlay?.remove();this.dropTarget?.classList.remove("document-drop-zone");this.assets?.replaceChildren();this.controls?.replaceChildren();if(this.strip){this.strip.replaceChildren();this.strip.hidden=true;}}
  }
  window.CollectorDocuments={create:options=>new Documents(options)};
})();
