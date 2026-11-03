"use strict";
// Offline checks of actual UI rendering/navigation with a minimal DOM boundary.
// No browser, audio, provider, package or external network is used.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict"),path=require("node:path");
const roots=[],document={activeElement:null};
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.id="";this.className="";this.children=[];this.parentElement=null;this.dataset={};this.style={};this.attributes={};this.listeners={};this._text="";this.hidden=false;this.open=false;
  this.classList={contains:c=>this.className.split(/\s+/).includes(c),add:c=>this.classList.toggle(c,true),remove:c=>this.classList.toggle(c,false),toggle:(c,on)=>{const values=new Set(this.className.split(/\s+/).filter(Boolean));const yes=on===undefined?!values.has(c):on;if(yes)values.add(c);else values.delete(c);this.className=[...values].join(" ");return yes;}};
 }
 get textContent(){return this._text+this.children.map(c=>c.textContent).join("");}
 set textContent(value){this.replaceChildren();this._text=String(value);}
 get firstElementChild(){return this.children[0]||null;}
 get isConnected(){let node=this;while(node.parentElement)node=node.parentElement;return roots.includes(node);}
 append(...children){for(const child of children){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(c=>c!==child);child.parentElement=this;this.children.push(child);}}
 replaceChildren(...children){for(const child of this.children)child.parentElement=null;this.children=[];this._text="";this.append(...children);}
 setAttribute(name,value){this.attributes[name]=String(value);}
 getAttribute(name){return this.attributes[name]??null;}
 removeAttribute(name){delete this.attributes[name];}
 addEventListener(name,listener){(this.listeners[name]??=[]).push(listener);}
 dispatch(name){for(const listener of this.listeners[name]||[])listener({target:this});}
 contains(target){return target===this||this.children.some(child=>child.contains(target));}
 querySelector(selector){return walk(this).find(node=>node!==this&&matches(node,selector))||null;}
 focus(){const dialog=document.getElementById("foundation-dialog");if(dialog?.open&&!dialog.contains(this))throw Error("Focus attempted outside an open modal");document.activeElement=this;}
 scrollIntoView(){for(let node=this;node;node=node.parentElement)if(node.tagName==="DETAILS"&&!node.open)throw Error("Scrolled to hidden disclosure content");this.scrolled=true;}
 showModal(){this.open=true;document.activeElement=this;}
 close(){this.open=false;this.dispatch("close");}
}
function walk(root){return[root,...root.children.flatMap(walk)];}
function matches(node,selector){
 if(selector.startsWith("."))return node.classList.contains(selector.slice(1));
 if(selector==="[data-foundation-topic]")return typeof node.dataset.foundationTopic==="string";
 if(selector==="[data-review-target]")return typeof node.dataset.reviewTarget==="string";
 if(/^[a-z]+$/i.test(selector))return node.tagName===selector.toUpperCase();
 const selected=selector.match(/^\[data-foundation-topic="([^"]+)"\]$/);return Boolean(selected&&node.dataset.foundationTopic===selected[1]);
}
document.body=new Element("body");roots.push(document.body);
document.createElement=tag=>new Element(tag);
document.createElementNS=(_,tag)=>new Element(tag);
document.createTextNode=text=>{const node=new Element("#text");node.textContent=text;return node;};
document.getElementById=id=>walk(document.body).find(node=>node.id===id)||null;
document.querySelectorAll=selector=>walk(document.body).filter(node=>matches(node,selector));
document.querySelector=selector=>document.querySelectorAll(selector)[0]||null;
function mount(id,tag="div",parent=document.body){const node=new Element(tag);node.id=id;parent.append(node);return node;}
const interview=mount("interview-view"),review=mount("review-view"),current=mount("current-question","div",interview),history=mount("conversation-history","details",interview),scroll=mount("conversation-scroll","div",history);
mount("transcript","div",scroll);mount("history-count","span",history);
for(const id of ["coverage-list","coverage-count","coverage-progress","working-summary","summary-text","parking-panel","parking-count","parking-list","notice-text","global-notice","live-status","answer-text"])mount(id,"div",interview);
const setup=mount("setup-card","details",interview),form=mount("context-form","form",setup),contextDetails=mount("context-details","details",form);mount("process-name","input",form);
const dialog=mount("foundation-dialog","dialog");
for(const id of ["close-foundation-topic","foundation-topic-title","foundation-topic-status","foundation-topic-answer","foundation-topic-hint","foundation-topic-sources"])mount(id,id==="close-foundation-topic"?"button":"div",dialog);
const lifecycle=mount("review-lifecycles","details",review);
const sectionIds=["review-memo","review-map","review-procedure","review-lifecycles","review-variations","review-questions"];
for(const id of sectionIds){if(!document.getElementById(id))mount(id,"article",review);const button=mount(`review-tab-${id.slice(7)}`,"button",review);button.dataset.reviewTarget=id;}
const mapViewport=mount("process-map","div",document.getElementById("review-map"));mapViewport.clientWidth=780;
for(const id of ["map-zoom-out","map-zoom-in","map-fit","map-zoom-label"])mount(id,"button",document.getElementById("review-map"));
let providerCalls=0;
const context={console,document,Blob,DataView,Uint8Array,Date,JSON,setTimeout,clearTimeout,getComputedStyle:()=>({paddingLeft:"10px",paddingRight:"10px"}),requestAnimationFrame:fn=>fn(),fetch:()=>{providerCalls++;throw Error("Unexpected provider request");},window:{speechSynthesis:{},SpeechSynthesisUtterance:class{}}};
const source=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8")
 .replace(/  init\(\);\s*\}\)\(\);\s*$/,"  updateControls=()=>{}; window.__uiTests={state,renderTranscript,showFoundationTopic,initFoundationDialog,closeFoundationTopic,jumpToTurn,jumpToReview,tab,initReviewTabs,selectReviewSection,reviewTabKey,renderMap,zoomMap,fitMapToWidth};\n})();");
