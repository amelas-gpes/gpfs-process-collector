"""The source check of a map reviews what changed since the last check, with the real validation.

Offline. The scripted team of test_background_continuity plays the models through the real
Coordinator; the saved maps of the November 17 stress run (drawn by the real provider and
valid against their own transcripts) are the material for the difference and carry-forward
rules. No provider or network is used.
"""
import copy
import json
import threading
import time
import unittest
from pathlib import Path

from test_background_continuity import SCRIPT, ScriptedTeam, TypedInterview, account, concurrent, step
from test_server import server

CASES = Path(__file__).resolve().parents[1] / "docs" / "testing" / "runs" / "2026-11-17-stress" / "cases"
# Interviews without files whose final map validates against its own transcript.
SAVED = ("A-T01", "B-T01", "C-T01", "C-T07", "C-T11", "STRESS-T06", "STRESS-T09", "T03", "T04", "T09", "T13", "V02", "V04")


def unknown_memo():
    return [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []} for key in server.COVERAGE]


def baseline(workflow):
    return {"workflow": {key: copy.deepcopy(workflow[key]) for key in ("title", "steps", "connections", "open_questions")},
            "memo_findings": unknown_memo(), "summary": "", "focus": "", "parking_lot": []}


def part(workflow, count):
    """The first `count` steps of a map with the routes among them."""
    steps = workflow["steps"][:count]
    held = {item["id"] for item in steps}
    return {**workflow, "steps": steps,
            "connections": [edge for edge in workflow["connections"] if edge["from"] in held and edge["to"] in held]}


def saved_cases():
    for name in SAVED:
        case = json.loads((CASES / f"{name}.json").read_text(encoding="utf-8"))
        context, turns = server.validate_payload({"context": case["context"], "turns": case["turns"]})
        yield name, context, turns, case["workflow"]


