"use strict";
// What the page (the real web/app.js) hands to the Submit process dialog and keeps for it in a saved
// interview: the state of the file workspace, a draft request in flight, the interview's own identity
// and the details filed with the last submission. Stub DOM and a scripted network boundary; no
// provider, browser or audio is used. (Harness after tests/test_submit_capture_state.cjs.)
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const concurrentSource=fs.readFileSync(path.join(__dirname,"..","web","concurrent-interview.js"),"utf8");
const flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const ok=value=>({ok:true,status:200,json:async()=>value});
const plain=value=>JSON.parse(JSON.stringify(value));
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

let ids=0;   // one sequence for every page of this file, as two tabs never draw the same random identifier
function setup(){
  const nodes=new Map(),timers=new Map(),calls=[],notices=[],tabs=[];let serial=0,route=url=>{throw Error("Unexpected request "+url);};
  function node(id){
    if(!nodes.has(id)){
      nodes.set(id,{id,hidden:false,checked:false,disabled:false,value:"",textContent:"",className:"",open:false,dataset:{},children:[],style:{},listeners:{},
        classList:{toggle(){},add(){},remove(){},contains(){return false;}},
        setAttribute(){},removeAttribute(){},getAttribute(){return null;},focus(){},close(){this.open=false;for(const fn of this.listeners.close||[])fn({target:this});},showModal(){this.open=true;},remove(){},scrollIntoView(){},setSelectionRange(){},
        contains(){return false;},get firstElementChild(){return node(id+"-first");},
        querySelector(){return node(id+"-child");},querySelectorAll(){return[];},
        append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},
        addEventListener(type,fn,options){const list=(this.listeners[type]??=[]);list.push(options?.once?event=>{list.splice(list.indexOf(fn),1);fn(event);}:fn);}});
    }
    return nodes.get(id);
  }
  const setTimeout=(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout=id=>timers.delete(id);
  const window={speechSynthesis:{cancel(){}},SpeechSynthesisUtterance:class{},addEventListener(){},removeEventListener(){},setTimeout,clearTimeout,__notices:notices,__tabs:tabs};
  const context={window,console,Blob,Date,JSON,TextEncoder,AbortController,DOMException,confirm:()=>true,setTimeout,clearTimeout,
    requestAnimationFrame:()=>++serial,cancelAnimationFrame(){},
    crypto:{randomUUID:()=>`aaaaaaaa-aaaa-4aaa-8aaa-${String(++ids).padStart(12,"0")}`},
    document:{body:node("body"),activeElement:null,getElementById:node,querySelectorAll:()=>[],querySelector:()=>null,createElement:tag=>node("created-"+tag+"-"+(++serial)),addEventListener(){}},
    fetch:async(url,options)=>{calls.push({url,body:typeof options?.body==="string"?JSON.parse(options.body):null});return route(url,options);}};
  const seam=`
    renderTranscript=()=>{};renderDraft=()=>{};renderWorkingMap=()=>{};renderCoverage=()=>{};scrollConversation=()=>{};
    updateConversationControls=()=>{};updateDocumentIntakeUI=()=>{};stopSpeaking=()=>{};tab=(name,focus)=>{window.__tabs.push([name,Boolean(focus)]);};
    selectConversationView=view=>{conversationUI.view=view;};
    notice=(message,error)=>window.__notices.push({message,error:Boolean(error)});
    window.__page={state,conversationUI,sessionObject,importSession,clearState,generateDraft,updateControls,request,
      captureState:submissionCaptureState,
      fileWorkspace:typeof submissionFileWorkspace==="function"?submissionFileWorkspace:null,
      draftState:typeof submissionDraftState==="function"?submissionDraftState:null,
      setKnowledge:value=>{knowledgeUI=value;},setDocuments:value=>{documentController=value;}};
  })();`;
  const source=appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam);
  assert.notEqual(source,appSource,"Install the test seam only at application initialization");
  vm.createContext(context);vm.runInContext(concurrentSource,context,{filename:"concurrent-interview.js"});vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__page;
  // Stands in for the knowledge controller (web/knowledge-ui.js); records what the page asks of it.
  const knowledge={processId:null,hasPending:false,restored:[],changes:0,attribution:null,exportReceipt:()=>null,exportAttribution(){return this.attribution;},reset(){},
    restore(...values){this.restored.push(plain(values));},captureChanged(){this.changes++;}};
  t.setKnowledge(knowledge);
  t.state.config={api_configured:true,csrf_token:"synthetic"};
  t.state.started=true;t.state.context={process_name:"Invoice intake",process_owner:"AP manager",objective:"Document the work",background:""};
  t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A supplier email starts a case."}];
  const reopen=async file=>{const raw=JSON.stringify(file);t.state.dirty=false;await t.importSession({size:raw.length,text:async()=>raw});await flush();};
  return {t,node,context,calls,notices,tabs,timers,knowledge,reopen,route:fn=>{route=fn;}};
}

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
// r1-submit-1: only a file the current file workspace still holds can be filed as a saved excerpt.
await check("the page reports the removed files of the current file workspace and whether it can be read",async()=>{
  const h=setup();
  assert.equal(typeof h.t.fileWorkspace,"function","app.js must report the file workspace to the Submit dialog");
  assert.deepEqual(plain(h.t.fileWorkspace()),{unavailable:false,removed:[]},"No file workspace yet");
  h.t.setDocuments({scopeUnavailable:false,removed:[{id:"doc_gone",name:"returns-log.csv",kind:"csv",size:120}],exportState:()=>({scope:"s",documents:[]})});
  assert.deepEqual(plain(h.t.fileWorkspace()),{unavailable:false,removed:[{id:"doc_gone",name:"returns-log.csv"}]});
  h.t.setDocuments({scopeUnavailable:true,removed:[],exportState:()=>({scope:"s",documents:[]})});
  assert.equal(h.t.fileWorkspace().unavailable,true,"A workspace that cannot be opened on this computer is reported as such");
  assert.match(appSource,/CollectorKnowledge\.create\(\{[^}]*fileWorkspace:submissionFileWorkspace/,"The dialog receives it");
});

// gap3-submit-in-flight-5: Create draft / Update draft in flight.
const DRAFT=()=>({draft:{title:"Invoice intake",overview:"AP registers and checks supplier invoices.",trigger:"A supplier email",inputs:[],outputs:[],
  steps:[{id:"S1",title:"Register the invoice",description:"",actor:"AP analyst",system:"AP register",type:"activity",evidence_turns:["t002"]}],connections:[],
  exceptions:[],controls:[],open_questions:[],validation_notes:[],memo_summary:[]}});
await check("while a draft request runs the page keeps Submit waiting and says the draft will be included",async()=>{
  const h=setup(),reply=deferred();
  h.route(url=>url==="/api/draft"?reply.promise:ok({}));
  assert.equal(h.t.captureState().waiting,"");assert.deepEqual(plain(h.t.draftState()),{pending:false,arrivals:0});
  const running=h.t.generateDraft();await flush();
  assert.equal(h.calls.filter(call=>call.url==="/api/draft").length,1);
  const during=h.t.captureState();
  assert.equal(during.waiting,"A draft is being created.");
  assert.equal(during.action,"Submit when it is ready so the draft is included.");
  assert.equal(h.t.draftState().pending,true);
  const before=h.knowledge.changes;
  reply.resolve(ok(DRAFT()));await running;await flush();
  assert.equal(h.t.state.draft?.overview,"AP registers and checks supplier invoices.");
  assert.deepEqual(plain(h.t.draftState()),{pending:false,arrivals:1});
  assert.notEqual(h.t.captureState().waiting,"A draft is being created.");
  assert.ok(h.knowledge.changes>before,"The open dialog is told that the draft request ended");
  assert.deepEqual(plain(h.tabs),[["review",true]],"With no dialog open the page goes to Review as before");
  assert.ok(h.notices.some(item=>/^Your draft is ready\./.test(item.message)));
  // Voice comes first when both apply: the action shown must belong to the reason shown.
  h.t.conversationUI.live={active:true};
  assert.equal(h.t.captureState().action,"Close this window and choose Stop talking, then submit.");h.t.conversationUI.live=null;
});

await check("a failed or abandoned draft request releases Submit again",async()=>{
  const h=setup();
  h.route(url=>url==="/api/draft"?{ok:false,status:503,json:async()=>({error:"The provider is unavailable."})}:ok({}));
  await h.t.generateDraft();await flush();
  assert.deepEqual(plain(h.t.draftState()),{pending:false,arrivals:0});assert.notEqual(h.t.captureState().waiting,"A draft is being created.");
  assert.deepEqual(plain(h.tabs),[]);
  const reply=deferred();h.route(url=>url==="/api/draft"?reply.promise:ok({}));
  const running=h.t.generateDraft();await flush();assert.equal(h.t.draftState().pending,true);
  h.t.clearState();
  assert.equal(h.t.draftState().pending,false,"A new interview is not held by the old interview's draft request");
  reply.resolve(ok(DRAFT()));await running;await flush();
  assert.equal(h.t.draftState().arrivals,0);assert.equal(h.t.state.draft,null);
});

await check("a draft that arrives under the open Submit dialog opens Review when the dialog closes, not behind it",async()=>{
  const h=setup(),reply=deferred(),dialog=h.node("knowledge-submit");
  h.route(url=>url==="/api/draft"?reply.promise:ok({}));
  const running=h.t.generateDraft();await flush();
  dialog.showModal();                              // Submit process, opened from More options while the draft is being created
  reply.resolve(ok(DRAFT()));await running;await flush();
  assert.equal(h.t.draftState().arrivals,1);
  assert.deepEqual(plain(h.tabs),[],"The page must not switch to Review behind the modal dialog");
  assert.equal(h.notices.some(item=>/^Your draft is ready\./.test(item.message)),false,"The announcement is not spent behind the backdrop");
  dialog.close();
  assert.deepEqual(plain(h.tabs),[["review",true]]);assert.ok(h.notices.some(item=>/^Your draft is ready\./.test(item.message)));
  dialog.showModal();dialog.close();
  assert.equal(h.tabs.length,1,"Only the close that follows the draft opens Review");
  // A dialog closed because another interview replaced this one opens nothing.
  const other=setup(),second=deferred(),otherDialog=other.node("knowledge-submit");
  other.route(url=>url==="/api/draft"?second.promise:ok({}));
  const again=other.t.generateDraft();await flush();otherDialog.showModal();
  second.resolve(ok(DRAFT()));await again;await flush();
  other.t.clearState();otherDialog.close();
  assert.equal(other.tabs.some(([name])=>name==="review"),false);
  assert.equal(other.notices.some(item=>/^Your draft is ready\./.test(item.message)),false);
});

// live-draft-knowledge-2: the details filed with the last submission travel with the saved interview.
await check("a saved interview carries the details of its last submission and hands them back when reopened",async()=>{
  const h=setup(),filed={participant:"Dana (fictional)",team:"Treasury",department:"",scope:"Fund A"};
  assert.equal(plain(h.t.sessionObject()).knowledge_attribution,null,"Nothing was submitted yet");
  h.knowledge.processId="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";h.knowledge.attribution=filed;
  const saved=plain(h.t.sessionObject());
  assert.deepEqual(saved.knowledge_attribution,filed);assert.equal(saved.knowledge_process_id,h.knowledge.processId);
  await h.reopen(saved);
  assert.deepEqual(h.knowledge.restored.at(-1),[h.knowledge.processId,null,filed],"The knowledge controller gets the details beside the process ID and the status access");
  // A file saved before this existed reopens without them.
  const {knowledge_attribution,...older}=saved;
  await h.reopen(older);
  assert.deepEqual(h.knowledge.restored.at(-1),[h.knowledge.processId,null,null]);
});

// gap3-two-tabs-4: the interview's own identity.
await check("an interview has one identity, kept in every saved copy and replaced only by another interview",async()=>{
  const h=setup();
  const first=plain(h.t.sessionObject()).interview_id;
  assert.match(first,UUID,"Every saved or submitted interview carries an identity");
  assert.equal(plain(h.t.sessionObject()).interview_id,first,"It does not change from one save to the next");
  h.t.state.turns.push({id:"t003",role:"assistant",text:"And then?"},{id:"t004",role:"user",text:"The analyst registers it."});
  const saved=plain(h.t.sessionObject());assert.equal(saved.interview_id,first,"More answers do not make it another interview");
  // A copy opened in another tab, or reopened later, is the same interview.
  const other=setup();await other.reopen(saved);
  assert.equal(plain(other.t.sessionObject()).interview_id,first);
  // A new interview is another interview.
  h.t.clearState();
  const second=plain(h.t.sessionObject()).interview_id;
  assert.match(second,UUID);assert.notEqual(second,first);
  // A file saved before interviews had an identity, or with an unusable one, gets one when it is next saved.
  for(const legacy of [(({interview_id,...rest})=>rest)(saved),{...saved,interview_id:"not-an-id"},{...saved,interview_id:7}]){
    const old=setup();await old.reopen(legacy);
    const given=plain(old.t.sessionObject()).interview_id;
    assert.match(given,UUID);assert.notEqual(given,first);assert.equal(plain(old.t.sessionObject()).interview_id,given);
  }
});

await check("a browser that cannot make an identifier still saves, with no identity",async()=>{
  const h=setup();h.context.crypto=undefined;
  assert.equal(plain(h.t.sessionObject()).interview_id,null,"Save copy and Submit must not fail for want of an identity");
  h.context.crypto={randomUUID:()=>"not-a-uuid"};
  assert.equal(plain(h.t.sessionObject()).interview_id,null);
});

// knowledge-frontend-3 and gap3-two-tabs-4: what the page passes on from a refused submission.
await check("a refused submission reaches the dialog with the server's not-saved signal and conflict details",async()=>{
  const h=setup(),refuse=(status,body)=>h.route(()=>({ok:false,status,json:async()=>body}));
  const failure=async()=>{try{await h.t.request("/api/knowledge/submit",{turns:[]});}catch(error){return error;}throw Error("The request should have failed");};
  refuse(409,{error:"This interview was already submitted as revision 2.",code:"interview_already_submitted",process_id:"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",revision:2,not_saved:true});
  let error=await failure();
  assert.equal(error.status,409);assert.equal(error.code,"interview_already_submitted");assert.equal(error.process_id,"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
  assert.equal(error.revision,2);assert.equal(error.not_saved,true);assert.equal(error.message,"This interview was already submitted as revision 2.");
  refuse(400,{error:"Invalid capture state.",not_saved:true});
  error=await failure();assert.equal(error.status,400);assert.equal(error.not_saved,true);assert.equal(error.code,undefined);
  for(const body of [{error:"Submission key was already used for different content."},{error:"x",not_saved:"true"},{error:"x",not_saved:1},{error:"x",process_id:"p",revision:3}]){
    refuse(400,body);error=await failure();
    assert.equal(error.not_saved,undefined,"Only an explicit true releases an attempt: "+JSON.stringify(body));assert.equal(error.process_id,undefined);
  }
});

await check("the explicit saved file keeps an uncertain submission private from ordinary page snapshots",async()=>{
  const h=setup(),id=plain(h.t.sessionObject()).interview_id;
  const record={version:1,payload:{submission_key:"00000000-0000-4000-8000-000000000444",interview_id:id,context:{process_name:"Earlier version"},turns:[]}};
  h.knowledge.exportAttempt=()=>record;h.knowledge.hasPending=true;
  assert.equal(Object.hasOwn(h.t.sessionObject(),"knowledge_pending_attempt"),false);
  const saved=plain(h.t.sessionObject({includePresentation:true}));assert.deepEqual(saved.knowledge_pending_attempt,record);
  await h.reopen(saved);
  assert.deepEqual(h.knowledge.restored.at(-1).slice(3),[record,id]);
});

for(const version of ["0.25.1","0.26.1","0.29.0","0.30.0"]){
  await check("open a release "+version+" interview and retain its reported content",async()=>{
    const h=setup(),legacy=JSON.parse(fs.readFileSync(path.join(__dirname,"fixtures","compat","session-"+version+".json"),"utf8"));
    await h.reopen(legacy);
    const saved=plain(h.t.sessionObject());
    assert.match(h.notices.at(-1).message,/Interview opened.*provisional/);
    assert.deepEqual(saved.turns.map(({id,role,text})=>({id,role,text})),legacy.turns);
    assert.equal(saved.context.process_name,legacy.context.process_name);assert.equal(saved.summary,legacy.summary);
    for(const finding of legacy.memo_findings){const retained=saved.memo_findings.find(item=>item.key===finding.key);assert.equal(retained?.status,finding.status);}
    assert.equal(saved.draft,legacy.draft);assert.equal(saved.knowledge_status,null);
  });
}

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
