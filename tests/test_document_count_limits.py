"""A file past a count limit is indexed up to it, and the rest is named in its coverage.

Pages past MAX_PDF_PAGES, sheets past MAX_SHEETS, a CSV's rows past MAX_ROWS and columns past
MAX_COLUMNS, every row after the one that would pass MAX_CELLS, and whatever no longer fits in the
index used to refuse the whole file ("no partial index was published"). Safety limits still refuse.
The limits are patched small here; the stress-lab files (2,020 pages, 450,000 rows) were read
through the same paths.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

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


def pair_csv(rows):
    """Two short cells a row, no header: fifty rows make one section of the index."""
    return ('\n'.join(f'r{row:04}a,r{row:04}b' for row in range(1, rows + 1)) + '\n').encode()


def ledger_xlsx(rows=40, comments=None, sheets=('Ledger',)):
    """Column A filled; B to AD empty but bordered, so each row stores 30 cells and holds one value."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Border, Side
    workbook = Workbook()
    thin = Border(bottom=Side(style='thin'))
    for position, name in enumerate(sheets):
        sheet = workbook.active if position == 0 else workbook.create_sheet()
        sheet.title = name
        for row in range(1, rows + 1):
            sheet.cell(row, 1, f'{name.lower()}entry{row}')
            for column in range(2, 31):
                sheet.cell(row, column).border = thin
    for address, text in (comments or {}).items():
        workbook[sheets[0]][address].comment = Comment(text, 'Analyst')
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def legacy_xlrd(rows, stored, name='Ledger'):
    """A stand-in for xlrd 2.x: one sheet whose rows hold one value and stored empty cells after it."""
    reader = Mock()
    reader.__version__ = '2.0.1'
    sheet = Mock()
    sheet.name, sheet.visibility, sheet.nrows = name, 0, rows
    sheet.row_values.side_effect = lambda row: [f'entry{row + 1}'] + [''] * (stored - 1)
    book = reader.open_workbook.return_value
    book.nsheets = 1
    book.sheet_by_index.return_value = sheet
    return reader


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
        self.assert_cut(record, 'Pages 1 to 2 of 4 were read; the rest did not fit.', 2, 4)
        self.assertEqual(record['chunk_count'], 2)
        self.assertEqual(record['inventory']['pages_read'], 2)
        # Nothing fits: nothing is published, with a reason that is not one an earlier version used.
        with patch.object(documents, 'MAX_CHUNKS', 0):
            refused = self.read('none.pdf', pdf_bytes(2))
        self.assertEqual((refused['status'], refused['error']), ('error', documents.INDEX_FULL_MESSAGE))
        self.assertEqual(self.store.chunks(self.scope, refused['id'])['total'], 0)

    def test_pages_past_the_page_limit_are_not_said_not_to_fit(self):
        # The index fills at page 2, but pages 4 and 5 are past the page limit and were never tried.
        with patch.object(documents, 'MAX_PDF_PAGES', 3), patch.object(documents, 'MAX_CHUNKS', 2):
            record = self.read('both.pdf', pdf_bytes(5))
        self.assert_cut(record, 'Pages 1 to 2 of 5 were read; the rest was not.', 2, 5)


