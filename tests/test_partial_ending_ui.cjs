"use strict";
// The verified partial ("pause") ending on screen: said on the closure line with the sections that
// stay open, no invitation to wrap up again, Wrap up back as soon as the participant adds something,
// voice ended as after a completed interview. A review that failed, and a stop the participant asked
// for, are not that ending and keep their own controls. The page of web/index.html runs web/app.js
// through its own init() (tests/fixtures/app_page.cjs). No browser, provider or network.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="renderTranscript,updateControls,sendAnswer,applyInterview,applyLiveCapture,liveSnapshot,receiveLiveCaption,getConcurrentInterview,tab,selectConversationView,sessionObject";
const TOPICS=["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials","scope","rules","connections","data_systems","volume"];
const ACK="Let me check what we have and keep the unanswered parts open.";
const PAUSE="The remaining sections need information you do not have here: Consequences of failure; Volume & effort. We can keep this as a partial capture for follow-up.";
const FAILED="Your account is retained. The review could not finish; you can retry it when you are ready.";
const STOPPED="Of course. We can stop here. Your account is retained, with any unfinished sections still open.";
// Notes with fourteen sections captured and two the participant could not answer.
const findings=()=>TOPICS.map(key=>["risk","volume"].includes(key)
 ?{key,status:"partial",answer:"The participant does not know this and cannot say who does.",evidence_turns:["t004"]}
 :{key,status:"captured",answer:`Reported detail for ${key}.`,evidence_turns:["t002"]});
const capture=(question,kind,extra={})=>({question,summary:"A weekly supply count.",focus:"",parking_lot:[],memo_findings:findings(),coverage:[],
 completion:{ready_for_final_check:false,complete:false,partial:true},closure:{asked:false,confirmed:false},
 speech_authorization:{approved:true,kind,text:question,revision:"r1",completion_allowed:false},coverage_verified:false,...extra});
