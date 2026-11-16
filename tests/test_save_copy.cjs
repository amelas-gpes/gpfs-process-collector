"use strict";
// Save copy must not claim success, and must not drop the leave/replace guard,
// before a file is known to exist. The real exportSession, save cue, replace
// check and beforeunload binding run against a minimal DOM. The system Save
// dialog is a scripted stand-in. No browser, provider, file, download or
// network request is used.
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const app=fs.readFileSync(path.join(__dirname,"..","web","app.js"),"utf8");
const flush=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
const domError=name=>new DOMException(name==="AbortError"?"The user aborted a request.":"The request is not allowed.",name);
const bindings=app.split("\n").filter(line=>/\$\("export-session"\)\.addEventListener\("click"/.test(line)||/window\.addEventListener\("beforeunload"/.test(line)).join("\n");
assert.equal(bindings.split("\n").length,2,"The Save copy click binding and the beforeunload guard must be found in app.js");
let passed=0;

function harness() {
 // A fixed clock: the app reads Date.now() and new Date() from this class.
 const clock={now:Date.UTC(2026,10,13,14,32,5)};
 class TestDate extends Date{constructor(...args){if(args.length)super(...args);else super(clock.now);}static now(){return clock.now;}}
 const document={activeElement:null};
 class Element {
  constructor(id,parent=null){this.id=id;this.parentElement=parent;this.hidden=false;this.value="";this.textContent="";this.listeners={};this.attributes={};this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
  contains(node){for(let cursor=node;cursor;cursor=cursor.parentElement)if(cursor===this)return true;return false;}
  setAttribute(name,value){this.attributes[name]=String(value);}
  addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
  click(){for(const fn of this.listeners.click||[])fn({target:this});}
  focus(){document.activeElement=this;}
 }
 const nodes=new Map(),mount=(id,parent)=>{const node=new Element(id,parent);nodes.set(id,node);return node;};
 document.getElementById=id=>nodes.get(id)||null;
 const menu=mount("session-menu"),toggle=mount("session-menu-toggle"),hint=mount("save-hint"),button=mount("export-session",menu);
 for(const id of ["answer-text","process-name","process-owner","objective","background"])mount(id);
 hint.hidden=true;
 const downloads=[],notices=[],confirms=[],unload=[];
 const window={downloads,notices,addEventListener(name,fn){if(name==="beforeunload")unload.push(fn);}};
 const sandbox={console,document,window,setTimeout,clearTimeout,AbortController,TextEncoder,Date:TestDate,confirm:message=>{confirms.push(message);return false;}};
 const hook="  download=(...args)=>window.downloads.push(args); notice=(...args)=>window.notices.push(args); "+bindings+" window.saveTests={state,canReplaceSession,updateSaveHint};\n})();";
 const patched=app.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
 assert.notEqual(patched,app,"Install the test hook only at application initialization");
 vm.createContext(sandbox);vm.runInContext(patched,sandbox,{filename:"app.js"});
 const t=window.saveTests;
 // An interview with unsaved answers.
 t.state.context={process_name:"Supply order",process_owner:"Office manager",objective:"Understand the work",background:""};
 t.state.turns=[{id:"t001",role:"assistant",text:"What work would you like to walk through?"},{id:"t002",role:"user",text:"Every Monday I count the supply cupboard and list shortages."}];
 t.state.started=true;t.state.dirty=true;t.updateSaveHint();
 return {t,state:t.state,window,document,nodes,menu,toggle,hint,button,downloads,notices,confirms,clock,
  time:()=>new Date(clock.now).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}),
  saveCopy(){menu.hidden=false;button.focus();button.click();},
  // What desktop/NativeHost.cs asks before closing the window, and what a tab close asks.
  leavesWithoutAsking(){const event={defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};for(const fn of unload)fn(event);return !event.defaultPrevented;},
  // A stand-in for window.showSaveFilePicker whose outcome each test decides.
  picker(){const calls=[];let settle;window.showSaveFilePicker=options=>{calls.push(options);return new Promise((resolve,reject)=>{settle={resolve,reject};});};return {calls,choose:file=>settle.resolve(file),refuse:error=>settle.reject(error)};}};
}
// A chosen file. Like the browser's writer, nothing reaches the file before close() resolves.
function chosenFile(failAt=null) {
 const file={name:"Supply-order-session.json",contents:null,pending:"",aborted:0};
 file.createWritable=async()=>{
  if(failAt==="create")throw domError("NotAllowedError");
  return {write:async data=>{if(failAt==="write")throw domError("QuotaExceededError");file.pending+=data;},close:async()=>{if(failAt==="close")throw domError("AbortError");file.contents=file.pending;},
   abort:async()=>{file.aborted++;if(failAt==="close")throw new TypeError("The stream has already failed.");}};
 };
 return file;
}
async function check(name,fn) {try {await fn();passed++;} catch(error) {error.message=name+": "+error.message;throw error;}}
// Once a file of the interview is known, the unsaved cue names it (tests/test_recovery_copy.cjs covers the ages).
const SAVED_EARLIER="Unsaved changes · last saved less than 5 min ago";
const claimsSaved=notices=>notices.some(([message])=>/\bsaved\b/i.test(message));

(async()=>{
await check("a plain download never claims Saved and keeps the guard armed",async()=>{
 const h=harness();assert.equal(typeof h.window.showSaveFilePicker,"undefined");
 assert.equal(h.hint.textContent,"Unsaved changes");assert.equal(h.leavesWithoutAsking(),false);
 h.saveCopy();await flush();
 assert.equal(h.downloads.length,1);assert.match(h.downloads[0][1],/^Supply-order-session-\d{8}T\d{6}Z\.json$/);assert.equal(h.downloads[0][2],"application/json");
 assert.equal(JSON.parse(h.downloads[0][0]).turns.length,2);
 assert.equal(h.notices.length,1);assert.equal(claimsSaved(h.notices),false,"A started download is not a saved file");
 assert.match(h.notices[0][0],/^Download started\./);assert.match(h.notices[0][0],/Downloads folder/);assert.match(h.notices[0][0],/approved for company information/);
 assert.equal(h.state.dirty,true,"The unsaved state survives a download whose outcome is unknown");
 assert.equal(h.leavesWithoutAsking(),false,"Closing the tab or the desktop window still asks");
 assert.equal(h.hint.hidden,false);assert.equal(h.hint.textContent,`Last copy downloaded ${h.time()}`);
 // Narrow layouts hide the header cue (web/style.css), so this mark is the only unsaved cue there.
 assert.equal(h.button.classes.has("has-unsaved"),true,"The Save copy menu item stays marked while the download is unconfirmed");
 assert.equal(h.menu.hidden,true);assert.equal(h.document.activeElement,h.toggle,"Focus returns to the visible options control");
 assert.equal(h.t.canReplaceSession(),false);assert.equal(h.confirms.length,1,"Start over, Open and See an example still ask");
 assert.match(h.confirms[0],/haven’t saved will be cleared/);
 assert.ok(h.confirms[0].includes(`A copy was downloaded at ${h.time()}.`));assert.match(h.confirms[0],/Check that the file is in your Downloads folder/);
});

await check("an edit after the download brings Unsaved changes back",async()=>{
 const h=harness();h.saveCopy();await flush();
 assert.equal(h.hint.textContent,`Last copy downloaded ${h.time()}`);
 h.nodes.get("answer-text").value="One more detail";h.state.dirty=true;h.t.updateSaveHint();
 // No longer "Last copy downloaded": the download is named as what it is, an earlier unconfirmed copy.
 assert.equal(h.hint.textContent,`Unsaved changes · last download ${h.time()}`);assert.equal(h.hint.hidden,false);assert.equal(h.button.classes.has("has-unsaved"),true);
 assert.equal(h.t.canReplaceSession(),false);
 assert.ok(h.confirms[0].includes(`The copy downloaded at ${h.time()} does not include your latest changes.`));assert.match(h.confirms[0],/Save a copy first/);
 // A second download is described by its own time.
 h.clock.now+=5*60000;h.saveCopy();await flush();
 assert.equal(h.downloads.length,2);assert.equal(JSON.parse(h.downloads[1][0]).unsent_answer,"One more detail");
 assert.equal(h.hint.textContent,`Last copy downloaded ${h.time()}`);assert.equal(h.state.dirty,true);
 assert.equal(h.button.classes.has("has-unsaved"),true,"A newer download is still unconfirmed");
});

await check("the replace check keeps its wording when no copy was downloaded",async()=>{
 const h=harness();
 assert.equal(h.t.canReplaceSession(),false);
 assert.match(h.confirms[0],/Save a copy first if you want to keep it\.$/);assert.doesNotMatch(h.confirms[0],/download/i,"No download is mentioned when none was started");
});

await check("a download with nothing unsaved does not arm the guard",async()=>{
 const h=harness();h.state.dirty=false;h.t.updateSaveHint();
 h.saveCopy();await flush();
 assert.equal(h.downloads.length,1);assert.equal(claimsSaved(h.notices),false);
 assert.equal(h.state.dirty,false);assert.equal(h.hint.hidden,true);assert.equal(h.leavesWithoutAsking(),true);
 assert.equal(h.t.canReplaceSession(),true);assert.equal(h.confirms.length,0);
});

await check("with the system Save dialog nothing is claimed until the file is closed",async()=>{
 const h=harness(),picker=h.picker(),file=chosenFile();
 h.saveCopy();await flush();
 assert.equal(picker.calls.length,1,"Save copy opens the system Save dialog");
 assert.match(picker.calls[0].suggestedName,/^Supply-order-session-\d{8}T\d{6}Z\.json$/);assert.deepEqual(JSON.parse(JSON.stringify(picker.calls[0].types[0].accept)),{"application/json":[".json"]});
 assert.equal(h.menu.hidden,true,"The menu closes at once");assert.equal(h.document.activeElement,h.toggle);assert.equal(h.downloads.length,0);
 assert.equal(h.notices.length,0,"Nothing is announced while the dialog is open");assert.equal(h.state.dirty,true);assert.equal(h.hint.textContent,"Unsaved changes");assert.equal(h.leavesWithoutAsking(),false);
 h.clock.now+=4000;picker.choose(file);await flush();
 assert.equal(JSON.parse(file.contents).turns.length,2,"The written file is the restorable interview");assert.equal(JSON.parse(file.contents).schema_version,1);
 assert.equal(h.downloads.length,0);
 assert.deepEqual(h.notices.map(([message])=>message),["Saved. Keep the file somewhere approved for company information."]);
 assert.equal(h.state.dirty,false);assert.equal(h.hint.hidden,true);assert.equal(h.hint.textContent,"");assert.equal(h.button.classes.has("has-unsaved"),false);
 assert.equal(h.leavesWithoutAsking(),true);assert.equal(h.t.canReplaceSession(),true);assert.equal(h.confirms.length,0);
});

await check("Cancel in the system Save dialog changes nothing and says nothing",async()=>{
 const h=harness(),picker=h.picker();
 h.saveCopy();await flush();h.clock.now+=2500;picker.refuse(domError("AbortError"));await flush();
 assert.equal(h.notices.length,0,"A cancelled save is not announced, least of all as Saved");assert.equal(h.downloads.length,0,"Cancel must not start a download");
 assert.equal(h.state.dirty,true);assert.equal(h.hint.hidden,false);assert.equal(h.hint.textContent,"Unsaved changes");assert.equal(h.button.classes.has("has-unsaved"),true);
 assert.equal(h.leavesWithoutAsking(),false);assert.equal(h.t.canReplaceSession(),false);
 assert.match(h.confirms[0],/Save a copy first if you want to keep it\.$/);
});

await check("changes made while the Save dialog was open are not marked saved",async()=>{
 const changes={
  "an edit or a live-voice turn":h=>{h.state.turns.push({id:"t003",role:"user",text:"Then I email the order."});h.state.version++;h.state.dirty=true;},
  "unsent text":h=>{h.nodes.get("answer-text").value="Typed during the dialog";h.state.dirty=true;},
  "a new evidence version":h=>{h.state.version++;},
  "a replaced interview":h=>{h.state.generation++;}
 };
 for(const [label,change] of Object.entries(changes)){
  const h=harness(),picker=h.picker(),file=chosenFile();
  h.saveCopy();await flush();change(h);h.clock.now+=4000;picker.choose(file);await flush();
  assert.equal(JSON.parse(file.contents).turns.length,2,label+": the file holds the interview as it was when Save copy was chosen");
  assert.equal(h.state.dirty,true,label+": the unsaved state must survive");assert.equal(h.leavesWithoutAsking(),false,label);
  // The file that was written is an older copy of this interview; of a replaced interview nothing was saved.
  assert.equal(h.hint.textContent,label==="a replaced interview"?"Unsaved changes":SAVED_EARLIER,label);assert.equal(h.hint.hidden,false,label);
  assert.equal(h.notices.length,1,label);assert.match(h.notices[0][0],/^A copy was saved, but the interview has changed since\./,label);assert.match(h.notices[0][0],/Save copy again/,label);
  assert.equal(h.downloads.length,0,label);assert.equal(h.t.canReplaceSession(),false,label);
 }
});

await check("a location that cannot be written falls back to a download and says so",async()=>{
 for(const stage of ["create","write","close"]){
  const h=harness(),picker=h.picker(),file=chosenFile(stage);
  h.saveCopy();await flush();h.clock.now+=4000;picker.choose(file);await flush();
  assert.equal(file.contents,null,stage+": nothing reached the chosen file");assert.equal(file.aborted,stage==="create"?0:1,stage+": an unfinished write is released");
  assert.equal(h.downloads.length,1,stage+": the copy is offered as a download instead");assert.match(h.downloads[0][1],/^Supply-order-session-\d{8}T\d{6}Z\.json$/);
  assert.equal(h.notices.length,1,stage);assert.equal(claimsSaved(h.notices),false,stage+": no success is claimed");
  assert.match(h.notices[0][0],/couldn’t be written/,stage);assert.match(h.notices[0][0],/Downloads folder/,stage);assert.equal(h.notices[0][1],true,stage+": shown as a problem, not as a passing toast");
  assert.equal(h.state.dirty,true,stage);assert.equal(h.leavesWithoutAsking(),false,stage);assert.equal(h.hint.textContent,`Last copy downloaded ${h.time()}`,stage);
  assert.equal(h.button.classes.has("has-unsaved"),true,stage+": the menu item stays marked");
 }
});

await check("a Save dialog that cannot open falls back to the download",async()=>{
 // Chrome answers AbortError at once when dialogs are blocked by policy or none can open.
 const h=harness(),picker=h.picker();
 h.saveCopy();await flush();h.clock.now+=40;picker.refuse(domError("AbortError"));await flush();
 assert.equal(h.downloads.length,1,"Save copy must still produce a file when no dialog can open");
 assert.equal(claimsSaved(h.notices),false);assert.match(h.notices[0][0],/^Download started\./);
 assert.equal(h.state.dirty,true);assert.equal(h.leavesWithoutAsking(),false);
 // A dialog the browser refuses outright, synchronously or not.
 for(const refusal of [()=>{throw domError("SecurityError");},()=>Promise.reject(domError("NotAllowedError"))]){
  const other=harness();other.window.showSaveFilePicker=refusal;
  other.saveCopy();await flush();
  assert.equal(other.downloads.length,1);assert.equal(claimsSaved(other.notices),false);assert.match(other.notices[0][0],/^Download started\./);
  assert.equal(other.state.dirty,true);assert.equal(other.leavesWithoutAsking(),false);
 }
});

await check("a confirmed save replaces the earlier download's soft state",async()=>{
 const h=harness();h.saveCopy();await flush();
 assert.equal(h.hint.textContent,`Last copy downloaded ${h.time()}`);
 const picker=h.picker(),file=chosenFile();
 h.saveCopy();await flush();h.clock.now+=4000;picker.choose(file);await flush();
 assert.equal(h.state.dirty,false);assert.equal(h.hint.hidden,true);
 // The next edit is plainly unsaved: the old download no longer describes anything.
 h.state.dirty=true;h.t.updateSaveHint();
 assert.equal(h.hint.textContent,SAVED_EARLIER);assert.equal(h.t.canReplaceSession(),false);
 assert.match(h.confirms[0],/Save a copy first if you want to keep it\.$/);
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,files_written:0,downloads_created:0,network_calls:0}));
})().catch(error=>{console.error(error);process.exit(1);});
