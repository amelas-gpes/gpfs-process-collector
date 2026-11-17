"use strict";
// Exercise the actual app transport/state with the same fake browser/media
// boundary as the existing experience suite. No network or physical audio.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
let harness=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(harness.includes("function setup()"));
harness=harness.replace('const controlled=', 'const concurrent=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");\nconst controlled=');
harness=harness.replace('updateControls=()=>{updatePresence();};', 'const realUpdateControls=updateControls; updateControls=()=>{updatePresence();}; renderCoverage=()=>{}; renderWorkingMap=()=>{}; updateSaveHint=()=>{}; updateConversationControls=()=>{}; updateDocumentIntakeUI=()=>{};');
harness=harness.replace('setTeam:value=>', 'finalCheck,runLiveCapture,applyBackgroundCapture,sessionObject,transcriptObject,checkControls:realUpdateControls,resetConcurrent:()=>concurrentInterview?.reset(),setTeam:value=>');
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
await check("live voice captures use the managed team even with concurrent interviewing enabled",async()=>{
 const h=concurrentSetup();h.t.state.config.agent_team.voice_mode="live_front";
 h.t.conversationUI.live={active:true,updateCoverage(){}};
 h.t.state.turns.push({id:"live-user",role:"user",text:"The clerk records the request."});
 h.route(url=>url==="/api/agent-team/interview"?response({...approved(),summary:"Full live capture",coverage:[],memo_findings:[],capture_token:"live-capture"}):url==="/api/agent-team/status"?response({status:"completed",agents:[],events:[]}):Promise.reject(Error(url)));
 await h.t.runLiveCapture();assert.equal(h.calls[0].url,"/api/agent-team/interview");assert.equal(h.calls.some(call=>call.url.startsWith("/api/conversation/")),false);
 assert.equal(h.t.state.summary,"Full live capture");assert.equal(h.t.state.captureToken,"live-capture");
 assert.equal(h.t.state.liveSuggestedQuestion,"");assert.equal(h.t.state.turns.at(-1).id,"live-user");
});
for(const restarting of [false,true])await check("starting or resuming live voice cancels a prior concurrent capture",async()=>{
 const h=concurrentSetup(),analysis=deferred();h.route(url=>url==="/api/conversation/turn"?response(fast()):url==="/api/conversation/status"?analysis.promise:Promise.reject(Error(url)));
 await h.t.request("/api/interview",{...h.t.snapshot(),action:"answer"});await h.timer(650);
 h.t.state.config.agent_team.voice_mode="live_front";
 h.window.CollectorLiveVoice=class{async start(){this.active=true;}updateCoverage(){}};
 if(restarting)h.t.conversationUI.live=new h.window.CollectorLiveVoice();
 await h.t.startLiveConversation();assert.equal(h.calls[1].options.signal.aborted,true);
 analysis.resolve(response(readyCapture("Obsolete typed capture")));await flush();assert.equal(h.t.state.summary,"");assert.equal(h.t.conversationUI.live.active,true);
});
await check("a suggested title during reviewed voice does not invalidate its response",async()=>{
 const h=concurrentSetup(),question=deferred();h.t.state.voiceChoice="local:synthetic";h.t.state.voice={name:"Synthetic",lang:"en-US"};
 h.route(url=>url==="/api/transcribe"?response({text:"I set up my drone."}):question.promise);
 await h.t.startLiveConversation();await h.say();const basis=JSON.stringify(h.t.snapshot().context);h.t.applyProcessTitle("Drone setup");
 question.resolve(response(fast()));await flush();assert.equal(JSON.stringify(h.t.snapshot().context),basis);assert.equal(h.utterances.length,1);
 h.utterances[0].onend();await flush();assert.equal(h.t.conversationUI.status,"listening");await h.t.conversationUI.live.stop();h.t.resetConcurrent();
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
// The server attaches the same excerpt catalog to the notes and to the map of
// one result. Repeated IDs across those two lists are one source, not an error.
const sharedEvidence=()=>[{id:"doc_abc123_p1",document_id:"doc_abc123",name:"returns-procedure.pdf",label:"Page 1",text:"Credits above $400 need the Finance Controller's approval."},
 {id:"doc_abc123_p2",document_id:"doc_abc123",name:"returns-procedure.pdf",label:"Page 2",text:"The Returns Clerk logs each return in the register."}];
const citedFindings=()=>[{key:"checks",status:"partial",answer:"The Finance Controller approves credits above $400.",evidence_turns:["doc_abc123_p1"]}];
const citedWorkflow=()=>({workflow:{title:"Customer returns",steps:[{id:"s1",title:"Log the return",type:"activity",evidence_turns:["doc_abc123_p2"]},{id:"s2",title:"Obtain credit approval",type:"activity",evidence_turns:["doc_abc123_p1"]}],
 connections:[{from:"s1",to:"s2",label:"",evidence_turns:["doc_abc123_p2"]}],open_questions:[]},document_evidence:sharedEvidence()});
await check("invalid background map keeps valid notes and offers a map-only retry",async()=>{
 const h=concurrentSetup(),notes=readyCapture("Independent notes").capture;
 const previous={title:"Prior accepted workflow",steps:[],connections:[],open_questions:[]};
 h.t.conversationUI.workflow=previous;notes.workflow_capture={workflow:{title:"Invalid",steps:"invalid"}};
 h.t.applyBackgroundCapture(notes,h.t.snapshot());
 assert.equal(h.t.state.summary,"Independent notes");assert.equal(h.t.conversationUI.workflow,previous);
 assert.equal(h.node("retry-workflow").dataset.mapOnly,"true");assert.equal(h.node("retry-workflow").hidden,false);
 const questions=Array.from({length:500},(_,i)=>"Clarify item "+i);
 notes.workflow_capture={workflow:{title:"Historical workflow",steps:[],connections:[],open_questions:questions}};
 h.t.applyBackgroundCapture(notes,h.t.snapshot());assert.equal(h.t.conversationUI.workflow.open_questions.length,500);
});
await check("background notes and map carrying the same document excerpts both apply",async()=>{
 const h=concurrentSetup(),result=readyCapture("Notes citing a reference file");result.capture.document_evidence=sharedEvidence();result.capture.memo_findings=citedFindings();
 result.workflow_state="ready";result.workflow_capture=citedWorkflow();
 h.route(url=>url==="/api/conversation/turn"?response(fast()):url==="/api/conversation/status"?response(result):Promise.reject(Error(url)));
 h.node("answer-text").value="After logging the return I inspect the goods.";await h.t.sendAnswer({preventDefault(){}});await h.timer(650);
 assert.equal(h.t.state.summary,"Notes citing a reference file");assert.equal(h.t.state.documentEvidence.map(source=>source.id).join(),"doc_abc123_p1,doc_abc123_p2");
 assert.equal(h.t.state.memo_findings.find(finding=>finding.key==="checks").evidence_turns.join(),"doc_abc123_p1");
 assert.equal(h.t.conversationUI.workflow.steps.map(step=>step.evidence_turns.join()).join(),"doc_abc123_p2,doc_abc123_p1");
 assert.equal(h.node("workflow-status").textContent,"Updated through the latest answer");
 assert.match(h.node("analysis-status").textContent,/^Notes are up to date/);assert.doesNotMatch(h.node("analysis-status").textContent,/need attention/);
});
await check("wrap up applies a synchronized result whose notes and map cite the same document excerpts",async()=>{
 const h=concurrentSetup(),question="Which exception still needs explaining?";h.t.state.turns.push({id:"t002",role:"user",text:"The clerk reviews it."});
 h.route(url=>url==="/api/conversation/sync"?response({...approved(question),conversation_token:"session-one",revision:"r1",sync_required:false,summary:"Synchronized notes",
  memo_findings:citedFindings(),document_evidence:sharedEvidence(),workflow_capture:citedWorkflow()}):Promise.reject(Error(url)));
 await h.t.finalCheck();
 assert.equal(h.notices.filter(item=>item.error).map(item=>item.message).join(),"");assert.equal(h.calls[0].url,"/api/conversation/sync");
 assert.equal(h.t.state.turns.at(-1).text,question);assert.equal(h.t.state.summary,"Synchronized notes");
 assert.equal(h.t.state.documentEvidence.map(source=>source.id).join(),"doc_abc123_p1,doc_abc123_p2");
 assert.equal(h.t.conversationUI.workflow.connections[0].evidence_turns.join(),"doc_abc123_p2");assert.equal(h.node("workflow-status").textContent,"Updated through the latest answer");
 // A later result that repeats an already saved excerpt updates it in place.
 const again=readyCapture("Later notes");again.capture.document_evidence=sharedEvidence().slice(0,1);again.capture.memo_findings=citedFindings();
 h.t.applyBackgroundCapture(again.capture,h.t.snapshot());assert.equal(h.t.state.summary,"Later notes");assert.equal(h.t.state.documentEvidence.length,2);
});
await check("merging document excerpts still rejects a malformed citation",async()=>{
 for(const bad of [[null],[{document_id:"doc_abc123",text:"No identifier."}],[{id:"doc_other_p1",document_id:"doc_abc123",text:"Wrong file."}],
   [{id:"doc_abc123_p1",document_id:"doc_abc123",text:"  "}],[sharedEvidence()[0],{id:"doc_abc123_p1",document_id:"doc_abc123",text:""}],"doc_abc123_p1"]){
  const h=concurrentSetup(),result=readyCapture("Must not apply");result.capture.document_evidence=bad;
  assert.throws(()=>h.t.applyBackgroundCapture(result.capture,h.t.snapshot()),/saved document citation is invalid/);assert.equal(h.t.state.summary,"");assert.equal(h.t.state.documentEvidence.length,0);
 }
 // A result whose excerpt list is not a list at all is refused as before.
 const h=concurrentSetup();h.t.state.turns.push({id:"t002",role:"user",text:"The clerk reviews it."});
 h.route(url=>url==="/api/conversation/sync"?response({...approved("What happens next?"),conversation_token:"session-one",revision:"r1",sync_required:false,document_evidence:{0:sharedEvidence()[0]}}):Promise.reject(Error(url)));
 await h.t.finalCheck();assert.match(h.notices.filter(item=>item.error).map(item=>item.message).join(),/document evidence is invalid/);
 assert.equal(h.t.state.turns.at(-1).id,"t002");assert.equal(h.t.state.documentEvidence.length,0);
});
await check("automatic title refinement cannot stale an in-flight fast question",async()=>{
 const h=concurrentSetup(),question=deferred();h.t.state.context.process_name="";h.t.state.turns.push({id:"u1",role:"user",text:"I set up my drone."});h.route(()=>question.promise);
 const pending=h.t.request("/api/interview",{...h.t.snapshot(),action:"answer"});await flush();h.t.applyProcessTitle("Drone setup");question.resolve(response(fast()));const result=await pending;
 assert.equal(result.question,fast().question);assert.equal(h.t.snapshot().context.process_name,"");assert.equal(h.t.state.derivedProcessTitle,"Drone setup");
});
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
