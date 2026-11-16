"""Offline checks of the settings reader, including active and historical files."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server


class LogViewerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def store(self, mode="content"):
        store = server.raw_trace.TraceStore(self.root, {"RAW_TRACE_MODE": mode})
        self.addCleanup(store.close)
        return store

    def test_newest_first_current_run_and_off_mode_history(self):
        old = self.store()
        old.emit("test.old", {"text": "Earlier interview"})
        old.close()
        current = self.store()
        for i in range(4):
            current.emit("test.current", {"text": f"Answer {i}"})
        current.close()
        rows = current.recent_events()["events"]
        self.assertEqual([row["payload"]["text"] for row in rows], ["Answer 3", "Answer 2", "Answer 1", "Answer 0", "Earlier interview"])
        self.assertEqual(len(current.recent_events(current_run=True)["events"]), 4)
        self.assertEqual(len(current.recent_events(limit=2)["events"]), 2)
        self.assertTrue(current.recent_events(limit=2)["limited"])
        disabled = self.store("off")
        self.assertEqual(len(disabled.recent_events()["events"]), 5)
        self.assertEqual(disabled.recent_events(current_run=True)["events"], [])
        self.assertFalse(disabled.recent_events()["status"]["enabled"])

    def test_partial_malformed_oversized_rows_and_unrelated_files(self):
        store = self.store()
        store.emit("test.valid", {"text": "<script>window.injected=true</script>"})
        store.emit("test.large", {"text": "A" * 40000})
        store.close()
        path = next(store.directory.glob("*.jsonl"))
        original = path.read_bytes()
        with path.open("ab") as target:
            target.write(b'not-json\n[]\n{"partial":')
        (store.directory / "private.jsonl").write_text('{"type":"test.unrelated"}\n')
        data = store.recent_events()
        self.assertEqual(len(data["events"]), 2)
        self.assertTrue(data["events"][0]["viewer_truncated"])
        self.assertEqual(data["clipped"], 1)
        self.assertEqual(data["events"][1]["payload"]["text"], "<script>window.injected=true</script>")
        self.assertEqual(path.read_bytes(), original + b'not-json\n[]\n{"partial":')
        with patch.object(server.raw_trace, "_has_link", return_value=True):
            with self.assertRaises(OSError):
                store.recent_events()

    def test_reader_bounds_scan_of_large_active_file(self):
        store = self.store()
        store.emit("test.saved")
        store.close()
        path = next(store.directory.glob("*.jsonl"))
        row = path.read_bytes()
        with path.open("wb") as target:
            target.write(b"x" * (9 * 1024 * 1024) + b"\n" + row + b'{"unfinished":')
        data = store.recent_events()
        self.assertTrue(data["limited"])
        self.assertEqual([item["type"] for item in data["events"]], ["test.saved"])

    def test_http_requires_token_same_origin_and_valid_scope(self):
        httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=server.OpenAIClient({}),
            documents_root=self.root / "documents", knowledge_root=self.root / "knowledge",
            knowledge_settings={"RAW_TRACE_MODE": "content"})
        worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(worker.join)
        self.addCleanup(httpd.shutdown)
        base = f"http://127.0.0.1:{httpd.server_port}"

        def get(query="scope=all", token=None, origin=None):
            headers = {"X-CSRF-Token": token} if token else {}
            if origin:
                headers["Origin"] = origin
            try:
                with urlopen(Request(base + "/api/trace/logs?" + query, headers=headers), timeout=4) as response:
                    return response.status, json.load(response)
            except HTTPError as error:
                return error.code, json.load(error)

        self.assertEqual(get()[0], 403)
        self.assertEqual(get(token="invalid")[0], 403)
        self.assertEqual(get(token=httpd.csrf_token, origin="https://example.com")[0], 403)
        self.assertEqual(get("scope=../../.env.local", httpd.csrf_token)[0], 400)
        httpd.trace.emit("test.reader", {"text": "Settings can read this"})
        httpd.trace.close()
        before = [path.read_bytes() for path in httpd.trace.directory.glob("*.jsonl")]
        code, data = get(token=httpd.csrf_token)
        self.assertEqual(code, 200)
        self.assertTrue(any(row["type"] == "test.reader" for row in data["events"]))
        self.assertEqual(get("scope=current", httpd.csrf_token)[0], 200)
        self.assertEqual(before, [path.read_bytes() for path in httpd.trace.directory.glob("*.jsonl")])
        with urlopen(base + "/log-viewer.js", timeout=4) as response:
            self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
