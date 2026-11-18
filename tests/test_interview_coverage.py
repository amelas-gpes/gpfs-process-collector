"""Offline coverage contracts; model semantic judgement needs separate evaluation."""
import copy
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "coverage_contract_under_test", Path(__file__).resolve().parents[1] / "interview_coverage.py")
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


def fixture():
    """Clearly reported fictional facts, with one source per topic."""
    facts = {
        "name": "The process is invoice intake, also called AP logging by the Treasury team.",
        "purpose": "Treasury receives a registered, checked invoice ready for its separate payment process.",
        "trigger": "An invoice email in the shared AP mailbox starts a case. The AP analyst checks it each business morning; registration is due by 10 a.m.",
        "completion": "AP finishes when Treasury marks the queue entry Accepted. Treasury then handles payment separately.",
        "accountable": "The AP manager is accountable for the entire result through Treasury acceptance; the analyst performs intake.",
        "lifecycle": "The analyst logs each invoice as Received in the AP register, compares supplier and number, and marks it Checked or Hold. A duplicate is linked and closed. Other invoices go by queue link to Treasury, which records Accepted. A held invoice returns to checking after supplier correction.",
        "checks": "The analyst checks supplier and number for duplicates. The AP manager reviews the amount and records approval in the register before release. A failure stays on Hold for supplier correction and repeat checking. The analyst keeps the invoice and decision in the AP folder.",
        "variations": "Fund B requires the same AP manager to check currency before release; start and finish stay the same. The client requested it. It takes five extra minutes per invoice, our rough estimate, and we do not charge. The Fund B controller would object to removing it.",
        "pain_points": "The analyst manually copies invoice fields into the register. Corrections require another entry and chasing the supplier, delaying release until the corrected record arrives.",
        "risk": "Missing a duplicate could cause Treasury to pay twice. A late handoff can miss the supplier deadline.",
        "materials": "The AP checklist and register template are in the AP Teams files. They are available to the team, but no file has been supplied or reviewed in this interview.",
        "scope": "This enterprise AP intake subprocess serves the GPFS business. The AP manager reports the common team procedure from the written checklist, with a Fund B currency branch. Treasury payment execution is the parent lifecycle's next separate process.",
        "rules": "The AP manager interprets the AP checklist and approval matrix and records conflict resolutions in the register. The matrix governs approval; Fund B's documented client request adds the currency check. Intake performs no economic calculation; Treasury calculates payments separately.",
        "connections": "Supplier invoicing supplies the incoming invoice; Treasury payment execution consumes the checked invoice after queue acceptance. There are no embedded processes, shared calculations or parallel dependencies in this intake account.",
        "data_systems": "The AP register is the reported final record of intake. The analyst manually copies supplier invoice data; the purchasing system supplies order data. The checklist is a workpaper without calculations. Invoice and approvals live in AP Teams files. Intake does not calculate or repeat an amount.",
        "volume": "The AP manager estimates 30 invoices per normal day and 60 at month end. About one in ten needs supplier correction. Manual registration takes about two minutes per invoice; chasing corrections takes most effort. These counts and times are participant estimates.",
    }
    turns = [{"id": f"u_{key}", "role": "user", "text": fact} for key, fact in facts.items()]
    findings = [{"key": key, "status": "captured", "answer": fact, "evidence_turns": [f"u_{key}"]}
                for key, fact in facts.items()]
    # This fixture supplies a precomputed semantic assessment. These unit tests
    # exercise validation and mutation boundaries, not independent model quality.
    topics = [{"key": key, "explanation": facts[key], "evidence_turns": [f"u_{key}"],
               "dimensions": [{"key": dimension, "status": "supported", "detail": facts[key],
                               "evidence_turns": [f"u_{key}"]} for dimension in dimensions],
               "gaps": [], "next_question": "", "participant_unavailable": False,
               "unavailable_evidence_turns": [], "not_applicable_reason": "",
               "not_applicable_evidence_turns": []}
              for key, dimensions in coverage.TOPIC_DIMENSIONS.items()]
    return findings, {"topics": topics}, turns


def topic(assessment, key):
    return next(item for item in assessment["topics"] if item["key"] == key)


