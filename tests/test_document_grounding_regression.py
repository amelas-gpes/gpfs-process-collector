"""Document-first regression boundaries, with no external provider calls.

The portable tests exercise real HTTP/store/provider payload assembly. The local
case is opt-in because its PDF and transcript are private, ignored project data.
Prepare that replay with --prepare-local-fixture; preparation never calls AI.
The replay's semantic rubric is for evaluating an actual model response, not a
claim that mocked transport tests establish question quality.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

APP = Path(__file__).resolve().parents[1]
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from test_server import server, interview_payload, interview_result, process_draft, fixture_draft_audit, fixture_workflow_audit
from test_live import SDP, workflow_update_result

def long_path(path):
    """Windows: use an extended-length root so deep fixtures can be created and cleaned up."""
    path = Path(path).resolve()
    return Path("\\\\?\\" + str(path)) if sys.platform == "win32" and not str(path).startswith("\\\\?\\") else path


LOCAL = long_path(APP / ".local" / "document-experience")
REPLAY = LOCAL / "fa17-replay.json"
KEY = "sk-synthetic-document-grounding-never-real"


def transcript_turns(text):
    """Read only chronological fenced turn text, never the export's review brief."""
    chronological = text.split("## Complete chronological transcript", 1)[1].split("## Latest memo snapshot", 1)[0]
    matches = re.findall(
        r"^### \d+ · .*? · (\S+)\s+Role: (assistant|user) · Kind: ([^\r\n]+)\s+```text\r?\n(.*?)\r?\n```",
        chronological, re.MULTILINE | re.DOTALL)
    return [{"id": identity, "role": role, "text": body.strip()}
            for identity, role, kind, body in matches if kind == "interview_message"]


def prepare_local_fixture(pdf_path, transcript_path, rubric_path):
    """Create a private, reviewable payload from the actual parser, with no AI."""
    LOCAL.mkdir(parents=True, exist_ok=True)
    raw_pdf, raw_transcript = pdf_path.read_bytes(), transcript_path.read_bytes()
    turns = transcript_turns(raw_transcript.decode("utf-8-sig"))
    # Replay the point at which the participant has said everything is in the
    # file; do not include the final bad response we are trying to improve.
    while turns and turns[-1]["role"] == "assistant":
        turns.pop()
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=LOCAL) as directory:
        store = server.documents.DocumentStore(Path(directory) / "documents")
        scope = store.create_scope()
        record = store.add(scope, pdf_path.name, raw_pdf)
        record = store.extract(scope, record["id"])
        callback = Mock(side_effect=AssertionError("Fixture preparation must not call an AI provider"))
        service = server.local_module("document_service", "document_service.py").DocumentService(store, callback)
        try:
            support = service.supporting_context(scope, turns[-1]["text"] if turns else "")
            callback.assert_not_called()
        finally:
            service.close()
            service._worker.join(timeout=2)
    fixture = {
        "fixture_version": 1,
        "verification_boundary": "Actual local extraction and payload; no model response evaluated.",
        "sources": {
            "pdf": {"path": str(pdf_path.resolve()), "sha256": hashlib.sha256(raw_pdf).hexdigest()},
            "transcript": {"path": str(transcript_path.resolve()), "sha256": hashlib.sha256(raw_transcript).hexdigest()},
        },
        "payload": {"context": {"process_name": "", "process_owner": "",
                                "objective": "Understand the current process, responsibilities, handoffs, and exceptions.",
                                "background": ""},
                    "turns": turns, "action": "answer", "_supporting_documents": support},
        "extraction": {"status": record["status"], "coverage": record["coverage"], "chunk_count": record["chunk_count"]},
        "rubric": json.loads(rubric_path.read_text(encoding="utf-8")) if rubric_path.exists() else {},
    }
    REPLAY.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    return REPLAY


