"use strict";
// Offline checks of actual UI rendering/navigation with a minimal DOM boundary.
// No browser, audio, provider, package or external network is used.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict"),path=require("node:path");
const roots=[],document={activeElement:null,modalStack:[]};
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.id="";this.className="";this.value="";this.children=[];this.parentElement=null;this.dataset={};this.style={};this.attributes={};this.listeners={};this._text="";this.hidden=false;this.open=false;
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
 querySelectorAll(selector){return walk(this).filter(node=>node!==this&&selector.split(",").some(part=>matches(node,part.trim())));}
 querySelector(selector){return walk(this).find(node=>node!==this&&matches(node,selector))||null;}
 focus(){const dialog=document.modalStack.at(-1);if(dialog?.open&&!dialog.contains(this))throw Error("Focus attempted outside an open modal");document.activeElement=this;}
 scrollIntoView(){for(let node=this;node;node=node.parentElement)if(node.tagName==="DETAILS"&&!node.open)throw Error("Scrolled to hidden disclosure content");this.scrolled=true;}
 showModal(){if(!this.open)document.modalStack.push(this);this.open=true;document.activeElement=this;}
 close(){this.open=false;document.modalStack=document.modalStack.filter(dialog=>dialog!==this);this.dispatch("close");}
}
function walk(root){return[root,...root.children.flatMap(walk)];}
function matches(node,selector){
 if(selector.startsWith("."))return node.classList.contains(selector.slice(1));
 if(selector==="[data-foundation-topic]")return typeof node.dataset.foundationTopic==="string";
 if(selector==="[data-conversation-view]")return typeof node.dataset.conversationView==="string";
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
const interview=mount("interview-view"),review=mount("review-view"),current=mount("current-question","div",interview),history=mount("conversation-history","div",interview),scroll=mount("conversation-scroll","div",history);
mount("transcript","div",scroll);mount("history-count","span",history);
for(const id of ["coverage-list","coverage-count","coverage-progress","working-summary","summary-text","parking-panel","parking-count","parking-list","notice-text","global-notice","live-status","answer-text"])mount(id,"div",interview);
const setup=mount("setup-card","details",interview),form=mount("context-form","form",setup),settings=mount("interview-settings","dialog"),contextDetails=mount("context-details","details",settings);mount("process-name","input",form);
const memoSheet=mount("memo-sheet","dialog"),memoBody=mount("memo-sheet-body","div",memoSheet);mount("open-memo","button",interview);
const stepDialog=mount("workflow-step-dialog","dialog");for(const id of ["workflow-step-title","workflow-step-kind","workflow-step-content"])mount(id,"div",stepDialog);
for(const id of ["export-working-map","export-map"])mount(id,"button",interview);
const dialog=mount("foundation-dialog","dialog");
for(const id of ["close-foundation-topic","foundation-topic-title","foundation-topic-status","foundation-topic-answer","foundation-topic-hint","foundation-topic-sources"])mount(id,id==="close-foundation-topic"?"button":"div",dialog);
const lifecycle=mount("review-lifecycles","details",review);
const sectionIds=["review-report","review-memo","review-map","review-procedure","review-lifecycles","review-variations","review-questions"];
for(const id of sectionIds){if(!document.getElementById(id))mount(id,"article",review);const button=mount(`review-tab-${id.slice(7)}`,"button",review);button.dataset.reviewTarget=id;}
mount("report-content","div",document.getElementById("review-report"));
const mapViewport=mount("process-map","div",document.getElementById("review-map"));mapViewport.clientWidth=780;
for(const id of ["map-zoom-out","map-zoom-in","map-fit","map-zoom-label"])mount(id,"button",document.getElementById("review-map"));
for(const name of ["voice","transcript","workflow"]){
 if(!document.getElementById(name+"-panel"))mount(name+"-panel","section",interview);
 const button=mount("conversation-tab-"+name,"button",interview);button.dataset.conversationView=name;
}
for(const id of ["workflow-status","retry-workflow","retry-question","speak-questions","live-workflow","stop-speaking","voice-status","session-menu","session-menu-toggle","memo-focus","memo-next","coverage-mobile-count","coverage-summary","coverage-update-status","presence-status","session-presence","session-status","stop-live","mute-live"])mount(id,"div",interview);
for(const id of ["process-owner","objective","background","meeting-minutes"])mount(id,"input",contextDetails);
let providerCalls=0,serializations=0;
let timerId=0;const timers=new Map();
const localSetTimeout=(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;};
const localClearTimeout=id=>timers.delete(id);
const context={console,document,Blob,DataView,Uint8Array,Date,JSON,AbortController,confirm:()=>true,XMLSerializer:class{serializeToString(){serializations++;return "old-svg-fallback";}},setTimeout:localSetTimeout,clearTimeout:localClearTimeout,getComputedStyle:()=>({paddingLeft:"10px",paddingRight:"10px"}),requestAnimationFrame:fn=>fn(),fetch:()=>{providerCalls++;throw Error("Unexpected provider request");},window:{speechSynthesis:{cancel:()=>{}},SpeechSynthesisUtterance:class{}}};
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const exportBindings=appSource.split("\n").filter(line=>/\$\("(?:export-working-map|export-map)"\)\.addEventListener/.test(line)).join("\n");
const titleBinding=appSource.match(/\$\("process-name"\)\.addEventListener\("input",\(\)=>\{[\s\S]*?\n    \}\);/)?.[0]||"";
const liveBindings=appSource.split("\n").filter(line=>/\$\("(?:stop-live|mute-live)"\)\.addEventListener/.test(line)).join("\n");
const source=appSource
 .replace(/  init\(\);\s*\}\)\(\);\s*$/,"  updateControls=()=>{updatePresence();}; window.__downloads=[]; download=(...args)=>window.__downloads.push(args); "+exportBindings+titleBinding+liveBindings+" window.__uiTests={resolveDocumentPurpose,skipQuestion,getPendingDocumentReason:()=>pendingDocumentReason,readingUI,refreshReadingSearch,moveReadingSearch,returnToSource,renderCoverage,state,renderTranscript,showFoundationTopic,initFoundationDialog,closeFoundationTopic,jumpToTurn,jumpToReview,tab,initReviewTabs,selectReviewSection,reviewTabKey,renderMap,renderWorkingMap,workflowCanvases,showWorkflowStep,updateCanvasControls,zoomMap,fitMapToWidth,conversationUI,selectConversationView,conversationTabKey,receiveLiveCaption,scheduleWorkflow,refreshWorkflow,clearState,sendAnswer,retryQuestion,setMemoSheet,setInterviewSettings,notice,applyInterview,markdown,memoMarkdown,normalizeDraft,ensureConversation,applyProcessTitle,documentContext,onDocumentEvent,snapshot,sessionObject,importSession,presenceState,updatePresence,startLiveConversation,setPresenceFake:value=>{gpfsPresence=value;},setDocumentController:value=>{documentController=value;},renderReport:typeof renderReport==='function'?renderReport:null,setRequest:fn=>{request=fn;}};\n})();");
vm.createContext(context);vm.runInContext(source,context,{filename:"app.js"});
const t=context.window.__uiTests;if(!t)throw Error("UI test seam was not installed");t.initFoundationDialog();t.initReviewTabs();
let passes=0;
const turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"An email.\n<reported text, not markup>"},{id:"t003",role:"assistant",text:"What happens next?"}];
t.state.turns=turns;t.state.config={speech:{enabled:false}};t.renderTranscript();
assert.equal(current.querySelector(".turn-text").textContent,turns[2].text);assert.equal(current.firstElementChild.id,"","Latest caption is separate from source-linked transcript entries");
assert.equal(document.getElementById("transcript").children.length,3);assert.equal(document.getElementById("turn-t002").querySelector(".turn-text").textContent,turns[1].text);
assert.equal(new Set(walk(document.body).filter(node=>node.id.startsWith("turn-")).map(node=>node.id)).size,3);assert.equal(history.hidden,false);passes++;
{
 const question=current.textContent;t.state.turns.push({id:"t004",role:"user",text:"We log the request."});t.state.busy=true;t.renderTranscript();
 assert.equal(current.textContent,question,"Pending response must keep the latest question visible");assert.equal(document.getElementById("history-count").textContent,"4 messages");
 assert.equal(document.getElementById("turn-t003").querySelector(".play-turn").listeners.click.length,1);passes++;
}
{
 t.selectConversationView("voice");t.jumpToTurn("t002");assert.equal(t.conversationUI.view,"transcript");assert.equal(document.getElementById("transcript-panel").hidden,false);assert.equal(document.activeElement.id,"turn-t002");assert.equal(document.activeElement.scrolled,true);passes++;
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
 setup.open=false;contextDetails.open=false;t.jumpToTurn("context");assert.equal(setup.open,true);assert.equal(contextDetails.open,true);assert.equal(settings.open,true);t.setInterviewSettings(false,false);
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
 key("procedure","End");assert.equal(document.activeElement.id,"review-tab-questions");key("questions","ArrowRight");assert.equal(document.activeElement.id,"review-tab-report");
 key("report","ArrowLeft");assert.equal(document.activeElement.id,"review-tab-questions");key("questions","Home");assert.equal(document.activeElement.id,"review-tab-report");
 assert.equal(sectionIds.filter(id=>document.getElementById(`review-tab-${id.slice(7)}`).tabIndex===0).length,1);
 assert.equal(document.getElementById("review-tab-report").getAttribute("aria-selected"),"true");passes++;
}
{
 t.state.draft={title:"Reported route",steps:[{id:"S1",title:"Receive",actor:"Analyst",system:"Mailbox",type:"activity",description:"Reported input."},{id:"S2",title:"Review?",actor:"Reviewer",system:"Queue",type:"decision",description:"Reported decision."}],connections:[{from:"S1",to:"S2",label:"Received",evidence_turns:["t002"]}]};
 t.tab("review");t.selectReviewSection("review-map");t.renderMap();const svg=mapViewport.querySelector("svg");
 const snapshot=node=>({tag:node.tagName,attributes:node.attributes,text:node._text,children:node.children.map(snapshot)});
 const originalSVG=JSON.stringify(snapshot(svg)),originalDraft=JSON.stringify(t.state.draft);
 const intrinsic=Number(mapViewport.querySelector(".map-stage").dataset.intrinsicWidth);
 t.zoomMap(.25);assert.equal(mapViewport.querySelector(".map-stage").style.width,`${intrinsic*1.25}px`);
 t.zoomMap(10);assert.equal(document.getElementById("map-zoom-label").textContent,"200%");t.zoomMap(-10);assert.equal(document.getElementById("map-zoom-label").textContent,"25%");
 t.fitMapToWidth();const fittedWidth=parseFloat(mapViewport.querySelector(".map-stage").style.width);
 assert.ok(fittedWidth<=760||fittedWidth===intrinsic*.25,"Fit must fit the available viewport unless minimum zoom is reached");
 assert.equal(JSON.stringify(snapshot(svg)),originalSVG,"Map UI zoom must leave serialized SVG geometry unchanged");assert.equal(JSON.stringify(t.state.draft),originalDraft);assert.equal(providerCalls,0);passes++;
}

