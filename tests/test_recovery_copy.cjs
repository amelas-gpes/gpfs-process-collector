"use strict";
// The optional recovery copy, the "last saved" cue and Ctrl+S, in the page.
// Off (the default) the page must behave as before: no request, no timer, nothing
// kept. On, the unsaved interview is sent to the LOCAL server a moment after each
// change, is offered again at the next start through the Open saved interview checks,
// and is deleted after a confirmed Save copy, a confirmed replacement or Discard.
// The real app.js runs behind a stub DOM. The local server is a scripted stand-in with
// the same answers as server.py's recovery routes. Time is a test clock. No browser,
// provider, network, file or real timer is used.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const appSource=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const flush=async()=>{for(let i=0;i<60;i++)await Promise.resolve();};
// The single-line bindings under test, taken from initEvents() as they are written.
const wanted={
  saveCopy:/\$\("export-session"\)\.addEventListener\("click"/,
  leave:/window\.addEventListener\("beforeunload"/,
  startOver:/\$\("reset-session"\)\.addEventListener\("click"/,
  shortcut:/document\.addEventListener\("keydown".*exportSession\(\)/,
  restore:/\$\("recovery-restore"\)\??\.addEventListener\("click"/,
  discard:/\$\("recovery-discard"\)\??\.addEventListener\("click"/,
  setting:/\$\("recovery-enabled"\)\??\.addEventListener\("change"/,
  hidden:/document\.addEventListener\("visibilitychange".*writeRecoveryCopy/,
  reminder:/window\.setInterval\?\.\(/
};
const lines=appSource.split("\n"),bindings=[];
for(const [name,pattern] of Object.entries(wanted)){
  const found=lines.filter(line=>pattern.test(line));
  assert.equal(found.length,1,`app.js must bind "${name}" on one line (found ${found.length})`);
  bindings.push(found[0]);
}
const START=Date.UTC(2026,10,13,14,32,5);
const ID=/^[0-9a-f]{32}$/;
const OTHER="d".repeat(32);

// The local server's recovery routes, as server.py answers them.
function standInServer(initial={}) {
  const api={enabled:Boolean(initial.enabled),draft:initial.draft||null,down:false,calls:[],clock:null};
  const summary=()=>api.draft&&{id:api.draft.id,saved_at:api.draft.saved_at,readable:api.draft.readable!==false,
    process_name:api.draft.readable===false?"":(api.draft.session.process_name_manual!==true&&api.draft.session.derived_process_title)||api.draft.session.context.process_name||"",
    messages:api.draft.readable===false?0:api.draft.session.turns.filter(turn=>turn.document_event!==true).length};
  const reply=(status,value)=>({ok:status<400,status,json:async()=>value});
  api.fetch=async(url,options={})=>{
    const call={url,method:options.method,headers:options.headers||{},credentials:options.credentials,body:options.body===undefined?undefined:JSON.parse(options.body)};
    api.calls.push(call);
    assert.ok(url.startsWith("/api/recovery/"),"Only the local recovery routes may be contacted, not "+url);
    assert.equal(call.method,"POST");assert.equal(call.credentials,"same-origin");
    assert.equal(call.headers["X-CSRF-Token"],"synthetic-token");assert.equal(call.headers["Content-Type"],"application/json");
    if(api.down)throw new TypeError("Failed to fetch");
    const action=url.slice("/api/recovery/".length),body=call.body;
    if(action==="status")return reply(200,{enabled:api.enabled,draft:summary()});
    if(action==="setting"){api.enabled=body.enabled===true;if(!api.enabled)api.draft=null;return reply(200,{enabled:api.enabled,draft:summary()});}
    if(action==="save"){
      if(!api.enabled)return reply(409,{error:"Recovery copies are turned off in Settings. Nothing was stored.",enabled:false});
      if(api.draft&&api.draft.id!==body.id)return reply(409,{error:"A different recovery copy is stored on this computer. It was left as it is.",draft:summary()});
      api.draft={id:body.id,saved_at:new Date(api.clock.now).toISOString().replace(/\.\d+Z$/,"Z"),session:JSON.parse(JSON.stringify(body.session))};
      return reply(200,{id:body.id,saved_at:api.draft.saved_at});
    }
    if(action==="load"){
      if(!api.draft)return reply(404,{error:"No recovery copy is stored on this computer."});
      if(api.draft.readable===false||(body.id!==undefined&&body.id!==api.draft.id))return reply(409,{error:"A different recovery copy is stored on this computer. It was left as it is.",draft:summary()});
      return reply(200,{draft:{id:api.draft.id,saved_at:api.draft.saved_at,session:JSON.parse(JSON.stringify(api.draft.session))}});
    }
    if(action==="discard"){if(api.draft&&api.draft.id===body.id)api.draft=null;return reply(200,{enabled:api.enabled,draft:summary()});}
    return reply(404,{error:"Not found."});
  };
  api.sent=action=>api.calls.filter(call=>call.url==="/api/recovery/"+action);
  return api;
}

// recoveryConfig: what /api/config reports under "recovery" (undefined: an older server that reports nothing).
async function setup({recoveryConfig,server={},start=true}={}) {
  const clock={now:START,serial:0,timers:new Map()};
  class TestDate extends Date{constructor(...args){if(args.length)super(...args);else super(clock.now);}static now(){return clock.now;}}
  const api=standInServer(server);api.clock=clock;
  const nodes=new Map(),notices=[],confirms=[],prompt={answer:true},downloads=[],intervals=[],listeners={document:{},window:{}};
  let serial=0,uuid=0;
  function node(id){
    if(!nodes.has(id)){
      const handlers={},classes=new Set();
      nodes.set(id,{id,hidden:false,checked:false,disabled:false,value:"",textContent:"",className:"",open:false,dataset:{},children:[],style:{},
        classList:{toggle(name,on){if(on)classes.add(name);else classes.delete(name);},add(name){classes.add(name);},remove(name){classes.delete(name);},contains:name=>classes.has(name)},
        setAttribute(){},removeAttribute(){},getAttribute(){return null;},focus(){documentStub.activeElement=this;},close(){},showModal(){},remove(){},scrollIntoView(){},setSelectionRange(){},
        contains(){return false;},get firstElementChild(){return node(id+"-first");},
        querySelector(){return node(id+"-child");},querySelectorAll(){return[];},
        append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},
        addEventListener(type,fn){(handlers[type]??=[]).push(fn);},
        dispatch(type,event={}){for(const fn of handlers[type]||[])fn({target:this,preventDefault(){},...event});}});
    }
    return nodes.get(id);
  }
  const documentStub={body:node("body"),activeElement:null,visibilityState:"visible",getElementById:node,querySelectorAll:()=>[],querySelector:()=>null,
    createElement:tag=>node("created-"+tag+"-"+(++serial)),addEventListener(type,fn){(listeners.document[type]??=[]).push(fn);}};
  const window={speechSynthesis:{cancel(){}},SpeechSynthesisUtterance:class{},removeEventListener(){},
    addEventListener(type,fn){(listeners.window[type]??=[]).push(fn);},setInterval:(fn,ms)=>{intervals.push({fn,ms});return intervals.length;},
    __notices:notices,__downloads:downloads};
  const context={window,console,Blob,Date:TestDate,JSON,TextEncoder,AbortController,DOMException,document:documentStub,
    confirm:message=>{confirms.push(String(message));return prompt.answer;},
    crypto:{randomUUID:()=>"00000000-0000-4000-8000-"+String(++uuid).padStart(12,"0")},
    setTimeout:(fn,ms)=>{const id=++clock.serial;clock.timers.set(id,{fn,ms:Number(ms)||0,due:clock.now+(Number(ms)||0)});return id;},
    clearTimeout:id=>{clock.timers.delete(id);},requestAnimationFrame:()=>++serial,cancelAnimationFrame(){},
    fetch:(url,options)=>api.fetch(url,options)};
  const seam=`
    renderTranscript=()=>{};renderDraft=()=>{};renderWorkingMap=()=>{};renderCoverage=()=>{};scrollConversation=()=>{};
    updateConversationControls=()=>{};updateDocumentIntakeUI=()=>{};scheduleWorkflow=()=>{};stopSpeaking=()=>{};tab=()=>{};
    selectConversationView=view=>{conversationUI.view=view;};
    notice=(message,error)=>window.__notices.push({message,error:Boolean(error)});
    download=(...args)=>window.__downloads.push(args);
    ${bindings.join("\n")}
    window.__recovery={state,recovery,initRecovery,sessionObject,importSession,clearState,canReplaceSession,updateSaveHint,loadExample};
  })();`;
  const source=appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,seam);
  assert.notEqual(source,appSource,"Install the test seam only at application initialization");
  vm.createContext(context);vm.runInContext(source,context,{filename:"app.js"});
  const t=window.__recovery;
  t.state.config={api_configured:true,csrf_token:"synthetic-token",...(recoveryConfig===undefined?{}:{recovery:recoveryConfig})};
  if(start){
    // An interview in progress, with nothing unsaved yet.
    t.state.started=true;t.state.context={process_name:"Fee billing",process_owner:"Billing lead",objective:"Understand the work",background:""};
    node("process-name").value="Fee billing";node("process-owner").value="Billing lead";node("objective").value="Understand the work";
    t.state.turns=[{id:"t001",role:"assistant",text:"What happens on a Friday?"},{id:"t002",role:"user",text:"Every Friday I reconcile the fee ledger."}];
  }
  await t.initRecovery(t.state.config);await flush();
  const h={t,state:t.state,recovery:t.recovery,api,node,window,document:documentStub,notices,confirms,downloads,intervals,clock,listeners,
    get hint(){return node("save-hint").hidden?null:node("save-hint").textContent;},
    get offer(){return node("recovery-offer").hidden?null:node("recovery-offer-text").textContent;},
    set answer(value){prompt.answer=value;},
    change(text){if(text!==undefined)node("answer-text").value=text;t.state.dirty=true;t.updateSaveHint();},
    // Moves the clock and runs every timer that falls due, in order, as a browser would.
    async advance(ms){
      const end=clock.now+ms;
      for(;;){
        const due=[...clock.timers.entries()].filter(([,timer])=>timer.due<=end).sort((a,b)=>a[1].due-b[1].due)[0];
        if(!due)break;
        clock.timers.delete(due[0]);clock.now=Math.max(clock.now,due[1].due);due[1].fn();await flush();
      }
      clock.now=end;await flush();
    },
    tick(){for(const interval of intervals)interval.fn();},
    key(event){const sent={prevented:0,preventDefault(){this.prevented++;},...event};for(const fn of listeners.document.keydown||[])fn(sent);return sent;},
    visibility(value){documentStub.visibilityState=value;for(const fn of listeners.document.visibilitychange||[])fn({});},
    leavesWithoutAsking(){const event={defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};for(const fn of listeners.window.beforeunload||[])fn(event);return !event.defaultPrevented;},
    // A stand-in for the system Save dialog that writes the chosen file at once.
    saveDialog(){const files=[];window.showSaveFilePicker=async()=>{const file={contents:null};files.push(file);return {createWritable:async()=>{let pending="";return {write:async data=>{pending+=data;},close:async()=>{file.contents=pending;},abort:async()=>{}};}};};return files;},
    time:(at=clock.now)=>new Date(at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})};
  return h;
}
const file=value=>{const raw=typeof value==="string"?value:JSON.stringify(value);return {size:raw.length,text:async()=>raw};};
const comparable=session=>({...session,saved_at:null});
// An interview as another session of the app left it: four turns and a half-typed answer.
async function leftBehind() {
  const donor=await setup();
  donor.state.turns.push({id:"t003",role:"assistant",text:"Who checks the result?"},{id:"t004",role:"user",text:"The billing lead signs the reconciliation."});
  donor.node("answer-text").value="Then I email the";
  return {id:OTHER,saved_at:"2026-11-13T09:15:00Z",session:JSON.parse(JSON.stringify(donor.t.sessionObject({includePresentation:true})))};
}

// The real init() behind the smallest DOM, as tests/test_startup_notice.cjs opens the page:
// what the page asks the local server when it opens.
async function openPage(recoveryConfig,statusReply) {
  const nodes=new Map(),requests=[];
  const element=id=>{const classes=new Set(),parts=new Map();return {id,hidden:false,textContent:"",value:"",checked:false,dataset:{},
    classList:{toggle:(name,on)=>{if(on)classes.add(name);else classes.delete(name);return on;},contains:name=>classes.has(name)},
    querySelector(selector){if(!parts.has(selector))parts.set(selector,element(id+" "+selector));return parts.get(selector);},contains:()=>false,addEventListener(){}};};
  const node=id=>{if(!nodes.has(id))nodes.set(id,element(id));return nodes.get(id);};
  for(const id of ["global-notice","interview-error","review-error","review-view","connection-state","recovery-offer","recovery-setting"])node(id).hidden=true;
  const scope={console,window:{},document:{getElementById:node,activeElement:null,addEventListener(){}},crypto:{randomUUID:()=>"00000000-0000-4000-8000-000000000001"},
    fetch:async(url,options)=>{
      requests.push(url);
      if(url==="/api/config")return {ok:true,json:async()=>({csrf_token:"synthetic-token",data_notice:"Synthetic notice.",api_configured:true,...(recoveryConfig===undefined?{}:{recovery:recoveryConfig})})};
      assert.equal(options.headers["X-CSRF-Token"],"synthetic-token");
      return {ok:true,status:200,json:async()=>statusReply};
    },
    setTimeout:()=>0,clearTimeout(){},AbortController};
  const hook=`
    initEvents=()=>{};renderCoverage=()=>{};updateControls=()=>{};refreshVoices=()=>{};populateVoiceOptions=()=>{};
    createDocumentIntake=()=>null;
    window.startupTest={init,state,recovery};
  })();`;
  vm.createContext(scope);vm.runInContext(appSource.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook),scope,{filename:"app.js"});
  await scope.window.startupTest.init();await flush();
  return {requests,node,recovery:scope.window.startupTest.recovery,noticeHidden:node("global-notice").hidden};
}

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
await check("opening the page asks about a recovery copy only when the option is on or a copy is stored",async()=>{
  for(const recoveryConfig of [undefined,{enabled:false,stored:false}]){
    const page=await openPage(recoveryConfig,{enabled:true,draft:null});
    assert.deepEqual(page.requests,["/api/config"],"With the option off the page opens exactly as before");
    assert.equal(page.recovery.enabled,false);assert.equal(page.node("recovery-enabled").checked,false);
    assert.equal(page.node("recovery-setting").hidden,recoveryConfig===undefined);
    assert.equal(page.node("recovery-offer").hidden,true);assert.equal(page.noticeHidden,true);
  }
  const on=await openPage({enabled:true,stored:false},{enabled:true,draft:null});
  assert.deepEqual(on.requests,["/api/config","/api/recovery/status"]);
  assert.equal(on.recovery.enabled,true);assert.equal(on.node("recovery-enabled").checked,true);
  assert.equal(on.node("recovery-setting").hidden,false);assert.equal(on.node("recovery-offer").hidden,true);assert.equal(on.noticeHidden,true);
  const stored={id:OTHER,saved_at:"2026-11-13T09:15:00Z",process_name:"Fee billing",messages:41,readable:true};
  for(const recoveryConfig of [{enabled:true,stored:true},{enabled:false,stored:true}]){
    const page=await openPage(recoveryConfig,{enabled:recoveryConfig.enabled,draft:stored});
    assert.deepEqual(page.requests,["/api/config","/api/recovery/status"]);
    assert.equal(page.node("recovery-offer").hidden,false);
    assert.match(page.node("recovery-offer-text").textContent,/\(Fee billing, 41 messages\) is stored on this computer\./);
    assert.equal(page.noticeHidden,true,"The offer is a banner, not an error");
  }
  // A description that is not in the expected shape is not shown.
  for(const draft of ["text",{id:""},{id:7,saved_at:"2026-11-13T09:15:00Z"},{id:"x".repeat(81)}]){
    const page=await openPage({enabled:true,stored:true},{enabled:true,draft});
    assert.equal(page.node("recovery-offer").hidden,true,JSON.stringify(draft).slice(0,40));
  }
});

await check("off by default: a change makes no request and starts no timer",async()=>{
  for(const recoveryConfig of [undefined,{enabled:false,stored:false}]){
    const h=await setup({recoveryConfig});
    assert.equal(h.api.calls.length,0,"Opening the page asks the recovery routes nothing while the option is off");
    h.change("A half-typed answer");h.change("A half-typed answer, longer");await h.advance(60000);
    assert.equal(h.api.calls.length,0);assert.equal(h.clock.timers.size,0,"No timer runs for a copy nobody asked for");
    assert.equal(h.recovery.enabled,false);assert.equal(h.offer,null);
    assert.equal(h.leavesWithoutAsking(),false,"The leave question is unchanged");
    // The setting is shown, unchecked, only when the server offers it.
    assert.equal(h.node("recovery-setting").hidden,recoveryConfig===undefined);assert.equal(h.node("recovery-enabled").checked,false);
    h.visibility("hidden");await flush();assert.equal(h.api.calls.length,0);
  }
});

await check("off: the cue says how old the unsaved work is and what is known about a saved file",async()=>{
  const h=await setup();
  assert.equal(h.hint,null);
  h.change("A half-typed answer");
  assert.equal(h.hint,"Unsaved changes");
  assert.deepEqual(h.intervals.map(interval=>interval.ms),[30000],"One slow timer refreshes the cue; it does nothing while nothing is unsaved");
  h.clock.now+=4*60000;h.tick();assert.equal(h.hint,"Unsaved changes");
  h.clock.now+=8*60000;h.tick();assert.equal(h.hint,"Unsaved for 10 min · never saved");
  h.clock.now+=55*60000;h.tick();assert.equal(h.hint,"Unsaved for 1 h 5 min · never saved");
  // A confirmed Save copy clears the cue; the next change counts from that save.
  const files=h.saveDialog();h.node("export-session").dispatch("click");await flush();
  assert.equal(files.length,1);assert.equal(JSON.parse(files[0].contents).turns.length,2);
  assert.equal(h.state.dirty,false);assert.equal(h.hint,null);
  h.tick();assert.equal(h.hint,null);
  h.clock.now+=60000;h.change("One more detail");
  assert.equal(h.hint,"Unsaved changes · last saved less than 5 min ago");
  h.clock.now+=6*60000;h.tick();assert.equal(h.hint,"Unsaved changes · last saved 5 min ago");
  h.clock.now+=60*60000;h.tick();assert.equal(h.hint,"Unsaved changes · last saved 1 h 5 min ago");
  assert.equal(h.api.calls.length,0);
});

await check("off: an opened file and an unconfirmed download are named for what they are",async()=>{
  const donor=await setup(),saved=donor.t.sessionObject({includePresentation:true});
  const h=await setup();
  await h.t.importSession(file(saved));await flush();
  assert.equal(h.state.dirty,false);assert.equal(h.hint,null);
  h.clock.now+=12*60000;h.change("A new detail");
  assert.equal(h.hint,"Unsaved changes · file opened 10 min ago");
  // A download cannot be confirmed: its time is shown, and after the next change it is only "last download".
  const plain=await setup();plain.change("Typed");plain.node("export-session").dispatch("click");await flush();
  assert.equal(plain.downloads.length,1);assert.equal(plain.hint,`Last copy downloaded ${plain.time()}`);
  const downloadedAt=plain.clock.now;plain.clock.now+=3*60000;plain.change("Typed more");
  assert.equal(plain.hint,`Unsaved changes · last download ${plain.time(downloadedAt)}`);
  // Starting over forgets the file: the next interview has never been saved.
  h.answer=true;h.node("reset-session").dispatch("click");await flush();h.change("New interview");
  assert.equal(h.hint,"Unsaved changes");
});

await check("on: a change is written once, a moment later, as Save copy would write it",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  assert.deepEqual(h.api.calls.map(call=>call.url),["/api/recovery/status"]);
  assert.equal(h.recovery.enabled,true);assert.equal(h.node("recovery-enabled").checked,true);assert.equal(h.offer,null);
  h.change("Then I em");h.change("Then I email the");
  assert.equal(h.clock.timers.size,1,"Several quick changes share one pending write");
  await h.advance(1999);assert.equal(h.api.sent("save").length,0);
  await h.advance(1);
  const saves=h.api.sent("save");assert.equal(saves.length,1);
  assert.match(saves[0].body.id,ID);
  assert.deepEqual(comparable(saves[0].body.session),comparable(JSON.parse(JSON.stringify(h.t.sessionObject({includePresentation:true})))),"The copy is the Save copy file");
  assert.equal(saves[0].body.session.unsent_answer,"Then I email the");assert.equal(saves[0].body.session.turns.length,2);assert.equal(saves[0].body.session.schema_version,1);
  assert.deepEqual(Object.keys(saves[0].body).sort(),["id","session"]);
  assert.equal(h.hint,"Unsaved changes · recovery copy kept");
  assert.equal(h.leavesWithoutAsking(),false,"A recovery copy is not a saved file: leaving still asks");
  assert.equal(h.state.dirty,true);
  await h.advance(60000);assert.equal(h.api.sent("save").length,1,"Nothing is written while nothing changes");
  // The next change updates the same copy.
  h.state.turns.push({id:"t003",role:"assistant",text:"Who checks the result?"});h.state.version++;h.change("");
  await h.advance(2000);
  assert.equal(h.api.sent("save").length,2);assert.equal(h.api.sent("save")[1].body.id,saves[0].body.id);assert.equal(h.api.draft.session.turns.length,3);
  assert.equal(h.notices.length,0,"Keeping the copy is silent");
  assert.ok(h.api.calls.every(call=>call.url.startsWith("/api/recovery/")));
});

await check("on: changes that never pause are still written within ten seconds",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  // Live captions: a change every 1.5 s, never the 2 s of quiet.
  for(let i=0;i<6;i++){h.change("caption "+i);await h.advance(1500);}
  assert.equal(h.api.sent("save").length,0,"Nine seconds in, the quiet moment has not come");
  h.change("caption 6");await h.advance(1000);
  assert.equal(h.api.sent("save").length,1,"The first unwritten change is at most ten seconds old");
  assert.equal(h.api.draft.session.unsent_answer,"caption 6");
  for(let i=7;i<20;i++){h.change("caption "+i);await h.advance(1500);}
  assert.ok(h.api.sent("save").length>=2);
});

await check("on: hiding the tab writes a pending change at once",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  h.visibility("hidden");await flush();assert.equal(h.api.sent("save").length,0,"Nothing pending, nothing written");
  h.visibility("visible");h.change("Half a sentence");
  h.visibility("visible");await flush();assert.equal(h.api.sent("save").length,0);
  h.visibility("hidden");await flush();
  assert.equal(h.api.sent("save").length,1);assert.equal(h.api.draft.session.unsent_answer,"Half a sentence");
  await h.advance(5000);assert.equal(h.api.sent("save").length,1,"The pending timer was used up");
});

await check("on: the fictional example is not copied",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true},start:false});
  h.t.loadExample();await flush();
  assert.equal(h.state.example,true);assert.ok(h.state.turns.length>20);
  h.change("Trying the example");await h.advance(15000);
  assert.equal(h.api.sent("save").length,0);assert.equal(h.api.draft,null);
  assert.equal(h.hint,"Unsaved changes","No recovery copy is claimed for the example");
});

