"""A citation that already exists stays valid when its excerpt is outside the request.

One request reads at most 60,000 characters of reference files. When the map
and the notes together cite more than that, the document store reports the
cited excerpts it could not carry as known excerpts without their text. The
accepted map, the accepted notes and the private fact ledger may keep citing
them. Nothing may newly cite them. A changed step or topic keeps the ones it
already had when the change brings a source of its own; any other edit that
only keeps them is left out without refusing the update. An ID the store did
not report is refused as before. Hand-authored model output; no provider.
"""
import copy
import unittest

from test_server import server
import capture_facts as facts
from test_capture_facts import from_model_input, operation, typed_responder
from test_interview_orchestrator import SyntheticTeamProvider, reply_payload
from test_workflow_updates import audit, edge, payload, step, update

SHOWN = {"id": "doc_manual_r1_c1", "document_id": "doc_manual", "name": "manual.csv", "label": "Row 1",
         "location": {"row": 1}, "text": "The clerk records the request in the register."}
NOTES_ONLY = "doc_manual_r20_c1"
MAP_ONLY = "doc_manual_r30_c1"
CARRIED = {NOTES_ONLY, MAP_ONLY}


def baseline():
    """A map and notes that cite one excerpt this request reads and two it cannot carry."""
    value = payload()
    previous = value["previous_capture"]
    previous["workflow"]["steps"][1]["evidence_turns"] = ["u1", MAP_ONLY]
    previous["workflow"]["steps"][2]["evidence_turns"] = [SHOWN["id"]]
    previous["workflow"]["connections"][1]["evidence_turns"] = [MAP_ONLY]
    next(item for item in previous["memo_findings"] if item["key"] == "materials")["evidence_turns"] = ["u1", NOTES_ONLY]
    return value


def left_out(capture, subject=""):
    """How many open questions say that an edit of `subject` was left out of an update."""
    questions = capture["workflow"]["open_questions"] if "workflow" in capture else capture["open_questions"]
    return sum(1 for question in questions if "was left out of an update" in question and subject in question)


