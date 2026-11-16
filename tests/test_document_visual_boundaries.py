"""Actual-parser regressions for visual omissions and decoded PDF limits."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('visual_documents', Path(__file__).resolve().parents[1] / 'documents.py')
documents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(documents)
service_spec = importlib.util.spec_from_file_location('visual_document_service', Path(__file__).resolve().parents[1] / 'document_service.py')
service = importlib.util.module_from_spec(service_spec)
service_spec.loader.exec_module(service)


def pdf_bytes(kind='text', pages=1):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, DecodedStreamObject
    writer = PdfWriter()
    for number in range(pages):
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        command = b'BT /F1 12 Tf 20 160 Td (Native process instruction) Tj ET'
        if kind == 'image':
            image = DecodedStreamObject()
            image.set_data(b'\x00\x00\x00\xff\xff\xff')
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'), NameObject('/Width'): NumberObject(2), NameObject('/Height'): NumberObject(1), NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'): writer._add_object(image)})
            command += b' q 100 0 0 50 20 40 cm /Im1 Do Q'
        if kind == 'vector':
            command += b' 20 40 100 50 re S'
        page[NameObject('/Resources')] = resources
        contents = DecodedStreamObject()
        contents.set_data(command)
        page[NameObject('/Contents')] = writer._add_object(contents)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class VisualBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()

    def tearDown(self):
        self.temporary.cleanup()

    def extract(self, name, data):
        record = self.store.add(self.scope, name, data)
        return self.store.extract(self.scope, record['id'])

    def legacy(self, record, archived=False):
        with self.store._db() as db:
            row = db.execute('SELECT record FROM documents WHERE id=?', (record['id'],)).fetchone()
            old = json.loads(row[0])
            old.pop('extraction_version', None)
            old.pop('extraction_needs_reindex', None)
            old.update(status='ready', archived=archived,
                       analysis={'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'cursor': 1})
            encoded = json.dumps(old)
            db.execute('UPDATE documents SET record=? WHERE id=?', (encoded, record['id']))
        return encoded

    def test_legacy_records_lose_coverage_without_startup_retries_or_database_migration(self):
        # Revised with gap-upgrade-1. Reading a record still writes nothing and still projects it
        # cautiously, and a status poll still never starts a paid review. What a poll now does start is
        # one local comparison of the saved index with what the current parser reads. This file's index
        # is one the current parser does not reproduce, so it stays held back and its record keeps
        # everything it had; tests/test_document_reindex_check.py covers the index that is unchanged.
        record = self.extract('legacy.csv', b'stage\nFictionalIntake\n')
        self.assertEqual(record['extraction_version'], documents.EXTRACTION_VERSION)
        encoded = self.legacy(record)
        with self.store._db() as db:
            db.execute("UPDATE chunks SET label='Label written by an earlier parser' WHERE document_id=?", (record['id'],))
        for _ in range(3):
            read = self.store.get(self.scope, record['id'])
            self.assertTrue(read['extraction_needs_reindex'])
            self.assertEqual(read['analysis']['phase'], 'reindex_required')
        with self.store._db() as db:
            self.assertEqual(db.execute('SELECT record FROM documents WHERE id=?', (record['id'],)).fetchone()[0], encoded,
                             'Conservative read projection must not bulk-write private stored records')
        calls = []
        manager = service.DocumentService(self.store, lambda *args: calls.append(args))
        try:
            deadline = time.monotonic() + 15
            while True:
                records = manager.status(self.scope, {})
                self.assertTrue(records[0]['extraction_needs_reindex'])
                self.assertFalse(records[0]['analysis']['review_complete'])
                self.assertEqual(records[0]['coverage']['indexed_units'], 0)
                if records[0]['reindex_check']['outcome'] != 'pending' or time.monotonic() > deadline:
                    break
                threading.Event().wait(.01)
            self.assertEqual(records[0]['reindex_check']['outcome'], 'changed')
            for _ in range(3):
                manager.status(self.scope, {})
            threading.Event().wait(.05)
            self.assertEqual(calls, [], 'Startup/status cannot silently retry paid legacy review')
            context = manager.supporting_context(self.scope, 'FictionalIntake')
            self.assertTrue(context['unconfirmed'])
            self.assertTrue(context['documents'][0]['extraction_needs_reindex'])
            self.assertFalse(context['documents'][0]['review']['review_complete'])
            with self.store._db() as db:
                stored = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (record['id'],)).fetchone()[0])
            # The comparison recorded its outcome, once, and changed nothing else of the stored record.
            self.assertEqual(stored.pop('reindex_check'), {'extraction_version': documents.EXTRACTION_VERSION, 'outcome': 'changed'})
            self.assertEqual(stored.pop('revision'), json.loads(encoded)['revision'] + 1)
            before = json.loads(encoded)
            for key in ('revision', 'updated_at'):
                before.pop(key), stored.pop(key, None)
            self.assertEqual(stored, before)
        finally:
            manager.close()
            manager._worker.join(timeout=2)

    def test_explicit_revisit_reextracts_legacy_original_and_keeps_native_citation(self):
        record = self.extract('legacy.csv', b'stage\nFictionalIntake\n')
        original = self.store.original_path(self.scope, record['id']).read_bytes()
        source = self.store.chunks(self.scope, record['id'])['chunks'][0]
        self.legacy(record)
        calls = []
        def callback(context, current, chunks, phase):
            calls.append(phase)
            return {'summary': 'Fictional native text reviewed.', 'acknowledgement': 'Fictional fixture.', 'relevance': 'relevant',
                    'relevance_reason': 'Fictional fixture.', 'question': '', 'queries': [], 'observations': [], 'questions': [], 'extracted_text': ''}
        manager = service.DocumentService(self.store, callback)
        try:
            before = manager.supporting_context(self.scope, 'FictionalIntake', [source['id']])
            manager.action(self.scope, record['id'], 'revisit')
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                current = self.store.get(self.scope, record['id'])
                if current.get('analysis', {}).get('phase') == 'complete':
                    break
                threading.Event().wait(.01)
            self.assertEqual(current['extraction_version'], documents.EXTRACTION_VERSION)
            self.assertFalse(current['extraction_needs_reindex'])
            self.assertTrue(current['analysis']['review_complete'])
            self.assertEqual(calls, ['quick'])
            self.assertEqual(self.store.source(self.scope, record['id'], source['id'])['text'], source['text'])
            self.assertEqual(self.store.original_path(self.scope, record['id']).read_bytes(), original)
            after = manager.supporting_context(self.scope, 'FictionalIntake', [source['id']])
            self.assertNotEqual(before, after, 'Source state handed to the HTTP freshness gate changes after reindex')
            self.assertNotEqual(before['documents'][0]['source_revision'], after['documents'][0]['source_revision'])
        finally:
            manager.close()
            manager._worker.join(timeout=2)

    def test_failed_legacy_reindex_stays_unreviewed_and_keeps_original(self):
        record = self.extract('legacy.csv', b'stage\nFictionalIntake\n')
        self.legacy(record)
        with patch.object(documents, '_csv', side_effect=documents.ExtractionError('Synthetic parser rejection')):
            current = self.store.extract(self.scope, record['id'])
        self.assertEqual(current['status'], 'error')
        self.assertFalse(self.store.get(self.scope, record['id'])['analysis']['review_complete'])
        self.assertEqual(self.store.search(self.scope, 'FictionalIntake'), [])
        self.assertEqual(self.store.original_path(self.scope, record['id']).read_bytes(), b'stage\nFictionalIntake\n')

    def test_archived_legacy_sources_remain_scoped_retained_evidence_until_explicit_revisit(self):
        record = self.extract('legacy.csv', b'stage\nFictionalIntake\n')
        source = self.store.chunks(self.scope, record['id'])['chunks'][0]
        self.legacy(record, archived=True)
        calls = []
        manager = service.DocumentService(self.store, lambda *args: calls.append(args))
        try:
            self.assertEqual(manager.status(self.scope), [])
            self.assertTrue(self.store.extract(self.scope, record['id'])['archived'])
            with self.assertRaises(PermissionError):
                manager.source(self.scope, record['id'], source['id'])
            with self.assertRaises(PermissionError):
                manager.action(self.store.create_scope(), record['id'], 'revisit')
            context = manager.supporting_context(self.scope, 'FictionalIntake', [source['id']])
            retained = context['retained_evidence'][0]
            self.assertTrue(retained['archived'])
            self.assertTrue(retained['retained_only'])
            self.assertTrue(retained['extraction_needs_reindex'])
            self.assertEqual(retained['text'], source['text'])
            self.assertEqual(calls, [])
        finally:
            manager.close()
            manager._worker.join(timeout=2)

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing PDF runtime required')
    def test_mixed_raster_and_vector_pages_preserve_native_text_and_require_visual_review(self):
        for kind in ('image', 'vector'):
            with self.subTest(kind=kind):
                original = pdf_bytes(kind)
                record = self.extract(kind + '.pdf', original)
                self.assertEqual(record['status'], 'partial')
                self.assertEqual(record['coverage']['indexed_units'], 0)
                self.assertEqual(record['inventory']['mixed_visual_pages'], [1])
                chunks = self.store.chunks(self.scope, record['id'])['chunks']
                native = next(c for c in chunks if not c.get('requires_vision'))
                visual = next(c for c in chunks if c.get('requires_vision'))
                self.assertIn('Native process instruction', native['text'])
                self.assertEqual(native['id'], record['id'] + '_p1_c1')
                self.assertFalse(service.DocumentService._review_complete(record, {}, len(chunks), len(chunks)))
                with self.assertRaises(PermissionError):
                    self.store.record_extracted_text(self.store.create_scope(), record['id'], visual['id'], 'Forged visual content')
                updated = self.store.record_extracted_text(self.scope, record['id'], visual['id'], 'Synthetic visual interpretation')
                revision_before = service.DocumentService._source_revision(record)
                revision_after = service.DocumentService._source_revision(updated)
                self.assertNotEqual(revision_before, revision_after)
                self.assertEqual(updated['coverage']['indexed_units'], 1, 'Native text plus visual interpretation is still one page')
                self.assertEqual(self.store.source(self.scope, record['id'], native['id'])['text'], native['text'])
                visual_result = self.store.source(self.scope, record['id'], visual['id'])
                self.assertEqual(visual_result['origin'], 'ai_visual_transcription')
                self.assertFalse(visual_result['verified'])
                self.assertEqual(self.store.original_path(self.scope, record['id']).read_bytes(), original)
                same = self.store.record_extracted_text(self.scope, record['id'], visual['id'], 'Synthetic visual interpretation')
                self.assertEqual(revision_after, service.DocumentService._source_revision(same))
                corrected = self.store.record_extracted_text(self.scope, record['id'], visual['id'], 'Corrected synthetic visual interpretation')
                self.assertEqual(same['inventory']['visual_transcribed_units'], corrected['inventory']['visual_transcribed_units'])
                self.assertNotEqual(revision_after, service.DocumentService._source_revision(corrected))

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing PDF runtime required')
    def test_falsey_content_stream_still_enforces_per_page_and_total_decoded_byte_limits(self):
        for setting, limit, pages in [('MAX_PDF_PAGE_BYTES', 1, 1), ('MAX_PDF_CONTENT_BYTES', 80, 2)]:
            with self.subTest(setting=setting), patch.object(documents, setting, limit):
                data = pdf_bytes(pages=pages)
                record = self.extract(setting + '.pdf', data)
                self.assertEqual(record['status'], 'error')
                self.assertIn('decoded content exceeds', record['error'])
                self.assertEqual(self.store.chunks(self.scope, record['id'])['total'], 0)
                self.assertEqual(self.store.original_path(self.scope, record['id']).read_bytes(), data)

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing PDF runtime required')
    def test_plain_native_text_page_can_still_be_fully_indexed(self):
        record = self.extract('plain.pdf', pdf_bytes())
        self.assertEqual(record['status'], 'ready')
        self.assertEqual(record['inventory']['vision_pages'], [])
        chunks = self.store.chunks(self.scope, record['id'])['chunks']
        self.assertTrue(service.DocumentService._review_complete(record, {}, len(chunks), len(chunks)))

    @unittest.skipUnless(importlib.util.find_spec('openpyxl') and importlib.util.find_spec('PIL'), 'Existing spreadsheet/image runtime required')
    def test_embedded_chart_or_image_does_not_make_readable_cells_a_complete_worksheet(self):
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, Reference
        from openpyxl.drawing.image import Image as WorksheetImage
        from PIL import Image
        for kind in ('chart', 'image'):
            with self.subTest(kind=kind):
                book = Workbook()
                sheet = book.active
                sheet.append(['Fictional stage', 1])
                if kind == 'chart':
                    chart = BarChart()
                    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=1))
                    sheet.add_chart(chart, 'D1')
                else:
                    picture = io.BytesIO()
                    Image.new('RGB', (12, 12), 'black').save(picture, format='PNG')
                    picture.seek(0)
                    sheet.add_image(WorksheetImage(picture), 'D1')
                output = io.BytesIO()
                book.save(output)
                book.close()
                record = self.extract(kind + '.xlsx', output.getvalue())
                self.assertEqual(record['status'], 'partial')
                self.assertEqual(record['coverage']['indexed_units'], 0)
                self.assertEqual(record['coverage']['total_units'], 1)
                self.assertIn('drawing', record['inventory']['sheets'][0]['unread_visual_parts'])
                chunks = self.store.chunks(self.scope, record['id'])['chunks']
                self.assertIn('Fictional stage', chunks[0]['text'])
                self.assertFalse(service.DocumentService._review_complete(record, {}, len(chunks), len(chunks)))

    def test_relationship_xml_cannot_bypass_the_workbook_declaration_guard(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('xl/worksheets/_rels/sheet1.xml.rels', b'<!DOCTYPE Relationships [<!ENTITY x "fictional">]><Relationships>&x;</Relationships>')
        record = self.extract('relationships.xlsx', output.getvalue())
        self.assertEqual(record['status'], 'error')
        self.assertIn('DTD', record['error'])
        self.assertEqual(self.store.chunks(self.scope, record['id'])['total'], 0)


if __name__ == '__main__':
    unittest.main()
