"use strict";
// One submission attempt of the Submit process dialog from start to outcome: when a snapshot may be
// taken, what is sent, what the submitter is told when the dialog is closed, and how an attempt that
// was not confirmed is recovered or given up. The real web/knowledge-ui.js behind a synthetic DOM
// (harness after tests/test_submit_dialog.cjs). No browser, provider or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"..","web","knowledge-ui.js"),"utf8");
const all=root=>[root,...root.children.flatMap(all)],find=(root,test)=>all(root).find(test);
class E{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.dataset={};this.style={};this.hidden=false;this.open=false;this.value="";this._text="";this.disabled=false;this.checked=false;}
  append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this._text="";this.append(...children);}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join("");}
  setAttribute(key,value){this.attributes[key]=String(value);}
  addEventListener(key,fn){(this.listeners[key]??=[]).push(fn);}
  async dispatch(key){for(const fn of this.listeners[key]||[])await fn({preventDefault(){},target:this});}
  querySelectorAll(){return[];}querySelector(){return null;}
  showModal(){this.open=true;}close(){this.open=false;}focus(){this.focused=true;}
}
const settle=async()=>{for(let i=0;i<3;i++)await new Promise(resolve=>setImmediate(resolve));};
const uuid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const receipt=(revision=1,process=2)=>({submission_id:uuid(1),process_id:uuid(process),revision,job_id:uuid(10+revision),status:"pending",status_token:"a".repeat(64)});
const complete=turn=>({in_progress:false,notes_current:true,map_current:true,notes_through_turn:turn,map_through_turn:turn});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
const lost=()=>Object.assign(Error("The interviewer isn’t available right now. Try again in a moment."),{name:"TypeError"});

function setup(session={}){
  const nodes={};for(const id of ["knowledge-submit","submit-process-menu","submit-process-review","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  const calls=[],notices=[],timers=new Map();let keys=0,timerId=0;
  const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,TextEncoder,
    setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},clearTimeout:id=>timers.delete(id),
    crypto:{randomUUID:()=>`eeeeeeee-eeee-4eee-8eee-${String(++keys).padStart(12,"0")}`}};
  vm.runInNewContext(source,env,{filename:"knowledge-ui.js"});
  const state={saved_at:"2026-11-13T00:00:00.000Z",interview_id:uuid(900),context:{process_name:"Invoice intake"},turns:[{id:"u1",role:"user",text:"A supplier email starts a case."}],
    documents:null,workflow:{title:"Invoice intake",steps:[{id:"S1",title:"Receive and register invoice",evidence_turns:["u1"]}],connections:[]},draft:null,draft_stale:false,draft_edited:false,capture:complete("u1"),...session};
  // gate, drafts and workspace: what app.js reports through captureState(), draftState() and fileWorkspace().
  const h={nodes,calls,notices,state,timers,gate:{waiting:"",action:"",missing:[]},drafts:{pending:false,arrivals:0},workspace:{unavailable:false,removed:[]},respond:async()=>receipt(calls.length)};
  h.controller=env.window.CollectorKnowledge.create({session:()=>structuredClone(h.state),notice:(message,error)=>notices.push({message,error:Boolean(error)}),
    captureState:()=>structuredClone(h.gate),draftState:()=>structuredClone(h.drafts),fileWorkspace:()=>structuredClone(h.workspace),draftStaleReason:()=>"answers",
    request:async(pathName,payload)=>{if(pathName==="/api/knowledge/status")return {...payload,status:"pending",latest_revision:payload.revision};calls.push({path:pathName,payload:structuredClone(payload)});return h.respond(pathName,payload);}});
  h.dialog=nodes["knowledge-submit"];
  h.attribution=()=>JSON.parse(JSON.stringify(h.controller.exportAttribution()));   // a plain copy: the controller lives in another realm
  h.send=()=>find(h.dialog,node=>node.tagName==="BUTTON"&&node.type==="submit");
  h.button=label=>find(h.dialog,node=>node.tagName==="BUTTON"&&node.textContent===label);
  h.visible=node=>{for(let item=node;item;item=item.parentElement)if(item.hidden)return false;return Boolean(node);};
  h.controller.configure({revisions_available:true});
  h.open=()=>{h.controller.openSubmit();return h.dialog;};
  h.form=()=>find(h.dialog,node=>node.tagName==="FORM");
  h.field=name=>find(h.dialog,node=>node.tagName==="INPUT"&&node.name===name);
  h.type=async(name,text)=>{const input=h.field(name);input.value=text;await input.dispatch("input");};
  h.text=()=>h.dialog.textContent;
  h.statusLines=()=>all(h.dialog).filter(node=>node.className==="knowledge-status"&&h.visible(node)&&node._text).map(node=>node._text);
  h.submit=async()=>{await h.form().dispatch("submit");await settle();};
  h.click=async label=>{const control=h.button(label);assert.ok(control&&h.visible(control),"Missing control: "+label);await control.dispatch("click");await settle();};
  h.menu=async()=>{await nodes["session-menu-toggle"].dispatch("click");return nodes["submit-process-menu"];};
  return h;
}

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
// gap3-submit-in-flight-2: no snapshot while Live voice is on or its last caption is being saved.
// (Resolved by wave 1's capture gate; these pin both voice states at both places the finding names.)
await check("no snapshot is filed while voice is on or the last caption is being saved",async()=>{
  for(const [waiting,action,line] of [
    ["Voice is still on.","Close this window and choose Stop talking, then submit.","Voice is still on. Close this window and choose Stop talking, then submit."],
    ["The last part of your conversation is still being saved.","","The last part of your conversation is still being saved. Submit is available when this finishes."]]){
    // The state is already there when the dialog opens.
    const early=setup();early.gate={waiting,action,missing:[]};early.open();
    if(action){assert.equal(early.dialog.open,false);assert.match(early.notices.at(-1).message,/stop talking/i);}
    else{assert.equal(early.send().disabled,true,waiting);assert.ok(early.statusLines().includes(line));await early.submit();}
    assert.equal(early.calls.length,0,"Nothing is filed: "+waiting);
    // The state begins after the dialog opened, and nothing told the dialog: the snapshot is still refused.
    const late=setup();late.open();assert.equal(late.send().disabled,false);
    late.gate={waiting,action,missing:[]};
    await late.submit();
    assert.equal(late.calls.length,0,"The check is repeated where the snapshot is taken: "+waiting);
    assert.equal(late.controller.hasPending,false);assert.ok(late.statusLines().includes(line));
    late.gate={waiting:"",action:"",missing:[]};late.controller.captureChanged();
    await late.submit();assert.equal(late.calls.length,1,"Once voice has ended and the caption is saved, the complete answer is filed");
  }
});

