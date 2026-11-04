"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
function setup(route){
 let generation=1,serial=0;const timers=new Map(),calls=[],applied=[],statuses=[];
 const snapshot={context:{process_name:"Fictional process"},turns:[{id:"u1",role:"user",text:"The clerk receives a request."}],document_revision:"doc1"};
 const window={},context={window,AbortController,DOMException,JSON,Error,TypeError,Set};vm.createContext(context);vm.runInContext(source,context);
 const controller=new window.CollectorConcurrentInterview({request:async(url,data,options)=>{calls.push({url,data,options});return route(url,data,options);},getSnapshot:()=>snapshot,getGeneration:()=>generation,applyCapture:(capture,meta)=>applied.push({capture,meta}),onStatus:status=>statuses.push(status),setTimeout:fn=>{const id=++serial;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
 const tick=async()=>{const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());await flush();};
 return{controller,snapshot,calls,applied,statuses,timers,tick,nextGeneration:()=>generation++};
}
const question={question:"What happens next?",preserve_capture:true,conversation_token:"session-one",revision:"r1"};
let passed=0;async function test(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
(async()=>{
await test("next question returns while analysis remains blocked",async()=>{
 const analysis=deferred(),h=setup(url=>url.endsWith("/turn")?question:analysis.promise);
 const result=await h.controller.turn(h.snapshot);assert.equal(result.question,question.question);assert.equal(h.applied.length,0);
 await h.tick();assert.equal(h.calls.length,2);assert.equal(h.applied.length,0);
 h.snapshot.turns.push({id:"a1",role:"assistant",text:question.question});analysis.resolve({state:"ready",revision:"r1",conversation_token:"session-one",capture:{question:"Analysis must never be spoken",summary:"Captured facts"}});await flush();
 assert.equal(h.applied.length,1);assert.equal(h.applied[0].capture.summary,"Captured facts");assert.equal(h.timers.size,0);
});
await test("one poll at a time and no duplicate capture",async()=>{
 let count=0;const h=setup(url=>url.endsWith("/turn")?question:{state:++count<3?"working":"ready",conversation_token:"session-one",revision:"r1",capture:{summary:"Ready"}});
 await h.controller.turn(h.snapshot);assert.equal(h.timers.size,1);await h.tick();assert.equal(h.timers.size,1);await h.tick();assert.equal(h.timers.size,1);await h.tick();assert.equal(h.applied.length,1);assert.equal(h.timers.size,0);
});
await test("new participant answer rejects an older analysis",async()=>{
 const analysis=deferred(),h=setup(url=>url.endsWith("/turn")?question:analysis.promise);await h.controller.turn(h.snapshot);await h.tick();h.snapshot.turns.push({id:"u2",role:"user",text:"Correction: the manager receives it."});analysis.resolve({state:"ready",revision:"r1",conversation_token:"session-one",capture:{summary:"Stale"}});await flush();assert.equal(h.applied.length,0);assert.equal(h.timers.size,0);
});
await test("edited answer context or documents invalidate old results",async()=>{
 for(const change of [h=>h.snapshot.turns[0].text="Changed",h=>h.snapshot.context.process_name="Another",h=>h.snapshot.document_revision="doc2",h=>h.nextGeneration()]){
  const analysis=deferred(),h=setup(url=>url.endsWith("/turn")?question:analysis.promise);await h.controller.turn(h.snapshot);await h.tick();change(h);analysis.resolve({state:"ready",revision:"r1",conversation_token:"session-one",capture:{summary:"Stale"}});await flush();assert.equal(h.applied.length,0);
 }
});
await test("late question cannot change the current session",async()=>{
 const turn=deferred(),h=setup(()=>turn.promise),pending=h.controller.turn(h.snapshot);h.snapshot.turns[0].text="Corrected before question returned";turn.resolve(question);await assert.rejects(pending,error=>error.name==="AbortError");assert.equal(h.controller.token,null);assert.equal(h.timers.size,0);
});
await test("reset cancels polling and pending turn and discards late results",async()=>{
 const turn=deferred(),h=setup(()=>turn.promise),pending=h.controller.turn(h.snapshot);h.controller.reset();assert.equal(h.calls[0].options.signal.aborted,true);turn.resolve(question);await assert.rejects(pending,error=>error.name==="AbortError");assert.equal(h.controller.token,null);assert.equal(h.timers.size,0);
});
await test("sync cancels advisory polling and waits for current capture",async()=>{
 const analysis=deferred(),sync=deferred(),h=setup(url=>url.endsWith("/turn")?question:url.endsWith("/sync")?sync.promise:analysis.promise);
 await h.controller.turn(h.snapshot);await h.tick();const pending=h.controller.sync(h.snapshot);assert.equal(h.calls[1].options.signal.aborted,true);assert.equal(h.calls[2].data.conversation_token,"session-one");analysis.resolve({state:"ready",revision:"r1",conversation_token:"session-one",capture:{summary:"Earlier"}});await flush();assert.equal(h.applied.length,0);
 sync.resolve({...question,capture:{summary:"Authoritative"}});const result=await pending;assert.equal(result.capture.summary,"Authoritative");assert.equal(h.timers.size,0);
});
await test("background failure preserves conversation and stops automatic retries",async()=>{
 const h=setup(url=>url.endsWith("/turn")?question:Promise.reject(Error("Analysis unavailable")));await h.controller.turn(h.snapshot);await h.tick();assert.equal(h.applied.length,0);assert.equal(h.statuses.at(-1).state,"error");assert.equal(h.timers.size,0);assert.equal(h.snapshot.turns.length,1);
});
await test("new turns reuse capability and supersede old poll",async()=>{
 const old=deferred(),h=setup(url=>url.endsWith("/turn")?question:old.promise);await h.controller.turn(h.snapshot);await h.tick();h.snapshot.turns.push({id:"u2",role:"user",text:"Another answer"});await h.controller.turn(h.snapshot);assert.equal(h.calls[1].options.signal.aborted,true);assert.equal(h.calls[2].data.conversation_token,"session-one");assert.equal(h.timers.size,1);old.resolve({state:"ready",revision:"r1",conversation_token:"session-one",capture:{summary:"Old"}});await flush();assert.equal(h.applied.length,0);
});
await test("notes publish while workflow is still working and graph publishes later",async()=>{
 let polls=0;const h=setup(url=>url.endsWith("/turn")?question:{state:"ready",conversation_token:"session-one",revision:"r1",capture:{summary:"Notes already available"},workflow_state:++polls<3?"working":"ready",...(polls===3?{workflow_capture:{workflow:{steps:[],connections:[]}}}:{})});
 await h.controller.turn(h.snapshot);await h.tick();assert.equal(h.applied.length,1);assert.equal(h.applied[0].capture.summary,"Notes already available");assert.equal(h.timers.size,1);await h.tick();assert.equal(h.applied.length,1);await h.tick();assert.equal(h.applied.length,2);assert.ok(h.applied[1].capture.workflow_capture);assert.equal(h.timers.size,0);
});
await test("polling pins document retrieval hints even when applying notes adds citations",async()=>{
 const h=setup(url=>url.endsWith("/turn")?question:{state:"working",conversation_token:"session-one",revision:"r1"});h.snapshot.document_source_ids=["doc_original"];
 await h.controller.turn(h.snapshot);h.snapshot.document_source_ids=["doc_original","doc_new_citation"];h.snapshot.turns.push({id:"a1",role:"assistant",text:question.question});await h.tick();
 assert.deepEqual(h.calls[1].data.document_source_ids,["doc_original"]);assert.equal(h.calls[1].data.turns.at(-1).role,"user");assert.equal(h.timers.size,1);h.controller.reset();
});
await test("failed workflow publishes notes without falsely reporting caught up",async()=>{
 const h=setup(url=>url.endsWith("/turn")?question:{state:"ready",conversation_token:"session-one",revision:"r1",capture:{summary:"Accepted notes"},workflow_state:"error",workflow_error:"The workflow could not update."});
 await h.controller.turn(h.snapshot);await h.tick();assert.equal(h.applied.length,1);assert.equal(h.applied[0].capture.summary,"Accepted notes");assert.equal(h.statuses.at(-1).state,"error");assert.equal(h.statuses.some(status=>status.state==="ready"),false);assert.equal(h.timers.size,0);
});
await test("abort supplied by voice cancels pending turn",async()=>{
 const turn=deferred(),h=setup(()=>turn.promise),abort=new AbortController(),pending=h.controller.turn(h.snapshot,{signal:abort.signal});abort.abort();assert.equal(h.calls[0].options.signal.aborted,true);turn.resolve(question);await assert.rejects(pending,error=>error.name==="AbortError");assert.equal(h.timers.size,0);
});
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
