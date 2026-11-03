"use strict";
// Real bundled ELK, fictional process fixtures, and geometric acceptance checks.
// Uses existing Node and the vendored engine; no browser, downloads, or provider calls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ELK = require("../web/vendor/elk.bundled.js");
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/workflow-scenarios.json"), "utf8")).scenarios;
const window = { ELK };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../web/workflow-graph.js"), "utf8"), { window, console });
const api = window.CollectorWorkflow;
const clean = value => JSON.parse(JSON.stringify(value));
const EPS = 0.1;
const overlap = (a, b) => a.x < b.x + b.width - EPS && a.x + a.width > b.x + EPS && a.y < b.y + b.height - EPS && a.y + a.height > b.y + EPS;
const points = section => [section.startPoint, ...(section.bendPoints || []), section.endPoint];
const lineHits = (a, b, box) => {
  // Touching a node boundary is an allowed connection; crossing its interior is not.
  if (Math.abs(a.x - b.x) < EPS) return a.x > box.x + EPS && a.x < box.x + box.width - EPS && Math.max(a.y, b.y) > box.y + EPS && Math.min(a.y, b.y) < box.y + box.height - EPS;
  if (Math.abs(a.y - b.y) < EPS) return a.y > box.y + EPS && a.y < box.y + box.height - EPS && Math.max(a.x, b.x) > box.x + EPS && Math.min(a.x, b.x) < box.x + box.width - EPS;
  return false;
};
const compact = value => String(value || "").replace(/\s+/gu, "");

function auditText(input) {
  let blocks = 0, lines = 0;
  for (const step of input.steps) {
    const metrics = api.nodeMetrics(step);
    assert.equal(metrics.type, step.type, `${step.id}: every supported component retains its type.`);
    for (const block of metrics.blocks) {
      blocks++;
      assert(block.size >= 10, `${step.id}: text must not shrink to hide overflow.`);
      assert(block.x >= 0 && block.y >= 0 && block.x + block.width <= metrics.width && block.y + block.height <= metrics.height, `${step.id}: text blocks stay inside node bounds.`);
      for (const line of block.lines) {
        lines++;
        assert(api.measureText(line, block.size, block.weight) <= block.width, `${step.id}: measured ${block.role} line exceeds available width.`);
      }
      if (metrics.diamond) {
        for (const [x, y] of [[block.x, block.y], [block.x + block.width, block.y], [block.x, block.y + block.height], [block.x + block.width, block.y + block.height]]) {
          assert(Math.abs(x - metrics.width / 2) / (metrics.width / 2) + Math.abs(y - metrics.height / 2) / (metrics.height / 2) <= 1, `${step.id}: ${block.role} content rectangle must fit inside the diamond, including its narrow top and bottom.`);
        }
      }
    }
    for (const field of ["title", "actor", "system"]) {
      if (/^(unknown|not established|not applicable|n\/?a)$/i.test(String(step[field] || "").trim())) continue;
      assert.equal(compact(metrics.blocks.find(block => block.role === field)?.lines.join("")), compact(step[field]), `${step.id}: ${field} must wrap without losing text or truncating long identifiers.`);
    }
  }
  for (const edge of input.connections) {
    if (!edge.label) continue;
    const metrics = api.edgeMetrics(edge.label);
    assert.equal(compact(metrics.lines.join("")), compact(edge.label), `${edge.from}/${edge.to}: full branch conditions must remain readable.`);
    for (const line of metrics.lines) assert(api.measureText(line, 11, 500) <= metrics.width - 24, `${edge.from}/${edge.to}: measured branch label exceeds its padded box.`);
  }
  return { blocks, lines };
}

function auditLayout(layout, input, direction) {
  const issues = [], nodes = layout.children || [], edges = layout.edges || [], labels = edges.flatMap(edge => (edge.labels || []).map(label => ({ ...label, edge: edge.id })));
  const add = (kind, detail) => issues.push({ kind, detail });
  if (!Number.isFinite(layout.width) || !Number.isFinite(layout.height) || layout.width <= 0 || layout.height <= 0) add("invalid-bounds", "Canvas must have finite positive dimensions.");
  if (nodes.length !== input.steps.length || edges.length !== input.connections.length) add("lost-facts", "Layout changed the reported topology.");
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    if ([a.x, a.y, a.width, a.height].some(n => !Number.isFinite(n)) || a.width <= 0 || a.height <= 0) add("invalid-node", a.id);
    if (a.x < -EPS || a.y < -EPS || a.x + a.width > layout.width + EPS || a.y + a.height > layout.height + EPS) add("node-outside-canvas", a.id);
    for (const b of nodes.slice(i + 1)) if (overlap(a, b)) add("node-overlap", `${a.id}/${b.id}`);
  }
  for (let i = 0; i < labels.length; i++) {
    const label = labels[i];
    if ([label.x, label.y, label.width, label.height].some(n => !Number.isFinite(n))) add("invalid-label", label.edge);
    if (label.x < -EPS || label.y < -EPS || label.x + label.width > layout.width + EPS || label.y + label.height > layout.height + EPS) add("label-outside-canvas", label.edge);
    for (const node of nodes) if (overlap(label, node)) add("label-node-overlap", `${label.edge}/${node.id}`);
    for (const other of labels.slice(i + 1)) if (overlap(label, other)) add("label-label-overlap", `${label.edge}/${other.edge}`);
  }
  for (const edge of edges) {
    const original = input.connections[Number(edge.id.replace("edge-", ""))];
    if (!edge.sections?.length) add("unrouted-edge", edge.id);
    for (const section of edge.sections || []) {
      const vertices = points(section);
      for (let i = 1; i < vertices.length; i++) {
        const a = vertices[i - 1], b = vertices[i];
        if (Math.abs(a.x - b.x) > EPS && Math.abs(a.y - b.y) > EPS) add("diagonal-edge", edge.id);
        for (const node of nodes) if (node.id !== original.from && node.id !== original.to && lineHits(a, b, node)) add("edge-through-node", `${edge.id}/${node.id}`);
        for (const label of labels) if (label.edge !== edge.id && lineHits(a, b, label)) add("edge-through-unrelated-label", `${edge.id}/${label.edge}`);
      }
    }
  }
  return { direction, width: layout.width, height: layout.height, nodes: nodes.length, edges: edges.length, labels: labels.length, issues };
}

