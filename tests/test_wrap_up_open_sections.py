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
        self.assertEqual(detail, f" {len(labels)} of {len(server.COVERAGE)} are open; the Notes list shows which.")
        for label in labels:
            self.assertNotIn(label, detail)

    def test_the_wrap_up_reply_keeps_its_prefix_and_its_closing_sentence(self):
        labels = list(server.COVERAGE.values())
        reply = server.PARTIAL_CHECK_PREFIX + server.open_sections_detail(labels) + " You can create a partial draft."
        self.assertTrue(reply.startswith(server.PARTIAL_CHECK_PREFIX))
        self.assertTrue(reply.endswith("You can create a partial draft."))
        self.assertLess(len(reply), 140)


if __name__ == "__main__":
    unittest.main()
