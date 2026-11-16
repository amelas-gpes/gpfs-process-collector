"""How far the notes and the working map reached when a process was submitted.

Offline SQLite plus one loopback HTTP round trip; no analyzer, provider or external network.
"""
import knowledge_rows as rows
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

def submission(capture=None,**changes):
    """Six participant answers; the working map and the notes may stop at an earlier one."""
    turns=[]
    for number in range(1,7):
        turns.append({'id':f't{2*number-1:03d}','role':'assistant','text':f'Question {number}?'})
        turns.append({'id':f't{2*number:03d}','role':'user','text':f'Answer {number} describes one part of the work.'})
    result={'context':{'process_name':'Invoice intake'},'turns':turns,'draft':None,
            'workflow':{'title':'Invoice intake','steps':[{'id':'S1','title':'Receive invoice','evidence_turns':['t010']}],'connections':[]},
            'memo_findings':[]}
    if capture is not None: result['capture']=capture
    result.update(changes)
    return result

COMPLETE={'in_progress':False,'notes_current':True,'map_current':True,'notes_through_turn':'t012','map_through_turn':'t012'}
BEHIND={'in_progress':False,'notes_current':False,'map_current':False,'notes_through_turn':'t010','map_through_turn':'t010'}

class CaptureStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.graph=kg.KnowledgeGraph(Path(self.temp.name)/'graph.db')
    def tearDown(self): self.graph.close();self.temp.cleanup()
    def stored(self,payload):
        receipt=self.graph.submit(payload)
        detail=self.graph._revision(receipt['submission_id'],receipt['revision'])
        return detail

    def test_lagging_capture_is_stored_with_counts(self):
        # The audit's case: answer 6 submitted while notes and map still stood at answer 5.
        detail=self.stored(submission(BEHIND))
        self.assertEqual(detail['capture'],{**BEHIND,'answers':6,'notes_answers':5,'map_answers':5})
        self.assertEqual(len([t for t in detail['turns'] if t['role']=='user']),6,'The full transcript is stored regardless')

    def test_complete_capture_is_recorded(self):
        detail=self.stored(submission(COMPLETE))
        self.assertEqual(detail['capture'],{**COMPLETE,'answers':6,'notes_answers':6,'map_answers':6})

    def test_each_part_and_running_work_are_recorded(self):
        cases=({**COMPLETE,'in_progress':True},
               {**COMPLETE,'notes_current':False,'notes_through_turn':None},
               {**COMPLETE,'map_current':False,'map_through_turn':'t002'})
        for capture in cases:
            with self.subTest(capture=capture):
                detail=self.stored(submission(capture,context={'process_name':json.dumps(capture)}))
                self.assertEqual(detail['capture']['answers'],6)
        nothing=self.graph._revision(self.graph.submit(submission({**COMPLETE,'notes_current':False,'notes_through_turn':None},context={'process_name':'none'}))['submission_id'],1)
        self.assertEqual(nothing['capture']['notes_answers'],0)

    def test_unknown_coverage_is_kept_as_unknown(self):
        unknown={'in_progress':False,'notes_current':None,'map_current':None,'notes_through_turn':None,'map_through_turn':None}
        detail=self.stored(submission(unknown))
        self.assertEqual(detail['capture'],{**unknown,'answers':6,'notes_answers':None,'map_answers':None})

    def test_submission_without_a_marker_stays_valid(self):
        for capture in (None,'absent'):
            with self.subTest(capture=capture):
                payload=submission(context={'process_name':str(capture)})
                if capture is None: payload['capture']=None
                detail=self.stored(payload)
                self.assertNotIn('capture',detail)

    def test_malformed_or_contradictory_markers_are_rejected_and_nothing_is_stored(self):
        invalid=('yes',[],{},{**COMPLETE,'in_progress':'no'},{**COMPLETE,'in_progress':1},{**COMPLETE,'notes_current':'true'},
                 {**COMPLETE,'map_current':0},{**COMPLETE,'extra':'field'},
                 {**COMPLETE,'notes_through_turn':'t999'},          # not in the transcript
                 {**COMPLETE,'map_through_turn':'t011'},            # an interviewer turn
                 {**COMPLETE,'notes_through_turn':'t010'},          # claims current but stops early
                 {**COMPLETE,'map_through_turn':None},              # claims current but names no answer
                 {**BEHIND,'notes_through_turn':['t010']})
        for capture in invalid:
            with self.subTest(capture=capture),self.assertRaisesRegex(ValueError,'capture state'):
                self.graph.submit(submission(capture))
        self.assertEqual(rows.submissions(self.graph),[])

    def test_assumed_position_is_stored_as_assumed_and_never_as_recorded_coverage(self):
        # A file reopened without a capture record, then one more answer: only that answer is known to be
        # missing. The marker names where the file stood and says that this is an assumption.
        assumed={**BEHIND,'notes_assumed':True,'map_assumed':True}
        detail=self.stored(submission(assumed))
        self.assertEqual(detail['capture'],{**assumed,'answers':6,'notes_answers':5,'map_answers':5})
        one=self.stored(submission({**BEHIND,'map_current':True,'map_through_turn':'t012','notes_through_turn':'t004','notes_assumed':True},
                                     context={'process_name':'Notes only'}))
        self.assertEqual((one['capture']['notes_assumed'],one['capture']['notes_answers'],one['capture']['map_answers']),(True,2,6))
        self.assertNotIn('map_assumed',one['capture'])
        plain=self.stored(submission(BEHIND,context={'process_name':'Recorded'}))
        self.assertNotIn('notes_assumed',plain['capture'],'A recorded position carries no such flag')

    def test_assumed_flag_is_accepted_only_for_a_part_that_is_behind_a_later_answer(self):
        invalid=({**BEHIND,'notes_assumed':False},                                   # the flag is only ever true
                 {**BEHIND,'notes_assumed':'yes'},
                 {**COMPLETE,'notes_assumed':True},                                   # current cannot be assumed
                 {**BEHIND,'notes_through_turn':None,'notes_assumed':True},           # no position to assume
                 {**BEHIND,'map_through_turn':'t012','map_assumed':True},             # not behind any answer
                 {**BEHIND,'notes_current':None,'notes_assumed':True},
                 {**BEHIND,'draft_assumed':True})
        for capture in invalid:
            with self.subTest(capture=capture),self.assertRaisesRegex(ValueError,'capture state'):
                self.graph.submit(submission(capture))
        self.assertEqual(rows.submissions(self.graph),[])

    def test_notes_may_lag_on_the_wording_of_the_last_answer(self):
        # A spoken caption that grew after the last capture: same answer ID, later wording.
        detail=self.stored(submission({**BEHIND,'notes_through_turn':'t012'}))
        self.assertEqual(detail['capture']['notes_answers'],6);self.assertIs(detail['capture']['notes_current'],False)

    def test_document_only_capture_has_no_answers_to_reach(self):
        document_id='doc_'+'a'*32;source_id=document_id+'_page11_chunk0'
        evidence={'id':source_id,'document_id':document_id,'name':'Reference.pdf','label':'Page 11','text':'The source describes receiving work.'}
        payload=submission({'in_progress':False,'notes_current':True,'map_current':True,'notes_through_turn':None,'map_through_turn':None},
                           turns=[],workflow={'steps':[{'id':'S1','title':'Receive work','evidence_turns':[source_id]}],'connections':[]},
                           documents={'documents':[{'id':document_id,'name':'Reference.pdf','sources':[{'source_id':source_id}]}]})
        receipt=self.graph.submit(payload,document_scope='private-scope',document_evidence=[evidence])
        detail=self.graph._revision(receipt['submission_id'],1)
        self.assertEqual(detail['capture'],{'in_progress':False,'notes_current':True,'map_current':True,'notes_through_turn':None,'map_through_turn':None,
                                            'answers':0,'notes_answers':0,'map_answers':0})


class CaptureStateHTTPTests(unittest.TestCase):
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

    def test_marker_is_stored_with_the_filed_revision(self):
        code,receipt=self.post('/api/knowledge/submit',submission(BEHIND))
        self.assertEqual(code,202,receipt)
        with self.httpd.knowledge.lock:
            saved=self.httpd.knowledge._revision(receipt['submission_id'],receipt['revision'])
        self.assertEqual(saved['capture'],{**BEHIND,'answers':6,'notes_answers':5,'map_answers':5})

    def test_route_rejects_a_contradictory_marker(self):
        code,result=self.post('/api/knowledge/submit',submission({**COMPLETE,'notes_through_turn':'t010'}))
        self.assertEqual(code,400,result);self.assertIn('capture state',result['error'])
        self.assertEqual(rows.submissions(self.httpd.knowledge),[])

if __name__=='__main__':
    unittest.main()
