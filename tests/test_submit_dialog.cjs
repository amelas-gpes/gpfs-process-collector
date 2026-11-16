"use strict";
// What the Submit process dialog tells the submitter, checked against the real
// web/knowledge-ui.js behind a synthetic DOM. No browser, provider or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"..","web","knowledge-ui.js"),"utf8");
const all=root=>[root,...root.children.flatMap(all)],find=(root,test)=>all(root).find(test);
class E{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.dataset={};this.style={};this.hidden=false;this.open=false;this.value="";this._text="";this.disabled=false;this.checked=false;}
  append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this._text="";this.append(...children);}
  set textContent(value){this.writes=(this.writes||0)+1;this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join("");}
  setAttribute(key,value){this.attributes[key]=String(value);}
  addEventListener(key,fn){(this.listeners[key]??=[]).push(fn);}
  async dispatch(key){for(const fn of this.listeners[key]||[])await fn({preventDefault(){},target:this});}
  querySelectorAll(){return[];}querySelector(){return null;}
  showModal(){this.open=true;}close(){this.open=false;}focus(){this.focused=true;}
}
const settle=async()=>{for(let i=0;i<3;i++)await new Promise(resolve=>setImmediate(resolve));};
const uuid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const receipt=(revision=1)=>({submission_id:uuid(1),process_id:uuid(2),revision,job_id:uuid(10+revision),status:"pending",status_token:"a".repeat(64)});
const draft=()=>({title:"Invoice intake",steps:[{id:"S1",title:"REVIEWER CORRECTED TITLE",evidence_turns:["u1"]}],connections:[]});
const workflow=()=>({title:"Invoice intake",steps:[{id:"S1",title:"Receive and register invoice",evidence_turns:["u1"]}],connections:[]});
const complete=turn=>({in_progress:false,notes_current:true,map_current:true,notes_through_turn:turn,map_through_turn:turn});
const WAITING="Notes and the working map are still updating for your latest answer.";
const MISSING=["Notes include 5 of 6 answers.","The working map includes 5 of 6 answers."];

function setup(session={}){
  const nodes={};for(const id of ["knowledge-submit","submit-process-menu","submit-process-review","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  const calls=[],notices=[],timers=new Map();let keys=0,timerId=0;
  const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,
    setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},clearTimeout:id=>timers.delete(id),
    crypto:{randomUUID:()=>`eeeeeeee-eeee-4eee-8eee-${String(++keys).padStart(12,"0")}`}};
  vm.runInNewContext(source,env,{filename:"knowledge-ui.js"});
  const state={saved_at:"2026-11-13T00:00:00.000Z",context:{process_name:"Invoice intake"},turns:[{id:"u1",role:"user",text:"A supplier email starts a case."}],
    documents:null,workflow:workflow(),draft:null,draft_stale:false,draft_edited:false,capture:complete("u1"),...session};
  // What app.js reports through options.captureState(); tests change it to play the capture catching up.
  // reason: what app.js reports through options.draftStaleReason() for a draft that is out of date.
  // workspace: what app.js reports through options.fileWorkspace() about the current file workspace.
  const h={nodes,calls,notices,state,timers,gate:{waiting:"",missing:[]},gateReads:0,reason:"answers",workspace:{unavailable:false,removed:[]},respond:async()=>receipt(calls.length)};
  h.controller=env.window.CollectorKnowledge.create({session:()=>structuredClone(h.state),notice:(message,error)=>notices.push({message,error:Boolean(error)}),
    captureState:()=>{h.gateReads++;return structuredClone(h.gate);},draftStaleReason:()=>h.reason,fileWorkspace:()=>structuredClone(h.workspace),
    request:async(pathName,payload)=>{calls.push({path:pathName,payload:structuredClone(payload)});return h.respond(pathName,payload);}});
  h.send=()=>find(h.dialog,node=>node.tagName==="BUTTON"&&node.type==="submit");
  h.runTimers=()=>{const due=[...timers.values()];timers.clear();for(const timer of due)timer.fn();};
  h.dialog=nodes["knowledge-submit"];
  h.open=()=>{h.controller.openSubmit();return h.dialog;};
  h.form=()=>find(h.dialog,node=>node.tagName==="FORM");
  h.text=()=>h.dialog.textContent;
  h.statusLines=()=>all(h.dialog).filter(node=>node.className==="knowledge-status"&&!node.hidden&&node._text).map(node=>node._text);
  h.submit=async()=>{await h.form().dispatch("submit");await settle();};
  return h;
}

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
await check("a current draft, or no draft, carries no stale-draft warning",async()=>{
  for(const session of [{},{draft:draft()},{draft:draft(),draft_edited:true},{draft:null,draft_stale:true}]){
    const h=setup(session);h.open();
    assert.equal(h.dialog.open,true);assert.doesNotMatch(h.text(),/predates/i,JSON.stringify(session));
  }
});