await check("on: a confirmed Save copy deletes the copy, a download does not",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  h.change("Typed");await h.advance(2000);
  const id=h.api.draft.id;
  // No system Save dialog: a download starts, nothing is confirmed, the copy stays.
  h.node("export-session").dispatch("click");await flush();
  assert.equal(h.downloads.length,1);assert.equal(h.state.dirty,true);
  assert.equal(h.api.sent("discard").length,0);assert.equal(h.api.draft.id,id);
  // The system Save dialog confirms the file: the copy is deleted.
  const files=h.saveDialog();h.node("export-session").dispatch("click");await flush();
  assert.equal(files.length,1);assert.equal(h.state.dirty,false);
  assert.deepEqual(h.api.sent("discard").map(call=>call.body),[{id}]);assert.equal(h.api.draft,null);
  assert.equal(h.hint,null);assert.equal(h.leavesWithoutAsking(),true);
  await h.advance(15000);assert.equal(h.api.sent("save").length,1,"Nothing is written again until something changes");
  h.change("After the save");await h.advance(2000);
  assert.equal(h.api.sent("save").length,2);assert.equal(h.api.draft.id,id);
});

await check("on: a write still on its way when the file is saved cannot bring the copy back",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  const files=h.saveDialog();
  h.change("Typed");
  // The pending write fires and the Save dialog confirms in the same moment.
  const [timer]=[...h.clock.timers.values()];h.clock.timers.clear();timer.fn();
  h.node("export-session").dispatch("click");await flush();
  assert.equal(files.length,1);assert.equal(h.state.dirty,false);
  assert.deepEqual(h.api.calls.slice(1).map(call=>call.url),["/api/recovery/save","/api/recovery/discard"],"The delete follows the write, never the other way round");
  assert.equal(h.api.draft,null);
});