await check("a submission that was not confirmed stays reachable while voice is on",async()=>{
  const h=setup();h.open();h.respond=async()=>{throw lost();};await h.submit();
  assert.equal(h.controller.hasPending,true);h.dialog.close();
  h.gate={waiting:"Voice is still on.",action:"Close this window and choose Stop talking, then submit.",missing:[]};
  assert.equal((await h.menu()).textContent,"Submission status");
  h.open();assert.equal(h.send().disabled,false,"Recover retries a frozen snapshot and is not blocked by voice");
  h.respond=async()=>receipt(1);await h.submit();
  assert.deepEqual(h.calls[1].payload,h.calls[0].payload);assert.match(h.text(),/Process submitted/);
});

// gap3-submit-in-flight-5: a snapshot taken while Create draft or Update draft runs lacks the draft, or
// files the one about to be replaced.
await check("Submit waits for a draft request and says that the draft will then be included",async()=>{
  const h=setup();h.drafts.pending=true;h.gate={waiting:"A draft is being created.",action:"Submit when it is ready so the draft is included.",missing:[]};h.open();
  assert.equal(h.send().disabled,true);
  assert.ok(h.statusLines().includes("A draft is being created. Submit when it is ready so the draft is included."),h.statusLines().join(" | "));
  await h.submit();assert.equal(h.calls.length,0);
  // The draft arrives: the page reports it and the snapshot now carries it.
  h.state.draft={title:"Invoice intake",overview:"AP registers and checks supplier invoices.",steps:[],connections:[]};
  h.drafts={pending:false,arrivals:1};h.gate={waiting:"",action:"",missing:[]};h.controller.captureChanged();
  assert.equal(h.send().disabled,false);
  await h.submit();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].payload.draft.overview,"AP registers and checks supplier invoices.");
  assert.match(h.text(),/Process submitted/);assert.doesNotMatch(h.text(),/newer draft/i,"The filed revision holds the draft");
});

await check("a draft that arrives after the snapshot was taken is reported on the receipt",async()=>{
  // The submission is on its way, the dialog was closed as invited, and Create draft was then started.
  const h=setup(),pending=deferred();h.open();h.respond=()=>pending.promise;
  const sending=h.submit();await settle();
  h.state.draft={title:"Invoice intake",overview:"Created after the snapshot.",steps:[],connections:[]};h.drafts.arrivals=1;
  pending.resolve(receipt(1));await sending;
  assert.equal(h.calls[0].payload.draft,null);
  assert.match(h.text(),/Process submitted/);
  assert.ok(h.statusLines().includes("A newer draft arrived after this submission and is not part of revision 1. Submit again to include it."),h.statusLines().join(" | "));
  // The receipt is open when the draft arrives: the line is added once.
  const open=setup();open.open();await open.submit();
  assert.match(open.text(),/Process submitted/);assert.doesNotMatch(open.text(),/newer draft/i);
  open.drafts.arrivals=1;open.controller.captureChanged();open.controller.captureChanged();
  assert.equal(open.statusLines().filter(line=>/A newer draft arrived after this submission/.test(line)).length,1);
  // A reopened dialog says it too, until the interview is filed again.
  open.dialog.close();open.state.draft={title:"Invoice intake",steps:[],connections:[]};open.open();
  assert.match(open.text(),/Revision 1 does not include the draft created since\. Submit again to file the interview as it stands now\./);
  await open.submit();open.dialog.close();open.open();
  assert.doesNotMatch(open.text(),/draft created since|newer draft/i);
});