class CsvLimits(Case):
    def test_rows_after_the_cell_limit_are_counted_not_read(self):
        # Three cells a row: rows 1-3 take 9 of 10 cells, row 4 does not fit, rows 4-6 hold 9 more.
        with patch.object(documents, 'MAX_CELLS', 10):
            record = self.read('ledger.csv', csv_bytes(6))
        self.assert_cut(record, 'Rows 1 to 3 of 6 were read; the rest was not.', 3, 6)
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
        self.assert_cut(record, 'Rows 1 to 50 of 120 were read; the rest did not fit.', 50, 120)
        self.assertEqual(record['chunk_count'], 1)
        self.assertEqual(record['inventory']['sheets'][0]['read_to_row'], 50)
        self.assertFalse(self.found(record, 'r51c1'))

    def test_a_fault_after_the_stop_ends_the_count_not_the_file(self):
        content = csv_bytes(6) + b'"quoted"junk,value\n'
        with patch.object(documents, 'MAX_CELLS', 10):
            record = self.read('tail.csv', content)
        self.assertEqual(record['status'], 'partial', record.get('error'))
        self.assertEqual(record['coverage']['read_limit'], 'Rows 1 to 3 were read; the rest was not.')
        self.assertGreater(record['coverage']['total_units'], record['coverage']['indexed_units'])
        # The same fault before the stop still refuses the file, as a broken quote always has.
        refused = self.read('early.csv', b'h1,h2\n"quoted"junk,value\n' + csv_bytes(6))
        self.assertEqual(refused['status'], 'error')
        self.assertIn('invalid', refused['error'])

    def test_rows_read_before_a_stop_that_then_do_not_fit_are_not_called_read(self):
        # Rows 1-50 make the first section. The row limit stops the reading at row 61; the last
        # section, rows 51-60, does not fit. The sentence names the rows the index holds.
        with patch.object(documents, 'MAX_ROWS', 60), patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('rows.csv', pair_csv(100))
        self.assert_cut(record, 'Rows 1 to 50 of 100 were read; the rest was not.', 50, 100)
        self.assertTrue(self.found(record, 'r0050a'))
        self.assertFalse(self.found(record, 'r0055a'))
        # The same after the cell limit (120 cells: rows 1-60).
        with patch.object(documents, 'MAX_CELLS', 120), patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('cells.csv', pair_csv(101))
        self.assert_cut(record, 'Rows 1 to 50 of 101 were read; the rest was not.', 50, 101)
        self.assertNotIn('cells', record['coverage']['read_limit'])
        # The index fills first, at row 51, but rows 111-120 are past the row limit and would not have
        # been read in any case: the rest "was not" read.
        with patch.object(documents, 'MAX_ROWS', 110), patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('long.csv', pair_csv(120))
        self.assert_cut(record, 'Rows 1 to 50 of 120 were read; the rest was not.', 50, 120)
        # When none of the rows before the stop fit, the index is the reason given.
        with patch.object(documents, 'MAX_CELLS', 20), patch.object(documents, 'MAX_CHUNKS', 0):
            refused = self.read('none.csv', pair_csv(30))
        self.assertEqual((refused['status'], refused['error']), ('error', documents.INDEX_FULL_MESSAGE))

    def test_empty_lines_at_the_row_limit_leave_nothing_out(self):
        content = ('\n'.join(f'r{row}' for row in range(1, 6)) + '\n\n').encode()
        with patch.object(documents, 'MAX_ROWS', 5):
            record = self.read('five.csv', content)
        self.assertEqual(record['status'], 'ready')
        self.assertNotIn('read_limit', record['coverage'])
        self.assertEqual((record['coverage']['indexed_units'], record['coverage']['total_units']), (5, 5))
        # A value after the empty line is past the limit as before.
        with patch.object(documents, 'MAX_ROWS', 5):
            record = self.read('seven.csv', content + b'r7\n')
        self.assert_cut(record, 'Rows 1 to 5 of 7 were read; the rest was not.', 5, 7)
        self.assertFalse(self.found(record, 'r7'))

    def test_empty_lines_after_any_stop_are_not_counted_as_rows(self):
        # Ten rows of two cells and an empty last line. The cell limit stops the reading at row 10.
        with patch.object(documents, 'MAX_CELLS', 19):
            record = self.read('ten.csv', pair_csv(10) + b'\n')
        self.assert_cut(record, 'Rows 1 to 9 of 10 were read; the rest was not.', 9, 10)
        # After the index fills: the rows after the stop are counted to the last one that holds a value.
        with patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('index.csv', pair_csv(120) + b'\n\n')
        self.assert_cut(record, 'Rows 1 to 50 of 120 were read; the rest did not fit.', 50, 120)
        # Empty lines read before the index filled at the very end are not rows either.
        with patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('sixty.csv', pair_csv(60) + b'\n\n')
        self.assert_cut(record, 'Rows 1 to 50 of 60 were read; the rest did not fit.', 50, 60)
        # An empty line no longer turns "did not fit" into "was not" by passing the row limit.
        with patch.object(documents, 'MAX_ROWS', 120), patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('limit.csv', pair_csv(120) + b'\n')
        self.assert_cut(record, 'Rows 1 to 50 of 120 were read; the rest did not fit.', 50, 120)


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
        self.assert_cut(record, 'Rows 1 to 2 of Sheet01 were read; the rest of the workbook was not.', 0, 2)
        [sheet] = record['inventory']['sheets']
        self.assertEqual((sheet['name'], sheet['read_to_row'], sheet['rows']), ('Sheet01', 2, 3))
        self.assertEqual((record['inventory']['sheet_count'], record['inventory']['sheets_read']), (2, 1))
        self.assertTrue(self.found(record, 'row-2'))
        self.assertFalse(self.found(record, 'row-3'))

    def test_a_stop_at_the_end_of_a_sheet_names_that_sheet(self):
        with patch.object(documents, 'MAX_CELLS', 6):
            record = self.read('boundary.xlsx', workbook_bytes(sheets=2, rows=3))
        self.assert_cut(record, 'Sheet 1 of 2 was read; the rest was not.', 1, 2)
        self.assertEqual([sheet.get('read_to_row') for sheet in record['inventory']['sheets']], [None, 0])

    def test_a_cut_is_stated_in_rows_not_in_stored_cells(self):
        # 40 rows of 30 stored cells, one of them filled: the 600-cell allowance ends after row 20.
        # A count of cells would say 600 were read and 600 were not, for 20 values each.
        with patch.object(documents, 'MAX_CELLS', 600):
            record = self.read('ledger.xlsx', ledger_xlsx())
        self.assert_cut(record, 'Rows 1 to 20 of Ledger were read; the rest of the workbook was not.', 0, 1)
        sheet = record['inventory']['sheets'][0]
        self.assertEqual((sheet['read_to_row'], sheet['rows'], sheet['populated_cells']), (20, 40, 20))
        self.assertTrue(self.found(record, 'ledgerentry20'))
        self.assertFalse(self.found(record, 'ledgerentry21'))

    def test_a_cut_in_a_later_sheet_names_the_sheets_read_before_it(self):
        with patch.object(documents, 'MAX_CELLS', 10):
            record = self.read('three.xlsx', workbook_bytes(sheets=3, rows=3))
        self.assert_cut(record, 'Sheet 1 and rows 1 to 2 of Sheet02 were read; the rest of the workbook was not.', 1, 3)

    def test_rows_past_the_row_limit_are_read_up_to_it(self):
        # As in a CSV: not refused as rows that "repeat or are out of order".
        with patch.object(documents, 'MAX_ROWS', 2):
            record = self.read('rows.xlsx', workbook_bytes(sheets=2, rows=3))
        self.assert_cut(record, 'Rows 1 to 2 of Sheet01 were read; the rest of the workbook was not.', 0, 2)
        [sheet] = record['inventory']['sheets']
        self.assertEqual((sheet['read_to_row'], sheet['rows']), (2, 3))
        self.assertTrue(self.found(record, 'row-2'))
        self.assertFalse(self.found(record, 'row-3'))

    def test_chart_only_tabs_before_a_cut_are_not_called_read(self):
        def book(*tabs):
            from openpyxl import Workbook
            from openpyxl.chart import BarChart, Reference
            workbook = Workbook()
            workbook.remove(workbook.active)
            data = None
            for tab in tabs:
                if tab == 'chart':
                    continue
                data = workbook.create_sheet(tab)
                for row in range(1, 21):
                    data.append([f'{tab.lower()}entry{row}', row])
            for position, tab in enumerate(tabs):
                if tab == 'chart':
                    chart = BarChart()
                    chart.add_data(Reference(data, min_col=2, min_row=1, max_row=20))
                    workbook.create_chartsheet(f'Chart{position + 1}', position).add_chart(chart)
            output = io.BytesIO()
            workbook.save(output)
            return output.getvalue()
        # The chart tab is the first tab: only the rows of Data were read.
        with patch.object(documents, 'MAX_CELLS', 21):
            record = self.read('chart.xlsx', book('chart', 'Data'))
        self.assertEqual([sheet.get('kind') for sheet in record['inventory']['sheets']], ['chart_sheet', None])
        self.assert_cut(record, 'Rows 1 to 10 of Data were read; the rest of the workbook was not.', 0, 2)
        # A worksheet and a chart tab before the cut: the chart tab is named apart.
        with patch.object(documents, 'MAX_CELLS', 61):
            record = self.read('mixed.xlsx', book('Ledger', 'chart', 'Data'))
        self.assert_cut(record, 'Sheets 1 to 2 and rows 1 to 10 of Data were read, apart from 1 chart-only tab; '
                                'the rest of the workbook was not.', 1, 3)
        # The same past the sheet limit.
        with patch.object(documents, 'MAX_SHEETS', 2):
            record = self.read('tabs.xlsx', book('chart', 'Ledger', 'Data'))
        self.assert_cut(record, 'Sheets 1 to 2 of 3 were read, apart from 1 chart-only tab; the rest was not.', 1, 3)

    def test_comments_follow_the_rows_read_and_comments_that_do_not_fit_are_named(self):
        # The cell limit stops Ledger after row 20: the comment on row 5 is read with its row, the
        # one on row 30 is left out with its row.
        with patch.object(documents, 'MAX_CELLS', 600):
            record = self.read('notes.xlsx', ledger_xlsx(comments={'A5': 'Checked by treasury', 'A30': 'Approved by controller'}))
        self.assert_cut(record, 'Rows 1 to 20 of Ledger were read; the rest of the workbook was not.', 0, 1)
        self.assertTrue(self.found(record, 'treasury'))
        self.assertFalse(self.found(record, 'controller'))
        # The rows read fill the index: their comment does not fit, and the sentence says so.
        with patch.object(documents, 'MAX_CELLS', 600), patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('full.xlsx', ledger_xlsx(comments={'A5': 'Initialled by the treasurer'}))
        self.assert_cut(record, 'Rows 1 to 20 of Ledger were read, apart from some comments in Ledger; '
                                'the rest of the workbook was not.', 0, 1)
        self.assertFalse(self.found(record, 'treasurer'))
        # Without a cell limit: all cells were read, some comments were not.
        with patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('one.xlsx', ledger_xlsx(rows=10, comments={'A2': 'Countersigned by operations'}))
        self.assert_cut(record, 'Some comments in Ledger did not fit and were not read.', 0, 1)
        with patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('two.xlsx', ledger_xlsx(rows=10, comments={'A2': 'Signed by operations'}, sheets=('Ledger', 'Archive')))
        self.assert_cut(record, 'Sheet 1 of 2 was read, apart from some comments in Ledger; the rest did not fit.', 0, 2)
        self.assertFalse(self.found(record, 'archiveentry1'))

    def test_the_index_and_the_sheet_limit_together(self):
        with patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('two.xlsx', workbook_bytes(sheets=2, rows=3))
        self.assert_cut(record, 'Sheet 1 of 2 was read; the rest did not fit.', 1, 2)
        # Sheet 3 is past the sheet limit and was never tried: the rest "was not" read, whatever filled the index.
        with patch.object(documents, 'MAX_SHEETS', 2), patch.object(documents, 'MAX_CHUNKS', 1):
            record = self.read('three.xlsx', workbook_bytes(sheets=3, rows=3))
        self.assert_cut(record, 'Sheet 1 of 3 was read; the rest was not.', 1, 3)
        # When none of the rows before a stop fit, the index is the reason given.
        with patch.object(documents, 'MAX_CELLS', 4), patch.object(documents, 'MAX_CHUNKS', 0):
            refused = self.read('none.xlsx', workbook_bytes(sheets=1, rows=3))
        self.assertEqual((refused['status'], refused['error']), ('error', documents.INDEX_FULL_MESSAGE))


