"""The workspace says how many of an interview's file slots are used, removed files included."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import test_document_api as api
from test_server import server

spec = importlib.util.spec_from_file_location('collector_document_service_file_limit', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
import documents

CSV = b'stage,owner\nintake,FictionalClerk\n'


class ServiceCounts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.service = service_module.DocumentService(self.store, lambda *arguments: self.fail('no review is expected'))
        self.addCleanup(lambda: self.service._worker.join(timeout=4))
        self.addCleanup(self.service.close)
        self.service._schedule = lambda *arguments: None  # These tests count files; they review none.

    def test_session_and_status_count_every_stored_file_and_the_removed_ones(self):
        opened = self.service.session(None, {})
        scope = opened['scope']
        self.assertEqual(opened['limit'], {'maximum': documents.MAX_FILES_PER_SCOPE, 'used': 0, 'removed': 0})
        records = [self.service.upload(scope, f'file{index}.csv', CSV + str(index).encode()) for index in range(3)]
        self.assertEqual(self.service.listing(scope)['limit'], {'maximum': 20, 'used': 3, 'removed': 0})
        self.service.action(scope, records[0]['id'], 'remove')
        listing = self.service.listing(scope)
        self.assertEqual(listing['limit'], {'maximum': 20, 'used': 3, 'removed': 1})
        self.assertEqual((len(listing['documents']), len(listing['removed'])), (2, 1))
        self.assertEqual(self.service.session(scope)['limit'], listing['limit'])
        self.service.action(scope, records[0]['id'], 'restore')
        self.assertEqual(self.service.listing(scope)['limit'], {'maximum': 20, 'used': 3, 'removed': 0})
        # Another interview has its own count.
        self.assertEqual(self.service.session(None, {})['limit']['used'], 0)

    def test_count_reaches_the_maximum_exactly_when_the_store_refuses_the_next_file(self):
        scope = self.service.session(None, {})['scope']
        for index in range(documents.MAX_FILES_PER_SCOPE):
            record = self.service.upload(scope, f'file{index}.csv', CSV + str(index).encode())
            self.assertLess(self.service.listing(scope)['limit']['used'] - 1, documents.MAX_FILES_PER_SCOPE)
            self.service.action(scope, record['id'], 'remove')
        listing = self.service.listing(scope)
        # The audit's case: nothing is listed as a file of the interview, and every slot is used.
        self.assertEqual((listing['documents'], listing['limit']), ([], {'maximum': 20, 'used': 20, 'removed': 20}))
        with self.assertRaises(documents.DocumentError) as refusal:
            self.service.upload(scope, 'one-more.csv', CSV)
        self.assertIn('already has 20 documents, including archived originals', str(refusal.exception))
        self.assertEqual(self.service.listing(scope)['limit']['used'], 20)


class LimitOverHTTP(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=api.FakeProvider(),
                                            documents_root=Path(self.temporary.name) / 'documents')
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=2)
        self.httpd.documents._worker.join(timeout=10)  # A review still unwinding holds the database open.
        self.temporary.cleanup()

    def post(self, path, payload, headers=None):
        binary = isinstance(payload, bytes)
        sent = {'Origin': self.url, 'X-CSRF-Token': self.httpd.csrf_token,
                'Content-Type': 'application/octet-stream' if binary else 'application/json', **(headers or {})}
        try:
            with urlopen(Request(self.url + path, data=payload if binary else json.dumps(payload).encode(), headers=sent), timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_session_and_status_replies_carry_the_count(self):
        status, opened = self.post('/api/documents/session', {'context': {}, 'turns': []})
        self.assertEqual((status, opened['limit']), (200, {'maximum': 20, 'used': 0, 'removed': 0}))
        scope = opened['scope']
        uploaded = [self.post('/api/documents/upload', CSV + str(index).encode(), {'X-Document-Scope': scope, 'X-Document-Filename': quote(f'f{index}.csv', safe='')})[1]['document']
                    for index in range(2)]
        self.assertEqual(self.post('/api/documents/action', {'scope': scope, 'id': uploaded[0]['id'], 'action': 'remove'})[0], 200)
        status, listed = self.post('/api/documents/status', {'scope': scope, 'context': {}, 'turns': []})
        self.assertEqual((status, listed['limit']), (200, {'maximum': 20, 'used': 2, 'removed': 1}))
        status, reopened = self.post('/api/documents/session', {'scope': scope, 'context': {}, 'turns': []})
        self.assertEqual((status, reopened['limit']), (200, listed['limit']))


if __name__ == '__main__':
    unittest.main()
