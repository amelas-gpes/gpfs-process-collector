"""A file past a count limit is indexed up to it, and the rest is named in its coverage.

Pages past MAX_PDF_PAGES, sheets past MAX_SHEETS, a CSV's rows past MAX_ROWS and columns past
MAX_COLUMNS, every row after the one that would pass MAX_CELLS, and whatever no longer fits in the
index used to refuse the whole file ("no partial index was published"). Safety limits still refuse.
The limits are patched small here; the stress-lab files (2,020 pages, 450,000 rows) were read
through the same paths.
"""
import importlib.util
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_documents import workbook_bytes

spec = importlib.util.spec_from_file_location('collector_document_service_count_limits', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
import documents


def pdf_bytes(pages):
    from reportlab.pdfgen.canvas import Canvas
    output = io.BytesIO()
    canvas = Canvas(output)
    for number in range(1, pages + 1):
        canvas.drawString(30, 750, f'Fictional procedure page marker{number:03}')
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def csv_bytes(rows, columns=3):
    lines = [','.join(f'h{column}' for column in range(1, columns + 1))]
    lines += [','.join(f'r{row}c{column}' for column in range(1, columns + 1)) for row in range(2, rows + 1)]
    return ('\n'.join(lines) + '\n').encode()


class Case(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()

    def read(self, name, data):
        return self.store.extract(self.scope, self.store.add(self.scope, name, data)['id'])

    def found(self, record, word):
        return [hit for hit in self.store.search(self.scope, word, ids=[record['id']]) if word in hit['text']]

    def assert_cut(self, record, sentence, indexed, total):
        self.assertEqual(record['status'], 'partial', record.get('error'))
        self.assertEqual(record['coverage']['read_limit'], sentence)
        self.assertEqual(record['coverage']['limitations'][0], sentence, 'the cut is the first reading limit')
        self.assertEqual((record['coverage']['indexed_units'], record['coverage']['total_units']), (indexed, total))
        # The review is never called complete: fewer units are indexed than the file has.
        self.assertFalse(service_module.DocumentService._review_complete(record, {}, record['chunk_count'], record['chunk_count']))


@unittest.skipUnless(importlib.util.find_spec('pypdf') and importlib.util.find_spec('reportlab'), 'Existing PDF runtime required')
class PdfPages(Case):
    def test_pages_past_the_limit_are_left_out_and_named(self):
        with patch.object(documents, 'MAX_PDF_PAGES', 3):
            record = self.read('library.pdf', pdf_bytes(5))
        self.assert_cut(record, 'Pages 1 to 3 of 5 were read; the rest was not.', 3, 5)
        self.assertEqual((record['inventory']['pages'], record['inventory']['pages_read']), (5, 3))
        self.assertEqual([unit['page'] for unit in record['inventory']['page_inventory']], [1, 2, 3])
        self.assertEqual(record['coverage']['text_indexed_units'], 3)
        self.assertTrue(self.found(record, 'marker003'))
        self.assertFalse(self.found(record, 'marker004'))
        self.assertEqual(self.store.chunks(self.scope, record['id'])['total'], 3)

    def test_a_file_within_the_limit_is_unchanged(self):
        with patch.object(documents, 'MAX_PDF_PAGES', 3):
            record = self.read('short.pdf', pdf_bytes(3))
        self.assertEqual(record['status'], 'ready')
        self.assertNotIn('read_limit', record['coverage'])
        self.assertNotIn('pages_read', record['inventory'])
        self.assertEqual(record['coverage']['limitations'], [])

    def test_pages_that_no_longer_fit_in_the_index_are_left_out_whole(self):
        with patch.object(documents, 'MAX_CHUNKS', 2):
            record = self.read('index.pdf', pdf_bytes(4))
        self.assert_cut(record, 'Pages 1 to 2 of 4 were read; the rest did not fit in the text index.', 2, 4)
        self.assertEqual(record['chunk_count'], 2)
        self.assertEqual(record['inventory']['pages_read'], 2)
        # Nothing fits: nothing is published, with a reason that is not one an earlier version used.
        with patch.object(documents, 'MAX_CHUNKS', 0):
            refused = self.read('none.pdf', pdf_bytes(2))
        self.assertEqual((refused['status'], refused['error']), ('error', documents.INDEX_FULL_MESSAGE))
        self.assertEqual(self.store.chunks(self.scope, refused['id'])['total'], 0)


class CsvLimits(Case):
    def test_rows_after_the_cell_limit_are_counted_not_read(self):
        # Three cells a row: rows 1-3 take 9 of 10 cells, row 4 does not fit, rows 4-6 hold 9 more.
        with patch.object(documents, 'MAX_CELLS', 10):
            record = self.read('ledger.csv', csv_bytes(6))
        self.assert_cut(record, 'The first 9 cells were read, to row 3; 9 more were not.', 3, 6)
        sheet = record['inventory']['sheets'][0]
        self.assertEqual((sheet['rows'], sheet['read_to_row'], sheet['populated_cells']), (6, 3, 9))
        self.assertEqual(record['inventory']['rows'], 6)
        self.assertTrue(self.found(record, 'r3c3'))
        self.assertFalse(self.found(record, 'r4c1'))

    def test_a_file_at_the_cell_limit_is_read_whole(self):
        with patch.object(documents, 'MAX_CELLS', 18):
            record = self.read('exact.csv', csv_bytes(6))
        self.assertEqual(record['status'], 'ready')
        self.assertNotIn('read_limit', record['coverage'])
        self.assertNotIn('read_to_row', record['inventory']['sheets'][0])
        self.assertEqual((record['coverage']['indexed_units'], record['coverage']['total_units']), (6, 6))

    def test_rows_past_the_row_limit(self):
        with patch.object(documents, 'MAX_ROWS', 4):
            record = self.read('rows.csv', csv_bytes(7))
        self.assert_cut(record, 'Rows 1 to 4 of 7 were read; the rest was not.', 4, 7)
        self.assertFalse(self.found(record, 'r5c1'))

    def test_columns_past_the_column_limit(self):
        content = b'a,b,c,d,FarColumnValue\nkept1,kept2,kept3\n'
        with patch.object(documents, 'MAX_COLUMNS', 3):
            record = self.read('wide.csv', content)
        # The wide row is read in part, so it does not count as indexed; the next row does.
        self.assert_cut(record, 'Columns 1 to 3 of 5 were read; the rest was not.', 1, 2)
        self.assertTrue(self.found(record, 'kept3'))
        self.assertFalse(self.found(record, 'FarColumnValue'))
        self.assertEqual(record['inventory']['sheets'][0]['columns'], 3)

    def test_rows_that_no_longer_fit_in_the_index_are_left_out_whole(self):
        # Fifty rows make a section; the second section does not fit.
        with patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('index.csv', csv_bytes(120))
        self.assert_cut(record, 'Cells were read to row 50; the rest did not fit in the text index.', 50, 120)
        self.assertEqual(record['chunk_count'], 1)
        self.assertEqual(record['inventory']['sheets'][0]['read_to_row'], 50)
        self.assertFalse(self.found(record, 'r51c1'))

    def test_a_fault_after_the_stop_ends_the_count_not_the_file(self):
        content = csv_bytes(6) + b'"quoted"junk,value\n'
        with patch.object(documents, 'MAX_CELLS', 10):
            record = self.read('tail.csv', content)
        self.assertEqual(record['status'], 'partial', record.get('error'))
        self.assertEqual(record['coverage']['read_limit'], 'The first 9 cells were read, to row 3; the rest was not.')
        self.assertGreater(record['coverage']['total_units'], record['coverage']['indexed_units'])
        # The same fault before the stop still refuses the file, as a broken quote always has.
        refused = self.read('early.csv', b'h1,h2\n"quoted"junk,value\n' + csv_bytes(6))
        self.assertEqual(refused['status'], 'error')
        self.assertIn('invalid', refused['error'])


@unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'Existing openpyxl runtime required')
class WorkbookLimits(Case):
    def test_sheets_past_the_sheet_limit(self):
        with patch.object(documents, 'MAX_SHEETS', 2):
            record = self.read('tabs.xlsx', workbook_bytes(sheets=3, rows=3))
        self.assert_cut(record, 'Sheets 1 to 2 of 3 were read; the rest was not.', 2, 3)
        self.assertEqual((record['inventory']['sheet_count'], record['inventory']['sheets_read']), (3, 2))
        self.assertEqual([sheet['name'] for sheet in record['inventory']['sheets']], ['Sheet01', 'Sheet02'])
        self.assertFalse(self.found(record, 'NeedleLastSheet'))

    def test_stored_cells_past_the_limit_stop_the_reading_in_its_sheet(self):
        # Two cells a row, three rows a sheet: rows 1-2 of Sheet01 fit in 5 cells; the rest holds 8.
        with patch.object(documents, 'MAX_CELLS', 5):
            record = self.read('cells.xlsx', workbook_bytes(sheets=2, rows=3))
        self.assert_cut(record, 'The first 4 cells were read, to row 2 of Sheet01; 8 more were not.', 0, 2)
        [sheet] = record['inventory']['sheets']
        self.assertEqual((sheet['name'], sheet['read_to_row'], sheet['rows']), ('Sheet01', 2, 3))
        self.assertEqual((record['inventory']['sheet_count'], record['inventory']['sheets_read']), (2, 1))
        self.assertTrue(self.found(record, 'row-2'))
        self.assertFalse(self.found(record, 'row-3'))

    def test_a_stop_at_the_end_of_a_sheet_names_that_sheet(self):
        with patch.object(documents, 'MAX_CELLS', 6):
            record = self.read('boundary.xlsx', workbook_bytes(sheets=2, rows=3))
        self.assert_cut(record, 'The first 6 cells were read, to the end of Sheet01; 6 more were not.', 1, 2)
        self.assertEqual([sheet.get('read_to_row') for sheet in record['inventory']['sheets']], [None, 0])

    def test_safety_limits_still_refuse_the_whole_file(self):
        output = io.BytesIO()
        import zipfile
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('xl/worksheets/sheet1.xml', 'z' * 2_000_000)
        with patch.object(documents, 'MAX_CELLS', 1):
            bomb = self.read('bomb.xlsx', output.getvalue())
        self.assertEqual(bomb['status'], 'error')
        self.assertIn('compression-ratio', bomb['error'])
        with patch.object(documents, 'MAX_CELLS', 10), patch.object(documents, 'MAX_CELL_CHARS', 5):
            long_cell = self.read('long.csv', b'header\nmuch too long\n')
        self.assertEqual(long_cell['status'], 'error')
        self.assertIn('cell exceeds', long_cell['error'])
        self.assertEqual(self.store.chunks(self.scope, long_cell['id'])['total'], 0)


class EarlierRefusals(Case):
    def test_a_file_an_earlier_version_refused_for_a_count_limit_can_be_retried(self):
        record = self.store.add(self.scope, 'ledger.csv', csv_bytes(6))
        old = 'A sheet exceeds two million populated cells; no partial index was published.'
        self.store.update(self.scope, record['id'], {'status': 'error', 'error_code': 'invalid_file', 'retryable': False, 'error': old})
        read = self.store.get(self.scope, record['id'])
        self.assertEqual((read['retryable'], read['error']), (True, documents.COUNT_LIMIT_RETRY))
        # Other refusals keep their own wording and stay as they were.
        other = self.store.add(self.scope, 'other.csv', b'x\n1\n')
        self.store.update(self.scope, other['id'], {'status': 'error', 'retryable': False, 'error': 'CSV has no populated cells to index.'})
        self.assertFalse(self.store.get(self.scope, other['id'])['retryable'])
        # Retry review (revisit) reads it again, up to the limit.
        calls = []

        def review(context, saved, chunks, phase):
            calls.append(phase)
            raise RuntimeError('No provider review is expected')
        manager = service_module.DocumentService(self.store, review)
        self.addCleanup(lambda: manager._worker.join(timeout=5))
        self.addCleanup(manager.close)
        with patch.object(documents, 'MAX_CELLS', 10):
            manager.action(self.scope, record['id'], 'revisit')
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not calls:
                threading.Event().wait(.01)
        self.assertEqual(calls[:1], ['quick'])
        retried = self.store.get(self.scope, record['id'])
        self.assertEqual(retried['status'], 'partial')
        self.assertEqual(retried['coverage']['read_limit'], 'The first 9 cells were read, to row 3; 9 more were not.')

    def test_no_refusal_this_version_gives_reads_as_an_earlier_count_limit_refusal(self):
        source = (Path(__file__).resolve().parents[1] / 'documents.py').read_text(encoding='utf-8')
        for message in documents.COUNT_LIMIT_REFUSALS:
            self.assertNotIn(message, source.replace(repr(message), ''), message)


if __name__ == '__main__':
    unittest.main()
