"""Step facts, generating model metadata and owner export use synthetic, cited material."""
import copy
import tempfile
import unittest
from pathlib import Path

from test_server import interview_payload, process_draft, server
from test_knowledge_graph import kg, payload


class StepDetailsTests(unittest.TestCase):
    def setUp(self):
        self.turns = interview_payload()["turns"]
        self.participant = next(turn for turn in self.turns if turn["id"] == "u1")
        self.participant["text"] += " Operations enters the invoice each week in Ledger. Treasury checks the amount."
        self.detail = {"field": "responsible", "text": "Operations enters the invoice", "evidence_turns": ["u1"]}
        self.draft = process_draft()
        self.step = self.draft["steps"][0]
        self.step["operating_details"] = [self.detail]
        self.workflow = {k: self.draft[k] for k in server.WORKFLOW_SCHEMA["properties"]}

    def test_supported_detail_and_legacy_save(self):
        for current, validate in ((self.draft, server.validate_draft), (self.workflow, server.validate_workflow)):
            with self.subTest(validate=validate):
                result = validate(copy.deepcopy(current), self.turns)
                self.assertEqual(result["steps"][0]["operating_details"], [self.detail])
                legacy = copy.deepcopy(current)
                del legacy["steps"][0]["operating_details"]
                self.assertFalse(validate(legacy, self.turns)["steps"][0].get("operating_details"))

    def test_wrong_step_wrong_source_and_invented_role(self):
        for changes in ({"evidence_turns": ["u2"]}, {"evidence_turns": []}, {"text": "Finance approved the invoice."},
                        {"text": "peration"}, {"field": "authority"}, {"text": "a"*501}):
            with self.subTest(changes=changes):
                self.step["operating_details"] = [{**self.detail, **changes}]
                for current, validate in ((self.draft, server.validate_draft), (self.workflow, server.validate_workflow)):
                    with self.assertRaises(ValueError):
                        validate(current, self.turns)

    def test_document_and_context_are_bound_to_their_own_words(self):
        for ref, text in (("context", "Quarterly reconciliation"), ("doc1", "due by Friday")):
            self.step["evidence_turns"].append(ref)
            self.step["operating_details"] = [{"field": "deadline", "text": text, "evidence_turns": [ref]}]
            docs = [{"id": "doc1", "text": "The ledger is due by Friday."}]
            server.validate_workflow(self.workflow, self.turns, docs, context={"background": "Quarterly reconciliation"})
            self.step["operating_details"][0]["evidence_turns"] = ["u1"]
            with self.assertRaisesRegex(ValueError, "must quote"):
                server.validate_workflow(self.workflow, self.turns, docs, context={"background": "Quarterly reconciliation"})

    def test_knowledge_snapshots_retain_validated_facts_and_generation_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = kg.KnowledgeGraph(Path(tmp)/"knowledge.sqlite3")
            try:
                p = payload("Fixture process", self.participant["text"])
                p["draft"]["steps"][0]["operating_details"] = [self.detail]
                p["draft"]["steps"][0]["reviewed_fields"] = ["description","actor"]
                stage = {"stage": "workflow", "model": "fixture-model", "prompt_id": "abc123", "reasoning_effort": "low"}
                p.update(generated_by=[stage], app_version="1.2.3", app_build="dev+123")
                p["draft"]["generated_by"] = [stage]
                receipt = graph.submit(p)
                saved = graph._revision(receipt["submission_id"], 1)
                self.assertEqual(saved["draft"]["steps"][0]["operating_details"], [self.detail])
                self.assertEqual(saved["draft"]["steps"][0]["reviewed_fields"], ["description","actor"])
                self.assertEqual(saved["generated_by"], [stage])
                self.assertEqual(saved["draft"]["generated_by"], [stage])
                self.assertEqual(saved["app_version"], "1.2.3")
                p["draft"]["steps"][0]["reviewed_fields"] = ["approved_by_admin"]
                with self.assertRaisesRegex(ValueError, "editable field"): graph.submit(p)
                del p["draft"]["steps"][0]["reviewed_fields"]
                p["draft"]["steps"][0]["operating_details"][0] = {**self.detail, "text": "invented source"}
                with self.assertRaisesRegex(ValueError, "must quote"): graph.submit(p)
                p["generated_by"] = [{**stage, "submitter": "untrusted"}]
                with self.assertRaisesRegex(ValueError, "identify the stage"): graph.submit(p)
            finally:
                graph.close()
