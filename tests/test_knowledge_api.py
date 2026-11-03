"""Knowledge HTTP authorization boundaries; synthetic data, no provider requests."""
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server


class FakeGraph:
    def __init__(self, path, analyzer=None, document_resolver=None):
        self.calls = []
    def recover_submission(self, key, intent_digest, principal=None):
        return None
    def submit(self, payload, principal=None, document_scope=None, intent_digest=None):
        self.calls.append(('submit', payload, principal, document_scope))
        return {'submission_id': 'synthetic', 'process_id': 'process', 'revision': 1, 'job_id': 'job', 'status': 'pending'}
    def admin_browse(self, section, filters=None, offset=0, limit=25):
        self.calls.append(('browse',section,filters,offset,limit))
        return {'section':section,'items':[],'page':{'offset':offset,'limit':limit,'total':0,'has_more':False},'counts':{}}
    def admin_detail(self, kind, identifier, revision=None):
        self.calls.append(('detail',kind,identifier,revision));return {'kind':kind,'item':{'id':identifier}}
    def admin_history(self, kind, identifier, offset=0, limit=25):
        self.calls.append(('history',kind,identifier,offset,limit));return {'kind':kind,'items':[],'page':{'offset':offset,'limit':limit,'total':0,'has_more':False}}
    def admin_graph(self, filters=None, level='overview', submission_id=None):
        self.calls.append(('graph',filters,level,submission_id));return {'entities':[],'edges':[],'proposals':[]}
    def admin_snapshot(self):
        self.calls.append(('snapshot',))
        return {'submissions': [], 'proposals': [], 'entities': [], 'edges': [], 'jobs': []}
    def can_revise(self, process_id, principal):
        return process_id == 'owned-process' and principal == 'verified-employee'
    def status(self, submission_id, revision, status_token):
        if (submission_id, revision, status_token) != ('owned', 1, 'test-capability'):
            raise PermissionError('Not available')
        return {'submission_id':'owned', 'revision':1, 'job_id':'job', 'status':'pending', 'error':'', 'attempts':0}
    def document_scope(self, submission_id, revision, document_id):
        if (submission_id, revision, document_id) != ('owned', 1, 'doc-1'):
            raise PermissionError('Not available')
        return 'scope-secret'
    def review(self, *args, **kwargs):
        self.calls.append(('review', args, kwargs))
        return {'id': args[0], 'state': args[1]}
    def retry(self, job_id):
        self.calls.append(('retry', job_id))
        return {'id': job_id, 'status': 'pending'}
    def canonical_create(self, label, entity_ids, reviewer, reason, bounded_result=False):
        self.calls.append(('canonical_create', label, entity_ids, reviewer, reason))
        return {'id': 'canonical-1', 'label': label, 'review_version': 1}
    def canonical_update(self, canonical_id, action, value, reviewer, reason, expected_revision, bounded_result=False):
        self.calls.append(('canonical_update', canonical_id, action, value, reviewer, reason, expected_revision))
        return {'id': canonical_id, 'review_version': expected_revision + 1}
    def close(self):
        pass


class KnowledgeAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.instances = []

    def tearDown(self):
        for httpd, worker in self.instances:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=3)
        self.temp.cleanup()

    def serve(self, settings=None, authorizer=None):
        original = server.local_module
        def loader(name, filename):
            if name == 'knowledge_graph':
                return types.SimpleNamespace(KnowledgeGraph=FakeGraph)
            return original(name, filename)
        with patch.object(server, 'local_module', side_effect=loader):
            httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler,
                client=server.OpenAIClient({}), documents_root=Path(self.temp.name)/str(len(self.instances)),
                knowledge_settings=settings or {}, knowledge_authorizer=authorizer)
        worker = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        self.instances.append((httpd, worker))
        return httpd

    def request(self, httpd, path, payload=None, headers=None):
        url = f'http://127.0.0.1:{httpd.server_port}' + path
        options = dict(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            options.setdefault('Content-Type', 'application/json')
            options.setdefault('X-CSRF-Token', httpd.csrf_token)
        try:
            with urlopen(Request(url, data=data, headers=options), timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_employee_can_submit_but_cannot_read_or_mutate_admin_apis(self):
        httpd = self.serve()
        payload = {'turns': [], 'role': 'admin', 'submitter': 'forged', 'reviewer': 'forged',
                   'unsent_answer': 'private draft', 'document_scope': 'secret', 'documents': None,
                   'knowledge_status': {'status_token': 'private-capability'},
                   'context': {'nested': [{'status_token':'private-nested-capability'}]}}
        status, result = self.request(httpd, '/api/knowledge/submit', payload)
        self.assertEqual(status, 202)
        self.assertEqual(result['status'], 'pending')
        _, received, principal, document_scope = httpd.knowledge.calls[-1]
        self.assertIsNone(principal)
        self.assertFalse({'role', 'submitter', 'reviewer'} & set(received))
        self.assertNotIn('unsent_answer', received)
        self.assertNotIn('document_scope', received)
        self.assertNotIn('knowledge_status', received)
        self.assertNotIn('private-nested-capability', json.dumps(received))
        self.assertIsNone(document_scope)
        for route, data in (('snapshot', {}),('browse', {}),('detail', {}),('history', {}),('graph', {}), ('review', {'proposal_id':'p', 'action':'confirm', 'expected_revision':1}), ('retry', {'job_id':'j'}), ('document-source', {}), ('canonical-create', {}), ('canonical-update', {})):
            with self.subTest(route=route):
                self.assertEqual(self.request(httpd, '/api/knowledge/admin/' + route, data,
                    {'X-Admin': 'true', 'X-Role': 'admin'})[0], 403)
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {'process_id':'someone-else'})[0], 403)
        self.assertEqual(len(httpd.knowledge.calls), 1)

    def test_local_owner_requires_both_explicit_local_settings_and_hosted_denies(self):
        for settings, allowed in (({}, False), ({'KNOWLEDGE_LOCAL_OWNER':'true'}, False),
             ({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'hosted'}, False),
             ({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'local'}, True)):
            httpd = self.serve(settings)
            self.assertEqual(self.request(httpd, '/api/config')[1]['knowledge_admin_enabled'], allowed)
            self.assertEqual(self.request(httpd, '/api/knowledge/admin/browse', {})[0], 200 if allowed else 403)

    def test_trusted_authorizer_controls_review_identity_and_ignores_browser_claims(self):
        httpd = self.serve({'COLLECTOR_DEPLOYMENT_MODE':'hosted'}, lambda handler, capability: 'verified-admin' if capability == 'knowledge.admin' else None)
        status, _ = self.request(httpd, '/api/knowledge/admin/review', {'proposal_id':'p', 'action':'confirm',
            'reason':'reviewed evidence', 'expected_revision':2, 'reviewer':'forged'})
        self.assertEqual(status, 200)
        self.assertEqual(httpd.knowledge.calls[-1][1][2], 'verified-admin')
        self.assertEqual(self.request(httpd, '/api/knowledge/admin/review', {'proposal_id':'p', 'action':'confirm', 'expected_revision':True})[0], 400)

    def test_authenticated_employee_revision_is_limited_to_their_own_process(self):
        httpd = self.serve({'COLLECTOR_DEPLOYMENT_MODE':'hosted'},
            lambda handler, capability: 'verified-employee' if capability == 'knowledge.submit' else None)
        self.assertFalse(self.request(httpd, '/api/config')[1]['knowledge_admin_enabled'])
        self.assertEqual(self.request(httpd, '/api/knowledge/admin/snapshot', {})[0], 403)
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {'process_id':'other-process'})[0], 403)
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {'process_id':'owned-process', 'submitter':'forged'})[0], 202)
        self.assertEqual(httpd.knowledge.calls[-1][2], 'verified-employee')

    def test_local_owner_is_not_misrepresented_as_a_verified_employee(self):
        httpd = self.serve({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'local'})
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {})[0], 202)
        self.assertIsNone(httpd.knowledge.calls[-1][2])

    def test_same_origin_and_csrf_apply_to_every_knowledge_endpoint(self):
        httpd = self.serve({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'local'})
        for route in ('submit', 'status', 'admin/snapshot','admin/browse','admin/detail','admin/history','admin/graph', 'admin/review', 'admin/retry', 'admin/document-source', 'admin/canonical-create', 'admin/canonical-update'):
            path = '/api/knowledge/' + route
            self.assertEqual(self.request(httpd, path, {}, {'X-CSRF-Token':'wrong'})[0], 403)
            self.assertEqual(self.request(httpd, path, {}, {'Origin':'https://attacker.example'})[0], 403)
        self.assertEqual(httpd.knowledge.calls, [])

    def test_bounded_routes_forward_only_after_auth_and_full_snapshot_is_retired(self):
        httpd=self.serve({'COLLECTOR_DEPLOYMENT_MODE':'local','KNOWLEDGE_LOCAL_OWNER':'true'})
        for route,payload in (
            ('browse',{'section':'submissions','filters':{'team':'Operations'},'offset':25,'limit':25}),
            ('detail',{'kind':'submission','id':'source','revision':2}),
            ('history',{'kind':'proposal','id':'proposal','offset':10,'limit':10}),
            ('graph',{'level':'steps','submission_id':'source'})):
            code,result=self.request(httpd,'/api/knowledge/admin/'+route,payload)
            self.assertEqual(code,200,result);self.assertEqual(httpd.knowledge.calls[-1][0],route)
        self.assertEqual(self.request(httpd,'/api/knowledge/admin/snapshot',{})[0],409)
        self.assertFalse(any(call[0]=='snapshot' for call in httpd.knowledge.calls))

    def test_employee_status_capability_is_scoped_and_not_admin_authority(self):
        httpd = self.serve()
        request = {'submission_id':'owned', 'revision':1, 'status_token':'test-capability'}
        status, result = self.request(httpd, '/api/knowledge/status', request)
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {'submission_id','revision','job_id','status','error','attempts'})
        for overrides in ({'submission_id':'other'}, {'revision':2}, {'status_token':'forged'}):
            self.assertEqual(self.request(httpd, '/api/knowledge/status', {**request, **overrides})[0], 403)
        self.assertEqual(self.request(httpd, '/api/knowledge/admin/snapshot', request)[0], 403)

    def test_document_references_are_resolved_from_scope_not_browser_claims(self):
        httpd = self.serve()
        scope = httpd.documents_store.create_scope()
        record = httpd.documents_store.add(scope, 'actual.csv', b'column\nvalue\n')
        payload = {'documents': {'scope': scope, 'documents': [{'id': record['id'], 'name': 'forged.csv', 'sources': [{'source_id':'forged'}]}]}}
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', payload)[0], 202)
        _, received, _, private_scope = httpd.knowledge.calls[-1]
        self.assertEqual(private_scope, scope)
        self.assertEqual(received['documents']['documents'][0]['name'], 'actual.csv')
        self.assertEqual(received['documents']['documents'][0]['sources'], [])
        self.assertNotIn('scope', received['documents'])
        payload['documents']['scope'] = httpd.documents_store.create_scope()
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', payload)[0], 403)

    def test_document_source_read_requires_admin_and_exact_revision_reference(self):
        httpd = self.serve({'COLLECTOR_DEPLOYMENT_MODE':'local', 'KNOWLEDGE_LOCAL_OWNER':'true'})
        request = {'submission_id':'owned', 'revision':1, 'document_id':'doc-1', 'source_id':'page-1'}
        with patch.object(httpd.documents, 'source', return_value={'id':'page-1', 'text':'fixture'}) as source:
            status, result = self.request(httpd, '/api/knowledge/admin/document-source', request)
            self.assertEqual(status, 200)
            self.assertEqual(result['source']['text'], 'fixture')
            self.assertNotIn('scope-secret', json.dumps(result))
            source.assert_called_once_with('scope-secret', 'doc-1', 'page-1')
            request['document_id'] = 'other-document'
            self.assertEqual(self.request(httpd, '/api/knowledge/admin/document-source', request)[0], 403)
            source.assert_called_once()

    def test_canonical_actions_take_reviewer_from_trusted_server(self):
        httpd = self.serve({'COLLECTOR_DEPLOYMENT_MODE':'hosted'},
            lambda handler, capability: 'verified-admin' if capability == 'knowledge.admin' else None)
        create = {'label':'Ledger', 'entity_ids':['one', 'two'], 'reason':'reviewed', 'reviewer':'forged'}
        self.assertEqual(self.request(httpd, '/api/knowledge/admin/canonical-create', create)[0], 200)
        self.assertEqual(httpd.knowledge.calls[-1][3], 'verified-admin')
        update = {'canonical_id':'canonical-1', 'action':'remove_member', 'value':'two', 'reason':'mistaken match',
                  'expected_revision':1, 'reviewer':'forged'}
        self.assertEqual(self.request(httpd, '/api/knowledge/admin/canonical-update', update)[0], 200)
        self.assertEqual(httpd.knowledge.calls[-1][4], 'verified-admin')
        update['expected_revision'] = True
        self.assertEqual(self.request(httpd, '/api/knowledge/admin/canonical-update', update)[0], 400)


