"""How the background file review ends, pauses, resumes and is steered.

Real DocumentStore and DocumentService on a temporary SQLite store with a
scripted review callback; the provider client's own error classification is
exercised with its transport replaced. No provider or network access.
"""
import errno
import io
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

from test_reindex_transcriptions import HAS_PDF, pdf_bytes, png_bytes
from test_server import server

service_module = server.local_module('document_service', 'document_service.py')
documents = server.documents


def answer(chunks, relevance='relevant', notes=()):
    """A valid review reply. notes: texts of observations, each cited to the first supplied section."""
    return {'summary': 'A synthetic document account.', 'acknowledgement': 'Reviewed.', 'relevance': relevance,
            'relevance_reason': f'The synthetic reviewer judged this file {relevance}.',
            'question': 'Which of these fields do you use?' if relevance == 'relevant' else '',
            'queries': [], 'observations': [{'text': text, 'sources': [chunks[0]['id']]} for text in notes],
            'questions': [], 'extracted_text': ''}


def ledger(rows, size=5200):
    """A CSV whose rows are each one indexed section; four of them fill one in-depth request."""
    lines = ['row,detail']
    for index in range(rows):
        body = f'entry{index} ledger line {index} '
        lines.append(f'{index},' + (body * (size // len(body) + 1))[:size])
    return ('\n'.join(lines) + '\n').encode()


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='collector-review-outcomes-')
        self.store = documents.DocumentStore(Path(self.temp.name) / 'documents')
        self.scope = self.store.create_scope()
        self.services = []
        # create=True: on code without the setting each test then fails on its own assertion.
        waits = patch.object(service_module, 'RETRY_DELAYS', (.01, .01), create=True)
        waits.start()
        self.addCleanup(waits.stop)

    def tearDown(self):
        for service in self.services:
            service.close()
            service._worker.join(timeout=5)
            self.assertFalse(service._worker.is_alive())
        self.temp.cleanup()

    def service(self, callback):
        instance = service_module.DocumentService(self.store, callback)
        self.services.append(instance)
        instance.session(self.scope, {'process_name': 'Synthetic intake'})
        return instance

    def wait(self, identity, phase='complete', intent=None, timeout=90):
        # A generous limit: other suites run beside this one and a wait that succeeds costs nothing.
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            record = self.store.get(self.scope, identity)
            analysis = record.get('analysis') or {}
            if (record['status'] not in ('pending', 'indexing') and analysis.get('phase') == phase
                    and (intent is None or analysis.get('intent_version') == intent)):
                return record
            threading.Event().wait(.01)
        self.fail(f'Review did not reach {phase}: {self.store.get(self.scope, identity).get("analysis")}')

    def quiet(self, service, calls):
        """Polling must not start anything: the number of review requests stays as it is."""
        before = len(calls)
        for _ in range(4):
            service.status(self.scope)
        threading.Event().wait(.05)
        self.assertEqual(len(calls), before, 'A status poll started a review request')


class PausedReviewWordingTests(ReviewCase):
    """live-documents-8: a paused review names the kind of problem and the button that is on screen."""

    def paused(self, errors):
        def analyze(context, record, chunks, phase):
            raise errors[record['name']]
        service = self.service(analyze)
        records = {name: service.upload(self.scope, name, f'important,field\n{name},1\n'.encode()) for name in errors}
        return {name: self.wait(record['id'], 'error') for name, record in records.items()}

    def test_each_provider_problem_the_client_recognises_gets_its_own_fixed_sentence(self):
        expected = {'quota': 'no available API quota', 'authentication': 'rejected the API key', 'permissions': 'rejected the API key',
                    'rate_limit': 'rate limit was reached', 'model_access': 'model is unavailable', 'timeout': 'timed out',
                    'dns': 'could not be reached', 'tls': 'could not be reached', 'connection': 'could not be reached',
                    'network': 'could not be reached', 'configuration': 'no usable API key'}
        errors = {f'{category}.csv': server.APIError('PRIVATE-ROW 4411 of the ledger', 502, category) for category in expected}
        for name, record in self.paused(errors).items():
            category = name[:-4]
            with self.subTest(category=category):
                analysis = record['analysis']
                self.assertEqual(analysis['error'], service_module.REVIEW_PAUSED_BY_CATEGORY[category])
                self.assertIn(expected[category], analysis['error'])
                self.assertTrue(analysis['error'].startswith('Document review paused: '))
                self.assertIn('Retry review', analysis['error'], 'The message must name the button shown in this state')
                self.assertNotIn('Revisit', analysis['error'])
                self.assertEqual(analysis['retry_reason'], analysis['error'])
                self.assertIn(analysis['error'], analysis['limitations'])
                self.assertTrue(analysis['retry_required'])
                self.assertNotIn('PRIVATE-ROW', json.dumps(record), 'The exception text is never shown')

    def test_anything_else_keeps_the_generic_sentence_and_no_exception_text(self):
        class Labelled(Exception):
            def __init__(self, category):
                super().__init__('PRIVATE-ROW 4411 of the ledger')
                self.category = category
        errors = {'plain.csv': RuntimeError('PRIVATE-ROW 4411 of the ledger'),
                  'uncategorised.csv': server.APIError('PRIVATE-ROW 4411 of the ledger'),
                  'other-http.csv': server.APIError('PRIVATE-ROW 4411 of the ledger', 502, 'http_error'),
                  'unknown.csv': server.APIError('PRIVATE-ROW 4411 of the ledger', 502, 'PRIVATE-ROW 4411'),
                  'not-text.csv': Labelled({'quota': True}), 'number.csv': Labelled(5),
                  'parser.csv': documents.DocumentError('PRIVATE-ROW 4411 of the ledger')}
        for name, record in self.paused(errors).items():
            with self.subTest(error=name):
                self.assertEqual(record['analysis']['error'],
                                 'Document review paused after an invalid response or service error. Select Retry review to try again.')
                self.assertNotIn('PRIVATE-ROW', json.dumps(record))

    def test_the_provider_client_labels_its_own_failures(self):
        def http(code, details=None):
            return urllib.error.HTTPError('https://api.openai.com/v1/responses', code, 'Synthetic', {},
                                          io.BytesIO(json.dumps({'error': details or {}}).encode()))
        cases = [(http(429), 'rate_limit', True),
                 (http(429, {'code': 'insufficient_quota', 'type': 'insufficient_quota'}), 'quota', False),
                 (http(401), 'authentication', False), (http(403), 'permissions', False),
                 (http(404, {'code': 'model_not_found'}), 'model_access', False),
                 (http(400), 'invalid_configuration', False), (http(500), 'http_error', True), (http(503), 'provider_unavailable', True),
                 (http(503, {'code': 'server_is_overloaded', 'type': 'service_unavailable_error'}), 'provider_unavailable', True),
                 (urllib.error.URLError(TimeoutError('PRIVATE')), 'timeout', True),
                 (urllib.error.URLError(OSError(errno.ETIMEDOUT, 'PRIVATE')), 'timeout', True),
                 (urllib.error.URLError(socket.gaierror(-2, 'PRIVATE')), 'dns', False),
                 (urllib.error.URLError(ssl.SSLCertVerificationError(1, 'PRIVATE')), 'tls', False),
                 (ConnectionResetError('PRIVATE'), 'connection', False), (OSError('PRIVATE'), 'network', False)]
        for failure, category, transient in cases:
            with self.subTest(category=category, failure=getattr(failure, 'code', type(failure).__name__)):
                client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-test-sentinel-not-a-real-credential'})
                with patch.object(server.openai_transport, 'urlopen', side_effect=failure):
                    with self.assertRaises(server.APIError) as caught:
                        client.request('responses', {'model': 'synthetic-test'})
                self.assertEqual((caught.exception.category, caught.exception.transient), (category, transient))
        for settings in ({}, {'OPENAI_API_KEY': 'sk-bad key with spaces'}):
            with self.assertRaises(server.APIError) as caught:
                server.OpenAIClient(settings).request('responses', {})
            self.assertEqual((caught.exception.category, caught.exception.transient), ('configuration', False))
        plain = server.APIError('The model declined this request.')
        self.assertEqual((plain.status, plain.category, plain.transient), (502, None, False))

    def test_local_token_budget_reaches_the_file_card_without_contacting_the_provider(self):
        client = server.OpenAIClient({'OPENAI_API_KEY': 'test-key', 'DAILY_TOKEN_CAP': '1'})
        with patch.object(server.openai_transport, 'urlopen') as transport:
            service = self.service(lambda context, record, chunks, phase:
                                   client.analyze_document(context, record, chunks, phase, self.store))
            record = service.upload(self.scope, 'cited.csv', b'important,field\na,1\n')
            paused = self.wait(record['id'], 'error')
        transport.assert_not_called()
        self.assertIn('local token budget', paused['analysis']['error'])
        self.assertEqual(paused['analysis']['retry_reason'], paused['analysis']['error'])
        self.assertTrue(paused['analysis']['retry_required'])

    def test_a_rejected_key_reaches_the_file_card_through_the_real_request_path(self):
        client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-test-sentinel-not-a-real-credential'})
        rejected = urllib.error.HTTPError('https://api.openai.com/v1/responses', 401, 'Unauthorized', {},
                                          io.BytesIO(b'{"error": {"message": "PRIVATE provider wording"}}'))
        with patch.object(server.openai_transport, 'urlopen', side_effect=rejected):
            service = self.service(lambda context, record, chunks, phase: client.analyze_document(context, record, chunks, phase, self.store))
            record = service.upload(self.scope, 'cited.csv', b'important,field\na,1\n')
            paused = self.wait(record['id'], 'error')
        self.assertEqual(paused['analysis']['error'], service_module.REVIEW_PAUSED_BY_CATEGORY['authentication'])
        self.assertNotIn('PRIVATE', json.dumps(paused))


class UnreadablePageTests(ReviewCase):
    """document-service-1: an empty transcription is an outcome for one page, not a failed review."""

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_one_page_that_never_yields_a_reading_does_not_keep_the_later_pages_from_being_read(self):
        record = self.store.add(self.scope, 'scan.pdf', pdf_bytes(['blank'] * 8))
        unreadable, requested, calls = {4, 6}, [], []

        def analyze(context, current, chunks, phase):
            calls.append(phase)
            reply = answer(chunks)
            visual = next((chunk for chunk in chunks if chunk.get('requires_vision')), None)
            if visual:
                requested.append(visual['page'])
                if visual['page'] in unreadable:
                    # The prompt's own instruction for unreadable content: no transcription, explain in the summary.
                    reply['summary'] = f'Page {visual["page"]} is too faint to read.'
                    reply['observations'] = [{'text': 'Claim about the unread page.', 'sources': [visual['id']]}]
                else:
                    reply['extracted_text'] = f'ScanNeedle{visual["page"]} approvals above 500 need a second signer.'
            return reply
        service = self.service(analyze)
        done = self.wait(record['id'])
        analysis = done['analysis']
        self.assertEqual(sorted(requested), list(range(1, 9)), 'Every page was sent for a reading exactly once')
        self.assertEqual((analysis['cursor'], analysis['reviewed_chunks'], analysis['total_chunks']), (8, 8, 8))
        self.assertIsNone(analysis['error'])
        self.assertFalse(analysis.get('retry_required'))
        self.assertFalse(analysis['review_complete'], 'Two pages are unread: the file is not fully reviewed')
        self.assertEqual((done['coverage']['indexed_units'], done['coverage']['total_units']), (6, 8))
        self.assertIn('Visual review could not read 2 pages or images (page 4, page 6); they are not counted as read.',
                      analysis['limitations'])
        self.assertEqual(len([item for item in analysis['limitations'] if item.startswith('Visual review could not read')]), 1)
        self.assertNotIn('Claim about the unread page.', json.dumps(analysis), 'A claim cited to an unread page is not kept')
        for page in (1, 2, 3, 5, 7, 8):
            self.assertTrue(self.store.search(self.scope, f'ScanNeedle{page}'), f'page {page} is searchable')
        for page in (4, 6):
            source = service.source(self.scope, record['id'], f'{record["id"]}_p{page}_c1')
            self.assertTrue(source['requires_vision'], 'An unread page stays an explicit placeholder')
        self.quiet(service, calls)
        # An explicit re-read asks again for the two unread pages only, and the outcome is current.
        unreadable.discard(4)
        del requested[:]
        service.action(self.scope, record['id'], 'revisit')
        again = self.wait(record['id'], intent=1)
        self.assertEqual(sorted(requested), [4, 6])
        self.assertEqual(again['coverage']['indexed_units'], 7)
        self.assertIn('Visual review could not read 1 page or image (page 6); it is not counted as read.', again['analysis']['limitations'])
        self.assertNotIn('page 4', ' '.join(again['analysis']['limitations']))
        self.assertFalse(again['analysis']['review_complete'])

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_read_again_asks_only_for_the_unread_pages(self):
        record = self.store.add(self.scope, 'scan.pdf', pdf_bytes(['text', 'blank', 'text', 'blank', 'blank', 'text']))
        unreadable, calls = {2, 5}, []

        def analyze(context, current, chunks, phase):
            visual = [chunk for chunk in chunks if chunk.get('requires_vision')]
            calls.append((phase, len(chunks), [chunk['page'] for chunk in visual]))
            reply = answer(chunks, notes=[f'Observation of request {len(calls)}.'])
            if visual and visual[0]['page'] not in unreadable:
                reply['extracted_text'] = f'ScanNeedle{visual[0]["page"]} approval table.'
            return reply
        service = self.service(analyze)
        first = self.wait(record['id'])
        self.assertEqual((first['coverage']['indexed_units'], first['analysis']['reviewed_chunks']), (4, 6))
        self.assertEqual([entry['unit'] for entry in first['analysis']['unreadable_sources']], ['page 2', 'page 5'])
        notes = len(first['analysis']['observations'])
        # Read again: page 2 now yields a reading, page 5 still does not. No text section is sent.
        unreadable.discard(2)
        del calls[:]
        started = service.action(self.scope, record['id'], 'reread')
        self.assertEqual((started['analysis']['phase'], started['analysis']['readings_only']), ('deep', True))
        second = self.wait(record['id'], intent=1)
        self.assertEqual(calls, [('deep', 1, [2]), ('deep', 1, [5])], 'Only the two unread pages were sent, each by itself')
        analysis = second['analysis']
        self.assertEqual((second['coverage']['indexed_units'], analysis['reviewed_chunks'], analysis['total_chunks']), (5, 6, 6))
        self.assertEqual([item for item in analysis['limitations'] if item.startswith('Visual review could not read')],
                         ['Visual review could not read 1 page or image (page 5); it is not counted as read.'])
        self.assertFalse(analysis['review_complete'])
        self.assertNotIn('readings_only', analysis)
        self.assertEqual(len(analysis['observations']), notes + 1,
                         'The notes of the review are kept; the page that was read adds its own, the unread one adds none')
        self.assertTrue(self.store.search(self.scope, 'ScanNeedle2'))
        self.quiet(service, calls)
        # Once the last page yields a reading the file is fully reviewed.
        unreadable.clear()
        del calls[:]
        service.action(self.scope, record['id'], 'reread')
        third = self.wait(record['id'], intent=2)
        self.assertEqual(calls, [('deep', 1, [5])])
        self.assertEqual((third['coverage']['indexed_units'], third['coverage']['total_units']), (6, 6))
        self.assertTrue(third['analysis']['review_complete'])
        self.assertEqual(third['analysis']['unreadable_sources'], [])
        # With nothing unread there is nothing to read again.
        same = service.action(self.scope, record['id'], 'reread')
        self.assertEqual(same['analysis']['intent_version'], 2)
        self.quiet(service, calls)

    def test_an_image_that_yields_no_reading_ends_the_review_without_a_pause(self):
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or answer(chunks))
        record = service.upload(self.scope, 'photo.png', png_bytes())
        done = self.wait(record['id'])
        self.assertEqual(calls, ['quick'], 'The image is asked for once; it is not sent again in the same pass')
        self.assertEqual(done['analysis']['limitations'],
                         ['Visual review could not read 1 page or image (the image); it is not counted as read.'])
        self.assertFalse(done['analysis']['review_complete'])
        self.assertEqual(done['coverage']['indexed_units'], 0)
        self.quiet(service, calls)

    def test_a_reply_that_breaks_the_contract_still_pauses_the_review(self):
        def analyze(context, record, chunks, phase):
            reply = answer(chunks)
            reply['extracted_text'] = 'A transcription although no page or image was supplied.'
            return reply
        service = self.service(analyze)
        record = service.upload(self.scope, 'cited.csv', b'important,field\na,1\n')
        paused = self.wait(record['id'], 'error')
        self.assertEqual(paused['analysis']['error'], service_module.REVIEW_PAUSED)


class FullNotesTests(ReviewCase):
    """live-documents-9: once nothing of a reply can be kept, no further text is sent."""

    def limits(self, questions, observations, queries):
        for name, value in (('MAX_QUESTIONS', questions), ('MAX_OBSERVATIONS', observations), ('MAX_QUERIES', queries)):
            limit = patch.object(service_module, name, value)
            limit.start()
            self.addCleanup(limit.stop)

    def test_the_sweep_ends_when_questions_observations_and_queries_are_all_full(self):
        self.limits(2, 6, 3)
        calls = []

        def analyze(context, record, chunks, phase):
            number = len(calls)
            calls.append((phase, [chunk['id'] for chunk in chunks]))
            reply = answer(chunks, notes=[f'Observation {number}a.', f'Observation {number}b.'])
            reply['questions'] = [{'text': f'Question {number}?', 'sources': [chunks[0]['id']]}]
            reply['queries'] = [f'query {number}']
            return reply
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(48))
        done = self.wait(record['id'])
        analysis = done['analysis']
        deep = [ids for phase, ids in calls if phase == 'deep']
        # Quick fills 2 observations, 1 question, 1 query; two in-depth requests fill the rest.
        self.assertEqual(len(deep), 2, f'{len(deep)} in-depth requests were sent; nothing of the later ones could be kept')
        self.assertEqual((len(analysis['observations']), len(analysis['questions']), len(analysis['queries'])), (6, 2, 3))
        self.assertEqual(analysis['total_chunks'], 48)
        self.assertEqual(analysis['reviewed_chunks'], sum(len(ids) for ids in deep), 'Only sections that were sent count as reviewed')
        self.assertLess(analysis['reviewed_chunks'], analysis['total_chunks'])
        self.assertFalse(analysis['review_complete'])
        self.assertTrue(analysis['limit_indicator'])
        for name, limit in (('questions', 2), ('observations', 6)):
            self.assertIn(f'Retained {name} reached the {limit}-item limit; full source chunks remain searchable.', analysis['limitations'])
        self.assertTrue(self.store.search(self.scope, 'entry47'), 'The sections that were not sent stay searchable')
        self.quiet(service, calls)

    def test_room_in_any_of_the_three_lists_keeps_the_sweep_going(self):
        self.limits(2, 6, 3)
        calls = []

        def analyze(context, record, chunks, phase):
            number = len(calls)
            calls.append(phase)
            reply = answer(chunks, notes=[f'Observation {number}a.', f'Observation {number}b.'])
            reply['questions'] = [{'text': f'Question {number}?', 'sources': [chunks[0]['id']]}]
            return reply  # No search queries: that list never fills.
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(24))
        done = self.wait(record['id'])
        self.assertEqual(calls.count('deep'), 6, 'A reply could still add a search query, so every section was sent')
        self.assertEqual(done['analysis']['reviewed_chunks'], 24)

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_pages_that_need_a_visual_reading_are_still_read_after_the_notes_are_full(self):
        self.limits(1, 1, 1)
        record = self.store.add(self.scope, 'manual.pdf', pdf_bytes(['text'] * 6 + ['blank'] * 3))
        calls = []

        def analyze(context, current, chunks, phase):
            visual = [chunk for chunk in chunks if chunk.get('requires_vision')]
            calls.append((phase, [chunk['id'] for chunk in chunks], [chunk['page'] for chunk in visual]))
            reply = answer(chunks, notes=[f'Observation {len(calls)}.'])
            reply['questions'] = [{'text': f'Question {len(calls)}?', 'sources': [chunks[0]['id']]}]
            reply['queries'] = [f'query {len(calls)}']
            if visual:
                reply['extracted_text'] = f'VisualNeedle{visual[0]["page"]} scanned approval table.'
            return reply
        service = self.service(analyze)
        done = self.wait(record['id'])
        deep = [(ids, pages) for phase, ids, pages in calls if phase == 'deep']
        self.assertTrue(all(len(ids) == 1 and pages for ids, pages in deep), 'After the notes are full only a page to read is sent')
        self.assertEqual(sorted(page for _, _, pages in calls for page in pages), [7, 8, 9], 'Every scanned page is read once')
        for page in (7, 8, 9):
            self.assertTrue(self.store.search(self.scope, f'VisualNeedle{page}'))
        analysis = done['analysis']
        self.assertEqual((done['coverage']['indexed_units'], done['coverage']['total_units']), (9, 9))
        self.assertEqual(analysis['reviewed_chunks'], len(deep), 'The text pages that were passed over are not counted as reviewed')
        self.assertLess(analysis['reviewed_chunks'], analysis['total_chunks'])
        self.assertFalse(analysis['review_complete'])
        self.assertTrue(analysis['limit_indicator'])