await check("on: Start over and opening another interview delete the copy of the one they replace",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  h.change("Typed");await h.advance(2000);
  const id=h.api.draft.id;
  h.answer=false;h.node("reset-session").dispatch("click");await flush();
  assert.equal(h.confirms.length,1);assert.equal(h.state.turns.length,2,"Declined: nothing changes");assert.equal(h.api.draft.id,id);assert.equal(h.api.sent("discard").length,0);
  h.answer=true;h.node("reset-session").dispatch("click");await flush();
  assert.equal(h.state.turns.length,0);assert.equal(h.state.dirty,false);
  assert.deepEqual(h.api.sent("discard").map(call=>call.body),[{id}]);assert.equal(h.api.draft,null);
  await h.advance(15000);assert.equal(h.api.sent("save").length,1);
  // The same when a saved file replaces the interview.
  const donor=await setup(),saved=donor.t.sessionObject({includePresentation:true});
  const other=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  other.change("Typed");await other.advance(2000);assert.ok(other.api.draft);
  other.answer=true;await other.t.importSession(file(saved));await flush();
  assert.equal(other.api.draft,null);assert.equal(other.state.dirty,false);
  await other.advance(15000);assert.equal(other.api.sent("save").length,1,"An opened file is already a file: no copy until it changes");
});