// New reading/navigation behaviors are exercised without starting the app's voice paths.
{
 for(const kind of ["transcript","report"]){
  mount(kind+"-search","input");mount(kind+"-search-count","output");
  mount(kind+"-search-previous","button");mount(kind+"-search-next","button");
 }
 mount("source-return");mount("memo-next-action","button");mount("report-contents","select");
 t.state.turns=turns;t.renderTranscript();
 const input=document.getElementById("transcript-search");input.value="email";t.refreshReadingSearch("transcript");
 assert.equal(t.readingUI.transcript.matches.length,1);assert.equal(t.readingUI.transcript.matches[0].textContent,"email");
 assert.equal(document.getElementById("turn-t002").querySelector(".turn-text").textContent,turns[1].text,"Search must preserve source text and literal markup");
 input.value="what";t.refreshReadingSearch("transcript");assert.equal(t.readingUI.transcript.matches.length,2);
 t.moveReadingSearch("transcript",1);assert.equal(t.readingUI.transcript.index,1);t.moveReadingSearch("transcript",1);assert.equal(t.readingUI.transcript.index,0);
 input.value="absent";t.refreshReadingSearch("transcript");assert.equal(document.getElementById("transcript-search-count").textContent,"No matches");
 input.value="";t.refreshReadingSearch("transcript");assert.equal(t.readingUI.transcript.matches.length,0);assert.equal(t.readingUI.transcript.query,"");assert.equal(document.getElementById("transcript-search-count").textContent,"");passes++;
}
{
 review.hidden=false;interview.hidden=true;t.reviewUI;
 t.selectReviewSection("review-procedure");t.jumpToTurn("t002");
 assert.equal(t.conversationUI.view,"transcript");assert.equal(document.getElementById("source-return").hidden,false);
 t.returnToSource();assert.equal(review.hidden,false);assert.equal(document.getElementById("review-procedure").hidden,false);passes++;
}
{
 t.state.memo_findings=[{key:"materials",status:"not_applicable",answer:"No materials exist.",evidence_turns:["t002"]}];t.renderCoverage();
 const row=document.querySelector('[data-foundation-topic="materials"]');assert.equal(row.querySelector(".coverage-state").textContent,"Not applicable");
 const next=document.getElementById("memo-next-action");assert.equal(next.hidden,false);assert.match(next.textContent,/Name/);
 next.onclick();assert.equal(dialog.open,true);t.closeFoundationTopic(false);passes++;
}
{
 for(const id of ["interview-error","review-error"]){const region=mount(id);mount(id+"-message","span",region);}
 review.hidden=true;t.notice("Retry the retained answer.",true);
 const region=document.getElementById("interview-error");assert.equal(region.hidden,false);assert.equal(region.querySelector("span").textContent,"Retry the retained answer.");
 [...timers.values()].filter(timer=>timer.delay===3000).forEach(timer=>timer.fn());assert.equal(document.getElementById("global-notice").hidden,true);assert.equal(region.hidden,false,"Inline error persists after toast");passes++;
}

if(process.argv.includes("--usability-only")){
 (async()=>{
  review.hidden=false;interview.hidden=true;t.selectReviewSection("review-procedure");t.jumpToTurn("t002");t.returnToSource();
  assert.equal(document.activeElement.id,"review-tab-procedure","Returning to review restores visible keyboard focus");passes++;
  mount("settings-source-return","button");t.jumpToTurn("context");assert.equal(settings.open,true);assert.equal(document.getElementById("settings-source-return").hidden,false);t.returnToSource();assert.equal(settings.open,false);assert.equal(document.activeElement.id,"review-tab-procedure");passes++;
  {
   let finishRead,requests=0;t.state.started=true;t.state.busy=false;t.state.dirty=false;t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
   const oldTurns=JSON.stringify(t.state.turns);document.getElementById("answer-text").value="An unsent answer to preserve.";
   t.setRequest(async()=>{requests++;throw Error("No interview request is allowed during import");});
   const importing=t.importSession({size:4,text:()=>new Promise(resolve=>finishRead=resolve)});
   assert.equal(t.state.busy,true);assert.equal(t.state.importing,true);await t.sendAnswer({preventDefault(){}});
   assert.equal(requests,0);assert.equal(JSON.stringify(t.state.turns),oldTurns);finishRead("nope");await importing;
   assert.equal(t.state.busy,false);assert.equal(t.state.importing,false);assert.equal(JSON.stringify(t.state.turns),oldTurns);assert.equal(document.getElementById("answer-text").value,"An unsent answer to preserve.");passes++;
  }
  {
   timers.clear();t.state.context={process_name:"Old name"};t.state.config={api_configured:true};t.state.turns=[{id:"u1",role:"user",text:"We receive invoices."}];t.conversationUI.workflow={title:"Old name",steps:[],connections:[]};
   const revision=t.conversationUI.revision;document.getElementById("process-name").value="Renamed invoices";document.getElementById("process-name").dispatch("input");
   assert.equal(t.state.context.process_name,"Renamed invoices");assert.equal(t.conversationUI.workflow.title,"Renamed invoices");
   assert.equal(t.conversationUI.revision,revision);assert.equal([...timers.values()].some(timer=>timer.delay===1000),false,"Renaming alone must not schedule a paid workflow extraction");passes++;
  }
  {
   const retainedDraft=t.state.draft;timers.clear();t.state.started=true;t.state.busy=false;t.state.transcribing=false;t.state.requestingMic=false;t.state.recording=null;t.state.draft=null;t.state.context={process_name:"File purpose audit"};
   const base=[{id:"u1",role:"user",text:"We receive invoices."},{id:"a1",role:"assistant",text:"What starts the work?"}];
   const file={id:"doc_empty_audit",name:"Empty.csv",analysis:{intent_version:2,phase:"complete",disposition:"needs_reason",purpose_attempted:false,summary:"",acknowledgement:"File received. No readable source sections are available for review.",question:"What would you like me to look for in this file?",basis_turn_id:"u1",basis_question:base[1].text}};
   let files=[file],requests=[],refreshes=0;
   t.setDocumentController({exportState:()=>({scope:"scope_SYNTHETIC_AUDIT",documents:files}),refresh:()=>refreshes++});
   t.setRequest(async(url,payload)=>{requests.push({url,payload});return {};});
   document.getElementById("answer-text").value="";t.state.turns=JSON.parse(JSON.stringify(base));t.onDocumentEvent({type:"analysis",document:file});
   assert.match(t.state.turns.at(-1).text,/No readable source sections/);assert.equal(t.getPendingDocumentReason().questionId,t.state.turns.at(-1).id,"Purpose is bound to the question actually shown, even without an AI summary");
   await t.resolveDocumentPurpose("Please retain the blank template.");assert.equal(requests.length,1);assert.equal(requests[0].payload.id,file.id);assert.equal(requests[0].payload.purpose,"Please retain the blank template.");assert.equal(refreshes,1);assert.equal(t.getPendingDocumentReason(),null);passes++;
   // Every new fixture intent has an independent question. Completed tray actions,
   // removal, and a newer file intent must not consume an ordinary next answer.
   for(const changed of ["answered-in-files","removed","new-intent"]){
    const next=JSON.parse(JSON.stringify(file));next.analysis.intent_version++;
    t.state.turns=JSON.parse(JSON.stringify(base));files=[next];t.onDocumentEvent({type:"analysis",document:next});assert.ok(t.getPendingDocumentReason());
    if(changed==="answered-in-files")next.analysis={...next.analysis,disposition:"relevant",purpose_attempted:true};
    if(changed==="removed")files=[];
    if(changed==="new-intent")next.analysis.intent_version++;
    const before=requests.length;await t.resolveDocumentPurpose("An unrelated process answer.");assert.equal(requests.length,before,changed+" must not send a stale purpose");assert.equal(t.getPendingDocumentReason(),null);
    file.analysis.intent_version+=3;
   }passes++;
   {
    const next=JSON.parse(JSON.stringify(file));next.analysis.intent_version++;files=[next];t.state.turns=JSON.parse(JSON.stringify(base));t.onDocumentEvent({type:"analysis",document:next});
    t.onDocumentEvent({type:"question",document:{id:"doc_other_audit",name:"Other.csv",analysis:{disposition:"relevant"}},question:{text:"Who maintains this other tracker?",sources:[]}});
    const before=requests.length;await t.resolveDocumentPurpose("The AP manager.");assert.equal(requests.length,before);assert.equal(t.getPendingDocumentReason(),null);passes++;
   }
   {
    const next=JSON.parse(JSON.stringify(file));next.analysis.intent_version+=2;files=[next];t.state.turns=JSON.parse(JSON.stringify(base));t.onDocumentEvent({type:"analysis",document:next});assert.ok(t.getPendingDocumentReason());
    t.setRequest(async()=>{throw Error("Synthetic skip failure");});await t.skipQuestion();assert.equal(t.getPendingDocumentReason(),null,"An explicit skip clears file-purpose capture even if preparing the next topic fails");
    const before=requests.length;await t.resolveDocumentPurpose("The next ordinary answer.");assert.equal(requests.length,before);passes++;
   }
   t.setDocumentController(null);t.state.busy=false;t.state.draft=retainedDraft;t.conversationUI.typing=false;review.hidden=false;interview.hidden=true;
  }
  const retry=mount("map-retry-layout","button");let fail=true,updates=0;
  context.window.CollectorWorkflow={create:()=>({update:()=>{updates++;return fail?Promise.reject(Error("Layout unavailable")):Promise.resolve(true);},destroy:()=>{}})};
  t.workflowCanvases.clear();t.renderMap();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(retry.dataset.layoutRetry,"true");assert.equal(retry.hidden,false);assert.equal(document.getElementById("review-error").hidden,false);
  fail=false;t.renderMap();await new Promise(resolve=>setImmediate(resolve));assert.equal(updates,2);assert.equal(retry.hidden,true);assert.equal(document.getElementById("review-error").hidden,true);passes++;
  assert.equal(providerCalls,0);console.log(JSON.stringify({tests_passed:passes,provider_calls:0,voice_tests:0}));
 })().catch(error=>{console.error(error);process.exitCode=1;});
}else

