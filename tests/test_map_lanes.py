"""The workflow map alongside an interview: drawn at once, checked beside it, never cancelled by an answer.

Offline. A stand-in coordinator draws and checks maps for as long as each test tells it to, so
the timing properties of the November 17 stress run can be checked without a provider:
a new answer used to cancel the map being drawn, one worker served every interview, and each
map waited for its own source check. See docs/enhancements/diagram-speed-and-layout.md.
"""
import copy
import threading
import time
import unittest

from test_concurrent_interview import API, APIError, module, server, wait_for


def answers(*texts):
    """A conversation snapshot whose participant turns are u1, u2, ... with these texts."""
    turns = []
    for number, text in enumerate(texts, 1):
        turns.append({"id": f"u{number}", "role": "user", "text": text})
        turns.append({"id": f"a{number}", "role": "assistant", "text": "What happens after that?"})
    return {"context": {"process_name": "Invoices"}, "turns": turns[:-1], "_supporting_documents": {}, "action": "answer"}


def drawn_map(turns, previous=None):
    """One step per answer; steps the baseline already holds are kept exactly as they are."""
    steps = copy.deepcopy(previous["workflow"]["steps"]) if previous else []
    known = {step["id"] for step in steps}
    for turn in turns:
        # An answer that describes no step (an owner, a volume, a risk) changes nothing on the map.
        if turn["role"] == "user" and "S_" + turn["id"] not in known and not turn["text"].startswith("No step:"):
            steps.append({"id": "S_" + turn["id"], "title": turn["text"], "evidence_turns": [turn["id"]]})
    return {"workflow": {"title": "Invoices", "steps": steps, "connections": [], "open_questions": []},
            "memo_findings": [], "summary": "", "focus": "", "parking_lot": []}


class LaneAPI(API):
    same_map = staticmethod(server.same_map)


class LaneCoordinator:
    """Draws and checks as slowly as a test asks, and records every call."""

    def __init__(self):
        self.draws, self.checks, self.rebases, self.cancelled, self.captures = [], [], [], [], []
        self.draw_gate = self.check_gate = None
        self.draw_seconds = self.check_seconds = 0
        self.draw_error = self.check_error = self.rebase_error = None
        self.rich_full_pass = False
        self.active_draws = self.most_active_draws = 0
        self.lock = threading.Lock()

    def interview(self, value):
        self.captures.append(copy.deepcopy(value))
        return {"question": "What remains?", "capture_token": "server-owned-capability", "marker": value["turns"][-1]["text"],
                "speech_authorization": {"approved": True, "text": "What remains?", "kind": "question", "revision": "private"}}

    def workflow_draw(self, work):
        with self.lock:
            self.draws.append(copy.deepcopy(work))
            self.active_draws += 1
            self.most_active_draws = max(self.most_active_draws, self.active_draws)
            gate, seconds, error = self.draw_gate, self.draw_seconds, self.draw_error
        try:
            if gate:
                gate.wait(5)
            if seconds:
                time.sleep(seconds)
            if error:
                raise error
            capture = drawn_map(work["turns"], work.get("previous_capture"))
            if self.rich_full_pass and not work.get("previous_capture"):
                capture["workflow"]["steps"].append({"id": "S_missed", "title": "A step the updates left out",
                                                     "evidence_turns": [work["turns"][0]["id"]]})
                capture["workflow"]["steps"].append({"id": "S_missed_too", "title": "Another", "evidence_turns": [work["turns"][0]["id"]]})
            return {"capture": capture, "update": {}}
        finally:
            with self.lock:
                self.active_draws -= 1

    def workflow_check(self, work, drawn, corrections=()):
        with self.lock:
            self.checks.append({"work": copy.deepcopy(work), "drawn": copy.deepcopy(drawn), "corrections": list(corrections)})
            gate, seconds, error = self.check_gate, self.check_seconds, self.check_error
        if gate:
            gate.wait(5)
        if seconds:
            time.sleep(seconds)
        if error:
            raise error
        checked = copy.deepcopy(drawn)
        for step in checked["workflow"]["steps"]:
            step["checked"] = True
        return checked

    def workflow_rebase(self, work, checked_from, drawn, corrections=()):
        self.rebases.append({"work": copy.deepcopy(work), "checked_from": copy.deepcopy(checked_from), "drawn": copy.deepcopy(drawn)})
        if self.rebase_error:
            raise self.rebase_error
        result = copy.deepcopy(work["previous_capture"])
        before = {step["id"] for step in checked_from["workflow"]["steps"]}
        result["workflow"]["steps"] += [copy.deepcopy(step) for step in drawn["workflow"]["steps"] if step["id"] not in before]
        return result

    def cancel(self, run_id):
        self.cancelled.append(run_id)