await check("an edited draft that predates newer answers is named as the source of the graph",async()=>{
  const h=setup({draft:draft(),draft_stale:true,draft_edited:true});h.open();
  const line=h.statusLines().find(text=>/predates newer interview answers/.test(text));
  assert.ok(line,"The dialog must warn that the draft predates newer answers");
  assert.match(line,/graph[^.]*will be built from your edited draft/i);
  assert.match(line,/will not reflect those answers/i);assert.match(line,/full current interview is stored/i);
  assert.doesNotMatch(line,/working map/i);
});

await check("an unedited draft that predates newer answers is not said to be the source of the graph",async()=>{
  const h=setup({draft:draft(),draft_stale:true,draft_edited:false});h.open();
  const line=h.statusLines().find(text=>/predates newer interview answers/.test(text));
  assert.ok(line,"The dialog must warn that the draft predates newer answers");
  assert.match(line,/graph[^.]*will be built from the working map, not from the draft/i);
  assert.match(line,/draft and the full current interview are stored/i);
  assert.doesNotMatch(h.text(),/will include that stale draft/i,"The dialog must not claim the stale draft is what the graph contains");
});

await check("an unedited stale draft is still the source when the working map has no steps",async()=>{
  for(const map of [null,{title:"Invoice intake",steps:[],connections:[]}]){
    const h=setup({draft:draft(),draft_stale:true,draft_edited:false,workflow:map});h.open();
    const line=h.statusLines().find(text=>/predates newer interview answers/.test(text));
    assert.ok(line,"The dialog must warn that the draft predates newer answers");
    assert.match(line,/graph[^.]*will be built from your draft, because the working map has no steps/i);
    assert.match(line,/will not reflect those answers/i);
    assert.doesNotMatch(line,/edited draft|not from the draft/i);
  }
});

await check("the stale-draft flags reach the server unchanged so it can apply the same rule",async()=>{
  const h=setup({draft:draft(),draft_stale:true,draft_edited:true});h.open();await h.submit();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].path,"/api/knowledge/submit");
  const sent=h.calls[0].payload;
  assert.equal(sent.draft_stale,true);assert.equal(sent.draft_edited,true);
  assert.equal(sent.draft.steps[0].title,"REVIEWER CORRECTED TITLE");assert.equal(sent.workflow.steps[0].title,"Receive and register invoice");
  assert.match(h.text(),/Process submitted/);
});

// Repair round 1: draft_stale is also set when only the files in use changed, and when a reopened file
// merely carried the flag. The dialog may claim newer answers only when the page saw them.
await check("the stale-draft notice claims only what the page saw",async()=>{
  const lineFor=(reason,session)=>{const h=setup({draft:draft(),draft_stale:true,...session});h.reason=reason;h.open();return h.statusLines().find(text=>/process graph/.test(text));};
  // The false-flag case of gap-uncommitted-diff-2: a reopened file, no new answer, no working map.
  const saved=lineFor("saved",{draft_edited:false,workflow:null});
  assert.match(saved,/^Your draft was saved as out of date\. /);assert.doesNotMatch(saved,/predates|newer|those answers/i);
  assert.match(saved,/built from your draft, because the working map has no steps; it may not reflect your latest answers or files\./);
  assert.match(saved,/If the draft is up to date, mark it as current in Review\.$/);
  const savedBesideMap=lineFor("saved",{draft_edited:false});
  assert.match(savedBesideMap,/built from the working map, not from the draft/);assert.doesNotMatch(savedBesideMap,/predates|newer/i);
  assert.match(savedBesideMap,/Update the draft first, or mark it as current in Review, if the graph should match it\.$/);
  const files=lineFor("files",{draft_edited:true});
  assert.match(files,/^The files in use changed after your draft was created\. /);
  assert.match(files,/built from your edited draft, so it will not reflect that change\./);assert.doesNotMatch(files,/answers|mark it as current/i);
  const answers=lineFor("answers",{draft_edited:true});
  assert.match(answers,/^Your draft predates newer interview answers\. /);assert.match(answers,/will not reflect those answers\./);
  for(const reason of ["",undefined,"changed",7]){
    const line=lineFor(reason,{draft_edited:true});
    assert.match(line,/^Your draft is marked out of date\. /,"Without a known reason the notice stays neutral: "+String(reason));
    assert.match(line,/may not reflect your latest answers or files\./);assert.doesNotMatch(line,/predates/);
  }
});

// gap3-submit-in-flight-1: the snapshot must not be filed while notes and the working map are still catching up.
await check("Submit waits while capture work is running and opens again when it settles",async()=>{
  const h=setup();h.gate.waiting=WAITING;h.open();
  assert.equal(h.send().disabled,true,"Submit is unavailable while the latest answer is still being captured");
  assert.ok(h.statusLines().some(line=>line===WAITING+" Submit is available when this finishes."),h.statusLines().join(" | "));
  await h.submit();
  assert.equal(h.calls.length,0,"Nothing is sent while the button is disabled");
  h.gate.waiting="";h.controller.captureChanged();
  assert.equal(h.send().disabled,false,"The button is re-enabled from the page's status callback");
  assert.equal(h.send().textContent,"Submit process");assert.equal(h.statusLines().some(line=>/Submit is available/.test(line)),false);
  await h.submit();
  assert.equal(h.calls.length,1);assert.deepEqual(h.calls[0].payload.capture,complete("u1"),"The capture marker is stored with every submission");
  assert.match(h.text(),/Process submitted/);assert.doesNotMatch(h.text(),/filed before the notes/);
});

