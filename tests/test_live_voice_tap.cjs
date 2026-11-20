"use strict";
// The caption check's microphone tap, web/live-voice-tap.js, run as it is: the real processor class in
// an audio-worklet-like global scope (AudioWorkletProcessor, registerProcessor, sampleRate and
// currentTime), fed 128-frame render quanta the way the audio thread feeds it, with a port whose
// postMessage really transfers the buffers it is given (structuredClone with transfer), as a
// MessagePort does. In a real browser session (2026-11-20) the tap posted one block and never another:
// the next block was sized from the block just transferred, which is empty once it is handed over, so
// every caption's audio was missing. The unit tests of the page faked the worklet and could not see it.
// No browser, microphone, network or provider.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const SOURCE=fs.readFileSync(path.join(__dirname,"..","web","live-voice-tap.js"),"utf8");
const QUANTUM=128;
let passed=0;const failed=[];
function check(name,fn){
 try{fn();passed++;console.log("PASS "+name);}
 catch(error){failed.push(name);console.log("FAIL "+name+"\n     "+String(error&&error.stack||error).split("\n").slice(0,8).join("\n     "));}
}
// The audio-worklet global scope at one sample rate, and the processor registered in it.
function worklet(rate){
 const posted=[],detached=[];
 const port={onmessage:null,postMessage(message,transfer=[]){
  const copy=structuredClone(message,{transfer});
  // The sender's view is empty once its buffer is transferred, as in a browser.
  detached.push(message.samples.length===0&&message.samples.buffer.byteLength===0);
  posted.push(copy);
 }};
 const scope={sampleRate:rate,currentTime:0,registered:null,console};
 scope.AudioWorkletProcessor=class{constructor(){this.port=port;}};
 scope.registerProcessor=(name,processor)=>{scope.registered={name,processor};};
 vm.createContext(scope);
 vm.runInContext(SOURCE,scope,{filename:"live-voice-tap.js"});
 assert.equal(scope.registered?.name,"live-voice-tap");
 const node=new scope.registered.processor();
 let frame=0;
 // One render quantum: currentTime is the time of its first frame; each sample carries its frame number.
 const render=(connected=true)=>{
  scope.currentTime=frame/rate;
  const channel=new Float32Array(QUANTUM);for(let i=0;i<QUANTUM;i++)channel[i]=(frame+i)%1000003;
  const alive=node.process(connected?[[channel]]:[[]],[[new Float32Array(QUANTUM)]],{});
  frame+=QUANTUM;
  return alive;
 };
 return {node,posted,detached,render,frame:()=>frame,size:Math.max(128,Math.round(rate/10))};
}

for(const rate of [48000,44100,16000]){
 check(`at ${rate} Hz the tap keeps posting blocks of 100 ms for as long as it runs`,()=>{
  const w=worklet(rate),seconds=6,quanta=Math.ceil(seconds*rate/QUANTUM);
  for(let index=0;index<quanta;index++)assert.equal(w.render(),true,"The processor stays alive");
  const expected=Math.floor(w.frame()/w.size);
  assert.ok(expected>=seconds*10-1);
  assert.equal(w.posted.length,expected,`${expected} blocks over ${seconds} s (${w.posted.length} posted)`);
  assert.ok(w.detached.every(Boolean),"Each block's buffer was really transferred");
  for(const [index,message] of w.posted.entries()){
   assert.equal(message.samples.length,w.size,`block ${index} holds ${w.size} samples`);
   // Contiguous: block k holds frames k*size to (k+1)*size-1, and its end is the clock after its last frame.
   assert.equal(message.samples[0],index*w.size%1000003,`block ${index} starts where the last ended`);
   assert.equal(message.samples[w.size-1],((index+1)*w.size-1)%1000003);
   assert.ok(Math.abs(message.end-(index+1)*w.size/rate)<1e-9,`block ${index} ends at ${(index+1)*w.size/rate} s (${message.end})`);
  }
 });
}
check("a gap in the input drops the partial block and the blocks after it are whole",()=>{
 const w=worklet(48000);
 for(let index=0;index<60;index++)w.render();               // 7680 frames: one block posted, 2880 frames waiting
 assert.equal(w.posted.length,1);
 assert.equal(w.render(false),true,"Nothing connected for one quantum");
 const resumed=w.frame();
 for(let index=0;index<400;index++)w.render();               // 51200 frames: ten more blocks
 assert.equal(w.posted.length,1+Math.floor((w.frame()-resumed)/w.size));
 for(const message of w.posted.slice(1))assert.equal(message.samples.length,4800);
 assert.equal(w.posted[1].samples[0],resumed,"The first block after the gap starts after it, joined to nothing before it");
 assert.ok(Math.abs(w.posted[1].end-(resumed+4800)/48000)<1e-9);
});

console.log(JSON.stringify({checks_passed:passed,checks_failed:failed.length,provider_calls:0,network_calls:0}));
if(failed.length)process.exitCode=1;
