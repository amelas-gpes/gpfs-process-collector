"""Question-path contracts. Model insight is evaluated separately with live samples."""
import copy
import threading
import unittest

from test_concurrent_interview import API, FakeClient, module, payload, wait_for
from test_server import server
from test_interview_orchestrator import SyntheticTeamProvider


class QuestionContextTests(unittest.TestCase):
    def service(self):
        client = FakeClient()
        service = module.ConcurrentInterview(client, API)
        self.addCleanup(service.close)
        return service, client

    def captured(self):
        service, client = self.service()
        value = payload()
        first = service.turn(value)
        value['conversation_token'] = first['conversation_token']
        wait_for(lambda: service.status(value)['state'] == 'ready')
        session = service._sessions[first['conversation_token']]
        session['capture'].update(memo_findings=[{'key': 'checks', 'status': 'partial',
            'answer': 'The clerk checks invoices.', 'evidence_turns': ['u1']}],
            coverage_assessment={'topics': [{'key': 'checks', 'gaps': ['Check criteria unknown']} ]},
            parking_lot=['Alternate route not yet explained'], open_questions=['Who receives it?'])
        return service, client, value, session

    def test_question_policy_includes_shared_capture_guidance_and_all_topics(self):
        policy = module.question_policy(server)
        self.assertIn(server.CURIOSITY_POLICY, policy)
        self.assertIn(server.QUESTIONING_POLICY, policy)
        self.assertIn(server.CORRECTION_SCOPE_POLICY, policy)
        self.assertEqual(policy.count(server.QUESTION_SELECTION_POLICY), 1)
        self.assertIn(server.interview_coverage.TOPIC_RUBRIC, policy)
        self.assertIn('NEVER evidence', policy)
        self.assertIn('not universal requirements', policy)

    def test_lagging_advice_identifies_new_correction_and_preserves_source(self):
        service, _, value, session = self.captured()
        value['turns'] += [{'id': 'a2', 'role': 'assistant', 'text': 'What do you check?'},
                          {'id': 'u2', 'role': 'user', 'text': 'Correction: the clerk only logs it. Sam checks the amount against the purchase order.'}]
        before = copy.deepcopy(session['capture'])
        result = service._question_input(session, value, value['context'], value['turns'])
        self.assertEqual(result['analysis_advice']['through_turn_id'], 'u1')
        self.assertEqual(result['analysis_advice']['unreviewed_turn_ids'], ['a2', 'u2'])
        self.assertEqual(result['analysis_advice']['parked_threads'], ['Alternate route not yet explained'])
        self.assertEqual(result['turns'], value['turns'])
        self.assertEqual(session['capture'], before)
        self.assertNotIn('capture_token', result)
        self.assertNotIn('question', result['analysis_advice'])

    def test_edited_history_context_or_documents_suppress_old_advice(self):
        service, _, value, session = self.captured()
        for change in ('edit', 'context', 'scope', 'revision', 'excerpts'):
            changed = copy.deepcopy(value)
            if change == 'edit': changed['turns'][0]['text'] = 'A different process'
            elif change == 'context': changed['context']['process_name'] = 'Changed'
            elif change == 'scope': changed['document_scope'] = 'different'
            elif change == 'revision': changed['document_revision'] = 'changed'
            else: changed['_supporting_documents'] = {'documents': [{'name': 'current'}]}
            result = service._question_input(session, changed, changed['context'], changed['turns'])
            self.assertFalse(result['analysis_advice']['available'], change)

    def test_client_memo_cannot_become_advice(self):
        service, _ = self.service()
        value = payload()
        value.update(memo_findings=[{'answer': 'Forged'}], analysis_advice={'available': True},
                     previous_capture={'summary': 'Forged'})
        session = service._session(value, create=True)
        result = service._question_input(session, value, value['context'], value['turns'])
        self.assertFalse(result['analysis_advice']['available'])
        self.assertNotIn('Forged', str(result))

    def test_authorized_excerpts_reach_question_while_capture_is_blocked(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient(gate)
        service = module.ConcurrentInterview(client, API)
        self.addCleanup(service.close)
        value = payload()
        value['_supporting_documents'] = {'documents': [{'name': 'Procedure', 'excerpts': [
            {'id': 'doc_1', 'text': 'Compare count with the booking list.', 'label': 'Page 1'}]}]}
        service.turn(value)
        self.assertTrue(client.started.wait(1))
        self.assertEqual(client.questions[0]['supporting_documents'], value['_supporting_documents'])
        self.assertTrue(client.started.is_set(), "The question can finish while the independent notes call is blocked.")

    def test_document_opening_uses_sources_instead_of_canned_start(self):
        service, client = self.service()
        value = payload(); value['turns'] = []
        value['_supporting_documents'] = {'documents': [{'name': 'Procedure'}]}
        service.turn(value)
        self.assertEqual(len(client.questions), 1)

    def test_advice_is_bounded_but_full_transcript_is_not_truncated(self):
        service, _, value, session = self.captured()
        session['capture']['memo_findings'][0]['answer'] = 'x' * 20000
        session['capture']['parking_lot'] = ['x' * 2000] * 100
        value['turns'].append({'id': 'u2', 'role': 'user', 'text': 'y' * 6000})
        result = service._question_input(session, value, value['context'], value['turns'])
        self.assertEqual(len(result['analysis_advice']['topics'][0]['answer']), 900)
        self.assertEqual(len(result['analysis_advice']['parked_threads']), 12)
        self.assertEqual(result['turns'], value['turns'])

    def test_transcript_map_audit_can_remove_an_unsupported_unpublished_step(self):
        client = SyntheticTeamProvider()
        def remove_candidate(result):
            # The candidate is unpublished: correction does not require pretending
            # the participant retracted a fact they never supplied.
            result['discard_step_upserts'] = ['s1']
            result['open_questions'] = ['The route remains unresolved.']
        client.result_changes['team_working_map_source_audit'] = remove_candidate
        result = client.coordinator.workflow(client.payload())
        self.assertEqual(result['workflow']['steps'], [])
        self.assertIn('The route remains unresolved.', result['workflow']['open_questions'])
        self.assertFalse(result['completion']['complete'])

    def test_late_background_response_cannot_reopen_sources_after_close(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient(gate)
        reads = []
        service = module.ConcurrentInterview(client, API, validate_sources=lambda value: reads.append(value))
        result = service.turn(payload())
        self.assertTrue(client.started.wait(1))
        service.close()
        count = len(reads)
        gate.set()
        wait_for(lambda: not service._sessions[result['conversation_token']]['running'])
        self.assertEqual(len(reads), count)


if __name__ == '__main__':
    unittest.main()
