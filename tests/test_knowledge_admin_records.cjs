"use strict";
// What Admin shows a reviewer about stored records, checked against the real web/knowledge-ui.js
// behind a synthetic DOM. No browser, provider or network.
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
  async dispatch(key,extra={}){for(const fn of this.listeners[key]||[])await fn({preventDefault(){},target:this,...extra});}
  querySelectorAll(selector){return all(this).filter(node=>node!==this&&(selector==="[data-focus-key]"?node.dataset.focusKey!==undefined:selector.startsWith(".")&&String(node.className||"").split(/\s+/).includes(selector.slice(1))));}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  showModal(){this.open=true;}close(){this.open=false;void this.dispatch("close");}focus(){this.focused=true;}scrollIntoView(){}
}
const settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
const uuid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const page=(items,payload={})=>({items,page:{offset:payload.offset||0,limit:payload.limit||25,total:items.length,has_more:false}});
const stored=(extra={})=>({submission_id:uuid(1),process_id:uuid(2),revision:1,submitter:null,created_at:"2026-11-13T00:00:00+00:00",job_status:"completed",display_name:"Carrier claims",
  context:{process_name:"Carrier claims",process_owner:"Logistics lead",objective:"Document the work"},team:"Logistics",department:"",scope:"Fund A",participant:"",
  turns:[{id:"u1",role:"user",text:"We check the carrier claim limit."}],
  draft:{title:"Carrier claims",overview:"Reported account.",steps:[{id:"S1",title:"Check carrier claim limit",evidence_turns:["u1"]}],connections:[]},...extra});
const listed=item=>({submission_id:item.submission_id,process_id:item.process_id,revision:item.revision,submitter:item.submitter,created_at:item.created_at,display_name:item.display_name,
  context:{process_name:item.context.process_name,process_owner:item.context.process_owner},team:item.team,department:item.department,scope:item.scope,job_status:item.job_status});

// handler(path,payload) answers one Admin request; undefined means the test did not expect it.
async function openAdmin(handler,config={},mode="Local owner development mode"){
  const nodes={};for(const id of ["knowledge-submit","knowledge-admin","submit-process-menu","submit-process-review","open-knowledge-admin","session-menu","session-menu-toggle","interview-settings"])nodes[id]=new E("div");
  const env={window:{addEventListener(){},removeEventListener(){}},document:{getElementById:id=>nodes[id],createElement:tag=>new E(tag)},console,Date,JSON,crypto:{randomUUID:()=>uuid(99)}};
  vm.runInNewContext(source,env,{filename:"knowledge-ui.js"});
  const calls=[];
  const request=async(pathName,payload)=>{
    calls.push({path:pathName,payload:structuredClone(payload)});
    const answer=await handler(pathName,payload);
    if(answer===undefined)throw Error("Unexpected request "+pathName);
    return structuredClone(answer);
  };
  const controller=env.window.CollectorKnowledge.create({session:()=>({turns:[],documents:null}),notice(){},request});
  controller.configure({knowledge_admin_enabled:true,knowledge_admin_mode:mode,...config});
  const admin=nodes["knowledge-admin"];
  const button=(label,root=admin)=>find(root,node=>node.tagName==="BUTTON"&&node._text===label);
  const click=async(label,root=admin)=>{const control=button(label,root);assert.ok(control,"Missing control "+label);await control.dispatch("click");await settle();return control;};
  const notes=(cls="knowledge-status")=>all(admin).filter(node=>node.className===cls&&!node.hidden&&node._text).map(node=>node._text);
  const field=(name,root=admin)=>{const control=find(root,node=>node.name===name);assert.ok(control,"Missing field "+name);return control;};
  await nodes["open-knowledge-admin"].dispatch("click");await settle();
  return {admin,nodes,calls,controller,button,click,notes,field,text:()=>admin.textContent};
}
// A store with one submission; extra(path,payload) may answer first.
const oneSubmission=(item,extra=()=>undefined)=>(pathName,payload)=>{
  const first=extra(pathName,payload);if(first!==undefined)return first;
  if(pathName.endsWith("/browse"))return {...page(payload.section==="submissions"?[listed(item)]:[],payload),section:payload.section,counts:{submissions:1},analysis_limitations:""};
  if(pathName.endsWith("/detail")&&payload.kind==="submission")return {kind:"submission",item,submissions:[item],entities:[],edges:[],proposals:[]};
};

