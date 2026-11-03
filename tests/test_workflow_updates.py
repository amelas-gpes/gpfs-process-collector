"""Offline regression cases for scoped corrections to a previously accepted map."""
import copy
import unittest
from unittest.mock import Mock

from test_server import server


def step(step_id, title, sources=None):
    return {'id': step_id, 'title': title, 'type': 'activity', 'actor': 'Participant',
            'system': 'UNKNOWN', 'description': title, 'input': 'UNKNOWN', 'output': 'UNKNOWN',
            'completion_criteria': 'UNKNOWN', 'handoff': 'UNKNOWN',
            'evidence_turns': sources or ['u1']}


def edge(start, end, label='Next', sources=None):
    return {'from': start, 'to': end, 'label': label, 'evidence_turns': sources or ['u1']}


def payload():
    findings = [{'key': key, 'status': 'unknown', 'answer': 'UNKNOWN', 'evidence_turns': []}
                for key in server.COVERAGE]
    next(f for f in findings if f['key'] == 'materials').update(
        status='partial', answer='Jira tickets and Confluence documents.', evidence_turns=['u1'])
    next(f for f in findings if f['key'] == 'lifecycle').update(
        status='partial', answer='Prepare the board, prioritize and update ideas, then attach a ticket or document.',
        evidence_turns=['u1'])
    return {
        'context': {'process_name': 'Backlog refinement', 'process_owner': '', 'objective': '', 'background': ''},
        'turns': [
            {'id': 'u1', 'role': 'user', 'text': 'I prepare the discovery board, prioritize ideas, update them, then attach a Jira ticket or Confluence document.'},
            {'id': 'a1', 'role': 'assistant', 'text': 'How do you decide which idea comes first?'},
            {'id': 'u2', 'role': 'user', 'text': 'Sorry, the first step was not checking the discovery board. Change it to get water and put my mind at ease before I start.'},
            {'id': 'u3', 'role': 'user', 'text': "That's about it."},
        ],
        'previous_capture': {
            'workflow': {'title': 'Backlog refinement',
                         'steps': [step('S1', 'Prepare discovery board'), step('S2', 'Prioritize ideas'),
                                   step('S3', 'Update ideas'), step('S4', 'Attach ticket or document')],
                         'connections': [edge('S1', 'S2'), edge('S2', 'S3'), edge('S3', 'S4')],
                         'open_questions': []},
            'memo_findings': findings, 'summary': 'The participant described backlog refinement.',
            'focus': 'First work step', 'parking_lot': [],
        },
    }


def update(**overrides):
    result = {'title': 'Backlog refinement', 'upsert_steps': [], 'remove_steps': [],
              'upsert_connections': [], 'remove_connections': [], 'open_questions': [],
              'memo_findings': [], 'summary': 'The first step was corrected; later described work remains.',
              'focus': 'First work step', 'parking_lot': []}
    result.update(overrides)
    return result


def removal(step_id, source='u4', quote='Remove the update step'):
    return {'id': step_id, 'reason': 'Participant explicitly removed this action.',
            'source_quote': quote, 'evidence_turns': [source]}


