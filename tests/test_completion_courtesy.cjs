"use strict";
// After the completion line a thank-you or a goodbye must not cost the completion, and the
// reply the final check accepts is offered as a control. The real web/app.js, the real
// concurrent controller and the real reviewed-voice controller run behind the fake
// browser boundary of the existing experience suite. No network, provider or audio.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
let harness=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(harness.includes("function setup()"));
harness=harness.replace('const controlled=','const concurrent=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");\nconst controlled=');
harness=harness.replace('updateControls=()=>{updatePresence();};','updateControls=()=>{updatePresence();}; renderWorkingMap=()=>{}; updateSaveHint=()=>{}; updateConversationControls=()=>{}; updateDocumentIntakeUI=()=>{};');
// The closure line with its control, and the control's handler, are the application's own.
// (Looked up by name, so that a version of the page without them fails each check for
// what it does rather than at start-up.)
const own=name=>`${name}:typeof ${name}==="function"?${name}:()=>{throw Error("web/app.js has no ${name}()");}`;
harness=harness.replace('setTeam:value=>',`applyInterview,${own("confirmNothingToAdd")},${own("renderClosure")},finalCheck,draftStaleReason,submissionCaptureState,setTeam:value=>`);
harness=harness.replace('vm.runInContext(controlled,context,','vm.runInContext(concurrent,context,{filename:"concurrent-interview.js"});vm.runInContext(controlled,context,');
harness+='\nmodule.exports={setup,approved,response,flush,deferred};';
const exported={exports:{}};
vm.runInNewContext(harness,{require,__dirname,module:exported,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException},{filename:"completion-courtesy-harness.cjs"});
const {setup,approved,response,flush,deferred}=exported.exports;

const FINAL_CHECK="Before we finish, is there anything else someone doing this work needs to know that we haven't captured?";
const COMPLETE="Thank you. All sixteen sections are captured and you have confirmed the account. It is ready for process-owner review.";
const ACK="Let me check that I have everything before we finish.";
const SESSION="c".repeat(64);
const finalCheck=(extra={})=>({...approved(FINAL_CHECK,"final_check"),coverage_verified:true,capture_token:"tok-check",closure:{asked:true,confirmed:false},summary:"Reviewed notes",...extra});
// The Coordinator's result for the confirmation, and for a courtesy after it.
const completed=(extra={})=>({...approved(COMPLETE,"complete"),coverage_verified:true,no_new_run:true,capture_token:"tok-complete",closure:{asked:true,confirmed:true},summary:"Reviewed notes",...extra});
const kept=()=>completed({completion_retained:true,capture_token:"tok-kept"});
const reopened=()=>({...approved(ACK,"review_pending"),capture_token:"tok-reopened",coverage_verified:false,review_ticket:"ticket-two",agent_run_id:"run-two",closure:{asked:false,confirmed:false}});
const synced=value=>({...value,conversation_token:SESSION,revision:"r",sync_required:false});
const turnNeedsSync=()=>({question:"",preserve_capture:true,conversation_token:SESSION,revision:"r",sync_required:true,
  completion:{complete:false,ready_for_final_check:false,allowed:false},ready_for_draft:false,closure:{asked:false,confirmed:false}});
const posts=(h,url)=>h.calls.filter(call=>call.url===url).map(call=>JSON.parse(call.options.body));
const copies=(h,text)=>h.t.state.turns.filter(turn=>turn.text===text).length;

