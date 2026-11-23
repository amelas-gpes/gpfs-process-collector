"""The provider key is never shown or logged, and a library's own error text never reaches a response.

Offline. The provider is a loopback stand-in or a replaced server.openai_transport.urlopen; every key is synthetic.
"""

import ast
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, Mock, patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provider_key_boundary_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

# Two recognisable halves, so that a fragment of a malformed key is noticed too.
HEAD, TAIL = "sk-synthetic-HEADHALF-", "TAILHALF-never-a-real-key-0000"
KEY = HEAD + TAIL
SURROUNDED = (KEY + "\r\n", KEY + "\n", KEY + " ", "\t" + KEY, " \r\n" + KEY + "\r\n\r\n")
MALFORMED = (HEAD + "\r" + TAIL, HEAD + "\n" + TAIL + "\r\n", HEAD + " " + TAIL, HEAD + "\t" + TAIL,
             KEY + "\u200b", HEAD + "\u00e9" + TAIL, HEAD + "\x00" + TAIL, HEAD + "\x7f" + TAIL)
LIBRARY_TEXT = "PRIVATE_LIBRARY_TEXT"
# No system proxy may sit between a test and a loopback server.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def interview_payload():
    return {"context": {"process_name": "Invoice approval", "process_owner": "AP team",
                        "objective": "Capture the current process", "background": "Synthetic test fixture"},
            "turns": [{"id": "a1", "role": "assistant", "text": "What starts the process?"},
                      {"id": "u1", "role": "user", "text": "An AP clerk logs each invoice from the shared mailbox."}],
            "action": "answer"}


def leaks(text):
    return [part for part in (KEY, HEAD, TAIL) if part in text]


class StandInProvider:
    """A loopback server in the provider's place. It records each request it actually receives."""

    def __init__(self):
        received = self.received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                received.append((self.path, self.headers.get("Authorization")))
                raw = json.dumps({"value": "ek-synthetic-short-lived", "expires_at": 1893456000}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.worker.start()

    def urlopen(self, request, timeout=None):
        # The unchanged Request (method, headers, body) through the real HTTP library; only the address differs.
        request.full_url = (f"http://127.0.0.1:{self.httpd.server_port}/v1/"
                            + request.full_url.split("/v1/", 1)[1])
        return DIRECT.open(request, timeout=timeout)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)