await check("on start a stored copy is offered, never applied or replaced without being asked",async()=>{
  const draft=await leftBehind();
  for(const recoveryConfig of [{enabled:true,stored:true},{enabled:false,stored:true}]){
    const h=await setup({recoveryConfig,server:{enabled:recoveryConfig.enabled,draft:JSON.parse(JSON.stringify(draft))},start:false});
    assert.deepEqual(h.api.calls.map(call=>call.url),["/api/recovery/status"]);
    assert.match(h.offer,/^An unsaved interview from .+ \(Fee billing, 4 messages\) is stored on this computer\./);
    assert.ok(h.offer.includes(h.time(Date.UTC(2026,10,13,9,15,0))),"The offer says when the copy was written: "+h.offer);
    assert.equal(h.node("recovery-restore").hidden,false);
    assert.equal(h.state.turns.length,0,"Nothing is restored until the person chooses");assert.equal(h.state.dirty,false);
    // A new interview started without choosing never replaces the stored copy.
    h.change("A different interview");await h.advance(30000);
    assert.equal(h.api.sent("save").length,0);assert.equal(h.api.draft.id,OTHER);assert.equal(h.api.draft.session.turns.length,4);
    if(recoveryConfig.enabled)assert.equal(h.hint,"Unsaved changes · recovery copy paused");
  }
});

