/* Local procedure and diagram exports. Every route comes from an explicit saved connection. */
(function(scope) {
  "use strict";
  const xml=value=>String(value??"").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff\uD800-\uDFFF]/gu,"�")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&apos;");
  const fallback="UNKNOWN / TBD";
  const sources=item=>(item.evidence_turns||[]).join(", ")||"Uncited";
  function routeReview(graph,edge){
    const title=id=>{const node=graph.steps.find(s=>s.id===id);return [node?.title,node?.actor,node?.type,node?.entity_scope||[]];};
    const row=(graph.route_assurance||[]).find(r=>r.from===edge.from&&r.to===edge.to&&r.label===edge.label&&
      JSON.stringify(r.evidence_turns)===JSON.stringify(edge.evidence_turns)&&
      JSON.stringify(r.endpoints)===JSON.stringify([title(edge.from),title(edge.to)]));
    const changed=[edge.from,edge.to].some(id=>graph.steps.find(node=>node.id===id)?.reviewed_fields?.length);
    const labels={supported:"Source-checked",pending:"Awaiting source check",unread:"Source unread",unsupported:"Unsupported"};
    if(changed&&row?.status==="supported")return {label:"Awaiting source check",passages:[]};
    return {label:(labels[row?.status]||"Source check unknown")+(row?.reason?" - "+row.reason:""),passages:row?.passages||[]};
  }
  function csv(draft){
    const cell=value=>{
      let text=String(value??"");
      if(/^[\s\uFEFF]*[=+@-]/u.test(text))text="'"+text;
      return '"'+text.replaceAll('"','""')+'"';
    };
    const rows=[["Step ID","Step title","Type","Owner","System","Input","Output","Next steps and conditions","Sources","Review edits"]];
    for(const step of draft.steps){
      const outgoing=draft.connections.filter(edge=>edge.from===step.id).map(edge=>
        edge.to+(edge.label?" — "+edge.label:"")+" ["+routeReview(draft,edge).label+"]");
      rows.push([step.id,step.title,step.type,step.actor,step.system,step.input,step.output,outgoing.join(" | "),sources(step),(step.reviewed_fields||[]).join(", ")]);
    }
    return "\uFEFF"+rows.map(row=>row.map(cell).join(",")).join("\r\n")+"\r\n";
  }
  function mermaid(draft){
    const label=value=>Array.from(String(value||fallback)).map(ch=>/[A-Za-z0-9 ,._-]/.test(ch)?ch:"#"+ch.codePointAt(0)+";").join("");
    const ids=new Map(draft.steps.map((step,index)=>[step.id,"n"+(index+1)])),lines=["flowchart TD"];
    for(const step of draft.steps){
      const caption=label(step.id+" · "+(step.title||fallback)),decision=step.type==="decision";
      lines.push("  "+ids.get(step.id)+(decision?'{"'+caption+'"}':'["'+caption+'"]'));
    }
    for(const edge of draft.connections)if(ids.has(edge.from)&&ids.has(edge.to))lines.push("  "+ids.get(edge.from)+" -->"+('|"' + label([edge.label,routeReview(draft,edge).label].filter(Boolean).join(" - ")) + '"|')+" "+ids.get(edge.to));
    return lines.join("\n");
  }
  function bpmn(draft,layout,drawnGraph){
    const ids=new Map(draft.steps.map((step,index)=>[step.id,"Node_"+(index+1)])),positions=new Map((layout?.children||[]).map(box=>[box.id,box]));
    const routeKey=edge=>JSON.stringify([edge.from,edge.to,(edge.label||"").trim()]);
    const layoutById=new Map((layout?.edges||[]).map(edge=>[edge.id,edge]));
    // Older saved drafts can repeat the same route with different citations. The canvas
    // combines those routes. Give each saved flow the geometry of its own drawn route.
    const projectedRoutes = new Map();
    if (drawnGraph && drawnGraph.connections.length < draft.connections.length) {
      drawnGraph.connections.forEach((edge,index)=>projectedRoutes.set(routeKey(edge),index));
    }
    const stages={start:"startEvent",trigger:"startEvent",end:"endEvent",decision:"exclusiveGateway",merge:"exclusiveGateway",parallel_join:"parallelGateway",parallel_split:"parallelGateway",subprocess:"subProcess"};
    const rows=['<?xml version="1.0" encoding="UTF-8"?>','<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_1" targetNamespace="urn:ai-process-collector:workflow">','<process id="Process_1" isExecutable="false" name="'+xml(draft.title||"Draft process")+'"><documentation>DRAFT — process owner review required.</documentation>'];
    const lanes=new Map();
    for(const step of draft.steps){
      const actor=(step.actor||"").trim();if(!actor||/^unknown\b/i.test(actor))continue;
      if(!lanes.has(actor))lanes.set(actor,[]);lanes.get(actor).push(ids.get(step.id));
    }
    if(lanes.size){
      rows.push('<laneSet id="LaneSet_1">');let index=0;
      for(const [actor,steps] of lanes)rows.push('<lane id="Lane_'+(++index)+'" name="'+xml(actor)+'">'+steps.map(id=>'<flowNodeRef>'+id+'</flowNodeRef>').join("")+'</lane>');
      rows.push('</laneSet>');
    }
    const routeIds=draft.connections.map((_,i)=>"Route_"+(i+1));
    for(const [i,step] of draft.steps.entries()){
      const kind=stages[step.type]||"task",id=ids.get(step.id),direction=step.type==="parallel_join"||step.type==="merge"?' gatewayDirection="Converging"':step.type==="parallel_split"||step.type==="decision"?' gatewayDirection="Diverging"':"";
      rows.push('<'+kind+' id="'+id+'" name="'+xml(step.title||step.id)+'"'+direction+'><documentation>'+xml([step.id,step.description,"Sources: "+sources(step),step.reviewed_fields?.length?"Edited in review: "+step.reviewed_fields.join(", "):""].filter(Boolean).join("\n"))+'</documentation>');
      for(const [j,route] of draft.connections.entries()){if(route.to===step.id)rows.push('<incoming>'+routeIds[j]+'</incoming>');if(route.from===step.id)rows.push('<outgoing>'+routeIds[j]+'</outgoing>');}
      rows.push('</'+kind+'>');
      if(!positions.has(step.id))positions.set(step.id,{x:40+(i%4)*200,y:40+Math.floor(i/4)*115,width:140,height:64});
    }
    for(const [i,edge] of draft.connections.entries())rows.push('<sequenceFlow id="'+routeIds[i]+'" sourceRef="'+ids.get(edge.from)+'" targetRef="'+ids.get(edge.to)+'" name="'+xml(edge.label)+'"><documentation>'+xml("Sources: "+sources(edge)+". "+routeReview(draft,edge).label+" "+routeReview(draft,edge).passages.map(p=>p.source_id+": "+p.quote).join(" "))+'</documentation></sequenceFlow>');
    rows.push('</process><bpmndi:BPMNDiagram id="Diagram_1"><bpmndi:BPMNPlane id="Plane_1" bpmnElement="Process_1">');
    for(const step of draft.steps){
      const id=ids.get(step.id),box=positions.get(step.id);
      rows.push('<bpmndi:BPMNShape id="Shape_'+id+'" bpmnElement="'+id+'"><dc:Bounds x="'+box.x+'" y="'+box.y+'" width="'+box.width+'" height="'+box.height+'"/></bpmndi:BPMNShape>');
    }
    for(const [i,edge] of draft.connections.entries()){
      const drawnIndex = projectedRoutes.size ? projectedRoutes.get(routeKey(edge)) : i;
      const section = layoutById.get("edge-"+drawnIndex)?.sections?.[0];
      const from=positions.get(edge.from),to=positions.get(edge.to);
      const coordinates=section?[section.startPoint,...(section.bendPoints||[]),section.endPoint]:[{x:from.x+from.width,y:from.y+from.height/2},{x:to.x,y:to.y+to.height/2}];
      rows.push('<bpmndi:BPMNEdge id="Edge_'+routeIds[i]+'" bpmnElement="'+routeIds[i]+'">'+coordinates.map(point=>'<di:waypoint x="'+point.x+'" y="'+point.y+'"/>').join("")+'</bpmndi:BPMNEdge>');
    }
    rows.push('</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></definitions>');return rows.join("\n");
  }
  async function png(svg,doc=scope.document){
    const image=new Image();image.src="data:image/svg+xml;charset=utf-8,"+encodeURIComponent(svg);
    await image.decode();
    {
      const scale=Math.min(2,8192/Math.max(image.naturalWidth,image.naturalHeight,1)),canvas=doc.createElement("canvas");
      canvas.width=Math.max(1,Math.ceil(image.naturalWidth*scale));canvas.height=Math.max(1,Math.ceil(image.naturalHeight*scale));
      const drawing=canvas.getContext("2d");if(!drawing)throw Error("Your browser could not create a PNG.");
      drawing.fillStyle="#fff";drawing.fillRect(0,0,canvas.width,canvas.height);drawing.drawImage(image,0,0,canvas.width,canvas.height);
      return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(Error("The PNG could not be created.")),"image/png"));
    }
  }
  const checkedGraphs=new WeakMap();
  function structureQuestions(draft){
    if(!draft?.steps?.length)return [];
    const signature=JSON.stringify([draft.steps.map(({id,title,type})=>[id,title,type]),(draft.connections||[]).map(({from,to,label})=>[from,to,label])]);
    const previous=checkedGraphs.get(draft);if(previous?.signature===signature)return previous.questions;
    const questions=[],steps=draft.steps,ids=new Map(steps.map(s=>[s.id,s])),into=new Map(steps.map(s=>[s.id,[]])),out=new Map(steps.map(s=>[s.id,[]]));
    for(const edge of draft.connections||[]){if(ids.has(edge.from)&&ids.has(edge.to)){out.get(edge.from).push(edge);into.get(edge.to).push(edge);}}
    const reach=(start,blocked,undirected=false)=>{
      const reached=new Set(),waiting=[start];
      while(waiting.length){const id=waiting.pop();if(id===blocked||reached.has(id))continue;reached.add(id);waiting.push(...out.get(id).map(edge=>edge.to));if(undirected)waiting.push(...into.get(id).map(edge=>edge.from));}return reached;
    };
    const groups=[],seen=new Set(),loopSeen=new Set(),closures=new Map(steps.map(step=>[step.id,reach(step.id)]));
    const name=step=>step.id+" ("+(step.title||"untitled").slice(0,160)+")";
    for(const step of steps){
      const incoming=[...new Set(into.get(step.id).map(edge=>edge.from))],outgoing=out.get(step.id),targets=new Set(outgoing.map(edge=>edge.to));
      const labels=outgoing.map(edge=>(edge.label||"").trim().toLowerCase()),labelled=new Set(labels.filter(label=>label&&!["unknown","tbd"].includes(label))),title=name(step);
      if(step.type==="decision"){
        if(labelled.size<2)questions.push("Are there other outcomes from decision "+title+", and where do they lead?");
        for(const edge of outgoing)if(!labelled.has((edge.label||"").trim().toLowerCase()))questions.push("What condition leads from decision "+title+" to step "+edge.to+"?");
      }
      if(step.type==="merge"&&incoming.length<2)questions.push("Which alternative routes converge at "+title+"?");
      if(step.type==="parallel_split"&&targets.size<2)questions.push("Which branches begin in parallel at "+title+"?");
      if(step.type==="parallel_join"){
        if(incoming.length<2)questions.push("Which parallel prerequisites must all finish at "+title+"?");
        else if(incoming.some(id=>incoming.some(other=>other!==id&&reach(id,step.id).has(other))))questions.push("Does parallel join "+title+" count the same branch more than once?");
      }
      if(["merge","parallel_join"].includes(step.type)&&incoming.length>=2){
        const opposite=step.type==="merge"?"parallel_split":"decision";
        for(const origin of steps.filter(node=>node.type===opposite)){
          const paths=out.get(origin.id).map(edge=>incoming.filter(id=>reach(edge.to,step.id).has(id)));
          if(paths.some((left,index)=>left.length&&paths.slice(index+1).some(right=>right.length&&right.every(id=>!left.includes(id))))){
            questions.push("Confirm whether one or all branches must reach "+title+" after "+name(origin)+".");break;
          }
        }
      }
      if(step.type==="start"&&incoming.length)questions.push("Does "+title+" represent a new process start or a return within this process?");
      if(step.type==="end"&&outgoing.length)questions.push("Is "+title+" a process ending or an intermediate result?");
      if(!["decision","parallel_split"].includes(step.type)&&labels.length>1&&new Set(labels).size<labels.length)questions.push("Are the outgoing paths from "+title+" alternatives, or must they all occur?");
      if(["activity","wait","subprocess","document","data_store"].includes(step.type)&&incoming.length>1)questions.push("Does any incoming route start "+title+", or must all prerequisites finish?");
      if(!loopSeen.has(step.id)){
        const cycle=[...closures.get(step.id)].filter(id=>closures.get(id).has(step.id));
        if(cycle.length>1||targets.has(step.id)){cycle.forEach(id=>loopSeen.add(id));if(cycle.every(id=>out.get(id).every(edge=>cycle.includes(edge.to))))questions.push("What ends the loop containing "+title+"?");}
      }
      if(!seen.has(step.id)){const members=reach(step.id,null,true);members.forEach(id=>seen.add(id));groups.push([step,members.size]);}
    }
    if(groups.length>1)for(const [step,size] of groups){if(size===1)questions.push("How does "+name(step)+" connect to the rest of this process?");}
    const chains=groups.filter(([,size])=>size>1);
    for(const [step] of chains.slice(1))questions.push("Is there a reported handoff between the routes containing "+name(chains[0][0])+" and "+name(step)+"?");
    const unique=[...new Set(questions)];checkedGraphs.set(draft,{signature,questions:unique});return unique;
  }
  const api={bpmn,csv,mermaid,png,structureQuestions,routeReview};scope.CollectorWorkflowExports=api;
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
})(typeof window==="undefined"?globalThis:window);
