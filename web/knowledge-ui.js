/* Participant submission, revision and receipt controls. */
(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const node=(tag,cls,value)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=String(value);return n;};
  const value=x=>typeof x==="string"?x:typeof x==="number"?String(x):"";
  const array=x=>Array.isArray(x)?x:[];
  const tidy=x=>value(x).replaceAll("_"," ");
  function create(options){
    const submit=$("knowledge-submit"),menu=$("submit-process-menu"),review=$("submit-process-review");
    let processId=null,lastReceipt=null;
    let sessionEpoch=0,pendingAttempt=null,activeAttempt=null,submissionView=null,lastFiled=null,lastAttribution=null,submitLimit=1000000;
    const button=(label,fn,cls="button secondary small")=>{const b=node("button",cls,label);b.type="button";b.addEventListener("click",fn);return b;};
    const text=(tag,cls,label,parent)=>{const n=node(tag,cls,label);parent.append(n);return n;};
    const field=(parent,label,name,placeholder)=>{const wrap=node("label","knowledge-field"),input=node("input");wrap.append(node("span","",label),input);input.name=name;input.autocomplete="off";input.dir="auto";input.maxLength=500;input.placeholder=placeholder;parent.append(wrap);return input;};
    const error=(container,message)=>{container.textContent=message||"";container.hidden=!message;};
    const close=dialog=>{if(dialog.open)dialog.close();};
    const uuid=x=>typeof x==="string"&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(x);
    function validReceipt(receipt,id){return receipt&&uuid(id)&&receipt.process_id===id&&uuid(receipt.submission_id)&&uuid(receipt.job_id)&&Number.isSafeInteger(receipt.revision)&&receipt.revision>0&&typeof receipt.status_token==="string"&&/^[0-9a-f]{64}$/i.test(receipt.status_token)&&["pending","processing","completed","failed","superseded"].includes(receipt.status);}
    function exportReceipt(){return validReceipt(lastReceipt,processId)?{submission_id:lastReceipt.submission_id,process_id:processId,revision:lastReceipt.revision,job_id:lastReceipt.job_id,status:lastReceipt.status,status_token:lastReceipt.status_token}:null;}
    // Participant, team, department and scope as the last submission of this process filed them, where
    // known (a key is absent when this tab never saw the value). Saved with the interview, so that a
    // revision starts from them instead of filing them blank.
    const ATTRIBUTION=["participant","team","department","scope"];
    function knownAttribution(saved){
      const known={};if(saved&&typeof saved==="object"&&!Array.isArray(saved))for(const key of ATTRIBUTION)if(typeof saved[key]==="string"&&saved[key].length<=500)known[key]=saved[key];
      return Object.keys(known).length?known:null;
    }
    function exportAttribution(){return processId?knownAttribution(lastAttribution):null;}
    function reset(){
      sessionEpoch++;processId=null;lastReceipt=null;lastAttribution=null;lastFiled=null;
      pendingAttempt=null;activeAttempt=null;submissionView=null;receiptChecked=false;close(submit);
    }
    function exportAttempt(){
      if(!pendingAttempt)return null;
      return {version:1,payload:JSON.parse(JSON.stringify(pendingAttempt.payload)),
        ...(pendingAttempt.leftOut?{left_out:true}:{}),...(pendingAttempt.omitted?{omitted:pendingAttempt.omitted}:{})};
    }
    function restoreAttempt(record,interviewId){
      if(!record)return null;
      const payload=record.payload;
      const forbidden=["csrf_token","authorization","api_key","status_token","knowledge_status","knowledge_process_id","knowledge_attribution","knowledge_pending_attempt","document_evidence","unsent_answer","voice_choice","submitter","principal","authenticated_submitter","__proto__","constructor","prototype"];
      if(record.version!==1||!payload||typeof payload!=="object"||Array.isArray(payload)||!uuid(payload.submission_key)||
          !uuid(interviewId)||payload.interview_id!==interviewId||!Array.isArray(payload.turns)||
          !payload.context||typeof payload.context!=="object"||Array.isArray(payload.context)||payload.synthetic_example===true||
          forbidden.some(key=>Object.hasOwn(payload,key))||(payload.process_id!=null&&!uuid(payload.process_id)))return null;
      const files=payload.documents;
      if(files!=null&&(typeof files!=="object"||Object.keys(files).some(key=>!["scope","documents"].includes(key))||
          !Array.isArray(files.documents)||files.documents.length>20||
          (files.scope==null?files.documents.length!==0:typeof files.scope!=="string"||files.scope.length>500)||
          files.documents.some(file=>!file||typeof file.id!=="string"||Object.keys(file).some(key=>key!=="id"))))return null;
      let frozen;
      try{const json=JSON.stringify(payload);if(byteLength(json)>submitLimit)return null;frozen=JSON.parse(json);}
      catch{return null;}
      const attribution=knownAttribution(payload)||{};
      return {payload:frozen,epoch:sessionEpoch,uncertain:true,attribution,
        drafts:draftArrivals(),leftOut:record.left_out===true,
        omitted:Number.isSafeInteger(record.omitted)&&record.omitted>0?Math.min(1000,record.omitted):0};
    }
    function restore(id,receipt,attribution,attempt,interviewId){reset();pendingAttempt=restoreAttempt(attempt,interviewId);processId=uuid(id)?id:null;lastAttribution=processId?knownAttribution(attribution):null;lastReceipt=validReceipt(receipt,processId)?{submission_id:receipt.submission_id,process_id:receipt.process_id,revision:receipt.revision,job_id:receipt.job_id,status:receipt.status,status_token:receipt.status_token}:null;}
    const isExample=()=>options.session()?.synthetic_example===true;
    let revisionsAvailable=false,receiptChecked=false;
    function configure(config){
      revisionsAvailable=config?.revisions_available===true;
      submitLimit=Number.isSafeInteger(config?.knowledge_submit_max_bytes)&&config.knowledge_submit_max_bytes>0?config.knowledge_submit_max_bytes:1000000;
    }
    // The size of a submission as the server counts it (bytes of the JSON body), and which part makes one
    // too large. submitLimit mirrors MAX_KNOWLEDGE_SUBMIT in server.py until /api/config supplies it.
    const byteLength=string=>{if(typeof TextEncoder==="function")return new TextEncoder().encode(string).length;let size=0;for(const character of string){const code=character.codePointAt(0);size+=code<0x80?1:code<0x800?2:code<0x10000?3:4;}return size;};
    function tooLargeMessage(payload,size){
      const kilobytes=bytes=>`${Math.ceil(bytes/1000).toLocaleString("en-US")} kB`;
      const parts=[["the transcript",payload.turns],["the draft",payload.draft],["the working map",payload.workflow],["the notes",[payload.memo_findings,payload.summary,payload.coverage,payload.capture_repairs]]]
        .map(([label,part])=>[label,part==null?0:byteLength(JSON.stringify(part))]).sort((a,b)=>b[1]-a[1]);
      return `This interview is too large to submit: it is ${kilobytes(size)} and company knowledge accepts ${kilobytes(submitLimit)}. The largest part is ${parts[0][0]} (${kilobytes(parts[0][1])}). Nothing was sent.`;
    }
    const knowledgeMessage=error=>/interviewer|your answer is safe|failed to fetch|networkerror|load failed/i.test(String(error?.message||""))?"Could not reach the local company knowledge service. Keep this interview open and try again.":String(error?.message||"Company knowledge is unavailable.");
    // onStatus(result) receives each verified status answer; with it the status is also read once when the
    // panel is shown, quietly, so a copy older than the newest revision of its process can say so before Submit.
    function showReceipt(parent,receipt,onStatus){
      const wrap=node("section","knowledge-block");text("h3","","Submission status",wrap);const status=text("p","knowledge-muted",`Revision ${receipt.revision} · ${tidy(receipt.status)||"pending"}`+(receiptChecked?"":" · saved receipt, not checked on this computer"),wrap);status.setAttribute("role","status");
      if(typeof receipt.status_token==="string"&&receipt.status_token){let reading=false,remaining=6;const read=async quiet=>{if(reading)return;reading=true;refresh.setAttribute("aria-disabled","true");try{const result=await options.request("/api/knowledge/status",{submission_id:receipt.submission_id,revision:receipt.revision,status_token:receipt.status_token});
        // Receipts from earlier versions may refer to a deleted process.
        if(result?.status==="deleted"&&result.submission_id===receipt.submission_id&&result.revision===receipt.revision){status.textContent=`Revision ${receipt.revision} · deleted. This process was removed from company knowledge. To file it again, submit it as a new process.`;return;}
        if(result?.submission_id!==receipt.submission_id||result?.revision!==receipt.revision||result?.job_id!==receipt.job_id||!["pending","processing","completed","failed","superseded"].includes(result.status))throw Error("Status could not be verified.");receipt.status=result.status;if(lastReceipt===receipt)receiptChecked=true;
        // A job that is waiting with no worker (status() in knowledge_graph.py) is said to be so, with the stored reason when there is one.
        const waiting=result.status==="pending"&&result.stalled===true,reason=["failed","pending"].includes(result.status)?value(result.error):"";
        status.textContent=`Revision ${receipt.revision} · ${tidy(result.status)}${result.status==="failed"?" · matching could not finish":waiting?" · analysis has not started":""}${reason?" · "+(waiting?reason.replace(/\.$/,""):reason):""}${waiting?". Your process is saved. Analysis can start the next time the app opens with an AI provider configured.":""}`;onStatus?.(result);}catch(e){if(e.status===403&&lastReceipt===receipt){lastReceipt=null;receiptChecked=false;status.textContent="The saved receipt could not be verified on this computer.";}else if(!quiet&&submit.open)status.textContent=`Status unavailable. ${e.message||"Try again."}`;}finally{reading=false;refresh.removeAttribute?.("aria-disabled");if(remaining-->0&&submit.open&&lastReceipt===receipt&&["pending","processing"].includes(receipt.status)&&wrap.isConnected!==false&&typeof setTimeout==="function"){
          const timer=setTimeout(()=>{if(submit.open&&lastReceipt===receipt&&wrap.isConnected!==false)void read(true);},4000);timer?.unref?.();
        }}},refresh=button("Refresh status",()=>read(false),"text-button");wrap.append(refresh);if(onStatus)void read(true);else if(["pending","processing"].includes(receipt.status)&&typeof setTimeout==="function"){const timer=setTimeout(()=>{if(submit.open&&lastReceipt===receipt&&wrap.isConnected!==false)void read(true);},4000);timer?.unref?.();}text("p","knowledge-muted","Status access is a private capability. Save the interview file to keep it, and share that file only with authorized people.",wrap);}
      else text("p","knowledge-muted","Status access is unavailable in this tab. The saved process is unaffected.",wrap);parent.append(wrap);return wrap;
    }
    function hasSubmissionEvidence(session){
      if(array(session.turns).some(turn=>turn.role==="user"&&!turn.document_event))return true;
      if(typeof session.documents?.scope!=="string"||!session.documents.scope)return false;
      const active=new Set(array(session.documents.documents).filter(file=>!file.archived&&file.analysis?.disposition!=="parked"&&["ready","partial"].includes(file.status)).map(file=>file.id));
      return array(session.document_evidence).some(source=>active.has(source.document_id)&&typeof source.id==="string"&&source.id.startsWith(source.document_id+"_")&&!source.retained_only&&!source.archived);
    }
    // Which map the stored graph will be built from. Mirrors KnowledgeGraph._materialize in
    // knowledge_graph.py; change the two together.
    function graphSource(session){
      const draft=session.draft&&typeof session.draft==="object"&&Object.keys(session.draft).length>0?session.draft:null;
      const hasSteps=map=>array(map?.steps).length>0;
      if(!draft)return "workflow";
      return session.draft_stale&&session.draft_edited!==true&&(hasSteps(session.workflow)||!hasSteps(draft))?"workflow":"draft";
    }
    // The notice claims only what the page itself saw (draftStaleReason in app.js): newer answers, a change
    // of the files in use, or nothing beyond the mark a saved file carried. Without a reason it stays neutral.
    function staleDraftNotice(session){
      const reason=value(options.draftStaleReason?.());
      const lead=reason==="answers"?"Your draft predates newer interview answers.":reason==="files"?"The files in use changed after your draft was created.":reason==="saved"?"Your draft was saved as out of date.":"Your draft is marked out of date.";
      const lacks=reason==="answers"?"will not reflect those answers":reason==="files"?"will not reflect that change":"may not reflect your latest answers or files";
      const start=lead+" The process graph (steps, roles, systems and handoffs) will be built from ";
      if(graphSource(session)==="workflow")return start+"the working map, not from the draft. The draft and the full current interview are stored with it. "+(reason==="saved"?"Update the draft first, or mark it as current in Review,":"Update the draft first")+" if the graph should match it.";
      return start+(session.draft_edited===true?"your edited draft, so it ":"your draft, because the working map has no steps; it ")+lacks+". The full current interview is stored with it."+(reason==="saved"?" If the draft is up to date, mark it as current in Review.":"");
    }
    // File passages the snapshot cites although their file is no longer in use in the interview (removed,
    // or saved for later). The server files them as saved excerpts (retained_document_evidence in server.py),
    // so the dialog names those files before the submitter confirms and can leave the passages out.
    // Only a file of the current file workspace can be filed that way: one that is listed there (saved for
    // later), or among its removed files (options.fileWorkspace, from the Assets panel). A cited file that is
    // neither (the interview was reopened on another computer, or a new file workspace was started) cannot
    // be read by the server, which refuses the citation (check_document_citations): state "unavailable".
    function savedExcerptCitations(session){
      const listed=array(session?.documents?.documents).filter(file=>file&&typeof file.id==="string");
      const workspace=options.fileWorkspace?.(),unreadable=workspace?.unavailable===true;
      const removed=array(workspace?.removed).filter(file=>file&&typeof file.id==="string");
      const known=new Map(array(session?.document_evidence).filter(source=>source&&typeof source.id==="string").map(source=>[source.id,source]));
      const ids=new Set(),files=new Map(),pending=[session];
      while(pending.length){
        const item=pending.pop();if(!item||typeof item!=="object")continue;
        if(!Array.isArray(item)&&Array.isArray(item.evidence_turns))for(const id of item.evidence_turns){
          if(typeof id!=="string"||!/^doc_[A-Za-z0-9_]{1,196}$/.test(id)||ids.has(id))continue;
          // Not a saved excerpt the server holds: it is never sent (unavailableCitations below).
          if(known.get(id)?.workspace_unavailable===true)continue;
          const file=listed.find(entry=>id.startsWith(entry.id+"_"));
          if(file&&!unreadable&&!file.archived&&file.analysis?.disposition!=="parked")continue;
          ids.add(id);
          const gone=file?null:removed.find(entry=>id.startsWith(entry.id+"_"));
          // A passage without a cached excerpt of its own still belongs to the file its ID starts with.
          const source=known.get(id)||[...known.values()].find(entry=>value(entry.document_id)&&id.startsWith(entry.document_id+"_")),key=file?.id||gone?.id||value(source?.document_id);
          const state=unreadable?"unavailable":file?(file.archived?"removed":"parked"):gone?"removed":"unavailable";
          if(!files.has(key))files.set(key,{name:value(file?.name)||value(gone?.name)||value(source?.name),state});
        }
        for(const child of Array.isArray(item)?item:Object.values(item))pending.push(child);
      }
      return {ids,files:[...files.values()]};
    }
    function savedExcerptNotice(files){
      const list=(items,name)=>{const names=items.slice(0,5).map(name);if(items.length>5)names.push(`${items.length-5} more`);return names.join(", ");};
      const kept=files.filter(file=>file.state!=="unavailable"),unread=files.filter(file=>file.state==="unavailable"),parts=[];
      if(kept.length)parts.push(`This interview cites passages of ${kept.length===1?"a file that is":"files that are"} no longer in use: ${list(kept,file=>`${file.name?`“${file.name}”`:"a file that is no longer listed"} (${file.state==="parked"?"saved for later":"removed"})`)}. Submitting stores those passages in company knowledge as saved excerpts.`);
      // Nothing is promised for a file the server cannot read: its passages are refused, not stored.
      if(unread.length)parts.push(`This interview ${kept.length?"also ":""}cites passages of ${unread.length===1?"a file that is":"files that are"} not among this interview’s files on this computer: ${list(unread,file=>file.name?`“${file.name}”`:"a file whose name is not known")}. Those passages cannot be read here, so company knowledge cannot store them. Leave them out below, or the submission will be refused.`);
      return parts.join(" ");
    }
    // Citations of excerpts saved from a file workspace this computer does not have (app.js marks them
    // workspace_unavailable when a new file workspace is started). The server cannot resolve them and never
    // takes an excerpt from the browser, so every submission is filed without them; the interview keeps them.
    function unavailableCitations(session){
      const gone=new Map(array(session?.document_evidence).filter(source=>source?.workspace_unavailable===true&&typeof source.id==="string").map(source=>[source.id,value(source.name)]));
      const ids=new Set(),names=new Set(),pending=gone.size?[session]:[];
      while(pending.length){
        const item=pending.pop();if(!item||typeof item!=="object")continue;
        if(!Array.isArray(item)&&Array.isArray(item.evidence_turns))for(const id of item.evidence_turns)if(gone.has(id)){ids.add(id);if(gone.get(id))names.add(gone.get(id));}
        for(const child of Array.isArray(item)?item:Object.values(item))pending.push(child);
      }
      return {ids,names:[...names]};
    }
    function unavailableNotice(names){
      const listed=names.slice(0,5).map(name=>`“${name}”`);
      if(names.length>5)listed.push(`${names.length-5} more`);
      return `This interview cites saved excerpts of ${names.length===1?"a file that is":"files that are"} not on this computer${listed.length?": "+listed.join(", "):""}. They cannot be checked here, so those citations are left out of this submission. The steps and notes are filed without them; your interview keeps them.`;
    }
    // Capture gate. A submission is a snapshot of the page: the transcript is complete at once, but notes
    // and the working map follow each answer by a provider round trip. While that work is running the
    // Submit button waits; when it has stopped short, "Submit anyway" says what the revision would lack.
    const participantAnswers=session=>array(session?.turns).filter(turn=>turn?.role==="user"&&!turn.document_event).length;
    const captureIncomplete=capture=>Boolean(capture&&(capture.in_progress===true||capture.notes_current===false||capture.map_current===false));
    function captureGate(){
      const state=options.captureState?.();
      return {waiting:value(state?.waiting),action:value(state?.action),missing:array(state?.missing).map(value).filter(Boolean).join(" ")};
    }
    function applyGate(view){
      if(!view||view!==submissionView||view.epoch!==sessionEpoch||view.done||pendingAttempt||activeAttempt)return null;
      const state=captureGate();
      view.shown=state.waiting?null:state.missing;
      // This runs on every page update, every status poll and its own timer. The line is a live region:
      // write it, and the button, only when something changed, or a screen reader repeats the sentence.
      const put=(element,key,next)=>{if(element[key]!==next)element[key]=next;};
      // Work that ends by itself is waited for; voice and a recording need the submitter to end them, and a
      // draft request says what waiting is for (state.action).
      const message=state.waiting?state.waiting+" "+(state.action||"Submit is available when this finishes."):state.missing?"This would be filed incomplete. "+state.missing+" Wait or retry in the interview, or submit anyway. The full transcript is stored along with a record of which updates were missing.":"";
      put(view.send,"disabled",Boolean(state.waiting));
      put(view.send,"textContent",!state.waiting&&state.missing?"Submit anyway":"Submit process");
      put(view.gate,"textContent",message);put(view.gate,"hidden",!message);
      // Safety net beside captureChanged(): a missed notification must not leave the button disabled.
      if(view.timer){clearTimeout(view.timer);view.timer=null;}
      if(state.waiting&&typeof setTimeout==="function")view.timer=setTimeout(()=>{view.timer=null;if(submit.open)applyGate(view);},1000);
      return state;
    }
    // A draft that Create draft or Update draft delivers after the snapshot was taken is not in the filed
    // revision (options.draftState, from app.js). The gate keeps Submit waiting while such a request runs;
    // this covers a request started while a submission was already on its way.
    const draftArrivals=()=>Number(options.draftState?.()?.arrivals)||0;
    function noteNewerDraft(view){
      if(!view?.done||view.draftNoted||view.epoch!==sessionEpoch||!lastFiled||draftArrivals()<=lastFiled.drafts)return;
      view.draftNoted=true;text("p","knowledge-status",`A newer draft arrived after this submission and is not part of revision ${lastFiled.revision}. Submit again to include it.`,submit).setAttribute("role","status");
    }
    function captureChanged(){if(!submit.open)return;applyGate(submissionView);noteNewerDraft(submissionView);}
    // A refusal over file citations (check_document_citations in server.py) names, per file, the cited
    // source IDs and the steps or notes that cite them. "Submit without these citations" files a copy of
    // the snapshot without every ID named so far in this dialog; the interview itself keeps its citations.
    const citationState=state=>state==="removed"?"removed from this interview":state==="parked"?"saved for later":"cannot be read";
    function showCitations(view,citations){
      for(const item of citations)for(const id of array(item?.source_ids))if(typeof id==="string")view.citationIds.add(id);
      const parts=item=>array(item?.cited_by).map(value).filter(Boolean),more=item=>Math.max(0,Number(item?.more)||0);
      view.citedList.replaceChildren();
      // One file with a few parts is complete in the server's sentence; list them when there is more to say.
      if(citations.length>1||(citations.length&&parts(citations[0]).length+more(citations[0])>3))
        for(const item of citations)text("li","",`${value(item?.name)||"A file that is not among this interview’s files"} (${citationState(item?.state)}): ${parts(item).join("; ")}${more(item)?`; and ${more(item)} more`:""}`,view.citedList);
      view.citedList.hidden=!view.citedList.children.length;view.cited.hidden=!citations.length;
    }
    function withoutCitations(payload,ids){
      let removed=0;const pending=[payload];
      while(pending.length){
        const item=pending.pop();if(!item||typeof item!=="object")continue;
        if(!Array.isArray(item)&&Array.isArray(item.evidence_turns)){const kept=item.evidence_turns.filter(id=>!ids.has(id));removed+=item.evidence_turns.length-kept.length;item.evidence_turns=kept;}
        for(const child of Array.isArray(item)?item:Object.values(item))pending.push(child);
      }
      return removed;
    }
    function submitHeading(label){
      const head=node("div","knowledge-head"),title=node("h2","",label);
      title.id="knowledge-submit-title";title.tabIndex=-1;
      head.append(title,button("Close",()=>close(submit),"text-button"));submit.replaceChildren(head);
      return title;
    }
    let submitOpener=null;
    function openSubmit(event){
      const capture=options.captureState?.();
      if(!pendingAttempt&&!isExample()&&capture?.action && /microphone|talking|recording/i.test(capture.action)){
        options.notice("Finish the recording or stop talking before submitting the process.");return;
      }
      submitOpener=event?.currentTarget===review?review:$("session-menu-toggle");
      const formEpoch=sessionEpoch;
      const current=options.session();
      if(current.synthetic_example===true){
        submitHeading("Fictional example");
        text("p","knowledge-muted","This fictional interview is for exploring the app. Company knowledge submissions are available in your own interviews.",submit);
        submit.showModal();return;
      }
      if(!pendingAttempt&&!hasSubmissionEvidence(current)){options.notice("Add an interview answer or capture a process from an attached file before submitting.",true);return;}
      submitHeading("Submit process");
      text("p","knowledge-muted","This files the interview in company knowledge on this computer, excluding your unsent answer. It is not a copy you can reopen: use Save copy for that. Matching related processes may send selected transcript statements and bounded excerpts from referenced documents to the configured AI provider and may incur charges.",submit);
      // How long a submission is kept, said before it is sent.
      text("p","knowledge-muted","A submitted process, including every revision, its transcript and the cited file passages, stays in company knowledge on this computer.",submit);
      if(!array(current.turns).some(turn=>turn.role==="user"&&!turn.document_event))text("p","knowledge-status","This capture comes from reference documents. Submitting it does not record participant confirmation or process-owner approval.",submit);
      // The revision this copy was filed as (0: a process ID without a receipt). The server refuses a revision
      // from a copy that is not based on the latest one (RevisionConflict in knowledge_graph.py) until the
      // submitter confirms it here, naming the latest revision they were shown.
      const base=lastReceipt?lastReceipt.revision:0;
      function noteLatest(latest){
        const newer=view.newer;if(!newer||!Number.isSafeInteger(latest)||latest<=base||view.done)return;
        if(newer.latest!==latest)newer.box.checked=false;
        newer.latest=latest;
        newer.line.textContent=(base?`This copy is based on revision ${base}; the latest is revision ${latest}.`:`This copy does not record which revision it is based on; the latest is revision ${latest}.`)+" Submitting it as a revision makes this older copy the newest one, without what was changed since. Open the latest saved copy instead, or confirm below.";
        newer.label.textContent=`Submit this copy as revision ${latest+1} anyway`;
        newer.block.hidden=false;
      }
      if(lastReceipt)showReceipt(submit,lastReceipt,processId?result=>noteLatest(result.latest_revision):undefined);else if(processId)text("p","knowledge-muted","A process ID was restored, but no valid status access was saved. Your process remains saved.",submit);
      if(lastReceipt&&lastFiled?.revision===lastReceipt.revision&&!pendingAttempt){
        const newer=participantAnswers(current)-lastFiled.answers;
        const notes=[lastFiled.incomplete?"was filed before the notes and working map had caught up":"",newer>0?`does not include ${newer} newer answer${newer===1?"":"s"}`:"",draftArrivals()>lastFiled.drafts?"does not include the draft created since":""].filter(Boolean);
        if(notes.length)text("p","knowledge-status",`Revision ${lastFiled.revision} ${notes.join(" and ")}. Submit again to file the interview as it stands now.`,submit);
      }
      if(current.draft&&current.draft_stale)text("p","knowledge-status",staleDraftNotice(current),submit);
      const form=node("form","knowledge-form");const participant=field(form,"Participant describing the work","participant",""),team=field(form,"Team","team",""),department=field(form,"Department","department",""),scope=field(form,"Business scope","scope","Client, fund or jurisdiction");
      const fields={participant,team,department,scope},touched=new Set(),fieldHint=text("p","knowledge-muted","",form);
      for(const [key,input] of Object.entries(fields))input.addEventListener("input",()=>touched.add(key));
      let newProcess=null;if(processId && !revisionsAvailable)text("p","knowledge-status","This interview was already filed. Submitting again will file a new, separate process.",form);
      if(processId && revisionsAvailable){const choice=node("label","knowledge-choice");newProcess=node("input");newProcess.type="checkbox";newProcess.checked=Boolean(pendingAttempt&&!pendingAttempt.payload.process_id);choice.append(newProcess,node("span","","Submit as a new process instead of a revision"));form.append(choice);text("p","knowledge-muted","Revisions require the verified owner or an authorized administrator. A new process is a second, separate record of this interview in company knowledge.",form);}
      // A revision starts from what the previous one recorded (live-draft-knowledge-2): known values are
      // shown in the fields; a field left untouched and empty is not sent, and the server keeps the earlier
      // value (KnowledgeGraph.submit); a field the submitter clears is sent empty and filed blank.
      const earlier=revisionsAvailable&&processId&&lastAttribution?lastAttribution:current.participant?{participant:current.participant}:{};
      if(!pendingAttempt)for(const [key,input] of Object.entries(fields))if(typeof earlier[key]==="string")input.value=earlier[key];
      const describeFields=()=>{fieldHint.textContent=!processId||!revisionsAvailable||newProcess?.checked?"All fields are optional. Participant names are self-reported.":
        Object.keys(earlier).length?`The fields show what ${lastReceipt?"revision "+lastReceipt.revision:"the previous revision"} recorded. Change what is no longer right; a field you clear is filed blank. Participant names are self-reported.`:
        "A revision keeps the participant, team, department and scope of the previous revision in every field you leave untouched. To file a field blank, type in it and clear it again. Participant names are self-reported.";};
      describeFields();newProcess?.addEventListener("change",describeFields);
      // Shown when a newer revision of this process is known to exist: from the status read above, or from the server's refusal.
      let newer=null;if(processId && revisionsAvailable){const block=node("div","knowledge-newer-revision"),line=text("p","knowledge-status","",block),choice=node("label","knowledge-choice"),box=node("input"),label=node("span","","");line.setAttribute("role","status");box.type="checkbox";choice.append(box,label);block.append(choice);block.hidden=true;form.append(block);newer={block,line,box,label,latest:null};}
      // Said before the submitter confirms: passages of removed or saved-for-later files are stored too, unless left out here.
      let leaveOut=null;const savedFiles=savedExcerptCitations(current).files;
      if(savedFiles.length){text("p","knowledge-status",savedExcerptNotice(savedFiles),form);const choice=node("label","knowledge-choice");leaveOut=node("input");leaveOut.type="checkbox";leaveOut.checked=Boolean(pendingAttempt?.leftOut);choice.append(leaveOut,node("span","","Leave these passages out of this submission. The steps and notes are stored without that file as their source; your interview keeps them."));form.append(choice);}
      const unavailable=unavailableCitations(current);
      if(unavailable.ids.size)text("p","knowledge-status",unavailableNotice(unavailable.names),form);
      const status=text("p","knowledge-status","",form);status.setAttribute("role","status");status.hidden=true;const gate=text("p","knowledge-status","",form);gate.setAttribute("role","status");gate.hidden=true;const send=node("button","button primary","Submit process");send.type="submit";
      // Shown when the server refuses the snapshot over file citations: the affected files and a way to file without them.
      const cited=node("div","knowledge-citations"),citedList=node("ul","knowledge-list");cited.hidden=true;
      cited.append(citedList,node("p","knowledge-muted","Submit without these citations files those steps and notes without that file as their source. Your interview keeps them."),button("Submit without these citations",()=>{view.omit=true;return onSubmit();}));
      // Shown when the server already holds this interview and no process ID was sent (another tab, or a copy
      // saved before the first Submit): the submitter chooses, instead of a twin process being created unasked.
      const conflict=node("div","knowledge-conflict"),conflictText=text("p","knowledge-status","",conflict);conflict.hidden=true;conflictText.setAttribute("role","status");
      conflict.append(node("p","knowledge-muted",revisionsAvailable?"A revision adds to the process that is already there; it requires the verified owner or an authorized administrator. A separate process is a second record of the same interview in company knowledge, beside the first.":"A separate process creates a second record of the same interview in company knowledge."));
      if(revisionsAvailable)conflict.append(button("Submit as a revision",()=>{view.choice="revision";return onSubmit();}));
      conflict.append(button("Submit as a separate process",()=>{view.choice="separate";return onSubmit();}));
      // Beside Recover, for an attempt that was never confirmed: a way out that does not need another interview.
      const discard=node("div","knowledge-discard");discard.hidden=true;
      discard.append(node("p","knowledge-muted","Or give up on that attempt to edit and submit again. If it was in fact saved, the next submission creates a separate record or a revision."),button("Discard this attempt and edit",()=>discardAttempt(),"text-button"));
      form.append(cited,conflict,send,discard);
      const view={status,gate,send,cited,citedList,citationIds:new Set(),omit:false,conflict,conflictText,conflictWith:null,choice:null,discard,fields,touched,describeFields,newProcess,leaveOut,newer,noteLatest,epoch:formEpoch,shown:"",timer:null,done:false};submissionView=view;
      const frozen=attempt=>{for(const [key,input] of Object.entries(view.fields)){input.value=value(attempt.payload[key]);input.disabled=true;}if(newProcess)newProcess.disabled=true;if(leaveOut)leaveOut.disabled=true;if(newer)newer.box.disabled=true;error(gate,"");cited.hidden=true;conflict.hidden=true;send.hidden=false;discard.hidden=activeAttempt===attempt;send.textContent=activeAttempt===attempt?"Saving submission…":"Recover previous submission";send.disabled=activeAttempt===attempt;error(status,activeAttempt===attempt?"Saving the captured submission. You can close this window while it finishes.":"The previous submission may already be saved. Recover retries that exact captured snapshot. Later interview edits remain available for an explicit new revision after recovery.");};
      // Gives up on an attempt that was never confirmed. The form starts again from what that attempt held;
      // the interview itself is untouched. Should the attempt have been saved after all, the server knows the
      // interview by its interview_id on the next submission and asks, instead of filing a twin unasked.
      const discardAttempt=()=>{
        const attempt=pendingAttempt;if(!attempt||activeAttempt===attempt||formEpoch!==sessionEpoch)return;
        pendingAttempt=null;openSubmit();
        const next=submissionView;if(!next||next===view){close(submit);return;}
        for(const [key,input] of Object.entries(next.fields))if(typeof attempt.payload[key]==="string"){input.value=attempt.payload[key];next.touched.add(key);}
        if(next.newProcess){next.newProcess.checked=Boolean(processId&&!attempt.payload.process_id);next.describeFields();}
        if(next.leaveOut)next.leaveOut.checked=Boolean(attempt.leftOut);
        error(next.status,"That attempt was discarded. If it was in fact saved, the next submission creates a separate record or a revision.");
      };
      if(pendingAttempt)frozen(pendingAttempt);else applyGate(view);
      const onSubmit=async event=>{event?.preventDefault();const omit=view.omit,choice=view.choice;view.omit=false;view.choice=null;if(send.disabled||formEpoch!==sessionEpoch)return;if(activeAttempt){frozen(activeAttempt);return;}
        let attempt=pendingAttempt;
        if(!attempt){
          // The snapshot is taken here, not when the dialog opened: check the capture again, and ask again
          // when what would be missing is not what the button last showed.
          const shown=view.shown,state=applyGate(view);
          if(state&&(state.waiting||(state.missing&&state.missing!==shown)))return;
          try{
            const session=options.session();if(session.synthetic_example===true)throw Error("The fictional example cannot be submitted to company knowledge.");
            if(!hasSubmissionEvidence(session))throw Error("The source is no longer available. Attach a file or add an interview answer before submitting.");
            // The server resolves cited IDs against the authorized file scope;
            // a browser's cached excerpt is never submitted as new authority.
            const {unsent_answer,voice_choice,knowledge_process_id,knowledge_status,knowledge_attribution,knowledge_pending_attempt,document_evidence,...data}=session;
            const key=globalThis.crypto?.randomUUID?.();if(!uuid(key))throw Error("A secure submission identifier is unavailable. Use a current browser and try again.");
            // The process this files a revision of: this tab's own, or the one the server named when it
            // recognised the interview. separate_process says a second process is the submitter's choice.
            const revised=!revisionsAvailable?null:choice==="revision"&&uuid(view.conflictWith?.process_id)?view.conflictWith.process_id:processId&&!newProcess?.checked?processId:null;
            const revising=Boolean(revised),separate=!revising&&(choice==="separate"||Boolean(processId&&(!revisionsAvailable||newProcess?.checked))),attribution={};
            for(const [name,input] of Object.entries(fields)){const entered=input.value.trim();if(!revising||entered||touched.has(name))attribution[name]=entered;}
            // Of each attached file only the ID is sent: the server rebuilds name, kind, size, digest and
            // sources from its own store, and whole review records made the request too large (data-pipeline-2).
            // A file workspace that cannot be opened on this computer is not presented as this submission's files.
            const files=session.documents&&typeof session.documents==="object"&&options.fileWorkspace?.()?.unavailable!==true?
              {scope:session.documents.scope,documents:array(session.documents.documents).filter(file=>file&&typeof file.id==="string").map(file=>({id:file.id}))}:null;
            const payload={...data,documents:files,...attribution,...(revising?{process_id:revised,base_revision:revised===processId?base:view.conflictWith.revision,...(newer?.box.checked&&newer.latest?{acknowledged_revision:newer.latest}:{})}:{}),...(separate?{separate_process:true}:{}),submission_key:key};
            attempt={payload:JSON.parse(JSON.stringify(payload)),epoch:formEpoch,drafts:draftArrivals(),attribution};
            const drop=new Set(omit?view.citationIds:[]);
            for(const id of unavailableCitations(session).ids)drop.add(id);
            if(leaveOut?.checked){attempt.leftOut=true;for(const id of savedExcerptCitations(session).ids)drop.add(id);}
            if(drop.size)attempt.omitted=withoutCitations(attempt.payload,drop);
            // Refused here, before anything is sent, with the part that makes it too large: the server would
            // refuse the same bytes, and an attempt that can never be accepted must not become one to recover.
            const size=byteLength(JSON.stringify(attempt.payload));
            if(size>submitLimit)throw Error(tooLargeMessage(attempt.payload,size));
            pendingAttempt=attempt;
          }catch(e){error(status,e.message||"Could not prepare the submission.");return;}
        }
        activeAttempt=attempt;frozen(attempt);
        try{
          const receipt=await options.request("/api/knowledge/submit",JSON.parse(JSON.stringify(attempt.payload)));
          if(attempt.epoch!==sessionEpoch||pendingAttempt!==attempt)return;
          if(!validReceipt(receipt,receipt?.process_id)||(attempt.payload.process_id&&receipt.process_id!==attempt.payload.process_id))throw Error("The server did not return a valid submission receipt.");
          // A field a revision did not send kept its earlier value on the server: what this tab knew of it still holds.
          lastAttribution={...(attempt.payload.process_id?lastAttribution:null),...attempt.attribution};
          processId=receipt.process_id;lastReceipt=receipt;receiptChecked=true;pendingAttempt=null;activeAttempt=null;
          lastFiled={revision:receipt.revision,answers:participantAnswers(attempt.payload),incomplete:captureIncomplete(attempt.payload.capture),omitted:attempt.omitted||0,drafts:attempt.drafts};
          try{options.onSubmitted?.(receipt);}catch(e){options.notice("The process is saved, but the interview could not update its save indicator. Save an interview copy before closing.",true);}
          const target=submissionView;
          if(target?.epoch===sessionEpoch){
            target.done=true;
            const title=submitHeading("Process submitted");
            // Submitting files a revision in company knowledge; it is not a copy the submitter can reopen, and the
            // status access shown below lives only in the interview file. So Save copy is said first and offered here.
            text("p","knowledge-muted","Submitted to company knowledge on this computer. To reopen or continue this interview, and to keep the status access below, you still need Save copy.",submit);
            if(options.saveCopy){
              const outcome=node("p","knowledge-muted","");outcome.setAttribute("role","status");outcome.hidden=true;
              const copy=button("Save copy",async()=>{copy.disabled=true;try{const message=await options.saveCopy();if(typeof message==="string"&&message)error(outcome,message);}catch{error(outcome,"The copy could not be saved. Choose Save copy in Menu.");}finally{copy.disabled=false;}});
              submit.append(copy,outcome);
            }
            text("p","knowledge-muted",revisionsAvailable?"You can submit later edits as a new revision.":"Later edits can be filed as a separate process.",submit);
            if(lastFiled.incomplete)text("p","knowledge-status","This revision was filed before the notes and working map had caught up with your answers. The submission includes the full transcript and records which updates were missing.",submit);
            if(lastFiled.omitted)text("p","knowledge-status",`${lastFiled.omitted} file citation${lastFiled.omitted===1?" was":"s were"} left out of this revision. Your interview keeps ${lastFiled.omitted===1?"it":"them"}.`,submit);
            showReceipt(submit,receipt);noteNewerDraft(target);if(submit.open)title.focus();
          }
          // The dialog invited the submitter to close it while this was saving: the outcome follows them to the page.
          if(!submit.open)options.notice(`Process submitted (revision ${receipt.revision}). Save a copy to keep its status access.`);
        }catch(e){
          if(attempt.epoch!==sessionEpoch||pendingAttempt!==attempt)return;
          activeAttempt=null;
          // Definitive when the server says that no record exists under this submission key (not_saved), or
          // when a first attempt, whose key is new, is answered with a refusal. After an attempt that got no
          // answer, a bare refusal is not proof: its key may hold a record ("already used for different content").
          const rejected=e.not_saved===true||(!attempt.uncertain&&([400,401,403,409,413,415,422].includes(e.status)||["knowledge_store_unavailable","document_store_unavailable"].includes(e.code)));
          if(rejected)pendingAttempt=null;
          else attempt.uncertain=true;
          const target=submissionView,message=knowledgeMessage(e);
          const already=rejected&&e.code==="interview_already_submitted"&&uuid(e.process_id)&&Number.isSafeInteger(e.revision)&&e.revision>0;
          if(target?.epoch===sessionEpoch){
            for(const [key,input] of Object.entries(target.fields)){input.value=value(attempt.payload[key]);input.disabled=!rejected;}
            if(target.newProcess)target.newProcess.disabled=!rejected;
            if(target.leaveOut)target.leaveOut.disabled=!rejected;
            if(target.newer)target.newer.box.disabled=!rejected;
            if(rejected&&e.code==="newer_revision_exists")target.noteLatest(e.latest_revision);
            target.send.textContent=rejected?"Submit process":"Recover previous submission";
            target.send.disabled=false;target.discard.hidden=rejected;
            error(target.status,already?"":rejected?message:`${message} It may already be saved. Recover retries the same captured snapshot; later edits will not be silently included.`);
            showCitations(target,rejected&&e.code==="document_citations_unavailable"?array(e.citations):[]);
            target.conflictWith=already?{process_id:e.process_id,revision:e.revision}:null;
            error(target.conflictText,already?`This interview was already submitted as Revision ${e.revision}. ${revisionsAvailable?"Submit as a revision, or as a separate process?":"File a separate process?"}`:"");target.conflict.hidden=!already;
            // With the question open, the plain Submit button would only ask it again.
            target.send.hidden=Boolean(already);
            if(rejected)applyGate(target);
          }
          if(!submit.open)options.notice(already?`This interview was already submitted as revision ${e.revision}. Open Menu > Submit process to choose how to file it.`:
            rejected?`The process was not submitted. ${message}`:"The process submission was not confirmed. Open Menu > Submission status to retry.",true);
        }
        finally{if(activeAttempt===attempt)activeAttempt=null;}
      };form.addEventListener("submit",onSubmit);submit.append(form);if(!submit.open)submit.showModal();if(!participant.disabled)participant.focus();else send.focus();
    }
    $("session-menu-toggle").addEventListener("click",()=>{
      const session=options.session();
      menu.hidden=!pendingAttempt&&!session.synthetic_example&&!hasSubmissionEvidence(session);
      menu.textContent=session.synthetic_example?"About this example":pendingAttempt?"Submission status":"Submit process";
    });
    menu.addEventListener("click",()=>{$("session-menu").hidden=true;$("session-menu-toggle").setAttribute("aria-expanded","false");openSubmit();});review.addEventListener("click",openSubmit);
    submit.addEventListener("close",()=>{if(!submit.open)submitOpener?.focus?.({preventScroll:true});});
    return {get processId(){return processId;},get hasPending(){return Boolean(pendingAttempt);},configure,reset,restore,exportReceipt,exportAttempt,exportAttribution,openSubmit,captureChanged};
  }
  window.CollectorKnowledge={create};
})();
