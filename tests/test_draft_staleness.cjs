"use strict";
// A review draft is out of date only when participant evidence changed after it was
// created: a sent or spoken answer, a participant caption, or the set of active files.
// Titles, interviewer turns and file notices move state.version (the in-flight request
// guard) but must never flag the draft. Real app.js logic behind a stub DOM; no
// provider, network, browser or audio is used.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const titleBinding=appSource.match(/\$\("process-name"\)\.addEventListener\("input",\(\)=>\{[\s\S]*?\n    \}\);/)?.[0]||"";
assert.ok(titleBinding,"The Process name input handler must be present in app.js");
const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const STALE_REPORT=/interview has changed since this draft/i;
// The Markdown report words its warning by what the app saw: newer answers, a change of files, or a saved flag.
const STALE_MARKDOWN=/\*\*(The interview has changed since this draft was created|The files used in this interview have changed since this draft was created|This draft was saved as out of date)[.:]/;

function setup(){
  const nodes=new Map(),notices=[],confirms=[],prompt={answer:true};let serial=0,networkCalls=0;
  function node(id){
    if(!nodes.has(id)){
      const listeners={};
      nodes.set(id,{id,hidden:false,checked:false,disabled:false,value:"",textContent:"",className:"",open:false,dataset:{},children:[],style:{},
        classList:{toggle(){},add(){},remove(){},contains(){return false;}},
        setAttribute(){},removeAttribute(){},getAttribute(){return null;},focus(){},close(){},showModal(){},remove(){},scrollIntoView(){},setSelectionRange(){},
        contains(){return false;},get firstElementChild(){return node(id+"-first");},
        querySelector(){return node(id+"-child");},querySelectorAll(){return[];},
        append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},
        addEventListener(type,fn){(listeners[type]??=[]).push(fn);},
        dispatch(type){for(const fn of listeners[type]||[])fn({target:this,preventDefault(){}});}});
    }
    return nodes.get(id);
  }
  const window={speechSynthesis:{cancel(){}},SpeechSynthesisUtterance:class{},addEventListener(){},removeEventListener(){},__notices:notices};
  const context={window,console,Blob,Date,JSON,TextEncoder,AbortController,DOMException,confirm:message=>{confirms.push(String(message));return prompt.answer;},
    document:{body:node("body"),activeElement:null,getElementById:node,querySelectorAll:()=>[],querySelector:()=>null,
      createElement:tag=>node("created-"+tag+"-"+(++serial)),addEventListener(){}},
    setTimeout:()=>++serial,clearTimeout(){},requestAnimationFrame:()=>++serial,cancelAnimationFrame(){},
    fetch:()=>{networkCalls++;throw Error("Draft staleness checks must stay local.");}};
  const seam=`
    renderTranscript=()=>{};renderDraft=()=>{};renderWorkingMap=()=>{};renderCoverage=()=>{};scrollConversation=()=>{};
    updateConversationControls=()=>{};updateDocumentIntakeUI=()=>{};scheduleWorkflow=()=>{};stopSpeaking=()=>{};tab=()=>{};
    selectConversationView=view=>{conversationUI.view=view;};
    notice=(message,error)=>window.__notices.push({message,error:Boolean(error)});
    ${titleBinding}
    window.__staleness={state,conversationUI,updateControls,sessionObject,transcriptObject,markdown,renderReport,generateDraft,sendAnswer,
      applyInterview,appendDocumentMessage,receiveLiveCaption,startLiveConversation,onDocumentEvent,importSession,
      confirmDraftCurrent:typeof confirmDraftCurrent==="function"?confirmDraftCurrent:null,
      draftStaleReason:typeof draftStaleReason==="function"?draftStaleReason:()=>"",
      setRequest:fn=>{request=fn;},setDocuments:value=>{documentController=value;}};
  })();`;
  const source=appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam);
  assert.notEqual(source,appSource,"Install the test seam only at application initialization");
  vm.createContext(context);vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__staleness;
  t.state.config={api_configured:true,csrf_token:"synthetic"};
  t.state.started=true;t.state.context={process_name:"Invoice intake",process_owner:"AP manager",objective:"Document the work",background:""};
  node("process-name").value="Invoice intake";
  t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A supplier email starts a case."}];
  const draftReply=()=>({draft:{title:"Invoice intake",overview:"Reported account.",steps:[{id:"S1",title:"Receive and register invoice",evidence_turns:["t002"]}],connections:[],memo_summary:[]},document_evidence:[]});
  // The banner, the saved file, the transcript export, the Markdown report and the on-screen report must agree.
  const stale=()=>{
    t.updateControls();t.renderReport();
    const flags={banner:!node("draft-stale").hidden,saved:t.sessionObject().draft_stale,transcript:t.transcriptObject().interview_notes.draft_questions_may_be_stale,
      markdown:STALE_MARKDOWN.test(t.markdown()),report:node("report-content").children.some(child=>child.className==="report-warning"&&(STALE_REPORT.test(child.textContent)||/saved as out of date/i.test(child.textContent)))};
    const values=new Set(Object.values(flags));
    assert.equal(values.size,1,"Every stale-draft indicator must agree: "+JSON.stringify(flags));
    return flags.saved;
  };
  const createDraft=async()=>{t.setRequest(async pathName=>{assert.equal(pathName,"/api/draft");return draftReply();});await t.generateDraft();assert.ok(t.state.draft,"The draft must be created");assert.equal(stale(),false,"A new draft is current");};
  const typeTitle=value=>{node("process-name").value=value;node("process-name").dispatch("input");};
  return {t,node,window,notices,confirms,stale,createDraft,typeTitle,draftReply,get networkCalls(){return networkCalls;},
    get answer(){return prompt.answer;},set answer(value){prompt.answer=value;}};
}

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
await check("a Process name keystroke, even when undone, leaves a reviewed draft current",async()=>{
  const h=setup();await h.createDraft();
  h.t.state.draft.steps[0].title="REVIEWER CORRECTED TITLE";h.t.state.draftEdited=true;
  const version=h.t.state.version;
  h.typeTitle("Invoice intakes");h.typeTitle("Invoice intake");
  assert.notEqual(h.t.state.version,version,"The title handler may still move the in-flight request guard");
  assert.equal(h.stale(),false,"Typing in Process name must not flag the draft");
  const saved=h.t.sessionObject();
  assert.equal(saved.draft_stale,false);assert.equal(saved.draft_edited,true);
  assert.equal(saved.draft.steps[0].title,"REVIEWER CORRECTED TITLE");
  h.typeTitle("Supplier invoice intake");
  assert.equal(h.stale(),false,"A real title change is presentation, not participant evidence");
  assert.equal(h.t.sessionObject().context.process_name,"Supplier invoice intake");
});

