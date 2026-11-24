"use strict";
// gap3-submit-in-flight-1: what the page reports to the Submit dialog while notes and the
// working map are catching up with the latest answer, and the capture marker stored with
// every saved or submitted interview. Real app.js and concurrent-interview.js behind a stub
// DOM, with the network boundary scripted; no provider, browser or audio is used.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const concurrentSource=fs.readFileSync(path.join(__dirname,"..","web","concurrent-interview.js"),"utf8");
const flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const ok=value=>({ok:true,status:200,json:async()=>value});
const down=()=>({ok:false,status:503,json:async()=>({error:"The provider is unavailable."})});
const plain=value=>JSON.parse(JSON.stringify(value));
const question=text=>({question:text,summary:"Captured so far.",focus:"",parking_lot:[],memo_findings:[],coverage:[]});
const map=title=>({workflow:{title,steps:[],connections:[],open_questions:[]}});
const WAITING_NOTES="Notes and the working map are still updating for your latest answer.";

function setup(){
  const nodes=new Map(),timers=new Map(),calls=[],notices=[];let serial=0,route=url=>{throw Error("Unexpected request "+url);};
  function node(id){
    if(!nodes.has(id)){
      nodes.set(id,{id,hidden:false,checked:false,disabled:false,value:"",textContent:"",className:"",open:false,dataset:{},children:[],style:{},
        classList:{toggle(){},add(){},remove(){},contains(){return false;}},
        setAttribute(){},removeAttribute(){},getAttribute(){return null;},focus(){},close(){},showModal(){},remove(){},scrollIntoView(){},setSelectionRange(){},
        contains(){return false;},get firstElementChild(){return node(id+"-first");},
        querySelector(){return node(id+"-child");},querySelectorAll(){return[];},
        append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},addEventListener(){}});
    }
    return nodes.get(id);
  }
  const setTimeout=(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout=id=>timers.delete(id);
  const window={speechSynthesis:{cancel(){}},SpeechSynthesisUtterance:class{},addEventListener(){},removeEventListener(){},setTimeout,clearTimeout,__notices:notices};
  const context={window,console,Blob,Date,JSON,TextEncoder,AbortController,DOMException,confirm:()=>true,setTimeout,clearTimeout,
    requestAnimationFrame:()=>++serial,cancelAnimationFrame(){},crypto:{randomUUID:()=>String(++serial).padStart(32,"0")},
    document:{body:node("body"),activeElement:null,getElementById:node,querySelectorAll:()=>[],querySelector:()=>null,createElement:tag=>node("created-"+tag+"-"+(++serial)),addEventListener(){}},
    fetch:async(url,options)=>{calls.push({url,body:typeof options?.body==="string"?JSON.parse(options.body):null});return route(url,options);}};
  const seam=`
    renderTranscript=()=>{};renderDraft=()=>{};renderWorkingMap=()=>{};renderCoverage=()=>{};scrollConversation=()=>{};
    updateConversationControls=()=>{};updateDocumentIntakeUI=()=>{};stopSpeaking=()=>{};tab=()=>{};
    selectConversationView=view=>{conversationUI.view=view;};
    notice=(message,error)=>window.__notices.push({message,error:Boolean(error)});
    window.__capture={state,conversationUI,renderAnalysisThrough,scheduleWorkflow,sendAnswer,sessionObject,importSession,refreshWorkflow,updateControls,
      captureState:typeof submissionCaptureState==="function"?submissionCaptureState:()=>({waiting:"",missing:[],capture:undefined}),
      setKnowledge:value=>{knowledgeUI=value;},setIntake:value=>{documentIntake=value;},setReview:value=>{pendingCompletionReview=value;},
      concurrent:()=>concurrentInterview};
  })();`;
  const source=appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam);
  assert.notEqual(source,appSource,"Install the test seam only at application initialization");
  vm.createContext(context);vm.runInContext(concurrentSource,context,{filename:"concurrent-interview.js"});vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__capture;let changes=0,notified=null;const seen=[];
  // Stands in for the open Submit dialog: it re-reads the capture state whenever the page says it changed.
  t.setKnowledge({processId:null,hasPending:false,exportReceipt:()=>null,reset(){},restore(){},
    captureChanged(){changes++;const state=t.captureState();notified=state.waiting;seen.push({waiting:state.waiting,missing:[...state.missing]});}});
  t.state.config={api_configured:true,csrf_token:"synthetic"};
  t.state.started=true;t.state.context={process_name:"Invoice intake",process_owner:"AP manager",objective:"Document the work",background:""};
  t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
  const answer=text=>{node("answer-text").value=text;return t.sendAnswer({preventDefault(){}});};
  const runTimers=async ms=>{const due=[...timers.entries()].filter(([,timer])=>ms===undefined||timer.ms===ms);for(const [id,timer] of due){timers.delete(id);timer.fn();}await flush();};
  const gate=()=>{const state=t.captureState();return {waiting:state.waiting,action:state.action,missing:plain(state.missing),capture:state.capture===undefined?undefined:plain(state.capture)};};
  return {t,node,calls,notices,timers,answer,runTimers,gate,seen,route:fn=>{route=fn;},get changes(){return changes;},get notified(){return notified;}};
}

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
await check("a typed answer keeps Submit waiting until its notes and its map have landed",async()=>{
  const h=setup(),interview=deferred(),workflow=deferred();
  h.route(url=>url==="/api/interview"?interview.promise:url==="/api/workflow"?workflow.promise:Promise.reject(Error(url)));
  const sending=h.answer("A supplier email starts a case.");await flush();
  let state=h.gate();
  assert.ok(state.waiting,"While the interviewer is working, Submit waits");
  assert.deepEqual(state.capture,{in_progress:true,notes_current:false,map_current:false,notes_through_turn:null,map_through_turn:null});
  assert.equal(h.t.sessionObject().turns.length,2,"The transcript already holds the new answer");
  assert.deepEqual(plain(h.t.sessionObject().capture),state.capture,"The same marker travels in the saved and submitted interview");
  interview.resolve(ok(question("What happens next?")));await sending;await flush();
  state=h.gate();
  assert.equal(h.t.state.busy,false);
  assert.equal(state.waiting,WAITING_NOTES,"The question has arrived, but the working map is still on its way");
  assert.equal(state.capture.notes_current,true);assert.equal(state.capture.notes_through_turn,"t002");assert.equal(state.capture.map_current,false);
  await h.runTimers(1000);
  assert.ok(h.calls.some(call=>call.url==="/api/workflow"),"The working map request runs alongside");
  assert.equal(h.gate().waiting,WAITING_NOTES);
  const before=h.changes;
  workflow.resolve(ok(map("Invoice intake")));await flush();
  state=h.gate();
  assert.equal(state.waiting,"");assert.deepEqual(state.missing,[]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:true,map_current:true,notes_through_turn:"t002",map_through_turn:"t002"});
  assert.ok(h.changes>before,"The open dialog is told when the map lands");
  assert.equal(h.notified,"","The last notification already sees nothing running, so the dialog can enable Submit");
});