class RunningApp:
    """The real handler around a given client, on a loopback port, with throwaway stores."""

    def __init__(self, test, client):
        root = Path(test.enterContext(tempfile.TemporaryDirectory(prefix="collector-key-boundary-")))
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                                            documents_root=root / "documents", knowledge_settings={})
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.worker.start()
        test.addCleanup(self.close)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)

    def get(self, path):
        with DIRECT.open(self.url + path, timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def post(self, path, payload=None, raw=None, content_type="application/json"):
        data = raw if raw is not None else json.dumps(payload).encode()
        request = urllib.request.Request(self.url + path, data=data, method="POST", headers={
            "Content-Type": content_type, "X-CSRF-Token": self.httpd.csrf_token})
        try:
            with DIRECT.open(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def post_with_length(self, path, length):
        """A request whose Content-Length header is not a number, which no browser sends."""
        with socket.create_connection(self.httpd.server_address, timeout=5) as connection:
            connection.sendall((f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.httpd.server_port}\r\n"
                                f"X-CSRF-Token: {self.httpd.csrf_token}\r\nContent-Type: application/json\r\n"
                                f"Connection: close\r\nContent-Length: {length}\r\n\r\n").encode())
            reply = b""
            while chunk := connection.recv(65536):
                reply += chunk
        head, _, body = reply.partition(b"\r\n\r\n")
        return int(head.split()[1]), body.decode("utf-8")

    def log(self):
        path = self.httpd.diagnostics_path
        return path.read_text(encoding="utf-8") if path.is_file() else ""


class KeySettingTests(unittest.TestCase):
    def test_line_breaks_and_spaces_around_the_key_are_removed_before_it_is_sent(self):
        for supplied in SURROUNDED:
            with self.subTest(supplied=repr(supplied)):
                client = server.OpenAIClient({"OPENAI_API_KEY": supplied})
                self.assertEqual(client.key, KEY)
                self.assertEqual(client.key_problem, "")
                config = client.public_config()
                self.assertTrue(config["api_configured"])
                self.assertNotIn("api_problem", config)
                sent = []

                def answer(request, timeout=None):
                    sent.append(request.get_header("Authorization"))
                    raise urllib.error.URLError(ConnectionRefusedError("synthetic"))

                with patch.object(server.openai_transport, "urlopen", side_effect=answer):
                    with self.assertRaises(server.APIError):
                        client.request("responses", {"model": "synthetic"})
                self.assertEqual(sent, ["Bearer " + KEY])

    def test_a_key_that_cannot_be_an_http_header_is_not_kept_sent_or_shown(self):
        for supplied in MALFORMED:
            with self.subTest(supplied=repr(supplied)):
                diagnostics = Mock()
                client = server.OpenAIClient({"OPENAI_API_KEY": supplied}, diagnostics)
                self.assertEqual(client.key, "")
                self.assertEqual(client.key_problem, server.UNUSABLE_KEY_MESSAGE)
                config = client.public_config()
                self.assertFalse(config["api_configured"])
                self.assertFalse(config["speech"]["enabled"])
                self.assertFalse(config["live"]["enabled"])
                self.assertEqual(config["api_problem"], server.UNUSABLE_KEY_MESSAGE)
                self.assertEqual(leaks(json.dumps(config)), [])
                for path, body in (("responses", {"model": "synthetic"}), ("realtime/client_secrets", {}),
                                   ("live/sessions", {}), ("audio/transcriptions", b"audio")):
                    with patch.object(server.openai_transport, "urlopen") as network:
                        with self.assertRaises(server.APIError) as caught:
                            client.request(path, body)
                    network.assert_not_called()
                    self.assertEqual(caught.exception.status, 503)
                    self.assertEqual(str(caught.exception), server.UNUSABLE_KEY_MESSAGE)
                self.assertEqual(leaks(repr(diagnostics.mock_calls)), [])

    def test_the_explanation_names_the_setting_and_never_a_value(self):
        self.assertIn("local API settings", server.UNUSABLE_KEY_MESSAGE)
        self.assertEqual(leaks(server.UNUSABLE_KEY_MESSAGE), [])

    def test_a_missing_key_keeps_its_own_explanation(self):
        for settings in ({}, {"OPENAI_API_KEY": ""}, {"OPENAI_API_KEY": " \r\n"}, {"OPENAI_API_KEY": None}):
            with self.subTest(settings=settings):
                client = server.OpenAIClient(settings)
                self.assertEqual((client.key, client.key_problem), ("", ""))
                self.assertNotIn("api_problem", client.public_config())
                with patch.object(server.openai_transport, "urlopen") as network:
                    with self.assertRaises(server.APIError) as caught:
                        client.request("responses", {})
                network.assert_not_called()
                self.assertEqual(caught.exception.status, 503)
                self.assertIn("no API key configured", str(caught.exception))


class TransportTextTests(unittest.TestCase):
    def test_a_library_failure_while_sending_or_reading_becomes_fixed_text(self):
        failures = (
            ValueError("Invalid header value b'Bearer " + LIBRARY_TEXT + "\\r\\n'"),
            UnicodeEncodeError("latin-1", LIBRARY_TEXT + "\u200b", len(LIBRARY_TEXT), len(LIBRARY_TEXT) + 1, LIBRARY_TEXT),
            http.client.InvalidURL("URL can't contain control characters. " + LIBRARY_TEXT),
            http.client.IncompleteRead(LIBRARY_TEXT.encode()),
            http.client.BadStatusLine(LIBRARY_TEXT),
            http.client.LineTooLong(LIBRARY_TEXT),
        )
        for failure in failures:
            for streamed in (False, True):
                with self.subTest(failure=type(failure).__name__, streamed=streamed):
                    diagnostics = Mock()
                    client = server.OpenAIClient({"OPENAI_API_KEY": KEY}, diagnostics)
                    with patch.object(server.openai_transport, "urlopen", side_effect=failure) as network:
                        with self.assertRaises(server.APIError) as caught:
                            client.request("responses", {"model": "synthetic"},
                                           **({"on_text": lambda text: False} if streamed else {}))
                    network.assert_called_once()
                    self.assertEqual(caught.exception.status, 502)
                    expected = ("connection" if isinstance(failure, http.client.IncompleteRead) else
                                "invalid_response" if isinstance(failure, (http.client.BadStatusLine, http.client.LineTooLong)) else "protocol")
                    self.assertTrue(str(caught.exception))
                    self.assertNotIn(LIBRARY_TEXT, str(caught.exception))
                    self.assertEqual(leaks(str(caught.exception)), [])
                    fields = diagnostics.call_args.kwargs
                    self.assertEqual(fields["outcome"], "error")
                    self.assertEqual(fields["error_category"], expected)
                    self.assertEqual(fields["error_type"], type(failure).__name__)
                    self.assertNotIn(LIBRARY_TEXT, repr(diagnostics.call_args))
                    self.assertEqual(leaks(repr(diagnostics.call_args)), [])

    def test_a_truncated_reply_is_reported_with_fixed_text(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.side_effect = http.client.IncompleteRead(LIBRARY_TEXT.encode())
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        with patch.object(server.openai_transport, "urlopen", return_value=response):
            with self.assertRaises(server.APIError) as caught:
                client.request("responses", {"model": "synthetic"})
        self.assertNotIn(LIBRARY_TEXT, str(caught.exception))

    def test_a_failure_while_building_the_request_is_covered_too(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        with patch.object(server.openai_transport, "Request", side_effect=ValueError(LIBRARY_TEXT)), \
             patch.object(server.openai_transport, "urlopen") as network:
            with self.assertRaises(server.APIError) as caught:
                client.request("responses", {"model": "synthetic"})
        network.assert_not_called()
        self.assertNotIn(LIBRARY_TEXT, str(caught.exception))

    def test_a_header_refused_by_the_http_library_is_never_quoted(self):
        # Should a value the HTTP library refuses ever reach the header again, the
        # library's message (which prints the whole header) must still not travel.
        provider = StandInProvider()
        self.addCleanup(provider.close)
        diagnostics = Mock()
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY}, diagnostics)
        for forced in (KEY + "\r\n", HEAD + "\n" + TAIL, KEY + "\u200b"):
            with self.subTest(forced=repr(forced)):
                client.key = forced
                with patch.object(server.openai_transport, "urlopen", side_effect=provider.urlopen):
                    with self.assertRaises(server.APIError) as caught:
                        client.request("realtime/client_secrets", {})
                self.assertEqual(leaks(str(caught.exception)), [])
                self.assertNotIn("header", str(caught.exception).lower())
                self.assertEqual(leaks(repr(diagnostics.call_args)), [])
        self.assertEqual(provider.received, [])


class BrowserNeverSeesTheKeyTests(unittest.TestCase):
    def test_a_key_followed_by_a_line_break_works_and_is_not_echoed(self):
        provider = StandInProvider()
        self.addCleanup(provider.close)
        for supplied in (KEY + "\r\n", KEY + "\n"):
            with self.subTest(supplied=repr(supplied)):
                provider.received.clear()
                app = RunningApp(self, server.OpenAIClient({"OPENAI_API_KEY": supplied}))
                with patch.object(server.openai_transport, "urlopen", side_effect=provider.urlopen):
                    status, body = app.post("/api/voice-session", {"voice": "marin"})
                self.assertEqual(leaks(body), [])
                self.assertEqual(status, 200, body)
                self.assertEqual(json.loads(body)["client_secret"], "ek-synthetic-short-lived")
                self.assertEqual(provider.received, [("/v1/realtime/client_secrets", "Bearer " + KEY)])
                self.assertEqual(leaks(app.get("/api/config")[1]), [])
                self.assertEqual(leaks(app.log()), [])

    def test_an_unusable_key_is_explained_on_every_provider_bound_route_without_being_shown(self):
        provider = StandInProvider()
        self.addCleanup(provider.close)
        audio = {"raw": b"x" * 400, "content_type": "audio/webm;codecs=opus"}
        live = {**interview_payload(), "turns": [], "voice": "marin",
                "sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"}
        for supplied in (HEAD + "\r" + TAIL + "\r\n", HEAD + " " + TAIL, KEY + "\u200b"):
            with self.subTest(supplied=repr(supplied)):
                app = RunningApp(self, server.OpenAIClient({"OPENAI_API_KEY": supplied}))
                with patch.object(server.openai_transport, "urlopen", side_effect=provider.urlopen):
                    replies = {
                        "/api/voice-session": app.post("/api/voice-session", {"voice": "marin"}),
                        "/api/transcribe": app.post("/api/transcribe", **audio),
                        "/api/draft": app.post("/api/draft", interview_payload()),
                        "/api/workflow": app.post("/api/workflow", interview_payload()),
                        "/api/live-session": app.post("/api/live-session", live),
                        "/api/interview": app.post("/api/interview", interview_payload()),
                        "/api/conversation/turn": app.post("/api/conversation/turn", interview_payload()),
                    }
                for path, (status, body) in replies.items():
                    with self.subTest(path=path):
                        self.assertEqual(leaks(body), [])
                        self.assertNotIn("header", body.lower())
                        self.assertNotIn("codec", body.lower())
                for path in ("/api/voice-session", "/api/transcribe", "/api/draft", "/api/workflow", "/api/live-session"):
                    with self.subTest(path=path):
                        status, body = replies[path]
                        self.assertEqual(status, 503, body)
                        self.assertEqual(json.loads(body)["error"], server.UNUSABLE_KEY_MESSAGE)
                config = json.loads(app.get("/api/config")[1])
                self.assertFalse(config["api_configured"])
                self.assertEqual(config["api_problem"], server.UNUSABLE_KEY_MESSAGE)
                self.assertEqual(leaks(json.dumps(config)), [])
                self.assertEqual(leaks(app.log()), [])
        self.assertEqual(provider.received, [])


class StartupTraceTests(unittest.TestCase):
    """main() around a real server whose serving loop returns at once; no fixed port is bound."""

    def started(self, key):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="collector-key-start-")))
        real, built = server.InterviewServer, []

        def build(address, handler):
            # main() asks for its default port; the test binds a free one instead.
            built.append(real(("127.0.0.1", 0), handler, client=server.OpenAIClient({"OPENAI_API_KEY": key}),
                              documents_root=root / "documents", knowledge_settings={}))
            return built[0]

        console = io.StringIO()
        with patch.object(server, "InterviewServer", side_effect=build), \
             patch.object(real, "serve_forever", return_value=None), \
             patch.object(sys, "argv", ["server.py"]), patch("sys.stdout", new=console):
            server.main()
        log = built[0].diagnostics_path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in log.splitlines()]
        return console.getvalue(), log, rows

    def test_a_discarded_key_is_named_on_the_console_and_in_the_start_row_without_being_shown(self):
        for supplied in MALFORMED:
            with self.subTest(supplied=repr(supplied)):
                console, log, rows = self.started(supplied)
                self.assertEqual([row["event"] for row in rows], ["start", "exit"])
                self.assertEqual(rows[0].get("reason"), "provider_key_unusable")
                self.assertEqual(console.splitlines()[2:], [server.UNUSABLE_KEY_MESSAGE])
                self.assertEqual(leaks(console + log), [])

    def test_a_usable_or_missing_key_adds_nothing_to_the_console_or_the_start_row(self):
        for supplied in (KEY, KEY + "\r\n", ""):
            with self.subTest(supplied=repr(supplied)):
                console, log, rows = self.started(supplied)
                self.assertEqual([row["event"] for row in rows], ["start", "exit"])
                self.assertNotIn("reason", rows[0])
                self.assertEqual(len(console.splitlines()), 2)
                self.assertNotIn(server.UNUSABLE_KEY_MESSAGE, console)
                self.assertEqual(leaks(console + log), [])

    def test_the_explanation_fits_the_length_the_page_accepts(self):
        # web/app.js refuses a longer api_problem and shows its generic sentence instead.
        page = (APP / "web" / "app.js").read_text(encoding="utf-8")
        accepted = re.search(r"config\.api_problem\.length\s*<=\s*(\d+)", page)
        self.assertIsNotNone(accepted, "The page no longer reads config.api_problem.")
        self.assertLessEqual(len(server.UNUSABLE_KEY_MESSAGE), int(accepted.group(1)))


