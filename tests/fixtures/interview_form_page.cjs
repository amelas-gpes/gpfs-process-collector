"use strict";
// A page without a browser, for suites that run the real web/app.js against the real web/index.html.
// The shipped markup is read into a small element tree (ids, classes, attributes, text, nesting), so a
// suite can ask what a control is, where it sits and what the application wrote into it. The other
// page scripts are not loaded: app.js treats them as optional. Nothing here opens a network
// connection, an audio device or a provider; timers and fetch are stand-ins the suite controls.
//
//   const {openPage}=require("./fixtures/app_page.cjs");
//   const page=await openPage({config:{api_configured:true},expose:["state","applyInterview"]});
//   page.$("answer-text"), page.app.state, page.fire(node,"click"), await page.settle()
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const WEB=path.join(__dirname,"..","..","web");
const VOID=new Set(["meta","link","img","input","source","hr","br"]);
const kebab=name=>name.replace(/[A-Z]/g,letter=>"-"+letter.toLowerCase());

function createDocument(){
 const document={activeElement:null,hidden:false,listeners:{},parentElement:null,
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(item=>item!==fn);}};
 class Element{
  constructor(tag){
   this.tagName=tag.toUpperCase();this.attributes={};this.children=[];this.parentElement=null;this.listeners={};this.style={};
   this.id="";this.open=false;this.checked=false;this.value="";this.type="";this.title="";this.tabIndex=0;
   this._text="";this._disabled=false;this.writes=0;this.scrollTop=0;this.scrollHeight=0;this.clientHeight=0;this.clientWidth=0;
   const node=this;
   this.dataset=new Proxy({},{get:(_,key)=>typeof key==="string"?node.attributes["data-"+kebab(key)]:undefined,
    set:(_,key,value)=>{node.attributes["data-"+kebab(key)]=String(value);return true;},
    has:(_,key)=>typeof key==="string"&&("data-"+kebab(key)) in node.attributes,
    deleteProperty:(_,key)=>{delete node.attributes["data-"+kebab(key)];return true;}});
   this.classList={contains:name=>node.className.split(/\s+/).includes(name),add:(...names)=>names.forEach(name=>node.classList.toggle(name,true)),
    remove:(...names)=>names.forEach(name=>node.classList.toggle(name,false)),
    toggle:(name,on)=>{const names=new Set(node.className.split(/\s+/).filter(Boolean)),yes=on===undefined?!names.has(name):Boolean(on);if(yes)names.add(name);else names.delete(name);node.className=[...names].join(" ");return yes;}};
  }
  // hidden is the attribute, as in a browser, so a [hidden] selector sees what the application set.
  get hidden(){return "hidden" in this.attributes;}
  set hidden(value){if(value)this.attributes.hidden="";else delete this.attributes.hidden;}
  get className(){return this.attributes.class||"";}
  set className(value){this.attributes.class=String(value);}
  // A control that is disabled while it has focus loses it, as in a browser.
  get disabled(){return this._disabled;}
  set disabled(value){this._disabled=Boolean(value);if(this._disabled&&document.activeElement===this)document.activeElement=document.body;}
  get maxLength(){return "maxlength" in this.attributes?Number(this.attributes.maxlength):-1;}
  set maxLength(value){this.attributes.maxlength=String(value);}
  get textContent(){return this.tagName==="#TEXT"?this._text:this.children.map(child=>child.textContent).join("");}
  set textContent(value){this.writes++;if(this.tagName==="#TEXT"){this._text=String(value);return;}this.replaceChildren();if(String(value))this.append(document.createTextNode(String(value)));}
  set innerHTML(value){this.replaceChildren();this._html=String(value);}
  get innerHTML(){return this._html||"";}
  get firstElementChild(){return this.elements[0]||null;}
  get lastElementChild(){return this.elements.at(-1)||null;}
  get firstChild(){return this.children[0]||null;}
  get elements(){return this.children.filter(child=>child.tagName!=="#TEXT");}
  get childElementCount(){return this.elements.length;}
  get nextElementSibling(){const all=this.parentElement?.elements||[];return all[all.indexOf(this)+1]||null;}
  get previousElementSibling(){const all=this.parentElement?.elements||[];return all[all.indexOf(this)-1]||null;}
  get isConnected(){let node=this;while(node.parentElement)node=node.parentElement;return node===document.body;}
  get options(){return this.querySelectorAll("option");}
  // Shown to a person: neither this element nor anything around it is hidden, and no dialog or
  // disclosure around it is closed.
  get shown(){for(let node=this;node;node=node.parentElement){if(node.hidden)return false;if(node.tagName==="DIALOG"&&!node.open)return false;if(node.parentElement?.tagName==="DETAILS"&&!node.parentElement.open&&node.tagName!=="SUMMARY")return false;}return this.isConnected;}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}
  append(...nodes){for(const item of nodes){const node=typeof item==="string"?document.createTextNode(item):item;node.remove();node.parentElement=this;this.children.push(node);}}
  prepend(...nodes){for(const item of [...nodes].reverse()){const node=typeof item==="string"?document.createTextNode(item):item;node.remove();node.parentElement=this;this.children.unshift(node);}}
  appendChild(node){this.append(node);return node;}
  replaceChildren(...nodes){for(const child of this.children)child.parentElement=null;this.children=[];this._html="";this.append(...nodes);}
  setAttribute(name,value){this.attributes[name]=String(value);if(name==="id")this.id=String(value);else if(["disabled","open","checked"].includes(name))this[name]=true;else if(["value","type","title"].includes(name))this[name]=String(value);else if(name==="tabindex")this.tabIndex=Number(value);}
  getAttribute(name){return name in this.attributes?this.attributes[name]:null;}
  hasAttribute(name){return name in this.attributes;}
  removeAttribute(name){delete this.attributes[name];if(["disabled","open","checked"].includes(name))this[name]=false;}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(item=>item!==fn);}
  contains(target){for(let node=target;node;node=node.parentElement)if(node===this)return true;return false;}
  matches(selector){return matches(this,selector);}
  closest(selector){for(let node=this;node;node=node.parentElement)if(matches(node,selector))return node;return null;}
  querySelectorAll(selector){return walk(this).filter(node=>node!==this&&node.tagName!=="#TEXT"&&matches(node,selector));}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  focus(){if(this.disabled||!this.shown)return;document.activeElement=this;}
  blur(){if(document.activeElement===this)document.activeElement=document.body;}
  click(){fire(this,"click");}
  showModal(){this.open=true;}
  show(){this.open=true;}
  close(){if(!this.open)return;this.open=false;fire(this,"close",{bubbles:false});}
  hidePopover(){}
  showPopover(){}
  scrollIntoView(){}
  scrollTo(){}
  setSelectionRange(){}
  reportValidity(){return true;}
  checkValidity(){return true;}
  getBoundingClientRect(){return {top:0,left:0,right:0,bottom:0,width:0,height:0};}
 }
 const walk=root=>[root,...root.children.flatMap(walk)];
 function compound(node,text){
  if(node.tagName==="#TEXT")return false;
  const parts=text.match(/^[a-zA-Z][\w-]*|[#.][\w-]+|\[[\w-]+(?:="[^"]*")?\]/g);
  assert.equal((parts||[]).join(""),text,"Selector not supported by the test page: "+text);
  return parts.every(part=>{
   if(part[0]==="#")return node.id===part.slice(1);
   if(part[0]===".")return node.classList.contains(part.slice(1));
   if(part[0]==="["){const [,name,value]=part.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);return name in node.attributes&&(value===undefined||node.attributes[name]===value);}
   return node.tagName===part.toUpperCase();
  });
 }
 function matches(node,selector){
  return selector.split(",").some(option=>{
   const chain=option.trim().split(/\s+/);
   if(!compound(node,chain.pop()))return false;
   let ancestor=node.parentElement;
   while(chain.length){const wanted=chain.pop();while(ancestor&&!compound(ancestor,wanted))ancestor=ancestor.parentElement;if(!ancestor)return false;ancestor=ancestor.parentElement;}
   return true;
  });
 }
 // Runs the listeners on the target and then on each ancestor up to the document, as a bubbling
 // event does. Returns the event, so a suite can read defaultPrevented.
 function fire(target,type,properties={}){
  const event={type,target,bubbles:true,defaultPrevented:false,stopped:false,key:"",ctrlKey:false,metaKey:false,shiftKey:false,altKey:false,
   preventDefault(){this.defaultPrevented=true;},stopPropagation(){this.stopped=true;},...properties};
  for(let node=target;node&&!event.stopped;node=node===document?null:node.parentElement||(node===document.body?document:null)){
   event.currentTarget=node;
   for(const fn of [...(node.listeners[type]||[])])fn(event);
   if(!event.bubbles)break;
  }
  return event;
 }
 document.createElement=tag=>new Element(tag);
 document.createElementNS=(_,tag)=>new Element(tag);
 document.createTextNode=text=>{const node=new Element("#text");node._text=String(text);return node;};
 document.createDocumentFragment=()=>new Element("#fragment");
 document.documentElement=new Element("html");document.body=new Element("body");
 document.getElementById=id=>walk(document.body).find(node=>node.id===id)||null;
 document.querySelectorAll=selector=>document.body.querySelectorAll(selector);
 document.querySelector=selector=>document.querySelectorAll(selector)[0]||null;
 return {document,Element,walk,fire};
}