await check("when the provider is down the gap is named and Submit is not blocked forever",async()=>{
  const h=setup();
  h.route(url=>url==="/api/interview"?ok(question("What happens next?")):url==="/api/workflow"?ok(map("Invoice intake")):Promise.reject(Error(url)));
  await h.answer("A supplier email starts a case.");await h.runTimers(1000);
  assert.deepEqual(h.gate().missing,[]);
  h.route(()=>down());
  await h.answer("The analyst registers the invoice.");await h.runTimers(1000);await flush();
  const state=h.gate();
  assert.equal(state.waiting,"","Nothing is running any more");
  assert.deepEqual(state.missing,["Notes include 1 of 2 answers.","The working map includes 1 of 2 answers."]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:false,map_current:false,notes_through_turn:"t002",map_through_turn:"t002"});
  assert.equal(h.t.sessionObject().turns.filter(turn=>turn.role==="user").length,2);
});

await check("nothing captured at all is said plainly",async()=>{
  const h=setup();h.route(()=>down());
  await h.answer("A supplier email starts a case.");await h.runTimers(1000);await flush();
  const state=h.gate();
  assert.equal(state.waiting,"");
  assert.deepEqual(state.missing,["No notes have been captured from your 1 answer.","No working map has been built from your 1 answer."]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:false,map_current:false,notes_through_turn:null,map_through_turn:null});
});

