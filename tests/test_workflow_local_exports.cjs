"use strict";
const assert=require("node:assert/strict");
const {csv,bpmn,mermaid,structureQuestions}=require("../web/workflow-exports.js");
const draft={title:"Fee & approval",steps:[
  {id:"S1",title:"=HYPERLINK(1)",type:"start",actor:"Operator",evidence_turns:["t1"]},
  {id:"S2",title:"Approve <draft>?",type:"decision",actor:"Reviewer",evidence_turns:["t8"]},
  {id:"S3",title:"Close",type:"end",actor:"Reviewer",reviewed_fields:["title"],evidence_turns:[]}
],connections:[{from:"S1",to:"S2",label:"",evidence_turns:["t1"]},{from:"S2",to:"S3",label:"Yes",evidence_turns:["t8"]}]};
const xml=bpmn(draft,{children:[{id:"S1",x:18,y:21,width:90,height:60}]});
assert.match(xml,/<startEvent id="Node_1"/);
assert.match(xml,/<exclusiveGateway[^>]*Approve &lt;draft&gt;\?"/);
assert.match(xml,/<endEvent id="Node_3"/);
assert.match(xml,/sourceRef="Node_2" targetRef="Node_3" name="Yes"/);
assert.match(xml,/x="18" y="21"/);
assert.match(xml,/lane id="Lane_2" name="Reviewer"/);
assert.match(xml,/Sources: t8/);assert.match(xml,/Edited in review: title/);
// A saved draft can cite the same named route twice. The canvas projects one path for
// it; a second saved occurrence must use that geometry without shifting later routes.
const routes=[{from:'S1',to:'S2',label:'Ready',evidence_turns:['u1']},{from:'S1',to:'S2',label:'Ready',evidence_turns:['u2']},{from:'S1',to:'S3',label:'Return',evidence_turns:['u3']}];
const positions={edges:[12,48].map((x,i)=>({id:'edge-'+i,sections:[{startPoint:{x,y:0},endPoint:{x,y:10}}]}))};
const duplicateXml=bpmn({...draft,connections:routes},positions,{connections:[routes[0],routes[2]]});
assert.deepEqual([...duplicateXml.matchAll(/<bpmndi:BPMNEdge [^>]*><di:waypoint x="(\d+)"/g)].map(match=>match[1]),['12','12','48']);
for(const id of ['u1','u2','u3'])assert.match(duplicateXml,new RegExp('Sources: '+id));
// A layout prepared directly from the unprojected draft has a distinct path for each occurrence.
const fullLayout={edges:[12,30,48].map((x,i)=>({id:'edge-'+i,sections:[{startPoint:{x,y:0},endPoint:{x,y:10}}]}))};
const fullXml=bpmn({...draft,connections:routes},fullLayout);
assert.deepEqual([...fullXml.matchAll(/<bpmndi:BPMNEdge [^>]*><di:waypoint x="(\d+)"/g)].map(match=>match[1]),['12','30','48']);
const table=csv(draft);assert.ok(table.includes("\uFEFF"));assert.ok(table.includes('"\'=HYPERLINK(1)"'));assert.ok(table.includes("S3 — Yes"));assert.ok(table.includes('"Uncited","title"'));
const graph=mermaid(draft);assert.match(graph,/^flowchart TD/);assert.match(graph,/n2 -->\|"Yes - Source check unknown"\| n3/);assert.ok(!graph.includes("<draft>"));
assert.ok(structureQuestions(draft).some(q=>q.includes("other outcomes")));
draft.connections.push({from:"S2",to:"S1",label:"No",evidence_turns:[]});
assert.ok(!structureQuestions(draft).some(q=>q.includes("other outcomes")));
assert.ok(structureQuestions(draft).some(q=>q.includes("new process start")));
const join={steps:[{id:"A",title:"Branch",type:"parallel_join"}],connections:[{from:"A",to:"A",label:""}]};
assert.ok(structureQuestions(join).some(q=>q.includes("prerequisites")));assert.ok(structureQuestions(join).some(q=>q.includes("loop")));
console.log("Local workflow exports and structural validation passed.");