const verifiedPause=(extra={})=>capture(PAUSE,"pause",{coverage_verified:true,capture_token:"token-pause",...extra});
function interview(page){
 page.state.context={process_name:"Supply order",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A weekly count of the supply cupboard starts it."},
  {id:"t003",role:"assistant",text:"What happens if it is missed, and how many orders are there?"},{id:"t004",role:"user",text:"I don't know either of those, and I don't know who would."}];
 page.state.completion={ready_for_final_check:true,complete:false};
 page.t.conversationUI.typing=true;page.t.tab("interview");page.t.selectConversationView("transcript");page.t.renderTranscript();
}
// Wrap up as the person presses it: acknowledgement, then the review's decision.
async function wrapUp(page,decision){
 const calls={lead:0,review:0};
 page.route((url,options,body)=>{
  if(url==="/api/agent-team/interview"){calls.lead++;return capture(ACK,"review_pending",{review_purpose:"partial",capture_token:"token-ack",review_ticket:"ticket-one",agent_run_id:"run-one"});}
  if(url==="/api/agent-team/review"){calls.review++;return decision;}
  return {};
 });
 assert.equal(page.$("final-check").click(),true,"Wrap up can be pressed");await page.flush();await page.flush();
 return calls;
}
const closureLine=page=>page.$("closure-status").hidden?"":page.text("closure-status");
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,6).join("\n     "));}
}
(async()=>{
 const config={agent_team:{enabled:true}};
 await check("a verified partial ending is stated, with the open sections, and Wrap up is not offered again",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page);
  const calls=await wrapUp(page,verifiedPause());
  assert.deepEqual(calls,{lead:1,review:1});assert.equal(page.state.turns.at(-1).text,PAUSE);assert.equal(page.state.turns.at(-2).text,ACK);
  assert.equal(page.shown("closure-status"),true,"The ending has a state on screen");
  assert.match(closureLine(page),/^Kept as a partial capture\./);
  assert.match(closureLine(page),/2 sections need information you do not have here: Risks; Volume and effort\./,"The open sections are named as the Notes list names them");
  assert.equal(page.$("final-check").hidden,true,"Wrap up is not offered for the same evidence again");
  assert.equal(page.$("generate-draft").disabled,false,"The draft can be created from the partial capture");
  assert.equal(page.state.closure.partial,true);assert.equal(page.state.closure.asked,false);assert.equal(page.state.closure.confirmed,false);
  assert.equal(page.$("retry-question").hidden,true,"Nothing failed, so nothing is offered to retry");
  // Saved interviews keep the shape they had: a partial ending is never stored as a confirmation.
  assert.equal(JSON.stringify(page.t.sessionObject().closure),JSON.stringify({asked:false,confirmed:false,partial:true}));
 });
 await check("one open section is worded in the singular, and the notes status stops inviting a wrap-up",async()=>{
  const page=await open({config:{...config,concurrent_interview:{enabled:true}},modules:["concurrent-interview.js"],expose:EXPOSE});interview(page);
  page.t.getConcurrentInterview().notify({state:"ready"});
  assert.equal(page.text("analysis-status"),"Notes are up to date.");
  const one=verifiedPause();Object.assign(one.memo_findings.find(item=>item.key==="volume"),{status:"captured",answer:"About forty orders a month.",evidence_turns:["t002"]});
  page.t.applyInterview(one);
  assert.match(closureLine(page),/1 section needs information you do not have here: Risks\./);
  assert.equal(page.$("final-check").hidden,true);
  // The ending is said once, beside the draft control; the notes status only reports the notes.
  assert.equal(page.text("analysis-status"),"Notes are up to date.");
  assert.doesNotMatch(page.text("analysis-status"),/Wrap up/);assert.doesNotMatch(closureLine(page),/Wrap up/);
 });
 await check("the ending lasts until the participant adds something; then Wrap up is back",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page);await wrapUp(page,verifiedPause());
  assert.equal(page.$("final-check").hidden,true);
  page.route(url=>url==="/api/agent-team/interview"?capture("Who could tell us the order volume?","question",{capture_token:"token-next"}):{});
  page.$("answer-text").input("Actually, about forty orders a month.");await page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(page.state.closure.partial,undefined,"New evidence withdraws the ending");
  assert.equal(closureLine(page),"");assert.equal(page.$("final-check").hidden,false,"Wrap up is offered again");
 });
 await check("a review that failed keeps its retry control and is not shown as a partial ending",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page);
  await wrapUp(page,capture(FAILED,"pause",{preserve_capture:true,review_retry_required:true,review_ticket:"ticket-one",capture_token:"token-failed",coverage_verified:false}));
  assert.equal(page.state.turns.at(-1).text,FAILED);
  assert.equal(page.state.closure.partial,undefined);assert.doesNotMatch(closureLine(page),/partial capture/);
  assert.equal(page.$("retry-question").hidden,false);assert.equal(page.text("retry-question"),"Retry completion review");
  assert.equal(page.$("final-check").hidden,false,"Wrap up stays available");
 });
 await check("a pause that is not a verified review decision is not that ending either",async()=>{
  const cases={
   "the participant asked to stop":capture(STOPPED,"pause",{preserve_capture:true}),
   "a pause without verified coverage":capture(PAUSE,"pause",{coverage_verified:false}),
   "a verified final check":capture("Is there anything I have missed?","final_check",{coverage_verified:true,completion:{ready_for_final_check:true,complete:false},closure:{asked:true,confirmed:false}}),
   "an ordinary question":capture("Who could tell us?","question")};
  for(const [name,result] of Object.entries(cases)){
   const page=await open({config,expose:EXPOSE});interview(page);page.t.applyInterview(result);
   assert.equal(page.state.closure.partial,undefined,name);assert.doesNotMatch(closureLine(page),/partial capture/,name);
   assert.equal(page.$("final-check").hidden,false,name+": Wrap up stays available");
  }
 });
 await check("the same ending returned again adds no line to the transcript",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page);await wrapUp(page,verifiedPause());
  const before=page.state.turns.length;
  // What the server now answers to a repeated Wrap up: the kept capture, marked as no new run.
  page.t.applyInterview(verifiedPause({no_new_run:true}));page.t.applyInterview(verifiedPause({no_new_run:true}));
  assert.equal(page.state.turns.length,before,"No second copy of the line");assert.equal(page.state.turns.filter(turn=>turn.text===PAUSE).length,1);
  assert.equal(page.state.closure.partial,true);assert.equal(page.$("final-check").hidden,true);
  // If the line never reached the transcript (the first response was lost), it is added once.
  const lost=await open({config,expose:EXPOSE});interview(lost);
  lost.t.applyInterview(verifiedPause({no_new_run:true}));
  assert.equal(lost.state.turns.at(-1).text,PAUSE);assert.equal(lost.state.turns.filter(turn=>turn.text===PAUSE).length,1);
  // A new run is never mistaken for a repeat, even with the same wording.
  page.t.applyInterview(verifiedPause());assert.equal(page.state.turns.length,before+1);
 });
 await check("Live voice: the partial ending is spoken once and voice then ends, as after completion",async()=>{
  const live=()=>({active:true,connected:true,participantSpeaking:false,assistantSpeaking:false,said:[],stops:0,
   say(text){this.said.push(text);return Promise.resolve({status:"acknowledged"});},stop(){this.stops++;this.active=false;return Promise.resolve({finalized:true});},
   setMuted(){},appendContext(){return Promise.resolve({status:"acknowledged"});}});
  const ending=page=>page.waiting(timer=>timer.ms===9000);
  const page=await open({config:{agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true}},expose:EXPOSE});interview(page);
  page.route(()=>({}));page.t.conversationUI.live=live();
  assert.equal(await page.t.applyLiveCapture(verifiedPause(),page.t.liveSnapshot()),true);await page.flush();
  assert.deepEqual([...page.t.conversationUI.live.said],[PAUSE]);assert.equal(page.state.closure.partial,true);
  assert.match(closureLine(page),/^Kept as a partial capture\./,"The page says so while voice is still on");
  assert.equal(ending(page).length,1,"Voice is set to end after the line, as after a completed interview");
  const session=page.t.conversationUI.live;session.assistantSpeaking=true;await page.run(ending(page)[0]);
  assert.equal(session.stops,0,"A long spoken ending is allowed to finish");
  session.assistantSpeaking=false;page.advance(1600);await page.run(page.waiting(timer=>timer.ms===500)[0]);
  assert.equal(session.stops,1,"Voice has ended");
  // The participant speaks again before that: the ending is withdrawn and voice stays on.
  const again=await open({config:{agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true}},expose:EXPOSE});interview(again);
  again.route(()=>({}));again.t.conversationUI.live=live();
  await again.t.applyLiveCapture(verifiedPause(),again.t.liveSnapshot());await again.flush();assert.equal(ending(again).length,1);
  again.t.receiveLiveCaption({id:"c1",role:"user",text:"Oh, I remember now:",final:false});
  assert.equal(ending(again).length,0);assert.equal(again.t.conversationUI.live.stops,0);assert.equal(again.state.closure.partial,undefined);
  // A failed review spoken in voice does not end the session.
  const failedReview=await open({config:{agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true}},expose:EXPOSE});interview(failedReview);
  failedReview.route(()=>({}));failedReview.t.conversationUI.live=live();
  await failedReview.t.applyLiveCapture(capture(FAILED,"pause",{preserve_capture:true,review_retry_required:true,review_ticket:"ticket-one",coverage_verified:false}),failedReview.t.liveSnapshot());await failedReview.flush();
  assert.equal(ending(failedReview).length,0,"Voice stays on after a review that could not finish");assert.equal(failedReview.state.closure.partial,undefined);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
