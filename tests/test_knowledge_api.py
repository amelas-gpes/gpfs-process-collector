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
from knowledge_rows import proposals, submissions


class FakeGraph:
    def __init__(self, path, analyzer=None, document_resolver=None, request_scope=None):
        self.calls = []
    def recover_submission(self, key, intent_digest, principal=None):
        return None
    def submit(self, payload, principal=None, document_scope=None, intent_digest=None, document_evidence=None):
        self.calls.append(('submit', payload, principal, document_scope))
        self.document_evidence = document_evidence
        return {'submission_id': 'synthetic', 'process_id': 'process', 'revision': 1, 'job_id': 'job', 'status': 'pending'}
    def can_revise(self, process_id, principal):
        return process_id == 'owned-process' and principal == 'verified-employee'
    def status(self, submission_id, revision, status_token):
        if (submission_id, revision, status_token) != ('owned', 1, 'test-capability'):
            raise PermissionError('Not available')
        return {'submission_id':'owned', 'revision':1, 'job_id':'job', 'status':'pending', 'error':'', 'attempts':0}
    def stop_scheduling(self):
        pass

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

    def test_employee_submission_strips_client_roles_and_private_fields(self):
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
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {'process_id':'someone-else'})[0], 403)
        self.assertEqual(len(httpd.knowledge.calls), 1)

    def test_local_owner_requires_both_explicit_local_settings_and_hosted_denies(self):
        for settings, allowed in (({}, False), ({'KNOWLEDGE_LOCAL_OWNER':'true'}, False),
             ({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'hosted'}, False),
             ({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'local'}, True)):
            httpd = self.serve(settings)
            self.assertEqual(self.request(httpd, '/api/config')[1]['revisions_available'], allowed)
            status, _ = self.request(httpd, '/api/knowledge/submit', {'process_id': 'owned-process'})
            self.assertEqual(status, 202 if allowed else 403)

    def test_the_agent_prompt_route_is_not_served_even_to_a_trusted_admin(self):
        path = '/api/admin/agent-prompts'
        httpd = self.serve(authorizer=lambda handler, capability: 'verified-person')
        headers = {'X-CSRF-Token': httpd.csrf_token}
        config = self.request(httpd, '/api/config')[1]
        self.assertTrue(config['revisions_available'])
        self.assertNotIn('agent_prompts_available', config)
        with patch.object(httpd.client, 'request', side_effect=AssertionError('unexpected provider call')):
            self.assertEqual(self.request(httpd, path, headers=headers)[0], 404)
            self.assertEqual(self.request(httpd, path, {'prompt': 'replacement'})[0], 404)
        self.assertNotIn(server.agent_team.PROCESS_REVIEW_INSTRUCTIONS.splitlines()[0], json.dumps(config))

    def test_removed_admin_routes_are_unavailable_even_to_local_and_trusted_owners(self):
        for httpd in (self.serve(), self.serve({'COLLECTOR_DEPLOYMENT_MODE': 'local', 'KNOWLEDGE_LOCAL_OWNER': 'true'}),
                      self.serve(authorizer=lambda handler, capability: 'verified-admin')):
            config = self.request(httpd, '/api/config')[1]
            self.assertFalse({'knowledge_admin_enabled', 'knowledge_admin_mode', 'knowledge_delete_enabled'} & config.keys())
            for route in ('snapshot', 'example', 'browse', 'detail', 'history', 'graph', 'review', 'retry',
                          'delete', 'document-source', 'canonical-create', 'canonical-update'):
                with self.subTest(route=route):
                    status, result = self.request(httpd, '/api/knowledge/admin/' + route, {})
                    self.assertEqual((status, result), (404, {'error': 'Not found.'}))
            self.assertEqual(httpd.knowledge.calls, [])

    def test_fictional_examples_cannot_be_filed(self):
        httpd = self.serve({'COLLECTOR_DEPLOYMENT_MODE': 'local', 'KNOWLEDGE_LOCAL_OWNER': 'true'})
        for marker in ({'example': True}, {'synthetic_example': True}):
            self.assertEqual(self.request(httpd, '/api/knowledge/submit', marker)[0], 400)
        self.assertEqual(httpd.knowledge.calls, [])

    def test_authenticated_employee_revision_is_limited_to_their_own_process(self):
        httpd = self.serve({'COLLECTOR_DEPLOYMENT_MODE':'hosted'},
            lambda handler, capability: 'verified-employee' if capability == 'knowledge.submit' else None)
        self.assertTrue(self.request(httpd, '/api/config')[1]['revisions_available'])
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {'process_id':'other-process'})[0], 403)
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {'process_id':'owned-process', 'submitter':'forged'})[0], 202)
        self.assertEqual(httpd.knowledge.calls[-1][2], 'verified-employee')

    def test_local_owner_is_not_misrepresented_as_a_verified_employee(self):
        httpd = self.serve({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'local'})
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', {})[0], 202)
        self.assertIsNone(httpd.knowledge.calls[-1][2])

    def test_trusted_capabilities_require_a_complete_principal_identifier(self):
        identity = 'x' * 200
        httpd = self.serve(authorizer=lambda handler, capability: identity)
        for identity, allowed in (('x' * 200, True), ('x' * 201, False),
                                  (' name ', False), ('name\ncontinued', False)):
            with self.subTest(length=len(identity), allowed=allowed):
                config = self.request(httpd, '/api/config')[1]
                self.assertIs(config['revisions_available'], allowed)
                status, _ = self.request(httpd, '/api/knowledge/submit', {'process_id': 'owned-process'})
                self.assertEqual(status, 202 if allowed else 403)
        self.assertEqual([call[2] for call in httpd.knowledge.calls], ['x' * 200])

    def test_same_origin_and_csrf_apply_to_every_knowledge_endpoint(self):
        httpd = self.serve({'KNOWLEDGE_LOCAL_OWNER':'true','COLLECTOR_DEPLOYMENT_MODE':'local'})
        for route in ('submit', 'status'):
            path = '/api/knowledge/' + route
            self.assertEqual(self.request(httpd, path, {}, {'X-CSRF-Token':'wrong'})[0], 403)
            self.assertEqual(self.request(httpd, path, {}, {'Origin':'https://attacker.example'})[0], 403)
        self.assertEqual(httpd.knowledge.calls, [])

    def test_employee_status_capability_is_scoped_to_the_filed_revision(self):
        httpd = self.serve()
        request = {'submission_id':'owned', 'revision':1, 'status_token':'test-capability'}
        status, result = self.request(httpd, '/api/knowledge/status', request)
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {'submission_id','revision','job_id','status','error','attempts'})
        for overrides in ({'submission_id':'other'}, {'revision':2}, {'status_token':'forged'}):
            self.assertEqual(self.request(httpd, '/api/knowledge/status', {**request, **overrides})[0], 403)

    def test_document_references_are_resolved_from_scope_not_browser_claims(self):
        httpd = self.serve()
        scope = httpd.documents_store.create_scope()
        record = httpd.documents_store.add(scope, 'actual.csv', b'column\nvalue\n')
        httpd.documents_store.extract(scope,record['id'])
        httpd.documents_store.update(scope,record['id'],{'analysis':{'phase':'complete','disposition':'relevant'}})
        payload = {'documents': {'scope': scope, 'documents': [{'id': record['id'], 'name': 'forged.csv', 'sources': [{'source_id':'forged'}]}]}}
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', payload)[0], 202)
        _, received, _, private_scope = httpd.knowledge.calls[-1]
        self.assertEqual(private_scope, scope)
        self.assertEqual(received['documents']['documents'][0]['name'], 'actual.csv')
        self.assertEqual(received['documents']['documents'][0]['sources'], [])
        self.assertNotIn('scope', received['documents'])
        payload['documents']['scope'] = httpd.documents_store.create_scope()
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', payload)[0], 403)

    def test_cited_document_evidence_is_rehydrated_separately_from_browser_catalog(self):
        httpd = self.serve()
        scope = httpd.documents_store.create_scope()
        record = httpd.documents_store.add(scope, 'procedure.csv', b'action,actor\nRecord receipt,Treasury\n')
        httpd.documents_store.extract(scope, record['id'])
        source = httpd.documents_store.chunks(scope, record['id'])['chunks'][0]
        payload = {'documents': {'scope': scope, 'documents': [{'id': record['id']}]},
                   'workflow': {'steps': [{'id': 'S1', 'evidence_turns': [source['id']]}]},
                   'document_evidence': [{'id': source['id'], 'text': 'FORGED_TEXT'}]}
        status, result = self.request(httpd, '/api/knowledge/submit', payload)
        self.assertEqual(status, 202, result)
        _, received, _, private_scope = httpd.knowledge.calls[-1]
        self.assertEqual(private_scope, scope)
        self.assertNotIn('document_evidence', received, 'Browser catalogs never cross the trusted catalog boundary')
        catalog = httpd.knowledge.document_evidence
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]['id'], source['id'])
        self.assertEqual(catalog[0]['text'], source['text'])
        self.assertEqual(catalog[0]['name'], 'procedure.csv')
        self.assertIn({'source_id': source['id'], 'label': source['label']}, received['documents']['documents'][0]['sources'])
        payload['documents']['scope'] = httpd.documents_store.create_scope()
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', payload)[0], 403)

    def test_cited_document_source_without_an_attached_authorized_file_is_rejected(self):
        httpd = self.serve()
        payload = {'workflow': {'steps': [{'id': 'S1', 'evidence_turns': ['doc_missing_p1_c1']}]},
                   'document_evidence': [{'id': 'doc_missing_p1_c1', 'text': 'FORGED_TEXT'}]}
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', payload)[0], 400)
        self.assertEqual(httpd.knowledge.calls, [])


