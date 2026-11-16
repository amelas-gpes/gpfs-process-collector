"use strict";
// A stop or pause request must never cost the notes. The real app state and the
// real concurrent controller run behind the same fake browser/media boundary as
// the existing experience suite. No network, provider or physical audio.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
let harness=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(harness.includes("function setup()"));
harness=harness.replace('const controlled=','const concurrent=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");\nconst controlled=');
harness=harness.replace('updateControls=()=>{updatePresence();};','updateControls=()=>{updatePresence();}; renderWorkingMap=()=>{}; updateSaveHint=()=>{}; updateConversationControls=()=>{}; updateDocumentIntakeUI=()=>{};');
harness=harness.replace('setTeam:value=>','finalCheck,applyBackgroundCapture,sessionObject,transcriptObject,renderAnalysisThrough,setTeam:value=>');
harness=harness.replace('vm.runInContext(controlled,context,','vm.runInContext(concurrent,context,{filename:"concurrent-interview.js"});vm.runInContext(controlled,context,');
harness+='\nmodule.exports={setup,approved,response,flush,deferred};';
const exported={exports:{}};
vm.runInNewContext(harness,{require,__dirname,module:exported,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException},{filename:"stop-keeps-notes-harness.cjs"});
const {setup,approved,response,flush}=exported.exports;
const clone=value=>JSON.parse(JSON.stringify(value));
const TURN_PAUSE="Of course. We can pause here and keep the unfinished parts open.";
const COORDINATOR_PAUSE="Of course. We can stop here. Your account is retained, with any unfinished sections still open.";
// The Coordinator's reply to a stop request, exactly as interview_orchestrator.py builds it: no notes at all.
const pauseReply=()=>({question:COORDINATOR_PAUSE,preserve_capture:true,ready_for_draft:false,closure:{asked:false,confirmed:false},
  completion:{allowed:false,complete:false,partial:true,ready_for_final_check:false,blockers:["participant_stopped"]},
  agent_team:{run_id:"run-stop",status:"blocked",cancelled:true,agents:[],events:[]},agent_run_id:"run-stop",
  speech_authorization:{approved:true,kind:"pause",text:COORDINATOR_PAUSE,revision:"ledger",completion_allowed:false}});
// What /api/conversation/turn answers a stop request with.
const pauseTurn=()=>({question:TURN_PAUSE,preserve_capture:true,conversation_token:"session-one",revision:"r-stop",sync_required:false,
  completion:{complete:false,ready_for_final_check:false,allowed:false},ready_for_draft:false,closure:{asked:false,confirmed:false},
  speech_authorization:{approved:true,text:TURN_PAUSE,kind:"pause",revision:"r-stop",completion_allowed:false}});
const notes=(summary="A clerk logs each request and the supervisor reviews it before release.")=>({...approved("This analysis question must not be spoken"),summary,
  focus:"How the review is evidenced",parking_lot:["Month-end volume was mentioned but not explained"],
  memo_findings:[{key:"trigger",status:"partial",answer:"A clerk receives the request and logs it.",evidence_turns:["t002"]},
    {key:"checks",status:"partial",answer:"The supervisor reviews it before release.",evidence_turns:["t004"]}],
  coverage:[{key:"trigger",status:"partial"},{key:"checks",status:"partial"}],
  taxonomy:[{facet:"function",value:"Operations",note:"Request handling",evidence_turns:["t002"]}],
  connections_out:[{relationship_type:"feeds",counterpart:"Client reporting",condition:"After release",evidence_turns:["t004"]}],
  topic_discussion:[{key:"trigger",discussed:true,evidence_turns:["t002"]},{key:"checks",discussed:true,evidence_turns:["t004"]}]});
