"""Local document trust boundaries and complete-corpus regression fixtures."""
import concurrent.futures
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from xml.sax.saxutils import escape

spec = importlib.util.spec_from_file_location('collector_documents', Path(__file__).resolve().parents[1] / 'documents.py')
documents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(documents)


def workbook_bytes(sheets=1, rows=3, formulas=False):
    """Minimal OOXML fixture, not an authored user workbook."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, sheets + 1)) + '</Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="Sheet{i:02}" sheetId="{i}" r:id="rId{i}"/>' for i in range(1, sheets + 1)) + '</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, sheets + 1)) + '</Relationships>')
        for index in range(1, sheets + 1):
            values = []
            for number in range(1, rows + 1):
                marker = 'NeedleLastSheet' if index == sheets and number == rows else f'row-{number}'
                cells = f'<c r="A{number}" t="inlineStr"><is><t>{escape(marker)}</t></is></c><c r="B{number}" t="inlineStr"><is><t>sheet-{index}</t></is></c>'
                if formulas and number == 2:
                    cells += '<c r="C2"><f>1+2</f><v>3</v></c><c r="D2"><f>2+2</f><v></v></c>'
                values.append(f'<row r="{number}">{cells}</row>')
            archive.writestr(f'xl/worksheets/sheet{index}.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:XFD1048576"/><sheetData>' + ''.join(values) + '</sheetData></worksheet>')
    return output.getvalue()


class DocumentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'documents'
        self.store = documents.DocumentStore(self.root)
        self.scope = self.store.create_scope()

    def tearDown(self):
        self.temporary.cleanup()

    def add_csv(self, content=b'name,value\nalpha,42\n', **kwargs):
        return self.store.add(self.scope, 'sample.csv', content, **kwargs)

    def test_original_and_atomic_metadata_survive_reload_with_private_permissions(self):
        record = self.add_csv(context={'latest_question': 'Which tracker?', 'turns': [{'id': 'u1', 'role': 'user', 'text': 'This one.'}], 'OPENAI_API_KEY': 'must-not-store'})
        self.assertEqual(record['status'], 'pending')
        reopened = documents.DocumentStore(self.root)
        self.assertEqual(reopened.pending(self.scope)[0]['id'], record['id'])
        self.assertNotIn('OPENAI_API_KEY', json.dumps(reopened.get(self.scope, record['id'])))
        original = reopened.original_path(self.scope, record['id'])
        self.assertEqual(original.read_bytes(), b'name,value\nalpha,42\n')
        self.assertEqual(stat.S_IMODE(original.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(original.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.root / 'documents.sqlite3').stat().st_mode), 0o600)
        self.assertNotIn(self.scope.encode(), (self.root / 'documents.sqlite3').read_bytes())
        self.assertNotIn('path', json.dumps(record))

    def test_every_read_write_and_source_access_is_scope_authorized(self):
        record = self.add_csv()
        self.store.extract(self.scope, record['id'])
        source = self.store.chunks(self.scope, record['id'])['chunks'][0]['id']
        other = self.store.create_scope()
        calls = [lambda: self.store.get(other, record['id']), lambda: self.store.update(other, record['id'], {'notes': 'x'}),
                 lambda: self.store.extract(other, record['id']), lambda: self.store.archive(other, record['id']),
                 lambda: self.store.original_path(other, record['id']), lambda: self.store.chunks(other, record['id']),
                 lambda: self.store.search(other, 'alpha', ids=[record['id']]),
                 lambda: self.store.record_extracted_text(other, record['id'], source, 'private')]
        for call in calls:
            with self.assertRaises(PermissionError):
                call()
        self.assertEqual(self.store.search(other, 'alpha'), [])
        with self.assertRaises(PermissionError):
            self.store.list('guessed-token')

    def test_csv_all_rows_and_long_tail_are_searchable_with_coordinates(self):
        content = ('column,value\n' + ''.join(f'row{i},v{i}\n' for i in range(1, 2501)) + 'tail,UniqueRow2502\n').encode()
        record = self.add_csv(content)
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['inventory']['rows'], 2502)
        hit = self.store.search(self.scope, 'UniqueRow2502')[0]
        self.assertEqual(hit['row_end'], 2502)
        self.assertIn('B2502=UniqueRow2502', hit['text'])
        first = self.store.chunks(self.scope, record['id'], limit=1)
        self.assertGreater(first['total'], 1)
        self.assertEqual(first['next_offset'], 1)

    def test_malformed_csv_quoting_fails_without_publishing_partial_content(self):
        for content in (b'header,value\n"unfinished,value', b'header,value\n"quoted"junk,value\n'):
            with self.subTest(content=content):
                record = self.add_csv(content)
                result = self.store.extract(self.scope, record['id'])
                self.assertEqual(result['status'], 'error')
                self.assertIn('invalid', result['error'])
                self.assertEqual(self.store.chunks(self.scope, record['id'])['total'], 0)
                self.assertEqual(self.store.original_path(self.scope, record['id']).read_bytes(), content)

    def test_archive_is_reversible_and_never_deletes_original_or_index(self):
        record = self.add_csv()
        self.store.extract(self.scope, record['id'])
        path = self.store.original_path(self.scope, record['id'])
        self.store.remove(self.scope, record['id'])
        self.assertEqual(self.store.list(self.scope), [])
        self.assertEqual(self.store.search(self.scope, 'alpha'), [])
        self.assertTrue(path.exists())
        self.assertEqual(len(self.store.list(self.scope, include_archived=True)), 1)
        self.store.archive(self.scope, record['id'], False)
        self.assertTrue(self.store.search(self.scope, 'alpha'))

    def test_size_count_type_and_huge_cell_limits_fail_explicitly(self):
        with patch.object(documents, 'MAX_FILE_BYTES', 10), self.assertRaises(documents.DocumentError):
            self.add_csv(b'x' * 11)
        with self.assertRaises(documents.DocumentError):
            self.store.add(self.scope, 'run.exe', b'code')
        with patch.object(documents, 'MAX_FILES_PER_SCOPE', 1):
            self.add_csv()
            with self.assertRaises(documents.DocumentError):
                self.add_csv()
        record = self.add_csv(b'header\n' + b'z' * 30)
        with patch.object(documents, 'MAX_CELL_CHARS', 20):
            result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('cell exceeds', result['error'])
        self.assertEqual(self.store.chunks(self.scope, record['id'])['total'], 0)

    def test_search_quotes_untrusted_fts_syntax_and_never_changes_database(self):
        record = self.add_csv()
        self.store.extract(self.scope, record['id'])
        self.assertEqual(self.store.search(self.scope, '" OR scope:*; DROP TABLE documents'), [])
        self.assertEqual(self.store.get(self.scope, record['id'])['status'], 'ready')
        self.assertTrue(self.store.search(self.scope, 'alpha'))

    def test_concurrent_metadata_changes_merge_without_losing_other_fields(self):
        record = self.add_csv()
        second = documents.DocumentStore(self.root)
        def update(index):
            store = self.store if index % 2 else second
            return store.update(self.scope, record['id'], {'analysis' if index % 2 else 'notes': {'pass': index}})
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(update, range(20)))
        result = self.store.get(self.scope, record['id'])
        self.assertIn('pass', result['analysis'])
        self.assertIn('pass', result['notes'])
        self.assertEqual(result['revision'], 20)
        with self.assertRaises(documents.DocumentError):
            self.store.update(self.scope, record['id'], {'id': 'replace-identity'})

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'Existing openpyxl runtime required')
    def test_all_fifty_tabs_and_rows_after_one_thousand_are_indexed(self):
        record = self.store.add(self.scope, 'fifty-tabs.xlsx', workbook_bytes(sheets=50, rows=1205))
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'ready', result.get('error'))
        self.assertEqual(result['inventory']['sheet_count'], 50)
        self.assertEqual(result['inventory']['rows'], 50 * 1205)
        self.assertTrue(all(sheet['rows'] == 1205 for sheet in result['inventory']['sheets']))
        self.assertTrue(all(sheet['columns'] == 2 and sheet['header_sample'] for sheet in result['inventory']['sheets']))
        self.assertLessEqual(len(json.dumps(result['inventory']).encode()), documents.MAX_INVENTORY_BYTES)
        hits = self.store.search(self.scope, 'NeedleLastSheet')
        self.assertEqual(hits[0]['sheet'], 'Sheet50')
        self.assertEqual(hits[0]['row_end'], 1205)
        self.assertIn('A1205=NeedleLastSheet', hits[0]['text'])

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'Existing openpyxl runtime required')
    def test_formulas_and_saved_values_are_flagged_and_never_executed(self):
        record = self.store.add(self.scope, 'formula.xlsm', workbook_bytes(formulas=True))
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['inventory']['formula_cells'], 2)
        self.assertEqual(result['inventory']['sheets'][0]['formulas_without_cached_values'], 1)
        text = '\n'.join(item['text'] for item in self.store.chunks(self.scope, record['id'])['chunks'])
        self.assertIn('FORMULA (not executed) =1+2', text)
        self.assertIn('cached value (not recalculated): 3', text)
        self.assertIn('UNAVAILABLE', text)
        self.assertFalse(result['inventory']['macros_executed'])

    def test_zip_bomb_and_xml_entities_are_rejected_without_partial_index(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('xl/worksheets/bomb.xml', 'z' * 2_000_000)
        record = self.store.add(self.scope, 'bomb.xlsx', output.getvalue())
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('compression-ratio', result['error'])
        self.assertEqual(self.store.chunks(self.scope, record['id'])['total'], 0)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('xl/workbook.xml', '<!DOCTYPE x [<!ENTITY y SYSTEM "file:///secret">]><x/>')
        record = self.store.add(self.scope, 'entity.xlsx', output.getvalue())
        self.assertIn('external entities', self.store.extract(self.scope, record['id'])['error'])

    def test_legacy_xls_dependency_gap_is_explicit_and_original_is_kept(self):
        record = self.store.add(self.scope, 'legacy.xls', b'not actually parsed without xlrd')
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('original', result['error'].lower())
        self.assertTrue(self.store.original_path(self.scope, record['id']).exists())

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Existing Pillow runtime required')
    def test_png_verification_and_native_visual_text_are_scoped_and_searchable(self):
        from PIL import Image
        output = io.BytesIO()
        Image.new('RGB', (20, 30), 'white').save(output, format='PNG')
        record = self.store.add(self.scope, 'scan.png', output.getvalue())
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'partial')
        source = self.store.chunks(self.scope, record['id'])['chunks'][0]
        self.assertTrue(source['requires_vision'])
        reviewed = self.store.record_extracted_text(self.scope, record['id'], source['id'], 'NativeVisualNeedle ' + 'x' * 12000 + ' finalVisionTail')
        self.assertEqual(reviewed['coverage']['indexed_units'], 1)
        self.assertTrue(self.store.search(self.scope, 'finalVisionTail'))
        hit = self.store.search(self.scope, 'NativeVisualNeedle')[0]
        self.assertEqual(hit['origin'], 'ai_visual_transcription')
        self.assertFalse(hit['verified'])
        with self.assertRaises(PermissionError):
            self.store.record_extracted_text(self.scope, record['id'], 'invented_source', 'text')
        invalid = self.store.add(self.scope, 'broken.png', output.getvalue()[:30])
        self.assertEqual(self.store.extract(self.scope, invalid['id'])['status'], 'error')

    @unittest.skipUnless(importlib.util.find_spec('reportlab') and importlib.util.find_spec('pypdf'), 'Existing PDF runtime required')
    def test_all_one_hundred_pdf_pages_are_searchable_with_stable_sources(self):
        from reportlab.pdfgen.canvas import Canvas
        output = io.BytesIO()
        canvas = Canvas(output)
        for number in range(1, 101):
            canvas.drawString(30, 750, 'NeedlePageHundred' if number == 100 else f'Page {number} of the synthetic process')
            canvas.showPage()
        canvas.save()
        record = self.store.add(self.scope, 'hundred.pdf', output.getvalue())
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'ready', result.get('error'))
        self.assertEqual(result['inventory']['pages'], 100)
        self.assertEqual(len(result['inventory']['page_inventory']), 100)
        self.assertIn('NeedlePageHundred', result['inventory']['page_inventory'][-1]['sample'])
        hit = self.store.search(self.scope, 'NeedlePageHundred')[0]
        self.assertEqual(hit['id'], record['id'] + '_p100_c1')
        self.assertEqual(hit['page'], 100)
        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(io.BytesIO(self.store.page_input(self.scope, record['id'], 100))).pages), 1)

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing pypdf runtime required')
    def test_scanned_and_encrypted_pdfs_never_claim_text_coverage(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        raw = io.BytesIO()
        writer.write(raw)
        record = self.store.add(self.scope, 'scan.pdf', raw.getvalue())
        result = self.store.extract(self.scope, record['id'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['coverage']['indexed_units'], 0)
        self.assertEqual(result['inventory']['vision_pages'], [1])
        chunk = self.store.chunks(self.scope, record['id'])['chunks'][0]
        self.assertTrue(chunk['requires_vision'])
        self.store.record_extracted_text(self.scope, record['id'], chunk['id'], 'Visual page note')
        self.assertEqual(self.store.get(self.scope, record['id'])['coverage']['indexed_units'], 1)
        writer.encrypt('secret-password')
        raw = io.BytesIO()
        writer.write(raw)
        encrypted = self.store.add(self.scope, 'encrypted.pdf', raw.getvalue())
        result = self.store.extract(self.scope, encrypted['id'])
        self.assertEqual(result['status'], 'error')
        self.assertIn('Encrypted', result['error'])
        self.assertEqual(self.store.chunks(self.scope, encrypted['id'])['total'], 0)

    def test_inventory_budget_keeps_every_unit_and_flags_shortened_samples(self):
        inventory = {'pages': 100, 'page_inventory': [
            {'page': number, 'sample': '界' * 180, 'text_chars': 9000, 'requires_vision': False}
            for number in range(1, 101)]}
        result = documents._inventory_budget(inventory)
        self.assertEqual(len(result['page_inventory']), 100)
        self.assertEqual(result['page_inventory'][-1]['page'], 100)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), documents.MAX_INVENTORY_BYTES)
        self.assertIn('summary_limitations', result)


if __name__ == '__main__':
    unittest.main()