await check("Restore opens the copy through the Open saved interview checks and leaves it unsaved",async()=>{
  const draft=await leftBehind();
  const h=await setup({recoveryConfig:{enabled:true,stored:true},server:{enabled:true,draft:JSON.parse(JSON.stringify(draft))},start:false});
  h.node("recovery-restore").dispatch("click");await flush();
  assert.deepEqual(h.api.sent("load").map(call=>call.body),[{id:OTHER}]);
  assert.deepEqual(h.state.turns.map(turn=>turn.id),["t001","t002","t003","t004"]);
  assert.equal(h.state.turns[3].text,"The billing lead signs the reconciliation.");
  assert.equal(h.node("answer-text").value,"Then I email the","The unsent answer comes back");
  assert.equal(h.state.context.process_name,"Fee billing");assert.equal(h.state.started,true);
  assert.equal(h.state.dirty,true,"Only the recovery copy holds it: still unsaved");assert.equal(h.leavesWithoutAsking(),false);
  assert.equal(h.offer,null);assert.equal(h.confirms.length,0,"Nothing unsaved was replaced, so nothing was asked");
  const said=h.notices.at(-1);assert.equal(said.error,false);
  assert.match(said.message,/restored from the recovery copy/i);assert.match(said.message,/Save copy/);assert.match(said.message,/provisional/);
  assert.equal(h.api.sent("discard").length,0,"Restoring does not delete the copy");assert.equal(h.api.draft.id,OTHER);
  // The restored interview goes on under the same copy.
  h.change("Then I email the controller");await h.advance(2000);
  assert.equal(h.api.sent("save").at(-1).body.id,OTHER);assert.equal(h.api.draft.session.unsent_answer,"Then I email the controller");
  assert.equal(h.hint,"Unsaved changes · recovery copy kept");
  // And a confirmed Save copy deletes it.
  const files=h.saveDialog();h.node("export-session").dispatch("click");await flush();
  assert.equal(JSON.parse(files[0].contents).turns.length,4);assert.equal(h.api.draft,null);
});

