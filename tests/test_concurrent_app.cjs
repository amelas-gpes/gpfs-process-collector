"use strict";
// Exercise the actual app transport/state with the same fake browser/media
// boundary as the existing experience suite. No network or physical audio.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
let harness=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(harness.includes("function setup()"));
harness=harness.replace('const controlled=', 'const concurrent=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");\nconst controlled=');
harness=harness.replace('updateControls=()=>{updatePresence();};', 'const realUpdateControls=updateControls; updateControls=()=>{updatePresence();}; renderCoverage=()=>{}; renderWorkingMap=()=>{}; updateSaveHint=()=>{}; updateConversationControls=()=>{}; updateDocumentIntakeUI=()=>{};');
harness=harness.replace('setTeam:value=>', 'finalCheck,applyBackgroundCapture,applyProcessTitle,sessionObject,transcriptObject,checkControls:realUpdateControls,resetConcurrent:()=>concurrentInterview?.reset(),setTeam:value=>');
harness=harness.replace('vm.runInContext(controlled,context,', 'vm.runInContext(concurrent,context,{filename:"concurrent-interview.js"});vm.runInContext(controlled,context,');
harness+='\nmodule.exports={setup,approved,response,flush,deferred};';
const exported={exports:{}};
vm.runInNewContext(harness,{require,__dirname,module:exported,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException},{filename:"concurrent-app-harness.cjs"});
const {setup,approved,response,flush,deferred}=exported.exports;
const fast=()=>({...approved("Who receives it next?"),preserve_capture:true,conversation_token:"session-one",revision:"r1"});
function readyCapture(summary="Captured answer"){
 return {state:"ready",revision:"r1",conversation_token:"session-one",capture:{...approved("This analysis question must not be spoken"),summary,memo_findings:[],coverage:[],completion:{complete:true,ready_for_final_check:true},coverage_verified:true,closure:{asked:true,confirmed:true}}};
}
function concurrentSetup(){const h=setup();h.t.state.config.concurrent_interview={enabled:true};h.t.state.config.api_configured=true;h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts this work?"}];return h;}
let passed=0;async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
(async()=>{
await check("typed answer receives fast question before background analysis",async()=>{
 const h=concurrentSetup(),analysis=deferred();h.route(url=>url==="/api/conversation/turn"?response(fast()):url==="/api/conversation/status"?analysis.promise:Promise.reject(Error(url)));
 h.node("answer-text").value="A clerk receives the request.";await h.t.sendAnswer({preventDefault(){}});
 assert.equal(h.t.state.busy,false);assert.equal(h.t.state.turns.at(-1).text,fast().question);assert.equal(h.calls[0].url,"/api/conversation/turn");assert.equal(h.t.state.summary,"");
 await h.timer(650);const before=h.t.state.turns.length;analysis.resolve(response(readyCapture()));await flush();
 assert.equal(h.t.state.summary,"Captured answer");assert.equal(h.t.state.turns.length,before);assert.equal(h.t.state.turns.at(-1).text,fast().question);assert.equal(h.t.state.coverageVerified,false);assert.equal(h.t.state.completion,null);assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.sockets.length,0);assert.equal(h.utterances.length,0);
});
await check("voice answer uses fast path and listens while analysis is pending",async()=>{
 const h=concurrentSetup(),analysis=deferred();h.t.state.voiceChoice="local:synthetic";h.t.state.voice={name:"Synthetic",lang:"en-US"};
 h.route(url=>url==="/api/transcribe"?response({text:"The clerk records the request."}):url==="/api/conversation/turn"?response(fast()):url==="/api/conversation/status"?analysis.promise:Promise.reject(Error(url)));
 await h.t.startLiveConversation();await h.say();assert.ok(h.calls.some(call=>call.url==="/api/conversation/turn"));assert.equal(h.calls.some(call=>call.url==="/api/agent-team/interview"),false);assert.equal(h.utterances.length,1);h.utterances[0].onend();await flush();assert.equal(h.t.conversationUI.status,"listening");assert.equal(h.track.enabled,true);
 await h.timer(650);analysis.resolve(response(readyCapture("Background voice notes")));await flush();assert.equal(h.t.state.summary,"Background voice notes");assert.equal(h.t.conversationUI.status,"listening");assert.equal(h.utterances.length,1);await h.t.conversationUI.live.stop();
});
await check("wrap up uses synchronization even while capture is incomplete",async()=>{
 const h=concurrentSetup(),sync=deferred();h.t.state.turns.push({id:"t002",role:"user",text:"The clerk reviews it."});
 h.node("start-interview").firstElementChild={textContent:""};h.t.checkControls();assert.equal(h.node("final-check").disabled,false);
 h.route(url=>url==="/api/conversation/sync"?sync.promise:Promise.reject(Error(url)));const wrapping=h.t.finalCheck();await flush();assert.equal(h.calls[0].url,"/api/conversation/sync");assert.equal(h.t.state.busy,true);
 sync.resolve(response({...fast(),question:"Which exception still needs explaining?",speech_authorization:{...fast().speech_authorization,text:"Which exception still needs explaining?"}}));await wrapping;assert.equal(h.t.state.busy,false);assert.equal(h.t.state.turns.at(-1).text,"Which exception still needs explaining?");assert.equal(h.t.state.closure.confirmed,false);
});
await check("generation change and reset discard a late background capture",async()=>{
 const h=concurrentSetup(),analysis=deferred();h.route(url=>url==="/api/conversation/turn"?response(fast()):analysis.promise);await h.t.request("/api/interview",{...h.t.snapshot(),action:"answer"});await h.timer(650);h.t.state.generation++;h.t.resetConcurrent();analysis.resolve(response(readyCapture("Stale notes")));await flush();assert.equal(h.t.state.summary,"");assert.equal(h.t.state.turns.length,1);assert.equal(h.calls[1].options.signal.aborted,true);
});
await check("a new participant correction blocks an older capture",async()=>{
 const h=concurrentSetup(),analysis=deferred();h.route(url=>url==="/api/conversation/turn"?response(fast()):analysis.promise);await h.t.request("/api/interview",{...h.t.snapshot(),action:"answer"});await h.timer(650);h.t.state.turns.push({id:"correction",role:"user",text:"Actually the supervisor receives it."});analysis.resolve(response(readyCapture("Old claim")));await flush();assert.equal(h.t.state.summary,"");assert.equal(h.t.state.turns.at(-1).id,"correction");
});
await check("a fast wrap signal synchronizes before it can reach transcript or speech",async()=>{
 const h=concurrentSetup(),sync=deferred();h.route(url=>url==="/api/conversation/turn"?response({conversation_token:"session-one",sync_required:true,question:"",revision:"r1"}):url==="/api/conversation/sync"?sync.promise:Promise.reject(Error(url)));
 const pending=h.t.request("/api/interview",{...h.t.snapshot(),action:"answer"});await flush();assert.equal(h.calls.length,2);assert.equal(h.calls[1].url,"/api/conversation/sync");assert.equal(h.t.state.turns.length,1);sync.resolve(response(fast()));const result=await pending;assert.equal(result.question,fast().question);assert.equal(h.t.state.turns.length,1);
});
await check("background workflow names the process without changing source identity",async()=>{
 const h=concurrentSetup();h.t.state.context.process_name="";const result=readyCapture();result.workflow_state="ready";result.workflow_capture={workflow:{title:"Drone setup",steps:[],connections:[],open_questions:[]}};
 h.route(url=>url==="/api/conversation/turn"?response(fast()):url==="/api/conversation/status"?response(result):Promise.reject(Error(url)));
 h.node("answer-text").value="I would like to talk about how I set up my drone.";await h.t.sendAnswer({preventDefault(){}});const source=JSON.stringify(h.t.snapshot().context),turns=h.t.state.turns.length;
 await h.timer(650);assert.equal(h.node("process-name").value,"Drone setup");assert.equal(h.t.state.derivedProcessTitle,"Drone setup");assert.equal(JSON.stringify(h.t.snapshot().context),source);assert.equal(h.t.state.turns.length,turns);assert.equal(h.t.transcriptObject().process.name,"Drone setup");assert.equal(h.t.sessionObject().derived_process_title,"Drone setup");assert.equal(h.t.sessionObject().context.process_name,"");
});
await check("automatic title refinement cannot stale an in-flight fast question",async()=>{
 const h=concurrentSetup(),question=deferred();h.t.state.context.process_name="";h.t.state.turns.push({id:"u1",role:"user",text:"I set up my drone."});h.route(()=>question.promise);
 const pending=h.t.request("/api/interview",{...h.t.snapshot(),action:"answer"});await flush();h.t.applyProcessTitle("Drone setup");question.resolve(response(fast()));const result=await pending;
 assert.equal(result.question,fast().question);assert.equal(h.t.snapshot().context.process_name,"");assert.equal(h.t.state.derivedProcessTitle,"Drone setup");
});
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
