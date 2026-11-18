"""The questions a reviewer wrote come before the application's own routing questions.

Generated questions about the shape of the map name step ids ("Does any incoming route start
S7 (Enter wire), or must all prerequisites finish?"). They were placed ahead of the questions
a reviewer wrote about the work, so they led the Questions for the process owner list and the
report, while the draft's own notes call its first questions the priority ones. No provider.
"""
import unittest

from test_server import server


OWNER = ["Who approves a payment above the limit?", "What happens to a held payment?"]
ROUTING = ["Does any incoming route start S7 (Enter wire), or must all prerequisites finish?",
           "How does step S9 (File confirmation) connect to the rest of this process, if at all?"]


class OpenQuestionOrderTests(unittest.TestCase):
    def test_generated_questions_follow_the_register_they_are_added_to(self):
        self.assertEqual(server.add_workflow_questions(list(OWNER), ROUTING), OWNER + ROUTING)

    def test_a_question_already_in_the_register_is_not_repeated_or_moved(self):
        existing = [ROUTING[1], *OWNER]
        self.assertEqual(server.add_workflow_questions(existing, ROUTING), existing + [ROUTING[0]])
        self.assertEqual(server.add_workflow_questions(list(OWNER), []), OWNER)
        self.assertEqual(server.add_workflow_questions([], ROUTING + ROUTING), ROUTING)

    def test_a_nearly_full_register_keeps_its_questions_first_and_combines_the_generated_ones(self):
        existing = [f"Owner question {index}?" for index in range(99)]
        combined = server.add_workflow_questions(existing, ROUTING)
        self.assertEqual(combined[:99], existing)
        self.assertEqual(combined[99], " ".join(ROUTING))
        with self.assertRaises(ValueError):
            server.add_workflow_questions([f"Owner question {index}?" for index in range(100)], ROUTING)

    def test_a_drawn_map_lists_its_own_questions_before_the_routing_questions(self):
        steps = [{"id": "S1", "type": "activity", "title": "Prepare"}, {"id": "S2", "type": "activity", "title": "File"}]
        generated = server.workflow_structure_questions(steps, [])
        self.assertTrue(generated)
        register = server.add_workflow_questions(list(OWNER), generated)
        self.assertEqual(register[:len(OWNER)], OWNER)
        self.assertEqual(register[len(OWNER):], generated)


if __name__ == "__main__":
    unittest.main()
