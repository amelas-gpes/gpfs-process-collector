"""Offline provider adapter boundary tests; no provider calls."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('knowledge_ai', Path(__file__).resolve().parents[1] / 'knowledge_ai.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def account(i, count=1):
    return {'submission_id': f's{i}', 'process_id': f'p{i}', 'revision': 1,
            'scope': 'fund A', 'context': {'process_name': 'Synthetic process'},
            'turns': [{'id': f'u{n}', 'role': 'user', 'text': 'x' * 2000} for n in range(count)]}


class FakeClient:
    def __init__(self): self.calls = []
    def structured(self, *args):
        self.calls.append(args)
        return {'proposals': []}


class AdapterTests(unittest.TestCase):
    def test_no_candidates_does_not_call_provider(self):
        client = FakeClient()
        self.assertEqual(mod.build_analyzer(client)(account(0), []), [])
        self.assertFalse(client.calls)

    def test_inputs_are_bounded_and_limitation_is_explicit(self):
        client = FakeClient()
        mod.build_analyzer(client)(account(0, 20), [account(i) for i in range(1, 12)])
        instructions, payload, schema, name, maximum = client.calls[0]
        self.assertIn('UNTRUSTED DATA', instructions)
        self.assertEqual(len(payload['candidates']), 8)
        self.assertEqual(payload['candidates_omitted'], 3)
        self.assertEqual(payload['submission']['turns_omitted'], 8)
        self.assertEqual(len(payload['submission']['participant_turns'][0]['text']), 1600)
        self.assertTrue(payload['submission']['participant_turns'][0]['excerpt_truncated'])
        self.assertIn('partial bounded sample', payload['coverage_notice'])
        self.assertEqual(name, 'knowledge_connection_proposals')
        self.assertFalse(schema['additionalProperties'])

    def test_malformed_provider_output_is_not_accepted(self):
        client = FakeClient()
        client.structured = lambda *args: {'proposals': [None] * 21}
        with self.assertRaises(ValueError):
            mod.build_analyzer(client)(account(0), [account(1)])

    def test_document_excerpts_are_bounded_and_never_include_scope_capabilities(self):
        client = FakeClient()
        submission = account(0)
        submission['document_scope'] = 'scope-secret'
        submission['document_excerpts'] = [{'document_id': 'd', 'source_id': 'page-1',
                                             'label': 'Page 1', 'text': 'a' * 1300,
                                             'origin':'ai_visual_transcription','verified':False}]
        mod.build_analyzer(client)(submission, [account(1)])
        sent = client.calls[0][1]['submission']
        self.assertNotIn('scope-secret', str(sent))
        self.assertEqual(len(sent['document_excerpts'][0]['text']), 1200)
        self.assertTrue(sent['document_excerpts'][0]['excerpt_truncated'])
        self.assertEqual(sent['document_excerpts'][0]['source_id'], 'page-1')
        self.assertEqual(sent['document_excerpts'][0]['origin'],'ai_visual_transcription')
        self.assertIs(sent['document_excerpts'][0]['verified'],False)

    def test_file_events_and_incompatible_scopes_are_not_provider_inputs(self):
        client=FakeClient();submission=account(0)
        submission['turns'].append({'id':'receipt','role':'user','text':'File received.','document_event':True})
        incompatible=account(1);incompatible['scope']='fund B'
        self.assertEqual(mod.build_analyzer(client)(submission,[incompatible]),[])
        self.assertEqual(client.calls,[])
        compatible=account(2);compatible['scope']=' FUND A '
        mod.build_analyzer(client)(submission,[incompatible,compatible])
        sent=client.calls[0][1]
        self.assertEqual([item['submission_id'] for item in sent['candidates']],['s2'])
        self.assertEqual([item['id'] for item in sent['submission']['participant_turns']],['u0'])


if __name__ == '__main__': unittest.main()
