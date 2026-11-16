"use strict";
// What a live map update does to a reader who is following a path (the view itself: tests/test_workflow_live_view.cjs).
// Real bundled ELK and a fictional packing process; no browser, network or provider calls.
const assert=require('node:assert/strict');
const {environment,nativeTree}=require('./fixtures/workflow_canvas.cjs');
// The reader's branch: S2 (glass teapot?) -> S3 (wrap it) -> S5 (tape box shut). S4 is the other branch.
function packing(){
 return {title:'Pack an order',steps:[
  {id:'S1',title:'Pick the items',type:'start',actor:'Packer'},{id:'S2',title:'Glass teapot in the order?',type:'decision',actor:'Packer'},
  {id:'S3',title:'Wrap the glass teapot',type:'activity',actor:'Packer'},{id:'S4',title:'Add tissue paper',type:'activity',actor:'Packer'},
  {id:'S5',title:'Tape box shut',type:'activity',actor:'Packer'},{id:'S6',title:'Weigh the box',type:'activity',actor:'Packer'},{id:'S7',title:'Hand to courier',type:'end',actor:'Courier'}],
  connections:[{from:'S1',to:'S2',label:''},{from:'S2',to:'S3',label:'Glass teapot'},{from:'S2',to:'S4',label:'No glass teapot'},
   {from:'S3',to:'S5',label:'After cushioning'},{from:'S4',to:'S5',label:'After tissue'},{from:'S5',to:'S6',label:''},{from:'S6',to:'S7',label:''}]};
}
// The same process with every step id moved up by `shift` (what a provider does when it renumbers).
function renumbered(graph,shift=1){
 const id=old=>`S${Number(old.slice(1))+shift}`;
 return {...graph,steps:graph.steps.map(step=>({...step,id:id(step.id)})),connections:graph.connections.map(edge=>({...edge,from:id(edge.from),to:id(edge.to)}))};
}
async function following(graph=packing(),hops=['S3','S5'],start='S2'){
 const env=environment(),events=[],canvas=env.api.create(env.container,{onViewChange:info=>events.push(info)});
 await canvas.update(graph);assert.equal(canvas.followPath(start),true);for(const hop of hops)assert.equal(canvas.navigatePath(hop,'next'),true);
 const titles=()=>nativeTree(canvas.getPathNavigation().trail).map(id=>canvas.graph.steps.find(step=>step.id===id).title);
 return {env,canvas,events,titles,path:()=>nativeTree(canvas.getPathNavigation()),said:()=>canvas.status.textContent};
}
let passed=0;
(async()=>{
 // ---- Follow path across a live update --------------------------------------------------------
 // A pure renumbering changes nothing the reader can see: the path stays on the same steps.
 {
  const {canvas,events,titles,path,said}=await following();
  assert.equal(said(),'Tape box shut. One reported next step.');
  await canvas.update(renumbered(packing()));
  assert.equal(path().following,true);assert.equal(path().current.title,'Tape box shut','The reader stays on the step they were reading, not on the step that now has its old id');
  assert.deepEqual(titles(),['Glass teapot in the order?','Wrap the glass teapot','Tape box shut'],'The trail still runs along the branch the reader chose');
  assert.deepEqual(path().trail,['S3','S4','S6']);assert.equal(canvas.selected,'S6');
  assert.deepEqual(path().previous.map(choice=>choice.label),['After cushioning','After tissue']);
  assert.equal(path().notice,'');assert.equal(said(),'Tape box shut. One reported next step.');
  assert.equal(events.at(-1).path.current.title,'Tape box shut');
  const dimmed=canvas.world.querySelectorAll('[data-step-id]').filter(node=>node.getAttribute('opacity')==='0.28').map(node=>node.getAttribute('data-step-id'));
  assert.deepEqual(dimmed,['S2','S8'],'Dimming follows the same steps: only the first step and the last are off the path and its neighbours');
  canvas.destroy();passed++;
 }
 // A step that keeps its id and is reworded keeps the path, and the reader is told what it now says.
 {
  const {canvas,events,titles,path,said}=await following();
  const reworded=packing();reworded.steps[4].title='Seal the box with tape';
  await canvas.update(reworded);
  assert.deepEqual(path().trail,['S2','S3','S5'],'A reworded step is the same step');assert.equal(path().current.title,'Seal the box with tape');
  assert.equal(said(),'The map changed. Seal the box with tape. One reported next step.','The canvas status must not keep announcing the old title');
  assert.equal(path().notice,said(),'The path bar is given the same sentence');assert.equal(events.at(-1).path.notice,said());
  assert.deepEqual(titles(),['Glass teapot in the order?','Wrap the glass teapot','Seal the box with tape']);
  // The notice is about that update; the reader's next move on the path replaces it.
  assert.equal(canvas.navigatePath('S6','next'),true);assert.equal(path().notice,'');assert.equal(said(),'Weigh the box. One reported next step.');
  canvas.destroy();passed++;
 }
 // Two steps share a title. Rewording one of them must not move the path to the other.
 {
  const twins=packing();twins.steps[3].title='Wrap the glass teapot';
  const {canvas,path,said}=await following(twins,['S3']);
  const reworded=nativeTree(twins);reworded.steps[2].title='Wrap the teapot twice';
  await canvas.update(reworded);
  assert.deepEqual(path().trail,['S2','S3']);assert.equal(path().current.title,'Wrap the teapot twice');assert.match(said(),/^The map changed\. Wrap the teapot twice\./);
  canvas.destroy();passed++;
 }
 // A change of type alone is a change the reader is told about.
 {
  const {canvas,path,said}=await following();
  const retyped=packing();retyped.steps[4].type='subprocess';
  await canvas.update(retyped);
  assert.deepEqual(path().trail,['S2','S3','S5']);assert.match(said(),/^The map changed\. Tape box shut\./);assert.equal(path().current.type,'subprocess');
  canvas.destroy();passed++;
 }
 // The audit's real case: the id of the current step now belongs to a different step, its own
 // wording changed too, and the route the reader came along is gone. There is no step to follow to.
 {
  const {canvas,events,path,said}=await following();
  const reordered=packing();reordered.steps[4].title='Weigh the box';reordered.steps[5].title='Tape the box shut';
  reordered.connections=[{from:'S1',to:'S2',label:''},{from:'S2',to:'S3',label:'Glass teapot'},{from:'S2',to:'S4',label:'No glass teapot'},{from:'S3',to:'S6',label:'After cushioning'},{from:'S4',to:'S6',label:'After tissue'},{from:'S5',to:'S6',label:''},{from:'S6',to:'S7',label:''}];
  await canvas.update(reordered);
  assert.equal(path().following,true);assert.deepEqual(path().trail,['S5'],'A trail whose route is gone is not kept');
  assert.equal(said(),'The map changed. Follow path restarts at this step. Weigh the box. One reported next step.');
  assert.equal(path().notice,said());assert.equal(events.at(-1).path.notice,said());
  canvas.destroy();passed++;
 }
 // A route on the trail is removed while every step stays: the path restarts, and says so.
 {
  const {canvas,path,said}=await following();
  const rerouted=packing();rerouted.connections=rerouted.connections.filter(edge=>!(edge.from==='S3'&&edge.to==='S5'));rerouted.connections.push({from:'S3',to:'S6',label:'After cushioning'});
  await canvas.update(rerouted);
  assert.deepEqual(path().trail,['S5']);assert.equal(said(),'The map changed. Follow path restarts at this step. Tape box shut. One reported next step.');
  canvas.destroy();passed++;
 }
 // An earlier step of the trail is removed: same.
 {
  const {canvas,path,said}=await following();
  const shorter=packing();shorter.steps=shorter.steps.filter(step=>step.id!=='S3');shorter.connections=shorter.connections.filter(edge=>edge.from!=='S3'&&edge.to!=='S3');
  await canvas.update(shorter);
  assert.deepEqual(path().trail,['S5']);assert.match(said(),/^The map changed\. Follow path restarts at this step\. Tape box shut\./);
  canvas.destroy();passed++;
 }
 // The current step is removed: Follow path ends, and says so instead of silently showing everything.
 {
  const {canvas,events,path,said}=await following();
  const removed=packing();removed.steps=removed.steps.filter(step=>step.id!=='S5');removed.connections=removed.connections.filter(edge=>edge.from!=='S5'&&edge.to!=='S5');
  await canvas.update(removed);
  assert.equal(path().following,false);assert.equal(path().current,null);assert.deepEqual(path().trail,[]);
  assert.equal(said(),'The map changed. Follow path was reset.');assert.equal(path().notice,said());assert.equal(events.at(-1).path.notice,said());
  assert(canvas.world.querySelectorAll('[data-step-id]').every(node=>node.getAttribute('opacity')==='1'));
  // Starting again, or leaving, clears the notice.
  assert.equal(canvas.followPath('S2'),true);assert.equal(path().notice,'');assert.equal(said(),'Glass teapot in the order?. 2 reported branches. Choose the next route.');
  canvas.destroy();passed++;
 }
 // Updates that leave the path as it is say nothing: a caption, a description, a step added elsewhere.
 {
  const {canvas,path,said}=await following();
  const before=path();
  const captioned=packing();captioned.connections[3].label='Once cushioned';captioned.steps[0].description='New detail';await canvas.update(captioned);
  assert.deepEqual(path().trail,before.trail);assert.equal(path().notice,'');assert.equal(said(),'Tape box shut. One reported next step.');
  const longer=nativeTree(captioned);longer.steps.push({id:'S8',title:'File the paperwork',type:'activity'});longer.connections.push({from:'S7',to:'S8',label:''});await canvas.update(longer);
  assert.deepEqual(path().trail,before.trail);assert.equal(path().notice,'');assert.equal(said(),'Tape box shut. One reported next step.');
  canvas.destroy();passed++;
 }
 // A reader who is not following a path is told nothing about paths.
 {
  const env=environment(),canvas=env.api.create(env.container);await canvas.update(packing());canvas.select(packing().steps[4]);
  const reworded=packing();reworded.steps[4].title='Seal the box with tape';await canvas.update(reworded);
  assert.equal(canvas.status.textContent,'');assert.equal(canvas.getPathNavigation().notice,'');canvas.destroy();passed++;
 }
 console.log(JSON.stringify({tests_passed:passed,real_elk_layout:true,network_calls:0,provider_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