// The server always reports agent_team.enabled (server.py, /api/config). There the interview reply carries
// the notes and a /api/workflow reply only the working map, whatever else that reply contains.
await check("with the agent team on, the shipped configuration, the notes come from the interview reply and the map request moves only the map",async()=>{
  const reply={...map("Invoice intake"),...question("unused"),summary:"From the map request."};
  const h=setup(),interview=deferred(),workflow=deferred();h.t.state.config.agent_team={enabled:true};
  // The agent team has its own endpoints and an advisory progress poll beside each request.
  const team=(lead,mapper)=>url=>url==="/api/agent-team/interview"?lead():url==="/api/agent-team/workflow"?mapper():
    ["/api/agent-team/status","/api/agent-team/cancel"].includes(url)?ok({}):Promise.reject(Error("Unexpected request "+url));
  h.route(team(()=>interview.promise,()=>workflow.promise));
  const sending=h.answer("A supplier email starts a case.");await flush();
  assert.ok(h.gate().waiting,"While the interviewer is working, Submit waits");
  interview.resolve(ok(question("What happens next?")));await sending;await flush();
  let state=h.gate();
  assert.equal(state.waiting,WAITING_NOTES,"The working map is still on its way");
  assert.equal(state.capture.notes_current,true,"The interview reply marks the notes current");
  assert.equal(state.capture.notes_through_turn,"t002");assert.equal(state.capture.map_current,false);assert.equal(state.capture.map_through_turn,null);
  await h.runTimers(1000);workflow.resolve(ok(reply));await flush();
  assert.deepEqual([...new Set(h.calls.map(call=>call.url).filter(url=>!/status|cancel/.test(url)))],["/api/agent-team/interview","/api/agent-team/workflow"],
    "This check runs the agent-team path, not the single-interviewer one");
  state=h.gate();
  assert.equal(state.waiting,"");assert.deepEqual(state.missing,[]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:true,map_current:true,notes_through_turn:"t002",map_through_turn:"t002"});
  assert.equal(h.t.state.summary,"Captured so far.","The map request does not replace the notes");
  // Second answer: the interviewer fails, the map request succeeds. The map moves on; the notes must not.
  h.route(team(()=>down(),()=>ok(reply)));
  await h.answer("The analyst registers the invoice.");await h.runTimers(1000);await flush();
  state=h.gate();
  assert.equal(state.waiting,"");
  assert.deepEqual(state.missing,["Notes include 1 of 2 answers."],"A map reply must not mark the notes as caught up");
  assert.deepEqual(state.capture,{in_progress:false,notes_current:false,map_current:true,notes_through_turn:"t002",map_through_turn:"t004"});
  assert.equal(h.t.state.summary,"Captured so far.");
  // Without the agent team the same map reply does carry the notes; the difference is the configuration.
  const single=setup();single.route(url=>url==="/api/interview"?ok(question("What happens next?")):ok(map("Invoice intake")));
  await single.answer("A supplier email starts a case.");await single.runTimers(1000);
  single.route(url=>url==="/api/workflow"?ok(reply):down());
  await single.answer("The analyst registers the invoice.");await single.runTimers(1000);await flush();
  assert.deepEqual(single.gate().missing,[]);assert.equal(single.gate().capture.notes_through_turn,"t004");
});

