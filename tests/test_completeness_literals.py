"""Finding-level uncertainty distinguishes literal field labels from missing facts."""
import unittest

from test_server import server, memo_findings


class CompletenessLiteralTests(unittest.TestCase):
    def validate(self, key, answer, documents=None):
        findings = memo_findings()
        finding = next(item for item in findings if item["key"] == key)
        finding.update(status="captured", answer=answer,
                       evidence_turns=["doc_literal"] if documents else ["u_literal"])
        # Existing partial fixture facts retain their legitimate user references.
        turns = [{"id": "u1", "role": "user", "text": "The clerk logs invoices."},
                 {"id": "u2", "role": "user", "text": "The manager approves by email."},
                 {"id": "u_literal", "role": "user", "text": answer}]
        server.validate_findings(findings, turns, documents)
        return finding["status"]

    def test_explicit_literal_stage_value_is_not_missing_lifecycle_knowledge(self):
        answer = ("The analyst records the literal value UNKNOWN in the Stage column before "
                  "the reviewer changes it to Approved.")
        self.assertEqual(self.validate("lifecycle", answer), "captured")

    def test_explicit_quoted_literal_stage_value_is_not_missing_lifecycle_knowledge(self):
        for quote in ('"', "'"):
            answer = f"The analyst writes the literal value {quote}UNKNOWN{quote} in the Stage column, then the reviewer changes it to Approved."
            with self.subTest(quote=quote):
                self.assertEqual(self.validate("lifecycle", answer), "captured")

    def test_literal_check_label_is_explained_current_practice(self):
        answer = ("The check displays the literal label UNKNOWN for missing dates; the reviewer "
                  "obtains the date, reruns the check and records Pass before release.")
        self.assertEqual(self.validate("checks", answer), "captured")

    def test_actual_unknown_owner_still_prevents_full_coverage(self):
        for answer in ("The accountable owner is UNKNOWN.", "The accountable owner is 'UNKNOWN'.",
                       'The accountable owner is "UNKNOWN".', "The accountable owner is “UNKNOWN”:",
                       "I don't know who is accountable."):
            with self.subTest(answer=answer):
                self.assertEqual(self.validate("accountable", answer), "partial")

    def test_owner_topic_is_not_closed_by_a_literal_placeholder(self):
        answer = "The overall owner field contains the literal value UNKNOWN."
        self.assertEqual(self.validate("accountable", answer), "partial")

    def test_literal_label_does_not_hide_separate_unresolved_lifecycle_actor(self):
        answer = ("The analyst records the literal value UNKNOWN in the Stage column; "
                  "the person who releases the completed invoice is unknown.")
        self.assertEqual(self.validate("lifecycle", answer), "partial")

    def test_literal_check_label_does_not_hide_missing_approval_knowledge(self):
        answer = ("The check displays the literal label UNKNOWN for missing dates, "
                  "but we don't know who approves the correction.")
        self.assertEqual(self.validate("checks", answer), "partial")

    def test_quote_marks_alone_are_not_evidence_of_a_literal_operational_value(self):
        answer = "Who receives the invoice is 'UNKNOWN'."
        self.assertEqual(self.validate("lifecycle", answer), "partial")

    def test_document_only_literal_fact_cannot_establish_participant_practice(self):
        answer = "The analyst records the literal value UNKNOWN in the Stage column before a reviewer changes it to Approved."
        self.assertEqual(self.validate("lifecycle", answer, [{"id": "doc_literal", "text": answer}]), "partial")

    def test_operational_risk_consequences_are_not_unknown_process_facts(self):
        for answer in (
            "If an incorrect payment file is released, the fund might pay the wrong amount and need a corrected transfer.",
            "A missed bank cut-off is likely to delay settlement to the next business day; the client then receives the revised settlement date.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(self.validate("risk", answer), "captured")

    def test_handled_operational_discrepancies_and_named_records_are_not_epistemic_gaps(self):
        cases = {
            "checks": "When the invoice and order contain conflicting amounts, the reviewer holds release, obtains the buyer's corrected order, reruns the comparison and records Pass before release.",
            "lifecycle": "If the preparer and reviewer disagree on a total, the controller compares the signed source schedule, records the resolved amount and returns the correction to the preparer; the reviewer then reruns the check before release.",
            "materials": "The team retains the disagreement log with each disputed amount, the controller's resolution, the source schedule and the final review timestamp in the event folder.",
        }
        for key, answer in cases.items():
            with self.subTest(key=key):
                self.assertEqual(self.validate(key, answer), "captured")

    def test_operational_words_do_not_hide_separate_authority_or_knowledge_gaps(self):
        cases = [
            ("accountable", "The overall owner is likely the controller."),
            ("accountable", "The controller might be accountable for the result."),
            ("checks", "There are conflicting accounts of who approves the release."),
            ("checks", "There are conflicting approval procedures."),
            ("checks", "We disagree on who approves the release."),
            ("checks", "The reviewer resolves conflicting amounts against the signed schedule, but we do not know who authorizes final release."),
            ("risk", "An incorrect payment might delay settlement, but the person who approves the correction is unknown."),
            ("risk", "The manager is likely responsible for handling the risk."),
            ("risk", "A payment might require the manager's approval."),
            ("materials", "The disagreement log is available, but its current approved version is unknown."),
        ]
        for key, answer in cases:
            with self.subTest(key=key, answer=answer):
                self.assertEqual(self.validate(key, answer), "partial")


if __name__ == "__main__":
    unittest.main()
