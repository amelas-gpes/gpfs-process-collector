"""The Live voice model is told what each memo topic needs, in compact form.

Completion is judged against every dimension of interview_coverage.TOPIC_DIMENSIONS. The
spoken interviewer used to receive one label per topic ("checks: Checks, approvals &
proof") and so could not know which parts of an open topic were still unexplained. It now
receives the name of every dimension, generated from the same table; the explanations of
the dimensions (the review table) stay with the background capture and review. No
provider: only the composed instructions are inspected.
"""
import re
import unittest
from pathlib import Path

from test_server import server


APP = Path(__file__).resolve().parents[1]
DIMENSIONS = server.interview_coverage.TOPIC_DIMENSIONS


def guide_rows(text):
    """topic key -> the dimension names listed for it in the guide line."""
    line = next(line for line in text.splitlines() if line.startswith("INTERNAL COVERAGE TOPICS"))
    body = line.split("): ", 1)[1].rstrip(".")
    rows = {}
    for row in body.split("; "):
        key, names = row.split(": ", 1)
        rows[key] = names.split(", ")
    return line, rows


class LiveTopicGuideTests(unittest.TestCase):
    def test_every_dimension_of_every_topic_is_named_to_the_live_interviewer(self):
        _, rows = guide_rows(server.LIVE_INSTRUCTIONS)
        self.assertEqual(list(rows), list(server.COVERAGE))
        self.assertEqual(sum(map(len, rows.values())), sum(map(len, DIMENSIONS.values())))
        for topic, dimensions in DIMENSIONS.items():
            with self.subTest(topic=topic):
                self.assertEqual(rows[topic], [name.replace("_", " ") for name in dimensions])
        # The dimensions the audit found missing from the spoken interviewer's view of "checks".
        for name in ("thresholds", "segregation", "escalation override", "retained evidence"):
            self.assertIn(name, rows["checks"])

    def test_the_guide_is_generated_from_the_rubric_table(self):
        changed = {**DIMENSIONS, "checks": {**DIMENSIONS["checks"], "sampling_basis": "How the sample is chosen."}}
        _, rows = guide_rows(server.live_topic_guide(changed))
        self.assertEqual(rows["checks"][-1], "sampling basis")
        self.assertEqual(server.live_topic_guide(), server.live_topic_guide(DIMENSIONS))
        self.assertIn(server.live_topic_guide(), server.LIVE_BASE_INSTRUCTIONS)

    def test_the_guide_is_private_and_is_not_a_script(self):
        line, _ = guide_rows(server.LIVE_INSTRUCTIONS)
        heading = line.split("): ", 1)[0]
        self.assertIn("private", heading)
        self.assertRegex(heading, r"never (?:read|a script)")
        self.assertIn("one question", heading)

    def test_the_guide_stays_compact_and_the_review_table_stays_in_the_background(self):
        line, _ = guide_rows(server.LIVE_INSTRUCTIONS)
        self.assertLess(len(line), 2000)
        self.assertLess(len(server.LIVE_INSTRUCTIONS), 17100)
        self.assertNotIn(server.interview_coverage.TOPIC_RUBRIC, server.LIVE_INSTRUCTIONS)
        for topic, dimensions in DIMENSIONS.items():
            for name, explanation in dimensions.items():
                with self.subTest(topic=topic, dimension=name):
                    self.assertNotIn(explanation, server.LIVE_INSTRUCTIONS)

    def test_the_delegate_keeps_the_full_rubric_route_it_had(self):
        # Unchanged by this guide: the delegated reasoning call still receives the foundation.
        self.assertNotIn("INTERNAL COVERAGE TOPICS", server.BASE_INSTRUCTIONS)
        self.assertIn("INTERNAL COVERAGE TOPICS", server.LIVE_BASE_INSTRUCTIONS)


class LiveCoverageDocumentsTests(unittest.TestCase):
    """The documents describe what the spoken interviewer actually receives."""

    def read(self, name):
        return " ".join((APP / name).read_text(encoding="utf-8").split())

    def test_the_foundation_no_longer_promises_the_live_interviewer_the_reviewers_gaps(self):
        text = self.read("FOUNDATION.md")
        self.assertNotIn("Give the live interviewer the same topic rubric and current coverage gaps", text)
        self.assertIn("The live interviewer receives the name of every topic's required dimensions and the topics still open", text)

    def test_the_completeness_guide_says_what_reaches_direct_live_voice(self):
        text = self.read("docs/INTERVIEW_COMPLETENESS.md")
        self.assertNotIn("The same concise rubric reaches typed interviewing, the question auditor, direct live voice", text)
        self.assertIn("Direct live voice receives the names of each topic's dimensions", text)

    def test_the_team_guide_describes_the_silent_note_as_sent(self):
        text = self.read("docs/AGENT_TEAM.md")
        current = re.search(r"2\. After a completed capture \(and on connection\).*?(?= 3\. |$)", text)
        self.assertIsNotNone(current)
        self.assertIn("Private capture status; silent, no speech requested.", current[0])
        self.assertNotIn("When they finish, I ask", current[0].split("Until 0.26.1")[0])
        self.assertIn("Still open:", current[0])


if __name__ == "__main__":
    unittest.main()
