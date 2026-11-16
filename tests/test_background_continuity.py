"""The typed and reviewed-voice path keeps its notes and its map between answers.

Every typed or dictated answer queues a background capture and a background map.
Each of them must continue from what this conversation last published: the notes
from the private fact ledger of the session's own last capture, the map from the
session's own last published map. Neither comes from the browser and neither gives
background work any authority to confirm, review or finish an interview.

Real ConcurrentInterview, real Coordinator, real HTTP handler and document store.
Only the four models are stand-ins. They follow their instructions in the simplest
way: the lead and the map model return what the answers add to the state they are
shown, and nothing else. No provider access.
"""
import copy
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_capture_facts import from_model_input, operation
from test_concurrent_http import ConversationProvider
from test_interview_orchestrator import SyntheticTeamProvider, prepared_review, reply_payload, reviewed_capture
from test_server import server

concurrent = server.local_module("concurrent_interview", "concurrent_interview.py")
STOP = "I need to stop now."
PAUSE_REPLY = "Of course. We can pause here and keep the unfinished parts open."
OPENING = "What starts this work?"
RANK = {"unknown": 0, "partial": 1, "captured": 2, "not_applicable": 2}
# One participant answer each: what the lead records from it and the step the map model draws.
SCRIPT = {
    "u1": {"say": "A supplier emails an invoice to the shared AP mailbox.",
           "facts": [("trigger", "A supplier email with an invoice starts the work.")],
           "step": ("Receive invoice", "Supplier")},
    "u2": {"say": "The AP clerk logs the invoice in the register.",
           "facts": [("lifecycle", "The AP clerk logs each invoice in the register.")],
           "step": ("Log invoice", "AP clerk")},
    "u3": {"say": "The AP manager approves each logged invoice in the portal.",
           "facts": [("checks", "The AP manager approves each logged invoice in the portal.")],
           "step": ("Approve invoice", "AP manager")},
    "u4": {"say": "Treasury releases the payment run every Thursday.",
           "facts": [("completion", "Treasury releases the payment run every Thursday.")],
           "step": ("Release payment", "Treasury")},
    "u5": {"say": "The AP clerk files the remittance advice in the shared drive.",
           "facts": [("materials", "The AP clerk files the remittance advice in the shared drive.")],
           "step": ("File remittance advice", "AP clerk")},
}


def step(identity, title, actor, sources):
    return {"id": identity, "title": title, "type": "activity", "actor": actor, "system": "UNKNOWN",
            "description": title + ".", "evidence_turns": list(sources), "input": "UNKNOWN", "output": "UNKNOWN",
            "completion_criteria": "UNKNOWN", "handoff": "UNKNOWN", "control_type": [], "data_origin": "",
            "entry_mode": "unknown", "rule_source_ref": "", "entity_scope": [], "parent_process": ""}


def excerpts(supporting):
    return [item for document in (supporting or {}).get("documents", []) for item in document.get("excerpts", [])]


def account(*answers):
    """A request as a direct route receives it: the scripted answers so far, no capability."""
    turns = []
    for number, key in enumerate(answers, 1):
        turns += [{"id": f"a{number}", "role": "assistant", "text": OPENING if number == 1 else "What happens next?"},
                  {"id": f"u{number}", "role": "user", "text": SCRIPT[key]["say"]}]
    return {"context": {"process_name": "Invoice handling", "process_owner": "AP team",
                        "objective": "Capture the current process",
                        "background": "Synthetic test fixture, not an actual company process"},
            "turns": turns, "action": "answer", "_supporting_documents": {}}


class ScriptedTeam(server.OpenAIClient):
    """The fast interviewer, the lead, the map model and the route reviewer of a typed interview."""

    def __init__(self, script=None):
        super().__init__({"OPENAI_API_KEY": "sk-offline-never-real", "AGENT_INTERVIEW_MODEL": "synthetic-lead",
                          "AGENT_COVERAGE_MODEL": "synthetic-coverage", "AGENT_PROCESS_MODEL": "synthetic-process",
                          "AGENT_DOCUMENT_MODEL": "synthetic-document"})
        self.script = copy.deepcopy(SCRIPT if script is None else script)
        self.calls = []
        # How many of the latest answers each model looks at. None: everything the state it is shown lacks.
        self.lead_window = None
        self.map_window = 1
        self.unquoted = set()       # (from, to) routes the reviewer returns without a passage
        self.broken = {}            # schema name -> callable(result) that damages one reply
        self.hooks = {}

    def request(self, path, body, content_type="application/json", timeout=90, on_text=None):
        if path != "responses" or not isinstance(body, dict):
            raise server.APIError("The scripted team has no such endpoint.", 503)
        name = body["text"]["format"]["name"]
        sent = json.loads(body["input"][0]["content"])
        if name in self.hooks:
            self.hooks[name](sent)
        self.calls.append({"name": name, "model": body["model"], "max_output_tokens": body["max_output_tokens"], "sent": sent})
        if name == "conversation_question":
            result = {"question": "What happens next?", "request_review": False}
        elif name == "team_interview_capture":
            result = self.capture(sent)
        elif name == "team_working_process_map":
            result = self.working_map(sent)
        elif name == "team_working_map_source_audit":
            result = self.map_audit(sent)
        else:
            raise AssertionError("Unexpected offline schema: " + name)
        if name in self.broken:
            self.broken.pop(name)(result)
        text = json.dumps(result)
        if on_text is not None:
            on_text(text)
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}

    def sent(self, name):
        return [call["sent"] for call in self.calls if call["name"] == name]

    def leads(self):
        return [call for call in self.calls if call["name"] == "team_interview_capture"]

    def maps(self):
        return self.sent("team_working_process_map")

    # ---- the lead: one fact transaction against the ledger it is shown ----
    def capture(self, sent):
        held = {fact["text"]: fact for fact in sent["fact_state"]["facts"]}
        answers = [turn["id"] for turn in sent["turns"] if turn["role"] == "user"]
        considered = answers if self.lead_window is None else answers[-self.lead_window:]
        shown = excerpts(sent.get("supporting_documents"))
        replaced = {old for turn in considered for _, old, _ in self.script.get(turn, {}).get("corrections", [])}
        operations, statuses = [], {}
        for turn in considered:
            entry = self.script.get(turn, {})
            sources = [turn] + [item["id"] for item in shown if entry.get("cites") and entry["cites"] in item["text"]]
            for topic, text in entry.get("facts", []):
                if text not in held and text not in replaced:
                    operations.append({**operation(topic, text, turn), "evidence_turns": sources})
                    statuses[topic] = entry.get("status", "partial")
            for topic, old, new in entry.get("corrections", []):
                if old in held:
                    operations.append(operation(topic, new, turn, op="replace", target=held[old]["id"],
                                                reason="participant_correction"))
                elif new not in held:
                    operations.append(operation(topic, new, turn))
                statuses[topic] = "partial"
        return from_model_input(sent, operations, statuses)

    # ---- the map model: targeted edits to the baseline it is shown ----
    def working_map(self, sent):
        previous = sent["previous_capture"]
        steps = {item["id"]: item for item in previous["workflow"]["steps"]}
        drawn = {source: item for item in steps.values() for source in item["evidence_turns"]}
        answers = [turn["id"] for turn in sent["turns"] if turn["role"] == "user"]
        considered = answers if self.map_window is None else answers[-self.map_window:]
        shown = excerpts(sent.get("supporting_documents"))
        number = max([int(identity[1:]) for identity in steps if identity[1:].isdigit()], default=0)
        last = list(steps)[-1] if steps else None
        upserts, routes, removals = [], [], []
        for turn in considered:
            entry = self.script.get(turn, {})
            if "step" in entry and turn not in drawn:
                number += 1
                title, actor = entry["step"]
                sources = [turn] + [item["id"] for item in shown if entry.get("cites") and entry["cites"] in item["text"]]
                upserts.append(step(f"S{number}", title, actor, sources))
                if last:
                    routes.append({"from": last, "to": f"S{number}", "label": "then", "evidence_turns": [turn]})
                last = f"S{number}"
            if "revise" in entry and entry["revise"][0] in drawn:
                target, changes = entry["revise"]
                upserts.append({**drawn[target], **changes, "evidence_turns": drawn[target]["evidence_turns"] + [turn]})
            if "withdraw" in entry and entry["withdraw"][0] in drawn:
                target, quote = entry["withdraw"]
                removals.append({"id": drawn[target]["id"], "reason": "The participant withdrew this step.",
                                 "source_quote": quote, "evidence_turns": [turn]})
        return {"title": "Invoice handling", "upsert_steps": upserts, "remove_steps": removals,
                "upsert_connections": routes, "remove_connections": [],
                "open_questions": previous["workflow"]["open_questions"], "memo_findings": [],
                "summary": "Scripted map.", "focus": "Walk through the invoice route", "parking_lot": []}

    # ---- the route reviewer: quotes the cited answer for each route it is asked about ----
    def map_audit(self, sent):
        update = sent["candidate_update"]
        spoken = {turn["id"]: turn["text"] for turn in sent["turns"] if turn["role"] == "user"}
        support = [{"from": edge["from"], "to": edge["to"], "label": edge["label"],
                    "passages": [] if (edge["from"], edge["to"]) in self.unquoted else
                    [{"source_id": source, "quote": spoken[source]} for source in edge["evidence_turns"] if source in spoken]}
                   for edge in sent["proposed_routes_to_verify"]]
        return {"title": update["title"], "discard_step_upserts": [], "discard_connection_upserts": [],
                "discard_step_removals": [], "discard_connection_removals": [], "remove_connections": [],
                "route_support": support, "upsert_steps": [], "upsert_connections": [], "memo_findings": [],
                "open_questions": update["open_questions"], "summary": update["summary"], "focus": update["focus"],
                "parking_lot": update["parking_lot"]}


