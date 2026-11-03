// Focused offline coverage checks; does not start voice or contact a provider.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const start = source.indexOf('  function evidenceSources(');
const end = source.indexOf('  function normalizeDraft(', start);
assert(start >= 0 && end > start, 'Memo normalization must exist');
const scope = {TOPICS: [['accountable', 'Accountable owner']],
  strings: (value, limit) => Array.isArray(value) ? value.slice(0, limit).filter(v => typeof v === 'string') : [],
  text: (value, limit) => typeof value === 'string' ? value.trim().slice(0, limit) : ''};
vm.createContext(scope);
vm.runInContext(source.slice(start, end) + '\nthis.normalizeFindings = normalizeFindings;', scope);
const findings = [{key: 'accountable', status: 'captured', answer: 'The controller owns it.', evidence_turns: ['u1']}];
const turns = [{id:'u1', role:'user', text:'I am not sure who owns it.'},
               {id:'u2', role:'user', text:'I checked: the controller owns it.'}];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
turns[0].text = 'I cannot identify the final accountable owner yet.';
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
turns[0].text = 'I am unable to identify the final accountable owner.';
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
findings[0].evidence_turns = ['u2'];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'captured');
findings[0].answer = 'The controller probably owns it.';
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
findings[0].answer = 'The controller owns it.'; findings[0].evidence_turns = [];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
const gapStart=source.indexOf('  function workflowGapSummary(');
const gapEnd=source.indexOf('  function renderWorkingMap(', gapStart);
assert(gapStart >= 0 && gapEnd > gapStart, 'Workflow gap summary must exist');
vm.runInContext(source.slice(gapStart, gapEnd) + '\nthis.workflowGapSummary = workflowGapSummary;', scope);
const flow={steps:[{id:'S1',title:'Receive'},{id:'S2',title:'Approve'},{id:'S3',title:'Resolve exception'}],connections:[{from:'S1',to:'S2'},{from:'S3',to:'S3'}]};
assert.match(scope.workflowGapSummary(flow), /Resolve exception \(S3\)/);
flow.connections.push({from:'S2',to:'S3'});
assert.equal(scope.workflowGapSummary(flow), '');
assert.equal(scope.workflowGapSummary({steps:[{id:'S1'}],connections:[]}), '');
console.log(JSON.stringify({tests_passed: 9, provider_calls: 0, voice_tests: 0}));
