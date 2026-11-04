"""On-demand draft model selection and bounded stage execution."""
import copy
import unittest
from unittest.mock import Mock

from test_server import server, process_draft, interview_payload, incomplete_assessment


class DraftRoutingTests(unittest.TestCase):
    def test_draft_override_applies_to_generation_audit_and_coverage(self):
        client = server.OpenAIClient({'OPENAI_API_KEY':'fictional',
            'INTERVIEW_MODEL':'legacy-model', 'DRAFT_MODEL':'chosen-draft-model'})
        draft = process_draft()
        draft['memo_summary'][0].update(status='captured', answer='The process is called invoice approval.',
                                       evidence_turns=['context'])
        assessment = incomplete_assessment(draft['memo_summary'])
        for topic in assessment['topics']:
            topic['capture_repair'] = {'needed': False}
        client.structured = Mock(side_effect=[copy.deepcopy(draft), copy.deepcopy(draft), assessment])
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
