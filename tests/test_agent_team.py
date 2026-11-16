"""Offline manager contracts: provenance, honest progress and closure permits."""
import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest

from test_interview_coverage import fixture, coverage

APP = Path(__file__).resolve().parents[1]
if "interview_coverage" not in sys.modules:
    sys.modules["interview_coverage"] = coverage
spec = importlib.util.spec_from_file_location("agent_team_contract", APP / "agent_team.py")
team_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(team_module)


def inputs(confirmed=False):
    findings, raw, turns = fixture()
    if confirmed:
        turns += [{"id": "a_final", "role": "assistant", "text": team_module.FINAL_CHECK_PREFIX + " we missed?"},
                  {"id": "u_final", "role": "user", "text": "No, nothing else. This captures my account."}]
    ledger = team_module.build_evidence_ledger({"process_name": "Invoice intake"}, turns)
    _, assessed = coverage.apply_assessment(findings, raw, turns)
    process = {"summary": "Reported invoice route is described through Treasury acceptance.",
               "evidence_turns": ["u_lifecycle"], "findings": [], "next_question": "",
               "no_material_blockers": True}
    return ledger, assessed, process


def complete_team(confirmed=False, process_blocker=False, include_document=False):
    ledger, assessed, process = inputs(confirmed)
    if process_blocker:
        process["findings"] = [{"id": "P1", "kind": "unclear_handoff", "material": True,
                                "detail": "The reported return does not identify who receives the corrected item.",
                                "evidence_turns": ["u_lifecycle"], "question": "Who receives the corrected invoice?"}]
    run = team_module.TeamRun(ledger, models={role: "synthetic-test-model" for role in team_module.ROLE_CONTRACTS},
                              include_document_analyst=include_document)
    run.run_role("lead_interviewer", lambda: {"question": "What else should this account include?"})
    run.run_role("coverage_reviewer", lambda: assessed)
    run.run_role("process_reviewer", lambda: process)
    return run


class EvidenceLedgerTests(unittest.TestCase):
    def test_revision_tracks_corrections_source_text_and_archival_not_dict_order(self):
        context = {"process_name": "Invoice intake", "objective": "Document work"}
        turns = [{"id": "u1", "role": "user", "text": "The analyst sends the invoice."}]
        docs = [{"id": "doc_1", "text": "Treasury receives the invoice."}]
        original = team_module.build_evidence_ledger(context, turns, docs)
        reordered = team_module.build_evidence_ledger(dict(reversed(list(context.items()))), turns, docs)
        self.assertEqual(original.revision, reordered.revision)
        for change in (lambda: turns[0].update(text="The manager sends the invoice."),
                       lambda: docs[0].update(text="Operations receives the invoice."),
                       lambda: docs[0].update(archived=True)):
            change()
            self.assertNotEqual(original.revision, team_module.evidence_revision(context, turns, docs))
        self.assertEqual(original.snapshot["turns"][0]["text"], "The analyst sends the invoice.")

    def test_returned_snapshot_cannot_rewrite_ledger(self):
        ledger, _, _ = inputs()
        changed = ledger.snapshot
        changed["turns"][0]["text"] = "Fabricated"
        self.assertNotEqual(ledger.snapshot["turns"][0]["text"], "Fabricated")

    def test_assistant_notifications_and_retained_sources_are_not_active_evidence(self):
        turns = [{"id": "u1", "role": "user", "text": "The analyst sends it."},
                 {"id": "a1", "role": "assistant", "text": "The controller probably approves."},
                 {"id": "notice", "role": "user", "text": "File loaded.", "document_event": True}]
        docs = [{"id": "doc_old", "text": "Old rule", "retained_only": True},
                {"id": "doc_current", "text": "Current documented rule"}]
        ledger = team_module.build_evidence_ledger({"objective": "Capture process"}, turns, docs)
        self.assertEqual(ledger.source_ids, {"u1", "doc_current"})

    def test_duplicate_ids_across_roles_and_document_sources_are_rejected(self):
        turns = [{"id": "u1", "role": "user", "text": "Reported fact"}]
        for other in ({"id": "u1", "role": "assistant", "text": "Question"}, turns[0]):
            with self.assertRaises(ValueError):
                team_module.build_evidence_ledger({}, turns + [other])
        with self.assertRaises(ValueError):
            team_module.build_evidence_ledger({}, turns, [{"id": "u1", "text": "File fact"}])


