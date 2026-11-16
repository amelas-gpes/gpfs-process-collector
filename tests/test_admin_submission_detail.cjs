"use strict";
// What Admin tells a reviewer about one stored submission, checked against the real
// web/knowledge-ui.js behind a synthetic DOM. No browser, provider or network.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"..","web","knowledge-ui.js"),"utf8");
const all=root=>[root,...root.children.flatMap(all)],find=(root,test)=>all(root).find(test);
class E{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.dataset={};this.style={};this.hidden=false;this.open=false;this.value="";this._text="";this.disabled=false;}
  append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this._text="";this.append(...children);}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join("");}
  get firstElementChild(){return this.children[0];}
  setAttribute(key,value){this.attributes[key]=String(value);}
  addEventListener(key,fn){(this.listeners[key]??=[]).push(fn);}
  async dispatch(key){for(const fn of this.listeners[key]||[])await fn({preventDefault(){},target:this});}
  querySelectorAll(selector){return all(this).filter(node=>node!==this&&selector.startsWith(".")&&String(node.className||"").split(/\s+/).includes(selector.slice(1)));}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  showModal(){this.open=true;}close(){this.open=false;void this.dispatch("close");}focus(){this.focused=true;}scrollIntoView(){}
}
const settle=async()=>{for(let i=0;i<3;i++)await new Promise(resolve=>setImmediate(resolve));};
const uuid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const stored=(extra={})=>({submission_id:uuid(1),process_id:uuid(2),revision:1,submitter:null,created_at:"2026-11-13T00:00:00+00:00",job_status:"completed",display_name:"Invoice intake",
  context:{process_name:"Invoice intake",process_owner:"AP manager",objective:"Document the work"},team:"Accounts payable",department:"",scope:"Fund A",participant:"",
  turns:[{id:"u1",role:"user",text:"A supplier email starts a case."}],
  draft:{title:"Invoice intake",overview:"Reported account.",steps:[{id:"S1",title:"REVIEWER CORRECTED TITLE",evidence_turns:["u1"]}],connections:[]},
  workflow:{title:"Invoice intake",steps:[{id:"S1",title:"Receive and register invoice",evidence_turns:["u1"]}],connections:[]},draft_stale:false,draft_edited:false,...extra});
const listed=item=>({submission_id:item.submission_id,process_id:item.process_id,revision:item.revision,submitter:item.submitter,created_at:item.created_at,display_name:item.display_name,
  context:{process_name:item.context.process_name,process_owner:item.context.process_owner},team:item.team,department:item.department,scope:item.scope,job_status:item.job_status,
  ...(item.listed||{})});

