"""The draft audit returns its corrections; the application applies them to the candidate.

Measured with the real provider on 2026-11-17: the audit wrote the whole candidate out again
(a median of 14,600 tokens in 163 s), which took longer than writing the draft and left 97 to
99% of its wording as it was. It now returns only what it changes. No provider here.
"""
import copy
import unittest
from unittest.mock import Mock

from test_server import server, interview_payload, process_draft, fixture_draft_audit

draft_audit = server.draft_audit


def corrections(**changes):
    """An audit reply that corrects nothing, with the given fields replaced."""
    empty = {key: ([] if schema.get("type") == "array" else "")
             for key, schema in server.DRAFT_AUDIT_SCHEMA["properties"].items()}
    return {**empty, **changes}


def candidate():
    draft = process_draft()
    first = draft["steps"][0]
    draft["steps"] = [dict(copy.deepcopy(first), id=f"S{n}", title=f"Step {n}") for n in (1, 2, 3)]
    draft["connections"] = [{"from": "S1", "to": "S2", "label": "", "evidence_turns": ["u1"]},
                            {"from": "S2", "to": "S3", "label": "approved", "evidence_turns": ["u2"]}]
    draft["trigger"] = "An invoice arrives"
    draft["inputs"], draft["exceptions"] = ["Invoice", "Purchase order"], ["Missing purchase order"]
    return draft


class MergeTests(unittest.TestCase):
    def test_an_audit_without_corrections_leaves_the_candidate_as_it_is(self):
        draft = candidate()
        merged = draft_audit.merge(draft, corrections())
        for key in draft:
            self.assertEqual(merged[key], draft[key], key)
        self.assertEqual((merged["field_evidence"], merged["route_support"]), ([], []))
        self.assertIsNot(merged["steps"][0], draft["steps"][0], "The candidate itself is never changed")

    def test_a_returned_step_replaces_the_step_with_its_id_and_a_new_one_is_added(self):
        draft = candidate()
        fixed = dict(copy.deepcopy(draft["steps"][1]), actor="UNKNOWN", title="Step 2, corrected")
        added = dict(copy.deepcopy(draft["steps"][0]), id="S9", title="Step 9")
        merged = draft_audit.merge(draft, corrections(steps=[fixed, added]))
        self.assertEqual([step["id"] for step in merged["steps"]], ["S1", "S2", "S3", "S9"])
        self.assertEqual(merged["steps"][1], fixed)
        self.assertEqual(merged["steps"][0], draft["steps"][0])

    def test_an_added_step_stands_where_its_routes_put_it(self):
        draft = candidate()
        start = dict(copy.deepcopy(draft["steps"][0]), id="S0", title="Invoice arrives", type="start")
        check = dict(copy.deepcopy(draft["steps"][0]), id="S9", title="Second check")
        loose = dict(copy.deepcopy(draft["steps"][0]), id="S8", title="Nobody said where")
        merged = draft_audit.merge(draft, corrections(steps=[loose, check, start], connections=[
            {"from": "S0", "to": "S1", "label": "", "evidence_turns": ["u1"]},
            {"from": "S2", "to": "S9", "label": "over the limit", "evidence_turns": ["u2"]}]))
        self.assertEqual([step["id"] for step in merged["steps"]], ["S0", "S1", "S2", "S9", "S3", "S8"])

    def test_the_removal_fields_can_be_used_when_no_participant_has_spoken(self):
        # The wire schema allows no remove_steps or remove_connections without a participant turn (a
        # rule for map updates). A draft made from files alone must still be able to lose a step.
        wire = server.provider_schema.wire_schema(server.route_audit_schema(server.DRAFT_AUDIT_SCHEMA, []), ["doc1"], [], {})
        for field in ("drop_steps", "drop_connections"):
            self.assertNotEqual(wire["properties"][field].get("maxItems"), 0, field)
        self.assertNotIn("remove_steps", server.DRAFT_AUDIT_SCHEMA["properties"])
        self.assertNotIn("remove_connections", server.DRAFT_AUDIT_SCHEMA["properties"])

    def test_a_removed_step_takes_its_connections_and_references_with_it(self):
        draft = candidate()
        draft["variations"] = [{"applies_to": "Client A", "difference": "An extra check", "standard_route_ref": "S3"}]
        merged = draft_audit.merge(draft, corrections(drop_steps=["S3"]))
        self.assertEqual([step["id"] for step in merged["steps"]], ["S1", "S2"])
        self.assertEqual([(edge["from"], edge["to"]) for edge in merged["connections"]], [("S1", "S2")])
        self.assertEqual(merged["variations"][0]["standard_route_ref"], "")

    def test_connections_are_corrected_added_and_removed_by_from_to_and_label(self):
        draft = candidate()
        merged = draft_audit.merge(draft, corrections(
            connections=[{"from": "S1", "to": "S2", "label": "", "evidence_turns": ["u3"]},
                         {"from": "S2", "to": "S3", "label": "approved by the manager", "evidence_turns": ["u2"]},
                         {"from": "S2", "to": "S7", "label": "to a step that does not exist", "evidence_turns": ["u2"]}],
            drop_connections=[{"from": "S2", "to": "S3", "label": "approved"}]))
        self.assertEqual([(edge["from"], edge["to"], edge["label"], edge["evidence_turns"]) for edge in merged["connections"]],
                         [("S1", "S2", "", ["u3"]), ("S2", "S3", "approved by the manager", ["u2"])])

    def test_only_a_named_section_is_replaced(self):
        draft = candidate()
        merged = draft_audit.merge(draft, corrections(changed_sections=["exceptions"], exceptions=[], inputs=["ignored"], overview=""))
        self.assertEqual(merged["exceptions"], [])
        self.assertEqual(merged["inputs"], draft["inputs"])
        self.assertEqual(merged["overview"], draft["overview"])

    def test_a_returned_finding_replaces_the_finding_with_its_key(self):
        draft = candidate()
        key = draft["memo_summary"][0]["key"]
        fixed = dict(copy.deepcopy(draft["memo_summary"][0]), answer="UNKNOWN", status="unknown", evidence_turns=[])
        merged = draft_audit.merge(draft, corrections(memo_summary=[fixed]))
        self.assertEqual([row["key"] for row in merged["memo_summary"]], [row["key"] for row in draft["memo_summary"]])
        self.assertEqual(next(row for row in merged["memo_summary"] if row["key"] == key), fixed)

    def test_field_evidence_is_bound_to_the_entries_as_they_stand(self):
        draft = candidate()
        rows = [{"field": "trigger", "index": 0, "text": "An invoice arrives", "evidence_turns": ["u1"]},
                {"field": "inputs", "index": 0, "text": "Purchase order", "evidence_turns": ["u1"]},   # index of another entry
                {"field": "inputs", "index": 5, "text": "Invoice", "evidence_turns": ["u1"]},          # index out of range
                {"field": "exceptions", "index": 0, "text": "Reworded exception", "evidence_turns": ["u2"]},  # matches nothing
                {"field": "inputs", "index": 1, "text": "Purchase order", "evidence_turns": ["u2"]}]   # a second row for one entry
        merged = draft_audit.merge(draft, corrections(field_evidence=rows))
        self.assertEqual([(row["field"], row["index"], row["text"]) for row in merged["field_evidence"]],
                         [("trigger", 0, "An invoice arrives"), ("inputs", 1, "Purchase order"), ("inputs", 0, "Invoice")])

    def test_a_complete_corrected_draft_is_returned_as_it_is(self):
        draft = candidate()
        complete = fixture_draft_audit(draft, interview_payload()["turns"])
        self.assertIs(draft_audit.merge(draft, complete), complete)


