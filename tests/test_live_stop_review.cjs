"use strict";
// Voice ends (Stop talking, a dropped session) while the completion review that Live
// voice started is still running. The application connects the real caption controller
// (web/live-voice.js) through its own startLiveConversation, and the real Stop talking
// handler of web/app.js is used, all on one virtual clock. WebRTC, the page and the
// provider are the local fakes of the existing suites; no network is used.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");

const clock={now:0,serial:0,timers:new Map()};
const virtualSetTimeout=(fn,delay)=>{const id={timer:++clock.serial};clock.timers.set(id,{fn,due:clock.now+(Number(delay)||0)});return id;};
const virtualClearTimeout=id=>{clock.timers.delete(id);};
class VirtualDate extends Date{static now(){return 1790000000000+clock.now;}}
function advance(ms){
 const end=clock.now+ms;
 for(;;){
  let next=null;
  for(const entry of clock.timers)if(entry[1].due<=end&&(!next||entry[1].due<next[1].due))next=entry;
  if(!next)break;
  clock.timers.delete(next[0]);clock.now=Math.max(clock.now,next[1].due);next[1].fn();
 }
 clock.now=end;
}
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,JSON,AbortController,DOMException,setImmediate,
 Date:VirtualDate,setTimeout:virtualSetTimeout,clearTimeout:virtualClearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
const web=name=>fs.readFileSync(path.join(__dirname,"..","web",name),"utf8");
// The Stop talking handler is taken from app.js itself, as tests/test_ui_state.cjs does.
const stopBinding=web("app.js").split("\n").filter(line=>/\$\("stop-live"\)\.addEventListener/.test(line)).join("\n");
assert.ok(stopBinding,"app.js binds the Stop talking control");
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(source.includes("setTeam:value=>"),"The application test seam is available");
source=source.replace("setTeam:value=>",()=>"bindStop:()=>{"+stopBinding+"},setTeam:value=>");
// The seam's stand-in for setBusy keeps the message too, so the label on screen can be read.
assert.ok(source.includes("setBusy=value=>{state.busy=value;};"),"The application test seam replaces setBusy");
source=source.replace("setBusy=value=>{state.busy=value;};",()=>"setBusy=(value,message=\"\")=>{state.busy=value;state.busyMessage=message;updateControls();};");
const app=exported(source,"\nmodule.exports={setup,approved,response,flush,reviewAck,deferred};");

