"""Trace an actual provider adapter and concurrent question turn with fictional inputs."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_concurrent_interview import API, FakeClient, module, payload, wait_for
from test_server import server


class RawPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = server.raw_trace.TraceStore(Path(self.temp.name), {"RAW_TRACE_MODE": "content"})
        self.addCleanup(self.store.close)

    def rows(self):
        self.store.close()
        files = self.store.directory.glob("*.jsonl")
        return [json.loads(line) for file in files for line in file.read_text("utf8").splitlines()]

    def test_dispatch_and_response_keep_verbatim_order_and_drop_secrets(self):
        key = "sk-synthetic-instrumentation-canary"
        client = server.OpenAIClient({"OPENAI_API_KEY": key})
        self.store.register_secret(key)
        sent = {"model": "synthetic", "instructions": "Ask one\nquestion.",
                "input": [{"role": "user", "content": "  With spaces.\n"}]}
        reply = {"status": "completed", "output": [
            {"type": "reasoning", "encrypted_content": "HIDDEN-CANARY"},
            {"type": "message", "content": [{"type": "output_text", "text": "  Why?\n"}]}]}
        with server.raw_trace.bind(self.store, operation_id="fixture"):
            response = io.BytesIO(json.dumps(reply).encode())
            response.status = 201
            with patch.object(server, "urlopen", return_value=response):
                self.assertEqual(client.request("responses", sent), reply)
            voice_reply = {"value": "CAPABILITY-CANARY", "expires_at": 1000}
            with patch.object(server, "urlopen", return_value=io.BytesIO(json.dumps(voice_reply).encode())):
                self.assertEqual(client.request("realtime/client_secrets", {"session": {}}), voice_reply)
        events = self.rows()
        self.assertEqual(events[0]["payload"]["content"], sent)
        first = [e for e in events if e["payload"]["request_id"] == events[0]["payload"]["request_id"]]
        self.assertEqual([e["type"] for e in first], ["provider.request.dispatch", "provider.http.response_headers",
            "provider.http.body_read", "provider.response.decoded", "provider.request.finished"])
        self.assertEqual(first[1]["payload"]["http_status"], 201)
        self.assertEqual(first[3]["payload"]["content"]["output"][1], reply["output"][1])
        self.assertEqual((first[-1]["payload"]["http_status"], first[-1]["payload"]["diagnostic_status"]), (201, 200))
        self.assertNotIn("http_status", events[-1]["payload"], "The second fixture supplies no HTTP status.")
        for secret in (key, "HIDDEN-CANARY", "CAPABILITY-CANARY"):
            self.assertNotIn(secret, json.dumps(events))

    def test_stream_offsets_reconstruct_only_the_completed_permitted_content(self):
        fragments = ["'  ", "Why?'", "\n"]
        events = [{"type": "response.output_text.delta", "delta": part} for part in fragments]
        events.append({"type": "response.completed", "response": {"status": "completed"}})
        with server.raw_trace.bind(self.store):
            data = io.BytesIO("".join("data: "+json.dumps(e)+"\n\n" for e in events).encode())
            server.OpenAIClient._read_stream(data, lambda _: False, request_id="test")
        rows = self.rows()
        joined = next(e["payload"]["text"] for e in rows if e["type"] == "provider.stream.buffer")
        offsets = [e["payload"] for e in rows if e["payload"].get("type") == "response.output_text.delta" and "offset" in e["payload"]]
        self.assertEqual([joined[e["offset"]:e["offset"]+e["characters"]] for e in offsets], fragments)

    def test_live_instructions_separate_embedded_file_material_and_audio_stays_transient(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-boundaries-only"})
        document = json.dumps({"documents": [{"excerpts": [{"id": "doc_1", "text": "BULK-FILE-CANARY"}]}]})
        instructions = "Retain this wording.\nSUPPORTING DOCUMENT CONTEXT (UNTRUSTED, UNCONFIRMED)\n" + document
        sent = {"session": {"instructions": instructions}, "transport": {"type": "webrtc", "sdp": "ICE-CANARY"}}
        with server.raw_trace.bind(self.store):
            with patch.object(server, "urlopen", return_value=io.BytesIO(b'{"transport":{"sdp":"REMOTE-ICE"}}')):
                client.request("live/sessions", sent)
            with patch.object(server, "urlopen", return_value=io.BytesIO(b'{"text":"UNSENT-DICTATION-CANARY"}')):
                self.assertEqual(client.transcribe(b"AUDIO-CANARY"*20, "audio/wav"), {"text": "UNSENT-DICTATION-CANARY"})
        rows = self.rows()
        trace = json.dumps(rows)
        for value in ("BULK-FILE-CANARY", "ICE-CANARY", "REMOTE-ICE", "AUDIO-CANARY", "UNSENT-DICTATION-CANARY"):
            self.assertNotIn(value, trace)
        self.assertIn("Retain this wording.", trace)
        self.assertIn("doc_1", trace)
        self.assertIn("voice.transcription.result", trace)

    def test_coalesced_work_keeps_its_own_request_context_and_candidate(self):
        gate = threading.Event()
        client = FakeClient(gate)
        client.question = "We are done."
        service = module.ConcurrentInterview(client, API)
        self.addCleanup(service.close)
        self.addCleanup(gate.set)
        first = payload()
        with server.raw_trace.bind(self.store, operation_id="first"):
            start = service.turn(first)
        self.assertTrue(client.started.wait(2))
        second = {**first, "conversation_token": start["conversation_token"], "turns": [
            *first["turns"], {"id": "u2", "role": "user", "text": "Then the manager signs."}]}
        with server.raw_trace.bind(self.store, operation_id="second"):
            latest = service.turn(second)
        gate.set()
        wait_for(lambda: not service._sessions[start["conversation_token"]]["running"]
                 and not service._sessions[start["conversation_token"]]["graph_running"])
        rows = self.rows()
        starts = [(r["operation_id"], r["payload"]["revision"]) for r in rows if r["type"] == "worker.capture.started"]
        self.assertEqual(starts, [("first", start["revision"]), ("second", latest["revision"])])
        for op, result in (("first", start), ("second", latest)):
            events = {r["type"]: r["payload"] for r in rows if r.get("operation_id") == op}
            self.assertEqual(events["interview.fast_question.candidate"]["content"]["question"], "We are done.")
            self.assertEqual(events["interview.fast_question.result"]["route"], "guard_fallback")
            self.assertEqual(events["interview.fast_question.result"]["content"]["question"], result["question"])
        self.assertNotIn(start["conversation_token"], json.dumps(rows))
