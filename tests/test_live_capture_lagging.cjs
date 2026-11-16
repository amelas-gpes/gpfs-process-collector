"use strict";
// Live voice, answers arriving faster than one notes capture. A capture that returns after the
// participant has added an answer (or is speaking) is paid for: its notes are shown for the
// answers it read, without completion authority, and the capture for the newer answers follows.
// A capture whose answers were rewritten is still discarded. The real request, runLiveCapture and
// applyLiveCapture of web/app.js run; media and the provider are local fakes. No network.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(source.includes("setTeam:value=>"),"The application test seam is available");
source=source.replace("setTeam:value=>","runLiveCapture,applyLiveCapture,liveSnapshot,syncLiveCoverage,getCapturedThrough:()=>liveCapturedThrough,getLiveQueued:()=>liveCaptureQueued,getPendingReview:()=>pendingCompletionReview,setTeam:value=>");
const app=exported(source,"\nmodule.exports={setup,approved,response,flush,reviewAck};");
const captureCalls=h=>h.calls.filter(call=>call.url==="/api/agent-team/interview");
const sent=(h,index)=>JSON.parse(captureCalls(h)[index].options.body);
const FIRST="An email from the client starts it.",SECOND="The treasury analyst approves the list.";
function fixture(){
 const h=app.setup();h.notes=[];h.said=[];h.pending=[];
 h.t.state.config.agent_team.voice_mode="live_front";h.t.state.config.concurrent_interview={enabled:true};
 h.t.conversationUI.live={active:true,participantSpeaking:false,assistantSpeaking:false,
   appendContext(text){h.notes.push(text);return Promise.resolve({status:"acknowledged"});},say(text){h.said.push(text);return Promise.resolve({status:"acknowledged"});}};
 h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:FIRST}];
 h.t.conversationUI.revision=1;h.t.state.summary="Last accepted notes";h.t.state.captureToken="token-before";
 // Every capture stays on its way until the test lets it return.
 h.route(url=>{
  if(url==="/api/agent-team/interview")return new Promise(resolve=>h.pending.push(resolve));
  if(url==="/api/agent-team/review")throw Error("No completion review may start from a capture of earlier answers");
  return app.response({});
 });
 // The live interviewer asks its next question and the participant answers it.
 h.exchange=(n,answer)=>{h.t.state.turns.push({id:"a"+n,role:"assistant",text:`Follow-up ${n}?`},{id:"u"+n,role:"user",text:answer});h.t.conversationUI.revision++;};
 h.land=async(extra={})=>{h.pending.shift()(app.response({...app.approved("What happens after the approval?"),...extra}));};
 return h;
}
const firstNotes=(extra={})=>({summary:"Notes through the first answer",capture_token:"token-first",coverage_verified:false,
 memo_findings:[{key:"trigger",status:"partial",answer:"An email from the client starts the work.",evidence_turns:["t002"]}],...extra});