await check("a waiting dialog writes its status line and its button only when they change",async()=>{
  // The line is a live region and the gate is re-applied about three times a second while it waits.
  const h=setup();h.gate.waiting=WAITING;h.open();
  const line=all(h.dialog).find(node=>node.className==="knowledge-status"&&node._text.startsWith(WAITING)),send=h.send();
  assert.equal(line.attributes.role,"status");
  const before=[line.writes,send.writes];
  for(let i=0;i<5;i++){h.controller.captureChanged();h.runTimers();}
  assert.deepEqual([line.writes,send.writes],before,"An unchanged sentence must not be written again, or a screen reader repeats it");
  assert.equal(send.disabled,true);assert.equal(h.timers.size,1,"The safety-net timer still runs");
  h.gate.waiting="Your files are still being read.";h.controller.captureChanged();h.controller.captureChanged();
  assert.equal(line._text,"Your files are still being read. Submit is available when this finishes.");
  assert.deepEqual([line.writes,send.writes],[before[0]+1,before[1]],"A new reason is written once; the button label did not change");
  h.gate.waiting="";h.gate.missing=[MISSING[0]];h.controller.captureChanged();h.controller.captureChanged();
  assert.equal(send.textContent,"Submit anyway");assert.equal(send.disabled,false);
  assert.deepEqual([line.writes,send.writes],[before[0]+2,before[1]+1]);
  h.gate.missing=[];h.controller.captureChanged();h.controller.captureChanged();
  assert.equal(line.hidden,true);assert.equal(line._text,"");assert.equal(send.textContent,"Submit process");
  assert.deepEqual([line.writes,send.writes],[before[0]+3,before[1]+2]);
});

await check("voice or a recording says what to do instead of promising that it finishes",async()=>{
  const h=setup();h.open();h.gate.waiting="Voice is still on.";h.gate.action="Close this window and choose Stop talking, then submit.";h.controller.captureChanged();
  assert.equal(h.send().disabled,true);
  assert.ok(h.statusLines().includes("Voice is still on. Close this window and choose Stop talking, then submit."),h.statusLines().join(" | "));
  assert.equal(h.statusLines().some(line=>/available when this finishes/.test(line)),false,"Voice does not finish by itself");
  h.gate.waiting=WAITING;h.gate.action="";h.controller.captureChanged();
  assert.ok(h.statusLines().includes(WAITING+" Submit is available when this finishes."),"Work that ends by itself is still waited for");
});

await check("the gate is checked again when the snapshot is taken",async()=>{
  const h=setup();h.open();
  assert.equal(h.send().disabled,false);assert.equal(h.send().textContent,"Submit process");
  h.gate.waiting=WAITING;                       // a new answer starts its capture; no notification reaches the dialog
  await h.submit();
  assert.equal(h.calls.length,0,"The form handler, where the payload is read, must gate as well");
  assert.equal(h.send().disabled,true);assert.ok(h.statusLines().some(line=>line.startsWith(WAITING)));
  assert.equal(h.controller.hasPending,false);
});

await check("a missed notification cannot leave Submit disabled",async()=>{
  const h=setup();h.gate.waiting=WAITING;h.open();
  assert.equal(h.send().disabled,true);assert.equal(h.timers.size,1,"A waiting dialog re-checks on a timer");
  h.gate.waiting="";h.runTimers();
  assert.equal(h.send().disabled,false);assert.equal(h.timers.size,0,"The timer stops once nothing is running");
  const waiting=setup();waiting.gate.waiting=WAITING;waiting.open();waiting.dialog.close();
  const reads=waiting.gateReads;waiting.runTimers();waiting.runTimers();
  assert.ok(waiting.gateReads<=reads+1,"A closed dialog stops polling");assert.equal(waiting.timers.size,0);
});

await check("a capture that stopped short needs an explicit Submit anyway that says what is missing",async()=>{
  const h=setup({turns:Array.from({length:6},(_,i)=>({id:"u"+(i+1),role:"user",text:"Answer "+(i+1)})),
    capture:{in_progress:false,notes_current:false,map_current:false,notes_through_turn:"u5",map_through_turn:"u5"}});
  h.gate.missing=MISSING;h.open();
  assert.equal(h.send().disabled,false,"A settled gap must not block forever");
  assert.equal(h.send().textContent,"Submit anyway");
  const line=h.statusLines().find(text=>/filed incomplete/.test(text));
  assert.ok(line);for(const sentence of MISSING)assert.ok(line.includes(sentence),"The dialog names what is missing: "+sentence);
  assert.match(line,/full transcript is stored/i);
  await h.submit();
  assert.equal(h.calls.length,1);
  assert.deepEqual(h.calls[0].payload.capture,{in_progress:false,notes_current:false,map_current:false,notes_through_turn:"u5",map_through_turn:"u5"});
  assert.equal(h.calls[0].payload.turns.length,6);
  assert.match(h.text(),/Process submitted/);
  assert.match(h.text(),/filed before the notes and working map had caught up/i,"The confirmation must not read as a complete filing");
  h.dialog.close();h.gate.missing=[];h.state.capture=complete("u6");h.open();
  assert.match(h.text(),/Revision 1 was filed before the notes and working map had caught up\. Submit again/);
});

