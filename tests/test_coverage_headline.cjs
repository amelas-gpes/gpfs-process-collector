"use strict";
// The Notes headline is the figure that advances during an interview: topics captured (or confirmed
// not applicable), whether or not the completion review has run. Whether it has run is said beside
// the number; the tick and the word "Covered" stay reserved for reviewed topics; and there is one
// counter, not three. The page of web/index.html runs web/app.js through its own init()
// (tests/fixtures/app_page.cjs). No browser, provider or network.
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
const headline=page=>({count:page.text("coverage-count"),pill:page.text("coverage-mobile-count"),bar:page.$("coverage-progress").style.width,check:page.text("coverage-check"),label:page.$("coverage-count").parentNode.parentNode.textContent.replace(/\s+/g," ").trim()});
const ticks=page=>KEYS.filter(key=>topic(page,key).querySelector(".coverage-dot").textContent==="✓").length;
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
  assert.equal(shown.count,"13 / 16","Twelve captured and one not applicable");assert.equal(shown.pill,"13/16","The Workspace button of the narrow layout shows the same figure");
  assert.equal(shown.bar,"81.25%");
  assert.equal(shown.check,"","Nothing is marked as checked before the final check");
  assert.match(shown.label,/^Topics captured/);assert.doesNotMatch(shown.label,/fully/,"The label does not claim more than the figure means");
  // Nothing is presented as covered before the review.
  assert.equal(ticks(page),0,"No tick before the final check");
  assert.equal(KEYS.filter(key=>topic(page,key).classList.contains("covered")).length,0);
  assert.equal(topic(page,"name").querySelector(".coverage-state").textContent,"Captured");
  assert.match(topic(page,"name").title,/captured; awaiting review/);
 });
 await check("after the final check the same figure is marked as checked and the topics get their ticks",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,true);
  const shown=headline(page);
  assert.equal(shown.count,"13 / 16");assert.equal(shown.pill,"13/16");assert.equal(shown.check,"Checked","Verification is said beside the number");
  assert.equal(ticks(page),13);assert.equal(topic(page,"name").querySelector(".coverage-state").textContent,"","The tick says it; the row adds no word");
  assert.match(topic(page,"name").title,/Covered$/);
  assert.equal(topic(page,"rules").querySelector(".coverage-state").textContent,"Not applicable");
  assert.equal(topic(page,"connections").classList.contains("partial"),true);assert.equal(topic(page,"volume").classList.contains("missing"),true);
 });
 await check("a new answer withdraws the check, not the progress",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,true);
  page.route(()=>new Promise(()=>{})); // the interviewer has not replied yet
  page.$("answer-text").input("One more thing about the count.");void page.t.sendAnswer({preventDefault(){}});await page.flush();
  const shown=headline(page);
  assert.equal(shown.count,"13 / 16","The bar does not fall back to zero on the next answer");assert.equal(shown.bar,"81.25%");
  assert.equal(shown.check,"","The check mark is withdrawn");assert.equal(ticks(page),0,"The ticks wait for the next check");
 });
 await check("only captured and not-applicable topics count, and an explicit note outranks a coverage flag",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,false);
  page.state.memo_findings=[{key:"name",status:"partial",answer:"Supply order, perhaps.",evidence_turns:["t002"]},{key:"purpose",status:"unknown",answer:"",evidence_turns:[]},
   {key:"trigger",status:"captured",answer:"A weekly count starts it.",evidence_turns:["t002"]}];
  page.state.coverage=[{key:"name",label:"Name and scope",status:"covered"},{key:"purpose",label:"Purpose",status:"covered"},{key:"risk",label:"Risks",status:"covered"},{key:"volume",label:"Volume and effort",status:"partial"}];
  page.t.renderCoverage();
  assert.equal(headline(page).count,"2 / 16","The captured note and the one covered flag that has no note");
  page.state.memo_findings=[];page.state.coverage=[];page.t.renderCoverage();
  const empty=headline(page);assert.equal(empty.count,"0 / 16");assert.equal(empty.bar,"0%");assert.equal(empty.check,"","Nothing captured: nothing to check yet");
 });
 await check("one counter: no second count of captured topics and no count of discussed topics",async()=>{
  const page=await open({config,expose:EXPOSE});interview(page,false);
  assert.equal(page.document.getElementById("discussion-progress"),null,"The page has no separate discussed counter");
  const rail=page.$("memo-panel-notes").textContent;
  assert.doesNotMatch(rail,/topics discussed/);assert.doesNotMatch(rail,/\d+ captured · awaiting review/,"The line under the bar no longer repeats the figure");
  assert.equal(page.$("coverage-summary").hidden,true,"With no advisory detail to add, the line under the bar is not shown");
  // What "discussed" told is on each topic.
  assert.equal(topic(page,"connections").querySelector(".coverage-state").textContent,"Needs detail");
  assert.equal(topic(page,"connections").classList.contains("needs-detail"),true,"The one state a row colours");
  assert.equal(topic(page,"volume").querySelector(".coverage-state").textContent,"","An untouched topic says nothing");
 });
 await check("without the review team there is no check to report and captured topics are simply covered",async()=>{
  const page=await open({config:{agent_team:{enabled:false}},expose:EXPOSE});interview(page,false);
  const shown=headline(page);assert.equal(shown.count,"13 / 16");assert.equal(shown.check,"");assert.equal(ticks(page),13);
 });
 await check("the built-in example shows its sixteen captured topics",async()=>{
  const page=await open({config,expose:EXPOSE});
  assert.equal(page.$("welcome-example").click(),true);await page.flush();
  const shown=headline(page);assert.equal(shown.count,"16 / 16");assert.equal(shown.pill,"16/16");assert.equal(shown.bar,"100%");
  assert.match(shown.check,/^(Checked)?$/);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
