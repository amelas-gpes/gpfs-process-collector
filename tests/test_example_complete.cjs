"use strict";
// Execute the actual built-in fixture and real normalizers/exporter, with the UI boundary
// stubbed. This makes no network, model or microphone calls.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
let calls = 0;
const context = {console, window:{}, document:{getElementById:()=>({value:""})},
  fetch:()=>{calls++;throw new Error("The example must not contact a provider.");},
  setTimeout:()=>0, clearTimeout:()=>{}, AbortController};
const hook = `
  canReplaceSession=()=>true;
  clearState=(context)=>{state.context=context;state.turns=[];state.draft=null;state.version=0;state.closure={asked:false,confirmed:false};state.parking_lot=[];};
  renderWorkingMap=()=>{}; renderTranscript=()=>{}; renderDraft=()=>{}; scrollConversation=()=>{}; notice=()=>{};
  window.exampleTest={loadExample,state,conversationUI,markdown,memoMarkdown,memoComplete,escapeMarkdown};
})();`;
const patched = source.replace(/  init\(\);\s*\}\)\(\);\s*$/,hook);
assert.notEqual(patched,source,"Install a test hook only at the app's initialization boundary");
vm.createContext(context);
vm.runInContext(patched,context,{filename:"app.js"});
const app = context.window.exampleTest;
app.loadExample();
const {state,conversationUI} = app;
const turns=state.turns, draft=state.draft;
const userTurns=new Set(turns.filter(t=>t.role==="user").map(t=>t.id));
const validEvidence = ids => Array.isArray(ids) && ids.some(id=>userTurns.has(id)) && ids.every(id=>id==="context"||userTurns.has(id));
const present = value => typeof value==="string" && value.trim().length>0 && !/\b(?:unknown|tbd|not established|not specified|unclear|unresolved)\b/i.test(value);
let checks=0;
assert.equal(state.example,true);assert.equal(state.started,true);assert.equal(state.closure.asked,true);assert.equal(state.closure.confirmed,true);assert.equal(calls,0);checks++;
assert(turns.length>=12,"The full interview must have multiple exchanges");
assert(turns.filter(t=>t.role==="user").length>=6);
assert(turns.filter(t=>t.role==="assistant").length>=6);
assert.equal(new Set(turns.map(t=>t.id)).size,turns.length,"Transcript IDs must be unique");
assert(turns.every(t=>typeof t.text==="string" && t.text.trim().length>0));checks++;
assert.equal(state.memo_findings.length,16);
assert.equal(new Set(state.memo_findings.map(f=>f.key)).size,16);
for(const finding of state.memo_findings){
  assert.equal(finding.status,"captured",`${finding.key} must have a full check after normalization`);
  assert(present(finding.answer),`${finding.key} needs a substantive answer`);
  assert(validEvidence(finding.evidence_turns),`${finding.key} needs a real participant source`);
}
assert.equal(app.memoComplete(),true);checks++;
assert(draft && draft.steps.length>=6,"A detailed process needs multiple steps");
assert.deepEqual(JSON.parse(JSON.stringify(draft.memo_summary)),JSON.parse(JSON.stringify(state.memo_findings)));
assert.equal(state.draftEvidence?.version,state.evidenceVersion,"The example must not open with a stale review");
assert.doesNotMatch(app.markdown(),/interview has changed since this draft/i,"The example report must not carry a stale-draft warning");checks++;
const ids=new Set(draft.steps.map(s=>s.id));assert.equal(ids.size,draft.steps.length);
assert(new Set(draft.steps.map(s=>s.type)).size>=4,"The example should demonstrate several grounded diagram components");
for(const [id,type] of Object.entries({S1:"data_store",S3:"end",S10:"document",S11:"end"}))assert.equal(draft.steps.find(step=>step.id===id).type,type);
for(const step of draft.steps){
  for(const field of ["title","actor","system","description","input","output","completion_criteria","handoff"])
    assert(present(step[field]),`${step.id}: ${field} must be fully described`);
  assert(validEvidence(step.evidence_turns),`${step.id}: exact participant evidence required`);
}
checks++;
assert(draft.connections.length>=draft.steps.length-1);
const outgoing=new Map([...ids].map(id=>[id,[]])),incoming=new Map([...ids].map(id=>[id,[]]));
for(const edge of draft.connections){
  assert(ids.has(edge.from)&&ids.has(edge.to),"Connections must reference real steps");
  assert(validEvidence(edge.evidence_turns),`${edge.from} → ${edge.to} needs participant evidence`);
  outgoing.get(edge.from).push(edge.to);incoming.get(edge.to).push(edge.from);
}
assert([...outgoing.values()].some(edges=>edges.length>1),"Include an explicit decision branch");
assert([...incoming.values()].some(edges=>edges.length>1),"Include a branch return or convergence");
const roots=[...ids].filter(id=>incoming.get(id).length===0);assert(roots.length>0,"The graph needs an entry");
const terminals=[...ids].filter(id=>outgoing.get(id).length===0);assert(terminals.length>0,"The graph needs an endpoint");
const visit=(starts,adj)=>{const seen=new Set(starts),queue=[...starts];while(queue.length){for(const next of adj.get(queue.shift()))if(!seen.has(next)){seen.add(next);queue.push(next);}}return seen;};
assert.equal(visit(roots,outgoing).size,ids.size,"Every step must be reachable from a start");
assert.equal(visit(terminals,incoming).size,ids.size,"Every step must be able to reach an endpoint");checks++;
assert(draft.lifecycle_items.length>0,"Include a documented item lifecycle");
assert(draft.variations.length>0,"Include the process variation");
for(const variation of draft.variations){for(const key of ["applies_to","difference","reason","cost","charging","removability","boundary_reason"])assert(present(variation[key]),`Variation ${key} needs detail`);assert(validEvidence(variation.evidence_turns));}
assert(draft.controls.length>0);assert(draft.exceptions.length>0);checks++;
assert.deepEqual(JSON.parse(JSON.stringify(conversationUI.workflow.steps)),JSON.parse(JSON.stringify(draft.steps)),"Live workflow and review must describe the same process");
assert.deepEqual(JSON.parse(JSON.stringify(conversationUI.workflow.connections)),JSON.parse(JSON.stringify(draft.connections)));checks++;
const markdown=app.markdown(),memo=app.memoMarkdown();
const userMarkup="Quoted words\n===\n---\n~~~html\n    # new heading\n1. link &amp; <script>";
const safe=app.escapeMarkdown(userMarkup);
assert(!/^(?:===|---|~~~|    |1\.)/m.test(safe));
assert(safe.includes("&amp;amp;"));assert(safe.includes("\\<script\\>"));checks++;
for(const heading of ["## Business context","## Topic notes","## Procedure","## Step routes","## Item lifecycles","## Variations and boundaries","## Exceptions","## Controls","## Interview evidence"])assert(markdown.includes(heading),`Export must include ${heading}`);
for(const turn of turns)assert(markdown.includes(app.escapeMarkdown(turn.text)),`Export must include complete turn ${turn.id}`);
for(const step of draft.steps){assert(markdown.includes(app.escapeMarkdown(step.title)));for(const value of [step.actor,step.system,step.input,step.output,step.completion_criteria,step.handoff])assert(markdown.includes(app.escapeMarkdown(value)),`Export missing detail from ${step.id}`);}
assert(memo.includes("## Normal route"));assert(!memo.includes("## Interview evidence"));
assert.equal(draft.open_questions.length,0,"The complete fictional example should have no remaining questions");
assert(markdown.includes("No open questions recorded."));assert(markdown.includes("No topics parked."));
assert(memo.includes("No open questions recorded; the process owner should still review the draft."));
assert.equal(calls,0);checks++;
console.log(JSON.stringify({checks_passed:checks,provider_calls:calls,voice_tests:0}));