async function main() {
  const engine = new ELK(), results = [], components = new Set(), started = Date.now();
  let textBlocks = 0, textLines = 0;
  try {
    for (const title of ["e\u0301".repeat(90), "👨‍👩‍👧‍👦".repeat(20), "العربية 日本語 Français Português", "ACCOUNT_REFERENCE_".repeat(15)]) {
      const wrapped = api.wrapText(title, 186, 15, 600);
      assert.equal(compact(wrapped.join("")), compact(title), "Grapheme and unbroken-identifier wrapping must retain every character.");
      assert(wrapped.every(line => api.measureText(line, 15, 600) <= 186), "Unicode and long-token wrapping must respect the available text width.");
    }
    for (const fixture of cases) {
      assert.equal(fixture.synthetic, true, `${fixture.id}: fixtures must be identified as fictional.`);
      assert(fixture.narrative.length > 40, `${fixture.id}: process source narrative required.`);
      const input = fixture.graph, before = JSON.stringify(input), prepared = api.model(input);
      const text = auditText(input); textBlocks += text.blocks; textLines += text.lines;
      input.steps.forEach(step => components.add(step.type));
      for (const kind of fixture.forbidden_types || []) assert(!input.steps.some(step => step.type === kind), `${fixture.id}: unknown process boundaries must remain unknown.`);
      for (const id of fixture.disconnected_ids || []) assert(!input.connections.some(edge => edge.from === id || edge.to === id), `${fixture.id}: no invented handoff for disconnected steps.`);
      for (const [from, to] of fixture.required_loops || []) assert(input.connections.some(edge => edge.from === from && edge.to === to), `${fixture.id}: explicit loop must be retained.`);
      if (fixture.merge_before_join) {
        const { merge, alternative_predecessors, join, independent_predecessors } = fixture.merge_before_join;
        assert.equal(input.steps.find(step => step.id === merge)?.type, "merge", "Either accepted route continues through an alternative merge.");
        assert.equal(input.steps.find(step => step.id === join)?.type, "parallel_join", "All independent workstreams must complete at the parallel join.");
        assert.deepEqual(input.connections.filter(edge => edge.to === merge).map(edge => edge.from).sort(), [...alternative_predecessors].sort());
        assert.deepEqual(input.connections.filter(edge => edge.to === join).map(edge => edge.from).sort(), [...independent_predecessors].sort());
        assert(!input.connections.some(edge => alternative_predecessors.includes(edge.from) && edge.to === join), "Mutually exclusive results must not become separate required arrivals at an all-branches join.");
      }
      for (const direction of ["RIGHT", "DOWN"]) {
        const layout = await engine.layout(clean(api.elkGraph(prepared, direction))), result = auditLayout(layout, input, direction);
        result.scenario = fixture.id;
        for (const route of fixture.ordered_routes || []) for (let i = 1; i < route.length; i++) {
          const a = layout.children.find(node => node.id === route[i - 1]), b = layout.children.find(node => node.id === route[i]);
          assert(direction === "RIGHT" ? a.x + a.width <= b.x + EPS : a.y + a.height <= b.y + EPS, `${fixture.id}: sequence must read in the chosen direction.`);
        }
        for (const branch of fixture.branches || []) {
          const targets = branch.targets.map(id => layout.children.find(node => node.id === id));
          assert(new Set(targets.map(node => direction === "RIGHT" ? node.y : node.x)).size > 1, `${fixture.id}: reported branches must not collapse to a single row or column.`);
        }
        results.push(result);
      }
      assert.equal(JSON.stringify(input), before, `${fixture.id}: layout must not mutate source facts.`);
    }
    assert.deepEqual([...components].sort(), ["activity", "data_store", "decision", "document", "end", "merge", "parallel_join", "parallel_split", "start", "subprocess", "wait"]);
    const report = { scenarios: cases.length, layouts: results.length, node_types: [...components].sort(), text_blocks: textBlocks, text_lines: textLines, issues: results.reduce((n, result) => n + result.issues.length, 0), duration_ms: Date.now() - started, real_elk_layout: true, real_browser: false, network_calls: 0, provider_calls: 0, results };
    const reportArg = process.argv.indexOf("--report");
    if (reportArg >= 0) { const output = path.resolve(process.argv[reportArg + 1]); fs.mkdirSync(path.dirname(output), { recursive: true }); fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n"); }
    const failures = results.filter(result => result.issues.length).map(result => ({ scenario: result.scenario, direction: result.direction, issues: result.issues }));
    console.log(JSON.stringify({ ...report, results: undefined, failures }, null, 2));
    if (!process.argv.includes("--allow-issues")) assert.equal(report.issues, 0, "Workflow scenario geometry has collisions or missing routes; see report above.");
  } finally { try { engine.terminateWorker?.(); } catch {} }
}
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { auditLayout, cases };
