"""Reads of one interview's sections must not read every interview's sections.

The full-text table can only be looked up by MATCH or rowid. Format 2 of the store adds
chunk_map for every other lookup and matches a search inside its own scope.
"""
import importlib.util
import io
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('collector_document_service_index', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
import documents

FULL_SCAN = re.compile(r'SCAN chunks VIRTUAL TABLE INDEX \d+:$')
OLD_CHUNKS = ("CREATE VIRTUAL TABLE chunks USING fts5(id UNINDEXED, document_id UNINDEXED, scope UNINDEXED, "
              "label, text, location UNINDEXED, tokenize='unicode61')")


def csv_rows(rows, word='ledger'):
    return ('stage,owner,note\n' + ''.join(f'step{index},clerk{index},{word} entry {index}\n' for index in range(rows))).encode()


def png_bytes():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (40, 20), 'white').save(output, 'PNG')
    return output.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'documents'
        self.store = documents.DocumentStore(self.root)
        self.scope = self.store.create_scope()

    def indexed(self, name, data, scope=None):
        scope = scope or self.scope
        record = self.store.extract(scope, self.store.add(scope, name, data)['id'])
        self.assertIn(record['status'], ('ready', 'partial'), record.get('error'))
        return record

    def raw(self, sql, parameters=()):
        db = sqlite3.connect(str(self.root / 'documents.sqlite3'))
        try:
            rows = db.execute(sql, parameters).fetchall()
            db.commit()
            return rows
        finally:
            db.close()

    def assert_map_matches_index(self):
        mapped = self.raw('SELECT scope,document_id,id,chunk_rowid FROM chunk_map ORDER BY chunk_rowid')
        self.assertEqual(mapped, self.raw('SELECT scope,document_id,id,rowid FROM chunks ORDER BY rowid'))
        return mapped

    def traced(self, action):
        """Run action and return the query plan of every statement it sent that reads or changes sections."""
        statements, connect = [], sqlite3.connect

        def connecting(*arguments, **options):
            db = connect(*arguments, **options)
            db.set_trace_callback(statements.append)
            return db
        with patch.object(documents.sqlite3, 'connect', side_effect=connecting):
            result = action()
        plans = {}
        db = connect(str(self.root / 'documents.sqlite3'))
        try:
            for statement in statements:
                if re.match(r'\s*(SELECT|DELETE|UPDATE)\b', statement) and re.search(r'\bchunks\b', statement):
                    plans[statement] = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + statement)]
        finally:
            db.close()
        return result, plans


