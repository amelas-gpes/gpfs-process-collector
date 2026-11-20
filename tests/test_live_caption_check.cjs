"use strict";
// Live voice caption check (LIVE_CAPTION_CHECK). The live transcriber takes no spelling hints: in the
// November 19 stress test a 20-second accented answer came back with every acronym wrong ("KYC" as
// "kite", "LPAC" as "CPAC"), and notes must quote the caption as it is. Now fund terms and configured
// names in live captions are corrected using the participant's own audio: each final caption's audio
// is transcribed again through /api/transcribe, marked as a caption check so that the server hints it
// with its glossary alone, and only a glossary term read in the place of a misheard caption word
// replaces that word. A whole reading is never used: in a real browser session (2026-11-20,
// stress-lab/verify/live-captions.md) it fixed some terms and broke words the caption had right.
//
// Part 1 runs web/live-voice.js with the fake WebRTC and audio of tests/test_live_voice.cjs and a fake
// audio worklet (tests/test_live_voice_tap.cjs runs the real one): what the tap records, which audio a
// caption gets, mute, bounds, the provider's clock and the fallbacks.
// Part 2 runs web/app.js on the page of web/index.html (tests/fixtures/app_page.cjs) with a stand-in
// transport and server: the request and its glossary, the targeted correction (on the real captions and
// readings of that session), stale and failed results, the notes capture and map that wait, the
// closing sequence and the setting off.
// No microphone, browser, network or provider.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const {open}=require("./fixtures/app_page.cjs");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
const tick=()=>new Promise(resolve=>setImmediate(resolve));
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.stack||error).split("\n").slice(0,8).join("\n     "));}
}

// ---- Part 1: the transport ------------------------------------------------------------------
// The audio clock runs 5 s ahead of the page clock; a block of 100 ms at 48 kHz reaches the page
// 5 ms after its end, every third one 40 ms after. Each block holds one value that names its end
// (page time), so the audio a caption gets says which blocks it came from.
const AHEAD=5000,BLOCK=100,RATE=48000;
const level=end=>((end%50000)+100)/100000;
const sample=end=>Math.round(level(end)*32767);
async function transport({tap=true,worklet=true,script=false,failModule=false,rate=RATE}={}){
 const h=voice.setup({metering:true}),AC=h.window.AudioContext;
 h.modules=[];h.nodes=[];h.gains=[];h.traces=[];
 h.window.CollectorRawTrace={record:(type,payload)=>h.traces.push({type,payload})};
 AC.prototype.sampleRate=rate;AC.prototype.destination={destination:true};AC.prototype.currentTime=0;
 AC.prototype.createGain=function(){const gain={gain:{value:1},connected:[],connect(node){this.connected.push(node);},disconnect(){this.disconnected=true;}};h.gains.push(gain);return gain;};
 if(worklet)AC.prototype.audioWorklet={addModule:async url=>{h.modules.push(url);if(failModule)throw new Error("blocked");}};
 if(script)AC.prototype.createScriptProcessor=function(size,inputs,outputs){
  const node={kind:"script",size,inputs,outputs,onaudioprocess:null,connected:[],connect(next){this.connected.push(next);},disconnect(){this.disconnected=true;}};h.nodes.push(node);return node;};
 h.window.AudioWorkletNode=class{
  constructor(context,name,options){Object.assign(this,{kind:"worklet",context,name,options,connected:[],port:{onmessage:null}});h.nodes.push(this);}
  connect(next){this.connected.push(next);}disconnect(){this.disconnected=true;}};
 if(tap)h.api.options.captionAudio=true;
 await h.api.start({turns:[{id:"t001",role:"assistant",text:"What starts the work?"}]});await tick();
 h.streams[0].level=.05; // the participant is speaking: the gate keeps their captions
 let next=BLOCK; // the end of the next block, on the page clock
 h.now=()=>h.window.performance.now();
 h.deliver=end=>{
  const node=h.nodes.at(-1),samples=new Float32Array(RATE*BLOCK/1000).fill(level(end));
  if(node?.kind==="worklet")node.port.onmessage?.({data:{samples,end:(end+AHEAD)/1000}});
  else if(node?.kind==="script"){h.api.operation.audioContext.currentTime=(end+AHEAD)/1000;node.onaudioprocess?.({inputBuffer:{getChannelData:()=>samples}});}
 };
 // Run the page clock to `until`, a block every 100 ms, and the caption events due on the way.
 h.run=(until,events=[])=>{
  const due=()=>{while(events.length&&events[0].at<=h.now())events.shift().fire();};
  for(;;){
   const arrives=next+((next/BLOCK)%3?5:40);
   if(arrives>until)break;
   if(arrives>h.now())h.step(arrives-h.now());
   h.deliver(next);next+=BLOCK;due();
  }
  if(h.now()<until)h.step(until-h.now());
  due();
 };
 h.user=(delta,start_ms,end_ms)=>h.event({type:"session.input_transcript.delta",event_id:"event_"+start_ms+"_"+delta.length,delta,start_ms,end_ms});
 h.tap=()=>h.api.operation?.tap;
 return h;
}
// The WAV the transport makes: header fields and samples.
function readWav(bytes){
 const view=new DataView(bytes),ascii=(at,n)=>String.fromCharCode(...new Uint8Array(bytes,at,n));
 const samples=new Int16Array((bytes.byteLength-44)/2);for(let i=0;i<samples.length;i++)samples[i]=view.getInt16(44+i*2,true);
 return {riff:ascii(0,4),size:view.getUint32(4,true),wave:ascii(8,4),fmt:ascii(12,4),fmtSize:view.getUint32(16,true),format:view.getUint16(20,true),
  channels:view.getUint16(22,true),rate:view.getUint32(24,true),byteRate:view.getUint32(28,true),align:view.getUint16(32,true),bits:view.getUint16(34,true),
  data:ascii(36,4),dataSize:view.getUint32(40,true),samples};
}

// ---- Part 2: the page -----------------------------------------------------------------------
const EXPOSE="request,captionFix,captionTokens,captionGlossary,receiveCheckedCaption,receiveLiveCaption,receiveLiveStatus,getCapturedThrough,askFinalCheck,startLiveConversation,generateDraft,finalCheck,resetLiveFront,liveNotesStatus";
const HOOK="const getCapturedThrough=()=>liveCapturedThrough,askFinalCheck=line=>{pendingFinalCheck={line};};"+
 "window.__notices=[];const __notice=notice;notice=(message,...rest)=>{window.__notices.push(String(message));return __notice(message,...rest);};";
const CONFIG=(caption_check=true)=>({agent_team:{enabled:true,voice_mode:"live_front",interview_memory:true,stop_intent_patterns:["^(?:i need to stop)$"]},
 live:{enabled:true,caption_check},concurrent_interview:{enabled:true}});
