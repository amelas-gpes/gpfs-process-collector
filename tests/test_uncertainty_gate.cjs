// The browser's copy of the uncertainty gate, run on the same cases as the server
// (tests/fixtures/uncertainty_gate_cases.json, also used by test_uncertainty_gate.py).
// Offline: evaluates the memo-normalization slice of web/app.js; no provider, DOM or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'uncertainty_gate_cases.json'), 'utf8'));
const topicsStart = source.indexOf('  const TOPICS = [');
const topicsEnd = source.indexOf('  const MEMO_HEADINGS', topicsStart);
const start = source.indexOf('  function evidenceSources(');
const end = source.indexOf('  function normalizeDraft(', start);
assert(topicsStart >= 0 && topicsEnd > topicsStart && start >= 0 && end > start, 'Memo normalization must exist');
const scope = {state: {documentEvidence: []},
  strings: (value, limit) => Array.isArray(value) ? value.slice(0, limit).filter(v => typeof v === 'string') : [],
  text: (value, limit) => typeof value === 'string' ? value.trim().slice(0, limit) : ''};
vm.createContext(scope);
vm.runInContext(source.slice(topicsStart, topicsEnd) + source.slice(start, end) +
  '\nthis.TOPICS = TOPICS; this.normalizeFindings = normalizeFindings; this.uncertainWording = uncertainWording;', scope);
assert.equal(typeof scope.uncertainWording, 'function', 'The browser applies the shared uncertainty gate');
const turns = [{id: 'u1', role: 'user', text: 'Synthetic participant account.'}];
let passed = 0;

function shown(key, answer, status = 'captured') {
  const findings = scope.TOPICS.map(([topic]) => ({key: topic, status: 'captured', answer: 'Synthetic complete topic.', evidence_turns: ['u1']}));
  Object.assign(findings.find(finding => finding.key === key), {status, answer});
  const result = scope.normalizeFindings(findings, turns, []);
  return {status: result.find(finding => finding.key === key).status,
    complete: result.length === 16 && result.every(finding => ['captured', 'not_applicable'].includes(finding.status))};
}

assert.ok(cases.confident.length >= 45 && cases.uncertain.length >= 55);
for (const [key, answer] of cases.confident) {
  assert.equal(scope.uncertainWording(key, answer), '', `Ordinary process wording is not a knowledge gap [${key}] ${answer}`);
  assert.deepEqual(shown(key, answer), {status: 'captured', complete: true}, `[${key}] ${answer}`);
  passed++;
}
for (const [key, answer, wording] of cases.uncertain) {
  assert.ok(wording, 'The fixture names the wording the gate reports');
  assert.equal(scope.uncertainWording(key, answer), wording, `The browser reports the server's wording [${key}] ${answer}`);
  assert.deepEqual(shown(key, answer), {status: 'partial', complete: false}, `[${key}] ${answer}`);
  passed++;
}

// The sentences written after the rules were final are decided by the browser as labelled too.
const heldOut = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'uncertainty_gate_heldout.json'), 'utf8'));
for (const part of ['first', 'second']) {
  assert.ok(heldOut[part].sentences.length >= 60);
  for (const [decision, key, answer] of heldOut[part].sentences) {
    assert.equal(Boolean(scope.uncertainWording(key, answer)), decision === 'hold', `[${part}] [${key}] ${answer}`);
    assert.equal(shown(key, answer).status, decision === 'hold' ? 'partial' : 'captured', `[${part}] [${key}] ${answer}`);
    passed++;
  }
}

// A state noted after its subject holds however it is joined and whatever follows it,
// and a hedge on who approves holds wherever it stands in the clause.
for (const subject of ['Approver', 'Cutoff time', 'Volume', 'System of record']) {
  for (const connector of [': ', ' ', ' - ', ' – ', '; ', ', ', ' is ', ' (', ' remains ']) {
    for (const state of ['unknown', 'unclear', 'unconfirmed', 'not confirmed', 'not yet known', 'TBC', 'to be confirmed']) {
      for (const tail of ['', ' yet', ' at this stage', ' so far', ' by the participant', ' in the interview']) {
        const answer = subject + connector + state + tail + (connector === ' (' ? ')' : '') + '.';
        assert.notEqual(scope.uncertainWording('lifecycle', answer), '', answer);
        passed++;
      }
    }
  }
}
for (const form of ['Approver: {h} the CFO.', 'The approver is the CFO, {h}.', 'The CFO approves, {h}.', 'The CFO, {h}, approves.',
  'The CFO ({h}) approves.', 'Approved by the CFO, {h}.', '{H} the CFO.', 'The CFO signs off, {h}.']) {
  for (const hedge of ['probably', 'likely', 'possibly', 'perhaps', 'maybe', 'presumably']) {
    const answer = form.replace('{h}', hedge).replace('{H}', hedge[0].toUpperCase() + hedge.slice(1));
    assert.notEqual(scope.uncertainWording('checks', answer), '', answer);
    passed++;
  }
}