class LegacyWorkbookLimits(Case):
    def test_a_cut_is_stated_in_rows_not_in_stored_cells(self):
        # Four rows of five stored cells, one of them filled: the 12-cell allowance ends after row 2.
        data = bytes.fromhex('D0CF11E0A1B11AE1') + b'FAKE TEST DATA'
        with (patch.dict(sys.modules, {'xlrd': legacy_xlrd(rows=4, stored=5)}), patch.object(documents, 'MAX_CELLS', 12),
              patch.object(documents.importlib.util, 'find_spec', return_value=True)):
            record = self.read('legacy.xls', data)
        self.assert_cut(record, 'Rows 1 to 2 of Ledger were read; the rest of the workbook was not.', 0, 1)
        self.assertEqual((record['inventory']['sheets'][0]['read_to_row'], record['inventory']['sheets'][0]['rows']), (2, 4))
        self.assertTrue(self.found(record, 'entry2'))
        self.assertFalse(self.found(record, 'entry3'))

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


OLD_PAGES = 'PDF page count exceeds the 500-page limit or is empty; no partial index was published.'
OLD_INDEX = 'Document exceeds the 64 MiB text or 50,000-chunk indexing limit; no partial index was published.'


class EarlierRefusals(Case):
    def saved(self, document_id, **fields):
        """Change the stored record itself, as an earlier version left it; reads still project it."""
        with self.store._db() as db:
            record = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()[0])
            record.update(fields)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), document_id))

    def old_refusal(self, name='library.pdf', error=OLD_PAGES, data=None):
        """A file refused whole by the version before EXTRACTION_VERSION 5, nothing of it indexed."""
        record = self.store.add(self.scope, name, data or f'%PDF-1.4\n%{name}\n%%EOF\n'.encode())
        self.saved(record['id'], status='error', error_code='invalid_file', retryable=False, extraction_version=4, error=error)
        return self.store.get(self.scope, record['id'])

    def card(self, record):
        """What the real web/documents.js shows on the Assets card of this record."""
        node = os.environ.get('NODE') or shutil.which('node')
        if not node:
            self.skipTest('Node.js renders the card: put it on PATH or set NODE to it')
        path = Path(self.temporary.name) / 'record.json'
        path.write_text(json.dumps(record), encoding='utf-8')
        script = Path(__file__).resolve().parent / 'test_documents_count_refusal_card.cjs'
        return json.loads(subprocess.run([node, str(script), '--record', str(path)], capture_output=True, text=True,
                                         timeout=60, check=True).stdout)

    def retry(self, record):
        """Retry review (revisit), as the card's button does, until this version has read the file again."""
        manager = service_module.DocumentService(self.store, lambda *args: self.fail('No provider review is expected'))
        self.addCleanup(lambda: manager._worker.join(timeout=5))
        self.addCleanup(manager.close)
        manager.action(self.scope, record['id'], 'revisit')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and self.store.get(self.scope, record['id'])['status'] in ('pending', 'indexing'):
            threading.Event().wait(.01)
        return self.store.get(self.scope, record['id'])

    def test_an_old_refusal_is_offered_retry_review_and_not_a_re_index(self):
        read = self.old_refusal()
        self.assertEqual((read['status'], read['error'], read['retryable']), ('error', documents.COUNT_LIMIT_RETRY, True))
        # Nothing of it was indexed, so there is no earlier index to confirm or re-index.
        self.assertFalse(read['extraction_needs_reindex'])
        self.assertNotIn('reindex_check', read)
        self.assertEqual(read['coverage']['limitations'], [])
        self.assertEqual(read['analysis'], {})
        # update() writes back the record as read, so a build without this rule may have saved its
        # re-index projection with the record. It is taken back out.
        self.saved(read['id'], error=documents.COUNT_LIMIT_RETRY, retryable=True, extraction_needs_reindex=True,
                   coverage={'indexed_units': 0, 'total_units': 0, 'limitations': [documents.REINDEX_NOTICE]},
                   analysis={'phase': 'reindex_required', 'review_complete': False, 'intent_version': 2})
        read = self.store.get(self.scope, read['id'])
        self.assertEqual((read['error'], read['retryable'], read['extraction_needs_reindex']), (documents.COUNT_LIMIT_RETRY, True, False))
        self.assertEqual(read['coverage']['limitations'], [])
        self.assertEqual(read['analysis'], {'review_complete': False, 'intent_version': 2})
        # A refusal that left an earlier index in place (a re-index whose stored visual readings no
        # longer fit) is that index's case: it keeps its reason and needs the re-index.
        other = self.store.add(self.scope, 'indexed.pdf', b'%PDF-1.4\n%indexed\n%%EOF\n')
        self.saved(other['id'], status='error', retryable=False, extraction_version=4, error=OLD_INDEX, chunk_count=3)
        read = self.store.get(self.scope, other['id'])
        self.assertEqual((read['error'], read['retryable'], read['extraction_needs_reindex']), (OLD_INDEX, False, True))

    def test_the_card_of_an_old_refusal_shows_the_button_it_names(self):
        # The record as the store returns it, rendered by the real web/documents.js.
        seen = self.card(self.old_refusal())
        self.assertEqual(seen['status'], 'Could not read file')
        self.assertIsNone(seen['detail'], 'No line says the file was indexed: nothing of it was')
        self.assertEqual(seen['warnings'], [documents.COUNT_LIMIT_RETRY], 'One instruction')
        self.assertIn('Retry review', seen['buttons'])
        self.assertNotIn('Re-index and review', seen['buttons'])
        self.assertIsNone(seen['cost_note'])
        self.assertNotIn('Indexed by an earlier version', seen['text'])

    def test_a_retry_that_fails_again_is_this_version_s_failure_and_no_re_index(self):
        # The retry reads the file with this version, and this version cannot read it either. The record
        # keeps its earlier extraction_version (nothing was indexed), but it is not then described as
        # indexed by an earlier version, nor told to choose a Re-index button that is not shown.
        empty_pdf = self.old_refusal()
        cells = self.old_refusal('ledger.csv', 'A sheet exceeds two million populated cells; no partial index was published.',
                                 csv_bytes(6))
        # The first row of the CSV is past a one-cell limit: this version reads nothing of it.
        for old, max_cells in ((empty_pdf, documents.MAX_CELLS), (cells, 1)):
            with self.subTest(old['name']), patch.object(documents, 'MAX_CELLS', max_cells):
                self.assertEqual((old['error'], old['retryable']), (documents.COUNT_LIMIT_RETRY, True))
                failed = self.retry(old)
                self.assertEqual((failed['status'], failed['retryable'], failed['extraction_version']), ('error', False, 4))
                self.assertNotIn(failed['error'], [documents.COUNT_LIMIT_RETRY, *documents.COUNT_LIMIT_REFUSALS])
                self.assertFalse(failed['extraction_needs_reindex'])
                self.assertNotEqual((failed.get('analysis') or {}).get('phase'), 'reindex_required')
                self.assertNotIn(documents.REINDEX_NOTICE, failed['coverage']['limitations'])
                seen = self.card(failed)
                self.assertEqual(seen['status'], 'Could not read file')
                self.assertIsNone(seen['detail'])
                self.assertEqual(seen['warnings'], [failed['error']], 'Its own reason, and no instruction beside it')
                self.assertFalse({'Retry review', 'Re-index and review'} & set(seen['buttons']), seen['buttons'])
                self.assertIsNone(seen['cost_note'])
                self.assertNotRegex(seen['text'], 'Indexed by an earlier version|Re-index')
        self.assertEqual(self.store.get(self.scope, cells['id'])['error'], documents.NOTHING_READ_MESSAGE)

    def test_an_earlier_index_that_cannot_be_read_again_names_no_missing_button(self):
        # An earlier index is kept beside a failed re-index. The card says so, and names no button it does not show.
        record = self.store.add(self.scope, 'scan.pdf', b'%PDF-1.4\n%scan\n%%EOF\n')
        self.saved(record['id'], status='error', error_code='invalid_file', retryable=False, extraction_version=4,
                   error=documents.CARRIED_TOO_LARGE_MESSAGE, chunk_count=3)
        read = self.store.get(self.scope, record['id'])
        self.assertTrue(read['extraction_needs_reindex'])
        seen = self.card(read)
        self.assertEqual((seen['status'], seen['detail']), ('Could not read file', 'Indexed by an earlier version; not counted.'))
        self.assertEqual(seen['warnings'], [documents.CARRIED_TOO_LARGE_MESSAGE])
        self.assertFalse({'Retry review', 'Re-index and review'} & set(seen['buttons']), seen['buttons'])
        self.assertIsNone(seen['cost_note'])
        self.assertNotIn('Re-index', seen['text'])

    def test_a_failure_that_can_be_read_again_names_only_the_button_its_card_shows(self):
        # A reading that stopped (the reader process was ended from outside) or could not be stored. With an
        # index from an earlier version the card offers Re-index and review, not Retry review, so the
        # file's own reason names no button; the line about the update names the one shown.
        buttons = ('Retry review', 'Re-index and review', 'Revisit this file', 'Read again')
        earlier = {'reading_stopped': 'Reading this file stopped before it finished. Select Retry review.',
                   'storage_unavailable': 'Local storage could not publish the index. Check free disk space and access, '
                                          'then select Retry review.'}
        current = {'reading_stopped': documents.READING_STOPPED_MESSAGE,
                   'storage_unavailable': documents.STORAGE_UNAVAILABLE_MESSAGE}
        for code, saved_error in earlier.items():
            for version in (4, documents.EXTRACTION_VERSION):
                with self.subTest(code=code, version=version):
                    record = self.store.add(self.scope, f'{code}-{version}.csv', csv_bytes(3 + version))
                    self.saved(record['id'], status='error', error_code=code, retryable=True, extraction_version=version,
                               error=saved_error, chunk_count=1)
                    read = self.store.get(self.scope, record['id'])
                    self.assertEqual(read['error'], current[code], 'An earlier wording is read as the current one')
                    self.assertEqual(read['extraction_needs_reindex'], version < documents.EXTRACTION_VERSION)
                    seen = self.card(read)
                    self.assertEqual(seen['status'], 'Could not read file')
                    shown = 'Re-index and review' if version < documents.EXTRACTION_VERSION else 'Retry review'
                    self.assertIn(shown, seen['buttons'])
                    for warning in seen['warnings']:
                        named = {button for button in buttons if button in warning}
                        self.assertLessEqual(named, set(seen['buttons']), warning)
                    self.assertEqual(sum(shown in warning for warning in seen['warnings']),
                                     int(shown == 'Re-index and review'), seen['warnings'])

    def test_an_old_index_full_refusal_can_be_retried(self):
        read = self.old_refusal('large.pdf', OLD_INDEX)
        self.assertEqual((read['error'], read['retryable'], read['extraction_needs_reindex']), (documents.COUNT_LIMIT_RETRY, True, False))

    def test_a_re_index_whose_saved_visual_readings_do_not_fit_gives_its_own_reason(self):
        # The one refusal of this version that the old index-full wording described. It must not read
        # as an earlier refusal, or each retry would offer the next.
        chunks = documents._Chunks({'id': 'doc_scan'})
        chunks.add('p1', 'scan.pdf · page 1', 'PDF page contains no extractable text. Native visual review is required.',
                   {'page': 1, 'requires_vision': True, 'origin': 'visual_placeholder'})
        saved = [{'id': 'doc_scan_p1_c1', 'text': 'Transcribed approval matrix. ' * 8,
                  'location': json.dumps({'page': 1, 'origin': 'ai_visual_transcription'})}]
        with patch.object(documents, 'MAX_INDEX_BYTES', 150), self.assertRaises(documents.ExtractionError) as raised:
            documents._carry_transcriptions(saved, chunks, {}, {})
        self.assertEqual(str(raised.exception), documents.CARRIED_TOO_LARGE_MESSAGE)
        self.assertNotIn(str(raised.exception), documents.COUNT_LIMIT_REFUSALS)
        self.assertNotEqual(str(raised.exception), documents.COUNT_LIMIT_RETRY)

    def test_a_file_an_earlier_version_refused_for_a_count_limit_can_be_retried(self):
        record = self.store.add(self.scope, 'ledger.csv', csv_bytes(6))
        old = 'A sheet exceeds two million populated cells; no partial index was published.'
        self.store.update(self.scope, record['id'], {'status': 'error', 'error_code': 'invalid_file', 'retryable': False, 'error': old})
        self.saved(record['id'], extraction_version=4)
        read = self.store.get(self.scope, record['id'])
        self.assertEqual((read['retryable'], read['error'], read['extraction_needs_reindex']), (True, documents.COUNT_LIMIT_RETRY, False))
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
        self.assertEqual((retried['extraction_version'], retried['extraction_needs_reindex']), (documents.EXTRACTION_VERSION, False))
        self.assertEqual(retried['coverage']['read_limit'], 'Rows 1 to 3 of 6 were read; the rest was not.')

    def test_no_refusal_this_version_gives_reads_as_an_earlier_count_limit_refusal(self):
        # Every earlier refusal a retry would read again is named only in COUNT_LIMIT_REFUSALS itself:
        # no code of this version can refuse a file with it, so a retry cannot be offered in a loop.
        root = Path(__file__).resolve().parents[1]
        self.assertIn(OLD_INDEX, documents.COUNT_LIMIT_REFUSALS)
        listed = re.compile(r'^COUNT_LIMIT_REFUSALS = frozenset\(\(\n.*?^\)\)$', re.M | re.S)
        sources = {path.name: path.read_text(encoding='utf-8') for path in [*root.glob('*.py'), *root.glob('desktop/*.py')]}
        self.assertEqual(len(listed.findall(sources['documents.py'])), 1)
        sources['documents.py'] = listed.sub('', sources['documents.py'])
        self.assertGreater(len(sources), 10)
        for message in documents.COUNT_LIMIT_REFUSALS:
            for name, source in sources.items():
                self.assertNotIn(message, source, name)
        # The sentence a retryable record is given is written only where it is defined.
        self.assertEqual(sum(source.count(documents.COUNT_LIMIT_RETRY) for source in sources.values()), 1)
        # The other refusals that can leave nothing indexed have their own wording too.
        for message in (documents.INDEX_FULL_MESSAGE, documents.NOTHING_READ_MESSAGE, documents.CARRIED_TOO_LARGE_MESSAGE):
            self.assertNotIn(message, documents.COUNT_LIMIT_REFUSALS)

    def test_the_refusal_when_nothing_fits_is_plain(self):
        for word in ('MiB', '50,000', 'section', 'index'):
            self.assertNotIn(word, documents.INDEX_FULL_MESSAGE)