const ACK="Let me check that I have everything before we finish.";
const FINAL_CHECK="Is there anything else someone doing this work needs to know that we haven't captured?";
const REVIEW_LABEL="Checking the recorded topics and process…";
let events=0;
const settle=async()=>{for(let i=0;i<6;i++)await app.flush();};
const finalCheck=()=>({...app.approved(FINAL_CHECK,"final_check"),coverage_verified:true,summary:"Reviewed notes",closure:{asked:true,confirmed:false}});
// A response that is still on its way; like fetch, it is rejected when its request is cancelled.
function onItsWay(options){
 const pending=app.deferred();
 options?.signal?.addEventListener("abort",()=>pending.reject(new DOMException("Aborted","AbortError")),{once:true});
 return pending;
}
async function session(){
 const turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
 const v=voice.setup(),h=app.setup();
 h.t.state.config.agent_team.voice_mode="live_front";h.t.state.config.concurrent_interview={enabled:true};
 vm.runInContext(web("concurrent-interview.js"),h.context,{filename:"concurrent-interview.js"});
 h.t.state.turns=turns.map(turn=>({...turn}));
 // The application builds its live controller itself. The class it finds hands back the
 // real controller of the voice suite with the application's own callbacks attached.
 h.window.CollectorLiveVoice=class{constructor(options){
  const attach=(list,call)=>{list.push=value=>{Array.prototype.push.call(list,value);call?.(value);return list.length;};};
  attach(v.captions,options.onTranscript);attach(v.statuses,options.onStatus);attach(v.errors,options.onError);
  return v.api;}};
 await h.t.startLiveConversation();await settle();
 assert.equal(h.t.conversationUI.live,v.api,"The application runs the real live controller");assert.equal(v.api.active,true);
 let stopTalking=null;h.node("stop-live").addEventListener=(type,listener)=>{if(type==="click")stopTalking=listener;};
 h.t.bindStop();assert.equal(typeof stopTalking,"function");
 const origin=clock.now;
 const s={v,h,review:null,
  to(ms){const delta=origin+ms-clock.now;assert.ok(delta>=0,"The scenario clock only moves forward");v.step(delta);advance(delta);},
  hear(role,start,end,text){s.to(end);v.event({type:role==="user"?"session.input_transcript.delta":"session.output_transcript.delta",event_id:"event_"+(++events),delta:text,start_ms:start,end_ms:end});},
  lines(){return v.channels.at(-1).sent.filter(event=>event.type==="session.instructions.append");},
  acknowledge(ms){s.to(ms);const sent=s.lines().at(-1);assert.ok(sent,"A line was handed to the interviewer");v.event({type:"session.instructions.appended",client_event_id:sent.event_id,start_ms:ms});},
  transcript(){return h.t.state.turns.map(turn=>`${turn.role}: ${turn.text.trim()}`);},
  copies(text){return h.t.state.turns.filter(turn=>turn.text.includes(text)).length;},
  errors(){return Array.from(h.notices).filter(item=>item.error).map(item=>item.message);},
  posts(url){return Array.from(h.calls).filter(call=>call.url===url).map(call=>JSON.parse(call.options.body));},
  // Stop talking, exactly as the button does it; the provider then confirms the close.
  press(){return stopTalking();},
  async closed(stopping){v.event({type:"session.closed"});await stopping;await settle();assert.equal(v.api.active,false);},
  async stop(){const stopping=s.press();await settle();const closing=h.t.conversationUI.status;await s.closed(stopping);return closing;}};
 // The participant's last answer completes the topics: the capture answers with the
 // acknowledgement, the application has the interviewer read it and starts the review.
 h.route((url,options)=>url==="/api/agent-team/interview"?app.response(app.reviewAck()):url==="/api/agent-team/review"?(s.review=onItsWay(options)).promise:app.response({}));
 s.hear("user",100,1500,"An email from the client starts it.");
 s.to(3200);await h.timer(400);await settle();
 assert.equal(h.t.state.turns.at(-1).text,ACK,"The application records the acknowledgement");
 assert.equal(s.posts("/api/agent-team/review").length,0,"The review waits for the spoken acknowledgement");
 s.acknowledge(3300);s.hear("assistant",3500,6000,ACK);s.to(7700);await settle();
 assert.equal(s.posts("/api/agent-team/review").length,1,"The completion review is running"); // GPT-Live reads the line
 return s;
}
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,12).join("\n     "));}
}
(async()=>{
 await check("Stop talking while the completion review runs keeps the review, shows it and applies its result",async()=>{
  const s=await session(),before=s.transcript();
  assert.equal(s.h.t.state.busy,false,"While voice is on the review runs behind the conversation");
  const closing=await s.stop();
  assert.equal(closing,"closing","The transport was still closing when the page was first checked");
  assert.deepEqual(s.transcript(),before,"Stopping adds nothing to the transcript");assert.equal(s.copies(ACK),1,"The acknowledgement appears once");
  assert.equal(s.h.t.state.busy,true,"The review that is still running is shown as work in progress");
  assert.equal(s.h.t.state.busyMessage,REVIEW_LABEL);
  assert.equal(s.h.node("presence-status").textContent,REVIEW_LABEL,"The presence line names the review instead of Voice off");
  assert.equal(s.posts("/api/agent-team/review").length,1,"No second review is requested");
  s.review.resolve(app.response(finalCheck()));await settle();
  assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK,"The finished review's final check is shown");
  assert.equal(s.h.t.state.closure.asked,true);assert.equal(s.h.t.state.coverageVerified,true);assert.equal(s.h.t.state.summary,"Reviewed notes");
  assert.equal(s.h.t.state.busy,false,"The busy state ends with the review");
  assert.equal(s.lines().length,1,"Nothing is handed to the voice session that has ended");
  assert.equal(s.h.node("retry-question").hidden,true);assert.deepEqual(s.errors(),[]);
  assert.equal(s.posts("/api/agent-team/interview").length,1,"No second capture was needed");
 });
 await check("the busy state appears as soon as Stop talking is pressed, before the transport has closed",async()=>{
  const s=await session();
  const stopping=s.press();await settle();
  assert.equal(s.h.t.conversationUI.status,"closing");assert.equal(s.h.t.state.busy,true);assert.equal(s.h.t.state.busyMessage,REVIEW_LABEL);
  // The review returns while the transport is still closing.
  s.review.resolve(app.response(finalCheck()));await settle();
  assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK);assert.equal(s.h.t.state.busy,false);
  await s.closed(stopping);
  assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK);assert.equal(s.copies(FINAL_CHECK),1);assert.equal(s.copies(ACK),1);
  assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);
 });
 await check("a review that fails after Stop talking is announced and retried with the same review, without a second capture",async()=>{
  const s=await session();await s.stop();
  s.review.resolve({ok:false,status:500,json:async()=>({error:"The model service is unavailable."})});await settle();
  assert.equal(s.h.t.state.busy,false);
  assert.equal(s.errors().length,1,"The participant is told the review did not finish");
  assert.match(s.errors()[0],/Retry completion review/);assert.match(s.errors()[0],/The model service is unavailable\./);
  assert.doesNotMatch(s.errors()[0],/Voice continues/,"Voice has ended; the notice does not say it continues");
  const retry=s.h.node("retry-question");
  assert.equal(retry.hidden,false,"The retry control is shown");assert.equal(retry.textContent,"Retry completion review");
  assert.notEqual(s.h.t.state.turns.at(-1).text,FINAL_CHECK);
  const retrying=s.h.t.retryQuestion();await settle();
  s.review.resolve(app.response(finalCheck()));await retrying;await settle();
  const reviews=s.posts("/api/agent-team/review");
  assert.equal(reviews.length,2);assert.equal(reviews[1].review_ticket,"review-ticket-one","The retry uses the prepared review");
  assert.equal(s.posts("/api/agent-team/interview").length,1,"No second capture");assert.equal(s.posts("/api/conversation/sync").length,0,"No Wrap up round");
  assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK);assert.equal(s.copies(ACK),1);
  assert.equal(retry.hidden,true);assert.equal(s.h.t.state.busy,false);
 });
 await check("interviewer speech during a live review stays in the transcript and the review still applies after Stop",async()=>{
  const s=await session();
  s.hear("assistant",9000,12000," While I check, is there anything about approvals you want to add?");s.to(13700);
  const remark=s.h.t.state.turns.at(-1).text;
  await s.stop();s.review.resolve(app.response(finalCheck()));await settle();
  assert.equal(s.copies(remark),1);assert.equal(s.copies(FINAL_CHECK),1);assert.equal(s.h.t.state.closure.asked,true);
  assert.equal(s.posts("/api/agent-team/review").length,1);assert.equal(s.errors().length,0);
 });
 await check("an expired live review shows Retry, and after Stop the retry checks a fresh snapshot",async()=>{
  const s=await session();
  s.review.resolve({ok:false,status:409,json:async()=>({error:"Review expired."})});await settle();
  const retry=s.h.node("retry-question");assert.equal(retry.hidden,false);assert.equal(retry.dataset.resumeReview,"true");
  assert.match(s.errors().at(-1),/stop talking, then choose Retry completion review/i);
  await s.stop();
  s.h.route((url,options)=>url==="/api/conversation/sync"?app.response({...app.reviewAck(),review_ticket:"review-ticket-two",conversation_token:"c".repeat(64),revision:"r2",sync_required:false}):
   url==="/api/agent-team/review"?(s.review=onItsWay(options)).promise:app.response({}));
  const retrying=s.h.t.retryQuestion();await settle();
  assert.equal(s.posts("/api/conversation/sync")[0].action,"close");
  s.review.resolve(app.response(finalCheck()));await retrying;await settle();
  assert.equal(s.posts("/api/agent-team/review").at(-1).review_ticket,"review-ticket-two");assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK);
 });
 await check("Pause review works after Stop talking and nothing else is announced",async()=>{
  const s=await session();await s.stop();
  assert.equal(s.h.t.state.busy,true);
  s.h.t.pauseCompletionReview();await settle();
  assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);
  assert.equal(s.h.node("retry-question").textContent,"Resume review");assert.equal(s.h.node("retry-question").hidden,false);
  assert.ok(Array.from(s.h.notices).some(item=>/Review paused/.test(item.message)));
  assert.equal(s.copies(FINAL_CHECK),0);
 });
 await check("a session that the provider closes during the review keeps the review as well",async()=>{
  const s=await session();
  s.v.event({type:"session.closed"});await settle(); // not Stop talking: the connection ended by itself
  assert.equal(s.v.api.active,false);assert.equal(s.h.t.conversationUI.status,"idle");
  assert.equal(s.errors().length,1);assert.match(s.errors()[0],/live voice session ended/i);
  assert.equal(s.h.t.state.busy,true);assert.equal(s.h.t.state.busyMessage,REVIEW_LABEL);
  s.review.resolve(app.response(finalCheck()));await settle();
  assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK);assert.equal(s.h.t.state.closure.asked,true);
  assert.equal(s.h.t.state.busy,false);assert.equal(s.errors().length,1);assert.equal(s.copies(ACK),1);
 });
 await check("while voice is on the review still answers through the interviewer and the page is not busy",async()=>{
  const s=await session();
  s.review.resolve(app.response(finalCheck()));await settle();
  assert.equal(s.h.t.state.busy,false);
  assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK);assert.equal(s.lines().length,2,"The final check is handed to the interviewer to say");
  assert.equal(s.h.t.state.closure.asked,true);assert.deepEqual(s.errors(),[]);
  await s.v.api.stop({immediate:true});await settle();
  assert.equal(s.h.t.state.busy,false,"Nothing is running when voice ends afterwards");
 });
 await check("last words that arrive as voice ends withdraw the review, and the participant is told once",async()=>{
  const s=await session();
  const stopping=s.press();await settle();
  assert.equal(s.h.t.state.busy,true);assert.equal(s.h.t.state.busyMessage,REVIEW_LABEL);
  // The provider delivers the participant's last words while the transport is closing.
  s.hear("user",8000,9200,"Oh, and the bank confirms receipt.");await settle();
  await s.closed(stopping);
  assert.equal(s.errors().length,1,"A check that was announced and then withdrawn is not dropped in silence");
  assert.match(s.errors()[0],/last words/);assert.match(s.errors()[0],/Wrap up/);assert.doesNotMatch(s.errors()[0],/Retry completion review/);
  assert.equal(s.h.node("retry-question").hidden,true,"There is no prepared review left to retry");
  assert.equal(s.transcript().at(-1),"user: Oh, and the bank confirms receipt.");assert.equal(s.copies(FINAL_CHECK),0);assert.equal(s.copies(ACK),1);
  assert.equal(s.posts("/api/agent-team/interview").length,2,"The notes are caught up with the last words");
  assert.equal(s.posts("/api/agent-team/review").length,1,"No review starts by itself after voice has ended");
  assert.equal(s.h.t.state.busy,false);assert.equal(s.h.t.state.coverageVerified,false);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
