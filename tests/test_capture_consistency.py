"""One capture must not contradict itself (findings 8, 9 and 11 of docs/testing/process-capture-2026-11-16).

- A handoff recorded as a structured link while the Connections note still read "unknown".
- The same escalation recorded twice because the participant described it in two wordings.
- The goal of the interview ("document how this process works") recorded as the purpose of the work.
The transactions below are hand-authored for a fictional process: no provider is involved.
"""
import copy
import unittest

from test_server import server
import capture_facts as facts
from test_capture_facts import operation, transaction

CONTEXT = {"process_name": "Payment release", "process_owner": "",
           "objective": "Document how this process works, including controls and what remains unresolved.", "background": ""}
TURNS = [
    {"id": "u1", "role": "user", "text": "Treasury checks cash against pending payments. If funds are short the status becomes "
     "Insufficient Funds and FA-16 takes over. Unresolved screening goes to the Compliance Officer."},
    {"id": "a1", "role": "assistant", "text": "What happens when a check fails?"},
    {"id": "u2", "role": "user", "text": "Unresolved or failed screening goes to the Compliance Officer and the client is notified. "
     "Operations communicates clearance to FA-07 and communicates a block to FA-07. An unverified wire cannot be used: "
     "clearance is a hard gate before release."},
]


def link(kind, counterpart, condition, source="u1"):
    return {"relationship_type": kind, "counterpart": counterpart, "condition": condition, "evidence_turns": [source]}


def apply(state, operations=(), links=None, statuses=None, turns=TURNS, context=CONTEXT, removed=()):
    delta = transaction(state, list(operations), statuses)
    if links is not None:
        delta["connections_out"] = list(links)
    if removed:
        delta["remove_connections"] = list(removed)
    return facts.apply_delta(state, delta, context, turns, [])


def notes(state, topic):
    return next(row for row in facts.findings(state) if row["key"] == topic)


class EquivalentLinkTests(unittest.TestCase):
    def test_the_same_condition_in_other_words_is_recognised_narrowly(self):
        same = [("Unresolved screening is escalated.", "Unresolved or failed screening is escalated."),
                ("When funds are short", "when the funds are short."),
                ("Approved above 10,000 EUR", "Approved above 10,000 EUR by the director")]
        different = [("Operations communicates clearance.", "Operations communicates a block."),
                     ("Approved above 10,000 EUR", "Approved above 50,000 EUR"),
                     ("Escalated", "Unresolved screening is escalated."),
                     ("", "Unresolved screening is escalated."),
                     ("Screening is unresolved", "Screening is unresolved after two attempts and the client has been told")]
        for left, right in same:
            self.assertTrue(facts.same_condition(left, right), (left, right))
            self.assertTrue(facts.same_condition(right, left), (right, left))
        for left, right in different:
            self.assertFalse(facts.same_condition(left, right), (left, right))

    def test_a_handoff_described_twice_is_one_link_with_both_citations(self):
        state = apply(facts.empty_state(), links=[link("hands_off_to", "Compliance Officer", "Unresolved screening is escalated.")])
        first = state["connections_out"][0]["id"]
        state = apply(state, links=[link("hands_off_to", "Compliance Officer", "Unresolved or failed screening is escalated.", "u2")])
        self.assertEqual(len(state["connections_out"]), 1)
        merged = state["connections_out"][0]
        self.assertEqual(merged["id"], first, "The link recorded first keeps its identity")
        self.assertEqual(merged["condition"], "Unresolved or failed screening is escalated.", "The fuller wording is kept")
        self.assertEqual(merged["evidence_turns"], ["u1", "u2"])
        self.assertEqual(set(merged["sources"]), {"u1", "u2"})
        public = facts.public_capture(state, transaction(state), server.COVERAGE)["connections_out"]
        self.assertEqual(public, [{"relationship_type": "hands_off_to", "counterpart": "Compliance Officer",
                                   "condition": "Unresolved or failed screening is escalated.", "evidence_turns": ["u1", "u2"]}])

    def test_a_route_whose_outcome_differs_stays_a_separate_link(self):
        state = apply(facts.empty_state(), links=[link("hands_off_to", "FA-07", "Operations communicates clearance.", "u2"),
                                                  link("hands_off_to", "FA-07", "Operations communicates a block.", "u2"),
                                                  link("requires_approval_from", "FA-07", "Operations communicates clearance.", "u2")])
        self.assertEqual(len(state["connections_out"]), 3)

    def test_links_a_ledger_already_holds_twice_are_merged_on_its_next_update(self):
        state = apply(facts.empty_state(), links=[link("hands_off_to", "Compliance Officer", "Unresolved screening is escalated.")])
        twin = copy.deepcopy(state["connections_out"][0])
        twin.update(id="connection_saved_twin", condition="Unresolved or failed screening is escalated.",
                    evidence_turns=["u2"], sources={"u2": facts.sources(CONTEXT, TURNS, [])["u2"]})
        state["connections_out"].append(twin)
        state = apply(facts._refresh(state))
        self.assertEqual([(item["condition"], item["evidence_turns"]) for item in state["connections_out"]],
                         [("Unresolved or failed screening is escalated.", ["u1", "u2"])])