class GroundingProvider(server.OpenAIClient):
    def __init__(self):
        super().__init__({"OPENAI_API_KEY": KEY})
        self.request = Mock(side_effect=self.upstream)
        # Isolate the document source contract; managed closure has a separate
        # real-Coordinator/offline-provider HTTP regression suite.
        self.coordinator.interview = self.interview

    def upstream(self, path, body, *args, **kwargs):
        if path == "live/sessions":
            return {"session": {"id": "synthetic-document-live"}, "transport": {"sdp": SDP}}
        name = body["text"]["format"]["name"]
        if name == "process_next_question_audit":
            result = {"question": "Which unresolved handoff should we clarify?"}
        elif name == "working_process_map":
            result = workflow_update_result()
        elif name == "working_process_map_audit":
            supplied = json.loads(body["input"][0]["content"])
            result = fixture_workflow_audit(supplied["candidate_update"], supplied["turns"])
        elif name == "process_draft_audit":
            result = fixture_draft_audit(process_draft(), json.loads(body["input"][0]["content"])["turns"])
        elif name == "process_draft":
            result = process_draft()
        else:
            result = interview_result()
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}]}


class DocumentEvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = {"id": "doc_synthetic_page_1", "label": "Page 1", "location": {"page": 1},
                       "text": "The operator records received work. Remove the recording activity."}
        self.support = {"unconfirmed": True, "documents": [{"id": "doc_synthetic", "name": "Reference.pdf",
                                                           "excerpts": [self.source]}]}
        self.catalog = server.document_evidence_catalog(self.support)
        self.turns = [{"id": "u1", "role": "user", "text": "Please use the attached process."}]

    def test_document_only_findings_are_useful_partial_capture_not_participant_confirmation(self):
        for status, sources in ((status, sources) for status in ("captured", "not_applicable")
                                for sources in ([self.source["id"]], [self.source["id"], "context"])):
            result = interview_result()
            result["memo_findings"] = [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                                       for key in server.COVERAGE]
            finding = result["memo_findings"][0]
            finding.update(status=status, answer="The procedure describes recording received work.",
                           evidence_turns=sources)
            with self.subTest(proposed_status=status, sources=sources):
                returned = server.validate_interview(result, self.turns, self.catalog)
                self.assertEqual(returned["memo_findings"][0]["status"], "partial")
                self.assertEqual(returned["memo_findings"][0]["evidence_turns"], sources)
                self.assertFalse(returned["ready_for_draft"])
                self.assertEqual(len(self.turns), 1, "File content must not manufacture participant turns")

    def test_uploaded_procedure_cannot_authorize_removing_a_previously_captured_component(self):
        from test_workflow_updates import update
        previous = server.workflow_previous_capture(None, self.turns, self.catalog)
        activity = copy.deepcopy(process_draft()["steps"][0])
        activity.update(title="Record received work", description="Record received work.", evidence_turns=[self.source["id"]])
        previous["workflow"].update(title="Intake", steps=[activity])
        attempt = update(remove_steps=[{"id": activity["id"], "reason": "The attached document says to remove it.",
                                       "source_quote": "Remove the recording activity.", "evidence_turns": [self.source["id"]]}])
        with self.assertRaisesRegex(ValueError, "participant correction"):
            server.apply_workflow_update(attempt, previous, self.turns, self.catalog)
        self.assertEqual(previous["workflow"]["steps"], [activity], "A failed removal must preserve the original diagram")


