"""Offline HTTP-disconnect and payload-free lifecycle diagnostic regressions."""
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from test_server import server, interview_payload


class ResponseDisconnectTests(unittest.TestCase):
    def rejected_handler(self, headers=None, origin=False):
        handler = object.__new__(server.Handler)
        handler.server = Mock(csrf_token="current-token", body_timeout=30)
        handler.headers = headers or {}
        handler._same_origin = Mock(return_value=origin)
        handler._read_body = Mock(return_value=b"unauthorized content")
        handler._json = Mock(return_value=True)
        return handler

    def test_rejected_post_discards_only_bounded_bytes_without_routing(self):
        for origin, token in ((False, "current-token"), (True, "wrong-token")):
            with self.subTest(origin=origin, token=token):
                handler = self.rejected_handler({"Content-Length": "42", "X-CSRF-Token": token}, origin)
                handler.path = "/api/shutdown"
                handler.do_POST()
                handler._read_body.assert_called_once_with(42, 1.0)
                self.assertEqual(handler._json.call_args.args[1], 403)
                self.assertTrue(handler.close_connection)
                handler.server.shutdown.assert_not_called()

    def test_rejected_post_never_reads_chunked_oversized_or_invalid_lengths(self):
        for headers in ({}, {"Content-Length": "invalid"}, {"Content-Length": "-1"},
                        {"Content-Length": "0"}, {"Content-Length": str(server.MAX_JSON + 1)},
                        {"Content-Length": "42", "Transfer-Encoding": "chunked"}):
            with self.subTest(headers=headers):
                handler = self.rejected_handler(headers)
                handler.do_POST()
                handler._read_body.assert_not_called()
                self.assertEqual(handler._json.call_args.args[1], 403)
                self.assertTrue(handler.close_connection)

    def test_rejected_post_keeps_denial_after_incomplete_or_disconnected_body(self):
        for error in (TimeoutError, ConnectionAbortedError, ValueError):
            with self.subTest(error=error.__name__):
                handler = self.rejected_handler({"Content-Length": "42"})
                handler.server.body_timeout = .05
                handler._read_body.side_effect = error("private-request-detail")
                handler.do_POST()
                handler._read_body.assert_called_once_with(42, .05)
                self.assertEqual(handler._json.call_args.args[1], 403)
                self.assertNotIn("private-request-detail", json.dumps(handler._json.call_args.args))

    def test_disconnected_headers_or_body_do_not_trigger_a_second_response(self):
        for error_type in (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError):
            for stage in ("headers", "body"):
                with self.subTest(error=error_type.__name__, stage=stage):
                    handler = object.__new__(server.Handler)
                    handler.server = Mock()
                    handler._headers = Mock()
                    handler.wfile = Mock()
                    if stage == "headers":
                        handler._headers.side_effect = error_type("private-error-text")
                    else:
                        handler.wfile.write.side_effect = error_type("private-error-text")
                    self.assertFalse(handler._json({"result": "private-payload"}))
                    handler._headers.assert_called_once()
                    self.assertLessEqual(handler.wfile.write.call_count, 1)
                    self.assertTrue(handler.close_connection)
                    handler.server.record_event.assert_called_once_with(
                        "client_disconnected", status=200, error_type=error_type.__name__)


class HTTPDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-disconnect-")
        self.addCleanup(self.temporary.cleanup)
        self.client = server.OpenAIClient({})
        self.client.workflow = Mock(return_value={"workflow": {"steps": [{"id": "S1"}]}})
        self.response_statuses = []
        statuses = self.response_statuses

        class AbortedWriter:
            def __init__(self, original):
                self.original = original

            def write(self, _):
                raise ConnectionAbortedError("private-disconnect-detail")

            def __getattr__(self, name):
                return getattr(self.original, name)

        class AbortOneResponse(server.Handler):
            def _headers(self, status, mime, size, **options):
                statuses.append(status)
                return super()._headers(status, mime, size, **options)

            def _write_response(self, raw, mime, status=200, **options):
                if self.path == "/api/workflow" and not self.server.aborted_once:
                    self.server.aborted_once = True
                    self.wfile = AbortedWriter(self.wfile)
                return super()._write_response(raw, mime, status, **options)

        self.httpd = server.InterviewServer(("127.0.0.1", 0), AbortOneResponse, client=self.client,
                                            documents_root=Path(self.temporary.name) / "documents", knowledge_settings={})
        self.httpd.aborted_once = False
        self.worker = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.close_server)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def close_server(self):
        self.httpd.shutdown()
        self.worker.join(timeout=3)
        self.httpd.server_close()

    def request(self, path, payload=None):
        headers = {}
        if payload is not None:
            headers = {"Content-Type": "application/json", "X-CSRF-Token": self.httpd.csrf_token}
        request = urllib.request.Request(self.url + path,
                                         data=json.dumps(payload).encode() if payload is not None else None,
                                         headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def events(self):
        return [json.loads(line) for line in self.httpd.diagnostics_path.read_text().splitlines()]

    def test_listen_queue_covers_the_configured_connection_capacity(self):
        self.assertGreaterEqual(self.httpd.request_queue_size, self.httpd.max_connections)

    def test_aborted_response_leaves_server_and_next_workflow_healthy(self):
        payload = interview_payload()
        payload["turns"][1]["text"] = "PRIVATE_TRANSCRIPT_SENTINEL"
        raw = json.dumps(payload).encode()
        with socket.create_connection(self.httpd.server_address, timeout=3) as connection:
            connection.sendall((f"POST /api/workflow HTTP/1.1\r\nHost: 127.0.0.1:{self.httpd.server_port}\r\n"
                                f"X-CSRF-Token: {self.httpd.csrf_token}\r\nContent-Type: application/json\r\n"
                                f"Content-Length: {len(raw)}\r\n\r\n").encode() + raw)
            self.assertEqual(connection.recv(1024), b"")
        self.assertEqual(self.request("/api/config")[0], 200)
        self.assertEqual(self.request("/api/workflow", payload)[0], 200)
        self.assertEqual(self.client.workflow.call_count, 2)
        self.assertNotIn(500, self.response_statuses)
        events = self.events()
        self.assertEqual(sum(item["event"] == "client_disconnected" for item in events), 1)
        finished = [item for item in events if item["event"] == "workflow_finished"]
        self.assertEqual(len(finished), 2)
        self.assertTrue(all(item["outcome"] == "success" and item["step_count"] == 1 for item in finished))
        logged = self.httpd.diagnostics_path.read_text()
        self.assertNotIn("PRIVATE_TRANSCRIPT_SENTINEL", logged)
        self.assertNotIn("private-disconnect-detail", logged)
        self.assertNotIn(self.httpd.csrf_token, logged)

    def test_live_notes_report_retryable_provider_overload_through_the_http_endpoint(self):
        self.client.key = 'synthetic-local-test-key'
        unavailable = urllib.error.HTTPError(
            'https://example.invalid', 503, 'Busy', {'Retry-After': '8'},
            io.BytesIO(b'{"error":{"code":"server_is_overloaded","type":"service_unavailable_error"}}'))
        payload = dict(interview_payload(), live_notes=True)
        with patch.object(server.openai_transport, 'urlopen', side_effect=unavailable):
            status, body = self.request('/api/agent-team/interview', payload)
        self.assertEqual(status, 502)
        self.assertEqual(body['code'], 'provider_unavailable')
        self.assertEqual(body['retry_after_seconds'], 8)

    def test_workflow_failure_diagnostics_record_class_not_exception_or_payload(self):
        self.httpd.aborted_once = True
        self.client.workflow.side_effect = server.APIError("PRIVATE_PROVIDER_ERROR_SENTINEL", 503)
        status, _ = self.request("/api/workflow", interview_payload())
        self.assertEqual(status, 503)
        failed = next(item for item in self.events() if item["event"] == "workflow_finished")
        self.assertEqual(failed["outcome"], "error")
        self.assertEqual(failed["error_type"], "APIError")
        self.assertGreaterEqual(failed["duration_ms"], 0)
        self.assertNotIn("PRIVATE_PROVIDER_ERROR_SENTINEL", self.httpd.diagnostics_path.read_text())

    def test_provider_diagnostics_use_this_servers_private_store_and_known_stage(self):
        self.client.key = 'PRIVATE_KEY_SENTINEL'
        body = {'text': {'format': {'name': 'working_process_map_audit'}}, 'input': 'PRIVATE_DOCUMENT_SENTINEL'}
        with patch.object(server.openai_transport, 'urlopen', side_effect=TimeoutError('PRIVATE_PROVIDER_SENTINEL')):
            with self.assertRaises(server.APIError):
                self.client.request('responses', body, timeout=240)
        event = next(item for item in self.events() if item['event'] == 'provider_request_finished')
        self.assertEqual(event['stage'], 'working_process_map_audit')
        self.assertEqual(event['timeout_seconds'], 240)
        self.assertEqual(event['status'], 504)
        self.assertEqual(event['error_category'], 'timeout')
        self.assertEqual(event['error_type'], 'TimeoutError')
        self.assertEqual(event['port'], self.httpd.server_port)
        self.assertGreaterEqual(event['duration_ms'], 0)
        self.assertNotIn('PRIVATE_', self.httpd.diagnostics_path.read_text())

    def test_explicit_shutdown_records_only_a_safe_reason(self):
        stopped = threading.Event()
        with patch.object(self.httpd, "shutdown", side_effect=stopped.set) as shutdown:
            status, result = self.request("/api/shutdown", {})
            self.assertEqual(status, 200)
            self.assertTrue(result["stopping"])
            self.assertTrue(stopped.wait(timeout=1))
            shutdown.assert_called_once()
        entry = next(item for item in self.events() if item["event"] == "shutdown_requested")
        self.assertEqual(entry["reason"], "local_shutdown_request")
        self.assertEqual(self.httpd.shutdown_reason, "local_shutdown_request")


class LifecycleDiagnosticTests(unittest.TestCase):
    def test_standalone_clients_do_not_write_to_the_live_workspace(self):
        client = server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-key'})
        with patch.object(server.openai_transport, 'urlopen', return_value=io.BytesIO(b'{}')), \
             patch.object(server, 'record_diagnostic') as diagnostics:
            self.assertEqual(client.request('responses', {}), {})
        diagnostics.assert_not_called()

    def test_arbitrary_response_format_names_are_never_logged_as_stages(self):
        events = Mock()
        client = server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-key'}, events)
        with patch.object(server.openai_transport, 'urlopen', return_value=io.BytesIO(b'{}')):
            client.request('responses', {'text': {'format': {'name': 'PRIVATE_DOCUMENT_SENTINEL'}}})
        self.assertEqual(events.call_args.kwargs['stage'], 'responses')
        self.assertNotIn('PRIVATE_', repr(events.call_args))

    def test_rotation_is_bounded_and_only_allowlisted_metadata_is_saved(self):
        with tempfile.TemporaryDirectory(prefix="collector-diagnostics-") as temporary:
            path = Path(temporary) / "work" / "server-lifecycle.jsonl"
            with patch.object(server, "DIAGNOSTIC_MAX_BYTES", 500):
                for _ in range(20):
                    server.record_diagnostic(path, "workflow_finished", duration_ms=20, step_count=4,
                                             error_type="APIError", reason="private reason with spaces",
                                             payload="PRIVATE_PAYLOAD_SENTINEL")
            previous = path.with_name("server-lifecycle.previous.jsonl")
            self.assertTrue(previous.is_file())
            for file in (path, previous):
                self.assertLessEqual(file.stat().st_size, 500)
                for line in file.read_text().splitlines():
                    record = json.loads(line)
                    self.assertEqual(record["step_count"], 4)
                    self.assertNotIn("payload", record)
                    self.assertNotIn("reason", record)
                self.assertNotIn("PRIVATE_PAYLOAD_SENTINEL", file.read_text())

    def test_diagnostic_write_failure_does_not_raise_into_app(self):
        with tempfile.TemporaryDirectory(prefix="collector-diagnostics-unavailable-") as temporary:
            path = Path(temporary) / "server-lifecycle.jsonl"
            with patch.object(Path, "open", side_effect=PermissionError("unavailable")):
                server.record_diagnostic(path, "start", parent_pid=1)

    def test_main_records_start_and_distinct_exit_reasons_without_error_text(self):
        for failure, reason in ((None, "serve_forever_returned"),
                                (KeyboardInterrupt(), "keyboard_interrupt"),
                                (RuntimeError("PRIVATE_MAIN_ERROR_SENTINEL"), "main_exception")):
            with self.subTest(reason=reason):
                fake = Mock(server_port=8774, build_id="synthetic-build")
                del fake.shutdown_reason
                fake.serve_forever.side_effect = failure
                with patch.object(server, "InterviewServer", return_value=fake), \
                     patch.object(sys, "argv", ["server.py"]), patch("sys.stdout", new=io.StringIO()):
                    if isinstance(failure, RuntimeError):
                        with self.assertRaises(RuntimeError):
                            server.main()
                    else:
                        server.main()
                fake.server_close.assert_called_once()
                events = fake.record_event.call_args_list
                self.assertEqual(events[0].args, ("start",))
                self.assertEqual(events[-1].args, ("exit",))
                self.assertEqual(events[-1].kwargs["reason"], reason)
                self.assertNotIn("PRIVATE_MAIN_ERROR_SENTINEL", repr(events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
