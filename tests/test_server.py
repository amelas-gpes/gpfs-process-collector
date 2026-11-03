"""Focused offline tests for the interviewer's trust boundaries.

Run with the existing Python runtime; these tests never send model requests.
"""

import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("voice_interviewer_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)


def interview_payload():
    return {
        "context": {
            "process_name": "Invoice approval",
            "process_owner": "AP team",
            "objective": "Capture the current process and its exceptions",
            "background": "Synthetic test fixture, not an actual company process",
            "meeting_minutes": 60,
        },
        "turns": [
            {"id": "a1", "role": "assistant", "text": "What starts the process?"},
            {
                "id": "u1",
                "role": "user",
                "text": "An AP clerk checks the shared mailbox each weekday and logs invoices in a spreadsheet.",
            },
            {"id": "a2", "role": "assistant", "text": "What happens next?"},
            {
                "id": "u2",
                "role": "user",
                "text": "A manager approves by email. Invoices that do not match the purchase order go to the buyer.",
            },
        ],
        "action": "answer",
        "session": {"elapsed_minutes": 12},
    }


def memo_findings():
    findings = [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                for key in server.COVERAGE]
    by_key = {finding["key"]: finding for finding in findings}
    by_key["name"].update(status="captured", answer="Invoice approval", evidence_turns=["context"])
    by_key["lifecycle"].update(status="partial", answer="Invoices are logged by the AP clerk, then approved by a manager or referred to the buyer.", evidence_turns=["u1", "u2"])
    return findings


def interview_result():
    return {
        "question": "Who releases payment after the manager approves?",
        "summary": "The AP clerk logs invoices and a manager approves by email.",
        "ready_for_draft": True,
        "focus": "Understand the normal invoice route and its finish condition",
        "parking_lot": ["Payment-release ownership remains unknown"],
        "closure": {"asked": False, "confirmed": False},
        "memo_findings": memo_findings(),
        "coverage": [{"key": key, "label": label, "status": "partial"} for key, label in server.COVERAGE.items()],
    }


def process_variation(evidence=None):
    return {
        "applies_to": "Fund B",
        "difference": "Unmatched invoices are routed to the buyer in a ticketing tool.",
        "reason": "UNKNOWN", "cost": "UNKNOWN", "charging": "UNKNOWN", "removability": "UNKNOWN",
        "boundary": "variation", "boundary_reason": "The participant reported that the trigger, accountable role, and finished result remain the same.",
        "evidence_turns": evidence if evidence is not None else ["u3"],
    }


def process_draft():
    return {
        "title": "Invoice approval",
        "overview": "Draft based on a synthetic interview; requires process-owner review.",
        "trigger": "Invoices arrive in the shared mailbox",
        "inputs": ["Invoices", "Purchase orders"],
        "outputs": ["Email approval or referral to the buyer"],
        "steps": [
            {
                "id": "s1", "title": "Log received invoices", "type": "activity",
                "actor": "AP clerk", "system": "Shared mailbox and spreadsheet",
                "description": "Check the shared mailbox each weekday and log invoices.",
                "evidence_turns": ["u1"],
                "input": "Invoice received in the shared mailbox", "output": "Logged invoice",
                "completion_criteria": "Invoice has been logged in the spreadsheet", "handoff": "Manager; submission method UNKNOWN",
            },
            {
                "id": "s2", "title": "Approve invoice", "type": "activity",
                "actor": "Manager", "system": "Email",
                "description": "Approve the invoice by email.", "evidence_turns": ["u2"],
                "input": "Invoice", "output": "Email approval", "completion_criteria": "Approval sent by email",
                "handoff": "UNKNOWN; payment-release owner not established",
            },
        ],
        "connections": [{"from": "s1", "to": "s2", "label": "Submitted for approval", "evidence_turns": ["u1", "u2"]}],
        "exceptions": ["Invoices that do not match the purchase order go to the buyer."],
        "controls": [],
        "open_questions": ["Who releases payment, and what checks do they perform?"],
        "validation_notes": ["No payment-release role or control was provided."],
        "memo_summary": memo_findings(),
        "lifecycle_items": [{"item": "Invoice", "stages": ["Received", "Logged", "Manager approval"],
                             "locations": ["Shared mailbox", "Spreadsheet", "Email"],
                             "handoffs": ["AP clerk to manager"], "evidence_turns": ["u1", "u2"]}],
        "variations": [],
    }


class EvidenceValidationTests(unittest.TestCase):
    def test_accepts_a_draft_supported_by_interview_answers(self):
        payload = interview_payload()
        server.validate_payload(payload, require_answers=True)
        server.validate_draft(process_draft(), payload["turns"])

    def test_duplicate_turn_ids_cannot_make_evidence_ambiguous(self):
        payload = interview_payload()
        payload["turns"][-1]["id"] = "u1"
        with self.assertRaises(ValueError):
            server.validate_payload(payload)

    def test_a_system_message_cannot_be_smuggled_in_as_an_answer(self):
        payload = interview_payload()
        payload["turns"][-1]["role"] = "system"
        with self.assertRaises(ValueError):
            server.validate_payload(payload)

    def test_a_procedure_requires_some_user_evidence(self):
        payload = interview_payload()
        payload["turns"] = [payload["turns"][0]]
        with self.assertRaises(ValueError):
            server.validate_payload(payload, require_answers=True)

    def test_step_evidence_cannot_reference_invented_turns(self):
        draft = process_draft()
        draft["steps"][0]["evidence_turns"] = ["invented-user-answer"]
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_agent_question_is_not_user_evidence(self):
        draft = process_draft()
        draft["steps"][0]["evidence_turns"] = ["a1"]
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_graph_edges_cannot_reference_nonexistent_steps(self):
        draft = process_draft()
        draft["connections"][0]["to"] = "missing-step"
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_graph_nodes_need_unique_ids(self):
        draft = process_draft()
        draft["steps"][1]["id"] = draft["steps"][0]["id"]
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_map_connections_need_their_own_source_evidence(self):
        draft = process_draft()
        draft["connections"][0]["evidence_turns"] = []
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_map_connections_cannot_cite_questions_or_invented_turns(self):
        for evidence in (["a1"], ["fabricated-turn"]):
            with self.subTest(evidence=evidence):
                draft = process_draft()
                draft["connections"][0]["evidence_turns"] = evidence
                with self.assertRaises(ValueError):
                    server.validate_draft(draft, interview_payload()["turns"])

    def test_all_eleven_memo_topics_are_included_even_when_unknown(self):
        draft = server.validate_draft(process_draft(), interview_payload()["turns"])
        self.assertEqual(len(draft["memo_summary"]), 11)
        self.assertEqual({item["key"] for item in draft["memo_summary"]}, set(server.COVERAGE))
        self.assertTrue(any(item["status"] == "unknown" and not item["evidence_turns"] for item in draft["memo_summary"]))

    def test_reported_memo_findings_require_evidence(self):
        for status in ("captured", "partial", "not_applicable"):
            for kind in ("interview", "draft"):
                with self.subTest(status=status, kind=kind):
                    result = interview_result() if kind == "interview" else process_draft()
                    findings = result["memo_findings" if kind == "interview" else "memo_summary"]
                    findings[0].update(status=status, evidence_turns=[])
                    validate = server.validate_interview if kind == "interview" else server.validate_draft
                    with self.assertRaises(ValueError):
                        validate(result, interview_payload()["turns"])

    def test_missing_memo_topic_is_rejected_in_interview_and_draft(self):
        for kind in ("interview", "draft"):
            with self.subTest(kind=kind):
                result = interview_result() if kind == "interview" else process_draft()
                result["memo_findings" if kind == "interview" else "memo_summary"].pop()
                validate = server.validate_interview if kind == "interview" else server.validate_draft
                with self.assertRaises(ValueError):
                    validate(result, interview_payload()["turns"])

    def test_memo_coverage_and_finding_statuses_are_distinct_contracts(self):
        result = interview_result()
        result["coverage"][0]["status"] = "captured"
        with self.assertRaises(ValueError):
            server.validate_interview(result, interview_payload()["turns"])
        result = interview_result()
        result["memo_findings"][0]["status"] = "covered"
        with self.assertRaises(ValueError):
            server.validate_interview(result, interview_payload()["turns"])

    def test_variations_cannot_cite_questions_or_nonexistent_answers(self):
        for evidence in (["a1"], ["invented-turn"], []):
            with self.subTest(evidence=evidence):
                draft = process_draft()
                draft["variations"] = [process_variation(evidence)]
                with self.assertRaises(ValueError):
                    server.validate_draft(draft, interview_payload()["turns"])

    def test_supported_variation_and_lifecycle_metadata_are_retained(self):
        payload = interview_payload()
        payload["turns"].append({"id": "u3", "role": "user", "text": "For Fund B we use the ticketing tool to route unmatched invoices to the buyer. The trigger, accountable role, and finished result remain the same; I do not know the cost, charging, or reason."})
        draft = process_draft()
        draft["variations"] = [process_variation()]
        result = server.validate_draft(draft, payload["turns"])
        self.assertEqual(result["variations"][0]["cost"], "UNKNOWN")
        self.assertEqual(result["variations"][0]["evidence_turns"], ["u3"])
        self.assertEqual(result["lifecycle_items"][0]["item"], "Invoice")
        self.assertEqual(result["steps"][0]["output"], "Logged invoice")
        self.assertIn("UNKNOWN", result["steps"][1]["handoff"])

    def test_closure_cannot_be_confirmed_without_a_completeness_check(self):
        result = interview_result()
        result["closure"] = {"asked": False, "confirmed": True}
        with self.assertRaises(ValueError):
            server.validate_interview(result, interview_payload()["turns"])


class ClosureEnforcementTests(unittest.TestCase):
    def test_confirmation_cannot_precede_any_actual_final_check(self):
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, interview_payload()["turns"], "answer")
        self.assertFalse(checked["closure"]["confirmed"])

    def test_an_unanswered_final_check_cannot_be_confirmed(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": False})

    def test_participant_text_cannot_masquerade_as_the_final_check(self):
        turns = interview_payload()["turns"] + [
            {"id": "u3", "role": "user", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u4", "role": "user", "text": "No, that is all."},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        self.assertFalse(server.enforce_closure(result, turns, "answer")["closure"]["confirmed"])

    def test_actual_reply_after_final_check_can_remain_confirmed(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "No, nothing else. This captures my account."},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": True})

    def test_asked_state_is_preserved_when_model_forgets_it(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "There is one more exception to explain."},
        ]
        result = interview_result()
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": False})

    def test_new_final_check_needs_a_new_participant_reply(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "No, that is all."},
            {"id": "a4", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " after that correction?"},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": False})


class UpstreamErrorTests(unittest.TestCase):
    def test_exhausted_credit_balance_is_quota_error_not_temporary_rate_limit(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-test-sentinel-not-a-real-credential"})
        details = {"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota",
                             "message": "Synthetic exhausted-credit response"}}
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 429, "Too Many Requests", {},
                                       io.BytesIO(json.dumps(details).encode()))
        with patch.object(server, "urlopen", side_effect=error) as network:
            with self.assertRaises(server.APIError) as caught:
                client.request("responses", {"model": "synthetic-test"})
        network.assert_called_once()
        message = str(caught.exception).lower()
        self.assertIn("no available api quota", message)
        self.assertIn("billing", message)
        self.assertNotIn("wait", message)
        self.assertNotIn("rate limit", message)


class HTTPBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_key = "sk-test-sentinel-not-a-real-credential"
        cls.client = server.OpenAIClient({"OPENAI_API_KEY": cls.test_key})
        cls.client.request = Mock()
        cls.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=cls.client)
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=3)

    def setUp(self):
        self.client.request.reset_mock(side_effect=True, return_value=True)
        self.client.request.side_effect = self.upstream_response
        self.mock_draft = process_draft()
        self.mock_interview = interview_result()

    def upstream_response(self, path, body, *args, **kwargs):
        if path == "audio/transcriptions":
            return {"text": "A synthetic recorded answer."}
        result = self.mock_draft if body["text"]["format"]["name"] in ("process_draft", "process_draft_audit") else self.mock_interview
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}]}

    def request(self, path, payload=None, headers=None, method=None, csrf=True):
        request_headers = {}
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            if csrf:
                request_headers["X-CSRF-Token"] = self.httpd.csrf_token
            payload = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        request_headers.update(headers or {})
        req = urllib.request.Request(self.url + path, data=payload, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_public_config_exposes_no_credential(self):
        status, headers, raw = self.request("/api/config")
        self.assertEqual(status, 200)
        config = json.loads(raw)
        self.assertTrue(config["api_configured"])
        self.assertEqual(config["app_id"], "voice-interviewer")
        self.assertEqual(config["csrf_token"], self.httpd.csrf_token)
        self.assertNotIn(self.test_key.encode(), raw)
        self.assertNotIn("OPENAI_API_KEY", raw.decode())
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_nonlocal_bind_is_rejected(self):
        with self.assertRaises(ValueError):
            server.InterviewServer(("0.0.0.0", 0), server.Handler, client=self.client)

    def test_host_header_rebinding_is_rejected(self):
        status, _, _ = self.request("/api/config", headers={"Host": "attacker.example"})
        self.assertEqual(status, 403)

    def test_cross_site_reads_and_writes_are_rejected(self):
        for path, payload in (("/api/config", None), ("/api/interview", interview_payload())):
            with self.subTest(path=path):
                status, _, _ = self.request(path, payload, headers={"Origin": "https://attacker.example"})
                self.assertEqual(status, 403)
        status, _, _ = self.request("/api/config", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.client.request.assert_not_called()

    def test_mutating_requests_need_the_current_csrf_token(self):
        for headers in ({}, {"X-CSRF-Token": "incorrect-token"}):
            with self.subTest(headers=headers):
                status, _, _ = self.request("/api/interview", interview_payload(), headers=headers, csrf=False)
                self.assertEqual(status, 403)
        self.client.request.assert_not_called()

    def test_secret_and_source_files_are_not_served(self):
        for path in ("/.env.local", "/../.env.local", "/%2e%2e/.env.local", "/server.py", "/tests/test_server.py"):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404)

    def test_json_media_type_and_valid_json_are_required(self):
        status, _, _ = self.request("/api/interview", interview_payload(), headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _, raw = self.request("/api/interview", b"{broken-json")
        self.assertEqual(status, 400)
        self.assertIn("Invalid JSON", json.loads(raw)["error"])
        self.client.request.assert_not_called()

    def test_oversized_request_is_rejected_before_read_or_model_call(self):
        status, _, _ = self.request("/api/interview", b"{}", headers={"Content-Length": str(server.MAX_JSON + 1)})
        self.assertEqual(status, 413)
        self.client.request.assert_not_called()

    def test_invalid_interview_role_is_rejected_before_model_call(self):
        payload = interview_payload()
        payload["turns"][-1]["role"] = "system"
        status, _, _ = self.request("/api/interview", payload)
        self.assertEqual(status, 400)
        self.client.request.assert_not_called()

    def test_valid_interview_uses_stateless_strict_structured_output(self):
        status, _, raw = self.request("/api/interview", interview_payload())
        self.assertEqual(status, 200)
        self.assertIn("releases payment", json.loads(raw)["question"])
        self.client.request.assert_called_once()
        path, body = self.client.request.call_args.args
        self.assertEqual(path, "responses")
        self.assertIs(body["store"], False)
        self.assertIs(body["text"]["format"]["strict"], True)
        self.assertNotIn(self.test_key, json.dumps(body))

    def test_draft_without_answers_is_rejected_before_model_call(self):
        payload = interview_payload()
        payload["turns"] = []
        status, _, _ = self.request("/api/draft", payload)
        self.assertEqual(status, 400)
        self.client.request.assert_not_called()

    def test_draft_is_labelled_for_human_review(self):
        status, _, raw = self.request("/api/draft", interview_payload())
        self.assertEqual(status, 200)
        draft = json.loads(raw)["draft"]
        self.assertTrue(any("Process-owner review is required" in note for note in draft["validation_notes"]))
        self.assertEqual(draft["steps"][0]["evidence_turns"], ["u1"])
        self.assertIn("Who releases payment", draft["open_questions"][0])

    def test_invented_model_evidence_is_not_returned_as_a_valid_draft(self):
        self.mock_draft["steps"][0]["evidence_turns"] = ["fabricated-turn"]
        status, _, raw = self.request("/api/draft", interview_payload())
        self.assertEqual(status, 502)
        self.assertIn("error", json.loads(raw))
        self.assertNotIn("draft", json.loads(raw))

    def test_transcription_rejects_non_audio_without_model_call(self):
        status, _, _ = self.request("/api/transcribe", b"x" * 200, headers={"Content-Type": "text/html"})
        self.assertEqual(status, 400)
        self.client.request.assert_not_called()

    def test_api_failure_does_not_leak_key(self):
        self.client.request.side_effect = server.APIError("A controlled upstream test failure.")
        status, _, raw = self.request("/api/interview", interview_payload())
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(raw)["error"], "A controlled upstream test failure.")
        self.assertNotIn(self.test_key.encode(), raw)

    def test_close_action_asks_a_completeness_check_without_confirming_it(self):
        payload = interview_payload()
        payload["action"] = "close"
        repetitive_gap = "Who releases payment after the manager approves?"
        self.mock_interview["question"] = repetitive_gap
        self.mock_interview["closure"] = {"asked": False, "confirmed": False}
        status, _, raw = self.request("/api/interview", payload)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertEqual(result["closure"], {"asked": True, "confirmed": False})
        self.assertTrue(result["question"].startswith(server.FINAL_CHECK_PREFIX))
        self.assertNotEqual(result["question"], repetitive_gap)
        self.assertIn("haven't captured", result["question"])
        sent = json.loads(self.client.request.call_args.args[1]["input"][0]["content"])
        self.assertEqual(sent["action"], "close")

    def test_close_action_replaces_a_blank_model_question_before_validation(self):
        payload = interview_payload()
        payload["action"] = "close"
        self.mock_interview["question"] = ""
        self.mock_interview["closure"] = {"asked": False, "confirmed": False}
        status, _, raw = self.request("/api/interview", payload)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertTrue(result["question"].startswith(server.FINAL_CHECK_PREFIX))
        self.assertEqual(result["closure"], {"asked": True, "confirmed": False})

    def test_blank_question_after_confirmed_reply_becomes_an_acknowledgment(self):
        payload = interview_payload()
        payload["turns"].extend([
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "No, nothing else. This captures my account."},
        ])
        self.mock_interview["question"] = "   "
        self.mock_interview["closure"] = {"asked": False, "confirmed": True}
        status, _, raw = self.request("/api/interview", payload)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertEqual(result["closure"], {"asked": True, "confirmed": True})
        self.assertIn("captured for review", result["question"])
        self.assertIn("unknowns remain open", result["question"])
        self.assertNotIn("?", result["question"])

    def test_meeting_time_is_advisory_and_does_not_stop_answers(self):
        for planned, elapsed in ((60, 90), (90, 120)):
            with self.subTest(planned=planned, elapsed=elapsed):
                self.client.request.reset_mock()
                payload = interview_payload()
                payload["context"]["meeting_minutes"] = planned
                payload["session"]["elapsed_minutes"] = elapsed
                status, _, raw = self.request("/api/interview", payload)
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(raw)["question"])
                sent = json.loads(self.client.request.call_args.args[1]["input"][0]["content"])
                self.assertEqual(sent["timing"], {"elapsed_minutes": elapsed, "planned_minutes": planned})

    def test_shutdown_requires_same_origin_and_current_token(self):
        with patch.object(self.httpd, "shutdown") as shutdown:
            for kwargs in ({"csrf": False}, {"headers": {"Origin": "https://attacker.example"}}):
                with self.subTest(kwargs=kwargs):
                    status, _, _ = self.request("/api/shutdown", {}, **kwargs)
                    self.assertEqual(status, 403)
            shutdown.assert_not_called()

    def test_authorized_shutdown_calls_only_the_test_server(self):
        stopped = threading.Event()
        with patch.object(self.httpd, "shutdown", side_effect=stopped.set) as shutdown:
            status, _, raw = self.request("/api/shutdown", {})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)["stopping"])
            self.assertTrue(stopped.wait(timeout=2))
            shutdown.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