function interview({concurrent=true}={}){
  const h=setup();h.t.state.config.api_configured=true;
  if(concurrent)h.t.state.config.concurrent_interview={enabled:true};
  // An installed voice, so that anything the page speaks is recorded by the fake synthesizer.
  h.t.state.voiceChoice="local:test";h.t.state.voice={name:"Test voice",lang:"en-US"};h.node("speak-questions").checked=true;
  h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts this work?"},{id:"t002",role:"user",text:"A clerk receives the request and logs it."},
    {id:"t003",role:"assistant",text:FINAL_CHECK}];
  return h;
}
// The participant confirmed the final check: the completion line is the interviewer's last turn.
function completedInterview(options){
  const h=interview(options);
  h.t.state.turns.push({id:"t004",role:"user",text:"No, nothing else."});
  // The working map of this checkpoint arrives with it, and a draft has been made from the account.
  h.t.applyInterview(completed({workflow_capture:{workflow:{title:"",steps:[],connections:[],open_questions:[]}}}));
  assert.equal(h.t.state.turns.at(-1).text,COMPLETE);assert.equal(h.t.state.closure.confirmed,true);assert.equal(h.t.state.coverageVerified,true);
  assert.equal(h.t.state.captureToken,"tok-complete");assert.equal(h.utterances.length,1,"The completion line is spoken once");
  h.t.state.draft={title:"Draft"};h.t.state.draftEvidence={version:h.t.state.evidenceVersion,documents:h.t.snapshot().document_revision};
  assert.equal(h.t.draftStaleReason(),"");
  const capture=h.t.submissionCaptureState().capture;
  assert.equal(capture.notes_current,true);assert.equal(capture.map_current,true);
  return h;
}
const send=(h,text)=>{h.node("answer-text").value=text;return h.t.sendAnswer({preventDefault(){}});};
function assertStillComplete(h,label,draftCurrent=true){
  assert.equal(h.t.state.closure.confirmed,true,label+": the confirmation is kept");assert.equal(h.t.state.closure.asked,true,label);
  assert.equal(h.t.state.coverageVerified,true,label+": the review is kept");assert.equal(h.t.state.completion?.complete,true,label);
  assert.equal(copies(h,COMPLETE),1,label+": the completion line is in the transcript once");
  assert.equal(h.utterances.length,1,label+": the completion line is not spoken again");
  if(draftCurrent)assert.equal(h.t.draftStaleReason(),"",label+": the draft is not marked out of date");
}
// What Submit would say about the notes and the working map once nothing is running.
function assertCaptureCurrent(h,label){
  const capture=h.t.submissionCaptureState().capture;
  assert.equal(capture.notes_current,true,label+": the notes include every saved answer");
  assert.equal(capture.map_current,true,label+": so does the working map");
}

