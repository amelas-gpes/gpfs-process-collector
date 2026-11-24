"""Source authority across file versions, typed confirmations, and audited drafts."""
import copy
import unittest
import tempfile
from pathlib import Path

from test_server import server
from test_file_reading_speed import sections, supporting, DOC
from test_background_continuity import step


class ReviewedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.text = "The reviewer checks the schedule then the controller releases the notice."
        self.source = DOC + "_p1_c1"
        self.ref = "review_v1_" + "1" * 32
        self.version = "a" * 64
        self.document = {"id": DOC, "name": "Rules.txt", "source_revision": self.version,
                         "excerpts": [{"id": self.source, "text": self.text}]}
        self.review = {"topic":"rules", "decision":"confirmed", "answer":self.text, "source_ids":[self.source],
                       "source_revisions":{self.source:self.version}, "reference":self.ref}
        self.turns = [{"id":"u1","role":"user","text":"The register holds signed notices."}]

    def context(self, docs, reviews):
        return server.validate_payload({"context":{}, "turns":self.turns, "file_topic_reviews":reviews,
                                        "_supporting_documents":{"documents":docs}})[0]

    def test_same_confirmation_supports_each_exact_claim_and_expires_with_its_source(self):
        ctx = self.context([self.document], [self.review])
        catalog = server.document_evidence_catalog({"documents":[self.document]})
        self.assertIn(self.ref, server.evidence_sources(self.turns,catalog,ctx))
        self.assertNotIn("context", server.evidence_sources(self.turns,catalog,ctx))
        refs = server.capture_facts.sources(ctx,self.turns,catalog)
        self.assertEqual(refs[self.ref]["authority"],"confirmation")
        nodes = [step("S1","Check schedule","Reviewer",[self.ref]),step("S2","Release notice","Controller",[self.ref])]
        nodes[0]["operating_details"] = [{"field":"control","text":self.text,"evidence_turns":[self.ref]}]
        server.gpfs_interview.validate_operating_details(nodes,self.turns,catalog,ctx)
        edge = {"from":"S1","to":"S2","label":"then","evidence_turns":[self.ref]}
        proof = {**edge,"passages":[{"source_id":self.ref,"quote":self.text}]}
        log = {}
        self.assertEqual(server.grounded_routes([edge],[proof],nodes,ctx,self.turns,catalog,audit_log=log),([edge],[]))
        receipt = server.route_review_record({"steps":nodes,"connections":[edge],"open_questions":[]},log,ctx,self.turns,catalog)
        self.assertEqual(receipt[0]["status"],"supported")
        filed = {"steps":nodes,"connections":[edge],"open_questions":[],"route_assurance":receipt}
        server.revalidate_filed_routes(filed, ctx, self.turns, catalog)
        self.assertEqual(filed["route_assurance"][0]["status"],"supported")
        filed["steps"][1]["actor"] = "Another team"
        server.revalidate_filed_routes(filed, ctx, self.turns, catalog)
        self.assertEqual(filed["route_assurance"][0]["status"],"pending")
        draft = {"controls":[self.text],"field_evidence":[{"field":"controls","index":0,"text":self.text,"evidence_turns":[self.ref]}]}
        server.review_draft_fields(draft,self.turns,catalog,ctx)
        self.assertEqual(draft["controls"],[self.text])
        for docs, reviews in (([self.document],[]),([],[self.review]),
                              ([{**self.document,"source_revision":"b"*64}],[self.review])):
            stale = self.context(docs,reviews)
            self.assertNotIn(self.ref, server.evidence_sources(self.turns,[],stale))
            self.assertIn("u1",server.evidence_sources(self.turns,[],stale))

    def test_undo_wins_across_reopen_and_stale_requests_in_both_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=server.documents.DocumentStore(Path(tmp))
            scope=store.create_scope()
            self.assertEqual(store.current_topic_reviews(scope,[self.review]),[self.review])
            self.assertEqual(store.current_topic_reviews(scope,[{**self.review,"answer":"Different words."}]),[])
            store.current_topic_reviews(scope,[],[self.ref])
            reopened=server.documents.DocumentStore(Path(tmp))
            self.assertEqual(reopened.current_topic_reviews(scope,[self.review]),[])
            another="review_v1_"+"2"*32
            reopened.current_topic_reviews(scope,[],[another])
            self.assertEqual(store.current_topic_reviews(scope,[{**self.review,"reference":another}]),[])

    def test_same_wording_under_different_sheet_scopes_stays_separate(self):
        data = sections(30)
        wording = "The controller releases the notice."
        for row, sheet in zip(data[:2], ("Fund A","Fund B")):
            row["text"] = wording + "\n" + row["text"]
            row["location"]["sheet"] = sheet
        reading = server.file_parts.plan(supporting(data), {DOC:data})
        parts = [{"fact_operations":[{"topic":"rules","kind":"detail","text":wording,
                   "support":[{"source_id":row["id"],"first_line":1,"last_line":1}]}]} for row in data[:2]]
        delta = server.file_parts.join(reading,server.capture_facts.empty_state()["revision"],parts,[])
        catalog = server.document_evidence_catalog(reading["supporting"])
        held = server.capture_facts.apply_delta(server.capture_facts.empty_state(),delta,{},[],catalog)
        self.assertEqual(len(held["facts"]),2)
        self.assertEqual([f["evidence_turns"] for f in held["facts"]],[[row["id"]] for row in data[:2]])

    def test_an_internal_estimate_or_a_misread_cannot_establish_that_a_new_notice_was_sent(self):
        turns = [{"role":"user","id":"u1","text":"We issued a notice with the $250,000 fee."},
                 {"role":"user","id":"u2","text":"The fee is now $225,000."}]
        for words in ("We later revised the internal fee estimate to $225,000.",
                      "I misread the notice. The fee always showed $225,000.", "The fee is now $225,000."):
            turns[1]["text"] = words
            graph = {"steps":[step("S1","Send a revised notice","Controller",["u2"])],"connections":[],"open_questions":[]}
            server.route_review_record(graph,{}, {},turns,[])
            self.assertIn("Owner review needed", graph["steps"][0]["title"])
            self.assertTrue(graph["open_questions"])

    def test_unrelated_citation_does_not_publish_a_material_control(self):
        claim = "A second reviewer signs every payment."
        draft = {"controls":[claim],"field_evidence":[{"field":"controls","index":0,"text":claim,"evidence_turns":["u1"]}]}
        supported = copy.deepcopy(draft)
        server.review_draft_fields(draft,self.turns,[],{})
        self.assertTrue(draft["controls"][0].startswith("Owner review needed"))
        self.assertFalse(draft["field_evidence"])
        server.review_draft_fields(supported,[{**self.turns[0],"text":claim}],[],{})
        self.assertEqual(supported["controls"],[claim])
