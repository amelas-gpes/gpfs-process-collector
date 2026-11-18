"""A cancelled or overdue request to the AI service ends at once and frees its slots.

A loopback server stands in for the provider and holds its answer back, the way a request
that is not streamed behaves: nothing arrives until the whole answer exists. No provider,
network or credential is used.
"""
import json
import socket
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from test_server import server


class WatchedHTTPHandler(server.NamesProviderSockets, urllib.request.HTTPHandler):
    """The application's own socket naming, over the plain HTTP of the loopback stand-in."""


class SlowProvider:
    """Answers after `delay` seconds, or as soon as `release` is set. Records what became of each request."""

    def __init__(self, delay=5.0):
        self.delay, self.release, self.outcomes = delay, threading.Event(), []
        self.waiting = threading.Event()
        self.outcome_recorded = threading.Event()
        self.prefix_bytes = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                raw = json.dumps({"status": "completed", "output": [{"content": [
                    {"type": "output_text", "text": json.dumps({"question": "What happens next?"})}]}]}).encode()
                response = (f"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n".encode() + raw)
                try:
                    if owner.prefix_bytes:
                        self.wfile.write(response[:owner.prefix_bytes])
                    owner.waiting.set()
                    owner.release.wait(owner.delay)
                    self.wfile.write(response[owner.prefix_bytes:])
                    owner.outcomes.append("answered")
                except OSError:
                    owner.outcomes.append("client_gone")
                owner.outcome_recorded.set()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.worker.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), WatchedHTTPHandler())

    def urlopen(self, request, timeout=None):
        request.full_url = f"http://127.0.0.1:{self.httpd.server_port}/v1/" + request.full_url.split("/v1/", 1)[1]
        return self.opener.open(request, timeout=timeout)

    def close(self):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)


def free(semaphore, size):
    """How many permits of a bounded semaphore are free right now."""
    taken = 0
    while taken < size and semaphore.acquire(blocking=False):
        taken += 1
    for _ in range(taken):
        semaphore.release()
    return taken


class ProviderCancellationTests(unittest.TestCase):
    def setUp(self):
        self.provider = SlowProvider()
        self.addCleanup(self.provider.close)
        self.client = server.OpenAIClient({"OPENAI_API_KEY": "sk-cancel-test-never-real"})
        patcher = patch.object(server, "urlopen", self.provider.urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, cancelled=None, timeout=30, background=False):
        outcome = {}

        def run():
            if background:
                server.provider_usage.background_work.set(True)
            started = time.monotonic()
            try:
                with self.client.request_scope("", should_abort=cancelled):
                    outcome["result"] = self.client.request("responses", {"model": "offline", "input": "x"}, timeout=timeout)
            except server.APIError as error:
                outcome["error"] = error
            outcome["seconds"] = time.monotonic() - started
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, outcome

    def test_a_cancelled_request_that_is_not_streamed_returns_at_once_and_frees_its_slot(self):
        # The map draw and its source check are not streamed. Cancelling one used to be noticed
        # only when the provider had finished the whole answer (up to four minutes later).
        flag = threading.Event()
        thread, outcome = self.ask(cancelled=flag.is_set)
        time.sleep(.3)
        self.assertEqual(free(self.client._provider_slots, self.client.provider_slots), self.client.provider_slots - 1)
        flag.set()
        thread.join(3)
        self.assertFalse(thread.is_alive(), "The cancelled request is still waiting for the provider")
        self.assertLess(outcome["seconds"], 2.5)
        self.assertEqual((outcome["error"].status, outcome["error"].category), (409, "cancelled"))
        self.assertEqual(free(self.client._provider_slots, self.client.provider_slots), self.client.provider_slots)

    def test_cancellation_interrupts_a_partial_response_without_a_socket_shutdown_wakeup(self):
        # A timed Winsock recv can still be waiting for readability after local shutdown.
        for cut in (9, 80):  # incomplete status line, then incomplete JSON body
            with self.subTest(cut=cut), patch.object(socket.socket, "shutdown", return_value=None):
                self.provider.waiting.clear()
                self.provider.prefix_bytes = cut
                flag = threading.Event()
                thread, outcome = self.ask(cancelled=flag.is_set)
                self.assertTrue(self.provider.waiting.wait(2))
                flag.set()
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual((outcome["error"].status, outcome["error"].category), (409, "cancelled"))
                self.assertEqual(free(self.client._provider_slots, self.client.provider_slots), self.client.provider_slots)

    def test_slow_partial_header_and_body_arrive_intact(self):
        self.provider.delay = .65
        for cut in (9, 80):
            with self.subTest(cut=cut):
                self.provider.prefix_bytes = cut
                thread, outcome = self.ask(cancelled=lambda: False)
                thread.join(3)
                self.assertEqual(outcome["result"]["status"], "completed")

    def test_a_request_past_its_time_is_ended_while_the_provider_is_still_silent(self):
        thread, outcome = self.ask(timeout=.6)
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertLess(outcome["seconds"], 2.5)
        self.assertEqual((outcome["error"].status, outcome["error"].category), (504, "timeout"))
        self.assertEqual(free(self.client._provider_slots, self.client.provider_slots), self.client.provider_slots)

    def test_silent_tls_handshake_can_be_cancelled_or_reach_its_deadline(self):
        # The peer accepts ClientHello but sends no handshake response. Cancellation must
        # release the request even before HTTPSConnection has returned a connected SSL socket.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), server.WatchedHTTPSHandler())
        with socket.socket() as listener:
            listener.settimeout(3)
            listener.bind(("127.0.0.1", 0))
            listener.listen()

            def local(request, timeout):
                request.full_url = f"https://127.0.0.1:{listener.getsockname()[1]}/v1/responses"
                return opener.open(request, timeout=timeout)

            with patch.object(server, "urlopen", local):
                for cancel in (True, False):
                    with self.subTest(cancel=cancel):
                        flag = threading.Event()
                        thread, outcome = self.ask(cancelled=flag.is_set, timeout=10 if cancel else .8)
                        self.addCleanup(thread.join, 3)
                        with listener.accept()[0] as peer:
                            peer.settimeout(2)
                            self.assertTrue(peer.recv(1))
                            if cancel:
                                flag.set()
                            thread.join(2)
                            self.assertFalse(thread.is_alive())
                            error = outcome["error"]
                            self.assertEqual((error.status, error.category), (409, "cancelled") if cancel else (504, "timeout"))
                            self.assertEqual(free(self.client._provider_slots, self.client.provider_slots), self.client.provider_slots)

    def test_an_answer_that_arrives_in_time_is_returned_unchanged(self):
        self.provider.release.set()
        thread, outcome = self.ask(cancelled=lambda: False)
        thread.join(5)
        self.assertEqual(outcome["result"]["status"], "completed")
        self.assertTrue(self.provider.outcome_recorded.wait(3), "The provider did not record its outcome")
        self.assertEqual(self.provider.outcomes, ["answered"])

    def test_a_cancelled_request_is_recorded_as_cancelled(self):
        records = []
        self.client.diagnostic_callback = lambda event, **fields: records.append((event, fields))
        flag = threading.Event()
        thread, _outcome = self.ask(cancelled=flag.is_set)
        time.sleep(.2)
        flag.set()
        thread.join(3)
        finished = [fields for event, fields in records if event == "provider_request_finished"]
        self.assertEqual([(row["status"], row.get("error_category")) for row in finished], [(409, "cancelled")])


