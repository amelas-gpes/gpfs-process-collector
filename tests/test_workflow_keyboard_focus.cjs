"use strict";
// Keyboard focus on a step or route that is off screen brings it into view in the diagram.
// Focus that comes from a click does not move the map.
// Real bundled ELK and a fictional process; no browser, network or provider calls.
const assert=require('node:assert/strict');
const {RealmELK,environment,chain}=require('./fixtures/workflow_canvas.cjs');
function branching(){
 return {title:'Pack an order',steps:[
  {id:'S1',title:'Pick the items',type:'start'},{id:'S2',title:'Glass teapot in the order?',type:'decision'},{id:'S3',title:'Wrap the glass teapot',type:'activity'},
  {id:'S4',title:'Add tissue paper',type:'activity'},{id:'S5',title:'Tape box shut',type:'activity'},{id:'S6',title:'Weigh the box',type:'activity'},{id:'S7',title:'Hand to courier',type:'end'}],
  connections:[{from:'S1',to:'S2',label:''},{from:'S2',to:'S3',label:'Glass teapot'},{from:'S2',to:'S4',label:'No glass teapot'},{from:'S3',to:'S5',label:''},{from:'S4',to:'S5',label:''},{from:'S5',to:'S6',label:''},{from:'S6',to:'S7',label:''}]};
}
let passed=0;
(async()=>{
 // ---- Diagram ----------------------------------------------------------------------------------
 // A canvas that shows about two steps of seven at reading size, as in the audit's keyboard walk.
 const open=async(graph=branching(),width=520,height=420)=>{
  const env=environment(RealmELK,width,height),canvas=env.api.create(env.container,{direction:'RIGHT'});await canvas.update(graph);
  const box=id=>canvas.layout.children.find(node=>node.id===id);
  const inside=id=>{const n=box(id),{x,y,scale}=canvas.camera;return n.x>=x&&n.y>=y&&n.x+n.width<=x+width/scale&&n.y+n.height<=y+height/scale;};
  // Tab (keyboard) or a click (pointer) moving focus to a step.
  const focus=(id,keyboard=true)=>{env.document.keyboardFocus=keyboard;env.node(canvas,id).focus();};
  return {env,canvas,box,inside,focus};
 };
 {
  const {env,canvas,inside,focus}=await open();
  assert.equal(canvas.fitMode,false,'The reproduction needs a map larger than the canvas');assert(!inside('S7'));
  const scale=canvas.getScale(),start={...canvas.camera};
  focus('S7');
  assert.notDeepEqual({...canvas.camera},start,'Tabbing to the last step must move the view');
  assert(inside('S7'),'The focused step is completely in view');assert.equal(canvas.getScale(),scale,'The zoom the reader chose is kept');
  assert.equal(env.document.activeElement.getAttribute('data-step-id'),'S7');
  assert.equal(env.node(canvas,'S7').querySelector('.workflow-node-shape').getAttribute('stroke'),'#dc6e2c','The focus outline is drawn on the step now in view');
  canvas.destroy();passed++;
 }
 {
  // The whole Tab order: every step is in view when it takes focus, forwards and backwards.
  const {canvas,inside,focus}=await open();
  const order=canvas.world.querySelectorAll('[data-step-id]').map(node=>node.getAttribute('data-step-id'));
  assert.equal(order.length,7);
  for(const id of [...order,...order.slice().reverse()]){focus(id);assert(inside(id),`${id} must be in view when Tab reaches it`);}
  canvas.destroy();passed++;
 }
 {
  // A click also focuses the step. The map must not jump under the pointer, even for a step that is only partly showing.
  const {canvas,box,inside,focus}=await open();
  const edge=box('S3');canvas.camera.x=edge.x+edge.width/2-520/canvas.camera.scale;canvas.camera.y=edge.y-40;canvas.paintView();
  assert(!inside('S3'));const camera={...canvas.camera};
  focus('S3',false);assert.deepEqual({...canvas.camera},camera,'Pointer focus leaves the view alone');
  // The same step reached by keyboard is nudged into view: only as far as needed, not re-centred.
  focus('S1',false);focus('S3');
  assert(inside('S3'));assert.equal(canvas.camera.y,camera.y,'No vertical move was needed');
  const moved=canvas.camera.x-camera.x;assert(moved>0&&moved<edge.width,'The smallest move that shows the whole step');
  const right=(edge.x+edge.width-canvas.camera.x)*canvas.camera.scale;assert(right<=520&&right>=520-24,'The step ends just inside the right edge');
  canvas.destroy();passed++;
 }
 {
  // A step that is already completely in view does not move at all when focused.
  const {canvas,inside,focus}=await open();
  assert(inside('S1'));const camera={...canvas.camera};focus('S1');assert.deepEqual({...canvas.camera},camera);
  // In the overview every step is in view: Tab never leaves Fit.
  canvas.fit();const fitted={...canvas.camera};for(const id of ['S7','S1','S4']){focus(id);assert.deepEqual({...canvas.camera},fitted);}assert.equal(canvas.fitMode,true);
  canvas.destroy();passed++;
 }
 {
  // Zoomed in so far that the step is larger than the view: its middle is shown.
  const {canvas,box,focus}=await open(branching(),300,160);
  canvas.zoomAt(2.5);focus('S6');
  const n=box('S6'),cam=canvas.camera;
  assert(Math.abs(cam.x+300/cam.scale/2-(n.x+n.width/2))<.01&&Math.abs(cam.y+160/cam.scale/2-(n.y+n.height/2))<.01);assert.equal(cam.scale,2.5);
  canvas.destroy();passed++;
 }
 {
  // A live update redraws the map and gives focus back to the step that had it. That is not the reader pressing Tab.
  const {env,canvas,focus}=await open(chain(5),900,500);
  assert.equal(canvas.fitMode,true);focus('S5');
  const longer=chain(5);longer.steps[1].title='Check the pick list against the order twice';
  await canvas.update(longer);
  assert.equal(env.document.activeElement.getAttribute('data-step-id'),'S5');assert.equal(canvas.fitMode,true,'Restoring focus after an update must not take the map out of Fit');
  canvas.destroy();passed++;
 }
 {
  // A browser that cannot answer :focus-visible keeps today's behaviour instead of failing.
  const {env,canvas,focus}=await open();
  const node=env.node(canvas,'S7'),matches=node.matches.bind(node);node.matches=selector=>{if(selector===':focus-visible')throw new SyntaxError("':focus-visible' is not a valid selector");return matches(selector);};
  const camera={...canvas.camera};focus('S7');assert.deepEqual({...canvas.camera},camera);
  canvas.destroy();passed++;
 }
 console.log(JSON.stringify({tests_passed:passed,real_elk_layout:true,network_calls:0,provider_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
