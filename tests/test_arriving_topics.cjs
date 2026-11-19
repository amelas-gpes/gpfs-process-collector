"use strict";
// After a file is added, the topic states of the notes being written are passed on for display, and
// the page asks for the result often while someone is watching for it. Offline: no provider, no network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
function setup(route){
 let serial=0,clock=1000;const timers=new Map(),delays=[],applied=[],arriving=[];
 const snapshot={context:{process_name:""},turns:[],document_revision:"doc1"};
 const window={},context={window,crypto:require("node:crypto").webcrypto,AbortController,DOMException,JSON,Error,TypeError,Set,Date:{now:()=>clock}};
 vm.createContext(context);vm.runInContext(source,context);
 const controller=new window.CollectorConcurrentInterview({request:async(url,data)=>route(url,data),getSnapshot:()=>snapshot,getGeneration:()=>1,
  applyCapture:capture=>applied.push(capture),onProvisionalTopics:(rows,meta)=>arriving.push({rows,meta}),
  setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,fn);delays.push(ms);return id;},clearTimeout:id=>timers.delete(id)});
 const tick=async(elapsed=0)=>{clock+=elapsed;const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());await flush();};
 return{controller,snapshot,applied,arriving,delays,timers,tick};
}
const question={question:"Who approves the release?",preserve_capture:true,conversation_token:"session-one",revision:"r1"};
const TOPICS=[{key:"purpose",status:"partial"},{key:"volume",status:"unknown"}];
const working=(topics)=>({state:"working",conversation_token:"session-one",revision:"r1",agent_team:{run_id:"run",status:"running",agents:[],events:[],...(topics?{provisional_topics:topics}:{})}});
let passed=0;async function test(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
(async()=>{
await test("topic states of notes still being written are passed on, and never applied as notes",async()=>{
 const replies=[working(),working(TOPICS),working(TOPICS),{state:"ready",conversation_token:"session-one",revision:"r1",capture:{summary:"Notes"}}];
 const h=setup(url=>url.endsWith("/turn")?question:replies.shift());
 await h.controller.turn(h.snapshot,{documentIntake:true});
 await h.tick();assert.equal(h.arriving.length,0);
 await h.tick();assert.equal(h.arriving.length,1);
 assert.deepEqual(JSON.parse(JSON.stringify(h.arriving[0])),{rows:TOPICS,meta:{revision:"r1"}});
 assert.equal(h.applied.length,0);
 await h.tick();assert.equal(h.arriving.length,2);
 await h.tick();assert.equal(h.applied.length,1);assert.equal(h.applied[0].summary,"Notes");assert.equal(h.arriving.length,2);
});
await test("an empty or malformed list is not passed on",async()=>{
 const replies=[working([]),working("purpose"),{state:"ready",conversation_token:"session-one",revision:"r1",capture:{summary:"Notes"}}];
 const h=setup(url=>url.endsWith("/turn")?question:replies.shift());
 await h.controller.turn(h.snapshot,{documentIntake:true});await h.tick();await h.tick();await h.tick();
 assert.equal(h.arriving.length,0);assert.equal(h.applied.length,1);
});
await test("states that arrive for a superseded account are dropped with it",async()=>{
 const h=setup(url=>url.endsWith("/turn")?question:working(TOPICS));
 await h.controller.turn(h.snapshot,{documentIntake:true});
 h.snapshot.turns.push({id:"u1",role:"user",text:"We start when the invoice arrives."});
 await h.tick();assert.equal(h.arriving.length,0);
});
await test("after a file is added the page asks often for half a minute, then backs off",async()=>{
 const h=setup(url=>url.endsWith("/turn")?question:working());
 await h.controller.turn(h.snapshot,{documentIntake:true});
 for(let i=0;i<12;i++)await h.tick(400);
 assert.deepEqual(h.delays.slice(1,13),Array(12).fill(400));
 await h.tick(30000);
 assert.ok(h.delays.at(-1)>1000,"backed off: "+h.delays.at(-1));
});
await test("an ordinary answer keeps the earlier pace",async()=>{
 const h=setup(url=>url.endsWith("/turn")?question:working());
 await h.controller.turn(h.snapshot);
 for(let i=0;i<7;i++)await h.tick(650);
 assert.deepEqual(h.delays.slice(0,8),[650,650,650,1300,1300,1300,1950,1950]);
});
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
