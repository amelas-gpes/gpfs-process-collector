"use strict";
// Replay the actual caption controller and app capture path, including delayed
// responses. Media/provider boundaries are local fakes; no network is used.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
source=source.replace("selectConversationView=view=>","const actualSchedule=scheduleWorkflow; selectConversationView=view=>");
source=source.replace("setTeam:value=>","TOPICS,receiveLiveStatus,receiveLiveCaption,sessionObject,transcriptObject,enableMapUpdates:()=>{scheduleWorkflow=actualSchedule;},presenceState,runLiveCapture,applyLiveCapture,liveSnapshot,syncLiveCoverage,refreshWorkflow,getCapturedThrough:()=>liveCapturedThrough,setTeam:value=>");
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
async function connected(){
 const h=fixture(),v=voice.setup();h.t.conversationUI.live=v.api;
 v.api.options.onTranscript=c=>h.t.receiveLiveCaption(c);
 v.api.options.onStatus=h.t.receiveLiveStatus;
 Object.defineProperty(h,"settled",{get:()=>app.flush()});
 await v.api.start({turns:h.t.state.turns});
 return {h,v};
}
function input(v,role,text,id){
 v.event({type:`session.${role==="user"?"input":"output"}_transcript.delta`,event_id:id,delta:text});
 return v.api.operation.captions[role];
}
async function settleVoice(v){const stopping=v.api.stop();v.event({type:"session.closed"});await stopping;}
let passed=0;
async function check(name,fn){await fn();passed++;console.log("PASS "+name);}
(async()=>{
 await check("GPT-Live playback displays Speaking while reviewed playback can still be preparing",async()=>{
  const h=fixture();
  h.t.conversationUI.status="speaking";
  assert.equal(h.t.presenceState(),"speaking");
  h.t.state.config.agent_team.voice_mode="reviewed_turns";
  assert.equal(h.t.presenceState(),"processing");
 });
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
 await check("the live hint keeps a practical veto and an untouched topic open, while leaving an approved follow-up with its owner",async()=>{
  const probe=async verified=>{
   const h=fixture();
   const followup={kind:"operational_hold",dimension:"release_conditions",gap:"Approve the Method B release test.",scope:"Method B",
    interim_action:"Hold Method B until Accounting approves the test.",resolver:"Accounting",evidence_turns:["u1"]};
   h.t.state.turns[0].text=followup.interim_action;
   const memo_findings=h.t.TOPICS.map(([key])=>({key,status:key==="volume"?"unknown":["checks","lifecycle"].includes(key)?"partial":"captured",
    answer:key==="volume"?"":"The participant described the current route.",evidence_turns:key==="volume"?[]:["u1"]}));
   const topics=memo_findings.map(({key,status})=>({key,complete:status==="captured",ready_for_owner_review:key!=="volume",
    owner_followups:["checks","lifecycle"].includes(key)?[{...followup,dimension:key==="checks"?"release_conditions":"handoffs"}]:[],gaps:[]}));
   const result={...app.approved("Who receives a rejected item?"),coverage_verified:verified,memo_findings,coverage_assessment:{topics},
    process_review:{findings:[{material:true,detail:"The return from rejection is unclear."}]},coverage_adjudication:{unconfirmed_topics:["lifecycle"]}};
   assert.equal(await h.t.applyLiveCapture(result,h.t.liveSnapshot()),true);
   assert.equal(h.notes.length,1);assert.equal(h.said.length,0);assert.equal(h.calls.length,0);
   assert.ok(!h.notes[0].includes(followup.gap),"The silent hint shares topic labels only");
   return h.notes[0];
  };
  assert.match(await probe(true),/Still open: lifecycle, volume\./);
  assert.match(await probe(false),/Still open: lifecycle, checks, volume\./);
 });
 await check("an approved pause closes local input immediately, even when its spoken line fails",async()=>{
   const {h,v}=await connected();h.route(()=>app.response(app.approved()));
   const result={...app.approved("We can pause here.","pause"),preserve_capture:true};
   const run=h.t.applyLiveCapture(result,h.t.liveSnapshot());await app.flush();
   assert.equal(v.tracks[0].enabled,false);assert.equal(v.tracks[0].stopped,true);assert.equal(v.api.setMuted(false),false);const send=v.channels[0].sent.find(e=>e.type==="session.instructions.append");
   v.event({type:"error",error:{client_event_id:send.event_id}});await run;
   assert.equal(v.api.active,false);assert.equal(v.tracks[0].stopped,true);assert.equal(h.t.state.turns.at(-1).delivery,"text");
   await settleVoice(v);await h.settled;
 });
 await check("a finalized stop bypasses provider decisions, drains captions and settles the prior process answer",async()=>{
   const {h,v}=await connected();h.t.state.config.agent_team.stop_intent_patterns=["^(?:please )?stop(?: the interview)?$"];
   const payloads=[];h.route((url,options)=>{if(url==="/api/agent-team/interview")payloads.push(JSON.parse(options.body));return app.response({...app.approved(),summary:"The processor checks the invoice."});});
   const prior=input(v,"user","Stop. Nothing is released until the controller signs.","prior");v.api.caption(v.api.operation,prior,true);
   assert.equal(v.api.active,true);input(v,"assistant","What happens next?","question");
   const stop=input(v,"user","Please stop the interview.","stop");assert.equal(v.tracks[0].enabled,true);
   v.api.caption(v.api.operation,stop,true);
   assert.equal(v.tracks[0].stopped,true);assert.equal(v.tracks[0].enabled,false);
   v.event({type:"session.closed"});await h.settled;
   assert.equal(payloads.length,1);assert.equal(payloads[0].turns.at(-1).role,"assistant");
   assert(payloads[0].turns.some(t=>t.text===prior.text));assert(!payloads[0].turns.some(t=>t.text===stop.text));
   assert(h.t.state.turns.some(t=>t.text===stop.text));assert.equal(h.t.state.summary,"The processor checks the invoice.");
 });
 await check("map and notes exclude a finalized stop in a rolling caption and retain everything before it",async()=>{
   for(const prefix of ["","The clerk logs the crate. Finance signs the handoff. "]){
     const {h,v}=await connected();h.t.state.turns=[];h.t.state.config.api_configured=true;h.t.state.config.agent_team.stop_intent_patterns=["^please stop the interview$"];h.t.enableMapUpdates();
     const bodies=[];h.route((url,options)=>{if(url==="/api/agent-team/workflow"||url==="/api/agent-team/interview")bodies.push({url,turns:JSON.parse(options.body).turns});return app.response(url==="/api/agent-team/workflow"?{workflow:{title:"Crate workflow",steps:[],connections:[]},memo_findings:[]}:app.approved());});
     if(prefix)input(v,"user",prefix,"substance");
     const command=input(v,"user","Please stop the interview.","stop");
     assert(![...h.timers.values()].some(timer=>timer.ms===1000),"partial speech does not schedule a provider map");
     v.api.caption(v.api.operation,command,true);v.event({type:"session.closed"});await h.settled;
     if([...h.timers.values()].some(timer=>timer.ms===1000))await h.timer(1000);
     assert.equal(bodies.length,prefix?2:0);
     for(const {turns} of bodies){assert.equal(turns.length,1);assert.equal(turns[0].text,prefix.trim());assert.equal(turns[0].id,h.t.state.turns[0].id);}
     assert.equal(h.t.state.turns[0].text,prefix+"Please stop the interview.");
   }
 });
 await check("Stop drains a new answer and settles a pending lead response once without reopening voice",async()=>{
   for(const alreadySent of [false,true]){
     const {h,v}=await connected();let resolve;h.route(url=>url==="/api/agent-team/interview"?new Promise(r=>resolve=r):app.response({}));
     const c=input(v,"user","The final handoff goes to Legal.","legal");
     if(alreadySent){v.api.caption(v.api.operation,c,true);void h.t.runLiveCapture();await app.flush();}
     await settleVoice(v);await app.flush();assert.equal(captureCalls(h).length,1);
     resolve(app.response({...app.approved(),summary:"Legal receives the handoff."}));await h.settled;
     assert.equal(h.t.state.summary,"Legal receives the handoff.");assert.equal(captureCalls(h).length,1);
     assert.equal(v.api.active,false);assert.equal(h.t.conversationUI.coverageCheckpoint.through,h.t.state.turns.at(-1).id);
   }
 });
 await check("an unconfirmed acknowledgment stays visible as text, unrelated captions are preserved, and review waits",async()=>{
   const {h,v}=await connected();const ack="Let me check that I have everything before we finish.";
   const r={...app.approved(ack,"review_pending"),review_ticket:"ticket"};const run=h.t.applyLiveCapture(r,h.t.liveSnapshot());await app.flush();
   const send=v.channels[0].sent.find(e=>e.type==="session.instructions.append");
   input(v,"assistant","Who signs the exception?","unrelated");
   assert(h.t.state.turns.some(turn=>turn.text==="Who signs the exception?"));
   assert.equal(h.t.state.turns.filter(turn=>turn.text===ack).length,1);assert(!h.calls.some(c=>c.url==="/api/agent-team/review"));
   v.event({type:"error",error:{client_event_id:send.event_id}});await run;
   assert.equal(h.t.state.turns.find(turn=>turn.text===ack)?.delivery,"text");
   assert.equal(h.node("retry-question").hidden,false);assert(!h.calls.some(c=>c.url==="/api/agent-team/review"));
   h.route(()=>app.response(app.approved()));await settleVoice(v);await h.settled;
 });
 await check("only a matching final caption plus delivery receipt releases the next review",async()=>{
   const {h,v}=await connected();const ack="Let me check that I have everything before we finish.";
   const final="Before we finish, is there anything else we haven’t captured?";
   const review=[];h.route((url,options)=>{if(url==="/api/agent-team/review"){review.push(JSON.parse(options.body));return app.response({...app.approved(final,"final_check"),coverage_verified:true});}return app.response(app.approved());});
   const run=h.t.applyLiveCapture({...app.approved(ack,"review_pending"),review_ticket:"ticket"},h.t.liveSnapshot());await app.flush();
   const send=v.channels[0].sent.find(e=>e.type==="session.instructions.append");v.event({type:"session.instructions.appended",client_event_id:send.event_id});
   const c=input(v,"assistant",ack.toLowerCase().replace(".","!"),"ack");await app.flush();assert.equal(review.length,0);
   v.api.caption(v.api.operation,c,true);await app.flush();
   const finalSend=v.channels[0].sent.filter(e=>e.type==="session.instructions.append").at(-1);
   v.event({type:"session.instructions.appended",client_event_id:finalSend.event_id});
   const check=input(v,"assistant",final.toUpperCase().replace("’","").replace("?","."),"final");v.api.caption(v.api.operation,check,true);await run;
   assert.equal(h.t.state.turns.filter(t=>t.text===final).length,1);assert.equal(h.t.state.turns.at(-1).text,final);assert.equal(h.t.state.closure.asked,true);
   assert.equal(review.length,1);assert.equal(review[0].turns.at(-1).text,ack);assert.equal(h.t.state.turns.filter(t=>t.text===ack).length,1);
   await settleVoice(v);await h.settled;
 });
 await check("new substantive speech revokes the closing timer, completion and both export confirmations",async()=>{
   const {h,v}=await connected();const closing="Thank you for confirming the account.";
   const run=h.t.applyLiveCapture({...app.approved(closing,"complete"),coverage_verified:true},h.t.liveSnapshot());await app.flush();
   const send=v.channels[0].sent.find(e=>e.type==="session.instructions.append");v.event({type:"session.instructions.appended",client_event_id:send.event_id});
   const c=input(v,"assistant",closing,"close");v.api.operation.sound.playbackActive=true;v.api.caption(v.api.operation,c,true);await run;
   assert.equal(h.t.state.closure.confirmed,true);assert([...h.timers.values()].some(t=>t.ms===9000));
   h.route(()=>app.response(app.approved()));
   const correction=input(v,"user","Wait, the backup approval is different.","correction");v.api.caption(v.api.operation,correction,true);
   await h.t.runLiveCapture();assert.equal(h.t.state.closure.confirmed,false);
   assert.equal(h.t.sessionObject().closure.confirmed,false);assert.equal(h.t.transcriptObject().memo.closure.confirmed,false);
   assert(![...h.timers.values()].some(t=>t.ms===9000));assert.equal(v.api.active,true);
   h.route(()=>app.response(app.approved()));await settleVoice(v);await h.settled;
 });
 await check("a stuck playback meter cannot leave an idle, confirmed session recording",async()=>{
   const {h,v}=await connected();let wall=10000;h.context.Date=class extends Date{static now(){return wall;}};
   const closing="Thank you for confirming the account.";
   const run=h.t.applyLiveCapture({...app.approved(closing,"complete"),coverage_verified:true},h.t.liveSnapshot());await app.flush();
   const send=v.channels[0].sent.find(e=>e.type==="session.instructions.append");v.event({type:"session.instructions.appended",client_event_id:send.event_id});
   const c=input(v,"assistant",closing,"closing");v.api.operation.sound.playbackActive=true;v.api.caption(v.api.operation,c,true);await run;
   wall+=31000;await h.timer(9000);assert.equal(v.api.active,false);assert.equal(v.tracks[0].stopped,true);
   h.route(()=>app.response(app.approved()));await settleVoice(v);await h.settled;
 });
 await check("a malformed completion cannot mutate a live capture or request speech",async()=>{
   const {h,v}=await connected(),r={...app.approved("We are done.","complete"),coverage_verified:true};r.speech_authorization.approved=false;
   await assert.rejects(h.t.applyLiveCapture(r,h.t.liveSnapshot()),/Unapproved speech/);
   assert.equal(h.t.state.closure.confirmed,false);assert(!v.channels[0].sent.some(e=>e.type==="session.instructions.append"));assert.equal(h.t.state.summary,"Last accepted notes");
   h.route(()=>app.response(app.approved()));await settleVoice(v);await h.settled;
 });
 await check("a spoken file-purpose answer is retained once and Assets keeps control of the file purpose",async()=>{
   const {h,v}=await connected();const file={id:"doc_example",name:"Work.csv",analysis:{disposition:"needs_reason",intent_version:1,purpose_attempted:false}};
   h.t.setDocuments({exportState:()=>({scope:"local-synthetic",documents:[file]}),refresh(){}});
   h.route(()=>app.response(app.approved()));
   const q=input(v,"assistant","Why did you share Work.csv?","q");v.api.caption(v.api.operation,q,true);
   const answer=input(v,"user","It lists the approvals.","a");v.api.caption(v.api.operation,answer,true);v.api.caption(v.api.operation,answer,true);
   await app.flush();const calls=h.calls.filter(c=>c.url==="/api/documents/action");assert.equal(calls.length,0);assert.equal(h.t.state.turns.filter(t=>t.text==="It lists the approvals.").length,1);
   await settleVoice(v);await h.settled;assert.equal(h.calls.filter(c=>c.url==="/api/documents/action").length,0);
 });
 await check("the live session receives the selected supported AI voice",async()=>{
   const h=fixture();h.t.conversationUI.live=null;h.t.state.voiceChoice="ai:cedar";h.t.state.config.speech.voices.push({id:"cedar",label:"Cedar"});
   let value;h.window.CollectorLiveVoice=class{async start(payload){value=payload.voice;}};
   await h.t.startLiveConversation();assert.equal(value,"cedar");
 });
 console.log(JSON.stringify({checks_passed:passed,provider_calls:0,network_calls:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
