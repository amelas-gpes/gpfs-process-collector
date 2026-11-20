"""The request-size limit and the transcript limit must describe the same interview.

The browser and validate_payload allow 400,000 transcript characters. The interview
routes receive the whole transcript on every request, so their byte limit has to admit
that many characters in any script. No provider and no settings file: the client below
runs the server's own validate_payload, the first thing every real route does.
"""
import http.client
import json
import socket
import tempfile
import threading
import types
import unittest
from pathlib import Path

from test_server import server


class ValidatingClient:
    """Not an OpenAIClient: no key and no network."""
    voice_mode = "reviewed"

    def __init__(self):
        self.coordinator = types.SimpleNamespace(review=self._ok, interview=self._ok, workflow=self._ok,
                                                 advisory_coverage=self._ok, status=self._status, cancel=self._status)

    def public_config(self):
        return {"api_configured": True}

    def browser_connect_sources(self):
        return ()

    def _ok(self, payload):
        _, turns = server.validate_payload(payload)
        return {"ok": True, "turns": len(turns), "chars": sum(len(turn["text"]) for turn in turns),
                "workflow": {"steps": []}}

    def _status(self, *_):
        return {"ok": True}

    interview = draft = workflow = voice_session = _ok


def snapshot(char, sizes):
    """The shape web/app.js snapshot() posts: context, turns, session and file fields."""
    turns = [{"id": f"t{index + 1:03d}", "role": "user" if index % 2 == 0 else "assistant", "text": char * size}
             for index, size in enumerate(sizes)]
    return {"context": {"process_name": "Invoices", "process_owner": "", "objective": "", "background": ""},
            "turns": turns, "session": {"closure_requested": False}, "document_revision": '[""]',
            "document_source_ids": [], "action": "answer"}


# 66 answers of the per-turn maximum and one of 4,000 characters: exactly the 400,000
# characters that the composer (web/app.js transcriptHasRoom) and validate_payload allow.
FULL_TRANSCRIPT = [6000] * 66 + [4000]
SCRIPTS = {"ASCII": "a", "Cyrillic": "я", "Greek": "ω", "Arabic": "ش", "Devanagari": "क",
           "CJK": "好", "Japanese": "あ"}
INTERVIEW_ROUTES = ("/api/interview", "/api/draft", "/api/workflow", "/api/agent-team/interview",
                    "/api/agent-team/workflow", "/api/agent-team/review", "/api/agent-team/coverage")


class RequestSizeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=ValidatingClient(),
                                           documents_root=root / "documents", knowledge_settings={})
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=5)
        cls.folder.cleanup()

    def post(self, path, body):
        # JSON.stringify leaves non-ASCII text unescaped, so the browser sends UTF-8.
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=30)
        try:
            connection.request("POST", path, body=raw, headers={
                "Content-Type": "application/json", "X-CSRF-Token": self.httpd.csrf_token,
                "Origin": f"http://127.0.0.1:{self.httpd.server_port}"})
            response = connection.getresponse()
            return len(raw), response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def post_like_a_browser(self, path, raw):
        """Send the whole body before reading anything, as Chrome does."""
        head = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.httpd.server_port}\r\n"
                f"Content-Type: application/json\r\nX-CSRF-Token: {self.httpd.csrf_token}\r\n"
                f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n").encode("ascii")
        with socket.create_connection(("127.0.0.1", self.httpd.server_port), timeout=30) as client:
            client.sendall(head)
            client.sendall(raw)
            received = bytearray()
            while chunk := client.recv(65536):
                received.extend(chunk)
        header, _, body = bytes(received).partition(b"\r\n\r\n")
        return int(header.split(b" ", 2)[1]), json.loads(body.decode("utf-8"))

    def test_a_full_transcript_in_any_script_fits_every_interview_route(self):
        self.assertEqual(sum(FULL_TRANSCRIPT), 400_000)
        for name, char in SCRIPTS.items():
            body = snapshot(char, FULL_TRANSCRIPT)
            for path in INTERVIEW_ROUTES:
                with self.subTest(script=name, path=path):
                    size, status, result = self.post(path, body)
                    self.assertEqual((status, result.get("chars")), (200, 400_000), (size, result))

    def test_the_largest_full_transcript_leaves_room_for_the_rest_of_the_request(self):
        # Three bytes per character is the most a 400,000-unit browser transcript can
        # weigh (a character outside the Basic Multilingual Plane counts as two units
        # in the browser and is four bytes). Context, turn fields and the other
        # snapshot fields must still fit.
        raw = json.dumps(snapshot("好", FULL_TRANSCRIPT), ensure_ascii=False).encode("utf-8")
        self.assertGreater(len(raw), 1_200_000)
        self.assertLessEqual(len(raw) + 500_000, server.MAX_SNAPSHOT_JSON)

    def test_a_transcript_over_the_character_limit_gets_the_transcript_message_in_any_script(self):
        for name, char in SCRIPTS.items():
            with self.subTest(script=name):
                _, status, result = self.post("/api/interview", snapshot(char, FULL_TRANSCRIPT + [2000]))
                self.assertEqual(status, 400)
                self.assertIn("text context limit is reached", result["error"])
                self.assertIn("Save the session", result["error"])

    def test_a_request_over_the_byte_limit_is_answered_with_a_message_about_the_interview(self):
        raw = b'{"padding":"' + b"a" * (server.MAX_SNAPSHOT_JSON + 200_000) + b'"}'
        for path in ("/api/interview", "/api/draft", "/api/agent-team/review"):
            for attempt in range(3):
                with self.subTest(path=path, attempt=attempt):
                    status, result = self.post_like_a_browser(path, raw)
                    self.assertEqual(status, 413)
                    self.assertIn("too large", result["error"])
                    self.assertIn("Save copy", result["error"])
                    self.assertNotIn("prototype limit", result["error"])

    def test_an_empty_request_is_not_called_too_large(self):
        _, status, result = self.post("/api/interview", b"")
        self.assertEqual(status, 400)  # empty is a bad request, not one that is too large
        self.assertNotIn("too large", result["error"])
        self.assertIn("empty", result["error"])

    def test_routes_with_small_bodies_keep_the_small_limit(self):
        self.assertLess(server.MAX_JSON, server.MAX_SNAPSHOT_JSON)
        raw = b'{"run_id":"' + b"a" * (server.MAX_JSON + 1000) + b'"}'
        for path in ("/api/agent-team/status", "/api/agent-team/cancel", "/api/voice-session"):
            with self.subTest(path=path):
                status, _ = self.post_like_a_browser(path, raw)
                self.assertEqual(status, 413)
        for path in INTERVIEW_ROUTES:
            self.assertEqual(server.request_body_limit(path), server.MAX_SNAPSHOT_JSON, path)
        for path in ("/api/agent-team/status", "/api/agent-team/cancel", "/api/voice-session"):
            self.assertEqual(server.request_body_limit(path), server.MAX_JSON, path)
        self.assertEqual(server.request_body_limit("/api/transcribe"), server.MAX_AUDIO)

    def test_a_body_far_beyond_the_limit_is_not_read(self):
        class Body:
            def __init__(self, available):
                self.available, self.read = available, 0

            def read1(self, size):
                if self.available <= 0:
                    raise TimeoutError("silent")
                chunk = b"x" * min(size, self.available)
                self.available -= len(chunk)
                self.read += len(chunk)
                return chunk

        def handler(available):
            item = object.__new__(server.Handler)
            item.server = types.SimpleNamespace(body_timeout=30, header_timeout=10)
            item.timeouts = []
            item.connection = types.SimpleNamespace(settimeout=item.timeouts.append)
            item.rfile = Body(available)
            return item

        beyond = handler(server.MAX_REJECTED_DRAIN + 1)
        beyond._discard_oversize_body(server.MAX_REJECTED_DRAIN + 1)
        self.assertEqual(beyond.rfile.read, 0)
        self.assertTrue(beyond.close_connection)
        whole = handler(server.MAX_REJECTED_DRAIN)
        whole._discard_oversize_body(server.MAX_REJECTED_DRAIN)
        self.assertEqual(whole.rfile.read, server.MAX_REJECTED_DRAIN)
        self.assertTrue(whole.close_connection)
        # Each wait for more bytes is short, and the connection's own timeout is restored.
        self.assertLessEqual(max(whole.timeouts[:-1]), .5)
        self.assertEqual(whole.timeouts[-1], 10)
        # A sender that declares more than it sends does not hold the worker.
        silent = handler(1000)
        silent._discard_oversize_body(server.MAX_SNAPSHOT_JSON + 1)
        self.assertEqual(silent.rfile.read, 1000)
        self.assertEqual(silent.timeouts[-1], 10)


if __name__ == "__main__":
    unittest.main()