def held_method(topic_row):
    action = "We hold Method B until Accounting releases the schedule."
    dimension = next(row for row in topic_row["dimensions"] if row["key"] == "release_conditions")
    dimension.update(status="owner_followup", detail=action, evidence_turns=["u_hold"])
    disposition = {"dimension": "release_conditions", "kind": "operational_hold",
        "gap": "Which method and approvals permit a Method B release?", "scope": "Method B",
        "interim_action": action, "resolver": "Accounting", "evidence_turns": ["u_hold"]}
    topic_row.update(owner_followups=[disposition])
    return {"id": "u_hold", "role": "user", "text": action}


class OwnerFollowupTests(unittest.TestCase):
    def setUp(self):
        self.findings, self.assessment, self.turns = fixture()
        self.checks = topic(self.assessment, "checks")
        self.turns.append(held_method(self.checks))
        next(f for f in self.findings if f["key"] == "checks").update(status="partial")

    def result(self, documents=None):
        _, result = coverage.apply_assessment(self.findings, self.assessment, self.turns, documents)
        return result

    def test_hold_is_ready_for_review_with_the_dimension_still_open(self):
        result = self.result()
        self.assertTrue(result["all_topics_ready_for_owner_review"])
        self.assertFalse(result["all_topics_covered"])
        self.assertEqual(topic(result, "checks")["owner_followups"], self.checks["owner_followups"])

    def test_answerable_blocker_alongside_a_handoff_keeps_the_interview_open(self):
        self.checks["gaps"].append("What evidence is kept for normal releases?")
        self.checks["next_question"] = self.checks["gaps"][0]
        result = topic(self.result(), "checks")
        self.assertFalse(result["ready_for_owner_review"])
        self.assertTrue(result["owner_followups"])

    def test_invalid_dispositions_and_generic_referrals_cannot_clear_a_release(self):
        original = self.checks["owner_followups"][0]
        for change in ({"interim_action": "We release on Friday."}, {"resolver": "Legal"},
                       {"scope": "TBD"}, {"kind": "context_detail"}, {"evidence_turns": ["document_hold"]},
                       {"interim_action": "Ask Accounting about that."}):
            with self.subTest(change=change):
                self.turns[-1]["text"] += " Ask Accounting about that."
                self.checks["owner_followups"] = [dict(original, **change)]
                result = topic(self.result([{"id": "document_hold"}]), "checks")
                self.assertFalse(result["ready_for_owner_review"])
                self.assertFalse(result["owner_followups"])
                self.assertTrue(result["gaps"])

    def test_a_known_external_handoff_and_nonmaterial_estimate_can_be_referred(self):
        for key, dimension, kind, words in (
                ("completion", "downstream_consumer", "external_handoff", "We deliver the reconciled ledger to Tax for its separate return."),
                ("volume", "counts", "context_detail", "We use the same review at every volume. The operations register keeps counts.")):
            with self.subTest(key=key):
                row = topic(self.assessment, key)
                next(d for d in row["dimensions"] if d["key"] == dimension).update(
                    status="owner_followup", detail=words, evidence_turns=["u_extra"])
                row["owner_followups"] = [{"dimension": dimension, "kind": kind, "gap": "Confirm the downstream detail.",
                    "scope": "reconciled ledger" if key == "completion" else "every volume",
                    "interim_action": words.split(". ")[0], "resolver": "Tax" if key == "completion" else "operations register",
                    "evidence_turns": ["u_extra"]}]
                self.turns.append({"id":"u_extra", "role":"user", "text":words})
                self.assertTrue(topic(self.result(), key)["ready_for_owner_review"])
                self.turns.pop()

    def test_a_hedged_or_negated_holding_sentence_does_not_establish_a_hold(self):
        row = self.checks["owner_followups"][0]
        for testimony, action in (
                ("I don't know whether Accounting holds Method B.", "Accounting holds Method B."),
                ("We never hold Method B for Accounting.", "We never hold Method B for Accounting."),
                ("I think Accounting holds Method B.", "I think Accounting holds Method B."),
                ("We hold Method B. I don't know whether Accounting owns the rule.", "We hold Method B.")):
            with self.subTest(testimony=testimony):
                self.turns[-1]["text"] = testimony
                row["interim_action"] = action
                self.assertFalse(topic(self.result(), "checks")["ready_for_owner_review"])
        row["interim_action"] = "Method B stays on hold until Accounting signs off"
        self.turns[-1]["text"] = "I don't know the formula, so Method B stays on hold until Accounting signs off."
        self.assertTrue(topic(self.result(), "checks")["ready_for_owner_review"])

    def test_a_rule_can_hold_release_or_explicitly_allow_it_until_a_change(self):
        row = self.checks["owner_followups"][0]
        for words, allowed in (
                ("We continue to release Method B until Accounting issues new instructions.", False),
                ("We do not change the Method B release date unless Accounting requests it.", False),
                ("We don't release Method B until Accounting issues instructions.", True),
                ("Accounting must clear Method B before release.", True)):
            with self.subTest(words=words):
                self.turns[-1]["text"] = words
                row["interim_action"] = words
                self.assertEqual(topic(self.result(), "checks")["ready_for_owner_review"], allowed)

    def test_accepted_exception_requires_authorized_continuation_and_owned_treatment_for_this_route(self):
        row = self.checks["owner_followups"][0]
        row.update(kind="accepted_exception", scope="Fund A", resolver="Treasury",
                   gap="Confirm the exception's resolution.")
        for words, scope, allowed in (
                ("For Fund A we may close with the exception logged open and assigned to Treasury.", "Fund A", True),
                ("For Fund A the exception is logged open and assigned to Treasury.", "Fund A", False),
                ("For Fund A we may close with an open exception in the Treasury log.", "Fund A", False),
                ("For Fund A we cannot close with an open exception assigned to Treasury.", "Fund A", False),
                ("For Fund A we may close with the exception logged open and assigned to Treasury.", "Fund B", False)):
            with self.subTest(words=words, scope=scope):
                self.turns[-1]["text"] = words + " Fund B follows separate instructions."
                row.update(interim_action=words, scope=scope)
                self.assertEqual(topic(self.result(), "checks")["ready_for_owner_review"], allowed)

    def test_adjacent_participant_sentences_can_supply_route_treatment_and_resolver(self):
        row = self.checks["owner_followups"][0]
        for kind, first, second, resolver in (
                ("operational_hold", "We use Method B for Fund A.", "Release waits for the schedule. Treasury owns the decision.", "Treasury"),
                ("accepted_exception", "For Fund A we may proceed with an open exception.",
                 "We log it and escalate it to Treasury.", "Treasury")):
            with self.subTest(kind=kind):
                self.turns[-1]["text"] = first
                self.turns.append({"id": "u_handling", "role": "user", "text": second})
                row.update(kind=kind, scope="Fund A", interim_action=first + " " + second, resolver=resolver,
                           evidence_turns=["u_hold", "u_handling"])
                self.assertTrue(topic(self.result(), "checks")["ready_for_owner_review"])
                self.turns.insert(-1, {"id":"u_correction", "role":"user", "text":"That treatment is being corrected."})
                self.assertFalse(topic(self.result(), "checks")["ready_for_owner_review"])
                self.turns.pop(-2)
                self.turns.pop()
        words = "Fund A remains held. For Fund B we may proceed with the open exception assigned to Treasury."
        self.turns[-1]["text"] = words
        row.update(kind="accepted_exception", scope="Fund A", interim_action=words, evidence_turns=["u_hold"])
        self.assertFalse(topic(self.result(), "checks")["ready_for_owner_review"])

    def test_changing_disposition_cannot_use_a_different_clients_evidence(self):
        row = topic(self.assessment, "volume")
        next(d for d in row["dimensions"] if d["key"] == "counts").update(
            status="owner_followup", detail="Treasury supplies the counts.", evidence_turns=["u_routes"])
        action = "We send the Fund B file to Treasury to get the counts."
        self.turns.append({"id":"u_routes", "role":"user", "text":"Fund A has different instructions. " + action})
        for kind in ("operational_hold", "accepted_exception", "external_handoff", "context_detail"):
            with self.subTest(kind=kind):
                row["owner_followups"] = [{"dimension":"counts", "kind":kind, "scope":"Fund A", "gap":"Who confirms the count?",
                    "interim_action":action, "resolver":"Treasury", "evidence_turns":["u_routes"]}]
                self.assertFalse(topic(self.result(), "volume")["ready_for_owner_review"])