class ConnectionsNoteTests(unittest.TestCase):
    FA16 = link("hands_off_to", "FA-16", "When funds are short and the status becomes Insufficient Funds.")

    def test_a_recorded_handoff_is_never_unknown_in_the_connections_note(self):
        state = apply(facts.empty_state(), links=[self.FA16])
        row = notes(state, "connections")
        self.assertEqual(row["status"], "partial", "A recorded link is not an unknown topic")
        self.assertEqual(row["answer"], "Hands off to FA-16: When funds are short and the status becomes Insufficient Funds.")
        self.assertEqual(row["evidence_turns"], ["u1"])
        fact = next(fact for fact in state["facts"] if fact["topic"] == "connections")
        self.assertEqual((fact["origin"], fact["kind"], fact["connection_id"]), (facts.STRUCTURED_LINK, "detail", state["connections_out"][0]["id"]))
        self.assertEqual(fact["unverified"], [])
        # Applying the same links again states nothing twice.
        again = apply(state, links=[self.FA16])
        self.assertEqual(notes(again, "connections")["answer"], row["answer"])
        self.assertEqual(sum(fact["topic"] == "connections" and fact["state"] == "active" for fact in again["facts"]), 1)

    def test_a_gap_that_only_mentions_the_counterpart_does_not_stand_in_for_the_link(self):
        gap = operation("connections", "What FA-16 does with the payment afterwards is not specified.", kind="gap")
        state = apply(facts.empty_state(), [gap], [self.FA16], {"connections": "partial"})
        answer = notes(state, "connections")["answer"]
        self.assertIn("Hands off to FA-16: When funds are short", answer)
        self.assertIn("What FA-16 does with the payment afterwards is not specified.", answer, "The narrower uncertainty is retained")

    def test_the_notes_own_wording_replaces_the_restated_link(self):
        state = apply(facts.empty_state(), links=[self.FA16])
        own = operation("connections", "If funds are short, FA-16 takes over the payment.")
        state = apply(state, [own], [self.FA16], {"connections": "partial"})
        self.assertEqual(notes(state, "connections")["answer"], "If funds are short, FA-16 takes over the payment.")
        # A counterpart named in full or by its process code counts as named.
        self.assertTrue(facts._names("Treasury verifies wires under FA-17.", "FA-17 Treasury wire verification"))
        self.assertTrue(facts._names("The Compliance Officer decides.", "compliance officer"))
        self.assertFalse(facts._names("FA-170 is unrelated.", "FA-17 Treasury wire verification"))
        self.assertFalse(facts._names("Anything.", ""))

    def test_a_withdrawn_link_takes_its_statement_with_it(self):
        state = apply(facts.empty_state(), links=[self.FA16])
        identity = state["connections_out"][0]["id"]
        turns = TURNS + [{"id": "u3", "role": "user", "text": "Correction: FA-16 does not take over, Treasury keeps the payment."}]
        state = apply(state, removed=[{"target_id": identity, "evidence_turns": ["u3"]}], turns=turns)
        self.assertEqual(state["connections_out"], [])
        self.assertEqual(notes(state, "connections")["status"], "unknown")
        self.assertEqual(notes(state, "connections")["answer"], "")

    def test_every_link_of_a_capture_reaches_the_note_within_its_bounds(self):
        links = [link("hands_off_to", "FA-07", "Operations communicates clearance.", "u2"),
                 link("requires_approval_from", "Client", ""), link("consumes", "FA-20 AML/KYC", "Clearance is included in the review.", "u2")]
        state = apply(facts.empty_state(), links=links)
        self.assertEqual(notes(state, "connections")["answer"].split("\n"),
                         ["Hands off to FA-07: Operations communicates clearance.", "Requires approval from Client.",
                          "Uses the output of FA-20 AML/KYC: Clearance is included in the review."])
        self.assertEqual(set(facts.CONNECTION_WORDING), set(server.gpfs_interview.RELATIONSHIPS))


