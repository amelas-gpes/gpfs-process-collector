"use strict";
// What an Assets card says about the state of a file and of the workspace, checked against the real
// web/documents.js behind a synthetic DOM (the harness of test_documents_removed.cjs). No browser,
// provider, filesystem upload or real network.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const source=fs.readFileSync(path.join(__dirname,"..","web","documents.js"),"utf8");
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
class Element {
 constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.listeners={};this.attributes={};this.dataset={};this.className="";this.id="";this.hidden=false;this.open=false;this.disabled=false;this.value="";this._text="";this.classList={contains:name=>this.className.split(/\s+/).includes(name),add:name=>{this.className+=" "+name;},remove:name=>{this.className=this.className.split(/\s+/).filter(value=>value!==name).join(" ");}};}
 get textContent(){return this._text+this.children.map(child=>child.textContent).join("");}
 set textContent(value){this.replaceChildren();this._text=String(value);}
 append(...children){for(const child of children){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(item=>item!==child);child.parentElement=this;this.children.push(child);}}
 replaceChildren(...children){this.children.forEach(child=>child.parentElement=null);this.children=[];this._text="";this.append(...children);}
 setAttribute(name,value){this.attributes[name]=String(value);}
 getAttribute(name){return this.attributes[name]??null;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
 removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(item=>item!==fn);}
 dispatch(name,extra={}){for(const fn of this.listeners[name]||[])fn({target:this,preventDefault(){},...extra});}
 click(){if(!this.disabled)this.dispatch("click");}
 focus(){this.ownerDocument.activeElement=this;}
 scrollIntoView(){}
 contains(node){return walk(this).includes(node);}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}
 querySelectorAll(selector){return walk(this).filter(node=>node!==this&&matches(node,selector));}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
