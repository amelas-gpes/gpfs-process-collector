"use strict";
// A page for the Node suites: web/index.html is parsed into a small DOM and web/app.js is started on it
// by its own init(), so the tests press the controls the page really has and read the regions it really
// shows. Only the browser itself is a stand-in: layout, the top layer, timers, media and the network.
// Nothing is installed, no browser is started and no request leaves the process.
//
//   const {open}=require("./fixtures/app_page.cjs");
//   const page=await open({config:{agent_team:{enabled:true}},expose:"notice,updateControls"});
//   page.$("final-check").click(); page.t.notice("…"); page.timers; page.requests; page.route((url,options)=>reply)
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const WEB=path.join(__dirname,"..","..","web");
const VOID=new Set(["meta","link","input","br","hr","img","source","track","wbr","area","base","col","embed"]);
const camel=name=>name.replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());
const FLAGS=["hidden","disabled","checked","open","required","inert","multiple","selected"];

function createDocument(){
 const document={activeElement:null,modals:[],listeners:{},hidden:false,visibilityState:"visible",title:""};
 class Node{
  constructor(){this.parentNode=null;this.childNodes=[];}
  get parentElement(){return this.parentNode instanceof Element?this.parentNode:null;}
  get nextSibling(){const list=this.parentNode?.childNodes||[];return list[list.indexOf(this)+1]||null;}
  get previousSibling(){const list=this.parentNode?.childNodes||[];return list[list.indexOf(this)-1]||null;}
  get isConnected(){let node=this;while(node.parentNode)node=node.parentNode;return node===document.documentElement;}
  remove(){if(!this.parentNode)return;const list=this.parentNode.childNodes;list.splice(list.indexOf(this),1);this.parentNode=null;}
 }
 class Text extends Node{
  constructor(value){super();this.data=String(value);this.nodeType=3;}
  get textContent(){return this.data;}set textContent(value){this.data=String(value);}
 }
 class Element extends Node{
  constructor(tag){
   super();this.nodeType=1;this.tagName=tag.toUpperCase();this.attributes={};this.dataset={};this.listeners={};this.className="";this.id="";this.value="";
   this.style={setProperty(name,value){this[name]=value;},removeProperty(name){delete this[name];},getPropertyValue(name){return this[name]||"";}};
   for(const flag of FLAGS)this[flag]=false;
   this.scrollTop=0;this.scrollHeight=0;this.clientHeight=0;this.clientWidth=0;this.offsetWidth=0;this.offsetHeight=0;this.tabIndex=-1;this.modal=false;
   const classes=()=>this.className.split(/\s+/).filter(Boolean);
   this.classList={contains:name=>classes().includes(name),
    add:(...names)=>{this.className=[...new Set([...classes(),...names])].join(" ");},
    remove:(...names)=>{this.className=classes().filter(name=>!names.includes(name)).join(" ");},
    toggle:(name,on)=>{const yes=on===undefined?!classes().includes(name):Boolean(on);if(yes)this.classList.add(name);else this.classList.remove(name);return yes;}};
  }
  // Attributes the application reads back as properties are kept as properties.
  setAttribute(name,value){
   value=String(value);
   if(name==="id")this.id=value;else if(name==="class")this.className=value;else if(name==="value")this.value=value;
   else if(FLAGS.includes(name))this[name]=true;else if(name.startsWith("data-"))this.dataset[camel(name.slice(5))]=value;
   else if(name==="tabindex")this.tabIndex=Number(value);
   else this.attributes[name]=value;
   if(["type","name","title","href","placeholder","role","for"].includes(name))this[name==="for"?"htmlFor":name]=value;
  }
  getAttribute(name){
   if(name==="id")return this.id||null;if(name==="class")return this.className||null;
   if(FLAGS.includes(name))return this[name]?"":null;if(name.startsWith("data-"))return this.dataset[camel(name.slice(5))]??null;
   if(name==="tabindex")return this.attributes.tabindex??(this.tabIndex>=0?String(this.tabIndex):null);
   return this.attributes[name]??null;
  }
  hasAttribute(name){return this.getAttribute(name)!==null;}
  removeAttribute(name){if(FLAGS.includes(name))this[name]=false;else if(name.startsWith("data-"))delete this.dataset[camel(name.slice(5))];else delete this.attributes[name];}
  get children(){return this.childNodes.filter(node=>node instanceof Element);}
  get firstElementChild(){return this.children[0]||null;}
  get lastElementChild(){return this.children.at(-1)||null;}
  get firstChild(){return this.childNodes[0]||null;}
  get childElementCount(){return this.children.length;}
  get textContent(){return this.childNodes.map(node=>node.textContent).join("");}
  set textContent(value){for(const node of this.childNodes)node.parentNode=null;this.childNodes=[];if(String(value)!=="")this.append(String(value));}
  get innerText(){return this.textContent;}set innerText(value){this.textContent=value;}
  set innerHTML(value){this.textContent="";this.markup=String(value);}get innerHTML(){return this.markup||"";}
  get options(){return this.querySelectorAll("option");}
  get labels(){return [];}
  get form(){return this.closest("form");}
  adopt(node){if(!(node instanceof Node))node=new Text(node);node.remove();node.parentNode=this;return node;}
  append(...nodes){for(const node of nodes)this.childNodes.push(this.adopt(node));changed(this);}
  prepend(...nodes){this.childNodes.unshift(...nodes.map(node=>this.adopt(node)));}
  appendChild(node){this.append(node);return node;}
  insertBefore(node,before){node=this.adopt(node);const index=before?this.childNodes.indexOf(before):-1;if(index<0)this.childNodes.push(node);else this.childNodes.splice(index,0,node);return node;}
  removeChild(node){node.remove();return node;}
  replaceChildren(...nodes){for(const node of this.childNodes)node.parentNode=null;this.childNodes=[];this.append(...nodes);}
  after(...nodes){let before=this.nextSibling;for(const node of nodes)this.parentNode.insertBefore(node,before);}
  before(...nodes){for(const node of nodes)this.parentNode.insertBefore(node,this);}
  replaceWith(...nodes){this.before(...nodes);this.remove();}
  contains(node){for(let cursor=node;cursor;cursor=cursor.parentNode)if(cursor===this)return true;return false;}
  matches(selector){return selector.split(",").some(part=>matchesChain(this,part.trim().split(/\s*>\s*|\s+/).filter(Boolean),/>/.test(part)));}
  closest(selector){for(let node=this;node instanceof Element;node=node.parentNode)if(node.matches(selector))return node;return null;}
  querySelectorAll(selector){return descendants(this).filter(node=>node.matches(selector));}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  getElementsByTagName(tag){return descendants(this).filter(node=>node.tagName===tag.toUpperCase());}
  addEventListener(type,listener,options){(this.listeners[type]??=[]).push({listener,once:Boolean(options&&options.once)});}
  removeEventListener(type,listener){this.listeners[type]=(this.listeners[type]||[]).filter(entry=>entry.listener!==listener);}
  dispatchEvent(event){
   event.target??=this;event.defaultPrevented??=false;
   event.preventDefault??=()=>{event.defaultPrevented=true;};event.stopPropagation??=()=>{event.stopped=true;};
   for(let node=this;node&&!event.stopped;node=event.bubbles?node.parentNode:null){
    event.currentTarget=node;
    for(const entry of [...(node.listeners?.[event.type]||[])]){
     if(entry.once)node.listeners[event.type]=node.listeners[event.type].filter(item=>item!==entry);
     entry.listener.call(node,event);
    }
   }
   if(event.bubbles&&!event.stopped)for(const entry of [...(document.listeners[event.type]||[])])entry.listener.call(document,event);
   return !event.defaultPrevented;
  }
  // What a person can do: a control that is disabled, hidden, or behind a modal dialog does not react.
  get reachable(){
   for(let node=this;node instanceof Element;node=node.parentNode)if(node.hidden||node.inert||node.tagName==="DIALOG"&&!node.open)return false;
   const top=document.modals.at(-1);return this.isConnected&&(!top||top.contains(this));
  }
  click(){if(this.disabled||!this.reachable)return false;this.dispatchEvent({type:"click",bubbles:true});return true;}
  input(value){assert.ok(!this.disabled&&this.reachable,`${this.id||this.tagName} cannot be edited`);this.value=value;this.dispatchEvent({type:"input",bubbles:true});this.dispatchEvent({type:"change",bubbles:true});}
  focus(){
   if(this.disabled||!this.reachable||document.activeElement===this)return;
   const previous=document.activeElement;document.activeElement=this;
   previous?.dispatchEvent?.({type:"focusout",bubbles:true,relatedTarget:this});this.dispatchEvent({type:"focusin",bubbles:true,relatedTarget:previous});
  }
  blur(){if(document.activeElement!==this)return;document.activeElement=document.body;this.dispatchEvent({type:"focusout",bubbles:true,relatedTarget:null});}
  hover(on=true){this.dispatchEvent({type:on?"mouseenter":"mouseleave",bubbles:false});}
  showModal(){if(this.open)throw new Error("The dialog is already open");this.open=true;this.modal=true;document.modals.push(this);const focused=document.activeElement;if(focused&&!this.contains(focused)){document.activeElement=this;focused.dispatchEvent?.({type:"focusout",bubbles:true,relatedTarget:this});}}
  show(){this.open=true;}
  close(){if(!this.open)return;this.open=false;this.modal=false;document.modals=document.modals.filter(dialog=>dialog!==this);if(this.contains(document.activeElement))document.activeElement=document.body;this.dispatchEvent({type:"close",bubbles:false});}
  scrollIntoView(){}scrollTo(){}select(){}setSelectionRange(){}animate(){return {finished:Promise.resolve(),cancel(){}};}
  reportValidity(){return true;}checkValidity(){return true;}setCustomValidity(){}
  getBoundingClientRect(){return {top:0,left:0,right:0,bottom:0,width:0,height:0,x:0,y:0};}
  // Whether a person would see this element: nothing on the way up is hidden or a closed dialog,
  // and no modal dialog covers it.
  get visible(){return this.reachable;}
 }
 function descendants(root){const found=[];for(const child of root.children){found.push(child,...descendants(child));}return found;}
 // Child-list observers, told after the change as a browser tells them (replaceChildren ends in append).
 function changed(target){for(const observer of document.observers)if(observer.target===target)queueMicrotask(()=>{if(document.observers.has(observer))observer.callback([],observer);});}
 document.observers=new Set();
 document.MutationObserver=class{constructor(callback){this.callback=callback;}observe(target){this.target=target;document.observers.add(this);}disconnect(){document.observers.delete(this);}};
 function matchesCompound(node,compound){
  const pattern=/^([a-zA-Z][\w-]*|\*)?((?:[#.][\w-]+|\[[\w-]+(?:[~^$*]?="[^"]*")?\]|:not\([^()]*\)|:[\w-]+)*)$/;
  const parsed=pattern.exec(compound);if(!parsed)throw new SyntaxError(`Selector not supported by the test page: ${compound}`);
  if(parsed[1]&&parsed[1]!=="*"&&node.tagName!==parsed[1].toUpperCase())return false;
  for(const piece of parsed[2].match(/[#.][\w-]+|\[[^\]]+\]|:not\([^()]*\)|:[\w-]+/g)||[]){
   if(piece[0]==="#"){if(node.id!==piece.slice(1))return false;}
   else if(piece[0]==="."){if(!node.classList.contains(piece.slice(1)))return false;}
   else if(piece[0]==="["){
    const [,name,operator,value]=/^\[([\w-]+)(?:([~^$*]?=)"([^"]*)")?\]$/.exec(piece),actual=node.getAttribute(name);
    if(actual===null)return false;
    if(operator==="="&&actual!==value||operator==="^="&&!actual.startsWith(value)||operator==="*="&&!actual.includes(value)||operator==="$="&&!actual.endsWith(value)||operator==="~="&&!actual.split(/\s+/).includes(value))return false;
   }
   else if(piece.startsWith(":not(")){if(matchesCompound(node,piece.slice(5,-1)))return false;}
   else if(piece===":modal"){if(!(node.tagName==="DIALOG"&&node.open&&node.modal))return false;}
   else if(piece===":disabled"){if(!node.disabled)return false;}
   else if(piece===":checked"){if(!node.checked)return false;}
   else throw new SyntaxError(`Selector not supported by the test page: ${piece}`);
  }
  return true;
 }
 function matchesChain(node,compounds,direct){
  if(!matchesCompound(node,compounds.at(-1)))return false;
  if(compounds.length===1)return true;
  const rest=compounds.slice(0,-1);
  if(direct)return node.parentNode instanceof Element&&matchesChain(node.parentNode,rest,direct);
  for(let up=node.parentNode;up instanceof Element;up=up.parentNode)if(matchesChain(up,rest,direct))return true;
  return false;
 }
 Object.assign(document,{
  createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),createTextNode:value=>new Text(value),
  createDocumentFragment:()=>new Element("#fragment"),
  getElementById:id=>descendants(document.documentElement).find(node=>node.id===id)||null,
  querySelectorAll:selector=>document.documentElement.querySelectorAll(selector),
  querySelector:selector=>document.documentElement.querySelector(selector),
  addEventListener(type,listener){(document.listeners[type]??=[]).push({listener});},
  removeEventListener(type,listener){document.listeners[type]=(document.listeners[type]||[]).filter(entry=>entry.listener!==listener);}
 });
 return {document,Element,Text};
}

// index.html as the application ships it. Scripts and styles are not run or read here.
function parse(html,document){
 const root=document.createElement("html"),stack=[root],tags=/<!--[\s\S]*?-->|<!doctype[^>]*>|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s"'<>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>/gi;
 const decode=value=>value.replace(/&(amp|lt|gt|quot|#39|nbsp|middot|rarr|larr|hellip|mdash|ndash|times);|&#(\d+);|&#x([0-9a-f]+);/gi,(whole,name,decimal,hex)=>
  decimal?String.fromCodePoint(Number(decimal)):hex?String.fromCodePoint(parseInt(hex,16)):({amp:"&",lt:"<",gt:">",quot:'"',"#39":"'",nbsp:" ",middot:"·",rarr:"→",larr:"←",hellip:"…",mdash:"—",ndash:"–",times:"×"})[name.toLowerCase()]);
 let last=0,match;
 const text=until=>{const value=html.slice(last,until);if(value.trim())stack.at(-1).append(decode(value));};
 while((match=tags.exec(html))){
  text(match.index);last=tags.lastIndex;
  if(match[1]){
   const name=match[1].toUpperCase(),index=stack.findLastIndex(node=>node.tagName===name);
   if(index>0){
    // A text area starts with its content as its value; a list with its selected, else first, option.
    const closed=stack[index];
    if(name==="TEXTAREA")closed.value=closed.textContent;
    if(name==="SELECT"){const options=closed.querySelectorAll("option");closed.value=(options.find(option=>option.selected)||options[0])?.value||"";}
    stack.length=index;
   }
   continue;
  }
  if(!match[2])continue;
  const node=document.createElement(match[2]);
  for(const attribute of match[3].matchAll(/([^\s"'<>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g))node.setAttribute(attribute[1].toLowerCase(),decode(attribute[2]??attribute[3]??attribute[4]??""));
  stack.at(-1).append(node);
  const tag=match[2].toLowerCase();
  if(tag==="script"||tag==="style"){const end=html.toLowerCase().indexOf("</"+tag,last);last=tags.lastIndex=html.indexOf(">",end)+1;continue;}
  if(!VOID.has(tag)&&!match[4])stack.push(node);
 }
 return root;
}

// Opens the page and starts the application. options:
//   config   merged into the /api/config reply (api_configured true unless stated)
//   expose   names of functions and variables of app.js to hand to the test as page.t
//   hook     extra source run inside app.js just before init(), for a stand-in the test needs
//   narrow   true: the narrow layout, where Notes, Summary and Assets live in the Workspace sheet
//   modules  other files of web/ to load before app.js (for example ["concurrent-interview.js"])
async function open(options={}){
 const {document}=createDocument();
 document.documentElement=parse(fs.readFileSync(path.join(WEB,"index.html"),"utf8"),document);
 document.body=document.documentElement.querySelector("body");document.head=document.documentElement.querySelector("head");
 document.activeElement=document.body;
 const timers=new Map(),frames=[],requests=[],media=[];let serial=0,route=null,now=Date.UTC(2026,10,13,9,0,0);
 const setTimeout=(fn,ms=0)=>{const id=++serial;timers.set(id,{fn,ms:Number(ms)||0,at:now});return id;},clearTimeout=id=>{timers.delete(id);};
 const config={csrf_token:"synthetic-csrf",api_configured:true,data_notice:"Synthetic data notice.",version:"test",...options.config};
 const reply=value=>({ok:true,status:200,json:async()=>value,blob:async()=>new Blob([])});
 const fetch=async(url,init)=>{
  requests.push({url,options:init,body:typeof init?.body==="string"?JSON.parse(init.body):init?.body});
  if(url==="/api/config")return reply(config);
  const answer=route?await route(url,init,requests.at(-1).body):undefined;
  if(answer===undefined)throw new TypeError("No stand-in reply for "+url);
  return answer&&typeof answer.json==="function"?answer:reply(answer);
 };
 const window={document,setTimeout,clearTimeout,fetch,listeners:{},innerWidth:options.narrow?600:1440,innerHeight:900,
  addEventListener(type,listener){(this.listeners[type]??=[]).push(listener);},removeEventListener(){},
  matchMedia:query=>{const entry={query,matches:Boolean(options.narrow)&&/max-width/.test(query),addEventListener(){},removeEventListener(){}};media.push(entry);return entry;},
  requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},cancelAnimationFrame(){},
  speechSynthesis:{cancel(){},getVoices:()=>[],addEventListener(){},speak(){}},SpeechSynthesisUtterance:class{},
  navigator:{mediaDevices:null},location:{href:"http://127.0.0.1/",origin:"http://127.0.0.1"},getComputedStyle:()=>({paddingLeft:"0px",paddingRight:"0px"})};
 const context={window,document,console,fetch,setTimeout,clearTimeout,requestAnimationFrame:window.requestAnimationFrame,cancelAnimationFrame(){},
  navigator:window.navigator,getComputedStyle:window.getComputedStyle,confirm:message=>{page.confirms.push(message);return page.confirmAnswer;},
  Blob,TextEncoder,TextDecoder,URL:{createObjectURL:()=>"blob:synthetic",revokeObjectURL(){}},AbortController,DOMException,JSON,
  Date:class extends Date{constructor(...args){if(args.length)super(...args);else super(now);}static now(){return now;}},
  crypto:{randomUUID:()=>String(++serial).padStart(8,"0")+"-0000-4000-8000-000000000000"},structuredClone,MutationObserver:document.MutationObserver};
 vm.createContext(context);
 for(const name of options.modules||[])vm.runInContext(fs.readFileSync(path.join(WEB,name),"utf8"),context,{filename:name});
 const source=fs.readFileSync(path.join(WEB,"app.js"),"utf8");
 const names=["state","conversationUI","init",...String(options.expose||"").split(",").map(name=>name.trim()).filter(Boolean)];
 const seam=`${options.hook||""}\n  window.__page={${[...new Set(names)].join(",")}};\n})();`;
 const patched=source.replace(/  init\(\);\s*\}\)\(\);\s*$/,()=>seam);
 assert.notEqual(patched,source,"The test seam replaces only the application's start");
 vm.runInContext(patched,context,{filename:"app.js"});
 const flush=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
 const page={document,window,context,timers,requests,confirms:[],confirmAnswer:true,t:window.__page,state:window.__page.state,flush,reply,
  $:id=>{const node=document.getElementById(id);assert.ok(node,`The page has an element with id "${id}"`);return node;},
  route(fn){route=fn;},
  // Timers the application is waiting on, as [id, {fn, ms}]; run(entry) fires one as the clock would.
  waiting(test=()=>true){return [...timers].filter(([,timer])=>test(timer));},
  async run(entry){assert.ok(entry,"A timer is waiting");timers.delete(entry[0]);now+=entry[1].ms;await entry[1].fn();await flush();},
  advance(ms){now+=ms;},
  async frame(){for(const fn of frames.splice(0))fn(now);await flush();},
  text:id=>page.$(id).textContent.replace(/\s+/g," ").trim(),
  shown:id=>page.$(id).visible};
 await window.__page.init();await flush();
 return page;
}
module.exports={open,createDocument,parse};
