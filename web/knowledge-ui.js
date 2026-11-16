/* Local knowledge workspace. Administrative records are fetched only through server-authorized APIs. */
(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const node=(tag,cls,value)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=String(value);return n;};
  const value=x=>typeof x==="string"?x:typeof x==="number"?String(x):"";
  const array=x=>Array.isArray(x)?x:[];
  const show=x=>typeof x==="string"?x:JSON.stringify(x,null,2);
  const tidy=x=>value(x).replaceAll("_"," ");
  function create(options){
    const submit=$("knowledge-submit"),admin=$("knowledge-admin"),menu=$("submit-process-menu"),review=$("submit-process-review"),adminButton=$("open-knowledge-admin");
    let adminMode="",processId=null,lastReceipt=null,snapshot=null,graph=null,graphLevel="overview",section="overview",selected=null,epoch=0,filters={state:"all",team:"",system:"",scope:"",freshness:"all"};
    const PAGE_SIZE=25,offsets={},groupSelection=new Map();
    let graphQuery="",graphType="",pickerQuery="";const processTerms={submissions:"",jobs:""};
    let graphProcess=null,graphProcessName="",processPickerOpen=false,processPickerOffset=0,includeEarlier=false,entityQuery="",entityType="",groupDraft={open:false,label:"",reason:""};
    let loading=false,loadError="",focusAfterLoad=null,restoreSettingsOnClose=true,resizeListening=false;
    let sessionEpoch=0,pendingAttempt=null,activeAttempt=null,submissionView=null,lastFiled=null,lastAttribution=null,submitLimit=1000000;
    let adminExample=false,exampleSeeded=false,exampleSeedPromise=null,filtersOpen=false,adminGeneration=0,adminView=0;
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
    function reset(){stopAdminResize();sessionEpoch++;epoch++;processId=null;lastReceipt=null;lastAttribution=null;lastFiled=null;pendingAttempt=null;activeAttempt=null;submissionView=null;snapshot=null;selected=null;receiptChecked=false;groupSelection.clear();close(submit);if(admin.open){restoreSettingsOnClose=false;close(admin);}}
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
    function ensureExample(){
      if(adminMode!=="Local owner development mode")return Promise.reject(Error("The fictional example graph is available only in local owner development mode."));
      if(exampleSeeded)return Promise.resolve(true);
      if(exampleSeedPromise)return exampleSeedPromise;
      exampleSeedPromise=options.request("/api/knowledge/admin/example",{}).then(receipt=>{if(receipt?.synthetic_example!==true)throw Error("The example graph could not be verified.");exampleSeeded=true;return true;}).finally(()=>{exampleSeedPromise=null;});
      return exampleSeedPromise;
    }
    function activateExample(){
      if(!isExample()||adminButton.hidden||adminMode!=="Local owner development mode")return;
      void ensureExample().catch(()=>{if(isExample())options.notice("The example could not be added to Admin. Open Admin to retry; your interview is unchanged.",true);});
    }
    // deleteEnabled: the owner of this computer has let administrators delete a submitted process (KNOWLEDGE_ADMIN_DELETE).
    let deleteEnabled=false,revisionsAvailable=false,receiptChecked=false;
    function configure(config){revisionsAvailable=config?.revisions_available===true;adminButton.hidden=!config?.knowledge_admin_enabled;adminMode=value(config?.knowledge_admin_mode);submitLimit=Number.isSafeInteger(config?.knowledge_submit_max_bytes)&&config.knowledge_submit_max_bytes>0?config.knowledge_submit_max_bytes:1000000;deleteEnabled=config?.knowledge_delete_enabled===true;activateExample();}
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
    const adminRequest=async(path,payload)=>{try{return await options.request(path,adminExample?{...payload,example:true}:payload);}catch(error){error.message=knowledgeMessage(error);throw error;}};
    const adminContext=()=>({session:sessionEpoch,generation:adminGeneration,view:adminView,example:adminExample});
    const sameAdmin=context=>admin.open&&context.session===sessionEpoch&&context.generation===adminGeneration&&context.view===adminView&&context.example===adminExample;
    // onStatus(result) receives each verified status answer; with it the status is also read once when the
    // panel is shown, quietly, so a copy older than the newest revision of its process can say so before Submit.
    function showReceipt(parent,receipt,onStatus){
      const wrap=node("section","knowledge-block");text("h3","","Submission status",wrap);const status=text("p","knowledge-muted",`Revision ${receipt.revision} · ${tidy(receipt.status)||"pending"}`+(receiptChecked?"":" · saved receipt, not checked on this computer"),wrap);status.setAttribute("role","status");
      if(typeof receipt.status_token==="string"&&receipt.status_token){let reading=false,remaining=6;const read=async quiet=>{if(reading)return;reading=true;refresh.setAttribute("aria-disabled","true");try{const result=await options.request("/api/knowledge/status",{submission_id:receipt.submission_id,revision:receipt.revision,status_token:receipt.status_token});
        // An administrator deleted the process (delete_submission in knowledge_graph.py): no job is left to report.
        if(result?.status==="deleted"&&result.submission_id===receipt.submission_id&&result.revision===receipt.revision){status.textContent=`Revision ${receipt.revision} · deleted. An administrator removed this process from company knowledge. To file it again, submit it as a new process.`;return;}
        if(result?.submission_id!==receipt.submission_id||result?.revision!==receipt.revision||result?.job_id!==receipt.job_id||!["pending","processing","completed","failed","superseded"].includes(result.status))throw Error("Status could not be verified.");receipt.status=result.status;if(lastReceipt===receipt)receiptChecked=true;
        // A job that is waiting with no worker (status() in knowledge_graph.py) is said to be so, with the stored reason when there is one.
        const waiting=result.status==="pending"&&result.stalled===true,reason=["failed","pending"].includes(result.status)?value(result.error):"";
        status.textContent=`Revision ${receipt.revision} · ${tidy(result.status)}${result.status==="failed"?" · matching could not finish":waiting?" · analysis has not started":""}${reason?" · "+(waiting?reason.replace(/\.$/,""):reason):""}${waiting?". Your process is saved; analysis starts when the app next starts with an AI provider configured, or when an administrator retries it.":""}`;onStatus?.(result);}catch(e){if(e.status===403&&lastReceipt===receipt){lastReceipt=null;receiptChecked=false;status.textContent="The saved receipt could not be verified on this computer.";}else if(!quiet&&submit.open)status.textContent=`Status unavailable. ${e.message||"Try again."}`;}finally{reading=false;refresh.removeAttribute?.("aria-disabled");if(remaining-->0&&submit.open&&lastReceipt===receipt&&["pending","processing"].includes(receipt.status)&&wrap.isConnected!==false&&typeof setTimeout==="function"){
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
      if(kept.length)parts.push(`This interview cites passages of ${kept.length===1?"a file that is":"files that are"} no longer in use: ${list(kept,file=>`${file.name?`“${file.name}”`:"a file that is no longer listed"} (${file.state==="parked"?"saved for later":"removed"})`)}. Submitting stores those passages in company knowledge as saved excerpts, where administrators can read them.`);
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
      const message=state.waiting?state.waiting+" "+(state.action||"Submit is available when this finishes."):state.missing?"This would be filed incomplete. "+state.missing+" Wait or retry in the interview, or submit anyway: the full transcript is stored and Admin shows what was missing.":"";
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
        text("p","knowledge-muted","This fictional process can be viewed in Admin’s separate example graph. It is not submitted to company knowledge or sent for AI analysis.",submit);
        if(!adminButton.hidden&&adminMode==="Local owner development mode")submit.append(button("Open example in Admin",()=>{close(submit);openAdmin({from:"submit"});}));
        else text("p","knowledge-muted","An authorized local administrator can view the example graph.",submit);
        submit.showModal();return;
      }
      if(!pendingAttempt&&!hasSubmissionEvidence(current)){options.notice("Add an interview answer or capture a process from an attached file before submitting.",true);return;}
      submitHeading("Submit process");
      text("p","knowledge-muted","This files the interview in company knowledge on this computer, excluding your unsent answer. It is not a copy you can reopen: use Save copy for that. Matching related processes may send selected transcript statements and bounded excerpts from referenced documents to the configured AI provider and may incur charges. An administrator reviews suggested connections.",submit);
      // How long a submission is kept, said before it is sent.
      text("p","knowledge-muted","A submitted process, with every revision, its transcript and the cited file passages, stays in company knowledge on this computer"+(deleteEnabled?" until an administrator deletes it.":". This app does not delete submissions; removing one is a manual step for the owner of this computer."),submit);
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
            const session=options.session();if(session.synthetic_example===true)throw Error("Open the fictional example in Admin instead.");
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
            // Submitting files a revision for administrators; it is not a copy the submitter can reopen, and the
            // status access shown below lives only in the interview file. So Save copy is said first and offered here.
            text("p","knowledge-muted","Submitted to company knowledge on this computer. To reopen or continue this interview, and to keep the status access below, you still need Save copy.",submit);
            if(options.saveCopy){
              const outcome=node("p","knowledge-muted","");outcome.setAttribute("role","status");outcome.hidden=true;
              const copy=button("Save copy",async()=>{copy.disabled=true;try{const message=await options.saveCopy();if(typeof message==="string"&&message)error(outcome,message);}catch{error(outcome,"The copy could not be saved. Choose Save copy in More options.");}finally{copy.disabled=false;}});
              submit.append(copy,outcome);
            }
            text("p","knowledge-muted",revisionsAvailable?"You can submit later edits as a new revision.":"Later edits can be filed as a separate process.",submit);
            if(lastFiled.incomplete)text("p","knowledge-status","This revision was filed before the notes and working map had caught up with your answers. Its transcript is complete, and Admin shows what was missing.",submit);
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
          if(!submit.open)options.notice(already?`This interview was already submitted as revision ${e.revision}. Open More options > Submit process to choose how to file it.`:
            rejected?`The process was not submitted. ${message}`:"The process submission was not confirmed. Open More options > Submission status to retry.",true);
        }
        finally{if(activeAttempt===attempt)activeAttempt=null;}
      };form.addEventListener("submit",onSubmit);submit.append(form);if(!submit.open)submit.showModal();if(!participant.disabled)participant.focus();else send.focus();
    }
    const sourceSubmission=(sid,revision)=>array(snapshot?.submissions).find(s=>s.submission_id===sid&&s.revision===revision);
    const entity=id=>array(snapshot?.entities).find(item=>item.id===id);
    const label=id=>entity(id)?.label||id||"Unknown";
    const processLabel=item=>item?.display_name||item?.context?.process_name;
    // Where an entity comes from: its process and the steps that name it. Equal labels of different processes
    // (one "Ledger" per process) are otherwise indistinguishable on cards, picker rows and selection chips.
    const entitySource=item=>[value(item?.process_name),item?.step_count>1?`named by ${item.step_count} steps`:item?.step_count===1&&value(item.step_label)?`step: ${item.step_label}`:""].filter(Boolean).join(" · ");
    const entityLine=item=>[tidy(item.type),entitySource(item),"revision "+item.revision].filter(Boolean).join(" · ");
    const submissionLabel=(sid,revision)=>processLabel(sourceSubmission(sid,revision))||sid||"Unknown process";
    const evidenceRefs=item=>[...new Set([...array(item?.data?.evidence_turns),...array(item?.evidence?.evidence_turns),...array(item?.evidence).map(e=>e.turn_id).filter(Boolean),...(item?.type==="contains"?array(entity(item.target)?.data?.evidence_turns):[])])];
    function addInfo(parent,title,content){const block=node("section","knowledge-block");text("h3","",title,block);if(content===undefined||content===null||content===""||(Array.isArray(content)&&!content.length))text("p","knowledge-muted","Not established",block);else block.append(node("pre","knowledge-evidence",show(content)));parent.append(block);return block;}
    function pageInfo(result){const page=result?.page;if(!Array.isArray(result?.items)||!page||!Number.isSafeInteger(page.offset)||page.offset<0||!Number.isSafeInteger(page.limit)||page.limit<1||page.limit>50||!Number.isSafeInteger(page.total)||page.total<0||result.items.length>page.limit)throw Error("The administrative page could not be verified.");return page;}
    function pager(parent,result,onPage,name="records"){
      const page=pageInfo(result);
      if(!page.offset&&!page.has_more)return;
      const bar=node("nav","knowledge-pagination");bar.setAttribute("aria-label",name+" pages");
      const previous=button("Previous",()=>onPage(Math.max(0,page.offset-page.limit)),"knowledge-tab");previous.disabled=page.offset===0;previous.setAttribute("aria-label","Previous "+name+" page");
      const next=button("Next",()=>onPage(page.offset+page.limit),"knowledge-tab");next.disabled=!page.has_more;next.setAttribute("aria-label","Next "+name+" page");
      const count=text("span","knowledge-muted",page.total?(page.offset+1)+"–"+Math.min(page.total,page.offset+result.items.length)+" of "+page.total:"0 records",bar);count.setAttribute("role","status");bar.append(previous,next);parent.append(bar);
    }
    function listFilters(){return {...filters,...(processTerms[section]?{query:processTerms[section]}:{}),...(section==="entities"?{query:entityQuery,type:entityType,latest_only:!includeEarlier}:{})};}
    function focusControl(key){const target=[...(admin.querySelectorAll?.("[data-focus-key]")||[])].find(el=>el.dataset.focusKey===key);target?.focus?.({preventScroll:true});}
    function navigate(next){section=next;selected=null;focusAfterLoad="heading";return load();}
    function openDetail(kind,id,revision,turnId){
      selected={kind,id,revision,turn_id:turnId,returnTo:selected,returnLabel:document.activeElement?.dataset?.returnLabel||"",scrollTop:(admin.querySelector?.(".knowledge-results")||admin).scrollTop||0,pages:{}};
      focusAfterLoad="heading";return load();
    }
    function retryState(parent,message,retry){const block=node("section","knowledge-load-state");text("p","knowledge-status",message,block).setAttribute("role","status");block.append(button("Try again",retry));parent.append(block);}
    function scrollActiveTab(){
      if(!admin.open)return;const tabs=admin.querySelector?.(".knowledge-tabs"),current=tabs?.querySelector?.('[aria-current="page"]');
      if(current&&tabs.scrollWidth>tabs.clientWidth)tabs.scrollLeft=Math.max(0,current.offsetLeft-tabs.offsetLeft-8);
    }
    function startAdminResize(){if(resizeListening)return;window.addEventListener?.("resize",scrollActiveTab,{passive:true});resizeListening=true;}
    function stopAdminResize(){if(!resizeListening)return;window.removeEventListener?.("resize",scrollActiveTab);resizeListening=false;}
    function shell(){
      admin.replaceChildren();const head=node("div","knowledge-head"),title=node("h2","","Company knowledge");title.id="knowledge-admin-title";
      const actions=node("div","knowledge-actions");actions.append(button("Refresh",()=>{offsets[section]=0;return load({focus:"heading"});},"text-button"),button("Done",()=>{if(canExitAdmin())close(admin);},"text-button"));head.append(title,actions);admin.append(head);
      text("p","knowledge-owner knowledge-mode-label",adminMode||"Administrator",admin);
      if(adminExample)text("p","knowledge-example-banner","EXAMPLE MODE · Fictional data only, stored separately on this computer. No AI analysis.",admin);
      else text("p","knowledge-muted",adminMode.toLowerCase().includes("local")?"Local development data on this computer. Not shared hosted storage or a production roles system.":"Reported accounts and reviewed connections.",admin);
      const tabs=node("nav","knowledge-tabs");tabs.setAttribute("aria-label","Company knowledge sections");
      for(const [id,title] of [["overview","Overview"],["submissions","Submissions"],["connections","Connections"],["graph","Graph"],["entities","Entities"],["groups","Reviewed groups"],["jobs","Processing"]]){const b=button(title,()=>navigate(id),"knowledge-tab");if(section===id)b.setAttribute("aria-current","page");tabs.append(b);}
      const strip=node("div","knowledge-tab-strip");strip.append(tabs);admin.append(strip);
      Promise.resolve().then(scrollActiveTab);
      const active=Object.entries(filters).filter(([,v])=>v&&v!=="all"),bar=node("div","knowledge-filter-bar");
      const toggle=button("Filters"+(active.length?" ("+active.length+")":""),()=>{filtersOpen=!filtersOpen;render();admin.querySelector?.("[data-filter-toggle]")?.focus();},"knowledge-tab");toggle.dataset.filterToggle="true";toggle.setAttribute("aria-expanded",String(filtersOpen));toggle.setAttribute("aria-controls","knowledge-filters");bar.append(toggle);
      const names={team:"Team",system:"System",scope:"Scope",state:"Review state",freshness:"Freshness"};
      const changed=()=>{selected=null;for(const key of Object.keys(offsets))delete offsets[key];processPickerOffset=0;filtersOpen=false;return load({focus:"filter"});};
      for(const [key,v] of active){const title=v==="recent"?"Last 30 days":v==="older"?"Older / unknown":tidy(v),chip=button(names[key]+": "+title+" ×",()=>{filters[key]=["state","freshness"].includes(key)?"all":"";return changed();},"knowledge-filter-chip");chip.setAttribute("aria-label","Remove "+names[key].toLowerCase()+" filter: "+title);bar.append(chip);}
      if(active.length>1)bar.append(button("Clear filters",()=>{filters={state:"all",team:"",system:"",scope:"",freshness:"all"};return changed();},"text-button"));admin.append(bar);
      const controls=node("div","knowledge-filters");controls.id="knowledge-filters";controls.hidden=!filtersOpen;controls.setAttribute("role","group");controls.setAttribute("aria-label","Filter company knowledge");const inputs={};
      const apply=()=>{for(const key of ["team","system","scope"])filters[key]=inputs[key].value.trim();for(const key of ["state","freshness"])filters[key]=inputs[key].value;return changed();};
      for(const [key,title] of [["team","Team or department"],["system","System"],["scope","Scope"]]){const input=field(controls,title,key,"All");input.value=filters[key];inputs[key]=input;input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();void apply();}});}
      for(const [key,title,choices] of [["state","Review state",["all","reported","proposed","awaiting_clarification","confirmed","disputed","rejected","stale","superseded"]],["freshness","Freshness",["all","recent","older"]]]){const wrap=node("label","knowledge-field"),input=node("select");wrap.append(node("span","",title),input);for(const choice of choices){const opt=node("option","",choice==="recent"?"Last 30 days":choice==="older"?"Older / unknown":tidy(choice));opt.value=choice;input.append(opt);}input.value=filters[key];inputs[key]=input;controls.append(wrap);}
      const applyActions=node("div","knowledge-filter-actions");applyActions.append(button("Apply filters",apply,"button secondary small"),node("span","knowledge-muted","Filters apply across all saved records."));controls.append(applyActions);admin.append(controls);
      const out=node("div","knowledge-results");out.setAttribute("aria-busy",String(loading));admin.append(out);return out;
    }
    function card(parent,title,description,onSelect,recordKey=""){
      const card=node("article","knowledge-card"),heading=node("h3");
      if(onSelect){const choice=button(title,onSelect,"knowledge-record-link");choice.dataset.returnLabel=recordKey||title;heading.append(choice);}
      else heading.textContent=title;
      card.append(heading);
      if(description)text("p","knowledge-muted",description,card);
      parent.append(card);return card;
    }
    async function historyPanel(parent,title,kind,id,renderItem,empty="None recorded."){
      const block=node("section","knowledge-block knowledge-paged-region"),heading=text("h3","",title,block),body=node("div");heading.tabIndex=-1;block.append(body);parent.append(block);
      const pages=selected.pages;let sequence=0;
      async function read(offset=pages[kind]||0,focus=false){const sequenceId=++sequence,context=adminContext();body.replaceChildren(node("p","knowledge-muted","Loading "+title.toLowerCase()+"…"));
        try{const result=await adminRequest("/api/knowledge/admin/history",{kind,id,offset,limit:PAGE_SIZE});if(sequenceId!==sequence||!sameAdmin(context))return;
          const page=pageInfo(result),lastOffset=Math.max(0,Math.floor((page.total-1)/page.limit)*page.limit);
          if(offset>lastOffset)return read(lastOffset,focus);
          pages[kind]=page.offset;body.replaceChildren();if(result.analysis_limitations)text("p","knowledge-muted",result.analysis_limitations,body);if(!result.items.length)text("p","knowledge-muted",empty,body);for(const item of result.items)renderItem(body,item);pager(body,result,next=>read(next,true),title.toLowerCase());if(focus){heading.scrollIntoView?.({block:"start"});heading.focus();}}
        catch(e){if(sequenceId!==sequence||!sameAdmin(context))return;body.replaceChildren();retryState(body,e.message||"This page is unavailable.",()=>read(offset,true));}
      }return read();
    }
    function documentSources(parent,item){for(const doc of array(item.documents?.documents)){const block=node("section","knowledge-block");text("h3","",doc.name||"Supporting file",block);if(!array(doc.sources).length)text("p","knowledge-muted","No source locations available.",block);
      for(const source of array(doc.sources)){const output=node("pre","knowledge-evidence"),unverified=node("p","knowledge-status","AI visual transcription is unverified; inspect the original document before relying on it."),open=button(source.label||source.source_id,async()=>{const context=adminContext();open.disabled=true;unverified.hidden=true;output.textContent="Loading source…";try{const result=await adminRequest("/api/knowledge/admin/document-source",{submission_id:item.submission_id,revision:item.revision,document_id:doc.id,source_id:source.source_id});if(sameAdmin(context)){output.textContent=show(result.source?.text||result.source||"Source unavailable.");unverified.hidden=!(result.source?.origin==="ai_visual_transcription"||result.source?.verified===false);}}catch(e){if(sameAdmin(context))output.textContent=e.message||"Source unavailable.";}finally{if(sameAdmin(context))open.disabled=false;}},"text-button");unverified.hidden=true;block.append(open,unverified,output);}parent.append(block);}}
    function proposalEvidence(parent,items){
      const block=node("section","knowledge-block");text("h3","","Supporting evidence",block);if(!array(items).length)text("p","knowledge-muted","No evidence supplied.",block);
      for(const item of array(items)){const article=node("article","knowledge-evidence-item"),isDocument=item.type==="document_supported";text("h4","",isDocument?"Document-supported":item.type==="simulated_document_account"?"Document-derived simulation — not an employee statement":item.type==="employee_reported"?"Employee-reported statement":"Evidence type not established",article);
        text("p","knowledge-muted",submissionLabel(item.submission_id,item.revision)+" · revision "+item.revision+" · "+(isDocument?(item.label||item.source_id||"document source"):("transcript "+(item.turn_id||"location unknown"))),article);text("blockquote","knowledge-quote",item.quote||"No quotation supplied.",article);
        if(!isDocument&&item.turn_id){const open=button("Open answer "+item.turn_id,()=>openDetail("interview",item.submission_id,item.revision,item.turn_id),"text-button");open.dataset.sourceKey=item.submission_id+":"+item.revision+":"+item.turn_id;article.append(open);}
        if(isDocument){if(item.origin==="ai_visual_transcription"||item.verified===false)text("p","knowledge-status","AI visual transcription is unverified; inspect the original document before relying on it.",article);
          const output=node("pre","knowledge-evidence"),open=button("Read exact document source",async()=>{const context=adminContext();open.disabled=true;output.textContent="Loading source…";try{const result=await adminRequest("/api/knowledge/admin/document-source",{submission_id:item.submission_id,revision:item.revision,document_id:item.document_id,source_id:item.source_id});if(sameAdmin(context))output.textContent=show(result.source?.text||result.source||"Source unavailable.");}catch(e){if(sameAdmin(context))output.textContent=e.message||"Source unavailable.";}finally{if(sameAdmin(context))open.disabled=false;}},"text-button");article.append(open,output);}
        block.append(article);
      }parent.append(block);
    }
    function facts(parent,rows){const list=node("dl","knowledge-facts");for(const [label,content] of rows){text("dt","",label,list);text("dd","",value(content)||"Not established",list);}parent.append(list);}
    function listSection(parent,title,items,empty="None recorded."){const section=node("section","knowledge-block");text("h3","",title,section);const values=array(items);if(!values.length)text("p","knowledge-muted",empty,section);else{const list=node("ul","knowledge-list");for(const item of values)text("li","",typeof item==="string"?item:show(item),list);section.append(list);}parent.append(section);return section;}
    function transcript(parent,submission,focusId){const section=node("details","knowledge-transcript");section.open=Boolean(focusId);text("summary","",`Interview transcript · ${array(submission.turns).length} messages`,section);for(const turn of array(submission.turns)){const entry=node("article",`knowledge-turn${turn.id===focusId?" is-source":""}`);entry.id=`knowledge-turn-${turn.id}`;entry.tabIndex=-1;text("h4","",`${turn.document_event?"File context update":turn.role==="user"?"Participant":"AI interviewer"} · ${turn.id}`,entry);text("p","",turn.text||"",entry);section.append(entry);}if(!array(submission.turns).length)text("p","knowledge-muted","No transcript was supplied.",section);parent.append(section);if(focusId){const context=adminContext();(globalThis.requestAnimationFrame||((fn)=>Promise.resolve().then(fn)))(()=>{if(!sameAdmin(context))return;const target=$("knowledge-turn-"+focusId);target?.scrollIntoView?.({block:"center"});target?.focus?.({preventScroll:true});});}}
    function sourceEvidence(parent,sid,revision,refs){
      const submission=sourceSubmission(sid,revision),block=node("details","knowledge-block knowledge-source-evidence");text("summary","","Source evidence",block);
      const ids=[...new Set(array(refs).filter(x=>typeof x==="string"))];if(!ids.length)text("p","knowledge-muted","No source references were supplied for this item.",block);
      for(const id of ids){const turn=array(submission?.turns).find(t=>t.id===id&&t.role==="user"&&!t.document_event);
        if(id==="context"){text("p","knowledge-muted","Supplied interview context",block);text("p","",submission?.context?.background||submission?.context?.objective||"Context details are unavailable.",block);continue;}
        const source=array(submission?.document_evidence).find(item=>item.id===id);
        if(source){
          const item=node("article","knowledge-evidence-item");text("h4","","Document-supported",item);
          text("p","knowledge-muted",source.label||source.name||id,item);
          text("p","knowledge-muted","Documented information; this source does not by itself confirm current practice or process-owner approval.",item);
          if(source.retained_only||source.archived)text("p","knowledge-status","Saved excerpt from a removed or parked file; retained as provenance for the existing capture.",item);
          // How the stored text was read (validated_document_evidence in knowledge_graph.py). A revision filed before that was recorded says so.
          const origin=value(source.origin)||value(source.location?.origin);
          if(origin==="ai_visual_transcription"||source.verified===false)text("p","knowledge-status","AI visual transcription is unverified; inspect the original before relying on it.",item);
          else if(!origin)text("p","knowledge-muted","How this text was read was not recorded for this revision: it may be the file’s own text or an AI visual transcription. Inspect the original before relying on it.",item);
          const excerpt=node("details","knowledge-document-excerpt");excerpt.append(node("summary","","Read exact document excerpt"),node("pre","knowledge-evidence",source.text||"The document excerpt is unavailable in this revision."));item.append(excerpt);block.append(item);continue;
        }
        text("blockquote","knowledge-quote",turn?.text||(id.startsWith("doc_")?"Document source ":"Answer ")+id+" is unavailable in this revision.",block);
        if(turn){const open=button("Open answer "+id,()=>openDetail("interview",sid,revision,id),"text-button");open.dataset.sourceKey=sid+":"+revision+":"+id;block.append(open);}
      }parent.append(block);
    }
    function stepDetails(parent,step,sid,revision){const section=node("section","knowledge-block knowledge-step");text("h3","",`${step.id?step.id+" · ":""}${step.title||"Process step"}`,section);if(step.description)text("p","",step.description,section);facts(section,[["Owner / role",step.actor],["System / tool",step.system],["Input",step.input],["Output",step.output],["Completion",step.completion_criteria],["Handoff note",step.handoff],["Data origin",step.data_origin],["Entry mode",step.entry_mode],["Rule source",step.rule_source_ref],["Entity scope",array(step.entity_scope).join(", ")],["Parent process",step.parent_process],["Control type",array(step.control_type).join(", ")]]);sourceEvidence(section,sid,revision,step.evidence_turns);
      for(const row of array(step.operating_details)){facts(section,[[row.field[0].toUpperCase()+row.field.slice(1),row.text]]);sourceEvidence(section,sid,revision,row.evidence_turns);}
      parent.append(section);}
    function technical(parent,item){const detail=node("details","knowledge-technical"),summary=node("summary","","Technical record");detail.append(summary,node("pre","knowledge-evidence",show(item)));parent.append(detail);}
    // How far the notes and the working map reached when the revision was filed (see validate_capture_state).
    function captureSummary(capture){
      if(!capture||typeof capture!=="object")return "Not recorded";
      const answers=Number(capture.answers)||0;
      // An assumed position (a file reopened without a capture record) is not a recorded coverage: say only what is known.
      const latest=covered=>{const behind=answers-(Number(covered)||0);return behind===1?"the latest answer":behind>1?`the latest ${behind} answers`:"the latest answers";};
      const part=(label,current,covered,assumed)=>current===true?"":current!==false?label+" coverage not recorded":assumed===true?`${label} did not include ${latest(covered)} (coverage of the earlier answers was not recorded)`:Number(covered)>=answers?label+" did not reflect the latest wording of the answers":`${label} covered ${Number(covered)||0} of ${answers} answer${answers===1?"":"s"}`;
      const parts=[capture.in_progress===true?"capture had not finished":"",part("notes",capture.notes_current,capture.notes_answers,capture.notes_assumed),part("the working map",capture.map_current,capture.map_answers,capture.map_assumed)].filter(Boolean);
      return parts.length?parts.join("; "):`Complete through all ${answers} answer${answers===1?"":"s"}`;
    }
    function submissionDetails(parent,item){
      const draft=item.draft||{steps:item.workflow?.steps||[],taxonomy:item.taxonomy,connections_out:item.connections_out,memo_summary:item.memo_findings},context=item.context||{};
      if(!item.draft)text("p","knowledge-status","This revision contains the working map and interview notes. No reviewed draft was filed.",parent);
      if(item.capture_provenance?.method==="document_simulation"){const provenance=node("section","knowledge-block knowledge-provenance");provenance.setAttribute("role","note");text("h3","","Document-derived simulation — not an employee statement",provenance);text("p","knowledge-status","The interview was simulated from written documentation. No employee confirmation or process owner approval has been recorded.",provenance);listSection(provenance,"Source documents",array(item.capture_provenance.source_documents).map(doc=>value(doc?.filename)).filter(Boolean),"Source filenames were not supplied.");parent.append(provenance);}
      const summary=node("section","knowledge-block");text("h3","","Business summary",summary);text("p","",draft.overview||item.summary||"A business summary has not been supplied.",summary);facts(summary,[...(item.created_at?[["Submitted",recordedTime(item.created_at)]]:[]),["Process owner",context.process_owner],["Interview objective",context.objective],["Supplied context",context.background],["Revision",item.revision],["Participant (self-reported)",item.participant],["Verified submitter",item.submitter],["Team / department",[item.team,item.department].filter(Boolean).join(" · ")],["Scope",item.scope],["Processing",tidy(item.job_status)],["Notes and map when filed",captureSummary(item.capture)],["Trigger",draft.trigger]]);if(captureIncomplete(item.capture))text("p","knowledge-status","Filed before the notes and working map had caught up with the interview: "+captureSummary(item.capture)+". The transcript below is complete; notes, steps, roles and systems from the later answers may be missing.",summary);if(item.draft_stale)text("p","knowledge-status","This draft was marked out of date when the revision was filed: answers or files may have changed after it was written. Review the current transcript before relying on it.",summary);if(item.draft&&item.graph_source==="workflow")text("p","knowledge-status","The graph for this revision was built from the working map, not from the draft shown here.",summary);parent.append(summary);listSection(parent,"Inputs",draft.inputs);listSection(parent,"Outputs",draft.outputs);text("h3","","Detailed process steps",parent);for(const step of array(draft.steps))stepDetails(parent,step,item.submission_id,item.revision);if(!array(draft.steps).length)text("p","knowledge-muted","No process steps were supplied.",parent);listSection(parent,"Controls and checks",draft.controls);listSection(parent,"Exceptions and recovery",draft.exceptions);listSection(parent,"Open questions",draft.open_questions,"No open questions recorded. This is a submitted account and still requires owner review.");listSection(parent,"Validation notes",draft.validation_notes);
      for(const tag of array(draft.taxonomy)){const block=node("section","knowledge-block");text("h3","","Classification",block);facts(block,[["Facet",tag.facet],["Value",tag.value],["Reported scope",tag.note]]);sourceEvidence(block,item.submission_id,item.revision,tag.evidence_turns);parent.append(block);}
      for(const link of array(draft.connections_out)){const block=node("section","knowledge-block");text("h3","","Reported process dependency",block);facts(block,[["Relationship",link.relationship_type],["Counterpart",link.counterpart],["Condition",link.condition]]);sourceEvidence(block,item.submission_id,item.revision,link.evidence_turns);parent.append(block);}
      for(const variation of array(draft.variations)){const block=node("section","knowledge-block");text("h3","","Process variation",block);facts(block,[["Applies to",variation.applies_to],["Difference",variation.difference],["Reason",variation.reason],["Cost / effort",variation.cost],["Charging / billing",variation.charging],["Standardization",variation.removability],["Process boundary",variation.boundary_reason],["Variation class",variation.variant_class],["Nature",variation.substantive_or_presentation],["Reported source",variation.source],["Standard route step",variation.standard_route_ref]]);sourceEvidence(block,item.submission_id,item.revision,variation.evidence_turns);parent.append(block);}
      for(const lifecycle of array(draft.lifecycle_items)){const block=node("section","knowledge-block");text("h3","",lifecycle.item||"Work item lifecycle",block);listSection(block,"Stages",lifecycle.stages);listSection(block,"Locations",lifecycle.locations);listSection(block,"Handoffs",lifecycle.handoffs);sourceEvidence(block,item.submission_id,item.revision,lifecycle.evidence_turns);parent.append(block);}
      for(const memo of array(draft.memo_summary)){const block=node("section","knowledge-block");text("h3","",`Memo · ${tidy(memo.key)}`,block);text("p","knowledge-muted",tidy(memo.status),block);text("p","",memo.answer||"No answer supplied.",block);sourceEvidence(block,item.submission_id,item.revision,memo.evidence_turns);parent.append(block);}
      documentSources(parent,item);transcript(parent,item);technical(parent,item);if(deleteEnabled&&!adminExample)deleteProcess(parent,item);}
    // Offered only where the owner of this computer enabled it. The server checks the same switch, the
    // administrator, the latest revision shown here and the typed word (delete_submission in knowledge_graph.py).
    function deleteProcess(parent,item){
      const latest=Number.isSafeInteger(item.latest_revision)?item.latest_revision:item.revision;
      const form=node("form","knowledge-review knowledge-block");text("h3","","Delete this process",form);
      text("p","knowledge-status",`This removes the process and ${latest===1?"its one revision":"all "+latest+" revisions"} from company knowledge on this computer: the participant’s name, the transcript, the stored file passages, the graph, and every suggested or reviewed connection that quotes it. It cannot be undone. Files uploaded to the interview and saved interview files are not removed.`,form);
      const reason=field(form,"Reason for deleting","delete_reason","Why is this process removed?"),confirm=field(form,"Type DELETE to confirm","delete_confirm","DELETE"),status=text("p","knowledge-status","",form);status.setAttribute("role","status");status.hidden=true;
      const send=node("button","button secondary small","Delete process");send.type="submit";form.append(send);let sending=false;
      form.addEventListener("submit",async event=>{event.preventDefault();if(sending)return;
        if(!reason.value.trim()||confirm.value.trim()!=="DELETE"){error(status,"Give a reason and type DELETE in capitals to confirm.");return;}
        sending=true;send.disabled=true;const operation=adminContext();
        try{await adminRequest("/api/knowledge/admin/delete",{submission_id:item.submission_id,expected_revision:latest,reason:reason.value.trim(),confirm:"DELETE"});if(!sameAdmin(operation))return;section="submissions";selected=null;offsets.submissions=0;await load({focus:"heading"});}
        catch(e){if(sameAdmin(operation)){sending=false;send.disabled=false;error(status,e.message||"Could not delete the process. Refresh to review the current record.");}}
      });parent.append(form);
    }
    // What a matching job compared and kept (jobs.detail, written by _run in knowledge_graph.py): a completed
    // job is not a statement that nothing related exists, and dropped suggestions are named with their reasons.
    function jobNotes(detail){
      const notes=[];if(!detail||typeof detail!=="object")return notes;
      const compared=detail.candidates,more=detail.candidates_omitted;
      if(Number.isSafeInteger(compared))notes.push(compared===0?"No other process with a compatible scope to compare with.":`Compared with ${compared} process${compared===1?"":"es"} of a compatible scope`+(more>0?`; ${more} more compatible process${more===1?" was":"es were"} not compared (the most recent are used).`:"."));
      const dropped=detail.proposals_dropped,returned=detail.proposals_returned,kept=detail.proposals_kept;
      if(dropped>0){
        const reasons=Object.entries(detail.dropped_reasons&&typeof detail.dropped_reasons==="object"?detail.dropped_reasons:{}).map(([reason,count])=>`${reason} (${count})`).join(" ");
        notes.push(`${dropped} of ${returned} suggested connection${returned===1?"":"s"} ${dropped===1?"was":"were"} dropped for failing a check; ${kept} ${kept===1?"was":"were"} kept. ${reasons}`.trim());
      }
      return notes;
    }
    function relationshipCard(parent,item){
      return card(parent,(item.source_label||label(item.source))+" → "+(item.target_label||label(item.target)),tidy(item.status)+" · "+tidy(item.type),()=>openDetail(item.proposal_id?"proposal":"relationship",item.proposal_id||item.id));
    }
    function recordedTime(value){
      if(typeof value!=="string"||!value)return "";
      const date=new Date(value);
      if(!Number.isFinite(date.getTime()))return "";
      return date.toLocaleString("en-US",{dateStyle:"medium",timeStyle:"short"})+" ("+date.toISOString().slice(0,16).replace("T"," ")+" UTC)";
    }
    function dateSuffix(label,value){const date=recordedTime(value);return date?" · "+label+" "+date:"";}
    function reviewHistory(parent,item){const block=node("article","knowledge-history-entry");facts(block,[["Action",tidy(item.action)],["Reviewer",item.reviewer],["Recorded",recordedTime(item.created_at||item.reviewed_at)],["Reason",item.reason],["Revision",item.review_version||item.revision]]);if(item.side)facts(block,[["Side statement",item.side]]);if(item.value!==undefined)addInfo(block,"Recorded value",item.value);parent.append(block);}
    function proposalReview(parent,item){
      const view=selected;
      const revalidate=item.status==="stale" && /^Document source changed/i.test(item.stale_reason||"");
      if(!revalidate && !["proposed","awaiting_clarification","confirmed","disputed","rejected"].includes(item.status)){delete view.reviewDraft;return;}
      if(!view.reviewDraft||view.reviewDraft.revision!==item.review_version){
        view.reviewDraft={revision:item.review_version,reason:"",side:"",pending:false,message:""};
      }
      const draft=view.reviewDraft,formContext=adminContext();
      const form=node("form","knowledge-review"),labelEl=node("label","knowledge-field"),reason=node("textarea");labelEl.append(node("span","","Reason for this decision"),reason);reason.maxLength=2000;reason.required=true;form.append(labelEl);
      reason.value=draft.reason;reason.addEventListener("input",()=>{draft.reason=reason.value;});
      const sideWrap=node("label","knowledge-field"),side=node("select");sideWrap.append(node("span","","Side statement recorded by administrator (optional)"),side);
      for(const [v,l] of [["","Administrator review only"],["sender","Sending-side statement"],["receiver","Receiving-side statement"]]){const opt=node("option","",l);opt.value=v;side.append(opt);}side.value=draft.side;side.addEventListener("change",()=>{draft.side=side.value;});form.append(sideWrap);
      text("p","knowledge-muted","Record who supplied any side statement and what they confirmed in the reason. This does not verify the identity or claim that both sides confirmed.",form);
      const status=text("p","knowledge-status","",form);status.setAttribute("role","status");const actions=node("div","knowledge-actions");
      function syncForm(){
        reason.disabled=side.disabled=draft.pending;
        for(const control of actions.children)control.disabled=draft.pending;
        error(status,draft.message);
      }
      if(revalidate)text("p","knowledge-muted","Revalidating checks the original evidence and returns the connection to proposed for a new decision.",form);
      const choices=item.status==="rejected"?[["reopen","Reopen for review"]]:revalidate?[["revalidate","Revalidate evidence"]]:[["confirm","Confirm"],["clarify","Request clarification"],["dispute","Dispute"],["reject","Reject"]];
      for(const [action,title] of choices)actions.append(button(title,async()=>{
        if(draft.pending||!sameAdmin(formContext)||view.reviewDraft!==draft)return;
        if(!reason.value.trim()){reason.focus();error(status,"Enter a reason before recording a decision.");return;}
        if(action==="reject"&&typeof window.confirm==="function"&&!window.confirm("Reject this connection? Automatic matching will skip this proposal until you reopen it."))return;
        Object.assign(draft,{reason:reason.value,side:side.value,pending:true,message:""});syncForm();
        try{
          await adminRequest("/api/knowledge/admin/review",{proposal_id:item.id,action,reason:draft.reason.trim(),expected_revision:draft.revision,...(draft.side?{side:draft.side}:{})});
          if(view.reviewDraft!==draft)return;
          delete view.reviewDraft;view.pages={};
          if(admin.open&&selected===view)await load({focus:"heading"});
        }catch(e){
          draft.pending=false;draft.message=e.message||"Could not record the decision. Refresh to review the latest version.";
          if((e.status===409||/stale|superseded|proposal changed/i.test(e.message||""))&&admin.open&&selected===view){
            view.refusedReason=draft.reason;await load({focus:"heading"});}
          else if(sameAdmin(formContext))syncForm();
          else if(admin.open&&selected===view&&view.reviewDraft===draft&&!loading&&!loadError)render();
        }
      }));syncForm();form.append(actions);parent.append(form);
    }
    function entityChooser(parent,group,onChoose){
      const region=node("section","knowledge-picker"),heading=text("h4","knowledge-picker-heading","Eligible entities",region),controls=node("div","knowledge-picker-search"),query=field(controls,"Find an entity","member_query","Search all eligible records"),body=node("div");controls.append(button("Search",()=>read(0),"knowledge-tab"));region.append(controls,body);parent.append(region);heading.tabIndex=-1;let sequence=0;
      query.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();void read(0);}});
      async function read(offset,focus=false){const token=++sequence,context=adminContext(),term=query.value.trim();body.replaceChildren(node("p","knowledge-muted","Loading eligible entities…"));
        try{const result=await adminRequest("/api/knowledge/admin/browse",{section:"entities",filters:{...filters,type:group.type,query:term,latest_only:true,exclude_group_id:group.id},offset,limit:PAGE_SIZE});if(token!==sequence||!sameAdmin(context))return;pageInfo(result);body.replaceChildren();
          if(!result.items.length)text("p","knowledge-muted","No matching entities. Try another search or refine the company filters.",body);
          for(const item of result.items){const row=node("div","knowledge-picker-row");text("span","",[item.label,entitySource(item),"revision "+item.revision].filter(Boolean).join(" · "),row);if(item.canonical_id||item.latest===false)text("span","knowledge-muted",item.canonical_id?"Already grouped":"Earlier revision",row);else row.append(button("Choose",()=>onChoose(item),"text-button"));body.append(row);}pager(body,result,next=>read(next,true),"eligible entities");if(focus){heading.scrollIntoView?.({block:"start"});heading.focus();}
        }catch(e){if(token===sequence&&sameAdmin(context)){body.replaceChildren();retryState(body,e.message||"Entity choices are unavailable.",()=>read(offset));}}
      }void read(0);return region;
    }
    function groupDetails(parent,group){
      facts(parent,[["Entity type",tidy(group.type)],["Review state",tidy(group.status)],["Members",group.member_count],["Aliases",group.alias_count],["History records",group.history_count],["Review version",group.review_version]]);
      if(group.status==="stale"||group.needs_review)text("p","knowledge-status","Needs review · "+(group.stale_reason||"Source evidence changed. Review the members before revalidating."),parent);
      text("p","knowledge-muted","Groups are explicit administrator judgments. Original evidence is retained; membership and aliases can be changed with a recorded reason.",parent);
      const view=selected,change=view.groupChange?.revision===group.review_version?view.groupChange:(view.groupChange={revision:group.review_version,action:"add_member",value:"",label:"",reason:"",alias:"",pending:false});
      const form=node("form","knowledge-review knowledge-block"),reason=field(form,"Reason for change","reason","Why is this grouping appropriate?"),wrap=node("label","knowledge-field"),action=node("select");wrap.append(node("span","","Change"),action);
      for(const [v,l] of [["add_member","Add entity"],["remove_member","Remove entity"],["add_alias","Add alias"],["remove_alias","Remove alias"],...((group.status==="stale"||group.needs_review)?[["replace_outdated","Replace outdated members with the latest revision’s entities"],["revalidate","Revalidate current grouping"]]:[])]){const opt=node("option","",l);opt.value=v;action.append(opt);}action.value=change.action;form.append(wrap);
      const chosen=text("p","knowledge-muted","",form),alias=field(form,"New alias","alias","Alias label"),chooserHost=node("div"),status=text("p","knowledge-status","",form);status.setAttribute("role","status");status.hidden=true;form.append(chooserHost);const send=node("button","button secondary small","Record change");send.type="submit";form.append(send);let selectedValue=change.value,selectedLabel=change.label,sending=change.pending;reason.value=change.reason;alias.value=change.alias;send.disabled=sending;
      reason.addEventListener("input",()=>{change.reason=reason.value;});alias.addEventListener("input",()=>{change.alias=alias.value;});chosen.tabIndex=-1;chosen.setAttribute("role","status");
      const choose=(value,label,kind)=>{selectedValue=value;selectedLabel=label;action.value=kind;update(false);chosen.scrollIntoView?.({block:"center"});chosen.focus?.({preventScroll:true});};
      function update(clear=true){if(clear){selectedValue="";selectedLabel="";}Object.assign(change,{value:selectedValue,label:selectedLabel,action:action.value});chooserHost.replaceChildren();alias.parentElement.hidden=action.value!=="add_alias";
        chosen.textContent=action.value==="revalidate"?"Review the current members and evidence before revalidating.":action.value==="replace_outdated"?"Each member from an earlier revision is replaced by the entity with the same type and label in the latest revision of its process. A member without exactly one such entity stays for you to remove. Review the members and revalidate afterwards.":selectedValue?"Selected: "+selectedLabel:action.value==="remove_member"?"Choose Remove beside a member below.":action.value==="remove_alias"?"Choose Remove beside an alias below.":action.value==="add_alias"?"Enter the new alias.":"Choose an eligible entity.";
        if(action.value==="add_member")entityChooser(chooserHost,group,item=>choose(item.id,item.label,"add_member"));
      }
      action.addEventListener("change",()=>update());update(false);
      form.addEventListener("submit",async event=>{event.preventDefault();if(sending)return;const v=(["revalidate","replace_outdated"].includes(action.value)?"reviewed":action.value==="add_alias"?alias.value:selectedValue).trim();if(!v||!reason.value.trim()){error(status,"Choose a value and give a review reason.");return;}change.pending=true;sending=true;send.disabled=true;const operation=adminContext();
        try{await adminRequest("/api/knowledge/admin/canonical-update",{canonical_id:group.id,action:action.value,value:v,reason:reason.value.trim(),expected_revision:group.review_version});if(admin.open&&selected===view){delete view.groupChange;selected.pages={};await load({focus:"heading"});}}
        catch(e){change.pending=false;if(sameAdmin(operation)){sending=false;send.disabled=false;error(status,knowledgeMessage(e));}else if(admin.open&&selected===view){render();options.notice?.(knowledgeMessage(e),true);}}
      });parent.append(form);
      void historyPanel(parent,"Members and source evidence","group_members",group.id,(out,item)=>{const c=card(out,item.label,entityLine(item)+(item.latest===false?" · earlier revision":""),()=>openDetail("entity",item.id),"entity:"+item.id+":"+(item.revision||""));c.append(button("Remove member",()=>choose(item.id,item.label,"remove_member"),"text-button"));});
      void historyPanel(parent,"Reviewed aliases","group_aliases",group.id,(out,item)=>{const row=node("div","knowledge-picker-row");text("span","",item.alias,row);row.append(button("Remove alias",()=>choose(item.alias,item.alias,"remove_alias"),"text-button"));out.append(row);});
      void historyPanel(parent,"Group review history","group",group.id,reviewHistory);technical(parent,group);
    }
    function details(parent,item,kind){
      const current=selected;parent.append(button(kind==="interview"?"← Back to detail":"← Back",()=>{selected=current.returnTo;focusAfterLoad=kind==="interview"?{sourceKey:current.id+":"+current.revision+":"+current.turn_id}:{returnLabel:current.returnLabel,scrollTop:current.scrollTop};return load();},"text-button"));
      const title=kind==="proposal"?submissionLabel(item.source_submission_id,item.source_revision)+" → "+submissionLabel(item.destination_submission_id,item.destination_revision):kind==="downstream"?"Potential downstream of "+item.label:processLabel(item)||item.label||submissionLabel(item.submission_id,item.revision)||"Details";
      const heading=text("h2","knowledge-detail-title",title,parent);heading.tabIndex=-1;
      if(kind==="proposal"&&recordedTime(item.created_at))text("p","knowledge-muted","Proposed "+recordedTime(item.created_at),parent);
      if(kind==="interview"){transcript(parent,item,current.turn_id);return;}
      if(kind==="submission"){submissionDetails(parent,item);return;}
      if(kind==="group"){groupDetails(parent,item);return;}
      if(kind==="downstream"){text("p","knowledge-muted","Reachability follows reported sequence and confirmed handoffs only. It is not a measured impact; missing links and process containment may leave step-to-process effects unknown.",parent);void historyPanel(parent,"Affected connections","downstream",item.id,relationshipCard,"No reported sequence or confirmed handoffs are reachable from this entity.");return;}
      if(kind==="entity"){
        if(["process","process_version"].includes(item.type))parent.append(button("Open submitted account",()=>openDetail("submission",item.submission_id,item.revision),"text-button"));
        else if(["step","decision"].includes(item.type))stepDetails(parent,item.data||{title:item.label},item.submission_id,item.revision);
        else{facts(parent,[["Entity type",tidy(item.type)],["Label",value(item.data?.full_label)||item.label],["Source process",submissionLabel(item.submission_id,item.revision)],["Revision",item.revision]]);sourceEvidence(parent,item.submission_id,item.revision,item.data?.evidence_turns);}
        parent.append(button("Show affected connections",()=>openDetail("downstream",item.id),"text-button"));void historyPanel(parent,"Immediate upstream and downstream relationships","entity_neighbors",item.id,relationshipCard);technical(parent,item);return;
      }
      if(kind==="relationship"){facts(parent,[["From",item.source_label||label(item.source)],["To",item.target_label||label(item.target)],["Relationship",tidy(item.type)],["Evidence state",tidy(item.status)],["Condition",item.evidence?.label],["Source process",submissionLabel(item.submission_id,item.revision)],["Revision",item.revision]]);sourceEvidence(parent,item.submission_id,item.revision,evidenceRefs(item));technical(parent,item);return;}
      if(kind==="proposal"){
        if(selected.refusedReason)text("p","knowledge-status","Your review was not recorded. Previous reason: "+selected.refusedReason,parent);
        if(["stale","superseded"].includes(item.status)){
          text("p","knowledge-status",(item.stale_reason||"The underlying process or source changed.")+" Review the latest process revisions and source evidence before relying on this connection.",parent);
          parent.append(button("See current connections",()=>navigate("connections"),"text-button"));
        }
        for(const [key,title] of [["relationship_type","Relationship type"],["status","Review state"],["source_name","Sending process"],["source_revision","Sending revision"],["destination_name","Receiving process"],["destination_revision","Receiving revision"],["scope","Scope"],["condition","Condition"],["explanation","Explanation"],["inference","Inferred interpretation"]])addInfo(parent,title,item[key]);
        listSection(parent,"Missing evidence",item.missing_evidence,"No missing evidence recorded.");listSection(parent,"Contradictions",item.contradictions,"No contradictions recorded.");proposalEvidence(parent,item.evidence);void historyPanel(parent,"Connection review history","proposal",item.id,reviewHistory);proposalReview(parent,item);technical(parent,item);
      }
    }
    function entityControls(parent){
      const controls=node("div","knowledge-entity-controls"),query=field(controls,"Find entities","entity_query","Search all records"),typeWrap=node("label","knowledge-field"),type=node("select");query.value=entityQuery;typeWrap.append(node("span","","Entity type"),type);
      for(const key of ["","process_version","step","decision","role","system","business_object","team","scope"]){const opt=node("option","",key?tidy(key):"All types");opt.value=key;type.append(opt);}type.value=entityType;controls.append(typeWrap);
      const earlierWrap=node("label","knowledge-choice"),earlier=node("input");earlier.type="checkbox";earlier.checked=includeEarlier;earlierWrap.append(earlier,node("span","","Include earlier revisions"));controls.append(earlierWrap);
      const apply=()=>{entityQuery=query.value.trim();entityType=type.value;includeEarlier=earlier.checked;offsets.entities=0;focusAfterLoad="heading";return load();};controls.append(button("Search entities",apply,"knowledge-tab"));query.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();void apply();}});earlier.addEventListener("change",apply);parent.append(controls);
      const toggle=button(groupDraft.open?"Cancel grouping":"Create reviewed group",()=>{groupDraft.open=!groupDraft.open;if(!groupDraft.open){groupSelection.clear();groupDraft={open:false,label:"",reason:""};}render();focusControl("group-toggle");},"knowledge-tab");toggle.dataset.focusKey="group-toggle";toggle.setAttribute("aria-expanded",String(groupDraft.open));parent.append(toggle);
    }
    function groupCreate(parent){
      const form=node("form","knowledge-review knowledge-block");const heading=text("h3","","Create reviewed group",form);heading.tabIndex=-1;heading.dataset.focusKey="group-heading";const title=field(form,"Canonical label","label","Name for this group"),reason=field(form,"Review reason","reason","Why these records describe the same thing");title.value=groupDraft.label;reason.value=groupDraft.reason;title.addEventListener("input",()=>groupDraft.label=title.value);reason.addEventListener("input",()=>groupDraft.reason=reason.value);
      text("p","knowledge-muted","Select 2–100 current, ungrouped entities of one type. Selections are kept as you page; source records and evidence stay separate.",form);
      const selectedBox=node("div","knowledge-selected-entities");text("p","knowledge-muted",groupSelection.size+" selected",selectedBox);for(const item of groupSelection.values()){const chip=button(item.label+(item.source?" · "+item.source:"")+" ×",()=>{groupSelection.delete(item.id);render();focusControl("group-heading");},"knowledge-filter-chip");chip.setAttribute("aria-label","Remove selected entity "+item.label+(item.source?", "+item.source:""));selectedBox.append(chip);}form.append(selectedBox);
      const status=text("p","knowledge-status","",form);status.setAttribute("role","status");status.hidden=true;const send=node("button","button secondary small","Create group");send.type="submit";form.append(send);let sending=false;
      form.addEventListener("submit",async event=>{event.preventDefault();if(sending)return;groupDraft.label=title.value;groupDraft.reason=reason.value;if(!title.value.trim()||!reason.value.trim()||groupSelection.size<2){error(status,"Provide a label, reason and 2–100 entities of the same type.");return;}sending=true;send.disabled=true;const operation=adminContext();
        try{await adminRequest("/api/knowledge/admin/canonical-create",{label:title.value.trim(),entity_ids:[...groupSelection.keys()],reason:reason.value.trim()});if(!sameAdmin(operation))return;groupSelection.clear();groupDraft={open:false,label:"",reason:""};section="groups";selected=null;offsets.groups=0;await load({focus:"heading"});}
        catch(e){if(sameAdmin(operation)){error(status,e.message||"Could not create the group. Refresh to review the current records.");sending=false;send.disabled=false;}}
      });parent.append(form);
    }
    function links(data){
      const internal=array(data.edges).filter(e=>e.status==="reported").map(e=>e.type==="happens_after"?{...e,source:e.target,target:e.source,type:"before"}:e);
      const process=(sid,rev)=>array(data.entities).find(e=>e.submission_id===sid&&e.revision===rev&&e.type==="process_version")?.id;
      const reviewed=array(data.proposals).filter(p=>p.status==="confirmed").map(p=>{const source=process(p.source_submission_id,p.source_revision),target=process(p.destination_submission_id,p.destination_revision);return {id:p.id,proposal_id:p.id,source:p.relationship_type==="happens_after"?target:source,target:p.relationship_type==="happens_after"?source:target,type:p.relationship_type==="happens_after"?"before":p.relationship_type,status:"confirmed"};}).filter(e=>e.source&&e.target);return [...internal,...reviewed];
    }
    function processPicker(parent){
      const region=node("section","knowledge-block knowledge-process-picker"),heading=text("h3","","Choose a process",region),body=node("div");heading.tabIndex=-1;region.append(body);parent.append(region);let sequence=0;
      const search=node("form","knowledge-filter-bar"),find=field(search,"Find a process","picker_query","Process name");
      find.value=pickerQuery;const submit=node("button","knowledge-tab","Search");submit.type="submit";search.append(submit);region.append(search,body);
      search.addEventListener("submit",event=>{event.preventDefault();pickerQuery=find.value.trim();void read(0,true);});
      async function read(offset,focus=false){const token=++sequence,context=adminContext();processPickerOffset=offset;body.replaceChildren(node("p","knowledge-muted","Loading process choices…"));
        try{const result=await adminRequest("/api/knowledge/admin/browse",{section:"submissions",filters:{...filters,latest_only:true,...(pickerQuery?{query:pickerQuery}:{})},offset,limit:PAGE_SIZE});if(token!==sequence||!sameAdmin(context))return;pageInfo(result);body.replaceChildren();if(!result.items.length)text("p","knowledge-muted","No processes match these filters.",body);
          for(const item of result.items){const row=node("div","knowledge-picker-row");text("span","",(processLabel(item)||"Untitled process")+" · revision "+item.revision,row);row.append(button("Show process",()=>{graphProcess=item.submission_id;graphProcessName=processLabel(item)||"Selected process";processPickerOpen=false;focusAfterLoad="heading";return load();},"text-button"));body.append(row);}pager(body,result,next=>read(next,true),"process choices");if(focus){heading.scrollIntoView?.({block:"start"});heading.focus();}
        }catch(e){if(token===sequence&&sameAdmin(context)){body.replaceChildren();retryState(body,e.message||"Process choices are unavailable.",()=>read(offset,true));}}
      }void read(processPickerOffset);
    }
    function renderGraph(root,data){
      text("h2","knowledge-detail-title","Company process graph",root).tabIndex=-1;
      text("p","knowledge-muted","Reported steps and confirmed links.",root);
      const choices=node("div","knowledge-actions knowledge-graph-levels");for(const [level,title] of [["overview","Process overview"],["steps","Process steps"],["all","All entities"]]){const b=button(title,()=>{graphLevel=level;focusAfterLoad="heading";return load();},"knowledge-tab");b.setAttribute("aria-pressed",String(graphLevel===level));choices.append(b);}root.append(choices);
      // The text and type filters of the graph route (admin_graph): the way to narrow a view, above all "All entities", that exceeds the limit.
      const narrow=node("div","knowledge-entity-controls"),find=field(narrow,"Find in graph","graph_query","Label contains"),typeWrap=node("label","knowledge-field"),type=node("select");find.value=graphQuery;typeWrap.append(node("span","","Entity type"),type);
      for(const key of ["","process_version","step","decision","role","system","business_object","team","scope"]){const opt=node("option","",key?tidy(key):"All types");opt.value=key;type.append(opt);}type.value=graphType;typeWrap.hidden=graphLevel!=="all";narrow.append(typeWrap);
      const applyNarrow=()=>{graphQuery=find.value.trim();graphType=type.value;focusAfterLoad="heading";return load();};
      narrow.append(button("Search graph",applyNarrow,"knowledge-tab"));find.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();void applyNarrow();}});root.append(narrow);
      const display=array(data.entities),rawConnections=array(data.edges).length+array(data.proposals).length;
      const mustNarrow=data.too_large||display.length>80||rawConnections>150;
      const scope=node("div","knowledge-filter-bar");text("span","knowledge-muted",graphProcess?graphProcessName:"All matching processes",scope);
      if(!mustNarrow){
        const toggle=button(processPickerOpen?"Close process choices":"Choose process",()=>{processPickerOpen=!processPickerOpen;render();focusControl("process-toggle");},"knowledge-tab");
        toggle.dataset.focusKey="process-toggle";toggle.setAttribute("aria-expanded",String(processPickerOpen));scope.append(toggle);
      }
      if(graphProcess)scope.append(button("Show all processes",()=>{graphProcess=null;graphProcessName="";return load({focus:"heading"});},"text-button"));root.append(scope);
      if(data.too_large){text("p","knowledge-status",data.message||"This complete view exceeds 80 entities or 150 connections. Choose a process or refine filters.",root);if(data.counts)text("p","knowledge-muted",data.counts.nodes+" entities · "+data.counts.connections+" connections. No partial graph is displayed.",root);}
      else if(mustNarrow)text("p","knowledge-status","This view exceeds the graph limit. Choose a process or refine filters.",root);
      if(processPickerOpen||mustNarrow)processPicker(root);
      if(mustNarrow)return;
      const valid=links(data),ids=new Set(display.map(e=>e.id));
      if(valid.length!==rawConnections||valid.some(e=>!ids.has(e.source)||!ids.has(e.target))){retryState(root,"The graph contains an unresolved endpoint. Refresh or refine filters.",()=>load());return;}
      if(!display.length){text("p","knowledge-muted",graphProcess?"The chosen process does not match these filters.":"No graph entities match these filters.",root);return;}
      const canvas=node("div","knowledge-canvas");canvas.setAttribute("aria-label","Reported and confirmed knowledge graph");const controls=node("div","knowledge-actions");root.append(controls,canvas);
      const expand=button("Expand graph",()=>{const expanded=canvas.classList.toggle("knowledge-canvas-expanded");expand.textContent=expanded?"Reduce graph":"Expand graph";expand.setAttribute("aria-expanded",String(expanded));graph?.refresh?.();});
      controls.append(expand);
      const drawn=graphLevel==="steps"?valid.filter(e=>e.type!=="contains"):valid,connected=new Set(drawn.flatMap(e=>[e.source,e.target])),canvasEntities=graphLevel==="steps"?display.filter(e=>e.type!=="process_version"||connected.has(e.id)):display;
      const shortIds=new Map(canvasEntities.map((e,i)=>[e.id,"N"+(i+1)])),originalIds=new Map(canvasEntities.map((e,i)=>["N"+(i+1),e.id]));
      const component=(e,key,relation)=>value(e.data?.[key])||display.find(x=>array(data.edges).some(edge=>edge.source===e.id&&edge.target===x.id&&edge.type===relation&&edge.status==="reported"))?.label||"";
      if(!canvasEntities.length)text("p","knowledge-muted","No connected process steps match these filters.",canvas);
      else if(window.CollectorWorkflow){const context=adminContext();try{graph=window.CollectorWorkflow.create(canvas,{onSelectStep:s=>{if(sameAdmin(context)){const id=originalIds.get(s.id);if(id)return openDetail("entity",id);}}});const currentGraph=graph;controls.append(button("−",()=>currentGraph.zoom(-.15)),button("+",()=>currentGraph.zoom(.15)),button("Fit all",()=>currentGraph.fit()));Promise.resolve(graph.update({title:"Reported and confirmed company knowledge",steps:canvasEntities.map(e=>({id:shortIds.get(e.id),title:e.label||"Untitled",kind_caption:tidy(e.type)+" · "+(entitySource(e)||"Company knowledge"),type:e.type==="decision"?"decision":"activity",actor:e.type==="process_version"?"Process":component(e,"actor","performed_by"),system:e.type==="process_version"?"Revision "+e.revision:component(e,"system","uses_system"),evidence_turns:array(e.data?.evidence_turns)})),connections:drawn.map(e=>({from:shortIds.get(e.source),to:shortIds.get(e.target),label:graphLevel==="steps"&&e.type==="before"?value(e.evidence?.label):tidy(e.status)+" · "+tidy(e.type),evidence_turns:evidenceRefs(e)}))})).catch(()=>{if(sameAdmin(context))canvas.replaceChildren(node("p","knowledge-muted","Graph layout unavailable; inspect entity and connection lists."));});}catch{canvas.replaceChildren(node("p","knowledge-muted","Graph layout unavailable; inspect entity and connection lists."));}}
      else text("p","knowledge-muted","Graph layout unavailable; inspect entity and connection lists.",canvas);
      text("h3","","Visible relationships",root);for(const edge of valid)relationshipCard(root,edge);if(!valid.length)text("p","knowledge-muted","No relationships are established in this view.",root);
    }
    function render(){
      if(!admin.open)return;adminView++;if(graph){graph.destroy();graph=null;}const root=shell();
      if(loading){text("p","knowledge-muted","Loading company knowledge…",root).setAttribute("role","status");return;}
      if(loadError){retryState(root,loadError,()=>load({focus:"heading"}));return;}if(!snapshot)return;
      if(selected){details(root,snapshot.item,selected.kind);return;}
      if(section==="graph"){renderGraph(root,snapshot);return;}
      const items=array(snapshot.items);
      if(["overview","connections"].includes(section))text("p","knowledge-muted","Counts and lists show the last recorded review state. Opening a connection checks its cited document sources.",root);
      if(section==="overview"){
        text("h2","knowledge-detail-title","A view of reported work",root).tabIndex=-1;const stats=node("div","knowledge-stats"),counts=snapshot.counts||{};
        for(const [key,label] of [["processes","Processes"],["revisions","Submitted revisions"],["open_decisions","Open review decisions"],["confirmed_connections","Confirmed connections"],["processing_failures","Processing failures"]]){const s=node("div","knowledge-stat");s.append(node("strong","",counts[key]??(key==="processes"||key==="revisions"?counts.submissions:key==="open_decisions"?counts.awaiting_review:0)??0),node("span","",label));stats.append(s);}root.append(stats);
        // Jobs that were filed without a provider or left by a stop are not failures; say that they are waiting.
        if(counts.processing_stalled>0)text("p","knowledge-status",`${counts.processing_stalled} submission${counts.processing_stalled===1?" has":"s have"} waited more than five minutes for analysis that has not run. Open Processing to see and retry ${counts.processing_stalled===1?"it":"them"}.`,root).setAttribute("role","status");
        if(snapshot.analysis_limitations)text("p","knowledge-muted",snapshot.analysis_limitations,root);return;
      }
      const titles={submissions:"Employee submissions & revisions",connections:"Connection review",entities:"Reported entities",groups:"Reviewed canonical groups",jobs:"Background processing"};text("h2","knowledge-detail-title",titles[section]||"Saved records",root).tabIndex=-1;
      if(Object.hasOwn(processTerms,section)){
        const form=node("form","knowledge-filter-bar"),find=field(form,"Find a process","process_query","Process name");
        find.value=processTerms[section];const submit=node("button","knowledge-tab","Search");submit.type="submit";form.append(submit);
        form.addEventListener("submit",event=>{event.preventDefault();processTerms[section]=find.value.trim();offsets[section]=0;void load({focus:"heading"});});root.append(form);
      }
      if(section==="entities"){entityControls(root);if(groupDraft.open)groupCreate(root);}
      if(section==="groups")text("p","knowledge-muted","Reviewed groups and aliases retain the separate source records and a complete history.",root);
      if(section==="jobs")text("p","knowledge-muted","Saved submissions remain available if processing is pending or fails.",root);
      for(const item of items){
        if(section==="submissions")card(root,processLabel(item)||"Untitled process","Revision "+item.revision+(item.latest===false?" · superseded by a later revision":"")+" · "+(item.team||item.department||"Team unknown")+" · "+(tidy(item.job_status)||"Processing pending")+(item.capture_incomplete===true?" · filed before notes and map caught up":"")+dateSuffix("Submitted",item.created_at),()=>openDetail("submission",item.submission_id,item.revision),"submission:"+item.submission_id+":"+(item.revision||""));
        if(section==="connections")card(root,(item.source_name||submissionLabel(item.source_submission_id,item.source_revision))+" (r"+item.source_revision+") → "+(item.destination_name||submissionLabel(item.destination_submission_id,item.destination_revision))+" (r"+item.destination_revision+") · "+(tidy(item.relationship_type)||"Connection")+" · "+tidy(item.status),(item.scope||"Scope not established")+" · "+(item.explanation||"Open to inspect evidence and uncertainty.")+dateSuffix("Proposed",item.created_at),()=>openDetail("proposal",item.id),"proposal:"+item.id+":"+(item.revision||""));
        if(section==="groups")card(root,item.label+" · "+tidy(item.type),tidy(item.status)+" · "+item.member_count+" members · "+item.alias_count+" aliases"+(item.stale_reason?" · "+item.stale_reason:""),()=>openDetail("group",item.id),"group:"+item.id+":"+(item.revision||""));
        if(section==="entities"){
          const c=card(root,item.label||"Untitled",entityLine(item)+(item.latest===false?" · earlier revision":"")+(item.canonical_id?" · reviewed group":""),()=>openDetail("entity",item.id),"entity:"+item.id+":"+(item.revision||""));
          if(groupDraft.open){const row=node("label","knowledge-choice"),check=node("input"),selectionType=groupSelection.values().next().value?.type;check.type="checkbox";check.value=item.id;check.checked=groupSelection.has(item.id);check.disabled=Boolean(item.canonical_id)||item.latest===false||Boolean(selectionType&&selectionType!==item.type)||(!check.checked&&groupSelection.size>=100);check.setAttribute("aria-label","Select "+item.label);check.dataset.focusKey="entity:"+item.id;row.append(check,node("span","",check.disabled?"Unavailable for this group":"Select for group"));check.addEventListener("change",()=>{if(check.disabled)return;if(check.checked)groupSelection.set(item.id,{id:item.id,label:item.label,type:item.type,source:entitySource(item)});else groupSelection.delete(item.id);render();focusControl("entity:"+item.id);});c.append(row);}
        }
        if(section==="jobs"){const c=card(root,(tidy(item.status)||"Pending")+" · revision "+item.revision,(item.process_name||"Process")+" · "+(item.error||"No error reported")+" · "+(item.attempts||0)+" attempts"+dateSuffix("Queued",item.created_at));for(const note of jobNotes(item.detail))text("p","knowledge-muted",note,c);if(["failed","pending"].includes(item.status)||(item.status==="processing"&&Number.isFinite(item.detail?.claimed_at)&&Date.now()/1000-item.detail.claimed_at>=900)){const status=text("p","knowledge-status","",c);status.hidden=true;status.setAttribute("role","status");const retry=button("Retry",async()=>{retry.disabled=true;const context=adminContext();try{await adminRequest("/api/knowledge/admin/retry",{job_id:item.id});if(sameAdmin(context))await load({focus:"heading"});}catch(e){if(sameAdmin(context)){retry.disabled=false;error(status,e.message||"Could not retry this job.");}}});c.append(retry);}}
      }
      if(!items.length)text("p","knowledge-muted","No records match these filters.",root);pager(root,snapshot,next=>{offsets[section]=next;return load({focus:"heading"});},section);
    }
    async function load(settings={}){
      const token=++epoch;loading=true;loadError="";snapshot=null;if(settings.focus)focusAfterLoad=settings.focus;render();const context=adminContext(),choice=selected,currentSection=section;
      const active=()=>token===epoch&&admin.open&&context.session===sessionEpoch&&context.generation===adminGeneration&&context.example===adminExample;
      try{
        if(adminExample)await ensureExample();if(!active())return;let result;
        if(choice){const kind=["interview","submission"].includes(choice.kind)?"submission":choice.kind==="downstream"?"entity":choice.kind;result=await adminRequest("/api/knowledge/admin/detail",{kind,id:choice.id,...(choice.revision!==undefined?{revision:choice.revision}:{})});if(!result?.item||typeof result.item!=="object"||Array.isArray(result.item))throw Error("The saved detail could not be verified.");}
        else if(currentSection==="graph"){result=await adminRequest("/api/knowledge/admin/graph",{filters:{...filters,...(graphQuery?{query:graphQuery}:{}),...(graphLevel==="all"&&graphType?{type:graphType}:{})},level:graphLevel,...(graphProcess?{submission_id:graphProcess}:{})});if(!Array.isArray(result?.entities)||!Array.isArray(result?.edges)||!Array.isArray(result?.proposals)||typeof result?.too_large!=="boolean")throw Error("The graph response could not be verified.");}
        else{result=await adminRequest("/api/knowledge/admin/browse",{section:currentSection,filters:listFilters(),offset:offsets[currentSection]||0,limit:PAGE_SIZE});const page=pageInfo(result);if(active()&&page.total>0&&page.offset>=page.total){offsets[currentSection]=Math.floor((page.total-1)/page.limit)*page.limit;return load(settings);}}
        if(!active())return;snapshot=result;loading=false;render();const focus=focusAfterLoad;focusAfterLoad=null;
        if(focus&&!(choice?.kind==="interview"&&choice.turn_id)){const target=focus?.returnLabel?([...(admin.querySelectorAll?.(".knowledge-record-link")||[])].find(el=>el.dataset.returnLabel===focus.returnLabel)||admin.querySelector?.(".knowledge-detail-title")):typeof focus==="object"?([...(admin.querySelectorAll?.("[data-source-key]")||[])].find(el=>el.dataset.sourceKey===focus.sourceKey)||admin.querySelector?.(".knowledge-detail-title")):focus==="filter"?admin.querySelector?.("[data-filter-toggle]"):admin.querySelector?.(".knowledge-detail-title");if(focus?.returnLabel)(admin.querySelector?.(".knowledge-results")||admin).scrollTop=focus.scrollTop||0;
          for(let panel=target?.closest?.("details");panel;panel=panel.parentElement?.closest?.("details"))panel.open=true;
          target?.scrollIntoView?.({block:"nearest"});target?.focus?.({preventScroll:true});}
      }catch(e){if(!active())return;loading=false;loadError=e.message||"Administrative data is unavailable.";render();}
    }
    function canExitAdmin(){
      const edit=selected?.groupChange,review=selected?.reviewDraft;
      const dirty=Boolean(review?.reason||review?.side||edit?.reason||edit?.alias||edit?.value||groupSelection.size||groupDraft.label||groupDraft.reason);
      return !dirty||window.confirm?.("Discard the unrecorded review or group changes and close Admin?")===true;
    }
    admin.addEventListener("cancel",event=>{if(!canExitAdmin())event.preventDefault();});
    function openAdmin({from="settings"}={}){
      if(adminButton.hidden)return;adminGeneration++;const nextExample=isExample();if(nextExample!==adminExample){filters={state:"all",team:"",system:"",scope:"",freshness:"all"};filtersOpen=false;section="overview";graphLevel=nextExample?"steps":"overview";for(const key of Object.keys(offsets))delete offsets[key];graphProcess=null;graphProcessName="";graphQuery="";graphType="";processPickerOpen=false;processPickerOffset=0;entityQuery="";entityType="";includeEarlier=false;groupSelection.clear();groupDraft={open:false,label:"",reason:""};}
      adminExample=nextExample;restoreSettingsOnClose=from==="settings";selected=null;snapshot=null;close($("interview-settings"));if(!admin.open)admin.showModal();startAdminResize();void load({focus:"heading"});
    }
    $("session-menu-toggle").addEventListener("click",()=>{
      const session=options.session();
      menu.hidden=!pendingAttempt&&!session.synthetic_example&&!hasSubmissionEvidence(session);
      menu.textContent=session.synthetic_example?"About this example":pendingAttempt?"Submission status":"Submit process";
    });
    menu.addEventListener("click",()=>{$("session-menu").hidden=true;$("session-menu-toggle").setAttribute("aria-expanded","false");openSubmit();});review.addEventListener("click",openSubmit);adminButton.addEventListener("click",openAdmin);
    submit.addEventListener("close",()=>{if(!submit.open&&!admin.open)submitOpener?.focus?.({preventScroll:true});});
    admin.addEventListener("close",()=>{if(admin.open)return;stopAdminResize();epoch++;adminGeneration++;if(graph){graph.destroy();graph=null;}snapshot=null;selected=null;groupSelection.clear();groupDraft={open:false,label:"",reason:""};const settings=$("interview-settings");if(restoreSettingsOnClose){if(!settings.open)settings.showModal();adminButton.focus({preventScroll:true});}else $("session-menu-toggle")?.focus?.({preventScroll:true});restoreSettingsOnClose=true;});
    return {get processId(){return processId;},get hasPending(){return Boolean(pendingAttempt);},configure,reset,restore,exportReceipt,exportAttempt,exportAttribution,openSubmit,captureChanged,activateExample};
  }
  window.CollectorKnowledge={create};
})();
