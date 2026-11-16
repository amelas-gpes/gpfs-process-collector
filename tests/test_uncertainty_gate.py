"""The uncertainty gate holds a topic only for wording that says something is not known.

One classifier (interview_coverage.uncertain_wording) serves the lead gate in
server.validate_findings, the dimension gate in interview_coverage.apply_assessment
and the browser's copy in web/app.js. tests/fixtures/uncertainty_gate_cases.json is
run through the server here and through the browser's copy by test_uncertainty_gate.cjs.
"""
import copy
import json
from pathlib import Path
import re
import unittest

from test_server import server
import capture_facts as facts
from test_interview_coverage import fixture
from test_interview_orchestrator import SyntheticTeamProvider, reply_payload
from test_capture_facts import operation, transaction
from test_concurrent_interview import API, FakeClient, module as concurrent, payload as conversation_payload, wait_for

coverage = server.interview_coverage
ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((Path(__file__).with_name("fixtures") / "uncertainty_gate_cases.json").read_text(encoding="utf-8"))
CONFIDENT = [tuple(row) for row in CASES["confident"]]
UNCERTAIN = [tuple(row) for row in CASES["uncertain"]]
HELD_OUT = json.loads((Path(__file__).with_name("fixtures") / "uncertainty_gate_heldout.json").read_text(encoding="utf-8"))
# The masks that read a word as a label or value of the process (see _MENTIONED in interview_coverage.py).
LABEL_MASKS = {"Another listed value", "A listed value", "listed values", "named", "a named value", "takes a named value"}


def gate_status(key, answer, status="captured"):
    findings = [{"key": topic, "status": "captured", "answer": "Synthetic complete topic.", "evidence_turns": ["u1"]}
                for topic in server.COVERAGE]
    finding = next(item for item in findings if item["key"] == key)
    finding.update(status=status, answer=answer)
    turns = [{"id": "u1", "role": "user", "text": "Synthetic participant account."}]
    server.validate_findings(findings, turns)
    return finding["status"], server.memo_has_enough_detail(findings)


class LeadGateTests(unittest.TestCase):
    def test_fixture_is_large_enough_to_mean_something(self):
        self.assertGreaterEqual(len(CONFIDENT), 45)
        self.assertGreaterEqual(len(UNCERTAIN), 55)
        self.assertTrue(all(key in server.COVERAGE for key, *_ in CONFIDENT + UNCERTAIN))

    def test_ordinary_process_wording_keeps_a_captured_topic(self):
        for key, answer in CONFIDENT:
            with self.subTest(key=key, answer=answer):
                self.assertEqual(coverage.uncertain_wording(answer, key), "")
                self.assertEqual(gate_status(key, answer), ("captured", True))

    def test_wording_that_reports_a_knowledge_gap_holds_the_topic_and_is_named(self):
        for key, answer, wording in UNCERTAIN:
            with self.subTest(key=key, answer=answer):
                self.assertEqual(gate_status(key, answer), ("partial", False))
                self.assertTrue(wording, "The fixture names the wording the gate reports")
                self.assertEqual(coverage.uncertain_wording(answer, key), wording)

    def test_not_applicable_reason_is_held_to_the_same_standard(self):
        self.assertEqual(gate_status("variations", "No client differences apply because this is the only fund.",
                                     "not_applicable")[0], "not_applicable")
        self.assertEqual(gate_status("variations", "I think no client differences apply.", "not_applicable")[0], "partial")

    def test_each_fact_line_is_judged_on_its_own(self):
        # The ledger joins a topic's facts with line breaks; a hedge at the end of one
        # fact must not combine with an approval named at the start of the next.
        answer = "A rush call is possible, and clients ask for one maybe\nApproval is recorded by the controller in the register."
        self.assertEqual(coverage.uncertain_wording(answer, "variations"), "")
        answer = "The controller approves the notice.\nThe second approver is unknown."
        self.assertEqual(coverage.uncertain_wording(answer, "checks"), "is unknown")

    def test_topic_specific_literals_stay_scoped_to_their_topics(self):
        literal = "The analyst records the literal value UNKNOWN in the Stage column before the reviewer changes it."
        self.assertEqual(coverage.uncertain_wording(literal, "lifecycle"), "")
        self.assertEqual(coverage.uncertain_wording(literal, "data_systems"), "")
        self.assertEqual(coverage.uncertain_wording(literal, "accountable"), "UNKNOWN")
        self.assertEqual(coverage.uncertain_wording(literal), "UNKNOWN", "No topic means no topic-specific exemption")

    def test_typographic_quotes_and_spaces_read_as_plain_ones(self):
        for answer, wording in (("The storage location is" + chr(0xA0) + "unknown.", "is unknown"),
                                ("I don" + chr(0x2019) + "t" + chr(0x2009) + "know who approves.", "don't know"),
                                ("We can" + chr(0x02BC) + "t recall the approver.", "can't recall"),
                                ("The owner is " + chr(0x201C) + "unclear" + chr(0x201D) + ".", 'is "unclear'),
                                # Dashes too: an en dash, an em dash with and without spaces, a minus sign.
                                ("Storage location " + chr(0x2013) + " unknown.", "Storage location - unknown"),
                                ("Storage location " + chr(0x2014) + " not confirmed.", "Storage location - not confirmed"),
                                ("Storage location" + chr(0x2014) + "unknown.", "unknown"),
                                ("Storage location " + chr(0x2212) + " unclear at present.", "Storage location - unclear")):
            with self.subTest(answer=answer):
                self.assertEqual(coverage.uncertain_wording(answer, "materials"), wording)
                self.assertEqual(gate_status("materials", answer), ("partial", False))

    def test_a_hedged_name_alone_holds_only_where_it_answers_who(self):
        # "Probably the controller." answers who owns (accountable) or who approves and
        # checks (checks). Elsewhere a hedge holds a topic only beside an owner or approver.
        self.assertEqual(coverage.uncertain_wording("Probably the controller.", "accountable"), "Probably")
        self.assertEqual(coverage.uncertain_wording("Probably the controller.", "checks"), "Probably the controller")
        self.assertEqual(coverage.uncertain_wording("The controller, most likely.", "checks"), "The controller, most likely")
        self.assertEqual(coverage.uncertain_wording("Probably the bank's email.", "trigger"), "")
        self.assertEqual(coverage.uncertain_wording("Probably the controller."), "")
        self.assertEqual(coverage.uncertain_wording("The reviewer might return the item to the preparer.", "checks"), "")

    def test_wording_is_a_bounded_excerpt_of_the_answer(self):
        answer = "The approver " + "really " * 80 + "is unknown."
        wording = coverage.uncertain_wording(answer, "checks")
        self.assertEqual(wording, "is unknown")
        self.assertLessEqual(len(wording), 160)
        self.assertEqual(coverage.uncertain_wording("", "checks"), "")
        self.assertEqual(coverage.uncertain_wording(None, "checks"), "")