def checked_within(read, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = read()
        if status.get("workflow_checked") is True:
            return status
        time.sleep(.01)
    raise AssertionError("The map was not checked in time")


def drawn_within(read, seconds=15):
    """The map of this snapshot as soon as it is drawn, whether or not its check has finished."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = read()
        if "workflow_capture" in status:
            return status
        time.sleep(.01)
    raise AssertionError("The map was not drawn in time")


class SavedMapDifferences(unittest.TestCase):
    """server.workflow_delta and workflow_rebase_update on maps a real interview produced."""

    def previous(self, workflow, turns, context):
        return server.workflow_previous_capture(baseline(workflow), turns, None, (), context=context)

    def test_the_difference_between_an_earlier_and_a_later_state_reproduces_the_later_one(self):
        compared = 0
        for name, context, turns, workflow in saved_cases():
            for count in sorted({0, 1, len(workflow["steps"]) // 2, len(workflow["steps"]) - 1}):
                with self.subTest(case=name, steps=count):
                    earlier = self.previous(part(workflow, count), turns, context)
                    later = self.previous(workflow, turns, context)
                    update = server.workflow_delta(earlier, later)
                    self.assertIsNotNone(update)
                    # Only what is new travels: the steps the earlier state already held are not sent again.
                    self.assertEqual(len(update["upsert_steps"]), len(workflow["steps"]) - count)
                    self.assertEqual((update["remove_steps"], update["remove_connections"]), ([], []))
                    applied = server.apply_workflow_update(update, earlier, turns, None, (), context=context)
                    self.assertTrue(server.same_map(applied["workflow"], later["workflow"]))
                    compared += 1
        self.assertGreater(compared, 30)

    def test_an_unchanged_map_has_an_empty_difference(self):
        for name, context, turns, workflow in saved_cases():
            with self.subTest(case=name):
                state = self.previous(workflow, turns, context)
                update = server.workflow_delta(state, copy.deepcopy(state))
                self.assertEqual([update[key] for key in ("upsert_steps", "remove_steps", "upsert_connections", "remove_connections")],
                                 [[], [], [], []])

    def test_a_component_that_left_the_map_needs_the_participant_s_quotation(self):
        for name, context, turns, workflow in saved_cases():
            if len(workflow["steps"]) < 4:
                continue
            with self.subTest(case=name):
                answer = next(turn for turn in turns if turn["role"] == "user")
                quote = answer["text"][:160]
                gone = workflow["steps"][-1]["id"]
                later = {**workflow, "steps": workflow["steps"][:-1],
                         "connections": [edge for edge in workflow["connections"] if gone not in (edge["from"], edge["to"])]}
                before, after = self.previous(workflow, turns, context), self.previous(later, turns, context)
                # A draw never removes without a record. Without one the difference cannot be written...
                self.assertIsNone(server.workflow_delta(before, after))
                # ...and with the record the draw verified, it carries the same quotation.
                record = {"type": "step", "id": gone, "reason": "The participant withdrew this step.",
                          "source_quote": quote, "evidence_turns": [answer["id"]]}
                update = server.workflow_delta(before, after, [record])
                self.assertEqual(update["remove_steps"], [{key: record[key] for key in ("id", "reason", "source_quote", "evidence_turns")}])
                # The routes of the removed step are not named: applying the removal takes them with it.
                self.assertEqual(update["remove_connections"], [])
                applied = server.apply_workflow_update(update, before, turns, None, (), context=context)
                self.assertTrue(server.same_map(applied["workflow"], after["workflow"]))

    def test_a_route_that_left_the_map_needs_its_record_too(self):
        for name, context, turns, workflow in saved_cases():
            if not workflow["connections"]:
                continue
            with self.subTest(case=name):
                answer = next(turn for turn in turns if turn["role"] == "user")
                edge = workflow["connections"][0]
                later = {**workflow, "connections": workflow["connections"][1:]}
                before, after = self.previous(workflow, turns, context), self.previous(later, turns, context)
                self.assertIsNone(server.workflow_delta(before, after))
                record = {"type": "connection", **{key: edge[key] for key in ("from", "to", "label")},
                          "reason": "The participant corrected this handoff.", "source_quote": answer["text"][:160],
                          "evidence_turns": [answer["id"]]}
                update = server.workflow_delta(before, after, [record])
                applied = server.apply_workflow_update(update, before, turns, None, (), context=context)
                self.assertTrue(server.same_map(applied["workflow"], after["workflow"]))

    def test_draws_made_during_a_check_are_carried_onto_its_result(self):
        for name, context, turns, workflow in saved_cases():
            total = len(workflow["steps"])
            if total < 6:
                continue
            with self.subTest(case=name):
                half = total // 2
                checked_from = self.previous(part(workflow, half), turns, context)
                drawn = self.previous(workflow, turns, context)
                # The check corrected one step and took another off the map with its routes.
                checked = copy.deepcopy(checked_from)
                checked["workflow"]["steps"][0]["title"] = "Corrected by the source check"
                dropped = checked["workflow"]["steps"].pop()["id"]
                checked["workflow"]["connections"] = [edge for edge in checked["workflow"]["connections"]
                                                      if dropped not in (edge["from"], edge["to"])]
                checked["workflow"]["open_questions"] = ["Which source states the removed handoff?"] + checked["workflow"]["open_questions"]
                checked = server.workflow_previous_capture(checked, turns, None, (), context=context)
                update = server.workflow_rebase_update(checked, checked_from, drawn)
                self.assertIsNotNone(update)
                rebased = server.apply_workflow_update(update, checked, turns, None, (), context=context)["workflow"]
                steps = {item["id"]: item for item in rebased["steps"]}
                # The correction stays, what the check took off stays off, the later answers are all there.
                self.assertEqual(steps[workflow["steps"][0]["id"]]["title"], "Corrected by the source check")
                self.assertNotIn(dropped, steps)
                self.assertEqual(set(steps), {item["id"] for item in workflow["steps"]} - {dropped})
                self.assertTrue(all(dropped not in (edge["from"], edge["to"]) for edge in rebased["connections"]))
                self.assertIn("Which source states the removed handoff?", rebased["open_questions"])
                later_routes = [edge for edge in workflow["connections"]
                                if dropped not in (edge["from"], edge["to"])]
                self.assertEqual({server.route_key(edge) for edge in rebased["connections"]},
                                 {server.route_key(edge) for edge in later_routes})

    def test_same_map_ignores_order_and_sees_every_field(self):
        _name, context, turns, workflow = next(saved_cases())
        shuffled = {**workflow, "steps": workflow["steps"][::-1], "connections": workflow["connections"][::-1]}
        self.assertTrue(server.same_map(workflow, shuffled))
        changed = copy.deepcopy(workflow)
        changed["steps"][0]["actor"] = "Somebody else"
        self.assertFalse(server.same_map(workflow, changed))


class RecordingTeam(ScriptedTeam):
    """The scripted team, keeping the instructions and the allowance of each request as well."""

    def __init__(self, script=None):
        super().__init__(script)
        self.bodies = []
        self.truncate = 0

    def request(self, path, body, content_type="application/json", timeout=90, on_text=None):
        if isinstance(body, dict):
            self.bodies.append({"name": body["text"]["format"]["name"], "instructions": body["instructions"],
                                "max_output_tokens": body["max_output_tokens"], "timeout": timeout})
            if body["text"]["format"]["name"] == "team_working_process_map" and self.truncate:
                self.truncate -= 1
                return {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
        return super().request(path, body, content_type, timeout, on_text)

    def draws(self):
        return [body for body in self.bodies if body["name"] == "team_working_process_map"]


class CheckedBesideTheDraw(unittest.TestCase):
    def setUp(self):
        self.client = RecordingTeam()
        self.service = concurrent.ConcurrentInterview(self.client, server)
        self.addCleanup(self.service.close)
        self.interview = TypedInterview(self.service)

    def say(self, turn):
        self.interview.answer(SCRIPT[turn]["say"])
        return checked_within(lambda: self.service.status(self.interview.payload()))

    def audits(self):
        return self.client.sent("team_working_map_source_audit")

    def test_the_background_draw_is_given_every_rule_of_the_map(self):
        # 103 of 106 background maps in the stress run were drawn from instructions cut before
        # these policies; the source audit then rewrote most steps of every map.
        self.say("u1")
        instructions = self.client.draws()[0]["instructions"]
        for policy in ("GRAPH_ROUTING_POLICY", "WORKFLOW_COMPONENT_POLICY", "WORKFLOW_SOURCE_AUDIT_POLICY",
                       "STEP_DETAIL_POLICY", "REQUIRED_DEPENDENCY_POLICY", "ARTIFACT_EVIDENCE_POLICY"):
            self.assertIn(getattr(server, policy), instructions, policy + " is missing from the background draw")
        self.assertIn("Keep an existing route label verbatim", instructions)
        # It returns no memo, so the memo rules are the one part it does not need.
        self.assertNotIn("In memo_findings return", instructions)
        self.assertEqual(instructions, server.WORKFLOW_MAP_INSTRUCTIONS)
        # A map the page waits for returns the memo as well and keeps the full instructions, unchanged.
        self.assertTrue(server.WORKFLOW_INSTRUCTIONS.startswith(server.ARTIFACT_EVIDENCE_POLICY + server.WORKFLOW_MAP_RULES))
        self.assertIn(server.WORKFLOW_MEMO_RULES, server.WORKFLOW_INSTRUCTIONS)
        self.assertEqual(server.provider_usage.prompt_id(server.WORKFLOW_INSTRUCTIONS), "f57783fe73a74655")

    def test_each_check_reviews_only_what_the_latest_answer_changed(self):
        self.say("u1")
        self.say("u2")
        status = self.say("u3")
        first, _second, third = self.audits()[:3]
        self.assertEqual(first["previous_capture"]["workflow"]["steps"], [])
        self.assertEqual([item["id"] for item in third["previous_capture"]["workflow"]["steps"]], ["S1", "S2"])
        self.assertEqual([item["id"] for item in third["candidate_update"]["upsert_steps"]], ["S3"])
        self.assertEqual([(edge["from"], edge["to"]) for edge in third["proposed_routes_to_verify"]], [("S2", "S3")])
        graph = status["workflow_capture"]["workflow"]
        self.assertEqual([item["id"] for item in graph["steps"]], ["S1", "S2", "S3"])
        self.assertEqual([(edge["from"], edge["to"]) for edge in graph["connections"]], [("S1", "S2"), ("S2", "S3")])
        self.assertEqual(len(self.audits()), 3)

    def test_a_route_the_check_refuses_stays_off_the_map_when_later_answers_are_drawn(self):
        self.say("u1")
        # The reviewer quotes nothing for S1 to S2, and is still reading when the next answer arrives.
        self.client.unquoted.add(("S1", "S2"))
        reading, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold(_sent):
            reading.set()
            release.wait(10)
        self.client.hooks["team_working_map_source_audit"] = hold
        self.interview.send(SCRIPT["u2"]["say"])
        self.assertTrue(reading.wait(5))
        self.interview.send(SCRIPT["u3"]["say"])
        drawn = drawn_within(lambda: self.service.status(self.interview.payload()))
        # The map of the third answer is on screen while the check of the second still runs.
        self.assertEqual([(edge["from"], edge["to"]) for edge in drawn["workflow_capture"]["workflow"]["connections"]],
                         [("S1", "S2"), ("S2", "S3")])
        self.assertIs(drawn["workflow_checked"], False)
        del self.client.hooks["team_working_map_source_audit"]
        release.set()
        status = checked_within(lambda: self.service.status(self.interview.payload()))
        graph = status["workflow_capture"]["workflow"]
        self.assertEqual([item["id"] for item in graph["steps"]], ["S1", "S2", "S3"])
        # The refused route did not come back with the later draw; the later route was checked and stays.
        self.assertEqual([(edge["from"], edge["to"]) for edge in graph["connections"]], [("S2", "S3")])
        # What the check noted about the refused route is kept. Its question about S2 standing alone
        # is not: the later draw connected S2, and only what is still true of the map is asked.
        self.assertIn("What handoff or prerequisite, if any, connects Receive invoice to Log invoice (proposed condition: then)?",
                      graph["open_questions"])
        self.assertTrue(any("step S1 " in question for question in graph["open_questions"]), graph["open_questions"])
        self.assertFalse(any("step S2 " in question for question in graph["open_questions"]), graph["open_questions"])
        last = self.audits()[-1]
        self.assertEqual([item["id"] for item in last["candidate_update"]["upsert_steps"]], ["S3"])
        self.assertEqual([(edge["from"], edge["to"]) for edge in last["proposed_routes_to_verify"]], [("S2", "S3")])

    def test_a_withdrawn_step_reaches_the_check_with_the_quotation_the_draw_verified(self):
        script = copy.deepcopy(SCRIPT)
        script["u3"] = {"say": "Actually we no longer log the invoice in the register, that was dropped.",
                        "facts": [], "withdraw": ("u2", "we no longer log the invoice in the register")}
        self.client.script = script
        self.say("u1")
        self.say("u2")
        self.interview.answer(script["u3"]["say"])
        status = checked_within(lambda: self.service.status(self.interview.payload()))
        self.assertEqual([item["id"] for item in status["workflow_capture"]["workflow"]["steps"]], ["S1"])
        removal = self.audits()[-1]["candidate_update"]["remove_steps"]
        self.assertEqual([(row["id"], row["source_quote"], row["evidence_turns"]) for row in removal],
                         [("S2", "we no longer log the invoice in the register", ["u3"])])

    def test_a_drawn_map_that_is_not_a_later_state_of_the_checked_one_is_checked_whole(self):
        coordinator = self.client.coordinator
        work = {**account("u1", "u2"), "_map_only": True}
        unrelated = baseline({"title": "Invoice handling", "open_questions": [], "connections": [],
                              "steps": [step("X1", "Receive invoice", "Supplier", ["u1"])]})
        drawn = baseline({"title": "Invoice handling", "open_questions": [],
                          "steps": [step("S1", "Receive invoice", "Supplier", ["u1"]), step("S2", "Log invoice", "AP clerk", ["u2"])],
                          "connections": [{"from": "S1", "to": "S2", "label": "then", "evidence_turns": ["u2"]}]})
        checked = coordinator.workflow_check({**work, "previous_capture": unrelated, "_session_baseline": True}, drawn)
        audit = self.audits()[-1]
        self.assertEqual(audit["previous_capture"]["workflow"]["steps"], [], "The whole map is the update")
        self.assertEqual([item["id"] for item in audit["candidate_update"]["upsert_steps"]], ["S1", "S2"])
        self.assertEqual([item["id"] for item in checked["workflow"]["steps"]], ["S1", "S2"])

    def test_wrap_up_returns_the_map_with_its_check_state(self):
        self.say("u1")
        self.say("u2")
        # The second look is held until Wrap up has answered: with a stand-in that draws at once it
        # could be over before the reply is put together, and the reply would rightly say so.
        looking, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold(_sent):
            looking.set()
            release.wait(10)
        self.client.hooks["team_working_process_map"] = hold
        result = self.service.sync({**self.interview.payload(), "action": "close"})
        # The map is released at once. It was built answer by answer, so Wrap up looks at the whole
        # account once more, and until that look is done the map is not reported as final.
        self.assertEqual((result["workflow_state"], result["workflow_pending"]), ("ready", False))
        self.assertEqual((result["workflow_checked"], result["workflow_check_state"]), (False, "working"))
        self.assertEqual([item["id"] for item in result["workflow_capture"]["workflow"]["steps"]], ["S1", "S2"])
        self.assertTrue(looking.wait(5))
        release.set()
        query = {"conversation_token": result["conversation_token"], "revision": result["revision"]}
        final = checked_within(lambda: self.service.status_for_revision(query))
        # The second look added nothing here, so the map that was on screen stays, checked as it was.
        self.assertEqual([item["id"] for item in final["workflow_capture"]["workflow"]["steps"]], ["S1", "S2"])
        self.assertEqual(len(self.client.draws()), 3, "Two answers and one second look")
        self.assertEqual(len(self.audits()), 2, "The map that was kept is not checked again")


class DrawAllowance(unittest.TestCase):
    """Finding 3: a long first answer reached the draw's output allowance and the map was thrown away."""

    def setUp(self):
        self.client = RecordingTeam()

    def test_a_background_draw_cut_off_at_its_allowance_is_asked_for_once_more_with_a_larger_one(self):
        self.client.truncate = 1
        drawn = self.client.coordinator.workflow_draw({**account("u1"), "_map_only": True})
        orchestrator = server.interview_orchestrator
        self.assertEqual([body["max_output_tokens"] for body in self.client.draws()],
                         [orchestrator.MAP_DRAW_OUTPUT_TOKENS, orchestrator.MAP_DRAW_RETRY_OUTPUT_TOKENS])
        self.assertEqual([body["timeout"] for body in self.client.draws()],
                         [orchestrator.BACKGROUND_MAP_GENERATION_SECONDS, orchestrator.BACKGROUND_MAP_RETRY_SECONDS])
        self.assertEqual([item["id"] for item in drawn["capture"]["workflow"]["steps"]], ["S1"])

    def test_a_second_cut_off_reply_is_an_error_and_never_a_third_request(self):
        self.client.truncate = 5
        with self.assertRaises(server.OutputTruncated):
            self.client.coordinator.workflow_draw({**account("u1"), "_map_only": True})
        self.assertEqual(len(self.client.draws()), 2)

    def test_a_map_the_page_waits_for_is_not_drawn_twice(self):
        self.client.truncate = 1
        with self.assertRaises(server.OutputTruncated):
            self.client.coordinator.workflow(account("u1"))
        self.assertEqual(len(self.client.draws()), 1)

    def test_the_whole_operation_still_draws_and_checks_in_one_call(self):
        capture = self.client.coordinator.workflow({**account("u1", "u2"), "_map_only": True})
        self.assertEqual([body["name"] for body in self.client.bodies], ["team_working_process_map", "team_working_map_source_audit"])
        self.assertEqual([item["id"] for item in capture["workflow"]["steps"]], ["S1"])


EXCERPT = {"id": "doc_abc_c1", "label": "Section 1", "location": {},
           "text": "A supplier emails an invoice to the shared AP mailbox, per the AP manual."}
ACTIVE = {"documents": [{"id": "doc_abc", "name": "ap.txt", "excerpts": [EXCERPT]}]}
# The same file after Save for later: its excerpt is still handed over, as inactive evidence.
PARKED = {"documents": [], "retained_evidence": [{**EXCERPT, "document_id": "doc_abc", "name": "ap.txt",
                                                  "retained_only": True, "archived": True, "disposition": "parked"}]}
# The same excerpt when it is real but outside what one request can carry.
CARRIED = [{"id": "doc_abc_c1", "document_id": "doc_abc", "name": "ap.txt", "characters": 80}]


def route(start, end, sources, label="then"):
    return {"from": start, "to": end, "label": label, "evidence_turns": list(sources)}


class AFileTheCheckCannotRead(unittest.TestCase):
    """What a draw took from a file excerpt stays as drawn when the check can no longer read that excerpt.

    Found by review after the lanes were merged: the check measured "already on the map"
    against the last checked map, so a step drawn from a file that was then saved for later
    (or whose excerpt no longer fitted the request) was refused as new evidence from an
    inactive file. The whole-map fallback was refused the same way, before any request was
    sent, after every further answer.
    """

    def drawn(self):
        # S1 from the first answer; S2 and the route to it from the file; S3 and its route from the second answer.
        return baseline({"title": "Invoice handling", "open_questions": [],
                         "steps": [step("S1", "Receive invoice", "Supplier", ["u1"]),
                                   step("S2", "Log invoice", "AP clerk", ["doc_abc_c1"]),
                                   step("S3", "Approve invoice", "AP manager", ["u2"])],
                         "connections": [route("S1", "S2", ["doc_abc_c1"]), route("S2", "S3", ["u2"])]})

    def sources(self):
        return {"saved for later": {"_supporting_documents": copy.deepcopy(PARKED)},
                "outside the reading limit": {"_supporting_documents": {"documents": []},
                                              "_carried_document_sources": copy.deepcopy(CARRIED)}}

    def test_the_check_reviews_the_rest_and_keeps_what_cites_the_file_as_it_was_drawn(self):
        for name, sources in self.sources().items():
            with self.subTest(file=name):
                client = RecordingTeam()
                drawn = self.drawn()
                checked = client.coordinator.workflow_check({**account("u1", "u2"), **sources, "_map_only": True}, drawn)
                audits = client.sent("team_working_map_source_audit")
                self.assertEqual(len(audits), 1, "The check was sent")
                # What cites the file is part of the map the reviewer starts from, with the step its route needs.
                self.assertEqual([item["id"] for item in audits[0]["previous_capture"]["workflow"]["steps"]], ["S1", "S2"])
                self.assertEqual([(edge["from"], edge["to"]) for edge in audits[0]["previous_capture"]["workflow"]["connections"]],
                                 [("S1", "S2")])
                # The rest is reviewed like any difference.
                self.assertEqual([item["id"] for item in audits[0]["candidate_update"]["upsert_steps"]], ["S3"])
                self.assertEqual([(edge["from"], edge["to"]) for edge in audits[0]["proposed_routes_to_verify"]], [("S2", "S3")])
                # The checked map is the drawn one, in the order it was drawn.
                self.assertEqual(checked["workflow"]["steps"], drawn["workflow"]["steps"])
                self.assertEqual(checked["workflow"]["connections"], drawn["workflow"]["connections"])

    def test_a_checked_map_stays_the_baseline_and_only_the_difference_travels(self):
        for name, sources in self.sources().items():
            with self.subTest(file=name):
                client = RecordingTeam()
                drawn = self.drawn()
                earlier = baseline({"title": "Invoice handling", "open_questions": [], "connections": [],
                                    "steps": [step("S1", "Receive invoice", "Supplier", ["u1"])]})
                client.coordinator.workflow_check({**account("u1", "u2"), **sources, "_map_only": True,
                                                   "previous_capture": earlier, "_session_baseline": True}, drawn)
                audit = client.sent("team_working_map_source_audit")[0]
                self.assertEqual([item["id"] for item in audit["previous_capture"]["workflow"]["steps"]], ["S1", "S2"])
                self.assertEqual([item["id"] for item in audit["candidate_update"]["upsert_steps"]], ["S3"])

    def test_nothing_is_set_aside_while_every_cited_excerpt_can_be_read(self):
        payload = {**account("u1", "u2"), "_supporting_documents": copy.deepcopy(ACTIVE)}
        context, turns = server.validate_payload(payload, require_answers=False)
        evidence = server.document_evidence_catalog(payload["_supporting_documents"])
        empty = server.workflow_previous_capture(None, turns, evidence, {}, context=context)
        update = server.workflow_delta(empty, self.drawn())
        previous, kept = server.keep_unread_as_drawn(update, empty, evidence, {})
        self.assertIs(previous, empty)
        self.assertIs(kept, update)
        # And the review then sees every step, the one from the file included.
        client = RecordingTeam()
        client.coordinator.workflow_check({**payload, "_map_only": True}, self.drawn())
        audit = client.sent("team_working_map_source_audit")[0]
        self.assertEqual([item["id"] for item in audit["candidate_update"]["upsert_steps"]], ["S1", "S2", "S3"])

    def test_an_edit_that_cites_the_file_newly_is_still_refused_when_a_map_is_drawn(self):
        # The rule itself is unchanged: an inactive file establishes nothing in a draw.
        payload = {**account("u1", "u2"), "_supporting_documents": copy.deepcopy(PARKED)}
        context, turns = server.validate_payload(payload, require_answers=False)
        evidence = server.document_evidence_catalog(payload["_supporting_documents"])
        empty = server.workflow_previous_capture(None, turns, evidence, {}, context=context)
        with self.assertRaisesRegex(ValueError, "Inactive document evidence"):
            server.apply_workflow_update(server.workflow_delta(empty, self.drawn()), empty, turns, evidence, {}, context=context)

    def test_a_file_saved_for_later_during_a_check_does_not_stop_the_checks_that_follow(self):
        script = copy.deepcopy(SCRIPT)
        script["u1"]["cites"] = "shared AP mailbox"        # the step of the first answer also cites the file
        client = RecordingTeam(script)
        service = concurrent.ConcurrentInterview(client, server)
        self.addCleanup(service.close)
        interview = TypedInterview(service)
        reading, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold(_sent):
            if not reading.is_set():
                reading.set()
                release.wait(10)
        client.hooks["team_working_map_source_audit"] = hold
        interview.send(script["u1"]["say"], _supporting_documents=copy.deepcopy(ACTIVE))
        self.assertTrue(reading.wait(5))
        # The participant saves the file for later and answers again while the first check still reads.
        parked = lambda: service.status(interview.payload(_supporting_documents=copy.deepcopy(PARKED)))
        seen = []
        for turn in ("u2", "u3", "u4"):
            interview.send(script[turn]["say"], _supporting_documents=copy.deepcopy(PARKED))
            release.set()
            status = checked_within(parked)
            seen.append(status.get("workflow_check_state"))
        graph = status["workflow_capture"]["workflow"]
        self.assertEqual([item["id"] for item in graph["steps"]], ["S1", "S2", "S3", "S4"])
        self.assertEqual(graph["steps"][0]["evidence_turns"], ["u1", "doc_abc_c1"])
        self.assertEqual(seen, [None, None, None], "No check failed")
        later = client.sent("team_working_map_source_audit")[1:]
        self.assertGreaterEqual(len(later), 3, "Every answer after the file was set aside had its check")
        for audit in later:
            # The step from the file is on the map the reviewer starts from and is never proposed anew.
            self.assertIn("S1", [item["id"] for item in audit["previous_capture"]["workflow"]["steps"]])
            self.assertNotIn("S1", [item["id"] for item in audit["candidate_update"]["upsert_steps"]])


class AStepTheCheckTookOffAndALaterAnswerStatedAgain(unittest.TestCase):
    """Found by review: such a step came back alone, and no check ever saw the route into it."""

    def test_it_returns_with_its_routes_for_the_next_check(self):
        context, turns = server.validate_payload(account("u1", "u2", "u3"), require_answers=False)
        valid = lambda workflow: server.workflow_previous_capture(baseline(workflow), turns, None, (), context=context)
        first, second, third = (step("S1", "Receive invoice", "Supplier", ["u1"]), step("S2", "Log invoice", "AP clerk", ["u2"]),
                                step("S3", "Approve invoice", "AP manager", ["u3"]))
        title = {"title": "Invoice handling", "open_questions": []}
        checked_from = valid({**title, "steps": [first, second], "connections": [route("S1", "S2", ["u2"])]})
        # The check took the new step off; its route went with it.
        checked = valid({**title, "steps": [first], "connections": []})
        # Meanwhile the third answer was drawn: it says where the clerk logs the invoice and adds a step after that.
        restated = {**second, "system": "Invoice register", "evidence_turns": ["u2", "u3"]}
        drawn = valid({**title, "steps": [first, restated, third],
                       "connections": [route("S1", "S2", ["u2"]), route("S2", "S3", ["u3"])]})
        update = server.workflow_rebase_update(checked, checked_from, drawn)
        rebased = server.apply_workflow_update(update, checked, turns, None, (), context=context)
        self.assertEqual([item["id"] for item in rebased["workflow"]["steps"]], ["S1", "S2", "S3"])
        self.assertEqual({(edge["from"], edge["to"]) for edge in rebased["workflow"]["connections"]}, {("S1", "S2"), ("S2", "S3")})
        self.assertFalse(any("step S1 " in question for question in rebased["workflow"]["open_questions"]))
        # Nothing was checked by coming back: the next check is asked about the step and both routes.
        review = server.workflow_delta(checked, baseline(rebased["workflow"]))
        self.assertEqual([item["id"] for item in review["upsert_steps"]], ["S2", "S3"])
        self.assertEqual({(edge["from"], edge["to"]) for edge in review["upsert_connections"]}, {("S1", "S2"), ("S2", "S3")})

    def test_a_step_no_later_answer_touched_stays_off_and_takes_the_route_to_it_along(self):
        context, turns = server.validate_payload(account("u1", "u2", "u3"), require_answers=False)
        valid = lambda workflow: server.workflow_previous_capture(baseline(workflow), turns, None, (), context=context)
        first, second, third = (step("S1", "Receive invoice", "Supplier", ["u1"]), step("S2", "Log invoice", "AP clerk", ["u2"]),
                                step("S3", "Approve invoice", "AP manager", ["u3"]))
        title = {"title": "Invoice handling", "open_questions": []}
        checked_from = valid({**title, "steps": [first, second], "connections": [route("S1", "S2", ["u2"])]})
        checked = valid({**title, "steps": [first], "connections": []})
        drawn = valid({**title, "steps": [first, second, third],
                       "connections": [route("S1", "S2", ["u2"]), route("S2", "S3", ["u3"])]})
        update = server.workflow_rebase_update(checked, checked_from, drawn)
        rebased = server.apply_workflow_update(update, checked, turns, None, (), context=context)
        self.assertEqual([item["id"] for item in rebased["workflow"]["steps"]], ["S1", "S3"])
        self.assertEqual(rebased["workflow"]["connections"], [])

    def test_through_the_interview_the_route_is_reviewed_and_the_map_keeps_its_order(self):
        script = copy.deepcopy(SCRIPT)
        script["u3"]["revise"] = ("u2", {"system": "Invoice register"})
        client = RecordingTeam(script)
        service = concurrent.ConcurrentInterview(client, server)
        self.addCleanup(service.close)
        interview = TypedInterview(service)
        read = lambda: service.status(interview.payload())
        interview.send(script["u1"]["say"])
        checked_within(read)
        reading, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold(_sent):
            if not reading.is_set():
                reading.set()
                release.wait(10)
        client.hooks["team_working_map_source_audit"] = hold
        # The reviewer finds the step of the second answer unsupported, once.
        client.broken["team_working_map_source_audit"] = lambda result: result["discard_step_upserts"].append("S2")
        interview.send(script["u2"]["say"])
        self.assertTrue(reading.wait(5))
        interview.send(script["u3"]["say"])
        drawn = drawn_within(read)
        self.assertEqual([item["id"] for item in drawn["workflow_capture"]["workflow"]["steps"]], ["S1", "S2", "S3"])
        release.set()
        status = checked_within(read)
        graph = status["workflow_capture"]["workflow"]
        self.assertEqual([(item["id"], item["system"]) for item in graph["steps"]],
                         [("S1", "UNKNOWN"), ("S2", "Invoice register"), ("S3", "UNKNOWN")])
        self.assertEqual([(edge["from"], edge["to"]) for edge in graph["connections"]], [("S1", "S2"), ("S2", "S3")])
        last = client.sent("team_working_map_source_audit")[-1]
        self.assertEqual({(edge["from"], edge["to"]) for edge in last["proposed_routes_to_verify"]}, {("S1", "S2"), ("S2", "S3")})
        # The map carried under the later draw keeps the record of the models that made it.
        self.assertEqual([row["stage"] for row in status["workflow_capture"]["generated_by"]],
                         ["team_working_process_map", "team_working_map_source_audit"])


class TheMapKeepsItsRecord(unittest.TestCase):
    """Found by review: the background map had lost the record of the model and prompt behind it.

    The page files that record with a saved interview and prints it with an export. Only the
    whole operation was tracked; the draw and the check that replaced it in the background were not.
    """

    def setUp(self):
        self.client = RecordingTeam()
        self.service = concurrent.ConcurrentInterview(self.client, server)
        self.addCleanup(self.service.close)
        self.interview = TypedInterview(self.service)
        self.read = lambda: self.service.status(self.interview.payload())

    def record(self, status):
        return [(row["stage"], row["model"]) for row in status["workflow_capture"].get("generated_by", [])]

    def test_a_drawn_map_names_its_draw_and_a_checked_map_its_check_as_well(self):
        reading, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold(_sent):
            reading.set()
            release.wait(10)
        self.client.hooks["team_working_map_source_audit"] = hold
        self.interview.send(SCRIPT["u1"]["say"])
        self.assertTrue(reading.wait(5))
        drawn = drawn_within(self.read)
        self.assertEqual(self.record(drawn), [("team_working_process_map", "synthetic-process")])
        self.assertEqual(drawn["workflow_capture"]["app_version"], server.VERSION)
        del self.client.hooks["team_working_map_source_audit"]
        release.set()
        checked = checked_within(self.read)
        self.assertEqual(self.record(checked), [("team_working_process_map", "synthetic-process"),
                                                ("team_working_map_source_audit", "synthetic-process")])
        self.assertEqual(checked["workflow_capture"]["app_version"], server.VERSION)
        for row in checked["workflow_capture"]["generated_by"]:
            self.assertTrue(row["prompt_id"] and row["generated_at"], row)

    def test_the_record_follows_the_map_through_later_answers_one_row_a_stage(self):
        self.interview.send(SCRIPT["u1"]["say"])
        first = checked_within(self.read)["workflow_capture"]["generated_by"]
        reading, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def hold(_sent):
            reading.set()
            release.wait(10)
        self.client.hooks["team_working_map_source_audit"] = hold
        self.interview.send(SCRIPT["u2"]["say"])
        self.assertTrue(reading.wait(5))
        # Drawn again and not yet checked: the new draw, and the check the map before it had passed.
        drawn = drawn_within(self.read)["workflow_capture"]["generated_by"]
        self.assertEqual([row["stage"] for row in drawn], ["team_working_process_map", "team_working_map_source_audit"])
        self.assertNotEqual(drawn[0], first[0])
        self.assertEqual(drawn[1], first[1])
        del self.client.hooks["team_working_map_source_audit"]
        release.set()
        checked = checked_within(self.read)["workflow_capture"]["generated_by"]
        self.assertEqual([row["stage"] for row in checked], ["team_working_process_map", "team_working_map_source_audit"])
        self.assertEqual(checked[0], drawn[0])
        self.assertNotEqual(checked[1], first[1])
        # A baseline never carries the record into the next request.
        self.assertNotIn("generated_by", self.client.sent("team_working_process_map")[-1]["previous_capture"])


if __name__ == "__main__":
    unittest.main()
