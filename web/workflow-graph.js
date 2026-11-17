/* Workflow canvas: source-grounded graph data + locally bundled ELK layout. */
"use strict";
(function(scope) {
  const NS="http://www.w3.org/2000/svg", FONT="'Source Sans 3', 'Source Sans Pro', 'Segoe UI', system-ui, sans-serif";
  const PALETTE=["#4f6178","#7a6c56","#a65c46","#303033","#646466","#b0561f"];
  let serial=0;
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  const string=value=>typeof value==="string"?value:"";
  const svgNode=(doc,name,attrs={},text)=>{const node=doc.createElementNS(NS,name);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value)));if(text!==undefined)node.textContent=text;return node;};
  const styles=(node,values)=>Object.assign(node.style,values);
  const TYPES={activity:{label:"Activity",fill:"#ffffff",stroke:"#cad2da"},decision:{label:"Decision",fill:"#fffbef",stroke:"#bca570"},
    start:{label:"Start",fill:"#eef7f2",stroke:"#789c89"},end:{label:"End",fill:"#edf1f7",stroke:"#71859e"},
    parallel_split:{label:"Parallel split",fill:"#eff4fc",stroke:"#8398b8"},parallel_join:{label:"Parallel join",fill:"#eff4fc",stroke:"#8398b8"},merge:{label:"Merge alternatives",fill:"#f5f3fa",stroke:"#a395b5"},
    wait:{label:"Wait",fill:"#fbf3eb",stroke:"#c49c77"},subprocess:{label:"Subprocess",fill:"#f6f3fa",stroke:"#a395b5"},
    document:{label:"Document",fill:"#f1f7f8",stroke:"#85a8ae"},data_store:{label:"Stored data",fill:"#f1f7f8",stroke:"#85a8ae"}};
  const MIN_BOX_TEXT=120,DENSE_CONNECTIONS=60,MARKER_SIZE=36;
  let measureContext,graphemeSegmenter;
  const measurements=new Map();
  function measureText(value,size=14,weight=400){
    const text=string(value),key=`${size}|${weight}|${text}`;
    if(measurements.has(key))return measurements.get(key);
    if(measureContext===undefined){try{measureContext=scope.document?.createElement("canvas")?.getContext?.("2d")||null;}catch{measureContext=null;}}
    let width;
    if(measureContext){measureContext.font=`${weight} ${size}px ${FONT}`;width=measureContext.measureText(text).width;}
    else width=Array.from(text).reduce((sum,ch)=>sum+size*(/[\u2e80-\uffff]/u.test(ch)?1:/[MW@#%]/.test(ch)?.9:/[il.,'\s]/.test(ch)?.32:.62),0);
    // A small allowance protects exported SVGs when a compatible fallback font is used.
    width=Math.ceil(width*1.035);if(measurements.size>8000)measurements.clear();measurements.set(key,width);return width;
  }
  function wrapText(value,width,size=14,weight=400){
    const lines=[];let line="";
    for(const paragraph of string(value).split(/\r?\n/)){
      for(const word of paragraph.split(/\s+/u).filter(Boolean)){
        if(line&&measureText(`${line} ${word}`,size,weight)>width){lines.push(line);line="";}
        if(measureText(word,size,weight)>width){
          if(graphemeSegmenter===undefined)graphemeSegmenter=typeof Intl!=="undefined"&&Intl.Segmenter?new Intl.Segmenter(undefined,{granularity:"grapheme"}):null;
          for(const item of graphemeSegmenter?graphemeSegmenter.segment(word):Array.from(word)){
            const ch=typeof item==="string"?item:item.segment;
            if(line&&measureText(line+ch,size,weight)>width && !/^[、。，．！？；：）】〕」』ぁぃぅぇぉっゃゅょァィゥェォッャュョ]/u.test(ch)){lines.push(line);line="";}line+=ch;
          }
        }else line+=(line?" ":"")+word;
      }
      if(line){lines.push(line);line="";}
    }
    return lines.length?lines:[""];
  }
  const known=value=>Boolean(string(value).trim())&&!/^(?:unknown(?:\s*\/\s*tbd)?|tbd|not established|not applicable|n\/?a)$/i.test(string(value).trim());
  function nodeMetrics(step){
    // A marker of the picture (see present): a small circle or diamond with no text of its own.
    if(step.implied)return {type:TYPES[step.type]?step.type:"activity",width:MARKER_SIZE,height:MARKER_SIZE,contentWidth:0,contentHeight:0,blocks:[],diamond:step.type==="decision"};
    const type=TYPES[step.type]?step.type:"activity",diamond=["decision","parallel_split","parallel_join","merge"].includes(type);
    let width=diamond?360:280,contentWidth=diamond?186:type==="wait"?208:232;

    const blocks=[];
    const add=(role,text,size,weight,lineHeight,gap)=>{const lines=wrapText(text,contentWidth,size,weight);blocks.push({role,lines,size,weight,lineHeight,gap,width:contentWidth,height:lines.length*lineHeight});};
    add("kind",step.kind_caption||`${step.id} · ${["parallel_split","parallel_join"].includes(type)?"+ ":type==="merge"?"× ":""}${TYPES[type].label.toUpperCase()}`,10,600,14,8);
    add("title",step.title||"Untitled step",15,600,20,10);
    if(known(step.actor))add("actor",step.actor,11,600,15,2);
    if(known(step.system))add("system",step.system,11,400,15,0);
    if(!diamond){
      // A box is only as wide as its longest line needs, so a map of short titles is not
      // stretched into a strip. The lines were wrapped at the full width and stay as they are.
      const longest=Math.max(...blocks.flatMap(block=>block.lines.map(line=>measureText(line,block.size,block.weight))));
      // An even width keeps the centred connection points on whole units.
      const narrowed=clamp(2*Math.ceil(longest/2),MIN_BOX_TEXT,contentWidth);
      width-=contentWidth-narrowed;contentWidth=narrowed;
      for(const block of blocks)block.width=contentWidth;
    }
    const contentHeight=blocks.reduce((sum,b,i)=>sum+b.height+(i<blocks.length-1?b.gap:0),0);
    const top=type==="data_store"?32:22,bottom=type==="document"?34:22;
    const height=diamond?Math.max(192,Math.ceil(contentHeight*2.3+8)):Math.max(type==="start"||type==="end"?104:116,contentHeight+top+bottom);
    let y=diamond?(height-contentHeight)/2:top;
    for(const block of blocks){block.x=(width-contentWidth)/2-(type==="wait"?8:0);block.y=y;y+=block.height+block.gap;}
    return {type,width,height,contentWidth,contentHeight,blocks,diamond};
  }
  function edgeMetrics(value){const width=clamp(measureText(value,11,500)+24,44,200),lines=wrapText(value,width-24,11,500);return {width,height:lines.length*15+14,lines};}
  const stepTooltip=step=>`${step.id}: ${step.title}\n${step.description||""}\nOwner: ${step.actor||"Not established"}\nSystem: ${step.system||"Not established"}`;
  const edgeTooltip=edge=>`${edge.from} → ${edge.to}${edge.label?": "+edge.label:""}. Sources: ${(edge.evidence_turns||[]).join(", ")||"No source references in this view; open details to review evidence"}`;
  function cinematicNodeMetrics(step) {
    const width=150;
    const titleLines=wrapText(step.title||step.id,width-12,15,600);
    return {width,height:Math.max(108,76+16*titleLines.length),titleLines};
  }
  function cinematicEdgeMetrics(label) {
    const width=clamp(measureText(label,12,500)+14,28,107);
    const lines=wrapText(label,width-14,12,500);
    return {width,height:lines.length*14+6,lines};
  }
  function colorFor(actor) {let hash=0;for(const ch of string(actor))hash=(hash*31+ch.charCodeAt(0))>>>0;return PALETTE[hash%PALETTE.length];}
  function nodeShape(doc,type,x,y,w,h,mini=false){
    const theme=TYPES[type]||TYPES.activity,attrs={fill:theme.fill,stroke:theme.stroke,"stroke-width":mini?0:1.4};
    if(["decision","parallel_split","parallel_join","merge"].includes(type))return svgNode(doc,"path",{...attrs,d:`M ${x+w/2} ${y} L ${x+w} ${y+h/2} L ${x+w/2} ${y+h} L ${x} ${y+h/2} Z`});
    if(type==="document")return svgNode(doc,"path",{...attrs,d:`M ${x} ${y} H ${x+w} V ${y+h-14} C ${x+w*.7} ${y+h-38} ${x+w*.3} ${y+h+10} ${x} ${y+h-14} Z`});
    if(type==="data_store")return svgNode(doc,"path",{...attrs,d:`M ${x} ${y+12} C ${x} ${y-4} ${x+w} ${y-4} ${x+w} ${y+12} V ${y+h-12} C ${x+w} ${y+h+4} ${x} ${y+h+4} ${x} ${y+h-12} Z`});
    if(type==="wait")return svgNode(doc,"path",{...attrs,d:`M ${x} ${y} H ${x+w-40} Q ${x+w} ${y} ${x+w} ${y+h/2} Q ${x+w} ${y+h} ${x+w-40} ${y+h} H ${x} Z`});
    return svgNode(doc,"rect",{...attrs,x,y,width:w,height:h,rx:["start","end"].includes(type)?Math.min(48,h/2):8});
  }
  // The size limit is that of a reported map. Its picture adds markers (see present) and is not held to it.
  function model(graph,limited=true) {
    if(!graph||!Array.isArray(graph.steps)||!Array.isArray(graph.connections))throw new Error("The workflow is missing steps or connections.");
    if(limited&&(graph.steps.length>80||graph.connections.length>150))throw new Error("This workflow is too large to display in one canvas.");
    const seen=new Set(),steps=graph.steps.map(step=>{
      if(!step||typeof step.id!=="string"||!step.id||seen.has(step.id))throw new Error("Workflow step IDs must be unique.");
      seen.add(step.id);return {...step};
    });
    const connections=graph.connections.map((edge,index)=>{
      if(!edge||!seen.has(edge.from)||!seen.has(edge.to))throw new Error("A workflow connection points to a missing step.");
      return {...edge,label:string(edge.label).trim(),id:`edge-${index}`};
    });
    const incoming=new Map(steps.map(step=>[step.id,[]])),outgoing=new Map(steps.map(step=>[step.id,[]]));
    connections.forEach(edge=>{incoming.get(edge.to).push(edge);outgoing.get(edge.from).push(edge);});
    return {title:string(graph.title),steps,connections,incoming,outgoing};
  }
  // The picture of a map: the reported steps and connections, with the marks a reader of
  // process diagrams looks for. The reported graph is the evidence and is never altered:
  // this returns a copy, which is laid out and drawn and goes nowhere else (it is not
  // saved, sent, selected, navigated or exported). Every addition is marked `implied`
  // and has an ID no reported step can have ("~" is not allowed in a step ID).
  //   - A start marker in front of the first step of the main route, and an end marker
  //     after each step of that route nothing follows, unless the account itself states
  //     the start or the end. Participants rarely say "this is where it starts".
  //   - A small gateway after a step with several ways out. The routing rules keep a
  //     decision the participant did not name off the map, so its routes would leave one
  //     point of an ordinary box; the gateway shows that they are separate ways on.
  // Steps that are not connected to the main route stay as they are, shown as detached.
  const GATEWAYS=new Set(["decision","parallel_split","parallel_join","merge"]);
  function present(graph) {
    const steps=graph.steps.map(step=>({...step})),connections=graph.connections.map(edge=>({...edge}));
    const picture={title:graph.title,steps,connections};
    const known=new Set(steps.map(step=>step.id));
    if(known.size!==steps.length||connections.some(edge=>!known.has(edge.from)||!known.has(edge.to))||!connections.length)return picture;
    const incoming=new Map(steps.map(step=>[step.id,[]])),outgoing=new Map(steps.map(step=>[step.id,[]]));
    connections.forEach(edge=>{incoming.get(edge.to).push(edge);outgoing.get(edge.from).push(edge);});
    // The main route is the connected group of the step the map opens on (see initialStep).
    const connected=steps.filter(step=>outgoing.get(step.id).length),entries=connected.filter(step=>!incoming.get(step.id).length);
    const first=entries.find(step=>step.type==="start")||entries[0]||connected.find(step=>step.type==="start")||connected[0];
    const main=new Set(),queue=[first.id];
    while(queue.length){
      const id=queue.pop();if(main.has(id))continue;main.add(id);
      for(const edge of outgoing.get(id))queue.push(edge.to);
      for(const edge of incoming.get(id))queue.push(edge.from);
    }
    const markers=[],links=[];
    const route=steps.filter(step=>main.has(step.id));
    if(!route.some(step=>step.type==="start")){
      const opening=route.filter(step=>!incoming.get(step.id).length&&outgoing.get(step.id).length);
      markers.push({id:"~start",type:"start",title:"Start",implied:"start"});
      for(const step of opening.length?opening:[first])links.push({from:"~start",to:step.id,label:"",implied:true});
    }
    for(const step of route){
      if(step.type!=="end"&&!outgoing.get(step.id).length&&incoming.get(step.id).length){
        markers.push({id:`~end:${step.id}`,type:"end",title:"End",implied:"end",of:step.id});
        links.push({from:step.id,to:`~end:${step.id}`,label:"",implied:true});
      }
    }
    for(const step of steps){
      const exits=outgoing.get(step.id).filter(edge=>edge.to!==step.id);
      if(GATEWAYS.has(step.type)||exits.length<2)continue;
      const gate={id:`~gate:${step.id}`,type:"decision",title:"",implied:"gateway",of:step.id};
      markers.push(gate);
      // The reported connections keep their place in the list (and so their identity on the
      // canvas); in the picture they leave from the gateway.
      for(const edge of exits)edge.from=gate.id;
      links.push({from:step.id,to:gate.id,label:"",implied:true});
    }
    steps.push(...markers);connections.push(...links);
    return picture;
  }
  const markerTooltip=marker=>marker.implied==="start"?"Start. Added to the picture; the account does not state where the work starts."
    :marker.implied==="end"?"End. Added to the picture; the account does not state that the work ends here."
    :"Several routes lead on from the step before this point.";
  // Walk actual connections from their entry points. An edge back to an active
  // ancestor closes a cycle; it remains a real edge and gets its own return port.
  // The order supplied by the interviewer only breaks ties between ready steps.
  function routingOrder(data) {
    const visited=new Set(),active=new Set(),returns=new Set(),returnNodes=new Set();
    function visit(id) {
      if(visited.has(id))return;
      visited.add(id);active.add(id);
      for(const edge of data.outgoing.get(id)) {
        if(active.has(edge.to)) {
          returns.add(edge.id);returnNodes.add(edge.from);returnNodes.add(edge.to);
        }else visit(edge.to);
      }
      active.delete(id);
    }
    for(const step of data.steps)if(!data.incoming.get(step.id).length)visit(step.id);
    for(const step of data.steps)if(step.type==="start")visit(step.id);
    for(const step of data.steps)visit(step.id);

    const waiting=new Map(data.steps.map(step=>[step.id,data.incoming.get(step.id).filter(edge=>!returns.has(edge.id)).length]));
    const ordered=[];
    while(waiting.size) {
      const step=data.steps.find(candidate=>waiting.get(candidate.id)===0);
      ordered.push(step);waiting.delete(step.id);
      for(const edge of data.outgoing.get(step.id)) {
        if(!returns.has(edge.id))waiting.set(edge.to,waiting.get(edge.to)-1);
      }
    }
    return {ordered,returns,returnNodes};
  }
  function initialStep(data) {
    const connected=data.steps.filter(step=>data.outgoing.get(step.id).length);
    const entries=connected.filter(step=>!data.incoming.get(step.id).length);
    return entries.find(step=>step.type==="start")||entries[0]||connected.find(step=>step.type==="start")||connected[0]||data.steps[0];
  }
  // A caption on an arrow states the condition for taking it. The only way out of a step
  // that is not a decision has no condition, so the map draws that arrow plain; its
  // wording stays in the arrow's tooltip and in the step details.
  function captionedEdges(data) {
    const decisions=new Set(data.steps.filter(step=>step.type==="decision").map(step=>step.id));
    return new Set(data.connections.filter(edge=>edge.label&&(decisions.has(edge.from)||data.outgoing.get(edge.from).length>1)).map(edge=>edge.id));
  }
  // wrapAspect (width / height of the canvas) asks the engine to fold a long strip into
  // rows, or columns when vertical. The folded result is only a candidate: see layeredLayout.
  function elkGraph(data,direction="RIGHT",cinematic=false,wrapAspect=null) {
    const vertical=direction==="DOWN";
    const {ordered,returns,returnNodes}=routingOrder(data);
    const captioned=cinematic?null:captionedEdges(data),folding=!cinematic&&Number.isFinite(wrapAspect)&&wrapAspect>0;
    return {id:"workflow",layoutOptions:{
      "elk.algorithm":"layered","elk.direction":vertical?"DOWN":"RIGHT","elk.edgeRouting":"ORTHOGONAL",
      "elk.padding":"[top=24,left=24,bottom=24,right=24]","elk.spacing.nodeNode":"28",
      "elk.layered.spacing.nodeNodeBetweenLayers":"36","elk.spacing.edgeNode":"18",
      "elk.layered.spacing.edgeNodeBetweenLayers":"14","elk.spacing.edgeEdge":"12",
      "elk.layered.spacing.edgeEdgeBetweenLayers":"12","elk.layered.considerModelOrder.strategy":"NODES_AND_EDGES",
      // Network simplex gives the most compact map but its cost grows steeply with
      // cross-links (seconds at 80 connections, a minute at 150); Brandes-Koepf stays under a second.
      // The long return routes of a folded map make it pay that cost at half the size.
      "elk.layered.nodePlacement.strategy":data.connections.length>(folding?DENSE_CONNECTIONS/2:DENSE_CONNECTIONS)?"BRANDES_KOEPF":"NETWORK_SIMPLEX","elk.layered.cycleBreaking.strategy":"MODEL_ORDER",
      "elk.layered.crossingMinimization.strategy":"LAYER_SWEEP","elk.separateConnectedComponents":"true",
      ...(cinematic ? {
        "elk.padding":"[top=18,left=18,bottom=18,right=18]",
        "elk.spacing.nodeNode":"22","elk.layered.spacing.nodeNodeBetweenLayers":"22",
        "elk.spacing.edgeNode":"14","elk.layered.spacing.edgeNodeBetweenLayers":"14",
        "elk.spacing.edgeEdge":"12","elk.layered.spacing.edgeEdgeBetweenLayers":"12"
      } : {}),
      ...(folding ? {
        "elk.layered.wrapping.strategy":"MULTI_EDGE","elk.aspectRatio":String(Math.round(wrapAspect*100)/100)
      } : {})
    },children:ordered.map(step=>{
      const {width,height}=cinematic ? cinematicNodeMetrics(step) : nodeMetrics(step);
      const ports=[
        {id:`${step.id}::in`,x:vertical?width/2:0,y:vertical?0:height/2,width:0,height:0,layoutOptions:{"elk.port.side":vertical?"NORTH":"WEST"}},
        // ELK normalizes side ports to the box border; the wave's midpoint is inset.
        {id:`${step.id}::out`,x:vertical?width/2:width,y:vertical?height:height/2,width:0,height:0,layoutOptions:{"elk.port.side":vertical?"SOUTH":"EAST","elk.port.borderOffset":vertical&&!cinematic&&step.type==="document"?"-14":"0"}}
      ];
      if(!cinematic&&returnNodes.has(step.id))ports.push({
        id:`${step.id}::return`,x:vertical?width:width/2,y:vertical?height/2:height,width:0,height:0,
        layoutOptions:{"elk.port.side":vertical?"EAST":"SOUTH","elk.port.borderOffset":!vertical&&step.type==="document"?"-14":"0"}
      });
      return {id:step.id,width,height,layoutOptions:{"elk.portConstraints":"FIXED_POS"},ports};
    }),edges:data.connections.map(edge=>{
      const size=cinematic ? edge.label&&cinematicEdgeMetrics(edge.label) : captioned.has(edge.id)&&edgeMetrics(edge.label);
      const returning=!cinematic&&returns.has(edge.id);
      const sourcePort=returning&&edge.from!==edge.to?"return":"out";
      return {id:edge.id,sources:[`${edge.from}::${sourcePort}`],targets:[`${edge.to}::${returning?"return":"in"}`],
        labels:size?[{id:`${edge.id}-label`,text:string(edge.label),width:size.width,height:size.height}]:[]};
    })};
  }
  function points(section) {return [section.startPoint,...(section.bendPoints||[]),section.endPoint].filter(Boolean);}
  // The box whose centre is closest to a point; the first one listed wins a tie.
  function nearestNode(nodes,point) {
    let best=null,least=Infinity;
    for(const node of nodes){const distance=Math.hypot(node.x+node.width/2-point.x,node.y+node.height/2-point.y);if(distance<least){best=node;least=distance;}}
    return best;
  }
  function validateLayeredRoutes(layout,data) {
    const nodes=new Map((layout?.children||[]).map(node=>[node.id,node]));
    const routes=new Map((layout?.edges||[]).map(edge=>[edge.id,edge]));
    if(!Number.isFinite(layout?.width)||!Number.isFinite(layout?.height)||
      layout.children?.length!==data.steps.length||nodes.size!==data.steps.length||
      layout.edges?.length!==data.connections.length||routes.size!==data.connections.length||
      !data.steps.every(step=>nodes.has(step.id)))throw new Error("The complete workflow layout could not be calculated.");
    function onPort(stepId,portId,point) {
      const node=nodes.get(stepId),port=node.ports?.find(item=>item.id===portId);
      return point&&port&&Math.hypot(point.x-node.x-port.x,point.y-node.y-port.y)<.1;
    }
    for(const edge of data.connections) {
      const route=routes.get(edge.id),sections=route?.sections;
      if(!sections?.length||!sections.every(section=>section.startPoint&&section.endPoint))
        throw new Error("The complete workflow layout could not be calculated.");
      if(!onPort(edge.from,route.sources?.[0],sections[0].startPoint)||
         !onPort(edge.to,route.targets?.[0],sections.at(-1).endPoint))
        throw new Error("A workflow connection could not be attached to its reported steps.");
    }
  }
  function roundedPath(vertices,radius=7) {
    if(!vertices.length)return "";
    let d=`M ${vertices[0].x} ${vertices[0].y}`;
    for(let i=1;i<vertices.length-1;i++){
      const a=vertices[i-1],b=vertices[i],c=vertices[i+1];
      const inLength=Math.hypot(b.x-a.x,b.y-a.y),outLength=Math.hypot(c.x-b.x,c.y-b.y);
      if(!inLength||!outLength)continue;
      const r=Math.min(radius,inLength/2,outLength/2),before={x:b.x-(b.x-a.x)*r/inLength,y:b.y-(b.y-a.y)*r/inLength},after={x:b.x+(c.x-b.x)*r/outLength,y:b.y+(c.y-b.y)*r/outLength};
      d+=` L ${before.x} ${before.y} Q ${b.x} ${b.y} ${after.x} ${after.y}`;
    }
    if(vertices.length>1)d+=` L ${vertices.at(-1).x} ${vertices.at(-1).y}`;
    return d;
  }
  let cinematicEngine;
  const cinematicRequests=[];
  function loadEngine() {
    if(!scope.CollectorWorkflowAssets?.loadEngine)throw new Error("The local workflow layout engine could not load.");
    return scope.CollectorWorkflowAssets.loadEngine();
  }
  // In a browser the engine runs in one worker shared by every canvas and the walkthrough:
  // the page stays responsive, and a layout that is no longer wanted or that exceeds its
  // budget is really stopped (a worker can only be stopped by ending it; the next layout
  // starts a new one). Where there are no workers, or the worker script cannot start, the
  // engine runs in the page as before.
  const LAYOUT_WORKER="/workflow-layout-worker.js",LAYOUT_BUDGET_MS=8000;
  const layouts={worker:null,active:null,queue:[],proven:false,broken:false,serial:0,engine:null};
  const workerLayouts=()=>typeof scope.Worker==="function"&&!layouts.broken;
  function stopLayoutWorker() {
    const worker=layouts.worker;layouts.worker=null;
    if(!worker)return;
    worker.onmessage=null;worker.onerror=null;
    try{worker.terminate();}catch{/* The worker had already ended. */}
  }
  function settleLayout(request,error,layout) {
    if(request.timer!==undefined)scope.clearTimeout?.(request.timer);
    if(layouts.active===request)layouts.active=null;
    if(error)request.reject(error);else request.resolve(layout);
    pumpLayouts();
  }
  async function pageLayout(graph) {
    if(!layouts.engine){const Engine=scope.ELK||await loadEngine();layouts.engine ||= new Engine();}
    return layouts.engine.layout(graph);
  }
  function layoutWorkerFailed() {
    stopLayoutWorker();
    const request=layouts.active;
    // A worker that has produced layouts before is simply started again for the next one.
    if(layouts.proven){if(request)settleLayout(request,new Error("The workflow layout engine stopped."));return;}
    // It never started (blocked, missing or failed script): lay out in the page from now on.
    layouts.broken=true;
    const waiting=[...(request?[request]:[]),...layouts.queue];layouts.active=null;layouts.queue=[];
    for(const item of waiting){
      if(item.timer!==undefined)scope.clearTimeout?.(item.timer);
      pageLayout(item.graph).then(item.resolve,item.reject);
    }
  }
  function pumpLayouts() {
    if(layouts.active||!layouts.queue.length)return;
    const request=layouts.active=layouts.queue.shift();
    try{
      if(!layouts.worker){
        const worker=layouts.worker=new scope.Worker(LAYOUT_WORKER);
        worker.onmessage=event=>{
          const message=event?.data||{},current=layouts.active;
          if(worker!==layouts.worker||!current||message.id!==current.id)return;
          if(typeof message.error==="string")settleLayout(current,new Error(message.error||"The workflow layout could not be calculated."));
          else{layouts.proven=true;settleLayout(current,null,message.layout);}
        };
        worker.onerror=event=>{event?.preventDefault?.();if(worker===layouts.worker)layoutWorkerFailed();};
      }
      request.timer=scope.setTimeout?.(()=>{
        request.timer=undefined;stopLayoutWorker();
        settleLayout(request,new Error("The workflow layout took too long."));
      },LAYOUT_BUDGET_MS);
      layouts.worker.postMessage({id:request.id,graph:request.graph});
    }catch{layoutWorkerFailed();}
  }
  // Returns a promise with cancel(): a queued request is dropped, a running one ends its worker.
  function workerLayout(graph) {
    let request;
    const promise=new Promise((resolve,reject)=>{request={id:++layouts.serial,graph,resolve,reject,timer:undefined};});
    promise.cancel=()=>{
      const queued=layouts.queue.indexOf(request);
      if(queued>=0)layouts.queue.splice(queued,1);
      else if(layouts.active===request)stopLayoutWorker();
      else return;
      settleLayout(request,new Error("The workflow layout was superseded."));
    };
    layouts.queue.push(request);pumpLayouts();
    return promise;
  }
  function orderedComponents(layout,data){
    if(!layout?.children?.length)return layout;
    const remaining=new Set(data.steps.map(step=>step.id)),components=[];
    const first=data.steps.find(step=>step.type==="start")||data.steps.find(step=>data.outgoing.get(step.id).length)||data.steps[0];
    for(const root of [first,...data.steps]){
      if(!remaining.has(root.id))continue;
      const stack=[root.id],members=new Set();
      while(stack.length){
        const id=stack.pop();if(!remaining.delete(id))continue;members.add(id);
        stack.push(...data.incoming.get(id).map(edge=>edge.from),...data.outgoing.get(id).map(edge=>edge.to));
      }
      components.push(members);
    }
    if(components.length<2)return layout;
    const copy=JSON.parse(JSON.stringify(layout)),edges=new Map(data.connections.map(edge=>[edge.id,edge]));
    const bands=components.map(members=>{
      const nodes=copy.children.filter(node=>members.has(node.id)),boxes=[...nodes],points=[];
      for(const edge of copy.edges||[]){
        if(!members.has(edges.get(edge.id)?.from))continue;
        boxes.push(...(edge.labels||[]));
        for(const part of edge.sections||[])points.push(part.startPoint,...(part.bendPoints||[]),part.endPoint);
      }
      const rectangles=boxes.filter(box=>Number.isFinite(box.x)&&Number.isFinite(box.y)),coords=points.filter(point=>point&&Number.isFinite(point.x)&&Number.isFinite(point.y));
      const x=Math.min(...rectangles.map(box=>box.x),...coords.map(point=>point.x)),y=Math.min(...rectangles.map(box=>box.y),...coords.map(point=>point.y));
      const right=Math.max(...rectangles.map(box=>box.x+box.width),...coords.map(point=>point.x)),bottom=Math.max(...rectangles.map(box=>box.y+box.height),...coords.map(point=>point.y));
      return {items:[...rectangles,...coords],x,y,width:right-x,height:bottom-y};
    });
    if(bands.some(band=>!Number.isFinite(band.width)||!Number.isFinite(band.height)))return layout;
    const placed=[],padding=12,gap=12;
    for(const band of bands){
      const xs=[padding,...placed.map(box=>box.x+box.width+gap)].sort((a,b)=>a-b);
      const ys=[padding,...placed.map(box=>box.y+box.height+gap)].sort((a,b)=>a-b);
      let position;
      for(const y of ys){
        for(const x of xs){
          if(x+band.width>layout.width-padding+.01||y+band.height>layout.height-padding+.01)continue;
          if(placed.every(box=>x>=box.x+box.width+gap||y>=box.y+box.height+gap||x+band.width+gap<=box.x||y+band.height+gap<=box.y)){position={x,y};break;}
        }
        if(position)break;
      }
      if(!position)return layout;
      placed.push({...position,width:band.width,height:band.height});
      for(const point of band.items){point.x+=position.x-band.x;point.y+=position.y-band.y;}
    }
    return copy;
  }
  function layoutDefects(layout) {
    const nodes=layout.children||[],edges=layout.edges||[],EPS=.1;
    const labels=edges.flatMap(edge=>(edge.labels||[]).map(label=>({...label,edge:edge.id})));
    const overlap=(a,b)=>a.x<b.x+b.width-EPS&&a.x+a.width>b.x+EPS&&a.y<b.y+b.height-EPS&&a.y+a.height>b.y+EPS;
    const inside=box=>box.x>=-EPS&&box.y>=-EPS&&box.x+box.width<=layout.width+EPS&&box.y+box.height<=layout.height+EPS;
    // Touching a border is a connection; passing through the interior is a defect.
    const hits=(a,b,box)=>Math.abs(a.x-b.x)<EPS
      ?a.x>box.x+EPS&&a.x<box.x+box.width-EPS&&Math.max(a.y,b.y)>box.y+EPS&&Math.min(a.y,b.y)<box.y+box.height-EPS
      :a.y>box.y+EPS&&a.y<box.y+box.height-EPS&&Math.max(a.x,b.x)>box.x+EPS&&Math.min(a.x,b.x)<box.x+box.width-EPS;
    let defects=0,crossings=0;const segments=[];
    nodes.forEach((node,i)=>{if(!inside(node))defects++;for(const other of nodes.slice(i+1))if(overlap(node,other))defects++;});
    labels.forEach((label,i)=>{
      if(!inside(label))defects++;
      for(const node of nodes)if(overlap(label,node))defects++;
      for(const other of labels.slice(i+1))if(overlap(label,other))defects++;
    });
    for(const edge of edges){
      const [from,to]=[edge.sources?.[0],edge.targets?.[0]].map(port=>string(port).split("::")[0]);
      for(const section of edge.sections||[]){
        const vertices=points(section);
        for(let i=1;i<vertices.length;i++){
          const a=vertices[i-1],b=vertices[i];
          if(Math.abs(a.x-b.x)>EPS&&Math.abs(a.y-b.y)>EPS){defects++;continue;}
          for(const node of nodes)if(node.id!==from&&node.id!==to&&hits(a,b,node))defects++;
          for(const label of labels)if(label.edge!==edge.id&&hits(a,b,label))defects++;
          segments.push({edge:edge.id,a,b,flat:Math.abs(a.y-b.y)<EPS});
        }
      }
    }
    segments.forEach((one,i)=>{
      for(const two of segments.slice(i+1)){
        if(one.edge===two.edge||one.flat===two.flat)continue;
        const flat=one.flat?one:two,upright=one.flat?two:one,x=upright.a.x,y=flat.a.y;
        if(x>Math.min(flat.a.x,flat.b.x)+EPS&&x<Math.max(flat.a.x,flat.b.x)-EPS&&y>Math.min(upright.a.y,upright.b.y)+EPS&&y<Math.max(upright.a.y,upright.b.y)-EPS)crossings++;
      }
    });
    return {defects,crossings};
  }
  // The scale at which Fit shows a whole layout on a canvas of this size (the margins fit() leaves).
  const fitScale=(layout,view)=>Math.min((view.width-40)/layout.width,(view.height-48)/layout.height);
  // The layered layout is one strip along the reading direction. For a longer process the
  // strip is far longer than the canvas, so the whole map is only readable in pieces. The
  // engine can fold the strip into rows, but its folding does not always keep every route
  // attached or clear of other shapes: the folded layout is used only when it is as sound
  // as the strip, adds no crossing and makes the whole map clearly larger on the canvas.
  // A short process is not folded, and neither is one with many more connections than steps:
  // that is a web rather than a line, and folding it only adds crossings.
  const WRAP_MIN_STEPS=8,WRAP_MAX_DENSITY=1.5,WRAP_STRETCH=1.25,WRAP_GAIN=1.15,RESHAPE_SETTLE_MS=200;
  const sized=view=>view?.width>80&&view?.height>96;
  const foldable=data=>data.steps.length>=WRAP_MIN_STEPS&&data.connections.length<=data.steps.length*WRAP_MAX_DENSITY;
  // Canvas shapes within about a fifth of each other fold alike.
  const canvasShape=(view,data)=>foldable(data)&&sized(view)?Math.round(Math.log(view.width/view.height)/Math.log(1.2)):null;
  // `known` is the strip already calculated for this map, when only the canvas has changed.
  function layeredLayout(data,direction,view,run,known=null) {
    const job={cancelled:false,request:null,strip:known,shape:canvasShape(view,data),cancel(){job.cancelled=true;job.request?.cancel?.();}};
    // A canvas with no size yet (a hidden panel) is taken as an ordinary screen shape.
    if(!sized(view))view={width:960,height:600};
    const aspect=view.width/view.height;
    const pass=graph=>{
      if(job.cancelled)throw new Error("The workflow layout was superseded.");
      return job.request=run(graph);
    };
    job.result=(async()=>{
      const strip=job.strip=known||await pass(elkGraph(data,direction));
      if(job.cancelled)throw new Error("The workflow layout was superseded.");
      if(!foldable(data)||!(strip?.width>0)||!(strip?.height>0))return strip;
      const shape=strip.width/strip.height;
      if(direction==="DOWN"?shape*WRAP_STRETCH>aspect:shape<aspect*WRAP_STRETCH)return strip;
      let folded;
      try{
        validateLayeredRoutes(strip,data);
        folded=await pass(elkGraph(data,direction,false,aspect));
        validateLayeredRoutes(folded,data);
      }catch(error){if(job.cancelled)throw error;return strip;}
      if(fitScale(folded,view)<fitScale(strip,view)*WRAP_GAIN)return strip;
      const before=layoutDefects(strip),after=layoutDefects(folded);
      return after.defects<=before.defects&&after.crossings<=before.crossings?folded:strip;
    })();
    job.result.catch(()=>{});
    return job;
  }
  // Only a single, acyclic path can change row direction without separating a choice
  // from its alternatives or turning a normal handoff into a long return connector.
  function cinematicChain(data,aspect) {
    if(data.steps.length<8 || data.connections.length!==data.steps.length-1)return null;
    if(data.steps.some(step=>data.incoming.get(step.id).length>1||data.outgoing.get(step.id).length>1))return null;
    const starts=data.steps.filter(step=>!data.incoming.get(step.id).length);
    if(starts.length!==1)return null;
    const byId=new Map(data.steps.map(step=>[step.id,step])),nodes=[],edges=[];
    let step=starts[0];
    while(step){
      nodes.push({id:step.id,step,...cinematicNodeMetrics(step)});
      const edge=data.outgoing.get(step.id)[0];
      if(!edge)break;
      edges.push({edge,key:JSON.stringify([edge.from,edge.to,edge.label||""]),
        labels:edge.label?[cinematicEdgeMetrics(edge.label)]:[]});
      step=byId.get(edge.to);
    }
    // A disjoint cycle can satisfy the degree and edge-count checks above.
    if(nodes.length!==data.steps.length)return null;
    const width=nodes[0].width, pad=18, gap=22;
    const avgHeight=nodes.reduce((sum,node)=>sum+node.height,0)/nodes.length;
    const avgLabel=edges.reduce((sum,item)=>sum+(item.labels[0]?.width||0),0)/edges.length;
    const columns=clamp(Math.round(Math.sqrt(nodes.length*aspect*(avgHeight+gap)/(width+avgLabel+gap))),2,nodes.length);
    const rows=Math.ceil(nodes.length/columns);
    const rowHeights=Array(rows).fill(0),rowGaps=Array(rows-1).fill(gap),columnGaps=Array(columns-1).fill(gap);
    const column=i=>Math.floor(i/columns)%2 ? columns-1-i%columns : i%columns;
    for(let i=0;i<nodes.length;i++){
      const row=Math.floor(i/columns);
      rowHeights[row]=Math.max(rowHeights[row],nodes[i].height);
      const label=edges[i]?.labels[0];
      if(!label)continue;
      if(column(i)===column(i+1))rowGaps[row]=Math.max(rowGaps[row],label.height+gap);
      else{
        const index=Math.min(column(i),column(i+1));
        columnGaps[index]=Math.max(columnGaps[index],label.width+gap);
        rowHeights[row]=Math.max(rowHeights[row],2*(label.height+6));
      }
    }
    const xs=[pad],ys=[pad];
    for(let i=1;i<columns;i++)xs.push(xs[i-1]+width+columnGaps[i-1]);
    for(let i=1;i<rows;i++)ys.push(ys[i-1]+rowHeights[i-1]+rowGaps[i-1]);
    nodes.forEach((node,i)=>{
      const row=Math.floor(i/columns);
      node.x=xs[column(i)];node.y=ys[row]+(rowHeights[row]-node.height)/2;
    });
    edges.forEach((item,i)=>{
      const a=nodes[i],b=nodes[i+1],vertical=a.x===b.x,forward=b.x>a.x;
      const start=vertical?{x:a.x+width/2,y:a.y+a.height}:{x:a.x+(forward?width:0),y:a.y+a.height/2};
      const end=vertical?{x:b.x+width/2,y:b.y}:{x:b.x+(forward?0:width),y:b.y+b.height/2};
      const points=[start,end];
      item.paths=[{points,d:roundedPath(points)}];
      const label=item.labels[0];
      if(label){
        label.x=vertical ? start.x+(column(i)===0?6:-label.width-6) : (start.x+end.x-label.width)/2;
        label.y=vertical ? (start.y+end.y-label.height)/2 : start.y-label.height-4;
      }
    });
    return {width:xs.at(-1)+width+pad,height:ys.at(-1)+rowHeights.at(-1)+pad,nodes,edges,usesAspect:true};
  }
  async function cinematicLayout(graph,aspect=1.9,isCurrent=()=>true) {
    const data=model(graph);
    if(!data.steps.length)return {width:0,height:0,nodes:[],edges:[]};
    const chain=cinematicChain(data,Number.isFinite(aspect)?clamp(aspect,.6,2.4):1.9);
    if(chain)return chain;
    let layout;
    if(workerLayouts()){
      // A walkthrough layout that its stage no longer wants must not hold up the next one.
      for(const item of cinematicRequests.splice(0)){
        let wanted=false;try{wanted=item.isCurrent();}catch{/* A closed stage wants nothing. */}
        if(wanted)cinematicRequests.push(item);else item.request.cancel();
      }
      const item={request:workerLayout(elkGraph(data,"RIGHT",true)),isCurrent};
      cinematicRequests.push(item);
      try{layout=await item.request;}
      finally{const index=cinematicRequests.indexOf(item);if(index>=0)cinematicRequests.splice(index,1);}
    }else{
      if(!cinematicEngine){
        const Engine=scope.ELK||await loadEngine();
        if(!isCurrent())return null;
        cinematicEngine ||= new Engine();
      }
      layout=orderedComponents(await cinematicEngine.layout(elkGraph(data,"RIGHT",true)),data);
    }
    validateLayeredRoutes(layout,data);
    const steps=new Map(data.steps.map(step=>[step.id,step]));
    const connections=new Map(data.connections.map(edge=>[edge.id,edge]));
    const nodes=layout.children.map(({id,x,y,width,height})=>{
      const step=steps.get(id);
      return {id,step,x,y,width,height,titleLines:cinematicNodeMetrics(step).titleLines};
    });
    const edges=layout.edges.map(item=>{
      const edge=connections.get(item.id);
      const paths=item.sections.map(section=>{
        const vertices=points(section);
        return {d:roundedPath(vertices),points:vertices};
      });
      const labels=(item.labels||[]).map(({x,y,width,height})=>({x,y,width,height,lines:cinematicEdgeMetrics(edge.label).lines}));
      return {key:JSON.stringify([edge.from,edge.to,edge.label||""]),edge,paths,labels};
    });
    return {width:layout.width,height:layout.height,nodes,edges};
  }
  class Canvas {
    constructor(container,options={}) {
      if(!container)throw new Error("A workflow container is required.");
      this.container=container;this.doc=container.ownerDocument||scope.document;this.options=options;
      this.originalTabIndex=container.getAttribute?.("tabindex");container.setAttribute?.("tabindex","-1");
      this.uid=`workflow-${++serial}`;this.version=0;this.dead=false;this.graph=null;this.requestedGraph=null;this.layout=null;this.fitted=false;this.fitMode=true;this.pending=false;this.layoutError=false;this.lastSize=null;
      this.camera={x:0,y:0,scale:1};this.direction=options.direction==="DOWN"||(!options.direction&&container.clientWidth>0&&container.clientWidth<640)?"DOWN":"RIGHT";this.selected=null;this.following=false;this.pathTrail=[];this.listeners=[];this.pointers=new Map();this.pointerMoved=false;
      this.autoDirectionPending=!options.direction&&!container.clientWidth;
      container.replaceChildren();container.classList.add("workflow-canvas");
      styles(container,{position:"relative",overflow:"hidden",touchAction:"none"});
      this.svg=svgNode(this.doc,"svg",{xmlns:NS,width:"100%",height:"100%",tabindex:"0",role:"group","aria-label":"Workflow canvas. Drag to pan, use plus or minus to zoom, press 0 for the overview, and Tab to explore steps. Press F to follow a path and Escape to leave it."});
      styles(this.svg,{display:"block",position:"absolute",inset:"0",width:"100%",height:"100%",minWidth:"0",cursor:"grab",outlineOffset:"-3px"});
      this.title=svgNode(this.doc,"title");this.description=svgNode(this.doc,"desc");this.svg.append(this.title,this.description);
      this.world=svgNode(this.doc,"g");this.svg.append(this.world);
      this.mini=svgNode(this.doc,"svg",{width:144,height:88,"aria-hidden":"true"});
      this.mini.classList.add("workflow-minimap");
      styles(this.mini,{position:"absolute",right:"14px",bottom:"14px",width:"144px",height:"88px",minWidth:"0",cursor:"crosshair"});
      this.miniWorld=svgNode(this.doc,"g");this.miniView=svgNode(this.doc,"rect",{class:"wf-mini-view",fill:"#6c809a24",stroke:"#6c809a","stroke-width":2,"vector-effect":"non-scaling-stroke",rx:4});this.mini.append(this.miniWorld,this.miniView);
      this.hint=this.doc.createElement("div");this.hint.className="workflow-canvas-hint";this.hint.textContent="Drag to move around · Select a step for details";
      styles(this.hint,{position:"absolute",left:"16px",bottom:"14px",pointerEvents:"none",maxWidth:"calc(100% - 190px)"});
      this.status=this.doc.createElement("div");this.status.setAttribute("role","status");this.status.setAttribute("aria-live","polite");styles(this.status,{position:"absolute",width:"1px",height:"1px",overflow:"hidden",clipPath:"inset(50%)",whiteSpace:"nowrap"});
      container.append(this.svg,this.mini,this.hint,this.status);
      this.listen(this.svg,"pointerdown",event=>this.pointerDown(event));
      this.listen(this.svg,"pointermove",event=>this.pointerMove(event));
      this.listen(this.svg,"pointerup",event=>this.pointerUp(event));
      this.listen(this.svg,"pointercancel",event=>this.pointerUp(event));
      this.listen(this.svg,"wheel",event=>this.wheel(event),{passive:false});
      this.listen(this.svg,"keydown",event=>this.key(event));
      this.listen(this.mini,"pointerdown",event=>this.navigateMini(event));
      if(scope.ResizeObserver){this.observer=new scope.ResizeObserver(()=>{if(!this.layout)return;this.refresh();});this.observer.observe(container);}
    }
    listen(target,name,fn,options){target.addEventListener(name,fn,options);this.listeners.push([target,name,fn,options]);}
    size(){return {width:this.container.clientWidth||0,height:this.container.clientHeight||0};}
    notify(){this.options.onViewChange?.({scale:this.camera.scale,hasGraph:Boolean(this.layout?.children?.length),selected:this.selected,direction:this.direction,updating:this.pending,path:this.getPathNavigation(),exportReady:Boolean(this.layout?.children?.length)&&!this.pending&&!this.layoutError&&!this.dead});}
    async update(graph) {
      if(this.dead)return false;
      // Invalidate any in-flight layout even if the replacement is malformed.
      // Otherwise a late layout can present old evidence as the current graph.
      const revision=++this.version;
      this.reshapeJob?.cancel();
      if(this.autoDirectionPending&&this.size().width){this.direction=this.size().width<640?"DOWN":"RIGHT";this.autoDirectionPending=false;}
      let data,picture,renderKey,layoutKey;
      try{
        renderKey=JSON.stringify({direction:this.direction,title:string(graph?.title),steps:graph?.steps,connections:graph?.connections});
        if(this.layout&&this.renderKey===renderKey){
          this.dropLayoutJob();
          if(this.pending||this.layoutError){
            this.requestedGraph=JSON.parse(renderKey);
            this.pending=false;this.layoutError=false;
          }
          if(!this.fitted)this.initialView();
          this.notify();return true;
        }
        // The interview editor can mutate its draft while the engine is running.
        this.requestedGraph=JSON.parse(renderKey);
        data=model(this.requestedGraph);
        // What is laid out and drawn. Selection, path navigation and export read `data`, the evidence.
        picture=this.options.presentation===true?model(present(this.requestedGraph),false):data;
        layoutKey=JSON.stringify([this.direction,data.steps.map(s=>[s.id,s.type,s.title,s.actor,s.system]),data.connections.map(e=>[e.from,e.to,e.label])]);
      }catch(error){this.dropLayoutJob();this.requestedGraph=null;this.pending=false;this.layoutError=true;this.notify();throw error;}
      if(this.layout&&this.layoutKey===layoutKey){
        // All geometry and displayed labels match. Refresh the evidence behind the existing controls.
        this.dropLayoutJob();
        this.graph=data;this.renderKey=renderKey;this.pending=false;this.layoutError=false;
        this.title.textContent=`Workflow: ${data.title||"Current process"}`;
        const updateTooltip=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
        data.steps.forEach((step,index)=>updateTooltip(this.stepTitles[index],stepTooltip(step)));
        data.connections.forEach(edge=>updateTooltip(this.edgeTitles.get(edge.id),edgeTooltip(edge)));
        if(!this.fitted)this.initialView();
        this.notify();return true;
      }
      this.pending=Boolean(data.steps.length);this.layoutError=false;this.notify();
      if(!data.steps.length){this.dropLayoutJob();this.graph=data;this.layout=null;this.stepTitles=[];this.edgeTitles=null;this.selected=null;this.following=false;this.pathTrail=[];this.pathNotice="";this.fitted=false;this.fitMode=true;this.world.replaceChildren();this.miniWorld.replaceChildren();this.mini.style.display="none";this.mini.hidden=true;this.hint.textContent="Describe a step to start building the workflow.";this.notify();return true;}
      let positions,job;
      try{
        if(!workerLayouts()&&!this.engine){
          const Engine=scope.ELK||await loadEngine();
          if(this.dead||revision!==this.version)return false;
          this.engine ||= new Engine();
        }
        job=this.layoutJob;
        if(!job||job.key!==layoutKey){
          // A different map is wanted now: stop computing the one it replaces.
          job?.cancel();
          job=layeredLayout(picture,this.direction,this.size(),
            graph=>workerLayouts()?workerLayout(graph):this.engine?this.engine.layout(graph):pageLayout(graph));
          job.key=layoutKey;
          this.layoutJob=job;
        }
        positions=await job.result;
        if(this.dead||revision!==this.version)return false;
        validateLayeredRoutes(positions,picture);
      }catch(error){
        if(this.dead||revision!==this.version)return false;
        this.pending=false;this.layoutError=true;this.notify();throw error;
      }finally{
        if(job&&this.layoutJob===job)this.layoutJob=null;
      }
      this.pending=false;this.layoutError=false;
      this.strip={key:layoutKey,layout:job.strip};this.layoutShape=job.shape;
      this.show(data,orderedComponents(positions,picture),picture);
      this.layoutKey=layoutKey;this.renderKey=renderKey;
      this.notify();
      this.queueReshape();
      return true;
    }
    // Draws a new layout of `data` in place of the one on screen.
    show(data,positions,picture=data){
      const previousLayout=this.layout,previousGraph=this.graph,previousSelected=this.selected;
      const focusedStep=this.doc.activeElement?.getAttribute?.("data-step-id");
      this.graph=data;this.picture=picture;this.layout=positions;
      const path=this.following&&previousGraph&&previousGraph!==data?this.reconcilePath(previousGraph,data):null;
      if(!this.following&&previousGraph&&previousSelected){
        const old=previousGraph.steps.find(step=>step.id===previousSelected),same=data.steps.find(step=>step.id===previousSelected);
        if(old&&(!same||same.title!==old.title||same.type!==old.type)){
          const matches=data.steps.filter(step=>step.title===old.title&&step.type===old.type);
          const retainedEvidence=same?.type===old.type&&same.evidence_turns?.some(ref=>old.evidence_turns?.includes(ref));
          this.selected=matches.length===1?matches[0].id:retainedEvidence?same.id:null;
        }
      }
      this.selected=data.steps.some(step=>step.id===this.selected)?this.selected:null;
      // A correction may remove or reroute a path. Never retain an invalid trail.
      this.pathTrail=this.pathTrail.filter(id=>data.steps.some(step=>step.id===id));
      if(this.following&&!this.selected){this.following=false;this.pathTrail=[];}
      else if(this.following&&this.pathTrail.some((id,i)=>i&&!data.connections.some(edge=>edge.from===this.pathTrail[i-1]&&edge.to===id)))this.pathTrail=[this.selected];
      if(path?.notice){this.pathNotice=path.notice;this.status.textContent=path.notice;}
      // Keep the same evidence-backed step under the camera when an upstream correction shifts layout.
      if(this.fitted&&!this.fitMode&&previousLayout){
        const {width,height}=this.size(),viewWidth=width/this.camera.scale,viewHeight=height/this.camera.scale;
        const cx=this.camera.x+viewWidth/2,cy=this.camera.y+viewHeight/2;
        const inView=node=>node.x+node.width>this.camera.x&&node.x<this.camera.x+viewWidth&&node.y+node.height>this.camera.y&&node.y<this.camera.y+viewHeight;
        // A followed step that was found again under another id is anchored from where it was drawn.
        const renamed=path?.moved&&this.selected?previousSelected:null;
        // The selected step holds the view only while the reader can see it. A step selected
        // earlier and left off screen would drag the view by however far it moved.
        let before=previousLayout.children.find(node=>node.id===(renamed||this.selected));
        if(before&&!inView(before))before=null;
        if(!before){
          let nearest=Infinity;
          for(const node of previousLayout.children){
            const distance=Math.hypot(node.x+node.width/2-cx,node.y+node.height/2-cy);
            if(data.incoming.has(node.id)&&distance<nearest){before=node;nearest=distance;}
          }
        }
        const after=before&&positions.children.find(node=>node.id===(renamed&&before.id===renamed?this.selected:before.id));
        if(before&&after){this.camera.x+=after.x+after.width/2-before.x-before.width/2;this.camera.y+=after.y+after.height/2-before.y-before.height/2;}
        // Whatever the update did, the reader is not left looking at an empty canvas.
        // (Reported steps only: a marker of the picture left alone in view is still an empty canvas.)
        const boxes=positions.children.filter(node=>data.incoming.has(node.id));
        if(width&&height&&boxes.length&&!boxes.some(inView)){
          const nearest=nearestNode(boxes,{x:this.camera.x+viewWidth/2,y:this.camera.y+viewHeight/2});
          this.camera.x=nearest.x+nearest.width/2-viewWidth/2;this.camera.y=nearest.y+nearest.height/2-viewHeight/2;
        }
      }
      this.draw();
      if(focusedStep){
        this.restoringFocus=true;
        try{[...this.world.querySelectorAll("[data-step-id]")].find(node=>node.getAttribute("data-step-id")===focusedStep)?.focus({preventScroll:true});}
        finally{this.restoringFocus=false;}
      }
      if(!this.fitted)this.initialView();else if(this.fitMode)this.fit();else this.paintView();
    }
    // Brings a box into view at the current zoom with the smallest move that shows all of it,
    // or shows its middle when it is larger than the view.
    reveal(box){
      const {width,height}=this.size();if(!width||!height)return;
      const margin=16/this.camera.scale;
      const along=(start,length,view,camera)=>length+2*margin>view?start+length/2-view/2:clamp(camera,start+length+margin-view,start-margin);
      const x=along(box.x,box.width,width/this.camera.scale,this.camera.x),y=along(box.y,box.height,height/this.camera.scale,this.camera.y);
      if(x===this.camera.x&&y===this.camera.y)return;
      this.camera.x=x;this.camera.y=y;this.fitMode=false;this.paintView();
    }
    // Follow path across a map update. Ids are the provider's and can be reused for another
    // step, so each step of the trail is compared with what its id says now. A step whose
    // wording and type are unchanged is itself. One whose id now says something else is
    // followed to another id only when its old wording and type identified exactly one step
    // before and identify exactly one step now; a step that was simply reworded keeps its id.
    // Whatever the reader would otherwise have to discover (the path ended, restarted, or the
    // current step reads differently) is returned as a sentence for the live regions.
    reconcilePath(previous,data){
      const key=step=>`${TYPES[step.type]?step.type:"activity"}\n${string(step.title).trim().replace(/\s+/gu," ").toLowerCase()}`;
      const carriers=(graph,wanted)=>graph.steps.filter(step=>key(step)===wanted);
      const follow=id=>{
        const before=previous.steps.find(step=>step.id===id),now=data.steps.find(step=>step.id===id);
        if(!before||(now&&key(now)===key(before)))return now?id:null;
        const wanted=key(before),found=carriers(data,wanted);
        return carriers(previous,wanted).length===1&&found.length===1?found[0].id:now?id:null;
      };
      const was=previous.steps.find(step=>step.id===this.selected),from=this.selected;
      let trail=this.pathTrail.map(follow);
      const current=trail.at(-1)??null;
      if(!current){
        this.following=false;this.pathTrail=[];this.selected=null;
        return {moved:false,notice:"The map changed. Follow path was reset."};
      }
      const cut=trail.some((id,i)=>!id||(i&&!data.connections.some(edge=>edge.from===trail[i-1]&&edge.to===id)));
      if(cut)trail=[current];
      this.pathTrail=trail;this.selected=current;
      const now=data.steps.find(step=>step.id===current),reworded=!was||key(now)!==key(was);
      return {moved:current!==from,notice:cut?`The map changed. Follow path restarts at this step. ${this.pathSentence()}`:reworded?`The map changed. ${this.pathSentence()}`:""};
    }
    // Stops a layout that no update is waiting for any more, so it cannot hold up the next one.
    dropLayoutJob(){const job=this.layoutJob;this.layoutJob=null;job?.cancel();}
    // The fold suits the canvas shape it was made for. The panel changes shape after the first
    // drawing (its legend and step bar appear), when the reply box opens and when it is expanded;
    // once the shape has settled, the fold is decided again for the canvas as it now is.
    queueReshape(){
      if(this.dead||!this.layout||!scope.setTimeout||canvasShape(this.size(),this.picture||this.graph)===this.layoutShape)return;
      scope.clearTimeout?.(this.reshapeTimer);
      this.reshapeTimer=scope.setTimeout(()=>{this.reshapeTimer=undefined;this.reshape().catch(()=>{/* The map on screen stays. */});},RESHAPE_SETTLE_MS);
    }
    async reshape(){
      // An update that is under way reads the canvas itself and asks again when it is done.
      if(this.dead||!this.layout||this.pending||this.layoutError)return false;
      const view=this.size(),data=this.graph,picture=this.picture||data,revision=this.version,shape=canvasShape(view,picture);
      if(shape===this.layoutShape)return false;
      this.reshapeJob?.cancel();
      const job=this.reshapeJob=layeredLayout(picture,this.direction,view,
        graph=>workerLayouts()?workerLayout(graph):this.engine?this.engine.layout(graph):pageLayout(graph),
        this.strip?.key===this.layoutKey?this.strip.layout:null);
      let positions;
      try{positions=await job.result;validateLayeredRoutes(positions,picture);}
      // The map on screen is still a sound drawing of the same process; it simply stays.
      catch{return false;}
      finally{if(this.reshapeJob===job)this.reshapeJob=null;}
      if(this.dead||revision!==this.version||this.pending||this.graph!==data)return false;
      this.layoutShape=shape;
      // Redraw only for a map that Fit shows larger on this canvas than the one on screen.
      if(positions===this.layout||!sized(view)||fitScale(positions,view)<=fitScale(this.layout,view))return false;
      // A reader who has not moved the opening view gets the opening view of the new drawing.
      const opening=this.opening,camera=this.camera;
      if(opening&&opening.x===camera.x&&opening.y===camera.y&&opening.scale===camera.scale)this.fitted=false;
      this.show(data,orderedComponents(positions,picture),picture);
      this.notify();
      return true;
    }
    initialView(){
      const {width,height}=this.size();if(!width||!height){this.fitMode=true;return;}
      const overviewScale=Math.min((width-48)/this.layout.width,(height-48)/this.layout.height);
      if(overviewScale>=.6){this.fit();this.opening={...this.camera};return;}
      const start=initialStep(this.graph),anchor=this.layout.children.find(node=>node.id===start.id);
      const scale=clamp(Math.min(.8,(width-40)/anchor.width,(height-56)/anchor.height),.05,.8);
      // Larger flows start on a complete readable first step, including on a phone.
      this.camera={x:width<500||this.direction==="DOWN"?anchor.x+anchor.width/2-width/scale/2:anchor.x-28/scale,y:anchor.y-28/scale,scale};
      // The start marker of the picture stands in front of that step: the opening view takes it in.
      const marker=this.layout.children.find(node=>node.id==="~start");
      if(marker){this.camera.x=Math.min(this.camera.x,marker.x-16/scale);this.camera.y=Math.min(this.camera.y,marker.y-16/scale);}
      this.fitMode=false;this.fitted=true;this.opening={...this.camera};this.paintView();
    }
    fit(){
      if(!this.layout)return;const {width,height}=this.size();if(!width||!height)return;
      const scale=clamp(Math.min((width-40)/this.layout.width,(height-48)/this.layout.height),.000001,1.35);
      this.camera={x:(this.layout.width-width/scale)/2,y:(this.layout.height-height/scale)/2,scale};this.fitMode=true;this.fitted=true;this.paintView();
    }
    refresh(){
      if(!this.layout)return;const size=this.size();if(!size.width||!size.height)return;
      this.queueReshape();
      if(this.autoDirectionPending){this.autoDirectionPending=false;const direction=size.width<640?"DOWN":"RIGHT";if(direction!==this.direction)return this.setDirection(direction).catch(()=>{this.status.textContent="The layout could not be refreshed. Change direction to retry.";});}
      if(!this.fitted){this.initialView();return;}
      if(this.fitMode){this.fit();return;}
      if(this.lastSize&&(this.lastSize.width!==size.width||this.lastSize.height!==size.height)){
        if(this.opening&&this.camera.x===this.opening.x&&this.camera.y===this.opening.y&&this.camera.scale===this.opening.scale){this.initialView();return;}
        const center={x:this.camera.x+this.lastSize.width/this.camera.scale/2,y:this.camera.y+this.lastSize.height/this.camera.scale/2};
        this.camera.x=center.x-size.width/this.camera.scale/2;this.camera.y=center.y-size.height/this.camera.scale/2;
        const viewWidth=size.width/this.camera.scale,viewHeight=size.height/this.camera.scale,right=this.camera.x+viewWidth,bottom=this.camera.y+viewHeight;
        // The reported steps decide what counts as something to look at, not the markers of the picture.
        const boxes=this.layout.children.filter(n=>this.graph.incoming.has(n.id));
        const fitting=boxes.filter(n=>n.width<=viewWidth&&n.height<=viewHeight);
        const fullyVisible=fitting.some(n=>n.x>=this.camera.x&&n.x+n.width<=right&&n.y>=this.camera.y&&n.y+n.height<=bottom);
        const intersects=boxes.some(n=>n.x+n.width>this.camera.x&&n.x<right&&n.y+n.height>this.camera.y&&n.y<bottom);
        if((fitting.length?!fullyVisible:!intersects)&&boxes.length){
          const nearest=nearestNode(fitting.length?fitting:boxes,center);
          this.camera.x=nearest.x+nearest.width/2-size.width/this.camera.scale/2;this.camera.y=nearest.y+nearest.height/2-size.height/this.camera.scale/2;
        }
      }
      this.paintView();
    }
    getScale(){return this.camera.scale;}
    getDirection(){return this.direction;}
    getSteps(){return (this.graph?.steps||[]).map(({id,title,type})=>({id,title,type}));}
    getPathNavigation(){
      const current=this.graph?.steps.find(step=>step.id===this.selected),choice=edge=>({id:edge.to,label:edge.label||this.graph.steps.find(step=>step.id===edge.to)?.title||edge.to,from:edge.from,to:edge.to});
      return {following:this.following,current:current?{id:current.id,title:current.title,type:current.type}:null,trail:[...this.pathTrail],notice:this.pathNotice||"",
        next:current?(this.graph.outgoing.get(current.id)||[]).map(choice):[],
        previous:current?(this.graph.incoming.get(current.id)||[]).map(edge=>({...choice(edge),id:edge.from,label:edge.label||this.graph.steps.find(step=>step.id===edge.from)?.title||edge.from})):[]};
    }
    followPath(id=this.selected){
      if(!this.graph?.steps.length||!this.layout||this.pending||this.layoutError)return false;
      id=id||initialStep(this.graph).id;
      if(!this.graph.steps.some(step=>step.id===id))return false;
      this.following=true;this.selected=id;this.pathTrail=[id];this.pathNotice="";this.drawSelection();this.focusStep(id,{readable:true,keyboard:false});this.announcePath();return true;
    }
    leavePath(){this.following=false;this.pathTrail=[];this.pathNotice="";this.drawSelection();this.status.textContent="All reported workflow routes are visible.";this.notify();}
    navigatePath(id,direction="auto"){
      if(!this.following||!this.graph||this.pending||this.layoutError)return false;
      const next=this.graph.outgoing.get(this.selected)||[],previous=this.graph.incoming.get(this.selected)||[];
      const forward=direction!=="previous"&&next.some(edge=>edge.to===id),backward=direction!=="next"&&previous.some(edge=>edge.from===id);
      if(!["auto","next","previous"].includes(direction)||(!forward&&!backward))return false;
      if(forward)this.pathTrail.push(id);
      else if(this.pathTrail.at(-2)===id)this.pathTrail.pop();
      else this.pathTrail=[id];
      this.selected=id;this.pathNotice="";this.drawSelection();this.focusStep(id,{readable:true,keyboard:false});this.announcePath();return true;
    }
    pathSentence(){const state=this.getPathNavigation(),parallel=state.current?.type==="parallel_split";return `${state.current?.title||"Workflow"}. ${state.next.length>1?`${state.next.length} reported branches. ${parallel?"All branches proceed. Choose a branch to inspect.":"Choose the next route."}`:state.next.length?"One reported next step.":"No reported next step."}`;}
    // The reader's own move on the path replaces whatever the last map update had to say about it.
    announcePath(){this.pathNotice="";this.status.textContent=this.pathSentence();}
    setDirection(direction){
      if(!["RIGHT","DOWN"].includes(direction))throw new Error("Choose a horizontal or vertical workflow layout.");
      this.autoDirectionPending=false;
      if(this.layoutError&&!this.requestedGraph)return Promise.reject(new Error("The current workflow is invalid and cannot be laid out."));
      if(this.direction===direction)return Promise.resolve(false);
      this.direction=direction;
      const current=this.requestedGraph||this.graph;
      return current?this.update({title:current.title,steps:current.steps,connections:current.connections}):Promise.resolve(false);
    }
    minimumScale(){const {width,height}=this.size();return this.layout?Math.max(.000001,Math.min(.05,(width-40)/this.layout.width,(height-48)/this.layout.height)):.05;}
    zoom(delta){this.zoomAt(clamp(this.camera.scale*Math.exp(delta*2),this.minimumScale(),2.5));}
    zoomAt(scale,clientPoint){
      if(!this.layout)return;const {width,height}=this.size(),rect=this.svg.getBoundingClientRect();
      const px=clientPoint?clientPoint.x-rect.left:width/2,py=clientPoint?clientPoint.y-rect.top:height/2;
      const worldX=this.camera.x+px/this.camera.scale,worldY=this.camera.y+py/this.camera.scale;
      this.camera={scale,x:worldX-px/scale,y:worldY-py/scale};this.clampCamera();this.fitMode=false;this.paintView();
    }
    paintView(){
      const {width,height}=this.size();if(!width||!height||!this.layout)return;
      this.lastSize={width,height};
      this.svg.setAttribute("viewBox",`${this.camera.x} ${this.camera.y} ${width/this.camera.scale} ${height/this.camera.scale}`);
      const showMini=!this.fitMode&&width>=500&&height>=200;this.mini.style.display=showMini?"block":"none";this.hint.style.display=width>=420&&height>=180?"block":"none";
      const bounds={x:0,y:0,width:this.layout.width,height:this.layout.height};
      this.mini.setAttribute("viewBox",`${bounds.x-10} ${bounds.y-10} ${bounds.width+20} ${bounds.height+20}`);
      for(const [key,value] of Object.entries({x:this.camera.x,y:this.camera.y,width:width/this.camera.scale,height:height/this.camera.scale}))this.miniView.setAttribute(key,value);
      this.notify();
    }
    pointerDown(event){
      if(event.button!==undefined&&event.button!==0)return;
      const onStep=event.target.closest?.("[data-step-id]");
      if(!this.pointers.size){this.pointerMoved=false;this.dragOrigin={x:event.clientX,y:event.clientY};}
      if(!onStep){this.svg.focus({preventScroll:true});this.svg.setPointerCapture?.(event.pointerId);}
      event.preventDefault();this.pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});this.svg.style.cursor="grabbing";
      if(this.pointers.size===2)this.pinch=this.pinchData();
    }
    pinchData(){const [a,b]=[...this.pointers.values()];return {distance:Math.hypot(b.x-a.x,b.y-a.y),center:{x:(a.x+b.x)/2,y:(a.y+b.y)/2}};}
    pointerMove(event){
      const previous=this.pointers.get(event.pointerId);if(!previous||!this.layout)return;
      const next={x:event.clientX,y:event.clientY};this.pointers.set(event.pointerId,next);
      if(this.pointers.size===1&&!this.pointerMoved&&Math.hypot(next.x-this.dragOrigin.x,next.y-this.dragOrigin.y)<4)return;
      this.svg.setPointerCapture?.(event.pointerId);this.fitMode=false;
      if(this.pointers.size===2){const pinch=this.pinchData();if(this.pinch?.distance)this.zoomAt(clamp(this.camera.scale*pinch.distance/this.pinch.distance,this.minimumScale(),2.5),pinch.center);this.pinch=pinch;}
      else this.pan(-(next.x-previous.x)/this.camera.scale,-(next.y-previous.y)/this.camera.scale);
      this.pointerMoved=true;
    }
    pointerUp(event){this.pointers.delete(event.pointerId);this.pinch=null;this.dragOrigin=this.pointers.values().next().value;try{this.svg.releasePointerCapture?.(event.pointerId);}catch{/* Cancelled pointers may already have released capture. */}this.svg.style.cursor="grab";}
    // Keeps part of the map in view: at least a thumb's width of the area the steps occupy, and,
    // when the move started with a step in view, a step. `from` is the camera before the move.
    clampCamera(from=null){
      // Reported steps bound the view; the markers of the picture lie beside them.
      const {width,height}=this.size(),nodes=(this.layout?.children||[]).filter(n=>!this.graph||this.graph.incoming.has(n.id));if(!width||!height||!nodes.length)return;
      const viewWidth=width/this.camera.scale,viewHeight=height/this.camera.scale;
      const left=Math.min(...nodes.map(n=>n.x)),right=Math.max(...nodes.map(n=>n.x+n.width)),top=Math.min(...nodes.map(n=>n.y)),bottom=Math.max(...nodes.map(n=>n.y+n.height));
      const keepX=Math.min(48/this.camera.scale,(right-left)/2),keepY=Math.min(48/this.camera.scale,(bottom-top)/2);
      this.camera.x=clamp(this.camera.x,left+keepX-viewWidth,right-keepX);this.camera.y=clamp(this.camera.y,top+keepY-viewHeight,bottom-keepY);
      if(!from)return;
      const shows=camera=>nodes.some(n=>n.x+n.width>camera.x&&n.x<camera.x+viewWidth&&n.y+n.height>camera.y&&n.y<camera.y+viewHeight);
      if(!shows(from)||shows(this.camera))return;
      // The steps do not fill that area (separate groups, a branch on one side). Keep the part
      // of the move that still shows a step; otherwise stay.
      const {x,y}=this.camera;
      if(shows({x:from.x,y}))this.camera.x=from.x;
      else if(shows({x,y:from.y}))this.camera.y=from.y;
      else{this.camera.x=from.x;this.camera.y=from.y;}
    }
    // Moves the view by a distance in map units. Returns false when the edge of the map leaves no room to move.
    pan(dx,dy){
      if(!this.layout)return false;
      const from={x:this.camera.x,y:this.camera.y};
      this.camera.x+=dx;this.camera.y+=dy;this.clampCamera(from);
      if(this.camera.x===from.x&&this.camera.y===from.y)return false;
      this.fitMode=false;this.paintView();return true;
    }
    wheel(event){
      if(!this.layout)return;
      if(event.ctrlKey||event.metaKey){event.preventDefault();this.zoomAt(clamp(this.camera.scale*Math.exp(-event.deltaY*.004),this.minimumScale(),2.5),{x:event.clientX,y:event.clientY});}
      // At the edge of the map the wheel is left to the page, so the page scrolls on.
      else if(this.pan(event.deltaX/this.camera.scale,event.deltaY/this.camera.scale))event.preventDefault();
    }
    key(event){
      if(event.ctrlKey||event.metaKey||event.altKey)return;
      if(event.key==="Escape"&&this.following){event.preventDefault();this.leavePath();return;}
      if(event.key?.toLowerCase()==="f"){event.preventDefault();this.followPath(event.target.getAttribute?.("data-step-id")||this.selected);return;}
      const onCanvas=event.target===this.svg;
      const move={ArrowLeft:[-80,0],ArrowRight:[80,0],ArrowUp:[0,-80],ArrowDown:[0,80]}[event.key];
      if(move&&onCanvas){event.preventDefault();this.pan(move[0]/this.camera.scale,move[1]/this.camera.scale);}
      if(event.key==="+"||event.key==="="){event.preventDefault();this.zoom(.15);}
      if(event.key==="-"){event.preventDefault();this.zoom(-.15);}
      if(event.key==="0"||event.key==="Home"){event.preventDefault();this.fit();}
    }
    navigateMini(event){
      if(!this.layout)return;event.preventDefault();const box=this.mini.getBoundingClientRect(),w=this.layout.width+20,h=this.layout.height+20,scale=Math.min(box.width/w,box.height/h),offsetX=(box.width-w*scale)/2,offsetY=(box.height-h*scale)/2;
      const x=(event.clientX-box.left-offsetX)/scale-10,y=(event.clientY-box.top-offsetY)/scale-10,{width,height}=this.size();this.camera.x=x-width/this.camera.scale/2;this.camera.y=y-height/this.camera.scale/2;this.clampCamera();this.fitMode=false;this.paintView();
    }
    select(step){this.selected=step.id;this.pathNotice="";if(this.following){this.pathTrail=[step.id];this.focusStep(step.id,{readable:true,keyboard:false});this.announcePath();}this.drawSelection();this.options.onSelectStep?.({...step});this.notify();}
    drawSelection(){
      const related=new Set(this.following?[this.selected,...this.pathTrail]:[]),activeEdges=new Set();
      if(this.following)for(const edge of this.graph?.connections||[]){if(edge.from===this.selected||edge.to===this.selected||this.pathTrail.some((id,i)=>i&&id===edge.to&&this.pathTrail[i-1]===edge.from)){related.add(edge.from);related.add(edge.to);activeEdges.add(edge.id);}}
      this.world.querySelectorAll?.("[data-step-id]").forEach(node=>{const id=node.getAttribute("data-step-id"),active=id===this.selected;node.setAttribute("aria-pressed",String(active));node.setAttribute("opacity",this.following&&!related.has(id)?.28:1);const shape=node.querySelector(".workflow-node-shape");if(shape){shape.setAttribute("stroke-width",active?2.5:1.4);shape.setAttribute("stroke",active?"#dc6e2c":shape.getAttribute("data-base-stroke"));}});
      this.world.querySelectorAll?.("[data-edge-id]").forEach(node=>{node.setAttribute("opacity",this.following&&!activeEdges.has(node.getAttribute("data-edge-id"))?.22:1);});
      this.world.querySelectorAll?.("[data-edge-label-for]").forEach(node=>{node.setAttribute("opacity",this.following&&!activeEdges.has(node.getAttribute("data-edge-label-for"))?.22:1);});
      this.hint.textContent=this.following?"Following the path · Select a branch to inspect":"Drag to move around · Select a step for details";
    }
    focusNeighbor(position,key){
      const horizontal=key==="ArrowLeft"||key==="ArrowRight";
      const sign=key==="ArrowLeft"||key==="ArrowUp"?-1:1;
      const x=position.x+position.width/2,y=position.y+position.height/2;
      const linked=new Set([
        ...this.graph.incoming.get(position.id).map(edge=>edge.from),
        ...this.graph.outgoing.get(position.id).map(edge=>edge.to)
      ]);
      let best=null,bestLinked=false,bestDistance=Infinity;
      for(const node of this.layout.children){
        if(!this.graph.incoming.has(node.id))continue;  // A marker of the picture is not a step.
        const dx=node.x+node.width/2-x,dy=node.y+node.height/2-y;
        const ahead=sign*(horizontal?dx:dy),across=Math.abs(horizontal?dy:dx);
        // Search the quadrant facing this arrow. A node on the next parallel
        // branch remains reachable even when the two steps have no direct link.
        if(ahead<=0||across>ahead)continue;
        const connected=linked.has(node.id),distance=Math.hypot(ahead,across)+across;
        if((connected&&!bestLinked)||(connected===bestLinked&&distance<bestDistance)){
          best=node;bestLinked=connected;bestDistance=distance;
        }
      }
      if(best)this.focusStep(best.id);
    }
    draw(){
      const doc=this.doc,layout=this.layout,data=this.graph;this.world.replaceChildren();this.miniWorld.replaceChildren();this.mini.hidden=false;
      this.hint.textContent="Drag to move around · Select a step for details";
      this.title.textContent=`Workflow: ${data.title||"Current process"}`;
      this.description.textContent=`${data.steps.length} reported steps and ${data.connections.length} reported connections. ${data.steps.map(step=>`${step.id}: ${step.title}, ${step.actor||"owner not established"}`).join(". ")}`;
      const defs=svgNode(doc,"defs"),arrow=svgNode(doc,"marker",{id:`${this.uid}-arrow`,viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:7,markerHeight:7,orient:"auto-start-reverse"});arrow.append(svgNode(doc,"path",{class:"wf-arrow",d:"M 1 1 L 9 5 L 1 9 z",fill:"#718197"}));defs.append(arrow);this.world.append(defs);
      const edges=svgNode(doc,"g",{class:"workflow-edges"}),edgeLabels=svgNode(doc,"g");this.world.append(edges);
      const picture=this.picture||data;
      const byEdgeId=new Map(data.connections.map(edge=>[edge.id,edge]));
      const drawnEdges=new Map(picture.connections.map(edge=>[edge.id,edge]));
      const markers=new Map(picture.steps.filter(step=>step.implied).map(step=>[step.id,step]));
      const stepIndex=new Map(data.steps.map((step,index)=>[step.id,index]));
      this.edgeTitles=new Map();this.stepTitles=[];
      layout.edges.forEach(edge=>{
        if(drawnEdges.get(edge.id)?.implied){
          // A link to or from a marker: part of the picture, not a reported connection.
          const link=svgNode(doc,"g",{"data-implied-edge":""});
          (edge.sections||[]).forEach(section=>{const p=points(section);link.append(svgNode(doc,"path",{class:"wf-edge wf-implied-edge",d:roundedPath(p),fill:"none",stroke:"#9aa7b6","stroke-width":1.4,"stroke-dasharray":"4 3","stroke-linejoin":"round","marker-end":`url(#${this.uid}-arrow)`}));});
          edges.append(link);return;
        }
        const original=byEdgeId.get(edge.id);if(!original)return;
        const group=svgNode(doc,"g",{"data-edge-id":edge.id}),tooltip=svgNode(doc,"title",{},edgeTooltip(original));
        group.append(tooltip);this.edgeTitles.set(edge.id,tooltip);
        (edge.sections||[]).forEach(section=>{const p=points(section);group.append(svgNode(doc,"path",{class:"wf-edge",d:roundedPath(p),fill:"none",stroke:"#718197","stroke-width":1.6,"stroke-linejoin":"round","marker-end":`url(#${this.uid}-arrow)`}));this.miniWorld.append(svgNode(doc,"path",{class:"wf-mini-edge",d:roundedPath(p,0),fill:"none",stroke:"#a4b0be","stroke-width":3}));});edges.append(group);
        const labelGroup=svgNode(doc,"g",{"data-edge-label-for":edge.id});
        (edge.labels||[]).forEach(label=>{
          const x=label.x||0,y=label.y||0,words=edgeMetrics(original.label).lines;labelGroup.append(svgNode(doc,"rect",{class:"wf-edge-label",x,y,width:label.width,height:label.height,rx:5,fill:"#ffffff",stroke:"#d9e0e8","stroke-width":.8}));
          const text=svgNode(doc,"text",{class:"wf-edge-text",x:x+label.width/2,y:y+18,fill:"#4f6178","font-family":FONT,"font-size":11,"font-weight":500,"text-anchor":"middle","data-text-box":`${x+10} ${y+5} ${label.width-20} ${label.height-10}`});words.forEach((line,i)=>text.append(svgNode(doc,"tspan",{x:x+label.width/2,dy:i?15:0},line)));labelGroup.append(text);
        });edgeLabels.append(labelGroup);
      });
      this.world.append(edgeLabels);
      if(!data.steps.some(step=>step.id===this.tabStep))this.tabStep=data.steps[0]?.id;
      layout.children.forEach(position=>{
        const marker=markers.get(position.id);
        if(marker){
          // Drawn apart from the reported steps: dashed, without a label, and not a control.
          const {x,y,width:w,height:h}=position,theme=TYPES[marker.type]||TYPES.activity;
          const mark=svgNode(doc,"g",{"data-implied":marker.implied,"data-node-box":`${x} ${y} ${w} ${h}`,"aria-hidden":"true"});
          mark.append(svgNode(doc,"title",{},markerTooltip(marker)));
          const outline=nodeShape(doc,marker.type,x,y,w,h);outline.classList.add("workflow-implied-shape");
          outline.setAttribute("stroke-dasharray","4 3");outline.setAttribute("stroke-width",marker.implied==="end"?2.4:1.4);mark.append(outline);
          this.world.append(mark);
          const small=nodeShape(doc,marker.type,x,y,w,h,true);small.classList.add("wf-mini-node");small.setAttribute("fill",theme.stroke);small.setAttribute("opacity",.6);this.miniWorld.append(small);
          return;
        }
        const index=stepIndex.get(position.id),step=data.steps[index],{x,y,width:w,height:h}=position,metrics=nodeMetrics(step),type=metrics.type,theme=TYPES[type],color=colorFor(step.actor);
        const group=svgNode(doc,"g",{"data-step-id":step.id,"data-step-type":type,"data-node-box":`${x} ${y} ${w} ${h}`,tabindex:step.id===(this.tabStep||this.selected||this.layout.children[0]?.id)?"0":"-1",role:"button","aria-label":`${step.id}: ${step.title}. ${theme.label}. ${step.actor||"Owner not established"}. Show details.`,"aria-pressed":"false"});group.style.setProperty?.("--actor-color",color);styles(group,{cursor:"pointer",outline:"none"});
        const tooltip=svgNode(doc,"title",{},stepTooltip(step));group.append(tooltip);this.stepTitles[index]=tooltip;
        const shape=nodeShape(doc,type,x,y,w,h);shape.classList.add("workflow-node-shape");if(type==="decision")shape.classList.add("is-decision");shape.setAttribute("data-base-stroke",theme.stroke);group.append(shape);
        if(type==="subprocess")group.append(svgNode(doc,"path",{d:`M ${x+13} ${y+1} V ${y+h-1} M ${x+w-13} ${y+1} V ${y+h-1}`,stroke:theme.stroke,fill:"none","stroke-width":1}));
        if(type==="data_store")group.append(svgNode(doc,"path",{d:`M ${x} ${y+12} C ${x} ${y+28} ${x+w} ${y+28} ${x+w} ${y+12}`,stroke:theme.stroke,fill:"none","stroke-width":1}));
        if(type==="end")group.append(svgNode(doc,"rect",{x:x+5,y:y+5,width:w-10,height:h-10,rx:Math.min(43,(h-10)/2),stroke:theme.stroke,fill:"none","stroke-width":.8}));
        for(const block of metrics.blocks){
          const center=x+block.x+block.width/2,text=svgNode(doc,"text",{class:"wf-"+block.role,direction:/^[^A-Za-z\u0590-\u08ff]*[\u0590-\u08ff]/u.test(block.lines.join(" "))?"rtl":"ltr","unicode-bidi":"plaintext",x:center,y:y+block.y+block.size,"text-anchor":"middle","font-family":FONT,"font-size":block.size,"font-weight":block.weight,fill:block.role==="title"?"#26354a":block.role==="actor"?color:block.role==="kind"?"#53657b":"#646b75","data-text-box":`${x+block.x} ${y+block.y} ${block.width} ${block.height}`});
          block.lines.forEach((line,i)=>text.append(svgNode(doc,"tspan",{x:center,dy:i?block.lineHeight:0},line)));group.append(text);
        }
        group.addEventListener("click",event=>{if(!this.pointerMoved||event.detail===0)this.select(this.graph.steps[index]);});
        group.addEventListener("keydown",event=>{
          if(event.ctrlKey||event.altKey||event.metaKey)return;
          if(event.key==="Enter"||event.key===" "){event.preventDefault();this.select(this.graph.steps[index]);}
          if(["ArrowRight","ArrowLeft","ArrowDown","ArrowUp"].includes(event.key)){
            event.preventDefault();this.focusNeighbor(position,event.key);
          }
        });
        group.addEventListener("focus",()=>{
          this.tabStep=step.id;for(const btn of this.world.querySelectorAll("[data-step-id]"))btn.setAttribute("tabindex",btn===group?"0":"-1");
          group.setAttribute("opacity",1);shape.setAttribute("stroke","#dc6e2c");shape.setAttribute("stroke-width",2.5);
          // Tab can land on a step that is off screen. A click focuses a step too, and then the
          // map must not move under the pointer; a redraw giving focus back is not the reader either.
          let keyboard=false;
          try{keyboard=!this.restoringFocus&&group.matches(":focus-visible");}catch{/* Without :focus-visible the view stays as it is. */}
          if(keyboard)this.reveal(position);
        });
        group.addEventListener("blur",()=>this.drawSelection());
        this.world.append(group);
        const miniShape=nodeShape(doc,type,x,y,w,h,true);miniShape.classList.add("wf-mini-node");if(type==="decision")miniShape.classList.add("is-decision");miniShape.setAttribute("fill",theme.stroke);this.miniWorld.append(miniShape);
      });
      this.drawSelection();
    }
    focusStep(id,{readable=false,keyboard=true,select=false}={}){
      const node=this.layout?.children.find(item=>item.id===id);if(!node)return;
      const {width,height}=this.size();if(!width||!height)return;
      if(select){this.selected=id;this.pathNotice="";if(this.following)this.pathTrail=[id];this.drawSelection();}
      if(readable)this.camera.scale=clamp(Math.max(this.camera.scale,.95),.05,Math.max(.05,Math.min((width-32)/node.width,(height-32)/node.height,1.35)));
      this.camera.x=node.x+node.width/2-width/this.camera.scale/2;this.camera.y=node.y+node.height/2-height/this.camera.scale/2;this.fitMode=false;this.paintView();
      if(keyboard)[...this.world.querySelectorAll("[data-step-id]")].find(item=>item.getAttribute("data-step-id")===id)?.focus({preventScroll:true});
    }
    // The layout of the reported steps and connections alone, for a file that states evidence
    // (the BPMN download). Markers are left out. A connection that leaves a gateway in the picture
    // is given back its whole way: from its step, through the place of the gateway, to its target.
    exportLayout(){
      const picture=this.picture||this.graph;
      if(!this.layout||!this.graph||picture===this.graph)return this.layout;
      const routes=new Map(this.layout.edges.map(edge=>[edge.id,edge])),drawn=new Map(picture.connections.map(edge=>[edge.id,edge]));
      const stubs=new Map(picture.connections.filter(edge=>edge.implied&&edge.to.startsWith("~gate:")).map(edge=>[edge.to,routes.get(edge.id)]));
      return {...this.layout,children:this.layout.children.filter(node=>this.graph.incoming.has(node.id)),
        edges:this.graph.connections.map(edge=>{
          const route=routes.get(edge.id),from=drawn.get(edge.id)?.from,section=route?.sections?.[0],lead=from!==edge.from?stubs.get(from)?.sections?.[0]:null;
          if(!route||!section||!lead)return route;
          return {...route,sections:[{...section,startPoint:lead.startPoint,bendPoints:[...(lead.bendPoints||[]),lead.endPoint,section.startPoint,...(section.bendPoints||[])]}]};
        }).filter(Boolean)};
    }
    exportSVG(metadata=null){
      if(!this.layout||this.pending||this.layoutError||this.dead)return null;
      const svg=svgNode(this.doc,"svg",{xmlns:NS,viewBox:`0 0 ${this.layout.width} ${this.layout.height}`,width:this.layout.width,height:this.layout.height,role:"img"});
      svg.append(this.title.cloneNode(true),this.description.cloneNode(true),svgNode(this.doc,"rect",{width:this.layout.width,height:this.layout.height,fill:"#ffffff"}),this.world.cloneNode(true));
      if(metadata){
        const heading=64,width=Math.max(620,this.layout.width),height=heading+this.layout.height,world=svg.lastElementChild;
        svg.setAttribute("viewBox","0 0 "+width+" "+height);svg.setAttribute("width",width);svg.setAttribute("height",height);
        world?.setAttribute("transform","translate(0 "+heading+")");
        svg.append(svgNode(this.doc,"rect",{width,height:heading,fill:"#ffffff"}));
        const line=(label,y,size)=>svg.append(svgNode(this.doc,"text",{x:12,y,fill:"#1c2633","font-size":size,"font-family":"Arial, sans-serif"},label));
        line(metadata.title||"Process workflow",19,16);
        line([metadata.state,metadata.example?"Fictional example":"",metadata.stale?"Out of date":""].filter(Boolean).join(" · "),38,12);
        line("Exported "+metadata.date+" · Evidence details are included in step and route descriptions.",54,10);
        for(const group of svg.querySelectorAll?.("[data-step-id]")||[]){
          const step=this.graph.steps.find(row=>row.id===group.getAttribute("data-step-id"));
          if(!step)continue;
          if(!step.evidence_turns?.length||step.reviewed_fields?.length){
            const title=group.querySelector?.("title");if(title)title.textContent+=" · "+(step.reviewed_fields?.length?"Edited in review · verify sources":"No cited source");
            group.querySelector?.(".workflow-node-shape")?.setAttribute("stroke-dasharray","5 3");
          }
        }
      }
      // The file says of itself that its steps and routes carry their evidence. The markers the
      // picture adds (a start or end nobody stated, a gateway) carry none and are left out of it.
      for(const selector of ["[data-implied]","[data-implied-edge]"])svg.querySelectorAll?.(selector).forEach(node=>node.remove());
      svg.querySelectorAll?.("[tabindex]").forEach(node=>{node.removeAttribute("tabindex");node.removeAttribute("role");node.removeAttribute("aria-pressed");});
      // Focus is a navigation aid; an exported full workflow retains every route equally.
      svg.querySelectorAll?.("[opacity]").forEach(node=>node.removeAttribute("opacity"));
      svg.querySelectorAll?.(".workflow-node-shape").forEach(node=>{node.setAttribute("stroke",node.getAttribute("data-base-stroke"));node.setAttribute("stroke-width",1.4);});
      // XML 1.0 forbids these code points even in otherwise valid, escaped text.
      return new scope.XMLSerializer().serializeToString(svg).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff\uD800-\uDFFF]/gu,"\uFFFD");
    }
    destroy(){
      if(this.originalTabIndex==null)this.container.removeAttribute?.("tabindex");else this.container.setAttribute("tabindex",this.originalTabIndex);
      this.dead=true;this.pending=false;this.version++;this.dropLayoutJob();this.reshapeJob?.cancel();scope.clearTimeout?.(this.reshapeTimer);this.observer?.disconnect();try{this.engine?.terminateWorker?.();}catch{/* ELK's in-process browser worker has no terminate method. */}this.listeners.forEach(([target,name,fn,options])=>target.removeEventListener(name,fn,options));this.listeners=[];this.container.replaceChildren();this.container.classList.remove("workflow-canvas");
    }
  }
  scope.CollectorWorkflow={create:(container,options)=>new Canvas(container,options),model,present,elkGraph,cinematicLayout,roundedPath,measureText,wrapText,known,nodeMetrics,edgeMetrics,types:TYPES};
})(typeof window!=="undefined"?window:globalThis);
