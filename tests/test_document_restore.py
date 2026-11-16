"""Restore puts a removed file back as it was; Revisit is the action that reviews a file again.

Removed files are listed for the interview that owns them, so that a file removed by mistake (or
before this listing existed) can be returned. Temporary stores and loopback HTTP only; the document
reviewer is a counting stand-in.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from test_server import server
from test_document_api import FakeProvider

spec = importlib.util.spec_from_file_location('restore_document_service', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
from documents import DocumentStore

CSV = b'important,field\nalpha,42\n'


def response(chunks):
    sources = [chunks[0]['id']] if chunks else []
    return {'summary': 'A synthetic document account.', 'acknowledgement': 'I have reviewed the first relevant sections.',
            'relevance': 'relevant', 'relevance_reason': 'Synthetic relation to intake.', 'question': 'Which of these fields do you use?',
            'queries': ['important'], 'observations': [{'text': 'The document describes intake fields.', 'sources': sources}] if sources else [],
            'questions': [], 'extracted_text': ''}


class RestoreServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DocumentStore(Path(self.temp.name) / 'documents')
        self.services = []
        self.scope = self.store.create_scope()

    def tearDown(self):
        for service in self.services:
            service.close()
            service._worker.join(timeout=12)
            self.assertFalse(service._worker.is_alive())
        self.temp.cleanup()

    def service(self, callback):
        instance = service_module.DocumentService(self.store, callback)
        self.services.append(instance)
        instance.session(self.scope, {'process_name': 'Synthetic intake', 'latest_question': 'Which fields are important?'})
        return instance

    def wait(self, identity, phase='complete', timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            record = self.store.get(self.scope, identity)
            if (record.get('analysis') or {}).get('phase') == phase:
                return record
            threading.Event().wait(.01)
        self.fail(f'Document did not reach {phase}: {self.store.get(self.scope, identity)}')

    def idle(self, service, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with service._condition:
                if not service._running and not service._queued:
                    return
            threading.Event().wait(.01)
        self.fail('The document reviewer did not become idle.')

    def test_restore_returns_a_removed_file_as_it_was_and_starts_no_review(self):
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or response(chunks))
        record = service.upload(self.scope, 'returns-log.csv', CSV)
        before = self.wait(record['id'])
        self.idle(service)
        reviewed = len(calls)
        seen_by_interview = service.supporting_context(self.scope, 'important')['documents'][0]['source_revision']
        self.assertTrue(service.action(self.scope, record['id'], 'remove')['archived'])
        listing = service.listing(self.scope)
        self.assertEqual(listing['documents'], [])
        self.assertEqual(listing['removed'], [{'id': record['id'], 'name': 'returns-log.csv', 'kind': 'csv', 'size': len(CSV)}])
        self.assertEqual(service.status(self.scope), [])
        self.assertEqual(service.supporting_context(self.scope, 'important')['documents'], [])
        restored = service.action(self.scope, record['id'], 'restore')
        self.assertIs(restored['archived'], False)
        for key in ('phase', 'disposition', 'summary', 'cursor', 'reviewed_chunks', 'total_chunks', 'review_complete',
                    'intent_version', 'sources', 'questions', 'observations', 'acknowledgement'):
            self.assertEqual(restored['analysis'].get(key), before['analysis'].get(key), key)
        for _ in range(3):
            service.status(self.scope)
        self.idle(service)
        threading.Event().wait(.1)
        self.assertEqual(len(calls), reviewed, 'Restore must not send the file to the reviewer again')
        listing = service.listing(self.scope)
        self.assertEqual([item['id'] for item in listing['documents']], [record['id']])
        self.assertEqual(listing['removed'], [])
        self.assertEqual(service.supporting_context(self.scope, 'important')['documents'][0]['source_revision'], seen_by_interview,
                         'The interview sees the same file as before it was removed')

    def test_revisit_remains_the_action_that_reviews_a_removed_file_again(self):
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or response(chunks))
        record = service.upload(self.scope, 'returns-log.csv', CSV)
        before = self.wait(record['id'])
        self.idle(service)
        reviewed = len(calls)
        service.action(self.scope, record['id'], 'remove')
        service.action(self.scope, record['id'], 'revisit')
        after = self.wait(record['id'])
        self.idle(service)
        self.assertGreater(len(calls), reviewed)
        self.assertGreater(after['analysis']['intent_version'], before['analysis']['intent_version'])

    def test_restoring_a_file_that_was_not_removed_changes_nothing(self):
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or response(chunks))
        record = service.upload(self.scope, 'returns-log.csv', CSV)
        before = self.wait(record['id'])
        self.idle(service)
        reviewed = len(calls)
        self.assertEqual(service.action(self.scope, record['id'], 'restore'), before)
        self.assertEqual(self.store.get(self.scope, record['id']), before)
        self.idle(service)
        self.assertEqual(len(calls), reviewed)

    def test_review_that_had_not_finished_continues_after_restore(self):
        entered, release, calls = threading.Event(), threading.Event(), []
        def analyze(context, record, chunks, phase):
            calls.append(phase)
            if len(calls) == 1:
                entered.set()
                release.wait(10)
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'returns-log.csv', CSV)
        self.assertTrue(entered.wait(10))
        service.action(self.scope, record['id'], 'remove')
        release.set()
        self.idle(service)
        self.assertNotIn('summary', self.store.get(self.scope, record['id']).get('analysis') or {}, 'A removed file takes no late review result')
        service.action(self.scope, record['id'], 'restore')
        service.status(self.scope)
        final = self.wait(record['id'])
        self.assertIn('summary', final['analysis'])
        self.assertGreaterEqual(len(calls), 2)

    def test_file_removed_before_its_first_review_started_is_reviewed_once_restored(self):
        # Read, then removed before any review phase was recorded (also the state of older stores).
        record = self.store.add(self.scope, 'early.csv', CSV)
        self.store.extract(self.scope, record['id'])
        self.store.update(self.scope, record['id'], {'analysis': {'intent_version': 1, 'version': 1}})
        self.store.archive(self.scope, record['id'])
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or response(chunks))
        self.idle(service)
        self.assertEqual(calls, [])
        service.action(self.scope, record['id'], 'restore')
        service.status(self.scope)
        self.assertIn('summary', self.wait(record['id'])['analysis'])

    def test_removed_files_are_listed_only_for_their_own_scope(self):
        service = self.service(lambda context, record, chunks, phase: response(chunks))
        record = service.upload(self.scope, 'returns-log.csv', CSV)
        self.wait(record['id'])
        service.action(self.scope, record['id'], 'remove')
        other = self.store.create_scope()
        self.assertEqual(service.listing(other), {'documents': [], 'removed': [],
                                                  'limit': {'maximum': 20, 'used': 0, 'removed': 0}})  # 'limit' added by live-documents-13
        self.assertEqual(service.session(other)['removed'], [])
        self.assertEqual([item['id'] for item in service.session(self.scope)['removed']], [record['id']])
        with self.assertRaises(PermissionError):
            service.action(other, record['id'], 'restore')
        self.assertTrue(self.store.get(self.scope, record['id'])['archived'])


class RestoreHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.client = FakeProvider()
        self.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / 'documents')
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temporary.cleanup()

    def post(self, path, payload, headers=None):
        binary = isinstance(payload, bytes)
        sent = {'Origin': self.url, 'X-CSRF-Token': self.httpd.csrf_token,
                'Content-Type': 'application/octet-stream' if binary else 'application/json', **(headers or {})}
        try:
            with urlopen(Request(self.url + path, data=payload if binary else json.dumps(payload).encode(), headers=sent), timeout=15) as reply:
                return reply.status, json.loads(reply.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def ready(self, scope, identity):
        end = time.monotonic() + 20
        while time.monotonic() < end:
            record = self.httpd.documents_store.get(scope, identity)
            if (record.get('analysis') or {}).get('phase') == 'complete':
                return record
            time.sleep(.05)
        self.fail('Synthetic background review did not complete.')

    def test_status_lists_removed_files_and_restore_returns_one_without_a_new_review(self):
        status, session = self.post('/api/documents/session', {'context': {}, 'turns': [], 'current_question': 'Which fields matter?'})
        self.assertEqual(status, 200, session)
        self.assertEqual(session['removed'], [])
        scope = session['scope']
        status, uploaded = self.post('/api/documents/upload', CSV, {'X-Document-Scope': scope, 'X-Document-Filename': quote('returns-log.csv', safe='')})
        self.assertEqual(status, 202, uploaded)
        identity = uploaded['document']['id']
        before = self.ready(scope, identity)
        poll = {'scope': scope, 'context': {}, 'turns': []}
        self.assertEqual(self.post('/api/documents/status', poll)[1]['removed'], [])
        reviewed = len(self.client.analysis_calls)
        status, removed = self.post('/api/documents/action', {'scope': scope, 'id': identity, 'action': 'remove'})
        self.assertEqual((status, removed['document']['archived']), (200, True))
        status, listing = self.post('/api/documents/status', poll)
        self.assertEqual(status, 200, listing)
        self.assertEqual(listing['documents'], [])
        self.assertEqual(listing['removed'], [{'id': identity, 'name': 'returns-log.csv', 'kind': 'csv', 'size': len(CSV)}])
        self.assertEqual(self.post('/api/documents/session', {'scope': scope, 'context': {}, 'turns': []})[1]['removed'], listing['removed'])
        other = self.post('/api/documents/session', {'context': {}, 'turns': []})[1]['scope']
        self.assertEqual(self.post('/api/documents/status', {**poll, 'scope': other})[1]['removed'], [])
        self.assertEqual(self.post('/api/documents/action', {'scope': other, 'id': identity, 'action': 'restore'})[0], 403)
        status, restored = self.post('/api/documents/action', {'scope': scope, 'id': identity, 'action': 'restore'})
        self.assertEqual(status, 200, restored)
        self.assertIs(restored['document']['archived'], False)
        self.assertEqual(restored['document']['analysis']['intent_version'], before['analysis']['intent_version'])
        self.assertEqual(restored['document']['analysis']['phase'], 'complete')
        for _ in range(3):
            status, listing = self.post('/api/documents/status', poll)
        self.assertEqual(([item['id'] for item in listing['documents']], listing['removed']), ([identity], []))
        time.sleep(.2)
        self.assertEqual(len(self.client.analysis_calls), reviewed, 'Restore must not send the file to the reviewer again')
        self.client.request.assert_not_called()
        status, refused = self.post('/api/documents/action', {'scope': scope, 'id': identity, 'action': 'undelete'})
        self.assertEqual(status, 400)
        self.assertIn('restore', refused['error'])


if __name__ == '__main__':
    unittest.main()
