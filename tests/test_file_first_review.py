"""A file added before anything is named or said, and what its participant waits for after adding it.

The first review of such a file judges the file by its own content; its verdict and summary are
published while its observations are still being written; the requests a participant watches
arrive are asked for on the provider's priority tier; and the topic states of the first notes
are shown while the facts are written. Offline: no provider or network call is made.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("file_first_review_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)
spec = importlib.util.spec_from_file_location("file_first_review_service", APP / "document_service.py")
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
from documents import DocumentStore
import agent_team

KEY = "sk-synthetic-file-first-never-real"
HEADER = ("summary", "acknowledgement", "relevance", "relevance_reason", "question", "queries")
SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"note": {"type": "string"}}, "required": ["note"]}


def review(chunks, relevance="relevant"):
    sources = [chunks[0]["id"]] if chunks else []
    return {"summary": "A synthetic procedure for approving invoices.", "acknowledgement": "",
            "relevance": relevance, "relevance_reason": "It describes how invoices are approved.",
            "question": "Who approves an invoice above the limit?" if relevance == "relevant" else "What should I notice?",
            "queries": ["invoice approval"],
            "observations": [{"text": "The file lists approval fields.", "sources": sources}] if sources else [],
            "questions": [], "extracted_text": ""}


def completed(note="ok", **fields):
    return {"id": "resp_synthetic", "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": json.dumps({"note": note})}]}], **fields}


class OpeningFileTests(unittest.TestCase):
    def test_a_file_opens_an_interview_only_when_nothing_was_named_said_or_directed(self):
        blank = {"context": {"process_name": "", "process_owner": "", "objective": "", "background": ""}, "turns": [],
                 "focus": "", "current_question": "", "latest_question": ""}
        self.assertTrue(server.file_opens_interview(blank, {}))
        self.assertTrue(server.file_opens_interview({}, {"analysis": {}}))
        self.assertTrue(server.file_opens_interview(
            {**blank, "turns": [{"id": "d1", "role": "assistant", "text": "Thanks for sharing.", "document_event": True}]}, {}))
        for changed in ({**blank, "context": {"process_name": "Invoice approval"}},
                        {**blank, "context": {"objective": "Document the month-end close."}},
                        {**blank, "turns": [{"id": "u1", "role": "user", "text": "We start with the invoice."}]},
                        {**blank, "latest_question": "What starts this work?"},
                        {"process_name": "Invoice approval", "latest_question": ""}):
            self.assertFalse(server.file_opens_interview(changed, {}), changed)
        for record in ({"analysis": {"purpose": "Use the approval limits."}}, {"analysis": {"purpose_attempted": True}},
                       {"analysis": {"selected_by_participant": True}}, {"analysis": {"parked_by_user": True}}):
            self.assertFalse(server.file_opens_interview(blank, record), record)
        self.assertFalse(server.file_opens_interview(None, {}))

    def _reviewed(self, context, phase="quick", analysis=None):
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        chunks = [{"id": "doc_1_r1", "label": "Rows 1-3", "text": "Step 1: the clerk checks the invoice.", "location": {"row": 1}}]
        record = {"id": "doc_1", "name": "procedure.csv", "kind": "csv", "inventory": {}, "coverage": {}, "analysis": analysis or {}}
        seen = {}

        def structured(instructions, payload, schema, name, max_tokens, **options):
            seen.update(instructions=instructions, payload=payload, options=options)
            return review(chunks)
        with patch.object(client, "structured", side_effect=structured):
            client.analyze_document(context, record, chunks, phase, None, _agent_managed=True)
        return seen

    def test_only_the_first_review_of_an_opening_file_is_told_to_judge_the_file_itself(self):
        blank = {"context": {"process_name": "", "objective": "", "background": ""}, "turns": []}
        opening = self._reviewed(blank)
        self.assertTrue(opening["payload"]["opening_file"])
        self.assertEqual(opening["instructions"], server.DOCUMENT_INSTRUCTIONS + server.OPENING_FILE_INSTRUCTIONS)
        for seen in (self._reviewed({"context": {"process_name": "Invoice approval"}, "turns": []}),
                     self._reviewed(blank, phase="deep"),
                     self._reviewed(blank, analysis={"purpose": "Check the limits.", "purpose_attempted": True})):
            # Every other review is asked exactly what it was asked before.
            self.assertNotIn("opening_file", seen["payload"])
            self.assertEqual(seen["instructions"], server.DOCUMENT_INSTRUCTIONS)

    def test_the_first_review_is_fast_and_the_in_depth_batches_are_not(self):
        blank = {"context": {}, "turns": []}
        self.assertIs(self._reviewed(blank)["options"]["fast"], True)
        self.assertIs(self._reviewed(blank, phase="deep")["options"]["fast"], False)


class HeaderWatchTests(unittest.TestCase):
    def test_the_opening_is_handed_over_once_when_the_observations_begin(self):
        reply = review([{"id": "c1"}])
        text = json.dumps(reply)
        cut = text.index('"observations"')
        got = []
        watch = server.document_header_watch(got.append)
        for end in range(1, cut):
            self.assertFalse(watch(text[:end]))
        self.assertEqual(got, [])
        self.assertTrue(watch(text[:cut + len('"observations":')]))
        self.assertEqual(got, [{key: reply[key] for key in HEADER}])

    def test_wording_that_looks_like_the_next_field_is_not_taken_for_it(self):
        reply = review([{"id": "c1"}])
        reply["summary"] = 'The file quotes a record: {"a": 1, "observations": [] } and then lists its steps.'
        text = json.dumps(reply)
        got = []
        watch = server.document_header_watch(got.append)
        inside = text.index("and then lists")
        self.assertFalse(watch(text[:inside]))
        self.assertEqual(got, [])

    def test_a_reply_in_another_order_is_never_published_early(self):
        got = []
        watch = server.document_header_watch(got.append)
        self.assertTrue(watch('{"relevance":"relevant","summary":"S","observations":['))
        self.assertEqual(got, [])


class HeaderFirstReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DocumentStore(Path(self.temp.name) / "documents")
        self.services = []
        self.scope = self.store.create_scope()

    def tearDown(self):
        for service in self.services:
            service.close()
            service._worker.join(timeout=4)
            self.assertFalse(service._worker.is_alive())
        self.temp.cleanup()

    def service(self, callback):
        instance = service_module.DocumentService(self.store, callback)
        self.services.append(instance)
        instance.session(self.scope, {"context": {"process_name": ""}, "turns": []})
        return instance

    def wait(self, identity, done, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            record = self.store.get(self.scope, identity)
            if done(record.get("analysis") or {}):
                return record
            threading.Event().wait(.01)
        self.fail(f"The review did not settle: {self.store.get(self.scope, identity)}")

    def test_verdict_and_summary_are_published_while_the_observations_are_still_written(self):
        at_header, release = {}, threading.Event()

        def analyze(context, record, chunks, phase, on_header=None):
            reply = review(chunks)
            if phase == "quick":
                self.assertIsNotNone(on_header)
                on_header({key: reply[key] for key in HEADER})
                at_header.update(copy.deepcopy(self.store.get(self.scope, record["id"])["analysis"]))
                release.wait(4)
            return reply
        service = self.service(analyze)
        record = service.upload(self.scope, "procedure.csv", b"step,action\n1,check the invoice\n2,approve it\n")
        self.wait(record["id"], lambda analysis: analysis.get("observations_pending"))
        # The file can be asked about now: nothing the rest of the reply adds changes that.
        self.assertEqual(at_header["disposition"], "relevant")
        self.assertEqual(at_header["phase"], "complete")
        self.assertIs(at_header["question_ready"], True)
        self.assertEqual(at_header["summary"], "A synthetic procedure for approving invoices.")
        self.assertEqual(at_header["question"], "Who approves an invoice above the limit?")
        self.assertEqual(at_header["observations"], [])
        release.set()
        final = self.wait(record["id"], lambda analysis: analysis.get("phase") == "complete" and not analysis.get("observations_pending"))["analysis"]
        self.assertEqual([row["text"] for row in final["observations"]], ["The file lists approval fields."])
        # What identifies the evidence a set of notes was built on is exactly as it was published.
        for key in ("summary", "summary_basis", "summary_at_review_version", "disposition", "relevance", "relevance_reason",
                    "question", "queries", "phase", "review_complete", "reviewed_chunks", "total_chunks", "question_ready"):
            self.assertEqual(final.get(key), at_header.get(key), key)
        self.assertGreater(final["version"], at_header["version"])

    def test_a_file_the_reviewer_is_unsure_of_is_settled_on_its_whole_reply(self):
        at_header = {}

        def analyze(context, record, chunks, phase, on_header=None):
            reply = review(chunks, relevance="unclear")
            on_header({key: reply[key] for key in HEADER})
            at_header.update(copy.deepcopy(self.store.get(self.scope, record["id"])["analysis"]))
            return reply
        service = self.service(analyze)
        record = service.upload(self.scope, "list.csv", b"item\nmilk\n")
        final = self.wait(record["id"], lambda analysis: analysis.get("phase") == "complete")["analysis"]
        self.assertEqual(at_header.get("phase"), "quick")
        self.assertNotIn("disposition", at_header)
        self.assertEqual(final["disposition"], "needs_reason")
        self.assertIs(final["review_stopped"], True)

    def test_an_opening_that_does_not_fit_the_reply_format_changes_nothing(self):
        def analyze(context, record, chunks, phase, on_header=None):
            on_header({"summary": "S", "relevance": "relevant"})
            on_header({**{key: review(chunks)[key] for key in HEADER}, "relevance": "certainly"})
            self.assertEqual(self.store.get(self.scope, record["id"])["analysis"].get("phase"), "quick")
            return review(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, "procedure.csv", b"step,action\n1,check the invoice\n")
        final = self.wait(record["id"], lambda analysis: analysis.get("phase") == "complete")["analysis"]
        self.assertEqual(final["disposition"], "relevant")
        self.assertEqual(final["summary_at_review_version"], 1)

    def test_a_reviewer_that_takes_no_opening_is_called_as_before(self):
        calls = []

        def analyze(context, record, chunks, phase):
            calls.append(phase)
            return review(chunks)
        service = self.service(analyze)
        record = service.upload(self.scope, "procedure.csv", b"step,action\n1,check the invoice\n")
        final = self.wait(record["id"], lambda analysis: analysis.get("phase") == "complete")["analysis"]
        self.assertEqual(calls, ["quick"])
        self.assertNotIn("observations_pending", final)
        self.assertIs(final["question_ready"], True)


class FastTierTests(unittest.TestCase):
    def client(self, **settings):
        return server.OpenAIClient({"OPENAI_API_KEY": KEY, **settings})

    def sent(self, client, **options):
        bodies = []

        def request(path, body, **kwargs):
            bodies.append(copy.deepcopy(body))
            return completed()
        with patch.object(client, "request", side_effect=request):
            client.structured("Instructions.", {"a": 1}, SCHEMA, "process_interview", 100, **options)
        return bodies

    def test_only_a_request_marked_fast_names_the_priority_tier(self):
        client = self.client()
        self.assertNotIn("service_tier", self.sent(client)[0])
        self.assertEqual(self.sent(client, fast=True)[0]["service_tier"], "priority")

    def test_the_setting_switches_the_tier_off_and_refuses_other_values(self):
        self.assertNotIn("service_tier", self.sent(self.client(COLLECTOR_FAST_TIER="off"), fast=True)[0])
        with self.assertRaises(server.SettingsError):
            self.client(COLLECTOR_FAST_TIER="sometimes")

    def test_a_project_without_the_tier_gets_the_same_request_the_ordinary_way_from_then_on(self):
        client, bodies = self.client(), []

        def request(path, body, **kwargs):
            bodies.append(copy.deepcopy(body))
            if "service_tier" in body:
                raise server.APIError("The provider rejected a model parameter or request format.", category="invalid_configuration")
            return completed()
        with patch.object(client, "request", side_effect=request):
            self.assertEqual(client.structured("Instructions.", {"a": 1}, SCHEMA, "process_interview", 100, fast=True), {"note": "ok"})
            self.assertEqual(client.structured("Instructions.", {"a": 1}, SCHEMA, "process_interview", 100, fast=True), {"note": "ok"})
        self.assertEqual(["service_tier" in body for body in bodies], [True, False, False])
        first, second = bodies[0], bodies[1]
        first.pop("service_tier")
        self.assertEqual(first, second)

    def test_any_other_refusal_is_not_retried(self):
        client, calls = self.client(), []

        def request(path, body, **kwargs):
            calls.append(1)
            raise server.APIError("Rate limit.", category="rate_limit", transient=True)
        with patch.object(client, "request", side_effect=request):
            with self.assertRaises(server.APIError):
                client.structured("Instructions.", {"a": 1}, SCHEMA, "process_interview", 100, fast=True)
        self.assertEqual(len(calls), 1)
        self.assertFalse(client._fast_tier_refused)

    def test_the_tier_that_answered_is_recorded_as_a_plain_identifier(self):
        metrics = server.OpenAIClient._usage_metrics(completed(service_tier="fast", model="gpt-synthetic"), {"model": "gpt-synthetic"})
        self.assertEqual(metrics["service_tier"], "fast")
        self.assertNotIn("service_tier", server.OpenAIClient._usage_metrics(completed(service_tier="not a plain id!"), {}))


class ArrivingTopicsTests(unittest.TestCase):
    def run_with_lead(self):
        ledger = agent_team.build_evidence_ledger({"process_name": "Synthetic"}, [])
        return agent_team.TeamRun(ledger) if hasattr(agent_team, "TeamRun") else None

    def test_topic_states_are_reported_only_while_the_lead_is_writing(self):
        team = next(value for name, value in vars(agent_team).items()
                    if isinstance(value, type) and hasattr(value, "set_provisional_topics"))
        run = team(agent_team.build_evidence_ledger({"process_name": "Synthetic"}, []))
        rows = [{"key": "purpose", "status": "partial", "participant_unavailable": False},
                {"key": "volume", "status": "unknown", "participant_unavailable": False},
                {"key": "x" * 60, "status": "partial"}, {"key": "risk", "status": "certain"}, "not a row"]
        self.assertEqual(run.public_status()["provisional_topics"], [])
        seen = {}

        def lead():
            self.assertTrue(run.set_provisional_topics(rows))
            seen.update(run.public_status())
            return {"ok": True}
        run.run_role("lead_interviewer", lead)
        self.assertEqual(seen["provisional_topics"], [{"key": "purpose", "status": "partial"}, {"key": "volume", "status": "unknown"}])
        # The capture has been accepted or refused: the states it wrote on the way are no longer shown.
        self.assertEqual(run.public_status()["provisional_topics"], [])
        self.assertFalse(run.set_provisional_topics([]))
        run.cancel()
        self.assertFalse(run.set_provisional_topics(rows))


if __name__ == "__main__":
    unittest.main()
