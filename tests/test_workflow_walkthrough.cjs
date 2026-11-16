"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const invoice = require("../Examples/Synthetic-reviewed-session.json").workflow;

test("only a reported single chain folds into adjacent stations, including the return rows", async () => {
  const ELK = require("../web/vendor/elk.bundled.js");
  const window = {ELK:class extends ELK { layout(input) { return super.layout(JSON.parse(JSON.stringify(input))); } }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../web/workflow-graph.js"),"utf8"),{window,console});
  const layout = window.CollectorWorkflow.cinematicLayout;
  const steps=Array.from({length:22},(_,i)=>({id:"S"+i,title:i===9?"Reconcile all the unusually long statements and verify the detail before moving on":"Checkpoint "+i}));
  const connections=steps.slice(1).map((step,i)=>({from:steps[i].id,to:step.id,label:i===5?"Only once the reporting period has closed and the approved records are available":"Documented handoff"}));
  const graph={steps:[...steps].reverse(),connections:[...connections].reverse()};
  const original=JSON.stringify(graph);
  for(const aspect of [.65,1.9]){
    const result=await layout(graph,aspect);
    const nodes=new Map(result.nodes.map(node=>[node.id,node]));
    const directions=new Set();
    const labels=result.edges.flatMap(edge=>edge.labels.map(label=>({...label,key:edge.key})));
    const overlap=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
    for(const item of result.edges){
      const a=nodes.get(item.edge.from),b=nodes.get(item.edge.to);
      assert.equal(item.key,edgeKey(item.edge));
      const p=item.paths[0].points;
      assert.equal(p.length,2,"A direct handoff never circles around the row");
      const [s,t]=p;
      if(s.y===t.y){
        const right=s.x<t.x;directions.add(right?"right":"left");
        assert.equal(s.x,right?a.x+a.width:a.x);assert.equal(t.x,right?b.x:b.x+b.width);
        assert.equal(s.y,a.y+a.height/2);assert.equal(t.y,b.y+b.height/2);
      }else{
        directions.add("down");assert.equal(s.x,t.x);
        assert.equal(s.y,a.y+a.height);assert.equal(t.y,b.y);
      }
      const label=item.labels[0];
      assert.equal(label.lines.join("").replace(/\s/g,""),item.edge.label.replace(/\s/g,""));
      const segment={x:Math.min(s.x,t.x),y:Math.min(s.y,t.y),width:Math.abs(t.x-s.x),height:Math.abs(t.y-s.y)};
      for(const box of nodes.values()){
        assert(!overlap(label,box),"Room is reserved for every route label");
        assert(!overlap(segment,box),"A connector cannot pass through a station");
      }
      for(const other of labels.filter(other=>other.key!==item.key)){
        assert(!overlap(label,other)&&!overlap(segment,other),"Every condition stays with its own connection");
      }
    }
    assert.equal(directions.size,3,"The chain turns at the row ends and remains continuous");
  }
  const short=await layout({steps:steps.slice(0,5),connections:connections.slice(0,4)});
  assert(short.edges.every(edge=>edge.paths[0].points.length===2),"Short chains run straight through");
  const disjoint={steps:steps.slice(0,8),connections:[...connections.slice(0,4),...connections.slice(5,7),{from:"S7",to:"S5",label:"Retry"}]};
  const separate=await layout(disjoint);
  assert.deepEqual(Array.from(separate.edges,item=>item.key).sort(),disjoint.connections.map(edgeKey).sort(),"A separate cycle never becomes part of the main sequence");
  assert.equal(JSON.stringify(graph),original);
});

test("a connector that stops short of the reported station is never presented as complete", async () => {
  const ELK=require("../web/vendor/elk.bundled.js");
  const window={ELK:class extends ELK {
    async layout(input) {
      const result=await super.layout(JSON.parse(JSON.stringify(input)));
      result.edges[0].sections[0].endPoint.x-=24;
      return result;
    }
  }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../web/workflow-graph.js"),"utf8"),{window,console});
  await assert.rejects(window.CollectorWorkflow.cinematicLayout(invoice),/attached to its reported steps/);
});

test("folded chains and abandoned cinematic views avoid starting the layered engine", async () => {
  let resolveEngine,loads=0;
  const window={CollectorWorkflowAssets:{loadEngine(){
    loads++;
    return new Promise(resolve=>{resolveEngine=resolve;});
  }}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../web/workflow-graph.js"),"utf8"),{window,console});
  const layout=window.CollectorWorkflow.cinematicLayout;
  const steps=Array.from({length:8},(_,i)=>({id:String(i),title:"Step "+i}));
  const chain=await layout({steps,connections:steps.slice(1).map((step,i)=>({from:steps[i].id,to:step.id}))});
  assert.equal(chain.usesAspect,true);
  assert.equal(loads,0);
  let current=true;
  const pending=layout(invoice,1.9,()=>current);
  current=false;
  resolveEngine(class {constructor(){throw new Error("Abandoned cinematic view started an engine");}});
  assert.equal(await pending,null);
  assert.equal(loads,1);
});

// Exercise the actual UI controller with local evidence and a controllable stage.
class Element extends EventTarget {
  constructor(tag, document) {
    super();
    this.tagName = tag;
    this.ownerDocument = document;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.className = "";
    this._text = "";
    this.value = "";
    this.classList = {toggle:(name, enabled) => {
      const classes = new Set(this.className.split(/\s+/).filter(Boolean));
      if (enabled) classes.add(name); else classes.delete(name);
      this.className = [...classes].join(" ");
    }};
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set textContent(value) { this.replaceChildren(); this._text = String(value ?? ""); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  get childElementCount() { return this.children.length; }
  get isConnected() { return this === this.ownerDocument.body || Boolean(this.parentElement?.isConnected); }
  remove() {
    if (this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
    this.parentElement = null;
  }
  append(...items) {
    for (let item of items) {
      if (typeof item === "string") item = this.ownerDocument.createTextNode(item);
      item.remove();
      item.parentElement = this;
      this.children.push(item);
    }
  }
  replaceChildren(...items) {
    for (const child of this.children) child.parentElement = null;
    this.children = [];
    this._text = "";
    this.append(...items);
  }
  insertBefore(item, next) {
    item.remove();
    item.parentElement = this;
    this.children.splice(this.children.indexOf(next), 0, item);
  }
  nodes() { return [this, ...this.children.flatMap(child => child.nodes())]; }
  contains(element) { return this.nodes().includes(element); }
  querySelectorAll(selector) { return this.nodes().slice(1).filter(node => selector.split(",").includes(node.tagName)); }
  querySelector(selector) {
    return this.nodes().slice(1).find(node => selector.startsWith(".")
      ? node.className.split(/\s+/).includes(selector.slice(1)) : node.tagName === selector) || null;
  }
  focus() { this.ownerDocument.activeElement = this; }
  click() { if (!this.disabled) { this.focus(); this.dispatchEvent(new Event("click")); } }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent(new Event("close")); }
}

function setup({defer = false, reduced = false} = {}) {
  const document = new EventTarget();
  document.createElement = tag => new Element(tag, document);
  document.createElementNS = (_ns, tag) => document.createElement(tag);
  document.createTextNode = value => { const node = document.createElement("#text"); node.textContent = value; return node; };
  document.body = document.createElement("body");
  document.activeElement = document.body;
  const root = document.createElement("div"); document.body.append(root);
  const preference = new EventTarget(); preference.matches = reduced;
  const layouts = [], selected = [], opened = [], visibility = [], motion = [], sourceLinks = [];
  let callbacks, disposed = false, requestCount = 0;
  const noNetwork = () => { requestCount++; throw new Error("The cinematic map requested network access"); };
  const stage = {
    update(graph) {
      const record = {graph:structuredClone(graph)};
      layouts.push(record);
      if (!defer) return Promise.resolve(true);
      return new Promise((resolve, reject) => { record.resolve = resolve; record.reject = reject; });
    },
    select(value) { selected.push(structuredClone(value)); },
    setVisible(value) { visibility.push(value); },
    setMotion(value) { motion.push(value); },
    fit() {}, zoom() {}, destroy() { disposed = true; }
  };
  const window = {
    document, fetch:noNetwork, matchMedia:() => preference,
    CollectorWorkflowStage:{create:(_element, events) => { callbacks = events; return stage; }}
  };
  const source = fs.readFileSync(path.join(__dirname, "..", "web", "workflow-walkthrough.js"), "utf8");
  vm.runInNewContext(source, {window, document, fetch:noNetwork, console});
  const ui = window.CollectorWalkthrough.create(root, {
    onDetails:id => opened.push(id),
    renderEvidence(refs) {
      const printed = Array.from(refs); sourceLinks.push(printed);
      return document.createTextNode(printed.join(", "));
    }
  });
  const button = (label, container = root) => container.nodes().find(node => node.tagName === "button" &&
    (node.getAttribute("aria-label") === label || node.textContent === label));
  const inspector = () => root.querySelector(".ww-inspector");
  return {ui, root, stage, layouts, selected, opened, visibility, motion, preference, button, inspector,
    callbacks:() => callbacks, disposed:() => disposed, requestCount:() => requestCount, sourceLinks};
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const edgeKey = edge => JSON.stringify([edge.from, edge.to, edge.label || ""]);

test("the complete invoice graph is immediately available for arbitrary component and route selection", async () => {
  const h = setup();
  const input = structuredClone(invoice);
  const handoff = input.connections.at(-1), other = {...handoff,label:"Paper delivery",evidence_turns:["t202"]};
  input.connections.push(other); // Two separately reported handoffs may have identical endpoints.
  h.ui.update(input); h.ui.setVisible(true);
  await flush();
  assert.deepEqual(h.layouts[0].graph.steps, input.steps);
  assert.deepEqual(h.layouts[0].graph.connections, input.connections);
  const picker = h.root.querySelector(".ww-picker");
  assert.equal(picker.nodes().filter(n => n.tagName === "option").length, 1 + input.steps.length + input.connections.length);
  assert(h.inspector().hidden);

  h.callbacks().onSelectStep("S11"); // Jump directly to the final station without traversing any route.
  assert.equal(h.inspector().querySelector("h4").textContent, input.steps.at(-1).title);
  assert(h.inspector().textContent.includes(input.steps.at(-1).actor));
  h.button("Step details and sources", h.inspector()).click();
  assert.deepEqual(h.opened, ["S11"]);

  for (const edge of [other, handoff]) {
    h.callbacks().onSelectEdge(edgeKey(edge));
    assert.equal(h.inspector().querySelector("h4").textContent, edge.label);
    assert.deepEqual(h.sourceLinks.at(-1), edge.evidence_turns);
    assert.equal(h.selected.at(-1).edgeKey, edgeKey(edge));
  }
  const destination = input.steps.at(-1);
  h.button(destination.title, h.inspector()).click();
  assert.equal(h.selected.at(-1).stepId, destination.id);
  h.button("Fit map").click();
  assert(h.inspector().hidden);
  assert.equal(h.layouts.length, 1, "Inspecting components or routes must reuse the layout.");
  assert.equal(h.requestCount(), 0);
});

test("in-place live corrections preserve surviving selection and clear a removed connection", async () => {
  const h = setup(), input = structuredClone(invoice);
  h.ui.update(input, {live:true});
  await flush();
  h.callbacks().onSelectStep("S4");
  const step = input.steps.find(item => item.id === "S4");
  step.title = "Compare all three purchasing records";
  h.ui.update(input, {live:true});
  await flush();
  assert.equal(h.selected.at(-1).stepId, "S4");
  assert.equal(h.inspector().querySelector("h4").textContent, step.title);
  assert.equal(h.layouts.at(-1).graph.steps.find(item => item.id === "S4").title, step.title);
  h.ui.update(structuredClone(input), {live:true});
  assert.equal(h.layouts.length, 2, "An equivalent graph update should not reset or relayout the map.");

  const edge = input.connections.pop();
  h.callbacks().onSelectEdge(edgeKey(edge));
  input.connections.reverse(); input.connections.push(edge); // Reordering the data must not change the selected connector.
  h.ui.update(input, {live:true}); await flush();
  assert.equal(h.selected.at(-1).edgeKey, edgeKey(edge));
  input.connections.pop(); h.ui.update(input, {live:true}); await flush();
  assert(h.inspector().hidden);
  assert.deepEqual(h.selected.at(-1), {});
  assert.equal(h.requestCount(), 0);
});

test("live updates preserve the reader's place in the selected inspector", async () => {
  const h=setup(),data=structuredClone(invoice);
  h.ui.update(data,{live:true});h.ui.setVisible(true);await flush();
  h.callbacks().onSelectStep("S4");
  const panel=h.inspector(),doc=panel.ownerDocument;
  const outgoing=data.connections.find(edge=>edge.from==="S4");
  const next=data.steps.find(step=>step.id===outgoing.to);
  const routeButton=()=>h.button(outgoing.label+" · "+next.title,panel);
  panel.querySelector("details").open=true;routeButton().focus();panel.scrollTop=102;
  next.title="Corrected downstream handoff";
  data.steps.find(step=>step.id==="S4").description="Current evidence for the checkpoint.";
  h.ui.update(data,{live:true});await flush();
  assert(panel.querySelector("details").open);
  assert(doc.activeElement===routeButton(),"A corrected route title must keep focus on the same captured connection");
  assert.equal(panel.scrollTop,102);
  assert(panel.textContent.includes("Current evidence for the checkpoint."));
  data.connections=data.connections.filter(edge=>edge!==outgoing);
  h.ui.update(data,{live:true});await flush();
  assert(doc.activeElement===panel.querySelector("h4"),"A removed route returns focus to the selected step heading");
  const picker=h.root.querySelector(".ww-picker");picker.focus();
  data.steps.find(step=>step.id==="S4").description="Another reported detail.";
  h.ui.update(data,{live:true});await flush();assert(doc.activeElement===picker);
  panel.querySelector("summary").focus();
  data.steps=data.steps.filter(step=>step.id!=="S4");data.connections=data.connections.filter(edge=>edge.from!=="S4"&&edge.to!=="S4");
  h.ui.update(data,{live:true});await flush();
  assert(panel.hidden);assert(doc.activeElement===picker);h.ui.destroy();
});

test("only the current layout can display an error, and its fallback supports selection and retry", async () => {
  const h = setup({defer:true}), input = structuredClone(invoice);
  h.ui.update(input);
  input.steps[0].title = "Register the incoming case"; h.ui.update(input);
  h.layouts[1].resolve(); await flush();
  h.layouts[0].reject(new Error("obsolete layout failure")); await flush();
  assert.equal(h.root.querySelector(".ww-message").textContent, "");

  input.connections.pop(); h.ui.update(input);
  h.layouts[2].reject(new Error("local geometry failed")); await flush();
  assert.match(h.root.querySelector(".ww-message").textContent, /map could not be drawn/i);
  const picker = h.root.querySelector(".ww-picker");
  const lastComponent = picker.nodes().find(node => node.tagName === "option" && node.textContent.startsWith("S11 ·"));
  picker.value = lastComponent.value; picker.dispatchEvent(new Event("change"));
  assert.equal(h.inspector().querySelector("h4").textContent, input.steps.at(-1).title);
  h.button("Retry map").click(); h.layouts[3].resolve(); await flush();
  assert.equal(h.root.querySelector(".ww-message").textContent, "");
  assert.equal(h.selected.at(-1).stepId, "S11");
  assert.equal(h.requestCount(), 0);
});

test("visibility, motion preferences and destruction stop the corresponding stage work", async () => {
  const h = setup({reduced:true});
  h.ui.update(invoice); h.ui.setVisible(true); await flush();
  const motion = h.button("Flow motion");
  assert(motion.disabled); assert.equal(h.motion.at(-1), false);
  h.preference.matches = false; h.preference.dispatchEvent(new Event("change"));
  assert(!motion.disabled); assert.equal(h.motion.at(-1), true);
  motion.click(); assert.equal(h.motion.at(-1), false);
  h.ui.setVisible(false); h.ui.setVisible(true);
  assert.deepEqual(h.visibility, [true, false, true]);
  assert.equal(h.motion.at(-1), false);
  h.ui.destroy();
  assert(h.disposed());
  const callsBefore = h.motion.length;
  h.preference.matches = true; h.preference.dispatchEvent(new Event("change"));
  assert.equal(h.motion.length, callsBefore);
  assert.equal(h.root.childElementCount, 0);
  assert.equal(h.requestCount(), 0);
});

test("a live graph that reassigns step IDs retains the inspected work", async () => {
  const h=setup(),data=structuredClone(invoice);
  h.ui.update(data,{live:true});await flush();
  const [first,second]=data.steps,oldId=first.id,newId=second.id;
  h.ui.restoreSelection({stepId:oldId});
  first.id=newId;second.id=oldId;
  h.ui.update(data,{live:true});await flush();
  assert.equal(h.ui.currentSelection().stepId,newId);
  assert.equal(h.inspector().querySelector("h4").textContent,first.title);
  h.ui.destroy();
});
