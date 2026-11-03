"""Deterministic background review, intent isolation and citation contracts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collector_document_service', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
from documents import DocumentStore


def response(chunks, relevance='relevant'):
    sources = [chunks[0]['id']] if chunks else []
    return {'summary': 'A synthetic document account.', 'acknowledgement': 'I have reviewed the first relevant sections.',
            'relevance': relevance, 'relevance_reason': 'Synthetic relation to intake.',
            'question': 'Which of these fields do you use?' if relevance == 'relevant' else '',
            'queries': ['important'], 'observations': [{'text': 'The document describes intake fields.', 'sources': sources}] if sources else [],
            'questions': [{'text': 'Is this tracker still current?', 'sources': sources}] if sources else [], 'extracted_text': ''}


class DocumentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DocumentStore(Path(self.temp.name) / 'documents')
        self.services = []
        self.scope = self.store.create_scope()
        self.context = {'process_name': 'Synthetic intake', 'latest_question': 'Which fields are important?',
                        'turns': [{'id': 'u2', 'role': 'user', 'text': 'Here is the tracker.'}]}

    def tearDown(self):
        for service in self.services:
            service.close()
        self.temp.cleanup()

    def service(self, callback):
        instance = service_module.DocumentService(self.store, callback)
        self.services.append(instance)
        instance.session(self.scope, self.context)
        return instance

    def wait(self, identity, phase='complete', timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            record = self.store.get(self.scope, identity)
            if (record.get('analysis') or {}).get('phase') == phase:
                return record
            threading.Event().wait(.01)
        self.fail(f'Document did not reach {phase}: {self.store.get(self.scope, identity)}')

    def test_relevant_document_gets_quick_then_complete_deep_review_and_unconfirmed_context(self):
        calls = []
        def analyze(context, record, chunks, phase):
            self.assertEqual(record['_scope'], self.scope)
            self.assertLessEqual(len(chunks), 8)
            self.assertLessEqual(sum(len(chunk['text']) for chunk in chunks), 24000)
            calls.append((phase, [chunk['id'] for chunk in chunks]))
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'intake.csv', b'important,field\nalpha,42\n')
        result = self.wait(record['id'])
        self.assertEqual(calls[0][0], 'quick')
        self.assertTrue(any(phase == 'deep' for phase, _ in calls))
        self.assertEqual(result['analysis']['reviewed_chunks'], result['analysis']['total_chunks'])
        self.assertTrue(result['analysis']['review_complete'])
        self.assertEqual(result['analysis']['basis_turn_id'], 'u2')
        self.assertEqual(result['analysis']['basis_question'], self.context['latest_question'])
        self.assertNotIn(self.scope, json.dumps(result))
        support = service.supporting_context(self.scope, 'important')
        self.assertTrue(support['unconfirmed'])
        self.assertIn('UNCONFIRMED', support['notice'])
        source = support['documents'][0]['excerpts'][0]
        self.assertEqual(service.source(self.scope, record['id'], source['id'])['text'], source['text'])
        other = self.store.create_scope()
        with self.assertRaises(PermissionError):
            service.source(other, record['id'], source['id'])

    def test_lexical_miss_uses_semantic_query_fallback_and_bounds_long_queries(self):
        def analyze(context, record, chunks, phase):
            value = response(chunks)
            value['queries'] = ['AlternateLookupTerm']
            return value
        service = self.service(analyze)
        record = service.upload(self.scope, 'alternate.csv', b'header,value\nAlternateLookupTerm,42\n')
        self.wait(record['id'])
        support = service.supporting_context(self.scope, 'CompletelyDifferent ' * 2000)
        self.assertTrue(support['unconfirmed'])
        self.assertEqual(support['documents'][0]['id'], record['id'])
        self.assertIn('AlternateLookupTerm', support['documents'][0]['excerpts'][0]['text'])
        self.assertEqual(support['documents'][0]['basis_question'], self.context['latest_question'])
        self.assertTrue(support['documents'][0]['questions'])

    def test_relevant_summary_and_questions_survive_a_total_lexical_miss_with_context_limits(self):
        def analyze(context, record, chunks, phase):
            value = response(chunks)
            value['summary'] = 'S' * 1200
            value['queries'] = ['NeverMatchesAnyFile']
            value['questions'] = [{'text': f'Question {i}', 'sources': [chunks[0]['id']]} for i in range(3)]
            return value
        service = self.service(analyze)
        records = [service.upload(self.scope, f'reference{i}.csv', b'header,value\na,42\n') for i in range(7)]
        for record in records:
            self.wait(record['id'])
        support = service.supporting_context(self.scope, 'AnotherCompletelyMissingTerm')
        self.assertEqual(len(support['documents']), 6)
        self.assertEqual(support['omitted_documents'], 1)
        for document in support['documents']:
            self.assertEqual(len(document['summary']), 700)
            self.assertTrue(document['summary_excerpt'])
            self.assertEqual(len(document['questions']), 2)
            self.assertEqual(document['excerpts'], [])
        service.action(self.scope, records[0]['id'], 'park')
        self.assertNotIn(records[0]['id'], [item['id'] for item in service.supporting_context(self.scope, 'AnotherCompletelyMissingTerm')['documents']])

    def test_reason_is_requested_once_then_unrelated_document_is_parked_without_question(self):
        calls = []
        def analyze(context, record, chunks, phase):
            calls.append(phase)
            return response(chunks, 'unrelated')
        service = self.service(analyze)
        record = service.upload(self.scope, 'other.csv', b'important,unrelated\nother,99\n')
        first = self.wait(record['id'])
        self.assertEqual(first['analysis']['disposition'], 'needs_reason')
        self.assertIn('relate', first['analysis']['question'])
        service.action(self.scope, record['id'], 'purpose', 'This belongs to another process.')
        final = self.wait(record['id'])
        # Await the new intent, not the old already-complete phase.
        end = time.monotonic() + 5
        while final['analysis'].get('intent_version') != 1 or final['analysis']['phase'] != 'complete':
            self.assertLess(time.monotonic(), end)
            time.sleep(.01)
            final = self.store.get(self.scope, record['id'])
        self.assertEqual(final['analysis']['disposition'], 'parked')
        self.assertEqual(final['analysis']['question'], '')
        self.assertIn('Thank you', final['analysis']['acknowledgement'])
        self.assertEqual(service.supporting_context(self.scope, 'important')['documents'], [])
        with self.assertRaises(ValueError):
            service.action(self.scope, record['id'], 'purpose', 'A second reason')

    def test_remove_during_provider_request_invalidates_late_result_and_keeps_original(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def analyze(context, record, chunks, phase):
            entered.set()
            release.wait(3)
            finished.set()
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'remove.csv', b'important,field\na,1\n')
        self.assertTrue(entered.wait(2))
        service.action(self.scope, record['id'], 'remove')
        release.set()
        self.assertTrue(finished.wait(2))
        time.sleep(.03)
        current = self.store.get(self.scope, record['id'])
        self.assertTrue(current['archived'])
        self.assertNotIn('summary', current.get('analysis') or {})
        self.assertTrue(self.store.original_path(self.scope, record['id']).exists())
        self.assertEqual(service.status(self.scope), [])

    def test_user_park_overrides_relevant_late_results_and_background_review_continues(self):
        entered, release = threading.Event(), threading.Event()
        count = 0
        def analyze(context, record, chunks, phase):
            nonlocal count
            count += 1
            if count == 1:
                entered.set()
                release.wait(3)
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'park.csv', b'important,field\na,1\n')
        self.assertTrue(entered.wait(2))
        service.action(self.scope, record['id'], 'park')
        release.set()
        result = self.wait(record['id'])
        self.assertEqual(result['analysis']['disposition'], 'parked')
        self.assertEqual(result['analysis']['question'], '')
        self.assertGreaterEqual(count, 2)
        self.assertEqual(service.supporting_context(self.scope, 'important')['documents'], [])

    def test_fabricated_citation_errors_once_and_only_revisit_retries(self):
        calls = []
        invalid = True
        def analyze(context, record, chunks, phase):
            calls.append(phase)
            value = response(chunks)
            if invalid:
                value['observations'][0]['sources'] = ['fabricated_document_source']
            return value
        service = self.service(analyze)
        record = service.upload(self.scope, 'cited.csv', b'important,field\na,1\n')
        self.wait(record['id'], 'error')
        for _ in range(4):
            service.status(self.scope, self.context)
        time.sleep(.03)
        self.assertEqual(len(calls), 1)
        invalid = False
        service.action(self.scope, record['id'], 'revisit')
        result = self.wait(record['id'])
        self.assertTrue(result['analysis']['review_complete'])
        self.assertGreater(len(calls), 1)

    def test_new_upload_quick_review_has_priority_over_deep_continuations_and_one_callback_at_a_time(self):
        deep_entered, release = threading.Event(), threading.Event()
        calls, active = [], 0
        lock = threading.Lock()
        def analyze(context, record, chunks, phase):
            nonlocal active
            with lock:
                active += 1
                self.assertEqual(active, 1)
                calls.append((record['name'], phase))
            if record['name'] == 'long.csv' and phase == 'deep' and not deep_entered.is_set():
                deep_entered.set()
                release.wait(3)
            with lock:
                active -= 1
            return response(chunks)
        service = self.service(analyze)
        content = ('important,value\n' + ''.join(f'row-{i},' + 'x' * 100 + '\n' for i in range(700))).encode()
        old = service.upload(self.scope, 'long.csv', content)
        self.assertTrue(deep_entered.wait(3))
        new = service.upload(self.scope, 'new.csv', b'important,new\na,2\n')
        release.set()
        self.wait(new['id'])
        self.wait(old['id'])
        old_first = calls.index(('long.csv', 'deep'))
        new_quick = calls.index(('new.csv', 'quick'))
        self.assertEqual(new_quick, old_first + 1)

    def test_status_resumes_ordered_deep_cursor_after_service_restart(self):
        record = self.store.add(self.scope, 'resume.csv', ('important,value\n' + ''.join(f'r{i},' + 'x' * 100 + '\n' for i in range(200))).encode())
        self.store.extract(self.scope, record['id'])
        expected = self.store.chunks(self.scope, record['id'], offset=1, limit=1)['chunks'][0]['id']
        self.store.update(self.scope, record['id'], {'analysis': {'phase': 'deep', 'cursor': 1, 'intent_version': 3,
                           'disposition': 'relevant', 'questions': [], 'observations': [], 'version': 2}})
        calls = []
        service = self.service(lambda context, record, chunks, phase: (calls.append((phase, chunks[0]['id'])) or response(chunks)))
        result = self.wait(record['id'])
        self.assertEqual(calls[0], ('deep', expected))
        self.assertEqual(result['analysis']['reviewed_chunks'], result['analysis']['total_chunks'])

    def test_close_returns_without_waiting_for_network_and_late_callback_cannot_publish(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def analyze(context, record, chunks, phase):
            entered.set()
            release.wait(3)
            finished.set()
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'close.csv', b'important,field\na,1\n')
        self.assertTrue(entered.wait(2))
        before = time.monotonic()
        service.close()
        self.assertLess(time.monotonic() - before, .1)
        release.set()
        self.assertTrue(finished.wait(2))
        time.sleep(.03)
        self.assertNotIn('summary', self.store.get(self.scope, record['id'])['analysis'])

    def test_question_limits_are_explicit_and_prevent_a_false_full_review_claim(self):
        def analyze(context, record, chunks, phase):
            value = response(chunks)
            value['questions'] = [{'text': f'Question {i}?', 'sources': [chunks[0]['id']]} for i in range(3)]
            return value
        service = self.service(analyze)
        with patch.object(service_module, 'MAX_QUESTIONS', 1):
            record = service.upload(self.scope, 'limits.csv', b'important,field\na,1\n')
            result = self.wait(record['id'])
        self.assertEqual(len(result['analysis']['questions']), 1)
        self.assertTrue(result['analysis']['limit_indicator'])
        self.assertFalse(result['analysis']['review_complete'])
        self.assertTrue(result['analysis']['limitations'])

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing pypdf runtime required')
    def test_native_visual_batches_are_single_source_and_every_page_becomes_searchable(self):
        from pypdf import PdfWriter
        import io
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=100, height=100)
        data = io.BytesIO()
        writer.write(data)
        calls = []
        def analyze(context, record, chunks, phase):
            visual = [chunk for chunk in chunks if chunk.get('requires_vision')]
            self.assertLessEqual(len(visual), 1)
            calls.append([chunk['id'] for chunk in chunks])
            value = response(chunks)
            if visual:
                value['extracted_text'] = 'NativePageNeedle' + str(visual[0]['page'])
            return value
        service = self.service(analyze)
        record = service.upload(self.scope, 'visual.pdf', data.getvalue())
        result = self.wait(record['id'])
        self.assertEqual(result['coverage']['indexed_units'], 3)
        self.assertEqual(result['analysis']['reviewed_chunks'], result['analysis']['total_chunks'])
        self.assertTrue(self.store.search(self.scope, 'NativePageNeedle3'))
        self.assertGreaterEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
