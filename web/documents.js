"use strict";

// Document attachments are context to review, never automatically accepted process facts.
(() => {
  const MAX_FILE = 64 * 1024 * 1024, MAX_FILES = 20;
  const EXTENSIONS = new Set(["pdf","png","xlsx","xlsm","csv"]);
  const FILE_NOTICE = "Files are saved on this computer. Relevant content is sent to OpenAI. Confirm file details in the interview.";
  const copy = value => JSON.parse(JSON.stringify(value));
  const abortError = () => new DOMException("Cancelled", "AbortError");
  const message = error => String(error?.message || "The file request could not be completed.").slice(0,600);
  const label = value => typeof value === "string" ? value : "";

  class Documents {
    constructor(options) {
      if (typeof options?.requestJSON !== "function") throw new TypeError("A same-origin JSON request function is required.");
      this.options=options;this.doc=options.document||window.document;this.generation=0;this.revision=0;this.scope=null;this.documents=[];
      this.uploads=[];this.uploadErrors=[];this.seen=new Map();this.pollTimer=null;this.polling=null;this.sessionPromise=null;
      this.mutating=0;this.sequence=0;this.batchSequence=0;this.lifecycleStamp="";this.disposed=false;this.restoreFocus=true;this.connectionError="";this.lastError="";this.source=null;
      this.controller=new AbortController();this.actions=new Set();this.actionErrors=new Map();this.expandedAssets=new Map();this.build();this.render();
      this.suspended=false;this.pagehide=()=>this.suspend();this.pageshow=event=>{if(event.persisted)this.resume();};
      window.addEventListener?.("pagehide",this.pagehide);window.addEventListener?.("pageshow",this.pageshow);
      this.buildDropZone();
    }
    node(tag,className,text) {const node=this.doc.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=String(text);return node;}
    button(text,className,fn) {const button=this.node("button",className,text);button.type="button";button.addEventListener("click",fn);return button;}
    control(button,document,action,identity="") {button.classList.add("document-control");button.dataset.documentControl=JSON.stringify([document.id,action,identity]);return button;}
    visible(node) {for(let current=node;current;current=current.parentElement)if(current.hidden||(current.tagName==="DIALOG"&&!current.open))return false;return true;}
    focusDocumentFallback(id) {
      const card=this.body.querySelector?.(`[data-document-id="${this.safeId(id)}"]`)||this.body.querySelector?.(".documents-card");
      const target=card||(this.assets?this.attachButton:this.dialog?.querySelector?.(".documents-close"))||this.attachButton;
      if(target&&!target.disabled&&this.visible(target)){if(card)card.tabIndex=-1;target.focus?.({preventScroll:true});}
    }
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
      if(this.options.canDiscuss?.()===false){this.options.notice?.("Wait for the current reply to finish, then choose Discuss again. The file question is retained.");return;}
      this.close(false);this.options.onDiscuss?.();this.emit({type:"question",document:copy(document),question:copy(question)});
    }
    context() {const value=this.options.getContext?.()||{};return {context:value.context||{},turns:value.turns||[],focus:value.focus||"",current_question:value.current_question||""};}
    current(generation) {return !this.disposed&&generation===this.generation;}
    allowed() {return !this.disposed&&!this.suspended&&(this.options.canUpload?.()!==false);}
    fileDrag(event) {return Array.from(event.dataTransfer?.types||[]).includes("Files");}
    dropInside(event) {return Boolean(this.dropTarget&&!this.dropTarget.hidden&&(this.dropTarget.contains(event.target)||this.assets?.contains(event.target)));}
    clearDrop() {this.dragDepth=0;if(this.dropOverlay)this.dropOverlay.hidden=true;}
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
        const full=this.documents.length+this.uploads.length>=MAX_FILES,allowed=this.allowed();
        this.dropTitle.textContent=!allowed?"Files can't be attached right now":full?"This conversation has 20 files":"Drop files into this conversation";
        this.dropHelp.textContent=!allowed?"Finish loading the interview, then try again.":full?"The conversation file limit has been reached.":"PDF, PNG, XLSX, XLSM or CSV · Up to 64 MiB each";
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
        event.dataTransfer.dropEffect=inside&&this.allowed()&&this.documents.length+this.uploads.length<MAX_FILES?"copy":"none";
      });
      listen(window,"drop",event=>{
        if(!this.fileDrag(event))return;
        event.preventDefault();const inside=this.dropInside(event);this.clearDrop();
        if(!inside)return;
        if(!this.allowed()){this.options.notice?.("Files can't be attached right now. Finish loading the interview, then try again.",true);return;}
        const items=Array.from(event.dataTransfer.items||[]);
        const directories=items.some(item=>{try{return item.webkitGetAsEntry?.()?.isDirectory===true;}catch{return false;}});
        if(directories){this.options.notice?.("Drop individual files rather than folders.",true);return;}
        const files=Array.from(event.dataTransfer.files||[]);
        if(!files.length){this.options.notice?.("The dropped files could not be read. Try Add files instead.",true);return;}
        void this.addFiles(files);
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
      footer.append(add,this.node("p","",FILE_NOTICE));
      this.dialog.replaceChildren(header,this.liveStatus,this.body,footer);
    }
    buildAssets() {
      this.assets.classList.add("document-assets");
      const header=this.node("div","documents-assets-heading");
      this.attachButton=this.button("Add files","documents-add",()=>this.attach());
      this.input=this.node("input");this.input.type="file";this.input.accept=".pdf,.png,.xlsx,.xlsm,.csv";this.input.multiple=true;this.input.hidden=true;
      this.input.addEventListener("change",()=>{const files=Array.from(this.input.files||[]);this.input.value="";this.addFiles(files);});
      const formats=this.node("p","documents-assets-formats","PDF, PNG, XLSX, XLSM or CSV · Up to 64 MiB each");
      header.append(this.attachButton,this.input,formats);
      this.liveStatus=this.node("p","documents-live-status");this.liveStatus.setAttribute("role","status");this.liveStatus.setAttribute("aria-live","polite");this.liveStatus.setAttribute("aria-atomic","true");
      this.body=this.node("div","documents-body");this.body.setAttribute("aria-live","off");this.body.setAttribute("aria-label","Uploaded files");
      const footer=this.node("p","documents-assets-privacy",FILE_NOTICE);
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
        this.scope=result.scope;this.setDocuments(result.documents||[],false);this.options.onDirty?.();return this.scope;
      })();
      this.sessionPromise=task;
      try{return await task;}finally{if(this.sessionPromise===task)this.sessionPromise=null;}
    }
    async addFiles(files) {
      if(!this.allowed()||!files.length)return;
      const generation=this.generation;
      const available=Math.max(0,MAX_FILES-this.documents.length-this.uploads.length),accepted=[];
      for(const file of files){
        const extension=String(file.name||"").split(".").pop().toLowerCase();
        const error=!EXTENSIONS.has(extension)?"Choose a PDF, PNG, XLSX, XLSM or CSV file.":!Number.isFinite(file.size)||file.size<1?"This file is empty.":file.size>MAX_FILE?"This file exceeds the 64 MiB limit.":accepted.length>=available?"A conversation can hold up to 20 files.":null;
        if(error){this.uploadErrors.push({name:file.name||"File",message:error});continue;}accepted.push(file);
      }
      this.uploadErrors=this.uploadErrors.slice(-20);
      if(!accepted.length){this.render();this.open();this.changed();return;}
      const batchId=`upload_${++this.batchSequence}`;
      const queued=accepted.map(file=>({key:++this.sequence,name:file.name,status:"Waiting to upload",file}));
      this.uploads.push(...queued);this.mutating++;this.revision++;
      this.emit({type:"upload_started",batchId,names:accepted.map(file=>file.name)});
      this.options.onDirty?.();this.render();this.changed();
      if(this.assets)this.open();
      try{
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
            this.upsert(result.document);this.emit({type:"received",document:copy(result.document)});this.options.onDirty?.();
          }catch(error){
            if(!this.current(generation)||this.controller.signal.aborted)return;
            if(error.name==="AbortError")error=new Error("Uploading took too long. Check Files before trying again.");
            this.uploadErrors.push({name:upload.name,message:message(error),file:upload.file});this.reportError(error,true);
          }finally{
            if(this.current(generation)){this.uploads=this.uploads.filter(item=>item.key!==upload.key);this.render();this.changed();}
          }
        }
      }catch(error){if(this.current(generation)&&!this.controller.signal.aborted){
        if(error.name==="AbortError")error=new Error("Opening the file workspace took too long. Please try again.");
        this.uploadErrors.push(...queued.map(upload=>({name:upload.name,message:message(error),file:upload.file})));this.uploads=this.uploads.filter(item=>!queued.includes(item));this.reportError(error,true);this.render();
      }}finally{if(this.current(generation)){this.mutating=Math.max(0,this.mutating-1);this.revision++;this.changed();this.emit({type:"upload_settled",batchId});this.schedule(0);}}
    }
    async uploadFile(file,scope) {
      const controller=new AbortController(),outer=this.controller.signal,abort=()=>controller.abort();
      outer.addEventListener("abort",abort,{once:true});if(outer.aborted)abort();
      const timer=setTimeout(abort,120000);
      try{return await (this.options.fetch||window.fetch.bind(window))("/api/documents/upload",{
        method:"POST",credentials:"same-origin",signal:controller.signal,body:file,
        headers:{"Content-Type":"application/octet-stream","X-CSRF-Token":this.options.config?.()?.csrf_token||"",
          "X-Document-Scope":scope,"X-Document-Filename":encodeURIComponent(file.name)}
      });}finally{clearTimeout(timer);outer.removeEventListener("abort",abort);}
    }
    upsert(document) {const index=this.documents.findIndex(item=>item.id===document.id);if(index<0)this.documents.push(copy(document));else this.documents[index]=copy(document);this.connectionError="";this.render();this.changed();}
    setDocuments(documents,emit=true) {
      if(!Array.isArray(documents))throw new Error("The local file list was incomplete.");
      const next=documents.filter(item=>item&&typeof item.id==="string").map(copy);
      const changed=JSON.stringify(next)!==JSON.stringify(this.documents);this.documents=next;this.connectionError="";this.lastError="";
      for(const document of next){
        const version=document.analysis?.version;
        const available=!document.archived&&["ready","partial"].includes(document.status)&&Number(document.chunk_count)>0;
        if((version!==undefined&&version!==null)||available){
        // Native extraction can finish before the first model review. Publish
        // that availability once so the interview can use its exact text now.
        const key=`${version??"indexed"}:${available?document.chunk_count:0}:${document.analysis?.intent_version||0}`;
        if(this.seen.get(document.id)!==key){this.seen.set(document.id,key);if(emit)this.emit({type:"analysis",document:copy(document),analysis:copy(document.analysis||{})});}
      }}
      this.render();this.changed(emit);if(changed&&emit)this.options.onDirty?.();
    }
    pending() {return this.uploads.length||this.documents.some(item=>["pending","indexing"].includes(item.status)||["quick","deep"].includes(item.analysis?.phase));}
    schedule(delay) {
      clearTimeout(this.pollTimer);this.pollTimer=null;
      if(this.disposed||this.suspended||!this.scope||(!this.documents.length&&!this.uploads.length))return;
      this.pollTimer=setTimeout(()=>{this.pollTimer=null;this.refresh();},delay===undefined?(this.pending()?2000:10000):delay);
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
          this.setDocuments(result.documents,emit);
        }catch(error){if(this.current(generation)&&scope===this.scope&&revision===this.revision&&error.name!=="AbortError"){this.connectionError=message(error);this.reportError(error,false,emit);this.render();this.changed(emit);}}
        finally{if(this.current(generation))this.schedule();}
      })();this.polling=task;
      try{return await task;}finally{if(this.polling===task)this.polling=null;}
    }
    reportError(error,notify,emit=true) {
      const text=message(error);if(notify)this.options.notice?.(text,true);
      if(this.lastError!==text){this.lastError=text;if(emit)this.emit({type:"error",message:text});}
    }
    async action(document,action,purpose) {
      const key=document.id+":"+action;if(this.disposed||this.suspended||this.documentBusy(document.id)||!this.scope)return;
      const generation=this.generation;this.actions.add(key);this.mutating++;this.revision++;
      this.render();this.changed();
      try{
        const result=await this.options.requestJSON("/api/documents/action",{scope:this.scope,id:document.id,action,...(purpose!==undefined?{purpose}:{})},{signal:this.controller.signal,timeout:30000});
        if(!this.current(generation))return;
        this.actionErrors.delete(document.id);
        if(action==="remove"){this.documents=this.documents.filter(item=>item.id!==document.id);this.seen.delete(document.id);if(this.source?.documentId===document.id)this.source=null;}
        else if(result.document)this.upsert(result.document);
        this.options.onDirty?.();this.render();
      }catch(error){if(this.current(generation)&&error.name!=="AbortError"){this.actionErrors.set(document.id,{action,purpose,message:message(error)});this.reportError(error,true);}}
      finally{if(this.current(generation)){this.actions.delete(key);this.mutating=Math.max(0,this.mutating-1);this.revision++;this.render();this.changed();this.schedule(0);}}
    }
    documentBusy(id) {return [...this.actions].some(key=>key.startsWith(id+":"));}
    reviewError(document) {return document.status==="error"||document.analysis?.phase==="error"||Boolean(document.analysis?.error);}
    status(document) {
      if(document.status==="error")return "Could not read file";
      if(document.analysis?.phase==="error"||document.analysis?.error)return "Review paused";
      if(this.actionErrors.has(document.id))return "Action needs attention";
      if(document.analysis?.disposition==="parked")return "Saved for later";
      if(document.analysis?.disposition==="needs_reason")return "Needs your direction";
      if(["pending","indexing"].includes(document.status))return "Reading file";
      if(document.analysis?.phase==="deep")return "Reading in depth";
      if(document.analysis?.phase==="quick"||!document.analysis?.summary)return "Checking relevance";
      if(document.status==="partial")return "Partly readable";
      return "Ready to review";
    }
    stageDetail(document) {
      const analysis=document.analysis||{},parts=[];
      const indexed=Number(document.coverage?.indexed_units),total=Number(document.coverage?.total_units);
      if(Number.isFinite(indexed)&&Number.isFinite(total)&&total>0)parts.push(`${indexed}/${total} units indexed.`);
      const reviewed=Number(analysis.reviewed_chunks),chunks=Number(analysis.total_chunks);
      if(Number.isFinite(reviewed)&&Number.isFinite(chunks)&&chunks>0)parts.push(`${reviewed} of ${chunks} sections reviewed.`);
      return parts.join(" ");
    }
    render() {
      if(this.disposed)return;
      const total=this.documents.length+this.uploads.length;
      const counts=new Map();this.documents.forEach(document=>{const status=this.status(document);counts.set(status,(counts.get(status)||0)+1);});
      const announcement=[`${total} ${total===1?"file":"files"}`,...[...counts].map(([status,count])=>`${count} ${status.toLowerCase()}`),...(this.uploads.length?[`${this.uploads.length} uploading`]:[]),...(this.uploadErrors.length?[`${this.uploadErrors.length} file issues`]:[])].join(". ");
      if(this.liveStatus.textContent!==announcement)this.liveStatus.textContent=announcement;
      this.attachButton.disabled=!this.allowed()||total>=MAX_FILES;
      this.options.onCountChange?.({total,issues:this.uploadErrors.length+this.documents.filter(document=>this.reviewError(document)||this.actionErrors.has(document.id)).length});
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
      if(this.connectionError){const error=this.node("div","documents-warning");error.append(this.node("p","",`Saved file details are retained. ${this.connectionError}`),this.button("Try again","documents-text-button",()=>this.refresh()));this.body.append(error);}
      this.uploadErrors.forEach((error,index)=>{const item=this.node("div","documents-warning");item.append(this.node("strong","",error.name),this.node("p","",error.message));if(error.file){const retry=this.button("Retry upload","documents-text-button",()=>{if(!this.allowed())return;this.uploadErrors.splice(index,1);this.addFiles([error.file]);});retry.disabled=!this.allowed();item.append(retry);}item.append(this.button("Dismiss issue","documents-text-button",()=>{this.uploadErrors.splice(index,1);this.render();this.changed();}));this.body.append(item);});
      if(!total&&!this.uploadErrors.length)this.body.append(this.node("p","documents-empty","Drop reference files anywhere in the interview."));
      for(const upload of this.uploads)this.body.append(this.node("p","documents-upload",`${upload.name} · ${upload.status}…`));
      for(const document of this.documents)this.renderDocument(document,drafts);
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
      const remove=this.control(this.button("Remove","documents-text-button",()=>this.action(document,"remove")),document,"remove");remove.setAttribute("aria-label",`Remove ${document.name||"file"} from this conversation`);head.append(title,remove);card.append(head);
      card.setAttribute("aria-busy",String(this.documentBusy(document.id)));
      const analysis=document.analysis||{};
      const stage=this.node("div","documents-stage");stage.dataset.state=this.reviewError(document)||this.actionErrors.has(document.id)?"error":analysis.disposition==="parked"?"later":["pending","indexing"].includes(document.status)||["quick","deep"].includes(analysis.phase)?"working":"ready";
      stage.append(this.node("strong","documents-stage-label",this.status(document)));const detail=this.stageDetail(document);if(detail)stage.append(this.node("span","documents-stage-detail",detail));card.append(stage);
      const failed=this.actionErrors.get(document.id);if(failed){const error=this.node("div","documents-warning");error.setAttribute("role","status");const retry=this.control(this.button("Retry action","documents-text-button",()=>this.action(document,failed.action,failed.purpose)),document,"retry-action",failed.action);retry.disabled=this.actions.has(document.id+":"+failed.action);error.append(this.node("p","",failed.message),retry);card.append(error);}
      if(document.error)card.append(this.node("p","documents-warning",typeof document.error==="string"?document.error:"Some content could not be read."));
      if(analysis.error)card.append(this.node("p","documents-warning",typeof analysis.error==="string"?analysis.error:analysis.error.message||"Review could not be completed. Try reviewing this file again."));
      if(analysis.phase==="error"&&!analysis.error)card.append(this.node("p","documents-warning","Review could not be completed. Your saved file is retained."));
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
      if(document.coverage){
        const coverage=typeof document.coverage==="string"?document.coverage:document.coverage.summary||document.coverage.note;if(coverage)content.append(this.node("p","documents-progress",coverage));
      }
      const limitations=[document.coverage?.limitations,analysis.limitations].flatMap(value=>Array.isArray(value)?value:typeof value==="string"?[value]:[]).filter(value=>typeof value==="string"&&value.trim());
      if(limitations.length){const section=this.node("div","documents-limitations"),list=this.node("ul");section.append(this.node("h4","","Reading limits"));for(const limitation of new Set(limitations))list.append(this.node("li","",limitation));section.append(list);content.append(section);}
      if(document.inventory)this.renderInventory(content,document.inventory);
      const primary=typeof analysis.question==="string"?analysis.question.trim():"";
      if(analysis.disposition==="needs_reason"){
        const form=this.node("form","documents-purpose"),input=this.node("input"),field=this.node("label","documents-purpose-field");
        input.type="text";input.required=true;input.maxLength=1000;input.placeholder="e.g. Check the approval thresholds";input.dataset.documentPurpose=document.id;input.value=drafts.get(document.id)||"";
        field.append(this.node("span","",primary||"What should I look for?"),input);
        const submit=this.control(this.node("button","documents-add","Review now"),document,"review-now");submit.type="submit";
        const updateSubmit=()=>{submit.disabled=!input.value.trim()||this.documentBusy(document.id);};
        input.addEventListener("input",updateSubmit);updateSubmit();
        form.append(field,submit,this.control(this.button("Save for later","documents-text-button",()=>this.action(document,"park")),document,"park"));
        form.addEventListener("submit",event=>{event.preventDefault();const purpose=input.value.trim();if(purpose)this.action(document,"purpose",purpose);});content.append(form);
      }
      if(this.reviewError(document))card.append(this.control(this.button("Retry review","documents-text-button",()=>this.action(document,"revisit")),document,"retry-review"));
      else if(analysis.disposition==="parked")card.append(this.control(this.button("Revisit this file","documents-text-button",()=>this.action(document,"revisit")),document,"revisit"));
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
    renderInventory(card,inventory) {
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
      for(const source of valid.slice(0,30)){const button=this.control(this.button(source.label||`${document.name} · Source`,"documents-source",()=>this.openSource(document,source)),document,"source",JSON.stringify([groupKey,source.source_id]));button.setAttribute("aria-label",`Read source: ${document.name} · ${source.label||source.source_id}`);button.dataset.documentSource=`${document.id}:${source.source_id}`;group.append(button);}parent.append(group);
    }
    async openSource(document,source) {
      const generation=this.generation,scope=this.scope;if(this.disposed||this.suspended||!scope)return;
      if(this.assets)this.expandedAssets.set(document.id,true);
      this.sourceReturnKey=`${document.id}:${source.source_id}`;
      const selected=this.source={documentId:document.id,sourceId:source.source_id,label:this.sourceTitle(document,source.label||source.source_id),text:"Loading source…",loading:true};this.render();if(this.assets)this.focusSource();
      try{
        const result=await this.options.requestJSON("/api/documents/source",{scope,id:document.id,source_id:source.source_id},{signal:this.controller.signal,timeout:30000});
        if(!this.current(generation)||this.source!==selected||!this.documents.some(item=>item.id===document.id))return;
        this.source={documentId:document.id,sourceId:source.source_id,label:this.sourceTitle(document,result.source?.label||source.label||source.source_id),text:label(result.source?.text)||"This source has no readable text."};this.render();if(!this.assets||this.doc.activeElement===this.sourceHeading)this.focusSource();
      }catch(error){if(this.current(generation)&&this.source===selected&&error.name!=="AbortError"){this.source={documentId:document.id,sourceId:source.source_id,label:this.sourceTitle(document,source.label||source.source_id),text:message(error),error:true};this.render();if(!this.assets||this.doc.activeElement===this.sourceHeading)this.focusSource();}}
    }
    sourceTitle(document,reference) {const name=document.name||"File",text=label(reference);return text.includes(name)?text:`${name}${text?" · "+text:""}`;}
    focusSource() {
      if(this.assets&&!this.visible(this.assets))return;
      if(this.assets||this.dialog?.open){this.sourceHeading?.focus?.({preventScroll:true});this.sourceHeading?.scrollIntoView?.({block:"nearest"});}
    }
    renderSource() {
      const source=this.node("section","documents-source-preview"),heading=this.sourceHeading=this.node("h3","",this.source.label);heading.tabIndex=-1;heading.dataset.documentSourceHeading=`${this.source.documentId}:${this.source.sourceId}`;
      source.append(heading,this.button("Close source","documents-text-button",()=>{const key=this.sourceReturnKey;this.source=null;this.sourceHeading=null;this.render();[...this.body.querySelectorAll(".documents-source")].find(button=>button.dataset.documentSource===key)?.focus?.({preventScroll:true});}));
      const content=this.node("pre","documents-source-text",this.source.text);source.append(content);
      const fileDetails=this.assets&&this.body.querySelector?.(`[data-document-id="${this.safeId(this.source.documentId)}"]`)?.querySelector(".documents-detail-content");(fileDetails||this.body).append(source);
      if(this.source.error){const selected=this.source,document=this.documents.find(item=>item.id===selected.documentId);if(document)source.append(this.button("Retry source","documents-text-button",()=>this.openSource(document,{source_id:selected.sourceId,label:selected.label})));}
    }
    size(bytes) {const value=Number(bytes)||0;return value>=1024*1024?`${(value/1024/1024).toFixed(1)} MiB`:value>=1024?`${Math.round(value/1024)} KiB`:`${value} bytes`;}
    exportState() {return {scope:this.scope,documents:copy(this.documents)};}
    async restoreState(saved) {
      this.reset();if(!saved||typeof saved!=="object")return;
      if(typeof saved.scope==="string"&&saved.scope)this.scope=saved.scope;
      if(Array.isArray(saved.documents))this.setDocuments(saved.documents,false);this.render();
      if(this.scope)await this.refresh(false);
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
      this.cancel();this.generation++;this.revision++;this.suspended=false;this.controller=new AbortController();this.scope=null;this.documents=[];this.uploads=[];this.uploadErrors=[];this.seen=new Map();this.sessionPromise=null;this.polling=null;this.mutating=0;this.actions.clear();this.actionErrors.clear();this.expandedAssets.clear();this.source=null;this.sourceHeading=null;this.sourceReturnKey=null;this.connectionError="";this.lastError="";this.close(false);this.render();this.changed(false);
    }
    dispose() {if(this.disposed)return;this.reset();this.disposed=true;this.cancel();window.removeEventListener?.("pagehide",this.pagehide);window.removeEventListener?.("pageshow",this.pageshow);for(const [target,name,fn] of this.dropListeners||[])target.removeEventListener?.(name,fn);this.dropListeners=[];this.dropOverlay?.remove();this.dropTarget?.classList.remove("document-drop-zone");this.assets?.replaceChildren();this.controls?.replaceChildren();if(this.strip){this.strip.replaceChildren();this.strip.hidden=true;}}
  }
  window.CollectorDocuments={create:options=>new Documents(options)};
})();