class RetryAfterErrorTests(ReviewCase):
    """live-documents-7: retry continues, a passing failure is tried again, a re-read replaces its notes."""

    def test_retry_review_continues_the_in_depth_pass_where_it_failed(self):
        calls, state = [], {'fail_at': 20}

        def analyze(context, record, chunks, phase):
            # The batches of one wave arrive in any order: the failure is the batch at section 20.
            failing = state['fail_at'] is not None and self.store.chunks(
                self.scope, record['id'], offset=state['fail_at'], limit=1)['chunks'][0]['id']
            if phase == 'deep' and chunks[0]['id'] == failing:
                state['fail_at'] = None
                calls.append(('failed', [chunk['id'] for chunk in chunks]))
                raise RuntimeError('Synthetic provider interruption')
            calls.append((phase, [chunk['id'] for chunk in chunks]))
            return answer(chunks, notes=[f'Observation of request {len(calls)}.'])
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(46))
        paused = self.wait(record['id'], 'error')
        self.assertEqual((paused['analysis']['cursor'], paused['analysis']['reviewed_chunks']), (20, 20))
        failed = next(ids for kind, ids in calls if kind == 'failed')
        notes_before = len(paused['analysis']['observations'])
        self.quiet(service, calls)
        retry_from = len(calls)
        resumed = service.action(self.scope, record['id'], 'revisit')
        self.assertEqual((resumed['analysis']['phase'], resumed['analysis']['cursor']), ('deep', 20), 'Retry must not start the review again')
        done = self.wait(record['id'], intent=1)
        after = calls[retry_from:]
        self.assertEqual([kind for kind, _ in after].count('quick'), 0, 'The first assessment was not paid for again')
        self.assertIn(failed, [ids for _, ids in after], 'The pass continues with the batch that failed')
        sent = [identity for kind, ids in calls if kind == 'deep' for identity in ids]
        before = {chunk['id'] for chunk in self.store.chunks(self.scope, record['id'], offset=0, limit=20)['chunks']}
        retried = {identity for _, ids in after for identity in ids}
        # Sections before the failed batch were recorded and are not sent again. A batch of the failed
        # wave answered after it was not recorded, so it is asked for again: that is the only repeat.
        self.assertFalse(before & retried, 'A recorded section was sent again')
        self.assertEqual(len(set(sent)), 46)
        analysis = done['analysis']
        self.assertTrue(analysis['review_complete'])
        self.assertEqual((analysis['cursor'], analysis['reviewed_chunks'], analysis['total_chunks']), (46, 46, 46))
        # One observation per recorded reply. The replies of the failed wave that came after the failed
        # batch were not recorded; their batches were asked for again and recorded once.
        batches = {ids[0] for kind, ids in calls if kind == 'deep'}
        self.assertEqual(len(analysis['observations']), 1 + len(batches),
                         'One observation per recorded batch: nothing repeated, nothing lost')
        self.assertGreater(len(analysis['observations']), notes_before)
        self.assertFalse(analysis['retry_required'])
        self.assertNotIn(service_module.REVIEW_PAUSED, analysis['limitations'])
        self.assertNotIn('error_phase', analysis)

    def test_a_failed_first_assessment_and_a_saved_for_later_file_start_again(self):
        calls, state = [], {'fail': 'quick'}

        def analyze(context, record, chunks, phase):
            if state['fail'] == phase:
                state['fail'] = None
                raise RuntimeError('Synthetic provider interruption')
            calls.append(phase)
            return answer(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(8))
        self.wait(record['id'], 'error')
        service.action(self.scope, record['id'], 'revisit')
        self.wait(record['id'], intent=1)
        self.assertEqual(calls, ['quick', 'deep', 'deep'])
        # A file saved for later after a failed in-depth pass is read from the start when revisited.
        del calls[:]
        state['fail'] = 'deep'
        service.action(self.scope, record['id'], 'revisit')
        self.wait(record['id'], 'error')
        service.action(self.scope, record['id'], 'park')
        restarted = service.action(self.scope, record['id'], 'revisit')
        self.assertEqual((restarted['analysis']['phase'], restarted['analysis']['cursor']), ('quick', 0))
        self.wait(record['id'], intent=4)
        # The failed wave's other batch may have been answered before the file was saved for later.
        self.assertEqual(calls[0], 'quick')
        self.assertEqual(calls[-3:], ['quick', 'deep', 'deep'])
        self.assertEqual(calls.count('quick'), 2)

    def test_a_passing_provider_failure_is_tried_again_before_the_review_pauses(self):
        attempts = []

        def analyze(context, record, chunks, phase):
            attempts.append(phase)
            if len(attempts) in (1, 2):
                raise server.APIError('PRIVATE', 502, 'rate_limit', True)
            return answer(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(3))
        done = self.wait(record['id'])
        self.assertEqual(attempts, ['quick', 'quick', 'quick'], 'The request was sent again twice, then answered')
        self.assertTrue(done['analysis']['review_complete'])
        self.assertIsNone(done['analysis']['error'])

    def test_three_passing_failures_in_a_row_pause_the_review_with_their_reason(self):
        attempts = []

        def analyze(context, record, chunks, phase):
            attempts.append(phase)
            raise server.APIError('PRIVATE', 504, 'timeout', True)
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(3))
        paused = self.wait(record['id'], 'error')
        self.assertEqual(attempts, ['quick'] * 3)
        self.assertEqual(paused['analysis']['error'], service_module.REVIEW_PAUSED_BY_CATEGORY['timeout'])
        self.quiet(service, attempts)

    def test_a_failure_that_waiting_cannot_cure_is_not_sent_again(self):
        for error in (server.APIError('PRIVATE', 502, 'quota'), server.APIError('PRIVATE', 502, 'rate_limit', 'yes'),
                      RuntimeError('PRIVATE')):
            with self.subTest(error=getattr(error, 'category', 'plain')):
                self.scope=self.store.create_scope()
                attempts = []

                def analyze(context, record, chunks, phase):
                    attempts.append(phase)
                    raise error
                service = self.service(analyze)
                record = service.upload(self.scope, 'ledger.csv', ledger(3))
                self.wait(record['id'], 'error')
                self.assertEqual(attempts, ['quick'])
        self.scope=self.store.create_scope()
        invalid = []

        def cites_elsewhere(context, record, chunks, phase):
            invalid.append(phase)
            reply = answer(chunks, notes=['Fabricated.'])
            reply['observations'][0]['sources'] = ['fabricated_document_source']
            return reply
        service = self.service(cites_elsewhere)
        record = service.upload(self.scope, 'cited.csv', ledger(3))
        self.wait(record['id'], 'error')
        self.assertEqual(invalid, ['quick'], 'An invalid reply is never sent again by itself')

    def test_waiting_for_another_attempt_does_not_hold_up_closing_the_app(self):
        attempts = []

        def analyze(context, record, chunks, phase):
            attempts.append(phase)
            raise server.APIError('PRIVATE', 502, 'rate_limit', True)
        with patch.object(service_module, 'RETRY_DELAYS', (30, 30)):
            service = self.service(analyze)
            record = service.upload(self.scope, 'ledger.csv', ledger(3))
            deadline = time.monotonic() + 60
            while not attempts and time.monotonic() < deadline:
                threading.Event().wait(.01)
            service.action(self.scope, record['id'], 'remove')
            service.close()  # Ends the wait at once; a removed file's review is not resumed.
            service._worker.join(timeout=5)
            self.assertFalse(service._worker.is_alive())
        self.assertEqual(attempts, ['quick'])

    def test_an_explicit_re_read_replaces_the_notes_of_the_reading_before_it(self):
        counter = {'pass': 1}

        def analyze(context, record, chunks, phase):
            return answer(chunks, notes=[f'Wording of pass {counter["pass"]} for {chunks[0]["id"][-8:]} in {phase}.'])
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(8))
        first = self.wait(record['id'])
        self.assertEqual(len(first['analysis']['observations']), 3)
        counter['pass'] = 2
        service.action(self.scope, record['id'], 'revisit')
        second = self.wait(record['id'], intent=1)
        texts = [item['text'] for item in second['analysis']['observations']]
        self.assertEqual(len(texts), 3, 'The same findings worded differently were kept beside the earlier ones')
        self.assertTrue(all('pass 2' in text for text in texts), texts)
        self.assertTrue(second['analysis']['review_complete'])

    def test_notes_reaching_their_limit_in_one_reading_do_not_mark_the_next_reading(self):
        with patch.object(service_module, 'MAX_OBSERVATIONS', 2):
            service = self.service(lambda context, record, chunks, phase: answer(chunks, notes=[f'Observation in {phase} of {chunks[0]["id"][-8:]}.']))
            record = service.upload(self.scope, 'ledger.csv', ledger(12))
            first = self.wait(record['id'])
            self.assertTrue(first['analysis']['limit_indicator'])
        service.action(self.scope, record['id'], 'revisit')
        second = self.wait(record['id'], intent=1)
        self.assertFalse(second['analysis']['limit_indicator'])
        self.assertEqual([item for item in second['analysis']['limitations'] if item.startswith('Retained')], [])
        self.assertTrue(second['analysis']['review_complete'])


