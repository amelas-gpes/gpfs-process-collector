"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const invoice = require("../Examples/Synthetic-reviewed-session.json").workflow;

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