let passed=0;
async function check(name,fn){await fn();passed++;console.log("PASS "+name);}
(async()=>{
 await check("a capture that returns after a newer answer updates the notes for the answers it read",async()=>{
  const h=fixture(),capture=h.t.runLiveCapture();await app.flush();
  assert.equal(captureCalls(h).length,1);assert.equal(sent(h,0).turns.length,2);
  h.exchange(1,SECOND);
  await h.land(firstNotes());await capture;await app.flush();
  assert.equal(h.t.state.summary,"Notes through the first answer","The paid capture is shown");
  assert.equal(h.t.state.memo_findings.find(item=>item.key==="trigger")?.answer,"An email from the client starts the work.");
  assert.equal(h.t.state.captureToken,"token-first","The next capture continues from this one");
  // The checkpoint is bound to the answers that were read, so nothing claims the newer answer.
  assert.equal(h.t.conversationUI.coverageCheckpoint.basis,JSON.stringify([["t002",FIRST]]));
  assert.equal(h.t.conversationUI.coverageCheckpoint.through,"t002");
  assert.equal(h.notes.length,0,"No coverage note is sent to the live interviewer for a checkpoint that lags the conversation");
  assert.equal(h.said.length,0);assert.equal(h.t.state.turns.length,4,"The lead's proposed question is not added");
  assert.equal(h.t.state.coverageVerified,false);assert.equal(h.t.state.completion,null);
  assert.notEqual(h.t.getCapturedThrough(),"u1:"+SECOND,"The newer answer is not marked as captured");
  // The capture for the newer answer follows at once, from the token just taken.
  await h.timer(400);
  assert.equal(captureCalls(h).length,2,"The follow-up capture starts without waiting for another caption");
  assert.equal(sent(h,1).turns.at(-1).text,SECOND);assert.equal(sent(h,1).capture_token,"token-first");
  await h.land({summary:"Notes through both answers",capture_token:"token-second",memo_findings:[
   {key:"trigger",status:"partial",answer:"An email from the client starts the work.",evidence_turns:["t002"]},
   {key:"checks",status:"partial",answer:"The treasury analyst approves the list.",evidence_turns:["u1"]}]});
  await app.flush();
  assert.equal(h.t.state.summary,"Notes through both answers");assert.equal(h.t.getCapturedThrough(),"u1:"+SECOND);
  assert.equal(h.t.conversationUI.coverageCheckpoint.through,"u1");
  assert.equal(h.notes.length,1,"The caught-up checkpoint sends its one coverage note");
 });
 await check("six answers that each arrive before the previous capture returns: every capture is used",async()=>{
  const h=fixture();let applied=0;
  for(let round=1;round<=6;round++){
   const capture=h.t.runLiveCapture();await app.flush();
   assert.equal(captureCalls(h).length,round,"One capture per round, never two at once");
   h.exchange(round,`Answer number ${round}.`);
   const before=h.t.state.summary;
   await h.land({summary:"Notes through round "+round,capture_token:"token-"+round});await capture;await app.flush();
   if(h.t.state.summary!==before)applied++;
   assert.equal(h.t.state.summary,"Notes through round "+round);
   // The follow-up for the answer that arrived meanwhile is already scheduled; the next round runs it.
   assert.ok([...h.timers.values()].some(timer=>timer.ms===400),"A follow-up capture is scheduled");
   for(const [id,timer] of [...h.timers])if(timer.ms===400)h.timers.delete(id);
  }
  assert.equal(applied,6);assert.equal(h.said.length,0);assert.equal(h.t.state.coverageVerified,false);
 });
 await check("a capture of earlier answers never carries completion authority",async()=>{
  for(const kind of ["review_pending","final_check","pause","complete"]){
   const h=fixture(),capture=h.t.runLiveCapture();await app.flush();
   h.exchange(1,"One more thing: the bank confirms receipt by email.");
   const decided=kind==="review_pending"?app.reviewAck():{...app.approved("Thank you. That is everything.",kind),closure:{asked:true,confirmed:kind==="complete"}};
   await h.land({...decided,...firstNotes({coverage_verified:kind!=="review_pending"})});await capture;await app.flush();
   assert.equal(h.t.state.summary,"Notes through the first answer",kind+": the notes are still used");
   assert.equal(h.t.state.coverageVerified,false,kind);assert.equal(h.t.state.completion,null,kind);
   assert.deepEqual({...h.t.state.closure},{asked:false,confirmed:false},kind);
   assert.equal(h.said.length,0,kind+": no closing line is spoken");assert.equal(h.t.state.turns.length,4,kind+": no line is added");
   assert.equal(h.t.getPendingReview(),null,kind+": no completion review is prepared");
   assert.equal(h.calls.filter(call=>call.url==="/api/agent-team/review").length,0,kind);
   assert.equal(h.notes.length,0,kind);
  }
 });
 await check("the participant is speaking when the capture returns: notes are shown, the decision waits",async()=>{
  const h=fixture(),capture=h.t.runLiveCapture();await app.flush();
  h.t.conversationUI.live.participantSpeaking=true;
  await h.land({...app.approved("Thank you. That is everything.","complete"),...firstNotes({coverage_verified:true})});await capture;await app.flush();
  assert.equal(h.t.state.summary,"Notes through the first answer");
  assert.equal(h.t.state.coverageVerified,false);assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.said.length,0);
  assert.equal(h.notes.length,0,"Nothing is fed to the live interviewer mid-answer");
  // Nothing new was said after all: the same answers are captured again (the server answers that
  // from the capture it kept), and this time the decision can be applied.
  assert.equal(h.t.getCapturedThrough(),null);assert.equal(h.t.getLiveQueued(),true);
  h.t.conversationUI.live.participantSpeaking=false;
  const again=h.t.runLiveCapture();await app.flush();
  assert.equal(captureCalls(h).length,2);assert.equal(sent(h,1).capture_token,"token-first");
  await h.land({...app.approved("Have I missed anything?","final_check"),...firstNotes({coverage_verified:true,no_new_run:true,capture_token:"token-final"})});await again;await app.flush();
  assert.equal(h.t.state.coverageVerified,true);assert.deepEqual(h.said,["Have I missed anything?"]);
  assert.equal(h.t.getCapturedThrough(),"t002:"+FIRST);
 });
 await check("a capture whose answers were rewritten or removed is still discarded",async()=>{
  const changes={
   "an earlier answer was corrected":h=>{h.t.state.turns[1].text="A letter from the client starts it.";h.exchange(1,SECOND);},
   "the answer it read grew after it was sent":h=>{h.t.state.turns[1].text=FIRST+" Usually on Monday.";h.t.conversationUI.revision++;},
   "an answer it read is gone":h=>{h.t.state.turns.splice(1,1);h.exchange(1,SECOND);},
   "the files changed":h=>{h.exchange(1,SECOND);h.t.setDocuments({exportState:()=>({scope:"changed-file-scope",documents:[]})});},
   "the context changed":h=>{h.exchange(1,SECOND);h.t.state.context={...h.t.state.context,background:"Changed scope"};}};
  for(const [name,change] of Object.entries(changes)){
   const h=fixture(),capture=h.t.runLiveCapture();await app.flush();
   change(h);
   await h.land(firstNotes());await capture;await app.flush();
   assert.equal(h.t.state.summary,"Last accepted notes",name);assert.equal(h.t.state.captureToken,"token-before",name);
   assert.equal(h.t.conversationUI.coverageCheckpoint,null,name);assert.equal(h.t.getCapturedThrough(),null,name);
   assert.equal(h.t.getLiveQueued(),true,name+": the capture of the conversation as it now stands is queued");
  }
 });
 await check("the capture token is taken only when the next capture can continue from it",async()=>{
  // The interviewer's caption that the capture was sent with has grown since: the server could not
  // continue from a token bound to the shorter transcript, so the earlier token stays in use.
  const h=fixture();h.t.state.turns.push({id:"t003",role:"assistant",text:"Got it."},{id:"t004",role:"user",text:SECOND});
  const capture=h.t.runLiveCapture();await app.flush();
  h.t.state.turns[2].text="Got it. And who approves the list?";h.exchange(1,"Nobody else.");
  await h.land(firstNotes());await capture;await app.flush();
  assert.equal(h.t.state.summary,"Notes through the first answer","The notes are used");
  assert.equal(h.t.state.captureToken,"token-before");
 });
 await check("a capture that still matches the conversation keeps its full authority",async()=>{
  const h=fixture(),capture=h.t.runLiveCapture();await app.flush();
  // The interviewer spoke meanwhile; the participant added nothing.
  h.t.state.turns.push({id:"t003",role:"assistant",text:"Thank you, that is clear."});
  await h.land({...app.approved("Have I missed anything?","final_check"),...firstNotes({coverage_verified:true})});await capture;await app.flush();
  assert.equal(h.t.state.coverageVerified,true);assert.equal(h.t.state.closure.asked,true);assert.deepEqual(h.said,["Have I missed anything?"]);
  assert.equal(h.t.getCapturedThrough(),"t002:"+FIRST);assert.equal(h.t.getLiveQueued(),false);
 });
 console.log(JSON.stringify({checks_passed:passed,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