await check("Restore keeps the Open saved interview rule that saved statuses are provisional",async()=>{
  const donor=await setup({start:false});donor.t.loadExample();
  const session=JSON.parse(JSON.stringify(donor.t.sessionObject({includePresentation:true})));
  assert.ok(session.memo_findings.every(finding=>finding.status==="captured"));assert.equal(session.closure.confirmed,true);
  session.synthetic_example=false;
  const opened=await setup({start:false});await opened.t.importSession(file(session));await flush();
  const h=await setup({recoveryConfig:{enabled:true,stored:true},server:{enabled:true,draft:{id:OTHER,saved_at:"2026-11-13T09:15:00Z",session}},start:false});
  h.node("recovery-restore").dispatch("click");await flush();
  assert.equal(h.state.turns.length,26);assert.ok(h.state.draft);
  assert.ok(h.state.memo_findings.every(finding=>finding.status==="partial"),"No stored copy can establish a completed assessment");
  assert.equal(h.state.closure.confirmed,false);assert.equal(h.state.coverageNeedsReview,true);
  // Field for field what Open saved interview makes of the same file.
  for(const key of ["turns","memo_findings","coverage","draft","closure","summary","focus","context"])
    assert.deepEqual(JSON.parse(JSON.stringify(h.state[key])),JSON.parse(JSON.stringify(opened.state[key])),key);
});

await check("a copy that Open saved interview would refuse is refused the same way and replaces nothing",async()=>{
  const draft=await leftBehind();
  const broken={
    "another format":session=>{session.schema_version=2;},
    "a transcript export":session=>{session.format="ai-process-collector-transcript";},
    "a turn over the limit":session=>{session.turns[1].text="x".repeat(6001);},
    "a duplicate turn":session=>{session.turns[2].id="t001";},
    "too many turns":session=>{session.turns=Array.from({length:401},(_,i)=>({id:"t"+String(i+1).padStart(3,"0"),role:"user",text:"x"}));},
    "an oversized unsent answer":session=>{session.unsent_answer="x".repeat(18001);},
    "a damaged draft":session=>{session.draft={title:"Fee billing",steps:"not a list"};},
    "forged provenance":session=>{session.capture_provenance={method:"document_simulation",source_documents:[],participant_confirmed:true,process_owner_approved:true};}
  };
  for(const [label,damage] of Object.entries(broken)){
    const session=JSON.parse(JSON.stringify(draft.session));damage(session);
    const viaFile=await setup();await viaFile.t.importSession(file(session));await flush();
    const refusal=viaFile.notices.at(-1);
    assert.equal(refusal.error,true,label);assert.match(refusal.message,/^Couldn’t open that interview\. /,label);
    const h=await setup({recoveryConfig:{enabled:true,stored:true},server:{enabled:true,draft:{...draft,session}}});
    h.node("recovery-restore").dispatch("click");await flush();
    const said=h.notices.at(-1);
    assert.equal(said.error,true,label);
    assert.equal(said.message,refusal.message.replace("Couldn’t open that interview.","Couldn’t restore the recovery copy."),label+": the same check, the same reason");
    assert.deepEqual(h.state.turns.map(turn=>turn.id),["t001","t002"],label+": the open interview is untouched");assert.equal(h.state.dirty,false,label);
    assert.match(h.offer,/is stored on this computer/,label+": the copy is still offered, so it can be discarded");
    assert.equal(h.api.sent("discard").length,0,label);assert.equal(h.api.draft.id,OTHER,label);
  }
});

