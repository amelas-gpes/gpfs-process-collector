"""Replies that add nothing to the account never cost a review or a completion.

After the final omissions check: a hedged or courteous "no" completes the account, and
a reply without content has the check asked again; neither starts a review. After the
completion line: a thank-you, a goodbye or a request to stop leaves the completed
account as it is. A request to stop in reply to the final check pauses and keeps the
review. Only a reply with content is analysed again.

Real Coordinator, real stop detector and real ConcurrentInterview against
schema-routed offline models: no provider access.
"""
import copy
import unittest

from test_concurrent_http import ConversationProvider
from test_interview_orchestrator import (REVIEW_CALLS, SyntheticTeamProvider, prepared_review, reply_payload,
                                         reviewed_capture)
from test_server import server

concurrent = server.local_module("concurrent_interview", "concurrent_interview.py")
# What is added to the final check when it has to be asked again (agent_team.FINAL_CHECK_HINT).
HINT = "Say “no” if nothing is missing, or tell me what to add."
REVIEWED = 1 + REVIEW_CALLS  # one lead capture and one completion review
STOP = "I need to stop now."


def stop_requests(*candidates):
    """Those sentences that the stop detector takes as a request to stop.

    Which wording counts is the detector's rule (server.participant_requested_stop),
    tested with it. These tests are about what follows once it has said so.
    """
    found = [text for text in (STOP, *candidates)
             if server.participant_requested_stop([{"id": "u_stop", "role": "user", "text": text}])]
    assert STOP in found
    return found


def then(payload, result, *turns, token=True):
    """The transcript after `result`: its line as the interviewer's turn, then `turns`."""
    value = copy.deepcopy(payload)
    value.pop("agent_run_id", None)
    value.pop("review_ticket", None)
    if token and result.get("capture_token"):
        value["capture_token"] = result["capture_token"]
    number = len(value["turns"])
    value["turns"].append({"id": f"a_line_{number}", "role": "assistant", "text": result["question"]})
    for index, turn in enumerate(turns):
        role, text = turn if isinstance(turn, tuple) else ("user", turn)
        value["turns"].append({"id": f"{role[0]}_more_{number}_{index}", "role": role, "text": text})
    return value


def completed(client):
    """A reviewed account whose final check the participant has confirmed."""
    payload, reviewed = reviewed_capture(client)
    confirming = reply_payload(payload, reviewed, "No, nothing else.")
    complete = client.coordinator.interview(confirming)
    assert complete["speech_authorization"]["kind"] == "complete" and complete["completion"]["complete"]
    client.completion_line = complete["question"]
    return confirming, complete


