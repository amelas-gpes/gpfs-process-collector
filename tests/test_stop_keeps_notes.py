"""A stop or pause request on the typed/reviewed path must never cost the notes.

The Coordinator answers a stop request with a pause reply that carries no notes.
These tests run the real Coordinator, the real stop detector and the real
ConcurrentInterview against schema-routed offline models: no provider access.
"""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_concurrent_http import ConversationProvider
from test_interview_orchestrator import SyntheticTeamProvider
from test_server import server

concurrent = server.local_module("concurrent_interview", "concurrent_interview.py")
STOP = "I need to stop now."


def capture_calls(client):
    return [call.args[1]["text"]["format"]["name"] for call in client.request.call_args_list
            if call.args[0] == "responses"].count("team_interview_capture")


def settled(read, seconds=10):
    """Poll until both background products have finished for this snapshot."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = read()
        if status["state"] in ("ready", "error") and status["workflow_state"] in ("ready", "error"):
            return status
        time.sleep(.01)
    raise AssertionError("Background analysis did not settle")


def after(snapshot, question, text, turn_id):
    value = copy.deepcopy(snapshot)
    value["turns"] += [{"id": "a_" + turn_id, "role": "assistant", "text": question},
                       {"id": "u_" + turn_id, "role": "user", "text": text}]
    return value


class StopOnTheConcurrentPath(unittest.TestCase):
    def setUp(self):
        self.client = ConversationProvider()
        self.client.incomplete()
        self.service = concurrent.ConcurrentInterview(self.client, server)
        self.addCleanup(self.service.close)

    def status(self, snapshot):
        return settled(lambda: self.service.status(copy.deepcopy(snapshot)))

    def captured(self):
        """One ordinary answer, analysed: sixteen topics of notes are published."""
        payload = self.client.payload()
        first = self.service.turn(copy.deepcopy(payload))
        snapshot = {**payload, "conversation_token": first["conversation_token"]}
        ready = self.status(snapshot)
        self.assertEqual(len(ready["capture"]["memo_findings"]), len(server.COVERAGE))
        return snapshot, first, ready

    def stopped(self):
        snapshot, first, ready = self.captured()
        stop = after(snapshot, first["question"], STOP, "stop")
        reply = self.service.turn(copy.deepcopy(stop))
        self.assertEqual(reply["speech_authorization"]["kind"], "pause")
        self.assertNotIn("?", reply["question"])
        return stop, reply, ready

    def test_status_after_a_stop_never_publishes_the_pause_reply_as_notes(self):
        stop, reply, ready = self.stopped()
        status = self.status(stop)
        self.assertEqual(status["state"], "ready")
        self.assertNotIn("error", status)
        # Nothing memo-less may ever reach the browser under the name "capture".
        self.assertNotIn("capture", status)
        self.assertIs(status.get("capture_preserved"), True)
        session = self.service._sessions[stop["conversation_token"]]
        self.assertEqual(session["capture"]["memo_findings"], ready["capture"]["memo_findings"])
        self.assertEqual(session["capture"]["summary"], ready["capture"]["summary"])
        self.assertNotIn("preserve_capture", session["capture"])

    def test_notes_still_guide_the_next_question_after_a_stop(self):
        stop, reply, _ = self.stopped()
        self.status(stop)
        asked = []
        self.client.hooks["conversation_question"] = lambda body: asked.append(json.loads(body["input"][0]["content"]))
        resumed = after(stop, reply["question"], "The treasury analyst releases the payment run.", "resume")
        self.service.turn(copy.deepcopy(resumed))
        advice = asked[-1]["analysis_advice"]
        self.assertTrue(advice["available"])
        self.assertEqual(len(advice["topics"]), len(server.COVERAGE))
        # The advice still states its own age: everything from the stop onwards is unreviewed.
        self.assertEqual(advice["unreviewed_turn_ids"], ["a_stop", "u_stop", "a_resume", "u_resume"])
        # The further answer is analysed as usual: full notes are published again.
        status = self.status(resumed)
        self.assertEqual(len(status["capture"]["memo_findings"]), len(server.COVERAGE))
        self.assertNotIn("capture_preserved", status)

    def test_stop_as_the_very_first_answer_settles_without_notes_or_error(self):
        payload = self.client.payload()
        payload["turns"] = [{"id": "a1", "role": "assistant", "text": "What starts this work?"},
                            {"id": "u1", "role": "user", "text": STOP}]

        def nothing_to_map(result):
            # What a map model returns for an account that holds no process yet. The
            # canned map cites turns of the long fixture transcript, which are not here.
            result.update(upsert_steps=[], summary="", parking_lot=[],
                          memo_findings=[{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                                         for key in server.COVERAGE])
        self.client.result_changes["team_working_process_map"] = nothing_to_map
        reply = self.service.turn(copy.deepcopy(payload))
        self.assertEqual(reply["speech_authorization"]["kind"], "pause")
        status = self.status({**payload, "conversation_token": reply["conversation_token"]})
        self.assertEqual(status["state"], "ready")
        self.assertNotIn("capture", status)
        self.assertNotIn("error", status)
        self.assertIs(status.get("capture_preserved"), True)
        # Neither background product may end in the state the browser shows as
        # "Notes need attention".
        self.assertEqual(status["workflow_state"], "ready")
        self.assertNotIn("workflow_error", status)
        self.assertEqual(capture_calls(self.client), 0)

    def test_a_second_stop_keeps_the_same_notes(self):
        stop, reply, ready = self.stopped()
        self.status(stop)
        again = after(stop, reply["question"], "Please stop.", "again")
        self.assertEqual(self.service.turn(copy.deepcopy(again))["speech_authorization"]["kind"], "pause")
        status = self.status(again)
        self.assertNotIn("capture", status)
        self.assertIs(status.get("capture_preserved"), True)
        session = self.service._sessions[stop["conversation_token"]]
        self.assertEqual(session["capture"]["memo_findings"], ready["capture"]["memo_findings"])

    def test_stop_that_overtakes_a_running_capture_keeps_its_last_answer_as_a_checkpoint(self):
        snapshot, first, ready = self.captured()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold(_body):
            entered.set()
            release.wait(5)
        self.client.hooks["team_interview_capture"] = hold
        second = after(snapshot, first["question"], "The buyer resolves mismatched invoices.", "two")
        question = self.service.turn(copy.deepcopy(second))["question"]
        self.assertTrue(entered.wait(3))
        stop = after(second, question, STOP, "stop")
        self.assertEqual(self.service.turn(copy.deepcopy(stop))["speech_authorization"]["kind"], "pause")
        del self.client.hooks["team_interview_capture"]
        release.set()
        status = self.status(stop)
        self.assertEqual(status["state"], "ready")
        self.assertNotIn("capture", status)
        self.assertIs(status.get("capture_preserved"), True)
        session = self.service._sessions[stop["conversation_token"]]
        self.assertNotEqual(session["capture"]["capture_token"], ready["capture"]["capture_token"])
        self.assertEqual(status["checkpoint"]["capture"], session["capture"])
        self.assertEqual(status["checkpoint"]["through_turn_id"], "u_two")
        self.assertEqual(status["checkpoint"]["turns"], second["turns"])

    def test_stop_in_reply_to_the_final_check_settles_without_queued_work(self):
        snapshot, first, _ = self.captured()
        session = self.service._sessions[snapshot["conversation_token"]]
        session["synchronized"] = {"speech_authorization": {"kind": "final_check"}}
        stop = after(snapshot, server.FINAL_CHECK_PREFIX + " we missed?", STOP, "stop")
        reply = self.service.turn(copy.deepcopy(stop))
        self.assertEqual(reply["speech_authorization"]["kind"], "pause")
        self.assertFalse(reply["sync_required"])
        status = self.service.status(copy.deepcopy(stop))
        self.assertEqual(status["state"], "ready")
        self.assertNotIn("capture", status)
        self.assertIs(status.get("capture_preserved"), True)
        # Nothing queued a map for this revision either. A Wrap up that carries no
        # capture token must get one made, not wait out its deadline for it.
        wrap = copy.deepcopy(stop)
        wrap["turns"].append({"id": "a_ack", "role": "assistant", "text": reply["question"]})
        wrap["action"] = "close"
        started = time.monotonic()
        result = self.service.sync(wrap, timeout=4)
        self.assertLess(time.monotonic() - started, 3.5)
        self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
        self.assertEqual(len(result["memo_findings"]), len(server.COVERAGE))
        self.assertIn("workflow_capture", result)

    def test_skip_after_a_stop_asks_the_next_question_and_the_next_answer_is_analysed(self):
        # As docs/CONCURRENT_INTERVIEW.md states: Skip is answered with a question, not
        # the pause reply; the pause reply it follows adds no evidence, so nothing is
        # captured and nothing memo-less is published until the participant answers.
        stop, reply, ready = self.stopped()
        self.status(stop)
        before = capture_calls(self.client)
        skip = copy.deepcopy(stop)
        skip["turns"].append({"id": "a_ack", "role": "assistant", "text": reply["question"]})
        skip["action"] = "skip"
        again = self.service.turn(copy.deepcopy(skip))
        self.assertEqual(again["speech_authorization"]["kind"], "question")
        self.assertTrue(again["question"].endswith("?"))
        status = self.status(skip)
        self.assertEqual(status["state"], "ready")
        self.assertNotIn("capture", status)
        self.assertIs(status.get("capture_preserved"), True)
        self.assertEqual(capture_calls(self.client), before)
        session = self.service._sessions[stop["conversation_token"]]
        self.assertEqual(session["capture"]["memo_findings"], ready["capture"]["memo_findings"])
        answered = after(skip, again["question"], "The treasury analyst releases the payment run.", "next")
        answered.pop("action")
        self.service.turn(copy.deepcopy(answered))
        status = self.status(answered)
        self.assertNotIn("capture_preserved", status)
        self.assertEqual(len(status["capture"]["memo_findings"]), len(server.COVERAGE))
        self.assertEqual(capture_calls(self.client), before + 1)

    def test_status_after_wrap_up_publishes_the_new_notes_not_the_pause(self):
        stop, reply, _ = self.stopped()
        self.status(stop)
        wrap = copy.deepcopy(stop)
        wrap["turns"].append({"id": "a_ack", "role": "assistant", "text": reply["question"]})
        wrap["action"] = "close"
        result = self.service.sync(copy.deepcopy(wrap), timeout=10)
        status = self.service.status(copy.deepcopy(wrap))
        self.assertNotIn("capture_preserved", status)
        self.assertEqual(status["capture"]["capture_token"], result["capture_token"])
        self.assertNotIn("preserve_capture", status["capture"])

    def test_wrap_up_after_a_stop_runs_a_real_capture(self):
        stop, reply, _ = self.stopped()
        self.status(stop)
        before = capture_calls(self.client)
        wrap = copy.deepcopy(stop)
        wrap["turns"].append({"id": "a_ack", "role": "assistant", "text": reply["question"]})
        wrap["action"] = "close"
        result = self.service.sync(wrap, timeout=10)
        self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
        self.assertIsNot(result.get("preserve_capture"), True)
        self.assertEqual(len(result["memo_findings"]), len(server.COVERAGE))
        self.assertTrue(any(item["status"] != "unknown" for item in result["memo_findings"]))
        self.assertIn("capture_token", result)
        self.assertEqual(capture_calls(self.client), before + 1)

    def test_wrap_up_on_a_reopened_interview_that_ends_with_a_stop_request(self):
        # A saved file is re-opened in a new server session; its last participant
        # turn is the stop request and the pause reply never made it into the file.
        payload = after(self.client.payload(), "What happens after the invoice is logged?", STOP, "stop")
        payload["action"] = "close"
        result = self.service.sync(copy.deepcopy(payload), timeout=10)
        self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
        self.assertIsNot(result.get("preserve_capture"), True)
        self.assertEqual(len(result["memo_findings"]), len(server.COVERAGE))
        self.assertEqual(capture_calls(self.client), 1)

    def test_wrap_up_with_an_earlier_capture_token_after_a_stop_runs_a_real_capture(self):
        snapshot, first, _ = self.captured()
        asked = copy.deepcopy(snapshot)
        asked["turns"].append({"id": "a_fast", "role": "assistant", "text": first["question"]})
        earlier = self.service.sync({**copy.deepcopy(asked), "action": "close"}, timeout=10)
        stop = after({**asked, "capture_token": earlier["capture_token"]}, earlier["question"], STOP, "stop")
        reply = self.service.turn(copy.deepcopy(stop))
        self.assertEqual(reply["speech_authorization"]["kind"], "pause")
        self.assertNotIn("capture", self.status(stop))
        wrap = copy.deepcopy(stop)
        wrap["turns"].append({"id": "a_ack", "role": "assistant", "text": reply["question"]})
        wrap["action"] = "close"
        result = self.service.sync(wrap, timeout=10)
        self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
        self.assertEqual(len(result["memo_findings"]), len(server.COVERAGE))
        # The synchronized capture, not a pause reply, is what the session now publishes.
        status = self.service.status(copy.deepcopy(wrap))
        self.assertNotIn("capture_preserved", status)
        self.assertEqual(len(status["capture"]["memo_findings"]), len(server.COVERAGE))


class StopAtTheCoordinator(unittest.TestCase):
    def test_explicit_wrap_up_after_a_stop_captures_instead_of_repeating_the_pause(self):
        for action in ("close", "skip"):
            with self.subTest(action=action):
                client = SyntheticTeamProvider()
                client.incomplete()
                payload = client.payload()
                payload["turns"].append({"id": "u_stop", "role": "user", "text": STOP})
                payload["action"] = action
                result = client.coordinator.interview(payload)
                self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
                self.assertIsNot(result.get("preserve_capture"), True)
                self.assertEqual(len(result["memo_findings"]), len(server.COVERAGE))
                self.assertGreater(client.request.call_count, 0)

    STOP_LINE = "Of course. We can stop here. Your account is retained, with any unfinished sections still open."

    def acknowledged(self, client, text="Can we pause? I want to upload the procedure document first."):
        payload = client.payload()
        payload["turns"] += [{"id": "a_q", "role": "assistant", "text": "What happens after the manager approves?"},
                             {"id": "u_stop", "role": "user", "text": text},
                             {"id": "a_stop", "role": "assistant", "text": self.STOP_LINE}]
        return payload

    def test_acknowledged_stop_is_not_repeated_for_wrap_up_skip_or_another_request(self):
        for action in ("close", "skip", "answer"):
            with self.subTest(action=action):
                client = SyntheticTeamProvider()
                client.incomplete()
                payload = self.acknowledged(client, "Can we pause? I have to leave.")
                payload["action"] = action
                result = client.coordinator.interview(payload)
                self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
                self.assertNotEqual(result["question"], self.STOP_LINE)
                self.assertEqual(len(result["memo_findings"]), len(server.COVERAGE))
                self.assertNotIn("participant_stopped", result["completion"]["blockers"])

    def test_acknowledged_stop_is_not_repeated_for_a_file_follow_up(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        payload = self.acknowledged(client, "Can we pause? I have to leave.")
        excerpt = {"id": "doc_fixture_p1_c1", "label": "Page 1", "location": {"page": 1},
                   "text": "The manager approves invoices over 5,000 in the AP register."}
        payload["_supporting_documents"] = {"documents": [{"id": "doc_fixture", "name": "Procedure.pdf",
                                                           "review": {"phase": "complete"}, "excerpts": [excerpt]}]}
        payload["previous_capture"] = {
            "workflow": {"title": "", "steps": [], "connections": [], "open_questions": []},
            "memo_findings": [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                              for key in server.COVERAGE],
            "summary": "", "focus": "", "parking_lot": []}
        payload["action"] = "document_followup"
        result = client.coordinator.interview(payload)
        self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
        self.assertNotEqual(result["question"], self.STOP_LINE)
        self.assertTrue(result["question"].rstrip().endswith("?"))

    def test_wrap_up_after_an_acknowledged_stop_reaches_the_final_check(self):
        # Every topic is captured: after the pause was acknowledged, Wrap up must run the
        # completion review and ask the real final check, not repeat the stop line.
        client = SyntheticTeamProvider()
        payload = self.acknowledged(client, "I need to stop now.")
        payload["action"] = "close"
        pending = client.coordinator.interview(payload)
        self.assertEqual(pending["speech_authorization"]["kind"], "review_pending")
        payload.update(capture_token=pending["capture_token"], review_ticket=pending["review_ticket"])
        payload["turns"].append({"id": "a_review_ack", "role": "assistant", "text": pending["question"]})
        reviewed = client.coordinator.review(payload)
        self.assertEqual(reviewed["speech_authorization"]["kind"], "final_check")
        self.assertTrue(reviewed["question"].startswith(server.FINAL_CHECK_PREFIX))
        # The stop sentence itself never counts as the participant's confirmation.
        self.assertFalse(reviewed["completion"]["complete"])
        self.assertFalse(reviewed["completion"]["participant_confirmed"])

    def test_wrap_up_after_an_unacknowledged_stop_reaches_the_final_check(self):
        # The pause reply never arrived (or a live call ended before it): the transcript
        # ends with the stop request, or with the live model's own caption after it.
        # Wrap up answers that request, so it must not block the final check as well.
        for caption in ([], [{"id": "a_live", "role": "assistant", "text": "Sure, no problem at all."}]):
            with self.subTest(caption=bool(caption)):
                client = SyntheticTeamProvider()
                payload = client.payload()
                payload["turns"] += [{"id": "a_q", "role": "assistant", "text": "What happens after the manager approves?"},
                                     {"id": "u_stop", "role": "user", "text": STOP}, *caption]
                payload["action"] = "close"
                pending = client.coordinator.interview(copy.deepcopy(payload))
                self.assertEqual(pending["speech_authorization"]["kind"], "review_pending")
                self.assertNotIn("participant_stopped", pending["completion"]["blockers"])
                payload.update(capture_token=pending["capture_token"], review_ticket=pending["review_ticket"])
                payload["turns"].append({"id": "a_review_ack", "role": "assistant", "text": pending["question"]})
                reviewed = client.coordinator.review(copy.deepcopy(payload))
                self.assertEqual(reviewed["speech_authorization"]["kind"], "final_check")
                self.assertEqual(reviewed["completion"]["blockers"], ["confirmation_pending"])
                # The gate is unchanged: the stop sentence confirms nothing ...
                self.assertFalse(reviewed["completion"]["complete"])
                self.assertFalse(reviewed["completion"]["participant_confirmed"])
                # ... and only an explicit reply to the final check completes the account.
                payload["capture_token"] = reviewed["capture_token"]
                payload.pop("review_ticket")
                payload["action"] = "answer"
                payload["turns"] += [{"id": "a_final", "role": "assistant", "text": reviewed["question"]},
                                     {"id": "u_final", "role": "user", "text": "No, nothing else. This captures my account."}]
                confirmed = client.coordinator.interview(copy.deepcopy(payload))
                self.assertEqual(confirmed["speech_authorization"]["kind"], "complete")
                self.assertTrue(confirmed["completion"]["participant_confirmed"])

    def test_a_stop_in_reply_to_the_final_check_still_pauses_and_confirms_nothing(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        payload["turns"] += [{"id": "a_q", "role": "assistant", "text": "What happens after the manager approves?"},
                             {"id": "u_stop", "role": "user", "text": STOP}]
        payload["action"] = "close"
        pending = client.coordinator.interview(copy.deepcopy(payload))
        payload.update(capture_token=pending["capture_token"], review_ticket=pending["review_ticket"])
        payload["turns"].append({"id": "a_review_ack", "role": "assistant", "text": pending["question"]})
        reviewed = client.coordinator.review(copy.deepcopy(payload))
        self.assertEqual(reviewed["speech_authorization"]["kind"], "final_check")
        payload["capture_token"] = reviewed["capture_token"]
        payload.pop("review_ticket")
        payload["action"] = "answer"
        payload["turns"] += [{"id": "a_final", "role": "assistant", "text": reviewed["question"]},
                             {"id": "u_again", "role": "user", "text": "Please stop the interview now."}]
        result = client.coordinator.interview(copy.deepcopy(payload))
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        self.assertFalse(result["completion"]["complete"])
        self.assertEqual(result["completion"]["blockers"], ["participant_stopped"])

    def test_process_answers_that_begin_like_a_stop_request_are_captured(self):
        for text in ("I'm done with this when the bank confirms receipt of the wire.",
                     "I need to stop and check the source file before I release anything.",
                     "Stop and escalate to the fund controller."):
            with self.subTest(text=text):
                client = SyntheticTeamProvider()
                client.incomplete()
                payload = client.payload()
                payload["turns"] += [{"id": "a_q", "role": "assistant", "text": "How do you know this work is finished?"},
                                     {"id": "u_last", "role": "user", "text": text}]
                result = client.coordinator.interview(payload)
                self.assertGreater(client.request.call_count, 0)
                self.assertFalse(result.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
                self.assertIn("memo_findings", result)

    def test_natural_stop_requests_pause_without_provider_calls(self):
        for text in ("Sorry, I need to stop now.", "I'd like to stop here.", "Okay, let's stop here.",
                     "I have to go now, thanks for your help."):
            with self.subTest(text=text):
                client = SyntheticTeamProvider()
                client.incomplete()
                payload = client.payload()
                payload["turns"] += [{"id": "a_q", "role": "assistant", "text": "How do you know this work is finished?"},
                                     {"id": "u_last", "role": "user", "text": text}]
                result = client.coordinator.interview(payload)
                client.request.assert_not_called()
                self.assertEqual(result["speech_authorization"]["kind"], "pause")
                self.assertEqual(result["question"], self.STOP_LINE)

    def test_an_answer_that_is_a_stop_request_still_pauses_without_provider_calls(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        payload["turns"].append({"id": "u_stop", "role": "user", "text": STOP})
        result = client.coordinator.interview(payload)
        client.request.assert_not_called()
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        self.assertIs(result["preserve_capture"], True)
        self.assertNotIn("memo_findings", result)


class StopOverHTTP(unittest.TestCase):
    def setUp(self):
        local = Path(__file__).resolve().parents[1] / "work"
        local.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="stop-http-", dir=local)
        self.client = ConversationProvider()
        self.client.incomplete()
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
            documents_root=Path(self.temporary.name) / "documents")
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temporary.cleanup()

    def post(self, route, payload):
        req = Request(self.url + route, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "X-CSRF-Token": self.httpd.csrf_token})
        try:
            with urlopen(req, timeout=15) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def poll(self, payload):
        def read():
            status, progress = self.post("/api/conversation/status", payload)
            self.assertEqual(status, 200, progress)
            return progress
        return settled(read)

    def test_typed_stop_then_wrap_up_over_the_real_routes(self):
        payload = self.client.payload()
        status, first = self.post("/api/conversation/turn", payload)
        self.assertEqual(status, 200, first)
        payload["conversation_token"] = first["conversation_token"]
        ready = self.poll(payload)
        self.assertEqual(len(ready["capture"]["memo_findings"]), len(server.COVERAGE))
        stop = after(payload, first["question"], STOP, "stop")
        status, reply = self.post("/api/conversation/turn", stop)
        self.assertEqual((status, reply["speech_authorization"]["kind"]), (200, "pause"))
        progress = self.poll(stop)
        self.assertEqual(progress["state"], "ready")
        self.assertNotIn("capture", progress)
        self.assertIs(progress.get("capture_preserved"), True)
        stop["turns"].append({"id": "a_ack", "role": "assistant", "text": reply["question"]})
        stop["action"] = "close"
        status, wrapped = self.post("/api/conversation/sync", stop)
        self.assertEqual(status, 200, wrapped)
        self.assertFalse(wrapped.get("preserve_capture"), "Wrap up produces a real account, including when it names open topics.")
        self.assertEqual(len(wrapped["memo_findings"]), len(server.COVERAGE))

    def test_a_posted_stop_consumed_marker_cannot_switch_off_the_pause_reply(self):
        # _stop_consumed is set by the server for its own background work only.
        payload = self.client.payload()
        payload["turns"].append({"id": "u_stop", "role": "user", "text": STOP})
        payload["_stop_consumed"] = True
        for route in ("/api/interview", "/api/agent-team/interview"):
            with self.subTest(route=route):
                status, result = self.post(route, payload)
                self.assertEqual(status, 200, result)
                self.assertEqual(result["speech_authorization"]["kind"], "pause")
                self.assertIs(result["preserve_capture"], True)
        self.assertEqual(capture_calls(self.client), 0)
        # The capture-token path of Wrap up copies the request as it is.
        status, first = self.post("/api/conversation/turn", self.client.payload())
        self.assertEqual(status, 200, first)
        asked = {**self.client.payload(), "conversation_token": first["conversation_token"]}
        self.poll(asked)
        asked["turns"].append({"id": "a_fast", "role": "assistant", "text": first["question"]})
        status, earlier = self.post("/api/conversation/sync", {**asked, "action": "close"})
        self.assertEqual(status, 200, earlier)
        stop = after({**asked, "capture_token": earlier["capture_token"]}, earlier["question"], STOP, "stop")
        before = capture_calls(self.client)
        status, result = self.post("/api/conversation/sync", {**stop, "_stop_consumed": True})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        self.assertEqual(capture_calls(self.client), before)


class StopMarkerOffTheWire(unittest.TestCase):
    def test_sync_with_a_capture_token_drops_a_marker_in_its_payload(self):
        # The same rule without the HTTP boundary in front of ConcurrentInterview.
        client = ConversationProvider()
        client.incomplete()
        service = concurrent.ConcurrentInterview(client, server)
        self.addCleanup(service.close)
        payload = client.payload()
        first = service.turn(copy.deepcopy(payload))
        asked = {**payload, "conversation_token": first["conversation_token"]}
        settled(lambda: service.status(copy.deepcopy(asked)))
        asked["turns"].append({"id": "a_fast", "role": "assistant", "text": first["question"]})
        earlier = service.sync({**copy.deepcopy(asked), "action": "close"}, timeout=10)
        stop = after({**asked, "capture_token": earlier["capture_token"]}, earlier["question"], STOP, "stop")
        before = capture_calls(client)
        result = service.sync({**copy.deepcopy(stop), "_stop_consumed": True}, timeout=10)
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        self.assertEqual(capture_calls(client), before)
        # The pause settles that revision for the status poll as well.
        status = service.status(copy.deepcopy(stop))
        self.assertEqual(status["state"], "ready")
        self.assertNotIn("capture", status)
        self.assertIs(status.get("capture_preserved"), True)


if __name__ == "__main__":
    unittest.main()
