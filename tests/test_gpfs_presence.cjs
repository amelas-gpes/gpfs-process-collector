"use strict";
// Vector choreography boundary tests. Synthetic levels and virtual time; no real microphone or playback.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict"),crypto=require("node:crypto");
const source=fs.readFileSync(path.join(__dirname,"..","web","gpfs-presence.js"),"utf8");
class Element{
  constructor(tag,doc){this.tagName=tag;this.ownerDocument=doc;this.children=[];this.attributes={};this.classList={add:()=>{}};}
  setAttribute(k,v){this.attributes[k]=String(v);}
  getAttribute(k){return this.attributes[k]??null;}
  appendChild(n){this.children.push(n);return n;}
  replaceChildren(...nodes){this.children=nodes;}
}
function setup({reduced=false,autoStart=false}={}){
  const callbacks=new Map(),listeners=new Map(),motionListeners=new Set();let nextId=0,clock=0;
  const media={matches:reduced,addEventListener:(_,fn)=>motionListeners.add(fn),removeEventListener:(_,fn)=>motionListeners.delete(fn)};
  const document={hidden:false,createElementNS:(_,tag)=>new Element(tag,document),addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:(name,fn)=>{if(listeners.get(name)===fn)listeners.delete(name);}};
  const window={document,performance:{now:()=>clock},matchMedia:()=>media,requestAnimationFrame:fn=>{const id=++nextId;callbacks.set(id,fn);return id;},cancelAnimationFrame:id=>callbacks.delete(id)};document.defaultView=window;
  vm.runInNewContext(source,{window});
  const root=new Element("div",document),api=window.GPFSPresence.create(root,{autoStart});
  return{api,root,window,document,callbacks,listeners,motionListeners,
    sample(time){clock=time;return api.sample(time);},
    frames(count=30,start=0,step=1000/30){let result;for(let i=0;i<count;i++)result=this.sample(start+i*step);return result;},
    raf(time){clock=time;const tasks=[...callbacks.values()];callbacks.clear();tasks.forEach(fn=>fn(time));},
    visibility(hidden){document.hidden=hidden;listeners.get("visibilitychange")();},
    motion(matches){media.matches=matches;motionListeners.forEach(fn=>fn({matches}));}
  };
}
const audio=(overrides={})=>({input:0,output:0,inputActive:false,outputActive:false,playbackActive:false,muted:false,connected:true,...overrides});
const near=(actual,expected,epsilon=.01)=>assert.ok(Math.abs(actual-expected)<epsilon,`${actual} not near ${expected}`);
const walk=node=>[node,...node.children.flatMap(walk)];
const tests=[];function test(name,fn){tests.push([name,fn]);}

