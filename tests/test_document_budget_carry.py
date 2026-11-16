"""The map and the notes keep updating when they cite more than one request can read.

One request reads at most 60,000 characters of reference files. The browser's
map and notes can together cite more than that. Each later request must still
be served: citations that already exist stay valid because the document store
confirms them as excerpts of this interview's files, not because their text
fitted. Real HTTP handler, coordinator, fact ledger, document store and
document service on a loopback port; only the provider is scripted. The
scripted models cite every excerpt they are shown, which is not model
behaviour but reaches the limit quickly.
"""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_interview_orchestrator import REVIEW_CALLS, SyntheticTeamProvider
from test_server import server
import capture_facts

SECTION = 4800
DOCUMENT_SERVICE = server.local_module("document_service", "document_service.py")
# document-service-5 keeps room in each request for the sections that best match the current
# turns. Two tests below pin, excerpt by excerpt, what is read when citations alone exceed the
# limit; their fixture turns happen to match other sections of the fixture file. They run with
# that room switched off, which is also the state of any turn whose wording matches nothing.
# The room itself is tested in test_room_for_matches_* below and in test_document_context_budget.py.
NO_ROOM_FOR_MATCHES = patch.object(DOCUMENT_SERVICE, "MAX_QUERY_MATCHES", 0)
TOPICS = list(capture_facts.TOPICS)
EMPTY_MAP = {"title": "", "steps": [], "connections": [], "open_questions": []}


def generic(schema, root=None):
    root = root or schema
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return generic(node, root)
    if "anyOf" in schema:
        return generic(schema["anyOf"][0], root)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {name: generic(child, root) for name, child in schema.get("properties", {}).items()}
    if kind == "array":
        return [generic(schema["items"], root) for _ in range(schema.get("minItems", 0))]
    if kind == "boolean":
        return False
    if kind in ("integer", "number"):
        return 0
    return "x" if schema.get("minLength") else ""


def shown(supporting):
    """The citable excerpts exactly as a model receives them."""
    return [(document, excerpt) for document in (supporting or {}).get("documents", [])
            for excerpt in document.get("excerpts", [])
            if not excerpt.get("requires_vision") and str(excerpt.get("text", "")).strip()]


def step(source, title=None):
    return {"id": "s_" + source[-24:], "title": title or "Step from " + source[-12:], "type": "activity", "actor": "Clerk",
            "system": "", "description": "Documented step.", "evidence_turns": [source], "input": "", "output": "",
            "completion_criteria": "", "handoff": "", "control_type": [], "data_origin": "", "entry_mode": "unknown",
            "rule_source_ref": "", "entity_scope": [], "parent_process": ""}


def unknown_findings():
    return [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []} for key in server.COVERAGE]


def notes_citing(sources):
    findings = unknown_findings()
    for index, source in enumerate(sources):
        finding = findings[index % len(findings)]
        finding.update(status="partial", answer=(finding["answer"] + "\n" if finding["evidence_turns"] else "")
                       + f"Documented in section {source[-12:]}.", evidence_turns=finding["evidence_turns"] + [source])
    return findings


def cited(value):
    found = []
    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, item in node.items():
                if key == "evidence_turns" and isinstance(item, list):
                    found.extend(ref for ref in item if isinstance(ref, str) and ref.startswith("doc_"))
                else:
                    walk(item)
    walk(value)
    return list(dict.fromkeys(found))


def left_out(body):
    """What the response's open questions name as an edit that was left out of an update."""
    marker = " need to change? A proposed change was left out of an update"
    return [question[len("Does "):question.index(marker)] for question in body["workflow"]["open_questions"] if marker in question]


