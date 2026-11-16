"use strict";
// Assets lists removed files and offers Restore, checked against the real web/documents.js behind a
// synthetic DOM. No browser, provider, filesystem upload or real network.
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
function setup(request){
 const document={activeElement:null};document.body=new Element("body",document);document.createElement=tag=>new Element(tag,document);document.createElementNS=(_,tag)=>new Element(tag,document);document.getElementById=id=>walk(document.body).find(node=>node.id===id)||null;
 const dropTarget=document.createElement("section");dropTarget.id="interview-view";document.body.append(dropTarget);
 const assets=document.createElement("div");assets.id="document-assets";dropTarget.append(assets);
 const timers=new Map();let timerId=0;const events=[],notices=[],calls=[];let dirty=0;
 const window={document,addEventListener(){},removeEventListener(){}};
 const ctx={window,DOMException,AbortController,setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const api=window.CollectorDocuments.create({document,config:()=>({csrf_token:"test-csrf"}),getContext:()=>({context:{},turns:[],focus:"",current_question:""}),canUpload:()=>true,
  requestJSON:(url,body,options)=>{calls.push({url,body});return request(url,body,options);},onEvent:event=>events.push(event),onDirty:()=>dirty++,notice:(...args)=>notices.push(args),onOpen(){},onCountChange(){}});
 const section=()=>api.body.querySelector(".documents-removed");
 const restoreButtons=()=>api.body.querySelectorAll(".document-control").filter(button=>JSON.parse(button.dataset.documentControl)[1]==="restore");
 return{api,document,events,notices,calls,section,restoreButtons,get dirty(){return dirty;},cards:()=>api.body.querySelectorAll(".documents-card")};
}
function doc(overrides={}){return{id:"doc_1",name:"returns-log.csv",kind:"csv",size:1200,status:"ready",analysis:{phase:"complete",disposition:"relevant",summary:"Returns by reason.",version:3,intent_version:1,sources:[]},...overrides};}
const REMOVED={id:"doc_1",name:"returns-log.csv",kind:"csv",size:1200};
// Arrays built inside the page's realm are compared by value.
const ids=files=>Array.from(files,file=>file.id);

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
await check("a removed file stays listed under Removed files with a Restore control",async()=>{
 const h=setup(async()=>({document:{...doc(),archived:true}}));h.api.scope="local-scope";h.api.setDocuments([doc(),doc({id:"doc_2",name:"Second.pdf"})],false);
 assert.equal(h.section(),null,"Nothing is listed before a file is removed");
 await h.api.action(h.api.documents[0],"remove");
 assert.deepEqual(ids(h.api.documents),["doc_2"]);
 const section=h.section();assert.ok(section,"Assets must show where the removed file went");
 assert.equal(section.tagName,"DETAILS");assert.equal(section.open,true,"The list opens after a removal so that it can be undone");
 assert.equal(section.querySelector("summary").textContent,"Removed files (1)");
 assert.match(section.textContent,/returns-log\.csv/);assert.match(section.textContent,/not used in the interview/);assert.match(section.textContent,/Restore puts a file back as it was/);
 assert.equal(h.restoreButtons().length,1);assert.equal(h.restoreButtons()[0].textContent,"Restore");
 assert.equal(h.restoreButtons()[0].getAttribute("aria-label"),"Restore returns-log.csv to this conversation");
 assert.equal(h.api.liveStatus.textContent,"1 file. 1 ready to review. 1 removed, can be restored","The removal is announced as something that can be undone");
 assert.deepEqual(ids(h.api.exportState().documents),["doc_2"],"A removed file is not submitted or saved as one of the interview's files");
 h.api.dispose();
});

await check("Restore asks the server to restore, not to revisit, and the file returns as it was",async()=>{
 const restored=doc({archived:false});
 const h=setup(async(url,body)=>body.action==="remove"?{document:{...doc(),archived:true}}:{document:restored});h.api.scope="local-scope";h.api.setDocuments([doc()],false);
 await h.api.action(h.api.documents[0],"remove");
 const before=h.events.length,dirty=h.dirty;
 h.restoreButtons()[0].click();
 assert.equal(h.restoreButtons()[0].disabled,true,"A restore in flight cannot be started twice");
 for(let i=0;i<20;i++)await Promise.resolve();
 assert.deepEqual(h.calls.map(call=>[call.url,call.body.action,call.body.id]),[["/api/documents/action","remove","doc_1"],["/api/documents/action","restore","doc_1"]]);
 assert.equal(h.calls.some(call=>call.body.action==="revisit"),false,"Revisit reviews the file again through the provider; Restore must not");
 assert.equal(h.section(),null,"Nothing is left under Removed files");
 assert.deepEqual(Array.from(h.api.documents,file=>[file.id,file.analysis.intent_version,file.analysis.phase]),[["doc_1",1,"complete"]]);
 assert.equal(h.cards().length,1);assert.match(h.cards()[0].textContent,/returns-log\.csv/);
 const emitted=h.events.slice(before);
 assert.ok(emitted.some(event=>event.type==="changed"&&event.state.documents.length===1),"The interview learns that the file is active again");
 assert.ok(h.dirty>dirty);
 h.api.dispose();
});

await check("removed files reported by the server are listed, for example after reopening a saved interview",async()=>{
 let listing={documents:[],removed:[REMOVED,{id:"doc_9",name:"Old policy.pdf",kind:"pdf",size:5}]};
 const h=setup(async url=>url.endsWith("/status")?listing:{document:doc()});h.api.scope="local-scope";
 await h.api.refresh();
 assert.equal(h.section().querySelector("summary").textContent,"Removed files (2)");
 assert.equal(h.section().open,false,"A list the user did not just add to starts closed");
 assert.equal(h.restoreButtons().length,2);
 const control=h.restoreButtons()[0];h.section().open=true;h.section().dispatch("toggle");
 await h.api.refresh();
 assert.ok(h.restoreButtons()[0]===control,"An unchanged poll must not rebuild the list under the pointer");
 listing={documents:[doc()],removed:[listing.removed[1]]};
 await h.api.refresh();
 assert.equal(h.section().querySelector("summary").textContent,"Removed files (1)");assert.equal(h.section().open,true,"The list stays as the user left it");
 assert.match(h.section().textContent,/Old policy\.pdf/);assert.doesNotMatch(h.section().textContent,/returns-log/);
 listing={documents:[doc()]};
 await h.api.refresh();
 assert.equal(h.restoreButtons().length,1,"A reply without the list leaves it as it was");
 h.api.dispose();
});

await check("the session reply lists removed files too",async()=>{
 const h=setup(async url=>url.endsWith("/session")?{scope:"local-scope",documents:[],removed:[REMOVED]}:{documents:[],removed:[REMOVED]});
 await h.api.ensureSession();
 assert.equal(h.restoreButtons().length,1);
 h.api.reset();assert.equal(h.section(),null,"Another interview does not inherit the list");
 h.api.dispose();
});

await check("a restore that fails keeps the file under Removed files and says so",async()=>{
 const pending=deferred();
 const h=setup(async(url,body)=>url.endsWith("/status")?{documents:[],removed:[REMOVED]}:pending.promise);h.api.scope="local-scope";
 await h.api.refresh();
 const restoring=h.api.action(h.api.removed[0],"restore");
 assert.equal(h.restoreButtons()[0].disabled,true);
 pending.reject(new Error("These files are not available in this interview."));await restoring;
 assert.equal(h.restoreButtons().length,1);assert.equal(h.restoreButtons()[0].disabled,false);
 assert.equal(h.api.documents.length,0);
 assert.ok(h.notices.some(([message,error])=>/not available in this interview/.test(message)&&error===true));
 h.api.dispose();
});

// Repair round 1: app.js reads the file list on every control update to check the draft's file signature.
await check("the file list can be read in place, without the copy that exportState makes",async()=>{
 const h=setup(async url=>url.endsWith("/status")?{documents:[doc(),doc({id:"doc_2",name:"policy.pdf",archived:true})],removed:[]}:{document:doc()});h.api.scope="local-scope";
 await h.api.refresh();
 const live=h.api.peekState(),copy=h.api.exportState();
 assert.equal(live.scope,"local-scope");
 assert.ok(live.documents===h.api.documents,"peekState hands out the records themselves, not a deep copy");
 assert.ok(copy.documents!==h.api.documents&&copy.documents[0]!==h.api.documents[0],"exportState still returns an independent copy for saving");
 assert.deepEqual(ids(live.documents),ids(copy.documents));assert.equal(JSON.stringify(live.documents),JSON.stringify(copy.documents));
 assert.ok(h.api.peekState().documents===live.documents,"Reading twice allocates no new list");
 h.api.dispose();
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
