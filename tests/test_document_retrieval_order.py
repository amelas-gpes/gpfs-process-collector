"""Which passages of a reference file reach the interview for the answer just given.

The search runs on the first forty distinct words of its query. Built oldest first, a long
earlier answer used up every place, so the section the participant was now talking about
arrived a turn late or not at all, and the rest of the reading limit was filled from the first
pages. Real handler, real store and index; the interviewer is a recording stand-in. No provider.
"""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("document_retrieval_order_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)
service_module = server.local_module("document_service", "document_service.py")

SECTIONS = 40
VENDOR, CHARGEBACK = 6, 33
# Two realistic turns: a long earlier answer about one subject, then a short one about another.
TURNS = [
    {"id": "t001", "role": "user", "text":
        "We start with vendor onboarding. The procurement clerk collects the W9 tax form and the supplier questionnaire, "
        "and then the vendor record is created in the system by the master data team after a second person has checked "
        "the bank details against the letterhead."},
    {"id": "t002", "role": "assistant", "text": "What happens when a customer disputes a card payment?"},
    {"id": "t003", "role": "user", "text":
        "For chargebacks the treasury analyst opens a dispute case in the acquirer portal and anything above five "
        "thousand is escalated to the treasury director."},
]
CONTEXT = {"process_name": "", "process_owner": "", "objective": "Understand the process.", "background": ""}


def section_rows(number, filler=30):
    rows = [f"Section {number}. Operating manual part {number}."]
    if number == VENDOR:
        rows.append("Vendor onboarding: the procurement clerk collects the W9 tax form and the supplier questionnaire "
                    "before a vendor record is created by the master data team.")
    if number == CHARGEBACK:
        rows.append("Chargeback disputes: the treasury analyst opens a dispute case in the acquirer portal within two days "
                    "and escalates chargebacks above 5000 to the treasury director for written approval.")
    # Ordinary prose: every section contains the usual function words, as real documents do.
    rows.extend(f"In the routine remark {number}-{row} a general note zq{number}x{row} is kept by the team and then it has what we need."
                for row in range(filler))
    return rows


def manual(sections, filler=30):
    lines = ["section,text"]
    for number in sections:
        lines.extend(f'{number},"{row}"' for row in section_rows(number, filler))
    return ("\n".join(lines) + "\n").encode()


class Recorder:
    """Stands where the interviewer would be and keeps what each request was given to read."""

    def __init__(self):
        self.supporting = []

    def public_config(self):
        return {"api_configured": True}

    def browser_connect_sources(self):
        return ()

    def analyze_document(self, context, record, chunks, phase, store):
        raise AssertionError("No file review runs in these tests.")

    def interview(self, payload):
        self.supporting.append(payload["_supporting_documents"])
        return {"question": "What happens next?"}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-retrieval-order-")
        self.addCleanup(self.temporary.cleanup)
        self.client = Recorder()
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / "documents", knowledge_settings={})
        self.addCleanup(self.httpd.server_close)
        worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(self.httpd.shutdown)
        self.store = self.httpd.documents_store
        self.scope = self.store.create_scope()

    def add(self, name, data, analysis=None):
        record = self.store.add(self.scope, name, data, {})
        self.store.extract(self.scope, record["id"])
        if analysis is not None:
            self.store.update(self.scope, record["id"], {"analysis": analysis})
        return self.store.get(self.scope, record["id"])

    def chunks(self, record):
        found, offset = [], 0
        while offset is not None:
            page = self.store.chunks(self.scope, record["id"], offset=offset, limit=500)
            found.extend(page["chunks"])
            offset = page["next_offset"]
        return found

    def interview(self, turns):
        url = f"http://127.0.0.1:{self.httpd.server_port}"
        body = json.dumps({"context": CONTEXT, "turns": turns, "action": "answer", "document_scope": self.scope}).encode()
        request = Request(url + "/api/interview", data=body, headers={
            "Origin": url, "X-CSRF-Token": self.httpd.csrf_token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=20) as response:
                self.assertEqual(response.status, 200)
        except HTTPError as error:
            self.fail(f"{error.code}: {error.read()!r}")
        return self.client.supporting[-1]

    @staticmethod
    def text_of(document):
        return "\n".join(chunk["text"] for chunk in document["excerpts"])


class LatestAnswerLeads(Fixture):
    def test_a_large_file_gives_the_section_the_latest_answer_is_about(self):
        record = self.add("operating-manual.csv", manual(range(1, SECTIONS + 1)))
        total = sum(len(chunk["text"]) for chunk in self.chunks(record))
        self.assertGreater(total, 2 * service_module.MAX_SUPPORT_CHARS, "The file must be far over the reading limit")
        support = self.interview(TURNS)
        document = support["documents"][0]
        self.assertEqual(document["context_coverage"]["selection"], "selected excerpts")
        text = self.text_of(document)
        self.assertIn("acquirer portal within two days", text, "The chargeback section belongs to the latest answer")
        # Both matching sections are offered ahead of the file's opening pages.
        leading = "\n".join(chunk["text"] for chunk in document["excerpts"][:2])
        self.assertIn("acquirer portal within two days", leading)
        self.assertIn("before a vendor record is created", leading)

    def test_the_section_changes_with_the_answer_not_one_turn_late(self):
        self.add("operating-manual.csv", manual(range(1, SECTIONS + 1)))
        first = self.interview(TURNS[:1])["documents"][0]
        self.assertIn("before a vendor record is created", first["excerpts"][0]["text"])
        self.assertNotIn("acquirer portal within two days", self.text_of(first))
        second = self.interview(TURNS)["documents"][0]
        self.assertIn("acquirer portal within two days", self.text_of(second))
        # A following question alone does not push the answer out of the query.
        third = self.interview(TURNS + [{"id": "t004", "role": "assistant", "text": "Who signs off the written approval?"}])
        self.assertIn("acquirer portal within two days", self.text_of(third["documents"][0]))
        # Nor does a long answer about something else two turns later, while the search still has room for it.
        later = TURNS + [{"id": "t004", "role": "assistant", "text": "Who signs off the written approval?"},
                         {"id": "t005", "role": "user", "text": "The treasury director signs chargebacks off in the acquirer portal."}]
        self.assertIn("acquirer portal within two days", self.text_of(self.interview(later)["documents"][0]))

    def test_several_mid_size_files_together_over_the_limit_keep_the_matching_part(self):
        # Each file fits the limit by itself; five of them do not. The matching rows are at the end of their file.
        records = [self.add(f"part-{index}.csv", manual(range(index * 10 + 1, index * 10 + 11), filler=18))
                   for index in range(5)]
        sizes = [sum(len(chunk["text"]) for chunk in self.chunks(record)) for record in records]
        self.assertTrue(all(size < service_module.MAX_SUPPORT_CHARS for size in sizes), sizes)
        self.assertGreater(sum(sizes), service_module.MAX_SUPPORT_CHARS, sizes)
        support = self.interview(TURNS)
        by_name = {document["name"]: document for document in support["documents"]}
        holder = by_name["part-3.csv"]  # sections 31 to 40
        self.assertIn("acquirer portal within two days", self.text_of(holder))
        self.assertLess(holder["context_coverage"]["included_chunks"], holder["context_coverage"]["total_chunks"],
                        "The file was cut, and its matching part was kept")
        self.assertIn("acquirer portal within two days", holder["excerpts"][0]["text"])

    def test_a_file_that_fits_whole_is_still_given_whole_and_in_its_own_order(self):
        record = self.add("short-manual.csv", manual((1, 2, 3, VENDOR, 7, 8, CHARGEBACK, 34)))
        expected = [chunk["id"] for chunk in self.chunks(record)]
        self.assertGreater(len(expected), 2)
        document = self.interview(TURNS)["documents"][0]
        self.assertEqual([chunk["id"] for chunk in document["excerpts"]], expected)
        self.assertTrue(document["context_coverage"]["complete_text"])


class PassagesBesideAMatch(Fixture):
    def test_the_passages_next_to_a_match_come_before_the_first_pages(self):
        record = self.add("operating-manual.csv", manual(range(1, SECTIONS + 1)))
        ordered = [chunk["id"] for chunk in self.chunks(record)]
        support = self.httpd.documents.supporting_context(self.scope, "chargebacks acquirer portal treasury")
        document = support["documents"][0]
        included = [chunk["id"] for chunk in document["excerpts"]]
        hit = next(chunk["id"] for chunk in document["excerpts"] if "acquirer portal within two days" in chunk["text"])
        position = ordered.index(hit)
        self.assertGreater(position, len(ordered) // 2, "The match is in the second half of the file")
        for neighbour in (ordered[position - 1], ordered[position + 1]):
            self.assertIn(neighbour, included)
            self.assertLess(included.index(neighbour), included.index(ordered[1]) if ordered[1] in included else len(included),
                            "A passage beside the match is offered before the file's second chunk")
        # The structural samples (start, middle, end) are still there.
        for sample in (ordered[0], ordered[len(ordered) // 2], ordered[-1]):
            self.assertIn(sample, included)

    def test_a_reader_gives_no_neighbours_for_a_chunk_it_did_not_return(self):
        record = self.add("operating-manual.csv", manual(range(1, 6)))
        ordered = self.chunks(record)
        with self.store.interview_reader(self.scope) as reader:
            self.assertEqual(reader.neighbours(record["id"], ordered[1]["id"]), [])
            listed = reader.chunk_rows(record["id"], 0, 3)
            self.assertEqual([chunk["id"] for chunk in reader.neighbours(record["id"], listed[1]["id"])],
                             [ordered[2]["id"], ordered[0]["id"]])
            self.assertEqual([chunk["id"] for chunk in reader.neighbours(record["id"], listed[0]["id"])], [ordered[1]["id"]])
            self.assertEqual(reader.neighbours("doc_unknown", listed[0]["id"]), [])


class ReviewNotesBringTheirPassage(Fixture):
    def test_a_note_in_the_participants_words_brings_the_passage_it_cites(self):
        # The file calls them "reversals" and shares no topic word with the conversation; the review's
        # note and the participant say "chargebacks".
        lines = ["section,text"]
        for number in range(1, SECTIONS + 1):
            rows = [f"Part {number}. Operating manual part {number}."]
            if number == CHARGEBACK:
                rows.append("Payment reversals: cash desk staff raise a ticket with the processor inside two days "
                            "and refer large reversals to the head of cash management.")
            rows.extend(f"In the routine remark {number}-{row} a general note zq{number}x{row} is kept by the group and then it has what we need."
                        for row in range(30))
            lines.extend(f'{number},"{row}"' for row in rows)
        record = self.add("operating-manual.csv", ("\n".join(lines) + "\n").encode())
        cited = next(chunk for chunk in self.chunks(record) if "Payment reversals" in chunk["text"])
        turns = [TURNS[0], {"id": "t002", "role": "assistant", "text": "What happens when a customer disputes a charge?"}, TURNS[2]]
        note = {"text": "Chargebacks are opened as a dispute case by the treasury analyst and escalated to the treasury director.",
                "sources": [{"source_id": cited["id"], "label": cited["label"]}]}
        unrelated = {"text": "The manual has forty numbered sections.", "sources": [{"source_id": self.chunks(record)[0]["id"]}]}

        without = self.interview(turns)["documents"][0]
        self.assertNotIn("Payment reversals", self.text_of(without), "The file's own wording does not match the answer")
        self.store.update(self.scope, record["id"], {"analysis": {"phase": "complete", "disposition": "relevant", "version": 3,
                          "summary": "An operating manual.", "observations": [unrelated, note], "questions": []}})
        document = self.interview(turns)["documents"][0]
        self.assertIn("Payment reversals", self.text_of(document))
        self.assertIn(note["text"], [item["text"] for item in document["observations"]],
                      "The note is passed on because its passage is now among the excerpts")

    def test_a_note_that_does_not_match_the_conversation_brings_nothing(self):
        record = self.add("operating-manual.csv", manual(range(1, SECTIONS + 1)))
        ordered = self.chunks(record)
        far = ordered[len(ordered) // 3]
        note = {"text": "Petty cash is counted weekly by the office manager.", "sources": [{"source_id": far["id"]}]}
        baseline = [chunk["id"] for chunk in self.interview(TURNS)["documents"][0]["excerpts"]]
        self.store.update(self.scope, record["id"], {"analysis": {"phase": "complete", "disposition": "relevant", "version": 3,
                          "summary": "An operating manual.", "observations": [note], "questions": []}})
        self.assertEqual([chunk["id"] for chunk in self.interview(TURNS)["documents"][0]["excerpts"]], baseline)


class QueryWords(unittest.TestCase):
    def test_the_query_is_built_newest_first(self):
        query = server.retrieval_query(TURNS)
        self.assertTrue(query.startswith("For chargebacks the treasury analyst"))
        self.assertLess(query.index("customer disputes a card payment"), query.index("vendor onboarding"))
        words = service_module.retrieval_words(query)
        self.assertLessEqual(len(words), service_module.MAX_QUERY_WORDS)
        for word in ("chargebacks", "treasury", "acquirer", "portal", "escalated", "director"):
            self.assertIn(word, words)
        self.assertEqual(server.retrieval_query([], "Invoice approval"), "Invoice approval")
        self.assertEqual(server.retrieval_query([{"text": "only answer"}], "ignored"), "only answer")
        self.assertEqual(len(server.retrieval_query([{"text": "x" * 5000}])), 2000)
        # Only the last three turns are used.
        many = [{"text": f"turn{index}"} for index in range(6)]
        self.assertEqual(server.retrieval_query(many), "turn5 turn4 turn3")

    def test_a_query_that_fits_keeps_every_word(self):
        words = service_module.retrieval_words("Who is the approver of the PO if it is over 5 thousand?")
        self.assertEqual(words, ["who", "is", "the", "approver", "of", "po", "if", "it", "over", "5", "thousand"])

    def test_case_does_not_use_up_places(self):
        self.assertEqual(service_module.retrieval_words("The the THE Vendor vendor VENDOR"), ["the", "vendor"])

    def test_a_long_query_gives_up_function_words_before_topic_words(self):
        filler = "and then we do it for all of them because that is how it was when I was here before you"
        long_answer = " ".join(f"{filler} item{index}" for index in range(30)) + " and the PO goes to AP for a 3 way match with the GRN"
        words = service_module.retrieval_words(long_answer)
        # Thirty topic words and the closing clause all fit once the function words have given up their places.
        self.assertEqual(words, [*(f"item{index}" for index in range(30)), "po", "goes", "ap", "way", "match", "grn"])
        self.assertFalse(set(words) & service_module.FUNCTION_WORDS)
        # Before, the first forty distinct words were the filler and "item0" to "item19": the closing clause was cut.
        self.assertLessEqual(len(words), service_module.MAX_QUERY_WORDS)
        # Short codes are topic words: they are kept when they are among the first forty.
        short = service_module.retrieval_words("the PO goes to AP for a 3 way match with the GRN " + " ".join(f"{filler} item{index}" for index in range(40)))
        for code in ("po", "ap", "grn", "way", "match"):
            self.assertIn(code, short)
        self.assertNotIn("3", short, "A single character gives up its place")
        self.assertNotIn("the", short)

    def test_a_long_query_of_function_words_only_is_not_emptied(self):
        words = service_module.retrieval_words(" ".join(sorted(service_module.FUNCTION_WORDS)))
        self.assertEqual(len(words), service_module.MAX_QUERY_WORDS)

    def test_other_scripts_and_bounds(self):
        words = service_module.retrieval_words("Rechnung prüfen und freigeben 請求書 を 確認")
        self.assertIn("prüfen", words)
        self.assertIn("請求書", words)
        self.assertEqual(service_module.retrieval_words(""), [])
        with self.assertRaises(service_module.DocumentError):
            service_module.retrieval_words(None)
        self.assertLessEqual(len(" ".join(service_module.retrieval_words("y" * 150 + " " + " ".join("w%d" % i + "x" * 95 for i in range(60))))), 2000)


if __name__ == "__main__":
    unittest.main()
