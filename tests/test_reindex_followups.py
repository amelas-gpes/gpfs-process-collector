"""Follow-ups to keeping stored AI visual transcriptions across a re-index.

Real DocumentStore and DocumentService on temporary SQLite stores, and the
application's own request builder with only the provider transport replaced.
No provider or network access.
"""
import json
import unittest
from unittest.mock import Mock

from test_reindex_transcriptions import (HAS_PDF, REREAD, TRANSCRIPTION, ReviewCase, StoreCase, documents,
                                         pdf_bytes, png_bytes, reviewed, server, service)

# The base classes above carry no tests of their own; only their helpers are used here.


class RequestCoverageTests(ReviewCase):
    """r1-reindex-1: the request for a new reading must not already count that unit as read."""
    documents_module = server.documents
    service_module = server.local_module('document_service', 'document_service.py')

    def recorded(self, answer):
        client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-reindex-sentinel-never-a-real-credential'})
        sent = []

        def transport(path, body, *args, **kwargs):
            content = body['input'][0]['content']
            payload = json.loads(content[0]['text'] if isinstance(content, list) else content)
            sent.append(payload)
            return {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(answer(payload))}]}]}
        client.request = Mock(side_effect=transport)
        manager = self.manager(lambda context, record, chunks, phase: client.analyze_document(context, record, chunks, phase, self.store))
        return manager, sent

    def test_the_request_for_a_new_reading_of_an_image_shows_that_image_as_not_yet_read(self):
        document_id = self.indexed('rate-card.png', png_bytes())
        source_id = document_id + '_image_c1'
        parsed = self.store.get(self.scope, document_id)
        self.assertEqual((parsed['coverage']['indexed_units'], parsed['coverage']['total_units']), (0, 1))
        self.store.record_extracted_text(self.scope, document_id, source_id, TRANSCRIPTION)
        self.outdate(document_id)
        stored = []

        def answer(payload):
            # What the store says while the request for the new reading is out.
            stored.append(self.store.get(self.scope, document_id))
            return reviewed(REREAD if payload['visual_source_id'] else '')
        manager, sent = self.recorded(answer)
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        first, second = sent
        self.assertEqual(first['visual_source_id'], source_id)
        # The file-level figures of that request are the parser's own: nothing read yet.
        self.assertEqual(first['file']['coverage'], parsed['coverage'])
        self.assertEqual(first['file']['inventory'], parsed['inventory'])
        self.assertNotIn('visual_transcribed_units', first['file']['inventory'])
        self.assertIn('Image contents require native visual review; no OCR was performed.', first['file']['coverage']['limitations'])
        self.assertNotIn('independently verified', json.dumps(first['file']))
        # The stored record is untouched by that view: the kept transcription still counts.
        self.assertEqual((stored[0]['coverage']['indexed_units'], stored[0]['inventory']['visual_transcribed_units']), (1, ['image']))
        self.assertEqual(self.store.source(self.scope, document_id, source_id)['text'], REREAD)
        # Once the reading has arrived, later requests describe the unit as read.
        self.assertIsNone(second['visual_source_id'])
        self.assertEqual((second['file']['coverage']['indexed_units'], second['file']['inventory']['visual_transcribed_units']), (1, ['image']))
        self.assertTrue(complete['analysis']['review_complete'])
        for key in ('visual_reread_pending', 'visual_reread_basis'):
            self.assertNotIn(key, complete)
            self.assertNotIn(key, json.dumps(sent), 'Review bookkeeping is not provider input')

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_each_page_is_uncounted_only_in_the_request_that_reads_it_again(self):
        document_id = self.indexed('scanned.pdf', pdf_bytes(['text', 'blank', 'blank', 'blank']))
        pages = {number: f'{document_id}_p{number}_c1' for number in (2, 3, 4)}
        for number in (2, 3):  # Page 4 was never read.
            self.store.record_extracted_text(self.scope, document_id, pages[number], f'Earlier reading of page {number}.')
        self.outdate(document_id)
        manager, sent = self.recorded(lambda payload: reviewed(
            f'New reading of {payload["visual_source_id"]}.' if payload['visual_source_id'] else ''))
        manager.action(self.scope, document_id, 'revisit')
        complete = self.settle(document_id)
        readings = {payload['visual_source_id']: payload['file'] for payload in sent if payload['visual_source_id']}
        self.assertEqual(set(readings), set(pages.values()), 'Every scanned page is read once')
        for number in (2, 3):
            file = readings[pages[number]]
            self.assertNotIn(number, file['inventory']['visual_transcribed_units'], 'The page being read is not listed as read')
            self.assertIn(5 - number, file['inventory']['visual_transcribed_units'], 'The other kept page is still listed: it is stored text')
            self.assertEqual((file['coverage']['indexed_units'], file['coverage']['total_units']), (2, 4))
            self.assertIn('2 pages still require native visual review.', file['coverage']['limitations'])
        # A page that never had a transcription is described by the store as it is.
        self.assertEqual(readings[pages[4]]['coverage']['indexed_units'], 3)
        self.assertEqual((complete['coverage']['indexed_units'], complete['coverage']['total_units']), (4, 4))

    def test_a_record_without_the_parser_coverage_is_described_as_stored(self):
        document_id, source_id, current = self.transcribed_png()
        legacy = {**current, 'visual_reread_pending': {source_id: 'Earlier placeholder sentence.'}}
        inventory, coverage = documents.unread_view(legacy, 'image')
        self.assertEqual((inventory, coverage), (current['inventory'], current['coverage']))
        self.assertEqual(documents.unread_view(current, 'no such unit'), (current['inventory'], current['coverage']))


