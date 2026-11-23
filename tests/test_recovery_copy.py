"""The optional recovery copy of an unsaved interview: local store and HTTP boundary.

Off unless the person turns it on. Real servers on free local ports with throwaway data
folders; the provider is a stand-in that records every call and answers none. No network,
no provider request, no fixed port and no data of the real application is used.
"""
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

APP = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server = load_module("recovery_collector_server", "server.py")
launcher = load_module("recovery_collector_launcher", "launcher.py")

ANSWER = "PRIVATE_ANSWER_SENTINEL: every Friday I reconcile the fee ledger."
UNSENT = "PRIVATE_UNSENT_SENTINEL half-typed answer"
SETTING_LABEL = "Keep a recovery copy on this computer"


def interview(turns=2, name="Fee billing"):
    rows = []
    for index in range(turns):
        role = "assistant" if index % 2 == 0 else "user"
        rows.append({"id": f"t{index + 1:03d}", "role": role,
                     "text": "What happens on a Friday?" if role == "assistant" else ANSWER})
    return {"schema_version": 1, "saved_at": "2026-11-13T14:32:05.000Z",
            "context": {"process_name": name, "process_owner": "Billing lead",
                        "objective": "Understand the work", "background": ""},
            "process_name_manual": True, "derived_process_title": "", "turns": rows,
            "coverage": [], "summary": "", "memo_findings": [], "focus": "", "parking_lot": [],
            "closure": {"asked": False, "confirmed": False}, "draft": None, "workflow": None,
            "documents": None, "synthetic_example": False, "unsent_answer": UNSENT, "voice_choice": None}


class RecordingProvider(server.OpenAIClient):
    """Believes it has a key; records every provider-bound call and completes none."""

    def __init__(self):
        super().__init__({"OPENAI_API_KEY": "recovery-test-not-a-key"})
        self.calls = []

    def request(self, path, body, content_type="application/json", timeout=90, on_text=None):
        self.calls.append((path, body))
        raise server.APIError("Recovery tests never reach a provider.", 503)


class RecoveryCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="collector-recovery-")))
        self.instances = []

    def tearDown(self):
        for httpd, worker in self.instances:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=5)

    def serve(self, data="work", provider=None):
        httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=provider or RecordingProvider(),
                                       documents_root=self.root / data / "documents", knowledge_settings={})
        worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.instances.append((httpd, worker))
        return httpd

    def call(self, httpd, path, payload=None, headers=None, raw=None):
        """POST as the page does (token and origin), or GET when there is no body."""
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
        try:
            if payload is None and raw is None:
                connection.request("GET", path)
            else:
                body = raw if raw is not None else json.dumps(payload).encode("utf-8")
                sent = {"Content-Type": "application/json", "X-CSRF-Token": httpd.csrf_token,
                        "Origin": f"http://127.0.0.1:{httpd.server_port}"}
                sent.update(headers or {})
                connection.request("POST", path, body=body, headers={k: v for k, v in sent.items() if v is not None})
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    def folder(self, data="work"):
        return self.root / data / "recovery"

    def kept_text(self, data="work"):
        """Everything this instance wrote under its data folder, as one string."""
        base = self.root / data
        return "\n".join(path.read_text(encoding="utf-8", errors="replace")
                         for path in sorted(base.rglob("*")) if path.is_file() and path.suffix in (".json", ".jsonl", ".tmp"))

    def turn_on(self, httpd):
        status, result = self.call(httpd, "/api/recovery/setting", {"enabled": True})
        self.assertEqual((status, result["enabled"]), (200, True))
        return result


