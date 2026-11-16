"use strict";
// The participant speech gate of Live voice: a caption fragment is withheld only on
// positive evidence of silence, and never silently. Real web/live-voice.js and
// web/app.js with the fakes of the existing suites; no microphone, browser, network
// or provider. The microphone here is a level over time, so a meter reading sees
// what happened since the previous reading, as a real analyser's buffer does.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const shared={require,__dirname,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException,setImmediate,setTimeout,clearTimeout};
const exported=(source,tail)=>{const module={exports:{}};vm.runInNewContext(source+tail,{...shared,module});return module.exports;};
const voice=exported(fs.readFileSync(path.join(__dirname,"test_live_voice.cjs"),"utf8").split("(async()=>{")[0],"\nmodule.exports={setup};");
const tick=()=>new Promise(resolve=>setImmediate(resolve));
let events=0;
async function live(){
 const h=voice.setup({metering:true});h.withheld=[];
 await h.api.start({turns:[{id:"t001",role:"assistant",text:"What starts the work?"}]});
 h.api.options.onWithheld=entry=>h.withheld.push(entry);
 // 48 kHz microphone whose past levels stay readable for as long as an analyser keeps them.
 const mic=h.streams[0],changes=[{at:-Infinity,level:0}];h.now=()=>h.window.performance.now();
 Object.defineProperty(mic,"level",{configurable:true,get:()=>changes.at(-1).level,set:level=>{changes.push({at:h.now(),level});}});
 const fill=(buffer,write)=>{
  let index=buffer.length;
  for(let c=changes.length-1;c>=0&&index>0;c--){
   const from=Math.max(0,buffer.length-Math.round((h.now()-changes[c].at)*48));
   for(let i=from;i<index;i++)buffer[i]=write(i,changes[c].level);
   index=Math.min(index,from);
  }
 };
 for(const analyser of h.analysers)if(analyser.stream===mic){
  analyser.getFloatTimeDomainData=buffer=>fill(buffer,(i,level)=>(i%2?1:-1)*level);
  analyser.getByteTimeDomainData=buffer=>fill(buffer,(i,level)=>128+Math.round((i%2?1:-1)*level*128));
 }
 h.mic=level=>{mic.level=level;};
 h.run=(ms,each=16)=>{for(let done=0;done<ms;done+=each)h.step(each);};
 h.user=(delta,start_ms,end_ms)=>h.event({type:"session.input_transcript.delta",event_id:"event_"+(++events),delta,start_ms,end_ms});
 h.interviewer=(delta,start_ms,end_ms)=>h.event({type:"session.output_transcript.delta",event_id:"event_"+(++events),delta,start_ms,end_ms});
 h.heard=()=>[...new Map(h.captions.filter(caption=>caption.role==="user").map(caption=>[caption.id,caption.text])).values()];
 h.hide=()=>{h.document.hidden=true;h.document.emit("visibilitychange");};
 h.remote(0);await tick();h.step(40);
 return h;
}
let source=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(source.includes("setTeam:value=>"),"The application test seam is available");
source=source.replace("setTeam:value=>",()=>"withheldSpeech:()=>liveWithheld,clearState,setTeam:value=>");
let passed=0;const failed=[];
async function check(name,fn){
 try{await fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.message||error).split("\n").slice(0,12).join("\n     "));}
}
(async()=>{
 await check("quiet speech between 0.004 and 0.008 RMS is captioned",async()=>{
  for(const level of [.004,.006,.0079]){
   const h=await live();
   h.mic(level);h.run(1920); // about two seconds of steady quiet speech
   h.user("An email from the supplier starts it.",140,1840);
   h.interviewer("Thanks. What happens next?",2140,3040);
   assert.deepEqual(h.heard(),["An email from the supplier starts it."],"A microphone at "+level+" RMS still carries the answer");
   assert.equal(h.withheld.length,0);assert.equal(h.captions.at(-1).text,"Thanks. What happens next?");
   await h.api.stop({immediate:true});
  }
 });
 await check("a fragment over measured silence is withheld, kept and reported, never discarded",async()=>{
  const h=await live();
  h.run(2400); // the meter covers the whole time and the microphone is silent
  h.user("a young woman",1000,1400);
  assert.deepEqual(h.heard(),[],"An invented fragment is still not a participant caption");
  assert.equal(h.withheld.length,1,"The withheld words are handed to the application");
  assert.equal(h.withheld[0].text,"a young woman");assert.equal(h.withheld[0].start_ms,1000);assert.equal(h.withheld[0].fragments,1);
  h.user(" is standing",1400,1900);
  assert.equal(h.withheld.at(-1).id,h.withheld[0].id,"Fragments of one moment are one withheld entry");
  assert.equal(h.withheld.at(-1).text,"a young woman is standing");assert.equal(h.withheld.at(-1).fragments,2);
  h.run(9600);h.user("a close-up",9000,9400);
  assert.notEqual(h.withheld.at(-1).id,h.withheld[0].id,"A later moment is a separate entry");assert.equal(h.withheld.at(-1).text,"a close-up");
  h.interviewer("What starts the work?",9500,10400);
  assert.equal(h.captions.at(-1).role,"assistant","Interviewer captions are never gated");assert.deepEqual(h.heard(),[]);assert.deepEqual(Array.from(h.errors),[]);
  await h.api.stop({immediate:true});
 });
 await check("a fragment over a muted microphone is withheld and marked as muted",async()=>{
  const h=await live();
  h.mic(.05);h.run(480);
  h.user("An email starts it.",100,500);
  assert.equal(h.api.setMuted(true),true);h.run(4800); // the room stays loud, but nothing is sent while muted
  h.user("thank you for watching",3000,3600);
  assert.deepEqual(h.heard(),["An email starts it."]);
  assert.equal(h.withheld.length,1);assert.equal(h.withheld[0].text,"thank you for watching");assert.equal(h.withheld[0].muted,true);
  assert.equal(h.api.setMuted(false),true);h.run(960);
  h.user("And then we approve it.",5500,6200);
  assert.deepEqual(h.heard(),["An email starts it. And then we approve it."],"Speech after unmuting is captioned again");
  await h.api.stop({immediate:true});
 });
 await check("a short answer in a hidden tab is captioned although it fell between two meter readings",async()=>{
  const h=await live();h.hide();
  h.step(250);h.step(250);
  h.step(20);const began=h.now();
  h.mic(.08);h.step(200);h.mic(0);h.step(30); // a 200 ms "Yes." between two readings 250 ms apart
  for(let i=0;i<12;i++)h.step(250);
  h.user("Yes.",began,began+200);
  assert.deepEqual(h.heard(),["Yes."]);assert.equal(h.withheld.length,0);
  await h.api.stop({immediate:true});
 });
 await check("in a hidden tab a long answer is captioned and measured silence is still withheld",async()=>{
  const h=await live();h.hide();
  h.step(250);h.step(250);const began=h.now();
  h.mic(.05);for(let i=0;i<12;i++)h.step(250); // three seconds of speech
  h.mic(0);for(let i=0;i<2;i++)h.step(250);
  h.user("We reconcile the account every month and send the report to treasury.",began+100,began+2900);
  assert.deepEqual(h.heard(),["We reconcile the account every month and send the report to treasury."]);
  for(let i=0;i<24;i++)h.step(250); // six more seconds, silent and fully measured
  h.user(" a person is",began+6500,began+7000);
  assert.deepEqual(h.heard(),["We reconcile the account every month and send the report to treasury."],"A hidden tab is not a reason to keep invented fragments");
  assert.equal(h.withheld.length,1);assert.equal(h.withheld[0].text,"a person is");
  await h.api.stop({immediate:true});
 });
 await check("when a throttled hidden tab leaves the moment unmeasured, the fragment is kept",async()=>{
  const h=await live();h.hide();
  h.step(250);
  h.step(10);const began=h.now();
  h.mic(.08);h.step(200);h.mic(0);
  h.step(790); // the browser ran the sampler a second late: its buffer no longer reaches back to the answer
  h.step(1000);h.step(1000);
  h.user("No.",began,began+200);
  assert.deepEqual(h.heard(),["No."],"No measurement of the moment is not evidence of silence");assert.equal(h.withheld.length,0);
  await h.api.stop({immediate:true});
 });
 await check("the gate follows the room's noise floor instead of one fixed level",async()=>{
  const h=await live();
  h.mic(.006);h.run(20000); // twenty seconds of steady room noise
  h.user("a person is",15000,15500);
  assert.deepEqual(h.heard(),[],"Steady noise is not speech");assert.equal(h.withheld.length,1);
  h.mic(.05);h.run(1000);h.mic(.006);h.run(320);
  h.user("The analyst logs it.",20100,20900);
  assert.deepEqual(h.heard(),["The analyst logs it."],"Speech above the noise is captioned");assert.equal(h.withheld.length,1);
  await h.api.stop({immediate:true});
 });
 await check("a level below the earlier hard threshold still preserves a measured change in a quiet room",async()=>{
  for(const amplitude of [.006,.0079]){
   const h=await live();h.mic(0);h.run(2000);h.mic(amplitude);h.run(600);h.mic(0);h.run(320);
   h.user("I recorded the waiver.",2100,2500);assert.deepEqual(h.heard(),["I recorded the waiver."]);
   await h.api.stop({immediate:true});
  }
 });
 await check("speech in a noisy room, and a long steady voice, are never measured as silence",async()=>{
  // Steady room noise at 0.03 RMS (a fan, traffic) for 20 s, then an answer whose syllables reach 0.05 over it.
  const h=await live();
  h.mic(.03);h.run(20000);
  for(let t=0;t<2000;t+=160){h.mic(.05);h.run(96);h.mic(.03);h.run(64);}
  h.user("We reconcile the account every month.",20100,21900);
  assert.deepEqual(h.heard(),["We reconcile the account every month."],"The noise floor only makes the gate more sensitive, never deaf");
  assert.equal(h.withheld.length,0);
  await h.api.stop({immediate:true});
  // A quiet room and one loud, steady voice for 12 s: the floor has risen to the voice by the end.
  const k=await live();
  k.run(1000);k.mic(.05);k.run(12000);
  k.user("And then it goes on and on for a long while.",9000,11800);
  assert.deepEqual(k.heard(),["And then it goes on and on for a long while."]);assert.equal(k.withheld.length,0);
  // Silence afterwards is still silence.
  k.mic(0);k.run(6000);k.user("a young woman",16000,16500);
  assert.equal(k.heard().length,1);assert.equal(k.withheld.length,1);
  await k.api.stop({immediate:true});
 });
 await check("the application keeps withheld speech and tells the participant",async()=>{
  const app=exported(source,"\nmodule.exports={setup};"),h=app.setup();let callbacks=null;
  h.window.CollectorLiveVoice=class{constructor(options){callbacks=options;this.active=false;}async start(){this.active=true;return true;}async stop(){this.active=false;return{finalized:true};}
   appendContext(){return Promise.resolve({status:"acknowledged"});}say(){return Promise.resolve({status:"acknowledged"});}};
  h.t.state.config.agent_team.voice_mode="live_front";h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
  await h.t.startLiveConversation();
  assert.equal(typeof callbacks.onWithheld,"function","The application listens for withheld speech");
  const said=()=>Array.from(h.notices).map(item=>item.message).filter(message=>/may not have been captioned/.test(message));
  callbacks.onWithheld({id:"m1",text:"thank you for watching this video",start_ms:200,end_ms:900,fragments:1,muted:true});
  assert.equal(said().length,0,"Nothing the participant said is missed while they have muted the microphone");
  callbacks.onWithheld({id:"w1",text:"Yes.",start_ms:1000,end_ms:1200,fragments:1});
  callbacks.onWithheld({id:"w2",text:"No.",start_ms:9000,end_ms:9200,fragments:2});
  assert.equal(said().length,0,"One or two stray words are kept without interrupting the conversation");
  callbacks.onWithheld({id:"w3",text:"Friday.",start_ms:15000,end_ms:15300,fragments:3});
  assert.equal(said().length,1,"Repeated withholding is announced");assert.match(said()[0],/microphone/i);assert.match(said()[0],/Friday\./,"The notice shows the words so they can be said or typed again");
  callbacks.onWithheld({id:"w4",text:"The treasury team signs",start_ms:20000,end_ms:21000,fragments:4});
  assert.equal(said().length,2,"Several words in one moment are announced at once");assert.match(said()[1],/The treasury team signs/);
  callbacks.onWithheld({id:"w4",text:"The treasury team signs off first.",start_ms:20000,end_ms:22000,fragments:5});
  assert.equal(said().length,2,"One announcement per moment");
  // Over a long quiet session the transcriber's short inventions keep coming: they are not announced again.
  for(let i=5;i<12;i++)callbacks.onWithheld({id:"w"+i,text:"a young woman",start_ms:i*9000,end_ms:i*9000+400,fragments:i+1});
  assert.equal(said().length,2,"Repeated short moments are announced once per live session");
  assert.ok(Array.from(h.notices).filter(item=>/may not have been captioned/.test(item.message)).every(item=>!item.error),"Shown as information, not as an error");
  const kept=Array.from(h.t.withheldSpeech());
  assert.deepEqual(kept.map(item=>item.text).slice(0,5),["thank you for watching this video","Yes.","No.","Friday.","The treasury team signs off first."],"Nothing withheld is discarded");
  assert.equal(kept.length,12);assert.ok(kept.every(item=>item.withheld===true),"Kept apart from the transcript and flagged");
  assert.equal(h.t.state.turns.length,1,"Withheld speech never becomes a transcript turn by itself");
  // Every withheld moment can be read back, including a single short answer that was never announced.
  const listed=()=>Array.from(h.node("withheld-list").children).map(item=>item.textContent);
  assert.equal(h.node("withheld-speech").hidden,false,"The list the notice points to is shown");
  const page=fs.readFileSync(path.join(__dirname,"..","web","index.html"),"utf8");
  for(const id of ["withheld-speech","withheld-list","withheld-count"])assert.ok(page.includes(`id="${id}"`),"The page has #"+id);
  assert.match(page,/<details id="withheld-speech"[^>]* hidden>/,"Nothing is shown until something was withheld");
  assert.deepEqual(listed().slice(0,4),["Yes.","No.","Friday.","The treasury team signs off first."]);
  assert.ok(!listed().includes("thank you for watching this video"),"Words heard while the participant had muted the microphone are not listed");
  assert.equal(h.node("withheld-count").textContent,"11");assert.match(said()[0],/Speech not captioned/,"The notice says where the words are listed");
  // Continue talking: the list is kept for the interview, and the new session announces repetition once more.
  await h.t.conversationUI.live.stop();await h.t.startLiveConversation();
  assert.equal(listed().length,11,"Earlier withheld moments are still readable after Continue talking");
  callbacks.onWithheld({id:"w1",text:"Maybe.",start_ms:500,end_ms:700,fragments:1}); // a new session numbers its moments again
  assert.equal(listed().length,12);assert.equal(listed().at(-1),"Maybe.");
  h.t.clearState(null);
  assert.equal(h.node("withheld-speech").hidden,true,"A new interview starts with an empty list");assert.equal(Array.from(h.t.withheldSpeech()).length,0);
 });
 console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0,physical_audio:false}));
 if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
