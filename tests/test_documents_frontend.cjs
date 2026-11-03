"use strict";
// Document UI/lifecycle boundary tests: no browser, provider, filesystem upload or real network.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const source=fs.readFileSync(path.join(__dirname,"..","web","documents.js"),"utf8");
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
class Element {
 constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.listeners={};this.attributes={};this.dataset={};this.className="";this.id="";this.hidden=false;this.open=false;this.value="";this._text="";this.clicks=0;this.classList={add:name=>{this.className+=" "+name;}};}
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
function setup({request,fetch,getContext,canUpload}={}){
 const document={activeElement:null};document.body=new Element("body",document);document.createElement=tag=>new Element(tag,document);document.createElementNS=(_,tag)=>new Element(tag,document);document.getElementById=id=>walk(document.body).find(node=>node.id===id)||null;
 for(const id of ["document-controls","document-strip","documents-dialog"]){const node=document.createElement(id.endsWith("dialog")?"dialog":"div");node.id=id;document.body.append(node);}
 const timers=new Map();let timerId=0;const events=[],notices=[],jsonCalls=[],uploads=[];let dirty=0;
 const listeners={},window={document,addEventListener:(name,fn)=>listeners[name]=fn,removeEventListener:name=>delete listeners[name]};
 const ctx={window,DOMException,AbortController,setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const api=window.CollectorDocuments.create({document,config:()=>({csrf_token:"test-csrf"}),getContext:getContext||(()=>({context:{},turns:[],focus:"Intake",current_question:"What starts the work?"})),canUpload:canUpload||(()=>true),
 requestJSON:(...args)=>{jsonCalls.push(args);return request?request(...args):Promise.resolve({scope:"local-scope",documents:[]});},fetch:async(...args)=>{uploads.push(args);return fetch?fetch(...args):{ok:true,json:async()=>({document:doc()})};},
 onEvent:event=>events.push(event),onDirty:()=>dirty++,notice:(...args)=>notices.push(args)});
 return{api,document,events,notices,jsonCalls,uploads,timers,listeners,get dirty(){return dirty;},findText:(tag,text)=>walk(document.body).find(node=>node.tagName===tag.toUpperCase()&&node.textContent===text)};
}
function doc(overrides={}){return{id:"doc_1",name:"Procedure.pdf",kind:"pdf",size:1200,status:"ready",analysis:{phase:"complete",disposition:"relevant",summary:"Reported procedure.",version:1,sources:[]},...overrides};}
function response(document){return{ok:true,json:async()=>({document})};}
(async()=>{
 let passes=0;
 {
  const h=setup();assert.equal(h.jsonCalls.length,0);assert.equal(h.uploads.length,0);assert.equal(h.api.strip.hidden,true);assert.equal(h.api.input.multiple,true);assert.equal(h.api.input.accept,".pdf,.png,.xlsx,.xlsm,.csv");
  h.api.attach();assert.equal(h.api.input.clicks,1);assert.match(h.api.dialog.textContent,/Files are saved on this computer; relevant content is sent to OpenAI/);h.api.dispose();passes++;
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
  const card=h.api.body.querySelector(".documents-card"),question=card.querySelector(".documents-purpose-question"),form=card.querySelector("form");assert.ok(question);assert.ok(card.children.indexOf(question)<card.children.indexOf(form),"The purpose question belongs immediately before its input rather than being omitted by an empty questions list");assert.ok(h.findText("button","Save for later"));h.api.dispose();passes++;
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
 console.log(JSON.stringify({tests_passed:passes,network_calls:0,provider_calls:0,physical_files_uploaded:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
