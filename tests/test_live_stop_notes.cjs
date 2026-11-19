"use strict";
// Voice ends (Stop talking, a dropped session) before the notes include the last spoken
// answer: a capture is still on its way, or the last caption was only finalized by the
// stop. The application connects the real caption controller (web/live-voice.js) through
// its own startLiveConversation and the real Stop talking handler of web/app.js is used,
// on one virtual clock. WebRTC, the page and the provider are local fakes; no network.
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
// The handlers of the two controls are taken from app.js itself, as tests/test_ui_state.cjs does.
const binding=pattern=>web("app.js").split("\n").filter(line=>pattern.test(line)).join("\n");
const stopBinding=binding(/\$\("stop-live"\)\.addEventListener/),updateBinding=binding(/\$\("update-notes"\)\??\.addEventListener/);
assert.ok(stopBinding,"app.js binds the Stop talking control");
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
// The original fixture disables map scheduling. Exercise the real scheduler
// when a scenario enables API access for its synthetic workflow endpoint.
source=source.replace("scheduleWorkflow=()=>{};","");
assert.ok(source.includes("setTeam:value=>"),"The application test seam is available");
source=source.replace("setTeam:value=>",()=>"bindStop:()=>{"+stopBinding+"},bindUpdate:()=>{"+updateBinding+"},generateDraft,refreshWorkflow,renderAnalysisThrough,clearState,setTeam:value=>");
// The seam's stand-in for setBusy keeps the message too, so the label on screen can be read.
assert.ok(source.includes("setBusy=value=>{state.busy=value;};"),"The application test seam replaces setBusy");
source=source.replace("setBusy=value=>{state.busy=value;};",()=>"setBusy=(value,message=\"\")=>{state.busy=value;state.busyMessage=message;updateControls();};renderWorkingMap=()=>{};");
const app=exported(source,"\nmodule.exports={setup,approved,response,flush,reviewAck,deferred};");