let passed=0;const failed=[];
async function check(name,fn){
  try{await fn();passed++;console.log("PASS "+name);}
  catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,12).join("\n     "));}
}
(async()=>{
await check("the final confirmation advances a current map without a new map request",async()=>{
  const h=interview();h.t.state.turns.pop();
  h.t.applyInterview(finalCheck({workflow_capture:{workflow:{title:"Evidence map",steps:[],connections:[],open_questions:[]}}}));
  assert.equal(h.t.submissionCaptureState().capture.map_current,true);
  h.t.state.turns.push({id:"confirmation",role:"user",text:"No, nothing else."});
  h.t.applyInterview(completed());
  assertCaptureCurrent(h,"the server confirmed the same account");
  const behind=interview();
  behind.t.state.turns.push({id:"confirmation",role:"user",text:"No, nothing else."});
  behind.t.applyInterview(completed());
  assert.equal(behind.t.submissionCaptureState().capture.map_current,false,"a missing map remains missing");
});
await check("a typed thank-you after the completion line leaves the completed account as it is",async()=>{
  const h=completedInterview(),sync=deferred(),revision=h.t.conversationUI.revision;
  h.route(url=>url==="/api/conversation/turn"?response(turnNeedsSync()):url==="/api/conversation/sync"?sync.promise:response({}));
  const sending=send(h,"Thank you");await flush();
  // While the server decides, nothing is revoked on the page.
  assert.equal(posts(h,"/api/conversation/sync").length,1,"The message is sent to the server like any answer");
  assert.equal(h.t.state.turns.at(-1).text,"Thank you");assert.equal(h.t.state.busy,true);
  assertStillComplete(h,"while the reply is awaited");
  sync.resolve(response(synced(kept())));await sending;await flush();
  assertStillComplete(h,"after the reply");assertCaptureCurrent(h,"after the reply");
  h.t.renderClosure();
  assert.equal(h.node("closure-status").textContent,"You confirmed nothing is missing.");assert.equal(h.node("confirm-nothing").hidden,true);
  assert.equal(h.t.state.turns.at(-1).text,"Thank you","Nothing is added after the participant's message");
  assert.equal(h.t.state.turns.at(-2).text,COMPLETE);
  assert.equal(h.t.state.captureToken,"tok-kept");assert.equal(h.t.state.busy,false);
  assert.equal(h.t.conversationUI.revision,revision,"No working-map update is due for a courtesy");
  assert.equal(h.node("answer-text").value,"");assert.equal(h.notices.filter(item=>item.error).length,0);
  const request=posts(h,"/api/conversation/sync")[0];
  assert.equal(request.capture_token,"tok-complete");assert.deepEqual(request.turns.slice(-2).map(turn=>turn.text),[COMPLETE,"Thank you"]);
  // A second courtesy follows the first directly: the line was not issued again.
  h.route(url=>url==="/api/conversation/turn"?response(turnNeedsSync()):url==="/api/conversation/sync"?response(synced(kept())):response({}));
  await send(h,"Bye!");await flush();
  assertStillComplete(h,"after a second courtesy");
  assert.deepEqual(posts(h,"/api/conversation/sync")[1].turns.slice(-3).map(turn=>turn.text),[COMPLETE,"Thank you","Bye!"]);
});
await check("an addition after the completion line reopens the review as before",async()=>{
  const h=completedInterview(),revision=h.t.conversationUI.revision,review=deferred();
  h.route(url=>url==="/api/conversation/turn"?response(turnNeedsSync()):url==="/api/conversation/sync"?response(synced(reopened())):
    url==="/api/agent-team/review"?review.promise:response({}));
  h.node("speak-questions").checked=false;
  const sending=send(h,"Actually the bank also confirms receipt.");await flush();
  assert.equal(h.t.state.closure.confirmed,false,"The completion no longer stands");assert.equal(h.t.state.coverageVerified,false);
  assert.equal(h.t.draftStaleReason(),"answers","The draft does not include the addition");
  assert.equal(h.t.state.completion?.complete,false);assert.equal(h.t.conversationUI.revision,revision+1,"The working map is due for the addition");
  assert.equal(h.t.state.turns.at(-1).text,ACK);assert.equal(posts(h,"/api/agent-team/review").length,1,"The new review starts");
  review.resolve(response(finalCheck({capture_token:"tok-check-two"})));await sending;await flush();
  assert.equal(h.t.state.turns.at(-1).text,FINAL_CHECK);assert.equal(h.t.state.closure.asked,true);assert.equal(h.t.state.closure.confirmed,false);
});
await check("a message the server could not judge no longer shows the completion as standing",async()=>{
  const h=completedInterview(),revision=h.t.conversationUI.revision;
  h.route(url=>url==="/api/conversation/turn"?{ok:false,status:503,json:async()=>({error:"The model service is unavailable."})}:response({}));
  await send(h,"Thank you");await flush();
  assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.t.state.coverageVerified,false);assert.equal(h.t.state.completion,null);
  assert.equal(h.t.conversationUI.revision,revision+1);
  assert.equal(h.notices.filter(item=>item.error).length,1);assert.equal(h.node("retry-question").hidden,false);
  // Try again asks the server about the same transcript, and its answer restores the page.
  h.route(url=>url==="/api/conversation/turn"?response(turnNeedsSync()):url==="/api/conversation/sync"?response(synced(kept())):response({}));
  await h.t.retryQuestion();await flush();
  // (The draft stays flagged: while the message was unjudged it had to count as an answer.)
  assertStillComplete(h,"after Try again",false);
  assert.equal(h.t.state.turns.at(-1).text,"Thank you");
});
await check("without the concurrent interviewer a courtesy is held the same way and an addition is not",async()=>{
  const h=completedInterview({concurrent:false}),revision=h.t.conversationUI.revision;
  h.route(url=>url==="/api/agent-team/interview"?response(kept()):response({}));
  await send(h,"Great, thanks.");await flush();
  assertStillComplete(h,"managed team, typed");
  assert.equal(h.t.conversationUI.revision,revision,"No working-map update is requested for a courtesy");
  assert.equal(posts(h,"/api/agent-team/workflow").length,0);
  h.node("speak-questions").checked=false;
  h.route(url=>url==="/api/agent-team/interview"?response(approved("Which bank confirms it?")):response({}));
  await send(h,"The bank confirms receipt as well.");await flush();
  assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.t.conversationUI.revision,revision+1);
  assert.equal(h.t.state.turns.at(-1).text,"Which bank confirms it?");
});
await check("the first completion result is still shown and spoken, whatever its flags",async()=>{
  // The confirmation itself is answered without a new run as well; only a completion
  // line that is already in the transcript is left out.
  const h=interview();
  h.route(url=>url==="/api/conversation/turn"?response(turnNeedsSync()):url==="/api/conversation/sync"?response(synced(completed({completion_retained:true}))):response({}));
  await send(h,"No, nothing else.");await flush();
  assert.equal(copies(h,COMPLETE),1);assert.equal(h.t.state.turns.at(-1).text,COMPLETE);assert.equal(h.utterances.length,1);
  assert.equal(h.utterances[0].text,COMPLETE);assert.equal(h.t.state.closure.confirmed,true);
});
await check("Nothing to add is offered while the final check waits and sends a reply the check accepts",async()=>{
  const h=interview(),button=h.node("confirm-nothing");
  h.t.renderClosure();
  assert.equal(button.hidden,true,"Not offered before the final check has been asked");
  h.t.state.turns.pop();h.t.applyInterview(finalCheck());
  h.t.renderClosure();
  assert.equal(h.node("closure-status").textContent,"Waiting for your final confirmation.");
  assert.equal(button.hidden,false);assert.equal(button.disabled,false);
  h.t.state.busy=true;h.t.renderClosure();assert.equal(button.disabled,true,"Not while the interviewer is working");
  h.t.state.busy=false;h.t.conversationUI.live={active:true};h.t.renderClosure();assert.equal(button.disabled,true,"In voice the reply is spoken");
  h.t.conversationUI.live=null;h.t.renderClosure();assert.equal(button.disabled,false);
  // An answer that is being typed is not thrown away or sent by the control.
  h.node("answer-text").value="One more thing about refunds";
  h.route(()=>{throw Error("Nothing may be sent while an answer is being typed");});
  await h.t.confirmNothingToAdd();
  assert.equal(h.calls.length,0);assert.equal(h.node("answer-text").value,"One more thing about refunds");
  assert.equal(h.notices.length,1);assert.match(h.notices[0].message,/answer you have typed/);
  h.node("answer-text").value="";
  h.route(url=>url==="/api/conversation/turn"?response(turnNeedsSync()):url==="/api/conversation/sync"?response(synced(completed())):response({}));
  await h.t.confirmNothingToAdd();await flush();
  const request=posts(h,"/api/conversation/sync")[0];
  assert.deepEqual(request.turns.slice(-2).map(turn=>[turn.role,turn.text]),[["assistant",FINAL_CHECK],["user","No, nothing to add."]]);
  assert.equal(request.capture_token,"tok-check");assert.equal(request.action,"answer");
  assert.equal(h.t.state.turns.at(-1).text,COMPLETE);assert.equal(h.t.state.closure.confirmed,true);
  h.t.renderClosure();
  assert.equal(button.hidden,true,"Not offered once the account is confirmed");
  assert.equal(h.node("closure-status").textContent,"You confirmed nothing is missing.");
  // Without a pending final check the control does nothing at all.
  const calls=h.calls.length;await h.t.confirmNothingToAdd();assert.equal(h.calls.length,calls);
});
await check("Nothing to add is withdrawn when the review needs a new check",async()=>{
  const h=interview();h.t.state.turns.pop();h.t.applyInterview(finalCheck());
  h.t.state.coverageNeedsReview=true;h.t.renderClosure();
  assert.equal(h.node("confirm-nothing").hidden,true);assert.equal(h.node("closure-status").textContent,"Coverage and completion need a new check.");
  h.route(()=>{throw Error("Nothing may be sent");});await h.t.confirmNothingToAdd();assert.equal(h.calls.length,0);
});
await check("reviewed voice does not speak the completion line again for a courtesy",async()=>{
  const h=completedInterview({concurrent:false});
  h.t.state.voiceChoice="ai:marin";h.t.state.voice=null;
  h.route(url=>url==="/api/transcribe"?response({text:"Thank you, bye."}):url==="/api/agent-team/interview"?response(kept()):
    url==="/api/voice-session"?response(h.voiceSession):response({}));
  await h.t.startLiveConversation();await h.say();await flush();
  assert.equal(posts(h,"/api/agent-team/interview").length,1);
  assert.equal(h.t.state.turns.at(-1).text,"Thank you, bye.");assert.equal(copies(h,COMPLETE),1);
  // The speech connection prepared while the answer was processed is not used.
  for(const socket of h.sockets){socket.packet({type:"session.created"});await flush();}
  assert.equal(h.sockets.filter(socket=>socket.sent.length).length,0,"No speech is requested for a line that was already spoken");
  assert.equal(h.audio.length,0);
  assert.equal(h.t.conversationUI.live.active,false,"The voice session ends, as it does after the completion line");
  assert.equal(h.t.state.closure.confirmed,true);assert.equal(h.t.state.coverageVerified,true);
  assert.equal(h.notices.filter(item=>item.error).length,0);
});
console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