// A topic the server returned as partial or unknown is never promoted by the browser.
assert.equal(shown('checks', 'The controller approves the notice.', 'partial').status, 'partial');
assert.equal(shown('variations', 'No client differences apply because this is the only fund.', 'not_applicable').status, 'not_applicable');
assert.equal(shown('variations', 'I think no client differences apply.', 'not_applicable').status, 'partial');
passed += 3;

// Each fact line is judged on its own, and topic-specific literals stay scoped to their topics.
assert.equal(scope.uncertainWording('variations', 'A rush call is possible, and clients ask for one maybe\nApproval is recorded by the controller in the register.'), '');
assert.equal(scope.uncertainWording('checks', 'The controller approves the notice.\nThe second approver is unknown.'), 'is unknown');
const literal = 'The analyst records the literal value UNKNOWN in the Stage column before the reviewer changes it.';
assert.equal(scope.uncertainWording('lifecycle', literal), '');
assert.equal(scope.uncertainWording('data_systems', literal), '');
assert.equal(scope.uncertainWording('accountable', literal), 'UNKNOWN');
assert.equal(scope.uncertainWording(undefined, literal), 'UNKNOWN');
assert.equal(scope.uncertainWording('checks', 'The approver ' + 'really '.repeat(80) + 'is unknown.'), 'is unknown');
assert.equal(scope.uncertainWording('checks', ''), '');
assert.equal(scope.uncertainWording('checks', undefined), '');
passed += 9;

// Typographic quotes and spaces read as plain ones, exactly as on the server.
const typed = (...parts) => parts.map(part => typeof part === 'number' ? String.fromCharCode(part) : part).join('');
for (const [answer, wording] of [
  [typed('The storage location is', 0xa0, 'unknown.'), 'is unknown'],
  [typed('I don', 0x2019, 't', 0x2009, 'know who approves.'), "don't know"],
  [typed('We can', 0x02bc, 't recall the approver.'), "can't recall"],
  [typed('The owner is ', 0x201c, 'unclear', 0x201d, '.'), 'is "unclear'],
  [typed('Storage location ', 0x2013, ' unknown.'), 'Storage location - unknown'],
  [typed('Storage location ', 0x2014, ' not confirmed.'), 'Storage location - not confirmed'],
  [typed('Storage location', 0x2014, 'unknown.'), 'unknown'],
  [typed('Storage location ', 0x2212, ' unclear at present.'), 'Storage location - unclear']]) {
  assert.equal(scope.uncertainWording('materials', answer), wording);
  assert.equal(shown('materials', answer).status, 'partial');
  passed++;
}

// A hedged name alone holds only where it answers who: who owns (accountable) and who
// approves or checks (checks). Elsewhere a hedge holds only beside an owner or approver.
assert.equal(scope.uncertainWording('accountable', 'Probably the controller.'), 'Probably');
assert.equal(scope.uncertainWording('checks', 'Probably the controller.'), 'Probably the controller');
assert.equal(scope.uncertainWording('trigger', "Probably the bank's email."), '');
assert.equal(scope.uncertainWording(undefined, 'Probably the controller.'), '');
assert.equal(scope.uncertainWording('checks', 'The reviewer might return the item to the preparer.'), '');
passed += 5;

// A word is a label only beside what names it as one; the masks are case-sensitive, as on the server.
assert.equal(scope.uncertainWording('data_systems', 'The tracker has a status called "unconfirmed" for wires awaiting callback.'), '');
assert.equal(scope.uncertainWording('lifecycle', 'The Payer (Unknown) bucket holds unmatched receipts.'), '');
assert.equal(scope.uncertainWording('data_systems', 'The default category is Unknown.'), '');
assert.notEqual(scope.uncertainWording('data_systems', 'The approval status is Unknown.'), '');
assert.notEqual(scope.uncertainWording('accountable', 'Owner: Unknown.'), '');
assert.notEqual(scope.uncertainWording('accountable', 'The owner field is marked "unknown".'), '');
passed += 6;

console.log(JSON.stringify({tests_passed: passed, provider_calls: 0, voice_tests: 0}));