class LaneClient:
    agent_models = {"lead_interviewer": "offline-model"}

    def __init__(self):
        self.coordinator = LaneCoordinator()

    def structured(self, instructions, data, schema, name, tokens, **kwargs):
        return {"question": "What happens after that?", "request_review": False}


class MapLaneTests(unittest.TestCase):
    def service(self, **kwargs):
        client = LaneClient()
        instance = module.ConcurrentInterview(client, LaneAPI, **kwargs)
        self.addCleanup(instance.close)
        for gate in ("draw_gate", "check_gate"):
            self.addCleanup(lambda name=gate: getattr(client.coordinator, name) and getattr(client.coordinator, name).set())
        return instance, client.coordinator

    @staticmethod
    def step_ids(capture):
        return [step["id"] for step in capture["workflow"]["steps"]]

    def test_a_new_answer_does_not_cancel_the_map_being_drawn_and_its_result_is_kept(self):
        # Finding 1 of the November 17 run: 65 maps were cancelled by the next answer.
        service, team = self.service()
        team.draw_gate, team.check_gate = threading.Event(), threading.Event()
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        wait_for(lambda: len(team.draws) == 1)
        second = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        service.turn(second)
        self.assertEqual(team.cancelled, [], "The map being drawn was cancelled by the next answer")
        status = service.status(second)
        self.assertNotIn("workflow_capture", status)
        self.assertNotIn("workflow_checkpoint", status)
        team.draw_gate.set()
        # The first map arrives as the map through the first answer...
        wait_for(lambda: len(team.draws) == 2)
        # ...and the map of the second answer starts from it instead of from nothing.
        self.assertEqual(self.step_ids(team.draws[1]["previous_capture"]), ["S_u1"])
        self.assertIs(team.draws[1]["_session_baseline"], True)
        wait_for(lambda: "workflow_capture" in service.status(second))
        status = service.status(second)
        self.assertEqual(self.step_ids(status["workflow_capture"]), ["S_u1", "S_u2"])
        self.assertEqual(status["workflow_state"], "ready")
        self.assertEqual(len(team.draws), 2, "No map was drawn twice")

    def test_the_map_through_an_earlier_answer_is_offered_while_the_next_is_drawn(self):
        service, team = self.service()
        team.check_gate = threading.Event()
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        one = {**answers("The clerk receives the invoice."), "conversation_token": token}
        wait_for(lambda: "workflow_capture" in service.status(one))
        team.draw_gate = threading.Event()
        two = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        service.turn(two)
        wait_for(lambda: len(team.draws) == 2)
        status = service.status(two)
        self.assertNotIn("workflow_capture", status)
        self.assertEqual(status["workflow_state"], "working")
        checkpoint = status["workflow_checkpoint"]
        self.assertEqual(checkpoint["through_turn_id"], "u1")
        self.assertEqual([turn["id"] for turn in checkpoint["turns"]], ["u1"])
        self.assertEqual(self.step_ids(checkpoint["workflow_capture"]), ["S_u1"])
        self.assertIs(checkpoint["checked"], False)
        team.draw_gate.set()
        wait_for(lambda: "workflow_capture" in service.status(two))
        self.assertNotIn("workflow_checkpoint", service.status(two))

    def test_a_map_drawn_from_wording_that_was_edited_since_is_not_kept(self):
        service, team = self.service()
        team.draw_gate = threading.Event()
        first = service.turn(answers("The clerk receives the invoice."))
        wait_for(lambda: len(team.draws) == 1)
        edited = {**answers("Correction: the manager receives the invoice."), "conversation_token": first["conversation_token"]}
        service.turn(edited)
        team.draw_gate.set()
        wait_for(lambda: len(team.draws) == 2)
        self.assertNotIn("previous_capture", team.draws[1], "A map of the old wording became the baseline")
        wait_for(lambda: "workflow_capture" in service.status(edited))
        self.assertEqual(service.status(edited)["workflow_capture"]["workflow"]["steps"][0]["title"],
                         "Correction: the manager receives the invoice.")

    def test_the_drawn_map_is_shown_before_its_source_check_and_says_so(self):
        # Finding 2: the check took longer than the draw (112 s against 41 s) and stood in front of it.
        service, team = self.service()
        team.check_gate = threading.Event()
        first = service.turn(answers("The clerk receives the invoice."))
        snapshot = {**answers("The clerk receives the invoice."), "conversation_token": first["conversation_token"]}
        wait_for(lambda: "workflow_capture" in service.status(snapshot))
        status = service.status(snapshot)
        self.assertEqual((status["workflow_state"], status["workflow_pending"]), ("ready", False))
        self.assertIs(status["workflow_checked"], False)
        self.assertEqual(status["workflow_check_state"], "working")
        self.assertNotIn("checked", status["workflow_capture"]["workflow"]["steps"][0])
        version = status["workflow_version"]
        wait_for(lambda: len(team.checks) == 1)
        self.assertNotIn("previous_capture", team.checks[0]["work"], "The first check has no checked map to continue from")
        team.check_gate.set()
        wait_for(lambda: service.status(snapshot).get("workflow_checked") is True)
        status = service.status(snapshot)
        self.assertNotIn("workflow_check_state", status)
        self.assertGreater(status["workflow_version"], version)
        self.assertIs(status["workflow_capture"]["workflow"]["steps"][0]["checked"], True)
        self.assertEqual(len(team.checks), 1, "A checked map is not checked again")

    def test_a_running_check_does_not_hold_up_the_next_map_and_its_result_is_carried_forward(self):
        service, team = self.service()
        team.check_gate = threading.Event()
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        wait_for(lambda: len(team.checks) == 1)
        two = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        service.turn(two)
        # The second map is drawn and shown while the check of the first is still running.
        wait_for(lambda: "workflow_capture" in service.status(two))
        self.assertEqual(self.step_ids(service.status(two)["workflow_capture"]), ["S_u1", "S_u2"])
        self.assertEqual(len(team.checks), 1, "One check at a time for an interview")
        team.check_gate.set()
        # The finished check is applied under the later draw: its correction of S_u1 stays, S_u2 stays.
        wait_for(lambda: len(team.rebases) == 1)
        rebase = team.rebases[0]
        self.assertEqual(self.step_ids(rebase["checked_from"]), ["S_u1"])
        self.assertEqual(self.step_ids(rebase["drawn"]), ["S_u1", "S_u2"])
        self.assertIs(rebase["work"]["previous_capture"]["workflow"]["steps"][0]["checked"], True)
        # What the later answer added is checked next, from the checked map and not from nothing.
        wait_for(lambda: len(team.checks) == 2)
        self.assertEqual(self.step_ids(team.checks[1]["work"]["previous_capture"]), ["S_u1"])
        self.assertEqual(self.step_ids(team.checks[1]["drawn"]), ["S_u1", "S_u2"])
        wait_for(lambda: service.status(two).get("workflow_checked") is True)
        steps = service.status(two)["workflow_capture"]["workflow"]["steps"]
        self.assertEqual([(step["id"], step.get("checked")) for step in steps], [("S_u1", True), ("S_u2", True)])

    def test_a_check_that_cannot_be_carried_forward_is_left_out_and_the_map_stays_as_drawn(self):
        service, team = self.service()
        team.check_gate = threading.Event()
        team.rebase_error = ValueError("The later draws cannot be applied to the checked map.")
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        wait_for(lambda: len(team.checks) == 1)
        two = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        service.turn(two)
        wait_for(lambda: "workflow_capture" in service.status(two))
        team.check_gate.set()
        wait_for(lambda: len(team.rebases) == 1)
        # The map as drawn is checked again, whole: nothing of the unusable result is assumed.
        wait_for(lambda: len(team.checks) == 2)
        self.assertNotIn("previous_capture", team.checks[1]["work"])
        wait_for(lambda: service.status(two).get("workflow_checked") is True)
        self.assertEqual(len(team.rebases), 1)

    def test_a_failed_check_keeps_the_map_on_screen_and_is_tried_once_more_at_wrap_up(self):
        # Finding 3: a timed-out audit used to discard a map that had been drawn correctly.
        service, team = self.service()
        service.map_wait = .05
        failure = APIError("Private provider detail", 504, "timeout")
        team.check_error = failure
        first = service.turn(answers("The clerk receives the invoice."))
        snapshot = {**answers("The clerk receives the invoice."), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot).get("workflow_check_state") == "error")
        status = service.status(snapshot)
        self.assertEqual(self.step_ids(status["workflow_capture"]), ["S_u1"])
        self.assertEqual((status["workflow_state"], status["workflow_checked"]), ("ready", False))
        self.assertEqual(status["workflow_check_error"], "The provider timed out. Your answers are retained.")
        self.assertNotIn("Private", str(status))
        time.sleep(.1)
        self.assertEqual(len(team.checks), 1, "A failed check started again by itself")
        team.check_error = None
        result = service.sync({**snapshot, "action": "close"})
        self.assertEqual(self.step_ids(result["workflow_capture"]), ["S_u1"])
        self.assertEqual((result["workflow_state"], result["workflow_pending"]), ("ready", False))
        wait_for(lambda: len(team.checks) == 2)
        closing = {**snapshot, "action": "close"}
        query = {"conversation_token": result["conversation_token"], "revision": result["revision"]}
        wait_for(lambda: service.status_for_revision(query).get("workflow_checked") is True)
        del closing

    def test_a_refused_check_is_followed_by_a_check_of_the_whole_map(self):
        service, team = self.service()
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        one = {**answers("The clerk receives the invoice."), "conversation_token": token}
        wait_for(lambda: service.status(one).get("workflow_checked") is True)
        team.check_error = ValueError("The revised step leaves the existing handoff S_u1 to S_u2 unverified.")
        two = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        service.turn(two)
        wait_for(lambda: service.status(two).get("workflow_check_state") == "error")
        self.assertIn("previous_capture", team.checks[1]["work"])
        team.check_error = None
        three = {**answers("The clerk receives the invoice.", "The manager approves it.", "Treasury pays it."), "conversation_token": token}
        service.turn(three)
        wait_for(lambda: service.status(three).get("workflow_checked") is True)
        self.assertNotIn("previous_capture", team.checks[-1]["work"],
                         "The difference that was refused would be refused again: the whole map is checked")

    def test_an_answer_that_changes_nothing_on_the_map_needs_no_second_check(self):
        service, team = self.service()
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        one = {**answers("The clerk receives the invoice."), "conversation_token": token}
        wait_for(lambda: service.status(one).get("workflow_checked") is True)
        two = {**answers("The clerk receives the invoice.", "No step: about forty invoices arrive each week."), "conversation_token": token}
        service.turn(two)
        wait_for(lambda: service.status(two).get("workflow_checked") is True)
        status = service.status(two)
        self.assertEqual(self.step_ids(status["workflow_capture"]), ["S_u1"])
        self.assertNotIn("workflow_check_state", status)
        self.assertEqual((len(team.draws), len(team.checks)), (2, 1), "A map that did not change was sent for review again")
        # The next answer that does add a step is checked from the checked map as before.
        three = {**two, "turns": [*two["turns"], {"id": "a2", "role": "assistant", "text": "What happens after that?"},
                                  {"id": "u3", "role": "user", "text": "The manager approves it."}]}
        service.turn(three)
        wait_for(lambda: service.status(three).get("workflow_checked") is True)
        self.assertEqual(len(team.checks), 2)
        self.assertEqual(self.step_ids(team.checks[1]["work"]["previous_capture"]), ["S_u1"])

    def test_a_failed_draw_leaves_the_earlier_map_and_reports_the_error(self):
        service, team = self.service()
        team.check_gate = threading.Event()
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        one = {**answers("The clerk receives the invoice."), "conversation_token": token}
        wait_for(lambda: "workflow_capture" in service.status(one))
        team.draw_error = APIError("Private provider detail", 429, "rate_limit")
        two = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        service.turn(two)
        wait_for(lambda: service.status(two)["workflow_state"] == "error")
        status = service.status(two)
        self.assertEqual(status["workflow_error"], "The provider is busy. Try again shortly.")
        self.assertEqual(self.step_ids(status["workflow_checkpoint"]["workflow_capture"]), ["S_u1"])

    def test_discarding_a_conversation_ends_its_draw_and_its_check(self):
        service, team = self.service()
        team.check_gate, team.draw_gate = threading.Event(), None
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        wait_for(lambda: len(team.checks) == 1)
        team.draw_gate = threading.Event()
        service.turn({**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token})
        wait_for(lambda: len(team.draws) == 2)
        session = service._sessions[token]
        service.discard(token)
        self.assertIn(team.draws[1]["agent_run_id"], team.cancelled)
        self.assertIn(team.checks[0]["work"]["agent_run_id"], team.cancelled)
        team.draw_gate.set()
        team.check_gate.set()
        wait_for(lambda: not session["graph_running"] and not session["check_running"])
        self.assertEqual((len(team.draws), len(team.checks)), (2, 1))

    def test_wrap_up_reads_the_whole_account_once_more_and_takes_the_richer_map(self):
        # A map built answer by answer came out thinner than one drawn from the whole account
        # (16 to 20 of 28 stated steps in the prototype replay).
        service, team = self.service()
        service.map_wait = .05
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        two = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        wait_for(lambda: len(team.draws) == 1)
        service.turn(two)
        wait_for(lambda: service.status(two).get("workflow_checked") is True)
        self.assertEqual(len(team.draws), 2)
        team.rich_full_pass = True
        team.draw_gate = threading.Event()
        result = service.sync({**two, "action": "close"})
        self.assertEqual(self.step_ids(result["workflow_capture"]), ["S_u1", "S_u2"], "Wrap up releases the map it has")
        self.assertEqual(result["workflow_state"], "ready")
        # The map was checked, and is still not final: the page must keep asking while the second look runs.
        self.assertEqual((result["workflow_checked"], result["workflow_check_state"]), (False, "working"))
        team.draw_gate.set()
        wait_for(lambda: len(team.draws) == 3)
        self.assertNotIn("previous_capture", team.draws[2], "The second look reads the whole account, not the map")
        query = {"conversation_token": result["conversation_token"], "revision": result["revision"]}
        wait_for(lambda: "S_missed" in self.step_ids(service.status_for_revision(query)["workflow_capture"]))
        status = service.status_for_revision(query)
        self.assertEqual(status["workflow_state"], "ready")
        # The map that replaced it is checked whole: nothing checked on the other map carries over.
        wait_for(lambda: service.status_for_revision(query).get("workflow_checked") is True)
        self.assertNotIn("previous_capture", team.checks[-1]["work"])
        # One second look for a revision, also when Wrap up is chosen again.
        service.sync({**two, "action": "close"})
        time.sleep(.1)
        self.assertEqual(len(team.draws), 3)

    def test_wrap_up_keeps_the_map_on_screen_when_the_second_look_adds_nothing(self):
        service, team = self.service()
        service.map_wait = .05
        first = service.turn(answers("The clerk receives the invoice."))
        token = first["conversation_token"]
        two = {**answers("The clerk receives the invoice.", "The manager approves it."), "conversation_token": token}
        wait_for(lambda: len(team.draws) == 1)
        service.turn(two)
        wait_for(lambda: service.status(two).get("workflow_checked") is True)
        version = service.status(two)["workflow_version"]
        checks = len(team.checks)
        team.draw_gate = threading.Event()
        result = service.sync({**two, "action": "close"})
        wait_for(lambda: len(team.draws) == 3)
        query = {"conversation_token": result["conversation_token"], "revision": result["revision"]}
        looking = service.status_for_revision(query)
        self.assertEqual((looking["workflow_checked"], looking["workflow_check_state"]), (False, "working"))
        team.draw_gate.set()
        session = service._sessions[token]
        wait_for(lambda: not session["graph_running"])
        status = service.status_for_revision(query)
        self.assertEqual((status["workflow_version"], status["workflow_checked"]), (version, True))
        self.assertNotIn("workflow_check_state", status)
        self.assertEqual(len(team.checks), checks, "A map that was kept is not checked again")

    def test_a_map_drawn_whole_needs_no_second_look(self):
        service, team = self.service()
        service.map_wait = .05
        first = service.turn(answers("The clerk receives the invoice."))
        snapshot = {**answers("The clerk receives the invoice."), "conversation_token": first["conversation_token"]}
        wait_for(lambda: service.status(snapshot).get("workflow_checked") is True)
        service.sync({**snapshot, "action": "close"})
        time.sleep(.1)
        self.assertEqual(len(team.draws), 1)