let passed=0;
async function check(name,fn){try{await fn();passed++;}catch(error){error.message=name+": "+error.message;throw error;}}
const UNVERIFIED=/AI visual transcription is unverified/;

(async()=>{
// gap-knowledge-documents-2: a cited AI reading of an image is not shown as the file's own text.
const evidence=[
  {id:"doc_a_image_c1",document_id:"doc_a",name:"carrier-claim-limits.png",label:"carrier-claim-limits.png · image",text:"Brindle Freight | Standard pallet | $2,375 | 14 days",source_kind:"document",origin:"ai_visual_transcription",verified:false},
  {id:"doc_b_p1_c1",document_id:"doc_b",name:"policy.pdf",label:"policy.pdf · page 1",text:"Claims above the limit go to the insurer.",source_kind:"document",origin:"source_extraction"},
  {id:"doc_c_p1_c1",document_id:"doc_c",name:"older.pdf",label:"older.pdf · page 1",text:"Stored before the reading was recorded.",source_kind:"document"}];
const citing=ids=>stored({document_evidence:evidence,documents:{documents:[{id:"doc_a",name:"carrier-claim-limits.png",sources:[{source_id:"doc_a_image_c1",label:"image"}]},{id:"doc_b",name:"policy.pdf",sources:[{source_id:"doc_b_p1_c1",label:"page 1"}]}]},
  draft:{title:"Carrier claims",overview:"Reported account.",steps:[{id:"S3",title:"Check carrier claim limit",evidence_turns:ids}],connections:[]}});
const evidenceItems=view=>all(view.admin).filter(node=>node.className==="knowledge-evidence-item").map(node=>node.textContent);

await check("a step citing an AI visual transcription says it is unverified",async()=>{
  const view=await openAdmin(oneSubmission(citing(["doc_a_image_c1"])));
  await view.click("Submissions");await view.click("Carrier claims");
  const items=evidenceItems(view);
  assert.equal(items.length,1);
  assert.match(items[0],/Document-supported/);assert.match(items[0],/\$2,375/);
  assert.match(items[0],UNVERIFIED,"The reviewer must be told the figure is a model's reading of an image");
});

await check("the file's own text carries no transcription warning, and an unrecorded reading says so",async()=>{
  const view=await openAdmin(oneSubmission(citing(["doc_b_p1_c1","doc_c_p1_c1"])));
  await view.click("Submissions");await view.click("Carrier claims");
  const [native,legacy]=evidenceItems(view);
  assert.doesNotMatch(native,UNVERIFIED);assert.doesNotMatch(native,/was not recorded/);
  assert.doesNotMatch(legacy,UNVERIFIED,"An unknown reading is not asserted to be a transcription");
  assert.match(legacy,/How this text was read was not recorded for this revision/);
});

await check("a stored verified:false alone is enough for the warning",async()=>{
  const item=citing(["doc_b_p1_c1"]);item.document_evidence[1]={...item.document_evidence[1],origin:"source_extraction",verified:false};
  const view=await openAdmin(oneSubmission(item));
  await view.click("Submissions");await view.click("Carrier claims");
  assert.match(evidenceItems(view)[0],UNVERIFIED);
});

await check("reading a supporting file says when the text is an AI visual transcription",async()=>{
  const sources={doc_a_image_c1:{text:"Brindle Freight | Standard pallet | $2,375 | 14 days",origin:"ai_visual_transcription",verified:false},doc_b_p1_c1:{text:"Claims above the limit go to the insurer."}};
  const view=await openAdmin(oneSubmission(citing(["u1"]),(pathName,payload)=>pathName.endsWith("/document-source")?{source:sources[payload.source_id]}:undefined));
  await view.click("Submissions");await view.click("Carrier claims");
  assert.equal(view.notes().some(note=>UNVERIFIED.test(note)),false,"Nothing is claimed before a source is read");
  await view.click("page 1");
  assert.match(view.text(),/Claims above the limit go to the insurer\./);
  assert.equal(view.notes().some(note=>UNVERIFIED.test(note)),false,"Native text is not flagged");
  await view.click("image");
  assert.match(view.text(),/\$2,375/);
  assert.equal(view.notes().filter(note=>UNVERIFIED.test(note)).length,1,"The transcription is flagged beside its text");
});

// knowledge-store-1: jobs that are waiting with nothing running them are visible on the overview.
const overview=counts=>(pathName,payload)=>pathName.endsWith("/browse")?{...page([],payload),section:payload.section,counts,analysis_limitations:""}:undefined;

await check("the overview says when submissions are waiting for analysis that has not run",async()=>{
  let view=await openAdmin(overview({submissions:3,processing_failures:0,processing_stalled:2}));
  assert.deepEqual(view.notes(),["2 submissions have waited more than five minutes for analysis that has not run. Open Processing to see and retry them."]);
  view=await openAdmin(overview({submissions:3,processing_failures:0,processing_stalled:1}));
  assert.match(view.notes()[0],/^1 submission has waited .* retry it\.$/);
  for(const counts of [{submissions:3,processing_failures:1,processing_stalled:0},{submissions:3,processing_failures:1}]){
    view=await openAdmin(overview(counts));
    assert.deepEqual(view.notes(),[],"Nothing is said when no job is waiting, or when an older server sends no count");
  }
});

// gap-privacy-3: deleting a submitted process is offered only where the owner enabled it, with a reason and a typed word.
const deleteForm=view=>all(view.admin).find(node=>node.tagName==="FORM"&&node.textContent.includes("Delete this process"));

await check("no delete control is shown unless the owner enabled deletion",async()=>{
  for(const config of [{},{knowledge_delete_enabled:false},{knowledge_delete_enabled:"true"}]){
    const view=await openAdmin(oneSubmission(stored({latest_revision:1})),config);
    await view.click("Submissions");await view.click("Carrier claims");
    assert.match(view.text(),/Business summary/);
    assert.equal(deleteForm(view),undefined,JSON.stringify(config));
  }
});

await check("an administrator deletes a process with a reason, the typed word and the latest revision shown",async()=>{
  let deleted=false,fail=true;
  const item=stored({revision:1,latest_revision:3});
  const view=await openAdmin((pathName,payload)=>{
    if(pathName.endsWith("/delete")){if(fail){fail=false;throw Error("Submission changed; refresh before deleting.");}deleted=true;return {deleted:true,submission_id:item.submission_id,revisions:3};}
    if(pathName.endsWith("/browse"))return {...page(payload.section==="submissions"&&!deleted?[listed(item)]:[],payload),section:payload.section,counts:{submissions:deleted?0:1},analysis_limitations:""};
    if(pathName.endsWith("/detail"))return {kind:"submission",item,submissions:[item],entities:[],edges:[],proposals:[]};
  },{knowledge_delete_enabled:true});
  await view.click("Submissions");await view.click("Carrier claims");
  const form=deleteForm(view);assert.ok(form,"The delete form is in the submission detail");
  assert.match(form.textContent,/all 3 revisions/);assert.match(form.textContent,/cannot be undone/i);assert.match(form.textContent,/Files uploaded to the interview and saved interview files are not removed/);
  const sent=()=>view.calls.filter(call=>call.path.endsWith("/delete"));
  for(const [reason,word] of [["","DELETE"],["Erasure request",""],["Erasure request","delete"],["   ","DELETE"]]){
    view.field("delete_reason",form).value=reason;view.field("delete_confirm",form).value=word;
    await form.dispatch("submit");await settle();
    assert.equal(sent().length,0,"Nothing is sent without a reason and the exact word");
    assert.match(form.textContent,/Give a reason and type DELETE in capitals/);
  }
  view.field("delete_reason",form).value=" Erasure request ";view.field("delete_confirm",form).value="DELETE";
  await form.dispatch("submit");await settle();
  assert.deepEqual(sent()[0].payload,{submission_id:item.submission_id,expected_revision:3,reason:"Erasure request",confirm:"DELETE"});
  assert.match(form.textContent,/Submission changed; refresh before deleting\./,"A refusal stays on the record with the server's reason");
  assert.equal(view.button("Delete process",form).disabled,false);
  await form.dispatch("submit");await settle();
  assert.equal(sent().length,2);
  assert.match(view.text(),/Employee submissions & revisions/);assert.match(view.text(),/No records match these filters/);
  assert.equal(deleteForm(view),undefined);
});

// live-draft-knowledge-7: equal labels of different processes can be told apart, the graph can be narrowed
// by text and type, and a stale group can take the latest revision's entities in one change.
const ledger=(n,processName,extra={})=>({id:uuid(500+n),submission_id:uuid(600+n),revision:1,type:"system",label:"LedgerLoom",latest:true,canonical_id:null,process_name:processName,step_count:12,step_label:"Register vendor",...extra});
const records=(entities,extra=()=>undefined)=>(pathName,payload)=>{
  const first=extra(pathName,payload);if(first!==undefined)return first;
  if(pathName.endsWith("/browse"))return {...page(payload.section==="entities"?entities:[],payload),section:payload.section,counts:{},analysis_limitations:""};
};

await check("entity cards, the selection chips and the member picker name the source process and steps",async()=>{
  const entities=[ledger(1,"Vendor onboarding"),ledger(2,"Payment run",{step_count:1,step_label:"Release payment"}),ledger(3,"",{step_count:0,step_label:null})];
  const view=await openAdmin(records(entities));
  await view.click("Entities");
  const cards=all(view.admin).filter(node=>node.className==="knowledge-card").map(node=>node.textContent);
  assert.match(cards[0],/^LedgerLoomsystem · Vendor onboarding · named by 12 steps · revision 1/);
  assert.match(cards[1],/^LedgerLoomsystem · Payment run · step: Release payment · revision 1/);
  assert.match(cards[2],/^LedgerLoomsystem · revision 1/,"An older server that sends no source still gets a readable card");
  await view.click("Create reviewed group");
  const boxes=all(view.admin).filter(node=>node.tagName==="INPUT"&&node.type==="checkbox"&&node.attributes["aria-label"]==="Select LedgerLoom");
  for(const index of [0,1]){const box=all(view.admin).filter(node=>node.tagName==="INPUT"&&node.type==="checkbox"&&node.attributes["aria-label"]==="Select LedgerLoom")[index];box.checked=true;await box.dispatch("change");await settle();}
  assert.equal(boxes.length,3);
  const chips=all(view.admin).filter(node=>node.className==="knowledge-filter-chip").map(node=>[node._text,node.attributes["aria-label"]]);
  assert.deepEqual(chips,[["LedgerLoom · Vendor onboarding · named by 12 steps ×","Remove selected entity LedgerLoom, Vendor onboarding · named by 12 steps"],["LedgerLoom · Payment run · step: Release payment ×","Remove selected entity LedgerLoom, Payment run · step: Release payment"]]);
});

const staleGroup={id:uuid(700),label:"LedgerLoom",type:"system",status:"stale",stale_reason:"A member source was revised; replace outdated members and review the group.",review_version:4,member_count:2,alias_count:0,history_count:3,members:[],aliases:[],history:[]};
const groupStore=(group,calls=[])=>(pathName,payload)=>{
  if(pathName.endsWith("/browse"))return {...page(payload.section==="groups"?[group]:payload.section==="entities"?[ledger(4,"Payment run")]:[],payload),section:payload.section,counts:{},analysis_limitations:""};
  if(pathName.endsWith("/detail"))return {kind:"group",item:group,submissions:[],entities:[],edges:[],proposals:[]};
  if(pathName.endsWith("/history"))return {...page(payload.kind==="group_members"?[ledger(1,"Vendor onboarding",{latest:false}),ledger(2,"Payment run")]:[],payload),kind:payload.kind,id:payload.id};
  if(pathName.endsWith("/canonical-update")){calls.push(payload);return {...group,replaced:1,left_outdated:0};}
};

await check("a stale group offers to replace outdated members with the latest revision's entities",async()=>{
  const view=await openAdmin(groupStore(staleGroup));
  await view.click("Reviewed groups");await view.click("LedgerLoom · system");
  const form=all(view.admin).find(node=>node.tagName==="FORM"),action=find(form,node=>node.tagName==="SELECT");
  const options=action.children.map(node=>[node.value,node._text]);
  assert.deepEqual(options.slice(-2),[["replace_outdated","Replace outdated members with the latest revision’s entities"],["revalidate","Revalidate current grouping"]]);
  assert.match(view.text(),/LedgerLoomsystem · Vendor onboarding · named by 12 steps · revision 1 · earlier revision/,"Members name their process");
  assert.match(view.text(),/LedgerLoom · Payment run · named by 12 steps · revision 1/,"Picker rows name their process");
  action.value="replace_outdated";await action.dispatch("change");await settle();
  assert.match(form.textContent,/replaced by the entity with the same type and label in the latest revision of its process/);
  view.field("reason",form).value="Process was revised";
  await form.dispatch("submit");await settle();
  const sent=view.calls.filter(call=>call.path.endsWith("/canonical-update")).map(call=>call.payload);
  assert.deepEqual(sent,[{canonical_id:staleGroup.id,action:"replace_outdated",value:"reviewed",reason:"Process was revised",expected_revision:4}]);
});

await check("an active group does not offer the replacement",async()=>{
  const view=await openAdmin(groupStore({...staleGroup,status:"active",stale_reason:""}));
  await view.click("Reviewed groups");await view.click("LedgerLoom · system");
  const action=find(all(view.admin).find(node=>node.tagName==="FORM"),node=>node.tagName==="SELECT");
  assert.deepEqual(action.children.map(node=>node.value),["add_member","remove_member","add_alias","remove_alias"]);
});

await check("the graph can be narrowed by text, and by entity type at All entities",async()=>{
  const tooLarge={entities:[],edges:[],proposals:[],submissions:[],too_large:true,counts:{nodes:124,connections:140},message:"Select a process or refine filters to show a complete graph of at most 80 entities and 150 connections."};
  const view=await openAdmin((pathName,payload)=>pathName.endsWith("/graph")?tooLarge:pathName.endsWith("/browse")?{...page([],payload),section:payload.section,counts:{},analysis_limitations:""}:undefined);
  const graphCalls=()=>view.calls.filter(call=>call.path.endsWith("/graph")).map(call=>call.payload);
  await view.click("Graph");
  assert.deepEqual(graphCalls().at(-1).filters,{state:"all",team:"",system:"",scope:"",freshness:"all"},"No narrowing is sent until it is asked for");
  const typeField=()=>all(view.admin).find(node=>node.tagName==="SELECT"&&node.parentElement.textContent.startsWith("Entity type"));
  assert.equal(typeField().parentElement.hidden,true,"Entity type applies to All entities only");
  await view.click("All entities");
  assert.match(view.text(),/124 entities · 140 connections\. No partial graph is displayed\./);
  assert.equal(typeField().parentElement.hidden,false,"The narrowing controls stay available when the view is too large");
  view.field("graph_query").value=" ledger ";typeField().value="system";
  await view.click("Search graph");
  assert.equal(graphCalls().at(-1).level,"all");
  assert.deepEqual([graphCalls().at(-1).filters.query,graphCalls().at(-1).filters.type],["ledger","system"]);
  assert.equal(view.field("graph_query").value,"ledger","The search stays in the field");
  await view.click("Process steps");
  assert.deepEqual([graphCalls().at(-1).filters.query,graphCalls().at(-1).filters.type],["ledger",undefined],"The type is not sent to a level that fixes its own types");
  view.field("graph_query").value="";
  await view.field("graph_query").dispatch("keydown",{key:"Enter"});await settle();
  assert.equal(graphCalls().at(-1).filters.query,undefined);
});

// ui-flows-review-admin-2: a long Input or Output is listed with a bounded label and read in full in its detail.
await check("an entity whose label was shortened shows its whole text in the detail",async()=>{
  const whole="Supplier invoice with remittance advice. ".repeat(40).trim(),item={...ledger(9,"Invoice intake",{type:"business_object",label:whole.slice(0,999)+"…"})};
  const view=await openAdmin(records([item],(pathName,payload)=>pathName.endsWith("/detail")?{kind:"entity",item:{...item,data:{full_label:whole},neighbor_count:0},submissions:[],entities:[],edges:[],proposals:[]}:pathName.endsWith("/history")?{...page([],payload),kind:payload.kind,id:payload.id}:undefined));
  await view.click("Entities");await view.click(item.label);
  const facts=all(view.admin).filter(node=>node.tagName==="DD").map(node=>node._text);
  assert.ok(facts.includes(whole),"The detail shows the full text, not the shortened label");
});

// knowledge-store-3 and live-draft-knowledge-5: the Processing list says what a job compared, what it
// dropped and why, and what kind of failure stopped it.
await check("a job card says what was compared, what was dropped and why",async()=>{
  const job=(n,extra)=>({id:uuid(900+n),submission_id:uuid(1),revision:n,status:"completed",attempts:1,error:"",created_at:"2026-11-13T00:00:00+00:00",process_name:"Carrier claims",detail:{},...extra});
  const jobs=[
    job(1,{detail:{candidates:8,candidates_omitted:3,proposals_returned:10,proposals_kept:9,proposals_dropped:1,dropped_reasons:{"Evidence must quote an exact participant statement.":1}}}),
    job(2,{detail:{candidates:1,candidates_omitted:0,proposals_returned:3,proposals_kept:1,proposals_dropped:2,dropped_reasons:{"Evidence must quote an exact participant statement.":1,"Proposal scopes do not match.":1}}}),
    job(3,{detail:{candidates:0,candidates_omitted:0,proposals_returned:0,proposals_kept:0,proposals_dropped:0}}),
    job(4,{status:"failed",error:"The AI provider did not complete the analysis: The model did not finish its response. Retry when the provider is available.",detail:{candidates:2,candidates_omitted:0,error_kind:"provider",error_class:"APIError"}}),
    job(5,{status:"pending",attempts:0}),job(6,{detail:undefined})];
  const view=await openAdmin((pathName,payload)=>pathName.endsWith("/browse")?{...page(payload.section==="jobs"?jobs:[],payload),section:payload.section,counts:{},analysis_limitations:""}:undefined);
  await view.click("Processing");
  const cards=all(view.admin).filter(node=>node.className==="knowledge-card").map(card=>all(card).filter(node=>node.className==="knowledge-muted").map(node=>node._text));
  assert.deepEqual(cards[0].slice(1),["Compared with 8 processes of a compatible scope; 3 more compatible processes were not compared (the most recent are used).",
    "1 of 10 suggested connections was dropped for failing a check; 9 were kept. Evidence must quote an exact participant statement. (1)"]);
  assert.deepEqual(cards[1].slice(1),["Compared with 1 process of a compatible scope.",
    "2 of 3 suggested connections were dropped for failing a check; 1 was kept. Evidence must quote an exact participant statement. (1) Proposal scopes do not match. (1)"]);
  assert.deepEqual(cards[2].slice(1),["No other process with a compatible scope to compare with."]);
  assert.match(cards[3][0],/The AI provider did not complete the analysis: The model did not finish its response\./);
  assert.deepEqual(cards[3].slice(1),["Compared with 2 processes of a compatible scope."]);
  assert.equal(cards[4].length,1,"A job that has not run says nothing about a comparison");
  assert.equal(cards[5].length,1,"An older server's job without detail is shown as before");
});

console.log(JSON.stringify({tests_passed:passed,provider_calls:0,network_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
