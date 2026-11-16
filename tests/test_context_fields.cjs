"use strict";
// Interview context (process owner, goal, background): discoverable before the interview starts,
// the process owner correctable afterwards, and the lock on goal and background explained where
// it applies. The page of web/index.html runs web/app.js through its own init()
// (tests/fixtures/app_page.cjs). No browser, provider or network.
const assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="renderTranscript,updateControls,sendAnswer,snapshot,markdown,importSession,sessionObject,setInterviewSettings,tab,selectConversationView,renderDraft,normalizeDraft";
const ACK="Let me check that I have everything before we finish.";
const question=(text,kind="question",extra={})=>({question:text,summary:"",focus:"",parking_lot:[],memo_findings:[],coverage:[],
 completion:{ready_for_final_check:kind==="final_check",complete:false},closure:{asked:kind==="final_check",confirmed:false},
 speech_authorization:{approved:true,kind,text,revision:"r1",completion_allowed:false},coverage_verified:kind==="final_check",...extra});
const lockNote=page=>page.text("context-lock-note");
// Starts a typed interview as a person does: Type instead, then one answer.
async function started(page){
 page.route(url=>url==="/api/agent-team/interview"?question("What starts the work?"):{});
 assert.equal(page.$("type-instead").click(),true);await page.flush();
 page.$("answer-text").input("Every Monday I count the supply cupboard.");
 await page.t.sendAnswer({preventDefault(){}});await page.flush();
 assert.equal(page.state.started,true);assert.equal(page.state.turns.filter(turn=>turn.role==="user").length,1);
}
const openContext=page=>{assert.equal(page.$("open-context").click(),true,"Context is accessible from the navbar");};
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,6).join("\n     "));}
}
(async()=>{
 const config={agent_team:{enabled:true}};
 await check("Context in the navbar opens the three fields and restores keyboard focus when closed",async()=>{
  const page=await open({config,expose:EXPOSE});
  const link=page.$("open-context");
  assert.equal(link.visible,true);assert.equal(link.textContent.trim(),"Context");
  assert.ok(link.closest("nav"),"Context is in the navbar");
  assert.equal(link.getAttribute("aria-haspopup"),"dialog");
  assert.equal(link.getAttribute("aria-controls"),"interview-settings");
  link.focus();openContext(page);
  assert.equal(page.$("interview-settings").open,true);assert.equal(page.$("context-details").open,true,"Interview context is unfolded");
  assert.equal(page.document.activeElement,page.$("process-owner"),"The first field has focus");
  for(const id of ["process-owner","objective","background"])assert.equal(page.$(id).disabled,false,id+" can be filled in");
  assert.match(lockNote(page),/Goal and background lock when the interview starts/);
  // What is typed there is what the interview starts with.
  page.$("process-owner").input("Office manager");page.$("background").input("Shared cupboard on the second floor.");
  page.$("close-interview-settings").click();
  assert.equal(page.document.activeElement,link,"Closing returns focus to Context");
  await started(page);
  assert.equal(page.state.context.process_owner,"Office manager");assert.equal(page.state.context.background,"Shared cupboard on the second floor.");
 });
 await check("after the start the process owner can still be corrected; goal and background say why they cannot",async()=>{
  const page=await open({config,expose:EXPOSE});await started(page);
  assert.equal(page.$("open-context").visible,true,"The navbar action remains available during an interview");
  openContext(page);
  assert.equal(page.$("process-owner").disabled,false,"Process owner stays editable");
  assert.equal(page.$("objective").disabled,true);assert.equal(page.$("background").disabled,true);
  assert.equal(page.shown("context-lock-note"),true,"The reason is beside the locked fields");
  assert.match(lockNote(page),/Goal and background are locked once the interview starts; add corrections as an answer\./);
  assert.match(lockNote(page),/Process owner can still be changed/);
  for(const id of ["objective","background"])assert.ok(page.$(id).getAttribute("aria-describedby").split(/\s+/).includes("context-lock-note"),id+" is described by the reason");
  const version=page.state.version;page.state.dirty=false;
  page.$("process-owner").input("  Office manager ");
  assert.equal(page.state.context.process_owner,"Office manager");
  assert.ok(page.state.version>version,"The edit moves the request guard, as a title edit does");assert.equal(page.state.dirty,true);
  assert.equal(page.t.snapshot().context.process_owner,"Office manager","The next request carries the corrected owner");
  assert.equal(page.state.context.objective,"Understand the current process, responsibilities, handoffs, and exceptions.","Goal untouched");
  // Clearing it is a correction too.
  page.$("process-owner").input("");assert.equal(page.state.context.process_owner,"");
 });
 await check("the corrected owner reaches the report and the Markdown export",async()=>{
  const page=await open({config,expose:EXPOSE});await started(page);
  page.state.draft=page.t.normalizeDraft({title:"Supply order",summary:"A weekly count.",steps:[],connections:[],open_questions:[]},page.state.turns,[]);
  page.t.renderDraft();page.t.tab("review");
  assert.match(page.t.markdown(),/Process owner \/ role:\*{0,2} UNKNOWN \/ TBD/);
  openContext(page);page.$("process-owner").input("Office manager");
  assert.match(page.t.markdown(),/Process owner \/ role:\*{0,2} Office manager/);
  assert.match(page.text("report-content"),/Process owner \/ role\s*Office manager/,"The report on screen is redrawn with it");
 });
 await check("an owner correction invalidates a completion review that is running, as other context edits do",async()=>{
  const page=await open({config,expose:EXPOSE});await started(page);
  let finish;
  page.route(url=>{
   if(url==="/api/agent-team/interview")return question(ACK,"review_pending",{capture_token:"token-ack",review_ticket:"ticket-one",agent_run_id:"run-one"});
   if(url==="/api/agent-team/review")return new Promise(resolve=>{finish=resolve;});
   return {};
  });
  page.$("answer-text").input("That is everything.");const sending=page.t.sendAnswer({preventDefault(){}});await page.flush();
  assert.equal(typeof finish,"function","The review is running");
  openContext(page);page.$("process-owner").input("Office manager");
  finish(page.reply(question("Is there anything I have missed?","final_check",{capture_token:"token-final"})));await sending;await page.flush();
  assert.equal(page.state.coverageVerified,false,"A review of the earlier context is not applied");
  assert.notEqual(page.state.turns.at(-1).text,"Is there anything I have missed?");assert.equal(page.state.closure.asked,false);
 });
 await check("a reopened interview can have its owner corrected",async()=>{
  const page=await open({config,expose:EXPOSE});await started(page);
  const saved=JSON.stringify(page.t.sessionObject());
  await page.t.importSession({size:saved.length,text:async()=>saved});await page.flush();
  assert.equal(page.state.started,true);openContext(page);
  assert.equal(page.$("process-owner").disabled,false);assert.equal(page.$("objective").disabled,true);
  page.$("process-owner").input("Facilities lead");assert.equal(page.state.context.process_owner,"Facilities lead");
  assert.equal(JSON.parse(JSON.stringify(page.t.sessionObject())).context.process_owner,"Facilities lead","Save copy keeps it");
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
