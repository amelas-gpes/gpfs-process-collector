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
from documents import DocumentStore, pdf_reader


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
            # close() has a bounded production shutdown deadline. A synthetic
            # callback may still be unwinding; do not remove its temporary
            # SQLite directory while that known worker handle is alive.
            service._worker.join(timeout=4)
            self.assertFalse(service._worker.is_alive())
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

    def test_observation_sources_and_generation_survive_the_background_review(self):
        stage = {"stage":"document", "model":"fixture", "prompt_id":"abc123", "reasoning_effort":"low"}
        def analyze(context, record, chunks, phase):
            result = response(chunks)
            result.update(generated_by=[stage], app_version="1.2.3")
            if chunks:
                result["observations"] += [
                    {"text":"The source names a tracker.", "sources":[chunks[0]["id"]], "basis":"stated", "quote":"tracker"},
                    {"text":"An invented observation.", "sources":[chunks[0]["id"]], "basis":"stated", "quote":"this is absent"}]
            return result
        service = self.service(analyze)
        record = service.upload(self.scope, "intake.csv", b"tracker,field\nalpha,42\n")
        analysis = self.wait(record["id"])["analysis"]
        self.assertEqual(analysis["generated_by"], [stage])
        self.assertEqual(analysis["app_version"], "1.2.3")
        by_text = {row["text"]:row for row in analysis["observations"]}
        self.assertEqual(by_text["The source names a tracker."]["quote"], "tracker")
        self.assertNotIn("basis", by_text["The document describes intake fields."])
        self.assertNotIn("An invented observation.", by_text)

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
        self.assertEqual(len(calls), 1, 'A complete quick sample is reviewed once.')
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
        records = [service.upload(self.scope, f'reference{i}.csv', f'header,value\na,{i}\n'.encode()) for i in range(7)]
        for record in records:
            self.wait(record['id'], timeout=20)
        support = service.supporting_context(self.scope, 'AnotherCompletelyMissingTerm')
        self.assertEqual(len(support['documents']), 6)
        self.assertEqual(support['omitted_documents'], 1)
        self.assertEqual({item['id'] for item in support['source_versions']}, {record['id'] for record in records})
        versions = {item['id']: item['source_revision'] for item in support['source_versions']}
        for document in support['documents']:
            self.assertEqual(document['source_revision'], versions[document['id']])
            self.assertEqual(len(document['summary']), 700)
            self.assertTrue(document['summary_excerpt'])
            self.assertEqual(len(document['questions']), 2)
            self.assertTrue(document['excerpts'])
            self.assertTrue(document['context_coverage']['complete_text'])
        service.action(self.scope, records[0]['id'], 'park')
        parked_context = service.supporting_context(self.scope, 'AnotherCompletelyMissingTerm')
        self.assertNotIn(records[0]['id'], [item['id'] for item in parked_context['documents']])
        self.assertNotIn(records[0]['id'], [item['id'] for item in parked_context['source_versions']])

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

    def test_deep_review_does_not_overwrite_quick_relevance_or_direction(self):
        def analyze(context, record, chunks, phase):
            initial = 'unrelated' if record['name'].startswith('unrelated') else 'relevant'
            relevance = initial if phase == 'quick' else ('relevant' if initial == 'unrelated' else 'unrelated')
            value = response(chunks, relevance)
            value['relevance_reason'] = f'{phase} assessment'
            value['summary'] = 'Whole process identity and scope.' if phase == 'quick' else 'The final appendix only.'
            value['queries'] = ['process identity'] if phase == 'quick' else ['final appendix']
            return value
        service = self.service(analyze)
        unrelated = service.upload(self.scope, 'unrelated.csv', b'important,value\na,42\n')
        relevant = service.upload(self.scope, 'relevant.csv', b'important,value\nb,99\n')
        unrelated_result = self.wait(unrelated['id'])['analysis']
        relevant_result = self.wait(relevant['id'])['analysis']
        self.assertEqual((unrelated_result['relevance'], unrelated_result['relevance_reason'], unrelated_result['disposition']),
                         ('unrelated', 'quick assessment', 'needs_reason'))
        self.assertEqual((relevant_result['relevance'], relevant_result['relevance_reason'], relevant_result['disposition']),
                         ('relevant', 'quick assessment', 'relevant'))
        self.assertEqual(relevant_result['summary'], 'Whole process identity and scope.')
        self.assertEqual(relevant_result['summary_basis'], 'initial_review')
        self.assertEqual(relevant_result['summary_at_review_version'], 1)
        self.assertGreaterEqual(relevant_result['version'], relevant_result['summary_at_review_version'])
        self.assertEqual(relevant_result['summary_basis_note'], service_module.INITIAL_SUMMARY_NOTE)
        self.assertEqual(relevant_result['queries'], ['process identity'])
        available = {item['id']: item for item in service.supporting_context(self.scope, 'important')['documents']}
        self.assertEqual(set(available), {relevant['id']})
        self.assertEqual(available[relevant['id']]['summary_basis'], 'initial_review')
        self.assertEqual(available[relevant['id']]['summary_at_review_version'], 1)
        self.assertEqual(available[relevant['id']]['summary_basis_note'], service_module.INITIAL_SUMMARY_NOTE)
        self.assertTrue(available[relevant['id']]['review']['review_complete'])

    def test_older_summary_gets_historical_basis_without_database_write_or_provider_call(self):
        record = self.store.add(self.scope, 'old-overview.csv', b'name,value\nfictional,42\n', self.context)
        record = self.store.extract(self.scope, record['id'])
        old_analysis = {'summary': 'Graphics were not reviewed in this initial selection.',
                        'phase': 'complete', 'review_complete': True, 'version': 8,
                        'disposition': 'relevant'}
        self.store.update(self.scope, record['id'], {'analysis': old_analysis})
        with self.store._db() as db:
            before = db.execute('SELECT record FROM documents WHERE id=?', (record['id'],)).fetchone()[0]
        service = self.service(lambda *args: self.fail('Metadata projection cannot call a provider.'))
        public = service.status(self.scope)[0]['analysis']
        self.assertEqual(public['summary'], old_analysis['summary'])
        self.assertEqual(public['summary_basis'], 'initial_review')
        self.assertIsNone(public['summary_at_review_version'])
        support = service.supporting_context(self.scope, 'fictional')['documents'][0]
        self.assertEqual(support['summary_basis_note'], service_module.INITIAL_SUMMARY_NOTE)
        self.assertTrue(support['review']['review_complete'])
        with self.store._db() as db:
            after = db.execute('SELECT record FROM documents WHERE id=?', (record['id'],)).fetchone()[0]
        self.assertEqual(before, after)

    def test_initial_document_text_is_available_before_model_review_without_repeating_intake(self):
        service = self.service(lambda *args: self.fail('Supporting context must not require a provider request.'))
        # A complete modest procedure exceeds the old 18k excerpt budget. Its
        # final instruction is as important to the process as its opening.
        data = ('step,description\n' + ''.join(f'{i},Documented handling detail ' + 'x' * 90 + '\n' for i in range(250))
                + 'final,Release requires two authorized reviewers and record retention.\n').encode()
        record = self.store.add(self.scope, 'procedure.csv', data, self.context)
        indexed = self.store.extract(self.scope, record['id'])
        self.assertEqual(indexed['analysis'], {})
        support = service.supporting_context(self.scope, 'Everything is already in the attached file')
        document = support['documents'][0]
        self.assertEqual(document['disposition'], 'awaiting_review')
        self.assertEqual(document['name'], 'procedure.csv')
        self.assertFalse(document['review']['review_complete'])
        self.assertTrue(document['context_coverage']['complete_text'])
        self.assertGreater(support['context_budget']['characters'], 18000)
        self.assertIn('Release requires two authorized reviewers', '\n'.join(chunk['text'] for chunk in document['excerpts']))
        self.assertEqual(document['excerpts'], self.store.chunks(self.scope, record['id'])['chunks'])
        self.assertIn('Do not ask the participant to repeat', support['notice'])

    def test_large_document_retains_exact_prior_sources_and_exposes_partial_coverage(self):
        service = self.service(lambda *args: self.fail('Context retrieval must not call the provider.'))
        data = ('step,description\n' + ''.join(f'{i},common handling detail ' + 'x' * 200 + '\n' for i in range(1000))).encode()
        record = self.store.add(self.scope, 'large.csv', data, self.context)
        self.store.extract(self.scope, record['id'])
        chunks = self.store.chunks(self.scope, record['id'])['chunks']
        first = service.supporting_context(self.scope, 'common')['documents'][0]
        included = {chunk['id'] for chunk in first['excerpts']}
        previous = next(chunk for chunk in reversed(chunks) if chunk['id'] not in included)
        other_scope = self.store.create_scope()
        foreign = self.store.add(other_scope, 'foreign.csv', b'field,value\nprivate,other interview\n', {})
        self.store.extract(other_scope, foreign['id'])
        foreign_source = self.store.chunks(other_scope, foreign['id'])['chunks'][0]
        second = chunks[0]
        requested = [previous['id'], foreign_source['id'], second['id'], previous['id'], record['id'] + '_missing']
        with patch.object(self.store, '_db', wraps=self.store._db) as connections:
            support = service.supporting_context(self.scope, 'common', source_ids=requested)
        self.assertEqual(connections.call_count, 1)
        document = support['documents'][0]
        self.assertEqual(document['excerpts'][:2], [previous, second])
        self.assertEqual(sum(chunk['id'] == previous['id'] for chunk in document['excerpts']), 1)
        self.assertFalse(document['context_coverage']['complete_text'])
        self.assertEqual(document['context_coverage']['selection'], 'selected excerpts')
        self.assertLess(document['context_coverage']['included_chunks'], document['context_coverage']['total_chunks'])
        self.assertLessEqual(support['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS)
        self.assertNotIn(foreign_source['id'], json.dumps(support))
        with self.store.interview_reader(self.scope) as reader:
            self.store.archive(self.scope, record['id'])
            self.assertEqual(reader.prior_sources(requested), [previous, second])
            self.assertTrue(reader.search('common', [record['id']], 1))
        removed = service.supporting_context(self.scope, 'common', source_ids=[previous['id'], foreign_source['id']])
        self.assertEqual(removed['documents'], [])
        self.assertEqual(removed['source_versions'], [])
        self.assertEqual(len(removed['retained_evidence']), 1)
        self.assertEqual(removed['retained_evidence'][0], {**previous, 'retained_only': True,
                                                         'archived': True, 'disposition': 'awaiting_review',
                                                         'extraction_version': self.store.get(self.scope, record['id'])['extraction_version'],
                                                         'extraction_needs_reindex': False})
        self.assertEqual(service.supporting_context(self.scope, 'common')['retained_evidence'], [])
        with self.assertRaises(PermissionError):
            service.source(self.scope, record['id'], previous['id'])

    def test_pending_and_failed_files_are_visible_without_claiming_they_have_been_read(self):
        service = self.service(lambda *args: self.fail('Context retrieval must not call the provider.'))
        pending = self.store.add(self.scope, 'waiting.csv', b'field,value\na,1\n', {})
        failed = self.store.add(self.scope, 'failed.csv', b'field,value\na,1\n', {})
        self.store.update(self.scope, failed['id'], {'status': 'error', 'error': 'Unable to decode.'})
        support = service.supporting_context(self.scope, 'the file has everything')
        self.assertEqual(support['documents'], [])
        self.assertEqual(support['source_versions'], [])
        for item in support['pending_documents']:
            self.assertRegex(item['source_revision'], r'^[a-f0-9]{64}$')
        self.assertEqual({item['id']: item['status'] for item in support['pending_documents']},
                         {pending['id']: 'pending', failed['id']: 'error'})

    def test_source_revision_ignores_query_selection_and_review_progress(self):
        service = self.service(lambda *args: self.fail('Source metadata must not call the provider.'))
        rows = ''.join(f'{i},{"EarlyNeedle" if i < 100 else "LateNeedle" if i > 900 else "Middle"} ' + 'x' * 200 + '\n' for i in range(1000))
        record = self.store.add(self.scope, 'large-revision.csv', ('step,detail\n' + rows).encode(), self.context)
        self.store.extract(self.scope, record['id'])
        first = service.supporting_context(self.scope, 'EarlyNeedle')['documents'][0]
        second = service.supporting_context(self.scope, 'LateNeedle')['documents'][0]
        self.assertNotEqual([c['id'] for c in first['excerpts']], [c['id'] for c in second['excerpts']])
        self.assertEqual(first['source_revision'], second['source_revision'])
        self.assertRegex(first['source_revision'], r'^[a-f0-9]{64}$')
        self.store.update(self.scope, record['id'], {'analysis': {'phase': 'complete', 'version': 500,
                          'cursor': 500, 'summary': 'Changed progress overview', 'review_complete': True,
                          'reviewed_chunks': 500, 'disposition': 'relevant'}})
        for _ in range(3):
            service.status(self.scope)
        third = service.supporting_context(self.scope, 'NeverMatches')['documents'][0]
        self.assertEqual(first['source_revision'], third['source_revision'])
        self.assertNotIn(self.scope, first['source_revision'])

    def test_source_revision_changes_for_explicit_purpose_and_revisit(self):
        service = self.service(lambda context, record, chunks, phase: response(chunks))
        record = service.upload(self.scope, 'intent-revision.csv', b'important,value\nFictional,42\n')
        self.wait(record['id'])
        original = service.supporting_context(self.scope, 'important')['documents'][0]['source_revision']
        service.action(self.scope, record['id'], 'purpose', 'Use this for the fictional receiving step.')
        purpose_revision = service.supporting_context(self.scope, 'important')['documents'][0]['source_revision']
        self.assertNotEqual(original, purpose_revision)
        self.wait(record['id'])
        self.assertEqual(purpose_revision, service.supporting_context(self.scope, 'different query')['documents'][0]['source_revision'])
        service.action(self.scope, record['id'], 'revisit')
        revisited = service.supporting_context(self.scope, 'important')['documents'][0]['source_revision']
        self.assertNotEqual(purpose_revision, revisited)
        self.wait(record['id'])
        self.assertEqual(revisited, service.supporting_context(self.scope, '')['documents'][0]['source_revision'])

    def test_remove_during_provider_request_invalidates_late_result_and_keeps_original(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def analyze(context, record, chunks, phase):
            entered.set()
            self.addCleanup(release.set)
            release.wait()
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
        count, phases = 0, []
        def analyze(context, record, chunks, phase):
            nonlocal count
            count += 1
            phases.append((record['analysis']['intent_version'], phase))
            if count == 1:
                entered.set()
                self.addCleanup(release.set)
                release.wait()
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'park.csv', b'important,field\na,1\n')
        self.assertTrue(entered.wait(2))
        parked = service.action(self.scope, record['id'], 'park')
        self.assertEqual(parked['analysis']['phase'], 'complete')
        for _ in range(3):
            service.status(self.scope)
        release.set()
        result = self.wait(record['id'])
        self.assertEqual(result['analysis']['disposition'], 'parked')
        self.assertEqual(result['analysis']['question'], '')
        self.assertEqual(count, 1)
        self.assertNotIn((1, 'quick'), phases, 'Polling a parked deep review must not queue another quick assessment')
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

    def test_parking_failed_reviews_waits_for_explicit_revisit(self):
        calls = []
        def analyze(context, record, chunks, phase):
            calls.append(phase)
            if len(calls) == 1:
                raise RuntimeError('Synthetic provider interruption')
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'park-after-error.csv', b'item,value\na,1\n')
        self.wait(record['id'], 'error')
        parked = service.action(self.scope, record['id'], 'park')
        self.assertEqual(parked['analysis']['phase'], 'error')
        self.assertEqual(parked['analysis']['disposition'], 'parked')
        self.assertFalse(parked['analysis']['review_complete'])
        self.assertEqual(service.status(self.scope)[0]['analysis']['phase'], 'error')
        self.assertEqual(service.supporting_context(self.scope, 'item')['documents'], [])
        self.assertEqual(calls, ['quick'])
        service.action(self.scope, record['id'], 'revisit')
        self.assertTrue(self.wait(record['id'])['analysis']['review_complete'])
        self.assertEqual(calls, ['quick', 'quick'])

    def test_parking_a_failed_extraction_preserves_its_original_and_error(self):
        record = self.store.add(self.scope, 'broken.csv', b'"unfinished')
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'error')
        service = self.service(lambda *args: self.fail('No readable sections to review'))
        parked = service.action(self.scope, record['id'], 'park')
        self.assertEqual(parked['analysis']['phase'], 'error')
        self.assertEqual(parked['error'], result['error'])
        self.assertEqual(parked['analysis']['disposition'], 'parked')
        self.assertEqual(self.store.original_bytes(self.scope, record['id']), b'"unfinished')

    def test_error_reporting_storage_failure_does_not_kill_worker_or_poll_retry(self):
        calls, invalid = [], True
        def analyze(context, record, chunks, phase):
            calls.append(record['name'])
            value = response(chunks)
            if record['name'] == 'first.csv' and invalid:
                value['observations'][0]['sources'] = ['invalid-source']
            return value
        service = self.service(analyze)
        original_update = self.store.update
        def fail_error_write(scope, identity, changes):
            if (changes.get('analysis') or {}).get('phase') == 'error':
                raise OSError('Synthetic storage failure while recording an error')
            return original_update(scope, identity, changes)
        with patch.object(self.store, 'update', side_effect=fail_error_write):
            first = service.upload(self.scope, 'first.csv', b'important,field\na,1\n')
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if service.status(self.scope)[0]['analysis'].get('phase') == 'error':
                    break
                threading.Event().wait(.01)
            else:
                self.fail('The failed write did not surface a paused review')
            self.assertTrue(service._worker.is_alive())
            for _ in range(3):
                service.status(self.scope)
            second = service.upload(self.scope, 'second.csv', b'important,field\nb,2\n')
            self.wait(second['id'])
            self.assertEqual(calls.count('first.csv'), 1, 'Polling must not retry an unpersisted failure')
        invalid = False
        service.action(self.scope, first['id'], 'revisit')
        self.assertTrue(self.wait(first['id'])['analysis']['review_complete'])

    def test_new_upload_quick_review_has_priority_over_deep_continuations_and_one_callback_at_a_time(self):
        deep_entered, release = threading.Event(), threading.Event()
        calls, active = [], 0
        lock = threading.Lock()
        def analyze(context, record, chunks, phase):
            nonlocal active
            with lock:
                active += 1
                calls.append((record['name'], phase))
            if record['name'] == 'long.csv' and phase == 'deep' and not deep_entered.is_set():
                deep_entered.set()
                self.addCleanup(release.set)
                release.wait()
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
        # The new file's first pass comes right after the in-depth wave that was in flight,
        # before any later wave of the old file.
        between = calls[old_first:new_quick]
        self.assertTrue(set(between) == {('long.csv', 'deep')} and len(between) <= service_module.MAX_DEEP_WAVE, between)

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

    def test_explicit_revisit_restarts_full_reading_instead_of_reusing_old_end_cursor(self):
        calls = []
        def analyze(context, record, chunks, phase):
            calls.append((record['analysis']['intent_version'], phase, chunks[0]['id']))
            return response(chunks)
        service = self.service(analyze)
        content = ('important,value\n' + ''.join(f'r{i},' + 'x' * 100 + '\n' for i in range(200))).encode()
        record = service.upload(self.scope, 'reread.csv', content)
        original = self.wait(record['id'])
        self.assertGreater(original['analysis']['cursor'], 1)
        first_source = self.store.chunks(self.scope, record['id'], limit=1)['chunks'][0]['id']
        revised = service.action(self.scope, record['id'], 'revisit')
        self.assertEqual(revised['analysis']['cursor'], 0)
        self.assertFalse(revised['analysis']['review_complete'])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = self.store.get(self.scope, record['id'])['analysis']
            if current.get('intent_version') == 1 and current.get('phase') == 'complete':
                break
            threading.Event().wait(.01)
        self.assertTrue(current['review_complete'])
        self.assertIn((1, 'quick', first_source), calls)

    def test_delayed_status_poll_does_not_repeat_a_completed_quick_review(self):
        entered, release, read_snapshot, resume_poll = [threading.Event() for _ in range(4)]
        calls = []
        def analyze(context, record, chunks, phase):
            calls.append(phase)
            if len(calls) == 1:
                entered.set()
                self.addCleanup(release.set)
                release.wait()
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'poll-race.csv', b'important,field\na,1\n')
        self.assertTrue(entered.wait(2))
        original_list = self.store.list
        def delayed_list(scope, *args, **kwargs):
            records = original_list(scope, *args, **kwargs)
            if threading.current_thread().name == 'delayed-poll':
                read_snapshot.set()
                resume_poll.wait(3)
            return records
        with patch.object(self.store, 'list', side_effect=delayed_list):
            poll = threading.Thread(target=service.status, args=(self.scope,), name='delayed-poll')
            poll.start()
            self.assertTrue(read_snapshot.wait(2))
            release.set()
            # With the regression, the worker can finish while status retains
            # stale quick metadata outside the orchestration lock. With the fix
            # it waits until this poll has scheduled its consistent snapshot.
            deadline = time.monotonic() + .2
            while time.monotonic() < deadline:
                if self.store.get(self.scope, record['id'])['analysis'].get('phase') == 'complete':
                    break
                threading.Event().wait(.005)
            resume_poll.set()
            poll.join(2)
            self.assertFalse(poll.is_alive())
        self.wait(record['id'])
        threading.Event().wait(.03)
        self.assertEqual(calls.count('quick'), 1)

    def test_repeated_intent_changes_discard_superseded_queued_work(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def analyze(context, record, chunks, phase):
            calls.append(record['analysis']['intent_version'])
            if len(calls) == 1:
                entered.set()
                self.addCleanup(release.set)
                release.wait()
            return response(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'intent-queue.csv', b'important,field\na,1\n')
        self.assertTrue(entered.wait(2))
        for _ in range(20):
            service.action(self.scope, record['id'], 'park')
            service.action(self.scope, record['id'], 'revisit')
        with service._condition:
            self.assertLessEqual(len(service._queued), 1)
            self.assertLessEqual(len(service._urgent) + len(service._deep), 1)
            self.assertEqual(next(iter(service._queued))[2], 40)
        release.set()
        final = self.wait(record['id'])
        self.assertEqual(final['analysis']['intent_version'], 40)
        self.assertEqual(set(calls), {0, 40}, 'Superseded intents must never reach the analyzer')

    def test_close_returns_without_waiting_for_network_and_late_callback_cannot_publish(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def analyze(context, record, chunks, phase):
            entered.set()
            self.addCleanup(release.set)
            release.wait()
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

    def test_close_during_batch_preparation_does_not_start_analysis_afterward(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        service = self.service(lambda *args: calls.append(args))
        original = service._quick_chunks
        def prepare(*args):
            chunks = original(*args)
            entered.set()
            self.addCleanup(release.set)
            release.wait()
            return chunks
        with patch.object(service, '_quick_chunks', side_effect=prepare):
            record = service.upload(self.scope, 'stop-before-dispatch.csv', b'important,field\na,1\n')
            self.assertTrue(entered.wait(2))
            service.close()
            release.set()
            service._worker.join(2)
            self.assertFalse(service._worker.is_alive())
        self.assertEqual(calls, [])
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

    def test_empty_readable_content_is_acknowledged_without_a_full_review_claim(self):
        def analyze(*args):
            self.fail('A file without source sections must not invoke an analyzer')
        service = self.service(analyze)
        record = service.upload(self.scope, 'empty.csv', b'\n')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            saved = self.store.get(self.scope,record['id'])
            if saved['status'] == 'error': break
            threading.Event().wait(.02)
        self.assertEqual(saved['error_code'], 'invalid_file')
        self.assertIn('no populated cells', saved['error'])
        self.assertFalse(saved.get('analysis',{}).get('review_complete'))

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'Existing openpyxl runtime required')
    def test_unread_chart_tab_prevents_a_full_document_review_claim(self):
        import io
        from openpyxl import Workbook
        from openpyxl.chart import BarChart
        book = Workbook()
        book.active.append(['important', 'value'])
        book.active.append(['sample', 42])
        chart = book.create_chartsheet('Visual diagram')
        chart.add_chart(BarChart())
        output = io.BytesIO()
        book.save(output)
        service = self.service(lambda context, record, chunks, phase: response(chunks))
        record = service.upload(self.scope, 'mixed-chart.xlsx', output.getvalue())
        result = self.wait(record['id'])
        self.assertEqual(result['coverage']['indexed_units'], 1)
        self.assertEqual(result['coverage']['total_units'], 2)
        self.assertTrue(result['analysis']['reviewed_chunks'])
        self.assertFalse(result['analysis']['review_complete'], 'Reviewing available text must not claim the unread chart tab was reviewed')

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing pypdf runtime required')
    def test_empty_visual_result_is_recorded_for_that_page_without_read_credit_or_poll_retry(self):
        # Changed with document-service-1: this test pinned a pause of the whole review at the
        # page whose reading came back empty. The page is now recorded as unread and the
        # review ends; it is still not counted as read, and polling still pays for nothing.
        import io
        PdfWriter = pdf_reader().PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        data = io.BytesIO()
        writer.write(data)
        record = self.store.add(self.scope, 'fictional-two-page.pdf', data.getvalue())
        calls = []
        fail_visual = {'enabled': True}
        def analyze(context, current, chunks, phase):
            calls.append((phase, [c['id'] for c in chunks]))
            value = response(chunks)
            visual = next((c for c in chunks if c.get('requires_vision')), None)
            if visual:
                if phase == 'deep' and fail_visual['enabled']:
                    value['observations'] = [{'text': 'Must not merge failed visual claim', 'sources': [visual['id']]}]
                else:
                    value['extracted_text'] = 'Synthetic description: this fictional page is blank.'
            return value
        manager = self.service(analyze)
        ended = self.wait(record['id'])
        self.assertEqual(len(calls), 2)
        self.assertFalse(ended['analysis']['review_complete'])
        self.assertIsNone(ended['analysis']['error'])
        unread = 'Visual review could not read 1 page or image (page 2); it is not counted as read.'
        self.assertIn(unread, ended['analysis']['limitations'])
        self.assertEqual(ended['analysis']['reviewed_chunks'], ended['analysis']['total_chunks'])
        self.assertNotIn('Must not merge failed visual claim', json.dumps(ended['analysis']))
        self.assertEqual(ended['coverage']['indexed_units'], 1)
        for _ in range(4):
            manager.status(self.scope)
        threading.Event().wait(.03)
        self.assertEqual(len(calls), 2, 'Polling never pays for an incomplete visual response again')
        fail_visual['enabled'] = False
        manager.action(self.scope, record['id'], 'revisit')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            completed = self.store.get(self.scope, record['id'])
            if completed['analysis'].get('intent_version') == 1 and completed['analysis'].get('phase') == 'complete':
                break
            threading.Event().wait(.01)
        self.assertEqual(len(calls), 4)
        self.assertTrue(completed['analysis']['review_complete'])
        self.assertFalse(completed['analysis']['retry_required'])
        self.assertNotIn(unread, completed['analysis']['limitations'])
        self.assertEqual(completed['coverage']['indexed_units'], 2)
        self.assertEqual(self.store.original_path(self.scope, record['id']).read_bytes(), data.getvalue())

    def test_native_visual_batches_are_single_source_and_every_page_becomes_searchable(self):
        PdfWriter = pdf_reader().PdfWriter
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