// live-draft-knowledge-2: a revision must not blank participant, team, department and scope.
const ATTRIBUTION=["participant","team","department","scope"];
const sentAttribution=payload=>Object.fromEntries(ATTRIBUTION.filter(key=>key in payload).map(key=>[key,payload[key]]));
const hint=h=>all(h.dialog).filter(node=>node.className==="knowledge-muted").map(node=>node._text).find(line=>/Participant names are self-reported/.test(line));
await check("a revision starts from the details the previous revision recorded",async()=>{
  const h=setup();h.open();
  assert.equal(hint(h),"All fields are optional. Participant names are self-reported.","A first submission is described as before");
  await h.type("participant","Fictional vendor master coordinator");await h.type("team","Procurement Operations");await h.type("department","Finance");
  await h.submit();
  assert.deepEqual(sentAttribution(h.calls[0].payload),{participant:"Fictional vendor master coordinator",team:"Procurement Operations",department:"Finance",scope:""},"A new process sends all four fields");
  assert.deepEqual(h.attribution(),{participant:"Fictional vendor master coordinator",team:"Procurement Operations",department:"Finance",scope:""});
  // One correction later the participant resubmits without retyping anything.
  h.dialog.close();h.state.turns.push({id:"u2",role:"user",text:"The threshold is 5,000, not 500."});h.state.capture=complete("u2");h.open();
  assert.deepEqual(ATTRIBUTION.map(key=>h.field(key).value),["Fictional vendor master coordinator","Procurement Operations","Finance",""],"The form shows what revision 1 recorded");
  assert.equal(hint(h),"The fields show what revision 1 recorded. Change what is no longer right; a field you clear is filed blank. Participant names are self-reported.");
  h.respond=async()=>receipt(2);await h.submit();
  const revision=h.calls[1].payload;
  assert.equal(revision.process_id,uuid(2));
  assert.deepEqual(sentAttribution(revision),{participant:"Fictional vendor master coordinator",team:"Procurement Operations",department:"Finance"},"Untouched details are filed again; the empty, untouched scope is left to the server");
  // Clearing a field is an explicit choice and is sent as empty; a changed field is sent as typed.
  h.dialog.close();h.open();await h.type("team","");await h.type("scope","Fund A");
  h.respond=async()=>receipt(3);await h.submit();
  assert.deepEqual(sentAttribution(h.calls[2].payload),{participant:"Fictional vendor master coordinator",team:"",department:"Finance",scope:"Fund A"});
  assert.deepEqual(h.attribution(),{participant:"Fictional vendor master coordinator",team:"",department:"Finance",scope:"Fund A"});
  assert.equal("knowledge_attribution" in h.calls[2].payload,false);
});

await check("a reopened interview carries the filed details, and one saved without them leaves them to the server",async()=>{
  // Saved after the fix: the file holds the details beside the process ID and the status access.
  const saved=setup({knowledge_attribution:{participant:"Should not be sent as a session field"}});
  saved.controller.restore(uuid(2),receipt(1),{participant:"Dana (fictional)",team:"Treasury",department:"",scope:"Fund A",role:"admin",extra:7});
  assert.deepEqual(saved.attribution(),{participant:"Dana (fictional)",team:"Treasury",department:"",scope:"Fund A"},"Only the four text fields are kept");
  saved.open();
  assert.deepEqual(ATTRIBUTION.map(key=>saved.field(key).value),["Dana (fictional)","Treasury","","Fund A"]);
  saved.respond=async()=>receipt(2);await saved.submit();
  assert.deepEqual(sentAttribution(saved.calls[0].payload),{participant:"Dana (fictional)",team:"Treasury",scope:"Fund A"});
  assert.equal("knowledge_attribution" in saved.calls[0].payload,false,"The saved copy of the details is not part of the filed interview");
  // Saved before the fix: only the process ID and the status access. Nothing is known, so nothing is sent
  // for an untouched field and the server keeps what the previous revision recorded.
  const older=setup();older.controller.restore(uuid(2),receipt(1));
  assert.equal(older.attribution(),null);
  older.open();
  assert.deepEqual(ATTRIBUTION.map(key=>older.field(key).value),["","","",""]);
  assert.match(hint(older),/^A revision keeps the participant, team, department and scope of the previous revision in every field you leave untouched\. To file a field blank, type in it and clear it again\./);
  await older.type("scope","Fund B");await older.type("team","Typed by mistake");await older.type("team","");
  older.respond=async()=>receipt(2);await older.submit();
  assert.deepEqual(sentAttribution(older.calls[0].payload),{team:"",scope:"Fund B"},"Untouched fields are omitted, a cleared one is sent empty, a typed one as typed");
  assert.deepEqual(older.attribution(),{team:"",scope:"Fund B"},"Only what this tab knows is saved");
  // Malformed saved details are ignored, and details without a process ID belong to nothing.
  const odd=setup();odd.controller.restore(uuid(2),receipt(1),{participant:7,team:"x".repeat(501),scope:["Fund A"]});assert.equal(odd.attribution(),null);
  odd.controller.restore("not-an-id",null,{team:"Treasury"});assert.equal(odd.attribution(),null);
});