class ConstructionTests(unittest.TestCase):
    """A rule states a construction, so it holds for the neighbours of the sentences it was written from."""

    SUBJECTS = (("Approver", "checks"), ("Owner", "accountable"), ("Cutoff", "lifecycle"), ("Cutoff time", "lifecycle"),
                ("Volume", "volume"), ("Second approval", "checks"), ("Next step", "lifecycle"),
                ("System of record", "data_systems"))
    CONNECTORS = (": ", " ", " - ", " " + chr(0x2013) + " ", "; ", ", ", " is ", " (", " remains ")
    STATES = ("unknown", "unclear", "uncertain", "unconfirmed", "not confirmed", "not yet confirmed", "not known",
              "not clear", "TBC", "to be confirmed")
    TAILS = ("", " yet", " at this stage", " so far", " at present", " by the participant", " in the interview", " here")

    def test_a_state_noted_after_its_subject_holds_however_it_is_joined_and_whatever_follows(self):
        # r1-gate-1 (a), (b): every round before this one closed the notes it was given and
        # left the same note with a tail ("yet", "at this stage") or another join open.
        passed = [subject + connector + state + tail + (")" if connector == " (" else "") + "."
                  for subject, topic in self.SUBJECTS for connector in self.CONNECTORS for state in self.STATES
                  for tail in self.TAILS
                  if not coverage.uncertain_wording(subject + connector + state + tail + (")" if connector == " (" else "") + ".",
                                                    topic)]
        self.assertEqual(passed, [])

    def test_a_hedge_on_who_approves_holds_wherever_it_stands_in_the_clause(self):
        # r1-gate-1 (c): before the approval, after it, or set apart by commas, brackets or a dash.
        forms = ("Approver: {h} the CFO.", "The approver is {h} the CFO.", "The approver is the CFO, {h}.",
                 "The CFO approves, {h}.", "The CFO, {h}, approves.", "The CFO ({h}) approves.", "Approved by the CFO, {h}.",
                 "{H} the CFO.", "{H} the CFO approves.", "The CFO {h} approves.", "The CFO approves the release, {h}.",
                 "It is {h} the CFO who approves.", "The approver - {h} the CFO.", "Sign-off by the CFO, {h}.",
                 "The CFO signs off, {h}.", "The CFO is {h} the approver.", "{H}, the CFO approves.",
                 "The release is approved by the CFO ({h}).", "Approval comes from the CFO, {h}.",
                 "The CFO is responsible, {h}.", "Owner: the controller ({h}).", "Who approves: {h} the CFO.")
        passed = [form.format(h=hedge, H=hedge.capitalize()) for form in forms
                  for hedge in ("probably", "likely", "possibly", "perhaps", "maybe", "presumably")
                  if not coverage.uncertain_wording(form.format(h=hedge, H=hedge.capitalize()), "checks")]
        self.assertEqual(passed, [])

    def test_the_same_hedges_on_something_else_do_not_hold(self):
        # The other direction: the audit's defect was a hedge or a state word holding a topic
        # whatever it qualified.
        for key, answer in (("lifecycle", "The cutoff is probably 3 p.m."),
                            ("lifecycle", "The clerk probably posts the invoice before the manager approves it."),
                            ("checks", "The controller approves the notice, and the clerk probably files it the same day."),
                            ("checks", "The approver might be away; the deputy then signs in the portal."),
                            ("checks", "The approver may be changed by the controller in the portal."),
                            ("lifecycle", "The clerk uses her own checklist, probably the 2024 version."),
                            ("pain_points", "The approval step is probably where most delays occur."),
                            ("lifecycle", "Wires not confirmed stay in the queue overnight."),
                            ("lifecycle", "Invoices not yet agreed with the buyer are parked in the Hold queue."),
                            ("lifecycle", "The analyst sets the flag to not confirmed and emails the bank."),
                            ("checks", "The amount needs to be confirmed against the signed notice."),
                            ("lifecycle", "Payer unknown, the receipt is posted to suspense.")):
            with self.subTest(answer=answer):
                self.assertEqual(coverage.uncertain_wording(answer, key), "")

    def test_an_assumption_about_who_approves_holds_and_a_cited_convention_does_not(self):
        # r1-gate-1 (d), r1-gate-2 (1), r1-gate-3: the rules-topic exemption for a convention
        # ("a 365-day year is assumed.") must not reach an owner, an approval or a sign-off.
        for answer in ("The owner is assumed.", "The approver is assumed.", "Approval by the CFO is assumed.",
                       "Sign-off by Treasury is assumed.", "Assumption: the CFO approves per the policy.",
                       "The team assumes the CFO approves, per the manager."):
            with self.subTest(answer=answer):
                self.assertTrue(coverage.uncertain_wording(answer, "rules"))
        for answer in ("A 365-day year is assumed.", "For the waterfall, full distribution is assumed.",
                       "Assumption: a 30/360 day count per the LPA.", "Under the LPA, capital is presumed returned first.",
                       "The interface assumes that every investor has one bank account."):
            with self.subTest(answer=answer):
                self.assertEqual(coverage.uncertain_wording(answer, "rules"), "")
        self.assertTrue(coverage.uncertain_wording("A 365-day year is assumed.", "lifecycle"), "Only the rules topic")

    def test_a_step_recurs_with_the_process_and_an_open_point_waits_on_the_next_interview(self):
        # r1-gate-2 (2), (3): the exemptions for a step and for "until" an event of the process
        # must not release what waits on asking somebody.
        for key, answer in (("accountable", "The owner needs to be confirmed before the report is final."),
                            ("checks", "The approver needs to be confirmed via Treasury."),
                            ("accountable", "The owner needs to be confirmed within the next week."),
                            ("checks", "Who signs is unknown until the controller is interviewed."),
                            ("lifecycle", "The cutoff is unknown until the follow-up interview."),
                            ("lifecycle", "The cutoff is not confirmed until the next session."),
                            ("lifecycle", "The cutoff is to be confirmed in the next session.")):
            with self.subTest(answer=answer):
                self.assertTrue(coverage.uncertain_wording(answer, key))
        for key, answer in (("checks", "The approver needs to be identified in the portal before the wire is released."),
                            ("accountable", "The owner has to be confirmed by the steering group each year."),
                            ("rules", "The final amount is unknown until the bank file loads."),
                            ("lifecycle", "Payment to the vendor is not confirmed until the bank file loads."),
                            ("rules", "The rate is to be determined by the valuation committee each quarter.")):
            with self.subTest(answer=answer):
                self.assertEqual(coverage.uncertain_wording(answer, key), "")

    def test_a_word_is_a_label_only_beside_what_names_it_as_one(self):
        # r1-gate-3: a status, a bucket, a list or a legend of values cannot be reworded away.
        for key, answer in (("data_systems", "The tracker has a status called \"unconfirmed\" for wires awaiting callback."),
                            ("data_systems", "Items in the 'Unknown' bucket are reviewed weekly."),
                            ("lifecycle", "The Payer (Unknown) bucket holds unmatched receipts."),
                            ("data_systems", "The Type column takes one of: known, unknown, disputed."),
                            ("lifecycle", "Pending: awaiting callback. Confirmed: released. Not confirmed: returned to the preparer."),
                            ("data_systems", "The default category is Unknown.")):
            with self.subTest(answer=answer):
                self.assertEqual(coverage.uncertain_wording(answer, key), "")
        # Quotation marks, a capital or a list alone do not make one, nor does a value that
        # stands where an owner or approver should be.
        for key, answer in (("materials", "The owner is \"unclear\"."), ("accountable", "Owner: Unknown."),
                            ("lifecycle", "Owner, approver, unknown."), ("lifecycle", "Statuses: unknown."),
                            ("data_systems", "The approval status is Unknown."),
                            ("accountable", "The owner field is marked \"unknown\"."),
                            ("data_systems", "The status of the second approver is \"unknown\"."),
                            ("checks", "Unconfirmed: second approval.")):
            with self.subTest(answer=answer):
                self.assertTrue(coverage.uncertain_wording(answer, key))

    def test_no_gap_sentence_passes_or_is_touched_because_a_word_is_read_as_a_label(self):
        masks = [pattern for _, pattern, replacement in coverage.UNCERTAINTY_MASKS if replacement in LABEL_MASKS]
        self.assertEqual(len(masks), 10, "Every label mask is checked")
        gaps = [answer for _, answer, _ in UNCERTAIN] + [answer for part in ("first", "second")
                                                         for decision, _, answer in HELD_OUT[part]["sentences"]
                                                         if decision == "hold"]
        self.assertGreater(len(gaps), 300)
        touched = [answer for answer in gaps
                   if any(pattern.search(answer.translate(coverage._GATE_PUNCTUATION)) for pattern in masks)]
        self.assertEqual(touched, [])

    def test_sentences_written_after_the_rules_were_final_are_decided_as_labelled(self):
        for part, size in (("first", 72), ("second", 64)):
            sentences = [tuple(row) for row in HELD_OUT[part]["sentences"]]
            self.assertEqual(len(sentences), size)
            self.assertEqual(sum(1 for decision, *_ in sentences if decision == "hold") * 2, size, "Half hold, half pass")
            self.assertTrue(set(HELD_OUT[part]["missed_when_written"]) <= {answer for *_, answer in sentences})
            for decision, key, answer in sentences:
                with self.subTest(part=part, answer=answer):
                    self.assertIn(key, server.COVERAGE)
                    self.assertEqual(bool(coverage.uncertain_wording(answer, key)), decision == "hold")
                    self.assertEqual(gate_status(key, answer)[0], "partial" if decision == "hold" else "captured")

    def test_rows_held_by_cost_are_rows_of_the_corpus(self):
        uncertain = {answer for _, answer, _ in UNCERTAIN}
        for answer, reason in CASES["held_by_cost"]:
            with self.subTest(answer=answer):
                self.assertIn(answer, uncertain)
                self.assertTrue(reason)


