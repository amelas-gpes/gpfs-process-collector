"use strict";
// "Saved" is kept for the file that Save copy writes. An interview lives in the tab until then, so
// messages that reassure after a failure say the answers are "still here", add "Not saved yet — use
// Save copy." while no copy is current, and the Submit dialog says that submitting is not a copy.
// Real web/app.js and web/knowledge-ui.js behind synthetic DOMs. No browser, provider or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {setup,run,flush,deferred,response,approved,reviewAck}=require("./support/interview_page.cjs");
const web=name=>fs.readFileSync(path.join(__dirname,"..","web",name),"utf8");
const REMINDER=" Not saved yet — use Save copy.";
let passed=0;
const check=async(name,fn)=>{try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}};
const page=()=>setup({expose:"exportSession,updateSaveHint,unsavedReminder",seam:"window.__downloads=[];download=(...args)=>window.__downloads.push(args);"});
// A request that never answers, timed out by the app's own deadline.
async function timedOut(h){
  h.route((_url,options)=>new Promise((_,reject)=>options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")))));
  const failed=h.t.request("/api/transcribe",new Blob(["synthetic audio"])).then(()=>null,error=>error);
  await flush();await h.timer(150000);return failed;
}

// The knowledge dialog, as tests/test_submit_dialog.cjs builds it.
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
function dialog(extra={}){
  const nodes={};for(const id of ["knowledge-submit","knowledge-admin","submit-process-menu","submit-process-review","open-knowledge-admin","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  let keys=0;const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,
    setTimeout:()=>0,clearTimeout(){},crypto:{randomUUID:()=>`eeeeeeee-eeee-4eee-8eee-${String(++keys).padStart(12,"0")}`}};
  vm.runInNewContext(web("knowledge-ui.js"),env,{filename:"knowledge-ui.js"});
  const session={saved_at:"2026-11-13T00:00:00.000Z",context:{process_name:"Invoice intake"},turns:[{id:"u1",role:"user",text:"A supplier email starts a case."}],documents:null,
    workflow:{title:"Invoice intake",steps:[{id:"S1",title:"Receive invoice",evidence_turns:["u1"]}],connections:[]},draft:null,draft_stale:false,draft_edited:false,
    capture:{in_progress:false,notes_current:true,map_current:true,notes_through_turn:"u1",map_through_turn:"u1"}};
  const h={box:nodes["knowledge-submit"],submitted:0};
  h.controller=env.window.CollectorKnowledge.create({session:()=>structuredClone(session),notice(){},captureState:()=>({waiting:"",missing:[]}),draftStaleReason:()=>"answers",
    onSubmitted:()=>{h.submitted++;},request:async()=>({submission_id:uuid(1),process_id:uuid(2),revision:1,job_id:uuid(11),status:"pending",status_token:"a".repeat(64)}),...extra});
  h.open=()=>h.controller.openSubmit();
  h.submit=async()=>{await find(h.box,node=>node.tagName==="FORM").dispatch("submit");await settle();};
  h.button=label=>find(h.box,node=>node.tagName==="BUTTON"&&node.textContent===label);
  return h;
}

run(async()=>{
  await check("no message calls work that exists only in the tab saved or safe",async()=>{
    // What the app says about answers, transcripts, notes and the process after a failure. A sentence of
    // this shape with "saved" or "safe" in it is the defect; "still here" is the wording kept for it.
    const claim=/\b(?:answers?|transcript|conversation|capture|notes|process|interview|response)\s+(?:(?:is|are|remains?)\s+)?(?:saved|safe)\b|\bsaved\s+(?:here|locally|answers\s+are\s+retained)|\bsaves\s+the\s+interview\b/i;
    for(const name of ["app.js","controlled-voice.js","live-voice.js","concurrent-interview.js","document-intake.js"]){
      const strings=web(name).match(/"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g)||[];
      const found=strings.filter(value=>claim.test(value));
      assert.deepEqual(found,[],name+" still reassures with saved/safe");
    }
    // The rule is about the wording's shape, not these files' sentences: neighbouring phrasings are caught too.
    for(const sentence of ["Your answer is saved.","Earlier answers are saved; continue by typing.","Your conversation is safe.","Your process is safe — try again.","Your answers are saved here.","This saves the interview locally.","Your interview is saved locally.","Your transcript remains safe."])assert.match(sentence,claim,sentence);
    for(const sentence of ["Your answer is still here.","Nothing was lost — try again.","Saved. Keep the file somewhere approved for company information.","A copy was saved, but the interview has changed since.","Open saved interview…","Not saved yet — use Save copy."])assert.doesNotMatch(sentence,claim,sentence);
    const submitDialog=web("knowledge-ui.js");
    assert.doesNotMatch(submitDialog,/saves the interview locally|interview is saved locally/i);
  });

  await check("a failed turn says the answer is still here and that it is not saved yet",async()=>{
    const h=page();h.route(()=>response({error:"Synthetic provider outage."},503));h.node("answer-text").value="A paper invoice arrives by post.";
    await h.t.sendAnswer({preventDefault(){}});
    const said=h.notices.at(-1);assert.equal(said.error,true);
    assert.match(said.message,/^Your answer is still here, but the next question didn’t load\./);assert.match(said.message,/Synthetic provider outage\./);
    assert.ok(said.message.endsWith(REMINDER),said.message);assert.doesNotMatch(said.message.replace(REMINDER,""),/\bsaved\b|\bsafe\b/);
    assert.equal(h.t.state.dirty,true);assert.equal(h.t.state.turns.at(-1).text,"A paper invoice arrives by post.");
  });

  await check("the reminder follows what is known about a copy",async()=>{
    const h=page();
    // Nothing unsaved (a fresh page, or a file just written): no reminder.
    h.t.state.dirty=false;assert.equal(h.t.unsavedReminder(),"");
    // Unsaved work: the reminder is added.
    h.t.state.dirty=true;assert.equal(h.t.unsavedReminder(),REMINDER);
    // A download of exactly this state was started: the header says when, and the reminder is not repeated.
    const outcome=await h.t.exportSession();
    assert.equal(h.context.__downloads.length,1);assert.match(outcome,/^Download started\./,"Save copy reports its outcome to its caller");assert.equal(h.notices.at(-1).message,outcome);
    assert.equal(h.t.state.dirty,true);assert.match(h.node("save-hint").textContent,/^Last copy downloaded /);
    assert.equal(h.t.unsavedReminder(),"");
    // A newer answer makes that download out of date.
    h.t.state.turns.push({id:"t009",role:"user",text:"One more detail."});h.t.state.version++;h.t.state.dirty=true;
    assert.equal(h.t.unsavedReminder(),REMINDER);
  });

  await check("a request that runs out of time says nothing was lost, and the reminder is added once where it is shown",async()=>{
    const h=page();h.t.state.dirty=true;
    const error=await timedOut(h);
    assert.equal(error.message,"That took too long. Nothing was lost — try again.");assert.equal(error.transient,true);
    // The same failure for a typed answer: one sentence about the answer, the reason, one reminder.
    const slow=page();slow.route((_url,options)=>new Promise((_,reject)=>options.signal.addEventListener("abort",()=>reject(new DOMException("Aborted","AbortError")))));
    slow.node("answer-text").value="A paper invoice arrives by post.";const sending=slow.t.sendAnswer({preventDefault(){}});await flush();await slow.timer(330000);await sending;
    const said=slow.notices.at(-1).message;
    assert.equal(said,"Your answer is still here, but the next question didn’t load. Add more detail, or choose Try again. That took too long. Nothing was lost — try again."+REMINDER);
    assert.equal(said.split(REMINDER.trim()).length,2,"The reminder appears once");
  });

  await check("pausing a review does not call the answers saved",async()=>{
    const h=setup(),review=deferred();
    h.route(url=>url==="/api/agent-team/interview"?response(reviewAck()):url==="/api/agent-team/review"?review.promise:response({}));
    h.node("answer-text").value="That completes the remaining detail.";const sending=h.t.sendAnswer({preventDefault(){}});await flush();
    h.t.pauseCompletionReview();await flush();
    const said=h.notices.find(item=>/^Review paused\./.test(item.message));assert.ok(said);
    assert.equal(said.message,"Review paused. Your answers are still here. Add more detail, or choose Resume review when you’re ready."+REMINDER);
    review.resolve(response(approved()));await sending;
  });

  await check("the menu button carries the unsaved mark that a narrow layout otherwise hides",async()=>{
    const h=page(),toggle=h.node("session-menu-toggle"),item=h.node("export-session");
    h.t.state.dirty=true;h.t.updateSaveHint();
    assert.equal(toggle.classList.contains("has-unsaved"),true);assert.equal(toggle.getAttribute("aria-label"),"More options · unsaved changes");assert.equal(toggle.title,"More options · unsaved changes");
    assert.equal(item.classList.contains("has-unsaved"),true);assert.equal(h.node("save-hint").hidden,false);
    await h.t.exportSession();
    assert.equal(toggle.classList.contains("has-unsaved"),true,"A started download is not proof of a file");
    h.t.state.dirty=false;h.t.updateSaveHint();
    assert.equal(toggle.classList.contains("has-unsaved"),false);assert.equal(toggle.getAttribute("aria-label"),"More options");assert.equal(h.node("save-hint").hidden,true);
    const css=web("style.css"),narrow=css.slice(css.indexOf(".save-hint { max-width: 12ch;"));
    assert.match(narrow.slice(0,600),/#session-menu-toggle\.has-unsaved::after\s*\{[^}]*background:/,"The narrow layout draws the mark beside the compact header text");
  });

  await check("the Submit dialog says submitting is not a copy and offers Save copy",async()=>{
    let copies=0;const h=dialog({saveCopy:async()=>{copies++;return "Download started. Check that the file is in your Downloads folder.";}});
    h.open();
    assert.match(h.box.textContent,/files the interview in company knowledge on this computer/);assert.match(h.box.textContent,/use Save copy for that/);
    assert.doesNotMatch(h.box.textContent,/saves the interview|saved locally/i);assert.equal(h.button("Save copy"),undefined,"Before submitting, the dialog only points to Save copy");
    await h.submit();
    const text=h.box.textContent;assert.match(text,/Process submitted/);assert.equal(h.submitted,1);
    assert.match(text,/Submitted to company knowledge on this computer\. To reopen or continue this interview, and to keep the status access below, you still need Save copy\./);
    assert.doesNotMatch(text,/saved locally/i);
    assert.ok(text.indexOf("you still need Save copy")<text.indexOf("Submission status"),"Save copy is the lead sentence, before the receipt");
    const copy=h.button("Save copy");assert.ok(copy);
    await copy.dispatch("click");await settle();
    assert.equal(copies,1);assert.match(h.box.textContent,/Download started\. Check that the file is in your Downloads folder\./,"The outcome is shown inside the dialog");assert.equal(copy.disabled,false);
  });

  await check("a Save copy that fails from the dialog says where to try again",async()=>{
    const h=dialog({saveCopy:async()=>{throw Error("synthetic");}});h.open();await h.submit();
    await h.button("Save copy").dispatch("click");await settle();
    assert.match(h.box.textContent,/The copy could not be saved\. Choose Save copy in More options\./);assert.equal(h.button("Save copy").disabled,false);
  });

  await check("without a Save copy action the dialog still says a copy is needed",async()=>{
    const h=dialog();h.open();await h.submit();
    assert.match(h.box.textContent,/you still need Save copy/);assert.equal(h.button("Save copy"),undefined);
  });

  console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0}));
});
