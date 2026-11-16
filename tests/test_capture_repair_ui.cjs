"use strict";
// A section a coverage review rewrote is announced, marked, and keeps its earlier wording
// readable. Runs the real web/app.js against a minimal DOM boundary: no browser, provider,
// audio or network is used.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));
let passed = 0, providerCalls = 0;

function dom() {
  const document = {activeElement:null, modalStack:[], listeners:{}, addEventListener(name, listener) {(this.listeners[name] ??= []).push(listener);}};
  const walk = root => [root, ...root.children.flatMap(walk)];
  const matches = (node, selector) => {
    if (selector.startsWith(".")) return node.classList.contains(selector.slice(1));
    if (selector.startsWith("#")) return node.id === selector.slice(1);
    const data = selector.match(/^\[data-([a-z-]+)(?:="([^"]*)")?\]$/);
    if (data) {
      const key = data[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      return typeof node.dataset[key] === "string" && (data[2] === undefined || node.dataset[key] === data[2]);
    }
    return /^[a-z0-9]+$/i.test(selector) && node.tagName === selector.toUpperCase();
  };
  class Element {
    constructor(tag) {
      Object.assign(this, {tagName:tag.toUpperCase(), id:"", className:"", value:"", children:[], parentElement:null, dataset:{}, style:{},
        attributes:{}, listeners:{}, _text:"", hidden:false, open:false, checked:false, disabled:false, scrollTop:0, scrollHeight:0, clientHeight:0});
      this.classList = {contains:name => this.className.split(/\s+/).includes(name), add:name => this.classList.toggle(name, true),
        remove:name => this.classList.toggle(name, false), toggle:(name, on) => {
          const values = new Set(this.className.split(/\s+/).filter(Boolean)), yes = on === undefined ? !values.has(name) : on;
          if (yes) values.add(name); else values.delete(name);
          this.className = [...values].join(" "); return yes;
        }};
    }
    get textContent() {return this._text + this.children.map(child => child.textContent).join("");}
    set textContent(value) {this.replaceChildren(); this._text = String(value);}
    get firstElementChild() {return this.children[0] || null;}
    get lastElementChild() {return this.children.at(-1) || null;}
    get isConnected() {return true;}
    remove() {if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null;}
    append(...children) {for (const child of children) {child.remove?.(); child.parentElement = this; this.children.push(child);}}
    prepend(...children) {for (const child of children.reverse()) {child.remove?.(); child.parentElement = this; this.children.unshift(child);}}
    replaceChildren(...children) {for (const child of this.children) child.parentElement = null; this.children = []; this._text = ""; this.append(...children);}
    setAttribute(name, value) {this.attributes[name] = String(value);}
    getAttribute(name) {return this.attributes[name] ?? null;}
    removeAttribute(name) {delete this.attributes[name];}
    toggleAttribute(name, on) {if (on) this.attributes[name] = ""; else delete this.attributes[name];}
    addEventListener(name, listener) {(this.listeners[name] ??= []).push(listener);}
    removeEventListener() {}
    dispatch(name) {for (const listener of this.listeners[name] || []) listener({target:this, preventDefault() {}});}
    click() {this.dispatch("click");}
    contains(target) {return target === this || this.children.some(child => child.contains(target));}
    closest(selector) {for (let node = this; node; node = node.parentElement) if (matches(node, selector)) return node; return null;}
    querySelectorAll(selector) {return walk(this).filter(node => node !== this && selector.split(",").some(part => matches(node, part.trim())));}
    querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
    focus() {document.activeElement = this;}
    blur() {}
    scrollIntoView() {}
    scrollTo() {}
    getBoundingClientRect() {return {top:0, bottom:0, left:0, right:0, width:0, height:0};}
    setSelectionRange() {}
    showModal() {this.open = true;}
    close() {this.open = false; this.dispatch("close");}
  }
  document.body = new Element("body");
  document.documentElement = new Element("html");
  document.createElement = tag => new Element(tag);
  document.createElementNS = (_, tag) => new Element(tag);
  document.createDocumentFragment = () => new Element("fragment");
  // Every element the application asks for by ID exists; tests inspect the ones they use.
  document.getElementById = id => walk(document.body).find(node => node.id === id) || (() => {
    const node = new Element(["foundation-dialog", "memo-sheet", "interview-settings"].includes(id) ? "dialog" : "div");
    node.id = id; document.body.append(node); return node;
  })();
  document.querySelectorAll = selector => walk(document.body).filter(node => selector.split(",").some(part => matches(node, part.trim())));
  document.querySelector = selector => document.querySelectorAll(selector)[0] || null;
  // Controls whose label lives in a child element.
  for (const id of ["start-live", "interview-error", "review-error"]) document.getElementById(id).append(new Element("span"));
  return {document, Element, walk};
}

function harness() {
  const {document, walk} = dom(), notices = [];
  const scope = {console, document, Date, JSON, AbortController, DOMException, TextEncoder, Blob, URL,
    window:{speechSynthesis:{cancel() {}}, matchMedia:() => ({matches:false, addEventListener() {}})},
    confirm:() => true, requestAnimationFrame:fn => fn(), setTimeout:() => 0, clearTimeout() {},
    getComputedStyle:() => ({}), fetch:() => {providerCalls++; throw Error("Capture repair UI checks stay local.");},
    captureNotice:(...args) => notices.push(args)};
  const hook = `
    const realNotice=notice;
    notice=(...args)=>{captureNotice(...args);return realNotice(...args);};
    updateControls=()=>{};
    window.repairTest={state,conversationUI,TOPICS,MEMO_HEADINGS,normalizeFindings,normalizeDraft,normalizeRepairs,reviewedRepairs,acceptRepairs,
      repairSummary,repairNote,renderCoverage,showFoundationTopic,closeFoundationTopic,applyInterview,renderMemo,renderReport,generateDraft,
      sessionObject,importSession,transcriptObject,transcriptMarkdown,clearState,markdown,memoMarkdown,setRequest:fn=>{request=fn;}};
  })();`;
  const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/, hook);
  assert.notEqual(patched, source, "Install a test hook only at application initialization");
  vm.createContext(scope); vm.runInContext(patched, scope, {filename:"app.js"});
  const app = scope.window.repairTest;
  // The background pre-check after an ordinary capture has no server here.
  app.setRequest(async () => {throw new Error("No server in this check.");});
  app.state.context ={process_name:"Invoice intake", process_owner:"AP manager", objective:"Understand actual work", background:""};
  app.state.config = {version:"test-version", api_configured:true, agent_team:{enabled:true}};
  app.state.started = true;
  app.state.turns = [{id:"t001", role:"assistant", text:"How does an invoice move through intake?"},
    {id:"t002", role:"user", text:"The analyst logs each invoice as Received and marks it Checked or Hold. A duplicate is linked and closed. Other invoices go by queue link to Treasury, which records Accepted. A held invoice returns to checking after supplier correction."},
    {id:"t003", role:"assistant", text:"Who approves the amount?"},
    {id:"t004", role:"user", text:"The AP manager reviews the amount and records approval in the register before release."}];
  return {app, document, notices, walk, byId:id => document.getElementById(id)};
}
function check(name, fn) {
  const run = async () => {try {await fn(); passed++;} catch (error) {error.message = name + ": " + error.message; throw error;}};
  queue = queue.then(run);
}
let queue = Promise.resolve();

const LEAD = ["The analyst logs each invoice as Received and marks it Checked or Hold.", "A duplicate is linked and closed.",
  "Other invoices go by queue link to Treasury, which records Accepted.", "A held invoice returns to checking after supplier correction."];
const SHORT = "The analyst logs and checks each invoice, then sends it to Treasury.";
function findings(app, lifecycle, status = "captured") {
  return app.TOPICS.map(([key]) => key === "lifecycle" ? {key, status, answer:lifecycle, evidence_turns:["t002"]}
    : key === "checks" ? {key, status:"captured", answer:"The AP manager reviews the amount and records approval in the register before release.", evidence_turns:["t004"]}
    : {key, status:"captured", answer:`The participant described ${key} in the interview.`, evidence_turns:["t002"]});
}
function reviewResult(app, {answer = SHORT, repairs, kind = "final_check", status = "captured"} = {}) {
  const question = "Before we finish, is there anything else someone doing this work needs to know that we haven't captured?";
  return {question, summary:"Invoice intake.", focus:"Final check", parking_lot:[], memo_findings:findings(app, answer, status),
    coverage:app.TOPICS.map(([key, label]) => ({key, label, status:"covered"})), closure:{asked:true, confirmed:false},
    coverage_verified:true, completion:{ready_for_final_check:true, complete:false}, capture_token:"capture-token",
    speech_authorization:{approved:true, kind, text:question},
    coverage_assessment:{all_topics_covered:true, topics:[], capture_repairs:repairs === undefined ? [
      {key:"lifecycle", answer, evidence_turns:["t002"], previous_answer:LEAD.join("\n"), previous_evidence_turns:["t002"]}] : repairs}};
}
function captureResult(app, lifecycle) {
  const question = "What else happens to a held invoice?";
  return {question, summary:"Invoice intake.", focus:"Holds", parking_lot:[], memo_findings:findings(app, lifecycle),
    coverage:app.TOPICS.map(([key, label]) => ({key, label, status:"partial"})), closure:{asked:false, confirmed:false},
    coverage_verified:false, completion:null, capture_token:"capture-token-2", speech_authorization:{approved:true, kind:"question", text:question}};
}
const lifecycleButton = document => document.querySelector('[data-foundation-topic="lifecycle"]');

check("the record of a rewritten section is validated before it is kept", () => {
  const {app} = harness(), memo = app.normalizeFindings(findings(app, SHORT), app.state.turns, []);
  const entry = {key:"lifecycle", answer:SHORT, evidence_turns:["t002"], previous_answer:LEAD.join("\n"), previous_evidence_turns:["t002", "t_removed"]};
  assert.deepEqual(plain(app.normalizeRepairs([entry], memo, app.state.turns, [])),
    {lifecycle:{key:"lifecycle", answer:SHORT, previous_answer:LEAD.join("\n"), previous_evidence_turns:["t002"]}},
    "An earlier source that is no longer available is dropped; the earlier wording is kept");
  assert.deepEqual(plain(app.normalizeRepairs(undefined, memo, app.state.turns, [])), {});
  for (const [label, value] of [["not a list", {lifecycle:entry}], ["unknown topic", [{...entry, key:"made_up"}]], ["duplicate", [entry, entry]],
      ["no earlier text", [{...entry, previous_answer:undefined}]], ["answer not text", [{...entry, answer:7}]],
      ["sources not a list", [{...entry, previous_evidence_turns:"t002"}]], ["oversized earlier text", [{...entry, previous_answer:"x".repeat(12001)}]],
      ["too many", Array.from({length:17}, () => entry)]])
    assert.throws(() => app.normalizeRepairs(value, memo, app.state.turns, []), /rewritten section|supported/, label);
  assert.equal(app.reviewedRepairs({coverage_assessment:{review_available:false, capture_repairs:[entry]}}, memo, app.state.turns, []), null);
  assert.equal(app.reviewedRepairs({coverage_assessment:{topics:[]}}, memo, app.state.turns, []), null, "An assessment that cannot repair carries no record");
  assert.equal(app.reviewedRepairs({}, memo, app.state.turns, []), null);
  assert.equal(LEAD.join("\n").length, 236);
  assert.equal(app.repairSummary({answer:SHORT, previous_answer:LEAD.join("\n")}), "0 of 4 earlier statements kept word for word; 236 → 68 characters.");
  assert.match(app.repairSummary({answer:[LEAD[0], LEAD[1], "Other invoices go to Treasury.", LEAD[3]].join(" "), previous_answer:LEAD.join("\n")}), /^3 of 4 earlier statements kept/);
});

check("a review that rewrites a section says so, marks the section and keeps the earlier notes", () => {
  const {app, document, notices, byId} = harness();
  app.applyInterview(reviewResult(app));
  assert.deepEqual(Object.keys(app.state.captureRepairs.memo), ["lifecycle"]);
  const announced = notices.map(args => args[0]).filter(message => /rewrote/.test(message));
  assert.equal(announced.length, 1);
  const listLabel = app.TOPICS.find(([key]) => key === "lifecycle")[1];
  assert.equal(announced[0], `The completion review rewrote a section: ${listLabel}. Open it to compare with your earlier notes.`,
    "The notice keeps the readiness message and uses the name shown in the notes list");
  assert.equal(byId("notice-text").textContent, announced[0]);
  const item = lifecycleButton(document);
  assert.ok(item.classList.contains("rewritten"));
  assert.match(item.getAttribute("aria-label"), /rewritten by the completion review, earlier notes kept$/);
  assert.equal(document.querySelectorAll(".coverage-item").filter(node => node.classList.contains("rewritten")).length, 1);
  assert.equal(byId("coverage-summary").hidden, false);
  assert.equal(byId("coverage-summary").textContent, "All topics covered · 1 rewritten by the review");
  app.showFoundationTopic("lifecycle", item);
  assert.equal(byId("foundation-topic-answer").textContent, SHORT);
  const panel = byId("foundation-topic-repair");
  assert.equal(panel.hidden, false);
  assert.match(panel.querySelector(".repair-note-lead").textContent, /^Rewritten by the completion review\. 0 of 4 earlier statements kept word for word; 236 → 68 characters\.$/);
  const earlier = panel.querySelector("details");
  assert.equal(earlier.querySelector("summary").textContent, "Notes before the completion review");
  assert.equal(earlier.querySelector(".repair-earlier-text").textContent, LEAD.join("\n"));
  assert.equal(earlier.querySelectorAll(".evidence-link").length, 1);
  assert.equal(earlier.querySelector(".text-button"), null, "Interview notes belong to the server; no local restore is offered");
  // Reading the earlier notes survives a re-render of the open dialog.
  earlier.open = true; app.renderCoverage();
  assert.equal(byId("foundation-topic-repair").querySelector("details").open, true);
  app.showFoundationTopic("checks", document.querySelector('[data-foundation-topic="checks"]'));
  assert.equal(byId("foundation-topic-repair").hidden, true, "A section the review left alone shows no notice");
  assert.equal(byId("foundation-topic-repair").children.length, 0);
});

check("the earlier notes stay on record while the section is the rewrite, and across later answers", () => {
  const {app, document, notices, byId} = harness();
  app.applyInterview(reviewResult(app));
  // The server reassembles a section one statement per line: still the same rewrite.
  app.applyInterview(captureResult(app, SHORT));
  assert.deepEqual(Object.keys(app.state.captureRepairs.memo), ["lifecycle"]);
  app.showFoundationTopic("lifecycle", lifecycleButton(document));
  assert.doesNotMatch(byId("foundation-topic-repair").textContent, /changed again/);
  // The lead adds to the rewritten section: the earlier notes remain readable.
  app.applyInterview(captureResult(app, SHORT + "\nA held invoice waits for the supplier."));
  app.showFoundationTopic("lifecycle", lifecycleButton(document));
  assert.match(byId("foundation-topic-repair").querySelector(".repair-note-lead").textContent, /This section has changed again since\.$/);
  assert.equal(byId("foundation-topic-repair").querySelector(".repair-earlier-text").textContent, LEAD.join("\n"));
  assert.equal(notices.filter(args => /rewrote/.test(args[0])).length, 1, "Only the review that rewrote the section announces it");
});

check("a later review replaces the record; one that leaves a changed section alone clears it", () => {
  const {app, notices} = harness();
  app.applyInterview(reviewResult(app));
  // The same reviewed result again (for example the confirmation that reuses it) is not a new rewrite.
  app.applyInterview(reviewResult(app));
  assert.equal(notices.filter(args => /rewrote/.test(args[0])).length, 1);
  // A later review that rewrites nothing: the section still reads as the earlier rewrite.
  app.applyInterview(reviewResult(app, {repairs:[]}));
  assert.deepEqual(Object.keys(app.state.captureRepairs.memo), ["lifecycle"]);
  // A retried review that did not repair returns the lead's own text: nothing was rewritten.
  app.applyInterview(reviewResult(app, {answer:LEAD.join("\n"), repairs:[]}));
  assert.deepEqual(Object.keys(app.state.captureRepairs.memo), []);
  app.applyInterview(reviewResult(app));
  assert.equal(notices.filter(args => /rewrote/.test(args[0])).length, 2);
  app.clearState(app.state.context);
  assert.deepEqual(plain(app.state.captureRepairs), {memo:{}, draft:{}});
});

check("a repair the process review did not clear changed nothing, so nothing is marked or announced", () => {
  const {app, document, notices, byId} = harness();
  const result = reviewResult(app, {answer:LEAD.join("\n"), status:"partial", kind:"question",
    repairs:[{key:"lifecycle", answer:SHORT, evidence_turns:["t002"], previous_answer:LEAD.join("\n"), previous_evidence_turns:["t002"]}]});
  result.question = "Who releases each invoice to Treasury?"; result.speech_authorization.text = result.question;
  result.completion = {ready_for_final_check:false, complete:false}; result.closure = {asked:false, confirmed:false};
  result.coverage_adjudication = {withdrawn_repairs:["lifecycle"], unconfirmed_topics:["lifecycle"], process_finding_ids:["P1"], reason:"Open."};
  app.applyInterview(result);
  assert.deepEqual(plain(app.state.captureRepairs.memo), {});
  assert.equal(notices.filter(args => /rewrote/.test(args[0])).length, 0);
  assert.equal(lifecycleButton(document).classList.contains("rewritten"), false);
  app.showFoundationTopic("lifecycle", lifecycleButton(document));
  assert.equal(byId("foundation-topic-answer").textContent, LEAD.join("\n"));
  assert.equal(byId("foundation-topic-repair").hidden, true);
});

check("an invalid rewrite record rejects the result before the notes or transcript change", () => {
  const {app} = harness();
  const kept = () => JSON.stringify([app.state.turns, app.state.memo_findings, app.state.coverage, app.state.captureRepairs]);
  const before = kept();
  assert.throws(() => app.applyInterview(reviewResult(app, {repairs:[{key:"lifecycle", answer:SHORT}]})), /rewritten section/);
  assert.equal(kept(), before);
});

check("the transcript export carries the earlier notes of a rewritten section only", () => {
  const {app} = harness();
  app.applyInterview(reviewResult(app));
  const data = app.transcriptObject(), lifecycle = data.memo.topics.find(topic => topic.key === "lifecycle");
  assert.deepEqual(plain(lifecycle.review_rewrite), {previous_answer:LEAD.join("\n"), previous_evidence_turn_ids:["t002"]});
  assert.equal(data.memo.topics.filter(topic => "review_rewrite" in topic).length, 1);
  const markdown = app.transcriptMarkdown(data);
  assert.match(markdown, /notes before the completion review rewrote this section/);
  assert.ok(markdown.includes(LEAD.join("\n")));
});

const draftFixture = app => ({title:"Invoice intake", overview:"Draft.", trigger:"An invoice email.", inputs:[], outputs:[],
  steps:[{id:"s1", title:"Log invoice", type:"activity", actor:"Analyst", system:"AP register", description:"Log the invoice.", evidence_turns:["t002"]}],
  connections:[], exceptions:[], controls:[], open_questions:[],
  validation_notes:["The coverage review rewrote this memo section to match the interview evidence: Items, stages & handoffs. The new wording was not checked by a process review, so it is marked partial; compare it with the interview before approval."],
  memo_summary:findings(app, SHORT, "partial"), variations:[], lifecycle_items:[], taxonomy:[], connections_out:[]});
const draftRepairs = [{key:"lifecycle", answer:SHORT, evidence_turns:["t002"], previous_answer:LEAD.join(" "), previous_evidence_turns:["t002"]}];

check("a report section the coverage review rewrote shows the notice and can take its earlier wording back", async () => {
  const {app, notices, byId} = harness();
  app.setRequest(async () => ({draft:draftFixture(app), coverage_assessment:{topics:[], capture_repairs:draftRepairs}}));
  await app.generateDraft();
  assert.ok(app.state.draft, notices.map(args => args[0]).join(" | "));
  assert.deepEqual(Object.keys(app.state.captureRepairs.draft), ["lifecycle"]);
  assert.deepEqual(plain(app.state.captureRepairs.memo), {}, "A draft's rewrite is separate from the interview notes");
  assert.match(notices.at(-1)[0], /^Your draft is ready\. The coverage review rewrote a memo section \(.+\); it is marked partial with the earlier wording kept\.$/);
  app.renderReport();
  const sections = byId("report-content").querySelectorAll(".report-finding");
  assert.equal(sections.length, app.TOPICS.length);
  const rewritten = sections.filter(section => section.querySelector(".repair-note"));
  assert.equal(rewritten.length, 1);
  assert.match(rewritten[0].querySelector(".repair-note-lead").textContent, /^Rewritten by the coverage review\. 0 of 4 earlier statements kept/);
  assert.equal(rewritten[0].querySelector("summary").textContent, "Wording before the coverage review");
  assert.equal(rewritten[0].querySelector(".repair-earlier-text").textContent, LEAD.join(" "));
  assert.equal(rewritten[0].querySelector(".text-button"), null, "The read-only report offers no edit");
  app.renderMemo();
  const editor = byId("memo-summary").querySelectorAll(".memo-finding").find(item => item.querySelector(".repair-note"));
  assert.equal(editor.querySelector(".memo-rewritten").textContent, "Rewritten by review");
  const restore = editor.querySelector(".repair-note").querySelector(".text-button");
  assert.equal(restore.textContent, "Use the earlier wording");
  restore.click();
  const section = app.state.draft.memo_summary.find(item => item.key === "lifecycle");
  assert.equal(section.answer, LEAD.join(" "));
  assert.deepEqual(plain(section.evidence_turns), ["t002"]);
  assert.equal(section.status, "partial", "Restoring wording does not promote the section");
  assert.deepEqual(plain(app.state.captureRepairs.draft), {});
  assert.equal(app.state.draftEdited, true);
  assert.equal(byId("memo-summary").querySelectorAll(".repair-note").length, 0);
  assert.equal(byId("report-content").querySelectorAll(".repair-note").length, 0);
  assert.match(notices.at(-1)[0], /^Earlier wording restored for /);
});

check("a draft without a rewrite keeps its ordinary notice and shows no marker", async () => {
  const {app, notices, byId} = harness();
  app.setRequest(async () => ({draft:draftFixture(app), coverage_assessment:{topics:[], capture_repairs:[]}}));
  await app.generateDraft();
  assert.equal(notices.at(-1)[0], "Your draft is ready. Check the steps and open questions.");
  app.renderReport(); app.renderMemo();
  assert.equal(byId("report-content").querySelectorAll(".repair-note").length, 0);
  assert.equal(byId("memo-summary").querySelectorAll(".memo-rewritten").length, 0);
});

// agent-team-coverage-13: the draft's own coverage review decides how its memo statuses read.
const LIMITATION = "Coverage review could not be completed; full coverage is unconfirmed.";
const unreviewedDraft = app => {
  // What the server returns when the draft's coverage call fails: every captured section is
  // partial, and the assessment beside the draft names them.
  const draft = draftFixture(app);
  draft.validation_notes = [];
  draft.memo_summary = findings(app, SHORT, "captured").map(finding => ({...finding, status:finding.key === "volume" ? "unknown" : "partial"}));
  const unconfirmed = app.TOPICS.map(([key]) => key).filter(key => !["volume", "risk"].includes(key));
  return {draft, coverage_assessment:{all_topics_covered:false, review_available:false, unconfirmed_topics:unconfirmed, topics:[], limitation:LIMITATION}};
};

check("a draft whose coverage review could not run says so, marks the sections it held back and offers a retry", async () => {
  const {app, notices, byId} = harness();
  let calls = 0;
  app.state.coverageVerified = true; // the interview itself was fully verified
  app.setRequest(async () => {calls++; return unreviewedDraft(app);});
  await app.generateDraft();
  assert.ok(app.state.draft, notices.map(args => args[0]).join(" | "));
  assert.equal(notices.at(-1)[0], "Your draft is ready, but its coverage review could not be completed: 14 memo sections are marked partial until it is. Open Notes in Review to try the review again.");
  assert.equal(app.state.draftCoverage.limitation, LIMITATION);
  assert.equal(app.state.draftCoverage.unconfirmed.length, 14);
  app.renderMemo(); app.renderReport();
  const note = byId("memo-summary").querySelector(".draft-coverage-note");
  assert.match(note.textContent, /^Coverage review could not be completed; full coverage is unconfirmed\. 14 sections that were captured are shown as in progress because the review did not run, not because anything is missing\./);
  const badges = byId("memo-summary").querySelectorAll(".memo-status");
  assert.equal(badges.filter(badge => badge.textContent === "In progress · coverage review unavailable").length, 14);
  // A section the server did not hold back reads as its own status: "risk" was partial before the review.
  const keys = app.TOPICS.map(([key]) => key);
  assert.equal(badges[keys.indexOf("risk")].textContent, "In progress");
  assert.equal(badges[keys.indexOf("volume")].textContent, "Unknown");
  const report = byId("report-content");
  assert.ok(report.querySelectorAll(".report-warning").some(item => item.textContent.startsWith(LIMITATION)));
  const statuses = report.querySelectorAll(".report-finding-status").map(item => item.textContent);
  assert.equal(statuses.filter(value => value === "In progress · coverage review unavailable").length, 14);
  assert.equal(statuses[keys.indexOf("risk")], "In progress");
  // Each export lists each memo section once.
  for (const [exported, times] of [[app.markdown(), 1], [app.memoMarkdown(), 1]]) {
    assert.ok(exported.includes("**Coverage review could not be completed; full coverage is unconfirmed.**"), exported.slice(0, 300));
    assert.equal(exported.split("Status: In progress · coverage review unavailable").length - 1, 14 * times);
    assert.equal(exported.split("Status: In progress\n").length - 1, times, "risk was partial before the review");
  }
  // A status the reviewer of the draft sets by hand is that person's own, with no qualifier.
  const select = byId("memo-summary").querySelectorAll(".memo-finding")[keys.indexOf("purpose")].querySelector("select");
  select.value = "captured"; select.dispatch("change");
  assert.equal(badges[keys.indexOf("purpose")].textContent, "Covered");
  select.value = "partial"; select.dispatch("change");
  assert.equal(badges[keys.indexOf("purpose")].textContent, "In progress · coverage review unavailable");
  // The retry runs the draft again; a review that now finishes clears the note and the qualifiers.
  app.setRequest(async () => {calls++; return {draft:{...draftFixture(app), validation_notes:[], memo_summary:findings(app, SHORT, "captured")},
    coverage_assessment:{all_topics_covered:true, topics:[], capture_repairs:[]}};});
  const retry = note.querySelector(".text-button");
  assert.equal(retry.textContent, "Update draft to try the review again");
  retry.click();
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2);
  assert.equal(app.state.draftCoverage, null);
  assert.equal(notices.at(-1)[0], "Your draft is ready. Check the steps and open questions.");
  assert.equal(byId("memo-summary").querySelector(".draft-coverage-note"), null);
  assert.equal(byId("memo-summary").querySelectorAll(".memo-status").filter(badge => badge.textContent === "Covered").length, app.TOPICS.length-1);
  assert.equal(byId("report-content").querySelectorAll(".report-warning").some(item => item.textContent.startsWith(LIMITATION)), false);
});