await check("concurrent interviewing: the fast question does not open Submit before the background capture",async()=>{
  const h=setup(),status=deferred();h.t.state.config.concurrent_interview={enabled:true};let polls=0;
  h.route(url=>url==="/api/conversation/turn"?ok({...question("Who receives it next?"),preserve_capture:true,conversation_token:"session-one",revision:"r1"}):
    url==="/api/conversation/status"?(++polls===1?ok({state:"working",revision:"r1",conversation_token:"session-one"}):status.promise):
    url==="/api/workflow"?down():Promise.reject(Error(url)));
  await h.answer("A supplier email starts a case.");
  assert.equal(h.t.state.busy,false);assert.equal(h.t.state.turns.at(-1).text,"Who receives it next?","The next question is already on screen");
  let state=h.gate();
  assert.equal(state.waiting,WAITING_NOTES,"This is the audit's case: question arrived, notes and map still pending");
  assert.deepEqual(state.capture,{in_progress:true,notes_current:false,map_current:false,notes_through_turn:null,map_through_turn:null});
  await h.runTimers(1000);await flush();        // the first answer's own map request ends; only the background capture is left
  assert.equal(h.t.conversationUI.flowBusy,false);assert.equal(h.t.conversationUI.flowTimer,null);
  assert.equal(h.gate().waiting,WAITING_NOTES,"The background capture alone keeps Submit waiting");
  await h.runTimers(650);
  assert.equal(polls,1);
  assert.equal(h.notified,WAITING_NOTES,"A status poll that reports work in progress must not open Submit: the dialog is told while the next poll is already scheduled");
  await h.runTimers(650);
  assert.equal(polls,2);assert.equal(h.t.concurrent().active,true);
  assert.equal(h.gate().waiting,WAITING_NOTES,"Still waiting while the status request is in flight");
  const before=h.changes;
  status.resolve(ok({state:"ready",revision:"r1",conversation_token:"session-one",capture:question("unused"),workflow_state:"ready",workflow_capture:map("Invoice intake")}));await flush();
  assert.equal(h.t.concurrent().active,false);
  state=h.gate();
  assert.equal(state.waiting,"");assert.deepEqual(state.missing,[]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:true,map_current:true,notes_through_turn:"t002",map_through_turn:"t002"});
  assert.equal(h.t.state.summary,"Captured so far.");
  assert.ok(h.changes>before,"The dialog is re-enabled from the concurrent status callback");
});

// The server sends agent-team progress with every status reply, and the notes can land before the map.
// Both reach the page before the next poll is scheduled; the open dialog must not read that moment as
// "nothing is running" and flip to "Submit anyway" and back on every poll.
await check("concurrent interviewing: progress notices and notes that land first never make the dialog flip",async()=>{
  const h=setup();h.t.state.config.concurrent_interview={enabled:true};h.t.state.config.agent_team={enabled:true};let polls=0;
  const progress={run_id:"run-one",status:"working",agents:[]},last=deferred();
  h.route(url=>url==="/api/conversation/turn"?ok({...question("Who receives it next?"),preserve_capture:true,conversation_token:"session-one",revision:"r1"}):
    url==="/api/conversation/status"?(++polls===1?ok({state:"working",revision:"r1",conversation_token:"session-one",agent_team:progress}):
      polls===2?ok({state:"ready",revision:"r1",conversation_token:"session-one",agent_team:progress,capture:question("unused"),workflow_state:"working"}):last.promise):
    url==="/api/workflow"||url==="/api/agent-team/workflow"?down():ok({}));
  await h.answer("A supplier email starts a case.");await h.runTimers(1000);await flush();
  h.seen.length=0;
  await h.runTimers(650);                        // poll 1: still working, with a progress notice
  assert.equal(polls,1);assert.ok(h.seen.length>=2,"The progress notice and the status both notify the dialog");
  assert.deepEqual(h.seen.filter(state=>!state.waiting),[],"A progress notice must not read as nothing running");
  await h.runTimers(650);                        // poll 2: the notes land, the working map is still on its way
  assert.equal(polls,2);assert.equal(h.gate().capture.notes_current,true);assert.equal(h.gate().capture.map_current,false);
  assert.deepEqual(h.seen.filter(state=>!state.waiting||state.missing.length),[],"Notes that land before the map must not offer Submit anyway for a moment");
  assert.equal(h.gate().waiting,WAITING_NOTES);
  await h.runTimers(650);                        // poll 3 in flight
  assert.equal(polls,3);assert.equal(h.t.concurrent().active,true);
  last.resolve(ok({state:"ready",revision:"r1",conversation_token:"session-one",agent_team:{...progress,status:"completed"},workflow_state:"ready",capture:question("unused"),workflow_capture:map("Invoice intake")}));await flush();
  assert.equal(h.t.concurrent().active,false,"Nothing is left running once the outcome is reported");
  assert.equal(h.seen.at(-1).waiting,"","The last notification opens Submit");assert.deepEqual(h.seen.at(-1).missing,[]);
  assert.deepEqual(h.gate().capture,{in_progress:false,notes_current:true,map_current:true,notes_through_turn:"t002",map_through_turn:"t002"});
  // A poll that fails leaves nothing running either.
  const failing=setup();failing.t.state.config.concurrent_interview={enabled:true};
  failing.route(url=>url==="/api/conversation/turn"?ok({...question("Who receives it next?"),preserve_capture:true,conversation_token:"session-one",revision:"r1"}):down());
  await failing.answer("A supplier email starts a case.");await failing.runTimers(1000);await failing.runTimers(650);await flush();
  assert.equal(failing.t.concurrent().active,true,"Transient failures keep watching the current revision");
  for(let attempt=0;attempt<12 && failing.t.concurrent().active;attempt++)await failing.runTimers();
  assert.equal(failing.t.concurrent().active,false);assert.equal(failing.gate().waiting,"");
});