class OwnWordingTests(unittest.TestCase):
    FIXED = "FIXED WORDING"

    def caught(self, action):
        try:
            action()
        except Exception as error:  # noqa: BLE001 - the test inspects exactly what was raised
            return error
        self.fail("The action was expected to raise.")

    def test_wording_from_an_application_raise_statement_is_kept(self):
        graph = server.local_module("knowledge_graph", "knowledge_graph.py")
        service = server.local_module("document_service", "document_service.py")
        for action, expected in (
                (lambda: server.bounded_text(5, "Label"), "Label must be text of at most 6000 characters."),
                (lambda: server.validate_payload([]), "A JSON object is required."),
                (lambda: server.agent_team._text(5, "Summary"), "Summary must be bounded text."),
                (lambda: graph.named_text(5, 100, "Participant"), "Participant must be text."),
                # One line that replaces a library error by the application's own sentence.
                (lambda: server.bounded_text("\ud800", "Turn"), "Turn contains an incomplete Unicode character. Edit that text and try again."),
                (lambda: service._text(5, "summary", 10), "Document review returned invalid summary.")):
            with self.subTest(expected=expected):
                error = self.caught(action)
                self.assertIsInstance(error, ValueError)
                self.assertEqual(server.own_wording(error, self.FIXED), expected)

    def test_wording_survives_a_journey_through_library_frames(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            error = self.caught(pool.submit(server.bounded_text, "", "Turn text", 10, True).result)
        self.assertEqual(server.own_wording(error, self.FIXED), "Turn text is required.")

    def test_text_composed_by_a_library_is_replaced(self):
        def refused_header():
            connection = http.client.HTTPConnection("127.0.0.1", 9)  # Nothing is opened: the check comes first.
            connection.putrequest("POST", "/")
            connection.putheader("Authorization", "Bearer " + LIBRARY_TEXT + "\r\n")

        def raised_outside_the_application():
            raise ValueError(LIBRARY_TEXT)

        specimens = {
            "http header check": refused_header,
            "number parser": lambda: int(LIBRARY_TEXT),
            "codec": lambda: (LIBRARY_TEXT + "\u200b").encode("latin-1"),
            "json": lambda: json.loads("{" + LIBRARY_TEXT),
            "path": lambda: Path("C:/" + LIBRARY_TEXT).relative_to("D:/elsewhere"),
            "test double": Mock(side_effect=ValueError(LIBRARY_TEXT)),
            "code outside the application": raised_outside_the_application,
        }
        for label, action in specimens.items():
            with self.subTest(source=label):
                error = self.caught(action)
                self.assertIsInstance(error, ValueError)
                self.assertEqual(server.own_wording(error, self.FIXED), self.FIXED)

    def test_an_error_that_was_never_raised_is_replaced(self):
        self.assertEqual(server.own_wording(ValueError(LIBRARY_TEXT), self.FIXED), self.FIXED)


class RaiseSiteRuleTests(unittest.TestCase):
    """own_wording trusts every raise statement in the application folder, so none may relay a caught error's text."""

    @staticmethod
    def relays(source):
        """Raise statements that build a new error from the error their handler caught."""
        found = []
        for handler in ast.walk(ast.parse(source)):
            if not isinstance(handler, ast.ExceptHandler) or not handler.name:
                continue
            for statement in ast.walk(handler):
                # "raise error" itself adds no raise site of ours to the error's origin.
                if not isinstance(statement, ast.Raise) or statement.exc is None or isinstance(statement.exc, ast.Name):
                    continue
                pending = [statement.exc]
                while pending:
                    node = pending.pop()
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "own_wording":
                        continue  # The one permitted way to carry wording over.
                    if isinstance(node, ast.Attribute) and node.attr == "status" and isinstance(node.value, ast.Name):
                        continue  # An APIError's HTTP status is a number, not wording.
                    if isinstance(node, ast.Name) and node.id == handler.name:
                        found.append(f"line {statement.lineno}: {ast.unparse(statement)}")
                        break
                    pending.extend(ast.iter_child_nodes(node))
        return found

    def test_the_check_recognises_each_way_of_relaying_a_caught_error(self):
        relayed = ("raise ValueError(str(error))", "raise ValueError(f'Could not read: {error}')",
                   "raise APIError('Failed: ' + repr(error), 502)", "raise ValueError(*error.args) from None",
                   "raise APIError('Failed: %s' % error)", "raise ValueError('{}'.format(error.reason))")
        allowed = ("raise", "raise error", "raise ValueError('Choose a valid record.') from error",
                   "raise APIError(own_wording(error, FIXED)) from None", "raise APIError('Failed.', error.status)",
                   "raise SystemExit(1)")
        for line in relayed:
            with self.subTest(relayed=line):
                self.assertEqual(len(self.relays(f"try:\n    work()\nexcept ValueError as error:\n    {line}\n")), 1)
        for line in allowed:
            with self.subTest(allowed=line):
                self.assertEqual(self.relays(f"try:\n    work()\nexcept ValueError as error:\n    {line}\n"), [])

    def test_no_application_module_relays_a_caught_errors_text(self):
        modules = sorted(server.APP_DIR.glob("*.py"))
        self.assertIn(server.APP_DIR / "server.py", modules)
        for module in modules:
            with self.subTest(module=module.name):
                self.assertEqual(self.relays(module.read_text(encoding="utf-8")), [],
                                 "Word the error yourself, or use own_wording(error, fixed_text).")


class ResponseWordingTests(unittest.TestCase):
    def setUp(self):
        self.client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        self.client.request = Mock(side_effect=AssertionError("Unexpected provider call"))
        self.app = RunningApp(self, self.client)

    def error(self, reply):
        status, body = reply
        self.assertNotIn(LIBRARY_TEXT, body)
        return status, json.loads(body)["error"]

    def test_application_validation_wording_still_reaches_the_person(self):
        expected = (
            (("/api/voice-session", {"voice": "not-a-voice"}), "That AI voice is not supported. Choose a voice from the list."),
            (("/api/draft", {**interview_payload(), "turns": []}), "Add at least one interview answer before generating a draft."),
            (("/api/interview", {**interview_payload(), "context": None}), "Interview context is required."),
            (("/api/conversation/status", [1]), "A conversation snapshot is required."),
            (("/api/agent-team/status", {"run_id": 7}), "Run identifier must be text of at most 80 characters."),
            (("/api/documents/context", [1]), "A document request object is required."),
            (("/api/documents/source", {"scope": "s", "id": ""}), "Document ID is required."),
            (("/api/knowledge/status", {"submission_id": "s", "revision": 0}), "Choose the submission revision."),
        )
        for (path, payload), message in expected:
            with self.subTest(path=path):
                self.assertEqual(self.error(self.app.post(path, payload)), (400, message))
        status, message = self.error(self.app.post("/api/transcribe", raw=b"x" * 400, content_type="text/html"))
        self.assertEqual((status, message), (400, "Unsupported recording format. Use an up-to-date Chrome or Edge browser."))
        self.client.request.assert_not_called()

    def test_a_library_error_inside_a_request_is_answered_with_fixed_text(self):
        for path, payload, method in (("/api/voice-session", {"voice": "marin"}, "voice_session"),
                                      ("/api/draft", interview_payload(), "draft"),
                                      ("/api/workflow", interview_payload(), "workflow")):
            with self.subTest(path=path):
                with patch.object(self.client, method, side_effect=ValueError(LIBRARY_TEXT)):
                    status, message = self.error(self.app.post(path, payload))
                self.assertEqual((status, message), (400, server.UNREADABLE_REQUEST_MESSAGE))

    def test_a_body_that_is_not_utf8_or_json_names_no_codec(self):
        status, message = self.error(self.app.post("/api/interview", raw=b"\xff\xfe{}"))
        self.assertEqual((status, message), (400, server.UNREADABLE_REQUEST_MESSAGE))
        status, message = self.error(self.app.post("/api/interview", raw=b"{broken-json"))
        self.assertEqual((status, message), (400, "Invalid JSON body."))
        for path in ("/api/knowledge/status", "/api/documents/context"):
            with self.subTest(path=path):
                status, message = self.error(self.app.post(path, raw=b"\xff\xfe{}"))
                self.assertEqual((status, message), (400, server.UNREADABLE_REQUEST_MESSAGE))

    def test_a_builtin_failing_inside_application_code_is_not_quoted(self):
        # int() fails inside the handler itself: the frame is ours, the wording is the interpreter's.
        for path in ("/api/interview", "/api/knowledge/status", "/api/documents/context"):
            with self.subTest(path=path):
                status, body = self.app.post_with_length(path, LIBRARY_TEXT)
                self.assertEqual(status, 400, body)
                self.assertNotIn(LIBRARY_TEXT, body)
                self.assertNotIn("invalid literal", body)
                self.assertEqual(json.loads(body)["error"], "Invalid Content-Length.")


class ModelResultWordingTests(unittest.TestCase):
    """interview(), workflow() and draft() turn a failed check of a model result into an APIError."""

    def client(self, *results):
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        client.structured = Mock(side_effect=list(results) or None, return_value={})
        return client

    def assert_fixed(self, action):
        with self.assertRaises(server.APIError) as caught:
            action()
        self.assertEqual(str(caught.exception), server.UNUSABLE_RESULT_MESSAGE)
        self.assertEqual(caught.exception.status, 502)

    def test_a_library_error_during_each_check_is_replaced(self):
        foreign = ValueError(LIBRARY_TEXT)
        payload = interview_payload()
        with patch.object(server, "check_schema", side_effect=foreign):
            self.assert_fixed(lambda: self.client().workflow(payload))
            self.assert_fixed(lambda: self.client().interview(payload))
            self.assert_fixed(lambda: self.client({"connections": []}).draft(payload))
        with patch.object(server, "check_schema", side_effect=[None, foreign]):
            self.assert_fixed(lambda: self.client({"connections": []}, {}).draft(payload))
        with patch.object(server, "check_schema"), \
             patch.object(server, "apply_workflow_update", return_value={"memo_findings": []}), \
             patch.object(server, "proposed_routes_to_verify", return_value=[{"from": "s1", "to": "s2"}]), \
             patch.object(server, "route_audit_schema", return_value={}), \
             patch.object(server, "apply_workflow_audit", side_effect=foreign):
            self.assert_fixed(lambda: self.client().workflow(payload))
        with patch.object(server, "check_schema"), \
             patch.object(server, "apply_workflow_update", return_value={"memo_findings": []}), \
             patch.object(server, "proposed_routes_to_verify", return_value=[]):
            client = self.client()
            client.apply_coverage_review = Mock(side_effect=foreign)
            self.assert_fixed(lambda: client.workflow(payload))

    def test_the_applications_own_finding_about_a_model_result_is_still_reported(self):
        with self.assertRaises(server.APIError) as caught:
            self.client({"connections": [{"unexpected": True}]}).draft(interview_payload())
        self.assertEqual(str(caught.exception), "candidate_draft.connections has missing or unexpected fields.")
        with self.assertRaises(server.APIError) as caught:
            self.client({"unexpected": True}).interview(interview_payload())
        self.assertEqual(str(caught.exception), "result has missing or unexpected fields.")


if __name__ == "__main__":
    unittest.main()
