"""Interview text of any script must never stop the file workspace, its status poll or an upload.

The context that travels with these requests is a hint for the file review. Its limits are
measured in characters, the unit the rest of the API uses, and an oversized context is
shortened, never refused.
"""
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

spec = importlib.util.spec_from_file_location('collector_document_service_limits', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
from unittest.mock import patch
import documents
from documents import DocumentStore, DocumentError, _context as stored_context

# One character of each costs six bytes as an ASCII JSON escape; in UTF-8 two, three and four.
SCRIPTS = {'cyrillic': 'ж', 'cjk': '流', 'astral': '\U0001F4C4'}


def long_text(character, length, lead='Q'):
    return (lead + ' ' + character * length)[:length]


def interview(character, turn_chars=6000, background_chars=8000):
    turns = [{'id': f't{index}', 'role': 'user' if index % 2 else 'assistant', 'text': long_text(character, turn_chars, f'turn{index}')}
             for index in range(1, 5)]
    return {'context': {'process_name': long_text(character, 500, 'name'), 'process_owner': 'Owner',
                        'objective': long_text(character, 500, 'goal'), 'background': long_text(character, background_chars, 'background')},
            'turns': turns, 'focus': long_text(character, 1000, 'focus'),
            'current_question': long_text(character, 6000, 'question')}


class ServiceContextLimits(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = DocumentStore(Path(self.temporary.name) / 'documents')
        self.service = service_module.DocumentService(self.store, lambda *arguments: self.fail('no review is expected'))
        self.addCleanup(lambda: self.service._worker.join(timeout=4))
        self.addCleanup(self.service.close)
        self.service._schedule = lambda *arguments: None  # These tests are about the context, not the review.

    def current(self, character, **sizes):
        value = interview(character, **sizes)
        return {**value, 'latest_question': value['current_question']}

    def test_largest_context_the_api_accepts_opens_a_workspace_and_polls_in_every_script(self):
        for name, character in SCRIPTS.items():
            with self.subTest(script=name):
                context = self.current(character)
                scope = self.service.session(None, context)['scope']
                self.assertEqual(self.service.status(scope, context), [])
                self.assertEqual(self.service.listing(scope, context)['documents'], [])
                # Nothing the API accepts needs shortening: the review receives the interview as it is.
                self.assertEqual(self.service._contexts[scope], context)

    def test_upload_is_accepted_with_long_non_latin_turns_and_its_stored_context_is_bounded(self):
        for name, character in SCRIPTS.items():
            with self.subTest(script=name):
                context = self.current(character)
                scope = self.service.session(None, context)['scope']
                record = self.service.upload(scope, 'ledger.csv', b'stage,owner\nintake,FictionalClerk\n')
                saved = self.store.get(scope, record['id'])['context']
                self.assertLessEqual(len(json.dumps(saved, ensure_ascii=False).encode('utf-8')), 32 * 1024)
                self.assertTrue(saved['latest_question'].startswith('question'), 'the question the file answers was lost')
                self.assertEqual(stored_context(saved), saved, 'the store itself would refuse what the service saved')

    def test_question_longer_than_the_store_allowance_is_shortened_from_its_end(self):
        # Changed with gap-privacy-1: an upload no longer stores turns at all (tests/test_document_privacy.py),
        # so what can outgrow the store's 32 KiB is the question. Four-byte characters: 6,000 of them are 24 KB.
        for name, character in SCRIPTS.items():
            with self.subTest(script=name):
                with patch.object(documents, 'MAX_CONTEXT_BYTES', 4 * 1024):
                    context = {'process_name': 'Synthetic intake', 'latest_question': 'Which fields? ' + character * 5000, 'turn_id': 'u1'}
                    scope = self.service.session(None, context)['scope']
                    saved = self.service.upload(scope, 'ledger.csv', b'stage\nintake\n')['context']
                    self.assertLessEqual(documents.context_bytes(saved), 4 * 1024)
                self.assertTrue(saved['latest_question'].startswith('Which fields? '))
                self.assertTrue(saved['latest_question'].endswith(service_module.CLIPPED))
                self.assertEqual((saved['process_name'], saved['turn_id']), ('Synthetic intake', 'u1'))

    def test_context_larger_than_any_request_is_shortened_rather_than_refused(self):
        for name, character in SCRIPTS.items():
            with self.subTest(script=name):
                context = self.current(character, turn_chars=6000, background_chars=8000)
                context['turns'] = [{'id': f'x{index}', 'role': 'user', 'text': long_text(character, 6000, f'turn{index}') + ' END'}
                                    for index in range(12)]
                scope = self.service.session(None, context)['scope']
                kept = self.service._contexts[scope]
                self.assertLessEqual(len(json.dumps(kept, ensure_ascii=False)), service_module.MAX_CONTEXT_CHARS)
                # Same shape: every key, every turn and its identity; only long texts are shorter.
                self.assertEqual([turn['id'] for turn in kept['turns']], [turn['id'] for turn in context['turns']])
                self.assertEqual(set(kept), set(context))
                self.assertEqual(set(kept['context']), set(context['context']))
                self.assertTrue(all(turn['text'].endswith(' END') for turn in kept['turns']), 'a turn lost its latest words')
                self.assertTrue(kept['context']['background'].startswith('background'))
                self.assertEqual(kept['context']['process_owner'], 'Owner')
                self.assertEqual(self.service.status(scope, context), [])

    def test_only_a_context_that_is_not_interview_text_is_still_refused(self):
        with self.assertRaises(DocumentError):
            self.service.session(None, {'padding': ['x'] * 40000})
        with self.assertRaises(DocumentError):
            self.service.session(None, {'value': float('nan')})
        with self.assertRaises(DocumentError):
            self.service.session(None, ['not', 'an', 'object'])


class StoreContextLimit(unittest.TestCase):
    def test_store_measures_its_context_allowance_in_utf8_not_in_ascii_escapes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DocumentStore(Path(folder) / 'documents')
            scope = store.create_scope()
            # 6,000 Cyrillic characters: 12 KB of UTF-8, 36 KB as ASCII escapes.
            record = store.add(scope, 'a.csv', b'a\n1\n', {'latest_question': 'ж' * 6000})
            self.assertEqual(len(record['context']['latest_question']), 6000)
            with self.assertRaises(DocumentError):
                store.add(scope, 'b.csv', b'a\n1\n', {'turns': [{'role': 'user', 'text': '流' * 6000}] * 2})
            # A text the JSON parser accepts but UTF-8 cannot encode is measured, not a crash.
            self.assertEqual(stored_context({'latest_question': '\ud83d' * 10})['latest_question'], '\ud83d' * 10)


class DocumentContextHTTP(unittest.TestCase):
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
        raw = payload if binary else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        try:
            with urlopen(Request(self.url + path, data=raw, headers=sent), timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_session_status_and_upload_work_with_long_answers_in_every_script(self):
        for name, character in SCRIPTS.items():
            with self.subTest(script=name):
                payload = interview(character)
                status, opened = self.post('/api/documents/session', payload)
                self.assertEqual(status, 200, opened)
                scope = opened['scope']
                status, uploaded = self.post('/api/documents/upload', b'stage,owner\nintake,FictionalClerk\n',
                                             {'X-Document-Scope': scope, 'X-Document-Filename': quote('ledger.csv', safe='')})
                self.assertEqual(status, 202, uploaded)
                status, listed = self.post('/api/documents/status', {'scope': scope, **payload})
                self.assertEqual(status, 200, listed)
                self.assertEqual([item['id'] for item in listed['documents']], [uploaded['document']['id']])


if __name__ == '__main__':
    unittest.main()
