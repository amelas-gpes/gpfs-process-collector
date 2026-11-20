"""Live voice holds a notes capture back while the words so far could be a request to stop.

While a long answer is being spoken, the page may send the transcript as it stands for notes
(web/app.js captureMidAnswer). The server reads a request to stop in it (server.stop_request_prefix)
and would answer with its pause reply, so the page holds the capture back while the words read
that way (liveStopInWords). This suite is the server half of a parity check: it holds
tests/fixtures/live_stop_cases.json to server.py, the stop patterns the page is given included.
tests/test_live_notes_mid_answer.cjs runs the page's own code on the same file and expects every
case the server reads as a request to stop to be held back. No provider, browser or network.
"""
import json
import unittest
from pathlib import Path

from test_server import server

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "live_stop_cases.json"


class LiveStopParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_patterns_are_the_ones_the_page_is_given(self):
        # The page receives server.STOP_INTENT_PATTERNS as agent_team.stop_intent_patterns.
        self.assertEqual(self.data["patterns"], list(server.STOP_INTENT_PATTERNS),
                         "server.py's stop patterns changed: copy them into " + FIXTURE.name)

    def test_fixture_records_what_the_server_reads(self):
        rows = [[text, server.stop_request_prefix(text) is not None, page] for text, _, page in self.data["cases"]]
        self.assertEqual(self.data["cases"], rows,
                         "Update " + FIXTURE.name + " cases to:\n" + "\n".join(json.dumps(row, ensure_ascii=False) for row in rows))

    def test_the_page_holds_back_at_least_what_the_server_reads_as_a_stop(self):
        cases = self.data["cases"]
        self.assertTrue(all(page for _, stop, page in cases if stop))
        # The review's cases, which the page's earlier check (the last sentence, split at . ! ?) let through.
        for text in ("The bank file goes out at noon. Okay, I need to stop", "Sorry, I need to stop",
                     "The bank file goes out at noon; I need to stop", "The bank file goes out at noon… I need to stop",
                     "I need to stop now, my boss is calling"):
            self.assertIn([text, True, True], cases)
        # A longer reason before the request, in an earlier sentence: a check of the short clauses
        # that open the words, and of the last sentence, let these through as well.
        for text in ("My boss is calling me now. I need to stop now. The bank file goes out at noon",
                     "I have another meeting in five minutes, so I need to stop now. Thanks. Bye"):
            self.assertIn([text, True, True], cases)
        # Python reads letters, digits and spaces beyond ASCII as such, and its case-blind match
        # takes İ and ı for i and ſ for s; the page's JavaScript did not, and let these through.
        for text in ("The bank file goes out at noon. I have to go because I have another café meeting",
                     "The bank file goes out at noon. I have to go because I have another meeting at \u0663",
                     "The bank file goes out at noon. \u0130 need to stop now",
                     "The bank file goes out at noon. \u0131 need to stop now",
                     "The bank file goes out at noon. I need to \u017ftop now",
                     "The bank file goes out at noon.\x1cI need to stop now",
                     "The bank file goes out at noon. I need to stop now as soon\u00e8 as possible"):
            self.assertIn([text, True, True], cases)
        self.assertGreaterEqual(sum(1 for _, stop, page in cases if not stop and not page), 4,
                                "Ordinary answers are not held back")


if __name__ == "__main__":
    unittest.main()
