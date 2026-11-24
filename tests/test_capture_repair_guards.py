"""A coverage repair is a guarded, visible correction, never an unreviewed overwrite.

The coverage reviewer may correct an already captured section from the transcript
(interview_coverage.apply_repair_assessment). These tests hold that correction to the
guards the lead's own text passes: it may not drop a participant statement the section
cited, it passes the shared uncertainty gate, the process reviewer reads the repaired
text before the section is shown as covered, the report path does not present it as
covered, and the text it replaced stays reachable.
"""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from test_server import server, process_draft, interview_payload, incomplete_assessment, fixture_draft_audit, coverage_topic_properties
import capture_facts as facts
from test_interview_coverage import fixture, topic
from test_interview_orchestrator import REVIEW_CALLS, SyntheticTeamProvider, prepared_review, reply_payload

coverage = server.interview_coverage
agent_team = server.agent_team
CASES = json.loads((Path(__file__).with_name("fixtures") / "uncertainty_gate_cases.json").read_text(encoding="utf-8"))

# The sentences the audit published through a repair, and passive forms of the same hedge.
HEDGED_REPAIRS = [
    ("checks", "The AP manager probably approves the amount before release, and it is assumed that Treasury accepts the queue entry."),
    ("checks", "The AP manager probably approves the amount before release."),
    ("checks", "It is assumed that Treasury accepts the queue entry."),
    ("lifecycle", "It is assumed that Treasury accepts the queue entry."),
    ("checks", "The amount is probably approved by the AP manager before release."),
    ("checks", "The release is assumed to be approved by the AP manager."),
    ("checks", "Approval is presumably recorded in the register before release."),
    ("checks", "I think the AP manager might approve the amount before release."),
    ("accountable", "The AP manager is assumed to be accountable for the result."),
    ("accountable", "The AP manager might be accountable for the whole result."),
    # Variants of the same sentences that the first version of the repaired gate let through.
    ("lifecycle", "Treasury is assumed to accept the queue entry."),
    ("lifecycle", "The queue entry is presumed to be accepted by Treasury."),
    ("lifecycle", "Treasury is believed to accept the queue entry."),
    ("lifecycle", "The entry is thought to be logged by the analyst."),
    ("checks", "The team assumes the AP manager approves the amount before release."),
    ("checks", "The amount is assumed checked by the AP manager."),
    ("checks", "Unknown approver for amounts above the limit."),
    ("checks", "Not clear who approves the amount."),
    ("checks", "Approval is assumed."),
    ("checks", "Sign-off is assumed to happen in Treasury."),
    ("accountable", "The owner needs to be confirmed."),
    ("accountable", "The process has an owner whose identity is unknown."),
]
LIFECYCLE = ["The analyst logs each invoice as Received in the AP register, compares supplier and number, and marks it Checked or Hold.",
             "A duplicate is linked and closed.",
             "Other invoices go by queue link to Treasury, which records Accepted.",
             "A held invoice returns to checking after supplier correction."]


def repair_fixture(key="lifecycle", explanation=None):
    findings, assessment, turns = fixture()
    for item in assessment["topics"]:
        item["capture_repair"] = {"needed": False}
    local = topic(assessment, key)
    local["capture_repair"] = {"needed": True}
    if explanation is not None:
        local["explanation"] = explanation
    return findings, assessment, turns


def finding(items, key):
    return next(item for item in items if item["key"] == key)


def repairing(client, key, explanation=None):
    def change(result):
        for local in result["topics"]:
            # Strict output cannot carry a field its schema lacks: a call made with the
            # plain audit schema (the stand-in adds capture_repair only for the repair
            # schema) has no repair to return.
            if local["key"] == key and "capture_repair" in local:
                local["capture_repair"] = {"needed": True}
                if explanation is not None:
                    local["explanation"] = explanation
    client.result_changes["process_coverage_assessment"] = change


def call_names(client):
    return [call.args[1]["text"]["format"]["name"] for call in client.request.call_args_list]


def ledger(client, result, key="lifecycle"):
    state = client.coordinator._captures[result["capture_token"]]["fact_state"]
    return [fact for fact in state["facts"] if fact["topic"] == key]


