"""The draft keeps the map the participant was shown, where the sources support it.

Measured with the real provider on 2026-11-17. A draft was told to use the working map "only as
a prior interpretation" and re-derived its own: in three interviews it kept 13 of 24, 21 of 31
and 22 of 46 of the working map's routes and 20 of 24, 21 of 28 and 8 of 34 of its steps under
the same id and title, and one draft folded a 27-step map into five steps. With the instruction
below the same interviews kept 23 of 24, 29 of 31 and 33 of 46 routes and 24 of 24, 27 of 28 and
33 of 34 steps. The audit still removes any route the sources do not support. No provider here.
"""
import copy
import unittest
from unittest.mock import Mock

from test_server import server, interview_payload, process_draft, fixture_draft_audit


class DraftKeepsWorkingMapTests(unittest.TestCase):
    def test_the_draft_is_told_to_keep_supported_steps_and_routes_of_the_working_map(self):
        instructions = server.draft_instructions()
        for wording in ("The working map is the map the participant has been shown while answering.",
                        "Keep its step ids, steps and routes wherever the participant turns and authorized excerpts support them",
                        "do not drop or renumber a supported step or route",
                        "Change or leave out a step or route only when the sources contradict it or do not support it",
                        "Describe material differences in validation_notes."):
            self.assertIn(wording, instructions)
        self.assertNotIn("only as a prior interpretation", instructions)
        # The evidence rules the audit enforces are unchanged.
        self.assertIn("Never invent an implied branch", instructions)
        self.assertIn("Every connection must cite its supporting USER turn IDs", instructions)

    def test_a_large_map_is_kept_too_because_the_output_allowance_follows_it(self):
        # A draft told to keep a 60-step map was cut off at a fixed 22,000-token allowance on every
        # attempt (about 380 tokens a step). The allowance now follows the map, up to the 80 steps
        # a draft may have, and the request is given the time that allowance takes to write.
        step = {"id": "S1", "type": "activity", "title": "Do the work"}
        def working_map(count):
            return {"title": "Map", "steps": [dict(step, id=f"S{index + 1}") for index in range(count)], "connections": [], "open_questions": []}
        for count in (1, 27, 36):
            self.assertEqual(server.draft_output_tokens([], (), working_map(count)), server.DRAFT_OUTPUT_TOKENS)
        for count in (50, 60, 80):
            allowance = server.draft_output_tokens([], (), working_map(count))
            self.assertGreaterEqual(allowance, count * 380 * 1.25, "A kept map must fit the draft's output allowance with room to spare")
            self.assertLessEqual(allowance, server.DRAFT_OUTPUT_TOKENS_MAX)
            self.assertGreaterEqual(server.draft_generation_timeout([], (), allowance), allowance / 88)
        for missing in (None, {}, {"steps": None}, "not a map"):
            self.assertEqual(server.draft_output_tokens([], (), missing), server.DRAFT_OUTPUT_TOKENS)
        # A long account without a map (a file on its own) is given room by what was reported.
        long_account = [{"role": "user", "text": "x" * 15000}]
        self.assertGreater(server.draft_output_tokens(long_account), server.DRAFT_OUTPUT_TOKENS)
        self.assertEqual(server.draft_output_tokens([{"role": "user", "text": "x" * 4000}]), server.DRAFT_OUTPUT_TOKENS)
        self.assertEqual(server.draft_output_tokens([], [{"text": "y" * 500000}]), server.DRAFT_OUTPUT_TOKENS_MAX)
        self.assertLessEqual(server.DRAFT_OUTPUT_TOKENS_MAX / 88, server.DRAFT_GENERATION_TIMEOUT_LARGE)

    def test_the_draft_request_carries_that_instruction_and_the_audit_still_follows(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        draft = process_draft()
        seen = []

        def structured(instructions, payload, schema, name, *args, **kwargs):
            seen.append((name, instructions, payload))
            if name == "process_draft":
                return copy.deepcopy(draft)
            if name == "process_draft_audit":
                return fixture_draft_audit(draft, payload["turns"])
            raise server.APIError("No further scripted reply.", 503)
        client.structured = Mock(side_effect=structured)
        result = client.draft(interview_payload())
        self.assertIn("draft", result)
        self.assertEqual([name for name, _, _ in seen[:2]], ["process_draft", "process_draft_audit"])
        self.assertEqual(seen[0][1], server.draft_instructions())
        self.assertIn("working_map", seen[0][2], "The draft request names the working map it was given, also when there is none")
        self.assertIn("proposed_routes_to_verify", seen[1][2], "Every route of the candidate still goes to the audit")


if __name__ == "__main__":
    unittest.main()
