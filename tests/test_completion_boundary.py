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
        # A few open sections are named.
        result = interview_result()
        for finding in result["memo_findings"]:
            finding["status"] = "partial" if finding["key"] in ("risk", "volume") else "captured"
        server.enforce_closure(result, interview_payload()["turns"], "close")
        server.enforce_response_boundary(result, interview_payload()["turns"], "close")
        self.assertTrue(result["question"].startswith(server.PARTIAL_CHECK_PREFIX))
        self.assertIn("Consequences of failure", result["question"])
        self.assertFalse(result["closure"]["confirmed"])
        self.assertFalse(result["closure"]["asked"])
        # Many open sections are counted; the Notes list beside the conversation shows which.
        result = self.partial()
        server.enforce_closure(result, interview_payload()["turns"], "close")
        server.enforce_response_boundary(result, interview_payload()["turns"], "close")
        self.assertTrue(result["question"].startswith(server.PARTIAL_CHECK_PREFIX))
        self.assertIn("the Notes list shows which", result["question"])
        self.assertNotIn("Consequences of failure", result["question"])
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

    @staticmethod
    def stop(text, *action):
        return server.participant_requested_stop([{"id": "u", "role": "user", "text": text}], *action)

    def test_process_answers_that_begin_like_a_stop_request_are_analysed(self):
        for text in (
                # Answers to the server's own 'How do you know this work is finished?'
                "I'm done with this when the bank confirms receipt of the wire.",
                "I am done with this once the manager signs off the notice.",
                "I'm done with this step when the reconciliation ties to zero, then I move to allocations.",
                "I'm done with that after the controller signs the break report.",
                "I'm done when the bank confirms receipt.",
                "I'm done. The manager takes over from there.",
                # Ambiguous without a qualifier ('the work ends there'): left to the interviewer.
                "I'm done.", "We are done.",
                # First-person process statements
                "I need to stop and check the source file before I release anything.",
                "I need to stop and check the bank portal before I release anything.",
                "I need to stop, fix the allocation and rerun the merge.",
                "I want to pause, because the controller has to approve before I go on.",
                "I want to pause because the controller has to approve before I go on.",
                "I need to finish, and then send the report to the manager.",
                "I want to finish, so I send the report first.",
                "I need to stop as soon as the totals differ.",
                "I have to stop the batch and tell the controller.",
                "We need to stop the run if a price is stale.",
                "I have to go to the vault and count the cash.",
                "We need to finish today.", "I have to finish.", "We have to finish today. The filing is due tomorrow.",
                "I need to stop now, then check the file.", "I need to stop here. The controller signs first.",
                # Imperatives that describe the work
                "Stop. Nothing is released until the controller signs the break report.",
                "Stop and escalate to the fund controller.",
                "Stop as soon as the totals differ.",
                "Stop, that's not right - the client approves first.",
                "Stop as in stop-loss? No, we don't use those.",
                "Stop the merge when the totals differ.",
                "Pause, I forgot to say the controller signs it first.",
                "Pause, then the controller signs off.",
                "Pause, then call the custodian and wait for their confirmation.",
                "Pause. Let me think about the order.",
                "Pause and resume are both buttons in the workflow tool.",
                # Navigation inside the interview, not ending it
                "Can we stop here and go back to the approval step? I missed something.",
                "I need to stop now and go to the vault to verify the amount.",
                "I need to stop now and attend a meeting with the reviewer before release.",
                "Let's pause and look at the exceptions instead.",
                "Let's stop, I got that wrong. The senior checks it first.",
                "Let's finish. The last step is filing.",
                "Stop. I have to go to the vault and count the cash before anything is released.",
                # 'The call', 'the meeting', 'the session' and 'there' can be things or points in the work.
                "Stop the call.", "Pause the call.", "We need to stop the meeting.", "I need to stop there.",
                "We have to pause there.", "Stop there.", "I need to end the call. Then I log the complaint in the CRM.",
                "We need to stop the session. Then the user logs back in.",
                "Let's end the session. The system then posts the batch.",
                "I have to pause the session now. Otherwise the batch posts twice.",
                "I want to end the session for today. Tomorrow the batch resumes.",
                # 'We' statements about the work, and the end of a step
                "We need to stop now. The custodian cut-off is 4 pm.",
                "We need to stop now. That's what the controller tells the desk when a price is stale.",
                "We're done with that.", "I'm done with that.", "We are done with this.",
                "I'm done for the day. The night team picks up the reconciliation from there.",
                "We're done for today. The night team takes over.",
                # A reason for leaving is a whole clause; a longer one is about the work.
                "Stop. I have a meeting with the controller before anything is released.",
                "Pause. My call with the custodian confirms the amount.",
                "Stop, I am late posting the journal entries.",
                "We have to stop. I have another meeting with the auditors at that point in the process.",
                "Pause. My manager is calling the custodian.", "Stop. I need a break report from the custodian.",
                # A firm request that carries on with the work
                "I need to stop now and check the file.", "I need to stop now, and check the file.",
                "I need to stop now. Then I check the file.", "I need to stop now, otherwise the batch posts twice.",
                "Stop now. Do not release the wire."):
            with self.subTest(text=text):
                self.assertFalse(self.stop(text))

    def test_ordinary_ways_of_asking_to_stop_are_recognised(self):
        for text in (
                "I need to stop now.", "Please stop.", "Can we pause?", "I'd like to stop here.", "I'd like to stop now.",
                "I have to stop now.", "I have to go, can we stop?", "Okay, let's stop here.", "Sorry, I need to stop now.",
                "Um, can we stop?", "Actually, can we pause?", "Well, I would like to stop.", "We need to stop.", "Can I stop?",
                "Stop please.", "Please can we stop?", "Could we please stop here?", "Let's stop for the day.",
                "Let's stop the interview here.", "I need to stop here for today.", "Please stop the interview now.",
                "Lets stop here.", "Let’s pause for now.", "I'm done for now.", "I'm done for the day.", "We're done for today.",
                "I am done with the interview.", "I'm done with this.", "That's all I have time for today.",
                "I need to end the call.", "I have to go now, thanks for your help.", "I need to stop now, thanks.",
                "I need to stop now.\nI have another meeting.", "Can we pause? I have to leave.",
                "I need to stop now, I have another meeting.", "I need to stop now because I have another meeting.",
                "Please stop the interview because I have to go.", "Let's stop here since I'm out of time.",
                "  STOP.  ",
                # A firm request about the interview itself stands whatever is added after it.
                "I need to stop now. Leave those gaps recorded; I do not want another question today.",
                "Please stop the interview now. I do not want more questions.",
                "Sorry. I'm done for today. We can pick up the exceptions next time.",
                # ... with any reason, after any punctuation: dictated text gets its
                # punctuation from the transcriber.
                "I need to stop now because I'm tired.", "I need to stop now because I am not feeling well.",
                "Please stop the interview because I am not feeling well.",
                "I need to stop for now because the fire alarm is going off.",
                "I'm done for today because I'm exhausted.", "I need to stop for today since my shift is over.",
                "I need to stop now as I have a meeting.", "I need to stop now so I can pick up my kids.",
                "I need to stop now, my manager is calling me.", "I need to stop now, I'm tired.",
                "I need to stop now. I'm tired.", "I need to stop now, my boss is calling.",
                "I need to stop now. My boss is calling.", "I need to stop now; my boss is calling.",
                "I need to stop now - my manager needs me.", "I need to stop now, something urgent came up.",
                "I need to stop now, I have a client call in five minutes.",
                "I need to stop now, I have to pick up my kids.", "Please stop the interview, I don't feel well.",
                "I need to stop now, I'm not feeling well.", "Can we stop now, I really need to get back to work.",
                "I want to stop the interview, this is taking too long.", "I need to stop now (meeting).",
                "Let's stop here for today, I have a hard stop at 3:30.",
                "That is all I have time for, we are done.",
                # ... or with a later time to resume
                "I need to stop now, we can continue tomorrow.", "I need to stop for now, can we continue tomorrow?",
                "I need to stop for now and continue tomorrow.", "I need to stop now and pick this up tomorrow.",
                "I'd like to pause the interview and come back to it later.",
                # An ambiguous request with an everyday reason or a later time to resume
                "I need to stop because I am tired.", "Can we pause because I need a break?", "Can we stop? I'm tired.",
                "Let's stop. I am tired.", "Let's stop, I'm tired.", "Please stop, I need a break.",
                "Stop, please, I'm exhausted.", "Pause please, I need five minutes.", "Stop. Save what we have.",
                "I need to stop because my manager is calling me.", "I need to stop as I have a meeting.",
                "I need to stop so I can get to a meeting.", "Stop, I have a call in five minutes.",
                "Can we stop here and continue tomorrow?", "Let's stop here and pick this up next week.",
                "Let's stop and continue tomorrow.", "Can we stop and pick this up tomorrow?",
                "I need to stop now and go to a meeting.", "I need to stop now and I have another call.",
                "Can we pause the interview and get back to work?", "I need to stop now and pick up my kids.",
                "I must go now.", "Let's pause the interview and my manager is calling.",
                "We need to stop now, thanks.", "I need to stop here. Thanks, bye.", "I need to end the call."):
            with self.subTest(text=text):
                self.assertTrue(self.stop(text))

    def test_stop_request_is_consumed_by_an_explicit_action(self):
        for action in ("close", "skip", "document_followup"):
            self.assertFalse(self.stop("I need to stop now.", action))
        self.assertTrue(self.stop("I need to stop now.", "answer"))
        self.assertTrue(self.stop("I need to stop now.", "start"))

    def test_stop_request_is_consumed_by_the_servers_own_acknowledgement(self):
        asked = [{"id": "a_q", "role": "assistant", "text": "What happens after the manager approves?"},
                 {"id": "u_stop", "role": "user", "text": "Can we pause? I have to leave."}]
        self.assertTrue(server.participant_requested_stop(asked))
        for line in server.STOP_ACKNOWLEDGEMENTS:
            with self.subTest(line=line):
                self.assertFalse(server.participant_requested_stop(
                    asked + [{"id": "a_stop", "role": "assistant", "text": line}]))
        # In live voice the model's own spoken caption can already follow the
        # request when the capture is posted: that alone must not lose the stop.
        caption = asked + [{"id": "a_live", "role": "assistant", "text": "Sure, no problem at all."}]
        self.assertTrue(server.participant_requested_stop(caption))
        self.assertFalse(server.participant_requested_stop(
            caption + [{"id": "a_stop", "role": "assistant", "text": server.STOP_ACKNOWLEDGEMENTS[1]}]))
        # A file notification between the request and the reply changes nothing.
        notice = {"id": "file", "role": "assistant", "text": "File received.", "document_event": True}
        self.assertTrue(server.participant_requested_stop(asked + [notice]))
        # A new request after an acknowledged one is a new request.
        again = asked + [{"id": "a_stop", "role": "assistant", "text": server.STOP_ACKNOWLEDGEMENTS[0]},
                         {"id": "u_again", "role": "user", "text": "Please stop."}]
        self.assertTrue(server.participant_requested_stop(again))

    def test_every_stop_reply_the_server_issues_is_a_known_acknowledgement(self):
        turns = interview_payload()["turns"] + [{"id": "u3", "role": "user", "text": "I need to stop now."}]
        partial = server.enforce_response_boundary(self.partial(), turns, "answer")["question"]
        complete = self.partial()
        for finding in complete["memo_findings"]:
            finding.update(status="captured", answer="The AP clerk logs each invoice in the register.", evidence_turns=["u1"])
        captured = server.enforce_response_boundary(complete, turns, "answer")["question"]
        self.assertNotEqual(partial, captured)
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        client.request = Mock(side_effect=AssertionError("A stop needs no provider call"))
        coordinator = client.coordinator.interview({**interview_payload(), "turns": turns})["question"]
        for line in (partial, captured, coordinator):
            self.assertIn(line, server.STOP_ACKNOWLEDGEMENTS)

    def test_wrap_up_after_an_explicit_stop_is_not_answered_with_the_stop_line(self):
        turns = interview_payload()["turns"] + [{"id": "u3", "role": "user", "text": "I need to stop now."}]
        result = server.enforce_response_boundary(self.partial(), turns, "close")
        self.assertNotIn("stop here", result["question"])
        self.assertTrue(result["question"].startswith(server.PARTIAL_CHECK_PREFIX))
        acknowledged = turns + [{"id": "a3", "role": "assistant", "text": server.STOP_ACKNOWLEDGEMENTS[3]}]
        result = self.partial()
        result["question"] = "Who releases payment after the manager approves?"
        self.assertEqual(server.enforce_response_boundary(result, acknowledged, "answer")["question"],
                         "Who releases payment after the manager approves?")

    def test_stop_detector_stays_fast_on_long_input(self):
        import time
        started = time.perf_counter()
        for text in ("um " * 1900 + "stop", "I have another meeting " + "x " * 2900, "stop " + "please " * 800,
                     "Okay, " * 900 + "I need to stop now", "I need to stop now" + ", thanks" * 600,
                     "I have to go, " * 400, "I'm done " + "for now " * 700, "so " * 1990 + "x",
                     # Repeated request-and-reason fragments: a single backtracking pattern takes minutes here.
                     "my next meeting " + "stop i have another meeting " * 210 + ". x",
                     "my next meeting " + "stop thanks i have another meeting " * 170 + ". x",
                     "stop because " + "i have another meeting because " * 190 + "x",
                     "stop, " * 1000, "stop. " * 1000, "a, " * 2000, "i need to stop now " * 300,
                     "i need to stop now because " + "so " * 1900, "stop and " + "continue " * 600 + "tomorrow",
                     "i'm " + "really very so " * 400 + "tired", "i have a " + "meeting in " * 500 + "minutes",
                     "i need to stop now, " + "thanks, " * 700 + "then x", "stop (" * 900, "my manager is " * 450):
            self.stop(text[:6000])
        self.assertLess(time.perf_counter() - started, 2)

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
