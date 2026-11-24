"use strict";
// Shared offline harness for the workflow canvas suites: the page's own web/workflow-graph.js in a
// fresh VM realm, a small DOM stand-in and the real bundled ELK. No browser, network or provider.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ELK=require('../../web/vendor/elk.bundled.js'),source=fs.readFileSync(path.join(__dirname,'../../web/workflow-graph.js'),'utf8');
const nativeTree=value=>JSON.parse(JSON.stringify(value));
// The browser builds the graph and runs the engine in one realm; normalize what crosses Node's VM boundary.
class RealmELK {constructor(){this.engine=new ELK();}layout(value){return this.engine.layout(nativeTree(value));}terminateWorker(){try{this.engine.terminateWorker?.();}catch{}}}
const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function environment(Engine=RealmELK,width=900,height=500){
 // keyboardFocus stands for the browser's own judgement that focus arrived from the keyboard (:focus-visible).
 const document={activeElement:null,keyboardFocus:false};
 class Element {
  constructor(tag){this.tagName=tag;this.ownerDocument=document;this.attributes={};this.style={setProperty(name,value){this[name]=value;}};this.children=[];this.listeners={};this.parentElement=null;this.clientWidth=width;this.clientHeight=height;this._text='';this.hidden=false;
   const names=()=>(this.attributes.class||'').split(' ').filter(Boolean),set=list=>{this.attributes.class=[...new Set(list)].join(' ');};
   this.classList={add:(...values)=>set([...names(),...values]),remove:(...values)=>set(names().filter(name=>!values.includes(name))),toggle:(value,on=!names().includes(value))=>set(on?[...names(),value]:names().filter(name=>name!==value)),contains:value=>names().includes(value)};}
  contains(other){for(let node=other;node;node=node.parentElement)if(node===this)return true;return false;}
  hasPointerCapture(){return false;}
  setAttribute(k,v){this.attributes[k]=String(v);}getAttribute(k){return this.attributes[k]??null;}removeAttribute(k){delete this.attributes[k];}
  append(...values){values.forEach(value=>{value.parentElement=this;this.children.push(value);});}
  replaceChildren(...values){this.children.forEach(c=>c.parentElement=null);this.children=[];this._text='';this.append(...values);}
  remove(){const parent=this.parentElement;if(parent){parent.children=parent.children.filter(child=>child!==this);this.parentElement=null;}}
  set textContent(value){this.replaceChildren();this._text=String(value);}get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(f=>f!==fn);}
  emit(name,event={}){for(const fn of this.listeners[name]||[])fn({target:this,preventDefault(){},...event});}
  getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:this.clientHeight};}
  matches(selector){if(selector===':focus-visible')return document.keyboardFocus&&document.activeElement===this;if(selector[0]==='.')return (this.attributes.class||'').split(' ').includes(selector.slice(1));const attribute=selector.match(/^\[([^=\]]+)\]$/);return attribute?attribute[1] in this.attributes:this.tagName===selector;}
  querySelectorAll(selector){return this.children.flatMap(c=>[...(c.matches(selector)?[c]:[]),...c.querySelectorAll(selector)]);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  closest(selector){return this.matches(selector)?this:this.parentElement?.closest(selector)||null;}
  focus(){document.activeElement=this;this.emit('focus');}
  setPointerCapture(){}releasePointerCapture(){}
  cloneNode(deep){const copy=new Element(this.tagName);copy.attributes={...this.attributes};copy.style={...this.style};copy._text=this._text;if(deep)copy.append(...this.children.map(c=>c.cloneNode(true)));return copy;}
 }
 const serialize=e=>`<${e.tagName}${Object.entries(e.attributes).map(([k,v])=>` ${k}="${escape(v)}"`).join('')}>${escape(e._text)}${e.children.map(serialize).join('')}</${e.tagName}>`;
 document.createElementNS=(_,name)=>new Element(name);document.createElement=name=>new Element(name);
 document.body=new Element('body');document.hidden=false;document.addEventListener=()=>{};document.removeEventListener=()=>{};
 const window={ELK:Engine,document,XMLSerializer:class{serializeToString(e){return serialize(e);}}};
 document.defaultView=window;
 const context=vm.createContext({window,console});vm.runInContext(source,context);
 // Loads another of the page's scripts into the same realm.
 const load=file=>vm.runInContext(fs.readFileSync(path.join(__dirname,'../../web',file),'utf8'),context);
 const container=new Element('div');
 // What the reader can see: the step boxes that intersect the current view.
 const visible=canvas=>{const {x,y,scale}=canvas.camera,w=container.clientWidth/scale,h=container.clientHeight/scale;return canvas.layout.children.filter(n=>n.x+n.width>x&&n.x<x+w&&n.y+n.height>y&&n.y<y+h).map(n=>n.id);};
 const node=(canvas,id)=>canvas.world.querySelectorAll('[data-step-id]').find(el=>el.getAttribute('data-step-id')===id);
 return {api:window.CollectorWorkflow,container,document,window,visible,node,load};
}
// A fictional process of `count` steps in one line; `label` captions every arrow.
function chain(count,label=''){
 return {title:'Chain',steps:Array.from({length:count},(_,i)=>({id:`S${i+1}`,title:`Reported activity ${i+1}`,type:'activity',actor:'Packer'})),connections:Array.from({length:count-1},(_,i)=>({from:`S${i+1}`,to:`S${i+2}`,label}))};
}
module.exports={ELK,RealmELK,environment,nativeTree,chain};