class OffByDefaultTests(RecoveryCase):
    def test_nothing_is_kept_and_nothing_is_written_until_the_person_turns_it_on(self):
        httpd = self.serve()
        status, config = self.call(httpd, "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(config["recovery"], {"enabled": False, "stored": False})
        self.assertEqual(self.call(httpd, "/api/recovery/status", {}), (200, {"enabled": False, "draft": None}))
        status, refused = self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        self.assertEqual(status, 409)
        self.assertIs(refused["enabled"], False)
        self.assertIn("turned off", refused["error"])
        self.assertEqual(self.call(httpd, "/api/recovery/load", {})[0], 404)
        self.assertFalse(self.folder().exists(), "With the setting off no recovery folder may appear")
        self.assertNotIn("SENTINEL", self.kept_text())

    def test_turning_it_off_again_deletes_the_copy_and_leaves_no_folder(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})[0], 200)
        self.assertIn("PRIVATE_ANSWER_SENTINEL", self.kept_text())
        status, result = self.call(httpd, "/api/recovery/setting", {"enabled": False})
        self.assertEqual((status, result), (200, {"enabled": False, "draft": None}))
        self.assertFalse(self.folder().exists())
        self.assertNotIn("SENTINEL", self.kept_text())
        self.assertEqual(self.call(httpd, "/api/config")[1]["recovery"], {"enabled": False, "stored": False})
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})[0], 409)

    def test_unreadable_or_unknown_setting_does_not_disclose_an_existing_copy(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        setting = self.folder() / "setting.json"
        for raw in (b"damaged", b'{"format":2,"enabled":true}', b'{"format":1,"enabled":false}'):
            with self.subTest(setting=raw):
                setting.write_bytes(raw)
                self.assertEqual(self.call(httpd, "/api/recovery/status", {})[1], {"enabled": False, "draft": None})
                self.assertEqual(self.call(httpd, "/api/recovery/load", {})[0], 404)
                self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})[0], 409)
                self.assertTrue((self.folder() / "draft.json").exists())
        self.turn_on(httpd)
        self.assertEqual(self.call(httpd, "/api/recovery/load", {})[1]["draft"]["session"], interview())

    def test_the_setting_must_be_a_plain_choice(self):
        httpd = self.serve()
        for value in ("true", 1, None, {"enabled": True}):
            status, result = self.call(httpd, "/api/recovery/setting", {"enabled": value})
            self.assertEqual(status, 400, value)
        self.assertEqual(self.call(httpd, "/api/config")[1]["recovery"]["enabled"], False)