check("a reviewed draft reads by its own statuses while the interview is still awaiting its review", async () => {
  const {app, byId} = harness();
  app.state.coverageVerified = false; // the interview's completion review has not run
  app.setRequest(async () => ({draft:{...draftFixture(app), validation_notes:[], memo_summary:findings(app, SHORT, "captured")},
    coverage_assessment:{all_topics_covered:true, topics:[], capture_repairs:[]}}));
  await app.generateDraft();
  assert.equal(app.state.draftCoverage, null);
  app.renderMemo(); app.renderReport();
  assert.equal(byId("memo-summary").querySelectorAll(".memo-status").filter(badge => badge.textContent === "Covered").length, app.TOPICS.length);
  assert.equal(byId("memo-summary").querySelector(".draft-coverage-note"), null);
  assert.equal(byId("report-content").querySelectorAll(".report-finding-status").filter(item => item.textContent === "Covered").length, app.TOPICS.length);
  for (const exported of [app.markdown(), app.memoMarkdown()]) assert.doesNotMatch(exported, /awaiting review|review unavailable/);
});

check("a malformed record of the failed review does not replace the draft on screen", async () => {
  const {app, notices} = harness();
  app.setRequest(async () => ({...unreviewedDraft(app), coverage_assessment:{review_available:false, unconfirmed_topics:[7], limitation:LIMITATION}}));
  await app.generateDraft();
  assert.equal(app.state.draft, null);
  assert.equal(notices.at(-1)[1], true, "The failure is shown as an error");
  // Unknown topic names are dropped, and a missing limitation falls back to the fixed sentence.
  const second = harness();
  second.app.setRequest(async () => ({...unreviewedDraft(second.app), coverage_assessment:{review_available:false, unconfirmed_topics:["purpose", "no_such_topic", "purpose"]}}));
  await second.app.generateDraft();
  assert.deepEqual(plain(second.app.state.draftCoverage), {limitation:LIMITATION, unconfirmed:["purpose"]});
  // Starting over forgets the record.
  second.app.clearState(second.app.state.context);
  assert.equal(second.app.state.draftCoverage, null);
});