class WorkflowUpdateTests(unittest.TestCase):
    def client(self, result):
        client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-workflow-regression'})
        client.structured = Mock(return_value=result)
        return client

    def test_first_step_correction_preserves_later_actions_edges_and_materials(self):
        original = payload()
        before = copy.deepcopy(original)
        revised = step('S1', 'Get water', ['u2'])
        patch = update(upsert_steps=[revised], upsert_connections=[edge('S1', 'S2', sources=['u1', 'u2'])],
                       memo_findings=[{'key': 'lifecycle', 'status': 'partial',
                                       'answer': 'Get water, prioritize and update ideas, then attach a Jira ticket or Confluence document.',
                                       'evidence_turns': ['u1', 'u2']}])
        client = self.client(patch)
        result = client.workflow(original)
        self.assertEqual(result['workflow']['steps'], [revised, *before['previous_capture']['workflow']['steps'][1:]])
        self.assertEqual(result['workflow']['connections'][1:], before['previous_capture']['workflow']['connections'][1:])
        by_key = {f['key']: f for f in result['memo_findings']}
        self.assertEqual(by_key['materials'], before['previous_capture']['memo_findings'][-1])
        self.assertIn('prioritize', by_key['lifecycle']['answer'])
        self.assertEqual(original, before, 'The accepted prior capture and transcript must remain untouched.')
        sent = client.structured.call_args.args[1]
        self.assertEqual(sent['previous_capture']['workflow']['steps'], before['previous_capture']['workflow']['steps'])

    def test_no_op_or_ambiguous_wrap_up_does_not_withdraw_earlier_steps(self):
        original = payload()
        result = self.client(update()).workflow(original)
        self.assertEqual(result['workflow']['steps'], original['previous_capture']['workflow']['steps'])
        self.assertEqual(result['workflow']['connections'], original['previous_capture']['workflow']['connections'])
        self.assertEqual(result['memo_findings'], original['previous_capture']['memo_findings'])

    def test_remove_one_step_only_cascades_its_incident_edges_without_inventing_rejoin(self):
        original = payload()
        original['turns'].append({'id': 'u4', 'role': 'user', 'text': 'Remove the update step; updates belong to another process.'})
        result = self.client(update(remove_steps=[removal('S3')])).workflow(original)
        self.assertEqual([s['id'] for s in result['workflow']['steps']], ['S1', 'S2', 'S4'])
        self.assertEqual(result['workflow']['connections'], [edge('S1', 'S2')])
        self.assertFalse(any(e['from'] == 'S2' and e['to'] == 'S4' for e in result['workflow']['connections']))
        self.assertTrue(any('S4' in q for q in result['workflow']['open_questions']))

    def test_new_node_does_not_renumber_existing_survivors(self):
        original = payload()
        original['turns'].append({'id': 'u4', 'role': 'user', 'text': 'After attaching the ticket, archive the completed idea.'})
        added = step('S5', 'Archive completed idea', ['u4'])
        result = self.client(update(upsert_steps=[added], upsert_connections=[edge('S4', 'S5', sources=['u4'])])).workflow(original)
        self.assertEqual(result['workflow']['steps'], [*original['previous_capture']['workflow']['steps'], added])

    def test_relabel_one_parallel_edge_leaves_other_routes_untouched(self):
        original = payload()
        old_edge = edge('S2', 'S3', 'Approved')
        other_edge = edge('S2', 'S3', 'Deferred')
        original['previous_capture']['workflow']['connections'][1:2] = [old_edge, other_edge]
        original['turns'].append({'id': 'u4', 'role': 'user', 'text': 'Call the Approved route Ready; leave the Deferred route as described.'})
        remove = {**old_edge, 'reason': 'Participant corrected the route name.', 'source_quote': 'Call the Approved route Ready'}
        remove['evidence_turns'] = ['u4']
        result = self.client(update(remove_connections=[remove], upsert_connections=[edge('S2', 'S3', 'Ready', ['u4'])])).workflow(original)
        self.assertIn(other_edge, result['workflow']['connections'])
        self.assertIn(edge('S2', 'S3', 'Ready', ['u4']), result['workflow']['connections'])
        self.assertNotIn(old_edge, result['workflow']['connections'])

    def test_all_steps_can_be_withdrawn_explicitly(self):
        original = payload()
        original['turns'].append({'id': 'u4', 'role': 'user', 'text': 'Discard all of the process steps; none describes the process I meant.'})
        removed = [removal(s['id'], quote='Discard all of the process steps') for s in original['previous_capture']['workflow']['steps']]
        result = self.client(update(remove_steps=removed)).workflow(original)
        self.assertEqual(result['workflow']['steps'], [])
        self.assertEqual(result['workflow']['connections'], [])

    def test_initial_capture_and_unknown_topics_need_no_previous_map(self):
        original = payload()
        del original['previous_capture']
        result = self.client(update()).workflow(original)
        self.assertEqual(result['workflow']['steps'], [])
        self.assertEqual(len(result['memo_findings']), 11)
        self.assertTrue(all(f['status'] == 'unknown' for f in result['memo_findings']))

    def test_unknown_target_or_mismatched_quote_cannot_delete_anything(self):
        for removed in (removal('missing', source='u2', quote='get water'),
                        removal('S3', source='u2', quote='Delete the entire diagram'),
                        {**removal('S3', source='u2', quote='get water'), 'source_quote': ''},
                        {**removal('S3', source='u2', quote='get water'), 'reason': ''}):
            with self.subTest(removed=removed):
                original = payload()
                before = copy.deepcopy(original)
                with self.assertRaises(server.APIError):
                    self.client(update(remove_steps=[removed])).workflow(original)
                self.assertEqual(original, before)

    def test_assistant_context_and_file_events_cannot_authorize_a_removal(self):
        for source, quote in (('a1', 'How do you decide'), ('context', 'Backlog refinement'),
                              ('file_notice', 'Remove the update step'), ('invented', 'get water')):
            with self.subTest(source=source):
                original = payload()
                original['turns'].append({'id': 'file_notice', 'role': 'user', 'document_event': True,
                                          'text': 'Remove the update step'})
                with self.assertRaises(server.APIError):
                    self.client(update(remove_steps=[removal('S3', source=source, quote=quote)])).workflow(original)

    def test_removal_uses_current_caption_text_even_when_turn_id_is_unchanged(self):
        original = payload()
        original['turns'][2]['text'] = 'Remove the update step; updates belong to another process.'
        result = self.client(update(remove_steps=[removal('S3', source='u2')])).workflow(original)
        self.assertNotIn('S3', [s['id'] for s in result['workflow']['steps']])
        original['turns'][2]['text'] = 'Keep the update step.'
        with self.assertRaises(server.APIError):
            self.client(update(remove_steps=[removal('S3', source='u2')])).workflow(original)

    def test_invalid_edge_or_contradictory_edit_rejects_the_whole_capture(self):
        for patch in (update(upsert_connections=[edge('S1', 'missing')]),
                      update(upsert_steps=[step('S3', 'Updated title', ['u2'])],
                             remove_steps=[removal('S3', source='u2', quote='get water')]),
                      update(remove_connections=[{'from': 'S2', 'to': 'S4', 'label': 'Not reported',
                                                  'reason': 'Remove an edge', 'source_quote': 'get water',
                                                  'evidence_turns': ['u2']}])):
            with self.subTest(patch=patch):
                original = payload()
                before = copy.deepcopy(original)
                with self.assertRaises(server.APIError):
                    self.client(patch).workflow(original)
                self.assertEqual(original, before)

    def test_missing_patch_fields_cannot_be_mistaken_for_a_complete_replacement(self):
        original = payload()
        legacy = {**original['previous_capture']['workflow'], 'memo_findings': [],
                  'summary': '', 'focus': '', 'parking_lot': []}
        legacy['steps'] = []
        legacy['connections'] = []
        with self.assertRaises(server.APIError):
            self.client(legacy).workflow(original)

    def test_memo_retraction_requires_participant_evidence_and_does_not_drop_other_topics(self):
        original = payload()
        retraction = {'key': 'materials', 'status': 'unknown', 'answer': 'Materials no longer established.', 'evidence_turns': []}
        original['turns'].append({'id': 'file_notice', 'role': 'user', 'document_event': True,
                                  'text': 'No materials are established by this document.'})
        for sources in ([], ['context'], ['a1'], ['file_notice'], ['invented']):
            with self.subTest(sources=sources), self.assertRaises(server.APIError):
                self.client(update(memo_findings=[{**retraction, 'evidence_turns': sources}])).workflow(original)
        original['turns'].append({'id': 'u4', 'role': 'user', 'text': 'I withdraw the Jira and Confluence references; I do not know which documents are used.'})
        retraction['evidence_turns'] = ['u4']
        result = self.client(update(memo_findings=[retraction])).workflow(original)
        by_key = {f['key']: f for f in result['memo_findings']}
        self.assertEqual(by_key['materials']['status'], 'unknown')
        self.assertEqual(by_key['lifecycle'], original['previous_capture']['memo_findings'][5])


if __name__ == '__main__':
    unittest.main()
