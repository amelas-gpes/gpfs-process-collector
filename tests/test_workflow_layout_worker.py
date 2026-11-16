"""The workflow layout worker script is served locally under the page's script policy; no provider calls."""

from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from test_server import server


class WorkflowLayoutWorkerAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-layout-worker-test-never-a-real-key"})
        cls.client.request = Mock(side_effect=AssertionError("Static assets must never invoke a provider"))
        cls.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=cls.client,
                                          documents_root=Path(cls.directory.name) / "documents")
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=3)
        cls.directory.cleanup()

    def fetch(self, path):
        try:
            with urlopen(Request(self.url + path), timeout=3) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def test_worker_script_and_the_engine_it_imports_are_served_as_scripts(self):
        for path in ("/workflow-layout-worker.js", "/vendor/elk.bundled.js"):
            with self.subTest(path=path):
                status, headers, body = self.fetch(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/javascript")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(body, (server.WEB_DIR / path.lstrip("/")).read_bytes())
        self.client.request.assert_not_called()

    def test_worker_imports_only_the_local_engine(self):
        source = (server.WEB_DIR / "workflow-layout-worker.js").read_text(encoding="utf-8")
        self.assertEqual(source.count("importScripts("), 1)
        self.assertIn('importScripts("/vendor/elk.bundled.js")', source)
        self.assertNotIn("http", source)

    def test_page_policy_admits_a_same_origin_worker_and_nothing_wider(self):
        _, headers, _ = self.fetch("/")
        policy = {part.split()[0]: part.split()[1:] for part in headers["Content-Security-Policy"].split(";") if part.strip()}
        # Without worker-src or child-src a worker is governed by script-src.
        self.assertNotIn("worker-src", policy)
        self.assertNotIn("child-src", policy)
        self.assertEqual(policy["script-src"], ["'self'"])


if __name__ == "__main__":
    unittest.main()
