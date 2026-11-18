/* Cinematic map controls use the working or reviewed graph already in memory. */
"use strict";
(function (scope) {
  const paths = {
    expand:"M4 9V4h5m6 0h5v5m0 6v5h-5M9 20H4v-5", close:"m6 6 12 12M18 6 6 18",
    fit:"M4 8V4h4m8 0h4v4m0 8v4h-4M8 20H4v-4 M8 8h8v8H8z",
    plus:"M5 12h14M12 5v14", minus:"M5 12h14", motion:"M2 13h4l3-7 5 13 3-8h5",
    map:"M3 4h6v5H3z M15 15h6v5h-6z M6 9v8h9 M9 6h9v9",
    details:"M5 4h14v16H5z M8 8h8m-8 4h8m-8 4h5",
    library:"M3 5h5v14H3z M9 5h4v14H9z M14 6l4-1 4 13-4 1z"
  };
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  function glyph(name) {
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns,"svg");
    const path = document.createElementNS(ns,"path");
    svg.setAttribute("viewBox","0 0 24 24"); svg.setAttribute("aria-hidden","true");
    path.setAttribute("d",paths[name]); path.setAttribute("fill","none");
    path.setAttribute("stroke","currentColor"); path.setAttribute("stroke-width","1.6");
    path.setAttribute("stroke-linecap","round"); path.setAttribute("stroke-linejoin","round");
    svg.append(path); return svg;
  }
  function control(name, icon, action, showText = false) {
    const button = el("button","ww-control");
    button.type = "button"; button.title = name;
    button.setAttribute("aria-label",name); button.append(glyph(icon));
    if (showText) button.append(el("span","",name));
    button.addEventListener("click",action);
    return button;
  }
  const edgeKey = edge => JSON.stringify([edge.from,edge.to,edge.label || ""]);
  const count = (n,noun) => n + " " + noun + (n === 1 ? "" : "s");
  const typeLabel = step => scope.CollectorWorkflow?.types?.[step.type]?.label || "Activity";

  function create(root, {onDetails,onExit,renderEvidence,onSetDesign,sourceCaption}) {
    const media = scope.matchMedia("(prefers-reduced-motion: reduce)");
    let motionEnabled = true, visible = false, destroyed = false, generation = 0;
    let fingerprint, graph = {steps:[],connections:[]}, selected = {}, steps = new Map(), edges = new Map(), options = [];
    const shell = el("section","ww-shell"), theater = el("dialog","ww-theater");
    shell.setAttribute("aria-label","Cinematic process map"); theater.setAttribute("aria-label","Expanded cinematic map");
    const header = el("header","ww-head"), identity = el("div","ww-identity"), heading = el("div");
    const processName = el("h3","ww-process-name"), counts = el("p","ww-counts");
    processName.tabIndex = -1;
    heading.append(processName,counts); identity.append(glyph("map"),heading);
    const tools = el("div","ww-tools"), zoomLabel = el("span","ww-zoom","100%");
    zoomLabel.setAttribute("aria-label","Map zoom");
    const zoomOut = control("Zoom out of cinematic map","minus",() => stage.zoom(1/1.3));
    const zoomIn = control("Zoom in on cinematic map","plus",() => stage.zoom(1.3));
    const fit = control("Fit map","fit",() => { select({}); stage.fit(); },true);
    const motion = control("Flow motion","motion",() => { motionEnabled = !motionEnabled; syncMotion(); },true);
    const expand = control("Expand cinematic map","expand",toggleTheater);
    const library = control("Component library","library",() => scope.CollectorComponentLibrary.open({opener:library}),true);
    tools.append(zoomOut,zoomLabel,zoomIn,fit,motion,library,expand); header.append(identity,tools);
    const navigation = el("div","ww-navigation"), picker = el("select","ww-picker");
    picker.setAttribute("aria-label","Find a component or connection");
    navigation.append(picker);
    const workspace = el("div","ww-workspace"), scene = el("div","ww-scene"), inspector = el("section","ww-inspector");
    inspector.hidden = true; inspector.setAttribute("aria-label","Selection details"); workspace.append(scene,inspector);
    const message = el("div","ww-message"), announcement = el("span","ww-sr");
    message.setAttribute("role","status"); announcement.setAttribute("role","status");
    shell.append(header,navigation,message,workspace,announcement); root.replaceChildren(shell,theater);
    const stage = scope.CollectorWorkflowStage.create(scene,{
      onSelectStep: id => select(id ? {stepId:id} : {}),
      onSelectEdge: key => select(key ? {edgeKey:key} : {},Boolean(key)),
      onInspect: () => inspector.querySelector("h4")?.focus({preventScroll:true}),
      onViewChange: view => { zoomLabel.textContent = Math.round(view.scale * 100) + "%"; }
    });
    picker.addEventListener("change",() => {
      const item = options[Number(picker.value)] || {};
      select(item,true);
      if (!item.stepId && !item.edgeKey) stage.fit();
      else inspector.querySelector("h4")?.focus({preventScroll:true});
    });
    shell.addEventListener("keydown",event=>{
      if(event.key!=="Escape" || inspector.hidden)return;
      event.preventDefault(); event.stopPropagation();
      select({}); picker.focus({preventScroll:true});
    });
    media.addEventListener("change",motionPreference);
    theater.addEventListener("close",leaveTheater);
    function toggleTheater() {
      if (theater.open) { theater.close(); return; }
      theater.append(shell); theater.showModal(); expand.title = "Close expanded map";
      expand.setAttribute("aria-label",expand.title); expand.replaceChildren(glyph("close")); expand.focus({preventScroll:true});
    }
    function leaveTheater() {
      root.insertBefore(shell,theater); expand.title = "Expand cinematic map";
      expand.setAttribute("aria-label",expand.title); expand.replaceChildren(glyph("expand"));
      expand.hidden = !steps.size;
      if (visible && !expand.hidden) expand.focus({preventScroll:true});
    }
    function syncMotion() {
      const large=graph.connections.length>24;
      const active = motionEnabled && !media.matches && !large;
      motion.disabled = large || media.matches || !graph.connections.length;
      motion.setAttribute("aria-pressed",String(active));
      motion.title = large ? "Motion is paused on larger maps for readability" : media.matches ? "Reduced motion is enabled on this device" : "Animate direction along captured connections";
      stage.setMotion(active);
    }
    function motionPreference() { syncMotion(); }
    function rebuildPicker() {
      const overview = el("option","","Whole process");
      options = [{}]; overview.value = "0"; picker.replaceChildren(overview);
      function group(label, entries) {
        if (!entries.length) return;
        const container = el("optgroup"); container.label = label;
        for (const [text,selection] of entries) {
          const option = el("option","",text);
          option.value = String(options.length); options.push(selection); container.append(option);
        }
        picker.append(container);
      }
      group("Components",graph.steps.map(step => [step.id + " · " + (step.title || typeLabel(step)),{stepId:step.id}]));
      group("Connections",graph.connections.map(edge => [edge.from + " → " + edge.to + (edge.label ? " · " + edge.label : ""),{edgeKey:edgeKey(edge)}]));
    }
    function link(label, selection, endpoint) {
      const button = el("button","ww-link",label); button.type = "button";
      button.dataset.focusKey = JSON.stringify([endpoint,selection.stepId || selection.edgeKey]);
      button.addEventListener("click",() => { select(selection,true); inspector.querySelector("h4")?.focus({preventScroll:true}); });
      return button;
    }
    function routeList(heading, connections, incoming) {
      if (!connections.length) return;
      const list = el("ul","ww-routes"); inspector.append(el("h5","ww-label",heading),list);
      for (const edge of connections) {
        const id = incoming ? edge.from : edge.to, row = el("li");
        row.append(link((edge.label ? edge.label + " · " : "") + (steps.get(id)?.title || id),{edgeKey:edgeKey(edge)},incoming?"to":"from"));
        list.append(row);
      }
    }
    function paintInspector() {
      const step = steps.get(selected.stepId), edge = edges.get(selected.edgeKey);
      inspector.hidden = !(step || edge); workspace.classList.toggle("ww-inspecting",!inspector.hidden);
      inspector.replaceChildren();
      if (inspector.hidden) return;
      const top = el("div","ww-inspector-top"), close = control("Close selection","close",() => { select({}); picker.focus(); });
      top.append(el("span","ww-label",step ? step.id + " / " + typeLabel(step) : edge.from + " → " + edge.to),close);
      const title = el("h4","ww-title",step ? step.title || step.id : edge.label || "Connection");
      title.tabIndex = -1; inspector.append(top,title);
      if (step) {
        if (scope.CollectorWorkflowStage.createComponentPreview && scope.CollectorComponents) {
          const appliedDesign = graph.component_designs?.[step.id];
          const variant = scope.CollectorComponents.forDisplay(step,appliedDesign);
          const art = el("div","ww-art-study");
          art.setAttribute("aria-hidden","true");
          scope.CollectorWorkflowStage.createComponentPreview(art,{type:step.type,variant});
          const editable = onSetDesign && ["activity","document","data_store","subprocess"].includes(step.type || "activity");
          const design = el("button","ww-design-link",(variant?.label || typeLabel(step)) + (editable ? " · Change design" : ""));
          design.type = "button"; design.disabled = !scope.CollectorComponentLibrary?.open;
          design.title = editable ? "Choose a design for this step" : "View this design in the component library";
          design.addEventListener("click",()=>scope.CollectorComponentLibrary.open({
            variant,appliedDesign,type:step.type,opener:design,returnFocus:picker,stepTitle:step.title,
            onApply:editable ? id=>onSetDesign(step.id,id) : undefined
          }));
          inspector.append(art,design);
        }
        if (step.description) inspector.append(el("p","ww-description",step.description));
        const known = scope.CollectorWorkflow?.known || (value=>Boolean(value));
        const fields = el("dl","ww-fields");
        for (const [name,value] of [["Owner",step.actor],["System",step.system]]) {
          if (known(value)) fields.append(el("dt","",name),el("dd","",value));
        }
        if (fields.childElementCount) inspector.append(fields);

        const controls = Array.isArray(step.control_type) ? step.control_type.filter(value=>value!=="none_reported")
          .map(value=>value.replace(/^gpfs_/,"GPFS ").replaceAll("_"," ")).join(", ") : "";
        const recorded = [["Input",step.input],["Output",step.output],["Completion",step.completion_criteria],
          ["Handoff note",step.handoff],["Control",controls],["Entry method",step.entry_mode?.replaceAll("_"," ")],
          ["Data source",step.data_origin],["Rule source",step.rule_source_ref&&sourceCaption?sourceCaption(step.rule_source_ref):step.rule_source_ref]].filter(([,value])=>known(value));
        if (recorded.length || step.operating_details?.length) {
          const more=el("details","ww-operating"), dl=el("dl","ww-fields");
          more.append(el("summary","","Operating details"),dl);
          for(const [label,value] of recorded) dl.append(el("dt","",label),el("dd","",value));
          for(const row of step.operating_details||[]){
            const fact=el("dd","",row.text);
            if(renderEvidence)fact.append(renderEvidence(row.evidence_turns));
            dl.append(el("dt","",row.field[0].toUpperCase()+row.field.slice(1)),fact);
          }
          inspector.append(more);
        }
        inspector.append(control("Step details and sources","details",() => onDetails(step.id),true));
        const incoming=graph.connections.filter(e=>e.to===step.id),outgoing=graph.connections.filter(e=>e.from===step.id);
        routeList("Incoming connections",incoming,true);
        routeList(step.type === "parallel_split" ? "Parallel branches" : "Outgoing connections",outgoing,false);
        if(!incoming.length&&!outgoing.length)inspector.append(el("p","ww-description","No connections have been recorded for this step."));
      } else {
        for (const [label,id] of [["From",edge.from],["To",edge.to]]) {
          inspector.append(el("h5","ww-label",label),link(steps.get(id)?.title || id,{stepId:id},label));
        }
        if (renderEvidence) inspector.append(renderEvidence(edge.evidence_turns || []));
      }
    }
    function select(value, focus = false) {
      selected = value.stepId && steps.has(value.stepId) ? {stepId:value.stepId} :
        value.edgeKey && edges.has(value.edgeKey) ? {edgeKey:value.edgeKey} : {};
      picker.value = String(options.findIndex(opt => opt.stepId === selected.stepId && opt.edgeKey === selected.edgeKey));
      paintInspector(); stage.select(selected,{focus});
      const title = steps.get(selected.stepId)?.title || edges.get(selected.edgeKey)?.label;
      const status = title ? "Selected " + title : "Whole process";
      if(announcement.textContent!==status)announcement.textContent=status;
    }
    function refreshSelection() {
      const top=inspector.scrollTop,open=inspector.querySelector(".ww-operating")?.open;
      const controlKey=node=>JSON.stringify([node.tagName,node.className,node.dataset.focusKey||node.dataset.sourceTurn||node.getAttribute("aria-label")]);
      const active=root.ownerDocument.activeElement;
      const focused=active&&inspector.contains(active)?controlKey(active):null;
      select(selected);
      const details=inspector.querySelector(".ww-operating");
      if(details&&open)details.open=true;
      if(focused){
        const replacement=Array.from(inspector.querySelectorAll("h4,button,summary")).find(node=>controlKey(node)===focused);
        const fallback=inspector.hidden?(steps.size?picker:processName):inspector.querySelector("h4");
        (replacement||fallback)?.focus({preventScroll:true});
      }
      if(!inspector.hidden)inspector.scrollTop=top;
    }
    async function draw() {
      const revision = ++generation;
      message.replaceChildren();
      try {
        await stage.update(graph);
        if (revision !== generation || destroyed) return;
        stage.select(selected,{focus:false});
      } catch {
        if (revision !== generation || destroyed) return;
        const retry = el("button","ww-link","Retry map"); retry.type = "button"; retry.addEventListener("click",draw);
        message.append(el("span","","The map could not be drawn. Use the list to inspect the captured steps and connections."),retry);
        if (onExit) {
          const diagram = el("button","ww-link","Open diagram"); diagram.type = "button";
          diagram.addEventListener("click",onExit); message.append(diagram);
        }
      }
    }
    function update(input,{live = false} = {}) {
      const data = {title:input?.title || "",steps:input?.steps || [],connections:input?.connections || []};
      if (input?.component_designs) data.component_designs = input.component_designs;
      const signature = JSON.stringify(data);
      if (signature === fingerprint) return;
      fingerprint = signature; graph = JSON.parse(signature); // The draft editor updates its graph in place.
      const previousStep=steps.get(selected.stepId),previousEdge=edges.get(selected.edgeKey);
      steps = new Map(graph.steps.map(s => [s.id,s])); edges = new Map(graph.connections.map(e => [edgeKey(e),e]));
      if(previousStep){
        const same=steps.get(previousStep.id);
        const sameWork=step=>step.title===previousStep.title && step.type===previousStep.type;
        if(!same || !sameWork(same)){
          const matches=graph.steps.filter(sameWork);
          const cited=same?.type===previousStep.type && (same?.evidence_turns||[]).some(id=>previousStep.evidence_turns?.includes(id));
          selected=matches.length===1?{stepId:matches[0].id}:cited?{stepId:same.id}:{};
        }
      }
      if(previousEdge && !edges.has(selected.edgeKey)){
        const matches=graph.connections.filter(edge=>edge.from===previousEdge.from && edge.to===previousEdge.to);
        if(matches.length===1)selected={edgeKey:edgeKey(matches[0])};
      }
      const empty = !graph.steps.length;
      processName.textContent = graph.title || "Process map";
      counts.textContent = count(graph.steps.length,"component") + " · " + count(graph.connections.length,"connection");
      syncMotion();
      for (const item of [counts,zoomOut,zoomLabel,zoomIn,fit,navigation,workspace]) item.hidden = empty;
      library.hidden = empty || !scope.CollectorComponentLibrary?.open;
      motion.hidden = !graph.connections.length;
      expand.hidden = empty && !theater.open;
      rebuildPicker(); refreshSelection(); void draw();
      if (empty) message.textContent = live ? "The map will appear when the interview captures its first step." : "This draft has no captured steps yet.";
    }
    function setVisible(value,{pageHidden=false}={}) {
      visible = Boolean(value); stage.setVisible(visible);
      if (!visible && !pageHidden && theater.open) theater.close();
    }
    function destroy() {
      destroyed = true; visible = false; generation++;
      media.removeEventListener("change",motionPreference); theater.removeEventListener("close",leaveTheater);
      if (theater.open) theater.close();
      stage.destroy(); root.replaceChildren();
    }
    return {update,setVisible,destroy,currentSelection:()=>({...selected}),restoreSelection:item=>select(item),isExpanded:()=>theater.open,openTheater(){if(!theater.open&&steps.size)toggleTheater();},closeTheater(){if(theater.open)theater.close();}};
  }
  if (scope.CollectorWorkflowStage?.create) scope.CollectorWalkthrough = {create};
})(window);
