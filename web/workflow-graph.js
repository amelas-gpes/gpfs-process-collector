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
  function wrap(value,limit=29,max=3) {
    const words=string(value).split(/\s+/).filter(Boolean),lines=[];let line="";
    for(const word of words) {
      if((line+" "+word).trim().length>limit&&line){lines.push(line);line=word;}else line=(line+" "+word).trim();
    }
    if(line)lines.push(line);
    if(lines.length>max)return lines.slice(0,max-1).concat(lines[max-1].slice(0,limit-1)+"…");
    return lines.map(line=>line.length>limit+5?line.slice(0,limit+3)+"…":line);
  }
  const short=(value,max)=>{const s=string(value);return s.length>max?s.slice(0,max-1)+"…":s;};
  function colorFor(actor) {let hash=0;for(const ch of string(actor))hash=(hash*31+ch.charCodeAt(0))>>>0;return PALETTE[hash%PALETTE.length];}
  function model(graph) {
    if(!graph||!Array.isArray(graph.steps)||!Array.isArray(graph.connections))throw new Error("The workflow is missing steps or connections.");
    if(graph.steps.length>80||graph.connections.length>150)throw new Error("This workflow is too large to display in one canvas.");
    const seen=new Set(),steps=graph.steps.map(step=>{
      if(!step||typeof step.id!=="string"||!step.id||seen.has(step.id))throw new Error("Workflow step IDs must be unique.");
      seen.add(step.id);return {...step};
    });
    const connections=graph.connections.map((edge,index)=>{
      if(!edge||!seen.has(edge.from)||!seen.has(edge.to))throw new Error("A workflow connection points to a missing step.");
      return {...edge,id:`edge-${index}`};
    });
    const incoming=new Map(steps.map(step=>[step.id,[]])),outgoing=new Map(steps.map(step=>[step.id,[]]));
    connections.forEach(edge=>{incoming.get(edge.to).push(edge);outgoing.get(edge.from).push(edge);});
    return {title:string(graph.title),steps,connections,incoming,outgoing};
  }
  function elkGraph(data,direction="RIGHT") {
    const vertical=direction==="DOWN";
    return {id:"workflow",layoutOptions:{
      "elk.algorithm":"layered","elk.direction":vertical?"DOWN":"RIGHT","elk.edgeRouting":"ORTHOGONAL",
      "elk.padding":"[top=40,left=40,bottom=40,right=40]","elk.spacing.nodeNode":"44",
      "elk.layered.spacing.nodeNodeBetweenLayers":"50","elk.spacing.edgeNode":"28",
      "elk.layered.spacing.edgeNodeBetweenLayers":"22","elk.spacing.edgeEdge":"20",
      "elk.layered.spacing.edgeEdgeBetweenLayers":"20","elk.layered.considerModelOrder.strategy":"NODES_AND_EDGES",
      "elk.layered.nodePlacement.strategy":"NETWORK_SIMPLEX","elk.layered.cycleBreaking.strategy":"MODEL_ORDER",
      "elk.layered.crossingMinimization.strategy":"LAYER_SWEEP","elk.separateConnectedComponents":"true"
    },children:data.steps.map(step=>{
      const width=step.type==="decision"?238:226,height=step.type==="decision"?168:118;
      return {id:step.id,width,height,layoutOptions:{"elk.portConstraints":"FIXED_POS"},ports:[
        {id:`${step.id}::in`,x:vertical?width/2:0,y:vertical?0:height/2,width:0,height:0,layoutOptions:{"elk.port.side":vertical?"NORTH":"WEST"}},
        {id:`${step.id}::out`,x:vertical?width/2:width,y:vertical?height:height/2,width:0,height:0,layoutOptions:{"elk.port.side":vertical?"SOUTH":"EAST"}}
      ]};
    }),edges:data.connections.map(edge=>({id:edge.id,sources:[`${edge.from}::out`],targets:[`${edge.to}::in`],
        labels:edge.label?[{id:`${edge.id}-label`,text:string(edge.label),width:Math.min(130,Math.max(34,Math.min(string(edge.label).length,19)*6+18)),height:wrap(edge.label,19,3).length*14+12}]:[]
      }))};
  }
  function points(section) {return [section.startPoint,...(section.bendPoints||[]),section.endPoint].filter(Boolean);}
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
  class Canvas {
    constructor(container,options={}) {
      if(!container)throw new Error("A workflow container is required.");
      this.container=container;this.doc=container.ownerDocument||scope.document;this.options=options;
      this.uid=`workflow-${++serial}`;this.version=0;this.dead=false;this.graph=null;this.requestedGraph=null;this.layout=null;this.fitted=false;this.fitMode=true;this.pending=false;this.layoutError=false;this.lastSize=null;
      this.camera={x:0,y:0,scale:1};this.direction=options.direction==="DOWN"?"DOWN":"RIGHT";this.selected=null;this.following=false;this.pathTrail=[];this.listeners=[];this.pointers=new Map();this.pointerMoved=false;
      if(!scope.ELK)throw new Error("The local workflow layout engine could not load.");
      this.engine=new scope.ELK();
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
      this.hint=this.doc.createElement("div");this.hint.className="workflow-canvas-hint";this.hint.textContent="Drag to explore · Select a step for detail";
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
      let data;
      try{data=model(graph);}catch(error){this.requestedGraph=null;this.pending=false;this.layoutError=true;this.notify();throw error;}
      this.requestedGraph=data;this.pending=Boolean(data.steps.length);this.layoutError=false;this.notify();
      if(!data.steps.length){this.graph=data;this.layout=null;this.selected=null;this.following=false;this.pathTrail=[];this.fitted=false;this.fitMode=true;this.world.replaceChildren();this.miniWorld.replaceChildren();this.mini.hidden=true;this.hint.textContent="Describe a step to start building the workflow.";this.notify();return true;}
      let positions;
      try{
        positions=await this.engine.layout(elkGraph(data,this.direction));
        if(!Number.isFinite(positions.width)||!Number.isFinite(positions.height))throw new Error("The workflow layout could not be calculated.");
      }catch(error){
        if(this.dead||revision!==this.version)return false;
        this.pending=false;this.layoutError=true;this.notify();throw error;
      }
      if(this.dead||revision!==this.version)return false;
      this.pending=false;this.layoutError=false;
      const previousGraph=this.graph,previousLayout=this.layout,previousSelected=this.selected;
      const focusedStep=this.doc.activeElement?.getAttribute?.("data-step-id");
      this.graph=data;this.layout=positions;this.selected=data.steps.some(step=>step.id===this.selected)?this.selected:null;
      // A correction may remove or reroute a path. Never retain an invalid trail.
      this.pathTrail=this.pathTrail.filter(id=>data.steps.some(step=>step.id===id));
      if(this.following&&!this.selected){this.following=false;this.pathTrail=[];}
      else if(this.following&&this.pathTrail.some((id,i)=>i&&!data.connections.some(edge=>edge.from===this.pathTrail[i-1]&&edge.to===id)))this.pathTrail=[this.selected];
      // Keep the same evidence-backed step under the camera when an upstream correction shifts layout.
      if(this.fitted&&!this.fitMode&&previousLayout){
        const anchorId=previousSelected||previousGraph?.steps.find(step=>data.steps.some(next=>next.id===step.id))?.id;
        const before=previousLayout.children.find(node=>node.id===anchorId),after=positions.children.find(node=>node.id===anchorId);
        if(before&&after){this.camera.x+=after.x-before.x;this.camera.y+=after.y-before.y;}
      }
      this.draw();
      if(focusedStep)[...this.world.querySelectorAll("[data-step-id]")].find(node=>node.getAttribute("data-step-id")===focusedStep)?.focus({preventScroll:true});
      if(!this.fitted)this.initialView();else if(this.fitMode)this.fit();else this.paintView();
      this.notify();
      return true;
    }
    initialView(){
      const {width,height}=this.size();if(!width||!height){this.fitMode=true;return;}
      const overviewScale=Math.min((width-48)/this.layout.width,(height-48)/this.layout.height);
      if(overviewScale>=.6){this.fit();return;}
      const scale=.8;
      const start=this.graph.steps.find(step=>!this.graph.incoming.get(step.id).length)||this.graph.steps[0],anchor=this.layout.children.find(node=>node.id===start.id);
      // Larger flows start on a complete readable first step, including on a phone.
      this.camera={x:width<500||this.direction==="DOWN"?anchor.x+anchor.width/2-width/scale/2:anchor.x-28/scale,y:anchor.y-28/scale,scale};this.fitMode=false;this.fitted=true;this.paintView();
    }
    fit(){
      if(!this.layout)return;const {width,height}=this.size();if(!width||!height)return;
      const scale=clamp(Math.min((width-40)/this.layout.width,(height-48)/this.layout.height),.05,1.35);
      this.camera={x:(this.layout.width-width/scale)/2,y:(this.layout.height-height/scale)/2,scale};this.fitMode=true;this.fitted=true;this.paintView();
    }
    refresh(){
      if(!this.layout)return;const size=this.size();if(!size.width||!size.height)return;
      if(!this.fitted){this.initialView();return;}
      if(this.fitMode){this.fit();return;}
      if(this.lastSize&&(this.lastSize.width!==size.width||this.lastSize.height!==size.height)){
        const center={x:this.camera.x+this.lastSize.width/this.camera.scale/2,y:this.camera.y+this.lastSize.height/this.camera.scale/2};
        this.camera.x=center.x-size.width/this.camera.scale/2;this.camera.y=center.y-size.height/this.camera.scale/2;
        const viewWidth=size.width/this.camera.scale,viewHeight=size.height/this.camera.scale,right=this.camera.x+viewWidth,bottom=this.camera.y+viewHeight;
        const fitting=this.layout.children.filter(n=>n.width<=viewWidth&&n.height<=viewHeight);
        const fullyVisible=fitting.some(n=>n.x>=this.camera.x&&n.x+n.width<=right&&n.y>=this.camera.y&&n.y+n.height<=bottom);
        const intersects=this.layout.children.some(n=>n.x+n.width>this.camera.x&&n.x<right&&n.y+n.height>this.camera.y&&n.y<bottom);
        if((fitting.length?!fullyVisible:!intersects)&&this.layout.children.length){
          const nearest=[...(fitting.length?fitting:this.layout.children)].sort((a,b)=>Math.hypot(a.x+a.width/2-center.x,a.y+a.height/2-center.y)-Math.hypot(b.x+b.width/2-center.x,b.y+b.height/2-center.y))[0];
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
      return {following:this.following,current:current?{id:current.id,title:current.title,type:current.type}:null,trail:[...this.pathTrail],
        next:current?(this.graph.outgoing.get(current.id)||[]).map(choice):[],
        previous:current?(this.graph.incoming.get(current.id)||[]).map(edge=>({...choice(edge),id:edge.from,label:edge.label||this.graph.steps.find(step=>step.id===edge.from)?.title||edge.from})):[]};
    }
    followPath(id=this.selected){
      if(!this.graph?.steps.length||!this.layout||this.pending||this.layoutError)return false;
      id=id||this.graph.steps.find(step=>!this.graph.incoming.get(step.id).length)?.id||this.graph.steps[0].id;
      if(!this.graph.steps.some(step=>step.id===id))return false;
      this.following=true;this.selected=id;this.pathTrail=[id];this.drawSelection();this.focusStep(id,{readable:true,keyboard:false});this.announcePath();return true;
    }
    leavePath(){this.following=false;this.pathTrail=[];this.drawSelection();this.status.textContent="All reported workflow routes are visible.";this.notify();}
    navigatePath(id,direction="auto"){
      if(!this.following||!this.graph||this.pending||this.layoutError)return false;
      const next=this.graph.outgoing.get(this.selected)||[],previous=this.graph.incoming.get(this.selected)||[];
      const forward=direction!=="previous"&&next.some(edge=>edge.to===id),backward=direction!=="next"&&previous.some(edge=>edge.from===id);
      if(!["auto","next","previous"].includes(direction)||(!forward&&!backward))return false;
      if(forward)this.pathTrail.push(id);
      else if(this.pathTrail.at(-2)===id)this.pathTrail.pop();
      else this.pathTrail=[id];
      this.selected=id;this.drawSelection();this.focusStep(id,{readable:true,keyboard:false});this.announcePath();return true;
    }
    announcePath(){const state=this.getPathNavigation();this.status.textContent=`${state.current?.title||"Workflow"}. ${state.next.length>1?`${state.next.length} reported branches. Choose the next route.`:state.next.length?"One reported next step.":"No reported next step."}`;}
    setDirection(direction){
      if(!["RIGHT","DOWN"].includes(direction))throw new Error("Choose a horizontal or vertical workflow layout.");
      if(this.layoutError&&!this.requestedGraph)return Promise.reject(new Error("The current workflow is invalid and cannot be laid out."));
      if(this.direction===direction)return Promise.resolve(false);
      this.direction=direction;this.fitted=false;this.fitMode=false;
      const current=this.requestedGraph||this.graph;
      return current?this.update({title:current.title,steps:current.steps,connections:current.connections}):Promise.resolve(false);
    }
    zoom(delta){this.zoomAt(clamp(this.camera.scale+delta,.05,2.5));}
    zoomAt(scale,clientPoint){
      if(!this.layout)return;const {width,height}=this.size(),rect=this.svg.getBoundingClientRect();
      const px=clientPoint?clientPoint.x-rect.left:width/2,py=clientPoint?clientPoint.y-rect.top:height/2;
      const worldX=this.camera.x+px/this.camera.scale,worldY=this.camera.y+py/this.camera.scale;
      this.camera={scale,x:worldX-px/scale,y:worldY-py/scale};this.fitMode=false;this.paintView();
    }
    paintView(){
      const {width,height}=this.size();if(!width||!height||!this.layout)return;
      this.lastSize={width,height};
      this.svg.setAttribute("viewBox",`${this.camera.x} ${this.camera.y} ${width/this.camera.scale} ${height/this.camera.scale}`);
      const showMini=width>=500&&height>=200;this.mini.style.display=showMini?"block":"none";this.hint.style.display=width>=420&&height>=180?"block":"none";
      const bounds={x:0,y:0,width:this.layout.width,height:this.layout.height};
      this.mini.setAttribute("viewBox",`${bounds.x-10} ${bounds.y-10} ${bounds.width+20} ${bounds.height+20}`);
      for(const [key,value] of Object.entries({x:this.camera.x,y:this.camera.y,width:width/this.camera.scale,height:height/this.camera.scale}))this.miniView.setAttribute(key,value);
      this.notify();
    }
    pointerDown(event){
      if(event.button!==undefined&&event.button!==0)return;
      if(event.target.closest?.("[data-step-id]"))return;
      this.svg.focus({preventScroll:true});event.preventDefault();this.svg.setPointerCapture?.(event.pointerId);
      this.pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});this.pointerMoved=false;this.svg.style.cursor="grabbing";
      if(this.pointers.size===2)this.pinch=this.pinchData();
    }
    pinchData(){const [a,b]=[...this.pointers.values()];return {distance:Math.hypot(b.x-a.x,b.y-a.y),center:{x:(a.x+b.x)/2,y:(a.y+b.y)/2}};}
    pointerMove(event){
      const previous=this.pointers.get(event.pointerId);if(!previous||!this.layout)return;
      const next={x:event.clientX,y:event.clientY};this.pointers.set(event.pointerId,next);this.fitMode=false;
      if(this.pointers.size===2){const pinch=this.pinchData();if(this.pinch?.distance)this.zoomAt(clamp(this.camera.scale*pinch.distance/this.pinch.distance,.05,2.5),pinch.center);this.pinch=pinch;}
      else{this.camera.x-=(next.x-previous.x)/this.camera.scale;this.camera.y-=(next.y-previous.y)/this.camera.scale;this.paintView();}
      this.pointerMoved=true;
    }
    pointerUp(event){this.pointers.delete(event.pointerId);this.pinch=null;this.svg.releasePointerCapture?.(event.pointerId);this.svg.style.cursor="grab";}
    wheel(event){
      if(!this.layout)return;event.preventDefault();
      if(event.ctrlKey||event.metaKey){this.zoomAt(clamp(this.camera.scale*Math.exp(-event.deltaY*.004),.05,2.5),{x:event.clientX,y:event.clientY});}
      else{this.camera.x+=event.deltaX/this.camera.scale;this.camera.y+=event.deltaY/this.camera.scale;this.fitMode=false;this.paintView();}
    }
    key(event){
      if(event.key==="Escape"&&this.following){event.preventDefault();this.leavePath();return;}
      if(event.key?.toLowerCase()==="f"){event.preventDefault();this.followPath(event.target.getAttribute?.("data-step-id")||this.selected);return;}
      if(event.target!==this.svg)return;
      const move={ArrowLeft:[-80,0],ArrowRight:[80,0],ArrowUp:[0,-80],ArrowDown:[0,80]}[event.key];
      if(move){event.preventDefault();this.camera.x+=move[0]/this.camera.scale;this.camera.y+=move[1]/this.camera.scale;this.fitMode=false;this.paintView();}
      if(event.key==="+"||event.key==="="){event.preventDefault();this.zoom(.15);}
      if(event.key==="-"){event.preventDefault();this.zoom(-.15);}
      if(event.key==="0"||event.key==="Home"){event.preventDefault();this.fit();}
    }
    navigateMini(event){
      if(!this.layout)return;event.preventDefault();const box=this.mini.getBoundingClientRect(),w=this.layout.width+20,h=this.layout.height+20,scale=Math.min(box.width/w,box.height/h),offsetX=(box.width-w*scale)/2,offsetY=(box.height-h*scale)/2;
      const x=(event.clientX-box.left-offsetX)/scale-10,y=(event.clientY-box.top-offsetY)/scale-10,{width,height}=this.size();this.camera.x=x-width/this.camera.scale/2;this.camera.y=y-height/this.camera.scale/2;this.fitMode=false;this.paintView();
    }
    select(step){this.selected=step.id;if(this.following){this.pathTrail=[step.id];this.focusStep(step.id,{readable:true,keyboard:false});this.announcePath();}this.drawSelection();this.options.onSelectStep?.({...step});this.notify();}
    drawSelection(){
      const related=new Set(this.following?[this.selected,...this.pathTrail]:[]),activeEdges=new Set();
      if(this.following)for(const edge of this.graph?.connections||[]){if(edge.from===this.selected||edge.to===this.selected||this.pathTrail.some((id,i)=>i&&id===edge.to&&this.pathTrail[i-1]===edge.from)){related.add(edge.from);related.add(edge.to);activeEdges.add(edge.id);}}
      this.world.querySelectorAll?.("[data-step-id]").forEach(node=>{const id=node.getAttribute("data-step-id"),active=id===this.selected;node.setAttribute("aria-pressed",String(active));node.setAttribute("opacity",this.following&&!related.has(id)?.28:1);const shape=node.querySelector(".workflow-node-shape");if(shape){shape.setAttribute("stroke-width",active?2.5:1.2);shape.setAttribute("stroke",active?"#dc6e2c":shape.getAttribute("data-base-stroke"));}});
      this.world.querySelectorAll?.("[data-edge-id]").forEach(node=>{node.setAttribute("opacity",this.following&&!activeEdges.has(node.getAttribute("data-edge-id"))?.22:1);});
      this.world.querySelectorAll?.("[data-edge-label-for]").forEach(node=>{node.setAttribute("opacity",this.following&&!activeEdges.has(node.getAttribute("data-edge-label-for"))?.22:1);});
      this.hint.textContent=this.following?"Following reported routes · Choose a branch to continue":"Drag to explore · Select a step for detail";
    }
    draw(){
      const doc=this.doc,layout=this.layout,data=this.graph;this.world.replaceChildren();this.miniWorld.replaceChildren();this.mini.hidden=false;
      this.hint.textContent="Drag to explore · Select a step for detail";
      this.title.textContent=`Workflow: ${data.title||"Current process"}`;
      this.description.textContent=`${data.steps.length} reported steps and ${data.connections.length} reported connections. ${data.steps.map(step=>`${step.id}: ${step.title}, ${step.actor||"owner not established"}`).join(". ")}`;
      const defs=svgNode(doc,"defs"),arrow=svgNode(doc,"marker",{id:`${this.uid}-arrow`,viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:6,markerHeight:6,orient:"auto-start-reverse"});arrow.append(svgNode(doc,"path",{class:"wf-arrow",d:"M 1 1 L 9 5 L 1 9 z",fill:"#9a9ca2"}));defs.append(arrow);this.world.append(defs);
      const edges=svgNode(doc,"g",{class:"workflow-edges"}),edgeLabels=svgNode(doc,"g");this.world.append(edges);
      layout.edges.forEach(edge=>{
        const original=data.connections.find(item=>item.id===edge.id);if(!original)return;
        const group=svgNode(doc,"g",{"data-edge-id":edge.id});group.append(svgNode(doc,"title",{},`${original.from} → ${original.to}${original.label?": "+original.label:""}. Sources: ${(original.evidence_turns||[]).join(", ")||"No source references in this view; open details to review evidence"}`));
        (edge.sections||[]).forEach(section=>{const p=points(section);group.append(svgNode(doc,"path",{class:"wf-edge",d:roundedPath(p),fill:"none",stroke:"#9a9ca2","stroke-width":1.5,"marker-end":`url(#${this.uid}-arrow)`}));this.miniWorld.append(svgNode(doc,"path",{class:"wf-mini-edge",d:roundedPath(p,0),fill:"none",stroke:"#dee0e4","stroke-width":3}));});edges.append(group);
        const labelGroup=svgNode(doc,"g",{"data-edge-label-for":edge.id});
        (edge.labels||[]).forEach(label=>{
          const x=label.x||0,y=label.y||0,words=wrap(original.label,19,3);labelGroup.append(svgNode(doc,"rect",{class:"wf-edge-label",x,y,width:label.width,height:label.height,rx:2,fill:"#ffffff",stroke:"#dee0e4","stroke-width":.8}));
          const text=svgNode(doc,"text",{class:"wf-edge-text",x:x+label.width/2,y:y+15,fill:"#646466","font-family":FONT,"font-size":11,"text-anchor":"middle"});words.forEach((line,i)=>text.append(svgNode(doc,"tspan",{x:x+label.width/2,dy:i?14:0},line)));labelGroup.append(text);
        });edgeLabels.append(labelGroup);
      });
      this.world.append(edgeLabels);
      layout.children.forEach(position=>{
        const step=data.steps.find(item=>item.id===position.id),{x,y,width:w,height:h}=position,decision=step.type==="decision",color=colorFor(step.actor);
        const group=svgNode(doc,"g",{"data-step-id":step.id,tabindex:"0",role:"button","aria-label":`${step.id}: ${step.title}. ${decision?"Decision":"Activity"}. ${step.actor||"Owner not established"}. Show details.`,"aria-pressed":"false"});styles(group,{cursor:"pointer",outline:"none"});
        group.append(svgNode(doc,"title",{},`${step.id}: ${step.title}\n${step.description||""}\nOwner: ${step.actor||"Not established"}\nSystem: ${step.system||"Not established"}`));
        const shape=decision?svgNode(doc,"path",{d:`M ${x+w/2} ${y} L ${x+w} ${y+h/2} L ${x+w/2} ${y+h} L ${x} ${y+h/2} Z`,fill:"#f4f2ef",stroke:"#c9c1b4"}):svgNode(doc,"rect",{x,y,width:w,height:h,rx:4,fill:"#fff",stroke:"#dee0e4"});
        shape.classList.add("workflow-node-shape");if(decision)shape.classList.add("is-decision");shape.setAttribute("data-base-stroke",decision?"#c9c1b4":"#dee0e4");shape.setAttribute("stroke-width",1.2);group.append(shape);
        const isolated=!data.incoming.get(step.id).length&&!data.outgoing.get(step.id).length;
        const boundary=isolated?"UNCONNECTED":!data.incoming.get(step.id).length?"FIRST REPORTED":!data.outgoing.get(step.id).length?"LAST REPORTED":"";
        const titleLines=wrap(step.title,decision?20:26,decision?3:2),centerX=x+w/2;
        if(!decision){group.append(svgNode(doc,"rect",{x:x+14,y:y+14,width:5,height:5,rx:2.5,fill:color}));}
        const headY=decision?y+35:y+19;
        group.append(svgNode(doc,"text",{class:decision?"wf-kind is-decision":"wf-kind",x:decision?centerX:x+26,y:headY,"text-anchor":decision?"middle":"start","font-family":FONT,"font-size":10,"font-weight":600,"letter-spacing":.5,fill:decision?"#7a6c56":"#646466"},`${step.id} · ${decision?"DECISION":boundary||"ACTIVITY"}`));
        const title=svgNode(doc,"text",{class:"wf-title",x:centerX,y:decision?y+61:y+45,"text-anchor":"middle","font-family":FONT,"font-size":15,"font-weight":600,fill:"#303033"});titleLines.forEach((line,i)=>title.append(svgNode(doc,"tspan",{x:centerX,dy:i?17:0},line)));group.append(title);
        const actor=short(step.actor||"Owner not established",decision?24:34),system=short(step.system||"System not established",decision?18:35);
        const actorY=decision?y+119:y+90;
        group.append(svgNode(doc,"text",{class:"wf-actor",x:centerX,y:actorY,"text-anchor":"middle","font-family":FONT,"font-size":11,"font-weight":600,fill:color},actor));
        group.append(svgNode(doc,"text",{class:"wf-system",x:centerX,y:actorY+14,"text-anchor":"middle","font-family":FONT,"font-size":11,fill:"#646466"},system));
        group.addEventListener("click",()=>this.select(step));
        group.addEventListener("keydown",event=>{
          if(event.key==="Enter"||event.key===" "){event.preventDefault();this.select(step);}
          const index=data.steps.findIndex(item=>item.id===step.id),direction=event.key==="ArrowRight"||event.key==="ArrowDown"?1:event.key==="ArrowLeft"||event.key==="ArrowUp"?-1:0;
          if(direction){event.preventDefault();const target=data.steps[(index+direction+data.steps.length)%data.steps.length];this.focusStep(target.id);}
        });
        group.addEventListener("focus",()=>{group.setAttribute("opacity",1);shape.setAttribute("stroke","#dc6e2c");shape.setAttribute("stroke-width",2.5);});
        group.addEventListener("blur",()=>this.drawSelection());
        this.world.append(group);
        this.miniWorld.append(svgNode(doc,"rect",{class:decision?"wf-mini-node is-decision":"wf-mini-node",x,y,width:w,height:h,rx:2,fill:decision?"#d8d0c4":"#c9ced6"}));
      });
      this.drawSelection();
    }
    focusStep(id,{readable=false,keyboard=true,select=false}={}){
      const node=this.layout?.children.find(item=>item.id===id);if(!node)return;
      const {width,height}=this.size();if(!width||!height)return;
      if(select){this.selected=id;if(this.following)this.pathTrail=[id];this.drawSelection();}
      if(readable)this.camera.scale=clamp(Math.max(this.camera.scale,.95),.05,Math.max(.3,Math.min((width-32)/node.width,(height-32)/node.height,1.35)));
      this.camera.x=node.x+node.width/2-width/this.camera.scale/2;this.camera.y=node.y+node.height/2-height/this.camera.scale/2;this.fitMode=false;this.paintView();
      if(keyboard)[...this.world.querySelectorAll("[data-step-id]")].find(item=>item.getAttribute("data-step-id")===id)?.focus({preventScroll:true});
    }
    exportSVG(){
      if(!this.layout||this.pending||this.layoutError||this.dead)return null;
      const svg=svgNode(this.doc,"svg",{xmlns:NS,viewBox:`0 0 ${this.layout.width} ${this.layout.height}`,width:this.layout.width,height:this.layout.height,role:"img"});
      svg.append(this.title.cloneNode(true),this.description.cloneNode(true),svgNode(this.doc,"rect",{width:this.layout.width,height:this.layout.height,fill:"#ffffff"}),this.world.cloneNode(true));
      svg.querySelectorAll?.("[tabindex]").forEach(node=>{node.removeAttribute("tabindex");node.removeAttribute("role");node.removeAttribute("aria-pressed");});
      // Focus is a navigation aid; an exported full workflow retains every route equally.
      svg.querySelectorAll?.("[opacity]").forEach(node=>node.removeAttribute("opacity"));
      return new scope.XMLSerializer().serializeToString(svg);
    }
    destroy(){
      this.dead=true;this.pending=false;this.version++;this.observer?.disconnect();try{this.engine.terminateWorker?.();}catch{/* ELK's in-process browser worker has no terminate method. */}this.listeners.forEach(([target,name,fn,options])=>target.removeEventListener(name,fn,options));this.listeners=[];this.container.replaceChildren();this.container.classList.remove("workflow-canvas");
    }
  }
  scope.CollectorWorkflow={create:(container,options)=>new Canvas(container,options),model,elkGraph,roundedPath};
})(typeof window!=="undefined"?window:globalThis);
