"""Trace a scoped CSV upload, retried background review and an interview recovery over loopback."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

import test_document_api
from test_document_api import FakeProvider
from test_recovery_copy import interview
from test_server import server


class RawJourney(unittest.TestCase):
    request = test_document_api.DocumentHTTPTests.request
    ready = test_document_api.DocumentHTTPTests.ready

    def test_file_retry_and_recovery_trace_the_observed_request_and_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            client = FakeProvider()
            httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                documents_root=root / "documents", knowledge_root=root / "knowledge",
                knowledge_settings={"RAW_TRACE_MODE": "content"})
            self.httpd, self.url = httpd, f"http://127.0.0.1:{httpd.server_port}"
            worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            worker.start()
            tab, interview_id = str(uuid.uuid4()), str(uuid.uuid4())

            def send(route, data, operation, **headers):
                status, _, raw = self.request(route, data, {"X-Trace-Producer": tab, "X-Trace-Interview": interview_id,
                    "X-Trace-Operation": operation, **headers})
                self.assertIn(status, (200, 202), raw)
                return json.loads(raw)

            try:
                upload_op, context_op, restore_op = (str(uuid.uuid4()) for _ in range(3))
                scope = send("/api/documents/session", {"context": {}, "turns": []}, str(uuid.uuid4()))["scope"]
                source = b"field,value\ninvoice,SYNTHETIC-PRIVATE-SOURCE-NEVER-LOG\n"
                analyze = client.analyze_document
                calls = []

                def fail_once(*args):
                    calls.append(args[3])
                    if len(calls) == 1:
                        raise server.APIError("Fictional retry", 502, "timeout", transient=True)
                    return analyze(*args)

                service = server.local_module("document_service", "document_service.py")
                with patch.object(service, "RETRY_DELAYS", (.001,)), patch.object(client, "analyze_document", side_effect=fail_once):
                    doc = send("/api/documents/upload", source, upload_op,
                        **{"X-Document-Filename": "Fictional.csv", "X-Document-Scope": scope})["document"]
                    self.ready(scope, doc["id"])
                view = send("/api/documents/context", {"scope": scope, "query": "invoice"}, context_op)
                references = [row["id"] for row in view["document_evidence"]]
                self.assertTrue(references)
                saved = interview()
                recovery_id = uuid.uuid4().hex
                send("/api/recovery/setting", {"enabled": True}, str(uuid.uuid4()))
                send("/api/recovery/save", {"id": recovery_id, "session": saved}, str(uuid.uuid4()))
                restored = send("/api/recovery/load", {"id": recovery_id}, restore_op)
                self.assertEqual(restored["draft"]["session"], saved)
            finally:
                httpd.shutdown()
                httpd.server_close()
                worker.join(3)

            rows = [json.loads(line) for file in (root / "raw-trace").glob("*.jsonl")
                    for line in file.read_text("utf8").splitlines()]
            self.assertTrue(rows)
            upload = [r for r in rows if r.get("operation_id") == upload_op]
            attempts = [r["payload"] for r in upload if r["type"] == "document.review_attempt"]
            self.assertEqual([r["attempt"] for r in attempts if r["phase"] == "quick"], [1, 2])
            self.assertEqual(attempts[0]["source_ids"], attempts[1]["source_ids"])
            self.assertEqual(next(r["payload"]["bytes"] for r in upload if r["type"] == "document.upload_read"), len(source))
            self.assertTrue(all(r.get("interview_id") == interview_id and r.get("tab_id") == tab for r in upload))
            selected = next(r["payload"]["documents"] for r in rows
                if r.get("operation_id") == context_op and r["type"] == "document.selection")
            self.assertEqual(selected[0]["source_ids"], references)
            restored_events = [r for r in rows if r.get("operation_id") == restore_op and r["type"].startswith("http.")]
            self.assertEqual([r["type"] for r in restored_events], ["http.received", "http.json_parsed", "http.response_write"])
            self.assertEqual(restored_events[-1]["payload"]["status"], 200)
            self.assertTrue(restored_events[-1]["payload"]["written"])
            for omitted in (scope, recovery_id, saved["unsent_answer"], "SYNTHETIC-PRIVATE-SOURCE-NEVER-LOG"):
                self.assertNotIn(omitted, json.dumps(rows))