class NoStoreWideScans(Case):
    def test_no_read_or_review_step_scans_the_sections_of_every_interview(self):
        other = self.store.create_scope()
        self.indexed('other.csv', csv_rows(1200, 'ledger'), other)
        record = self.indexed('mine.csv', csv_rows(30))
        scan = self.indexed('scan.png', png_bytes())
        source_id = self.store.chunks(self.scope, record['id'])['chunks'][0]['id']
        service = service_module.DocumentService(self.store, lambda *arguments: self.fail('no review is expected'))
        self.addCleanup(lambda: service._worker.join(timeout=4))
        self.addCleanup(service.close)

        def everything():
            self.store.chunks(self.scope, record['id'], offset=1, limit=2)
            self.store.source(self.scope, record['id'], source_id)
            self.store.search(self.scope, 'which ledger entry does the clerk check')
            self.store.search(self.scope, '', ids=[record['id']])
            service.supporting_context(self.scope, 'ledger entry', source_ids=[source_id])
            self.store.record_extracted_text(self.scope, scan['id'], scan['id'] + '_image_c1', 'x' * (documents.MAX_CHUNK_CHARS + 5))
            self.store.record_extracted_text(self.scope, scan['id'], scan['id'] + '_image_c1', 'A shorter reading.')
            self.rewrite_version(record['id'])
            self.store.check_extraction(self.scope, record['id'])
            self.rewrite_version(record['id'])
            self.store.extract(self.scope, record['id'])
        _, plans = self.traced(everything)
        self.assertGreater(len(plans), 12, 'the statements were not traced')
        scans = {statement[:160]: plan for statement, plan in plans.items() if any(FULL_SCAN.search(step) for step in plan)}
        self.assertEqual(scans, {}, 'these statements read every section of every interview')
        # A search by words is matched inside the interview, in label and text only.
        matches = [statement for statement in plans if ' MATCH ' in statement]
        self.assertTrue(matches)
        digest = self.store._scope_hash(self.scope)
        for statement in matches:
            self.assertIn(f'scope : "{digest}" AND text : (', statement)
        self.assert_map_matches_index()

    def rewrite_version(self, document_id):
        with self.store._db() as db:
            saved = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()[0])
            saved.pop('extraction_version', None)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(saved), document_id))

    def test_search_stays_inside_the_interview_and_never_matches_the_scope_column_as_text(self):
        other = self.store.create_scope()
        theirs = self.indexed('other.csv', csv_rows(40, 'ledger'), other)
        mine = self.indexed('mine.csv', csv_rows(5, 'ledger'))
        hits = self.store.search(self.scope, 'ledger', limit=100)
        self.assertTrue(hits)
        self.assertEqual({hit['document_id'] for hit in hits}, {mine['id']})
        self.assertEqual({hit['document_id'] for hit in self.store.search(other, 'ledger', limit=100)}, {theirs['id']})
        for digest in (self.store._scope_hash(self.scope), self.store._scope_hash(other)):
            self.assertEqual(self.store.search(self.scope, digest), [], 'a scope digest is not searchable text')
        self.assertEqual(self.store.search(self.scope, mine['id']), [], 'a file ID is not searchable text')
        # Words that are operators or column names of the search syntax are ordinary words.
        for query in ('scope', 'label AND text', 'NOT ledger OR NEAR', '"ledger" *'):
            self.store.search(self.scope, query)
        self.assertEqual([hit['id'] for hit in self.store.search(self.scope, 'entry 3 clerk3', limit=1)],
                         [hit['id'] for hit in hits if 'clerk3' in hit['text']][:1])


class ChunkMapStaysInStep(Case):
    def test_every_change_of_the_index_changes_chunk_map_in_the_same_transaction(self):
        record = self.indexed('mine.csv', csv_rows(450))
        scan = self.indexed('scan.png', png_bytes())
        self.assertGreater(record['chunk_count'], 2)
        self.assertEqual(len(self.assert_map_matches_index()), record['chunk_count'] + 1)
        source_id = scan['id'] + '_image_c1'
        long = 'reading ' * 2000
        self.store.record_extracted_text(self.scope, scan['id'], source_id, long)
        parts = [row[2] for row in self.assert_map_matches_index() if row[1] == scan['id']]
        self.assertEqual(parts, [source_id, source_id + '_v2', source_id + '_v3'])
        self.assertEqual(''.join(chunk['text'] for chunk in self.store.chunks(self.scope, scan['id'])['chunks']), long)
        self.store.record_extracted_text(self.scope, scan['id'], source_id, 'A shorter reading.')
        self.assertEqual([row[2] for row in self.assert_map_matches_index() if row[1] == scan['id']], [source_id])
        self.assertEqual(self.store.chunks(self.scope, scan['id'])['total'], 1)
        with self.assertRaises(PermissionError):
            self.store.source(self.scope, scan['id'], source_id + '_v2')
        # A re-index replaces a file's rows in both tables; a refused one changes neither.
        before = self.assert_map_matches_index()
        with self.store._db() as db:
            saved = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (record['id'],)).fetchone()[0])
            saved.pop('extraction_version')
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(saved), record['id']))
        with patch.object(documents, 'MAX_CHUNKS', 1):
            self.assertEqual(self.store.extract(self.scope, record['id'])['status'], 'error')
        self.assertEqual(self.assert_map_matches_index(), before)
        with self.store._db() as db:
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(saved), record['id']))
        again = self.store.extract(self.scope, record['id'])
        self.assertEqual(again['status'], 'ready')
        after = self.assert_map_matches_index()
        self.assertEqual(sorted(row[2] for row in after), sorted(row[2] for row in before))
        self.assertNotEqual(after, before, 're-indexed rows are new rows')
        page = self.store.chunks(self.scope, record['id'], offset=1, limit=2)
        self.assertEqual((page['total'], page['offset'], page['next_offset']), (record['chunk_count'], 1, 3))
        self.assertEqual([chunk['id'] for chunk in page['chunks']], [row[2] for row in after if row[1] == record['id']][1:3])


