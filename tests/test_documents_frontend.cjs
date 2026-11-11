"use strict";
// Document UI/lifecycle boundary tests: no browser, provider, filesystem upload or real network.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const source=fs.readFileSync(path.join(__dirname,"..","web","documents.js"),"utf8");
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
class Element {
 constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.listeners={};this.attributes={};this.dataset={};this.className="";this.id="";this.hidden=false;this.open=false;this.value="";this._text="";this.clicks=0;this.classList={contains:name=>this.className.split(/\s+/).includes(name),add:name=>{this.className+=" "+name;},remove:name=>{this.className=this.className.split(/\s+/).filter(value=>value!==name).join(" ");}};}
 get textContent(){return this._text+this.children.map(child=>child.textContent).join("");}
 set textContent(value){this.replaceChildren();this._text=String(value);}
 get isConnected(){let node=this;while(node.parentElement)node=node.parentElement;return node===this.ownerDocument.body;}
 append(...children){for(const child of children){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(item=>item!==child);child.parentElement=this;this.children.push(child);}}
 replaceChildren(...children){this.children.forEach(child=>child.parentElement=null);this.children=[];this._text="";this.append(...children);}
 setAttribute(name,value){this.attributes[name]=String(value);}
 getAttribute(name){return this.attributes[name]??null;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
 removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(item=>item!==fn);}
 dispatch(name,extra={}){for(const fn of this.listeners[name]||[])fn({target:this,preventDefault(){},...extra});}
 click(){this.clicks++;this.dispatch("click");}
 focus(){this.ownerDocument.activeElement=this;}
 setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
 scrollIntoView(){this.scrolled=true;}
 contains(node){return walk(this).includes(node);}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}
 showModal(){this.open=true;this.focus();}
 close(){this.open=false;this.dispatch("close");}
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
function setup({request,fetch,getContext,canUpload,inline=false}={}){
 const document={activeElement:null};document.body=new Element("body",document);document.createElement=tag=>new Element(tag,document);document.createElementNS=(_,tag)=>new Element(tag,document);document.getElementById=id=>walk(document.body).find(node=>node.id===id)||null;
 const dropTarget=document.createElement("section");dropTarget.id="interview-view";document.body.append(dropTarget);
 for(const id of inline?["document-assets"]:["document-controls","document-strip","documents-dialog"]){const node=document.createElement(id.endsWith("dialog")?"dialog":"div");node.id=id;(id.endsWith("dialog")?document.body:dropTarget).append(node);}
 const timers=new Map();let timerId=0;const events=[],notices=[],jsonCalls=[],uploads=[],counts=[];let dirty=0,opened=0,discussed=0;
 const listeners={},window={document,addEventListener:(name,fn)=>listeners[name]=fn,removeEventListener:name=>delete listeners[name]};
 const ctx={window,DOMException,AbortController,setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const api=window.CollectorDocuments.create({document,config:()=>({csrf_token:"test-csrf"}),getContext:getContext||(()=>({context:{},turns:[],focus:"Intake",current_question:"What starts the work?"})),canUpload:canUpload||(()=>true),
 requestJSON:(...args)=>{jsonCalls.push(args);return request?request(...args):Promise.resolve({scope:"local-scope",documents:[]});},fetch:async(...args)=>{uploads.push(args);return fetch?fetch(...args):{ok:true,json:async()=>({document:doc()})};},
 onEvent:event=>events.push(event),onDirty:()=>dirty++,notice:(...args)=>notices.push(args),onOpen:()=>opened++,onDiscuss:()=>discussed++,onCountChange:value=>counts.push(value)});
 return{api,document,dropTarget,events,notices,jsonCalls,uploads,timers,listeners,counts,get opened(){return opened;},get discussed(){return discussed;},get dirty(){return dirty;},findText:(tag,text)=>walk(document.body).find(node=>node.tagName===tag.toUpperCase()&&node.textContent===text)};
}
function doc(overrides={}){return{id:"doc_1",name:"Procedure.pdf",kind:"pdf",size:1200,status:"ready",analysis:{phase:"complete",disposition:"relevant",summary:"Reported procedure.",version:1,sources:[]},...overrides};}
function response(document){return{ok:true,json:async()=>({document})};}
(async()=>{
 let passes=0;
 {
  const h=setup({inline:true});h.api.setDocuments([doc({coverage:{indexed_units:3,total_units:3},analysis:{phase:"complete",disposition:"relevant",summary:"Some sections have not yet been reviewed.",summary_basis:"initial_review",summary_basis_note:"This overview was written from the initial selection; current coverage is separate.",summary_at_review_version:1,reviewed_chunks:3,total_chunks:3,version:4,limitations:["Current detail still needs participant confirmation."]}})],false);h.api.open("doc_1");
  assert.equal(h.api.body.querySelector(".documents-overview").querySelector("h4").textContent,"Initial overview");assert.match(h.api.body.querySelector(".documents-overview").textContent,/initial selection/);assert.match(h.api.body.querySelector(".documents-stage-detail").textContent,/3 of 3 sections reviewed/);assert.match(h.api.body.querySelector(".documents-summary").textContent,/not yet been reviewed/);assert.match(h.api.body.querySelector(".documents-limitations").textContent,/participant confirmation/);h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({inline:true,request:()=>pending.promise});h.api.scope="local-scope";h.api.setDocuments([doc(),doc({id:"doc_2",name:"Second.pdf"})],false);
  h.api.body.querySelectorAll(".document-control").find(button=>JSON.parse(button.dataset.documentControl)[1]==="remove").focus();
  const removing=h.api.action(h.api.documents[0],"remove");assert.equal(h.document.activeElement.dataset.documentId,"doc_1","Pending removal keeps keyboard focus on the file card");pending.resolve({removed:true});await removing;assert.equal(h.document.activeElement.dataset.documentId,"doc_2","Removing a file focuses a remaining file");h.api.body.querySelectorAll(".document-control").find(button=>JSON.parse(button.dataset.documentControl)[1]==="remove").focus();await h.api.action(h.api.documents[0],"remove");assert.equal(h.document.activeElement,h.api.attachButton,"Removing the final file focuses Add files");h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({inline:true,request:()=>pending.promise});h.api.scope="local-scope";h.api.setDocuments([doc()],false);h.api.body.querySelectorAll(".document-control").find(button=>JSON.parse(button.dataset.documentControl)[1]==="remove").focus();const removing=h.api.action(h.api.documents[0],"remove");
  const composer=h.document.createElement("textarea");h.dropTarget.append(composer);composer.focus();pending.resolve({removed:true});await removing;assert.equal(h.document.activeElement,composer,"A completed removal must not steal focus after the user moves to their reply");h.api.dispose();passes++;
 }
 {
  const h=setup({inline:true}),questions=[{id:"q1",text:"Who checks the payment?",sources:[{source_id:"p1",label:"Page 1"}]},{id:"q2",text:"Who releases the payment?",sources:[{source_id:"p1",label:"Page 1"}]}];
  const file=doc({analysis:{phase:"complete",disposition:"relevant",summary:"Payment review",sources:[{source_id:"p1",label:"Page 1"}],questions}});h.api.setDocuments([file],false);h.api.open(file.id);
  for(const action of ["remove","park","source","discuss"]){
   const controls=h.api.body.querySelectorAll(".document-control").filter(button=>JSON.parse(button.dataset.documentControl)[1]===action),control=controls.at(-1),key=control.dataset.documentControl;control.focus();h.api.render();
   assert.notEqual(h.document.activeElement,control);assert.equal(h.document.activeElement.dataset.documentControl,key,`${action} keyboard focus must survive polling`);assert.equal(h.document.activeElement.isConnected,true);
  }
  const discuss=h.api.body.querySelectorAll(".document-control").find(button=>JSON.parse(button.dataset.documentControl)[1]==="discuss"&&JSON.parse(button.dataset.documentControl)[2].includes("q2"));discuss.focus();const key=discuss.dataset.documentControl;
  h.api.setDocuments([{...file,analysis:{...file.analysis,questions:[questions[1],questions[0]]}}],false);assert.equal(h.document.activeElement.dataset.documentControl,key,"Question reordering must retain the same question, not its former position");
  h.api.dispose();passes++;
 }
 {
  for(const reject of [false,true]){
   const pending=deferred(),h=setup({inline:true,request:()=>pending.promise});h.api.scope="local-scope";const file=doc();h.api.setDocuments([file],false);
   const read=h.api.openSource(file,{source_id:"s1"});assert.equal(h.document.activeElement,h.api.sourceHeading,"An explicit source action focuses its loading heading immediately");
   const composer=h.document.createElement("textarea");h.dropTarget.append(composer);composer.value="Continue my answer";composer.focus();
   if(reject)pending.reject(Error("Source unavailable"));else pending.resolve({source:{text:"Source loaded"}});await read;
   assert.equal(h.document.activeElement,composer,"An asynchronous source result must not steal focus from typing in the conversation");assert.equal(composer.value,"Continue my answer");h.api.dispose();
  }passes++;
 }
 {
  const h=setup({inline:true}),ready=doc(),needsPurpose=doc({id:"doc_2",name:"Other.pdf",analysis:{phase:"quick",disposition:"needs_reason"}});h.api.setDocuments([ready,needsPurpose],false);
  let cards=h.api.body.querySelectorAll(".documents-card"),toggle=cards[0].querySelector(".documents-detail-toggle");assert.equal(toggle.getAttribute("aria-expanded"),"false");assert.equal(cards[0].querySelector(".documents-detail-content").hidden,true);assert.equal(cards[1].querySelector(".documents-detail-content").hidden,false,"Files awaiting direction expose the purpose form immediately");
  toggle.focus();toggle.click();assert.equal(toggle.getAttribute("aria-expanded"),"true");h.api.render();cards=h.api.body.querySelectorAll(".documents-card");toggle=cards[0].querySelector(".documents-detail-toggle");assert.equal(cards[0].querySelector(".documents-detail-content").hidden,false);assert.equal(h.document.activeElement,toggle,"Polling retains disclosure focus and expansion");
  toggle.click();h.api.render();assert.equal(h.api.body.querySelector(".documents-detail-content").hidden,true);h.api.open("doc_1");assert.equal(h.api.body.querySelector(".documents-detail-content").hidden,false,"Evidence links reveal the selected file's details");
  h.api.reset();h.api.setDocuments([ready],false);assert.equal(h.api.body.querySelector(".documents-detail-content").hidden,true);h.api.dispose();passes++;
 }
 {
  const h=setup({inline:true});assert.equal(h.document.getElementById("documents-dialog"),null);assert.equal(h.document.getElementById("document-strip"),null);assert.equal(h.document.getElementById("document-controls"),null);
  assert.equal(h.api.assets.querySelectorAll("input").length,1);assert.equal(h.findText("button","Add files"),h.api.attachButton);assert.equal(h.counts.at(-1).total,0);
  h.api.setDocuments([doc()],false);assert.equal(h.counts.at(-1).total,1);assert.equal(h.api.assets.querySelectorAll(".documents-card").length,1);assert.equal(h.api.assets.querySelectorAll(".document-chip").length,0);
  const before=h.api.exportState();h.api.open("doc_1");assert.equal(h.opened,1);assert.equal(h.document.activeElement.dataset.documentId,"doc_1");assert.equal(h.document.activeElement.scrolled,true);h.api.render();assert.equal(h.document.activeElement,h.api.body.querySelector(".documents-card"));assert.deepEqual(h.api.exportState(),before,"Opening Assets only changes presentation");h.api.dispose();assert.equal(h.api.assets.children.length,0);passes++;
 }
 {
  const pending=deferred(),h=setup({inline:true,fetch:()=>pending.promise});await h.api.addFiles([{name:"invalid.exe",size:12}]);assert.equal(h.opened,1);assert.equal(h.counts.at(-1).issues,1);assert.equal(h.jsonCalls.length,0);assert.match(h.api.body.textContent,/Choose a PDF/);
  const upload=h.api.addFiles([{name:"Reference.pdf",size:12}]);await tick();assert.equal(h.opened,2);assert.equal(h.counts.at(-1).total,1);assert.match(h.api.body.textContent,/Uploading/);pending.resolve(response(doc()));await upload;
  assert.equal(h.counts.at(-1).total,1);assert.equal(h.api.assets.querySelectorAll(".documents-card").length,1);assert.equal(h.api.uploads.length,0);h.api.reset();assert.equal(h.counts.at(-1).total,0);assert.equal(h.counts.at(-1).issues,0);h.api.dispose();passes++;
 }
 {
  const h=setup({inline:true,request:async()=>({source:{label:"Page 2",text:"Source text"}})});h.api.scope="local-scope";const file=doc({analysis:{phase:"complete",disposition:"needs_reason",sources:[{source_id:"s1",label:"Page 2"}]}});h.api.setDocuments([file],false);
  let input=h.api.body.querySelector("[data-document-purpose]");input.value="Check approval controls";input.focus();input.setSelectionRange(2,8);h.api.body.scrollTop=60;h.api.render();input=h.api.body.querySelector("[data-document-purpose]");assert.equal(input.value,"Check approval controls");assert.equal(h.document.activeElement,input);assert.equal(input.selectionStart,2);assert.equal(h.api.body.scrollTop,60);
  await h.api.openSource(file,{source_id:"s1",label:"Page 2"});assert.equal(h.document.activeElement,h.api.sourceHeading);assert.equal(h.api.sourceHeading.scrolled,true);assert.match(h.api.body.textContent,/Source text/);h.findText("button","Close source").click();assert.equal(h.document.activeElement.dataset.documentSource,"doc_1:s1");assert.equal(h.api.body.querySelector("[data-document-purpose]").value,"Check approval controls");h.api.dispose();passes++;
 }
 {
  const h=setup({inline:true});const file=doc(),question={id:"q1",text:"Who approves this?"};h.api.setDocuments([file],false);h.api.options.canDiscuss=()=>false;h.api.discuss(file,question);assert.equal(h.discussed,0);assert.equal(h.events.length,0);
  h.api.options.canDiscuss=()=>true;h.api.discuss(file,question);assert.equal(h.discussed,1);assert.equal(h.events.at(-1).type,"question");assert.equal(h.api.documents.length,1);h.api.dispose();passes++;
 }
 {
  const h=setup({inline:true}),sheet=h.document.createElement("dialog");sheet.open=true;h.document.body.append(sheet);sheet.append(h.api.assets);const transfer={types:["Files"],files:[{name:"mobile.pdf",size:20}],items:[]};
  h.listeners.drop({target:h.api.attachButton,dataTransfer:transfer,preventDefault(){}});await tick();assert.equal(h.uploads.length,1,"The relocated mobile Assets panel remains a file drop target");assert.equal(h.opened,1);h.api.dispose();assert.equal(h.listeners.drop,undefined);passes++;
 }
 {
  const pending=deferred(),h=setup({inline:true,request:()=>pending.promise});h.api.scope="local-scope";const file=doc();h.api.setDocuments([file],false);const read=h.api.openSource(file,{source_id:"s1"});h.api.assets.hidden=true;const other=h.document.createElement("button");h.document.body.append(other);other.focus();pending.resolve({source:{text:"Read later"}});await read;assert.equal(h.document.activeElement,other,"A source finishing after the tab changed must not steal focus into the hidden Assets panel");h.api.dispose();passes++;
 }
 {
  const h=setup(),file={name:"Dropped procedure.pdf",size:1200},transfer={types:["Files"],files:[file],items:[]};let prevented=0,adding;const addFiles=h.api.addFiles.bind(h.api);h.api.addFiles=files=>(adding=addFiles(files));
  h.dropTarget.dispatch("dragenter",{dataTransfer:transfer,preventDefault(){prevented++;}});assert.equal(h.api.dropOverlay.hidden,false);assert.match(h.api.dropOverlay.textContent,/Drop files into this conversation/);
  h.dropTarget.dispatch("dragenter",{target:h.api.strip,dataTransfer:transfer});h.dropTarget.dispatch("dragleave",{target:h.api.strip,dataTransfer:transfer,relatedTarget:h.api.controls});assert.equal(h.api.dropOverlay.hidden,false,"Moving between children keeps the drop target visible");
  h.listeners.dragover({target:h.api.controls,dataTransfer:transfer,preventDefault(){prevented++;}});assert.equal(transfer.dropEffect,"copy");
  h.listeners.drop({target:h.api.controls,dataTransfer:transfer,preventDefault(){prevented++;}});assert.equal(h.api.dropOverlay.hidden,true);await adding;
  assert.equal(prevented,3);assert.equal(h.uploads.length,1);assert.equal(h.uploads[0][1].body,file);assert.equal(h.api.documents.length,1);assert.equal(h.api.input.clicks,0,"Drop must bypass the chooser and reuse direct upload");h.api.dispose();passes++;
 }
 {
  const h=setup();let prevented=false;const transfer={types:["text/plain"],files:[]};
  h.dropTarget.dispatch("dragenter",{dataTransfer:transfer,preventDefault(){prevented=true;}});h.listeners.dragover({target:h.dropTarget,dataTransfer:transfer,preventDefault(){prevented=true;}});h.listeners.drop({target:h.dropTarget,dataTransfer:transfer,preventDefault(){prevented=true;}});
  assert.equal(prevented,false,"Text editing/internal text drags must keep browser behavior");assert.equal(h.api.dropOverlay.hidden,true);assert.equal(h.uploads.length,0);h.api.dispose();passes++;
 }
 {
  const h=setup(),transfer={types:["Files"],files:[{name:"outside.pdf",size:20}]};let prevented=0;
  h.listeners.dragover({target:h.document.body,dataTransfer:transfer,preventDefault(){prevented++;}});h.listeners.drop({target:h.document.body,dataTransfer:transfer,preventDefault(){prevented++;}});
  assert.equal(prevented,2,"A file dropped outside the conversation cannot navigate away from unsaved work");assert.equal(transfer.dropEffect,"none");assert.equal(h.uploads.length,0);assert.equal(h.jsonCalls.length,0);
  h.dropTarget.hidden=true;h.listeners.drop({target:h.api.controls,dataTransfer:transfer,preventDefault(){prevented++;}});assert.equal(h.uploads.length,0,"A hidden interview cannot accept uploads from another view");h.api.dispose();passes++;
 }
 {
  let allowed=false;const h=setup({canUpload:()=>allowed}),transfer={types:["Files"],files:[{name:"wait.pdf",size:20}]};
  h.dropTarget.dispatch("dragenter",{dataTransfer:transfer});assert.match(h.api.dropOverlay.textContent,/can't be attached/);h.listeners.drop({target:h.dropTarget,dataTransfer:transfer,preventDefault(){}});assert.equal(h.uploads.length,0);assert.match(h.notices.at(-1)[0],/can't be attached/);
  allowed=true;h.api.setDocuments(Array.from({length:20},(_,i)=>doc({id:"doc_"+i})),false);h.dropTarget.dispatch("dragenter",{dataTransfer:transfer});assert.match(h.api.dropOverlay.textContent,/20 files/);h.listeners.drop({target:h.dropTarget,dataTransfer:transfer,preventDefault(){}});await tick();assert.equal(h.uploads.length,0);assert.match(h.api.dialog.textContent,/up to 20 files/);h.api.dispose();passes++;
 }
 {
  const h=setup(),transfer={types:["Files"],files:[{name:"not-supported.exe",size:20},{name:"too-large.pdf",size:64*1024*1024+1},{name:"empty.csv",size:0}]};
  h.listeners.drop({target:h.dropTarget,dataTransfer:transfer,preventDefault(){}});await tick();assert.equal(h.uploads.length,0);assert.equal(h.api.uploadErrors.length,3);assert.match(h.api.dialog.textContent,/64 MiB/);assert.equal(h.api.dialog.open,true,"Dropped validation errors use the same file tray");h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({fetch:()=>pending.promise}),transfer={types:["Files"],files:[{name:"late-drop.pdf",size:20}]};
  h.listeners.drop({target:h.dropTarget,dataTransfer:transfer,preventDefault(){}});await tick();assert.equal(h.uploads.length,1);h.api.reset();assert.equal(h.uploads[0][1].signal.aborted,true);pending.resolve(response(doc()));await tick();assert.equal(h.api.documents.length,0);assert.equal(h.events.filter(e=>e.type==="received").length,0);h.api.dispose();passes++;
 }
 {
  const h=setup(),transfer={types:["Files"],files:[]};h.dropTarget.dispatch("dragenter",{dataTransfer:transfer});h.listeners.keydown({key:"Escape"});assert.equal(h.api.dropOverlay.hidden,true);
  h.dropTarget.dispatch("dragenter",{dataTransfer:transfer});h.dropTarget.dispatch("dragleave",{dataTransfer:transfer});assert.equal(h.api.dropOverlay.hidden,true);
  h.dropTarget.dispatch("dragenter",{dataTransfer:transfer});h.api.suspend();assert.equal(h.api.dropOverlay.hidden,true);h.api.resume();h.dropTarget.dispatch("dragenter",{dataTransfer:transfer});h.listeners.blur();assert.equal(h.api.dropOverlay.hidden,true);
  const overlay=h.api.dropOverlay;h.api.dispose();assert.equal(overlay.isConnected,false);assert.equal(h.listeners.drop,undefined);assert.equal(h.listeners.dragover,undefined);assert.equal(h.dropTarget.classList.contains("document-drop-zone"),false);passes++;
 }
 {
  const h=setup(),transfer={types:["Files"],files:[],items:[{webkitGetAsEntry:()=>({isDirectory:true})}]};
  h.listeners.drop({target:h.dropTarget,dataTransfer:transfer,preventDefault(){}});assert.equal(h.uploads.length,0);assert.match(h.notices.at(-1)[0],/individual files/);
  h.listeners.drop({target:h.dropTarget,dataTransfer:{types:["Files"],files:[]},preventDefault(){}});assert.match(h.notices.at(-1)[0],/could not be read/);h.api.dispose();passes++;
 }
 {
  const old=deferred(),fresh=deferred();let requests=0;const h=setup({request:()=>++requests===1?old.promise:fresh.promise});h.api.scope="local-scope";h.api.setDocuments([doc()],false);
  const polling=h.api.refresh(),before=h.api.controller.signal;h.listeners.pagehide();assert.equal(before.aborted,true);assert.equal(h.api.allowed(),false);assert.equal(h.api.documents.length,1);
  await h.api.refresh();await h.api.action(h.api.documents[0],"park");await h.api.openSource(h.api.documents[0],{source_id:"p1"});h.api.schedule(0);
  assert.equal(requests,1,"Suspended controllers cannot start new work");assert.equal(h.timers.size,0,"Suspended controllers cannot start poll loops");
  h.listeners.pageshow({persisted:true});assert.equal(h.api.controller.signal.aborted,false);assert.equal(h.api.allowed(),true);assert.equal(requests,2,"Cache restoration refreshes with a new request controller");
  old.resolve({documents:[]});await polling;assert.equal(h.api.documents.length,1,"Pre-navigation status cannot erase restored state");
  fresh.resolve({documents:[doc({name:"Restored.pdf"})]});await tick();assert.equal(h.api.documents[0].name,"Restored.pdf");h.api.dispose();assert.equal(h.listeners.pageshow,undefined);passes++;
 }
 {
  const pending=deferred(),h=setup({request:()=>pending.promise});h.api.scope="local-scope";h.api.setDocuments([doc()],false);h.api.open();
  const source=h.api.openSource(h.api.documents[0],{source_id:"page1",label:"Page 1"});h.listeners.pagehide();assert.equal(h.api.source.loading,false);assert.equal(h.api.source.error,true);pending.resolve({source:{text:"Obsolete source response"}});await source;assert.notEqual(h.api.source.text,"Obsolete source response");h.api.dispose();passes++;
 }

 {
  const pending=deferred(),h=setup({request:(url,payload)=>payload.action==="park"?pending.promise:Promise.resolve({})});h.api.scope="local-scope";h.api.setDocuments([doc()],false);
  const file=h.api.documents[0],parking=h.api.action(file,"park");await h.api.action(file,"remove");
  assert.equal(h.jsonCalls.filter(call=>call[0].endsWith("/action")).length,1,"A pending action prevents a conflicting removal");
  pending.resolve({document:doc({analysis:{phase:"complete",disposition:"parked",version:2}})});await parking;
  await h.api.action(h.api.documents[0],"remove");assert.equal(h.api.documents.length,0,"A completed action releases the document for later removal");h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.scope="local-scope";h.api.setDocuments([doc({analysis:{phase:"complete",disposition:"relevant",questions:[{text:"Who approves this file?"}]}})],false);h.api.open();h.api.options.canDiscuss=()=>false;
  h.findText("button","Discuss").click();assert.equal(h.api.dialog.open,true);assert.equal(h.events.filter(event=>event.type==="question").length,0);assert.match(h.notices.at(-1)[0],/current reply/);
  h.api.options.canDiscuss=()=>true;h.findText("button","Discuss").click();assert.equal(h.api.dialog.open,false);assert.equal(h.events.filter(event=>event.type==="question").length,1);h.api.dispose();passes++;
 }

 {
  const h=setup();assert.equal(h.jsonCalls.length,0);assert.equal(h.uploads.length,0);assert.equal(h.api.strip.hidden,true);assert.equal(h.api.input.multiple,true);assert.equal(h.api.input.accept,".pdf,.png,.xlsx,.xlsm,.csv");
  h.api.attach();assert.equal(h.api.input.clicks,1);assert.match(h.api.dialog.textContent,/Files are saved on this computer\. Relevant content is sent to OpenAI/);h.api.dispose();passes++;
 }
 {
  const h=setup();const file={name:"Client notes & café.pdf",size:1024};await h.api.addFiles([file]);
  assert.equal(h.jsonCalls[0][0],"/api/documents/session");assert.deepEqual(JSON.parse(JSON.stringify(h.jsonCalls[0][1].context)),{},"Uploads must work before a process name exists");
  assert.equal(h.uploads.length,1);assert.equal(h.uploads[0][1].body,file);assert.equal(h.uploads[0][1].headers["X-CSRF-Token"],"test-csrf");assert.equal(h.uploads[0][1].headers["X-Document-Filename"],encodeURIComponent(file.name));
  assert.equal(h.events.filter(event=>event.type==="received").length,1);assert.equal(h.events.filter(event=>event.type==="question").length,0);assert.equal(h.api.exportState().documents.length,1);assert.ok(h.dirty>0);h.api.dispose();passes++;
 }
 {
  const h=setup();await h.api.addFiles([{name:"large.pdf",size:64*1024*1024+1},{name:"program.exe",size:10},{name:"empty.csv",size:0}]);
  assert.equal(h.uploads.length,0);assert.equal(h.jsonCalls.length,0);assert.equal(h.api.dialog.open,true);assert.match(h.api.dialog.textContent,/64 MiB/);assert.match(h.api.dialog.textContent,/empty/);h.api.dispose();passes++;
 }
 {
  const h=setup();await h.api.addFiles([{name:"limit.pdf",size:64*1024*1024}]);assert.equal(h.uploads.length,1,"Exactly64MiB is within the upload limit");h.api.reset();
  h.api.scope="local-scope";h.api.setDocuments(Array.from({length:20},(_,i)=>doc({id:"doc_"+i})),false);assert.equal(h.api.attachButton.disabled,true);
  await h.api.addFiles([{name:"extra.pdf",size:10}]);assert.equal(h.uploads.length,1);assert.match(h.api.dialog.textContent,/20 files/);h.api.dispose();passes++;
 }
 {
  let version=1;const h=setup({request:async()=>({documents:[doc({analysis:{phase:"deep",disposition:"relevant",version,summary:"Useful context",question:"A quick question?",questions:[{id:"q1",text:"A quiet question?",sources:[]}]}})]})});h.api.scope="local-scope";
  await h.api.refresh();assert.equal(h.events.filter(event=>event.type==="analysis").length,1);assert.ok([...h.timers.values()].some(timer=>timer.delay===2000));
  await h.api.refresh();assert.equal(h.events.filter(event=>event.type==="analysis").length,1,"Repeated analysis versions must not re-announce");version=2;await h.api.refresh();assert.equal(h.events.filter(event=>event.type==="analysis").length,2);assert.equal(h.events.filter(event=>event.type==="question").length,0,"Background questions must not interrupt the interview");h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.scope="local-scope";h.api.setDocuments([doc({analysis:{phase:"complete",disposition:"parked",version:1,questions:[{id:"q1",text:"Should we revisit this?",sources:[]}]}})],false);
  h.api.open();assert.match(h.api.body.textContent,/Questions for later/);h.findText("button","Discuss").click();assert.equal(h.api.dialog.open,false);assert.equal(h.events.filter(event=>event.type==="question").length,1);assert.equal(h.events.at(-1).question.id,"q1");h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({request:(url)=>url.endsWith("/action")?pending.promise:Promise.resolve({documents:[]})});h.api.scope="local-scope";
  h.api.setDocuments([doc({analysis:{phase:"quick",disposition:"needs_reason",version:1}})],false);h.api.open();let input=h.api.body.querySelector("[data-document-purpose]");input.value="  Look for approval gaps.  ";input.focus();input.setSelectionRange(4,12);h.api.render();input=h.api.body.querySelector("[data-document-purpose]");assert.equal(input.value,"  Look for approval gaps.  ");assert.equal(h.document.activeElement,input);assert.equal(input.selectionStart,4);
  const form=h.api.body.querySelector("form");form.dispatch("submit");form.dispatch("submit");assert.equal(h.jsonCalls.filter(call=>call[0].endsWith("/action")).length,1,"An in-flight purpose must only submit once");assert.equal(h.jsonCalls[0][1].purpose,"Look for approval gaps.");
  pending.resolve({document:doc()});await tick();assert.equal(h.api.documents[0].analysis.disposition,"relevant");h.api.dispose();passes++;
 }
 {
  const calls=[],h=setup({request:async(url,body)=>{calls.push(body.action);return{document:doc({analysis:{phase:"deep",disposition:body.action==="park"?"parked":"relevant",version:2}})};}});h.api.scope="local-scope";h.api.setDocuments([doc()],false);
  await h.api.action(h.api.documents[0],"park");assert.equal(h.api.documents[0].analysis.disposition,"parked");assert.ok(h.findText("button","Revisit this file"));await h.api.action(h.api.documents[0],"revisit");assert.deepEqual(calls,["park","revisit"]);h.api.dispose();passes++;
 }
 {
  const h=setup({request:async(url,body)=>({source:{label:"Sheet1!B7:C9",text:"Exact <img onerror=bad> cell text."}})});h.api.scope="local-scope";const document=doc({name:"Register.xlsx",kind:"xlsx",analysis:{phase:"complete",disposition:"relevant",version:1,sources:[{source_id:"s1",label:"Sheet1!B7:C9"}]}});h.api.setDocuments([document],false);
  await h.api.openSource(document,{source_id:"s1",label:"Sheet1!B7:C9"});assert.match(h.api.body.textContent,/Register.xlsx · Sheet1!B7:C9/);assert.ok(h.api.body.textContent.includes("Exact <img onerror=bad> cell text."));assert.equal(h.api.body.querySelector("img"),null);assert.equal(h.jsonCalls[0][1].id,document.id);assert.equal(h.jsonCalls[0][1].source_id,"s1");h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({fetch:()=>pending.promise});const adding=h.api.addFiles([{name:"late.pdf",size:20}]);await tick();assert.equal(h.uploads.length,1);const uploadSignal=h.uploads[0][1].signal;
  h.api.reset();assert.equal(uploadSignal.aborted,true);pending.resolve(response(doc()));await adding;assert.equal(h.api.documents.length,0);assert.equal(h.events.filter(event=>event.type==="received").length,0);assert.equal(h.jsonCalls.some(call=>call[1]?.action==="remove"),false,"Reset must not delete the persistent original");h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({request:()=>pending.promise});h.api.scope="local-scope";const refreshing=h.api.refresh();h.api.reset();pending.resolve({documents:[doc()]});await refreshing;
  assert.equal(h.api.scope,null);assert.equal(h.api.documents.length,0);assert.equal(h.events.length,0,"Reset must ignore stale polling callbacks");h.api.dispose();passes++;
 }
 {
  const h=setup({request:async()=>{throw new Error("This local file workspace is unavailable.");}});await h.api.restoreState({scope:"saved-local-scope",documents:[doc()]});
  assert.equal(h.api.documents.length,1);assert.equal(h.api.exportState().scope,"saved-local-scope");assert.match(h.api.body.textContent,/Saved file details are retained/);
  const saved=h.api.exportState();saved.documents[0].name="Changed externally";assert.equal(h.api.documents[0].name,"Procedure.pdf");h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({request:()=>pending.promise});h.api.scope="local-scope";const first=h.api.refresh(),second=h.api.refresh();assert.equal(h.jsonCalls.length,1,"Polling must never overlap");
  pending.resolve({documents:[doc()]});await Promise.all([first,second]);assert.ok([...h.timers.values()].some(timer=>timer.delay===10000));h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({request:(url)=>url.endsWith("/status")?pending.promise:Promise.resolve({document:doc()})});h.api.scope="local-scope";h.api.setDocuments([doc()],false);const refreshing=h.api.refresh();await h.api.action(h.api.documents[0],"remove");pending.resolve({documents:[doc()]});await refreshing;
  assert.equal(h.api.documents.length,0,"An older status snapshot must not resurrect a removed attachment");h.api.dispose();passes++;
 }
 {
  let allowed=false;const h=setup({canUpload:()=>allowed});h.api.attach();assert.equal(h.api.input.clicks,0);await h.api.addFiles([{name:"x.pdf",size:10}]);assert.equal(h.uploads.length,0);
  allowed=true;h.api.attach();assert.equal(h.api.input.clicks,1);h.api.countButton.focus();h.api.open();h.api.close();assert.equal(h.document.activeElement,h.api.countButton);h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.scope="local-scope";h.api.setDocuments([doc()],false);h.api.schedule();assert.equal(h.timers.size,1);h.api.dispose();assert.equal(h.timers.size,0);assert.equal(h.api.controls.children.length,0);assert.equal(h.api.strip.hidden,true);passes++;
 }
 {
  const h=setup({fetch:(url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener("abort",()=>reject(new DOMException("Timed out","AbortError"))))});
  const adding=h.api.addFiles([{name:"slow.pdf",size:20}]);await tick();const timeout=[...h.timers.entries()].find(([,timer])=>timer.delay===120000);assert.ok(timeout,"Raw uploads need a bounded network wait");
  h.timers.delete(timeout[0]);timeout[1].fn();await adding;assert.equal(h.api.uploads.length,0);assert.match(h.notices[0][0],/took too long/);assert.equal(h.api.documents.length,0);h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({request:url=>url.endsWith("/status")?pending.promise:Promise.resolve({document:doc()})});h.api.scope="local-scope";h.api.setDocuments([doc()],false);
  const refreshing=h.api.refresh();await h.api.action(h.api.documents[0],"remove");pending.reject(new Error("Old status request failed"));await refreshing;
  assert.equal(h.events.filter(event=>event.type==="error").length,0,"An obsolete status error must not disturb a later document action");assert.equal(h.api.connectionError,"");h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.setDocuments([doc({name:"Fifty tabs.xlsx",coverage:{indexed_units:3,total_units:50,limitations:["Formula values may be stale.","Embedded visuals are not fully interpreted."]},inventory:{sheets:Array.from({length:50},(_,i)=>`Tab ${i+1}`)},analysis:{phase:"deep",disposition:"relevant",version:1,limitations:["Unsupported content remains explicit.","Formula values may be stale."]}})],false);
  assert.ok(h.api.body.textContent.includes("3/50 units indexed."));for(const limitation of ["Formula values may be stale.","Embedded visuals are not fully interpreted.","Unsupported content remains explicit."])assert.ok(h.api.body.textContent.includes(limitation));
  assert.equal(h.api.body.textContent.split("Formula values may be stale.").length-1,1,"Reading limits should not repeat identical messages");assert.ok(h.api.body.textContent.includes("50 sheets"));assert.ok(h.api.body.textContent.includes("Tab 12"));assert.ok(h.api.body.textContent.includes("38 more listed"));h.api.dispose();passes++;
 }
 {
  const h=setup({request:async()=>({document:doc()})});h.api.scope="local-scope";h.api.setDocuments([doc({status:"ready",analysis:{phase:"error",disposition:"relevant",version:1,error:"The review service is unavailable."}})],false);
  assert.match(h.api.strip.textContent,/Review paused/);assert.doesNotMatch(h.api.strip.textContent,/Ready to review/);assert.ok(h.api.body.textContent.includes("The review service is unavailable."));h.findText("button","Retry review").click();await tick();
  assert.equal(h.jsonCalls[0][0],"/api/documents/action");assert.equal(h.jsonCalls[0][1].action,"revisit");assert.equal(h.api.documents[0].analysis.phase,"complete");
  h.api.setDocuments([doc({analysis:{phase:"error",disposition:"parked",version:2}})],false);assert.ok(h.findText("button","Retry review"));assert.match(h.api.body.textContent,/Your saved file is retained/);h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.setDocuments([doc({analysis:{phase:"quick",disposition:"relevant",version:1,question:"Who checks this handoff?",questions:[]}})],false);
  assert.ok(h.api.body.textContent.includes("Who checks this handoff?"));h.findText("button","Discuss").click();assert.equal(h.events.at(-1).question.text,"Who checks this handoff?");
  h.api.setDocuments([doc({analysis:{phase:"quick",disposition:"needs_reason",version:2,question:"What would you like me to look for in this file?",questions:[]}})],false);
  const field=h.api.body.querySelector(".documents-purpose-field"),input=field.querySelector("input"),submit=h.findText("button","Review now");
  assert.equal(field.textContent,"What would you like me to look for in this file?");
  assert.equal(submit.disabled,true);input.value="   ";input.dispatch("input");assert.equal(submit.disabled,true);
  input.value="Check the thresholds";input.dispatch("input");assert.equal(submit.disabled,false);
  h.api.render();assert.equal(h.findText("button","Review now").disabled,false,"Polling keeps the drafted purpose actionable");
  assert.ok(h.findText("button","Save for later"));h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.setDocuments([doc({analysis:null})],false);assert.match(h.api.strip.textContent,/Checking relevance/);assert.doesNotMatch(h.api.strip.textContent,/Ready to review/);
  h.api.setDocuments([doc({analysis:{phase:"quick",version:1,summary:""}})],false);assert.match(h.api.strip.textContent,/Checking relevance/);
  h.api.setDocuments([doc({analysis:{phase:"deep",version:2,summary:"Initial context"}})],false);assert.match(h.api.strip.textContent,/Reading in depth/);
  h.api.setDocuments([doc()],false);assert.match(h.api.strip.textContent,/Ready to review/);h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.setDocuments([doc({analysis:{phase:"deep",disposition:"relevant",version:1,summary:"Long source summary that must not be announced repeatedly."}})],false);
  assert.equal(h.api.body.getAttribute("aria-live"),"off");assert.equal(h.api.liveStatus.getAttribute("role"),"status");assert.equal(h.api.liveStatus.getAttribute("aria-live"),"polite");
  const announced=h.api.liveStatus.textContent;assert.match(announced,/reading in depth/);assert.equal(announced.includes("Long source summary"),false);
  h.api.setDocuments([doc({analysis:{phase:"deep",disposition:"relevant",version:2,summary:"Different long summary, same reading state."}})],false);assert.equal(h.api.liveStatus.textContent,announced,"Polling should announce concise changed status, not reannounce complete tray content");h.api.dispose();passes++;
 }
 {
  const pending=deferred(),h=setup({request:()=>pending.promise});h.api.scope="local-scope";const file=doc({analysis:{phase:"complete",disposition:"relevant",version:1,summary:"Reference",sources:[{source_id:"s1",label:"Page2"}]}});h.api.setDocuments([file],false);h.api.open();
  const sourceButton=h.api.body.querySelector(".documents-source");sourceButton.focus();const reading=h.api.openSource(file,{source_id:"s1",label:"Page2"});
  assert.notEqual(h.document.activeElement,h.api.sourceHeading,"A pending source response must not steal focus repeatedly");pending.resolve({source:{label:"Page2",text:"Source body"}});await reading;
  assert.equal(h.document.activeElement,h.api.sourceHeading);assert.equal(h.api.sourceHeading.scrolled,true,"An explicit loaded source should be brought into the contained tray viewport");
  const prior=h.api.sourceHeading;h.api.body.scrollTop=350;h.api.render();assert.notEqual(h.api.sourceHeading,prior);assert.equal(h.document.activeElement,h.api.sourceHeading,"Polling must preserve source-heading focus on its replacement node");assert.equal(h.api.body.scrollTop,350);
  h.api.countButton.focus();h.api.render();assert.equal(h.document.activeElement,h.api.countButton,"Polling must not steal focus from other controls to the source heading");
  h.findText("button","Close source").click();assert.equal(h.document.activeElement.dataset.documentSource,"doc_1:s1","Closing source returns to the matching reference control");h.api.dispose();passes++;
 }
 {
  let fail=true;const h=setup({request:async(url,body)=>{if(url.endsWith("/status"))return{documents:[doc()]};if(fail)throw Error("Could not save that direction.");return{document:doc({analysis:{phase:"deep",disposition:"relevant",version:2}})};}});h.api.scope="local-scope";h.api.setDocuments([doc()],false);
  await h.api.action(h.api.documents[0],"purpose","Check threshold evidence");assert.match(h.api.body.textContent,/Could not save that direction/);assert.ok(h.findText("button","Retry action"));assert.equal(h.notices.length,1);
  await h.api.refresh();assert.match(h.api.body.textContent,/Could not save that direction/,"A successful status refresh must retain a failed user action for recovery");fail=false;h.findText("button","Retry action").click();await tick();
  assert.equal(h.jsonCalls.at(-1)[1].purpose,"Check threshold evidence");assert.equal(h.api.actionErrors.size,0);assert.equal(h.findText("button","Retry action"),undefined);h.api.dispose();passes++;
 }
 {
  let fail=true;const file={name:"Retry.pdf",size:40},h=setup({fetch:async()=>{if(fail)throw Error("Upload connection failed.");return response(doc());}});await h.api.addFiles([file]);
  assert.match(h.api.body.textContent,/Upload connection failed/);assert.ok(h.findText("button","Retry upload"));assert.equal(h.api.exportState().documents.length,0,"The in-memory retry file is not included in saved interview state");
  fail=false;h.findText("button","Retry upload").click();await tick();assert.equal(h.uploads.length,2);assert.equal(h.uploads.at(-1)[1].body,file);assert.equal(h.api.uploadErrors.length,0);assert.equal(h.api.documents.length,1);h.api.dispose();passes++;
 }
 {
  let fail=true;const h=setup({request:async()=>{if(fail)throw Error("Source unavailable.");return{source:{label:"Page 2",text:"Loaded evidence"}};}});h.api.scope="local-scope";const document=doc();h.api.setDocuments([document],false);
  await h.api.openSource(document,{source_id:"s1",label:"Page 2"});assert.match(h.api.body.textContent,/Source unavailable/);assert.ok(h.findText("button","Retry source"));h.api.render();assert.ok(h.findText("button","Retry source"));
  fail=false;h.findText("button","Retry source").click();await tick();assert.match(h.api.body.textContent,/Loaded evidence/);assert.equal(h.findText("button","Retry source"),undefined);h.api.dispose();passes++;
 }
 {
  const h=setup();h.api.setDocuments([doc({coverage:{indexed_units:10,total_units:50},analysis:{phase:"deep",disposition:"relevant",version:1,reviewed_chunks:3,total_chunks:12}})],false);
  const stage=h.api.body.querySelector(".documents-stage");assert.match(stage.textContent,/Reading in depth/);assert.match(stage.textContent,/10\/50 units indexed/);assert.match(stage.textContent,/3 of 12 sections reviewed/);assert.equal(stage.dataset.state,"working");assert.match(h.api.body.textContent,/Reading in depth/);
  h.api.setDocuments([doc({analysis:{phase:"complete",disposition:"parked",version:2}})],false);assert.equal(h.api.body.querySelector(".documents-stage").dataset.state,"later");assert.match(h.api.body.textContent,/Saved for later/);
  h.api.setDocuments([doc({analysis:{phase:"complete",disposition:"needs_reason",version:3}})],false);const field=h.api.body.querySelector(".documents-purpose-field");assert.equal(field.tagName,"LABEL");assert.match(field.textContent,/What should I look for/);assert.equal(field.querySelector("input").dataset.documentPurpose,"doc_1");assert.ok(h.findText("button","Review now"));assert.ok(h.findText("button","Save for later"));h.api.dispose();passes++;
 }
 {
  const h=setup(),indexed=doc({status:"ready",chunk_count:11,analysis:{}});
  h.api.setDocuments([doc({status:"pending",chunk_count:0,analysis:{}})]);
  assert.equal(h.events.filter(event=>event.type==="analysis").length,0,"A pending file must not be announced as readable");
  h.api.setDocuments([indexed]);h.api.setDocuments([indexed]);
  const available=h.events.filter(event=>event.type==="analysis");assert.equal(available.length,1,"Native text availability must reach the interview before model review and only once per snapshot");
  assert.equal(available[0].document.chunk_count,11);assert.equal(JSON.stringify(available[0].analysis),"{}");
  h.api.setDocuments([doc({chunk_count:11,analysis:{phase:"quick",version:1,summary:"Initial review"}})]);
  assert.equal(h.events.filter(event=>event.type==="analysis").length,2,"The later real model review still emits its own update");h.api.dispose();passes++;
 }
 {
  const h=setup(),indexed=doc({status:"partial",chunk_count:3,analysis:null});
  h.api.setDocuments([indexed],false);h.api.setDocuments([indexed]);
  assert.equal(h.events.filter(event=>event.type==="analysis").length,0,"Restoring saved readable metadata must not add a surprise event");
  h.api.setDocuments([{...indexed,chunk_count:4}]);
  assert.equal(h.events.filter(event=>event.type==="analysis").length,1,"Additional native-readable chunks must be available without a summary");
  h.api.reset();h.api.setDocuments([indexed]);assert.equal(h.events.filter(event=>event.type==="analysis").length,2,"A new interview must not reuse the old event-deduplication state");h.api.dispose();passes++;
 }
 {
  const session=deferred();let uploaded=0;const h=setup({request:()=>session.promise,fetch:async()=>response(doc({id:`doc_${++uploaded}`}))});
  const files=[{name:"First.pdf",size:20,privateRawFile:"must not enter lifecycle"},{name:"Second.csv",size:30},{name:"Ignored.exe",size:10}];
  const adding=h.api.addFiles(files),started=h.events.filter(event=>event.type==="upload_started");
  assert.equal(started.length,1,"A selected batch is announced before opening the file workspace resolves");assert.deepEqual(Array.from(started[0].names),["First.pdf","Second.csv"]);assert.equal(h.uploads.length,0);
  assert.equal(h.api.lifecycle().uploading,2);assert.equal(h.api.lifecycle().mutating,1);assert.equal(JSON.stringify(h.api.lifecycle()).includes("must not enter lifecycle"),false);
  session.resolve({scope:"local-scope",documents:[]});await adding;
  const settled=h.events.filter(event=>event.type==="upload_settled");assert.equal(settled.length,1);assert.equal(settled[0].batchId,started[0].batchId);
  const final=h.events.filter(event=>event.type==="changed").at(-1).state;assert.equal(final.uploading,0);assert.equal(final.mutating,0);assert.equal(final.documents.length,2);assert.equal(final.uploadErrors.length,1);
  assert.ok(h.events.indexOf(settled[0])>h.events.indexOf(h.events.filter(event=>event.type==="changed").at(-1)),"Batch completion follows the zero-counter snapshot");
  final.documents[0].name="External mutation";assert.notEqual(h.api.documents[0].name,"External mutation","Lifecycle payloads cannot mutate controller records");h.api.dispose();passes++;
 }
 {
  const first=deferred(),second=deferred(),h=setup({fetch:(url,request)=>request.body.name==="First.pdf"?first.promise:second.promise});
  const a=h.api.addFiles([{name:"First.pdf",size:20}]),b=h.api.addFiles([{name:"Second.pdf",size:20}]);await tick();
  const batches=h.events.filter(event=>event.type==="upload_started");assert.equal(batches.length,2);assert.notEqual(batches[0].batchId,batches[1].batchId);assert.equal(h.api.lifecycle().uploading,2);assert.equal(h.api.lifecycle().mutating,2);
  first.resolve(response(doc({id:"doc_first"})));await a;assert.equal(h.api.lifecycle().uploading,1);assert.equal(h.api.lifecycle().mutating,1);assert.equal(h.events.filter(event=>event.type==="upload_settled").length,1);
  second.resolve(response(doc({id:"doc_second"})));await b;assert.equal(h.api.lifecycle().uploading,0);assert.equal(h.api.lifecycle().mutating,0);assert.equal(h.api.lifecycle().documents.length,2);assert.equal(h.events.filter(event=>event.type==="upload_settled").length,2);h.api.dispose();passes++;
 }
 {
  const h=setup(),pending=doc({status:"pending",chunk_count:0,analysis:{}}),failed={...pending,status:"error",error:"The file could not be extracted."};
  h.api.setDocuments([pending]);h.api.setDocuments([failed]);const changes=h.events.filter(event=>event.type==="changed");
  assert.equal(changes.length,2);assert.equal(changes.at(-1).state.documents[0].status,"error","Extraction failure reaches the coordinator without an analysis version");assert.equal(h.events.filter(event=>event.type==="analysis").length,0);
  h.api.setDocuments([failed]);h.api.render();assert.equal(h.events.filter(event=>event.type==="changed").length,2,"Unchanged polling and rendering do not duplicate lifecycle events");
  h.api.setDocuments([doc({status:"partial",analysis:{phase:"complete",version:1,review_complete:false}})]);assert.equal(h.events.filter(event=>event.type==="changed").at(-1).state.documents[0].analysis.review_complete,false,"Terminal partial review is preserved without claiming complete coverage");h.api.dispose();passes++;
 }
 {
  let fails=true;const record=doc(),h=setup({request:async()=>{if(fails)throw Error("Status temporarily unavailable.");return{documents:[record]};}});h.api.scope="local-scope";h.api.setDocuments([record],false);
  await h.api.refresh();assert.equal(h.events.filter(event=>event.type==="changed").length,1);assert.equal(h.events.filter(event=>event.type==="changed")[0].state.connectionError,"Status temporarily unavailable.");
  await h.api.refresh();assert.equal(h.events.filter(event=>event.type==="changed").length,1,"Repeated connection errors do not reannounce");
  fails=false;await h.api.refresh();assert.equal(h.events.filter(event=>event.type==="changed").length,2);assert.equal(h.events.filter(event=>event.type==="changed").at(-1).state.connectionError,"");
  await h.api.refresh();assert.equal(h.events.filter(event=>event.type==="changed").length,2,"Recovery is emitted once even if the document record itself is unchanged");h.api.dispose();passes++;
 }
 {
  let intent=0;const h=setup({request:async(url,body)=>({document:doc({analysis:{phase:body.action==="park"?"complete":"quick",disposition:body.action==="park"?"parked":"reviewing",version:++intent,intent_version:intent}})})});h.api.scope="local-scope";h.api.setDocuments([doc()],false);
  for(const action of ["park","revisit","remove"]){
   const before=h.events.length;await h.api.action(h.api.documents[0],action);const changes=h.events.slice(before).filter(event=>event.type==="changed");
   assert.equal(changes[0].state.mutating,1);assert.equal(changes.at(-1).state.mutating,0,"Actions publish lifecycle completion after counters settle");
   if(action==="remove")assert.equal(changes.at(-1).state.documents.length,0);else assert.equal(changes.at(-1).state.documents[0].analysis.disposition,action==="park"?"parked":"reviewing");
  }h.api.dispose();passes++;
 }
 {
  const h=setup({request:async()=>{throw Error("Direction was not saved.");}});h.api.scope="local-scope";h.api.setDocuments([doc()],false);await h.api.action(h.api.documents[0],"revisit");
  assert.equal(h.api.lifecycle().mutating,0);assert.equal(h.events.filter(event=>event.type==="changed").at(-1).state.mutating,0);assert.equal(h.api.actionErrors.size,1);h.api.dispose();passes++;
 }
 {
  for(const failure of [false,true]){
   const h=setup({request:async()=>{if(failure)throw Error("Saved scope unavailable.");return{documents:[doc({analysis:{phase:"complete",version:2}})]};}});
   await h.api.restoreState({scope:"saved-scope",documents:[doc({analysis:{phase:"deep",version:1}})]});assert.equal(h.events.length,0,"Restoring saved state, its initial refresh and any restore error stay passive");
   assert.equal(h.api.lifecycle().scope,"saved-scope");assert.equal(Boolean(h.api.lifecycle().connectionError),failure);h.api.dispose();
  }passes++;
 }
 {
  for(const kind of ["failure","timeout"]){
   const h=setup({request:async()=>{throw kind==="timeout"?new DOMException("Timed out","AbortError"):Error("Workspace unavailable.");}});
   await h.api.addFiles([{name:"First.pdf",size:20},{name:"Second.pdf",size:20}]);assert.equal(h.api.lifecycle().uploading,0);assert.equal(h.api.lifecycle().mutating,0);assert.equal(h.api.lifecycle().uploadErrors.length,2);
   assert.equal(h.events.filter(event=>event.type==="upload_started").length,1);assert.equal(h.events.filter(event=>event.type==="upload_settled").length,1,"A failed workspace request must release its accepted upload batch");assert.equal(h.uploads.length,0);h.api.dispose();
  }passes++;
 }
 {
  const h=setup({fetch:async(url,request)=>{if(request.body.name==="Failed.pdf")throw Error("Upload failed.");return response(doc());}});
  await h.api.addFiles([{name:"Failed.pdf",size:20,privateRawFile:"private"},{name:"Saved.pdf",size:20}]);const state=h.api.lifecycle();
  assert.equal(state.uploading,0);assert.equal(state.mutating,0);assert.equal(state.documents.length,1);assert.equal(state.uploadErrors.length,1);assert.deepEqual(Object.keys(state.uploadErrors[0]),["name","message"]);assert.equal(JSON.stringify(state).includes("privateRawFile"),false);assert.equal(h.events.filter(event=>event.type==="upload_settled").length,1);h.api.dispose();passes++;
 }
 {
  for(const action of ["reset","suspend"]){
   const pending=deferred(),h=setup({fetch:()=>pending.promise}),adding=h.api.addFiles([{name:"Old.pdf",size:20}]);await tick();const before=h.events.length;
   h.api[action]();pending.resolve(response(doc()));await adding;assert.equal(h.events.length,before,"An old generation cannot publish upload progress or completion into the current interview");assert.equal(h.api.lifecycle().uploading,0);assert.equal(h.api.lifecycle().mutating,0);h.api.dispose();
  }passes++;
 }
 {
  const session=deferred(),h=setup({request:()=>session.promise}),adding=h.api.addFiles([{name:"Interrupted.pdf",size:20}]);
  h.api.suspend();session.resolve({scope:"obsolete-scope",documents:[]});await adding;h.api.resume();
  const recovered=h.events.filter(event=>event.type==="changed").at(-1).state;assert.equal(recovered.scope,null);assert.equal(recovered.uploading,0);assert.equal(recovered.mutating,0);assert.match(recovered.uploadErrors[0].message,/interrupted/);
  h.findText("button","Dismiss issue").click();assert.equal(h.events.filter(event=>event.type==="changed").at(-1).state.uploadErrors.length,0,"Dismissing an upload issue updates the lifecycle without a poll");h.api.dispose();passes++;
 }
 console.log(JSON.stringify({tests_passed:passes,network_calls:0,provider_calls:0,physical_files_uploaded:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
