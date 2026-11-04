"""Real loopback/source retrieval across delayed review and cached confirmation."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from test_interview_orchestrator import SyntheticTeamProvider
from test_server import server


class ReviewSourceHydrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='collector-review-source-')
        self.client = SyntheticTeamProvider()
        self.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=self.client,
            documents_root=Path(self.temp.name) / 'documents', knowledge_root=Path(self.temp.name) / 'knowledge')
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        store = self.httpd.documents_store
        self.scope = store.create_scope()
        rows = ['topic,detail'] + [f'row{i},Invoice evidence material risk reference {i} ' + 'documented facts ' * 20 for i in range(1000)]
        record = store.add(self.scope, 'fictional-large-reference.csv', '\n'.join(rows).encode())
        self.document_id = record['id']
        store.extract(self.scope, self.document_id)
        store.update(self.scope, self.document_id, {'analysis': {
            'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'summary': 'Fictional documentary reference.'}})
        self.hydrate = Mock(wraps=self.httpd.documents.supporting_context)
        self.httpd.documents.supporting_context = self.hydrate

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def post(self, route, payload):
        request = Request(self.url + route, data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json', 'Origin': self.url, 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def prepare(self):
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        code, prepared = self.post('/api/interview', payload)
        self.assertEqual(code, 200, prepared)
        self.assertEqual(prepared['speech_authorization']['kind'], 'review_pending')
        payload['turns'].append({'id': 'review_ack', 'role': 'assistant', 'text': prepared['question']})
        payload.update(capture_token=prepared['capture_token'], review_ticket=prepared['review_ticket'])
        return payload, prepared

    def test_large_source_selection_stays_bound_through_ack_and_zero_call_confirmation(self):
        payload, prepared = self.prepare()
        initial_query = self.hydrate.call_args.args[1]
        self.assertEqual(self.client.request.call_count, 1)
        code, reviewed = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 200, reviewed)
        self.assertEqual(reviewed['speech_authorization']['kind'], 'final_check')
        self.assertEqual(self.hydrate.call_args.args[1], initial_query)
        self.assertTrue(self.hydrate.call_args.kwargs['source_ids'])
        self.assertEqual(self.client.request.call_count, 3)
        payload.pop('review_ticket')
        payload['capture_token'] = reviewed['capture_token']
        payload['turns'] += [{'id': 'global_check', 'role': 'assistant', 'text': reviewed['question']},
                            {'id': 'confirmation', 'role': 'user', 'text': "No, that's everything."}]
        code, completed = self.post('/api/interview', payload)
        self.assertEqual(code, 200, completed)
        self.assertTrue(completed['completion']['complete'])
        self.assertEqual(self.client.request.call_count, 3)
        self.assertEqual(self.hydrate.call_args.args[1], initial_query)

    def test_archiving_source_invalidates_prepared_review_before_provider_work(self):
        payload, _ = self.prepare()
        self.httpd.documents_store.archive(self.scope, self.document_id)
        code, result = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, result)
        self.assertEqual(self.client.request.call_count, 1)
        self.assertNotIn('speech_authorization', result)

    def test_ticket_cannot_authorize_a_different_document_scope(self):
        payload, _ = self.prepare()
        payload['document_scope'] = self.httpd.documents_store.create_scope()
        code, result = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, result)
        self.assertEqual(self.client.request.call_count, 1)

    def test_ordinary_turn_pins_private_fact_sources_without_browser_memo(self):
        # The coordinator supplies only citation IDs; the current scoped store
        # still loads their content. Neither the browser nor private metadata
        # can inject an excerpt or evade the HTTP release recheck.
        inventory = self.httpd.documents_store.chunks(self.scope, self.document_id, limit=1)
        source = self.httpd.documents_store.chunks(
            self.scope, self.document_id, offset=max(0, inventory['total'] - 2), limit=1)['chunks'][0]
        self.client.coordinator.fact_source_ids = Mock(return_value=[source['id']])
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        self.assertNotIn('previous_capture', payload)
        code, result = self.post('/api/interview', payload)
        self.assertEqual(code, 200, result)
        self.client.coordinator.fact_source_ids.assert_called_once()
        self.assertGreaterEqual(self.hydrate.call_count, 2)
        for call in self.hydrate.call_args_list:
            self.assertEqual(call.kwargs['source_ids'][0], source['id'])
        self.assertTrue(any(item['id'] == source['id'] and item['text'] == source['text']
                            for item in result['document_evidence']))

    def test_private_fact_source_preference_cannot_cross_document_scopes(self):
        source = self.httpd.documents_store.chunks(self.scope, self.document_id, limit=1)['chunks'][0]
        self.client.coordinator.fact_source_ids = Mock(return_value=[source['id']])
        payload = self.client.payload()
        payload['document_scope'] = self.httpd.documents_store.create_scope()
        code, result = self.post('/api/interview', payload)
        self.assertEqual(code, 200, result)
        self.assertFalse(result.get('document_evidence'))

    def test_source_archived_during_review_cannot_release_final_check_or_cached_permit(self):
        payload, prepared = self.prepare()
        self.client.hooks['process_specialist_review'] = lambda body: self.httpd.documents_store.archive(self.scope, self.document_id)
        code, result = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, result)
        self.assertNotIn('speech_authorization', result)
        self.assertTrue(self.client.coordinator.status(prepared['agent_run_id'])['cancelled'])
        calls = self.client.request.call_count
        code, replay = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, replay)
        self.assertEqual(self.client.request.call_count, calls)

    def test_new_pending_document_during_capture_withholds_old_response(self):
        def add_source(body):
            self.httpd.documents_store.add(self.scope, 'new-reference.csv', b'event,status\nchanged,pending')
        self.client.hooks['team_interview_capture'] = add_source
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        code, result = self.post('/api/interview', payload)
        self.assertEqual(code, 409, result)
        self.assertNotIn('speech_authorization', result)

    def test_source_archived_during_draft_withholds_stale_export(self):
        def make_draft(payload):
            self.httpd.documents_store.archive(self.scope, self.document_id)
            return {'draft': {'title': 'Stale draft must never be released'}}
        self.client.draft = Mock(side_effect=make_draft)
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        code, result = self.post('/api/draft', payload)
        self.assertEqual(code, 409, result)
        self.assertNotIn('draft', result)


if __name__ == '__main__':
    unittest.main()