function walk(node){return[node,...node.children.flatMap(walk)];}
function matches(node,selector){
 if(selector.startsWith("."))return node.className.split(/\s+/).includes(selector.slice(1));
 if(selector==="[data-document-purpose]")return node.dataset.documentPurpose!==undefined;
 const match=selector.match(/^\[data-document-id="([^"]+)"\]$/);if(match)return node.dataset.documentId===match[1];
 return node.tagName===selector.toUpperCase();
}
function setup(request,config={},options={}){
 const document={activeElement:null};document.body=new Element("body",document);document.createElement=tag=>new Element(tag,document);document.createElementNS=(_,tag)=>new Element(tag,document);document.getElementById=id=>walk(document.body).find(node=>node.id===id)||null;
 const dropTarget=document.createElement("section");dropTarget.id="interview-view";document.body.append(dropTarget);
 const assets=document.createElement("div");assets.id="document-assets";dropTarget.append(assets);
 const timers=new Map();let timerId=0;const events=[],notices=[],calls=[],counts=[];let dirty=0;
 const window={document,addEventListener(){},removeEventListener(){}};
 const ctx={window,DOMException,AbortController,setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const api=window.CollectorDocuments.create({document,config:()=>({csrf_token:"test-csrf",...config}),getContext:()=>({context:{},turns:[],focus:"",current_question:""}),canUpload:()=>true,...options,
  requestJSON:(url,body,options)=>{calls.push({url,body});return request(url,body,options);},onEvent:event=>events.push(event),onDirty:()=>dirty++,notice:(...args)=>notices.push(args),onOpen(){},onCountChange:value=>counts.push(value)});
 const buttons=text=>api.body.querySelectorAll("button").filter(button=>button.textContent===text);
 return{api,document,events,notices,calls,counts,buttons,timers,get dirty(){return dirty;},card:()=>api.body.querySelector(".documents-card"),text:()=>api.assets.textContent};
}
function doc(overrides={}){return{id:"doc_1",name:"returns-log.csv",kind:"csv",size:1200,status:"ready",chunk_count:1,coverage:{indexed_units:5,total_units:5,limitations:[]},analysis:{phase:"complete",disposition:"relevant",summary:"Returns by reason.",version:3,intent_version:1,reviewed_chunks:1,total_chunks:1,sources:[]},...overrides};}
const settle=()=>new Promise(resolve=>setImmediate(resolve));

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
// ---- gap-upgrade-1: a file indexed by an earlier version of the app ----
const NOTICE="Process Collector was updated since this file was indexed, and its saved index predates the current completeness checks. It does not count as a full review until the file has been re-indexed.";
const outdated=(overrides={})=>doc({status:"partial",extraction_needs_reindex:true,reindex_check:{outcome:"pending"},coverage:{indexed_units:0,total_units:5,limitations:[NOTICE]},analysis:{phase:"reindex_required",review_complete:false,disposition:"relevant",summary:"Returns by reason.",version:3,intent_version:1,reviewed_chunks:1,total_chunks:1,sources:[]},...overrides});
await check("while the saved index is compared locally the card says so, offers no paid action and keeps polling",async()=>{
 const h=setup(async()=>({documents:[outdated()]}));h.api.scope="local-scope";h.api.setDocuments([outdated()],false);
 const card=h.card();
 assert.equal(card.querySelector(".documents-stage-label").textContent,"Checking after update");
 assert.equal(card.querySelector(".documents-stage").dataset.state,"working");
 const line=card.querySelector(".documents-reindex-status");
 assert.match(line.textContent,/^Process Collector was updated since this file was indexed\. It is being read again on this computer/);
 assert.match(line.textContent,/Nothing is sent to the AI provider for this check\./);
 assert.ok(!line.className.split(/\s+/).includes("documents-warning"),"A check in progress is not a warning");
 assert.equal(h.buttons("Re-index and review").length,0);assert.equal(h.buttons("Retry review").length,0);
 assert.equal(card.querySelector(".documents-reindex-note"),null,"No cost statement without a paid action on screen");
 assert.doesNotMatch(card.textContent,/units indexed|sections reviewed/);
 assert.ok(h.api.pending(),"The workspace polls at the short interval until the comparison is done");
 assert.deepEqual({...h.counts.at(-1)},{total:1,issues:0});
 assert.equal(h.api.liveStatus.textContent,"1 file. 1 checking after update");
 h.api.dispose();
});
await check("a file whose index differs is its own state: one coherent line, the reason, and a button named for what it does",async()=>{
 const h=setup(async()=>({document:doc()}));h.api.scope="local-scope";
 for(const [outcome,reason] of [["changed","the current version reads it differently"],["failed","it could not be read again on this computer"]]){
  h.api.setDocuments([outdated({reindex_check:{extraction_version:2,outcome}})],false);
  const card=h.card();
  assert.equal(card.querySelector(".documents-stage-label").textContent,"Needs re-indexing");
  assert.equal(card.querySelector(".documents-stage").dataset.state,"error");
  assert.equal(card.querySelector(".documents-stage-detail").textContent,"Indexed by an earlier version; not counted until it is confirmed.");
  assert.doesNotMatch(card.textContent,/0\/5 units indexed|1 of 1 sections reviewed/,"The card must not contradict itself");
  const line=card.querySelector(".documents-reindex-status");
  assert.ok(line.className.split(/\s+/).includes("documents-warning"));
  assert.ok(line.textContent.includes(`Its earlier review does not count as a full review, because ${reason}. Choose Re-index and review to bring it up to date.`),line.textContent);
  assert.equal(h.buttons("Re-index and review").length,1);assert.equal(h.buttons("Retry review").length,0);
  assert.equal(card.querySelector(".documents-reindex-note").querySelector("h4").textContent,"Before you choose Re-index and review");
  assert.match(card.querySelector(".documents-reindex-note").textContent,/paid re-read: it uses provider credits/);
  assert.equal(h.buttons("Save for later").length,1);
  assert.ok(!h.api.pending());assert.deepEqual({...h.counts.at(-1)},{total:1,issues:1});
 }
 h.buttons("Re-index and review")[0].click();await settle();
 assert.deepEqual(h.calls.map(call=>[call.url,call.body.action]),[["/api/documents/action","revisit"]]);
 h.api.dispose();
});
await check("an error left by an earlier review is shown beside the update sentence, never instead of it",async()=>{
 const h=setup(async()=>({}));h.api.scope="local-scope";
 h.api.setDocuments([outdated({reindex_check:{extraction_version:2,outcome:"changed"},analysis:{phase:"reindex_required",review_complete:false,disposition:"relevant",version:2,error:"Document review paused after an invalid response or service error. Revisit to retry."}})],false);
 const text=h.card().textContent;
 assert.match(text,/Document review paused after an invalid response or service error/);
 assert.match(text,/Process Collector was updated since this file was indexed\./);
 assert.equal(h.card().querySelector(".documents-stage-label").textContent,"Needs re-indexing");
 // A record saved by an earlier build, shown while the workspace cannot be reached: no check is running, so none is claimed.
 const saved=outdated({analysis:{phase:"error",review_complete:false,disposition:"relevant",version:1,error:"Saved extraction predates the current completeness checks. Revisit this file to re-index it before claiming a full review."}});delete saved.reindex_check;
 h.api.setDocuments([saved],false);
 assert.equal(h.card().querySelector(".documents-stage-label").textContent,"Needs re-indexing");assert.equal(h.buttons("Re-index and review").length,1);
 assert.match(h.card().querySelector(".documents-reindex-status").textContent,/because its saved index predates the current completeness checks/);
 // A file the earlier version could not read at all has nothing to compare.
 h.api.setDocuments([outdated({status:"error",error:"CSV must be UTF-8 or BOM-marked UTF-16; no lossy decoding was performed.",reindex_check:undefined})],false);
 assert.equal(h.card().querySelector(".documents-stage-label").textContent,"Could not read file");
 assert.match(h.card().querySelector(".documents-reindex-status").textContent,/Choose Re-index and review to read it with the current version\./);
 assert.equal(h.buttons("Re-index and review").length,1);
 // Saved for later: the label stays, the action is the one a parked file has.
 h.api.setDocuments([outdated({reindex_check:{extraction_version:2,outcome:"changed"},analysis:{phase:"reindex_required",disposition:"parked",version:4}})],false);
 assert.equal(h.card().querySelector(".documents-stage-label").textContent,"Saved for later");
 assert.match(h.card().querySelector(".documents-reindex-status").textContent,/Choose Revisit this file to bring it up to date\./);
 h.api.dispose();
});
await check("a current file, a paused review and an index made by a newer version are not described as outdated",async()=>{
 const h=setup(async()=>({}));h.api.scope="local-scope";h.api.setDocuments([doc()],false);
 assert.equal(h.card().querySelector(".documents-reindex-status"),null);assert.match(h.card().textContent,/5\/5 rows indexed\. 1 of 1 sections reviewed\./);
 assert.equal(h.api.attentionNote(),"");
 h.api.setDocuments([doc({analysis:{phase:"error",disposition:"relevant",version:1,error:"The review service is unavailable."}})],false);
 assert.equal(h.card().querySelector(".documents-reindex-status"),null);assert.equal(h.buttons("Retry review").length,1);assert.equal(h.buttons("Re-index and review").length,0);
 assert.equal(h.card().querySelector(".documents-stage-label").textContent,"Review paused");
 h.api.setDocuments([doc({indexed_by_newer_build:true})],false);
 assert.equal(h.card().querySelector(".documents-newer-index").textContent,"Indexed by a newer version of Process Collector. This version uses that index as it is.");
 assert.equal(h.card().querySelector(".documents-stage-label").textContent,"Ready to review");assert.equal(h.buttons("Re-index and review").length,0);
 h.api.dispose();
});
await check("the notice after opening a saved interview names files that are being checked or need attention",async()=>{
 const h=setup(async()=>({}));h.api.scope="local-scope";
 h.api.setDocuments([outdated(),outdated({id:"doc_2"}),doc({id:"doc_3"})],false);
 assert.equal(h.api.attentionNote()," 2 saved files are being checked again on this computer after an app update.");
 h.api.setDocuments([outdated({reindex_check:{extraction_version:2,outcome:"changed"}}),doc({id:"doc_3"})],false);
 assert.equal(h.api.attentionNote()," 1 saved file needs attention in Assets before the interview can be completed.");
 h.api.setDocuments([outdated(),doc({id:"doc_2",status:"error",error:"Unreadable."}),doc({id:"doc_3",analysis:{phase:"error",disposition:"relevant",version:1,error:"Paused."}})],false);
 assert.equal(h.api.attentionNote()," 1 saved file is being checked again on this computer after an app update. 2 saved files need attention in Assets before the interview can be completed.");
 const app=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
 assert.ok(app.includes('+(documentController?.attentionNote?.()||""),false,"opened",true);'),"The notice shown after opening a saved interview carries the note");
 h.api.dispose();
});

// ---- live-documents-13: the file slots of an interview, removed files included ----
const removedFile=index=>({id:`gone_${index}`,name:`old-${index}.csv`,kind:"csv",size:10});
const file=(name,size=10)=>({name,size});
await check("Assets counts used slots as the server does and names the removed files among them",async()=>{
 const reply={scope:"local-scope",documents:[doc(),doc({id:"doc_2",name:"second.csv"})],removed:[removedFile(1)],limit:{maximum:20,used:3,removed:1}};
 const h=setup(async url=>url==="/api/documents/session"?reply:{documents:reply.documents,removed:reply.removed,limit:reply.limit});
 assert.equal(h.api.usage.hidden,true,"Nothing is said about an empty workspace");assert.equal(h.api.usageText(),"");
 await h.api.ensureSession();
 assert.equal(h.api.usage.textContent,"3 of 20 file slots used, 1 by removed file.");assert.equal(h.api.usage.hidden,false);
 assert.equal(h.api.attachButton.disabled,false);assert.equal(h.api.attachButton.getAttribute("aria-describedby"),h.api.usage.id);
 assert.ok(h.api.assets.querySelector(".documents-usage")===h.api.usage,"The count is on screen in Assets");
 // What the page does before the next reply is counted at once and never lowers the count.
 await h.api.action(h.api.documents[0],"remove");
 assert.equal(h.api.usage.textContent,"3 of 20 file slots used, 2 by removed files.");
 h.api.setLimit({maximum:20,used:7,removed:2});assert.equal(h.api.usage.textContent,"7 of 20 file slots used, 2 by removed files.");
 h.api.setLimit(undefined);h.api.setLimit("7");assert.equal(h.api.used(),7,"A reply without a count keeps the last one");
 h.api.dispose();
});
await check("with every slot used Add files is unavailable and says why, although no file is listed",async()=>{
 // The audit's case: twenty files uploaded and removed. The page lists none of them as a file of the interview.
 const removed=Array.from({length:20},(_,index)=>removedFile(index));
 const reply={scope:"local-scope",documents:[],removed,limit:{maximum:20,used:20,removed:20}};
 const fetched=[];
 const h=setup(async()=>reply);h.api.options.fetch=async(...call)=>{fetched.push(call);throw new Error("no upload expected");};
 await h.api.ensureSession();
 assert.equal(h.api.documents.length,0);assert.equal(h.api.attachButton.disabled,true,"Add files stayed enabled with every slot used");
 assert.equal(h.api.usage.textContent,"20 of 20 file slots used, 20 by removed files. No more files can be added to this interview. Removed files stay on this computer and keep their slots: restore one to use it again.");
 await h.api.addFiles([file("returns-procedure.csv")]);
 assert.equal(fetched.length,0,"A file the server would refuse is not sent");
 assert.deepEqual(Array.from(h.api.uploadErrors,error=>error.message),["An interview can hold up to 20 files, and removed files keep their slots."]);
 assert.equal(h.api.uploadErrors[0].file,undefined,"There is no Retry upload for a file that cannot fit");
 // Restoring one changes nothing about the slots: it is a file of the interview again.
 h.api.setRemoved(removed.slice(1));h.api.setDocuments([doc({id:"gone_0"})],false);
 assert.equal(h.api.used(),20);assert.equal(h.api.attachButton.disabled,true);
 assert.match(h.api.usage.textContent,/^20 of 20 file slots used, 19 by removed files\. No more files can be added/);
 h.api.dispose();
});
await check("one slot short of the limit one more file is accepted, and a server without counts is counted by the page",async()=>{
 const sent=[];
 const listed=Array.from({length:18},(_,index)=>doc({id:`doc_${index}`}));
 const h=setup(async()=>({scope:"local-scope",documents:listed,removed:[removedFile(1)],limit:{maximum:20,used:19,removed:1}}));
 h.api.options.fetch=async(url,options)=>{sent.push(options.body.name);return{ok:true,json:async()=>({document:doc({id:"new_"+sent.length,name:options.body.name})})};};
 await h.api.ensureSession();assert.equal(h.api.attachButton.disabled,false);
 await h.api.addFiles([file("a.csv"),file("b.csv")]);
 assert.deepEqual(sent,["a.csv"]);assert.deepEqual(Array.from(h.api.uploadErrors,error=>error.name),["b.csv"]);
 assert.equal(h.api.used(),20);assert.equal(h.api.attachButton.disabled,true);
 assert.match(h.api.usage.textContent,/^20 of 20 file slots used, 1 by removed file\. No more files can be added to this interview\. Removed files stay/);
 h.api.dispose();
 const old=setup(async()=>({scope:"local-scope",documents:Array.from({length:20},(_,index)=>doc({id:`doc_${index}`})),removed:[]}));
 await old.api.ensureSession();
 assert.equal(old.api.limit,null);assert.equal(old.api.attachButton.disabled,true);
 assert.equal(old.api.usage.textContent,"20 of 20 file slots used. No more files can be added to this interview.");
 old.api.dispose();
});

// ---- gap-privacy-1: Remove and Start over do not erase, and the page says so ----
await check("the Remove control, the file notice and the start-over note all say that files stay on this computer",async()=>{
 const h=setup(async()=>({document:{...doc(),archived:true}}));h.api.scope="local-scope";
 assert.equal(h.api.keptFilesNote(),"","Nothing is said when the interview has no files");
 h.api.setDocuments([doc()],false);
 const remove=h.buttons("Remove from interview");
 assert.equal(remove.length,1);assert.equal(h.buttons("Remove").length,0,"The bare word reads as deletion");
 assert.equal(remove[0].getAttribute("aria-label"),"Remove returns-log.csv from this conversation. It is kept on this computer.");
 assert.equal(remove[0].title,"Kept on this computer. It can be restored from Removed files.");
 assert.match(h.api.assets.querySelector(".documents-assets-privacy").textContent,/Remove stops further review.*Permanently delete.*original and index/);
 assert.equal(h.api.keptFilesNote()," The file added to this interview stays on this computer: the app does not delete it.");
 h.api.setDocuments([doc(),doc({id:"doc_2"})],false);
 remove[0].click;await h.api.action(h.api.documents[0],"remove");
 assert.equal(h.api.documents.length,1);assert.equal(h.api.removed.length,1);
 assert.equal(h.api.keptFilesNote()," The 2 files added to this interview stay on this computer: the app does not delete them.","A removed file is still a kept file");
 assert.deepEqual(h.calls.map(call=>call.body.action),["remove"],"Remove stays one click; Restore undoes it");
 const app=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
 assert.ok(app.includes(':saveAdvice())+(documentController?.keptFilesNote?.()||""));'),"The question asked before replacing an interview names the files that stay");
 assert.ok(/const kept=documentController\?\.keptFilesNote[\s\S]{0,360}clearState\(\);focusWorkspace\("interview"\);notice\("Started over\."\+kept\)/.test(app),"Start over says so even when it has nothing to ask");
 h.api.dispose();
});

// ---- architecture-11: file kinds this computer's Python cannot read ----
await check("a kind whose reader is missing is announced, not offered by the picker and not uploaded",async()=>{
 const PDF="This computer cannot read PDF files: the Python that runs Process Collector has no usable pypdf package. Install the packages listed in requirements-documents.txt.";
 const XLS="This computer cannot read Excel workbook files: the Python that runs Process Collector has no usable openpyxl package.";
 const sent=[];
 const h=setup(async()=>({scope:"local-scope",documents:[],removed:[]}),{documents:{enabled:true,types:["png","csv"],unavailable:{pdf:PDF,xlsx:XLS,xlsm:XLS,exe:"not a kind of file the page knows",png:""}}});
 h.api.options.fetch=async(url,options)=>{sent.push(options.body.name);return{ok:true,json:async()=>({document:doc({id:"new_"+sent.length,name:options.body.name})})};};
 h.api.render();
 const warning=h.api.body.querySelector(".documents-unreadable-kinds");
 assert.ok(warning,"Assets says which files cannot be read before one is chosen");
 assert.deepEqual(Array.from(warning.children,child=>child.textContent),[PDF,XLS],"Each reason once, as the server gave it");
 assert.equal(h.api.input.accept,".png,.csv");
 await h.api.addFiles([file("procedure.pdf"),file("ledger.xlsx"),file("macro.XLSM"),file("stages.csv"),file("rates.png")]);
 assert.deepEqual(sent,["stages.csv","rates.png"]);
 assert.deepEqual(Array.from(h.api.uploadErrors,error=>[error.name,error.message]),[["procedure.pdf",PDF],["ledger.xlsx",XLS],["macro.XLSM",XLS]]);
 assert.ok(Array.from(h.api.uploadErrors).every(error=>error.file===undefined),"Retry upload cannot help until the package is installed");
 h.api.dispose();
 // A computer with every reader, and a server that does not say: nothing changes.
 for(const config of [{documents:{enabled:true,types:["pdf","png","xlsx","xlsm","csv"],unavailable:{}}},{},{documents:{unavailable:"none"}}]){
  const plain=setup(async()=>({scope:"local-scope",documents:[],removed:[]}),config);plain.api.render();
  assert.equal(plain.api.body.querySelector(".documents-unreadable-kinds"),null);assert.equal(plain.api.input.accept,".pdf,.png,.xlsx,.xlsm,.csv");
  plain.api.dispose();
 }
});


// ---- Add files follows state the page owns, which changes without the list being redrawn ----
await check("Add files is refreshed when the page leaves the example, opens a file or finishes a draft",async()=>{
 // The page resets the file list while the example is still open, then leaves the example.
 const page={example:true,draft:false};
 const h=setup(async()=>({documents:[]}),{},{canUpload:()=>!page.example&&!page.draft,
  uploadBlockedReason:()=>page.example?"Choose Start your own before adding a real file.":"Wait for the draft to finish, then add the file."});
 h.api.reset();
 assert.equal(h.api.attachButton.disabled,true);assert.equal(h.api.attachButton.title,"Choose Start your own before adding a real file.");
 page.example=false;
 assert.equal(h.api.attachButton.disabled,true,"Nothing redraws the list when the example closes");
 h.api.syncAttach();
 assert.equal(h.api.attachButton.disabled,false,"Add files stayed disabled after Start your own");assert.equal(h.api.attachButton.title,"Add files");
 // A draft in flight blocks uploads, and its end allows them again.
 page.draft=true;h.api.syncAttach();
 assert.equal(h.api.attachButton.disabled,true);assert.equal(h.api.attachButton.title,"Wait for the draft to finish, then add the file.");
 page.draft=false;h.api.syncAttach();
 assert.equal(h.api.attachButton.disabled,false);assert.equal(h.api.attachButton.title,"Add files");
 // A full interview stays full whatever the page allows.
 h.api.scope="local-scope";h.api.setDocuments(Array.from({length:20},(_,index)=>doc({id:`doc_${index}`})),false);h.api.syncAttach();
 assert.equal(h.api.attachButton.disabled,true);
 h.api.dispose();h.api.syncAttach();
 // The page refreshes it with its own controls.
 const app=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
 const controls=app.slice(app.indexOf("function updateControls() {"),app.indexOf("function updateControls() {")+400);
 assert.match(controls,/documentController\?\.syncAttach\?\.\(\)/,"updateControls no longer refreshes Add files");
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
