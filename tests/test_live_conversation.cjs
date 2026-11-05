"use strict";
// Replay the actual caption controller and app capture path, including delayed
// responses. Media/provider boundaries are local fakes; no network is used.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
source=source.replace("setTeam:value=>","runLiveCapture,applyLiveCapture,liveSnapshot,syncLiveCoverage,refreshWorkflow,getCapturedThrough:()=>liveCapturedThrough,setTeam:value=>");
const app=exported(source,"\nmodule.exports={setup,approved,response,flush};");
const captureCalls=h=>h.calls.filter(c=>c.url==="/api/agent-team/interview");
function fixture(){
 const h=app.setup();h.notes=[];h.said=[];
 h.t.state.config.agent_team.voice_mode="live_front";h.t.state.config.concurrent_interview={enabled:true};
 h.t.conversationUI.live={active:true,participantSpeaking:false,assistantSpeaking:false,
   appendContext(text){h.notes.push(text);return Promise.resolve({status:"acknowledged"});},say(text){h.said.push(text);return Promise.resolve({status:"acknowledged"});}};
 h.t.state.turns=[{id:"u1",role:"user",text:"We"}];h.t.conversationUI.revision=1;h.t.state.summary="Last accepted notes";
 return h;
}
let passed=0;
async function check(name,fn){await fn();passed++;console.log("PASS "+name);}
(async()=>{
 await check("listening cues and delayed fragments keep one participant answer",async()=>{
  const h=voice.setup();await h.api.start();
  h.event({type:"session.input_transcript.delta",event_id:"u1",delta:"We",start_ms:100,end_ms:300});
  h.event({type:"session.output_transcript.delta",event_id:"a1",delta:"Mm.",start_ms:250,end_ms:450});
  assert.equal(h.captions.filter(c=>c.role==="user"&&c.final).length,0);
  h.event({type:"session.input_transcript.delta",event_id:"u2",delta:" keep everything documented",start_ms:500,end_ms:1100});
  h.event({type:"session.output_transcript.delta",event_id:"a2",delta:"Mm-hmm.",start_ms:1000,end_ms:1200});
  h.event({type:"session.output_transcript.delta",event_id:"a3",delta:" Go ahead.",start_ms:1250,end_ms:1400});
  h.event({type:"session.output_transcript.delta",event_id:"a4",delta:" Got it, thanks. Good to know.",start_ms:1450,end_ms:1700});
  h.event({type:"session.input_transcript.delta",event_id:"u3",delta:" on our documentation site",start_ms:2000,end_ms:2600});
  h.event({type:"session.input_transcript.delta",event_id:"u4",delta:".",start_ms:2600,end_ms:2620});
  const users=h.captions.filter(c=>c.role==="user");
  assert.equal(new Set(users.map(c=>c.id)).size,1);
  assert.equal(users.at(-1).text,"We keep everything documented on our documentation site.");
  assert.equal(users.filter(c=>c.final).length,0);
  await h.api.stop({immediate:true});
 });
 await check("a substantive interviewer question starts a separate next answer",async()=>{
  const h=voice.setup();await h.api.start();
  h.event({type:"session.input_transcript.delta",event_id:"u1",delta:"Capital calls.",start_ms:100,end_ms:400});
  const first=h.captions.at(-1).id;
  h.event({type:"session.output_transcript.delta",event_id:"a1",delta:"Talk me through how a call normally goes.",start_ms:700,end_ms:1600});
  h.event({type:"session.input_transcript.delta",event_id:"u2",delta:"The client asks for a call.",start_ms:1900,end_ms:2800});
  assert.notEqual(h.captions.at(-1).id,first);
  assert.equal(h.captions.at(-1).text,"The client asks for a call.");
  await h.api.stop({immediate:true});
 });
 await check("microphone activity holds a quiet text checkpoint",async()=>{
  const h=voice.setup({metering:true});await h.api.start();h.streams[0].level=.05;h.step(20);
  h.event({type:"session.input_transcript.delta",event_id:"u1",delta:"When",start_ms:0,end_ms:100});
  await new Promise(resolve=>setTimeout(resolve,1580));
  assert.equal(h.captions.filter(c=>c.role==="user"&&c.final).length,0);
  h.event({type:"session.input_transcript.delta",event_id:"u2",delta:" the bank confirms receipt.",start_ms:200,end_ms:700});
  assert.equal(h.captions.at(-1).text,"When the bank confirms receipt.");
  await h.api.stop({immediate:true});
 });
 await check("notes from a fragment cannot overwrite a completed answer or suppress catch-up",async()=>{
  const h=fixture();let resolve;h.route(()=>new Promise(r=>resolve=r));
  const old=h.t.runLiveCapture();await app.flush();
  assert.equal(JSON.parse(captureCalls(h)[0].options.body).turns[0].text,"We");
  h.t.state.turns[0].text="We keep everything documented on the documentation site.";h.t.conversationUI.revision++;
  resolve(app.response({...app.approved("What were you going to add?"),summary:"Only the fragment We was analysed.",capture_token:"stale-token"}));await old;await app.flush();
  assert.equal(h.t.state.summary,"Last accepted notes");assert.notEqual(h.t.state.captureToken,"stale-token");
  assert.equal(h.t.getCapturedThrough(),null);assert.equal(h.t.conversationUI.coverageCheckpoint,null);assert.equal(h.notes.length,0);
  const latest=h.t.runLiveCapture();await app.flush();assert.equal(captureCalls(h).length,2);
  assert.equal(JSON.parse(captureCalls(h)[1].options.body).turns[0].text,h.t.state.turns[0].text);
  resolve(app.response({...app.approved("What does that procedure cover?"),summary:"Documentation exists; it was not reviewed.",memo_findings:[{key:"materials",status:"partial",answer:"The participant reports a procedure on the documentation site; it has not been reviewed.",evidence_turns:["u1"]}]}));
  await latest;assert.equal(h.t.state.summary,"Documentation exists; it was not reviewed.");
  assert.equal(h.t.conversationUI.coverageCheckpoint.basis,JSON.stringify([["u1",h.t.state.turns[0].text]]));
  assert.equal(h.t.state.liveSuggestedQuestion,"");assert(h.notes.length>0);assert(h.notes.every(n=>!n.includes("What does that procedure cover")&&!n.includes("I ask:")));
 });
 await check("new answers and document changes invalidate old completion authority",async()=>{
  for(const change of [h=>{h.t.state.turns.push({id:"u2",role:"user",text:"I need to correct the team name."});h.t.conversationUI.revision++;},h=>{h.t.state.context.background="Changed scope";},h=>{h.t.setDocuments({exportState:()=>({scope:"changed-file-scope",documents:[]})});}]){
   const h=fixture(),captured=h.t.liveSnapshot();change(h);
   assert.equal(await h.t.applyLiveCapture({...app.approved("We are finished.","complete"),coverage_verified:true},captured),false);
   assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.said.length,0);assert.equal(h.notes.length,0);
  }
 });
 await check("speech and unfinished captions cannot trigger capture",async()=>{
  const h=fixture();h.route(()=>{throw Error("Capture must wait for the participant");});
  h.t.conversationUI.pendingParticipantCaptions.add("user:u1");await h.t.runLiveCapture();assert.equal(h.calls.length,0);
  h.t.conversationUI.pendingParticipantCaptions.clear();h.t.conversationUI.live.participantSpeaking=true;
  await h.t.runLiveCapture();assert.equal(h.calls.length,0);
 });
 await check("an already-sent completion review cannot publish after a new answer",async()=>{
  const h=fixture();let resolve;h.route(()=>new Promise(r=>resolve=r));
  const pending=h.t.request("/api/agent-team/review",h.t.snapshot());await app.flush();
  const rejected=assert.rejects(pending,error=>error.name==="AbortError");
  h.t.state.turns.push({id:"u2",role:"user",text:"Correction: the bank confirmation is the finish email."});
  h.t.conversationUI.revision++;
  resolve(app.response({...app.approved("Everything is complete."),speech_authorization:{approved:true,kind:"complete"},completion:{complete:true}}));
  await rejected;assert.equal(h.t.state.closure.confirmed,false);assert.equal(h.said.length,0);
 });
 await check("a late diagram cannot revoke review of newer participant evidence",async()=>{
  const h=fixture();let resolve;h.route(()=>new Promise(r=>resolve=r));
  const older=h.t.refreshWorkflow();await app.flush();
  h.t.state.turns.push({id:"u2",role:"user",text:"The bank email confirms receipt."});h.t.conversationUI.revision++;
  h.t.state.coverageVerified=true;h.t.state.completion={ready_for_final_check:true,complete:false};
  const currentCompletion=h.t.state.completion;
  resolve(app.response({workflow:{title:"Earlier workflow",steps:[],connections:[],open_questions:[]},coverage:[],memo_findings:[]}));
  await older;
  assert.equal(h.t.state.completion,currentCompletion);assert.equal(h.t.state.coverageVerified,true);
 });
 await check("progress updates wait for a natural pause and never supply a question",async()=>{
  const h=fixture();h.route(()=>app.response({}));
  await h.t.applyLiveCapture({...app.approved("Where does the main rule come from?"),memo_findings:[]},h.t.liveSnapshot());
  assert(h.notes.every(n=>!n.includes("main rule")&&!n.includes("I ask:")));
  h.notes.length=0;h.t.conversationUI.liveCoverageKey=null;h.t.conversationUI.live.assistantSpeaking=true;h.t.syncLiveCoverage();assert.equal(h.notes.length,0);
  h.t.conversationUI.live.assistantSpeaking=false;h.t.syncLiveCoverage();assert.equal(h.notes.length,1);
  h.t.state.turns[0].text="A later correction.";h.t.conversationUI.revision++;h.t.conversationUI.liveCoverageKey=null;h.notes.length=0;
  h.t.syncLiveCoverage();assert.equal(h.notes.length,0,"A lagging checkpoint sends no old advice");
 });
 console.log(JSON.stringify({checks_passed:passed,provider_calls:0,network_calls:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