class DimensionGateTests(unittest.TestCase):
    """The reviewer's dimension details pass through the same classifier as the lead's findings."""

    def assess(self, key, detail):
        findings, assessment, turns = fixture()
        local = next(item for item in assessment["topics"] if item["key"] == key)
        local["dimensions"][0]["detail"] = detail
        revised, public = coverage.apply_assessment(findings, assessment, turns)
        topic = next(item for item in public["topics"] if item["key"] == key)
        return (topic["dimensions"][0]["status"], topic["complete"],
                next(item for item in revised if item["key"] == key)["status"])

    def test_ordinary_process_wording_in_a_supported_dimension_stays_supported(self):
        for key, detail in CONFIDENT:
            with self.subTest(key=key, detail=detail):
                self.assertEqual(self.assess(key, detail), ("supported", True, "captured"))

    def test_knowledge_gap_wording_in_a_supported_dimension_becomes_unresolved(self):
        for key, detail, _ in UNCERTAIN:
            with self.subTest(key=key, detail=detail):
                self.assertEqual(self.assess(key, detail), ("unresolved", False, "partial"))

    def test_rejected_counterclaim_is_still_not_an_asserted_gap(self):
        rejected = ("There is no variation being assessed for charging. The participant explicitly distinguishes "
                    "this from saying that a particular difference is free or that billing is unknown.")
        self.assertFalse(coverage.repair_has_uncertainty(rejected, "variations"))
        self.assertTrue(coverage.repair_has_uncertainty(rejected + " But the accountable owner is unknown.", "variations"))

    def test_repair_answers_use_the_topic_exemptions_of_the_lead_gate(self):
        literal = "The analyst records the literal value UNKNOWN in the Stage column before the reviewer changes it."
        self.assertFalse(coverage.repair_has_uncertainty(literal, "lifecycle"))
        self.assertTrue(coverage.repair_has_uncertainty(literal, "accountable"))
        self.assertTrue(coverage.repair_has_uncertainty(literal))


