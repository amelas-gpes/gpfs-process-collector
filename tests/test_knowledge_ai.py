"""Offline provider adapter boundary tests; no provider calls."""
import importlib.util
from copy import deepcopy
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
    def test_nonempty_scope_schema_requires_exact_current_scope_without_mutating_global_schema(self):
        before=deepcopy(mod.SCHEMA)
        current=account(0);current['scope']='US FA17 documented process; pending owner review'
        other=account(1);other['scope']=current['scope'].upper()
        client=FakeClient();analyze=mod.build_analyzer(client)
        analyze(current,[other])
        instructions,_,first_schema,*_=client.calls[0]
        first_scope=first_schema['properties']['proposals']['items']['properties']['scope']
        self.assertEqual(first_scope['enum'],['',current['scope']])
        properties=first_schema['properties']['proposals']['items']['properties']
        for field in ('source_submission_id','destination_submission_id','condition','explanation','inference'):
            self.assertEqual(properties[field],{'type':'string'})
        self.assertEqual(properties['evidence']['items']['properties']['quote'],{'type':'string'})
        self.assertNotIn(other['scope'],first_scope['enum'])
        self.assertIn('shorten, paraphrase or combine scope labels',instructions)
        current=account(2);current['scope']='Another exact scope';other=account(3);other['scope']=current['scope']
        analyze(current,[other])
        second_schema=client.calls[1][2]
        self.assertEqual(second_schema['properties']['proposals']['items']['properties']['scope']['enum'],['','Another exact scope'])
        self.assertEqual(first_scope['enum'],['','US FA17 documented process; pending owner review'])
        self.assertIsNot(first_schema,second_schema)
        self.assertEqual(mod.SCHEMA,before)
    def test_empty_current_scope_enum_uses_only_exact_selected_candidate_scopes(self):
        before=deepcopy(mod.SCHEMA)
        current=account(0);current['scope']=''
        candidates=[account(i) for i in range(1,11)]
        labels=['Fund A','FUND A','Fund A','','Fund B','Fund C','Fund D','Fund E','Excluded ninth','Excluded tenth']
        for candidate,label in zip(candidates,labels):candidate['scope']=label
        client=FakeClient();mod.build_analyzer(client)(current,candidates)
        schema=client.calls[0][2]
        self.assertEqual(schema['properties']['proposals']['items']['properties']['scope']['enum'],['','Fund A','FUND A','Fund B','Fund C','Fund D','Fund E'])
        self.assertEqual(len(client.calls[0][1]['candidates']),8)
        self.assertEqual(mod.SCHEMA,before)
    def test_document_simulation_provenance_and_attribution_reach_both_provider_accounts(self):
        provenance={'method':'document_simulation',
                    'source_documents':[{'filename':'Reference.pdf','sha256':'b'*64}],
                    'participant_confirmed':False,'process_owner_approved':False}
        submission=account(0);candidate=account(1)
        submission['capture_provenance']={**provenance,'private_scope':'do-not-forward'}
        candidate['capture_provenance']=provenance
        client=FakeClient();mod.build_analyzer(client)(submission,[candidate])
        instructions,sent,schema,*_=client.calls[0]
        for record in (sent['submission'],sent['candidates'][0]):
            self.assertEqual(record['capture_provenance'],provenance)
            self.assertEqual({t['evidence_type'] for t in record['participant_turns']},{'simulated_document_account'})
        self.assertNotIn('do-not-forward',str(sent))
        self.assertIn('not employee testimony',instructions)
        self.assertIn('simulated_document_account',schema['properties']['proposals']['items']['properties']['evidence']['items']['properties']['type']['enum'])
    def test_simulation_provider_context_cannot_claim_participant_confirmation_or_owner_approval(self):
        for key in ('participant_confirmed','process_owner_approved'):
            submission=account(0)
            submission['capture_provenance']={'method':'document_simulation','source_documents':[],
                                             'participant_confirmed':False,'process_owner_approved':False,key:True}
            client=FakeClient()
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'cannot claim confirmation or approval'):
                mod.build_analyzer(client)(submission,[account(1)])
            self.assertEqual(client.calls,[])
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