await check("interviewer turns and file notices do not flag the draft",async()=>{
  const h=setup();await h.createDraft();
  const version=h.t.state.version;
  h.t.applyInterview({question:"Let me check that I have everything.",preserve_capture:true});
  assert.equal(h.stale(),false,"A wrap-up acknowledgement is not a participant answer");
  h.t.applyInterview({question:"Is anything missing?",coverage:[],memo_findings:[],summary:"",focus:"",parking_lot:[]});
  assert.equal(h.stale(),false,"A new interviewer question is not a participant answer");
  assert.ok(h.t.appendDocumentMessage("Checklist.pdf has been updated in Files.",{id:"doc_checklist"}),"The file notice must be added");
  assert.equal(h.stale(),false,"A file-update notice is not participant evidence");
  h.t.receiveLiveCaption({role:"assistant",id:"a1",text:"Thanks, that is clear.",final:true});
  assert.equal(h.stale(),false,"A spoken interviewer caption is not participant evidence");
  assert.equal(h.t.state.turns.length,6);assert.ok(h.t.state.version>=version+4,"These turns still move the in-flight request guard");
});

await check("a sent answer flags the draft everywhere",async()=>{
  const h=setup();await h.createDraft();
  h.t.setRequest(async()=>({question:"What happens next?",coverage:[],memo_findings:[],summary:"",focus:"",parking_lot:[]}));
  h.node("answer-text").value="The analyst also checks for duplicates.";
  await h.t.sendAnswer({preventDefault(){}});
  assert.equal(h.t.state.turns.at(-2).text,"The analyst also checks for duplicates.");
  assert.equal(h.stale(),true,"A new participant answer postdates the draft");
  h.typeTitle("Invoice intake and duplicate check");
  assert.equal(h.stale(),true,"A later title edit cannot clear a real change");
  await h.createDraft();
});