class ParticipantChoiceTests(ReviewCase):
    """live-documents-16: the participant can overrule the verdict and word the purpose again."""

    def reviewer(self, calls, relevant_when=None):
        def analyze(context, record, chunks, phase):
            calls.append((phase, record['analysis'].get('purpose', '')))
            related = relevant_when is not None and relevant_when in record['analysis'].get('purpose', '')
            return answer(chunks, 'relevant' if related else 'unrelated')
        return analyze

    def parked_by_verdict(self, service):
        record = service.upload(self.scope, 'returns-log.csv', b'approver,amount\nAda,42\n')
        self.assertEqual(self.wait(record['id'])['analysis']['disposition'], 'needs_reason')
        service.action(self.scope, record['id'], 'purpose', 'Look at the approver column.')
        parked = self.wait(record['id'], intent=1)
        self.assertEqual(parked['analysis']['disposition'], 'parked')
        self.assertEqual(service.supporting_context(self.scope, 'approver')['documents'], [])
        return record['id'], parked

    def test_use_this_file_anyway_puts_a_parked_file_to_use_as_the_participants_choice(self):
        calls = []
        service = self.service(self.reviewer(calls))
        identity, parked = self.parked_by_verdict(service)
        self.assertEqual((parked['analysis']['relevance'], parked['analysis']['relevance_reason']),
                         ('unrelated', 'The synthetic reviewer judged this file unrelated.'), 'The verdict and its reason are on the record')
        before = len(calls)
        used = service.action(self.scope, identity, 'use')
        analysis = used['analysis']
        self.assertEqual((analysis['disposition'], analysis['selected_by_participant'], analysis['parked_by_user']), ('relevant', True, False))
        self.assertEqual((analysis['relevance'], analysis['phase']), ('unrelated', 'complete'), 'The verdict stays; nothing is reviewed again')
        self.quiet(service, calls)
        self.assertEqual(len(calls), before)
        document = service.supporting_context(self.scope, 'approver')['documents'][0]
        self.assertEqual((document['id'], document['disposition']), (identity, 'relevant'))
        self.assertEqual((document['disposition_basis'], document['reviewer_relevance']), ('participant_selected', 'unrelated'))
        self.assertTrue(document['excerpts'])
        # The choice outlives a new reading that reaches the same verdict.
        service.action(self.scope, identity, 'revisit')
        again = self.wait(identity, intent=3)
        self.assertEqual((again['analysis']['disposition'], again['analysis']['relevance']), ('relevant', 'unrelated'))
        self.assertEqual(again['analysis']['question'], '')
        # Save for later takes the file out again and ends the choice.
        service.action(self.scope, identity, 'park')
        later = self.wait(identity, intent=4)
        self.assertEqual((later['analysis']['disposition'], later['analysis']['selected_by_participant']), ('parked', False))
        self.assertEqual(service.supporting_context(self.scope, 'approver')['documents'], [])

    def test_a_file_the_reviewer_decided_itself_carries_no_participant_label(self):
        service = self.service(lambda context, record, chunks, phase: answer(chunks))
        record = service.upload(self.scope, 'returns-log.csv', b'approver,amount\nAda,42\n')
        self.wait(record['id'])
        document = service.supporting_context(self.scope, 'approver')['documents'][0]
        self.assertNotIn('disposition_basis', document)
        self.assertNotIn('reviewer_relevance', document)

    def test_use_this_file_anyway_answers_the_first_question_without_a_purpose(self):
        calls = []
        service = self.service(self.reviewer(calls))
        record = service.upload(self.scope, 'returns-log.csv', b'approver,amount\nAda,42\n')
        self.wait(record['id'])
        used = service.action(self.scope, record['id'], 'use')
        self.assertEqual((used['analysis']['disposition'], used['analysis']['question']), ('relevant', ''))
        self.assertEqual(service.supporting_context(self.scope, 'approver')['documents'][0]['disposition_basis'], 'participant_selected')

    def test_using_a_file_whose_review_is_paused_does_not_send_it_again(self):
        calls = []

        def analyze(context, record, chunks, phase):
            calls.append(phase)
            raise RuntimeError('Synthetic provider interruption')
        service = self.service(analyze)
        record = service.upload(self.scope, 'returns-log.csv', b'approver,amount\nAda,42\n')
        self.wait(record['id'], 'error')
        used = service.action(self.scope, record['id'], 'use')
        self.assertEqual((used['analysis']['phase'], used['analysis']['disposition']), ('error', 'relevant'))
        self.assertTrue(used['analysis']['error'])
        self.quiet(service, calls)
        self.assertEqual(calls, ['quick'])

    def test_revisit_lets_the_participant_word_the_purpose_again(self):
        calls = []
        service = self.service(self.reviewer(calls, relevant_when='second signer'))
        identity, _ = self.parked_by_verdict(service)
        with self.assertRaises(ValueError):
            service.action(self.scope, identity, 'purpose', 'Without Revisit a second purpose is still refused.')
        service.action(self.scope, identity, 'revisit')
        asked = self.wait(identity, intent=2)
        self.assertEqual(asked['analysis']['disposition'], 'needs_reason', 'Revisit repeated the verdict and left no way to answer it')
        self.assertTrue(asked['analysis']['question'])
        self.assertFalse(asked['analysis']['purpose_attempted'])
        self.assertEqual(calls[-1][1], 'Look at the approver column.', 'The earlier purpose is still what the reviewer was told')
        service.action(self.scope, identity, 'purpose', 'It shows who is the second signer for each return.')
        relevant = self.wait(identity, intent=3)
        self.assertEqual((relevant['analysis']['disposition'], relevant['analysis']['purpose']),
                         ('relevant', 'It shows who is the second signer for each return.'))
        self.assertNotIn('selected_by_participant', relevant['analysis'])
        self.assertEqual(service.supporting_context(self.scope, 'approver')['documents'][0]['id'], identity)

    def test_an_unknown_action_names_the_actions_that_exist(self):
        service = self.service(lambda *args: self.fail('No review is expected'))
        record = self.store.add(self.scope, 'returns-log.csv', b'approver,amount\nAda,42\n')
        with self.assertRaises(ValueError) as refused:
            service.action(self.scope, record['id'], 'erase')
        for name in ('purpose', 'park', 'revisit', 'use', 'stop', 'continue', 'reread', 'remove', 'restore'):
            self.assertIn(name, str(refused.exception))


