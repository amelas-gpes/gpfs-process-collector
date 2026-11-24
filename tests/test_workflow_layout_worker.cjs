"use strict";
// Layout cost and where it runs: the fast placement for heavily connected maps, the worker script,
// and the page side that shares one worker, stops superseded or over-budget layouts and falls
// back to the page when no worker can start. Real bundled ELK; no browser, network or provider calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {RealmELK,environment,nativeTree,chain}=require('./fixtures/workflow_canvas.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const until=async(test,what)=>{for(let i=0;i<2000;i++){if(test())return;await tick();}throw new Error('Timed out waiting for '+what);};
// The audit's synthetic worst case: a chain plus random forward and backward cross-links.
function dense(steps,connections){
 let seed=11;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
 const graph={title:'Dense',steps:Array.from({length:steps},(_,i)=>({id:`S${i+1}`,title:`Reported activity number ${i+1} with a normal title`,type:i%7===3?'decision':'activity',actor:'Fund accountant',system:'Ledger'})),connections:[]};
 for(let i=0;i<steps-1&&graph.connections.length<connections;i++)graph.connections.push({from:`S${i+1}`,to:`S${i+2}`,label:random()<.5?'Approved and ready':''});
 while(graph.connections.length<connections){
  const a=1+Math.floor(random()*steps);let b=1+Math.floor(random()*steps);
  if(random()>.15&&b<a)b=Math.min(steps,a+1+Math.floor(random()*6));
  graph.connections.push({from:`S${a}`,to:`S${b}`,label:random()<.5?'Exception found':''});
 }
 return graph;
}
// A stand-in for the browser's Worker. mode: 'real' answers with the real engine, 'silent' never
// answers, 'dead' reports that the script could not start.
function workers(env,mode='real'){
 const made=[],engine=new RealmELK();
 env.window.Worker=class {
  constructor(url){this.url=url;this.posts=[];this.terminated=false;this.mode=typeof mode==='function'?mode(made.length):mode;if(this.mode==='blocked')throw new Error('Refused');made.push(this);
   if(this.mode==='dead')setImmediate(()=>this.onerror?.({preventDefault(){}}));}
  postMessage(message){this.posts.push(message);if(this.mode!=='real')return;
   engine.layout(message.graph).then(layout=>{if(!this.terminated)this.onmessage?.({data:{id:message.id,layout}});},error=>{if(!this.terminated)this.onmessage?.({data:{id:message.id,error:String(error.message||error)}});});}
  terminate(){this.terminated=true;}
 };
 return made;
}
function clock(env){
 const timers=[];
 env.window.setTimeout=(fn,ms)=>{timers.push({fn,ms,live:true});return timers.length;};
 env.window.clearTimeout=id=>{if(timers[id-1])timers[id-1].live=false;};
 return timers;
}
const retitled=title=>{const graph=chain(5);graph.steps[0].title=title;return graph;};
let passed=0;
(async()=>{
 const base=environment(),api=base.api;

 // ---- Heavily connected maps use the placement that stays fast ------------------------------
 const placement=graph=>api.elkGraph(api.model(graph),'RIGHT').layoutOptions['elk.layered.nodePlacement.strategy'];
 assert.equal(placement(dense(40,60)),'NETWORK_SIMPLEX','Up to 60 connections keep the compact placement');
 assert.equal(placement(dense(40,61)),'BRANDES_KOEPF','More than 60 connections use the fast placement');
 assert.equal(placement(dense(80,150)),'BRANDES_KOEPF');
 assert.equal(placement(chain(80)),'BRANDES_KOEPF');assert.equal(placement(chain(12)),'NETWORK_SIMPLEX');
 // Folding adds long return routes, so the folded request changes over at half the size.
 const folded=graph=>api.elkGraph(api.model(graph),'RIGHT',2).layoutOptions['elk.layered.nodePlacement.strategy'];
 assert.equal(folded(dense(28,30)),'NETWORK_SIMPLEX');assert.equal(folded(dense(28,31)),'BRANDES_KOEPF');passed++;

 // The largest supported map (80 steps, 150 connections) took 36 to 81 s here before; a browser tab was frozen for that long.
 const heavy=dense(80,150),started=Date.now();
 const heavyView=environment(),heavyCanvas=heavyView.api.create(heavyView.container);
 assert.equal(await heavyCanvas.update(heavy),true);
 const diagramMs=Date.now()-started;
 assert.equal(heavyCanvas.layout.children.length,80);assert.equal(heavyCanvas.layout.edges.length,150);assert(heavyCanvas.exportSVG());heavyCanvas.destroy();
 assert(diagramMs<20000,`The diagram of the largest supported map must be laid out within 20 s even on a busy machine (took ${diagramMs} ms)`);
 passed++;

 // ---- The worker script ---------------------------------------------------------------------
 // Run web/workflow-layout-worker.js as a worker would: its own realm, importScripts, self.
 const bundle=fs.readFileSync(path.join(__dirname,'../web/vendor/elk.bundled.js'),'utf8'),script=fs.readFileSync(path.join(__dirname,'../web/workflow-layout-worker.js'),'utf8');
 const imported=[],answers=[],realm={setTimeout,clearTimeout,console};realm.self=realm;
 const context=vm.createContext(realm);
 realm.importScripts=(...urls)=>{imported.push(...urls);vm.runInContext(bundle,context);};
 realm.postMessage=message=>answers.push(JSON.parse(JSON.stringify(message)));
 vm.runInContext(script,context);
 assert.deepEqual(imported,['/vendor/elk.bundled.js'],'The worker loads only the locally bundled engine');
 const deliver=message=>realm.onmessage({data:vm.runInContext('(text=>JSON.parse(text))',context)(JSON.stringify(message))});
 const request=api.elkGraph(api.model(chain(5)));
 deliver({id:7,graph:request});await until(()=>answers.length===1,'the worker to answer');
 assert.equal(answers[0].id,7);assert.equal(answers[0].error,undefined);
 const direct=nativeTree(await new RealmELK().layout(request));
 assert.deepEqual(answers[0].layout.children.map(({id,x,y})=>({id,x,y})),direct.children.map(({id,x,y})=>({id,x,y})),'The worker returns the engine\'s own layout');
 assert.equal(answers[0].layout.edges.length,4);
 deliver({id:8,graph:{id:'broken',children:[{id:'a'}],edges:[{id:'e',sources:['a'],targets:['missing']}]}});await until(()=>answers.length===2,'the worker to report a failure');
 assert.equal(answers[1].id,8);assert.equal(typeof answers[1].error,'string');assert(answers[1].error.length>0);assert.equal(answers[1].layout,undefined);
 deliver({id:9,graph:request});await until(()=>answers.length===3,'the worker to keep working after a failure');assert.equal(answers[2].layout.children.length,5);passed++;
 // The server lists every script it serves.
 assert.match(fs.readFileSync(path.join(__dirname,'../server.py'),'utf8'),/"\/workflow-layout-worker\.js": \("workflow-layout-worker\.js", "text\/javascript; charset=utf-8"\)/);passed++;

 // ---- One worker for the page ---------------------------------------------------------------
 const page=environment(null);let engineLoads=0;page.window.CollectorWorkflowAssets={loadEngine(){engineLoads++;return Promise.resolve(RealmELK);}};
 const made=workers(page),timers=clock(page);
 const one=page.api.create(page.container),otherContainer=page.document.createElement('div'),two=page.api.create(otherContainer);
 assert.equal(await one.update(chain(5)),true);assert.equal(await two.update(retitled('Second map')),true);
 assert.equal(made.length,1,'Both diagrams share one worker');assert.equal(made[0].url,'/workflow-layout-worker.js');
 assert.equal(made[0].posts.length,2);assert.equal(new Set(made[0].posts.map(post=>post.id)).size,2);
 assert.equal(engineLoads,0,'With a worker the page never loads the engine itself');assert.equal(one.engine,undefined);
 assert.equal(one.world.querySelectorAll('[data-step-id]').length,5);assert(one.exportSVG());
 assert(timers.length>=2&&timers.every(timer=>timer.ms===8000&&!timer.live),'Each layout runs against an 8 s budget that is cleared when it answers');
 // Closing one diagram leaves the shared worker for the other.
 one.destroy();assert.equal(made[0].terminated,false);assert.equal(await two.update(retitled('Second map, revised')),true);assert.equal(made.length,1);two.destroy();passed++;

 // ---- A layout nobody is waiting for is stopped ---------------------------------------------
 const busy=environment(null),busyMade=workers(busy,index=>index===0?'silent':'real');clock(busy);
 const busyCanvas=busy.api.create(busy.container),events=[];busyCanvas.options.onViewChange=info=>events.push(info);
 const older=busyCanvas.update(retitled('Older answer'));await tick();
 assert.equal(busyMade.length,1);assert.equal(busyMade[0].posts.length,1);
 const newer=busyCanvas.update(retitled('Newer answer'));
 assert.equal(await older,false);assert.equal(await newer,true);
 assert.equal(busyMade[0].terminated,true,'The computation for the replaced map is ended, not left to finish first');
 assert.equal(busyMade.length,2);assert.equal(busyMade[1].posts.length,1);assert.equal(busyCanvas.graph.steps[0].title,'Newer answer');
 // A change that moves nothing keeps the running layout.
 const still=environment(null),stillMade=workers(still,'silent');clock(still);const stillCanvas=still.api.create(still.container);
 const evidence=chain(5),firstAsk=stillCanvas.update(evidence);await tick();evidence.steps[0].description='New source detail';const secondAsk=stillCanvas.update(evidence);await tick();
 assert.equal(stillMade.length,1);assert.equal(stillMade[0].posts.length,1);assert.equal(stillMade[0].terminated,false);
 // Closing the diagram ends its layout.
 stillCanvas.destroy();assert.equal(stillMade[0].terminated,true);assert.equal(await firstAsk,false);assert.equal(await secondAsk,false);
 // Two diagrams: the one that waits its turn is dropped without disturbing the one that is running.
 const pair=environment(null),pairMade=workers(pair,'silent');clock(pair);
 const front=pair.api.create(pair.container),back=pair.api.create(pair.document.createElement('div'));
 const frontAsk=front.update(chain(5)),backAsk=back.update(retitled('Waiting'));await tick();
 assert.equal(pairMade[0].posts.length,1,'One layout runs at a time');back.destroy();assert.equal(await backAsk,false);
 assert.equal(pairMade[0].terminated,false);assert.equal(pairMade.length,1);front.destroy();assert.equal(await frontAsk,false);passed++;

 // ---- A layout that exceeds its budget is stopped and reported ------------------------------
 const slow=environment(null),slowMade=workers(slow,index=>index===0?'silent':'real'),slowTimers=clock(slow),slowEvents=[];
 const slowCanvas=slow.api.create(slow.container,{onViewChange:info=>slowEvents.push(info)});
 const stuck=slowCanvas.update(chain(5));await tick();
 assert.equal(slowTimers.length,1);assert.equal(slowTimers[0].ms,8000);assert.equal(slowEvents.at(-1).updating,true);
 slowTimers[0].fn();
 await assert.rejects(stuck,/took too long/);
 assert.equal(slowMade[0].terminated,true,'The worker is ended, so the tab is not left computing');
 assert.equal(slowEvents.at(-1).updating,false);assert.equal(slowEvents.at(-1).exportReady,false);assert.equal(slowCanvas.exportSVG(),null,'The app shows its list of steps with Retry diagram');
 // Retry starts a fresh worker.
 assert.equal(await slowCanvas.update(chain(5)),true);assert.equal(slowMade.length,2);assert.equal(slowEvents.at(-1).exportReady,true);
 // An engine error is reported as such and the worker stays.
 const refusing=slowCanvas.update({title:'Unroutable',steps:chain(5).steps,connections:chain(5).connections});
 await refusing;const worker=slowMade[1];worker.mode='silent';
 const failing=slowCanvas.update(retitled('Engine failure'));await tick();worker.onmessage({data:{id:worker.posts.at(-1).id,error:'org.eclipse.elk.core.UnsupportedGraphException'}});
 await assert.rejects(failing,/UnsupportedGraphException/);assert.equal(worker.terminated,false);
 worker.mode='real';assert.equal(await slowCanvas.update(retitled('After the failure')),true);assert.equal(slowMade.length,2);
 // A worker that stops after it has worked is replaced for the next layout.
 worker.mode='silent';const crashing=slowCanvas.update(retitled('Crash'));await tick();worker.onerror({preventDefault(){}});
 await assert.rejects(crashing,/engine stopped/);assert.equal(await slowCanvas.update(retitled('After the crash')),true);assert.equal(slowMade.length,3);slowCanvas.destroy();passed++;

 // ---- No worker: the page lays out as before -------------------------------------------------
 for(const mode of ['dead','blocked']){
  const plain=environment(RealmELK),plainMade=workers(plain,mode);clock(plain);
  const first=plain.api.create(plain.container),second=plain.api.create(plain.document.createElement('div'));
  const asks=[first.update(chain(5)),second.update(retitled('Queued behind it'))];
  assert.deepEqual(await Promise.all(asks),[true,true],`${mode}: both diagrams are drawn by the engine in the page`);
  assert.equal(first.layout.children.length,5);assert.equal(second.layout.children.length,5);
  const count=plainMade.length;
  assert.equal(await first.update(retitled('Later change')),true);assert.equal(plainMade.length,count,`${mode}: no further worker is attempted`);
  first.destroy();second.destroy();
 }
 // The engine is fetched by the page only in that case.
 const lazy=environment(null);let loads=0;lazy.window.CollectorWorkflowAssets={loadEngine(){loads++;return Promise.resolve(RealmELK);}};workers(lazy,'dead');clock(lazy);
 const lazyCanvas=lazy.api.create(lazy.container);assert.equal(await lazyCanvas.update(chain(5)),true);assert.equal(loads,1);lazyCanvas.destroy();passed++;

 console.log(JSON.stringify({tests_passed:passed,largest_map_diagram_ms:diagramMs,real_elk_layout:true,network_calls:0,provider_calls:0,real_browser:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