class RepairAssessmentGuardTests(unittest.TestCase):
    def test_repair_that_drops_a_cited_participant_turn_is_refused_and_recorded_as_a_gap(self):
        findings, assessment, turns = repair_fixture(
            explanation="The analyst logs each invoice as Received and sends it by queue link to Treasury, which records Accepted.")
        turns.append({"id": "u_rework", "role": "user", "text": "A held invoice returns to checking after supplier correction."})
        original = finding(findings, "lifecycle")
        original["evidence_turns"] = ["u_lifecycle", "u_rework"]
        before = copy.deepcopy(original)
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        kept = finding(revised, "lifecycle")
        self.assertEqual((kept["answer"], kept["evidence_turns"]), (before["answer"], before["evidence_turns"]),
                         "The lead's text and citations stay when the repair would drop a cited statement")
        self.assertEqual(kept["status"], "partial")
        self.assertEqual(public["capture_repairs"], [])
        local = topic(public, "lifecycle")
        self.assertFalse(local["complete"])
        self.assertTrue(any("u_rework" in gap and "no longer cites" in gap for gap in local["gaps"]), local["gaps"])
        self.assertFalse(public["all_topics_covered"])

    def test_repair_citing_the_dropped_turn_in_a_dimension_is_accepted(self):
        findings, assessment, turns = repair_fixture()
        turns.append({"id": "u_rework", "role": "user", "text": "A held invoice returns to checking after supplier correction."})
        finding(findings, "lifecycle")["evidence_turns"] = ["u_lifecycle", "u_rework"]
        topic(assessment, "lifecycle")["dimensions"][-1]["evidence_turns"] = ["u_rework"]
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual(finding(revised, "lifecycle")["evidence_turns"], ["u_lifecycle", "u_rework"])
        self.assertEqual(len(public["capture_repairs"]), 1)

    def test_a_shorter_repair_that_keeps_every_citation_is_not_refused_for_its_length(self):
        # Removing an AI-added overstatement legitimately shortens a section.
        findings, assessment, turns = repair_fixture(key="risk", explanation="Missing a duplicate could cause Treasury to pay twice.")
        original = finding(findings, "risk")
        original["answer"] += " The controller always reverses the duplicate payment the same day."
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual(finding(revised, "risk")["answer"], "Missing a duplicate could cause Treasury to pay twice.")
        self.assertEqual(finding(revised, "risk")["status"], "captured")
        self.assertEqual([item["key"] for item in public["capture_repairs"]], ["risk"])

    def test_intake_context_is_not_a_participant_turn_for_the_citation_guard(self):
        findings, assessment, turns = repair_fixture(key="name")
        finding(findings, "name")["evidence_turns"] = ["context", "u_name"]
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual([item["key"] for item in public["capture_repairs"]], ["name"])

    def test_applied_repair_keeps_the_text_and_citations_it_replaced(self):
        findings, assessment, turns = repair_fixture()
        original = finding(findings, "lifecycle")
        original["answer"] = "The analyst registers and sends invoices to Treasury."
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        repaired = finding(revised, "lifecycle")
        self.assertEqual(public["capture_repairs"], [{
            "key": "lifecycle", "answer": repaired["answer"], "evidence_turns": repaired["evidence_turns"],
            "previous_answer": "The analyst registers and sends invoices to Treasury.",
            "previous_evidence_turns": ["u_lifecycle"]}])
        self.assertEqual(original["answer"], "The analyst registers and sends invoices to Treasury.", "Inputs are not mutated")

    def test_hedged_repairs_never_replace_the_leads_text(self):
        gate_cases = [(key, answer) for key, answer, _ in CASES["uncertain"]]
        self.assertGreaterEqual(len(gate_cases), 55)
        for key, hedged in HEDGED_REPAIRS + gate_cases:
            with self.subTest(key=key, hedged=hedged):
                findings, assessment, turns = repair_fixture(key=key, explanation=hedged)
                before = copy.deepcopy(finding(findings, key))
                revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
                after = finding(revised, key)
                self.assertEqual(after["answer"], before["answer"])
                self.assertEqual(after["status"], "partial")
                self.assertEqual(public["capture_repairs"], [])
                self.assertFalse(topic(public, key)["complete"])
                # The same text proposed by the lead is held by the same gate.
                self.assertTrue(server.finding_has_uncertainty({"key": key, "answer": hedged}))

    def test_repaired_answer_meets_the_lead_gate_without_the_reviewers_commentary_exemption(self):
        # A reviewer's dimension note may reject a counterclaim ("does not claim that ... is unknown").
        # A published answer is read by the lead gate and the browser, which have no such exemption.
        text = "The AP manager records approval in the register. The participant does not claim that the approver is unknown."
        self.assertFalse(coverage.repair_has_uncertainty(text, "checks"))
        self.assertTrue(server.finding_has_uncertainty({"key": "checks", "answer": text}))
        findings, assessment, turns = repair_fixture(key="checks", explanation=text)
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual(public["capture_repairs"], [])
        self.assertEqual(finding(revised, "checks")["status"], "partial")
        self.assertEqual(finding(revised, "checks")["answer"], finding(findings, "checks")["answer"])

    def test_repair_with_a_statement_the_ledger_cannot_record_is_refused_not_a_failed_review(self):
        self.assertEqual(coverage.STATEMENT_LIMIT, facts.MAX_FACT_TEXT)
        sample = "The analyst logs it. Treasury accepts it!\nA held invoice returns? Yes, after correction.\n\nDone."
        self.assertEqual(coverage.statements(sample), facts._sentences(sample))
        self.assertEqual(coverage.statements(sample), ["The analyst logs it.", "Treasury accepts it!", "A held invoice returns?",
                                                       "Yes, after correction.", "Done."])
        unbroken = "The analyst logs each invoice" + ", then checks the supplier and the number" * 45 + "."
        self.assertGreater(len(unbroken), coverage.STATEMENT_LIMIT)
        findings, assessment, turns = repair_fixture(explanation="The analyst logs each invoice. " + unbroken)
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual(public["capture_repairs"], [])
        self.assertEqual(finding(revised, "lifecycle")["answer"], finding(findings, "lifecycle")["answer"])
        self.assertEqual(finding(revised, "lifecycle")["status"], "partial")
        self.assertTrue(any("too long to record" in gap for gap in topic(public, "lifecycle")["gaps"]))
        # Through a review this is an open section and a question, not an error after the review has run.
        client = SyntheticTeamProvider()
        repairing(client, "lifecycle", "The analyst logs each invoice. " + unbroken)
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertEqual(finding(result["memo_findings"], "lifecycle")["answer"], "\n".join(LIFECYCLE))

    def test_list_markers_are_not_part_of_a_repaired_section(self):
        # The prompt asks for one statement per line. A reviewer that answers with a
        # bulleted or numbered list means the same statements.
        plain = [LIFECYCLE[0], LIFECYCLE[1], "Other invoices go by queue link to Treasury.", LIFECYCLE[3]]
        for label, text in (("bullets", "\n".join("- " + line for line in plain)),
                            ("typographic bullets", "\n".join(chr(0x2022) + " " + line for line in plain)),
                            ("stars", "\n".join("  * " + line for line in plain)),
                            ("numbers", "\n".join(f"{index}. {line}" for index, line in enumerate(plain, 1))),
                            ("brackets", "\n".join(f"{index}) {line}" for index, line in enumerate(plain, 1)))):
            with self.subTest(label):
                self.assertEqual(coverage.statements(text), plain)
                findings, assessment, turns = repair_fixture(explanation=text)
                revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
                published = finding(revised, "lifecycle")["answer"]
                self.assertEqual(published.split("\n"), [line for line in plain], "No list marker is published")
                self.assertEqual(public["capture_repairs"][0]["answer"], published)
                self.assertEqual(topic(public, "lifecycle")["explanation"], published)
        # Text that only looks like a marker inside a statement is left alone.
        inside = "The analyst logs 3 invoices - never more - by 3 p.m. on day 2. Treasury accepts them."
        self.assertEqual(coverage.without_list_markers(inside), inside)
        self.assertIn("no bullets or numbering", coverage.REPAIR_AUDIT_INSTRUCTIONS)

    def test_ordinary_process_wording_is_still_repairable(self):
        for key, answer in [tuple(row) for row in CASES["confident"]][:12]:
            with self.subTest(key=key, answer=answer):
                findings, assessment, turns = repair_fixture(key=key, explanation=answer)
                revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
                self.assertEqual(finding(revised, key)["answer"], answer)
                self.assertEqual(finding(revised, key)["status"], "captured")

    def test_published_repair_metadata_is_revalidated_with_the_same_guards(self):
        findings, assessment, turns = repair_fixture()
        finding(findings, "lifecycle")["answer"] = "The analyst registers and sends invoices to Treasury."
        _, public = coverage.apply_repair_assessment(findings, assessment, turns)
        participants = {turn["id"] for turn in turns} | {"context"}
        self.assertEqual(coverage.validate_capture_repairs(public, participants), public["capture_repairs"])

        def broken(change):
            value = copy.deepcopy(public)
            change(value)
            return value
        hedged = "It is assumed that Treasury accepts the queue entry."
        rejected = "The analyst logs the invoice. The participant does not claim that the approver is unknown."
        for label, value in (
                ("legacy shape", broken(lambda v: [v["capture_repairs"][0].pop(key) for key in ("previous_answer", "previous_evidence_turns")])),
                ("previous text", broken(lambda v: v["capture_repairs"][0].update(previous_answer=None))),
                ("previous sources", broken(lambda v: v["capture_repairs"][0].update(previous_evidence_turns=[1]))),
                ("oversized previous text", broken(lambda v: v["capture_repairs"][0].update(previous_answer="x" * 12001))),
                ("hedged answer", broken(lambda v: (v["capture_repairs"][0].update(answer=hedged),
                                                    topic(v, "lifecycle").update(explanation=hedged)))),
                ("lead gate", broken(lambda v: (v["capture_repairs"][0].update(answer=rejected),
                                                topic(v, "lifecycle").update(explanation=rejected))))):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    coverage.validate_capture_repairs(value, participants)


class RepairPromptTests(unittest.TestCase):
    def test_repair_groups_are_not_told_to_keep_the_canonical_answer_concise(self):
        group = coverage.COVERAGE_REVIEW_GROUPS[1]
        plain, repair = coverage.group_instructions(group), coverage.group_instructions(group, repair=True)
        self.assertIn("Keep explanations concise and cite evidence rather than restating it.", plain)
        self.assertNotIn("Keep explanations concise", repair)
        self.assertIn("ASSESS ONLY THESE TOPICS, EACH EXACTLY ONCE, IN THIS ORDER: " + ", ".join(
            key for key in coverage.TOPIC_DIMENSIONS if key in group), repair)
        self.assertIn("The other candidate findings are supplied for context only; do not return them.", repair)

    def test_repair_policy_requires_targeted_edits_with_individual_evidence(self):
        self.assertIn("Write a concise explanation using only established facts.", coverage.AUDIT_INSTRUCTIONS)
        repair = coverage.REPAIR_AUDIT_INSTRUCTIONS
        self.assertNotIn("Write a concise explanation", repair)
        for phrase in ("edit only the specific affected statements", "cite participant evidence for each edit",
                       "Preserve all unmentioned statements"):
            self.assertIn(phrase, " ".join(repair.split()))
        for group in coverage.COVERAGE_REVIEW_GROUPS:
            self.assertIn("specific affected statements", " ".join(coverage.group_instructions(group, repair=True).split()))

    def test_a_repaired_explanation_may_be_as_long_as_the_topic_it_replaces(self):
        plain = coverage.TOPIC_SCHEMA["properties"]["explanation"]["maxLength"]
        repair = coverage.REPAIR_TOPIC_SCHEMA["properties"]["explanation"]["maxLength"]
        self.assertEqual(plain, 4000, "An explanation that replaces nothing stays a concise summary")
        self.assertEqual(repair, coverage.TOPIC_ANSWER_LIMIT)
        self.assertEqual(coverage.TOPIC_ANSWER_LIMIT, 12000)
        grouped = coverage.group_schema(coverage.COVERAGE_REVIEW_GROUPS[1], repair=True)
        self.assertEqual(grouped["properties"]["topics"]["items"]["properties"]["explanation"]["maxLength"], 12000)
        self.assertEqual(coverage.group_schema(coverage.COVERAGE_REVIEW_GROUPS[1])["properties"]["topics"]["items"]
                         ["properties"]["explanation"]["maxLength"], 4000)
        sentence = "The analyst logs each invoice as Received in the AP register and files the email in the AP folder."
        long_text = "\n".join(f"{sentence[:-1]} for supplier group {index}." for index in range(60))
        self.assertGreater(len(long_text), 4000)
        findings, assessment, turns = repair_fixture(explanation=long_text)
        revised, public = coverage.apply_repair_assessment(findings, assessment, turns)
        self.assertEqual(finding(revised, "lifecycle")["answer"], long_text)
        self.assertEqual(len(public["capture_repairs"]), 1)


class ProcessBudgetTests(unittest.TestCase):
    def test_process_reviewer_has_one_further_pass_for_a_repaired_account(self):
        self.assertEqual(agent_team.ROLE_CONTRACTS["process_reviewer"]["max_calls"], 2)
        self.assertEqual(agent_team.ROLE_CONTRACTS["coverage_reviewer"]["max_calls"], 1)
        _, _, turns = fixture()
        run = agent_team.TeamRun(agent_team.build_evidence_ledger({"process_name": "Invoice intake"}, turns))
        review = {"summary": "Reviewed.", "evidence_turns": ["u_lifecycle"], "findings": [], "next_question": "",
                  "no_material_blockers": True}
        run.run_role("process_reviewer", lambda: review)
        second = dict(review, summary="Reviewed the repaired account.")
        run.run_role("process_reviewer", lambda: second)
        self.assertEqual(run.results["process_reviewer"]["summary"], "Reviewed the repaired account.")
        with self.assertRaises(agent_team.TeamBlockedError):
            run.run_role("process_reviewer", lambda: self.fail("A third pass is not budgeted"))
        self.assertEqual(run.public_status()["budget"]["used_calls"], 2)


