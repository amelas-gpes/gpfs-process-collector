"use strict";
// Which reference files the app asks the server to read, and what it tells the
// participant about files the interviewer has not received. Actual app state,
// request transport and intake controller; display and network are faked.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
let harness=fs.readFileSync(path.join(__dirname,"test_agent_experience.cjs"),"utf8").split("let passed=0;")[0];
assert.ok(harness.includes("function setup()"));
harness=harness.replace('const flush=', 'const intake=fs.readFileSync(path.join(__dirname,"../web/document-intake.js"),"utf8");\nconst flush=');
harness=harness.replace('updateControls=()=>{updatePresence();};', 'const realUpdateControls=updateControls; updateControls=()=>{updatePresence();}; renderCoverage=()=>{}; renderWorkingMap=()=>{}; updateSaveHint=()=>{}; updateConversationControls=()=>{}; updateDocumentIntakeUI=()=>{};');
// The hook is exported only where the app has it, so that against an app without it every case
// still runs and fails on its own assertion instead of the whole file failing in setup.
harness=harness.replace('setTeam:value=>', 'startIntake:()=>{documentIntake=createDocumentIntake();return documentIntake;},syncDocumentReading:typeof syncDocumentReading==="function"?syncDocumentReading:undefined,checkControls:realUpdateControls,setTeam:value=>');
harness=harness.replace('vm.runInContext(source,context,', 'vm.runInContext(intake,context,{filename:"document-intake.js"});vm.runInContext(source,context,');
harness+='\nmodule.exports={setup,approved,response,flush};';
const exported={exports:{}};
vm.runInNewContext(harness,{require,__dirname,module:exported,console,Buffer,Blob,DataView,Uint8Array,Float32Array,TextEncoder,Date,JSON,AbortController,DOMException},{filename:"document-reading-harness.cjs"});
const {setup,approved,response,flush}=exported.exports;
const file=(id,name,overrides={})=>({id,name,status:"ready",chunk_count:2,archived:false,analysis:{phase:"complete",disposition:"relevant",intent_version:0,version:2,summary:"Reference."},...overrides});
const excerpt=id=>({id:id+"_p1",document_id:id,name:id+".csv",label:"Rows 1-2",text:"Documented reference rows."});
function documentsSetup(files){
 const h=setup(),reports=[];h.files=files;h.reports=reports;
 h.t.state.config.agent_team={enabled:false};h.t.state.config.api_configured=true;
 h.t.state.turns=[{id:"t001",role:"assistant",text:"What starts this work?"},{id:"t002",role:"user",text:"A clerk logs the return."}];
 const state=()=>JSON.parse(JSON.stringify({scope:"scope-one",generation:1,documents:h.files,uploading:0,mutating:0,uploadErrors:[]}));
 h.t.setDocuments({exportState:state,lifecycle:state,setReading:report=>reports.push(JSON.parse(JSON.stringify(report))),render(){},refresh(){}});
 h.sent=url=>h.calls.filter(call=>call.url===url).map(call=>JSON.parse(call.options.body));
 const report=h.t.syncDocumentReading;h.sync=()=>{if(report)report();};
 return h;
}
const asked=body=>(body.document_required_ids||[]).join();
// Every case runs and reports its own failure; one failing case does not hide the others.
let passed=0;const failures=[];async function check(name,fn){try{await fn();passed++;}catch(error){failures.push(name+": "+(error&&error.message||error));}}
(async()=>{
await check("every request asks for the ready files the interviewer has not received",async()=>{
 const h=documentsSetup([file("doc_read","Read.csv"),file("doc_unread","Unread.csv"),file("doc_partial","Partial.pdf",{status:"partial"}),
  file("doc_retained","Revisited.csv"),file("doc_parked","Later.csv",{analysis:{phase:"complete",disposition:"parked"}}),
  file("doc_pending","Pending.csv",{status:"indexing",chunk_count:0}),file("doc_removed","Removed.csv",{archived:true})]);
 h.t.state.documentEvidence=[excerpt("doc_read"),{...excerpt("doc_retained"),retained_only:true}];
 assert.equal(asked(h.t.snapshot()),"doc_unread,doc_partial,doc_retained");
 assert.equal(h.t.snapshot("close").document_source_ids.length,0);
 h.t.state.documentEvidence=[excerpt("doc_read"),excerpt("doc_unread"),excerpt("doc_partial"),excerpt("doc_retained")];
 assert.equal(Object.hasOwn(h.t.snapshot(),"document_required_ids"),false);
 h.files=Array.from({length:25},(_,index)=>file("doc_many"+index,"Many.csv"));assert.equal(h.t.snapshot().document_required_ids.length,20);
});
await check("the file list is told what has been read and how many files the latest request left out",async()=>{
 const h=documentsSetup([file("doc_read","Read.csv"),file("doc_unread","Unread.csv"),file("doc_parked","Later.csv",{analysis:{phase:"complete",disposition:"parked"}})]);
 h.t.state.documentEvidence=[excerpt("doc_read")];h.sync();
 assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_read"],omitted:0,sent:null}));
 h.route(url=>url==="/api/draft"?response({draft:null,document_reading:{omitted_documents:3,documents:[{id:"doc_read",included_chunks:2,total_chunks:2},{id:"doc_unread",included_chunks:0,total_chunks:4},null,{included_chunks:1}]}}):Promise.reject(Error(url)));
 await h.t.request("/api/draft",h.t.snapshot());
 assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_read"],omitted:3,sent:["doc_read"]}));
 // Evidence applied by a later response is picked up the next time the controls refresh.
 h.t.state.documentEvidence=[excerpt("doc_read"),excerpt("doc_unread")];h.node("start-interview").firstElementChild={textContent:""};h.t.checkControls();
 assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_read","doc_unread"],omitted:3,sent:["doc_read"]}));
 const before=h.reports.length;h.t.checkControls();assert.equal(h.reports.length,before,"Unchanged evidence must not be reported again");
 // A new interview does not inherit the previous interview's count.
 h.t.state.generation++;h.sync();assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_read","doc_unread"],omitted:0,sent:null}));
 h.route(url=>response({document_reading:{omitted_documents:"many"}}));await h.t.request("/api/draft",h.t.snapshot());assert.equal(h.reports.at(-1).omitted,0);assert.equal(h.reports.at(-1).sent,null);
});
await check("the file list is told how many cited excerpts the latest request could not read again",async()=>{
 const h=documentsSetup([file("doc_read","Read.csv")]);h.t.state.documentEvidence=[excerpt("doc_read")];
 const reading=extra=>({omitted_documents:0,documents:[{id:"doc_read",included_chunks:12,total_chunks:40}],...extra});
 h.route(()=>response({draft:null,document_reading:reading({omitted_prior_sources:9})}));await h.t.request("/api/draft",h.t.snapshot());
 assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_read"],omitted:0,sent:["doc_read"],carried:9}));
 // The count belongs to the latest request only, and a malformed value is not shown.
 for(const value of [0,-2,"9",2.5,null]){
  h.route(()=>response({draft:null,document_reading:reading({omitted_prior_sources:9})}));await h.t.request("/api/draft",h.t.snapshot());assert.equal(h.reports.at(-1).carried,9);
  h.route(()=>response({draft:null,document_reading:reading({omitted_prior_sources:value})}));await h.t.request("/api/draft",h.t.snapshot());
  assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_read"],omitted:0,sent:["doc_read"]}));
 }
 h.route(()=>response({draft:null,document_reading:reading({omitted_prior_sources:4})}));await h.t.request("/api/draft",h.t.snapshot());assert.equal(h.reports.at(-1).carried,4);
 h.route(()=>response({draft:null,document_reading:reading({})}));await h.t.request("/api/draft",h.t.snapshot());assert.equal(Object.hasOwn(h.reports.at(-1),"carried"),false);
 // A new interview does not inherit the previous interview's count.
 h.route(()=>response({draft:null,document_reading:reading({omitted_prior_sources:4})}));await h.t.request("/api/draft",h.t.snapshot());
 h.t.state.generation++;h.sync();assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_read"],omitted:0,sent:null}));
});
await check("an intake asks for its own files in the baseline and again in the follow-up",async()=>{
 const h=documentsSetup([file("doc_old","Old.csv")]);h.t.state.documentEvidence=[excerpt("doc_old")];
 const intake=h.t.startIntake(),listing=()=>({scope:"scope-one",generation:1,documents:h.files,uploading:0,mutating:0,uploadErrors:[]});intake.observe(listing());
 h.route(url=>url==="/api/workflow"?response({workflow:{title:"Returns",steps:[],connections:[],open_questions:[]},document_evidence:[excerpt("doc_old"),excerpt("doc_new")],document_reading:{omitted_documents:0,documents:[]}}):
  url==="/api/interview"?response(approved("Is the limit in New.csv still current?")):Promise.reject(Error(url)));
 intake.begin({documentId:"doc_new",names:["New.csv"]});
 h.files=[file("doc_old","Old.csv"),file("doc_new","New.csv")];intake.observe(listing());
 for(let i=0;i<8&&intake.active;i++)await flush();
 assert.equal(intake.phase,"ready",intake.error);
 const baseline=h.sent("/api/workflow"),followup=h.sent("/api/interview");
 assert.equal(baseline.length,1);assert.equal(asked(baseline[0]),"doc_new");
 // By the follow-up the file has been read, so only the intake still names it.
 assert.equal(followup.length,1);assert.equal(followup[0].action,"document_followup");assert.equal(asked(followup[0]),"doc_new");
 assert.equal(h.t.state.turns.at(-1).text,"Is the limit in New.csv still current?");assert.equal(h.notices.filter(item=>item.error).length,0);
 assert.equal(Object.hasOwn(h.t.snapshot(),"document_required_ids"),false);
 // While the intake worked, the list treated its files as being read; afterwards it reports the evidence.
 assert.ok(h.reports.some(report=>report.read.join()==="doc_old,doc_new"));assert.equal(h.reports.at(-1).read.join(),"doc_old,doc_new");
});
await check("an intake whose file was not in the update says so instead of preparing a follow-up",async()=>{
 const h=documentsSetup([file("doc_old","Old.csv")]);h.t.state.documentEvidence=[excerpt("doc_old")];
 const intake=h.t.startIntake(),listing=()=>({scope:"scope-one",generation:1,documents:h.files,uploading:0,mutating:0,uploadErrors:[]});intake.observe(listing());
 h.route(url=>url==="/api/workflow"?response({workflow:{title:"Returns",steps:[],connections:[],open_questions:[]},document_evidence:[excerpt("doc_old")],document_reading:{omitted_documents:0,documents:[{id:"doc_new",included_chunks:0,total_chunks:4}]}}):Promise.reject(Error(url)));
 intake.begin({documentId:"doc_new",names:["New.csv"]});h.files=[file("doc_old","Old.csv"),file("doc_new","New.csv")];intake.observe(listing());
 for(let i=0;i<8&&intake.phase!=="error";i++)await flush();
 assert.equal(intake.phase,"error");assert.match(intake.error,/did not receive readable text from New\.csv in this update/);assert.match(intake.error,/Not yet read in this interview/);
 assert.equal(h.sent("/api/interview").length,0);assert.equal(asked(h.sent("/api/workflow")[0]),"doc_new");
 // The failed intake no longer counts as reading the file (the app refreshes its controls on
 // every intake status change), and the next request asks for it again.
 assert.equal(h.reports.at(-1).read.join(),"doc_old,doc_new");h.node("start-interview").firstElementChild={textContent:""};h.t.checkControls();
 assert.equal(h.reports.at(-1).read.join(),"doc_old");assert.equal(asked(h.t.snapshot()),"doc_new");
});
await check("while an intake is reading, what an earlier request left out is not shown against the new files",async()=>{
 const h=documentsSetup([file("doc_old","Old.csv")]);h.t.state.documentEvidence=[excerpt("doc_old")];
 h.route(()=>response({document_reading:{omitted_documents:2,documents:[{id:"doc_old",included_chunks:1,total_chunks:1}]}}));await h.t.request("/api/draft",h.t.snapshot());
 assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_old"],omitted:2,sent:["doc_old"]}));
 const intake=h.t.startIntake(),listing=()=>({scope:"scope-one",generation:1,documents:h.files,uploading:0,mutating:0,uploadErrors:[]});intake.observe(listing());
 h.route(()=>new Promise(()=>{}));intake.begin({documentId:"doc_new",names:["New.csv"]});h.files=[file("doc_old","Old.csv"),file("doc_new","New.csv")];intake.observe(listing());await flush();
 assert.equal(intake.phase,"baseline");h.sync();
 assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_old","doc_new"],omitted:0,sent:null}));
 intake.reset();h.sync();assert.equal(JSON.stringify(h.reports.at(-1)),JSON.stringify({read:["doc_old"],omitted:2,sent:["doc_old"]}));
});
await check("an intake with several files continues when only some were read, and names the others",async()=>{
 const h=documentsSetup([]);
 const intake=h.t.startIntake(),listing=()=>({scope:"scope-one",generation:1,documents:h.files,uploading:0,mutating:0,uploadErrors:[]});intake.observe(listing());
 h.route(url=>url==="/api/workflow"?response({workflow:{title:"Returns",steps:[],connections:[],open_questions:[]},document_evidence:[excerpt("doc_a")]}):
  url==="/api/interview"?response(approved("Which of these do you use?")):Promise.reject(Error(url)));
 intake.begin({batchId:"upload_1",names:["A.csv","B.csv"]});h.files=[file("doc_a","A.csv"),file("doc_b","B.csv")];intake.include("doc_a");intake.include("doc_b");intake.settle("upload_1");intake.observe(listing());
 for(let i=0;i<8&&intake.active;i++)await flush();
 assert.equal(intake.phase,"ready",intake.error);assert.equal(asked(h.sent("/api/workflow")[0]),"doc_a,doc_b");
 assert.equal(asked(h.sent("/api/interview")[0]),"doc_b,doc_a");
 const warning=h.notices.filter(item=>item.error).map(item=>item.message).join();assert.match(warning,/did not receive readable text from B\.csv in this update/);assert.doesNotMatch(warning,/A\.csv/);
});
for(const failure of failures)console.error("FAIL "+failure);
if(failures.length)process.exitCode=1;
console.log(JSON.stringify({tests_passed:passed,tests_failed:failures.length,provider_calls:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