await check("submitting as a new process files the form as it stands and says the fields are optional",async()=>{
  const h=setup();h.controller.restore(uuid(2),receipt(1),{participant:"Dana (fictional)",team:"Treasury",department:"",scope:""});h.open();
  const choice=find(h.dialog,node=>node.tagName==="INPUT"&&node.type==="checkbox");
  choice.checked=true;await choice.dispatch("change");
  assert.equal(hint(h),"All fields are optional. Participant names are self-reported.");
  h.respond=async()=>receipt(1,7);await h.submit();
  assert.equal(h.calls[0].payload.process_id,undefined);
  assert.deepEqual(sentAttribution(h.calls[0].payload),{participant:"Dana (fictional)",team:"Treasury",department:"",scope:""},"A new process has nothing to inherit from: every field is sent");
  choice.checked=false;
});

// data-pipeline-2: what is sent, and how large it may be.
const reviewedFile=number=>({id:"doc_"+number,name:`procedure-${number}.pdf`,kind:"pdf",size:48000,sha256:"f".repeat(64),status:"ready",chunk_count:30,
  analysis:{phase:"complete",disposition:"relevant",observations:Array.from({length:200},(_,index)=>({text:`Observation ${index}: `+"detail ".repeat(90)})),sources:[{source_id:`doc_${number}_p1_c1`,label:"page 1"}]}});
await check("of each attached file only the ID is sent, however large its review record is",async()=>{
  const files=Array.from({length:5},(_,index)=>reviewedFile(index+1));
  const h=setup({documents:{scope:"scope-synthetic",documents:files},document_evidence:[{id:"doc_1_p1_c1",document_id:"doc_1",name:"procedure-1.pdf",text:"Cached text"}],
    workflow:{title:"Invoice intake",steps:[{id:"S1",title:"Check",evidence_turns:["doc_1_p1_c1","u1"]}],connections:[]}});
  assert.ok(JSON.stringify(h.state).length>600000,"The interview as the page holds it is larger than the old request limit");
  h.open();await h.submit();
  assert.equal(h.calls.length,1,h.statusLines().join(" | "));
  const sent=h.calls[0].payload;
  assert.deepEqual(sent.documents,{scope:"scope-synthetic",documents:files.map(file=>({id:file.id}))});
  assert.ok(JSON.stringify(sent).length<5000,"The request no longer grows with the review records");
  assert.deepEqual(sent.workflow.steps[0].evidence_turns,["doc_1_p1_c1","u1"],"Citations are sent as they are; the server resolves them");
  assert.equal("document_evidence" in sent,false);
  assert.match(JSON.stringify(h.state.documents),/Observation 199/,"The interview itself keeps its records");
  const none=setup();none.open();await none.submit();assert.equal(none.calls[0].payload.documents,null,"No file workspace, no file list");
  const malformed=setup({documents:{scope:"scope-synthetic",documents:[null,{name:"no id"},{id:7},reviewedFile(9)]}});malformed.open();await malformed.submit();
  assert.deepEqual(malformed.calls[0].payload.documents.documents,[{id:"doc_9"}]);
});

await check("a file workspace that cannot be opened here is not sent as this submission's files",async()=>{
  // Interview reopened on another computer: the server would refuse the unknown workspace outright, and
  // leaving the unreadable passages out (r1-submit-1) could then never succeed.
  const h=setup({documents:{scope:"scope-from-another-computer",documents:[reviewedFile(1)]},
    workflow:{title:"Invoice intake",steps:[{id:"S1",title:"Check",evidence_turns:["doc_1_p1_c1","u1"]}],connections:[]}});
  h.workspace.unavailable=true;h.open();
  const choice=find(h.dialog,node=>node.tagName==="LABEL"&&/Leave these passages out/.test(node.textContent))?.children[0];
  assert.ok(choice,"The unreadable passages are named with a way to leave them out");choice.checked=true;
  await h.submit();
  assert.equal(h.calls[0].payload.documents,null);assert.deepEqual(h.calls[0].payload.workflow.steps[0].evidence_turns,["u1"]);
});

