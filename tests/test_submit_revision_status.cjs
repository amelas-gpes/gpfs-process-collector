"use strict";
// What the Submit process dialog says about the filed revision and its analysis, checked against the
// real web/knowledge-ui.js behind a synthetic DOM. No browser, provider or network.
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
const settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
const uuid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const receipt=(revision=1,extra={})=>({submission_id:uuid(1),process_id:uuid(2),revision,job_id:uuid(10+revision),status:"pending",status_token:"a".repeat(64),...extra});

// respond(path,payload) answers each request; restore a saved receipt with h.controller.restore.
function setup(respond,session={}){
  const nodes={};for(const id of ["knowledge-submit","knowledge-admin","submit-process-menu","submit-process-review","open-knowledge-admin","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  const calls=[];let keys=0;
  const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,
    crypto:{randomUUID:()=>`eeeeeeee-eeee-4eee-8eee-${String(++keys).padStart(12,"0")}`}};
  vm.runInNewContext(source,env,{filename:"knowledge-ui.js"});
  const state={saved_at:"2026-11-13T00:00:00.000Z",context:{process_name:"Registration"},turns:[{id:"u1",role:"user",text:"Registration is due by 10 a.m."}],documents:null,...session};
  const h={nodes,calls,state,dialog:nodes["knowledge-submit"]};
  h.controller=env.window.CollectorKnowledge.create({session:()=>structuredClone(h.state),notice(){},
    request:async(pathName,payload)=>{calls.push({path:pathName,payload:structuredClone(payload)});return respond(pathName,payload,calls);}});
  h.controller.configure({revisions_available:true});
  h.open=async()=>{h.controller.openSubmit();await settle();return h.dialog;};
  h.form=()=>find(h.dialog,node=>node.tagName==="FORM");
  h.text=()=>h.dialog.textContent;
  h.button=label=>find(h.dialog,node=>node.tagName==="BUTTON"&&node._text===label);
  h.click=async label=>{const control=h.button(label);assert.ok(control,"Missing control "+label);await control.dispatch("click");await settle();};
  h.submit=async()=>{await h.form().dispatch("submit");await settle();};
  h.statusLine=()=>find(h.dialog,node=>node.attributes.role==="status"&&/^(Revision|Status)/.test(node._text))?._text;
  h.submits=()=>calls.filter(call=>call.path==="/api/knowledge/submit");
  return h;
}
const jobStatus=(revision,extra)=>({submission_id:uuid(1),revision,job_id:uuid(10+revision),status:"pending",error:"",attempts:0,stalled:false,...extra});

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}

