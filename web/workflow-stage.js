/* Dimensional, source-grounded workflow stage. All geometry is local and all process text is inserted as text. */
(function (scope) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const COPPER = "#dc6e2c", FELDSPAR = "#d28c79", BERMUDA = "#6c809a";
  const names = {
    activity: "Activity", start: "Start", end: "End", decision: "Decision",
    parallel_split: "Parallel split", parallel_join: "Join all", merge: "Merge",
    wait: "Wait", document: "Document", data_store: "Data store", subprocess: "Subprocess"
  };
  let serial = 0;

  function add(parent, tag, attrs, text) {
    const node = parent.ownerDocument.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    parent.append(node);
    return node;
  }
  const path = (parent, d, attrs = {}) => add(parent, "path", { d, ...attrs });
  const dots = points => points.map(p => p.map(n => Number(n.toFixed(2))).join(",")).join(" ");
  const line = (parent, d, color, width = 1, extra = {}) => path(parent, d, {
    fill: "none", stroke: color, "stroke-width": width, "stroke-linecap": "round", "stroke-linejoin": "round", ...extra
  });
  const projected = (x, z, height) => [(x - z) * .89, (x + z) * .42 - height];

  function resources(svg, prefix) {
    const defs = add(svg, "defs");
    const paint = key => "url(#" + prefix + "-" + key + ")";
    function gradient(name, radial, coords, stops) {
      const g = add(defs, radial ? "radialGradient" : "linearGradient", {id: prefix + "-" + name, ...coords});
      for (const [offset, color, opacity = 1] of stops) {
        add(g, "stop", {offset, "stop-color": color, "stop-opacity": opacity});
      }
    }
    gradient("wash", true, {}, [[0, "#8b7d66", .31], [.46, "#e2ded9", .12], [1, "#e2ded9", 0]]);
    gradient("warmwash", true, {}, [[0, "#d28c79", .3], [.48, "#dc6e2c", .1], [1, "#d28c79", 0]]);
    gradient("shadow", true, {}, [[0, "#383635", .96], [.57, "#383635", .68], [1, "#383635", 0]]);
    gradient("metal", false, {x1: "0", y1: "0", x2: ".86", y2: "1"}, [
      [0, "#bcb4a6"], [.14, "#8b7d66"], [.43, "#70695e"], [.78, "#474541"], [1, "#8b7d66"]
    ]);
    gradient("deck", false, {x1: ".05", y1: "0", x2: ".95", y2: "1"}, [
      [0, "#8b7d66"], [.12, "#5b564e"], [.42, "#474541"], [.72, "#474541"], [1, "#70695e"]
    ]);
    gradient("lens", false, {x1: "0", y1: "0", x2: ".9", y2: "1"}, [
      [0, "#f7f7f7", .93], [.3, "#bec6ce", .72], [.63, "#6c809a", .62], [1, "#404852", .78]
    ]);
    gradient("amberglass", false, {x1: "0", y1: "0", x2: ".95", y2: "1"}, [
      [0, "#f4e7df", .93], [.28, "#d28c79", .85], [.62, "#9e6d59", .75], [1, "#62534e", .82]
    ]);
    gradient("drum", false, {x1: "0", y1: "0", x2: "1", y2: "0"}, [
      [0, "#4d5966"], [.12, "#8797a7"], [.32, "#dee0e4"], [.52, "#8997a5"], [.79, "#606a76"], [1, "#45494e"]
    ]);
    gradient("lid", false, {x1: ".2", y1: "0", x2: ".8", y2: "1"}, [
      [0, "#dee0e4"], [.4, "#bfc4c9"], [.8, "#77869a"], [1, "#9caaba"]
    ]);
    return {defs, paint};
  }

  // Machined, chamfered plinths use a common projection so the signal always sits on the same surface.
  function slab(parent, width, depth, top, thickness, fill, trim) {
    const a = width / 2, b = depth / 2, c = Math.min(12, a / 3, b / 3);
    const outline = [[-a+c,-b],[a-c,-b],[a,-b+c],[a,b-c],[a-c,b],[-a+c,b],[-a,b-c],[-a,-b+c]];
    const upper = outline.map(([x,z])=>projected(x,z,top)), lower = outline.map(([x,z])=>projected(x,z,top-thickness));
    const faces = ["#474541","#5b564e","#474541","#70695e","#70695e","#70695e","#5b564e","#474541"];
    for (const i of [0,7,1,6,2,5,3,4]) {
      const next = (i+1)%8;
      add(parent, "polygon", {points: dots([upper[i],upper[next],lower[next],lower[i]]), fill: faces[i]});
    }
    add(parent, "polygon", {points: dots(upper), fill, stroke: trim || "#a39b8b", "stroke-width": .85, "stroke-linejoin":"round"});
    return upper;
  }

  function deck(parent, paint, accent) {
    add(parent, "ellipse", {cx: 0, cy: 12, rx: 142, ry: 54, fill: paint("shadow")});
    add(parent, "ellipse", {cx: 0, cy: 5, rx: 141, ry: 55, fill: paint(accent === FELDSPAR ? "warmwash":"wash"), opacity: .7});
    slab(parent, 124, 122, 4, 7, paint("deck"));
    slab(parent, 126, 124, 10, 4, "#474541", "#a39b8b");
    slab(parent, 124, 122, 15, 4, "#5b564e", "#bcb4a6");
    // A low luminous seam between the heat sink and the instrument deck.
    const rim = slab(parent, 126, 124, 20, 4, paint("metal"), "#bcb4a6");
    add(parent, "polyline", {points: dots(rim.slice(2,7)), fill:"none", stroke: accent, "stroke-width":2.3, opacity:.88});
    slab(parent, 122, 120, 25, 4, paint("deck"), "#bcb4a6");
    const inset = slab(parent, 101, 99, 25.8, 1.5, paint("deck"), "#8b7d66");
    add(parent, "polyline", {points: dots(inset.slice(0,4)), fill:"none", stroke:"#d4cdc1", "stroke-width":.7, opacity:.62});
    for (const [x,z] of [[-45,-45],[45,-45],[-45,45],[45,45]]) {
      const [cx,cy] = projected(x,z,26);
      add(parent,"ellipse",{cx,cy,rx:2.6,ry:1.2,fill:"#d4cdc1"});
      line(parent,"M"+(cx-1.2)+" "+(cy+.4)+"l2.4 -.8","#70695e",.6);
    }
    for(let i=-39;i<=39;i+=6){
      const [x,y]=projected(i,62,12);
      line(parent,"M"+x+" "+y+"v3.8","#303033",1.35);
    }
    add(parent,"ellipse",{cx:0,cy:-26,rx:67,ry:29,fill:paint(accent===FELDSPAR?"warmwash":"wash")});
  }

  function database(parent, paint) {
    for(const top of [-45,-64,-83]){
      const bottom=top+13;
      path(parent,`M-43 ${top}a43 17 0 0 1 86 0v13a43 17 0 0 1 -86 0z`,{fill:paint("drum"),stroke:"#bcb4a6","stroke-width":.6});
      line(parent,`M-42 ${bottom-3}a42 15 0 0 0 84 0`,COPPER,1.7,{opacity:.9});
      add(parent,"ellipse",{cx:0,cy:top,rx:43,ry:17,fill:paint("lid"),stroke:"#e2ded9","stroke-width":1});
      for(const x of [-23,-18,-13]) add(parent,"circle",{cx:x,cy:bottom+10+Math.abs(x)*-.09,r:1.05,fill:"#f7f7f7"});
    }
    add(parent,"ellipse",{cx:0,cy:-83,rx:31,ry:11.5,fill:"none",stroke:"#f7f7f7","stroke-width":.8,opacity:.85});
    add(parent,"ellipse",{cx:0,cy:-83,rx:20,ry:7.6,fill:"#70695e",stroke:COPPER,"stroke-width":1.1});
    line(parent,"M-8 -82l6 2.4 11 -4.6","#ffffff",1.4);
  }

  function gate(parent, paint, type) {
    const amber=type==="decision", accent=amber?FELDSPAR:COPPER, glass=paint(amber?"amberglass":"lens");
    slab(parent,52,41,32,5,paint("metal"));
    // A solid beveled outer rim surrounds the upright dichroic glass.
    path(parent,"M-48 -81l43 -49 11 -4 46 44 -43 56 -12 3z",{fill:"#5b564e",stroke:"#bcb4a6","stroke-width":1.2});
    path(parent,"M-48 -81l43 -49 46 44 -44 55z",{fill:glass,stroke:accent,"stroke-width":2});
    path(parent,"M-40 -81l36 -40 36 35 -35 44z",{fill:"#474541",stroke:accent,"stroke-width":1.2});
    path(parent,"M-35 -81l31 -34 30 30 -30 36z",{fill:glass,opacity:.46});
    line(parent,"M-48 -81l42 -47 12 -4","#ffe3cf",1.6);
    line(parent,"M41 -86l10 -4 -42 55 -12 4",accent,1,{opacity:.75});
    let glyph;
    if(type==="parallel_split") glyph="M-6 -64v-12l-12-11v-7m-4 6 4-6 4 5m8 13 14-12v-7m-4 6 4-6 4 5";
    else if(type==="parallel_join") glyph="M-19 -94v8l13 10 13-12v-8M-6 -76v13m-5-6 5 6 5-6";
    else if(type==="merge") glyph="m-18 -94 24 24m-1-26-23 27";
    else glyph="M-7 -65v-12l-10 -8v-8m10 16 14 -15m-6 1 6 -1 -1 6";
    line(parent,glyph,amber?"#fff5eb":"#ffffff",2.9);
  }

  function documentObject(parent, paint) {
    const sheet=add(parent,"g",{transform:"matrix(.93 .24 0 1 -26 -114)"});
    path(sheet,"M7 -3h44l16 16v63l-6 4 -54 -5z",{fill:"#5b564e",stroke:"#a39b8b","stroke-width":1});
    path(sheet,"M0 0h43l17 17v65H0z",{fill:paint("lens"),stroke:"#f7f7f7","stroke-width":1.5});
    path(sheet,"M43 0v17h17",{fill:"#8b7d66",stroke:COPPER,"stroke-width":1});
    path(sheet,"M8 22h17v10H8z",{fill:"#f7f7f7",opacity:.83});
    for(const [y,w] of [[41,41],[48,34],[55,39],[66,22]]) line(sheet,"M9 "+y+"h"+w,"#303033",1.5,{opacity:.9});
  }

  const colors = {
    activity: COPPER, start: "#798b9c", end: "#798b9c", data_store: BERMUDA, document: "#8b7d66",
    decision: FELDSPAR, wait: "#b97d53", merge: "#6c809a", parallel_split: "#968474",
    parallel_join: "#968474", subprocess: "#6c809a"
  };
  function instrument(parent, paint, type) {
    if (type === "data_store") return database(parent, paint);
    if (type === "document") return documentObject(parent, paint);
    if (["decision","parallel_split","parallel_join","merge"].includes(type)) return gate(parent, paint, type);
    const accent = colors[type] || COPPER;
    if (type === "wait") {
      slab(parent,46,39,36,9,paint("metal"));
      const clock = add(parent,"g",{transform:"translate(0 -77) skewY(-9)"});
      add(clock,"circle",{cx:5,cy:1,r:36,fill:paint("metal"),stroke:"#a39b8b"});
      add(clock,"circle",{cx:0,cy:0,r:35,fill:paint("amberglass"),stroke:accent,"stroke-width":2});
      add(clock,"circle",{cx:0,cy:0,r:27,fill:"#433e39",stroke:accent});
      for (let i=0;i<12;i++) line(clock,"M0 -23v3","#e2ded9",1.4,{transform:"rotate("+i*30+")"});
      line(clock,"M0 -17V0l13 8","#f7f7f7",3.5);
      return;
    }
    if (type === "start" || type === "end") {
      slab(parent,66,64,36,9,paint("metal"));
      const sign = add(parent,"g",{transform:"translate(0 -75) skewY(-12)"});
      add(sign,"circle",{cx:5,cy:1,r:32,fill:paint("metal"),stroke:"#a39b8b"});
      add(sign,"circle",{r:32,fill:paint("lens"),stroke:accent,"stroke-width":2});
      add(sign,"circle",{r:25,fill:"#474541",stroke:accent});
      if (type === "start") path(sign,"M-7 -13l22 13-22 13z",{fill:accent});
      else {
        add(sign,"circle",{r:20,fill:"none",stroke:accent,"stroke-width":1});
        line(sign,"m-12 0 8 8 17-18",accent,4);
      }
      return;
    }
    if (type === "subprocess") {
      for (const z of [30,48,66]) slab(parent,65,54,z,12,paint("metal"),accent);
      slab(parent,51,43,75,7,paint("lens"),accent);
      return;
    }
    slab(parent,76,65,36,9,paint("metal"));
    slab(parent,66,58,44,7,paint("deck"),"#d4cdc1");
    slab(parent,54,49,78,33,paint("lens"),COPPER);
    const cap=add(parent,"g",{transform:"translate(0 -78)"});
    add(cap,"ellipse",{rx:19,ry:8,fill:"#5b564e",stroke:COPPER,"stroke-width":1.6});
    line(cap,"M-10 0l7 -3 5 3 8 -4","#ffffff",2.4);
  }

  // The map, inspector and library thumbnails all reference the same local symbol bank.
  // Build each registered instrument only on its first use in this document.
  const banks = new WeakMap();
  function assetBank(doc) {
    if (banks.has(doc)) return banks.get(doc);
    const prefix = "gpfs-art-" + (++serial), ids = new Set();
    const bank = add(doc.body,"svg",{width:0,height:0,"aria-hidden":"true",focusable:"false",class:"ws-instruments"});
    const {defs,paint} = resources(bank,prefix);
    function ensure(key,draw) {
      const id=prefix+"-"+key;
      if (!ids.has(id)) {
        const part=add(defs,"g",{id});
        draw(part);
        ids.add(id);
      }
      return "#"+id;
    }
    function ref(type,variant) {
      const motif = variant?.id;
      const modeled = Boolean(motif && ["activity","document","data_store","subprocess"].includes(type) && scope.CollectorComponentArt?.has(motif));
      return ensure("part-"+type+(modeled?"-"+motif:""),part=>{
        const base = ensure("base-"+type,p=>deck(p,paint,colors[type]));
        add(part,"use",{href:base});
        if (modeled) {
          const object = ensure("motif-"+motif,p=>scope.CollectorComponentArt.draw(p,motif));
          if(type==="subprocess") {
            slab(part,76,67,34,5,paint("metal"),colors[type]);
            slab(part,74,65,40,4,paint("deck"),colors[type]);
          }
          let raised=type==="subprocess"?12:0;
          if(type==="data_store") {
            for(const y of [-32,-41]){
              path(part,`M-55 ${y}a55 20 0 0 1 110 0v6a55 20 0 0 1 -110 0z`,{fill:paint("drum"),stroke:BERMUDA});
              add(part,"ellipse",{cx:0,cy:y,rx:55,ry:20,fill:paint("lid"),stroke:"#e2ded9"});
            }
            raised=13;
          } else if(type==="document") {
            for(const y of [-35,-40]) {
              path(part,`M-65 ${y}l60-18 62 21-52 24q-10-7-20-6z`,{fill:"#e2ded9",stroke:"#8b7d66","stroke-width":1.4});
              line(part,`M36 ${y+10}l4-7 17 0`,"#8b7d66",1.3);
            }
            raised=10;
          }
          add(part,"use",{href:object,transform:"translate(0 "+(-raised)+")"});
        } else instrument(part,paint,type);
      });
    }
    const api={ref};
    banks.set(doc,api);
    return api;
  }

  function makeArrow(svg,prefix) {
    const defs=add(svg,"defs");
    const marker = add(defs,"marker", {id:prefix+"-arrow", viewBox:"0 0 10 10", refX:9, refY:5,
      markerWidth:7, markerHeight:7, orient:"auto", markerUnits:"userSpaceOnUse"});
    path(marker, "M0 0 10 5 0 10 2.5 5Z", {fill:"context-stroke"});
  }

  function drawStep(layer, node, designId) {
    const {step, width, height} = node, type = Object.hasOwn(names, step.type) ? step.type : "activity";
    const variant = scope.CollectorComponents?.forDisplay(step,designId) || null;
    const typeLabel = scope.CollectorWorkflow?.types?.[type]?.label || names[type];
    const caption=[step.id,step.title,typeLabel,variant?.label,step.actor].filter(Boolean);
    const g = add(layer, "g", {class:"ws-node", "data-step-id":node.id, "data-step-type":type, tabindex:0,
      role:"button", "aria-label":caption.join(". "),
      "aria-pressed":"false",transform:"translate("+node.x+" "+node.y+")"});
    if(variant)g.setAttribute("data-component-id",variant.id);
    g.style.setProperty("--ws-color", colors[type]);
    add(g,"title",{},caption.join(" · "));
    // The ports sit on the measured envelope. The icon and caption together occupy one pick target.
    const lid = "M9 0H" + (width-9) + "L" + width + " 9V" + (height-9) + "L" + (width-9) +
      " " + height + "H9L0 " + (height-9) + "V9Z";
    path(g,lid,{class:"ws-tile-rim",transform:"translate(0 2.4)"});
    path(g,lid,{class:"ws-tile"});
    path(g,"M11 0H"+Math.min(width-12,35),{class:"ws-tile-index"});
    // The <use> instance shares the prebuilt component mesh for every node of its type.
    const use = add(g,"use",{href:assetBank(layer.ownerDocument).ref(type,variant),transform:"translate("+width/2+" 44) scale(.32)","aria-hidden":"true"});
    use.setAttribute("pointer-events","none");
    const label=add(g,"text",{x:width/2,y:76,class:"ws-node-name","text-anchor":"middle"});
    node.titleLines.forEach((word,i)=>add(label,"tspan",{x:width/2,dy:i?16:0},word));
    return g;
  }

  function createComponentPreview(host, {type="activity",variant=null}={}) {
    if (!Object.hasOwn(names,type)) type="activity";
    if (typeof variant==="string") variant=scope.CollectorComponents?.all?.find(item=>item.id===variant) || null;
    const svg=host.ownerDocument.createElementNS(NS,"svg");
    svg.setAttribute("class","ws-component-preview");
    svg.setAttribute("viewBox","-133 -144 266 213");
    svg.setAttribute("role","img"); svg.setAttribute("focusable","false");
    svg.setAttribute("aria-label",variant?.label || names[type]);
    const detail=scope.CollectorComponentArt?.detail(variant?.id);
    if(detail)add(svg,"desc",{},detail);
    add(svg,"use",{href:assetBank(host.ownerDocument).ref(type,variant)});
    host.replaceChildren(svg);
    return svg;
  }

  function drawRoute(layer, edge, index, prefix, decision) {
    const source = edge.edge;
    const name = [source.from+" → "+source.to, source.label].filter(Boolean).join(" · ");
    const g = add(layer,"g",{class:"ws-edge","data-edge-key":edge.key,tabindex:0,role:"button",
      "aria-label":"Connection "+name,"aria-pressed":"false"});
    g.style.setProperty("--ws-route-color", decision ? "#955132" : "#576b80");
    g.style.setProperty("--ws-delay", (-index * .61 % 4.6) + "s");
    add(g,"title",{},name);
    for (const section of edge.paths) {
      path(g,section.d,{class:"ws-road-bed"});
      path(g,section.d,{class:"ws-road","marker-end":"url(#"+prefix+"-arrow)"});
      path(g,section.d,{class:"ws-signal",pathLength:100,"aria-hidden":"true"});
      path(g,section.d,{class:"ws-edge-hit"});
    }
    for (const label of edge.labels) {
      const box=add(g,"g",{class:"ws-route-label"});
      add(box,"rect",{x:label.x,y:label.y,width:label.width,height:label.height,rx:4});
      const x = label.x + label.width/2, y = label.y + label.height/2 + 4 - (label.lines.length-1)*7;
      const text=add(box,"text",{x,y,"text-anchor":"middle"});
      label.lines.forEach((word,i)=>add(text,"tspan",{x,dy:i?14:0},word));
    }
    return g;
  }

  function routeBounds(route) {
    if (route.labels.length) return route.labels[0];
    const points = route.paths.flatMap(section => section.points);
    if (!points.length) return null;
    const xs = points.map(p=>p.x), ys = points.map(p=>p.y);
    return {x:Math.min(...xs),y:Math.min(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};
  }

  function create(host, options = {}) {
    const doc = host.ownerDocument, win = doc.defaultView || scope;
    const id = "cinematic-" + (++serial);
    host.classList.add("workflow-stage");
    host.replaceChildren();
    const svg = add(host,"svg",{class:"ws-scene",role:"group",tabindex:0,
      "aria-label":"Cinematic workflow map. Select any component or connection. Drag to pan. Use plus or minus to zoom and Home to fit the whole process."});
    makeArrow(svg,id);
    const world = add(svg,"g",{class:"ws-world"});
    const pointers = new Map(), listeners = [];
    const motionQuery = win.matchMedia?.("(prefers-reduced-motion: reduce)");
    let visible = true, moving = true, dead = false, version = 0, layout = null;
    let nodes = new Map(), routes = new Map(), nodeElements = new Map(), routeElements = new Map();
    let current = {}, fitted = true, moved = false, origin, camera = {x:0,y:0,scale:1};

    function listen(target,name,cb,options) {
      target.addEventListener(name,cb,options);
      listeners.push(()=>target.removeEventListener(name,cb,options));
    }
    function size() {
      const rect=svg.getBoundingClientRect();
      return {width:rect.width,height:rect.height,left:rect.left,top:rect.top};
    }
    function overviewScale(view) {
      if (!layout || !view.width || !view.height) return 1;
      const margin = view.width < 480 ? 10 : 16;
      return Math.max(.00001,Math.min(1.8,(view.width-margin*2)/Math.max(1,layout.width),(view.height-margin*2)/Math.max(1,layout.height)));
    }
    function paintCamera() {
      const view=size();
      if (!view.width || !view.height || !layout) return;
      const w=view.width/camera.scale, h=view.height/camera.scale;
      svg.setAttribute("viewBox",[camera.x-w/2,camera.y-h/2,w,h].join(" "));
      options.onViewChange?.({scale:camera.scale});
    }
    function fit() {
      fitted=true;
      if (!layout) return;
      camera={x:layout.width/2,y:layout.height/2,scale:overviewScale(size())};
      paintCamera();
    }
    function zoom(factor, at, before=at) {
      const view=size();
      if (!layout || !view.width || !view.height || !Number.isFinite(factor) || factor<=0) return;
      const oldScale=camera.scale;
      const scale=Math.max(overviewScale(view)*.65,Math.min(3.5,oldScale*factor));
      if (at) {
        const mid={x:view.left+view.width/2,y:view.top+view.height/2};
        camera.x+=(before.x-mid.x)/oldScale-(at.x-mid.x)/scale;
        camera.y+=(before.y-mid.y)/oldScale-(at.y-mid.y)/scale;
      }
      camera.scale=scale;
      fitted=false;
      paintCamera();
    }
    function focusBox(box) {
      const view=size();
      if (!box || !view.width || !view.height) return;
      const readable=Math.min(1.35,(view.width-28)/Math.max(box.width,28),(view.height-28)/Math.max(box.height,28));
      camera={x:box.x+box.width/2,y:box.y+box.height/2,scale:Math.max(overviewScale(view),Math.min(3.5,readable))};
      fitted=false;
      paintCamera();
    }
    function mark(element,state) {
      element.setAttribute("aria-pressed",String(state==="selected"));
      if (state) element.setAttribute("data-emphasis",state);
      else element.removeAttribute("data-emphasis");
    }
    function select(value={}, {focus=false}={}) {
      current = value || {};
      const step = nodes.get(current.stepId), route = routes.get(current.edgeKey);
      const related = new Set();
      for (const [key,el] of routeElements) {
        const edge=routes.get(key).edge;
        const incident=Boolean(step && (edge.from===step.id || edge.to===step.id));
        if (incident) { related.add(edge.from); related.add(edge.to); }
        mark(el,route?.key===key?"selected":incident?"related":"");
      }
      if(route){related.add(route.edge.from);related.add(route.edge.to);}
      for (const [key,el] of nodeElements) mark(el,step?.id===key?"selected":related.has(key)?"related":"");
      if (focus) focusBox(step || (route && routeBounds(route)));
    }
    function readTarget(target) {
      const node=target?.closest?.("[data-step-id]");
      if(node) return {stepId:node.getAttribute("data-step-id")};
      const route=target?.closest?.("[data-edge-key]");
      return route ? {edgeKey:route.getAttribute("data-edge-key")} : null;
    }
    function activate(target) {
      if(!target) return;
      select(target);
      if (target.stepId) options.onSelectStep?.(target.stepId);
      else options.onSelectEdge?.(target.edgeKey);
    }
    function refreshMotion() {
      host.classList.toggle("ws-moving",moving && visible && !doc.hidden && !motionQuery?.matches);
    }
    function setVisible(value) {
      visible=Boolean(value);
      refreshMotion();
      if(visible && fitted)fit();
    }
    function setMotion(value) {moving=Boolean(value); refreshMotion();}
    async function update(graph) {
      const revision=++version;
      if(dead)return false;
      const hasSteps=Boolean(graph?.steps?.length);
      svg.setAttribute("aria-busy",String(hasSteps));
      let next;
      try {
        next=hasSteps ? await scope.CollectorWorkflow.cinematicLayout(graph) : null;
      } catch(error) {
        if(dead || version!==revision)return false;
        layout=null; nodes.clear(); routes.clear(); nodeElements.clear(); routeElements.clear(); world.replaceChildren();
        svg.setAttribute("aria-busy","false");
        throw error;
      }
      if(dead || version!==revision)return false;
      const focused=svg.contains(doc.activeElement) ? readTarget(doc.activeElement) : null;
      const anchor=nodes.get(current.stepId);
      layout=next;
      nodes=new Map((layout?.nodes||[]).map(n=>[n.id,n]));
      routes=new Map((layout?.edges||[]).map(e=>[e.key,e]));
      nodeElements=new Map(); routeElements=new Map();
      world.replaceChildren();
      svg.setAttribute("aria-busy","false");
      if(!layout){current={}; fitted=true;return true;}
      const edgeLayer=add(world,"g",{class:"ws-routes"}), parts=add(world,"g",{class:"ws-components"});
      layout.edges.forEach((edge,index)=>routeElements.set(edge.key, drawRoute(edgeLayer,edge,index,id,nodes.get(edge.edge.from)?.step.type==="decision")));
      for (const node of layout.nodes) nodeElements.set(node.id,drawStep(parts,node,graph.component_designs?.[node.id]));
      if(!nodes.has(current.stepId) && !routes.has(current.edgeKey))current={};
      select(current);
      const replacement=nodes.get(current.stepId);
      if(!fitted && replacement && anchor){
        camera.x+=replacement.x+replacement.width/2-anchor.x-anchor.width/2;
        camera.y+=replacement.y+replacement.height/2-anchor.y-anchor.height/2;
      }
      if(fitted)fit(); else paintCamera();
      if(focused){
        const restored=nodeElements.get(focused.stepId)||routeElements.get(focused.edgeKey);
        (restored||svg).focus({preventScroll:true});
      }
      return true;
    }

    function keydown(event) {
      const key=event.key, target=readTarget(event.target);
      if ((key==="Enter" || key===" ") && target) activate(target);
      else if(key==="+" || key==="=")zoom(1.35);
      else if(key==="-")zoom(1/1.35);
      else if(key==="Home" || key==="0")fit();
      else if(key.startsWith("Arrow") && layout){
        const delta=55/camera.scale;
        if(key==="ArrowRight")camera.x+=delta;
        if(key==="ArrowLeft")camera.x-=delta;
        if(key==="ArrowUp")camera.y-=delta;
        if(key==="ArrowDown")camera.y+=delta;
        fitted=false;paintCamera();
      } else return;
      event.preventDefault();
    }
    function point(event){return {x:event.clientX,y:event.clientY};}
    function center(a,b){return {x:(a.x+b.x)/2,y:(a.y+b.y)/2};}
    function distance(a,b){return Math.hypot(a.x-b.x,a.y-b.y);}
    listen(svg,"pointerdown",event=>{
      if(event.button!==0 || !layout)return;
      if(!pointers.size){moved=false;origin=point(event);}
      else moved=true;
      pointers.set(event.pointerId,point(event));
    });
    listen(svg,"pointermove",event=>{
      const prev=pointers.get(event.pointerId);
      if(!prev || !layout)return;
      const at=point(event);
      if(!moved && distance(at,origin)<5)return;
      moved=true;
      svg.classList.add("ws-dragging");
      svg.setPointerCapture?.(event.pointerId);
      pointers.set(event.pointerId,at);
      const other=[...pointers].find(([pointerId])=>pointerId!==event.pointerId)?.[1];
      if(other)zoom(distance(at,other)/Math.max(.1,distance(prev,other)),center(at,other),center(prev,other));
      else {
        camera.x-=(at.x-prev.x)/camera.scale;
        camera.y-=(at.y-prev.y)/camera.scale;
        fitted=false;paintCamera();
      }
    });
    function pointerEnd(event) {
      pointers.delete(event.pointerId);
      if(svg.hasPointerCapture?.(event.pointerId))svg.releasePointerCapture(event.pointerId);
      if(!pointers.size)svg.classList.remove("ws-dragging");
    }
    listen(svg,"pointerup",pointerEnd);
    listen(svg,"pointercancel",pointerEnd);
    listen(svg,"pointerleave",event=>{if(!svg.hasPointerCapture?.(event.pointerId))pointerEnd(event);});
    listen(svg,"click",event=>{if(!moved || event.detail===0)activate(readTarget(event.target));});
    listen(svg,"dblclick",event=>{
      const target=readTarget(event.target);
      if(target){event.preventDefault();select(target,{focus:true});}
    });
    listen(svg,"wheel",event=>{
      if(!layout)return;
      event.preventDefault();
      const delta=event.deltaY*(event.deltaMode===1?16:1);
      zoom(Math.exp(-Math.max(-120,Math.min(120,delta))*.007),point(event));
    },{passive:false});
    listen(svg,"keydown",keydown);
    listen(svg,"focusin",event=>{
      if(!layout || fitted)return;
      const target=readTarget(event.target), view=size();
      const node=nodes.get(target?.stepId), route=routes.get(target?.edgeKey);
      const box=node || (route && routeBounds(route));
      if(!box)return;
      const x=box.x+box.width/2,y=box.y+box.height/2;
      if(Math.abs(x-camera.x)*camera.scale>view.width*.48 || Math.abs(y-camera.y)*camera.scale>view.height*.46){
        camera.x=x;camera.y=y;paintCamera();
      }
    });
    listen(doc,"visibilitychange",refreshMotion);
    if(motionQuery)listen(motionQuery,"change",refreshMotion);
    const observer=win.ResizeObserver ? new win.ResizeObserver(()=>{if(fitted)fit();else paintCamera();}) : null;
    observer?.observe(host);
    refreshMotion();
    return {update,select,zoom,fit,setVisible,setMotion,destroy(){
      dead=true;version++;observer?.disconnect();listeners.forEach(remove=>remove());pointers.clear();
      host.classList.remove("workflow-stage","ws-moving");host.replaceChildren();
    }};
  }
  scope.CollectorWorkflowStage={create,createComponentPreview};
})(typeof window==="object" ? window : globalThis);
