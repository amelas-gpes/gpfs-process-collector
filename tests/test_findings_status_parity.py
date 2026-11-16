"""The browser must show the status the server validated for a memo finding.

The server decides whether a finding is captured (server.validate_findings). The browser normalises
every result again (normalizeFindings in web/app.js) and can only demote; a finding it demotes that
the server accepted is shown, exported and sent back as partial. This suite is the server half of a
parity check on the cases of tests/test_completeness_literals.py: it records what that suite puts
through server.validate_findings and holds tests/fixtures/completeness_literal_cases.json to exactly
that, statuses included. tests/test_findings_status_parity.cjs runs the same fixture through the
browser's own code and expects the same statuses. No provider, browser or network is used.
"""
import json
import unittest
from pathlib import Path

import test_completeness_literals as literals

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "completeness_literal_cases.json"


def recorded_cases():
    """Run the literal suite and return each finding it validated, with the server's status."""
    seen = []

    class Recorder(literals.CompletenessLiteralTests):
        def validate(self, key, answer, documents=None):
            status = super().validate(key, answer, documents)
            row = [key, answer, status, "document" if documents else "answer"]
            if row not in seen:
                seen.append(row)
            return status

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Recorder)
    result = unittest.TestResult()
    suite.run(result)
    return seen, result


class FindingStatusParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        cls.recorded, cls.result = recorded_cases()

    def test_the_literal_suite_itself_passes_while_recorded(self):
        self.assertTrue(self.result.wasSuccessful(), self.result.failures + self.result.errors)
        self.assertGreaterEqual(self.result.testsRun, 12)

    def test_fixture_is_exactly_what_the_literal_suite_validates(self):
        # A case added to test_completeness_literals.py without its fixture row would never reach the
        # browser's code; a fixture row that suite no longer runs would be checked against nothing.
        self.assertEqual(sorted(self.cases), sorted(self.recorded))

    def test_fixture_covers_both_outcomes_and_the_document_only_rule(self):
        statuses = {row[2] for row in self.cases}
        self.assertEqual(statuses, {"captured", "partial"})
        self.assertTrue(any(row[3] == "document" for row in self.cases))
        self.assertGreaterEqual(sum(row[2] == "captured" for row in self.cases), 8)
        self.assertGreaterEqual(sum(row[2] == "partial" for row in self.cases), 15)

    def test_every_case_names_a_real_topic_once(self):
        keys = {finding["key"] for finding in literals.memo_findings()}
        for key, answer, status, source in self.cases:
            with self.subTest(key=key, answer=answer):
                self.assertIn(key, keys)
                self.assertIn(source, ("answer", "document"))
        self.assertEqual(len(self.cases), len({(row[0], row[1], row[3]) for row in self.cases}))

    def test_server_status_of_each_fixture_case(self):
        # Direct, without the recorder: the fixture's status is the server's status today.
        checker = literals.CompletenessLiteralTests("validate")
        for key, answer, status, source in self.cases:
            with self.subTest(key=key, answer=answer):
                documents = [{"id": "doc_literal", "text": answer}] if source == "document" else None
                self.assertEqual(checker.validate(key, answer, documents), status)


if __name__ == "__main__":
    unittest.main()