class KnowledgeRealHTTPTests(unittest.TestCase):
    setUp = KnowledgeAPITests.setUp
    tearDown = KnowledgeAPITests.tearDown
    request = KnowledgeAPITests.request

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

    def test_original_submitter_can_continue_after_admin_revises(self):
        from test_knowledge_graph import payload
        employee=self.serve_real(lambda h,c: 'original-owner' if c=='knowledge.submit' else None)
        admin=self.serve_real(lambda h,c: 'admin-editor')
        original=payload('Publishing','We publish approved NAV.')
        status,first=self.request(employee,'/api/knowledge/submit',original)
        self.assertEqual(status,202,first)
        correction={**original,'process_id':first['process_id']}
        correction['turns']=[{'id':'u1','role':'user','text':'Publication follows final sign-off.'}]
        status,second=self.request(admin,'/api/knowledge/submit',correction)
        self.assertEqual(status,202,second)
        follow_up={**correction,'turns':correction['turns']+[{'id':'u2','role':'user','text':'The controller signs off.'}]}
        status,third=self.request(employee,'/api/knowledge/submit',follow_up)
        self.assertEqual(status,202,third)
        self.assertEqual(third['revision'],3)
        rows=submissions(employee.knowledge)
        self.assertEqual({r['revision']:r['submitter'] for r in rows},
                         {1:'original-owner',2:'admin-editor',3:'original-owner'})

    def test_document_simulation_preserves_provenance_without_verified_employee_identity(self):
        from test_knowledge_graph import payload,simulation_provenance
        admin=self.serve_real(lambda h,c:'verified-admin' if c=='knowledge.admin' else None)
        submitted=payload('Document-derived walkthrough','The source describes preparing the file.')
        submitted.update(capture_provenance=simulation_provenance(),
                         participant='AI-simulated participant; no employee interview',submitter='forged employee')
        code,receipt=self.request(admin,'/api/knowledge/submit',submitted)
        self.assertEqual(code,202,receipt)
        saved = submissions(admin.knowledge)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['capture_provenance'], simulation_provenance())
        self.assertIsNone(saved[0]['submitter'])
        submitted['capture_provenance']['process_owner_approved']=True
        self.assertEqual(self.request(admin,'/api/knowledge/submit',submitted)[0],400)
        self.assertEqual(len(submissions(admin.knowledge)),1)

    def test_submission_and_scoped_status_survive_revision_and_restart(self):
        from test_knowledge_graph import payload
        employee = self.serve_real(lambda h,c: 'verified-employee' if c == 'knowledge.submit' else None)
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
        saved = next(item for item in submissions(employee.knowledge) if item['submission_id'] == first['submission_id'])
        self.assertEqual(saved['submitter'], 'verified-employee')
        self.assertEqual(saved['documents']['documents'][0]['name'], 'support.csv')
        for secret in (scope, first['status_token'], 'synthetic-old-status-capability'):
            self.assertNotIn(secret, json.dumps(saved))
        a['process_id'] = first['process_id']
        a['turns'][0]['text'] = 'Corrected NAV account.'
        status, revised = self.request(employee, '/api/knowledge/submit', a)
        self.assertEqual(status, 202, revised)
        self.assertEqual(revised['revision'], 2)
        self.assertEqual(self.request(employee, '/api/knowledge/status', {**first_status, 'revision':2})[0], 403)
        for httpd, worker in self.instances:
            httpd.shutdown(); httpd.server_close(); worker.join(timeout=3)
        self.instances.clear()
        reopened = self.serve_real(None)
        self.assertEqual(self.request(reopened, '/api/knowledge/status', first_status)[0], 200)
        self.assertEqual(sorted(item['revision'] for item in submissions(reopened.knowledge)
                                if item['submission_id'] == first['submission_id']), [1, 2])

    def test_matching_resolves_document_evidence_without_leaking_private_scope(self):
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
        httpd = self.serve_real(None, analyze)
        scope = httpd.documents_store.create_scope()
        document = httpd.documents_store.add(scope, 'support.csv', b'field,value\nnav,approved\n')
        httpd.documents_store.extract(scope, document['id'])
        source = httpd.documents_store.chunks(scope, document['id'])['chunks'][0]
        httpd.documents_store.update(scope, document['id'], {'analysis': {'sources':[{'source_id':source['id'], 'label':source['label']}]}})
        first = payload('Publish', 'We publish approved NAV.')
        first['documents'] = {'scope':scope, 'documents':[{'id':document['id']}]}
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', first)[0], 202)
        second = payload('Statements', 'We use approved NAV.')
        second['documents'] = None
        self.assertEqual(self.request(httpd, '/api/knowledge/submit', second)[0], 202)
        for _ in range(200):
            matched = proposals(httpd.knowledge)
            if matched:
                break
            time.sleep(.01)
        self.assertEqual(len(matched), 1)
        self.assertNotIn(scope, json.dumps(matched))
        item = matched[0]
        self.assertEqual(item['evidence'][0]['type'], 'document_supported')
        self.assertEqual(item['evidence'][0]['source_id'], source['id'])

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
        self.assertEqual(status,202,recovered);self.assertEqual(recovered,{**first,'status':recovered['status']})
        httpd.documents_store.archive(scope,document['id'])
        with patch.object(httpd.documents_store,'get',side_effect=AssertionError('Archived file must not block exact receipt recovery')):
            status,recovered=self.request(httpd,'/api/knowledge/submit',retry)
        self.assertEqual(status,202,recovered);self.assertEqual(recovered,{**first,'status':recovered['status']})
        changed=copy.deepcopy(retry);changed['turns'][0]['text']='A different account.'
        self.assertEqual(self.request(httpd,'/api/knowledge/submit',changed)[0],400)
        changed=copy.deepcopy(retry);changed['documents']['scope']='different-scope'
        self.assertEqual(self.request(httpd,'/api/knowledge/submit',changed)[0],400,'The original private scope remains bound to intent.')
        identity['employee']='another-employee'
        self.assertEqual(self.request(httpd,'/api/knowledge/submit',retry)[0],400)
        identity['employee']='verified-employee'
        saved = submissions(httpd.knowledge)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['documents']['documents'][0]['sources'],[],'Saved evidence is not rewritten by later source discovery.')
        self.assertNotIn(scope,json.dumps(saved));self.assertNotIn('intent_digest',json.dumps(saved))
        for running,worker in self.instances:
            running.shutdown();running.server_close();worker.join(timeout=3)
        self.instances.clear()
        reopened=self.serve_real(authorizer,lambda current,candidates:[])
        self.assertEqual(self.request(reopened,'/api/knowledge/submit',retry),(202,{**first,'status':'completed'}),'Raw-intent recovery survives restart with the original document archived.')


if __name__ == "__main__":
    unittest.main()