const KEPT=["memo_findings","coverage","summary","focus","parking_lot","taxonomy","connections_out"];
const kept=h=>clone(Object.fromEntries(KEPT.map(key=>[key,h.t.state[key]])));
function interview(){
  const h=setup();h.t.state.config.concurrent_interview={enabled:true};h.t.state.config.api_configured=true;
  h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts this work?"}];return h;
}
// An interview with notes on two topics, taken by the app's own background-capture path.
function interviewWithNotes(){
  const h=interview();
  h.t.state.turns.push({id:"t002",role:"user",text:"A clerk receives the request and logs it."},{id:"t003",role:"assistant",text:"Who reviews it?"},
    {id:"t004",role:"user",text:"The supervisor reviews it before release."},{id:"t005",role:"assistant",text:"What happens after the review?"});
  h.t.applyBackgroundCapture(notes(),h.t.snapshot());
  assert.equal(h.t.state.memo_findings.filter(item=>item.status!=="unknown").length,2);assert.equal(h.t.state.taxonomy.length,1);
  assert.equal(topicsWithNotes(h),2);assert.equal(h.node("analysis-through").textContent,"Notes include all 2 saved answers");
  return h;
}
// What the Notes list shows: the topics that carry a state ("Discussed · needs detail", "Captured · …").
// The separate line "N of 16 topics discussed" was folded into these per-topic labels, so the panel is read here.
function topicsWithNotes(h){return h.node("coverage-list").children.filter(topic=>topic.children[2].textContent!=="").length;}
function stopSnapshot(h){h.t.state.turns.push({id:"t006",role:"user",text:"I need to stop now."});return h.t.snapshot();}
function assertNotesKept(h,before,label){
  assert.deepEqual(kept(h),before,label+": the notes changed");
  const saved=h.t.sessionObject();
  for(const key of KEPT)assert.deepEqual(clone(saved[key]),before[key],label+": Save copy lost "+key);
  assert.equal(saved.memo_findings.filter(item=>item.status!=="unknown").length,2,label);
  const exported=h.t.transcriptObject();
  assert.equal(exported.memo.topics.filter(topic=>topic.status!=="unknown").length,2,label+": the transcript export lost topics");
  assert.equal(exported.interview_notes.working_summary,before.summary,label+": the transcript export lost the summary");
  assert.equal(topicsWithNotes(h),2,label+": the Notes list lost its topics");
}
let passed=0;async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
(async()=>{
await check("a pause reply published as a background capture leaves every note alone",async()=>{
  const h=interviewWithNotes(),before=kept(h),captured=stopSnapshot(h);
  h.t.applyBackgroundCapture(pauseReply(),captured);
  assertNotesKept(h,before,"pause reply");
  assert.equal(h.t.state.memo_findings[0].answer.startsWith("UNKNOWN"),h.t.state.memo_findings[0].status==="unknown");
});
await check("a result without a list of notes is never applied as notes",async()=>{
  const h=interviewWithNotes(),before=kept(h),captured=stopSnapshot(h);
  h.t.applyBackgroundCapture({question:"Anything",summary:"A summary with no notes behind it",focus:"Wrong",parking_lot:["Wrong"],coverage:[]},captured);
  assertNotesKept(h,before,"memo-less result");
  // It was not a pause either: the unanalysed answer stays visibly pending.
  assert.equal(h.node("analysis-through").textContent,"Notes through answer 2 · answer 3 pending");
});
await check("after a pause the status line says how far the notes go and never claims every answer",async()=>{
  const h=interviewWithNotes(),captured=stopSnapshot(h);
  h.t.applyBackgroundCapture(pauseReply(),captured);
  const line=h.node("analysis-through").textContent;
  assert.doesNotMatch(line,/include all/);assert.doesNotMatch(line,/pending/);
  assert.equal(line,"Notes kept through answer 2 · paused at your request");
  // Applying the same pause again (the workflow poll does) keeps the same statement.
  h.t.applyBackgroundCapture(pauseReply(),captured);assert.equal(h.node("analysis-through").textContent,line);
});
await check("a pause before any notes exist says so without inventing an answer number",async()=>{
  const h=interview();h.t.state.turns.push({id:"t002",role:"user",text:"I need to stop now."});
  h.t.applyBackgroundCapture({preserve_capture:true},h.t.snapshot());
  assert.equal(h.node("analysis-through").textContent,"Notes kept as they were · paused at your request");
  assert.deepEqual(clone(h.t.state.memo_findings),[]);assert.equal(h.t.state.summary,"");
});
await check("a pause still lets the workflow map update",async()=>{
  const h=interviewWithNotes(),before=kept(h),captured=stopSnapshot(h);
  h.t.applyBackgroundCapture({...pauseReply(),workflow_capture:{workflow:{title:"Request handling",steps:[],connections:[],open_questions:[]}}},captured);
  assert.equal(h.t.conversationUI.workflow.title,"Request handling");assert.equal(h.node("workflow-status").textContent,"Updated through the latest answer");
  assertNotesKept(h,before,"pause with a workflow update");
});
await check("typed stop request: the reply, the status poll and Save copy keep the notes",async()=>{
  const h=interviewWithNotes(),before=kept(h);
  h.route(url=>url==="/api/conversation/turn"?response(pauseTurn()):url==="/api/conversation/status"?response({state:"ready",revision:"r-stop",conversation_token:"session-one",capture_preserved:true,workflow_state:"ready"}):Promise.reject(Error(url)));
  h.node("answer-text").value="I need to stop now.";await h.t.sendAnswer({preventDefault(){}});
  assert.equal(h.t.state.turns.at(-1).text,TURN_PAUSE);assert.equal(h.t.state.turns.at(-2).text,"I need to stop now.");
  await h.timer(650);
  assert.equal(h.calls.at(-1).url,"/api/conversation/status");assert.equal(h.timers.size,0,"polling ends once the pause is settled");
  assertNotesKept(h,before,"typed stop");
  assert.equal(h.t.sessionObject().turns.length,7);
  assert.equal(h.node("analysis-status").textContent,"Paused — your notes are kept. Wrap up when you’re ready for the final checks.");
  assert.equal(h.node("analysis-through").textContent,"Notes kept through answer 2 · paused at your request");
  assert.equal(h.notices.filter(item=>item.error).length,0);
});
await check("a server that still publishes the pause reply as its capture cannot blank the notes",async()=>{
  const h=interviewWithNotes(),before=kept(h);
  h.route(url=>url==="/api/conversation/turn"?response(pauseTurn()):url==="/api/conversation/status"?response({state:"ready",revision:"r-stop",conversation_token:"session-one",capture:pauseReply(),workflow_state:"ready"}):Promise.reject(Error(url)));
  h.node("answer-text").value="I need to stop now.";await h.t.sendAnswer({preventDefault(){}});await h.timer(650);
  assertNotesKept(h,before,"pause reply as the capture");
  assert.doesNotMatch(h.node("analysis-through").textContent,/include all/);
});
await check("a stop as the very first answer does not break the poller",async()=>{
  const h=interview();
  h.route(url=>url==="/api/conversation/turn"?response(pauseTurn()):url==="/api/conversation/status"?response({state:"ready",revision:"r-stop",conversation_token:"session-one",capture_preserved:true,workflow_state:"ready"}):Promise.reject(Error(url)));
  h.node("answer-text").value="I need to stop now.";await h.t.sendAnswer({preventDefault(){}});await h.timer(650);
  assert.equal(h.t.state.turns.at(-1).text,TURN_PAUSE);assert.equal(h.timers.size,0);
  assert.doesNotMatch(h.node("analysis-status").textContent,/need attention/);
  assert.equal(h.node("analysis-status").textContent,"Paused — your notes are kept. Wrap up when you’re ready for the final checks.");
  assert.equal(h.notices.filter(item=>item.error).length,0);
});
await check("wrap up after a stop applies the real capture it returns",async()=>{
  const h=interviewWithNotes();
  h.route(url=>url==="/api/conversation/turn"?response(pauseTurn()):url==="/api/conversation/status"?response({state:"ready",revision:"r-stop",conversation_token:"session-one",capture_preserved:true,workflow_state:"ready"}):
    url==="/api/conversation/sync"?response({...notes("The whole account, captured again at wrap up."),question:"Which exception still needs explaining?",capture_token:"capture-after-stop",conversation_token:"session-one",revision:"r-stop",sync_required:false,
      speech_authorization:{approved:true,kind:"question",text:"Which exception still needs explaining?",revision:"r-stop",completion_allowed:false}}):Promise.reject(Error(url)));
  h.node("answer-text").value="I need to stop now.";await h.t.sendAnswer({preventDefault(){}});await h.timer(650);
  await h.t.finalCheck();
  const sync=h.calls.find(call=>call.url==="/api/conversation/sync");assert.ok(sync,"Wrap up synchronizes");
  const sent=JSON.parse(sync.options.body);assert.equal(sent.action,"close");assert.equal(sent.turns.at(-1).text,TURN_PAUSE);
  assert.equal(h.t.state.summary,"The whole account, captured again at wrap up.");assert.equal(h.t.state.turns.at(-1).text,"Which exception still needs explaining?");
  assert.equal(h.t.state.memo_findings.filter(item=>item.status!=="unknown").length,2);
  // The transcript renderer that refreshes this line is outside the harness boundary.
  h.t.renderAnalysisThrough();assert.equal(h.node("analysis-through").textContent,"Notes include all 3 saved answers");
});
await check("a synchronization that answers with the pause reply keeps the notes",async()=>{
  const h=interviewWithNotes(),before=kept(h);stopSnapshot(h);
  h.route(url=>url==="/api/conversation/sync"?response({...pauseReply(),conversation_token:"session-one",revision:"r-stop",sync_required:false}):Promise.reject(Error(url)));
  await h.t.finalCheck();
  assert.equal(h.t.state.turns.at(-1).text,COORDINATOR_PAUSE);assertNotesKept(h,before,"pause reply from sync");
});
// The controller alone, as tests/test_concurrent_interview.cjs drives it.
const controllerSource=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");
function controller(route){
  let serial=0;const timers=new Map(),calls=[],applied=[],statuses=[];
  const snapshot={context:{process_name:"Fictional process"},turns:[{id:"u1",role:"user",text:"I need to stop now."}],document_revision:"doc1"};
  const window={},context={window,AbortController,DOMException,JSON,Error,TypeError,Set};vm.createContext(context);vm.runInContext(controllerSource,context);
  const instance=new window.CollectorConcurrentInterview({request:async(url,data,options)=>{calls.push({url,data,options});return route(url,data,options);},getSnapshot:()=>snapshot,getGeneration:()=>1,
    applyCapture:(capture,meta)=>applied.push({capture,meta}),onStatus:status=>statuses.push(status),setTimeout:fn=>{const id=++serial;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
  const tick=async()=>{const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());await flush();};
  return{instance,snapshot,calls,applied,statuses,timers,tick};
}
const settled={state:"ready",revision:"r-stop",conversation_token:"session-one",capture_preserved:true};
await check("a settled pause without a capture is a result, not an error",async()=>{
  const h=controller(url=>url.endsWith("/turn")?pauseTurn():{...settled,workflow_state:"ready"});
  await h.instance.turn(h.snapshot);await h.tick();
  assert.equal(h.statuses.some(status=>status.state==="error"),false);assert.equal(h.statuses.at(-1).state,"ready");assert.equal(h.statuses.at(-1).kept,true);
  assert.equal(h.applied.length,1);assert.deepEqual(clone(h.applied[0].capture),{preserve_capture:true});assert.equal(h.timers.size,0);
});
await check("a kept pause still delivers the workflow when it arrives",async()=>{
  let polls=0;const h=controller(url=>url.endsWith("/turn")?pauseTurn():{...settled,workflow_state:++polls<2?"working":"ready",...(polls>=2?{workflow_capture:{workflow:{steps:[],connections:[]}}}:{})});
  await h.instance.turn(h.snapshot);await h.tick();assert.equal(h.applied.length,1);assert.equal(h.timers.size,1);
  await h.tick();assert.equal(h.applied.length,2);assert.equal(h.applied[1].capture.preserve_capture,true);assert.ok(h.applied[1].capture.workflow_capture);
  assert.equal("memo_findings" in h.applied[1].capture,false);assert.equal(h.timers.size,0);
});
await check("ready without a capture and without the pause marker is still reported",async()=>{
  const h=controller(url=>url.endsWith("/turn")?pauseTurn():{state:"ready",revision:"r-stop",conversation_token:"session-one"});
  await h.instance.turn(h.snapshot);await h.tick();
  assert.equal(h.applied.length,0);assert.equal(h.statuses.at(-1).state,"error");assert.match(h.statuses.at(-1).message,/without a capture/);
});
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
