"use strict";
// Findings 3 and 6 of docs/testing/runs/2026-11-16-process-capture, in the actual app with the same fake
// browser boundary as the concurrent suite: Wrap up releases the synchronized notes while the map
// keeps its own status and retry, and an accepted map ends an earlier map failure in both panels.
// No network, provider or physical audio.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
let harness=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(harness.includes("function setup()"));
harness=harness.replace('const controlled=', 'const concurrent=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");\nconst controlled=');
harness=harness.replace('updateControls=()=>{updatePresence();};', 'updateControls=()=>{updatePresence();}; renderCoverage=()=>{}; renderWorkingMap=()=>{}; updateSaveHint=()=>{}; updateConversationControls=()=>{}; updateDocumentIntakeUI=()=>{};');
harness=harness.replace('setTeam:value=>', 'applyBackgroundCapture,applyLateWorkflow,settleMapStatus,publishWorkingMap,submissionCaptureState,analysis:()=>analysisState,controller:()=>concurrentInterview,setTeam:value=>');
harness=harness.replace('vm.runInContext(controlled,context,', 'vm.runInContext(concurrent,context,{filename:"concurrent-interview.js"});vm.runInContext(controlled,context,');
harness+='\nmodule.exports={setup,approved,response,flush,deferred};';
const exported={exports:{}};
vm.runInNewContext(harness,{require,__dirname,module:exported,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException},{filename:"wrap-up-map-harness.cjs"});
const {setup,approved,response,flush,deferred}=exported.exports;
const REVISION="cd".repeat(32);
const map=title=>({workflow:{title,steps:[{id:"s1",title:"Receive the request",type:"activity",evidence_turns:["u1"]}],connections:[],open_questions:[]}});
function ready(){
 const h=setup();h.t.state.config.concurrent_interview={enabled:true};h.t.state.config.api_configured=true;
 h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts this work?"},{id:"u1",role:"user",text:"A clerk receives the request."}];
 return h;
}
// What Wrap up returns once the notes are synchronized: the review acknowledgement is not needed here.
const synchronized=extra=>({...approved("What remains to be explained?"),summary:"Synchronized notes",memo_findings:[],coverage:[],conversation_token:"session-one",revision:REVISION,...extra});
let passed=0;async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
(async()=>{
await check("wrap up shows the synchronized notes while the map is still being drawn, then takes the map alone",async()=>{
 const h=ready(),status=deferred();
 h.route(url=>url==="/api/conversation/sync"?response(synchronized({workflow_state:"working",workflow_pending:true})):
  url==="/api/conversation/status"?status.promise:Promise.reject(Error(url)));
 const result=await h.t.request("/api/interview",{...h.t.snapshot(),action:"close"});
 assert.equal(result.summary,"Synchronized notes","Wrap up returned without waiting for the map");
 assert.equal(h.t.analysis().state,"ready");assert.match(h.node("analysis-status").textContent,/^Notes are up to date/);
 assert.equal(h.node("workflow-status").textContent,"Updating the map for your latest answer…");
 assert.equal(h.t.controller().active,true,"The map of this revision is still being fetched");
 assert.match(h.t.submissionCaptureState().waiting||"",/working map are still updating/,"Submit waits for the map as before");
 // The review that follows sets its own state; a late map must not disturb it.
 h.t.state.summary="Synchronized notes";h.t.state.coverageVerified=true;h.t.state.closure={asked:true,confirmed:false};h.t.state.completion={ready_for_final_check:true};
 await h.timer(650);assert.equal(h.calls.at(-1).url,"/api/conversation/status");
 assert.equal(JSON.stringify(JSON.parse(h.calls.at(-1).options.body)),JSON.stringify({conversation_token:"session-one",revision:REVISION}));
 status.resolve(response({state:"ready",conversation_token:"session-one",revision:REVISION,workflow_state:"ready",
  capture:{...approved("unused"),summary:"Background notes that must not replace the review",memo_findings:[],coverage:[]},workflow_capture:map("Request intake")}));await flush();
 assert.equal(h.t.conversationUI.workflow.title,"Request intake");
 assert.equal(h.node("workflow-status").textContent,"Updated through the latest answer");
 assert.equal(h.t.state.summary,"Synchronized notes","Only the map is taken from the poll");
 assert.equal(h.t.state.coverageVerified,true);assert.equal(h.t.state.closure.asked,true);assert.equal(h.t.state.completion.ready_for_final_check,true);
 assert.equal(h.t.controller().active,false);assert.equal(h.t.analysis().state,"ready");
});
await check("a map that failed is the workflow's failure with its own retry; notes say they are up to date",async()=>{
 const h=ready();
 h.route(url=>url==="/api/conversation/sync"?response(synchronized({workflow_state:"error",workflow_pending:false,workflow_error:"The provider timed out. Your answers are retained."})):Promise.reject(Error(url)));
 const result=await h.t.request("/api/interview",{...h.t.snapshot(),action:"close"});
 assert.equal(result.summary,"Synchronized notes","A map failure preserves the notes and the transcript");
 assert.equal(h.t.state.turns.length,2);
 assert.equal(h.t.analysis().scope,"workflow");
 assert.match(h.node("analysis-status").textContent,/^Notes are up to date\. The workflow still needs an update/);
 assert.doesNotMatch(h.node("analysis-status").textContent,/timed out|need attention/,"The map's failure is not shown as a failure of the notes");
 assert.equal(h.node("workflow-status").textContent,"The provider timed out. Your answers are retained.");
 assert.equal(h.node("retry-workflow").hidden,false);assert.equal(h.node("retry-workflow").dataset.mapOnly,"true");
 assert.equal(h.node("retry-workflow").textContent,"Update workflow");
});
await check("an accepted map ends the earlier map failure in both panels",async()=>{
 const h=ready();
 h.route(url=>url==="/api/conversation/sync"?response(synchronized({workflow_state:"error",workflow_pending:false,workflow_error:"The workflow could not update. Your answers are retained."})):Promise.reject(Error(url)));
 await h.t.request("/api/interview",{...h.t.snapshot(),action:"close"});
 assert.equal(h.t.analysis().state,"error");
 // The retry succeeded: the accepted map of the current answers arrives.
 h.t.applyLateWorkflow(map("Request intake"),h.t.snapshot());
 assert.equal(h.t.analysis().state,"ready","The failure is history once the retry is accepted");
 assert.match(h.node("analysis-status").textContent,/^Notes are up to date/);
 assert.doesNotMatch(h.node("analysis-status").textContent,/workflow still needs|could not update|timed out/);
 assert.equal(h.node("workflow-status").textContent,"Updated through the latest answer");
 assert.equal(h.node("retry-workflow").hidden,true);
 // A failure of the notes themselves is not cleared by a map.
 const notes=ready();
 notes.route(url=>url==="/api/conversation/turn"?response({...approved("Who receives it next?"),preserve_capture:true,conversation_token:"session-one",revision:"r1"}):
  url==="/api/conversation/status"?response({state:"error",conversation_token:"session-one",revision:"r1",error:"The provider timed out. Your answers are retained."}):Promise.reject(Error(url)));
 await notes.t.request("/api/interview",{...notes.t.snapshot(),action:"answer"});await notes.timer(650);
 assert.equal(notes.t.analysis().state,"error");assert.equal(notes.t.analysis().scope,undefined);
 notes.t.settleMapStatus();assert.equal(notes.t.analysis().state,"error");
 assert.equal(notes.node("analysis-status").textContent,"The provider timed out. Your answers are retained.");
});
await check("a map failure during the interview is scoped to the workflow as well",async()=>{
 const h=ready();
 h.route(url=>url==="/api/conversation/turn"?response({...approved("Who receives it next?"),preserve_capture:true,conversation_token:"session-one",revision:"r1"}):
  url==="/api/conversation/status"?response({state:"ready",conversation_token:"session-one",revision:"r1",workflow_state:"error",workflow_error:"The provider timed out. Your answers are retained.",
   capture:{...approved("unused"),summary:"Captured answer",memo_findings:[],coverage:[]}}):Promise.reject(Error(url)));
 await h.t.request("/api/interview",{...h.t.snapshot(),action:"answer"});await h.timer(650);
 assert.equal(h.t.state.summary,"Captured answer");assert.equal(h.t.analysis().scope,"workflow");
 assert.match(h.node("analysis-status").textContent,/^Notes are up to date\. The workflow still needs an update/);
 assert.equal(h.node("retry-workflow").dataset.mapOnly,"true");
 h.t.applyLateWorkflow(map("Request intake"),h.t.snapshot());
 assert.equal(h.t.analysis().state,"ready");assert.match(h.node("analysis-status").textContent,/^Notes are up to date/);
});
await check("a late map for answers that have since changed is not applied",async()=>{
 const h=ready(),captured=h.t.snapshot();
 h.t.state.turns[1].text="Rewritten: the manager receives the request.";
 h.t.applyLateWorkflow(map("Stale map"),captured);
 assert.notEqual(h.t.conversationUI.workflow?.title,"Stale map");
});
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
