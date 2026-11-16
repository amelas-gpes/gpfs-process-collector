"""A file selection is rechecked and replayed with the files it asked for.

The fast question, its status polls and the release recheck must all resolve
the same reference files, including files the browser asked to have read and a
confirmation's frozen selection. Loopback only; no network providers.
"""
import copy
import time
import unittest
from unittest.mock import patch

import test_concurrent_http
from test_server import server


class DocumentSelectionReplayTests(unittest.TestCase):
    # The loopback harness of the concurrent suite, without running its tests again.
    setUp = test_concurrent_http.ConcurrentHTTPTests.setUp
    tearDown = test_concurrent_http.ConcurrentHTTPTests.tearDown
    post = test_concurrent_http.ConcurrentHTTPTests.post

    def test_source_recheck_passes_the_selection_options_of_the_snapshot(self):
        context = self.client.payload()["context"]
        original = {"documents": [], "source_revision": "one"}
        binding = server.interview_orchestrator.Coordinator._source_binding(context, original)
        for options in ({"required_documents": ["doc_unread"]}, {"frozen": True},
                        {"frozen": True, "required_documents": ["doc_unread"]}, {}):
            payload = {"_conversation_document_snapshot": ("scope", "query", ["source"], context, binding, options)}
            with patch.object(self.httpd.documents, "supporting_context", return_value=copy.deepcopy(original)) as resolve:
                self.assertTrue(self.httpd.validate_conversation_sources(payload))
                resolve.assert_called_once_with("scope", "query", source_ids=["source"], **options)
            with patch.object(self.httpd.documents, "supporting_context", return_value={"documents": [], "source_revision": "two"}):
                self.assertFalse(self.httpd.validate_conversation_sources(payload))

    def test_status_polls_replay_the_files_asked_for_with_the_fast_question(self):
        payload = self.client.payload()
        payload.update(document_scope="controlled-scope-capability", document_required_ids=["doc_unread1"])
        calls = []

        def selected(_scope, query, **kwargs):
            calls.append(kwargs)
            return {"documents": [{"id": "doc_unread1", "context_coverage": {"included_chunks": 2, "total_chunks": 3}}],
                    "omitted_documents": 4, "retrieval_query": query}
        with patch.object(self.httpd.documents, "supporting_context", side_effect=selected):
            status, fast = self.post("/api/conversation/turn", payload)
            self.assertEqual(status, 200, fast)
            reading = {"omitted_documents": 4, "documents": [{"id": "doc_unread1", "included_chunks": 2, "total_chunks": 3}]}
            self.assertEqual(fast["document_reading"], reading)
            payload["conversation_token"] = fast["conversation_token"]
            payload["turns"].append({"id": "shown_fast_question", "role": "assistant", "text": fast["question"]})
            # By now the browser has the file and no longer asks for it; the selection must not change.
            payload["document_required_ids"] = []
            for _ in range(80):
                status, progress = self.post("/api/conversation/status", payload)
                self.assertEqual(status, 200)
                if progress["state"] == "ready":
                    break
                time.sleep(.01)
            self.assertEqual(progress["state"], "ready", progress)
            self.assertIn("capture", progress)
            self.assertEqual(progress["document_reading"], reading)
        self.assertTrue(calls)
        self.assertTrue(all(kwargs.get("required_documents") == ["doc_unread1"] for kwargs in calls), calls)

    def test_a_malformed_list_of_files_to_read_is_refused_before_any_provider_work(self):
        for invalid in ("doc_one", {"id": "doc_one"}, ["doc_x"] * 21):
            payload = self.client.payload()
            payload.update(document_scope="controlled-scope-capability", document_required_ids=invalid)
            with patch.object(self.httpd.documents, "supporting_context", return_value={"documents": []}) as resolve:
                status, result = self.post("/api/conversation/turn", payload)
            self.assertEqual(status, 400, result)
            self.assertEqual(result["error"], "Choose at most 20 documents to read.")
            resolve.assert_not_called()
        self.client.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