(async()=>{
 t.state.busy=false;
 const graph=(title,steps=[{id:"S1",title:"Receive",evidence_turns:["t002"]}])=>({title,steps,connections:[],open_questions:[]});
 const checkpoint=()=>{timers.clear();t.conversationUI.flowTimer=null;};
 const workflowTimers=()=>[...timers.entries()].filter(([,timer])=>timer.delay===1000);
 {
  t.state.config={api_configured:true,speech:{enabled:false}};t.state.context={process_name:"Invoices"};
  t.conversationUI.workflow=null;checkpoint();const before=JSON.stringify(t.state),calls=providerCalls;
  for(const view of ["transcript","workflow","voice"]){t.selectConversationView(view);assert.equal(["voice","transcript","workflow"].filter(name=>!document.getElementById(name+"-panel").hidden).length,1);}
  assert.equal(JSON.stringify(t.state),before,"Changing views must not mutate interview data");
  assert.equal(timers.size,0,"Changing views must not schedule API calls");assert.equal(providerCalls,calls);
  let prevented=false;t.conversationTabKey({currentTarget:document.getElementById("conversation-tab-voice"),key:"End",preventDefault:()=>prevented=true});
  assert.equal(prevented,true);assert.equal(t.conversationUI.view,"workflow");assert.equal(document.activeElement.id,"conversation-tab-workflow");
  assert.equal(document.activeElement.getAttribute("aria-selected"),"true");passes++;
 }
 {
  checkpoint();let starts=0,stops=0,requests=0;
  const live={active:true,connected:true,start:()=>starts++,stop:()=>stops++},turns=t.state.turns,captions=t.conversationUI.captions;
  const graphBefore=t.conversationUI.workflow;const domainBefore=JSON.stringify(t.state);
  t.conversationUI.live=live;t.conversationUI.status="listening";
  scroll.scrollTop=120;scroll.scrollHeight=1000;scroll.clientHeight=350;
  document.getElementById("answer-text").value="An unsent note.";
  t.setRequest(async()=>{requests++;throw new Error("View selection must not make requests");});
  for(const view of ["workflow","transcript","voice","workflow","voice"]){t.selectConversationView(view);assert.equal(t.conversationUI.live,live);assert.equal(t.conversationUI.live.connected,true);}
  assert.equal(starts,0,"Switching representations must not start a second live session");assert.equal(stops,0,"Switching representations must not stop the active session");
  assert.equal(requests,0);assert.equal(timers.size,0);assert.equal(scroll.scrollTop,120,"Changing views must preserve the transcript reader's internal scroll position");assert.equal(t.conversationUI.captions,captions);assert.equal(t.state.turns,turns);assert.equal(t.conversationUI.workflow,graphBefore);
  assert.equal(JSON.stringify(t.state),domainBefore);assert.equal(document.getElementById("answer-text").value,"An unsent note.");assert.equal(t.conversationUI.status,"listening");
  t.conversationUI.live=null;t.conversationUI.status="idle";passes++;
 }
 {
  t.state.turns=[];t.state.version=0;t.state.dirty=false;t.conversationUI.captions=new Map();t.conversationUI.revision=0;t.conversationUI.applied=-1;checkpoint();
  t.receiveLiveCaption({id:"live_user",role:"user",text:"Invoices arrive by email.",final:false});
  const originalId=t.state.turns[0].id;
  t.receiveLiveCaption({id:"live_assistant",role:"assistant",text:"What happens next?",final:false});
  t.receiveLiveCaption({id:"live_user",role:"user",text:"Correction: invoices arrive in the portal.",final:true});
  assert.equal(t.state.turns.length,2,"Caption updates replace an existing turn rather than duplicating it");
  assert.equal(t.state.turns[0].id,originalId);assert.equal(t.state.turns[0].text,"Correction: invoices arrive in the portal.");
  assert.equal(document.getElementById("turn-"+originalId).querySelector(".turn-text").textContent,t.state.turns[0].text);
  const version=t.state.version,revision=t.conversationUI.revision;t.conversationUI.applied=revision;checkpoint();
  t.receiveLiveCaption({id:"live_user",role:"user",text:t.state.turns[0].text,final:true});
  assert.equal(t.state.version,version,"Repeated caption checkpoints must not mark unchanged text dirty");assert.equal(t.conversationUI.revision,revision);assert.equal(timers.size,0);passes++;
 }
 {
  checkpoint();t.conversationUI.workflow=graph("Earlier flow");t.conversationUI.applied=-1;t.conversationUI.flowBusy=false;
  const prior=t.conversationUI.workflow;let complete;let received;
  t.setRequest((url,payload)=>{assert.equal(url,"/api/workflow");received=payload;return new Promise(resolve=>complete=resolve);});
  const pending=t.refreshWorkflow();assert.equal(t.conversationUI.flowBusy,true);
  t.receiveLiveCaption({id:"live_user",role:"user",text:"Correction: invoices arrive by post.",final:true});
  complete({workflow:graph("Outdated email flow")});await pending;
  assert.equal(t.conversationUI.workflow,prior,"Responses based on superseded answers must never replace the graph");
  assert.equal(t.conversationUI.flowBusy,false);assert.equal(received.turns[0].text,"Correction: invoices arrive in the portal.","In-flight request must preserve its captured evidence");
  assert.equal(timers.size,1,"New evidence should schedule exactly one follow-up update");passes++;
 }
 {
  checkpoint();let complete;let signal;t.setRequest((url,payload,options)=>{signal=options.signal;return new Promise(resolve=>complete=resolve);});
  const pending=t.refreshWorkflow();const generation=t.state.generation;t.clearState();assert.equal(t.state.generation,generation+1);assert.equal(signal.aborted,true);
  complete({workflow:graph("Previous interview")});await pending;
  assert.equal(t.conversationUI.workflow,null,"A cleared interview must ignore late work from its predecessor");assert.equal(t.state.turns.length,0);assert.equal(t.conversationUI.flowBusy,false);passes++;
 }
 {
  checkpoint();t.state.turns=[{id:"t002",role:"user",text:"Old interview."}];t.state.context={process_name:"Old work"};t.conversationUI.applied=-1;
  const pendingRequests=[];t.setRequest(()=>new Promise(resolve=>pendingRequests.push(resolve)));
  const oldRequest=t.refreshWorkflow();t.clearState();t.state.turns=[{id:"t002",role:"user",text:"New interview."}];t.state.context={process_name:"New work"};
  const currentRequest=t.refreshWorkflow();assert.equal(pendingRequests.length,2);
  pendingRequests[0]({workflow:graph("Old graph")});await oldRequest;
  assert.equal(t.conversationUI.flowBusy,true,"Old finalization must not release a new interview's in-flight request");assert.equal(t.conversationUI.workflow,null);
  pendingRequests[1]({workflow:graph("New graph")});await currentRequest;assert.equal(t.conversationUI.workflow.title,"New graph");assert.equal(t.conversationUI.flowBusy,false);passes++;
 }
 {
  checkpoint();t.state.turns=[{id:"t002",role:"user",text:"Receive the paper invoice."}];t.state.context={process_name:"Invoices"};
  t.conversationUI.workflow=graph("Retained flow");t.conversationUI.applied=-1;const prior=t.conversationUI.workflow;
  t.setRequest(async()=>{throw new Error("Temporary failure");});await t.refreshWorkflow();
  assert.equal(t.conversationUI.workflow,prior,"Failure must retain the previous graph");assert.equal(document.getElementById("retry-workflow").hidden,false);assert.match(document.getElementById("workflow-status").textContent,/retained/);passes++;
 }
 {
  checkpoint();t.state.draft={title:"Owner-edited draft",steps:[{id:"manual",title:"Manual review step"}],connections:[]};t.state.draftEdited=true;
  const retained=t.state.draft,serialized=JSON.stringify(retained);t.conversationUI.applied=-1;
  t.setRequest(async()=>({workflow:graph("Updated paper route",[{id:"S2",title:"Receive paper invoice",evidence_turns:["t002"]}])}));await t.refreshWorkflow();
  assert.equal(t.conversationUI.workflow.title,"Updated paper route");assert.equal(t.conversationUI.workflow.steps.length,1);assert.equal(t.conversationUI.workflow.steps[0].id,"S2","A new graph fully replaces removed/edited working nodes");
  assert.equal(t.state.draft,retained);assert.equal(JSON.stringify(t.state.draft),serialized,"Live graph updates must not overwrite the owner-edited review draft");assert.equal(t.state.draftEdited,true);passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
  document.getElementById("answer-text").value="  A paper invoice arrives by post.  ";document.getElementById("retry-question").hidden=true;
  const calls=[];t.setRequest(async(url,payload)=>{calls.push({url,payload});if(url==="/api/interview")throw new Error("Invalid question metadata");return {workflow:graph("Paper invoice flow")};});
  let prevented=false;await t.sendAnswer({preventDefault:()=>prevented=true});
  assert.equal(prevented,true);assert.equal(t.state.busy,false);assert.equal(t.state.turns.length,2);
  assert.equal(t.state.turns[1].role,"user");assert.equal(t.state.turns[1].text,"A paper invoice arrives by post.");assert.equal(t.state.turns[1].id,"t002");
  assert.equal(document.getElementById("answer-text").value,"","Accepted answers must not remain as unsent duplicates after next-question failure");assert.equal(document.getElementById("retry-question").hidden,false);
  assert.match(document.getElementById("notice-text").textContent,/answer is kept/);assert.equal(calls.length,1);assert.equal(workflowTimers().length,1,"Accepted evidence must schedule a workflow update even if the next question fails");
  const [timerId,timer]=workflowTimers()[0];timers.delete(timerId);await timer.fn();
  assert.equal(calls[1].url,"/api/workflow");assert.equal(calls[1].payload.turns.filter(turn=>turn.role==="user").length,1);assert.equal(calls[1].payload.turns[1].text,"A paper invoice arrives by post.");
  assert.equal(t.conversationUI.workflow.title,"Paper invoice flow");passes++;
 }
 {
  checkpoint();const accepted=t.state.turns.find(turn=>turn.role==="user"),serialized=JSON.stringify(accepted),calls=[];
  t.setRequest(async(url,payload)=>{calls.push({url,payload});throw new Error("Question service unavailable");});
  await t.retryQuestion();assert.equal(t.state.turns.length,2);assert.equal(JSON.stringify(t.state.turns.find(turn=>turn.role==="user")),serialized);assert.equal(document.getElementById("retry-question").hidden,false);
  document.getElementById("answer-text").value="A separate, unsent detail.";
  t.setRequest(async(url,payload)=>{calls.push({url,payload});return {question:"Who opens the post?",coverage:[],memo_findings:[]};});
  await t.retryQuestion();assert.equal(t.state.turns.length,3);assert.equal(t.state.turns.filter(turn=>turn.role==="user").length,1,"Retrying must reuse accepted evidence rather than submitting it again");
  assert.equal(JSON.stringify(t.state.turns.find(turn=>turn.role==="user")),serialized);assert.equal(t.state.turns[2].text,"Who opens the post?");assert.equal(document.getElementById("retry-question").hidden,true);
  assert.equal(document.getElementById("answer-text").value,"A separate, unsent detail.","Retry must preserve a different unsent answer");
  for(const call of calls){assert.equal(call.url,"/api/interview");assert.equal(call.payload.turns.filter(turn=>turn.role==="user").length,1);assert.equal(call.payload.turns.find(turn=>turn.role==="user").id,accepted.id);}
  assert.equal(workflowTimers().length,0,"Question retry must not create redundant workflow requests");passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
  document.getElementById("answer-text").value="The vendor posts an invoice.";
  const calls=[];t.setRequest(async(url,payload)=>{calls.push({url,payload});return url==="/api/interview"?{question:"Who receives it?",coverage:[],memo_findings:[]}:{workflow:graph("Posted invoice")};});
  await t.sendAnswer({preventDefault(){}});assert.equal(t.state.turns.length,3);assert.equal(t.state.turns.filter(turn=>turn.role==="user").length,1);assert.equal(t.state.turns[2].text,"Who receives it?");
  assert.equal(document.getElementById("answer-text").value,"");assert.equal(document.getElementById("retry-question").hidden,true);assert.equal(t.state.busy,false);assert.equal(timers.size,1);
  const [timerId,timer]=workflowTimers()[0];timers.delete(timerId);await timer.fn();
  assert.equal(calls.length,2);assert.equal(calls[1].url,"/api/workflow");assert.equal(calls[1].payload.turns[1].text,"The vendor posts an invoice.");assert.equal(t.conversationUI.workflow.title,"Posted invoice");passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};t.conversationUI.view="transcript";
  scroll.scrollTop=120;scroll.scrollHeight=1000;scroll.clientHeight=350;
  t.receiveLiveCaption({id:"scroll-reader",role:"user",text:"The invoice arrives.",final:false});
  assert.equal(scroll.scrollTop,120,"New captions must not pull a reader away from earlier conversation");passes++;
  scroll.scrollTop=650;
  t.receiveLiveCaption({id:"scroll-reader",role:"user",text:"The invoice arrives by post.",final:false});
  assert.equal(scroll.scrollTop,scroll.scrollHeight,"Captions should follow automatically when the reader is already at the bottom");passes++;
 }
 const memoResult=(title,answer="A paper invoice arrives by post.")=>({workflow:graph(title),memo_findings:[{key:"trigger",status:"captured",answer,evidence_turns:["t002"]}],coverage:[{key:"trigger",status:"covered"}],summary:"Paper invoices are received by post.",focus:"Who opens incoming post",parking_lot:["Digital invoice intake is separate."]});
 const memoSnapshot=()=>JSON.stringify({findings:t.state.memo_findings,coverage:t.state.coverage,summary:t.state.summary,focus:t.state.focus,parking:t.state.parking_lot});
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A paper invoice arrives by post."}];
  t.state.memo_findings=[{key:"trigger",status:"unknown",answer:"Old trigger note.",evidence_turns:[]}];t.renderTranscript();
  const edited={title:"Owner-reviewed draft",steps:[],connections:[]},closure={asked:true,confirmed:false};t.state.draft=edited;t.state.draftEdited=true;t.state.closure=closure;
  const topic=document.querySelector('[data-foundation-topic="trigger"]');t.showFoundationTopic("trigger",topic);assert.equal(dialog.open,true);
  t.setRequest(async()=>memoResult("Current paper flow"));await t.refreshWorkflow();
  assert.equal(t.conversationUI.workflow.title,"Current paper flow");assert.equal(t.state.memo_findings.find(finding=>finding.key==="trigger").answer,"A paper invoice arrives by post.");
  assert.equal(t.state.coverage.find(item=>item.key==="trigger").status,"covered");assert.equal(t.state.summary,"Paper invoices are received by post.");assert.equal(t.state.focus,"Who opens incoming post");assert.equal(t.state.parking_lot[0],"Digital invoice intake is separate.");
  assert.equal(document.getElementById("coverage-count").textContent,"1 / 11");assert.equal(document.querySelector('[data-foundation-topic="trigger"]').classList.contains("covered"),true);
  assert.equal(dialog.open,true);assert.equal(document.getElementById("foundation-topic-answer").textContent,"A paper invoice arrives by post.","An open memo topic must reflect accepted live coverage updates");
  assert.equal(t.state.draft,edited);assert.equal(t.state.draftEdited,true);assert.equal(t.state.closure,closure,"Live coverage must not imply participant completeness confirmation");t.closeFoundationTopic();passes++;
 }
 {
  checkpoint();t.conversationUI.applied=-1;const priorGraph=t.conversationUI.workflow,priorMemo=memoSnapshot();let complete;
  t.setRequest(()=>new Promise(resolve=>complete=resolve));const pending=t.refreshWorkflow();
  t.receiveLiveCaption({id:"memo-correction",role:"user",text:"Correction: invoices arrive in person.",final:true});
  complete(memoResult("Superseded paper flow","A stale trigger answer."));await pending;
  assert.equal(t.conversationUI.workflow,priorGraph);assert.equal(memoSnapshot(),priorMemo,"Stale graph responses must not regress the memo rail");passes++;
 }
 {
  checkpoint();t.conversationUI.applied=-1;const priorGraph=t.conversationUI.workflow,priorMemo=memoSnapshot();
  const invalid=memoResult("Graph that must not be committed");invalid.memo_findings[0].evidence_turns=["missing_user_source"];
  t.setRequest(async()=>invalid);await t.refreshWorkflow();
  assert.equal(t.conversationUI.workflow,priorGraph,"Invalid memo evidence must prevent graph/rail partial commits");assert.equal(memoSnapshot(),priorMemo);assert.equal(document.getElementById("retry-workflow").hidden,false);passes++;
 }
 {
  checkpoint();t.conversationUI.applied=-1;const priorGraph=t.conversationUI.workflow,priorMemo=memoSnapshot();
  t.setRequest(async()=>{throw new Error("Metadata request failed");});await t.refreshWorkflow();
  assert.equal(t.conversationUI.workflow,priorGraph);assert.equal(memoSnapshot(),priorMemo,"Provider failures must retain prior graph and memo coverage together");passes++;
 }
 {
  checkpoint();t.conversationUI.applied=-1;let complete;t.setRequest(()=>new Promise(resolve=>complete=resolve));const pending=t.refreshWorkflow();t.clearState();const clearedMemo=memoSnapshot();
  complete(memoResult("Prior interview memo"));await pending;
  assert.equal(t.conversationUI.workflow,null);assert.equal(memoSnapshot(),clearedMemo,"A cleared interview must ignore late memo coverage from an older session");assert.equal(document.getElementById("coverage-count").textContent,"0 / 11");passes++;
 }
 {
  checkpoint();t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"A paper invoice arrives."}];t.state.context={process_name:"Invoices"};t.renderTranscript();
  t.setMemoSheet(true);assert.equal(memoSheet.open,true);t.tab("review",true);
  assert.equal(memoSheet.open,false,"Review navigation must close the mobile memo sheet before focusing background content");assert.equal(document.activeElement,review);passes++;
 }
 {
  checkpoint();t.tab("interview");const coverageList=document.getElementById("coverage-list"),originalParent=coverageList.parentElement;memoBody.append(coverageList);
  t.state.memo_findings=[{key:"trigger",status:"captured",answer:"A paper invoice arrives.",evidence_turns:["t002"]}];t.renderTranscript();
  t.setMemoSheet(true);t.showFoundationTopic("trigger",document.querySelector('[data-foundation-topic="trigger"]'));
  assert.equal(document.modalStack.length,2);document.getElementById("foundation-topic-sources").querySelector(".evidence-link").dispatch("click");
  assert.equal(dialog.open,false);assert.equal(memoSheet.open,false,"Following a memo source must release the underlying mobile modal too");assert.equal(document.activeElement.id,"turn-t002");assert.equal(t.conversationUI.view,"transcript");
  originalParent.append(coverageList);passes++;
 }
 {
  checkpoint();t.renderTranscript();const oldTopic=document.querySelector('[data-foundation-topic="trigger"]');oldTopic.focus();
  t.receiveLiveCaption({id:"focus-retained",role:"user",text:"Then an analyst logs the invoice.",final:false});
  assert.notEqual(document.activeElement,oldTopic);assert.equal(document.activeElement.dataset.foundationTopic,"trigger");assert.equal(document.activeElement.isConnected,true,"Live transcript updates must preserve keyboard focus on a replacement memo topic button");
  t.showFoundationTopic("trigger",document.activeElement);const modalFocus=document.activeElement;
  t.receiveLiveCaption({id:"focus-retained",role:"user",text:"Then an analyst logs the invoice in a register.",final:false});
  assert.equal(document.activeElement,modalFocus,"Live rail updates must never steal focus from the open topic dialog");t.closeFoundationTopic();passes++;
 }
 {
  checkpoint();t.notice("An ordinary update.");assert.equal(document.getElementById("global-notice").hidden,false);
  const pending=[...timers.entries()].filter(([,timer])=>timer.delay===3000);assert.equal(pending.length,1,"Every notification must schedule its dismissal after three seconds");
  const [id,timer]=pending[0];timers.delete(id);timer.fn();assert.equal(document.getElementById("global-notice").hidden,true);passes++;
 }
 {
  checkpoint();t.notice("First notification",true);const first=[...timers.entries()].find(([,timer])=>timer.delay===3000);assert.ok(first);
  t.notice("A newer notification");assert.equal(timers.has(first[0]),false,"A new message must cancel the previous message's dismiss timer");
  assert.equal(document.getElementById("notice-text").textContent,"A newer notification");assert.equal(document.getElementById("global-notice").classList.contains("error"),false);
  const pending=[...timers.entries()].filter(([,timer])=>timer.delay===3000);assert.equal(pending.length,1);assert.notEqual(pending[0][0],first[0]);
  timers.delete(pending[0][0]);pending[0][1].fn();assert.equal(document.getElementById("global-notice").hidden,true);passes++;
 }
 const memoKeys=["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials"];
 const completeFindings=()=>memoKeys.map(key=>({key,status:"captured",answer:`Reported ${key} detail.`,evidence_turns:["t002"]}));
 const interviewResult=findings=>({question:"Anything to correct?",ready_for_draft:true,coverage:memoKeys.map(key=>({key,status:"covered"})),memo_findings:findings,summary:"Reported process.",focus:"Completeness",parking_lot:[]});
 for(const incomplete of ["partial","unknown","missing"]){
  checkpoint();document.getElementById("global-notice").hidden=true;t.state.turns=[{id:"t002",role:"user",text:"Reported process facts."}];
  const findings=completeFindings();if(incomplete==="missing")findings.pop();else findings[5].status=incomplete;
  t.applyInterview(interviewResult(findings));assert.equal(document.getElementById("global-notice").hidden,true,`Model readiness must not surface an enough-detail notification with a ${incomplete} topic`);
  assert.notEqual(document.getElementById("coverage-count").textContent,"11 / 11",`An explicit ${incomplete} finding must not display a full coverage circle from a contradictory model coverage flag`);passes++;
 }
 {
  checkpoint();document.getElementById("global-notice").hidden=true;t.state.turns=[{id:"t002",role:"user",text:"Reported process facts."}];
  const findings=completeFindings();findings[7].status="not_applicable";findings[7].answer="The participant explicitly reported that variations do not apply.";
  t.applyInterview(interviewResult(findings));assert.equal(document.getElementById("global-notice").hidden,false,"All eleven full-circle topics may surface readiness, including explicit not-applicable findings");
  assert.match(document.getElementById("notice-text").textContent,/captured|enough detail|review|draft/i);
  const firstReadyTimer=[...timers.entries()].find(([,timer])=>timer.delay===3000)?.[0];t.applyInterview(interviewResult(findings));
  assert.equal([...timers.entries()].find(([,timer])=>timer.delay===3000)?.[0],firstReadyTimer,"Repeated complete snapshots must not keep re-announcing readiness");
  findings[3].status="partial";t.applyInterview(interviewResult(findings));assert.equal(document.getElementById("global-notice").hidden,true,"A correction that reopens a topic must withdraw a currently visible readiness notice");passes++;
 }
 {
  checkpoint();t.state.turns=[{id:"t002",role:"user",text:"Reported process facts."}];t.state.context={process_name:"Invoices"};t.conversationUI.applied=-1;t.conversationUI.readyAnnounced=false;
  document.getElementById("global-notice").hidden=true;t.setRequest(async()=>({...memoResult("Complete live process"),memo_findings:completeFindings(),coverage:memoKeys.map(key=>({key,status:"covered"}))}));
  await t.refreshWorkflow();assert.equal(document.getElementById("coverage-count").textContent,"11 / 11");assert.equal(document.getElementById("global-notice").hidden,false,"The live workflow/memo path must announce full coverage without relying on a typed-interview readiness flag");
  assert.match(document.getElementById("notice-text").textContent,/all 11|enough detail/i);passes++;
 }
 {
  checkpoint();t.state.context={process_name:"Invoice process",process_owner:"Accountable owner sentinel",objective:"Interview objective sentinel",background:"Existing materials sentinel"};
  t.state.turns=[{id:"t001",role:"assistant",text:"Interviewer question sentinel"},{id:"t002",role:"user",text:"Participant evidence sentinel"}];t.state.parking_lot=["Parked topic sentinel"];t.state.closure={asked:true,confirmed:false};
  t.state.draft=t.normalizeDraft({title:"Detailed invoice capture",overview:"Overview sentinel",trigger:"Trigger sentinel",inputs:["Input sentinel"],outputs:["Output sentinel"],memo_summary:completeFindings(),
   steps:[{id:"S1",title:"Receive *invoice*",actor:"Analyst sentinel",system:"Mailbox sentinel",description:"Reported step description sentinel",input:"Step input sentinel",output:"Step output sentinel",completion_criteria:"Completion criteria sentinel",handoff:"Next handoff sentinel",evidence_turns:["t002"]},{id:"S2",title:"Approve invoice",actor:"Manager",system:"Queue",description:"Approval step",input:"Pending invoice",output:"Approved invoice",completion_criteria:"Approval recorded",handoff:"Treasury",evidence_turns:["t002"]}],
   connections:[{from:"S1",to:"S2",label:"Decision route sentinel",evidence_turns:["t002"]}],lifecycle_items:[{item:"Lifecycle item sentinel",stages:["Lifecycle stage sentinel"],locations:["Lifecycle location sentinel"],handoffs:["Lifecycle handoff sentinel"],evidence_turns:["t002"]}],
   variations:[{applies_to:"Variation scope sentinel",difference:"Variation difference sentinel",reason:"Variation reason sentinel",cost:"Variation cost sentinel",charging:"Variation charging sentinel",removability:"Variation removability sentinel",boundary:"possibly_separate_work",boundary_reason:"Variation boundary reason sentinel",evidence_turns:["t002"]}],exceptions:["Exception sentinel"],controls:["Control sentinel"],open_questions:["Question one","Question two","Question three","Question four","Question five","Sixth open question sentinel"],validation_notes:["Validation note sentinel"]},t.state.turns);
  t.state.draftVersion=t.state.version-1;const before=JSON.stringify(t.state),procedure=t.markdown(),memo=t.memoMarkdown();
  for(const value of ["Accountable owner sentinel","Interview objective sentinel","Existing materials sentinel","Overview sentinel","Trigger sentinel","Input sentinel","Output sentinel","Analyst sentinel","Mailbox sentinel","Reported step description sentinel","Step input sentinel","Step output sentinel","Completion criteria sentinel","Next handoff sentinel","Decision route sentinel","Lifecycle item sentinel","Lifecycle stage sentinel","Lifecycle location sentinel","Lifecycle handoff sentinel","Variation scope sentinel","Variation difference sentinel","Variation reason sentinel","Variation cost sentinel","Variation charging sentinel","Variation removability sentinel","Variation boundary reason sentinel","Exception sentinel","Control sentinel","Sixth open question sentinel","Validation note sentinel","Parked topic sentinel","Participant evidence sentinel","Interviewer question sentinel"]){assert.ok(procedure.includes(value),`Complete Markdown export omitted: ${value}`);}
  for(const key of memoKeys)assert.ok(procedure.includes(`Reported ${key.replaceAll("_","\\_")} detail.`),`Missing memo topic ${key}`);
  assert.ok(memo.includes("Sixth open question sentinel"),"Standalone memo export must include every open question rather than truncate after five");
  assert.match(procedure,/new answers|changed|stale/i,"The export must disclose that the review draft predates newer conversation");
  assert.doesNotMatch(procedure,/Planned interview:|Elapsed active time:/,"Timing must not reappear in the user-facing export");
  assert.ok(procedure.includes("\\*invoice\\*"),"Reported Markdown characters must remain literal");assert.equal(JSON.stringify(t.state),before,"Export must not mutate accepted answers or reviewer edits");passes++;
 }
 {
  checkpoint();assert.equal(typeof t.renderReport,"function","The detailed Report renderer must be available");
  const before=JSON.stringify(t.state);t.selectReviewSection("review-report");const report=document.getElementById("report-content");
  for(const value of ["Accountable owner sentinel","Interview objective sentinel","Existing materials sentinel","Overview sentinel","Trigger sentinel","Input sentinel","Output sentinel","Receive *invoice*","Analyst sentinel","Mailbox sentinel","Reported step description sentinel","Step input sentinel","Step output sentinel","Completion criteria sentinel","Next handoff sentinel","Decision route sentinel","Lifecycle item sentinel","Lifecycle stage sentinel","Lifecycle location sentinel","Lifecycle handoff sentinel","Variation scope sentinel","Variation difference sentinel","Variation reason sentinel","Variation cost sentinel","Variation charging sentinel","Variation removability sentinel","Variation boundary reason sentinel","Exception sentinel","Control sentinel","Sixth open question sentinel","Validation note sentinel","Parked topic sentinel","Participant evidence sentinel","Interviewer question sentinel"]){assert.ok(report.textContent.includes(value),`Detailed Report omitted ${value}`);}
  for(const key of memoKeys)assert.ok(report.textContent.includes(`Reported ${key} detail.`),`Detailed Report omitted memo topic ${key}`);
  assert.equal(report.querySelector("input"),null);assert.equal(report.querySelector("textarea"),null);assert.equal(JSON.stringify(t.state),before,"Reading the Report must not mutate accepted facts or reviewer edits");
  t.selectReviewSection("review-procedure");t.state.draft.steps[0].description="Updated reviewer wording sentinel";const edited=JSON.stringify(t.state);
  t.selectReviewSection("review-report");assert.ok(report.textContent.includes("Updated reviewer wording sentinel"),"Reopening Report must show the latest reviewer wording");assert.equal(JSON.stringify(t.state),edited);passes++;
 }
 const nextMicrotask=async()=>{await Promise.resolve();await Promise.resolve();};
 const fakeWorkflow=()=>{
  const made=[];
  context.window.CollectorWorkflow={create:(container,options)=>{
   const canvas={container,options,pending:true,requests:[],destroyed:false,update(graph){
    this.pending=true;options.onViewChange({scale:1,hasGraph:true,updating:true});
    return new Promise((resolve,reject)=>this.requests.push({graph,resolve:value=>{this.pending=false;options.onViewChange({scale:1,hasGraph:true,updating:false});resolve(value);},reject}));
   },destroy(){this.destroyed=true;},refresh(){},exportSVG(){return this.pending?null:`<svg id="complete-${container.id}"/>`;}};made.push(canvas);return canvas;
  }};return made;
 };
 const finishCanvases=()=>{t.workflowCanvases.forEach(canvas=>canvas.destroy());t.workflowCanvases.clear();delete context.window.CollectorWorkflow;};
 {
  checkpoint();t.clearState();const made=fakeWorkflow();t.state.context={process_name:"Old process"};t.state.turns=[{id:"t002",role:"user",text:"Old evidence"}];
  t.renderMap(document.getElementById("live-workflow"),graph("Old map"));const old=made[0];t.clearState();assert.equal(old.destroyed,true);
  old.requests[0].reject(new Error("Old layout failed"));await nextMicrotask();assert.equal(document.getElementById("global-notice").hidden,true,"A layout failure after clearing must not notify or change the new interview");finishCanvases();passes++;
 }
 {
  checkpoint();document.getElementById("global-notice").hidden=true;const made=fakeWorkflow(),liveRoot=document.getElementById("live-workflow");
  t.renderMap(liveRoot,graph("Discarded controller"));const old=made[0];t.renderMap(liveRoot,graph("Empty",[]));t.renderMap(liveRoot,graph("Replacement controller"));const current=made[1];
  old.requests[0].reject(new Error("Discarded controller failed"));await nextMicrotask();assert.equal(document.getElementById("global-notice").hidden,true,"A superseded canvas controller must not report an error for the current map");
  assert.equal(t.workflowCanvases.get("live-workflow"),current);current.requests[0].resolve(true);await nextMicrotask();finishCanvases();passes++;
 }
 {
  checkpoint();document.getElementById("global-notice").hidden=true;const made=fakeWorkflow(),data=graph("Retained process");
  t.renderMap(document.getElementById("live-workflow"),data);made[0].requests[0].reject(new Error("Current layout failed"));await nextMicrotask();
  assert.equal(document.getElementById("global-notice").hidden,false);assert.match(document.getElementById("notice-text").textContent,/captured process is retained/);assert.match(document.getElementById("workflow-status").textContent,/paused/);assert.equal(data.steps[0].id,"S1");finishCanvases();passes++;
 }
 {
  checkpoint();const made=fakeWorkflow(),liveRoot=document.getElementById("live-workflow");t.state.turns=[{id:"t002",role:"user",text:"Reported evidence"}];
  const original=graph("Live process",[{id:"S1",title:"Old live title",description:"Old live detail",evidence_turns:["t002"]}]);
  t.renderMap(liveRoot,original);made[0].requests[0].resolve(true);await nextMicrotask();t.showWorkflowStep(original.steps[0],"live-workflow");assert.equal(stepDialog.open,true);
  t.renderMap(null,graph("Separate review graph",[{id:"S1",title:"Review-only title",description:"Review-only detail",evidence_turns:["t002"]}]));
  assert.equal(document.getElementById("workflow-step-title").textContent,"Old live title","A review graph update must not overwrite a detail dialog opened from the live graph");
  const corrected=graph("Corrected live process",[{id:"S1",title:"Corrected live title",description:"Corrected live detail",evidence_turns:["t002"]}]);t.renderMap(liveRoot,corrected);
  assert.equal(stepDialog.open,true);assert.equal(document.getElementById("workflow-step-title").textContent,"Corrected live title");assert.ok(document.getElementById("workflow-step-content").textContent.includes("Corrected live detail"));
  t.conversationUI.workflow=graph("All facts withdrawn",[]);t.renderWorkingMap();assert.equal(stepDialog.open,false,"Removing all working steps must close a dialog for a step that no longer exists");assert.equal(t.workflowCanvases.has("live-workflow"),false);assert.equal(document.getElementById("export-working-map").disabled,true);finishCanvases();passes++;
 }
 {
  checkpoint();const made=fakeWorkflow();context.window.__downloads.length=0;const beforeSerializations=serializations;
  t.state.context={process_name:"Invoices"};t.state.draft=graph("Current review graph");
  t.renderMap(document.getElementById("live-workflow"),graph("Current working graph"));t.renderMap();
  mapViewport.append(document.createElementNS("http://www.w3.org/2000/svg","svg"));
  assert.equal(document.getElementById("export-working-map").disabled,true);assert.equal(document.getElementById("export-map").disabled,true,"Review SVG export must disable while current layout is pending");
  document.getElementById("export-working-map").dispatch("click");document.getElementById("export-map").dispatch("click");assert.equal(context.window.__downloads.length,0);assert.equal(serializations,beforeSerializations,"A pending graph canvas must never fall back to serializing old displayed SVG");
  made.forEach(canvas=>canvas.requests[0].resolve(true));await nextMicrotask();assert.equal(document.getElementById("export-working-map").disabled,false);assert.equal(document.getElementById("export-map").disabled,false);
  document.getElementById("export-working-map").dispatch("click");document.getElementById("export-map").dispatch("click");assert.equal(context.window.__downloads.length,2);assert.equal(context.window.__downloads[0][0],'<svg id="complete-live-workflow"/>');assert.equal(context.window.__downloads[1][0],'<svg id="complete-process-map"/>');assert.equal(serializations,beforeSerializations);
  for(const id of ["live-workflow","process-map"])t.updateCanvasControls(id,{scale:1,hasGraph:true,updating:false,exportReady:false});
  assert.equal(document.getElementById("export-working-map").disabled,true);assert.equal(document.getElementById("export-map").disabled,true,"A failed replacement layout must keep export disabled even while the old graph remains visible");finishCanvases();passes++;
 }
 const fileRecord=(overrides={})=>({id:"doc_ref1",name:"Reference.pdf",kind:"pdf",status:"ready",size:1234,coverage:{indexed_units:2,total_units:3,limitations:["A visual appendix could not be interpreted."]},analysis:{phase:"complete",disposition:"relevant",version:1,intent_version:1,summary:"Unconfirmed document summary sentinel",question:"Does the reported process use this approval?",questions:[],sources:[{source_id:"source_page2",label:"Reference.pdf · Page2"}],observations:[{text:"Unconfirmed document observation sentinel",sources:[{source_id:"source_page1",label:"Reference.pdf · Page1"}]}],limitations:["Formula values were not recalculated."]},...overrides});
 const fakeDocuments=(saved={scope:"scope_PRIVATE_REFERENCE",documents:[fileRecord()]})=>({saved:JSON.parse(JSON.stringify(saved)),resets:0,restores:[],exportState(){return JSON.parse(JSON.stringify(this.saved));},reset(){this.resets++;this.saved={scope:null,documents:[]};},async restoreState(value){this.restores.push(JSON.parse(JSON.stringify(value)));this.saved=JSON.parse(JSON.stringify(value));},refresh(){},open(){}});
 {
  checkpoint();t.setDocumentController(null);t.clearState();document.getElementById("process-name").value="";
  assert.equal(t.ensureConversation(),true,"Voice must be able to start before the process has a name");assert.equal(t.state.started,true);assert.equal(t.state.context.process_name,"");assert.equal(t.state.turns.length,0);assert.equal(timers.size,0);passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();t.applyProcessTitle("Invoice approval");assert.equal(t.state.context.process_name,"","A document or model title without a participant answer cannot name the process");
  t.state.turns=[{id:"t002",role:"user",text:"We approve vendor invoices."}];t.applyProcessTitle("Invoice approval");assert.equal(t.state.context.process_name,"Invoice approval");assert.equal(document.getElementById("process-name").value,"Invoice approval");
  const title=t.state.context.process_name;for(const generic of ["UNKNOWN","Untitled","Workflow","Not established"])t.applyProcessTitle(generic);assert.equal(t.state.context.process_name,title);
  assert.doesNotThrow(()=>t.applyProcessTitle("X".repeat(181)),"A valid long workflow title must not fail an otherwise accepted capture");assert.equal(t.state.context.process_name,title);passes++;
 }
 {
  checkpoint();document.getElementById("process-name").value="Owner's chosen title";document.getElementById("process-name").dispatch("input");assert.equal(t.state.processNameManual,true);t.applyProcessTitle("A model-proposed replacement");assert.equal(t.state.context.process_name,"Owner's chosen title");
  const saved=t.sessionObject();assert.equal(saved.process_name_manual,true);t.state.dirty=false;await t.importSession({size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)});
  assert.equal(t.state.processNameManual,true);assert.equal(t.state.context.process_name,"Owner's chosen title");t.applyProcessTitle("Another model title");assert.equal(t.state.context.process_name,"Owner's chosen title");passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();t.state.turns=[{id:"t002",role:"user",text:"We log invoices."}];t.applyProcessTitle("Automatically inferred title");
  const saved=t.sessionObject();assert.equal(saved.process_name_manual,false);t.state.dirty=false;await t.importSession({size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)});assert.equal(t.state.processNameManual,false);t.applyProcessTitle("More precise inferred title");assert.equal(t.state.context.process_name,"More precise inferred title");passes++;
 }
 {
  checkpoint();const docs=fakeDocuments();t.setDocumentController(docs);t.state.context={process_name:"Invoice process"};t.state.turns=[{id:"t002",role:"user",text:"Participant-confirmed intake."}];
  const capture=t.snapshot();assert.equal(capture.document_scope,"scope_PRIVATE_REFERENCE");assert.equal(Object.hasOwn(capture,"documents"),false);assert.equal(Object.hasOwn(capture,"document_facts"),false);
  const serialized=JSON.stringify(capture);assert.equal(serialized.includes("Unconfirmed document observation sentinel"),false);assert.equal(serialized.includes("Unconfirmed document summary sentinel"),false);assert.equal(serialized.includes("Reference.pdf"),false,"Provider snapshots pass a scope reference rather than embedding raw file metadata/content");t.setDocumentController(null);passes++;
 }
 {
  checkpoint();t.clearState();const before=t.conversationUI.revision;t.onDocumentEvent({type:"received",document:fileRecord()});
  assert.equal(t.state.turns.length,1);assert.equal(t.state.turns[0].role,"assistant");assert.equal(t.state.turns[0].document_event,true);assert.equal(t.state.turns[0].document_id,"doc_ref1");assert.equal(t.state.turns.some(turn=>turn.role==="user"),false);
  assert.equal(document.getElementById("coverage-count").textContent,"0 / 11");assert.equal(t.conversationUI.revision,before);assert.equal(t.documentContext().current_question,"");passes++;
 }
 {
  checkpoint();const base=[{id:"t002",role:"user",text:"A confirmed participant answer."},{id:"t003",role:"assistant",text:"A newer interview question?"}];
  const cases=[{name:"newer question",basis:"An older question?"},{name:"unanswered first question",basis:""},{name:"unsent answer",basis:"A newer interview question?",unsent:"Still composing a reply."},{name:"future participant answer",basis:"A newer interview question?",future:true},{name:"transcription in progress",basis:"A newer interview question?",transcribing:true},{name:"microphone permission in progress",basis:"A newer interview question?",requestingMic:true}];
  for(const item of cases){
   t.clearState();t.ensureConversation();t.state.turns=JSON.parse(JSON.stringify(base));if(item.future)t.state.turns.push({id:"t004",role:"user",text:"New participant evidence."});
   t.state.transcribing=Boolean(item.transcribing);t.state.requestingMic=Boolean(item.requestingMic);document.getElementById("answer-text").value=item.unsent||"";
   const before=JSON.stringify(t.state.turns),composer=document.getElementById("answer-text").value;const file=fileRecord();file.analysis={...file.analysis,basis_turn_id:"t002",basis_question:item.basis,acknowledgement:"I reviewed the file.",question:"A file follow-up?"};
   t.onDocumentEvent({type:"analysis",document:file,analysis:file.analysis});assert.equal(JSON.stringify(t.state.turns),before,`Late document analysis must not insert over ${item.name}`);assert.equal(document.getElementById("answer-text").value,composer);
  }t.state.transcribing=false;t.state.requestingMic=false;passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();t.state.turns=[{id:"t002",role:"user",text:"A participant answer."},{id:"t003",role:"assistant",text:"The original question?"}];
  const file=fileRecord();file.analysis={...file.analysis,basis_turn_id:"t002",basis_question:"The original question?",acknowledgement:"I reviewed the reference.",question:"Does that match what you do?"};
  t.onDocumentEvent({type:"analysis",document:file});const count=t.state.turns.length;t.onDocumentEvent({type:"analysis",document:file});
  assert.equal(count,3);assert.equal(t.state.turns.length,count,"Quick analysis must not append its question more than once");assert.equal(t.state.turns.at(-1).role,"assistant");assert.equal(t.state.turns.filter(turn=>turn.role==="user").length,1);assert.equal(document.getElementById("coverage-count").textContent,"0 / 11");passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();const docs=fakeDocuments();t.setDocumentController(docs);const beforeTurns=[{id:"t002",role:"user",text:"An actual participant answer."},{id:"t003",role:"assistant",text:"The saved current question?"}];t.state.turns=JSON.parse(JSON.stringify(beforeTurns));
  const saved=t.sessionObject();saved.unsent_answer="An unsent saved correction.";docs.restoreState=async function(value){this.restores.push(value);this.saved=JSON.parse(JSON.stringify(value));const file=fileRecord();file.analysis={...file.analysis,basis_turn_id:"t002",basis_question:"The saved current question?",acknowledgement:"New background review.",question:"A restored file question?"};t.onDocumentEvent({type:"analysis",document:file});};
  t.state.dirty=false;await t.importSession({size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)});assert.equal(docs.resets,1);assert.equal(docs.restores.length,1);assert.equal(JSON.stringify(t.state.turns),JSON.stringify(beforeTurns),"Restoring file metadata must not add a surprise question to the saved conversation");assert.equal(document.getElementById("answer-text").value,"An unsent saved correction.");
  const noComposer={...saved,unsent_answer:""};t.state.dirty=false;await t.importSession({size:JSON.stringify(noComposer).length,text:async()=>JSON.stringify(noComposer)});assert.equal(docs.resets,2);assert.equal(JSON.stringify(t.state.turns),JSON.stringify(beforeTurns),"Opening a saved interview with an empty composer must not auto-insert newly restored file questions either");
  t.clearState();assert.equal(docs.resets,3);assert.equal(t.state.turns.length,0);assert.equal(docs.saved.documents.length,0);t.setDocumentController(null);passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();t.state.turns=[{id:"t002",role:"user",text:"Participant facts remain separate."}];t.state.draft=t.normalizeDraft({title:"Reported process",steps:[],connections:[],memo_summary:[]},t.state.turns);t.state.draftVersion=t.state.version;
  const docs=fakeDocuments();t.setDocumentController(docs);const before=JSON.stringify(t.state),report=document.getElementById("report-content");t.renderReport();const exported=t.markdown();
  for(const value of ["Reference.pdf","Unconfirmed document summary sentinel","Unconfirmed document observation sentinel","A visual appendix could not be interpreted.","Formula values were not recalculated.","Reference.pdf · Page1","Reference.pdf · Page2","Does the reported process use this approval?"]){assert.ok(report.textContent.includes(value),`Report file appendix omitted ${value}`);assert.ok(exported.includes(value),`Markdown file appendix omitted ${value}`);}
  assert.ok(report.textContent.includes("not participant-confirmed process facts"));assert.ok(exported.includes("unconfirmed reference material"));assert.equal(report.textContent.includes("scope_PRIVATE_REFERENCE"),false);assert.equal(exported.includes("scope_PRIVATE_REFERENCE"),false,"Export must not disclose the local document capability token");assert.equal(JSON.stringify(t.state),before);t.setDocumentController(null);passes++;
 }
 {
  checkpoint();t.setDocumentController(null);t.clearState();let finishRestore;const docs=fakeDocuments();docs.restoreState=function(value){this.restores.push(value);return new Promise(resolve=>finishRestore=resolve);};t.setDocumentController(docs);
  const saved={schema_version:1,context:{process_name:"Old imported process",process_owner:"",objective:"Old objective",background:""},turns:[{id:"t002",role:"user",text:"Old imported participant answer."}],documents:{scope:"scope_OLD_REFERENCE",documents:[fileRecord()]},workflow:{title:"Old imported graph",steps:[{id:"S1",title:"Old step",evidence_turns:["t002"]}],connections:[]},unsent_answer:"Old imported unsent text."};
  t.state.dirty=false;const opening=t.importSession({size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)});await nextMicrotask();assert.equal(docs.restores.length,1);
  t.clearState({process_name:"New current interview",objective:"New objective"});t.ensureConversation();t.state.turns=[{id:"t002",role:"user",text:"New current participant answer."}];document.getElementById("answer-text").value="New current unsent text.";
  finishRestore();await opening;assert.equal(t.state.context.process_name,"New current interview");assert.equal(t.state.turns[0].text,"New current participant answer.");assert.equal(document.getElementById("answer-text").value,"New current unsent text.","A cancelled import must not overwrite a newer interview's composer when document restoration finishes");assert.equal(t.conversationUI.workflow,null,"A cancelled import must not revive its old workflow");t.setDocumentController(null);passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();t.state.turns=[{id:"t001",role:"assistant",text:"What happens next?"}];
  t.onDocumentEvent({type:"received",document:fileRecord()});
  assert.equal(document.getElementById("current-question").textContent,"What happens next?","A file receipt must not replace the question on the voice stage");
  assert.ok(document.getElementById("transcript").textContent.includes("File update"));
  assert.equal(document.getElementById("transcript").textContent.includes("Question 2"),false,"A receipt is not a numbered question");passes++;
 }
 {
  checkpoint();t.clearState();t.conversationUI.live=null;t.conversationUI.status="idle";
  const presence={states:[],visibility:[],audio:[],setState(value){this.states.push(value);},setVisible(value){this.visibility.push(value);},setAudio(value){this.audio.push(value);}};
  t.setPresenceFake(presence);t.state.started=true;t.updatePresence();assert.equal(presence.states.at(-1),"idle");
  t.conversationUI.flowBusy=true;t.updatePresence();assert.equal(presence.states.at(-1),"idle","Background workflow retrieval must not imply the conversation is processing");
  t.conversationUI.flowBusy=false;t.state.busy=true;t.updatePresence();assert.equal(presence.states.at(-1),"processing");assert.equal(document.getElementById("presence-status").textContent,"Processing…");
  t.state.busy=false;t.state.transcribing=true;t.updatePresence();assert.equal(presence.states.at(-1),"processing");
  t.state.transcribing=false;t.state.requestingMic=true;t.updatePresence();assert.equal(presence.states.at(-1),"connecting");
  t.state.requestingMic=false;t.state.recording={};t.updatePresence();assert.equal(presence.states.at(-1),"listening");
  t.state.recording=null;t.setPresenceFake(null);passes++;
 }
 {
  checkpoint();t.clearState();t.conversationUI.live=null;t.state.turns=[{id:"t001",role:"user",text:"Preserve my interview while I change views."}];t.renderTranscript();
  const visible=[],presence={setState(){},setVisible:value=>visible.push(value),setAudio(){}};t.setPresenceFake(presence);
  const before=JSON.stringify(t.state),transcript=document.getElementById("transcript").textContent;
  t.tab("interview");t.selectConversationView("voice");assert.equal(visible.at(-1),true);
  t.selectConversationView("transcript");assert.equal(visible.at(-1),false);t.selectConversationView("workflow");assert.equal(visible.at(-1),false);
  t.selectConversationView("voice");t.tab("review");assert.equal(visible.at(-1),false,"Review hides the audio renderer");
  t.tab("interview");assert.equal(visible.at(-1),true);document.hidden=true;t.updatePresence();assert.equal(visible.at(-1),false);document.hidden=false;t.updatePresence();assert.equal(visible.at(-1),true);
  assert.equal(JSON.stringify(t.state),before);assert.equal(document.getElementById("transcript").textContent,transcript,"Visibility changes preserve captured conversation");t.setPresenceFake(null);passes++;
 }
 {
  checkpoint();t.clearState();t.conversationUI.live=null;t.state.started=true;t.state.context={process_name:"Synthetic audio wiring",objective:"Preserve source facts"};t.state.config={api_configured:true,live:{enabled:true},speech:{enabled:false}};
  const presence={states:[],audio:[],visible:[],setState(value){this.states.push(value);},setAudio(value){this.audio.push(value);},setVisible(value){this.visible.push(value);}};t.setPresenceFake(presence);
  let callbacks,starts=0,stops=0;
  context.window.CollectorLiveVoice=class{
   constructor(options){callbacks=options;this.active=false;this.connected=false;}
   async start(){starts++;this.active=true;callbacks.onStatus("connecting");this.connected=true;callbacks.onStatus("listening");return true;}
   setMuted(value){callbacks.onStatus(value?"muted":"listening");}
   async stop(){stops++;this.active=false;this.connected=false;callbacks.onStatus("idle");return{finalized:true};}
  };
  await t.startLiveConversation();assert.equal(starts,1);assert.equal(presence.states.at(-1),"listening");assert.equal(t.conversationUI.status,"listening");
  const frame=Object.freeze({input:.2,output:.7,inputActive:true,outputActive:true,playbackActive:true,muted:false,connected:true});callbacks.onAudioFrame(frame);assert.equal(presence.audio.at(-1),frame,"The actual Live frame is forwarded without combining input and output");
  const audioCount=presence.audio.length;callbacks.onTranscript({id:"assistant_caption",role:"assistant",text:"An output caption can arrive before audible speech.",final:false});
  assert.equal(presence.states.at(-1),"listening");assert.equal(presence.audio.length,audioCount,"Captions cannot synthesize playback energy or a speaking state");assert.ok(t.state.turns.some(turn=>turn.text.includes("output caption")));
  callbacks.onStatus("speaking");assert.equal(presence.states.at(-1),"speaking");assert.equal(document.getElementById("presence-status").textContent,"Speaking");
  t.conversationUI.muted=true;t.updatePresence();assert.equal(document.getElementById("session-status").textContent,"Speaking · mic muted");
  callbacks.onStatus("muted");assert.equal(presence.states.at(-1),"muted");assert.equal(document.getElementById("presence-status").textContent,"Microphone muted");
  callbacks.onStatus("processing");assert.equal(presence.states.at(-1),"processing");callbacks.onStatus("listening");
  const transcript=JSON.stringify(t.state.turns);t.selectConversationView("transcript");assert.equal(presence.visible.at(-1),false);assert.equal(t.conversationUI.live.connected,true);assert.equal(stops,0,"Hiding the visual must not stop the audio session");
  t.selectConversationView("voice");t.tab("review");assert.equal(interview.hidden,false,"An active session keeps microphone controls accessible");assert.equal(presence.visible.at(-1),true);
  callbacks.onStatus("closing");assert.equal(presence.states.at(-1),"ended");assert.equal(document.getElementById("presence-status").textContent,"Finishing your transcript…");
  await document.getElementById("stop-live").listeners.click[0]({target:document.getElementById("stop-live")});
  assert.equal(stops,1);assert.equal(presence.states.at(-1),"ended");assert.equal(document.getElementById("presence-status").textContent,"Voice ended");assert.equal(JSON.stringify(t.state.turns),transcript,"Ending the session preserves transcript content");
  await t.startLiveConversation();assert.equal(starts,2);assert.equal(presence.states.at(-1),"listening","Continuing a conversation clears the ended posture");
  document.getElementById("mute-live").dispatch("click");assert.equal(t.conversationUI.muted,true);assert.equal(presence.states.at(-1),"muted");
  await document.getElementById("stop-live").listeners.click[0]({target:document.getElementById("stop-live")});t.clearState();assert.equal(presence.states.at(-1),"idle","A new interview resets the ended state");
  t.conversationUI.live=null;t.setPresenceFake(null);delete context.window.CollectorLiveVoice;passes++;
 }
 checkpoint();console.log(JSON.stringify({tests_passed:passes,provider_calls:providerCalls,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