await check("Restore asks before it replaces unsaved work, and says so when the copy is gone",async()=>{
  const draft=await leftBehind();
  const h=await setup({recoveryConfig:{enabled:true,stored:true},server:{enabled:true,draft:JSON.parse(JSON.stringify(draft))}});
  h.change("Unsaved work in this window");
  h.answer=false;h.node("recovery-restore").dispatch("click");await flush();
  assert.equal(h.confirms.length,1);assert.match(h.confirms[0],/haven’t saved will be cleared/);
  assert.equal(h.api.sent("load").length,0);assert.equal(h.state.turns.length,2);assert.match(h.offer,/is stored on this computer/);
  // Deleted meanwhile (another window discarded it).
  h.api.draft=null;h.answer=true;h.node("recovery-restore").dispatch("click");await flush();
  assert.equal(h.state.turns.length,2,"Nothing was replaced");
  assert.equal(h.notices.at(-1).error,true);assert.match(h.notices.at(-1).message,/^Couldn’t restore the recovery copy\. /);
  assert.equal(h.offer,null,"A copy that no longer exists is no longer offered");
  // The interview in this window is now the one being copied.
  h.change("Unsaved work in this window, more");await h.advance(2000);
  assert.equal(h.api.sent("save").length,1);assert.notEqual(h.api.draft.id,OTHER);
});

await check("Discard asks first, deletes the copy, and the open interview is copied from then on",async()=>{
  const draft=await leftBehind();
  const h=await setup({recoveryConfig:{enabled:true,stored:true},server:{enabled:true,draft:JSON.parse(JSON.stringify(draft))}});
  h.answer=false;h.node("recovery-discard").dispatch("click");await flush();
  assert.equal(h.confirms.length,1);assert.match(h.confirms[0],/Delete the recovery copy/);assert.match(h.confirms[0],/cannot be brought back/);
  assert.equal(h.api.sent("discard").length,0);assert.equal(h.api.draft.id,OTHER);assert.match(h.offer,/is stored on this computer/);
  h.answer=true;h.node("recovery-discard").dispatch("click");await flush();
  assert.deepEqual(h.api.sent("discard").map(call=>call.body),[{id:OTHER}]);assert.equal(h.api.draft,null);assert.equal(h.offer,null);
  assert.equal(h.notices.at(-1).message,"Recovery copy deleted.");assert.equal(h.state.turns.length,2);
  h.change("Typed");await h.advance(2000);
  assert.equal(h.api.sent("save").length,1);assert.match(h.api.draft.id,ID);assert.notEqual(h.api.draft.id,OTHER);
});

await check("a copy this version cannot read can only be discarded",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:true},server:{enabled:true,draft:{id:"unreadable-0123456789abcdef01234567",saved_at:"2026-11-13T09:15:00Z",readable:false}}});
  assert.match(h.offer,/cannot read it/);assert.equal(h.node("recovery-restore").hidden,true);
  h.node("recovery-restore").dispatch("click");await flush();assert.equal(h.api.sent("load").length,0);
  h.change("Typed");await h.advance(15000);assert.equal(h.api.sent("save").length,0);
  h.answer=true;h.node("recovery-discard").dispatch("click");await flush();
  assert.equal(h.api.draft,null);assert.equal(h.offer,null);
});

await check("another window's copy is never overwritten: it is offered instead",async()=>{
  const draft=await leftBehind();
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  assert.equal(h.offer,null);
  h.api.draft=JSON.parse(JSON.stringify(draft));   // written through the other server after this page opened
  h.change("Typed here");await h.advance(2000);
  assert.equal(h.api.sent("save").length,1);assert.equal(h.api.draft.id,OTHER,"The stored copy is left as it is");
  assert.match(h.offer,/\(Fee billing, 4 messages\) is stored on this computer/);
  assert.equal(h.hint,"Unsaved changes · recovery copy paused");
  h.change("Typed here, more");await h.advance(30000);
  assert.equal(h.api.sent("save").length,1,"No further attempt while the choice is open");
  assert.equal(h.notices.filter(item=>item.error).length,0);
});