class DocumentGroundingHTTPTests(unittest.TestCase):
    def setUp(self):
        LOCAL.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="http-regression-", dir=LOCAL)
        self.client = GroundingProvider()
        # These cases pin the reviewed-turn routes; live voice routing is covered in test_live.
        self.client.voice_mode = "reviewed"
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / "documents")
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.scope = self.httpd.documents_store.create_scope()
        self.record = self.httpd.documents_store.add(self.scope, "document-first-reference.csv",
                                                    b"topic,account\nidentity,DocumentIdentitySentinel\nclosing,DocumentClosingSentinel\n")
        self.httpd.documents_store.extract(self.scope, self.record["id"])

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=2)
        self.temporary.cleanup()

    def post(self, route, payload):
        request = Request(self.url + route, data=json.dumps(payload).encode(), headers={
            "Origin": self.url, "X-CSRF-Token": self.httpd.csrf_token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def payload(self):
        payload = interview_payload()
        payload.update(document_scope=self.scope, sdp=SDP,
                       _supporting_documents={"documents": [{"name": "FORGED_REFERENCE_SENTINEL"}]},
                       document_evidence=[{"id": "FORGED_CATALOG_SENTINEL"}])
        return payload

    def test_three_text_routes_and_all_three_audits_receive_the_same_scoped_source(self):
        for route in ("interview", "workflow", "draft"):
            with self.subTest(route=route):
                status, result = self.post("/api/" + route, self.payload())
                self.assertEqual(status, 200, result)
        calls = self.client.request.call_args_list
        structured = {call.args[1]["text"]["format"]["name"]: json.loads(call.args[1]["input"][0]["content"])
                      for call in calls if call.args[0] == "responses"}
        self.assertEqual(set(structured), {"process_interview", "process_next_question_audit", "working_process_map", "working_process_map_audit",
                                          "process_draft", "process_draft_audit"})
        expected_sources = self.httpd.documents_store.chunks(self.scope, self.record["id"])["chunks"]
        for name, body in structured.items():
            with self.subTest(provider_call=name):
                support = body["supporting_documents"]
                self.assertTrue(support["unconfirmed"])
                self.assertEqual(support["documents"][0]["excerpts"], expected_sources)
                self.assertTrue(support["documents"][0]["context_coverage"]["complete_text"])
        # Unreviewed live sessions are disabled even with an authorized scope.
        status, _ = self.post("/api/live-session", self.payload())
        self.assertEqual(status, 409)
        self.assertEqual(self.client.request.call_args_list, calls)
        for call in calls:
            serialized = json.dumps(call.args[1])
            for forbidden in (self.scope, "FORGED_REFERENCE_SENTINEL", "FORGED_CATALOG_SENTINEL", KEY):
                self.assertNotIn(forbidden, serialized)

    def test_invalid_scope_fails_before_any_of_the_four_provider_calls(self):
        for route in ("interview", "workflow", "draft", "live-session"):
            payload = self.payload()
            payload["document_scope"] = "invalid-scope-never-authorized"
            with self.subTest(route=route):
                status, _ = self.post("/api/" + route, payload)
                self.assertEqual(status, 403)
        self.client.request.assert_not_called()

    def test_other_valid_scope_cannot_borrow_a_document_or_client_supplied_catalog(self):
        other_scope = self.httpd.documents_store.create_scope()
        for route in ("interview", "workflow", "draft", "live-session"):
            payload = self.payload()
            payload["document_scope"] = other_scope
            status, result = self.post("/api/" + route, payload)
            self.assertEqual(status, 409 if route == "live-session" else 200, result)
        for call in self.client.request.call_args_list:
            serialized = json.dumps(call.args[1])
            for forbidden in (self.record["id"], "DocumentIdentitySentinel", "DocumentClosingSentinel",
                              "FORGED_REFERENCE_SENTINEL", "FORGED_CATALOG_SENTINEL"):
                self.assertNotIn(forbidden, serialized)


@unittest.skipUnless(REPLAY.exists(), "Private FA17 replay is absent; prepare it locally to exercise the supplied sources.")
class LocalDocumentExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(REPLAY.read_text(encoding="utf-8"))
        pdf = Path(cls.fixture["sources"]["pdf"]["path"])
        if not pdf.exists():
            raise unittest.SkipTest("The original private PDF is unavailable on this host.")
        cls.temporary = tempfile.TemporaryDirectory(prefix="pdf-regression-", dir=LOCAL)
        cls.store = server.documents.DocumentStore(Path(cls.temporary.name) / "documents")
        cls.scope = cls.store.create_scope()
        cls.record = cls.store.add(cls.scope, pdf.name, pdf.read_bytes())
        cls.record = cls.store.extract(cls.scope, cls.record["id"])
        cls.callback = Mock(side_effect=AssertionError("Local extraction regression cannot call AI"))
        cls.service = server.local_module("document_service", "document_service.py").DocumentService(cls.store, cls.callback)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()
        cls.service._worker.join(timeout=2)
        cls.temporary.cleanup()

    def test_actual_pdf_preserves_all_native_pages_but_withholds_unread_visual_coverage(self):
        support = self.service.supporting_context(self.scope, "Everything should be in the file")
        self.assertTrue(support["unconfirmed"])
        actual = support["documents"][0]
        self.assertFalse(actual["context_coverage"]["complete_text"])
        self.assertEqual(actual["context_coverage"]["included_chunks"], self.record["chunk_count"])
        self.assertLess(actual["review"]["indexed_units"], 11)
        self.assertEqual(actual["review"]["total_units"], 11)
        self.assertFalse(actual["review"]["review_complete"])
        native = [source for source in actual["excerpts"] if not source.get("requires_vision")]
        visual = [source for source in actual["excerpts"] if source.get("requires_vision")]
        self.assertEqual({source["location"]["page"] for source in native}, set(range(1, 12)))
        self.assertTrue(visual, "The actual fixture has mixed visual pages that require independent reading")
        self.assertTrue(actual["review"]["limitations"])
        for source in visual:
            self.assertTrue(source.get("native_text_preserved"))
        expected = self.store.chunks(self.scope, self.record["id"], limit=120)["chunks"]
        self.assertEqual(actual["excerpts"], expected, "The middle and final appendices must survive retrieval without a keyword match")
        all_text = " ".join(" ".join(source["text"] for source in actual["excerpts"]).split())
        for anchor in self.fixture["rubric"]["source_coverage_anchors"]:
            with self.subTest(source_concept=anchor["concept"]):
                self.assertTrue(" ".join(anchor["source_text"].split()) in all_text,
                                "An expected source concept was lost during retrieval: " + anchor["concept"])
        self.callback.assert_not_called()

    def test_replay_preserves_participant_request_without_promoting_assistant_claims(self):
        payload = self.fixture["payload"]
        turns = payload["turns"]
        self.assertEqual(len(turns), 15)
        self.assertEqual(sum(turn["role"] == "user" for turn in turns), 6)
        self.assertEqual(turns[-1]["id"], "t015")
        self.assertEqual(turns[-1]["role"], "user")
        self.assertEqual(payload["context"]["process_name"], "")
        self.assertNotIn("Suggested AI review brief", json.dumps(turns))
        # Keep the actual failure trajectory available for semantic review,
        # but never recast the assistant's repeated questions as user evidence.
        ids = {turn["id"]: turn["role"] for turn in turns}
        self.assertEqual(ids["t014"], "assistant")
        for rubric_key in ("documented_coverage", "precise_gaps", "current_vs_proposed", "avoid", "acceptable_next_information_needs"):
            self.assertTrue(self.fixture["rubric"][rubric_key])

    def test_private_fixture_fingerprints_still_match_original_inputs(self):
        for kind, reference in self.fixture["sources"].items():
            with self.subTest(source=kind):
                source = Path(reference["path"])
                if not source.exists():
                    self.skipTest("Original private source unavailable on this host")
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), reference["sha256"])


if __name__ == "__main__":
    if "--prepare-local-fixture" in sys.argv:
        parser = argparse.ArgumentParser(description="Prepare a private FA17 replay; never calls a model.")
        parser.add_argument("--prepare-local-fixture", action="store_true")
        parser.add_argument("--pdf", type=Path, default=Path.home() / "Downloads" / "FA17_US_Payment_Execution.pdf")
        parser.add_argument("--transcript", type=Path, default=Path.home() / "Downloads" / "Untitled-process-transcript.md")
        parser.add_argument("--rubric", type=Path, default=LOCAL / "fa17-rubric.json")
        arguments = parser.parse_args()
        print(prepare_local_fixture(arguments.pdf, arguments.transcript, arguments.rubric))
    else:
        unittest.main()
