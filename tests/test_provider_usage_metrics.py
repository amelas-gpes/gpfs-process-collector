"""A finished Responses call records its model and the token counts the provider reported.

The lifecycle log receives sizes and one identifier, never content. Offline: server.openai_transport.urlopen is replaced.
"""

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provider_usage_metrics_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

KEY = "sk-synthetic-usage-metrics-never-real"
PRIVATE = "PRIVATE_CONTENT_SENTINEL"
SIZES = ("model", "input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens")
USAGE = {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 1024},
         "output_tokens": 350, "output_tokens_details": {"reasoning_tokens": 128}, "total_tokens": 1550}


def reply(**fields):
    return {"id": "resp_synthetic", "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": json.dumps({"note": PRIVATE})}]}], **fields}


def events_stream(final):
    lines = [{"type": "response.output_text.delta", "delta": json.dumps({"note": PRIVATE})},
             {"type": "response.completed", "response": final}]
    return io.BytesIO("".join("data: " + json.dumps(line) + "\n\n" for line in lines).encode() + b"data: [DONE]\n\n")


def body(model="gpt-requested-model", name="process_interview"):
    return {"model": model, "input": PRIVATE, "text": {"format": {"name": name}}}


class RequestMetricsTests(unittest.TestCase):
    def finished(self, answer, request_body=None, path="responses", **options):
        diagnostics = Mock()
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY}, diagnostics)
        raw = answer if isinstance(answer, io.BytesIO) else io.BytesIO(json.dumps(answer).encode())
        with patch.object(server.openai_transport, "urlopen", return_value=raw):
            result = client.request(path, body() if request_body is None else request_body, **options)
        self.assertEqual(diagnostics.call_args.args, ("provider_request_finished",))
        self.assertNotIn(PRIVATE, repr(diagnostics.call_args))
        self.assertNotIn(KEY, repr(diagnostics.call_args))
        return result, diagnostics.call_args.kwargs

    def test_a_finished_responses_call_records_its_model_and_token_counts(self):
        result, fields = self.finished(reply(model="gpt-5.4-mini-2026-03-17", usage=USAGE))
        self.assertEqual(result["id"], "resp_synthetic")
        self.assertEqual({name: fields.get(name) for name in SIZES}, {
            "model": "gpt-5.4-mini-2026-03-17", "input_tokens": 1200, "output_tokens": 350,
            "cached_tokens": 1024, "reasoning_tokens": 128})
        self.assertEqual((fields["outcome"], fields["status"], fields["stage"]), ("success", 200, "process_interview"))

    def test_a_streamed_call_records_the_same_fields_from_its_final_event(self):
        heard = []
        result, fields = self.finished(events_stream(reply(model="gpt-6-luna-2026-09-01", usage=USAGE)),
                                       on_text=lambda text: heard.append(text) or True)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(heard)
        self.assertEqual({name: fields.get(name) for name in SIZES}, {
            "model": "gpt-6-luna-2026-09-01", "input_tokens": 1200, "output_tokens": 350,
            "cached_tokens": 1024, "reasoning_tokens": 128})

    def test_the_requested_model_is_recorded_when_the_reply_names_none(self):
        for answer in (reply(usage=USAGE), reply(model=None, usage=USAGE), reply(model=7, usage=USAGE),
                       reply(model=PRIVATE + " with spaces", usage=USAGE), reply(model="m" * 101, usage=USAGE)):
            with self.subTest(model=repr(answer.get("model"))[:40]):
                _, fields = self.finished(answer)
                self.assertEqual(fields["model"], "gpt-requested-model")
                self.assertEqual(fields["input_tokens"], 1200)

    def test_a_model_name_that_is_not_a_plain_identifier_is_never_recorded(self):
        for requested in (PRIVATE + " with spaces", "m" * 101, "", 7, None, ["gpt"]):
            with self.subTest(requested=repr(requested)[:40]):
                _, fields = self.finished(reply(model={"name": PRIVATE}, usage=USAGE),
                                          {"model": requested, "input": PRIVATE})
                self.assertNotIn("model", fields)
                self.assertEqual(fields["output_tokens"], 350)

    def test_unusable_usage_is_left_out_and_never_fails_the_call(self):
        cases = (
            (None, {}),
            (PRIVATE, {}),
            ([1200, 350], {}),
            ({}, {}),
            ({"input_tokens": PRIVATE, "output_tokens": 350}, {"output_tokens": 350}),
            ({"input_tokens": True, "output_tokens": 1.5}, {}),
            ({"input_tokens": -5, "output_tokens": 0}, {"output_tokens": 0}),
            ({"input_tokens": 9, "input_tokens_details": PRIVATE, "output_tokens_details": [128]}, {"input_tokens": 9}),
            ({"input_tokens_details": {"cached_tokens": "many"}, "output_tokens_details": {"reasoning_tokens": 3}},
             {"reasoning_tokens": 3}),
        )
        for usage, expected in cases:
            with self.subTest(usage=repr(usage)[:60]):
                result, fields = self.finished(reply(model="gpt-reported", usage=usage))
                self.assertEqual(result["status"], "completed")
                self.assertEqual({name: fields[name] for name in SIZES[1:] if name in fields}, expected)
                self.assertEqual(fields["model"], "gpt-reported")
                self.assertEqual(fields["outcome"], "success")
        for answer in ([reply(usage=USAGE)], "text", 5):
            with self.subTest(answer=type(answer).__name__):
                with self.assertRaisesRegex(server.APIError, "unreadable response"):
                    self.finished(answer)

    def test_a_failed_call_records_no_size(self):
        diagnostics = Mock()
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY}, diagnostics)
        with patch.object(server.openai_transport, "urlopen", side_effect=TimeoutError(PRIVATE)):
            with self.assertRaises(server.APIError):
                client.request("responses", body())
        with patch.object(server.openai_transport, "urlopen", return_value=io.BytesIO(b"not json " + PRIVATE.encode())):
            with self.assertRaises(server.APIError):
                client.request("responses", body())
        for call in diagnostics.call_args_list:
            self.assertEqual(call.kwargs["outcome"], "error")
            self.assertEqual([name for name in SIZES if name in call.kwargs], [])

    def test_other_provider_routes_record_no_token_fields(self):
        for path, request_body in (("audio/transcriptions", b"audio"), ("realtime/client_secrets", {"model": "gpt-voice"}),
                                   ("live/sessions", {"model": "gpt-live"})):
            with self.subTest(path=path):
                _, fields = self.finished({"text": "spoken", "model": "gpt-other", "usage": USAGE}, request_body, path)
                self.assertEqual([name for name in SIZES if name in fields], [])

    def test_knowledge_matching_is_logged_under_its_own_stage(self):
        _, fields = self.finished(reply(usage=USAGE), body(name="knowledge_connection_proposals"))
        self.assertEqual(fields["stage"], "knowledge_connection_proposals")
        adapter = server.local_module("knowledge_ai", "knowledge_ai.py")
        diagnostics = Mock()
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY}, diagnostics)
        answer = {"status": "completed", "model": "gpt-reported", "usage": USAGE,
                  "output": [{"content": [{"type": "output_text", "text": json.dumps({"proposals": []})}]}]}
        record = {"submission_id": "s1", "process_id": "p1", "revision": 1, "turns": [], "context": {}}
        with patch.object(server.openai_transport, "urlopen", return_value=io.BytesIO(json.dumps(answer).encode())):
            self.assertEqual(adapter.build_analyzer(client)(record, [{**record, "submission_id": "s2", "process_id": "p2"}]), [])
        self.assertEqual(diagnostics.call_args.kwargs["stage"], "knowledge_connection_proposals")
        self.assertEqual(diagnostics.call_args.kwargs["input_tokens"], 1200)

    def test_an_unlisted_format_name_is_still_logged_as_plain_responses(self):
        _, fields = self.finished(reply(usage=USAGE), body(name=PRIVATE))
        self.assertEqual(fields["stage"], "responses")


