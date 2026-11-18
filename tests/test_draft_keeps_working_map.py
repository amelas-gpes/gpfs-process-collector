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

from test_server import server, interview_payload, process_draft, fixture_draft_audit, fixture_workflow_audit


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


class DraftFromCheckedMapTests(unittest.TestCase):
    def setUp(self):
        self.client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        self.account = interview_payload()
        self.draft = process_draft()
        self.changes = {**self.draft, "steps": [], "connections": [], "drop_steps": [], "drop_connections": []}
        self.requests = []
        self.update = {"title": self.draft["title"], "upsert_steps": self.draft["steps"],
                       "upsert_connections": self.draft["connections"], "remove_steps": [], "remove_connections": [],
                       "open_questions": [], "memo_findings": [], "summary": "", "focus": "", "parking_lot": []}

        def structured(instructions, data, schema, name, *args, **kwargs):
            self.requests.append((name, schema, data))
            if name in ("working_process_map", "team_working_process_map"):
                return copy.deepcopy(self.update)
            if name in ("working_process_map_audit", "team_working_map_source_audit"):
                return fixture_workflow_audit(self.update, data["turns"])
            if name == "process_draft":
                return copy.deepcopy(self.changes if schema is server.DRAFT_FROM_MAP_SCHEMA else self.draft)
            if name == "process_draft_audit":
                return fixture_draft_audit(data["candidate_draft"], data["turns"])
            raise server.APIError("No further scripted reply.", 503)
        self.client.structured = Mock(side_effect=structured)

    def capture(self, result):
        return {key: copy.deepcopy(result[key]) for key in server.WORKFLOW_PREVIOUS_SCHEMA["properties"]}

    def draft_payload(self):
        return {**self.account, "previous_capture": self.capture(self.client.workflow(self.account))}

    def schemas(self):
        return [schema for name, schema, data in self.requests if name == "process_draft"]

    def test_prepared_changes_keep_the_exact_map_and_every_route_is_independently_audited(self):
        payload = self.draft_payload()
        old = copy.deepcopy(payload["previous_capture"]["workflow"])
        self.client.draft(dict(payload, prepare_only=True))
        result = self.client.draft(payload)["draft"]
        self.assertEqual(self.schemas(), [server.DRAFT_FROM_MAP_SCHEMA])
        audit = next(data for name, schema, data in self.requests if name == "process_draft_audit")
        for key in ("steps", "connections"):
            self.assertEqual(audit["candidate_draft"][key], old[key])
            self.assertEqual(result[key], old[key])
        self.assertEqual(audit["proposed_routes_to_verify"], old["connections"])
        self.assertNotIn("drop_steps", result)
        self.assertNotIn("drop_connections", result)

    def test_draw_only_uses_full_draft_until_the_separate_source_check_finishes(self):
        coordinator = self.client.coordinator
        drawn = self.capture(coordinator.workflow_draw(self.account)["capture"])
        self.client.draft(dict(self.account, previous_capture=drawn, prepare_only=True))
        checked = self.capture(coordinator.workflow_check(self.account, drawn))
        self.client.draft(dict(self.account, previous_capture=checked, prepare_only=True))
        self.assertEqual(self.schemas(), [server.DRAFT_SCHEMA, server.DRAFT_FROM_MAP_SCHEMA])

    def test_appended_answers_can_change_kept_work_but_rewritten_sources_or_maps_use_full_drafts(self):
        payload = self.draft_payload()
        newer = copy.deepcopy(payload)
        newer["turns"].append({"id": "u4", "role": "user", "text": "The supervisor approves invoices."})
        changed_step = {**self.draft["steps"][1], "actor": "Supervisor", "evidence_turns": ["u4"]}
        self.changes["steps"] = [changed_step]
        result = self.client.draft(newer)["draft"]
        self.assertEqual([step["actor"] for step in result["steps"]], [self.draft["steps"][0]["actor"], "Supervisor"])
        self.assertEqual(result["steps"][1]["evidence_turns"], ["u4"])
        for change in ("answer", "question", "map", "scope", "context"):
            other = copy.deepcopy(payload)
            if change == "answer":
                other["turns"][1]["text"] += " Correction."
            if change == "question":
                other["turns"][0]["text"] = "What stops the process?"
            if change == "map":
                other["previous_capture"]["workflow"]["steps"][0]["title"] = "Changed in a saved file"
            if change == "scope":
                other["document_scope"] = "different-workspace"
            if change == "context":
                other["context"]["process_owner"] = "Different team"
            other["workflow_checked"] = True  # A browser flag cannot certify a map.
            self.client.draft(dict(other, prepare_only=True))
        self.assertEqual(self.schemas(), [server.DRAFT_FROM_MAP_SCHEMA] + [server.DRAFT_SCHEMA] * 5)

    def test_new_trailing_wrap_up_question_preserves_eligibility(self):
        payload = self.draft_payload()
        payload["turns"].append({"id": "wrapup", "role": "assistant", "text": "Anything else to add?"})
        self.client.draft(dict(payload, prepare_only=True))
        self.assertEqual(self.schemas(), [server.DRAFT_FROM_MAP_SCHEMA])

    def test_document_binding_normalized_legacy_browser_values_and_unchecked_ancestry(self):
        context, turns = server.validate_payload(self.account)
        graph = self.draft_payload()["previous_capture"]["workflow"]
        graph["steps"][0]["evidence_turns"] = ["doc_example"]
        graph["steps"][0]["input"] = ""
        excerpt = {"id": "doc_example", "text": "The clerk logs the invoice."}
        self.client.remember_checked_map({"steps": []}, graph, context, turns, [excerpt], "scope")
        browser = copy.deepcopy(graph)
        for step in browser["steps"]:
            server.gpfs_interview.legacy_defaults(step, server.DRAFT_SCHEMA["properties"]["steps"]["items"])
        browser["steps"][0]["input"] = "UNKNOWN / TBD"
        account = server._map_account(turns)
        def recognized(candidate, evidence):
            return self.client._map_was_checked(server.checked_map_key(candidate, context, turns, evidence, "scope"), account)
        self.assertTrue(recognized(browser, [excerpt]))
        for evidence in ([], [{**excerpt, "text": "Different text"}], [{**excerpt, "retained_only": True}]):
            self.assertFalse(recognized(browser, evidence))
        other = copy.deepcopy(graph)
        other["steps"][0]["title"] = "Unverified ancestor"
        next_map = copy.deepcopy(graph)
        next_map["steps"][0]["actor"] = "Another actor"
        self.client.remember_checked_map(other, next_map, context, turns, [excerpt], "scope")
        self.assertFalse(recognized(next_map, [excerpt]))

    def test_changed_routes_and_steps_include_additions_replacements_and_deletions(self):
        graph = self.draft_payload()["previous_capture"]["workflow"]
        added = {**graph["steps"][0], "id": "new"}
        retained = {**graph["steps"][1], "description": "Updated description"}
        new_route = {**graph["connections"][0], "from": "new", "label": "Submitted"}
        changes = {**self.changes, "steps": [added, retained], "drop_steps": [graph["steps"][0]["id"]],
                   "connections": [new_route], "drop_connections": [
                       {key: graph["connections"][0][key] for key in ("from", "to", "label")}]}
        candidate = server.draft_audit.draft_from_map(graph, changes)
        self.assertEqual(candidate["steps"], [added, retained])
        self.assertEqual(candidate["connections"], [new_route])
        self.assertEqual(graph["steps"][0]["id"], "s1")

    def test_invalid_map_changes_are_not_prepared_or_cached_and_full_replies_still_work(self):
        payload = self.draft_payload()
        for changes in ({"drop_steps": ["missing"]}, {"steps": [self.draft["steps"][1]] * 2},
                        {"steps": [self.draft["steps"][0]], "drop_steps": ["s1"]},
                        {"connections": [{**self.draft["connections"][0], "to": "missing"}]},
                        {"steps": [{**self.draft["steps"][1], "evidence_turns": ["fabricated"]}]},
                        {"steps": [{**self.draft["steps"][1], "rule_source_ref": "u1"}]}):
            with self.subTest(changes=changes):
                self.changes = {**self.draft, "steps": [], "connections": [], "drop_steps": [], "drop_connections": [], **changes}
                with self.assertRaises(server.APIError):
                    self.client.draft(dict(payload, prepare_only=True))
                self.assertFalse(self.client._draft_candidates)
        self.changes = self.draft
        self.assertEqual(self.client.draft(payload)["draft"]["steps"], self.draft["steps"])


if __name__ == "__main__":
    unittest.main()