def settled(read, seconds=15):
    """Poll until the notes and the map of this snapshot have both finished.

    A capture that failed queues no map, so that state is final by itself.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = read()
        if status["state"] == "error" or (status["state"] == "ready" and status["workflow_state"] in ("ready", "error")):
            return status
        time.sleep(.01)
    raise AssertionError("Background analysis did not settle")


class TypedInterview:
    """Plays the browser on the typed path: an answer, then the status polls until both products settle.

    Like the browser before the first Wrap up, it holds no capture token and sends no map.
    """

    def __init__(self, service, prefix="", **extra):
        self.service, self.prefix, self.extra = service, prefix, extra
        self.turns, self.token, self.question, self.count = [], None, OPENING, 0
        self.context = {"process_name": "Invoice handling", "process_owner": "AP team",
                        "objective": "Capture the current process",
                        "background": "Synthetic test fixture, not an actual company process"}

    def payload(self, **more):
        return {"context": copy.deepcopy(self.context),
                "turns": copy.deepcopy(self.turns), "action": "answer", "_supporting_documents": {},
                **({"conversation_token": self.token} if self.token else {}), **copy.deepcopy(self.extra), **more}

    def send(self, text, **more):
        self.count += 1
        self.turns += [{"id": f"{self.prefix}a{self.count}", "role": "assistant", "text": self.question},
                       {"id": f"{self.prefix}u{self.count}", "role": "user", "text": text}]
        reply = self.service.turn(self.payload(**more))
        self.token, self.question = reply["conversation_token"], reply["question"]
        return reply

    def answer(self, text, **more):
        self.send(text, **more)
        return self.status()

    def status(self):
        return settled(lambda: self.service.status(self.payload()))

    def session(self):
        return self.service._sessions[self.token]


def notes(status):
    return {item["key"]: item for item in status["capture"]["memo_findings"]}


def graph(status):
    return status["workflow_capture"]["workflow"]


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.client = ScriptedTeam()
        self.service = concurrent.ConcurrentInterview(self.client, server)
        self.addCleanup(self.service.close)
        self.interview = TypedInterview(self.service)

    def say(self, turn):
        return self.interview.answer(SCRIPT[turn]["say"])


class NotesContinueBetweenAnswers(ServiceCase):
    def test_second_capture_receives_the_first_capture_s_facts_on_the_lead_model(self):
        # Past 6,000 characters of transcript an empty ledger is a "long-history rebuild":
        # the document model with a 12,000-token allowance. A continued ledger is neither.
        padding = " The participant supplied additional process detail." * 70
        first = self.interview.answer(SCRIPT["u1"]["say"] + padding)
        self.assertGreater(sum(len(turn["text"]) for turn in self.interview.turns), 3000)
        second = self.interview.answer(SCRIPT["u2"]["say"] + padding)
        self.assertGreater(sum(len(turn["text"]) for turn in self.interview.turns), 6000)
        one, two = self.client.leads()
        self.assertEqual(one["sent"]["fact_state"]["facts"], [], "Nothing was captured before the first answer")
        self.assertEqual([fact["text"] for fact in two["sent"]["fact_state"]["facts"]],
                         [SCRIPT["u1"]["facts"][0][1]])
        self.assertEqual((two["model"], two["max_output_tokens"]), ("synthetic-lead", 6500))
        self.assertEqual(notes(second)["trigger"]["answer"], notes(first)["trigger"]["answer"])
        self.assertEqual(notes(second)["lifecycle"]["evidence_turns"], ["u2"])
        # The capability and the server's flag are routing, never model input or published state.
        for call in self.client.calls:
            self.assertNotIn("capture_token", call["sent"])
            self.assertNotIn("_facts_only", json.dumps(call["sent"]))
        self.assertNotIn("_facts_only", json.dumps(second))

    def test_the_lead_changes_only_what_the_new_answer_adds(self):
        for turn in ("u1", "u2", "u3", "u4"):
            self.say(turn)
        ledgers = [[fact["text"] for fact in call["sent"]["fact_state"]["facts"]] for call in self.client.leads()]
        expected = [SCRIPT[turn]["facts"][0][1] for turn in ("u1", "u2", "u3")]
        self.assertEqual(ledgers, [expected[:count] for count in range(4)])
        # Fact identity is kept too: the application's IDs do not change from answer to answer.
        identities = [{fact["text"]: fact["id"] for fact in call["sent"]["fact_state"]["facts"]} for call in self.client.leads()]
        self.assertEqual(identities[3][expected[0]], identities[1][expected[0]])

    def test_a_partial_delta_never_removes_or_demotes_what_earlier_answers_established(self):
        # The lead restates only the latest answer. Omission retains: that is the ledger's
        # promise, and it has to hold on this path as well.
        self.client.lead_window = 1
        self.client.script["u3"]["status"] = "captured"
        history = []
        for turn in ("u1", "u2", "u3", "u4", "u5"):
            history.append(notes(self.say(turn)))
        for earlier, later in zip(history, history[1:]):
            for key in server.COVERAGE:
                with self.subTest(topic=key):
                    self.assertGreaterEqual(RANK[later[key]["status"]], RANK[earlier[key]["status"]])
                    if earlier[key]["status"] != "unknown":
                        self.assertEqual(later[key]["answer"], earlier[key]["answer"])
                        self.assertEqual(later[key]["evidence_turns"], earlier[key]["evidence_turns"])
        final = history[-1]
        self.assertEqual({key for key in final if final[key]["status"] != "unknown"} - {"name"},
                         {"trigger", "lifecycle", "checks", "completion", "materials"})
        self.assertEqual(final["checks"]["status"], "captured")
        self.assertEqual(sorted(source for item in final.values() for source in item["evidence_turns"] if source != "context"),
                         ["u1", "u2", "u3", "u4", "u5"])

    def test_an_empty_delta_keeps_every_published_note(self):
        self.client.lead_window = 1
        del self.client.script["u2"]
        first = self.say("u1")
        second = self.interview.answer("Nothing changes for the second invoice.")
        self.assertEqual(self.client.leads()[1]["sent"]["fact_state"]["facts"][0]["text"], SCRIPT["u1"]["facts"][0][1])
        self.assertEqual(notes(second)["trigger"], notes(first)["trigger"])

    def test_a_correction_replaces_the_fact_it_corrects_and_nothing_else(self):
        self.say("u1")
        self.say("u2")
        before = notes(self.say("u3"))
        self.client.script["u4"] = {"say": "Correction: the controller approves each logged invoice, not the AP manager.",
                                    "corrections": [("checks", SCRIPT["u3"]["facts"][0][1],
                                                     "The controller approves each logged invoice in the portal.")]}
        after = notes(self.interview.answer(self.client.script["u4"]["say"]))
        self.assertEqual(after["checks"]["answer"], "The controller approves each logged invoice in the portal.")
        self.assertEqual(after["checks"]["evidence_turns"], ["u4"])
        for key in ("trigger", "lifecycle"):
            self.assertEqual(after[key], before[key])
        ledger = self.client.leads()[-1]["sent"]["fact_state"]["facts"]
        self.assertEqual(len(ledger), 3, "The correction was applied to the continued ledger, not to a rebuild")

    def test_a_stop_request_in_the_middle_changes_nothing_and_the_ledger_continues(self):
        # The stop request is the third answer (u3); the account goes on with the fourth.
        self.client.script = {"u1": SCRIPT["u1"], "u2": SCRIPT["u2"], "u4": SCRIPT["u3"]}
        self.say("u1")
        before = self.say("u2")
        kept = copy.deepcopy(self.interview.session()["capture"])
        reply = self.interview.send(STOP)
        self.assertEqual(reply["speech_authorization"]["kind"], "pause")
        stopped = self.interview.status()
        self.assertIs(stopped.get("capture_preserved"), True)
        self.assertNotIn("capture", stopped)
        self.assertEqual(self.interview.session()["capture"], kept)
        self.assertEqual(len(self.client.leads()), 2, "A stop request is not analysed")
        resumed = self.interview.answer(SCRIPT["u3"]["say"])
        sent = self.client.leads()[2]["sent"]
        self.assertEqual([fact["text"] for fact in sent["fact_state"]["facts"]],
                         [SCRIPT["u1"]["facts"][0][1], SCRIPT["u2"]["facts"][0][1]])
        for key in ("trigger", "lifecycle"):
            self.assertEqual(notes(resumed)[key], notes(before)[key])
        self.assertEqual(notes(resumed)["checks"]["evidence_turns"], ["u4"])

    def test_a_renamed_process_keeps_the_notes_and_the_map(self):
        # The intake context is a source of its own. Changing it retires what cites it,
        # not what the participant said.
        self.say("u1")
        before = self.say("u2")
        self.interview.context["process_name"] = "Supplier invoice handling"
        after = self.say("u3")
        self.assertEqual([fact["text"] for fact in self.client.leads()[2]["sent"]["fact_state"]["facts"]],
                         [SCRIPT["u1"]["facts"][0][1], SCRIPT["u2"]["facts"][0][1]])
        self.assertEqual([item["id"] for item in self.client.maps()[2]["previous_capture"]["workflow"]["steps"]], ["S1", "S2"])
        for key in ("trigger", "lifecycle"):
            self.assertEqual(notes(after)[key], notes(before)[key])
        self.assertEqual(graph(after)["steps"][:2], graph(before)["steps"])

    def test_an_edited_earlier_answer_is_rebuilt_from_the_transcript(self):
        self.say("u1")
        self.say("u2")
        self.interview.turns[1]["text"] = "A buyer forwards an invoice to the shared AP mailbox."
        self.client.script["u1"] = {"say": self.interview.turns[1]["text"],
                                    "facts": [("trigger", "A buyer forwarding an invoice starts the work.")],
                                    "step": ("Receive invoice", "Buyer")}
        third = self.say("u3")
        sent = self.client.leads()[2]["sent"]
        self.assertEqual(sent["fact_state"]["facts"], [], "An edited account is never continued from the old ledger")
        self.assertEqual(notes(third)["trigger"]["answer"], "A buyer forwarding an invoice starts the work.")
        self.assertEqual(self.client.maps()[2]["previous_capture"]["workflow"]["steps"], [],
                         "Nor is its map continued from the old one")

    def test_another_conversation_s_capability_sent_by_a_browser_is_never_the_ledger_base(self):
        self.say("u1")
        other = self.interview.session()["capture"]["capture_token"]
        stranger = TypedInterview(self.service, "x", capture_token=other, review_ticket="forged-ticket",
                                  _facts_only=True, _session_baseline=True)
        self.client.script["xu1"] = {"say": "We reconcile the bank account every morning.",
                                     "facts": [("trigger", "The bank reconciliation starts every morning.")],
                                     "step": ("Reconcile bank account", "Accountant")}
        stranger.answer(self.client.script["xu1"]["say"])
        first = self.client.leads()[1]["sent"]
        self.assertEqual(first["fact_state"]["facts"], [], "A browser cannot point background work at a ledger")
        self.assertEqual(self.client.maps()[1]["previous_capture"]["workflow"]["steps"], [])
        stranger.answer("The controller signs the reconciliation.")
        self.assertEqual([fact["text"] for fact in self.client.leads()[2]["sent"]["fact_state"]["facts"]],
                         ["The bank reconciliation starts every morning."], "Its own notes, and only those")
        self.assertEqual([item["title"] for item in self.client.maps()[2]["previous_capture"]["workflow"]["steps"]],
                         ["Reconcile bank account"])
        # The first conversation is untouched by the other one and still continues its own notes.
        self.say("u2")
        self.assertEqual([fact["text"] for fact in self.client.leads()[3]["sent"]["fact_state"]["facts"]],
                         [SCRIPT["u1"]["facts"][0][1]])

    def test_wrap_up_after_the_fast_question_continues_the_ledger_too(self):
        padding = " The participant supplied additional process detail." * 70
        self.interview.answer(SCRIPT["u1"]["say"] + padding)
        self.interview.answer(SCRIPT["u2"]["say"] + padding)
        wrap = self.interview.payload(action="close")
        wrap["turns"].append({"id": "a_fast", "role": "assistant", "text": self.interview.question})
        result = self.service.sync(wrap, timeout=15)
        self.assertEqual(len(self.client.leads()), 2, "Appending only the fast question keeps the capture.")
        self.assertIn(result["speech_authorization"]["kind"], ("question", "pause"))
        self.assertEqual({item["key"] for item in result["memo_findings"] if item["status"] != "unknown"},
                         {"trigger", "lifecycle"})
        self.assertIn("workflow_capture", result)

    def test_wrap_up_holding_an_older_capability_continues_the_conversation_s_latest_notes(self):
        # A file follow-up (or a capture from before the participant typed) leaves the browser
        # with a capability of its own, older than the notes the conversation has since
        # published. Wrap up sends it. Its ledger must not replace the latest notes.
        self.client.lead_window = 1
        self.say("u1")
        held = self.client.coordinator.interview(self.interview.payload())
        self.assertEqual({item["key"] for item in held["memo_findings"] if item["status"] != "unknown"}, {"trigger"})
        self.interview.extra["capture_token"] = held["capture_token"]
        for turn in ("u2", "u3"):
            self.say(turn)
        before = notes(self.say("u4"))
        wrap = self.interview.payload(action="close")
        wrap["turns"].append({"id": "a_fast", "role": "assistant", "text": self.interview.question})
        result = self.service.sync(wrap, timeout=15)
        lead = self.client.leads()[-1]
        self.assertEqual(lead["sent"]["action"], "close", "The browser's capability keeps its own path and meaning")
        self.assertEqual([fact["text"] for fact in lead["sent"]["fact_state"]["facts"]],
                         [SCRIPT[turn]["facts"][0][1] for turn in ("u1", "u2", "u3", "u4")])
        self.assertEqual((lead["model"], lead["max_output_tokens"]), ("synthetic-lead", 6500))
        after = {item["key"]: item for item in result["memo_findings"]}
        for key in ("trigger", "lifecycle", "checks", "completion"):
            self.assertEqual(after[key], before[key])
        self.assertNotIn("_ledger_token", json.dumps(result))
        self.assertNotIn("_ledger_token", json.dumps(lead["sent"]))
        # The capture Wrap up made is the conversation's latest: the next answer continues it.
        self.interview.turns.append({"id": "a_fast", "role": "assistant", "text": self.interview.question})
        self.interview.question = result["question"]
        self.interview.extra["capture_token"] = result["capture_token"]
        self.interview.count = 4
        self.say("u5")
        self.assertEqual(len(self.client.leads()[-1]["sent"]["fact_state"]["facts"]), 4)

    def test_a_ledger_capability_in_a_wrap_up_payload_is_ignored(self):
        # Only the server names a second ledger, and only its session's own. The HTTP boundary
        # drops a posted _ledger_token; a Wrap up that reaches the service with one drops it too.
        older = self.client.coordinator.interview(account("u1"))
        newer = self.client.coordinator.interview(account("u1", "u2"))
        self.service.sync({**account("u1", "u2", "u3"), "action": "close", "capture_token": older["capture_token"],
                           "_ledger_token": newer["capture_token"]}, timeout=15)
        self.assertEqual([fact["text"] for fact in self.client.leads()[2]["sent"]["fact_state"]["facts"]],
                         [SCRIPT["u1"]["facts"][0][1]])

    def test_a_full_topic_retains_its_facts_and_other_topics_can_continue(self):
        long_fact = "The AP clerk checks the invoice against the purchase order line by line " + "and records it " * 90
        for number in range(1, 10):
            self.client.script[f"u{number}"] = {"say": f"Detail {number} of the register check.",
                                                "facts": [("lifecycle", f"{long_fact}in pass {number}.")]}
        statuses = [self.interview.answer(self.client.script[f"u{number}"]["say"])["state"] for number in range(1, 9)]
        self.assertEqual(statuses, ["ready"] * 8)
        capped = self.interview.answer(self.client.script["u9"]["say"])
        self.assertEqual(capped["state"], "ready")
        self.assertEqual(capped["capture"]["consolidation_required"], ["lifecycle"])
        self.assertEqual(len(notes(capped)["lifecycle"]["evidence_turns"]), 8)
        self.assertEqual(len(self.client.leads()[8]["sent"]["fact_state"]["facts"]), 8)
        self.client.script["u10"] = {"say":"The registrar owns the outcome.", "facts":[("accountable", "The registrar owns the outcome.")]}
        continued = self.interview.answer(self.client.script["u10"]["say"])
        self.assertEqual(continued["state"], "ready")
        self.assertIn("u10", notes(continued)["accountable"]["evidence_turns"])
        self.assertEqual(len(notes(continued)["lifecycle"]["evidence_turns"]), 8)

    def test_a_provider_failure_keeps_the_ledger_for_the_next_capture(self):
        first = self.say("u1")

        def down(_sent):
            del self.client.hooks["team_interview_capture"]
            raise server.APIError("The provider is unavailable.", 503)
        self.client.hooks["team_interview_capture"] = down
        self.assertEqual(self.say("u2")["state"], "error")
        third = self.say("u3")
        self.assertEqual([fact["text"] for fact in self.client.leads()[-1]["sent"]["fact_state"]["facts"]],
                         [SCRIPT["u1"]["facts"][0][1]], "A failed request says nothing about the ledger")
        self.assertEqual(notes(third)["trigger"], notes(first)["trigger"])
        self.assertEqual((notes(third)["lifecycle"]["evidence_turns"], notes(third)["checks"]["evidence_turns"]), (["u2"], ["u3"]))

    def test_wrap_up_retry_after_a_refused_delta_rebuilds(self):
        self.say("u1")

        def stale(result):
            result["base_revision"] = "0" * 64
        self.client.broken["team_interview_capture"] = stale
        self.assertEqual(self.say("u2")["state"], "error")
        wrap = self.interview.payload(action="close")
        wrap["turns"].append({"id": "a_fast", "role": "assistant", "text": self.interview.question})
        result = self.service.sync(wrap, timeout=15)
        retried = self.client.leads()[2]["sent"]
        self.assertEqual(retried["fact_state"]["facts"], [], "The explicit retry does not repeat the refused base")
        self.assertEqual({item["key"] for item in result["memo_findings"] if item["status"] != "unknown"},
                         {"trigger", "lifecycle"})


    def test_wrap_up_with_a_capability_after_a_refused_delta_recaptures_as_well(self):
        # After a first Wrap up the browser holds a capability of this same conversation. Its
        # ledger is the one that refused the transaction; sending it must not undo the recovery.
        self.say("u1")
        wrap = self.interview.payload(action="close")
        wrap["turns"].append({"id": "a_fast", "role": "assistant", "text": self.interview.question})
        held = self.service.sync(wrap, timeout=15)
        self.interview.turns.append({"id": "a_fast", "role": "assistant", "text": self.interview.question})
        self.interview.question = held["question"]
        self.interview.extra["capture_token"] = held["capture_token"]

        def stale(result):
            result["base_revision"] = "0" * 64
        self.client.broken["team_interview_capture"] = stale
        self.assertEqual(self.say("u2")["state"], "error")
        self.assertEqual(len(self.client.leads()[-1]["sent"]["fact_state"]["facts"]), 1)
        again = self.interview.payload(action="close")
        again["turns"].append({"id": "a_fast_two", "role": "assistant", "text": self.interview.question})
        result = self.service.sync(again, timeout=15)
        lead = self.client.leads()[-1]["sent"]
        self.assertEqual((lead["action"], lead["fact_state"]["facts"]), ("close", []))
        self.assertEqual({item["key"] for item in result["memo_findings"] if item["status"] != "unknown"},
                         {"trigger", "lifecycle"})
        # The recaptured notes are the conversation's latest; the next answer continues them.
        self.interview.turns.append({"id": "a_fast_two", "role": "assistant", "text": self.interview.question})
        self.interview.question = result["question"]
        self.interview.extra["capture_token"] = result["capture_token"]
        self.say("u3")
        self.assertEqual(len(self.client.leads()[-1]["sent"]["fact_state"]["facts"]), 2)


class NotesWithAReferenceFile(ServiceCase):
    DOCS = {"source_versions": [{"id": "source1", "source_revision": "a" * 64}],
            "documents": [{"id": "source1", "name": "Procedure", "source_revision": "a" * 64,
                           "review": {"phase": "complete"},
                           "excerpts": [{"id": "doc_rule", "text": "The analyst checks the invoice."}]}]}

    def test_an_unchanged_file_uses_the_document_model_for_the_first_capture_only(self):
        self.interview.extra["_supporting_documents"] = copy.deepcopy(self.DOCS)
        self.client.script["u1"]["cites"] = "analyst checks"
        for turn in ("u1", "u2", "u3"):
            status = self.say(turn)
            self.assertEqual(status["state"], "ready", status)
        self.assertEqual([(call["model"], call["max_output_tokens"]) for call in self.client.leads()],
                         [("synthetic-document", 12000), ("synthetic-lead", 6500), ("synthetic-lead", 6500)])
        self.assertEqual(notes(status)["trigger"]["evidence_turns"], ["u1", "doc_rule"])

    def test_a_file_citation_the_request_cannot_read_back_restarts_the_notes_instead_of_failing(self):
        # Over HTTP a new answer's selection reads or confirms what the session cites (see
        # the HTTP cases). Should a citation ever not come back although its file is
        # unchanged, background work must not stop: before the ledger was continued, it
        # could not fail this way. The account is captured from its sources instead.
        self.interview.extra["_supporting_documents"] = copy.deepcopy(self.DOCS)
        self.client.script["u1"]["cites"] = "analyst checks"
        self.say("u1")
        moved = copy.deepcopy(self.DOCS)
        moved["documents"][0]["excerpts"] = [{"id": "doc_other", "text": "The manager signs the register."}]
        self.interview.extra["_supporting_documents"] = moved
        del self.client.script["u1"]["cites"]
        self.client.script["u2"]["cites"] = "manager signs"
        status = self.say("u2")
        self.assertEqual((status["state"], status["workflow_state"]), ("ready", "ready"), status)
        self.assertEqual(self.client.leads()[1]["sent"]["fact_state"]["facts"], [])
        self.assertEqual(self.client.maps()[1]["previous_capture"]["workflow"]["steps"], [])
        self.assertEqual(notes(status)["trigger"]["evidence_turns"], ["u1"])
        self.assertEqual(notes(status)["lifecycle"]["evidence_turns"], ["u2", "doc_other"])
        # A request that holds a capability itself (Live voice, a file follow-up) is still
        # refused in that situation, with the notes left as they are.
        held = {**self.interview.payload(), "capture_token": self.interview.session()["capture"]["capture_token"],
                "_supporting_documents": copy.deepcopy(self.DOCS)}
        held["turns"] += [{"id": "a3", "role": "assistant", "text": status["capture"]["question"]},
                          {"id": "u3", "role": "user", "text": SCRIPT["u3"]["say"]}]
        with self.assertRaisesRegex(server.APIError, "could not read back"):
            self.client.coordinator.interview(held)

    def test_a_replaced_file_retires_what_cited_it_and_is_read_as_a_new_baseline(self):
        self.interview.extra["_supporting_documents"] = copy.deepcopy(self.DOCS)
        self.client.script["u1"]["cites"] = "analyst checks"
        self.say("u1")
        changed = copy.deepcopy(self.DOCS)
        changed["source_versions"][0]["source_revision"] = changed["documents"][0]["source_revision"] = "b" * 64
        changed["documents"][0]["excerpts"] = [{"id": "doc_rule_v2", "text": "The controller checks the invoice."}]
        self.interview.extra["_supporting_documents"] = changed
        status = self.say("u2")
        self.assertEqual(status["state"], "ready", status)
        second = self.client.leads()[1]
        self.assertEqual(second["model"], "synthetic-document")
        carried = second["sent"]["fact_state"]["facts"]
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["evidence_turns"], ["u1"])
        self.assertIn(carried[0]["id"], second["sent"]["fact_state"]["reconciliation_targets"])


class MapContinuesBetweenAnswers(ServiceCase):
    def test_second_map_request_starts_from_the_first_published_map(self):
        first = self.say("u1")
        self.say("u2")
        one, two = self.client.maps()
        self.assertEqual(one["previous_capture"]["workflow"]["steps"], [])
        baseline = two["previous_capture"]
        self.assertEqual(set(baseline), {"workflow", "memo_findings", "summary", "focus", "parking_lot"})
        self.assertEqual(set(baseline["workflow"]), {"title", "steps", "connections", "open_questions"})
        self.assertEqual(baseline["workflow"], graph(first))
        published = first["workflow_capture"]
        self.assertEqual([baseline[key] for key in ("memo_findings", "summary", "focus", "parking_lot")],
                         [published[key] for key in ("memo_findings", "summary", "focus", "parking_lot")])
        # Neither request, nor anything published, carries the server's marker.
        for call in self.client.calls:
            self.assertNotIn("_session_baseline", json.dumps(call["sent"]))
        self.assertNotIn("_session_baseline", json.dumps(self.interview.status()))

    def test_untouched_steps_and_accepted_routes_stay_exactly_as_they_were(self):
        history = [graph(self.say(turn)) for turn in ("u1", "u2", "u3", "u4", "u5")]
        self.assertEqual([[item["id"] for item in workflow["steps"]] for workflow in history],
                         [["S1", "S2", "S3", "S4", "S5"][:count] for count in range(1, 6)])
        for earlier, later in zip(history, history[1:]):
            self.assertEqual(later["steps"][:len(earlier["steps"])], earlier["steps"], "IDs, titles, owners and sources")
            self.assertEqual(later["connections"][:len(earlier["connections"])], earlier["connections"])
        self.assertEqual([(edge["from"], edge["to"]) for edge in history[-1]["connections"]],
                         [("S1", "S2"), ("S2", "S3"), ("S3", "S4"), ("S4", "S5")])
        # Each review is asked about the one new route, never again about an accepted one.
        asked = [[(edge["from"], edge["to"]) for edge in sent["proposed_routes_to_verify"]]
                 for sent in self.client.sent("team_working_map_source_audit")]
        self.assertEqual(asked, [[], [("S1", "S2")], [("S2", "S3")], [("S3", "S4")], [("S4", "S5")]])

    def test_a_reviewer_that_quotes_nothing_later_cannot_cost_an_accepted_route(self):
        self.say("u1")
        accepted = graph(self.say("u2"))["connections"]
        self.client.unquoted = {("S1", "S2"), ("S2", "S3")}
        later = graph(self.say("u3"))
        self.assertEqual(later["connections"], accepted, "The accepted route stays; the unquoted new one is a question")
        self.assertTrue(any("Log invoice" in question and "Approve invoice" in question for question in later["open_questions"]))

    def test_a_correction_revises_the_corrected_step_under_its_own_id(self):
        for turn in ("u1", "u2", "u3"):
            before = graph(self.say(turn))
        self.client.script["u4"] = {"say": "Correction: the controller approves each logged invoice, not the AP manager.",
                                    "revise": ("u3", {"actor": "Controller", "description": "The controller approves each logged invoice."})}
        after = graph(self.interview.answer(self.client.script["u4"]["say"]))
        self.assertEqual([item["id"] for item in after["steps"]], ["S1", "S2", "S3"])
        self.assertEqual(after["steps"][:2], before["steps"][:2])
        self.assertEqual((after["steps"][2]["actor"], after["steps"][2]["evidence_turns"]), ("Controller", ["u3", "u4"]))
        self.assertEqual(after["connections"], before["connections"])

    def test_a_withdrawn_step_is_removed_with_its_routes_and_no_other(self):
        for turn in ("u1", "u2", "u3"):
            self.say(turn)
        self.client.script["u4"] = {"say": "Actually nobody approves in the portal any more; drop that step.",
                                    "withdraw": ("u3", "nobody approves in the portal any more")}
        after = graph(self.interview.answer(self.client.script["u4"]["say"]))
        self.assertEqual([item["id"] for item in after["steps"]], ["S1", "S2"])
        self.assertEqual([(edge["from"], edge["to"]) for edge in after["connections"]], [("S1", "S2")])
        # The steps that were not withdrawn are the same ones after the next answer as well.
        final = graph(self.interview.answer(SCRIPT["u5"]["say"]))
        self.assertEqual(final["steps"][:2], after["steps"])
        self.assertEqual([item["title"] for item in final["steps"]], ["Receive invoice", "Log invoice", "File remittance advice"])

    def test_a_stop_request_in_the_middle_leaves_the_map_as_it_was(self):
        # The stop request is the third answer (u3); the account goes on with the fourth.
        self.client.script = {"u1": SCRIPT["u1"], "u2": SCRIPT["u2"], "u4": SCRIPT["u3"]}
        self.say("u1")
        before = self.say("u2")
        self.interview.send(STOP)
        stopped = self.interview.status()
        self.assertEqual(stopped["workflow_state"], "ready")
        self.assertEqual(graph(stopped), graph(before))
        resumed = graph(self.interview.answer(SCRIPT["u3"]["say"]))
        self.assertEqual(resumed["steps"][:2], graph(before)["steps"])
        self.assertEqual([item["id"] for item in resumed["steps"]], ["S1", "S2", "S3"])
        self.assertEqual(resumed["connections"][0], graph(before)["connections"][0])

    def test_a_baseline_that_no_longer_validates_falls_back_to_the_empty_baseline(self):
        documents = copy.deepcopy(NotesWithAReferenceFile.DOCS)
        self.interview.extra["_supporting_documents"] = documents
        self.client.script["u1"]["cites"] = "analyst checks"
        first = graph(self.say("u1"))
        self.assertEqual(first["steps"][0]["evidence_turns"], ["u1", "doc_rule"])
        # The file is replaced: the excerpt the published map cites no longer exists.
        changed = copy.deepcopy(documents)
        changed["source_versions"][0]["source_revision"] = changed["documents"][0]["source_revision"] = "b" * 64
        changed["documents"][0]["excerpts"] = [{"id": "doc_rule_v2", "text": "The controller checks the invoice."}]
        self.interview.extra["_supporting_documents"] = changed
        self.client.map_window = None
        self.client.script["u1"].pop("cites")
        status = self.say("u2")
        self.assertEqual(status["workflow_state"], "ready", status)
        self.assertEqual(self.client.maps()[1]["previous_capture"]["workflow"]["steps"], [])
        self.assertEqual([item["evidence_turns"] for item in graph(status)["steps"]], [["u1"], ["u2"]])
        # The map published now is the next baseline.
        self.say("u3")
        self.assertEqual(len(self.client.maps()[2]["previous_capture"]["workflow"]["steps"]), 2)

    def test_an_update_the_baseline_refuses_is_followed_by_a_rebuild_not_a_stuck_map(self):
        self.say("u1")
        self.say("u2")

        def missing(result):
            result["remove_steps"] = [{"id": "S9", "reason": "No such step.", "source_quote": "approves",
                                       "evidence_turns": ["u3"]}]
        self.client.broken["team_working_process_map"] = missing
        failed = self.say("u3")
        self.assertEqual((failed["state"], failed["workflow_state"]), ("ready", "error"))
        self.assertNotIn("workflow_capture", failed)
        self.client.map_window = None
        recovered = self.say("u4")
        self.assertEqual(recovered["workflow_state"], "ready", recovered)
        self.assertEqual(self.client.maps()[3]["previous_capture"]["workflow"]["steps"], [])
        self.assertEqual([item["title"] for item in graph(recovered)["steps"]],
                         ["Receive invoice", "Log invoice", "Approve invoice", "Release payment"])
        self.client.map_window = 1
        self.say("u5")
        self.assertEqual(len(self.client.maps()[4]["previous_capture"]["workflow"]["steps"]), 4)

    def test_a_provider_failure_keeps_the_baseline_for_the_next_update(self):
        self.say("u1")
        self.say("u2")

        def down(_sent):
            del self.client.hooks["team_working_process_map"]
            raise server.APIError("The provider is unavailable.", 503)
        self.client.hooks["team_working_process_map"] = down
        self.assertEqual(self.say("u3")["workflow_state"], "error")
        self.client.map_window = 2
        recovered = graph(self.say("u4"))
        self.assertEqual(len(self.client.maps()[-1]["previous_capture"]["workflow"]["steps"]), 2)
        self.assertEqual([item["id"] for item in recovered["steps"]], ["S1", "S2", "S3", "S4"])

    def test_a_map_sent_by_the_browser_is_never_the_baseline(self):
        forged = {"workflow": {"title": "Forged", "steps": [step("X1", "Pay the forger", "Nobody", ["u1"])],
                               "connections": [], "open_questions": []},
                  "memo_findings": [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                                    for key in server.COVERAGE],
                  "summary": "", "focus": "", "parking_lot": []}
        self.interview.extra.update(previous_capture=forged, _session_baseline=True)
        first = graph(self.say("u1"))
        self.assertEqual(self.client.maps()[0]["previous_capture"]["workflow"]["steps"], [])
        second = graph(self.say("u2"))
        self.assertEqual(self.client.maps()[1]["previous_capture"]["workflow"], first)
        self.assertNotIn("Pay the forger", json.dumps(second))


class BackgroundWorkHasNoAuthority(unittest.TestCase):
    """The capability feeds the ledger only: no confirmation, no replay, no review."""

    def test_a_ledger_only_request_never_confirms_the_final_check(self):
        client = SyntheticTeamProvider()
        payload, reviewed = reviewed_capture(client)
        self.assertEqual(reviewed["speech_authorization"]["kind"], "final_check")
        confirmation = reply_payload(payload, reviewed, "No, nothing else. This captures my account.")
        before = client.request.call_count
        background = client.coordinator.interview({**copy.deepcopy(confirmation), "_facts_only": True})
        self.assertIsNot(background.get("no_new_run"), True)
        self.assertFalse(background["completion"]["complete"])
        self.assertNotEqual(background["speech_authorization"]["kind"], "complete")
        self.assertGreater(client.request.call_count, before, "It is analysed as an ordinary answer")
        # The same request without the server's marker is the participant's confirmation.
        client = SyntheticTeamProvider()
        payload, reviewed = reviewed_capture(client)
        confirmed = client.coordinator.interview(reply_payload(payload, reviewed, "No, nothing else. This captures my account."))
        self.assertTrue(confirmed["completion"]["complete"])

    def test_a_ledger_only_request_never_replays_the_stored_capture(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        payload = client.payload()
        first = client.coordinator.interview(copy.deepcopy(payload))
        same = {**copy.deepcopy(payload), "capture_token": first["capture_token"]}
        self.assertIs(client.coordinator.interview(copy.deepcopy(same)).get("no_new_run"), True)
        seen = []
        client.hooks["team_interview_capture"] = lambda body: seen.append(json.loads(body["input"][0]["content"]))
        again = client.coordinator.interview({**copy.deepcopy(same), "_facts_only": True})
        self.assertIsNot(again.get("no_new_run"), True)
        self.assertEqual(len(seen), 1)
        self.assertGreater(len(seen[0]["fact_state"]["facts"]), 0, "The ledger is continued")
        self.assertNotEqual(again["capture_token"], first["capture_token"])

    def test_a_ledger_only_run_joins_the_conversation_so_an_older_review_cannot_publish(self):
        # Decided deliberately: background work continues the capture family of the ledger it
        # uses. A review prepared before a newer answer then fails closed, exactly as it
        # does when the newer answer arrives with the browser's own capability.
        client = SyntheticTeamProvider()
        review, pending = prepared_review(client)
        newer = reply_payload(client.payload(), pending, "One more thing: the buyer is copied on rejections.")
        newer["_facts_only"] = True
        client.coordinator.interview(newer)
        with self.assertRaisesRegex(server.APIError, "cancelled or replaced"):
            client.coordinator.review(review)

    def test_held_wording_reaches_the_lead_once_through_the_ledger_when_it_is_continued(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        finding = next(item for item in client.findings if item["key"] == "checks")
        finding["answer"] += " The second approver is probably the AP manager."
        seen = []
        client.hooks["team_interview_capture"] = lambda body: seen.append(json.loads(body["input"][0]["content"]))
        payload = client.payload()
        first = client.coordinator.interview(copy.deepcopy(payload))
        held = [{"topic": "checks", "wording": "approver is probably"}]
        follow = reply_payload(payload, first, "Nothing changes.")
        client.coordinator.interview({**copy.deepcopy(follow), "_facts_only": True, "_held_wording": held})
        self.assertIn("held_for_wording", seen[1]["fact_state"]["topics"]["checks"])
        self.assertNotIn("held_wording", seen[1], "The continued ledger already names the wording")
        # Without a ledger to continue (here: an unknown capability) the advice is passed as before.
        client.coordinator.interview({**copy.deepcopy(follow), "capture_token": "f" * 64, "_facts_only": True,
                                      "_held_wording": held})
        self.assertEqual(seen[2]["fact_state"]["facts"], [])
        self.assertEqual(seen[2]["held_wording"], held)

    def test_the_more_recently_published_of_two_ledgers_is_continued(self):
        # Two captures of one conversation that do not share a capability: what the browser
        # holds and what the session published. Whichever was published later is continued.
        client = ScriptedTeam()
        texts = [SCRIPT[key]["facts"][0][1] for key in ("u1", "u2", "u3", "u4")]
        browser = client.coordinator.interview(account("u1"))
        session = client.coordinator.interview(account("u1", "u2"))
        third = client.coordinator.interview({**account("u1", "u2", "u3"), "capture_token": browser["capture_token"],
                                              "_ledger_token": session["capture_token"]})
        self.assertEqual([fact["text"] for fact in client.leads()[2]["sent"]["fact_state"]["facts"]], texts[:2])
        self.assertEqual(client.leads()[2]["sent"]["previous_capture"]["summary"], session["summary"])
        # The capture just made belongs to the browser's capability and is now the latest of both.
        client.coordinator.interview({**account("u1", "u2", "u3", "u4"), "capture_token": session["capture_token"],
                                      "_ledger_token": browser["capture_token"]})
        self.assertEqual([fact["text"] for fact in client.leads()[3]["sent"]["fact_state"]["facts"]], texts[:3])
        self.assertNotEqual(third["capture_token"], browser["capture_token"])
        # An edited account is recaptured; no earlier capture is resurrected, whoever names it.
        edited = account("u1", "u2", "u3", "u4", "u5")
        edited["turns"][3]["text"] = "The AP clerk scans the invoice."
        client.coordinator.interview({**edited, "capture_token": browser["capture_token"], "_ledger_token": session["capture_token"]})
        self.assertEqual(client.leads()[4]["sent"]["fact_state"]["facts"], [])

    def test_the_session_s_capability_adds_no_authority_to_the_browser_s(self):
        # The final check was issued for the capture the browser holds. A newer capture named
        # only as the ledger to continue neither confirms it nor stands in for it.
        client = SyntheticTeamProvider()
        payload, reviewed = reviewed_capture(client)
        confirmation = reply_payload(payload, reviewed, "No, nothing else. This captures my account.")
        before = client.request.call_count
        confirmed = client.coordinator.interview({**copy.deepcopy(confirmation), "_ledger_token": reviewed["capture_token"]})
        self.assertTrue(confirmed["completion"]["complete"], "The browser's own capability still confirms")
        self.assertEqual(client.request.call_count, before)
        forged = {**copy.deepcopy(confirmation), "capture_token": "f" * 64, "_ledger_token": reviewed["capture_token"]}
        answered = client.coordinator.interview(forged)
        self.assertFalse(answered["completion"]["complete"])
        self.assertIsNot(answered.get("no_new_run"), True)

    def test_a_ledger_only_request_sees_the_previous_notes_as_context_not_as_authority(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        seen = []
        client.hooks["team_interview_capture"] = lambda body: seen.append(json.loads(body["input"][0]["content"]))
        payload = client.payload()
        first = client.coordinator.interview(copy.deepcopy(payload))
        follow = reply_payload(payload, first, "Nothing changes.")
        client.coordinator.interview({**copy.deepcopy(follow), "_facts_only": True})
        self.assertEqual(seen[1]["previous_capture"]["parking_lot"], first["parking_lot"])
        self.assertEqual(seen[1]["previous_capture"]["summary"], first["summary"])


class HTTPCase(unittest.TestCase):
    make_client = ScriptedTeam

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="collector-background-continuity-")
        self.client = self.make_client()
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
            documents_root=Path(self.temp.name) / "documents", knowledge_root=Path(self.temp.name) / "knowledge")
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.turns, self.token, self.question, self.count, self.extra = [], None, OPENING, 0, {}

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)
        self.temp.cleanup()

    def post(self, route, payload):
        request = Request(self.url + route, data=json.dumps(payload).encode(), headers={
            "Content-Type": "application/json", "Origin": self.url, "X-CSRF-Token": self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=60) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def payload(self, **more):
        return {"context": {"process_name": "Invoice handling", "process_owner": "AP team",
                            "objective": "Capture the current process",
                            "background": "Synthetic test fixture, not an actual company process"},
                "turns": copy.deepcopy(self.turns), "session": {"closure_requested": False}, "document_source_ids": [],
                **({"conversation_token": self.token} if self.token else {}), **copy.deepcopy(self.extra), **more}

    def answer(self, text, **more):
        self.count += 1
        self.turns += [{"id": f"a{self.count}", "role": "assistant", "text": self.question},
                       {"id": f"u{self.count}", "role": "user", "text": text}]
        sent = self.payload(**more)
        status, reply = self.post("/api/conversation/turn", sent)
        self.assertEqual(status, 200, reply)
        self.token, self.question = reply["conversation_token"], reply["question"]
        sent["conversation_token"] = self.token
        # Wait for the two background workers without polling over HTTP: every status poll
        # opens the document store, and on Windows the store's permission step can be denied
        # while several connections open and close at once on a loaded machine. The one poll
        # that follows is what the browser's last poll would return.
        conversation = self.httpd.conversation
        session = conversation._sessions[self.token]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with conversation._lock:
                if not (session["running"] or session["graph_running"] or session["pending"] or session["graph_pending"]):
                    break
            time.sleep(.01)
        else:
            self.fail("Background analysis did not settle")
        code, progress = self.post("/api/conversation/status", sent)
        self.assertEqual(code, 200, progress)
        return progress


class TypedInterviewOverHTTP(HTTPCase):
    def test_typed_answers_keep_the_notes_and_the_map_between_answers(self):
        padding = " The participant supplied additional process detail." * 70
        first = self.answer(SCRIPT["u1"]["say"] + padding)
        second = self.answer(SCRIPT["u2"]["say"] + padding)
        self.assertEqual((second["state"], second["workflow_state"]), ("ready", "ready"), second)
        lead = self.client.leads()[1]
        self.assertEqual([fact["text"] for fact in lead["sent"]["fact_state"]["facts"]], [SCRIPT["u1"]["facts"][0][1]])
        self.assertEqual((lead["model"], lead["max_output_tokens"]), ("synthetic-lead", 6500))
        self.assertEqual(self.client.maps()[1]["previous_capture"]["workflow"], graph(first))
        self.assertEqual([item["id"] for item in graph(second)["steps"]], ["S1", "S2"])
        self.assertEqual(graph(second)["steps"][0], graph(first)["steps"][0])
        self.assertEqual(notes(second)["trigger"], notes(first)["trigger"])

    def test_server_only_markers_in_a_request_body_are_dropped(self):
        # On the conversation routes: they neither start a ledger nor a baseline.
        forged = {"workflow": {"title": "Forged", "steps": [step("X1", "Pay the forger", "Nobody", ["u1"])],
                               "connections": [], "open_questions": []},
                  "memo_findings": [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                                    for key in server.COVERAGE],
                  "summary": "", "focus": "", "parking_lot": []}
        self.extra = {"_facts_only": True, "_session_baseline": True, "previous_capture": forged, "capture_token": "f" * 64}
        status = self.answer(SCRIPT["u1"]["say"])
        self.assertEqual((status["state"], status["workflow_state"]), ("ready", "ready"), status)
        self.assertEqual(self.client.maps()[0]["previous_capture"]["workflow"]["steps"], [])
        self.assertNotIn("Pay the forger", json.dumps(status))
        # On the map route: an invalid baseline from a browser is still refused, marker or not.
        forged["workflow"]["steps"][0]["evidence_turns"] = ["u404"]
        before = len(self.client.calls)
        code, body = self.post("/api/agent-team/workflow", {**self.payload(), "previous_capture": forged, "_session_baseline": True})
        self.assertEqual(code, 400, body)
        self.assertEqual(len(self.client.calls), before)

    def test_a_posted_ledger_capability_is_dropped(self):
        # _ledger_token is how the server names its session's own capture beside the browser's.
        # A browser that posts one (here: a real, newer capability it also holds) changes nothing.
        older = self.client.coordinator.interview(account("u1"))
        newer = self.client.coordinator.interview(account("u1", "u2"))
        request = {**account("u1", "u2", "u3"), "capture_token": older["capture_token"], "_ledger_token": newer["capture_token"]}
        code, body = self.post("/api/agent-team/interview", request)
        self.assertEqual(code, 200, body)
        self.assertEqual([fact["text"] for fact in self.client.leads()[2]["sent"]["fact_state"]["facts"]],
                         [SCRIPT["u1"]["facts"][0][1]])

    def test_a_posted_ledger_only_marker_cannot_switch_off_a_confirmation(self):
        client = SyntheticTeamProvider()
        self.httpd.client = client
        payload, reviewed = reviewed_capture(client)
        confirmation = reply_payload(payload, reviewed, "No, nothing else. This captures my account.")
        confirmation["_facts_only"] = True
        before = client.request.call_count
        code, body = self.post("/api/agent-team/interview", confirmation)
        self.assertEqual(code, 200, body)
        self.assertTrue(body["completion"]["complete"])
        self.assertEqual(client.request.call_count, before)


class CompletionAfterContinuedCaptures(HTTPCase):
    """The whole route to completion, with a lead that proposes the review after every answer."""
    make_client = ConversationProvider

    def poll(self, payload):
        def read():
            code, progress = self.post("/api/conversation/status", payload)
            self.assertEqual(code, 200, progress)
            return progress
        return settled(read, 30)

    def test_review_final_check_and_confirmation_still_bind_to_the_wrapped_up_transcript(self):
        seen = []
        self.client.hooks["team_interview_capture"] = lambda body: seen.append(json.loads(body["input"][0]["content"]))
        payload = self.client.payload()
        code, fast = self.post("/api/conversation/turn", payload)
        self.assertEqual(code, 200, fast)
        payload["conversation_token"] = fast["conversation_token"]
        first = self.poll(payload)["capture"]
        self.assertEqual(first["speech_authorization"]["kind"], "review_pending")
        earlier = {**copy.deepcopy(payload), "capture_token": first["capture_token"], "review_ticket": first["review_ticket"]}
        earlier["turns"].append({"id": "a_ack_early", "role": "assistant", "text": first["question"]})
        # One more answer: analysed in the background from the ledger of the capture before it.
        payload["turns"] += [{"id": "a_fast", "role": "assistant", "text": fast["question"]},
                             {"id": "u_more", "role": "user", "text": "Nothing else changes in that route."}]
        code, fast = self.post("/api/conversation/turn", payload)
        self.assertEqual(code, 200, fast)
        self.assertEqual(self.poll(payload)["state"], "ready")
        self.assertEqual(len(seen), 2)
        self.assertGreater(len(seen[1]["fact_state"]["facts"]), 0)
        # The review prepared for the shorter account cannot be held any more: fail closed.
        code, refused = self.post("/api/agent-team/review", earlier)
        self.assertEqual(code, 409, refused)
        # Wrap up, review, final check and the participant's confirmation.
        payload["turns"].append({"id": "a_fast_two", "role": "assistant", "text": fast["question"]})
        payload["action"] = "close"
        code, pending = self.post("/api/conversation/sync", payload)
        self.assertEqual(code, 200, pending)
        self.assertEqual(pending["speech_authorization"]["kind"], "review_pending")
        self.assertEqual(len(seen), 2, "Wrap up extends the existing ticket without repeating the notes call")
        payload.update(capture_token=pending["capture_token"], review_ticket=pending["review_ticket"])
        payload["turns"].append({"id": "a_ack", "role": "assistant", "text": pending["question"]})
        code, reviewed = self.post("/api/agent-team/review", payload)
        self.assertEqual(code, 200, reviewed)
        self.assertEqual(reviewed["speech_authorization"]["kind"], "final_check")
        payload.update(capture_token=reviewed["capture_token"], action="answer")
        payload.pop("review_ticket")
        payload["turns"] += [{"id": "a_final", "role": "assistant", "text": reviewed["question"]},
                             {"id": "u_final", "role": "user", "text": "No, nothing else. This captures my account."}]
        before = self.client.request.call_count
        code, gate = self.post("/api/conversation/turn", payload)
        self.assertEqual((code, gate["sync_required"]), (200, True))
        code, complete = self.post("/api/conversation/sync", payload)
        self.assertEqual(code, 200, complete)
        self.assertTrue(complete["completion"]["complete"])
        self.assertEqual(self.client.request.call_count, before, "The confirmation spends no provider call")


class TypedInterviewWithAFileOverHTTP(HTTPCase):
    SECTION = 4800

    def setUp(self):
        super().setUp()
        self.store = self.httpd.documents_store
        self.scope = self.store.create_scope()
        rows = ["section,detail"]
        for index in range(40):
            body = f"manualsec{index} supplier onboarding approval step {index} of manual.csv "
            rows.append(f"{index}," + (body * (self.SECTION // len(body) + 1))[:self.SECTION - 12])
        record = self.store.add(self.scope, "manual.csv", ("\n".join(rows) + "\n").encode())
        self.store.extract(self.scope, record["id"])
        self.store.update(self.scope, record["id"], {"analysis": {
            "phase": "complete", "review_complete": True, "disposition": "relevant", "summary": "Synthetic reference."}})
        self.sections = {re.search(r"manualsec\d+", chunk["text"]).group(0): chunk["id"]
                         for chunk in self.store.chunks(self.scope, record["id"], limit=200)["chunks"]}
        # One reader of the document store at a time. A request handler and the background
        # workers read it concurrently, and on Windows the store's permission step can be
        # denied while several connections open and close at once on a loaded machine
        # (documents.py retries for about 100 ms, then the request ends in 409). That is not
        # what these tests are about, and it failed them in loaded full runs.
        service, read, gate = self.httpd.documents, self.httpd.documents.supporting_context, threading.Lock()

        def one_at_a_time(*args, **kwargs):
            with gate:
                return read(*args, **kwargs)
        service.supporting_context = one_at_a_time
        self.extra = {"document_scope": self.scope, "document_revision": "one"}
        # Each answer points at one section of the manual, far from the sections every request reads.
        self.client.script = {
            "u1": {"say": "We follow manualsec30 when the supplier form arrives.", "cites": "manualsec30 ",
                   "facts": [("trigger", "The supplier form starts the work, as section 30 documents.")],
                   "step": ("Receive supplier form", "Clerk")},
            "u2": {"say": "Then manualsec33 applies to the bank details.", "cites": "manualsec33 ",
                   "facts": [("lifecycle", "Bank details are checked as section 33 documents.")],
                   "step": ("Check bank details", "Clerk")},
            "u3": {"say": "Finally manualsec36 covers the approval.", "cites": "manualsec36 ",
                   "facts": [("checks", "Approval follows section 36.")], "step": ("Approve supplier", "Manager")},
            "u4": {"say": "After that the supplier is active.",
                   "facts": [("completion", "The supplier is active after approval.")], "step": ("Activate supplier", "Clerk")},
        }

    def shown(self, sent):
        return [item["id"] for item in excerpts(sent["supporting_documents"])]

    def test_the_ledger_s_and_the_map_s_file_citations_are_read_again_without_the_browser_naming_them(self):
        # The browser sends no document_source_ids here: it has not applied the latest notes
        # and map yet, which is the ordinary state right after an answer.
        section30, section33 = self.sections["manualsec30"], self.sections["manualsec33"]
        first = self.answer(self.client.script["u1"]["say"])
        self.assertEqual((first["state"], first["workflow_state"]), ("ready", "ready"), first)
        self.assertEqual(notes(first)["trigger"]["evidence_turns"], ["u1", section30])
        self.assertEqual(graph(first)["steps"][0]["evidence_turns"], ["u1", section30])
        self.answer(self.client.script["u2"]["say"])
        third = self.answer(self.client.script["u3"]["say"])
        fourth = self.answer(self.client.script["u4"]["say"])
        self.assertEqual((fourth["state"], fourth["workflow_state"]), ("ready", "ready"), fourth)
        leads, maps = self.client.leads(), self.client.maps()
        # By the fourth answer nothing in the latest turns points at section 30 any more.
        for request in (leads[3]["sent"], maps[3]):
            self.assertEqual(self.shown(request)[:3], [section30, section33, self.sections["manualsec36"]],
                             "Cited excerpts are read first")
        self.assertEqual(len(leads[3]["sent"]["fact_state"]["facts"]), 3, "The ledger with its file citations continues")
        self.assertEqual([item["id"] for item in maps[3]["previous_capture"]["workflow"]["steps"]], ["S1", "S2", "S3"])
        self.assertEqual(notes(fourth)["trigger"], notes(first)["trigger"])
        self.assertEqual(graph(fourth)["steps"][:3], graph(third)["steps"])
        self.assertEqual([(call["model"], call["max_output_tokens"]) for call in leads],
                         [("synthetic-document", 12000)] + [("synthetic-lead", 6500)] * 3)

    def test_a_correction_and_a_stop_request_in_an_interview_with_a_file(self):
        section30, section33, section36 = (self.sections[f"manualsec{number}"] for number in (30, 33, 36))
        script = self.client.script
        self.client.script = {
            "u1": script["u1"], "u2": script["u2"],
            "u3": {"say": "Correction: the controller checks the bank details, not the clerk.",
                   "corrections": [("lifecycle", script["u2"]["facts"][0][1], "The controller checks the bank details.")],
                   "revise": ("u2", {"actor": "Controller"})},
            # u4 is the stop request.
            "u5": {**script["u3"], "say": "Finally manualsec36 covers the approval."}}
        first = self.answer(script["u1"]["say"])
        self.answer(script["u2"]["say"])
        corrected = self.answer(self.client.script["u3"]["say"])
        self.assertEqual((corrected["state"], corrected["workflow_state"]), ("ready", "ready"), corrected)
        self.assertEqual(notes(corrected)["lifecycle"]["answer"], "The controller checks the bank details.")
        self.assertEqual(notes(corrected)["trigger"], notes(first)["trigger"])
        self.assertEqual([(item["id"], item["actor"], item["evidence_turns"]) for item in graph(corrected)["steps"]],
                         [("S1", "Clerk", ["u1", section30]), ("S2", "Controller", ["u2", section33, "u3"])])
        self.assertEqual(graph(corrected)["steps"][0], graph(first)["steps"][0])
        stopped = self.answer(STOP)
        self.assertIs(stopped.get("capture_preserved"), True)
        self.assertNotIn("capture", stopped)
        self.assertEqual(graph(stopped), graph(corrected))
        self.assertEqual(len(self.client.leads()), 3, "The stop request is not analysed")
        resumed = self.answer(self.client.script["u5"]["say"])
        self.assertEqual((resumed["state"], resumed["workflow_state"]), ("ready", "ready"), resumed)
        lead = self.client.leads()[3]
        self.assertEqual([fact["text"] for fact in lead["sent"]["fact_state"]["facts"]],
                         [script["u1"]["facts"][0][1], "The controller checks the bank details."])
        self.assertEqual((lead["model"], lead["max_output_tokens"]), ("synthetic-lead", 6500))
        self.assertEqual(graph(resumed)["steps"][:2], graph(corrected)["steps"])
        self.assertEqual(graph(resumed)["steps"][2]["evidence_turns"], ["u5", section36])
        self.assertEqual([(edge["from"], edge["to"]) for edge in graph(resumed)["connections"]], [("S1", "S2"), ("S2", "S3")])
        self.assertEqual(notes(resumed)["trigger"], notes(first)["trigger"])

    def test_status_polls_and_wrap_up_replay_the_same_selection(self):
        self.answer(self.client.script["u1"]["say"])
        self.answer(self.client.script["u2"]["say"])
        status = self.answer(self.client.script["u3"]["say"])
        self.assertEqual(status["state"], "ready", status)
        wrap = self.payload(action="close")
        wrap["turns"].append({"id": "a_fast", "role": "assistant", "text": self.question})
        code, result = self.post("/api/conversation/sync", wrap)
        self.assertEqual(code, 200, result)
        self.assertEqual(len(self.client.leads()), 3, "The same selected document and notes were reused")
        self.assertEqual(result["document_evidence"], status["capture"]["document_evidence"])


if __name__ == "__main__":
    unittest.main()