const ACK="Let me check that I have everything before we finish.";
const COMPLETE="Thank you. All sixteen sections are captured and you have confirmed the account. It is ready for process-owner review.";
const UPDATING="Updating notes from your last answer…",BEHIND="Notes are behind the transcript";
const FIRST="An email from the client starts it.",SECOND="The treasury analyst approves the list.";
let events=0;
const settle=async()=>{for(let i=0;i<6;i++)await app.flush();};
// A response that is still on its way; like fetch, it is rejected when its request is cancelled.
function onItsWay(options){
 const pending=app.deferred();
 options?.signal?.addEventListener("abort",()=>pending.reject(new DOMException("Aborted","AbortError")),{once:true});
 return pending;
}
// What the lead returns for a transcript: notes that cite each answer it was given.
function notes(body,extra={}){
 const answers=body.turns.filter(turn=>turn.role==="user");
 const memo_findings=[{key:"trigger",status:"partial",answer:"An email from the client starts the work.",evidence_turns:[answers[0].id]}];
 if(answers.some(turn=>turn.text.includes("treasury")))memo_findings.push({key:"checks",status:"partial",answer:"The treasury analyst approves the list.",evidence_turns:[answers.at(-1).id]});
 return {...app.approved("What happens after the approval?"),summary:`Notes with ${memo_findings.length} topic${memo_findings.length>1?"s":""}`,capture_token:"tok-"+memo_findings.length,coverage_verified:false,memo_findings,...extra};
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
 let stopTalking=null,updateNotes=null;
 h.node("stop-live").addEventListener=(type,listener)=>{if(type==="click")stopTalking=listener;};
 h.node("update-notes").addEventListener=(type,listener)=>{if(type==="click")updateNotes=listener;};
 h.t.bindStop();h.t.bindUpdate();assert.equal(typeof stopTalking,"function");
 const origin=clock.now;
 const s={v,h,captures:[],hold:false,fail:null,drafts:0,answer:notes,
  to(ms){const delta=origin+ms-clock.now;assert.ok(delta>=0,"The scenario clock only moves forward");v.step(delta);advance(delta);},
  hear(role,start,end,text){s.to(end);v.event({type:role==="user"?"session.input_transcript.delta":"session.output_transcript.delta",event_id:"event_"+(++events),delta:text,start_ms:start,end_ms:end});},
  lines(){return v.channels.at(-1).sent.filter(event=>event.type==="session.instructions.append");},
  transcript(){return h.t.state.turns.map(turn=>`${turn.role}: ${turn.text.trim()}`);},
  copies(text){return h.t.state.turns.filter(turn=>turn.text.includes(text)).length;},
  errors(){return Array.from(h.notices).filter(item=>item.error).map(item=>item.message);},
  posts(url){return Array.from(h.calls).filter(call=>call.url===url).map(call=>JSON.parse(call.options.body));},
  finding(key){return h.t.state.memo_findings.find(item=>item.key===key);},
  line(){return h.node("analysis-through").textContent;},
  // Stop talking, exactly as the button does it; the provider then confirms the close.
  press(){return stopTalking();},
  async closed(stopping){v.event({type:"session.closed"});await stopping;await settle();assert.equal(v.api.active,false);},
  async stop(){const stopping=s.press();await settle();await s.closed(stopping);},
  updateNotes(){assert.equal(typeof updateNotes,"function","The Notes panel has an Update notes control");return updateNotes();},
  // The capture that is on its way answers now.
  async land(index,extra){const capture=s.captures[index];capture.response.resolve(app.response(s.answer(capture.body,extra)));await settle();},
  // The first answer, captured while voice is on.
  async first(){s.hear("user",100,1500,FIRST);s.to(3200);await h.timer(400);await settle();
   assert.equal(s.captures.length,1);assert.equal(h.t.state.summary,"Notes with 1 topic","The first answer is in the notes");assert.equal(h.t.state.captureToken,"tok-1");}};
 h.route((url,options)=>{
  const other=s.extra?.(url,options);if(other)return other;
  if(url==="/api/agent-team/interview"){
   const capture={body:JSON.parse(options.body),signal:options.signal,response:null};s.captures.push(capture);
   if(s.fail)return {ok:false,status:s.fail.status,json:async()=>s.fail};
   if(s.hold){capture.response=onItsWay(options);return capture.response.promise;}
   return app.response(s.answer(capture.body));
  }
  if(url==="/api/agent-team/workflow")return app.response({workflow:{title:"",steps:[],connections:[],open_questions:[]}});
  if(url==="/api/draft"){s.drafts++;return {ok:false,status:503,json:async()=>({error:"No draft in this test."})};}
  return app.response({});
 });
 return s;
}
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,12).join("\n     "));}
}
(async()=>{
 const overload={status:502,code:"provider_unavailable",error:"The AI service is temporarily unavailable."};
 const timers=(s,ms)=>[...s.h.timers.values()].filter(timer=>timer.ms===ms).length;
 async function busyNotes(failure=overload){
  const s=await session();s.fail=failure;
  s.hear("user",100,1500,FIRST);s.to(3200);await s.h.timer(400);await settle();
  return s;
 }
 await check("an upstream overload retries without another answer and limits consecutive attempts",async()=>{
  const s=await busyNotes();
  assert.equal(s.captures.length,1);assert.deepEqual(s.errors(),[]);assert.equal(s.v.api.active,true);
  await s.h.timer(3000);await settle();assert.equal(s.captures.length,2);
  await s.h.timer(10000);await settle();assert.equal(s.captures.length,3);
  assert.equal(s.errors().length,1);assert.equal(timers(s,10000)+timers(s,3000)+timers(s,400),0);
  assert.equal(s.h.t.state.turns.filter(t=>t.role==="user").length,1);
  const recovered=await busyNotes();recovered.fail=null;
  await recovered.h.timer(3000);await settle();
  assert.equal(recovered.h.t.state.summary,"Notes with 1 topic");assert.deepEqual(recovered.errors(),[]);
 });
 await check("answers during backoff share one up-to-date retry and respect the provider wait",async()=>{
  const s=await busyNotes({...overload,retry_after_seconds:8});
  s.hear("assistant",3500,4500,"Who checks it?");s.hear("user",5000,6000,SECOND);s.to(7700);
  assert.equal(timers(s,400),0);assert.equal(timers(s,3000),0);assert.equal(timers(s,8000),1);
  s.fail=null;await s.h.timer(8000);await settle();
  assert.equal(s.captures.length,2);assert.equal(s.captures[1].body.turns.at(-1).text,SECOND);
  assert.equal(s.h.t.state.summary,"Notes with 2 topics");assert.equal(s.lines().length,0);
 });
 await check("ending or replacing voice cancels its retry timer",async()=>{
  const s=await busyNotes();s.fail=null;await s.stop();
  assert.equal(timers(s,3000),0);assert.equal(s.captures.length,2);assert.equal(s.h.t.state.summary,"Notes with 1 topic");
  const reset=await busyNotes();reset.h.t.clearState(null);await settle();
  assert.equal(timers(reset,3000),0);assert.equal(reset.captures.length,1);
 });
 await check("a permanent provider rejection does not retry its local 502 response",async()=>{
  const s=await busyNotes({status:502,code:"authentication",error:"Check the API key."});
  assert.equal(s.captures.length,1);assert.equal(s.errors().length,1);
  assert.equal(timers(s,3000)+timers(s,10000),0);assert.equal(s.v.api.active,true);
 });
 await check("an older in-flight map at Stop is followed by one map including the final spoken answer",async()=>{
  const s=await session();await s.first();
  s.h.t.state.config.api_configured=true;
  const older=app.deferred();let calls=0;
  const mapReply=()=>app.response({workflow:{title:"Test",steps:[],connections:[],open_questions:[]}});
  s.extra=url=>url==="/api/agent-team/workflow"?(++calls===1?older.promise:mapReply()):null;
  const running=s.h.t.refreshWorkflow();await settle();assert.equal(calls,1);
  s.hear("assistant",3500,4500,"Who checks it?");s.hear("user",5000,6000,SECOND);
  await s.stop();assert.equal(calls,1);
  older.resolve(mapReply());await running;await settle();await s.h.timer(1000);await settle();
  assert.equal(calls,2);assert.equal(s.posts("/api/agent-team/workflow")[1].turns.at(-1).text,SECOND);
  assert.equal(s.h.t.conversationUI.applied,s.h.t.conversationUI.revision);assert.equal(timers(s,1000),0);
 });
 await check("Stop talking while the capture of the last answer is on its way applies its notes when it returns",async()=>{
  const s=await session();await s.first();
  s.hear("assistant",3600,5200,"Got it. And who approves the list?");s.to(6900);
  s.hold=true;s.hear("user",7000,9000,SECOND);s.to(10700);await s.h.timer(400);await settle();
  assert.equal(s.captures.length,2,"The capture of the last answer is on its way");
  s.hear("assistant",10800,11600,"Thank you, that is clear."); // the interviewer answers while the notes capture runs
  const before=s.transcript();
  await s.stop();
  assert.equal(s.h.t.state.busy,true,"The capture that is still running is shown as work in progress");
  assert.equal(s.h.t.state.busyMessage,UPDATING);assert.equal(s.line(),UPDATING);
  assert.equal(s.captures.length,2,"The capture on its way is awaited, not repeated");assert.equal(s.captures[1].signal.aborted,false);
  await s.land(1);
  assert.equal(s.h.t.state.summary,"Notes with 2 topics","The paid response is used");
  assert.equal(s.finding("checks").answer,"The treasury analyst approves the list.");assert.equal(s.finding("checks").status,"partial");
  assert.equal(s.h.t.state.captureToken,"tok-2");assert.equal(s.h.t.state.coverageVerified,false,"Notes applied after voice are never a verified review");
  assert.deepEqual(s.transcript(),before,"The lead's proposed question is not added to the transcript");
  assert.equal(s.lines().length,0,"Nothing is handed to the voice session that has ended");assert.equal(s.posts("/api/agent-team/review").length,0);
  assert.equal(s.h.t.state.busy,false,"The busy state ends when the notes land");assert.deepEqual(s.errors(),[]);
  assert.equal(s.captures.length,2,"No further capture is needed");
  assert.equal(s.line(),"Notes include all 2 saved answers");assert.equal(s.h.node("update-notes").hidden,true);
 });
 await check("a caption that Stop talking finalizes is captured once, after voice has ended",async()=>{
  const s=await session();await s.first();
  s.hear("assistant",3600,5200,"Got it. And who approves the list?");s.to(6900);
  s.hold=true;s.hear("user",7000,9000,SECOND);s.to(9300); // 300 ms after the last words: the caption is still open
  assert.equal(s.captures.length,1,"No capture has run for the last answer");
  const before=s.transcript(),stopping=s.press();await settle();
  assert.equal(s.captures.length,1,"Nothing is sent before the transport has delivered its final captions");
  await s.closed(stopping);
  assert.equal(s.captures.length,2,"One catch-up capture is sent when voice has ended");
  const sent=s.captures[1].body;
  assert.equal(sent.action,"answer");assert.equal(sent.capture_token,"tok-1","The catch-up continues the capture the notes came from");
  assert.equal(sent.turns.at(-1).text,SECOND,"It carries the answer the stop finalized");
  assert.equal(s.posts("/api/conversation/turn").length,0,"It is a notes capture, not a typed interviewer turn");
  assert.equal(s.h.t.state.busy,true);assert.equal(s.h.t.state.busyMessage,UPDATING);assert.equal(s.line(),UPDATING);
  // Create draft and Continue talking wait for the notes.
  await s.h.t.generateDraft();assert.equal(s.drafts,0,"Create draft waits for the notes");
  await s.h.t.startLiveConversation();assert.equal(s.v.api.active,false,"Voice does not restart over the catch-up");
  await s.land(1);
  assert.equal(s.h.t.state.summary,"Notes with 2 topics");assert.equal(s.finding("checks").status,"partial");assert.equal(s.h.t.state.captureToken,"tok-2");
  assert.deepEqual(s.transcript(),before,"Nothing is added to the transcript");assert.equal(s.lines().length,0);
  assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);assert.equal(s.captures.length,2,"Exactly one catch-up");
  assert.equal(s.line(),"Notes include all 2 saved answers");
 });
 await check("a capture that began before the participant's last words is replaced by one catch-up capture",async()=>{
  const s=await session();s.hold=true;
  s.hear("user",100,1500,FIRST);s.to(3200);await s.h.timer(400);await settle();
  assert.equal(s.captures.length,1);
  s.hear("user",3400,5000,"Then the treasury analyst approves the list.");s.to(5300); // more of the answer while the capture runs
  await s.stop();
  assert.equal(s.captures[0].signal.aborted,true,"A capture that cannot include the last words is not waited for");
  assert.equal(s.captures.length,2,"One catch-up capture replaces it");
  assert.match(s.captures[1].body.turns.findLast(turn=>turn.role==="user").text,/Then the treasury analyst approves the list\./);
  assert.equal(s.h.t.state.busy,true);assert.equal(s.h.t.state.busyMessage,UPDATING);
  await s.land(1);
  assert.equal(s.h.t.state.summary,"Notes with 2 topics");assert.equal(s.h.t.state.busy,false);assert.equal(s.captures.length,2);assert.deepEqual(s.errors(),[]);
 });
 await check("a catch-up that fails says so, offers Update notes, and never calls the notes up to date",async()=>{
  const s=await session();await s.first();
  s.hear("user",3400,5000,"Then the treasury analyst approves the list.");s.to(5300);
  s.fail={status:503,error:"The model service is unavailable."};
  await s.stop();
  assert.equal(s.captures.length,2,"One catch-up, no silent retries");assert.equal(s.h.t.state.busy,false);
  assert.equal(s.errors().length,1,"The participant is told");assert.match(s.errors()[0],/Update notes/);assert.match(s.errors()[0],/The model service is unavailable\./);
  assert.equal(s.line(),BEHIND);assert.equal(s.h.node("update-notes").hidden,false,"The catch-up control is shown");
  assert.equal(s.h.t.state.summary,"Notes with 1 topic","The earlier notes are kept");
  // The map refresh of the last answer finishes: the map is up to date, the notes are not.
  s.h.node("coverage-update-status").textContent="Up to date";
  await s.h.t.refreshWorkflow();await settle();
  assert.equal(s.h.node("workflow-status").textContent,"Up to date");
  assert.notEqual(s.h.node("coverage-update-status").textContent,"Up to date","The notes are not called up to date while they lack the last answer");
  assert.equal(s.line(),BEHIND);
  // The control runs the catch-up again.
  s.fail=null;s.hold=true;s.updateNotes();await settle();
  assert.equal(s.captures.length,3);assert.equal(s.h.t.state.busy,true);assert.equal(s.line(),UPDATING);assert.equal(s.h.node("update-notes").hidden,true);
  await s.land(2);
  assert.equal(s.h.t.state.summary,"Notes with 2 topics");assert.equal(s.h.t.state.busy,false);
  assert.equal(s.line(),"Notes include all 1 saved answers");assert.equal(s.h.node("update-notes").hidden,true);assert.equal(s.errors().length,1);
  s.updateNotes();await settle();assert.equal(s.captures.length,3,"Update notes does nothing once the notes are current");
 });
 await check("once the typed interviewer has brought the notes up to date they are no longer reported as behind",async()=>{
  const s=await session();await s.first();
  s.hear("user",3400,5000,"Then the treasury analyst approves the list.");s.to(5300);
  s.fail={status:503,error:"The model service is unavailable."};
  await s.stop();
  assert.equal(s.line(),BEHIND);assert.equal(s.h.node("update-notes").hidden,false);
  // The participant carries on with the typed interviewer, whose background analysis reads the whole transcript.
  const token="c".repeat(64);
  s.extra=(url,options)=>url==="/api/conversation/turn"?app.response({...app.approved("What happens after the approval?"),preserve_capture:true,conversation_token:token,revision:"r1",sync_required:false}):
   url==="/api/conversation/status"?app.response({state:"ready",capture:notes(JSON.parse(options.body)),conversation_token:token,revision:"r1",workflow_state:"ready"}):null;
  await s.h.t.retryQuestion();await settle();
  assert.equal(s.h.t.state.turns.at(-1).text,"What happens after the approval?");
  await s.h.timer(650);await settle();
  assert.equal(s.h.t.state.summary,"Notes with 2 topics","The typed interviewer's analysis included the spoken answer");
  assert.equal(s.line(),"Notes include all 1 saved answers");assert.equal(s.h.node("update-notes").hidden,true);
  assert.equal(s.captures.length,2,"No further live capture was sent");
 });
 await check("Stop talking when the notes already include the last answer sends nothing and reports them as current",async()=>{
  const s=await session();await s.first();
  s.hear("assistant",3600,5200,"Got it. And who approves the list?");s.to(6900);
  await s.stop();
  assert.equal(s.captures.length,1,"No capture is repeated");assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);
  assert.equal(s.line(),"Notes include all 1 saved answers","The notes line does not claim an update that is not running");
  assert.equal(s.h.node("update-notes").hidden,true);
  // The map refresh that follows reports in Workflow; the notes line keeps saying what the notes include.
  s.h.node("coverage-update-status").textContent="";await s.h.t.refreshWorkflow();await settle();
  assert.equal(s.h.node("workflow-status").textContent,"Up to date");assert.equal(s.h.node("coverage-update-status").textContent,"","A refresh of the map alone says nothing about the notes");
  assert.equal(s.line(),"Notes include all 1 saved answers","Current notes are still reported as current");
  // A session in which nothing was said.
  const quiet=await session();await quiet.stop();
  assert.equal(quiet.captures.length,0);assert.equal(quiet.h.t.state.busy,false);assert.deepEqual(quiet.errors(),[]);
 });
 await check("a capture that returns the review acknowledgement after voice has ended updates the notes and starts no review",async()=>{
  const s=await session();s.hold=true;
  s.hear("user",100,1500,FIRST);s.to(3200);await s.h.timer(400);await settle();
  await s.stop();
  assert.equal(s.h.t.state.busy,true);
  await s.land(0,{...app.reviewAck(),summary:"Notes before the review",memo_findings:notes(s.captures[0].body).memo_findings});
  assert.equal(s.h.t.state.summary,"Notes before the review");assert.equal(s.h.t.state.captureToken,"capture-before-review");
  assert.equal(s.h.t.state.coverageVerified,false);assert.equal(s.copies(ACK),0,"No acknowledgement is added");
  assert.equal(s.posts("/api/agent-team/review").length,0,"No review starts");assert.equal(s.lines().length,0);
  assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);assert.equal(s.captures.length,1);
 });
 await check("a result that only repeats an earlier capture keeps that capture's token and adds no completion",async()=>{
  const s=await session();await s.first();
  s.hear("assistant",3600,5200,"Is there anything else we have not captured?");s.to(6900);
  s.hold=true;s.hear("user",7000,8000,"No, nothing else.");s.to(9700);await s.h.timer(400);await settle();
  assert.equal(s.captures.length,2);
  await s.stop();
  assert.equal(s.h.t.state.busy,true);assert.equal(s.line(),UPDATING);
  await s.land(1,{...app.approved(COMPLETE,"complete"),no_new_run:true,capture_token:"tok-complete",coverage_verified:true,closure:{asked:true,confirmed:true},
   memo_findings:notes(s.captures[0].body).memo_findings,summary:"Notes with 1 topic"});
  assert.equal(s.h.t.state.captureToken,"tok-1","The token of the capture the page still follows is kept");
  assert.equal(s.copies(COMPLETE),0);assert.equal(s.h.t.state.closure.confirmed,false);assert.equal(s.h.t.state.coverageVerified,false);
  assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);assert.equal(s.captures.length,2,"The answer counts as captured");
  assert.equal(s.line(),"Notes include all 2 saved answers");assert.equal(s.h.node("update-notes").hidden,true);
 });
 await check("a session that the provider closes catches the notes up as well",async()=>{
  const s=await session();await s.first();
  s.hold=true;s.hear("user",3400,5000,"Then the treasury analyst approves the list.");s.to(5300);
  s.v.event({type:"session.closed"});await settle(); // not Stop talking: the connection ended by itself
  assert.equal(s.v.api.active,false);assert.equal(s.errors().length,1);assert.match(s.errors()[0],/live voice session ended/i);
  assert.equal(s.captures.length,2);assert.equal(s.h.t.state.busy,true);
  await s.land(1);
  assert.equal(s.h.t.state.summary,"Notes with 2 topics");assert.equal(s.h.t.state.busy,false);assert.equal(s.errors().length,1);
 });
 await check("a new interview started while voice is on finishes nothing for the interview it replaces",async()=>{
  const s=await session();await s.first();
  s.hold=true;s.hear("user",3400,5000,"Then the treasury analyst approves the list.");s.to(5300);
  s.h.t.clearState(null);await settle(); // New interview: voice is stopped as part of clearing the page
  assert.equal(s.v.api.active,false);assert.equal(s.h.t.state.turns.length,0);
  assert.equal(s.captures.length,1,"No capture is sent for an interview that was replaced");assert.equal(s.h.t.state.busy,false);
 });
 await check("while voice is on a capture is applied as before and the notes line says what the notes include",async()=>{
  const s=await session();await s.first();
  s.h.t.renderAnalysisThrough();
  assert.equal(s.line(),"Notes include all 1 saved answers","After a capture the line no longer says an update is running");
  assert.equal(s.h.t.state.busy,false);assert.equal(s.h.node("update-notes").hidden,true);
  s.hear("assistant",3600,5200,"Got it. And who approves the list?");s.to(6900);
  s.hold=true;s.hear("user",7000,9000,SECOND);s.to(10700);await s.h.timer(400);await settle();
  s.h.t.renderAnalysisThrough();
  assert.equal(s.line(),"Notes through answer 1 of 2");assert.equal(s.h.t.state.busy,false,"Voice is on: the capture runs behind the conversation");
  await s.land(1);s.h.t.renderAnalysisThrough();
  assert.equal(s.line(),"Notes include all 2 saved answers");assert.equal(s.h.t.state.summary,"Notes with 2 topics");
  await s.v.api.stop({immediate:true});await settle();
  assert.equal(s.captures.length,2);assert.equal(s.h.t.state.busy,false);
 });
 await check("the lead's proposed question never replaces the notes label while the catch-up runs",async()=>{
  const s=await session();await s.first();
  // As the real lead does: its status reports the question it is drafting before the notes are finished.
  s.extra=url=>url==="/api/agent-team/status"?app.response({provisional_question:"What happens after the approval?"}):null;
  s.hear("assistant",3600,5200,"Got it. And who approves the list?");s.to(6900);
  s.hold=true;s.hear("user",7000,9000,SECOND);s.to(9300);
  await s.stop();
  assert.equal(s.captures.length,2);assert.equal(s.h.t.state.busy,true);
  await s.h.timer(150);await settle(); // the first status poll of the catch-up
  assert.ok(s.posts("/api/agent-team/status").length>=1,"The status of the capture was read");
  assert.equal(s.h.t.state.provisionalQuestion,null,"A question that will not be asked is not put on the progress line");
  assert.equal(s.h.t.state.busyMessage,UPDATING);
  // updateControls shows the busy message once neither a review nor a provisional question is set.
  assert.match(web("app.js"),/state\.provisionalQuestion \? `Up next: \$\{state\.provisionalQuestion\} — finishing the notes…` : state\.busyMessage \|\|/);
  const before=s.transcript();await s.land(1);
  assert.deepEqual(s.transcript(),before);assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);
 });
 await check("Continue talking after a failed catch-up takes the behind notice and its control off the screen",async()=>{
  const s=await session();await s.first();
  s.hear("assistant",3600,5200,"Got it. And who approves the list?");s.to(6900);
  s.hear("user",7000,9000,SECOND);s.to(9300);
  s.fail={status:503,error:"The model service is unavailable."};
  await s.stop();
  assert.equal(s.line(),BEHIND);assert.equal(s.h.node("update-notes").hidden,false);
  s.fail=null;
  await s.h.t.startLiveConversation();await settle();
  assert.equal(s.v.api.active,true);
  assert.equal(s.h.node("update-notes").hidden,true,"Update notes does nothing while voice is on, so it is not offered");
  assert.equal(s.line(),"Notes through answer 1 of 2","The notes line says what the notes include");
  await s.v.api.stop({immediate:true});await settle();
 });
 await check("after voice has ended a notes capture is waited for no longer than a minute and a half",async()=>{
  const waiting=s=>[...s.h.timers.values()].map(timer=>timer.ms);
  // The catch-up capture has its own, shorter deadline.
  const s=await session();await s.first();
  s.hold=true;s.hear("user",3400,5000,"Then the treasury analyst approves the list.");s.to(5300);
  await s.stop();
  assert.equal(s.captures.length,2);assert.equal(s.h.t.state.busy,true);
  assert.ok(waiting(s).includes(90000),"The catch-up is given 90 seconds");assert.ok(!waiting(s).includes(330000),"Not the 330 seconds of an interview turn");
  await s.h.timer(90000);await settle();
  assert.equal(s.captures[1].signal.aborted,true);assert.equal(s.h.t.state.busy,false,"The page is given back");
  assert.equal(s.errors().length,1);assert.match(s.errors()[0],/took too long/);assert.match(s.errors()[0],/Update notes/);
  assert.equal(s.line(),BEHIND);assert.equal(s.h.node("update-notes").hidden,false);assert.equal(s.captures.length,2,"No second attempt by itself");
  // A capture that voice ended on is given up after the same time.
  const k=await session();await k.first();
  k.hear("assistant",3600,5200,"Got it. And who approves the list?");k.to(6900);
  k.hold=true;k.hear("user",7000,9000,SECOND);k.to(10700);await k.h.timer(400);await settle();
  assert.equal(k.captures.length,2);assert.ok(!waiting(k).includes(90000),"While voice is on nothing is waited for");
  await k.stop();
  assert.equal(k.h.t.state.busy,true);assert.ok(waiting(k).includes(90000));
  await k.h.timer(90000);await settle();
  assert.equal(k.captures[1].signal.aborted,true);assert.equal(k.h.t.state.busy,false);
  assert.equal(k.errors().length,1);assert.match(k.errors()[0],/took too long/);
  assert.equal(k.line(),BEHIND);assert.equal(k.h.node("update-notes").hidden,false);assert.equal(k.captures.length,2,"No second attempt by itself");
  // Update notes still works afterwards, and a capture that lands in time leaves no deadline behind.
  k.updateNotes();await settle();assert.equal(k.captures.length,3);
  await k.land(2);assert.equal(k.h.t.state.summary,"Notes with 2 topics");assert.equal(k.h.t.state.busy,false);
  assert.ok(!waiting(k).includes(90000),"Nothing is left waiting");
 });
 await check("a pause reply leaves nothing pending on the notes line, during voice and after it",async()=>{
  const PAUSE="We will stop here and keep the unanswered parts open.";
  const s=await session();await s.first();
  s.hear("assistant",3600,5200,"Got it. And who approves the list?");s.to(6900);
  s.hold=true;s.hear("user",7000,9000,"Let us stop here for today.");s.to(10700);await s.h.timer(400);await settle();
  await s.stop();
  assert.equal(s.h.t.state.busy,true);
  await s.land(1,{...app.approved(PAUSE,"pause"),preserve_capture:true,capture_token:"tok-pause"});
  assert.equal(s.h.t.state.busy,false);assert.deepEqual(s.errors(),[]);assert.equal(s.captures.length,2,"The answer counts as captured");
  assert.equal(s.h.t.state.summary,"Notes with 1 topic","A pause reply carries no notes: the earlier notes stay");
  assert.equal(s.line(),"Notes kept through answer 1 · paused at your request","The line does not claim that an update is pending");
  assert.equal(s.h.node("update-notes").hidden,true);assert.equal(s.copies(PAUSE),0);
  // While voice is on the same reply is spoken, and the line says the same.
  const k=await session();await k.first();
  k.answer=(body,extra)=>({...notes(body),...app.approved(PAUSE,"pause"),preserve_capture:true,capture_token:"tok-pause",...extra});
  k.hear("assistant",3600,5200,"Got it. And who approves the list?");k.to(6900);
  k.hear("user",7000,9000,"Let us stop here for today.");k.to(10700);await k.h.timer(400);await settle();
  assert.equal(k.captures.length,2);assert.equal(k.copies(PAUSE),1);
  k.h.t.renderAnalysisThrough();
  assert.equal(k.line(),"Notes kept through answer 1 · paused at your request");
  await k.v.api.stop({immediate:true});await settle();
  assert.equal(k.captures.length,2,"Nothing is left to catch up");assert.equal(k.h.t.state.busy,false);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
