"use strict";
// Seven behaviours that a mutation sample of the audit (qa-js-tests-8) showed no suite would miss:
// each check below fails when the one operator named beside it is flipped in the source.
//   web/app.js              reply box disabled while busy or recording; a draft edit marks the interview
//                           unsaved and arms the leave guard; what counts as a source for a draft; the
//                           128 / 100 limit on classifications and relationships
//   web/controlled-voice.js the microphone stays closed when listening resumes while muted; a reviewed
//                           response is not applied or spoken while muted or after its turn was cancelled
//   web/documents.js        a file is announced as usable only when it is active, read and has text
// Real modules; the browser, media and network are stand-ins. No provider, no network.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const shared={process:{argv:[]},require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout,Set,Map,Promise,Error,TypeError};
const exported=(file,cut,tail)=>{const module={exports:{}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,file),"utf8").split(cut)[0]+tail,{...shared,module});return module.exports;};
// The harnesses of the two module suites, as those suites define them.
const voice=exported("test_controlled_voice.cjs","let passed=0;","\nmodule.exports={setup,approved,deferred,flush};");
const files=exported("test_documents_frontend.cjs","(async()=>{","\nmodule.exports={setup,doc};");
const EXPOSE="setBusy,updateControls,renderTranscript,renderDraft,normalizeDraft,normalizeDiscovery,tab,selectReviewSection,updateSaveHint";
const config={agent_team:{enabled:true}};
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,6).join("\n     "));}
}
const conversation=page=>{page.state.context={process_name:"Supply order",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A weekly count of the supply cupboard."}];page.t.renderTranscript();};
(async()=>{
 await check("the reply box is disabled while a request is running, while recording, and without a provider",async()=>{
  // app.js: $("answer-text").disabled = working || recording || !ready
  const page=await open({config,expose:EXPOSE});conversation(page);const reply=page.$("answer-text");
  assert.equal(reply.disabled,false,"Idle and configured: the reply box can be typed in");
  page.t.setBusy(true);assert.equal(reply.disabled,true,"Busy alone disables it");
  page.t.setBusy(false);assert.equal(reply.disabled,false);
  page.state.recording={recorder:{state:"recording"}};page.t.updateControls();assert.equal(reply.disabled,true,"Recording alone disables it");
  page.state.recording=null;page.state.transcribing=true;page.t.updateControls();assert.equal(reply.disabled,true,"Transcribing disables it");
  page.state.transcribing=false;page.state.requestingMic=true;page.t.updateControls();assert.equal(reply.disabled,true,"Waiting for the microphone disables it");
  page.state.requestingMic=false;page.t.updateControls();assert.equal(reply.disabled,false);
  page.state.config={...page.state.config,api_configured:false};page.t.updateControls();assert.equal(reply.disabled,true,"No provider: nothing can be sent");
 });
 await check("editing the draft marks the interview unsaved and arms the leave guard",async()=>{
  // app.js draftChanged: state.dirty = true
  const page=await open({config,expose:EXPOSE});conversation(page);
  const leaving=()=>{const event={prevented:false,preventDefault(){this.prevented=true;}};for(const listener of page.window.listeners.beforeunload||[])listener(event);return event.prevented;};
  assert.equal((page.window.listeners.beforeunload||[]).length,1,"The page asks before it is left");
  page.state.draft=page.t.normalizeDraft({title:"Supply order",summary:"A weekly count.",steps:[],connections:[],open_questions:[]},page.state.turns,[]);
  page.t.renderDraft();page.t.tab("review");page.t.selectReviewSection("review-procedure");page.state.dirty=false;page.state.draftEdited=false;page.t.updateSaveHint();
  assert.equal(page.shown("draft-overview"),true,"The Steps tab of Review shows the editable overview");
  assert.equal(leaving(),false,"Nothing unsaved: leaving is not questioned");assert.equal(page.$("save-hint").hidden,true);
  page.$("draft-overview").input("Counted every Monday by the office manager.");
  assert.equal(page.state.draft.overview,"Counted every Monday by the office manager.");
  assert.equal(page.state.dirty,true,"A Review edit is unsaved work");assert.equal(page.state.draftEdited,true);
  assert.equal(page.$("save-hint").hidden,false);assert.equal(page.text("save-hint"),"Unsaved changes");
  assert.equal(leaving(),true,"Closing the tab now asks first");
  // A list field goes through the same path.
  page.state.dirty=false;page.$("draft-inputs").input("Count sheet\nOrder form");
  assert.deepEqual([...page.state.draft.inputs],["Count sheet","Order form"]);assert.equal(page.state.dirty,true);assert.equal(leaving(),true);
 });
 await check("a draft needs a participant answer or a file: interviewer lines alone are not a source",async()=>{
  // app.js: hasDraftSource = state.turns.some(t => t.role === "user") || hasDocumentEvidence()
  const page=await open({config,expose:EXPOSE});
  page.state.context={process_name:"",process_owner:"",objective:"Understand the work",background:""};page.state.started=true;
  page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];page.t.renderTranscript();
  assert.equal(page.$("generate-draft").disabled,true,"Only the interviewer has spoken: no draft");
  assert.equal(page.$("regenerate-draft").disabled,true);assert.equal(page.$("review-create-draft").hidden,true);
  assert.equal(page.text("review-next-step"),"Describe your process or add a file to start a draft.");assert.equal(page.$("empty-start").hidden,false);
  page.state.turns=[{id:"t001",role:"user",text:"We count the cupboard every Monday."}];page.t.renderTranscript();
  assert.equal(page.$("generate-draft").disabled,false,"One participant answer is enough, with no interviewer line at all");
  assert.equal(page.$("review-create-draft").hidden,false);assert.equal(page.$("review-create-draft").disabled,false);assert.equal(page.$("empty-start").hidden,true);
  page.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A weekly count."}];page.t.renderTranscript();
  assert.equal(page.$("generate-draft").disabled,false);
  page.state.turns=[];page.t.renderTranscript();assert.equal(page.$("generate-draft").disabled,true,"An empty interview has nothing to draft from");
 });
 await check("classifications stop at 128 and process relationships at 100, each by itself",async()=>{
  // app.js normalizeDiscovery: taxonomy.length>128||connections_out.length>100
  const page=await open({config,expose:EXPOSE});conversation(page);
  const tags=count=>Array.from({length:count},(_,index)=>({facet:"entity",value:"Entity "+index,note:"",evidence_turns:["t002"]}));
  const links=count=>Array.from({length:count},(_,index)=>({relationship_type:"downstream",counterpart:"Process "+index,condition:"",evidence_turns:["t002"]}));
  const read=(taxonomy,connections_out)=>page.t.normalizeDiscovery({taxonomy,connections_out},page.state.turns,[]);
  const kept=read(tags(128),links(100));assert.equal(kept.taxonomy.length,128);assert.equal(kept.connections_out.length,100);
  assert.throws(()=>read(tags(129),links(0)),/Too many classifications or process relationships/,"129 classifications alone are too many");
  assert.throws(()=>read(tags(0),links(101)),/Too many classifications or process relationships/,"101 relationships alone are too many");
  assert.throws(()=>read(tags(129),links(101)),/Too many/);
 });
 await check("the microphone stays closed when listening resumes while muted",async()=>{
  // controlled-voice.js listen(): if(op.muted){this.tracks(op,false);…}
  const response=voice.deferred(),h=voice.setup({request:url=>url==="/api/transcribe"?{text:"A retained answer."}:response.promise});
  await h.voice.start();await h.say();
  assert.equal(h.requests.length,2,"The answer is with the interviewer");
  h.track.enabled=true; // whatever state the track was left in, mute must close it and keep it closed
  h.voice.setMuted(true);assert.equal(h.track.enabled,false);
  // The cancelled turn settles and hands control back to listen(): still muted, still closed.
  response.resolve(voice.approved());await voice.flush();await voice.flush();
  assert.equal(h.voice.status,"muted");assert.equal(h.track.enabled,false,"The microphone track is not re-enabled while the page says Muted");
  assert.equal(h.stream.getAudioTracks().every(track=>track.enabled===false),true,"Every microphone track is disabled");
  // The same holds when listen() is reached directly (a frame, a timer) while muted.
  h.track.enabled=true;h.voice.listen(h.voice.operation);
  assert.equal(h.track.enabled,false);assert.equal(h.voice.status,"muted");assert.equal(h.recorders.filter(recorder=>recorder.state==="recording").length,0,"No recording starts");
  h.voice.setMuted(false);await voice.flush();assert.equal(h.track.enabled,true,"Unmuting reopens the microphone after the pending reply plays");assert.equal(h.voice.status,"listening");
  await h.voice.stop();
 });
 await check("a reviewed response is neither applied nor spoken while muted, or after its turn was cancelled",async()=>{
  // controlled-voice.js playReviewed(): if(!this.current(op)||signal.aborted||op.muted)return;
  for(const [name,arrange] of [["muted",(h,controller)=>{h.voice.operation.muted=true;}],["cancelled",(h,controller)=>{controller.abort();}]]){
   const h=voice.setup();await h.voice.start();
   const op=h.voice.operation,controller=new AbortController();arrange(h,controller);
   await h.voice.playReviewed(op,voice.approved("What happens after that?"),"basis-of-the-request",controller.signal);
   assert.equal(h.results.length,0,name+": the response is not added to the conversation");
   assert.equal(h.spoken.length,0,name+": nothing is spoken");assert.equal(h.errors.length,0,name+": and nothing is reported as failed");
   await h.voice.stop({immediate:true});
  }
  // The guard does not swallow a live turn: the ordinary flow still applies and speaks its response.
  const h=voice.setup();await h.voice.start();await h.say();
  assert.equal(h.results.length,1);assert.equal(h.spoken.length,1);await h.voice.stop({immediate:true});
 });
 await check("a file is announced as usable only when it is active, read and has text",async()=>{
  // documents.js setDocuments(): available = !archived && ["ready","partial"].includes(status) && chunk_count>0
  const unreviewed=extra=>files.doc({analysis:{phase:"quick",disposition:"relevant",sources:[]},...extra});
  const announced=file=>{const h=files.setup({inline:true});h.api.scope="local-scope";h.api.setDocuments([file]);const events=h.events.filter(event=>event.type==="analysis");h.api.dispose();return events.length;};
  assert.equal(announced(unreviewed({status:"ready",chunk_count:3})),1,"Read, with text, active: usable before its first review");
  assert.equal(announced(unreviewed({status:"partial",chunk_count:1})),1,"Partly read with text counts");
  assert.equal(announced(unreviewed({status:"ready",chunk_count:0})),0,"Read but no text was extracted");
  assert.equal(announced(unreviewed({status:"ready"})),0,"No count of text at all");
  assert.equal(announced(unreviewed({status:"processing",chunk_count:3})),0,"Still being read");
  assert.equal(announced(unreviewed({status:"failed",chunk_count:3})),0,"Reading failed");
  assert.equal(announced(unreviewed({status:"ready",chunk_count:3,archived:true})),0,"Saved for later: not part of the interview");
  // A reviewed file is announced by its review, whatever its text count.
  assert.equal(announced(files.doc({status:"ready",chunk_count:0})),1);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,real_browser:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