class KeptCopyTests(RecoveryCase):
    def test_one_copy_is_kept_described_and_given_back_unchanged(self):
        httpd = self.serve()
        self.assertEqual(self.turn_on(httpd), {"enabled": True, "draft": None})
        saved = interview(turns=4)
        status, written = self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": saved})
        self.assertEqual(status, 200)
        self.assertEqual(written["id"], "a" * 32)
        self.assertRegex(written["saved_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        status, state = self.call(httpd, "/api/recovery/status", {})
        self.assertEqual(status, 200)
        self.assertEqual(state["draft"], {"id": "a" * 32, "saved_at": written["saved_at"], "process_name": "Fee billing",
                                          "messages": 4, "readable": True})
        self.assertNotIn("SENTINEL", json.dumps(state), "The description of a copy carries none of its text")
        status, loaded = self.call(httpd, "/api/recovery/load", {"id": "a" * 32})
        self.assertEqual(status, 200)
        self.assertEqual(loaded["draft"]["session"], saved)
        self.assertEqual(loaded["draft"]["id"], "a" * 32)
        self.assertEqual(self.call(httpd, "/api/config")[1]["recovery"], {"enabled": True, "stored": True})
        self.assertEqual(sorted(path.name for path in self.folder().iterdir()), ["draft.json", "setting.json"])

    def test_the_description_uses_the_derived_title_and_leaves_file_notices_out_of_the_count(self):
        httpd = self.serve()
        self.turn_on(httpd)
        saved = interview(turns=3, name="")
        saved.update(process_name_manual=False, derived_process_title="Quarterly fee run")
        saved["turns"].append({"id": "doc_note_1", "role": "assistant", "text": "File added: fees.xlsx", "document_event": True})
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "b" * 32, "session": saved})[0], 200)
        draft = self.call(httpd, "/api/recovery/status", {})[1]["draft"]
        self.assertEqual((draft["process_name"], draft["messages"]), ("Quarterly fee run", 3))

    def test_text_in_any_script_and_half_a_character_pair_come_back_as_they_were_sent(self):
        httpd = self.serve()
        self.turn_on(httpd)
        saved = interview(turns=2, name="請求書の承認 \ud83d")   # a name cut in the middle of an emoji
        saved["turns"][1]["text"] = "Ελέγχω το τιμολόγιο 👨‍👩‍👧 and then \ud83d"
        saved["unsent_answer"] = "half \ude00 pair"
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": saved})[0], 200)
        status, state = self.call(httpd, "/api/recovery/status", {})
        self.assertEqual(status, 200)
        self.assertTrue(state["draft"]["process_name"].startswith("請求書の承認"))
        self.assertEqual(self.call(httpd, "/api/config")[1]["recovery"]["stored"], True)
        status, loaded = self.call(httpd, "/api/recovery/load", {"id": "a" * 32})
        self.assertEqual(status, 200)
        self.assertEqual(loaded["draft"]["session"], saved)
        # Kept as UTF-8 text, not as escapes three times the size.
        self.assertIn("請求書の承認".encode("utf-8"), (self.folder() / "draft.json").read_bytes())

    def test_the_same_interview_replaces_its_copy_and_another_interview_does_not(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview(2)})[0], 200)
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview(6)})[0], 200)
        self.assertEqual(self.call(httpd, "/api/recovery/status", {})[1]["draft"]["messages"], 6)
        status, refused = self.call(httpd, "/api/recovery/save", {"id": "b" * 32, "session": interview(2, "Other work")})
        self.assertEqual(status, 409)
        self.assertEqual((refused["draft"]["id"], refused["draft"]["process_name"], refused["draft"]["messages"]),
                         ("a" * 32, "Fee billing", 6))
        kept = self.call(httpd, "/api/recovery/load", {})[1]["draft"]
        self.assertEqual((kept["id"], len(kept["session"]["turns"])), ("a" * 32, 6))
        # Asking for a copy that is no longer the stored one names the stored one instead of handing it over.
        status, changed = self.call(httpd, "/api/recovery/load", {"id": "b" * 32})
        self.assertEqual((status, changed["draft"]["id"]), (409, "a" * 32))
        self.assertNotIn("session", changed["draft"])

    def test_discard_deletes_only_the_copy_it_names(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        status, kept = self.call(httpd, "/api/recovery/discard", {"id": "b" * 32})
        self.assertEqual((status, kept["draft"]["id"]), (200, "a" * 32))
        self.assertTrue((self.folder() / "draft.json").is_file())
        status, gone = self.call(httpd, "/api/recovery/discard", {"id": "a" * 32})
        self.assertEqual((status, gone), (200, {"enabled": True, "draft": None}))
        self.assertFalse((self.folder() / "draft.json").exists())
        self.assertNotIn("SENTINEL", self.kept_text())
        self.assertEqual(self.call(httpd, "/api/recovery/load", {})[0], 404)
        # The place is free again for another interview.
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "b" * 32, "session": interview()})[0], 200)

    def test_requests_without_the_page_token_or_from_another_origin_are_refused(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        for headers in ({"X-CSRF-Token": None}, {"X-CSRF-Token": "guess"}, {"Origin": "http://127.0.0.1:1"},
                        {"Origin": "https://example.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
            for path, body in (("/api/recovery/load", {}), ("/api/recovery/status", {}), ("/api/recovery/discard", {"id": "a" * 32}),
                               ("/api/recovery/setting", {"enabled": False}),
                               ("/api/recovery/save", {"id": "a" * 32, "session": interview(6)})):
                status, result = self.call(httpd, path, body, headers=headers)
                self.assertEqual(status, 403, (headers, path))
                self.assertNotIn("SENTINEL", json.dumps(result))
        self.assertEqual(self.call(httpd, "/api/recovery/status", {})[1]["draft"]["messages"], 2)
        # A plain GET never reads, writes or deletes a copy.
        for path in ("/api/recovery/load", "/api/recovery/status", "/api/recovery/discard"):
            self.assertEqual(self.call(httpd, path)[0], 404)
        self.assertEqual(self.call(httpd, "/api/recovery/unknown", {})[0], 404)

    def test_only_what_open_saved_interview_would_accept_is_stored(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})

        def changed(**fields):
            value = interview()
            value.update(fields)
            return value

        long_turns = [{"id": f"t{index:03d}", "role": "user", "text": "x" * 5000} for index in range(81)]
        refused = {
            "not a saved interview": {"turns": []},
            "another format version": changed(schema_version=2),
            "no context": changed(context=None),
            "an oversized objective": changed(context={"process_name": "Fee billing", "objective": "x" * 501}),
            "an oversized background": changed(context={"process_name": "Fee billing", "background": "x" * 8001}),
            "turns that are not a list": changed(turns={"t001": "text"}),
            "more than 400 turns": changed(turns=[{"id": f"t{index:03d}", "role": "user", "text": "x"} for index in range(401)]),
            "a turn over 6,000 characters": changed(turns=[{"id": "t001", "role": "user", "text": "x" * 6001}]),
            # The page counts UTF-16 units: 3,001 emoji are 6,002 of them.
            "a turn over the limit as the page counts it": changed(turns=[{"id": "t001", "role": "user", "text": "\U0001F600" * 3001}]),
            "a turn without text": changed(turns=[{"id": "t001", "role": "user"}]),
            "more than 400,000 characters": changed(turns=long_turns),
            "a duplicate turn id": changed(turns=[{"id": "t001", "role": "user", "text": "a"}, {"id": "t001", "role": "user", "text": "b"}]),
            "a reserved turn id": changed(turns=[{"id": "context", "role": "user", "text": "a"}]),
            "an unknown role": changed(turns=[{"id": "t001", "role": "system", "text": "a"}]),
            "an oversized unsent answer": changed(unsent_answer="x" * 18001),
            "the fictional example": changed(synthetic_example=True),
        }
        for label, value in refused.items():
            with self.subTest(label):
                status, result = self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": value})
                self.assertEqual(status, 400, result)
                self.assertIsInstance(result["error"], str)
        for label, identifier in (("no id", None), ("a short id", "abc"), ("a path", "../../draft"), ("a long id", "a" * 65)):
            with self.subTest(label):
                self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": identifier, "session": interview()})[0], 400)
        for label, raw in (("not JSON", b"{"), ("not an object", b"[1]")):
            with self.subTest(label):
                self.assertEqual(self.call(httpd, "/api/recovery/save", raw=raw)[0], 400)
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()},
                                   headers={"Content-Type": "text/plain"})[0], 415)
        # Every refusal left the stored copy as it was.
        kept = self.call(httpd, "/api/recovery/load", {})[1]["draft"]
        self.assertEqual(kept["session"], interview())
        # What the page itself can hold is accepted, at the limits and with an empty turn.
        full = changed(turns=[{"id": "t001", "role": "user", "text": "\U0001F600" * 3000}, {"id": "t002", "role": "assistant", "text": ""}],
                       unsent_answer="x" * 18000,
                       context={"process_name": "n" * 500, "process_owner": "", "objective": "o" * 500, "background": "b" * 8000})
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": full})[0], 200)
        self.assertEqual(self.call(httpd, "/api/recovery/load", {})[1]["draft"]["session"], full)
        self.assertEqual([path.name for path in self.folder().iterdir() if path.suffix == ".tmp"], [])

    def test_store_refuses_invalid_sessions_from_any_caller(self):
        store = server.RecoveryStore(self.folder())
        store.set_enabled(True)
        saved = interview()
        store.save("first-copy", saved)
        for key, value in (("schema_version", True), ("turns", "damaged")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                store.save("first-copy", {**saved, key: value})
        self.assertEqual(store.load()["session"], saved)

    def test_invalid_consent_and_oversized_saves_cannot_change_storage(self):
        store = server.RecoveryStore(self.folder())
        with self.assertRaises(ValueError):
            store.set_enabled("false")
        self.assertFalse(self.folder().exists())
        store.set_enabled(True)
        store.save("first-copy", interview())
        with patch.object(server.recovery_store, "MAX_RECOVERY", 4000):
            with self.assertRaises(ValueError):
                store.save("first-copy", {**interview(), "summary": "x" * 5000})
        self.assertEqual(store.load()["session"], interview())

    def test_damaged_saved_session_is_described_without_exposing_or_replacing_it(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        path = self.folder() / "draft.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for changes in ({"format": True}, {"session": {**interview(), "turns": "damaged"}}):
            with self.subTest(field=next(iter(changes))):
                raw = json.dumps({**original, **changes}).encode("utf-8")
                path.write_bytes(raw)
                summary = self.call(httpd, "/api/recovery/status", {})[1]["draft"]
                self.assertIs(summary["readable"], False)
                self.assertEqual(self.call(httpd, "/api/recovery/load", {})[0], 409)
                response = self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
                self.assertEqual(response[0], 409)
                self.assertEqual(path.read_bytes(), raw)

    def test_a_copy_larger_than_the_page_would_open_is_refused(self):
        self.assertEqual(server.MAX_RECOVERY, 16 * 1024 * 1024, "The same bound as Open saved interview in web/app.js")
        page = (APP / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("file.size > 16 * 1024 * 1024", page)
        httpd = self.serve()
        self.turn_on(httpd)
        with patch.object(server, "MAX_RECOVERY", 4000):
            small = interview()
            self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": small})[0], 200)
            large = interview()
            large["summary"] = "x" * 5000
            status, result = self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": large})
            self.assertEqual(status, 413)
            self.assertIn("16 MB", result["error"])
        self.assertEqual(self.call(httpd, "/api/recovery/load", {})[1]["draft"]["session"], small)

    def test_a_failed_write_keeps_the_earlier_copy_whole(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview(2)})
        with patch.object(server.os, "replace", side_effect=PermissionError("in use")), patch.object(server.time, "sleep"):
            status, result = self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview(6)})
        self.assertEqual(status, 500)
        self.assertNotIn("in use", result["error"])
        self.assertEqual(len(self.call(httpd, "/api/recovery/load", {})[1]["draft"]["session"]["turns"]), 2)
        self.assertEqual([path.name for path in self.folder().iterdir() if path.suffix == ".tmp"], [])

    def test_a_copy_this_version_cannot_read_is_reported_and_never_overwritten(self):
        httpd = self.serve()
        self.turn_on(httpd)
        newer = {"format": server.RECOVERY_FORMAT + 1, "id": "c" * 32, "saved_at": "2026-11-13T10:00:00Z", "session": interview()}
        for label, raw in (("a newer format", json.dumps(newer).encode("utf-8")), ("damaged", b'{"format": 1, "id": ')):
            with self.subTest(label):
                (self.folder() / "draft.json").write_bytes(raw)
                draft = self.call(httpd, "/api/recovery/status", {})[1]["draft"]
                self.assertIs(draft["readable"], False)
                self.assertNotIn("SENTINEL", json.dumps(draft))
                self.assertEqual(self.call(httpd, "/api/config")[1]["recovery"]["stored"], True)
                status, refused = self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
                self.assertEqual((status, refused["draft"]["readable"]), (409, False))
                self.assertEqual((self.folder() / "draft.json").read_bytes(), raw, "An unreadable copy is left as it is")
                self.assertEqual(self.call(httpd, "/api/recovery/load", {"id": draft["id"]})[0], 409)
                status, gone = self.call(httpd, "/api/recovery/discard", {"id": draft["id"]})
                self.assertEqual((status, gone["draft"]), (200, None))
                self.assertFalse((self.folder() / "draft.json").exists())


    def test_a_stored_file_larger_than_the_page_opens_is_never_handed_to_the_page(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.assertEqual(self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})[0], 200)
        path = self.folder() / "draft.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["session"]["summary"] = "x" * 20000     # grown on disk, outside the app
        path.write_text(json.dumps(record), encoding="utf-8")
        with patch.object(server.recovery_store, "MAX_RECOVERY", 8000):
            draft = self.call(httpd, "/api/recovery/status", {})[1]["draft"]
            self.assertIs(draft["readable"], False)
            status, refused = self.call(httpd, "/api/recovery/load", {})
            self.assertEqual(status, 409)
            self.assertNotIn("session", json.dumps(refused))