// Reads the body of index.html into the tree. The markup is the application's own and is regular:
// double-quoted attributes, no comments and no inline scripts in the body.
function mountMarkup(document,html){
 const body=html.match(/<body\b[^>]*>([\s\S]*)<\/body>/)?.[1];
 assert.ok(body,"index.html has a body");
 const decode=text=>text.replace(/&amp;/g,"&").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&nbsp;/g," ");
 const stack=[document.body],token=/<(\/?)([a-zA-Z][\w-]*)((?:\s+[\w:-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/g;
 let match;
 while((match=token.exec(body))){
  const [,closing,tag,attributes,textRun]=match,parent=stack.at(-1);
  if(textRun!==undefined){if(textRun.trim())parent.append(document.createTextNode(decode(textRun.replace(/\s+/g," "))));continue;}
  if(closing){assert.equal(parent.tagName,tag.toUpperCase(),"index.html closes its elements in order");stack.pop();continue;}
  const node=document.createElement(tag);
  for(const [,name,value] of attributes.matchAll(/([\w:-]+)(?:="([^"]*)")?/g))node.setAttribute(name,decode(value||""));
  parent.append(node);
  if(!VOID.has(tag.toLowerCase()))stack.push(node);
 }
 assert.equal(stack.length,1,"index.html closes every element");
 for(const area of document.body.querySelectorAll("textarea")){area.value=area.textContent;}
}

// options: config (the /api/config reply; csrf_token and data_notice are filled in), fetch (async
// (url,init) => reply, for every other request), expose (names inside app.js to hand back as
// page.app), prepare (source run inside app.js just before init(), for example to replace request),
// voices (the installed voices speechSynthesis reports; what it is asked to say is page.spoken),
// globals (extra globals for app.js, for example MediaRecorder).
async function openPage(options={}){
 const html=fs.readFileSync(path.join(WEB,"index.html"),"utf8"),source=fs.readFileSync(path.join(WEB,"app.js"),"utf8");
 const {document,walk,fire}=createDocument();
 mountMarkup(document,html);
 const requests=[],timeouts=new Map(),intervals=new Map(),spoken=[];let timerId=0;
 const config={csrf_token:"synthetic-token",data_notice:"Synthetic data notice.",api_configured:true,...(options.config||{})};
 const windowListeners={};
 const globals={
  console,document,AbortController,DOMException,TextEncoder,TextDecoder,Blob,Uint8Array,DataView,
  URL:{createObjectURL:()=>"blob:synthetic",revokeObjectURL(){}},
  setTimeout:(fn,delay)=>{timeouts.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>{timeouts.delete(id);},
  setInterval:(fn,delay)=>{intervals.set(++timerId,{fn,delay});return timerId;},clearInterval:id=>{intervals.delete(id);},
  requestAnimationFrame:fn=>{fn(0);return 0;},cancelAnimationFrame(){},confirm:()=>true,
  getComputedStyle:()=>({paddingLeft:"0px",paddingRight:"0px"}),
  matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}}),
  navigator:{mediaDevices:null},
  SpeechSynthesisUtterance:class{constructor(text){this.text=text;}},
  speechSynthesis:{cancel(){},speak(utterance){spoken.push(utterance);},getVoices:()=>options.voices||[],addEventListener(){}},
  addEventListener:(type,fn)=>{(windowListeners[type]??=[]).push(fn);},removeEventListener(){},
  fetch:async(url,init)=>{
   requests.push({url,init});
   if(url==="/api/config")return {ok:true,status:200,json:async()=>config};
   if(options.fetch)return options.fetch(url,init);
   throw new Error("Unexpected request in a test page: "+url);
  },
  ...(options.globals||{})
 };
 const context=vm.createContext(globals),scope=vm.runInContext("globalThis",context);
 scope.window=scope;
 const names=options.expose||[];
 const hook=`  ${options.prepare||""}\n  window.__page={${names.join(",")}};\n  window.__ready=init();\n})();`;
 const patched=source.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
 assert.notEqual(patched,source,"Install the test hook only at application initialization");
 vm.runInContext(patched,context,{filename:"app.js"});
 await scope.__ready;
 const settle=async(turns=8)=>{for(let i=0;i<turns;i++)await new Promise(resolve=>setImmediate(resolve));};
 return {document,window:scope,app:scope.__page,requests,timeouts,intervals,spoken,windowListeners,walk,fire,settle,config,html,source,
  $:id=>document.getElementById(id),
  // Runs the timers due within the given milliseconds, earliest first; the application's clock is not moved.
  runTimeouts(limit=Infinity){for(const [id,timer] of [...timeouts].sort((a,b)=>a[1].delay-b[1].delay)){if(timer.delay<=limit&&timeouts.delete(id))timer.fn();}}};
}

// A microphone, a recorder and a clock for Dictate. Pass .globals to openPage; move .clock forward
// (milliseconds) to let time pass. A recorder that is stopped hands over one chunk of stand-in audio.
function standInMicrophone(){
 const microphone={clock:1000,recorders:[],tracks:[]};
 class Recorder{
  static isTypeSupported(type){return type==="audio/webm";}
  constructor(stream,options){this.stream=stream;this.mimeType=options?.mimeType||"";this.state="inactive";this.listeners={};microphone.recorders.push(this);}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  emit(type,event={}){for(const fn of this.listeners[type]||[])fn(event);}
  start(){this.state="recording";}
  stop(){this.state="inactive";this.emit("dataavailable",{data:new Blob(["synthetic audio"])});this.emit("stop");}
 }
 microphone.globals={MediaRecorder:Recorder,performance:{now:()=>microphone.clock},
  navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>{const track={stopped:false,stop(){this.stopped=true;}};microphone.tracks.push(track);return [track];}})}}};
 return microphone;
}

module.exports={openPage,createDocument,mountMarkup,standInMicrophone};
