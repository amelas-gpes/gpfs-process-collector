"use strict";
// Application-authorized lines in Live voice: the real caption controller
// (web/live-voice.js) feeds the real transcript path (web/app.js receiveLiveCaption,
// applyLiveCapture, the Stop talking handler) on one virtual clock. WebRTC, the page
// and the provider are the local fakes of the existing suites; no network is used.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");

// The controller's timers and the application's Date share this clock, so "10 seconds
// later" and "25 seconds later" are exact and take no real time.
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
// The Stop talking handler is taken from app.js itself, as tests/test_ui_state.cjs does.
const stopBinding=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8").split("\n").filter(line=>/\$\("stop-live"\)\.addEventListener/.test(line)).join("\n");
assert.ok(stopBinding,"app.js binds the Stop talking control");
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(source.includes("setTeam:value=>"),"The application test seam is available");
source=source.replace("setTeam:value=>",()=>"receiveLiveCaption,applyLiveCapture,liveSnapshot,authorizeLiveUtterance,bindStop:()=>{"+stopBinding+"},setTeam:value=>");
const app=exported(source,"\nmodule.exports={setup,approved,response,flush,reviewAck,deferred};");

const ACK="Let me check that I have everything before we finish.";
const FINAL_CHECK="Is there anything else someone doing this work needs to know that we haven't captured?";
const PAUSE="We will stop here and keep the unanswered parts open.";
let events=0;
const settle=async()=>{for(let i=0;i<6;i++)await app.flush();};
// One live session: the controller is connected exactly as app.js connects it
// (onTranscript:receiveLiveCaption, onError:message=>notice(message,true)).
async function session(){
 const turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
 const v=voice.setup();assert.equal(await v.api.start({turns}),true);
 const h=app.setup();
 h.t.state.config.agent_team.voice_mode="live_front";h.t.state.config.concurrent_interview={enabled:true};
 h.t.state.turns=turns.map(turn=>({...turn}));h.t.conversationUI.live=v.api;
 v.captions.push=caption=>{Array.prototype.push.call(v.captions,caption);h.t.receiveLiveCaption(caption);return v.captions.length;};
 v.errors.push=message=>{Array.prototype.push.call(v.errors,message);h.notices.push({message,error:true});return v.errors.length;};
 const origin=clock.now;
 const s={v,h,
  to(ms){const delta=origin+ms-clock.now;assert.ok(delta>=0,"The scenario clock only moves forward");v.step(delta);advance(delta);},
  hear(role,start,end,text){s.to(end);v.event({type:role==="user"?"session.input_transcript.delta":"session.output_transcript.delta",event_id:"event_"+(++events),delta:text,start_ms:start,end_ms:end});},
  lines(){return v.channels.at(-1).sent.filter(event=>event.type==="session.instructions.append");},
  acknowledge(ms){s.to(ms);const sent=s.lines().at(-1);assert.ok(sent,"A line was handed to the interviewer");v.event({type:"session.instructions.appended",client_event_id:sent.event_id,start_ms:ms});return sent.event_id;},
  transcript(){return h.t.state.turns.map(turn=>`${turn.role}: ${turn.text.trim()}`);},
  copies(text){return h.t.state.turns.filter(turn=>turn.text.includes(text)).length;},
  errors(){return Array.from(h.notices).filter(item=>item.error).map(item=>item.message);}};
 return s;
}
// A line issued by the application the way a background capture issues it.
async function authorize(s,line,kind,ms){
 s.to(ms);
 assert.equal(await s.h.t.applyLiveCapture({...app.approved(line,kind),coverage_verified:true},s.h.t.liveSnapshot()),true);
 assert.ok(s.lines().at(-1).content.includes(JSON.stringify(line)),"The exact line is handed to the interviewer");
 return s.acknowledge(ms+100);
}
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,12).join("\n     "));}
}
(async()=>{
 await check("the reading of an acknowledged line is a caption of its own, tagged with that line",async()=>{
  const v=voice.setup();await v.api.start({turns:[{id:"t001",role:"assistant",text:"What starts the work?"}]});
  const say=(type,delta,start_ms,end_ms)=>v.event({type:`session.${type}_transcript.delta`,event_id:"event_"+(++events),delta,start_ms,end_ms});
  say("input","An email starts it.",100,900);
  say("output","Got it. And who approves",1200,2400);
  const earlier=v.captions.at(-1).id;
  const receipt=v.api.say(ACK),sent=v.channels.at(-1).sent.filter(event=>event.type==="session.instructions.append").at(-1);
  // The interviewer was still finishing its own sentence when the line was handed over.
  say("output"," the list?",2400,2900);
  assert.equal(v.captions.at(-1).id,earlier,"Speech before the acknowledgement still belongs to the interviewer's own caption");
  assert.equal(v.captions.at(-1).authorized,undefined);
  v.event({type:"session.instructions.appended",client_event_id:sent.event_id,start_ms:3000});
  assert.equal((await receipt).status,"acknowledged");
  // No participant speech in between: before the fix the reading extended the earlier caption.
  say("output","Let me check that I have everything",3200,4600);
  const reading=v.captions.at(-1);
  assert.notEqual(reading.id,earlier,"The reading never extends an earlier interviewer caption");
  assert.equal(reading.authorized,sent.event_id,"The reading is tagged with the line it reads");
  assert.equal(reading.text,"Let me check that I have everything");
  const closed=v.captions.filter(caption=>caption.id===earlier).at(-1);
  assert.equal(closed.text,"Got it. And who approves the list?","The earlier caption is closed unchanged");assert.equal(closed.final,true);
  say("output"," before we finish",4600,5400);say("output",".",5400,5450);
  assert.equal(v.captions.at(-1).id,reading.id);assert.equal(v.captions.at(-1).text,ACK,"Punctuation stays with the line");
  // The interviewer's own words after the line, again with no participant speech in between.
  say("output"," While I check, is there anything about approvals you want to add?",9000,12000);
  const own=v.captions.at(-1);
  assert.notEqual(own.id,reading.id,"A tagged caption holds no more than the line");assert.equal(own.authorized,undefined);
  assert.equal(own.text,"While I check, is there anything about approvals you want to add?");
  await v.api.stop({immediate:true});
  const last=id=>v.captions.filter(caption=>caption.id===id).at(-1);
  assert.equal(last(reading.id).final,true);assert.equal(last(reading.id).authorized,sent.event_id,"Every emission of the reading carries the tag, including the one at cleanup");
  assert.equal(last(own.id).authorized,undefined);
 });
 await check("a line the provider did not accept tags nothing",async()=>{
  const v=voice.setup();await v.api.start({turns:[{id:"t001",role:"assistant",text:"What starts the work?"}]});
  const say=(type,delta,start_ms,end_ms)=>v.event({type:`session.${type}_transcript.delta`,event_id:"event_"+(++events),delta,start_ms,end_ms});
  say("output","Who approves the list?",1000,2000);const earlier=v.captions.at(-1).id;
  const receipt=v.api.say(ACK),sent=v.channels.at(-1).sent.filter(event=>event.type==="session.instructions.append").at(-1);
  v.event({type:"error",error:{client_event_id:sent.event_id}});assert.equal((await receipt).status,"rejected");
  say("output"," And where is that recorded?",2600,3600);
  assert.equal(v.captions.at(-1).id,earlier);assert.equal(v.captions.at(-1).authorized,undefined);
  assert.equal(v.captions.at(-1).text,"Who approves the list? And where is that recorded?");
  await v.api.stop({immediate:true});assert.ok(v.captions.every(caption=>caption.authorized===undefined));
 });
 await check("when the participant speaks before the line is read, the interviewer's next words are recorded",async()=>{
  const v=voice.setup();await v.api.start({turns:[{id:"t001",role:"assistant",text:"What starts the work?"}]});
  const say=(type,delta,start_ms,end_ms)=>v.event({type:`session.${type}_transcript.delta`,event_id:"event_"+(++events),delta,start_ms,end_ms});
  say("input","An email starts it.",100,900);v.step(4000);
  const receipt=v.api.say(FINAL_CHECK),sent=v.channels.at(-1).sent.filter(event=>event.type==="session.instructions.append").at(-1);
  v.event({type:"session.instructions.appended",client_event_id:sent.event_id,start_ms:4100});assert.equal((await receipt).status,"acknowledged");
  say("input","Sorry, one more thing about refunds.",4300,6000);
  say("output","Of course. What happens with refunds?",6400,8000);
  assert.equal(v.captions.at(-1).authorized,undefined,"A reply to the participant is not taken for the reading");
  await v.api.stop({immediate:true});
 });
 await check("an uncovered topic selected by the reviewers is issued once in Live",async()=>{
  const s=await session(),question="Who receives the registrar's exception list?";
  s.h.route(url=>url==="/api/agent-team/interview"?app.response(app.reviewAck()):url==="/api/agent-team/review"?app.response({...app.approved(question),coverage_verified:true}):app.response({}));
  s.hear("user",100,1500,"An email from the registrar starts it.");s.to(3200);await s.h.timer(400);await settle();
  s.acknowledge(3500);s.hear("assistant",3900,6900,ACK);s.to(9000);await settle();
  assert.equal(s.copies(question),1);
  assert.equal(s.lines().filter(event=>event.content.includes(question)).length,1);
  await s.v.api.stop({immediate:true});
 });
 await check("the acknowledgement after a GPT-Live follow-up leaves recorded turns alone and the review returns",async()=>{
  const s=await session(),review=app.deferred();
  s.h.route(url=>url==="/api/agent-team/interview"?app.response(app.reviewAck()):url==="/api/agent-team/review"?review.promise:app.response({}));
  s.hear("user",100,1500,"An email from the client starts it.");
  s.hear("assistant",1800,3600,"Got it. And who approves the list?");
  s.to(5300); // both captions reach their quiet checkpoint; the final answer schedules the background capture
  await s.h.timer(400);await settle();
  assert.equal(s.h.t.state.turns.at(-1).text,ACK,"The application records the acknowledgement as the interviewer's turn");
  assert.equal(s.lines().length,1);
  s.acknowledge(5400);
  // GPT-Live reads the line; nobody has spoken since its own follow-up.
  s.hear("assistant",5600,7000,"Let me check that I have");s.hear("assistant",7000,8600," everything before we finish.");
  s.to(10300);
  assert.deepEqual(s.transcript(),["assistant: What starts the work?","user: An email from the client starts it.","assistant: Got it. And who approves the list?","assistant: "+ACK],
   "The reading neither rewrites the recorded follow-up nor repeats the line");
  review.resolve(app.response({...app.approved(FINAL_CHECK,"final_check"),coverage_verified:true}));await settle();
  assert.equal(s.h.t.state.closure.asked,true,"The finished review issues the final check");
  assert.equal(s.h.t.state.turns.at(-1).text,FINAL_CHECK);assert.equal(s.lines().length,2,"The final check is handed to the interviewer");
  assert.equal(s.copies(ACK),1);assert.deepEqual(s.errors(),[]);
  await s.v.api.stop({immediate:true});
 });
 await check("a GPT-Live follow-up inside 20 seconds of an authorized line is recorded where it was asked",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"An email from the client starts it.");s.to(3200);
  await authorize(s,FINAL_CHECK,"final_check",4000);
  s.hear("assistant",4500,8500,FINAL_CHECK);
  s.hear("user",10000,12000,"Yes, the treasury team signs off first.");
  s.hear("assistant",13000,16000,"Who on the treasury team signs off, and what do they check?"); // 12 seconds after the line
  s.hear("user",17000,20000,"The treasury analyst, she checks the bank balance.");
  assert.deepEqual(s.transcript().slice(2),["assistant: "+FINAL_CHECK,"user: Yes, the treasury team signs off first.",
   "assistant: Who on the treasury team signs off, and what do they check?","user: The treasury analyst, she checks the bank balance."]);
  s.to(60000);await s.v.api.stop({immediate:true});
  assert.equal(s.copies("Who on the treasury team"),1);assert.equal(s.copies(FINAL_CHECK),1);assert.deepEqual(s.errors(),[]);
 });
 await check("a reply more than 20 seconds after an authorized line does not bring the reading back",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"An email from the client starts it.");s.to(3200);
  await authorize(s,FINAL_CHECK,"final_check",4000);
  s.hear("assistant",4500,8500,"Is there anything else someone doing this work needs to know that we have not captured?"); // GPT-Live's own wording of the line
  s.hear("user",30000,33000,"No, I think that is everything."); // 26 seconds after the line
  s.hear("assistant",34000,36000,"Understood, thank you."); // the controller now closes the reading's caption and emits it again
  s.to(40000);
  assert.deepEqual(s.transcript().slice(2),["assistant: "+FINAL_CHECK,"user: No, I think that is everything.","assistant: Understood, thank you."]);
  assert.equal(s.h.t.state.turns.filter(turn=>/anything else someone doing this work/.test(turn.text)).length,1,"One copy of the final check");
  await s.v.api.stop({immediate:true});
  assert.equal(s.h.t.state.turns.filter(turn=>/anything else someone doing this work/.test(turn.text)).length,1,"Cleanup emits the reading once more; it is still not added");
 });
 await check("Stop talking after an authorized line does not repeat the line",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  let stopTalking=null;s.h.node("stop-live").addEventListener=(type,listener)=>{if(type==="click")stopTalking=listener;};
  s.h.t.bindStop();assert.equal(typeof stopTalking,"function");
  s.hear("user",100,1500,"That is all I know about it.");s.to(3200);
  await authorize(s,PAUSE,"pause",4000);
  s.hear("assistant",4500,7500,"We'll stop here and keep the unanswered parts open."); // GPT-Live's own wording of the line
  s.to(9200);const before=s.transcript();
  s.to(13500);const stopping=stopTalking();await settle();
  s.v.event({type:"session.closed"});await stopping;await settle(); // cleanup emits every open caption once more
  assert.equal(s.v.api.active,false);
  assert.deepEqual(s.transcript(),before,"Stopping adds nothing to the transcript");
  assert.equal(s.h.t.state.turns.filter(turn=>/stop here and keep the unanswered parts open/.test(turn.text)).length,1);
  assert.deepEqual(s.errors(),[]);
 });
 await check("a line that could not be handed to the interviewer is announced and suppresses nothing",async()=>{
  // Longer than the controller accepts: say() answers rejected/invalid_text without a notice of its own.
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"That is all I know about it.");s.to(3200);
  const long="The remaining sections need information you do not have here: "+"Owner; Checks and controls; Variations; ".repeat(31)+"We can keep this as a partial capture.";
  assert.ok(long.length>1200);
  s.h.t.authorizeLiveUtterance(long);await settle();
  assert.equal(s.lines().length,0);
  assert.equal(s.errors().length,1,"The participant is told the line was not spoken");assert.match(s.errors()[0],/transcript/i);
  s.hear("assistant",6000,8000,"Is there anything you would like to add?"); // 3 seconds later
  assert.equal(s.transcript().at(-1),"assistant: Is there anything you would like to add?","Nothing is suppressed for a line that was never delivered");
  await s.v.api.stop({immediate:true});
  // Voice already ended: say() answers unavailable.
  const ended=await session();await ended.v.api.stop({immediate:true});
  ended.h.t.authorizeLiveUtterance(ACK);await settle();
  assert.equal(ended.h.t.state.turns.at(-1).text,ACK);assert.equal(ended.errors().length,1);assert.match(ended.errors()[0],/transcript/i);
  // The provider refuses the line: the controller reports it once and the application does not repeat that.
  const refused=await session();refused.h.route(()=>app.response({}));
  refused.hear("user",100,1500,"That is all I know about it.");refused.to(3200);
  refused.h.t.authorizeLiveUtterance(ACK);
  refused.v.event({type:"error",error:{client_event_id:refused.lines().at(-1).event_id,message:"private provider detail"}});await settle();
  assert.equal(refused.errors().length,1);assert.match(refused.errors()[0],/next line/);
  refused.hear("assistant",5000,7000,"What else should I know?");
  assert.equal(refused.transcript().at(-1),"assistant: What else should I know?");
  await refused.v.api.stop({immediate:true});
 });
 // The reading is recognised by its words, not by its position after the acknowledgement.
 await check("the rest of GPT-Live's own sentence after the acknowledgement is recorded, and the reading is not",async()=>{
  const s=await session(),review=app.deferred();
  s.h.route(url=>url==="/api/agent-team/interview"?app.response(app.reviewAck()):url==="/api/agent-team/review"?review.promise:app.response({}));
  s.hear("user",100,1500,"An email from the client starts it.");
  s.hear("assistant",1800,3100,"So the email comes in first. And who approves");
  s.to(3200);await s.h.timer(400);await settle(); // the capture returns the acknowledgement while GPT-Live is in mid-sentence
  assert.equal(s.lines().length,1);s.acknowledge(3300);
  s.hear("assistant",3300,4300," the list before it is sent?");
  s.hear("assistant",4800,6000,"Let me check that I have");s.hear("assistant",6000,7600," everything before we finish.");
  s.to(9500);
  assert.deepEqual(s.transcript(),["assistant: What starts the work?","user: An email from the client starts it.",
   "assistant: So the email comes in first. And who approves the list before it is sent?","assistant: "+ACK],"The interviewer's own question is whole and the line appears once");
  await s.v.api.stop({immediate:true});assert.equal(s.copies("before we finish"),1);
 });
 await check("a participant backchannel during the reading leaves no part of the reading as a turn",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"That is all I know about it.");s.to(3200);
  const line=await authorize(s,FINAL_CHECK,"final_check",4000);
  s.hear("assistant",4500,6000,"Is there anything else someone doing this work");
  s.hear("user",6000,6300,"Mm-hmm.");
  s.hear("assistant",6300,8500," needs to know that we haven't captured?");
  s.hear("user",9500,10500,"No, nothing else.");
  s.to(12500);
  assert.deepEqual(s.transcript().slice(2),["assistant: "+FINAL_CHECK,"user: Mm-hmm.","user: No, nothing else."],"The answer to the line is a turn of its own, below the backchannel");
  const tagged=s.v.captions.filter(caption=>caption.authorized===line);
  assert.equal(new Set(tagged.map(caption=>caption.id)).size,2,"Both parts of the reading are tagged with the line");
  await s.v.api.stop({immediate:true});assert.equal(s.copies("haven't captured"),1);
 });
 await check("when the participant goes on talking after the line was issued, its later reading is still not repeated",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"That is all I know about it.");s.to(3200);
  await authorize(s,FINAL_CHECK,"final_check",4000);
  s.hear("user",4200,5200,"Oh, and the bank confirms.");
  s.hear("assistant",5600,9500,FINAL_CHECK); // GPT-Live reads the line after the interjection
  s.to(12000);
  assert.deepEqual(s.transcript().slice(2),["assistant: "+FINAL_CHECK,"user: Oh, and the bank confirms."]);
  await s.v.api.stop({immediate:true});assert.equal(s.copies(FINAL_CHECK),1);
  // No timestamps on the participant's fragment: nothing changes.
  const bare=await session();bare.h.route(()=>app.response({}));
  bare.hear("user",100,1500,"That is all I know about it.");bare.to(3200);
  await authorize(bare,FINAL_CHECK,"final_check",4000);
  bare.to(5200);bare.v.event({type:"session.input_transcript.delta",event_id:"event_"+(++events),delta:"Hello?"});
  bare.hear("assistant",5600,9500,FINAL_CHECK);bare.to(12000);
  await bare.v.api.stop({immediate:true});assert.equal(bare.copies(FINAL_CHECK),1);
 });
 await check("a reading with extra words stays one tagged caption and an exact rereading is required before review",async()=>{
  const s=await session(),review=app.deferred();
  s.h.route(url=>url==="/api/agent-team/interview"?app.response(app.reviewAck()):url==="/api/agent-team/review"?review.promise:app.response({}));
  s.hear("user",100,1500,"An email from the client starts it.");
  s.to(3300);await s.h.timer(400);await settle();s.acknowledge(3500);
  let at=3800;("Alright, "+ACK).split(" ").forEach((word,index)=>{s.hear("assistant",at,at+200,(index?" ":"")+word);at+=200;});
  s.to(at+2000);
  assert.deepEqual(s.transcript(),["assistant: What starts the work?","user: An email from the client starts it.","assistant: "+ACK],"No word of the reading is a turn");
  assert.equal(s.v.captions.at(-1).text,"Alright, "+ACK,"The tagged caption holds the whole reading, to its last word");assert.ok(s.v.captions.at(-1).authorized);
  assert.equal(s.h.t.state.closure.asked,false,"A reading with extra words cannot release the review");
  assert.equal(s.h.calls.filter(c=>c.url==="/api/agent-team/review").length,0);
  await s.v.api.stop({immediate:true});
 });
 await check("a provider that never acknowledges a line still has its reading recognised, and Stop reports nothing",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"That is all I know about it.");s.to(4000);
  assert.equal(await s.h.t.applyLiveCapture({...app.approved(FINAL_CHECK,"final_check"),coverage_verified:true},s.h.t.liveSnapshot()),true);
  s.hear("assistant",4500,8500,FINAL_CHECK); // read before, or without, any acknowledgement event
  assert.equal(s.v.captions.at(-1).authorized,s.lines().at(-1).event_id);
  s.hear("user",10000,12000,"No, that is everything.");s.to(15000);
  await s.v.api.stop({immediate:true});await settle();
  assert.equal(s.copies(FINAL_CHECK),1);assert.deepEqual(s.errors(),[],"Hearing the line read confirms its delivery");
 });
 await check("a line that is neither confirmed nor read is reported once, and the interviewer's later words are recorded",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"That is all I know about it.");s.to(4000);
  assert.equal(await s.h.t.applyLiveCapture({...app.approved(FINAL_CHECK,"final_check"),coverage_verified:true},s.h.t.liveSnapshot()),true);
  s.to(18000);await settle();assert.deepEqual(s.errors(),[],"Not before the time allowed for a confirmation");
  s.to(19500);await settle();
  assert.equal(s.errors().length,1);assert.match(s.errors()[0],/did not confirm/);assert.match(s.errors()[0],/transcript/i);
  // 40 seconds later GPT-Live speaks in its own words: nothing of it is taken for the reading.
  s.hear("assistant",44000,46000,"Are you still there? Take your time.");s.to(49000);
  assert.equal(s.transcript().at(-1),"assistant: Are you still there? Take your time.");
  await s.v.api.stop({immediate:true});await settle();
  assert.equal(s.errors().length,1,"Stop does not report the same line again");assert.equal(s.copies("Are you still there"),1);
  // The same when the line was acknowledged but never read.
  const read=await session();read.h.route(()=>app.response({}));
  read.hear("user",100,1500,"That is all I know about it.");read.to(3200);
  await authorize(read,FINAL_CHECK,"final_check",4000);
  read.hear("assistant",44000,46000,"Are you still there? Take your time.");read.to(49000);
  assert.equal(read.transcript().at(-1),"assistant: Are you still there? Take your time.");assert.deepEqual(read.errors(),[]);
  await read.v.api.stop({immediate:true});
 });
 await check("the interviewer's own words are never taken for a reading they only resemble",async()=>{
  const v=voice.setup();await v.api.start({turns:[{id:"t001",role:"assistant",text:"What starts the work?"}]});
  const say=(type,delta,start_ms,end_ms)=>v.event({type:`session.${type}_transcript.delta`,event_id:"event_"+(++events),delta,start_ms,end_ms});
  const shown=()=>{const order=[];for(const caption of v.captions)if(!order.includes(caption.id))order.push(caption.id);
   return order.map(id=>{const caption=v.captions.filter(item=>item.id===id).at(-1);return (caption.authorized?"line: ":caption.role+": ")+caption.text;});};
  say("input","An email starts it.",100,900);
  v.api.say(ACK);
  // Begins like the line and goes elsewhere, word by word: held back while undecided, then recorded whole.
  let at=1200;"Let me check the invoice number first.".split(" ").forEach((word,index)=>{say("output",(index?" ":"")+word,at,at+200);at+=200;});
  assert.deepEqual(shown(),["user: An email starts it.","assistant: Let me check the invoice number first."]);
  // A single word and nothing more: recorded after a moment, not lost.
  say("input","Okay.",3000,3300);say("output","Right.",3500,3700);
  assert.equal(shown().length,3,"One word is too short to tell yet");
  advance(1100);
  assert.deepEqual(shown().slice(2),["user: Okay.","assistant: Right."]);
  // One delta that ends the interviewer's sentence, reads the line and goes on.
  say("output"," That is good. Let me check that I have everything before we finish. Meanwhile, what else?",5000,9000);
  assert.deepEqual(shown().slice(3),["assistant: Right. That is good.","line: "+ACK,"assistant: Meanwhile, what else?"]);
  // The line has been read: the interviewer repeating it later is its own speech.
  say("input","Sorry, what did you say?",9500,10500);say("output",ACK,11000,13000);
  assert.equal(shown().at(-1),"assistant: "+ACK);
  await v.api.stop({immediate:true});
 });
 await check("a reading cut short by the next line, and a reading in parts of words, are both left out",async()=>{
  const s=await session();s.h.route(()=>app.response({}));
  s.hear("user",100,1500,"That is all I know about it.");s.to(3200);
  await authorize(s,ACK,"pause",4000);
  s.hear("assistant",4500,5000,"Let me check");
  await authorize(s,FINAL_CHECK,"final_check",5200);
  s.hear("assistant",5400,6500," that I have everything before we fin");s.hear("assistant",6500,6700,"ish.");
  s.hear("assistant",7000,11000," "+FINAL_CHECK);s.to(14000);
  assert.deepEqual(s.transcript().slice(2),["assistant: "+ACK,"assistant: "+FINAL_CHECK]);
  await s.v.api.stop({immediate:true});assert.equal(s.copies(FINAL_CHECK),1);assert.equal(s.copies("before we finish"),1);
  // A word after the last word of the line, word by word: the reading ends with its sentence.
  const k=await session();k.h.route(()=>app.response({}));
  k.hear("user",100,1500,"That is all I know about it.");k.to(3200);
  await authorize(k,FINAL_CHECK,"final_check",4000);
  let at=4500;FINAL_CHECK.replace("captured?","captured yet?").split(" ").forEach((word,index)=>{k.hear("assistant",at,at+200,(index?" ":"")+word);at+=200;});
  k.hear("assistant",at+100,at+900," Take your time.");k.to(at+3000);
  assert.deepEqual(k.transcript().slice(2),["assistant: "+FINAL_CHECK,"assistant: Take your time."]);
  await k.v.api.stop({immediate:true});
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
