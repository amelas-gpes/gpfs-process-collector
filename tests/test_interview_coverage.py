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
        self.assertEqual(public["capture_repairs"], [{"key": "lifecycle", "answer": actual["answer"], "evidence_turns": actual["evidence_turns"]}])
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
        self.assertEqual(set(coverage.CAPTURE_REPAIR_SCHEMA["properties"]), {"needed"})

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

    def test_repair_mode_instructions_distinguish_omission_from_missing_fact(self):
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
        topic(assessment, "trigger")["dimensions"].pop()
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
        self.assertEqual(len(coverage.TOPIC_DIMENSIONS), 11)
        self.assertEqual(coverage.TOPIC_SCHEMA["properties"]["key"]["enum"], list(coverage.TOPIC_DIMENSIONS))
        self.assertIn("unknown isn't", coverage.AUDIT_INSTRUCTIONS)
        self.assertIn("Do not initiate a final omissions check", coverage.COMPLETION_POLICY)


if __name__ == "__main__":
    unittest.main()
