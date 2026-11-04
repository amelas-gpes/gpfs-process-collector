"""Synthetic regressions from an equipment-setup interview; no provider calls."""
import copy
import unittest

from test_server import server
import capture_facts as facts
from test_capture_facts import transaction, operation, from_model_input, typed_responder
from test_interview_orchestrator import SyntheticTeamProvider


class EquipmentDiscussionTests(unittest.TestCase):
    def setUp(self):
        self.context = {'process_name': ''}
        self.turns = [
            {'id': 'a1', 'role': 'assistant', 'text': 'What work would you like to describe?'},
            {'id': 'u1', 'role': 'user', 'text': 'Preparing my inspection drone.'},
            {'id': 'a2', 'role': 'assistant', 'text': 'What do you do first?'},
            {'id': 'u2', 'role': 'user', 'text': 'I fetch the case and remove the drone.'},
            {'id': 'a3', 'role': 'assistant', 'text': 'What happens next?'},
            {'id': 'u3', 'role': 'user', 'text': 'If the drone is missing from the case, I fetch the spare drone.'},
        ]
        self.operations = [
            operation('name', 'The work is preparing the participant’s inspection drone.', 'u1'),
            operation('lifecycle', 'The participant fetches the case and removes the drone.', 'u2'),
            operation('lifecycle', 'If the drone is missing, the participant fetches the spare drone.', 'u3'),
            operation('variations', 'Missing equipment changes the route: the participant fetches the spare drone.', 'u3'),
        ]

    def capture(self):
        state = facts.empty_state()
        delta = transaction(state, self.operations, {'name': 'partial', 'lifecycle': 'partial', 'variations': 'partial'})
        server.check_schema(delta, facts.schema_for(state, ['u1', 'u2', 'u3']))
        return facts.apply_delta(state, delta, self.context, self.turns, [])

    def test_conditional_equipment_route_can_support_two_distinct_incomplete_topics(self):
        state = self.capture()
        by_key = {row['key']: row for row in facts.findings(state)}
        progress = {row['key']: row for row in facts.discussion(state)}
        self.assertEqual(by_key['variations']['status'], 'partial')
        self.assertEqual(by_key['variations']['evidence_turns'], ['u3'])
        self.assertIn('spare drone', by_key['lifecycle']['answer'])
        self.assertEqual({row['key'] for row in progress.values() if row['discussed']},
                         {'name', 'lifecycle', 'variations'})
        self.assertEqual(progress['variations']['evidence_turns'], ['u3'])
        self.assertFalse(server.memo_has_enough_detail(facts.findings(state)))

    def test_first_activity_does_not_establish_the_initiating_event(self):
        state = self.capture()
        trigger = next(row for row in facts.findings(state) if row['key'] == 'trigger')
        discussion = next(row for row in facts.discussion(state) if row['key'] == 'trigger')
        self.assertEqual(trigger['status'], 'unknown')
        self.assertEqual(trigger['evidence_turns'], [])
        self.assertEqual(discussion, {'key': 'trigger', 'discussed': False, 'evidence_turns': []})

    def test_model_absence_note_is_not_an_explored_topic(self):
        state = facts.empty_state()
        delta = transaction(state, [operation('risk', 'The consequences of failure are unknown.', 'u2', kind='gap')])
        state = facts.apply_delta(state, delta, self.context, self.turns, [])
        self.assertEqual(state['topics']['risk']['status'], 'partial')
        row = next(row for row in facts.discussion(state) if row['key'] == 'risk')
        self.assertEqual(row, {'key': 'risk', 'discussed': False, 'evidence_turns': []})

    def test_changed_or_removed_testimony_cannot_keep_old_discussion_evidence(self):
        state = self.capture()
        changed = copy.deepcopy(self.turns)
        changed[-1]['text'] = 'The equipment is always in its case.'
        rebased = facts.rebase(state, self.context, changed, [])
        variation = next(row for row in facts.discussion(rebased) if row['key'] == 'variations')
        self.assertFalse(variation['discussed'])
        self.assertEqual(variation['evidence_turns'], [])

    def test_authoritative_coordinator_publishes_discussion_separately_from_completion(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        payload['context']['process_name'] = ''
        payload['turns'] = copy.deepcopy(self.turns)
        typed_responder(client, lambda model_input: from_model_input(model_input, self.operations,
            {'name': 'partial', 'lifecycle': 'partial', 'variations': 'partial'}))
        result = client.coordinator.interview(payload)
        self.assertEqual(next(row for row in result['topic_discussion'] if row['key'] == 'variations'),
                         {'key': 'variations', 'discussed': True, 'evidence_turns': ['u3']})
        self.assertFalse(result['coverage_verified'])
        self.assertFalse(result['completion']['complete'])
        self.assertFalse(result['completion']['ready_for_final_check'])


if __name__ == '__main__':
    unittest.main()
