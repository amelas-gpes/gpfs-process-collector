'use strict';
// Bounded API / synthetic DOM regression only. No browser, audio, provider, or network calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const all=root=>[root,...root.children.flatMap(all)],find=(root,pred)=>all(root).find(pred),findText=(root,t)=>find(root,e=>e._text===t);
class E{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.dataset={};this.style={};this.hidden=false;this.open=false;this.value='';this._text='';this.disabled=false;}
 append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
 replaceChildren(...children){this.children=[];this._text='';this.append(...children);}
 set textContent(t){this._text=String(t);this.children=[];}get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}get firstElementChild(){return this.children[0];}
 setAttribute(key,v){this.attributes[key]=String(v);}addEventListener(key,fn){(this.listeners[key]??=[]).push(fn);}
 async dispatch(key,extra={}){for(const fn of this.listeners[key]||[])await fn({preventDefault(){},target:this,...extra});}
 showModal(){this.open=true;}close(){this.open=false;void this.dispatch('close');}focus(){this.focused=true;document.activeElement=this;}scrollIntoView(){this.scrolled=true;}
}
const ids=['knowledge-submit','submit-process-menu','submit-process-review','session-menu','session-menu-toggle'],nodes={};
const document={getElementById:id=>nodes[id]||Object.values(nodes).map(root=>find(root,e=>e.id===id)).find(Boolean),createElement:tag=>new E(tag)};
const window={};
let keyNumber=0;const env={window,document,console,Date,JSON,crypto:{randomUUID:()=>`eeeeeeee-eeee-4eee-8eee-${String(++keyNumber).padStart(12,'0')}`}};
vm.runInNewContext(fs.readFileSync('web/knowledge-ui.js','utf8'),env);
const uuid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
function fresh(request,onSubmitted=()=>{}){
 for(const id of ids)nodes[id]=new E(id==='knowledge-submit'?'dialog':'div');
 const session={saved_at:'first-save',context:{process_name:'First process'},turns:[{id:'u1',role:'user',text:'The original participant account.'}],documents:{documents:[]}},notices=[];
 const controller=window.CollectorKnowledge.create({session:()=>structuredClone(session),notice:m=>notices.push(m),request,onSubmitted});controller.configure({revisions_available:true});return {controller,session,notices,form:()=>find(nodes['knowledge-submit'],e=>e.tagName==='FORM')};
}
const settle=async()=>{await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));};
async function click(label,root){const control=find(root,e=>e.tagName==='BUTTON'&&e._text===label)||findText(root,label);assert(control,'Missing control '+label);await control.dispatch('click');await settle();return control;}
const testReceipt=(revision=1,processId='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')=>({submission_id:'cccccccc-cccc-4ccc-8ccc-cccccccccccc',process_id:processId,job_id:'dddddddd-dddd-4ddd-8ddd-dddddddddddd',revision,status:'pending',status_token:'a'.repeat(64)});
let passes=0;
(async()=>{
 {
  const html=fs.readFileSync('web/index.html','utf8');
  assert.match(html,/id="interview-settings"/);
  assert.doesNotMatch(html,/id="(?:open-)?knowledge-admin"/);
  const calls=[],f=fresh(async path=>{calls.push(path);});
  f.session.synthetic_example=true;
  f.controller.configure({revisions_available:true});
  await nodes['session-menu-toggle'].dispatch('click');
  assert.equal(nodes['submit-process-menu'].textContent,'About this example');
  await nodes['submit-process-menu'].dispatch('click');
  assert.equal(nodes['knowledge-submit'].open,true);
  assert.equal(f.form(),undefined);
  assert.deepEqual(calls,[],'Opening the fictional example must not seed or submit it');
  passes++;
 }
 {
  const submitted=[],receipt=testReceipt();
  const f=fresh(async(path,payload)=>{
   if(path.endsWith('/status'))return testReceipt(); // The dialog reads the restored receipt's status when it opens.
   submitted.push(structuredClone(payload));
   if(payload.process_id)throw Object.assign(Error('Revisions require a verified owner or administrator.'),{status:403});
   return testReceipt(1,uuid(44));
  });
  f.controller.restore(receipt.process_id,receipt);
  f.controller.openSubmit();
  await f.form().dispatch('submit');
  assert.equal(f.controller.hasPending,false);
  assert.doesNotMatch(f.form().textContent,/Recover previous submission/);
  const choice=find(f.form(),e=>e.type==='checkbox');
  assert.equal(choice.disabled,false);
  choice.checked=true;
  await f.form().dispatch('submit');
  assert.equal(submitted[0].process_id,receipt.process_id);
  assert.equal(submitted[1].process_id,undefined);
  assert.notEqual(submitted[0].submission_key,submitted[1].submission_key);
  assert.match(nodes['knowledge-submit'].textContent,/Process submitted/);passes++;
 }
 {
  const submitted=[];
  const f=fresh(async(path,payload)=>{
   submitted.push(structuredClone(payload));
   if(submitted.length===1)throw Error('Connection interrupted');
   if(submitted.length===2)throw Object.assign(Error('Administrator access unavailable'),{status:403});
   return testReceipt();
  });
  f.controller.openSubmit();
  await f.form().dispatch('submit');await f.form().dispatch('submit');
  assert.equal(f.controller.hasPending,true);
  assert.match(f.form().textContent,/Recover previous submission/);
  await f.form().dispatch('submit');
  assert.deepEqual(submitted[0],submitted[2]);passes++;
 }
 {
  let fail=true;const submitted=[];const f=fresh(async(path,payload)=>{submitted.push(structuredClone(payload));if(path.endsWith('/status'))return {...testReceipt(),status:'completed'};if(fail){fail=false;throw Error('Temporary error');}return testReceipt();});f.session.unsent_answer='Do not submit';f.session.documents.scope='private-scope';f.controller.openSubmit();assert.match(nodes['knowledge-submit'].textContent,/bounded excerpts.*configured AI provider.*incur charges/);await f.form().dispatch('submit');assert.match(f.form().textContent,/Temporary error/);await f.form().dispatch('submit');assert.equal(submitted[0].unsent_answer,undefined);assert.equal(submitted[0].documents.scope,'private-scope');assert.deepEqual(submitted[0],submitted[1]);assert(!nodes['knowledge-submit'].textContent.includes('a'.repeat(64)));await click('Refresh status',nodes['knowledge-submit']);const receipt=f.controller.exportReceipt();assert.equal(receipt.status,'completed');f.controller.restore(receipt.process_id,{...receipt,job_id:'bad'});assert.equal(f.controller.exportReceipt(),null);f.controller.restore(receipt.process_id,receipt);assert.equal(f.controller.exportReceipt().revision,1);passes++;
 }
 {
  const submitted=[];let complete;let saves=0;
  const {controller,form}=fresh(async(path,payload)=>{submitted.push(structuredClone(payload));return await new Promise(resolve=>complete=resolve);},()=>saves++);
  controller.openSubmit();const first=form(),pending=first.dispatch('submit');assert.equal(controller.hasPending,true);
  nodes['knowledge-submit'].close();controller.openSubmit();const reopened=form();assert.notEqual(reopened,first);assert.match(reopened.textContent,/Saving the captured submission/);
  await reopened.dispatch('submit');assert.equal(submitted.length,1,'Closing and reopening cannot start a second concurrent submission');
  complete(testReceipt());await pending;assert.match(nodes['knowledge-submit'].textContent,/Process submitted/);assert(!form());assert.equal(document.activeElement.id,'knowledge-submit-title');assert.equal(saves,1);assert.equal(controller.hasPending,false);passes++;
 }
 {
  let complete;let saves=0;let requests=0;
  const {controller,session,form}=fresh(async()=>{requests++;return await new Promise(resolve=>complete=resolve);},()=>saves++);
  controller.openSubmit();const old=form(),pending=old.dispatch('submit');controller.reset();session.context.process_name='Replacement process';controller.openSubmit();const replacement=form();
  complete(testReceipt());await pending;assert.equal(controller.processId,null);assert.equal(controller.exportReceipt(),null);assert.equal(saves,0);assert(!replacement.textContent.includes('Process submitted'),'Stale response must not overwrite the replacement dialog');
  await old.dispatch('submit');assert.equal(requests,1,'A detached old form cannot submit a replacement conversation');passes++;
 }
 {
  let complete;let saves=0;
  const {controller,form}=fresh(async()=>await new Promise(resolve=>complete=resolve),()=>saves++);
  controller.openSubmit();const pending=form().dispatch('submit');const imported=testReceipt(4,'ffffffff-ffff-4fff-8fff-ffffffffffff');controller.restore(imported.process_id,imported);
  complete(testReceipt());await pending;assert.equal(controller.processId,imported.process_id);assert.equal(controller.exportReceipt().revision,4);assert.equal(saves,0,'An old response cannot bind itself to an imported interview');passes++;
 }
 {
  const submitted=[];let saves=0;
  const {controller,session,form}=fresh(async(path,payload)=>{if(path.endsWith('/status'))return testReceipt();submitted.push(structuredClone(payload));if(submitted.length===1)throw Error('Response lost after save');return testReceipt(submitted.length===2?1:2);},()=>saves++);
  controller.openSubmit();find(form(),e=>e.name==='participant').value='Original participant';await form().dispatch('submit');assert.equal(controller.hasPending,true);
  session.saved_at='later-save';session.turns.push({id:'u2',role:'user',text:'A later clarification.'});session.documents.documents.push({id:'doc1',analysis:{phase:'complete',summary:'Background result'}});
  nodes['knowledge-submit'].close();controller.openSubmit();assert.match(form().textContent,/Recover retries that exact captured snapshot/);assert.equal(find(form(),e=>e.name==='participant').value,'Original participant');
  await form().dispatch('submit');assert.deepEqual(submitted[1],submitted[0],'Lost-response recovery must resend the immutable original body and key, even after edits/background review');assert.equal(saves,1);assert.equal(controller.hasPending,false);
  controller.openSubmit();await form().dispatch('submit');assert.notEqual(submitted[2].submission_key,submitted[0].submission_key);assert.equal(submitted[2].process_id,testReceipt().process_id);assert.equal(submitted[2].turns.length,2,'New content is submitted only as an explicit subsequent revision');assert.equal(submitted[2].documents.documents.length,1);assert.equal(controller.exportReceipt().revision,2);assert.equal(all(nodes['knowledge-submit']).filter(e=>e.tagName==='H3'&&e._text==='Submission status').length,1,'A successful revision replaces the old status panel instead of leaving conflicting receipt controls');assert.doesNotMatch(nodes['knowledge-submit'].textContent,/Revision 1/);passes++;
 }
 {
  const submitted=[],f=fresh(async(path,payload)=>{submitted.push(structuredClone(payload));return testReceipt();});
  Object.assign(f.session,{turns:[],documents:{scope:'private-file-scope',documents:[{id:'doc_local',status:'ready',analysis:{disposition:'relevant'}}]},
   document_evidence:[{id:'doc_local_p1',document_id:'doc_local',name:'Procedure.pdf',text:'Verified source text'}],workflow:{steps:[{id:'S1',title:'Release payment',evidence_turns:['doc_local_p1']}],connections:[]}});
  await nodes['session-menu-toggle'].dispatch('click');assert.equal(nodes['submit-process-menu'].hidden,false);
  await nodes['submit-process-menu'].dispatch('click');assert(f.form(),'Document-only captures can be submitted without manufacturing a participant turn');assert.match(nodes['knowledge-submit'].textContent,/does not record participant confirmation/);
  await f.form().dispatch('submit');assert.equal(submitted.length,1);assert.equal(submitted[0].turns.length,0);assert.equal(submitted[0].documents.scope,'private-file-scope');assert.equal(submitted[0].workflow.steps[0].evidence_turns[0],'doc_local_p1');assert.equal(submitted[0].document_evidence,undefined,'Browser cached text must not be sent as authority; the server resolves exact scoped citations');passes++;
 }
 {
  let requests=0;const f=fresh(async()=>{requests++;return testReceipt();});f.session.turns=[];f.session.document_evidence=[{id:'doc_local_p1',document_id:'doc_local',text:'A browser claim'}];
  await nodes['session-menu-toggle'].dispatch('click');assert.equal(nodes['submit-process-menu'].hidden,true);
  f.controller.openSubmit();assert.equal(f.form(),undefined,'A saved excerpt without a local file scope cannot create a new documentary submission');
  f.session.documents={scope:'private-file-scope',documents:[{id:'doc_local',status:'ready',analysis:{disposition:'parked'}}]};f.controller.openSubmit();assert.equal(f.form(),undefined,'Parked files are not new submission evidence');
  f.session.documents.documents[0].analysis.disposition='relevant';f.controller.openSubmit();const form=f.form();assert(form);f.session.documents.documents=[];await form.dispatch('submit');assert.equal(requests,0);assert.match(form.textContent,/source is no longer available/,'An open form rechecks evidence before taking a fresh snapshot');passes++;
 }
 {
  // http-boundary-3: the server rebuilds each file reference from its own store by ID, so a submission carries the
  // workspace and the file IDs only, never the saved analysis and inventory of each file (up to 250 KB per file).
  const submitted=[],f=fresh(async(path,payload)=>{submitted.push(structuredClone(payload));return testReceipt();});
  const record=id=>({id,name:id+'.pdf',kind:'pdf',size:1200,sha256:'a'.repeat(64),status:'ready',analysis:{disposition:'relevant',phase:'complete',summary:'S'.repeat(200000),sources:[{source_id:id+'_p1'}]},inventory:'I'.repeat(50000)});
  f.session.documents={scope:'private-file-scope',documents:[record('doc_a'),record('doc_b'),{name:'no id'},null],unavailable_workspaces:[{scope:'older-scope',documents:[record('doc_old')]}]};
  f.controller.openSubmit();await f.form().dispatch('submit');assert.equal(submitted.length,1);
  assert.deepEqual(submitted[0].documents,{scope:'private-file-scope',documents:[{id:'doc_a'},{id:'doc_b'}]});
  assert(JSON.stringify(submitted[0]).length<5000,'Three files with long analyses no longer push a submission past the request limit');
  assert.equal(f.session.documents.documents[0].analysis.summary.length,200000,'The interview itself keeps its file records');passes++;
  // A session without a file workspace keeps the shape the server expects.
  const plain=fresh(async(path,payload)=>{submitted.push(structuredClone(payload));return testReceipt();});
  plain.controller.openSubmit();await plain.form().dispatch('submit');assert.deepEqual(submitted[1].documents,{documents:[]});passes++;
 }
 {
  // A submission the server would refuse for its size is measured first: nothing is sent, the message says so,
  // and it is never presented as a submission that "may already be saved".
  let requests=0;const f=fresh(async()=>{requests++;throw new TypeError('Failed to fetch');});
  f.session.turns=Array.from({length:70},(_,i)=>({id:'u'+i,role:'user',text:'x'.repeat(15000)}));
  f.controller.openSubmit();const form=f.form();await form.dispatch('submit');
  assert.equal(requests,0,'An oversized body is not sent');assert.equal(f.controller.hasPending,false);
  assert.match(form.textContent,/too large to submit:.*company knowledge accepts 1,000 kB.*Nothing was sent/);
  assert.doesNotMatch(form.textContent,/may already be saved|Recover previous submission/);
  const send=find(form,e=>e.tagName==='BUTTON'&&e.type==='submit');assert.equal(send.textContent,'Submit process');assert.equal(send.disabled,false);
  // Characters outside ASCII count by their encoded size: 250,000 two-byte letters are over the limit as well.
  f.session.turns=[{id:'u1',role:'user',text:'é'.repeat(510000)}];await form.dispatch('submit');assert.equal(requests,0);assert.match(form.textContent,/too large to submit/);
  // The limit is the server's when the configuration states it; a body inside it is sent.
  f.controller.configure({knowledge_submit_max_bytes:2000000});await form.dispatch('submit');assert.equal(requests,1);passes++;
  const small=fresh(async()=>{requests++;return testReceipt();});small.controller.configure({knowledge_submit_max_bytes:100});
  small.controller.openSubmit();await small.form().dispatch('submit');assert.equal(requests,1);assert.match(small.form().textContent,/too large to submit/);
  for(const odd of [0,-5,'600000',null,1.5]){small.controller.configure({knowledge_submit_max_bytes:odd});}
  small.controller.openSubmit();await small.form().dispatch('submit');assert.equal(requests,2,'An unusable limit in the configuration leaves the built-in one');passes++;
 }
 {
  // A switched-off store is a refusal, not an uncertain outcome: nothing was saved, so there is nothing to recover.
  for(const code of ['knowledge_store_unavailable','document_store_unavailable']){
   const f=fresh(async()=>{throw Object.assign(new Error('Company knowledge is switched off: its saved database is damaged.'),{status:503,code});});
   f.controller.openSubmit();const form=f.form();await form.dispatch('submit');
   assert.match(form.textContent,/Company knowledge is switched off/);assert.doesNotMatch(form.textContent,/may already be saved|Recover previous submission/);assert.equal(f.controller.hasPending,false);
  }
  // Any other failure without a clear refusal stays recoverable, as before.
  const f=fresh(async()=>{throw Object.assign(new Error('The local server is busy. Retry shortly.'),{status:503});});
  f.controller.openSubmit();await f.form().dispatch('submit');assert.match(f.form().textContent,/may already be saved/);assert.equal(f.controller.hasPending,true);passes++;
 }
 console.log(JSON.stringify({tests_passed:passes,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
