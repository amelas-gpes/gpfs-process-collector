"use strict";
// Topic coverage advances with capture. Visible labels distinguish pending and reviewed topics.
// The fixture runs web/index.html and web/app.js together without provider or network calls.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="renderTranscript,renderCoverage,sendAnswer,tab,selectConversationView";
const KEYS=["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials","scope","rules","connections","data_systems","volume"];
// Twelve topics captured, one confirmed not applicable, one partly answered, two untouched.
const notes=()=>KEYS.slice(0,14).map((key,index)=>({key,evidence_turns:["t002"],
 status:index<12?"captured":index===12?"not_applicable":"partial",
 answer:index===12?"The participant confirmed that this does not apply to the work.":`Reported detail for ${key}.`}));
function interview(page,verified){
 page.state.context={process_name:"Supply order",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A weekly count of the supply cupboard starts it."}];
 page.state.memo_findings=notes();page.state.coverageVerified=verified;
 page.t.conversationUI.typing=true;page.t.tab("interview");page.t.selectConversationView("transcript");page.t.renderTranscript();
}
const topic=(page,key)=>page.document.querySelector(`[data-foundation-topic="${key}"]`);
function headline(page){
 const meter=page.$("coverage-meter");
 return {
  count:page.text("coverage-count"),pill:page.text("coverage-mobile-count"),fraction:page.text("coverage-fraction"),
  arcOffset:page.$("coverage-progress").style.strokeDashoffset,check:page.text("coverage-check"),
  label:meter.getAttribute("aria-label")||page.text(meter.getAttribute("aria-labelledby")),
  value:meter.getAttribute("aria-valuenow"),valueText:meter.getAttribute("aria-valuetext")
 };
}
const withState=(page,state)=>KEYS.filter(key=>topic(page,key).dataset.topicState===state);
const label=(page,key)=>topic(page,key).querySelector(".coverage-state").textContent;
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,6).join("\n     "));}
}
(async()=>{
 const config={agent_team:{enabled:true}};
 await check("before the final check the headline already counts what has been captured",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,false);
  const shown=headline(page);
  assert.equal(shown.count,"81%","Twelve captured and one not applicable");assert.equal(shown.pill,"81%","The Workspace button of the narrow layout shows the same figure");
  assert.equal(shown.arcOffset,"18.75");
  assert.equal(shown.fraction,"13 of 16 topics captured · 1 partly covered","The topic that holds part of an answer is counted beside the figure, not in it");
  assert.equal(page.$("coverage-meter").getAttribute("role"),"progressbar");
  assert.equal(shown.value,"81");assert.equal(shown.valueText,"13 of 16 topics captured · 1 partly covered (81%)");
  assert.deepEqual(withState(page,"captured"),KEYS.slice(0,12));assert.deepEqual(withState(page,"notApplicable"),["rules"]);
  assert.equal(shown.check,"","Nothing is marked as checked before the final check");
  assert.equal(shown.label,"Topic coverage");
  // Nothing is presented as covered before the review.
  assert.equal(withState(page,"covered").length,0);
  assert.equal(label(page,"name"),"Captured");
  assert.match(topic(page,"name").title,/Final coverage check pending/);
 });
 await check("after the final check the same figure is marked as checked and the topics are labeled",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,true);
  const shown=headline(page);
  assert.equal(shown.count,"81%");assert.equal(shown.pill,"81%");assert.equal(shown.check,"Checked","Verification is said beside the number");
  assert.deepEqual(withState(page,"covered"),KEYS.slice(0,12));assert.equal(label(page,"name"),"Covered");
  assert.equal(label(page,"rules"),"Not applicable");
  assert.equal(label(page,"connections"),"Needs detail");assert.equal(label(page,"volume"),"Not covered");
 });
 await check("a captured topic with a follow-up gap remains identifiable among partial and empty topics",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,false);
  const emptyKeys=["name","risk"];
  page.state.memo_findings=KEYS.map(key=>({key,
   status:emptyKeys.includes(key)?"unknown":key==="purpose"?"captured":"partial",
   answer:emptyKeys.includes(key)?"":`Recorded detail for ${key}.`,evidence_turns:emptyKeys.includes(key)?[]:["t002"]
  }));
  page.state.advisory.purpose={answer:"Recorded detail for purpose.",complete:false,gaps:["Clarify the result."]};
  page.t.renderCoverage();
  assert.equal(headline(page).count,"6%");assert.equal(withState(page,"covered").length,0);
  assert.equal(headline(page).fraction,"1 of 16 topics captured · 13 partly covered","Thirteen topics with notes and a gap are not shown as nothing");
  assert.equal(label(page,"purpose"),"Needs detail");assert.match(topic(page,"purpose").title,/Clarify the result/);
  assert.equal(withState(page,"detail").length,14);
  assert.equal(label(page,"trigger"),"Needs detail");
  assert.deepEqual(withState(page,"open"),emptyKeys);
  page.state.coverageVerified=true;page.t.renderCoverage();
  assert.deepEqual(withState(page,"covered"),["purpose"]);
 });
 await check("a new answer withdraws the check, not the progress",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,true);
  page.route(()=>new Promise(()=>{})); // the interviewer has not replied yet
  page.$("answer-text").input("One more thing about the count.");void page.t.sendAnswer({preventDefault(){}});await page.flush();
  const shown=headline(page);
  assert.equal(shown.count,"81%","The percentage stays current on the next answer");assert.equal(shown.arcOffset,"18.75");
  assert.equal(shown.check,"","The check is withdrawn");assert.equal(withState(page,"covered").length,0);
 });
 await check("only captured and not-applicable topics count, and an explicit note outranks a coverage flag",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,false);
  page.state.memo_findings=[{key:"name",status:"partial",answer:"Supply order, perhaps.",evidence_turns:["t002"]},{key:"purpose",status:"unknown",answer:"",evidence_turns:[]},
   {key:"trigger",status:"captured",answer:"A weekly count starts it.",evidence_turns:["t002"]}];
  page.state.coverage=[{key:"name",label:"Name and scope",status:"covered"},{key:"purpose",label:"Purpose",status:"covered"},{key:"risk",label:"Risks",status:"covered"},{key:"volume",label:"Volume and effort",status:"partial"}];
  page.t.renderCoverage();
  assert.equal(headline(page).count,"13%","The captured note and the one covered flag that has no note");
  page.state.memo_findings=[];page.state.coverage=[];page.t.renderCoverage();
  const empty=headline(page);
  assert.equal(empty.count,"0%");assert.equal(empty.pill,"0%");assert.equal(empty.arcOffset,"100");
  assert.equal(empty.value,"0");assert.equal(empty.valueText,"0 of 16 topics captured (0%)");assert.equal(empty.check,"");
 });
 await check("the progress summary counts each captured topic once and leaves discussion detail on the rows",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,false);
  assert.equal(page.document.getElementById("discussion-progress"),null,"The page has no separate discussed counter");
  const rail=page.$("memo-panel-notes").textContent;
  assert.doesNotMatch(rail,/topics discussed/);assert.doesNotMatch(rail,/\d+ captured · awaiting review/,"The line under the bar no longer repeats the figure");
  assert.equal(page.$("coverage-summary").hidden,true,"With no advisory detail to add, the line under the bar is not shown");
  // What "discussed" told is on each topic.
  assert.equal(label(page,"connections"),"Needs detail");
  assert.equal(label(page,"volume"),"Not covered");
 });
 await check("without the review team there is no check to report and captured topics are simply covered",async()=>{
  const page=await open({config:{agent_team:{enabled:false}},expose:EXPOSE});interview(page,false);
  const shown=headline(page);assert.equal(shown.count,"81%");assert.equal(shown.check,"");assert.equal(withState(page,"covered").length,12);
 });
 await check("the built-in example shows its sixteen captured topics",async()=>{
  const page=await open({config,expose:EXPOSE});
  assert.equal(page.$("welcome-example").click(),true);await page.flush();
  const shown=headline(page);assert.equal(shown.count,"100%");assert.equal(shown.pill,"100%");assert.equal(shown.arcOffset,"0");
  assert.equal(shown.value,"100");assert.equal(shown.valueText,"16 of 16 topics captured (100%)");
  assert.match(shown.check,/^(Checked)?$/);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
