"""Fact preservation and authority regressions using hand-authored transactions."""
import copy
import json
import unittest
from unittest.mock import Mock

from test_server import server
import capture_facts as facts
from test_interview_orchestrator import SyntheticTeamProvider, prepared_review, reply_payload
from fact_fixture import fixture_reconciliations


def transaction(state, operations=(), statuses=None, unavailable=()):
    return {"question": "Who is accountable for the result?", "summary": "Reported account.",
            "focus": "Clarify accountability", "parking_lot": [], "base_revision": state["revision"],
            "fact_reconciliations": fixture_reconciliations(state, list(operations)),
            "topic_states": [{"key": key, "status": (statuses or {}).get(key, state["topics"][key]["status"]),
                              "participant_unavailable": key in unavailable} for key in facts.TOPICS],
            "fact_operations": list(operations)}


def operation(topic, text, source="u1", *, kind="detail", op="add", target="", reason="new_evidence"):
    return {"op": op, "topic": topic, "target_id": target, "kind": kind, "text": text,
            "evidence_turns": [source], "reason": reason}


def from_model_input(model_input, operations=(), statuses=None, unavailable=()):
    # Keep the server's scoped reconciliation targets: only those need a row.
    state = {"revision": model_input["fact_state"]["base_revision"],
             "topics": model_input["fact_state"]["topics"], "facts": model_input["fact_state"]["facts"],
             "reconciliation_targets": model_input["fact_state"]["reconciliation_targets"]}
    return transaction(state, operations, statuses, unavailable)


def typed_responder(client, callback):
    previous = client.reply
    def reply(path, body, *args, **kwargs):
        if body["text"]["format"]["name"] != "team_interview_capture":
            return previous(path, body, *args, **kwargs)
        model_input = json.loads(body["input"][0]["content"])
        result = callback(model_input)
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}]}
    client.request = Mock(side_effect=reply)


class ScopedReconciliationTests(unittest.TestCase):
    """Only open claims the latest answer could affect need an explicit reconciliation row."""

    def setUp(self):
        self.context = {"process_name": "Invoice intake"}
        self.turns = [{"id": "a1", "role": "assistant", "text": "Who owns the overall result?"},
                      {"id": "u1", "role": "user",
                       "text": "I don't know who owns the overall result, and I am not sure where the procedure is kept."}]
        self.documents = []

    def seeded(self):
        state = facts.empty_state()
        delta = transaction(state, [
            operation("accountable", "The accountable owner is unknown.", kind="gap"),
            operation("materials", "The procedure's storage location is not specified.", kind="gap")],
            {"accountable": "partial", "materials": "partial"})
        server.check_schema(delta, facts.FACT_DELTA_SCHEMA)
        return facts.apply_delta(state, delta, self.context, self.turns, self.documents)

    def test_turn_focus_pairs_the_latest_answer_with_its_question(self):
        self.assertIsNone(facts.turn_focus([{"id": "a1", "role": "assistant", "text": "What starts it?"}]))
        self.assertEqual(facts.turn_focus(self.turns), {"answer": self.turns[1]["text"], "question": self.turns[0]["text"]})
        notice = {"id": "n1", "role": "user", "text": "File update", "document_event": True}
        self.assertEqual(facts.turn_focus(self.turns + [notice])["answer"], self.turns[1]["text"])

    def test_untouched_gap_needs_no_row_but_can_still_be_resolved_explicitly(self):
        state = self.seeded()
        self.turns += [{"id": "a2", "role": "assistant", "text": "Which role owns the overall result?"},
                       {"id": "u2", "role": "user", "text": "The AP manager owns it."}]
        focus = facts.turn_focus(self.turns)
        scoped = facts.reconciliation_targets(state, focus)
        self.assertEqual([fact["topic"] for fact in scoped], ["accountable"])
        self.assertEqual(len(facts.reconciliation_targets(state)), 2)
        schema = facts.schema_for(state, facts.sources(self.context, self.turns, self.documents), focus)
        self.assertEqual(schema["properties"]["fact_reconciliations"]["maxItems"], 1)
        self.assertEqual(list(schema["properties"])[0], "question", "The question streams first")
        model = facts.model_state(state, focus)
        self.assertEqual(model["reconciliation_targets"], [scoped[0]["id"]])
        self.assertEqual([fact["id"] for fact in facts.reconciliation_targets(model)], [scoped[0]["id"]],
                         "A model-facing state carries the already selected targets")
        resolved = operation("accountable", "The AP manager owns the overall result.", "u2",
                             op="replace", target=scoped[0]["id"], reason="resolved_gap")
        delta = transaction(state, [resolved])
        delta["fact_reconciliations"] = [{"target_id": scoped[0]["id"], "disposition": "replace",
                                          "basis": "The AP manager is now named as the owner."}]
        with self.assertRaises(ValueError):
            facts.apply_delta(state, delta, self.context, self.turns, self.documents)
        after = facts.apply_delta(state, delta, self.context, self.turns, self.documents, focus)
        answers = {item["key"]: item["answer"] for item in facts.findings(after)}
        self.assertEqual(answers["accountable"], "The AP manager owns the overall result.")
        self.assertIn("storage location is not specified", answers["materials"])
        materials_gap = next(fact for fact in after["facts"] if fact["topic"] == "materials" and fact["state"] == "active")
        retire = operation("materials", "", "u2", op="remove", target=materials_gap["id"], reason="withdrawal")
        delta = transaction(after, [retire])
        delta["fact_reconciliations"] = []
        self.assertEqual(facts.reconciliation_targets(after, focus), [])
        later = facts.apply_delta(after, delta, self.context, self.turns, self.documents, focus)
        self.assertEqual(next(item for item in facts.findings(later) if item["key"] == "materials")["status"], "unknown")

    def test_renamed_process_keeps_participant_cited_facts(self):
        # The working map names the process after the first turn; that context
        # change must not discard the private ledger or force a full re-seed.
        client = SyntheticTeamProvider()
        payload = client.payload()
        seen = []

        def response(model_input):
            seen.append(model_input)
            if len(seen) == 1:
                return from_model_input(model_input, [operation("trigger", "A supplier email starts a case.", "u_trigger")],
                                        {"trigger": "partial"})
            return from_model_input(model_input)
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "The finance team lead is accountable for the whole process.")
        follow["context"] = {**follow["context"], "process_name": "Monthly expense claim approval"}
        client.coordinator.interview(follow)
        self.assertEqual([fact["text"] for fact in seen[1]["fact_state"]["facts"]], ["A supplier email starts a case."])

    def test_live_interviewer_caption_between_captures_keeps_the_ledger(self):
        # In live voice the assistant turn after a capture is GPT-Live's own
        # caption, not the lead's question. Participant-cited facts survive it.
        client = SyntheticTeamProvider()
        payload = client.payload()
        seen = []

        def response(model_input):
            seen.append(model_input)
            if len(seen) == 1:
                return from_model_input(model_input, [operation("trigger", "A supplier email starts a case.", "u_trigger")],
                                        {"trigger": "partial"})
            return from_model_input(model_input)
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "The AP manager owns the result.")
        follow["turns"][-2]["text"] = "Got it. And who looks after the result overall?"
        client.coordinator.interview(follow)
        self.assertEqual([fact["text"] for fact in seen[1]["fact_state"]["facts"]], ["A supplier email starts a case."])
        self.assertEqual(client.request.call_count, 2)

    def test_unrelated_answer_keeps_the_fast_lead_despite_an_open_gap(self):
        client = SyntheticTeamProvider()
        client.agent_models["process_reviewer"] = "configured-reconciler"
        payload = client.payload()
        next(turn for turn in payload["turns"] if turn["id"] == "u_accountable")["text"] = "I don't know who owns the overall result."
        seen = []

        def response(model_input):
            seen.append(model_input)
            if len(seen) == 1:
                result = from_model_input(model_input, [operation("accountable", "The accountable owner is unknown.",
                                                                  "u_accountable", kind="gap")], {"accountable": "partial"})
                result["question"] = "Where is the written procedure kept?"
                return result
            return from_model_input(model_input)
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        self.assertEqual(first["question"], "Where is the written procedure kept?")
        second = client.coordinator.interview(reply_payload(payload, first, "On the finance team's shared drive."))
        self.assertEqual([call.args[1]["model"] for call in client.request.call_args_list], ["synthetic-lead", "synthetic-lead"])
        self.assertEqual(seen[1]["fact_state"]["reconciliation_targets"], [])
        self.assertTrue(any(fact["kind"] == "gap" for fact in seen[1]["fact_state"]["facts"]),
                        "The untouched gap stays visible to the lead")
        self.assertEqual(next(row["model"] for row in second["agent_team"]["agents"] if row["role"] == "lead_interviewer"),
                         "synthetic-lead")


