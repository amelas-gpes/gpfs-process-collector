"use strict";
// gap-uncommitted-diff-3: a saved interview opened on a computer that does not have its file
// workspace. "Start new file workspace" must leave an interview that can update its working map,
// take answers and be submitted, without the browser ever supplying evidence for the old files:
// the excerpts saved from them stay with the interview as references and their IDs are left out
// of everything that is sent. Real web/app.js, web/documents.js and web/knowledge-ui.js behind a
// synthetic DOM. The network boundary is a stand-in that refuses what server.py refuses
// (validate_workflow and validate_findings without a file scope, an unknown scope, a submission
// citing a file that is not among the interview's files). No browser, provider or real network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const read=name=>fs.readFileSync(path.join(__dirname,"..","web",name),"utf8");
const appSource=read("app.js"),documentsSource=read("documents.js"),knowledgeSource=read("knowledge-ui.js");
const flush=async()=>{for(let i=0;i<80;i++)await Promise.resolve();};
const plain=value=>JSON.parse(JSON.stringify(value));

const walk=node=>[node,...node.children.flatMap(walk)];
const dataKey=name=>name.replace(/^data-/,"").replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase());
function matches(node,selector){
  if(selector.startsWith("."))return node.className.split(/\s+/).includes(selector.slice(1));
  const attribute=selector.match(/^\[(data-[a-z-]+)(?:="([^"]*)")?\]$/);
  if(attribute)return attribute[2]===undefined?node.dataset[dataKey(attribute[1])]!==undefined:node.dataset[dataKey(attribute[1])]===attribute[2];
  return node.tagName===selector.toUpperCase();
}
class Element{
  constructor(tag,doc){this.tagName=String(tag).toUpperCase();this.ownerDocument=doc;this.children=[];this.parentElement=null;this.listeners={};this.attributes={};this.dataset={};this.style={};
    this.className="";this.id="";this.hidden=false;this.open=false;this.disabled=false;this.checked=false;this.value="";this._text="";
    this.classList={contains:name=>this.className.split(/\s+/).includes(name),add:name=>{if(!this.classList.contains(name))this.className=(this.className+" "+name).trim();},
      remove:name=>{this.className=this.className.split(/\s+/).filter(value=>value!==name).join(" ");},
      toggle:(name,force)=>{const on=force===undefined?!this.classList.contains(name):Boolean(force);if(on)this.classList.add(name);else this.classList.remove(name);return on;}};}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join("");}
  set textContent(value){this.replaceChildren();this._text=String(value);}
  // A node of the page itself (looked up by ID) answers for markup this stand-in does not hold.
  placeholder(name){this.placeholders??=new Map();if(!this.placeholders.has(name))this.placeholders.set(name,new Element("span",this.ownerDocument));return this.placeholders.get(name);}
  get firstElementChild(){return this.children[0]||(this.page?this.placeholder("first"):null);}
  append(...children){for(const child of children){if(!(child instanceof Element))continue;if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(item=>item!==child);child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){this.children.forEach(child=>{child.parentElement=null;});this.children=[];this._text="";this.append(...children);}
  setAttribute(name,value){this.attributes[name]=String(value);}
  getAttribute(name){return this.attributes[name]??null;}
  removeAttribute(name){delete this.attributes[name];}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  removeEventListener(name,fn){this.listeners[name]=(this.listeners[name]||[]).filter(item=>item!==fn);}
  async dispatch(name){for(const fn of this.listeners[name]||[])await fn({target:this,preventDefault(){}});}
  click(){if(!this.disabled)return this.dispatch("click");}
  focus(){this.ownerDocument.activeElement=this;}
  scrollIntoView(){}setSelectionRange(){}
  showModal(){this.open=true;}close(){this.open=false;}
  contains(node){return walk(this).includes(node);}
  closest(){return null;}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null;}
  querySelectorAll(selector){return walk(this).filter(node=>node!==this&&matches(node,selector));}
  querySelector(selector){return this.querySelectorAll(selector)[0]||(this.page?this.placeholder(selector):null);}
}