class FormatOneStore(Case):
    def downgraded(self):
        """Give the store the layout formats 0 and 1 had, with the same rows under the same rowids."""
        db = sqlite3.connect(str(self.root / 'documents.sqlite3'))
        try:
            db.execute('ALTER TABLE chunks RENAME TO chunks_new')
            db.execute(OLD_CHUNKS)
            db.execute('INSERT INTO chunks(rowid,id,document_id,scope,label,text,location) '
                       'SELECT rowid,id,document_id,scope,label,text,location FROM chunks_new')
            db.execute('DROP TABLE chunks_new')
            db.execute('DROP TABLE chunk_map')
            db.execute('PRAGMA user_version=1')
            db.commit()
        finally:
            db.close()

    def test_store_of_an_earlier_format_is_upgraded_once_with_every_section_where_it_was(self):
        other = self.store.create_scope()
        theirs = self.indexed('other.csv', csv_rows(300, 'ledger'), other)
        mine = self.indexed('mine.csv', csv_rows(300, 'ledger'))
        scan = self.indexed('scan.png', png_bytes())
        self.store.record_extracted_text(self.scope, scan['id'], scan['id'] + '_image_c1', 'reading ' * 2000)
        rows = self.raw('SELECT rowid,id,document_id,scope,label,text,location FROM chunks ORDER BY rowid')
        reads = lambda store: (store.chunks(self.scope, mine['id'], offset=1, limit=3), store.chunks(self.scope, scan['id']),
                               store.source(other, theirs['id'], rows[0][1]), store.search(self.scope, 'ledger clerk7 reading', limit=20),
                               store.search(self.scope, '', limit=5))
        before = reads(self.store)
        for earlier in (1, 0):
            with self.subTest(format=earlier):
                self.downgraded()
                self.raw('PRAGMA user_version=%d' % earlier)
                self.assertEqual(self.raw("SELECT count(*) FROM sqlite_master WHERE name='chunk_map'"), [(0,)])
                upgraded = documents.DocumentStore(self.root)
                self.assertEqual(self.raw('PRAGMA user_version'), [(documents.STORE_FORMATS[1],)])
                self.assertEqual(self.raw('SELECT rowid,id,document_id,scope,label,text,location FROM chunks ORDER BY rowid'), rows)
                self.assertEqual(len(self.assert_map_matches_index()), len(rows))
                self.assertEqual(reads(upgraded), before)
                self.assertEqual(self.raw("SELECT name FROM sqlite_master WHERE name LIKE 'chunks_scoped%'"), [])
                # Opened again, nothing is rebuilt.
                with patch.object(documents, 'CHUNKS_TABLE', 'NOT SQL: the table must not be created twice'):
                    self.assertEqual(reads(documents.DocumentStore(self.root)), before)
        # The upgraded store takes new work like a new one.
        added = self.indexed('later.csv', csv_rows(5, 'ledger'))
        self.assertEqual(self.store.chunks(self.scope, added['id'])['total'], added['chunk_count'])
        self.assert_map_matches_index()

    def test_failed_upgrade_leaves_the_earlier_store_as_it_was(self):
        self.indexed('mine.csv', csv_rows(20))
        self.downgraded()
        tables = self.raw('SELECT name,sql FROM sqlite_master ORDER BY name')
        rows = self.raw('SELECT rowid,id,text FROM chunks ORDER BY rowid')
        with patch.object(documents, 'CHUNKS_TABLE', "CREATE VIRTUAL TABLE {name} USING fts5(id, tokenize='unicode61')"):
            with self.assertRaises(sqlite3.Error):
                documents.DocumentStore(self.root)
        self.assertEqual(self.raw('PRAGMA user_version'), [(1,)])
        self.assertEqual(self.raw('SELECT name,sql FROM sqlite_master ORDER BY name'), tables)
        self.assertEqual(self.raw('SELECT rowid,id,text FROM chunks ORDER BY rowid'), rows)


