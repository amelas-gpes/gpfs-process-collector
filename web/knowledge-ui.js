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
    let graphProcess=null,graphProcessName="",processPickerOpen=false,processPickerOffset=0,includeEarlier=false,entityQuery="",entityType="",groupDraft={open:false,label:"",reason:""};
    let loading=false,loadError="",focusAfterLoad=null,restoreSettingsOnClose=true,resizeListening=false;
    let sessionEpoch=0,pendingAttempt=null,activeAttempt=null,submissionView=null;
    let adminExample=false,exampleSeeded=false,exampleSeedPromise=null,filtersOpen=false,adminGeneration=0,adminView=0;
    const button=(label,fn,cls="button secondary small")=>{const b=node("button",cls,label);b.type="button";b.addEventListener("click",fn);return b;};
    const text=(tag,cls,label,parent)=>{const n=node(tag,cls,label);parent.append(n);return n;};
    const field=(parent,label,name,placeholder)=>{const wrap=node("label","knowledge-field"),input=node("input");wrap.append(node("span","",label),input);input.name=name;input.maxLength=500;input.placeholder=placeholder;parent.append(wrap);return input;};
    const error=(container,message)=>{container.textContent=message||"";container.hidden=!message;};
    const close=dialog=>{if(dialog.open)dialog.close();};
    const uuid=x=>typeof x==="string"&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(x);
    function validReceipt(receipt,id){return receipt&&uuid(id)&&receipt.process_id===id&&uuid(receipt.submission_id)&&uuid(receipt.job_id)&&Number.isSafeInteger(receipt.revision)&&receipt.revision>0&&typeof receipt.status_token==="string"&&/^[0-9a-f]{64}$/i.test(receipt.status_token)&&["pending","processing","completed","failed","superseded"].includes(receipt.status);}
    function exportReceipt(){return validReceipt(lastReceipt,processId)?{submission_id:lastReceipt.submission_id,process_id:processId,revision:lastReceipt.revision,job_id:lastReceipt.job_id,status:lastReceipt.status,status_token:lastReceipt.status_token}:null;}
    function reset(){stopAdminResize();sessionEpoch++;epoch++;processId=null;lastReceipt=null;pendingAttempt=null;activeAttempt=null;submissionView=null;snapshot=null;selected=null;groupSelection.clear();close(submit);if(admin.open){restoreSettingsOnClose=false;close(admin);}}
    function restore(id,receipt){reset();processId=uuid(id)?id:null;lastReceipt=validReceipt(receipt,processId)?{submission_id:receipt.submission_id,process_id:receipt.process_id,revision:receipt.revision,job_id:receipt.job_id,status:receipt.status,status_token:receipt.status_token}:null;}
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
    function configure(config){adminButton.hidden=!config?.knowledge_admin_enabled;adminMode=value(config?.knowledge_admin_mode);activateExample();}
    const adminRequest=(path,payload)=>options.request(path,adminExample?{...payload,example:true}:payload);
    const adminContext=()=>({session:sessionEpoch,generation:adminGeneration,view:adminView,example:adminExample});
    const sameAdmin=context=>admin.open&&context.session===sessionEpoch&&context.generation===adminGeneration&&context.view===adminView&&context.example===adminExample;
    function showReceipt(parent,receipt){
      const wrap=node("section","knowledge-block");text("h3","","Submission status",wrap);const status=text("p","knowledge-muted",`Revision ${receipt.revision} · ${tidy(receipt.status)||"pending"}`,wrap);status.setAttribute("role","status");
      if(typeof receipt.status_token==="string"&&receipt.status_token){const refresh=button("Refresh status",async()=>{refresh.disabled=true;try{const result=await options.request("/api/knowledge/status",{submission_id:receipt.submission_id,revision:receipt.revision,status_token:receipt.status_token});if(result?.submission_id!==receipt.submission_id||result?.revision!==receipt.revision||result?.job_id!==receipt.job_id||!["pending","processing","completed","failed","superseded"].includes(result.status))throw Error("Status could not be verified.");receipt.status=result.status;status.textContent=`Revision ${receipt.revision} · ${tidy(result.status)}${result.status==="failed"?" · processing needs attention": ""}`;}catch(e){status.textContent=`Status unavailable. ${e.message||"Try again."}`;}finally{refresh.disabled=false;}},"text-button");wrap.append(refresh);text("p","knowledge-muted","Status access is a private capability. Save the interview file to keep it, and share that file only with authorized people.",wrap);}
      else text("p","knowledge-muted","Status access is unavailable in this tab. The saved process is unaffected.",wrap);parent.append(wrap);
    }
    function openSubmit(){
      const formEpoch=sessionEpoch;
      const current=options.session();
      if(current.synthetic_example===true){
        submit.replaceChildren();const head=node("div","knowledge-head");head.append(node("div","","Fictional example"),button("Close",()=>close(submit),"text-button"));head.firstElementChild.id="knowledge-submit-title";submit.append(head);
        text("p","knowledge-muted","This fictional process can be viewed in Admin’s separate example graph. It is not submitted to company knowledge or sent for AI analysis.",submit);
        if(!adminButton.hidden)submit.append(button("Open example in Admin",()=>{close(submit);openAdmin();}));
        else text("p","knowledge-muted","An authorized local administrator can view the example graph.",submit);
        submit.showModal();return;
      }
      if(!array(current.turns).some(t=>t.role==="user"&&!t.document_event)){options.notice("Add an interview answer before submitting a process.",true);return;}
      submit.replaceChildren();const head=node("div","knowledge-head");head.append(node("div","", "Submit process"),button("Close",()=>close(submit),"text-button"));head.firstElementChild.id="knowledge-submit-title";submit.append(head);
      text("p","knowledge-muted","Save this interview as a submitted process for local review. For cross-process matching, selected transcript statements and bounded excerpts from referenced documents may be sent to the configured AI provider and may incur charges. AI connections require administrator review. Your unsent answer is not included; you can continue editing the interview.",submit);
      if(lastReceipt)showReceipt(submit,lastReceipt);else if(processId)text("p","knowledge-muted","A process ID was restored, but no valid status access was saved. Your process remains saved.",submit);
      if(current.draft_stale)text("p","knowledge-status","Your draft predates newer interview answers. The submitted process will include that stale draft and the full current interview; reconcile it before relying on its details.",submit);
      const form=node("form","knowledge-form");const participant=field(form,"Participant describing the work","participant","Optional name (not verified)"),team=field(form,"Team","team","Optional"),department=field(form,"Department","department","Optional"),scope=field(form,"Business scope","scope","Client, fund, jurisdiction or other scope");
      text("p","knowledge-muted","Names entered here are participant-provided, not authenticated identities. Unknown details may be left blank.",form);
      let newProcess=null;if(processId&&!pendingAttempt){const choice=node("label","knowledge-choice");newProcess=node("input");newProcess.type="checkbox";choice.append(newProcess,node("span","","Submit as a new process instead of a revision"));form.append(choice);text("p","knowledge-muted","Revisions require the verified owner or an authorized administrator.",form);}
      const status=text("p","knowledge-status","",form);status.setAttribute("role","status");status.hidden=true;const send=node("button","button primary","Submit process");send.type="submit";form.append(send);
      const view={form,status,send,fields:{participant,team,department,scope},newProcess,epoch:formEpoch};submissionView=view;
      const frozen=attempt=>{for(const [key,input] of Object.entries(view.fields)){input.value=value(attempt.payload[key]);input.disabled=true;}if(newProcess)newProcess.disabled=true;send.textContent=activeAttempt===attempt?"Saving submission…":"Recover previous submission";send.disabled=activeAttempt===attempt;error(status,activeAttempt===attempt?"Saving the captured submission. You can close this window while it finishes.":"The previous submission may already be saved. Recover retries that exact captured snapshot. Later interview edits remain available for an explicit new revision after recovery.");};
      if(pendingAttempt)frozen(pendingAttempt);
      form.addEventListener("submit",async event=>{event.preventDefault();if(send.disabled||formEpoch!==sessionEpoch)return;if(activeAttempt){frozen(activeAttempt);return;}
        let attempt=pendingAttempt;
        if(!attempt){
          try{
            const session=options.session();if(session.synthetic_example===true)throw Error("Open the fictional example in Admin instead.");
            const {unsent_answer,voice_choice,knowledge_process_id,knowledge_status,...data}=session;
            const key=globalThis.crypto?.randomUUID?.();if(!uuid(key))throw Error("A secure submission identifier is unavailable. Use a current browser and try again.");
            const payload={...data,participant:participant.value.trim(),team:team.value.trim(),department:department.value.trim(),scope:scope.value.trim(),...(processId&&!newProcess?.checked?{process_id:processId}:{}),submission_key:key};
            attempt={payload:JSON.parse(JSON.stringify(payload)),epoch:formEpoch};pendingAttempt=attempt;
          }catch(e){error(status,e.message||"Could not prepare the submission.");return;}
        }
        activeAttempt=attempt;frozen(attempt);
        try{
          const receipt=await options.request("/api/knowledge/submit",JSON.parse(JSON.stringify(attempt.payload)));
          if(attempt.epoch!==sessionEpoch||pendingAttempt!==attempt)return;
          if(!validReceipt(receipt,receipt?.process_id)||(attempt.payload.process_id&&receipt.process_id!==attempt.payload.process_id))throw Error("The server did not return a valid submission receipt.");
          processId=receipt.process_id;lastReceipt=receipt;pendingAttempt=null;activeAttempt=null;
          try{options.onSubmitted?.(receipt);}catch(e){options.notice("The process is saved, but the interview could not update its save indicator. Save an interview copy before closing.",true);}
          const target=submissionView;
          if(target?.epoch===sessionEpoch){target.form.replaceChildren();text("h3","","Process submitted",target.form);text("p","knowledge-muted","The captured snapshot is saved locally. Later interview edits remain available; submit a new revision when you’re ready.",target.form);showReceipt(target.form,receipt);target.form.append(button("Done",()=>close(submit)));}
        }catch(e){if(attempt.epoch===sessionEpoch&&pendingAttempt===attempt){activeAttempt=null;const target=submissionView;if(target?.epoch===sessionEpoch){for(const [key,input] of Object.entries(target.fields)){input.value=value(attempt.payload[key]);input.disabled=true;}target.send.textContent="Recover previous submission";target.send.disabled=false;error(target.status,`${e.message||"Could not confirm the submission."} It may already be saved. Recover retries the same captured snapshot; later edits will not be silently included.`);}}}
        finally{if(activeAttempt===attempt)activeAttempt=null;}
      });submit.append(form);if(!submit.open)submit.showModal();if(!participant.disabled)participant.focus();else send.focus();
    }
    const descriptor=item=>item?{kind:item.kind,id:item.id,revision:item.revision,turn_id:item.turn_id,returnTo:item.returnTo}:null;
    const sourceSubmission=(sid,revision)=>array(snapshot?.submissions).find(s=>s.submission_id===sid&&s.revision===revision);
    const entity=id=>array(snapshot?.entities).find(item=>item.id===id);
    const label=id=>entity(id)?.label||id||"Unknown";
    const submissionLabel=(sid,revision)=>sourceSubmission(sid,revision)?.context?.process_name||sid||"Unknown process";
    const evidenceRefs=item=>[...new Set([...array(item?.data?.evidence_turns),...array(item?.evidence?.evidence_turns),...array(item?.evidence).map(e=>e.turn_id).filter(Boolean),...(item?.type==="contains"?array(entity(item.target)?.data?.evidence_turns):[])])];
    function addInfo(parent,title,content){const block=node("section","knowledge-block");text("h3","",title,block);if(content===undefined||content===null||content===""||(Array.isArray(content)&&!content.length))text("p","knowledge-muted","Not established",block);else block.append(node("pre","knowledge-evidence",show(content)));parent.append(block);return block;}
    function pageInfo(result){const page=result?.page;if(!Array.isArray(result?.items)||!page||!Number.isSafeInteger(page.offset)||page.offset<0||!Number.isSafeInteger(page.limit)||page.limit<1||page.limit>50||!Number.isSafeInteger(page.total)||page.total<0||result.items.length>page.limit)throw Error("The administrative page could not be verified.");return page;}
    function pager(parent,result,onPage,name="records"){
      const page=pageInfo(result),bar=node("nav","knowledge-pagination");bar.setAttribute("aria-label",name+" pages");
      const previous=button("Previous",()=>onPage(Math.max(0,page.offset-page.limit)),"knowledge-tab");previous.disabled=page.offset===0;previous.setAttribute("aria-label","Previous "+name+" page");
      const next=button("Next",()=>onPage(page.offset+page.limit),"knowledge-tab");next.disabled=!page.has_more;next.setAttribute("aria-label","Next "+name+" page");
      const count=text("span","knowledge-muted",page.total?(page.offset+1)+"–"+Math.min(page.total,page.offset+result.items.length)+" of "+page.total:"0 records",bar);count.setAttribute("role","status");bar.append(previous,next);parent.append(bar);
    }
    function listFilters(){return {...filters,...(section==="entities"?{query:entityQuery,type:entityType,latest_only:!includeEarlier}:{})};}
    function focusControl(key){const target=[...(admin.querySelectorAll?.("[data-focus-key]")||[])].find(el=>el.dataset.focusKey===key);target?.focus?.({preventScroll:true});}
    function navigate(next){section=next;selected=null;focusAfterLoad="heading";return load();}
    function openDetail(kind,id,revision,extra={}){selected={kind,id,revision,...extra};focusAfterLoad="heading";return load();}
    function retryState(parent,message,retry){const block=node("section","knowledge-load-state");text("p","knowledge-status",message,block).setAttribute("role","status");block.append(button("Try again",retry));parent.append(block);}
    function scrollActiveTab(){
      if(!admin.open)return;const tabs=admin.querySelector?.(".knowledge-tabs"),current=tabs?.querySelector?.('[aria-current="page"]');
      if(current&&tabs.scrollWidth>tabs.clientWidth)tabs.scrollLeft=Math.max(0,current.offsetLeft-tabs.offsetLeft-8);
    }
    function startAdminResize(){if(resizeListening)return;window.addEventListener?.("resize",scrollActiveTab,{passive:true});resizeListening=true;}
    function stopAdminResize(){if(!resizeListening)return;window.removeEventListener?.("resize",scrollActiveTab);resizeListening=false;}
    function shell(){
      admin.replaceChildren();const head=node("div","knowledge-head"),title=node("div","","Company knowledge");title.id="knowledge-admin-title";
      const actions=node("div","knowledge-actions");actions.append(button("Refresh",()=>{offsets[section]=0;return load({focus:"heading"});},"text-button"),button("Done",()=>close(admin),"text-button"));head.append(title,actions);admin.append(head);
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
      const changed=()=>{selected=null;for(const key of Object.keys(offsets))delete offsets[key];processPickerOffset=0;graphProcess=null;graphProcessName="";filtersOpen=false;return load({focus:"filter"});};
      for(const [key,v] of active){const title=v==="recent"?"Last 30 days":v==="older"?"Older / unknown":tidy(v),chip=button(names[key]+": "+title+" ×",()=>{filters[key]=["state","freshness"].includes(key)?"all":"";return changed();},"knowledge-filter-chip");chip.setAttribute("aria-label","Remove "+names[key].toLowerCase()+" filter: "+title);bar.append(chip);}
      if(active.length>1)bar.append(button("Clear filters",()=>{filters={state:"all",team:"",system:"",scope:"",freshness:"all"};return changed();},"text-button"));admin.append(bar);
      const controls=node("div","knowledge-filters");controls.id="knowledge-filters";controls.hidden=!filtersOpen;controls.setAttribute("role","group");controls.setAttribute("aria-label","Filter company knowledge");const inputs={};
      const apply=()=>{for(const key of ["team","system","scope"])filters[key]=inputs[key].value.trim();for(const key of ["state","freshness"])filters[key]=inputs[key].value;return changed();};
      for(const [key,title] of [["team","Team or department"],["system","System"],["scope","Scope"]]){const input=field(controls,title,key,"All");input.value=filters[key];inputs[key]=input;input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();void apply();}});}
      for(const [key,title,choices] of [["state","Review state",["all","reported","proposed","awaiting_clarification","confirmed","disputed","rejected","stale","superseded"]],["freshness","Freshness",["all","recent","older"]]]){const wrap=node("label","knowledge-field"),input=node("select");wrap.append(node("span","",title),input);for(const choice of choices){const opt=node("option","",choice==="recent"?"Last 30 days":choice==="older"?"Older / unknown":tidy(choice));opt.value=choice;input.append(opt);}input.value=filters[key];inputs[key]=input;controls.append(wrap);}
      const applyActions=node("div","knowledge-filter-actions");applyActions.append(button("Apply filters",apply,"button secondary small"),node("span","knowledge-muted","Filters apply across all saved records."));controls.append(applyActions);admin.append(controls);
      const out=node("div","knowledge-results");out.setAttribute("aria-busy",String(loading));admin.append(out);return out;
    }
    function card(parent,title,description,onSelect){const c=node("article","knowledge-card");text("h3","",title,c);if(description)text("p","knowledge-muted",description,c);if(onSelect)c.append(button("View details",onSelect,"text-button"));parent.append(c);return c;}
    async function historyPanel(parent,title,kind,id,renderItem,empty="None recorded."){
      const block=node("section","knowledge-block knowledge-paged-region"),heading=text("h3","",title,block),body=node("div");heading.tabIndex=-1;block.append(body);parent.append(block);
      let sequence=0;
      async function read(offset=0,focus=false){const sequenceId=++sequence,context=adminContext();body.replaceChildren(node("p","knowledge-muted","Loading "+title.toLowerCase()+"…"));
        try{const result=await adminRequest("/api/knowledge/admin/history",{kind,id,offset,limit:PAGE_SIZE});if(sequenceId!==sequence||!sameAdmin(context))return;pageInfo(result);body.replaceChildren();if(result.analysis_limitations)text("p","knowledge-muted",result.analysis_limitations,body);if(!result.items.length)text("p","knowledge-muted",empty,body);for(const item of result.items)renderItem(body,item);pager(body,result,next=>read(next,true),title.toLowerCase());if(focus)heading.focus({preventScroll:true});}
        catch(e){if(sequenceId!==sequence||!sameAdmin(context))return;body.replaceChildren();retryState(body,e.message||"This page is unavailable.",()=>read(offset,true));}
      }return read();
    }
    function documentSources(parent,item){for(const doc of array(item.documents?.documents)){const block=node("section","knowledge-block");text("h3","",doc.name||"Supporting file",block);if(!array(doc.sources).length)text("p","knowledge-muted","No source locations available.",block);
      for(const source of array(doc.sources)){const output=node("pre","knowledge-evidence"),open=button(source.label||source.source_id,async()=>{const context=adminContext();open.disabled=true;output.textContent="Loading source…";try{const result=await adminRequest("/api/knowledge/admin/document-source",{submission_id:item.submission_id,revision:item.revision,document_id:doc.id,source_id:source.source_id});if(sameAdmin(context))output.textContent=show(result.source?.text||result.source||"Source unavailable.");}catch(e){if(sameAdmin(context))output.textContent=e.message||"Source unavailable.";}finally{if(sameAdmin(context))open.disabled=false;}},"text-button");block.append(open,output);}parent.append(block);}}
    function proposalEvidence(parent,items){
      const block=node("section","knowledge-block");text("h3","","Supporting evidence",block);if(!array(items).length)text("p","knowledge-muted","No evidence supplied.",block);
      for(const item of array(items)){const article=node("article","knowledge-evidence-item"),isDocument=item.type==="document_supported";text("h4","",isDocument?"Document-supported":item.type==="simulated_document_account"?"Document-derived simulation — not an employee statement":item.type==="employee_reported"?"Employee-reported statement":"Evidence type not established",article);
        text("p","knowledge-muted",submissionLabel(item.submission_id,item.revision)+" · revision "+item.revision+" · "+(isDocument?(item.label||item.source_id||"document source"):("transcript "+(item.turn_id||"location unknown"))),article);text("blockquote","knowledge-quote",item.quote||"No quotation supplied.",article);
        if(!isDocument&&item.turn_id){const open=button("Open answer "+item.turn_id,()=>openDetail("interview",item.submission_id,item.revision,{turn_id:item.turn_id,returnTo:descriptor(selected)}),"text-button");open.dataset.sourceKey=item.submission_id+":"+item.revision+":"+item.turn_id;article.append(open);}
        if(isDocument){if(item.origin==="ai_visual_transcription"||item.verified===false)text("p","knowledge-status","AI visual transcription is unverified; inspect the original document before relying on it.",article);
          const output=node("pre","knowledge-evidence"),open=button("Read exact document source",async()=>{const context=adminContext();open.disabled=true;output.textContent="Loading source…";try{const result=await adminRequest("/api/knowledge/admin/document-source",{submission_id:item.submission_id,revision:item.revision,document_id:item.document_id,source_id:item.source_id});if(sameAdmin(context))output.textContent=show(result.source?.text||result.source||"Source unavailable.");}catch(e){if(sameAdmin(context))output.textContent=e.message||"Source unavailable.";}finally{if(sameAdmin(context))open.disabled=false;}},"text-button");article.append(open,output);}
        block.append(article);
      }parent.append(block);
    }
    function facts(parent,rows){const list=node("dl","knowledge-facts");for(const [label,content] of rows){text("dt","",label,list);text("dd","",value(content)||"Not established",list);}parent.append(list);}
    function listSection(parent,title,items,empty="None recorded."){const section=node("section","knowledge-block");text("h3","",title,section);const values=array(items);if(!values.length)text("p","knowledge-muted",empty,section);else{const list=node("ul","knowledge-list");for(const item of values)text("li","",typeof item==="string"?item:show(item),list);section.append(list);}parent.append(section);return section;}
    function transcript(parent,submission,focusId){const section=node("section","knowledge-transcript");text("h3","",`Interview transcript · ${array(submission.turns).length} messages`,section);for(const turn of array(submission.turns)){const entry=node("article",`knowledge-turn${turn.id===focusId?" is-source":""}`);entry.id=`knowledge-turn-${turn.id}`;entry.tabIndex=-1;text("h4","",`${turn.role==="user"?"Participant":"AI interviewer"} · ${turn.id}`,entry);text("p","",turn.text||"",entry);section.append(entry);}if(!array(submission.turns).length)text("p","knowledge-muted","No transcript was supplied.",section);parent.append(section);if(focusId){const context=adminContext();(globalThis.requestAnimationFrame||((fn)=>Promise.resolve().then(fn)))(()=>{if(!sameAdmin(context))return;const target=$("knowledge-turn-"+focusId);target?.scrollIntoView?.({block:"center"});target?.focus?.({preventScroll:true});});}}
    function sourceEvidence(parent,sid,revision,refs){
      const submission=sourceSubmission(sid,revision),block=node("section","knowledge-block knowledge-source-evidence");text("h3","","Interview evidence",block);
      const ids=[...new Set(array(refs).filter(x=>typeof x==="string"))];if(!ids.length)text("p","knowledge-muted","No interview answer references were supplied for this item.",block);
      for(const id of ids){const turn=array(submission?.turns).find(t=>t.id===id&&t.role==="user"&&!t.document_event);
        if(id==="context"){text("p","knowledge-muted","Supplied interview context",block);text("p","",submission?.context?.background||submission?.context?.objective||"Context details are unavailable.",block);continue;}
        text("blockquote","knowledge-quote",turn?.text||"Answer "+id+" is unavailable in this revision.",block);
        if(turn){const open=button("Open answer "+id,()=>openDetail("interview",sid,revision,{turn_id:id,returnTo:descriptor(selected)}),"text-button");open.dataset.sourceKey=sid+":"+revision+":"+id;block.append(open);}
      }parent.append(block);
    }
    function stepDetails(parent,step,sid,revision){const section=node("section","knowledge-block knowledge-step");text("h3","",`${step.id?step.id+" · ":""}${step.title||"Process step"}`,section);if(step.description)text("p","",step.description,section);facts(section,[["Owner / role",step.actor],["System / tool",step.system],["Input",step.input],["Output",step.output],["Completion",step.completion_criteria],["Next handoff",step.handoff]]);sourceEvidence(section,sid,revision,step.evidence_turns);parent.append(section);}
    function technical(parent,item){const detail=node("details","knowledge-technical"),summary=node("summary","","Technical record");detail.append(summary,node("pre","knowledge-evidence",show(item)));parent.append(detail);}
    function submissionDetails(parent,item){const draft=item.draft||item.workflow||{},context=item.context||{};
      if(item.capture_provenance?.method==="document_simulation"){const provenance=node("section","knowledge-block knowledge-provenance");provenance.setAttribute("role","note");text("h3","","Document-derived simulation — not an employee statement",provenance);text("p","knowledge-status","The interview was simulated from written documentation. No employee confirmation or process owner approval has been recorded.",provenance);listSection(provenance,"Source documents",array(item.capture_provenance.source_documents).map(doc=>value(doc?.filename)).filter(Boolean),"Source filenames were not supplied.");parent.append(provenance);}
      const summary=node("section","knowledge-block");text("h3","","Business summary",summary);text("p","",draft.overview||context.objective||"A business summary has not been supplied.",summary);facts(summary,[["Process owner",context.process_owner],["Interview objective",context.objective],["Supplied context",context.background],["Revision",item.revision],["Participant (self-reported)",item.participant],["Verified submitter",item.submitter],["Team / department",[item.team,item.department].filter(Boolean).join(" · ")],["Scope",item.scope],["Processing",tidy(item.job_status)],["Trigger",draft.trigger]]);if(item.draft_stale)text("p","knowledge-status","This draft predates newer interview answers. Review the current transcript before relying on it.",summary);parent.append(summary);listSection(parent,"Inputs",draft.inputs);listSection(parent,"Outputs",draft.outputs);text("h3","","Detailed process steps",parent);for(const step of array(draft.steps))stepDetails(parent,step,item.submission_id,item.revision);if(!array(draft.steps).length)text("p","knowledge-muted","No process steps were supplied.",parent);listSection(parent,"Controls and checks",draft.controls);listSection(parent,"Exceptions and recovery",draft.exceptions);listSection(parent,"Open questions",draft.open_questions,"No open questions recorded. This is a submitted account and still requires owner review.");listSection(parent,"Validation notes",draft.validation_notes);
      for(const variation of array(draft.variations)){const block=node("section","knowledge-block");text("h3","","Process variation",block);facts(block,[["Applies to",variation.applies_to],["Difference",variation.difference],["Reason",variation.reason],["Cost / effort",variation.cost],["Charging / billing",variation.charging],["Standardization",variation.removability],["Process boundary",variation.boundary_reason]]);sourceEvidence(block,item.submission_id,item.revision,variation.evidence_turns);parent.append(block);}
      for(const lifecycle of array(draft.lifecycle_items)){const block=node("section","knowledge-block");text("h3","",lifecycle.item||"Work item lifecycle",block);listSection(block,"Stages",lifecycle.stages);listSection(block,"Locations",lifecycle.locations);listSection(block,"Handoffs",lifecycle.handoffs);sourceEvidence(block,item.submission_id,item.revision,lifecycle.evidence_turns);parent.append(block);}
      for(const memo of array(draft.memo_summary)){const block=node("section","knowledge-block");text("h3","",`Memo · ${tidy(memo.key)}`,block);text("p","knowledge-muted",tidy(memo.status),block);text("p","",memo.answer||"No answer supplied.",block);sourceEvidence(block,item.submission_id,item.revision,memo.evidence_turns);parent.append(block);}
      documentSources(parent,item);transcript(parent,item);technical(parent,item);}
    function relationshipCard(parent,item){
      return card(parent,(item.source_label||label(item.source))+" → "+(item.target_label||label(item.target)),tidy(item.status)+" · "+tidy(item.type),()=>openDetail(item.proposal_id?"proposal":"relationship",item.proposal_id||item.id));
    }
    function reviewHistory(parent,item){const block=node("article","knowledge-history-entry");facts(block,[["Action",tidy(item.action)],["Reviewer",item.reviewer],["Recorded",item.created_at||item.reviewed_at],["Reason",item.reason],["Revision",item.review_version||item.revision]]);if(item.side)facts(block,[["Side statement",item.side]]);if(item.value!==undefined)addInfo(block,"Recorded value",item.value);parent.append(block);}
    function proposalReview(parent,item){
      if(!["proposed","awaiting_clarification","confirmed","disputed"].includes(item.status))return;
      const form=node("form","knowledge-review"),labelEl=node("label","knowledge-field"),reason=node("textarea");labelEl.append(node("span","","Reason for this decision"),reason);reason.maxLength=2000;reason.required=true;form.append(labelEl);
      const sideWrap=node("label","knowledge-field"),side=node("select");sideWrap.append(node("span","","Side statement recorded by administrator (optional)"),side);
      for(const [v,l] of [["","Administrator review only"],["sender","Sending-side statement"],["receiver","Receiving-side statement"]]){const opt=node("option","",l);opt.value=v;side.append(opt);}side.value="";form.append(sideWrap);
      text("p","knowledge-muted","Record who supplied any side statement and what they confirmed in the reason. This does not verify the identity or claim that both sides confirmed.",form);
      const status=text("p","knowledge-status","",form);status.setAttribute("role","status");status.hidden=true;const actions=node("div","knowledge-actions");let sending=false;
      for(const [action,title] of [["confirm","Confirm"],["clarify","Request clarification"],["dispute","Dispute"],["reject","Reject"]])actions.append(button(title,async()=>{
        if(sending)return;if(!reason.value.trim()){reason.focus();error(status,"Enter a reason before recording a decision.");return;}sending=true;for(const x of actions.children)x.disabled=true;const operation=adminContext();
        try{await adminRequest("/api/knowledge/admin/review",{proposal_id:item.id,action,reason:reason.value.trim(),expected_revision:item.review_version,...(side.value?{side:side.value}:{})});if(sameAdmin(operation))await load({focus:"heading"});}
        catch(e){if(sameAdmin(operation)){error(status,e.message||"Could not record the decision. Refresh to review the latest version.");sending=false;for(const x of actions.children)x.disabled=false;}}
      }));form.append(actions);parent.append(form);
    }
    function entityChooser(parent,group,onChoose){
      const region=node("section","knowledge-picker"),heading=text("h4","knowledge-picker-heading","Eligible entities",region),controls=node("div","knowledge-picker-search"),query=field(controls,"Find an entity","member_query","Search all eligible records"),body=node("div");controls.append(button("Search",()=>read(0),"knowledge-tab"));region.append(controls,body);parent.append(region);heading.tabIndex=-1;let sequence=0;
      query.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();void read(0);}});
      async function read(offset,focus=false){const token=++sequence,context=adminContext(),term=query.value.trim();body.replaceChildren(node("p","knowledge-muted","Loading eligible entities…"));
        try{const result=await adminRequest("/api/knowledge/admin/browse",{section:"entities",filters:{...filters,type:group.type,query:term,latest_only:true,exclude_group_id:group.id},offset,limit:PAGE_SIZE});if(token!==sequence||!sameAdmin(context))return;pageInfo(result);body.replaceChildren();
          if(!result.items.length)text("p","knowledge-muted","No matching entities. Try another search or refine the company filters.",body);
          for(const item of result.items){const row=node("div","knowledge-picker-row");text("span","",item.label+" · revision "+item.revision,row);if(item.canonical_id||item.latest===false)text("span","knowledge-muted",item.canonical_id?"Already grouped":"Earlier revision",row);else row.append(button("Choose",()=>onChoose(item),"text-button"));body.append(row);}pager(body,result,next=>read(next,true),"eligible entities");if(focus)heading.focus({preventScroll:true});
        }catch(e){if(token===sequence&&sameAdmin(context)){body.replaceChildren();retryState(body,e.message||"Entity choices are unavailable.",()=>read(offset));}}
      }void read(0);return region;
    }
    function groupDetails(parent,group){
      facts(parent,[["Entity type",tidy(group.type)],["Review state",tidy(group.status)],["Members",group.member_count],["Aliases",group.alias_count],["History records",group.history_count],["Review version",group.review_version]]);
      if(group.status==="stale"||group.needs_review)text("p","knowledge-status","Needs review · "+(group.stale_reason||"Source evidence changed. Review the members before revalidating."),parent);
      text("p","knowledge-muted","Groups are explicit administrator judgments. Original evidence is retained; membership and aliases can be changed with a recorded reason.",parent);
      const form=node("form","knowledge-review knowledge-block"),reason=field(form,"Reason for change","reason","Why is this grouping appropriate?"),wrap=node("label","knowledge-field"),action=node("select");wrap.append(node("span","","Change"),action);
      for(const [v,l] of [["add_member","Add entity"],["remove_member","Remove entity"],["add_alias","Add alias"],["remove_alias","Remove alias"],...((group.status==="stale"||group.needs_review)?[["revalidate","Revalidate current grouping"]]:[])]){const opt=node("option","",l);opt.value=v;action.append(opt);}action.value="add_member";form.append(wrap);
      const chosen=text("p","knowledge-muted","",form),alias=field(form,"New alias","alias","Alias label"),chooserHost=node("div"),status=text("p","knowledge-status","",form);status.setAttribute("role","status");status.hidden=true;form.append(chooserHost);const send=node("button","button secondary small","Record change");send.type="submit";form.append(send);let selectedValue="",selectedLabel="",sending=false;chosen.tabIndex=-1;chosen.setAttribute("role","status");
      const choose=(value,label,kind)=>{selectedValue=value;selectedLabel=label;action.value=kind;update(false);chosen.focus?.({preventScroll:true});};
      function update(clear=true){if(clear){selectedValue="";selectedLabel="";}chooserHost.replaceChildren();alias.parentElement.hidden=action.value!=="add_alias";
        chosen.textContent=action.value==="revalidate"?"Review the current members and evidence before revalidating.":selectedValue?"Selected: "+selectedLabel:action.value==="remove_member"?"Choose Remove beside a member below.":action.value==="remove_alias"?"Choose Remove beside an alias below.":action.value==="add_alias"?"Enter the new alias.":"Choose an eligible entity.";
        if(action.value==="add_member")entityChooser(chooserHost,group,item=>choose(item.id,item.label,"add_member"));
      }
      action.addEventListener("change",()=>update());update();
      form.addEventListener("submit",async event=>{event.preventDefault();if(sending)return;const v=(action.value==="revalidate"?"reviewed":action.value==="add_alias"?alias.value:selectedValue).trim();if(!v||!reason.value.trim()){error(status,"Choose a value and give a review reason.");return;}sending=true;send.disabled=true;const operation=adminContext();
        try{await adminRequest("/api/knowledge/admin/canonical-update",{canonical_id:group.id,action:action.value,value:v,reason:reason.value.trim(),expected_revision:group.review_version});if(sameAdmin(operation))await load({focus:"heading"});}
        catch(e){if(sameAdmin(operation)){sending=false;send.disabled=false;error(status,e.message||"Could not record the change. Refresh to review the latest version.");}}
      });parent.append(form);
      void historyPanel(parent,"Members and source evidence","group_members",group.id,(out,item)=>{const c=card(out,item.label,tidy(item.type)+" · revision "+item.revision+(item.latest===false?" · earlier revision":""),()=>openDetail("entity",item.id));c.append(button("Remove member",()=>choose(item.id,item.label,"remove_member"),"text-button"));});
      void historyPanel(parent,"Reviewed aliases","group_aliases",group.id,(out,item)=>{const row=node("div","knowledge-picker-row");text("span","",item.alias,row);row.append(button("Remove alias",()=>choose(item.alias,item.alias,"remove_alias"),"text-button"));out.append(row);});
      void historyPanel(parent,"Group review history","group",group.id,reviewHistory);technical(parent,group);
    }
    function details(parent,item,kind){
      const current=descriptor(selected);parent.append(button(kind==="interview"?"← Back to detail":"← Back",()=>{selected=kind==="interview"?current.returnTo:null;focusAfterLoad=kind==="interview"?{sourceKey:current.id+":"+current.revision+":"+current.turn_id}:"heading";return load();},"text-button"));
      const title=kind==="proposal"?submissionLabel(item.source_submission_id,item.source_revision)+" → "+submissionLabel(item.destination_submission_id,item.destination_revision):kind==="downstream"?"Potential downstream of "+item.label:item.context?.process_name||item.label||submissionLabel(item.submission_id,item.revision)||"Details";
      const heading=text("h2","knowledge-detail-title",title,parent);heading.tabIndex=-1;
      if(kind==="interview"){transcript(parent,item,current.turn_id);return;}
      if(kind==="submission"){submissionDetails(parent,item);return;}
      if(kind==="group"){groupDetails(parent,item);return;}
      if(kind==="downstream"){text("p","knowledge-muted","Reachability follows reported sequence and confirmed handoffs only. It is not a measured impact; missing links and process containment may leave step-to-process effects unknown.",parent);void historyPanel(parent,"Affected connections","downstream",item.id,relationshipCard,"No reported sequence or confirmed handoffs are reachable from this entity.");return;}
      if(kind==="entity"){
        if(["step","decision"].includes(item.type))stepDetails(parent,item.data||{title:item.label},item.submission_id,item.revision);
        else{facts(parent,[["Entity type",tidy(item.type)],["Label",item.label],["Source process",submissionLabel(item.submission_id,item.revision)],["Revision",item.revision]]);sourceEvidence(parent,item.submission_id,item.revision,item.data?.evidence_turns);}
        parent.append(button("Show affected connections",()=>openDetail("downstream",item.id),"text-button"));void historyPanel(parent,"Immediate upstream and downstream relationships","entity_neighbors",item.id,relationshipCard);technical(parent,item);return;
      }
      if(kind==="relationship"){facts(parent,[["From",item.source_label||label(item.source)],["To",item.target_label||label(item.target)],["Relationship",tidy(item.type)],["Evidence state",tidy(item.status)],["Condition",item.evidence?.label],["Source process",submissionLabel(item.submission_id,item.revision)],["Revision",item.revision]]);sourceEvidence(parent,item.submission_id,item.revision,evidenceRefs(item));technical(parent,item);return;}
      if(kind==="proposal"){
        for(const [key,title] of [["relationship_type","Relationship type"],["status","Review state"],["source_submission_id","Sending submission"],["source_revision","Sending revision"],["destination_submission_id","Receiving submission"],["destination_revision","Receiving revision"],["scope","Scope"],["condition","Condition"],["explanation","Explanation"],["inference","Inferred interpretation"],["missing_evidence","Missing evidence"],["contradictions","Contradictions"]])addInfo(parent,title,item[key]);
        proposalEvidence(parent,item.evidence);void historyPanel(parent,"Connection review history","proposal",item.id,reviewHistory);proposalReview(parent,item);technical(parent,item);
      }
    }
    function entityControls(parent){
      const controls=node("div","knowledge-entity-controls"),query=field(controls,"Find entities","entity_query","Search all records"),typeWrap=node("label","knowledge-field"),type=node("select");query.value=entityQuery;typeWrap.append(node("span","","Entity type"),type);
      for(const key of ["","process_version","step","decision","role","system","business_object","variant"]){const opt=node("option","",key?tidy(key):"All types");opt.value=key;type.append(opt);}type.value=entityType;controls.append(typeWrap);
      const earlierWrap=node("label","knowledge-choice"),earlier=node("input");earlier.type="checkbox";earlier.checked=includeEarlier;earlierWrap.append(earlier,node("span","","Include earlier revisions"));controls.append(earlierWrap);
      const apply=()=>{entityQuery=query.value.trim();entityType=type.value;includeEarlier=earlier.checked;offsets.entities=0;focusAfterLoad="heading";return load();};controls.append(button("Search entities",apply,"knowledge-tab"));query.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();void apply();}});earlier.addEventListener("change",apply);parent.append(controls);
      const toggle=button(groupDraft.open?"Cancel grouping":"Create reviewed group",()=>{groupDraft.open=!groupDraft.open;if(!groupDraft.open){groupSelection.clear();groupDraft={open:false,label:"",reason:""};}render();focusControl("group-toggle");},"knowledge-tab");toggle.dataset.focusKey="group-toggle";toggle.setAttribute("aria-expanded",String(groupDraft.open));parent.append(toggle);
    }
    function groupCreate(parent){
      const form=node("form","knowledge-review knowledge-block");const heading=text("h3","","Create reviewed group",form);heading.tabIndex=-1;heading.dataset.focusKey="group-heading";const title=field(form,"Canonical label","label","Name for this group"),reason=field(form,"Review reason","reason","Why these records describe the same thing");title.value=groupDraft.label;reason.value=groupDraft.reason;title.addEventListener("input",()=>groupDraft.label=title.value);reason.addEventListener("input",()=>groupDraft.reason=reason.value);
      text("p","knowledge-muted","Select 2–100 current, ungrouped entities of one type. Selections are kept as you page; source records and evidence stay separate.",form);
      const selectedBox=node("div","knowledge-selected-entities");text("p","knowledge-muted",groupSelection.size+" selected",selectedBox);for(const item of groupSelection.values()){const chip=button(item.label+" ×",()=>{groupSelection.delete(item.id);render();focusControl("group-heading");},"knowledge-filter-chip");chip.setAttribute("aria-label","Remove selected entity "+item.label);selectedBox.append(chip);}form.append(selectedBox);
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
      async function read(offset,focus=false){const token=++sequence,context=adminContext();processPickerOffset=offset;body.replaceChildren(node("p","knowledge-muted","Loading process choices…"));
        try{const result=await adminRequest("/api/knowledge/admin/browse",{section:"submissions",filters:{...filters,latest_only:true},offset,limit:PAGE_SIZE});if(token!==sequence||!sameAdmin(context))return;pageInfo(result);body.replaceChildren();if(!result.items.length)text("p","knowledge-muted","No processes match these filters.",body);
          for(const item of result.items){const row=node("div","knowledge-picker-row");text("span","",(item.context?.process_name||"Untitled process")+" · revision "+item.revision,row);row.append(button("Show process",()=>{graphProcess=item.submission_id;graphProcessName=item.context?.process_name||"Selected process";processPickerOpen=false;focusAfterLoad="heading";return load();},"text-button"));body.append(row);}pager(body,result,next=>read(next,true),"process choices");if(focus)heading.focus({preventScroll:true});
        }catch(e){if(token===sequence&&sameAdmin(context)){body.replaceChildren();retryState(body,e.message||"Process choices are unavailable.",()=>read(offset,true));}}
      }void read(processPickerOffset);
    }
    function renderGraph(root,data){
      text("h2","knowledge-detail-title","Company process graph",root).tabIndex=-1;const intro=node("div","knowledge-graph-intro");text("span","knowledge-muted","Reported steps and confirmed links.",intro);intro.append(button("Connection review →",()=>navigate("connections"),"text-button"));root.append(intro);
      const choices=node("div","knowledge-actions knowledge-graph-levels");for(const [level,title] of [["overview","Process overview"],["steps","Process steps"],["all","All entities"]]){const b=button(title,()=>{graphLevel=level;focusAfterLoad="heading";return load();},"knowledge-tab");b.setAttribute("aria-pressed",String(graphLevel===level));choices.append(b);}root.append(choices);
      const scope=node("div","knowledge-filter-bar");text("span","knowledge-muted",graphProcess?graphProcessName:"All matching processes",scope);scope.append(button(processPickerOpen?"Close process choices":"Choose process",()=>{processPickerOpen=!processPickerOpen;render();focusControl("process-toggle");},"knowledge-tab"));scope.children[1].dataset.focusKey="process-toggle";if(graphProcess)scope.append(button("Show all processes",()=>{graphProcess=null;graphProcessName="";return load({focus:"heading"});},"text-button"));root.append(scope);
      if(data.too_large){text("p","knowledge-status",data.message||"This complete view exceeds 80 entities or 150 connections. Choose a process or refine filters.",root);if(data.counts)text("p","knowledge-muted",data.counts.nodes+" entities · "+data.counts.connections+" connections. No partial graph is displayed.",root);}
      if(processPickerOpen||data.too_large)processPicker(root);
      if(data.too_large)return;
      const display=array(data.entities),valid=links(data),rawConnections=array(data.edges).length+array(data.proposals).length,ids=new Set(display.map(e=>e.id));
      if(display.length>80||rawConnections>150){text("p","knowledge-status","This complete view exceeds the graph limit. Choose a process or refine filters.",root);if(!processPickerOpen)processPicker(root);return;}
      if(valid.length!==rawConnections||valid.some(e=>!ids.has(e.source)||!ids.has(e.target))){retryState(root,"The graph contains an unresolved endpoint. Refresh or refine filters.",()=>load());return;}
      if(!display.length){text("p","knowledge-muted","No graph entities match these filters.",root);return;}
      const canvas=node("div","knowledge-canvas");canvas.setAttribute("aria-label","Reported and confirmed knowledge graph");root.append(canvas);const controls=node("div","knowledge-actions");root.append(controls);
      const drawn=graphLevel==="steps"?valid.filter(e=>e.type!=="contains"):valid,connected=new Set(drawn.flatMap(e=>[e.source,e.target])),canvasEntities=graphLevel==="steps"?display.filter(e=>e.type!=="process_version"||connected.has(e.id)):display;
      const shortIds=new Map(canvasEntities.map((e,i)=>[e.id,"N"+(i+1)])),originalIds=new Map(canvasEntities.map((e,i)=>["N"+(i+1),e.id]));
      const component=(e,key,relation)=>value(e.data?.[key])||display.find(x=>array(data.edges).some(edge=>edge.source===e.id&&edge.target===x.id&&edge.type===relation&&edge.status==="reported"))?.label||"";
      if(!canvasEntities.length)text("p","knowledge-muted","No connected process steps match these filters.",canvas);
      else if(window.CollectorWorkflow){const context=adminContext();try{graph=window.CollectorWorkflow.create(canvas,{onSelectStep:s=>{if(sameAdmin(context)){const id=originalIds.get(s.id);if(id)return openDetail("entity",id);}}});const currentGraph=graph;controls.append(button("−",()=>currentGraph.zoom(-.15)),button("+",()=>currentGraph.zoom(.15)),button("Fit all",()=>currentGraph.fit()));Promise.resolve(graph.update({title:"Reported and confirmed company knowledge",steps:canvasEntities.map(e=>({id:shortIds.get(e.id),title:e.label||"Untitled",type:e.type==="decision"?"decision":"activity",actor:e.type==="process_version"?"Process":component(e,"actor","performed_by"),system:e.type==="process_version"?"Revision "+e.revision:component(e,"system","uses_system"),evidence_turns:array(e.data?.evidence_turns)})),connections:drawn.map(e=>({from:shortIds.get(e.source),to:shortIds.get(e.target),label:graphLevel==="steps"&&e.type==="before"?value(e.evidence?.label):tidy(e.status)+" · "+tidy(e.type),evidence_turns:evidenceRefs(e)}))})).catch(()=>{if(sameAdmin(context))canvas.replaceChildren(node("p","knowledge-muted","Graph layout unavailable; inspect entity and connection lists."));});}catch{canvas.replaceChildren(node("p","knowledge-muted","Graph layout unavailable; inspect entity and connection lists."));}}
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
      if(section==="overview"){
        text("h2","knowledge-detail-title","A view of reported work",root).tabIndex=-1;const stats=node("div","knowledge-stats"),counts=snapshot.counts||{};
        for(const [key,label] of [["submissions","Submissions"],["awaiting_review","Awaiting review"],["confirmed_connections","Confirmed connections"],["processing_failures","Processing failures"]]){const s=node("div","knowledge-stat");s.append(node("strong","",counts[key]||0),node("span","",label));stats.append(s);}root.append(stats);text("p","knowledge-muted","Coverage reflects submitted accounts, not operational measurements. Missing and conflicting information remains open for review.",root);if(snapshot.analysis_limitations)text("p","knowledge-muted",snapshot.analysis_limitations,root);return;
      }
      const titles={submissions:"Employee submissions & revisions",connections:"Connection review",entities:"Reported entities",groups:"Reviewed canonical groups",jobs:"Background processing"};text("h2","knowledge-detail-title",titles[section]||"Saved records",root).tabIndex=-1;
      if(section==="entities"){entityControls(root);if(groupDraft.open)groupCreate(root);text("p","knowledge-muted","Each entity retains its submission and revision. Open a record for its full evidence.",root);}
      if(section==="groups")text("p","knowledge-muted","Reviewed groups and aliases retain the separate source records and a complete history.",root);
      if(section==="jobs")text("p","knowledge-muted","Saved submissions remain available if processing is pending or fails.",root);
      for(const item of items){
        if(section==="submissions")card(root,item.context?.process_name||"Untitled process","Revision "+item.revision+" · "+(item.team||item.department||"Team unknown")+" · "+(tidy(item.job_status)||"Processing pending"),()=>openDetail("submission",item.submission_id,item.revision));
        if(section==="connections")card(root,(tidy(item.relationship_type)||"Connection")+" · "+tidy(item.status),(item.scope||"Scope not established")+" · "+(item.explanation||"Open to inspect evidence and uncertainty."),()=>openDetail("proposal",item.id));
        if(section==="groups")card(root,item.label+" · "+tidy(item.type),tidy(item.status)+" · "+item.member_count+" members · "+item.alias_count+" aliases"+(item.stale_reason?" · "+item.stale_reason:""),()=>openDetail("group",item.id));
        if(section==="entities"){
          const c=card(root,item.label||"Untitled",tidy(item.type)+" · revision "+item.revision+(item.latest===false?" · earlier revision":"")+(item.canonical_id?" · reviewed group":""),()=>openDetail("entity",item.id));
          if(groupDraft.open){const row=node("label","knowledge-choice"),check=node("input"),selectionType=groupSelection.values().next().value?.type;check.type="checkbox";check.value=item.id;check.checked=groupSelection.has(item.id);check.disabled=Boolean(item.canonical_id)||item.latest===false||Boolean(selectionType&&selectionType!==item.type)||(!check.checked&&groupSelection.size>=100);check.setAttribute("aria-label","Select "+item.label);check.dataset.focusKey="entity:"+item.id;row.append(check,node("span","",check.disabled?"Unavailable for this group":"Select for group"));check.addEventListener("change",()=>{if(check.disabled)return;if(check.checked)groupSelection.set(item.id,{id:item.id,label:item.label,type:item.type});else groupSelection.delete(item.id);render();focusControl("entity:"+item.id);});c.append(row);}
        }
        if(section==="jobs"){const c=card(root,(tidy(item.status)||"Pending")+" · revision "+item.revision,(item.process_name||"Process")+" · "+(item.error||"No error reported")+" · "+(item.attempts||0)+" attempts");if(["failed","pending"].includes(item.status)){const status=text("p","knowledge-status","",c);status.hidden=true;status.setAttribute("role","status");const retry=button("Retry",async()=>{retry.disabled=true;const context=adminContext();try{await adminRequest("/api/knowledge/admin/retry",{job_id:item.id});if(sameAdmin(context))await load({focus:"heading"});}catch(e){if(sameAdmin(context)){retry.disabled=false;error(status,e.message||"Could not retry this job.");}}});c.append(retry);}}
      }
      if(!items.length)text("p","knowledge-muted","No records match these filters.",root);pager(root,snapshot,next=>{offsets[section]=next;return load({focus:"heading"});},section);
    }
    async function load(settings={}){
      const token=++epoch;loading=true;loadError="";snapshot=null;if(settings.focus)focusAfterLoad=settings.focus;render();const context=adminContext(),choice=descriptor(selected),currentSection=section;
      const active=()=>token===epoch&&admin.open&&context.session===sessionEpoch&&context.generation===adminGeneration&&context.example===adminExample;
      try{
        if(adminExample)await ensureExample();if(!active())return;let result;
        if(choice){const kind=["interview","submission"].includes(choice.kind)?"submission":choice.kind==="downstream"?"entity":choice.kind;result=await adminRequest("/api/knowledge/admin/detail",{kind,id:choice.id,...(choice.revision!==undefined?{revision:choice.revision}:{})});if(!result?.item||typeof result.item!=="object"||Array.isArray(result.item))throw Error("The saved detail could not be verified.");}
        else if(currentSection==="graph"){result=await adminRequest("/api/knowledge/admin/graph",{filters:{...filters},level:graphLevel,...(graphProcess?{submission_id:graphProcess}:{})});if(!Array.isArray(result?.entities)||!Array.isArray(result?.edges)||!Array.isArray(result?.proposals)||typeof result?.too_large!=="boolean")throw Error("The graph response could not be verified.");}
        else{result=await adminRequest("/api/knowledge/admin/browse",{section:currentSection,filters:listFilters(),offset:offsets[currentSection]||0,limit:PAGE_SIZE});const page=pageInfo(result);if(active()&&page.total>0&&page.offset>=page.total){offsets[currentSection]=Math.floor((page.total-1)/page.limit)*page.limit;return load(settings);}}
        if(!active())return;snapshot=result;loading=false;render();const focus=focusAfterLoad;focusAfterLoad=null;
        if(focus&&!(choice?.kind==="interview"&&choice.turn_id)){const target=typeof focus==="object"?([...(admin.querySelectorAll?.("[data-source-key]")||[])].find(el=>el.dataset.sourceKey===focus.sourceKey)||admin.querySelector?.(".knowledge-detail-title")):focus==="filter"?admin.querySelector?.("[data-filter-toggle]"):admin.querySelector?.(".knowledge-detail-title");target?.focus?.({preventScroll:true});}
      }catch(e){if(!active())return;loading=false;loadError=e.message||"Administrative data is unavailable.";render();}
    }
    function openAdmin(){
      if(adminButton.hidden)return;adminGeneration++;const nextExample=isExample();if(nextExample!==adminExample){filters={state:"all",team:"",system:"",scope:"",freshness:"all"};filtersOpen=false;section="overview";graphLevel=nextExample?"steps":"overview";for(const key of Object.keys(offsets))delete offsets[key];graphProcess=null;graphProcessName="";processPickerOpen=false;processPickerOffset=0;entityQuery="";entityType="";includeEarlier=false;groupSelection.clear();groupDraft={open:false,label:"",reason:""};}
      adminExample=nextExample;restoreSettingsOnClose=true;selected=null;snapshot=null;close($("interview-settings"));if(!admin.open)admin.showModal();startAdminResize();void load({focus:"heading"});
    }
    menu.addEventListener("click",()=>{$("session-menu").hidden=true;$("session-menu-toggle").setAttribute("aria-expanded","false");openSubmit();});review.addEventListener("click",openSubmit);adminButton.addEventListener("click",openAdmin);
    admin.addEventListener("close",()=>{if(admin.open)return;stopAdminResize();epoch++;adminGeneration++;if(graph){graph.destroy();graph=null;}snapshot=null;selected=null;groupSelection.clear();groupDraft={open:false,label:"",reason:""};const settings=$("interview-settings");if(restoreSettingsOnClose){if(!settings.open)settings.showModal();adminButton.focus({preventScroll:true});}restoreSettingsOnClose=true;});
    return {get processId(){return processId;},get hasPending(){return Boolean(pendingAttempt);},configure,reset,restore,exportReceipt,openSubmit,activateExample};
  }
  window.CollectorKnowledge={create};
})();