class GroupedAssessmentTests(unittest.TestCase):
    """The completion review runs topic groups concurrently; validation stays whole-account."""

    def test_groups_cover_every_topic_exactly_once(self):
        keys = [key for group in coverage.COVERAGE_REVIEW_GROUPS for key in group]
        self.assertEqual(sorted(keys), sorted(coverage.TOPIC_DIMENSIONS))
        self.assertEqual(len(keys), len(set(keys)))

    def test_group_schema_and_instructions_are_limited_to_the_group(self):
        schema = coverage.group_schema(("purpose", "name"))
        topics = schema["properties"]["topics"]
        self.assertEqual(topics["items"]["properties"]["key"]["enum"], ["name", "purpose"])
        self.assertEqual((topics["minItems"], topics["maxItems"]), (2, 2))
        self.assertIn("capture_repair", coverage.group_schema(("name",), repair=True)["properties"]["topics"]["items"]["properties"])
        with self.assertRaises(ValueError):
            coverage.group_schema(("unknown",))
        instructions = coverage.group_instructions(("name", "purpose"))
        self.assertIn("ASSESS ONLY THESE TOPICS, EACH EXACTLY ONCE, IN THIS ORDER: name, purpose", instructions)
        self.assertIn("name: everyday_name", instructions)
        self.assertNotIn("lifecycle: items_and_stages", instructions)
        self.assertEqual(coverage.group_instructions(tuple(coverage.TOPIC_DIMENSIONS)), coverage.AUDIT_INSTRUCTIONS)
        self.assertIn("EXPLICIT CAPTURE REPAIR RULES", coverage.group_instructions(("risk",), repair=True))

    def test_merge_requires_every_requested_topic_once_and_nothing_else(self):
        _, assessment, _ = fixture()
        by_key = {item["key"]: item for item in assessment["topics"]}
        groups = coverage.COVERAGE_REVIEW_GROUPS
        parts = [(group, {"topics": [by_key[key] for key in reversed(group)]}) for group in groups]
        merged = coverage.merge_group_assessments(parts)
        self.assertEqual([item["key"] for item in merged["topics"]], list(coverage.TOPIC_DIMENSIONS))
        with self.assertRaises(ValueError):
            coverage.merge_group_assessments([(groups[0], {"topics": [by_key[key] for key in groups[0][:-1]]})])
        with self.assertRaises(ValueError):
            coverage.merge_group_assessments([(groups[0], {"topics": [by_key[key] for key in groups[0]] + [by_key["risk"]]})])
        with self.assertRaises(ValueError):
            coverage.merge_group_assessments([(groups[0], {"topics": [by_key[groups[0][0]]] * len(groups[0])})])

    def test_subset_assessment_describes_only_the_requested_topics(self):
        findings, assessment, turns = fixture()
        risk = topic(assessment, "risk")
        with self.assertRaises(ValueError):
            coverage.apply_assessment(findings, {"topics": [risk]}, turns)
        revised, public = coverage.apply_assessment(findings, {"topics": [risk]}, turns, required_keys=["risk"])
        self.assertEqual([item["key"] for item in public["topics"]], ["risk"])
        self.assertTrue(public["all_topics_covered"])
        self.assertEqual(revised, findings)
        with self.assertRaises(ValueError):
            coverage.apply_assessment(findings, {"topics": [risk]}, turns, required_keys=["risk", "name"])
        with self.assertRaises(ValueError):
            coverage.apply_assessment(findings, {"topics": [risk]}, turns, required_keys=["unknown"])


