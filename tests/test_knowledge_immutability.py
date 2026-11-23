"""The SQLite boundary preserves filed revisions and historical decisions across upgrades."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_release_compatibility import knowledge_graph, restore_fixture


class FiledHistoryTests(unittest.TestCase):
    def test_history_in_reopened_store_accepts_appends_and_refuses_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.sqlite3"
            restore_fixture(path, "knowledge", "0.26.1")
            graph = knowledge_graph.KnowledgeGraph(path)
            try:
                db = graph.db
                revision = db.execute("SELECT * FROM revisions").fetchone()
                original = json.loads(revision["payload"])
                receipt = graph.submit({"process_id": revision["process_id"], "context": original["context"],
                                        "turns": original["turns"], "draft": original["draft"]}, base_revision=1)
                self.assertEqual(receipt["revision"], 2)
                with db:
                    db.execute("INSERT INTO proposals(id,fingerprint,data,status,created_at) VALUES "
                               "('p','p','{}','proposed','t')")
                    db.execute("INSERT INTO review_history VALUES ('r','p','reject','system','reason',NULL,'t',1)")
                    db.execute("INSERT INTO canonical_groups(id,label,type,review_version,created_at) VALUES "
                               "('g','example','role',1,'t')")
                    db.execute("INSERT INTO canonical_history VALUES ('h','g','stale','','system','reason',1,'t')")
                    db.execute("INSERT INTO deletions VALUES ('d','old-submission','old-process',1,0,'system','reason','t')")
            finally:
                graph.close()

            reopened = knowledge_graph.KnowledgeGraph(path)
            try:
                db = reopened.db
                for table in ("revisions", "review_history", "canonical_history", "deletions"):
                    for statement in (f"UPDATE {table} SET rowid=rowid", f"DELETE FROM {table}",
                                      f"INSERT OR REPLACE INTO {table} SELECT * FROM {table} LIMIT 1"):
                        with self.subTest(statement=statement):
                            try:
                                with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                                    db.execute(statement)
                            finally:
                                db.rollback()
                stored = db.execute("SELECT * FROM revisions WHERE submission_id=? AND revision=1",
                                    (revision["submission_id"],)).fetchone()
                self.assertEqual(dict(stored), dict(revision))
            finally:
                reopened.close()

    def test_late_storage_failure_rolls_back_the_filing_and_allows_a_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = knowledge_graph.KnowledgeGraph(Path(directory) / "knowledge.sqlite3")
            try:
                db = graph.db
                submission = {"context": {"process_name": "Example"},
                              "turns": [{"id": "t1", "role": "user", "text": "We review a request."}],
                              "submission_key": "00000000-0000-4000-8000-000000000001"}
                db.execute("""CREATE TEMP TRIGGER refuse_job BEFORE INSERT ON jobs
                              BEGIN SELECT RAISE(ABORT, 'synthetic job failure'); END""")
                with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic job failure"):
                    graph.submit(submission)
                for table in ("revisions", "entities", "edges", "jobs", "status_capabilities", "submission_keys"):
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
                db.execute("DROP TRIGGER refuse_job")
                receipt = graph.submit(submission)
                self.assertEqual(graph.submit(submission), receipt)
                self.assertEqual(receipt["revision"], 1)
            finally:
                graph.close()