class ContextOfACutFile(Case):
    def test_a_file_read_up_to_a_limit_is_never_given_as_complete_text(self):
        with patch.object(documents, 'MAX_ROWS', 4):
            record = self.read('rows.csv', csv_bytes(7))
        self.store.update(self.scope, record['id'], {'analysis': {'phase': 'complete', 'disposition': 'relevant', 'summary': 'Rows.'}})
        manager = service_module.DocumentService(self.store, lambda *args: self.fail('No review is expected'))
        self.addCleanup(lambda: manager._worker.join(timeout=5))
        self.addCleanup(manager.close)
        [document] = manager.supporting_context(self.scope, 'r3c1')['documents']
        # Every section of the index is supplied, and the index is not the whole file.
        self.assertTrue(document['context_coverage']['all_indexed_sections_supplied'])
        self.assertFalse(document['context_coverage']['complete_text'])
        self.assertEqual(document['context_coverage']['selection'], 'selected excerpts')
        self.assertIn('Rows 1 to 4 of 7 were read; the rest was not.', document['review']['limitations'])
        self.assertEqual(document['context_coverage']['read_limit'], 'Rows 1 to 4 of 7 were read; the rest was not.')

    def test_a_sheet_read_up_to_a_limit_is_given_with_its_indexed_text(self):
        # A one-sheet workbook cut at a cell limit had been given to the interviewer as 0 of 1 units of
        # indexed text, beside the excerpts of that very sheet. Its rows up to the limit are indexed text;
        # the read limit says where the reading stopped.
        manager = service_module.DocumentService(self.store, lambda *args: self.fail('No review is expected'))
        self.addCleanup(lambda: manager._worker.join(timeout=5))
        self.addCleanup(manager.close)
        with patch.object(documents, 'MAX_CELLS', 600):
            workbook = self.read('ledger.xlsx', ledger_xlsx())
        with patch.object(documents, 'MAX_COLUMNS', 2):
            wide = self.read('wide.csv', csv_bytes(4))
        data = bytes.fromhex('D0CF11E0A1B11AE1') + b'FAKE TEST DATA'
        with (patch.dict(sys.modules, {'xlrd': legacy_xlrd(rows=4, stored=5)}), patch.object(documents, 'MAX_CELLS', 12),
              patch.object(documents.importlib.util, 'find_spec', return_value=True)):
            legacy = self.read('legacy.xls', data)
        whole = self.read('whole.xlsx', ledger_xlsx(rows=3))
        for record, native, indexed, total in ((workbook, 1, 0, 1), (wide, 4, 0, 4), (legacy, 1, 0, 1), (whole, 1, 1, 1)):
            with self.subTest(record['name']):
                coverage = record['coverage']
                self.assertEqual((coverage.get('text_indexed_units'), coverage['indexed_units'], coverage['total_units']),
                                 (native, indexed, total))
                self.store.update(self.scope, record['id'], {'analysis': {'phase': 'complete', 'disposition': 'relevant', 'summary': 'Rows.'}})
                context = manager.supporting_context(self.scope, 'entry1', required_documents=[record['id']])
                [document] = [entry for entry in context['documents'] if entry['id'] == record['id']]
                self.assertEqual((document['review']['native_text_units'], document['review']['total_units']), (native, total))
                self.assertTrue(document['context_coverage']['all_indexed_sections_supplied'])
                cut = record is not whole
                self.assertEqual('read_limit' in document['context_coverage'], cut)
                self.assertEqual(document['context_coverage']['complete_text'], not cut)
        # Every unit then has indexed text and all of it is supplied: the notice keeps a read limit apart.
        self.assertIn('context_coverage has no read_limit, do not call the text coverage incomplete', context['notice'])
        self.assertIn('read_limit says where the reading of a file stopped', context['notice'])

    def test_the_first_notes_read_in_parts_never_give_a_cut_file_as_complete(self):
        # file_parts reads all of the index in parallel parts, and of a cut file that is not the whole file.
        parts_spec = importlib.util.spec_from_file_location('collector_file_parts_count_limits',
                                                            Path(__file__).resolve().parents[1] / 'file_parts.py')
        file_parts = importlib.util.module_from_spec(parts_spec)
        parts_spec.loader.exec_module(file_parts)
        manager = service_module.DocumentService(self.store, lambda *args: self.fail('No review is expected'))
        self.addCleanup(lambda: manager._worker.join(timeout=5))
        self.addCleanup(manager.close)
        with patch.object(documents, 'MAX_ROWS', 300):
            cut = self.read('cut.csv', csv_bytes(400))
        whole = self.read('whole.csv', csv_bytes(300))
        sentence = 'Rows 1 to 300 of 400 were read; the rest was not.'
        self.assertEqual(cut['coverage']['read_limit'], sentence)
        for record, complete in ((cut, False), (whole, True)):
            self.store.update(self.scope, record['id'], {'analysis': {'phase': 'complete', 'disposition': 'relevant', 'summary': 'Rows.'}})
            supporting = manager.supporting_context(self.scope, 'r3c1', required_documents=[record['id']])
            supporting = {**supporting, 'documents': [entry for entry in supporting['documents'] if entry['id'] == record['id']]}
            sections = manager.whole_sections(self.scope, record['id'], file_parts.MAX_FILE_CHARS)
            reading = file_parts.plan(supporting, {record['id']: sections})
            self.assertIsNotNone(reading, 'The file is read in parts')
            [entry] = reading['supporting']['documents']
            coverage = entry['context_coverage']
            self.assertEqual((coverage['complete_text'], coverage['all_indexed_sections_supplied']), (complete, True))
            self.assertEqual(coverage['selection'], 'whole file' if complete else file_parts.CUT_SELECTION)
            self.assertEqual(coverage.get('read_limit'), None if complete else sentence)
            # The reply schemas name the fact topics of capture_facts, which sits beside file_parts.
            with patch.dict(sys.modules), patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1]), *sys.path]):
                payload, suffix, _ = file_parts.sweep_request(reading, {'context': {}, 'turns': []})
                parts = file_parts.part_requests(reading, {'context': {}, 'turns': []})
            [swept] = payload['supporting_documents']['documents']
            self.assertEqual(len(swept['excerpts']), len(sections), 'The sweep reads all of the index')
            self.assertEqual(swept['context_coverage']['complete_text'], complete)
            self.assertEqual(file_parts.SWEEP_CUT_NOTE in suffix, not complete)
            for part, _, _, _ in parts:
                self.assertFalse(part['supporting_documents']['documents'][0]['context_coverage']['complete_text'])


if __name__ == '__main__':
    unittest.main()