check("a saved interview keeps both records and reopens with them", async () => {
  const {app, notices} = harness();
  app.applyInterview(reviewResult(app));
  app.setRequest(async () => ({draft:draftFixture(app), coverage_assessment:{topics:[], capture_repairs:draftRepairs}}));
  await app.generateDraft();
  const saved = plain(app.sessionObject());
  assert.deepEqual(saved.capture_repairs, {
    memo:[{key:"lifecycle", answer:SHORT, previous_answer:LEAD.join("\n"), previous_evidence_turns:["t002"]}],
    draft:[{key:"lifecycle", answer:SHORT, previous_answer:LEAD.join(" "), previous_evidence_turns:["t002"]}]});
  const reopened = harness();
  await reopened.app.importSession({size:10, text:async () => JSON.stringify(saved)});
  assert.equal(reopened.app.state.turns.length, saved.turns.length, reopened.notices.map(args => args[0]).join(" | "));
  assert.deepEqual(plain(reopened.app.state.captureRepairs), {
    memo:{lifecycle:saved.capture_repairs.memo[0]}, draft:{lifecycle:saved.capture_repairs.draft[0]}});
  // A file saved before this record existed still opens.
  const older = harness(), legacy = {...saved}; delete legacy.capture_repairs;
  await older.app.importSession({size:10, text:async () => JSON.stringify(legacy)});
  assert.equal(older.app.state.turns.length, saved.turns.length, older.notices.map(args => args[0]).join(" | "));
  assert.deepEqual(plain(older.app.state.captureRepairs), {memo:{}, draft:{}});
  // A damaged record does not replace the open interview.
  const damaged = harness();
  await damaged.app.importSession({size:10, text:async () => JSON.stringify({...saved, capture_repairs:{memo:[{key:"lifecycle"}], draft:[]}})});
  assert.match(damaged.notices.at(-1)[0], /^Couldn’t open that interview\. .*rewritten section/);
  assert.equal(damaged.app.state.memo_findings.length, 0, "The open interview is left as it was");
  assert.equal(damaged.app.state.draft, null);
  assert.equal(notices.length > 0, true);
});

queue.then(() => {
  assert.equal(providerCalls, 0);
  console.log(JSON.stringify({tests_passed:passed, provider_calls:providerCalls, voice_tests:0}));
}).catch(error => {console.error(error); process.exit(1);});
