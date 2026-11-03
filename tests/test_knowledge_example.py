"""Isolated synthetic knowledge graph mode; no provider or voice calls."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server
from test_knowledge_graph import payload


class KnowledgeExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.servers=[]; self.analysis_calls=[]
    def tearDown(self):
        for httpd,worker in self.servers:
            httpd.shutdown(); httpd.server_close(); worker.join(timeout=3)
        self.temp.cleanup()
    def serve(self, settings, authorizer=None):
        def analyzer(current,candidates):
            self.analysis_calls.append((current['submission_id'],len(candidates)))
            return []
        httpd=server.InterviewServer(('127.0.0.1',0),server.Handler,client=server.OpenAIClient({}),
            documents_root=Path(self.temp.name)/'documents',knowledge_root=Path(self.temp.name)/'knowledge',
            knowledge_settings=settings,knowledge_authorizer=authorizer,knowledge_analyzer=analyzer)
        worker=threading.Thread(target=httpd.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start();self.servers.append((httpd,worker));return httpd
    def request(self,httpd,path,data,headers=None):
        options={'Content-Type':'application/json','X-CSRF-Token':httpd.csrf_token};options.update(headers or {})
        req=Request(f'http://127.0.0.1:{httpd.server_port}'+path,data=json.dumps(data).encode(),headers=options)
        try:
            with urlopen(req,timeout=4) as response:return response.status,json.loads(response.read())
        except HTTPError as error:return error.code,json.loads(error.read())
    def wait(self,graph,job):
        for _ in range(200):
            row=graph.db.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()
            if row['status'] not in ('pending','processing'):return
            time.sleep(.01)
        self.fail('Timed out waiting for fixture job.')
    def test_example_seeding_is_private_idempotent_and_never_calls_analyzer(self):
        h=self.serve({'COLLECTOR_DEPLOYMENT_MODE':'local','KNOWLEDGE_LOCAL_OWNER':'true'})
        real=h.knowledge.submit(payload('Real fixture','The participant reports a real process.'));self.wait(h.knowledge,real['job_id'])
        before=h.knowledge.admin_snapshot();self.assertEqual(self.analysis_calls,[])
        with patch.object(h.knowledge,'admin_browse',side_effect=AssertionError('Real graph must not be read')):
            code,first=self.request(h,'/api/knowledge/admin/example',{'fixture':'untrusted content'})
            self.assertEqual(code,200);self.assertNotIn('status_token',first)
            self.assertEqual(first['status'],'completed');self.assertTrue(first['synthetic_example'])
            code,second=self.request(h,'/api/knowledge/admin/example',{})
            self.assertEqual(second['submission_id'],first['submission_id'])
            code,sample=self.request(h,'/api/knowledge/admin/browse',{'example':True,'section':'submissions'})
            self.assertEqual(code,200);self.assertEqual(len(sample['items']),1)
            self.assertNotIn('turns',sample['items'][0]);self.assertNotIn('draft',sample['items'][0])
            self.assertTrue(sample['synthetic_example']);self.assertIn('No AI analysis',sample['analysis_limitations'])
            code,detail=self.request(h,'/api/knowledge/admin/detail',{'example':True,'kind':'submission','id':first['submission_id'],'revision':1})
            self.assertEqual(code,200,detail);self.assertTrue(detail['item']['synthetic_example'])
            self.assertEqual(len(detail['item']['turns']),26)
            self.assertEqual(len(detail['item']['draft']['steps']),11)
            jobs=self.request(h,'/api/knowledge/admin/browse',{'example':True,'section':'jobs'})[1]
            self.assertEqual(jobs['items'][0]['status'],'completed')
        self.assertEqual(self.analysis_calls,[]);self.assertEqual(before,h.knowledge.admin_snapshot())
        self.assertNotEqual(first['submission_id'],real['submission_id'])
        self.assertEqual(self.request(h,'/api/knowledge/submit',{'synthetic_example':True})[0],400)
        self.assertEqual(self.request(h,'/api/knowledge/status',{'example':True})[0],403)
        for httpd,worker in self.servers: httpd.shutdown();httpd.server_close();worker.join(timeout=3)
        self.servers.clear()
        h=self.serve({'COLLECTOR_DEPLOYMENT_MODE':'local','KNOWLEDGE_LOCAL_OWNER':'true'})
        self.assertEqual(self.request(h,'/api/knowledge/admin/example',{})[1]['submission_id'],first['submission_id'])
        self.assertEqual(len(self.request(h,'/api/knowledge/admin/browse',{'example':True,'section':'submissions'})[1]['items']),1)
        self.assertEqual(len(self.request(h,'/api/knowledge/admin/browse',{'section':'submissions'})[1]['items']),1)
    def test_ordinary_and_hosted_users_cannot_open_synthetic_admin_graph(self):
        h=self.serve({},lambda handler,capability:'employee' if capability=='knowledge.submit' else None)
        for path in ('/api/knowledge/admin/example','/api/knowledge/admin/browse','/api/knowledge/admin/detail','/api/knowledge/admin/history','/api/knowledge/admin/graph','/api/knowledge/admin/review'):
            self.assertEqual(self.request(h,path,{'example':True},{'X-Role':'admin'})[0],403)
        hosted=self.serve({'COLLECTOR_DEPLOYMENT_MODE':'hosted'},lambda handler,capability:'admin' if capability=='knowledge.admin' else None)
        self.assertEqual(self.request(hosted,'/api/knowledge/admin/browse',{})[0],200)
        self.assertEqual(self.request(hosted,'/api/knowledge/admin/example',{})[0],403)
        self.assertEqual(self.request(hosted,'/api/knowledge/admin/browse',{'example':True})[0],403)
        self.assertFalse(hosted.example_graph_path.exists())
    def test_example_operations_require_csrf_and_same_origin(self):
        h=self.serve({'COLLECTOR_DEPLOYMENT_MODE':'local','KNOWLEDGE_LOCAL_OWNER':'true'})
        for path in ('/api/knowledge/admin/example','/api/knowledge/admin/browse','/api/knowledge/admin/detail','/api/knowledge/admin/history','/api/knowledge/admin/graph'):
            self.assertEqual(self.request(h,path,{'example':True},{'X-CSRF-Token':'bad'})[0],403)
            self.assertEqual(self.request(h,path,{'example':True},{'Origin':'https://attacker.example'})[0],403)
        self.assertFalse(h.example_graph_path.exists())

if __name__=='__main__':unittest.main()
