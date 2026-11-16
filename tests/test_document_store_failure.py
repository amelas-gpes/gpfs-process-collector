"""The file store fails while an interview that uses files is open.

Every request that carried the file workspace used to end in an unexplained HTTP 500, and the
page had no way to drop the workspace and go on. Now the failure has a code of its own
(document_store_unavailable) wherever the store is read, so that Assets can offer the existing
"Start new file workspace" action, and nothing promises that the files are retained.
Real handler and store; the interviewer is a recording stand-in. No provider.
"""

import errno
import importlib.util
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
spec = importlib.util.spec_from_file_location("document_store_failure_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

TURNS = [{"id": "t001", "role": "assistant", "text": "What starts the work?"},
         {"id": "t002", "role": "user", "text": "An invoice arrives in the shared mailbox and the clerk logs it."}]
CONTEXT = {"process_name": "Invoice intake", "process_owner": "", "objective": "Understand the process.", "background": ""}
FAILURES = (sqlite3.DatabaseError("file is not a database"), sqlite3.OperationalError("unable to open database file"),
            sqlite3.OperationalError("disk I/O error"), OSError(errno.ENOSPC, "No space left on device"),
            FileNotFoundError(errno.ENOENT, "PRIVATE-PATH"), PermissionError(errno.EACCES, "PRIVATE-PATH"))


class Recorder:
    def __init__(self):
        self.interviews, self.during = [], None

    def public_config(self):
        return {"api_configured": True}

    def browser_connect_sources(self):
        return ()

    def analyze_document(self, context, record, chunks, phase, store):
        raise AssertionError("No file review runs in these tests.")

    def interview(self, payload):
        self.interviews.append(payload)
        if self.during:
            self.during()
        return {"question": "What happens next?"}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-store-failure-")
        self.addCleanup(self.temporary.cleanup)
        self.client = Recorder()
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / "documents", knowledge_settings={})
        self.addCleanup(self.httpd.server_close)
        worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(self.httpd.shutdown)
        self.store = self.httpd.documents_store
        self.scope = self.store.create_scope()
        record = self.store.add(self.scope, "fields.csv", b"field,meaning\ninvoice,the supplier's bill\n", {})
        self.store.extract(self.scope, record["id"])
        self.document = record["id"]

    def post(self, path, payload):
        url = f"http://127.0.0.1:{self.httpd.server_port}"
        request = Request(url + path, data=json.dumps(payload).encode(), headers={
            "Origin": url, "X-CSRF-Token": self.httpd.csrf_token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def interview(self, scoped=True):
        return self.post("/api/interview", {"context": CONTEXT, "turns": TURNS, "action": "answer",
                                            **({"document_scope": self.scope} if scoped else {})})

    def break_store(self):
        """What a truncating sync tool or a full disk leaves: the database file is no longer a database."""
        path = Path(self.temporary.name) / "documents" / "documents.sqlite3"
        for sidecar in path.parent.glob("documents.sqlite3-*"):
            sidecar.unlink()
        path.write_bytes(b"This is not an SQLite database. " * 64)

    def assert_store_failure(self, answer):
        status, body = answer
        self.assertEqual((status, body.get("code")), (503, "document_store_unavailable"), body)
        self.assertEqual(body["error"], server.DOCUMENT_STORE_FAILED_MESSAGE)


class InterviewRequests(Fixture):
    def test_the_message_says_how_to_continue_and_promises_nothing_about_the_files(self):
        message = server.DOCUMENT_STORE_FAILED_MESSAGE
        self.assertIn("Start new file workspace", message)
        self.assertIn("Your interview is retained", message)
        self.assertNotIn("existing files are retained", message)

    def test_discard_pauses_only_the_named_workspace_and_keeps_its_index(self):
        second = self.store.create_scope()
        outside = self.store.add(second, 'other.csv', b'column\nsynthetic', {})
        self.store.extract(second, outside["id"])
        for scope, document in [(self.scope, self.document), (second, outside["id"])]:
            self.store.update(scope, document, {"analysis": {"phase": "deep", "intent_version": 1, "version": 1}})
        route = "/api/conversation/discard"
        self.assertEqual(self.post(route, {"document_scope": self.scope}), (200, {"discarded": True}))
        stopped = self.store.get(self.scope, self.document)
        self.assertTrue(stopped["analysis"]["review_stopped"])
        self.assertTrue(self.store.chunks(self.scope, self.document)["chunks"])
        self.assertFalse(self.store.get(second, outside["id"])["analysis"].get("review_stopped"))
        self.assertEqual(self.post(route, {"document_scope": self.scope})[0], 200)
        self.assertEqual(self.store.get(self.scope, self.document)["analysis"]["version"], stopped["analysis"]["version"])
        self.assertEqual(self.post(route, {})[0], 400)

    def test_a_working_store_is_unaffected(self):
        status, body = self.interview()
        self.assertEqual(status, 200, body)
        self.assertEqual(self.client.interviews[-1]["_supporting_documents"]["documents"][0]["id"], self.document)

    def test_a_store_damaged_while_the_app_runs_gets_its_own_code_on_every_scoped_route(self):
        self.break_store()
        self.assert_store_failure(self.interview())
        self.assertEqual(self.client.interviews, [], "Nothing was sent to the interviewer")
        for path in ("/api/draft", "/api/workflow"):
            self.assert_store_failure(self.post(path, {"context": CONTEXT, "turns": TURNS, "document_scope": self.scope}))
        self.assert_store_failure(self.post("/api/agent-team/status", {"run_id": "", "document_scope": self.scope}))
        self.assert_store_failure(self.post("/api/conversation/discard", {"document_scope": self.scope}))
        # The same turn without the file workspace still gets its question.
        status, body = self.interview(scoped=False)
        self.assertEqual((status, body.get("question")), (200, "What happens next?"), body)
        events = [json.loads(line)["event"] for line in self.httpd.diagnostics_path.read_text(encoding="utf-8").splitlines()]
        self.assertIn("document_store_failed", events)

    def test_every_kind_of_storage_error_is_reported_the_same_way_without_its_text(self):
        for failure in FAILURES:
            with self.subTest(failure=repr(failure)[:50]):
                with patch.object(self.httpd.documents, "supporting_context", side_effect=failure):
                    status, body = self.interview()
                self.assertEqual((status, body.get("code")), (503, "document_store_unavailable"), body)
                self.assertNotIn("PRIVATE", json.dumps(body))

    def test_a_store_that_fails_after_the_provider_answered_is_not_an_unexplained_500(self):
        self.client.during = self.break_store
        self.assert_store_failure(self.interview())
        self.assertEqual(len(self.client.interviews), 1, "The provider had answered; the recheck is what failed")

    def test_the_stores_own_refusals_keep_their_meaning(self):
        other = self.store.create_scope()
        status, body = self.post("/api/interview", {"context": CONTEXT, "turns": TURNS, "action": "answer",
                                                    "document_scope": "x" * 43})
        self.assertEqual(status, 403, body)
        self.assertNotEqual(body.get("code"), "document_store_unavailable")
        # A file that changed during the request is still a 409, not a store failure.
        self.client.during = lambda: self.httpd.documents.action(self.scope, self.document, "remove", "")
        status, body = self.interview()
        self.assertEqual(status, 409, body)
        self.assertEqual(body.get("code"), "document_sources_changed")
        self.assertTrue(other)
        # An ordinary invalid request is still a 400.
        with patch.object(self.httpd.documents, "supporting_context", side_effect=server.documents.DocumentError("Choose at most 20 documents to read.")):
            status, body = self.interview()
        self.assertEqual(status, 400, body)


class FileRequests(Fixture):
    def test_file_routes_report_the_store_failure_with_its_code(self):
        self.break_store()
        for path, payload in (("/api/documents/status", {"scope": self.scope, "context": {}, "turns": []}),
                              ("/api/documents/action", {"scope": self.scope, "id": self.document, "action": "remove"}),
                              ("/api/documents/context", {"scope": self.scope, "query": "invoice"}),
                              ("/api/documents/session", {"context": {}, "turns": [], "current_question": ""})):
            with self.subTest(path=path):
                self.assert_store_failure(self.post(path, payload))

    def test_operating_system_errors_are_store_failures_but_the_stores_refusals_are_not(self):
        payload = {"scope": self.scope, "context": {}, "turns": []}
        for failure in FAILURES:
            with self.subTest(failure=repr(failure)[:50]):
                with patch.object(self.httpd.documents, "listing", side_effect=failure):
                    answer = self.post("/api/documents/status", payload)
                self.assert_store_failure(answer)
                self.assertNotIn("PRIVATE", json.dumps(answer[1]))
        # A workspace this computer does not have keeps its own code and the 403.
        status, body = self.post("/api/documents/status", {**payload, "scope": "x" * 43})
        self.assertEqual((status, body.get("code")), (403, "document_scope_unavailable"), body)
        # A refusal the store raised itself (no error number) is still "not available in this interview".
        with patch.object(self.httpd.documents, "listing", side_effect=PermissionError("Document is not available in this interview.")):
            status, body = self.post("/api/documents/status", payload)
        self.assertEqual(status, 403, body)
        self.assertNotIn("code", body)
        # Anything else unexpected keeps the generic answer.
        with patch.object(self.httpd.documents, "listing", side_effect=RuntimeError("unexpected")):
            status, body = self.post("/api/documents/status", payload)
        self.assertEqual(status, 500, body)
        self.assertNotIn("code", body)

    def test_a_submission_with_files_is_refused_with_the_code_not_left_uncertain(self):
        self.break_store()
        payload = {"submission_key": str(uuid.uuid4()), "context": CONTEXT, "turns": TURNS,
                   "documents": {"scope": self.scope, "documents": [{"id": self.document}]}}
        self.assert_store_failure(self.post("/api/knowledge/submit", payload))
        # Without files the same submission does not touch the file store.
        payload = {"submission_key": str(uuid.uuid4()), "context": CONTEXT, "turns": TURNS}
        status, body = self.post("/api/knowledge/submit", payload)
        self.assertNotEqual(body.get("code"), "document_store_unavailable", body)
        self.assertNotEqual(status, 500, body)


if __name__ == "__main__":
    unittest.main()