async function openDetail(item){
  const nodes={};for(const id of ["knowledge-submit","knowledge-admin","submit-process-menu","submit-process-review","open-knowledge-admin","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,crypto:{randomUUID:()=>uuid(99)}};
  vm.runInNewContext(source,env,{filename:"knowledge-ui.js"});
  const calls=[],page=items=>({items,page:{offset:0,limit:25,total:items.length,has_more:false}});
  const request=async(pathName,payload)=>{
    calls.push({path:pathName,payload});
    if(pathName.endsWith("/browse"))return {...page(payload.section==="submissions"?[listed(item)]:[]),section:payload.section,counts:{submissions:1},analysis_limitations:""};
    if(pathName.endsWith("/detail")){const {listed:_,...detail}=item;return {kind:"submission",item:structuredClone(detail),submissions:[structuredClone(detail)],entities:[],edges:[],proposals:[]};}
    throw Error("Unexpected request "+pathName);
  };
  const controller=env.window.CollectorKnowledge.create({session:()=>({turns:[],documents:null}),notice(){},request});
  controller.configure({knowledge_admin_enabled:true,knowledge_admin_mode:"Local owner development mode"});
  const admin=nodes["knowledge-admin"];
  const click=async label=>{const control=find(admin,node=>node.tagName==="BUTTON"&&node._text===label);assert.ok(control,"Missing control "+label);await control.dispatch("click");await settle();};
  await nodes["open-knowledge-admin"].dispatch("click");await settle();
  await click("Submissions");
  const list={text:admin.textContent,cards:all(admin).filter(node=>node.className==="knowledge-card").map(node=>node.textContent)};
  await click("Invoice intake");
  assert.equal(calls.at(-1).payload.kind,"submission");
  const notes=all(admin).filter(node=>node.className==="knowledge-status"&&!node.hidden&&node._text).map(node=>node._text);
  return {admin,list,notes,text:admin.textContent};
}

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
const WORKING_MAP_NOTE=/graph for this revision was built from the working map, not from the draft shown here/i;
const STALE_DRAFT_NOTE=/draft was marked out of date when the revision was filed/i;

(async()=>{
await check("a graph built from the draft carries no working-map note",async()=>{
  for(const extra of [{graph_source:"draft"},{graph_source:"draft",draft_stale:true,draft_edited:true},{}]){
    const view=await openDetail(stored(extra));
    assert.match(view.text,/REVIEWER CORRECTED TITLE/,"The submission detail shows the stored draft");
    assert.equal(view.notes.some(note=>WORKING_MAP_NOTE.test(note)),false,JSON.stringify(extra));
    assert.equal(view.notes.some(note=>STALE_DRAFT_NOTE.test(note)),extra.draft_stale===true);
    // The stored flag does not say why: a saved file may have carried it, or only the files in use changed.
    assert.equal(view.notes.some(note=>/predates newer interview answers/.test(note)),false,"Admin must not assert newer answers it cannot know of");
  }
});

await check("a graph built from the working map beside a stored draft says so",async()=>{
  const view=await openDetail(stored({graph_source:"workflow",draft_stale:true}));
  assert.match(view.text,/REVIEWER CORRECTED TITLE/);
  assert.ok(view.notes.some(note=>WORKING_MAP_NOTE.test(note)),"Admin must say the graph did not come from the draft it displays");
  assert.ok(view.notes.some(note=>STALE_DRAFT_NOTE.test(note)));
});

await check("a submission without a draft needs no note about the draft",async()=>{
  const view=await openDetail(stored({graph_source:"workflow",draft:null}));
  assert.match(view.text,/Receive and register invoice/,"Without a draft the detail shows the working map");
  assert.equal(view.notes.some(note=>WORKING_MAP_NOTE.test(note)),false);
});

// gap3-submit-in-flight-1: a revision filed before notes and the working map caught up is marked as such.
const fact=(view,label)=>{const nodes=all(view.admin),index=nodes.findIndex(node=>node.tagName==="DT"&&node._text===label);assert.ok(index>=0,"Missing fact "+label);return nodes[index+1]._text;};
const LAGGING={in_progress:false,notes_current:false,map_current:false,notes_through_turn:"u5",map_through_turn:"u5",answers:6,notes_answers:5,map_answers:5};

await check("a revision whose notes and map stopped early is flagged in the list and explained in the detail",async()=>{
  const view=await openDetail(stored({capture:LAGGING,listed:{capture_incomplete:true}}));
  assert.equal(view.list.cards.length,1);
  assert.match(view.list.cards[0],/Revision 1 · Accounts payable · completed · filed before notes and map caught up/);
  assert.equal(fact(view,"Notes and map when filed"),"notes covered 5 of 6 answers; the working map covered 5 of 6 answers");
  const note=view.notes.find(text=>/Filed before the notes and working map had caught up/.test(text));
  assert.ok(note,"The detail must not read as a complete filing");
  assert.match(note,/notes covered 5 of 6 answers; the working map covered 5 of 6 answers/);
  assert.match(note,/transcript below is complete/i);
});

// live-draft-knowledge-2: the Submissions list shows every revision; one that a later revision replaced says so.
await check("a revision that a later one replaced is marked as superseded in the list",async()=>{
  const earlier=await openDetail(stored({listed:{latest:false}}));
  assert.match(earlier.list.cards[0],/Revision 1 · superseded by a later revision · Accounts payable · completed/);
  for(const listedAs of [{latest:true},{}]){
    const current=await openDetail(stored({listed:listedAs}));
    assert.doesNotMatch(current.list.cards[0],/superseded/,"The latest revision, or a list without the flag, carries no marker");
  }
});

await check("a complete capture is stated without a warning",async()=>{
  const view=await openDetail(stored({capture:{in_progress:false,notes_current:true,map_current:true,notes_through_turn:"u6",map_through_turn:"u6",answers:6,notes_answers:6,map_answers:6},listed:{capture_incomplete:false}}));
  assert.doesNotMatch(view.list.cards[0],/filed before/);
  assert.equal(fact(view,"Notes and map when filed"),"Complete through all 6 answers");
  assert.equal(view.notes.some(text=>/Filed before/.test(text)),false);
});

await check("other capture states are worded for what is known",async()=>{
  const cases=[
    [{in_progress:true,notes_current:true,map_current:true,answers:1,notes_answers:1,map_answers:1},"capture had not finished",true],
    [{in_progress:false,notes_current:false,map_current:true,notes_through_turn:null,answers:2,notes_answers:0,map_answers:2},"notes covered 0 of 2 answers",true],
    [{in_progress:false,notes_current:false,map_current:true,answers:3,notes_answers:3,map_answers:3},"notes did not reflect the latest wording of the answers",true],
    [{in_progress:false,notes_current:null,map_current:null,answers:4,notes_answers:null,map_answers:null},"notes coverage not recorded; the working map coverage not recorded",false],
    // A file reopened without a capture record: only the answers added since are known to be missing.
    [{in_progress:false,notes_current:false,map_current:false,notes_through_turn:"u13",map_through_turn:"u13",answers:14,notes_answers:13,map_answers:13,notes_assumed:true,map_assumed:true},
      "notes did not include the latest answer (coverage of the earlier answers was not recorded); the working map did not include the latest answer (coverage of the earlier answers was not recorded)",true],
    [{in_progress:false,notes_current:false,map_current:true,notes_through_turn:"u2",map_through_turn:"u5",answers:5,notes_answers:2,map_answers:5,notes_assumed:true},
      "notes did not include the latest 3 answers (coverage of the earlier answers was not recorded)",true],
    [undefined,"Not recorded",false]];
  for(const [capture,summary,warned] of cases){
    const view=await openDetail(stored(capture?{capture}:{}));
    assert.equal(fact(view,"Notes and map when filed"),summary);
    assert.equal(view.notes.some(text=>/Filed before/.test(text)),warned,summary);
    if(capture?.notes_assumed)assert.doesNotMatch(view.text,/notes covered \d+ of/,"An assumed position must not be shown as a recorded coverage");
  }
});

// gap-knowledge-documents-1. This check is a GUARD, not the regression test: the wording it reads was
// already in web/knowledge-ui.js before the fix and could simply never render, so the check also passes
// on the old client. The defect is detected on the server side, in tests/test_knowledge_retained_documents.py
// (for example test_revision_keeps_a_citation_to_a_removed_file_as_a_flagged_saved_excerpt), which asserts
// that the stored flags reach admin_detail and fails on the old code. Here: the reviewer's view of such a revision.
await check("a citation kept from a removed or parked file is shown as a saved excerpt",async()=>{
  const evidence=[{id:"doc_a_r1_c1",document_id:"doc_a",name:"returns-log.csv",label:"returns-log.csv · rows 1-2",text:"A1=return | B1=reason",source_kind:"document",retained_only:true,archived:true,disposition:"relevant"},
    {id:"doc_b_p1_c1",document_id:"doc_b",name:"policy.pdf",label:"policy.pdf · page 1",text:"Returns need approval.",source_kind:"document"}];
  const view=await openDetail(stored({document_evidence:evidence,documents:{documents:[{id:"doc_b",name:"policy.pdf",sources:[{source_id:"doc_b_p1_c1",label:"page 1"}]}],retained:[{id:"doc_a",name:"returns-log.csv",archived:true,sources:[{source_id:"doc_a_r1_c1",label:"rows 1-2"}]}]},
    draft:{title:"Invoice intake",overview:"Reported account.",steps:[{id:"S1",title:"Check the log",evidence_turns:["doc_a_r1_c1","u1"]},{id:"S2",title:"Approve",evidence_turns:["doc_b_p1_c1"]}],connections:[]}}));
  assert.equal(view.notes.filter(note=>/Saved excerpt from a removed or parked file/.test(note)).length,1,"Only the citation to the removed file carries the note");
  assert.match(view.text,/A1=return \| B1=reason/,"The saved excerpt is stored with the revision and shown");
  const live=all(view.admin).filter(node=>node.tagName==="BUTTON").map(node=>node._text);
  assert.ok(live.includes("page 1"),"A file in use keeps its Read source control");
  assert.equal(live.includes("rows 1-2"),false,"A removed file is not offered for a live read");
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
