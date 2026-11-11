"""Component contracts shared by working maps and reviewed drafts; no provider requests."""
import copy
import unittest

from test_server import server, process_draft
from test_workflow_updates import edge, step, payload, update


TYPES = ['activity', 'decision', 'merge', 'start', 'end', 'parallel_split', 'parallel_join',
         'wait', 'subprocess', 'document', 'data_store']
TURNS = [{'id': 'u1', 'role': 'user', 'text': (
    'A request arrives. Check whether it is accepted; rejected requests end as rejected. '
    'For accepted requests start document preparation and the background-check procedure '
    'in parallel. Wait until both finish, then wait for the agreed release date. '
    'Write the release into the register and notify the requester; the process ends as released.')}]


def component(step_id, title, kind):
    return {**step(step_id, title), 'type': kind}


def complex_map():
    return {'title': 'Request release', 'steps': [
        component('S1', 'Request arrives', 'start'),
        component('S2', 'Request accepted?', 'decision'),
        component('S3', 'Request rejected', 'end'),
        component('S4', 'Begin both preparations', 'parallel_split'),
        component('S5', 'Prepare release document', 'document'),
        component('S6', 'Run background-check procedure', 'subprocess'),
        component('S7', 'Both preparations complete', 'parallel_join'),
        component('S8', 'Wait for release date', 'wait'),
        component('S9', 'Write release to register', 'data_store'),
        component('S10', 'Notify requester', 'activity'),
        component('S11', 'Request released', 'end'),
    ], 'connections': [
        edge('S1', 'S2'), edge('S2', 'S3', 'Rejected'), edge('S2', 'S4', 'Accepted'),
        edge('S4', 'S5', 'Document preparation'), edge('S4', 'S6', 'Background check'),
        edge('S5', 'S7', 'Document ready'), edge('S6', 'S7', 'Check complete'),
        edge('S7', 'S8', 'Both complete'), edge('S8', 'S9', 'Release date reached'),
        edge('S9', 'S10'), edge('S10', 'S11'),
    ], 'open_questions': []}