class KnowledgeRealHTTPTests(unittest.TestCase):
    setUp = KnowledgeAPITests.setUp
    tearDown = KnowledgeAPITests.tearDown
    request = KnowledgeAPITests.request

    def page_items(self,httpd,section,**options):
        rows=[];offset=0
        while True:
            code,result=self.request(httpd,'/api/knowledge/admin/browse',{'section':section,'offset':offset,'limit':25,**options})
            self.assertEqual(code,200,result);self.assertLessEqual(len(result['items']),25);rows.extend(result['items'])
            if not result['page']['has_more']:return rows
            offset+=25

    def history_items(self,httpd,kind,identifier):
        rows=[];offset=0
        while True:
            code,result=self.request(httpd,'/api/knowledge/admin/history',{'kind':kind,'id':identifier,'offset':offset,'limit':25})
            self.assertEqual(code,200,result);self.assertLessEqual(len(result['items']),25);rows.extend(result['items'])
            if not result['page']['has_more']:return rows
            offset+=25

    def snapshot(self,httpd):
        # Test-only reconstruction exercises lazy endpoints over the small fixture.
        # The application never assembles whole-store data this way.
        result={'submissions':[],'proposals':[],'entities':self.page_items(httpd,'entities'),
                'jobs':self.page_items(httpd,'jobs'),'canonical_groups':[]}
        for meta in self.page_items(httpd,'submissions'):
            code,detail=self.request(httpd,'/api/knowledge/admin/detail',{'kind':'submission','id':meta['submission_id'],'revision':meta['revision']})
            self.assertEqual(code,200,detail);result['submissions'].append(detail['item'])
        for meta in self.page_items(httpd,'connections'):
            code,detail=self.request(httpd,'/api/knowledge/admin/detail',{'kind':'proposal','id':meta['id']})
            self.assertEqual(code,200,detail);item=detail['item'];item['history']=self.history_items(httpd,'proposal',item['id']);result['proposals'].append(item)
        for meta in self.page_items(httpd,'groups'):
            code,detail=self.request(httpd,'/api/knowledge/admin/detail',{'kind':'group','id':meta['id']})
            self.assertEqual(code,200,detail);item=detail['item'];item['members']=[x['id'] for x in self.history_items(httpd,'group_members',item['id'])]
            item['aliases']=[x['alias'] for x in self.history_items(httpd,'group_aliases',item['id'])]
            item['history']=self.history_items(httpd,'group',item['id']);result['canonical_groups'].append(item)
        return result

    def serve_real(self, authorizer, analyzer=None):
        from test_knowledge_graph import proposal
        httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler,
            client=server.OpenAIClient({}), documents_root=Path(self.temp.name)/'documents',
            knowledge_root=Path(self.temp.name)/'graph', knowledge_settings={'COLLECTOR_DEPLOYMENT_MODE':'hosted'},
            knowledge_authorizer=authorizer, knowledge_analyzer=analyzer or proposal)
        worker = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        self.instances.append((httpd, worker))
        return httpd

    def test_document_simulation_roundtrips_in_real_admin_without_verified_employee_identity(self):
        from test_knowledge_graph import payload,simulation_provenance
        admin=self.serve_real(lambda h,c:'verified-admin' if c=='knowledge.admin' else None)
        submitted=payload('Document-derived walkthrough','The source describes preparing the file.')
        submitted.update(capture_provenance=simulation_provenance(),
                         participant='AI-simulated participant; no employee interview',submitter='forged employee')
        code,receipt=self.request(admin,'/api/knowledge/submit',submitted)
        self.assertEqual(code,202,receipt)
        code,detail=self.request(admin,'/api/knowledge/admin/detail',
                                 {'kind':'submission','id':receipt['submission_id'],'revision':receipt['revision']})
        self.assertEqual(code,200,detail)
        self.assertEqual(detail['item']['capture_provenance'],simulation_provenance())
        self.assertIsNone(detail['item']['submitter'])
        submitted['capture_provenance']['process_owner_approved']=True
        self.assertEqual(self.request(admin,'/api/knowledge/submit',submitted)[0],400)
        self.assertEqual(len(self.page_items(admin,'submissions')),1)

    def test_paged_http_metadata_and_selected_detail_validate_all_arguments(self):
        from test_knowledge_graph import payload
        admin = self.serve_real(lambda h,c: 'verified-admin' if c == 'knowledge.admin' else None)
        receipts = [admin.knowledge.submit(payload('Process '+str(i), 'Full selected account '+str(i)))
                    for i in range(3)]
        with patch.object(admin.knowledge, 'admin_snapshot', side_effect=AssertionError('unbounded read')):
            code, first = self.request(admin, '/api/knowledge/admin/browse', {'section':'submissions','limit':2})
            self.assertEqual(code, 200, first)
            self.assertEqual(first['page'], {'offset':0,'limit':2,'total':3,'has_more':True})
            self.assertEqual(len(first['items']), 2)
            self.assertTrue(all('turns' not in item and 'draft' not in item for item in first['items']))
            code, last = self.request(admin, '/api/knowledge/admin/browse', {'section':'submissions','limit':2,'offset':2})
            self.assertEqual(code, 200, last)
            self.assertFalse(last['page']['has_more'])
            self.assertEqual({item['submission_id'] for item in first['items']+last['items']},
                             {item['submission_id'] for item in receipts})
            selected = last['items'][0]
            code, detail = self.request(admin, '/api/knowledge/admin/detail',
                {'kind':'submission','id':selected['submission_id'],'revision':selected['revision']})
            self.assertEqual(code, 200, detail)
            self.assertEqual(detail['item']['submission_id'], selected['submission_id'])
            self.assertEqual(len(detail['item']['turns']), 1)
            self.assertNotIn('status_token', json.dumps(detail))
        for route, body in (
            ('browse', {'section':'submissions','offset':True}),
            ('browse', {'section':'submissions','limit':51}),
            ('browse', {'section':'submissions','filters':{'latest_only':1}}),
            ('browse', {'section':'submissions','filters':{'team':['spoofed']}}),
            ('detail', {'kind':'submission','id':receipts[0]['submission_id'],'revision':True}),
            ('detail', {'kind':'submission','id':receipts[0]['submission_id']}),
            ('history', {'kind':'downstream','id':receipts[0]['submission_id'],'offset':-1}),
            ('graph', {'level':'invalid'}),
            ('graph', {'submission_id':'invalid'}),
        ):
            with self.subTest(route=route, body=body):
                code, result = self.request(admin, '/api/knowledge/admin/'+route, body)
                self.assertEqual(code, 400, result)
                self.assertIsInstance(result.get('error'), str)

    def test_real_persistence_review_and_document_authorization(self):
        import time
        from test_knowledge_graph import payload
        employee = self.serve_real(lambda h,c: 'verified-employee' if c == 'knowledge.submit' else None)
        admin = self.serve_real(lambda h,c: 'verified-admin' if c == 'knowledge.admin' else None)
        scope = employee.documents_store.create_scope()
        document = employee.documents_store.add(scope, 'support.csv', b'field,value\nnav,approved\n')
        employee.documents_store.extract(scope, document['id'])
        source = employee.documents_store.chunks(scope, document['id'])['chunks'][0]
        employee.documents_store.update(scope, document['id'], {'analysis': {'sources':[{'source_id':source['id'],'label':source['label']}]}})
        a = payload('Publish', 'We publish approved NAV.')
        a['documents'] = {'scope':scope, 'documents':[{'id':document['id'],'name':'forged.csv'}]}
        a['knowledge_status'] = {'status_token':'synthetic-old-status-capability'}
        status, first = self.request(employee, '/api/knowledge/submit', a)
        self.assertEqual(status, 202, first)
        b = payload('Statements', 'We use approved NAV.')
        b['documents'] = None
        status, second = self.request(employee, '/api/knowledge/submit', b)
        self.assertEqual(status, 202, second)
        first_status = {'submission_id':first['submission_id'], 'revision':first['revision'], 'status_token':first['status_token']}
        self.assertEqual(self.request(employee, '/api/knowledge/status', first_status)[0], 200)
        self.assertEqual(self.request(employee, '/api/knowledge/status', {**first_status, 'submission_id':second['submission_id']})[0], 403)
        self.assertEqual(self.request(employee, '/api/knowledge/status', {**first_status, 'status_token':'forged'})[0], 403)
        self.assertEqual(self.request(employee, '/api/knowledge/admin/snapshot', first_status)[0], 403)
        for _ in range(200):
            snapshot = self.snapshot(admin)
            if snapshot['proposals']:
                break
            time.sleep(.01)
        self.assertEqual(len(snapshot['proposals']), 1)
        self.assertNotIn(scope, json.dumps(snapshot))
        self.assertNotIn(first['status_token'], json.dumps(snapshot))
        self.assertNotIn('synthetic-old-status-capability', json.dumps(snapshot))
        systems = [item for item in snapshot['entities'] if item['type'] == 'system' and item['label'] == 'Ledger']
        self.assertEqual(len(systems), 2)
        group_request = {'label':'Shared ledger', 'entity_ids':[item['id'] for item in systems], 'reason':'Reviewed aliases'}
        self.assertEqual(self.request(employee, '/api/knowledge/admin/canonical-create', group_request)[0], 403)
        status, group = self.request(admin, '/api/knowledge/admin/canonical-create', group_request)
        self.assertEqual(status, 200, group)
        update = {'canonical_id':group['id'], 'action':'remove_member', 'value':systems[1]['id'],
                  'reason':'Correction after review', 'expected_revision':group['review_version']}
        status, corrected_group = self.request(admin, '/api/knowledge/admin/canonical-update', update)
        self.assertEqual(status, 200, corrected_group)
        self.assertEqual(self.request(admin, '/api/knowledge/admin/canonical-update', update)[0], 400)
        saved = next(item for item in snapshot['submissions'] if item['submission_id'] == first['submission_id'])
        self.assertEqual(saved['submitter'], 'verified-employee')
        self.assertEqual(saved['documents']['documents'][0]['name'], 'support.csv')
        source_request = {'submission_id':first['submission_id'], 'revision':1, 'document_id':document['id'], 'source_id':source['id']}
        self.assertEqual(self.request(employee, '/api/knowledge/admin/snapshot', {})[0], 403)
        self.assertEqual(self.request(employee, '/api/knowledge/admin/document-source', source_request)[0], 403)
        status, readback = self.request(admin, '/api/knowledge/admin/document-source', source_request)
        self.assertEqual(status, 200, readback)
        self.assertIn('nav', readback['source']['text'])
        self.assertNotIn(scope, json.dumps(readback))
        p = snapshot['proposals'][0]
        review = {'proposal_id':p['id'], 'action':'confirm', 'reason':'Reviewed fixture', 'expected_revision':p['review_version']}
        self.assertEqual(self.request(employee, '/api/knowledge/admin/review', review)[0], 403)
        self.assertEqual(self.request(admin, '/api/knowledge/admin/review', review)[1]['status'], 'confirmed')
        a['process_id'] = first['process_id']
        a['turns'][0]['text'] = 'Corrected NAV account.'
        status, revised = self.request(employee, '/api/knowledge/submit', a)
        self.assertEqual(status, 202, revised)
        self.assertEqual(revised['revision'], 2)
        self.assertEqual(self.request(employee, '/api/knowledge/status', {**first_status, 'revision':2})[0], 403)
        snapshot = self.snapshot(admin)
        self.assertEqual(self.request(admin, '/api/knowledge/status', first_status)[0], 200)
        self.assertEqual(next(item for item in snapshot['proposals'] if item['id'] == p['id'])['status'], 'stale')
        for httpd, worker in self.instances:
            httpd.shutdown(); httpd.server_close(); worker.join(timeout=3)
        self.instances.clear()
        admin = self.serve_real(lambda h,c: 'verified-admin' if c == 'knowledge.admin' else None)
        self.assertEqual(self.request(admin, '/api/knowledge/status', first_status)[0], 200)
        snapshot = self.snapshot(admin)
        self.assertEqual(len([item for item in snapshot['submissions'] if item['submission_id'] == first['submission_id']]), 2)
        self.assertEqual(next(item for item in snapshot['proposals'] if item['id'] == p['id'])['status'], 'stale')
        restored = next(item for item in snapshot['canonical_groups'] if item['id'] == group['id'])
        self.assertGreaterEqual(restored['review_version'], corrected_group['review_version'])
        self.assertTrue(any(event['reviewer'] == 'verified-admin' for event in restored['history']))
        self.assertTrue(any(item['id'] == systems[1]['id'] for item in snapshot['entities']))
        self.assertEqual(self.request(admin, '/api/knowledge/admin/document-source', source_request)[0], 200)

    def test_document_evidence_resolves_privately_and_turns_stale_when_archived(self):
        import time
        from test_knowledge_graph import payload, proposal
        def analyze(current, candidates):
            # Only derived excerpts and document/source IDs reach the adapter.
            self.assertNotIn(scope, json.dumps((current, candidates)))
            excerpt = candidates[0]['document_excerpts'][0]
            result = proposal(current, candidates)
            result[0]['evidence'][0] = {
                'type':'document_supported', 'submission_id':candidates[0]['submission_id'],
                'revision':candidates[0]['revision'], 'document_id':excerpt['document_id'],
                'source_id':excerpt['source_id'], 'quote':'B2=approved'}
            return result
        admin = self.serve_real(lambda h,c: 'verified-admin' if c == 'knowledge.admin' else None, analyze)
        scope = admin.documents_store.create_scope()
        document = admin.documents_store.add(scope, 'support.csv', b'field,value\nnav,approved\n')
        admin.documents_store.extract(scope, document['id'])
        source = admin.documents_store.chunks(scope, document['id'])['chunks'][0]
        admin.documents_store.update(scope, document['id'], {'analysis': {'sources':[{'source_id':source['id'], 'label':source['label']}]}})
        first = payload('Publish', 'We publish approved NAV.')
        first['documents'] = {'scope':scope, 'documents':[{'id':document['id']}]}
        self.assertEqual(self.request(admin, '/api/knowledge/submit', first)[0], 202)
        second = payload('Statements', 'We use approved NAV.')
        second['documents'] = None
        self.assertEqual(self.request(admin, '/api/knowledge/submit', second)[0], 202)
        for _ in range(200):
            snapshot = self.snapshot(admin)
            if snapshot['proposals']:
                break
            time.sleep(.01)
        self.assertEqual(len(snapshot['proposals']), 1)
        self.assertNotIn(scope, json.dumps(snapshot))
        item = snapshot['proposals'][0]
        self.assertEqual(item['evidence'][0]['type'], 'document_supported')
        self.assertEqual(item['evidence'][0]['source_id'], source['id'])
        review = {'proposal_id':item['id'], 'action':'confirm', 'reason':'Reviewed fixture', 'expected_revision':item['review_version']}
        self.assertEqual(self.request(admin, '/api/knowledge/admin/review', review)[0], 200)
        admin.documents_store.archive(scope, document['id'])
        changed = self.snapshot(admin)['proposals'][0]
        self.assertEqual(changed['status'], 'stale')
        self.assertEqual(changed['history'][-1]['action'], 'stale')

    def test_saved_attempt_recovers_before_document_drift_or_archive_hydration(self):
        import copy
        import uuid
        from test_knowledge_graph import payload
        identity={'employee':'verified-employee'}
        authorizer=lambda handler,capability: identity['employee'] if capability=='knowledge.submit' else None
        httpd=self.serve_real(authorizer,lambda current,candidates:[])
        scope=httpd.documents_store.create_scope()
        document=httpd.documents_store.add(scope,'support.csv',b'field,value\nnav,approved\n')
        httpd.documents_store.extract(scope,document['id'])
        source=httpd.documents_store.chunks(scope,document['id'])['chunks'][0]
        attempt=payload('Publish','We publish approved NAV.')
        attempt.update(submission_key=str(uuid.uuid4()),saved_at='original time',knowledge_status={'status_token':'ignored-old-status'})
        attempt['documents']={'scope':scope,'documents':[{'id':document['id']}]}
        status,first=self.request(httpd,'/api/knowledge/submit',attempt)
        self.assertEqual(status,202,first)
        # Source discovery after the accepted write must not change its request identity.
        httpd.documents_store.update(scope,document['id'],{'analysis':{'sources':[{'source_id':source['id'],'label':source['label']}]}})
        retry=copy.deepcopy(attempt);retry['saved_at']='later time';retry['knowledge_status']['status_token']='different-ignored-status';retry['intent_digest']='forged-browser-claim'
        with patch.object(httpd.documents_store,'get',side_effect=AssertionError('Recovery must precede mutable hydration')):
            status,recovered=self.request(httpd,'/api/knowledge/submit',retry)
        self.assertEqual(status,202,recovered);self.assertEqual(recovered,first)
        httpd.documents_store.archive(scope,document['id'])
        with patch.object(httpd.documents_store,'get',side_effect=AssertionError('Archived file must not block exact receipt recovery')):
            status,recovered=self.request(httpd,'/api/knowledge/submit',retry)
        self.assertEqual(status,202,recovered);self.assertEqual(recovered,first)
        changed=copy.deepcopy(retry);changed['turns'][0]['text']='A different account.'
        self.assertEqual(self.request(httpd,'/api/knowledge/submit',changed)[0],400)
        changed=copy.deepcopy(retry);changed['documents']['scope']='different-scope'
        self.assertEqual(self.request(httpd,'/api/knowledge/submit',changed)[0],400,'The original private scope remains bound to intent.')
        identity['employee']='another-employee'
        self.assertEqual(self.request(httpd,'/api/knowledge/submit',retry)[0],400)
        identity['employee']='verified-employee'
        snapshot=httpd.knowledge.admin_snapshot();self.assertEqual(len(snapshot['submissions']),1)
        self.assertEqual(snapshot['submissions'][0]['documents']['documents'][0]['sources'],[],'Saved evidence is not rewritten by later source discovery.')
        self.assertNotIn(scope,json.dumps(snapshot));self.assertNotIn('intent_digest',json.dumps(snapshot))
        for running,worker in self.instances:
            running.shutdown();running.server_close();worker.join(timeout=3)
        self.instances.clear()
        reopened=self.serve_real(authorizer,lambda current,candidates:[])
        self.assertEqual(self.request(reopened,'/api/knowledge/submit',retry),(202,first),'Raw-intent recovery survives restart with the original document archived.')


if __name__ == "__main__":
    unittest.main()