vm.createContext(context);vm.runInContext(source,context,{filename:"app.js"});
const t=context.window.__uiTests;if(!t)throw Error("UI test seam was not installed");t.initFoundationDialog();t.initReviewTabs();
let passes=0;
const turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"An email.\n<reported text, not markup>"},{id:"t003",role:"assistant",text:"What happens next?"}];
t.state.turns=turns;t.state.config={speech:{enabled:false}};t.renderTranscript();
assert.equal(current.firstElementChild.id,"turn-t003");assert.equal(current.querySelector(".turn-text").textContent,turns[2].text);
assert.equal(document.getElementById("transcript").children.length,2);assert.equal(document.getElementById("turn-t002").querySelector(".turn-text").textContent,turns[1].text);
assert.equal(new Set(walk(document.body).filter(node=>node.id.startsWith("turn-")).map(node=>node.id)).size,3);assert.equal(history.hidden,false);passes++;
{
 const retained=current.firstElementChild;t.state.turns.push({id:"t004",role:"user",text:"We log the request."});t.state.busy=true;t.renderTranscript();
 assert.equal(current.firstElementChild,retained,"Pending response must retain the current question element");assert.equal(document.getElementById("history-count").textContent,"3 messages");
 assert.equal(retained.querySelector(".play-turn").listeners.click.length,1);passes++;
}
{
 history.open=false;t.jumpToTurn("t002");assert.equal(history.open,true);assert.equal(document.activeElement.id,"turn-t002");assert.equal(document.activeElement.scrolled,true);passes++;
}
{
 t.state.memo_findings=[{key:"trigger",status:"captured",answer:"The participant reported an email.",evidence_turns:["t002"]}];
 t.state.draft={memo_summary:[{key:"trigger",status:"captured",answer:"A contradictory reviewer edit."}]};t.renderTranscript();
 const before=JSON.stringify(t.state),trigger=document.querySelector('[data-foundation-topic="trigger"]');t.showFoundationTopic("trigger",trigger);
 assert.equal(dialog.open,true);assert.equal(document.getElementById("foundation-topic-answer").textContent,"The participant reported an email.");
 assert.match(document.getElementById("foundation-topic-hint").textContent,/not independently verified/);assert.equal(JSON.stringify(t.state),before);
 const sources=document.getElementById("foundation-topic-sources");sources.querySelector(".evidence-link").dispatch("click");
 assert.equal(dialog.open,false);assert.equal(document.activeElement.id,"turn-t002","A modal source link must close before focusing its target");passes++;
}
{
 const button=document.querySelector('[data-foundation-topic="purpose"]');t.showFoundationTopic("purpose",button);
 assert.equal(document.getElementById("foundation-topic-status").textContent,"Unknown / TBD");assert.match(document.getElementById("foundation-topic-answer").textContent,/Not yet established/);
 t.closeFoundationTopic();assert.equal(document.activeElement,button);passes++;
}
{
 setup.open=false;contextDetails.open=false;t.jumpToTurn("context");assert.equal(setup.open,true);assert.equal(contextDetails.open,true);
 lifecycle.open=false;t.jumpToReview("review-lifecycles");assert.equal(lifecycle.open,true);assert.equal(document.activeElement,lifecycle);assert.equal(providerCalls,0);passes++;
}
{
 const manual=mount("draft-title","input",document.getElementById("review-procedure"));manual.value="Manually reviewed title";
 document.getElementById("answer-text").value="An unsent answer";const before=JSON.stringify(t.state);
 t.selectReviewSection("review-map");t.selectReviewSection("review-memo");t.selectReviewSection("review-procedure");
 assert.equal(document.getElementById("draft-title"),manual);assert.equal(manual.value,"Manually reviewed title");assert.equal(document.getElementById("answer-text").value,"An unsent answer");
 assert.equal(JSON.stringify(t.state),before,"Review tab selection must not rewrite domain state");
 assert.equal(sectionIds.filter(id=>!document.getElementById(id).hidden).length,1);assert.equal(document.getElementById("review-procedure").hidden,false);passes++;
}
{
 function key(from,key){let prevented=false;t.reviewTabKey({currentTarget:document.getElementById(`review-tab-${from}`),key,preventDefault:()=>prevented=true});assert.equal(prevented,true);}
 key("procedure","End");assert.equal(document.activeElement.id,"review-tab-questions");key("questions","ArrowRight");assert.equal(document.activeElement.id,"review-tab-memo");
 key("memo","ArrowLeft");assert.equal(document.activeElement.id,"review-tab-questions");key("questions","Home");assert.equal(document.activeElement.id,"review-tab-memo");
 assert.equal(sectionIds.filter(id=>document.getElementById(`review-tab-${id.slice(7)}`).tabIndex===0).length,1);
 assert.equal(document.getElementById("review-tab-memo").getAttribute("aria-selected"),"true");passes++;
}
{
 t.state.draft={title:"Reported route",steps:[{id:"S1",title:"Receive",actor:"Analyst",system:"Mailbox",type:"activity",description:"Reported input."},{id:"S2",title:"Review?",actor:"Reviewer",system:"Queue",type:"decision",description:"Reported decision."}],connections:[{from:"S1",to:"S2",label:"Received",evidence_turns:["t002"]}]};
 t.tab("review");t.selectReviewSection("review-map");t.renderMap();const svg=mapViewport.querySelector("svg");
 const snapshot=node=>({tag:node.tagName,attributes:node.attributes,text:node._text,children:node.children.map(snapshot)});
 const originalSVG=JSON.stringify(snapshot(svg)),originalDraft=JSON.stringify(t.state.draft);
 t.zoomMap(.25);assert.equal(mapViewport.querySelector(".map-stage").style.width,"950px");
 t.zoomMap(10);assert.equal(document.getElementById("map-zoom-label").textContent,"200%");t.zoomMap(-10);assert.equal(document.getElementById("map-zoom-label").textContent,"25%");
 t.fitMapToWidth();assert.equal(document.getElementById("map-zoom-label").textContent,"100%");
 assert.equal(JSON.stringify(snapshot(svg)),originalSVG,"Map UI zoom must leave serialized SVG geometry unchanged");assert.equal(JSON.stringify(t.state.draft),originalDraft);assert.equal(providerCalls,0);passes++;
}
console.log(JSON.stringify({tests_passed:passes,provider_calls:providerCalls,network_calls:0,real_browser:false}));
