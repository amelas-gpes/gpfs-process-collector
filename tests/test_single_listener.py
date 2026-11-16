"""One port, one server.

On Windows SO_REUSEADDR lets a second listener bind an address that is already being served, so
two instances with different CSRF tokens could share a port and "Port N is busy" never fired.
The launcher must also tell "nothing is listening" from "something is listening but busy or
slow", or it starts a second server. Loopback sockets only; no provider, no browser.
"""

import contextlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch


APP = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server = load_module("single_listener_server", "server.py")
launcher = load_module("single_listener_launcher", "launcher.py")
REAL_SERVER = server.InterviewServer


class OfflineClient:
    def public_config(self):
        return {"api_configured": False}

    def browser_connect_sources(self):
        return ()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-single-listener-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.count = 0

    def start(self, port=0, serve=True):
        self.count += 1
        httpd = REAL_SERVER(("127.0.0.1", port), server.Handler, client=OfflineClient(),
                            documents_root=self.root / f"documents-{self.count}", knowledge_settings={})
        # Cleanups run last-in first-out: stop serving, wait for the loop, then close.
        self.addCleanup(httpd.server_close)
        if serve:
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 5)
            self.addCleanup(httpd.shutdown)
        return httpd

    def config(self, port):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/api/config")
            return json.loads(connection.getresponse().read())
        finally:
            connection.close()


class ExclusiveBind(Fixture):
    def test_a_second_server_cannot_bind_the_port_of_a_running_one(self):
        first = self.start()
        port = first.server_port
        with self.assertRaises(server.PortUnavailable) as refused:
            self.start(port, serve=False)
        self.assertIsInstance(refused.exception, OSError)
        # The first instance is untouched and still the one that answers.
        for _ in range(5):
            self.assertEqual(self.config(port)["csrf_token"], first.csrf_token)

    def test_a_port_held_by_another_program_is_refused_the_same_way(self):
        with socket.socket() as other:
            other.bind(("127.0.0.1", 0))
            other.listen(1)
            with self.assertRaises(server.PortUnavailable):
                self.start(other.getsockname()[1], serve=False)

    @unittest.skipUnless(os.name == "nt", "SO_REUSEADDR shares a listening port only on Windows")
    def test_windows_binds_exclusively_instead_of_reusing_the_address(self):
        self.assertFalse(server.InterviewServer.allow_reuse_address)
        first = self.start(serve=False)
        self.assertEqual(first.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)
        self.assertEqual(first.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 0)
        # A listener that asks for address reuse, as the old server did, is refused too.
        with socket.socket() as second:
            second.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                second.bind(("127.0.0.1", first.server_port))

    @unittest.skipIf(os.name == "nt", "Other systems keep address reuse, which only skips the TIME_WAIT delay there")
    def test_other_systems_keep_address_reuse(self):
        self.assertTrue(server.InterviewServer.allow_reuse_address)

    def test_the_port_is_usable_again_once_the_first_server_has_closed(self):
        first = self.start()
        port = first.server_port
        self.config(port)
        first.shutdown()
        first.server_close()
        with patch.object(server, "InterviewServer", lambda address, handler: self.start(address[1])):
            second = server.start_server(port)
        self.assertEqual(self.config(port)["csrf_token"], second.csrf_token)
        self.assertNotEqual(second.csrf_token, first.csrf_token)


class BoundedBindRetry(unittest.TestCase):
    def test_a_briefly_refused_bind_is_retried_and_then_succeeds(self):
        made = MagicMock(side_effect=[server.PortUnavailable(10048, "in use"), server.PortUnavailable(10013, "denied"), "the server"])
        with patch.object(server, "InterviewServer", made), patch.object(server.time, "sleep") as pause:
            self.assertEqual(server.start_server(8799), "the server")
        self.assertEqual(made.call_count, 3)
        self.assertEqual(pause.call_count, 2)
        made.assert_called_with(("127.0.0.1", 8799), server.Handler)

    def test_the_retry_is_bounded_and_main_then_reports_the_busy_port(self):
        made = MagicMock(side_effect=server.PortUnavailable(10048, "in use"))
        with patch.object(server, "InterviewServer", made), patch.object(server.time, "sleep") as pause, \
                patch.object(sys, "argv", ["server.py", "--port", "8799"]):
            with self.assertRaises(SystemExit) as stopped:
                server.main()
        self.assertEqual(str(stopped.exception), "Port 8799 is busy. Stop the existing prototype or choose another --port.")
        self.assertEqual(made.call_count, server.BIND_ATTEMPTS)
        self.assertLessEqual(made.call_count, 8)
        self.assertEqual(pause.call_count, server.BIND_ATTEMPTS - 1)
        self.assertLessEqual(sum(call.args[0] for call in pause.call_args_list), 3)

    def test_only_a_refused_bind_is_retried(self):
        for failure in (ValueError("settings"), PermissionError("work folder"), RuntimeError("store")):
            made = MagicMock(side_effect=failure)
            with patch.object(server, "InterviewServer", made), patch.object(server.time, "sleep") as pause:
                with self.assertRaises(type(failure)):
                    server.start_server(8799)
            self.assertEqual(made.call_count, 1)
            pause.assert_not_called()


