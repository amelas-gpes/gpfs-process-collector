"""FOUNDATION.md is written for people; each model call receives the parts it can act on.

The fact-capture call has no field for a step map, a variation record or a memo, and the
application (not that model) closes the interview. Marked parts of the document are left
out of that call only; the draft, the legacy interview and the Live delegate receive the
whole policy as before. No provider: prompts are inspected, and requests are scripted.
"""
import hashlib
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from test_server import server
from test_interview_orchestrator import SyntheticTeamProvider


APP = Path(__file__).resolve().parents[1]
HEADER = "SERVER-OWNED INTERVIEW FOUNDATION"
MARKER = re.compile(r"<!--\s*prompt:(omit\s+[a-z, ]+?|end)\s*-->")


def reader_document():
    return (APP / "FOUNDATION.md").read_text(encoding="utf-8")


def squeezed(text):
    return " ".join(text.split())


class FoundationDocumentTests(unittest.TestCase):
    def test_markers_are_balanced_and_name_known_consumers(self):
        depth = 0
        for match in MARKER.finditer(reader_document()):
            if match[1] == "end":
                depth -= 1
            else:
                depth += 1
                names = {name.strip() for name in match[1].removeprefix("omit").split(",")}
                self.assertLessEqual(names, set(server.FOUNDATION_CONSUMERS), match[0])
            self.assertIn(depth, (0, 1), "Marked parts do not nest and every one is closed")
        self.assertEqual(depth, 0)
        # Nothing else in the document looks like a marker that the parser would miss.
        self.assertEqual(len(re.findall(r"prompt:", reader_document())), len(MARKER.findall(reader_document())))

    def test_the_topic_rows_are_listed_in_key_order(self):
        rows = re.findall(r"^\| (\d+)\. ", reader_document(), flags=re.M)
        self.assertEqual([int(number) for number in rows], list(range(1, len(server.COVERAGE) + 1)))

    def test_the_reader_document_still_reads_whole(self):
        visible = MARKER.sub("", reader_document())
        for text in ("its SHA-256 is", "The live interviewer receives", "checks before closing", "## Deliverables",
                     "Use separate statuses such as answered, unknown, disputed"):
            self.assertIn(text, visible)


class FoundationConsumerTests(unittest.TestCase):
    def test_no_marker_reaches_any_model(self):
        for consumer in server.FOUNDATION_CONSUMERS:
            with self.subTest(consumer=consumer):
                text = server.foundation_instructions(consumer)
                self.assertIn(HEADER, text)
                self.assertNotIn("<!--", text)
                self.assertNotIn("prompt:", text)
                self.assertNotRegex(text, r"\n{3,}")

    def test_the_draft_the_legacy_interview_and_the_live_delegate_receive_the_whole_policy(self):
        whole = squeezed(HEADER + "\n" + MARKER.sub("", reader_document()))
        for consumer in ("draft", "interview", "live"):
            with self.subTest(consumer=consumer):
                self.assertEqual(squeezed(server.foundation_instructions(consumer)), whole)
        self.assertEqual(server.foundation_instructions(), server.foundation_instructions("draft"))

    def test_the_capture_call_is_not_sent_what_it_cannot_act_on(self):
        text = server.foundation_instructions("capture")
        for name, absent in {
                "provenance of the source memorandum": "SHA-256",
                "link for readers": "docs/MEMO_REQUIREMENTS.md",
                "note to developers about the live interviewer": "The live interviewer receives",
                "note about another component": "The independent coverage assessment records",
                "closing steps the application owns": "checks before closing",
                "final completeness question": "Ask a natural final completeness question",
                "confirmation the application records": "Obtain the participant's explicit confirmation",
                "deliverables it does not produce": "## Deliverables",
                "memo format": "under two pages",
                "records it has no field for": "a step/branch map, variation records",
                "statuses its schema does not have": "awaiting evidence"}.items():
            with self.subTest(part=name):
                self.assertNotIn(absent, text)

    def test_the_capture_call_keeps_the_interview_policy(self):
        text = squeezed(server.foundation_instructions("capture"))
        for kept in ("Discover how the work actually runs today.", "Preserve uncertainty.",
                     "Apply the explanation test before awarding coverage",
                     "Always honor an explicit participant stop while keeping incomplete sections open.",
                     "### Purposeful curiosity", "| 7. Checks, approvals and proof |", "| 16. Volume and effort |",
                     "## Main work, branches, variations and possibly separate work", "| Do we charge for it |",
                     "## GPFS discovery and correction checkpoints", "## Detailed process map and procedure appendix",
                     "Handoff recipient, method, required information",
                     "When information conflicts, retain the separate accounts"):
            with self.subTest(kept=kept):
                self.assertIn(kept, text)
        self.assertLess(len(server.foundation_instructions("capture")),
                        len(server.foundation_instructions("draft")) - 3000)

    def test_the_capture_call_is_told_its_own_statuses_and_who_is_who(self):
        notes = server.FOUNDATION_CAPTURE_NOTES
        self.assertIn(notes, server.foundation_instructions("capture"))
        self.assertNotIn(notes, server.foundation_instructions("draft"))
        statuses = server.capture_facts.FACT_DELTA_SCHEMA["properties"]["topic_states"]["items"]["properties"]["status"]["enum"]
        self.assertEqual(sorted(statuses), ["captured", "not_applicable", "partial", "unknown"])
        for status in statuses:
            self.assertIn(status, notes)
        for other in ("answered", "disputed", "awaiting evidence"):
            self.assertNotIn(other + ",", notes)
        self.assertIn('role "user"', notes)
        self.assertIn("participant", notes)
        # The notes come before the reference text they explain.
        text = server.foundation_instructions("capture")
        self.assertLess(text.index(notes), text.index("# Process interviewer foundation"))

    def test_an_unknown_consumer_is_refused(self):
        with self.assertRaises(ValueError):
            server.foundation_instructions("somebody")


class FoundationCacheTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(server._FOUNDATION)
        server._FOUNDATION.clear()
        self.addCleanup(lambda: (server._FOUNDATION.clear(), server._FOUNDATION.update(self.saved)))

    def test_the_file_is_read_once_and_identified_by_its_hash(self):
        real, reads = Path.read_bytes, []

        def counted(path):
            reads.append(path.name)
            return real(path)
        with patch.object(Path, "read_bytes", counted):
            first = server.foundation_instructions("capture")
            for consumer in server.FOUNDATION_CONSUMERS:
                server.foundation_instructions(consumer)
            self.assertEqual(server.foundation_instructions("capture"), first)
        self.assertEqual(reads, ["FOUNDATION.md"])
        self.assertEqual(server.foundation_digest(), hashlib.sha256((APP / "FOUNDATION.md").read_bytes()).hexdigest())

    def test_a_missing_file_is_reported_and_not_remembered(self):
        with patch.object(Path, "read_bytes", side_effect=FileNotFoundError("synthetic")):
            with self.assertRaisesRegex(server.APIError, "Restore FOUNDATION.md") as refused:
                server.foundation_instructions("draft")
        self.assertEqual(refused.exception.status, 503)
        self.assertIn(HEADER, server.foundation_instructions("draft"))


class CapturePromptOrderTests(unittest.TestCase):
    def test_the_fact_contract_comes_before_the_reference_material(self):
        client, seen = SyntheticTeamProvider(), []
        client.hooks["team_interview_capture"] = lambda body: seen.append(body["instructions"])
        client.coordinator.interview(client.payload())
        self.assertEqual(len(seen), 1)
        prompt = seen[0]
        foundation = prompt.index(HEADER)
        for contract in ("Use the supplied fact-transaction schema for this conversational pass.",
                         "Return the fact-transaction schema, not the older full memo_findings response.",
                         "Choose the spoken question AFTER reconciling"):
            with self.subTest(contract=contract):
                self.assertLess(prompt.index(contract), foundation)
        self.assertTrue(prompt.endswith(server.foundation_instructions("capture")))
        self.assertNotIn("## Deliverables", prompt)
        self.assertNotIn("checks before closing", prompt)

    def test_the_draft_calls_still_receive_the_deliverables(self):
        client, seen = server.OpenAIClient({"OPENAI_API_KEY": "fictional"}), []

        def structured(instructions, *args, **kwargs):
            seen.append(instructions)
            raise server.APIError("No scripted reply.", 503)
        client.structured = structured
        from test_server import interview_payload
        with self.assertRaises(server.APIError):
            client.draft(interview_payload())
        self.assertIn("## Deliverables", seen[0])
        self.assertIn("checks before closing", seen[0])


if __name__ == "__main__":
    unittest.main()
