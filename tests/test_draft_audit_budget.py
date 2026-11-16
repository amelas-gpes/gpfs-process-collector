"""The draft audit's output allowance follows the draft it must write out again.

The audit returns the whole candidate draft plus one quoted route_support row per connection, with
more reasoning than the generator. Under the generator's fixed 22,000-token allowance a larger
draft could be generated but never audited. Offline arithmetic and stand-ins only.
"""

import copy
import json
import unittest
from unittest.mock import Mock

from test_server import server, process_draft, interview_payload, fixture_draft_audit


def tokens(value):
    """The estimate the audit of this defect used: about 3.5 characters of JSON per token."""
    return len(json.dumps(value, ensure_ascii=False)) / 3.5


def sized_draft(steps, connections, turns):
    """A candidate of the fixture's own shapes with the given number of steps and connections."""
    draft = process_draft()
    step, edge = draft["steps"][0], draft["connections"][0] if draft["connections"] else None
    draft["steps"] = [{**copy.deepcopy(step), "id": f"s{index}", "title": f"{step['title']} {index}"}
                      for index in range(steps)]
    draft["connections"] = [{**({key: value for key, value in edge.items()} if edge else {}),
                             "from": f"s{index % steps}", "to": f"s{(index * 7 + 1) % steps}",
                             "label": f"Route {index} when the invoice matches the purchase order",
                             "evidence_turns": ["u1", "u2"]} for index in range(connections)]
    return draft, fixture_draft_audit(draft, turns)


class DraftAuditBudget(unittest.TestCase):
    def setUp(self):
        self.turns = interview_payload()["turns"]

    def test_a_small_draft_keeps_the_existing_allowance(self):
        draft = process_draft()
        self.assertEqual(server.draft_audit_output_tokens(draft, draft["connections"]), 22000)
        self.assertEqual(server.draft_audit_output_tokens({}, []), 22000)

    def test_the_allowance_covers_what_the_audit_must_write_with_room_to_reason(self):
        for steps, connections in ((40, 60), (60, 100), (70, 120), (80, 150)):
            with self.subTest(steps=steps, connections=connections):
                draft, audit = sized_draft(steps, connections, self.turns)
                allowance = server.draft_audit_output_tokens(draft, draft["connections"])
                # The reply itself, plus the reserve for medium reasoning that shares the allowance.
                self.assertGreaterEqual(allowance, tokens(audit) + 4000)
                self.assertLessEqual(allowance, server.DRAFT_AUDIT_MAX_TOKENS)

    def test_the_fixed_allowance_was_too_small_inside_the_advertised_limits(self):
        # The defect, on the project's own fixture shapes: the largest draft validate_draft accepts
        # needs more than the 22,000 tokens the audit used to get.
        draft, audit = sized_draft(80, 150, self.turns)
        self.assertGreater(tokens(audit), 22000)
        self.assertLess(tokens(draft), 22000)
        self.assertGreater(server.draft_audit_output_tokens(draft, draft["connections"]), tokens(audit))

    def test_the_allowance_grows_with_the_draft_and_is_bounded(self):
        sizes = [server.draft_audit_output_tokens(*(lambda made: (made, made["connections"]))(
            sized_draft(steps, connections, self.turns)[0])) for steps, connections in ((10, 12), (40, 60), (60, 100), (80, 150))]
        self.assertEqual(sizes, sorted(sizes))
        self.assertGreater(sizes[-1], sizes[0])
        huge = {"overview": "x" * 2_000_000}
        self.assertEqual(server.draft_audit_output_tokens(huge, [{}] * 150), server.DRAFT_AUDIT_MAX_TOKENS)

    def test_text_outside_ascii_is_counted_by_its_encoded_size(self):
        latin = {"overview": "a" * 60000}
        wide = {"overview": "請求書" * 20000}  # the same number of characters, three bytes each
        self.assertGreater(server.draft_audit_output_tokens(wide, []), server.draft_audit_output_tokens(latin, []))

    def test_a_candidate_that_cannot_be_measured_keeps_the_floor(self):
        for candidate in (None, "text", {"steps": {1, 2}}, {"value": float("nan")}):
            with self.subTest(candidate=repr(candidate)[:30]):
                self.assertGreaterEqual(server.draft_audit_output_tokens(candidate, []), 22000)

    def test_draft_gives_the_audit_the_derived_allowance_and_the_generator_its_own(self):
        payload = interview_payload()
        for steps, connections in ((2, 1), (60, 100)):
            with self.subTest(steps=steps):
                candidate, audit = sized_draft(steps, connections, payload["turns"])
                client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-not-a-credential"})
                # The audit reply is not valid for publication here; only the two requests matter.
                client.structured = Mock(side_effect=[copy.deepcopy(candidate), server.APIError("stop after the audit")])
                with self.assertRaises(server.APIError):
                    client.draft(payload)
                generation, review = client.structured.call_args_list
                self.assertEqual((generation.args[3], generation.args[4]), ("process_draft", 22000))
                self.assertEqual(review.args[3], "process_draft_audit")
                self.assertEqual(review.args[4], server.draft_audit_output_tokens(candidate, candidate["connections"]))
                if steps == 60:
                    self.assertGreater(review.args[4], 22000)
                    self.assertGreaterEqual(review.args[4], tokens(audit) + 4000)


if __name__ == "__main__":
    unittest.main()