const OLD_SCOPE="A".repeat(43),DOC="doc_0123456789abcdef",MIXED=DOC+"_p1_c1",ALONE=DOC+"_p2_c1";
const UNAVAILABLE={code:"document_scope_unavailable",error:"The saved file workspace is unavailable on this computer."};
const step=(id,title,sources)=>({id,title,type:"activity",actor:"Accounts payable clerk",system:"",description:title,evidence_turns:sources});
function savedInterview(){
  return {schema_version:1,saved_at:"2026-11-13T09:00:00.000Z",
    context:{process_name:"Invoice approval",process_owner:"",objective:"Understand the current process.",background:""},process_name_manual:true,derived_process_title:"",
    turns:[{id:"t001",role:"user",text:"I receive each supplier invoice by email and check it against the purchase order."},
      {id:"t002",role:"assistant",text:"Who approves an invoice above the limit?"},
      {id:"t003",role:"user",text:"The finance manager gives the second approval."}],
    documents:{scope:OLD_SCOPE,documents:[{id:DOC,name:"Approval policy.pdf",kind:"pdf",status:"ready",chunk_count:2,
      analysis:{phase:"complete",disposition:"relevant",version:1,intent_version:1,summary:"Approval limits.",sources:[{source_id:MIXED,label:"Page 1"}]}}]},
    document_evidence:[{id:MIXED,document_id:DOC,name:"Approval policy.pdf",label:"Page 1",text:"Invoices above 5,000 need a second approval by the finance manager."},
      {id:ALONE,document_id:DOC,name:"Approval policy.pdf",label:"Page 2",text:"Approved invoices are archived for seven years."}],
    // S2 rests on an answer and on the file; S3 and the route into it rest on the file alone.
    workflow:{title:"Invoice approval",steps:[step("S1","Receive and check invoice",["t001"]),step("S2","Second approval above 5,000",["t003",MIXED]),step("S3","Archive the approved invoice",[ALONE])],
      connections:[{from:"S1",to:"S2",label:"Above limit",evidence_turns:["t003"]},{from:"S2",to:"S3",label:"",evidence_turns:[ALONE]},{from:"S1",to:"S3",label:"Below limit",evidence_turns:["t001"]}],open_questions:[]},
    memo_findings:[{key:"trigger",status:"partial",answer:"A supplier invoice arrives by email.",evidence_turns:["t001"]},
      {key:"checks",status:"partial",answer:"A second approval applies above 5,000.",evidence_turns:["t003",MIXED]},
      {key:"rules",status:"partial",answer:"Approved invoices are kept for seven years.",evidence_turns:[ALONE]}],
    taxonomy:[{facet:"control",value:"second approval",note:"From the policy.",evidence_turns:[MIXED,"t003"]}],connections_out:[],
    coverage:[],summary:"Invoice approval so far.",focus:"",parking_lot:[],closure:{asked:false,confirmed:false},
    draft:{title:"Invoice approval",steps:[step("D1","Second approval above 5,000",["t003",MIXED]),step("D2","Archive the approved invoice",[ALONE])],connections:[{from:"D1",to:"D2",label:"",evidence_turns:[ALONE]}]},
    draft_stale:false,draft_edited:false,synthetic_example:false,unsent_answer:""};
}
// Every document excerpt ID anywhere in an outgoing body, wherever it is cited.
function citedDocuments(value,found=new Set()){
  if(Array.isArray(value))value.forEach(item=>citedDocuments(item,found));
  else if(value&&typeof value==="object")for(const [key,item] of Object.entries(value)){
    if(["evidence_turns","document_source_ids"].includes(key)&&Array.isArray(item))item.filter(id=>typeof id==="string"&&id.startsWith("doc_")).forEach(id=>found.add(id));
    else citedDocuments(item,found);
  }
  return found;
}
// What server.py answers when the request names no file scope it knows: a citation of a file excerpt
// cannot be resolved, a step or route needs evidence, a reported note needs evidence.
function captureRefusal(body,known=new Set()){
  const sources=new Set(["context",...known,...body.turns.filter(turn=>turn.role==="user"&&!turn.document_event).map(turn=>turn.id)]);
  const prior=body.previous_capture;if(!prior)return null;
  for(const item of [...prior.workflow.steps,...prior.workflow.connections])
    if(!item.evidence_turns.length||!item.evidence_turns.every(id=>sources.has(id)))return "The working map cites missing or non-participant evidence.";
  const ids=new Set(prior.workflow.steps.map(item=>item.id));
  if(prior.workflow.connections.some(edge=>!ids.has(edge.from)||!ids.has(edge.to)))return "A working map connection references a missing step.";
  for(const finding of prior.memo_findings){
    if(!finding.evidence_turns.every(id=>sources.has(id)))return "A memo finding references missing or non-participant evidence without an authorized document source.";
    if(["captured","partial","not_applicable"].includes(finding.status)&&!finding.evidence_turns.length)return "A reported memo finding must identify its interview evidence.";
  }
  return null;
}
const json=(status,value)=>({ok:status<400,status,json:async()=>value});
const receipt=revision=>({submission_id:"00000000-0000-4000-8000-000000000001",process_id:"00000000-0000-4000-8000-000000000002",revision,job_id:"00000000-0000-4000-8000-00000000001"+revision,status:"pending",status_token:"a".repeat(64)});