class ProcessReviewerTests(unittest.TestCase):
    def test_material_finding_overrides_false_clear_flag(self):
        run = complete_team(process_blocker=True)
        review = run.results["process_reviewer"]
        self.assertFalse(review["no_material_blockers"])
        permit = team_module.completion_permit(run, current_revision=run.ledger.revision)
        self.assertFalse(permit["ready_for_final_check"])
        self.assertIn("process_blocker:P1", permit["blockers"])

    def test_fabricated_assistant_and_archived_source_ids_are_rejected(self):
        ledger, _, review = inputs()
        for source in ("invented", "a_final", "doc_archived"):
            with self.subTest(source=source):
                invalid = copy.deepcopy(review)
                invalid["findings"] = [{"id": "P1", "kind": "missing_transition", "material": True,
                                        "detail": "A transition is missing.", "evidence_turns": [source],
                                        "question": "What follows the check?"}]
                with self.assertRaises(ValueError):
                    team_module.validate_process_review(invalid, ledger)

    def test_document_claims_can_be_cited_without_becoming_participant_evidence(self):
        ledger = team_module.build_evidence_ledger({}, [], [{"id": "doc_rule", "text": "The proposal recommends approval."}])
        review = {"summary": "The supplied document describes a proposal.", "evidence_turns": ["doc_rule"],
                  "findings": [{"id": "P1", "kind": "unsupported_claim", "material": True,
                                "detail": "Proposed approval has not been established as current practice.",
                                "evidence_turns": ["doc_rule"], "question": "Is that proposal currently followed?"}],
                  "next_question": "Is that proposal currently followed?", "no_material_blockers": False}
        result = team_module.validate_process_review(review, ledger)
        self.assertEqual(result["findings"][0]["evidence_turns"], ["doc_rule"])
        self.assertFalse(result["no_material_blockers"])


