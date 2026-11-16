"""Evidence, correction and compatibility acceptance contracts for GPFS capture."""
import copy
import unittest
from test_server import server, process_draft, interview_result, interview_payload
from test_capture_facts import transaction
import capture_facts
import gpfs_interview as gpfs


class GPFSContractTests(unittest.TestCase):
    def setUp(self):
        self.turns = [{"id": "u1", "role": "user", "text": "This is a fund process for one fund. The approved notice comes from capital activity. I use Entrilia."},
                      {"id": "u2", "role": "user", "text": "Correction: this is enterprise internal HR work, not a fund process."}]

    def tag(self, facet="entity_type", value="fund", refs=None):
        return {"op": "add", "target_id": "", "facet": facet, "value": value,
                "note": "Participant-reported scope", "evidence_turns": refs or ["u1"]}

    def test_canonical_sixteen_topics_reach_all_contracts(self):
        expected = set(server.interview_coverage.TOPIC_DIMENSIONS)
        self.assertEqual(len(expected), 16)
        self.assertEqual(expected, set(server.COVERAGE))
        self.assertEqual(expected, set(capture_facts.TOPICS))
        self.assertEqual(expected, set(server.FINDING["properties"]["key"]["enum"]))
        self.assertEqual(expected, {k for group in server.interview_coverage.COVERAGE_REVIEW_GROUPS for k in group})

    def test_live_policy_includes_shared_selection_and_compact_coverage(self):
        self.assertIn(server.QUESTION_SELECTION_POLICY, server.LIVE_INSTRUCTIONS)
        self.assertNotIn(server.interview_coverage.TOPIC_RUBRIC, server.LIVE_INSTRUCTIONS)
        self.assertIn("NATURAL DISCOVERY AND COVERAGE",server.LIVE_INSTRUCTIONS)
        self.assertNotIn("SCOPE AND BOUNDARY ARE THE FIRST PHASE",server.LIVE_INSTRUCTIONS)
        for key in server.COVERAGE:
            self.assertIn(f"{key}:",server.LIVE_INSTRUCTIONS)
        self.assertLess(len(server.LIVE_BASE_INSTRUCTIONS),len(server.BASE_INSTRUCTIONS))

    def test_taxonomy_schema_constrains_each_value_to_its_own_facet(self):
        valid={"facet":"entity_type","value":"fund","note":"Reported", "evidence_turns":["u1"]}
        server.check_schema(valid,gpfs.TAG)
        with self.assertRaises(ValueError):
            server.check_schema({**valid,"value":"manual"},gpfs.TAG)

    def test_legacy_defaults_cannot_fill_unrelated_required_evidence_or_permission_fields(self):
        for key in ("source", "parent_process", "taxonomy", "control_type", "recap_due"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                server.check_schema({},server.obj({key:server.STRING}))

    def test_tag_add_omit_correct_and_source_rewrite_are_evidence_bound(self):
        state = capture_facts.empty_state()
        delta = transaction(state)
        delta["tag_operations"] = [self.tag()]
        state = capture_facts.apply_delta(state, delta, {}, self.turns[:1], [])
        self.assertEqual(state["tags"][0]["value"], "fund")
        same = capture_facts.apply_delta(state, transaction(state), {}, self.turns[:1], [])
        self.assertEqual(same["tags"], state["tags"])
        corrected = transaction(state)
        corrected["tag_operations"] = [{**self.tag(value="enterprise", refs=["u2"]), "op": "replace", "target_id": state["tags"][0]["id"]}]
        revised = capture_facts.apply_delta(state, corrected, {}, self.turns, [])
        self.assertEqual([t["value"] for t in revised["tags"]], ["enterprise"])
        edited = copy.deepcopy(self.turns)
        edited[1]["text"] = "The earlier correction is withdrawn."
        rebased = capture_facts.rebase(revised, {}, edited, [])
        self.assertEqual(rebased["tags"], [])
        self.assertEqual(state["tags"][0]["value"], "fund", "Transactions must not mutate their input")

    def test_invalid_taxonomy_and_assistant_sources_fail_atomically(self):
        state = capture_facts.empty_state()
        for tag in [self.tag(value="imaginary"), self.tag(refs=["a1"]), self.tag(value="other") | {"note": ""}]:
            delta = transaction(state)
            delta["tag_operations"] = [tag]
            with self.assertRaises(ValueError):
                capture_facts.apply_delta(state, delta, {}, self.turns, [])
        self.assertNotIn("tags", state)

    def test_one_interview_cannot_certify_gold_standard(self):
        tag = {k:v for k,v in self.tag("variant_class", "gold_standard", ["u1","u2"]).items() if k not in ("op","target_id")}
        with self.assertRaises(ValueError):
            gpfs.validate_corroboration({"taxonomy": [tag]}, self.turns, [])
        gpfs.validate_corroboration({"taxonomy": [{**tag,"evidence_turns":["u1","doc_rule"]}]}, self.turns, [{"id":"doc_rule"}])

    def test_external_process_leads_are_preserved_and_rebased(self):
        state = capture_facts.empty_state()
        delta = transaction(state)
        delta["connections_out"] = [{"relationship_type":"subprocess_of", "counterpart":"Capital call", "condition":"Approved notice", "evidence_turns":["u1"]}]
        state = capture_facts.apply_delta(state, delta, {}, self.turns[:1], [])
        public = capture_facts.public_capture(state, transaction(state), server.COVERAGE)
        self.assertEqual(public["connections_out"][0]["counterpart"], "Capital call")
        self.assertNotIn("sources", public["connections_out"][0])
        self.assertEqual(capture_facts.rebase(state, {}, [], [])["connections_out"], [])

    def test_old_capture_reopens_with_new_topics_unknown_and_completion_revoked(self):
        value = interview_result()
        value["memo_findings"] = value["memo_findings"][:11]
        value["coverage"] = value["coverage"][:11]
        server.validate_interview(value, interview_payload()["turns"])
        self.assertEqual(len(value["memo_findings"]),16)
        self.assertFalse(value["ready_for_draft"])
        self.assertTrue(all(f["status"]=="unknown" for f in value["memo_findings"][11:]))

    def test_draft_extensions_require_real_source_and_existing_standard_step(self):
        draft = process_draft()
        draft["taxonomy"] = [{"facet":"entity_type","value":"enterprise","note":"Internal AP", "evidence_turns":["u1"]}]
        draft["steps"][0].update(data_origin="Supplier email",entry_mode="manual",control_type=["gpfs_operational"],entity_scope=["enterprise"],parent_process="Procure-to-pay",rule_source_ref="u1")
        draft["variations"] = []
        server.validate_draft(draft, interview_payload()["turns"])
        self.assertEqual(draft["steps"][0]["data_origin"],"Supplier email")
        draft["steps"][0]["rule_source_ref"]="assistant_summary"
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_new_graph_relationships_are_accepted_by_both_owners(self):
        from test_knowledge_ai import mod as ai
        knowledge_graph = server.local_module("knowledge_graph", "knowledge_graph.py")
        for relation in ("subprocess_of","parallel_with","shares_calculation_with"):
            self.assertIn(relation, ai.RELATIONSHIPS)
            self.assertIn(relation, knowledge_graph.RELATIONSHIPS)


if __name__ == "__main__":
    unittest.main()
