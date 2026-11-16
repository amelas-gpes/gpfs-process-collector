"""A damaged or locked saved store at start-up.

A damaged knowledge.sqlite3 or documents.sqlite3 used to stop the whole application with a Python
traceback, and the launcher blamed the port. Now a damaged store switches off only the feature
that needs it and says so; a locked one stops the start with one line naming the file and the
lock; nothing is replaced, renamed or deleted. Temporary folders and loopback only.
"""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("store_startup_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

GRAPH = server.local_module("knowledge_graph", "knowledge_graph.py")
GARBAGE = b"This is not an SQLite database. " * 64


class OfflineClient:
    def public_config(self):
        return {"api_configured": False}

    def browser_connect_sources(self):
        return ()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-store-startup-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.documents_file = self.root / "documents" / "documents.sqlite3"
        self.knowledge_file = self.root / "knowledge" / "knowledge.sqlite3"

    def healthy_stores(self):
        """Create both stores the way the application does, then close them."""
        self.construct().server_close()

    def construct(self):
        return server.InterviewServer(("127.0.0.1", 0), server.Handler, client=OfflineClient(),
                                      documents_root=self.root / "documents", knowledge_settings={})

    def start(self):
        httpd = self.construct()
        self.addCleanup(httpd.server_close)
        worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(httpd.shutdown)
        return httpd

    def call(self, httpd, path, payload=None):
        url = f"http://127.0.0.1:{httpd.server_port}"
        headers = {"Origin": url}
        raw = None
        if payload is not None:
            headers.update({"X-CSRF-Token": httpd.csrf_token, "Content-Type": "application/json"})
            raw = json.dumps(payload).encode()
        try:
            with urlopen(Request(url + path, data=raw, headers=headers), timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def events(self, httpd):
        if not httpd.diagnostics_path.exists():
            return []
        return [json.loads(line) for line in httpd.diagnostics_path.read_text(encoding="utf-8").splitlines()]

    def damage(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(GARBAGE)


class DamagedStore(Fixture):
    def test_a_healthy_start_reports_no_storage_problem(self):
        httpd = self.start()
        status, config = self.call(httpd, "/api/config")
        self.assertEqual(status, 200)
        self.assertIs(config["documents"]["enabled"], True)
        self.assertNotIn("documents_unavailable", config)
        self.assertNotIn("knowledge_unavailable", config)
        self.assertEqual(httpd.storage_problems, {})
        self.assertFalse([row for row in self.events(httpd) if row["event"] == "store_unavailable"])

    def test_a_damaged_knowledge_store_switches_off_company_knowledge_only(self):
        self.damage(self.knowledge_file)
        with contextlib.redirect_stdout(io.StringIO()) as console:
            httpd = self.start()
        status, config = self.call(httpd, "/api/config")
        self.assertEqual(status, 200)
        problem = config["knowledge_unavailable"]
        self.assertIn("knowledge.sqlite3", problem)
        self.assertIn("damaged", problem)
        self.assertIn("Submit process is unavailable", problem)
        self.assertIn("Nothing was changed", problem)
        self.assertNotIn(str(self.root), problem, "The page is not told where on the disk the file is")
        self.assertIn(str(self.knowledge_file), console.getvalue(), "The console line names the file")
        # Files still work, and so does everything that does not need company knowledge.
        self.assertIs(config["documents"]["enabled"], True)
        self.assertNotIn("documents_unavailable", config)
        status, session = self.call(httpd, "/api/documents/session", {"context": {}, "turns": [], "current_question": ""})
        self.assertEqual(status, 200, session)
        # Every company-knowledge operation explains itself instead of failing obscurely.
        for path, payload in (("/api/knowledge/submit", {"submission_key": "k" * 36, "turns": []}),
                              ("/api/knowledge/status", {"submission_id": "s", "revision": 1, "status_token": "t"})):
            status, answer = self.call(httpd, path, payload)
            self.assertEqual((status, answer.get("code")), (503, "knowledge_store_unavailable"), answer)
            self.assertEqual(answer["error"], problem)
        row = next(row for row in self.events(httpd) if row["event"] == "store_unavailable")
        self.assertEqual((row["stage"], row["error_category"], row["error_type"]), ("knowledge", "damaged", "DatabaseError"))
        # The damaged file is left exactly as it was: not replaced by a fresh store, not renamed.
        self.assertEqual(self.knowledge_file.read_bytes(), GARBAGE)
        self.assertEqual(sorted(path.name for path in self.knowledge_file.parent.iterdir()), ["knowledge.sqlite3"])
        # Nothing holds it open, so the owner can move it aside while the app runs.
        aside = self.knowledge_file.with_name("knowledge.sqlite3.aside")
        self.knowledge_file.replace(aside)
        self.assertEqual(aside.read_bytes(), GARBAGE)

    def test_a_damaged_documents_store_switches_off_reference_files_only(self):
        self.damage(self.documents_file)
        with contextlib.redirect_stdout(io.StringIO()) as console:
            httpd = self.start()
        status, config = self.call(httpd, "/api/config")
        self.assertEqual(status, 200)
        problem = config["documents_unavailable"]
        self.assertIs(config["documents"]["enabled"], False)
        self.assertIn("documents.sqlite3", problem)
        self.assertIn("damaged", problem)
        self.assertIn("Nothing was changed", problem)
        self.assertNotIn(str(self.root), problem)
        self.assertIn(str(self.documents_file), console.getvalue())
        self.assertNotIn("knowledge_unavailable", config)
        for path, payload in (("/api/documents/session", {"context": {}, "turns": [], "current_question": ""}),
                              ("/api/documents/status", {"scope": "s" * 43, "context": {}, "turns": []}),
                              ("/api/documents/action", {"scope": "s" * 43, "id": "doc_1", "action": "remove"})):
            status, answer = self.call(httpd, path, payload)
            self.assertEqual((status, answer.get("code")), (503, "document_store_unavailable"), answer)
            self.assertEqual(answer["error"], problem)
        # Company knowledge is open: an unknown submission is refused by the graph itself, not by a missing store.
        status, answer = self.call(httpd, "/api/knowledge/status", {"submission_id": "s", "revision": 1, "status_token": "t"})
        self.assertNotEqual(status, 503, answer)
        self.assertNotEqual(status, 500, answer)
        row = next(row for row in self.events(httpd) if row["event"] == "store_unavailable")
        self.assertEqual((row["stage"], row["error_category"]), ("documents", "damaged"))
        self.assertEqual(self.documents_file.read_bytes(), GARBAGE)

    def test_a_store_damaged_after_it_was_created_is_treated_the_same(self):
        self.healthy_stores()
        raw = self.knowledge_file.read_bytes()
        self.assertGreater(len(raw), 8192)
        for sidecar in self.knowledge_file.parent.glob("knowledge.sqlite3-*"):
            sidecar.unlink()
        self.knowledge_file.write_bytes(raw[:100] + b"\xff" * (len(raw) - 100))  # the header survives, the pages do not
        with contextlib.redirect_stdout(io.StringIO()):
            httpd = self.start()
        self.assertIn("knowledge", httpd.storage_problems)
        self.assertEqual(self.call(httpd, "/api/config")[0], 200)

    def test_both_stores_damaged_still_leaves_the_interviewer_running(self):
        self.damage(self.documents_file)
        self.damage(self.knowledge_file)
        with contextlib.redirect_stdout(io.StringIO()):
            httpd = self.start()
        status, config = self.call(httpd, "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(httpd.storage_problems), ["documents", "knowledge"])
        self.assertIn("documents_unavailable", config)
        self.assertIn("knowledge_unavailable", config)
        self.assertEqual(sorted(row["stage"] for row in self.events(httpd) if row["event"] == "store_unavailable"),
                         ["documents", "knowledge"])

    def test_a_submission_with_files_explains_the_missing_file_store(self):
        self.damage(self.documents_file)
        with contextlib.redirect_stdout(io.StringIO()):
            httpd = self.start()
        payload = {"submission_key": str(uuid.uuid4()), "context": {"process_name": "Synthetic"}, "turns": [],
                   "documents": {"scope": "s" * 43, "documents": [{"id": "doc_1"}]}}
        status, answer = self.call(httpd, "/api/knowledge/submit", payload)
        self.assertEqual((status, answer.get("code")), (503, "document_store_unavailable"), answer)
        self.assertIn("documents.sqlite3", answer["error"])


class LockedStore(Fixture):
    def locked(self):
        """Hold a write lock on the knowledge store the way another running copy would."""
        self.healthy_stores()
        other = sqlite3.connect(str(self.knowledge_file), timeout=0.1, check_same_thread=False)
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")
        other.execute("INSERT OR REPLACE INTO private_meta(key,value) VALUES ('held-by-test', x'00')")
        return other

    def test_a_locked_knowledge_store_stops_the_start_and_names_the_lock(self):
        other = self.locked()
        before = self.knowledge_file.read_bytes()
        with patch.object(GRAPH.KnowledgeGraph, "busy_timeout", 0.3), self.assertRaises(server.StoreStartError) as stopped:
            self.construct()
        message = str(stopped.exception)
        self.assertIn(str(self.knowledge_file), message)
        self.assertIn("in use by another program", message)
        self.assertIn("Nothing was changed", message)
        self.assertNotIn("damaged", message)
        self.assertNotIn("\n", message)
        # Never set aside, never replaced: the same file, and no copy beside it.
        other.rollback()
        self.assertEqual(self.knowledge_file.read_bytes(), before)
        self.assertFalse([path.name for path in self.knowledge_file.parent.iterdir() if "damaged" in path.name or "aside" in path.name])
        # Once the other program lets go, the same store opens normally with its content intact.
        other.close()
        httpd = self.start()
        self.assertEqual(httpd.storage_problems, {})

    def test_the_knowledge_store_waits_as_long_as_the_file_store_for_a_lock(self):
        # SQLite's own default is 5 seconds; documents.py has always waited 30.
        self.assertEqual(GRAPH.KnowledgeGraph.busy_timeout, 30)
        opened = []
        real = sqlite3.connect

        def recording(*args, **kwargs):
            opened.append(kwargs)
            return real(*args, **kwargs)
        with patch.object(GRAPH.sqlite3, "connect", recording):
            GRAPH.KnowledgeGraph(self.root / "probe" / "knowledge.sqlite3").close()
        self.assertEqual(opened[0]["timeout"], 30)

    def test_a_lock_that_clears_in_time_does_not_stop_the_start(self):
        other = self.locked()
        release = threading.Timer(0.4, other.rollback)
        release.start()
        self.addCleanup(release.cancel)
        with patch.object(GRAPH.KnowledgeGraph, "busy_timeout", 10):
            httpd = self.construct()
        self.addCleanup(httpd.server_close)
        self.assertEqual(httpd.storage_problems, {})


class StartFailureMessages(Fixture):
    def stopped(self, failure):
        with patch.object(server, "InterviewServer", side_effect=failure), patch.object(server.time, "sleep"), \
                patch.object(sys, "argv", ["server.py", "--port", "8799"]):
            with self.assertRaises(SystemExit) as stopped:
                server.main()
        message = str(stopped.exception)
        self.assertNotIn("\n", message)
        return message

    def test_only_a_refused_bind_is_reported_as_a_busy_port(self):
        self.assertEqual(self.stopped(server.PortUnavailable(10048, "in use")),
                         "Port 8799 is busy. Stop the existing prototype or choose another --port.")
        # Wording that this application did not write (a library's, or anything handed in from outside) is never printed.
        for failure in (PermissionError(13, "Access is denied: PRIVATE-PATH"), FileNotFoundError(2, "PRIVATE-PATH"),
                        sqlite3.OperationalError("unable to open PRIVATE-PATH"), sqlite3.DatabaseError("PRIVATE"),
                        server.StoreStartError("PRIVATE wording that no raise statement of the application wrote"),
                        server.documents.StoreFormatError("PRIVATE")):
            with self.subTest(failure=type(failure).__name__):
                message = self.stopped(failure)
                self.assertNotIn("busy", message)
                self.assertNotIn("PRIVATE", message)
                self.assertIn("could not start", message)

    def real_start(self):
        """Run main() against this fixture's folders and return what it printed on stopping."""
        server_class = server.InterviewServer
        made = lambda address, handler: server_class(address, handler, client=OfflineClient(),
                                                     documents_root=self.root / "documents", knowledge_settings={})
        with patch.object(GRAPH.KnowledgeGraph, "busy_timeout", 0.3), patch.object(server, "InterviewServer", made), \
                patch.object(sys, "argv", ["server.py", "--port", "0"]):
            with self.assertRaises(SystemExit) as stopped:
                server.main()
        self.assertNotIn("\n", str(stopped.exception))
        return str(stopped.exception)

    def test_a_store_from_a_newer_build_is_reported_in_its_own_words(self):
        for path, contents in ((self.knowledge_file, "company knowledge"), (self.documents_file, "documents")):
            with self.subTest(store=path.name):
                self.healthy_stores()
                database = sqlite3.connect(str(path))
                stored = database.execute("PRAGMA user_version").fetchone()[0]
                database.execute("PRAGMA user_version=99")
                database.commit()
                database.close()
                message = self.real_start()
                self.assertIn("store format 99", message)
                self.assertIn(contents, message)
                self.assertIn("newer build", message)
                self.assertNotIn("busy", message)
                database = sqlite3.connect(str(path))
                database.execute("PRAGMA user_version=%d" % stored)
                database.commit()
                database.close()

    def test_a_locked_store_reaches_the_console_as_one_line(self):
        self.healthy_stores()
        other = sqlite3.connect(str(self.knowledge_file), timeout=0.1)
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")
        message = self.real_start()
        self.assertIn("knowledge.sqlite3", message)
        self.assertIn("in use by another program", message)
        self.assertNotIn("busy", message)


if __name__ == "__main__":
    unittest.main()