await check("an answer whose next question fails to load still flags the draft",async()=>{
  const h=setup();await h.createDraft();
  h.t.setRequest(async()=>{throw Error("Offline interviewer");});
  h.node("answer-text").value="Rejected invoices go back to the buyer.";
  await h.t.sendAnswer({preventDefault(){}});
  assert.equal(h.t.state.turns.at(-1).role,"user");assert.equal(h.stale(),true);
});

await check("a participant caption flags the draft, and so does its later correction",async()=>{
  const h=setup();await h.createDraft();
  h.t.receiveLiveCaption({role:"user",id:"u1",text:"We also",final:false});
  assert.equal(h.stale(),true,"A participant caption is new evidence");
  await h.createDraft();
  h.t.receiveLiveCaption({role:"user",id:"u1",text:"We also notify Treasury.",final:true});
  assert.equal(h.stale(),true,"A changed participant caption is new evidence");
  await h.createDraft();
  h.t.receiveLiveCaption({role:"user",id:"u1",text:"We also notify Treasury.",final:true});
  assert.equal(h.stale(),false,"Repeating an unchanged caption adds nothing");
});

await check("a reviewed voice answer flags the draft",async()=>{
  const h=setup();let voice=null;
  await h.createDraft();
  h.t.state.config.agent_team={enabled:true};
  h.window.CollectorControlledVoice=class{constructor(options){voice=options;}async start(){this.active=true;}stop(){this.active=false;}};
  await h.t.startLiveConversation();
  assert.ok(voice,"Reviewed voice must be selected");
  voice.onAnswer("The controller approves anything above the limit.");
  assert.equal(h.t.state.turns.at(-1).role,"user");
  h.t.conversationUI.live.active=false;
  assert.equal(h.stale(),true);
});

await check("changing the active files flags the draft and restoring them clears it",async()=>{
  const h=setup();
  const file=(id,extra={})=>({id,name:id+".pdf",status:"ready",analysis:{intent_version:1,sources:[{source_id:id+"_p1"}]},...extra});
  let documents=[file("doc_a")];
  h.t.setDocuments({exportState:()=>({scope:"scope_synthetic",documents:JSON.parse(JSON.stringify(documents))})});
  await h.createDraft();
  documents=[file("doc_a"),file("doc_b")];
  assert.equal(h.stale(),true,"A file added after the draft is new evidence");
  documents=[file("doc_a"),file("doc_b",{archived:true})];
  assert.equal(h.stale(),false,"Removing that file again restores the evidence the draft was built from");
  documents=[file("doc_a",{analysis:{intent_version:2,sources:[]}})];
  assert.equal(h.stale(),true,"A file reviewed again for a new purpose is new evidence");
  documents=[file("doc_a",{status:"ready",chunk_count:12})];
  assert.equal(h.stale(),false,"File status details alone are not a change of evidence");
  // The banner follows the file list itself, without waiting for an unrelated control update.
  documents=[file("doc_a",{archived:true})];
  h.t.onDocumentEvent({type:"changed",state:{documents}});
  assert.equal(h.node("draft-stale").hidden,false,"Removing a file the draft was built from shows the warning at once");
  documents=[file("doc_a")];
  h.t.onDocumentEvent({type:"changed",state:{documents}});
  assert.equal(h.node("draft-stale").hidden,true);
  assert.equal(h.stale(),false);
});