test("official lockup asset is byte-faithful and includes the verified source palette",()=>{
  const asset=fs.readFileSync(path.join(__dirname,"..","web","assets","gpfs-logo.svg"));
  assert.equal(crypto.createHash("sha256").update(asset).digest("hex"),"f7a6179bbe98c6477ff443a646e1253273305460231e888b1f83ef114425002b");
  assert.match(asset.toString(),/viewBox="0 0 129.92136 45.69322"/);assert.match(asset.toString(),/#c9753a/);assert.match(asset.toString(),/#8b7d65/);
});
test("mounts source paths synchronously with five articulating parts and stable supplied lettering",()=>{
  const h=setup(),svg=h.root.children[0],word=h.root.children[1];assert.equal(svg.getAttribute("class"),"gpfs-symbol");assert.equal(word.children.length,17);
  const parts=svg.children.filter(n=>n.getAttribute("data-gpfs-part")!==null);assert.equal(parts.length,5);
  const official=fs.readFileSync(path.join(__dirname,"..","web","assets","gpfs-logo.svg"),"utf8"),paths=[...official.matchAll(/<path[^>]* d="([^"]+)"/g)].map(m=>m[1]);
  parts.forEach((part,i)=>assert.equal(part.children[0].getAttribute("d"),paths.slice(-5)[i]));
  assert.equal(parts[0].children[0].getAttribute("transform"),"translate(-12.09812 16.40127) rotate(-45.00283)");
  assert.equal(walk(svg).some(node=>node.tagName==="filter"),false);assert.equal(h.callbacks.size,0);h.api.dispose();
});
test("silence and background noise do not create microphone motion",()=>{
  const h=setup();h.api.setState("listening");h.api.setAudio(audio({input:.012}));const rest=h.frames(80);
  assert.equal(rest.input,0);near(rest.gather,.22);near(rest.project,0);assert.ok(rest.parts[0].x>0);assert.ok(rest.parts[2].x<0);h.api.dispose();
});
test("quiet microphone speech gathers inward with a controlled attack and long release",()=>{
  const h=setup();h.api.setState("listening");h.frames(40);h.api.setAudio(audio({input:.08,inputActive:true}));
  const first=h.sample(1400),spoken=h.frames(20,1434);assert.ok(first.input>0&&first.input<spoken.input);assert.ok(spoken.input>.08);assert.ok(spoken.gather>.32);assert.ok(spoken.parts[0].x>first.parts[0].x);
  h.api.setAudio(audio());const release=h.sample(2134);assert.ok(release.input>0&&release.input<spoken.input);const settled=h.frames(70,2167);near(settled.gather,.22);near(settled.input,0);h.api.dispose();
});
test("actual output projects outward and travels in the opposite illumination direction",()=>{
  const h=setup();h.api.setState("listening");h.api.setAudio(audio({input:.7,inputActive:true}));const listening=h.frames(40);
  h.api.setState("speaking");h.api.setAudio(audio({output:.7,outputActive:true,playbackActive:true}));const speaking=h.frames(40,1400);
  assert.equal(speaking.mode,"speaking");assert.ok(speaking.project>.8);assert.ok(speaking.parts[0].x<0&&speaking.parts[2].x>0);assert.ok(speaking.tilt>0&&listening.tilt<0);assert.ok(speaking.band>listening.band);h.api.dispose();
});
test("speaking metadata waits for actual playback before projecting",()=>{
  const h=setup();h.api.setState("speaking");h.api.setAudio(audio({playbackActive:true}));let p=h.frames(30);assert.equal(p.mode,"listening");near(p.project,0);
  h.api.setAudio(audio({output:.2,outputActive:true,playbackActive:true}));p=h.frames(30,1100);assert.equal(p.mode,"speaking");assert.ok(p.project>.3);h.api.dispose();
});
test("trusted auxiliary audio playback can project without inventing an output level",()=>{
  const h=setup();h.api.setState("speaking");const speaking=h.frames(50);assert.equal(speaking.mode,"speaking");near(speaking.project,.22);assert.equal(speaking.output,0);h.api.setState("idle");const stopped=h.frames(70,1800);near(stopped.project,0);h.api.dispose();
});
test("phrase pauses relax while speaking and playback completion returns to listening",()=>{
  const h=setup();h.api.setState("speaking");h.api.setAudio(audio({output:.8,outputActive:true,playbackActive:true}));const full=h.frames(40);
  h.api.setAudio(audio({playbackActive:true}));const pause=h.frames(40,1400);assert.equal(pause.mode,"speaking");assert.ok(pause.project<full.project);near(pause.project,.22,.025);
  h.api.setAudio(audio());const ended=h.frames(60,2800);assert.equal(ended.mode,"listening");near(ended.project,0);near(ended.gather,.22);h.api.dispose();
});
test("a microphone interruption continuously leaves projection and becomes receptive",()=>{
  const h=setup();h.api.setState("speaking");h.api.setAudio(audio({output:.8,outputActive:true,playbackActive:true}));const before=h.frames(40);
  h.api.setAudio(audio({input:.65,inputActive:true,output:.4,outputActive:true,playbackActive:true}));const first=h.sample(1334),after=h.frames(35,1367);
  assert.equal(first.mode,"listening");assert.ok(first.parts[0].x<0,"Direction changes through the existing posture, without a jump");assert.ok(Math.abs(first.parts[0].x-before.parts[0].x)<.5);assert.ok(after.parts[0].x>0&&after.input>.5);h.api.dispose();
});
test("muted microphone is quiet while real AI playback remains expressive",()=>{
  const h=setup();h.api.setState("muted");h.api.setAudio(audio({muted:true,input:.9,inputActive:true}));const muted=h.frames(70);assert.equal(muted.mode,"muted");assert.equal(muted.input,0);near(muted.gather,0);
  h.api.setAudio(audio({muted:true,output:.6,outputActive:true,playbackActive:true}));const speaking=h.frames(30,2400);assert.equal(speaking.mode,"speaking");assert.ok(speaking.project>.6);h.api.dispose();
});
test("idle and ended states ignore stale audio and settle to the exact resting pose",()=>{
  const h=setup();h.api.setAudio(audio({input:.8,output:.8,inputActive:true,outputActive:true}));let p=h.frames(50);assert.equal(p.mode,"idle");near(p.input,0);near(p.project,0);
  h.api.setState("speaking");h.api.setAudio(audio({output:.8,outputActive:true,playbackActive:true}));h.frames(30,1800);h.api.setState("ended");h.api.setAudio(audio({output:.8,outputActive:true}));p=h.frames(100,2900);assert.equal(p.mode,"ended");near(p.project,0);near(p.tilt,0);h.api.dispose();
});
test("connecting and processing have distinct restrained activity only in actual waiting states",()=>{
  const h=setup();h.api.setState("connecting");const a=h.frames(20);const b=h.frames(20,700);assert.equal(a.mode,"connecting");assert.ok(Math.abs(a.gather-b.gather)>.002);assert.ok(a.gather<.2&&b.gather<.2);near(a.project,0);
  h.api.setState("processing");const c=h.frames(50,1500);assert.equal(c.mode,"processing");assert.ok(c.project<.15);near(c.input,0);near(c.output,0);h.api.dispose();
});
test("reduced motion retains distinct static illumination without articulation or RAF",()=>{
  const h=setup({reduced:true,autoStart:true});h.api.setState("listening");h.api.setAudio(audio({input:.8,inputActive:true}));const listening=h.api.inspect();
  h.api.setState("speaking");h.api.setAudio(audio({output:.8,outputActive:true,playbackActive:true}));const speaking=h.sample(1000);
  assert.equal(h.callbacks.size,0);assert.equal(speaking.mode,"speaking");assert.ok(speaking.light>listening.light);for(const p of speaking.parts){assert.equal(p.x,0);assert.equal(p.y,0);assert.equal(p.rotation,0);}h.api.dispose();
});
test("runtime reduced-motion preference cancels rendering and restores a quiet pose",()=>{
  const h=setup({autoStart:true});h.api.setState("speaking");h.api.setAudio(audio({output:.7,outputActive:true,playbackActive:true}));h.raf(0);h.raf(40);assert.ok(h.callbacks.size>0);h.motion(true);assert.equal(h.callbacks.size,0);assert.equal(h.api.inspect().reducedMotion,true);assert.ok(h.api.inspect().parts.every(p=>p.rotation===0));h.motion(false);assert.ok(h.callbacks.size>0);h.api.dispose();
});
test("hidden panel and hidden document pause rendering; resume does not replay elapsed time",()=>{
  const h=setup({autoStart:true});h.api.setState("listening");h.api.setAudio(audio({input:.7,inputActive:true}));h.raf(0);const before=h.api.inspect();h.api.setVisible(false);assert.equal(h.callbacks.size,0);h.api.setAudio(audio({input:.9,inputActive:true}));h.sample(100000);assert.equal(h.api.inspect().renderCount,before.renderCount);
  h.api.setVisible(true);h.raf(100100);const resumed=h.api.inspect();assert.ok(resumed.input<.7,"Resume uses one short frame rather than the hidden interval");h.visibility(true);assert.equal(h.callbacks.size,0);h.visibility(false);assert.ok(h.callbacks.size>0);h.api.dispose();
});
test("rendering caps at 30fps while audio remains independently sampled",()=>{
  const h=setup({autoStart:true});h.api.setState("listening");h.api.setAudio(audio({input:.7,inputActive:true}));const start=h.api.inspect().renderCount;for(let t=0;t<=1000;t+=1000/120)h.raf(t);const rendered=h.api.inspect().renderCount-start;assert.ok(rendered>=28&&rendered<=31,`${rendered} frames`);h.api.dispose();
});
test("settled idle and below-floor audio do not keep a RAF loop alive",()=>{
  const h=setup({autoStart:true});h.api.setState("listening");for(let t=0;t<3000;t+=34)h.raf(t);assert.equal(h.callbacks.size,0);const rendered=h.api.inspect().renderCount;h.api.setAudio(audio({input:.01}));assert.equal(h.callbacks.size,0);assert.equal(h.api.inspect().renderCount,rendered);h.api.dispose();
});
test("inspect is read-only and deterministic sampling does not schedule RAF",()=>{
  const h=setup();h.api.setState("listening");h.api.setAudio(audio({input:.5,inputActive:true}));const p=h.frames(12),before=h.api.inspect();h.api.inspect();assert.deepEqual(h.api.inspect(),before);h.sample(0);const after=h.api.inspect();near(after.input,p.input);assert.equal(h.callbacks.size,0);h.api.dispose();
});
test("multiple instances have independent light IDs and disposal removes owned listeners",()=>{
  const h=setup({autoStart:true}),otherRoot=new Element("div",h.document),other=h.window.GPFSPresence.create(otherRoot,{autoStart:false});
  const id1=h.root.children[0].children[0].children[0].getAttribute("id"),id2=otherRoot.children[0].children[0].children[0].getAttribute("id");assert.notEqual(id1,id2);
  h.api.setState("connecting");assert.ok(h.callbacks.size>0);h.api.dispose();assert.equal(h.callbacks.size,0);const before=h.api.inspect();h.api.setAudio(audio({output:.9,outputActive:true}));h.api.setState("speaking");h.api.sample(5000);assert.deepEqual(h.api.inspect(),before);other.dispose();assert.equal(h.motionListeners.size,0);
});
let passed=0;for(const[name,fn]of tests){try{fn();passed++;process.stdout.write(`PASS ${name}\n`);}catch(error){process.stderr.write(`FAIL ${name}\n${error.stack}\n`);process.exitCode=1;}}
process.stdout.write(`GPFS presence: ${passed}/${tests.length} passed; ${tests.length-passed} failed; 0 skipped. Synthetic audio only.\n`);