class LifecycleLogTests(unittest.TestCase):
    def rows(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_the_log_keeps_the_sizes_and_still_drops_everything_else(self):
        with tempfile.TemporaryDirectory(prefix="collector-usage-log-") as temporary:
            path = Path(temporary) / "work" / "server-lifecycle.jsonl"
            server.record_diagnostic(path, "provider_request_finished", stage="process_draft", outcome="success",
                                     model="gpt-5.4-mini-2026-03-17", input_tokens=1200, output_tokens=350,
                                     cached_tokens=1024, reasoning_tokens=128, total_tokens=1550,
                                     prompt=PRIVATE, usage={"input_tokens": 1}, interview=PRIVATE)
            server.record_diagnostic(path, "provider_request_finished", model=PRIVATE + " with spaces",
                                     input_tokens=True, output_tokens=-4, cached_tokens=10 ** 12, reasoning_tokens=1.5)
            server.record_diagnostic(path, "provider_request_finished", model="m" * 101, input_tokens=None)
            first, second, third = self.rows(path)
            self.assertEqual({name: first[name] for name in SIZES}, {
                "model": "gpt-5.4-mini-2026-03-17", "input_tokens": 1200, "output_tokens": 350,
                "cached_tokens": 1024, "reasoning_tokens": 128})
            self.assertEqual(set(first), {"event", "time_utc", "pid", "version", "stage", "outcome", *SIZES})
            self.assertEqual(set(second), {"event", "time_utc", "pid", "version", "output_tokens", "cached_tokens"})
            self.assertEqual((second["output_tokens"], second["cached_tokens"]), (0, 2_147_483_647))
            self.assertEqual(set(third), {"event", "time_utc", "pid", "version"})
            self.assertNotIn(PRIVATE, path.read_text(encoding="utf-8"))

    def test_a_running_server_writes_the_sizes_of_each_responses_call(self):
        with tempfile.TemporaryDirectory(prefix="collector-usage-server-") as temporary:
            root = Path(temporary)
            client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
            httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                                           documents_root=root / "documents", knowledge_settings={})
            try:
                with patch.object(server.openai_transport, "urlopen", return_value=io.BytesIO(json.dumps(
                        reply(model="gpt-5.4-mini-2026-03-17", usage=USAGE)).encode())):
                    result = client.structured("Synthetic instructions.", {"question": PRIVATE},
                                               {"type": "object", "properties": {"note": {"type": "string"}},
                                                "required": ["note"], "additionalProperties": False},
                                               "process_interview", 100)
                self.assertEqual(result, {"note": PRIVATE})
                logged = httpd.diagnostics_path.read_text(encoding="utf-8")
                row = next(item for item in self.rows(httpd.diagnostics_path)
                           if item["event"] == "provider_request_finished")
            finally:
                httpd.server_close()
            self.assertEqual({name: row[name] for name in SIZES}, {
                "model": "gpt-5.4-mini-2026-03-17", "input_tokens": 1200, "output_tokens": 350,
                "cached_tokens": 1024, "reasoning_tokens": 128})
            self.assertEqual((row["stage"], row["outcome"], row["status"]), ("process_interview", "success", 200))
            self.assertNotIn(PRIVATE, logged)
            self.assertNotIn(KEY, logged)


if __name__ == "__main__":
    unittest.main()
