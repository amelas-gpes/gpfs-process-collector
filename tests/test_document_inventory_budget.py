"""The 50 KiB inventory must hold a PDF of the documented 500 pages, before and after visual review."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import test_document_visual_boundaries as visual

spec = importlib.util.spec_from_file_location('collector_document_service_inventory', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
import documents


def size(inventory):
    return len(json.dumps(inventory, ensure_ascii=False).encode('utf-8'))


def pdf_inventory(pages, kind, text_chars=99_999_999, sample='界' * 180):
    """What documents._pdf returns for a PDF whose pages are all of one kind, at its largest."""
    numbers = list(range(1, pages + 1))
    readable = kind != 'failed'
    return {'pages': pages,
            'page_inventory': [{'page': number, 'text_chars': text_chars if readable else 0, 'sample': sample if readable else '',
                                'requires_vision': kind != 'text'} for number in numbers],
            'text_pages': pages if readable else 0, 'text_only_pages': pages if kind == 'text' else 0,
            'mixed_visual_pages': numbers if kind == 'mixed' else [],
            'vision_pages': [] if kind == 'text' else numbers,
            'failed_pages': numbers if kind == 'failed' else [], 'requires_vision': kind != 'text'}


def old_budget(inventory):
    """The budget as it was before this fix: no room kept for later readings, samples never left out."""
    while size(inventory) > documents.MAX_INVENTORY_BYTES - 512:
        reduced = False
        for unit in inventory['page_inventory']:
            if unit.get('sample'):
                unit['sample'] = unit['sample'][:len(unit['sample']) // 2]
                unit['sample_truncated'] = True
                reduced = True
        if not reduced:
            raise AssertionError('this inventory could not have been stored by the earlier build')
    return inventory


class InventoryBudget(unittest.TestCase):
    def test_largest_pdf_fits_with_room_for_a_reading_of_every_page(self):
        for kind in ('mixed', 'failed', 'text'):
            for pages in (documents.MAX_PDF_PAGES, 470, 455):
                with self.subTest(kind=kind, pages=pages):
                    inventory = documents._inventory_budget(pdf_inventory(pages, kind))
                    self.assertEqual([unit['page'] for unit in inventory['page_inventory']], list(range(1, pages + 1)))
                    self.assertEqual(len(inventory['vision_pages']), 0 if kind == 'text' else pages)
                    self.assertTrue(all(unit['requires_vision'] == (kind != 'text') for unit in inventory['page_inventory']))
                    if kind != 'failed':  # A page that could not be decoded has no sample to give up.
                        self.assertTrue(inventory['summary_limitations'])
                    # Every page that awaits a reading receives one, in the order a review supplies them.
                    for number in inventory['vision_pages']:
                        inventory.setdefault('visual_transcribed_units', []).append(number)
                        inventory = documents._inventory_budget(inventory)
                    self.assertLessEqual(size(inventory), documents.MAX_INVENTORY_BYTES)
                    self.assertEqual(len(inventory.get('visual_transcribed_units', [])), len(inventory['vision_pages']))

    def test_samples_are_shortened_before_they_are_left_out_and_each_state_is_flagged(self):
        modest = documents._inventory_budget(pdf_inventory(120, 'mixed'))
        self.assertTrue(all(unit['sample'] and unit['sample_truncated'] for unit in modest['page_inventory']))
        self.assertEqual(modest['summary_limitations'], [documents.SAMPLES_SHORTENED])
        self.assertNotIn('samples_omitted', modest)
        small = documents._inventory_budget(pdf_inventory(40, 'mixed'))
        self.assertTrue(all(len(unit['sample']) == 180 and 'sample_truncated' not in unit for unit in small['page_inventory']))
        self.assertNotIn('summary_limitations', small)
        largest = documents._inventory_budget(pdf_inventory(documents.MAX_PDF_PAGES, 'mixed'))
        self.assertTrue(largest['samples_omitted'])
        self.assertEqual(largest['summary_limitations'], [documents.SAMPLES_OMITTED])
        self.assertTrue(all(set(unit) == {'page', 'text_chars', 'requires_vision'} for unit in largest['page_inventory']))

    def test_inventory_that_cannot_fit_names_what_to_do_and_only_extraction_refuses_it(self):
        sheets = [{'name': 'S' * 900 + str(index), 'index': index, 'rows': 1, 'columns': 1, 'header_sample': 'A1=x',
                   'header_sample_truncated': False, 'populated_cells': 1, 'formula_cells': 0,
                   'formulas_without_cached_values': 0} for index in range(1, 101)]
        with self.assertRaises(documents.ExtractionError) as refusal:
            documents._inventory_budget({'sheets': copy.deepcopy(sheets), 'sheet_count': 100})
        self.assertEqual(str(refusal.exception), documents.INVENTORY_LIMIT_MESSAGE)
        self.assertIn('Split it into smaller files', documents.INVENTORY_LIMIT_MESSAGE)
        kept = documents._inventory_budget({'sheets': copy.deepcopy(sheets), 'sheet_count': 100}, strict=False)
        self.assertEqual([sheet['name'] for sheet in kept['sheets']], [sheet['name'] for sheet in sheets])


class FiveHundredPages(unittest.TestCase):
    """The real parser, store and review loop on a PDF at the page limit whose pages all carry graphics."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = visual.pdf_bytes('vector', documents.MAX_PDF_PAGES)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()

    def extracted(self):
        record = self.store.extract(self.scope, self.store.add(self.scope, 'manual.pdf', self.pdf)['id'])
        self.assertEqual(record['status'], 'partial', record.get('error'))
        self.assertEqual(record['inventory']['pages'], documents.MAX_PDF_PAGES)
        self.assertEqual(len(record['inventory']['page_inventory']), documents.MAX_PDF_PAGES)
        self.assertEqual(record['inventory']['vision_pages'], list(range(1, documents.MAX_PDF_PAGES + 1)))
        self.assertEqual(record['chunk_count'], 2 * documents.MAX_PDF_PAGES)
        return record

    def test_every_page_of_a_500_page_pdf_with_graphics_indexes_and_takes_a_reading(self):
        record = self.extracted()
        for number in range(1, documents.MAX_PDF_PAGES + 1):
            record = self.store.record_extracted_text(self.scope, record['id'], f'{record["id"]}_p{number}_visual_c1',
                                                      f'Reading of the diagram on page {number}.')
        self.assertLessEqual(size(record['inventory']), documents.MAX_INVENTORY_BYTES)
        self.assertEqual(record['inventory']['visual_transcribed_units'], list(range(1, documents.MAX_PDF_PAGES + 1)))
        self.assertEqual(record['coverage']['indexed_units'], documents.MAX_PDF_PAGES)
        self.assertNotIn('native visual review', json.dumps(record['coverage']['limitations']))
        self.assertEqual(self.store.source(self.scope, record['id'], f'{record["id"]}_p500_visual_c1')['text'],
                         'Reading of the diagram on page 500.')

    def test_inventory_stored_by_the_earlier_build_at_its_limit_still_takes_every_reading(self):
        record = self.extracted()
        # 455 mixed pages were the most the earlier build stored; the 146th reading then failed for good.
        with self.store._db() as db:
            saved = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (record['id'],)).fetchone()[0])
            saved['inventory'] = old_budget(pdf_inventory(455, 'mixed', text_chars=2600, sample='Header line ' * 15))
            # Exactly at the earlier limit, with no byte to spare for a list of the pages read.
            saved['inventory']['page_inventory'][0]['sample'] += 'x' * (documents.MAX_INVENTORY_BYTES - 512 - size(saved['inventory']))
            self.assertEqual(size(saved['inventory']), documents.MAX_INVENTORY_BYTES - 512)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(saved), record['id']))
        for number in range(1, 456):
            record = self.store.record_extracted_text(self.scope, record['id'], f'{record["id"]}_p{number}_visual_c1', 'A reading.')
            self.assertLessEqual(size(record['inventory']), documents.MAX_INVENTORY_BYTES, number)
        self.assertEqual(len(record['inventory']['visual_transcribed_units']), 455)
        self.assertEqual(len(record['inventory']['page_inventory']), 455)