class WorkflowComponentTests(unittest.TestCase):
    def test_separate_connected_fragments_are_visible_in_live_and_draft_routing_questions(self):
        nodes = [component(n, n, 'activity') for n in ('A', 'B', 'C', 'D')]
        links = [edge('A', 'B'), edge('C', 'D')]
        workflow = {'title':'Reported routes', 'steps':nodes, 'connections':links, 'open_questions':[]}
        draft = process_draft()
        draft.update(workflow, lifecycle_items=[], memo_summary=[{'key':k, 'status':'unknown','answer':'UNKNOWN',
                                                                'evidence_turns':[]} for k in server.COVERAGE])
        for validator, value in ((server.validate_workflow, workflow), (server.validate_draft, draft)):
            result = validator(copy.deepcopy(value), TURNS)
            self.assertEqual(result['connections'], links)
            self.assertEqual(len(result['open_questions']), 1)
            self.assertIn('separate', result['open_questions'][0])
            self.assertEqual(validator(result, TURNS)['open_questions'], result['open_questions'])

    def test_all_component_types_preserve_topology_in_working_and_draft_maps(self):
        workflow = complex_map()
        before = copy.deepcopy(workflow)
        validated = server.validate_workflow(workflow, TURNS)
        self.assertEqual(validated, before)
        self.assertEqual(set(s['type'] for s in validated['steps']), set(TYPES) - {'merge'})
        draft = process_draft()
        draft.update(copy.deepcopy(workflow))
        draft['memo_summary'] = [{'key': k, 'status': 'unknown', 'answer': 'UNKNOWN', 'evidence_turns': []}
                                 for k in server.COVERAGE]
        draft['lifecycle_items'] = []
        validated_draft = server.validate_draft(draft, TURNS)
        self.assertEqual(validated_draft['steps'], before['steps'])
        self.assertEqual(validated_draft['connections'], before['connections'])
        self.assertEqual(validated_draft['open_questions'], [])

    def test_old_activity_decision_files_need_no_new_fields(self):
        workflow = complex_map()
        workflow['steps'] = [component('S1', 'Evaluate request', 'decision'),
                             component('S2', 'Process accepted request', 'activity'),
                             component('S3', 'Close rejected request', 'activity')]
        workflow['connections'] = [edge('S1', 'S2', 'Accepted'), edge('S1', 'S3', 'Rejected')]
        self.assertEqual(server.validate_workflow(copy.deepcopy(workflow), TURNS), workflow)

    def test_alternative_merge_remains_distinct_from_all_parallel_join(self):
        candidate = {'title': 'Checks with optional correction', 'steps': [
            component('S1', 'Identity accepted?', 'decision'),
            component('S2', 'Correct and recheck document', 'activity'),
            component('S3', 'Identity route complete', 'merge'),
            component('S4', 'IT setup', 'activity'),
            component('S5', 'Identity and IT complete', 'parallel_join')],
            'connections': [edge('S1', 'S3', 'Accepted'), edge('S1', 'S2', 'Correction required'),
                            edge('S2', 'S3', 'Recheck complete'), edge('S3', 'S5', 'Identity complete'),
                            edge('S4', 'S5', 'IT complete')], 'open_questions': []}
        before = copy.deepcopy(candidate)
        self.assertEqual(server.validate_workflow(candidate, TURNS), before)
        draft = process_draft()
        draft.update(copy.deepcopy(candidate))
        draft['memo_summary'] = [{'key': k, 'status': 'unknown', 'answer': 'UNKNOWN', 'evidence_turns': []}
                                 for k in server.COVERAGE]
        draft['lifecycle_items'] = []
        result = server.validate_draft(draft, TURNS)
        self.assertEqual(result['steps'], before['steps'])
        self.assertEqual(result['connections'], before['connections'])
        self.assertEqual(result['open_questions'], [])

    def test_component_correction_keeps_id_and_unrelated_steps_and_connections(self):
        original = payload()
        original['turns'].append({'id': 'u4', 'role': 'user', 'text': 'The last step creates the handoff document.'})
        previous = server.workflow_previous_capture(original['previous_capture'], original['turns'])
        changed = {**previous['workflow']['steps'][-1], 'type': 'document',
                   'title': 'Create handoff document', 'evidence_turns': ['u4']}
        result = server.apply_workflow_update(update(upsert_steps=[changed]), previous, original['turns'])
        self.assertEqual(result['workflow']['steps'][:-1], previous['workflow']['steps'][:-1])
        self.assertEqual(result['workflow']['steps'][-1], changed)
        self.assertEqual(result['workflow']['connections'], previous['workflow']['connections'])

    def test_every_component_requires_actual_participant_evidence(self):
        for kind in TYPES:
            for sources in ([], ['missing'], ['a1']):
                with self.subTest(kind=kind, sources=sources):
                    candidate = {'title': 'Partial', 'steps': [component('S1', 'Reported component', kind)],
                                 'connections': [], 'open_questions': []}
                    candidate['steps'][0]['evidence_turns'] = sources
                    with self.assertRaises(ValueError):
                        server.validate_workflow(candidate, TURNS + [{'id': 'a1', 'role': 'assistant', 'text': 'Question?'}])

    def test_partial_gateways_keep_reported_routes_and_surface_missing_semantics(self):
        for kind, expected in [('decision', 'other outcomes'), ('parallel_split', 'branches begin in parallel'),
                               ('parallel_join', 'prerequisites must all finish'),
                               ('merge', 'alternative routes converge')]:
            with self.subTest(kind=kind):
                candidate = {'title': 'Partial', 'steps': [component('S1', 'Known step', 'activity'),
                             component('S2', 'Reported routing point', kind)],
                             'connections': [edge('S1', 'S2')], 'open_questions': ['Who owns this process?']}
                before = copy.deepcopy(candidate)
                result = server.validate_workflow(candidate, TURNS)
                self.assertEqual(result['steps'], before['steps'])
                self.assertEqual(result['connections'], before['connections'])
                self.assertTrue(any(expected in question for question in result['open_questions']))
                self.assertIn('Who owns this process?', result['open_questions'])
                self.assertEqual(server.validate_workflow(copy.deepcopy(result), TURNS), result,
                                 'Repeated validation must not duplicate questions.')

    def test_unlabelled_decision_route_is_retained_as_an_explicit_gap(self):
        candidate = complex_map()
        candidate['connections'][1]['label'] = ''
        result = server.validate_workflow(candidate, TURNS)
        self.assertEqual(result['connections'][1]['label'], '')
        self.assertTrue(any('What condition leads from decision S2' in q for q in result['open_questions']))

    def test_wait_preserves_early_response_and_timeout_as_alternative_exits(self):
        candidate = {'title': 'Response follow-up', 'steps': [
            component('S1', 'Wait for response or deadline', 'wait'),
            component('S2', 'Assess response', 'activity'),
            component('S3', 'Send reminder', 'activity')],
            'connections': [edge('S1', 'S2', 'Response arrives within three business days'),
                            edge('S1', 'S3', 'Three business days pass without a response')],
            'open_questions': []}
        before = copy.deepcopy(candidate)
        result = server.validate_workflow(candidate, TURNS)
        self.assertEqual(result, before, 'A wait can have event exits without an invented decision or extra delay.')

    def test_document_correction_can_return_to_wait_without_an_invented_boundary(self):
        candidate = {'title': 'Contract correction', 'steps': [
            component('S1', 'Wait for signed contract', 'wait'),
            component('S2', 'Signature valid?', 'decision'),
            component('S3', 'Return contract for correction', 'document'),
            component('S4', 'Record supplier', 'data_store')],
            'connections': [edge('S1', 'S2', 'Signed contract arrives'),
                            edge('S2', 'S3', 'Invalid signature'), edge('S2', 'S4', 'Valid signature'),
                            edge('S3', 'S1', 'Correction requested')], 'open_questions': []}
        before = copy.deepcopy(candidate)
        self.assertEqual(server.validate_workflow(candidate, TURNS), before)

    def test_unknown_order_does_not_create_parallelism_or_approval_evidence(self):
        candidate = {'title': 'Required approvals', 'steps': [
            component('S1', 'Manager approves invoice', 'activity'),
            component('S2', 'Controller approves invoice', 'activity')],
            'connections': [], 'open_questions': ['What is the approval order and routing?']}
        before = copy.deepcopy(candidate)
        result = server.validate_workflow(candidate, TURNS)
        self.assertEqual(result['steps'], before['steps'])
        self.assertEqual(result['connections'], [])
        self.assertTrue(all(s['completion_criteria'] == 'UNKNOWN' for s in result['steps']))

    def test_rework_with_unknown_criterion_keeps_its_reported_loop(self):
        candidate = {'title': 'Identity checks', 'steps': [
            component('S1', 'Check identity', 'activity'),
            component('S2', 'Correct document', 'document'),
            component('S3', 'Identity and IT complete', 'parallel_join'),
            component('S4', 'Set up IT account', 'activity')],
            'connections': [edge('S1', 'S2', 'Correction required'), edge('S2', 'S1', 'Recheck'),
                            edge('S1', 'S3', 'Identity check complete'), edge('S4', 'S3', 'IT setup complete')],
            'open_questions': ['What requires a document correction?']}
        before = copy.deepcopy(candidate)
        self.assertEqual(server.validate_workflow(candidate, TURNS), before)

    def test_possible_double_counted_parallel_branch_is_flagged_without_rewriting_it(self):
        candidate = complex_map()
        candidate['connections'].append(edge('S5', 'S6', 'Reported dependency needing clarification'))
        before = copy.deepcopy(candidate)
        result = server.validate_workflow(candidate, TURNS)
        self.assertEqual(result['steps'], before['steps'])
        self.assertEqual(result['connections'], before['connections'])
        self.assertTrue(any('count the same branch more than once through S5, S6' in q
                            for q in result['open_questions']))

    def test_reported_loop_after_join_does_not_make_independent_inputs_look_related(self):
        candidate = complex_map()
        candidate['connections'].append(edge('S10', 'S4', 'Reported repeat'))
        before = copy.deepcopy(candidate)
        result = server.validate_workflow(candidate, TURNS)
        self.assertEqual(result, before, 'Reachability through the join itself must not flag its valid inputs.')

    def test_boundary_conflicts_surface_without_guessing_new_processes(self):
        candidate = {'title': 'Unclear boundary', 'steps': [component('S1', 'Start event', 'start'),
                     component('S2', 'End result', 'end')],
                     'connections': [edge('S1', 'S2'), edge('S2', 'S1', 'Reported repeat')],
                     'open_questions': []}
        before = copy.deepcopy(candidate)
        result = server.validate_workflow(candidate, TURNS)
        self.assertEqual(result['connections'], before['connections'])
        self.assertEqual(result['steps'], before['steps'])
        self.assertEqual(len(result['open_questions']), 2)

    def test_unknown_component_type_is_rejected_instead_of_silently_downgraded(self):
        candidate = complex_map()
        candidate['steps'][0]['type'] = 'unrecognized_event'
        with self.assertRaises(ValueError):
            server.validate_workflow(candidate, TURNS)

    def test_approved_rich_component_contract_reaches_capture_draft_and_audit(self):
        # Wiring check; semantic quality is separately evaluated with fictional provider replays.
        for instructions in (server.WORKFLOW_INSTRUCTIONS, server.DRAFT_INSTRUCTIONS,
                             server.DRAFT_AUDIT_INSTRUCTIONS):
            self.assertIn(server.WORKFLOW_COMPONENT_POLICY, instructions)
        self.assertEqual(server.WORKFLOW_STEP_TYPES, TYPES)
        self.assertIs(server.WORKFLOW_SCHEMA['properties']['steps'], server.DRAFT_SCHEMA['properties']['steps'])
        self.assertIs(server.WORKFLOW_UPDATE_SCHEMA['properties']['upsert_steps'],
                      server.WORKFLOW_SCHEMA['properties']['steps'])


if __name__ == '__main__':
    unittest.main()
