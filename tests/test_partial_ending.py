"""A verified partial ("pause") ending is final until the participant adds something.

After the completion review has confirmed that the only open sections need information the
participant does not have, choosing Wrap up again adds no evidence. The Coordinator answers it
from the capture it kept: no provider call, no new run, the same line. Anything that is not that
exact situation (a new answer, a review that failed, an ordinary question) is still worked on.
The real Coordinator and concurrent service run with the schema-routed offline provider of
tests/test_interview_orchestrator.py; no network.
"""
import copy
import unittest

from test_server import server
from test_interview_orchestrator import SyntheticTeamProvider, reviewed_capture, prepared_review, REVIEW_CALLS


def unavailable_gap(client):
    """The participant cannot say who receives a corrected invoice, or who could (as in the
    existing pause test): the review confirms the gap as unavailable and pauses."""
    client.turns.append({"id": "u_unknown", "role": "user",
                         "text": "I don't know who receives the corrected invoice or who could tell us."})
    topic = next(item for item in client.assessment["topics"] if item["key"] == "lifecycle")
    topic.update(gaps=["The recipient of a corrected invoice remains unknown."], next_question="",
                 participant_unavailable=True, unavailable_evidence_turns=["u_unknown"])
    next(item for item in topic["dimensions"] if item["key"] == "handoffs").update(
        status="unresolved", detail="The participant does not know the corrected invoice recipient.",
        evidence_turns=["u_unknown"])
    client.blocker("")
    client.process["findings"][0]["evidence_turns"] = ["u_unknown"]


def after(payload, result, *more, action="close", line=True):
    """What the page sends next: the reviewed transcript, the line it was given, then `more`."""
    value = copy.deepcopy(payload)
    value.pop("agent_run_id", None)
    value.pop("review_ticket", None)
    value.update(capture_token=result["capture_token"], action=action)
    if line:
        value["turns"].append({"id": "a_issued", "role": "assistant", "text": result["question"]})
    value["turns"] += [dict(turn) for turn in more]
    return value


class RepeatedWrapUpAfterAVerifiedPartialEnding(unittest.TestCase):
    def paused(self):
        client = SyntheticTeamProvider()
        unavailable_gap(client)
        payload, result = reviewed_capture(client)
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        self.assertIs(result["coverage_verified"], True)
        self.assertNotIn("review_retry_required", result)
        return client, payload, result

    def test_wrap_up_again_is_answered_from_the_kept_capture_without_a_provider_call(self):
        client, payload, result = self.paused()
        calls = client.request.call_count
        for _ in range(3):
            again = client.coordinator.interview(after(payload, result))
            self.assertIs(again.get("no_new_run"), True)
            self.assertEqual(again["question"], result["question"])
            self.assertEqual(again["speech_authorization"]["kind"], "pause")
            self.assertIs(again["coverage_verified"], True)
            self.assertEqual(again["memo_findings"], result["memo_findings"])
            self.assertEqual(again["capture_token"], result["capture_token"],
                             "The capture that was kept stays the one the page continues from")
        self.assertEqual(client.request.call_count, calls, "Three more presses cost no provider call")

    def test_the_same_holds_when_the_pause_line_never_reached_the_transcript(self):
        client, payload, result = self.paused()
        calls = client.request.call_count
        again = client.coordinator.interview(after(payload, result, line=False))
        self.assertIs(again.get("no_new_run"), True)
        self.assertEqual(again["question"], result["question"])
        self.assertEqual(client.request.call_count, calls)

    def test_the_concurrent_wrap_up_returns_it_without_a_map_or_review_call(self):
        client, payload, result = self.paused()
        calls = client.request.call_count
        service = server.local_module("concurrent_interview", "concurrent_interview.py").ConcurrentInterview(client, server)
        self.addCleanup(service.close)
        synced = service.sync(after(payload, result))
        self.assertIs(synced.get("no_new_run"), True)
        self.assertEqual(synced["question"], result["question"])
        self.assertEqual(synced["speech_authorization"]["kind"], "pause")
        self.assertNotIn("workflow_capture", synced)
        self.assertEqual(client.request.call_count, calls)

    def test_a_new_answer_after_the_pause_is_captured_again(self):
        client, payload, result = self.paused()
        calls = client.request.call_count
        for action in ("close", "answer"):
            added = after(payload, result, {"id": "u_more", "role": "user",
                                            "text": "Actually the credit controller receives the corrected invoice."},
                          action=action)
            newer = client.coordinator.interview(added)
            self.assertIsNot(newer.get("no_new_run"), True, action)
            self.assertGreater(client.request.call_count, calls, action)
            calls = client.request.call_count

    def test_a_review_that_failed_is_not_treated_as_an_ending(self):
        client = SyntheticTeamProvider()
        unavailable_gap(client)
        payload, pending = prepared_review(client)
        client.faults["process_specialist_review"] = server.APIError("Synthetic review outage", 503)
        failed = client.coordinator.review(payload)
        self.assertEqual(failed["speech_authorization"]["kind"], "pause")
        self.assertIs(failed.get("review_retry_required"), True)
        self.assertIsNot(failed.get("coverage_verified"), True)
        client.faults.clear()
        calls = client.request.call_count
        again = client.coordinator.interview(after(payload, failed))
        self.assertIsNot(again.get("no_new_run"), True, "Wrap up after a failed review works on the account again")
        self.assertGreater(client.request.call_count, calls)

    def test_wrap_up_after_an_ordinary_question_still_runs(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        payload = client.payload()
        asked = client.coordinator.interview(payload)
        self.assertEqual(asked["speech_authorization"]["kind"], "question")
        calls = client.request.call_count
        closing = client.coordinator.interview(after(payload, asked))
        self.assertIsNot(closing.get("no_new_run"), True)
        self.assertGreater(client.request.call_count, calls, "Wrap up is never answered from the cache of a question")

    def test_wrap_up_after_the_final_check_was_asked_still_runs(self):
        client = SyntheticTeamProvider()
        payload, result = reviewed_capture(client)
        self.assertEqual(result["speech_authorization"]["kind"], "final_check")
        calls = client.request.call_count
        closing = client.coordinator.interview(after(payload, result))
        self.assertIsNot(closing.get("no_new_run"), True)
        self.assertGreaterEqual(client.request.call_count, calls + 1)


if __name__ == "__main__":
    unittest.main()
