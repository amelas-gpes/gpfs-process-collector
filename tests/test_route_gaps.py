"""A reviewed map is checked for parts its route passes by before it is published.

Finding 2 of docs/testing/runs/2026-11-16-process-capture. The carry-vesting map led from the start
to the calculation without passing the method selection whose Method B outcome puts the work on
hold; another map left the identity check and ownership tracing outside the route, a third the
legal clearance. The fixture below is a fictional process with the same shape: no provider,
no file and no real interview is used.
"""
import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import Mock

from test_server import server

CORPUS = Path(__file__).resolve().parents[1] / 'docs' / 'testing' / 'runs' / '2026-11-16-process-capture' / 'interviews'

TURNS = [
    {'id': 'u1', 'role': 'user', 'text': 'When a grant changes, the preparer opens a change record and then ties the prior '
     'balances to the workbook. The client chooses the allowed option and names the recipients. If they select Option B, '
     'we put it on hold. We never run Option B from this procedure.'},
    {'id': 'a1', 'role': 'assistant', 'text': 'What does the preparer compare?'},
    {'id': 'u2', 'role': 'user', 'text': 'The prior schedules and recorded amounts must tie. Next we calculate the released '
     'units and allocate all released units to the named recipients.'},
    {'id': 'a2', 'role': 'assistant', 'text': 'What happens after that?'},
    {'id': 'u3', 'role': 'user', 'text': 'A reviewer checks the package before the schedules are sent.'},
]


def step(identity, title, kind='activity', sources=('u1',), **fields):
    return {'id': identity, 'title': title, 'type': kind, 'actor': 'UNKNOWN', 'system': 'UNKNOWN', 'description': title,
            'input': 'UNKNOWN', 'output': 'UNKNOWN', 'completion_criteria': 'UNKNOWN', 'handoff': 'UNKNOWN',
            'evidence_turns': list(sources), **fields}


def edge(start, end, label='', sources=('u1',)):
    return {'from': start, 'to': end, 'label': label, 'evidence_turns': list(sources)}


def bypassing_map():
    """S1 -> S2 -> S6 -> S7, with the selection, its decision and the hold drawn beside the route."""
    steps = [step('S1', 'Open change record', output='Change record'),
             step('S2', 'Tie starting position', sources=('u1', 'u2'), output='Tied starting position'),
             step('S3', 'Select option and recipients', output='Selected option and named recipients'),
             step('S4', 'Is Option B selected?', 'decision', output='Option outcome'),
             step('S5', 'Hold Option B', 'wait', output='Documented hold'),
             step('S6', 'Calculate and allocate units', sources=('u2',),
                  input='Tied starting position and named recipients', output='Allocated units'),
             step('S7', 'Review package', sources=('u3',), input='Allocated units')]
    connections = [edge('S1', 'S2', 'Record opened'), edge('S2', 'S6', 'Starting position tied', ('u2',)),
                   edge('S3', 'S4', 'Option selected'), edge('S4', 'S5', 'Option B selected'), edge('S6', 'S7', '', ('u3',))]
    return {'title': 'Grant changes', 'steps': steps, 'connections': connections,
            'open_questions': server.workflow_structure_questions(steps, connections) + ['Who approves the schedules?']}


def capture(workflow=None):
    return {'workflow': workflow or bypassing_map(), 'summary': 'A fictional grant change.', 'memo_findings': []}


SELECT_AFTER_TIE = {'from': 'S2', 'to': 'S3', 'label': 'Starting position tied', 'evidence_turns': ['u1'],
                    'passages': [{'source_id': 'u1', 'quote': 'ties the prior balances to the workbook. The client chooses the allowed option and names the recipients.'}]}
OTHER_OPTION = {'from': 'S4', 'to': 'S6', 'label': 'Option other than B selected', 'evidence_turns': ['u1', 'u2'],
                'passages': [{'source_id': 'u1', 'quote': 'If they select Option B, we put it on hold.'},
                             {'source_id': 'u2', 'quote': 'allocate all released units to the named recipients'}]}
BYPASS = {'from': 'S2', 'to': 'S6', 'label': 'Starting position tied'}


class Repair:
    """Stands in for the one bounded request; records what it was asked."""

    def __init__(self, answer):
        self.answer, self.asked, self.recorded = answer, [], []

    def ask(self, workflow, gaps):
        self.asked.append(copy.deepcopy(gaps))
        return copy.deepcopy(self.answer)

    def record(self, outcome, **counts):
        self.recorded.append((outcome, counts))