class BrowserCopyTests(unittest.TestCase):
    """web/app.js carries a copy of the two tables; this fails as soon as either side changes alone."""

    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def block(self, name):
        match = re.search(r"const " + name + r" = \[\r?\n(.*?)\r?\n  \];", self.source, re.S)
        self.assertIsNotNone(match, f"web/app.js must define {name} as one row per line")
        return [line.strip() for line in match.group(1).splitlines() if line.strip() and not line.strip().startswith("//")]

    def test_mask_table_is_identical(self):
        rows = []
        for line in self.block("uncertaintyMasks"):
            match = re.fullmatch(r'\[(null|\[[^\]]*\]), /(.+)/(gi?), "([^"]*)"\],?', line)
            self.assertIsNotNone(match, line)
            topics = None if match.group(1) == "null" else tuple(json.loads(match.group(1)))
            rows.append((topics, match.group(2), "i" in match.group(3), match.group(4)))
        expected = [(topics, pattern.pattern, bool(pattern.flags & re.IGNORECASE), replacement)
                    for topics, pattern, replacement in coverage.UNCERTAINTY_MASKS]
        self.assertEqual(rows, expected)

    def test_rule_table_is_identical(self):
        rows = []
        for line in self.block("uncertaintyRules"):
            match = re.fullmatch(r'\["([a-z_]+)", (null|\[[^\]]*\]), /(.+)/(i?)\],?', line)
            self.assertIsNotNone(match, line)
            topics = None if match.group(2) == "null" else tuple(json.loads(match.group(2)))
            rows.append((match.group(1), topics, match.group(3), match.group(4) == "i"))
        expected = [(name, topics, pattern.pattern, bool(pattern.flags & re.IGNORECASE))
                    for name, topics, pattern in coverage.UNCERTAINTY_RULES]
        self.assertEqual(rows, expected)
        self.assertEqual(len({name for name, *_ in coverage.UNCERTAINTY_RULES}), len(coverage.UNCERTAINTY_RULES))

    def test_plain_punctuation_tables_are_identical(self):
        def numbers(name):
            match = re.search(r"const " + name + r" = \[([^;]*)\];", self.source)
            self.assertIsNotNone(match, name)
            return [int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]+)", match.group(1))]
        self.assertEqual(numbers("uncertaintySpaces"), list(coverage.UNCERTAINTY_SPACES))
        self.assertEqual(numbers("uncertaintyQuotes"),
                         [number for source, plain in coverage.UNCERTAINTY_QUOTES for number in (source, ord(plain))])

    def test_patterns_use_only_syntax_both_engines_read_the_same_way(self):
        patterns = ([pattern for _, pattern, _ in coverage.UNCERTAINTY_MASKS]
                    + [pattern for _, _, pattern in coverage.UNCERTAINTY_RULES])
        for pattern in patterns:
            with self.subTest(pattern=pattern.pattern):
                self.assertTrue(pattern.flags & re.ASCII, "Browser \\w, \\b and \\s are ASCII; the server must match")
                self.assertNotRegex(pattern.pattern, r"\(\?P|\(\?[aiLmsux]|\\[AZ]|/|\$|\\n",
                                    "No Python-only groups, inline flags, anchors, slashes or line breaks")
                self.assertTrue(pattern.pattern.isascii())
        for topics, _, replacement in coverage.UNCERTAINTY_MASKS:
            self.assertNotRegex(replacement, r"[$\\\x22]", "A replacement is plain text in both engines")
            self.assertTrue(topics is None or set(topics) <= set(server.COVERAGE))
        self.assertTrue(all(topics is None or set(topics) <= set(server.COVERAGE)
                            for _, topics, _ in coverage.UNCERTAINTY_RULES))

    def test_browser_applies_the_shared_gate_and_no_older_word_list(self):
        self.assertNotIn("uncertainMemo", self.source)
        self.assertRegex(self.source, r"uncertainWording\(key,\s*answer\)")