class PendingRecordSizeTests(StoreCase):
    """r1-reindex-3: a long scan must not carry one placeholder sentence per pending page."""

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_each_placeholder_sentence_is_stored_once_however_many_pages_await_a_reading(self):
        count = 120
        document_id = self.indexed('long-scan.pdf', pdf_bytes(['blank'] * count))
        pages = [f'{document_id}_p{number}_c1' for number in range(1, count + 1)]
        for number, source_id in enumerate(pages, 1):
            self.store.record_extracted_text(self.scope, document_id, source_id, f'Earlier reading of page {number}.')
        before = self.store.get(self.scope, document_id)
        self.outdate(document_id)
        after = self.store.extract(self.scope, document_id)
        self.assertEqual(list(after['visual_reread_pending']), pages)
        sentence = self.placeholder(pages[0])
        self.assertEqual(json.dumps(after).count(sentence), 1, 'The sentence every page shares is saved once')
        self.assertEqual({documents.reread_placeholder(after, source_id) for source_id in pages}, {sentence})
        extra = len(json.dumps(after)) - len(json.dumps(before))
        ids_only = len(json.dumps(pages))
        self.assertLess(extra, ids_only + 12 * count + 1024,
                        'Beside the list of pending source IDs the record grows by a few bytes per page, not by a sentence')
        # Each arriving reading shrinks the bookkeeping; the last one removes it.
        for number, source_id in enumerate(pages, 1):
            current = self.store.record_extracted_text(self.scope, document_id, source_id, f'New reading of page {number}.')
        self.assertNotIn('visual_reread_pending', current)
        self.assertNotIn('visual_reread_basis', current)

    @unittest.skipUnless(HAS_PDF, 'Existing PDF runtime required')
    def test_different_placeholders_keep_their_own_sentence(self):
        document_id = self.indexed('mixed.pdf', pdf_bytes(['text', 'blank', 'mixed', 'blank']))
        scanned, other, mixed = (document_id + suffix for suffix in ('_p2_c1', '_p4_c1', '_p3_visual_c1'))
        for source_id in (scanned, other, mixed):
            self.store.record_extracted_text(self.scope, document_id, source_id, 'Earlier reading.')
        self.outdate(document_id)
        after = self.store.extract(self.scope, document_id)
        self.assertEqual(len(after['visual_reread_basis']['placeholders']), 2)
        for source_id in (scanned, other, mixed):
            self.assertEqual(documents.reread_placeholder(after, source_id), self.placeholder(source_id))
        self.assertNotEqual(self.placeholder(scanned), self.placeholder(mixed))
        self.assertIsNone(documents.reread_placeholder(after, document_id + '_p1_c1'), 'A page the parser reads itself awaits nothing')

    def test_a_record_that_holds_the_sentence_itself_is_still_read(self):
        # Written by the build that first kept transcriptions: source ID -> sentence.
        record = {'visual_reread_pending': {'doc_x_image_c1': 'PNG image 2 by 2 pixels.'}}
        self.assertEqual(documents.reread_placeholder(record, 'doc_x_image_c1'), 'PNG image 2 by 2 pixels.')
        chunk = {'id': 'doc_x_image_c1', 'label': 'x.png · image', 'text': 'Stored transcription.', 'verified': False,
                 'location': {'image': True, 'requires_vision': False, 'origin': 'ai_visual_transcription', 'verified': False}}
        offered = service.DocumentService._reread(record, [chunk])
        self.assertEqual([(item['text'], item['requires_vision'], item['origin']) for item in offered],
                         [('PNG image 2 by 2 pixels.', True, 'visual_placeholder')])


