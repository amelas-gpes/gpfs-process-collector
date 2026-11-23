"""Focused offline tests for the interviewer's trust boundaries.

Run with the existing Python runtime; these tests never send model requests.
"""

import copy
import errno
from html.parser import HTMLParser
import http.client
import importlib.util
import io
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, Mock, patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("voice_interviewer_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)


def coverage_topic_properties(schema):
    item = schema["properties"]["topics"]["items"]
    return [branch["properties"] for branch in item.get("anyOf", [item])]


def interview_payload():
    return {
        "context": {
            "process_name": "Invoice approval",
            "process_owner": "AP team",
            "objective": "Capture the current process and its exceptions",
            "background": "Synthetic test fixture, not an actual company process",
            "meeting_minutes": 60,
        },
        "turns": [
            {"id": "a1", "role": "assistant", "text": "What starts the process?"},
            {
                "id": "u1",
                "role": "user",
                "text": "An AP clerk checks the shared mailbox each weekday and logs invoices in a spreadsheet.",
            },
            {"id": "a2", "role": "assistant", "text": "What happens next?"},
            {
                "id": "u2",
                "role": "user",
                "text": "A manager approves by email. Invoices that do not match the purchase order go to the buyer.",
            },
        ],
        "action": "answer",
        "session": {"elapsed_minutes": 12},
    }


def memo_findings():
    findings = [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                for key in server.COVERAGE]
    by_key = {finding["key"]: finding for finding in findings}
    # A supplied title does not establish alternate names or the complete name topic.
    by_key["name"].update(status="partial", answer="Invoice approval", evidence_turns=["context"])
    by_key["lifecycle"].update(status="partial", answer="Invoices are logged by the AP clerk, then approved by a manager or referred to the buyer.", evidence_turns=["u1", "u2"])
    return findings


def interview_result():
    return {
        "question": "Who releases payment after the manager approves?",
        "summary": "The AP clerk logs invoices and a manager approves by email.",
        "ready_for_draft": True,
        "focus": "Understand the normal invoice route and its finish condition",
        "parking_lot": ["Payment-release ownership remains unknown"],
        "closure": {"asked": False, "confirmed": False},
        "memo_findings": memo_findings(),
        "coverage": [{"key": key, "label": label, "status": "partial"} for key, label in server.COVERAGE.items()],
    }


def incomplete_assessment(findings):
    """Conservative offline review fixture; it makes no semantic completeness claim."""
    return {"topics": [{"key": finding["key"], "explanation": finding["answer"],
                         "evidence_turns": list(finding["evidence_turns"]),
                         "dimensions": [{"key": key, "status": "unresolved",
                                         "detail": "This dimension needs further participant detail.",
                                         "evidence_turns": list(finding["evidence_turns"])}
                                        for key in server.interview_coverage.TOPIC_DIMENSIONS[finding["key"]]],
                         "gaps": ["The partial test account does not establish this complete section."],
                         "next_question": "", "participant_unavailable": False,
                         "unavailable_evidence_turns": [], "not_applicable_reason": "",
                         "not_applicable_evidence_turns": []} for finding in findings]}


def process_variation(evidence=None):
    return {
        "applies_to": "Fund B",
        "difference": "Unmatched invoices are routed to the buyer in a ticketing tool.",
        "reason": "UNKNOWN", "cost": "UNKNOWN", "charging": "UNKNOWN", "removability": "UNKNOWN",
        "boundary": "variation", "boundary_reason": "The participant reported that the trigger, accountable role, and finished result remain the same.",
        "evidence_turns": evidence if evidence is not None else ["u3"],
    }


def fixture_route_support(edges, turns):
    """Synthetic auditor passages for fixtures that exercise an accepted route."""
    sources = {turn["id"]: turn["text"] for turn in turns if turn["role"] == "user"}
    return [{**{key: edge[key] for key in ("from", "to", "label")},
             "passages": [{"source_id": ref, "quote": sources[ref]} for ref in edge["evidence_turns"] if ref in sources]}
            for edge in edges]


def fixture_workflow_audit(candidate, turns, inherited=()):
    routes = {server.route_key(edge): edge for edge in [*inherited, *candidate["upsert_connections"]]}
    return {**{key: copy.deepcopy(candidate[key]) for key in ("title", "open_questions", "summary", "focus", "parking_lot")},
            "discard_step_upserts": [], "discard_connection_upserts": [], "discard_step_removals": [],
            "discard_connection_removals": [], "remove_connections": [], "upsert_steps": [], "upsert_connections": [], "memo_findings": [],
            "route_support": fixture_route_support(routes.values(), turns)}


def fixture_draft_audit(draft, turns):
    return {**copy.deepcopy(draft), "route_support": fixture_route_support(draft["connections"], turns)}


def process_draft():
    return {
        "title": "Invoice approval",
        "overview": "Draft based on a synthetic interview; requires process-owner review.",
        "trigger": "Invoices arrive in the shared mailbox",
        "inputs": ["Invoices", "Purchase orders"],
        "outputs": ["Email approval or referral to the buyer"],
        "steps": [
            {
                "id": "s1", "title": "Log received invoices", "type": "activity",
                "actor": "AP clerk", "system": "Shared mailbox and spreadsheet",
                "description": "Check the shared mailbox each weekday and log invoices.",
                "evidence_turns": ["u1"],
                "input": "Invoice received in the shared mailbox", "output": "Logged invoice",
                "completion_criteria": "Invoice has been logged in the spreadsheet", "handoff": "Manager; submission method UNKNOWN",
            },
            {
                "id": "s2", "title": "Approve invoice", "type": "activity",
                "actor": "Manager", "system": "Email",
                "description": "Approve the invoice by email.", "evidence_turns": ["u2"],
                "input": "Invoice", "output": "Email approval", "completion_criteria": "Approval sent by email",
                "handoff": "UNKNOWN; payment-release owner not established",
            },
        ],
        "connections": [{"from": "s1", "to": "s2", "label": "Submitted for approval", "evidence_turns": ["u1", "u2"]}],
        "exceptions": ["Invoices that do not match the purchase order go to the buyer."],
        "controls": [],
        "open_questions": ["Who releases payment, and what checks do they perform?"],
        "validation_notes": ["No payment-release role or control was provided."],
        "memo_summary": memo_findings(),
        "lifecycle_items": [{"item": "Invoice", "stages": ["Received", "Logged", "Manager approval"],
                             "locations": ["Shared mailbox", "Spreadsheet", "Email"],
                             "handoffs": ["AP clerk to manager"], "evidence_turns": ["u1", "u2"]}],
        "variations": [],
    }


class EvidenceValidationTests(unittest.TestCase):
    def test_file_notifications_are_not_participant_answers_or_evidence(self):
        event = {"id": "file_notice", "role": "user", "text": "A supplied file claims manager approval.", "document_event": True}
        payload = interview_payload()
        payload["turns"].append(event)
        _, turns = server.validate_payload(payload)
        self.assertNotIn(event["id"], {turn["id"] for turn in turns})
        payload["turns"] = [event]
        with self.assertRaisesRegex(ValueError, "at least one interview answer"):
            server.validate_payload(payload, require_answers=True)
        raw_turns = interview_payload()["turns"] + [event]
        result = interview_result()
        result["memo_findings"][0].update(status="captured", answer="The manager approves.", evidence_turns=[event["id"]])
        with self.assertRaisesRegex(ValueError, "non-participant evidence"):
            server.validate_interview(result, raw_turns)
        draft = process_draft()
        draft["steps"][0]["evidence_turns"] = [event["id"]]
        with self.assertRaisesRegex(ValueError, "non-participant evidence"):
            server.validate_draft(draft, raw_turns)
        workflow = {key: draft[key] for key in ("title", "steps", "connections", "open_questions")}
        with self.assertRaisesRegex(ValueError, "non-participant evidence"):
            server.validate_workflow(workflow, raw_turns)

    def test_explicit_uncertainty_overrides_full_circle_and_allows_later_clarification(self):
        cases = ["The owner is probably the fund controller.", "The trigger is UNKNOWN.",
                 "We don't know who approves it.", "This is an assumed practice.",
                 "The participants gave conflicting accounts.", "It needs confirmation.",
                 "I cannot identify the final accountable owner yet.",
                 "I am unable to identify the final accountable owner.",
                 "I do not know whether this is approved.", "The owner is not established."]
        for uncertain in cases:
            with self.subTest(uncertain=uncertain):
                result = interview_result()
                result['memo_findings'] = [{'key': key, 'status': 'captured',
                    'answer': 'Reported detail.', 'evidence_turns': ['u1']} for key in server.COVERAGE]
                result['memo_findings'][0]['answer'] = uncertain
                validated = server.validate_interview(result, interview_payload()['turns'])
                self.assertEqual(validated['memo_findings'][0]['status'], 'partial')
                self.assertEqual(validated['coverage'][0]['status'], 'partial')
                self.assertFalse(validated['ready_for_draft'])

        for known_exception in ('The analyst cannot approve invoices.', 'The requester cannot contact the vendor.'):
            result = interview_result()
            result['memo_findings'][0].update(status='captured', answer=known_exception, evidence_turns=['u1'])
            self.assertEqual(server.validate_interview(result, interview_payload()['turns'])['memo_findings'][0]['status'], 'captured')

        payload = interview_payload()
        payload['turns'].extend([
            {'id':'u3','role':'user','text':"I am not sure who owns it."},
            {'id':'u4','role':'user','text':"I checked: the fund controller is accountable."},
        ])
        result = interview_result()
        result['memo_findings'][0].update(status='captured', answer='The fund controller is accountable.', evidence_turns=['u3'])
        # Syntactic validation does not decide what an entire source turn means.
        # The independent per-dimension audit checks whether this particular
        # assertion is supported; unrelated uncertainty must not demote it.
        self.assertEqual(server.validate_interview(result, payload['turns'])['memo_findings'][0]['status'], 'captured')
        result['memo_findings'][0].update(status='captured', evidence_turns=['u4'])
        self.assertEqual(server.validate_interview(result, payload['turns'])['memo_findings'][0]['status'], 'captured')

    def test_reported_memo_finding_cannot_claim_coverage_without_detail(self):
        for status in ("captured", "partial", "not_applicable"):
            for answer in ("", "  ", " UNKNOWN "):
                with self.subTest(status=status, answer=answer):
                    result = interview_result()
                    result["memo_findings"][0].update(status=status, answer=answer, evidence_turns=["u1"])
                    with self.assertRaisesRegex(ValueError, "reported detail or reason"):
                        server.validate_interview(result, interview_payload()["turns"])

    def test_unknown_or_partial_topics_override_a_premature_model_ready_flag(self):
        for key in server.COVERAGE:
            for status in ('unknown', 'partial'):
                result = interview_result()
                result['memo_findings'] = [
                    {'key': topic, 'status': 'captured', 'answer': 'Synthetic complete topic.', 'evidence_turns': ['u1']}
                    for topic in server.COVERAGE]
                finding = next(item for item in result['memo_findings'] if item['key'] == key)
                finding['status'] = status
                result['ready_for_draft'] = True
                with self.subTest(key=key, status=status):
                    validated = server.validate_interview(result, interview_payload()['turns'])
                    self.assertFalse(validated['ready_for_draft'])

    def test_all_topics_captured_or_explicitly_not_applicable_are_ready_without_implying_closure(self):
        result = interview_result()
        result['ready_for_draft'] = False
        result['memo_findings'] = [
            {'key': topic, 'status': 'not_applicable' if topic == 'variations' else 'captured',
             'answer': 'Synthetic participant basis.', 'evidence_turns': ['u1']}
            for topic in server.COVERAGE]
        validated = server.validate_interview(result, interview_payload()['turns'])
        self.assertTrue(validated['ready_for_draft'])
        self.assertFalse(validated['closure']['confirmed'])
        self.assertFalse(validated['closure']['asked'])

    def test_enough_detail_never_accepts_a_missing_or_duplicate_topic(self):
        findings = [{'key': key, 'status': 'captured'} for key in server.COVERAGE]
        self.assertFalse(server.memo_has_enough_detail(findings[:-1]))
        findings[-1] = findings[0]
        self.assertFalse(server.memo_has_enough_detail(findings))

    def test_accepts_a_draft_supported_by_interview_answers(self):
        payload = interview_payload()
        server.validate_payload(payload, require_answers=True)
        server.validate_draft(process_draft(), payload["turns"])

    def test_duplicate_turn_ids_cannot_make_evidence_ambiguous(self):
        payload = interview_payload()
        payload["turns"][-1]["id"] = "u1"
        with self.assertRaises(ValueError):
            server.validate_payload(payload)

    def test_a_system_message_cannot_be_smuggled_in_as_an_answer(self):
        payload = interview_payload()
        payload["turns"][-1]["role"] = "system"
        with self.assertRaises(ValueError):
            server.validate_payload(payload)

    def test_a_procedure_requires_some_user_evidence(self):
        payload = interview_payload()
        payload["turns"] = [payload["turns"][0]]
        with self.assertRaises(ValueError):
            server.validate_payload(payload, require_answers=True)

    def test_step_evidence_cannot_reference_invented_turns(self):
        draft = process_draft()
        draft["steps"][0]["evidence_turns"] = ["invented-user-answer"]
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_agent_question_is_not_user_evidence(self):
        draft = process_draft()
        draft["steps"][0]["evidence_turns"] = ["a1"]
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_graph_edges_cannot_reference_nonexistent_steps(self):
        draft = process_draft()
        draft["connections"][0]["to"] = "missing-step"
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_graph_nodes_need_unique_ids(self):
        draft = process_draft()
        draft["steps"][1]["id"] = draft["steps"][0]["id"]
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_map_connections_need_their_own_source_evidence(self):
        draft = process_draft()
        draft["connections"][0]["evidence_turns"] = []
        with self.assertRaises(ValueError):
            server.validate_draft(draft, interview_payload()["turns"])

    def test_map_connections_cannot_cite_questions_or_invented_turns(self):
        for evidence in (["a1"], ["fabricated-turn"]):
            with self.subTest(evidence=evidence):
                draft = process_draft()
                draft["connections"][0]["evidence_turns"] = evidence
                with self.assertRaises(ValueError):
                    server.validate_draft(draft, interview_payload()["turns"])

    def test_all_eleven_memo_topics_are_included_even_when_unknown(self):
        draft = server.validate_draft(process_draft(), interview_payload()["turns"])
        self.assertEqual(len(draft["memo_summary"]), 16)
        self.assertEqual({item["key"] for item in draft["memo_summary"]}, set(server.COVERAGE))
        self.assertTrue(any(item["status"] == "unknown" and not item["evidence_turns"] for item in draft["memo_summary"]))

    def test_reported_memo_findings_require_evidence(self):
        for status in ("captured", "partial", "not_applicable"):
            for kind in ("interview", "draft"):
                with self.subTest(status=status, kind=kind):
                    result = interview_result() if kind == "interview" else process_draft()
                    findings = result["memo_findings" if kind == "interview" else "memo_summary"]
                    findings[0].update(status=status, evidence_turns=[])
                    validate = server.validate_interview if kind == "interview" else server.validate_draft
                    with self.assertRaises(ValueError):
                        validate(result, interview_payload()["turns"])

    def test_missing_memo_topic_is_rejected_in_interview_and_draft(self):
        for kind in ("interview", "draft"):
            with self.subTest(kind=kind):
                result = interview_result() if kind == "interview" else process_draft()
                result["memo_findings" if kind == "interview" else "memo_summary"].pop()
                validate = server.validate_interview if kind == "interview" else server.validate_draft
                with self.assertRaises(ValueError):
                    validate(result, interview_payload()["turns"])

    def test_memo_coverage_and_finding_statuses_are_distinct_contracts(self):
        result = interview_result()
        result["coverage"][0]["status"] = "captured"
        with self.assertRaises(ValueError):
            server.validate_interview(result, interview_payload()["turns"])
        result = interview_result()
        result["memo_findings"][0]["status"] = "covered"
        with self.assertRaises(ValueError):
            server.validate_interview(result, interview_payload()["turns"])

    def test_variations_cannot_cite_questions_or_nonexistent_answers(self):
        for evidence in (["a1"], ["invented-turn"], []):
            with self.subTest(evidence=evidence):
                draft = process_draft()
                draft["variations"] = [process_variation(evidence)]
                with self.assertRaises(ValueError):
                    server.validate_draft(draft, interview_payload()["turns"])

    def test_supported_variation_and_lifecycle_metadata_are_retained(self):
        payload = interview_payload()
        payload["turns"].append({"id": "u3", "role": "user", "text": "For Fund B we use the ticketing tool to route unmatched invoices to the buyer. The trigger, accountable role, and finished result remain the same; I do not know the cost, charging, or reason."})
        draft = process_draft()
        draft["variations"] = [process_variation()]
        result = server.validate_draft(draft, payload["turns"])
        self.assertEqual(result["variations"][0]["cost"], "UNKNOWN")
        self.assertEqual(result["variations"][0]["evidence_turns"], ["u3"])
        self.assertEqual(result["lifecycle_items"][0]["item"], "Invoice")
        self.assertEqual(result["steps"][0]["output"], "Logged invoice")
        self.assertIn("UNKNOWN", result["steps"][1]["handoff"])

    def test_closure_cannot_be_confirmed_without_a_completeness_check(self):
        result = interview_result()
        result["closure"] = {"asked": False, "confirmed": True}
        with self.assertRaises(ValueError):
            server.validate_interview(result, interview_payload()["turns"])


class GraphRoutingContractTests(unittest.TestCase):
    def test_isolated_workflow_steps_raise_questions_without_inventing_edges(self):
        draft = process_draft()
        isolated = copy.deepcopy(draft['steps'][0])
        isolated.update(id='s3', title='Reconcile the ledger')
        workflow = {'title':'Invoice work', 'steps':draft['steps'] + [isolated],
                    'connections':copy.deepcopy(draft['connections']), 'open_questions':['Who owns the handoff?']}
        original_edges = copy.deepcopy(workflow['connections'])
        result = server.validate_workflow(workflow, interview_payload()['turns'])
        self.assertEqual(result['connections'], original_edges)
        # The reviewer's own question stays first; the generated routing question follows it.
        self.assertEqual(result['open_questions'][0], 'Who owns the handoff?')
        self.assertIn('s3 (Reconcile the ledger)', result['open_questions'][1])
        self.assertEqual(len(server.validate_workflow(result, interview_payload()['turns'])['open_questions']), 2)
        result['connections'].append({'from':'s3', 'to':'s3', 'label':'Retry', 'evidence_turns':['u1']})
        result['open_questions'] = []
        self.assertIn('s3', server.validate_workflow(result, interview_payload()['turns'])['open_questions'][0])

    def test_connected_or_single_step_does_not_create_isolation_question(self):
        draft = process_draft()
        workflow = {'title':'Invoice work', 'steps':draft['steps'], 'connections':draft['connections'], 'open_questions':[]}
        self.assertEqual(server.validate_workflow(workflow, interview_payload()['turns'])['open_questions'], [])
        workflow['steps'] = workflow['steps'][:1]; workflow['connections'] = []
        self.assertEqual(server.validate_workflow(workflow, interview_payload()['turns'])['open_questions'], [])

    def test_generation_and_audit_keep_known_exception_entry_and_distinct_client_routes(self):
        payload = interview_payload()
        payload['turns'] = [
            {'id': 'u1', 'role': 'user', 'text': 'The analyst performs the service, checks the result, then records it ready for coordinator closure.'},
            {'id': 'u2', 'role': 'user', 'text': 'If the job platform is unavailable during the work, the analyst marks it blocked and notifies the lead. Restart and rejoin are unknown.'},
            {'id': 'u3', 'role': 'user', 'text': 'After ready and before closure, Orion requires compliance approval. Other clients skip approval. The approval is recorded before Orion closure.'},
        ]
        candidate = process_draft()
        template = candidate['steps'][0]
        candidate['steps'] = []
        for step_id, title, source in (('work', 'Perform service', 'u1'), ('blocked', 'Mark blocked and notify lead', 'u2'),
                                       ('ready', 'Record ready', 'u1'), ('approval', 'Record compliance approval', 'u3'),
                                       ('close', 'Coordinator closure', 'u1')):
            step = copy.deepcopy(template)
            step.update(id=step_id, title=title, evidence_turns=[source])
            candidate['steps'].append(step)
        candidate['connections'] = [
            {'from': 'work', 'to': 'ready', 'label': 'Result matches', 'evidence_turns': ['u1']},
            {'from': 'work', 'to': 'blocked', 'label': 'Job platform unavailable', 'evidence_turns': ['u1', 'u2']},
            {'from': 'ready', 'to': 'approval', 'label': 'Client Orion', 'evidence_turns': ['u3']},
            {'from': 'ready', 'to': 'close', 'label': 'Other clients', 'evidence_turns': ['u3']},
            {'from': 'approval', 'to': 'close', 'label': 'Approval recorded', 'evidence_turns': ['u3']},
        ]
        candidate['open_questions'] = ['Who authorizes restarting blocked work, and where does it rejoin?']
        client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-not-a-credential'})
        client.structured = Mock(side_effect=[copy.deepcopy(candidate), fixture_draft_audit(candidate, payload["turns"])])
        result = client.draft(payload)['draft']
        self.assertEqual(result['connections'], candidate['connections'])
        self.assertFalse(any(edge['from'] == 'blocked' for edge in result['connections']))
        self.assertEqual(client.structured.call_count, 2)
        for call in client.structured.call_args_list:
            self.assertIn(server.GRAPH_ROUTING_POLICY, call.args[0])
            self.assertIn(server.FULL_CIRCLE_POLICY, call.args[0])
        self.assertEqual(client.structured.call_args_list[0].args[2], server.DRAFT_SCHEMA)
        self.assertEqual(client.structured.call_args_list[1].args[2],
                         server.route_audit_schema(server.DRAFT_AUDIT_SCHEMA, candidate['connections']))
        self.assertIn(server.GRAPH_ROUTING_POLICY, server.WORKFLOW_INSTRUCTIONS)


class NextQuestionAuditTests(unittest.TestCase):
    def test_claimed_completion_receives_independent_assessment_before_question_audit(self):
        from test_interview_coverage import fixture
        findings, assessment, turns = fixture()
        payload = interview_payload()
        payload["turns"] = turns
        candidate = interview_result()
        candidate["memo_findings"] = findings
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-independent-coverage"})
        client.request = Mock(side_effect=[self.response(candidate), self.response(assessment),
                                          self.response({"question": "Is there a correction to this account?"})])
        result = client.interview(payload)
        calls = [call.args[1] for call in client.request.call_args_list]
        self.assertEqual([body["text"]["format"]["name"] for body in calls],
                         ["process_interview", "process_coverage_assessment", "process_next_question_audit"])
        assessment_input = json.loads(calls[1]["input"][0]["content"])
        audit_input = json.loads(calls[2]["input"][0]["content"])
        self.assertEqual(assessment_input["turns"], turns)
        self.assertEqual(assessment_input["candidate_findings"], findings)
        self.assertEqual(audit_input["coverage_assessment"], result["coverage_assessment"])
        self.assertTrue(result["ready_for_draft"])
        self.assertTrue(result["coverage_assessment"]["all_topics_covered"])
        self.assertFalse(result["closure"]["confirmed"])

    @staticmethod
    def response(value):
        return {"status": "completed", "output": [{"content": [
            {"type": "output_text", "text": json.dumps(value)}]}]}

    def client(self, candidate, audit):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-synthetic-question-audit"})
        client.request = Mock(side_effect=[self.response(candidate), self.response(audit)])
        return client

    def test_audited_question_replaces_candidate_without_changing_validated_capture(self):
        payload = interview_payload()
        candidate = interview_result()
        expected = server.validate_interview(copy.deepcopy(candidate), payload["turns"])
        replacement = "What happens when the buyer cannot resolve the mismatch?"
        client = self.client(candidate, {"question": replacement})

        result = client.interview(payload)

        self.assertEqual(result, {**expected, "question": replacement})
        self.assertEqual(result["memo_findings"], expected["memo_findings"])
        self.assertEqual(result["coverage"], expected["coverage"])
        self.assertEqual(result["closure"], expected["closure"])
        self.assertFalse(result["ready_for_draft"])
        self.assertEqual(client.request.call_count, 2)
        first, second = [call.args[1] for call in client.request.call_args_list]
        self.assertEqual(first["text"]["format"]["name"], "process_interview")
        self.assertEqual(second["text"]["format"]["name"], "process_next_question_audit")
        self.assertEqual(set(second["text"]["format"]["schema"]["properties"]), {"question"})
        self.assertLessEqual(second["max_output_tokens"], 1600)
        sent = json.loads(second["input"][0]["content"])
        self.assertEqual(sent["turns"], payload["turns"])
        self.assertEqual(sent["candidate_question"], candidate["question"])
        self.assertEqual(sent["memo_findings"], expected["memo_findings"])
        self.assertEqual(sent["closure"], expected["closure"])
        self.assertNotIn("ready_for_draft", sent)
        self.assertNotIn("coverage", sent)

    def test_answer_and_skip_with_user_history_both_use_question_audit(self):
        for action in ("answer", "skip"):
            with self.subTest(action=action):
                payload = interview_payload()
                payload["action"] = action
                client = self.client(interview_result(), {"question": "What manual work takes the most effort?"})
                self.assertEqual(client.interview(payload)["question"], "What manual work takes the most effort?")
                self.assertEqual(client.request.call_count, 2)

    def test_start_and_close_do_not_add_a_question_audit(self):
        for action in ("start", "close"):
            with self.subTest(action=action):
                payload = interview_payload()
                payload["action"] = action
                client = self.client(interview_result(), {"question": "Must not be used"})
                result = client.interview(payload)
                self.assertEqual(client.request.call_count, 1)
                if action == "close":
                    self.assertTrue(result["question"].startswith(server.PARTIAL_CHECK_PREFIX))
                    self.assertEqual(result["closure"], {"asked": False, "confirmed": False})
                else:
                    self.assertEqual(result["question"], interview_result()["question"])

    def test_no_user_history_does_not_add_a_question_audit(self):
        for action in ("answer", "skip"):
            with self.subTest(action=action):
                payload = interview_payload()
                payload.update(action=action, turns=[payload["turns"][0]])
                candidate = interview_result()
                for finding in candidate["memo_findings"]:
                    if finding["key"] != "name":
                        finding.update(status="unknown", answer="UNKNOWN", evidence_turns=[])
                client = self.client(candidate, {"question": "Must not be used"})
                self.assertEqual(client.interview(payload)["question"], candidate["question"])
                self.assertEqual(client.request.call_count, 1)

    def test_invalid_initial_capture_is_rejected_before_audit(self):
        candidate = interview_result()
        candidate["memo_findings"][1].update(status="partial", answer="Invented evidence", evidence_turns=["missing-turn"])
        client = self.client(candidate, {"question": "Would hide the invalid finding"})
        with self.assertRaises(server.APIError):
            client.interview(interview_payload())
        self.assertEqual(client.request.call_count, 1)

    def test_invalid_audit_rejects_without_returning_or_overwriting_the_capture(self):
        for audit in ({"question": " "}, {"question": "x" * 1201}, {"question": 12},
                      {"question": "Who approves?", "ready_for_draft": True}, {}, None):
            with self.subTest(audit=audit):
                candidate = interview_result()
                original = copy.deepcopy(candidate)
                client = self.client(candidate, audit)
                with self.assertRaises(server.APIError):
                    client.interview(interview_payload())
                self.assertEqual(client.request.call_count, 2)
                self.assertEqual(candidate, original)


class ClosureEnforcementTests(unittest.TestCase):
    def test_file_notifications_cannot_ask_or_answer_the_final_check(self):
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        turns = interview_payload()["turns"] + [
            {"id": "notice", "role": "assistant", "document_event": True, "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "reply", "role": "user", "text": "No."}]
        self.assertFalse(server.enforce_closure(result, turns, "answer")["closure"]["confirmed"])
        turns[-2].pop("document_event")
        turns[-1]["document_event"] = True
        result["closure"] = {"asked": True, "confirmed": True}
        self.assertFalse(server.enforce_closure(result, turns, "answer")["closure"]["confirmed"])

    def test_confirmation_cannot_precede_any_actual_final_check(self):
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, interview_payload()["turns"], "answer")
        self.assertFalse(checked["closure"]["confirmed"])

    def test_an_unanswered_final_check_cannot_be_confirmed(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": False})

    def test_participant_text_cannot_masquerade_as_the_final_check(self):
        turns = interview_payload()["turns"] + [
            {"id": "u3", "role": "user", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u4", "role": "user", "text": "No, that is all."},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        self.assertFalse(server.enforce_closure(result, turns, "answer")["closure"]["confirmed"])

    def test_actual_reply_after_final_check_can_remain_confirmed(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "No, nothing else. This captures my account."},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": True})

    def test_asked_state_is_preserved_when_model_forgets_it(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "There is one more exception to explain."},
        ]
        result = interview_result()
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": False})

    def test_new_final_check_needs_a_new_participant_reply(self):
        turns = interview_payload()["turns"] + [
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "No, that is all."},
            {"id": "a4", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " after that correction?"},
        ]
        result = interview_result()
        result["closure"] = {"asked": True, "confirmed": True}
        checked = server.enforce_closure(result, turns, "answer")
        self.assertEqual(checked["closure"], {"asked": True, "confirmed": False})


class UpstreamErrorTests(unittest.TestCase):
    def test_transport_failures_are_classified_without_private_details_or_retries(self):
        failures = [
            (TimeoutError("PRIVATE_TRANSPORT_SENTINEL"), 504, "timeout", "timed out"),
            (urllib.error.URLError(TimeoutError("PRIVATE_TRANSPORT_SENTINEL")), 504, "timeout", "timed out"),
            (urllib.error.URLError(OSError(errno.ETIMEDOUT, "PRIVATE_TRANSPORT_SENTINEL")), 504, "timeout", "timed out"),
            (urllib.error.URLError(OSError(10060, "PRIVATE_TRANSPORT_SENTINEL")), 504, "timeout", "timed out"),
            (urllib.error.URLError(socket.gaierror(-2, "PRIVATE_TRANSPORT_SENTINEL")), 502, "dns", "network address"),
            (urllib.error.URLError(ssl.SSLCertVerificationError(1, "PRIVATE_TRANSPORT_SENTINEL")), 502, "tls", "secure connection"),
            (ConnectionResetError("PRIVATE_TRANSPORT_SENTINEL"), 502, "connection", "interrupted"),
            (urllib.error.URLError(ConnectionRefusedError("PRIVATE_TRANSPORT_SENTINEL")), 502, "connection", "interrupted"),
            (OSError("PRIVATE_TRANSPORT_SENTINEL"), 502, "network", "Could not reach"),
        ]
        for failure, status, category, expected in failures:
            with self.subTest(category=category, failure=type(failure).__name__):
                diagnostics = Mock()
                client = server.OpenAIClient({"OPENAI_API_KEY": "PRIVATE_KEY_SENTINEL"}, diagnostics)
                with patch.object(server.openai_transport, "urlopen", side_effect=failure) as network:
                    with self.assertRaises(server.APIError) as caught:
                        client.request("responses", {"text": {"format": {"name": "working_process_map_audit"}},
                                                     "input": "PRIVATE_DOCUMENT_SENTINEL"}, timeout=240)
                self.assertEqual(caught.exception.status, status)
                self.assertIn(expected, str(caught.exception))
                if category == "timeout":
                    self.assertIn("saved files do not need to be uploaded again", str(caught.exception))
                    self.assertNotIn("Check the network", str(caught.exception))
                network.assert_called_once()
                self.assertEqual(diagnostics.call_args.args, ("provider_request_finished",))
                fields = diagnostics.call_args.kwargs
                self.assertEqual(fields["error_category"], category)
                self.assertEqual(fields["stage"], "working_process_map_audit")
                self.assertEqual(fields["status"], status)
                self.assertEqual(fields["timeout_seconds"], 240)
                self.assertGreaterEqual(fields["duration_ms"], 0)
                self.assertNotIn("PRIVATE_", str(caught.exception))
                self.assertNotIn("PRIVATE_", repr(diagnostics.call_args))

    def test_timeout_while_reading_a_connected_response_is_not_reported_as_no_connection(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.side_effect = TimeoutError("PRIVATE_RESPONSE_SENTINEL")
        client = server.OpenAIClient({"OPENAI_API_KEY": "synthetic-key"})
        with patch.object(server.openai_transport, "urlopen", return_value=response) as network:
            with self.assertRaises(server.APIError) as caught:
                client.request("responses", {}, timeout=240)
        self.assertEqual(caught.exception.status, 504)
        self.assertIn("timed out", str(caught.exception))
        self.assertNotIn("Could not reach", str(caught.exception))
        network.assert_called_once()
        response.__exit__.assert_called_once()

    def test_successful_provider_call_remains_successful_when_diagnostics_fail(self):
        diagnostics = Mock(side_effect=OSError("PRIVATE_DIAGNOSTIC_SENTINEL"))
        client = server.OpenAIClient({"OPENAI_API_KEY": "synthetic-key"}, diagnostics)
        with patch.object(server.openai_transport, "urlopen", return_value=io.BytesIO(b'{"ok": true}')):
            self.assertEqual(client.request("responses", {}), {"ok": True})
        self.assertEqual(diagnostics.call_args.kwargs["outcome"], "success")
        self.assertEqual(diagnostics.call_args.kwargs["status"], 200)

    def test_exhausted_credit_balance_is_quota_error_not_temporary_rate_limit(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-test-sentinel-not-a-real-credential"})
        details = {"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota",
                             "message": "Synthetic exhausted-credit response"}}
        error = urllib.error.HTTPError("https://api.openai.com/v1/responses", 429, "Too Many Requests", {},
                                       io.BytesIO(json.dumps(details).encode()))
        with patch.object(server.openai_transport, "urlopen", side_effect=error) as network:
            with self.assertRaises(server.APIError) as caught:
                client.request("responses", {"model": "synthetic-test"})
        network.assert_called_once()
        message = str(caught.exception).lower()
        self.assertIn("no available api quota", message)
        self.assertIn("billing", message)
        self.assertNotIn("wait", message)
        self.assertNotIn("rate limit", message)


class HTTPResourceLifecycleTests(unittest.TestCase):
    def start_server(self, handler=None, max_connections=16, header_timeout=15):
        temporary = tempfile.TemporaryDirectory(prefix="collector-http-lifecycle-")
        self.addCleanup(temporary.cleanup)
        client = server.OpenAIClient({})
        client.request = Mock(side_effect=AssertionError("Unexpected provider call"))
        started = threading.Event()

        class BoundedServer(server.InterviewServer):
            def process_request_thread(self, request, address):
                started.set()
                super().process_request_thread(request, address)

        BoundedServer.max_connections = max_connections
        BoundedServer.header_timeout = header_timeout
        httpd = BoundedServer(("127.0.0.1", 0), handler or server.Handler, client=client,
                              documents_root=Path(temporary.name) / "documents", knowledge_settings={})
        worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()

        def cleanup():
            if worker.is_alive():
                httpd.shutdown()
                worker.join(timeout=2)
            if not getattr(httpd, "_test_closed", False):
                httpd.server_close()
        self.addCleanup(cleanup)
        return httpd, worker, client, started

    def test_idle_connections_are_bounded_and_timeout_releases_capacity(self):
        httpd, _, client, started = self.start_server(max_connections=1, header_timeout=.15)
        idle = socket.create_connection(httpd.server_address, timeout=2)
        self.addCleanup(idle.close)
        self.assertTrue(started.wait(timeout=2))
        with socket.create_connection(httpd.server_address, timeout=2) as excess:
            response = excess.recv(4096)
        self.assertIn(b"503 Service Unavailable", response)
        self.assertIn(b"Retry-After: 1", response)
        self.assertEqual(idle.recv(1024), b"", "An idle header cannot retain a worker indefinitely")
        self.assertTrue(httpd.connection_slots.acquire(timeout=1))
        httpd.connection_slots.release()
        with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/api/config", timeout=2) as response:
            self.assertEqual(response.status, 200)
        client.request.assert_not_called()

    def test_incomplete_body_times_out_with_no_provider_request(self):
        httpd, _, client, _ = self.start_server()
        httpd.body_timeout = .08
        with socket.create_connection(httpd.server_address, timeout=2) as incomplete:
            incomplete.sendall((f"POST /api/interview HTTP/1.1\r\nHost: 127.0.0.1:{httpd.server_port}\r\n"
                                f"X-CSRF-Token: {httpd.csrf_token}\r\nContent-Type: application/json\r\n"
                                "Content-Length: 100\r\n\r\n{").encode())
            response = incomplete.recv(4096)
        self.assertIn(b"408 Request Timeout", response)
        client.request.assert_not_called()

    def test_trickled_bytes_do_not_reset_the_total_body_deadline(self):
        handler = object.__new__(server.Handler)
        handler.connection = Mock()
        handler.rfile = Mock()
        handler.rfile.read1.return_value = b"a"
        with patch.object(server.time, "monotonic", side_effect=[0, 0, 2, 4]):
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                handler._read_body(10, 3)
        self.assertEqual(handler.rfile.read1.call_count, 2)

    def test_rejected_incomplete_body_still_returns_403_and_releases_capacity(self):
        httpd, _, client, _ = self.start_server(max_connections=1)
        httpd.body_timeout = .08
        with socket.create_connection(httpd.server_address, timeout=2) as rejected:
            rejected.sendall((f"POST /api/interview HTTP/1.1\r\nHost: 127.0.0.1:{httpd.server_port}\r\n"
                              "X-CSRF-Token: wrong-token\r\nContent-Type: application/json\r\n"
                              "Content-Length: 100\r\n\r\n{").encode())
            response = rejected.recv(4096)
        self.assertIn(b"403 Forbidden", response)
        self.assertTrue(httpd.connection_slots.acquire(timeout=1))
        httpd.connection_slots.release()
        client.request.assert_not_called()

    def test_upload_capacity_is_bounded_before_the_large_body_is_read(self):
        httpd, _, client, _ = self.start_server()
        self.assertTrue(httpd.upload_slots.acquire(blocking=False))
        self.assertTrue(httpd.upload_slots.acquire(blocking=False))
        self.addCleanup(httpd.upload_slots.release)
        self.addCleanup(httpd.upload_slots.release)
        with socket.create_connection(httpd.server_address, timeout=2) as upload:
            upload.sendall((f"POST /api/documents/upload HTTP/1.1\r\nHost: 127.0.0.1:{httpd.server_port}\r\n"
                            f"X-CSRF-Token: {httpd.csrf_token}\r\nContent-Length: 100\r\n\r\n").encode())
            response = upload.recv(4096)
        self.assertIn(b"429 Too Many Requests", response)
        client.request.assert_not_called()

    def test_storage_stays_open_until_an_admitted_request_finishes(self):
        entered, release = threading.Event(), threading.Event()
        result = {}

        class HeldHandler(server.Handler):
            def do_GET(self):
                entered.set()
                release.wait(timeout=2)
                result["storage_open"] = not self.server.knowledge.closed
                self.server.knowledge.db.execute("SELECT 1")
                self._json({"finished": True})

        httpd, worker, client, _ = self.start_server(handler=HeldHandler)
        received = []
        def fetch():
            with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/held", timeout=3) as response:
                received.append(response.status)
        request = threading.Thread(target=fetch)
        request.start()
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(timeout=2))
        httpd.shutdown(); worker.join(timeout=2)
        finished = threading.Event()
        def close():
            httpd.server_close()
            httpd._test_closed = True
            finished.set()
        closing = threading.Thread(target=close)
        closing.start()
        self.assertFalse(finished.wait(timeout=.05))
        self.assertFalse(httpd.knowledge.closed)
        release.set()
        request.join(timeout=2); closing.join(timeout=2)
        self.assertFalse(request.is_alive())
        self.assertTrue(finished.is_set())
        self.assertEqual(received, [200])
        self.assertTrue(result["storage_open"])
        self.assertTrue(httpd.knowledge.closed)
        client.request.assert_not_called()

    def test_failed_store_initialization_releases_the_bound_port(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        client = server.OpenAIClient({})
        with patch.object(server.documents, "DocumentStore", side_effect=ValueError("Synthetic store failure")):
            with self.assertRaisesRegex(ValueError, "Synthetic store failure"):
                server.InterviewServer(("127.0.0.1", port), server.Handler, client=client)
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))


class HTTPBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_key = "sk-test-sentinel-not-a-real-credential"
        cls.client = server.OpenAIClient({"OPENAI_API_KEY": cls.test_key})
        cls.client.request = Mock()
        root = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=cls.client,
                                           documents_root=root / "documents", knowledge_settings={})
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=3)

    def setUp(self):
        self.client.request.reset_mock(side_effect=True, return_value=True)
        self.client.request.side_effect = self.upstream_response
        self.mock_draft = process_draft()
        self.mock_interview = interview_result()

    def upstream_response(self, path, body, *args, **kwargs):
        if path == "audio/transcriptions":
            return {"text": "A synthetic recorded answer."}
        name = body["text"]["format"]["name"]
        if name == "process_next_question_audit":
            result = {"question": json.loads(body["input"][0]["content"])["candidate_question"]}
        elif name == "team_interviewer_response":
            result = {"question": json.loads(body["input"][0]["content"])["candidate_question"], "intent": "ask"}
        elif name == "team_interview_capture":
            supplied = json.loads(body["input"][0]["content"])
            # This HTTP fixture describes a new partial interview. Return the
            # actual private fact protocol; production has no legacy fallback.
            result = {key: copy.deepcopy(self.mock_interview[key])
                      for key in ("question", "summary", "focus", "parking_lot")}
            result.update(base_revision=supplied["fact_state"]["base_revision"],
                fact_reconciliations=[{"target_id": item["id"], "disposition": "unchanged",
                    "basis": "This controlled HTTP fixture supplies no revision to the prior assertion.",
                    "evidence_turns": list(item["evidence_turns"])}
                    for item in server.capture_facts.reconciliation_targets(supplied["fact_state"])],
                topic_states=[{"key": f["key"], "status": f["status"], "participant_unavailable": False}
                              for f in self.mock_interview["memo_findings"]],
                fact_operations=[{"op": "add", "topic": f["key"], "target_id": "",
                    "kind": "not_applicable" if f["status"] == "not_applicable" else "detail",
                    "text": f["answer"], "evidence_turns": list(f["evidence_turns"]), "reason": "new_evidence"}
                    for f in self.mock_interview["memo_findings"] if f["status"] != "unknown"])
        elif name == "process_coverage_assessment":
            result = incomplete_assessment(json.loads(body["input"][0]["content"])["candidate_findings"])
            if 'capture_repair' in coverage_topic_properties(body['text']['format']['schema'])[0]:
                for topic in result['topics']:
                    topic['capture_repair'] = {'needed': False}
        elif name == "process_specialist_review":
            result = {"summary": "The partial test account still needs review.", "evidence_turns": [],
                      "findings": [], "next_question": "", "no_material_blockers": False}
        elif name == "process_draft_audit":
            result = fixture_draft_audit(self.mock_draft, json.loads(body["input"][0]["content"])["turns"])
        else:
            result = self.mock_draft if name == "process_draft" else self.mock_interview
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}]}

    def request(self, path, payload=None, headers=None, method=None, csrf=True):
        request_headers = {}
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            if csrf:
                request_headers["X-CSRF-Token"] = self.httpd.csrf_token
            payload = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        request_headers.update(headers or {})
        req = urllib.request.Request(self.url + path, data=payload, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_public_config_exposes_no_credential(self):
        status, headers, raw = self.request("/api/config")
        self.assertEqual(status, 200)
        config = json.loads(raw)
        self.assertTrue(config["api_configured"])
        self.assertEqual(config["app_id"], "voice-interviewer")
        self.assertEqual(config["build_id"],self.httpd.build_id)
        self.assertRegex(config["build_id"],r'^[0-9a-f]{64}$')
        self.assertEqual(config["csrf_token"], self.httpd.csrf_token)
        self.assertNotIn(self.test_key.encode(), raw)
        self.assertNotIn("OPENAI_API_KEY", raw.decode())
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_nonlocal_bind_is_rejected(self):
        with self.assertRaises(ValueError):
            server.InterviewServer(("0.0.0.0", 0), server.Handler, client=self.client)

    def test_host_header_rebinding_is_rejected(self):
        status, _, _ = self.request("/api/config", headers={"Host": "attacker.example"})
        self.assertEqual(status, 403)

    def test_cross_site_reads_and_writes_are_rejected(self):
        for path, payload in (("/api/config", None), ("/api/interview", interview_payload())):
            with self.subTest(path=path):
                status, _, _ = self.request(path, payload, headers={"Origin": "https://attacker.example"})
                self.assertEqual(status, 403)
        status, _, _ = self.request("/api/config", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.client.request.assert_not_called()

    def test_mutating_requests_need_the_current_csrf_token(self):
        for headers in ({}, {"X-CSRF-Token": "incorrect-token"}):
            with self.subTest(headers=headers):
                status, _, _ = self.request("/api/interview", interview_payload(), headers=headers, csrf=False)
                self.assertEqual(status, 403)
        self.client.request.assert_not_called()

    def test_secret_and_source_files_are_not_served(self):
        for path in ("/.env.local", "/../.env.local", "/%2e%2e/.env.local", "/server.py", "/tests/test_server.py"):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404)

    def test_every_deferred_entrypoint_script_is_served(self):
        class Scripts(HTMLParser):
            def __init__(self):
                super().__init__()
                self.paths = []

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == "script" and "defer" in attributes and attributes.get("src"):
                    self.paths.append(attributes["src"])

        status, _, html = self.request("/")
        self.assertEqual(status, 200)
        scripts = Scripts()
        scripts.feed(html.decode("utf-8"))
        self.assertIn("/document-intake.js", [path.partition("?")[0] for path in scripts.paths])
        for path in scripts.paths:
            with self.subTest(script=path):
                status, headers, content = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn("javascript", headers["Content-Type"])
                self.assertIn("immutable", headers["Cache-Control"])
                self.assertEqual(content, (APP / "web" / path.partition("?")[0].lstrip("/")).read_bytes())
        self.client.request.assert_not_called()

    def test_json_media_type_and_valid_json_are_required(self):
        status, _, _ = self.request("/api/interview", interview_payload(), headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _, raw = self.request("/api/interview", b"{broken-json")
        self.assertEqual(status, 400)
        self.assertIn("Invalid JSON", json.loads(raw)["error"])
        self.client.request.assert_not_called()

    def test_oversized_request_is_rejected_before_read_or_model_call(self):
        # An interview route admits a full transcript in any script (see
        # test_request_size_parity.py); a small-body route keeps MAX_JSON.
        status, _, _ = self.request("/api/interview", b"{}", headers={"Content-Length": str(server.MAX_SNAPSHOT_JSON + 1)})
        self.assertEqual(status, 413)
        status, _, _ = self.request("/api/agent-team/status", b"{}", headers={"Content-Length": str(server.MAX_JSON + 1)})
        self.assertEqual(status, 413)
        self.client.request.assert_not_called()

    def test_invalid_interview_role_is_rejected_before_model_call(self):
        payload = interview_payload()
        payload["turns"][-1]["role"] = "system"
        status, _, _ = self.request("/api/interview", payload)
        self.assertEqual(status, 400)
        self.client.request.assert_not_called()

    def test_valid_interview_uses_stateless_strict_structured_output(self):
        status, _, raw = self.request("/api/interview", interview_payload())
        self.assertEqual(status, 200)
        self.assertIn("releases payment", json.loads(raw)["question"])
        self.assertEqual(self.client.request.call_count, 1)
        self.assertEqual({call.args[1]["text"]["format"]["name"] for call in self.client.request.call_args_list},
                         {"team_interview_capture"})
        self.assertFalse(json.loads(raw)["completion"]["complete"])
        for call in self.client.request.call_args_list:
            path, body = call.args
            self.assertEqual(path, "responses")
            self.assertIs(body["store"], False)
            self.assertIs(body["text"]["format"]["strict"], True)
            self.assertNotIn(self.test_key, json.dumps(body))

    def test_draft_without_answers_is_rejected_before_model_call(self):
        payload = interview_payload()
        payload["turns"] = []
        status, _, _ = self.request("/api/draft", payload)
        self.assertEqual(status, 400)
        self.client.request.assert_not_called()

    def test_draft_is_labelled_for_human_review(self):
        status, _, raw = self.request("/api/draft", interview_payload())
        self.assertEqual(status, 200)
        draft = json.loads(raw)["draft"]
        self.assertTrue(any("Process-owner review is required" in note for note in draft["validation_notes"]))
        self.assertEqual(draft["steps"][0]["evidence_turns"], ["u1"])
        self.assertIn("Who releases payment", draft["open_questions"][0])

    def test_invented_model_evidence_is_not_returned_as_a_valid_draft(self):
        self.mock_draft["steps"][0]["evidence_turns"] = ["fabricated-turn"]
        status, _, raw = self.request("/api/draft", interview_payload())
        self.assertEqual(status, 502)
        self.assertIn("error", json.loads(raw))
        self.assertNotIn("draft", json.loads(raw))

    def test_transcription_rejects_non_audio_without_model_call(self):
        status, _, _ = self.request("/api/transcribe", b"x" * 200, headers={"Content-Type": "text/html"})
        self.assertEqual(status, 400)
        self.client.request.assert_not_called()

    def test_api_failure_does_not_leak_key(self):
        self.client.request.side_effect = server.APIError("A controlled upstream test failure.")
        status, _, raw = self.request("/api/interview", interview_payload())
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(raw)["error"], "A controlled upstream test failure.")
        self.assertNotIn(self.test_key.encode(), raw)

    def test_key_supplied_with_a_trailing_line_break_is_not_echoed(self):
        # A real client. The stand-in applies the HTTP library's own header check
        # (the one that prints a refused header in full), then refuses the connection.
        def refuse(request, timeout=None):
            connection = http.client.HTTPConnection("api.openai.com")
            connection.putrequest(request.get_method(), request.selector)
            for name, value in request.header_items():
                connection.putheader(name, value)
            raise urllib.error.URLError(ConnectionRefusedError("synthetic refusal"))

        client = server.OpenAIClient({"OPENAI_API_KEY": self.test_key + "\r\n"})
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                                       documents_root=root / "documents", knowledge_settings={})
        worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{httpd.server_port}/api/voice-session", data=b'{"voice": "marin"}',
                headers={"Content-Type": "application/json", "X-CSRF-Token": httpd.csrf_token})
            with patch.object(server.openai_transport, "urlopen", side_effect=refuse) as network:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=3)
            raw = caught.exception.read()
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=3)
        network.assert_called_once()
        self.assertNotIn(self.test_key.encode(), raw)
        self.assertNotIn(b"header", raw.lower())
        self.assertEqual(caught.exception.code, 502)
        self.assertIn("connection to the AI service was interrupted", json.loads(raw)["error"])

    def test_close_action_reviews_open_sections_without_claiming_final_completeness(self):
        payload = interview_payload()
        payload["action"] = "close"
        repetitive_gap = "Who releases payment after the manager approves?"
        self.mock_interview["question"] = repetitive_gap
        self.mock_interview["closure"] = {"asked": False, "confirmed": False}
        status, _, raw = self.request("/api/interview", payload)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertEqual(result["closure"], {"asked": False, "confirmed": False})
        self.assertFalse(result["question"].startswith(server.FINAL_CHECK_PREFIX))
        self.assertTrue(result["question"].startswith(server.PARTIAL_CHECK_PREFIX))
        self.assertIn("create a draft from what is here", result["question"].lower())
        self.assertNotEqual(result["question"], repetitive_gap)
        self.assertFalse(result["completion"]["complete"])
        sent = json.loads(self.client.request.call_args.args[1]["input"][0]["content"])
        self.assertEqual(sent["action"], "close")

    def test_close_action_replaces_a_blank_model_question_before_validation(self):
        payload = interview_payload()
        payload["action"] = "close"
        self.mock_interview["question"] = ""
        self.mock_interview["closure"] = {"asked": False, "confirmed": False}
        status, _, raw = self.request("/api/interview", payload)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertFalse(result["question"].startswith(server.FINAL_CHECK_PREFIX))
        self.assertTrue(result["question"].startswith(server.PARTIAL_CHECK_PREFIX))
        self.assertIn("create a draft from what is here", result["question"].lower())
        self.assertEqual(result["closure"], {"asked": False, "confirmed": False})

    def test_prior_final_check_reply_cannot_close_an_incomplete_account(self):
        payload = interview_payload()
        payload["turns"].extend([
            {"id": "a3", "role": "assistant", "text": server.FINAL_CHECK_PREFIX + " that we missed?"},
            {"id": "u3", "role": "user", "text": "No, nothing else. This captures my account."},
        ])
        self.mock_interview["question"] = "   "
        self.mock_interview["closure"] = {"asked": False, "confirmed": True}
        status, _, raw = self.request("/api/interview", payload)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertFalse(result["closure"]["confirmed"])
        self.assertFalse(result["ready_for_draft"])
        self.assertIn("?", result["question"])
        self.assertNotIn("create or update the draft now", result["question"])

    def test_legacy_meeting_time_is_ignored_and_never_sent_to_the_provider(self):
        for planned, elapsed in ((60, 90), (0, -1), ('unlimited', 'ignored'), (None, None), (10**20, 10**30)):
            with self.subTest(planned=planned, elapsed=elapsed):
                self.client.request.reset_mock()
                payload = interview_payload()
                payload["context"]["meeting_minutes"] = planned
                payload["session"]["elapsed_minutes"] = elapsed
                status, _, raw = self.request("/api/interview", payload)
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(raw)["question"])
                sent = json.loads(self.client.request.call_args.args[1]["input"][0]["content"])
                self.assertNotIn('timing', sent)
                self.assertNotIn('session', sent)
                self.assertNotIn('meeting_minutes', sent['context'])
                instructions = self.client.request.call_args_list[0].args[1]['instructions']
                self.assertNotIn('60-minute meeting', instructions)
                self.assertNotIn('Use elapsed time', instructions)
                self.assertIn('no duration target', instructions)

    def test_shutdown_requires_same_origin_and_current_token(self):
        with patch.object(self.httpd, "shutdown") as shutdown:
            for kwargs in ({"csrf": False}, {"headers": {"Origin": "https://attacker.example"}}):
                with self.subTest(kwargs=kwargs):
                    status, _, _ = self.request("/api/shutdown", {}, **kwargs)
                    self.assertEqual(status, 403)
            shutdown.assert_not_called()

    def test_authorized_shutdown_calls_only_the_test_server(self):
        stopped = threading.Event()
        with patch.object(self.httpd, "shutdown", side_effect=stopped.set) as shutdown:
            status, _, raw = self.request("/api/shutdown", {})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)["stopping"])
            self.assertTrue(stopped.wait(timeout=2))
            shutdown.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
