"use strict";
// Panning the map: the wheel, a drag, the arrow keys and the minimap can never slide the whole map
// out of view, and the wheel is left to the page once the edge of the map is reached.
// Real bundled ELK and a fictional process; no browser, network or provider calls.
const assert=require('node:assert/strict');
const {RealmELK,environment,chain}=require('./fixtures/workflow_canvas.cjs');
function branching(){
 return {title:'Pack an order',steps:[
  {id:'S1',title:'Pick the items',type:'start'},{id:'S2',title:'Glass teapot in the order?',type:'decision'},{id:'S3',title:'Wrap the glass teapot',type:'activity'},
  {id:'S4',title:'Add tissue paper',type:'activity'},{id:'S5',title:'Tape box shut',type:'activity'},{id:'S6',title:'Weigh the box',type:'activity'},{id:'S7',title:'Hand to courier',type:'end'}],
  connections:[{from:'S1',to:'S2',label:''},{from:'S2',to:'S3',label:'Glass teapot'},{from:'S2',to:'S4',label:'No glass teapot'},{from:'S3',to:'S5',label:''},{from:'S4',to:'S5',label:''},{from:'S5',to:'S6',label:''},{from:'S6',to:'S7',label:''}]};
}
// The Review map of the audit: a canvas of 1115x538 inside a page that can scroll.
async function open(graph=branching(),width=1115,height=538,options={}){
 const env=environment(RealmELK,width,height),canvas=env.api.create(env.container,options);await canvas.update(graph);
 // One wheel event; returns whether the canvas kept it from the page.
 const wheel=(deltaX,deltaY,keys={})=>{let kept=false;canvas.wheel({deltaX,deltaY,clientX:width/2,clientY:height/2,preventDefault(){kept=true;},...keys});return kept;};
 const miniShown=()=>{const [x,y,w,h]=canvas.mini.getAttribute('viewBox').split(' ').map(Number),view=Object.fromEntries(['x','y','width','height'].map(key=>[key,Number(canvas.miniView.getAttribute(key))]));
  return view.x+view.width>x&&view.x<x+w&&view.y+view.height>y&&view.y<y+h;};
 return {env,canvas,wheel,miniShown,seen:()=>env.visible(canvas)};
}
let passed=0;
(async()=>{
 // ---- The wheel ------------------------------------------------------------------------------
 for(const [name,dx,dy] of [['down',0,400],['up',0,-400],['right',400,0],['left',-400,0],['diagonally',300,300]]){
  const {canvas,wheel,miniShown,seen}=await open();
  const kept=[];for(let i=0;i<40;i++)kept.push(wheel(dx,dy));
  assert.notDeepEqual(seen(),[],`40 wheel notches ${name}: part of the map must still be in view`);
  assert(miniShown(),`40 wheel notches ${name}: the minimap still shows where the view is`);
  assert.equal(kept[0],true,`${name}: while the map can move, the wheel moves the map`);
  assert.equal(kept.at(-1),false,`${name}: at the edge of the map the wheel is left to the page, which scrolls`);
  assert(kept.indexOf(false)>0&&kept.slice(kept.indexOf(false)).every(value=>!value),`${name}: once the edge is reached every further notch goes to the page`);
  // Turning back is immediate: the map did not run away past the edge.
  assert.equal(wheel(-dx,-dy),true);canvas.destroy();
 }passed++;
 {
  // Inside the map nothing is held back: each notch moves the view by exactly its distance.
  const {canvas,wheel}=await open(chain(7),600,400,{direction:'RIGHT'});
  const scale=canvas.getScale(),start={...canvas.camera};
  assert.equal(wheel(120,0),true);assert(Math.abs(canvas.camera.x-start.x-120/scale)<1e-9);assert.equal(canvas.camera.y,start.y);
  assert.equal(wheel(0,40),true);assert(Math.abs(canvas.camera.y-start.y-40/scale)<1e-9);
  // A notch larger than the room that is left moves the view to the edge instead of being ignored.
  const far=wheel(100000,0);assert.equal(far,true);const edge=canvas.camera.x;assert.equal(wheel(100000,0),false);assert.equal(canvas.camera.x,edge);
  const last=canvas.layout.children.find(node=>node.id==='S7');assert(edge<last.x+last.width&&edge>last.x,'The view stops with the last step still partly on screen');
  canvas.destroy();passed++;
 }
 {
  // Zooming with Ctrl or Cmd is always the map's, and before there is a map the wheel is always the page's.
  const {canvas,wheel,seen}=await open();
  for(let i=0;i<40;i++)wheel(0,400);
  const scale=canvas.getScale();assert.equal(wheel(0,-120,{ctrlKey:true}),true);assert(canvas.getScale()>scale);assert.equal(wheel(0,120,{metaKey:true}),true);
  for(let i=0;i<30;i++)wheel(0,-240,{ctrlKey:true});
  assert.notDeepEqual(seen(),[],'Zooming far in at the edge of the map keeps part of it in view');canvas.destroy();
  const empty=environment(),blank=empty.api.create(empty.container);await blank.update({title:'Nothing yet',steps:[],connections:[]});
  let kept=false;blank.wheel({deltaX:0,deltaY:400,preventDefault(){kept=true;}});assert.equal(kept,false);blank.destroy();passed++;
 }
 // ---- Drag, arrow keys, minimap --------------------------------------------------------------
 {
  const {canvas,miniShown,seen}=await open();
  const background={closest:()=>null};let x=500,y=250;
  canvas.svg.emit('pointerdown',{target:background,pointerId:1,clientX:x,clientY:y,button:0});
  for(let i=0;i<200;i++){x-=90;y-=70;canvas.svg.emit('pointermove',{target:background,pointerId:1,clientX:x,clientY:y,button:0});}
  canvas.svg.emit('pointerup',{target:background,pointerId:1,clientX:x,clientY:y,button:0});
  assert.notDeepEqual(seen(),[],'A long drag cannot throw the map off the canvas');assert(miniShown());
  const stopped={...canvas.camera};
  // The drag is not stuck at the edge: dragging back moves at once.
  canvas.svg.emit('pointerdown',{target:background,pointerId:2,clientX:100,clientY:100,button:0});canvas.svg.emit('pointermove',{target:background,pointerId:2,clientX:160,clientY:150,button:0});canvas.svg.emit('pointerup',{target:background,pointerId:2,clientX:160,clientY:150,button:0});
  assert(canvas.camera.x<stopped.x&&canvas.camera.y<stopped.y);canvas.destroy();passed++;
 }
 for(const key of ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown']){
  const {canvas,miniShown,seen}=await open();let prevented=0;
  for(let i=0;i<150;i++)canvas.svg.emit('keydown',{key,preventDefault(){prevented++;}});
  assert.notDeepEqual(seen(),[],`150 presses of ${key} leave part of the map in view`);assert(miniShown());
  assert.equal(prevented,150,'With the map focused the arrow keys never scroll the page instead');canvas.destroy();
 }passed++;
 {
  // The minimap is letterboxed: a click in its empty margin points well outside the map.
  const {env,canvas,miniShown,seen}=await open(chain(7),600,400,{direction:'RIGHT'});
  canvas.mini.clientWidth=144;canvas.mini.clientHeight=88;
  for(const [clientX,clientY] of [[72,1],[72,87],[1,1],[143,87]]){
   canvas.mini.emit('pointerdown',{clientX,clientY});
   assert.notDeepEqual(seen(),[],`A click at ${clientX},${clientY} on the minimap must not show an empty canvas`);assert(miniShown());
  }
  // A click on the map itself in the minimap still centres the view there.
  const mid=canvas.layout.children.find(node=>node.id==='S4'),w=canvas.layout.width+20,h=canvas.layout.height+20,scale=Math.min(144/w,88/h);
  canvas.mini.emit('pointerdown',{clientX:(144-w*scale)/2+(mid.x+mid.width/2+10)*scale,clientY:(88-h*scale)/2+(mid.y+mid.height/2+10)*scale});
  assert(Math.abs(canvas.camera.x+600/canvas.camera.scale/2-(mid.x+mid.width/2))<.01);assert(env.visible(canvas).includes('S4'));canvas.destroy();passed++;
 }
 {
  // A map that does not fill its bounding box: two separate groups drawn far apart leave empty corners.
  const apart={title:'Two groups',steps:[...chain(6).steps,{id:'X1',title:'Unconnected note',type:'activity'}],connections:chain(6).connections};
  const {canvas,wheel,seen}=await open(apart,500,300,{direction:'RIGHT'});
  for(const [dx,dy] of [[400,0],[0,400],[-400,0],[0,-400],[400,400],[-400,400],[400,-400],[-400,-400]]){for(let i=0;i<30;i++)wheel(dx,dy);assert.notDeepEqual(seen(),[],`Wheel ${dx},${dy}: a step stays in view even in a corner of the map`);}
  canvas.destroy();passed++;
 }
 {
  // A reader who has zoomed into the empty space between steps can still move.
  const {canvas,wheel,seen}=await open(chain(7),600,400,{direction:'RIGHT'});
  const a=canvas.layout.children.find(node=>node.id==='S3'),b=canvas.layout.children.find(node=>node.id==='S4');
  canvas.camera={x:a.x+a.width+8,y:a.y+20,scale:2.5};canvas.paintView();
  if(b.x-a.x-a.width>600/2.5+16){assert.deepEqual(seen(),[]);assert.equal(wheel(20,0),true,'From an empty stretch inside the map the view is free to move');}
  canvas.destroy();passed++;
 }
 console.log(JSON.stringify({tests_passed:passed,real_elk_layout:true,network_calls:0,provider_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