await check("concurrent interviewing: notes without a map, and a failed turn, are gaps rather than a block",async()=>{
  const h=setup();h.t.state.config.concurrent_interview={enabled:true};
  h.route(url=>url==="/api/conversation/turn"?ok({...question("Who receives it next?"),preserve_capture:true,conversation_token:"session-one",revision:"r1"}):
    url==="/api/conversation/status"?ok({state:"ready",revision:"r1",conversation_token:"session-one",capture:question("unused"),workflow_state:"error",workflow_error:"The workflow could not update."}):down());
  await h.answer("A supplier email starts a case.");await h.runTimers(650);await h.runTimers(1000);await flush();
  let state=h.gate();
  assert.equal(state.waiting,"");
  assert.deepEqual(state.missing,["No working map has been built from your 1 answer."],"The notes landed; only the map is missing");
  assert.equal(state.capture.notes_current,true);assert.equal(state.capture.map_current,false);
  h.route(()=>down());
  await h.answer("The analyst registers the invoice.");await flush();
  state=h.gate();
  assert.equal(h.t.concurrent().active,false);
  assert.equal(state.waiting,"","A turn that failed leaves nothing running, whatever the last status said");
  assert.deepEqual(state.missing,["Notes include 1 of 2 answers.","No working map has been built from your 2 answers."]);
});

