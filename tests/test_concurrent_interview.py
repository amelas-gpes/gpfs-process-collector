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


class APIError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class API:
    APIError = APIError
    ordinary_question_allowed = staticmethod(server.ordinary_question_allowed)
    fallback_interview_question = staticmethod(server.fallback_interview_question)

    @staticmethod
    def validate_payload(payload):
        if not isinstance(payload.get("context"), dict) or not isinstance(payload.get("turns"), list):
            raise ValueError("Invalid snapshot")
        return payload["context"], payload["turns"]

    @staticmethod
    def participant_requested_stop(turns):
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
        self.assertEqual(client.graphs, [])
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
        wait_for(lambda: len(client.graphs) == 1)
        self.assertEqual(len(client.graphs), 1)

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

    def test_sync_failed_workflow_gets_one_retry_and_blocks_final_review(self):
        client = FakeClient()
        client.graph_fail = True
        service = self.service(client)
        first = service.turn(payload())
        snapshot = {**payload(), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot)["workflow_state"] == "error")
        with self.assertRaisesRegex(APIError, "workflow review could not finish"):
            service.sync(snapshot)
        self.assertEqual(len(client.graphs), 2)
        self.assertIsNone(service._sessions[first["conversation_token"]]["synchronized"])
        client.graph_fail = False
        result = service.sync(snapshot)
        self.assertIn("workflow_capture", result)
        self.assertEqual(len(client.graphs), 3)

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

    def test_fast_question_recovers_from_premature_completion_and_compound_prompts(self):
        for line in ("Are we all done?", "The interview is complete. Who should receive the notes?",
                     "Who owns it? Who approves it?"):
            with self.subTest(line=line):
                client = FakeClient()
                client.question = line
                result = self.service(client).turn(payload())
                self.assertNotEqual(result["question"], line)
                self.assertTrue(server.ordinary_question_allowed(result["question"]))
                self.assertEqual(result["speech_authorization"]["text"], result["question"])
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual(len(client.questions), 1)

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
