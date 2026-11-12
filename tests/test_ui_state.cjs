"use strict";
// Offline checks of actual UI rendering/navigation with a minimal DOM boundary.
// No browser, audio, provider, package or external network is used.
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict"),path=require("node:path");
const roots=[],document={activeElement:null,modalStack:[],listeners:{},addEventListener(name,listener){(this.listeners[name]??=[]).push(listener);}};
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.id="";this.className="";this.value="";this.children=[];this.parentElement=null;this.dataset={};this.style={};this.attributes={};this.listeners={};this._text="";this.hidden=false;this.open=false;
  this.classList={contains:c=>this.className.split(/\s+/).includes(c),add:c=>this.classList.toggle(c,true),remove:c=>this.classList.toggle(c,false),toggle:(c,on)=>{const values=new Set(this.className.split(/\s+/).filter(Boolean));const yes=on===undefined?!values.has(c):on;if(yes)values.add(c);else values.delete(c);this.className=[...values].join(" ");return yes;}};
 }
 get textContent(){return this._text+this.children.map(c=>c.textContent).join("");}
 set textContent(value){this.replaceChildren();this._text=String(value);}
 get firstElementChild(){return this.children[0]||null;}
 get isConnected(){let node=this;while(node.parentElement)node=node.parentElement;return roots.includes(node);}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}
 append(...children){for(const child of children){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(c=>c!==child);child.parentElement=this;this.children.push(child);}}
 replaceChildren(...children){for(const child of this.children)child.parentElement=null;this.children=[];this._text="";this.append(...children);}
 setAttribute(name,value){this.attributes[name]=String(value);}
 getAttribute(name){return this.attributes[name]??null;}
 removeAttribute(name){delete this.attributes[name];}
 addEventListener(name,listener){(this.listeners[name]??=[]).push(listener);}
 dispatch(name){for(const listener of this.listeners[name]||[])listener({target:this});}
 contains(target){return target===this||this.children.some(child=>child.contains(target));}
 closest(selector){for(let node=this;node;node=node.parentElement)if(matches(node,selector))return node;return null;}
 querySelectorAll(selector){return walk(this).filter(node=>node!==this&&selector.split(",").some(part=>matches(node,part.trim())));}
 querySelector(selector){return walk(this).find(node=>node!==this&&matches(node,selector))||null;}
 focus(){const dialog=document.modalStack.at(-1);if(dialog?.open&&!dialog.contains(this))throw Error("Focus attempted outside an open modal");document.activeElement=this;}
 scrollIntoView(options){this.scrollOptions=options;for(let node=this;node;node=node.parentElement)if(node.tagName==="DETAILS"&&!node.open)throw Error("Scrolled to hidden disclosure content");this.scrolled=true;}
 showModal(){if(!this.open)document.modalStack.push(this);this.open=true;document.activeElement=this;}
 close(){this.open=false;document.modalStack=document.modalStack.filter(dialog=>dialog!==this);this.dispatch("close");}
}
function walk(root){return[root,...root.children.flatMap(walk)];}
function matches(node,selector){
 if(selector.startsWith("."))return node.classList.contains(selector.slice(1));
 if(selector==="[data-foundation-topic]")return typeof node.dataset.foundationTopic==="string";
 if(selector==="[data-conversation-view]")return typeof node.dataset.conversationView==="string";
 if(selector==="[data-review-target]")return typeof node.dataset.reviewTarget==="string";
 if(selector==="[data-transcript-format]")return typeof node.dataset.transcriptFormat==="string";
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
mount("transcript","div",scroll);mount("transcript-dock-host","div",scroll);mount("history-count","span",history);
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
const context={console,document,Blob,DataView,Uint8Array,Date,JSON,AbortController,DOMException,confirm:()=>true,XMLSerializer:class{serializeToString(){serializations++;return "old-svg-fallback";}},setTimeout:localSetTimeout,clearTimeout:localClearTimeout,getComputedStyle:()=>({paddingLeft:"10px",paddingRight:"10px"}),requestAnimationFrame:fn=>fn(),fetch:()=>{providerCalls++;throw Error("Unexpected provider request");},window:{speechSynthesis:{cancel:()=>{}},SpeechSynthesisUtterance:class{}}};
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const exportBindings=appSource.split("\n").filter(line=>/\$\("(?:export-working-map|export-map)"\)\.addEventListener/.test(line)).join("\n");
const titleBinding=appSource.match(/\$\("process-name"\)\.addEventListener\("input",\(\)=>\{[\s\S]*?\n    \}\);/)?.[0]||"";
const liveBindings=appSource.split("\n").filter(line=>/\$\("(?:stop-live|mute-live)"\)\.addEventListener/.test(line)).join("\n");
const source=appSource
 .replace("  init();","  window.__sidebarTests={mapProjection,workflowGapSummary,openConnectionEditor,selectWorkflowMode,syncWorkflowVisibility,exportSession,generateDraft,memoUI,selectMemoSection,memoTabKey,initMemoTabs,openDocumentAssets,updateAssetCount,placeConversationDock,setTranscriptFind,setTranscriptExport,initTranscriptTools,updateConversationControls,exerciseControls:updateControls,appendDocumentMessage,realRequest:request,createIntake:()=>documentIntake=createDocumentIntake(),setIntake:value=>{documentIntake=value;}};\n  init();")
 .replace(/  init\(\);\s*\}\)\(\);\s*$/,"  updateControls=()=>{updatePresence();}; window.__downloads=[]; download=(...args)=>window.__downloads.push(args); "+exportBindings+titleBinding+liveBindings+" window.__uiTests={normalizeDocumentEvidence,normalizeFindings,boundedVoiceDocuments,sourceCaption,scrollToElement,dismissInlineError,dismissNotice,placeMemo,resolveDocumentPurpose,skipQuestion,getPendingDocumentReason:()=>pendingDocumentReason,readingUI,refreshReadingSearch,moveReadingSearch,returnToSource,renderCoverage,state,renderTranscript,showFoundationTopic,initFoundationDialog,closeFoundationTopic,jumpToTurn,jumpToReview,tab,initReviewTabs,selectReviewSection,reviewTabKey,renderMap,renderWorkingMap,workflowCanvases,showWorkflowStep,renderWorkflowLegend,retryWorkflowLayout,ensureWorkflowAssets,renderSteps,updateWorkflowNavigation,updateCanvasControls,zoomMap,fitMapToWidth,conversationUI,selectConversationView,conversationTabKey,receiveLiveCaption,scheduleWorkflow,refreshWorkflow,clearState,sendAnswer,retryQuestion,setMemoSheet,setInterviewSettings,notice,applyInterview,markdown,memoMarkdown,normalizeDraft,ensureConversation,applyProcessTitle,documentContext,onDocumentEvent,snapshot,sessionObject,importSession,presenceState,updatePresence,startLiveConversation,setPresenceFake:value=>{gpfsPresence=value;},setDocumentController:value=>{documentController=value;},renderReport:typeof renderReport==='function'?renderReport:null,setRequest:fn=>{request=fn;}};\n})();");
context.TextEncoder=TextEncoder;vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,"../web/controlled-voice.js"),"utf8"),context);vm.runInContext(source,context,{filename:"app.js"});
const t=context.window.__uiTests;if(!t)throw Error("UI test seam was not installed");Object.assign(t,context.window.__sidebarTests);t.initFoundationDialog();t.initReviewTabs();
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
 assert.equal(document.getElementById("foundation-topic-status").textContent,"Unknown");assert.match(document.getElementById("foundation-topic-answer").textContent,/Not covered yet/);
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
 t.state.draft={title:"Reported route",steps:[{id:"S1",title:"Receive "+"a complete long reported title ".repeat(12),actor:"Analyst "+"long owner ".repeat(12),system:"Mailbox "+"long system ".repeat(12),type:"activity",description:"Reported input in full."},{id:"S2",title:"Review?",actor:"Reviewer",system:"Queue",type:"decision",description:"Reported decision."}],connections:[{from:"S1",to:"S2",label:"Received with "+"a long route condition ".repeat(10),evidence_turns:["t002"]}]};
 t.tab("review");t.selectReviewSection("review-map");t.renderMap();
 const originalDraft=JSON.stringify(t.state.draft),fallback=mapViewport.querySelector(".workflow-fallback-list");
 assert.equal(mapViewport.querySelector("svg"),null,"Unavailable layout must not show a misleading simplified diagram");assert.match(mapViewport.textContent,/diagram couldn’t load/);assert.equal(fallback.children.length,2);
 for(const expected of [t.state.draft.steps[0].title,t.state.draft.steps[0].actor,t.state.draft.steps[0].system,t.state.draft.connections[0].label])assert(mapViewport.textContent.includes(expected),"Fallback must retain full reported text without truncation");
 assert.match(fallback.children[0].textContent,/→ S2 · Review/);assert.equal(fallback.children[1].querySelector(".workflow-fallback-routes"),null,"Fallback must not invent a next step for an unconnected component");
 t.zoomMap(.25);t.fitMapToWidth();assert.equal(document.getElementById("map-fit").disabled,true);assert.equal(document.getElementById("export-map").disabled,true);assert.equal(JSON.stringify(t.state.draft),originalDraft);assert.equal(providerCalls,0);passes++;
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

// Recovery and accessibility regression cases remain independent of voice paths.
{
 const originalTurns=t.state.turns;
 t.state.turns=[{id:"unicode1",role:"user",text:"Aİb [invoice.*] σΣ"}];t.renderTranscript();
 const search=document.getElementById("transcript-search");
 search.value="b";t.refreshReadingSearch("transcript");
 assert.equal(t.readingUI.transcript.matches.length,1);assert.equal(t.readingUI.transcript.matches[0].textContent,"b","Unicode case conversion must not shift later highlight offsets");
 search.value="[invoice.*]";t.refreshReadingSearch("transcript");
 assert.equal(t.readingUI.transcript.matches.length,1);assert.equal(t.readingUI.transcript.matches[0].textContent,"[invoice.*]","Search metacharacters are literal");
 assert.equal(document.getElementById("turn-unicode1").querySelector(".turn-text").textContent,"Aİb [invoice.*] σΣ");
 t.state.turns=originalTurns;search.value="";t.renderTranscript();passes++;
}
{
 const original=t.state.turns,search=document.getElementById("transcript-search"),ui=t.readingUI.transcript;
 const question={id:"q1",role:"assistant",text:"Where is the invoice?"};
 const answer={id:"a1",role:"user",text:"invoice ".repeat(499)+"<&>\n"};
 const receipt={id:"file",role:"assistant",document_event:true,text:"File received"};
 const final={id:"q2",role:"assistant",text:"Another invoice?"};
 t.state.turns=[question,answer,receipt,final];t.renderTranscript();
 const first=document.getElementById("turn-q1"),play=first.querySelector("button"),latest=current.firstElementChild;
 search.value="invoice";t.refreshReadingSearch("transcript",false);const firstMatch=ui.matches[0];
 assert.equal(ui.matches.length,500);assert.equal(document.getElementById("turn-q2").querySelector("mark"),null);
 play.focus();t.state.turns[1]={...answer,text:"invoice <&>\n"};t.renderTranscript();
 assert.equal(ui.matches[0],firstMatch);assert.equal(document.activeElement,play);assert.equal(first.isConnected,true);
 assert.equal(current.firstElementChild,latest);assert.equal(ui.matches.length,3);assert.equal(ui.matches[2].closest("article").id,"turn-q2");
 t.state.turns=[question,receipt,final];t.renderTranscript();
 assert.equal(ui.matches.length,2);assert.equal(firstMatch,ui.matches[0]);assert.equal(document.getElementById("turn-a1"),null);
 assert.equal(document.getElementById("turn-q2").querySelector(".turn-id").textContent,"Question 2");
 t.state.turns=[{...final,role:"user"},question,answer];t.renderTranscript();
 assert.equal(document.getElementById("turn-q2").querySelector(".turn-id").textContent,"Answer 1");
 assert.equal(document.getElementById("turn-q1").querySelector(".turn-id").textContent,"Question 1");
 assert.equal(document.getElementById("turn-a1").querySelector(".turn-id").textContent,"Answer 2");
 assert.equal(ui.matches.length,500);search.value="";t.refreshReadingSearch("transcript",false);
 assert.equal(document.getElementById("turn-a1").querySelector(".turn-text").textContent,answer.text);
 assert.equal(document.getElementById("transcript").querySelectorAll("mark").length,0);
 t.state.turns=original;t.renderTranscript();passes++;
}
{
 const report=document.getElementById("report-content"),search=document.getElementById("report-search");
 const text=mount("report-test-text","p",report),evidence=mount("report-test-source","p",report),link=mount("report-test-link","button",evidence);
 text.textContent="Invoice <123>\ninvoICE";link.textContent="Invoice source";
 search.value="invoice";t.refreshReadingSearch("report",false);
 assert.equal(t.readingUI.report.matches.length,2);assert.equal(evidence.firstElementChild,link);
 t.moveReadingSearch("report",1);assert.equal(t.readingUI.report.matches[1].classList.contains("current-match"),true);
 search.value="";t.refreshReadingSearch("report",false);
 assert.equal(text.textContent,"Invoice <123>\ninvoICE");assert.equal(text.querySelector("mark"),null);
 assert.equal(evidence.firstElementChild,link);text.remove();evidence.remove();passes++;
}
{
 t.state.started=true;t.selectConversationView("transcript");t.tab("review");t.tab("interview",true);
 assert.equal(document.activeElement.id,"conversation-tab-transcript");assert.equal(document.activeElement.tabIndex,0,"Returning to Interview keeps the selected tab in the keyboard entry order");
 if(!document.getElementById("workflow-expand"))mount("workflow-expand","button",interview);
 t.selectConversationView("workflow");interview.classList.add("workflow-expanded");t.tab("review");t.tab("interview",true);
 assert.equal(document.activeElement.id,"workflow-expand","Expanded workflow returns focus to its visible Collapse action");
 interview.classList.remove("workflow-expanded");t.selectConversationView("transcript");passes++;
}
{
 context.window.matchMedia=()=>({matches:true});t.jumpToTurn("t002");
 assert.equal(document.getElementById("turn-t002").scrollOptions.behavior,"auto","Reduced motion also applies to programmatic source/search scrolling");
 context.window.matchMedia=()=>({matches:false});t.jumpToTurn("t002");assert.equal(document.getElementById("turn-t002").scrollOptions.behavior,"smooth");
 const panel=document.getElementById("review-procedure");panel.setAttribute("tabindex","0");panel.tabIndex=0;t.jumpToReview("review-procedure");assert.equal(panel.tabIndex,0,"Section jumps preserve the panel's keyboard entry point");
 delete context.window.matchMedia;passes++;
}
{
 const region=document.getElementById("interview-error"),dismiss=mount("dismiss-error-test","button",region);
 region.hidden=false;t.tab("interview");t.selectConversationView("transcript");dismiss.focus();t.dismissInlineError("interview-error");
 assert.equal(region.hidden,true);assert.equal(document.activeElement.id,"conversation-tab-transcript","Dismissing an error cannot strand focus inside hidden content");assert.equal(document.activeElement.tabIndex,0);passes++;
}


{
 const list=document.getElementById("coverage-list"),parent=list.parentElement;t.renderCoverage();
 const topic=document.querySelector('[data-foundation-topic="trigger"]');t.showFoundationTopic("trigger",topic);
 memoBody.append(list);t.closeFoundationTopic();
 assert.equal(document.activeElement.id,"open-memo","Closing a topic after mobile resize must not focus a topic inside a closed memo sheet");parent.append(list);passes++;
}
{
 const region=document.getElementById("global-notice"),dismiss=mount("dismiss-notice-test","button",region);t.state.started=true;t.tab("interview");t.selectConversationView("transcript");
 t.notice("Temporary update");dismiss.focus();const pending=[...timers.values()].find(timer=>timer.delay===3000);assert.ok(pending);pending.fn();
 assert.equal(region.hidden,true);assert.equal(document.activeElement.id,"conversation-tab-transcript","A notification expiring while its close button is focused must restore visible keyboard focus");passes++;
}


{
 const list=document.getElementById("coverage-list"),parent=list.parentElement,host=mount("memo-host","div",interview),rail=mount("memo-rail","aside",host),close=mount("close-memo","button",memoSheet);rail.append(list);t.renderCoverage();
 const topic=document.querySelector('[data-foundation-topic="trigger"]');topic.focus();t.placeMemo(true);
 assert.equal(rail.parentElement,memoBody);assert.equal(document.activeElement.id,"open-memo","Narrowing the workspace must restore visible focus after moving the active topic into a closed dialog");
 t.setMemoSheet(true);close.focus();t.placeMemo(false);
 assert.equal(memoSheet.open,false);assert.equal(rail.parentElement,host);assert.equal(document.activeElement.dataset.foundationTopic,"name","Widening the workspace must not strand focus on the closed sheet's close button");
 t.showFoundationTopic("trigger",topic);const modalFocus=document.activeElement;t.placeMemo(true);assert.equal(document.activeElement,modalFocus,"Responsive memo placement must not steal focus from open topic details");t.closeFoundationTopic();parent.append(list);passes++;
}

