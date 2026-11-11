"""On-demand draft model selection and bounded stage execution."""
import copy
import unittest
from unittest.mock import Mock

from test_server import server, process_draft, interview_payload, incomplete_assessment, fixture_draft_audit


class DraftRoutingTests(unittest.TestCase):
    def test_unusable_candidate_route_inventory_stops_before_the_audit_call(self):
        edge = process_draft()['connections'][0]
        for candidate in (None, {}, {'connections':{}}, {'connections':[{}]}, {'connections':[edge]*151}):
            with self.subTest(candidate_type=type(candidate).__name__):
                client = server.OpenAIClient({'OPENAI_API_KEY':'fictional'})
                client.structured = Mock(return_value=candidate)
                with self.assertRaisesRegex(server.APIError, 'connections'):
                    client.draft(interview_payload())
                client.structured.assert_called_once()

    def test_draft_preserves_a_supported_transition_and_leaves_an_unverified_reverse_open(self):
        payload = interview_payload()
        draft = process_draft()
        original = draft['connections'][0]
        reverse = {**original, 'from':original['to'], 'to':original['from'], 'label':'Retry'}
        draft['connections'].append(reverse)
        reviewed = fixture_draft_audit(draft, payload['turns'])
        reviewed['route_support'][1]['passages'] = [{'source_id':'u2','quote':'I return it to the clerk.'}]
        client = server.OpenAIClient({'OPENAI_API_KEY':'fictional'})
        client.structured = Mock(side_effect=[copy.deepcopy(draft), reviewed])
        result = client.draft(payload)['draft']
        self.assertEqual(result['connections'], [original])
        self.assertEqual(result['steps'], draft['steps'])
        self.assertNotIn('route_support', result)
        self.assertTrue(any('Retry' in q and 'handoff or prerequisite' in q for q in result['open_questions']))

    def test_intake_objective_and_archived_file_are_not_evidence_of_a_new_transition(self):
        quote = 'Send the approved entry from accounting to the buyer.'
        docs = [{'id':'doc_ref', 'text':quote, 'retained_only':True}]
        for source in ('context', 'doc_ref'):
            edge = {'from':'a','to':'b','label':'Approved','evidence_turns':[source]}
            reviewed = [{'from':'a','to':'b','label':'Approved','passages':[{'source_id':source,'quote':quote}]}]
            steps = [{'id':'a','title':'Approve'}, {'id':'b','title':'Buyer receives the entry'}]
            accepted, gaps = server.grounded_routes([edge], reviewed, steps, {'objective':quote}, [], docs)
            self.assertFalse(accepted)
            self.assertTrue(gaps)
            accepted, gaps = server.grounded_routes([edge], reviewed, steps, {'background':quote}, [], [{**docs[0], 'retained_only':False}])
            self.assertEqual(accepted, [edge])
            self.assertFalse(gaps)

    def test_repeated_draft_edge_combines_citations_and_keeps_other_outcomes(self):
        turns = [{'id':'u1','role':'user','text':'Send approved requests to Intake.'},
                 {'id':'u2','role':'user','text':'Yes, Intake receives those approvals and the referrals too.'}]
        first = {'from':'a','to':'b','label':'Approved','evidence_turns':['u1']}
        same = {**first,'evidence_turns':['u2']}
        other = {**same,'label':'Referral'}
        edges = [first, same, other]
        result, gaps = server.grounded_routes(edges, fixture_draft_audit({'connections':edges}, turns)['route_support'],
            [{'id':'a','title':'Assess request'},{'id':'b','title':'Triage case'}], {}, turns, [])
        self.assertEqual(result, [{**first, 'evidence_turns':['u1','u2']}, other])
        self.assertFalse(gaps)

    def test_joint_dependencies_with_unknown_order_need_no_individual_handoff_quote(self):
        turns = [{'role':'user','id':'u1','text':'Both checks are required for release. We have no prescribed order.'}]
        steps = [{'id':'a','title':'Assess identity'}, {'id':'b','title':'Inspect goods'}, {'id':'c','title':'Release goods'}]
        edges = [{'from':source,'to':'c','label':'Both checks complete','evidence_turns':['u1']} for source in ('a','b')]
        reviewed = fixture_draft_audit({'connections':edges}, turns)['route_support']
        accepted, gaps = server.grounded_routes(edges, reviewed, steps, {}, turns, [])
        self.assertEqual(accepted, edges)
        self.assertFalse(gaps)
        for instructions in (server.WORKFLOW_INSTRUCTIONS, server.WORKFLOW_AUDIT_INSTRUCTIONS,
                             server.DRAFT_INSTRUCTIONS, server.DRAFT_AUDIT_INSTRUCTIONS):
            self.assertIn(server.REQUIRED_DEPENDENCY_POLICY, instructions)

    def test_draft_override_applies_to_generation_audit_and_coverage(self):
        client = server.OpenAIClient({'OPENAI_API_KEY':'fictional',
            'INTERVIEW_MODEL':'legacy-model', 'DRAFT_MODEL':'chosen-draft-model'})
        draft = process_draft()
        draft['memo_summary'][0].update(status='captured', answer='The process is called invoice approval.',
                                       evidence_turns=['context'])
        assessment = incomplete_assessment(draft['memo_summary'])
        for topic in assessment['topics']:
            topic['capture_repair'] = {'needed': False}
        client.structured = Mock(side_effect=[copy.deepcopy(draft), fixture_draft_audit(draft, interview_payload()['turns']), assessment])
        result = client.draft(interview_payload())
        self.assertIn('draft', result)
        self.assertEqual(client.structured.call_count, 3)
        self.assertTrue(all(call.kwargs['model_override'] == 'chosen-draft-model'
                            for call in client.structured.call_args_list))
        self.assertEqual(client.structured.call_args_list[0].kwargs['request_timeout'], 120)
        self.assertEqual(client.structured.call_args_list[1].kwargs['request_timeout'], 240)
        self.assertIsNot(result['coverage_assessment'].get('review_available'), False)
        self.assertEqual(client.public_config()['models']['draft'], 'chosen-draft-model')

    def test_unset_draft_model_reuses_configured_process_model(self):
        client = server.OpenAIClient({'INTERVIEW_MODEL':'legacy-model',
            'AGENT_PROCESS_MODEL':'configured-process-model'})
        self.assertEqual(client.draft_model, 'configured-process-model')
        self.assertEqual(client.model, 'legacy-model')


if __name__ == '__main__':
    unittest.main()
