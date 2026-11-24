"""File analysis in seconds: the first notes read the whole file in parallel parts, replies are lean.

Offline. The provider is replaced: by a stub of structured() for the parallel reading, and by a
fake urlopen for the lean wire format (one line, short source names given back in full).
"""

import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("file_reading_speed_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)
file_parts = server.file_parts
capture_facts = server.capture_facts
documents = server.documents

KEY = "sk-synthetic-file-reading-never-real"
DOC = "doc_" + "ab" * 12


def sections(pages, lines=40):
    return [{"id": f"{DOC}_p{page}_c1", "label": f"Procedure.pdf · page {page}",
             "text": "\n".join(f"Page {page} line {number}: the analyst checks record {page}-{number}." for number in range(1, lines + 1)),
             "location": {"page": page}} for page in range(1, pages + 1)]


def supporting(rows):
    excerpts = [{"id": row["id"], "source_id": row["id"], "document_id": DOC, "name": "Procedure.pdf", "label": row["label"],
                 "text": row["text"], "location": row["location"], "page": row["location"]["page"]} for row in rows[:3]]
    return {"documents": [{"id": DOC, "name": "Procedure.pdf", "summary": "A procedure.", "excerpts": excerpts,
                           "observations": [], "questions": [],
                           "context_coverage": {"included_chunks": 3, "total_chunks": len(rows), "complete_text": False}}],
            "retained_evidence": [], "context_budget": {"characters": 0, "chunks": 3}}


class PlanAndJoinTests(unittest.TestCase):
    def setUp(self):
        self.rows = sections(30)
        self.reading = file_parts.plan(supporting(self.rows), {DOC: self.rows})

    def test_the_whole_file_is_split_into_consecutive_parts_with_a_fact_budget(self):
        self.assertIsNotNone(self.reading)
        parts = self.reading["parts"]
        self.assertGreater(len(parts), 1)
        self.assertEqual([row["id"] for _, part in parts for row in part], [row["id"] for row in self.rows],
                         "Every section is read once, in file order")
        whole = self.reading["supporting"]["documents"][0]
        self.assertEqual(len(whole["excerpts"]), 30)
        self.assertTrue(whole["context_coverage"]["complete_text"])
        requests = file_parts.part_requests(self.reading, {"context": {}, "turns": []})
        budgets = [budget for _, _, _, budget in requests]
        self.assertTrue(all(budget >= 2 for budget in budgets))
        payload, suffix, schema, budget = requests[0]
        excerpt = payload["supporting_documents"]["documents"][0]["excerpts"][0]
        self.assertTrue(excerpt["text"].startswith("1| Page 1 line 1"), "Each line is shown with its number")
        self.assertIn(f"Record at most {budget} facts", suffix)
        allowed = schema["properties"]["fact_operations"]["items"]["properties"]["support"]["items"]["properties"]["source_id"]["enum"]
        self.assertEqual(allowed, [row["id"] for row in parts_of(self.reading)[0]], "A part cites only its own sections")

    def test_a_small_file_or_a_huge_one_is_read_the_usual_way(self):
        small = sections(2, lines=5)
        self.assertIsNone(file_parts.plan(supporting(small), {DOC: small}))
        with patch.object(file_parts, "MAX_FILE_CHARS", 1000):
            self.assertIsNone(file_parts.plan(supporting(self.rows), {DOC: self.rows}))

    def test_a_cited_passage_is_cut_from_the_section_word_for_word(self):
        first = self.rows[0]["id"]
        replies = [{"fact_operations": [
            {"topic": "checks", "kind": "detail", "text": "The analyst checks the records.",
             "support": [{"source_id": first, "first_line": 2, "last_line": 3}]},
            {"topic": "checks", "kind": "detail", "text": "A fact citing a line that does not exist.",
             "support": [{"source_id": first, "first_line": 900, "last_line": 901}]},
            {"topic": "lifecycle", "kind": "detail", "text": "A long passage is held to eight lines.",
             "support": [{"source_id": first, "first_line": 1, "last_line": 40}]}]}]
        states = {"topic_states": [{"key": "checks", "status": "unknown", "participant_unavailable": False},
                                   {"key": "risk", "status": "partial", "participant_unavailable": False}]}
        transaction = file_parts.join(self.reading, "rev", replies, [states, {"tag_operations": []}])
        operations = transaction["fact_operations"]
        self.assertEqual(len(operations), 2, "A fact whose passage cannot be found is not recorded")
        self.assertEqual(operations[0]["support"][0]["quote"], "\n".join(self.rows[0]["text"].split("\n")[1:3]))
        self.assertEqual(len(operations[1]["support"][0]["quote"].split("\n")), file_parts.MAX_QUOTE_LINES)
        self.assertEqual(operations[0]["evidence_turns"], [first])
        status = {row["key"]: row["status"] for row in transaction["topic_states"]}
        self.assertEqual(len(transaction["topic_states"]), len(capture_facts.TOPICS), "Every topic is stated exactly once")
        self.assertEqual((status["checks"], status["risk"], status["lifecycle"], status["volume"]),
                         ("partial", "unknown", "partial", "unknown"),
                         "A topic with facts is partial; one with none has nothing to show for it")

    def test_the_same_fact_from_two_neighbouring_parts_is_kept_once(self):
        first, second = self.rows[0]["id"], self.rows[1]["id"]
        for row in self.rows[:2]:
            row["text"] = "Approvals need two signatures before release.\n" + row["text"]
        self.reading = file_parts.plan(supporting(self.rows), {DOC: self.rows})
        replies = [{"fact_operations": [{"topic": "rules", "kind": "detail", "text": "Approvals need two signatures before release.",
                                         "support": [{"source_id": first, "first_line": 1, "last_line": 1}]}]},
                   {"fact_operations": [{"topic": "rules", "kind": "detail", "text": "Approvals need two signatures before release",
                                         "support": [{"source_id": second, "first_line": 1, "last_line": 1}]}]}]
        operations = file_parts.join(self.reading, "rev", replies, [])["fact_operations"]
        self.assertEqual(len(operations), 1)
        self.assertEqual([item["source_id"] for item in operations[0]["support"]], [first, second])
        steps = [{"fact_operations": [{"topic": "lifecycle", "kind": "detail", "text": f"Step {number} is performed by accounts payable.",
                                       "support": [{"source_id": first, "first_line": number, "last_line": number}]}]} for number in (3, 4)]
        self.assertEqual(len(file_parts.join(self.reading, "rev", steps, [])["fact_operations"]), 2,
                         "Two steps worded alike are two facts")

    def test_the_topic_sweep_fills_only_topics_no_part_recorded(self):
        first = self.rows[0]["id"]
        part = {"fact_operations": [{"topic": "risk", "kind": "detail", "text": "A wrong payment is the main exposure.",
                                     "support": [{"source_id": first, "first_line": 1, "last_line": 1}]}]}
        sweep = {"fact_operations": [
            {"topic": "risk", "kind": "detail", "text": "Another account of the risk.", "support": [{"source_id": first, "first_line": 2, "last_line": 2}]},
            {"topic": "volume", "kind": "detail", "text": "About forty events a quarter.", "support": [{"source_id": first, "first_line": 3, "last_line": 3}]}]}
        states = {"topic_states": [{"key": "risk", "status": "partial", "participant_unavailable": False},
                                   {"key": "volume", "status": "partial", "participant_unavailable": False}]}
        self.assertEqual(file_parts.uncovered([part], [states]), ["volume"])
        self.assertEqual(file_parts.uncovered([part, {"fact_operations": [{"topic": "volume"}]}], [states]), [])
        operations = file_parts.join(self.reading, "rev", [part], [states], sweep)["fact_operations"]
        self.assertEqual([(row["topic"], row["text"]) for row in operations],
                         [("risk", "A wrong payment is the main exposure."), ("volume", "About forty events a quarter.")])
        sweep_request = file_parts.sweep_request(self.reading, {"context": {}, "turns": []})
        excerpts = sweep_request[0]["supporting_documents"]["documents"][0]["excerpts"]
        self.assertEqual(len(excerpts), 30, "The sweep reads the whole file")
        with patch.object(file_parts, "SWEEP_MAX_CHARS", 5000):
            opening = file_parts.sweep_request(self.reading, {"context": {}, "turns": []})
        excerpts = opening[0]["supporting_documents"]["documents"][0]["excerpts"]
        self.assertEqual([row["id"] for row in excerpts], [row["id"] for row in self.rows[:len(excerpts)]],
                         "A larger file's sweep reads its opening")
        self.assertLess(len(excerpts), 30)
        self.assertEqual(opening[2]["properties"]["fact_operations"]["items"]["properties"]["support"]["items"]
                         ["properties"]["source_id"]["enum"], [row["id"] for row in excerpts])


def parts_of(reading):
    return [part for _, part in reading["parts"]]


class ParallelReadingThroughTheLedgerTests(unittest.TestCase):
    """The joined reply is checked by the same ledger code as the single request it replaces."""

    def test_the_parts_are_sent_at_once_and_their_facts_are_accepted_with_exact_passages(self):
        rows = sections(30)
        reading = file_parts.plan(supporting(rows), {DOC: rows})
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        evidence = server.document_evidence_catalog(reading["supporting"])
        state = capture_facts.empty_state()
        schema = capture_facts.schema_for(state, capture_facts.sources({}, [], evidence), None, with_question=False)
        calls, lock, together = [], threading.Lock(), threading.Barrier(len(reading["parts"]) + 2, timeout=10)

        def structured(instructions, payload, schema, name, tokens, **options):
            with lock:
                calls.append((name, sorted(schema["properties"])))
            together.wait()  # Every request is in flight before any is answered.
            props = schema["properties"]
            if "fact_operations" in props:
                ids = props["fact_operations"]["items"]["properties"]["support"]["items"]["properties"]["source_id"]["enum"]
                if "TOPIC SWEEP" in instructions:
                    return {"fact_operations": []}
                return {"fact_operations": [{"topic": "lifecycle", "kind": "detail", "text": f"Step on {ident} is performed.",
                                             "support": [{"source_id": ident, "first_line": 1, "last_line": 2}]} for ident in ids[:1]]}
            if "topic_states" in props:
                return {"topic_states": [{"key": "lifecycle", "status": "partial", "participant_unavailable": False}],
                        "summary": "A procedure.", "focus": "The steps", "parking_lot": []}
            return {"tag_operations": [], "connections_out": [], "active_modules": [], "recap_due": "none"}

        topics = []

        class Run:
            def set_provisional_topics(self, rows):
                topics.append(rows)

        client.structured = structured
        transaction = client.coordinator._read_in_parts(Run(), reading, {"context": {}, "turns": [], "action": "start"},
                                                        "Capture.", schema, "model", False)
        self.assertIsNotNone(transaction)
        self.assertEqual(len(calls), len(reading["parts"]) + 2, "Parts and two account-wide requests; no missing topic needs a sweep")
        server.check_schema(transaction, schema)
        delta = copy.deepcopy(transaction)
        capture_facts.normalize_operations(delta, state, capture_facts.sources({}, [], evidence))
        new = capture_facts.apply_delta(state, delta, {}, [], evidence, None, preserve_on_limit=True)
        facts = [fact for fact in new["facts"] if fact["state"] == "active"]
        self.assertEqual(len(facts), len(reading["parts"]))
        self.assertFalse([fact for fact in facts if fact.get("unverified")], "Every passage is the section's own text")

    def test_a_part_that_fails_twice_falls_back_to_the_usual_request(self):
        rows = sections(30)
        reading = file_parts.plan(supporting(rows), {DOC: rows})
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        attempts = []

        def structured(instructions, payload, schema, name, tokens, **options):
            if "PARALLEL READING ASSIGNMENT\nThis file" in instructions and "part 1 of" in instructions:
                attempts.append(1)
                raise server.APIError("A synthetic provider failure.")
            props = schema["properties"]
            if "fact_operations" in props:
                return {"fact_operations": []}
            if "topic_states" in props:
                return {"topic_states": [], "summary": "", "focus": "", "parking_lot": []}
            return {"tag_operations": [], "connections_out": [], "active_modules": [], "recap_due": "none"}

        client.structured = structured
        schema = capture_facts.schema_for(capture_facts.empty_state(), {}, None, with_question=False)

        class Run:
            def set_provisional_topics(self, rows):
                pass
        self.assertIsNone(client.coordinator._read_in_parts(Run(), reading, {"context": {}, "turns": []}, "Capture.", schema, "m", False))
        self.assertEqual(len(attempts), 2, "A failed part is asked for once more before the reading gives way")


class EvidenceBindingTests(unittest.TestCase):
    def test_the_reviewer_s_notes_filling_up_does_not_change_the_evidence(self):
        rows = sections(3)
        base = supporting(rows)
        base["documents"][0]["review"] = {"phase": "deep", "review_complete": False, "limitations": ["Cell text is indexed."]}
        full = copy.deepcopy(base)
        full["documents"][0]["review"].update(phase="complete", limitations=[
            "Cell text is indexed.", "Retained questions reached the 40-item limit; full source chunks remain searchable."])
        self.assertEqual(capture_facts.supporting_identity(base), capture_facts.supporting_identity(full))
        stopped = copy.deepcopy(base)
        stopped["documents"][0]["review"]["limitations"].append("Background review was stopped at your request.")
        self.assertNotEqual(capture_facts.supporting_identity(base), capture_facts.supporting_identity(stopped),
                            "A limitation of what was read still changes the evidence")


class SelectionStaysPutTests(unittest.TestCase):
    def test_the_in_depth_pass_does_not_change_what_a_file_is_searched_for(self):
        merge = server.local_module("document_service", "document_service.py").DocumentService._merge
        record = {"id": DOC}
        reply = {"summary": "S", "acknowledgement": "A", "relevance": "relevant", "relevance_reason": "R", "question": "Q?",
                 "queries": ["capital call"], "observations": [], "questions": [], "extracted_text": ""}
        first = merge({}, reply, record, "quick")
        self.assertEqual(first["opening_queries"], ["capital call"])
        later = merge(first, {**reply, "queries": ["wire release", "callback"]}, record, "deep")
        self.assertEqual(later["queries"][:3], ["capital call", "wire release", "callback"])
        self.assertEqual(later["opening_queries"], ["capital call"], "The fallback search stays the first pass's")


class LeanReplyTests(unittest.TestCase):
    def test_short_source_names_are_handed_out_and_given_back_in_full(self):
        other = "doc_" + "cd" * 12
        body = {"instructions": "Review.", "input": [{"role": "user", "content": json.dumps({"ids": [f"{DOC}_p1_c1", f"{other}_s1_r1_2_b1_c1"]})}],
                "text": {"format": {"type": "json_schema", "schema": {"enum": [f"{DOC}_p1_c1", f"{other}_s1_r1_2_b1_c1"]}}}}
        names = server.ShortSourceNames(body)
        short = names.shorten(body)
        text = json.dumps(short)
        self.assertNotIn(DOC, text)
        self.assertNotIn(other, text)
        self.assertIn("d1_p1_c1", text)
        reply = {"sources": ["d1_p1_c1", "d2_s1_r1_2_b1_c1"], "step": "s_d1_p1_c1", "note": "Odd1_ is not a name."}
        self.assertEqual(names.restore(reply), {"sources": [f"{DOC}_p1_c1", f"{other}_s1_r1_2_b1_c1"],
                                                "step": f"s_{DOC}_p1_c1", "note": "Odd1_ is not a name."})

    def test_a_stand_in_that_already_occurs_in_the_request_is_not_used(self):
        body = {"input": [{"role": "user", "content": f"Row d1_total and {DOC}_p1_c1"}]}
        names = server.ShortSourceNames(body)
        self.assertNotIn("d1_", names.back)
        self.assertEqual(names.restore(json.loads(json.dumps(names.shorten(body)))), body)

    def test_the_wire_request_asks_for_one_line_and_short_names_and_the_reply_comes_back_in_full(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": KEY})
        body = {"model": "m", "instructions": "Review the file.", "input": [{"role": "user", "content": json.dumps({"id": f"{DOC}_p3_c1"})}],
                "text": {"format": {"type": "json_schema", "name": "document_context_review", "strict": True,
                                    "schema": {"type": "object", "properties": {"source": {"type": "string", "enum": [f"{DOC}_p3_c1"]}}}}}}
        sent = []

        def fake(request, timeout):
            sent.append(json.loads(request.data))
            answer = {"status": "completed", "output": [{"content": [{"type": "output_text", "text": '{"source":"d1_p3_c1"}'}]}]}
            return io.BytesIO(json.dumps(answer).encode())
        with patch.object(server.openai_transport, "urlopen", side_effect=fake):
            result = client.request("responses", copy.deepcopy(body))
        wire = sent[0]
        self.assertEqual(wire["instructions"], "Review the file.", "The instructions are sent as written")
        self.assertEqual(wire["input"][-1], {"role": "developer", "content": server.LEAN_REPLY_NOTE})
        self.assertNotIn(DOC, json.dumps(wire))
        self.assertEqual(json.loads(result["output"][0]["content"][0]["text"]), {"source": f"{DOC}_p3_c1"})


class CommentNotesAreNotDrawingsTests(unittest.TestCase):
    def workbook(self, extra_vml=False, image=False):
        from openpyxl import Workbook
        from openpyxl.comments import Comment
        book = Workbook()
        sheet = book.active
        sheet["A1"], sheet["B1"] = "Step", "Owner"
        sheet["A2"], sheet["B2"] = "Approve", "Controller"
        sheet["B2"].comment = Comment("Controller signs off before release.", "Reviewer")
        if image:
            from openpyxl.drawing.image import Image as SheetImage
            from PIL import Image
            picture = Path(tempfile.mkdtemp()) / "mark.png"
            Image.new("RGB", (8, 8), "white").save(picture)
            sheet.add_image(SheetImage(str(picture)), "D4")
        path = Path(tempfile.mkdtemp()) / "book.xlsx"
        book.save(path)
        if extra_vml:
            # Rewrite the comments' VML so it also holds a form control: that drawing is not only notes.
            source, target = path, path.with_name("book2.xlsx")
            with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w") as new:
                for item in old.infolist():
                    data = old.read(item.filename)
                    if item.filename.endswith(".vml"):
                        data = data.replace(b'ObjectType="Note"', b'ObjectType="Button"')
                    new.writestr(item, data)
            path = target
        return path

    def extract(self, path):
        store = documents.DocumentStore(tempfile.mkdtemp())
        scope = store.create_scope()
        scope = scope["scope"] if isinstance(scope, dict) else scope
        record = store.add(scope, "book.xlsx", path.read_bytes())
        return store.extract(scope, record["id"])

    def test_a_sheet_whose_only_drawing_is_its_comment_notes_is_fully_read(self):
        record = self.extract(self.workbook())
        self.assertEqual(record["status"], "ready")
        self.assertEqual((record["coverage"]["indexed_units"], record["coverage"]["total_units"]), (1, 1))
        self.assertEqual(record["inventory"]["sheets"][0].get("comment_count"), 1)
        self.assertNotIn("unread_visual_parts", record["inventory"]["sheets"][0])

    def test_a_drawing_that_holds_more_than_notes_still_counts_as_unread(self):
        record = self.extract(self.workbook(extra_vml=True))
        self.assertIn("vmlDrawing", record["inventory"]["sheets"][0]["unread_visual_parts"])
        self.assertEqual(record["coverage"]["indexed_units"], 0)

    def test_a_picture_beside_a_comment_still_counts_as_unread(self):
        record = self.extract(self.workbook(image=True))
        self.assertIn("drawing", record["inventory"]["sheets"][0]["unread_visual_parts"])


if __name__ == "__main__":
    unittest.main()
