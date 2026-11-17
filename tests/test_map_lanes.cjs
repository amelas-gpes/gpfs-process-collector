"use strict";
// The page side of the map lanes: the map is shown as soon as it is drawn, the map through an
// earlier answer is shown while the next is drawn, and the checked map replaces the drawn one.
// Offline: the controller of web/concurrent-interview.js with a scripted status route.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../web/concurrent-interview.js"),"utf8");
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
const R="a".repeat(64),EARLIER="b".repeat(64);
function setup(route,turns){
 let serial=0;const timers=new Map(),calls=[],applied=[],statuses=[],workflows=[];
 const snapshot={context:{process_name:"Fictional process"},turns:turns||[{id:"u1",role:"user",text:"The clerk receives a request."}],document_revision:"doc1"};
 const window={},context={window,AbortController,DOMException,JSON,Error,TypeError,Set,Date};vm.createContext(context);vm.runInContext(source,context);
 const controller=new window.CollectorConcurrentInterview({request:async(url,data,options)=>{calls.push({url,data,options});return route(url,data,options);},
  getSnapshot:()=>snapshot,getGeneration:()=>1,applyCapture:(capture,meta)=>applied.push({capture,meta}),applyWorkflow:(capture,meta)=>workflows.push({capture,meta}),
  onStatus:status=>statuses.push(status),setTimeout:fn=>{const id=++serial;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
 const tick=async()=>{const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());await flush();};
 return{controller,snapshot,calls,applied,workflows,statuses,timers,tick};
}
const question={question:"What happens next?",preserve_capture:true,conversation_token:"session-one",revision:R};
const map=title=>({workflow:{title,steps:[{id:"S1"}],connections:[],open_questions:[]}});
const base={conversation_token:"session-one",revision:R};
const scripted=replies=>{let index=0;return url=>url.endsWith("/turn")?question:replies[Math.min(index++,replies.length-1)];};
let passed=0;async function test(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
(async()=>{
await test("the map of this answer is shown before its notes are ready",async()=>{
 const h=setup(scripted([
  {...base,state:"working",workflow_state:"ready",workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"working",workflow_version:1},
  {...base,state:"working",workflow_state:"ready",workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"working",workflow_version:1}]));
 await h.controller.turn(h.snapshot);await h.tick();
 assert.equal(h.applied.length,0,"No notes yet");
 assert.equal(h.workflows.length,1);assert.equal(h.workflows[0].capture.workflow.title,"Drawn");assert.equal(h.workflows[0].meta.check,"working");
 await h.tick();assert.equal(h.workflows.length,1,"The same map is not applied twice");
 assert.equal(h.timers.size,1,"The notes are still awaited");
});
await test("the checked map replaces the drawn one without the notes being applied again",async()=>{
 const drawn={...base,state:"ready",capture:{summary:"Notes"},workflow_state:"ready",workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"working",workflow_version:1};
 const h=setup(scripted([drawn,drawn,{...drawn,workflow_capture:map("Checked"),workflow_checked:true,workflow_check_state:undefined,workflow_version:2}]));
 await h.controller.turn(h.snapshot);await h.tick();
 assert.equal(h.applied.length,1);assert.equal(h.applied[0].capture.workflow_capture.workflow.title,"Drawn");assert.equal(h.applied[0].meta.check,"working");
 assert.equal(h.statuses.at(-1).state,"ready","The notes are up to date while the map is being checked");assert.equal(h.statuses.at(-1).workflow,"checking");
 assert.equal(h.timers.size,1,"The page keeps asking for the result of the check");
 await h.tick();assert.equal(h.applied.length,1);assert.equal(h.workflows.length,0);
 await h.tick();
 assert.equal(h.applied.length,1,"The notes are not applied a second time for a map that changed");
 assert.equal(h.workflows.length,1);assert.equal(h.workflows[0].capture.workflow.title,"Checked");assert.equal(h.workflows[0].meta.check,"");
 assert.equal(h.timers.size,0);assert.equal(h.statuses.at(-1).state,"ready");assert.equal(h.statuses.at(-1).workflow,undefined);
});
await test("a check that failed during the interview stays quiet: the map says so and the next answer checks again",async()=>{
 const h=setup(scripted([{...base,state:"ready",capture:{summary:"Notes"},workflow_state:"ready",workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"error",workflow_check_error:"The provider timed out. Your answers are retained.",workflow_version:1}]));
 await h.controller.turn(h.snapshot);await h.tick();
 assert.equal(h.applied.length,1);assert.equal(h.applied[0].meta.check,"error");
 assert.equal(h.statuses.at(-1).state,"ready");assert.equal(h.timers.size,0,"A failed check is not polled for");
});
await test("the map through an earlier answer is shown once while the next is drawn, and only for an unchanged beginning",async()=>{
 const turns=[{id:"u1",role:"user",text:"The clerk receives a request."},{id:"a1",role:"assistant",text:"What happens next?"},{id:"u2",role:"user",text:"The manager approves it."}];
 for(const changed of [false,true]){
  const checkpoint={revision:EARLIER,through_turn_id:"u1",turns:[{id:"u1",role:"user",text:changed?"Another wording.":"The clerk receives a request."}],workflow_capture:map("Through answer one"),checked:false,version:3};
  const h=setup(scripted([{...base,state:"working",workflow_state:"working",workflow_checkpoint:checkpoint}]),JSON.parse(JSON.stringify(turns)));
  await h.controller.turn(h.snapshot);await h.tick();
  assert.equal(h.workflows.length,changed?0:1);
  if(!changed){
   assert.equal(h.workflows[0].capture.workflow.title,"Through answer one");
   assert.deepEqual(h.workflows[0].meta.snapshot.turns.map(turn=>turn.id),["u1"],"The map is applied against the answers it was drawn from");
   assert.equal(h.workflows[0].meta.checkpoint,true);
   await h.tick();assert.equal(h.workflows.length,1,"Published once");
  }
 }
});
await test("a checkpoint that does not name the answer it goes through is not shown",async()=>{
 const turns=[{id:"u1",role:"user",text:"The clerk receives a request."},{id:"u2",role:"user",text:"The manager approves it."}];
 const h=setup(scripted([{...base,state:"working",workflow_state:"working",workflow_checkpoint:{revision:EARLIER,through_turn_id:"u2",turns:[turns[0]],workflow_capture:map("Mislabelled"),version:1}}]),turns);
 await h.controller.turn(h.snapshot);await h.tick();assert.equal(h.workflows.length,0);
});
await test("the map of this answer takes the place of the earlier one when it arrives",async()=>{
 const turns=[{id:"u1",role:"user",text:"The clerk receives a request."},{id:"u2",role:"user",text:"The manager approves it."}];
 const checkpoint={revision:EARLIER,through_turn_id:"u1",turns:[turns[0]],workflow_capture:map("Through answer one"),checked:true,version:3};
 const h=setup(scripted([{...base,state:"working",workflow_state:"working",workflow_checkpoint:checkpoint},
  {...base,state:"ready",capture:{summary:"Notes"},workflow_state:"ready",workflow_capture:map("Latest"),workflow_checked:true,workflow_version:4}]),turns);
 await h.controller.turn(h.snapshot);await h.tick();assert.equal(h.workflows.length,1);
 await h.tick();assert.equal(h.applied.length,1);assert.equal(h.applied[0].capture.workflow_capture.workflow.title,"Latest");assert.equal(h.applied[0].meta.check,"");
 assert.equal(h.timers.size,0);
});
await test("wrap up shows the map it is given and fetches the checked one afterwards",async()=>{
 const replies=[{...base,state:"ready",workflow_state:"ready",workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"working",workflow_version:5},
  {...base,state:"ready",workflow_state:"ready",workflow_capture:map("Checked"),workflow_checked:true,workflow_version:6}];
 let index=0;
 const h=setup(url=>url.endsWith("/sync")?{...question,capture_token:"capability",workflow_state:"ready",workflow_pending:false,workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"working",workflow_version:5}:replies[Math.min(index++,1)]);
 const result=await h.controller.sync(h.snapshot);
 assert.equal(result.workflow_capture.workflow.title,"Drawn","The caller applies the released map");
 assert.equal(h.statuses.at(-1).state,"ready");assert.equal(h.statuses.at(-1).workflow,"checking");assert.equal(h.timers.size,1);
 await h.tick();assert.equal(h.workflows.length,0,"The map the caller already has is not applied again");assert.equal(h.timers.size,1);
 await h.tick();assert.equal(h.workflows.length,1);assert.equal(h.workflows[0].capture.workflow.title,"Checked");assert.equal(h.workflows[0].meta.check,"");
 assert.equal(h.applied.length,0,"After Wrap up nothing but the map is taken from a status reply");
 assert.equal(h.statuses.at(-1).workflow,"ready");assert.equal(h.timers.size,0);
});
await test("after wrap up a check that failed is reported with the map's own retry",async()=>{
 const h=setup(url=>url.endsWith("/sync")?{...question,workflow_state:"ready",workflow_pending:false,workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"working",workflow_version:5}
  :{...base,state:"ready",workflow_state:"ready",workflow_capture:map("Drawn"),workflow_checked:false,workflow_check_state:"error",workflow_check_error:"The provider timed out. Your answers are retained.",workflow_version:5});
 await h.controller.sync(h.snapshot);await h.tick();
 const last=h.statuses.at(-1);
 assert.equal(last.state,"error");assert.equal(last.scope,"workflow");assert.equal(last.message,"The provider timed out. Your answers are retained.");
 assert.equal(h.workflows.length,1,"The line under the map changes from pending to incomplete");assert.equal(h.workflows[0].meta.check,"error");
 assert.equal(h.timers.size,0);
});
await test("a checked map released by wrap up needs no further poll",async()=>{
 const h=setup(url=>url.endsWith("/sync")?{...question,workflow_state:"ready",workflow_pending:false,workflow_capture:map("Checked"),workflow_checked:true,workflow_version:2}:{});
 await h.controller.sync(h.snapshot);assert.equal(h.timers.size,0);assert.equal(h.statuses.at(-1).state,"ready");assert.equal(h.statuses.at(-1).workflow,undefined);
});
await test("a server that does not say whether the map was checked is treated as before",async()=>{
 const h=setup(scripted([{...base,state:"ready",capture:{summary:"Notes"},workflow_state:"ready",workflow_capture:map("Plain")}]));
 await h.controller.turn(h.snapshot);await h.tick();
 assert.equal(h.applied.length,1);assert.equal(h.applied[0].meta.check,"");assert.equal(h.timers.size,0);assert.equal(h.statuses.at(-1).state,"ready");
});
console.log(JSON.stringify({tests_passed:passed}));
})().catch(error=>{console.error(error);process.exitCode=1;});
