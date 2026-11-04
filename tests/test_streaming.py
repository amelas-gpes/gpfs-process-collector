"""Streamed lead responses: SSE parsing, request shape and the provisional question boundary."""
import json
import unittest
from unittest.mock import Mock, patch

from test_server import server
from test_interview_orchestrator import SyntheticTeamProvider


def sse(events):
    lines = []
    for event in events:
        lines += [b"event: " + event["type"].encode() + b"\n", b"data: " + json.dumps(event).encode() + b"\n", b"\n"]
    return lines


def delta(text):
    return {"type": "response.output_text.delta", "delta": text}


FINAL = {"status": "completed", "output": [{"content": [{"type": "output_text", "text": '{"question": "Q?"}'}]}]}


class FakeResponse:
    def __init__(self, lines):
        self.lines, self.status = lines, 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        return iter(self.lines)


class StreamParsingTests(unittest.TestCase):
    def test_deltas_accumulate_until_the_observer_is_satisfied(self):
        seen = []

        def observe(text):
            seen.append(text)
            return text.endswith("Q?")
        lines = sse([delta('{"question": '), delta('"Q?'), delta('", "x": 1}'),
                     {"type": "response.completed", "response": FINAL}]) + [b"data: [DONE]\n", b"\n"]
        self.assertEqual(server.OpenAIClient._read_stream(FakeResponse(lines), observe), FINAL)
        self.assertEqual(seen, ['{"question": ', '{"question": "Q?'])

    def test_observer_failure_does_not_stall_the_response(self):
        lines = sse([delta("a"), delta("b"), {"type": "response.completed", "response": FINAL}])
        calls = []

        def observe(text):
            calls.append(text)
            raise RuntimeError("display failure")
        self.assertEqual(server.OpenAIClient._read_stream(FakeResponse(lines), observe), FINAL)
        self.assertEqual(calls, ["a"])

    def test_stream_errors_and_missing_completion_are_unreadable_responses(self):
        for lines in (sse([delta("a"), {"type": "error", "message": "boom"}]), sse([delta("a")])):
            with self.assertRaises(ValueError):
                server.OpenAIClient._read_stream(FakeResponse(lines), lambda _: False)

    def test_request_streams_only_when_an_observer_is_supplied(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-stream-never-real"})
        lines = sse([delta('{"question": "What starts it?"'), {"type": "response.completed", "response": FINAL}])
        with patch.object(server, "urlopen", return_value=FakeResponse(lines)) as opened:
            result = client.request("responses", {"model": "m"}, on_text=lambda text: True)
        self.assertEqual(result, FINAL)
        self.assertIs(json.loads(opened.call_args.args[0].data)["stream"], True)
        plain = FakeResponse([])
        plain.read = lambda _size: json.dumps(FINAL).encode()
        with patch.object(server, "urlopen", return_value=plain) as opened:
            self.assertEqual(client.request("responses", {"model": "m"}), FINAL)
        self.assertNotIn("stream", json.loads(opened.call_args.args[0].data))

    def test_unreadable_stream_is_a_retained_provider_error(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-stream-never-real"})
        with patch.object(server, "urlopen", return_value=FakeResponse(sse([delta("a")]))):
            with self.assertRaises(server.APIError) as caught:
                client.request("responses", {"model": "m"}, on_text=lambda text: False)
        self.assertIn("unreadable", str(caught.exception))


class ProvisionalQuestionTests(unittest.TestCase):
    def streamed(self, client, partials):
        previous = client.reply

        def reply(path, body, *args, **kwargs):
            if body["text"]["format"]["name"] == "team_interview_capture":
                on_text = kwargs["on_text"]
                for text in partials:
                    on_text(text)
            return previous(path, body, *args, **kwargs)
        client.request = Mock(side_effect=reply)

    def test_usable_streamed_question_is_published_for_display_only(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        self.streamed(client, ['{"question": "What st', '{"question": "What starts the intake?", "base_revision'])
        result = client.coordinator.interview(client.payload())
        status = client.coordinator.status(result["agent_run_id"])
        self.assertEqual(status["provisional_question"], "What starts the intake?")
        self.assertEqual(result["agent_team"]["provisional_question"], "What starts the intake?")
        self.assertNotEqual(result["question"], "What starts the intake?", "The accepted capture decides the final question")

    def test_closing_language_is_never_shown_provisionally(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        self.streamed(client, ['{"question": "Anything else before we wrap up?", "base_revision'])
        result = client.coordinator.interview(client.payload())
        self.assertEqual(client.coordinator.status(result["agent_run_id"])["provisional_question"], "")

    def test_cancelled_or_stale_runs_publish_no_provisional_question(self):
        ledger = server.agent_team.build_evidence_ledger({"process_name": "x"}, [{"id": "u1", "role": "user", "text": "An answer."}])
        run = server.agent_team.TeamRun(ledger)
        self.assertTrue(run.set_provisional_question("What starts it?"))
        self.assertFalse(run.set_provisional_question(""))
        self.assertFalse(run.set_provisional_question("x" * 1601))
        run.cancel()
        self.assertEqual(run.public_status()["provisional_question"], "")
        self.assertFalse(run.set_provisional_question("What starts it?"))


if __name__ == "__main__":
    unittest.main()