class LedgerVisibilityTests(unittest.TestCase):
    """A hold is recorded with its wording so the lead is told why the topic stayed partial."""

    def setUp(self):
        self.context = {"process_name": "Capital call"}
        self.turns = [{"id": "a1", "role": "assistant", "text": "Who owns the overall result?"},
                      {"id": "u1", "role": "user", "text": "The controller, most likely. The CFO signs the notice."}]

    def capture(self, state):
        result = {"memo_findings": facts.findings(state)}
        server.validate_findings(result["memo_findings"], self.turns)
        return result

    def seeded(self, text="The overall owner is likely the controller."):
        state = facts.empty_state()
        delta = transaction(state, [operation("accountable", "The CFO signs the notice."), operation("accountable", text)],
                            {"accountable": "captured"})
        server.check_schema(delta, facts.FACT_DELTA_SCHEMA)
        return facts.apply_delta(state, delta, self.context, self.turns, [])

    def test_hold_names_the_wording_and_the_fact_and_reaches_the_model(self):
        state = self.seeded()
        self.assertEqual(state["topics"]["accountable"]["status"], "captured", "The lead proposed a captured topic")
        capture = self.capture(state)
        self.assertEqual(next(item["status"] for item in capture["memo_findings"] if item["key"] == "accountable"), "partial")
        held = facts.sync_review(state, capture, self.context, self.turns, [])
        fact = next(item for item in held["facts"] if "likely" in item["text"])
        self.assertEqual(held["topics"]["accountable"], {"status": "partial", "discussed": True, "participant_unavailable": False,
                         "held_for_wording": {"fact_id": fact["id"], "wording": "owner is likely"}})
        self.assertNotEqual(held["revision"], state["revision"])
        model = facts.model_state(held)
        self.assertEqual(model["topics"]["accountable"]["held_for_wording"], {"fact_id": fact["id"], "wording": "owner is likely"})
        self.assertIn(fact["id"], model["reconciliation_targets"])
        self.assertEqual([item["id"] for item in facts.reconciliation_targets(held)], [fact["id"]])
        self.assertIn("held_for_wording", facts.FACT_CAPTURE_POLICY)

    def test_held_fact_follows_the_scoped_reconciliation_rule(self):
        held = facts.sync_review(self.seeded(), self.capture(self.seeded()), self.context, self.turns, [])
        self.turns += [{"id": "a2", "role": "assistant", "text": "Where is the template kept?"},
                       {"id": "u2", "role": "user", "text": "On the shared drive."}]
        self.assertEqual(facts.reconciliation_targets(held, facts.turn_focus(self.turns)), [],
                         "An answer about something else needs no reconciliation row")
        self.turns += [{"id": "a3", "role": "assistant", "text": "Who owns the overall result?"},
                       {"id": "u3", "role": "user", "text": "The controller owns it."}]
        focus = facts.turn_focus(self.turns)
        self.assertEqual(len(facts.reconciliation_targets(held, focus)), 1)
        self.assertEqual(facts.schema_for(held, facts.sources(self.context, self.turns, []), focus)
                         ["properties"]["fact_reconciliations"]["maxItems"], 1)

    def test_rewording_or_resolving_the_fact_releases_the_hold(self):
        state = self.seeded()
        held = facts.sync_review(state, self.capture(state), self.context, self.turns, [])
        target = held["topics"]["accountable"]["held_for_wording"]["fact_id"]
        self.turns += [{"id": "a2", "role": "assistant", "text": "Who owns the overall result?"},
                       {"id": "u2", "role": "user", "text": "The controller owns it."}]
        delta = transaction(held, [operation("accountable", "The controller owns the overall result.", "u2",
                                             op="replace", target=target, reason="participant_correction")],
                            {"accountable": "captured"})
        after = facts.apply_delta(held, delta, self.context, self.turns, [])
        self.assertNotIn("held_for_wording", after["topics"]["accountable"])
        capture = self.capture(after)
        self.assertEqual(next(item["status"] for item in capture["memo_findings"] if item["key"] == "accountable"), "captured")
        released = facts.sync_review(after, capture, self.context, self.turns, [])
        self.assertEqual(released["topics"]["accountable"], {"status": "captured", "discussed": True, "participant_unavailable": False})
        self.assertEqual(facts.reconciliation_targets(released), [])

    def test_hold_lasts_while_the_lead_leaves_the_fact_unchanged(self):
        # The lead obeys the note (it does not propose the same wording as complete again)
        # and leaves the fact alone. The note and the reconciliation target must still be
        # there on the turns after, or the same proposal can simply come back.
        state = self.seeded()
        held = facts.sync_review(state, self.capture(state), self.context, self.turns, [])
        hold = held["topics"]["accountable"]["held_for_wording"]
        for number, (asked, answered, topic, text) in enumerate((
                ("Where is the template kept?", "On the shared drive.", "materials", "The template is kept on the shared drive."),
                ("Who sends the notice?", "The analyst sends it.", "lifecycle", "The analyst sends the notice.")), 2):
            with self.subTest(turn=number):
                self.turns += [{"id": f"a{number}", "role": "assistant", "text": asked},
                               {"id": f"u{number}", "role": "user", "text": answered}]
                focus = facts.turn_focus(self.turns)
                scoped = {**held, "reconciliation_targets": [fact["id"] for fact in facts.reconciliation_targets(held, focus)]}
                delta = transaction(scoped, [operation(topic, text, f"u{number}")], {"accountable": "partial"})
                held = facts.apply_delta(held, delta, self.context, self.turns, [], focus)
                self.assertEqual(held["topics"]["accountable"].get("held_for_wording"), hold)
                held = facts.sync_review(held, self.capture(held), self.context, self.turns, [])
                self.assertEqual(held["topics"]["accountable"]["status"], "partial")
                self.assertEqual(held["topics"]["accountable"].get("held_for_wording"), hold)
                model = facts.model_state(held)
                self.assertEqual(model["topics"]["accountable"]["held_for_wording"], hold, "The lead still sees the note")
                self.assertIn(hold["fact_id"], model["reconciliation_targets"])
        # It ends when the fact is retired, even though the topic stays partial.
        self.turns += [{"id": "a9", "role": "assistant", "text": "Who owns the overall result?"},
                       {"id": "u9", "role": "user", "text": "I was wrong about the controller; forget that."}]
        delta = transaction(held, [operation("accountable", "", "u9", op="remove", target=hold["fact_id"],
                                             reason="participant_correction")], {"accountable": "partial"})
        after = facts.apply_delta(held, delta, self.context, self.turns, [])
        self.assertNotIn("held_for_wording", after["topics"]["accountable"])
        after = facts.sync_review(after, self.capture(after), self.context, self.turns, [])
        self.assertNotIn("held_for_wording", after["topics"]["accountable"])

    def test_no_hold_is_invented_for_other_reasons_a_topic_is_partial(self):
        # A proposed partial, an explicit gap and a review demotion are not wording holds.
        state = self.seeded("The controller owns the overall result.")
        capture = self.capture(state)
        next(item for item in capture["memo_findings"] if item["key"] == "accountable")["status"] = "partial"
        reviewed = facts.sync_review(state, capture, self.context, self.turns, [])
        self.assertEqual(reviewed["topics"]["accountable"], {"status": "partial", "discussed": True, "participant_unavailable": False})
        state = facts.empty_state()
        delta = transaction(state, [operation("accountable", "The overall owner is unknown.", kind="gap")], {"accountable": "captured"})
        state = facts.apply_delta(state, delta, self.context, self.turns, [])
        reviewed = facts.sync_review(state, self.capture(state), self.context, self.turns, [])
        self.assertNotIn("held_for_wording", reviewed["topics"]["accountable"])


