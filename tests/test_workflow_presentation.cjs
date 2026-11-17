"use strict";
// The picture of a workflow map: implied start and end markers and a gateway after a step with
// several ways out (finding 7 of docs/testing/runs/2026-11-17-stress). The reported graph is the
// evidence and must come through untouched: markers are laid out and drawn, never selected,
// navigated, saved or exported. Real bundled ELK; no browser, network or provider calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {environment,nativeTree}=require('./fixtures/workflow_canvas.cjs');
const api=environment().api;
const step=(id,title,type='activity',actor='Clerk')=>({id,title,type,actor,evidence_turns:['u1']});
const edge=(from,to,label='')=>({from,to,label,evidence_turns:['u1']});
// Invoices: receive, check, then either pay or return; paying is followed by filing.
function invoices(){
 return {title:'Handle an invoice',steps:[step('S1','Receive the invoice'),step('S2','Check it against the order'),step('S3','Pay the invoice','activity','Treasury'),
  step('S4','Return it to the supplier'),step('S5','File the remittance')],
  connections:[edge('S1','S2'),edge('S2','S3','Matches the order'),edge('S2','S4','Does not match'),edge('S3','S5')]};
}
const implied=picture=>picture.steps.filter(item=>item.implied);
const reported=picture=>picture.steps.filter(item=>!item.implied);
const exits=(picture,id)=>picture.connections.filter(item=>item.from===id&&item.to!==id);
const GATEWAYS=new Set(['decision','parallel_split','parallel_join','merge']);
let passed=0;
(async()=>{
 // ---- The picture is derived; the evidence is not touched -------------------------------------
 {
  const graph=invoices(),before=JSON.stringify(graph),picture=api.present(graph);
  assert.equal(JSON.stringify(graph),before,'present must not alter the reported graph');
  assert.deepEqual(reported(picture).map(item=>item.id),['S1','S2','S3','S4','S5']);
  assert.deepEqual(implied(picture).map(item=>[item.id,item.implied]),[['~start','start'],['~end:S4','end'],['~end:S5','end'],['~gate:S2','gateway']]);
  // No marker can be mistaken for a step: the server refuses such an ID, and a marker cites nothing.
  for(const marker of implied(picture)){assert.doesNotMatch(marker.id,/^[A-Za-z0-9_-]{1,40}$/);assert.equal('evidence_turns' in marker,false);}
  // The reported connections keep their place in the list, their wording and their sources.
  graph.connections.forEach((original,index)=>{
   const drawn=picture.connections[index];
   assert.equal(drawn.to,original.to);assert.equal(drawn.label,original.label);assert.deepEqual(drawn.evidence_turns,original.evidence_turns);assert.equal(drawn.implied,undefined);
  });
  // The two ways out of the check leave a gateway, not one point of the box.
  assert.deepEqual(exits(picture,'S2').map(item=>[item.to,item.implied]),[['~gate:S2',true]]);
  assert.deepEqual(exits(picture,'~gate:S2').map(item=>[item.to,item.label]),[['S3','Matches the order'],['S4','Does not match']]);
  assert.deepEqual(exits(picture,'~start').map(item=>item.to),['S1']);
  assert.deepEqual(picture.connections.filter(item=>item.implied).map(item=>[item.from,item.to]),
   [['~start','S1'],['S4','~end:S4'],['S5','~end:S5'],['S2','~gate:S2']]);
  passed++;
 }
 // ---- What the account states is not drawn a second time --------------------------------------
 {
  const stated={title:'Stated',steps:[step('A','Order arrives','start'),step('B','Decide','decision'),step('C','Ship'),step('D','Done','end'),step('E','Cancel','end')],
   connections:[edge('A','B'),edge('B','C','In stock'),edge('B','E','Out of stock'),edge('C','D')]};
  assert.deepEqual(implied(api.present(stated)),[],'A stated start, stated ends and a named decision need no markers');
  // A lone step, or steps nobody connected, say nothing about a route.
  assert.deepEqual(implied(api.present({title:'',steps:[step('A','Only step')],connections:[]})),[]);
  assert.deepEqual(implied(api.present({title:'',steps:[step('A','One'),step('B','Two')],connections:[]})),[]);
  passed++;
 }
 // ---- Steps that are not joined to the main route stay as they are ----------------------------
 {
  const graph=invoices();graph.steps.push(step('X1','Archive old files'),step('X2','Shred after seven years'));graph.connections.push(edge('X1','X2'));
  const picture=api.present(graph);
  assert.equal(implied(picture).some(marker=>marker.of==='X2'),false,'A detached group gets no end marker');
  assert.deepEqual(picture.connections.filter(item=>item.from==='~start').map(item=>item.to),['S1'],'The start marker feeds the main route only');
  // A loop back is one way out among others: the step still gets its gateway, the loop stays a reported route.
  const loop={title:'Loop',steps:[step('A','Draft'),step('B','Review'),step('C','Publish')],connections:[edge('A','B'),edge('B','A','Changes needed'),edge('B','C','Approved')]};
  const looped=api.present(loop);
  assert.deepEqual(exits(looped,'~gate:B').map(item=>item.to),['A','C']);
  assert.deepEqual(implied(looped).map(item=>item.id),['~start','~end:C','~gate:B']);
  passed++;
 }
 // ---- Every final map of the November 17 run reads as a process diagram -----------------------
 {
  const folder=path.join(__dirname,'..','docs','testing','runs','2026-11-17-stress','cases');
  const cases=fs.existsSync(folder)?fs.readdirSync(folder).filter(name=>name.endsWith('.json')).map(name=>[name,JSON.parse(fs.readFileSync(path.join(folder,name),'utf8')).workflow]).filter(([,workflow])=>workflow?.steps?.length>1&&workflow.connections?.length):[];
  // The testing folder is left out of release archives; with the repository it holds twenty such maps.
  if(fs.existsSync(folder))assert(cases.length>=18,`Only ${cases.length} saved maps were found`);
  for(const [name,workflow] of cases){
   const before=JSON.stringify(workflow),picture=api.present(workflow);
   assert.equal(JSON.stringify(workflow),before,name);
   assert.equal(reported(picture).length,workflow.steps.length,name);
   assert.equal(picture.connections.filter(item=>!item.implied).length,workflow.connections.length,name);
   const starts=picture.steps.filter(item=>item.type==='start');
   assert(starts.length>=1,`${name}: no start`);
   assert(implied(picture).filter(item=>item.implied==='start').length<=1,`${name}: more than one start marker`);
   // No branch leaves an ordinary box directly.
   for(const item of reported(picture))if(!GATEWAYS.has(item.type))assert(exits(picture,item.id).length<=1,`${name}: ${item.id} has several ways out of a box`);
   // The picture is a valid canvas model and can be laid out.
   const model=api.model(picture,false);assert.equal(model.steps.length,picture.steps.length);
  }
  passed++;
 }
 // ---- On the canvas: drawn, but not a control and not part of what the map reports -----------
 {
  const env=environment(),events=[],canvas=env.api.create(env.container,{presentation:true,onSelectStep:selected=>events.push(selected.id)});
  await canvas.update(invoices());
  const world=canvas.world,ids=selector=>world.querySelectorAll(selector);
  assert.equal(ids('[data-step-id]').length,5,'Five reported steps are the controls');
  assert.equal(ids('[data-edge-id]').length,4,'Four reported connections');
  assert.deepEqual(nativeTree(ids('[data-implied]').map(node=>node.getAttribute('data-implied'))).sort(),['end','end','gateway','start']);
  assert.equal(ids('[data-implied-edge]').length,4);
  for(const marker of ids('[data-implied]')){
   assert.equal(marker.getAttribute('data-step-id'),null);assert.equal(marker.getAttribute('tabindex'),null);assert.equal(marker.getAttribute('role'),null);
   assert.equal(marker.getAttribute('aria-hidden'),'true');
  }
  // The canvas still reports and navigates the evidence.
  assert.deepEqual(nativeTree(canvas.graph.steps.map(item=>item.id)),['S1','S2','S3','S4','S5']);
  assert.match(canvas.description.textContent,/^5 reported steps and 4 reported connections\./);
  assert.equal(canvas.followPath('S2'),true);
  assert.deepEqual(nativeTree(canvas.getPathNavigation().next.map(choice=>[choice.id,choice.label])),[['S3','Matches the order'],['S4','Does not match']],'The path leads to the reported steps, not to the gateway');
  assert.equal(canvas.navigatePath('S3','next'),true);canvas.leavePath();
  // Laid out by the engine like any node: nothing overlaps a marker.
  const boxes=nativeTree(canvas.layout.children);
  assert.equal(boxes.length,9);
  for(let a=0;a<boxes.length;a++)for(let b=a+1;b<boxes.length;b++){
   const one=boxes[a],two=boxes[b];
   assert(one.x+one.width<=two.x||two.x+two.width<=one.x||one.y+one.height<=two.y||two.y+two.height<=one.y,`${one.id} overlaps ${two.id}`);
  }
  const marker=boxes.find(node=>node.id==='~start'),first=boxes.find(node=>node.id==='S1');
  assert.equal(marker.width,36);assert(marker.x+marker.width<first.x,'The start marker stands in front of the first step');
  // The exported file says its steps and routes carry their evidence: the markers are left out of it.
  const svg=canvas.exportSVG({title:'Handle an invoice',state:'Working map',date:'2026-11-17'});
  assert.doesNotMatch(svg,/data-implied/);assert.match(svg,/Receive the invoice/);assert.match(svg,/Matches the order/);
  canvas.destroy();passed++;
 }
 // ---- Without the option the canvas draws the reported graph alone ----------------------------
 {
  const env=environment(),canvas=env.api.create(env.container);await canvas.update(invoices());
  assert.equal(canvas.world.querySelectorAll('[data-implied]').length,0);assert.equal(canvas.layout.children.length,5);assert.equal(canvas.layout.edges.length,4);
  canvas.destroy();passed++;
 }
 // ---- A map at the size limit can still be drawn with its markers -----------------------------
 {
  const steps=Array.from({length:80},(_,index)=>step(`S${index+1}`,`Step ${index+1}`)),connections=steps.slice(1).map((item,index)=>edge(steps[index].id,item.id));
  const env=environment(),canvas=env.api.create(env.container,{presentation:true});
  assert.equal(await canvas.update({title:'Eighty steps',steps,connections}),true);
  assert.equal(canvas.layout.children.length,82);assert.equal(canvas.world.querySelectorAll('[data-step-id]').length,80);
  canvas.destroy();passed++;
 }
 console.log(JSON.stringify({tests_passed:passed,real_elk_layout:true,network_calls:0,provider_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