def connect(repair, workflow=None, **options):
    return server.connect_detached_routes(capture(workflow), repair, context={}, turns=TURNS, **options)['workflow']


def paths(workflow, start, end):
    """Every simple route from start to end, as lists of step IDs."""
    found, outgoing = [], {}
    for item in workflow['connections']:
        outgoing.setdefault(item['from'], []).append(item['to'])

    def walk(node, seen):
        if node == end:
            found.append(seen)
            return
        for following in outgoing.get(node, []):
            if following not in seen:
                walk(following, seen + [following])
    walk(start, [start])
    return found


class RouteGapTests(unittest.TestCase):
    def test_a_gate_the_route_passes_by_is_found_without_reading_any_source(self):
        workflow = bypassing_map()
        gaps = server.route_gaps(workflow['steps'], workflow['connections'])
        self.assertIn({'kind': 'detached', 'steps': ['S3', 'S4', 'S5'], 'gate': True}, gaps)
        # The map cites the prerequisite itself: the calculation's input is the selection's output.
        self.assertIn({'kind': 'unreached_input', 'step': 'S6', 'requires': 'S3', 'phrase': 'named recipients'}, gaps)
        self.assertEqual(len(gaps), 2)
        # The drawn route really does reach the calculation without the selection.
        self.assertEqual(paths(workflow, 'S1', 'S6'), [['S1', 'S2', 'S6']])

    def test_a_connected_map_and_generic_field_wording_raise_nothing(self):
        steps = [step('S1', 'Receive request', output='Request'), step('S2', 'Check request', input='Request', output='UNKNOWN'),
                 step('S3', 'File request', input='Information and details as required')]
        self.assertEqual(server.route_gaps(steps, [edge('S1', 'S2'), edge('S2', 'S3')]), [])
        self.assertEqual(server.route_gaps([], []), [])
        # An input another step produces upstream is satisfied, also through a loop.
        loop = [step('S1', 'Prepare package', output='Complete package'), step('S2', 'Review package', input='Complete package'),
                step('S3', 'Correct package', output='Corrected package')]
        self.assertEqual(server.route_gaps(loop, [edge('S1', 'S2'), edge('S2', 'S3', 'Rejected'), edge('S3', 'S2')]), [])

    def test_the_main_route_is_the_one_with_the_reported_start_else_the_largest(self):
        steps = [step('S1', 'Request arrives', 'start'), step('S2', 'Log request'),
                 step('S3', 'Screen'), step('S4', 'Assess'), step('S5', 'Decide'), step('S6', 'Archive')]
        gaps = server.route_gaps(steps, [edge('S1', 'S2'), edge('S3', 'S4'), edge('S4', 'S5')])
        self.assertEqual([gap['steps'] for gap in gaps], [['S3', 'S4', 'S5'], ['S6']])
        steps[0]['type'] = 'activity'
        gaps = server.route_gaps(steps, [edge('S1', 'S2'), edge('S3', 'S4'), edge('S4', 'S5')])
        self.assertEqual([gap['steps'] for gap in gaps], [['S1', 'S2'], ['S6']])

    def test_branch_that_only_feeds_into_the_started_route_needs_a_trigger(self):
        steps = [step('S1', 'Grant changes', 'start'), step('S2', 'Tie the balances'),
                 step('S3', 'Select the option'), step('S4', 'Review the selection'), step('S5', 'File package')]
        edges = [edge('S1', 'S2'), edge('S2', 'S5'), edge('S3', 'S4'), edge('S4', 'S3'), edge('S4', 'S5')]
        workflow = {'title': 'Grant changes', 'steps': steps, 'connections': edges, 'open_questions': []}
        branch = {'kind': 'unreached_branch', 'start': 'S1', 'steps': ['S3', 'S4']}
        self.assertEqual(server.route_gaps(steps, edges), [branch])
        unavailable = Repair(None)
        waiting = connect(unavailable, workflow)
        self.assertEqual(unavailable.asked, [[branch]])
        self.assertEqual(waiting['connections'], edges)
        question = next(item for item in waiting['open_questions'] if 'its own trigger' in item)
        self.assertIn('S3 (Select the option)', question)
        self.assertIn('S1 (Grant changes)', question)
        # A repeated check stays within the repair budget, and the clarification survives.
        repeated = Repair(None)
        self.assertIn(question, connect(repeated, waiting, baseline=workflow)['open_questions'])
        self.assertFalse(repeated.asked)
        supported = Repair({'connections': [SELECT_AFTER_TIE], 'replaced_connections': []})
        repaired = connect(supported, waiting)
        self.assertEqual(supported.asked, [[branch]])
        self.assertEqual(paths(repaired, 'S1', 'S4'), [['S1', 'S2', 'S3', 'S4']])
        self.assertNotIn(question, repaired['open_questions'])
        self.assertEqual(server.route_gaps(steps, repaired['connections']), [])

    def test_direction_check_requires_one_reported_start_and_stays_in_its_component(self):
        steps = [step('A', 'Start A', 'start'), step('B', 'Submit'),
                 step('C', 'Independent request', 'start'), step('D', 'Receive')]
        edges = [edge('A', 'B'), edge('C', 'B'), edge('D', 'C')]
        self.assertEqual(server.route_gaps(steps, edges), [])
        self.assertFalse(any('its own trigger' in q for q in server.workflow_structure_questions(steps, edges)))
        steps[0]['type'] = steps[2]['type'] = 'activity'
        self.assertEqual(server.route_gaps(steps, edges), [])
        steps[0]['type'] = 'start'
        separate = [edge('A', 'B'), edge('C', 'D')]
        self.assertEqual(server.route_gaps(steps, separate), [{'kind': 'detached', 'steps': ['C', 'D'], 'gate': False}])

    def test_sources_put_the_gate_on_the_route_and_the_bypass_is_rerouted_through_it(self):
        repair = Repair({'connections': [SELECT_AFTER_TIE, OTHER_OPTION], 'replaced_connections': [BYPASS]})
        workflow = connect(repair)
        published = {server.route_key(item) for item in workflow['connections']}
        self.assertIn(('S2', 'S3', 'starting position tied'), published)
        self.assertIn(('S4', 'S6', 'option other than b selected'), published)
        self.assertNotIn(('S2', 'S6', 'starting position tied'), published, 'The arrow that skipped the selection is gone')
        # Every route to the calculation passes the selection and its decision.
        routes = paths(workflow, 'S1', 'S6')
        self.assertEqual(routes, [['S1', 'S2', 'S3', 'S4', 'S6']])
        # Option B ends in its hold: nothing leads on from it.
        self.assertEqual([item['to'] for item in workflow['connections'] if item['from'] == 'S4' and 'option b selected' == item['label'].lower()], ['S5'])
        self.assertFalse([item for item in workflow['connections'] if item['from'] == 'S5'])
        self.assertEqual(server.route_gaps(workflow['steps'], workflow['connections']), [])
        # A published route keeps only the sources its passages were quoted from.
        added = next(item for item in workflow['connections'] if (item['from'], item['to']) == ('S2', 'S3'))
        self.assertEqual(added['evidence_turns'], ['u1'])
        # The application's questions about the old shape are replaced; the participant's own stay.
        self.assertFalse(any('separate, or is there a reported handoff' in question for question in workflow['open_questions']))
        self.assertIn('Who approves the schedules?', workflow['open_questions'])
        self.assertEqual(repair.recorded, [('connected', {'gaps': 2, 'connections_added': 2, 'connections_rerouted': 1})])
        self.assertEqual(len(repair.asked), 1)
        server.validate_workflow(copy.deepcopy(workflow), TURNS)

    def test_a_passage_that_does_not_occur_in_its_source_connects_nothing(self):
        bent = {**SELECT_AFTER_TIE, 'passages': [{'source_id': 'u1', 'quote': 'After the tie, the client always selects the option.'}]}
        wrong_source = {**OTHER_OPTION, 'evidence_turns': ['u3'], 'passages': OTHER_OPTION['passages']}
        assistant = {**OTHER_OPTION, 'evidence_turns': ['a1'], 'passages': [{'source_id': 'a1', 'quote': 'What does the preparer compare?'}]}
        for name, rows in {'bent quotation': [bent, OTHER_OPTION], 'source the route does not cite': [SELECT_AFTER_TIE, wrong_source],
                           'assistant turn': [SELECT_AFTER_TIE, assistant]}.items():
            with self.subTest(case=name):
                repair = Repair({'connections': rows, 'replaced_connections': [BYPASS]})
                workflow = connect(repair)
                published = {server.route_key(item) for item in workflow['connections']}
                # One verified connection alone does not lead from the tie through the gate to the
                # calculation, so the direct arrow stays: a reroute never loses a route.
                self.assertIn(('S2', 'S6', 'starting position tied'), published)
                self.assertEqual(len(workflow['connections']), 6)
                if name == 'bent quotation':
                    # The verified outcome of the decision is drawn; the calculation then has two
                    # incoming routes and the map asks how they combine instead of guessing.
                    self.assertIn(('S4', 'S6', 'option other than b selected'), published)
                    self.assertTrue(any('incoming route start S6' in question for question in workflow['open_questions']))
                else:
                    self.assertTrue(any('uses “named recipients”' in question for question in workflow['open_questions']))

    def test_an_arrow_is_never_taken_off_without_a_verified_route_through_the_detached_part(self):
        # Only a deletion is asked for.
        workflow = connect(Repair({'connections': [], 'replaced_connections': [BYPASS]}))
        self.assertEqual(workflow['connections'], bypassing_map()['connections'])
        # A reroute that does not pass through anything that was detached is not a reroute through a gate.
        side = {'from': 'S1', 'to': 'S6', 'label': 'Direct', 'evidence_turns': ['u2'],
                'passages': [{'source_id': 'u2', 'quote': 'Next we calculate the released units'}]}
        workflow = connect(Repair({'connections': [side], 'replaced_connections': [{'from': 'S1', 'to': 'S2', 'label': 'Record opened'}]}))
        self.assertIn(('S1', 'S2', 'record opened'), {server.route_key(item) for item in workflow['connections']})
        # An arrow that is not on the map, or listed twice, changes nothing.
        workflow = connect(Repair({'connections': [SELECT_AFTER_TIE, OTHER_OPTION],
                                   'replaced_connections': [BYPASS, BYPASS, {'from': 'S9', 'to': 'S6', 'label': ''}]}))
        self.assertEqual(len(workflow['connections']), 6)

    def test_proposals_that_are_not_routes_are_ignored(self):
        junk = [{**SELECT_AFTER_TIE, 'to': 'S99'}, {**SELECT_AFTER_TIE, 'to': 'S2'}, {**SELECT_AFTER_TIE, 'evidence_turns': []},
                {'from': 'S1', 'to': 'S2', 'label': 'Record opened', 'evidence_turns': ['u1'], 'passages': SELECT_AFTER_TIE['passages']},
                {**SELECT_AFTER_TIE, 'label': 'x' * 301}]
        workflow = connect(Repair({'connections': junk, 'replaced_connections': []}))
        self.assertEqual(workflow['connections'], bypassing_map()['connections'])

    def test_without_an_answer_the_map_is_published_as_reviewed_and_the_gap_is_named(self):
        for repair in (None, Repair(None)):
            with self.subTest(repair=repair is not None):
                workflow = connect(repair)
                self.assertEqual(workflow['connections'], bypassing_map()['connections'])
                self.assertTrue(any('S6 (Calculate and allocate units) uses “named recipients”, which S3 (Select option and recipients) produces'
                                    in question for question in workflow['open_questions']))
                self.assertTrue(any('separate, or is there a reported handoff' in question for question in workflow['open_questions']))
        self.assertEqual(Repair(None).recorded, [])

    def test_a_gap_is_put_to_the_sources_once_not_on_every_update(self):
        known = Repair({'connections': [], 'replaced_connections': []})
        connect(known, baseline=bypassing_map())
        self.assertEqual(known.asked, [], 'The map this update started from already had these gaps')
        # A step this update's review has just judged is not asked about a third time.
        judged = Repair({'connections': [], 'replaced_connections': []})
        connect(judged, judged=server.judged_route_steps([edge('S2', 'S3'), edge('S1', 'S2', 'Record opened')], bypassing_map()['connections']))
        self.assertEqual(judged.asked, [])
        # A new detached step is asked about; the gaps the baseline had are left out of that request.
        grown = bypassing_map()
        grown['steps'].append(step('S8', 'Archive package', sources=('u3',)))
        fresh = Repair({'connections': [], 'replaced_connections': []})
        connect(fresh, grown, baseline=bypassing_map())
        self.assertEqual(fresh.asked, [[{'kind': 'detached', 'steps': ['S8'], 'gate': False}]])
        self.assertEqual(fresh.recorded[0][0], 'unresolved')

    def test_a_connected_map_asks_nothing_and_returns_the_same_capture(self):
        workflow = bypassing_map()
        workflow['connections'] = [edge('S1', 'S2'), edge('S2', 'S3'), edge('S3', 'S4'), edge('S4', 'S5', 'Option B'),
                                   edge('S4', 'S6', 'Other option'), edge('S6', 'S7', '', ('u3',))]
        repair = Repair({'connections': [], 'replaced_connections': []})
        value = capture(workflow)
        self.assertIs(server.connect_detached_routes(value, repair, context={}, turns=TURNS), value)
        self.assertEqual(repair.asked, [])


