"""A revision keeps the participant, team, department and scope it does not send (live-draft-knowledge-2).

Offline SQLite plus loopback HTTP round trips; no analyzer, provider or external network.
"""
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server

spec=importlib.util.spec_from_file_location('knowledge_graph',Path(__file__).resolve().parents[1]/'knowledge_graph.py')
kg=importlib.util.module_from_spec(spec);spec.loader.exec_module(kg)

FIELDS=('participant','team','department','scope')
FIRST={'participant':'Fictional vendor master coordinator','team':'Procurement Operations (fictional)','department':'Finance (fictional)','scope':'Fund A'}

def submission(answers=1,**changes):
    turns=[]
    for number in range(1,answers+1):
        turns.append({'id':f't{2*number-1:03d}','role':'assistant','text':f'Question {number}?'})
        turns.append({'id':f't{2*number:03d}','role':'user','text':f'Answer {number} describes one part of the work.'})
    result={'context':{'process_name':'Vendor Onboarding'},'turns':turns,'draft':None,
            'workflow':{'title':'Vendor Onboarding','steps':[{'id':'S1','title':'Register the vendor','actor':'Coordinator','evidence_turns':['t002']}],'connections':[]},
            'memo_findings':[]}
    result.update(changes)
    return result


class RevisionAttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.graph=kg.KnowledgeGraph(Path(self.temp.name)/'graph.db')
    def tearDown(self): self.graph.close();self.temp.cleanup()
    def detail(self,receipt):
        return self.graph.admin_detail('submission',receipt['submission_id'],receipt['revision'])['item']
    def attribution(self,receipt):
        item=self.detail(receipt);return {key:item.get(key) for key in FIELDS}

    def test_revision_without_the_fields_keeps_what_the_previous_revision_recorded(self):
        first=self.graph.submit(submission(**FIRST))
        second=self.graph.submit(submission(2,process_id=first['process_id']))
        self.assertEqual(second['revision'],2)
        self.assertEqual(self.attribution(second),FIRST)
        # The finding's symptom: the current revision dropped out of a team-filtered view.
        current=self.graph.admin_browse('submissions',{'team':'Procurement','latest_only':True})['items']
        self.assertEqual([(row['revision'],row['team']) for row in current],[(2,FIRST['team'])])
        scoped=self.graph.admin_browse('submissions',{'scope':'Fund A','latest_only':True})['items']
        self.assertEqual([row['revision'] for row in scoped],[2])
        # The graph entities of the revision carry the team again.
        teams=self.graph.admin_browse('entities',{'team':'Procurement','latest_only':True})['items']
        self.assertTrue(any(row['revision']==2 for row in teams),teams)

    def test_inheritance_is_per_field_and_follows_the_latest_revision(self):
        first=self.graph.submit(submission(**FIRST))
        second=self.graph.submit(submission(2,process_id=first['process_id'],team='Vendor Master Data',scope=''))
        self.assertEqual(self.attribution(second),{**FIRST,'team':'Vendor Master Data','scope':''})
        third=self.graph.submit(submission(3,process_id=first['process_id'],participant='Second coordinator (fictional)'))
        self.assertEqual(self.attribution(third),{'participant':'Second coordinator (fictional)','team':'Vendor Master Data',
                                                  'department':FIRST['department'],'scope':''},
                         'A field cleared in revision 2 stays cleared; the others come from revision 2, not revision 1')
        self.assertEqual(self.attribution(first),FIRST,'Earlier revisions are not rewritten')

    def test_field_sent_empty_is_cleared(self):
        first=self.graph.submit(submission(**FIRST))
        second=self.graph.submit(submission(2,process_id=first['process_id'],participant='',team='',department='',scope=''))
        self.assertEqual(self.attribution(second),dict.fromkeys(FIELDS,''))
        self.assertEqual(self.graph.admin_browse('submissions',{'team':'Procurement','latest_only':True})['items'],[])
        # None is not a value a browser sends; it is treated like an empty field, as before.
        third=self.graph.submit(submission(3,process_id=first['process_id'],team=None,scope='Fund B'))
        self.assertEqual(self.attribution(third),{'participant':'','team':'','department':'','scope':'Fund B'})

    def test_new_process_inherits_nothing(self):
        self.graph.submit(submission(**FIRST))
        other=self.graph.submit(submission(context={'process_name':'Vendor Offboarding'}))
        self.assertEqual(self.attribution(other),dict.fromkeys(FIELDS,''))

    def test_retry_of_a_revision_returns_the_same_receipt_and_stores_nothing_new(self):
        first=self.graph.submit(submission(**FIRST))
        key='11111111-1111-4111-8111-111111111111'
        second=self.graph.submit(submission(2,process_id=first['process_id'],submission_key=key))
        again=self.graph.submit(submission(2,process_id=first['process_id'],submission_key=key))
        self.assertEqual((again['submission_id'],again['revision']),(second['submission_id'],2))
        self.assertEqual(self.attribution(second),FIRST)
        with self.assertRaisesRegex(ValueError,'different content'):
            self.graph.submit(submission(2,process_id=first['process_id'],submission_key=key,team='Another team'))

    def test_invalid_field_is_still_rejected_and_nothing_is_stored(self):
        first=self.graph.submit(submission(**FIRST))
        for bad in ({'team':'x'*501},{'scope':7},{'participant':['Dana']}):
            with self.assertRaises(ValueError,msg=bad):
                self.graph.submit(submission(2,process_id=first['process_id'],**bad))
        self.assertEqual([row['revision'] for row in self.graph.admin_browse('submissions')['items']],[1])

    def test_submissions_list_marks_revisions_that_a_later_one_replaced(self):
        first=self.graph.submit(submission(**FIRST))
        self.assertEqual([(row['revision'],row['latest']) for row in self.graph.admin_browse('submissions')['items']],[(1,True)])
        self.graph.submit(submission(2,process_id=first['process_id']))
        other=self.graph.submit(submission(context={'process_name':'Vendor Offboarding'}))
        rows={(row['submission_id'],row['revision']):row['latest'] for row in self.graph.admin_browse('submissions')['items']}
        self.assertEqual(rows,{(first['submission_id'],1):False,(first['submission_id'],2):True,(other['submission_id'],1):True})


class RevisionAttributionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.httpd=server.InterviewServer(('127.0.0.1',0),server.Handler,client=server.OpenAIClient({}),
            documents_root=Path(self.temp.name)/'documents',knowledge_root=Path(self.temp.name)/'graph',
            knowledge_settings={'COLLECTOR_DEPLOYMENT_MODE':'local','KNOWLEDGE_LOCAL_OWNER':'true'})
        self.worker=threading.Thread(target=self.httpd.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.worker.start()
    def tearDown(self):
        self.httpd.shutdown();self.httpd.server_close();self.worker.join(timeout=3);self.temp.cleanup()
    def post(self,path,payload):
        request=Request(f'http://127.0.0.1:{self.httpd.server_port}'+path,data=json.dumps(payload).encode(),
                        headers={'Content-Type':'application/json','X-CSRF-Token':self.httpd.csrf_token})
        try:
            with urlopen(request,timeout=5) as response: return response.status,json.loads(response.read())
        except HTTPError as error: return error.code,json.loads(error.read())

    def test_revision_submitted_with_untouched_fields_stays_attributed_in_admin(self):
        code,first=self.post('/api/knowledge/submit',submission(**FIRST))
        self.assertEqual(code,202,first)
        # What the browser sends for a revision whose form was not touched in a file saved before the fix.
        code,second=self.post('/api/knowledge/submit',submission(2,process_id=first['process_id']))
        self.assertEqual(code,202,second);self.assertEqual(second['revision'],2)
        code,detail=self.post('/api/knowledge/admin/detail',{'kind':'submission','id':second['submission_id'],'revision':2})
        self.assertEqual(code,200,detail)
        self.assertEqual({key:detail['item'][key] for key in FIELDS},FIRST)
        code,page=self.post('/api/knowledge/admin/browse',{'section':'submissions','filters':{'team':'Procurement'}})
        self.assertEqual(code,200,page)
        self.assertEqual(sorted((row['revision'],row['team'],row['latest']) for row in page['items']),
                         [(1,FIRST['team'],False),(2,FIRST['team'],True)])
        code,page=self.post('/api/knowledge/admin/browse',{'section':'submissions','filters':{'team':'Procurement','latest_only':True}})
        self.assertEqual([row['revision'] for row in page['items']],[2])


if __name__=='__main__':
    unittest.main()