class ExpiryTests(RecoveryCase):
    def test_a_copy_older_than_seven_days_is_deleted_instead_of_offered(self):
        self.assertEqual(server.RECOVERY_DAYS, 7)
        clock = {"now": 1_800_000_000.0}
        store = server.RecoveryStore(self.folder(), clock=lambda: clock["now"])
        store.set_enabled(True)
        store.save("a" * 32, interview())
        clock["now"] += 7 * 86400 - 60
        self.assertEqual(store.status()["draft"]["id"], "a" * 32)
        self.assertIsNotNone(store.load())
        clock["now"] += 120
        self.assertEqual(store.status(), {"enabled": True, "draft": None})
        self.assertFalse((self.folder() / "draft.json").exists())
        self.assertIsNone(store.load())
        self.assertTrue(store.enabled(), "Expiry removes the copy, not the person's choice")

    def test_an_expired_copy_is_removed_when_the_server_starts(self):
        first = self.serve()
        self.turn_on(first)
        self.call(first, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        path = self.folder() / "draft.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["saved_epoch"] -= 8 * 86400
        path.write_text(json.dumps(record), encoding="utf-8")
        second = self.serve()
        self.assertFalse(path.exists())
        self.assertEqual(self.call(second, "/api/config")[1]["recovery"], {"enabled": True, "stored": False})

    def test_another_interview_may_take_the_place_of_an_expired_copy(self):
        clock = {"now": 1_800_000_000.0}
        store = server.RecoveryStore(self.folder(), clock=lambda: clock["now"])
        store.set_enabled(True)
        store.save("a" * 32, interview())
        clock["now"] += 8 * 86400
        store.save("b" * 32, interview(4, "Other work"))
        self.assertEqual(store.status()["draft"]["process_name"], "Other work")


class SharedStoreTests(RecoveryCase):
    def test_two_servers_cannot_both_claim_the_empty_recovery_slot(self):
        first = server.RecoveryStore(self.folder())
        second = server.RecoveryStore(self.folder())
        first.set_enabled(True)
        writing = threading.Event()
        release = threading.Event()
        attempted = threading.Event()
        write = first._write

        def held_write(path, raw):
            writing.set()
            if not release.wait(5):
                raise TimeoutError("test writer timed out")
            write(path, raw)

        def competing_save():
            attempted.set()
            return second.save("second-id", interview(name="Second process"))

        with patch.object(first, "_write", held_write), ThreadPoolExecutor(2) as workers:
            winner = workers.submit(first.save, "first-id", interview(name="First process"))
            try:
                self.assertTrue(writing.wait(5))
                contender = workers.submit(competing_save)
                self.assertTrue(attempted.wait(5))
                with self.assertRaises(TimeoutError):
                    contender.result(.2)
            finally:
                release.set()
            self.assertEqual(winner.result()["id"], "first-id")
            with self.assertRaises(server.RecoveryConflict):
                contender.result()
        self.assertEqual(second.load()["session"]["context"]["process_name"], "First process")

    def test_two_servers_on_the_same_data_share_the_setting_and_the_copy(self):
        # The browser launcher (8774) and the desktop window (8776) are two servers on one work folder.
        browser, desktop = self.serve(), self.serve()
        self.assertNotEqual(browser.server_port, desktop.server_port)
        self.turn_on(browser)
        self.assertEqual(self.call(desktop, "/api/config")[1]["recovery"], {"enabled": True, "stored": False})
        saved = interview(4)
        self.assertEqual(self.call(browser, "/api/recovery/save", {"id": "a" * 32, "session": saved})[0], 200)
        self.assertEqual(self.call(desktop, "/api/recovery/status", {})[1]["draft"]["messages"], 4)
        self.assertEqual(self.call(desktop, "/api/recovery/load", {"id": "a" * 32})[1]["draft"]["session"], saved)
        # The other window's own interview does not silently replace it.
        self.assertEqual(self.call(desktop, "/api/recovery/save", {"id": "b" * 32, "session": interview()})[0], 409)
        # A copy updated through one server is seen as updated through the other.
        self.assertEqual(self.call(browser, "/api/recovery/save", {"id": "a" * 32, "session": interview(6)})[0], 200)
        self.assertEqual(self.call(desktop, "/api/recovery/status", {})[1]["draft"]["messages"], 6)
        self.assertEqual(self.call(desktop, "/api/recovery/setting", {"enabled": False})[0], 200)
        self.assertEqual(self.call(browser, "/api/recovery/status", {}), (200, {"enabled": False, "draft": None}))
        self.assertEqual(self.call(browser, "/api/recovery/save", {"id": "a" * 32, "session": interview()})[0], 409)

    def test_servers_with_separate_data_share_nothing(self):
        one, other = self.serve("one"), self.serve("other")
        self.turn_on(one)
        self.call(one, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        self.assertEqual(self.call(other, "/api/config")[1]["recovery"], {"enabled": False, "stored": False})
        self.assertFalse(self.folder("other").exists())


class NowhereElseTests(RecoveryCase):
    def test_the_copy_reaches_no_provider_request_and_no_log(self):
        provider = RecordingProvider()
        httpd = self.serve(provider=provider)
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        self.call(httpd, "/api/recovery/status", {})
        self.call(httpd, "/api/recovery/load", {"id": "a" * 32})
        self.assertEqual(provider.calls, [], "Keeping, describing and reading a copy calls no provider")
        # A later interview request carries what the page sends with it and nothing from the stored copy.
        payload = {"context": {"process_name": "Other work", "process_owner": "", "objective": "Understand the work", "background": ""},
                   "turns": [{"id": "t001", "role": "assistant", "text": "What starts the work?"},
                             {"id": "t002", "role": "user", "text": "A supplier email starts a case."}], "action": "answer"}
        self.call(httpd, "/api/interview", payload)
        self.assertTrue(provider.calls, "The interview request must have reached the stand-in provider")
        sent = json.dumps([body for _path, body in provider.calls], default=str)
        self.assertIn("A supplier email starts a case.", sent)
        self.assertNotIn("SENTINEL", sent)
        self.assertNotIn("Fee billing", sent)
        self.call(httpd, "/api/recovery/discard", {"id": "a" * 32})
        log = httpd.diagnostics_path.read_text(encoding="utf-8") if httpd.diagnostics_path.exists() else ""
        self.assertNotIn("SENTINEL", log)
        self.assertNotIn("Fee billing", log)

    def test_the_copy_lives_only_in_the_private_work_folder(self):
        httpd = self.serve()
        self.turn_on(httpd)
        self.call(httpd, "/api/recovery/save", {"id": "a" * 32, "session": interview()})
        holding = [path.relative_to(self.root).as_posix() for path in self.root.rglob("*")
                   if path.is_file() and b"PRIVATE_ANSWER_SENTINEL" in path.read_bytes()]
        self.assertEqual(holding, ["work/recovery/draft.json"])
        ignored = (APP / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("work/", ignored, "The work folder, and so the recovery copy, stays out of Git")


class WordingTests(RecoveryCase):
    """The promise that nothing is kept between sessions is stated with its one exception."""

    def test_the_data_notice_describes_the_option_and_the_default(self):
        notice = server.OpenAIClient({}).public_config()["data_notice"]
        self.assertIn("not saved automatically", notice)
        self.assertIn(SETTING_LABEL, notice)
        self.assertIn("That copy stays on this computer", notice)
        self.assertIn("seven days", notice)
        page = (APP / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn(SETTING_LABEL, page, "The notice names the setting as the page labels it")

    def started(self, turn_on):
        real, built = server.InterviewServer, []

        def build(address, handler):
            built.append(real(("127.0.0.1", 0), handler, client=server.OpenAIClient({}),
                              documents_root=self.root / "work" / "documents", knowledge_settings={}))
            if turn_on:
                built[0].recovery.set_enabled(True)
            return built[0]

        console = io.StringIO()
        with patch.object(server, "InterviewServer", side_effect=build), \
             patch.object(real, "serve_forever", return_value=None), \
             patch.object(sys, "argv", ["server.py"]), patch("sys.stdout", new=console):
            server.main()
        return console.getvalue().splitlines()

    def test_the_start_line_says_whether_interviews_are_kept(self):
        off = self.started(False)
        self.assertEqual(len(off), 2)
        self.assertIn("Interviews are not saved automatically", off[1])
        self.assertIn("recovery copy option", off[1])
        self.assertIn("is off", off[1])
        on = self.started(True)
        self.assertEqual(len(on), 2)
        self.assertIn("recovery copy option is on", on[1])
        self.assertIn("seven days", on[1])
        self.assertNotIn("not saved automatically", on[1])
        for lines in (off, on):
            self.assertIn("Save the interview separately", lines[1])

    def stopped(self, config):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        opener = MagicMock()
        opener.open.return_value = response
        console = io.StringIO()
        with patch.object(sys, "argv", ["launcher.py", "--stop", "--port", "8791"]), \
             patch.object(launcher, "config", side_effect=[config, None]), \
             patch.object(launcher, "build_opener", return_value=opener), \
             patch.object(launcher.time, "sleep"), patch("sys.stdout", new=console):
            launcher.main()
        return console.getvalue().strip()

    def test_the_stop_line_names_the_recovery_copy_only_when_one_may_exist(self):
        plain = "AI Process Collector stopped. Unsaved sessions remain only in any open browser tab."
        self.assertEqual(self.stopped({"csrf_token": "synthetic"}), plain)
        self.assertEqual(self.stopped({"csrf_token": "synthetic", "recovery": {"enabled": False, "stored": False}}), plain)
        for recovery in ({"enabled": True, "stored": False}, {"enabled": False, "stored": True}):
            line = self.stopped({"csrf_token": "synthetic", "recovery": recovery})
            self.assertIn("AI Process Collector stopped.", line)
            self.assertIn("recovery copy", line)
            self.assertNotEqual(line, plain)

    def test_the_readme_states_the_default_and_the_option(self):
        readme = (APP / "README.md").read_text(encoding="utf-8")
        self.assertIn(SETTING_LABEL, readme)
        self.assertIn("work/recovery", readme)
        self.assertIn("not automatically persisted", readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