class CoordinatorRepairReviewTests(unittest.TestCase):
    SHORT = "The analyst logs and checks each invoice, then sends it to Treasury."
    INVENTED = "The duty manager releases each invoice to Treasury after the analyst logs it."

    def test_process_reviewer_reads_the_repaired_text_before_it_is_shown_as_covered(self):
        client = SyntheticTeamProvider()
        repairing(client, "lifecycle", self.INVENTED)
        read = []

        def record(body):
            candidate = json.loads(body["input"][0]["content"])["candidate_capture"]
            read.append(finding(candidate["memo_findings"], "lifecycle")["answer"])
            self.assertNotIn("coverage_assessment", candidate, "Neither reviewer consumes the other's opinion")
            self.assertNotIn("process_review", candidate)
            client.process["summary"] = f"Process pass {len(read)}."
        client.hooks["process_specialist_review"] = record
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(len(read), 2)
        self.assertEqual(read[0], "\n".join(LIFECYCLE), "The concurrent pass read the lead's text")
        self.assertEqual(read[1], self.INVENTED, "A further pass read the text that is published")
        self.assertEqual(finding(result["memo_findings"], "lifecycle")["answer"], self.INVENTED)
        self.assertEqual(result["process_review"]["summary"], "Process pass 2.")
        role = next(row for row in result["agent_team"]["agents"] if row["role"] == "process_reviewer")
        self.assertEqual((role["status"], role["calls"]), ("completed", 2))

    def test_repaired_review_reaches_the_final_check_without_a_second_full_review(self):
        client = SyntheticTeamProvider()
        finding(client.findings, "lifecycle")["answer"] = "The analyst registers invoices and sends them to Treasury."
        repairing(client, "lifecycle")
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(result["speech_authorization"]["kind"], "final_check")
        self.assertTrue(result["coverage_verified"])
        self.assertTrue(result["completion"]["ready_for_final_check"])
        self.assertEqual(finding(result["memo_findings"], "lifecycle")["status"], "captured")
        names = call_names(client)
        self.assertEqual(names.count("process_coverage_assessment"), len(coverage.COVERAGE_REVIEW_GROUPS))
        self.assertEqual(names.count("process_specialist_review"), 2)
        self.assertEqual(names.count("team_interview_capture"), 1)
        self.assertEqual(client.request.call_count, 1 + REVIEW_CALLS + 1, "One further process pass, not a second full review")
        confirmed = client.coordinator.interview(reply_payload(payload, result, "No, nothing else."))
        self.assertTrue(confirmed["completion"]["complete"])
        self.assertEqual(client.request.call_count, 1 + REVIEW_CALLS + 1)

    def test_review_without_a_repair_keeps_one_process_pass(self):
        client = SyntheticTeamProvider()
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(call_names(client).count("process_specialist_review"), 1)
        self.assertEqual(client.request.call_count, 1 + REVIEW_CALLS)
        self.assertEqual(result["speech_authorization"]["kind"], "final_check")
        self.assertEqual(result["coverage_assessment"]["capture_repairs"], [])

    CHECKS = ["The analyst checks supplier and number for duplicates.",
              "The AP manager reviews the amount and records approval in the register before release.",
              "A failure stays on Hold for supplier correction and repeat checking.",
              "The analyst keeps the invoice and decision in the AP folder."]

    INVENTED_CHECK = "The duty manager approves the amount and records approval in the register before release."
    OBJECTION = "No participant statement names a duty manager as approver."
    # What a reviewer of the rewritten text might ask: it attributes the rewrite to the participant.
    ABOUT_THE_REWRITE = "You said the duty manager approves the amount; who covers for the duty manager?"
    REPAIR_QUESTION = ("I need to correct my notes on " + server.COVERAGE["checks"]
                       + " from what you have told me. What would you add or change in that part?")

    def objecting_to_duty_manager(self, client, question=ABOUT_THE_REWRITE):
        def object_to_repair(body):
            candidate = json.loads(body["input"][0]["content"])["candidate_capture"]
            if "duty manager" in finding(candidate["memo_findings"], "checks")["answer"]:
                client.blocker(question)
                client.process["findings"][0].update(kind="unsupported_claim", evidence_turns=["u_checks"], detail=self.OBJECTION)
                client.process["summary"] = "Reviewed the account in which the duty manager approves the amount."
        client.hooks["process_specialist_review"] = object_to_repair

    def test_repair_the_process_reviewer_objects_to_is_withdrawn_and_the_leads_text_stays(self):
        client = SyntheticTeamProvider()
        repairing(client, "checks", self.INVENTED_CHECK)
        self.objecting_to_duty_manager(client)
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertIn("repair_withdrawn:checks", result["completion"]["blockers"])
        checks = finding(result["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["evidence_turns"], checks["status"]), ("\n".join(self.CHECKS), ["u_checks"], "partial"))
        self.assertNotIn("duty manager", json.dumps(result["memo_findings"]))
        self.assertEqual(finding(result["coverage"], "checks")["status"], "partial")
        self.assertEqual(result["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        # The pass over the lead's text, which is the text published, raised nothing:
        # only the section whose correction was withdrawn stays open.
        self.assertEqual(result["coverage_adjudication"]["unconfirmed_topics"], ["checks"])
        self.assertEqual(finding(result["memo_findings"], "lifecycle")["status"], "captured")
        # The proposal stays on record beside the account it did not change.
        repair = result["coverage_assessment"]["capture_repairs"][0]
        self.assertEqual((repair["key"], repair["answer"], repair["previous_answer"]),
                         ("checks", self.INVENTED_CHECK, "\n".join(self.CHECKS)))
        records = ledger(client, result, "checks")
        self.assertEqual([(fact["text"], fact["state"], fact["origin"]) for fact in records],
                         [(text, "active", "lead") for text in self.CHECKS], "The private ledger is untouched")
        self.assertEqual(call_names(client).count("process_specialist_review"), 2)
        done = client.coordinator.interview(reply_payload(payload, result, "No, nothing else."))
        self.assertFalse(done["completion"]["complete"])

    def test_participant_is_not_asked_about_text_that_was_withdrawn(self):
        # The pass that objected read a rewrite that is not published. Its question and
        # its findings are about that rewrite, so neither is spoken or published as the review.
        client = SyntheticTeamProvider()
        repairing(client, "checks", self.INVENTED_CHECK)
        self.objecting_to_duty_manager(client)
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(result["question"], self.REPAIR_QUESTION)
        self.assertEqual(result["speech_authorization"]["text"], self.REPAIR_QUESTION)
        self.assertNotIn("duty manager", result["question"])
        published = result["process_review"]
        self.assertEqual(published["summary"], "The reported route is described through Treasury acceptance.",
                         "The published process review is the one that read the published text")
        self.assertEqual((published["findings"], published["next_question"]), ([], ""))
        self.assertNotIn("duty manager", json.dumps(published))
        self.assertEqual(result["coverage_adjudication"]["repair_pass_findings"], [self.OBJECTION])
        sent = []
        client.hooks["team_interview_capture"] = lambda body: sent.append(json.loads(body["input"][0]["content"]))
        client.coordinator.interview(reply_payload(payload, result, "The AP manager approves it; there is no duty manager."))
        previous = sent[0]["previous_capture"]
        self.assertNotIn("duty manager", json.dumps(previous["process_review"]),
                         "The lead is not given a review of unpublished text as the review of its account")
        told = next(item for item in previous["coverage_assessment"]["topics"] if item["key"] == "checks")
        # The lead meets the rewrite only as a labelled proposal, with what the process
        # review found in the account that had the proposal applied.
        self.assertEqual({key for key, value in told.items() if "duty manager" in json.dumps(value)},
                         {"proposed_correction", "findings_with_proposal_applied"})

    def test_published_assessment_does_not_call_a_withdrawn_section_complete(self):
        client = SyntheticTeamProvider()
        repairing(client, "checks", self.INVENTED_CHECK)
        self.objecting_to_duty_manager(client)
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        assessment = result["coverage_assessment"]
        checks = next(item for item in assessment["topics"] if item["key"] == "checks")
        self.assertFalse(checks["complete"])
        self.assertTrue(any("did not accept" in gap for gap in checks["gaps"]), checks["gaps"])
        self.assertFalse(assessment["all_topics_covered"])
        self.assertTrue(next(item for item in assessment["topics"] if item["key"] == "purpose")["complete"])
        self.assertEqual(finding(result["memo_findings"], "checks")["status"], "partial")
        # The role's own bound result is not edited: it still records what the reviewer returned.
        bound = client.coordinator._captures[result["capture_token"]]["run"].results["coverage_reviewer"]
        self.assertTrue(next(item for item in bound["topics"] if item["key"] == "checks")["complete"])

    def test_lead_is_told_that_a_section_with_a_withdrawn_repair_is_open(self):
        client = SyntheticTeamProvider()
        repairing(client, "checks", self.INVENTED_CHECK)
        self.objecting_to_duty_manager(client)
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        sent = []
        client.hooks["team_interview_capture"] = lambda body: sent.append(json.loads(body["input"][0]["content"]))
        client.coordinator.interview(reply_payload(payload, result, "The AP manager approves it; there is no duty manager."))
        topics = {item["key"]: item for item in sent[0]["previous_capture"]["coverage_assessment"]["topics"]}
        self.assertFalse(topics["checks"]["complete"])
        self.assertEqual(sum("did not accept" in gap for gap in topics["checks"]["gaps"]), 1, topics["checks"]["gaps"])
        self.assertFalse(sent[0]["previous_capture"]["coverage_assessment"]["all_topics_covered"])
        self.assertTrue(topics["purpose"]["complete"])
        self.assertNotIn("proposed_correction", topics["purpose"])
        # What the reviewer wanted to publish and what was objected to, so the lead can
        # correct its own facts instead of waiting for the same proposal again.
        self.assertEqual(topics["checks"]["proposed_correction"], self.INVENTED_CHECK)
        self.assertEqual(topics["checks"]["findings_with_proposal_applied"], [self.OBJECTION])
        self.assertNotIn("objections_to_proposal", topics["checks"], "A finding of that pass may concern another section")
        self.assertIn("proposed_correction", facts.FACT_CAPTURE_POLICY)
        self.assertIn("findings_with_proposal_applied", facts.FACT_CAPTURE_POLICY)
        self.assertRegex(facts.FACT_CAPTURE_POLICY, r"may concern\s+another section")
        self.assertIn("never evidence", facts.FACT_CAPTURE_POLICY)
        self.assertNotIn("duty manager approves", json.dumps(sent[0]["fact_state"]))

    def test_lead_is_shown_the_correction_a_guard_refused(self):
        # A refused repair leaves a section open that neither reviewer has a question
        # about. The participant is asked about that section by name, and the lead is
        # shown the proposed section so it can correct its own facts.
        client = SyntheticTeamProvider()
        client.turns.append({"id": "u_rework", "role": "user", "text": "A held invoice returns to checking after supplier correction."})
        finding(client.findings, "lifecycle")["evidence_turns"] = ["u_lifecycle", "u_rework"]
        proposed = "The analyst logs each invoice as Received and sends it by queue link to Treasury, which records Accepted."
        repairing(client, "lifecycle", proposed)
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertEqual(result["question"], "I need to correct my notes on " + server.COVERAGE["lifecycle"]
                         + " from what you have told me. What would you add or change in that part?")
        sent = []
        client.hooks["team_interview_capture"] = lambda body: sent.append(json.loads(body["input"][0]["content"]))
        client.coordinator.interview(reply_payload(payload, result, "I have nothing to add to that."))
        topics = {item["key"]: item for item in sent[0]["previous_capture"]["coverage_assessment"]["topics"]}
        self.assertEqual(topics["lifecycle"]["proposed_correction"], proposed)
        self.assertNotIn("findings_with_proposal_applied", topics["lifecycle"])
        self.assertTrue(any("u_rework" in gap for gap in topics["lifecycle"]["gaps"]), "The gap says why it was not applied")
        self.assertEqual([key for key, topic in topics.items() if "proposed_correction" in topic], ["lifecycle"])

    def test_repair_is_withdrawn_when_the_repaired_account_still_draws_a_material_finding(self):
        # A finding cannot be attributed to a section, so a repair stands only on a clear pass.
        client = SyntheticTeamProvider()
        client.blocker()
        repaired = " ".join(self.CHECKS[:3] + ["The analyst keeps the invoice and the approval decision in the AP folder."])
        repairing(client, "checks", repaired)
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(call_names(client).count("process_specialist_review"), 2)
        self.assertEqual(result["question"], "Who receives the corrected invoice?", "The question of the pass that read the published text")
        checks = finding(result["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["status"]), ("\n".join(self.CHECKS), "partial"))
        self.assertEqual(finding(result["coverage"], "checks")["status"], "partial")
        self.assertEqual(finding(result["memo_findings"], "lifecycle")["status"], "partial")
        self.assertEqual(result["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        self.assertEqual(result["coverage_adjudication"]["unconfirmed_topics"], ["lifecycle", "checks"])
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertEqual([(fact["state"], fact["origin"]) for fact in ledger(client, result, "checks")], [("active", "lead")] * 4)

    def test_objection_to_a_repair_is_not_hidden_by_an_earlier_unrelated_finding(self):
        # The lead's account already had one open process finding; the pass over the
        # repaired text has one finding too, and it is about the repair itself.
        client = SyntheticTeamProvider()
        repairing(client, "checks", self.INVENTED_CHECK)
        client.blocker("Who receives the corrected invoice?")
        self.objecting_to_duty_manager(client, "Who approves the amount before release?")
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(call_names(client).count("process_specialist_review"), 2)
        checks = finding(result["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["status"]), ("\n".join(self.CHECKS), "partial"))
        self.assertNotIn("duty manager", json.dumps(result["memo_findings"]))
        self.assertEqual(finding(result["coverage"], "checks")["status"], "partial")
        self.assertEqual(result["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        self.assertEqual(result["coverage_adjudication"]["unconfirmed_topics"], ["lifecycle", "checks"])
        self.assertEqual(result["question"], "Who receives the corrected invoice?")
        self.assertFalse(result["completion"]["ready_for_final_check"])
        records = ledger(client, result, "checks")
        self.assertEqual([(fact["text"], fact["state"], fact["origin"]) for fact in records],
                         [(text, "active", "lead") for text in self.CHECKS], "The lead's facts are not replaced")

    def test_repair_that_clears_the_finding_the_leads_text_drew_stands(self):
        client = SyntheticTeamProvider()
        client.blocker()
        repaired = " ".join(self.CHECKS[:3] + ["The analyst keeps the invoice and the approval decision in the AP folder."])
        repairing(client, "checks", repaired)

        def cleared_by_repair(body):
            candidate = json.loads(body["input"][0]["content"])["candidate_capture"]
            if "approval decision" in finding(candidate["memo_findings"], "checks")["answer"]:
                client.process.update(findings=[], next_question="", no_material_blockers=True)
        client.hooks["process_specialist_review"] = cleared_by_repair
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        checks = finding(result["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["status"]), (repaired, "captured"))
        self.assertEqual(finding(result["coverage"], "checks")["status"], "covered")
        self.assertNotIn("coverage_adjudication", result)
        self.assertEqual(result["speech_authorization"]["kind"], "final_check")
        self.assertEqual([fact["origin"] for fact in ledger(client, result, "checks") if fact["state"] == "active"],
                         ["lead", "lead", "lead", "coverage_repair"])

    def test_further_pass_is_given_the_repaired_text_and_nothing_else_of_the_coverage_review(self):
        client = SyntheticTeamProvider()
        repaired = " ".join(self.CHECKS[:3] + ["The analyst keeps the invoice and the approval decision in the AP folder."])

        def change(result):
            for local in result["topics"]:
                if local["key"] == "checks":
                    local.update(capture_repair={"needed": True}, explanation=repaired)
                if local["key"] == "risk":  # the coverage reviewer's opinion about another section
                    local.update(gaps=["The consequence of a late payment was not explained."],
                                 next_question="What happens if a payment is late?")
        client.result_changes["process_coverage_assessment"] = change
        seen = []
        client.hooks["process_specialist_review"] = lambda body: seen.append(
            {item["key"]: item for item in json.loads(body["input"][0]["content"])["candidate_capture"]["memo_findings"]})
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(len(seen), 2)
        self.assertEqual(finding(result["memo_findings"], "risk")["status"], "partial", "The coverage reviewer demoted it")
        self.assertEqual({key: item["status"] for key, item in seen[1].items()}, {key: item["status"] for key, item in seen[0].items()},
                         "The process reviewer is not given the coverage reviewer's status changes")
        self.assertEqual(seen[1]["risk"]["status"], "captured")
        self.assertEqual(seen[1]["checks"]["answer"], repaired)
        changed = [key for key in seen[0] if seen[0][key] != seen[1][key]]
        self.assertEqual(changed, ["checks"], "Only the repaired section differs between the two requests")

    FAITHFUL_CHECKS = " ".join(CHECKS[:3] + ["The analyst keeps the invoice and the approval decision in the AP folder."])
    UNAVAILABLE_DETAIL = "The recipient of the corrected invoice is not established."

    def repair_beside_an_unavailable_detail(self):
        """A faithful repair of the checks, and a process finding nobody in the room can settle."""
        client = SyntheticTeamProvider()
        client.turns.append({"id": "u_unknown", "role": "user", "text": "I don't know who receives the corrected invoice or who could tell us."})
        local = next(item for item in client.assessment["topics"] if item["key"] == "lifecycle")
        local.update(gaps=["The recipient of a corrected invoice remains unknown."], next_question="",
                     participant_unavailable=True, unavailable_evidence_turns=["u_unknown"])
        next(item for item in local["dimensions"] if item["key"] == "handoffs").update(
            status="unresolved", detail="The participant does not know the corrected invoice recipient.", evidence_turns=["u_unknown"])
        client.blocker("")
        client.process["findings"][0]["evidence_turns"] = ["u_unknown"]
        repairing(client, "checks", self.FAITHFUL_CHECKS)
        return client

    def test_a_repair_cannot_stand_beside_an_unresolved_finding_even_for_an_unavailable_detail(self):
        # A finding about a detail the participant cannot supply is still a material
        # finding on the repaired account, so the correction is withdrawn and its section
        # asked about; the pause for the unavailable detail follows at the next review.
        client = self.repair_beside_an_unavailable_detail()
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertEqual(result["question"], self.REPAIR_QUESTION)
        checks = finding(result["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["status"]), ("\n".join(self.CHECKS), "partial"))
        self.assertEqual(result["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        self.assertEqual(len(result["coverage_assessment"]["capture_repairs"]), 1, "The proposal stays on record")
        # The finding of that pass is about another section. The lead is given it as a
        # finding on the account with the proposal applied, not as an objection to the proposal.
        self.assertEqual(result["coverage_adjudication"]["repair_pass_findings"], [self.UNAVAILABLE_DETAIL])
        sent = []
        client.hooks["team_interview_capture"] = lambda body: sent.append(json.loads(body["input"][0]["content"]))
        client.coordinator.interview(reply_payload(payload, result, "I have nothing to add or change there."))
        told = next(item for item in sent[0]["previous_capture"]["coverage_assessment"]["topics"] if item["key"] == "checks")
        self.assertEqual(told["proposed_correction"], self.FAITHFUL_CHECKS)
        self.assertEqual(told["findings_with_proposal_applied"], [self.UNAVAILABLE_DETAIL])
        self.assertNotIn("objections_to_proposal", told)

    def next_review(self, client, payload, result, reply="I have nothing to add or change there.", number=2):
        """The participant answers the review's question; the lead proposes a full account again."""
        follow = reply_payload(payload, result, reply)
        for turn in follow["turns"][-2:]:
            turn["id"] += f"_{number}"
        turn = client.coordinator.interview(follow)
        self.assertEqual(turn["speech_authorization"]["kind"], "review_pending")
        follow["turns"].append({"id": f"a_review_ack_{number}", "role": "assistant", "text": turn["question"]})
        follow.update(capture_token=turn["capture_token"], review_ticket=turn["review_ticket"])
        return follow, client.coordinator.review(follow)

    def coverage_calls(self, client):
        """(topics asked for, whether the call could propose a repair) of each coverage call, in call order."""
        rows = []
        for call in client.request.call_args_list:
            body = call.args[1]
            if body["text"]["format"]["name"] == "process_coverage_assessment":
                item = coverage_topic_properties(body["text"]["format"]["schema"])[0]
                rows.append((json.loads(body["input"][0]["content"])["assess_topics"], "capture_repair" in item,
                             "EXPLICIT CAPTURE REPAIR RULES" in body["instructions"]))
        return rows

    def test_a_withdrawn_repair_is_not_asked_for_again_while_the_leads_text_is_unchanged(self):
        # The process finding can never be settled in this interview, so the same
        # faithful repair would be proposed and withdrawn at every review, and the pause
        # for the unavailable detail would never be offered.
        client = self.repair_beside_an_unavailable_detail()
        payload, pending = prepared_review(client)
        first = client.coordinator.review(payload)
        self.assertEqual(first["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        self.assertEqual(first["question"], self.REPAIR_QUESTION)
        self.assertTrue(all(repair and rules for _, repair, rules in self.coverage_calls(client)))
        before = client.request.call_count
        self.assertEqual(before, 1 + REVIEW_CALLS + 1)
        payload, second = self.next_review(client, payload, first)
        calls = self.coverage_calls(client)[len(coverage.COVERAGE_REVIEW_GROUPS):]
        # The section is judged on the lead's text, by a call that has no repair to offer.
        self.assertEqual([(topics, repair, rules) for topics, repair, rules in calls if "checks" in topics],
                         [(["checks"], False, False)])
        self.assertEqual(sorted(key for topics, repair, _ in calls if repair for key in topics),
                         sorted(key for key in server.COVERAGE if key != "checks"), "Every other section keeps the repair facility")
        self.assertEqual(second["coverage_assessment"]["capture_repairs"], [])
        self.assertNotIn("withdrawn_repairs", second.get("coverage_adjudication", {}))
        checks = finding(second["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["status"]), ("\n".join(self.CHECKS), "captured"),
                         "The plain audit accepted the lead's text as it stands")
        self.assertEqual(second["speech_authorization"]["kind"], "pause")
        self.assertIn("information you do not have here: " + server.COVERAGE["lifecycle"], second["question"])
        self.assertNotEqual(second["question"], first["question"])
        self.assertFalse(second["completion"]["ready_for_final_check"])
        # One lead call, the coverage groups plus the section's own call, one process pass:
        # no further pass, because no repair was proposed.
        self.assertEqual(client.request.call_count - before, 1 + len(coverage.COVERAGE_REVIEW_GROUPS) + 1 + 1)
        self.assertEqual(call_names(client).count("process_specialist_review"), 3)

    def test_the_plain_audit_of_that_section_can_still_find_it_wanting(self):
        # Not asking for the repair again is not accepting the section: the reviewer that
        # judges the lead's text may record its gap and ask the participant about it.
        client = self.repair_beside_an_unavailable_detail()
        payload, pending = prepared_review(client)
        first = client.coordinator.review(payload)
        propose = client.result_changes["process_coverage_assessment"]

        def judged_as_it_stands(result):
            propose(result)
            for local in result["topics"]:
                if local["key"] == "checks" and "capture_repair" not in local:
                    local.update(gaps=["Where the approval decision is kept is not in the captured section."],
                                 next_question="Where is the approval decision kept?")
                    local["dimensions"][0].update(status="unresolved", detail="The retained decision is not captured.")
        client.result_changes["process_coverage_assessment"] = judged_as_it_stands
        payload, second = self.next_review(client, payload, first)
        self.assertEqual(second["speech_authorization"]["kind"], "question")
        self.assertEqual(second["question"], "Where is the approval decision kept?", "A question of the reviewer's own")
        checks = finding(second["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["status"]), ("\n".join(self.CHECKS), "partial"))
        self.assertEqual(second["coverage_assessment"]["capture_repairs"], [])

    def test_a_repair_can_be_proposed_again_once_the_lead_changes_the_section(self):
        client = self.repair_beside_an_unavailable_detail()
        payload, pending = prepared_review(client)
        first = client.coordinator.review(payload)
        self.assertEqual(first["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        # The lead rewords the section after the participant's answer: it is a new text.
        changed = self.CHECKS[:3] + ["The analyst keeps the invoice and the decision in the shared AP folder."]
        finding(client.findings, "checks")["answer"] = "\n".join(changed)
        payload, second = self.next_review(client, payload, first, "It is the shared AP folder.")
        calls = self.coverage_calls(client)[len(coverage.COVERAGE_REVIEW_GROUPS):]
        self.assertEqual(len(calls), len(coverage.COVERAGE_REVIEW_GROUPS))
        self.assertTrue(all(repair for _, repair, _ in calls), "The changed section may be repaired")
        self.assertEqual(second["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        self.assertEqual(finding(second["memo_findings"], "checks")["answer"], "\n".join(changed))

    def test_another_conversation_with_the_same_section_text_keeps_the_repair_facility(self):
        # The memory of a withdrawn repair is keyed by the process context as well as the
        # section and its text. Keyed by the text alone, a second interview about another
        # process that happens to word a section the same way could never have it repaired.
        client = self.repair_beside_an_unavailable_detail()
        payload, pending = prepared_review(client)
        first = client.coordinator.review(payload)
        self.assertEqual(first["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        other = client.payload()
        other["context"].update(process_name="Supplier refund approval", process_owner="Treasury")
        other, pending = prepared_review(client, other)
        self.assertEqual(finding(pending["memo_findings"], "checks")["answer"], "\n".join(self.CHECKS), "The same section text")
        before = len(self.coverage_calls(client))
        second = client.coordinator.review(other)
        calls = self.coverage_calls(client)[before:]
        self.assertEqual(len(calls), len(coverage.COVERAGE_REVIEW_GROUPS), "No section is taken out of its group")
        self.assertTrue(all(repair and rules for _, repair, rules in calls), "Every section may be repaired")
        self.assertEqual(second["coverage_adjudication"]["withdrawn_repairs"], ["checks"], "The repair was proposed here too")
        # Back in the first conversation the section is still judged as it stands.
        payload, third = self.next_review(client, payload, first)
        self.assertEqual(third["coverage_assessment"]["capture_repairs"], [])
        self.assertNotIn("withdrawn_repairs", third.get("coverage_adjudication", {}))

    def test_the_memory_of_withdrawn_repairs_is_kept_per_section_and_bounded(self):
        coordinator = SyntheticTeamProvider().coordinator
        context = {"process_name": "Invoice approval", "process_owner": "AP team"}
        text = "The AP manager approves the amount before release."
        findings = [{"key": "checks", "answer": text}, {"key": "lifecycle", "answer": text},
                    {"key": "risk", "answer": "A wrong amount is paid."}]
        coordinator._note_withdrawn_repairs(context, findings, ["checks"])
        # The section is part of the key: the same words in another section are another text.
        self.assertEqual(coordinator._repairs_not_to_repeat(context, findings), ["checks"])
        self.assertEqual(coordinator._repairs_not_to_repeat(dict(context), copy.deepcopy(findings)), ["checks"], "By value")
        self.assertEqual(coordinator._repairs_not_to_repeat({**context, "process_name": "Supplier refund approval"}, findings), [])
        self.assertEqual(coordinator._repairs_not_to_repeat(context, [{"key": "checks", "answer": text + " It is logged."}]), [])
        # Only digests are kept, and no more than the limit: the oldest is forgotten first.
        limit = coordinator.WITHDRAWN_REPAIR_MEMORY
        self.assertEqual(limit, 512)
        self.assertTrue(all(isinstance(key, str) and len(key) == 64 and text not in key for key in coordinator._withdrawn_repairs))

        def section(number):
            return [{"key": "checks", "answer": f"Text {number}."}]
        for number in range(limit + 40):
            coordinator._note_withdrawn_repairs(context, section(number), ["checks"])
        self.assertEqual(len(coordinator._withdrawn_repairs), limit)
        self.assertEqual(coordinator._repairs_not_to_repeat(context, findings), [], "The first withdrawal has been forgotten")
        self.assertEqual(coordinator._repairs_not_to_repeat(context, section(39)), [])
        self.assertEqual(coordinator._repairs_not_to_repeat(context, section(40)), ["checks"])
        self.assertEqual(coordinator._repairs_not_to_repeat(context, section(limit + 39)), ["checks"])
        # A withdrawal that happens again counts as recent, so it outlives older ones.
        coordinator._note_withdrawn_repairs(context, section(40), ["checks"])
        coordinator._note_withdrawn_repairs(context, section("new"), ["checks"])
        self.assertEqual(len(coordinator._withdrawn_repairs), limit)
        self.assertEqual(coordinator._repairs_not_to_repeat(context, section(40)), ["checks"])
        self.assertEqual(coordinator._repairs_not_to_repeat(context, section(41)), [])

    def test_a_section_judged_without_the_repair_facility_cannot_come_back_repaired(self):
        client = SyntheticTeamProvider()
        context, captured = interview_payload()["context"], finding(client.findings, "checks")["answer"]
        findings, assessment = client.assess_coverage(client.findings, context, client.turns, {}, force=True,
                                                      allow_capture_repair=True, split=True, no_repair_topics=("checks", "risk"))
        calls = self.coverage_calls(client)
        # Independent workers can dispatch in either order. The protected sections
        # must still share exactly one call and keep the memo's order within it.
        self.assertEqual([call for call in calls if "checks" in call[0] or "risk" in call[0]],
                         [(["checks", "risk"], False, False)])
        self.assertEqual(len(calls), len(coverage.COVERAGE_REVIEW_GROUPS) + 1)
        self.assertEqual(sorted(key for topics, *_ in calls for key in topics), sorted(server.COVERAGE), "Every section exactly once")
        self.assertTrue(assessment["all_topics_covered"])
        self.assertEqual(assessment["capture_repairs"], [])
        self.assertEqual((finding(findings, "checks")["answer"], finding(findings, "checks")["status"]), (captured, "captured"))

        # A reply that carries a repair for such a section does not fit the schema it was
        # asked with, so the whole review fails closed instead of applying it.
        def forced(result):
            for local in result["topics"]:
                if local["key"] == "checks":
                    local.update(capture_repair={"needed": True}, explanation=self.INVENTED_CHECK)
        client.result_changes["process_coverage_assessment"] = forced
        findings, assessment = client.assess_coverage(client.findings, context, client.turns, {}, force=True,
                                                      allow_capture_repair=True, split=True, no_repair_topics=("checks",))
        self.assertFalse(assessment["review_available"])
        self.assertEqual((finding(findings, "checks")["answer"], finding(findings, "checks")["status"]), (captured, "partial"))
        # Without the repair facility, or for an advisory subset, there is nothing to withhold.
        client.result_changes.clear()
        before = client.request.call_count
        client.assess_coverage(client.findings, context, client.turns, {}, force=True, split=True, no_repair_topics=("checks",))
        self.assertEqual(client.request.call_count - before, len(coverage.COVERAGE_REVIEW_GROUPS))

    def test_a_pass_that_reports_blockers_without_naming_one_does_not_clear_a_repair(self):
        # The standing rule has two halves: no material finding, and the reviewer's own
        # statement that nothing material blocks the account. A pass over the repaired
        # text that names no finding but does not give that statement has not cleared it.
        client = SyntheticTeamProvider()
        repairing(client, "checks", self.FAITHFUL_CHECKS)

        def undecided_about_the_repair(body):
            candidate = json.loads(body["input"][0]["content"])["candidate_capture"]
            if "approval decision" in finding(candidate["memo_findings"], "checks")["answer"]:
                client.process.update(findings=[], next_question="", no_material_blockers=False,
                                      summary="Reviewed the repaired account without a conclusion.")
        client.hooks["process_specialist_review"] = undecided_about_the_repair
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(call_names(client).count("process_specialist_review"), 2)
        checks = finding(result["memo_findings"], "checks")
        self.assertEqual((checks["answer"], checks["evidence_turns"], checks["status"]), ("\n".join(self.CHECKS), ["u_checks"], "partial"))
        self.assertEqual(finding(result["coverage"], "checks")["status"], "partial")
        self.assertEqual(result["coverage_adjudication"]["withdrawn_repairs"], ["checks"])
        self.assertEqual(result["coverage_adjudication"]["repair_pass_findings"], [])
        self.assertEqual(result["process_review"]["summary"], "The reported route is described through Treasury acceptance.",
                         "The published process review is the pass that read the published text")
        self.assertTrue(result["process_review"]["no_material_blockers"])
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertIn("repair_withdrawn:checks", result["completion"]["blockers"])
        self.assertEqual(result["question"], self.REPAIR_QUESTION)
        self.assertEqual([(fact["state"], fact["origin"]) for fact in ledger(client, result, "checks")], [("active", "lead")] * 4)

    def test_failed_pass_over_the_repaired_text_verifies_nothing_and_asks_for_a_retry(self):
        client = SyntheticTeamProvider()
        repairing(client, "lifecycle", self.SHORT)
        calls = []

        def fail_second(body):
            calls.append(body)
            if len(calls) == 2:
                raise server.APIError("Synthetic process failure")
        client.hooks["process_specialist_review"] = fail_second
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["review_retry_required"])
        self.assertFalse(result["coverage_verified"])
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertEqual(result["speech_authorization"]["kind"], "pause")
        lifecycle = finding(result["memo_findings"], "lifecycle")
        self.assertEqual((lifecycle["answer"], lifecycle["status"]), ("\n".join(LIFECYCLE), "partial"),
                         "Text no process reviewer has read is not published")
        self.assertNotEqual(finding(result["coverage"], "lifecycle")["status"], "covered")
        self.assertFalse(result["process_review"]["review_available"])
        self.assertEqual(result["coverage_adjudication"]["withdrawn_repairs"], ["lifecycle"])
        self.assertEqual([fact["state"] for fact in ledger(client, result)], ["active"] * 4)
        # The explicit retry starts again from the lead's account and can apply the repair.
        client.hooks.clear()
        payload["capture_token"] = result["capture_token"]
        payload["turns"].append({"id": "a_review_failure", "role": "assistant", "text": result["question"]})
        retried = client.coordinator.review({**payload, "retry_review": True})
        self.assertEqual(retried["speech_authorization"]["kind"], "final_check")
        self.assertEqual(finding(retried["memo_findings"], "lifecycle")["answer"], self.SHORT)

    def test_first_process_failure_is_not_silently_retried_on_the_repaired_text(self):
        client = SyntheticTeamProvider()
        repairing(client, "lifecycle", self.SHORT)
        client.faults["process_specialist_review"] = server.APIError("Synthetic process failure")
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(call_names(client).count("process_specialist_review"), 1)
        self.assertTrue(result["review_retry_required"])
        self.assertFalse(result["coverage_verified"])
        lifecycle = finding(result["memo_findings"], "lifecycle")
        self.assertEqual((lifecycle["answer"], lifecycle["status"]), ("\n".join(LIFECYCLE), "partial"))
        self.assertEqual(result["coverage_adjudication"]["withdrawn_repairs"], ["lifecycle"])

    def test_lossy_repair_leaves_the_leads_text_reachable(self):
        client = SyntheticTeamProvider()
        repairing(client, "lifecycle", self.SHORT)
        payload, pending = prepared_review(client)
        before = finding(pending["memo_findings"], "lifecycle")
        result = client.coordinator.review(payload)
        self.assertEqual(finding(result["memo_findings"], "lifecycle")["answer"], self.SHORT)
        repair = result["coverage_assessment"]["capture_repairs"][0]
        self.assertEqual(repair["previous_answer"], before["answer"])
        self.assertEqual(repair["previous_answer"], "\n".join(LIFECYCLE))
        self.assertEqual(repair["previous_evidence_turns"], before["evidence_turns"])
        records = ledger(client, result)
        self.assertEqual([fact["text"] for fact in records if fact["state"] == "superseded_review"], LIFECYCLE)
        self.assertEqual([fact["text"] for fact in records if fact["state"] == "active"], [self.SHORT])

    def test_statements_a_repair_keeps_verbatim_remain_the_leads_own_facts(self):
        client = SyntheticTeamProvider()
        narrowed = "Other invoices go by queue link to Treasury."
        added = "Treasury records Accepted in the queue."
        repaired = " ".join([LIFECYCLE[0], LIFECYCLE[1], narrowed, added, LIFECYCLE[3]])
        repairing(client, "lifecycle", repaired)
        payload, pending = prepared_review(client)
        lead_ids = {fact["text"]: fact["id"] for fact in ledger(client, pending)}
        self.assertEqual(sorted(lead_ids), sorted(LIFECYCLE))
        result = client.coordinator.review(payload)
        records = ledger(client, result)
        active = [fact for fact in records if fact["state"] == "active"]
        self.assertEqual([fact["text"] for fact in active], [LIFECYCLE[0], LIFECYCLE[1], narrowed, added, LIFECYCLE[3]],
                         "The section reads in the order the review published")
        self.assertEqual([fact["origin"] for fact in active], ["lead", "lead", "coverage_repair", "coverage_repair", "lead"])
        for fact in active:
            if fact["origin"] == "lead":
                self.assertEqual(fact["id"], lead_ids[fact["text"]], "An untouched statement keeps its fact and citations")
        self.assertEqual([fact["text"] for fact in records if fact["state"] == "superseded_review"], [LIFECYCLE[2]])
        assembled = finding(facts.findings(client.coordinator._captures[result["capture_token"]]["fact_state"]), "lifecycle")
        self.assertEqual(assembled["answer"].split(), repaired.split())
        self.assertEqual(result["speech_authorization"]["kind"], "final_check")

    def test_a_bulleted_repair_keeps_the_leads_own_facts(self):
        client = SyntheticTeamProvider()
        narrowed = "Other invoices go by queue link to Treasury."
        lines = [LIFECYCLE[0], LIFECYCLE[1], narrowed, LIFECYCLE[3]]
        repairing(client, "lifecycle", "\n".join("- " + line for line in lines))
        payload, pending = prepared_review(client)
        result = client.coordinator.review(payload)
        self.assertEqual(finding(result["memo_findings"], "lifecycle")["answer"], "\n".join(lines))
        records = ledger(client, result)
        self.assertEqual([(fact["text"], fact["origin"]) for fact in records if fact["state"] == "active"],
                         [(lines[0], "lead"), (lines[1], "lead"), (narrowed, "coverage_repair"), (lines[3], "lead")])
        self.assertEqual([fact["text"] for fact in records if fact["state"] == "superseded_review"], [LIFECYCLE[2]])

    def test_hedged_repairs_named_by_the_audit_are_not_published_through_a_review(self):
        for key, hedged in HEDGED_REPAIRS[:6]:
            with self.subTest(key=key, hedged=hedged):
                client = SyntheticTeamProvider()
                repairing(client, key, hedged)
                payload, pending = prepared_review(client)
                before = finding(pending["memo_findings"], key)["answer"]
                result = client.coordinator.review(payload)
                after = finding(result["memo_findings"], key)
                self.assertEqual((after["status"], after["answer"]), ("partial", before))
                self.assertEqual(result["coverage_assessment"]["capture_repairs"], [])
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertEqual(finding(result["coverage"], key)["status"], "partial")
                self.assertEqual(call_names(client).count("process_specialist_review"), 1, "Nothing was repaired, so no further pass")
                done = client.coordinator.interview(reply_payload(payload, result, "No, nothing else."))
                self.assertFalse(done["completion"]["complete"])

    def test_repair_that_drops_a_cited_turn_is_not_published_through_a_review(self):
        client = SyntheticTeamProvider()
        client.turns.append({"id": "u_rework", "role": "user", "text": "A held invoice returns to checking after supplier correction."})
        finding(client.findings, "lifecycle")["evidence_turns"] = ["u_lifecycle", "u_rework"]
        repairing(client, "lifecycle", "The analyst logs each invoice as Received and sends it by queue link to Treasury, which records Accepted.")
        payload, pending = prepared_review(client)
        before = finding(pending["memo_findings"], "lifecycle")
        result = client.coordinator.review(payload)
        after = finding(result["memo_findings"], "lifecycle")
        self.assertEqual((after["answer"], after["evidence_turns"], after["status"]),
                         (before["answer"], ["u_lifecycle", "u_rework"], "partial"))
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        self.assertEqual([fact["state"] for fact in ledger(client, result)], ["active"] * 4)

    def test_repaired_finding_that_differs_from_its_validated_repair_fails_closed(self):
        # The coverage role's bound result is the assessment, and its repairs are validated
        # there. The findings come back beside it; only Coordinator._coverage compares a
        # repaired finding with the repair the assessment records. Each record below
        # carries a valid assessment, so nothing else can reject it.
        repaired = " ".join(self.CHECKS[:3] + ["The analyst keeps the invoice and the approval decision in the AP folder."])
        for label, tamper in (
                ("hedged text", lambda item: item.update(answer="The AP manager probably approves the amount before release.")),
                ("other text", lambda item: item.update(answer="The duty manager approves the amount before release.")),
                ("other citations", lambda item: item.update(evidence_turns=["u_lifecycle"]))):
            with self.subTest(label):
                class TamperingProvider(SyntheticTeamProvider):
                    def assess_coverage(self, findings, *args, **kwargs):
                        revised, assessment = super().assess_coverage(findings, *args, **kwargs)
                        assert [item["key"] for item in assessment["capture_repairs"]] == ["checks"]
                        tamper(finding(revised, "checks"))
                        return revised, assessment
                client = TamperingProvider()
                repairing(client, "checks", repaired)
                payload, pending = prepared_review(client)
                result = client.coordinator.review(payload)
                self.assertTrue(result["review_retry_required"])
                self.assertFalse(result["coverage_verified"])
                self.assertFalse(result["completion"]["ready_for_final_check"])
                checks = finding(result["memo_findings"], "checks")
                self.assertEqual((checks["answer"], checks["evidence_turns"], checks["status"]),
                                 ("\n".join(self.CHECKS), ["u_checks"], "partial"))
                self.assertEqual(next(row["status"] for row in result["agent_team"]["agents"]
                                      if row["role"] == "coverage_reviewer"), "error")
                self.assertEqual([(fact["state"], fact["origin"]) for fact in ledger(client, result, "checks")],
                                 [("active", "lead")] * 4)


class LedgerRepairTests(unittest.TestCase):
    def setUp(self):
        self.context = {"process_name": "Invoice intake"}
        self.turns = [{"id": "u1", "role": "user", "text": "The analyst logs the invoice. Treasury accepts it. I don't know the retention period."}]

    def seeded(self, rows, status="captured"):
        state = facts.empty_state()
        catalog = facts.sources(self.context, self.turns, [])
        for kind, text in rows:
            state["facts"].append(facts._new_fact("lifecycle", kind, text, ["u1"], catalog))
        state["topics"]["lifecycle"].update(status=status, discussed=True)
        return facts._refresh(state)

    def synced(self, state, answer, status="captured"):
        capture = {"memo_findings": [dict(item, status=status, answer=answer, evidence_turns=["u1"])
                                     if item["key"] == "lifecycle" else item for item in facts.findings(state)],
                   "coverage_assessment": {"capture_repairs": [{"key": "lifecycle", "answer": answer, "evidence_turns": ["u1"]}]}}
        return facts.sync_review(state, capture, self.context, self.turns, [])

    def test_only_reworded_statements_are_superseded(self):
        state = self.seeded([("detail", "The analyst logs the invoice."), ("detail", "Treasury accepts it the same day.")])
        ids = [fact["id"] for fact in state["facts"]]
        after = self.synced(state, "The analyst logs the invoice. Treasury accepts it.")
        by_id = {fact["id"]: fact for fact in after["facts"]}
        self.assertEqual(by_id[ids[0]]["state"], "active")
        self.assertEqual(by_id[ids[1]]["state"], "superseded_review")
        active = [fact for fact in after["facts"] if fact["state"] == "active"]
        self.assertEqual([(fact["text"], fact["origin"]) for fact in active],
                         [("The analyst logs the invoice.", "lead"), ("Treasury accepts it.", "coverage_repair")])
        self.assertEqual(finding(facts.findings(after), "lifecycle")["answer"], "The analyst logs the invoice.\nTreasury accepts it.")

    def test_a_two_sentence_fact_is_kept_whole_or_not_at_all(self):
        whole = "The analyst logs the invoice. The analyst then files the email."
        state = self.seeded([("detail", whole), ("detail", "Treasury accepts it.")])
        kept = self.synced(state, "Treasury accepts it. " + whole)
        self.assertEqual([(fact["text"], fact["origin"]) for fact in kept["facts"] if fact["state"] == "active"],
                         [("Treasury accepts it.", "lead"), (whole, "lead")])
        split = self.synced(state, "The analyst logs the invoice. Treasury accepts it. The analyst then files the email.")
        self.assertEqual([(fact["text"], fact["origin"]) for fact in split["facts"] if fact["state"] == "active"],
                         [("The analyst logs the invoice.", "coverage_repair"), ("Treasury accepts it.", "lead"),
                          ("The analyst then files the email.", "coverage_repair")])
        self.assertEqual([fact["text"] for fact in split["facts"] if fact["state"] == "superseded_review"], [whole])

    def test_a_gap_record_is_never_kept_as_a_repaired_statement(self):
        state = self.seeded([("detail", "The analyst logs the invoice."), ("gap", "The retention period is set by the records team.")],
                            status="partial")
        after = self.synced(state, "The analyst logs the invoice. The retention period is set by the records team.")
        active = [fact for fact in after["facts"] if fact["state"] == "active"]
        self.assertEqual([(fact["kind"], fact["origin"]) for fact in active], [("detail", "lead"), ("detail", "coverage_repair")])
        self.assertEqual([fact["kind"] for fact in after["facts"] if fact["state"] == "superseded_review"], ["gap"])

    def test_a_repeated_statement_keeps_one_fact_per_occurrence(self):
        state = self.seeded([("detail", "The analyst logs the invoice.")])
        after = self.synced(state, "The analyst logs the invoice. Treasury accepts it. The analyst logs the invoice.")
        active = [fact for fact in after["facts"] if fact["state"] == "active"]
        self.assertEqual([fact["origin"] for fact in active], ["lead", "coverage_repair", "coverage_repair"])


class ReportRepairTests(unittest.TestCase):
    REPAIRED = "The AP clerk logs each invoice from the shared mailbox in a spreadsheet. A manager approves by email."
    CANDIDATE = ("The AP clerk logs invoices and a manager approves them by email. "
                 "Invoices that do not match the purchase order go to the buyer.")

    def drafted(self, explanation=None, evidence=("u1", "u2"), needed=True):
        payload = interview_payload()
        draft = process_draft()
        finding(draft["memo_summary"], "lifecycle").update(status="captured", answer=self.CANDIDATE, evidence_turns=["u1", "u2"])
        assessment = incomplete_assessment(draft["memo_summary"])
        for local in assessment["topics"]:
            local["capture_repair"] = {"needed": False}
        local = topic(assessment, "lifecycle")
        text = self.REPAIRED if explanation is None else explanation
        local.update(explanation=text, evidence_turns=list(evidence), gaps=[], capture_repair={"needed": needed})
        for dimension in local["dimensions"]:
            dimension.update(status="supported", detail=self.REPAIRED, evidence_turns=list(evidence))
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        replies = {"process_draft": copy.deepcopy(draft), "process_draft_audit": fixture_draft_audit(draft, payload["turns"]),
                   "process_coverage_assessment": assessment}
        client.structured = Mock(side_effect=lambda instructions, body, schema, name, *args, **kwargs: copy.deepcopy(replies[name]))
        return client, client.draft(payload)

    def test_repaired_report_section_is_not_presented_as_covered_and_says_what_changed(self):
        client, result = self.drafted()
        self.assertEqual(sorted({call.args[3] for call in client.structured.call_args_list}),
                         ["process_coverage_assessment", "process_draft", "process_draft_audit"],
                         "The report path makes no further kind of provider call")
        self.assertEqual(client.structured.call_count, 2 + len(server.interview_coverage.COVERAGE_REVIEW_GROUPS),
                         "The topic review runs as its groups at the same time")
        section = finding(result["draft"]["memo_summary"], "lifecycle")
        self.assertEqual(section["answer"], self.REPAIRED)
        self.assertEqual(section["status"], "partial", "No process reviewer reads a report")
        repair = result["coverage_assessment"]["capture_repairs"][0]
        self.assertEqual((repair["key"], repair["previous_answer"], repair["previous_evidence_turns"]),
                         ("lifecycle", self.CANDIDATE, ["u1", "u2"]))
        notes = [note for note in result["draft"]["validation_notes"] if "rewrote" in note]
        self.assertEqual(len(notes), 1)
        self.assertIn(server.COVERAGE["lifecycle"], notes[0])
        self.assertIn("not checked by a process review", notes[0])
        provider_fields = dict(result["draft"])
        route_assurance = provider_fields.pop("route_assurance")
        self.assertIsInstance(route_assurance, list)
        self.assertEqual(len(route_assurance), len(provider_fields["connections"]))
        server.check_schema(provider_fields, server.DRAFT_SCHEMA)

    def test_unrepaired_report_keeps_its_status_and_gets_no_note(self):
        client, result = self.drafted(explanation=self.CANDIDATE, needed=False)
        section = finding(result["draft"]["memo_summary"], "lifecycle")
        self.assertEqual((section["status"], section["answer"]), ("captured", self.CANDIDATE))
        self.assertFalse(any("rewrote" in note for note in result["draft"]["validation_notes"]))
        self.assertEqual(result["coverage_assessment"]["capture_repairs"], [])

    def test_hedged_or_citation_dropping_repair_never_reaches_the_report(self):
        for label, kwargs in (("hedged", {"explanation": "The manager probably approves each invoice by email."}),
                              ("drops u2", {"evidence": ("u1",)})):
            with self.subTest(label=label):
                client, result = self.drafted(**kwargs)
                section = finding(result["draft"]["memo_summary"], "lifecycle")
                self.assertEqual(section["answer"], self.CANDIDATE)
                self.assertEqual(section["evidence_turns"], ["u1", "u2"])
                self.assertEqual(section["status"], "partial")
                self.assertEqual(result["coverage_assessment"]["capture_repairs"], [])
                self.assertFalse(any("rewrote" in note for note in result["draft"]["validation_notes"]))

    def bypassed(self, answer, evidence):
        # A coverage implementation that lets a repair through unchecked: the report
        # path must still run server.validate_findings on what it is about to return.
        payload = interview_payload()
        draft = process_draft()
        finding(draft["memo_summary"], "lifecycle").update(status="captured", answer=self.CANDIDATE, evidence_turns=["u1", "u2"])
        finding(draft["memo_summary"], "checks").update(status="captured", answer="A manager approves by email.", evidence_turns=["u2"])
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        client.structured = Mock(side_effect=[copy.deepcopy(draft), fixture_draft_audit(draft, payload["turns"])])

        def bypass(findings, *args, **kwargs):
            revised = copy.deepcopy(findings)
            finding(revised, "lifecycle").update(answer=answer, evidence_turns=list(evidence))
            return revised, {"topics": [], "all_topics_covered": False, "capture_repairs": [
                {"key": "lifecycle", "answer": answer, "evidence_turns": list(evidence),
                 "previous_answer": self.CANDIDATE, "previous_evidence_turns": ["u1", "u2"]}]}
        client.assess_coverage = bypass
        return client.draft(payload)

    def test_report_runs_the_normal_finding_check_on_the_repaired_summary(self):
        result = self.bypassed("It is assumed that a manager approves each invoice by email.", ["u1", "u2"])
        self.assertEqual(finding(result["draft"]["memo_summary"], "lifecycle")["status"], "partial")
        self.assertEqual(finding(result["draft"]["memo_summary"], "checks")["status"], "captured",
                         "A section the review did not rewrite keeps its status")
        with self.assertRaisesRegex(server.APIError, "missing or non-participant evidence"):
            self.bypassed(self.REPAIRED, ["u1", "u_not_in_the_interview"])


if __name__ == "__main__":
    unittest.main()