class ConversationAdviceTests(unittest.TestCase):
    """Ordinary concurrent turns rebuild the capture without a ledger; the question model is told instead."""

    class GateAPI(API):
        interview_coverage = coverage

    def advice(self, api, findings):
        service = concurrent.ConcurrentInterview(FakeClient(), api)
        self.addCleanup(service.close)
        value = conversation_payload()
        first = service.turn(value)
        value["conversation_token"] = first["conversation_token"]
        wait_for(lambda: service.status(value)["state"] == "ready")
        session = service._sessions[first["conversation_token"]]
        session["capture"].update(memo_findings=findings)
        return service._question_input(session, value, value["context"], value["turns"])["analysis_advice"]["topics"]

    def test_question_model_sees_the_wording_that_keeps_a_topic_open(self):
        findings = [{"key": "checks", "status": "partial", "answer": "The second approver is probably the AP manager.",
                     "evidence_turns": ["u1"]},
                    {"key": "lifecycle", "status": "partial", "answer": "The clerk logs each invoice.", "evidence_turns": ["u1"]},
                    {"key": "accountable", "status": "captured", "answer": "The AP manager owns the result.",
                     "evidence_turns": ["u1"]}]
        topics = {topic["key"]: topic for topic in self.advice(self.GateAPI, findings)}
        self.assertEqual(topics["checks"]["unresolved_wording"], "approver is probably")
        self.assertNotIn("unresolved_wording", topics["lifecycle"], "A partial topic with no such wording says nothing")
        self.assertNotIn("unresolved_wording", topics["accountable"])
        self.assertIn("unresolved_wording", concurrent.QUESTION_POLICY)

    HEDGED = [{"key": "checks", "status": "partial", "answer": "The second approver is probably the AP manager.",
               "evidence_turns": ["u1"]},
              {"key": "lifecycle", "status": "partial", "answer": "The clerk logs each invoice.", "evidence_turns": ["u1"]},
              {"key": "accountable", "status": "captured", "answer": "The AP manager owns the result.", "evidence_turns": ["u1"]}]

    def next_capture_request(self, api):
        client = FakeClient()
        service = concurrent.ConcurrentInterview(client, api)
        self.addCleanup(service.close)
        value = conversation_payload()
        first = service.turn(value)
        value["conversation_token"] = first["conversation_token"]
        wait_for(lambda: service.status(value)["state"] == "ready")
        self.assertNotIn("_held_wording", client.captures[0], "Nothing was captured before the first turn")
        service._sessions[first["conversation_token"]]["capture"].update(memo_findings=copy.deepcopy(self.HEDGED))
        value["turns"] += [{"id": "a2", "role": "assistant", "text": "Who is the second approver?"},
                           {"id": "u2", "role": "user", "text": "The AP manager."}]
        service.turn(value)
        wait_for(lambda: len(client.captures) == 2)
        return client.captures[1]

    def test_fact_capturing_lead_is_told_the_wording_that_held_a_topic_on_the_previous_capture(self):
        # A concurrent capture that cannot continue the previous private ledger (it
        # expired, or the account was edited) would never show its held_for_wording note
        # to the lead, so the wording always travels with the request as well.
        request = self.next_capture_request(self.GateAPI)
        self.assertEqual(request["_held_wording"], [{"topic": "checks", "wording": "approver is probably"}])
        # The session's own capability, for the ledger alone (orchestrator-2): the
        # Coordinator repeats the wording to the lead only when it finds no ledger.
        self.assertEqual((request["capture_token"], request["_facts_only"]), ("server-owned-capability", True))
        self.assertNotIn("_held_wording", self.next_capture_request(API), "Unchanged without the shared classifier")

    def test_advice_is_unchanged_without_the_shared_classifier(self):
        findings = [{"key": "checks", "status": "partial", "answer": "The approver is unknown.", "evidence_turns": ["u1"]}]
        self.assertEqual(self.advice(API, findings), [{"key": "checks", "status": "partial", "answer": "The approver is unknown.",
                         "evidence_turns": ["u1"], "gaps": [], "participant_unavailable": False}])


