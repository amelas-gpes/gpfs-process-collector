"""A request the server refuses before reading its body still gets its answer.

A 413, a 403 for a large body, an upload 429 and the busy 503 used to be written and the
connection closed while the client was still sending. On Windows that close resets the
connection and destroys the response, so the browser saw "Failed to fetch" instead of the status
and message. These tests send the whole declared body, as a browser does. Loopback sockets only.
"""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rejected_requests_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

MIB = 1024 * 1024
ATTEMPTS = 6


class OfflineClient:
    def public_config(self):
        return {"api_configured": False}

    def browser_connect_sources(self):
        return ()


def exchange(port, head, body=b"", chunk=64 * 1024, close_after_send=True, timeout=15):
    """Send one request the way a browser does: all of it, whatever the server does meanwhile.

    Returns (status, headers, json body or None, error). error names a transport failure
    (a reset, an abort) that prevented the complete response from being read.
    """
    received, failure = b"", None
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as client:
        try:
            client.sendall(head)
            for start in range(0, len(body), chunk):
                client.sendall(body[start:start + chunk])
            if close_after_send:
                client.shutdown(socket.SHUT_WR)
        except OSError as error:
            failure = "send: " + type(error).__name__
        try:
            while True:
                part = client.recv(65536)
                if not part:
                    break
                received += part
        except OSError as error:
            failure = "receive: " + type(error).__name__
    head_raw, _, payload = received.partition(b"\r\n\r\n")
    lines = head_raw.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1]) if lines and len(lines[0].split()) > 1 and lines[0].split()[1].isdigit() else None
    headers = {name.strip().lower(): value.strip() for name, _, value in (line.partition(":") for line in lines[1:])}
    length = int(headers.get("content-length", "-1"))
    parsed = None
    if length >= 0 and len(payload) == length:
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = None
    elif status is not None and failure is None:
        failure = "incomplete response"
    return status, headers, parsed, failure


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-rejected-")
        self.addCleanup(self.temporary.cleanup)
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=OfflineClient(),
                                            documents_root=Path(self.temporary.name) / "documents", knowledge_settings={})
        self.addCleanup(self.httpd.server_close)
        worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_port

    def head(self, path, length, token=None, content_type="application/json", extra=""):
        token = self.httpd.csrf_token if token is None else token
        return (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: http://127.0.0.1:{self.port}\r\n"
                f"X-CSRF-Token: {token}\r\nContent-Type: {content_type}\r\nContent-Length: {length}\r\n{extra}\r\n").encode()

    def slots_free(self):
        """True once every connection slot has been returned."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            taken = []
            while self.httpd.connection_slots.acquire(blocking=False):
                taken.append(None)
            for _ in taken:
                self.httpd.connection_slots.release()
            if len(taken) == self.httpd.max_connections:
                return True
            time.sleep(.02)
        return False


class RejectionsReachTheClient(Fixture):
    def all_answered(self, head, body, status, message, code=None):
        for attempt in range(ATTEMPTS):
            answer = exchange(self.port, head, body)
            self.assertEqual((answer[0], answer[3]), (status, None), f"attempt {attempt + 1}: {answer}")
            self.assertEqual(answer[2]["error"], message)
            self.assertEqual(answer[2].get("code"), code)
        self.assertTrue(self.slots_free(), "A lingering close gives its connection slot back")

    def test_an_oversized_json_body_gets_its_413(self):
        for path, limit in (("/api/interview", server.MAX_SNAPSHOT_JSON),
                            ("/api/knowledge/submit", server.MAX_KNOWLEDGE_SUBMIT),
                            ("/api/documents/status", server.MAX_JSON)):
            for size in (limit + 1, 3 * MIB):
                with self.subTest(path=path, size=size):
                    code = None
                    if path == "/api/interview":
                        message = (f"This interview is too large to send: the request is {size:,} bytes and the limit is "
                                   f"{limit:,}. Nothing was lost; the interview is still in this browser. "
                                   "Choose Save copy to keep it.")
                    elif path == "/api/knowledge/submit":
                        code = "submission_too_large"
                        message = (f"This submission is too large for company knowledge: it is {size:,} bytes "
                                   f"and the limit is {limit:,}. Nothing was saved.")
                    else:
                        message = "Document request is empty or too large."
                    body = b"{" + b" " * (size - 2) + b"}"
                    self.all_answered(self.head(path, len(body)), body, 413, message, code)

    def test_a_large_body_with_an_outdated_token_gets_its_403(self):
        for path, size, content_type in (("/api/transcribe", 2 * MIB, "audio/webm"),
                                         ("/api/documents/upload", 5 * MIB, "application/octet-stream"),
                                         ("/api/interview", 700_000, "application/json")):
            with self.subTest(path=path):
                body = b"\x00" * size
                self.all_answered(self.head(path, size, token="token-from-before-the-restart", content_type=content_type),
                                  body, 403, server.TOKEN_REJECTED_MESSAGE, "request_token_rejected")

    def test_an_upload_refused_for_capacity_gets_its_429(self):
        self.assertTrue(self.httpd.upload_slots.acquire(blocking=False))
        self.assertTrue(self.httpd.upload_slots.acquire(blocking=False))
        self.addCleanup(self.httpd.upload_slots.release)
        self.addCleanup(self.httpd.upload_slots.release)
        body = b"%PDF-1.7\n" + b"\x00" * (4 * MIB)
        head = self.head("/api/documents/upload", len(body), content_type="application/octet-stream",
                         extra="X-Document-Scope: " + "s" * 43 + "\r\nX-Document-Filename: big.pdf\r\n")
        self.all_answered(head, body, 429, "Two files are already uploading. Retry when they finish.")

    def test_an_upload_over_the_size_limit_gets_its_413_without_being_read_to_the_end(self):
        declared = server.documents.MAX_FILE_BYTES + 1
        sent = b"\x00" * (2 * MIB)  # the client gives up sending once it has the answer
        answer = exchange(self.port, self.head("/api/documents/upload", declared, content_type="application/octet-stream"), sent)
        self.assertEqual((answer[0], answer[3]), (413, None), answer)
        self.assertEqual(answer[2]["error"], "Each upload must be no larger than 64 MiB.")


class TokenRejectionWording(Fixture):
    def test_the_403_points_at_save_copy_and_carries_its_code(self):
        status, _, body, failure = exchange(self.port, self.head("/api/interview", 2, token="outdated"), b"{}")
        self.assertEqual((status, failure), (403, None))
        self.assertEqual(body, {"error": server.TOKEN_REJECTED_MESSAGE, "code": "request_token_rejected"})
        self.assertIn("Menu > Save copy", body["error"])
        self.assertIn("before you reload", body["error"])
        self.assertIn("Nothing was processed", body["error"])
        # The old advice discarded the unsaved interview.
        self.assertNotIn("refresh it before trying again", body["error"])


class LingerIsBoundedAndOnlyForRejections(Fixture):
    def test_a_request_that_was_read_in_full_closes_without_lingering(self):
        with patch.object(self.httpd, "_drain", wraps=self.httpd._drain) as drain:
            body = b'{"scope": "not-a-workspace", "context": {}, "turns": []}'
            status, _, answer, failure = exchange(self.port, self.head("/api/documents/status", len(body)), body)
            self.assertEqual((status, failure, answer.get("code")), (403, None, "document_scope_unavailable"))
            status, _, _, failure = exchange(self.port, (f"GET /api/config HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n").encode())
            self.assertEqual((status, failure), (200, None))
            self.assertTrue(self.slots_free())
            drain.assert_not_called()
            # A rejection with unread bytes is the one case that lingers.
            body = b" " * 700_000
            self.assertEqual(exchange(self.port, self.head("/api/documents/status", len(body)), body)[0], 413)
            self.assertTrue(self.slots_free())
            self.assertEqual(drain.call_count, 1)
        self.assertEqual(self.httpd._lingering, {})

    def test_a_client_that_never_sends_the_rest_cannot_hold_a_slot_for_long(self):
        self.httpd.linger_seconds = 0.6
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as stalled:
            stalled.sendall(self.head("/api/interview", 50 * MIB) + b"{")
            self.assertIn(b" 413 ", stalled.recv(65536))
            # The client keeps its side open and silent: the server gives up by itself.
            self.assertTrue(self.slots_free())
        self.assertLess(time.monotonic() - started, 4)

    def test_a_client_that_keeps_sending_is_cut_off_at_the_deadline(self):
        self.httpd.linger_seconds = 0.5
        stop, sent = threading.Event(), []

        def flood():
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=10) as client:
                    client.sendall(self.head("/api/interview", 10_000 * MIB))
                    while not stop.is_set():
                        client.sendall(b"\x00" * 65536)
                        sent.append(None)
                        time.sleep(.01)
            except OSError:
                pass
        sender = threading.Thread(target=flood, daemon=True)
        sender.start()
        self.addCleanup(sender.join, 5)
        self.addCleanup(stop.set)
        time.sleep(.2)
        started = time.monotonic()
        self.assertTrue(self.slots_free())
        self.assertLess(time.monotonic() - started, 4)

    def test_the_drain_stops_at_its_byte_cap(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        payload = b"\x00" * 300_000
        right.settimeout(5)

        def write():
            right.sendall(payload)
            right.shutdown(socket.SHUT_WR)

        # A socketpair's buffer can be smaller than this fixture. The reader must
        # be running while the writer fills it, including on a fresh macOS host.
        with ThreadPoolExecutor(max_workers=1) as pool:
            sent = pool.submit(write)
            started = time.monotonic()
            drained = self.httpd._drain(left, 100_000, 5)
            self.assertLess(time.monotonic() - started, 2, "The cap ends the drain, not the deadline")
            self.assertGreaterEqual(drained, 100_000)
            left.settimeout(5)
            remaining = sum(len(chunk) for chunk in iter(lambda: left.recv(65_536), b""))
            sent.result()
        self.assertGreater(remaining, 0, "The drain must stop before consuming the whole fixture")
        self.assertEqual(drained + remaining, len(payload))


class BusyServer(Fixture):
    def occupy(self):
        for _ in range(self.httpd.max_connections):
            self.assertTrue(self.httpd.connection_slots.acquire(blocking=False))
        released = []

        def release():
            if not released:
                released.append(None)
                for _ in range(self.httpd.max_connections):
                    self.httpd.connection_slots.release()
        self.addCleanup(release)
        return release

    def test_a_client_that_already_sent_its_request_reads_the_busy_503(self):
        self.occupy()
        body = b"{" + b" " * 300_000 + b"}"
        for attempt in range(ATTEMPTS):
            status, headers, answer, failure = exchange(self.port, self.head("/api/interview", len(body)), body)
            self.assertEqual((status, failure), (503, None), f"attempt {attempt + 1}")
            self.assertEqual(answer, {"error": "The local server is busy. Retry shortly."})
            self.assertEqual(headers.get("retry-after"), "1")

    def test_a_silent_client_does_not_delay_the_accept_loop(self):
        release = self.occupy()
        # Six clients that say nothing. Answered one after another in the accept loop, each would
        # hold it for the half second of silence its lingering close waits: three seconds in all.
        silent = [socket.create_connection(("127.0.0.1", self.port), timeout=10) for _ in range(6)]
        for client in silent:
            self.addCleanup(client.close)
        started = time.monotonic()
        status, _, answer, failure = exchange(self.port, f"GET /api/config HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
        self.assertEqual((status, failure), (503, None))
        self.assertLess(time.monotonic() - started, 2.5, "Other rejected clients are answered at once")
        for client in silent:
            self.assertIn(b" 503 ", client.recv(4096))
        release()
        status, _, _, failure = exchange(self.port, f"GET /api/config HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
        self.assertEqual((status, failure), (200, None))

    def test_a_flood_of_rejected_connections_starts_a_bounded_number_of_reply_threads(self):
        self.occupy()
        before = threading.active_count()
        clients = [socket.create_connection(("127.0.0.1", self.port), timeout=10) for _ in range(40)]
        for client in clients:
            self.addCleanup(client.close)
        time.sleep(.3)
        self.assertLessEqual(threading.active_count() - before, self.httpd.busy_reply_threads)
        answered = 0
        for client in clients:
            client.settimeout(3)
            try:
                answered += b" 503 " in client.recv(4096)
            except OSError:
                pass
        self.assertGreaterEqual(answered, self.httpd.busy_reply_threads)


if __name__ == "__main__":
    unittest.main()