await check("voice, file intake and a running review each keep Submit waiting",async()=>{
  const h=setup();h.route(url=>url==="/api/interview"?ok(question("Next?")):ok(map("Invoice intake")));
  await h.answer("A supplier email starts a case.");await h.runTimers(1000);
  assert.equal(h.gate().waiting,"");
  const expectWaiting=(apply,undo,pattern)=>{apply();const state=h.gate();assert.match(state.waiting,pattern);assert.equal(state.capture.in_progress,true);undo();assert.equal(h.gate().waiting,"");};
  expectWaiting(()=>{h.t.conversationUI.live={active:true};},()=>{h.t.conversationUI.live=null;},/Voice is still on/);
  expectWaiting(()=>{h.t.conversationUI.status="closing";},()=>{h.t.conversationUI.status="idle";},/still being saved/);
  expectWaiting(()=>{h.t.state.busy=true;h.t.state.busyMessage="Checking for omissions…";},()=>{h.t.state.busy=false;h.t.state.busyMessage="";},/Checking for omissions/);
  expectWaiting(()=>{h.t.setIntake({active:true,phase:"reviewing"});},()=>{h.t.setIntake(null);},/files are still being read/i);
  expectWaiting(()=>{h.t.setReview({promise:Promise.resolve(),controller:null});},()=>{h.t.setReview(null);},/completion review is still running/i);
  expectWaiting(()=>{h.t.conversationUI.flowBusy=true;},()=>{h.t.conversationUI.flowBusy=false;},/working map are still updating/);
  // Voice does not end by itself: the reason carries what to do. Work that ends by itself has none.
  const actionWhile=(apply,undo)=>{apply();const action=h.gate().action;undo();return action;};
  assert.match(actionWhile(()=>{h.t.conversationUI.live={active:true};},()=>{h.t.conversationUI.live=null;}),/Stop talking, then submit/);
  assert.equal(actionWhile(()=>{h.t.conversationUI.status="closing";},()=>{h.t.conversationUI.status="idle";}),"");
  assert.equal(actionWhile(()=>{h.t.conversationUI.flowBusy=true;},()=>{h.t.conversationUI.flowBusy=false;}),"");
  assert.equal(h.gate().action,"","Nothing to do when nothing is running");
  // Stopped rather than running: the submitter may go on, and is told what is unfinished.
  h.t.setIntake({active:true,phase:"error"});
  let state=h.gate();assert.equal(state.waiting,"");assert.deepEqual(state.missing,["A file review did not finish. Check Assets."]);assert.equal(state.capture.in_progress,true);
  h.t.setIntake(null);h.t.setReview({promise:null,controller:null});
  state=h.gate();assert.equal(state.waiting,"");assert.deepEqual(state.missing,["The completion review has not finished."]);assert.equal(state.capture.in_progress,true);
  h.t.setReview(null);assert.deepEqual(h.gate().missing,[]);
});

await check("the marker is saved with the interview and restored when it is reopened",async()=>{
  const h=setup();h.route(url=>url==="/api/interview"?ok(question("Next?")):ok(map("Invoice intake")));
  await h.answer("A supplier email starts a case.");await h.runTimers(1000);
  h.route(()=>down());await h.answer("The analyst registers the invoice.");await h.runTimers(1000);await flush();
  const saved=plain(h.t.sessionObject());
  assert.deepEqual(saved.capture,{in_progress:false,notes_current:false,map_current:false,notes_through_turn:"t002",map_through_turn:"t002"});
  const reopen=async file=>{const raw=JSON.stringify(file);h.t.state.dirty=false;await h.t.importSession({size:raw.length,text:async()=>raw});await flush();};
  await reopen(saved);
  let state=h.gate();
  assert.equal(state.waiting,"");assert.deepEqual(state.missing,["Notes include 1 of 2 answers.","The working map includes 1 of 2 answers."],"A reopened interview still knows where its capture stopped");
  await reopen({...saved,capture:{in_progress:false,notes_current:true,map_current:true,notes_through_turn:"t004",map_through_turn:"t004"}});
  state=h.gate();assert.deepEqual(state.missing,[]);assert.equal(state.capture.notes_current,true);assert.equal(state.capture.map_through_turn,"t004");
  h.t.state.config.concurrent_interview={enabled:true};
  h.t.renderAnalysisThrough();assert.equal(h.node("analysis-through").textContent,"Notes include all 2 saved answers");
  const requests=h.calls.length;h.t.scheduleWorkflow();await h.runTimers(1000);
  assert.equal(h.calls.length,requests,"Viewing a restored map does not regenerate it");
  assert.equal(h.t.conversationUI.workflow.title,saved.workflow.title);

});

