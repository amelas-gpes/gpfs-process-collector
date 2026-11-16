"""Offline reproductions of audit findings in capture, review and session expiry."""
import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from test_server import server
from test_capture_facts import facts, transaction, operation
from test_interview_orchestrator import SyntheticTeamProvider, prepared_review, reply_payload
from test_concurrent_interview import API, FakeClient, module, payload
from evaluate_capture_attribution import validate_attribution


class AuditRegressions(unittest.TestCase):
    def test_review_provenance_includes_parallel_stages_and_survives_cached_replay(self):
        client = SyntheticTeamProvider()
        payload, initial = prepared_review(client)
        final = client.coordinator.review(payload)
        self.assertEqual(initial["app_version"], server.VERSION)
        self.assertEqual({row["stage"] for row in final["generated_by"]},
                         {"team_interview_capture", "process_coverage_assessment", "process_specialist_review"})
        self.assertTrue(all(len(row["prompt_id"]) == 16 and row["model"] for row in final["generated_by"]))
        self.assertEqual(client.coordinator.review(payload)["generated_by"], final["generated_by"])
        self.assertEqual(len({row["prompt_id"] for row in final["generated_by"] if row["stage"] == "process_coverage_assessment"}),
                         len(server.interview_coverage.COVERAGE_REVIEW_GROUPS))

    def test_provenance_flags_changed_amount_role_and_short_quotes(self):
        state = facts.empty_state()
        turns = [{"id": "u1", "role": "user", "text": "The registrar files the waiver for $110 after approval."}]
        row = operation("checks", "The instructor files the waiver for $10.", "u1")
        row["support"] = [{"source_id": "u1", "quote": "f"}]
        updated = facts.apply_delta(state, transaction(state, [row]), {}, turns, [])
        fact = updated["facts"][0]
        self.assertFalse(fact["support"])
        self.assertTrue(any("$10" in warning for warning in fact["unverified"]))
        row["text"] = "The registrar files the waiver for $110 after approval."
        row["support"] = [{"source_id": "u1", "quote": turns[0]["text"]}]
        updated = facts.apply_delta(state, transaction(state, [row]), {}, turns, [])
        self.assertFalse(updated["facts"][0]["unverified"])

    def test_idle_reclamation_and_restoration(self):
        service = module.ConcurrentInterview(FakeClient(), API)
        self.addCleanup(service.close)
        first = service._session(payload(), create=True)
        first["at"] -= 1900
        service.prune()
        data = {**payload(), "conversation_token": first["token"]}
        with self.assertRaises(server.APIError) as response:
            service.status(data)
        self.assertEqual((response.exception.status, response.exception.category), (409, "conversation_expired"))
        self.assertNotEqual(service._session(data, create=True)["token"], first["token"])

    def test_live_fragments_confirm_without_paid_calls_after_an_hour(self):
        client = SyntheticTeamProvider()
        data = client.payload()
        data["live_notes"] = True
        snap, _ = prepared_review(client, data)
        final = client.coordinator.review(snap)
        count = client.request.call_count
        client.coordinator._captures[final["capture_token"]]["at"] -= 3600
        client.coordinator.prune()
        fragment = reply_payload(snap, final, "No,")
        result = client.coordinator.interview(fragment)
        self.assertTrue(result["awaiting_continuation"])
        fragment["turns"].append({"id":"u_finish", "role":"user", "text":"nothing else."})
        complete = client.coordinator.interview(fragment)
        self.assertTrue(complete["completion"]["complete"])
        self.assertEqual(client.request.call_count, count)

    def test_interviewer_only_extension_reuses_review_but_tampering_cannot(self):
        client = SyntheticTeamProvider()
        snap = client.payload()
        first = client.coordinator.interview(snap)
        extension = copy.deepcopy(snap)
        extension["turns"].append({"id": "fast", "role":"assistant", "text":"What happens with the file?"})
        bound = client.coordinator.rebind_capture(first["capture_token"], extension)
        self.assertEqual(bound["review_ticket"], first["review_ticket"])
        self.assertEqual(client.request.call_count, 1)
        extension["turns"][0]["text"] += " Changed participant account."
        self.assertIsNone(client.coordinator.rebind_capture(bound["capture_token"], extension))

    def test_review_counter_does_not_invalidate_but_changed_passage_does(self):
        one = {"documents":[{"id":"d","review":{"phase":"reviewing","reviewed_chunks":1},
                             "excerpts":[{"id":"chunk","text":"Source text."}]}]}
        two = copy.deepcopy(one)
        two["documents"][0]["review"]["reviewed_chunks"] = 3
        self.assertEqual(facts.supporting_identity(one), facts.supporting_identity(two))
        two["documents"][0]["excerpts"][0]["text"] = "Different content."
        self.assertNotEqual(facts.supporting_identity(one), facts.supporting_identity(two))

    def test_attribution_fixture_detects_wrong_subject_in_every_section(self):
        account = {"materials":"The waiver is kept in the green binder.",
                   "lifecycle":"The registrar then carefully files the signed waiver."}
        validate_attribution(account)
        for wrong in ("The instructor files it.", "The instructors are responsible for filing signed waivers.",
                      "The waiver is stored by the instructor."):
            with self.subTest(wrong=wrong), self.assertRaises(AssertionError):
                validate_attribution({**account, "completion": wrong})

    def test_reported_connection_survives_an_empty_delta_until_a_cited_correction(self):
        turns = [{"id":"u1", "role":"user", "text":"We hand the register to Treasury."}]
        state = facts.empty_state()
        row = transaction(state)
        row["connections_out"] = [{"relationship_type":"hands_off_to", "counterpart":"Treasury",
                                   "condition":"At close", "evidence_turns":["u1"]}]
        state = facts.apply_delta(state, row, {}, turns, [])
        identity = state["connections_out"][0]["id"]
        state = facts.apply_delta(state, transaction(state), {}, turns, [])
        self.assertEqual(state["connections_out"][0]["id"], identity)
        turns.append({"id":"u2", "role":"user", "text":"Correction, we do not hand anything to Treasury."})
        edit = transaction(state)
        edit["remove_connections"] = [{"target_id":identity, "evidence_turns":["u2"]}]
        self.assertFalse(facts.apply_delta(state, edit, {}, turns, [])["connections_out"])

    def test_gold_standard_metadata_slip_keeps_substantive_fact(self):
        state = facts.empty_state()
        turns = [{"id":"u1", "role":"user", "text":"The registrar checks the waiver."}]
        delta = transaction(state, [operation("checks", turns[0]["text"])])
        delta["tag_operations"] = [{"op":"add", "target_id":"", "facet":"variant_class", "value":"gold_standard",
                                    "note":"Usual case.", "evidence_turns":["u1"]}]
        result = facts.apply_delta(state, delta, {}, turns, [])
        self.assertEqual(result["tags"][0]["value"], "unclassified")
        self.assertEqual(result["facts"][0]["text"], turns[0]["text"])

    def test_dropped_tokenless_fast_reply_frees_the_unknown_session(self):
        client = FakeClient()
        service = module.ConcurrentInterview(client, API)
        self.addCleanup(service.close)
        with patch.object(client, "structured", side_effect=server.APIError("Synthetic failure")):
            with self.assertRaises(server.APIError):
                service.turn(payload())
        self.assertFalse(service._sessions)

    def test_both_sync_deadlines_leave_the_account_recoverable(self):
        for kind in ("notes", "workflow"):
            with self.subTest(kind=kind):
                gate = threading.Event()
                client = FakeClient(gate if kind == "notes" else None)
                client.graph_gate = gate if kind == "workflow" else None
                service = module.ConcurrentInterview(client, API)
                try:
                    data = payload()
                    response = service.turn(data)
                    data["conversation_token"] = response["conversation_token"]
                    with self.assertRaises(server.APIError) as expired:
                        service.sync(data, timeout=.05)
                    self.assertEqual(expired.exception.status, 504)
                    gate.set()
                    self.assertTrue(service.sync(data, timeout=3)["capture_token"])
                finally:
                    gate.set()
                    service.close()

    def test_129_independent_pending_reviews_do_not_starve_new_capture(self):
        client = SyntheticTeamProvider()
        context, turns = server.validate_payload(client.payload())
        for _ in range(129):
            _, run = client.coordinator._new_run({},context,turns,[])
            run.run_role("lead_interviewer", lambda: {"question":"What starts it?"})
        self.assertEqual(len(client.coordinator._runs), 128)

    def test_sparse_repair_keeps_unmentioned_source_statements(self):
        from test_interview_coverage import fixture
        findings, assessment, turns = fixture()
        for row in assessment["topics"]:
            row["capture_repair"] = {"needed": False, "edits":[]}
        topic = next(row for row in assessment["topics"] if row["key"] == "checks")
        prior = next(row for row in findings if row["key"] == "checks")["answer"]
        added = "The AP manager records the approval in the register."
        turns.append({"id":"u_edit", "role":"user", "text":added})
        topic["capture_repair"] = {"needed":True, "edits":[{"previous_statement":"", "replacement_statement":added,
                                                             "evidence_turns":["u_edit"]}]}
        revised, checked = server.interview_coverage.apply_repair_assessment(findings,assessment,turns)
        self.assertEqual(checked["capture_repairs"][0]["statement_evidence"],{added:["u_edit"]})
        self.assertIn(prior, " ".join(next(row for row in revised if row["key"] == "checks")["answer"].split()))

    def test_real_provider_registrar_replay_covers_actor_timeframe_and_routes(self):
        replay = json.loads((Path(__file__).parent / "fixtures" / "registrar-replay.json").read_text(encoding="utf8"))
        findings = {fact["topic"]:fact["text"] for fact in replay["facts"]}
        validate_attribution(findings)
        self.assertIn("used to use a blue binder", findings["variations"])
        self.assertIn("digital filing is a possible future change", findings["variations"])
        roles = {step["id"]:step["actor"].casefold() for step in replay["steps"]}
        observed = {(roles[route["from"]], roles[route["to"]]) for route in replay["routes"]}
        self.assertEqual(observed, {("registrar","instructor"), ("instructor","registrar")})
        self.assertIn("registrar as filing signed waivers", replay["document_observations"][0])
        self.assertIn("instructor as keeping the room schedule", replay["document_observations"][0])
        self.assertTrue(all(s.get("model") and s.get("prompt_id") for s in replay["stages"]))
        sources = {turn["id"]:turn["text"] for turn in replay["turns"]}
        for fact in replay["facts"]:
            for passage in fact["support"]:
                if passage["source_id"] in sources:
                    self.assertIn(" ".join(passage["quote"].casefold().split()),
                                  " ".join(sources[passage["source_id"]].casefold().split()))
        self.assertTrue(next(fact for fact in replay["facts"] if fact["topic"]=="data_systems")["unverified"])

    def test_interview_objective_is_never_promoted_to_a_business_purpose(self):
        state = facts.empty_state()
        context = {"objective":"Record how workshop waivers are filed.", "background":"Fictional museum example."}
        delta = transaction(state, [operation("purpose","The stated objective is to record how workshop waivers are filed.","context")],
                            {"purpose":"captured"})
        account = facts.apply_delta(state,delta,context,[],[])
        self.assertEqual(account["topics"]["purpose"]["status"], "partial")
        self.assertEqual(account["facts"][0]["kind"], "gap")

    def test_new_evidence_identity_includes_amount_but_excludes_progress_counters(self):
        state = facts.empty_state()
        sources = {"context":{"authority":"context"}, "u1":{"authority":"participant"}}
        wire = facts.schema_for(state, sources, with_question=False)
        self.assertNotIn("question", wire["properties"])
        self.assertEqual(wire["properties"]["fact_operations"]["maxItems"], 128)
        branches = wire["properties"]["tag_operations"]["items"]["anyOf"]
        values = [value for branch in branches for value in branch["properties"]["value"]["enum"]]
        self.assertNotIn("gold_standard", values)