class FactTransactionTests(unittest.TestCase):
    def setUp(self):
        self.context = {"process_name": "Event processing"}
        self.turns = [{"id": "u1", "role": "user", "text":
                       "Completion requires a locked package and settlement where applicable. The reviewer checks the totals."}]
        self.documents = []

    def apply(self, state, delta):
        server.check_schema(delta, facts.FACT_DELTA_SCHEMA)
        return facts.apply_delta(state, delta, self.context, self.turns, self.documents)

    def seeded(self):
        state = facts.empty_state()
        return self.apply(state, transaction(state, [
            operation("completion", "Completion requires an approved, locked package."),
            operation("completion", "Cash settlement is required where applicable."),
            operation("checks", "The reviewer checks the totals.")],
            {"completion": "partial", "checks": "partial"}))

    def test_new_closeout_fact_preserves_earlier_conditions_without_resending_them(self):
        state = self.seeded()
        before = copy.deepcopy(state)
        self.turns.append({"id": "u2", "role": "user", "text": "We retain the final closeout record."})
        after = self.apply(state, transaction(state, [operation("completion", "The final closeout record is retained.", "u2")]))
        answer = next(item["answer"] for item in facts.findings(after) if item["key"] == "completion")
        for text in ("approved, locked package", "settlement is required where applicable", "closeout record is retained"):
            self.assertIn(text, answer)
        self.assertEqual(state, before, "A transaction must not mutate its input snapshot")

    def test_targeted_actor_correction_cannot_drop_other_conditions(self):
        state = self.seeded()
        target = next(fact["id"] for fact in state["facts"] if fact["topic"] == "checks")
        self.turns.append({"id": "u2", "role": "user", "text": "Correction: the controller checks the totals, not the reviewer."})
        after = self.apply(state, transaction(state, [operation("checks", "The controller checks the totals.", "u2",
            op="replace", target=target, reason="participant_correction")]))
        self.assertEqual(next(item["answer"] for item in facts.findings(after) if item["key"] == "checks"),
                         "The controller checks the totals.")
        self.assertEqual([item for item in facts.findings(state) if item["key"] == "completion"],
                         [item for item in facts.findings(after) if item["key"] == "completion"])
        old = next(fact for fact in after["facts"] if fact["id"] == target)
        self.assertEqual(old["state"], "superseded")
        self.assertEqual(old["change_evidence"], ["u2"])

    def test_invalid_target_stale_revision_and_duplicate_change_fail_atomically(self):
        state = self.seeded()
        target = state["facts"][0]["id"]
        mutations = [operation("completion", "Remove unsupported clause.", op="remove", target="invented", reason="capture_correction"),
                     operation("checks", "Move a different topic's fact.", op="remove", target=target, reason="capture_correction")]
        for change in mutations:
            before = copy.deepcopy(state)
            with self.assertRaises(ValueError):
                self.apply(state, transaction(state, [operation("materials", "A known record."), change]))
            self.assertEqual(state, before)
        delta = transaction(state)
        delta["base_revision"] = "stale"
        with self.assertRaises(ValueError):
            self.apply(state, delta)
        change = operation("completion", "Corrected text.", op="replace", target=target, reason="capture_correction")
        with self.assertRaises(ValueError):
            self.apply(state, transaction(state, [change, change]))

    def test_resolved_gap_cannot_be_used_to_remove_a_material_detail(self):
        state = self.seeded()
        with self.assertRaises(ValueError):
            self.apply(state, transaction(state, [operation("completion", "It is resolved.", op="remove",
                target=state["facts"][0]["id"], reason="resolved_gap")]))

    def test_empty_remove_text_resolves_gap_but_keeps_authority_and_detail_guards(self):
        state = self.seeded()
        state = self.apply(state, transaction(state, [operation("completion", "The retained finish record is unknown.", kind="gap")]))
        target = next(fact["id"] for fact in state["facts"] if fact["kind"] == "gap")
        self.turns.append({"id": "u2", "role": "user", "text": "The closed record is retained in the event folder."})
        change = operation("completion", "", "u2", op="remove", target=target, reason="resolved_gap")
        delta = transaction(state, [change])
        server.check_schema(delta, facts.schema_for(state, ["u1", "u2", "context"]))
        result = self.apply(state, delta)
        old = next(fact for fact in result["facts"] if fact["id"] == target)
        self.assertEqual((old["state"], old["change_reason"], old["change_evidence"], old["change_text"]),
                         ("withdrawn", "resolved_gap", ["u2"], ""))
        self.assertTrue(any(fact["state"] == "active" and fact["kind"] == "detail" for fact in result["facts"]))
        for invalid in ({**change, "evidence_turns": ["forged"]}, {**change, "evidence_turns": []},
                        {**change, "target_id": state["facts"][0]["id"]},
                        {**change, "op": "replace"}, {**change, "op": "add", "target_id": "", "reason": "new_evidence"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.apply(state, transaction(state, [invalid]))

    def test_new_evidence_requires_gap_reconciliation_but_never_automatically_closes_it(self):
        state = self.seeded()
        gap = operation("completion", "The finish record and settlement boundary are not established.", kind="gap")
        state = self.apply(state, transaction(state, [gap]))
        self.turns.append({"id": "u2", "role": "user", "text": "A closed-event record is retained; the settlement boundary is still unknown."})
        additions = [operation("completion", "A closed-event record is retained.", "u2")]
        delta = transaction(state, additions, {"completion": "captured"})
        delta["fact_reconciliations"] = []
        with self.assertRaises(ValueError):
            self.apply(state, delta)
        delta = transaction(state, additions, {"completion": "captured"})
        delta["fact_reconciliations"][0]["basis"] = "The participant has not supplied the remaining settlement boundary."
        delta["fact_reconciliations"][0]["evidence_turns"] = ["u2"]
        unchanged = self.apply(state, delta)
        self.assertEqual(unchanged["topics"]["completion"]["status"], "partial")
        self.assertTrue(any(fact["kind"] == "gap" and fact["state"] == "active" for fact in unchanged["facts"]))
        target = next(fact["id"] for fact in state["facts"] if fact["kind"] == "gap")
        narrowed = self.apply(state, transaction(state, additions + [operation("completion", "The settlement boundary remains unknown.",
            "u2", kind="gap", op="replace", target=target, reason="resolved_gap")], {"completion": "captured"}))
        answer = next(item["answer"] for item in facts.findings(narrowed) if item["key"] == "completion")
        self.assertNotIn("finish record and settlement boundary are not established", answer)
        self.assertIn("settlement boundary remains unknown", answer)
        self.assertEqual(narrowed["topics"]["completion"]["status"], "partial")

    def test_mixed_detail_requires_explicit_review_and_cannot_be_silently_removed(self):
        state = self.seeded()
        mixed = "After release the file goes to posting and notices. The account does not establish their order."
        state = self.apply(state, transaction(state, [operation("lifecycle", mixed)]))
        target = next(fact["id"] for fact in facts.reconciliation_targets(state) if fact["topic"] == "lifecycle")
        self.assertIn(target, facts.model_state(state)["reconciliation_targets"])
        remove = operation("lifecycle", "", op="remove", target=target, reason="capture_correction")
        delta = transaction(state, [remove])
        delta["fact_reconciliations"][0]["disposition"] = "unchanged"
        with self.assertRaises(ValueError):
            self.apply(state, delta)
        for change in (lambda row: row.update(evidence_turns=["forged"]),
                       lambda row: row.update(disposition="replace"), lambda row: row.update(basis=""),
                       lambda row: row.update(target_id={"forged": True})):
            delta = transaction(state, [remove]); change(delta["fact_reconciliations"][0])
            before = copy.deepcopy(state)
            with self.assertRaises(ValueError):
                self.apply(state, delta)
            self.assertEqual(state, before)

    def test_new_protocol_cannot_silently_accept_old_delta_without_reconciliations(self):
        state = self.seeded()
        delta = transaction(state)
        delta.pop("fact_reconciliations")
        with self.assertRaises(ValueError):
            self.apply(state, delta)

    def test_participant_correction_or_withdrawal_requires_new_participant_evidence(self):
        state = self.seeded()
        for reason in ("participant_correction", "withdrawal"):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                self.apply(state, transaction(state, [operation("completion", "Disregard the old condition.",
                    op="remove", target=state["facts"][0]["id"], reason=reason)]))

    def test_forged_assistant_document_event_and_retained_only_sources_cannot_add_facts(self):
        self.turns.extend([{"id": "a1", "role": "assistant", "text": "An invented rule."},
                           {"id": "event1", "role": "user", "text": "File uploaded", "document_event": True}])
        self.documents = [{"id": "doc_old", "text": "Old rule", "retained_only": True}]
        for ref in ("invented", "a1", "event1", "doc_old"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                state = facts.empty_state()
                self.apply(state, transaction(state, [operation("checks", "A proposed rule.", ref)]))

    def test_changed_or_removed_document_retires_its_facts_but_preserves_participant_facts(self):
        self.documents = [{"id": "doc_rule", "text": "Reviewer approves."}]
        state = self.seeded()
        state = self.apply(state, transaction(state, [operation("checks", "The procedure assigns approval to the reviewer.", "doc_rule")]))
        for documents in ([], [{"id": "doc_rule", "text": "Controller approves."}]):
            after = facts.rebase(state, self.context, self.turns, documents)
            active = facts.model_state(after)["facts"]
            self.assertFalse(any("doc_rule" in fact["evidence_turns"] for fact in active))
            self.assertTrue(any(fact["topic"] == "completion" for fact in active))
            self.assertTrue(any(fact["state"] == "retired_source" for fact in after["facts"]))

    def test_unavailability_is_discussed_partial_not_untouched_or_not_applicable(self):
        self.turns += [{"id": "a_owner", "role": "assistant", "text": "Who is accountable for the result?"},
                       {"id": "u_unknown", "role": "user", "text": "I don't know."}]
        state = facts.empty_state()
        result = self.apply(state, transaction(state, [operation("accountable", "The participant cannot identify the accountable owner.",
            "u_unknown", kind="gap")], {"accountable": "unknown"}, ["accountable"]))
        self.assertEqual(result["topics"]["accountable"], {"status": "partial", "discussed": True, "participant_unavailable": True})
        self.assertEqual(result["topics"]["risk"]["discussed"], False)
        self.assertFalse(result["topics"]["risk"]["participant_unavailable"])

    def test_blanket_document_caveat_cannot_mark_all_topics_unavailable(self):
        self.turns.append({"id": "u_global", "role": "user", "text": "I cannot confirm whether this procedure reflects current practice."})
        state = facts.empty_state()
        changes = [operation(key, "The participant cannot confirm this topic's current practice.", "u_global", kind="gap") for key in facts.TOPICS]
        result = self.apply(state, transaction(state, changes, {key: "partial" for key in facts.TOPICS}, facts.TOPICS))
        self.assertFalse(all(item["participant_unavailable"] for item in result["topics"].values()))
        self.assertFalse(result["topics"]["accountable"]["participant_unavailable"])

    def test_model_absence_note_does_not_make_an_unasked_risk_topic_discussed(self):
        state = facts.empty_state()
        result = self.apply(state, transaction(state, [operation("risk", "Failure consequences have not been described.", kind="gap")],
                                              {"risk": "partial"}))
        self.assertFalse(result["topics"]["risk"]["discussed"])
        self.assertFalse(result["topics"]["risk"]["participant_unavailable"])
        self.assertEqual(result["topics"]["risk"]["status"], "partial")

    def test_local_answer_marks_actual_topic_discussed_without_claiming_unavailable(self):
        self.turns += [{"id": "a_risk", "role": "assistant", "text": "Has this failure occurred before?"},
                       {"id": "u_no", "role": "user", "text": "No."}]
        state = facts.empty_state()
        result = self.apply(state, transaction(state, [operation("risk", "The consequences of failure still need clarification.", "u_no", kind="gap")],
                                              {"risk": "partial"}, ["risk"]))
        self.assertTrue(result["topics"]["risk"]["discussed"])
        self.assertFalse(result["topics"]["risk"]["participant_unavailable"])

    def test_source_stated_owner_gap_is_considered_but_not_participant_unavailability(self):
        self.documents = [{"id": "doc_owner", "text": "The overall process owner is unconfirmed."}]
        state = facts.empty_state()
        result = self.apply(state, transaction(state, [operation("accountable", "The procedure leaves the owner unconfirmed.", "doc_owner", kind="gap")],
                                              {"accountable": "partial"}, ["accountable"]))
        self.assertTrue(result["topics"]["accountable"]["discussed"])
        self.assertFalse(result["topics"]["accountable"]["participant_unavailable"])

    def test_document_only_detail_still_cannot_pass_existing_practice_gate(self):
        self.documents = [{"id": "doc_rule", "text": "The controller approves."}]
        state = facts.empty_state()
        result = self.apply(state, transaction(state, [operation("checks", "The procedure names the controller as approver.", "doc_rule")],
                                              {"checks": "captured"}))
        findings = facts.findings(result)
        server.validate_findings(findings, self.turns, self.documents)
        self.assertEqual(next(item["status"] for item in findings if item["key"] == "checks"), "partial")

    def test_no_provider_legacy_answer_fallback_and_no_metadata_only_capture(self):
        state = facts.empty_state()
        result = self.apply(state, transaction(state, statuses={key: "captured" for key in facts.TOPICS}))
        self.assertTrue(all(item["status"] == "unknown" for item in facts.findings(result)))
        with self.assertRaises(ValueError):
            server.check_schema({"memo_findings": []}, facts.FACT_DELTA_SCHEMA)

    def test_provider_schema_binds_opaque_revision_targets_and_small_source_catalog(self):
        state = self.seeded()
        schema = facts.schema_for(state, ["u1", "context"])
        self.assertEqual(schema["properties"]["base_revision"]["enum"], [state["revision"]])
        branches = schema["properties"]["fact_operations"]["items"]["anyOf"]
        operation_schema = branches[0]["properties"]
        self.assertEqual({target for branch in branches for target in branch["properties"]["target_id"]["enum"]},
                         {""} | {fact["id"] for fact in state["facts"]})
        self.assertEqual(operation_schema["evidence_turns"]["items"]["enum"], ["context", "u1"])
        self.assertNotIn("enum", schema["properties"]["question"])
        self.assertNotIn("enum", facts.FACT_DELTA_SCHEMA["properties"]["base_revision"])
        delta = transaction(state)
        delta["base_revision"] = state["revision"][:-5]
        with self.assertRaises(ValueError):
            server.check_schema(delta, schema)
        large = facts.schema_for(state, ["doc_" + str(i) for i in range(201)])
        self.assertNotIn("enum", large["properties"]["fact_operations"]["items"]["anyOf"][0]["properties"]["evidence_turns"]["items"])

    def test_provider_branches_forbid_resolving_detail_and_permit_real_gap_resolution(self):
        state = self.seeded()
        state = self.apply(state, transaction(state, [operation("accountable", "The accountable owner is unknown.", kind="gap")],
                                              {"accountable": "partial"}))
        detail = next(fact for fact in state["facts"] if fact["kind"] == "detail")
        gap = next(fact for fact in state["facts"] if fact["kind"] == "gap")
        schema = facts.schema_for(state, ["u1", "context"])
        invalid = transaction(state, [operation(detail["topic"], "A revised fact.", op="replace",
            target=detail["id"], reason="resolved_gap")])
        with self.assertRaises(ValueError):
            server.check_schema(invalid, schema)
        valid = transaction(state, [operation(gap["topic"], "The controller owns the result.", op="replace",
            target=gap["id"], reason="resolved_gap")])
        server.check_schema(valid, schema)
        invalid_add = transaction(state, [operation("checks", "A new rule.", target=detail["id"])])
        with self.assertRaises(ValueError):
            server.check_schema(invalid_add, schema)

    def test_identical_additions_do_not_expand_state_and_bounds_fail_without_truncation(self):
        state = self.seeded()
        change = operation("completion", "Completion requires an approved, locked package.")
        result = self.apply(state, transaction(state, [change]))
        self.assertEqual(len(result["facts"]), len(state["facts"]))
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            self.apply(state, transaction(state, [operation("risk", "x" * (facts.MAX_FACT_TEXT + 1))]))
        self.assertEqual(state, before)

    def test_explicit_legacy_migration_keeps_retired_document_only_as_provenance(self):
        capture = {"memo_findings": [{"key": "checks", "status": "partial",
                   "answer": "The old procedure names a reviewer.", "evidence_turns": ["doc_old"]}]}
        documents = [{"id": "doc_old", "text": "Reviewer approves.", "retained_only": True}]
        state = facts.seed_legacy(capture, self.context, self.turns, documents)
        self.assertEqual(state["facts"][0]["state"], "retired_source")
        self.assertEqual(state["facts"][0]["origin"], "legacy_aid")
        self.assertEqual(facts.model_state(state)["facts"], [])
        self.assertEqual(next(item["status"] for item in facts.findings(state) if item["key"] == "checks"), "unknown")

    def test_explicit_review_repair_preserves_not_applicable_basis_on_later_turn(self):
        state = facts.empty_state()
        self.turns.append({"id": "u_na", "role": "user", "text": "No client or fund differences apply because this is our only fund and route."})
        answer = self.turns[-1]["text"]
        state = self.apply(state, transaction(state, [operation("variations", answer, "u_na", kind="not_applicable")],
                                              {"variations": "not_applicable"}))
        capture = {"memo_findings": facts.findings(state), "coverage_assessment": {
            "capture_repairs": [{"key": "variations", "answer": answer, "evidence_turns": ["u_na"]}]}}
        reviewed = facts.sync_review(state, capture, self.context, self.turns, [])
        after = self.apply(reviewed, transaction(reviewed))
        self.assertEqual(next(item["status"] for item in facts.findings(after) if item["key"] == "variations"), "not_applicable")
        self.assertTrue(any(fact["kind"] == "not_applicable" and fact["origin"] == "coverage_repair"
                            for fact in facts.model_state(after)["facts"]))


class FactCoordinatorTests(unittest.TestCase):
    def test_long_eleven_turn_seed_has_larger_bound_but_next_delta_stays_small(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        for turn in payload["turns"]:
            turn["text"] += " The participant supplied additional process detail." * 15
        self.assertEqual(len(payload["turns"]), 11)
        self.assertGreater(sum(len(turn["text"]) for turn in payload["turns"]), 6000)
        seen = []
        def response(model_input):
            seen.append(model_input)
            changes = [operation("completion", "Treasury acceptance finishes the AP work.", "u_completion")] if len(seen) == 1 else []
            return from_model_input(model_input, changes, {"completion": "partial"})
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        client.coordinator.interview(reply_payload(payload, first, "There is another detail."))
        bodies = [call.args[1] for call in client.request.call_args_list]
        self.assertEqual([body["max_output_tokens"] for body in bodies], [12000, 6500])
        self.assertEqual(client.request.call_count, 2)

    def test_model_routing_keeps_one_call_and_records_actual_selected_role_model(self):
        for with_document in (False, True):
            with self.subTest(with_document=with_document):
                client = SyntheticTeamProvider()
                client.incomplete()
                client.agent_models.update(lead_interviewer="configured-fast-lead", document_analyst="configured-baseline-model")
                payload = client.payload()
                if with_document:
                    payload["_supporting_documents"] = {"documents": [{"id": "source1", "name": "Procedure", "review": {"phase": "complete"},
                        "excerpts": [{"id": "doc_rule", "text": "The analyst checks the invoice."}]}]}
                first = client.coordinator.interview(payload)
                expected = "configured-baseline-model" if with_document else "configured-fast-lead"
                self.assertEqual(client.request.call_args.args[1]["model"], expected)
                self.assertEqual(next(row["model"] for row in first["agent_team"]["agents"] if row["role"] == "lead_interviewer"), expected)
                self.assertEqual(client.request.call_count, 1)
                self.assertEqual(len(first["agent_team"]["agents"]), 3, "Baseline routing does not invoke a separate document agent")
                second = client.coordinator.interview(reply_payload(payload, first, "A missed duplicate delays payment."))
                self.assertEqual(client.request.call_args.args[1]["model"], "configured-fast-lead")
                self.assertEqual(next(row["model"] for row in second["agent_team"]["agents"] if row["role"] == "lead_interviewer"), "configured-fast-lead")
                self.assertEqual(client.request.call_count, 2)

    def test_new_or_changed_document_baseline_uses_configured_document_model(self):
        for mutation in ("new", "changed"):
            with self.subTest(mutation=mutation):
                client = SyntheticTeamProvider()
                client.incomplete()
                payload = client.payload()
                payload["_supporting_documents"] = {"documents": [{"id": "source1", "name": "Procedure", "review": {"phase": "complete"},
                    "excerpts": [{"id": "doc_rule", "text": "The analyst checks the invoice."}]}]}
                first = client.coordinator.interview(payload)
                follow = reply_payload(payload, first, "The source was updated.")
                if mutation == "new":
                    follow["_supporting_documents"]["documents"].append({"id": "source2", "name": "Additional procedure",
                        "review": {"phase": "complete"}, "excerpts": [{"id": "doc_second", "text": "The manager signs the record."}]})
                else:
                    follow["_supporting_documents"]["documents"][0]["excerpts"][0]["text"] = "The controller checks the invoice."
                client.coordinator.interview(follow)
                self.assertEqual([call.args[1]["model"] for call in client.request.call_args_list], ["synthetic-document"] * 2)

    def test_query_selection_changes_with_stable_document_revision_keep_fast_delta(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        payload = client.payload()
        payload["_supporting_documents"] = {"source_versions": [{"id": "source1", "source_revision": "a" * 64}],
            "documents": [{"id": "source1", "name": "Procedure", "source_revision": "a" * 64,
                "review": {"phase": "complete"}, "excerpts": [{"id": "doc_first", "text": "First selected passage."}]}]}
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "Consider a different part of the same procedure.")
        follow["_supporting_documents"]["documents"][0]["excerpts"] = [{"id": "doc_other", "text": "Another passage from the same immutable file."}]
        result = client.coordinator.interview(follow)
        self.assertEqual([call.args[1]["model"] for call in client.request.call_args_list], ["synthetic-document", "synthetic-lead"])
        self.assertEqual(client.request.call_args.args[1]["max_output_tokens"], 6500)
        self.assertFalse(result["completion"]["complete"])

    def test_seed_versions_survive_unselected_active_files_but_changed_version_reseeds(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        payload = client.payload()
        docs = [{"id": "source1", "name": "First", "source_revision": "a" * 64, "review": {"phase": "complete"},
                 "excerpts": [{"id": "doc_first", "text": "First source."}]},
                {"id": "source2", "name": "Second", "source_revision": "b" * 64, "review": {"phase": "complete"},
                 "excerpts": [{"id": "doc_second", "text": "Second source."}]}]
        versions = [{"id": doc["id"], "source_revision": doc["source_revision"]} for doc in docs]
        payload["_supporting_documents"] = {"source_versions": versions, "documents": [docs[0]]}
        first = client.coordinator.interview(payload)
        second_payload = reply_payload(payload, first, "Consider the second procedure.")
        second_payload["turns"][-2]["id"], second_payload["turns"][-1]["id"] = "a_second_source", "u_second_source"
        second_payload["_supporting_documents"]["documents"] = [docs[1]]
        second = client.coordinator.interview(second_payload)
        third_payload = reply_payload(second_payload, second, "Return to the first procedure.")
        third_payload["turns"][-2]["id"], third_payload["turns"][-1]["id"] = "a_return_source", "u_return_source"
        third_payload["_supporting_documents"]["documents"] = [docs[0]]
        third = client.coordinator.interview(third_payload)
        self.assertEqual([call.args[1]["model"] for call in client.request.call_args_list],
                         ["synthetic-document", "synthetic-document", "synthetic-lead"])
        state = client.coordinator._captures[third["capture_token"]]["fact_state"]
        self.assertEqual(state["seeded_document_versions"], {"source1": "a" * 64, "source2": "b" * 64})
        fourth_payload = reply_payload(third_payload, third, "The first source has an actual revised version.")
        fourth_payload["_supporting_documents"]["source_versions"][0]["source_revision"] = "c" * 64
        fourth_payload["_supporting_documents"]["documents"][0]["source_revision"] = "c" * 64
        client.coordinator.interview(fourth_payload)
        self.assertEqual(client.request.call_args.args[1]["model"], "synthetic-document")

    def test_large_history_seed_uses_baseline_model_and_final_confirmation_still_zero_calls(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        for turn in payload["turns"]:
            turn["text"] += " This test turn restates the same supplied process account." * 15
        payload, pending = prepared_review(client, payload)
        self.assertEqual(client.request.call_args_list[0].args[1]["model"], "synthetic-document")
        result = client.coordinator.review(payload)
        count = client.request.call_count
        completed = client.coordinator.interview(reply_payload(payload, result, "No, nothing else. This captures my account."))
        self.assertTrue(completed["completion"]["complete"])
        self.assertEqual(client.request.call_count, count)
        self.assertEqual(next(row["model"] for row in completed["agent_team"]["agents"] if row["role"] == "lead_interviewer"), "synthetic-document")

    def test_failed_ordinary_call_retry_retains_published_facts_but_not_review_authority(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        seen = []
        def response(model_input):
            seen.append(model_input)
            if len(seen) == 1:
                return from_model_input(model_input, [operation("completion", "Treasury acceptance finishes the AP work.", "u_completion")],
                                        {"completion": "partial"})
            if len(seen) == 2:
                raise server.APIError("Synthetic provider failure")
            return from_model_input(model_input)
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "There is another detail to discuss.")
        with self.assertRaises(server.APIError):
            client.coordinator.interview(follow)
        retry = client.coordinator.interview(follow)
        self.assertIn("Treasury acceptance", next(item["answer"] for item in retry["memo_findings"] if item["key"] == "completion"))
        self.assertEqual(seen[1]["fact_state"]["facts"], seen[2]["fact_state"]["facts"])
        self.assertEqual(client.request.call_count, 3)
        self.assertFalse(retry["coverage_verified"])
        self.assertFalse(retry["completion"]["complete"])

    def test_cancelled_review_can_reuse_facts_only_in_a_new_unverified_call(self):
        client = SyntheticTeamProvider()
        payload, pending = prepared_review(client)
        reviewed = client.coordinator.review(payload)
        client.coordinator.cancel(reviewed["agent_run_id"])
        seen = []
        def response(model_input):
            seen.append(model_input)
            return from_model_input(model_input)
        typed_responder(client, response)
        result = client.coordinator.interview(reply_payload(payload, reviewed, "No, nothing else to add."))
        self.assertTrue(seen[0]["fact_state"]["facts"])
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(result["speech_authorization"]["kind"], "review_pending")
        self.assertFalse(result["coverage_verified"])
        self.assertFalse(result["completion"]["complete"])

    def test_edited_history_cannot_reuse_cancelled_or_stale_fact_state(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        payload = client.payload()
        first = client.coordinator.interview(payload)
        client.coordinator.cancel(first["agent_run_id"])
        follow = reply_payload(payload, first, "Continue.")
        follow["turns"][0]["text"] = "This is a different process account."
        seen = []
        typed_responder(client, lambda model_input: (seen.append(model_input) or from_model_input(model_input)))
        result = client.coordinator.interview(follow)
        self.assertEqual(seen[0]["fact_state"]["facts"], [])
        self.assertFalse(result["completion"]["complete"])

    def test_pre_ledger_private_capture_rebuilds_from_full_sources_not_derived_prose(self):
        client = SyntheticTeamProvider()
        client.incomplete()
        payload = client.payload()
        first = client.coordinator.interview(payload)
        private = client.coordinator._captures[first["capture_token"]]
        private.pop("fact_state")
        private["capture"]["memo_findings"][0]["answer"] = "A superseded derived claim must not become a fact."
        seen = []
        def response(model_input):
            seen.append(model_input)
            return from_model_input(model_input)
        typed_responder(client, response)
        follow = reply_payload(payload, first, "Please consider the full account.")
        client.coordinator.interview(follow)
        self.assertEqual(seen[0]["fact_state"]["facts"], [])
        self.assertEqual(seen[0]["turns"], follow["turns"])
        self.assertNotIn("superseded derived claim", json.dumps(seen[0]))
        self.assertEqual(client.request.call_count, 1)

    def test_existing_gap_uses_configured_reconciliation_model_in_same_single_call(self):
        client = SyntheticTeamProvider()
        client.agent_models["process_reviewer"] = "configured-reconciler"
        payload = client.payload()
        next(turn for turn in payload["turns"] if turn["id"] == "u_accountable")["text"] = "I don't know who owns the overall result."
        seen = []
        def response(model_input):
            seen.append(model_input)
            if len(seen) == 1:
                return from_model_input(model_input, [operation("accountable", "The accountable owner is unknown.",
                    "u_accountable", kind="gap")], {"accountable": "partial"})
            if len(seen) == 2:
                target = next(fact["id"] for fact in model_input["fact_state"]["facts"] if fact["kind"] == "gap")
                return from_model_input(model_input, [operation("accountable", "", "u_owner", op="remove", target=target,
                    reason="resolved_gap"), operation("accountable", "The AP manager owns the overall result.", "u_owner")],
                    {"accountable": "partial"})
            return from_model_input(model_input)
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "The AP manager owns the overall result.")
        follow["turns"][-1]["id"] = "u_owner"
        second = client.coordinator.interview(follow)
        third_payload = reply_payload(follow, second, "There is another part to explain.")
        third_payload["turns"][-2]["id"] = "a_more"
        third = client.coordinator.interview(third_payload)
        self.assertEqual([call.args[1]["model"] for call in client.request.call_args_list],
                         ["synthetic-lead", "configured-reconciler", "synthetic-lead"])
        self.assertEqual(client.request.call_count, 3)
        self.assertEqual(next(row["model"] for row in second["agent_team"]["agents"] if row["role"] == "lead_interviewer"),
                         "configured-reconciler")
        self.assertFalse(third["completion"]["complete"])

    def test_fresh_two_turn_account_preserves_conditions_with_one_call_per_turn(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        calls = []
        def response(model_input):
            calls.append(model_input)
            if len(calls) == 1:
                return from_model_input(model_input, [operation("completion", "Treasury acceptance finishes the AP work.", "u_completion"),
                    operation("checks", "The manager approves before release.", "u_checks")], {"completion": "partial", "checks": "partial"})
            return from_model_input(model_input, [operation("materials", "The closeout record is retained in AP files.", "u_reply")], {"materials": "partial"})
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        second = client.coordinator.interview(reply_payload(payload, first, "The closeout record is retained in AP files."))
        self.assertEqual(client.request.call_count, 2)
        self.assertEqual(next(item["answer"] for item in second["memo_findings"] if item["key"] == "completion"),
                         "Treasury acceptance finishes the AP work.")
        self.assertNotIn("fact_state", second)
        self.assertNotIn("fact_", json.dumps(second))
        self.assertFalse(second["completion"]["complete"])

    def test_review_repair_is_carried_into_next_single_call_without_legacy_overwrite(self):
        client = SyntheticTeamProvider()
        lifecycle = next(item for item in client.findings if item["key"] == "lifecycle")
        lifecycle["answer"] = "The analyst registers invoices and sends them to Treasury."
        topic = next(item for item in client.assessment["topics"] if item["key"] == "lifecycle")
        topic["capture_repair"] = {"needed": True}
        payload, pending = prepared_review(client)
        reviewed = client.coordinator.review(payload)
        self.assertTrue(reviewed["coverage_assessment"]["capture_repairs"])
        # Windows monotonic timestamps can tie for a fast capture and review.
        # Latest registry insertion, not a clock comparison, must select repair.
        stamp = client.coordinator._captures[reviewed["capture_token"]]["at"]
        for stored in client.coordinator._captures.values():
            stored["at"] = stamp
        seen = []
        def response(model_input):
            seen.append(model_input)
            return from_model_input(model_input)
        typed_responder(client, response)
        result = client.coordinator.interview(reply_payload(payload, reviewed, "There is more context to discuss."))
        text = next(item["answer"] for item in result["memo_findings"] if item["key"] == "lifecycle")
        self.assertIn("A held invoice returns to checking after supplier correction.", text)
        self.assertTrue(any(fact["origin"] == "coverage_repair" for fact in seen[0]["fact_state"]["facts"]))
        self.assertEqual(client.request.call_count, 1)
        self.assertFalse(result["completion"]["complete"])

    def test_changed_source_rebases_private_facts_even_when_completion_cache_is_invalid(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        support = {"documents": [{"id": "doc1", "name": "Procedure", "review": {"phase": "complete"},
                                   "excerpts": [{"id": "doc_rule", "text": "The reviewer approves."}]}]}
        payload["_supporting_documents"] = support
        seen = []
        def response(model_input):
            seen.append(model_input)
            changes = [operation("checks", "The procedure assigns approval to the reviewer.", "doc_rule")] if len(seen) == 1 else []
            return from_model_input(model_input, changes, {"checks": "partial"})
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "The procedure was corrected.")
        follow["_supporting_documents"]["documents"][0]["excerpts"][0]["text"] = "The controller approves."
        result = client.coordinator.interview(follow)
        self.assertFalse(any(fact["topic"] == "checks" for fact in seen[-1]["fact_state"]["facts"]))
        self.assertEqual(next(item["status"] for item in result["memo_findings"] if item["key"] == "checks"), "unknown")
        self.assertFalse(result["completion"]["complete"])

    def test_private_document_pins_preserve_facts_and_omission_fails_without_provider_work(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        alpha = {"id": "doc_alpha", "text": "The reviewer compares the two totals before release."}
        beta = {"id": "doc_beta", "text": "The packet is retained in the records folder."}
        payload["_supporting_documents"] = {"source_versions": [{"id": "file1", "source_revision": "a" * 64}],
            "documents": [{"id": "file1", "name": "Procedure", "source_revision": "a" * 64,
                           "review": {"phase": "complete"}, "excerpts": [alpha]}]}
        seen = []
        def response(model_input):
            seen.append(model_input)
            return from_model_input(model_input, [operation("checks", alpha["text"], "doc_alpha")] if len(seen) == 1 else [],
                                    {"checks": "partial"})
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "The next detail concerns records.")
        follow["_supporting_documents"]["documents"][0]["excerpts"] = [beta]
        self.assertEqual(client.coordinator.fact_source_ids(follow), ["doc_alpha"])
        with self.assertRaises(server.APIError) as caught:
            client.coordinator.interview(follow)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(client.request.call_count, 1)
        # The HTTP layer rehydrates the exact current authorized source ID.
        follow["_supporting_documents"]["documents"][0]["excerpts"].append(alpha)
        result = client.coordinator.interview(follow)
        self.assertEqual(next(item["answer"] for item in result["memo_findings"] if item["key"] == "checks"), alpha["text"])
        self.assertEqual(client.request.call_args.args[1]["model"], "synthetic-lead")
        # Renaming the process (the working map does this) keeps the same
        # interview's pins; only a different transcript or token loses them.
        changed = copy.deepcopy(follow)
        changed["context"]["process_name"] = "A different process"
        self.assertEqual(client.coordinator.fact_source_ids(changed), ["doc_alpha"])
        changed = copy.deepcopy(follow)
        changed["turns"][0]["text"] = "A changed account."
        self.assertEqual(client.coordinator.fact_source_ids(changed), [])
        self.assertEqual(client.coordinator.fact_source_ids({**follow, "capture_token": "forged"}), [])

    def test_omitted_document_fact_retires_when_authoritative_version_changes_or_archives(self):
        for active_versions in ([], [{"id": "file1", "source_revision": "b" * 64}]):
            with self.subTest(active_versions=active_versions):
                client = SyntheticTeamProvider()
                payload = client.payload()
                payload["_supporting_documents"] = {"source_versions": [{"id": "file1", "source_revision": "a" * 64}],
                    "documents": [{"id": "file1", "name": "Procedure", "source_revision": "a" * 64,
                        "excerpts": [{"id": "doc_alpha", "text": "The reviewer approves."}]}]}
                seen = []
                def response(model_input):
                    seen.append(model_input)
                    return from_model_input(model_input, [operation("checks", "The reviewer approves.", "doc_alpha")]
                                            if len(seen) == 1 else [], {"checks": "partial"})
                typed_responder(client, response)
                first = client.coordinator.interview(payload)
                follow = reply_payload(payload, first, "The file has changed.")
                follow["_supporting_documents"] = {"source_versions": active_versions, "documents": []}
                result = client.coordinator.interview(follow)
                self.assertFalse(seen[-1]["fact_state"]["facts"])
                self.assertEqual(next(item["status"] for item in result["memo_findings"] if item["key"] == "checks"), "unknown")

    def test_changed_document_version_retires_old_provenance_even_if_excerpt_text_is_identical(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        payload["_supporting_documents"] = {"source_versions": [{"id": "file1", "source_revision": "a" * 64}],
            "documents": [{"id": "file1", "name": "Procedure", "source_revision": "a" * 64,
                "excerpts": [{"id": "doc_alpha", "text": "The reviewer approves."}]}]}
        seen = []
        def response(model_input):
            seen.append(model_input)
            return from_model_input(model_input, [operation("checks", "The reviewer approves.", "doc_alpha")]
                                    if len(seen) == 1 else [], {"checks": "partial"})
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "The source interpretation changed.")
        follow["_supporting_documents"]["source_versions"][0]["source_revision"] = "b" * 64
        follow["_supporting_documents"]["documents"][0]["source_revision"] = "b" * 64
        result = client.coordinator.interview(follow)
        self.assertEqual(seen[-1]["fact_state"]["facts"], [])
        self.assertEqual(client.request.call_args.args[1]["model"], "synthetic-document")
        self.assertFalse(result["completion"]["complete"])


if __name__ == "__main__":
    unittest.main()