class ProviderSlotTests(unittest.TestCase):
    """Background work leaves room for what a person is waiting on."""

    def test_settings_size_the_pools_and_refuse_values_outside_their_range(self):
        client = server.OpenAIClient({})
        self.assertEqual((client.provider_slots, client.map_workers), (6, 2))
        sized = server.OpenAIClient({"COLLECTOR_PROVIDER_SLOTS": "10", "COLLECTOR_MAP_WORKERS": "4"})
        self.assertEqual((sized.provider_slots, sized.map_workers), (10, 4))
        for name, value in (("COLLECTOR_PROVIDER_SLOTS", "1"), ("COLLECTOR_PROVIDER_SLOTS", "33"),
                            ("COLLECTOR_MAP_WORKERS", "0"), ("COLLECTOR_MAP_WORKERS", "nine")):
            with self.subTest(name=name, value=value), self.assertRaises(server.SettingsError) as refused:
                server.OpenAIClient({name: value})
            self.assertIn(name, str(refused.exception))
        self.assertTrue({"COLLECTOR_PROVIDER_SLOTS", "COLLECTOR_MAP_WORKERS"} <= set(self.allowed_settings()))

    @staticmethod
    def allowed_settings():
        import os
        import tempfile
        from pathlib import Path
        names = ("COLLECTOR_PROVIDER_SLOTS", "COLLECTOR_MAP_WORKERS")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / ".env.local").write_text("".join(f"{name}=3\n" for name in names), encoding="utf-8")
            with patch.object(server, "APP_DIR", Path(folder)), patch.dict(os.environ, {}, clear=True):
                return server.load_settings()

    def test_background_work_cannot_take_the_slots_kept_for_questions(self):
        provider = SlowProvider(delay=10)
        self.addCleanup(provider.close)
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-slot-test-never-real", "COLLECTOR_PROVIDER_SLOTS": "3"})
        answers, stop = [], threading.Event()

        def ask(background):
            if background:
                server.provider_usage.background_work.set(True)
            try:
                with client.request_scope("", should_abort=stop.is_set):
                    answers.append(("background" if background else "question",
                                    client.request("responses", {"model": "offline", "input": "x"}, timeout=20)["status"]))
            except server.APIError:
                pass
        with patch.object(server, "urlopen", provider.urlopen):
            workers = [threading.Thread(target=ask, args=(True,), daemon=True) for _ in range(3)]
            for worker in workers:
                worker.start()
            time.sleep(.4)
            # Three slots, one kept for background work (three less the reserve of two): two of
            # the three background requests wait, and the slots they may not take are free.
            self.assertEqual(free(client._provider_slots, 3), 2)
            question = threading.Thread(target=ask, args=(False,), daemon=True)
            question.start()
            time.sleep(.3)
            self.assertEqual(free(client._provider_slots, 3), 1, "The question took a slot while background work was queued")
            provider.release.set()
            question.join(5)
            for worker in workers:
                worker.join(5)
            stop.set()
        self.assertIn(("question", "completed"), answers)
        self.assertEqual(len(answers), 4)


if __name__ == "__main__":
    unittest.main()
