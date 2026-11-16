"use strict";
// File-intake orchestration checks use deferred local hooks, never providers,
// physical audio, raw file uploads or browser globals beyond the exported class.
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const source=fs.readFileSync(path.join(__dirname,"..","web","document-intake.js"),"utf8"),sandbox={window:{},AbortController};
vm.createContext(sandbox);vm.runInContext(source,sandbox,{filename:"document-intake.js"});
const Intake=sandbox.window.CollectorDocumentIntake;
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const copy=value=>JSON.parse(JSON.stringify(value));
const file=(id="doc_one",overrides={})=>({id,name:id+".pdf",status:"ready",chunk_count:4,analysis:{phase:"complete",version:3,intent_version:0,disposition:"relevant",review_complete:true},...overrides});
const state=(documents=[],overrides={})=>({scope:"scope_one",generation:0,documents,uploading:0,mutating:0,connectionError:"",uploadErrors:[],...overrides});
function setup(overrides={}) {
 const events=[],calls={begin:[],baseline:[],question:[],complete:[],empty:[]},phases=[];
 const hooks={onStatus:controller=>phases.push(controller.phase),
  onBegin:input=>{events.push("pause");calls.begin.push(input);return overrides.begin?.(input);},
  buildBaseline:input=>{events.push("baseline");calls.baseline.push(input);return overrides.baseline?overrides.baseline(input):Promise.resolve({revision:calls.baseline.length,summary:"Accepted source baseline"});},
  askFollowup:input=>{events.push("question");calls.question.push(input);return overrides.question?overrides.question(input):Promise.resolve({question:"Who owns the remaining handoff?"});},
  onComplete:(result,documents)=>{events.push("complete");calls.complete.push({result,documents});overrides.complete?.(result,documents);},
  onEmpty:outcome=>{events.push("empty");calls.empty.push(outcome);overrides.empty?.(outcome);}};
 const intake=new Intake(hooks);intake.observe(state([]));return{intake,events,calls,phases};
}
const results=[];
async function check(name,run){try{await run();results.push({name,passed:true});}catch(error){results.push({name,passed:false,error:error.stack||String(error)});}}
(async()=>{
 await check("a sampled file with its review paused releases the interview",async()=>{
   const h=setup();h.intake.begin({batchId:"new"});h.intake.observe(state([file("one",{analysis:{phase:"deep",review_stopped:true}})]));h.intake.settle("new");await tick();
   assert.equal(h.intake.phase,"ready");assert.equal(h.calls.empty[0].reason,"paused");assert.equal(h.calls.baseline.length,0);
 });
 await check("a transient status outage preserves the already verified in-flight capture",async()=>{
   for(const stage of ["baseline","question"]){
     const pending=deferred(),h=setup({[stage]:()=>pending.promise});
     h.intake.begin({batchId:"first"});h.intake.observe(state([file()]));h.intake.settle("first");await tick();
     assert.equal(h.calls[stage].length,1);h.intake.observe(state([file()],{connectionError:"Status unavailable"}));await tick();
     assert.equal(h.calls[stage][0].signal.aborted,false);assert.equal(h.calls[stage].length,1);
     pending.resolve(stage==="baseline"?{revision:"verified"}:{question:"Current question?"});await tick();
     assert.equal(h.calls.complete.length,1);assert.equal(h.intake.phase,"ready");
   }
 });
 await check("a poll outage or dismissal of a previous error never restarts a baseline or question",async()=>{
  const old={name:"old.pdf",message:"Old upload failed"};
  const baseline=deferred(),question=deferred(),h=setup({baseline:()=>baseline.promise,question:()=>question.promise});
  h.intake.observe(state([],{uploadErrors:[old]}));h.intake.begin({batchId:"first"});
  h.intake.observe(state([file()],{uploadErrors:[old]}));h.intake.settle("first");await tick();
  for(const connectionError of ["Offline",""])h.intake.observe(state([file()],{connectionError}));
  assert.equal(h.calls.baseline.length,1);assert.equal(h.calls.baseline[0].signal.aborted,false);
  baseline.resolve({});await tick();
  for(const connectionError of ["Offline",""])h.intake.observe(state([file()],{connectionError}));
  assert.equal(h.calls.question[0].signal.aborted,false);question.resolve({question:"Ready?"});await tick();
  assert.equal(h.intake.phase,"ready");
 });
 await check("file action without an upload waits at the review stage",async()=>{
  const h=setup();h.intake.begin({documentId:"doc_one"});h.intake.observe(state([file()],{mutating:1}));
  assert.equal(h.intake.phase,"reviewing");assert.equal(h.calls.baseline.length,0);
 });
 await check("upload pauses synchronously and requires settled counters",async()=>{
  const h=setup();h.intake.begin({batchId:"batch_one",names:["Procedure.pdf"]});
  assert.deepEqual(h.events,["pause"]);assert.equal(h.intake.active,true);assert.equal(h.intake.phase,"uploading");
  h.intake.observe(state([file()],{uploading:1,mutating:1}));await tick();assert.equal(h.calls.baseline.length,0);
  h.intake.settle("batch_one");await tick();assert.equal(h.calls.baseline.length,0,"A settled callback cannot bypass uploads still shown in the snapshot");
  h.intake.observe(state([file()]));await tick();assert.deepEqual(h.events,["pause","baseline","question","complete"]);assert.equal(h.intake.phase,"ready");assert.equal(h.intake.active,false);
 });
 await check("extraction and quick/deep review do not ask early",async()=>{
  const h=setup();h.intake.begin({batchId:"batch_one",names:["Procedure.pdf"]});
  h.intake.observe(state([file("doc_one",{status:"indexing",chunk_count:0,analysis:{}})]));h.intake.settle("batch_one");await tick();assert.equal(h.intake.phase,"reviewing");
  for(const analysis of [{},{phase:"quick",version:1,summary:"Initial sample",question:"Premature question?"},{phase:"deep",version:2,summary:"More sections",question:"Still premature?"}]){
   h.intake.observe(state([file("doc_one",{status:"partial",analysis})]));await tick();assert.equal(h.calls.question.length,0);assert.equal(h.calls.baseline.length,0);
  }
  h.intake.observe(state([file("doc_one",{status:"partial",analysis:{phase:"complete",version:3,disposition:"relevant",review_complete:false}})]));await tick();
  assert.equal(h.calls.baseline.length,1);assert.equal(h.calls.question.length,1);assert.equal(h.calls.baseline[0].documents[0].analysis.review_complete,false,"Completed partial coverage must not be represented as full coverage");
 });
 await check("all accepted batches and files share a single pause and followup",async()=>{
  const h=setup();h.intake.begin({batchId:"first",names:["First.pdf"]});h.intake.begin({batchId:"second",names:["Second.pdf"]});assert.equal(h.calls.begin.length,1);
  h.intake.observe(state([file("first"),file("second",{analysis:{phase:"deep",version:2}})],{uploading:1,mutating:1}));h.intake.settle("first");await tick();assert.equal(h.calls.baseline.length,0);
  h.intake.observe(state([file("first"),file("second",{analysis:{phase:"deep",version:2}})]));h.intake.settle("second");await tick();assert.equal(h.intake.phase,"reviewing");
  h.intake.observe(state([file("first"),file("second")]));await tick();assert.equal(h.calls.question.length,1);assert.equal(h.calls.baseline[0].documents.length,2);assert.equal(h.calls.complete.length,1);
 });
 await check("baseline waits for voice stop and final caption drain",async()=>{
  const pause=deferred(),h=setup({begin:()=>pause.promise});h.intake.begin({batchId:"first",names:["Procedure.pdf"]});h.intake.observe(state([file()]));h.intake.settle("first");await tick();
  assert.equal(h.calls.baseline.length,0);assert.equal(h.calls.question.length,0,"A completed file cannot race ahead of the voice-drain dependency");
  pause.resolve();await tick();assert.equal(h.calls.baseline.length,1);assert.equal(h.calls.complete.length,1);
 });
 await check("accepted baseline is supplied before the single followup",async()=>{
  const baseline=deferred(),question=deferred(),h=setup({baseline:()=>baseline.promise,question:()=>question.promise});h.intake.begin({batchId:"first"});h.intake.observe(state([file()]));h.intake.settle("first");await tick();
  assert.equal(h.intake.phase,"baseline");assert.equal(h.calls.question.length,0);const accepted={revision:22,summary:"Updated graph and notes"};baseline.resolve(accepted);await tick();
  assert.equal(h.intake.phase,"question");assert.equal(h.calls.question[0].baseline,accepted);assert.equal(h.calls.complete.length,0);
  question.resolve({question:"Which team owns the documented exception?"});await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.calls.complete[0].result.question,"Which team owns the documented exception?");assert.equal(h.intake.phase,"ready");
 });
 await check("repeated status snapshots do not duplicate work or questions",async()=>{
  const baseline=deferred(),h=setup({baseline:()=>baseline.promise});h.intake.begin({batchId:"first"});const snapshot=state([file()]);h.intake.observe(snapshot);h.intake.settle("first");await tick();
  for(let i=0;i<5;i++)h.intake.observe(copy(snapshot));await tick();assert.equal(h.calls.baseline.length,1);assert.equal(h.calls.baseline[0].signal.aborted,false);
  baseline.resolve({revision:1});await tick();for(let i=0;i<5;i++)h.intake.observe(copy(snapshot));h.intake.settle("first");await tick();assert.equal(h.calls.question.length,1);assert.equal(h.calls.complete.length,1);
 });
 await check("new upload cancels a stale baseline without a second pause",async()=>{
  const old=deferred(),fresh=deferred(),h=setup({baseline:()=>h.calls.baseline.length===1?old.promise:fresh.promise});h.intake.begin({batchId:"first"});h.intake.observe(state([file("first")]));h.intake.settle("first");await tick();
  h.intake.begin({batchId:"second",names:["Second.pdf"]});assert.equal(h.calls.baseline[0].signal.aborted,true);assert.equal(h.calls.begin.length,1);
  old.resolve({revision:"stale"});await tick();assert.equal(h.calls.question.length,0);assert.equal(h.calls.complete.length,0);
  h.intake.observe(state([file("first"),file("second")]));h.intake.settle("second");await tick();assert.equal(h.calls.baseline.length,2);
  fresh.resolve({revision:"fresh"});await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.calls.question[0].baseline.revision,"fresh");
 });
 await check("new upload cancels a stale question before publication",async()=>{
  const stale=deferred(),h=setup({question:()=>h.calls.question.length===1?stale.promise:Promise.resolve({question:"Current batch question"})});h.intake.begin({batchId:"first"});h.intake.observe(state([file("first")]));h.intake.settle("first");await tick();assert.equal(h.intake.phase,"question");
  h.intake.begin({batchId:"second"});assert.equal(h.calls.question[0].signal.aborted,true);stale.resolve({question:"Obsolete question"});await tick();assert.equal(h.calls.complete.length,0);
  h.intake.observe(state([file("first"),file("second")]));h.intake.settle("second");await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.calls.complete[0].result.question,"Current batch question");
 });
 await check("review revision changes cancel the obsolete baseline",async()=>{
  const old=deferred(),h=setup({baseline:()=>h.calls.baseline.length===1?old.promise:Promise.resolve({revision:"current"})});h.intake.begin({batchId:"first"});h.intake.observe(state([file()]));h.intake.settle("first");await tick();
  h.intake.observe(state([file("doc_one",{analysis:{phase:"deep",version:4,intent_version:1,disposition:"relevant"}})]));assert.equal(h.calls.baseline[0].signal.aborted,true);old.resolve({revision:"obsolete"});await tick();assert.equal(h.calls.question.length,0);
  h.intake.observe(state([file("doc_one",{analysis:{phase:"complete",version:5,intent_version:1,disposition:"relevant"}})]));await tick();assert.equal(h.calls.question.length,1);assert.equal(h.calls.question[0].baseline.revision,"current");
 });
 await check("reset invalidates pause, baseline and question completions",async()=>{
  for(const step of ["begin","baseline","question"]){
   const pending=deferred(),h=setup({[step]:()=>pending.promise});h.intake.begin({batchId:"old"});h.intake.observe(state([file()]));h.intake.settle("old");await tick();
   const signals=[...h.calls.begin,...h.calls.baseline,...h.calls.question].map(call=>call.signal);h.intake.reset();assert.equal(h.intake.phase,"idle");assert.equal(h.intake.active,false);assert.ok(signals.every(signal=>signal.aborted));
   pending.resolve({question:"Stale question",revision:"stale"});await tick();assert.equal(h.calls.complete.length,0);assert.equal(h.calls.empty.length,0);assert.equal(h.intake.phase,"idle");
  }
 });
 await check("reset followed by another interview cannot publish old results",async()=>{
  const pending=deferred(),h=setup({question:()=>h.calls.question.length===1?pending.promise:Promise.resolve({question:"New interview question"})});h.intake.begin({batchId:"old"});h.intake.observe(state([file("old")]));h.intake.settle("old");await tick();
  h.intake.reset();h.intake.observe(state([],{scope:"scope_new"}));h.intake.begin({batchId:"new"});h.intake.observe(state([file("new")],{scope:"scope_new"}));h.intake.settle("new");await tick();
  pending.resolve({question:"Old interview question"});await tick();assert.equal(h.calls.begin.length,2);assert.equal(h.calls.complete.length,1);assert.equal(h.calls.complete[0].result.question,"New interview question");assert.equal(h.calls.complete[0].documents[0].id,"new");
 });
 await check("review errors retain previous capture until explicit retry succeeds",async()=>{
  const h=setup();h.intake.begin({batchId:"first"});h.intake.observe(state([file("broken",{analysis:{phase:"error",version:1,error:"Review timed out"}})]));h.intake.settle("first");await tick();
  assert.equal(h.intake.phase,"error");assert.equal(h.intake.retryAvailable,false,"File review must be retried from Assets");assert.equal(h.calls.baseline.length,0);h.intake.retry();await tick();assert.equal(h.calls.baseline.length,0,"Retry cannot relabel a failed document as reviewed");
  h.intake.observe(state([file("broken",{analysis:{phase:"quick",version:2,intent_version:1}})]));assert.equal(h.intake.phase,"reviewing");h.intake.observe(state([file("broken",{analysis:{phase:"complete",version:3,intent_version:1}})]));await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.calls.begin.length,1);
 });
 await check("connection and upload errors gate completion and recover",async()=>{
  const h=setup();h.intake.begin({batchId:"first"});h.intake.observe(state([file()],{connectionError:"Status unavailable"}));h.intake.settle("first");await tick();assert.equal(h.intake.phase,"error");assert.equal(h.calls.baseline.length,0);
  assert.equal(h.intake.retryAvailable,true);
  h.intake.observe(state([file()],{uploadErrors:[{name:"Missing.pdf",message:"Upload failed"}]}));await tick();assert.equal(h.intake.phase,"error");assert.equal(h.calls.question.length,0);
  assert.equal(h.intake.retryAvailable,false);
  h.intake.observe(state([file()]));await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.calls.begin.length,1);
 });
 await check("older active failed files block intake until parked or removed",async()=>{
  for(const action of ["parked","removed"]){
   const old={name:"Older.pdf",message:"Previously failed"},h=setup();h.intake.observe(state([file("older",{status:"error",analysis:{}})],{uploadErrors:[old]}));h.intake.begin({batchId:"new"});
   h.intake.observe(state([file("older",{status:"error",analysis:{}}),file("new")],{uploadErrors:[old]}));h.intake.settle("new");await tick();assert.equal(h.intake.phase,"error");assert.equal(h.calls.baseline.length,0,"All active files must satisfy server readiness before replacing the baseline");assert.equal(h.calls.question.length,0);
   const excluded=action==="removed"?file("older",{status:"error",archived:true,analysis:{}}):file("older",{status:"error",analysis:{phase:"error",disposition:"parked"}});
   h.intake.observe(state([excluded,file("new")],{uploadErrors:[old]}));await tick();assert.equal(h.calls.complete.length,1);assert.deepEqual(Array.from(h.calls.baseline[0].documents,file=>file.id),["new"]);assert.equal(h.calls.begin.length,1);
  }
 });
 await check("parked and removed failed files do not keep a batch stuck",async()=>{
  for(const action of ["parked","removed"]){
   const h=setup();h.intake.begin({batchId:"first"});h.intake.observe(state([file("failed",{status:"error",analysis:{}}),file("good")]));h.intake.settle("first");await tick();assert.equal(h.intake.phase,"error");
   const failed=action==="removed"?{...file("failed"),archived:true}:file("failed",{status:"error",analysis:{phase:"error",disposition:"parked"}});
   h.intake.observe(state([failed,file("good")]));await tick();assert.equal(h.calls.complete.length,1);assert.deepEqual(Array.from(h.calls.baseline[0].documents,file=>file.id),["good"]);
  }
 });
 await check("empty, unreadable and all-parked batches finish without fabricated question",async()=>{
  for(const documents of [[],[file("parked",{analysis:{phase:"deep",disposition:"parked"}})],[file("empty",{chunk_count:0,analysis:{phase:"complete",review_complete:false,disposition:"needs_reason"}})]]){
   const pause=deferred(),h=setup({begin:()=>pause.promise});h.intake.begin({batchId:"first"});h.intake.observe(state(documents));h.intake.settle("first");await tick();assert.equal(h.calls.empty.length,0,"Even an empty batch waits for voice drain");
   pause.resolve();await tick();assert.equal(h.calls.empty.length,1);assert.equal(h.calls.baseline.length,0);assert.equal(h.calls.question.length,0);assert.equal(h.intake.phase,"ready");
  }
 });
 await check("removing or parking every new file does not re-question historical evidence",async()=>{
  for(const action of ["removed","parked"]){
   const h=setup();h.intake.observe(state([file("historical")]));h.intake.begin({batchId:"new"});
   h.intake.observe(state([file("historical"),file("new",{analysis:{phase:"deep",version:2}})]));h.intake.settle("new");await tick();assert.equal(h.intake.phase,"reviewing");
   const excluded=action==="removed"?file("new",{archived:true}):file("new",{analysis:{phase:"complete",disposition:"parked"}});
   h.intake.observe(state([file("historical"),excluded]));await tick();assert.equal(h.calls.empty.length,1);assert.equal(h.calls.baseline.length,0);assert.equal(h.calls.question.length,0);assert.equal(h.intake.phase,"ready");
  }
 });
 await check("an interrupted upload generation can recover without a stale settled event",async()=>{
  const h=setup();h.intake.observe(state([]));h.intake.begin({batchId:"interrupted",names:["Interrupted.pdf"]});h.intake.observe(state([],{uploading:1,mutating:1}));await tick();
  h.intake.observe(state([],{generation:1,uploadErrors:[{name:"Interrupted.pdf",message:"Upload interrupted"}]}));await tick();assert.equal(h.intake.phase,"error","A suspended batch has no settled event; new generation must clear its pending batch ID");assert.equal(h.calls.baseline.length,0);
  h.intake.begin({batchId:"retry",names:["Interrupted.pdf"]});h.intake.observe(state([file("retried")],{generation:1,uploading:1,mutating:1}));await tick();assert.equal(h.calls.question.length,0);
  h.intake.observe(state([file("retried")],{generation:1}));h.intake.settle("retry");await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.calls.begin.length,1);assert.equal(h.intake.phase,"ready");
 });
 await check("generation changes cancel obsolete baseline and question work",async()=>{
  for(const stage of ["baseline","question"]){
   const pending=deferred(),h=setup({[stage]:()=>h.calls[stage].length===1?pending.promise:Promise.resolve(stage==="baseline"?{revision:"current"}:{question:"Current generation question"})});
   h.intake.observe(state([]));h.intake.begin({batchId:"first"});h.intake.observe(state([file()]));h.intake.settle("first");await tick();
   const oldSignal=h.calls[stage][0].signal;h.intake.observe(state([file()],{generation:1}));assert.equal(oldSignal.aborted,true,"The document generation is part of the evidence transaction identity");
   pending.resolve(stage==="baseline"?{revision:"stale"}:{question:"Stale question"});await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.intake.phase,"ready");assert.notEqual(h.calls.question.at(-1).baseline.revision,"stale");assert.notEqual(h.calls.complete[0].result.question,"Stale question");
  }
 });
 await check("baseline and followup failures can be retried without re-acknowledging",async()=>{
  for(const stage of ["baseline","question"]){
   let fail=true;const h=setup({[stage]:async()=>{if(fail)throw Error("Temporary "+stage+" failure");return stage==="baseline"?{revision:"retry"}:{question:"Recovered question"};}});h.intake.begin({batchId:"first"});h.intake.observe(state([file()]));h.intake.settle("first");await tick();
   assert.equal(h.intake.phase,"error");assert.equal(h.calls.complete.length,0);fail=false;h.intake.retry();await tick();assert.equal(h.calls.complete.length,1);assert.equal(h.calls.begin.length,1);assert.equal(h.intake.phase,"ready");
  }
 });
 await check("failed provider work stays paused across polls until an explicit retry",async()=>{
  for(const stage of ["baseline","question"]){
   let fail=true;const h=setup({[stage]:async()=>{if(fail)throw Error("OpenAI request timed out");return stage==="baseline"?{revision:"retry"}:{question:"Recovered question"};}});
   h.intake.begin({batchId:"first"});const snapshot=state([file()]);h.intake.observe(snapshot);h.intake.settle("first");await tick();
   assert.equal(h.intake.phase,"error");const calls=h.calls.baseline.length;fail=false;
   for(let i=0;i<5;i++){h.intake.observe(copy(snapshot));h.intake.settle("first");await tick();}
   h.intake.observe({...copy(snapshot),connectionError:"Status temporarily unavailable"});await tick();
   h.intake.observe(copy(snapshot));await tick();
   const metadata=copy(snapshot);metadata.documents[0].analysis.version++;h.intake.observe(metadata);await tick();
   assert.equal(h.calls.baseline.length,calls,"Polling, recovery and metadata must not repeat paid baseline work");assert.equal(h.calls.complete.length,0);assert.equal(h.intake.phase,"error");
   assert.equal(h.intake.error,"OpenAI request timed out");assert.equal(h.intake.retryAvailable,true);assert.equal(h.calls.begin.length,1);
   h.intake.retry();await tick();assert.equal(h.calls.baseline.length,calls+1);assert.equal(h.calls.complete.length,1);assert.equal(h.calls.begin.length,1);assert.equal(h.intake.phase,"ready");
  }
 });
 await check("explicit document changes can replace a failed provider run",async()=>{
  for(const action of ["intent","park","remove","upload"]){
   let fail=true;const h=setup({baseline:async()=>{if(fail)throw Error("OpenAI request timed out");return{revision:"changed"};}});
   h.intake.begin({batchId:"first"});const snapshot=state([file("one"),file("two")]);h.intake.observe(snapshot);h.intake.settle("first");await tick();assert.equal(h.intake.phase,"error");fail=false;
   const revised=copy(snapshot);
   if(action==="intent")revised.documents[0].analysis.intent_version++;
   if(action==="park")revised.documents[0].analysis.disposition="parked";
   if(action==="remove")revised.documents.splice(0,1);
   if(action==="upload"){h.intake.begin({batchId:"second"});revised.documents.push(file("three"));}
   h.intake.observe(revised);if(action==="upload")h.intake.settle("second");await tick();
   assert.equal(h.calls.baseline.length,2);assert.equal(h.calls.complete.length,1);assert.equal(h.calls.begin.length,1);assert.equal(h.intake.phase,"ready");
  }
 });
 await check("pause failure cannot commit a baseline or ask a question",async()=>{
  const h=setup({begin:async()=>{throw Error("Final transcript was not saved");}});h.intake.begin({batchId:"first"});h.intake.observe(state([file()]));h.intake.settle("first");await tick();assert.equal(h.intake.phase,"error");assert.match(h.intake.error,/Final transcript/);assert.equal(h.calls.baseline.length,0);assert.equal(h.calls.question.length,0);
 });
 await check("retry can recover a failed pause dependency",async()=>{
  let fail=true,acknowledgements=0;const h=setup({begin:async input=>{if(!input.retry)acknowledgements++;if(fail)throw Error("Voice stop temporarily failed");}});h.intake.begin({batchId:"first"});h.intake.observe(state([file()]));h.intake.settle("first");await tick();assert.equal(h.intake.phase,"error");
  fail=false;h.intake.retry();await tick();assert.equal(h.intake.phase,"ready","Retry must retry a rejected pause dependency rather than re-await the same rejected promise forever");assert.equal(h.calls.complete.length,1);assert.equal(h.calls.begin.length,2);assert.equal(h.calls.begin[1].retry,true);assert.equal(acknowledgements,1,"Retrying voice drain must not repeat the acknowledgement");
 });
 await check("a synchronous pause failure remains a recoverable intake error",async()=>{
  const h=setup({begin:()=>{throw Error("Pause failed synchronously");}});
  assert.doesNotThrow(()=>h.intake.begin({batchId:"first"}),"A UI lifecycle callback must not throw before Documents starts its guarded upload work");
  h.intake.observe(state([file()]));h.intake.settle("first");await tick();assert.equal(h.intake.phase,"error");assert.equal(h.calls.baseline.length,0);
 });
 await check("an old rejected pause cannot alter a new interview's retry dependency",async()=>{
  const old=deferred();let failBaseline=true;const h=setup({begin:()=>h.calls.begin.length===1?old.promise:Promise.resolve(),baseline:async()=>{if(failBaseline)throw Error("New baseline failed");return{revision:"recovered"};}});
  h.intake.begin({batchId:"old"});h.intake.observe(state([file("old")]));h.intake.settle("old");await tick();h.intake.reset();h.intake.observe(state([],{scope:"new_scope"}));
  h.intake.begin({batchId:"new"});h.intake.observe(state([file("new")],{scope:"new_scope"}));h.intake.settle("new");await tick();assert.equal(h.intake.phase,"error");assert.equal(h.calls.begin.length,2);
  old.reject(Error("Old voice session stopped late"));await tick();failBaseline=false;h.intake.retry();await tick();assert.equal(h.calls.begin.length,2,"An obsolete pause rejection must not mark the new cycle's successful pause as failed");assert.equal(h.calls.complete.length,1);
 });
 await check("metadata-only hooks never require uploaded File objects",async()=>{
  const h=setup();h.intake.begin({batchId:"first",names:["Source.pdf"]});h.intake.observe(state([file()]));h.intake.settle("first");await tick();
  assert.deepEqual(Object.keys(h.calls.begin[0]).sort(),["names","retry","signal"]);assert.deepEqual(Object.keys(h.calls.baseline[0]).sort(),["documents","signal"]);assert.deepEqual(Object.keys(h.calls.question[0]).sort(),["baseline","documents","signal"]);assert.equal(JSON.stringify(h.calls.complete).includes("rawFile"),false);
 });
 const failed=results.filter(result=>!result.passed);console.log(JSON.stringify({tests_passed:results.length-failed.length,tests_failed:failed.length,provider_calls:0,network_calls:0,physical_audio:false,failures:failed},null,2));if(failed.length)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