await check("Submit anyway covers only the gap the submitter was shown",async()=>{
  const h=setup();h.open();
  h.gate.missing=[MISSING[0]];                  // the capture fails after the dialog opened
  await h.submit();
  assert.equal(h.calls.length,0,"A gap that appeared since the button was drawn is shown first");
  assert.equal(h.send().textContent,"Submit anyway");assert.ok(h.statusLines().some(line=>line.includes(MISSING[0])));
  h.gate.missing=MISSING;
  await h.submit();
  assert.equal(h.calls.length,0,"A larger gap is shown again before it is accepted");
  assert.ok(h.statusLines().some(line=>line.includes(MISSING[1])));
  await h.submit();
  assert.equal(h.calls.length,1);
  const caughtUp=setup();caughtUp.gate.missing=MISSING;caughtUp.open();caughtUp.gate.missing=[];
  await caughtUp.submit();
  assert.equal(caughtUp.calls.length,1,"A gap that closed needs no second confirmation");
});

await check("recovering an uncertain submission is not gated and keeps its own snapshot",async()=>{
  const h=setup();h.open();
  h.respond=async()=>{throw Object.assign(Error("Connection lost"),{status:0});};
  await h.submit();
  assert.equal(h.controller.hasPending,true);assert.equal(h.send().textContent,"Recover previous submission");
  h.gate.waiting=WAITING;h.controller.captureChanged();
  assert.equal(h.send().disabled,false,"Recovery of the captured snapshot stays available");
  assert.equal(h.send().textContent,"Recover previous submission");
  h.respond=async()=>receipt(1);
  await h.submit();
  assert.equal(h.calls.length,2);assert.deepEqual(h.calls[1].payload,h.calls[0].payload);
  assert.match(h.text(),/Process submitted/);
});

await check("a rejected submission returns to the gate",async()=>{
  const h=setup();h.open();
  h.respond=async()=>{throw Object.assign(Error("Revisions require a verified owner or administrator."),{status:403});};
  h.gate.missing=[];await h.submit();
  assert.equal(h.controller.hasPending,false);
  h.gate.waiting=WAITING;h.controller.captureChanged();
  assert.equal(h.send().disabled,true,"After a rejection the ordinary gate applies again");
});

await check("a reopened dialog says when the filed revision lacks newer answers",async()=>{
  const h=setup();h.open();await h.submit();
  assert.match(h.text(),/Process submitted/);h.dialog.close();
  h.state.turns.push({id:"a2",role:"assistant",text:"Anything else?"},{id:"u2",role:"user",text:"Yes, Treasury confirms the cut-off."},{id:"u3",role:"user",text:"And the controller signs."});
  h.state.capture=complete("u3");h.open();
  assert.match(h.text(),/Revision 1 does not include 2 newer answers\. Submit again/);
  await h.submit();h.dialog.close();h.open();
  assert.doesNotMatch(h.text(),/does not include/,"Nothing to report once the current interview is filed");
});