class MapFairnessTests(unittest.TestCase):
    def service(self, **kwargs):
        client = LaneClient()
        instance = module.ConcurrentInterview(client, LaneAPI, **kwargs)
        self.addCleanup(instance.close)
        self.addCleanup(lambda: client.coordinator.draw_gate and client.coordinator.draw_gate.set())
        return instance, client.coordinator

    def test_several_maps_are_drawn_at_once_up_to_the_configured_number(self):
        # Finding 4: one map worker served every interview on a server.
        service, team = self.service(map_workers=2)
        team.draw_gate = threading.Event()
        for text in ("First interview.", "Second interview.", "Third interview."):
            service.turn(answers(text))
        wait_for(lambda: len(team.draws) == 2)
        time.sleep(.1)
        self.assertEqual((len(team.draws), team.most_active_draws), (2, 2))
        team.draw_gate.set()
        wait_for(lambda: len(team.draws) == 3)
        self.assertEqual(team.most_active_draws, 2)

    def test_an_interview_with_more_to_draw_queues_behind_the_others(self):
        # The worker used to stay with one interview for as long as it had work.
        service, team = self.service(map_workers=1)
        team.draw_gate = threading.Event()
        busy = service.turn(answers("Busy interview, first answer."))
        wait_for(lambda: len(team.draws) == 1)
        service.turn(answers("Waiting interview."))
        service.turn({**answers("Busy interview, first answer.", "Busy interview, second answer."),
                      "conversation_token": busy["conversation_token"]})
        team.draw_gate.set()
        wait_for(lambda: len(team.draws) == 3)
        self.assertEqual([work["turns"][0]["text"] for work in team.draws],
                         ["Busy interview, first answer.", "Waiting interview.", "Busy interview, first answer."])

    def test_the_client_setting_sizes_the_map_workers(self):
        client = LaneClient()
        client.map_workers = 3
        service = module.ConcurrentInterview(client, LaneAPI)
        self.addCleanup(service.close)
        self.assertEqual((service._draws.size, service._checks.size), (3, 2))
        single = module.ConcurrentInterview(LaneClient(), LaneAPI, map_workers=1)
        self.addCleanup(single.close)
        self.assertEqual((single._draws.size, single._checks.size), (1, 1))