const CAPTION="We run the kite checks before the CPAC meets and the each wire goes out.";
// The check's reading of that audio, and the turn then: "kite" and "CPAC" are corrected to the glossary's
// KYC and LPAC; "each" is a common word, which a check never turns into a term by itself, so it stays.
const RESULT="We run the KYC checks before the LPAC meets and the ACH wire goes out.";
const CHECKED="We run the KYC checks before the LPAC meets and the each wire goes out.";
// The glossary the server names with a check's reading (server.py caption_check_terms, default settings,
// process name "Capital calls"), and an answer of the transcription route to a check.
const TERMS=["KYC","AML","ACH","IRR","LPAC","K-1","NAV","LPA","GL","DPI","SWIFT","PEP","Capital calls","GPFS","GP Fund Solutions","Entrilia","Allvue"];
const READ=(text,terms=TERMS)=>({text,terms});
// A real browser session (2026-11-20, stress-lab/verify/live-captions.md): the jargon passage read by an
// accented voice (A13) and a clear one (A10). The captions of its first run (the tap then sent no audio)
// and the readings gpt-transcribe gave of the same clips in its second run.
const TRUTH="We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation; KYC and AML checks run in Investran and the ACH or SWIFT wire is released only after the callback from treasury. The IRR and the DPI go to the LPAC pack, and the K-1 estimate goes to the CFO.";
const REAL={
 A13:{caption:"We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. Calc and AML checks run in Investran and the ACH or SWIFT wire is released only after the callback from Treasury. DI and the DPI go to the LP AC pack, and the K one estimate goes to the CFO",
  reading:"Instruct the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation, KYC and AML checks run in Investron and the HRSWIFT wire is released only after the call back from treasury, the IR and the DPI go to the LPAC, and the K-1 estimate goes to the CFO."},
 A10:{caption:"We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. KYC and AML checks run in Investran and the ACH or SWIFT wire is released only after the callback from Treasury. DI and the DPI go to the LP AC pack, and the K one estimate goes to the CFO",
  reading:"I reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation, KYC and AML checks run in Investor and the ACH or SWIFT wire is released only after the callback from treasury. The IR and the DPI go to the LPAC, and the K-1 estimate goes to the CFO."},
 // The second run's own captions of the same clips, which its readings were made from.
 A13b:"We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. KYC and AML checks run in Investran and the H or SWIFT wire is released only after the callback from Treasury. DI and the DPI go to the LPAC pack, and the K one estimate goes to the CFO",
 A10b:"We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. KYC and AML checks run in Investran and the ACH or SWIFT wire is released only after the callback from Treasury. The IR and the DPI go to the LPAC pack, and the K one estimate goes to the CFO"};
// Words of a text as compared (case, punctuation and hyphens aside), and how many of them differ from the truth.
const words=text=>text.toLowerCase().replace(/[^a-z0-9 ]+/g," ").split(/\s+/).filter(Boolean);
const errors=text=>{const a=words(text),b=words(TRUTH),d=Array.from({length:a.length+1},(_,i)=>[i,...Array(b.length).fill(0)]);
 for(let j=1;j<=b.length;j++)d[0][j]=j;
 for(let i=1;i<=a.length;i++)for(let j=1;j<=b.length;j++)d[i][j]=Math.min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+(a[i-1]===b[j-1]?0:1));
 return d[a.length][b.length];};
const notes=summary=>({question:"What happens next?",summary,focus:"",parking_lot:[],coverage:[],coverage_verified:false,
 capture_token:"token-"+summary.replace(/\W+/g,"-").toLowerCase(),memo_findings:[],completion:{ready_for_final_check:false,complete:false},
 speech_authorization:{approved:true,kind:"question",text:"What happens next?",revision:"r1",completion_allowed:false}});
async function page({caption_check=true}={}){
 const page=await open({config:CONFIG(caption_check),expose:EXPOSE,hook:HOOK});
 page.state.context={process_name:"Capital calls",process_owner:"",objective:"Understand the work",background:""};
 page.state.started=true;page.state.captureToken="token-before";
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts a capital call?"},{id:"t002",role:"user",text:"The NAV is struck and the GP Fund Solutions team drafts the notice."},
  {id:"t003",role:"assistant",text:"Which checks run before it goes out?"}];
 const h={page,traces:[],audio:[],since:[],transcribe:[],captures:[],interviews:[],maps:[],drafts:[],reviews:[],said:[],context:[]};
 page.window.CollectorRawTrace={record:(type,payload)=>h.traces.push({type,payload}),link(){},references(){},configure(){}};
 page.t.conversationUI.live={active:true,connected:true,participantSpeaking:false,assistantSpeaking:false,
  stop(){this.active=false;return Promise.resolve({finalized:true});},setMuted(){},closeInput(){},
  appendContext(text){h.context.push(text);return Promise.resolve({status:"acknowledged"});},
  say(text){h.said.push(text);return Promise.resolve({status:"acknowledged"});},
  captionAudio(id,since){h.audio.push(id);h.since.push(since);return {wav:new ArrayBuffer(44+32000*2),duration_ms:2000};}};
 page.t.receiveLiveStatus("connecting");
 // Each request stays on its way until the test answers it; a cancelled one fails as fetch does.
 const pending=(list,url,init,body)=>new Promise((resolve,reject)=>{
  const entry={url,init,body,resolve,reject,aborted:false};list.push(entry);
  init.signal?.addEventListener("abort",()=>{entry.aborted=true;reject(new DOMException("The operation was aborted.","AbortError"));});
 });
 page.route((url,init,body)=>{
  if(url==="/api/transcribe")return pending(h.transcribe,url,init,body);
  // The notes captures of the live front; any other interview request (Wrap up) apart.
  if(url==="/api/agent-team/interview")return pending(body?.live_notes&&body.action==="answer"?h.captures:h.interviews,url,init,body);
  if(url==="/api/agent-team/workflow")return pending(h.maps,url,init,body);
  if(url==="/api/draft")return pending(h.drafts,url,init,body);
  if(url==="/api/agent-team/review"){h.reviews.push(body);return pending([],url,init,body);}
  return {};
 });
 h.say=(id,text,final=true,fragments=[])=>page.t.receiveCheckedCaption({id,role:"user",text,final,start_ms:1000,end_ms:5000,fragments});
 h.interviewer=(id,text)=>page.t.receiveCheckedCaption({id,role:"assistant",text,final:true,start_ms:6000,end_ms:7000,fragments:[]});
 h.answer=async(entry,value)=>{entry.resolve(value);await page.flush();await page.flush();};
 h.refuse=async(entry,status,error)=>{entry.resolve({ok:false,status,json:async()=>({error}),headers:{get:()=>"2"}});await page.flush();await page.flush();};
 h.timer=pattern=>page.waiting(entry=>String(entry[1]?.fn??entry.fn).includes(pattern));
 h.runCapture=async()=>{const timer=page.waiting(entry=>String(entry.fn).includes("runLiveCapture"))[0];assert.ok(timer,"A notes capture is scheduled");await page.run(timer);};
 h.runHold=async()=>{const timer=page.waiting(entry=>String(entry.fn).includes("check.timer=null"))[0];assert.ok(timer,"A caption check holds the notes");await page.run(timer);};
 // The map's start (scheduleWorkflow): fired without waiting for the map request it sends.
 h.runMap=async()=>{const timer=page.waiting(entry=>String(entry.fn).includes("refreshWorkflow"))[0];if(!timer)return false;
  page.timers.delete(timer[0]);page.advance(timer[1].ms);void timer[1].fn();await page.flush();return true;};
 h.turn=()=>page.state.turns.filter(turn=>turn.role==="user").at(-1);
 h.outcomes=()=>h.traces.filter(trace=>trace.type==="live.caption_check").map(trace=>trace.payload.outcome+(trace.payload.reason?":"+trace.payload.reason:""));
 h.lastAnswer=capture=>capture.body.turns.filter(turn=>turn.role==="user").at(-1).text;
 return h;
}