await check("an interview that is too large is refused before anything is sent, with the part that is too large",async()=>{
  const long=Array.from({length:260},(_,index)=>({id:"u"+(index+1),role:"user",text:"Answer "+index+" "+"word ".repeat(1000)}));
  const h=setup({turns:long,capture:complete("u260"),draft:{title:"Invoice intake",overview:"Short.",steps:[],connections:[]}});h.open();
  await h.submit();
  assert.equal(h.calls.length,0,"Nothing is sent");assert.equal(h.controller.hasPending,false,"There is no attempt to recover");
  const line=h.statusLines().find(text=>/too large to submit/.test(text));
  assert.ok(line,h.statusLines().join(" | "));
  assert.match(line,/^This interview is too large to submit: it is 1,3\d\d kB and company knowledge accepts 1,000 kB\. The largest part is the transcript \(1,3\d\d kB\)\. Nothing was sent\.$/);
  assert.equal(h.send().textContent,"Submit process");assert.equal(h.send().disabled,false);assert.equal(h.field("team").disabled,false);
  assert.equal((await h.menu()).textContent,"Submit process","No Submission status entry for something that was never sent");
  // The limit is the server's (/api/config), bytes are counted as the server counts them, and the part named is the largest.
  const small=setup({turns:[{id:"u1",role:"user",text:"é".repeat(1500)}]});small.controller.configure({knowledge_submit_max_bytes:2500});small.open();
  await small.submit();
  assert.equal(small.calls.length,0,"1,500 two-byte characters are 3,000 bytes");
  assert.match(small.statusLines().join(" "),/it is 4 kB and company knowledge accepts 3 kB\. The largest part is the transcript/);
  const drafted=setup({draft:{title:"Invoice intake",overview:"x".repeat(4000),steps:[],connections:[]}});drafted.controller.configure({knowledge_submit_max_bytes:2500});drafted.open();
  await drafted.submit();assert.match(drafted.statusLines().join(" "),/The largest part is the draft \(5 kB\)/);
  const fits=setup();fits.controller.configure({knowledge_submit_max_bytes:2500});fits.open();await fits.submit();assert.equal(fits.calls.length,1);
  for(const odd of [0,-5,"1000",null,1.5]){const kept=setup();kept.controller.configure({knowledge_submit_max_bytes:odd});kept.open();await kept.submit();assert.equal(kept.calls.length,1,"An unusable limit keeps the built-in one: "+odd);}
});

// knowledge-frontend-2: the dialog invites the submitter to close it while saving; the outcome must follow them.
await check("the outcome of a submission is announced on the page when the dialog was closed meanwhile",async()=>{
  const saved=setup(),first=deferred();saved.open();saved.respond=()=>first.promise;
  const sending=saved.submit();await settle();
  assert.match(saved.text(),/You can close this window while it finishes/);
  saved.dialog.close();first.resolve(receipt(1));await sending;await settle();
  assert.deepEqual(saved.notices,[{message:"Process submitted (revision 1). Save a copy to keep its status access.",error:false}]);
  // Not confirmed: said as an error, with where to retry; the menu entry carries that name.
  const unconfirmed=setup(),second=deferred();unconfirmed.open();unconfirmed.respond=()=>second.promise;
  const failing=unconfirmed.submit();await settle();unconfirmed.dialog.close();second.reject(lost());await failing;await settle();
  assert.deepEqual(unconfirmed.notices,[{message:"The process submission was not confirmed. Open More options > Submission status to retry.",error:true}]);
  assert.equal(unconfirmed.controller.hasPending,true);assert.equal((await unconfirmed.menu()).textContent,"Submission status");
  // Refused: the reason is on the page, because the reopened dialog starts afresh.
  const refused=setup(),third=deferred();refused.open();refused.respond=()=>third.promise;
  const rejecting=refused.submit();await settle();refused.dialog.close();
  third.reject(Object.assign(Error("A submission requires a participant statement or verified document evidence."),{status:400,not_saved:true}));await rejecting;await settle();
  assert.deepEqual(refused.notices,[{message:"The process was not submitted. A submission requires a participant statement or verified document evidence.",error:true}]);
  assert.equal(refused.controller.hasPending,false);assert.equal((await refused.menu()).textContent,"Submit process");
});

