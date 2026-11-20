"use strict";
// The Assets card of a file an earlier version refused whole for its size, checked against the real
// web/documents.js behind a synthetic DOM (the harness of test_documents_asset_states.cjs). No browser,
// provider, filesystem upload or real network.
//
//   node tests/test_documents_count_refusal_card.cjs                  checks the card of such a record
//   node tests/test_documents_count_refusal_card.cjs --record <file>  prints what the card of the record
//                                                                      in <file> (JSON) shows
// tests/test_document_count_limits.py uses the second form with the record DocumentStore itself returns.
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path"),assert=require("node:assert/strict");
const source=fs.readFileSync(path.join(__dirname,"..","web","documents.js"),"utf8");
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

// What a participant sees on the card, in order.
function render(record){
 const h=setup(async()=>({}));h.api.scope="local-scope";h.api.setDocuments([record],false);
 const card=h.card(),text=selector=>card.querySelector(selector)?.textContent??null;
 const seen={status:text(".documents-stage-label"),detail:text(".documents-stage-detail"),
  warnings:card.querySelectorAll(".documents-warning").map(node=>node.textContent),
  buttons:card.querySelectorAll("button").map(button=>button.textContent).filter(Boolean),
  cost_note:text(".documents-reindex-note"),text:card.textContent};
 h.api.dispose();return seen;
}

// The record DocumentStore returns for a PDF an earlier version (extraction_version 4) refused whole:
// "PDF page count exceeds the 500-page limit or is empty; no partial index was published."
const REFUSED={id:"doc_9",name:"library.pdf",filename:"library.pdf",kind:"pdf",media_type:"application/pdf",size:15,status:"error",archived:false,
 context:{},inventory:{},coverage:{indexed_units:0,total_units:0,limitations:[]},chunk_count:0,
 error:"An earlier version refused this file for its size. Retry review reads it up to the limits.",analysis:{},revision:0,
 extraction_version:4,extraction_needs_reindex:false,error_code:"invalid_file",retryable:true};

const option=process.argv.indexOf("--record");
if(option>0){
 process.stdout.write(JSON.stringify(render(JSON.parse(fs.readFileSync(process.argv[option+1],"utf8")))));
}else{
 let passed=0;
 const check=(name,fn)=>{try{fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
 check("an old size refusal gives one instruction and the button it names",()=>{
  const seen=render(REFUSED);
  assert.equal(seen.status,"Could not read file");
  assert.equal(seen.detail,null,"No line says the file was indexed: nothing of it was");
  assert.deepEqual(seen.warnings,["An earlier version refused this file for its size. Retry review reads it up to the limits."]);
  assert.ok(seen.buttons.includes("Retry review"),seen.buttons.join(" | "));
  assert.ok(!seen.buttons.includes("Re-index and review"),seen.buttons.join(" | "));
  assert.equal(seen.cost_note,null,"No paid re-index note");
  assert.doesNotMatch(seen.text,/Indexed by an earlier version|Re-index/);
 });
 check("a card names no button it does not show",()=>{
  // An earlier index kept beside a re-index that failed and cannot be retried.
  const kept={...REFUSED,name:"scan.pdf",chunk_count:3,extraction_needs_reindex:true,retryable:false,
   error:"Together with its saved AI visual readings, this file has more text than the app can store for one file, so it was not read again.",
   analysis:{phase:"reindex_required",review_complete:false}};
  let seen=render(kept);
  assert.equal(seen.detail,"Indexed by an earlier version; not counted.");
  assert.deepEqual(seen.warnings,[kept.error]);
  assert.ok(!seen.buttons.includes("Re-index and review")&&!seen.buttons.includes("Retry review"),seen.buttons.join(" | "));
  assert.equal(seen.cost_note,null,"No paid re-read note without the button");
  assert.doesNotMatch(seen.text,/Re-index/);
  // The same file while it can still be re-indexed: the instruction, the button it names and the cost beside it.
  seen=render({...kept,retryable:true});
  assert.ok(seen.buttons.includes("Re-index and review"),seen.buttons.join(" | "));
  assert.ok(seen.warnings.some(text=>text.includes("Choose Re-index and review")),seen.warnings.join(" | "));
  assert.match(seen.cost_note,/Before you choose Re-index and review/);
 });
 check("the upload limits are stated plainly and in the cells a workbook counts",()=>{
  const h=setup(async()=>({}));h.api.scope="local-scope";h.api.setDocuments([],false);
  const text=h.text();h.api.dispose();
  assert.match(text,/about 2 million spreadsheet cells \(formatted empty cells count\)/);
  assert.doesNotMatch(text,/populated cells|MiB of indexed text|sections/);
 });
 console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
}
