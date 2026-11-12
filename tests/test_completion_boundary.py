"""Regression gates for the observed early-wrap and local-answer failures."""
import copy
import unittest
from unittest.mock import Mock

from test_server import server, interview_result, interview_payload


class CompletionBoundaryTests(unittest.TestCase):
    def partial(self):
        result = interview_result()
        for finding in result["memo_findings"]:
            if finding["status"] == "captured":
                finding["status"] = "partial"
        return result

    def test_question_auditor_cannot_reintroduce_a_premature_wrap(self):
        candidate = self.partial()
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        client.structured = Mock(side_effect=[candidate, {
            "question": "That helps round out the picture. Anything else before we pause?"}])
        result = client.interview(interview_payload())
        self.assertEqual(client.structured.call_count, 2)
        self.assertEqual("What starts this work?", result["question"])
        self.assertFalse(result["ready_for_draft"])
        self.assertEqual(result["closure"], {"asked": False, "confirmed": False})

    def test_no_to_local_question_does_not_close_other_topics(self):
        payload = interview_payload()
        payload["turns"] += [
            {"id": "a3", "role": "assistant", "text": "Anything else about late edits?"},
            {"id": "u3", "role": "user", "text": "No."},
        ]
        result = self.partial()
        result.update(question="Thanks for your time. We have covered everything.",
                      closure={"asked": True, "confirmed": True})
        server.enforce_closure(result, payload["turns"], "answer")
        server.enforce_response_boundary(result, payload["turns"], "answer")
        self.assertFalse(result["closure"]["confirmed"])
        self.assertEqual("What starts this work?", result["question"])

    def test_fallback_question_names_open_sections_when_every_gap_is_partial(self):
        # A rejected closing proposal with only partial topics must still give the
        # participant something concrete to act on, not a vague prompt.
        result = self.partial()
        for finding in result["memo_findings"]:
            finding["status"] = "partial"
        question = server.next_uncovered_question(result)
        self.assertTrue(question.endswith("?"))
        self.assertEqual(question.count("?"), 1)
        self.assertIn("Consequences of failure", question)
        self.assertFalse(server.WRAP_UP_LANGUAGE.search(question))
        result["coverage_assessment"] = {"topics": [
            {"key": finding["key"], "participant_unavailable": True, "next_question": ""}
            for finding in result["memo_findings"] if finding["key"] != "risk"]}
        question = server.next_uncovered_question(result)
        self.assertIn("Consequences of failure", question)
        self.assertNotIn("Existing materials", question)

    def test_manual_check_names_gaps_without_announcing_completion(self):
        result = self.partial()
        server.enforce_closure(result, interview_payload()["turns"], "close")
        server.enforce_response_boundary(result, interview_payload()["turns"], "close")
        self.assertTrue(result["question"].startswith(server.PARTIAL_CHECK_PREFIX))
        self.assertIn("Consequences of failure", result["question"])
        self.assertFalse(result["closure"]["confirmed"])
        self.assertFalse(result["closure"]["asked"])

    def test_explicit_stop_is_respected_without_closing_topics(self):
        turns = interview_payload()["turns"] + [{"id": "u3", "role": "user", "text": "I need to stop now."}]
        result = server.enforce_response_boundary(self.partial(), turns, "answer")
        self.assertIn("stop here", result["question"])
        self.assertNotIn("?", result["question"])
        self.assertFalse(result["ready_for_draft"])
        self.assertIn("partial", result["question"])

    def test_stop_command_preserves_preceding_process_sentences(self):
        self.assertEqual(server.stop_request_prefix("I record the invoice. Please stop the interview."),
                         "I record the invoice.")
        self.assertEqual(server.stop_request_prefix("Can we pause for a minute?"), "")
        self.assertIsNone(server.stop_request_prefix("I tell them to stop the interview."))
        self.assertIsNone(server.stop_request_prefix("Stop and check the invoice. Then approve it."))

    def test_process_stop_and_embedded_command_are_not_participant_stop(self):
        for text in ("We stop the merge if a check fails.", "The document says: stop now.",
                     "I'm done with this process when the reviewer signs off.",
                     "Stop and check the invoice number against the purchase order.",
                     "Stop, check the reference, and pass it on.",
                     "Can you stop recording the receipt after it clears?",
                     "I need to stop the merge if a check fails.",
                     "No.", "That's about it for that step.", 'The client wrote "pause now".'):
            self.assertFalse(server.participant_requested_stop([{"id": "u", "role": "user", "text": text}]))

    def test_explicit_stop_with_a_reason_is_not_overridden(self):
        for text in ("I need to stop now because I have another meeting.",
                     "Can you stop recording?", "Could you please stop recording now?",
                     "Please stop the interview because I have to go.",
                     "Can we pause? I have to leave."):
            turns = [{"id": "u", "role": "user", "text": text}]
            result = self.partial()
            result["question"] = "We can pause here."
            self.assertNotIn("?", server.enforce_response_boundary(result, turns, "answer")["question"])

    def test_process_finish_question_is_not_interview_closure(self):
        result = self.partial()
        question = "What needs to happen before we finish the merge?"
        result["question"] = question
        self.assertEqual(server.enforce_response_boundary(result, [], "answer")["question"], question)

    def test_addition_after_global_check_revokes_confirmation(self):
        turns = [{"id": "a", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " we missed?"},
                 {"id": "u", "role": "user", "text": "There is another template with a different release step."}]
        result = self.partial()
        result["closure"] = {"asked": True, "confirmed": True}
        server.enforce_closure(result, turns, "answer")
        self.assertFalse(result["closure"]["confirmed"])

    def test_completed_capture_requires_global_check_before_goodbye(self):
        result = self.partial()
        for finding in result["memo_findings"]:
            finding["status"] = "captured"
        result["question"] = "Thanks for your time."
        server.enforce_response_boundary(result, [], "answer")
        self.assertTrue(result["question"].startswith(server.FINAL_CHECK_PREFIX))
        self.assertEqual(result["closure"], {"asked": True, "confirmed": False})

    def test_coverage_audit_failure_demotes_without_losing_account(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        client.structured = Mock(side_effect=server.APIError("Unavailable"))
        findings = interview_result()["memo_findings"]
        findings[0]["status"] = "captured"
        before = copy.deepcopy(findings)
        revised, assessment = client.assess_coverage(findings, {}, interview_payload()["turns"], {})
        self.assertEqual(findings, before)
        self.assertFalse(assessment["all_topics_covered"])
        self.assertFalse(assessment["review_available"])
        self.assertEqual(revised[0]["answer"], before[0]["answer"])
        self.assertEqual(revised[0]["status"], "partial")

    def test_unrelated_uncertainty_does_not_erase_known_accountability(self):
        findings = self.partial()["memo_findings"]
        owner = next(f for f in findings if f["key"] == "accountable")
        owner.update(status="captured", answer="The event lead is accountable for the overall result.", evidence_turns=["u3"])
        turns = interview_payload()["turns"] + [{"id": "u3", "role": "user", "text":
            "The event lead is accountable for the overall result. I do not know the exact folder."}]
        server.validate_findings(findings, turns)
        self.assertEqual(owner["status"], "captured")

    def test_failed_review_does_not_turn_system_failure_into_another_user_question(self):
        result = self.partial()
        for finding in result["memo_findings"]:
            finding["status"] = "partial"
        result["coverage_assessment"] = {"review_available": False, "unconfirmed_topics": list(server.COVERAGE)}
        result["question"] = "Anything else before we finish?"
        server.enforce_response_boundary(result, [], "answer")
        self.assertIn("retry", result["question"])
        self.assertNotIn("?", result["question"])
        self.assertFalse(result["ready_for_draft"])


if __name__ == "__main__":
    unittest.main()