class StopReviewTests(ReviewCase):
    """gap-cost-model-4: the size of a review is stated, and it can be stopped without losing the file."""

    def gated(self, calls, hold_at=2):
        """A reviewer that waits inside the in-depth request of its hold_at-th batch (four sections each) until released.

        The batches of one file go out together, so the batch is named by its place in the file,
        not by the order in which the requests happen to arrive.
        """
        entered, release = threading.Event(), threading.Event()

        def analyze(context, record, chunks, phase):
            calls.append((phase, [chunk['id'] for chunk in chunks]))
            held = self.store.chunks(self.scope, record['id'], offset=4 * (hold_at - 1), limit=1)['chunks'][0]['id']
            if phase == 'deep' and chunks[0]['id'] == held and not release.is_set():
                entered.set()
                release.wait(60)
            return answer(chunks, notes=[f'Observation of request {len(calls)}.'])
        return analyze, entered, release

    def test_the_first_assessment_says_about_how_many_requests_the_whole_file_takes(self):
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or answer(chunks))
        record = service.upload(self.scope, 'ledger.csv', ledger(40))
        done = self.wait(record['id'])
        estimated = done['analysis']['estimated_requests']
        sent = calls.count('deep')
        self.assertEqual(sent, 10)
        self.assertTrue(sent - 2 <= estimated <= sent, f'{estimated} requests announced, {sent} sent')
        small = service.upload(self.scope, 'small.csv', b'important,field\na,1\n')
        self.assertEqual(self.wait(small['id'])['analysis']['estimated_requests'], 1)

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_the_pages_of_a_scan_are_read_together_and_all_of_them_are_read(self):
        record = self.store.add(self.scope, 'scan.pdf', pdf_bytes(['blank'] * 8))
        lock, state = threading.Lock(), {'active': 0, 'most': 0, 'pages': 0}

        def analyze(context, current, chunks, phase):
            visual = any(chunk.get('requires_vision') for chunk in chunks)
            with lock:
                state['active'] += 1
                state['most'] = max(state['most'], state['active'])
                state['pages'] += visual
            threading.Event().wait(.05)
            with lock:
                state['active'] -= 1
            reply = answer(chunks)
            if visual:
                reply['extracted_text'] = 'A scanned page.'
            return reply
        self.service(analyze)
        done = self.wait(record['id'])
        self.assertEqual(state['pages'], 8, 'Each page is read once')
        self.assertGreater(state['most'], 1, 'The pages after the first pass were read one after another')
        self.assertEqual(done['coverage']['visual_pending_units'], 0)
        self.assertTrue(done['analysis']['review_complete'])

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_a_scan_counts_one_request_for_each_page_to_read(self):
        record = self.store.add(self.scope, 'scan.pdf', pdf_bytes(['blank'] * 12))

        def analyze(context, current, chunks, phase):
            reply = answer(chunks)
            if any(chunk.get('requires_vision') for chunk in chunks):
                reply['extracted_text'] = 'A scanned page.'
            return reply
        self.service(analyze)
        self.assertEqual(self.wait(record['id'])['analysis']['estimated_requests'], 12)

    def test_stop_review_ends_the_requests_and_keeps_the_file_readable_and_continue_resumes_it(self):
        calls = []
        analyze, entered, release = self.gated(calls)
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(40))
        self.assertTrue(entered.wait(60))
        # The first batch's reply is recorded while the second batch's request is still open.
        for _ in range(600):
            if (self.store.get(self.scope, record['id'])['analysis'] or {}).get('cursor') == 4:
                break
            threading.Event().wait(.01)
        stopped = service.action(self.scope, record['id'], 'stop')
        release.set()
        analysis = stopped['analysis']
        self.assertEqual((analysis['phase'], analysis['review_stopped'], analysis['review_complete']), ('complete', True, False))
        self.assertEqual((analysis['cursor'], analysis['reviewed_chunks']), (4, 4), 'Only the answered request counts')
        self.assertIn('Background review was stopped at your request before every section was sent for review. '
                      'The indexed text stays searchable; Continue review resumes it.', analysis['limitations'])
        threading.Event().wait(.2)
        self.quiet(service, calls)
        # The ten in-depth batches went out together before Stop; none is sent again or after it.
        first_wave = calls[1:]
        self.assertEqual(calls[0][0], 'quick')
        self.assertTrue(1 <= len(first_wave) <= 10 and all(kind == 'deep' for kind, _ in first_wave))
        self.assertEqual(len({ids[0] for _, ids in first_wave}), len(first_wave), 'Nothing was sent after Stop review')
        held_before = len(calls)
        current = self.store.get(self.scope, record['id'])
        self.assertFalse(current['archived'], 'Stop review is not Remove')
        self.assertEqual(current['analysis']['reviewed_chunks'], 4, 'The reply that arrived after Stop was not merged')
        self.assertTrue(self.store.search(self.scope, 'entry39'), 'Every section stays searchable')
        document = service.supporting_context(self.scope, 'entry39')['documents'][0]
        self.assertIn('entry39', document['excerpts'][0]['text'], 'The interview can still read the file')
        # A second Stop changes nothing; saving for later does not restart the review.
        self.assertEqual(service.action(self.scope, record['id'], 'stop')['analysis']['intent_version'], 1)
        service.action(self.scope, record['id'], 'park')
        self.quiet(service, calls)
        resumed = service.action(self.scope, record['id'], 'continue')
        self.assertEqual((resumed['analysis']['phase'], resumed['analysis']['cursor']), ('deep', 4))
        self.assertNotIn('review_stopped', resumed['analysis'])
        done = self.wait(record['id'], intent=3)
        after = [kind for kind, _ in calls[held_before:]]
        self.assertEqual(after, ['deep'] * 9, 'Continue review goes on from the section where the review stopped')
        opening = self.store.chunks(self.scope, record['id'], offset=0, limit=1)['chunks'][0]['id']
        first = next(ids for _, ids in first_wave if ids[0] == opening)
        sent = [identity for ids in [first, *(ids for _, ids in calls[held_before:])] for identity in ids]
        self.assertEqual((len(sent), len(set(sent))), (40, 40))
        self.assertEqual(done['analysis']['reviewed_chunks'], 40)
        self.assertEqual([item for item in done['analysis']['limitations'] if item.startswith('Background review was stopped')], [])

    def test_stopping_before_the_file_is_indexed_still_indexes_it_and_sends_nothing(self):
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or answer(chunks))
        record = self.store.add(self.scope, 'ledger.csv', ledger(8))  # Saved, not yet indexed.
        stopped = service.action(self.scope, record['id'], 'stop')
        self.assertTrue(stopped['analysis']['review_stopped'])
        done = self.wait(record['id'])
        self.assertEqual(calls, [], 'A stopped review sends nothing, not even the first assessment')
        self.assertEqual((done['status'], done['chunk_count'], done['analysis']['total_chunks']), ('ready', 8, 8))
        self.assertFalse(done['analysis']['review_complete'])
        self.assertTrue(self.store.search(self.scope, 'entry7'))
        self.quiet(service, calls)
        service.action(self.scope, record['id'], 'continue')
        self.wait(record['id'], intent=2)
        self.assertEqual(calls, ['quick', 'deep', 'deep'])

    def test_stop_and_continue_do_nothing_when_there_is_nothing_to_stop_or_continue(self):
        calls = []
        service = self.service(lambda context, record, chunks, phase: calls.append(phase) or answer(chunks))
        record = service.upload(self.scope, 'small.csv', b'important,field\na,1\n')
        done = self.wait(record['id'])
        for action in ('stop', 'continue'):
            same = service.action(self.scope, record['id'], action)
            self.assertEqual((same['analysis']['intent_version'], same['analysis']['version']),
                             (done['analysis']['intent_version'], done['analysis']['version']))
            self.assertNotIn('review_stopped', same['analysis'])
        self.quiet(service, calls)

    def test_an_explicit_re_read_of_a_stopped_file_starts_the_review_again(self):
        calls = []
        analyze, entered, release = self.gated(calls, hold_at=1)
        service = self.service(analyze)
        record = service.upload(self.scope, 'ledger.csv', ledger(8))
        self.assertTrue(entered.wait(60))
        service.action(self.scope, record['id'], 'stop')
        release.set()
        service.action(self.scope, record['id'], 'park')
        restarted = service.action(self.scope, record['id'], 'revisit')
        self.assertNotIn('review_stopped', restarted['analysis'])
        done = self.wait(record['id'], intent=3)
        self.assertTrue(done['analysis']['review_complete'])
        self.assertEqual([kind for kind, _ in calls].count('quick'), 2)
        self.assertEqual([kind for kind, _ in calls[-3:]], ['quick', 'deep', 'deep'])


if __name__ == '__main__':
    unittest.main()
