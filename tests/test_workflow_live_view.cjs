"use strict";
// Where the reader's view ends up when a live update re-lays-out the map they are looking at.
// Real bundled ELK and a fictional process; no browser, network or provider calls.
const assert=require('node:assert/strict');
const {RealmELK,environment,chain}=require('./fixtures/workflow_canvas.cjs');
let passed=0;
(async()=>{
 // Where a step is drawn on screen, in canvas pixels.
 const onScreen=(canvas,id)=>{const node=canvas.layout.children.find(item=>item.id===id);return {x:(node.x-canvas.camera.x)*canvas.camera.scale,y:(node.y-canvas.camera.y)*canvas.camera.scale};};
 const near=(a,b)=>Math.abs(a.x-b.x)<.01&&Math.abs(a.y-b.y)<.01;
 const without=(graph,ids)=>({...graph,steps:graph.steps.filter(step=>!ids.includes(step.id)),connections:graph.connections.filter(edge=>!ids.includes(edge.from)&&!ids.includes(edge.to))});
 // Seven steps in one strip (a process this short is never folded) on a canvas that shows about two of them.
 const reader=async()=>{const env=environment(RealmELK,400,300),canvas=env.api.create(env.container,{direction:'RIGHT'});await canvas.update(chain(7));return {env,canvas};};
 const toStart=canvas=>{const first=canvas.layout.children.find(node=>node.id==='S1');canvas.camera.x=first.x-30;canvas.camera.y=first.y-30;canvas.paintView();};
 // The audit's case: a late step picked in the Step list stays selected, the reader drags back to
 // the start, and the next answer removes steps upstream of the selected one.
 {
  const {env,canvas}=await reader();
  canvas.focusStep('S7',{readable:true,keyboard:false,select:true});assert.equal(canvas.selected,'S7');toStart(canvas);
  assert.deepEqual(env.visible(canvas),['S1','S2'],'The reader is at the start; the selected step is far off screen');
  const scale=canvas.getScale(),held=onScreen(canvas,'S2');
  const joined=without(chain(7),['S4','S5','S6']);joined.connections.push({from:'S3',to:'S7',label:''});
  await canvas.update(joined);
  assert.notDeepEqual(env.visible(canvas),[],'An update upstream of an off-screen selected step must not slide the view off the map');
  assert(near(onScreen(canvas,'S2'),held),'The steps the reader was looking at stay where they were');
  assert.equal(canvas.getScale(),scale);assert.equal(canvas.selected,'S7','The selection is kept; it just no longer drags the view');
  canvas.destroy();passed++;
 }
 // The selected step in view is still the anchor: a step inserted before it does not move it on screen.
 {
  const {env,canvas}=await reader();
  canvas.focusStep('S4',{readable:true,keyboard:false,select:true});const held=onScreen(canvas,'S4');
  const inserted=chain(7);inserted.steps.splice(2,0,{id:'S2b',title:'Check the pick list twice',type:'activity',actor:'Packer'});
  inserted.connections=inserted.connections.filter(edge=>!(edge.from==='S2'&&edge.to==='S3'));inserted.connections.push({from:'S2',to:'S2b',label:''},{from:'S2b',to:'S3',label:''});
  await canvas.update(inserted);
  assert(near(onScreen(canvas,'S4'),held),'A selected step the reader can see stays under their eyes');assert(env.visible(canvas).includes('S4'));
  canvas.destroy();passed++;
 }
 // Selected step off screen and the step in the middle of the view removed: the nearest surviving step holds the view.
 {
  const {env,canvas}=await reader();
  canvas.focusStep('S7',{readable:true,keyboard:false,select:true});
  const second=canvas.layout.children.find(node=>node.id==='S2');canvas.camera.x=second.x+second.width/2-200/canvas.camera.scale;canvas.camera.y=second.y-30;canvas.paintView();
  assert(env.visible(canvas).includes('S1')&&!env.visible(canvas).includes('S7'));const held=onScreen(canvas,'S1');
  const removed=without(chain(7),['S2']);removed.connections.push({from:'S1',to:'S3',label:''});
  await canvas.update(removed);
  assert(near(onScreen(canvas,'S1'),held),'A neighbouring step that survived keeps its place');assert(env.visible(canvas).includes('S1'));
  canvas.destroy();passed++;
 }
 // No step survives under its id (a replaced map): whatever happens, the reader is not left on an empty canvas.
 {
  const {env,canvas}=await reader();
  canvas.focusStep('S7',{readable:true,keyboard:false,select:true});
  const replaced={title:'Another process',steps:[{id:'T1',title:'Open the claim',type:'activity'},{id:'T2',title:'Close the claim',type:'activity'}],connections:[{from:'T1',to:'T2',label:''}]};
  await canvas.update(replaced);
  assert.notDeepEqual(env.visible(canvas),[],'A much smaller replacement map must be brought into view');assert.equal(canvas.selected,null);
  canvas.destroy();passed++;
 }
 // Only something off screen changed (a reworded step far along the strip): the view does not move.
 {
  const {env,canvas}=await reader();
  canvas.focusStep('S7',{readable:true,keyboard:false,select:true});toStart(canvas);const held=[onScreen(canvas,'S1'),onScreen(canvas,'S2')];
  const before=canvas.layout.children.find(node=>node.id==='S7').x;
  const reworded=chain(7);reworded.steps[5].title='Weigh the packed box on the despatch scale and note it';
  await canvas.update(reworded);
  assert.notEqual(canvas.layout.children.find(node=>node.id==='S7').x,before,'The off-screen selected step did move');
  assert(near(onScreen(canvas,'S1'),held[0])&&near(onScreen(canvas,'S2'),held[1]),'What the reader sees does not move');assert.deepEqual(env.visible(canvas),['S1','S2']);
  canvas.destroy();passed++;
 }
 // Follow path found its step again under another number: the view stays on that step, not on the step that now has its old number.
 {
  const packing={title:'Pack an order',steps:[{id:'S1',title:'Pick the items',type:'start'},{id:'S2',title:'Wrap the glass teapot',type:'activity'},{id:'S3',title:'Add tissue paper',type:'activity'},{id:'S4',title:'Tape box shut',type:'activity'},{id:'S5',title:'Weigh the box',type:'activity'},{id:'S6',title:'Print the label',type:'activity'},{id:'S7',title:'Hand to courier',type:'end'}],
   connections:Array.from({length:6},(_,i)=>({from:`S${i+1}`,to:`S${i+2}`,label:''}))};
  const env=environment(RealmELK,400,300),canvas=env.api.create(env.container,{direction:'RIGHT'});await canvas.update(packing);
  assert.equal(canvas.followPath('S4'),true);assert.equal(canvas.navigatePath('S5','next'),true);const held=onScreen(canvas,'S5');
  // Every number moves up by two because two steps were put in front.
  const shift=id=>`S${Number(id.slice(1))+2}`;
  const renumbered={title:packing.title,steps:[{id:'S1',title:'Open the order',type:'start'},{id:'S2',title:'Check the stock',type:'activity'},...packing.steps.map(step=>({...step,id:shift(step.id),type:step.type==='start'?'activity':step.type}))],
   connections:[{from:'S1',to:'S2',label:''},{from:'S2',to:'S3',label:''},...packing.connections.map(edge=>({...edge,from:shift(edge.from),to:shift(edge.to)}))]};
  await canvas.update(renumbered);
  assert.equal(canvas.getPathNavigation().current.title,'Weigh the box');assert.equal(canvas.selected,'S7');
  assert(near(onScreen(canvas,'S7'),held),'The followed step stays where it was on screen under its new number');
  canvas.destroy();passed++;
 }
 console.log(JSON.stringify({tests_passed:passed,real_elk_layout:true,network_calls:0,provider_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
