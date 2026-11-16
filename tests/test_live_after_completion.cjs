"use strict";
// Live voice after the completion line. What the participant says in the nine seconds
// before voice ends by itself (a thank-you, a goodbye) must not rewrite the confirmation
// turn, revoke the completion, repeat the line or keep the microphone open; only an
// addition reopens the review. The application connects the real caption controller
// (web/live-voice.js) through its own startLiveConversation, on one virtual clock.
// WebRTC, the page and the provider are the local fakes of the existing suites; no network.
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
assert.ok(source.includes("setBusy=value=>{state.busy=value;};"),"The application test seam replaces setBusy");
source=source.replace("setBusy=value=>{state.busy=value;};",()=>"setBusy=(value,message=\"\")=>{state.busy=value;state.busyMessage=message;updateControls();};renderWorkingMap=()=>{};");
const app=exported(source,"\nmodule.exports={setup,approved,response,flush,reviewAck,deferred};");

const FINAL_CHECK="Before we finish, is there anything else someone doing this work needs to know that we haven't captured?";
const COMPLETE="Thank you. All sixteen sections are captured and you have confirmed the account. It is ready for process-owner review.";
const ACK="Let me check that I have everything before we finish.";
const FIRST="An email from the client starts it.",CONFIRMATION="No, nothing else.";
let events=0;
const settle=async()=>{for(let i=0;i<6;i++)await app.flush();};
function onItsWay(options){
 const pending=app.deferred();
 options?.signal?.addEventListener("abort",()=>pending.reject(new DOMException("Aborted","AbortError")),{once:true});
 return pending;
}
const finalCheck=()=>({...app.approved(FINAL_CHECK,"final_check"),coverage_verified:true,capture_token:"tok-check",closure:{asked:true,confirmed:false},summary:"Reviewed notes"});
const completed=()=>({...app.approved(COMPLETE,"complete"),coverage_verified:true,no_new_run:true,capture_token:"tok-complete",closure:{asked:true,confirmed:true},summary:"Reviewed notes"});
// The Coordinator's answer to a courtesy after the completion line: the same capture, kept.
const kept=()=>({...completed(),completion_retained:true,capture_token:"tok-kept"});

