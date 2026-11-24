"""Question-grounding regressions using the process library's participant testimony."""
import json
from pathlib import Path
import unittest

from test_concurrent_interview import FakeClient, module
from test_server import server

LIBRARY_CASES = Path(__file__).resolve().parents[1] / 'docs/testing/runs/2026-11-16-process-capture/interviews'
ONBOARDING = 'When FA-05 does not accept the handoff, what happens to onboarding?'
PROVENANCE = 'Does GP-03 describe the process as it is currently carried out, or only its written requirements?'


def archived(process):
    return json.loads((LIBRARY_CASES / (process + '.json')).read_text(encoding='utf-8'))


class InterviewPremises(unittest.TestCase):
    def deliver(self, candidate, turns, context):
        client = FakeClient()
        client.question = candidate
        service = module.ConcurrentInterview(client, server)
        try:
            response = service.turn({'context':context, 'turns':turns, 'action':'answer', '_supporting_documents':{}})
            self.assertTrue(response['speech_authorization']['approved'])
            self.assertEqual(response['speech_authorization']['text'], response['question'])
            self.assertEqual(len(client.questions),1)
            return response['question']
        finally:
            service.close()

    def test_unreported_rejection_is_conditional_on_real_onboarding_account(self):
        case = archived('FA-07')
        self.assertEqual(self.deliver(ONBOARDING,case['turns'][:7],case['context']),
                         ONBOARDING.replace('When ','If ',1))

    def test_an_established_branch_and_an_actual_handoff_time_remain_askable(self):
        turns = [{'id':'u','role':'user','text':'If FA-05 rejects the handoff, work stops until corrected.'}]
        self.assertEqual(self.deliver(ONBOARDING,turns,{'process_name':'Onboarding'}),ONBOARDING)
        self.assertEqual(module.grounded_interview_question('When does FA-05 accept the handoff?',{},turns),
                         'When does FA-05 accept the handoff?')
        # Another process rejecting the same item cannot establish that FA-05 rejects it.
        turns[0]['text'] = 'FA-20 rejects the handoff if clearance is missing.'
        self.assertTrue(module.grounded_interview_question(ONBOARDING,{},turns).startswith('If '))
        turns.append({'id':'u2','role':'user','text':'FA-05 cannot reject the handoff.'})
        self.assertEqual(module.grounded_interview_question(ONBOARDING,{},turns),
                         'What confirms that this handoff is complete?')

    def test_active_file_can_establish_a_branch_but_a_parked_file_cannot(self):
        doc={'excerpts':[{'text':'FA-05 rejects the handoff when the submission is incomplete.'}]}
        self.assertEqual(module.grounded_interview_question(ONBOARDING,{},[],{'documents':[doc]}),ONBOARDING)
        doc['disposition']='parked'
        self.assertTrue(module.grounded_interview_question(ONBOARDING,{},[],{'documents':[doc]}).startswith('If '))

    def test_written_only_gp03_skips_reconfirmation_but_retains_scope_questions(self):
        case=archived('GP-03')
        context={'process_name':case['context']['process_name'],'background':'Documentary role-play from GP-03. I report written requirements rather than firsthand work.'}
        turns=case['turns'][:11]
        result=self.deliver(PROVENANCE,turns,context)
        self.assertIn('procedure',result)
        self.assertNotIn('currently carried out',result)
        scope='Does the written procedure cover a single client or all participating funds?'
        self.assertEqual(module.grounded_interview_question(scope,context,turns),scope)
        self.assertEqual(module.grounded_interview_question(PROVENANCE,{'background':'We have a procedure.'},turns),PROVENANCE)
        turns=turns+[{'id':'actual','role':'user','text':'I can now confirm current practice.'}]
        self.assertEqual(module.grounded_interview_question(PROVENANCE,context,turns),PROVENANCE)