await check("without a capture-state provider the dialog behaves as before",async()=>{
  const nodes={};for(const id of ["knowledge-submit","submit-process-menu","submit-process-review","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,crypto:{randomUUID:()=>uuid(77).replace(/^0{8}/,"eeeeeeee")}};
  vm.runInNewContext(source,env,{filename:"knowledge-ui.js"});
  const sent=[];
  const controller=env.window.CollectorKnowledge.create({session:()=>({turns:[{id:"u1",role:"user",text:"An answer."}],documents:null}),notice(){},request:async(_path,payload)=>{sent.push(payload);return receipt(1);}});
  controller.openSubmit();controller.captureChanged();
  const form=find(nodes["knowledge-submit"],node=>node.tagName==="FORM"),send=find(form,node=>node.tagName==="BUTTON"&&node.type==="submit");
  assert.equal(send.disabled,false);assert.equal(send.textContent,"Submit process");
  await form.dispatch("submit");await settle();
  assert.equal(sent.length,1);assert.equal("capture" in sent[0],false);
});

// gap-knowledge-documents-1: a refusal over file citations names them and offers a way forward.
const CITED=()=>({draft:{title:"Returns intake",steps:[{id:"S1",title:"Check the log",evidence_turns:["doc_a_r1_c1"]},{id:"S2",title:"Raise the credit note",evidence_turns:["doc_a_r1_c1","u1"]}],
    connections:[{from:"S1",to:"S2",evidence_turns:["u1","doc_a_r1_c1"]}]},
  workflow:{title:"Returns intake",steps:[{id:"S1",title:"Check the log",evidence_turns:["doc_a_r1_c1","doc_b_p1_c1"]}],connections:[]},
  memo_findings:[{key:"checks",status:"known",answer:"Each return is checked.",evidence_turns:["doc_a_r1_c1"]}],
  taxonomy:[{facet:"team",value:"Returns",evidence_turns:["doc_b_p1_c1","u1"]}]});
const REMOVED_FILE={document_id:"doc_a",name:"returns-log.csv",state:"removed",source_ids:["doc_a_r1_c1"],cited_by:["draft step S1 “Check the log”","the “Checks, approvals & proof” note"],more:0};
const UNKNOWN_FILE={document_id:"",name:"",state:"unavailable",source_ids:["doc_b_p1_c1"],cited_by:["working map step S1 “Check the log”"],more:0};
const REFUSED="“returns-log.csv” was removed from this interview, and a new process cannot rest on a removed file alone. These parts cite nothing else: draft step S1 “Check the log”. Restore the file under Assets, or submit without these citations.";
const refusal=(citations,message=REFUSED)=>Object.assign(Error(message),{status:400,code:"document_citations_unavailable",citations});
const without=h=>find(h.dialog,node=>node.tagName==="BUTTON"&&node.textContent==="Submit without these citations");
const offered=h=>{const control=without(h);if(!control)return false;for(let node=control;node;node=node.parentElement)if(node.hidden)return false;return true;};

await check("a refusal over file citations is shown as sent and offers Submit without these citations",async()=>{
  const h=setup(CITED());h.open();
  assert.equal(offered(h),false,"Nothing is offered before a refusal");
  h.respond=async()=>{throw refusal([REMOVED_FILE]);};
  await h.submit();
  assert.equal(h.calls.length,1);assert.equal(h.controller.hasPending,false,"The refusal is final for that snapshot");
  assert.ok(h.statusLines().includes(REFUSED),"The server's sentence names the file, the parts and the remedies");
  assert.equal(offered(h),true,"The dialog must offer the way forward that the message names");
  assert.equal(h.send().textContent,"Submit process");assert.equal(h.send().disabled,false);
  h.respond=async()=>receipt(1);
  await without(h).dispatch("click");await settle();
  assert.equal(h.calls.length,2);
  const sent=h.calls[1].payload;
  assert.doesNotMatch(JSON.stringify(sent),/doc_a_r1_c1/,"The named citations are left out of everything that is filed");
  assert.deepEqual(sent.draft.steps.map(step=>step.evidence_turns),[[],["u1"]]);
  assert.deepEqual(sent.draft.connections[0].evidence_turns,["u1"]);
  assert.deepEqual(sent.workflow.steps[0].evidence_turns,["doc_b_p1_c1"],"A citation that was not named stays");
  assert.deepEqual(sent.memo_findings[0].evidence_turns,[]);assert.deepEqual(sent.taxonomy[0].evidence_turns,["doc_b_p1_c1","u1"]);
  assert.notEqual(sent.submission_key,h.calls[0].payload.submission_key,"It is a new submission, not a retry of the refused one");
  assert.match(JSON.stringify(h.state),/doc_a_r1_c1/,"The interview itself keeps its citations");
  assert.match(h.text(),/Process submitted/);
  assert.match(h.text(),/5 file citations were left out of this revision/);
});

await check("after a citation refusal the ordinary Submit still files the capture unchanged",async()=>{
  const h=setup(CITED());h.open();
  h.respond=async()=>{throw refusal([REMOVED_FILE]);};await h.submit();
  h.respond=async()=>receipt(1);                 // the file was restored in Assets meanwhile
  await h.submit();
  assert.equal(h.calls.length,2);assert.match(JSON.stringify(h.calls[1].payload.draft),/doc_a_r1_c1/);
  assert.match(h.text(),/Process submitted/);assert.doesNotMatch(h.text(),/left out of this revision/);
});

await check("a later refusal adds to what Submit without these citations leaves out",async()=>{
  const h=setup(CITED());h.open();
  h.respond=async()=>{throw refusal([REMOVED_FILE]);};await h.submit();
  h.respond=async()=>{throw refusal([UNKNOWN_FILE],"These parts cite a file that is not among this interview’s files on this computer: working map step S1 “Check the log”. You can submit without these citations.");};
  await without(h).dispatch("click");await settle();
  assert.equal(h.calls.length,2);assert.doesNotMatch(JSON.stringify(h.calls[1].payload),/doc_a_r1_c1/);assert.match(JSON.stringify(h.calls[1].payload),/doc_b_p1_c1/);
  assert.equal(offered(h),true);assert.ok(h.statusLines().some(line=>/not among this interview/.test(line)));
  h.respond=async()=>receipt(1);
  await without(h).dispatch("click");await settle();
  assert.equal(h.calls.length,3);
  assert.doesNotMatch(JSON.stringify(h.calls[2].payload),/doc_[ab]_/,"Both refusals are honoured, or the two would alternate for ever");
  assert.match(h.text(),/7 file citations were left out of this revision/);
});

await check("every affected file is listed with its state and the parts that cite it",async()=>{
  const h=setup(CITED());h.open();
  const parked={document_id:"doc_c",name:"policy.pdf",state:"parked",source_ids:["doc_c_p1_c1"],cited_by:Array.from({length:12},(_,i)=>"draft step S"+(i+1)),more:2};
  h.respond=async()=>{throw refusal([REMOVED_FILE,parked,UNKNOWN_FILE]);};await h.submit();
  const lines=all(h.dialog).filter(node=>node.tagName==="LI").map(node=>node.textContent);
  assert.equal(lines.length,3);
  assert.match(lines[0],/^returns-log\.csv \(removed from this interview\): draft step S1 “Check the log”; the “Checks, approvals & proof” note$/);
  assert.match(lines[1],/^policy\.pdf \(saved for later\): draft step S1; .*draft step S12; and 2 more$/);
  assert.match(lines[2],/^A file that is not among this interview’s files \(cannot be read\): working map step S1/);
  const single=setup(CITED());single.open();single.respond=async()=>{throw refusal([REMOVED_FILE]);};await single.submit();
  assert.equal(all(single.dialog).filter(node=>node.tagName==="LI").length,0,"One file with a few parts is already complete in the message");
});

await check("an ordinary refusal offers no citation choice, and a new refusal replaces an old one",async()=>{
  const h=setup(CITED());h.open();
  h.respond=async()=>{throw refusal([REMOVED_FILE]);};await h.submit();
  assert.equal(offered(h),true);
  h.respond=async()=>{throw Object.assign(Error("Revisions require a verified owner or administrator."),{status:403});};
  await h.submit();
  assert.equal(offered(h),false);assert.ok(h.statusLines().includes("Revisions require a verified owner or administrator."));
  const plain=setup(CITED());plain.open();
  plain.respond=async()=>{throw Object.assign(Error("The submission cites document evidence that is unavailable."),{status:400});};
  await plain.submit();
  assert.equal(offered(plain),false,"Without the structured refusal there is nothing to leave out");
});

await check("one citation left out is reported in the singular",async()=>{
  const h=setup({workflow:{title:"Returns intake",steps:[{id:"d1",title:"Review the export",evidence_turns:["doc_a_r1_c1"]},{id:"S1",title:"Register",evidence_turns:["u1"]}],connections:[]}});h.open();
  h.respond=async()=>{throw refusal([{...REMOVED_FILE,cited_by:["working map step d1 “Review the export”"]}]);};await h.submit();
  h.respond=async()=>receipt(1);
  await without(h).dispatch("click");await settle();
  assert.deepEqual(h.calls[1].payload.workflow.steps.map(step=>step.evidence_turns),[[],["u1"]]);
  assert.match(h.text(),/1 file citation was left out of this revision\. Your interview keeps it\./);
});

await check("Submit without these citations waits for the capture gate like any submission",async()=>{
  const h=setup(CITED());h.open();
  h.respond=async()=>{throw refusal([REMOVED_FILE]);};await h.submit();
  h.gate.waiting=WAITING;h.respond=async()=>receipt(1);
  await without(h).dispatch("click");await settle();
  assert.equal(h.calls.length,1,"Nothing is filed while notes and the map are still catching up");
  assert.equal(offered(h),true);
  h.gate.waiting="";h.controller.captureChanged();
  await without(h).dispatch("click");await settle();
  assert.equal(h.calls.length,2);assert.doesNotMatch(JSON.stringify(h.calls[1].payload),/doc_a_r1_c1/);
});

// Repair round 1: passages of a removed or saved-for-later file are stored in company knowledge as saved
// excerpts. The dialog names those files before the submitter confirms, and can leave the passages out.
const WITH_SAVED=()=>({documents:{scope:"scope_synthetic",documents:[
    {id:"doc_live",name:"policy.pdf",status:"ready",analysis:{disposition:"relevant"}},
    {id:"doc_park",name:"salary-bands.csv",status:"ready",analysis:{disposition:"parked"}}]},
  document_evidence:[{id:"doc_gone_r1_c1",document_id:"doc_gone",name:"returns-log.csv",retained_only:true,archived:true},{id:"doc_live_p1_c1",document_id:"doc_live",name:"policy.pdf"}],
  workflow:{title:"Returns intake",steps:[{id:"S1",title:"Check the log",evidence_turns:["doc_gone_r1_c1","u1"]},{id:"S2",title:"Apply the policy",evidence_turns:["doc_live_p1_c1"]},
    {id:"S3",title:"Check the band",evidence_turns:["doc_park_r2_c1"]}],connections:[]},
  memo_findings:[{key:"checks",status:"known",answer:"Each return is checked.",evidence_turns:["doc_gone_r1_c1","doc_gone_r2_c1"]}]});
const savedNotice=h=>h.statusLines().find(line=>/no longer in use|not among this interview’s files/.test(line));
const leaveOut=h=>find(h.dialog,node=>node.tagName==="LABEL"&&/Leave these passages out of this submission/.test(node.textContent))?.children[0];
// The page lists a removed file apart from the files in use (the Assets panel's "Removed files"); it is
// not in session.documents.documents. r1-submit-1: only such a file is said to be stored as a saved excerpt.
const withSaved=session=>{const h=setup({...WITH_SAVED(),...session});h.workspace.removed=[{id:"doc_gone",name:"returns-log.csv"}];return h;};

await check("files that are no longer in use are named before their passages are stored",async()=>{
  const h=withSaved();h.open();
  const line=savedNotice(h);
  assert.ok(line,"The dialog must say before submitting that passages of removed or saved-for-later files are stored");
  assert.match(line,/“returns-log\.csv” \(removed\)/);assert.match(line,/“salary-bands\.csv” \(saved for later\)/);
  assert.doesNotMatch(line,/policy\.pdf/,"A file in use is not listed");
  assert.match(line,/stores those passages in company knowledge as saved excerpts/);
  const choice=leaveOut(h);
  assert.ok(choice,"The submitter can leave those passages out");assert.equal(choice.type,"checkbox");assert.equal(choice.checked,false);
  await h.submit();
  assert.equal(h.calls.length,1);
  assert.match(JSON.stringify(h.calls[0].payload),/doc_gone_r1_c1/,"By default the snapshot is sent unchanged; the server decides what a saved excerpt may support");
  assert.match(h.text(),/Process submitted/);assert.doesNotMatch(h.text(),/left out of this revision/);
});

await check("leaving those passages out removes exactly the citations of files that are no longer in use",async()=>{
  const h=withSaved();h.open();
  leaveOut(h).checked=true;
  await h.submit();
  assert.equal(h.calls.length,1);
  const sent=h.calls[0].payload;
  assert.doesNotMatch(JSON.stringify(sent),/doc_gone_|doc_park_/);
  assert.deepEqual(sent.workflow.steps.map(step=>step.evidence_turns),[["u1"],["doc_live_p1_c1"],[]]);
  assert.deepEqual(sent.memo_findings[0].evidence_turns,[]);
  assert.match(JSON.stringify(h.state),/doc_gone_r1_c1/,"The interview itself keeps its citations");
  assert.match(h.text(),/4 file citations were left out of this revision\. Your interview keeps them\./);
  // The choice is part of the captured attempt: it cannot change while the attempt is being sent or recovered.
  const lost=withSaved();lost.open();leaveOut(lost).checked=true;
  lost.respond=async()=>{throw Object.assign(Error("Connection lost"),{status:0});};
  await lost.submit();
  assert.equal(lost.controller.hasPending,true);assert.equal(leaveOut(lost).disabled,true);
  lost.dialog.close();lost.open();
  assert.equal(leaveOut(lost).checked,true,"A reopened dialog shows what the pending attempt left out");assert.equal(leaveOut(lost).disabled,true);
  lost.respond=async()=>receipt(1);await lost.submit();
  assert.deepEqual(lost.calls[1].payload,lost.calls[0].payload);
  const refusedOnce=withSaved();refusedOnce.open();
  refusedOnce.respond=async()=>{throw Object.assign(Error("Revisions require a verified owner or administrator."),{status:403});};
  await refusedOnce.submit();
  assert.equal(leaveOut(refusedOnce).disabled,false,"After a refusal the choice is open again");
});

await check("no saved-excerpt notice without such citations, and an unknown file is not given a name",async()=>{
  const none=setup();none.open();
  assert.equal(savedNotice(none),undefined);assert.equal(leaveOut(none),undefined);
  const active=withSaved({workflow:{title:"Returns intake",steps:[{id:"S2",title:"Apply the policy",evidence_turns:["doc_live_p1_c1","u1"]}],connections:[]},memo_findings:[]});active.open();
  assert.equal(savedNotice(active),undefined,"Citations of a file in use need no notice");
  // A file whose ID merely starts like a listed or removed one is a different file. (Changed on purpose for
  // r1-submit-1: this pinned "(removed)" and the saved-excerpt promise for a file the server cannot read.)
  const other=withSaved({document_evidence:[],workflow:{title:"Returns intake",steps:[{id:"S1",title:"Check",evidence_turns:["doc_livelier_p1_c1","doc_goner_p1_c1","u1"]}],connections:[]},memo_findings:[]});other.open();
  assert.match(savedNotice(other),/^This interview cites passages of a file that is not among this interview’s files on this computer: a file whose name is not known\. /);
  assert.doesNotMatch(savedNotice(other),/removed|saved excerpts|policy\.pdf|returns-log/);
  const many=withSaved({workflow:{title:"Returns intake",steps:Array.from({length:7},(_,i)=>({id:"S"+i,title:"Step",evidence_turns:[`doc_f${i}_p1_c1`,"u1"]})),connections:[]},memo_findings:[]});
  many.workspace.removed=Array.from({length:7},(_,i)=>({id:"doc_f"+i,name:`file-${i}.pdf`}));many.open();
  assert.match(savedNotice(many),/files that are no longer in use: .*“file-\d\.pdf” \(removed\), 2 more\. /);
});

// r1-submit-1 (follow-up of gap-knowledge-documents-1): the server can file a saved excerpt only from a file
// its file workspace still holds. A cited file that is neither listed nor among the removed files (interview
// reopened on another computer, or after Start new file workspace) is refused, so the dialog must not
// promise that its passages are stored.
const unreadNotice=h=>h.statusLines().find(line=>/not among this interview’s files on this computer/.test(line));
await check("a cited file that is not in the current file workspace is not said to be stored",async()=>{
  // After Start new file workspace: no files listed, nothing removed; the cached excerpt still says the file was removed.
  const h=setup({...WITH_SAVED(),documents:{scope:null,documents:[]},memo_findings:[],
    workflow:{title:"Returns intake",steps:[{id:"S1",title:"Check the log",evidence_turns:["doc_gone_r1_c1","u1"]}],connections:[]}});h.open();
  const line=unreadNotice(h);
  assert.ok(line,"The dialog must say that the passages cannot be read on this computer: "+h.statusLines().join(" | "));
  assert.match(line,/^This interview cites passages of a file that is not among this interview’s files on this computer: “returns-log\.csv”\. /);
  assert.match(line,/cannot be read here, so company knowledge cannot store them\. Leave them out below, or the submission will be refused\.$/);
  assert.doesNotMatch(h.text(),/stores those passages|saved excerpts|\(removed\)|no longer in use/,"Nothing may be promised that the server will refuse");
  const choice=leaveOut(h);assert.ok(choice,"The way forward is offered before the refusal");assert.equal(choice.checked,false);
  // Unchanged, the snapshot is sent as it is and the server's refusal is shown with its own way forward.
  h.respond=async()=>{throw refusal([{document_id:"",name:"",state:"unavailable",source_ids:["doc_gone_r1_c1"],cited_by:["working map step S1 “Check the log”"],more:0}],
    "These parts cite a file that is not among this interview’s files on this computer: working map step S1 “Check the log”. You can submit without these citations.");};
  await h.submit();
  assert.match(JSON.stringify(h.calls[0].payload),/doc_gone_r1_c1/);assert.equal(offered(h),true);
  // Ticked, the passages are left out and the submission is filed.
  h.respond=async()=>receipt(1);leaveOut(h).checked=true;
  await h.submit();
  assert.deepEqual(h.calls[1].payload.workflow.steps[0].evidence_turns,["u1"]);
  assert.match(h.text(),/Process submitted/);assert.match(h.text(),/1 file citation was left out of this revision/);
});

await check("a file workspace that cannot be opened on this computer makes every cited file unreadable",async()=>{
  // Interview reopened on another computer: the saved list still names the files, but none can be read here.
  const h=withSaved();h.workspace={unavailable:true,removed:[]};h.open();
  const line=unreadNotice(h);
  assert.ok(line);assert.match(line,/files that are not among this interview’s files on this computer: /);
  for(const name of ["policy.pdf","salary-bands.csv","returns-log.csv"])assert.ok(line.includes(`“${name}”`),name+" is named");
  assert.doesNotMatch(h.text(),/stores those passages|saved for later\)|\(removed\)/);
  leaveOut(h).checked=true;await h.submit();
  assert.doesNotMatch(JSON.stringify(h.calls[0].payload),/doc_(gone|live|park)_[pr]\d/,"Every file citation is left out");
});

await check("files that can be filed as saved excerpts and files that cannot are told apart in one notice",async()=>{
  const h=withSaved({workflow:{title:"Returns intake",steps:[{id:"S1",title:"Check the log",evidence_turns:["doc_gone_r1_c1","u1"]},{id:"S3",title:"Check the band",evidence_turns:["doc_park_r2_c1"]},
    {id:"S4",title:"Compare",evidence_turns:["doc_old_p3_c1","u1"]}],connections:[]},memo_findings:[],
    document_evidence:[{id:"doc_old_p3_c1",document_id:"doc_old",name:"2024-procedure.pdf",retained_only:true,archived:true}]});h.open();
  const line=savedNotice(h);
  const [kept]=line.split(" This interview also cites ");
  assert.match(kept,/^This interview cites passages of files that are no longer in use: .*\)\. Submitting stores those passages in company knowledge as saved excerpts\.$/);
  assert.match(kept,/“returns-log\.csv” \(removed\)/);assert.match(kept,/“salary-bands\.csv” \(saved for later\)/);
  assert.match(line,/ This interview also cites passages of a file that is not among this interview’s files on this computer: “2024-procedure\.pdf”\. Those passages cannot be read here/);
  assert.equal(line.split("2024-procedure.pdf").length,2,"The unreadable file is named once, and not among the saved excerpts");
});

await check("without a file-workspace provider an unlisted file is not promised either",async()=>{
  const nodes={};for(const id of ["knowledge-submit","submit-process-menu","submit-process-review","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,crypto:{randomUUID:()=>uuid(78).replace(/^0{8}/,"eeeeeeee")}};
  vm.runInNewContext(source,env,{filename:"knowledge-ui.js"});
  const controller=env.window.CollectorKnowledge.create({session:()=>({turns:[{id:"u1",role:"user",text:"An answer."}],...WITH_SAVED()}),notice(){},request:async()=>receipt(1)});
  controller.openSubmit();
  const lines=all(nodes["knowledge-submit"]).filter(node=>node.className==="knowledge-status"&&!node.hidden&&node._text).map(node=>node._text).join(" ");
  assert.match(lines,/no longer in use: “salary-bands\.csv” \(saved for later\)\./);assert.match(lines,/not among this interview’s files on this computer: “returns-log\.csv”\./);
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