await check("the setting is the person's choice; turning it off deletes the copy after asking",async()=>{
  const h=await setup({recoveryConfig:{enabled:false,stored:false}});
  const box=h.node("recovery-enabled");
  h.change("Typed before the option was on");
  box.checked=true;box.dispatch("change");await flush();
  assert.deepEqual(h.api.calls.map(call=>[call.url,call.body]),[["/api/recovery/setting",{enabled:true}]]);
  assert.equal(h.recovery.enabled,true);assert.equal(box.checked,true);assert.equal(h.confirms.length,0);
  assert.match(h.notices.at(-1).message,/^Recovery copy on\./);assert.match(h.notices.at(-1).message,/seven days/);
  await h.advance(2000);
  assert.equal(h.api.sent("save").length,1,"What was already unsaved is copied once the option is on");
  assert.equal(h.api.draft.session.unsent_answer,"Typed before the option was on");
  assert.match(h.node("recovery-status").textContent,/A copy of this interview is stored/);
  // Off: asked first, because a copy is deleted.
  h.answer=false;box.checked=false;box.dispatch("change");await flush();
  assert.equal(h.confirms.length,1);assert.match(h.confirms[0],/will be deleted/);
  assert.equal(h.api.sent("setting").length,1);assert.equal(box.checked,true,"Declined: the option stays on");assert.ok(h.api.draft);
  h.answer=true;box.checked=false;box.dispatch("change");await flush();
  assert.deepEqual(h.api.sent("setting").at(-1).body,{enabled:false});
  assert.equal(h.api.draft,null);assert.equal(h.recovery.enabled,false);assert.equal(box.checked,false);
  assert.match(h.notices.at(-1).message,/^Recovery copy off\./);
  const before=h.api.calls.length;
  h.change("Typed after the option was turned off");await h.advance(60000);
  assert.equal(h.api.calls.length,before,"Off again: no request");assert.equal(h.clock.timers.size,0);
  assert.equal(h.hint,"Unsaved changes");
  // A server that cannot store the choice leaves the switch where it was and says so.
  const failing=await setup({recoveryConfig:{enabled:false,stored:false}});
  failing.api.down=true;failing.node("recovery-enabled").checked=true;failing.node("recovery-enabled").dispatch("change");await flush();
  assert.equal(failing.recovery.enabled,false);assert.equal(failing.node("recovery-enabled").checked,false);assert.equal(failing.notices.at(-1).error,true);
});

await check("a copy that cannot be written is said once, never claimed, and tried again",async()=>{
  const h=await setup({recoveryConfig:{enabled:true,stored:false},server:{enabled:true}});
  h.api.down=true;h.change("Typed");await h.advance(2000);
  assert.equal(h.api.sent("save").length,1);assert.equal(h.api.draft,null);
  assert.equal(h.notices.length,1);assert.equal(h.notices[0].error,true);assert.match(h.notices[0].message,/recovery copy/i);assert.match(h.notices[0].message,/Save copy/);
  assert.equal(h.hint,"Unsaved changes · recovery copy not updated");assert.equal(h.leavesWithoutAsking(),false);
  await h.advance(10000);
  assert.equal(h.api.sent("save").length,2,"It is tried again without waiting for another change");assert.equal(h.notices.length,1,"The failure is not repeated as a new notice");
  h.api.down=false;await h.advance(10000);
  assert.equal(h.api.sent("save").length,3);assert.equal(h.api.draft.session.unsent_answer,"Typed");
  assert.equal(h.hint,"Unsaved changes · recovery copy kept");
  // Turned off through the other window: this page stops and says so, without an error.
  h.api.enabled=false;h.api.draft=null;h.change("Typed more");await h.advance(2000);
  assert.equal(h.recovery.enabled,false);assert.equal(h.node("recovery-enabled").checked,false);
  assert.equal(h.notices.length,2);assert.equal(h.notices[1].error,false);assert.match(h.notices[1].message,/turned off/);assert.match(h.notices[1].message,/no longer/);
  assert.equal(h.hint,"Unsaved changes");
  const calls=h.api.calls.length;h.change("And more");await h.advance(30000);assert.equal(h.api.calls.length,calls);
  assert.equal(h.notices.length,2);
});

await check("Ctrl+S saves a copy of the interview instead of the browser saving the page",async()=>{
  const h=await setup();h.change("Typed");
  let event=h.key({key:"s",ctrlKey:true});await flush();
  assert.equal(event.prevented,1,"The browser's Save Page dialog must not open");assert.equal(h.downloads.length,1);
  assert.equal(h.downloads[0][1],"Fee-billing-session-20261113T143205Z.json");assert.equal(JSON.parse(h.downloads[0][0]).unsent_answer,"Typed");
  event=h.key({key:"S",metaKey:true});await flush();assert.equal(event.prevented,1);assert.equal(h.downloads.length,2);
  event=h.key({key:"s",ctrlKey:true,repeat:true});await flush();assert.equal(event.prevented,1);assert.equal(h.downloads.length,2,"A held key saves once");
  for(const other of [{key:"s"},{key:"s",ctrlKey:true,shiftKey:true},{key:"s",ctrlKey:true,altKey:true},{key:"a",ctrlKey:true},{key:"Enter",ctrlKey:true},{key:"Escape"}]){
    event=h.key(other);await flush();assert.equal(event.prevented,0,JSON.stringify(other));
  }
  assert.equal(h.downloads.length,2);
  // With the system Save dialog it is the confirmed save.
  const files=h.saveDialog();h.key({key:"s",ctrlKey:true});await flush();
  assert.equal(files.length,1);assert.equal(h.state.dirty,false);assert.equal(h.notices.at(-1).message,"Saved. Keep the file somewhere approved for company information.");
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,files_written:0,real_timers:0}));
})().catch(error=>{console.error(error);process.exit(1);});