(async()=>{
 // ---- the transport ----
 await check("with the setting off the transport creates no audio node and loads nothing",async()=>{
  const h=await transport({tap:false});
  assert.deepEqual(h.modules,[],"No worklet module is loaded");assert.equal(h.nodes.length,0,"No tap node");assert.equal(h.gains.length,0,"No gain node");
  assert.equal(h.tap(),null);
  h.run(3000,[{at:2500,fire:()=>h.user("We run the kite checks.",1000,2000)}]);
  assert.equal(h.api.captionAudio(h.captions.at(-1).id),null,"No audio is kept");
  assert.equal(h.api.operation.userCaptions.size,0,"Captions are not even listed");
  await h.api.stop({immediate:true});
 });
 await check("a caption's audio is its own window of the echo-cancelled microphone, padded, as a 16 kHz mono WAV",async()=>{
  const h=await transport();
  assert.deepEqual(h.modules,["/live-voice-tap.js"],"The worklet comes from this origin");
  const node=h.nodes[0];
  assert.equal(node.name,"live-voice-tap");assert.equal(node.options.channelCount,1);assert.equal(node.options.channelCountMode,"explicit");
  assert.equal(node.stream,h.streams[0],"It listens to the microphone the live session opened");
  assert.equal(node.connected[0],h.gains[0]);assert.equal(h.gains[0].gain.value,0,"Through a muted gain: nothing is heard");
  assert.equal(h.gains[0].connected[0].destination,true);
  assert.equal(h.tap().kind,"worklet");assert.equal(JSON.stringify(h.traces.find(trace=>trace.type==="live.caption_tap").payload),JSON.stringify({state:"ready",kind:"worklet"}));
  h.run(7000,[{at:5100,fire:()=>h.user("We run the kite checks before the CPAC meets.",3000,5000)}]);
  const caption=h.captions.at(-1);assert.equal(caption.text,"We run the kite checks before the CPAC meets.");
  const audio=h.api.captionAudio(caption.id),file=readWav(audio.wav);
  assert.deepEqual([file.riff,file.wave,file.fmt,file.data],["RIFF","WAVE","fmt ","data"]);
  assert.deepEqual([file.fmtSize,file.format,file.channels,file.rate,file.byteRate,file.align,file.bits],[16,1,1,16000,32000,2,16],"16 kHz 16-bit mono PCM");
  assert.equal(file.dataSize,file.samples.length*2);assert.equal(file.size,36+file.dataSize);assert.equal(audio.wav.byteLength,44+file.dataSize);
  // 3.0 to 5.0 s on the session timeline, 2 s before (the mapping falls late by the time the
  // transcriber takes to deliver its words: 0.7 to 0.9 s in a real session) and 1 s after: 5 seconds.
  assert.ok(Math.abs(file.samples.length-80000)<=8,`5 s of audio (${file.samples.length} samples)`);assert.equal(audio.duration_ms,5000);
  assert.equal(file.samples[0],sample(1000),"It starts 2 s before the caption");
  assert.equal(file.samples[file.samples.length-20],sample(6000),"and ends 1 s after it");
  assert.equal(file.samples[40800],sample(3600),"the middle is the middle");
  const values=new Set(file.samples);
  for(let end=1000;end<=6000;end+=BLOCK)assert.ok(values.has(sample(end)),"block ending at "+end+" is there");
  assert.ok(!values.has(sample(900))&&!values.has(sample(6100)),"Nothing from outside the window");
  // No timestamps, a caption longer than 150 s, a window ahead of what was heard: no audio.
  h.run(10000,[{at:9000,fire:()=>h.event({type:"session.output_transcript.delta",event_id:"a1",delta:"Which checks?",start_ms:8000,end_ms:8800})},
   {at:9500,fire:()=>h.event({type:"session.input_transcript.delta",event_id:"u2",delta:"No timestamps here."})}]);
  assert.equal(h.captions.at(-1).text,"No timestamps here.");assert.ok(h.api.captionAudio(h.captions.at(-1).id)===null,"No timestamps, no audio");
  h.api.operation.userCaptions.get(caption.id).end_ms=3000+150001;
  assert.ok(h.api.captionAudio(caption.id)===null,"Over 150 seconds: the caption keeps its text");
  h.api.operation.userCaptions.get(caption.id).end_ms=5000;
  const dropped=h.tap().chunks.splice(0,33);
  assert.ok(h.api.captionAudio(caption.id)===null,"Its start is no longer in the buffer: audio is missing");
  h.tap().chunks.unshift(...dropped);
  h.tap().chunks.splice(38,3);
  assert.ok(h.api.captionAudio(caption.id)===null,"Audio is missing in the middle of the caption");
  assert.equal(h.api.captionAudio("live_unknown"),null);
  await h.api.stop({immediate:true});
 });
 await check("muted speech is never recorded, and a caption across the mute gets no audio",async()=>{
  const h=await transport();
  h.run(5000,[{at:4950,fire:()=>h.user("We approve it.",4300,4900)}]);
  const before=h.captions.at(-1);
  assert.equal(h.api.setMuted(true),true);
  h.run(7000);
  assert.ok(h.tap().chunks.some(chunk=>chunk.to<=5005),"Audio before the mute is kept");
  assert.ok(!h.tap().chunks.some(chunk=>chunk.to>5050),"Nothing is kept while the microphone is muted");
  // The caption's end now lies after the last audio kept before the mute.
  const held=h.api.operation.userCaptions.get(before.id),kept={end_ms:held.end_ms,lastDelta:held.lastDelta};
  Object.assign(held,{end_ms:5600,lastDelta:7000});
  assert.ok(h.api.captionAudio(before.id)===null,"Audio is missing inside the caption: no audio");
  Object.assign(held,kept);
  assert.equal(h.api.setMuted(false),true);
  h.run(9500,[{at:8600,fire:()=>{h.event({type:"session.output_transcript.delta",event_id:"a1",delta:"Okay, and then?",start_ms:7010,end_ms:7090});h.user("Then the wire goes out.",7100,8500);}}]);
  const after=h.captions.at(-1);assert.equal(after.text,"Then the wire goes out.");
  const file=readWav(h.api.captionAudio(after.id).wav);
  assert.ok(file.samples.length>0);
  // (The low-pass before 16 kHz rings by a few steps where the test's level jumps from block to block.)
  assert.ok(file.samples.every(value=>value===0||value>=sample(7000)-8),"Only audio heard after unmuting");
  await h.api.stop({immediate:true});
 });
 await check("the buffer keeps the last four minutes only",async()=>{
  const h=await transport();
  h.run(300000);
  const tap=h.tap(),kept=tap.chunks.reduce((sum,chunk)=>sum+chunk.samples.length,0);
  assert.equal(kept,tap.length);
  assert.ok(kept<=240*16000,`At most 240 s of samples (${kept/16000} s)`);assert.ok(kept>=239*16000);
  assert.ok(tap.chunks[0].from>=300000-240000-200,"The oldest audio is dropped first");
  await h.api.stop({immediate:true});
 });
 await check("the caption finalized when voice stops still gets its audio; then the tap is released",async()=>{
  const h=await transport();
  const heard=[];
  h.api.options.onTranscript=caption=>{h.captions.push(caption);if(caption.role==="user"&&caption.final)heard.push(h.api.captionAudio(caption.id));};
  h.run(5000,[{at:4500,fire:()=>h.user("We wire the funds after the LPAC signs.",2500,4400)}]);
  const node=h.nodes[0];
  await h.api.stop({immediate:true});
  assert.equal(heard.length,1,"The caption is finalized by the stop");
  assert.ok(heard[0]&&readWav(heard[0].wav).samples.length>40000,"Its audio is handed over while voice ends");
  assert.equal(h.api.operation,null);assert.equal(node.disconnected,true,"The tap is disconnected");assert.equal(node.port.onmessage,null);
  assert.equal(h.api.captionAudio(h.captions.at(-1).id),null,"Nothing is kept after voice has ended");
 });
 await check("without an audio worklet a script processor taps the microphone; without either the check is off",async()=>{
  for(const options of [{worklet:false,script:true},{worklet:true,failModule:true,script:true}]){
   const h=await transport(options);
   assert.equal(h.tap()?.kind,"script",JSON.stringify(options));
   assert.equal(h.nodes[0].size,4096);assert.equal(h.nodes[0].stream,h.streams[0]);assert.equal(h.nodes[0].connected[0],h.gains[0]);
   h.run(7000,[{at:5100,fire:()=>h.user("We run the kite checks.",3000,5000)}]);
   assert.ok(Math.abs(readWav(h.api.captionAudio(h.captions.at(-1).id).wav).samples.length-80000)<=8);
   await h.api.stop({immediate:true});
  }
  const h=await transport({worklet:false,script:false});
  assert.equal(h.tap(),null);assert.equal(h.gains[0]?.disconnected??true,true,"Nothing is left connected");
  assert.equal(JSON.stringify(h.traces.find(trace=>trace.type==="live.caption_tap").payload),JSON.stringify({state:"unavailable"}));
  h.run(6000,[{at:4100,fire:()=>h.user("We run the kite checks.",2000,4000)}]);
  assert.equal(h.api.captionAudio(h.captions.at(-1).id),null);assert.equal(h.api.connected,true,"Voice itself is unaffected");
  await h.api.stop({immediate:true});
 });

 await check("a caption's audio holds the whole answer when its words arrive late, and one timestamp that is too late moves no later window",async()=>{
  // Over a long call the session timeline runs ahead of the page clock (1693 ms at 16.5 minutes, as
  // test_live_speech_gate.cjs models it), and the transcriber delivers each word some time L after
  // it was said, so a caption's timeline maps late by up to L. decode: the end of the block (page
  // time) a sample was taken from; a block holds the 100 ms before its end.
  const decode=value=>Math.round(value/32767*100000-100);
  const covers=(h,caption,from,to)=>{
   const file=readWav(h.api.captionAudio(caption.id).wav);
   return {before:from%50000-decode(file.samples[0]),after:decode(file.samples.at(-1))-100-to%50000};
  };
  for(const late of [200,700,1000]){
   const h=await transport(),S=h.api.operation.sessionStartedAt,P0=125050,ms=t=>t-S+1693+late;
   h.run(P0+3000+late+1600,[
    {at:P0+1500+late,fire:()=>h.user("We approve the kite checks",ms(P0),ms(P0+1500))},
    {at:P0+3000+late,fire:()=>h.user(" before the wire goes out.",ms(P0+1500),ms(P0+3000))}]);
   const {before,after}=covers(h,h.captions.filter(caption=>caption.role==="user").at(-1),P0,P0+3000);
   assert.ok(before>=250,`Words delivered ${late} ms late: the audio begins ${before} ms before the first word`);
   assert.ok(after>=250,`and ends ${after} ms after the last`);
   await h.api.stop({immediate:true});
  }
  // A word whose end is two seconds too late (inside the drift the speech gate allows this late in a
  // call) raises the gate's clock lead for good; the next answer's audio is still its own.
  const h=await transport(),S=h.api.operation.sessionStartedAt,late=300,P0=375050,ms=t=>t-S+1693+late;
  h.run(P0+20000+3000+late+1600,[
   {at:P0+1000+late,fire:()=>h.user("Okay.",ms(P0),ms(P0+1000)+2000)},
   {at:P0+20000+1500+late,fire:()=>h.user("Treasury releases the wire",ms(P0+20000),ms(P0+21500))},
   {at:P0+20000+3000+late,fire:()=>h.user(" after two approvals.",ms(P0+21500),ms(P0+23000))}]);
  const caption=h.captions.filter(item=>item.role==="user").at(-1);
  assert.equal(caption.text,"Treasury releases the wire after two approvals.");
  assert.ok(h.api.operation.inputClockLead>3000,"The speech gate kept the late timestamp");
  const {before,after}=covers(h,caption,P0+20000,P0+23000);
  assert.ok(before>=250&&after>=250,`The next answer's audio holds it whole (${before} ms before, ${after} ms after)`);
  await h.api.stop({immediate:true});
 });
 await check("a provider clock 3.4 s ahead two minutes in, beyond what the speech gate believes, moves the window back: the audio covers the answer and is never refused",async()=>{
  // Real session (2026-11-20): at 122 s into the call a caption ending at end_ms 125600 arrived when
  // 122231 ms had passed, a lead of 3369 ms; the speech gate takes no lead above 500 ms and 1% of the
  // time so early, and its words came some 0.8 s after they were said. A window mapped with the gate's
  // lead lay after the words had arrived, and the check got no audio.
  const decode=value=>Math.round(value/32767*100000-100);
  const h=await transport(),S=h.api.operation.sessionStartedAt,late=800,P0=118550,ms=t=>t-S+3400+late;
  h.run(P0+3000+late+1600,[
   {at:P0+1500+late,fire:()=>h.user("We approve the kite checks",ms(P0),ms(P0+1500))},
   {at:P0+3000+late,fire:()=>h.user(" before the wire goes out.",ms(P0+1500),ms(P0+3000))}]);
  const caption=h.captions.filter(item=>item.role==="user").at(-1),held=h.api.operation.userCaptions.get(caption.id);
  assert.equal(caption.text,"We approve the kite checks before the wire goes out.");
  assert.ok(held.end_ms-(held.lastDelta-S)>=3300,`Its last word is ${held.end_ms-(held.lastDelta-S)} ms ahead of its arrival`);
  assert.ok(h.api.operation.inputClockLead<1000,`The speech gate did not take that lead (${h.api.operation.inputClockLead})`);
  const audio=h.api.captionAudio(caption.id);
  assert.ok(audio,"The caption gets its audio");
  const file=readWav(audio.wav),before=P0%50000-decode(file.samples[0]),after=decode(file.samples.at(-1))-100-(P0+3000)%50000;
  assert.ok(before>=1000,`It begins ${before} ms before the first word, though the words came ${late} ms after they were said`);
  assert.ok(after>=250,`and ends ${after} ms after the last`);
  await h.api.stop({immediate:true});
 });
 await check("the tap filters before it takes 16 kHz: speech-band tones pass clean and 9 to 12 kHz do not fold into them",async()=>{
  const sine=(rate,freq,n,offset)=>{const s=new Float32Array(n);for(let i=0;i<n;i++)s[i]=.5*Math.sin(2*Math.PI*freq*(i+offset)/rate);return s;};
  // A least-squares fit of a tone of freq: its amplitude, and how far everything else lies below it.
  const fit=(x,freq)=>{
   let ss=0,cc=0,sc=0,sx=0,cx=0;
   for(let i=0;i<x.length;i++){const s=Math.sin(2*Math.PI*freq*i/16000),c=Math.cos(2*Math.PI*freq*i/16000);ss+=s*s;cc+=c*c;sc+=s*c;sx+=s*x[i];cx+=c*x[i];}
   const det=ss*cc-sc*sc,a=(sx*cc-cx*sc)/det,b=(cx*ss-sx*sc)/det;let rest=0,tone=0;
   for(let i=0;i<x.length;i++){const y=a*Math.sin(2*Math.PI*freq*i/16000)+b*Math.cos(2*Math.PI*freq*i/16000);rest+=(x[i]-y)**2;tone+=y*y;}
   return {gain:20*Math.log10(Math.hypot(a,b)/.5),sinad:10*Math.log10(tone/rest)};
  };
  for(const rate of [48000,44100]){
   for(const freq of [1000,3000,6000,9000,10000,12000]){
    const h=await transport({rate}),op=h.api.operation,block=Math.round(rate/10);
    for(let index=0;index<20;index++){h.step(100);h.api.receiveTap(op,sine(rate,freq,block,index*block),(h.now()-1)/1000);}
    const x=[];for(const chunk of op.tap.chunks)for(const value of chunk.samples)x.push(value/32767);
    const steady=x.slice(1600,17600);
    if(freq<8000){
     const tone=fit(steady,freq);
     assert.ok(Math.abs(tone.gain)<1&&tone.sinad>=40,`${freq} Hz at ${rate} Hz: ${tone.gain.toFixed(1)} dB, SINAD ${tone.sinad.toFixed(1)} dB`);
    }else{
     const folded=fit(steady,16000-freq);
     assert.ok(folded.gain<=-40,`${freq} Hz at ${rate} Hz folds into ${16000-freq} Hz at ${folded.gain.toFixed(1)} dB`);
    }
    await h.api.stop({immediate:true});
   }
  }
 });
 await check("a script processor's buffers are stamped by the audio they hold, not by when a busy page runs them",async()=>{
  const h=await transport({worklet:false,script:true}),node=h.nodes.at(-1),op=h.api.operation,length=4096*1000/RATE;
  const fire=(heard,handled)=>{
   if(handled>h.now())h.step(handled-h.now());
   op.audioContext.currentTime=(handled+AHEAD)/1000;
   node.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(4096).fill(level(Math.round(heard)))}});
  };
  // A 400 ms long task from 3.0 s: the buffers heard meanwhile are handled together when it ends.
  const waiting=[];
  for(let heard=length;heard<6000;heard+=length){
   if(heard>3000&&heard<3400){waiting.push(heard);continue;}
   for(const queued of waiting.splice(0))fire(queued,3400);
   fire(heard,heard+1);
  }
  const around=op.tap.chunks.filter(chunk=>chunk.to>2900&&chunk.to<3700);
  assert.ok(around.length>=8);
  for(let index=1;index<around.length;index++)assert.ok(Math.abs(around[index].from-around[index-1].to)<1,"One buffer after another, no gap and no overlap");
  h.user("We run the kite checks before the CPAC meets.",2000,4000);
  assert.ok(h.api.captionAudio(h.captions.at(-1).id),"The caption across the long task gets its audio");
  await h.api.stop({immediate:true});
 });

 // ---- the page ----
 await check("a final caption's audio is read again with the glossary as its only hints, and the terms it corrects reach the turn before the notes read it",async()=>{
  const h=await page(),page_=h.page;
  h.say("live_u1","We run the kite checks",false);
  assert.deepEqual(h.audio,[],"Nothing while the caption is still open");
  h.say("live_u1",CAPTION);
  assert.deepEqual(h.audio,["live_u1"],"The final caption's audio is asked for");
  assert.equal(h.transcribe.length,1,"One transcription request");
  const sent=h.transcribe[0];
  assert.equal(sent.init.headers["Content-Type"],"audio/wav");assert.equal(sent.body.type,"audio/wav");assert.equal(sent.body.size,44+64000);
  // Marked as a check, so that the server hints it with its glossary; the page adds only the process
  // name, never a term of the transcript (the typed answer's "NAV" and "GP Fund Solutions" included).
  assert.equal(sent.init.headers["X-Transcription-Purpose"],"live-caption-check");
  assert.equal(decodeURIComponent(sent.init.headers["X-Transcription-Hints"]),"Capital calls","The process name alone");
  // The notes capture waits for the check.
  await h.runCapture();
  assert.equal(h.captures.length,0,"The capture waits for the caption check");
  assert.equal(h.turn().text,CAPTION);
  await h.answer(sent,READ(RESULT));
  assert.equal(h.turn().text,CHECKED,"The turn holds the corrected terms, and the caption's own words elsewhere");
  assert.equal(page_.text("transcript").includes(CHECKED),true,"The transcript shows it");
  await h.runCapture();
  assert.equal(h.captures.length,1,"Then the capture runs");
  assert.equal(h.lastAnswer(h.captures[0]),CHECKED,"and reads the checked wording");
  await h.answer(h.captures[0],notes("Notes with KYC"));
  assert.equal(page_.t.getCapturedThrough(),h.turn().id+":"+CHECKED);
  // The transport sends the caption's own text again (a new caption begins): the replacement stays, nothing is repeated.
  h.say("live_u1",CAPTION);h.interviewer("live_a1","Who signs the wire?");
  assert.equal(h.turn().text,CHECKED);assert.equal(h.transcribe.length,1);assert.deepEqual(h.audio,["live_u1"]);
  assert.deepEqual(h.outcomes(),["sent","replaced"]);
  assert.equal(h.traces.find(trace=>trace.payload.outcome==="replaced").payload.count,2,"Two terms corrected");
  assert.ok(h.traces.filter(trace=>trace.type==="live.caption_check").every(trace=>!JSON.stringify(trace.payload).includes("kite")&&!JSON.stringify(trace.payload).includes("KYC")),"No text in the trace");
  assert.equal(page_.window.__notices.length,0,"Nothing is said to the participant");
 });
 await check("a caption that grows after it was sent is checked again whole; the stale result is never used",async()=>{
  const h=await page();
  h.say("live_u1","We run the kite checks before the CPAC meets.");
  const first=h.transcribe[0];
  // The participant goes on: the caption grows.
  h.say("live_u1",CAPTION,false);
  assert.equal(first.aborted,true,"The out-of-date request is cancelled");
  await h.page.flush();
  assert.equal(h.transcribe.length,1,"Nothing new while the caption is open");
  h.say("live_u1",CAPTION);
  assert.equal(h.transcribe.length,2,"The whole caption is checked once it is final again");assert.deepEqual(h.audio,["live_u1","live_u1"]);
  await h.answer(h.transcribe[1],READ(RESULT));
  assert.equal(h.turn().text,CHECKED);
  assert.deepEqual(h.outcomes(),["sent","discarded:caption_changed","sent","replaced"]);
 });
 await check("a caption that goes on after a quiet checkpoint keeps its checked words; only the words added are checked, from their own audio",async()=>{
  // One answer with three pauses: the transport marks the caption final at each, and it goes on.
  const parts=["After the kite review the CPAC meets."," Then the kite file goes to the CPAC chair.",
   " The each wire is released after the DI is signed off."," And the K one goes out with the kite pack."];
  // ("each" is a common word and stays: see the targeted correction.)
  const fix=value=>value.replace(/kite/g,"KYC").replace(/CPAC/g,"LPAC").replace(/\bDI\b/g,"IRR").replace(/K one/g,"K-1");
  const h=await page(),fragments=[];let text="";
  for(const [index,part] of parts.entries()){
   text+=part;fragments.push({delta:part,start_ms:1000+index*10000,end_ms:5000+index*10000});
   if(index){
    h.say("live_u1",text,false,fragments.slice());
    assert.equal(h.turn().text,fix(parts.slice(0,index).join(""))+part,"While it grows the checked words keep their checked wording");
   }
   h.say("live_u1",text,true,fragments.slice());
   assert.equal(h.transcribe.length,index+1);
   assert.equal(h.since.at(-1),index?1000+index*10000:undefined,"Only the audio of the words added since is sent");
   // The transcription of that audio, with a word of the part before it from the padding.
   await h.answer(h.transcribe.at(-1),READ((index?"meets. ":"")+fix(part.trim()).replace(/The each/,"The ACH")));
   assert.equal(h.turn().text,fix(text));
  }
  // The last part's check is refused under load: the corrections before it stay.
  const last=" That is how it ends for the kite case.";
  text+=last;fragments.push({delta:last,start_ms:41000,end_ms:44000});
  h.say("live_u1",text,false,fragments.slice());h.say("live_u1",text,true,fragments.slice());
  await h.refuse(h.transcribe.at(-1),429,"Several requests are already processing.");
  assert.equal(h.turn().text,fix(parts.join(""))+last);
  assert.equal(h.transcribe.length,5,"One request for each part, none repeated");
  h.say("live_u1",text,true,fragments.slice());assert.equal(h.transcribe.length,5,"The refused part is not sent again by itself");
  // Should the answer go on, the refused part is read again with the words that follow it.
  const more=" The kite pack is filed.";
  text+=more;fragments.push({delta:more,start_ms:46000,end_ms:48000});
  h.say("live_u1",text,false,fragments.slice());h.say("live_u1",text,true,fragments.slice());
  assert.equal(h.transcribe.length,6);assert.equal(h.since.at(-1),41000);
  await h.answer(h.transcribe.at(-1),READ(fix((last+more).trim())));
  assert.equal(h.turn().text,fix(text));
 });
 await check("a refused or failed check keeps the caption, is not repeated or announced, and frees the notes at once",async()=>{
  for(const [status,error] of [[429,"Several requests are already processing. Wait for them to finish."],[503,"The AI service is unavailable."]]){
   const h=await page();
   h.say("live_u1",CAPTION);
   await h.runCapture();assert.equal(h.captures.length,0);
   await h.refuse(h.transcribe[0],status,error);
   assert.equal(h.turn().text,CAPTION,"The caption stays");
   await h.runCapture();assert.equal(h.captures.length,1,"The notes capture goes ahead");assert.equal(h.lastAnswer(h.captures[0]),CAPTION);
   h.say("live_u1",CAPTION);
   assert.equal(h.transcribe.length,1,"No second attempt");
   assert.deepEqual(h.outcomes(),["sent","failed:error"]);
   assert.equal(h.traces.find(trace=>trace.payload.outcome==="failed").payload.status,status);
   assert.equal(h.page.window.__notices.length,0,"Nothing is said to the participant");
  }
 });
 await check("on the real session's captions only glossary terms are corrected, and every word the caption had right stays (A13, A10)",async()=>{
  // The readings fixed some terms and broke words the captions had right ("Instruct" for "We reconcile",
  // "Investron", "HRSWIFT" for "ACH or SWIFT", "IR" for "IRR", "pack" lost). Only their glossary terms
  // in the place of misheard caption words are used: "Calc" (KYC), "LP AC" (LPAC, "pack" kept) and
  // "K one" (K-1). "DI" stays: the reading has "the IR" there, not a term.
  const cases=[
   ["A13, first run's caption",REAL.A13.caption,REAL.A13.reading,
    "We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. KYC and AML checks run in Investran and the ACH or SWIFT wire is released only after the callback from Treasury. DI and the DPI go to the LPAC pack, and the K-1 estimate goes to the CFO",3],
   ["A10, first run's caption",REAL.A10.caption,REAL.A10.reading,
    "We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. KYC and AML checks run in Investran and the ACH or SWIFT wire is released only after the callback from Treasury. DI and the DPI go to the LPAC pack, and the K-1 estimate goes to the CFO",2],
   // The second run's own captions: "H or SWIFT" stays (the reading's "HRSWIFT" is no term), K-1 is corrected.
   ["A13, second run's caption",REAL.A13b,REAL.A13.reading,
    "We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. KYC and AML checks run in Investran and the H or SWIFT wire is released only after the callback from Treasury. DI and the DPI go to the LPAC pack, and the K-1 estimate goes to the CFO",1],
   ["A10, second run's caption",REAL.A10b,REAL.A10.reading,
    "We reconcile the NAV to the GL before the capital call notice goes out. The LPA and each side letter set the allocation. KYC and AML checks run in Investran and the ACH or SWIFT wire is released only after the callback from Treasury. The IR and the DPI go to the LPAC pack, and the K-1 estimate goes to the CFO",1]];
  for(const [name,caption,reading,turn,count] of cases){
   const h=await page();
   h.say("live_u1",caption);
   await h.answer(h.transcribe[0],READ(reading));
   assert.equal(h.turn().text,turn,name);
   assert.deepEqual(h.outcomes(),["sent","replaced"],name);
   assert.equal(h.traces.find(trace=>trace.payload.outcome==="replaced").payload.count,count,name+": terms corrected");
   // No new error: the turn is the caption less the errors it corrected, and better than the whole reading.
   assert.equal(errors(turn),errors(caption)-(caption.includes("LP AC")?count+1:count),name+": errors "+errors(caption)+" then "+errors(turn));
   assert.ok(errors(turn)<errors(reading),name+": the turn ("+errors(turn)+" errors) beats the reading ("+errors(reading)+")");
  }
 });
 await check("a check corrects only a glossary term read in the place of a misheard word; everything else keeps the caption's words",async()=>{
  const used=[
   // (a) one caption word, read as a term: the caption's own punctuation and the rest stay.
   ["We run the kite checks first.","We run the KYC checks first.","We run the KYC checks first."],
   ["We do the kite check, then the wire goes out.","We do the KYC check. Then the wire goes out.","We do the KYC check, then the wire goes out."],
   ["The checks (kite, mostly) run first.","The checks (KYC, mostly) run first.","The checks (KYC, mostly) run first."],
   ["We run, um, the kite checks first.","We run the KYC checks first.","We run, um, the KYC checks first."],
   ["Then the CPAC signs it off.","Then the L P A C signs it off.","Then the LPAC signs it off."],
   ["We send the K one and the DI report.","We send the K-1 and the IRR report.","We send the K-1 and the IRR report."],
   ["We run the pet screening first.","We run the PEP screening first.","We run the PEP screening first."],
   // A configured name is a term too.
   ["We book it in Entralia every month.","We book it in Entrilia every month.","We book it in Entrilia every month."],
   // (b) caption words that spell the term: only they are replaced.
   ["The approvals go to the LP AC pack and then on.","The approvals go to the LPAC and then on.","The approvals go to the LPAC pack and then on."],
   ["Then the L P A C signs it off.","Then the LPAC signs it off.","Then the LPAC signs it off."],
   ["Then the K one goes out.","Then the K-1 goes out.","Then the K-1 goes out."],
   // A term in lower case that begins a sentence takes the caption word's capital.
   ["The NAV is struck. Water fall runs next.","The NAV is struck. waterfall runs next.","The NAV is struck. Waterfall runs next.",[...TERMS,"waterfall"]],
   // "each" is a common word: it stays though the reading has ACH there, and the rest is still corrected.
   ["We run the kite checks and the each wire goes out.","We run the KYC checks and the ACH wire goes out.","We run the KYC checks and the each wire goes out."]];
  for(const [caption,reading,turn,terms] of used){
   const h=await page();
   h.say("live_u1",caption);
   await h.answer(h.transcribe[0],READ(reading,terms));
   assert.equal(h.turn().text,turn,JSON.stringify(reading));
   assert.deepEqual(h.outcomes(),["sent","replaced"],JSON.stringify(reading));
  }
  const kept=[
   // The residual risk of rule (a): a common word read as a term. "each side letter" stays.
   ["The LPA and each side letter set it.","The LPA and ACH side letter set it.","no_correction"],
   // A word, not the term as the glossary writes it.
   ["We give the team a pet talk first.","We give the team a pep talk first.","no_correction"],
   // The term is already right; the reading lost a word, or wrote the same words.
   ["We send it to the LPAC pack today.","We send it to the LPAC today.","no_correction"],
   ["We run the KYC checks before the LPAC meets.","we run the KYC checks, before the LPAC meets!","same"],
   // Differences at the edges, where the window cuts the reading or runs into other speech.
   ["We send it to the CPAC.","So we send it to the LPAC. Thanks.","no_correction"],
   ["Kite checks run first.","Okay. KYC checks run first.","no_correction"],
   ["We approve the wire after the review.","approve the wire after the review.","no_correction"],
   ["Treasury releases the wire after two approvals.","What changed? Treasury releases the wire after","no_correction"],
   ["Treasury releases the wire after two approvals.","releases the wire after two approvals. Thanks, and who","no_correction"],
   // Other differences: more than one word read for one, or two words for one that they do not spell.
   ["We run the kite checks first.","We run the KYC AML checks first.","no_correction"],
   ["We run the kite list checks first.","We run the KYC checks first.","no_correction"],
   ["We approve it and the kite team signs.","We approve it and team signs.","no_correction"],
   // A window that fell on other speech: too few of the caption's words, whatever terms it holds.
   ["We run the kite checks before the CPAC meets.","The LPAC pack goes to the investors with the KYC file on Friday.","misaligned"],
   ["We run the kite checks before the CPAC meets.","","empty"],
   ["We run the kite checks before the CPAC meets.","…","empty"]];
  for(const [caption,reading,reason] of kept){
   const h=await page();
   h.say("live_u1",caption);
   await h.answer(h.transcribe[0],READ(reading));
   assert.equal(h.turn().text,caption,JSON.stringify(reading)+" corrects nothing");
   assert.deepEqual(h.outcomes(),["sent","kept:"+reason],JSON.stringify(reading));
  }
  // A stretch whose caption words already hold the term is left alone. (The alignment always matches
  // such a word, so this guards a stretch made otherwise.)
  const t=(await page()).page.t,was=t.captionTokens("the LPAC meets"),now=t.captionTokens("the LPAC meets");
  assert.equal(t.captionFix("the LPAC meets",was,now,[{i:1,j:1,kind:"sub"}],t.captionGlossary(TERMS)),null);
  // A server that names no glossary (an older one, or another provider) corrects nothing.
  for(const answer of [{text:RESULT},{text:RESULT,terms:[]},{text:RESULT,terms:"KYC"}]){
   const h=await page();
   h.say("live_u1",CAPTION);
   await h.answer(h.transcribe[0],answer);
   assert.equal(h.turn().text,CAPTION);assert.deepEqual(h.outcomes(),["sent","kept:no_terms"]);
  }
 });
 await check("a check that takes too long holds the notes six seconds; its later result is a correction applied once",async()=>{
  const h=await page();
  h.say("live_u1",CAPTION);
  await h.runCapture();assert.equal(h.captures.length,0,"Held");
  await h.runHold();
  await h.runCapture();
  assert.equal(h.captures.length,1,"After six seconds the capture reads the caption as it is");
  assert.equal(h.lastAnswer(h.captures[0]),CAPTION);
  await h.answer(h.transcribe[0],READ(RESULT));
  assert.equal(h.turn().text,CHECKED,"The later result still corrects the turn");
  await h.answer(h.captures[0],notes("Notes from the caption"));
  assert.notEqual(h.page.state.summary,"Notes from the caption","A capture that read the corrected answer is not used");
  await h.runCapture();
  assert.equal(h.captures.length,2,"The capture is redone");assert.equal(h.lastAnswer(h.captures[1]),CHECKED);
  await h.answer(h.captures[1],notes("Notes from the checked wording"));
  assert.equal(h.page.state.summary,"Notes from the checked wording");
  assert.equal(h.page.t.getCapturedThrough(),h.turn().id+":"+CHECKED);
  assert.equal(h.page.waiting(entry=>String(entry.fn).includes("runLiveCapture")).length,0,"and nothing loops");
  assert.equal(h.transcribe.length,1);
 });
 await check("at most two checks at once; the next waits for one to finish",async()=>{
  const h=await page();
  h.say("live_u1","We run the kite checks before it goes.");h.interviewer("live_a1","And then?");
  h.say("live_u2","The CPAC meets on Tuesday morning.");h.interviewer("live_a2","Who attends?");
  h.say("live_u3","Then the K one goes to the GP after that.");
  assert.equal(h.transcribe.length,2,"Two on their way");
  assert.deepEqual(h.audio,["live_u1","live_u2","live_u3"],"The third caption's audio is taken now, while it is held");
  await h.answer(h.transcribe[0],READ("We run the KYC checks before it goes."));
  assert.equal(h.transcribe.length,3,"The third goes when one finishes");
  await h.answer(h.transcribe[1],READ("The LPAC meets on Tuesday morning."));
  await h.answer(h.transcribe[2],READ("Then the K-1 goes to the GP after that."));
  assert.deepEqual(h.page.state.turns.filter(turn=>turn.role==="user").slice(1).map(turn=>turn.text),
   ["We run the KYC checks before it goes.","The LPAC meets on Tuesday morning.","Then the K-1 goes to the GP after that."]);
 });
 await check("the closing sequence and a request to stop decide on the caption: no check",async()=>{
  const h=await page();
  h.page.t.askFinalCheck("Have I missed anything?");h.page.state.closure={asked:true,confirmed:false};h.page.state.coverageVerified=true;
  h.say("live_u1","No, nothing else, thanks.");
  assert.deepEqual(h.audio,[]);assert.equal(h.transcribe.length,0);
  const stop=await page();
  stop.say("live_u1","That is all for today. I need to stop");
  assert.deepEqual(stop.audio,[]);assert.equal(stop.transcribe.length,0);
  // A result that lands once the final check has been asked is not applied.
  const late=await page();
  late.say("live_u1",CAPTION);
  late.page.t.askFinalCheck("Have I missed anything?");late.page.state.closure={asked:true,confirmed:false};
  await late.answer(late.transcribe[0],READ(RESULT));
  assert.equal(late.turn().text,CAPTION);assert.deepEqual(late.outcomes(),["sent","discarded:closing"]);
  // A one-word caption is left as it is.
  const short=await page();short.say("live_u1","Kite.");assert.equal(short.transcribe.length,0);
 });
 await check("voice stopped on an answer: the catch-up waits for its check and reads the checked wording",async()=>{
  const h=await page();
  h.page.t.conversationUI.live.active=false;h.page.t.receiveLiveStatus("closing");
  h.say("live_u1",CAPTION);
  h.page.t.receiveLiveStatus("idle");await h.page.flush();
  assert.equal(h.transcribe.length,1,"The caption finalized by the stop is checked");
  assert.equal(h.captures.length,0,"The catch-up waits for it");
  assert.equal(h.page.state.busy,true);assert.equal(h.page.text("analysis-through"),"Updating notes from your last answer…");
  await h.answer(h.transcribe[0],READ(RESULT));
  assert.equal(h.captures.length,1,"Then the catch-up runs");assert.equal(h.lastAnswer(h.captures[0]),CHECKED);
  await h.answer(h.captures[0],notes("Notes after voice"));
  assert.equal(h.page.state.summary,"Notes after voice");assert.equal(h.page.state.busy,false);
  assert.equal(h.page.t.getCapturedThrough(),h.turn().id+":"+CHECKED);
 });
 await check("with LIVE_CAPTION_CHECK off nothing is recorded or sent and the notes do not wait",async()=>{
  const h=await page({caption_check:false});
  h.say("live_u1",CAPTION);
  assert.deepEqual(h.audio,[],"No audio is asked for");assert.equal(h.transcribe.length,0,"No request");
  await h.runCapture();assert.equal(h.captures.length,1,"The capture is not held");assert.equal(h.lastAnswer(h.captures[0]),CAPTION);
  assert.deepEqual(h.outcomes(),[]);
  // The transport is created without its microphone tap.
  for(const enabled of [false,true]){
   const p=await page({caption_check:enabled}),made=[];
   p.page.t.conversationUI.live=null;
   p.page.window.CollectorLiveVoice=class{constructor(options){made.push(options);this.active=false;}start(){return Promise.resolve(false);}stop(){return Promise.resolve({finalized:true});}};
   await p.page.t.startLiveConversation();
   assert.equal(made.length,1,"The live transport is created");
   assert.equal(made[0].captionAudio,enabled?true:undefined,enabled?"With the check, the tap is asked for":"Without it, no tap");
   assert.equal(made[0].onTranscript.name,enabled?"receiveCheckedCaption":"receiveLiveCaption","Without it, captions go straight to the transcript as before");
  }
 });
 await check("the map waits for a caption check as the notes do: one map, of the checked wording, during voice and after it",async()=>{
  const MAP={workflow:{title:"Capital calls",steps:[],connections:[],open_questions:[]}};
  const h=await page();
  h.say("live_u1",CAPTION);
  // The map would start a second after the final caption, while the check is on its way.
  assert.equal(await h.runMap(),true);assert.equal(h.maps.length,0,"The map waits for the check");
  await h.answer(h.transcribe[0],READ(RESULT));
  assert.equal(await h.runMap(),true);
  assert.equal(h.maps.length,1,"Then one map");assert.equal(h.lastAnswer(h.maps[0]),CHECKED,"of the checked wording");
  await h.answer(h.maps[0],MAP);
  assert.equal(h.page.t.conversationUI.applied,h.page.t.conversationUI.revision,"and it is current");
  assert.equal(await h.runMap(),false,"No second map");
  // Voice stopped on an answer, the check returning before or after the map's start: the map owed
  // for the last spoken answer is drawn from the checked wording and ends up current.
  for(const early of [false,true]){
   const p=await page();
   p.page.t.conversationUI.live.active=false;p.page.t.receiveLiveStatus("closing");
   p.say("live_u1",CAPTION);
   p.page.t.receiveLiveStatus("idle");await p.page.flush();
   if(!early){assert.equal(await p.runMap(),true);assert.equal(p.maps.length,0);}
   await p.answer(p.transcribe[0],READ(RESULT));
   for(const capture of p.captures)await p.answer(capture,notes("Notes after voice"));
   assert.equal(await p.runMap(),true,"The map is started");
   assert.equal(p.maps.length,1);assert.equal(p.lastAnswer(p.maps[0]),CHECKED);
   await p.answer(p.maps[0],MAP);
   assert.equal(p.page.t.conversationUI.applied,p.page.t.conversationUI.revision,"The map is current");
   assert.equal(p.page.text("workflow-status"),"Up to date");
   assert.equal(await p.runMap(),false);
  }
 });
 await check("a check's only hints are the server's glossary: the page marks the request and adds the process name, never a term of the transcript; dictation is as before",async()=>{
  const h=await page(),header=(entry,name)=>entry.init.headers[name];
  h.say("live_u1","After the kite review the CPAC meets and approves the DI number.");
  h.interviewer("live_a1","And then?");
  // A reading corrects the turn's terms, and its own words never become hints: they may be wrong
  // (the real session's "HRSWIFT" and "IR" were the hints of the next check).
  await h.answer(h.transcribe[0],READ("After the KYC review the LPAC meets and approves the IR number."));
  assert.equal(h.turn().text,"After the KYC review the LPAC meets and approves the DI number.");
  h.say("live_u2","Then the CPAC signs and the kite file is closed.");
  assert.equal(h.transcribe.length,2);
  for(const entry of h.transcribe){
   assert.equal(header(entry,"X-Transcription-Purpose"),"live-caption-check","Marked as a caption check");
   assert.equal(decodeURIComponent(header(entry,"X-Transcription-Hints")),"Capital calls","The process name, nothing from the transcript");
  }
  // A process name that is not a short plain term is not sent: the server's glossary is enough.
  const unnamed=await page();
  unnamed.page.state.context.process_name="Capital calls, NAV and fees";
  unnamed.say("live_u1",CAPTION);
  assert.equal(header(unnamed.transcribe[0],"X-Transcription-Hints"),undefined);
  assert.equal(header(unnamed.transcribe[0],"X-Transcription-Purpose"),"live-caption-check");
  // Dictation and reviewed voice send what they always sent: the interview's terms, and no mark.
  const d=await page();
  void d.page.t.request("/api/transcribe",new Blob([new Uint8Array(200)],{type:"audio/webm"}));
  void d.page.t.request("/api/transcribe",new Blob([new Uint8Array(200)],{type:"audio/webm"}),{purpose:"anything-else"});
  await d.page.flush();
  for(const dictated of d.transcribe){
   assert.equal(header(dictated,"X-Transcription-Purpose"),undefined,"Not marked");
   const hints=decodeURIComponent(header(dictated,"X-Transcription-Hints")).split(",");
   assert.ok(hints.includes("Capital calls")&&hints.includes("NAV")&&hints.includes("GP Fund Solutions"),"The interview's terms: "+hints);
  }
 });
 await check("after voice a result that comes too late is not used: the catch-up, a draft and Wrap up read the transcript as it stands",async()=>{
  const stopped=async()=>{
   const h=await page();
   h.page.t.conversationUI.live.active=false;h.page.t.receiveLiveStatus("closing");
   h.say("live_u1",CAPTION);
   h.page.t.receiveLiveStatus("idle");await h.page.flush();
   // The check outlasts its hold: it is given up, and the catch-up reads the caption.
   await h.runHold();
   assert.equal(h.transcribe[0].aborted,true,"The check is given up");
   assert.equal(h.captures.length,1);assert.equal(h.lastAnswer(h.captures[0]),CAPTION);
   await h.answer(h.captures[0],notes("Notes after voice"));
   assert.equal(h.page.state.busy,false);
   return h;
  };
  const d=await stopped();
  const drafting=d.page.t.generateDraft();await d.page.flush();
  assert.equal(d.drafts.length,1);
  await d.answer(d.drafts[0],{draft:{title:"Capital calls",steps:[]},coverage_assessment:null});await drafting;
  assert.equal(d.turn().text,CAPTION);assert.equal(d.captures.length,1,"No second catch-up");
  assert.ok(!d.page.window.__notices.some(message=>/changed while the draft/.test(message)),"The draft is kept: "+d.page.window.__notices);
  assert.ok(d.outcomes().includes("discarded:late"));
  // Wrap up: the close request and the completion review read the same answer.
  const w=await stopped();
  w.page.state.completion={ready_for_final_check:true};w.page.state.config.concurrent_interview.enabled=false;
  // (Wrap up then waits for the completion review, which this test leaves on its way.)
  void w.page.t.finalCheck();await w.page.flush();
  assert.equal(w.interviews.length,1);assert.equal(w.interviews[0].body.action,"close");
  await w.answer(w.interviews[0],{question:"Let me check that I have everything before we finish.",speech_authorization:{kind:"review_pending",approved:true,text:"Let me check that I have everything before we finish."},
   review_ticket:"ticket-1",agent_run_id:"run1",summary:"s",coverage:[],parking_lot:[],capture_token:"tok-close"});
  await w.page.flush();
  assert.equal(w.reviews.length,1,"The completion review is sent");
  assert.equal(w.reviews[0].turns.filter(turn=>turn.role==="user").at(-1).text,w.interviews[0].body.turns.filter(turn=>turn.role==="user").at(-1).text);
  assert.equal(w.turn().text,CAPTION);
  // A check still within its hold when a draft or Wrap up begins is given up then.
  for(const start of ["generateDraft","finalCheck"]){
   const h=await page();
   h.say("live_u1",CAPTION);
   h.page.t.conversationUI.live.active=false;
   void h.page.t[start]();await h.page.flush();
   assert.equal(h.transcribe[0].aborted,true,start+" gives the check up");
   await h.answer(h.transcribe[0],READ(RESULT));
   assert.equal(h.turn().text,CAPTION);
   assert.deepEqual(h.outcomes(),["sent","discarded:closing"]);
  }
 });
 await check("the closing sequence gives every check up at once: none is waited for or sent",async()=>{
  // A request to stop: the catch-up does not wait for the check on its way.
  const h=await page();
  h.say("live_u1",CAPTION);h.interviewer("live_a1","And who approves it?");
  h.say("live_u2","That is all for today. I need to stop");
  assert.equal(h.transcribe[0].aborted,true,"The check on its way is given up");
  h.page.t.receiveLiveStatus("closing");h.page.t.receiveLiveStatus("idle");await h.page.flush();
  assert.equal(h.captures.length,1,"The catch-up runs at once");
  assert.equal(h.timer("check.timer=null").length,0,"Nothing waits for the check");
  assert.deepEqual(h.outcomes(),["sent","skipped:closing","discarded:closing"]);
  // The final check is read out while two checks are on their way and one waits.
  const q=await page();
  q.say("live_u1","We run the kite checks before it goes.");q.interviewer("live_a1","And then?");
  q.say("live_u2","The CPAC meets on Tuesday morning.");q.interviewer("live_a2","Who attends?");
  q.say("live_u3","The each team and the GP attend.");
  assert.equal(q.transcribe.length,2);
  q.page.t.askFinalCheck("Have I missed anything?");q.page.state.closure={asked:true,confirmed:false};
  q.interviewer("live_a3","Have I missed anything?");
  assert.deepEqual(q.transcribe.map(entry=>entry.aborted),[true,true],"Both requests are cancelled");
  await q.page.flush();
  assert.equal(q.transcribe.length,2,"The waiting check is never sent");
  assert.deepEqual(q.outcomes(),["sent","sent","discarded:closing","discarded:closing","discarded:closing"]);
 });
 await check("a new live session gives up the checks of the last one, and the trace says so",async()=>{
  const h=await page();
  h.say("live_u1",CAPTION);
  h.page.t.resetLiveFront();await h.page.flush();
  assert.equal(h.transcribe[0].aborted,true);
  assert.deepEqual(h.outcomes(),["sent","discarded:session_changed"]);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
