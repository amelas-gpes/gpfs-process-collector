"use strict";
// While live captions stream, the Notes list and an open topic dialog keep their controls: a
// click is mouse-down and mouse-up on the same element, so a control that is rebuilt between the
// two never receives it. The sixteen topic buttons are updated in place, and the source links
// (and a review's "earlier notes") of an open topic are rebuilt only when what they show changes.
// The page of web/index.html runs web/app.js through its own init() (tests/fixtures/app_page.cjs);
// captions arrive through the real receiveLiveCaption. No browser, provider or network.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="renderTranscript,renderCoverage,receiveLiveCaption,showFoundationTopic,closeFoundationTopic,tab,selectConversationView,rememberCoverageCheckpoint,normalizedFacts";
const topic=(page,key)=>page.document.querySelector(`[data-foundation-topic="${key}"]`);
// A mouse press as the browser treats it: the click goes to the element only if the element under
// the pointer at mouse-up is the one that was there at mouse-down.
function press(find){
 const down=find();assert.ok(down&&down.reachable,"The control can be pressed");
 return {release(){const up=find();return up===down&&down.isConnected?down.click():false;}};
}
async function voice(page){
 page.state.context={process_name:"Supply order",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A weekly count of the supply cupboard starts it."}];
 page.state.memo_findings=[{key:"trigger",status:"partial",answer:"A weekly count of the supply cupboard starts the work.",evidence_turns:["t002"]},
  {key:"purpose",status:"partial",answer:"Keeping the cupboard stocked.",evidence_turns:["t002"]}];
 page.route(()=>({}));
 page.t.conversationUI.live={active:true,connected:true,participantSpeaking:false,assistantSpeaking:true,stop:async()=>({finalized:true}),setMuted(){},appendContext(){return Promise.resolve({status:"acknowledged"});}};
 page.t.tab("interview");page.t.renderTranscript();
 let words=0;const sentence="Thanks. To begin, tell me who places the order and what they check first".split(" ");
 // One provider caption delta: the interviewer's caption grows by a word.
 return ()=>page.t.receiveLiveCaption({id:"live_1",role:"assistant",text:sentence.slice(0,++words).join(" "),final:false});
}
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,6).join("\n     "));}
}
(async()=>{
 const config={agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true}};
 await check("a press on a topic that straddles caption deltas still opens the topic",async()=>{
  const page=await open({config,expose:EXPOSE}),delta=await voice(page);
  for(const key of ["purpose","trigger","volume"]){
   delta();
   const pressed=press(()=>topic(page,key));
   delta();delta(); // the interviewer keeps talking between mouse-down and mouse-up
   assert.equal(pressed.release(),true,key+": the click reaches the button");
   assert.equal(page.$("foundation-dialog").open,true,key+": the topic opens");
   page.t.closeFoundationTopic();
  }
  assert.ok(page.state.turns.at(-1).text.split(" ").length>=9,"The caption really was streaming");
 });
 await check("the sixteen topic buttons are the same elements after any number of re-renders",async()=>{
  const page=await open({config,expose:EXPOSE}),delta=await voice(page);
  const before=page.$("coverage-list").children.slice();assert.equal(before.length,16);
  before[3].focus();
  for(let i=0;i<5;i++)delta();page.t.renderCoverage();page.t.renderTranscript(true);
  const after=page.$("coverage-list").children;
  assert.equal(after.length,16);assert.ok(after.every((node,index)=>node===before[index]),"No button was replaced");
  assert.equal(page.document.activeElement,before[3],"Keyboard focus stays where it was");
  assert.deepEqual(after.map(node=>node.dataset.foundationTopic),["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials","scope","rules","connections","data_systems","volume"]);
  // Space on the focused topic (key-down, a caption, key-up): the element that has focus is still the button.
  delta();assert.equal(page.document.activeElement.click(),true);assert.equal(page.$("foundation-dialog").open,true);
 });
 await check("the same buttons show new notes when the notes change",async()=>{
  const page=await open({config:{agent_team:{enabled:false}},expose:EXPOSE});await voice(page);
  const purpose=topic(page,"purpose"),risk=topic(page,"risk");
  assert.equal(purpose.classList.contains("partial"),true);assert.equal(purpose.querySelector(".coverage-state").textContent,"Needs detail");
  assert.equal(risk.classList.contains("missing"),true);assert.equal(risk.querySelector(".coverage-state").textContent,"");assert.match(risk.title,/^Risks: no detail captured yet/);
  page.state.memo_findings=[{key:"purpose",status:"captured",answer:"Keeping the cupboard stocked.",evidence_turns:["t002"]},
   {key:"risk",status:"partial",answer:"Running out stops the office.",evidence_turns:["t002"]}];
  page.t.renderCoverage();
  assert.equal(topic(page,"purpose"),purpose,"Same element");assert.equal(topic(page,"risk"),risk);
  assert.equal(purpose.classList.contains("covered"),true);assert.equal(purpose.classList.contains("partial"),false);
  assert.equal(purpose.querySelector(".coverage-dot").textContent,"✓");assert.equal(purpose.querySelector(".coverage-state").textContent,"","A covered topic shows its tick and no word");
  assert.equal(purpose.getAttribute("aria-label"),purpose.title);assert.match(purpose.title,/^Purpose: Covered/);
  assert.equal(risk.classList.contains("partial"),true);assert.equal(risk.classList.contains("missing"),false);assert.equal(risk.querySelector(".coverage-state").textContent,"Needs detail");
  assert.equal(topic(page,"trigger").classList.contains("missing"),true,"A topic whose note was withdrawn goes back to empty");
  assert.equal(topic(page,"trigger").querySelector(".coverage-state").textContent,"");
  // The open topic stays marked as selected through re-renders, and loses the mark when it closes.
  page.t.showFoundationTopic("risk",risk);page.t.renderCoverage();assert.equal(risk.classList.contains("selected"),true);assert.equal(purpose.classList.contains("selected"),false);
  page.t.closeFoundationTopic();page.t.renderCoverage();assert.equal(risk.classList.contains("selected"),false);
 });
 await check("a press on a source link in an open topic that straddles caption deltas still opens the source",async()=>{
  const page=await open({config,expose:EXPOSE}),delta=await voice(page);
  page.t.showFoundationTopic("trigger",topic(page,"trigger"));
  const link=()=>page.$("foundation-topic-sources").querySelector(".evidence-link");
  const first=link();assert.ok(first,"The topic lists its source");
  delta();const pressed=press(link);delta();delta();
  assert.equal(link(),first,"The source link was not rebuilt by the captions");
  assert.equal(pressed.release(),true);
  assert.equal(page.$("foundation-dialog").open,false,"The dialog closes for the jump");assert.equal(page.document.activeElement.id,"turn-t002","and the answer it cites has focus");
 });
 await check("the source links of an open topic are rebuilt when its evidence changes",async()=>{
  const page=await open({config,expose:EXPOSE}),delta=await voice(page);
  page.t.showFoundationTopic("trigger",topic(page,"trigger"));
  const sources=page.$("foundation-topic-sources"),links=()=>sources.querySelectorAll(".evidence-link").map(node=>node.dataset.sourceTurn);
  assert.deepEqual(links(),["t002"]);
  page.state.turns.push({id:"t003",role:"user",text:"And a low-stock email from the kitchen."});
  page.state.memo_findings=[{key:"trigger",status:"partial",answer:"A weekly count or a low-stock email starts the work.",evidence_turns:["t002","t003"]}];
  page.t.renderTranscript();
  assert.deepEqual(links(),["t002","t003"],"The new source is listed");assert.equal(page.text("foundation-topic-answer"),"A weekly count or a low-stock email starts the work.");
  // Another topic has its own row.
  page.t.showFoundationTopic("purpose",topic(page,"purpose"));assert.deepEqual(links(),[]);assert.equal(sources.hidden,true);
  page.t.showFoundationTopic("trigger",topic(page,"trigger"));assert.deepEqual(links(),["t002","t003"]);
  delta();assert.deepEqual(links(),["t002","t003"]);
 });
 await check("topic details show concrete early gaps and omit resolved or unasked gaps",async()=>{
  const page=await open({config,expose:EXPOSE}),delta=await voice(page);
  const gap="Who receives the low-stock email when the buyer is away?";
  page.state.factProvenance=page.t.normalizedFacts([{topic:"trigger",kind:"gap",text:gap,evidence_turns:["t002"]}],page.state.turns,[]);
  page.t.showFoundationTopic("trigger",topic(page,"trigger"));
  const panel=page.$("foundation-topic-gaps"),section=panel.querySelector("section");
  assert.match(panel.textContent,/Open in the notes/);assert.ok(panel.textContent.includes(gap));
  delta();assert.equal(panel.querySelector("section"),section,"Captions keep the details in place");
  assert.equal(page.$("coverage-list").textContent.includes(gap),false);
  page.state.factProvenance=[];page.t.renderCoverage();
  assert.match(panel.textContent,/Coverage to check/);assert.ok(!panel.textContent.includes(gap));
  page.t.showFoundationTopic("volume",topic(page,"volume"));
  assert.match(panel.textContent,/Coverage to check/);assert.ok(!panel.textContent.includes("Owner follow-up"));
 });
 await check("reviewed owner handoffs retain scope, action and resolver separately from interview gaps",async()=>{
  const page=await open({config,expose:EXPOSE});await voice(page);
  const row={dimension:"deadlines",kind:"operational_hold",gap:"Bank cutoff is awaiting confirmation.",scope:"Same-day wires",interim_action:"Hold the wire for Treasury.",resolver:"Treasury's current cutoff matrix",evidence_turns:["t002"]};
  const handoff={key:"trigger",ready_for_owner_review:true,owner_followups:[row],gaps:[],next_question:"",complete:false};
  const review={topics:[handoff,{key:"lifecycle",complete:true,gaps:[],next_question:""}]};
  page.state.coverageVerified=true;
  page.t.rememberCoverageCheckpoint(undefined,undefined,undefined,review,{findings:[{material:true,detail:"The return after a rejected payment is missing.",question:"Who receives the rejected payment?"}]});
  page.t.renderCoverage();page.t.showFoundationTopic("trigger",topic(page,"trigger"));
  const panel=page.$("foundation-topic-gaps");
  assert.match(panel.textContent,/For the process owner/);
  for(const value of [row.gap,row.scope,row.interim_action,row.resolver])assert.ok(panel.textContent.includes(value),value);
  assert.ok(!panel.textContent.includes("Open interview gaps"));
  assert.equal(topic(page,"trigger").querySelector(".coverage-state").textContent,"Owner follow-up");
  page.t.showFoundationTopic("lifecycle",topic(page,"lifecycle"));
  assert.match(panel.textContent,/Open interview gaps/);assert.match(panel.textContent,/return after a rejected payment/);
  page.t.showFoundationTopic("trigger",topic(page,"trigger"));
  page.state.turns.push({id:"new",role:"user",text:"Treasury has since changed the cutoff."});
  page.t.renderCoverage();
  assert.ok(!panel.textContent.includes(row.interim_action),"A new answer supersedes the assessment");
  assert.notEqual(topic(page,"trigger").querySelector(".coverage-state").textContent,"Owner follow-up");
  page.state.coverageVerified=false;page.state.savedOwnerFollowups=[{...row,topic:"trigger"}];
  page.t.renderCoverage();
  assert.match(panel.textContent,/Saved owner follow-up · recheck pending/);
  assert.notEqual(page.text("foundation-topic-status"),"Owner follow-up recorded");
 });
 await check("advisory handoffs stay provisional and can coexist with a question for the participant",async()=>{
  const page=await open({config,expose:EXPOSE});await voice(page);
  const finding=page.state.memo_findings[0];finding.status="captured";
  page.state.advisory.trigger={answer:finding.answer,complete:false,gaps:["receiver: Notification recipient for overnight requests is unclear."],next_question:"Who gets an overnight request?",
   owner_followups:[{kind:"external_handoff",gap:"Tax determines the applicable deadline.",scope:"Tax requests",interim_action:"Send intake to Tax.",resolver:"Tax lead"}]};
  page.t.showFoundationTopic("trigger",topic(page,"trigger"));
  const content=page.text("foundation-topic-gaps");
  assert.match(content,/Preliminary gaps/);assert.match(content,/Receiver — Notification recipient/);
  assert.match(content,/Who gets an overnight request/);assert.match(content,/Possible owner follow-up/);
  assert.equal(topic(page,"trigger").querySelector(".coverage-dot").textContent,"");
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
