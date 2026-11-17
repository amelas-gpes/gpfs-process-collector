"""Open frozen, fictional saves using the public store interfaces on this build."""

import knowledge_rows as rows
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_store_format import documents, knowledge_graph


FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'compat'
SCOPE = 'SYNTHETIC_ONLY_compatibility_file_workspace_00001'
ORIGINAL = b'Ticket,Action\nFixture,Record\n'
DOCUMENT_ID = 'doc_' + '1' * 24


def restore_fixture(target, kind, version):
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target)) as db:
        db.executescript((FIXTURES / f'{kind}-{version}.sql').read_text(encoding='utf-8'))


class ReleasedStores(unittest.TestCase):
    def test_read_then_append_with_both_store_generations(self):
        for version in ('0.26.1', '0.30.0'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                files = root / 'files'
                restore_fixture(files / 'documents.sqlite3', 'documents', version)
                original = files / hashlib.sha256(SCOPE.encode()).hexdigest() / DOCUMENT_ID / 'original.csv'
                original.parent.mkdir(parents=True)
                original.write_bytes(ORIGINAL)
                store = documents.DocumentStore(files)
                legacy_file = store.get(SCOPE, DOCUMENT_ID)
                # Both releases indexed this file with an earlier parser version (the PDF reader
                # changed in extraction version 4), so both are held back until the local comparison.
                self.assertEqual(legacy_file['status'], 'partial')
                self.assertTrue(legacy_file.get('extraction_needs_reindex'))
                found = store.chunks(SCOPE, DOCUMENT_ID)['chunks'][0]
                self.assertEqual(store.source(SCOPE, DOCUMENT_ID, found['id'])['text'],
                                 'A1=Ticket | B1=Action\nA2=Fixture | B2=Record')
                self.assertEqual(store.original_bytes(SCOPE, DOCUMENT_ID), ORIGINAL)
                # That comparison is local and free. The 0.30.0 index of this CSV is what the current
                # parser produces, so it is confirmed as it is; the 0.26.1 index is not and stays held.
                checked = store.check_extraction(SCOPE, DOCUMENT_ID)
                if version == '0.30.0':
                    self.assertEqual((checked['status'], checked['extraction_needs_reindex'], checked['extraction_version']),
                                     ('ready', False, documents.EXTRACTION_VERSION))
                    self.assertNotIn('reindex_check', checked)
                else:
                    self.assertTrue(checked['extraction_needs_reindex'])
                    self.assertEqual(checked['reindex_check']['outcome'], 'changed')
                self.assertEqual(store.source(SCOPE, DOCUMENT_ID, found['id'])['text'],
                                 'A1=Ticket | B1=Action\nA2=Fixture | B2=Record')
                second = store.add(SCOPE, 'additional.csv', b'Next\nFictional upload\n')
                self.assertEqual(store.extract(SCOPE, second['id'])['status'], 'ready')
                self.assertEqual(len(store.list(SCOPE)), 2)

                target = root / 'knowledge.sqlite3'
                restore_fixture(target, 'knowledge', version)
                graph = knowledge_graph.KnowledgeGraph(target)
                try:
                    item = rows.submissions(graph)[0]
                    original = graph._revision(item['submission_id'], 1)
                    self.assertEqual(original['context']['process_name'], 'Compatibility test')
                    self.assertIn('fictional reviewer', original['turns'][0]['text'])
                    receipt = graph.submit({'process_id': item['process_id'], 'context': original['context'],
                                            'turns': original['turns'], 'draft': original['draft']}, base_revision=1)
                    self.assertEqual(receipt['revision'], 2)
                    self.assertEqual(graph.status(receipt['submission_id'], 2, receipt['status_token'])['status'], 'pending')
                    self.assertEqual(graph._revision(item['submission_id'], 1)['turns'], original['turns'])
                finally:
                    graph.close()

    def test_legacy_columns_added_to_released_graph_without_losing_records(self):
        missing = {'canonical_groups': ['status', 'stale_reason'], 'jobs': ['owner_pid'],
                   'proposals': ['claim_key'], 'submission_keys': ['intent_digest']}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'knowledge.sqlite3'
            restore_fixture(target, 'knowledge', '0.26.1')
            with closing(sqlite3.connect(target)) as db:
                db.execute('DROP INDEX proposals_claim_idx')
                for table, columns in missing.items():
                    for column in columns:
                        db.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
                db.execute('PRAGMA user_version=0')
                db.commit()
            graph = knowledge_graph.KnowledgeGraph(target)
            try:
                self.assertEqual(len(rows.submissions(graph)), 1)
                for table, columns in missing.items():
                    stored = {row[1] for row in graph.db.execute(f'PRAGMA table_info({table})')}
                    self.assertTrue(set(columns) <= stored)
            finally:
                graph.close()


class LargeFileSources(unittest.TestCase):
    def test_discard_only_never_indexed_failed_original_and_use_its_slot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(documents, 'MAX_FILES_PER_SCOPE', 1):
            store = documents.DocumentStore(directory)
            scope = store.create_scope()
            with self.assertRaisesRegex(documents.DocumentError, '40 million'):
                store.add(scope, 'oversize.png', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + (9000).to_bytes(4, 'big') * 2)
            self.assertEqual(store.list(scope), [])
            failed = store.add(scope, 'unreadable.csv', b'\x00\x01\x02')
            self.assertEqual(store.extract(scope, failed['id'])['status'], 'error')
            original = store.original_path(scope, failed['id'])
            self.assertTrue(store.purge(scope, failed['id'], failed_only=True)['purged'])
            self.assertFalse(original.exists())
            healthy = store.add(scope, 'valid.csv', ORIGINAL)
            store.extract(scope, healthy['id'])
            with self.assertRaisesRegex(documents.DocumentError, 'Only a failed upload'):
                store.purge(scope, healthy['id'], failed_only=True)

    def test_wide_cells_keep_their_address_and_exact_excerpt_on_continuations(self):
        with tempfile.TemporaryDirectory() as directory:
            store = documents.DocumentStore(directory)
            scope = store.create_scope()
            fields = ['a' * 3500, 'b' * 2500, 'c' * 7000, 'End']
            record = store.add(scope, 'wide.csv', ','.join(fields).encode())
            self.assertEqual(store.extract(scope, record['id'])['status'], 'ready')
            chunks = store.chunks(scope, record['id'])['chunks']
            self.assertEqual([row['range'] for row in chunks], ['A1', 'B1', 'C1', 'C1', 'D1'])
            self.assertEqual(''.join(row['text'][3:] for row in chunks if row['range']=='C1'), fields[2])
            self.assertEqual([row['cell_part'] for row in chunks if row['range']=='C1'], [1,2])
            for row in chunks:
                self.assertIn('CSV!' + row['range'], row['label'])
                self.assertEqual(sum(row['cell_lengths']), len(row['text']))
                self.assertEqual(store.source(scope, record['id'], row['id'])['text'], row['text'])
