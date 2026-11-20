"use strict";
// Live voice caption check (LIVE_CAPTION_CHECK). The live transcriber takes no spelling hints: in the
// November 19 stress test a 20-second accented answer came back with every acronym wrong ("KYC" as
// "kite", "LPAC" as "CPAC"), and notes must quote the caption as it is. Now the participant's own
// microphone audio of each final caption is transcribed again through /api/transcribe with the hints
// dictation sends, and a plausible result replaces the turn's text before the notes read it.
//
// Part 1 runs web/live-voice.js with the fake WebRTC and audio of tests/test_live_voice.cjs and a fake
// audio worklet: what the tap records, which audio a caption gets, mute, bounds and the fallbacks.
// Part 2 runs web/app.js on the page of web/index.html (tests/fixtures/app_page.cjs) with a stand-in
// transport and server: the request, the replacement, stale and failed results, the plausibility
// guard, the notes capture that waits, the closing sequence and the setting off.
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
async function transport({tap=true,worklet=true,script=false,failModule=false}={}){
 const h=voice.setup({metering:true}),AC=h.window.AudioContext;
 h.modules=[];h.nodes=[];h.gains=[];h.traces=[];
 h.window.CollectorRawTrace={record:(type,payload)=>h.traces.push({type,payload})};
 AC.prototype.sampleRate=RATE;AC.prototype.destination={destination:true};AC.prototype.currentTime=0;
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
const EXPOSE="receiveCheckedCaption,receiveLiveCaption,receiveLiveStatus,getCapturedThrough,askFinalCheck,startLiveConversation";
const HOOK="const getCapturedThrough=()=>liveCapturedThrough,askFinalCheck=line=>{pendingFinalCheck={line};};"+
 "window.__notices=[];const __notice=notice;notice=(message,...rest)=>{window.__notices.push(String(message));return __notice(message,...rest);};";
const CONFIG=(caption_check=true)=>({agent_team:{enabled:true,voice_mode:"live_front",interview_memory:true,stop_intent_patterns:["^(?:i need to stop)$"]},
 live:{enabled:true,caption_check},concurrent_interview:{enabled:true}});
const CAPTION="We run the kite checks before the CPAC meets and the each wire goes out.";
const CHECKED="We run the KYC checks before the LPAC meets and the ACH wire goes out.";
const notes=summary=>({question:"What happens next?",summary,focus:"",parking_lot:[],coverage:[],coverage_verified:false,
 capture_token:"token-"+summary.replace(/\W+/g,"-").toLowerCase(),memo_findings:[],completion:{ready_for_final_check:false,complete:false},
 speech_authorization:{approved:true,kind:"question",text:"What happens next?",revision:"r1",completion_allowed:false}});
async function page({caption_check=true}={}){
 const page=await open({config:CONFIG(caption_check),expose:EXPOSE,hook:HOOK});
 page.state.context={process_name:"Capital calls",process_owner:"",objective:"Understand the work",background:""};
 page.state.started=true;page.state.captureToken="token-before";
 page.state.turns=[{id:"t001",role:"assistant",text:"What starts a capital call?"},{id:"t002",role:"user",text:"The NAV is struck and the GP Fund Solutions team drafts the notice."},
  {id:"t003",role:"assistant",text:"Which checks run before it goes out?"}];
 const h={page,traces:[],audio:[],transcribe:[],captures:[],said:[],context:[]};
 page.window.CollectorRawTrace={record:(type,payload)=>h.traces.push({type,payload}),link(){},references(){},configure(){}};
 page.t.conversationUI.live={active:true,connected:true,participantSpeaking:false,assistantSpeaking:false,
  stop(){this.active=false;return Promise.resolve({finalized:true});},setMuted(){},closeInput(){},
  appendContext(text){h.context.push(text);return Promise.resolve({status:"acknowledged"});},
  say(text){h.said.push(text);return Promise.resolve({status:"acknowledged"});},
  captionAudio(id){h.audio.push(id);return {wav:new ArrayBuffer(44+32000*2),duration_ms:2000};}};
 page.t.receiveLiveStatus("connecting");
 // Each request stays on its way until the test answers it; a cancelled one fails as fetch does.
 const pending=(list,url,init,body)=>new Promise((resolve,reject)=>{
  const entry={url,init,body,resolve,reject,aborted:false};list.push(entry);
  init.signal?.addEventListener("abort",()=>{entry.aborted=true;reject(new DOMException("The operation was aborted.","AbortError"));});
 });
 page.route((url,init,body)=>{
  if(url==="/api/transcribe")return pending(h.transcribe,url,init,body);
  if(url==="/api/agent-team/interview")return pending(h.captures,url,init,body);
  return {};
 });
 h.say=(id,text,final=true)=>page.t.receiveCheckedCaption({id,role:"user",text,final,start_ms:1000,end_ms:5000,fragments:[]});
 h.interviewer=(id,text)=>page.t.receiveCheckedCaption({id,role:"assistant",text,final:true,start_ms:6000,end_ms:7000,fragments:[]});
 h.answer=async(entry,value)=>{entry.resolve(value);await page.flush();await page.flush();};
 h.refuse=async(entry,status,error)=>{entry.resolve({ok:false,status,json:async()=>({error}),headers:{get:()=>"2"}});await page.flush();await page.flush();};
 h.timer=pattern=>page.waiting(entry=>String(entry[1]?.fn??entry.fn).includes(pattern));
 h.runCapture=async()=>{const timer=page.waiting(entry=>String(entry.fn).includes("runLiveCapture"))[0];assert.ok(timer,"A notes capture is scheduled");await page.run(timer);};
 h.runHold=async()=>{const timer=page.waiting(entry=>String(entry.fn).includes("releaseCaptionHold"))[0];assert.ok(timer,"A caption check holds the notes");await page.run(timer);};
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
  h.run(6000,[{at:4100,fire:()=>h.user("We run the kite checks before the CPAC meets.",2000,4000)}]);
  const caption=h.captions.at(-1);assert.equal(caption.text,"We run the kite checks before the CPAC meets.");
  const audio=h.api.captionAudio(caption.id),file=readWav(audio.wav);
  assert.deepEqual([file.riff,file.wave,file.fmt,file.data],["RIFF","WAVE","fmt ","data"]);
  assert.deepEqual([file.fmtSize,file.format,file.channels,file.rate,file.byteRate,file.align,file.bits],[16,1,1,16000,32000,2,16],"16 kHz 16-bit mono PCM");
  assert.equal(file.dataSize,file.samples.length*2);assert.equal(file.size,36+file.dataSize);assert.equal(audio.wav.byteLength,44+file.dataSize);
  // 2.0 to 4.0 s on the session timeline, 400 ms before and 600 ms after: 3 seconds.
  assert.ok(Math.abs(file.samples.length-48000)<=8,`3 s of audio (${file.samples.length} samples)`);assert.equal(audio.duration_ms,3000);
  assert.equal(file.samples[0],sample(1600),"It starts 400 ms before the caption");
  assert.equal(file.samples[file.samples.length-20],sample(4600),"and ends 600 ms after it");
  assert.equal(file.samples[24000],sample(3100),"the middle is the middle");
  const values=new Set(file.samples);
  for(let end=1600;end<=4600;end+=BLOCK)assert.ok(values.has(sample(end)),"block ending at "+end+" is there");
  assert.ok(!values.has(sample(1500))&&!values.has(sample(4700)),"Nothing from outside the window");
  // No timestamps, a caption longer than 150 s, a window ahead of what was heard: no audio.
  h.run(9000,[{at:8000,fire:()=>h.event({type:"session.output_transcript.delta",event_id:"a1",delta:"Which checks?",start_ms:7000,end_ms:7800})},
   {at:8500,fire:()=>h.event({type:"session.input_transcript.delta",event_id:"u2",delta:"No timestamps here."})}]);
  assert.equal(h.captions.at(-1).text,"No timestamps here.");assert.ok(h.api.captionAudio(h.captions.at(-1).id)===null,"No timestamps, no audio");
  h.api.operation.userCaptions.get(caption.id).end_ms=2000+150001;
  assert.ok(h.api.captionAudio(caption.id)===null,"Over 150 seconds: the caption keeps its text");
  h.api.operation.userCaptions.get(caption.id).end_ms=4000;
  const dropped=h.tap().chunks.splice(0,25);
  assert.ok(h.api.captionAudio(caption.id)===null,"Its start is no longer in the buffer: audio is missing");
  h.tap().chunks.unshift(...dropped);
  h.tap().chunks.splice(28,3);
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
  assert.ok(file.samples.every(value=>value===0||value>=sample(7000)),"Only audio heard after unmuting");
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
   h.run(6000,[{at:4100,fire:()=>h.user("We run the kite checks.",2000,4000)}]);
   assert.ok(Math.abs(readWav(h.api.captionAudio(h.captions.at(-1).id).wav).samples.length-48000)<=8);
   await h.api.stop({immediate:true});
  }
  const h=await transport({worklet:false,script:false});
  assert.equal(h.tap(),null);assert.equal(h.gains[0]?.disconnected??true,true,"Nothing is left connected");
  assert.equal(JSON.stringify(h.traces.find(trace=>trace.type==="live.caption_tap").payload),JSON.stringify({state:"unavailable"}));
  h.run(6000,[{at:4100,fire:()=>h.user("We run the kite checks.",2000,4000)}]);
  assert.equal(h.api.captionAudio(h.captions.at(-1).id),null);assert.equal(h.api.connected,true,"Voice itself is unaffected");
  await h.api.stop({immediate:true});
 });

 // ---- the page ----
 await check("a final caption is transcribed again with the dictation hints and the better wording replaces it before the notes read it",async()=>{
  const h=await page(),page_=h.page;
  h.say("live_u1","We run the kite checks",false);
  assert.deepEqual(h.audio,[],"Nothing while the caption is still open");
  h.say("live_u1",CAPTION);
  assert.deepEqual(h.audio,["live_u1"],"The final caption's audio is asked for");
  assert.equal(h.transcribe.length,1,"One transcription request");
  const sent=h.transcribe[0];
  assert.equal(sent.init.headers["Content-Type"],"audio/wav");assert.equal(sent.body.type,"audio/wav");assert.equal(sent.body.size,44+64000);
  const hints=decodeURIComponent(sent.init.headers["X-Transcription-Hints"]).split(",");
  assert.ok(hints.includes("Capital calls")&&hints.includes("NAV")&&hints.includes("GP Fund Solutions"),"The hints dictation sends: "+hints);
  assert.ok(!hints.includes("CPAC"),"The caption's own terms (the mishearings) are not hints");
  // The notes capture waits for the check.
  await h.runCapture();
  assert.equal(h.captures.length,0,"The capture waits for the caption check");
  assert.equal(h.turn().text,CAPTION);
  await h.answer(sent,{text:CHECKED});
  assert.equal(h.turn().text,CHECKED,"The turn holds the better wording");
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
  await h.answer(h.transcribe[1],{text:CHECKED});
  assert.equal(h.turn().text,CHECKED);
  assert.deepEqual(h.outcomes(),["sent","discarded:caption_changed","sent","replaced"]);
  // A replaced caption that grows shows its own words until it is checked again.
  h.say("live_u1",CAPTION+" Then the LPAC signs.",false);
  assert.equal(h.turn().text,CAPTION+" Then the LPAC signs.");
  h.say("live_u1",CAPTION+" Then the LPAC signs.");
  assert.equal(h.transcribe.length,3);
  await h.answer(h.transcribe[2],{text:CHECKED+" Then the LPAC signs."});
  assert.equal(h.turn().text,CHECKED+" Then the LPAC signs.");
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
 await check("the plausibility guard keeps the caption when the result is not a reading of the same words",async()=>{
  const cases={
   "": "empty",
   "Thanks for watching.":"word_count",
   "Kite.":"word_count",
   "Please subscribe to the channel for more videos about payments and wires and things.":"different_words",
   "We run the KYC checks before the LPAC meets and the ACH wire goes out. I need to stop":"stop_phrase",
   [CAPTION]:"same",
   // The caption word for word with words from the padding around it corrects nothing, and a
   // replacement is never an append: a capture that read the caption always reads a changed answer.
   [CAPTION+" Okay."]:"no_correction",["Mm. "+CAPTION]:"no_correction"};
  for(const [result,reason] of Object.entries(cases)){
   const h=await page();
   h.say("live_u1",CAPTION);
   await h.answer(h.transcribe[0],{text:result});
   assert.equal(h.turn().text,CAPTION,JSON.stringify(result)+" is not used");
   assert.deepEqual(h.outcomes(),["sent","kept:"+reason]);
  }
  // A shorter or longer reading of the same words is used, within the bounds.
  const h=await page();
  h.say("live_u1","Then the K one goes out.");
  await h.answer(h.transcribe[0],{text:"Then the K-1 goes out."});
  assert.equal(h.turn().text,"Then the K-1 goes out.");
 });
 await check("a check that takes too long holds the notes six seconds; its later result is a correction applied once",async()=>{
  const h=await page();
  h.say("live_u1",CAPTION);
  await h.runCapture();assert.equal(h.captures.length,0,"Held");
  await h.runHold();
  await h.runCapture();
  assert.equal(h.captures.length,1,"After six seconds the capture reads the caption as it is");
  assert.equal(h.lastAnswer(h.captures[0]),CAPTION);
  await h.answer(h.transcribe[0],{text:CHECKED});
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
  h.say("live_u3","The each team and the GP attend.");
  assert.equal(h.transcribe.length,2,"Two on their way");
  assert.deepEqual(h.audio,["live_u1","live_u2","live_u3"],"The third caption's audio is taken now, while it is held");
  await h.answer(h.transcribe[0],{text:"We run the KYC checks before it goes."});
  assert.equal(h.transcribe.length,3,"The third goes when one finishes");
  await h.answer(h.transcribe[1],{text:"The LPAC meets on Tuesday morning."});
  await h.answer(h.transcribe[2],{text:"The ACH team and the GP attend."});
  assert.deepEqual(h.page.state.turns.filter(turn=>turn.role==="user").slice(1).map(turn=>turn.text),
   ["We run the KYC checks before it goes.","The LPAC meets on Tuesday morning.","The ACH team and the GP attend."]);
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
  await late.answer(late.transcribe[0],{text:CHECKED});
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
  await h.answer(h.transcribe[0],{text:CHECKED});
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
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
