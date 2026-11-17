"""Offline concurrency contracts; no provider, microphone or credentials used."""
import copy
import importlib.util
from pathlib import Path
import threading
import time
import types
import unittest

from test_server import server

SPEC = importlib.util.spec_from_file_location("concurrent_interview", Path(__file__).resolve().parents[1] / "concurrent_interview.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


APIError = server.APIError


class API:
    document_reading_summary = staticmethod(server.document_reading_summary)
    APIError = APIError
    # The real closing-language and question checks: a stand-in pattern hid their effect on this path.
    question_rejection = staticmethod(server.question_rejection)
    record_question_rejection = staticmethod(server.record_question_rejection)
    next_uncovered_question = staticmethod(server.next_uncovered_question)

    @staticmethod
    def validate_payload(payload):
        if not isinstance(payload.get("context"), dict) or not isinstance(payload.get("turns"), list):
            raise ValueError("Invalid snapshot")
        return payload["context"], payload["turns"]

    @staticmethod
    def participant_requested_stop(turns, action="answer"):
        return bool(turns and turns[-1].get("text") == "Please pause.")

    @staticmethod
    def check_schema(value, schema):
        if set(value) != {"question", "request_review"} or not isinstance(value["question"], str) or not isinstance(value["request_review"], bool):
            raise ValueError("Invalid question schema")


def payload(text="The clerk receives the invoice."):
    return {"context": {"process_name": "Invoices"}, "turns": [{"id": "u1", "role": "user", "text": text}],
            "_supporting_documents": {}, "action": "answer"}


def wait_for(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("Worker did not reach expected state")


class FakeClient:
    agent_models = {"lead_interviewer": "offline-model"}

    def __init__(self, gate=None):
        self.gate = gate
        self.started = threading.Event()
        self.captures, self.graphs, self.questions = [], [], []
        self.fail = False
        self.request_review = False
        self.graph_gate = None
        self.graph_fail = False
        self.no_new_run = False
        self.question = "What happens after that?"
        self.coordinator = types.SimpleNamespace(interview=self.capture, workflow=self.workflow)

    def structured(self, instructions, data, schema, name, tokens, **kwargs):
        self.questions.append(copy.deepcopy(data))
        return {"question": "" if self.request_review else self.question, "request_review": self.request_review}

    def capture(self, value):
        self.captures.append(copy.deepcopy(value))
        self.started.set()
        if self.gate:
            self.gate.wait(3)
        if self.fail:
            raise APIError("Private provider detail")
        return {"question": "What remains?", "capture_token": "server-owned-capability", "marker": value["turns"][-1]["text"],
                **({"no_new_run": True} if value.get("capture_token") and self.no_new_run else {}),
                "speech_authorization": {"approved": True, "text": "What remains?", "kind": "question", "revision": "private"}}

    def workflow(self, value):
        self.graphs.append(copy.deepcopy(value))
        if self.graph_gate:
            self.graph_gate.wait(3)
        if self.graph_fail:
            raise APIError("Private workflow failure")
        return {"workflow": {"steps": [{"id": "reported"}]}}


class ConcurrentContracts(unittest.TestCase):
    def test_discard_cancels_active_jobs_and_drops_the_queued_revision(self):
        gate = threading.Event()
        client = FakeClient(gate)
        client.graph_gate = gate
        cancelled = []
        client.coordinator.cancel = cancelled.append
        service = self.service(client)
        self.addCleanup(gate.set)
        initial = service.turn(payload())
        token = initial["conversation_token"]
        session = service._sessions[token]
        wait_for(lambda: client.captures and client.graphs)
        newer = {**payload(), "conversation_token": token}
        newer["turns"] = [*newer["turns"], {"id": "added", "role": "user", "text": "Another fictional step."}]
        service.turn(newer)
        service.discard(token)
        service.discard(token)
        gate.set()
        wait_for(lambda: not session["running"] and not session["graph_running"])
        self.assertNotIn(token, service._sessions)
        self.assertEqual(len(client.captures), 1)
        self.assertEqual(len(client.graphs), 1)
        self.assertIn(client.captures[0]["agent_run_id"], cancelled)
        self.assertIn(client.graphs[0]["agent_run_id"], cancelled)
        with self.assertRaises(APIError):
            service._queue(session, newer)

    def test_compact_status_checks_revision_scope_and_server_owned_sources(self):
        validated = []
        service = self.service(validate_sources=lambda snapshot: validated.append(snapshot.copy()) or True)
        original = {**payload(), "document_scope": "private-scope"}
        result = service.turn(original)
        query = {key: result[key] for key in ("conversation_token", "revision")}
        query["document_scope"] = original["document_scope"]
        self.assertEqual(service.status_for_revision(query)["revision"], result["revision"])
        self.assertEqual(validated[-1]["turns"], original["turns"])
        for field, wrong, status in (("conversation_token", "a"*64, 409), ("revision", "old", 409),
                                     ("document_scope", "other-scope", 403)):
            with self.subTest(field=field), self.assertRaises(server.APIError) as caught:
                service.status_for_revision({**query, field: wrong})
            self.assertEqual(caught.exception.status, status)

    def service(self, client=None, **kwargs):
        instance = module.ConcurrentInterview(client or FakeClient(), API, **kwargs)
        self.addCleanup(instance.close)
        return instance

    def test_question_does_not_wait_for_capture_or_map(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient(gate)
        service = self.service(client)
        response = service.turn(payload())
        self.assertTrue(client.started.wait(1))
        self.assertEqual(response["question"], client.question)
        self.assertTrue(response["preserve_capture"])
        self.assertFalse(response["completion"]["complete"])
        wait_for(lambda: len(client.graphs) == 1)
        self.assertEqual(service.status({**payload(), "conversation_token": response["conversation_token"]})["state"], "working")

    def test_team_status_uses_actual_server_owned_capture_and_workflow_runs(self):
        capture_gate, graph_gate = threading.Event(), threading.Event()
        self.addCleanup(capture_gate.set)
        self.addCleanup(graph_gate.set)
        client = FakeClient(capture_gate)
        client.graph_gate = graph_gate
        client.coordinator.status = lambda run_id, scope: {"run_id": run_id, "status": "working", "agents": []}
        service = self.service(client)
        first = service.turn({**payload(), "agent_run_id": "browser-controlled"})
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        self.assertTrue(client.started.wait(1))
        capture_id = client.captures[0]["agent_run_id"]
        self.assertNotEqual(capture_id, "browser-controlled")
        self.assertEqual(service.status(snapshot)["agent_team"]["run_id"], capture_id)
        capture_gate.set()
        wait_for(lambda: len(client.graphs) == 1)
        graph_id = client.graphs[0]["agent_run_id"]
        self.assertNotEqual(graph_id, capture_id)
        wait_for(lambda: service.status(snapshot)["state"] == "ready")
        self.assertEqual(service.status(snapshot)["agent_team"]["run_id"], graph_id)
        graph_gate.set()

    def test_pending_answers_coalesce_and_old_result_cannot_publish(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient(gate)
        service = self.service(client)
        first = service.turn(payload("First answer"))
        self.assertTrue(client.started.wait(1))
        second = {**payload("Second answer"), "conversation_token": first["conversation_token"]}
        service.turn(second)
        third = {**payload("Corrected latest answer"), "conversation_token": first["conversation_token"]}
        service.turn(third)
        gate.set()
        wait_for(lambda: service.status(third).get("capture", {}).get("marker") == "Corrected latest answer")
        self.assertEqual([item["turns"][-1]["text"] for item in client.captures], ["First answer", "Corrected latest answer"])
        self.assertNotIn("capture", service.status(second))
        wait_for(lambda: service.status(third)["workflow_state"] == "ready")
        self.assertEqual(client.graphs[-1]["turns"][-1]["text"], "Corrected latest answer")

    def test_slow_obsolete_workflow_does_not_delay_next_capture(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient()
        client.graph_gate = gate
        service = self.service(client)
        first = service.turn(payload("First account"))
        wait_for(lambda: len(client.graphs) == 1)
        next_snapshot = {**payload("Correction: manager receives the invoice."),
                         "conversation_token": first["conversation_token"]}
        service.turn(next_snapshot)
        wait_for(lambda: service.status(next_snapshot).get("capture", {}).get("marker") == "Correction: manager receives the invoice.")
        self.assertEqual(len(client.graphs), 1)
        self.assertNotIn("workflow_capture", service.status(next_snapshot))
        self.assertEqual(service.status(next_snapshot)["workflow_state"], "queued")
        gate.set()
        wait_for(lambda: service.status(next_snapshot).get("workflow_state") == "ready")
        self.assertEqual(len(client.graphs), 2)

    def test_newly_spoken_question_does_not_obsolete_analysis(self):
        service = self.service()
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["state"] == "ready")
        snapshot["turns"].append({"id": "a2", "role": "assistant", "text": first["question"]})
        self.assertIn("capture", service.status(snapshot))
        snapshot["turns"][0]["text"] = "Correction: the manager receives it."
        self.assertNotIn("capture", service.status(snapshot))

    def test_document_retrieval_selection_is_pinned_without_granting_scope(self):
        service = self.service()
        original = {**payload(), "document_scope": "private-scope", "document_revision": "one",
                    "_conversation_document_snapshot": ("private-scope", "original query", ["chunk1"], {}, "binding")}
        response = service.turn(original)
        later = {**original, "conversation_token": response["conversation_token"], "document_source_ids": ["new-memo-citation"]}
        later["turns"] = copy.deepcopy(original["turns"]) + [{"id": "a2", "role": "assistant", "text": response["question"]}]
        self.assertEqual(service.retrieval_basis(later), {"query": "original query", "source_ids": ["chunk1"]})
        self.assertIsNone(service.retrieval_basis({**later, "document_scope": "other-scope"}))
        self.assertIsNone(service.retrieval_basis({**later, "document_revision": "replaced-file"}))

    def test_pinned_retrieval_selection_keeps_the_files_it_asked_for(self):
        service = self.service()
        options = {"required_documents": ["doc_unread"]}
        original = {**payload(), "document_scope": "private-scope", "document_revision": "one",
                    "_conversation_document_snapshot": ("private-scope", "original query", ["chunk1"], {}, "binding", options)}
        response = service.turn(original)
        later = {**original, "conversation_token": response["conversation_token"], "document_required_ids": []}
        later["turns"] = copy.deepcopy(original["turns"]) + [{"id": "a2", "role": "assistant", "text": response["question"]}]
        basis = service.retrieval_basis(later)
        self.assertEqual(basis, {"query": "original query", "source_ids": ["chunk1"], "options": options})
        basis["options"]["required_documents"].append("doc_changed")
        self.assertEqual(service.retrieval_basis(later)["options"], options)
        plain = {**original, "_conversation_document_snapshot": ("private-scope", "original query", ["chunk1"], {}, "binding", {})}
        plain.pop("conversation_token", None)
        response = service.turn(plain)
        self.assertEqual(service.retrieval_basis({**plain, "conversation_token": response["conversation_token"]}),
                         {"query": "original query", "source_ids": ["chunk1"]})

    def test_sync_waits_for_current_capture_and_preserves_authoritative_question(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        service = self.service(FakeClient(gate))
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        answer = []
        thread = threading.Thread(target=lambda: answer.append(service.sync(snapshot)))
        thread.start()
        time.sleep(.025)
        self.assertFalse(answer)
        gate.set()
        thread.join(1)
        self.assertEqual(answer[0]["capture_token"], "server-owned-capability")
        self.assertEqual(answer[0]["question"], "What remains?")

    def test_review_request_requires_sync_and_has_no_speech_permission(self):
        client = FakeClient()
        client.request_review = True
        result = self.service(client).turn(payload())
        self.assertTrue(result["sync_required"])
        self.assertNotIn("speech_authorization", result)

    def test_sync_rebases_ticket_after_fast_question_was_appended(self):
        client = FakeClient()
        service = self.service(client)
        response = service.turn(payload())
        snapshot = {**payload(), "conversation_token": response["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["state"] == "ready")
        snapshot["turns"].append({"id": "a2", "role": "assistant", "text": response["question"]})
        synchronized = service.sync(snapshot)
        self.assertEqual(client.captures[-1]["turns"], snapshot["turns"])
        self.assertEqual(synchronized["marker"], response["question"])
        self.assertEqual(len(client.captures), 2)

    def test_final_confirmation_bypasses_new_background_capture(self):
        client = FakeClient()
        service = self.service(client)
        response = service.turn(payload())
        snapshot = {**payload(), "conversation_token": response["conversation_token"]}
        # Let the already scheduled graph finish before counting NEW work.
        wait_for(lambda: service.status(snapshot)["state"] == "ready" and
                 service.status(snapshot)["workflow_state"] == "ready")
        session = service._sessions[response["conversation_token"]]
        session["synchronized"] = {"speech_authorization": {"kind": "final_check"}}
        snapshot["turns"] += [{"id": "af", "role": "assistant", "text": "Anything else?"},
                              {"id": "uf", "role": "user", "text": "No, that is everything."}]
        snapshot["capture_token"] = "coordinator-capability"
        client.no_new_run = True
        before = len(client.captures)
        before_graphs = len(client.graphs)
        self.assertTrue(service.turn(snapshot)["sync_required"])
        self.assertEqual(len(client.captures), before)
        service.sync(snapshot)
        self.assertEqual(len(client.captures), before + 1)
        self.assertEqual(client.captures[-1]["capture_token"], "coordinator-capability")
        self.assertEqual(len(client.graphs), before_graphs)

    def test_sync_waits_for_current_workflow_and_returns_it(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient()
        client.graph_gate = gate
        service = self.service(client)
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["state"] == "ready")
        answers = []
        thread = threading.Thread(target=lambda: answers.append(service.sync(snapshot)))
        thread.start()
        time.sleep(.025)
        self.assertFalse(answers)
        gate.set()
        thread.join(1)
        self.assertEqual(answers[0]["workflow_capture"], {"workflow": {"steps": [{"id": "reported"}]}})

    def test_sync_failed_workflow_gets_one_retry_and_releases_the_notes(self):
        # Finding 3 of docs/testing/process-capture-2026-11-16: a failed map used to fail Wrap up
        # (HTTP 502 or 504) although the notes were there. The notes are what a review reads; the
        # map keeps its own status and retry and never holds them back.
        client = FakeClient()
        client.graph_fail = True
        service = self.service(client)
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["workflow_state"] == "error")
        result = service.sync(snapshot)
        # One explicit retry of the failed map, never a paid loop.
        self.assertEqual(len(client.graphs), 2)
        self.assertEqual(result["marker"], snapshot["turns"][-1]["text"])
        self.assertNotIn("workflow_capture", result)
        self.assertEqual((result["workflow_state"], result["workflow_pending"]), ("error", False))
        self.assertEqual(result["workflow_error"], "The workflow could not update. Your answers are retained.")
        self.assertNotIn("Private", str(result))
        # The synchronized notes are available for review and the transcript is untouched.
        self.assertEqual(service._sessions[first["conversation_token"]]["synchronized"]["marker"], result["marker"])
        self.assertEqual(service.status(snapshot)["capture"]["marker"], result["marker"])
        # A further Wrap up may retry the map once more; when it then succeeds it is returned.
        client.graph_fail = False
        again = service.sync(snapshot)
        self.assertEqual(again["workflow_capture"], {"workflow": {"steps": [{"id": "reported"}]}})
        self.assertEqual((again["workflow_state"], again["workflow_pending"]), ("ready", False))
        self.assertEqual(len(client.graphs), 3)

    def test_sync_does_not_wait_for_a_slow_workflow_which_arrives_through_its_own_status(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient()
        client.graph_gate = gate
        service = self.service(client)
        service.map_wait = .05
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["state"] == "ready")
        started = time.monotonic()
        result = service.sync(snapshot)
        self.assertLess(time.monotonic() - started, 1, "Wrap up must not wait for a map that is still being drawn")
        self.assertEqual(result["marker"], snapshot["turns"][-1]["text"])
        self.assertNotIn("workflow_capture", result)
        self.assertIn(result["workflow_state"], ("queued", "working"))
        self.assertIs(result["workflow_pending"], True)
        self.assertNotIn("workflow_error", result)
        self.assertEqual(len(client.graphs), 1, "The map already being drawn is not started a second time")
        # The map keeps its own status: the poll of this revision delivers it when it arrives.
        query = {"conversation_token": result["conversation_token"], "revision": result["revision"]}
        self.assertIn(service.status_for_revision(query)["workflow_state"], ("queued", "working"))
        gate.set()
        wait_for(lambda: service.status_for_revision(query)["workflow_state"] == "ready")
        status = service.status_for_revision(query)
        self.assertEqual(status["workflow_capture"], {"workflow": {"steps": [{"id": "reported"}]}})
        self.assertEqual(status["capture"]["marker"], result["marker"])

    def test_sync_with_a_capability_releases_notes_and_serves_the_late_map_of_that_revision(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient()
        service = self.service(client)
        service.map_wait = .05
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["state"] == "ready" and service.status(snapshot)["workflow_state"] == "ready")
        # A correction after an earlier review: the browser holds a capability and the account changed.
        client.graph_gate = gate
        corrected = copy.deepcopy(snapshot)
        corrected["turns"] += [{"id": "a2", "role": "assistant", "text": "What remains?"},
                               {"id": "u2", "role": "user", "text": "The manager approves it first."}]
        corrected.update(capture_token="coordinator-capability", action="close")
        result = service.sync(corrected)
        self.assertEqual(result["marker"], "The manager approves it first.")
        self.assertNotIn("workflow_capture", result)
        self.assertIs(result["workflow_pending"], True)
        query = {"conversation_token": result["conversation_token"], "revision": result["revision"]}
        self.assertIn(service.status_for_revision(query)["workflow_state"], ("queued", "working"))
        gate.set()
        wait_for(lambda: service.status_for_revision(query)["workflow_state"] == "ready")
        self.assertIn("workflow_capture", service.status_for_revision(query))
        self.assertEqual(client.graphs[-1]["turns"][-1]["text"], "The manager approves it first.")

    def test_one_session_waiting_for_its_map_does_not_hold_up_wrap_up_in_another(self):
        # One map is drawn at a time across sessions. A second interview's Wrap up used to wait
        # behind the first one's map until its own request timed out.
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient()
        client.graph_gate = gate
        service = self.service(client)
        service.map_wait = .05
        first = service.turn(payload("The clerk receives the invoice."))
        second = service.turn(payload("The buyer raises a purchase order."))
        one = {**payload("The clerk receives the invoice."), "conversation_token": first["conversation_token"]}
        two = {**payload("The buyer raises a purchase order."), "conversation_token": second["conversation_token"]}
        wait_for(lambda: service.status(one)["state"] == "ready" and service.status(two)["state"] == "ready")
        wait_for(lambda: len(client.graphs) == 1)
        started = time.monotonic()
        results = [service.sync(one), service.sync(two)]
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual([item["marker"] for item in results],
                         ["The clerk receives the invoice.", "The buyer raises a purchase order."])
        self.assertEqual([item["workflow_pending"] for item in results], [True, True])
        self.assertEqual(len(client.graphs), 1, "The second map waits its turn in the background")
        gate.set()
        for item in results:
            query = {"conversation_token": item["conversation_token"], "revision": item["revision"]}
            wait_for(lambda: service.status_for_revision(query)["workflow_state"] == "ready")
            self.assertIn("workflow_capture", service.status_for_revision(query))
        self.assertEqual(len(client.graphs), 2)

    # Finding 4 of docs/testing/process-capture-2026-11-16: the first question after a file is
    # added is asked from the file's own excerpts at once; the notes and the audited map of the
    # same revision are completed in the background. Finding 5: that question never fails on
    # what a model returned, and falls back to a question bound to a verified excerpt.
    FILE = {"id": "doc_fee", "name": "Monitoring fee.csv", "review": {"phase": "complete"},
            "excerpts": [{"id": "doc_fee_r1_c1", "text": "Review the monitoring-fee schedule before quarter end."}],
            "questions": [{"text": "What happens to the monitoring-fee schedule after that review?",
                           "sources": [{"source_id": "doc_fee_r1_c1", "label": "Monitoring fee.csv · row 1"}]}]}

    def file_payload(self, **changes):
        return {"context": {"process_name": "Monitoring fees"},
                "turns": [{"id": "doc_intake", "role": "assistant", "text": "Thanks for sharing.", "document_event": True}],
                "_supporting_documents": {"documents": [copy.deepcopy(self.FILE)]},
                "document_required_ids": ["doc_fee"], "action": "document_followup", **changes}

    def test_file_followup_asks_from_the_excerpts_at_once_and_maps_the_file_in_the_background(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient(gate)
        client.graph_gate = gate
        client.question = "The document describes a schedule review before quarter end. What happens to the schedule after that review?"
        service = self.service(client)
        started = time.monotonic()
        result = service.turn(self.file_payload())
        self.assertLess(time.monotonic() - started, 1, "The file question must not wait for notes or the map")
        self.assertEqual(result["question"], client.question)
        self.assertFalse(result["sync_required"])
        self.assertEqual(result["speech_authorization"]["text"], client.question)
        sent = client.questions[0]
        self.assertEqual(sent["action"], "document_followup")
        self.assertEqual(sent["supporting_documents"]["documents"][0]["excerpts"][0]["id"], "doc_fee_r1_c1")
        # A file alone describes a process: its notes and its map are queued for this revision.
        wait_for(lambda: client.captures and client.graphs)
        self.assertTrue(client.graphs[0]["_map_only"])
        snapshot = {**self.file_payload(), "conversation_token": result["conversation_token"]}
        self.assertEqual(service.status(snapshot)["workflow_state"], "working")
        gate.set()
        wait_for(lambda: service.status(snapshot)["state"] == "ready" and service.status(snapshot)["workflow_state"] == "ready")
        self.assertIn("workflow_capture", service.status(snapshot))

    def test_file_followup_policy_grounds_the_question_and_other_turns_do_not_receive_it(self):
        self.assertIn("FILE FOLLOW-UP", module.question_policy(API, True))
        self.assertIn("take every one of them", module.question_policy(API, True))
        self.assertNotIn("FILE FOLLOW-UP", module.question_policy(API))
        instructions = []
        client = FakeClient()
        original = client.structured
        client.structured = lambda text, *rest, **options: instructions.append(text) or original(text, *rest, **options)
        service = self.service(client)
        service.turn(self.file_payload())
        service.turn(payload())
        self.assertIn("FILE FOLLOW-UP", instructions[0])
        self.assertNotIn("FILE FOLLOW-UP", instructions[1])

    def test_file_followup_never_fails_or_closes_on_the_models_reply(self):
        fallback = self.FILE["questions"][0]["text"]
        cases = {"provider failure": lambda client: setattr(client, "structured", lambda *args, **kwargs: (_ for _ in ()).throw(APIError("Private provider detail", 504))),
                 "malformed reply": lambda client: setattr(client, "structured", lambda *args, **kwargs: {"question": 7}),
                 "review requested": lambda client: setattr(client, "request_review", True),
                 "closing wording": lambda client: setattr(client, "question", "That covers everything, so we are done here."),
                 "no question": lambda client: setattr(client, "question", "The file is clear.")}
        for name, arrange in cases.items():
            with self.subTest(reply=name):
                client = FakeClient()
                arrange(client)
                result = self.service(client).turn(self.file_payload())
                self.assertEqual(result["question"], fallback, "The fallback is the review's question bound to a supplied excerpt")
                self.assertFalse(result["sync_required"])
                self.assertEqual(result["speech_authorization"]["text"], fallback)
                self.assertNotIn("Private", str(result))

    def test_file_fallback_question_is_bound_to_a_supplied_excerpt_and_never_repeats(self):
        service = self.service(FakeClient())
        turns = self.file_payload()["turns"]
        unbound = self.file_payload()
        unbound["_supporting_documents"]["documents"][0]["questions"][0]["sources"] = [{"source_id": "doc_fee_r9_c1"}]
        self.assertEqual(service._file_question(unbound, turns), module.FILE_QUESTION_FALLBACK,
                         "A question whose source was not supplied is not asked")
        asked = turns + [{"id": "a1", "role": "assistant", "text": self.FILE["questions"][0]["text"]}]
        self.assertEqual(service._file_question(self.file_payload(), asked), module.FILE_QUESTION_FALLBACK)
        # The files this intake added are tried before files read earlier.
        both = self.file_payload()
        earlier = {"id": "doc_old", "name": "Old.csv", "excerpts": [{"id": "doc_old_r1_c1", "text": "Old."}],
                   "questions": [{"text": "Who approves the old schedule?", "sources": [{"source_id": "doc_old_r1_c1"}]}]}
        both["_supporting_documents"]["documents"].insert(0, earlier)
        self.assertEqual(service._file_question(both, turns), self.FILE["questions"][0]["text"])
        closing = self.file_payload()
        closing["_supporting_documents"]["documents"][0]["questions"][0]["text"] = "Is there anything we have not covered?"
        self.assertEqual(service._file_question(closing, turns), module.FILE_QUESTION_FALLBACK)

    def test_an_ordinary_answer_still_reports_a_failed_question(self):
        client = FakeClient()
        client.structured = lambda *args, **kwargs: (_ for _ in ()).throw(APIError("Synthetic failure", 504))
        with self.assertRaises(APIError):
            self.service(client).turn(payload())

    def test_source_correction_while_sync_waits_cannot_release_old_workflow(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient()
        client.graph_gate = gate
        service = self.service(client)
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["state"] == "ready")
        errors = []
        def synchronize():
            try:
                service.sync(snapshot)
            except APIError as error:
                errors.append(error)
        thread = threading.Thread(target=synchronize)
        thread.start()
        time.sleep(.025)
        service.turn({**payload("Corrected account"), "conversation_token": first["conversation_token"]})
        thread.join(1.5)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].status, 409)
        gate.set()

    def test_sync_without_prior_fast_turn_can_restore_interview(self):
        service = self.service()
        result = service.sync(payload())
        self.assertEqual(len(result["conversation_token"]), 64)
        self.assertEqual(result["question"], "What remains?")

    def test_question_cannot_announce_completion(self):
        client = FakeClient()
        client.question = "Is there anything else you would like to add before we finish?"
        result = self.service(client).turn(payload())
        # Closing wording is still never spoken, but it no longer fails the turn:
        # the participant gets a neutral question from the single provider call.
        self.assertEqual(result["question"], "What happens next in this work?")
        self.assertEqual(result["speech_authorization"]["text"], result["question"])
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertFalse(result["sync_required"])
        self.assertFalse(result["completion"]["complete"])
        self.assertEqual(len(client.questions), 1)

    def real_stop_service(self, client):
        # The stub above recognises one fixed sentence. These cases run the turn
        # path against the application's actual stop detector.
        from test_server import server

        class RealStopAPI(API):
            participant_requested_stop = staticmethod(server.participant_requested_stop)
        instance = module.ConcurrentInterview(client, RealStopAPI)
        self.addCleanup(instance.close)
        return instance, server

    def test_real_stop_detector_pauses_natural_requests_without_a_question_call(self):
        for text in ("Sorry, I need to stop now.", "I'd like to stop here.", "Okay, let's stop here.",
                     "I have to go, can we stop?", "I need to stop now.\nI have another meeting.",
                     # A firm request with an everyday reason, whatever the punctuation
                     "I need to stop now because I'm not feeling well.", "I need to stop now, my boss is calling.",
                     "Please stop, I need a break.", "Can we stop here and continue tomorrow?"):
            with self.subTest(text=text):
                client = FakeClient()
                service, server = self.real_stop_service(client)
                response = service.turn(payload(text))
                self.assertEqual(response["speech_authorization"]["kind"], "pause")
                self.assertIn(response["question"], server.STOP_ACKNOWLEDGEMENTS)
                self.assertFalse(response["sync_required"])
                self.assertEqual(client.questions, [])

    def test_real_stop_detector_lets_process_answers_reach_the_interviewer(self):
        for text in ("I'm done with this when the bank confirms receipt of the wire.",
                     "I need to stop and check the source file before I release anything.",
                     "Stop and escalate to the fund controller.", "Pause. Let me think about the order.",
                     "Let's finish. The last step is filing.", "We're done with that.", "Stop the call.",
                     "We need to stop now. The custodian cut-off is 4 pm."):
            with self.subTest(text=text):
                client = FakeClient()
                service, _ = self.real_stop_service(client)
                response = service.turn(payload(text))
                self.assertEqual(response["speech_authorization"]["kind"], "question")
                self.assertEqual(response["question"], client.question)
                self.assertEqual(len(client.questions), 1)

    def test_real_stop_detector_answers_a_stop_once(self):
        client = FakeClient()
        service, server = self.real_stop_service(client)
        stopped = payload("I need to stop now.")
        first = service.turn(stopped)
        self.assertEqual(first["speech_authorization"]["kind"], "pause")
        acknowledged = {**stopped, "conversation_token": first["conversation_token"]}
        acknowledged["turns"] = stopped["turns"] + [{"id": "a2", "role": "assistant", "text": first["question"]}]
        for action in ("answer", "skip"):
            with self.subTest(action=action):
                again = service.turn({**acknowledged, "action": action})
                self.assertEqual(again["speech_authorization"]["kind"], "question")
        self.assertEqual(len(client.questions), 2)
        # Wrap up after the acknowledged stop asks for synchronization, not another pause.
        self.assertTrue(service.turn({**acknowledged, "action": "close"})["sync_required"])

    def test_invalid_or_missing_capability_reveals_no_capture(self):
        service = self.service()
        for token in (None, "guessed", "a" * 64):
            with self.assertRaises((APIError, ValueError)):
                service.status({**payload(), "conversation_token": token})

    def test_source_change_prevents_publish_and_exposes_no_provider_error(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        valid = [True]
        client = FakeClient(gate)
        service = self.service(client, validate_sources=lambda value: valid[0])
        response = service.turn(payload())
        self.assertTrue(client.started.wait(1))
        valid[0] = False
        gate.set()
        wait_for(lambda: not service._sessions[response["conversation_token"]]["running"])
        self.assertIsNone(service._sessions[response["conversation_token"]]["capture"])
        with self.assertRaises(APIError):
            service.status({**payload(), "conversation_token": response["conversation_token"]})

    def test_failed_analysis_has_one_explicit_retry_not_paid_loop(self):
        client = FakeClient()
        client.fail = True
        service = self.service(client)
        response = service.turn(payload())
        snapshot = {**payload(), "conversation_token": response["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["state"] == "error")
        self.assertNotIn("Private", service.status(snapshot)["error"])
        with self.assertRaises(APIError):
            service.sync(snapshot, timeout=.5)
        self.assertEqual(len(client.captures), 2)

    def test_shutdown_blocks_late_publication(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        client = FakeClient(gate)
        service = self.service(client)
        response = service.turn(payload())
        self.assertTrue(client.started.wait(1))
        service.close()
        gate.set()
        wait_for(lambda: not service._sessions[response["conversation_token"]]["running"])
        self.assertIsNone(service._sessions[response["conversation_token"]]["capture"])

    def test_session_bound_prevents_unlimited_waiting_workers(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        service = self.service(FakeClient(gate), max_sessions=1, workers=1)
        service.turn(payload())
        with self.assertRaises(APIError) as error:
            service.turn(payload("Another interview"))
        self.assertEqual(error.exception.status, 429)


if __name__ == "__main__":
    unittest.main()