class SelectionComputedOnce(Case):
    def setUp(self):
        super().setUp()
        self.record = self.indexed('mine.csv', csv_rows(30))
        self.second = self.indexed('second.csv', csv_rows(4, 'invoice'))
        self.service = service_module.DocumentService(self.store, lambda *arguments: self.fail('no review is expected'))
        self.addCleanup(lambda: self.service._worker.join(timeout=4))
        self.addCleanup(self.service.close)
        self.computed = []
        compute = self.service._supporting_context

        def counting(*arguments, **options):
            self.computed.append(arguments[1])
            return compute(*arguments, **options)
        self.service._supporting_context = counting

    def test_same_selection_of_unchanged_files_is_computed_once_and_handed_out_as_copies(self):
        source_id = self.store.chunks(self.scope, self.record['id'])['chunks'][0]['id']
        first = self.service.supporting_context(self.scope, 'ledger entry', source_ids=[source_id])
        first['documents'][0]['excerpts'].clear()
        first.pop('notice')
        second = self.service.supporting_context(self.scope, 'ledger entry', source_ids=(source_id,))
        third = self.service.supporting_context(self.scope, 'ledger entry', [source_id], required_documents=[])
        self.assertEqual(len(self.computed), 1)
        self.assertEqual(second, third)
        self.assertTrue(second['documents'][0]['excerpts'] and second['notice'], 'a caller changed what the next caller received')
        self.assertIsNot(second['documents'], third['documents'])
        # Each different request is its own computation.
        self.service.supporting_context(self.scope, 'invoice entry', source_ids=[source_id])
        self.service.supporting_context(self.scope, 'ledger entry')
        self.service.supporting_context(self.scope, 'ledger entry', source_ids=[source_id], required_documents=[self.second['id']])
        self.service.supporting_context(self.scope, 'ledger entry', source_ids=[source_id], frozen=True)
        self.service.supporting_context(self.scope, 'ledger entry', source_ids=[source_id], frozen=True, selected_documents=[self.record['id']])
        self.assertEqual(len(self.computed), 6)
        other = self.store.create_scope()
        self.assertEqual(self.service.supporting_context(other, 'ledger entry', source_ids=[source_id])['documents'], [])
        self.assertEqual(len(self.computed), 7)

    def test_any_change_of_a_file_is_seen_by_the_next_request(self):
        ask = lambda: self.service.supporting_context(self.scope, 'ledger entry')
        base = ask()
        changes = (
            ('review metadata', lambda: self.store.update(self.scope, self.record['id'], {'analysis': {'summary': 'Reviewed.', 'phase': 'complete'}})),
            ('removal', lambda: self.store.archive(self.scope, self.second['id'])),
            ('restore', lambda: self.store.archive(self.scope, self.second['id'], False)),
            ('a new file', lambda: self.indexed('third.csv', csv_rows(3))),
            ('a record rewritten without a new revision', lambda: self.unversioned(self.record['id'])),
            ('a newer parser version', lambda: setattr(documents, 'EXTRACTION_VERSION', documents.EXTRACTION_VERSION + 1)),
        )
        self.addCleanup(setattr, documents, 'EXTRACTION_VERSION', documents.EXTRACTION_VERSION)
        previous = base
        for count, (name, change) in enumerate(changes, 2):
            with self.subTest(change=name):
                change()
                current = ask()
                self.assertEqual(len(self.computed), count, 'the selection was not computed again')
                self.assertNotEqual(current, previous)
                self.assertEqual(ask(), current)
                self.assertEqual(len(self.computed), count)
                previous = current
        with self.assertRaises(documents.DocumentError):
            self.service.supporting_context(self.scope, 'ledger entry', required_documents=[{'not': 'an id'}])
        with self.assertRaises(documents.DocumentError):
            self.service.supporting_context(self.scope, ['not text'])

    def unversioned(self, document_id):
        with self.store._db() as db:
            saved = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()[0])
            saved['analysis'] = {**saved.get('analysis', {}), 'purpose': 'Changed by hand.'}
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(saved), document_id))

    def test_remembered_selections_are_bounded(self):
        for index in range(service_module.MAX_SUPPORT_MEMO + 5):
            self.service.supporting_context(self.scope, f'ledger entry {index}')
        self.assertEqual(len(self.service._support_memo), service_module.MAX_SUPPORT_MEMO)


if __name__ == '__main__':
    unittest.main()