await check("each stale-draft notice says what the app saw: newer answers or a change of files",async()=>{
  const file=id=>({id,name:id+".pdf",status:"ready",analysis:{intent_version:1,sources:[{source_id:id+"_p1"}]}});
  const h=setup();let documents=[file("doc_a")];
  h.t.setDocuments({exportState:()=>({scope:"scope_synthetic",documents:JSON.parse(JSON.stringify(documents))})});
  await h.createDraft();
  assert.equal(h.t.draftStaleReason(),"");
  documents=[file("doc_a"),file("doc_b")];
  assert.equal(h.stale(),true);assert.equal(h.t.draftStaleReason(),"files");
  assert.equal(h.node("draft-stale").textContent,"This draft doesn’t include the latest change to your files.","No answer was added, so none is claimed");
  assert.match(h.t.markdown(),/\*\*The files used in this interview have changed since this draft was created\. Reconcile the change before approval\.\*\*/);
  assert.doesNotMatch(h.t.markdown(),/Reconcile the new answers/);
  h.t.setRequest(async()=>{throw Error("Offline interviewer");});
  h.node("answer-text").value="One more exception applies.";await h.t.sendAnswer({preventDefault(){}});
  assert.equal(h.stale(),true);assert.equal(h.t.draftStaleReason(),"answers","A newer answer is the stronger reason");
  assert.equal(h.node("draft-stale").textContent,"This draft doesn’t include your latest answers.");
  assert.match(h.t.markdown(),/\*\*The interview has changed since this draft was created\. Reconcile the new answers before approval\.\*\*/);
});

await check("typing does not copy the file list to check the draft",async()=>{
  // updateControls runs on every keystroke; the draft's file signature must read the records in place.
  const h=setup();let copies=0;
  const documents=[{id:"doc_a",name:"a.pdf",status:"ready",analysis:{intent_version:1,review_notes:"x".repeat(1000)}}];
  h.t.setDocuments({peekState:()=>({scope:"scope_synthetic",documents}),exportState:()=>{copies++;return {scope:"scope_synthetic",documents:JSON.parse(JSON.stringify(documents))};}});
  await h.createDraft();
  const before=copies;
  for(let i=0;i<5;i++)h.t.updateControls();
  assert.equal(copies,before,"Control updates must not deep-copy every file record");
  assert.equal(h.node("draft-stale").hidden,true);
  documents.push({id:"doc_b",name:"b.pdf",status:"ready",analysis:{intent_version:1}});
  h.t.updateControls();
  assert.equal(h.node("draft-stale").hidden,false,"The signature still follows the live file list");
  assert.equal(copies,before);
  assert.deepEqual(JSON.parse(JSON.stringify(documents.map(file=>file.id))),["doc_a","doc_b"],"Reading the records must not change them");
});

await check("state.version still guards a draft request that is in flight",async()=>{
  const h=setup(),reply=deferred();
  h.t.setRequest(()=>reply.promise);
  const pending=h.t.generateDraft();await flush();
  assert.equal(h.t.state.busy,true);
  assert.ok(h.t.appendDocumentMessage("Checklist.pdf has been updated in Files.",{id:"doc_checklist"}));
  reply.resolve(h.draftReply());await pending;
  assert.equal(h.t.state.draft,null,"A draft built from an earlier conversation must not be shown as current");
  assert.equal(h.t.state.busy,false);
});

// Measured on 2026-11-23 in two live interviews out of two: the server returned a complete draft after
// 114 s and 169 s and the page discarded it with "The interview changed while the draft was being
// prepared", because the workflow map it draws in the background had been redrawn or checked meanwhile.
const workingMap=(...titles)=>({title:"Invoice intake",steps:titles.map((title,index)=>({id:"S"+(index+1),title,evidence_turns:["t002"]})),connections:[],open_questions:[]});
await check("a workflow map redrawn while the draft is written does not discard the draft",async()=>{
  const h=setup(),reply=deferred();let sent=null;
  h.t.conversationUI.workflow=workingMap("Receive invoice");h.t.conversationUI.workflowCheckPending=true;
  h.t.setRequest((pathName,body)=>{sent=body;return reply.promise;});
  const pending=h.t.generateDraft();await flush();
  assert.equal(sent.map_review_revision,"pending");
  h.t.conversationUI.workflow=workingMap("Receive invoice","Register invoice");h.t.conversationUI.workflowCheckPending=false;
  reply.resolve(h.draftReply());await pending;
  assert.ok(h.t.state.draft,"The draft the participant waited for is shown");
  assert.equal(h.stale(),false,"It holds every answer, so nothing marks it out of date");
  assert.ok(!h.notices.some(row=>/interview changed while the draft/.test(row.message)));
  assert.ok(h.notices.some(row=>/workflow map was updated while the draft was written; choose Update draft/.test(row.message)),"The newer map is mentioned once, with what to do about it");
});

