"""Offline readiness stress cases for server-owned interview capabilities."""
import copy
from concurrent.futures import ThreadPoolExecutor
import threading
import sys
import unittest
from unittest.mock import patch

from test_interview_orchestrator import (REVIEW_CALLS, SyntheticTeamProvider, prepared_review, reviewed_capture,
                                         reply_payload, server)


class CancellationRaceTests(unittest.TestCase):
    def failed_review(self):
        client = SyntheticTeamProvider()
        payload, pending = prepared_review(client)
        client.faults["process_coverage_assessment"] = server.APIError("Synthetic provider failure")
        failed = client.coordinator.review(payload)
        client.faults.clear()
        return client, payload, pending, failed

    def test_original_run_capability_cancels_current_explicit_retry(self):
        client, payload, pending, failed = self.failed_review()
        entered, release = threading.Event(), threading.Event()
        def hold(body):
            entered.set()
            self.assertTrue(release.wait(3))
        client.hooks["process_specialist_review"] = hold
        original_status = client.coordinator.status(pending["agent_run_id"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            request = pool.submit(client.coordinator.review, {**payload, "retry_review": True})
            self.assertTrue(entered.wait(3))
            progress = client.coordinator.status(pending["agent_run_id"])
            self.assertEqual(progress["status"], "running")
            self.assertEqual(progress["attempt"], 2)
            self.assertNotEqual(progress["active_run_id"], pending["agent_run_id"])
            self.assertGreater(min(event["sequence"] for event in progress["events"]),
                               max(event["sequence"] for event in original_status["events"]))
            self.assertTrue(client.coordinator.cancel(pending["agent_run_id"])["cancelled"])
            release.set()
            with self.assertRaises(server.APIError) as caught:
                request.result(timeout=4)
        self.assertEqual(caught.exception.status, 409)
        self.assertTrue(client.coordinator.status(pending["agent_run_id"])["cancelled"])
        self.assertTrue(client.coordinator.status(progress["active_run_id"])["cancelled"])
        with self.assertRaises(server.APIError):
            client.coordinator.review({**payload, "retry_review": True})


    def test_pre_registration_cancel_stops_queued_request_without_model_work(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        payload["agent_run_id"] = "pre-cancelled-request-123456789"
        self.assertTrue(client.coordinator.cancel(payload["agent_run_id"])["cancelled"])
        with self.assertRaises(server.APIError) as caught:
            client.coordinator.interview(payload)
        self.assertEqual(caught.exception.status, 409)
        client.request.assert_not_called()

    def test_malformed_falsey_run_identifiers_do_not_start_uncancellable_model_work(self):
        for token in (False, 0, [], {}, "", "short", "x" * 81):
            client = SyntheticTeamProvider()
            payload = client.payload()
            payload["agent_run_id"] = token
            with self.assertRaises(ValueError):
                client.coordinator.interview(payload)
            client.request.assert_not_called()

    def test_cancellation_tombstones_are_bounded_expire_and_reject_malformed_ids(self):
        client = SyntheticTeamProvider()
        for index in range(300):
            client.coordinator.cancel(f"cancelled-{index:024d}")
        self.assertEqual(len(client.coordinator._cancelled_runs), 256)
        for value in ([], {}, 42, None):
            with self.assertRaises(ValueError):
                client.coordinator.cancel(value)
        for value in ("", "short", "a" * 81, "path/" * 8):
            self.assertFalse(client.coordinator.cancel(value)["cancelled"])
        self.assertEqual(len(client.coordinator._cancelled_runs), 256)
        for key in client.coordinator._cancelled_runs:
            client.coordinator._cancelled_runs[key] -= 1801
        client.coordinator.cancel("fresh-cancel-request-123456789")
        self.assertEqual(len(client.coordinator._cancelled_runs), 1)

    def test_duplicate_review_waiter_cannot_replay_after_completed_run_is_cancelled(self):
        client = SyntheticTeamProvider()
        payload, pending = prepared_review(client)
        entered, release = threading.Event(), threading.Event()
        def hold(body):
            entered.set()
            self.assertTrue(release.wait(3))
        client.hooks["process_specialist_review"] = hold
        ticket = client.coordinator._tickets[pending["review_ticket"]]
        original_wait = ticket["event"].wait
        def cancel_before_waiter_reads(timeout):
            done = original_wait(timeout)
            client.coordinator.cancel(pending["agent_run_id"])
            return done
        with patch.object(ticket["event"], "wait", side_effect=cancel_before_waiter_reads):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(client.coordinator.review, payload)
                self.assertTrue(entered.wait(3))
                duplicate = pool.submit(client.coordinator.review, payload)
                release.set()
                first.result(timeout=4)
                with self.assertRaises(server.APIError) as caught:
                    duplicate.result(timeout=4)
        self.assertEqual(caught.exception.status, 409)


class SpokenBoundaryTests(unittest.TestCase):
    def test_incomplete_account_cannot_release_common_completion_phrasing(self):
        forbidden = ["You're all set. Shall we end the interview now?",
                     "This interview is complete. Do you want to save it?",
                     "All eleven sections are captured. Would you like to stop here?",
                     "We are done. Can we conclude?",
                     "Would you like to pause here?",
                     "Can we pause the interview now?",
                     "Is there anything important about volunteer schedule packets that I haven't asked about?",
                     "Is there anything else that we have not captured?",
                     "What else have we missed?",
                     "Have we missed any part of the process?",
                     "Is there any other important detail you want to add?",
                     "Does this cover everything you wanted to share?",
                     "What else should I know before we conclude?",
                     "Are we finished with the process review?",
                     "There are no further questions. Shall we finish now?"]
        for question in forbidden:
            with self.subTest(question=question):
                client = SyntheticTeamProvider()
                client.incomplete()
                client.result_changes["team_interview_capture"] = lambda result: result.update(question=question)
                result = client.coordinator.interview(client.payload())
                self.assertNotEqual(result["question"], question)
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertEqual(result["question"].count("?"), 1)

    def test_review_gap_cannot_release_generic_final_omissions_question(self):
        client = SyntheticTeamProvider()
        payload, _ = prepared_review(client)
        topic = next(item for item in client.assessment["topics"] if item["key"] == "risk")
        topic["gaps"] = ["A reported failure has no established consequence."]
        topic["dimensions"][0]["status"] = "unresolved"
        topic["next_question"] = "Is there anything important about this work that I haven't asked about?"
        result = client.coordinator.review(payload)
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertNotEqual(result["question"], topic["next_question"])

    def test_bundled_or_excessive_question_is_replaced_with_one_bounded_question(self):
        for question in ("Who approves it? Where is the approval recorded?", "Please explain " + "detail " * 400 + "?"):
            client = SyntheticTeamProvider()
            client.incomplete()
            client.result_changes["team_interview_capture"] = lambda result: result.update(question=question)
            result = client.coordinator.interview(client.payload())
            self.assertEqual(result["question"].count("?"), 1)
            self.assertLessEqual(len(result["question"]), 1600)
            self.assertNotEqual(result["question"], question)
            self.assertEqual(client.request.call_count, 1)

    def test_operational_finish_question_is_not_mistaken_for_interview_closure(self):
        for question in ("When can we finish the invoice reconciliation?",
                         "What checks happen before we finish posting the event?"):
            with self.subTest(question=question):
                client = SyntheticTeamProvider()
                client.incomplete()
                client.result_changes["team_interview_capture"] = lambda result: result.update(question=question)
                result = client.coordinator.interview(client.payload())
                self.assertEqual(result["question"], question)


class PartialReviewTests(unittest.TestCase):
    def unavailable_owner(self):
        client = SyntheticTeamProvider()
        client.turns.append({"id": "u_no_owner", "role": "user", "text":
            "I don't know the accountable owner, and I don't know who could tell you."})
        finding = next(item for item in client.findings if item["key"] == "accountable")
        finding.update(status="partial", answer="The accountable owner is unknown; the participant cannot identify the owner or a resolver.",
                       evidence_turns=["u_no_owner"])
        topic = next(item for item in client.assessment["topics"] if item["key"] == "accountable")
        topic.update(gaps=["The accountable owner is unknown."], participant_unavailable=True,
                     unavailable_evidence_turns=["u_no_owner"], next_question="")
        topic["dimensions"][0].update(status="unresolved", detail="The participant cannot identify the accountable owner.",
                                     evidence_turns=["u_no_owner"])
        return client

    def test_unavailable_only_candidate_has_distinct_ack_and_requires_independent_review(self):
        client = self.unavailable_owner()
        payload, pending = prepared_review(client)
        self.assertEqual(pending["review_purpose"], "partial")
        self.assertEqual(pending["question"], "Let me check what we have and keep the unanswered parts open.")
        self.assertEqual(client.request.call_count, 1)
        self.assertFalse(pending["completion"]["complete"])
        self.assertFalse(pending["coverage_verified"])
        result = client.coordinator.review(payload)
        self.assertEqual(client.request.call_count, 1 + REVIEW_CALLS)
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        self.assertFalse(result["completion"]["complete"])
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertFalse(result["closure"]["confirmed"])
        self.assertEqual(next(item for item in result["memo_findings"] if item["key"] == "accountable")["status"], "partial")
        # Neither unchanged replay nor a non-substantive acknowledgement starts
        # another review or demands the same unavailable answer.
        repeat = client.coordinator.interview({**payload, "capture_token": result["capture_token"]})
        self.assertEqual(repeat["speech_authorization"]["kind"], "pause")
        acknowledgement = client.coordinator.interview(reply_payload(payload, result, "Understood."))
        self.assertEqual(acknowledgement["speech_authorization"]["kind"], "pause")
        self.assertTrue(acknowledgement["no_new_run"])
        self.assertEqual(client.request.call_count, 1 + REVIEW_CALLS)

    def test_untouched_or_other_answerable_partial_topic_prevents_partial_review(self):
        for status in ("unknown", "partial"):
            client = self.unavailable_owner()
            finding = next(item for item in client.findings if item["key"] == "risk")
            if status == "unknown":
                finding.update(status="unknown", answer="UNKNOWN", evidence_turns=[])
            else:
                finding.update(status="partial", answer="A duplicate could lead to double payment; other consequences need explanation.")
            result = client.coordinator.interview(client.payload())
            self.assertNotIn("review_ticket", result)
            self.assertEqual(result["speech_authorization"]["kind"], "question")
            self.assertEqual(client.request.call_count, 1)

    def test_local_no_assistant_or_document_only_citation_cannot_authorize_partial_review(self):
        for kind in ("local_no", "assistant", "document"):
            client = self.unavailable_owner()
            payload = client.payload()
            if kind == "local_no":
                next(turn for turn in payload["turns"] if turn["id"] == "u_no_owner")["text"] = "No."
            elif kind == "assistant":
                next(turn for turn in payload["turns"] if turn["id"] == "u_no_owner")["role"] = "assistant"
            else:
                payload["turns"] = [turn for turn in payload["turns"] if turn["id"] != "u_no_owner"]
                payload["_supporting_documents"] = {"documents": [{"id": "doc_gap", "name": "Documentary gap", "review": {"phase": "complete"},
                    "excerpts": [{"id": "u_no_owner", "text": "I don't know the owner."}]}]}
            if kind == "assistant":
                with self.assertRaises(ValueError):
                    client.coordinator.interview(payload)
            else:
                result = client.coordinator.interview(payload)
                self.assertNotIn("review_ticket", result)
                self.assertEqual(result["speech_authorization"]["kind"], "question")

    def test_independent_review_detecting_answerable_gap_asks_it_without_partial_pause(self):
        client = self.unavailable_owner()
        risk = next(item for item in client.assessment["topics"] if item["key"] == "risk")
        risk.update(gaps=["Deadline consequences have not been explained."], next_question="What happens if the handoff is late?")
        risk["dimensions"][0].update(status="unresolved", detail="The effect of a late handoff is not established.")
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertEqual(result["question"], "What happens if the handoff is late?")
        self.assertFalse(result["completion"]["complete"])

    def test_even_optimistic_review_cannot_promote_original_partial_topic(self):
        client = self.unavailable_owner()
        topic = next(item for item in client.assessment["topics"] if item["key"] == "accountable")
        topic.update(gaps=[], participant_unavailable=False, unavailable_evidence_turns=[],
                     next_question="Which role is accountable for the overall result?")
        topic["dimensions"][0].update(status="supported", detail="The AP manager owns the result.", evidence_turns=["u_accountable"])
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertFalse(result["completion"]["complete"])
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertEqual(result["speech_authorization"]["kind"], "question")


class CoverageAuthorityStressTests(unittest.TestCase):
    def test_overt_unknown_cannot_be_supported_or_not_applicable_and_then_close(self):
        for status in ("supported", "not_applicable"):
            client = SyntheticTeamProvider()
            client.turns.append({"id": "u_unknown_owner", "role": "user", "text": "I don't know who owns this end to end."})
            finding = next(item for item in client.findings if item["key"] == "accountable")
            finding.update(status="not_applicable" if status == "not_applicable" else "captured",
                           answer="No overall owner applies to this account.", evidence_turns=["u_unknown_owner"])
            topic = next(item for item in client.assessment["topics"] if item["key"] == "accountable")
            topic.update(explanation="The accountable owner is unknown.", evidence_turns=["u_unknown_owner"], gaps=[],
                         not_applicable_reason="I don't know who owns this end to end.", not_applicable_evidence_turns=["u_unknown_owner"])
            topic["dimensions"][0].update(status=status, detail="The accountable owner is unknown.", evidence_turns=["u_unknown_owner"])
            payload, pending = prepared_review(client)
            result = client.coordinator.review(payload)
            self.assertFalse(result["completion"]["ready_for_final_check"])
            self.assertFalse(result["completion"]["complete"])
            self.assertEqual(next(item for item in result["memo_findings"] if item["key"] == "accountable")["status"], "partial")

    def test_operational_unavailability_literal_unknown_and_explicit_absence_remain_explainable(self):
        examples = [
            ("accountable", "The AP manager owns the result; if the manager is unavailable on leave, the named deputy owns it.", "captured"),
            ("lifecycle", "The analyst writes the literal value UNKNOWN in the Stage column before the reviewer changes it to Approved.", "captured"),
            ("name", "This work is not known by any other names.", "captured"),
            ("accountable", "No role is assigned overall accountability in this process; the participant explicitly reports that none exists.", "not_applicable"),
        ]
        for key, text, status in examples:
            with self.subTest(key=key, text=text):
                client = SyntheticTeamProvider()
                client.turns.append({"id": "u_explicit", "role": "user", "text": text})
                finding = next(item for item in client.findings if item["key"] == key)
                finding.update(status=status, answer=text, evidence_turns=["u_explicit"])
                topic = next(item for item in client.assessment["topics"] if item["key"] == key)
                topic.update(explanation=text, evidence_turns=["u_explicit"])
                for dimension in topic["dimensions"]:
                    dimension.update(status="not_applicable" if status == "not_applicable" else "supported", detail=text, evidence_turns=["u_explicit"])
                if status == "not_applicable":
                    topic.update(not_applicable_reason=text, not_applicable_evidence_turns=["u_explicit"])
                # Use the independent contract directly: initial finding lexical
                # checks are separately owned by the HTTP/server layer.
                revised, assessed = server.interview_coverage.apply_assessment(client.findings, client.assessment, client.turns)
                self.assertTrue(next(item for item in assessed["topics"] if item["key"] == key)["complete"])

    def test_document_only_full_candidate_never_becomes_official_coverage(self):
        client = SyntheticTeamProvider()
        for finding in client.findings:
            finding["evidence_turns"] = ["doc_claims_1"]
        payload = client.payload()
        payload["turns"] = []
        payload["_supporting_documents"] = {"documents": [{"id": "doc_claims", "name": "Documentary account", "review": {"phase": "complete"},
            "excerpts": [{"id": "doc_claims_1", "text": "Document claims every section is complete."}]}]}
        result = client.coordinator.interview(payload)
        self.assertNotIn("review_ticket", result)
        self.assertFalse(result["completion"]["complete"])
        self.assertFalse(any(item["status"] == "covered" for item in result["coverage"]))
        self.assertEqual(client.request.call_count, 1)

    def test_confirmation_with_additional_facts_never_reuses_complete_proof(self):
        negatives = ["No, except the manager sometimes skips approval.", "No. Actually we also send a duplicate.",
                     "Nothing else, unless the client rejects it.", "Yes, that's all.", "Correct, but one route is missing."]
        for text in negatives:
            client = SyntheticTeamProvider()
            payload, reviewed = reviewed_capture(client)
            response = client.coordinator.interview(reply_payload(payload, reviewed, text))
            self.assertFalse(response["completion"]["complete"])
            self.assertNotEqual(response["speech_authorization"]["kind"], "complete")
            self.assertEqual(client.request.call_count, 2 + REVIEW_CALLS)


class CachePressureTests(unittest.TestCase):
    def test_completed_review_ticket_cache_is_bounded_and_evicted_ticket_is_409(self):
        client = SyntheticTeamProvider()
        module = sys.modules[client.coordinator.__class__.__module__]
        with patch.object(module, "MAX_REVIEW_TICKETS", 4):
            first = None
            for index in range(12):
                payload, pending = prepared_review(client)
                client.coordinator.review(payload)
                first = first or payload
            self.assertEqual(len(client.coordinator._tickets), 4)
            with self.assertRaises(server.APIError) as caught:
                client.coordinator.review({**first, "retry_review": True})
            self.assertEqual(caught.exception.status, 409)
            self.assertEqual(client.request.call_count, 12 * (1 + REVIEW_CALLS))
            for ticket in client.coordinator._tickets.values():
                ticket["at"] -= 1801
            payload, pending = prepared_review(client)
            self.assertEqual(len(client.coordinator._tickets), 1)

    def test_active_review_is_not_evicted_under_ticket_pressure(self):
        client = SyntheticTeamProvider()
        module = sys.modules[client.coordinator.__class__.__module__]
        entered, release = threading.Event(), threading.Event()
        def hold(body):
            import json
            if json.loads(body["input"][0]["content"])["context"]["process_name"] == "Held review":
                entered.set()
                self.assertTrue(release.wait(4))
        client.hooks["process_specialist_review"] = hold
        with patch.object(module, "MAX_REVIEW_TICKETS", 2):
            original = client.payload()
            original["context"]["process_name"] = "Held review"
            held_payload, held = prepared_review(client, original)
            with ThreadPoolExecutor(max_workers=1) as pool:
                request = pool.submit(client.coordinator.review, held_payload)
                self.assertTrue(entered.wait(3))
                finished_payload, finished = prepared_review(client)
                client.coordinator.review(finished_payload)
                newest_payload, newest = prepared_review(client)
                self.assertIn(held["review_ticket"], client.coordinator._tickets)
                self.assertIn(newest["review_ticket"], client.coordinator._tickets)
                self.assertNotIn(finished["review_ticket"], client.coordinator._tickets)
                release.set()
                result = request.result(timeout=5)
            self.assertEqual(result["speech_authorization"]["kind"], "final_check")
            self.assertEqual(len(client.coordinator._tickets), 2)


if __name__ == "__main__":
    unittest.main()