await check("with the dialog open the outcome is shown there and not announced twice",async()=>{
  const h=setup();h.open();await h.submit();
  assert.match(h.text(),/Process submitted/);assert.deepEqual(h.notices,[]);
  const failed=setup();failed.open();failed.respond=async()=>{throw lost();};await failed.submit();
  assert.match(failed.text(),/It may already be saved/);assert.deepEqual(failed.notices,[]);
  const refused=setup();refused.open();refused.respond=async()=>{throw Object.assign(Error("Invalid capture state."),{status:400});};await refused.submit();
  assert.ok(refused.statusLines().includes("Invalid capture state."));assert.deepEqual(refused.notices,[]);
  // Closed and opened again while saving: the reopened dialog is open, so it shows the outcome.
  const reopened=setup(),pending=deferred();reopened.open();reopened.respond=()=>pending.promise;
  const sending=reopened.submit();await settle();reopened.dialog.close();reopened.open();
  pending.resolve(receipt(1));await sending;await settle();
  assert.match(reopened.text(),/Process submitted/);assert.deepEqual(reopened.notices,[]);
});

// knowledge-frontend-3: an attempt that was not confirmed must not hold the form for ever.
const discardControl=h=>h.button("Discard this attempt and edit");
const uncertain=async(session={})=>{const h=setup(session);h.open();await h.type("team","Treasury");h.respond=async()=>{throw lost();};await h.submit();
  assert.equal(h.controller.hasPending,true);assert.equal(h.send().textContent,"Recover previous submission");return h;};
await check("a refusal that says nothing was saved releases an attempt that was not confirmed",async()=>{
  const h=await uncertain();
  h.respond=async()=>{throw Object.assign(Error("The submission cites document evidence that is unavailable in its attached active files."),{status:400,not_saved:true});};
  await h.submit();
  assert.equal(h.controller.hasPending,false,"The server said that no record exists under this key");
  assert.deepEqual(h.statusLines(),["The submission cites document evidence that is unavailable in its attached active files."],"The plain reason, without “It may already be saved”");
  assert.equal(h.send().textContent,"Submit process");assert.equal(h.field("team").disabled,false);assert.equal(h.field("team").value,"Treasury");
  assert.equal(h.visible(discardControl(h)),false);
  assert.equal((await h.menu()).textContent,"Submit process");
  // The next press is a new submission of the interview as it stands now, under a new key.
  h.state.turns.push({id:"u2",role:"user",text:"A later answer."});h.state.capture=complete("u2");h.respond=async()=>receipt(1);
  await h.submit();
  assert.notEqual(h.calls[2].payload.submission_key,h.calls[0].payload.submission_key);assert.equal(h.calls[2].payload.turns.length,2);
  assert.match(h.text(),/Process submitted/);
  // The other refusals that carry the signal, whatever their status.
  for(const status of [403,409,413]){
    const other=await uncertain();other.respond=async()=>{throw Object.assign(Error("Refused."),{status,not_saved:true});};await other.submit();
    assert.equal(other.controller.hasPending,false,"status "+status);
  }
});

await check("a refusal without that signal keeps the attempt, because its key may hold a record",async()=>{
  for(const error of [Object.assign(Error("Submission key was already used for different content."),{status:400}),Object.assign(Error("Administrator access unavailable"),{status:403}),
    Object.assign(Error("The operation could not finish. Your interview remains in the browser."),{status:500,not_saved:false}),lost()]){
    const h=await uncertain();h.respond=async()=>{throw error;};await h.submit();
    assert.equal(h.controller.hasPending,true,error.message);
    const display=error.name==="TypeError"?"Could not reach the local company knowledge service. Keep this interview open and try again.":error.message;
    assert.ok(h.statusLines().some(line=>line.startsWith(display+" It may already be saved.")),h.statusLines().join(" | "));
    assert.equal(h.send().textContent,"Recover previous submission");assert.equal(h.field("team").disabled,true);
    assert.equal(h.visible(discardControl(h)),true,"The submitter is not left without a way out");
    h.respond=async()=>receipt(1);await h.submit();
    assert.deepEqual(h.calls[2].payload,h.calls[0].payload,"Recover still resends the frozen snapshot");assert.match(h.text(),/Process submitted/);
  }
});