(async()=>{
// knowledge-store-1: Refresh status tells the submitter when analysis is waiting with nothing running it.
await check("refresh status says when analysis has not started and shows the stored reason",async()=>{
  // The first answer is read when the dialog opens with a restored receipt; the rest by the button.
  const answers=[jobStatus(1),jobStatus(1,{stalled:true}),jobStatus(1,{stalled:true,error:"Interrupted before completion; retry available.",attempts:3}),jobStatus(1),
    jobStatus(1,{status:"failed",error:"Analysis did not complete. Retry when the provider is available.",attempts:1}),jobStatus(1,{status:"completed",error:"stale text"})];
  const h=setup(pathName=>pathName.endsWith("/status")?answers.shift():undefined);
  h.controller.restore(uuid(2),receipt(1));await h.open();
  await h.click("Refresh status");
  assert.equal(h.statusLine(),"Revision 1 · pending · analysis has not started. Your process is saved; analysis starts when the app next starts with an AI provider configured, or when an administrator retries it.");
  await h.click("Refresh status");
  assert.match(h.statusLine(),/^Revision 1 · pending · analysis has not started · Interrupted before completion; retry available\. Your process is saved;/);
  await h.click("Refresh status");
  assert.equal(h.statusLine(),"Revision 1 · pending","A job that is waiting its turn is not called stalled");
  await h.click("Refresh status");
  assert.equal(h.statusLine(),"Revision 1 · failed · matching could not finish · Analysis did not complete. Retry when the provider is available.");
  await h.click("Refresh status");
  assert.equal(h.statusLine(),"Revision 1 · completed","A finished job shows no leftover reason");
});

// gap3-reopen-continue-2: an older saved copy, or a stale tab, does not silently become the newest revision.
const refusal=(latest,base=1)=>Object.assign(Error(`A newer revision (${latest}) of this process exists. This copy is based on revision ${base}.`),{status:409,code:"newer_revision_exists",latest_revision:latest});
const newerNote=h=>all(h.dialog).find(node=>node.className==="knowledge-newer-revision");
const confirmBox=h=>find(newerNote(h),node=>node.tagName==="INPUT");
const newProcessBox=h=>find(h.form(),node=>node.tagName==="INPUT"&&node.type==="checkbox"&&node.parentElement.textContent.includes("new process"));

await check("an older copy says which revision it is based on and what the latest is, before Submit",async()=>{
  const h=setup((pathName,payload)=>pathName.endsWith("/status")?jobStatus(1,{status:"completed",latest_revision:2}):payload.acknowledged_revision===2?receipt(3):Promise.reject(refusal(2)));
  h.controller.restore(uuid(2),receipt(1));await h.open();
  assert.equal(h.calls[0].path,"/api/knowledge/status","The status is read when the dialog opens");
  const note=newerNote(h);
  assert.equal(note.hidden,false);
  assert.match(note.textContent,/This copy is based on revision 1; the latest is revision 2\./);
  assert.match(note.textContent,/Submit this copy as revision 3 anyway/);
  assert.equal(confirmBox(h).checked,false,"Nothing is confirmed for the submitter");
  await h.submit();
  assert.equal(h.submits().length,1);
  assert.equal(h.submits()[0].payload.base_revision,1);assert.equal(h.submits()[0].payload.acknowledged_revision,undefined);
  assert.match(h.text(),/A newer revision \(2\) of this process exists/);
  assert.equal(h.controller.hasPending,false,"A refusal is not an uncertain save");
  assert.doesNotMatch(h.text(),/Recover previous submission|may already be saved/);
  assert.equal(confirmBox(h).disabled,false);
  confirmBox(h).checked=true;await h.submit();
  const sent=h.submits()[1].payload;
  assert.deepEqual([sent.process_id,sent.base_revision,sent.acknowledged_revision],[uuid(2),1,2]);
  assert.notEqual(sent.submission_key,h.submits()[0].payload.submission_key,"The confirmed attempt is a new snapshot");
  assert.match(h.text(),/Process submitted/);assert.equal(h.controller.exportReceipt().revision,3);
});

await check("a copy based on the latest revision submits without any notice",async()=>{
  const h=setup(pathName=>pathName.endsWith("/status")?jobStatus(2,{latest_revision:2}):receipt(3));
  h.controller.restore(uuid(2),receipt(2));await h.open();
  assert.equal(newerNote(h).hidden,true);
  await h.submit();
  assert.equal(h.submits()[0].payload.base_revision,2);assert.equal(h.submits()[0].payload.acknowledged_revision,undefined);
  assert.match(h.text(),/Process submitted/);
  // The next revision is based on the one just filed.
  await h.open();await h.submit();
  assert.equal(h.submits()[1].payload.base_revision,3);
});

await check("when the status cannot be read, the server's refusal brings the notice and the confirmation",async()=>{
  let latest=2;
  const h=setup((pathName,payload)=>pathName.endsWith("/status")?Promise.reject(Error("offline")):payload.acknowledged_revision===latest?receipt(latest+1):Promise.reject(refusal(latest)));
  h.controller.restore(uuid(2),receipt(1));await h.open();
  assert.equal(h.statusLine(),"Revision 1 · pending · saved receipt, not checked on this computer","A failed read preserves the receipt and identifies it as unchecked");
  assert.equal(newerNote(h).hidden,true);
  await h.submit();
  assert.equal(newerNote(h).hidden,false);
  assert.match(newerNote(h).textContent,/based on revision 1; the latest is revision 2\./);
  // Another revision is filed elsewhere before the submitter confirms: the older confirmation does not carry over.
  confirmBox(h).checked=true;latest=3;await h.submit();
  assert.equal(h.submits()[1].payload.acknowledged_revision,2);
  assert.match(newerNote(h).textContent,/the latest is revision 3\./);assert.match(newerNote(h).textContent,/as revision 4 anyway/);
  assert.equal(confirmBox(h).checked,false,"A newer latest revision must be confirmed again");
  confirmBox(h).checked=true;await h.submit();
  assert.equal(h.submits()[2].payload.acknowledged_revision,3);assert.match(h.text(),/Process submitted/);
});

await check("a new process, and a first submission, carry no base revision",async()=>{
  let h=setup(pathName=>pathName.endsWith("/status")?jobStatus(1,{latest_revision:2}):receipt(1));
  h.controller.restore(uuid(2),receipt(1));await h.open();
  newProcessBox(h).checked=true;await h.submit();
  assert.equal(h.submits()[0].payload.process_id,undefined);assert.equal(h.submits()[0].payload.base_revision,undefined);assert.equal(h.submits()[0].payload.acknowledged_revision,undefined);
  h=setup(()=>receipt(1));await h.open();
  assert.equal(h.calls.length,0,"Nothing is read for an interview that was never submitted");
  assert.equal(newerNote(h),undefined);
  await h.submit();assert.equal(h.submits()[0].payload.base_revision,undefined);
});

await check("a process ID without a saved receipt is submitted as a copy that does not know its revision",async()=>{
  const h=setup((pathName,payload)=>payload.acknowledged_revision===2?receipt(3):Promise.reject(refusal(2,0)));
  h.controller.restore(uuid(2),null);await h.open();
  assert.equal(h.calls.length,0,"Without a status capability there is nothing to read");
  await h.submit();
  assert.equal(h.submits()[0].payload.base_revision,0);
  assert.match(newerNote(h).textContent,/This copy does not record which revision it is based on; the latest is revision 2\./);
  confirmBox(h).checked=true;await h.submit();
  assert.deepEqual([h.submits()[1].payload.base_revision,h.submits()[1].payload.acknowledged_revision],[0,2]);
});

// gap-privacy-3: the dialog says how long a submission is kept, and a deleted process is reported as such.
await check("the dialog says before Submit that submissions are kept, and whether an administrator can delete them",async()=>{
  let h=setup(()=>receipt(1));await h.open();
  assert.match(h.text(),/A submitted process, with every revision, its transcript and the cited file passages, stays in company knowledge on this computer\. This app does not delete submissions; removing one is a manual step for the owner of this computer\./);
  h=setup(()=>receipt(1));h.controller.configure({knowledge_delete_enabled:true});await h.open();
  assert.match(h.text(),/stays in company knowledge on this computer until an administrator deletes it\./);
  assert.doesNotMatch(h.text(),/does not delete submissions/);
});

await check("refresh status reports a process that an administrator deleted",async()=>{
  const h=setup(pathName=>pathName.endsWith("/status")?{submission_id:uuid(1),revision:1,job_id:null,status:"deleted",error:"",attempts:0,stalled:false,latest_revision:null}:undefined);
  h.controller.restore(uuid(2),receipt(1));await h.open();
  assert.equal(h.statusLine(),"Revision 1 · deleted. An administrator removed this process from company knowledge. To file it again, submit it as a new process.");
  assert.equal(h.controller.exportReceipt().status,"pending","The saved receipt is left as it was");
});

await check("manual status refresh keeps its keyboard target and suppresses duplicate requests",async()=>{
  let finish;const h=setup((_path,_payload,calls)=>calls.length===1?jobStatus(1):new Promise(resolve=>finish=resolve));
  h.controller.restore(uuid(2),receipt(1));await h.open();
  const button=h.button("Refresh status");button.focus();
  const pending=button.dispatch("click");await settle();assert.equal(button.attributes["aria-disabled"],"true");
  assert.equal(button.disabled,false);await button.dispatch("click");assert.equal(h.calls.length,2);
  finish(jobStatus(1,{status:"completed"}));await pending;await settle();
  assert.equal(h.button("Refresh status"),button);assert.equal(button.focused,true);assert.match(h.statusLine(),/completed/);
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