class ScriptedProvider(server.OpenAIClient):
    def __init__(self):
        super().__init__({"OPENAI_API_KEY": "offline-not-a-key", "VOICE_MODE": "live"})
        self.calls = []
        self.map_additions = []
        self.capture_limit = 120

    def request(self, path, body, content_type="application/json", timeout=90, on_text=None):
        if path != "responses" or not isinstance(body, dict):
            raise server.APIError("The scripted provider has no such endpoint.", 503)
        name, schema = body["text"]["format"]["name"], body["text"]["format"]["schema"]
        handler = {"team_interview_capture": self.capture, "team_working_process_map": self.working_map,
                   "working_process_map": self.working_map, "team_working_map_source_audit": self.map_audit,
                   "working_process_map_audit": self.map_audit}.get(name)
        if handler:
            payload = json.loads(body["input"][0]["content"])
            supporting = payload.get("supporting_documents") or {}
            self.calls.append({"name": name, "shown": [excerpt["id"] for _, excerpt in shown(supporting)],
                               "supporting": supporting, "payload": payload})
            result = handler(payload, schema)
        elif name == "document_context_review":
            # The background review that Save for later starts for a file.
            result = {"summary": "Synthetic reference.", "acknowledgement": "Received.", "relevance": "relevant",
                      "relevance_reason": "Scripted.", "question": "", "queries": [], "observations": [],
                      "questions": [], "extracted_text": ""}
        else:
            result = generic(schema)
        text = json.dumps(result)
        if on_text is not None:
            on_text(text)
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}

    def capture(self, payload, schema):
        known = {ref for fact in payload["fact_state"]["facts"] for ref in fact["evidence_turns"]}
        users = [turn["id"] for turn in payload["turns"] if turn["role"] == "user" and not turn.get("document_event")]
        operations = [{"op": "add", "topic": TOPICS[index % len(TOPICS)], "target_id": "", "kind": "detail",
                       "text": f"Documented in {document['name']} section {excerpt['id'][-12:]}.",
                       "evidence_turns": [excerpt["id"]], "reason": "new_evidence"}
                      for index, (document, excerpt) in enumerate(shown(payload.get("supporting_documents")))
                      if excerpt["id"] not in known][:self.capture_limit]
        if users and users[-1] not in known:
            operations.append({"op": "add", "topic": "lifecycle", "target_id": "", "kind": "detail",
                               "text": f"Participant statement in {users[-1]}.", "evidence_turns": [users[-1]],
                               "reason": "new_evidence"})
        targets = schema["properties"]["fact_reconciliations"]["items"]["anyOf"][0]["properties"]["target_id"]["enum"]
        touched = {item["topic"] for item in operations} | {fact["topic"] for fact in payload["fact_state"]["facts"]}
        return {"question": "What happens after that step?", "base_revision": schema["properties"]["base_revision"]["enum"][0],
                "fact_reconciliations": [{"target_id": target, "disposition": "unchanged", "basis": "Not addressed.",
                                          "evidence_turns": [(users[-1:] or ["context"])[0]]} for target in targets if target],
                "topic_states": [{"key": key, "status": "partial" if key in touched else "unknown",
                                  "participant_unavailable": False} for key in TOPICS],
                "fact_operations": operations, "summary": "Scripted capture.", "focus": "Walkthrough",
                "parking_lot": [], "tag_operations": [], "connections_out": [], "active_modules": [], "recap_due": "none"}

    def working_map(self, payload, schema):
        previous = payload.get("previous_capture") or {}
        have = {item["id"] for item in (previous.get("workflow") or {}).get("steps", [])}
        steps = [step(excerpt["id"]) for _, excerpt in shown(payload.get("supporting_documents"))
                 if "s_" + excerpt["id"][-24:] not in have]
        users = [turn["id"] for turn in payload.get("turns", []) if turn.get("role") == "user" and not turn.get("document_event")]
        if not steps and not have:
            steps = [{**step(users[0] if users else "context"), "id": "s_user"}]
        # The notes are repeated exactly as accepted: unchanged topics, not new claims.
        return {"title": "Supplier onboarding", "upsert_steps": steps + copy.deepcopy(self.map_additions), "remove_steps": [],
                "upsert_connections": [], "remove_connections": [], "open_questions": [],
                "memo_findings": previous.get("memo_findings") or unknown_findings(),
                "summary": "Scripted map.", "focus": "Walkthrough", "parking_lot": []}

    def map_audit(self, payload, schema):
        update = payload["candidate_update"]
        return {"title": update["title"], "discard_step_upserts": [], "discard_connection_upserts": [],
                "discard_step_removals": [], "discard_connection_removals": [], "remove_connections": [], "route_support": [],
                "upsert_steps": [], "upsert_connections": [], "memo_findings": [], "open_questions": update["open_questions"],
                "summary": update["summary"], "focus": update["focus"], "parking_lot": update["parking_lot"]}


class BudgetCarryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="collector-budget-carry-")
        self.client = ScriptedProvider()
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
            documents_root=Path(self.temp.name) / "documents", knowledge_root=Path(self.temp.name) / "knowledge")
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.store, self.service = self.httpd.documents_store, self.httpd.documents
        self.hydrate = Mock(wraps=self.service.supporting_context)
        self.service.supporting_context = self.hydrate
        self.begin()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)
        self.temp.cleanup()

    def begin(self):
        """A new interview: its own file scope and an empty browser state."""
        self.scope = self.store.create_scope()
        self.turns, self.token, self.memo, self.workflow, self.count = [], None, None, None, 0

    # ---- reference files -------------------------------------------------
    def file(self, name, sections):
        """One reviewed file whose rows are each one indexed section of about 4,800 characters."""
        word = name.split(".")[0]
        rows = ["section,detail"]
        for index in range(sections):
            body = f"{word}sec{index} supplier onboarding approval step {index} of {name} "
            rows.append(f"{index}," + (body * (SECTION // len(body) + 1))[:SECTION - 12])
        record = self.store.add(self.scope, name, ("\n".join(rows) + "\n").encode())
        self.store.extract(self.scope, record["id"])
        self.store.update(self.scope, record["id"], {"analysis": {
            "phase": "complete", "review_complete": True, "disposition": "relevant", "summary": "Synthetic reference."}})
        return record["id"]

    def sections(self, identity):
        chunks = self.store.chunks(self.scope, identity, limit=200)["chunks"]
        self.assertTrue(all(SECTION - 200 <= len(chunk["text"]) <= SECTION + 200 for chunk in chunks))
        return [chunk["id"] for chunk in chunks]

    def file_action(self, identity, action):
        self.service.action(self.scope, identity, action)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = self.store.get(self.scope, identity)
            if record["archived"] or (record.get("analysis") or {}).get("phase") in ("complete", "error"):
                return
            time.sleep(.02)
        self.fail("The file review did not settle.")

    # ---- what the browser sends (web/app.js snapshot, refreshWorkflow, runLiveCapture) ----
    def post(self, route, payload):
        request = Request(self.url + route, data=json.dumps(payload).encode(), headers={
            "Content-Type": "application/json", "Origin": self.url, "X-CSRF-Token": self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=120) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def say(self, text):
        self.count += 1
        self.turns.append({"id": f"t{self.count}", "role": "user", "text": text})

    def snapshot(self, **extra):
        # The browser pins what it cites: the map first, then the notes.
        return {"context": {"process_name": "Supplier onboarding", "participant": "Sam", "team": "Ops", "role": "Clerk"},
                "turns": copy.deepcopy(self.turns), "session": {"closure_requested": False},
                "document_source_ids": cited([self.workflow, self.memo]), "document_scope": self.scope,
                **({"capture_token": self.token} if self.token else {}), **extra}

    def previous_capture(self):
        return {"workflow": copy.deepcopy(self.workflow or EMPTY_MAP), "memo_findings": copy.deepcopy(self.memo or unknown_findings()),
                "summary": "", "focus": "", "parking_lot": []}

    def update_map(self, route="/api/agent-team/workflow", turns=None, apply=True):
        payload = self.snapshot(previous_capture=self.previous_capture())
        if turns is not None:
            payload["turns"] = turns
        status, body = self.post(route, payload)
        if status == 200 and apply:
            self.workflow = body["workflow"]
        return status, body

    def update_notes(self, action="answer"):
        payload = self.snapshot(action=action)
        if action == "document_followup":
            payload["previous_capture"] = self.previous_capture()
        status, body = self.post("/api/agent-team/interview", payload)
        if status == 200:
            self.token, self.memo = body["capture_token"], body["memo_findings"]
            if action == "document_followup":
                self.turns.append({"id": f"a{len(self.turns)}", "role": "assistant", "text": body["question"]})
        return status, body

    def last_call(self, *names):
        return next(call for call in reversed(self.client.calls) if call["name"] in names)

    def ledger_citations(self, identity):
        state = self.client.coordinator._captures[self.token]["fact_state"]
        return sorted(ref for fact in state["facts"] if fact["state"] == "active"
                      for ref in fact["sources"] if ref.startswith(identity + "_"))

    # ---- the regression of the finding ----------------------------------
    def test_map_is_updated_when_map_and_notes_cite_more_than_one_request_can_read(self):
        ids = self.sections(self.file("manual.csv", 40))
        self.say("I onboard new suppliers. I start from the supplier form.")
        drawn, noted = ids[:7], ids[20:27]
        for route, lead in (("/api/agent-team/workflow", "team_working_process_map"), ("/api/workflow", "working_process_map")):
            with self.subTest(route=route):
                # Seven sections are cited by the map and seven others by the notes: 67,000 characters.
                self.workflow = {**EMPTY_MAP, "title": "Supplier onboarding", "steps": [step(source) for source in drawn]}
                self.memo = notes_citing(noted)
                before = len(self.client.calls)
                status, body = self.update_map(route, apply=False)
                self.assertEqual(status, 200, body)
                call = self.last_call(lead)
                self.assertGreater(len(self.client.calls), before, "the map model was not asked")
                self.assertEqual(call["shown"], [*drawn, *noted[:5]])
                self.assertEqual(call["supporting"]["omitted_prior_sources"], 2)
                self.assertLessEqual(call["supporting"]["context_budget"]["characters"], 60000)
                # The model received the accepted baseline whole, and nothing about the two excerpts but their IDs.
                self.assertEqual(cited(call["payload"]["previous_capture"]), [*drawn, *noted])
                self.assertNotIn("carried_sources", call["supporting"])
                self.assertNotIn("_carried_document_sources", call["payload"])
                self.assertEqual([item["id"] for item in body["workflow"]["steps"]][:7], [step(source)["id"] for source in drawn])
                self.assertEqual(cited(body["memo_findings"]), noted)
                self.assertEqual(body["document_reading"]["omitted_prior_sources"], 2)
                self.assertEqual(sorted(item["id"] for item in body["document_evidence"]), sorted(call["shown"]))
                self.assertTrue(all(item["text"].strip() for item in body["document_evidence"]))
                self.assertNotIn("carried_sources", json.dumps(body))

    def test_a_map_that_alone_cites_more_than_one_request_can_read_is_still_updated(self):
        ids = self.sections(self.file("manual.csv", 40))
        self.say("I onboard new suppliers. I start from the supplier form.")
        for route in ("/api/agent-team/workflow", "/api/workflow"):
            with self.subTest(route=route):
                self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in ids[:13]]}
                self.memo = None
                status, body = self.update_map(route, apply=False)
                self.assertEqual(status, 200, body)
                self.assertEqual([item["id"] for item in body["workflow"]["steps"]], [step(source)["id"] for source in ids[:13]])
                self.assertEqual(body["document_reading"]["omitted_prior_sources"], 1)

    def test_a_request_within_the_limit_reports_nothing_left_unread(self):
        ids = self.sections(self.file("manual.csv", 40))
        self.say("I onboard new suppliers. I start from the supplier form.")
        self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in ids[:5]]}
        self.memo = notes_citing(ids[20:25])
        status, body = self.update_map(apply=False)
        self.assertEqual(status, 200, body)
        self.assertNotIn("omitted_prior_sources", body["document_reading"])
        self.assertEqual(self.last_call("team_working_process_map")["supporting"]["omitted_prior_sources"], 0)

    # ---- the check keeps its purpose -------------------------------------
    def test_an_excerpt_the_store_does_not_know_is_still_refused_before_any_provider_call(self):
        manual = self.file("manual.csv", 40)
        ids = self.sections(manual)
        mine = self.scope
        self.scope = self.store.create_scope()
        foreign = self.sections(self.file("other-interview.csv", 2))[0]
        self.scope = mine
        self.say("I onboard new suppliers. I start from the supplier form.")
        for forged in (manual + "_s1_r999_999_b999_c1", foreign, "doc_0123456789abcdef01234567_s1_r1_2_b1_c1"):
            for where in ("map", "notes"):
                with self.subTest(forged=forged, where=where):
                    # Over the limit, so that some real citations are carried in the same request.
                    self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in ids[:13]]}
                    self.memo = notes_citing(ids[20:22])
                    if where == "map":
                        self.workflow["steps"].append({**step(forged), "id": "s_forged"})
                    else:
                        self.memo = notes_citing([*ids[20:22], forged])
                    # A browser cannot declare an excerpt known: the server-owned list is replaced.
                    claim = [{"id": forged, "document_id": manual, "name": "manual.csv", "characters": 10}]
                    for route in ("/api/agent-team/workflow", "/api/workflow"):
                        status, body = self.post(route, self.snapshot(previous_capture=self.previous_capture(),
                                                                      _carried_document_sources=claim))
                        self.assertEqual(status, 400, body)
                        self.assertIn("missing or non-participant evidence", body["error"])
        self.assertEqual(self.client.calls, [])

    def test_only_what_was_already_accepted_may_cite_an_excerpt_that_was_not_read(self):
        ids = self.sections(self.file("manual.csv", 40))
        self.say("I onboard new suppliers. I start from the supplier form.")
        self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in ids[:7]]}
        self.memo = notes_citing(ids[20:27])
        unread = ids[26]
        accepted = self.workflow["steps"][0]
        for addition in ({**step(unread), "id": "s_new"}, {**accepted, "title": "Retitled", "evidence_turns": [ids[0], unread]}):
            with self.subTest(addition=addition["id"]):
                self.client.map_additions = [addition]
                status, body = self.update_map(apply=False)
                self.assertEqual(status, 400, body)
                self.assertIn("did not read", body["error"])
        # Repeating an accepted step unchanged is not a new claim.
        self.client.map_additions = [copy.deepcopy(accepted)]
        status, body = self.update_map(apply=False)
        self.assertEqual(status, 200, body)

    @NO_ROOM_FOR_MATCHES
    def test_a_topic_the_model_edits_keeps_the_citation_this_update_could_not_read(self):
        # WORKFLOW_INSTRUCTIONS: "In memo_findings return only new or changed topics ... Update each affected
        # topic cumulatively, retaining its other still-supported details and sources." A model that does so
        # returns the topic with the citation it already had, read or not. That must not refuse the update.
        ids = self.sections(self.file("manual.csv", 40))
        self.say("I onboard new suppliers. I start from the supplier form.")
        self.say("Finance approves every supplier above 10,000 before I activate it.")
        drawn, noted = ids[:7], ids[20:27]
        scripted = self.client.working_map
        for route, lead in (("/api/agent-team/workflow", "team_working_process_map"), ("/api/workflow", "working_process_map")):
            with self.subTest(route=route):
                self.workflow = {**EMPTY_MAP, "title": "Supplier onboarding", "steps": [step(source) for source in drawn]}
                self.memo = notes_citing(noted)
                # The two topics whose excerpt this request cannot read.
                extended, reworded = [copy.deepcopy(item) for item in self.memo if set(item["evidence_turns"]) & set(noted[5:])]
                def edited(payload, schema):
                    update = scripted(payload, schema)
                    accepted = {item["key"]: item for item in payload["previous_capture"]["memo_findings"]}
                    grown = copy.deepcopy(accepted[extended["key"]])
                    grown["answer"] += "\nFinance approves every supplier above 10,000 before activation."
                    grown["evidence_turns"] = [*grown["evidence_turns"], "t2"]
                    restated = {**copy.deepcopy(accepted[reworded["key"]]), "answer": "Restated without a source of its own."}
                    update["memo_findings"] = [grown, restated]
                    return update
                self.client.working_map = edited
                try:
                    status, body = self.update_map(route, apply=False)
                finally:
                    self.client.working_map = scripted
                self.assertEqual(status, 200, body)
                self.assertEqual(self.last_call(lead)["shown"], [*drawn, *noted[:5]])
                notes = {item["key"]: item for item in body["memo_findings"]}
                # The cumulative update is taken: the answer it adds has its own source.
                self.assertEqual(notes[extended["key"]]["evidence_turns"], [*extended["evidence_turns"], "t2"])
                self.assertTrue(notes[extended["key"]]["answer"].endswith("before activation."))
                # A restatement that rests on nothing this update read is left out; the accepted topic stays.
                self.assertEqual((notes[reworded["key"]]["answer"], notes[reworded["key"]]["evidence_turns"]),
                                 (reworded["answer"], reworded["evidence_turns"]))
                # The rest of the update was applied: the steps drawn from the excerpts that were read.
                self.assertEqual(len(body["workflow"]["steps"]), len(drawn) + 5)
                self.assertEqual(body["document_reading"]["omitted_prior_sources"], 2)
                # The response names the edit that was left out, and only that one.
                self.assertEqual(left_out(body), [f"the notes on {server.COVERAGE[reworded['key']]}"])

    def test_a_step_the_model_corrects_keeps_the_citation_this_update_could_not_read(self):
        # "Reuse each existing step's ID when its action is corrected."
        ids = self.sections(self.file("manual.csv", 40))
        self.say("I onboard new suppliers. I start from the supplier form.")
        self.say("Finance approves every supplier above 10,000 before I activate it.")
        for route, lead in (("/api/agent-team/workflow", "team_working_process_map"), ("/api/workflow", "working_process_map")):
            with self.subTest(route=route):
                # The map alone cites thirteen sections; the thirteenth is not read.
                self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in ids[:13]]}
                self.memo = None
                accepted = self.workflow["steps"][12]
                corrected = {**accepted, "title": "Finance approves the supplier", "evidence_turns": [ids[12], "t2"]}
                self.client.map_additions = [corrected]
                status, body = self.update_map(route, apply=False)
                self.assertEqual(status, 200, body)
                self.assertNotIn(ids[12], self.last_call(lead)["shown"])
                self.assertEqual(body["workflow"]["steps"][12]["title"], "Finance approves the supplier")
                self.assertEqual(body["workflow"]["steps"][12]["evidence_turns"], [ids[12], "t2"])
                self.assertEqual(left_out(body), [])
                # Retitled with nothing this update read: that one edit is left out, the map is still updated.
                self.client.map_additions = [{**accepted, "title": "Retitled without a source of its own"}]
                status, body = self.update_map(route, apply=False)
                self.assertEqual(status, 200, body)
                self.assertEqual(body["workflow"]["steps"][12], accepted)
                self.assertEqual(len(body["workflow"]["steps"]), 13)
                # The response says which step kept its accepted wording.
                self.assertEqual(left_out(body), [f"step {accepted['id']} ({accepted['title']})"])

    def test_a_changed_step_cannot_keep_a_citation_of_a_removed_or_parked_file_beyond_the_limit(self):
        # "Inactive document evidence may preserve an existing component, not establish a new or changed
        # fact." Within the limit the saved excerpt of the removed file is sent as retained evidence and
        # an edit that cites it is refused. Beyond the limit the same excerpt is only reported as known
        # and the model cannot see that it is inactive: the edit must not be accepted there either. It
        # is left out and named, the accepted step stays, and the rest of the update is applied.
        refusal = {"/api/agent-team/workflow": 400, "/api/workflow": 502}
        for action in ("remove", "park"):
            for active, fits in ((3, True), (12, False)):
                with self.subTest(action=action, active_cited_sections=active):
                    self.begin()
                    old = self.file("oldrules.csv", 2)
                    saved = self.sections(old)[0]
                    ids = self.sections(self.file("manual.csv", 40))
                    self.say("I onboard new suppliers. I start from the supplier form.")
                    self.say("Finance approves every supplier above 10,000 before I activate it.")
                    accepted = step(saved, "Follow the old rule")
                    self.workflow = {**EMPTY_MAP, "title": "Supplier onboarding",
                                     "steps": [accepted, *(step(source) for source in ids[:active])]}
                    self.memo = None
                    self.file_action(old, action)
                    corrected = {**accepted, "title": "Finance approves instead", "evidence_turns": [saved, "t2"]}
                    added = step("t2", "Activate the supplier")
                    for route, lead in (("/api/agent-team/workflow", "team_working_process_map"), ("/api/workflow", "working_process_map")):
                        self.client.map_additions = [corrected, added]
                        status, body = self.update_map(route, apply=False)
                        supporting = self.last_call(lead)["supporting"]
                        # The scenario is the one intended: the saved excerpt was sent, or was only carried.
                        self.assertEqual(saved in [item["id"] for item in supporting["retained_evidence"]], fits)
                        self.assertEqual(supporting["omitted_prior_sources"], 0 if fits else 1)
                        if fits:
                            self.assertEqual((status, body.get("error", "the update was applied")), (refusal[route],
                                "Inactive document evidence may preserve an existing component, not establish a new or changed fact."))
                        else:
                            self.assertEqual(status, 200, body.get("error"))
                            self.assertEqual(body["workflow"]["steps"][0], accepted)
                            self.assertEqual(left_out(body), [f"step {accepted['id']} (Follow the old rule)"])
                            self.assertEqual(sum("parked or removed file" in question
                                                 for question in body["workflow"]["open_questions"]), 1)
                            # The rest of the update was applied.
                            self.assertEqual(body["workflow"]["steps"][-1], added)
                        # The step repeated as accepted is no change: the update is applied and the step kept.
                        self.client.map_additions = [copy.deepcopy(accepted)]
                        status, body = self.update_map(route, apply=False)
                        self.assertEqual(status, 200, body)
                        self.assertEqual(body["workflow"]["steps"][0], accepted)
                        self.assertEqual(left_out(body), [])

    # ---- both routes in one interview ------------------------------------
    def test_live_answers_keep_both_the_map_and_the_notes_updating(self):
        # Each Live answer sends the map from a partial caption and the notes from the finished one:
        # the same pins, different wording, so each fills what is left of the limit differently.
        ids = self.sections(self.file("manual.csv", 40))
        self.say("I onboard new suppliers. I start from the supplier form.")
        unread = []
        def answer(partial, final):
            self.say(partial)
            partial_turns = copy.deepcopy(self.turns)
            self.turns[-1]["text"] = final
            drawn = self.update_map(turns=partial_turns, apply=False)
            noted = self.update_notes()
            self.assertEqual((drawn[0], noted[0]), (200, 200), (drawn[1].get("error"), noted[1].get("error")))
            self.workflow = drawn[1]["workflow"]
            unread.append((drawn[1]["document_reading"].get("omitted_prior_sources", 0),
                           noted[1]["document_reading"].get("omitted_prior_sources", 0)))
        first = "I mostly follow " + " ".join(f"manualsec{index}" for index in range(25, 34))
        answer(first, first + " and then " + " ".join(f"manualsec{index}" for index in range(10, 19)))
        self.assertGreater(len(cited([self.workflow, self.memo])) * (SECTION - 200), 60000,
                           "this scenario no longer exceeds the limit; the test would prove nothing")
        for number in range(2, 5):
            answer(f"Next is manualsec{number} manualsec{number + 30}",
                   f"Next is manualsec{number} manualsec{number + 30} and after that manualsec{number + 5} approval")
        self.assertTrue(all(drawn > 0 for drawn, _ in unread[1:]), unread)
        status, body = self.update_notes("document_followup")
        self.assertEqual(status, 200, body)
        status, body = self.update_map()
        self.assertEqual(status, 200, body)
        self.assertTrue(set(cited(self.workflow)) <= set(ids))

    def test_the_map_starts_from_the_private_citations_of_the_notes(self):
        manual = self.file("manual.csv", 40)
        ids = self.sections(manual)
        self.client.capture_limit = 6
        self.say("I follow " + " ".join(f"manualsec{index}" for index in range(10, 19)))
        status, body = self.update_notes()
        self.assertEqual(status, 200, body)
        noted = self.ledger_citations(manual)
        self.assertEqual(len(noted), 6)
        # The browser has not pinned those citations (as after a file follow-up) and asks for the
        # map with other wording. The map must be shown the excerpts the notes are built on.
        own = next(source for source in ids[30:] if source not in self.last_call("team_interview_capture")["shown"])
        self.memo, self.workflow = None, {**EMPTY_MAP, "steps": [step(own)]}
        self.say("Then " + " ".join(f"manualsec{index}" for index in range(20, 29)))
        for route, lead in (("/api/agent-team/workflow", "team_working_process_map"), ("/api/workflow", "working_process_map")):
            with self.subTest(route=route):
                self.hydrate.reset_mock()
                status, body = self.update_map(route, apply=False)
                self.assertEqual(status, 200, body)
                pins = self.hydrate.call_args_list[0].kwargs["source_ids"]
                # The map's own citation stays first; the notes' private citations follow.
                self.assertEqual(pins, [own, *noted])
                self.assertEqual(self.last_call(lead)["shown"][:7], [own, *noted])
                self.assertNotIn("omitted_prior_sources", body["document_reading"])

    def test_room_for_matches_reaches_the_models_and_never_displaces_what_the_notes_are_built_on(self):
        # document-service-5. The map cites twelve sections of a long manual: 57,600 of the 60,000
        # characters one request reads. The conversation then moves to sections nobody has cited.
        manual = self.file("manual.csv", 40)
        ids = self.sections(manual)
        self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in ids[:12]]}
        self.say("For returns I follow manualsec30 and then manualsec31.")
        status, body = self.update_notes()
        self.assertEqual(status, 200, body)
        shown = self.last_call("team_interview_capture")["shown"]
        self.assertTrue({ids[30], ids[31]} <= set(shown), "The sections the answer is about were not read")
        self.assertEqual(shown[:10], ids[:10], "Cited excerpts still come first, in the browser's order")
        self.assertEqual(body["document_reading"]["omitted_prior_sources"], 2)
        built_on = self.ledger_citations(manual)
        self.assertEqual(built_on, sorted(shown))
        # The notes now rest on twelve sections themselves. Those are read back before any room is
        # kept for a match: a fact record loses its tags and connections when its excerpt is not.
        self.say("Refunds are covered in manualsec35.")
        status, body = self.update_notes()
        self.assertEqual(status, 200, body)
        call = self.last_call("team_interview_capture")
        self.assertTrue(set(built_on) <= set(call["shown"]), "An excerpt the notes are built on was not read back")
        self.assertEqual(self.ledger_citations(manual), built_on)
        self.assertNotIn(ids[35], call["shown"])
        # The request says that it found more on the subject than it could read.
        self.assertGreaterEqual(call["supporting"]["omitted_query_matches"], 1)
        # The map is not bound to the notes' citations in that way: it reads the matching section.
        for route, lead in (("/api/agent-team/workflow", "team_working_process_map"), ("/api/workflow", "working_process_map")):
            with self.subTest(route=route):
                status, body = self.update_map(route, apply=False)
                self.assertEqual(status, 200, body)
                call = self.last_call(lead)
                self.assertIn(ids[35], call["shown"])
                self.assertLessEqual(call["supporting"]["context_budget"]["characters"], 60000)
                self.assertGreater(body["document_reading"]["omitted_prior_sources"], 0)
                self.assertEqual([item["id"] for item in body["workflow"]["steps"]][:12], [step(source)["id"] for source in ids[:12]],
                                 "Every accepted step is kept, read again or not")

    @NO_ROOM_FOR_MATCHES
    def test_notes_keep_updating_when_two_files_are_cited_beyond_the_limit(self):
        for large_first in (True, False):
            with self.subTest(large_file_sorts_first=large_first):
                for _ in range(80):
                    self.begin()
                    small, large = self.file("checklist.csv", 3), self.file("manual.csv", 40)
                    if (large < small) == large_first:
                        break
                else:
                    self.fail("No file order of the wanted kind was produced.")
                brief, manual = self.sections(small), self.sections(large)
                # The notes are built on the checklist and nine sections of the manual.
                self.say("I onboard new suppliers. I start from the supplier form.")
                self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in [*brief, *manual[10:19]]]}
                status, body = self.update_notes()
                self.assertEqual(status, 200, body)
                self.assertEqual((self.ledger_citations(small), self.ledger_citations(large)), (sorted(brief), sorted(manual[10:19])))
                # The map cites the checklist and nine other sections: 100,000 characters are now cited.
                self.workflow = {**EMPTY_MAP, "steps": [step(source) for source in [*brief, *manual[25:34]]]}
                for number in range(2):
                    self.say(f"Then approval stage {number} happens and I file the form.")
                    status, body = self.update_notes()
                    self.assertEqual(status, 200, body)
                    self.assertEqual(body["document_reading"]["omitted_prior_sources"], 9)
                    # Every excerpt the notes are built on was read again; none of their facts was lost.
                    self.assertTrue(set(brief) | set(manual[10:19]) <= set(self.last_call("team_interview_capture")["shown"]))
                    self.assertEqual((self.ledger_citations(small), self.ledger_citations(large)),
                                     (sorted(brief), sorted(manual[10:19])))
                self.assertEqual(self.update_map(apply=False)[0], 200)
                status, body = self.update_notes("document_followup")
                self.assertEqual(status, 200, body)
                for action in ("park", "remove"):
                    self.file_action(large, action)
                    self.say(f"After the manual was set aside ({action}), I still file the form.")
                    drawn = self.update_map(apply=False)
                    self.assertEqual(drawn[0], 200, drawn[1])
                    status, body = self.update_notes()
                    self.assertEqual(status, 200, body)
                    # The manual's facts go with the file; the checklist's stay, read from the active file.
                    self.assertEqual((self.ledger_citations(small), self.ledger_citations(large)), (sorted(brief), []))
                    self.assertTrue(set(brief) <= set(self.last_call("team_interview_capture")["shown"]))
                    status, body = self.update_notes("document_followup")
                    self.assertEqual(status, 200, body)