await check("an attempt that was not confirmed can be discarded from the dialog",async()=>{
  const fresh=setup();fresh.open();
  assert.equal(fresh.visible(discardControl(fresh)),false,"Nothing to discard before an attempt");
  const saving=setup(),pending=deferred();saving.open();saving.respond=()=>pending.promise;const sending=saving.submit();await settle();
  assert.equal(saving.visible(discardControl(saving)),false,"Not while the attempt is being sent");
  await discardControl(saving).dispatch("click");assert.equal(saving.controller.hasPending,true,"A forced click cannot discard a submission in flight");
  pending.resolve(receipt(1));await sending;

  const h=await uncertain();
  assert.equal(h.visible(discardControl(h)),true);
  assert.match(h.text(),/If it was in fact saved, the next submission creates a separate record or a revision\./,"The consequence is stated beside the control");
  // Reopened later: the choice is still there.
  h.dialog.close();h.open();assert.equal(h.send().textContent,"Recover previous submission");assert.equal(h.visible(discardControl(h)),true);
  h.state.turns.push({id:"u2",role:"user",text:"A later answer."});h.state.capture=complete("u2");
  await h.click("Discard this attempt and edit");
  assert.equal(h.controller.hasPending,false);assert.equal(h.dialog.open,true);
  assert.equal(h.send().textContent,"Submit process");assert.equal(h.send().disabled,false);
  assert.equal(h.field("team").disabled,false);assert.equal(h.field("team").value,"Treasury","The form starts from what the discarded attempt held");
  assert.ok(h.statusLines().some(line=>/^That attempt was discarded\. If it was in fact saved, the next submission creates a separate record or a revision\.$/.test(line)));
  assert.equal(h.visible(discardControl(h)),false);assert.equal((await h.menu()).textContent,"Submit process");
  assert.equal(h.calls.length,1,"Discarding sends nothing");
  h.respond=async()=>receipt(1);await h.submit();
  const next=h.calls[1].payload;
  assert.notEqual(next.submission_key,h.calls[0].payload.submission_key);assert.equal(next.turns.length,2,"The new submission is of the interview as it stands now");
  assert.equal(next.team,"Treasury");assert.match(h.text(),/Process submitted/);
});

await check("discarding keeps the choices of the attempt in a tab that already holds a process",async()=>{
  const h=setup();h.controller.restore(uuid(2),receipt(1),{participant:"Dana (fictional)",team:"Treasury",department:"",scope:""});h.open();
  const box=()=>find(h.dialog,node=>node.tagName==="INPUT"&&node.type==="checkbox");
  box().checked=true;await box().dispatch("change");await h.type("team","");
  h.respond=async()=>{throw lost();};await h.submit();
  await h.click("Discard this attempt and edit");
  assert.equal(box().checked,true,"Submit as a new process stays chosen");assert.equal(box().disabled,false);
  assert.equal(h.field("team").value,"");assert.equal(h.field("participant").value,"Dana (fictional)");
  box().checked=false;await box().dispatch("change");
  h.respond=async()=>receipt(2);await h.submit();
  assert.equal(h.calls[1].payload.process_id,uuid(2));assert.equal(h.calls[1].payload.team,"","A field that was cleared on purpose stays cleared");
});

// gap3-two-tabs-4: the same interview submitted from a second tab, or from a copy saved before the first Submit.
const already=(revision=1,process=2)=>Object.assign(Error(`This interview was already submitted as revision ${revision}.`),{status:409,code:"interview_already_submitted",process_id:uuid(process),revision,not_saved:true});
const question=h=>h.statusLines().find(line=>/already submitted as Revision/.test(line));
await check("every submission carries the interview's own identity",async()=>{
  const h=setup();h.open();await h.submit();
  assert.equal(h.calls[0].payload.interview_id,uuid(900));assert.equal("separate_process" in h.calls[0].payload,false);
});

await check("an interview the server already holds becomes a question, not a second process",async()=>{
  const h=setup();h.open();await h.type("scope","Fund A");
  h.respond=async()=>{throw already(1);};await h.submit();
  assert.equal(h.controller.hasPending,false,"Nothing was stored: there is nothing to recover");
  assert.equal(question(h),"This interview was already submitted as Revision 1. Submit as a revision, or as a separate process?");
  assert.ok(h.visible(h.button("Submit as a revision"))&&h.visible(h.button("Submit as a separate process")));
  assert.match(h.text(),/A revision adds to the process that is already there; it requires the verified owner or an authorized administrator\. A separate process is a second record of the same interview/,"Both choices are explained before either is taken");
  assert.equal(h.visible(h.send()),false,"The plain Submit would only ask the same question again");
  assert.equal(h.field("scope").disabled,false);
  // As a revision of the process the server named; this tab now belongs to that process.
  h.respond=async(_path,payload)=>receipt(2,2);
  await h.click("Submit as a revision");
  const sent=h.calls[1].payload;
  assert.equal(sent.process_id,uuid(2));assert.equal("separate_process" in sent,false);assert.notEqual(sent.submission_key,h.calls[0].payload.submission_key);
  assert.deepEqual(sentAttribution(sent),{scope:"Fund A"},"Untouched details are left to the earlier revision, as for any revision");
  assert.match(h.text(),/Process submitted/);assert.equal(h.controller.processId,uuid(2));assert.equal(h.controller.exportReceipt().revision,2);
});

