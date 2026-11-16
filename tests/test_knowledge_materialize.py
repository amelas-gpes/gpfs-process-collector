"""Which map a submitted process graph is built from. Offline SQLite; no analyzer, network or provider."""
import knowledge_rows as rows
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('knowledge_graph',Path(__file__).resolve().parents[1]/'knowledge_graph.py')
kg=importlib.util.module_from_spec(spec);spec.loader.exec_module(kg)

def submission(**changes):
    """A reviewed draft beside the working map that produced it; the two differ so the source is visible."""
    result={'context':{'process_name':'Invoice intake'},'team':'Accounts payable','scope':'Fund A',
            'turns':[{'id':'u1','role':'user','text':'A supplier email starts a case.'},
                     {'id':'u2','role':'user','text':'The analyst registers the invoice.'}],
            'draft':{'title':'Invoice intake','inputs':['Supplier invoice'],'outputs':['Registered case'],
                     'steps':[{'id':'S1','title':'REVIEWER CORRECTED TITLE','type':'activity','actor':'AP analyst','evidence_turns':['u1']},
                              {'id':'S2','title':'Reviewer-added check','type':'decision','evidence_turns':['u2']}],
                     'connections':[{'from':'S1','to':'S2','label':'Reviewed route','evidence_turns':['u2']}]},
            'workflow':{'title':'Working map','inputs':['Unreviewed input'],
                        'steps':[{'id':'S1','title':'Receive and register invoice','type':'activity','evidence_turns':['u1']}],
                        'connections':[]},
            'draft_stale':False,'draft_edited':False}
    result.update(changes)
    return result

class MaterializeSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.graph=kg.KnowledgeGraph(Path(self.temp.name)/'graph.db')
    def tearDown(self): self.graph.close();self.temp.cleanup()
    def stored(self,payload):
        receipt=self.graph.submit(payload)
        entities=[e for e in rows.entities(self.graph) if e['submission_id']==receipt['submission_id'] and e['revision']==receipt['revision']]
        edges=[e for e in rows.edges(self.graph) if e['submission_id']==receipt['submission_id'] and e['revision']==receipt['revision']]
        steps={e['label']:e['data'] for e in entities if e['type'] in ('step','decision')}
        basis={e['type']:e['data'] for e in entities if e['type'] in ('process','process_version')}
        routes=[e['evidence'] for e in edges if e['type']=='happens_after']
        objects={e['label'] for e in entities if e['type']=='business_object'}
        return receipt,steps,basis,routes,objects

    def assert_from_draft(self,steps,routes,objects):
        self.assertEqual(set(steps),{'REVIEWER CORRECTED TITLE','Reviewer-added check'})
        self.assertEqual({data['_materialized_from'] for data in steps.values()},{'draft'})
        self.assertEqual([(route['label'],route['_materialized_from']) for route in routes],[('Reviewed route','draft')])
        self.assertIn('Supplier invoice',objects);self.assertNotIn('Unreviewed input',objects)

    def assert_from_working_map(self,steps,routes,objects):
        self.assertEqual(set(steps),{'Receive and register invoice'})
        self.assertEqual(steps['Receive and register invoice']['_materialized_from'],'workflow')
        self.assertEqual(routes,[]);self.assertIn('Unreviewed input',objects);self.assertNotIn('Supplier invoice',objects)

    def test_reviewer_edited_draft_is_materialized_even_when_flagged_stale(self):
        # The audit's failure: one keystroke flagged the draft, and every reviewer correction was left out of the graph.
        receipt,steps,basis,routes,objects=self.stored(submission(draft_stale=True,draft_edited=True))
        self.assert_from_draft(steps,routes,objects)
        for kind in ('process','process_version'):
            self.assertEqual(basis[kind],{'source':'draft','draft_stale':True,'draft_edited':True})
        detail=self.graph._revision(receipt['submission_id'],receipt['revision'])
        self.assertIs(detail['draft_stale'],True)

    def test_current_draft_is_materialized_and_its_state_is_recorded(self):
        for edited in (False,True):
            with self.subTest(edited=edited):
                receipt,steps,basis,routes,objects=self.stored(submission(draft_edited=edited))
                self.assert_from_draft(steps,routes,objects)
                self.assertEqual(basis['process'],{'source':'draft','draft_stale':False,'draft_edited':edited})


    def test_unedited_stale_draft_still_yields_the_newer_working_map_and_says_so(self):
        receipt,steps,basis,routes,objects=self.stored(submission(draft_stale=True))
        self.assert_from_working_map(steps,routes,objects)
        self.assertEqual(basis['process'],{'source':'workflow','draft_stale':True,'draft_edited':False})
        self.assertEqual(basis['process_version'],basis['process'])
        detail=self.graph._revision(receipt['submission_id'],receipt['revision'])
        self.assertEqual(detail['draft']['steps'][0]['title'],'REVIEWER CORRECTED TITLE','The stored revision keeps the draft as submitted')

    def test_only_a_literal_true_counts_as_reviewer_edited(self):
        for value in ('true',1,None,'yes'):
            with self.subTest(value=value):
                _,steps,basis,routes,objects=self.stored(submission(draft_stale=True,draft_edited=value))
                self.assert_from_working_map(steps,routes,objects)
                self.assertIs(basis['process']['draft_edited'],False)

    def test_stale_draft_with_steps_is_never_replaced_by_an_empty_working_map(self):
        # A reopened file from the committed 0.29.0 build: every draft flagged stale, and often no working map.
        for working in (None,{},{'steps':[]},{'title':'Working map','steps':[],'connections':[]}):
            with self.subTest(working=working):
                receipt,steps,basis,routes,objects=self.stored(submission(draft_stale=True,workflow=working))
                self.assert_from_draft(steps,routes,objects)
                self.assertEqual(basis['process'],{'source':'draft','draft_stale':True,'draft_edited':False})


    def test_reopened_and_resaved_file_keeps_the_reviewed_draft_in_the_graph(self):
        # Save copy, reopen under the earlier build (draft_stale becomes true), then Submit.
        _,steps,basis,routes,objects=self.stored(submission(draft_stale=True,draft_edited=True,workflow=None))
        self.assert_from_draft(steps,routes,objects)
        self.assertEqual(basis['process']['source'],'draft')

    def test_stale_unedited_draft_without_steps_leaves_the_working_map_in_place(self):
        empty_draft={'title':'Invoice intake','overview':'Nothing reviewed yet.','steps':[],'connections':[]}
        _,steps,basis,routes,objects=self.stored(submission(draft_stale=True,draft=empty_draft))
        self.assert_from_working_map(steps,routes,objects)
        self.assertEqual(basis['process'],{'source':'workflow','draft_stale':True,'draft_edited':False})

    def test_working_map_is_materialized_before_any_draft_exists(self):
        for draft in (None,{}):
            with self.subTest(draft=draft):
                receipt,steps,basis,routes,objects=self.stored(submission(draft=draft))
                self.assert_from_working_map(steps,routes,objects)
                self.assertEqual(basis['process'],{'source':'workflow'})


if __name__=='__main__':
    unittest.main()
