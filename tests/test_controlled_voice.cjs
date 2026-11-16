"use strict";
// Fake microphone/recorder/playback boundary tests; no physical audio or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../web/controlled-voice.js"),"utf8");
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const approved=(question="What happens after that?",kind="question")=>({question,speech_authorization:{approved:true,text:question,kind,revision:"revision_1",completion_allowed:kind==="complete"},completion:{ready_for_final_check:kind==="final_check"||kind==="complete",complete:kind==="complete"}});
function setup(overrides={}){
  let now=0,level=0,serial=0,permissionCalls=0,playbackStops=0;
  const frames=new Map(),timers=new Map(),recorders=[],contexts=[],requests=[],answers=[],answerInfo=[],results=[],spoken=[],statuses=[],errors=[],notices=[],audioFrames=[],recovery=[],timings=[],endpoints=[],problems=[],handlers={};
  const track={enabled:true,stopped:0,stop(){this.stopped++;}},stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
  const snapshot={context:{process_name:"Fictional invoice process"},turns:[],document_revision:"docs1"};
  class Recorder {
    static isTypeSupported(type){return type==="audio/webm";}
    constructor(_stream,options){this.mimeType=options?.mimeType||"audio/webm";this.state="inactive";this.listeners={};recorders.push(this);}
    addEventListener(name,callback){(this.listeners[name]??=[]).push(callback);}
    start(){this.state="recording";}
    emit(name,value={}){for(const callback of this.listeners[name]||[])callback(value);}
    stop(){this.state="inactive";Promise.resolve().then(()=>{this.emit("dataavailable",{data:new Blob(["audio"])});this.emit("stop");});}
  }
  class AudioContext {
    constructor(){this.closed=0;contexts.push(this);}
    createMediaStreamSource(){return{connect(){},disconnect(){}};}
    createAnalyser(){return{fftSize:1024,getFloatTimeDomainData(buffer){if(shape)shape(buffer);else buffer.fill(level);}};}
    resume(){return Promise.resolve();}close(){this.closed++;return Promise.resolve();}
  }
  // shape(buffer) replaces the constant level when a test needs sound in only part of the window.
  let shape=null;
  const page={hidden:false,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},removeEventListener(name,fn){if(this.listeners[name]===fn)delete this.listeners[name];}};
  const window={document:page,addEventListener:(name,fn)=>handlers[name]=fn,removeEventListener:(name,fn)=>{if(handlers[name]===fn)delete handlers[name];}};
  const context={window,Blob,AbortController,Float32Array,Date,Set,JSON,Error,TypeError,Promise};vm.createContext(context);vm.runInContext(source,context);
  const options={mediaDevices:{getUserMedia:()=>{permissionCalls++;return overrides.permission||Promise.resolve(stream);}},MediaRecorder:Recorder,AudioContext,
    now:()=>now,requestAnimationFrame:fn=>{const id=++serial;frames.set(id,fn);return id;},cancelAnimationFrame:id=>frames.delete(id),setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
    getSnapshot:()=>JSON.parse(JSON.stringify(snapshot)),
    request:async(url,data,opts)=>{requests.push({url,data,opts});return overrides.request?overrides.request(url,data,opts):url==="/api/transcribe"?{text:"The clerk logs the invoice."}:approved();},
    // Like the app: more of the same answer joins the participant turn that is still open.
    onAnswer:(text,info)=>{answers.push(text);answerInfo.push(info);const last=snapshot.turns.at(-1);if(info?.continuation&&last?.role==="user")last.text+=" "+text;else snapshot.turns.push({id:`u${answers.length}`,role:"user",text});overrides.onAnswer?.(text,info);},
    onResult:result=>{results.push(result);snapshot.turns.push({id:`a${results.length}`,role:"assistant",text:result.question});},
    speak:(text,opts)=>{spoken.push({text,opts});return overrides.speak?overrides.speak(text,opts):Promise.resolve();},
    stopPlayback:()=>{playbackStops++;overrides.stopPlayback?.();},onStatus:value=>statuses.push(value),onError:value=>errors.push(value),onNotice:value=>notices.push(value),onAudioFrame:value=>audioFrames.push(value),onTranscriptionRecovery:value=>recovery.push(value),
    prepareSpeech:overrides.prepareSpeech,onTurnTiming:record=>timings.push(record),onEndpoint:()=>endpoints.push(now),onPlaybackProblem:value=>problems.push(value),
    ...(overrides.opening?{opening:overrides.opening}:{}),...(overrides.options||{})};
  const voice=new window.CollectorControlledVoice(options);
  const tick=async(ms,sound=level)=>{now+=ms;level=sound;const ready=[...frames.values()];frames.clear();ready.forEach(fn=>fn(now));await flush();};
  // Frames arrive about as often as a visible page delivers them under load (every 100 ms while
  // speaking, about once a second in silence), never as one frame for a whole utterance.
  const talk=async(ms=700,sound=.07)=>{for(let spent=0;spent<ms;spent+=100)await tick(Math.min(100,ms-spent),sound);};
  const quiet=async ms=>{const steps=Math.ceil(ms/1150);for(let step=0;step<steps;step++)await tick(ms/steps,0);};
  // The participant waits for the microphone before speaking (speech in its first 150 ms is a clipped start).
  const lead=async()=>{await tick(16,0);await tick(200,0);};
  const say=async()=>{await lead();await talk(700);await quiet(2300);};
  // No animation frames at all (a hidden or covered page parks them): time passes and only the
  // meter's own timers run, the 250 ms one of a hidden page or the 1 s one that backs up a frame.
  const beat=async(ms,sound=level)=>{now+=ms;level=sound;for(const [id,timer] of [...timers])if(timer.ms===250||timer.ms===1000){timers.delete(id);timer.fn();}await flush();};
  const setHidden=value=>{page.hidden=value;page.listeners.visibilitychange?.();};
  return {page,beat,setHidden,setShape:fn=>{shape=fn;},advance:ms=>{now+=ms;},voice,snapshot,stream,track,requests,answers,answerInfo,results,spoken,statuses,errors,notices,audioFrames,recovery,timings,endpoints,problems,recorders,contexts,frames,timers,handlers,window,tick,lead,talk,quiet,say,permissionCalls:()=>permissionCalls,playbackStops:()=>playbackStops};
}
// An optional argument runs only the checks whose label matches it:  node tests/test_controlled_voice.cjs "noise gate"
const only=process.argv[2]?new RegExp(process.argv[2],"i"):null;
let passed=0;async function check(label,fn){if(only&&!only.test(label))return;try{await fn();passed++;}catch(error){error.message=label+": "+error.message;throw error;}}
(async()=>{
await check("speech preparation overlaps transcription and is disposed after playback",async()=>{
 const transcribe=deferred(),playback=deferred();let prepared=0,disposed=0;
 const prep={dispose(){disposed++;}},h=setup({prepareSpeech:()=>{prepared++;return prep;},request:url=>url==="/api/transcribe"?transcribe.promise:approved(),speak:()=>playback.promise});
 await h.voice.start();await h.say();assert.equal(prepared,1);assert.equal(h.spoken.length,0);
 await h.tick(400,0);transcribe.resolve({text:"A useful answer."});await flush();
 assert.equal(h.spoken[0].opts.preparation,prep);assert.equal(h.timings.length,0);
 await h.tick(300,0);h.spoken[0].opts.onPlaybackStart();await h.tick(800,0);playback.resolve();await flush();
 assert.equal(disposed,1);assert.equal(h.timings.length,1);const t=h.timings[0];
 assert.equal(t.endpoint_ms,2300);assert.equal(t.transcription_ms,400);assert.equal(t.playback_preparation_ms,300);
 assert.equal(t.speech_end_to_meaningful_audio_ms,3000);assert.equal(t.playback_ms,800);
 assert.equal(t.physical_audio_verified,false);assert.equal(JSON.stringify(t).includes("useful answer"),false);await h.voice.dispose();
});
await check("preparation failure does not fail a valid question and missing playback events stay unknown",async()=>{
 const h=setup({prepareSpeech:()=>{throw Error("Unavailable preparation");}});await h.voice.start();await h.say();
 assert.equal(h.spoken.length,1);assert.equal(h.timings[0].speech_end_to_meaningful_audio_ms,null);await h.voice.dispose();
});
await check("a review acknowledgement is not counted as meaningful audio",async()=>{
 const review=deferred(),ack={...approved("Let me check that I have everything before we finish.","review_pending"),review_ticket:"review-one"};
 const h=setup({request:url=>url==="/api/transcribe"?{text:"Finished my account."}:url==="/api/interview"?ack:review.promise,speak:(_text,opts)=>{opts.onPlaybackStart();return Promise.resolve();}});
 await h.voice.start();await h.say();assert.equal(h.voice.operation.timing.started,null);
 await h.tick(700,0);review.resolve(approved("How is a rejected item returned?"));await flush();
 assert.equal(h.timings[0].speech_end_to_meaningful_audio_ms,3000);await h.voice.dispose();
});
await check("reviewed response is the only spoken output",async()=>{const playback=deferred(),h=setup({speak:()=>playback.promise});await h.voice.start();assert.equal(h.voice.connected,true);assert.equal(h.voice.status,"listening");await h.say();assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/interview"]);assert.equal(h.answers.length,1);assert.equal(h.results.length,1);assert.equal(h.spoken[0].text,h.results[0].speech_authorization.text);assert.equal(h.voice.status,"speaking");assert.equal(h.track.enabled,false);assert.equal(h.requests[1].data.turns[0].text,h.answers[0]);playback.resolve();await flush();assert.equal(h.voice.status,"listening");assert.equal(h.track.enabled,true);await h.voice.stop();});
for(const mutation of [result=>delete result.speech_authorization,result=>result.speech_authorization.approved=false,result=>result.speech_authorization.text="Different speech",result=>result.speech_authorization.kind="unreviewed",result=>result.speech_authorization.revision=""]){
 await check("unapproved response cannot reach transcript or speaker",async()=>{const result=approved("Thanks, we are all done.");mutation(result);const h=setup({request:url=>url==="/api/transcribe"?{text:"We have more sections."}:result});await h.voice.start();await h.say();assert.equal(h.answers.length,1);assert.equal(h.results.length,0);assert.equal(h.spoken.length,0);assert.equal(h.voice.active,false);assert.match(h.errors[0],/did not pass the speech check/);});
}
await check("opening response receives the same speech authorization gate",async()=>{const h=setup({opening:async()=>({question:"We're finished."})});await h.voice.start();assert.equal(h.spoken.length,0);assert.equal(h.results.length,0);assert.equal(h.requests.length,0);assert.equal(h.voice.active,false);});
for(const [kind,mutation] of [["final_check",result=>delete result.completion],["final_check",result=>result.completion.ready_for_final_check=false],["complete",result=>delete result.completion],["complete",result=>result.completion.complete=false],["complete",result=>result.speech_authorization.completion_allowed=false],["complete",result=>delete result.speech_authorization.completion_allowed]]){
 await check("inconsistent completion flags prevent speech",async()=>{const result=approved("That finishes the interview.",kind);mutation(result);const h=setup({request:url=>url==="/api/transcribe"?{text:"We still have gaps."}:result});await h.voice.start();await h.say();assert.equal(h.answers.length,1);assert.equal(h.results.length,0);assert.equal(h.spoken.length,0);assert.equal(h.voice.active,false);assert.match(h.errors[0],/completion check/);});
}
await check("ready final omissions check is spoken without ending the call",async()=>{const h=setup({request:url=>url==="/api/transcribe"?{text:"That addresses the final missing detail."}:approved("Is there anything else to include?","final_check")});await h.voice.start();await h.say();assert.equal(h.spoken.length,1);assert.equal(h.voice.active,true);assert.equal(h.voice.status,"listening");await h.voice.stop();});
await check("authorized pause remains available with unresolved completion",async()=>{const response=approved("The review could not finish. We can pause here.","pause");response.completion={ready_for_final_check:false,complete:false};response.speech_authorization.completion_allowed=false;const h=setup({request:url=>url==="/api/transcribe"?{text:"Please pause."}:response});await h.voice.start();await h.say();assert.equal(h.spoken.length,1);assert.equal(h.voice.active,false);});
await check("resuming without an approved opening only listens",async()=>{const h=setup({opening:async()=>null});await h.voice.start({turns:[{role:"assistant",text:"Unreviewed saved question"}]});assert.equal(h.spoken.length,0);assert.equal(h.requests.length,0);assert.equal(h.voice.status,"listening");await h.voice.stop();});
await check("immediate stop during transcription blocks follow-on requests",async()=>{const transcription=deferred(),h=setup({request:()=>transcription.promise});await h.voice.start();await h.say();assert.equal(h.requests.length,1);await h.voice.stop({immediate:true});assert.equal(h.requests[0].opts.signal.aborted,true);transcription.resolve({text:"A late answer"});await flush();assert.equal(h.answers.length,0);assert.equal(h.requests.length,1);assert.equal(h.spoken.length,0);assert.equal(h.track.stopped,1);});
await check("Stop drains the spoken answer before closing without asking another question",async()=>{
 const transcription=deferred(),h=setup({request:()=>transcription.promise});await h.voice.start();await h.say();
 const ended=h.voice.stop();assert.equal(h.track.enabled,false);transcription.resolve({text:"Keep this answer."});await ended;
 assert.deepEqual(h.answers,["Keep this answer."]);assert.equal(h.requests.length,1);assert.equal(h.spoken.length,0);
});
await check("a completed transcription can go to the editor without adding a participant turn",async()=>{
 const h=setup(),edited=[];h.voice.options.reviewBeforeSending=()=>true;h.voice.options.onEditableAnswer=text=>edited.push(text);
 await h.voice.start();await h.say();await flush();
 assert.deepEqual(edited,["The clerk logs the invoice."]);assert.equal(h.voice.active,false);
 assert.equal(h.answers.length,0);assert.deepEqual(h.requests.map(row=>row.url),["/api/transcribe"]);
});
await check("a measured quiet microphone prompts once until the participant starts answering",async()=>{
 const h=setup(),hints=[];h.voice.options.onMicHint=message=>hints.push(message);await h.voice.start();
 for(let i=0;i<15;i++)await h.tick(1000,.001);
 assert.equal(hints.length,1);assert.match(hints[0],/microphone input/);assert.equal(h.requests.length,0);
 await h.voice.stop();
});
await check("a failed review retains the accepted answer without retrying",async()=>{const h=setup({request:url=>url==="/api/transcribe"?{text:"An answer worth retaining."}:Promise.reject(Error("Provider unavailable"))});await h.voice.start();await h.say();assert.deepEqual(h.answers,["An answer worth retaining."]);assert.equal(h.voice.active,false);assert.equal(h.requests.length,2);await h.tick(100000,.2);assert.equal(h.requests.length,2);assert.equal(h.spoken.length,0);});
await check("a manual source title change during the turn invalidates the response",async()=>{const response=deferred(),h=setup({request:url=>url==="/api/transcribe"?{text:"Original account."}:response.promise});await h.voice.start();await h.say();h.snapshot.context.process_name="A different process scope";response.resolve(approved());await flush();assert.equal(h.results.length,0);assert.equal(h.spoken.length,0);assert.match(h.errors[0],/conversation changed/);assert.equal(h.voice.active,false);});
await check("a changed objective during the turn still invalidates the response",async()=>{const response=deferred(),h=setup({request:url=>url==="/api/transcribe"?{text:"Original account."}:response.promise});await h.voice.start();await h.say();h.snapshot.context.objective="A different objective";response.resolve(approved());await flush();assert.equal(h.results.length,0);assert.equal(h.spoken.length,0);assert.match(h.errors[0],/conversation changed/);});
await check("stale responses cannot be applied or spoken",async()=>{const response=deferred(),h=setup({request:url=>url==="/api/transcribe"?{text:"Original account."}:response.promise});await h.voice.start();await h.say();h.snapshot.turns.push({id:"correction",role:"user",text:"A newer correction."});response.resolve(approved());await flush();assert.equal(h.results.length,0);assert.equal(h.spoken.length,0);assert.equal(h.voice.active,false);assert.match(h.errors[0],/conversation changed/);});
await check("Mute preserves the accepted answer and resumes its reply",async()=>{
 const response=deferred(),h=setup({request:url=>url==="/api/transcribe"?{text:"A retained answer."}:response.promise});
 await h.voice.start();await h.say();h.voice.setMuted(true);assert.equal(h.track.enabled,false);
 assert.equal(h.requests[1].opts.signal.aborted,false);response.resolve(approved());await flush();
 assert.equal(h.spoken.length,0);assert.deepEqual(h.answers,["A retained answer."]);h.voice.setMuted(false);await flush();
 assert.equal(h.spoken.length,1);await h.voice.stop();
});
await check("mute discards an unfinished recording without transcribing it",async()=>{const h=setup();await h.voice.start();await h.tick(200,.1);h.voice.toggleMute();await flush();assert.equal(h.requests.length,0);assert.equal(h.track.enabled,false);h.voice.toggleMute();assert.equal(h.voice.status,"listening");await h.voice.stop();});
await check("stopping playback cannot reopen the microphone",async()=>{const playback=deferred(),h=setup({speak:()=>playback.promise});await h.voice.start();await h.say();await h.voice.stop();assert.equal(h.spoken[0].opts.signal.aborted,true);assert.equal(h.playbackStops(),1);playback.resolve();await flush();assert.equal(h.voice.active,false);assert.equal(h.voice.status,"idle");assert.equal(h.track.stopped,1);assert.equal(h.answers.length,1);assert.equal(h.results.length,1);});
await check("late microphone permission is cleaned up",async()=>{const permission=deferred(),h=setup({permission:permission.promise});const starting=h.voice.start();await h.voice.stop();permission.resolve(h.stream);assert.equal(await starting,false);assert.equal(h.track.stopped,1);assert.equal(h.recorders.length,0);assert.equal(h.requests.length,0);});
await check("starting twice cannot open two microphones",async()=>{const permission=deferred(),h=setup({permission:permission.promise});const first=h.voice.start();assert.equal(await h.voice.start(),false);assert.equal(h.permissionCalls(),1);permission.resolve(h.stream);await first;await h.voice.stop();});
for(const kind of ["complete","pause"]){await check("authorized terminal response stops after playback",async()=>{const playback=deferred(),h=setup({request:url=>url==="/api/transcribe"?{text:"Please stop."}:approved("We can stop here.",kind),speak:()=>playback.promise});await h.voice.start();await h.say();assert.equal(h.voice.active,true);assert.equal(h.track.enabled,false);playback.resolve();await flush();assert.equal(h.voice.active,false);assert.equal(h.recorders.length,2,"The answer's recorder and the one kept open while its reply was prepared; none after the terminal response");assert.ok(h.recorders.every(recorder=>recorder.state==="inactive"));assert.equal(h.spoken.length,1);});}
await check("silence cannot create paid transcription loops",async()=>{const h=setup();await h.voice.start();const timer=[...h.timers.values()].find(t=>t.ms===90000);timer.fn();await flush();assert.equal(h.requests.length,0);assert.equal(h.voice.status,"listening");assert.equal(h.recorders.length,2);await h.voice.stop();});
// live-voice-reviewed-7: the capture bound runs from the first speech and never hands half an answer
// to the interviewer. (This replaces "long spoken segments have a real capture bound", which asserted
// that the bound, 90 s after listening began, produced an upload and a reply whatever was being said.)
const bounds=h=>[...h.timers.values()].filter(timer=>timer.ms===90000);
await check("the bound that began with listening does not cut off an answer started late",async()=>{
 const h=setup();await h.voice.start();const fromListening=bounds(h)[0];
 for(let second=0;second<83;second++)await h.tick(1000,0);
 await h.talk(3000);fromListening.fn();await flush();
 assert.equal(h.requests.length,0,"Nothing is submitted while the participant is speaking");assert.equal(h.recorders.length,1);assert.equal(h.recorders[0].state,"recording");assert.equal(h.notices.length,0);
 await h.talk(2000);await h.quiet(2300);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/interview"]);assert.equal(h.answers.length,1);assert.equal(h.spoken.length,1);await h.voice.stop();
});
await check("ninety seconds of speech without a pause is said, and recording goes on to the pause",async()=>{
 const h=setup();await h.voice.start();const fromListening=bounds(h)[0];await h.lead();await h.talk(1000);
 const fromSpeech=bounds(h).find(timer=>timer!==fromListening);assert.ok(fromSpeech,"The bound is armed by the first speech");
 fromSpeech.fn();await flush();
 assert.equal(h.requests.length,0,"The interviewer is not asked mid-sentence");assert.equal(h.recorders[0].state,"recording");assert.equal(h.notices.length,1);assert.match(h.notices[0],/90 seconds/);
 await h.talk(500);await h.quiet(2300);assert.equal(h.requests.length,2);assert.equal(h.answers.length,1);assert.equal(h.recorders[0].state,"inactive");await h.voice.stop();
});
const reachSecondBound=async h=>{
 const fromListening=bounds(h)[0];await h.lead();await h.talk(1000);
 const first=bounds(h).find(timer=>timer!==fromListening);first.fn();await flush();
 const second=bounds(h).find(timer=>timer!==fromListening&&timer!==first);assert.ok(second,"A second bound follows the first");second.fn();await flush();
};
await check("the second bound saves that part and the interviewer still waits for the pause",async()=>{
 let heard=0;const h=setup({request:url=>url==="/api/transcribe"?{text:["The first three minutes.","And the rest."][heard++]}:approved()});
 await h.voice.start();await reachSecondBound(h);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe"],"The part is transcribed; no reply is requested while the participant is speaking");
 assert.deepEqual(h.answers,["The first three minutes."]);assert.match(h.notices.at(-1),/three minutes.*still listening/);assert.equal(h.recorders.length,2);assert.equal(h.recorders[1].state,"recording");assert.equal(h.track.enabled,true);
 await h.talk(800);await h.quiet(2300);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/transcribe","/api/interview"]);assert.equal(h.answerInfo[1].continuation,true);
 assert.equal(h.requests[2].data.turns.length,1);assert.equal(h.requests[2].data.turns[0].text,"The first three minutes. And the rest.");assert.equal(h.spoken.length,1);await h.voice.stop();
});
await check("a participant who stops exactly at the second bound still gets the reply",async()=>{
 const h=setup();await h.voice.start();await reachSecondBound(h);assert.equal(h.requests.length,1);
 await h.tick(16,0);assert.equal(h.requests.length,1);await h.quiet(2300);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/interview"]);assert.equal(h.answers.length,1);assert.equal(h.spoken.length,1);assert.equal(h.voice.status,"listening");await h.voice.stop();
});
await check("brief pauses do not cut off an answer",async()=>{const h=setup();await h.voice.start();await h.lead();await h.tick(100,.07);await h.tick(300,.07);await h.tick(600,0);await h.tick(1000,0);assert.equal(h.requests.length,0,"1.6 s of silence is still a pause");await h.tick(400,0);assert.equal(h.requests.length,2,"1.8 s of silence ends the answer");await h.voice.stop();});
// live-voice-reviewed-1: a pause inside an answer no longer costs the rest of it.
const cancelled=opts=>new Promise((_resolve,reject)=>opts.signal.addEventListener("abort",()=>reject(Object.assign(new Error("Cancelled"),{name:"AbortError"})),{once:true}));
await check("the microphone stays open while the reply is prepared and closes for playback",async()=>{
 const reply=deferred(),playback=deferred(),h=setup({request:url=>url==="/api/transcribe"?{text:"The clerk logs the invoice."}:reply.promise,speak:()=>playback.promise});
 await h.voice.start();await h.say();
 assert.equal(h.voice.status,"processing");assert.equal(h.endpoints.length,1,"The end of the turn is announced to the page");
 assert.equal(h.track.enabled,true,"Still capturing while the reply is prepared");assert.equal(h.voice.overlapOpen,true);assert.equal(h.recorders.at(-1).state,"recording");
 await h.tick(100,.1);await h.tick(100,0);
 assert.equal(h.requests[1].opts.signal.aborted,false,"A noise shorter than a word does not cancel the reply");
 reply.resolve(approved());await flush();
 assert.equal(h.voice.status,"speaking");assert.equal(h.track.enabled,false,"The microphone closes for playback");assert.equal(h.voice.overlapOpen,false);assert.equal(h.recorders.at(-1).state,"inactive");
 await h.talk(700,.2);assert.equal(h.requests.length,2,"Nothing is captured during playback");
 playback.resolve();await flush();assert.equal(h.voice.status,"listening");assert.equal(h.track.enabled,true);assert.equal(h.requests.length,2);assert.equal(h.errors.length,0);await h.voice.stop();
});
await check("speech that resumes while the first part is transcribed joins the same answer before the interviewer is asked",async()=>{
 const first=deferred();let heard=0;
 const h=setup({request:url=>url==="/api/transcribe"?(++heard===1?first.promise:{text:"and then prints a spine label."}):approved()});
 await h.voice.start();await h.say();assert.equal(h.requests.length,1);
 await h.talk(500);assert.equal(h.requests[0].opts.signal.aborted,false,"The transcription of the first part is kept");
 first.resolve({text:"The cataloguer scans the barcode"});await flush();
 assert.deepEqual(h.answers,["The cataloguer scans the barcode"]);assert.equal(h.requests.length,1,"No reply is requested while the participant is still answering");assert.equal(h.voice.status,"listening");
 await h.talk(300);await h.quiet(2300);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/transcribe","/api/interview"]);assert.equal(h.answerInfo[1].continuation,true);
 assert.equal(h.requests[2].data.turns.length,1,"One participant turn holds the whole answer");assert.equal(h.requests[2].data.turns[0].text,"The cataloguer scans the barcode and then prints a spine label.");
 assert.equal(h.spoken.length,1);assert.equal(h.errors.length,0);await h.voice.stop();
});
await check("speech that resumes while the reply is prepared cancels that reply and asks again with the whole answer",async()=>{
 let heard=0,asked=0;
 const h=setup({request:(url,_data,opts)=>url==="/api/transcribe"?{text:["The cataloguer scans the barcode","and then prints a spine label."][heard++]}:(++asked===1?cancelled(opts):approved())});
 await h.voice.start();await h.say();assert.equal(h.requests.length,2);assert.equal(h.answers.length,1);
 await h.talk(500);assert.equal(h.requests[1].opts.signal.aborted,true,"The reply to half an answer is cancelled");
 assert.equal(h.voice.status,"listening");assert.equal(h.results.length,0);assert.equal(h.spoken.length,0);assert.equal(h.voice.active,true);
 await h.quiet(2300);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/interview","/api/transcribe","/api/interview"]);
 assert.equal(h.requests[3].data.turns.length,1);assert.equal(h.requests[3].data.turns[0].text,"The cataloguer scans the barcode and then prints a spine label.");
 assert.equal(h.results.length,1);assert.equal(h.spoken.length,1);assert.equal(h.errors.length,0);await h.voice.stop();
});
await check("a continuation that ends before the first transcription returns is kept and added in order",async()=>{
 const first=deferred();let heard=0;
 const h=setup({request:url=>url==="/api/transcribe"?(++heard===1?first.promise:{text:"Then it is filed."}):approved()});
 await h.voice.start();await h.say();await h.talk(500);await h.quiet(2300);
 assert.equal(h.requests.length,1,"The second recording waits for the first");assert.equal(h.answers.length,0);
 first.resolve({text:"The form is signed."});await flush();
 assert.deepEqual(h.answers,["The form is signed.","Then it is filed."]);assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/transcribe","/api/interview"]);
 assert.equal(h.requests[2].data.turns[0].text,"The form is signed. Then it is filed.");assert.equal(h.spoken.length,1);await h.voice.stop();
});
await check("a noise taken for more speech cannot leave the answer without a reply",async()=>{
 let heard=0,asked=0;
 const h=setup({request:(url,_data,opts)=>url==="/api/transcribe"?{text:["We file the form.",""][heard++]}:(++asked===1?cancelled(opts):approved())});
 await h.voice.start();await h.say();await h.talk(500);await h.quiet(2300);
 assert.deepEqual(h.answers,["We file the form."]);assert.equal(asked,2,"The reply is requested again once the noise proves empty");
 assert.equal(h.requests.at(-1).data.turns.at(-1).text,"We file the form.");assert.equal(h.spoken.length,1);assert.equal(h.voice.hasPendingAudio,false);assert.equal(h.voice.active,true);await h.voice.stop();
});
await check("the end-of-turn pause can be lengthened within bounds",async()=>{
 const h=setup({options:{silenceMs:3000}});await h.voice.start();await h.lead();await h.talk(700);await h.quiet(2300);
 assert.equal(h.requests.length,0,"2.3 s is still a pause when the setting is 3 s");await h.quiet(700);assert.equal(h.requests.length,2);await h.voice.stop();
 for(const [value,expected] of [[200,1000],[60000,5000],["soon",1800],[undefined,1800],[2500.4,2500]])assert.equal(setup({options:{silenceMs:value}}).voice.silenceMs,expected);
});
await check("a noise blip shorter than a word is dropped locally without a transcription call",async()=>{const h=setup();await h.voice.start();await h.tick(100,.1);await h.tick(100,0);await h.quiet(1800);await flush();assert.equal(h.requests.length,0,"No paid transcription for a blip");assert.equal(h.voice.status,"listening");assert.equal(h.recorders.length,2,"The noisy segment is discarded and a fresh recorder listens");await h.say();assert.equal(h.requests.length,2,"Real speech afterwards is still transcribed");await h.voice.stop();});
// live-voice-reviewed-9: the noise gate must not eat one-word answers, and says so when it drops a near miss.
// Frames every 10 ms; ms is the time the level stays above the speech threshold.
const utter=async(h,ms,sound)=>{await h.lead();for(let spent=0;spent<ms;spent+=10)await h.tick(10,sound);await h.quiet(2300);};
await check("a clearly spoken one-word answer is transcribed instead of being dropped",async()=>{
 const h=setup({request:url=>url==="/api/transcribe"?{text:"No."}:approved()});await h.voice.start();await utter(h,160,.3);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/interview"]);assert.deepEqual(h.answers,["No."]);assert.equal(h.notices.length,0);await h.voice.stop();
});
for(const [ms,sound,transcribed,told,why] of [
  [30,.3,false,false,"a click is dropped without comment"],
  [50,.3,false,true,"a loud sound shorter than a word is a near miss"],
  [60,.3,true,false,"a short word spoken clearly passes on its level"],
  [60,.03,false,true,"the same length spoken faintly is a near miss"],
  [180,.03,false,true,"faint audio just under a quarter second with its tail is a near miss"],
  [190,.03,true,false,"a quarter second of voiced audio, tail included, passes at any level"],
  [190,.06,true,false,"just under the clear-speech level still passes on length"]]){
 await check("noise gate boundary: "+why,async()=>{
  const h=setup();await h.voice.start();await utter(h,ms,sound);
  assert.equal(h.requests.length,transcribed?2:0,`${ms} ms at ${sound}`);assert.equal(h.notices.length,told?1:0,`${ms} ms at ${sound}: notice`);
  if(told)assert.match(h.notices[0],/didn’t catch that.*say a little more/);
  assert.equal(h.voice.status,"listening");assert.equal(h.voice.active,true);assert.equal(h.errors.length,0);await h.voice.stop();
 });
}
await check("a near miss is said to have been missed and the next answer is still heard",async()=>{
 const h=setup();await h.voice.start();await utter(h,60,.03);
 assert.equal(h.requests.length,0,"No paid transcription for it");assert.equal(h.recorders.length,2,"A fresh recorder listens");assert.equal(h.voice.hasPendingAudio,false);
 await h.say();assert.equal(h.requests.length,2);assert.equal(h.answers.length,1);await h.voice.stop();
});
// live-voice-reviewed-10 (and item 2 of live-voice-reviewed-1): speech already under way when the
// microphone opens is not taken for a complete answer.
await check("an answer already under way when the microphone opens is not submitted; the participant is asked to repeat it",async()=>{
 const h=setup();await h.voice.start();
 await h.tick(16,.1);await h.talk(1600,.1);await h.quiet(2300);
 assert.equal(h.requests.length,0,"The tail of an answer is not transcribed");assert.equal(h.answers.length,0);assert.equal(h.notices.length,1);assert.match(h.notices[0],/wasn’t listening yet.*say that again/);
 assert.equal(h.voice.status,"listening");assert.equal(h.recorders.length,2);assert.equal(h.recorders[0].state,"inactive");assert.equal(h.track.enabled,true);
 await h.talk(700,.1);await h.quiet(2300);
 assert.equal(h.requests.length,2,"The repeat is heard in full: the microphone was open when it began");assert.equal(h.answers.length,1);assert.equal(h.notices.length,1);await h.voice.stop();
});
await check("a participant who starts early again is heard, with a warning, instead of being turned away every turn",async()=>{
 const h=setup();await h.voice.start();
 await h.tick(16,.1);await h.talk(700,.1);await h.quiet(2300);assert.equal(h.requests.length,0);
 await h.talk(700,.1);await h.quiet(2300);assert.equal(h.requests.length,2);assert.equal(h.voice.status,"listening","The reply was spoken and the microphone reopened");
 await h.tick(16,.1);await h.talk(700,.1);await h.quiet(2300);
 assert.equal(h.requests.length,4,"Starting early a second time is accepted");assert.equal(h.answers.length,2);assert.match(h.notices.at(-1),/may have started before I was listening/);
 await h.tick(16,0);await h.tick(300,0);await h.talk(700,.1);await h.quiet(2300);assert.equal(h.requests.length,6);assert.equal(h.notices.length,2,"A clean start needs no notice");
 await h.tick(16,.1);await h.talk(700,.1);await h.quiet(2300);
 assert.equal(h.requests.length,6,"After a clean start, an early one is asked to be repeated again");assert.match(h.notices.at(-1),/wasn’t listening yet/);await h.voice.stop();
});
await check("a long answer that began early is kept, with a warning, rather than thrown away",async()=>{
 const h=setup();await h.voice.start();
 await h.tick(16,.1);await h.talk(12000,.1);await h.quiet(2300);
 assert.equal(h.requests.length,2);assert.equal(h.answers.length,1);assert.equal(h.notices.length,1);assert.match(h.notices[0],/may have started before I was listening/);await h.voice.stop();
});
for(const [delay,clipped] of [[140,true],[160,false]]){
 await check(`speech first heard ${delay} ms after the microphone opens is ${clipped?"":"not "}treated as a clipped start`,async()=>{
  const h=setup();await h.voice.start();
  for(let spent=10;spent<delay;spent+=10)await h.tick(10,0);
  await h.tick(10,.1);await h.talk(700,.1);await h.quiet(2300);
  assert.equal(h.requests.length,clipped?0:2);assert.equal(h.notices.length,clipped?1:0);await h.voice.stop();
 });
}
await check("a recording that follows one with the microphone open all along is never a clipped start",async()=>{
 const h=setup();await h.voice.start();await utter(h,60,.03);assert.equal(h.recorders.length,2);assert.equal(h.notices.length,1);
 await h.tick(10,.1);await h.talk(700,.1);await h.quiet(2300);
 assert.equal(h.requests.length,2,"Voiced at its first frame, but nothing was missed");assert.equal(h.notices.length,1);await h.voice.stop();
});
await check("the page can tell when the app holds the microphone closed",async()=>{
 const opening=deferred(),reply=deferred(),playback=deferred(),h=setup({opening:()=>opening.promise,request:url=>url==="/api/transcribe"?{text:"An answer."}:reply.promise,speak:()=>playback.promise});
 const starting=h.voice.start();await flush();assert.equal(h.voice.status,"processing");assert.equal(h.voice.microphoneHeld,true,"Held while the opening question is prepared");
 opening.resolve(null);await starting;assert.equal(h.voice.status,"listening");assert.equal(h.voice.microphoneHeld,false);
 await h.say();assert.equal(h.voice.status,"processing");assert.equal(h.voice.microphoneHeld,false,"Open while the reply is prepared");
 reply.resolve(approved());await flush();assert.equal(h.voice.status,"speaking");assert.equal(h.voice.microphoneHeld,true,"Held during playback");
 playback.resolve();await flush();assert.equal(h.voice.microphoneHeld,false);await h.voice.stop();assert.equal(h.voice.microphoneHeld,false);
});
// live-voice-reviewed-4: the level meter does not depend on animation frames, and time nobody
// measured is neither speech nor silence.
const frameTimers=h=>[...h.timers.values()].filter(timer=>timer.ms===250||timer.ms===1000).map(timer=>timer.ms);
await check("an answer spoken while animation frames are parked is still heard",async()=>{
 const h=setup();await h.voice.start();
 for(let second=0;second<4;second++)await h.beat(1000,.07);
 await h.beat(1000,0);await h.beat(1000,0);
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/interview"]);assert.equal(h.answers.length,1);assert.equal(h.notices.length,0);await h.voice.stop();
});
await check("a hidden page is metered by timer and goes back to animation frames when shown",async()=>{
 const h=setup();await h.voice.start();assert.equal(h.frames.size,1);assert.deepEqual(frameTimers(h),[1000],"A timer backs up every animation frame");
 h.setHidden(true);assert.equal(h.frames.size,0,"The parked animation frame is dropped");assert.deepEqual(frameTimers(h),[250]);
 for(let step=0;step<8;step++)await h.beat(250,.07);
 await h.beat(1000,0);await h.beat(1000,0);assert.equal(h.requests.length,2,"The answer given in the background gets its reply");assert.equal(h.answers.length,1);
 h.setHidden(false);assert.equal(h.frames.size,1);assert.deepEqual(frameTimers(h),[1000]);
 await h.voice.dispose();assert.equal(h.page.listeners.visibilitychange,undefined);assert.equal(h.timers.size,0);assert.equal(h.frames.size,0);
});
await check("a typed retry's approved unanswered line can be heard once after reconnecting",async()=>{
 const h=setup(),result=approved("What does Treasury record?","final_check");
 h.snapshot.turns.push({id:"q",role:"assistant",text:result.question});h.voice.rememberUnplayed(result);
 await h.voice.start();assert.equal(h.spoken.length,1);assert.equal(h.spoken[0].text,result.question);
 assert.equal(h.requests.length,0);assert.equal(h.results.length,0);await h.voice.stop();
 await h.voice.start();assert.equal(h.spoken.length,1);await h.voice.stop();
 h.voice.rememberUnplayed(result);h.snapshot.turns.push({id:"u2",role:"user",text:"Something else."});
 await h.voice.start();assert.equal(h.spoken.length,1);await h.voice.stop();
});
await check("one late frame cannot turn a click into speech",async()=>{
 const h=setup();await h.voice.start();await h.tick(16,0);
 // Thirty seconds pass unmeasured; the next frame arrives during a click: only the newest 21 ms are loud.
 h.setShape(buffer=>{buffer.fill(0);buffer.fill(.3,Math.max(0,buffer.length-1024));});
 await h.tick(30000);h.setShape(null);await h.quiet(2300);
 assert.equal(h.requests.length,0,"The gap is not counted as voiced time");assert.equal(h.voice.status,"listening");await h.voice.stop();
});
await check("one silent reading after a gap does not end the answer",async()=>{
 const h=setup();await h.voice.start();await h.lead();await h.talk(700);
 await h.tick(2500,0);assert.equal(h.requests.length,0,"2.5 s that nobody measured is not 1.8 s of silence");
 await h.tick(700,0);assert.equal(h.requests.length,2,"A second silent reading ends the turn");await h.voice.stop();
});
await check("silence that was never measured is not dropped without a word",async()=>{
 const h=setup();await h.voice.start();
 // The page was frozen: neither animation frames nor the meter's timers ran before the 90 s recycle.
 h.advance(90000);[...h.timers.values()].find(timer=>timer.ms===90000).fn();await flush();
 assert.equal(h.requests.length,0,"Unmeasured audio is not sent for transcription");assert.equal(h.recorders.length,2);assert.equal(h.notices.length,1);
 assert.match(h.notices[0],/paused while this window was in the background/);assert.equal(h.voice.status,"listening");await h.voice.stop();
});
await check("a page that returns after a freeze says that listening had paused and records afresh",async()=>{
 const h=setup();await h.voice.start();await h.tick(16,0);h.advance(40000);await h.tick(16,0);
 assert.equal(h.notices.length,1);assert.match(h.notices[0],/paused while this window was in the background/);
 assert.equal(h.recorders.length,2);assert.equal(h.recorders[0].state,"inactive");assert.equal(h.requests.length,0);
 await h.say();assert.equal(h.requests.length,2,"The next answer is heard");await h.voice.stop();
});
await check("an empty transcription keeps listening and only a run of them stops the session",async()=>{let calls=0;const h=setup({request:url=>url==="/api/transcribe"?{text:["  ","","","Finally an answer."][calls++]}:approved()});await h.voice.start();await h.say();assert.equal(h.answers.length,0);assert.equal(h.voice.active,true);assert.equal(h.voice.status,"listening");assert.match(h.notices[0],/didn’t catch that/);assert.equal(h.errors.length,0);
  await h.say();assert.equal(h.voice.active,true);await h.say();assert.equal(h.voice.active,false,"Three empty answers in a row stop the session");assert.match(h.errors[0],/several times in a row/);assert.equal(h.answers.length,0);});
await check("a real answer resets the empty-transcription count",async()=>{let calls=0;const h=setup({request:url=>url==="/api/transcribe"?{text:["","Logged in the register.","",""][calls++]}:approved()});await h.voice.start();await h.say();await h.say();assert.deepEqual(h.answers,["Logged in the register."]);await h.say();await h.say();assert.equal(h.voice.active,true,"Two empties after a real answer are not yet a run of three");await h.voice.stop();});
await check("empty transcription cannot start an interview request",async()=>{const h=setup({request:()=>({text:"  "})});await h.voice.start();await h.say();assert.equal(h.requests.length,1);assert.equal(h.answers.length,0);assert.equal(h.voice.active,true,"One empty answer does not end the session");assert.equal(h.requests.filter(item=>item.url==="/api/interview").length,0);await h.voice.stop();});
await check("empty transcription keeps listening without submitting an answer or retrying automatically",async()=>{const h=setup({request:()=>({text:"  "})});await h.voice.start();await h.say();assert.equal(h.requests.length,1);assert.equal(h.answers.length,0);assert.equal(h.voice.active,true);assert.equal(h.voice.status,"listening");assert.equal(h.voice.hasPendingAudio,true);assert.match(h.notices[0],/No speech was recognized/);assert.equal(h.spoken.length,0);await h.voice.dispose();});
await check("transcription failure reports the unsaved audio accurately",async()=>{const h=setup({request:()=>Promise.reject(Error("Private transcription failure"))});await h.voice.start();await h.say();assert.equal(h.answers.length,0);assert.equal(h.requests.length,1);assert.match(h.errors[0],/could not transcribe/);assert.doesNotMatch(h.errors[0],/Private/);assert.equal(h.voice.active,false);});
await check("provider success with no recognized speech is recoverable",async()=>{const h=setup({request:()=>Promise.reject(Error("No speech was recognized. Try recording again or type your answer."))});await h.voice.start();await h.say();assert.equal(h.voice.active,true);assert.equal(h.voice.status,"listening");assert.equal(h.requests.length,1);assert.equal(h.voice.hasPendingAudio,true);assert.equal(h.recovery.at(-1).reason,"no_speech");await h.voice.dispose();});
await check("quota guidance retains one recording for explicit retry and never loops",async()=>{let fail=true;const h=setup({request:url=>url==="/api/transcribe"?(fail?Promise.reject(Error("The selected OpenAI project has no available API quota. Check that project's billing and usage limits.")):{text:"The clerk logs the invoice."}):approved()});await h.voice.start();await h.say();assert.equal(h.voice.active,false);assert.equal(h.voice.hasPendingAudio,true);assert.match(h.errors[0],/API project has no available quota/);assert.equal(h.requests.length,1);await h.tick(100000,.1);assert.equal(h.requests.length,1);fail=false;assert.equal(await h.voice.retryTranscription(),true);assert.equal(h.requests.length,3);assert.equal(h.requests[0].data,h.requests[1].data);assert.equal(h.answers.length,1);assert.equal(h.voice.hasPendingAudio,false);await h.voice.dispose();});
await check("retry from listening discards current capture and cannot duplicate an accepted answer",async()=>{let fail=true;const h=setup({request:url=>url==="/api/transcribe"?(fail?{text:""}:{text:"A recovered answer."}):approved()});await h.voice.start();await h.say();const previous=h.recorders.at(-1);fail=false;assert.equal(await h.voice.retryTranscription(),true);assert.equal(previous.state,"inactive");assert.equal(h.answers.length,1);assert.equal(await h.voice.retryTranscription(),false);assert.equal(h.requests.length,3);await h.voice.dispose();});
await check("source changes invalidate retained audio instead of inserting it in the wrong place",async()=>{const h=setup({request:()=>Promise.reject(Error("Connection interrupted"))});await h.voice.start();await h.say();h.snapshot.turns.push({id:"correction",role:"user",text:"A new answer."});assert.equal(await h.voice.retryTranscription(),false);assert.equal(h.voice.hasPendingAudio,false);assert.equal(h.requests.length,1);assert.match(h.errors.at(-1),/interview changed/);await h.voice.dispose();});
await check("source changes during an explicit retry reject late transcription",async()=>{const response=deferred();let fail=true;const h=setup({request:()=>fail?Promise.reject(Error("Connection interrupted")):response.promise});await h.voice.start();await h.say();fail=false;const retry=h.voice.retryTranscription();await flush();h.snapshot.turns.push({id:"correction",role:"user",text:"New account."});response.resolve({text:"An obsolete answer."});await retry;assert.equal(h.answers.length,0);assert.equal(h.voice.hasPendingAudio,false);assert.match(h.errors.at(-1),/interview changed/);await h.voice.dispose();});
await check("retained audio expires and page exit clears it",async()=>{const h=setup({request:()=>Promise.reject(Error("Connection interrupted"))});await h.voice.start();await h.say();assert.equal(h.voice.hasPendingAudio,true);const expiry=[...h.timers.values()].find(t=>t.ms===600000);assert.ok(expiry);expiry.fn();assert.equal(h.voice.hasPendingAudio,false);await h.voice.start();await h.say();assert.equal(h.voice.hasPendingAudio,true);h.handlers.pagehide();await flush();assert.equal(h.voice.hasPendingAudio,false);assert.equal(h.recovery.at(-1).available,false);await h.voice.dispose();});
await check("oversize failed recordings are not kept or advertised as retryable",async()=>{const h=setup({request:()=>({text:""})});await h.voice.start();h.voice.discardSegment(h.voice.operation);await h.voice.work(h.voice.operation,signal=>h.voice.processAnswer(h.voice.operation,new Blob([new Uint8Array(12*1024*1024+1)]),signal));assert.equal(h.voice.hasPendingAudio,false);assert.match(h.notices.at(-1),/exceeds the in-memory retry limit/);assert.equal(h.voice.status,"listening");await h.voice.dispose();});
// live-voice-reviewed-5: a question that could not be read aloud is still asked. (The first check
// replaces "playback failure retains the approved response", which asserted that the session ended
// with one generic sentence.)
const unread=(message,extra={})=>Promise.reject(Object.assign(new Error(message),extra));
await check("a playback failure keeps the session listening and the approved question in the transcript",async()=>{
 const h=setup({speak:()=>unread("Autoplay refused by a private browser detail")});await h.voice.start();await h.say();
 assert.equal(h.answers.length,1);assert.equal(h.results.length,1);assert.equal(h.voice.active,true,"The session goes on");assert.equal(h.voice.status,"listening");assert.equal(h.track.enabled,true);
 assert.equal(h.errors.length,0);assert.equal(h.problems.length,1);assert.match(h.problems[0],/could not play this question.*on screen.*listening for your answer/);assert.doesNotMatch(h.problems[0],/private browser detail/,"Only wording written by the app is shown");
 await h.say();assert.equal(h.answers.length,2,"The answer to the unread question is heard");assert.equal(h.requests.length,4);assert.equal(h.voice.active,true);await h.voice.stop();
});
await check("the reason the reader gave is passed on instead of one generic sentence",async()=>{
 const reason="The AI voice is unavailable because this API project has no available quota. Check its billing and usage limits, or choose an installed computer voice.";
 const h=setup({speak:()=>unread("reader failed",{voiceMessage:reason})});await h.voice.start();await h.say();
 assert.equal(h.problems.length,1);assert.ok(h.problems[0].startsWith(reason));assert.match(h.problems[0],/listening for your answer/);assert.equal(h.voice.status,"listening");await h.voice.stop();
});
await check("a reader that cannot play the closing line still ends the session as authorized",async()=>{
 const h=setup({request:url=>url==="/api/transcribe"?{text:"That is everything."}:approved("Thank you. The interview is complete.","complete"),speak:()=>unread("no audio")});
 await h.voice.start();await h.say();assert.equal(h.results.length,1);assert.equal(h.voice.active,false);assert.equal(h.problems.length,1);assert.doesNotMatch(h.problems[0],/listening for your answer/);assert.equal(h.errors.length,0);
});
await check("a review acknowledgement that cannot be played does not block the review",async()=>{
 const ack={...approved("Let me check that I have everything before we finish.","review_pending"),review_ticket:"review-one"};let spoken=0;
 const h=setup({request:url=>url==="/api/transcribe"?{text:"Finished my account."}:url==="/api/interview"?ack:approved("Is there anything else to include?","final_check"),speak:()=>++spoken===1?unread("no audio"):Promise.resolve()});
 await h.voice.start();await h.say();
 assert.deepEqual(h.requests.map(r=>r.url),["/api/transcribe","/api/interview","/api/agent-team/review"]);assert.equal(h.spoken.length,2);assert.equal(h.results.length,2);assert.equal(h.problems.length,0,"The unread acknowledgement is on screen and the question that follows was heard");assert.equal(h.voice.status,"listening");await h.voice.stop();
});
await check("reconnecting reads a question that was approved in this page session and never heard",async()=>{
 let reads=0;const h=setup({speak:()=>++reads===1?unread("no audio"):Promise.resolve()});await h.voice.start();await h.say();
 assert.equal(h.spoken.length,1);assert.equal(h.problems.length,1);await h.voice.stop();
 await h.voice.start();
 assert.equal(h.spoken.length,2,"The unheard question is read on reconnect");assert.equal(h.spoken[1].text,h.results[0].question);assert.equal(h.requests.length,2,"Nothing is requested for it");assert.equal(h.results.length,1,"It is not applied twice");assert.equal(h.voice.status,"listening");
 await h.voice.stop();await h.voice.start();assert.equal(h.spoken.length,2,"Once heard, it is not read again");await h.voice.stop();
});
await check("a question whose playback was stopped before any sound is read on reconnect; one stopped while audible is not",async()=>{
 const h=setup({speak:(_text,opts)=>cancelled(opts)});await h.voice.start();await h.say();assert.equal(h.voice.status,"speaking");
 await h.voice.stop();const second=h.voice.start();await flush();assert.equal(h.spoken.length,2,"Stopped while the voice was still being prepared");assert.equal(h.voice.status,"speaking");assert.equal(h.track.enabled,false);
 h.spoken[1].opts.onPlaybackStart();await h.voice.stop();await second;
 await h.voice.start();assert.equal(h.spoken.length,2,"The participant heard it begin and chose to stop");assert.equal(h.voice.status,"listening");await h.voice.stop();
});
await check("an unheard question is not read after the interview has changed",async()=>{
 const h=setup({speak:()=>unread("no audio")});await h.voice.start();await h.say();await h.voice.stop();
 h.snapshot.turns.push({id:"typed",role:"user",text:"I typed the answer instead."});
 await h.voice.start();assert.equal(h.spoken.length,1);assert.equal(h.voice.status,"listening");await h.voice.stop();
});
await check("context receipts do not contact a provider",async()=>{const h=setup();await h.voice.start();const receipt=await h.voice.appendContext("private context",{id:"coverage1",kind:"interview_coverage"});assert.equal(receipt.status,"acknowledged");assert.equal(receipt.reason,"server_snapshot_used");assert.equal(h.requests.length,0);await h.voice.stop();});
await check("audio metering reports measured input only",async()=>{const h=setup();await h.voice.start();await h.tick(100,.06);const frame=h.audioFrames.at(-1);assert.ok(frame.input>0);assert.equal(frame.output,0);assert.equal(frame.outputActive,false);assert.equal(frame.playbackActive,false);await h.voice.stop();});
await check("page exit and repeated disposal clean all resources",async()=>{const h=setup();await h.voice.start();h.handlers.pagehide();await flush();assert.equal(h.track.stopped,1);assert.equal(h.frames.size,0);assert.equal(h.timers.size,0);await h.voice.dispose();await h.voice.dispose();assert.equal(h.handlers.pagehide,undefined);assert.equal(h.track.stopped,1);});
for(const mutation of [r=>{delete r.review_ticket;},r=>{r.question="We are finished.";r.speech_authorization.text=r.question;},r=>{r.completion.complete=true;},r=>{r.completion.ready_for_final_check=true;},r=>{r.coverage_verified=true;}]){
 await check("review acknowledgement cannot carry completion or an invalid ticket",async()=>{const result={...approved("Let me check that I have everything before we finish.","review_pending"),review_ticket:"review-one"};mutation(result);const h=setup({request:url=>url==="/api/transcribe"?{text:"A reported detail."}:result});await h.voice.start();await h.say();assert.equal(h.results.length,0);assert.equal(h.spoken.length,0);assert.equal(h.requests.length,2);assert.equal(h.voice.active,false);});
}
await check("a correction during acknowledgement blocks the review request",async()=>{const playback=deferred(),ack={...approved("Let me check that I have everything before we finish.","review_pending"),review_ticket:"review-one"},h=setup({request:url=>url==="/api/transcribe"?{text:"Original account."}:ack,speak:()=>playback.promise});await h.voice.start();await h.say();h.snapshot.turns.push({id:"correction",role:"user",text:"The exception is still unresolved."});playback.resolve();await flush();assert.equal(h.requests.length,2);assert.equal(h.voice.active,false);assert.match(h.errors[0],/conversation changed/);});
for(const purpose of ["partial",undefined]){await check("partial-review acknowledgement requires its explicit purpose",async()=>{const ack={...approved("Let me check what we have and keep the unanswered parts open.","review_pending"),review_ticket:"partial-ticket",...(purpose?{review_purpose:purpose}:{})},h=setup({request:url=>url==="/api/transcribe"?{text:"I cannot answer the remaining gaps."}:url==="/api/interview"?ack:approved("We can pause with those sections still open.","pause")});await h.voice.start();await h.say();assert.equal(h.spoken.length,purpose?2:0);assert.equal(h.requests.filter(r=>r.url==="/api/agent-team/review").length,purpose?1:0);assert.equal(h.voice.active,false);if(purpose)assert.equal(h.results.at(-1).completion.complete,false);});}
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
