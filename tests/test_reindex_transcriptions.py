"""A re-index keeps stored AI visual transcriptions until a new reading arrives.

Real DocumentStore, DocumentService and KnowledgeGraph on temporary SQLite
stores. The review callback is scripted: no provider or network access.
"""
import knowledge_rows as rows
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from test_server import server

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


documents = load('reindex_documents', 'documents.py')
service = load('reindex_document_service', 'document_service.py')
kg = load('reindex_knowledge_graph', 'knowledge_graph.py')

TRANSCRIPTION = ('Carrier | Service | Maximum claim per parcel\n'
                 'Northline | Standard | 250\nNorthline | Express | 1000')
REREAD = TRANSCRIPTION + '\nNorthline | Freight | 5000'
HAS_PDF = bool(importlib.util.find_spec('pypdf'))


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def png_bytes():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (66, 21), 'white').save(output, format='PNG')
    return output.getvalue()


def pdf_bytes(kinds):
    """One page per entry: 'blank' (no text), 'text', or 'mixed' (text plus an image)."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, DecodedStreamObject
    writer = PdfWriter()
    for kind in kinds:
        page = writer.add_blank_page(width=300, height=200)
        if kind == 'blank':
            continue
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        command = b'BT /F1 12 Tf 20 160 Td (Native process instruction) Tj ET'
        if kind == 'mixed':
            image = DecodedStreamObject()
            image.set_data(b'\x00\x00\x00\xff\xff\xff')
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                          NameObject('/Width'): NumberObject(2), NameObject('/Height'): NumberObject(1),
                          NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'): writer._add_object(image)})
            command += b' q 100 0 0 50 20 40 cm /Im1 Do Q'
        page[NameObject('/Resources')] = resources
        contents = DecodedStreamObject()
        contents.set_data(command)
        page[NameObject('/Contents')] = writer._add_object(contents)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def reviewed(extracted_text=''):
    return {'summary': 'Fictional rate card.', 'acknowledgement': 'Fictional fixture.', 'relevance': 'relevant',
            'relevance_reason': 'Fictional fixture.', 'question': '', 'queries': [], 'observations': [],
            'questions': [], 'extracted_text': extracted_text}


class StoreCase(unittest.TestCase):
    documents_module, service_module = documents, service

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = self.documents_module.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()
        self.parsed = {}

    def indexed(self, name, data):
        record = self.store.add(self.scope, name, data)
        self.assertNotEqual(self.store.extract(self.scope, record['id'])['status'], 'error')
        # What the parser alone writes, before any review: the placeholder of each visual source.
        self.parsed.update({chunk['id']: chunk for chunk in self.store.chunks(self.scope, record['id'], limit=500)['chunks']})
        return record['id']

    def placeholder(self, source_id):
        self.assertEqual(self.parsed[source_id]['origin'], 'visual_placeholder')
        return self.parsed[source_id]['text']

    def transcribed_png(self, text=TRANSCRIPTION):
        # Independent histories need separate workspaces; a repeat upload in one workspace reuses its index.
        self.scope = self.store.create_scope()
        document_id = self.indexed('rate-card.png', png_bytes())
        source_id = document_id + '_image_c1'
        return document_id, source_id, self.store.record_extracted_text(self.scope, document_id, source_id, text)

    def outdate(self, document_id, version=None, drop_digests=False):
        """Rewrite the stored record as an earlier build left it; chunks are untouched."""
        with self.store._db() as db:
            old = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()[0])
            old.pop('extraction_needs_reindex', None)
            old.pop('extraction_version', None)
            if version is not None:
                old['extraction_version'] = version
            if drop_digests:
                old.pop('visual_transcription_hashes', None)
            old['analysis'] = {'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'cursor': 1}
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(old), document_id))

    def rows(self, document_id):
        return [(chunk['id'], chunk['text'], chunk['location'])
                for chunk in self.store.chunks(self.scope, document_id, limit=500)['chunks']]


class ReindexKeepsTranscriptionTests(StoreCase):
    def test_reindex_keeps_a_recorded_transcription_however_the_record_became_outdated(self):
        current = documents.EXTRACTION_VERSION
        cases = (('no stored version, as 0.19.1 and earlier wrote', lambda identity: self.outdate(identity), current),
                 ('neither a version nor a content digest', lambda identity: self.outdate(identity, drop_digests=True), current),
                 ('an earlier stored version', lambda identity: self.outdate(identity, current - 1), current),
                 ('the application raises its extraction version', lambda identity: None, current + 1))
        for label, age, running in cases:
            with self.subTest(label):
                document_id, source_id, before = self.transcribed_png()
                self.assertEqual(before['visual_transcription_hashes'], {'image': digest(TRANSCRIPTION)})
                age(document_id)
                with patch.object(documents, 'EXTRACTION_VERSION', running):
                    self.assertTrue(self.store.get(self.scope, document_id)['extraction_needs_reindex'])
                    after = self.store.extract(self.scope, document_id)
                    source = self.store.source(self.scope, document_id, source_id)
                    hits = self.store.search(self.scope, 'Northline', ids=[document_id])
                    self.assertFalse(self.store.get(self.scope, document_id)['extraction_needs_reindex'])
                self.assertEqual(after['extraction_version'], running)
                self.assertEqual(source['text'], TRANSCRIPTION)
                self.assertEqual(source['origin'], 'ai_visual_transcription')
                self.assertFalse(source['requires_vision'])
                self.assertIs(source['verified'], False)
                self.assertEqual([hit['id'] for hit in hits], [source_id])
                self.assertEqual(after['visual_transcription_hashes'], {'image': digest(TRANSCRIPTION)})
                self.assertEqual(after['inventory']['visual_transcribed_units'], ['image'])
                self.assertEqual((after['coverage']['indexed_units'], after['coverage']['total_units']), (1, 1))
                self.assertEqual(after['coverage']['limitations'], before['coverage']['limitations'])
                self.assertEqual((after['status'], after['chunk_count']), ('partial', 1))
                self.assertEqual(list(after['visual_reread_pending']), [source_id])
                self.assertEqual(documents.reread_placeholder(after, source_id), self.placeholder(source_id),
                                 'The kept source is marked for the separate re-read step, with the sentence the parser wrote for it')
                self.assertIn('Image contents require native visual review', self.placeholder(source_id))

    def test_reindex_keeps_every_part_of_a_long_transcription_in_order(self):
        long_text = ''.join(f'Row {number:05d} | fictional value {number * 7}\n' for number in range(480))
        document_id, source_id, before = self.transcribed_png(long_text)
        stored = self.rows(document_id)
        self.assertEqual([row[0] for row in stored], [source_id, source_id + '_v2', source_id + '_v3'])
        self.outdate(document_id)
        after = self.store.extract(self.scope, document_id)
        self.assertEqual(self.rows(document_id), stored)
        self.assertEqual(''.join(row[1] for row in self.rows(document_id)), long_text)
        self.assertEqual(after['visual_transcription_hashes'], {'image': digest(long_text)})
        self.assertEqual(after['chunk_count'], 3)
        self.assertEqual(list(after['visual_reread_pending']), [source_id], 'Continuation parts are not separate sources')

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_reindex_keeps_page_transcriptions_and_counts_every_page_once(self):
        document_id = self.indexed('scanned.pdf', pdf_bytes(['text', 'blank', 'blank', 'mixed']))
        scanned, mixed, unread = (document_id + suffix for suffix in ('_p2_c1', '_p4_visual_c1', '_p3_c1'))
        self.store.record_extracted_text(self.scope, document_id, scanned, 'Scanned page: approvals above 500 need a second signer.')
        before = self.store.record_extracted_text(self.scope, document_id, mixed, 'Diagram: Intake -> Review -> Release.')
        stored = self.rows(document_id)
        self.outdate(document_id)
        after = self.store.extract(self.scope, document_id)
        self.assertCountEqual(self.rows(document_id), stored)
        self.assertTrue(self.store.source(self.scope, document_id, unread)['requires_vision'],
                        'A page that was never read stays an explicit placeholder')
        self.assertEqual(self.store.source(self.scope, document_id, document_id + '_p4_c1')['text'].strip(), 'Native process instruction')
        self.assertEqual(after['inventory'], before['inventory'])
        self.assertEqual(after['inventory']['visual_transcribed_units'], [2, 4])
        self.assertEqual(after['visual_transcription_hashes'], before['visual_transcription_hashes'])
        self.assertEqual(set(after['visual_transcription_hashes']), {'2', '4'})
        self.assertEqual((after['coverage']['indexed_units'], after['coverage']['total_units']), (3, 4))
        self.assertCountEqual(after['coverage']['limitations'], before['coverage']['limitations'])
        self.assertIn('1 pages still require native visual review.', after['coverage']['limitations'])
        self.assertEqual({source: documents.reread_placeholder(after, source) for source in after['visual_reread_pending']},
                         {scanned: self.placeholder(scanned), mixed: self.placeholder(mixed)})
        self.assertEqual(list(after['visual_reread_pending']), [scanned, mixed])
        self.assertEqual(after['chunk_count'], len(stored))

    def test_text_the_parser_now_reads_itself_replaces_the_transcription_and_is_counted_once(self):
        document_id, source_id, _ = self.transcribed_png()
        self.outdate(document_id)

        def reads_text(path, record, chunks):
            chunks.add('image', record['name'] + ' · image', 'Parser-read text', {'image': True})
            return {'images': 1}, {'indexed_units': 1, 'total_units': 1, 'limitations': []}

        with patch.object(documents, '_png', reads_text):
            after = self.store.extract(self.scope, document_id)
        source = self.store.source(self.scope, document_id, source_id)
        self.assertEqual(source['text'], 'Parser-read text')
        self.assertNotEqual(source.get('origin'), 'ai_visual_transcription')
        self.assertEqual(after['visual_transcription_hashes'], {})
        self.assertNotIn('visual_transcribed_units', after['inventory'])
        self.assertNotIn('visual_reread_pending', after)
        self.assertEqual((after['status'], after['coverage']['indexed_units'], after['chunk_count']), ('ready', 1, 1))

    def test_reindex_that_cannot_hold_the_transcription_publishes_nothing_and_keeps_the_old_index(self):
        text = TRANSCRIPTION * 4
        document_id, source_id, before = self.transcribed_png(text)
        self.outdate(document_id)
        with patch.object(documents, 'MAX_INDEX_BYTES', 200):
            result = self.store.extract(self.scope, document_id)
        self.assertEqual(result['status'], 'error')
        self.assertIn('indexing limit', result['error'])
        source = self.store.source(self.scope, document_id, source_id)
        self.assertEqual((source['text'], source['origin']), (text, 'ai_visual_transcription'))
        self.assertEqual(self.store.get(self.scope, document_id)['visual_transcription_hashes'], before['visual_transcription_hashes'])


class ReviewCase(StoreCase):
    def manager(self, callback):
        manager = self.service_module.DocumentService(self.store, callback)

        def stop():
            manager.close()
            manager._worker.join(timeout=5)
        self.addCleanup(stop)
        return manager

    def settle(self, document_id, phase='complete'):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            record = self.store.get(self.scope, document_id)
            if record['status'] not in ('pending', 'indexing') and (record.get('analysis') or {}).get('phase') == phase:
                return record
            threading.Event().wait(.01)
        self.fail(f'Review did not reach {phase}: {record["status"]} {record.get("analysis")}')


class ReviewAfterReindexTests(ReviewCase):
    def test_failed_review_after_reindex_keeps_the_recorded_transcription(self):
        document_id, source_id, before = self.transcribed_png()
        self.outdate(document_id)
        # Changed with gap-upgrade-1: a poll now compares the saved index with what the current parser
        # reads, locally, and an identical index needs no re-index at all. This file keeps needing one
        # because its index is one the current parser does not reproduce.
        with self.store._db() as db:
            db.execute("UPDATE chunks SET label='Label written by an earlier parser' WHERE document_id=?", (document_id,))
        provider, seen = {'available': False}, []

        def review(context, record, chunks, phase):
            seen.append((phase, [(chunk['id'], bool(chunk.get('requires_vision')), chunk['text']) for chunk in chunks]))
            if not provider['available']:
                raise RuntimeError('Synthetic provider refusal')
            return reviewed(TRANSCRIPTION if any(chunk.get('requires_vision') for chunk in chunks) else '')
        manager = self.manager(review)
        for _ in range(3):
            manager.status(self.scope, {})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and self.store.get(self.scope, document_id)['reindex_check']['outcome'] == 'pending':
            threading.Event().wait(.01)
        checked = self.store.get(self.scope, document_id)
        self.assertEqual((checked['reindex_check']['outcome'], checked['extraction_needs_reindex']), ('changed', True))
        self.assertEqual(seen, [], 'Opening or polling an outdated file never starts a paid review')
        manager.action(self.scope, document_id, 'revisit')
        paused = self.settle(document_id, 'error')
        source = manager.source(self.scope, document_id, source_id)
        self.assertEqual(source['text'], TRANSCRIPTION)
        self.assertEqual(source['origin'], 'ai_visual_transcription')
        self.assertFalse(source['requires_vision'])
        self.assertIs(source['verified'], False)
        self.assertEqual([hit['id'] for hit in self.store.search(self.scope, 'Northline')], [source_id])
        self.assertEqual(seen, [('quick', [(source_id, True, self.placeholder(source_id))])],
                         'The new reading is requested as its own step, for the kept source, under the parser placeholder')
        self.assertEqual(paused['visual_transcription_hashes'], before['visual_transcription_hashes'])
        self.assertEqual(paused['inventory']['visual_transcribed_units'], ['image'])
        self.assertEqual((paused['coverage']['indexed_units'], paused['coverage']['total_units']), (1, 1))
        self.assertEqual(list(paused['visual_reread_pending']), [source_id])
        self.assertFalse(paused['extraction_needs_reindex'])
        self.assertFalse(paused['analysis']['review_complete'])
        self.assertIn('Select Retry review', paused['analysis']['error'])
        for _ in range(3):
            manager.status(self.scope, {})
        threading.Event().wait(.05)
        self.assertEqual(len(seen), 1, 'A paused re-read is never retried by polling')
        # The next explicit retry asks again; an identical reading changes nothing a citation depends on.
        provider['available'] = True
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        self.assertEqual([(phase, [chunk[1] for chunk in chunks]) for phase, chunks in seen[1:]],
                         [('quick', [True]), ('deep', [False])])
        self.assertEqual(manager.source(self.scope, document_id, source_id)['text'], TRANSCRIPTION)
        self.assertEqual(complete['visual_transcription_hashes'], before['visual_transcription_hashes'])
        self.assertNotIn('visual_reread_pending', complete)
        self.assertTrue(complete['analysis']['review_complete'])

    def test_a_new_reading_replaces_the_transcription_only_when_it_arrives(self):
        document_id, source_id, before = self.transcribed_png()
        self.outdate(document_id)
        seen = []

        def review(context, record, chunks, phase):
            visual = [chunk for chunk in chunks if chunk.get('requires_vision')]
            seen.append((phase, [chunk['id'] for chunk in visual], [chunk['text'] for chunk in chunks]))
            return reviewed(REREAD if visual else '')
        manager = self.manager(review)
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        self.assertEqual(seen, [('quick', [source_id], [self.placeholder(source_id)]), ('deep', [], [REREAD])],
                         'One visual request per kept source, without the stored text; later batches read the new text')
        source = manager.source(self.scope, document_id, source_id)
        self.assertEqual((source['text'], source['origin'], source['verified']), (REREAD, 'ai_visual_transcription', False))
        self.assertEqual(complete['visual_transcription_hashes'], {'image': digest(REREAD)})
        self.assertNotEqual(complete['visual_transcription_hashes'], before['visual_transcription_hashes'])
        self.assertNotIn('visual_reread_pending', complete)
        self.assertEqual(complete['inventory']['visual_transcribed_units'], ['image'])
        self.assertTrue(complete['analysis']['review_complete'])

    def test_an_empty_new_reading_keeps_the_transcription_and_does_not_stop_the_review(self):
        # Changed with document-service-1: an empty reading used to pause the review at that
        # source on every retry. It is now an outcome for that one source.
        document_id, source_id, before = self.transcribed_png()
        self.outdate(document_id)
        requested = []

        def review(context, record, chunks, phase):
            requested.append((phase, [chunk['id'] for chunk in chunks if chunk.get('requires_vision')], [chunk['text'] for chunk in chunks]))
            return reviewed('')
        manager = self.manager(review)
        manager.action(self.scope, document_id, 'revisit')
        done = self.settle(document_id)
        self.assertEqual(requested, [('quick', [source_id], [self.placeholder(source_id)]), ('deep', [], [TRANSCRIPTION])],
                         'The new reading is asked for once; the stored transcription is then reviewed as the text it still is')
        analysis = done['analysis']
        self.assertIsNone(analysis['error'])
        self.assertFalse(analysis['retry_required'])
        self.assertFalse(analysis['review_complete'], 'The file still owes a new reading')
        noted = [item for item in analysis['limitations'] if 'no new reading' in item]
        self.assertEqual(len(noted), 1, analysis['limitations'])
        self.assertIn('stored transcription is kept', noted[0])
        self.assertNotIn('not counted as read', ' '.join(analysis['limitations']), 'The earlier reading still counts')
        self.assertEqual(done['coverage']['indexed_units'], 1)
        source = manager.source(self.scope, document_id, source_id)
        self.assertEqual((source['text'], source['origin']), (TRANSCRIPTION, 'ai_visual_transcription'))
        self.assertEqual(done['visual_transcription_hashes'], before['visual_transcription_hashes'])
        self.assertEqual(list(done['visual_reread_pending']), [source_id])

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_each_kept_page_is_read_again_once_and_a_failure_leaves_the_rest_in_place(self):
        document_id = self.indexed('scanned.pdf', pdf_bytes(['blank', 'blank', 'blank']))
        pages = [f'{document_id}_p{number}_c1' for number in (1, 2, 3)]
        for number, source_id in enumerate(pages, 1):
            self.store.record_extracted_text(self.scope, document_id, source_id, f'Earlier reading of page {number}.')
        self.outdate(document_id)
        failing, requested = {pages[1]}, []

        def review(context, record, chunks, phase):
            visual = [chunk for chunk in chunks if chunk.get('requires_vision')]
            self.assertLessEqual(len(visual), 1, 'At most one visual source per request')
            if visual:
                requested.append(visual[0]['id'])
                if visual[0]['id'] in failing:
                    raise RuntimeError('Synthetic provider refusal')
                return reviewed(f'New reading of page {visual[0]["page"]}.')
            return reviewed()
        manager = self.manager(review)
        manager.action(self.scope, document_id, 'revisit')
        paused = self.settle(document_id, 'error')
        self.assertEqual(requested, pages[:2])
        self.assertEqual([manager.source(self.scope, document_id, source_id)['text'] for source_id in pages],
                         ['New reading of page 1.', 'Earlier reading of page 2.', 'Earlier reading of page 3.'])
        self.assertEqual(list(paused['visual_reread_pending']), pages[1:])
        self.assertEqual((paused['coverage']['indexed_units'], paused['coverage']['total_units']), (3, 3))
        failing.clear()
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        self.assertEqual(requested, [*pages[:2], *pages[1:]], 'Only the sources still awaiting a new reading are sent again')
        self.assertEqual([manager.source(self.scope, document_id, source_id)['text'] for source_id in pages],
                         [f'New reading of page {number}.' for number in (1, 2, 3)])
        self.assertNotIn('visual_reread_pending', complete)
        self.assertTrue(complete['analysis']['review_complete'])

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_long_kept_transcriptions_are_each_read_again_once_and_no_section_is_skipped(self):
        document_id = self.indexed('scanned.pdf', pdf_bytes(['blank'] * 5))
        pages = [f'{document_id}_p{number}_c1' for number in range(1, 6)]

        def reading(tag, number, rows):
            return ''.join(f'{tag} page {number} row {row:04d} | fictional value {row * 7}\n' for row in range(rows))
        # Pages 2 and 4 hold transcriptions long enough to be stored in three rows (_v2, _v3).
        earlier = {source_id: reading('Earlier', number, 300 if number in (2, 4) else 1) for number, source_id in enumerate(pages, 1)}
        # The new reading of page 2 is long again; the one of page 4 is short, so its parts disappear.
        new = {source_id: reading('New', number, 300 if number == 2 else 1) for number, source_id in enumerate(pages, 1)}
        for source_id in pages:
            self.store.record_extracted_text(self.scope, document_id, source_id, earlier[source_id])
        self.outdate(document_id)
        kept = self.store.extract(self.scope, document_id)
        ids = lambda: [row[0] for row in self.rows(document_id)]
        self.assertEqual(ids(), [pages[0], pages[1], pages[1] + '_v2', pages[1] + '_v3', pages[2],
                                 pages[3], pages[3] + '_v2', pages[3] + '_v3', pages[4]])
        self.assertEqual(list(kept['visual_reread_pending']), pages)
        self.outdate(document_id)
        failing, requested, answered, batches, texts = {pages[3]}, [], [], [], []

        def review(context, record, chunks, phase):
            visual = [chunk for chunk in chunks if chunk.get('requires_vision')]
            batches.append((phase, [chunk['id'] for chunk in chunks], [chunk['id'] for chunk in visual]))
            texts.extend(chunk['text'] for chunk in chunks)
            if not visual:
                return reviewed()
            requested.append(visual[0]['id'])
            if visual[0]['id'] in failing:
                batches.pop()  # A refused request reviewed nothing.
                raise RuntimeError('Synthetic provider refusal')
            answered.append(visual[0]['id'])
            return reviewed(new[visual[0]['id']])
        manager = self.manager(review)
        manager.action(self.scope, document_id, 'revisit')
        paused = self.settle(document_id, 'error')
        self.assertEqual(requested, pages[:4], 'Replacing the three rows of page 2 must not carry the review past pages 3 and 4')
        self.assertEqual(list(paused['visual_reread_pending']), pages[3:])
        self.assertFalse(paused['analysis']['review_complete'])
        self.assertEqual(ids(), [*pages[:2], pages[1] + '_v2', pages[1] + '_v3', *pages[2:4], pages[3] + '_v2', pages[3] + '_v3', pages[4]])
        stored = dict((row[0], row[1]) for row in self.rows(document_id))
        self.assertEqual(''.join(stored[pages[3] + suffix] for suffix in ('', '_v2', '_v3')), earlier[pages[3]],
                         'A refused reading leaves every row of the stored transcription in place')
        self.assertEqual(stored[pages[4]], earlier[pages[4]])
        failing.clear()
        # Changed with live-documents-7: Retry review continues the in-depth pass where it
        # failed, so the sections are counted over both attempts, not over a second full pass.
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        self.assertEqual([phase for phase, _, _ in batches].count('quick'), 1, 'Retry after an error does not start the review again')
        self.assertCountEqual(answered, pages, 'Every kept page receives exactly one new reading')
        self.assertCountEqual(requested[4:], pages[3:], 'Only the pages still awaiting a new reading are sent again')
        self.assertNotIn('visual_reread_pending', complete)
        final = ids()
        self.assertEqual(final, [*pages[:2], pages[1] + '_v2', pages[1] + '_v3', *pages[2:]])
        self.assertCountEqual([identity for phase, offered, _ in batches if phase == 'deep' for identity in offered], final,
                              'The in-depth pass offers every stored section once: none skipped, none repeated')
        for phase, offered, visual in batches:
            for identity in visual:
                self.assertFalse([part for part in offered if part.startswith(identity + '_v')],
                                 'A request for a new reading does not offer the rows that reading replaces')
        self.assertFalse([text for text in texts if 'Earlier' in text], 'A stored transcription awaiting its new reading is never review input')
        stored = dict((row[0], row[1]) for row in self.rows(document_id))
        self.assertEqual(''.join(stored[pages[1] + suffix] for suffix in ('', '_v2', '_v3')), new[pages[1]].strip())
        self.assertEqual([stored[source_id] for source_id in (pages[0], *pages[2:])], [new[source_id].strip() for source_id in (pages[0], *pages[2:])])
        analysis = complete['analysis']
        self.assertEqual((analysis['cursor'], analysis['reviewed_chunks'], analysis['total_chunks']), (len(final),) * 3)
        self.assertTrue(analysis['review_complete'])
        self.assertEqual((complete['coverage']['indexed_units'], complete['coverage']['total_units']), (5, 5))

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_a_request_for_a_new_reading_offers_no_row_it_replaces_as_a_citable_source(self):
        document_id = self.indexed('scanned.pdf', pdf_bytes(['text', 'blank']))
        source_id = f'{document_id}_p2_c1'
        long_text = ''.join(f'Row {number:05d} | fictional value {number * 7}\n' for number in range(480))
        self.store.record_extracted_text(self.scope, document_id, source_id, long_text)
        self.assertEqual([row[0] for row in self.rows(document_id)][1:], [source_id, source_id + '_v2', source_id + '_v3'])
        self.outdate(document_id)
        offered = []

        def review(context, record, chunks, phase):
            visual = [chunk for chunk in chunks if chunk.get('requires_vision')]
            offered.append(([chunk['id'] for chunk in visual], [chunk['id'] for chunk in chunks]))
            result = reviewed('Short new reading of page 2.' if visual else '')
            # A reviewer may cite any source it was given; here always the last one supplied.
            result['observations'] = [{'text': f'Fictional observation {len(offered)}.', 'sources': [chunks[-1]['id']]}]
            return result
        manager = self.manager(review)
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        self.assertEqual([visual for visual, _ in offered if visual], [[source_id]])
        for visual, supplied in offered:
            if visual:
                self.assertNotIn(source_id + '_v2', supplied)
                self.assertNotIn(source_id + '_v3', supplied)
        cited = [source['source_id'] for source in complete['analysis']['sources']]
        self.assertIn(source_id, cited)
        for identity in cited:
            self.assertEqual(manager.source(self.scope, document_id, identity)['id'], identity, 'Every accepted citation opens a stored source')
        self.assertEqual([row[0] for row in self.rows(document_id)], [f'{document_id}_p1_c1', source_id])
        self.assertTrue(complete['analysis']['review_complete'])

    def test_a_file_is_not_fully_reviewed_while_a_kept_source_awaits_its_new_reading(self):
        document_id, source_id, current = self.transcribed_png()
        review_complete = service.DocumentService._review_complete
        self.assertTrue(review_complete(current, {}, 1, 1))
        self.outdate(document_id)
        kept = self.store.extract(self.scope, document_id)
        self.assertEqual((kept['extraction_needs_reindex'], kept['coverage']['indexed_units'], kept['coverage']['total_units']), (False, 1, 1))
        self.assertEqual(list(kept['visual_reread_pending']), [source_id])
        self.assertFalse(review_complete(kept, {}, 1, 1), 'Reaching the last section does not finish a review that still owes a new reading')
        read = self.store.record_extracted_text(self.scope, document_id, source_id, REREAD)
        self.assertNotIn('visual_reread_pending', read)
        self.assertTrue(review_complete(read, {}, 1, 1))


class ProviderRequestTests(ReviewCase):
    """The application's own request builder; only the provider transport is replaced by a recorder."""
    documents_module = server.documents
    service_module = server.local_module('document_service', 'document_service.py')

    def test_new_reading_request_is_the_parser_placeholder_with_the_original_image_and_never_the_kept_text(self):
        original = png_bytes()
        document_id = self.indexed('rate-card.png', original)
        source_id = document_id + '_image_c1'
        parsed = self.parsed[source_id]
        self.store.record_extracted_text(self.scope, document_id, source_id, TRANSCRIPTION)
        self.outdate(document_id)
        client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-reindex-sentinel-never-a-real-credential'})
        sent = []

        def transport(path, body, *args, **kwargs):
            content = body['input'][0]['content']
            payload = json.loads(content[0]['text'] if isinstance(content, list) else content)
            sent.append({'payload': payload, 'raw': json.dumps(body),
                         'images': [item['image_url'] for item in content if isinstance(item, dict) and item.get('type') == 'input_image'],
                         'extracted_text': body['text']['format']['schema']['properties']['extracted_text']})
            result = reviewed(REREAD if payload['visual_source_id'] else '')
            return {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(result)}]}]}
        client.request = Mock(side_effect=transport)
        manager = self.manager(lambda context, record, chunks, phase: client.analyze_document(context, record, chunks, phase, self.store))
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        self.assertEqual([item['payload']['phase'] for item in sent], ['quick', 'deep'])
        first, second = sent
        self.assertEqual(first['payload']['visual_source_id'], source_id)
        # The chunk a re-index sent before stored transcriptions were kept: what the parser alone writes.
        self.assertEqual(first['payload']['chunks'],
                         [{'id': source_id, 'label': parsed['label'], 'text': self.placeholder(source_id),
                           'location': {'image': True, 'requires_vision': True, 'origin': 'visual_placeholder'},
                           'requires_vision': True}])
        self.assertEqual(first['payload']['chunks'][0]['location'], parsed['location'])
        self.assertNotIn('Northline', first['raw'], 'The stored transcription is not sent with the request for a new reading')
        self.assertNotIn('ai_visual_transcription', json.dumps(first['payload']['chunks']))
        self.assertEqual(len(first['images']), 1)
        self.assertEqual(base64.b64decode(first['images'][0].split(',', 1)[1]), original)
        self.assertEqual(first['extracted_text'], {'type': 'string'}, 'A new transcription may be returned for the supplied image')
        self.assertIsNone(second['payload']['visual_source_id'])
        self.assertEqual(second['images'], [])
        self.assertEqual(second['extracted_text'], {'type': 'string', 'enum': ['']})
        self.assertEqual([chunk['text'] for chunk in second['payload']['chunks']], [REREAD])
        for item in sent:
            self.assertNotIn('visual_reread_pending', item['raw'], 'Review bookkeeping is not provider input')
            self.assertNotIn(self.scope, item['raw'])
        self.assertEqual(manager.source(self.scope, document_id, source_id)['text'], REREAD)
        self.assertNotIn('visual_reread_pending', complete)


