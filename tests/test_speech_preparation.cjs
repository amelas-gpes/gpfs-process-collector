"use strict";
// Synthetic socket events; no network, tokens or microphone access.
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const window={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../web/controlled-voice.js"),"utf8"),{window,Promise,JSON,Error,Set,encodeURIComponent});
const Preparation=window.CollectorSpeechPreparation;
const session={provider:"openai",transport:"openai-realtime-websocket",model:"fake",client_secret:"fake"};
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
function setup(get=async()=>session){
 let socket,timer,cleared=0;
 class Socket{
  constructor(){socket=this;this.events={};this.readyState=0;this.sent=[];this.closed=0;}
  addEventListener(k,f){(this.events[k]??=new Set()).add(f);}
  removeEventListener(k,f){this.events[k]?.delete(f);}
  emit(k,data){for(const f of [...(this.events[k]||[])])f({data:JSON.stringify(data)});}
  send(value){this.sent.push(value);}
  close(){this.closed++;this.readyState=3;this.emit("close");}
 }
 const controller=new AbortController();
 const prep=new Preparation(get,"marin",{signal:controller.signal,WebSocket:Socket,setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>cleared++});
 return {prep,controller,socket:()=>socket,expire:()=>timer(),cleared:()=>cleared};
}
(async()=>{
 let checks=0;
 {
  // Native browser timer functions require their Window receiver.
  let cleared=false;window.setTimeout=function(){assert.equal(this,window);return 1;};
  window.clearTimeout=function(){assert.equal(this,window);cleared=true;};
  const p=new Preparation(async()=>{throw Error("No session");},"marin");await p.ready;
  assert.equal(cleared,true);checks++;
 }
 {
  const h=setup();await flush();const s=h.socket();assert.equal(s.sent.length,0);s.readyState=1;s.emit("message",{type:"session.created"});
  const result=await h.prep.take("marin");assert.equal(result.socket,s);assert.equal(s.sent.length,0);assert.equal(h.cleared(),1);
  assert.equal(await h.prep.take("marin"),null);h.prep.dispose();assert.equal(s.closed,0);s.close();checks++;
 }
 {
  const h=setup();await flush();const s=h.socket();h.controller.abort();assert.equal(await h.prep.take("marin"),null);assert.equal(s.closed,1);h.prep.dispose();assert.equal(s.closed,1);checks++;
 }
 {
  let resolve;const h=setup(()=>new Promise(r=>resolve=r));await flush();h.controller.abort();resolve(session);await flush();assert.equal(h.socket(),undefined);assert.equal(await h.prep.take("marin"),null);checks++;
 }
 for(const kind of ["error","close","expiry","invalid"]){
  const h=setup();await flush();const s=h.socket();
  if(kind==="expiry")h.expire();else if(kind==="invalid")s.emit("message",{type:"error"});else s.emit(kind);
  assert.equal(await h.prep.take("marin"),null);assert.equal(s.closed,1);checks++;
 }
 {
  const h=setup(async()=>{throw Error("No connection");});await flush();assert.equal(await h.prep.take("marin"),null);checks++;
 }
 {
  const h=setup();await flush();const s=h.socket();s.readyState=1;s.emit("message",{type:"session.created"});
  assert.equal(await h.prep.take("cedar"),null);h.prep.dispose();assert.equal(s.closed,1);checks++;
 }
 console.log(JSON.stringify({checks,network_calls:0,physical_audio:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