class RouteRepairRequestTests(unittest.TestCase):
    def repair(self, result=None, seconds=200, **failure):
        client = Mock()
        client.structured = Mock(return_value=result, **failure)
        client.diagnostic_callback = Mock()
        return client, server.RouteRepair(client, {}, TURNS, {}, 'team_working_map_source_audit', time.monotonic() + seconds,
                                          model_override='synthetic-audit')

    def test_one_bounded_request_names_the_gaps_and_sends_no_private_fields(self):
        answer = {'connections': [SELECT_AFTER_TIE], 'replaced_connections': []}
        client, repair = self.repair(answer)
        workflow = bypassing_map()
        gaps = server.route_gaps(workflow['steps'], workflow['connections'])
        self.assertEqual(repair.ask(workflow, gaps), answer)
        instructions, sent, schema, name = client.structured.call_args.args[:4]
        self.assertIs(schema, server.ROUTE_REPAIR_SCHEMA)
        self.assertEqual(name, 'route_gap_repair')
        self.assertIn('never deletes a route', instructions)
        self.assertIn(server.REQUIRED_DEPENDENCY_POLICY, instructions)
        self.assertEqual(sent['route_gaps'][0]['titles'], ['Select option and recipients', 'Is Option B selected?', 'Hold Option B'])
        self.assertEqual((sent['route_gaps'][1]['step_title'], sent['route_gaps'][1]['requires_title']),
                         ('Calculate and allocate units', 'Select option and recipients'))
        self.assertEqual(sent['workflow']['connections'], workflow['connections'])
        self.assertLessEqual(client.structured.call_args.kwargs['request_timeout'], server.ROUTE_RECHECK_TIMEOUT)
        self.assertEqual(client.structured.call_args.kwargs['model_override'], 'synthetic-audit')
        repair.record('connected', gaps=2, connections_added=1, connections_rerouted=0)
        client.diagnostic_callback.assert_called_once_with('route_gap_repair', stage='team_working_map_source_audit', outcome='connected',
                                                           gaps=2, connections_added=1, connections_rerouted=0)
        self.assertNotIn('Option', json.dumps(client.diagnostic_callback.call_args.kwargs))

    def test_it_never_runs_past_the_time_the_map_requests_left_and_never_fails_a_map(self):
        workflow = bypassing_map()
        gaps = server.route_gaps(workflow['steps'], workflow['connections'])
        client, late = self.repair({'connections': [], 'replaced_connections': []}, seconds=server.ROUTE_RECHECK_MINIMUM - 1)
        self.assertIsNone(late.ask(workflow, gaps))
        client.structured.assert_not_called()
        for failure in (server.APIError('Synthetic provider failure', 504), ValueError('malformed'), StopIteration()):
            with self.subTest(failure=type(failure).__name__):
                _, failing = self.repair(side_effect=failure)
                self.assertIsNone(failing.ask(workflow, gaps))
        _, malformed = self.repair({'connections': 'none'})
        self.assertIsNone(malformed.ask(workflow, gaps))
        # A diagnostic callback that fails cannot fail the map either.
        client, repair = self.repair()
        client.diagnostic_callback.side_effect = OSError('disk full')
        repair.record('unavailable', gaps=1, connections_added=0, connections_rerouted=0)

    def test_the_routing_policy_names_gates_and_stated_sequences_wherever_routes_are_judged(self):
        for instructions in (server.WORKFLOW_INSTRUCTIONS, server.WORKFLOW_AUDIT_INSTRUCTIONS, server.ROUTE_RECHECK_INSTRUCTIONS,
                             server.ROUTE_REPAIR_INSTRUCTIONS, server.DRAFT_INSTRUCTIONS):
            self.assertIn('would let the work skip the', instructions)
            self.assertIn('One statement that lists actions in the order the work is done', instructions)
        self.assertIn('an order stated inside one answer is', server.WORKFLOW_AUDIT_INSTRUCTIONS)
        self.assertIn('does support the link between them', server.ROUTE_SUPPORT_INSTRUCTIONS)