function setup({scopeKnown=false}={}){
  const document={activeElement:null},nodes=new Map(),timers=new Map(),calls=[],notices=[];let serial=0;
  document.body=new Element("body",document);
  document.createElement=tag=>new Element(tag,document);document.createElementNS=(_,tag)=>new Element(tag,document);
  document.getElementById=id=>{if(!nodes.has(id)){const node=new Element("div",document);node.id=id;node.page=true;nodes.set(id,node);}return nodes.get(id);};
  document.querySelectorAll=()=>[];document.querySelector=()=>null;document.addEventListener=()=>{};
  const setTimeout=(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout=id=>timers.delete(id);
  const window={document,speechSynthesis:{cancel(){}},SpeechSynthesisUtterance:class{},addEventListener(){},removeEventListener(){},setTimeout,clearTimeout,__notices:notices};
  // The stand-in server. A workspace it does not know is refused the way server.py refuses it.
  const server={workflowReply:null,submissions:0};
  const route=(url,body)=>{
    if(url==="/api/documents/status")return scopeKnown&&body.scope===OLD_SCOPE?json(200,{documents:savedInterview().documents.documents,removed:[]}):json(403,UNAVAILABLE);
    if(url==="/api/workflow"||url==="/api/interview"){
      if(body.document_scope&&!(scopeKnown&&body.document_scope===OLD_SCOPE))return json(403,{error:"The document reference is not available in this interview. Reopen the saved interview or upload the file again."});
      const refused=captureRefusal(body,scopeKnown?new Set([MIXED,ALONE]):new Set());
      if(refused)return json(400,{error:refused});
      return json(200,url==="/api/workflow"?server.workflowReply:{question:"What happens after the second approval?",summary:"Invoice approval so far.",focus:"",parking_lot:[],coverage:[],
        memo_findings:[{key:"trigger",status:"partial",answer:"A supplier invoice arrives by email.",evidence_turns:["t001"]}]});
    }
    if(url==="/api/knowledge/submit"){
      if(body.documents?.documents?.length&&!scopeKnown)return json(403,{error:"Knowledge operation is not authorized."});
      const unresolved=[...citedDocuments(body)].filter(()=>!scopeKnown);
      if(unresolved.length)return json(400,{code:"document_citations_unavailable",error:"These parts cite a file that is not among this interview’s files on this computer: working map step S2. You can submit without these citations.",
        citations:[{document_id:"",name:"",state:"unavailable",source_ids:unresolved,cited_by:["working map step S2"],more:0}]});
      return json(202,receipt(++server.submissions));
    }
    throw Error("Unexpected request "+url);
  };
  let uuid=0;
  const context={window,document,console,Blob,Date,JSON,TextEncoder,AbortController,DOMException,confirm:()=>true,setTimeout,clearTimeout,
    requestAnimationFrame:()=>++serial,cancelAnimationFrame(){},
    crypto:{randomUUID:()=>`eeeeeeee-eeee-4eee-8eee-${String(++uuid).padStart(12,"0")}`},
    fetch:async(url,options)=>{const body=typeof options?.body==="string"?JSON.parse(options.body):null;calls.push({url,body});return route(url,body);}};
  // The two controllers are created with the callbacks init() gives them; rendering of the page itself is left out.
  const seam=`
    renderTranscript=()=>{};renderDraft=()=>{};renderWorkingMap=()=>{};renderCoverage=()=>{};renderReport=()=>{};scrollConversation=()=>{};
    updateConversationControls=()=>{};updateDocumentIntakeUI=()=>{};stopSpeaking=()=>{};tab=()=>{};
    selectConversationView=view=>{conversationUI.view=view;};
    notice=(message,error)=>window.__notices.push({message,error:Boolean(error)});
    documentController=window.CollectorDocuments.create({requestJSON:request,getContext:documentContext,config:()=>state.config,canUpload:()=>!state.importing,
      onOpen(){},onCountChange(){},onEvent:onDocumentEvent,notice,onDirty:()=>{state.dirty=true;}});
    knowledgeUI=window.CollectorKnowledge.create({request,session:sessionObject,captureState:submissionCaptureState,draftStaleReason,notice,onSubmitted:()=>{state.dirty=true;}});
    window.__switch={state,conversationUI,importSession,refreshWorkflow,sendAnswer,sessionObject,snapshot,sourceCaption,documents:()=>documentController,knowledge:()=>knowledgeUI};
  })();`;
  const source=appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam);
  assert.notEqual(source,appSource,"Install the test seam only at application initialization");
  vm.createContext(context);
  vm.runInContext(documentsSource,context,{filename:"documents.js"});vm.runInContext(knowledgeSource,context,{filename:"knowledge-ui.js"});vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__switch;t.state.config={api_configured:true,csrf_token:"synthetic"};
  const node=id=>document.getElementById(id);
  const open=async saved=>{const text=JSON.stringify(saved);await t.importSession({size:text.length,text:async()=>text});await flush();};
  const dialog=node("knowledge-submit");
  const find=(root,test)=>walk(root).find(test);
  const h={t,node,calls,notices,server,timers,open,dialog,
    sent:url=>calls.filter(call=>call.url===url).map(call=>call.body),
    button:(root,label)=>find(root,item=>item.tagName==="BUTTON"&&item.textContent===label),
    switchWorkspace:async()=>{const button=h.button(t.documents().body,"Start new file workspace");assert.ok(button,"Assets must offer Start new file workspace");await button.click();await flush();},
    answer:async text=>{node("answer-text").value=text;await t.sendAnswer({preventDefault(){}});await flush();},
    submit:async()=>{t.knowledge().openSubmit();const form=find(dialog,item=>item.tagName==="FORM");assert.ok(form,"The Submit dialog must open: "+JSON.stringify(notices.at(-1)));await form.dispatch("submit");await flush();},
    statusLines:()=>walk(dialog).filter(item=>item.className==="knowledge-status"&&!item.hidden&&item._text).map(item=>item._text)};
  return h;
}
const mapReply=(extra={})=>({workflow:{title:"Invoice approval",steps:[step("S1","Receive and check invoice",["t001"]),step("S2","Second approval above 5,000",["t003"])],
  connections:[{from:"S1",to:"S2",label:"Above limit",evidence_turns:["t003"]}],open_questions:[]},
  memo_findings:[{key:"trigger",status:"partial",answer:"A supplier invoice arrives by email.",evidence_turns:["t001"]},{key:"checks",status:"partial",answer:"A second approval applies above 5,000.",evidence_turns:["t003"]}],
  coverage:[],summary:"Invoice approval so far.",focus:"",parking_lot:[],...extra});

