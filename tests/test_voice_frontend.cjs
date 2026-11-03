"use strict";
// Isolated media-protocol checks: no browser, network, microphone or provider call.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const source=fs.readFileSync(require("node:path").join(__dirname,"..","web","app.js"),"utf8")
 .replace(/  init\(\);\s*\}\)\(\);\s*$/, "  window.__voiceTests={state,normalizedSpeech,pcmWave,naturalSpeechAudio,stopSpeaking};\n})();");
let socket,revoked=[],cancelCount=0;
class FakeWebSocket{
 constructor(url,protocols){this.url=url;this.protocols=protocols;this.listeners={};this.sent=[];this.closed=false;socket=this;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
 send(value){this.sent.push(JSON.parse(value));}
 close(){this.closed=true;for(const fn of this.listeners.close||[])fn({});}
 emit(value){for(const fn of this.listeners.message||[])fn({data:JSON.stringify(value)});}
}
const nodes=new Map();
const context={console,Blob,DataView,Uint8Array,AbortController,DOMException,WebSocket:FakeWebSocket,
 setTimeout,clearTimeout,Date,JSON,URL:{revokeObjectURL:v=>revoked.push(v)},
 atob:s=>Buffer.from(s,"base64").toString("binary"),
 document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,{hidden:false});return nodes.get(id);}},
 window:{speechSynthesis:{cancel:()=>cancelCount++}}};
vm.createContext(context);vm.runInContext(source,context,{filename:"app.js"});
const t=context.window.__voiceTests;
if(!t)throw new Error("Test seam was not installed");
const session={provider:"openai",transport:"openai-realtime-websocket",model:"gpt-realtime-2.1-mini",client_secret:"ephemeral-fake-test-token"};
const operation=()=>({controller:new AbortController(),socket:null,audio:null,url:null,timer:null});
function begin(message="Hello there."){
 const op=operation(),promise=t.naturalSpeechAudio(session,message,op);
 socket.emit({type:"session.created"});
 const item=socket.sent[0].item;
 socket.emit({type:"conversation.item.done",item:{id:item.id,role:"user"}});
 return{op,promise,socket};
}
function complete(s,transcript="Hello there."){
 s.emit({type:"response.output_audio.delta",delta:Buffer.from([0,0,1,0]).toString("base64")});
 s.emit({type:"response.output_audio_transcript.done",transcript});
 s.emit({type:"response.done",response:{status:"completed"}});
}
(async()=>{
 let passes=0;
 assert.equal(t.normalizedSpeech("HELLO, １２!"),t.normalizedSpeech("hello 12"));passes++;
 {
  const previousSocket=socket;
  await assert.rejects(t.naturalSpeechAudio({...session,provider:"azure-foundry"},"Hello there.",operation()),/not supported by this version/);
  await assert.rejects(t.naturalSpeechAudio({...session,transport:"unimplemented-transport"},"Hello there.",operation()),/not supported by this version/);
  await assert.rejects(t.naturalSpeechAudio({model:session.model,client_secret:session.client_secret},"Hello there.",operation()),/not supported by this version/);
  assert.equal(socket,previousSocket,"Unsupported connections must not create an OpenAI socket");passes++;
 }
 {
  const run=begin();assert.equal(run.socket.sent.length,2);
  assert.equal(run.socket.sent[1].response.output_modalities[0],"audio");
  complete(run.socket);const blob=await run.promise,buffer=await blob.arrayBuffer(),view=new DataView(buffer);
  assert.equal(blob.type,"audio/wav");assert.equal(blob.size,48);assert.equal(view.getUint32(24,true),24000);
  assert.equal(view.getUint16(22,true),1);assert.equal(view.getUint16(34,true),16);assert.equal(run.socket.closed,true);passes++;
 }
 {
  const run=begin();const rejected=assert.rejects(run.promise,/did not read the question exactly/);
  complete(run.socket,"Here is an unrelated answer.");await rejected;assert.equal(run.socket.closed,true);passes++;
 }
 {
  const run=begin();const rejected=assert.rejects(run.promise,e=>e.name==="AbortError");
  run.op.controller.abort();await rejected;assert.equal(run.socket.closed,true);passes++;
 }
 {
  const run=begin();const rejected=assert.rejects(run.promise,/did not finish/);
  run.socket.emit({type:"response.done",response:{status:"incomplete"}});await rejected;passes++;
 }
 {
  const run=begin();const rejected=assert.rejects(run.promise,/exceeds the audio limit/);
  run.socket.emit({type:"response.output_audio.delta",delta:"A".repeat(Math.ceil(8*1024*1024*4/3)+8)});await rejected;passes++;
 }
 {
  const op=operation(),promise=t.naturalSpeechAudio(session,"Hello there.",op);
  socket.emit({type:"session.created"});socket.emit({type:"conversation.item.done",item:{id:"unrelated",role:"user"}});
  assert.equal(socket.sent.length,1);const rejected=assert.rejects(promise,e=>e.name==="AbortError");op.controller.abort();await rejected;passes++;
 }
 {
  const op=operation();let paused=false,removed=false;op.url="blob:disposable-test";
  op.audio={pause:()=>paused=true,removeAttribute:name=>removed=name==="src"};
  t.state.speechOperation=op;const oldVersion=t.state.speechVersion;t.stopSpeaking();
  assert.equal(op.controller.signal.aborted,true);assert.equal(paused,true);assert.equal(removed,true);
  assert.equal(revoked.includes(op.url),true);assert.equal(t.state.speechVersion,oldVersion+1);assert.equal(cancelCount>0,true);passes++;
 }
 console.log(JSON.stringify({tests_passed:passes,network_calls:0,provider_calls:0,physical_audio:false}));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