{
 const rail=document.getElementById("memo-rail");t.placeMemo(false);
 for(const name of ["notes","summary","assets"]){const button=mount("memo-tab-"+name,"button",rail);button.dataset.memoSection=name;mount("memo-panel-"+name,"section",rail);}
 const count=mount("memo-assets-count","span",document.getElementById("memo-tab-assets"));mount("parking-empty");
 t.initMemoTabs();
 const before={turns:t.state.turns,coverage:t.state.coverage,workflow:t.conversationUI.workflow,view:t.conversationUI.view,busy:t.state.busy};
 document.getElementById("answer-text").value="Keep this unsent answer";
 const notes=document.getElementById("memo-panel-notes");notes.scrollTop=120;
 const key=(name,value)=>{let prevented=false;t.memoTabKey({currentTarget:document.getElementById("memo-tab-"+name),key:value,preventDefault(){prevented=true;}});return prevented;};
 assert.equal(key("notes","ArrowRight"),true);assert.equal(t.memoUI.section,"summary");assert.equal(document.activeElement.id,"memo-tab-summary");
 assert.equal(notes.hidden,true);assert.equal(document.getElementById("memo-panel-summary").hidden,false);
 assert.equal(document.getElementById("memo-tab-notes").tabIndex,-1);assert.equal(document.getElementById("memo-tab-summary").getAttribute("aria-selected"),"true");
 key("summary","End");assert.equal(t.memoUI.section,"assets");key("assets","ArrowRight");assert.equal(t.memoUI.section,"notes");key("notes","ArrowLeft");assert.equal(t.memoUI.section,"assets");key("assets","Home");
 assert.equal(key("notes","ArrowDown"),false);assert.equal(notes.scrollTop,120);assert.equal(document.getElementById("answer-text").value,"Keep this unsent answer");
 assert.deepEqual({turns:t.state.turns,coverage:t.state.coverage,workflow:t.conversationUI.workflow,view:t.conversationUI.view,busy:t.state.busy},before,"Sidebar navigation must not change the interview or workflow");passes++;

 t.selectMemoSection("summary",true);t.state.summary="Updated process summary";t.state.parking_lot=["Confirm the exception owner"];t.renderCoverage();
 assert.equal(t.memoUI.section,"summary");assert.equal(document.activeElement.id,"memo-tab-summary");assert.equal(document.getElementById("summary-text").textContent,"Updated process summary");assert.equal(document.getElementById("parking-empty").hidden,true);
 t.state.summary="";t.state.parking_lot=[];t.renderCoverage();assert.equal(document.getElementById("working-summary").hidden,false);assert.equal(document.getElementById("parking-empty").hidden,false);assert.equal(document.getElementById("parking-list").hidden,true);passes++;

 t.updateAssetCount({total:2,issues:1});assert.equal(count.textContent,"2");assert.equal(count.hidden,false);assert.match(document.getElementById("memo-tab-assets").getAttribute("aria-label"),/2 files, 1 file issue/);assert.equal(document.activeElement.id,"memo-tab-summary","File polling must not steal focus");
 t.updateAssetCount({total:0,issues:0});assert.equal(count.hidden,true);passes++;

 t.tab("review");t.openDocumentAssets();assert.equal(interview.hidden,false);assert.equal(t.memoUI.section,"assets");assert.equal(document.activeElement.id,"memo-tab-assets");
 interview.classList.add("workflow-expanded");t.openDocumentAssets();assert.equal(interview.classList.contains("workflow-expanded"),false,"Opening assets reveals a rail hidden by expanded workflow");passes++;

 t.placeMemo(true);t.openDocumentAssets();assert.equal(memoSheet.open,true);assert.equal(document.activeElement.id,"memo-tab-assets");assert.equal(t.memoUI.section,"assets");
 document.getElementById("close-memo").focus();t.placeMemo(false);assert.equal(memoSheet.open,false);assert.equal(document.activeElement.id,"memo-tab-assets","Resize returns focus to the selected section");assert.equal(t.memoUI.section,"assets");
 t.selectMemoSection("notes");document.getElementById("answer-text").value="";passes++;
}