def submission(name, statement):
    return {'context': {'process_name': name}, 'participant': 'Participant', 'team': 'Operations', 'scope': 'Fund A',
            'turns': [{'id': 'u1', 'role': 'user', 'text': statement}],
            'draft': {'title': name, 'inputs': [], 'outputs': [],
                      'steps': [{'id': 's1', 'title': 'Start', 'type': 'activity', 'actor': 'Analyst', 'evidence_turns': ['u1']}],
                      'connections': []},
            'documents': {}, 'memo_findings': []}


class SubmittedConnectionTests(ReviewCase):
    def finished(self, graph, job):
        for _ in range(500):
            row = next(item for item in rows.jobs(graph) if item['id'] == job)
            if row['status'] not in ('pending', 'processing'):
                return row['status']
            time.sleep(.01)
        self.fail('Knowledge job timed out')

    def test_transcription_quoted_by_matching_survives_a_failed_review_after_reindex(self):
        document_id, source_id, _ = self.transcribed_png()

        def refuse(context, record, chunks, phase):
            raise RuntimeError('Synthetic provider refusal')
        manager = self.manager(refuse)
        quote = 'Northline | Express | 1000'

        def analyze(current, candidates):
            other = candidates[0]
            return [{'source_submission_id': other['submission_id'], 'source_revision': other['revision'],
                     'destination_submission_id': current['submission_id'], 'destination_revision': current['revision'],
                     'relationship_type': 'hands_off_to', 'scope': 'Fund A', 'condition': '',
                     'explanation': 'Both accounts use the carrier claim limit.', 'inference': 'Possible handoff; needs review.',
                     'missing_evidence': [], 'contradictions': [],
                     'evidence': [{'type': 'document_supported', 'submission_id': other['submission_id'], 'revision': other['revision'],
                                   'document_id': document_id, 'source_id': source_id, 'quote': quote},
                                  {'submission_id': current['submission_id'], 'revision': current['revision'],
                                   'turn_id': 'u1', 'quote': current['turns'][0]['text']}]}]
        graph = kg.KnowledgeGraph(Path(self.temporary.name) / 'knowledge' / 'graph.db', analyze, document_resolver=manager.source)
        self.addCleanup(graph.close)
        first = submission('Carrier claims', 'We follow the attached rate card.')
        first['documents'] = {'scope': self.scope, 'documents': [{'id': document_id, 'name': 'rate-card.png',
                                                                 'sources': [{'source_id': source_id, 'label': 'rate-card.png · image'}]}]}
        self.assertEqual(self.finished(graph, graph.submit(first, document_scope=self.scope)['job_id']), 'completed')
        second = graph.submit(submission('Claim payment', 'We pay claims up to the carrier limit.'))
        self.assertEqual(self.finished(graph, second['job_id']), 'completed')
        proposed = rows.proposals(graph)[0]
        self.assertEqual((proposed['evidence'][0]['type'], proposed['evidence'][0]['origin']),
                         ('document_supported', 'ai_visual_transcription'))
        # The store is opened by a newer build and the owner retries while the provider refuses.
        self.outdate(document_id)
        manager.action(self.scope, document_id, 'revisit')
        self.settle(document_id, 'error')
        self.assertEqual(rows.proposals(graph)[0]['evidence'][0]['source_hash'], digest(TRANSCRIPTION))


if __name__ == '__main__':
    unittest.main()
