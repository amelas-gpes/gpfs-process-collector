"use strict";
// How large the whole map can be drawn: boxes as wide as their text, plain arrows where there is
// no condition, and a long strip folded toward the canvas shape when the folded layout is sound.
// Real bundled ELK and fictional processes; no browser, network or provider calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {RealmELK,environment,nativeTree,chain}=require('./fixtures/workflow_canvas.cjs');
const {auditLayout}=require('./test_workflow_scenarios.cjs');
const scenarios=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/workflow-scenarios.json'),'utf8')).scenarios;
const fit=(layout,width,height)=>Math.min((width-40)/layout.width,(height-48)/layout.height);
const folds=graph=>'elk.layered.wrapping.strategy' in graph.layoutOptions;
// Places where a flat stretch of one arrow passes straight through an upright stretch of another.
function crossings(layout){
 const segments=layout.edges.flatMap(edge=>edge.sections.flatMap(section=>{const p=[section.startPoint,...(section.bendPoints||[]),section.endPoint];return p.slice(1).map((b,i)=>({edge:edge.id,a:p[i],b}));}));
 let count=0;
 segments.forEach((one,i)=>segments.slice(i+1).forEach(two=>{
  const flat=[one,two].find(s=>Math.abs(s.a.y-s.b.y)<.1),upright=[one,two].find(s=>Math.abs(s.a.x-s.b.x)<.1);
  if(one.edge===two.edge||!flat||!upright||flat===upright)return;
  const x=upright.a.x,y=flat.a.y;
  if(x>Math.min(flat.a.x,flat.b.x)+.1&&x<Math.max(flat.a.x,flat.b.x)-.1&&y>Math.min(upright.a.y,upright.b.y)+.1&&y<Math.max(upright.a.y,upright.b.y)-.1)count++;
 }));
 return count;
}
// An engine that records every request; `answer` may replace what the real engine returns.
function recording(answer){
 const calls=[];
 class Engine extends RealmELK {async layout(graph){calls.push(graph);const real=await super.layout(graph);return answer?answer(real,graph,calls.length):real;}}
 return {Engine,calls};
}
let passed=0;
(async()=>{
 const base=environment(),api=base.api,elk=new RealmELK();

 // ---- Boxes are as wide as their text needs -------------------------------------------------
 const short=api.nodeMetrics({id:'S5',title:'Tape box shut',type:'activity',actor:'Packer'});
 const long=api.nodeMetrics({id:'S6',title:'Check the weight of the packed box against the pick list before it is sealed',type:'activity',actor:'Packer'});
 assert(short.width<280&&short.width>=168,`A short title must not be given the full 280-unit box (received ${short.width})`);
 assert.equal(long.width,280,'A title that needs the full line keeps the full box');
 assert.equal(api.nodeMetrics({id:'D1',title:'Glass?',type:'decision'}).width,360,'A decision keeps its diamond, whose text area depends on its width');
 for(const type of ['activity','start','end','subprocess','document','data_store','wait'])for(const title of ['Go','Weigh the box','Send the weekly reconciliation report to the regional finance controller for sign-off','ACCOUNT_REFERENCE_'.repeat(6)]){
  const metrics=api.nodeMetrics({id:'S1',title,type,actor:'Fund accountant',system:'General ledger'});
  assert(metrics.width<=280&&metrics.width>=168,`${type}: box width stays between the smallest and the full box`);
  assert.equal(metrics.width%2,0,`${type}: an even width keeps the centred connection points on whole units`);
  for(const block of metrics.blocks){
   assert(block.x>=0&&block.x+block.width<=metrics.width,`${type}: text stays inside the narrowed box`);
   for(const line of block.lines)assert(api.measureText(line,block.size,block.weight)<=block.width,`${type}: no line is wider than its text area ("${line}")`);
  }
  assert.equal(metrics.blocks.find(block=>block.role==='title').lines.join(' ').replace(/\s+/g,''),title.replace(/\s+/g,''),`${type}: narrowing never drops or truncates the title`);
 }
 // A box only narrows; the wording wraps exactly as it did in the full-width box.
 const twoLines=api.nodeMetrics({id:'S7',title:'Wrap the glass teapot in two layers of cushioning',type:'activity'});
 assert.deepEqual(nativeTree(twoLines.blocks.find(block=>block.role==='title').lines),nativeTree(api.wrapText('Wrap the glass teapot in two layers of cushioning',232,15,600)));passed++;

 // ---- Only a condition is captioned ----------------------------------------------------------
 const packing={title:'Pack an order',steps:[
  {id:'S1',title:'Pick the items',type:'activity'},{id:'S2',title:'Glass teapot in the order?',type:'decision'},
  {id:'S3',title:'Wrap the glass teapot',type:'activity'},{id:'S4',title:'Add tissue paper',type:'activity'},
  {id:'S5',title:'Tape box shut',type:'activity'},{id:'S6',title:'Is the label printed?',type:'decision'},{id:'S7',title:'Hand to courier',type:'end'}],
  connections:[{from:'S1',to:'S2',label:'After picking'},{from:'S2',to:'S3',label:'Glass teapot'},{from:'S2',to:'S4',label:'No glass teapot'},
   {from:'S3',to:'S5',label:'After cushioning'},{from:'S4',to:'S5',label:'After tissue'},{from:'S5',to:'S6',label:''},{from:'S6',to:'S7',label:'Label printed'}]};
 const captions=graph=>graph.edges.filter(edge=>edge.labels.length).map(edge=>edge.labels[0].text);
 assert.deepEqual(captions(api.elkGraph(api.model(packing))),['Glass teapot','No glass teapot','Label printed'],
  'The two outcomes of a decision and the single recorded outcome of another are captioned; the only way out of an activity is a plain arrow');
 // A second way out turns the same wording into a condition; removing it makes the arrow plain again.
 const forked=nativeTree(packing);forked.connections.push({from:'S1',to:'S7',label:'Order cancelled'});
 assert.deepEqual(captions(api.elkGraph(api.model(forked))),['After picking','Glass teapot','No glass teapot','Label printed','Order cancelled']);
 const split={title:'Checks',steps:[{id:'P',title:'Start both checks',type:'parallel_split'},{id:'A',title:'Verify identity',type:'activity'},{id:'B',title:'Verify address',type:'activity'},{id:'J',title:'Both done',type:'parallel_join'},{id:'E',title:'Open account',type:'activity'}],
  connections:[{from:'P',to:'A',label:'Identity branch'},{from:'P',to:'B',label:'Address branch'},{from:'A',to:'J',label:'Identity verified'},{from:'B',to:'J',label:'Address verified'},{from:'J',to:'E',label:'Then'}]};
 assert.deepEqual(captions(api.elkGraph(api.model(split))),['Identity branch','Address branch'],'Branch names stay; arrivals at a join and the single continuation are plain');passed++;
 // The wording of a plain arrow is still available where the reader looks an arrow up.
 const plainView=environment(),plainCanvas=plainView.api.create(plainView.container);await plainCanvas.update(packing);
 assert.equal(plainCanvas.world.querySelectorAll('.wf-edge-label').length,3);
 assert.match(plainCanvas.edgeTitles.get('edge-3').textContent,/S3 → S5: After cushioning/,'The tooltip of a plain arrow keeps its recorded wording');
 assert.match(plainCanvas.exportSVG(),/After cushioning/,'The exported map keeps the wording in the arrow description');plainCanvas.destroy();passed++;

 // ---- A long strip is folded toward the canvas shape ----------------------------------------
 // The Interview diagram at 1440x900 with the reply box showing is about 1006x325.
 for(const [count,width,height,direction] of [[12,1006,325,'RIGHT'],[12,1115,538,'RIGHT'],[30,1006,325,'RIGHT'],[80,1006,325,'RIGHT'],[12,390,500,'DOWN']]){
  const graph=chain(count),strip=await elk.layout(api.elkGraph(api.model(graph),direction));
  const view=environment(RealmELK,width,height),canvas=view.api.create(view.container,{direction});await canvas.update(graph);
  const before=fit(strip,width,height),after=fit(canvas.layout,width,height);
  assert(after>=before*1.5,`${count} steps ${direction} on ${width}x${height}: the whole map must be drawn clearly larger than the single strip (strip ${before.toFixed(3)}, now ${after.toFixed(3)})`);
  assert.deepEqual(auditLayout(nativeTree(canvas.layout),graph,direction).issues,[],'A folded map has no overlap, no arrow through a box and every arrow on its steps');
  assert.equal(crossings(canvas.layout),0,'Folding a single line adds no crossing');
  assert.equal(canvas.layout.children.length,count);assert.equal(canvas.layout.edges.length,count-1);
  // The reading order survives: each step still hands off to the next one.
  assert(canvas.exportSVG().includes(`viewBox="0 0 ${canvas.layout.width} ${canvas.layout.height}"`),'The exported map is the folded map');
  canvas.destroy();
 }passed++;
 const eighty=environment(RealmELK,1006,325),eightyCanvas=eighty.api.create(eighty.container);await eightyCanvas.update(chain(80));eightyCanvas.fit();
 assert(eightyCanvas.getScale()>=.15,`Fit on the supported 80-step process must not shrink titles to a fraction of a pixel (scale ${eightyCanvas.getScale()})`);eightyCanvas.destroy();passed++;

 // ---- Never at the cost of a sound map ------------------------------------------------------
 // Every fictional scenario, on four canvas shapes: whatever the engine's folding does with
 // branches, loops and joins, the map shown is sound, crosses no more than the strip and is never smaller.
 let folded=0,kept=0;
 for(const fixture of scenarios)for(const [width,height] of [[1006,325],[1006,420],[1115,538],[390,500]]){
  const direction=width<640?'DOWN':'RIGHT',graph=fixture.graph;
  const strip=await elk.layout(api.elkGraph(api.model(graph),direction));
  const view=environment(RealmELK,width,height),canvas=view.api.create(view.container);await canvas.update(graph);
  const name=`${fixture.id} on ${width}x${height}`;
  assert.equal(canvas.getDirection(),direction);
  assert.deepEqual(auditLayout(nativeTree(canvas.layout),graph,direction).issues,[],`${name}: the map shown must be sound`);
  assert(crossings(canvas.layout)<=crossings(strip),`${name}: folding must not add a crossing`);
  if(canvas.layout.width===strip.width&&canvas.layout.height===strip.height)kept++;
  else{folded++;assert(fit(canvas.layout,width,height)>=fit(strip,width,height)*1.1,`${name}: a folded map is only used when it is clearly larger`);assert(graph.steps.length>=8,`${name}: a short process is never folded`);}
  canvas.destroy();
 }
 assert(folded>=8&&kept>=8,`The scenarios must exercise both outcomes (folded ${folded}, kept ${kept})`);passed++;

 // The same decisions with the engine's answer under the test's control.
 const long12=chain(12);
 const decide=async answer=>{const {Engine,calls}=recording(answer),view=environment(Engine,1006,325),canvas=view.api.create(view.container);await canvas.update(long12);const result={layout:nativeTree(canvas.layout),calls};canvas.destroy();return result;};
 const honest=await decide();
 assert.equal(honest.calls.length,2);assert(!folds(honest.calls[0])&&folds(honest.calls[1]),'The strip is laid out first; folding is a second request');
 assert.equal(honest.calls[1].layoutOptions['elk.aspectRatio'],'3.1','The fold aims at the shape of the canvas');
 const stripOnly=nativeTree(await elk.layout(honest.calls[0]));
 const same=(a,b)=>a.width===b.width&&a.height===b.height;
 assert(!same(honest.layout,stripOnly));
 const detached=await decide((real,graph)=>{if(folds(graph))real.edges[3].sections[0].endPoint.x+=60;return real;});
 assert(same(detached.layout,stripOnly),'A folded layout with an arrow off its step is discarded, not shown and not reported as a failure');
 // Both of these keep every arrow on its steps, so only the soundness check can reject them.
 const covered=await decide((real,graph)=>{if(folds(graph)){const box=real.children[5];real.edges[0].labels=[{id:'stray',text:'stray',x:box.x+8,y:box.y+8,width:40,height:20}];}return real;});
 assert(same(covered.layout,stripOnly),'A folded layout with a caption on top of a box is discarded');
 const detour=await decide((real,graph)=>{if(folds(graph)){const section=real.edges[0].sections[0],{x,y}=section.startPoint,far=y<real.height/2?real.height-2:2;section.bendPoints=[{x:x+4,y},{x:x+4,y:far},{x:x+8,y:far},{x:x+8,y}];}return real;});
 assert(same(detour.layout,stripOnly),'A folded layout whose arrow leaves its row and cuts through other rows is discarded');
 const failing=await decide((real,graph)=>{if(folds(graph))throw new Error('java.util.NoSuchElementException');return real;});
 assert(same(failing.layout,stripOnly),'An engine error while folding leaves the strip');
 const noGain=await decide((real,graph)=>folds(graph)?{...real,width:stripOnly.width*.95}:real);
 assert(same(noGain.layout,stripOnly),'A fold that barely changes the size is not worth the changed reading order');passed++;

 // ---- No second layout where folding cannot help ----------------------------------------------
 for(const [name,graph,width,height] of [['a short process',chain(7),1006,325],['a process that already fits the canvas shape',packing,1006,325],
  ['a web with many more connections than steps',{title:'Web',steps:chain(12).steps,connections:[...chain(12).connections,...Array.from({length:8},(_,i)=>({from:`S${i+1}`,to:`S${i+3}`,label:''}))]},1006,325],
  ['one step handing off to many (a single layer)',{title:'Fan',steps:chain(12).steps,connections:Array.from({length:11},(_,i)=>({from:'S1',to:`S${i+2}`,label:''}))},1006,325]]){
  const {Engine,calls}=recording(),view=environment(Engine,width,height),canvas=view.api.create(view.container);await canvas.update(graph);
  assert.equal(calls.length,1,`${name}: one layout request`);assert(!folds(calls[0]));canvas.destroy();
 }
 // A canvas that has no size yet (a hidden panel) folds toward an ordinary screen shape.
 const hiddenRun=recording(),hiddenView=environment(hiddenRun.Engine,0,0),hiddenCanvas=hiddenView.api.create(hiddenView.container,{direction:'RIGHT'});await hiddenCanvas.update(long12);
 assert.equal(hiddenRun.calls[1].layoutOptions['elk.aspectRatio'],'1.6');hiddenCanvas.destroy();passed++;

 // ---- Updates that do not move anything do not lay out again ---------------------------------
 const steady=recording(),steadyView=environment(steady.Engine,1006,325),steadyCanvas=steadyView.api.create(steadyView.container);await steadyCanvas.update(long12);
 const evidence=nativeTree(long12);evidence.steps[3].description='Corrected source description';evidence.title='Renamed';
 steadyView.container.clientHeight=538;await steadyCanvas.update(evidence);
 assert.equal(steady.calls.length,2,'A description or heading edit keeps the folded map as drawn, even after the panel changed size');
 const moved=nativeTree(evidence);moved.steps.push({id:'S13',title:'Archive the paperwork',type:'activity'});moved.connections.push({from:'S12',to:'S13',label:''});
 await steadyCanvas.update(moved);
 assert.equal(steady.calls.length,4);assert.equal(steady.calls[3].layoutOptions['elk.aspectRatio'],'1.87','The next real change folds toward the panel as it is now');steadyCanvas.destroy();passed++;

 // ---- The fold follows the canvas once its shape has settled ----------------------------------
 // In the app the panel is tall when the first layout is requested; its step bar, legend and the
 // reply box then take their room and the canvas ends up much flatter.
 const timers=[],settle=recording(),settleView=environment(settle.Engine,1006,583);
 settleView.window.setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};settleView.window.clearTimeout=id=>{if(timers[id-1])timers[id-1].fn=null;};
 const events=[],settleCanvas=settleView.api.create(settleView.container,{onViewChange:info=>events.push(info)});await settleCanvas.update(long12);
 assert.equal(settle.calls.at(-1).layoutOptions['elk.aspectRatio'],'1.73');assert.equal(timers.length,0,'Nothing is scheduled while the canvas keeps its shape');
 const tall=nativeTree(settleCanvas.layout),opening={...settleCanvas.camera};
 settleView.container.clientHeight=435;settleCanvas.refresh();settleView.container.clientHeight=325;settleCanvas.refresh();
 const waiting=timers.filter(timer=>timer.fn);
 assert.equal(waiting.length,1,'Several size changes in a row lead to one new layout');assert.equal(waiting[0].ms,200);
 assert(same(nativeTree(settleCanvas.layout),tall),'The map does not change while the panel is still settling');
 const before=settle.calls.length;waiting[0].fn();
 for(let i=0;i<50&&same(nativeTree(settleCanvas.layout),tall);i++)await new Promise(resolve=>setImmediate(resolve));
 assert.equal(settle.calls.length,before+1,'Only the fold is calculated again; the strip is kept from the first layout');
 assert.equal(settle.calls.at(-1).layoutOptions['elk.aspectRatio'],'3.1');
 assert(fit(settleCanvas.layout,1006,325)>fit(tall,1006,325)*1.1,'The map is folded for the canvas as it now is');
 assert.deepEqual(auditLayout(nativeTree(settleCanvas.layout),long12,'RIGHT').issues,[]);
 assert.equal(events.at(-1).exportReady,true);assert.equal(settleCanvas.world.querySelectorAll('[data-step-id]').length,12);
 // The reader had not moved the opening view, so the new drawing opens the same way: on its complete first step.
 const first=settleCanvas.layout.children.find(n=>n.id==='S1'),cam=settleCanvas.camera;
 assert.notDeepEqual({...cam},opening);assert(first.x>=cam.x&&first.y>=cam.y&&first.x+first.width<=cam.x+1006/cam.scale&&first.y+first.height<=cam.y+325/cam.scale);
 assert.equal(await settleCanvas.reshape(),false,'The same shape asks for nothing');assert.equal(settle.calls.length,before+1);
 // A reader who has moved keeps the step they were looking at, at the zoom they chose.
 settleCanvas.focusStep('S9',{keyboard:false});settleCanvas.zoom(.1);const chosen=settleCanvas.getScale(),held=settleCanvas.layout.children.find(n=>n.id==='S9'),offset={x:held.x-settleCanvas.camera.x,y:held.y-settleCanvas.camera.y};
 settleView.container.clientHeight=583;assert.equal(await settleCanvas.reshape(),true);
 const moved9=settleCanvas.layout.children.find(n=>n.id==='S9');
 assert.equal(settleCanvas.getScale(),chosen);assert(Math.abs(moved9.x-settleCanvas.camera.x-offset.x)<.01&&Math.abs(moved9.y-settleCanvas.camera.y-offset.y)<.01,'The step in view stays where it was on screen');
 // A fold that fails leaves the sound map that is on screen, and it stays exportable.
 const shown=nativeTree(settleCanvas.layout);settle.Engine.prototype.layout=async()=>{throw new Error('Layout failed');};
 settleView.container.clientHeight=325;assert.equal(await settleCanvas.reshape(),false);
 assert(same(nativeTree(settleCanvas.layout),shown));assert.equal(settleCanvas.layoutError,false);assert(settleCanvas.exportSVG());settleCanvas.destroy();
 // A short process has no fold to reconsider.
 const smallRun=recording(),smallView=environment(smallRun.Engine,1006,583),smallCanvas=smallView.api.create(smallView.container);await smallCanvas.update(packing);
 smallView.container.clientHeight=325;assert.equal(await smallCanvas.reshape(),false);assert.equal(smallRun.calls.length,1);smallCanvas.destroy();
 // An answer that arrives while the fold is being reconsidered wins.
 const gate=[];class Gated extends RealmELK {layout(graph){return new Promise(resolve=>gate.push(()=>resolve(super.layout(graph))));}}
 const raceView=environment(Gated,1006,583),raceCanvas=raceView.api.create(raceView.container);
 const firstDraw=raceCanvas.update(long12);for(let i=0;i<2;i++){while(gate.length<=i)await new Promise(resolve=>setImmediate(resolve));gate[i]();}await firstDraw;
 raceView.container.clientHeight=325;const reconsider=raceCanvas.reshape();
 const answer=raceCanvas.update(moved);while(gate.length<4)await new Promise(resolve=>setImmediate(resolve));gate[2]();gate[3]();
 while(gate.length<5)await new Promise(resolve=>setImmediate(resolve));gate[4]();
 assert.equal(await reconsider,false);assert.equal(await answer,true);assert.equal(raceCanvas.layout.children.length,13);raceCanvas.destroy();passed++;

 const islands={title:"Independent note",steps:[{id:"note",type:"activity",title:"Detached note"},{id:"start",type:"start",title:"Receive the filing"},{id:"finish",type:"end",title:"File the request"}],connections:[{from:"start",to:"finish"}]};
 const islandView=environment(RealmELK,1006,325),islandCanvas=islandView.api.create(islandView.container);await islandCanvas.update(islands);
 const islandNodes=new Map(islandCanvas.layout.children.map(n=>[n.id,n]));
 const entry=islandNodes.get("start"),looseNote=islandNodes.get("note");
 assert(entry.y<looseNote.y||Math.abs(entry.y-looseNote.y)<1&&entry.x<looseNote.x,"Read the routed start before the detached note");
 islandCanvas.destroy();passed++;
 elk.terminateWorker();
 console.log(JSON.stringify({tests_passed:passed,scenario_layouts_folded:folded,scenario_layouts_kept:kept,real_elk_layout:true,network_calls:0,provider_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
