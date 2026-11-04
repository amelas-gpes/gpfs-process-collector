"""Offline document-intake follow-up contracts; no external model requests.

These tests verify sequencing, source boundaries and provider context, not the
semantic quality of a live model's eventual question.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server, interview_payload, interview_result, process_draft


QUESTION = "Who resolves an invoice rejection before the request can proceed?"


def followup_payload():
    payload = interview_payload()
    source = {"id": "doc_intake_page_1", "label": "Page 1", "location": {"page": 1},
              "text": "The AP clerk logs received invoices. A manager approves them by email. "
                      "Rejected invoices are returned for correction; the resolver is not specified."}
    payload.update(action="document_followup", turns=[], _supporting_documents={
        "unconfirmed": True, "pending_documents": [], "documents": [{
            "id": "doc_intake", "name": "Invoice procedure.pdf",
            "review": {"phase": "complete", "review_complete": True, "limitations": []},
            "questions": [{"text": "What is the process called?", "sources": []}],
            "excerpts": [source]}]})
    baseline = server.workflow_previous_capture(None, [])
    step = copy.deepcopy(process_draft()["steps"][0])
    step["evidence_turns"] = [source["id"]]
    baseline["workflow"].update(title="Invoice approval", steps=[step],
                                open_questions=["Who resolves a rejected invoice?"])
    baseline.update(summary="Invoices are logged and routed for manager approval.",
                    focus="Invoice rejection ownership", parking_lot=["Historical invoice retention"])
    next(finding for finding in baseline["memo_findings"] if finding["key"] == "lifecycle").update(
        status="captured", answer=source["text"], evidence_turns=[source["id"]])
    payload["previous_capture"] = baseline
    return payload


def candidate_for(payload):
    result = interview_result()
    result.update(question="What is the process called?",
                  memo_findings=copy.deepcopy(payload["previous_capture"]["memo_findings"]))
    return result


def provider(payload):
    client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-followup-never-real"})
    client.structured = Mock(side_effect=[candidate_for(payload), {"question": QUESTION}])
    return client


class DocumentFollowupTests(unittest.TestCase):
    def test_source_sequence_takes_precedence_over_a_derived_baseline_gap(self):
        payload = followup_payload()
        source = payload["_supporting_documents"]["documents"][0]["excerpts"][0]
        source["text"] = ("Step,Owner,Action,Condition,Next\n"
                          "4,Finance,Record approval and notify requester,"
                          "Requests above 5000 require director approval before recording,End")
        unsupported_gap = "After director approval for requests above 5000, what happens next?"
        baseline = payload["previous_capture"]
        baseline["workflow"]["open_questions"] = [unsupported_gap]
        baseline["summary"] = "The handoff after director approval is unknown."
        baseline["parking_lot"] = [unsupported_gap]
        replacement = "Finance records the approval and notifies the requester. How does Finance receive the director's approval?"
        candidate = candidate_for(payload)
        candidate["question"] = unsupported_gap
        client = provider(payload)
        client.structured.side_effect = [candidate, {"question": replacement}]

        self.assertEqual(client.interview(payload)["question"], replacement)
        for call in client.structured.call_args_list:
            instructions, sent = call.args[:2]
            # The real contradiction reaches both passes with the precedence
            # rule; an echoed baseline gap must not become a participant unknown.
            self.assertIn(unsupported_gap, sent["previous_capture"]["workflow"]["open_questions"])
            self.assertEqual(sent["supporting_documents"]["documents"][0]["excerpts"][0], source)
            self.assertIn("Exact source statements take precedence over a conflicting baseline gap", instructions)
            self.assertIn("A known next step and an unknown\nhandoff mechanism are different information needs", instructions)
            self.assertIn("Do not invent the mechanism", instructions)
            self.assertIn("silently try to answer it from the exact source text", instructions)
        self.assertEqual(baseline["workflow"]["open_questions"], [unsupported_gap],
                         "Question-only follow-up must not rewrite the accepted map")

    def test_only_document_followup_question_audit_uses_the_configured_audit_model(self):
        for action in ("document_followup", "answer"):
            with self.subTest(action=action):
                payload = followup_payload() if action == "document_followup" else interview_payload()
                candidate = candidate_for(payload) if action == "document_followup" else interview_result()
                client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-model-routing",
                                             "INTERVIEW_MODEL": "synthetic-interviewer",
                                             "WORKFLOW_AUDIT_MODEL": "synthetic-evidence-auditor"})
                responses = [candidate, {"question": QUESTION}]
                client.request = Mock(side_effect=[{"status": "completed", "output": [{"content": [
                    {"type": "output_text", "text": json.dumps(value)}]}]} for value in responses])
                client.interview(payload)
                expected_audit = "synthetic-evidence-auditor" if action == "document_followup" else "synthetic-interviewer"
                self.assertEqual([call.args[1]["model"] for call in client.request.call_args_list],
                                 ["synthetic-interviewer", expected_audit])

    def test_document_first_followup_and_audit_both_receive_validated_baseline(self):
        payload = followup_payload()
        original = copy.deepcopy(payload)
        client = provider(payload)
        result = client.interview(payload)

        self.assertEqual(result["question"], QUESTION)
        self.assertEqual(client.structured.call_count, 2, "Document-only interviews still need the question audit")
        catalog = server.document_evidence_catalog(payload["_supporting_documents"])
        expected = server.workflow_previous_capture(payload["previous_capture"], [], catalog)
        first, audit = client.structured.call_args_list
        for call in (first, audit):
            self.assertEqual(call.args[1]["previous_capture"], expected)
            self.assertEqual(call.args[1]["supporting_documents"], payload["_supporting_documents"])
            self.assertEqual(call.args[1]["turns"], [])
            self.assertIn(server.DOCUMENT_FOLLOWUP_INSTRUCTIONS, call.args[0])
        self.assertEqual(first.args[1]["action"], "document_followup")
        self.assertEqual(audit.args[3], "process_next_question_audit")
        self.assertEqual(audit.args[2], server.NEXT_QUESTION_SCHEMA)
        self.assertEqual(audit.args[1]["candidate_question"], "What is the process called?")
        lifecycle = next(f for f in audit.args[1]["memo_findings"] if f["key"] == "lifecycle")
        self.assertEqual(lifecycle["status"], "partial", "A completed file review is not participant confirmation")
        self.assertFalse(result["ready_for_draft"])
        self.assertEqual(payload, original, "Validation must not mutate the accepted browser baseline")

    def test_baseline_is_required_and_schema_checked_before_any_model_request(self):
        for baseline in (None, {}, {"workflow": {}}):
            with self.subTest(baseline=baseline):
                payload = followup_payload()
                payload["previous_capture"] = baseline
                client = provider(followup_payload())
                with self.assertRaises(ValueError):
                    client.interview(payload)
                client.structured.assert_not_called()

    def test_baseline_cannot_authorize_a_fabricated_document_source(self):
        payload = followup_payload()
        payload["previous_capture"]["workflow"]["steps"][0]["evidence_turns"] = ["doc_forged_source"]
        client = provider(payload)
        with self.assertRaisesRegex(ValueError, "missing or non-participant evidence"):
            client.interview(payload)
        client.structured.assert_not_called()

    def test_review_must_be_complete_in_server_owned_context(self):
        for phase in (None, "pending", "quick", "deep", "error"):
            with self.subTest(phase=phase):
                payload = followup_payload()
                payload["_supporting_documents"]["documents"][0]["review"]["phase"] = phase
                payload.update(review_complete=True, documents_ready=True, baseline_complete=True)
                client = provider(payload)
                with self.assertRaisesRegex(ValueError, "Finish reviewing"):
                    client.interview(payload)
                client.structured.assert_not_called()

    def test_any_second_active_or_pending_file_blocks_early_followup(self):
        for second in ("indexed", "pending"):
            with self.subTest(second=second):
                payload = followup_payload()
                supporting = payload["_supporting_documents"]
                if second == "indexed":
                    document = copy.deepcopy(supporting["documents"][0])
                    document.update(id="doc_second", review={"phase": "quick"})
                    supporting["documents"].append(document)
                else:
                    supporting["pending_documents"].append({"id": "doc_second", "status": "queued"})
                client = provider(payload)
                with self.assertRaisesRegex(ValueError, "Finish reviewing"):
                    client.interview(payload)
                client.structured.assert_not_called()

    def test_completed_limited_review_is_allowed_without_claiming_full_coverage(self):
        payload = followup_payload()
        document = payload["_supporting_documents"]["documents"][0]
        document["review"].update(review_complete=False, limitations=["One image has no readable text"])
        document["context_coverage"] = {"complete_text": False, "selection": "selected excerpts"}
        payload.update(review_complete=True, completion_claim="FORGED_COMPLETION_CLAIM")
        client = provider(payload)
        self.assertEqual(client.interview(payload)["question"], QUESTION)
        for call in client.structured.call_args_list:
            sent = call.args[1]
            self.assertNotIn("FORGED_COMPLETION_CLAIM", json.dumps(sent))
            self.assertFalse(sent["supporting_documents"]["documents"][0]["review"]["review_complete"])
            self.assertIn("limited coverage", call.args[0])

    def test_retained_sources_preserve_baseline_but_do_not_count_as_active_review(self):
        payload = followup_payload()
        supporting = payload["_supporting_documents"]
        retained = {**supporting["documents"][0]["excerpts"][0], "id": "doc_archived_page_1",
                    "document_id": "doc_archived", "retained_only": True, "archived": True}
        supporting["retained_evidence"] = [retained]
        payload["previous_capture"]["workflow"]["steps"][0]["evidence_turns"] = [retained["id"]]
        client = provider(payload)
        self.assertEqual(client.interview(payload)["question"], QUESTION)
        self.assertEqual(client.structured.call_args_list[1].args[1]["previous_capture"]["workflow"]["steps"][0]
                         ["evidence_turns"], [retained["id"]])
        supporting["documents"] = []
        client = provider(payload)
        with self.assertRaisesRegex(ValueError, "Finish reviewing"):
            client.interview(payload)
        client.structured.assert_not_called()

    def test_invalid_candidate_or_empty_audit_is_rejected(self):
        payload = followup_payload()
        client = provider(payload)
        bad = candidate_for(payload)
        bad["memo_findings"][0].update(status="partial", answer="Invented", evidence_turns=["doc_missing"])
        client.structured.side_effect = [bad, {"question": QUESTION}]
        with self.assertRaises(server.APIError):
            client.interview(payload)
        self.assertEqual(client.structured.call_count, 1)
        client = provider(payload)
        client.structured.side_effect = [candidate_for(payload), {"question": " "}]
        with self.assertRaisesRegex(server.APIError, "Audited next question is required"):
            client.interview(payload)


class DocumentFollowupHTTPTests(unittest.TestCase):
    def setUp(self):
        local = Path(__file__).resolve().parents[1] / ".local" / "document-followup-tests"
        if sys.platform == "win32" and not str(local).startswith("\\\\?\\"):
            # Deep fixture paths exceed MAX_PATH from a nested checkout; an
            # extended-length root lets them be created and cleaned up.
            local = Path("\\\\?\\" + str(local))
        local.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="http-", dir=local)
        self.payload = followup_payload()
        self.client = provider(self.payload)
        # These HTTP fixtures isolate source hydration and the follow-up adapter.
        # The real manager's completion boundary is exercised separately.
        self.client.coordinator.interview = self.client.interview
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / "documents")
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        store = self.httpd.documents_store
        self.scope = store.create_scope()
        record = store.add(self.scope, "procedure.csv", b"step,owner\nRecord invoice,AP clerk\nApprove invoice,Manager\n")
        self.record = store.extract(self.scope, record["id"])
        store.update(self.scope, record["id"], {"analysis": {"phase": "complete", "review_complete": True}})
        source = store.chunks(self.scope, record["id"])["chunks"][0]
        baseline = self.payload["previous_capture"]
        baseline["workflow"]["steps"][0]["evidence_turns"] = [source["id"]]
        next(f for f in baseline["memo_findings"] if f["key"] == "lifecycle")["evidence_turns"] = [source["id"]]
        self.payload.update(document_scope=self.scope, document_evidence=[{"id": "FORGED_SOURCE_CATALOG"}],
                            completion_claim="FORGED_COMPLETION_CLAIM")
        self.payload["_supporting_documents"]["documents"][0]["name"] = "FORGED_SUPPORTING_FILE"
        self.client.structured.side_effect = [candidate_for(self.payload), {"question": QUESTION}]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=2)
        self.temporary.cleanup()

    def post(self):
        request = Request(self.url + "/api/interview", data=json.dumps(self.payload).encode(), headers={
            "Origin": self.url, "X-CSRF-Token": self.httpd.csrf_token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_http_uses_scoped_store_for_review_state_and_exact_sources(self):
        status, result = self.post()
        self.assertEqual(status, 200, result)
        self.assertEqual(result["question"], QUESTION)
        expected = self.httpd.documents_store.chunks(self.scope, self.record["id"])["chunks"]
        for call in self.client.structured.call_args_list:
            sent = call.args[1]
            self.assertEqual(sent["supporting_documents"]["documents"][0]["excerpts"], expected)
            for forbidden in ("FORGED_SUPPORTING_FILE", "FORGED_SOURCE_CATALOG", "FORGED_COMPLETION_CLAIM", self.scope):
                self.assertNotIn(forbidden, json.dumps(sent))

    def test_http_rechecks_store_when_client_claims_review_is_complete(self):
        self.httpd.documents_store.update(self.scope, self.record["id"], {"analysis": {"phase": "deep"}})
        self.payload.update(review_complete=True, documents_ready=True)
        status, result = self.post()
        self.assertEqual(status, 400, result)
        self.assertIn("Finish reviewing", result["error"])
        self.client.structured.assert_not_called()

    def test_another_scope_cannot_supply_review_or_evidence(self):
        self.payload["document_scope"] = self.httpd.documents_store.create_scope()
        status, result = self.post()
        self.assertEqual(status, 400, result)
        self.client.structured.assert_not_called()


if __name__ == "__main__":
    unittest.main()
