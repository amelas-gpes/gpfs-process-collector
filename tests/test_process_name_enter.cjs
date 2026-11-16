"use strict";
// Enter in the Process name field must only commit a rename once an interview
// exists. The real submit binding and startInterview run against a minimal DOM
// that models HTML implicit form submission. No browser, provider, audio device
// or network request is used.
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const root=path.join(__dirname,".."),html=fs.readFileSync(path.join(root,"web","index.html"),"utf8"),app=fs.readFileSync(path.join(root,"web","app.js"),"utf8");

const document={activeElement:null};
class Element {
 constructor(id){this.id=id;this.hidden=false;this.disabled=false;this.value="";this.textContent="";this.listeners={};this.blurs=0;this.firstElementChild=null;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
 focus(){document.activeElement=this;}
 blur(){this.blurs++;if(document.activeElement===this)document.activeElement=null;}
 reportValidity(){return true;}
}
const nodes=new Map(),mount=id=>{const node=new Element(id);nodes.set(id,node);return node;};
document.getElementById=id=>nodes.get(id)||null;
const form=mount("context-form"),title=mount("process-name"),startLive=mount("start-live");
for(const id of ["process-owner","objective","background"])mount(id);

// The shipped markup decides whether Enter in the title submits the form.
const formHtml=html.match(/<form id="context-form">[\s\S]*?<\/form>/)?.[0];
assert.ok(formHtml,"The Process name form must exist");
assert.match(formHtml,/<input id="process-name"/,"Process name must be the field inside the form");
assert.equal((formHtml.match(/<(?:input|textarea|select)\b/g)||[]).length,1,"Process name is the form's only field");
const defaultButtonId=formHtml.match(/<button type="submit" id="([^"]+)"/)?.[1]||null;
const defaultButton=defaultButtonId?mount(defaultButtonId):null;
if(defaultButton){defaultButton.hidden=/<button type="submit" id="[^"]+" hidden>/.test(formHtml);defaultButton.firstElementChild=new Element(defaultButtonId+"-label");}

