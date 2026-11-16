"""The browser endpoint receives observations, with the app's existing request protection."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

from test_server import server


class RawTraceHTTPTests(unittest.TestCase):
    def test_delivery_retries_permissions_and_transient_boundaries(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=server.OpenAIClient({}),
                documents_root=root / "documents", knowledge_settings={"RAW_TRACE_MODE":"content"})
            worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval":0.01}, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{httpd.server_port}"
            def post(path, data, protected=True):
                headers = {"Content-Type":"application/json"}
                if protected:
                    headers["X-CSRF-Token"] = httpd.csrf_token
                req = Request(base + path, data=json.dumps(data).encode(), headers=headers)
                try:
                    with urlopen(req, timeout=4) as response:
                        return response.status, json.load(response)
                except HTTPError as exc:
                    with exc:
                        return exc.code, json.load(exc)

            tab = str(uuid.uuid4())
            row = {"seq":2, "at":"2026-11-16T14:00:01.123Z", "type":"turn.created",
                   "payload":{"content":{"text":"First  line.\nSecond line."}}}
            route = "/api/trace/events"
            try:
                batch = {"producer_id":tab, "events":[row]}
                self.assertEqual(post(route, batch, protected=False)[0], 403)
                self.assertEqual(post(route, {**batch, "events":[row, {**row, "producer":"server"}]})[0], 400)
                for _ in range(2):
                    self.assertEqual(post(route, batch), (200, {"accepted":1, "received":1}))
                self.assertEqual(post("/api/recovery/setting", {"enabled":True})[0], 200)
                post("/api/recovery/save", {"id":"broken", "session":{"unsent_answer":"private-unsent-canary"}})
                with urlopen(base + "/api/config", timeout=4) as response:
                    config = json.load(response)
                self.assertTrue(config["raw_trace"]["content"])
                self.assertIn("Developer tracing is enabled", config["data_notice"])
            finally:
                httpd.shutdown()
                worker.join()
                httpd.server_close()
            raw = "".join(p.read_text("utf8") for p in (root / "raw-trace").glob("*.jsonl"))
            rows = [json.loads(line) for line in raw.splitlines()]
            observed = [r for r in rows if r["type"] == "browser.turn.created"]
            self.assertEqual(len(observed), 2)
            self.assertNotEqual(observed[0]["event_id"], observed[1]["event_id"])
            for item in observed:
                self.assertEqual((item["producer"], item["producer_id"], item["source_sequence"]), ("browser", tab, 2))
                self.assertEqual(item["payload"], row["payload"])
                self.assertEqual(item["observed_at"], row["at"])
            self.assertNotIn(httpd.csrf_token, raw)
            self.assertNotIn("private-unsent-canary", raw)