await check("a separate process is filed only when the submitter chooses it",async()=>{
  const h=setup();h.open();
  h.respond=async()=>{throw already(3,5);};await h.submit();
  assert.match(question(h),/Revision 3/);
  h.respond=async()=>receipt(1,7);
  await h.click("Submit as a separate process");
  const sent=h.calls[1].payload;
  assert.equal(sent.separate_process,true);assert.equal(sent.process_id,undefined);assert.equal(sent.interview_id,uuid(900));
  assert.match(h.text(),/Process submitted/);assert.equal(h.controller.processId,uuid(7));
  // A tab that holds a process and ticks "Submit as a new process" has made the same choice.
  const own=setup();own.controller.restore(uuid(2),receipt(1));own.open();
  assert.match(own.text(),/A new process is a second, separate record of this interview in company knowledge\./,"The choice is not offered without saying what it creates");
  const box=find(own.dialog,node=>node.tagName==="INPUT"&&node.type==="checkbox");box.checked=true;await box.dispatch("change");
  own.respond=async()=>receipt(1,8);await own.submit();
  assert.equal(own.calls[0].payload.separate_process,true);assert.equal(own.calls[0].payload.process_id,undefined);
  box.checked=false;
});

await check("where revisions are refused the question comes back instead of a dead end",async()=>{
  // The default configuration: no verified owner, so the revision is refused.
  const h=setup();h.open();h.respond=async()=>{throw already(1);};await h.submit();
  h.respond=async()=>{throw Object.assign(Error("Revisions require a verified owner or administrator."),{status:403,not_saved:true});};
  await h.click("Submit as a revision");
  assert.equal(h.controller.hasPending,false);assert.ok(h.statusLines().includes("Revisions require a verified owner or administrator."));
  assert.equal(question(h),undefined);assert.equal(h.visible(h.send()),true);assert.equal(h.send().textContent,"Submit process");
  assert.equal(h.controller.processId,null,"A refused revision does not bind this tab to the process");
  h.respond=async()=>{throw already(1);};await h.submit();
  assert.ok(question(h),"Submitting again asks again; nothing is filed as a new process unasked");
  assert.equal(h.calls[2].payload.process_id,undefined);assert.equal("separate_process" in h.calls[2].payload,false);
  h.respond=async()=>receipt(1,9);await h.click("Submit as a separate process");
  assert.equal(h.calls[3].payload.separate_process,true);assert.match(h.text(),/Process submitted/);
});

await check("the question respects the capture gate and a malformed conflict is an ordinary refusal",async()=>{
  const h=setup();h.open();h.respond=async()=>{throw already(1);};await h.submit();
  h.gate={waiting:"Notes and the working map are still updating for your latest answer.",action:"",missing:[]};h.controller.captureChanged();
  await h.button("Submit as a revision").dispatch("click");await settle();
  assert.equal(h.calls.length,1,"Nothing is filed while capture work is running");
  for(const broken of [{process_id:"not-an-id",revision:1},{process_id:uuid(2),revision:0},{process_id:uuid(2),revision:"1"}]){
    const odd=setup();odd.open();odd.respond=async()=>{throw Object.assign(Error("This interview was already submitted."),{status:409,code:"interview_already_submitted",...broken});};
    await odd.submit();
    assert.equal(question(odd),undefined);assert.ok(odd.statusLines().includes("This interview was already submitted."));assert.equal(odd.visible(odd.send()),true);
  }
  // Closed while the request was on its way: the page says what to do.
  const closed=setup(),pending=deferred();closed.open();closed.respond=()=>pending.promise;
  const sending=closed.submit();await settle();closed.dialog.close();pending.reject(already(2));await sending;await settle();
  assert.deepEqual(closed.notices,[{message:"This interview was already submitted as revision 2. Open More options > Submit process to choose how to file it.",error:true}]);
});

await check("saving an uncertain attempt restores its original body and key in a fresh interview",async()=>{
  const original=await uncertain({documents:{scope:null,documents:[]}});const record=JSON.parse(JSON.stringify(original.controller.exportAttempt()));
  assert.equal(record.payload.submission_key,original.calls[0].payload.submission_key);
  original.state.turns.push({id:"later",role:"user",text:"Added after the submission."});
  const reopened=setup(original.state);
  reopened.controller.restore(null,null,null,record,reopened.state.interview_id);reopened.open();
  assert.equal(reopened.calls.length,0);assert.equal(reopened.send().textContent,"Recover previous submission");
  record.payload.team="A subsequent edit";await reopened.submit();
  assert.deepEqual(reopened.calls[0].payload,original.calls[0].payload);
  assert.equal(reopened.controller.exportAttempt(),null);
  for(const changed of [{interview_id:uuid(901)},{status_token:"private receipt"},{unsent_answer:"unfiled"},
      {documents:{scope:"allowed",documents:[{id:"id",excerpt:"Private excerpt"}]}},{submission_key:"malformed"}]){
    const unsafe={...record,payload:{...record.payload,...changed}};
    reopened.controller.restore(null,null,null,unsafe,reopened.state.interview_id);
    assert.equal(reopened.controller.hasPending,false);
  }
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
