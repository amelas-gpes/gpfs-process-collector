"""A correct source reference must not turn a contradictory operating rule into evidence."""
import unittest

from test_server import server
from test_route_grounding import step, quote, review


class ControlBindings(unittest.TestCase):
    def check_binding(self, claim, source, expected):
        draft = {"controls": [claim], "field_evidence": [
            {"field": "controls", "index": 0, "text": claim, "evidence_turns": ["u1"]}]}
        server.review_draft_fields(draft, [{"role": "user", "id": "u1", "text": source}], [], {})
        self.assertEqual(bool(draft["field_evidence"]), expected)
        self.assertEqual(draft["controls"][0] == claim, expected)

    def test_preserve_duty_separation_deadline_authority_and_named_owner(self):
        for source, claim, supported in (
            ("Separate authorized operators enter and approve transfers.", "The same operator may enter and approve transfers.", False),
            ("The banking cutoff is unconfirmed.", "The banking cutoff is 16:30.", False),
            ("The banking cutoff is unconfirmed. The department meeting starts at 16:30.", "The banking cutoff is 16:30.", False),
            ("The banking cutoff is 16:30.", "The banking cutoff is 4:30 p.m.", True),
            ("No borrowing is permitted today.", "Borrowing is permitted today.", False),
            ("Live trading isn't permitted until clearance.", "Live trading is authorized today.", False),
            ("The department coordinates, the lender owns covenant decisions.", "The department owns covenant decisions.", False),
            ("The department coordinates, the lender owns covenant decisions.", "The lender is responsible for covenant decisions.", True),
            ("The calculation has no default rounding.", "Always round the calculation upward.", False),
            ("The lender may approve the request. Pricing has not been approved.", "The lender may approve the request.", True),
        ):
            with self.subTest(claim=claim):
                self.check_binding(claim, source, supported)


class RouteOutcomes(unittest.TestCase):
    def check_route(self, source, quote_text, start, target, label, expected):
        nodes = [step("S1", start, sources=("u1",)), step("S2", target, sources=("u1",))]
        edge = {"from": "S1", "to": "S2", "label": label, "evidence_turns": ["u1"]}
        result, gaps = server.grounded_routes([edge], [review([quote("u1", quote_text)], edge)],
                                              nodes, {}, [{"role": "user", "id": "u1", "text": source}], [])
        self.assertEqual(result, [edge] if expected else [])
        self.assertEqual(bool(gaps), not expected)

    def test_stops_waivers_and_negation_apply_to_the_destination(self):
        for source, excerpt, start, target, label, accepted in (
            ("Intake alone does not approve the exception.", "approve the exception", "Log intake", "Approve the exception", "Intake logged", False),
            ("After intake the manager approves the exception.", "manager approves the exception", "Log intake", "Approve the exception", "Intake logged", True),
            ("If the mandate is missing, processing is blocked.", None, "Check mandate", "Execute transfer", "Mandate missing", False),
            ("If the mandate is missing, processing is blocked.", None, "Check mandate", "Pause processing", "Mandate missing", True),
            ("If the ledger is short, we stop. Reconcile the difference and then close the run.",
             "If the ledger is short, we stop.", "Check ledger", "Close the run", "Ledger short", False),
            ("Do not release until Finance approves.", None, "Obtain Finance approval", "Release the package", "Finance approved", True),
            ("Do not release until Finance approves.", None, "Check Finance approval", "Release the package", "Finance approval missing", False),
            ("After changes we re-review the application.", None, "Change application", "Release immediately", "No additional review required", False),
            ("After changes we re-review the application.", None, "Change application", "Review the application again", "Changes recorded", True),
            ("The Controller reviews it under the client's rules. After approval I upload the shareable version and keep the receipt.",
             None, "Review matched support", "Upload shareable version", "After approval", True),
        ):
            with self.subTest(target=target):
                self.check_route(source, excerpt or source, start, target, label, accepted)