class AuditContractTests(unittest.TestCase):
    def test_the_audit_is_asked_for_corrections_and_both_registers(self):
        fields = set(server.DRAFT_AUDIT_SCHEMA["properties"])
        self.assertTrue({"steps", "drop_steps", "connections", "drop_connections", "changed_sections",
                         "memo_summary", "field_evidence", "route_support"} <= fields)
        self.assertEqual(set(server.DRAFT_AUDIT_SCHEMA["properties"]["changed_sections"]["items"]["enum"]), set(draft_audit.SECTIONS))
        self.assertTrue(set(draft_audit.SECTIONS) <= set(server.DRAFT_SCHEMA["properties"]))
        self.assertEqual(set(draft_audit.SECTIONS) | {"steps", "connections", "memo_summary"}, set(server.DRAFT_SCHEMA["properties"]),
                         "Every part of a draft can be corrected")
        instructions = server.draft_audit_instructions()
        for wording in ("Return your corrections to the candidate, not the candidate again.",
                        "whatever you do not return stays exactly as the candidate has it",
                        "a\n  returned step replaces the candidate step that has the same id",
                        "Return nothing merely to restate or reword it.",
                        "Include route_support for EVERY final draft connection"):
            self.assertIn(wording, instructions)
        self.assertNotIn("Return a corrected draft in the same schema", instructions)

    def test_a_draft_is_the_candidate_with_the_corrections_applied(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        draft = process_draft()
        payload = interview_payload()
        complete = fixture_draft_audit(draft, payload["turns"])
        reply = corrections(route_support=complete["route_support"],
                            field_evidence=[{"field": "trigger", "index": 0, "text": draft["trigger"], "evidence_turns": ["u1"]}],
                            changed_sections=["overview"], overview="Corrected overview.")

        def structured(instructions, body, schema, name, *args, **kwargs):
            if name == "process_draft":
                return copy.deepcopy(draft)
            if name == "process_draft_audit":
                self.assertEqual(schema, server.route_audit_schema(server.DRAFT_AUDIT_SCHEMA, draft["connections"]))
                return copy.deepcopy(reply)
            raise server.APIError("No further scripted reply.", 503)
        client.structured = Mock(side_effect=structured)
        result = client.draft(payload)["draft"]
        self.assertEqual(result["overview"], "Corrected overview.")
        self.assertEqual([step["id"] for step in result["steps"]], [step["id"] for step in draft["steps"]])
        self.assertEqual([step["title"] for step in result["steps"]], [step["title"] for step in draft["steps"]])
        self.assertEqual(result["trigger"], draft["trigger"])
        self.assertNotIn("route_support", result)
        self.assertNotIn("changed_sections", result)


if __name__ == "__main__":
    unittest.main()
