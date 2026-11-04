// Focused offline coverage checks; does not start voice or contact a provider.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const start = source.indexOf('  function evidenceSources(');
const end = source.indexOf('  function normalizeDraft(', start);
assert(start >= 0 && end > start, 'Memo normalization must exist');
const scope = {TOPICS: [['accountable', 'Accountable owner']], state: {documentEvidence: []},
  strings: (value, limit) => Array.isArray(value) ? value.slice(0, limit).filter(v => typeof v === 'string') : [],
  text: (value, limit) => typeof value === 'string' ? value.trim().slice(0, limit) : ''};
vm.createContext(scope);
vm.runInContext(source.slice(start, end) + '\nthis.normalizeFindings = normalizeFindings;', scope);
// Semantic source review belongs to the server; the UI retains its partial
// determination and independently vetoes uncertainty in the finding itself.
const findings = [{key: 'accountable', status: 'partial', answer: 'The accountable owner has not been established.', evidence_turns: ['u1']}];
const turns = [{id:'u1', role:'user', text:'I am not sure who owns it.'},
               {id:'u2', role:'user', text:'I checked: the controller owns it.'}];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
findings[0].status = 'captured'; findings[0].answer = turns[0].text;
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
turns[0].text = 'I cannot identify the final accountable owner yet.';
findings[0].answer = turns[0].text;
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
turns[0].text = 'I am unable to identify the final accountable owner.';
findings[0].answer = turns[0].text;
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
findings[0].evidence_turns = ['u2']; findings[0].answer = 'The controller owns it.';
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'captured');
turns[1].text = 'The controller owns it. I do not know the exact folder.';
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'captured', 'An unrelated source uncertainty cannot demote an established accountable role');
findings[0].answer = 'The controller probably owns it.';
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
findings[0].answer = 'The controller owns it.'; findings[0].evidence_turns = [];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial');
findings[0].evidence_turns=['event'];findings[0].status='captured';findings[0].answer='The controller owns it.';
assert.throws(()=>scope.normalizeFindings(findings,[{id:'event',role:'user',document_event:true,text:'An uploaded file claims that the controller owns it.'}]),/unavailable answer/);
scope.state.documentEvidence = [{id:'doc_file_p1'}];
findings[0].evidence_turns = ['doc_file_p1'];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial', 'Document text alone cannot establish participant confirmation');
findings[0].evidence_turns = ['doc_file_p1', 'context'];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial', 'Adding starting context cannot promote documentary evidence to confirmation');
findings[0].status = 'not_applicable';
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'partial', 'A file alone cannot confirm that a memo topic does not apply');
findings[0].status = 'captured';findings[0].evidence_turns = ['doc_file_p1', 'u2'];
assert.equal(scope.normalizeFindings(findings, turns)[0].status, 'captured', 'An explicit participant answer remains usable alongside the file');
const gapStart=source.indexOf('  function workflowGapSummary(');
const gapEnd=source.indexOf('  function renderWorkingMap(', gapStart);
assert(gapStart >= 0 && gapEnd > gapStart, 'Workflow gap summary must exist');
vm.runInContext(source.slice(gapStart, gapEnd) + '\nthis.workflowGapSummary = workflowGapSummary;', scope);
const flow={steps:[{id:'S1',title:'Receive'},{id:'S2',title:'Approve'},{id:'S3',title:'Resolve exception'}],connections:[{from:'S1',to:'S2'},{from:'S3',to:'S3'}]};
assert.match(scope.workflowGapSummary(flow), /Resolve exception \(S3\)/);
flow.connections.push({from:'S2',to:'S3'});
assert.equal(scope.workflowGapSummary(flow), '');
assert.equal(scope.workflowGapSummary({steps:[{id:'S1'}],connections:[]}), '');
console.log(JSON.stringify({tests_passed: 16, provider_calls: 0, voice_tests: 0}));
