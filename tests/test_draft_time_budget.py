"""The time allowed for the first draft request grows with the interview.

The draft is one response that arrives whole, so its timeout bounds the entire
generation. Two measured generations took 74 s (14 steps) and 58 s (10 steps), about
5.5 s per step; a fixed 120 s therefore failed, repeatably, for exactly the interviews
with the most to report. No provider: every reply and every duration here is scripted.
"""
import copy
import re
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_server import server, interview_payload, process_draft, fixture_draft_audit


APP = Path(__file__).resolve().parents[1]
COVERAGE_REVIEW_TIMEOUT = 120  # OpenAIClient.coverage_review, the last request of a draft


def turns_of(participant_characters, answers=20):
    size = participant_characters // answers
    turns = []
    for index in range(answers):
        turns.append({"id": f"q{index}", "role": "assistant", "text": "What happens next?"})
        turns.append({"id": f"u{index}", "role": "user", "text": "x" * size})
    return turns


def long_payload(participant_characters):
    payload = interview_payload()
    payload["turns"] = payload["turns"] + [
        {"id": f"long{index}", "role": "user", "text": "The clerk then files the record. " * 60}
        for index in range(-(-participant_characters // 1980))]
    return payload


class Clock:
    def __init__(self):
        self.now = 70000.0

    def __call__(self):
        return self.now


class DraftGenerationTimeoutTests(unittest.TestCase):
    def test_a_short_interview_keeps_the_base_allowance(self):
        self.assertEqual(server.draft_generation_timeout([]), server.DRAFT_GENERATION_TIMEOUT)
        self.assertEqual(server.draft_generation_timeout(interview_payload()["turns"]), server.DRAFT_GENERATION_TIMEOUT)
        # The two measured interviews (1,715 and 5,376 participant characters) finished in
        # 58 s and 74 s; neither needs less than it had.
        for characters in (1715, 5376):
            self.assertGreaterEqual(server.draft_generation_timeout(turns_of(characters)), server.DRAFT_GENERATION_TIMEOUT)

    def test_the_allowance_grows_with_what_the_participant_said_up_to_the_ceiling(self):
        sizes = (0, 2000, 4000, 6000, 8000, 12000, 20000, 60000, 400000)
        allowed = [server.draft_generation_timeout(turns_of(size)) for size in sizes]
        self.assertEqual(allowed, sorted(allowed))
        self.assertGreater(allowed[4], allowed[1])
        self.assertEqual(allowed[-1], server.DRAFT_GENERATION_TIMEOUT_MAX)
        self.assertEqual(allowed[-2], server.DRAFT_GENERATION_TIMEOUT_MAX)
        self.assertTrue(all(server.DRAFT_GENERATION_TIMEOUT <= value <= server.DRAFT_GENERATION_TIMEOUT_MAX
                            for value in allowed))
        self.assertTrue(all(type(value) is int for value in allowed))

    def test_a_thorough_interview_is_allowed_the_time_its_draft_takes(self):
        # 25 to 30 steps at the measured 5.5 s per step is 140 to 165 s. The densest
        # measured interview gave one step per 170 participant characters, so even a
        # terse account of 30 steps has about 5,100 characters; a typical one has more.
        self.assertGreaterEqual(server.draft_generation_timeout(turns_of(30 * 170)), 165)
        self.assertGreaterEqual(server.draft_generation_timeout(turns_of(25 * 170)), 140)

    def test_the_ceiling_covers_the_whole_output_allowance(self):
        # 22,000 output tokens are about 88,000 characters of draft; the two measured
        # generations wrote 344 and 377 characters a second.
        self.assertGreaterEqual(server.DRAFT_GENERATION_TIMEOUT_MAX, 88000 / 344)

    def test_only_the_participant_and_the_reference_files_count(self):
        interviewer_only = [{"id": f"a{index}", "role": "assistant", "text": "x" * 6000} for index in range(40)]
        self.assertEqual(server.draft_generation_timeout(interviewer_only), server.DRAFT_GENERATION_TIMEOUT)
        files = [{"id": f"doc_{index}", "text": "x" * 4000} for index in range(5)]
        self.assertEqual(server.draft_generation_timeout([], files), server.draft_generation_timeout(turns_of(20000)))
        self.assertGreater(server.draft_generation_timeout([], files), server.DRAFT_GENERATION_TIMEOUT)


class DraftRequestBudgetTests(unittest.TestCase):
    def client(self, clock, seconds):
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        draft = process_draft()

        def structured(instructions, payload, schema, name, *args, **kwargs):
            if name == "process_draft":
                took = seconds["process_draft"]
                if took > kwargs["request_timeout"]:
                    clock.now += kwargs["request_timeout"]
                    raise server.APIError("The OpenAI request timed out. Your session and previous capture are retained."
                                          " Try again; your saved files do not need to be uploaded again.", 504)
                clock.now += took
                return copy.deepcopy(draft)
            if name == "process_draft_audit":
                clock.now += seconds["process_draft_audit"]
                return fixture_draft_audit(draft, payload["turns"])
            raise server.APIError("No further scripted reply.", 503)
        client.structured = Mock(side_effect=structured)
        return client

    def test_a_thirty_step_draft_no_longer_times_out_on_every_attempt(self):
        clock = Clock()
        client = self.client(clock, {"process_draft": 165, "process_draft_audit": 100})
        with patch.object(server.time, "monotonic", clock):
            result = client.draft(long_payload(9000))
        self.assertIn("draft", result)
        first = client.structured.call_args_list[0]
        self.assertEqual(first.args[3], "process_draft")
        self.assertGreaterEqual(first.kwargs["request_timeout"], 165)
        self.assertEqual(client.structured.call_args_list[1].kwargs["request_timeout"], server.DRAFT_AUDIT_TIMEOUT)

    def test_a_short_interview_is_still_given_up_after_the_base_allowance(self):
        clock = Clock()
        client = self.client(clock, {"process_draft": 165, "process_draft_audit": 100})
        with patch.object(server.time, "monotonic", clock):
            with self.assertRaisesRegex(server.APIError, "timed out"):
                client.draft(interview_payload())
        self.assertEqual(client.structured.call_args_list[0].kwargs["request_timeout"], server.DRAFT_GENERATION_TIMEOUT)

    def test_the_second_route_review_is_measured_from_the_same_allowance(self):
        # RouteRecheck may use only what generation and audit left unused. With the larger
        # allowance of a long interview that is still true, counted from the same start.
        payload = long_payload(9000)
        allowed = server.draft_generation_timeout(payload["turns"])
        self.assertGreater(allowed, server.DRAFT_GENERATION_TIMEOUT)
        clock = Clock()
        started = clock.now
        client = self.client(clock, {"process_draft": allowed - 25, "process_draft_audit": server.DRAFT_AUDIT_TIMEOUT - 20})
        deadlines = []
        real = server.RouteRecheck

        def recorded(*args, **kwargs):
            deadlines.append(args[5])
            return real(*args, **kwargs)
        with patch.object(server.time, "monotonic", clock), patch.object(server, "RouteRecheck", recorded):
            client.draft(payload)
        self.assertEqual(deadlines, [started + allowed + server.DRAFT_AUDIT_TIMEOUT])

    def test_the_browser_waits_at_least_as_long_as_the_server_may_take(self):
        source = (APP / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('timeout:requestTimeout("draft",690000)', source)
        server_total = server.DRAFT_GENERATION_TIMEOUT_MAX + server.DRAFT_AUDIT_TIMEOUT + COVERAGE_REVIEW_TIMEOUT
        self.assertGreaterEqual(server.REQUEST_TIMEOUTS_MS["draft"], (server_total + 30) * 1000)



if __name__ == "__main__":
    unittest.main()