class CompletionBeyondLimitTests(unittest.TestCase):
    """The completion review and the final confirmation replay the excerpts their capture was shown.

    How many earlier citations a request could not carry depends on the list it asked for. The
    replay asks for the capture's own excerpts, so that count must not make it look like a change
    of evidence, while a real change of the files must still invalidate the review.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="collector-budget-review-")
        self.client = SyntheticTeamProvider()
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
            documents_root=Path(self.temp.name) / "documents", knowledge_root=Path(self.temp.name) / "knowledge")
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.store = self.httpd.documents_store
        self.scope = self.store.create_scope()
        rows = ["section,detail"]
        for index in range(40):
            body = f"manualsec{index} invoice evidence material risk reference {index} "
            rows.append(f"{index}," + (body * (SECTION // len(body) + 1))[:SECTION - 12])
        self.document_id = self.store.add(self.scope, "manual.csv", ("\n".join(rows) + "\n").encode())["id"]
        self.store.extract(self.scope, self.document_id)
        self.store.update(self.scope, self.document_id, {"analysis": {
            "phase": "complete", "review_complete": True, "disposition": "relevant", "summary": "Fictional reference."}})
        self.ids = [chunk["id"] for chunk in self.store.chunks(self.scope, self.document_id, limit=200)["chunks"]]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)
        self.temp.cleanup()

    post = BudgetCarryTests.post

    def prepared(self, pins):
        """A capture that is ready for its completion review, from a browser that pins `pins`."""
        payload = self.client.payload()
        payload.update(document_scope=self.scope, document_source_ids=pins)
        code, prepared = self.post("/api/interview", payload)
        self.assertEqual(code, 200, prepared)
        self.assertEqual(prepared["speech_authorization"]["kind"], "review_pending")
        payload["turns"].append({"id": "review_ack", "role": "assistant", "text": prepared["question"]})
        payload.update(capture_token=prepared["capture_token"], review_ticket=prepared["review_ticket"])
        return payload, prepared

    def test_review_and_confirmation_match_their_capture_when_more_is_cited_than_one_request_can_read(self):
        requested = self.ids[:16]
        payload, prepared = self.prepared(requested)
        # Current-turn matches also share the budget. Count the specific prior citations
        # the capture was shown, even when a fresh match used one of its twelve slots.
        omitted = set(requested) - {source["id"] for source in prepared["document_evidence"]}
        self.assertTrue(omitted)
        self.assertEqual(prepared["document_reading"]["omitted_prior_sources"], len(omitted))
        code, reviewed = self.post("/api/agent-team/review", payload)
        self.assertEqual(code, 200, reviewed)
        self.assertEqual(reviewed["speech_authorization"]["kind"], "final_check")
        self.assertEqual(self.client.request.call_count, 1 + REVIEW_CALLS)
        payload.pop("review_ticket")
        payload["capture_token"] = reviewed["capture_token"]
        payload["turns"] += [{"id": "global_check", "role": "assistant", "text": reviewed["question"]},
                             {"id": "confirmation", "role": "user", "text": "No, that's everything."}]
        code, completed = self.post("/api/interview", payload)
        self.assertEqual(code, 200, completed)
        self.assertTrue(completed["completion"]["complete"])
        self.assertEqual(self.client.request.call_count, 1 + REVIEW_CALLS, "the confirmation needs no further provider call")

    def test_a_removed_file_still_invalidates_the_review_beyond_the_limit(self):
        payload, _ = self.prepared(self.ids[:16])
        self.store.archive(self.scope, self.document_id)
        code, result = self.post("/api/agent-team/review", payload)
        self.assertEqual(code, 409, result)
        self.assertEqual(self.client.request.call_count, 1)
        self.assertNotIn("speech_authorization", result)


if __name__ == "__main__":
    unittest.main()