class ReviewLimitWording(unittest.TestCase):
    def test_a_reading_that_exceeds_the_index_limit_pauses_with_what_to_do_instead_of_retry(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = documents.DocumentStore(Path(temporary.name) / 'documents')
        scope = store.create_scope()

        def reading(context, record, chunks, phase):
            return {'summary': 'A scanned page.', 'acknowledgement': 'Read.', 'relevance': 'relevant', 'relevance_reason': 'It is the process.',
                    'question': '', 'queries': [], 'observations': [], 'questions': [], 'extracted_text': 'The page shows an approval stamp.'}

        service = service_module.DocumentService(store, reading)
        self.addCleanup(lambda: service._worker.join(timeout=4))
        self.addCleanup(service.close)
        record = store.extract(scope, store.add(scope, 'scan.pdf', self.scan())['id'])
        self.assertEqual(record['status'], 'partial', record.get('error'))
        original, documents.MAX_INDEX_BYTES = documents.MAX_INDEX_BYTES, 8
        self.addCleanup(setattr, documents, 'MAX_INDEX_BYTES', original)
        with self.assertRaises(documents.ExtractionError) as refusal:
            store.record_extracted_text(scope, record['id'], record['id'] + '_p1_c1', 'The page shows an approval stamp.')
        self.assertEqual(str(refusal.exception), documents.TRANSCRIPTION_LIMIT_MESSAGE)
        service.session(scope, {})
        end = time.monotonic() + 10
        while time.monotonic() < end:
            analysis = store.get(scope, record['id']).get('analysis') or {}
            if analysis.get('phase') == 'error':
                break
            threading.Event().wait(.01)
        self.assertEqual(analysis.get('error'), documents.TRANSCRIPTION_LIMIT_MESSAGE)
        self.assertIn('Split the file', analysis['error'])
        self.assertNotIn('Revisit to retry', analysis['error'])
        self.assertTrue(analysis['retry_required'])

    @staticmethod
    def scan():
        import io
        PdfWriter = documents.pdf_reader().PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        raw = io.BytesIO()
        writer.write(raw)
        return raw.getvalue()


if __name__ == '__main__':
    unittest.main()
