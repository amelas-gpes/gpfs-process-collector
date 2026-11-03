"""Local brand asset delivery and origin boundaries; no external service calls."""

from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from test_server import server


class GPFSAssetHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-gpfs-test-never-a-real-key"})
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

    def fetch(self, path, headers=None):
        try:
            with urlopen(Request(self.url + path, headers=headers or {}), timeout=3) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def test_local_assets_have_correct_content_types_and_exact_source_bytes(self):
        for path, mime in (("/gpfs-presence.js", "text/javascript"),
                           ("/gpfs-presence.css", "text/css"),
                           ("/assets/gpfs-symbol.svg", "image/svg+xml")):
            with self.subTest(path=path):
                status, headers, body = self.fetch(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), mime)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
                self.assertEqual(body, (server.WEB_DIR / path.lstrip("/")).read_bytes())
        self.client.request.assert_not_called()

    def test_symbol_only_svg_preserves_source_paths_and_verified_brand_palette(self):
        status, _, body = self.fetch("/assets/gpfs-symbol.svg")
        self.assertEqual(status, 200)
        svg = ET.fromstring(body)
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(svg.attrib["viewBox"], "0 0 42 46")
        original = ET.fromstring((server.WEB_DIR / "assets/gpfs-logo.svg").read_bytes())
        self.assertEqual(len(svg), 5, "Only the source symbol paths may be served for display")
        for displayed, source in zip(svg, list(original)[-5:]):
            self.assertEqual(displayed.tag, "{http://www.w3.org/2000/svg}path")
            self.assertEqual(displayed.attrib, source.attrib)
        text = body.decode().lower()
        self.assertIn("#c9753a", text)
        self.assertIn("#8b7d65", text)
        self.assertNotRegex(text, r"<!entity|<!doctype|<script|<foreignobject")
        for node in svg.iter():
            for name, value in node.attrib.items():
                self.assertFalse(name.lower().startswith("on"), "SVG event attributes are unnecessary")
                if name.rsplit("}", 1)[-1].lower() in {"href", "src"}:
                    self.assertTrue(value.startswith("#"), "Logo references must stay inside the local SVG")
                self.assertNotRegex(value, r"url\(\s*['\"]?(?:https?:|//)")

    def test_app_uses_same_origin_brand_assets_and_csp_blocks_external_images(self):
        status, headers, body = self.fetch("/")
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn('src="/assets/gpfs-symbol.svg"', html)
        # The header carries the official gpfs.com lockup; the live voice presence stays symbol-only.
        self.assertEqual(html.count("gpfs-logo.svg"), 1, "Only the header uses the full lettering lockup")
        self.assertRegex(html, r'<a class="brand"[^>]*><img class="brand-logo" src="/assets/gpfs-logo\.svg"')
        presence = re.search(r'<div class="gpfs-presence"[^>]*>(.*?)</div>', html)
        self.assertIsNotNone(presence)
        self.assertNotIn("gpfs-logo.svg", presence.group(1))
        self.assertIn('src="/gpfs-presence.js"', html)
        self.assertIn('href="/gpfs-presence.css"', html)
        self.assertNotRegex(html, r'(?:src|href)=["\']https?://(?:www\.)?gpfs\.com')
        img_policy = re.search(r"(?:^|;)\s*img-src\s+([^;]+)", headers["Content-Security-Policy"])
        self.assertIsNotNone(img_policy)
        self.assertEqual(set(img_policy.group(1).split()), {"'self'", "data:"})
        self.client.request.assert_not_called()

    def test_static_assets_keep_origin_checks_and_explicit_allowlist(self):
        for path in ("/gpfs-presence.js", "/gpfs-presence.css", "/assets/gpfs-symbol.svg"):
            for headers in ({"Origin": "https://attacker.example"}, {"Sec-Fetch-Site": "cross-site"}):
                with self.subTest(path=path, headers=headers):
                    self.assertEqual(self.fetch(path, headers)[0], 403)
        for path in ("/assets/unknown.svg", "/assets/../server.py", "/assets/%2e%2e/server.py"):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path)[0], 404)
        self.client.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