class PurposeTests(unittest.TestCase):
    RESTATED = "The stated objective is to document how the process works, including controls and unresolved points."
    BUSINESS = "The work releases approved payments once cash, screening and approvals are confirmed."

    def test_the_interview_goal_is_not_recorded_as_the_purpose_of_the_work(self):
        state = apply(facts.empty_state(), [operation("purpose", self.RESTATED, "context"), operation("purpose", self.BUSINESS)],
                      statuses={"purpose": "captured"})
        row = notes(state, "purpose")
        self.assertEqual(row["answer"], self.BUSINESS)
        self.assertEqual(row["evidence_turns"], ["u1"], "The intake is not cited for the purpose")
        self.assertEqual(row["status"], "captured")
        self.assertNotIn("objective", row["answer"].lower())

    def test_changing_only_the_interview_goal_changes_nothing_in_the_purpose(self):
        results = []
        for goal in (CONTEXT["objective"], "Understand the current process, responsibilities, handoffs, and exceptions."):
            context = {**CONTEXT, "objective": goal}
            restated = "The stated objective is to " + goal[0].lower() + goal[1:]
            state = apply(facts.empty_state(), [operation("purpose", restated, "context"), operation("purpose", self.BUSINESS)],
                          statuses={"purpose": "captured"}, context=context)
            results.append(notes(state, "purpose"))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["answer"], self.BUSINESS)

    def test_without_evidence_of_the_purpose_the_goal_is_an_open_gap_that_evidence_later_retires(self):
        state = apply(facts.empty_state(), [operation("purpose", self.RESTATED, "context")], statuses={"purpose": "captured"})
        row = notes(state, "purpose")
        self.assertEqual((row["answer"], row["status"]), (facts.OBJECTIVE_GAP, "partial"))
        state = apply(state, [operation("purpose", self.BUSINESS)], statuses={"purpose": "captured"})
        self.assertEqual(notes(state, "purpose")["answer"], self.BUSINESS, "The contradicted gap is retired")
        # A ledger saved before this rule is brought in line by its next update.
        legacy = apply(facts.empty_state(), [operation("purpose", self.BUSINESS)], statuses={"purpose": "captured"})
        old = facts._new_fact("purpose", "detail", self.RESTATED, ["context"], facts.sources(CONTEXT, TURNS, []))
        legacy["facts"].insert(0, old)
        legacy = apply(facts._refresh(legacy))
        self.assertEqual(notes(legacy, "purpose")["answer"], self.BUSINESS)

    def test_a_factual_background_can_still_state_the_purpose(self):
        context = {**CONTEXT, "background": "The team releases approved supplier payments for the funds it administers."}
        stated = "The team releases approved supplier payments for the funds it administers."
        state = apply(facts.empty_state(), [operation("purpose", stated, "context")], statuses={"purpose": "partial"}, context=context)
        self.assertEqual(notes(state, "purpose")["answer"], stated)
        # Other topics may cite the intake as before.
        state = apply(facts.empty_state(), [operation("name", "The process is called Payment release.", "context")],
                      statuses={"name": "partial"})
        self.assertEqual(notes(state, "name")["answer"], "The process is called Payment release.")


class ReopenedGapTests(unittest.TestCase):
    """An answer that states a requirement or names another process reopens the gaps it bears on."""

    def seeded(self):
        gaps = [operation("rules", "The governing requirements for release have not been specified.", kind="gap"),
                operation("connections", "No other process has been named.", kind="gap"),
                operation("volume", "Volumes have not been described.", kind="gap")]
        return apply(facts.empty_state(), gaps, statuses={"rules": "partial", "connections": "partial", "volume": "partial"},
                     turns=TURNS[:1])

    def test_a_stated_gate_reopens_the_rules_gap_and_a_named_process_the_connections_gap(self):
        state = self.seeded()
        gate = {"question": "What can go wrong?", "answer": "An unverified wire cannot be used and clearance is a hard gate before accepting capital."}
        self.assertEqual({fact["topic"] for fact in facts.reconciliation_targets(state, gate)}, {"rules"})
        handoff = {"question": "What happens then?", "answer": "If funds are short FA-16 takes over."}
        self.assertEqual({fact["topic"] for fact in facts.reconciliation_targets(state, handoff)}, {"connections"})
        unrelated = {"question": "Who files it?", "answer": "The preparer files the record."}
        self.assertEqual(facts.reconciliation_targets(state, unrelated), [])

    def test_everyday_words_do_not_make_rules_a_topic_the_participant_declined(self):
        # "cannot" scopes which gaps an answer reopens; it does not turn a general
        # inability to confirm something into unavailable knowledge about rules.
        self.assertNotRegex("I cannot confirm that.", facts._gap_scope_pattern("rules"))
        self.assertRegex("The policy says so.", facts._gap_scope_pattern("rules"))

    def test_the_capture_policy_tells_the_lead_to_keep_topics_and_links_in_step(self):
        policy = facts.FACT_CAPTURE_POLICY
        for wording in ("One answer usually bears on several topics", "is the same link", "names a receiving process, not a person",
                        "It is never the purpose of the"):
            self.assertIn(wording, policy)


if __name__ == "__main__":
    unittest.main()