class ReplacedPartCitationTests(ReviewCase):
    """r1-reindex-2: a note must not keep a link to a continuation row that a shorter reading removed."""

    def test_a_note_citing_a_part_that_a_shorter_new_reading_removes_follows_its_source(self):
        long_text = ''.join(f'Row {number:05d} | fictional value {number * 7}\n' for number in range(480))
        document_id, source_id, _ = self.transcribed_png(long_text)
        parts = [source_id, source_id + '_v2', source_id + '_v3']
        self.assertEqual([row[0] for row in self.rows(document_id)], parts)
        self.outdate(document_id)
        self.store.extract(self.scope, document_id)
        label = self.parsed[source_id]['label']
        # An in-depth pass that was under way when the app closed: its notes cite all three rows.
        notes = [{'id': f'{document_id}_note{index}', 'text': f'Fictional note {index}.',
                  'sources': [{'source_id': part, 'label': label}]} for index, part in enumerate(parts, 1)]
        notes.append({'id': f'{document_id}_note4', 'text': 'Fictional note on two rows.',
                      'sources': [{'source_id': parts[0], 'label': label}, {'source_id': parts[2], 'label': label}]})
        self.store.update(self.scope, document_id, {'analysis': {
            'phase': 'deep', 'cursor': 0, 'reviewed_chunks': 0, 'intent_version': 4, 'disposition': 'relevant', 'version': 3,
            'summary': 'Fictional rate card.', 'relevance': 'relevant', 'relevance_reason': 'Fictional fixture.',
            'questions': notes[:1], 'observations': notes[1:],
            'sources': [{'source_id': part, 'label': label} for part in parts]}})
        manager = self.manager(lambda context, record, chunks, phase: reviewed(
            'Short new reading.' if any(chunk.get('requires_vision') for chunk in chunks) else ''))
        manager.status(self.scope, {})  # The poll after a restart continues the pass.
        complete = self.settle(document_id)
        self.assertEqual([row[0] for row in self.rows(document_id)], [source_id], 'The shorter reading removed the later rows')
        analysis = complete['analysis']
        self.assertEqual([source['source_id'] for source in analysis['sources']], [source_id])
        for item in analysis['questions'] + analysis['observations']:
            self.assertEqual([source['source_id'] for source in item['sources']], [source_id], item['text'])
            self.assertEqual(item['sources'][0]['label'], label)
        self.assertEqual(len(analysis['questions']) + len(analysis['observations']), 4, 'No note was dropped')
        for source in analysis['sources']:
            self.assertEqual(manager.source(self.scope, document_id, source['source_id'])['id'], source['source_id'],
                             'Every listed source opens')

    def test_a_part_that_the_new_reading_writes_again_keeps_its_citation(self):
        long_text = ''.join(f'Row {number:05d} | fictional value {number * 7}\n' for number in range(480))
        document_id, source_id, _ = self.transcribed_png(long_text)
        self.outdate(document_id)
        self.store.extract(self.scope, document_id)
        label = self.parsed[source_id]['label']
        self.store.update(self.scope, document_id, {'analysis': {
            'phase': 'deep', 'cursor': 0, 'reviewed_chunks': 0, 'intent_version': 2, 'disposition': 'relevant', 'version': 3,
            'summary': 'Fictional rate card.', 'relevance': 'relevant', 'relevance_reason': 'Fictional fixture.', 'questions': [],
            'observations': [{'id': f'{document_id}_note', 'text': 'Fictional note.',
                              'sources': [{'source_id': source_id + '_v2', 'label': label}]}],
            'sources': [{'source_id': source_id + '_v2', 'label': label}]}})
        again = long_text.replace('fictional', 'corrected')
        manager = self.manager(lambda context, record, chunks, phase: reviewed(
            again if any(chunk.get('requires_vision') for chunk in chunks) else ''))
        manager.status(self.scope, {})
        complete = self.settle(document_id)
        self.assertEqual([source['source_id'] for source in complete['analysis']['sources']], [source_id + '_v2'])
        self.assertIn('corrected', manager.source(self.scope, document_id, source_id + '_v2')['text'])


if __name__ == '__main__':
    unittest.main()