class TeamProgressTests(unittest.TestCase):
    def test_deferred_reviewers_are_idle_with_no_fabricated_calls(self):
        ledger, _, _ = inputs()
        run = team_module.TeamRun(ledger)
        run.run_role("lead_interviewer", lambda: {"question": "What happens next?"})
        run.defer_roles(("coverage_reviewer", "process_reviewer"))
        status = run.public_status()
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["budget"]["used_calls"], 1)
        self.assertEqual([row["status"] for row in status["agents"]], ["completed", "idle", "idle"])
        self.assertFalse(team_module.completion_permit(run, current_revision=ledger.revision)["allowed"])

    def test_review_retry_reuses_only_successful_identical_evidence_lead(self):
        ledger, _, _ = inputs()
        original = team_module.TeamRun(ledger)
        original.run_role("lead_interviewer", lambda: {"capture": "retained"})
        retry = team_module.TeamRun(ledger)
        retry.reuse_lead_result(original)
        self.assertEqual(retry.results["lead_interviewer"], {"capture": "retained"})
        self.assertEqual(retry.public_status()["budget"]["used_calls"], 0)
        self.assertEqual(retry.public_status()["agents"][0]["reason_code"], "prior_result_reused")
        with self.assertRaises(ValueError):
            retry.defer_roles(("lead_interviewer",))
        changed = team_module.TeamRun(team_module.build_evidence_ledger({"process_name": "Changed"}, ledger.snapshot["turns"]))
        with self.assertRaises(ValueError):
            changed.reuse_lead_result(original)
        original.cancel()
        with self.assertRaises(ValueError):
            team_module.TeamRun(ledger).reuse_lead_result(original)

    def test_events_describe_actual_execution_without_private_content(self):
        ledger, _, _ = inputs()
        run = team_module.TeamRun(ledger)
        seen = []
        def callback():
            seen.append(run.public_status())
            return {"question": "PRIVATE_OUTPUT_SENTINEL"}
        run.run_role("lead_interviewer", callback)
        self.assertEqual(seen[0]["agents"][0]["status"], "running")
        status = run.public_status()
        self.assertEqual([event["status"] for event in status["events"]], ["running", "completed"])
        self.assertEqual([event["sequence"] for event in status["events"]], [1, 2])
        self.assertNotIn("PRIVATE_OUTPUT_SENTINEL", json.dumps(status))
        self.assertNotIn("invoice", json.dumps(status).lower())
        self.assertEqual(status["agents"][1]["status"], "pending")

    def test_failure_reports_no_exception_or_private_payload(self):
        ledger, _, _ = inputs()
        run = team_module.TeamRun(ledger)
        def fail():
            raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")
        with self.assertRaises(RuntimeError):
            run.run_role("lead_interviewer", fail)
        status = run.public_status()
        self.assertEqual(status["agents"][0]["status"], "error")
        self.assertEqual(status["agents"][0]["reason_code"], "role_failed")
        self.assertNotIn("PRIVATE_EXCEPTION_SENTINEL", json.dumps(status))

    def test_lead_has_two_calls_reviewers_one_and_budget_is_bounded(self):
        ledger, assessment, _ = inputs()
        run = team_module.TeamRun(ledger)
        run.run_role("lead_interviewer", lambda: {"phase": "initial"})
        run.run_role("lead_interviewer", lambda: {"phase": "final"})
        self.assertEqual(run.results["lead_interviewer"]["phase"], "final")
        with self.assertRaises(team_module.TeamBlockedError):
            run.run_role("lead_interviewer", lambda: self.fail("Budget must block this callback"))
        run.run_role("coverage_reviewer", lambda: assessment)
        with self.assertRaises(team_module.TeamBlockedError):
            run.run_role("coverage_reviewer", lambda: self.fail("Reviewer must run at most once"))
        self.assertEqual(run.public_status()["budget"]["used_calls"], 3)

    def test_aggregate_budget_blocks_unstarted_callback(self):
        ledger, _, _ = inputs()
        run = team_module.TeamRun(ledger, max_calls=1)
        run.run_role("lead_interviewer", lambda: {})
        with self.assertRaisesRegex(team_module.TeamBlockedError, "call_budget_exhausted"):
            run.run_role("process_reviewer", lambda: self.fail("No second callback permitted"))
        self.assertEqual(run.public_status()["budget"]["used_calls"], 1)

    def test_cancellation_discards_inflight_and_completed_results(self):
        ledger, assessment, _ = inputs()
        run = team_module.TeamRun(ledger)
        run.run_role("coverage_reviewer", lambda: assessment)
        entered, release = threading.Event(), threading.Event()
        def waiting():
            entered.set()
            self.assertTrue(release.wait(3))
            return {"question": "Should never be applied"}
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run.run_role, "lead_interviewer", waiting)
            self.assertTrue(entered.wait(3))
            run.cancel()
            release.set()
            with self.assertRaisesRegex(team_module.TeamBlockedError, "cancelled"):
                future.result(timeout=3)
        self.assertEqual(run.results, {})
        self.assertEqual(run.public_status()["status"], "blocked")

    def test_revision_change_during_callback_discards_late_result(self):
        ledger, _, _ = inputs()
        run = team_module.TeamRun(ledger)
        current = [ledger.revision]
        def callback():
            current[0] = "a different evidence revision"
            return {"question": "Stale answer"}
        with self.assertRaisesRegex(team_module.TeamBlockedError, "stale_revision"):
            run.run_role("lead_interviewer", callback, current_revision=lambda: current[0])
        self.assertEqual(run.results, {})
        self.assertTrue(run.public_status()["stale"])

    def test_doc_only_run_reports_only_the_work_it_performed(self):
        ledger, _, _ = inputs()
        run = team_module.TeamRun(ledger, roles=("document_analyst",))
        run.run_role("document_analyst", lambda: {"reviewed_source_count": 1})
        self.assertEqual([row["role"] for row in run.public_status()["agents"]], ["document_analyst"])
        self.assertEqual(run.public_status()["status"], "completed")
        permit = team_module.completion_permit(run, current_revision=ledger.revision)
        self.assertFalse(permit["ready_for_final_check"])
        self.assertIn("role_incomplete:coverage_reviewer", permit["blockers"])

    def test_model_configuration_does_not_accept_credential_as_public_metadata(self):
        ledger, _, _ = inputs()
        with self.assertRaises(ValueError):
            team_module.TeamRun(ledger, models={"lead_interviewer": "sk-private-key-sentinel"})


