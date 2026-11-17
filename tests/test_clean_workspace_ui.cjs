"use strict";
// The Workspace panel and the conversation dock say one thing at a time.
//  - Notes shows one status line: each source marks its level and style.css shows the first that
//    reports trouble, then work in progress, then a note, then the rest.
//  - A refresh of the map alone reports in Workflow and leaves the Notes line to the notes.
//  - The topic list is the only list of open topics; the line above Wrap up says why the controls
//    wait or what they are for, and nothing else.
//  - The question card starts at the question; the transcript keeps what was said.
//  - The example offers the way out instead of controls that only wait.
//  - An error that stands on the line above the conversation is not shown a second time as a toast.
// The page of web/index.html runs web/app.js through its own init() (tests/fixtures/app_page.cjs).
// No browser, provider or network.
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const {open}=require("./fixtures/app_page.cjs");
const EXPOSE="renderTranscript,renderCoverage,renderAnalysisThrough,renderAnalysisStatus,renderNextStep,refreshWorkflow,updateControls,notice,tab,selectConversationView,questionCardText,getConcurrentInterview,mapNote";
const KEYS=["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials","scope","rules","connections","data_systems","volume"];
const captured=()=>KEYS.map(key=>({key,status:"captured",answer:`Reported detail for ${key}.`,evidence_turns:["t002"]}));
function interview(page,{typing=true,findings=[]}={}){
 page.state.context={process_name:"Supply order",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A weekly count of the supply cupboard starts it."}];
 page.state.memo_findings=findings;page.t.conversationUI.typing=typing;
 page.t.tab("interview");page.t.selectConversationView(typing?"transcript":"voice");page.t.renderTranscript();page.t.renderCoverage();page.t.updateControls();
}
const level=(page,id)=>page.$(id).dataset.level||"";
const flush=async page=>{for(let index=0;index<6;index++)await page.flush();};
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.stack||error).split("\n").slice(0,6).join("\n     "));}
}
(async()=>{
 const team={agent_team:{enabled:true}},concurrent={...team,concurrent_interview:{enabled:true}};
 await check("the page orders the Notes sources by priority and style.css shows one of them",async()=>{
  const page=await open({config:concurrent,expose:EXPOSE});
  const box=page.document.querySelector(".notes-status");assert.ok(box,"The sources share one container");
  const ids=box.children.map(node=>node.id);
  assert.deepEqual(ids.slice(0,4),["analysis-through","analysis-status","coverage-update-status","coverage-summary"]);
  assert.ok(ids.includes("update-notes"));assert.ok(ids.includes("update-workflow"));
  const css=fs.readFileSync(path.join(__dirname,"..","web","style.css"),"utf8");
  assert.match(css,/\.notes-status > \.coverage-update-status \{ display: none;/,"A source is not shown unless it is picked");
  for(const name of ["issue","busy","info"])assert.match(css,new RegExp(`nth-child\\(1 of \\.coverage-update-status\\[data-level="${name}"\\]`),`${name} has its place in the order`);
  assert.equal(page.document.getElementById("memo-next-action"),null,"No second list of open topics and no \"next topic\" control");
  assert.doesNotMatch(page.$("memo-panel-notes").textContent,/Remaining topics/);
  assert.equal(page.$("memo-tab-summary").textContent.trim(),"Summary");
 });
 await check("the notes background status marks work, trouble and rest, and keeps to the notes",async()=>{
  const page=await open({config:concurrent,modules:["concurrent-interview.js"],expose:EXPOSE});interview(page);
  const notify=status=>{page.t.getConcurrentInterview().notify(status);};
  notify({state:"working"});
  assert.equal(page.text("analysis-status"),"Updating notes…");assert.equal(level(page,"analysis-status"),"busy");
  notify({state:"ready"});
  assert.equal(page.text("analysis-status"),"Notes are up to date.");assert.equal(level(page,"analysis-status"),"");
  assert.doesNotMatch(page.text("analysis-status"),/Wrap up|draft/,"What to do next is said beside the controls, once");
  notify({state:"error"});
  assert.equal(page.text("analysis-status"),"Notes need attention. Wrap up to retry.");assert.equal(level(page,"analysis-status"),"issue");
  // The map alone failed: the notes are fine, the retry is offered where that is said, and while
  // the retry runs the line reports it instead of asking for it again.
  notify({state:"error",scope:"workflow"});
  assert.equal(page.text("analysis-status"),"Notes are up to date. The workflow still needs an update.");
  assert.equal(level(page,"analysis-status"),"issue");assert.equal(page.$("update-workflow").hidden,false);
  page.t.conversationUI.flowBusy=true;page.t.renderAnalysisStatus();
  assert.equal(page.text("analysis-status"),"Notes are up to date. Updating the workflow…");
  assert.equal(level(page,"analysis-status"),"busy");assert.equal(page.$("update-workflow").hidden,true,"The control waits while its own request runs");
  page.t.conversationUI.flowBusy=false;
 });
 await check("before the first answer there are no notes to report on",async()=>{
  const page=await open({config:concurrent,modules:["concurrent-interview.js"],expose:EXPOSE});
  page.state.started=true;page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];page.t.updateControls();
  page.t.getConcurrentInterview().notify({state:"working"});
  assert.equal(page.$("analysis-status").hidden,true);
  page.t.getConcurrentInterview().notify({state:"error"});
  assert.equal(page.$("analysis-status").hidden,false,"A failure is always said");
 });
 await check("the notes line names the answer it has reached, in a form that fits the panel",async()=>{
  const page=await open({config:concurrent,expose:EXPOSE});interview(page);
  page.t.renderAnalysisThrough();
  assert.equal(page.text("analysis-through"),"Updating notes for answer 1");assert.equal(level(page,"analysis-through"),"busy");
 });
 await check("a refresh of the map alone leaves the Notes line alone",async()=>{
  const page=await open({config:team,expose:EXPOSE});interview(page);
  let release;page.route(url=>/workflow/.test(url)?new Promise(resolve=>{release=resolve;}):{});
  page.t.conversationUI.revision=3;page.t.conversationUI.applied=2;
  const run=page.t.refreshWorkflow();await flush(page);
  assert.equal(page.text("workflow-status"),"Updating…");
  assert.equal(page.text("coverage-update-status"),"","With the review team this request brings no notes");
  release({workflow:{title:"Supply order",steps:[],connections:[],open_questions:[]}});await run;await flush(page);
  assert.equal(page.text("workflow-status"),"Up to date");assert.equal(page.text("coverage-update-status"),"");
 });
 await check("the line above Wrap up says why the controls wait or what they are for, and nothing else",async()=>{
  const page=await open({config:team,expose:EXPOSE});interview(page);
  assert.equal(page.$("memo-next").hidden,true,"Open topics are shown by the list");
  page.state.memo_findings=captured();page.state.coverageVerified=false;page.t.renderCoverage();
  assert.equal(page.text("memo-next"),"Every topic is captured. Wrap up for the final check.");assert.equal(page.$("memo-next").hidden,false);
  page.state.coverageVerified=true;page.t.renderCoverage();
  assert.equal(page.text("memo-next"),"Everything’s covered. Create a draft when ready.");
  // A closure state is said in its own line and takes this one's place.
  page.state.closure={asked:true,confirmed:false};page.t.updateControls();
  assert.equal(page.$("closure-status").hidden,false);assert.equal(page.$("memo-next").hidden,true);
  page.state.closure={asked:false,confirmed:false};page.state.memo_findings=[];page.state.coverageVerified=false;
  page.t.conversationUI.live={active:true};page.t.updateControls();
  assert.equal(page.text("memo-next"),"Stop talking to wrap up.");assert.equal(page.$("final-check").disabled,true);
  page.t.conversationUI.live=null;page.t.updateControls();assert.equal(page.$("memo-next").hidden,true);
 });
 await check("the panel does not repeat the question that is on screen",async()=>{
  const page=await open({config:concurrent,expose:EXPOSE});interview(page);
  assert.equal(page.$("memo-focus-block").hidden,true);
  const legacy=await open({config:team,expose:EXPOSE});interview(legacy);legacy.state.focus="Approval thresholds";legacy.t.renderCoverage();
  assert.equal(legacy.$("memo-focus-block").hidden,false);assert.equal(legacy.text("memo-focus"),"Approval thresholds");
 });
 await check("the question card starts at the question; the transcript keeps what was said",async()=>{
  const page=await open({config:team,expose:EXPOSE});interview(page,{typing:false});
  const card=page.t.questionCardText;
  assert.equal(card("Mm. So the capital call begins with the investment team. What do they send you?"),"So the capital call begins with the investment team. What do they send you?");
  assert.equal(card("Okay, got it. who approves the list?"),"Who approves the list?");
  assert.equal(card("Right now, who approves the list?"),"Right now, who approves the list?","A word that only looks like an acknowledgement stays");
  assert.equal(card("Okay."),"Okay.","Nothing is left of a line that is only an acknowledgement, so it is kept");
  assert.equal(card("What starts the work?"),"What starts the work?");
  page.state.turns.push({id:"t003",role:"assistant",text:"Mm-hmm. And who checks the count before the order goes out?"});page.t.renderTranscript();
  assert.equal(page.$("current-question").firstElementChild.textContent,"And who checks the count before the order goes out?");
  assert.match(page.$("transcript").textContent,/Mm-hmm\. And who checks the count/,"The transcript is not edited");
 });
 await check("with the reply box open, voice is the alternative on offer",async()=>{
  const page=await open({config:{...team,api_configured:true,live:{enabled:true}},expose:EXPOSE});interview(page,{typing:false});
  page.t.updateControls();
  assert.equal(page.$("type-instead").hidden,false);assert.equal(page.$("start-live").querySelector("span").textContent,"Continue talking");
  page.t.conversationUI.typing=true;page.t.updateControls();
  assert.equal(page.$("type-instead").hidden,true,"Typing is not offered to someone who is typing");
  assert.equal(page.$("start-live").querySelector("span").textContent,"Talk instead");assert.equal(page.$("live-controls").dataset.typing,"true");
 });
 await check("the example offers the way out instead of controls that only wait",async()=>{
  const page=await open({config:team,expose:EXPOSE});
  assert.equal(page.$("example-start").hidden,true);
  assert.equal(page.$("welcome-example").click(),true);await page.flush();
  assert.equal(page.state.example,true);
  assert.equal(page.$("start-live").hidden,true);assert.equal(page.$("type-instead").hidden,true);assert.equal(page.$("composer-area").hidden,true);
  assert.equal(page.$("example-start").hidden,false);
  assert.equal(page.$("generate-draft").disabled,false,"Its prepared draft can be opened");assert.equal(page.$("generate-draft").textContent,"Open draft");
  assert.equal(page.$("analysis-through").hidden,true,"The banner already says this is the example");
  assert.equal(page.$("example-start").click(),true);await page.flush();
  assert.equal(page.state.example,false);assert.equal(page.$("example-start").hidden,true);assert.equal(page.$("start-live").hidden,false);
 });
 await check("an error that stands on the line above the conversation is not shown twice",async()=>{
  const page=await open({config:team,expose:EXPOSE});interview(page);
  page.t.notice("The notes could not update.",true);
  assert.equal(page.$("interview-error").hidden,false);assert.equal(page.$("global-notice").hidden,false,"The toast keeps its state");
  assert.equal(page.$("global-notice").classList.contains("mirrored"),true,"and is not drawn beside its own copy");
  page.t.notice("Copied.");
  assert.equal(page.$("global-notice").classList.contains("mirrored"),false,"A confirmation has no copy on the page");
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
