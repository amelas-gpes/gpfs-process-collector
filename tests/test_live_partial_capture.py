"""A live notes capture of an answer still being spoken (live_partial, web/app.js captureMidAnswer).

The page sends the transcript as it stands, the open answer cut off mid-sentence, with
live_partial: true and the capability it holds; when the answer ends it sends the whole answer
with that same capability. The partial capture is notes for display only. It does not invalidate
the capture the page holds, does not claim the capture family, issues no capability and publishes
no ledger, so the capture of the whole answer costs exactly what it costs without it: the same
model call, with the same input (the quick excerpt path for a short answer, the previous capture's
context and the incremental path for a long one), and no facts retired because the partial
text grew. A partial capture that reads as a request to stop, or as a reply the held capture
would answer, is refused before any run or model call. The flag is checked strictly. The provider
is a local stand-in; no network.
"""
import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from test_server import server, interview_payload


def answer(number, text):
    return {"id": f"t{number:03}", "role": "user", "text": text}


def question(number, text):
    return {"id": f"q{number:03}", "role": "assistant", "text": text}


def comparable(calls):
    """Model calls with the ledger's random fact ids (and the revision hash made from them) named by position."""
    text = json.dumps(calls, sort_keys=True)
    for number, fact_id in enumerate(dict.fromkeys(__import__("re").findall(r"fact_[0-9a-f]{32}", text))):
        text = text.replace(fact_id, f"fact_{number}")
    rows = json.loads(text)
    for _, model_input in rows:
        model_input.get("fact_state", {}).pop("base_revision", None)
    return rows


FIRST = "The operator logs each invoice in the register."
PART = "The controller reviews the batch every afternoon."
SHORT = PART + " Then the operator sends the signed register to Treasury."
LONG = SHORT + " " + " ".join([
    "Treasury checks the bank file against the register before anything is released.",
    "Anything above ten thousand needs a second approver from the finance director's office.",
    "Rejected lines go back to the operator, who corrects the account details the same day.",
    "The supplier gets a remittance advice by email from the shared mailbox after release.",
    "At month end the controller reports the totals and the exceptions to the finance director."] * 4)