class CompletionPermitTests(unittest.TestCase):
    def test_all_reviews_allow_final_check_but_not_unconfirmed_completion(self):
        run = complete_team()
        permit = team_module.completion_permit(run, current_revision=run.ledger.revision)
        self.assertTrue(permit["ready_for_final_check"])
        self.assertFalse(permit["allowed"])
        self.assertEqual(permit["blockers"], ["confirmation_pending"])

    def test_current_reviews_and_explicit_global_confirmation_allow_completion(self):
        run = complete_team(confirmed=True)
        permit = team_module.completion_permit(run, current_revision=run.ledger.revision, final_confirmation=True)
        self.assertTrue(permit["allowed"])
        self.assertTrue(permit["complete"])
        self.assertFalse(permit["partial"])

    def test_local_no_does_not_become_explicit_global_confirmation(self):
        run = complete_team()
        permit = team_module.completion_permit(run, current_revision=run.ledger.revision, final_confirmation=True)
        self.assertFalse(permit["allowed"])
        self.assertFalse(permit["participant_confirmed"])

    def test_yes_to_omissions_question_means_more_information_not_confirmation(self):
        ledger, assessed, process = inputs(confirmed=True)
        data = ledger.snapshot
        data["turns"][-1]["text"] = "Yes."
        ledger = team_module.build_evidence_ledger(data["context"], data["turns"])
        run = team_module.TeamRun(ledger)
        run.run_role("lead_interviewer", lambda: {})
        run.run_role("coverage_reviewer", lambda: assessed)
        run.run_role("process_reviewer", lambda: process)
        permit = team_module.completion_permit(run, current_revision=ledger.revision, final_confirmation=True)
        self.assertFalse(permit["participant_confirmed"])
        self.assertFalse(permit["ready_for_final_check"])
        self.assertFalse(permit["complete"])
        self.assertIn("participant_has_more_to_add", permit["blockers"])

    def test_explicit_nothing_more_variants_are_accepted_without_accepting_trailing_additions(self):
        ledger, _, _ = inputs(confirmed=True)
        data = ledger.snapshot
        for answer in ("No, that's everything.", "No, that covers it.", "That covers everything.",
                       "No, nothing else to add.", "Nope, that's it.", "That's everything from me.",
                       "Nothing more comes to mind.", "No, nothing else I can think of.",
                       # Hedged and courteous negatives (server-validation-2); the wider
                       # lists are in tests/test_final_confirmation.py.
                       "No, I think that's everything.", "No, I think that's it.", "No, nothing.", "Nothing.",
                       "No thanks.", "No, thank you.", "Nope, we're good.", "No, I don't think so.",
                       "Not that I can think of.", "That's all, thank you.", "No, nothing else. Thanks!"):
            data["turns"][-1]["text"] = answer
            self.assertTrue(team_module.explicit_final_confirmation(
                team_module.build_evidence_ledger(data["context"], data["turns"])), answer)
        for answer in ("No, that covers it. Actually, there is another exception.",
                       "Nothing else, unless the client rejects it.", "Yes, that's all.",
                       "Correct, but one route is missing.", "That's it for the approval step.",
                       "No, I think the controller also signs it.", "No thanks, just add the wire step.",
                       "Not really, but the bank confirms receipt.", "Thank you."):
            data["turns"][-1]["text"] = answer
            self.assertFalse(team_module.explicit_final_confirmation(
                team_module.build_evidence_ledger(data["context"], data["turns"])), answer)

    def test_user_stop_is_partial_even_after_successful_reviews(self):
        run = complete_team(confirmed=True)
        permit = team_module.completion_permit(run, current_revision=run.ledger.revision,
                                               final_confirmation=True, user_stopped=True)
        self.assertFalse(permit["allowed"])
        self.assertFalse(permit["ready_for_final_check"])
        self.assertTrue(permit["partial"])
        self.assertIn("participant_stopped", permit["blockers"])

    def test_stale_results_or_unbound_replacement_assessments_cannot_authorize_closure(self):
        run = complete_team(confirmed=True)
        stale = team_module.completion_permit(run, current_revision="different", final_confirmation=True)
        self.assertFalse(stale["allowed"])
        replacement = run.results["coverage_reviewer"]
        replacement["topics"][0]["explanation"] = "Invented replacement explanation."
        unbound = team_module.completion_permit(run, replacement, current_revision=run.ledger.revision, final_confirmation=True)
        self.assertFalse(unbound["allowed"])
        self.assertIn("coverage_result_unbound", unbound["blockers"])

    def test_every_assessed_dimension_and_document_role_are_required(self):
        ledger, assessment, process = inputs(confirmed=True)
        assessment["topics"][0]["dimensions"].pop()
        run = team_module.TeamRun(ledger, include_document_analyst=True)
        run.run_role("lead_interviewer", lambda: {})
        run.run_role("coverage_reviewer", lambda: assessment)
        run.run_role("process_reviewer", lambda: process)
        permit = team_module.completion_permit(run, current_revision=ledger.revision, final_confirmation=True)
        self.assertFalse(permit["allowed"])
        self.assertIn("coverage_unresolved:name", permit["blockers"])
        self.assertIn("role_incomplete:document_analyst", permit["blockers"])

    def test_metadata_only_coverage_result_cannot_complete_its_role(self):
        ledger, _, _ = inputs()
        run = team_module.TeamRun(ledger)
        with self.assertRaises(ValueError):
            run.run_role("coverage_reviewer", lambda: {"all_topics_covered": True, "topics": [
                {"key": key, "complete": True} for key in coverage.TOPIC_DIMENSIONS]})
        self.assertEqual(run.public_status()["agents"][1]["status"], "error")

    def test_process_result_cannot_be_replaced_with_an_invented_clean_review(self):
        run = complete_team(confirmed=True, process_blocker=True)
        clean = run.results["process_reviewer"]
        clean.update(findings=[], no_material_blockers=True)
        permit = team_module.completion_permit(run, process_review=clean, current_revision=run.ledger.revision,
                                               final_confirmation=True)
        self.assertFalse(permit["allowed"])
        self.assertIn("process_result_unbound", permit["blockers"])


if __name__ == "__main__":
    unittest.main()