await check("a map check that finishes without changing the map is not mentioned at all",async()=>{
  const h=setup(),reply=deferred();
  h.t.conversationUI.workflow=workingMap("Receive invoice");h.t.conversationUI.workflowCheckPending=true;
  h.t.setRequest(()=>reply.promise);
  const pending=h.t.generateDraft();await flush();
  h.t.conversationUI.workflowCheckPending=false;
  reply.resolve(h.draftReply());await pending;
  assert.ok(h.t.state.draft);
  assert.ok(!h.notices.some(row=>/workflow map was updated|interview changed/.test(row.message)));
});

await check("the Create draft button itself says that the draft is being made",async()=>{
  const h=setup(),reply=deferred();
  h.t.updateControls();assert.equal(h.node("generate-draft").textContent,"Create draft");
  h.t.setRequest(()=>reply.promise);
  const pending=h.t.generateDraft();await flush();
  assert.match(h.node("generate-draft").textContent,/^Creating draft · \d+:\d\d$/,"The Workspace panel has no other status line");
  h.t.updateControls();
  assert.match(h.node("generate-draft").textContent,/^Creating draft · /,"A control refresh keeps it");
  reply.resolve(h.draftReply());await pending;
  h.t.updateControls();assert.equal(h.node("generate-draft").textContent,"Open draft");
});

