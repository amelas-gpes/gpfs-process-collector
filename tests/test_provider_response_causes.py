"""A model response that arrived but cannot be used says why, to the person and in the lifecycle log.

A cut-off answer, a content filter and a provider failure are different problems with different
remedies. Each gets its own wording and a diagnostic row of its own, because the transport row for
the same call legitimately reads outcome=success, status=200. Offline: server.openai_transport.urlopen is replaced.
"""

import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provider_response_causes_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

KEY = "sk-synthetic-response-causes-never-real"
PRIVATE = "PRIVATE_CONTENT_SENTINEL"
SCHEMA = {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"],
          "additionalProperties": False}
USAGE = {"input_tokens": 900, "output_tokens": 600, "output_tokens_details": {"reasoning_tokens": 512}}
GENERIC = "The model did not finish its response. Your session is retained; try again."


def text_output(text):
    return [{"content": [{"type": "output_text", "text": text}]}]


def stream(*events):
    return io.BytesIO("".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()
                      + b"data: [DONE]\n\n")


class Causes(unittest.TestCase):
    def call(self, answer, **options):
        """Run one structured call; return (result or APIError, every diagnostic call)."""
        diagnostics = Mock()
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY}, diagnostics)
        raw = answer if isinstance(answer, io.BytesIO) else io.BytesIO(json.dumps(answer).encode())
        with patch.object(server.openai_transport, "urlopen", return_value=raw):
            try:
                outcome = client.structured("Synthetic instructions.", {"question": PRIVATE}, SCHEMA,
                                            "conversation_question", 600, **options)
            except server.APIError as error:
                outcome = error
        calls = diagnostics.call_args_list
        self.assertNotIn(PRIVATE, repr(calls))
        self.assertNotIn(KEY, repr(calls))
        return outcome, calls

    def rejected(self, answer, **options):
        outcome, calls = self.call(answer, **options)
        self.assertIsInstance(outcome, server.APIError)
        self.assertEqual([call.args[0] for call in calls], ["provider_request_finished", "provider_response_unusable"])
        transport, cause = (call.kwargs for call in calls)
        # The transport really succeeded; the second row is the one that explains the failure.
        self.assertEqual((transport["outcome"], transport["status"]), ("success", 200))
        self.assertEqual((cause["outcome"], cause["stage"]), ("error", "conversation_question"))
        return str(outcome), cause

    def test_an_answer_cut_off_at_the_output_limit_says_so(self):
        for partial in ([], text_output('{"note": "half an ans')):
            with self.subTest(partial=bool(partial)):
                message, cause = self.rejected({"status": "incomplete", "model": "gpt-6-luna-2026-09-01",
                                                "incomplete_details": {"reason": "max_output_tokens"},
                                                "output": partial, "usage": USAGE})
                self.assertNotEqual(message, GENERIC)
                self.assertIn("longer than this step allows", message)
                self.assertIn("retained", message)
                self.assertEqual((cause["error_category"], cause["reason"]), ("output_truncated", "max_output_tokens"))
                # Budget pressure is visible: how much was spent, and how much of it on reasoning.
                self.assertEqual((cause["output_tokens"], cause["reasoning_tokens"], cause["model"]),
                                 (600, 512, "gpt-6-luna-2026-09-01"))

    def test_a_content_filter_is_named_and_asks_for_other_wording(self):
        message, cause = self.rejected({"status": "incomplete", "incomplete_details": {"reason": "content_filter"},
                                        "output": []})
        self.assertIn("content filter", message)
        self.assertIn("retained", message)
        self.assertNotIn("longer than this step allows", message)
        self.assertEqual((cause["error_category"], cause["reason"]), ("content_filter", "content_filter"))

    def test_a_failed_response_is_worded_like_the_same_http_failure(self):
        cases = (("rate_limit_exceeded", server.RATE_LIMIT_MESSAGE),
                 ("insufficient_quota", server.QUOTA_MESSAGE),
                 ("server_error", "The AI service reported a failure while preparing the response. "
                                  "Your session is retained; try again."))
        for code, expected in cases:
            with self.subTest(code=code):
                message, cause = self.rejected({"status": "failed", "output": [],
                                                "error": {"code": code, "message": PRIVATE}})
                self.assertEqual(message, expected)
                self.assertEqual((cause["error_category"], cause["reason"]), ("response_failed", code))

    def test_the_http_branches_keep_the_wording_they_share(self):
        self.assertEqual(server.RATE_LIMIT_MESSAGE,
                         "The AI service's rate limit was reached. Wait briefly, then try again. Your answer is retained.")
        self.assertEqual(server.QUOTA_MESSAGE, "The selected API project has no available API quota. "
                                               "Check that project's billing and usage limits.")

    def test_provider_text_and_unlisted_codes_never_reach_the_message_or_the_log(self):
        shapes = ({"status": "failed", "error": {"code": PRIVATE, "message": PRIVATE}},
                  {"status": "failed", "error": {"code": "a_code_this_app_does_not_list"}},
                  {"status": "failed", "error": PRIVATE},
                  {"status": "failed", "error": None},
                  {"status": "failed", "error": {"code": 7}},
                  {"status": "failed"})
        for shape in shapes:
            with self.subTest(shape=repr(shape)[:60]):
                message, cause = self.rejected({**shape, "output": []})
                self.assertNotIn(PRIVATE, message)
                self.assertNotIn("a_code_this_app_does_not_list", message)
                self.assertEqual(cause["error_category"], "response_failed")
                self.assertNotIn("reason", cause)

    def test_an_unexplained_unfinished_response_keeps_the_plain_wording(self):
        shapes = ({"status": "incomplete"}, {"status": "incomplete", "incomplete_details": None},
                  {"status": "incomplete", "incomplete_details": PRIVATE},
                  {"status": "incomplete", "incomplete_details": {"reason": PRIVATE}},
                  {"status": "incomplete", "incomplete_details": {"reason": ["max_output_tokens"]}},
                  {"status": "cancelled"}, {"status": "in_progress"}, {"status": PRIVATE})
        for shape in shapes:
            with self.subTest(shape=repr(shape)[:60]):
                message, cause = self.rejected({**shape, "output": []})
                self.assertEqual(message, GENERIC)
                self.assertEqual(cause["error_category"], "response_failed")
                self.assertNotIn("reason", cause)

    def test_a_refusal_and_unusable_json_are_logged_as_such(self):
        message, cause = self.rejected({"status": "completed", "usage": USAGE,
                                        "output": [{"content": [{"type": "refusal", "refusal": PRIVATE}]}]})
        self.assertEqual(message, "The model declined this request. Rephrase the process context or answer and try again.")
        self.assertEqual(cause["error_category"], "refusal")
        self.assertEqual(cause["output_tokens"], 600)
        for text in ('{"note": "unterminated', "", PRIVATE):
            with self.subTest(text=text[:20]):
                message, cause = self.rejected({"status": "completed", "output": text_output(text)})
                self.assertEqual(message, server.UNUSABLE_RESULT_MESSAGE)
                self.assertEqual(cause["error_category"], "invalid_json")

    def test_a_usable_response_adds_no_second_row(self):
        for answer in ({"status": "completed", "output": text_output('{"note": "kept"}')},
                       {"output": text_output('{"note": "kept"}')}):
            outcome, calls = self.call(answer)
            self.assertEqual(outcome, {"note": "kept"})
            self.assertEqual([call.args[0] for call in calls], ["provider_request_finished"])

    def test_streamed_terminal_events_carry_the_same_causes(self):
        delta = {"type": "response.output_text.delta", "delta": '{"note": "half'}
        cases = (
            ({"type": "response.incomplete", "response": {"status": "incomplete", "usage": USAGE,
                                                          "incomplete_details": {"reason": "max_output_tokens"}}},
             "output_truncated", "longer than this step allows"),
            ({"type": "response.incomplete", "response": {"status": "incomplete",
                                                          "incomplete_details": {"reason": "content_filter"}}},
             "content_filter", "content filter"),
            ({"type": "response.failed", "response": {"status": "failed", "error": {"code": "rate_limit_exceeded"}}},
             "response_failed", server.RATE_LIMIT_MESSAGE),
        )
        for final, category, wording in cases:
            with self.subTest(category=category, kind=final["type"]):
                message, cause = self.rejected(stream(delta, final), on_text=lambda text: False)
                self.assertIn(wording, message)
                self.assertEqual(cause["error_category"], category)

    def test_a_streamed_error_event_is_a_provider_failure_not_an_unreadable_response(self):
        delta = {"type": "response.output_text.delta", "delta": '{"note": "half'}
        cases = (({"type": "error", "code": "rate_limit_exceeded", "message": PRIVATE}, server.RATE_LIMIT_MESSAGE,
                  "rate_limit_exceeded"),
                 ({"type": "error", "error": {"code": "insufficient_quota", "message": PRIVATE}}, server.QUOTA_MESSAGE,
                  "insufficient_quota"),
                 ({"type": "error", "code": "server_error", "message": PRIVATE},
                  "The AI service reported a failure while preparing the response. Your session is retained; try again.",
                  "server_error"),
                 ({"type": "error", "code": PRIVATE, "message": PRIVATE},
                  "The AI service reported a failure while preparing the response. Your session is retained; try again.", None),
                 ({"type": "error"},
                  "The AI service reported a failure while preparing the response. Your session is retained; try again.", None))
        for event, expected, reason in cases:
            with self.subTest(event=repr(event)[:50]):
                message, cause = self.rejected(stream(delta, event), on_text=lambda text: False)
                self.assertEqual(message, expected)
                self.assertNotIn("unreadable", message)
                self.assertEqual(cause["error_category"], "response_failed")
                self.assertEqual(cause.get("reason"), reason)

    def test_a_stream_that_cannot_be_read_is_still_an_unreadable_response(self):
        for raw in (io.BytesIO(b"data: not json\n\n"),
                    stream({"type": "response.output_text.delta", "delta": "{"})):
            outcome, calls = self.call(raw, on_text=lambda text: False)
            self.assertEqual(str(outcome), "The AI service returned an unreadable response. Please try again.")
            self.assertEqual([call.args[0] for call in calls], ["provider_request_finished"])
            self.assertEqual((calls[0].kwargs["outcome"], calls[0].kwargs["error_category"]), ("error", "invalid_response"))

    def test_a_failing_diagnostic_sink_never_changes_the_message(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY}, Mock(side_effect=RuntimeError("sink failed")))
        answer = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
        with patch.object(server.openai_transport, "urlopen", return_value=io.BytesIO(json.dumps(answer).encode())):
            with self.assertRaises(server.APIError) as raised:
                client.structured("Synthetic instructions.", {"question": PRIVATE}, SCHEMA, "conversation_question", 600)
        self.assertIn("longer than this step allows", str(raised.exception))
        # A client that has no sink (a standalone script) behaves the same.
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        with patch.object(server.openai_transport, "urlopen", return_value=io.BytesIO(json.dumps(answer).encode())):
            with self.assertRaises(server.APIError):
                client.structured("Synthetic instructions.", {"question": PRIVATE}, SCHEMA, "conversation_question", 600)

    def test_the_lifecycle_log_keeps_the_cause_row(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="collector-response-cause-") as temporary:
            path = Path(temporary) / "work" / "server-lifecycle.jsonl"
            client = server.OpenAIClient({"OPENAI_API_KEY": KEY},
                                         lambda event, **fields: server.record_diagnostic(path, event, **fields))
            answer = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                      "output": text_output('{"note": "' + PRIVATE), "usage": USAGE}
            with patch.object(server.openai_transport, "urlopen", return_value=io.BytesIO(json.dumps(answer).encode())):
                with self.assertRaises(server.APIError):
                    client.structured("Synthetic instructions.", {"question": PRIVATE}, SCHEMA, "process_draft_audit", 600)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["event"] for row in rows], ["provider_request_finished", "provider_response_unusable"])
            self.assertEqual({key: rows[1][key] for key in ("stage", "outcome", "error_category", "reason",
                                                           "output_tokens", "reasoning_tokens")},
                             {"stage": "process_draft_audit", "outcome": "error", "error_category": "output_truncated",
                              "reason": "max_output_tokens", "output_tokens": 600, "reasoning_tokens": 512})
            self.assertNotIn(PRIVATE, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