class CoordinatorTests(unittest.TestCase):
    """The shipped /api/interview path, with the repository's schema-routed offline provider."""

    def run_first_turn(self, sentence):
        client = SyntheticTeamProvider()
        finding = next(item for item in client.findings if item["key"] == "checks")
        finding["answer"] += " " + sentence
        next(item for item in client.turns if item["id"] == "u_checks")["text"] += " " + sentence
        seen = []
        client.hooks["team_interview_capture"] = lambda body: seen.append(json.loads(body["input"][0]["content"]))
        payload = client.payload()
        return client, payload, client.coordinator.interview(copy.deepcopy(payload)), seen

    def test_a_fully_described_control_reaches_the_completion_review(self):
        for sentence in ("Each payment requires confirmation from a second approver in the bank portal before release.",
                         "Invoices not confirmed by the supplier by Friday are chased by the analyst.",
                         "Unknown suppliers are created in the register by the AP manager."):
            with self.subTest(sentence=sentence):
                client, payload, result, _ = self.run_first_turn(sentence)
                statuses = {item["key"]: item["status"] for item in result["memo_findings"]}
                self.assertEqual(statuses["checks"], "captured")
                self.assertEqual(result["speech_authorization"]["kind"], "review_pending")
                self.assertIn("review_ticket", result)

    def test_a_capture_without_a_ledger_passes_the_previous_held_wording_to_the_lead(self):
        client = SyntheticTeamProvider()
        seen = []
        client.hooks["team_interview_capture"] = lambda body: seen.append(json.loads(body["input"][0]["content"]))
        payload = client.payload()
        payload["_held_wording"] = [{"topic": "checks", "wording": "approver is probably"}, {"topic": "not-a-topic", "wording": "x"},
                                    {"topic": "risk", "wording": "y" * 161}, {"topic": "risk", "wording": 7}, "malformed"]
        first = client.coordinator.interview(copy.deepcopy(payload))
        self.assertEqual(seen[0]["held_wording"], [{"topic": "checks", "wording": "approver is probably"}])
        self.assertNotIn("_held_wording", seen[0])
        self.assertIn("held_wording, when present", facts.FACT_CAPTURE_POLICY)
        self.assertNotIn("held_wording", json.dumps(first), "It is advice for the lead, not part of the published capture")
        # With the ledger of the previous capture the note travels in fact_state instead.
        follow = reply_payload(payload, first, "Nothing changes.")
        follow.pop("review_ticket", None)
        client.coordinator.interview(follow)
        self.assertIn("previous_capture", seen[1])
        self.assertNotIn("held_wording", seen[1])
        plain = client.payload()
        client.coordinator.interview(plain)
        self.assertNotIn("held_wording", seen[2])

    def test_a_hedged_approver_is_held_and_the_lead_is_told_which_wording(self):
        client, payload, first, seen = self.run_first_turn("The second approver is probably the AP manager.")
        statuses = {item["key"]: item["status"] for item in first["memo_findings"]}
        self.assertEqual(statuses["checks"], "partial")
        self.assertEqual(first["speech_authorization"]["kind"], "question")
        self.assertNotIn("review_ticket", first)
        self.assertNotIn("held_for_wording", json.dumps(first), "The private ledger note is not published to the browser")
        follow = reply_payload(payload, first, "The second approver is the AP manager; that is the whole check.")
        second = client.coordinator.interview(follow)
        state = seen[1]["fact_state"]
        hold = state["topics"]["checks"]["held_for_wording"]
        self.assertEqual(hold["wording"], "approver is probably")
        fact = next(item for item in state["facts"] if item["id"] == hold["fact_id"])
        self.assertEqual(fact["text"], "The second approver is probably the AP manager.")
        self.assertIn(hold["fact_id"], state["reconciliation_targets"])
        self.assertEqual([key for key, topic in state["topics"].items() if "held_for_wording" in topic], ["checks"])
        self.assertEqual(second["speech_authorization"]["kind"], "question", "Repeating the hedge keeps the hold")
        # The lead now states the confirmed fact plainly: the hold is released and review starts.
        finding = next(item for item in client.findings if item["key"] == "checks")
        finding["answer"] = finding["answer"].replace("is probably the AP manager", "is the AP manager")
        third_payload = reply_payload(follow, second, "Yes, the AP manager.")
        third_payload["turns"][-2]["id"], third_payload["turns"][-1]["id"] = "a_confirm", "u_confirm"
        third = client.coordinator.interview(third_payload)
        self.assertEqual(third["speech_authorization"]["kind"], "review_pending")
        self.assertIn("review_ticket", third)
        self.assertEqual(seen[2]["fact_state"]["topics"]["checks"]["held_for_wording"], hold,
                         "The lead saw the same hold when it reworded the fact")
        self.assertEqual(client.request.call_count, 3)
        private = client.coordinator._captures[third["capture_token"]]["fact_state"]
        self.assertFalse(any("held_for_wording" in topic for topic in private["topics"].values()))


if __name__ == "__main__":
    unittest.main()