// Reopening a saved interview (gap-uncommitted-diff-2). The committed 0.29.0 build flagged every
// reopened draft and wrote draft_stale:true on the next save.
const savedInterview=extra=>({schema_version:1,context:{process_name:"Invoice intake",objective:"Document the work"},
  turns:[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A supplier email starts a case."}],
  draft:{title:"Invoice intake",steps:[{id:"S1",title:"REVIEWER CORRECTED TITLE",evidence_turns:["t002"]}],connections:[],memo_summary:[]},
  workflow:{title:"Invoice intake",steps:[{id:"S1",title:"Receive and register invoice",evidence_turns:["t002"]}],connections:[]},draft_edited:true,...extra});
const reopen=async(h,saved)=>{const raw=JSON.stringify(saved);h.t.state.dirty=false;await h.t.importSession({size:raw.length,text:async()=>raw});assert.ok(h.t.state.draft,"The saved draft must reopen");};

await check("a file saved with a current draft reopens current and stays current when saved again",async()=>{
  const h=setup();await reopen(h,savedInterview({draft_stale:false}));
  assert.equal(h.stale(),false,"Reopening must not flag a draft that was saved as current");
  const again=JSON.parse(JSON.stringify(h.t.sessionObject()));
  assert.equal(again.draft_stale,false,"Save copy after reopening must not write draft_stale:true");
  assert.equal(again.draft_edited,true);assert.equal(again.draft.steps[0].title,"REVIEWER CORRECTED TITLE");
  await reopen(h,again);
  assert.equal(h.stale(),false,"A second reopen keeps the draft current");
  h.typeTitle("Invoice intake (reviewed)");
  assert.equal(h.stale(),false,"A title edit after reopening does not flag the draft");
  h.t.setRequest(async()=>{throw Error("Offline interviewer");});
  h.node("answer-text").value="One more exception applies.";await h.t.sendAnswer({preventDefault(){}});
  assert.equal(h.stale(),true,"A new answer after reopening does");
});

await check("a file saved as out of date, or with no flag, reopens flagged",async()=>{
  for(const extra of [{draft_stale:true},{},{draft_stale:"false"},{draft_stale:0}]){
    const h=setup();await reopen(h,savedInterview(extra));
    assert.equal(h.stale(),true,"Only a literal draft_stale:false reopens as current: "+JSON.stringify(extra));
    assert.equal(h.t.sessionObject().draft_stale,true);
  }
});

await check("a draft the saved file flagged can be confirmed as current, and only by the reviewer",async()=>{
  const h=setup();await reopen(h,savedInterview({draft_stale:true}));
  assert.equal(h.stale(),true);assert.equal(h.t.draftStaleReason(),"saved","This is the reason the Submit dialog words its notice by");
  assert.match(h.node("draft-stale").textContent,/saved as out of date/i,"The app did not see an answer change, so it must not claim one");
  assert.match(h.t.markdown(),/\*\*This draft was saved as out of date: the interview may have changed since it was created\. Update it or confirm that it is current before approval\.\*\*/);
  assert.doesNotMatch(h.t.markdown(),/interview has changed|new answers/,"The Markdown report of a reopened file with no new answer must not report one");
  const warning=h.node("report-content").children.find(child=>child.className==="report-warning");
  assert.match(warning.textContent,/saved as out of date\. Update the draft or mark it as current/i,"The report names both remedies");
  assert.equal(h.node("draft-confirm-current").hidden,false,"The confirmation is offered beside the warning");
  assert.equal(h.node("draft-confirm-current").disabled,false);
  h.confirms.length=0;h.answer=false;h.t.state.dirty=false;h.t.confirmDraftCurrent();
  assert.equal(h.confirms.length,1);assert.match(h.confirms[0],/every answer and file/i);assert.match(h.confirms[0],/Update draft/);
  assert.equal(h.stale(),true,"Declining leaves the draft flagged");assert.equal(h.t.state.dirty,false);
  h.answer=true;h.t.confirmDraftCurrent();
  assert.equal(h.stale(),false,"Confirming clears every stale-draft indicator");
  assert.equal(h.node("draft-confirm-current").hidden,true);assert.equal(h.t.state.dirty,true,"The confirmation is an unsaved change");
  assert.equal(h.t.state.draft.steps[0].title,"REVIEWER CORRECTED TITLE","Confirming keeps the reviewer's edits");
  const again=JSON.parse(JSON.stringify(h.t.sessionObject()));assert.equal(again.draft_stale,false);assert.equal(again.draft_edited,true);
  await reopen(h,again);assert.equal(h.stale(),false,"The confirmed state survives Save copy and reopening");
  h.confirms.length=0;h.t.confirmDraftCurrent();
  assert.equal(h.confirms.length,0,"Nothing is asked when the draft is current");
});

await check("a draft the app saw go out of date says so and can also be confirmed",async()=>{
  const h=setup();await h.createDraft();
  h.t.updateControls();assert.equal(h.node("draft-confirm-current").hidden,true,"A current draft offers nothing to confirm");
  h.t.setRequest(async()=>{throw Error("Offline interviewer");});
  h.node("answer-text").value="No, nothing else.";await h.t.sendAnswer({preventDefault(){}});
  assert.equal(h.stale(),true);
  assert.match(h.node("draft-stale").textContent,/doesn’t include your latest answers/);
  assert.equal(h.node("draft-confirm-current").hidden,false);
  h.t.state.busy=true;h.t.updateControls();
  assert.equal(h.node("draft-confirm-current").disabled,true,"Not while a request is in flight");
  h.confirms.length=0;h.t.confirmDraftCurrent();assert.equal(h.confirms.length,0);assert.equal(h.t.sessionObject().draft_stale,true);
  h.t.state.busy=false;h.t.confirmDraftCurrent();
  assert.equal(h.stale(),false);
  h.node("answer-text").value="Actually, one more step.";await h.t.sendAnswer({preventDefault(){}});
  assert.equal(h.stale(),true,"A later answer flags the draft again");
});

await check("no draft means nothing is flagged",async()=>{
  const h=setup();
  h.t.updateControls();
  assert.equal(h.node("draft-stale").hidden,true);assert.equal(h.t.sessionObject().draft_stale,false);
  assert.equal(h.t.transcriptObject().interview_notes.draft_questions_may_be_stale,false);
  assert.equal(h.networkCalls,0);
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
