"""The two SQLite stores carry a format number. Several builds can open the same work/ folder
(the checkout's server, the desktop window's approved build and its fallback), so a build must
refuse data written by a newer one, and must not report a newer index as out of date."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from test_desktop_updates import Installation, config


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


documents = load("store_format_documents", "documents.py")
knowledge_graph = load("store_format_knowledge_graph", "knowledge_graph.py")


def stored_format(path, change=None):
    """Read, or first set, the number SQLite keeps in the file (PRAGMA user_version)."""
    db = sqlite3.connect(str(path))
    try:
        if change is not None:
            db.execute("PRAGMA user_version=%d" % change)
            db.commit()
        return db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def tables(path):
    db = sqlite3.connect(str(path))
    try:
        return sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master"))
    finally:
        db.close()


def layout(path):
    """A fingerprint of the tables and indexes the application itself defines in a store."""
    db = sqlite3.connect(str(path))
    try:
        statements = sorted(" ".join(row[0].split()) for row in db.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'chunks\\_%' ESCAPE '\\'"))
    finally:
        db.close()
    return hashlib.sha256("\n".join(statements).encode("utf-8")).hexdigest()[:16]


class DocumentStoreFormat(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "documents"
        self.path = self.root / "documents.sqlite3"

    def test_build_declares_the_formats_it_reads_and_stamps_what_it_writes(self):
        oldest, newest = documents.STORE_FORMATS
        self.assertEqual(oldest, 0, "a store from before formats were recorded must still open")
        self.assertGreaterEqual(newest, 1)
        documents.DocumentStore(self.root)
        self.assertEqual(stored_format(self.path), newest)
        # A store written before formats were recorded holds 0: it is upgraded in place and keeps its data.
        store = documents.DocumentStore(self.root)
        scope = store.create_scope()
        record = store.add(scope, "legacy.csv", b"stage\nFictionalIntake\n")
        self.assertEqual(stored_format(self.path, 0), 0)
        store = documents.DocumentStore(self.root)
        self.assertEqual(stored_format(self.path), newest)
        self.assertEqual(store.get(scope, record["id"])["filename"], "legacy.csv")

    def test_store_written_by_a_newer_build_is_refused_and_left_as_it_was(self):
        documents.DocumentStore(self.root)
        newer = documents.STORE_FORMATS[1] + 1
        db = sqlite3.connect(str(self.path))
        db.execute("CREATE TABLE added_by_a_newer_build (value TEXT)")
        db.execute("DROP TABLE scopes")  # A layout this build would otherwise quietly re-create.
        db.execute("PRAGMA user_version=%d" % newer)
        db.commit()
        db.close()
        before = tables(self.path)
        with self.assertRaises(documents.StoreFormatError) as refusal:
            documents.DocumentStore(self.root)
        message = str(refusal.exception)
        self.assertIn("newer build", message)
        self.assertIn("format %d" % newer, message)
        self.assertNotIsInstance(refusal.exception, (OSError, ValueError),
                                 "the server reports OSError as a busy port and ValueError as bad input")
        self.assertEqual(stored_format(self.path), newer)
        self.assertEqual(tables(self.path), before, "a build changed a store it cannot read")

    def test_index_made_by_a_newer_build_is_not_reported_as_out_of_date(self):
        store = documents.DocumentStore(self.root)
        scope = store.create_scope()
        record = store.add(scope, "newer.csv", b"stage\nFictionalIntake\n")
        current = store.extract(scope, record["id"])
        self.assertEqual((current["status"], current["extraction_version"]), ("ready", documents.EXTRACTION_VERSION))
        indexed = current["coverage"]["indexed_units"]
        self.assertGreater(indexed, 0)

        def saved_with(version):
            with store._db() as db:
                row = db.execute("SELECT record FROM documents WHERE id=?", (record["id"],)).fetchone()
                saved = json.loads(row[0])
                saved.pop("extraction_version", None)
                if version is not None:
                    saved["extraction_version"] = version
                db.execute("UPDATE documents SET record=? WHERE id=?", (json.dumps(saved), record["id"]))
            return store.get(scope, record["id"])

        newer = saved_with(documents.EXTRACTION_VERSION + 1)
        self.assertTrue(documents.DocumentStore.extraction_current(newer))
        self.assertEqual(newer["status"], "ready")
        self.assertFalse(newer.get("extraction_needs_reindex"))
        self.assertEqual(newer["coverage"]["indexed_units"], indexed)
        self.assertNotIn("predates", json.dumps(newer), "an index made by a newer build was called older than this one")
        # Nor is it re-extracted with this build's older parser.
        again = store.extract(scope, record["id"])
        self.assertEqual(again["extraction_version"], documents.EXTRACTION_VERSION + 1)
        self.assertEqual(again["revision"], newer["revision"])
        # Records that really are older, or carry no usable version, are still held back.
        for version in (documents.EXTRACTION_VERSION - 1, None, str(documents.EXTRACTION_VERSION + 1), True):
            older = saved_with(version)
            self.assertFalse(documents.DocumentStore.extraction_current(older), version)
            self.assertTrue(older["extraction_needs_reindex"], version)
            self.assertEqual(older["coverage"]["indexed_units"], 0, version)
            self.assertIn("predates", json.dumps(older["coverage"]["limitations"]), version)


class KnowledgeGraphFormat(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "knowledge" / "knowledge.sqlite3"

    def test_build_declares_the_formats_it_reads_and_stamps_what_it_writes(self):
        oldest, newest = knowledge_graph.STORE_FORMATS
        self.assertEqual(oldest, 0)
        self.assertGreaterEqual(newest, 1)
        knowledge_graph.KnowledgeGraph(self.path).close()
        self.assertEqual(stored_format(self.path), newest)
        self.assertEqual(stored_format(self.path, 0), 0)
        graph = knowledge_graph.KnowledgeGraph(self.path)
        secret = graph.status_secret
        graph.close()
        self.assertEqual(stored_format(self.path), newest)
        graph = knowledge_graph.KnowledgeGraph(self.path)
        self.assertEqual(graph.status_secret, secret)
        graph.close()

    def test_store_written_by_a_newer_build_is_refused_and_left_as_it_was(self):
        knowledge_graph.KnowledgeGraph(self.path).close()
        newer = knowledge_graph.STORE_FORMATS[1] + 1
        db = sqlite3.connect(str(self.path))
        db.execute("ALTER TABLE jobs RENAME TO jobs_in_a_newer_layout")
        db.execute("PRAGMA user_version=%d" % newer)
        db.commit()
        db.close()
        before = tables(self.path)
        with self.assertRaises(knowledge_graph.StoreFormatError) as refusal:
            knowledge_graph.KnowledgeGraph(self.path)
        self.assertIn("newer build", str(refusal.exception))
        self.assertIn("format %d" % newer, str(refusal.exception))
        self.assertNotIsInstance(refusal.exception, (OSError, ValueError))
        self.assertEqual(stored_format(self.path), newer)
        self.assertEqual(tables(self.path), before, "a build changed a store it cannot read")
        # The refusal released the file (on Windows an open handle would block this).
        self.path.rename(self.path.with_name("moved.sqlite3"))


class StoreLayoutChanges(unittest.TestCase):
    """The format number protects nothing if a layout changes and the number does not. This
    records the layout each store has at its current format, so that a change is a decision."""

    # store: (the format the build writes, the fingerprint of the layout it creates)
    # documents, format 2 (performance-1): `scope` is an indexed full-text column and chunk_map maps scope,
    # file and section ID to rows. A format-1 build would write sections without their chunk_map rows.
    # knowledge: the deletions table (gap-privacy-3), the edges_target_idx index (live-draft-knowledge-7)
    # and the jobs.detail column (knowledge-store-3, live-draft-knowledge-5). Format stays 1: an earlier
    # build ignores the table, the index and the column (it names the job columns it writes), and a
    # deleted process has no rows left for it to misread.
    # knowledge, gap3-two-tabs-4: index revisions_interview_idx added and the format kept at 1. A build that
    # knows only the earlier layout reads the store as before and keeps the index up to date when it writes
    # (an expression index over json_extract, like proposals_source_idx); it only lacks the lookup that uses it.
    # Format 3 gives each document section a stable reading order with room after it for visual continuations.
    # Knowledge format 2 migrates stored document capabilities to revocable digests.
    # Knowledge format 3 enforces append-only filing history. Older writers do not
    # enable the recursive triggers needed for SQLite's replace operation.
    RECORDED = {"documents": (3, "79d8cfc60a730de2"), "knowledge": (3, "7797542cbf8bc6fb")}

    def test_changed_layout_comes_with_a_decision_about_its_format_number(self):
        with tempfile.TemporaryDirectory() as scratch:
            documents.DocumentStore(Path(scratch) / "documents")
            graph = Path(scratch) / "knowledge" / "knowledge.sqlite3"
            knowledge_graph.KnowledgeGraph(graph).close()
            current = {"documents": (documents.STORE_FORMATS[1], layout(Path(scratch) / "documents" / "documents.sqlite3")),
                       "knowledge": (knowledge_graph.STORE_FORMATS[1], layout(graph))}
        self.assertEqual(current, self.RECORDED, (
            "A store's tables or indexes changed, or its format number did. Several builds share these files "
            "(docs/DESKTOP.md, 'One set of data, several builds'). If a build that knows only the earlier layout "
            "would misread or damage the new one, raise the second number of STORE_FORMATS in documents.py or "
            "knowledge_graph.py. Then record the new pair in RECORDED."))


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class DesktopHostStoreGuard(unittest.TestCase):
    """The window gives saved data only to a build that declares it can read it."""

    def saved(self, site, module, version):
        folder, name = {"documents.py": ("documents", "documents.sqlite3"),
                        "knowledge_graph.py": ("knowledge", "knowledge.sqlite3")}[module]
        path = site.root / "work" / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        stored_format(path, version)
        return path

    def approve(self, site, mark, formats=None):
        files = {module: "STORE_FORMATS = (0, %d)\n" % newest for module, newest in (formats or {}).items()}
        revision = site.publish(mark, files=files)
        site.app.update(90, 90)
        site.app.approve(revision)
        return revision

    def test_manager_reads_the_declaration_of_the_real_modules_without_running_them(self):
        site = Installation(self)
        self.assertEqual(site.app.store_formats(ROOT, "documents.py"), documents.STORE_FORMATS)
        self.assertEqual(site.app.store_formats(ROOT, "knowledge_graph.py"), knowledge_graph.STORE_FORMATS)
        # A build from before the declaration existed wrote what is now format 1.
        self.assertEqual(site.app.store_formats(site.root, "documents.py"), (0, 1))
        # The manager looks for each store where this build's modules keep it.
        with tempfile.TemporaryDirectory() as home:
            work = Path(home) / "work"
            documents.DocumentStore(work / "documents")
            knowledge_graph.KnowledgeGraph(work / "knowledge" / "knowledge.sqlite3").close()
            for module, location, _ in site.app.STORES:
                self.assertIn(module, ("documents.py", "knowledge_graph.py"))
                self.assertTrue((Path(home) / location).is_file(), location)
            site.app.check_stores(ROOT, Path(home))  # This build opens what it wrote.

    def test_build_older_than_the_saved_data_is_not_started_and_the_window_is_told_why(self):
        for module, newest in (("documents.py", documents.STORE_FORMATS[1]),
                               ("knowledge_graph.py", knowledge_graph.STORE_FORMATS[1])):
            with self.subTest(store=module):
                site = Installation(self)
                old = self.approve(site, "c1", {module: newest - 1})
                path = self.saved(site, module, newest)
                code, out, err = site.run("serve", "--port", site.free_port())
                self.assertNotEqual(code, 0)
                self.assertFalse(site.proof.exists(), "a build older than the saved data was run")
                self.assertTrue(out.startswith("ERROR "), out)
                self.assertEqual(len(out.splitlines()), 1)
                for words in ("newer build", old[:12], f"format {newest}", "nothing was changed"):
                    self.assertIn(words, out)
                self.assertTrue(out.startswith(
                    {"documents.py": "ERROR The documents saved on this computer were written by a newer build ",
                     "knowledge_graph.py": "ERROR The company knowledge saved on this computer was written by a newer "
                                           "build "}[module]), out)
                self.assertIn("older-than-saved-data " + old[:12], site.log())
                self.assertEqual(site.app.failed(), {}, "the refusal was recorded as a failure to start")
                self.assertEqual(stored_format(path), newest)
                # A build that declares the newer format opens; going back to the old one is refused.
                new = self.approve(site, "c2", {module: newest})
                window, address = site.window()
                self.assertEqual(config(address)["build_id"], "stub-c2")
                self.assertEqual(site.close(window), "")
                with self.assertRaises(site.app.DesktopError) as refusal:
                    site.app.rollback(old)
                self.assertIn("newer build", str(refusal.exception))
                self.assertEqual(site.app.approved(), [new, old])

    def test_data_this_build_can_read_or_cannot_inspect_does_not_stop_the_window(self):
        site = Installation(self)
        self.approve(site, "c1")
        self.saved(site, "documents.py", 1)
        unreadable = site.root / "work" / "knowledge" / "knowledge.sqlite3"
        unreadable.parent.mkdir(parents=True)
        unreadable.write_bytes(b"not a database, so its own build must decide what to do with it\n" * 8)
        window, address = site.window()
        self.assertEqual(config(address)["build_id"], "stub-c1")
        self.assertEqual(site.close(window), "")
        self.assertNotIn("older-than-saved-data", site.log())


if __name__ == "__main__":
    unittest.main()