class CoverageAssessmentTests(unittest.TestCase):
    def repair_fixture(self, status="captured"):
        findings, assessment, turns = fixture()
        for item in assessment["topics"]:
            item["capture_repair"] = {"needed": False}
        finding = next(item for item in findings if item["key"] == "lifecycle")
        finding.update(status=status, answer="The analyst registers and sends invoices to Treasury.")
        local = topic(assessment, "lifecycle")
        local["capture_repair"] = {"needed": True}
        return findings, assessment, turns

    def test_explicit_repair_fills_reported_omission_and_records_authority(self):
        findings, assessment, turns = self.repair_fixture()
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        actual = next(item for item in revised if item["key"] == "lifecycle")
        self.assertEqual(actual["answer"], topic(assessment, "lifecycle")["explanation"])
        self.assertEqual(actual["status"], "captured")
        # The published repair also records the answer and citations it replaced.
        self.assertEqual(public["capture_repairs"], [{"key": "lifecycle", "answer": actual["answer"], "evidence_turns": actual["evidence_turns"],
                                                      "previous_answer": "The analyst registers and sends invoices to Treasury.",
                                                      "previous_evidence_turns": ["u_lifecycle"]}])
        self.assertTrue(public["all_topics_covered"])
        self.assertEqual(findings[5]["answer"], "The analyst registers and sends invoices to Treasury.")

    def test_canonical_repair_uses_one_explanation_and_union_of_validated_dimension_sources(self):
        findings, assessment, turns = self.repair_fixture()
        turns.append({"id": "u_rework", "role": "user", "text": "The held invoice returns to checking after supplier correction."})
        local = topic(assessment, "lifecycle")
        local["dimensions"][-1]["evidence_turns"] = ["u_rework"]
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        repaired = next(item for item in revised if item["key"] == "lifecycle")
        self.assertEqual(repaired["answer"], local["explanation"])
        self.assertEqual(repaired["evidence_turns"], ["u_lifecycle", "u_rework"])
        self.assertEqual(public["capture_repairs"][0]["evidence_turns"], repaired["evidence_turns"])
        self.assertEqual(set(coverage.CAPTURE_REPAIR_SCHEMA["properties"]), {"needed","edits"})

    def test_malformed_duplicate_repair_prose_is_not_converted_into_participant_gap(self):
        findings, assessment, turns = self.repair_fixture()
        topic(assessment, "lifecycle")["capture_repair"]["answer"] = "A different unsupported copy."
        original = copy.deepcopy(findings)
        with self.assertRaises(ValueError):
            coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual(findings, original)

    def test_repair_cannot_promote_unknown_or_partial(self):
        for status in ("unknown", "partial"):
            findings, assessment, turns = self.repair_fixture(status)
            revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
            self.assertEqual(revised[5], findings[5])
            self.assertFalse(public["capture_repairs"])
            self.assertFalse(topic(public, "lifecycle")["complete"])

    def test_unsupported_actor_or_missing_testimony_remains_a_gap(self):
        for gap in ("The proposed duty manager is not reported by the participant.", "The participant has not explained the return route."):
            findings, assessment, turns = self.repair_fixture()
            topic(assessment, "lifecycle")["gaps"] = [gap]
            revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
            self.assertEqual(revised[5]["answer"], findings[5]["answer"])
            self.assertEqual(revised[5]["status"], "partial")
            self.assertFalse(public["capture_repairs"])

    def test_uncertain_dimension_or_repair_cannot_be_declared_supported(self):
        for target in ("dimension", "answer"):
            findings, assessment, turns = self.repair_fixture()
            local = topic(assessment, "lifecycle")
            if target == "dimension":
                local["dimensions"][0]["detail"] = "The final release actor is unknown."
            else:
                local["explanation"] = "The final release actor is unknown."
            revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
            self.assertEqual(revised[5]["status"], "partial")
            self.assertFalse(public["capture_repairs"])

    def test_forged_assistant_and_document_only_repair_references_are_rejected(self):
        for source in ("invented", "a1", "doc_policy"):
            findings, assessment, turns = self.repair_fixture()
            turns.append({"id": "a1", "role": "assistant", "text": "The manager may release it."})
            topic(assessment, "lifecycle")["evidence_turns"] = [source]
            if source == "doc_policy":
                revised, public = coverage.apply_repair_assessment(findings, assessment, turns, [{"id": source}])
                self.assertFalse(public["capture_repairs"])
                self.assertEqual(revised[5]["status"], "partial")
                continue
            with self.assertRaises(ValueError):
                coverage.apply_repair_assessment(findings, assessment, turns, [{"id": "doc_policy"}])

    def test_reported_unavailable_actor_with_explicit_backup_is_not_unknown_knowledge(self):
        findings, assessment, turns = self.repair_fixture()
        fact = "If the analyst is unavailable, the AP manager appoints a backup analyst for the same steps."
        turns.append({"id": "u_backup", "role": "user", "text": fact})
        local = topic(assessment, "lifecycle")
        local["explanation"] += " " + fact
        local["evidence_turns"].append("u_backup")
        local["dimensions"][-1]["detail"] += " " + fact
        local["dimensions"][-1]["evidence_turns"].append("u_backup")
        local["capture_repair"] = {"needed": True}
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertTrue(topic(public, "lifecycle")["complete"])
        self.assertEqual(len(public["capture_repairs"]), 1)

    def test_empty_or_generic_explanation_cannot_be_repaired_complete(self):
        for answer in ("", "UNKNOWN", "Yes"):
            findings, assessment, turns = self.repair_fixture()
            local = topic(assessment, "lifecycle")
            local["explanation"] = answer
            revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
            self.assertFalse(public["capture_repairs"])
            self.assertEqual(revised[5]["status"], "partial")

    def test_repair_policy_includes_rules_for_omissions_and_missing_testimony(self):
        self.assertIn("do not silently repair", coverage.AUDIT_INSTRUCTIONS)
        self.assertNotIn("do not silently repair", coverage.REPAIR_AUDIT_INSTRUCTIONS)
        self.assertIn("Unsupported substitutions and missing testimony remain gaps", coverage.REPAIR_AUDIT_INSTRUCTIONS)

    def test_rejected_unknown_counterclaim_does_not_manufacture_a_variation_gap(self):
        findings, assessment, turns = fixture()
        local = topic(assessment, "variations")
        reason = "There are no variations: every packet uses the same source, route, deadlines and finish."
        detail = ("There is no variation being assessed for charging. The participant explicitly distinguishes "
                  "this from saying that a particular difference is free or that billing is unknown.")
        turns.append({"id": "u_no_variations", "role": "user", "text": reason})
        local.update(explanation=reason, evidence_turns=["u_no_variations"])
        for dimension in local["dimensions"]:
            dimension.update(status="not_applicable", detail=reason, evidence_turns=["u_no_variations"])
        local["dimensions"][4]["detail"] = detail
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertTrue(topic(public, "variations")["complete"])
        self.assertEqual(topic(public, "variations")["gaps"], [])
        detail = ("There is no variation being assessed for charging because the participant reports no variations. "
                  "The participant explicitly does not claim that a particular difference is free or that billing is unknown.")
        local["dimensions"][4]["detail"] = detail
        _, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertTrue(topic(public, "variations")["complete"])
        local["dimensions"][4]["detail"] = ("The participant explicitly clarifies that there is no difference being assessed, "
                                           "rather than claiming that a difference is free or that billing is unknown.")
        _, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertTrue(topic(public, "variations")["complete"])
        for uncertainty in ("Billing is unknown.", "The owner is unknown.",
                            detail + " But the accountable owner is unknown.",
                            "The participant explicitly does not claim billing is known; billing is unknown.",
                            "The participant does not claim billing is known, but billing is unknown.",
                            "The participant distinguishes this from saying billing is unknown, but the owner is unknown.",
                            'The participant said "billing is unknown".'):
            with self.subTest(uncertainty=uncertainty):
                self.assertTrue(coverage.repair_has_uncertainty(uncertainty))

    def test_explicit_repair_removes_only_ai_added_condition_extension(self):
        findings, assessment, turns = self.repair_fixture()
        local = topic(assessment, "risk")
        reported = ("Late packets delay the briefing and require individual calls. Unreadable packets "
                    "delay the briefing until a working copy is available.")
        next(item for item in turns if item["id"] == "u_risk")["text"] = reported
        finding = next(item for item in findings if item["key"] == "risk")
        finding["answer"] = "Late or unreadable packets delay the briefing and require individual calls."
        local["explanation"] = reported
        local["dimensions"][0]["detail"] = reported
        local["capture_repair"] = {"needed": True}
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual(next(item for item in revised if item["key"] == "risk")["answer"], reported)
        self.assertTrue(topic(public, "risk")["complete"])
        self.assertTrue(any(item["key"] == "risk" for item in public["capture_repairs"]))
        local["dimensions"][0]["status"] = "unresolved"
        local["gaps"] = ["The participant has not described any consequence of unreadable packets."]
        _, incomplete = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertFalse(topic(incomplete, "risk")["complete"])
        self.assertFalse(any(item["key"] == "risk" for item in incomplete["capture_repairs"]))

    def test_all_supported_dimensions_accept_original_full_findings(self):
        findings, assessment, turns = fixture()
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertEqual(revised, findings)
        self.assertTrue(public["all_topics_covered"])
        self.assertTrue(all(item["complete"] for item in public["topics"]))

    def test_shallow_action_mention_cannot_pass_a_dimension_audit(self):
        findings, assessment, turns = fixture()
        next(item for item in findings if item["key"] == "lifecycle")["answer"] = "We merge the notices."
        local = topic(assessment, "lifecycle")
        local["explanation"] = "The participant named merging notices but did not explain how the work proceeds."
        local["gaps"] = ["The proposed lifecycle finding only names the action; its operational explanation is missing."]
        local["dimensions"][1].update(status="unresolved", detail="The merging steps and decision rules were not described.")
        local["next_question"] = "How do you merge the notices?"
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        revised_local = next(item for item in revised if item["key"] == "lifecycle")
        self.assertEqual(revised_local["status"], "partial")
        self.assertEqual(revised_local["answer"], "We merge the notices.")
        self.assertFalse(public["all_topics_covered"])
        self.assertEqual(topic(public, "lifecycle")["next_question"], "How do you merge the notices?")

    def test_missing_dimensions_fail_closed_without_erasing_supported_details(self):
        findings, assessment, turns = fixture()
        topic(assessment, "trigger")["dimensions"] = [d for d in topic(assessment, "trigger")["dimensions"] if d["key"] != "deadlines"]
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertEqual(next(item for item in revised if item["key"] == "trigger")["status"], "partial")
        missing = next(item for item in topic(public, "trigger")["dimensions"] if item["key"] == "deadlines")
        self.assertEqual(missing["status"], "unresolved")
        self.assertTrue(any("deadlines" in gap for gap in topic(public, "trigger")["gaps"]))

    def test_document_only_evidence_cannot_establish_practice(self):
        findings, assessment, turns = fixture()
        local = topic(assessment, "checks")
        local["evidence_turns"] = ["doc_policy"]
        for dimension in local["dimensions"]:
            dimension["evidence_turns"] = ["doc_policy"]
        revised, public = coverage.apply_assessment(findings, assessment, turns, [{"id": "doc_policy"}])
        self.assertEqual(next(item for item in revised if item["key"] == "checks")["status"], "partial")
        self.assertFalse(topic(public, "checks")["complete"])

    def test_document_plus_context_does_not_disguise_document_only_support(self):
        findings, assessment, turns = fixture()
        local = topic(assessment, "purpose")
        local["evidence_turns"] = ["doc_policy", "context"]
        local["dimensions"][0]["evidence_turns"] = ["doc_policy", "context"]
        revised, _ = coverage.apply_assessment(findings, assessment, turns, [{"id": "doc_policy"}])
        self.assertEqual(next(item for item in revised if item["key"] == "purpose")["status"], "partial")

    def test_assistant_and_document_notifications_are_not_participant_evidence(self):
        for turn in ({"id": "bad_source", "role": "assistant", "text": "We have finished."},
                     {"id": "bad_source", "role": "user", "text": "File processed.", "document_event": True}):
            with self.subTest(turn=turn):
                findings, assessment, turns = fixture()
                turns.append(turn)
                topic(assessment, "purpose")["dimensions"][0]["evidence_turns"] = ["bad_source"]
                with self.assertRaises(ValueError):
                    coverage.apply_assessment(findings, assessment, turns)

    def test_unknown_source_is_rejected(self):
        findings, assessment, turns = fixture()
        topic(assessment, "purpose")["evidence_turns"] = ["does_not_exist"]
        with self.assertRaises(ValueError):
            coverage.apply_assessment(findings, assessment, turns)

    def test_uncertainty_is_local_to_assessed_dimension_not_whole_source_turn(self):
        findings, assessment, turns = fixture()
        next(turn for turn in turns if turn["id"] == "u_accountable")["text"] += " I don't know the exact invoice folder."
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertEqual(next(item for item in revised if item["key"] == "accountable")["status"], "captured")
        self.assertTrue(topic(public, "accountable")["complete"])

    def test_correction_reopens_affected_section_and_preserves_others(self):
        findings, assessment, turns = fixture()
        turns.append({"id": "u_correction", "role": "user", "text": "Actually, not all failed checks return to the analyst. I don't know who handles the other route."})
        local = topic(assessment, "checks")
        local["dimensions"][3].update(status="unresolved", detail="The corrected failed-check route has no established owner or return.", evidence_turns=["u_correction"])
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertEqual([item["key"] for item in revised if item["status"] == "partial"], ["checks"])
        self.assertFalse(public["all_topics_covered"])

    def test_audit_never_promotes_original_unknown_or_partial(self):
        for status in ("unknown", "partial"):
            with self.subTest(status=status):
                findings, assessment, turns = fixture()
                findings[0]["status"] = status
                revised, public = coverage.apply_assessment(findings, assessment, turns)
                self.assertEqual(revised[0]["status"], status)
                self.assertFalse(topic(public, "name")["complete"])
                self.assertFalse(public["all_topics_covered"])

    def test_not_applicable_requires_explicit_reason_and_participant_source(self):
        findings, assessment, turns = fixture()
        local_finding = next(item for item in findings if item["key"] == "variations")
        local_finding["status"] = "not_applicable"
        local = topic(assessment, "variations")
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertEqual(next(item for item in revised if item["key"] == "variations")["status"], "partial")
        self.assertFalse(topic(public, "variations")["complete"])
        reason = "The participant reports the same route, timing and output for all clients and funds, with no differences."
        turns.append({"id": "u_no_variations", "role": "user", "text": reason})
        local.update(explanation=reason, evidence_turns=["u_no_variations"], not_applicable_reason=reason,
                     not_applicable_evidence_turns=["u_no_variations"])
        for dimension in local["dimensions"]:
            dimension.update(status="not_applicable", detail=reason, evidence_turns=["u_no_variations"])
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertEqual(next(item for item in revised if item["key"] == "variations")["status"], "not_applicable")
        self.assertTrue(topic(public, "variations")["complete"])

    def test_metadata_or_yes_no_tokens_are_not_explanations(self):
        for placeholder in ("", "Yes", "UNKNOWN", "Not established", "N/A"):
            with self.subTest(placeholder=placeholder):
                findings, assessment, turns = fixture()
                topic(assessment, "purpose")["explanation"] = placeholder
                _, public = coverage.apply_assessment(findings, assessment, turns)
                self.assertFalse(topic(public, "purpose")["complete"])

    def test_unavailable_requires_an_actual_participant_statement(self):
        findings, assessment, turns = fixture()
        local = topic(assessment, "risk")
        local.update(participant_unavailable=True, unavailable_evidence_turns=["u_risk"])
        _, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertFalse(topic(public, "risk")["participant_unavailable"])
        turns.append({"id": "u_unknown", "role": "user", "text": "I don't know what other consequences this causes."})
        local.update(unavailable_evidence_turns=["u_unknown"], gaps=["Other consequences are unavailable to this participant."])
        _, public = coverage.apply_assessment(findings, assessment, turns)
        self.assertTrue(topic(public, "risk")["participant_unavailable"])
        self.assertFalse(topic(public, "risk")["complete"])

    def test_missing_duplicate_and_unknown_topics_are_rejected(self):
        for change in (lambda topics: topics.pop(), lambda topics: topics.__setitem__(1, copy.deepcopy(topics[0])),
                       lambda topics: topics[0].update(key="other")):
            findings, assessment, turns = fixture()
            change(assessment["topics"])
            with self.assertRaises(ValueError):
                coverage.apply_assessment(findings, assessment, turns)

    def test_duplicate_or_unknown_dimensions_are_rejected(self):
        for key in ("everyday_name", "made_up_dimension"):
            findings, assessment, turns = fixture()
            topic(assessment, "name")["dimensions"][1]["key"] = key
            with self.assertRaises(ValueError):
                coverage.apply_assessment(findings, assessment, turns)

    def test_inputs_are_not_mutated_even_when_a_finding_is_demoted(self):
        findings, assessment, turns = fixture()
        topic(assessment, "checks")["gaps"] = ["Retained evidence is not established."]
        original = copy.deepcopy((findings, assessment, turns))
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        revised[0]["answer"] = "Changed returned copy"
        public["topics"][0]["gaps"].append("Changed returned copy")
        self.assertEqual((findings, assessment, turns), original)

    def test_schema_and_rubric_cover_the_same_eleven_topics(self):
        self.assertEqual(len(coverage.TOPIC_DIMENSIONS), 16)
        self.assertEqual(coverage.TOPIC_SCHEMA["properties"]["key"]["enum"], list(coverage.TOPIC_DIMENSIONS))
        self.assertIn("unknown isn't", coverage.AUDIT_INSTRUCTIONS)
        self.assertIn("Do not initiate a final omissions check", coverage.COMPLETION_POLICY)


if __name__ == "__main__":
    unittest.main()