// WORKSPACE_SWITCH_ALL=1 runs every check and lists each failure (to see what a change breaks); the default stops at the first.
let passed=0;const failures=[];
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;if(!process.env.WORKSPACE_SWITCH_ALL)throw error;failures.push(error.message.split("\n")[0]);}}

(async()=>{
await check("the moved interview opens with its references and offers a new file workspace",async()=>{
  const h=setup();await h.open(savedInterview());
  assert.equal(h.t.state.turns.length,3);assert.equal(h.t.documents().scopeUnavailable,true);
  assert.match(h.t.documents().body.textContent,/saved file workspace is unavailable on this computer/);
  const offer=h.t.documents().body.textContent;
  assert.match(offer,/start a new file workspace/i);
  assert.doesNotMatch(offer,/Your saved references stay with the interview\./,"The offer must say what happens to the saved references, not only that they stay");
  assert.match(offer,/not sent|left out/i,"Before the switch the participant is told that the saved excerpts will not be used in updates or submissions");
});

await check("starting a new file workspace keeps the excerpts as marked references",async()=>{
  const h=setup();await h.open(savedInterview());h.notices.length=0;await h.switchWorkspace();
  const state=h.t.documents().exportState(true);
  assert.equal(state.scope,null);assert.deepEqual(plain(state.documents),[]);assert.equal(state.unavailable_workspaces[0].scope,OLD_SCOPE);
  const evidence=plain(h.t.state.documentEvidence);
  assert.deepEqual(evidence.map(source=>source.id),[MIXED,ALONE],"The saved excerpts stay with the interview");
  assert.ok(evidence.every(source=>source.workspace_unavailable===true&&source.retained_only===true),"Each one is marked as a reference this computer cannot read");
  assert.equal(evidence[0].text,"Invoices above 5,000 need a second approval by the finance manager.");
  // The interview itself keeps its citations; the note is on each of them.
  assert.deepEqual(plain(h.t.conversationUI.workflow.steps[1].evidence_turns),["t003",MIXED]);
  assert.deepEqual(plain(h.t.state.memo_findings.find(item=>item.key==="rules").evidence_turns),[ALONE]);
  for(const id of [MIXED,ALONE])assert.match(h.t.sourceCaption(id),/Approval policy\.pdf.*not on this computer/,"Every citation of such an excerpt says where it stands");
  assert.doesNotMatch(h.t.sourceCaption("t003"),/not on this computer/);
  const told=h.notices.map(item=>item.message).join(" ");
  assert.match(told,/2 saved excerpts/);assert.match(told,/not on this computer|cannot read/);
  assert.match(told,/1 step and 1 note rest only on/,"The participant is told which parts will not be carried into the next update");
  assert.equal(h.t.state.dirty,true);
});

await check("after the switch the working map updates again and no request names an excerpt of the old workspace",async()=>{
  const h=setup();await h.open(savedInterview());await h.switchWorkspace();
  h.server.workflowReply=mapReply();
  const updated=await h.t.refreshWorkflow();await flush();
  const sent=h.sent("/api/workflow");
  assert.equal(sent.length,1);
  assert.equal(updated,true,"The map update must be accepted: "+h.node("workflow-status").textContent);
  const body=sent[0];
  assert.equal(body.document_scope,undefined);assert.deepEqual(body.document_source_ids,[]);
  assert.deepEqual([...citedDocuments(body)],[],"No excerpt of the unavailable workspace is cited in the request");
  assert.equal(JSON.stringify(body).includes("second approval by the finance manager"),false,"The browser never sends the text of a saved excerpt");
  const prior=body.previous_capture;
  assert.deepEqual(prior.workflow.steps.map(item=>[item.id,item.evidence_turns]),[["S1",["t001"]],["S2",["t003"]]],"A step that also rests on an answer goes on with that answer; one that rests on the old file alone is held back");
  assert.deepEqual(prior.workflow.connections.map(edge=>[edge.from,edge.to,edge.evidence_turns]),[["S1","S2",["t003"]]],"Routes into a held-back step, and routes that rest on the old file alone, are held back with it");
  const notes=Object.fromEntries(prior.memo_findings.map(item=>[item.key,item]));
  assert.deepEqual(notes.checks.evidence_turns,["t003"]);assert.equal(notes.checks.status,"partial");assert.equal(notes.checks.answer,"A second approval applies above 5,000.");
  assert.equal(notes.rules.status,"unknown","A note that rests on the old file alone is not sent as a reported note");assert.deepEqual(notes.rules.evidence_turns,[]);
  assert.doesNotMatch(notes.rules.answer,/seven years/);
  assert.equal(prior.memo_findings.length,16);
  assert.deepEqual(plain(h.t.conversationUI.workflow.steps.map(item=>item.id)),["S1","S2"],"The reply is applied");
  assert.equal(h.node("workflow-status").textContent,"Up to date");
  // The excerpts are still with the interview, and the saved copy keeps them marked.
  const saved=plain(h.t.sessionObject({includePresentation:true}));
  assert.deepEqual(saved.document_evidence.map(source=>[source.id,source.workspace_unavailable]),[[MIXED,true],[ALONE,true]]);
  assert.equal(saved.documents.unavailable_workspaces[0].documents[0].name,"Approval policy.pdf");
});

await check("after the switch an answer is taken and its request names no excerpt of the old workspace",async()=>{
  const h=setup();await h.open(savedInterview());await h.switchWorkspace();h.server.workflowReply=mapReply();
  await h.answer("Then the payment run picks it up.");
  const sent=h.sent("/api/interview");
  assert.equal(sent.length,1);assert.equal(sent[0].document_scope,undefined);assert.deepEqual(sent[0].document_source_ids,[]);
  assert.equal(h.t.state.turns.at(-1).text,"What happens after the second approval?");
  assert.deepEqual(plain(h.t.snapshot().document_source_ids),[]);
});

await check("after the switch Submit process files the interview without the citations this computer cannot check",async()=>{
  const h=setup();await h.open(savedInterview());await h.switchWorkspace();
  h.t.knowledge().openSubmit();
  const before=h.statusLines().join(" ");
  assert.match(before,/Approval policy\.pdf/,"The dialog names the file before the submitter confirms");
  assert.match(before,/not on this computer/);assert.match(before,/left out of this submission/);
  assert.doesNotMatch(before,/stores those passages in company knowledge/,"Nothing is stored from a file this computer cannot read");
  await h.submit();
  const sent=h.sent("/api/knowledge/submit");
  assert.equal(sent.length,1,"One request files it; no refusal and second attempt is needed");
  const body=sent[0];
  assert.deepEqual([...citedDocuments(body)],[]);
  assert.equal(body.document_evidence,undefined,"The browser's cached excerpts are never submitted");
  assert.equal(JSON.stringify(body).includes("second approval by the finance manager"),false);
  assert.deepEqual(body.documents,{scope:null,documents:[]});
  assert.deepEqual(body.workflow.steps.map(item=>[item.id,item.evidence_turns]),[["S1",["t001"]],["S2",["t003"]],["S3",[]]],"The steps are filed; only the citations are left out");
  assert.deepEqual(body.draft.steps.map(item=>item.evidence_turns),[["t003"],[]]);
  assert.deepEqual(body.taxonomy[0].evidence_turns,["t003"]);
  assert.match(h.dialog.textContent,/Process submitted/);
  assert.match(h.dialog.textContent,/9 file citations were left out of this revision\. Your interview keeps them\./);
  // The interview itself is unchanged by submitting.
  assert.deepEqual(plain(h.t.conversationUI.workflow.steps[2].evidence_turns),[ALONE]);
});

await check("a copy saved after the switch reopens with its references still marked, also one saved before this rule existed",async()=>{
  const h=setup();await h.open(savedInterview());await h.switchWorkspace();
  const copy=plain(h.t.sessionObject({includePresentation:true}));
  const again=setup();await again.open(copy);
  assert.ok(plain(again.t.state.documentEvidence).every(source=>source.workspace_unavailable===true&&source.retained_only===true));
  assert.equal(again.t.documents().scopeUnavailable,false,"The new workspace has no files yet, so nothing is asked of the server");
  again.server.workflowReply=mapReply();
  assert.equal(await again.t.refreshWorkflow(),true);
  assert.deepEqual([...citedDocuments(again.sent("/api/workflow")[0])],[]);
  // A copy written after a switch by a build that did not mark the excerpts: the file list of the
  // replaced workspace says which excerpts this computer cannot read.
  const legacy=plain(copy);for(const source of legacy.document_evidence){delete source.workspace_unavailable;source.retained_only=false;}
  const old=setup();await old.open(legacy);
  assert.ok(plain(old.t.state.documentEvidence).every(source=>source.workspace_unavailable===true&&source.retained_only===true));
  old.server.workflowReply=mapReply();
  assert.equal(await old.t.refreshWorkflow(),true);
});

await check("excerpts read in the new workspace are cited as usual beside the marked references",async()=>{
  const h=setup();await h.open(savedInterview());await h.switchWorkspace();
  const NEW="doc_fedcba9876543210",FRESH=NEW+"_p1_c1";
  h.server.workflowReply=mapReply({document_evidence:[{id:FRESH,document_id:NEW,name:"Approval policy.pdf",label:"Page 1",text:"Invoices above 5,000 need a second approval."}]});
  h.server.workflowReply.workflow.steps[1].evidence_turns=["t003",FRESH];
  assert.equal(await h.t.refreshWorkflow(),true);
  const evidence=Object.fromEntries(plain(h.t.state.documentEvidence).map(source=>[source.id,source]));
  assert.equal(evidence[FRESH].workspace_unavailable,undefined);assert.equal(evidence[FRESH].retained_only,false);
  assert.equal(evidence[MIXED].workspace_unavailable,true);
  assert.deepEqual(plain(h.t.snapshot().document_source_ids),[FRESH],"Only what this computer can read is named in later requests");
  assert.doesNotMatch(h.t.sourceCaption(FRESH),/not on this computer/);
});

await check("on the computer that has the workspace nothing is marked, held back or left out",async()=>{
  const h=setup({scopeKnown:true});await h.open(savedInterview());
  assert.equal(h.t.documents().scopeUnavailable,false);assert.equal(h.button(h.t.documents().body,"Start new file workspace"),undefined);
  assert.ok(plain(h.t.state.documentEvidence).every(source=>source.workspace_unavailable===undefined&&source.retained_only===false));
  assert.doesNotMatch(h.t.sourceCaption(MIXED),/not on this computer/);
  h.server.workflowReply=mapReply();
  assert.equal(await h.t.refreshWorkflow(),true);
  const body=h.sent("/api/workflow")[0];
  assert.equal(body.document_scope,OLD_SCOPE);assert.deepEqual([...body.document_source_ids].sort(),[MIXED,ALONE].sort());
  assert.deepEqual(body.previous_capture.workflow.steps.map(item=>item.evidence_turns),[["t001"],["t003",MIXED],[ALONE]]);
  assert.equal(body.previous_capture.memo_findings.find(item=>item.key==="rules").status,"partial");
  const fresh=setup({scopeKnown:true});await fresh.open(savedInterview());await fresh.submit();
  const filed=fresh.sent("/api/knowledge/submit")[0];
  assert.deepEqual([...citedDocuments(filed)].sort(),[MIXED,ALONE].sort(),"Citations of files in use are submitted for the server to resolve");
  assert.doesNotMatch(fresh.dialog.textContent,/left out/);
});

if(failures.length){console.error(failures.join("\n"));process.exitCode=1;}
console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