class CarriedBaselineTests(unittest.TestCase):
    def test_accepted_baseline_may_cite_an_excerpt_the_request_could_not_carry(self):
        value = baseline()
        previous = server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN], CARRIED)
        self.assertEqual(previous["workflow"]["steps"][1]["evidence_turns"], ["u1", MAP_ONLY])
        self.assertEqual(next(item for item in previous["memo_findings"] if item["key"] == "materials")["evidence_turns"],
                         ["u1", NOTES_ONLY])
        # What the store did not report stays refused: the check still stops a forged or foreign ID.
        with self.assertRaisesRegex(ValueError, "working map cites missing"):
            server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN], {NOTES_ONLY})
        with self.assertRaisesRegex(ValueError, "memo finding references missing"):
            server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN], {MAP_ONLY})
        with self.assertRaisesRegex(ValueError, "working map cites missing"):
            server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN])

    def test_a_finding_supported_only_by_a_carried_excerpt_stays_partial(self):
        value = baseline()
        finding = next(item for item in value["previous_capture"]["memo_findings"] if item["key"] == "materials")
        finding.update(status="captured", evidence_turns=[NOTES_ONLY])
        previous = server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN], CARRIED)
        self.assertEqual(next(item for item in previous["memo_findings"] if item["key"] == "materials")["status"], "partial")

    def test_unchanged_components_keep_their_carried_citations_through_an_update(self):
        value = baseline()
        value["turns"].append({"id": "u4", "role": "user", "text": "Afterwards I archive the idea."})
        previous = server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN], CARRIED)
        before = copy.deepcopy(previous)
        # The model repeats two accepted components unchanged and adds one step from what it was shown.
        change = update(upsert_steps=[copy.deepcopy(previous["workflow"]["steps"][1]), step("S5", "Archive the idea", ["u4"])],
                        upsert_connections=[copy.deepcopy(previous["workflow"]["connections"][1])],
                        memo_findings=[copy.deepcopy(next(item for item in previous["memo_findings"] if item["key"] == "materials"))])
        merged = server.apply_workflow_update(change, previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["steps"][:4], before["workflow"]["steps"])
        self.assertEqual(merged["workflow"]["steps"][4]["id"], "S5")
        self.assertEqual(merged["workflow"]["connections"], before["workflow"]["connections"])
        self.assertEqual(merged["memo_findings"], before["memo_findings"])
        self.assertEqual(previous, before)
        with self.assertRaisesRegex(ValueError, "working map cites missing"):
            server.apply_workflow_update(change, previous, value["turns"], [SHOWN])

    def changed(self):
        value = baseline()
        value["turns"].append({"id": "u4", "role": "user", "text": "I rank the ideas with the team and keep the ranking in Jira."})
        previous = server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN], CARRIED)
        return value, previous, copy.deepcopy(previous)

    def test_a_carried_excerpt_cannot_support_anything_it_did_not_already_support(self):
        value, previous, before = self.changed()
        # New components, and accepted ones that would newly cite an excerpt this request could not read.
        rerouted = {**copy.deepcopy(previous["workflow"]["connections"][1]), "label": "When ranked"}
        borrowed = {**copy.deepcopy(previous["workflow"]["steps"][1]), "title": "Rank the ideas",
                    "evidence_turns": ["u1", MAP_ONLY, NOTES_ONLY, "u4"]}
        finding = {"key": "materials", "status": "partial", "answer": "Jira tickets and the ranking.",
                   "evidence_turns": ["u1", NOTES_ONLY, MAP_ONLY, "u4"]}
        moved = {"key": "lifecycle", "status": "partial", "answer": "Ranking comes first.", "evidence_turns": [NOTES_ONLY]}
        for change in (update(upsert_steps=[step("S5", "Invented from an unread excerpt", [MAP_ONLY])]),
                       update(upsert_steps=[borrowed]),
                       update(upsert_connections=[edge("S1", "S3", "Skips", [NOTES_ONLY])]),
                       update(upsert_connections=[rerouted]),
                       update(upsert_connections=[edge("S1", "S2", "Next", ["u1", MAP_ONLY])]),
                       update(memo_findings=[finding]),
                       update(memo_findings=[moved])):
            with self.subTest(change={key: item for key, item in change.items() if item and key.startswith(("upsert", "memo"))}):
                with self.assertRaisesRegex(ValueError, "did not read"):
                    server.apply_workflow_update(change, previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(previous, before)

    def test_an_edit_that_only_keeps_its_carried_citation_is_left_out_and_the_rest_is_applied(self):
        value, previous, before = self.changed()
        # The model restates accepted components whole, as it is asked to, without a source of its own
        # for the change. Each keeps its accepted version; the update is not refused.
        retitled = {**copy.deepcopy(previous["workflow"]["steps"][1]), "title": "Rank the ideas"}
        resourced = {**copy.deepcopy(previous["workflow"]["connections"][1]), "evidence_turns": [MAP_ONLY, "u4"]}
        finding = {"key": "materials", "status": "partial", "answer": "Jira tickets only.", "evidence_turns": ["u1", NOTES_ONLY]}
        change = update(upsert_steps=[retitled, step("S5", "Archive the idea", ["u4"])], upsert_connections=[resourced],
                        memo_findings=[finding, {"key": "lifecycle", "status": "partial",
                                                 "answer": "Ranking happens with the team.", "evidence_turns": ["u1", "u4"]}])
        merged = server.apply_workflow_update(change, previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["steps"][:4], before["workflow"]["steps"])
        self.assertEqual(merged["workflow"]["steps"][4]["id"], "S5")
        self.assertEqual(merged["workflow"]["connections"], before["workflow"]["connections"])
        notes = {item["key"]: item for item in merged["memo_findings"]}
        self.assertEqual(notes["materials"], next(item for item in before["memo_findings"] if item["key"] == "materials"))
        self.assertEqual(notes["lifecycle"]["answer"], "Ranking happens with the team.")
        self.assertEqual(previous, before)
        self.assertEqual(change["upsert_steps"][0], retitled)
        # Each edit that was left out is named once in the open questions, by its accepted name.
        for subject in ("step S2 (Prioritize ideas)", "the handoff S2 to S3", "the notes on Existing materials"):
            self.assertEqual(left_out(merged, subject), 1, merged["workflow"]["open_questions"])
        self.assertEqual(left_out(merged), 3)
        # The same restatement is taken once it cites only what this request read, and nothing is noted.
        retitled["evidence_turns"] = ["u1", SHOWN["id"]]
        merged = server.apply_workflow_update(update(upsert_steps=[retitled]), previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["steps"][1]["title"], "Rank the ideas")
        self.assertEqual(left_out(merged), 0)

    def test_an_edit_left_out_again_is_not_noted_twice_and_the_note_never_refuses_an_update(self):
        value, previous, before = self.changed()
        retitled = {**copy.deepcopy(previous["workflow"]["steps"][1]), "title": "Rank the ideas"}
        first = server.apply_workflow_update(update(upsert_steps=[retitled]), previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(left_out(first, "step S2 (Prioritize ideas)"), 1)
        # The model repeats the open questions of the accepted map and proposes the same edit again.
        again = server.apply_workflow_update(update(upsert_steps=[retitled], open_questions=first["workflow"]["open_questions"]),
                                             previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(again["workflow"]["open_questions"], first["workflow"]["open_questions"])
        # A full list of open questions is the map's own limit; the note must not turn it into a refusal.
        full = [f"Open question {number}?" for number in range(500)]
        merged = server.apply_workflow_update(update(upsert_steps=[retitled], open_questions=full),
                                              previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["open_questions"], full)
        self.assertIn("500 open questions", merged["question_limit_notice"])
        self.assertEqual(merged["workflow"]["steps"], before["workflow"]["steps"])
        # An update that leaves nothing out, and one without carried excerpts, adds nothing.
        self.assertEqual(server.add_left_out_questions(["Kept?"], []), ["Kept?"])
        archived = step("S5", "Archive the idea", ["u4"])
        self.assertEqual(left_out(server.apply_workflow_update(update(upsert_steps=[archived]), previous, value["turns"],
                                                               [SHOWN], CARRIED)), 0)

    def test_a_cumulative_topic_and_a_corrected_step_keep_the_carried_citations_they_had(self):
        value, previous, before = self.changed()
        # WORKFLOW_INSTRUCTIONS: update each affected topic cumulatively, retaining its other sources,
        # and reuse a step's ID when its action is corrected. Each change brings the answer it rests on.
        accepted = next(item for item in before["memo_findings"] if item["key"] == "materials")
        topic = {**copy.deepcopy(accepted), "answer": accepted["answer"] + "\nThe ranking is kept in Jira.",
                 "evidence_turns": [*accepted["evidence_turns"], "u4"]}
        corrected = {**copy.deepcopy(before["workflow"]["steps"][1]), "title": "Rank the ideas with the team",
                     "evidence_turns": ["u1", MAP_ONLY, "u4"]}
        merged = server.apply_workflow_update(update(upsert_steps=[corrected], memo_findings=[topic]),
                                              previous, value["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["steps"][1], corrected)
        self.assertEqual(next(item for item in merged["memo_findings"] if item["key"] == "materials"), topic)
        self.assertEqual(merged["workflow"]["connections"], before["workflow"]["connections"])
        # The addition is checked like any other source: one that nobody supplied is refused.
        topic["evidence_turns"][-1] = "doc_manual_r99_c1"
        with self.assertRaisesRegex(ValueError, "memo finding references missing"):
            server.apply_workflow_update(update(memo_findings=[topic]), previous, value["turns"], [SHOWN], CARRIED)
        # Without the store's confirmation nothing is carried, and the baseline rule is not involved.
        self.assertEqual(server.settle_carried_edits(update(upsert_steps=[corrected]), previous), update(upsert_steps=[corrected]))


class CarriedRouteReviewTests(unittest.TestCase):
    def reviewed(self, candidate, review, carried=CARRIED):
        value = baseline()
        previous = server.workflow_previous_capture(value["previous_capture"], value["turns"], [SHOWN], CARRIED)
        return previous, server.apply_workflow_audit(candidate, review, previous, context={}, turns=value["turns"],
                                                     documents=[SHOWN], carried=carried)

    def test_an_accepted_route_repeated_unchanged_keeps_its_carried_citation(self):
        accepted = baseline()["previous_capture"]["workflow"]["connections"][1]
        previous, corrected = self.reviewed(update(upsert_connections=[copy.deepcopy(accepted)]), audit())
        self.assertEqual(corrected["upsert_connections"], [accepted])
        merged = server.apply_workflow_update(corrected, previous, baseline()["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["connections"][1], accepted)
        # Without the store's confirmation the excerpt is not a source at all. The proposal that
        # rests on it alone is left out and named, instead of refusing the whole map for a
        # citation the model got wrong; the route check itself still refuses such a citation.
        _, unconfirmed = self.reviewed(update(upsert_connections=[copy.deepcopy(accepted)]), audit(), carried=())
        self.assertEqual(unconfirmed["upsert_connections"], [])
        self.assertTrue(any("handoff or prerequisite" in question for question in unconfirmed["open_questions"]))
        value = baseline()
        with self.assertRaisesRegex(ValueError, "map connection cites missing"):
            server.grounded_routes([copy.deepcopy(accepted)], [], value["previous_capture"]["workflow"]["steps"], {},
                                   value["turns"], [SHOWN])

    def test_a_new_route_cannot_rest_on_a_carried_excerpt(self):
        proposed = edge("S1", "S3", "Skips", [MAP_ONLY])
        support = [{"from": "S1", "to": "S3", "label": "Skips", "passages": [{"source_id": MAP_ONLY, "quote": "skips"}]}]
        with self.assertRaisesRegex(ValueError, "did not read|map connection cites missing"):
            self.reviewed(update(upsert_connections=[proposed]), audit(route_support=support))
        # The reviewer cannot introduce one either, and the route check itself still refuses it.
        with self.assertRaisesRegex(ValueError, "did not read|map connection cites missing"):
            self.reviewed(update(), audit(upsert_connections=[proposed], route_support=support))
        value = baseline()
        with self.assertRaisesRegex(ValueError, "map connection cites missing"):
            server.grounded_routes([proposed], support, value["previous_capture"]["workflow"]["steps"], {}, value["turns"],
                                   [SHOWN], carried=CARRIED, accepted_routes=value["previous_capture"]["workflow"]["connections"])

    def test_an_accepted_route_restated_with_another_source_keeps_its_accepted_version(self):
        # A changed route is verified from quoted passages and an unread excerpt cannot be quoted,
        # so the restatement is left out; the accepted route and the rest of the update stay.
        accepted = baseline()["previous_capture"]["workflow"]["connections"][1]
        restated = {**copy.deepcopy(accepted), "evidence_turns": [MAP_ONLY, "u1"]}
        archived = step("S5", "Archive the idea", ["u3"])
        previous, corrected = self.reviewed(update(upsert_steps=[archived], upsert_connections=[restated]), audit())
        self.assertEqual(corrected["upsert_connections"], [])
        self.assertEqual(corrected["upsert_steps"], [archived])
        merged = server.apply_workflow_update(corrected, previous, baseline()["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["connections"], previous["workflow"]["connections"])
        self.assertEqual(merged["workflow"]["steps"][4], archived)

    def test_a_restated_step_keeps_its_accepted_version_when_its_handoff_cites_an_unread_excerpt(self):
        # S2 is retitled, so its accepted handoffs must be re-verified from quoted passages.
        # The handoff S2 to S3 cites only an excerpt this request could not carry: no reviewer
        # can quote it. The retitle is left out, the accepted step and handoffs are kept, and
        # the rest of the update is applied instead of the whole update being refused.
        retitled = step("S2", "Rank the ideas")
        archived = step("S5", "Archive the idea", ["u3"])
        support = [{"from": "S1", "to": "S2", "label": "Next",
                    "passages": [{"source_id": "u1", "quote": "I prepare the discovery board, prioritize ideas"}]},
                   {"from": "S2", "to": "S3", "label": "Next", "passages": []}]
        previous, corrected = self.reviewed(update(upsert_steps=[retitled, archived]), audit(route_support=support))
        self.assertEqual(corrected["upsert_steps"], [archived])
        self.assertEqual(corrected["upsert_connections"], [])
        # The restatement that was held is named, by the accepted step, and nothing else is.
        self.assertEqual((left_out(corrected, "step S2 (Prioritize ideas)"), left_out(corrected)), (1, 1))
        merged = server.apply_workflow_update(corrected, previous, baseline()["turns"], [SHOWN], CARRIED)
        self.assertEqual(merged["workflow"]["steps"][:4], previous["workflow"]["steps"])
        self.assertEqual(merged["workflow"]["steps"][4], archived)
        self.assertEqual(merged["workflow"]["connections"], previous["workflow"]["connections"])
        self.assertEqual((left_out(merged, "step S2 (Prioritize ideas)"), left_out(merged)), (1, 1))

    def test_a_restated_step_is_still_refused_when_a_handoff_it_could_quote_is_unverified(self):
        # S4 is retitled. Its handoff S3 to S4 cites the participant, whom the reviewer could quote
        # and did not: that is not the reading limit, and the revision is refused as before.
        support = [{"from": "S3", "to": "S4", "label": "Next", "passages": []}]
        with self.assertRaisesRegex(ValueError, "handoff S3 to S4 unverified"):
            self.reviewed(update(upsert_steps=[step("S4", "File the ticket")]), audit(route_support=support))
        # Without the store's confirmation the handoff of a retitled S2 is refused as before as well.
        with self.assertRaisesRegex(ValueError, "map connection cites missing"):
            self.reviewed(update(upsert_steps=[step("S2", "Rank the ideas")]), audit(), carried=())


OLD = "doc_removed_r5_c1"
OLD_READ = {"id": OLD, "document_id": "doc_removed", "name": "removed.csv", "label": "Row 5", "location": {"row": 5},
            "text": "Old rule from a removed file.", "retained_only": True, "archived": True}
OLD_CARRIED = {"id": OLD, "document_id": "doc_removed", "name": "removed.csv", "characters": 29, "retained_only": True}


class CarriedInactiveEvidenceTests(unittest.TestCase):
    """A saved excerpt of a parked or removed file may preserve what cites it and nothing else.

    No changed component may rest on it, whether the saved excerpt fitted into the request
    (it is then among the documents, flagged retained_only, and the edit is refused) or did
    not (the store then reports it as carried, with the same flag; the model could not know,
    so the edit is left out and named).
    """

    def states(self):
        value = baseline()
        value["turns"].append({"id": "u4", "role": "user", "text": "I rank the ideas with the team and keep the ranking in Jira."})
        raw = value["previous_capture"]
        raw["workflow"]["steps"][1]["evidence_turns"] = ["u1", OLD]
        raw["workflow"]["connections"][1]["evidence_turns"] = [OLD]
        next(item for item in raw["memo_findings"] if item["key"] == "materials")["evidence_turns"] = ["u1", OLD]
        store = server.carried_document_sources({"_carried_document_sources": [OLD_CARRIED]})
        for name, documents, carried in (("read", [SHOWN, OLD_READ], {}), ("carried", [SHOWN], store)):
            previous = server.workflow_previous_capture(copy.deepcopy(raw), value["turns"], documents, carried)
            yield name, value["turns"], documents, carried, previous

    def test_a_changed_component_cannot_keep_a_carried_excerpt_of_a_parked_or_removed_file(self):
        for name, turns, documents, carried, previous in self.states():
            before = copy.deepcopy(previous)
            accepted = next(item for item in before["memo_findings"] if item["key"] == "materials")
            changes = {
                "step corrected with a source of its own": update(upsert_steps=[
                    {**copy.deepcopy(before["workflow"]["steps"][1]), "title": "Rank the ideas with the team",
                     "evidence_turns": ["u1", OLD, "u4"]}]),
                "topic extended with a source of its own": update(memo_findings=[
                    {**copy.deepcopy(accepted), "answer": "A rewritten answer.", "evidence_turns": ["u1", OLD, "u4"]}]),
                "step restated": update(upsert_steps=[{**copy.deepcopy(before["workflow"]["steps"][1]), "title": "Rank the ideas"}]),
                "topic restated": update(memo_findings=[{**copy.deepcopy(accepted), "answer": "Jira tickets only."}]),
                "connection restated": update(upsert_connections=[
                    {**copy.deepcopy(before["workflow"]["connections"][1]), "evidence_turns": [OLD, "u4"]}]),
            }
            invented = update(upsert_steps=[step("S5", "Invented from a removed file", [OLD])])
            subjects = {"step": "step S2 (Prioritize ideas)", "topic": "the notes on Existing materials",
                        "connection": "the handoff S2 to S3"}
            for label, change in changes.items():
                with self.subTest(excerpt=name, change=label):
                    if not carried:
                        # The model was shown the excerpt as inactive: the edit is refused, as in base.
                        with self.assertRaisesRegex(ValueError, "Inactive document evidence may preserve an existing component"):
                            server.apply_workflow_update(change, previous, turns, documents, carried)
                        continue
                    # The model could not know: the edit is left out, also with a source of its own.
                    archived = step("S5", "Archive the idea", ["u4"])
                    change["upsert_steps"].append(archived)
                    merged = server.apply_workflow_update(change, previous, turns, documents, carried)
                    self.assertEqual(merged["workflow"]["steps"], [*before["workflow"]["steps"], archived])
                    self.assertEqual(merged["workflow"]["connections"], before["workflow"]["connections"])
                    self.assertEqual(merged["memo_findings"], before["memo_findings"])
                    self.assertEqual((left_out(merged, subjects[label.split()[0]]), left_out(merged)), (1, 1))
                    self.assertEqual(left_out(merged, "parked or removed file"), 1)
                    # The review step leaves it out in the same way, before anything is merged.
                    reviewed = server.apply_workflow_audit(change, audit(), previous, context={}, turns=turns,
                                                           documents=documents, carried=carried)
                    self.assertEqual((reviewed["upsert_steps"], reviewed["upsert_connections"], reviewed["memo_findings"]),
                                     ([archived], [], []))
                    self.assertEqual(left_out(reviewed, "parked or removed file"), 1)
            with self.subTest(excerpt=name, change="new step"):
                with self.assertRaisesRegex(ValueError, "Inactive document evidence" if not carried else "did not read"):
                    server.apply_workflow_update(invented, previous, turns, documents, carried)
            self.assertEqual(previous, before)
            # Repeating what was accepted is not a change, and other edits are applied.
            with self.subTest(excerpt=name, change="unchanged"):
                kept = update(upsert_steps=[copy.deepcopy(before["workflow"]["steps"][1]), step("S5", "Archive the idea", ["u4"])],
                              upsert_connections=[copy.deepcopy(before["workflow"]["connections"][1])],
                              memo_findings=[copy.deepcopy(accepted)])
                merged = server.apply_workflow_update(kept, previous, turns, documents, carried)
                self.assertEqual(merged["workflow"]["steps"][:4], before["workflow"]["steps"])
                self.assertEqual(merged["workflow"]["connections"], before["workflow"]["connections"])
                self.assertEqual(merged["memo_findings"], before["memo_findings"])
                self.assertEqual(left_out(merged), 0)

    def test_a_restated_step_never_takes_over_a_handoff_that_cites_a_parked_or_removed_file(self):
        # S2 is retitled and no longer cites the saved excerpt itself. Its accepted handoff S2 to S3
        # cites only that excerpt, which no reviewer can quote. The retitled step is not accepted in
        # either state: refused when the excerpt was read, held and named when it was only carried.
        support = [{"from": "S1", "to": "S2", "label": "Next",
                    "passages": [{"source_id": "u1", "quote": "I prepare the discovery board, prioritize ideas"}]},
                   {"from": "S2", "to": "S3", "label": "Next", "passages": []}]
        for name, turns, documents, carried, previous in self.states():
            with self.subTest(excerpt=name):
                change = update(upsert_steps=[step("S2", "Rank the ideas")])
                if not carried:
                    with self.assertRaisesRegex(ValueError, "handoff S2 to S3 unverified"):
                        server.apply_workflow_audit(change, audit(route_support=support), previous, context={}, turns=turns,
                                                    documents=documents, carried=carried)
                    continue
                reviewed = server.apply_workflow_audit(change, audit(route_support=support), previous, context={}, turns=turns,
                                                       documents=documents, carried=carried)
                self.assertEqual((reviewed["upsert_steps"], reviewed["upsert_connections"]), ([], []))
                self.assertEqual((left_out(reviewed, "step S2 (Prioritize ideas)"), left_out(reviewed, "parked or removed file")), (1, 1))

    def test_only_an_entry_the_store_flagged_is_inactive(self):
        active = {"id": "doc_manual_r20_c1", "document_id": "doc_manual", "name": "manual.csv", "characters": 40}
        store = server.carried_document_sources({"_carried_document_sources": [OLD_CARRIED, active]})
        self.assertEqual(server.inactive_carried(store), {OLD})
        # A plain collection of IDs carries no flag; neither does an entry that is malformed or not flagged.
        for value in ((), set(), {OLD, active["id"]}, [OLD], {OLD: OLD}, {OLD: None}, {OLD: {**OLD_CARRIED, "retained_only": False}}):
            self.assertEqual(server.inactive_carried(value), set())


class CarriedFactTests(unittest.TestCase):
    def setUp(self):
        self.context = {"process_name": "Invoice intake"}
        self.turns = [{"id": "u1", "role": "user", "text": "The reviewer compares the totals."}]
        self.shown = {"id": "doc_file1_alpha", "document_id": "doc_file1", "text": "The reviewer compares the two totals."}
        self.other = {"id": "doc_file1_beta", "document_id": "doc_file1", "text": "The packet is retained."}

    def state(self):
        state = facts.empty_state()
        delta = {"question": "What happens next?", "summary": "", "focus": "", "parking_lot": [],
                 "base_revision": state["revision"], "fact_reconciliations": [],
                 "topic_states": [{"key": key, "status": "partial" if key == "checks" else "unknown",
                                   "participant_unavailable": False} for key in facts.TOPICS],
                 "fact_operations": [operation("checks", self.shown["text"], self.shown["id"]),
                                     operation("checks", "The participant confirmed the comparison.", "u1")]}
        return facts.apply_delta(state, delta, self.context, self.turns, [self.shown])

    def active(self, state):
        return [fact["text"] for fact in state["facts"] if fact["state"] == "active"]

    def test_rebase_keeps_a_fact_whose_excerpt_is_carried(self):
        state = self.state()
        dropped = facts.rebase(state, self.context, self.turns, [self.other])
        self.assertEqual(self.active(dropped), ["The participant confirmed the comparison."])
        kept = facts.rebase(state, self.context, self.turns, [self.other], {self.shown["id"]})
        self.assertEqual(self.active(kept), self.active(state))
        self.assertEqual(facts.carried_sources(kept, [self.other]), [self.shown["id"]])
        self.assertEqual(facts.carried_sources(kept, [self.shown]), [])
        # Carrying an excerpt never excuses another source of the same account from changing.
        edited = [{**self.turns[0], "text": "The reviewer skips the comparison."}]
        self.assertEqual(self.active(facts.rebase(state, self.context, edited, [self.other], {self.shown["id"]})),
                         [self.shown["text"]])
        # An excerpt that is read again is compared as before, whatever was reported as carried.
        changed = {**self.shown, "text": "The controller compares the two totals."}
        self.assertEqual(self.active(facts.rebase(state, self.context, self.turns, [changed], {self.shown["id"]})),
                         ["The participant confirmed the comparison."])

    def test_published_notes_may_keep_a_carried_citation(self):
        findings = facts.findings(facts.rebase(self.state(), self.context, self.turns, [self.other], {self.shown["id"]}))
        server.validate_findings(copy.deepcopy(findings), self.turns, [self.other], {self.shown["id"]})
        with self.assertRaisesRegex(ValueError, "memo finding references missing"):
            server.validate_findings(copy.deepcopy(findings), self.turns, [self.other])


class CarriedNotesTests(unittest.TestCase):
    """The notes route: the private ledger keeps a fact whose excerpt the request could not carry."""

    def prepared(self):
        client = SyntheticTeamProvider()
        payload = client.payload()
        self.alpha = {"id": "doc_file1_alpha", "text": "The reviewer compares the two totals before release."}
        self.beta = {"id": "doc_file1_beta", "text": "The packet is retained in the records folder."}
        payload["_supporting_documents"] = {"source_versions": [{"id": "doc_file1", "source_revision": "a" * 64}],
            "documents": [{"id": "doc_file1", "name": "Procedure.pdf", "source_revision": "a" * 64,
                           "review": {"phase": "complete"}, "excerpts": [self.alpha]}]}
        self.seen = []
        def response(model_input):
            self.seen.append(model_input)
            return from_model_input(model_input, [operation("checks", self.alpha["text"], self.alpha["id"])]
                                    if len(self.seen) == 1 else [], {"checks": "partial"})
        typed_responder(client, response)
        first = client.coordinator.interview(payload)
        follow = reply_payload(payload, first, "The next detail concerns records.")
        # The next request reads another excerpt of the same unchanged file instead.
        follow["_supporting_documents"]["documents"][0]["excerpts"] = [self.beta]
        return client, follow

    def carried(self, **changes):
        return [{"id": self.alpha["id"], "document_id": "doc_file1", "name": "Procedure.pdf", "characters": 52, **changes}]

    def test_a_fact_whose_excerpt_is_carried_stays_in_the_notes(self):
        client, follow = self.prepared()
        follow["_carried_document_sources"] = self.carried()
        result = client.coordinator.interview(follow)
        self.assertEqual(client.request.call_count, 2)
        finding = next(item for item in result["memo_findings"] if item["key"] == "checks")
        self.assertEqual((finding["answer"], finding["evidence_turns"]), (self.alpha["text"], [self.alpha["id"]]))
        self.assertEqual(finding["status"], "partial")
        self.assertIn(self.alpha["text"], [fact["text"] for fact in self.seen[-1]["fact_state"]["facts"]])
        # The model is offered only what this request read; the carried text is not sent again.
        self.assertEqual([item["id"] for item in self.seen[-1]["supporting_documents"]["documents"][0]["excerpts"]],
                         [self.beta["id"]])
        self.assertNotIn("_carried_document_sources", self.seen[-1])
        self.assertNotIn("carried_sources", self.seen[-1]["supporting_documents"])
        self.assertNotIn(self.alpha["text"], str(self.seen[-1]["supporting_documents"]))
        self.assertEqual([item["id"] for item in result["document_evidence"]], [self.beta["id"]])
        # The fact is still pinned, and the following answer keeps it in the same way.
        later = reply_payload(follow, result, "Nothing else changes there.")
        later["turns"][-1]["id"], later["turns"][-2]["id"] = "u_later", "a_later"
        self.assertEqual(client.coordinator.fact_source_ids(later), [self.alpha["id"]])
        again = client.coordinator.interview(later)
        self.assertEqual(next(item for item in again["memo_findings"] if item["key"] == "checks")["answer"], self.alpha["text"])

    def test_a_changed_or_removed_file_still_retires_the_fact(self):
        for versions in ([], [{"id": "doc_file1", "source_revision": "b" * 64}]):
            with self.subTest(versions=versions):
                client, follow = self.prepared()
                follow["_carried_document_sources"] = self.carried()
                follow["_supporting_documents"]["source_versions"] = versions
                follow["_supporting_documents"]["documents"] = []
                result = client.coordinator.interview(follow)
                self.assertEqual(next(item for item in result["memo_findings"] if item["key"] == "checks")["status"], "unknown")
                self.assertFalse(any(fact["topic"] == "checks" for fact in self.seen[-1]["fact_state"]["facts"]))

    def test_an_excerpt_the_store_did_not_report_is_refused_with_a_truthful_reason(self):
        for supplied in (None, [], self.forged()):
            with self.subTest(supplied=supplied):
                client, follow = self.prepared()
                if supplied is not None:
                    follow["_carried_document_sources"] = supplied
                with self.assertRaises(server.APIError) as caught:
                    client.coordinator.interview(follow)
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(client.request.call_count, 1)
                message = str(caught.exception)
                self.assertIn("Procedure.pdf", message)
                self.assertNotIn("retry with the referenced files available", message)
                self.assertNotIn("could not fit", message)

    @staticmethod
    def forged():
        return [{"id": "doc_file1_other", "document_id": "doc_file1", "name": "Procedure.pdf", "characters": 9},
                "doc_file1_alpha", {"id": 7, "document_id": "doc_file1"}, {"document_id": "doc_file1"}]


class SourceBindingTests(unittest.TestCase):
    def test_binding_follows_the_evidence_not_the_count_of_citations_left_unread(self):
        binding = server.interview_orchestrator.Coordinator._source_binding
        context = {"process_name": "Invoice intake"}
        support = {"documents": [{"id": "doc_a", "name": "a.csv", "source_revision": "a" * 64,
                                  "excerpts": [{"id": "doc_a_r1_c1", "text": "One."}, {"id": "doc_a_r2_c1", "text": "Two."}]}],
                   "retained_evidence": [], "pending_documents": [], "omitted_documents": 0, "omitted_prior_sources": 0,
                   "source_versions": [{"id": "doc_a", "source_revision": "a" * 64}],
                   "context_budget": {"characters": 8, "max_characters": 60000, "chunks": 2, "max_chunks": 120}}
        # A replay of the same excerpts that asked for a different list of earlier citations.
        replay = {**copy.deepcopy(support), "omitted_prior_sources": 4,
                  "carried_sources": [{"id": "doc_a_r9_c1", "document_id": "doc_a", "name": "a.csv", "characters": 4}]}
        self.assertEqual(binding(context, replay), binding(context, support))
        changes = []
        for change in (lambda value: value["documents"][0]["excerpts"][0].update(text="One, revised."),
                       lambda value: value["documents"][0]["excerpts"].pop(),
                       lambda value: value["documents"][0].update(source_revision="b" * 64),
                       lambda value: value["documents"].append({"id": "doc_b", "name": "b.csv", "excerpts": []}),
                       lambda value: value["retained_evidence"].append({"id": "doc_c_r1_c1", "text": "Saved.", "retained_only": True}),
                       lambda value: value["pending_documents"].append({"id": "doc_d", "status": "pending"}),
                       lambda value: value["source_versions"].append({"id": "doc_b", "source_revision": "c" * 64}),
                       lambda value: value.update(omitted_documents=1)):
            changed = copy.deepcopy(replay)
            change(changed)
            changes.append(binding(context, changed))
            self.assertNotEqual(changes[-1], binding(context, support))
        self.assertEqual(len(set(changes)), len(changes))
        self.assertNotEqual(binding({"process_name": "Another process"}, support), binding(context, support))


class CarriedSourceListTests(unittest.TestCase):
    def test_only_the_server_owned_list_is_read(self):
        entry = {"id": "doc_a_r1_c1", "document_id": "doc_a", "name": "a.csv", "characters": 10}
        self.assertEqual(server.carried_document_sources({"_carried_document_sources": [entry]}), {"doc_a_r1_c1": entry})
        for value in ({}, None, [], {"carried_sources": [entry]}, {"_carried_document_sources": "doc_a_r1_c1"},
                      {"_carried_document_sources": [None, "doc_a_r1_c1", {"id": 3, "document_id": "doc_a"},
                                                     {"id": "doc_a_r1_c1"}]},
                      {"_supporting_documents": {"carried_sources": [entry]}}):
            self.assertEqual(server.carried_document_sources(value), {})

    def test_reading_summary_reports_the_citations_that_were_not_read_again(self):
        self.assertEqual(server.document_reading_summary({"omitted_documents": 0, "documents": [], "omitted_prior_sources": 3}),
                         {"omitted_documents": 0, "documents": [], "omitted_prior_sources": 3})
        for supporting in ({"omitted_documents": 0, "documents": [], "omitted_prior_sources": 0},
                           {"omitted_documents": 0, "documents": []},
                           {"omitted_documents": 0, "documents": [], "omitted_prior_sources": "3"},
                           {"omitted_documents": 0, "documents": [], "omitted_prior_sources": True}):
            self.assertEqual(server.document_reading_summary(supporting), {"omitted_documents": 0, "documents": []})


if __name__ == "__main__":
    unittest.main()
