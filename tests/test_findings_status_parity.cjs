"use strict";
// The browser shows the status the server validated for a memo finding. The cases are the ones
// tests/test_completeness_literals.py puts through server.validate_findings, recorded with the
// server's status in tests/fixtures/completeness_literal_cases.json (tests/test_findings_status_parity.py
// holds that file to the server). Here the same findings go through the browser's own
// normalizeFindings (the memo-normalization slice of web/app.js) and must come out with that status.
// Offline: no provider, DOM or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const {cases} = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'completeness_literal_cases.json'), 'utf8'));
const topicsStart = source.indexOf('  const TOPICS = [');
const topicsEnd = source.indexOf('  const MEMO_HEADINGS', topicsStart);
const start = source.indexOf('  function evidenceSources(');
const end = source.indexOf('  function normalizeDraft(', start);
assert(topicsStart >= 0 && topicsEnd > topicsStart && start >= 0 && end > start, 'Memo normalization must exist');
const scope = {state: {documentEvidence: []},
  strings: (value, limit) => Array.isArray(value) ? value.slice(0, limit).filter(v => typeof v === 'string') : [],
  text: (value, limit) => typeof value === 'string' ? value.trim().slice(0, limit) : ''};
scope.reviewReferences=()=>[];
vm.createContext(scope);
vm.runInContext(source.slice(topicsStart, topicsEnd) + source.slice(start, end) +
  '\nthis.TOPICS = TOPICS; this.normalizeFindings = normalizeFindings;', scope);
let passed = 0;

// The interview the server suite uses: two earlier answers and the answer that carries the case.
function shown(key, answer, sourceKind) {
  const turns = [{id: 'u1', role: 'user', text: 'The clerk logs invoices.'}, {id: 'u2', role: 'user', text: 'The manager approves by email.'},
    {id: 'u_literal', role: 'user', text: answer}];
  const documents = sourceKind === 'document' ? [{id: 'doc_literal', document_id: 'doc', name: 'Procedure.pdf', label: 'page 1', text: answer}] : [];
  const findings = scope.TOPICS.map(([topic]) => ({key: topic, status: 'captured', answer: 'The clerk logs each invoice in the register.', evidence_turns: ['u1']}));
  Object.assign(findings.find(finding => finding.key === key), {answer, evidence_turns: [sourceKind === 'document' ? 'doc_literal' : 'u_literal']});
  const result = scope.normalizeFindings(findings, turns, documents);
  const others = result.filter(finding => finding.key !== key);
  assert.ok(others.every(finding => finding.status === 'captured'), 'Only the finding under test may change');
  return {status: result.find(finding => finding.key === key).status,
    complete: result.length === 16 && result.every(finding => ['captured', 'not_applicable'].includes(finding.status))};
}

assert.ok(cases.length >= 25, 'The fixture carries the literal suite');
const disagreements = [];
for (const [key, answer, status, sourceKind] of cases) {
  assert.ok(scope.TOPICS.some(([topic]) => topic === key), `Unknown topic ${key}`);
  const browser = shown(key, answer, sourceKind);
  if (browser.status !== status) disagreements.push(`[${key}] server=${status} browser=${browser.status}: ${answer}`);
  else {
    // A finding the server accepted leaves the memo complete; one it held does not.
    assert.equal(browser.complete, status === 'captured', `[${key}] ${answer}`);
    passed++;
  }
}
assert.deepEqual(disagreements, [], 'The browser shows the status the server validated');

// The four findings of the audit's reproduction, together in one memo as the server returned them.
const audit = {lifecycle: 'The analyst records the literal value UNKNOWN in the Stage column before the reviewer changes it to Approved.',
  checks: "When the invoice and order contain conflicting amounts, the reviewer holds release, obtains the buyer's corrected order, reruns the comparison and records Pass before release.",
  risk: 'If an incorrect payment file is released, the fund might pay the wrong amount and need a corrected transfer.',
  materials: "The team retains the disagreement log with each disputed amount, the controller's resolution, the source schedule and the final review timestamp in the event folder."};
for (const [key, answer] of Object.entries(audit)) assert.ok(cases.some(row => row[0] === key && row[1] === answer && row[2] === 'captured'), `The audit's ${key} finding is in the fixture`);
const turns = [{id: 'u1', role: 'user', text: 'Synthetic participant account.'}];
const memo = scope.normalizeFindings(scope.TOPICS.map(([topic]) => ({key: topic, status: 'captured', answer: audit[topic] || 'The clerk logs each invoice in the register.', evidence_turns: ['u1']})), turns, []);
// (Copied out of the evaluation context: its arrays have another realm's prototype.)
assert.deepEqual(Array.from(memo).filter(finding => finding.status !== 'captured').map(finding => finding.key), [], 'Nothing the server captured is shown as partial');
passed++;

// The browser never promotes: a status the server held stays held whatever the wording.
for (const status of ['partial', 'unknown']) {
  const held = scope.normalizeFindings(scope.TOPICS.map(([topic]) => ({key: topic, status: topic === 'checks' ? status : 'captured', answer: 'The controller approves the notice.', evidence_turns: ['u1']})), turns, []);
  assert.equal(held.find(finding => finding.key === 'checks').status, status);
  passed++;
}

console.log(JSON.stringify({checks_passed: passed, cases: cases.length, provider_calls: 0, network_calls: 0}));