// A Live voice interview in which the participant has just confirmed the final check: the
// application has recorded the completion line, the interviewer has read it, and voice
// is due to end by itself nine seconds after the line.
async function completedSession(){
 const v=voice.setup(),h=app.setup();
 h.t.state.config.agent_team.voice_mode="live_front";h.t.state.config.concurrent_interview={enabled:true};
 vm.runInContext(web("concurrent-interview.js"),h.context,{filename:"concurrent-interview.js"});
 h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
 h.window.CollectorLiveVoice=class{constructor(options){
  const attach=(list,call)=>{list.push=value=>{Array.prototype.push.call(list,value);call?.(value);return list.length;};};
  attach(v.captions,options.onTranscript);attach(v.statuses,options.onStatus);attach(v.errors,options.onError);
  return v.api;}};
 await h.t.startLiveConversation();await settle();
 assert.equal(h.t.conversationUI.live,v.api,"The application runs the real live controller");assert.equal(v.api.active,true);
 let stopTalking=null;h.node("stop-live").addEventListener=(type,listener)=>{if(type==="click")stopTalking=listener;};
 h.t.bindStop();assert.equal(typeof stopTalking,"function");
 const origin=clock.now;
 const s={v,h,captures:[],replies:[finalCheck(),completed()],hold:false,review:null,
  to(ms){const delta=origin+ms-clock.now;assert.ok(delta>=0,"The scenario clock only moves forward");v.step(delta);advance(delta);},
  hear(role,start,end,text){s.to(end);v.event({type:role==="user"?"session.input_transcript.delta":"session.output_transcript.delta",event_id:"event_"+(++events),delta:text,start_ms:start,end_ms:end});},
  lines(){return v.channels.at(-1).sent.filter(event=>event.type==="session.instructions.append");},
  acknowledge(ms){s.to(ms);const sent=s.lines().at(-1);assert.ok(sent,"A line was handed to the interviewer");v.event({type:"session.instructions.appended",client_event_id:sent.event_id,start_ms:ms});},
  transcript(){return h.t.state.turns.map(turn=>`${turn.role}: ${turn.text.trim()}`);},
  copies(text){return h.t.state.turns.filter(turn=>turn.text.includes(text)).length;},
  errors(){return Array.from(h.notices).filter(item=>item.error).map(item=>item.message);},
  posts(url){return Array.from(h.calls).filter(call=>call.url===url).map(call=>JSON.parse(call.options.body));},
  // Application timers are fired by hand in this harness; the ending is the 9000 ms one.
  due(ms){return [...h.timers.values()].filter(timer=>timer.ms===ms).length;},
  // The working map is due for an update whenever this number has moved on.
  mapRevision(){return h.t.conversationUI.revision;},
  // The participant says something; its caption is final once they have been quiet, and the notes capture follows.
  async say(start,end,text){s.hear("user",start,end,text);s.to(end+1700);await h.timer(400);await settle();},
  async land(index,reply){s.captures[index].response.resolve(app.response(reply));await settle();},
  press(){return stopTalking();},
  async closed(stopping){v.event({type:"session.closed"});await stopping;await settle();assert.equal(v.api.active,false);},
  // The nine seconds are up.
  async nineSeconds(){await h.timer(9000);await settle();},
  assertComplete(label){
   assert.equal(h.t.state.closure.confirmed,true,label+": the confirmation is kept");assert.equal(h.t.state.closure.asked,true,label);
   assert.equal(h.t.state.coverageVerified,true,label+": the review is kept");assert.equal(h.t.state.completion?.complete,true,label);
   assert.equal(s.copies(COMPLETE),1,label+": the completion line is in the transcript once");
   assert.equal(s.lines().length,2,label+": nothing more is handed to the interviewer to say");
  }};
 h.route((url,options)=>{
  if(url==="/api/agent-team/interview"){
   const capture={body:JSON.parse(options.body),response:null};s.captures.push(capture);
   if(s.fail)return {ok:false,status:503,json:async()=>({error:s.fail})};
   if(s.hold){capture.response=onItsWay(options);return capture.response.promise;}
   return app.response(s.replies.shift()||kept());
  }
  if(url==="/api/agent-team/review")return (s.review=onItsWay(options)).promise;
  return app.response({});
 });
 await s.say(100,1500,FIRST);
 assert.equal(h.t.state.turns.at(-1).text,FINAL_CHECK,"The application records the final check");
 s.acknowledge(3300);s.hear("assistant",3500,6000,FINAL_CHECK);s.to(7700); // the interviewer reads the line
 await s.say(8000,9000,CONFIRMATION);
 assert.equal(h.t.state.turns.at(-1).text,COMPLETE,"The application records the completion line");
 assert.equal(s.captures.length,2);assert.equal(h.t.state.captureToken,"tok-complete");
 s.acknowledge(10800);s.hear("assistant",11000,14000,COMPLETE);s.to(15700);
 s.assertComplete("at completion");
 assert.equal(s.due(9000),1,"Voice is due to end by itself");
 s.maps=s.mapRevision();
 return s;
}
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,12).join("\n     "));}
}
(async()=>{
 await check("a thank-you after the completion line is a turn of its own and changes nothing",async()=>{
  const s=await completedSession();
  // Already the first fragment of the caption used to cancel the ending and reset the closure.
  s.hear("user",16000,16400,"Thank");
  s.assertComplete("at the first fragment");assert.equal(s.due(9000),1,"The ending is still due");
  await s.say(16400,17000," you, bye.");
  assert.deepEqual(s.transcript().slice(-4),["assistant: "+FINAL_CHECK,"user: "+CONFIRMATION,"assistant: "+COMPLETE,"user: Thank you, bye."],
   "The confirmation turn is not rewritten and the line is not repeated");
  assert.equal(s.captures.length,3,"The words are sent to the lead like any answer");
  const sent=s.captures[2].body;
  assert.equal(sent.capture_token,"tok-complete");assert.deepEqual(sent.turns.slice(-3).map(turn=>turn.text),[CONFIRMATION,COMPLETE,"Thank you, bye."]);
  s.assertComplete("after the reply");
  assert.equal(s.due(9000),1,"The ending is still due");assert.equal(s.mapRevision(),s.maps,"No working-map update is due for a courtesy");
  assert.equal(s.h.t.state.captureToken,"tok-kept");assert.deepEqual(s.errors(),[]);
  // Nine seconds after the completion line voice ends by itself, with the account complete.
  await s.nineSeconds();
  await s.closed(Promise.resolve());
  s.assertComplete("after voice has ended");
  assert.equal(s.captures.length,3,"Nothing further is captured");assert.equal(s.h.t.state.busy,false);
 });
 await check("the interviewer's own goodbye between two courtesies changes nothing either",async()=>{
  const s=await completedSession();
  await s.say(16000,17000,"Thank you.");
  s.hear("assistant",19000,20000,"You're welcome. Goodbye!");
  await s.say(20400,21000,"Bye!");
  assert.deepEqual(s.transcript().slice(-4),["assistant: "+COMPLETE,"user: Thank you.","assistant: You're welcome. Goodbye!","user: Bye!"]);
  assert.equal(s.captures.length,4);
  assert.deepEqual(s.captures[3].body.turns.slice(-4).map(turn=>turn.text),[COMPLETE,"Thank you.","You're welcome. Goodbye!","Bye!"]);
  s.assertComplete("after two courtesies");assert.equal(s.due(9000),1);
 });
 await check("words that are still being judged when the nine seconds are up are waited for",async()=>{
  const s=await completedSession();
  s.hold=true;await s.say(16000,17000,"Thank you so much.");
  assert.equal(s.captures.length,3);
  await s.nineSeconds();
  assert.equal(s.v.api.active,true,"Voice does not end in the middle of a reply that has not been judged");
  s.assertComplete("while the reply is awaited");
  await s.land(2,kept());
  s.assertComplete("after the reply");
  await s.h.timer(500);await settle();
  await s.closed(Promise.resolve());
  s.assertComplete("after voice has ended");
 });
 await check("an addition after the completion line cancels the ending and reopens the review",async()=>{
  const s=await completedSession();
  s.replies.push({...app.reviewAck(),capture_token:"tok-reopened"});
  s.hear("user",16000,16400,"Oh, and");
  s.assertComplete("while the participant is speaking");
  await s.say(16400,18500," the bank also confirms receipt.");
  assert.equal(s.captures.length,3);
  assert.equal(s.h.t.state.closure.confirmed,false,"The completion no longer stands");assert.equal(s.h.t.state.coverageVerified,false);
  assert.equal(s.h.t.state.completion?.complete,false);
  assert.equal(s.due(9000),0,"Voice no longer ends by itself");assert.equal(s.due(500),0);
  assert.equal(s.mapRevision(),s.maps+1,"The working map is due for the addition");
  assert.equal(s.h.t.state.turns.at(-1).text,ACK);assert.equal(s.lines().length,3,"The interviewer is given the acknowledgement");
  assert.equal(s.posts("/api/agent-team/review").length,1,"The new review starts");
  assert.equal(s.v.api.active,true);assert.equal(s.copies(COMPLETE),1);
 });
 await check("when the words could not be judged the completion is no longer shown as standing",async()=>{
  const s=await completedSession();
  s.fail="The model service is unavailable.";
  await s.say(16000,17000,"Thank you.");
  assert.equal(s.errors().length,1);assert.match(s.errors()[0],/notes could not be updated/);
  assert.equal(s.h.t.state.closure.confirmed,false);assert.equal(s.h.t.state.coverageVerified,false);
  assert.equal(s.due(9000),0);assert.equal(s.v.api.active,true,"Voice continues, as the notice says");
  // The next words are judged again, and the lead's answer restores the page without repeating the line.
  s.fail=null;
  await s.say(19000,19600,"Bye!");
  assert.equal(s.h.t.state.closure.confirmed,true);assert.equal(s.h.t.state.coverageVerified,true);
  assert.equal(s.copies(COMPLETE),1);assert.equal(s.lines().length,2,"The completion line is not said a second time");
 });
 await check("Stop talking while a thank-you is being judged keeps the completed account",async()=>{
  const s=await completedSession();
  s.hold=true;await s.say(16000,17000,"Thanks, bye.");
  const stopping=s.press();await settle();await s.closed(stopping);
  assert.equal(s.h.t.state.busy,true,"The reply that is on its way is waited for");
  s.assertComplete("while voice has ended and the reply is awaited");
  await s.land(2,kept());
  assert.equal(s.h.t.state.busy,false);
  s.assertComplete("after the reply");
  assert.equal(s.captures.length,3,"No second capture is needed");assert.deepEqual(s.errors(),[]);
 });
 await check("an addition whose capture returns after voice has ended revokes the completion",async()=>{
  const s=await completedSession();
  s.hold=true;await s.say(16000,18000,"One more thing: the auditors see the register.");
  const stopping=s.press();await settle();await s.closed(stopping);
  await s.land(2,{...app.approved("Who sends the register to the auditors?"),capture_token:"tok-more",coverage_verified:false,summary:"Notes with the addition"});
  assert.equal(s.h.t.state.closure.confirmed,false,"The page no longer says the account is confirmed");
  assert.equal(s.h.t.state.coverageVerified,false);assert.equal(s.h.t.state.completion,null);
  assert.equal(s.h.t.state.summary,"Notes with the addition");assert.equal(s.h.t.state.busy,false);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
