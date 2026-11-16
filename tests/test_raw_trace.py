"""Synthetic observations only. No live provider, app stores or credentials."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / "raw_trace.py"
spec = importlib.util.spec_from_file_location("store_trace_under_test", PATH)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


class RawTraceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="collector-raw-trace-")))
        self.enterContext(patch.dict(os.environ, {"RAW_TRACE_MODE": ""}))

    def store(self, mode="content", **settings):
        store = trace.TraceStore(self.root, {"RAW_TRACE_MODE": mode, **settings})
        self.addCleanup(store.close)
        return store

    @staticmethod
    def read(store):
        store.close()
        return [json.loads(row) for path in sorted(store.directory.glob(f"*{store.run_id}*.jsonl"))
                for row in path.read_bytes().splitlines()]

    def test_preserves_exact_strings_structure_empty_and_duplicate_observations(self):
        store = self.store()
        original = ' { "turn" : "  Δ\n新  " } '.replace("\n", "\\n")
        payload = {"body": original, "turns": [{"role": "user", "text": "  Draft\n  “A”  "}],
                   "nullable": None, "empty": ""}
        with trace.bind(store, interview_id="family-1", producer="model", request_id="rq1"):
            first = trace.emit("provider.response", payload)
            second = store.emit("provider.response", payload)
        payload["turns"][0]["text"] = "changed after dispatch"
        a, b = self.read(store)
        self.assertEqual([a["sequence"], b["sequence"]], [1, 2])
        self.assertEqual([a["event_id"], b["event_id"]], [first, second])
        self.assertNotEqual(first, second)
        self.assertEqual(a["payload"]["body"], original)
        self.assertEqual(a["payload"]["turns"][0]["text"], "  Draft\n  “A”  ")
        self.assertEqual(a["payload"], b["payload"])
        self.assertIsNone(a["payload"]["nullable"])
        self.assertEqual(a["payload"]["empty"], "")
        self.assertEqual(a["interview_id"], b["interview_id"])
        self.assertEqual(a["producer"], "model")
        self.assertNotIn("turn_id", a)

    def test_no_shared_default_or_cross_store_context_on_worker(self):
        first, second = self.store(), self.store()
        self.assertFalse(trace.active())
        with trace.bind(first, turn_id="u1"):
            with ThreadPoolExecutor() as pool:
                submitted = pool.submit(trace.wrap(lambda: trace.emit("worker.observed", {})))
                self.assertIsNotNone(submitted.result())
                self.assertIsNone(pool.submit(trace.emit, "worker.unbound").result())
            with trace.bind(second):
                self.assertTrue(trace.content_enabled())
                trace.emit("second.observed")
            second.emit("direct.observed")
        self.assertEqual(self.read(first)[0]["turn_id"], "u1")
        b = self.read(second)
        self.assertEqual([row["type"] for row in b], ["second.observed", "direct.observed"])
        self.assertTrue(all("turn_id" not in row for row in b))
        self.assertNotEqual(first.run_id, second.run_id)

    def test_content_secrets_nested_json_transient_media_and_files(self):
        private = "known-provider-credential-synthetic"
        store = self.store(OPENAI_API_KEY=private)
        store.register_secret("csrf-canary-012345")
        item = {"value": "business value", "run_id": "agent-poll-cap-canary",
                "document_scope": "doc-scope-canary", "headers": {"Authorization": "header-canary"},
                "submission_key": "submit-canary", "knowledgeStatusToken": "status-canary",
                "unsent_answer": "unsent-canary", "sdp": "ice-canary",
                "video": b"binary-canary", "image_url": "data:image/png;base64,image-canary",
                "reason": f"echoed {private}", "another": "echoed csrf-canary-012345",
                "random": "Bearer standalone-secret-012345", "input_tokens": 15,
                "excerpts": [{"source_id": "doc_243_c1", "text": "file-canary"}]}
        store.emit("model.dispatch", {"input": json.dumps(item, default=lambda _: "ignored"),
                                      "direct": item,
                                      "reasoning": {"type": "reasoning", "summary": "reason-canary"}})
        row = self.read(store)[0]
        wire = json.dumps(row)
        for value in ("canary", private, "standalone-secret"):
            self.assertNotIn(value, wire)
        self.assertEqual(row["payload"]["direct"]["value"], "business value")
        self.assertEqual(row["payload"]["direct"]["input_tokens"], 15)
        self.assertEqual(row["payload"]["input"]["_trace"], "filtered_json_string")
        self.assertIn("doc_243_c1", wire)
        self.assertIn("credential_excluded", wire)

    def test_metadata_redacts_content_values_and_arbitrary_keys(self):
        store = self.store("metadata")
        store.emit("model.response", {"user-supplied-secret-name": "private response",
                                      "text": "private words", "stage": "fast_question",
                                      "input_tokens": 8, "file": {"name": "client.xlsx"}},
                   parent_event_id="op-1", observed_at="2026-11-16T10:00:00.100Z")
        row = self.read(store)[0]
        self.assertEqual(row["payload"]["text"], {"_trace": "metadata_only", "characters": 13})
        self.assertEqual(row["payload"]["stage"], "fast_question")
        self.assertEqual(row["parent_event_id"], "op-1")
        self.assertEqual(row["observed_at"], "2026-11-16T10:00:00.100Z")
        self.assertNotRegex(json.dumps(row), "private words|user-supplied-secret-name|client.xlsx|private response")

    def test_uncommitted_text_embedded_file_previews_and_document_quotes_stay_out(self):
        store = self.store()
        store.register_secret("server-credential-private")
        self.assertIsNone(store.emit("browser.server-credential-private"))
        data = {"file": {"inventory": {"sheets": [{"header_sample": "HEADER-CANARY"}],
                                      "page_inventory": [{"sample": "PAGE-CANARY"}]}},
                "observations": [{"basis": "stated", "sources": ["doc_123_s1"], "quote": "QUOTE-CANARY"}],
                "document_excerpts": [{"source_id": "doc_123_s1", "text": "EXCERPT-CANARY"}]}
        store.emit("provider.input", {"input": json.dumps(data),
                                    "broken": '{"scope":"SCOPE-CANARY",',
                                    "duplicate": '{"scope":"FIRST-CANARY","scope":""}',
                                    "other": {"type": "summary_text", "text": "REASON-CANARY"}})
        row = self.read(store)[0]
        self.assertNotIn("CANARY", json.dumps(row))
        self.assertIn("doc_123_s1", json.dumps(row))
        self.assertEqual(row["payload"]["duplicate"]["_trace"], "ambiguous_json_fields")

    def test_worker_start_failure_does_not_break_close_or_the_next_observation(self):
        store = self.store()
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("synthetic unavailable thread")):
            self.assertIsNone(store.emit("worker.one"))
        self.assertIsNotNone(store.emit("worker.two"))
        self.assertEqual([r["type"] for r in self.read(store)], ["worker.two", "trace.loss"])

    def test_failed_write_starts_new_segment_without_modifying_the_partial_file(self):
        store = self.store()
        open_stream = store._open_stream
        def fail_first():
            open_stream()
            if store._part == 1:
                stream = store._stream
                class Partial:
                    def write(self, data):
                        return stream.write(data[:10])
                    def close(self):
                        stream.close()
                store._stream = Partial()
        with patch.object(store, "_open_stream", fail_first):
            store.emit("worker.one")
            store.emit("worker.two")
            store.close()
        parts = list(store.directory.glob("*.part00000001.jsonl"))
        self.assertEqual(len(parts), 1)
        rows = [json.loads(line) for line in parts[0].read_bytes().splitlines()]
        self.assertEqual([r["type"] for r in rows], ["worker.two", "trace.loss"])
        self.assertEqual(len(next(p for p in store.directory.glob("*.jsonl") if p != parts[0]).read_bytes()), 10)

    def test_mode_selection_off_does_not_create_a_trace(self):
        marker = self.root / "raw-trace-mode.txt"
        self.assertEqual(trace.TraceStore(self.root).mode, "metadata")
        marker.write_text("content\n", encoding="ascii")
        self.assertTrue(trace.TraceStore(self.root).content)
        with patch.dict(os.environ, {"RAW_TRACE_MODE": "off"}):
            store = trace.TraceStore(self.root)
            self.assertFalse(store.enabled)
            self.assertIsNone(store.emit("disabled"))
            self.assertFalse(store.directory.exists())
            self.assertEqual(self.store("metadata").mode, "metadata")
        marker.write_text("invalid", encoding="ascii")
        self.assertEqual(trace.TraceStore(self.root).mode, "metadata")

    def test_parallel_stores_and_threads_do_not_mix_or_lose_events(self):
        stores = [self.store(), self.store()]
        def emit(i):
            stores[i % 2].emit("worker.item", {"i": i})
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(emit, range(120)))
        for j, store in enumerate(stores):
            rows = self.read(store)
            self.assertEqual([r["sequence"] for r in rows], list(range(1, 61)))
            self.assertEqual(sorted(r["payload"]["i"] for r in rows), list(range(j, 120, 2)))

    def test_independent_processes_append_separate_private_runs(self):
        program = (
            "import runpy,sys\n"
            "TraceStore=runpy.run_path(sys.argv[1])['TraceStore']\n"
            "s=TraceStore(sys.argv[2], {'RAW_TRACE_MODE':'content'})\n"
            "for i in range(8): s.emit('process.item', {'i':i,'owner':sys.argv[3]})\n"
            "s.close()"
        )
        def run(owner):
            subprocess.run([sys.executable, "-I", "-B", "-c", program, str(PATH), str(self.root), owner],
                           timeout=20, check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(run, ["one", "two"]))
        runs = []
        for path in (self.root / "raw-trace").glob("*.jsonl"):
            rows = [json.loads(line) for line in path.read_bytes().splitlines()]
            self.assertEqual([r["sequence"] for r in rows], list(range(1, 9)))
            self.assertEqual(len({r["app_run_id"] for r in rows}), 1)
            self.assertEqual(len({r["payload"]["owner"] for r in rows}), 1)
            runs.append(rows[0]["payload"]["owner"])
        self.assertCountEqual(runs, ["one", "two"])

    def test_stalled_writer_never_blocks_a_producer_or_silently_drops_work(self):
        store = self.store()
        blocked, released = threading.Event(), threading.Event()
        write = store._write
        def pause(*args, **kwargs):
            blocked.set()
            released.wait(5)
            write(*args, **kwargs)
        with patch.object(store, "_write", pause), patch.object(trace, "MAX_PENDING_EVENTS", 1):
            store.emit("worker.one")
            self.assertTrue(blocked.wait(5))
            try:
                self.assertIsNotNone(store.emit("worker.two"))
                self.assertIsNone(store.emit("worker.three"))
                self.assertEqual(store.status()["dropped"], 1)
            finally:
                released.set()
            store.close()
        rows = self.read(store)
        self.assertEqual([r["type"] for r in rows], ["worker.one", "worker.two", "trace.loss"])
        self.assertEqual(rows[-1]["sequence"], 4)
        self.assertEqual(rows[-1]["payload"]["dropped"], 1)

    def test_storage_failure_is_reported_without_creating_a_fake_event(self):
        store = self.store()
        store.directory.write_text("existing file")
        self.assertIsNotNone(store.emit("worker.one"))
        store.close()
        self.assertGreaterEqual(store.status()["failed"], 1)
        self.assertEqual(store.directory.read_text(), "existing file")
        self.assertFalse(store.directory.is_dir())

    def test_oversize_event_marks_its_omitted_value(self):
        store = self.store()
        with patch.object(trace, "MAX_EVENT_BYTES", 1500):
            store.emit("oversize.value", {"text": "x"*2000})
            rows = self.read(store)
        self.assertEqual(rows[0]["payload"]["text"], {"_trace": "snapshot_limit", "characters": 2000})

    def test_continuous_run_rotates_at_record_boundaries_without_loss(self):
        store = self.store()
        values = ["small", "small", "small", "oversized" * 250, "last", "last"]
        target = 850
        with patch.object(trace, "MAX_SEGMENT_BYTES", target):
            for value in values:
                store.emit("process.item", {"text": value})
            rows = self.read(store)
        segments = sorted(store.directory.glob("*.jsonl"))
        self.assertGreater(len(segments), 2)
        self.assertEqual([r["sequence"] for r in rows], list(range(1, len(values)+1)))
        self.assertEqual([r["payload"]["text"] for r in rows], values)
        self.assertTrue(all(r["app_run_id"] == store.run_id for r in rows))
        oversized = [file for file in segments if file.stat().st_size > target]
        self.assertEqual(len(oversized), 1)
        self.assertEqual(json.loads(oversized[0].read_bytes())["sequence"], 4)
        self.assertEqual((store.status()["dropped"], store.status()["failed"]), (0, 0))

    def test_disk_reserve_throttles_probes_and_marks_the_first_recovered_write(self):
        store = self.store()
        written = Queue()
        write = store._write
        now = [100.]
        low = SimpleNamespace(free=trace.DISK_RESERVE_BYTES + 1)
        healthy = SimpleNamespace(free=trace.DISK_RESERVE_BYTES + 50*1024*1024)
        def observed(*args, **kwargs):
            write(*args, **kwargs)
            written.put(args[0])
        def send(expected):
            self.assertIsNotNone(store.emit("test.observation", {"n": expected}))
            self.assertEqual(written.get(timeout=3), expected)
        def probe(_):
            self.assertNotEqual(threading.current_thread(), threading.main_thread())
            return low if now[0] == 100. else healthy
        with patch.object(store, "_write", observed), patch.object(trace, "monotonic", lambda: now[0]), \
                patch.object(trace.shutil, "disk_usage", side_effect=probe) as usage:
            send(1)
            send(2)
            self.assertEqual(usage.call_count, 1)
            self.assertFalse(store.directory.exists())
            self.assertEqual(store.status()["space_pause"], "low_disk_space")
            now[0] += trace.SPACE_CHECK_SECONDS
            send(3)
            send(4)
            self.assertEqual(usage.call_count, 2)
            self.assertIsNone(store.status()["space_pause"])
            rows = self.read(store)
        self.assertEqual([r["sequence"] for r in rows], [3, 4, 5])
        self.assertEqual(rows[0]["storage_gap_before"], {"first_sequence": 1, "last_sequence": 2, "omitted": 2})
        self.assertNotIn("storage_gap_before", rows[1])
        self.assertEqual(rows[-1]["type"], "trace.loss")
        self.assertEqual(store.status()["space_omitted"], 2)

    def test_space_sample_budget_refreshes_and_shutdown_respects_the_reserve(self):
        store = self.store()
        healthy = SimpleNamespace(free=trace.DISK_RESERVE_BYTES + 65536)
        with patch.object(trace, "SPACE_CHECK_BYTES", 1), patch.object(trace, "monotonic", return_value=100.), \
                patch.object(trace.shutil, "disk_usage", side_effect=[healthy, OSError("synthetic probe failure")]) as usage:
            store.emit("test.first")
            store.emit("test.missing")
            store.emit("test.still_missing")
            rows = self.read(store)
        self.assertEqual(usage.call_count, 2)
        self.assertEqual([r["type"] for r in rows], ["test.first"])
        self.assertEqual(store.status()["space_pause"], "space_check_failed")
        self.assertEqual(store.status()["space_omitted"], 2)
        self.assertEqual(store.status()["dropped"], 2)


if __name__ == "__main__":
    unittest.main()
