"""Positive and negative controls for reported prerequisites and handoffs."""
import copy
import unittest

from test_server import server
from test_route_grounding import step


class PrerequisiteFidelityTests(unittest.TestCase):
    def test_new_and_prior_schedule_are_distinct_and_repeated_proof_rejoins_the_gate(self):
        nodes = [step('old', 'Tie figures to prior schedules'), step('proof', 'Does the change net to zero?'),
                 step('new', 'Build new dated schedule')]
        wf = {'steps':nodes, 'connections':[
            {'from':'old','to':'proof','label':'','evidence_turns':['u']},
            {'from':'proof','to':'new','label':'Change across all members nets to zero','evidence_turns':['u']}],
            'open_questions':['Owner review needed before Tie figures to prior schedules: The change across all members must net to zero (u).',
                              'Where are prior schedules stored?']}
        source = 'The change across all members must net to zero before building a new dated schedule.'
        self.assertEqual(server.omitted_gates(wf, {'u':source}), {})
        server.route_review_record(wf, {}, {}, [{'role':'user','id':'u','text':source}], [])
        self.assertEqual(wf['open_questions'], ['Where are prior schedules stored?'])

    def test_both_independent_prerequisites_survive_and_only_the_absent_one_remains(self):
        guards = ['Compliance must finish sanctions screening before Treasury can release the payment.',
                  'An independent verifier must complete callback before Treasury can release the payment.']
        wf = {'steps':[step('r','Release the payment')],'connections':[]}
        for sentences in (guards, guards[::-1]):
            gap = server.omitted_gates(wf, {'u':' '.join(sentences)})['r']
            self.assertIn('sanctions screening',gap)
            self.assertIn('callback',gap)
        sanctions = {**step('s','Finish sanctions screening'),'actor':'Compliance'}
        wf['steps'].append(sanctions)
        wf['connections'].append({'from':'s','to':'r','label':'Screening complete'})
        gap = server.omitted_gates(wf, {'u':' '.join(guards)})['r']
        self.assertIn('callback',gap)
        self.assertNotIn('sanctions screening',gap)

    def workflow(self):
        a={**step('a','Inspect shipment',sources=['u']),'actor':'Supervisor'}
        b={**step('b','Dispatch sealed parcel',sources=['u']),'actor':'Clerk'}
        return {'steps':[a,b], 'connections':[], 'open_questions':[
            'What handoff or prerequisite, if any, connects Inspect shipment to Dispatch sealed parcel (proposed condition: After approval)?']}

    def test_recovered_conditional_handoff_is_quoted_and_filing_preserves_it(self):
        wf = self.workflow()
        turns=[{'id':'u','role':'user','text':'The supervisor inspects the shipment. After approval we dispatch the sealed parcel.'}]
        assurance=server.route_review_record(wf,{}, {},turns,[])
        self.assertEqual(wf['connections'],[{'from':'a','to':'b','label':'After approval','evidence_turns':['u']}])
        self.assertEqual(assurance[0]['status'],'supported')
        self.assertEqual(assurance[0]['passages'][0]['quote'],turns[0]['text'])
        self.assertFalse(any('handoff or prerequisite' in q for q in wf['open_questions']))
        wf['route_assurance']=assurance
        before=copy.deepcopy(wf)
        server.revalidate_filed_routes(wf,{},turns,[])
        self.assertEqual(wf,before)

    def test_recovery_does_not_drop_conditions_or_revive_a_superseded_handoff(self):
        positive='The supervisor inspects the shipment. After approval we dispatch the sealed parcel.'
        for source,correction in [
            (positive, 'We no longer dispatch the sealed parcel after inspection.'),
            (positive+' Correction: we never dispatch the sealed parcel here.', ''),
            ('The supervisor logs the shipment. After approval we dispatch the sealed parcel.', ''),
            ('The supervisor inspects the building. After approval we dispatch the sealed parcel.', ''),
            ('The operator inspects the shipment. After approval we dispatch the sealed parcel.', ''),
            ('The supervisor inspects the shipment. After approval we dispatch the sealed parcel only if Legal clears it.', ''),
            ('The supervisor inspects the shipment. After approval we might dispatch the sealed parcel.', ''),
            ('The supervisor inspects the shipment. After approval we dispatch the sealed manifest.', ''),
        ]:
            wf=self.workflow()
            turns=[{'id':'u','role':'user','text':source}]
            if correction:
                turns.append({'id':'c','role':'user','text':correction})
            with self.subTest(source=source,correction=correction):
                self.assertEqual(server.route_review_record(wf,{}, {},turns,[]),[])
                self.assertFalse(wf['connections'])
                self.assertIn('handoff or prerequisite',wf['open_questions'][0])

    def test_new_map_can_recover_an_unproposed_route_but_filing_respects_edits(self):
        wf = self.workflow()
        wf['steps'][0]['type'] = 'start'
        wf['open_questions'] = []
        turns = [{'id':'u','role':'user','text':'The supervisor inspects the shipment. After approval we dispatch the sealed parcel.'}]
        saved = copy.deepcopy(wf)
        saved['route_assurance'] = []
        server.revalidate_filed_routes(saved,{},turns,[])
        self.assertEqual(saved['connections'],[])
        receipt = server.route_review_record(wf,{}, {},turns,[],client=object())
        self.assertEqual([(e['from'],e['to'],e['status']) for e in receipt],[('a','b','supported')])

    def test_shared_predecessor_does_not_order_both_outcomes(self):
        statement='The final steps are reviewer checks, protection of final schedules and updates to GP-01 and GP-06, in that order.'
        source='A reviewer checks the package before final schedules are protected and GP-01 and GP-06 are updated.'
        self.assertEqual(server.gpfs_interview.grounded_sequence(statement,[source]),source)
        supported='We protect final schedules, then update GP-01 and GP-06.'
        self.assertEqual(server.gpfs_interview.grounded_sequence(statement,[source,supported]),statement)
        unrelated='A supervisor checks the seals before letters and parcels arrive.'
        self.assertEqual(server.gpfs_interview.grounded_sequence(statement,[unrelated]),statement)
        unchanged='We protect the schedules and update the accounts.'
        self.assertEqual(server.gpfs_interview.grounded_sequence(unchanged,[source]),unchanged)