class Silent(threading.Thread):
    """A listener that accepts connections and answers each with fixed bytes (or not at all)."""

    def __init__(self, reply=None):
        super().__init__(daemon=True)
        self.reply, self.listener, self.held = reply, socket.socket(), []
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.start()

    def run(self):
        while True:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                return
            self.held.append(connection)
            if self.reply is not None:
                try:
                    connection.settimeout(2)
                    connection.recv(65536)
                    connection.sendall(self.reply)
                    connection.close()
                except OSError:
                    pass

    def close(self):
        self.listener.close()
        for connection in self.held:
            connection.close()


def http_reply(status, body):
    raw = json.dumps(body).encode()
    return (f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
            "Connection: close\r\n\r\n").encode() + raw


class LauncherProbe(Fixture):
    def free_port(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def test_nothing_listening_reads_as_not_running(self):
        self.assertIsNone(launcher.config(f"http://127.0.0.1:{self.free_port()}/"))

    def test_this_app_answers_with_its_configuration(self):
        httpd = self.start()
        result = launcher.config(f"http://127.0.0.1:{httpd.server_port}/")
        self.assertEqual((result["app_id"], result["csrf_token"]), ("voice-interviewer", httpd.csrf_token))

    def test_a_listener_that_is_busy_slow_or_someone_else_is_not_mistaken_for_a_free_port(self):
        busy = http_reply(503, {"error": "The local server is busy. Retry shortly."})
        other = http_reply(200, {"app_id": "another-program"})
        for name, reply in (("slow", None), ("busy", busy), ("another program", other), ("not http", b"\x00\x01garbage\r\n\r\n"),
                            ("not an object", http_reply(200, ["voice-interviewer"]))):
            with self.subTest(listener=name):
                listener = Silent(reply)
                self.addCleanup(listener.close)
                self.assertIs(launcher.config(f"http://127.0.0.1:{listener.port}/", timeout=0.3), launcher.OCCUPIED)

    def launch(self, answers, *arguments):
        """Run launcher.main() with config() answering in turn; return (exit, spawn mock, sleeps)."""
        answers = list(answers)
        probe = MagicMock(side_effect=lambda url, **_: answers.pop(0) if len(answers) > 1 else answers[0])
        with patch.object(sys, "argv", ["launcher.py", "--no-browser", "--port", "8799", *arguments]), \
                patch.object(launcher, "config", probe), patch.object(launcher, "WORK_DIR", self.root / "work"), \
                patch.object(launcher.subprocess, "Popen") as spawn, patch.object(launcher.subprocess, "call") as run, \
                patch.object(launcher, "build_opener") as network, patch.object(launcher.time, "sleep") as pause, \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                launcher.main()
                stopped = None
            except SystemExit as error:
                stopped = str(error)
        self.assertFalse(run.called and spawn.called)
        return stopped, spawn, run, network, pause

    def test_a_port_that_stays_occupied_never_gets_a_second_server(self):
        for arguments in ((), ("--foreground",)):
            with self.subTest(arguments=arguments):
                stopped, spawn, run, network, pause = self.launch([launcher.OCCUPIED], *arguments)
                self.assertIn("Port 8799 is in use", stopped)
                self.assertIn("did not answer as AI Process Collector", stopped)
                self.assertNotIn("Could not start", stopped)
                spawn.assert_not_called()
                run.assert_not_called()
                network.assert_not_called()
                self.assertGreaterEqual(pause.call_count, 3)
                self.assertLessEqual(pause.call_count, 60)

    def test_a_busy_instance_that_then_answers_is_reused(self):
        build = launcher._build_module.build_id(launcher.APP_DIR)
        answer = {"app_id": "voice-interviewer", "build_id": build, "csrf_token": "synthetic"}
        stopped, spawn, run, _, _ = self.launch([launcher.OCCUPIED, launcher.OCCUPIED, answer])
        self.assertIsNone(stopped)
        spawn.assert_not_called()
        run.assert_not_called()

    def test_a_listener_that_goes_away_while_probing_lets_the_app_start(self):
        build = launcher._build_module.build_id(launcher.APP_DIR)
        answer = {"app_id": "voice-interviewer", "build_id": build, "csrf_token": "synthetic"}
        stopped, spawn, _, _, _ = self.launch([launcher.OCCUPIED, None, answer])
        self.assertIsNone(stopped)
        spawn.assert_called_once()

    def test_stop_does_not_claim_nothing_is_running_on_an_occupied_port(self):
        stopped, spawn, _, network, _ = self.launch([launcher.OCCUPIED], "--stop")
        self.assertIn("Port 8799 is in use", stopped)
        spawn.assert_not_called()
        network.assert_not_called()

    def test_a_child_that_never_answers_is_stopped_without_blaming_the_port(self):
        child = MagicMock()
        child.poll.return_value = None
        with patch.object(sys, "argv", ["launcher.py", "--no-browser", "--port", "8799"]), \
                patch.object(launcher, "config", side_effect=[None] + [launcher.OCCUPIED] * 300), \
                patch.object(launcher, "WORK_DIR", self.root / "work"), \
                patch.object(launcher.subprocess, "Popen", return_value=child), patch.object(launcher.time, "sleep"):
            with self.assertRaises(SystemExit) as stopped:
                launcher.main()
        self.assertIn("Could not start", str(stopped.exception))
        # Why it did not start is in the log; the launcher does not guess that the port was busy.
        self.assertNotIn("busy", str(stopped.exception))
        self.assertIn("voice-interviewer-server.log", str(stopped.exception))
        child.terminate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