class PartialCaptureTests(unittest.TestCase):
    def setUp(self):
        self.client = server.OpenAIClient({"OPENAI_API_KEY": "sk-test-synthetic"})
        self.calls = []

        def reply(instructions, model_input, schema, *args, **kwargs):
            if "needs_full_capture" in schema["properties"]:
                self.calls.append(("excerpt", copy.deepcopy(model_input)))
                texts = {turn["id"]: turn["text"] for turn in model_input["new_exchange"]}
                return {"needs_full_capture": False, "open_relationship": "", "gap_source_id": "",
                        "facts": [{"topic": "lifecycle", "source_id": ref, "quote": texts[ref]} for ref in model_input["new_answers"]]}
            self.calls.append(("full", copy.deepcopy(model_input)))
            # A full capture records each new answer it is shown whole, as one fact.
            known = {ref for fact in model_input["fact_state"]["facts"] for ref in fact["evidence_turns"]}
            new = [turn for turn in model_input["turns"] if turn["role"] == "user" and turn["id"] not in known]
            return {"base_revision": model_input["fact_state"]["base_revision"], "topic_states": [], "fact_reconciliations": [],
                    "fact_operations": [{"op": "add", "topic": "lifecycle", "target_id": "", "kind": "detail", "text": turn["text"][:400],
                                         "reason": "new_evidence", "evidence_turns": [turn["id"]]} for turn in new],
                    "summary": "The operator logs invoices and the controller reviews them.", "focus": "lifecycle", "parking_lot": []}

        self.client.structured = reply
        self.payload = interview_payload()
        self.payload.update(live_notes=True, interview_memory=True, action="answer")
        self.start = [question(0, "What starts the work?"), answer(0, FIRST)]
        self.asked = question(1, "What happens next?")

    def capture(self, turns, token=None, **extra):
        return self.client.coordinator.interview({**self.payload, "turns": turns, **({"capture_token": token} if token else {}), **extra})

    def end_of_answer(self, whole, partial):
        """The first answer's capture, optionally a partial one of the next, then the whole next answer."""
        first = self.capture(self.start)
        held = first["capture_token"]
        mid = self.capture(self.start + [self.asked, answer(1, PART)], held, live_partial=True) if partial else None
        before = len(self.calls)
        whole_capture = self.capture(self.start + [self.asked, answer(1, whole)], held)
        return first, mid, whole_capture, self.calls[before:]

    def test_the_capture_of_the_whole_answer_costs_what_it_costs_without_a_partial_one(self):
        for whole, path in ((SHORT, "excerpt"), (LONG, "full")):
            with self.subTest(path=path):
                self.calls = []
                _, _, alone, alone_calls = self.end_of_answer(whole, partial=False)
                self.calls = []
                first, mid, after, after_calls = self.end_of_answer(whole, partial=True)
                # One model call each, of the same kind and with the same input.
                self.assertEqual([kind for kind, _ in after_calls], [path])
                self.assertEqual(comparable(after_calls), comparable(alone_calls))
                if path == "full":
                    # The context of the capture the page held reaches the lead.
                    self.assertIn("previous_capture", after_calls[0][1])
                    self.assertEqual(after_calls[0][1]["previous_capture"]["summary"], first["summary"])
                # Nothing quoted from the partial text is retired: it never entered the ledger.
                self.assertEqual(after["fact_history"], alone["fact_history"])
                self.assertFalse(any(row["state"] == "retired_source" for row in after["fact_history"]))
                self.assertEqual(sorted(fact["text"] for fact in after["fact_provenance"]),
                                 sorted(fact["text"] for fact in alone["fact_provenance"]))
                self.assertTrue(after["capture_token"])

    def test_a_partial_capture_returns_notes_and_keeps_the_held_capture(self):
        first = self.capture(self.start)
        held = first["capture_token"]
        coordinator = self.client.coordinator
        registered = set(coordinator._captures)
        mid = self.capture(self.start + [self.asked, answer(1, PART)], held, live_partial=True)
        # Notes of what was said so far, for display.
        self.assertIs(mid["live_partial"], True)
        self.assertTrue(any(fact["text"] == PART and fact["evidence_turns"] == ["t001"] for fact in mid["fact_provenance"]))
        self.assertTrue(any(fact["text"] == FIRST for fact in mid["fact_provenance"]))
        self.assertEqual(mid["speech_authorization"]["kind"], "question")
        # No capability: nothing can be continued from it, and it is not published.
        self.assertNotIn("capture_token", mid)
        self.assertEqual(set(coordinator._captures), registered)
        # The held capture is still valid, its run neither retired nor cancelled.
        state = coordinator._captures[held]
        self.assertTrue(state["valid"])
        self.assertFalse(state["run"].public_status()["stale"])
        self.assertFalse(state["run"].public_status()["cancelled"])
        # The capture of the whole answer then retires the held capture as any new answer does.
        self.capture(self.start + [self.asked, answer(1, SHORT)], held)
        self.assertFalse(coordinator._captures[held]["valid"])

    def test_a_partial_capture_spends_nothing_on_the_excerpt_budget(self):
        # Two quick excerpt captures in a row are allowed before a full one (pending_live_excerpts).
        # Partial captures in between are not counted, because their ledger is never kept: the
        # captures of whole answers take the same path with and without them.
        def whole_answers(partial):
            self.calls = []
            turns = list(self.start)
            token, kinds = self.capture(turns)["capture_token"], [self.calls[-1][0]]
            for number in range(1, 6):
                said = f"Step {number} is checked by the controller each day and then filed."
                turns = turns + [question(number, "And then?"), answer(number, said)]
                if partial:
                    # It reads the same ledger as the capture of the whole answer, by the same rules.
                    self.capture(turns[:-1] + [answer(number, said.split(" and ")[0])], token, live_partial=True)
                    self.assertEqual(self.calls[-1][0], "full" if kinds[-2:] == ["excerpt", "excerpt"] else "excerpt")
                token = self.capture(turns, token)["capture_token"]
                kinds.append(self.calls[-1][0])
            return kinds
        alone = whole_answers(False)
        self.assertEqual(alone, ["excerpt", "excerpt", "full", "excerpt", "excerpt", "full"])
        self.assertEqual(whole_answers(True), alone)

    def test_the_next_whole_capture_retires_a_partial_one_still_running(self):
        first = self.capture(self.start)
        held = first["capture_token"]
        coordinator = self.client.coordinator
        seen = {}
        original = coordinator._join_family

        def join(payload, run):
            original(payload, run)
            seen["run"] = run
        with patch.object(coordinator, "_join_family", side_effect=join):
            self.capture(self.start + [self.asked, answer(1, PART)], held, live_partial=True)
        self.assertFalse(seen["run"].public_status()["stale"])
        self.capture(self.start + [self.asked, answer(1, SHORT)], held)
        self.assertTrue(seen["run"].public_status()["stale"], "A late partial capture cannot be published after the whole answer")

    def test_a_partial_capture_that_reads_as_a_request_to_stop_is_refused_before_any_call(self):
        held = self.capture(self.start)["capture_token"]
        before = len(self.calls)
        for words in ("The controller reviews the batch. Okay, I need to stop", "Sorry, I need to stop",
                      "The controller reviews the batch; I need to stop", "I need to stop now, my boss is calling"):
            with self.subTest(words=words):
                with self.assertRaises(server.APIError) as raised:
                    self.capture(self.start + [self.asked, answer(1, words)], held, live_partial=True)
                self.assertEqual(raised.exception.status, 409)
        self.assertEqual(len(self.calls), before, "No model call")
        self.assertTrue(self.client.coordinator._captures[held]["valid"], "The held capture stays valid")
        # The same words at the end of the answer get the pause reply, as before.
        reply = self.capture(self.start + [self.asked, answer(1, "Sorry, I need to stop")], held)
        self.assertEqual(reply["speech_authorization"]["kind"], "pause")

    def test_a_partial_capture_never_answers_from_the_held_capture(self):
        # A reply the held capture would answer (a confirmation of the final check, a courtesy after
        # the completion line) is decided when the answer ends; part of an answer is refused.
        held = self.capture(self.start)["capture_token"]
        coordinator = self.client.coordinator
        for step in ("confirmed", "retained", "held", "waiting_fragment", "repeat", "more"):
            with self.subTest(step=step), patch.object(coordinator, "_reply_step", return_value=step), \
                    patch.object(coordinator, "_confirmed_capture") as confirmed:
                with self.assertRaises(server.APIError) as raised:
                    self.capture(self.start + [self.asked, answer(1, "No, that's everything")], held, live_partial=True)
                self.assertEqual(raised.exception.status, 409)
                confirmed.assert_not_called()
        self.assertTrue(coordinator._captures[held]["valid"])

    def test_a_partial_capture_never_holds_a_review(self):
        held = self.capture(self.start)["capture_token"]
        coordinator = self.client.coordinator
        with patch.object(server, "memo_has_enough_detail", return_value=True):
            mid = self.capture(self.start + [self.asked, answer(1, PART)], held, live_partial=True)
            whole = self.capture(self.start + [self.asked, answer(1, SHORT)], held)
        self.assertEqual(mid["speech_authorization"]["kind"], "question")
        self.assertNotIn("review_ticket", mid)
        self.assertEqual(whole["speech_authorization"]["kind"], "review_pending", "The whole answer still can")
        self.assertEqual(len(coordinator._tickets), 1)

    def test_the_flag_is_checked_strictly(self):
        held = self.capture(self.start)["capture_token"]
        turns = self.start + [self.asked, answer(1, PART)]
        before = len(self.calls)
        for value in ("yes", 1, None, {}, [True]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.capture(turns, held, live_partial=value)
        for extra in ({"live_notes": False}, {"live_notes": "true"}, {"action": "close"}, {"action": "skip"},
                      {"_facts_only": True}, {"_ledger_token": held}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.capture(turns, held, live_partial=True, **extra)
        self.assertEqual(len(self.calls), before)
        payload = {**self.payload, "turns": turns, "capture_token": held, "live_partial": True}
        del payload["live_notes"]
        with self.assertRaises(ValueError):
            self.client.coordinator.interview(payload)
        # False is an ordinary capture.
        ordinary = self.capture(turns, held, live_partial=False)
        self.assertTrue(ordinary["capture_token"])
        self.assertNotIn("live_partial", ordinary)


class PartialCaptureHTTPTests(unittest.TestCase):
    """The flag crosses the HTTP boundary as sent, and a malformed one is refused there."""

    @classmethod
    def setUpClass(cls):
        cls.client = server.OpenAIClient({"OPENAI_API_KEY": "sk-test-synthetic"})
        cls.calls = []

        def reply(instructions, model_input, schema, *args, **kwargs):
            cls.calls.append(schema["properties"].keys())
            texts = {turn["id"]: turn["text"] for turn in model_input.get("new_exchange", [])}
            return {"needs_full_capture": False, "open_relationship": "", "gap_source_id": "",
                    "facts": [{"topic": "lifecycle", "source_id": ref, "quote": texts[ref]} for ref in model_input["new_answers"]]}
        cls.client.structured = reply
        root = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=cls.client,
                                           documents_root=root / "documents", knowledge_settings={})
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=3)

    def post(self, payload):
        request = urllib.request.Request(self.url + "/api/agent-team/interview", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", "X-CSRF-Token": self.httpd.csrf_token})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_partial_capture_over_http(self):
        base = {**interview_payload(), "live_notes": True, "interview_memory": True, "action": "answer"}
        start = [question(0, "What starts the work?"), answer(0, FIRST)]
        status, first = self.post({**base, "turns": start})
        self.assertEqual(status, 200, first)
        turns = start + [question(1, "What happens next?"), answer(1, PART)]
        calls = len(self.calls)
        status, refused = self.post({**base, "turns": turns, "capture_token": first["capture_token"], "live_partial": "true"})
        self.assertEqual(status, 400, refused)
        self.assertEqual(len(self.calls), calls)
        status, mid = self.post({**base, "turns": turns, "capture_token": first["capture_token"], "live_partial": True})
        self.assertEqual(status, 200, mid)
        self.assertIs(mid["live_partial"], True)
        self.assertNotIn("capture_token", mid)


if __name__ == "__main__":
    unittest.main()