const calls={confirm:[],clearState:[],notice:[],updateControls:0};
const binding=app.split("\n").filter(line=>/\$\("context-form"\)\.addEventListener\("submit"/.test(line)).join("\n");
assert.ok(binding,"The form's submit binding must be found in app.js");
const hook=`
  clearState=(...args)=>{window.calls.clearState.push(args);Object.assign(state,{turns:[],started:false,dirty:false,example:false});};
  notice=(...args)=>window.calls.notice.push(args);
  updateControls=()=>{window.calls.updateControls++;};
  ${binding}
  window.enterTests={state,conversationUI};
})();`;
const patched=app.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
assert.notEqual(patched,app,"Install the test hook only at application initialization");
// confirm() answers OK, as a habitual second Enter on the dialog's default button would.
const sandbox={console,document,window:{calls},setTimeout,clearTimeout,AbortController,TextEncoder,confirm:message=>{calls.confirm.push(message);return true;}};
vm.createContext(sandbox);vm.runInContext(patched,sandbox,{filename:"app.js"});
const t=sandbox.window.enterTests;
assert.equal(form.listeners.submit?.length,1,"The real submit handler is bound exactly once");

// HTML implicit submission: Enter in a single-line field submits its form through
// the default button, even a hidden one; a disabled default button blocks it.
function pressEnterInTitle(){
 title.focus();
 if(defaultButton?.disabled)return null;
 const event={type:"submit",target:form,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};
 for(const fn of form.listeners.submit)fn(event);
 return event;
}
function reset(){
 calls.confirm.length=0;calls.clearState.length=0;calls.notice.length=0;calls.updateControls=0;title.blurs=0;document.activeElement=null;
 Object.assign(t.state,{context:null,turns:[],started:false,busy:false,recording:null,transcribing:false,requestingMic:false,example:false,dirty:false});
 t.conversationUI.live=null;
 for(const id of ["process-name","process-owner","objective","background"])nodes.get(id).value="";
}
function startedInterview(){
 reset();
 const context={process_name:"Supply order",process_owner:"Office manager",objective:"Understand the work",background:""};
 const turns=[{id:"t001",role:"assistant",text:"What process are we documenting?"},{id:"t002",role:"user",text:"Every Monday I count the supply cupboard and list shortages."},{id:"t003",role:"assistant",text:"Who receives the list?"}];
 Object.assign(t.state,{context,turns,started:true,dirty:true});
 return {context,turns};
}
function assertUntouched(saved,label){
 assert.deepEqual(calls.confirm,[],label+": no dialog may be raised");
 assert.deepEqual(calls.clearState,[],label+": the interview must not be cleared");
 assert.deepEqual(calls.notice,[],label+": no notice may point at a hidden control");
 assert.equal(t.state.turns,saved.turns,label+": the turns are kept");assert.equal(t.state.turns.length,3);
 assert.equal(t.state.context,saved.context,label+": the context is not rebuilt from the form");
 assert.equal(t.state.started,true);assert.equal(t.state.dirty,true,label+": unsaved changes stay protected");
}
let checks=0;

{
 // A rename committed with Enter on a running interview.
 const saved=startedInterview();title.value="Weekly supply order";
 const event=pressEnterInTitle();
 assert.ok(event,"Enter reaches the submit handler while the default button is enabled");
 assert.equal(event.defaultPrevented,true,"The page must never navigate on submit");
 assertUntouched(saved,"rename");
 assert.equal(title.blurs,1,"Enter commits the rename by leaving the field");
 assert.notEqual(document.activeElement,title);assert.notEqual(document.activeElement,startLive,"Start-up focus handling must not run for a started interview");
 assert.equal(title.value,"Weekly supply order","The typed title is kept");checks++;
}
{
 // A held Enter key repeats the submission; none of the repeats may reach a destructive path.
 const saved=startedInterview();
 for(let i=0;i<6;i++)pressEnterInTitle();
 assertUntouched(saved,"held Enter");assert.equal(title.blurs,6);checks++;
}
{
 // The fictional example must not turn into a real interview that keeps its example context.
 const saved=startedInterview();t.state.example=true;t.state.dirty=false;
 pressEnterInTitle();
 assert.deepEqual(calls.confirm,[]);assert.deepEqual(calls.clearState,[]);assert.deepEqual(calls.notice,[]);
 assert.equal(t.state.example,true,"The example stays an example");assert.equal(t.state.context,saved.context);assert.equal(t.state.turns,saved.turns);
 assert.equal(t.state.dirty,false,"Enter alone is not an edit");checks++;
}
{
 // Live voice sets none of the busy flags, so a rename during a conversation takes the same path.
 const saved=startedInterview();let stops=0;t.conversationUI.live={active:true,stop:()=>{stops++;}};
 pressEnterInTitle();
 assertUntouched(saved,"live voice");assert.equal(stops,0,"The live session keeps running");checks++;
}
{
 // Whatever the busy state, a started interview is never replaced from this handler.
 for(const flag of ["busy","transcribing","requestingMic","recording"]){
  const saved=startedInterview();t.state[flag]=flag==="recording"?{}:true;
  pressEnterInTitle();assertUntouched(saved,flag);
 }
 checks++;
}
{
 // Before an interview exists, Enter keeps its start-up behaviour.
 reset();title.value="  Weekly supply order ";nodes.get("process-owner").value="Office manager";nodes.get("objective").value="Understand the work";
 const event=pressEnterInTitle();
 assert.equal(event.defaultPrevented,true);assert.deepEqual(calls.confirm,[]);assert.deepEqual(calls.clearState,[]);assert.deepEqual(calls.notice,[]);
 assert.equal(t.state.started,true);assert.equal(t.state.example,false);
 assert.deepEqual(JSON.parse(JSON.stringify(t.state.context)),{process_name:"Weekly supply order",process_owner:"Office manager",objective:"Understand the work",background:""});
 assert.equal(document.activeElement,startLive,"Starting moves focus to the first interview control");assert.equal(title.blurs,0);
 // The next Enter is a rename of the interview that now exists.
 const saved={context:t.state.context,turns:t.state.turns};
 pressEnterInTitle();assert.deepEqual(calls.confirm,[]);assert.deepEqual(calls.clearState,[]);assert.equal(t.state.context,saved.context);assert.equal(t.state.started,true);assert.equal(title.blurs,1);checks++;
}
{
 // No message may tell the participant to use a control that is never shown.
 assert.equal(defaultButton,null,"The title form handles native Enter without a hidden submit control");
 assert.doesNotMatch(html,/id="start-interview"/);
 assert.doesNotMatch(app,/select Start interview/i,"Start interview is never visible, so no notice may name it");
 assert.doesNotMatch(app,/Start a new interview\?/,"Replacing an interview belongs to Start over, which checks live voice and pending submissions");checks++;
}
console.log(JSON.stringify({checks_passed:checks,dialogs_raised:calls.confirm.length,provider_calls:0,network_calls:0}));