class PublishedMapTests(unittest.TestCase):
    """The check runs on the map path itself, after the review and before publication."""

    def payload(self):
        findings = [{'key': key, 'status': 'unknown', 'answer': 'UNKNOWN', 'evidence_turns': []} for key in server.COVERAGE]
        return {'context': {'process_name': 'Grant changes', 'process_owner': '', 'objective': '', 'background': ''},
                'turns': copy.deepcopy(TURNS),
                'previous_capture': {'workflow': {'title': '', 'steps': [], 'connections': [], 'open_questions': []},
                                     'memo_findings': findings, 'summary': '', 'focus': '', 'parking_lot': []}}

    def test_a_generated_map_with_a_bypassed_hold_is_repaired_before_it_is_published(self):
        drawn = bypassing_map()
        update = {'title': 'Grant changes', 'upsert_steps': drawn['steps'], 'remove_steps': [],
                  'upsert_connections': drawn['connections'], 'remove_connections': [], 'open_questions': [],
                  'memo_findings': [], 'summary': 'A fictional grant change.', 'focus': 'Route', 'parking_lot': []}
        quotes = {('S1', 'S2'): ('u1', 'opens a change record and then ties the prior balances'),
                  ('S2', 'S6'): ('u2', 'must tie. Next we calculate the released units'),
                  ('S3', 'S4'): ('u1', 'The client chooses the allowed option and names the recipients. If they select Option B'),
                  ('S4', 'S5'): ('u1', 'If they select Option B, we put it on hold.'),
                  ('S6', 'S7'): ('u3', 'A reviewer checks the package')}
        audit = {'title': update['title'], 'summary': update['summary'], 'focus': update['focus'], 'open_questions': [], 'parking_lot': [],
                 'route_support': [{'from': item['from'], 'to': item['to'], 'label': item['label'],
                                    'passages': [dict(zip(('source_id', 'quote'), quotes[(item['from'], item['to'])]))]}
                                   for item in drawn['connections']],
                 'remove_connections': [], 'remove_steps': [], 'discard_step_upserts': [], 'discard_connection_upserts': [],
                 'discard_step_removals': [], 'discard_connection_removals': [], 'upsert_steps': [], 'upsert_connections': [],
                 'memo_findings': []}
        repair = {'connections': [SELECT_AFTER_TIE, OTHER_OPTION], 'replaced_connections': [BYPASS]}
        client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-route-gaps'})
        client.structured = Mock(side_effect=[update, audit, repair])
        client.apply_coverage_review = lambda capture, *args, **kwargs: capture
        workflow = client.workflow(self.payload())['workflow']
        self.assertEqual(client.structured.call_count, 3)
        self.assertEqual(client.structured.call_args.args[3], 'route_gap_repair')
        self.assertEqual(paths(workflow, 'S1', 'S6'), [['S1', 'S2', 'S3', 'S4', 'S6']])
        self.assertFalse([item for item in workflow['connections'] if item['from'] == 'S5'])
        # Without an answer from the sources the reviewed map is still published, with the gap named.
        client.structured = Mock(side_effect=[update, audit, server.APIError('Synthetic provider failure', 504)])
        workflow = client.workflow(self.payload())['workflow']
        self.assertEqual(paths(workflow, 'S1', 'S6'), [['S1', 'S2', 'S6']])
        self.assertTrue(any('uses “named recipients”' in question for question in workflow['open_questions']))

    @unittest.skipUnless((CORPUS / 'GP-03.json').is_file(), 'Testing corpus not present')
    def test_the_saved_maps_of_the_november_run_show_the_reported_gaps(self):
        def gaps(name):
            workflow = json.loads((CORPUS / name).read_text(encoding='utf-8'))['workflow']
            return workflow, server.route_gaps(workflow['steps'], workflow['connections'])
        workflow, found = gaps('GP-03.json')
        self.assertIn({'kind': 'detached', 'steps': ['S3', 'S4', 'S5'], 'gate': True}, found)
        self.assertIn({'kind': 'unreached_input', 'step': 'S6', 'requires': 'S3', 'phrase': 'named recipients'}, found)
        self.assertEqual(paths(workflow, 'S1', 'S6'), [['S1', 'S2', 'S6']], 'The saved map reaches the calculation without the selection')
        _, found = gaps('FA-20.json')
        self.assertTrue({('S4',), ('S5',)} <= {tuple(gap['steps']) for gap in found if gap['kind'] == 'detached'},
                        'Identity validation and ownership tracing were left outside the route')
        _, found = gaps('FA-04.json')
        self.assertIn(('S6',), {tuple(gap['steps']) for gap in found if gap['kind'] == 'detached'},
                      'Legal clearance was left outside the route')


if __name__ == '__main__':
    unittest.main()
