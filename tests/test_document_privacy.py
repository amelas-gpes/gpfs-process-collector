"""A file's record outlives its interview on this computer, so it must not copy what the participant said."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import quote
from urllib.request import Request, urlopen

import test_document_api as api
from test_server import server

spec = importlib.util.spec_from_file_location('collector_document_service_privacy', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
import documents

ANSWER = 'ZQTRANSCRIPT-5512 I handle refunds. The test account is 000-ZQACCT-123.'
EARLIER = 'ZQEARLIER-7781 We also keep a paper log.'
QUESTION = 'Which export do you check first?'
TURNS = [{'id': 'a1', 'role': 'assistant', 'text': 'What do you do when a refund arrives?'},
         {'id': 'u1', 'role': 'user', 'text': EARLIER},
         {'id': 'a2', 'role': 'assistant', 'text': QUESTION},
         {'id': 'u2', 'role': 'user', 'text': ANSWER}]
CSV = b'stage,owner\nintake,FictionalClerk\n'


def stored_bytes(root):
    return b''.join(path.read_bytes() for path in sorted(Path(root).rglob('*')) if path.is_file())


class UploadContext(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'documents'
        self.store = documents.DocumentStore(self.root)
        self.services = []

    def service(self, callback=None):
        instance = service_module.DocumentService(self.store, callback or (lambda *arguments: self.fail('no review is expected')))
        self.services.append(instance)
        self.addCleanup(lambda: instance._worker.join(timeout=4))
        self.addCleanup(instance.close)
        return instance

    def test_upload_records_where_the_file_was_supplied_and_none_of_the_participants_words(self):
        service = self.service()
        service._schedule = lambda *arguments: None
        for label, context, expected in (
                ('as the server sends it', {'context': {'process_name': 'Refunds', 'process_owner': 'ZQOWNER', 'objective': 'Map refunds',
                                                        'background': 'ZQBACKGROUND notes'}, 'turns': TURNS, 'focus': 'ZQFOCUS',
                                            'current_question': QUESTION, 'latest_question': QUESTION},
                 {'process_name': 'Refunds', 'objective': 'Map refunds', 'latest_question': QUESTION, 'turn_id': 'u2'}),
                ('without a current question: the last one asked', {'process_name': 'Refunds', 'turns': TURNS},
                 {'process_name': 'Refunds', 'latest_question': QUESTION, 'turn_id': 'u2'}),
                ('a turn ID given directly', {'latest_question': QUESTION, 'turn_id': 'u9', 'role': 'reviewer'},
                 {'latest_question': QUESTION, 'turn_id': 'u9', 'role': 'reviewer'}),
                ('no interview yet', {}, {})):
            with self.subTest(context=label):
                scope = service.session(None, context)['scope']
                record = service.upload(scope, 'ledger.csv', CSV)
                self.assertEqual(record['context'], expected)
                self.assertEqual(self.store.get(scope, record['id'])['context'], expected)
        everything = stored_bytes(self.root)
        self.assertIn(QUESTION.encode(), everything)
        for words in (b'ZQTRANSCRIPT', b'ZQACCT', b'ZQEARLIER', b'ZQBACKGROUND', b'ZQFOCUS', b'ZQOWNER'):
            self.assertNotIn(words, everything, 'the interview was copied into the file store')

    def test_review_started_from_the_stored_context_alone_is_tied_to_the_same_question_and_turn(self):
        first = self.service()
        first._schedule = lambda *arguments: None
        scope = first.session(None, {'process_name': 'Refunds', 'turns': TURNS, 'latest_question': QUESTION})['scope']
        record = first.upload(scope, 'ledger.csv', CSV)
        first.close()
        seen = []

        def review(context, current, chunks, phase):
            seen.append(context)
            return {'summary': 'A stage list.', 'acknowledgement': 'Read.', 'relevance': 'relevant', 'relevance_reason': 'It lists stages.',
                    'question': '', 'queries': [], 'observations': [], 'questions': [], 'extracted_text': ''}
        # After a restart nothing but the record says where the file belongs.
        later = self.service(review)
        later.status(scope)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            analysis = self.store.get(scope, record['id']).get('analysis') or {}
            if analysis.get('phase') == 'complete':
                break
            threading.Event().wait(.01)
        self.assertEqual((analysis['basis_turn_id'], analysis['basis_question']), ('u2', QUESTION))
        self.assertEqual(seen[0], {'process_name': 'Refunds', 'latest_question': QUESTION, 'turn_id': 'u2'})

    def test_http_upload_keeps_the_answer_out_of_the_file_store(self):
        httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=api.FakeProvider(), documents_root=self.root.parent / 'served')
        worker = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=2)
            for document_worker in httpd.documents._workers:
                document_worker.join(timeout=10)
        running = self.enterContext(ExitStack())
        running.callback(stop)
        url = f'http://127.0.0.1:{httpd.server_port}'

        def post(path, payload, headers=None):
            binary = isinstance(payload, bytes)
            sent = {'Origin': url, 'X-CSRF-Token': httpd.csrf_token,
                    'Content-Type': 'application/octet-stream' if binary else 'application/json', **(headers or {})}
            with urlopen(Request(url + path, data=payload if binary else json.dumps(payload).encode(), headers=sent), timeout=10) as response:
                return json.loads(response.read())
        interview = {'context': {'process_name': 'Refunds', 'objective': 'Map refunds'}, 'turns': TURNS, 'current_question': QUESTION}
        scope = post('/api/documents/session', interview)['scope']
        uploaded = post('/api/documents/upload', CSV, {'X-Document-Scope': scope, 'X-Document-Filename': quote('ledger.csv', safe='')})['document']
        self.assertEqual(uploaded['context'], {'process_name': 'Refunds', 'objective': 'Map refunds', 'latest_question': QUESTION, 'turn_id': 'u2'})
        post('/api/documents/action', {'scope': scope, 'id': uploaded['id'], 'action': 'remove'})
        # Close the workers and SQLite handles before inspecting every persisted byte on Windows.
        running.close()
        self.assertFalse(any(worker.is_alive() for worker in httpd.documents._workers))
        everything = stored_bytes(self.root.parent / 'served')
        self.assertIn(b'FictionalClerk', everything, 'Remove is not erasure: the file and its text stay on this computer')
        for words in (b'ZQTRANSCRIPT', b'ZQACCT', b'ZQEARLIER'):
            self.assertNotIn(words, everything)


if __name__ == '__main__':
    unittest.main()