{
 const host=mount("conversation-dock-host","div",interview),dock=mount("conversation-dock","div",host),action=mount("placement-action","button",dock),draft=mount("placement-draft","textarea",dock);
 const priorLive=t.conversationUI.live,priorView=t.conversationUI.view;let stopped=0,clicked=0;
 const live={active:true,stop(){stopped++;}};t.conversationUI.live=live;draft.value="Unsent answer survives view changes";action.addEventListener("click",()=>clicked++);
 t.selectConversationView("voice");assert.equal(dock.parentElement.id,"voice-panel");action.focus();
 t.selectConversationView("transcript");assert.equal(dock.parentElement.id,"transcript-dock-host");assert.equal(dock.parentElement.parentElement,scroll);assert.equal(document.activeElement,action);
 t.selectConversationView("workflow",true);assert.equal(dock.parentElement,host);assert.equal(document.activeElement.id,"conversation-tab-workflow");
 t.selectConversationView("voice");assert.equal(dock.parentElement.id,"voice-panel");assert.equal(draft.value,"Unsent answer survives view changes");action.dispatch("click");assert.equal(clicked,1);assert.equal(stopped,0);assert.equal(t.conversationUI.live,live);
 assert.equal(document.querySelectorAll("div").filter(node=>node.id==="conversation-dock").length,1,"View switches move the same controls rather than duplicating them");
 t.conversationUI.live=priorLive;t.selectConversationView(priorView);passes++;
}
{
 const priorTurns=t.state.turns,priorView=t.conversationUI.view,voice=document.getElementById("voice-panel");t.selectConversationView("voice");
 const longText="A detailed explanation of the process. ".repeat(150)+"The complete closing question stays available.";
 t.state.turns=[{id:"t901",role:"assistant",text:longText}];voice.scrollTop=400;t.renderTranscript();assert.equal(current.textContent,longText);assert.equal(voice.scrollTop,0,"A new response begins at its start");
 voice.scrollTop=180;t.state.turns[0].text+=" More live caption text.";t.renderTranscript();assert.equal(voice.scrollTop,180,"Streaming the same response cannot reset the user's reading position");
 t.state.turns.push({id:"t902",role:"assistant",text:"The next question."});t.renderTranscript();assert.equal(voice.scrollTop,0);assert.equal(current.textContent,"The next question.");
 t.state.turns=priorTurns;t.selectConversationView(priorView);t.renderTranscript();passes++;
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
   assert.equal(t.state.turns.at(-1).text,base[1].text,"An empty-file analysis does not interrupt the current interview");assert.equal(t.getPendingDocumentReason(),null);
   t.onDocumentEvent({type:"question",document:file,question:{text:file.analysis.question,sources:[]}});
   assert.match(t.state.turns.at(-1).text,/What would you like me to look for/);assert.equal(t.getPendingDocumentReason().questionId,t.state.turns.at(-1).id,"An explicitly selected purpose question is bound to the question actually shown");
   await t.resolveDocumentPurpose("Please retain the blank template.");assert.equal(requests.length,1);assert.equal(requests[0].payload.id,file.id);assert.equal(requests[0].payload.purpose,"Please retain the blank template.");assert.equal(refreshes,1);assert.equal(t.getPendingDocumentReason(),null);passes++;
   // Every new fixture intent has an independent question. Completed tray actions,
   // removal, and a newer file intent must not consume an ordinary next answer.
   for(const changed of ["answered-in-files","removed","new-intent"]){
    const next=JSON.parse(JSON.stringify(file));next.analysis.intent_version++;
    t.state.turns=JSON.parse(JSON.stringify(base));files=[next];t.onDocumentEvent({type:"question",document:next,question:{text:next.analysis.question,sources:[]}});assert.ok(t.getPendingDocumentReason());
    if(changed==="answered-in-files")next.analysis={...next.analysis,disposition:"relevant",purpose_attempted:true};
    if(changed==="removed")files=[];
    if(changed==="new-intent")next.analysis.intent_version++;
    const before=requests.length;await t.resolveDocumentPurpose("An unrelated process answer.");assert.equal(requests.length,before,changed+" must not send a stale purpose");assert.equal(t.getPendingDocumentReason(),null);
    file.analysis.intent_version+=3;
   }passes++;
   {
    const next=JSON.parse(JSON.stringify(file));next.analysis.intent_version++;files=[next];t.state.turns=JSON.parse(JSON.stringify(base));t.onDocumentEvent({type:"question",document:next,question:{text:next.analysis.question,sources:[]}});
    t.onDocumentEvent({type:"question",document:{id:"doc_other_audit",name:"Other.csv",analysis:{disposition:"relevant"}},question:{text:"Who maintains this other tracker?",sources:[]}});
    const before=requests.length;await t.resolveDocumentPurpose("The AP manager.");assert.equal(requests.length,before);assert.equal(t.getPendingDocumentReason(),null);passes++;
   }
   {
    const next=JSON.parse(JSON.stringify(file));next.analysis.intent_version+=2;files=[next];t.state.turns=JSON.parse(JSON.stringify(base));t.onDocumentEvent({type:"question",document:next,question:{text:next.analysis.question,sources:[]}});assert.ok(t.getPendingDocumentReason());
    t.setRequest(async()=>{throw Error("Synthetic skip failure");});await t.skipQuestion();assert.equal(t.getPendingDocumentReason(),null,"An explicit skip clears file-purpose capture even if preparing the next topic fails");
    const before=requests.length;await t.resolveDocumentPurpose("The next ordinary answer.");assert.equal(requests.length,before);passes++;
   }
   t.setDocumentController(null);t.state.busy=false;t.state.draft=retainedDraft;t.conversationUI.typing=false;review.hidden=false;interview.hidden=true;
  }
  {
   const oldTurns=[{id:"old1",role:"user",text:"Keep this current interview."}],saved={schema_version:1,context:{process_name:"Incoming",process_owner:"",objective:"Capture work",background:""},turns:[{id:"new1",role:"user",text:"An imported account."}],documents:{scope:"local_saved_scope",documents:[{id:"doc_import",name:"Report.pdf",analysis:{observations:"invalid list"}}]}};
   let resets=0,restores=0;t.setDocumentController({render(){},reset(){resets++;},restoreState:async()=>{restores++;throw Error("Invalid saved analysis");}});
   for(const malformed of ["observations","sources","non-finite"]){
    t.state.turns=oldTurns;t.state.started=true;t.state.dirty=false;t.state.busy=false;document.getElementById("answer-text").value="Retain unsent detail.";
    const incoming=JSON.parse(JSON.stringify(saved));if(malformed==="sources")incoming.documents.documents[0].analysis={sources:[null]};if(malformed==="non-finite"){incoming.documents.documents[0].analysis={};incoming.documents.documents[0].size=1;}
    let raw=JSON.stringify(incoming);if(malformed==="non-finite")raw=raw.replace('"size":1','"size":1e400');
    await t.importSession({size:raw.length,text:async()=>raw});
    assert.equal(t.state.turns,oldTurns,malformed+" must fail before replacing the interview");assert.equal(document.getElementById("answer-text").value,"Retain unsent detail.");assert.equal(t.state.busy,false);assert.equal(t.state.importing,false);
   }
   assert.equal(resets,0);assert.equal(restores,0);t.setDocumentController(null);passes++;
  }
  {
   const before=t.state.draft;t.state.draft=t.normalizeDraft({title:"File diagnostics",steps:[],connections:[],memo_summary:[],variations:[],lifecycle_items:[]});
   t.setDocumentController({exportState:()=>({documents:[{id:"doc_error",name:"Failed.pdf",error:{message:"The file could not be indexed."},coverage:{limitations:"Two pages were unreadable."},analysis:{error:{message:"Background review was paused."},limitations:["Tables require confirmation."]}}]})});
   t.renderReport();const report=document.getElementById("report-content").textContent;
   assert.match(report,/The file could not be indexed/);assert.match(report,/Background review was paused/);assert.match(report,/Two pages were unreadable/);assert.match(report,/Tables require confirmation/);assert.equal(report.includes("[object Object]"),false);
   const exported=t.markdown();assert.match(exported,/- Two pages were unreadable\./);assert.match(exported,/- The file could not be indexed\./);assert.match(exported,/- Background review was paused\./);assert.equal(exported.includes("object Object"),false);
   t.setDocumentController(null);t.state.draft=before;passes++;
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
  t.state.turns=[];t.state.memo_findings=[];t.state.version=0;t.state.dirty=false;t.conversationUI.captions=new Map();t.conversationUI.revision=0;t.conversationUI.applied=-1;checkpoint();
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
  assert.equal(t.conversationUI.workflow,prior,"Failure must retain the previous graph");assert.equal(document.getElementById("retry-workflow").hidden,false);assert.match(document.getElementById("workflow-status").textContent,/safe/);passes++;
 }
 {
  checkpoint();t.state.draft={title:"Owner-edited draft",steps:[{id:"manual",title:"Manual review step"}],connections:[]};t.state.draftEdited=true;
  const retained=t.state.draft,serialized=JSON.stringify(retained);t.conversationUI.applied=-1;
  t.setRequest(async()=>({workflow:graph("Updated paper route",[{id:"S2",title:"Receive paper invoice",evidence_turns:["t002"]}])}));await t.refreshWorkflow();
  assert.equal(t.conversationUI.workflow.title,"Updated paper route");assert.equal(t.conversationUI.workflow.steps.length,1);assert.equal(t.conversationUI.workflow.steps[0].id,"S2","The UI applies the backend's complete validated graph after explicit removals");
  assert.equal(t.state.draft,retained);assert.equal(JSON.stringify(t.state.draft),serialized,"Live graph updates must not overwrite the owner-edited review draft");assert.equal(t.state.draftEdited,true);passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};
  t.state.turns=[{id:"t002",role:"user",text:"A paper invoice arrives. AP logs it."}];
  const prior=t.normalizeDraft({title:"Invoice intake",steps:[{id:"S1",title:"Receive invoice",evidence_turns:["t002"]},{id:"S2",title:"Log invoice",evidence_turns:["t002"]}],connections:[{from:"S1",to:"S2",label:"Next",evidence_turns:["t002"]}],open_questions:["Who owns the register?"]});
  t.conversationUI.workflow=prior;t.conversationUI.applied=-1;
  t.state.memo_findings=[{key:"trigger",status:"captured",answer:"Paper invoice received.",evidence_turns:["t002"]}];
  t.state.summary="Invoice receipt and logging.";t.state.focus="Register ownership";t.state.parking_lot=["Electronic invoices later."];
  t.state.draft={title:"Private owner-edited draft",steps:[],connections:[]};
  let received,complete;t.setRequest((url,payload)=>{assert.equal(url,"/api/workflow");received=payload;return new Promise(resolve=>complete=resolve);});
  const pending=t.refreshWorkflow(),baseline=received.previous_capture;
  assert.deepEqual(Object.keys(baseline.workflow).sort(),["connections","open_questions","steps","title"]);
  assert.equal(baseline.workflow.steps.length,2);assert.equal(baseline.workflow.connections[0].to,"S2");
  assert.equal(baseline.workflow.open_questions[0],"Who owns the register?");assert.equal(baseline.memo_findings.length,16);
  assert.equal(baseline.memo_findings.find(f=>f.key==="trigger").answer,"Paper invoice received.");
  assert.equal(baseline.summary,"Invoice receipt and logging.");assert.equal(baseline.focus,"Register ownership");assert.equal(baseline.parking_lot[0],"Electronic invoices later.");
  assert.equal(Object.hasOwn(t.snapshot(),"previous_capture"),false,"General interview and voice snapshots must not carry workflow update state");
  assert.equal(JSON.stringify(received).includes("Private owner-edited draft"),false,"Only the working map is update context; the owner-edited draft stays separate");
  const capturedBefore=JSON.stringify(baseline);
  prior.steps[0].title="Changed after request";prior.steps[0].evidence_turns.push("context");prior.connections[0].label="Changed";prior.open_questions.push("A later question");
  t.state.memo_findings[0].answer="Changed after request";t.state.memo_findings[0].evidence_turns.push("context");t.state.parking_lot[0]="A later tangent";
  t.state.summary="Later summary";t.state.focus="Later focus";
  assert.equal(JSON.stringify(baseline),capturedBefore,"In-flight prior graph, memo and source arrays must be detached from live state");
  complete({workflow:graph("Accepted backend graph")});await pending;passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"New work"};
  t.state.turns=[{id:"t002",role:"user",text:"A fresh process starts."}];
  let received;t.setRequest(async(_url,payload)=>{received=payload;return {workflow:graph("Fresh process")};});await t.refreshWorkflow();
  const baseline=received.previous_capture;
  assert.equal(baseline.workflow.title,"");assert.equal(baseline.workflow.steps.length,0);assert.equal(baseline.workflow.connections.length,0);assert.equal(baseline.workflow.open_questions.length,0);
  assert.equal(baseline.memo_findings.length,16);assert.ok(baseline.memo_findings.every(f=>f.status==="unknown"&&f.evidence_turns.length===0));
  assert.equal(baseline.summary,"");assert.equal(baseline.focus,"");assert.equal(baseline.parking_lot.length,0,"A cleared interview cannot inherit a former process's map or memo");passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"}];
  document.getElementById("answer-text").value="  A paper invoice arrives by post.  ";document.getElementById("retry-question").hidden=true;
  const calls=[];t.setRequest(async(url,payload)=>{calls.push({url,payload});if(url==="/api/interview")throw new Error("Invalid question metadata");return {workflow:graph("Paper invoice flow")};});
  let prevented=false;await t.sendAnswer({preventDefault:()=>prevented=true});
  assert.equal(prevented,true);assert.equal(t.state.busy,false);assert.equal(t.state.turns.length,2);
  assert.equal(t.state.turns[1].role,"user");assert.equal(t.state.turns[1].text,"A paper invoice arrives by post.");assert.equal(t.state.turns[1].id,"t002");
  assert.equal(document.getElementById("answer-text").value,"","Accepted answers must not remain as unsent duplicates after next-question failure");assert.equal(document.getElementById("retry-question").hidden,false);
  assert.match(document.getElementById("notice-text").textContent,/answer is saved/);assert.equal(calls.length,1);assert.equal(workflowTimers().length,1,"Accepted evidence must schedule a workflow update even if the next question fails");
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
  assert.equal(calls.length,2);assert.equal(calls[1].url,"/api/workflow");assert.equal(calls[1].payload.turns[1].text,"The vendor posts an invoice.");assert.equal(t.conversationUI.workflow.title,"Posted invoice");
  assert.equal(Object.hasOwn(calls[0].payload,"previous_capture"),false,"Next-question requests use ordinary interview evidence only");
  assert.equal(Object.hasOwn(calls[1].payload,"previous_capture"),true,"Only workflow requests receive the editable capture baseline");passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};t.conversationUI.view="transcript";
  scroll.scrollTop=120;scroll.scrollHeight=1000;scroll.clientHeight=350;
  t.receiveLiveCaption({id:"scroll-reader",role:"user",text:"The invoice arrives.",final:false});
  assert.equal(scroll.scrollTop,120,"New captions must not pull a reader away from earlier conversation");passes++;
  scroll.scrollTop=650;
  t.receiveLiveCaption({id:"scroll-reader",role:"user",text:"The invoice arrives by post.",final:false});
  assert.equal(scroll.scrollTop,scroll.scrollHeight,"Captions should follow automatically when the reader is already at the bottom");passes++;
  scroll.scrollTop=120;
  t.applyInterview({question:"Which team receives it?",preserve_capture:true});
  assert.equal(scroll.scrollTop,120,"A delayed interviewer reply must respect a reader who scrolled back");
  scroll.scrollTop=650;
  t.applyInterview({question:"What happens on receipt?",coverage:[],memo_findings:[]});
  assert.equal(scroll.scrollTop,scroll.scrollHeight,"A reader at the latest answer should see the new question");passes++;
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
  assert.equal(document.getElementById("coverage-count").textContent,"1 / 16");assert.equal(document.querySelector('[data-foundation-topic="trigger"]').classList.contains("covered"),true);
  assert.equal(dialog.open,true);assert.equal(document.getElementById("foundation-topic-answer").textContent,"A paper invoice arrives by post.","An open memo topic must reflect accepted live coverage updates");
  assert.equal(t.state.draft,edited);assert.equal(t.state.draftEdited,true);assert.equal(t.state.closure,closure,"Live coverage must not imply participant completeness confirmation");t.closeFoundationTopic();passes++;
 }
 {
  checkpoint();t.conversationUI.applied=-1;const priorGraph=t.conversationUI.workflow,priorMemo=memoSnapshot();let complete;
  t.setRequest(()=>new Promise(resolve=>complete=resolve));const pending=t.refreshWorkflow();
  t.conversationUI.captions.set("user:memo-correction",["t002"]);
  t.receiveLiveCaption({id:"memo-correction",role:"user",text:"Correction: invoices arrive in person.",final:true});
  complete(memoResult("Superseded paper flow","A stale trigger answer."));await pending;
  assert.equal(t.conversationUI.workflow,priorGraph);assert.equal(memoSnapshot(),priorMemo,"A rewritten source must invalidate the graph and memo checkpoint together");passes++;
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
  assert.equal(t.conversationUI.workflow,null);assert.equal(memoSnapshot(),clearedMemo,"A cleared interview must ignore late memo coverage from an older session");assert.equal(document.getElementById("coverage-count").textContent,"0 / 16");passes++;
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
 const memoKeys=["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials","scope","rules","connections","data_systems","volume"];
 const completeFindings=()=>memoKeys.map(key=>({key,status:"captured",answer:`Reported ${key} detail.`,evidence_turns:["t002"]}));
 const interviewResult=findings=>({question:"Anything to correct?",ready_for_draft:true,coverage:memoKeys.map(key=>({key,status:"covered"})),memo_findings:findings,summary:"Reported process.",focus:"Completeness",parking_lot:[]});
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};
  t.state.turns=[{id:"t001",role:"assistant",text:"Tell me how invoices are handled."}];
  document.getElementById("global-notice").hidden=true;
  const requests=[];
  t.setRequest((url,payload)=>{assert.equal(url,"/api/workflow");return new Promise(resolve=>requests.push({payload,resolve}));});
  t.receiveLiveCaption({id:"continuous-user",role:"user",text:"The analyst receives invoices.",final:false});
  const firstTimer=workflowTimers()[0];assert.ok(firstTimer,"Nonfinal speech must schedule a workflow checkpoint");
  for(const suffix of [" Then", " Then the analyst", " Then the analyst logs them."]){
   t.receiveLiveCaption({id:"continuous-user",role:"user",text:"The analyst receives invoices."+suffix,final:false});
   assert.equal(workflowTimers()[0][0],firstTimer[0],"Continued speech must not postpone the existing checkpoint");
  }
  timers.delete(firstTimer[0]);const firstRequest=firstTimer[1].fn();
  assert.equal(requests.length,1);const capturedRevision=t.conversationUI.revision;
  t.receiveLiveCaption({id:"continuous-user",role:"user",text:"The analyst receives invoices. Then the analyst logs them. They use a register.",final:false});
  t.receiveLiveCaption({id:"next-user-answer",role:"user",text:"A manager reviews the logged invoice.",final:false});
  for(let i=0;i<5;i++)t.scheduleWorkflow();
  assert.equal(workflowTimers().length,0,"Speech during an active request queues through its revision, not parallel timers");
  assert.equal(requests.length,1,"At most one workflow request may run at a time");
  requests[0].resolve({...memoResult("Captured invoice receipt"),memo_findings:completeFindings(),coverage:memoKeys.map(key=>({key,status:"covered"}))});
  await firstRequest;
  assert.equal(t.conversationUI.workflow.title,"Captured invoice receipt","A checkpoint must render while later answers continue arriving");
  assert.equal(t.state.memo_findings.length,16,"The checkpoint commits its graph and memo together");
  assert.equal(t.conversationUI.applied,capturedRevision);assert.ok(t.conversationUI.applied<t.conversationUI.revision);
  assert.equal(document.getElementById("workflow-status").textContent,"Updating latest answers…");
  assert.equal(document.getElementById("coverage-update-status").textContent,"Updating latest answers…");
  assert.equal(document.getElementById("global-notice").hidden,true,"A superseded completeness checkpoint cannot announce readiness");
  assert.equal(t.conversationUI.readyAnnounced,false);
  const followup=workflowTimers();assert.equal(followup.length,1,"The latest pending evidence must have exactly one follow-up checkpoint");
  timers.delete(followup[0][0]);const latestRequest=followup[0][1].fn();assert.equal(requests.length,2);
  assert.equal(requests[1].payload.previous_capture.workflow.title,"Captured invoice receipt","A follow-up must use the checkpoint that just rendered as its omission-safe baseline");
  assert.ok(requests[1].payload.turns.some(turn=>turn.text==="A manager reviews the logged invoice."));
  assert.ok(requests[1].payload.turns.find(turn=>turn.id==="t002").text.endsWith("They use a register."));
  requests[1].resolve({...memoResult("Latest invoice route"),memo_findings:completeFindings(),coverage:memoKeys.map(key=>({key,status:"covered"}))});
  await latestRequest;
  assert.equal(t.conversationUI.workflow.title,"Latest invoice route");assert.equal(t.conversationUI.applied,t.conversationUI.revision);
  assert.equal(document.getElementById("workflow-status").textContent,"Up to date");assert.equal(workflowTimers().length,0);
  assert.equal(document.getElementById("global-notice").hidden,false,"Readiness may be announced only after the latest answers are captured");passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Invoices"};t.state.turns=[{id:"t002",role:"user",text:"Receive an invoice."}];
  const prior=graph("Last accepted map");t.conversationUI.workflow=prior;t.selectConversationView("voice");
  t.setRequest(async()=>{throw new Error("Private provider diagnostic must not appear in the UI");});
  await t.refreshWorkflow();assert.equal(t.conversationUI.workflow,prior);
  assert.equal(document.getElementById("global-notice").hidden,false,"Background failure must be visible while staying in Voice");
  assert.match(document.getElementById("notice-text").textContent,/diagram and notes.*haven’t updated.*transcript.*safe/i);
  assert.equal(document.getElementById("notice-text").textContent.includes("Private provider"),false);
  const firstNotice=[...timers.entries()].find(([,timer])=>timer.delay===3000);
  await t.refreshWorkflow();assert.equal([...timers.entries()].find(([,timer])=>timer.delay===3000)[0],firstNotice[0],"Repeated failures must not spam or extend the notification");
  t.setRequest(async()=>memoResult("Recovered map"));await t.refreshWorkflow();assert.equal(t.conversationUI.flowErrorNotified,false);
  t.conversationUI.revision++;t.setRequest(async()=>{throw new Error("Another outage");});await t.refreshWorkflow();
  assert.notEqual([...timers.entries()].find(([,timer])=>timer.delay===3000)[0],firstNotice[0],"A new failure after recovery may notify again");passes++;
 }
 for(const incomplete of ["partial","unknown","missing"]){
  checkpoint();document.getElementById("global-notice").hidden=true;t.state.turns=[{id:"t002",role:"user",text:"Reported process facts."}];
  const findings=completeFindings();if(incomplete==="missing")findings.pop();else findings[5].status=incomplete;
  t.applyInterview(interviewResult(findings));assert.equal(document.getElementById("global-notice").hidden,true,`Model readiness must not surface an enough-detail notification with a ${incomplete} topic`);
  assert.notEqual(document.getElementById("coverage-count").textContent,"16 / 16",`An explicit ${incomplete} finding must not display a full coverage circle from a contradictory model coverage flag`);passes++;
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
  await t.refreshWorkflow();assert.equal(document.getElementById("coverage-count").textContent,"16 / 16");assert.equal(document.getElementById("global-notice").hidden,false,"The live workflow/memo path must announce full coverage without relying on a typed-interview readiness flag");
  assert.match(document.getElementById("notice-text").textContent,/all 16|enough detail/i);passes++;
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
  assert.equal(document.getElementById("global-notice").hidden,false);assert.match(document.getElementById("notice-text").textContent,/process is safe/);assert.match(document.getElementById("workflow-status").textContent,/Couldn’t/);assert.equal(data.steps[0].id,"S1");finishCanvases();passes++;
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
 {
  checkpoint();t.setDocumentController(null);t.clearState();t.conversationUI.live=null;
  const provenance={method:"document_simulation",source_documents:[{filename:"Reference procedure.pdf",sha256:"a".repeat(64)}],participant_confirmed:false,process_owner_approved:false};
  const saved={schema_version:1,context:{process_name:"Document walkthrough",process_owner:"",objective:"Capture the source",background:"Document-derived simulation, not employee testimony."},turns:[{id:"u1",role:"user",text:"The written procedure describes preparing a file."}],capture_provenance:provenance,closure:{asked:true,confirmed:false},coverage:[],memo_findings:[]};
  const open=async value=>{const raw=JSON.stringify(value);await t.importSession({size:raw.length,text:async()=>raw});};
  await open(saved);assert.deepEqual(JSON.parse(JSON.stringify(t.state.captureProvenance)),provenance);
  const exported=JSON.parse(JSON.stringify(t.sessionObject()));assert.deepEqual(exported.capture_provenance,provenance,"Save/sessionObject preserves the exact source declaration");assert.equal(exported.closure.confirmed,false);
  exported.capture_provenance.source_documents[0].filename="Do not mutate live state.pdf";assert.equal(t.state.captureProvenance.source_documents[0].filename,provenance.source_documents[0].filename,"Saved provenance is a detached snapshot");
  await open(JSON.parse(JSON.stringify(t.sessionObject())));assert.deepEqual(JSON.parse(JSON.stringify(t.state.captureProvenance)),provenance,"Opening a saved simulation retains its provenance");
  t.applyInterview({question:"What happens next in the written procedure?",summary:"",coverage:[],memo_findings:[],focus:"",parking_lot:[],closure:{asked:true,confirmed:true}});
  assert.equal(t.state.closure.confirmed,false,"A model response cannot turn simulation into participant confirmation");
  t.state.closure.confirmed=true;assert.equal(t.sessionObject().closure.confirmed,false,"Export/submission cannot claim simulation confirmation even if a stale local flag is true");t.state.closure.confirmed=false;
  for(const [id,tag] of [["knowledge-submit","dialog"],["knowledge-admin","dialog"],["submit-process-menu","button"],["submit-process-review","button"],["open-knowledge-admin","button"]])if(!document.getElementById(id))mount(id,tag);
  const oldCrypto=context.crypto;context.crypto={randomUUID:()=>"00000000-0000-4000-8000-000000000001"};
  vm.runInContext(fs.readFileSync(path.join(__dirname,"..","web","knowledge-ui.js"),"utf8"),context,{filename:"knowledge-ui.js"});
  const submissions=[],controller=context.window.CollectorKnowledge.create({session:t.sessionObject,notice(){},request:async(url,payload)=>{assert.equal(url,"/api/knowledge/submit");submissions.push(JSON.parse(JSON.stringify(payload)));return{process_id:"00000000-0000-4000-8000-000000000002",submission_id:"00000000-0000-4000-8000-000000000003",job_id:"00000000-0000-4000-8000-000000000004",revision:1,status:"pending",status_token:"b".repeat(64)};}});
  controller.openSubmit();const submitForm=document.getElementById("knowledge-submit").querySelector("form");await submitForm.listeners.submit[0]({preventDefault(){}});
  assert.equal(submissions.length,1);assert.deepEqual(submissions[0].capture_provenance,provenance,"The actual knowledge submit UI receives the preserved simulation declaration");assert.equal(submissions[0].closure.confirmed,false);assert.equal(Object.hasOwn(submissions[0],"submitter"),false,"The browser does not invent verified employee attribution");
  controller.reset();context.crypto=oldCrypto;
  const invalid=[null,{}, {...provenance,participant_confirmed:true},{...provenance,process_owner_approved:true},{...provenance,participant_confirmed:0},{...provenance,extra:"not permitted"},{...provenance,source_documents:[]},{...provenance,source_documents:[{filename:"../private.pdf",sha256:"a".repeat(64)}]},{...provenance,source_documents:[{filename:"Reference.pdf",sha256:"invalid"}]},{...provenance,source_documents:[...provenance.source_documents,...provenance.source_documents]}];
  for(const declaration of invalid){const before=JSON.stringify(t.state),oldTurns=t.state.turns;await open({...saved,capture_provenance:declaration});assert.equal(t.state.turns,oldTurns,"Malformed provenance cannot replace the current interview");assert.equal(JSON.stringify(t.state),before);assert.match(document.getElementById("notice-text").textContent,/provenance.*invalid|confirmation/);}
  {const before=JSON.stringify(t.state);await open({...saved,closure:{asked:true,confirmed:true}});assert.equal(JSON.stringify(t.state),before,"A simulation's claimed participant confirmation must fail before replacement");}
  t.clearState();assert.equal(t.state.captureProvenance,null);assert.equal(Object.hasOwn(t.sessionObject(),"capture_provenance"),false,"A new ordinary interview cannot inherit the simulation marker");
  t.ensureConversation();assert.equal(Object.hasOwn(t.sessionObject(),"capture_provenance"),false);
  await open(saved);const ordinary={...saved,closure:{asked:true,confirmed:true}};delete ordinary.capture_provenance;await open(ordinary);
  assert.equal(t.state.captureProvenance,null);assert.equal(Object.hasOwn(t.sessionObject(),"capture_provenance"),false,"Older ordinary saved sessions keep their no-provenance behavior");assert.equal(t.sessionObject().closure.confirmed,false,"Imported confirmation must be revisited after a fresh coverage assessment");
  t.clearState();passes++;
 }
 const fileRecord=(overrides={})=>({id:"doc_ref1",name:"Reference.pdf",kind:"pdf",status:"ready",size:1234,coverage:{indexed_units:2,total_units:3,limitations:["A visual appendix could not be interpreted."]},analysis:{phase:"complete",disposition:"relevant",version:1,intent_version:1,summary:"Unconfirmed document summary sentinel",question:"Does the reported process use this approval?",questions:[],sources:[{source_id:"source_page2",label:"Reference.pdf · Page2"}],observations:[{text:"Unconfirmed document observation sentinel",sources:[{source_id:"source_page1",label:"Reference.pdf · Page1"}]}],limitations:["Formula values were not recalculated."]},...overrides});
 const fakeDocuments=(saved={scope:"scope_PRIVATE_REFERENCE",documents:[fileRecord()]})=>({saved:JSON.parse(JSON.stringify(saved)),resets:0,restores:[],render(){},exportState(){return JSON.parse(JSON.stringify(this.saved));},reset(){this.resets++;this.saved={scope:null,documents:[]};},async restoreState(value){this.restores.push(JSON.parse(JSON.stringify(value)));this.saved=JSON.parse(JSON.stringify(value));},refresh(){},open(){}});
 {
  checkpoint();t.setDocumentController(null);t.clearState();document.getElementById("process-name").value="";
  assert.equal(t.ensureConversation(),true,"Voice must be able to start before the process has a name");assert.equal(t.state.started,true);assert.equal(t.state.context.process_name,"");assert.equal(t.state.turns.length,0);assert.equal(timers.size,0);passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();t.applyProcessTitle("Invoice approval");assert.equal(t.state.context.process_name,"","A document or model title without a participant answer cannot name the process");
  t.state.turns=[{id:"t002",role:"user",text:"We approve vendor invoices."}];const sourceContext=JSON.stringify(t.snapshot().context);t.applyProcessTitle("Invoice approval");assert.equal(t.state.context.process_name,"");assert.equal(t.state.derivedProcessTitle,"Invoice approval");assert.equal(document.getElementById("process-name").value,"Invoice approval");assert.equal(JSON.stringify(t.snapshot().context),sourceContext,"Automatic naming must not invalidate pending source revisions");
  const title=t.state.derivedProcessTitle;for(const generic of ["UNKNOWN","Untitled","Workflow","Not established"])t.applyProcessTitle(generic);assert.equal(t.state.derivedProcessTitle,title);
  assert.doesNotThrow(()=>t.applyProcessTitle("X".repeat(181)),"A valid long workflow title must not fail an otherwise accepted capture");assert.equal(t.state.derivedProcessTitle,title);passes++;
 }
 {
  checkpoint();document.getElementById("process-name").value="Owner's chosen title";document.getElementById("process-name").dispatch("input");assert.equal(t.state.processNameManual,true);assert.equal(t.state.derivedProcessTitle,"");t.applyProcessTitle("A model-proposed replacement");assert.equal(t.state.context.process_name,"Owner's chosen title");
  const saved=t.sessionObject();assert.equal(saved.process_name_manual,true);t.state.dirty=false;await t.importSession({size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)});
  assert.equal(t.state.processNameManual,true);assert.equal(t.state.context.process_name,"Owner's chosen title");t.applyProcessTitle("Another model title");assert.equal(t.state.context.process_name,"Owner's chosen title");passes++;
 }
 {
  checkpoint();t.clearState();t.ensureConversation();t.state.turns=[{id:"t002",role:"user",text:"We log invoices."}];t.applyProcessTitle("Automatically inferred title");
  const saved=t.sessionObject();assert.equal(saved.process_name_manual,false);assert.equal(saved.context.process_name,"");assert.equal(saved.derived_process_title,"Automatically inferred title");t.state.dirty=false;await t.importSession({size:JSON.stringify(saved).length,text:async()=>JSON.stringify(saved)});assert.equal(t.state.processNameManual,false);assert.equal(t.state.derivedProcessTitle,"Automatically inferred title");assert.equal(document.getElementById("process-name").value,"Automatically inferred title");t.applyProcessTitle("More precise inferred title");assert.equal(t.state.context.process_name,"");assert.equal(t.state.derivedProcessTitle,"More precise inferred title");passes++;
 }
 {
  checkpoint();const docs=fakeDocuments();t.setDocumentController(docs);t.state.context={process_name:"Invoice process"};t.state.turns=[{id:"t002",role:"user",text:"Participant-confirmed intake."}];
  const capture=t.snapshot();assert.equal(capture.document_scope,"scope_PRIVATE_REFERENCE");assert.equal(Object.hasOwn(capture,"documents"),false);assert.equal(Object.hasOwn(capture,"document_facts"),false);
  const serialized=JSON.stringify(capture);assert.equal(serialized.includes("Unconfirmed document observation sentinel"),false);assert.equal(serialized.includes("Unconfirmed document summary sentinel"),false);assert.equal(serialized.includes("Reference.pdf"),false,"Provider snapshots pass a scope reference rather than embedding raw file metadata/content");t.setDocumentController(null);passes++;
 }
 {
  checkpoint();t.clearState();const before=t.conversationUI.revision;t.onDocumentEvent({type:"received",document:fileRecord()});
  assert.equal(t.state.turns.length,0,"A per-file receipt must not create a second acknowledgement or interview turn");assert.equal(t.state.dirty,true);
  assert.equal(document.getElementById("coverage-count").textContent,"0 / 16");assert.equal(t.conversationUI.revision,before);assert.equal(t.documentContext().current_question,"");passes++;
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
  assert.equal(count,2,"An intermediate analysis question must wait for the completed document baseline");assert.equal(t.state.turns.length,count);assert.equal(t.state.turns.at(-1).text,"The original question?");assert.equal(t.state.turns.filter(turn=>turn.role==="user").length,1);assert.equal(document.getElementById("coverage-count").textContent,"0 / 16");passes++;
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
  t.appendDocumentMessage("Thanks for sharing. Give me a moment to digest the file.",fileRecord());
  assert.equal(document.getElementById("current-question").textContent,"What happens next?","A file receipt must not replace the question on the voice stage");
  assert.ok(document.getElementById("transcript").textContent.includes("File update"));
  assert.equal(document.getElementById("transcript").textContent.includes("Question 2"),false,"A receipt is not a numbered question");
  const receipt=t.state.turns.at(-1),row=document.getElementById(`turn-${receipt.id}`);
  assert.equal(row.classList.contains("turn-update"),true);assert.equal(row.querySelector(".turn-text").textContent,receipt.text,"Compact file activity preserves all searchable source text");
  assert.equal(row.querySelector(".play-turn"),null,"File receipts do not compete with the question's listening action");
  assert.equal(document.getElementById("turn-t001").querySelector(".play-turn").parentElement.className,"turn-meta");passes++;
 }
 {
  checkpoint();t.clearState();t.conversationUI.live=null;t.conversationUI.status="idle";
  const presence={states:[],visibility:[],audio:[],setState(value){this.states.push(value);},setVisible(value){this.visibility.push(value);},setAudio(value){this.audio.push(value);}};
  t.setPresenceFake(presence);t.state.started=true;t.updatePresence();assert.equal(presence.states.at(-1),"idle");
  t.conversationUI.flowBusy=true;t.updatePresence();assert.equal(presence.states.at(-1),"idle","Background workflow retrieval must not imply the conversation is processing");
  t.conversationUI.flowBusy=false;t.state.busy=true;t.updatePresence();assert.equal(presence.states.at(-1),"processing");assert.equal(document.getElementById("presence-status").textContent,"Thinking…");
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
  callbacks.onStatus("muted");assert.equal(presence.states.at(-1),"muted");assert.equal(document.getElementById("presence-status").textContent,"Mic muted");
  callbacks.onStatus("processing");assert.equal(presence.states.at(-1),"processing");callbacks.onStatus("listening");
  const transcript=JSON.stringify(t.state.turns);t.selectConversationView("transcript");assert.equal(presence.visible.at(-1),false);assert.equal(t.conversationUI.live.connected,true);assert.equal(stops,0,"Hiding the visual must not stop the audio session");
  t.selectConversationView("voice");t.tab("review");assert.equal(interview.hidden,false,"An active session keeps microphone controls accessible");assert.equal(presence.visible.at(-1),true);
  callbacks.onStatus("closing");assert.equal(presence.states.at(-1),"ended");assert.equal(document.getElementById("presence-status").textContent,"Saving the transcript…");
  await document.getElementById("stop-live").listeners.click[0]({target:document.getElementById("stop-live")});
  assert.equal(stops,1);assert.equal(presence.states.at(-1),"ended");assert.equal(document.getElementById("presence-status").textContent,"Voice off");assert.equal(JSON.stringify(t.state.turns),transcript,"Ending the session preserves transcript content");
  await t.startLiveConversation();assert.equal(starts,2);assert.equal(presence.states.at(-1),"listening","Continuing a conversation clears the ended posture");
  document.getElementById("mute-live").dispatch("click");assert.equal(t.conversationUI.muted,true);assert.equal(presence.states.at(-1),"muted");
  await document.getElementById("stop-live").listeners.click[0]({target:document.getElementById("stop-live")});t.clearState();assert.equal(presence.states.at(-1),"idle","A new interview resets the ended state");
  t.conversationUI.live=null;t.setPresenceFake(null);delete context.window.CollectorLiveVoice;passes++;
 }
 // Renderer failure recovery only retries the bundled files and never resubmits an interview.
 {
  checkpoint();t.clearState();const made=fakeWorkflow();
  t.conversationUI.workflow=graph("Earlier capture");t.renderWorkingMap();
  t.conversationUI.workflow=graph("Latest capture");t.renderWorkingMap();
  assert.equal(made.length,0,"Capturing evidence in Voice must not lay out hidden diagrams");
  t.tab("interview");t.selectConversationView("workflow");
  assert.equal(made.length,1);assert.equal(made[0].requests.length,1);
  assert.equal(made[0].requests[0].graph.title,"Latest capture");
  t.selectConversationView("voice");t.conversationUI.workflow=graph("Discarded capture");t.renderWorkingMap();
  t.clearState();t.selectConversationView("workflow");assert.equal(made.length,1,"A cleared interview must discard deferred captures");
  finishCanvases();passes++;
 }
 {
  checkpoint();t.clearState();t.state.context={process_name:"Preserved interview"};t.state.turns=[{id:"t002",role:"user",text:"Keep this evidence."}];t.state.summary="Keep this summary.";document.getElementById("answer-text").value="Keep my unsent answer.";
  t.tab("interview");t.selectConversationView("workflow");
  t.conversationUI.workflow=graph("Preserved graph");const before=JSON.stringify(t.state),live=document.getElementById("live-workflow");
  context.window.CollectorWorkflow={create:root=>{root.append(document.createElementNS("http://www.w3.org/2000/svg","svg"));throw new Error("ELK missing");}};
  assert.doesNotThrow(()=>t.renderWorkingMap(),"Synchronous renderer construction failure must remain inside the workflow view");assert.equal(live.querySelector("svg"),null);assert.match(live.textContent,/captured components and reported routes/);assert.equal(document.getElementById("export-working-map").disabled,true);assert.equal(JSON.stringify(t.state),before);assert.equal(document.getElementById("answer-text").value,"Keep my unsent answer.");delete context.window.CollectorWorkflow;passes++;
 }
 {
  checkpoint();delete context.window.ELK;delete context.window.CollectorWorkflow;const beforeScripts=document.querySelectorAll("script").length,beforeCalls=providerCalls,beforeSummary=t.state.summary;
  const recovery=t.retryWorkflowLayout("live-workflow"),shared=t.ensureWorkflowAssets();assert.equal(t.ensureWorkflowAssets(),shared,"Concurrent diagram retries share the same asset load");
  let scripts=document.querySelectorAll("script");assert.equal(scripts.length,beforeScripts+1);assert.equal(scripts.at(-1).src,"/vendor/elk.bundled.js");
  t.conversationUI.workflow=graph("Newer graph while loading",[{id:"S2",title:"Latest reported step",evidence_turns:["t002"]}]);
  context.window.ELK=function LocalELK(){};scripts.at(-1).dispatch("load");await nextMicrotask();scripts=document.querySelectorAll("script");assert.equal(scripts.length,beforeScripts+2);assert.equal(scripts.at(-1).src,"/workflow-graph.js");
  const made=fakeWorkflow();scripts.at(-1).dispatch("load");await recovery;await shared;assert.equal(made.length,1);assert.equal(made[0].requests[0].graph.title,"Newer graph while loading","Recovery renders current evidence, never the graph captured before the files loaded");
  assert.equal(document.getElementById("export-working-map").disabled,true);made[0].requests[0].resolve(true);await nextMicrotask();assert.equal(document.getElementById("export-working-map").disabled,false);assert.equal(document.getElementById("retry-workflow").hidden,true);assert.equal(t.state.summary,beforeSummary);assert.equal(document.getElementById("answer-text").value,"Keep my unsent answer.");assert.equal(providerCalls,beforeCalls);finishCanvases();passes++;
 }
 {
  checkpoint();delete context.window.ELK;const current=t.conversationUI.workflow,before=JSON.stringify(t.state);const recovery=t.retryWorkflowLayout("live-workflow"),script=document.querySelectorAll("script").at(-1);script.dispatch("error");await recovery;
  assert.equal(t.conversationUI.workflow,current);assert.equal(JSON.stringify(t.state),before);assert.equal(script.isConnected,false,"Failed script elements are removed before a later retry");assert.match(document.getElementById("live-workflow").textContent,/Latest reported step/);assert.equal(document.getElementById("retry-workflow").disabled,false);assert.equal(document.getElementById("export-working-map").disabled,true);passes++;
 }
 {
  checkpoint();context.window.ELK=function LocalELK(){};const recovery=t.retryWorkflowLayout("live-workflow"),script=document.querySelectorAll("script").at(-1);assert.equal(script.src,"/workflow-graph.js");t.clearState();
  const made=fakeWorkflow();script.dispatch("load");await recovery;assert.equal(made.length,0,"A late asset retry must not restore a cleared interview");assert.equal(document.getElementById("retry-workflow").disabled,false,"A cancelled retry cannot leave the next interview retry disabled");assert.equal(t.conversationUI.workflow,null);assert.equal(t.state.turns.length,0);assert.equal(document.getElementById("live-workflow").textContent.includes("Latest reported step"),false);finishCanvases();delete context.window.ELK;passes++;
 }

 // Document citations stay distinct from participant evidence across capture/save/reopen.
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:""};
  const documentId="doc_0123456789abcdef01234567",sourceId=documentId+"_page100_c10000";
  const evidence={id:sourceId,document_id:documentId,name:"Payment SOP.pdf",label:"Page 1",text:"Treasury reviews; the client releases the wire."};
  const doc={id:documentId,name:evidence.name,status:"ready",analysis:{phase:"complete",disposition:"relevant",summary:"Payment execution",sources:[{source_id:sourceId}],intent_version:0}};
  t.setDocumentController({exportState:()=>({scope:"testscope",documents:[doc]}),reset(){},render(){}});t.state.config={api_configured:true};
  t.onDocumentEvent({type:"analysis",document:doc,analysis:doc.analysis});
  assert.equal(timers.size,0,"Analysis events do not bypass the document intake coordinator with an independent workflow request");const revision=t.conversationUI.revision;
  t.onDocumentEvent({type:"analysis",document:doc,analysis:doc.analysis});assert.equal(t.conversationUI.revision,revision,"Polling the same file phase does not repeat capture");
  checkpoint();t.setRequest(async(url,payload)=>{assert.equal(url,"/api/workflow");assert.equal(payload.document_scope,"testscope");return {
   workflow:{title:"US payment execution",steps:[{id:"S1",title:"Client releases payment",evidence_turns:[sourceId]}],connections:[]},
   document_evidence:[evidence],memo_findings:[{key:"name",status:"captured",answer:"US payment execution",evidence_turns:[sourceId]}],coverage:[],summary:"Documented process",focus:"Named owner",parking_lot:[]};});
  await t.refreshWorkflow();assert.equal(t.conversationUI.workflow.steps.length,1);assert.equal(t.state.context.process_name,"");assert.equal(t.state.derivedProcessTitle,"US payment execution");
  assert.equal(t.state.memo_findings.find(f=>f.key==="name").status,"partial","Documented detail must not become participant-confirmed coverage");
  assert.match(t.sourceCaption(sourceId),/Payment SOP.pdf.*Page 1/);assert.equal(t.snapshot().document_source_ids[0],sourceId);
  t.showFoundationTopic("name",document.querySelector('[data-foundation-topic="name"]'));
  const citation=document.getElementById("foundation-topic-sources").querySelector(".evidence-link");
  citation.dispatch("click");
  const excerptDialog=document.getElementById("document-evidence-dialog");
  assert.equal(excerptDialog.open,true);assert.match(excerptDialog.textContent,/client releases the wire/);
  assert.equal(dialog.open,true,"Reading a document citation preserves its note underneath");
  excerptDialog.close();t.closeFoundationTopic();
  const saved=t.sessionObject();assert.equal(saved.document_evidence[0].text,evidence.text);
  assert.equal(t.normalizeDraft(saved.workflow,[],saved.document_evidence).steps[0].evidence_turns[0],sourceId);
  assert.throws(()=>t.normalizeDraft(saved.workflow,[],[]),/unavailable/);
  const before=JSON.stringify(t.state);assert.throws(()=>t.normalizeDocumentEvidence([{...evidence,id:"t001"}]),/invalid/);assert.equal(JSON.stringify(t.state),before);
  t.setDocumentController(null);t.clearState();assert.equal(t.state.documentEvidence.length,0);passes++;
 }
 {
  const excerpt={id:"doc_example_page1_c0",text:"Exact whole paragraph. ".repeat(350)};
  const input={documents:[{id:"doc_example",name:"SOP.pdf",summary:"Overview",review:{review_complete:true},context_coverage:{complete_text:true,total_chunks:3},excerpts:[excerpt,{...excerpt,id:"doc_example_page2_c0"},{...excerpt,id:"doc_example_page3_c0"}]}]};
  const result=t.boundedVoiceDocuments(input,"doc_example");assert.ok(Buffer.byteLength(JSON.stringify(result))<15000);assert.equal(result.documents[0].context_coverage.complete_text,false);assert.ok(result.documents[0].excerpts.length>0);assert.equal(result.documents[0].excerpts[0].text,excerpt.text,"Live source excerpts are never silently clipped");passes++;
 }
 // Rich component semantics survive imports, edits and both workflow views.
 {
  const types=["activity","decision","merge","start","end","parallel_split","parallel_join","wait","subprocess","document","data_store"];
  const input={title:"Component coverage",steps:types.map((type,i)=>({id:`N${i}`,type,title:`Reported ${type}`,evidence_turns:["t002"]})),connections:[]};
  t.state.turns=[{id:"t002",role:"user",text:"Fictional process used to validate UI component handling."}];
  const normalized=t.normalizeDraft(input);assert.deepEqual(Array.from(normalized.steps,step=>step.type),types);
  assert.equal(t.normalizeDraft({steps:[{id:"legacy",title:"Old saved activity"}]}).steps[0].type,"activity","Saved sessions without a component type retain their existing meaning");
  for(const type of ["invented","toString","constructor"])assert.throws(()=>t.normalizeDraft({steps:[{id:"bad",type}]}),/unsupported diagram component/);
  assert.equal(JSON.stringify(input.steps.map(step=>step.type)),JSON.stringify(types),"Normalization cannot rewrite the input data");passes++;
  for(const prefix of ["workflow","map"]){mount(prefix+"-legend","details");mount(prefix+"-legend-items","ul",document.getElementById(prefix+"-legend"));}
  t.renderWorkflowLegend("live-workflow",normalized);
  const legend=document.getElementById("workflow-legend"),items=document.getElementById("workflow-legend-items");
  assert.equal(legend.hidden,false);assert.equal(items.children.length,11);assert.match(items.textContent,/all required branches/);assert.match(items.textContent,/persistent record/);assert.match(items.textContent,/any one of the alternative routes/);passes++;
  t.renderWorkflowLegend("process-map",{steps:[normalized.steps[1],normalized.steps[4]]});
  assert.equal(document.getElementById("map-legend-items").children.length,2,"The key must describe only components actually used in this graph");
  assert.equal(items.children.length,11,"Review and live diagram keys must stay independent");
  t.renderWorkflowLegend("live-workflow",{steps:[]});assert.equal(legend.hidden,true);assert.equal(items.children.length,0);passes++;
  if(!document.getElementById("procedure-steps"))mount("procedure-steps");
  t.state.draft=normalized;t.renderSteps();
  const choices=document.getElementById("procedure-steps").children[0].querySelector("select").children;
  assert.deepEqual(Array.from(choices,option=>option.value),types,"The editable procedure must offer the same components as capture and rendering");passes++;
  const canvases=fakeWorkflow();
  t.tab("review");t.selectReviewSection("review-procedure");
  const instructions=document.getElementById("procedure-steps").children[0].querySelector(".step-description");
  instructions.value="Use the updated instructions";instructions.dispatch("input");
  t.selectReviewSection("review-map");
  assert.equal(canvases.at(-1).requests.at(-1).graph.steps[0].description,instructions.value,
    "Procedure details must reach the diagram even when the step geometry stays the same");
  finishCanvases();passes++;
 }
 {
  const live=t.normalizeDraft({title:"Parallel work",steps:[{id:"split",type:"parallel_split",title:"Start the two checks",evidence_turns:["t002"]},{id:"check",type:"subprocess",title:"Run customer check",evidence_turns:["t002"]},{id:"archive",type:"document",title:"Save the signed record",evidence_turns:["t002"]}],connections:[{from:"split",to:"check",label:"Customer verification",evidence_turns:["t002"]},{from:"split",to:"archive",label:"Signed record",evidence_turns:["t002"]}]});
  t.conversationUI.workflow=live;t.state.draft=t.normalizeDraft({title:"Separate draft",steps:[{id:"split",title:"Draft only",evidence_turns:["t002"]},{id:"private",title:"Draft route only",evidence_turns:["t002"]}],connections:[{from:"split",to:"private",label:"Draft branch",evidence_turns:["t002"]}]});
  const before=JSON.stringify(live);t.showWorkflowStep(live.steps[0],"live-workflow");
  const content=document.getElementById("workflow-step-content");assert.match(document.getElementById("workflow-step-kind").textContent,/Parallel split/);
  assert.match(content.textContent,/Each branch runs/);assert.match(content.textContent,/Customer verification → Run customer check/);assert.match(content.textContent,/Signed record → Save the signed record/);assert.equal(content.textContent.includes("Draft branch"),false);
  assert.equal(content.querySelector(".workflow-step-routes").querySelectorAll(".evidence-link").length,2,"Each route retains its own source evidence");passes++;
  content.querySelector(".workflow-route-link").dispatch("click");assert.equal(document.getElementById("workflow-step-title").textContent,"Run customer check");assert.match(document.getElementById("workflow-step-kind").textContent,/Subprocess/);assert.equal(JSON.stringify(live),before,"Following a route changes the view, never process data");stepDialog.close();passes++;
  const labels={start:"Start",end:"End",wait:"Wait",document:"Document",data_store:"Stored data",parallel_join:"Parallel join",merge:"Merge alternatives"};
  for(const [type,label] of Object.entries(labels)){t.showWorkflowStep({id:"kind",type,title:"Type details",evidence_turns:[]},"live-workflow");assert.equal(document.getElementById("workflow-step-kind").textContent,`kind · ${label}`);stepDialog.close();}passes++;
 }
 // Exercise the redesigned transcript controls using their real event handlers.
 {
  checkpoint();t.clearState({process_name:"Transcript interaction audit",objective:"Capture the reported work"});
  const find=mount("transcript-find","div",history),findToggle=mount("transcript-find-toggle","button",history),findClose=mount("transcript-find-close","button",find);
  find.hidden=true;const search=document.getElementById("transcript-search");find.append(search);
  const navigation=mount("transcript-match-navigation","div",find);navigation.hidden=true;
  const exportWrap=mount("transcript-export-test","div",history);exportWrap.className="transcript-export";
  const exportToggle=mount("export-transcript","button",exportWrap),options=mount("transcript-export-options","div",exportWrap);options.hidden=true;
  const formats=["markdown","json"].map(format=>{const button=mount("transcript-format-"+format,"button",options);button.dataset.transcriptFormat=format;return button;});
  t.initTranscriptTools();t.state.turns=[{id:"tool1",role:"assistant",text:"Who owns the email intake?"},{id:"tool2",role:"user",text:"An analyst checks the email inbox."}];t.renderTranscript();
  findToggle.dispatch("click");assert.equal(find.hidden,false);assert.equal(findToggle.getAttribute("aria-expanded"),"true");assert.equal(document.activeElement,search);
  search.value="email";t.refreshReadingSearch("transcript");assert.equal(navigation.hidden,false);assert.equal(t.readingUI.transcript.matches.length,2);
  findClose.dispatch("click");assert.equal(find.hidden,true);assert.equal(findToggle.getAttribute("aria-expanded"),"false");assert.equal(document.activeElement,findToggle);assert.equal(search.value,"");assert.equal(t.readingUI.transcript.matches.length,0);assert.equal(navigation.hidden,true);passes++;
  findToggle.dispatch("click");search.value="owns";t.refreshReadingSearch("transcript");assert.equal(navigation.hidden,true,"One match needs no navigation arrows");
  let prevented=0;for(const handler of document.listeners.keydown)handler({key:"Escape",target:search,preventDefault(){prevented++;}});
  assert.equal(prevented,1);assert.equal(find.hidden,true);assert.equal(search.value,"");assert.equal(document.activeElement,findToggle);passes++;
  exportToggle.dispatch("click");assert.equal(options.hidden,false);assert.equal(exportToggle.getAttribute("aria-expanded"),"true");assert.equal(document.activeElement,formats[0]);
  for(const handler of document.listeners.keydown)handler({key:"Escape",target:formats[0],preventDefault(){}});
  assert.equal(options.hidden,true);assert.equal(document.activeElement,exportToggle);passes++;
  exportToggle.dispatch("click");search.focus();for(const handler of document.listeners.click)handler({target:search});
  assert.equal(options.hidden,true);assert.equal(document.activeElement,search,"Outside clicks retain the user's new focus");
  exportToggle.dispatch("click");findToggle.dispatch("click");assert.equal(options.hidden,true);assert.equal(find.hidden,false);assert.equal(document.activeElement,search);t.setTranscriptFind(false);passes++;
  const escapeModal=mount("transcript-escape-test","dialog"),modalAction=mount("transcript-modal-action","button",escapeModal);
  exportToggle.dispatch("click");escapeModal.showModal();modalAction.focus();let modalPrevented=false;
  for(const handler of document.listeners.keydown)handler({key:"Escape",target:modalAction,preventDefault(){modalPrevented=true;}});
  assert.equal(options.hidden,true);assert.equal(modalPrevented,false,"Transcript Escape handling leaves the active modal's native dismissal available");assert.equal(document.activeElement,modalAction,"Closing an inactive export disclosure cannot steal focus from a modal");escapeModal.close();passes++;
  for(const view of ["voice","workflow"]){
   t.selectConversationView("transcript");exportToggle.dispatch("click");const destination=document.getElementById("conversation-tab-"+view);destination.focus();t.selectConversationView(view);
   assert.equal(options.hidden,true);assert.equal(exportToggle.getAttribute("aria-expanded"),"false");assert.equal(document.activeElement,destination,"Leaving Transcript closes export without returning focus to its hidden trigger");
  }
  t.selectConversationView("transcript");exportToggle.dispatch("click");const reviewDestination=document.getElementById("review-tab-procedure");reviewDestination.focus();t.tab("review");
  assert.equal(options.hidden,true);assert.equal(document.activeElement,reviewDestination);assert.equal(review.hidden,false);t.tab("interview");t.selectConversationView("transcript");passes++;
  const before=t.state.turns.map(turn=>turn.text),calls=providerCalls;
  for(const [index,format] of ["markdown","json"].entries()){
   exportToggle.dispatch("click");formats[index].dispatch("click");const [content,filename,mime]=context.window.__downloads.at(-1);
   assert.ok(filename.endsWith(format==="json"?".json":".md"));assert.match(mime,format==="json"?/application\/json/:/text\/markdown/);
   for(const text of before)assert.ok(content.includes(text));assert.equal(options.hidden,true);assert.equal(document.activeElement,exportToggle);
  }
  assert.equal(providerCalls,calls);passes++;
 }
 // Mount the real control boundary only after the earlier navigation fixtures.
 {
  checkpoint();t.clearState({process_name:"Typed first answer",objective:"Capture the actual process"});
  const dock=document.getElementById("conversation-dock"),ensure=(id,tag="div",parent=dock)=>document.getElementById(id)||mount(id,tag,parent);
  for(const id of ["composer-area","composer-hint","recording-status","thinking","thinking-text","presence-caption","transcript-live-hint","welcome","review-empty","draft-content","draft-dot","draft-stale","example-banner","closure-status"])ensure(id);
  for(const id of ["start-live","type-instead","send-answer","record-answer","skip-question","final-check","generate-draft","regenerate-draft","preview-voice","export-markdown","export-session","start-interview"])ensure(id,"button");
  for(const id of ["start-live","record-answer","start-interview"])if(!document.getElementById(id).querySelector("span"))mount(id+"-label","span",document.getElementById(id));
  ensure("voice-select","select");
  const dockRow=mount("transcript-dock-row-test","div",dock);dockRow.className="dock-row";
  const liveControls=mount("live-controls","div",dockRow),liveHeader=mount("transcript-live-controls","div",history);
  for(const id of ["start-live","stop-live","mute-live","type-instead"])liveControls.append(document.getElementById(id));
  t.state.config={api_configured:true,live:{enabled:true},speech:{enabled:false}};t.conversationUI.live=null;t.conversationUI.typing=false;
  const input=document.getElementById("answer-text"),composer=document.getElementById("composer-area"),talk=document.getElementById("start-live"),skip=document.getElementById("skip-question");
  input.value="A supplier email starts the work.";const original=JSON.stringify(t.state),requests=[];
  t.setRequest(async(url,payload)=>{requests.push({url,payload});return {question:"Who receives that email?",coverage:[],memo_findings:[]};});
  t.selectConversationView("transcript");t.exerciseControls();
  assert.equal(JSON.stringify(t.state),original);assert.equal(requests.length,0);assert.equal(composer.hidden,false);assert.equal(input.disabled,false);assert.equal(document.getElementById("send-answer").disabled,false);assert.equal(document.getElementById("record-answer").disabled,false,"The first response can be dictated without starting voice automatically");assert.equal(skip.hidden,true);assert.equal(document.getElementById("type-instead").hidden,true);assert.equal(document.getElementById("export-transcript").disabled,true,"An empty conversation cannot be exported");passes++;
  await t.sendAnswer({preventDefault(){}});assert.equal(t.state.started,true);assert.equal(requests.length,1);assert.equal(requests[0].url,"/api/interview");assert.equal(requests[0].payload.action,"answer");assert.equal(requests[0].payload.turns[0].text,"A supplier email starts the work.");assert.equal(t.state.turns[0].role,"user");assert.equal(t.state.turns[1].text,"Who receives that email?");assert.equal(input.value,"");checkpoint();passes++;
  input.value="Keep this unsent clarification.";t.conversationUI.live={active:true,connected:true};t.conversationUI.status="listening";t.exerciseControls();
  assert.equal(composer.hidden,true);assert.equal(input.disabled,true);assert.equal(document.getElementById("stop-live").hidden,false);assert.equal(talk.hidden,true);assert.equal(document.getElementById("transcript-live-hint").hidden,false);
  assert.equal(liveControls.parentElement,liveHeader,"Active voice controls stay available in the transcript header while reading history");
  const mute=document.getElementById("mute-live"),live=t.conversationUI.live;let muteEvents=0;mute.addEventListener("placement-check",()=>muteEvents++);mute.focus();
  for(const view of ["voice","transcript","workflow","transcript"]){
   t.selectConversationView(view);assert.equal(liveControls.parentElement,view==="transcript"?liveHeader:dockRow);assert.equal(document.activeElement,mute);assert.equal(t.conversationUI.live,live);assert.equal(input.value,"Keep this unsent clarification.");
  }
  mute.dispatch("placement-check");assert.equal(muteEvents,1);assert.equal(walk(document.body).filter(node=>node.id==="live-controls").length,1,"View changes move the original live controls and preserve their listeners");assert.equal(requests.length,1);passes++;
  await t.sendAnswer({preventDefault(){}});assert.equal(requests.length,1);assert.equal(input.value,"Keep this unsent clarification.");
  document.getElementById("stop-live").focus();
  t.conversationUI.live.active=false;t.conversationUI.live.connected=false;t.conversationUI.status="closing";t.exerciseControls();assert.equal(composer.hidden,true);assert.equal(document.getElementById("stop-live").disabled,true);assert.equal(liveControls.parentElement,liveHeader,"Final transcript save keeps the voice status in the header");
  t.conversationUI.status="idle";t.exerciseControls();assert.equal(composer.hidden,false);assert.equal(input.disabled,false);assert.equal(talk.hidden,false);assert.equal(skip.hidden,false);assert.equal(document.getElementById("transcript-live-hint").hidden,true);assert.equal(liveControls.parentElement,dockRow,"When voice ends, the same controls return beside the composer");assert.equal(input.value,"Keep this unsent clarification.");assert.equal(t.conversationUI.typing,false,"Transcript composer returns after voice without a hidden typing-mode prerequisite");assert.equal(document.activeElement,input,"Stopping voice returns keyboard focus to the visible reply field");passes++;
  t.selectConversationView("voice");live.active=true;live.connected=true;t.conversationUI.status="listening";t.exerciseControls();mute.focus();
  live.active=false;live.connected=false;t.conversationUI.status="idle";t.exerciseControls();assert.equal(document.activeElement,talk,"Ending voice outside Transcript leaves focus on the visible start control");assert.equal(input.value,"Keep this unsent clarification.");t.selectConversationView("transcript");passes++;
  t.state.config.api_configured=false;t.exerciseControls();assert.equal(input.disabled,true);assert.equal(document.getElementById("send-answer").disabled,true);assert.equal(document.getElementById("export-transcript").disabled,false,"Reading and export remain available without provider setup");passes++;
 }
 {
  const jump=mount("jump-latest","button",history);jump.hidden=true;scroll.scrollHeight=2400;scroll.clientHeight=500;scroll.scrollTop=260;
  t.selectConversationView("voice");t.selectConversationView("transcript");assert.equal(jump.hidden,false,"Opening an existing long transcript immediately offers latest-message navigation");assert.equal(scroll.scrollTop,260,"Navigation availability does not move the reader");
  scroll.scrollTop=1900;t.renderTranscript();assert.equal(jump.hidden,true,"The latest-message action disappears when the reader reaches the end");
  scroll.scrollTop=0;scroll.scrollHeight=500;t.renderTranscript();assert.equal(jump.hidden,true,"Short conversations do not display unnecessary scroll navigation");
  const saved=t.state.turns;t.state.turns=[];scroll.scrollHeight=2400;t.renderTranscript();assert.equal(jump.hidden,true,"An empty transcript has no latest message");t.state.turns=saved;passes++;
 }
 // Exercise the actual coordinator through the app's document events and provider boundary.
 {
  checkpoint();t.conversationUI.live=null;t.clearState({process_name:"Document intake",objective:"Capture the reported process"});
  vm.runInContext(fs.readFileSync(path.join(__dirname,"..","web","document-intake.js"),"utf8"),context,{filename:"document-intake.js"});
  const ensure=id=>document.getElementById(id)||mount(id);
  for(const id of ["document-intake-panel","document-intake-title","document-intake-detail","document-intake-retry","document-intake-continue","intake-step-upload","intake-step-review","intake-step-baseline","intake-step-question"])ensure(id);
  t.state.config={api_configured:true,live:{enabled:true},speech:{enabled:false}};t.ensureConversation();
  t.state.turns=[{id:"t002",role:"user",text:"Treasury receives the wire request."},{id:"t003",role:"assistant",text:"What happens next?"}];
  t.state.summary="Previous accepted summary";t.conversationUI.workflow=graph("Previous accepted workflow");
  const input=document.getElementById("answer-text");input.value="Keep my unsent clarification.";
  const sourceId="doc_0123456789abcdef01234567_page1_c0",documentId="doc_0123456789abcdef01234567";
  const evidence={id:sourceId,document_id:documentId,name:"Payment SOP.pdf",label:"Page 1",text:"Treasury checks the wire and the client releases it."};
  const lifecycle={scope:"scope_intake",generation:1,documents:[],uploading:1,mutating:1,uploadErrors:[],connectionError:""};
  const clone=value=>JSON.parse(JSON.stringify(value));
  t.setDocumentController({lifecycle:()=>clone(lifecycle),exportState:()=>({scope:lifecycle.scope,documents:clone(lifecycle.documents)}),reset(){},render(){}});
  let finishPause,finishBaseline,finishFollowup,stopCount=0,appendCount=0;const starts=[],requests=[];
  const appended=[];const live={active:true,connected:true,stop(){stopCount++;this.active=false;this.connected=false;t.conversationUI.status="idle";return new Promise(resolve=>finishPause=resolve);},async start(payload){starts.push(payload);this.active=true;this.connected=true;},appendContext(content,options){appendCount++;appended.push({text:content,options});}};
  t.conversationUI.live=live;t.conversationUI.status="listening";
  t.setRequest((url,payload,options)=>{requests.push({url,payload,options});if(url==="/api/workflow")return new Promise(resolve=>finishBaseline=resolve);if(url==="/api/interview")return new Promise(resolve=>finishFollowup=resolve);throw Error(`Unexpected request: ${url}`);});
  const intake=t.createIntake(),flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  t.onDocumentEvent({type:"upload_started",batchId:"batch-a",names:["Payment SOP.pdf"]});
  t.onDocumentEvent({type:"upload_started",batchId:"batch-b",names:["Appendix.pdf"]});
  t.exerciseControls();
  assert.equal(stopCount,1,"Overlapping file batches pause the voice session only once");assert.equal(appendCount,0);
  assert.equal(t.state.turns.filter(turn=>turn.document_event).length,1,"One intake acknowledgement covers the upload transaction");
  assert.match(t.state.turns.at(-1).text,/Thanks for sharing.*moment to digest/);assert.equal(intake.phase,"uploading");
  assert.equal(document.getElementById("document-intake-panel").hidden,false);assert.equal(current.hidden,true);
  for(const id of ["start-live","send-answer","record-answer","skip-question","final-check","generate-draft","regenerate-draft","retry-question"])assert.equal(document.getElementById(id).disabled,true,`${id} is gated during file intake`);
  assert.equal(input.value,"Keep my unsent clarification.");passes++;

  const file={id:documentId,name:evidence.name,status:"ready",chunk_count:1,analysis:{phase:"quick",version:1,intent_version:0,disposition:"relevant",question:"Premature document question?"}};
  lifecycle.documents=[file];t.onDocumentEvent({type:"received",document:file});t.onDocumentEvent({type:"analysis",document:file});
  lifecycle.uploading=0;lifecycle.mutating=0;
  t.onDocumentEvent({type:"upload_settled",batchId:"batch-a"});t.onDocumentEvent({type:"upload_settled",batchId:"batch-b"});await flush();
  assert.equal(intake.phase,"reviewing");assert.equal(requests.length,0,"Quick review cannot start either a workflow or an interview request");
  assert.equal(t.state.turns.length,3);assert.equal(t.state.summary,"Previous accepted summary");
  assert.equal(await t.refreshWorkflow(),false,"Manual capture cannot race the file review");
  await t.sendAnswer({preventDefault(){}});await t.startLiveConversation();assert.equal(requests.length,0);assert.equal(starts.length,0);
  t.onDocumentEvent({type:"question",document:file,question:{text:"A selected question too soon?"}});assert.equal(appendCount,0);assert.equal(t.state.turns.length,3);passes++;

  file.analysis={...file.analysis,phase:"complete",version:2,review_complete:false};
  t.onDocumentEvent({type:"analysis",document:file});await flush();
  assert.equal(requests.length,0,"A completed review still waits for the voice transcript to drain");
  finishPause({finalized:true});await flush();
  assert.equal(intake.phase,"baseline");assert.equal(requests.length,1);assert.equal(requests[0].url,"/api/workflow");
  assert.equal(requests[0].options.timeout,510000,"Document capture allows generation, source audit, coverage assessment and overhead");
  assert.equal(requests[0].payload.document_scope,"scope_intake");assert.equal(t.state.summary,"Previous accepted summary");
  assert.equal(t.state.turns.some(turn=>turn.text==="Premature document question?"),false);passes++;

  finishBaseline({workflow:graph("Reviewed payment process",[{id:"S1",title:"Client releases the wire",evidence_turns:[sourceId]}]),document_evidence:[evidence],memo_findings:[{key:"trigger",status:"captured",answer:"Treasury receives the request",evidence_turns:["t002"]}],coverage:[],summary:"Accepted document baseline",focus:"Confirm the release owner",parking_lot:["Confirm exceptions"]});await flush();
  assert.equal(intake.phase,"question");assert.equal(requests.length,2);assert.equal(requests[1].url,"/api/interview");assert.equal(requests[1].payload.action,"document_followup");
  assert.equal(requests[1].options.timeout,330000,"The follow-up allows two 90-second calls, the 120-second coverage assessment and overhead");
  assert.equal(requests[1].payload.previous_capture.summary,"Accepted document baseline");assert.equal(requests[1].payload.previous_capture.workflow.steps[0].title,"Client releases the wire");
  assert.equal(t.state.summary,"Accepted document baseline");assert.equal(t.state.turns.length,3,"The follow-up must not appear until its request resolves");
  t.applyInterview({question:"Stale question from before upload",summary:"Stale summary",coverage:[],memo_findings:[]});
  assert.equal(t.state.turns.length,3,"A late ordinary interview result cannot interrupt document intake");assert.equal(t.state.summary,"Accepted document baseline");passes++;

  finishFollowup({question:"Who confirms that the client released the wire?",summary:"Unrelated second snapshot",coverage:[],memo_findings:[],parking_lot:[]});await flush();t.exerciseControls();
  assert.equal(intake.phase,"ready");assert.equal(t.state.turns.length,4);assert.equal(t.state.turns.at(-1).text,"Who confirms that the client released the wire?");
  assert.equal(t.state.summary,"Accepted document baseline","The question response cannot overwrite the audited capture");assert.equal(t.state.memo_findings.find(item=>item.key==="trigger").answer,"Treasury receives the request");assert.equal(t.state.parking_lot[0],"Confirm exceptions");
  assert.equal(t.conversationUI.workflow.steps[0].title,"Client releases the wire");assert.equal(t.state.documentEvidence[0].id,sourceId);
  assert.equal(document.getElementById("document-intake-panel").hidden,true);assert.equal(current.hidden,false);assert.equal(document.getElementById("start-live").disabled,false);assert.equal(document.getElementById("send-answer").disabled,false);assert.equal(input.value,"Keep my unsent clarification.");
  t.onDocumentEvent({type:"analysis",document:file});t.onDocumentEvent({type:"changed",state:clone(lifecycle)});await flush();
  assert.equal(requests.length,2);assert.equal(t.state.turns.length,4,"Repeated final polling cannot add another follow-up");assert.equal(stopCount,1);passes++;

  await t.startLiveConversation();assert.equal(starts.length,1);assert.equal(starts[0].document_scope,"scope_intake");assert.equal(starts[0].turns.some(turn=>turn.document_event),false);assert.equal(starts[0].turns.at(-1).text,t.state.turns.at(-1).text);assert.equal(appendCount,1,"Resumed voice receives only the coverage snapshot; finalized files are seeded once on the server");assert.equal(appended[0].options.kind,"interview_coverage");assert.match(appended[0].text,/Notes cover the current/);
  intake.reset();t.setIntake(null);t.conversationUI.live=null;t.setDocumentController(null);t.clearState();passes++;
 }
 {
  checkpoint();t.clearState({process_name:"Cancel stale question",objective:"Keep the current interview"});t.state.config={api_configured:true,speech:{enabled:false}};t.ensureConversation();
  const intake=t.createIntake(),originalFetch=context.fetch;let completeResponse,signal;
  context.fetch=async(_url,options)=>{signal=options.signal;return {ok:true,json:()=>new Promise(resolve=>completeResponse=resolve)};};
  const pending=t.realRequest("/api/interview",{...t.snapshot(),action:"answer"});await nextMicrotask();
  t.onDocumentEvent({type:"upload_started",batchId:"cancellation-check",names:["Reference.pdf"]});
  assert.equal(signal.aborted,true,"Beginning file intake aborts a pending ordinary interview request");
  const rejected=assert.rejects(pending,error=>error.name==="AbortError"&&!/too long/i.test(error.message));completeResponse({question:"A stale response delivered despite cancellation"});await rejected;
  assert.equal(t.state.turns.some(turn=>turn.text==="A stale response delivered despite cancellation"),false);
  intake.reset();t.setIntake(null);context.fetch=originalFetch;t.clearState();passes++;
 }
 {
  const originalFetch=context.fetch,flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  for(const outcome of ["response","transport-error"]){
   checkpoint();t.clearState({process_name:"Late cancellation",objective:"Keep accepted answers"});t.state.config={api_configured:true,speech:{enabled:false}};t.ensureConversation();
   t.state.turns=[{id:"t001",role:"assistant",text:"What starts the process?"}];t.state.summary="Retain the accepted baseline";
   const intake=t.createIntake();let finish,signal;
   context.fetch=(_url,options)=>{signal=options.signal;return new Promise((resolve,reject)=>finish=()=>outcome==="response"?resolve({ok:true,json:async()=>({question:"Discard this stale question",summary:"Discard stale baseline",coverage:[],memo_findings:[]})}):reject(new TypeError("Late transport failure")));};
   t.setRequest(t.realRequest);document.getElementById("answer-text").value="A supplier sends the request.";document.getElementById("retry-question").hidden=true;
   document.getElementById("global-notice").hidden=true;document.getElementById("interview-error").hidden=true;
   const sending=t.sendAnswer({preventDefault(){}});await flush();assert.equal(t.state.busy,true);
   t.onDocumentEvent({type:"upload_started",batchId:"late-result",names:["Empty.csv"]});assert.equal(signal.aborted,true);
   t.onDocumentEvent({type:"upload_settled",batchId:"late-result"});await flush();
   assert.equal(intake.phase,"ready","An intake with no new evidence can finish before a cancelled request settles");
   const acceptedTurns=JSON.stringify(t.state.turns);finish();await sending;
   assert.equal(JSON.stringify(t.state.turns),acceptedTurns,"A late cancelled response cannot change the transcript after intake is ready");
   assert.equal(t.state.turns.find(turn=>turn.role==="user").text,"A supplier sends the request.");assert.equal(t.state.summary,"Retain the accepted baseline");
   assert.equal(document.getElementById("retry-question").hidden,true,"Intentional cancellation must not offer a misleading retry");
   assert.equal(document.getElementById("global-notice").hidden,true);assert.equal(document.getElementById("interview-error").hidden,true,"Late cancellation must not display a timeout or transport failure");assert.equal(t.state.busy,false);
   intake.reset();t.setIntake(null);passes++;
  }
  checkpoint();t.clearState();
  context.fetch=(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")),{once:true}));
  const deadline=t.realRequest("/api/interview",t.snapshot(),{timeout:731});
  const deadlineRejected=assert.rejects(deadline,error=>error.name!=="AbortError"&&/took too long/.test(error.message));
  const deadlineTimer=[...timers.values()].find(timer=>timer.delay===731);assert.ok(deadlineTimer);deadlineTimer.fn();await deadlineRejected;passes++;
  const external=new AbortController(),cancelled=t.realRequest("/api/interview",t.snapshot(),{signal:external.signal});
  const cancelledRejected=assert.rejects(cancelled,error=>error.name==="AbortError"&&!/too long/.test(error.message));external.abort();await cancelledRejected;
  context.fetch=originalFetch;t.clearState();passes++;
 }
 {
  const sources=[{id:"u_mixed",role:"user",text:"The operations manager owns the overall result. I do not know the exact folder."}];
  const findings=t.normalizeFindings([{key:"accountable",status:"captured",answer:"The operations manager owns the overall result.",evidence_turns:["u_mixed"]},{key:"materials",status:"captured",answer:"The exact folder is unknown.",evidence_turns:["u_mixed"]}],sources,[]);
  assert.equal(findings.find(item=>item.key==="accountable").status,"captured","An unrelated uncertainty in the same source turn cannot erase a known role");assert.equal(findings.find(item=>item.key==="materials").status,"partial","Uncertainty in the actual topic answer must still veto completion");passes++;
 }
 {
  checkpoint();t.clearState();t.state.config={api_configured:true,speech:{enabled:false}};
  for(const id of ["draft-title","draft-overview","draft-trigger","draft-inputs","draft-outputs","draft-open-questions","draft-validation-notes","draft-exceptions","draft-controls","procedure-steps","connection-rows","memo-summary","lifecycle-items","variation-items"])if(!document.getElementById(id))mount(id,"div",review);
  const findings=completeFindings(),turns=[{id:"t002",role:"user",text:"Reported process facts."}];findings[7].status="not_applicable";findings[7].answer="The participant explicitly reported that variations do not apply.";
  const saved={schema_version:1,context:{process_name:"Saved process",objective:"Review the process"},turns,coverage:memoKeys.map(key=>({key,status:"covered"})),memo_findings:findings,summary:"Preserve the reported account.",closure:{asked:true,confirmed:true},draft:{title:"Saved report",steps:[],connections:[],memo_summary:findings}};
  const raw=JSON.stringify(saved);let calls=0;t.setRequest(async()=>{calls++;throw Error("Import cannot request a provider");});
  const unsent="  Check the exception first.\nThen confirm receipt. ";
  const pending=JSON.stringify({...saved,unsent_answer:unsent});
  await t.importSession({size:pending.length,text:async()=>pending});
  assert.equal(t.conversationUI.view,"transcript");assert.equal(interview.hidden,false);
  assert.equal(document.getElementById("answer-text").value,unsent);
  assert.equal(t.state.turns.length,turns.length,"Reopening a reply cannot submit it");passes++;
  await t.importSession({size:raw.length,text:async()=>raw});
  assert.equal(review.hidden,false,"A saved draft without a pending reply still opens in Review");
  assert.equal(calls,0);assert.equal(workflowTimers().length,0,"Opening a file must not schedule automatic provider analysis");assert.equal(JSON.stringify(saved),raw,"The supplied source remains unchanged");assert.equal(t.state.closure.confirmed,false);assert.equal(t.state.coverageNeedsReview,true);
  assert.equal(t.state.memo_findings.every(item=>item.status==="partial"),true);assert.equal(t.state.draft.memo_summary.every(item=>item.status==="partial"),true);assert.equal(t.state.coverage.every(item=>item.status!=="covered"),true);assert.equal(document.getElementById("coverage-count").textContent,"0 / 16");
  assert.deepEqual(JSON.parse(JSON.stringify(t.state.memo_findings.map(({key,answer,evidence_turns})=>({key,answer,evidence_turns})))),findings.map(({key,answer,evidence_turns})=>({key,answer,evidence_turns})));assert.notEqual(t.state.draftVersion,t.state.version);
  assert.match(document.getElementById("notice-text").textContent,/provisional.*Recheck coverage/);assert.equal(document.getElementById("retry-workflow").hidden,false);assert.equal(document.getElementById("retry-workflow").textContent,"Recheck coverage");passes++;
  t.setRequest(async(_path,_payload,options)=>{calls++;assert.equal(options.timeout,330000);return {workflow:graph("Reviewed process"),memo_findings:findings,coverage:[],summary:"Preserve the reported account.",focus:"",parking_lot:[],coverage_assessment:{all_topics_covered:true,topics:[]}};});
  await t.refreshWorkflow();assert.equal(calls,1);assert.equal(t.state.coverageNeedsReview,false);assert.equal(document.getElementById("coverage-count").textContent,"16 / 16");assert.equal(t.state.closure.confirmed,false,"Rechecking topic coverage cannot manufacture a new participant confirmation");assert.equal(document.getElementById("retry-workflow").dataset.coverageRecheck,undefined);t.clearState();passes++;
 }
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Incomplete review"};t.state.config={api_configured:true,speech:{enabled:false}};t.state.turns=[{id:"t002",role:"user",text:"A paper invoice arrives by post."}];let calls=0;
  const result={...memoResult("Retained process"),coverage_assessment:{all_topics_covered:false,review_available:false,topics:[],limitation:"Review unavailable"}};
  t.setRequest(async()=>{calls++;return result;});await t.refreshWorkflow();
  assert.equal(t.conversationUI.workflow.title,"Retained process");assert.match(document.getElementById("coverage-update-status").textContent,/Coverage review incomplete/);assert.equal(document.getElementById("retry-workflow").hidden,false);assert.equal(document.getElementById("retry-workflow").textContent,"Recheck coverage");assert.equal(workflowTimers().length,0,"Coverage review failure must not schedule an automatic provider retry");passes++;
  result.coverage_assessment={all_topics_covered:false,review_available:true,topics:[]};await t.refreshWorkflow();assert.equal(calls,2,"Explicit recheck can run even when the diagram is already current");assert.equal(t.state.coverageNeedsReview,false);assert.equal(document.getElementById("retry-workflow").dataset.coverageRecheck,undefined);t.clearState();passes++;
 }
 {
  checkpoint();const originalFetch=context.fetch;
  context.fetch=(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")),{once:true}));
  for(const [path,budget] of [["/api/interview",330000],["/api/workflow",330000],["/api/draft",330000],["/api/voice-session",150000]]){
   const external=new AbortController(),pending=t.realRequest(path,t.snapshot(),{signal:external.signal});
   assert.ok([...timers.values()].some(timer=>timer.delay===budget),`${path} must allow its aggregate provider stages while retaining a bounded deadline`);
   const rejected=assert.rejects(pending,error=>error.name==="AbortError");external.abort();await rejected;
  }
  context.fetch=originalFetch;passes++;
 }
 // Coverage feedback is a silent working interpretation, never a participant turn.
 {
  checkpoint();t.clearState();t.state.started=true;t.state.context={process_name:"Synthetic coverage",objective:"Capture all sections"};t.state.config={api_configured:true,live:{enabled:true},speech:{enabled:false}};
  const keys=["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials","scope","rules","connections","data_systems","volume"];
  const findings=keys.map(key=>({key,status:"captured",answer:"A supported account for this synthetic test.",evidence_turns:["t002"]}));
  const assessment={all_topics_covered:true,topics:keys.map(key=>({key,gaps:[],next_question:"",complete:true}))};
  t.state.turns=[{id:"t002",role:"user",text:"A participant account."}];t.state.memo_findings=findings;
  const updates=[];let speech=0,stops=0;
  const live={active:false,connected:false,async start(){this.active=true;this.connected=true;},stop(){stops++;this.active=false;this.connected=false;},sendText(){speech++;},appendContext(content,options){updates.push({text:content,raw:content,options});return Promise.resolve({status:"acknowledged"});}};
  t.conversationUI.live=live;const beforeStart=JSON.stringify(t.state.turns);await t.startLiveConversation();
  assert.equal(updates.length,0,"Saved findings without a current accepted checkpoint send no live update");
  assert.equal(JSON.stringify(t.state.turns),beforeStart);passes++;
  const result=()=>({workflow:graph("Synthetic coverage"),memo_findings:findings,coverage:[],summary:"Reported facts",focus:"Coverage",parking_lot:[],coverage_assessment:assessment});
  t.setRequest(async()=>result());await t.refreshWorkflow();
  assert.equal(updates.length,1);assert.match(updates.at(-1).text,/Notes cover the current/);assert.match(updates.at(-1).text,/Nothing is open/);assert.equal(updates.at(-1).options.kind,"interview_coverage");assert.equal(updates.at(-1).options.replaceKey,"interview_coverage");assert.equal(updates.at(-1).options.plain,true);assert.equal(JSON.stringify(t.state.turns),beforeStart);assert.equal(speech,0);assert.equal(stops,0);passes++;
  t.receiveLiveCaption({id:"coverage-correction",role:"user",text:"A later correction",final:false});
  t.receiveLiveCaption({id:"coverage-correction",role:"user",text:"A later correction continues",final:false});t.receiveLiveCaption({id:"coverage-correction",role:"user",text:"A later correction continues",final:true});
  assert.equal(updates.length,1,"Caption fragments send no notes update; a stream of silent context mid-answer made the live model voice the participant");assert.equal(speech,0);passes++;
  let finish;checkpoint();t.setRequest(()=>new Promise(resolve=>finish=resolve));const pending=t.refreshWorkflow();
  t.receiveLiveCaption({id:"coverage-correction",role:"user",text:"A later correction continues with another detail",final:true});finish(result());await pending;
  assert.equal(updates.length,1,"A checkpoint that lags the newest answer sends no update");passes++;
  checkpoint();assessment.all_topics_covered=false;assessment.topics.find(topic=>topic.key==="risk").gaps=["Failure consequences remain unexplained."];assessment.topics.find(topic=>topic.key==="risk").next_question="What happens if the notice is wrong?";
  t.setRequest(async()=>result());await t.refreshWorkflow();
  assert.match(updates.at(-1).text,/Notes cover the current/);assert.match(updates.at(-1).text,/Still open: risk\./,"A reviewer gap keeps its topic open in the note even when the memo is all green");assert.doesNotMatch(updates.at(-1).text,/What happens if the notice is wrong|I ask:/,"The reviewer cannot supply a spoken question through silent context");assert.ok(new TextEncoder().encode(updates.at(-1).raw).length<=480,"The note fits one context event");passes++;
  const updateCount=updates.length;live.stop();await t.startLiveConversation();assert.equal(updates.length,updateCount+1,"A reconnected session receives its own coverage context");assert.match(updates.at(-1).text,/Notes cover the current/);assert.equal(new Set(updates.map(update=>update.options.id)).size,updates.length);passes++;
  const heldCount=updates.length;t.receiveLiveCaption({id:"unfinished-coverage-answer",role:"user",text:"A thought that has not ended",final:false});checkpoint();t.setRequest(async()=>result());await t.refreshWorkflow();
  assert.equal(updates.length,heldCount,"A note is held while a participant caption is still in progress; mid-answer it made the live model finish the participant's sentence");
  t.receiveLiveCaption({id:"unfinished-coverage-answer",role:"user",text:"A thought that has not ended",final:true});
  assert.equal(updates.length,heldCount+1,"The held note is sent once the participant pauses");assert.match(updates.at(-1).text,/Notes cover the current/,"The capture already covered the finished caption's text");
  t.conversationUI.revision++;checkpoint();t.setRequest(async()=>result());await t.refreshWorkflow();assert.match(updates.at(-1).text,/Notes cover the current/,"The next completed capture reports current notes");passes++;
  t.conversationUI.revision++;for(const finding of findings)finding.answer="界".repeat(4000);for(const topic of assessment.topics){topic.gaps=["界".repeat(500),"界".repeat(500),"界".repeat(500)];topic.next_question="界".repeat(500);}
  checkpoint();t.setRequest(async()=>result());await t.refreshWorkflow();assert.ok(new TextEncoder().encode(updates.at(-1).raw).length<=480,"Coverage labels fit one event regardless of reviewer verbosity");assert.doesNotMatch(updates.at(-1).text,/界|I ask:/,"Findings and suggested questions are omitted from the live note");assert.equal(t.state.memo_findings[0].answer.length,4000,"Accepted findings remain intact");passes++;
  const oldCount=updates.length;t.conversationUI.revision++;checkpoint();t.setRequest(async()=>{throw Error("Capture unavailable");});await t.refreshWorkflow();assert.equal(updates.length,oldCount,"A failed capture cannot publish an invented coverage checkpoint");
  live.active=false;t.conversationUI.live=null;t.clearState();passes++;
 }
 {
  checkpoint();t.state.config={api_configured:true,agent_team:{enabled:true},speech:{enabled:false}};t.state.started=true;t.state.context={process_name:"Review test"};
  t.state.turns=[{id:"t002",role:"user",text:"A definite reported process account."}];t.state.memo_findings=["name","purpose","trigger","completion","accountable","lifecycle","checks","variations","pain_points","risk","materials","scope","rules","connections","data_systems","volume"].map(key=>({key,status:"captured",answer:"A definite reported detail.",evidence_turns:["t002"]}));
  t.state.coverageVerified=false;t.renderCoverage();assert.equal(document.getElementById("coverage-count").textContent,"0 / 16");assert.match(document.getElementById("coverage-summary").textContent,/16 captured.*awaiting review/);assert.match(document.getElementById("memo-next").textContent,/awaiting.*review/);
  const topic=document.querySelector('[data-foundation-topic="name"]');assert.equal(topic.classList.contains("covered"),false);assert.match(topic.querySelector(".coverage-state").textContent,/awaiting review/);t.showFoundationTopic("name",topic);assert.match(document.getElementById("foundation-topic-status").textContent,/awaiting review/);t.closeFoundationTopic(false);
  t.state.coverageVerified=true;t.renderCoverage();assert.equal(document.getElementById("coverage-count").textContent,"16 / 16");assert.equal(document.querySelector('[data-foundation-topic="name"]').classList.contains("covered"),true);passes++;
  t.state.captureToken="opaque-server-capability";assert.equal(t.snapshot().capture_token,"opaque-server-capability");assert.ok(!JSON.stringify(t.sessionObject()).includes("opaque-server-capability"),"Server review capabilities must not be persisted in saved files");passes++;
  t.conversationUI.revision=20;t.conversationUI.applied=0;t.conversationUI.flowBusy=false;t.conversationUI.live=null;t.state.busy=false;t.conversationUI.view="voice";checkpoint();t.scheduleWorkflow();assert.equal(workflowTimers().length,1,"Ordinary turns schedule the map alongside the lead, whichever view is open");
  checkpoint();t.state.busy=true;t.scheduleWorkflow();assert.equal(workflowTimers().length,1,"A lead turn in progress does not postpone the concurrent map");t.state.busy=false;
  checkpoint();t.state.importing=true;t.scheduleWorkflow();assert.equal(workflowTimers().length,0,"Opening a saved interview must not start a map request");t.state.importing=false;
  checkpoint();t.selectConversationView("workflow");assert.equal(workflowTimers().length,1,"Opening Workflow still refreshes a map that is behind");passes++;
  checkpoint();t.state.example=true;t.conversationUI.applied=-1;let exampleCalls=0;t.setRequest(async()=>{exampleCalls++;return memoResult("Explicit fictional refresh");});
  for(const view of ["workflow","transcript","voice","workflow"])t.selectConversationView(view);
  assert.equal(workflowTimers().length,0,"Built-in or reopened synthetic examples must not schedule provider work when browsing views");assert.equal(exampleCalls,0);passes++;
  await t.refreshWorkflow();assert.equal(exampleCalls,1,"An explicit refresh remains available in example mode");assert.equal(t.conversationUI.workflow.title,"Explicit fictional refresh");t.state.example=false;passes++;
 }
 {
  // Advisory pre-check of provisional topics: display-only, bound to the exact captured answer.
  checkpoint();t.clearState();t.state.config={api_configured:true,agent_team:{enabled:true},speech:{enabled:false}};t.state.started=true;t.state.context={process_name:"Advisory test"};
  t.state.turns=[{id:"t001",role:"assistant",text:"What starts the work?"},{id:"t002",role:"user",text:"An email starts it."}];t.state.captureToken="capture-advisory";
  const calls=[];t.setRequest(async(url,payload)=>{calls.push({url,payload});return {advisory:true,revision:"r1",answers:{trigger:"An email starts the work."},topics:[{key:"trigger",complete:true,gaps:[],next_question:""}]};});
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  const reply=(question,findings)=>({question,summary:"",focus:"",parking_lot:[],coverage:[],memo_findings:findings,speech_authorization:{approved:true,kind:"question",text:question},capture_token:"capture-advisory"});
  t.applyInterview(reply("Who receives the email?",[{key:"trigger",status:"captured",answer:"An email starts the work.",evidence_turns:["t002"]},{key:"purpose",status:"partial",answer:"A registered invoice.",evidence_turns:["t002"]}]));
  assert.equal(calls.length,1);assert.equal(calls[0].url,"/api/agent-team/coverage");assert.equal(calls[0].payload.capture_token,"capture-advisory");
  assert.match(document.getElementById("coverage-summary").textContent,/checking/);
  await settle();await settle();
  assert.equal(t.state.advisory.trigger.complete,true);
  let item=document.querySelector('[data-foundation-topic="trigger"]');assert.match(item.querySelector(".coverage-state").textContent,/pre-checked/);
  assert.equal(item.classList.contains("covered"),false,"An advisory check never counts as official coverage");assert.equal(document.getElementById("coverage-count").textContent,"0 / 16");
  assert.match(document.getElementById("coverage-summary").textContent,/1 captured · awaiting review · 1 pre-checked/);
  t.showFoundationTopic("trigger",item);assert.match(document.getElementById("foundation-topic-status").textContent,/pre-checked/);t.closeFoundationTopic(false);
  // Topics already pre-checked for the same answer are not checked again; a changed answer loses its mark.
  t.applyInterview(reply("Who logs it?",[{key:"trigger",status:"captured",answer:"An email starts the work.",evidence_turns:["t002"]}]));
  assert.equal(calls.length,1,"An unchanged pre-checked topic needs no new advisory call");
  t.state.memo_findings.find(f=>f.key==="trigger").answer="A phone call starts the work.";t.renderCoverage();
  item=document.querySelector('[data-foundation-topic="trigger"]');assert.match(item.querySelector(".coverage-state").textContent,/awaiting review/);
  t.state.coverageVerified=true;t.renderCoverage();assert.equal(document.querySelector('[data-foundation-topic="trigger"]').classList.contains("covered"),true,"Official review supersedes advisory marks");
  t.state.coverageVerified=false;t.clearState();assert.equal(Object.keys(t.state.advisory).length,0,"A new interview starts without advisory marks");assert.equal(t.state.provisionalQuestion,null);passes++;
 }
 {
  // Live front, managed back: GPT-Live speaks; captions drive the background lead; the app owns completion.
  checkpoint();t.clearState();t.conversationUI.live=null;t.state.started=true;t.state.context={process_name:"Live front",objective:"Keep the gates"};
  t.state.config={api_configured:true,agent_team:{enabled:true,voice_mode:"live_front"},live:{enabled:true},speech:{enabled:false}};
  let callbacks;const said=[],appended=[],stops=[];
  context.window.CollectorLiveVoice=class{
   constructor(options){callbacks=options;this.active=false;this.connected=false;}
   async start(){this.active=true;this.connected=true;callbacks.onStatus("listening");return true;}
   say(text){said.push(text);const id="spoken-"+said.length;callbacks.onTranscript({id,role:"assistant",text,final:true});return Promise.resolve({status:"captioned",captionId:id});}
   appendContext(text,meta){appended.push({text,meta});return Promise.resolve({status:"acknowledged"});}
   async stop(){stops.push(1);this.active=false;this.connected=false;callbacks.onStatus("idle");return{finalized:true};}
  };
  const settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
  const runCaptureTimer=async()=>{const entry=[...timers.entries()].find(([,timer])=>timer.delay===400);assert.ok(entry,"A final participant caption schedules one background capture");timers.delete(entry[0]);entry[1].fn();await settle();};
  const lastUser=()=>t.state.turns.findLast(turn=>turn.role==="user").id;
  const reply=(question,kind="question",extra={})=>({question,summary:"Summary.",focus:"Focus",parking_lot:[],coverage:[],
    memo_findings:[{key:"trigger",status:"captured",answer:"An email starts it.",evidence_turns:[lastUser()]}],capture_token:"live-token",coverage_verified:false,
    completion:{ready_for_final_check:kind==="final_check"||kind==="complete",complete:kind==="complete"},
    speech_authorization:{approved:true,kind,text:question,revision:"r",completion_allowed:kind==="complete"},...extra});
  const calls=[];let answer=()=>({});t.setRequest(async(url,payload)=>{calls.push({url,payload});return answer(url,payload);});
  await t.startLiveConversation();assert.ok(t.conversationUI.live instanceof context.window.CollectorLiveVoice,"live_front selects GPT-Live");
  answer=url=>url==="/api/interview"?reply("Who receives the email?"):{};
  callbacks.onTranscript({id:"c1",role:"assistant",text:"What starts the work?",final:true});
  callbacks.onTranscript({id:"c2",role:"user",text:"An email starts it.",final:true});
  await runCaptureTimer();
  assert.equal(calls.filter(call=>call.url==="/api/interview").length,1);assert.equal(calls[0].payload.action,"answer");
  assert.equal(t.state.memo_findings.find(f=>f.key==="trigger").status,"captured");assert.equal(t.state.captureToken,"live-token");
  assert.ok(!t.state.turns.some(turn=>turn.text==="Who receives the email?"),"The lead's question is not spoken or added; GPT-Live asks its own");
  assert.equal(t.state.liveSuggestedQuestion,"");
  assert.ok(appended.some(item=>/Notes cover the current/.test(item.text)&&item.meta.plain===true),"Current capture status reaches GPT-Live silently");
  assert.ok(appended.every(item=>!item.text.includes("Who receives the email?")),"The background lead never scripts the live follow-up");
  // Completion readiness: the app records the acknowledgement, has GPT-Live say it, runs the review, then issues the final check.
  const ack="Let me check that I have everything before we finish.",finalCheck="Before we finish, is there anything else someone doing this work needs to know that we haven’t captured?";
  answer=url=>url==="/api/interview"?reply(ack,"review_pending",{review_ticket:"ticket-1",agent_run_id:"run-1"}):url==="/api/agent-team/review"?reply(finalCheck,"final_check",{coverage_verified:true}):{};
  callbacks.onTranscript({id:"c3",role:"assistant",text:"Who receives it?",final:true});
  callbacks.onTranscript({id:"c4",role:"user",text:"The AP clerk receives it.",final:true});
  await runCaptureTimer();
  assert.equal(said.join("|"),[ack,finalCheck].join("|"),"Both authorized lines are given to GPT-Live in order");
  assert.equal(t.state.turns.slice(-2).map(turn=>turn.text).join("|"),[ack,finalCheck].join("|"),"Authorized lines are the assistant's turns");
  assert.equal(calls.filter(call=>call.url==="/api/agent-team/review").length,1);assert.equal(t.state.coverageVerified,true);assert.equal(t.state.closure.asked,true);
  const before=t.state.turns.length;callbacks.onTranscript({id:"c5",role:"assistant",text:"Before we finish, is there anything else we missed?",final:true});
  assert.equal(t.state.turns.length,before+1,"A different spoken caption is retained");
  answer=url=>url==="/api/interview"?reply("Thank you. All eleven sections are captured and you have confirmed the account.","complete",{coverage_verified:true,no_new_run:true}):{};
  callbacks.onTranscript({id:"c6",role:"user",text:"No, nothing else to add.",final:true});
  await runCaptureTimer();
  assert.equal(t.state.closure.confirmed,true);assert.equal(said.length,3);
  await settle();assert.equal(stops.length,1,"The confirmed closing caption ends the session after playback settles");
  t.clearState();t.conversationUI.live=null;delete context.window.CollectorLiveVoice;passes++;
 }
 {
  checkpoint();t.state.busy=false;t.conversationUI.live=null;t.conversationUI.status="idle";t.conversationUI.view="transcript";
  const ack="Let me check that I have everything before we finish.";
  t.applyInterview({question:ack,review_ticket:"wait-label-ticket",capture_token:"wait-label-capture",coverage_verified:false,speech_authorization:{approved:true,kind:"review_pending",text:ack,revision:"review-label"},completion:{ready_for_final_check:false,complete:false}});
  let finish;t.setRequest(()=>new Promise(resolve=>finish=resolve));const reviewing=t.retryQuestion();t.exerciseControls();
  assert.equal(document.getElementById("thinking-text").textContent,"Checking the recorded topics and process…");t.updatePresence();assert.equal(document.getElementById("presence-status").textContent,"Checking the recorded topics and process…");
  t.conversationUI.live={active:true,connected:true};t.conversationUI.status="processing";t.updatePresence();assert.equal(document.getElementById("session-status").textContent,"Checking the recorded topics and process…");
  t.conversationUI.live=null;t.conversationUI.status="idle";finish({question:"Which handoff needs more detail?",coverage_verified:true});await reviewing;
  t.state.busy=true;t.state.busyMessage="";t.exerciseControls();assert.equal(document.getElementById("thinking-text").textContent,"Thinking of the next question…");t.updatePresence();assert.equal(document.getElementById("presence-status").textContent,"Thinking…");t.state.busy=false;passes++;
 }
 {
  checkpoint();t.clearState();t.conversationUI.live=null;
  for(const [prefix,parent] of [["map",review],["workflow",interview]]){
   mount(prefix+"-diagram","div",parent);
   mount(prefix+"-walkthrough","div",parent).hidden=true;
   for(const mode of ["diagram","walkthrough"])mount(prefix+"-mode-"+mode,"button",parent);
  }
  const players=[];
  context.window.CollectorWalkthrough={create(root,actions){
   const player={
    root,actions,visible:false,destroyed:false,
    update(data,{live}){this.title=data?.steps[0]?.title;this.live=live;},
    setVisible(value){this.visible=value;},
    destroy(){this.destroyed=true;}
   };
   players.push(player);return player;
  }};
  let cinematicRequests=0;
  t.setRequest(()=>{cinematicRequests++;throw Error("Viewing a captured map must stay local");});
  t.state.example=false;t.state.config={api_configured:true,agent_team:{enabled:true}};
  t.state.turns=[{id:"t002",role:"user",text:"I send the invoice to Treasury."}];
  t.conversationUI.applied=t.conversationUI.revision;
  t.renderTranscript();
  t.selectReviewSection("review-map");
  t.state.draft=graph("Draft",[{id:"S1",title:"Draft intake"}]);
  t.conversationUI.workflow=graph("Working",[{id:"S1",title:"Working intake"}]);
  t.tab("review");t.selectWorkflowMode("process-map","walkthrough");
  const draft=players[0];
  assert.equal(draft.visible,true);assert.equal(draft.live,false);assert.equal(draft.title,"Draft intake");
  assert.equal(document.getElementById("map-diagram").hidden,true);
  assert.equal(document.getElementById("export-map").hidden,true);
  const sourceRow=draft.actions.renderEvidence(["t002"]);
  draft.root.append(sourceRow);sourceRow.querySelector("button").dispatch("click");
  assert.equal(t.conversationUI.view,"transcript");
  const updatedRow=draft.actions.renderEvidence(["t002"]);
  draft.root.replaceChildren(updatedRow);t.returnToSource();
  assert.equal(document.activeElement,updatedRow.querySelector("button"),"Return to the selected connector's evidence");
  t.selectReviewSection("review-procedure");assert.equal(draft.visible,false);
  t.state.draft.steps[0].title="Edited draft intake";
  t.selectReviewSection("review-map");assert.equal(draft.title,"Edited draft intake");
  draft.actions.onDetails("S1");assert.equal(document.getElementById("workflow-step-title").textContent,"Edited draft intake");stepDialog.close();
  t.tab("interview");t.selectConversationView("workflow");assert.equal(draft.visible,false);
  assert.equal(document.getElementById("workflow-walkthrough").hidden,true);
  t.selectWorkflowMode("live-workflow","walkthrough");const working=players[1];
  assert.equal(working.visible,true);assert.equal(working.live,true);assert.equal(working.title,"Working intake");
  const staticCanvases=fakeWorkflow();
  t.conversationUI.workflow=graph("Working",[{id:"S1",title:"Updated working intake"}]);
  t.renderWorkingMap();assert.equal(working.title,"Updated working intake");
  assert.equal(staticCanvases.length,0,"A captured update lays out only the cinematic map while it is selected");
  assert.equal(document.getElementById("export-working-map").disabled,true);
  document.hidden=true;t.syncWorkflowVisibility();assert.equal(working.visible,false);
  t.conversationUI.workflow=graph("Working",[{id:"S1",title:"New evidence while hidden"}]);
  t.renderWorkingMap();assert.equal(working.title,"Updated working intake");
  document.hidden=false;t.syncWorkflowVisibility();assert.equal(working.visible,true);
  assert.equal(working.title,"New evidence while hidden");
  t.selectConversationView("transcript");assert.equal(working.visible,false);
  t.selectConversationView("workflow");assert.equal(working.visible,true);
  working.actions.onExit();assert.equal(working.visible,false);
  assert.equal(document.activeElement.id,"workflow-mode-diagram");
  assert.equal(staticCanvases[0].requests[0].graph,t.conversationUI.workflow);
  assert.equal(document.getElementById("export-working-map").disabled,true,"Static export waits for the latest layout");
  staticCanvases[0].requests[0].resolve(true);await nextMicrotask();
  assert.equal(document.getElementById("export-working-map").disabled,false);
  assert.equal(cinematicRequests,0);
  assert.equal(t.conversationUI.flowTimer,null,"Viewing existing evidence schedules no model request");
  finishCanvases();
  t.clearState();assert.ok(players.every(player=>player.destroyed));
  assert.equal(document.getElementById("map-mode-diagram").getAttribute("aria-pressed"),"true");
  assert.equal(document.getElementById("export-map").hidden,false);
  delete context.window.CollectorWalkthrough;passes++;
 }
 {
  // Explicit component choices travel only in a local Save copy; use the real catalog and editor.
  checkpoint();t.setDocumentController(null);
  vm.runInContext(fs.readFileSync(path.join(__dirname,"..","web","workflow-components.js"),"utf8"),context);
  const players={};
  context.window.CollectorWalkthrough={create(root,actions){
   const player={actions,setVisible(){},destroy(){},update(data){this.graph=data;}};
   players[root.id]=player;return player;
  }};
  const types=["activity","document","data_store","subprocess","decision","start","end","wait","parallel_split","parallel_join","merge"];
  const input={title:"Example process",steps:types.map((type,i)=>({id:"M"+i,type,title:"Handle item "+i,evidence_turns:["t002"]})),connections:[]};
  const base={schema_version:1,context:{process_name:"Example process"},turns:[{id:"t002",role:"user",text:"Fictional account"}],draft:input,workflow:input,coverage:[],synthetic_example:true};
  const open=async saved=>{const data=JSON.stringify(saved);await t.importSession({size:data.length,text:async()=>data});};
  const reviewPlayer=()=>{t.tab("review");t.selectReviewSection("review-map");t.selectWorkflowMode("process-map","walkthrough");return players["map-walkthrough"];};
  const control=label=>walk(document.getElementById("procedure-steps")).find(node=>node.getAttribute("aria-label")===label);
  const save=()=>{t.exportSession();return JSON.parse(context.window.__downloads.at(-1)[0]);};
  let modelCalls=0;
  t.setRequest(()=>{modelCalls++;throw Error("Unexpected request");});
  await open(base);let player=reviewPlayer();
  const source=JSON.stringify([t.state.draft,t.conversationUI.workflow,t.snapshot()]);
  for(const design of context.window.CollectorComponents.all)assert.equal(player.actions.onSetDesign("M0",design.id),true);
  for(const step of input.steps.slice(0,4))assert.equal(player.actions.onSetDesign(step.id,"invoice"),true);
  for(const step of input.steps.slice(4))assert.equal(player.actions.onSetDesign(step.id,"invoice"),false);
  for(const invalid of ["unrecognized",[],{},7,"x".repeat(200)])assert.equal(player.actions.onSetDesign("M0",invalid),false);
  assert.equal(player.actions.onSetDesign("missing","invoice"),false);
  assert.equal(JSON.stringify([t.state.draft,t.conversationUI.workflow,t.snapshot()]),source);
  assert.equal(t.state.dirty,true);assert.equal(t.state.draftEdited,false);
  assert.equal(t.sessionObject().presentation,undefined,"Knowledge submission receives no local design preferences");
  const saved=save();assert.equal(saved.presentation.component_designs.M0,"invoice");
  assert.deepEqual(saved.draft,JSON.parse(JSON.stringify(t.state.draft)));
  assert.equal(player.actions.onSetDesign("M0",null),true);assert.equal(player.graph.component_designs.M0,undefined);
  assert.equal(player.actions.onSetDesign("M0",null),true,"Choosing Automatic again closes the picker without creating another edit");
  const oldActions=player.actions;
  await open({...saved,presentation:{component_designs:{...saved.presentation.component_designs,M1:23,M4:"invoice",missing:"invoice",M2:"obsolete"}}});
  player=reviewPlayer();assert.deepEqual(Object.entries(player.graph.component_designs),[["M0","invoice"],["M3","invoice"]]);
  assert.equal(oldActions.onSetDesign("M0","waterfall"),false,"An action from a previous interview cannot change the new draft");
  t.tab("interview");t.selectConversationView("workflow");t.selectWorkflowMode("live-workflow","walkthrough");
  const live=players["workflow-walkthrough"];assert.equal(live.actions.onSetDesign,undefined);assert.equal(live.graph.component_designs,undefined);
  player=reviewPlayer();t.selectReviewSection("review-procedure");
  const type=control("Type of step M0");type.value="document";type.dispatch("change");assert.equal(save().presentation.component_designs.M0,"invoice");
  type.value="decision";type.dispatch("change");type.value="activity";type.dispatch("change");
  assert.equal(save().presentation.component_designs.M0,undefined,"Changing to a structural type removes the override permanently");
  const remove=control("Remove step M3");context.confirm=()=>false;remove.dispatch("click");
  assert.equal(save().presentation.component_designs.M3,"invoice");
  context.confirm=()=>true;remove.dispatch("click");
  assert.equal(save().presentation,undefined,"A removed ID cannot pass its previous choice to a future step");
  await open(saved);player=reviewPlayer();assert.equal(player.graph.component_designs.M0,"invoice");
  context.confirm=()=>false;await t.generateDraft();assert.equal(save().presentation.component_designs.M0,"invoice");
  assert.equal(modelCalls,0);
  context.confirm=()=>true;
  t.setRequest(async(url,payload)=>{modelCalls++;assert.equal(url,"/api/draft");assert.equal(payload.presentation,undefined);assert.equal(payload.component_designs,undefined);return {draft:input};});
  await t.generateDraft();assert.equal(modelCalls,1);assert.equal(save().presentation,undefined,"A regenerated draft may reuse step IDs for different work");
  await open(base);player=reviewPlayer();assert.equal(player.graph.component_designs,undefined,"Old saved sessions automatically use the catalog");
  player.actions.onSetDesign("M1","invoice");t.clearState();assert.equal(save().presentation,undefined);
  delete context.window.CollectorWalkthrough;passes++;
 }
 {
  // A connection belongs to the chosen endpoints and condition, not to the order of steps.
  const steps=["A","B","C","D"].map(id=>({id,title:"Step "+id,type:"activity",evidence_turns:[]}));
  const graph={steps,connections:[
   {from:"A",to:"B",label:"Released",evidence_turns:["t002"]},
   {from:"A",to:"B",label:"Released",evidence_turns:["t004","t002"]},
   {from:"A",to:"B",label:"Exempt",evidence_turns:[]},
   {from:"B",to:"A",label:"Return",evidence_turns:[]},
   {from:"C",to:"D",label:"Separate work",evidence_turns:[]}
  ]};
  const original=JSON.stringify(graph), projected=t.mapProjection(graph);
  assert.equal(projected.connections.length,4);
  assert.deepEqual(Array.from(projected.connections[0].evidence_turns),["t002","t004"]);
  assert.equal(JSON.stringify(graph),original,"Map projection must preserve the saved records");
  assert.match(t.workflowGapSummary(graph),/2 separate groups/);
  assert.equal(t.workflowGapSummary({...graph,connections:[...graph.connections,{from:"B",to:"C"}]}),"");
  passes++;

  const editor=mount("connection-editor","dialog"),form=mount("connection-form","form",editor);
  const newFrom=mount("connection-from","select",form),newTo=mount("connection-to","select",form),
    label=mount("connection-condition","input",form),choice=mount("connection-source-choice","label",form);
  mount("connection-editor-title","h2",form);mount("save-connection","button",form);
  mount("source-choice-label","span",choice);
  const keep=mount("connection-keep-sources","input",choice),error=mount("connection-error","p",form);
  const submit=()=>form.onsubmit({preventDefault(){}});
  t.state.draft={title:"Manual routes",steps,connections:graph.connections.slice(2)};
  const baseline=JSON.stringify(t.state.draft);
  t.openConnectionEditor();
  assert.equal(newFrom.value,"");assert.equal(newTo.value,"");
  assert.equal(JSON.stringify(t.state.draft),baseline);editor.close();
  t.openConnectionEditor();newFrom.value="A";newTo.value="B";label.value="Exempt";submit();
  assert.equal(editor.open,true);assert.equal(error.hidden,false);assert.equal(JSON.stringify(t.state.draft),baseline);
  newFrom.value="C";newTo.value="C";label.value="Still pending";submit();
  assert.equal(editor.open,false);assert.equal(t.state.draft.connections.at(-1).to,"C");passes++;

  const cited=t.state.draft.connections[0];cited.evidence_turns=["t002"];
  t.openConnectionEditor(cited);newFrom.value="D";form.oninput({target:newFrom});editor.close();
  assert.deepEqual(Array.from(cited.evidence_turns),["t002"]);assert.equal(cited.from,"A");
  t.openConnectionEditor(cited);newFrom.value="D";form.oninput({target:newFrom});submit();
  assert.equal(t.state.draft.connections[0].from,"D");
  assert.deepEqual(Array.from(t.state.draft.connections[0].evidence_turns),[]);
  const previous=t.state.draft.connections.at(-1);previous.evidence_turns=["t002"];
  t.openConnectionEditor(previous);label.value="Pending approval";form.oninput({target:label});keep.checked=true;submit();
  assert.deepEqual(Array.from(t.state.draft.connections.at(-1).evidence_turns),["t002"]);passes++;
 }
 checkpoint();console.log(JSON.stringify({tests_passed:passes,provider_calls:providerCalls,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