await check("a file that records no capture state reopens as unknown, not as complete or incomplete",async()=>{
  const h=setup();
  const legacy={schema_version:1,context:{process_name:"Invoice intake",objective:"Document the work"},
    turns:[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A supplier email starts a case."}],
    workflow:{title:"Invoice intake",steps:[{id:"S1",title:"Receive invoice",evidence_turns:["t002"]}],connections:[]}};
  for(const capture of [undefined,"yes",{notes_through_turn:"t999",map_through_turn:"t002"},{notes_through_turn:"t001"}]){
    const raw=JSON.stringify({...legacy,...(capture===undefined?{}:{capture})});h.t.state.dirty=false;
    await h.t.importSession({size:raw.length,text:async()=>raw});await flush();
    const state=h.gate(),label=JSON.stringify(capture);
    assert.equal(state.waiting,"",label);assert.deepEqual(state.missing,[],"The app cannot tell, so it does not accuse: "+label);
    assert.equal(state.capture.notes_current,null,label);assert.equal(state.capture.notes_through_turn,null,label);
    if(capture?.map_through_turn==="t002")assert.equal(state.capture.map_through_turn,"t002");
  }
  // What the file held is not known, but an answer added now is certainly not in its notes or map.
  const raw=JSON.stringify(legacy);h.t.state.dirty=false;await h.t.importSession({size:raw.length,text:async()=>raw});await flush();
  h.route(()=>down());await h.answer("The analyst registers the invoice.");await h.runTimers(1000);await flush();
  let state=h.gate();
  assert.equal(state.waiting,"");
  // How far the file's notes reached was never recorded, so "1 of 2 answers" would state an assumption as fact.
  assert.deepEqual(state.missing,["Notes do not include your latest answer.","The working map does not include your latest answer."]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:false,map_current:false,notes_through_turn:"t002",map_through_turn:"t002",notes_assumed:true,map_assumed:true},
    "The stored marker says that the earlier position is assumed");
  // Save copy and reopen: the position stays assumed, and a further answer is counted.
  const saved=plain(h.t.sessionObject());
  h.t.state.dirty=false;await h.t.importSession({size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)});await flush();
  state=h.gate();
  assert.deepEqual(state.missing,["Notes do not include your latest answer.","The working map does not include your latest answer."]);
  assert.equal(state.capture.notes_assumed,true);
  await h.answer("Then the manager approves it.");await h.runTimers(1000);await flush();
  state=h.gate();
  assert.deepEqual(state.missing,["Notes do not include your latest 2 answers.","The working map does not include your latest 2 answers."]);
  assert.equal(state.capture.notes_through_turn,"t002");assert.equal(state.capture.map_assumed,true);
  // Once a capture lands, the position is recorded and nothing is assumed any more.
  h.route(url=>url==="/api/interview"?ok(question("Next?")):ok(map("Invoice intake")));
  await h.answer("Finance posts it.");await h.runTimers(1000);await flush();
  state=h.gate();
  assert.deepEqual(state.missing,[]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:true,map_current:true,notes_through_turn:state.capture.notes_through_turn,map_through_turn:state.capture.map_through_turn});
  // A file that held no answer assumed nothing: after a first answer the count of 0 is exact, and the
  // marker names no turn (the server refuses an assumed flag without one).
  const empty=setup(),unanswered=JSON.stringify({...legacy,turns:[legacy.turns[0]],workflow:null});
  empty.t.state.dirty=false;await empty.t.importSession({size:unanswered.length,text:async()=>unanswered});await flush();
  empty.route(()=>down());await empty.answer("A supplier email starts a case.");await empty.runTimers(1000);await flush();
  state=empty.gate();
  assert.deepEqual(state.missing,["Notes include 0 of 1 answer.","The working map includes 0 of 1 answer."]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:false,map_current:false,notes_through_turn:null,map_through_turn:null});
});

await check("a capture from documents alone has no answers to reach",async()=>{
  const h=setup();h.t.state.turns=[];
  const state=h.gate();
  assert.equal(state.waiting,"");assert.deepEqual(state.missing,[]);
  assert.deepEqual(state.capture,{in_progress:false,notes_current:true,map_current:true,notes_through_turn:null,map_through_turn:null});
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