class RepliesToTheFinalCheck(unittest.TestCase):
    def test_hedged_and_courteous_negatives_complete_the_account_without_provider_calls(self):
        for text in ("No, I think that's everything.", "No, nothing.", "Not that I can think of.", "I don't think so.",
                     "No, thank you.", "Nope, we're good.", "Um, no, that's about it, thanks.", "No... nothing else."):
            with self.subTest(text=text):
                client = SyntheticTeamProvider()
                payload, reviewed = reviewed_capture(client)
                result = client.coordinator.interview(reply_payload(payload, reviewed, text))
                self.assertEqual(client.request.call_count, REVIEWED)
                self.assertEqual(result["speech_authorization"]["kind"], "complete")
                self.assertTrue(result["completion"]["complete"])
                self.assertTrue(result["completion"]["participant_confirmed"])
                self.assertTrue(result["closure"]["confirmed"])
                self.assertTrue(result["no_new_run"])

    def test_a_reply_that_adds_nothing_has_the_final_check_asked_again_without_a_review(self):
        for text in ("Okay.", "Sounds good.", "Thank you.", "Hmm, let me think.", "What do you mean?",
                     "I'm done.", "Maybe."):
            with self.subTest(text=text):
                client = SyntheticTeamProvider()
                payload, reviewed = reviewed_capture(client)
                follow = reply_payload(payload, reviewed, text)
                again = client.coordinator.interview(follow)
                self.assertEqual(client.request.call_count, REVIEWED, "No lead call and no review")
                self.assertEqual(again["speech_authorization"]["kind"], "final_check")
                self.assertTrue(again["no_new_run"])
                self.assertNotIn("review_ticket", again)
                self.assertTrue(again["coverage_verified"], "The review that passed is kept")
                self.assertEqual(again["question"], reviewed["question"] + " " + HINT)
                self.assertTrue(again["question"].startswith(server.FINAL_CHECK_PREFIX))
                self.assertEqual(again["speech_authorization"]["text"], again["question"])
                self.assertFalse(again["completion"]["complete"])
                self.assertFalse(again["completion"]["participant_confirmed"])
                self.assertTrue(again["completion"]["ready_for_final_check"])
                self.assertEqual(again["completion"]["blockers"], ["confirmation_pending"])
                self.assertEqual(again["closure"], {"asked": True, "confirmed": False})
                # A second reply of the kind does not grow the line ...
                second = then(follow, again, "Right.")
                once_more = client.coordinator.interview(second)
                self.assertEqual(once_more["question"], again["question"])
                self.assertEqual(once_more["question"].count(HINT), 1)
                # ... and the repeated check is the real one: a plain "no" completes the account.
                done = client.coordinator.interview(then(second, once_more, "No, I think that's everything."))
                self.assertEqual(done["speech_authorization"]["kind"], "complete")
                self.assertTrue(done["completion"]["complete"])
                self.assertEqual(client.request.call_count, REVIEWED)

    def test_a_yes_still_asks_what_to_add(self):
        client = SyntheticTeamProvider()
        payload, reviewed = reviewed_capture(client)
        answer = client.coordinator.interview(reply_payload(payload, reviewed, "Yes, there is something else."))
        self.assertEqual(answer["question"], "What should we add to the account?")
        self.assertEqual(answer["speech_authorization"]["kind"], "question")
        self.assertEqual(client.request.call_count, REVIEWED)

    def test_a_reply_with_content_is_analysed_and_reviewed_again(self):
        for text in ("Treasury signs too.", "No, but the controller also signs the batch.", "Okay, but refunds differ.",
                     "Not really, except at year end.", "Twice.", "She approves it."):
            with self.subTest(text=text):
                client = SyntheticTeamProvider()
                payload, reviewed = reviewed_capture(client)
                answer = client.coordinator.interview(reply_payload(payload, reviewed, text))
                self.assertEqual(client.request.call_count, REVIEWED + 1, "The lead reads the addition")
                self.assertNotIn("no_new_run", answer)
                self.assertFalse(answer["coverage_verified"])
                self.assertFalse(answer["completion"]["complete"])
                # The earlier review no longer stands for anything.
                stale = client.coordinator.interview(reply_payload(payload, reviewed, "No, nothing else."))
                self.assertFalse(stale["completion"]["complete"])

    def test_a_reply_that_adds_nothing_cannot_confirm_by_itself_or_skip_the_check(self):
        client = SyntheticTeamProvider()
        payload, reviewed = reviewed_capture(client)
        follow = reply_payload(payload, reviewed, "Okay, thanks.")
        again = client.coordinator.interview(follow)
        # "No" typed without the repeated check in front of it is not a reply to a check.
        skipped = copy.deepcopy(follow)
        skipped["capture_token"] = again["capture_token"]
        skipped["turns"].append({"id": "u_no", "role": "user", "text": "No."})
        result = client.coordinator.interview(skipped)
        self.assertFalse(result["completion"]["complete"])
        self.assertNotEqual(result["speech_authorization"]["kind"], "complete")

    def test_retrieval_selection_is_kept_for_every_reply_answered_without_a_review(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        payload["_supporting_documents"] = {"documents": [{"id": "doc_example", "name": "Procedure", "review": {"phase": "complete"},
            "excerpts": [{"id": "doc_example_1", "text": "The analyst registers the invoice."},
                         {"id": "doc_example_2", "text": "The coordinator sends the output."}]}]}
        review_payload, _ = prepared_review(client, payload)
        basis = client.coordinator.retrieval_basis(review_payload)
        reviewed = client.coordinator.review(review_payload)
        for text in ("No, I think that's everything.", "Sounds good.", "What do you mean?", "Yes.", STOP):
            with self.subTest(text=text):
                self.assertEqual(client.coordinator.retrieval_basis(reply_payload(review_payload, reviewed, text)), basis)
        for text in ("Treasury signs too.", "Okay, but refunds differ."):
            with self.subTest(text=text):
                self.assertIsNone(client.coordinator.retrieval_basis(reply_payload(review_payload, reviewed, text)))
        # With files attached the reply is still answered from the review that passed.
        done = client.coordinator.interview(reply_payload(review_payload, reviewed, "Not that I can think of."))
        self.assertEqual(done["speech_authorization"]["kind"], "complete")
        self.assertEqual(client.request.call_count, REVIEWED)


class AStopRequestAfterTheFinalCheck(unittest.TestCase):
    """It pauses and confirms nothing, as any request to stop does, and the review stays."""

    def stopped(self, text=STOP):
        client = SyntheticTeamProvider()
        payload, reviewed = reviewed_capture(client)
        stop = reply_payload(payload, reviewed, text)
        paused = client.coordinator.interview(stop)
        return client, payload, reviewed, stop, paused

    def test_it_pauses_without_a_completion_claim_or_a_provider_call(self):
        for text in stop_requests("Let's finish.", "I'm done for now.", "Please stop the interview now.", "Sorry, I have to go."):
            with self.subTest(text=text):
                client, _, _, _, paused = self.stopped(text)
                self.assertEqual(client.request.call_count, REVIEWED)
                self.assertEqual(paused["speech_authorization"]["kind"], "pause")
                self.assertIn(paused["question"], server.STOP_ACKNOWLEDGEMENTS)
                self.assertTrue(paused["preserve_capture"])
                self.assertFalse(paused["completion"]["complete"])
                self.assertFalse(paused["closure"]["confirmed"])
                self.assertEqual(paused["completion"]["blockers"], ["participant_stopped"])
                self.assertNotIn("capture_token", paused)

    def test_wrap_up_after_the_pause_asks_the_same_check_again_without_a_review(self):
        client, _, reviewed, stop, paused = self.stopped()
        wrap = then(stop, paused, token=False)
        wrap["action"] = "close"
        again = client.coordinator.interview(wrap)
        self.assertEqual(client.request.call_count, REVIEWED, "The review that passed was kept")
        self.assertEqual(again["speech_authorization"]["kind"], "final_check")
        self.assertEqual(again["question"], reviewed["question"] + " " + HINT)
        self.assertTrue(again["coverage_verified"])
        self.assertFalse(again["completion"]["complete"])
        done = client.coordinator.interview(then(wrap, again, "No, nothing else."))
        self.assertEqual(done["speech_authorization"]["kind"], "complete")
        self.assertTrue(done["completion"]["participant_confirmed"])
        self.assertEqual(client.request.call_count, REVIEWED)

    def test_a_no_after_the_pause_is_not_a_reply_to_the_check_and_has_it_asked_again(self):
        client, _, reviewed, stop, paused = self.stopped()
        later = then(stop, paused, "No, nothing else.", token=False)
        again = client.coordinator.interview(later)
        self.assertEqual(client.request.call_count, REVIEWED)
        self.assertEqual(again["speech_authorization"]["kind"], "final_check")
        self.assertFalse(again["completion"]["complete"])
        self.assertFalse(again["completion"]["participant_confirmed"])
        done = client.coordinator.interview(then(later, again, "No."))
        self.assertTrue(done["completion"]["complete"])
        self.assertEqual(client.request.call_count, REVIEWED)

    def test_a_goodbye_after_the_pause_has_the_check_asked_again_whatever_the_interviewer_said(self):
        # Live voice goes on after the pause line: the spoken interviewer may answer in
        # its own words before the participant says goodbye.
        client, _, reviewed, stop, paused = self.stopped()
        later = then(stop, paused, ("assistant", "Of course, goodbye."), "Thanks, bye.", token=False)
        again = client.coordinator.interview(later)
        self.assertEqual(client.request.call_count, REVIEWED)
        self.assertEqual(again["speech_authorization"]["kind"], "final_check")
        self.assertEqual(again["question"], reviewed["question"] + " " + HINT)
        self.assertFalse(again["completion"]["complete"])
        # With an addition in the same place the account is analysed again.
        client, _, _, stop, paused = self.stopped()
        added = then(stop, paused, ("assistant", "Of course, goodbye."), "Wait, the bank confirms receipt too.", token=False)
        self.assertFalse(client.coordinator.interview(added)["completion"]["complete"])
        self.assertEqual(client.request.call_count, REVIEWED + 1)

    def test_a_second_request_to_stop_pauses_again_and_still_keeps_the_review(self):
        client, _, reviewed, stop, paused = self.stopped()
        second = then(stop, paused, STOP, token=False)
        again = client.coordinator.interview(second)
        self.assertEqual(again["speech_authorization"]["kind"], "pause")
        self.assertEqual(client.request.call_count, REVIEWED)
        # The first capture still answers a later Wrap up of the first pause.
        wrap = then(stop, paused, token=False)
        wrap["action"] = "close"
        self.assertEqual(client.coordinator.interview(wrap)["speech_authorization"]["kind"], "final_check")
        self.assertEqual(client.request.call_count, REVIEWED)

    def test_an_addition_after_the_pause_is_analysed(self):
        client, _, _, stop, paused = self.stopped()
        answer = client.coordinator.interview(then(stop, paused, "One thing: the bank also confirms receipt.", token=False))
        self.assertEqual(client.request.call_count, REVIEWED + 1)
        self.assertFalse(answer["completion"]["complete"])
        self.assertFalse(answer["coverage_verified"])

    def test_only_the_servers_own_acknowledgement_counts_as_the_answer_to_the_stop(self):
        client, _, _, stop, _ = self.stopped()
        forged = copy.deepcopy(stop)
        forged["turns"].append({"id": "a_other", "role": "assistant", "text": "Sure, no problem at all."})
        forged["action"] = "close"
        client.coordinator.interview(forged)
        self.assertEqual(client.request.call_count, REVIEWED + 1, "An unknown line after the stop is not replayed")

    def test_a_stop_before_the_review_has_passed_keeps_nothing_it_should_not(self):
        # The capture that only announced the review is not a passed final check.
        client = SyntheticTeamProvider()
        payload, pending = prepared_review(client)
        stop = copy.deepcopy(payload)
        stop.pop("review_ticket")
        stop["turns"].append({"id": "u_stop", "role": "user", "text": STOP})
        paused = client.coordinator.interview(stop)
        self.assertEqual(paused["speech_authorization"]["kind"], "pause")
        with self.assertRaises(server.APIError):
            client.coordinator.review(payload)


class AfterTheCompletionLine(unittest.TestCase):
    def assert_still_complete(self, client, result):
        self.assertEqual(client.request.call_count, REVIEWED, "No lead call and no review")
        self.assertEqual(result["speech_authorization"]["kind"], "complete")
        self.assertTrue(result["speech_authorization"]["completion_allowed"])
        self.assertTrue(result["completion"]["complete"])
        self.assertTrue(result["completion"]["participant_confirmed"])
        self.assertEqual(result["closure"], {"asked": True, "confirmed": True})
        self.assertTrue(result["coverage_verified"])
        self.assertTrue(result["no_new_run"])
        self.assertIs(result["completion_retained"], True)
        self.assertEqual(result["question"], client.completion_line, "The same line, not a new one")
        self.assertEqual(result["speech_authorization"]["text"], client.completion_line)
        self.assertEqual(len(result["memo_findings"]), len(server.COVERAGE))

    def test_a_courtesy_keeps_the_completion_without_provider_calls(self):
        for text in ("Thank you", "Okay.", "Thank you, bye.", "Bye", "Great, thanks", "Thanks so much, have a good day!",
                     "Perfect, thank you very much.", "Sounds good.", "No, nothing else.", "You're welcome."):
            with self.subTest(text=text):
                client = SyntheticTeamProvider()
                confirming, complete = completed(client)
                self.assertNotIn("completion_retained", complete, "The completion itself is a new line to say")
                self.assert_still_complete(client, client.coordinator.interview(then(confirming, complete, text)))

    def test_a_request_to_stop_is_a_goodbye_and_keeps_the_completion(self):
        for text in stop_requests("Okay, I have to go now, thanks for your help.", "Let's finish.",
                                  "I'm done for today, thank you."):
            with self.subTest(text=text):
                client = SyntheticTeamProvider()
                confirming, complete = completed(client)
                self.assertTrue(server.participant_requested_stop(then(confirming, complete, text)["turns"]))
                result = client.coordinator.interview(then(confirming, complete, text))
                self.assert_still_complete(client, result)
                self.assertNotIn("preserve_capture", result)

    def test_further_courtesies_and_interviewer_captions_change_nothing(self):
        client = SyntheticTeamProvider()
        confirming, complete = completed(client)
        first = then(confirming, complete, "Thank you.")
        kept = client.coordinator.interview(first)
        self.assert_still_complete(client, kept)
        # The line is not issued again, so the transcript simply goes on: the spoken
        # interviewer answers in its own words and the participant says goodbye.
        second = copy.deepcopy(first)
        second["capture_token"] = kept["capture_token"]
        second["turns"] += [{"id": "a_live", "role": "assistant", "text": "You're welcome. Goodbye!"},
                            {"id": "u_bye", "role": "user", "text": "Bye!"}]
        self.assert_still_complete(client, client.coordinator.interview(second))
        # The capture issued with the completion line answers the same transcript too.
        second["capture_token"] = complete["capture_token"]
        self.assert_still_complete(client, client.coordinator.interview(second))
        third = copy.deepcopy(second)
        third["turns"].append({"id": "u_stop", "role": "user", "text": STOP})
        self.assert_still_complete(client, client.coordinator.interview(third))

    def test_a_substantive_addition_reopens_the_review(self):
        for turns in (["There is another route."], ["Thank you.", "Actually the bank also confirms receipt."],
                      ["Okay, but refunds go to treasury."], ["One thing."] * 2 + ["Refunds."]):
            with self.subTest(turns=turns):
                client = SyntheticTeamProvider()
                confirming, complete = completed(client)
                result = client.coordinator.interview(then(confirming, complete, *turns))
                self.assertEqual(client.request.call_count, REVIEWED + 1, "The lead reads the addition")
                self.assertNotIn("completion_retained", result)
                self.assertFalse(result["completion"]["complete"])
                self.assertFalse(result["closure"]["confirmed"])
                self.assertFalse(result["coverage_verified"])
                # The completed capture no longer answers anything.
                after = client.coordinator.interview(then(confirming, complete, "Thank you."))
                self.assertFalse(after["completion"]["complete"])

    def test_an_addition_after_a_kept_completion_reopens_it_as_well(self):
        client = SyntheticTeamProvider()
        confirming, complete = completed(client)
        first = then(confirming, complete, "Thanks.")
        kept = client.coordinator.interview(first)
        later = copy.deepcopy(first)
        later["capture_token"] = kept["capture_token"]
        later["turns"].append({"id": "u_late", "role": "user", "text": "Oh, and the auditors see the register too."})
        result = client.coordinator.interview(later)
        self.assertEqual(client.request.call_count, REVIEWED + 1)
        self.assertFalse(result["completion"]["complete"])

    def test_retrieval_selection_is_kept_for_a_courtesy_after_completion(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        payload["_supporting_documents"] = {"documents": [{"id": "doc_example", "name": "Procedure", "review": {"phase": "complete"},
            "excerpts": [{"id": "doc_example_1", "text": "The analyst registers the invoice."}]}]}
        review_payload, _ = prepared_review(client, payload)
        basis = client.coordinator.retrieval_basis(review_payload)
        reviewed = client.coordinator.review(review_payload)
        confirming = reply_payload(review_payload, reviewed, "No, nothing else.")
        complete = client.coordinator.interview(confirming)
        client.completion_line = complete["question"]
        courtesy = then(confirming, complete, "Thank you, bye.")
        self.assertEqual(client.coordinator.retrieval_basis(courtesy), basis)
        self.assertIsNone(client.coordinator.retrieval_basis(then(confirming, complete, "There is another route.")))
        self.assert_still_complete(client, client.coordinator.interview(courtesy))


class AfterAPartialPause(unittest.TestCase):
    def paused(self):
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
        payload, result = reviewed_capture(client)
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        return client, payload, result

    def test_ordinary_acknowledgements_do_not_repeat_the_review(self):
        for text in ("Okay, thanks.", "Sounds good.", "Understood, thank you.", "Alright.", "Great, bye."):
            with self.subTest(text=text):
                client, payload, result = self.paused()
                kept = client.coordinator.interview(reply_payload(payload, result, text))
                self.assertEqual(client.request.call_count, REVIEWED)
                self.assertEqual(kept["speech_authorization"]["kind"], "pause")
                self.assertTrue(kept["no_new_run"])
                self.assertEqual(kept["question"], result["question"])
                self.assertFalse(kept["completion"]["complete"])
                self.assertIsNotNone(client.coordinator.retrieval_basis(reply_payload(payload, result, text)))

    def test_a_reply_with_content_is_analysed(self):
        client, payload, result = self.paused()
        client.coordinator.interview(reply_payload(payload, result, "Okay, the controller might know the owner."))
        self.assertEqual(client.request.call_count, REVIEWED + 1)

    def test_a_request_to_stop_still_gets_the_stop_reply(self):
        client, payload, result = self.paused()
        reply = client.coordinator.interview(reply_payload(payload, result, STOP))
        self.assertEqual(reply["speech_authorization"]["kind"], "pause")
        self.assertIn(reply["question"], server.STOP_ACKNOWLEDGEMENTS)
        self.assertNotEqual(reply["question"], result["question"])
        self.assertEqual(client.request.call_count, REVIEWED)


class TheTypedPath(unittest.TestCase):
    """The default configuration: /api/conversation/turn hands these replies to the Coordinator."""

    def setUp(self):
        self.client = ConversationProvider()
        self.service = concurrent.ConcurrentInterview(self.client, server)
        self.addCleanup(self.service.close)

    def names(self):
        return [call.args[1]["text"]["format"]["name"] for call in self.client.request.call_args_list
                if call.args[0] == "responses"]

    def say(self, snapshot, text):
        """One typed reply, as web/concurrent-interview.js sends it: turn, then sync when asked to."""
        reply = self.service.turn(copy.deepcopy(snapshot))
        if reply["sync_required"]:
            reply = self.service.sync(copy.deepcopy(snapshot))
        return reply

    def at_final_check(self):
        payload = self.client.payload()
        pending = self.service.sync({**copy.deepcopy(payload), "action": "close"})
        self.assertEqual(pending["speech_authorization"]["kind"], "review_pending")
        snapshot = {**payload, "conversation_token": pending["conversation_token"], "capture_token": pending["capture_token"]}
        snapshot["turns"] = payload["turns"] + [{"id": "a_ack", "role": "assistant", "text": pending["question"]}]
        reviewed = self.client.coordinator.review({**copy.deepcopy(snapshot), "review_ticket": pending["review_ticket"]})
        self.assertEqual(reviewed["speech_authorization"]["kind"], "final_check")
        return snapshot, reviewed

    def reply(self, snapshot, result, text):
        value = then(snapshot, result, text)
        value["action"] = "answer"
        return value

    def test_a_hedged_no_completes_and_a_thank_you_after_it_changes_nothing(self):
        snapshot, reviewed = self.at_final_check()
        before = self.names()
        confirming = self.reply(snapshot, reviewed, "No, I think that's everything.")
        complete = self.say(confirming, "No, I think that's everything.")
        self.assertEqual(complete["speech_authorization"]["kind"], "complete")
        self.assertTrue(complete["completion"]["complete"])
        thanks = self.reply(confirming, complete, "Thank you")
        kept = self.say(thanks, "Thank you")
        self.assertEqual(kept["speech_authorization"]["kind"], "complete")
        self.assertIs(kept["completion_retained"], True)
        self.assertTrue(kept["completion"]["complete"])
        self.assertTrue(kept["closure"]["confirmed"])
        self.assertFalse(kept["sync_required"])
        self.assertNotIn("workflow_capture", kept, "No map is rebuilt for a courtesy")
        # The line is not issued again: the next message follows the courtesy directly.
        bye = copy.deepcopy(thanks)
        bye["capture_token"] = kept["capture_token"]
        bye["turns"].append({"id": "u_bye", "role": "user", "text": stop_requests("Okay, I have to go now. Bye!")[-1]})
        self.assertTrue(server.participant_requested_stop(bye["turns"]))
        last = self.say(bye, "bye")
        self.assertEqual(last["speech_authorization"]["kind"], "complete", "A goodbye is not answered with the pause line")
        self.assertIs(last["completion_retained"], True)
        self.assertEqual(self.names(), before, "No provider call for any of the three replies")

    def test_a_reply_that_adds_nothing_has_the_check_asked_again_and_then_confirmed(self):
        snapshot, reviewed = self.at_final_check()
        before = self.names()
        okay = self.reply(snapshot, reviewed, "Sounds good.")
        again = self.say(okay, "Sounds good.")
        self.assertEqual(again["speech_authorization"]["kind"], "final_check")
        self.assertEqual(again["question"], reviewed["question"] + " " + HINT)
        done = self.say(self.reply(okay, again, "Not that I can think of."), "no")
        self.assertEqual(done["speech_authorization"]["kind"], "complete")
        self.assertEqual(self.names(), before)

    def test_a_stop_request_after_the_final_check_pauses_and_wrap_up_resumes_the_same_review(self):
        snapshot, reviewed = self.at_final_check()
        before = self.names()
        stop = self.reply(snapshot, reviewed, stop_requests("Let's finish.")[-1])
        paused = self.service.turn(copy.deepcopy(stop))
        self.assertEqual(paused["speech_authorization"]["kind"], "pause")
        self.assertFalse(paused["sync_required"])
        self.assertIn(paused["question"], server.STOP_ACKNOWLEDGEMENTS)
        wrap = then(stop, paused, token=False)
        wrap["action"] = "close"
        again = self.service.sync(copy.deepcopy(wrap))
        self.assertEqual(again["speech_authorization"]["kind"], "final_check")
        self.assertTrue(again["coverage_verified"])
        self.assertNotIn("workflow_capture", again)
        done = self.say(self.reply(wrap, again, "No, nothing else."), "no")
        self.assertEqual(done["speech_authorization"]["kind"], "complete")
        self.assertEqual(self.names(), before, "The pause, the Wrap up and the confirmation cost no provider call")

    def test_an_addition_after_completion_is_analysed(self):
        snapshot, reviewed = self.at_final_check()
        confirming = self.reply(snapshot, reviewed, "No, nothing else.")
        complete = self.say(confirming, "no")
        before = self.names().count("team_interview_capture")
        result = self.say(self.reply(confirming, complete, "Actually the bank also confirms receipt."), "more")
        self.assertFalse(result["completion"]["complete"])
        self.assertNotIn("completion_retained", result)
        self.assertEqual(self.names().count("team_interview_capture"), before + 1)


if __name__ == "__main__":
    unittest.main()