class MapLatencyTests(unittest.TestCase):
    """The pacing of the stress run, scaled down about a hundred and fifty times.

    There a participant answered every 45 s, a draw took 41 s and its check 112 s; the diagram
    was there before the next answer for 7 of 139 answers. Here an answer comes every 300 ms and
    a check takes 700 ms. The draw takes 120 ms in the first case and 450 ms in the second:
    slower than the answers, as a draw with the full instructions may well be. The intervals
    are this long so that a loaded machine, which starts a thread tens of milliseconds late,
    still keeps the pace: at 90 ms an answer these cases failed two runs in six with every
    processor busy.
    """
    ANSWER, DRAW, CHECK = .3, .12, .7
    SLOW_DRAW = .45

    def test_a_draw_slower_than_the_answers_still_keeps_a_map_on_screen_that_trails_by_an_answer_or_two(self):
        client = LaneClient()
        team = client.coordinator
        team.draw_seconds, team.check_seconds = self.SLOW_DRAW, self.CHECK
        service = module.ConcurrentInterview(client, LaneAPI)
        self.addCleanup(service.close)
        texts = [f"Answer number {number}." for number in range(1, 8)]
        token, started, behind = None, time.monotonic(), []
        for count in range(1, len(texts) + 1):
            snapshot = answers(*texts[:count])
            if token:
                snapshot["conversation_token"] = token
            sent = time.monotonic()
            token = service.turn(snapshot)["conversation_token"]
            snapshot["conversation_token"] = token
            while time.monotonic() < sent + self.ANSWER:
                time.sleep(.004)
            # Just before the next answer: which answer does the map on screen go through?
            status = service.status(snapshot)
            if "workflow_capture" in status:
                behind.append(0)
            elif "workflow_checkpoint" in status:
                behind.append(count - int(status["workflow_checkpoint"]["through_turn_id"][1:]))
            else:
                behind.append(None)
        final = answers(*texts)
        final["conversation_token"] = token
        finished = time.monotonic()
        wait_for(lambda: "workflow_capture" in service.status(final), seconds=5)
        self.assertEqual(team.cancelled, [], "A slower draw must not bring cancellation back")
        # Once the first map is drawn there is always one on screen, never more than two answers behind.
        first = next(index for index, value in enumerate(behind) if value is not None)
        self.assertLessEqual(first, 2, f"No map after three answers: {behind}")
        self.assertTrue(all(value is not None and value <= 2 for value in behind[first:]), behind)
        # Each draw read the latest account at its start: fewer draws than answers, none wasted.
        self.assertLessEqual(len(team.draws), len(texts))
        self.assertGreaterEqual(len(team.draws), len(texts) // 2)
        # The map of the last answer follows within the draw in flight and one more.
        self.assertLess(time.monotonic() - finished, self.SLOW_DRAW * 2 + 1.0)
        wait_for(lambda: service.status(final).get("workflow_checked") is True, seconds=6)
        self.assertEqual([step["id"] for step in service.status(final)["workflow_capture"]["workflow"]["steps"]],
                         [f"S_u{number}" for number in range(1, 8)])
        # The check did not wait for the draws to stop (they never did): it ran beside them in
        # pieces, so the last check is a small difference and not the whole map at the end.
        self.assertGreaterEqual(len(team.checks), 2)
        self.assertTrue(all("previous_capture" in check["work"] for check in team.checks[1:]))
        self.assertLess(len(team.checks[-1]["drawn"]["workflow"]["steps"])
                        - len(team.checks[-1]["work"]["previous_capture"]["workflow"]["steps"]), len(texts))
        del started

    def test_every_answer_gets_its_map_while_checks_run_and_none_is_cancelled(self):
        client = LaneClient()
        team = client.coordinator
        team.draw_seconds, team.check_seconds = self.DRAW, self.CHECK
        service = module.ConcurrentInterview(client, LaneAPI)
        self.addCleanup(service.close)
        texts = [f"Answer number {number}." for number in range(1, 7)]
        token, waits = None, []
        for count in range(1, len(texts) + 1):
            snapshot = answers(*texts[:count])
            if token:
                snapshot["conversation_token"] = token
            sent = time.monotonic()
            token = service.turn(snapshot)["conversation_token"]
            snapshot["conversation_token"] = token
            deadline = sent + self.ANSWER
            shown = None
            while time.monotonic() < deadline:
                status = service.status(snapshot)
                if shown is None and "workflow_capture" in status:
                    shown = time.monotonic() - sent
                time.sleep(.004)
            waits.append(shown)
        final = answers(*texts)
        final["conversation_token"] = token
        wait_for(lambda: service.status(final).get("workflow_checked") is True, seconds=5)
        self.assertEqual(team.cancelled, [])
        self.assertEqual(len(team.draws), len(texts), "One draw for each answer, none repeated and none skipped")
        self.assertTrue(all(wait is not None for wait in waits),
                        f"A map was not there before the next answer: {waits}")
        # A check never stands in front of a draw: the wait is the draw, not the draw and the check.
        self.assertLess(max(waits), self.DRAW + self.ANSWER * .5)
        self.assertEqual([step["id"] for step in service.status(final)["workflow_capture"]["workflow"]["steps"]],
                         [f"S_u{number}" for number in range(1, 7)])
        # Checks reviewed differences, not the whole map each time: only the first had no checked map before it.
        self.assertEqual([("previous_capture" in check["work"]) for check in team.checks][0], False)
        self.assertTrue(all("previous_capture" in check["work"] for check in team.checks[1:]))
        self.assertLess(len(team.checks), len(texts) + 2)

    def test_five_interviews_on_one_server_each_get_their_map(self):
        client = LaneClient()
        team = client.coordinator
        team.draw_seconds, team.check_seconds = self.DRAW, self.CHECK
        service = module.ConcurrentInterview(client, LaneAPI, map_workers=2, workers=2)
        self.addCleanup(service.close)
        started = time.monotonic()
        snapshots = []
        for number in range(1, 6):
            snapshot = answers(f"Interview {number}, first answer.")
            snapshot["conversation_token"] = service.turn(snapshot)["conversation_token"]
            snapshots.append(snapshot)
        wait_for(lambda: all("workflow_capture" in service.status(snapshot) for snapshot in snapshots), seconds=5)
        # Five draws on two workers: three rounds of one draw, with room for a loaded machine.
        self.assertLess(time.monotonic() - started, self.DRAW * 3 + 1.0)
        self.assertEqual(team.most_active_draws, 2)
        wait_for(lambda: all(service.status(snapshot).get("workflow_checked") is True for snapshot in snapshots), seconds=8)


if __name__ == "__main__":
    unittest.main()
