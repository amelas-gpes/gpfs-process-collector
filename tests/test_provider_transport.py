"""The application exchanges provider responses through an injected transport."""
import importlib.util
import io
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from test_server import server


class ProviderTransportTests(unittest.TestCase):
    def test_proxy_configuration_is_loaded_on_first_exchange(self):
        spec = importlib.util.spec_from_file_location("isolated_transport", server.openai_transport.__file__)
        adapter = importlib.util.module_from_spec(spec)
        with patch("urllib.request.build_opener") as build:
            spec.loader.exec_module(adapter)
            build.assert_not_called()
            for _ in range(2):
                build.return_value.open.return_value = io.BytesIO(b"reply")
                with adapter.exchange("responses", b"{}", key="fixture", content_type="application/json",
                                      timeout=1, check_active=lambda: None, should_abort=None) as response:
                    self.assertEqual(response.read(), b"reply")
            build.assert_called_once()

    def test_request_uses_configured_transport_and_closes_response(self):
        response = io.BytesIO(b'{"status":"completed"}')
        sent = []

        @contextmanager
        def exchange(path, data, *, key, content_type, timeout, check_active, should_abort):
            sent.append((path, data, key, content_type, timeout))
            check_active()
            with response:
                yield response

        client = server.OpenAIClient({"OPENAI_API_KEY": "offline-fixture"}, transport=exchange)
        self.assertEqual(client.request("responses", {}, timeout=10), {"status": "completed"})
        self.assertTrue(response.closed)
        path, data, key, content_type, timeout = sent.pop()
        self.assertEqual((path, data, key, content_type), ("responses", b"{}", "offline-fixture", "application/json"))
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 10)

    def test_missing_key_is_rejected_before_transport(self):
        exchange = Mock()
        client = server.OpenAIClient({}, transport=exchange)
        with self.assertRaises(server.APIError) as refused:
            client.request("responses", {})
        self.assertEqual(refused.exception.category, "configuration")
        exchange.assert_not_called()

    def test_refused_response_is_closed_after_the_error_is_read(self):
        body = io.BytesIO(b'{"error":{"code":"model_not_found"}}')
        refused = HTTPError("https://example.invalid", 404, "missing", {}, body)
        client = server.OpenAIClient({"OPENAI_API_KEY": "offline-fixture"}, transport=Mock(side_effect=refused))
        with self.assertRaises(server.APIError) as caught:
            client.request("responses", {})
        self.assertEqual(caught.exception.category, "model_access")
        self.assertTrue(body.closed)
