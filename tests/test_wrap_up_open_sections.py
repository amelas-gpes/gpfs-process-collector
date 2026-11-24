"""What a wrap-up says about the sections that are still open.

Early in an interview most of the sixteen sections are open. The reply named every one of them,
which filled the conversation with a list the Notes panel already shows. It names them while they
are few and gives their number otherwise.
"""
import unittest

from test_server import server


class OpenSectionsDetailTests(unittest.TestCase):
    def test_no_open_section_adds_nothing(self):
        self.assertEqual(server.open_sections_detail([]), "")

    def test_a_few_open_sections_are_named(self):
        labels = [server.COVERAGE["risk"], server.COVERAGE["volume"]]
        self.assertEqual(server.open_sections_detail(labels), f" Still open: {labels[0]}, {labels[1]}.")
        self.assertEqual(server.open_sections_detail(labels, "; "), f" Still open: {labels[0]}; {labels[1]}.")
        limit = list(server.COVERAGE.values())[:server.MAX_OPEN_SECTIONS_NAMED]
        self.assertIn(limit[-1], server.open_sections_detail(limit))

    def test_many_open_sections_are_counted_and_left_to_the_notes_list(self):
        labels = list(server.COVERAGE.values())[:server.MAX_OPEN_SECTIONS_NAMED + 1]
        detail = server.open_sections_detail(labels)
        self.assertEqual(detail, f" {len(server.COVERAGE) - len(labels)} of {len(server.COVERAGE)} topics are complete; the Notes list shows what is missing.")
        for label in labels:
            self.assertNotIn(label, detail)

    def test_the_count_says_how_far_the_account_reaches(self):
        # "11 of 16 are open" told a participant who had given thirteen full answers only what was
        # missing. The count now leads with what is complete and separates a topic that is partly
        # covered from one that has not come up.
        labels = list(server.COVERAGE.values())
        self.assertEqual(server.open_sections_detail(labels[:11], partly=11),
                         " 5 of 16 topics are complete and 11 are partly covered; the Notes list shows what is missing.")
        self.assertEqual(server.open_sections_detail(labels[:15], partly=13),
                         " 1 of 16 topics is complete, 13 are partly covered and 2 have not come up; the Notes list shows what is missing.")
        self.assertEqual(server.open_sections_detail(labels[:15], partly=1),
                         " 1 of 16 topics is complete, 1 is partly covered and 14 have not come up; the Notes list shows what is missing.")
        self.assertEqual(server.open_sections_detail(labels, partly=0),
                         " 0 of 16 topics are complete and 16 have not come up; the Notes list shows what is missing.")
        # A count that cannot be right is left out.
        self.assertEqual(server.open_sections_detail(labels[:6], partly=9), server.open_sections_detail(labels[:6]))

    def test_the_wrap_up_reply_says_the_account_is_saved_and_what_can_be_done(self):
        labels = list(server.COVERAGE.values())
        reply = server.PARTIAL_CHECK_PREFIX + server.open_sections_detail(labels, partly=12) + server.PARTIAL_CHECK_CLOSE
        self.assertTrue(reply.startswith("Your account so far is captured."))
        self.assertTrue(reply.endswith("You can create a draft from what is here, or keep answering."))
        self.assertNotIn("still has open sections", reply)
        self.assertLess(len(reply), 220)
        # It is the application's own closing line, never a question that could be asked again.
        self.assertTrue(server.question_rejection(reply, 1200))


if __name__ == "__main__":
    unittest.main()
