"""Offline curiosity-policy wiring and question-only audit contract checks.

Mocks establish integration and mutation boundaries, not model question quality.
The fictional cases can also be imported by an explicitly invoked real-model
evaluation; importing this module never calls a provider.
"""
import copy
import unittest
from unittest.mock import Mock

from test_server import server


CURIOSITY_CASES = (
    {
        "id": "unnamed_start_mechanism",
        "process_name": "Getting ready to leave home",
        "turns": [
            {"id": "a1", "role": "assistant", "text": "Walk me through how your morning starts."},
            {"id": "u1", "role": "user", "text": "I wake up, get dressed, pack my bag and leave home."},
        ],
        "candidate_question": "What do you do next?",
        "contract_example": "What usually wakes you up?",
        "expected_information_need": "Clarify the unreported initiating mechanism for waking, without assuming an alarm, another person, or a fixed time.",
        "avoid": "Skipping straight to another step, or treating an alarm or another waking mechanism as established.",
    },
    {
        "id": "mechanism_already_volunteered",
        "process_name": "Getting ready to leave home",
        "turns": [
            {"id": "a1", "role": "assistant", "text": "Walk me through how your morning starts."},
            {"id": "u1", "role": "user", "text": "My phone alarm wakes me at seven. I turn it off, get dressed, pack my bag and leave home."},
        ],
        "candidate_question": "What usually wakes you up?",
        "contract_example": "How do you decide you are ready to leave?",
        "expected_information_need": "Choose an unanswered useful dimension, such as the finished condition, instead of re-asking the volunteered waking mechanism or time.",
        "avoid": "Repeatedly asking how or when waking happens, or inventing a failure of the alarm.",
    },
    {
        "id": "shorthand_check",
        "process_name": "Sending a prepared file",
        "turns": [
            {"id": "a1", "role": "assistant", "text": "What do you do before the file goes to Operations?"},
            {"id": "u1", "role": "user", "text": "I check the file, then email it to Operations."},
        ],
        "candidate_question": "What happens after you email it?",
        "contract_example": "What do you look for when you check the file?",
        "expected_information_need": "Unpack the actual check or readiness criterion before treating the shorthand as an explained action.",
        "avoid": "Assuming the file is checked against a total, checklist or another unreported standard.",
    },
    {
        "id": "exception_outcome",
        "process_name": "Sending a reconciled file",
        "turns": [
            {"id": "a1", "role": "assistant", "text": "What happens after you compare the totals?"},
            {"id": "u1", "role": "user", "text": "If the total differs I park the file. Otherwise I send it to Operations."},
        ],
        "candidate_question": "Where do you store the completed file?",
        "contract_example": "What happens to a file after you park it?",
        "expected_information_need": "Explore the reported exception's handling, outcome or rejoin without inventing its resolution.",
        "avoid": "Assuming a manager repairs the file, an escalation exists, or the parked file returns to the normal route.",
    },
    {
        "id": "unknown_detail_and_resolver",
        "process_name": "Receiving an automated file",
        "turns": [
            {"id": "u1", "role": "user", "text": "A file arrives in the shared mailbox and I check it before sending it on. I do not know how the sending system decides when to run."},
            {"id": "a1", "role": "assistant", "text": "Who or what source could explain the sending schedule?"},
            {"id": "u2", "role": "user", "text": "I do not know who owns it or any source that would explain it. I cannot add more about that schedule."},
        ],
        "candidate_question": "Who else might know what triggers the sending system?",
        "contract_example": "What do you look for when you check the received file?",
        "expected_information_need": "Retain the unavailable schedule and resolving source as gaps and select a different answerable process detail.",
        "avoid": "Rephrasing the unknown trigger, demanding a guess, or continuing a chain of resolver questions.",
    },
    {
        "id": "incidental_detail_not_a_tangent",
        "process_name": "Sending an approved package",
        "turns": [
            {"id": "a1", "role": "assistant", "text": "How do you prepare the package?"},
            {"id": "u1", "role": "user", "text": "I put the approved documents in a folder and send the package to Operations. My mug is blue; that has nothing to do with this work."},
        ],
        "candidate_question": "Why is your mug blue?",
        "contract_example": "How do you check that the package is ready to send?",
        "expected_information_need": "Follow a process-relevant readiness, action or handoff gap rather than incidental trivia.",
        "avoid": "Questions about the mug or other details explicitly unrelated to the process goal.",
    },
    {
        "id": "targeted_correction_retains_later_work",
        "process_name": "Backlog refinement",
        "turns": [
            {"id": "u1", "role": "user", "text": "I prepare the board, prioritize the ideas, update their details, then link the supporting issue or document."},
            {"id": "a1", "role": "assistant", "text": "How do you prepare the board?"},
            {"id": "u2", "role": "user", "text": "Correction: replace that first step with getting water so I am settled before starting. The later prioritizing, updating and linking steps still apply."},
        ],
        "candidate_question": "What is the next step after getting water?",
        "contract_example": "What do you look at when prioritizing an idea?",
        "expected_information_need": "Preserve the correction and already reported later sequence, then deepen one unanswered practical detail.",
        "avoid": "Restarting the walkthrough, re-asking the already supplied next step, or withdrawing unrelated actions.",
    },
    {
        "id": "explicit_stop",
        "process_name": "Preparing a recurring file",
        "turns": [
            {"id": "u1", "role": "user", "text": "I receive a file, check it and send it to Operations. Some of the exact checks are still unclear."},
            {"id": "a1", "role": "assistant", "text": "What do you check in the file?"},
            {"id": "u2", "role": "user", "text": "I need to stop now. Leave those gaps recorded; I do not want another question today."},
        ],
        "candidate_question": "Which file field do you check first?",
        "contract_example": "We can pause here and keep those unanswered details recorded.",
        "expected_information_need": "Honor the explicit stop with an acknowledgment, optional recap or pause rather than another substantive probe.",
        "avoid": "Continuing the interview, pressuring completion, or claiming that the remaining gaps are resolved.",
    },
)


def curiosity_payload(case):
    """Detached fictional input, suitable for offline mocks or an opt-in replay."""
    return {
        "context": {"process_name": case["process_name"], "process_owner": "",
                    "objective": "Understand the described process and retain its unresolved details.",
                    "background": "Fictional questioning evaluation, not an actual business account."},
        "turns": copy.deepcopy(case["turns"]),
        "action": "answer",
    }


def candidate_capture(case):
    participant = next(turn for turn in case["turns"] if turn["role"] == "user")
    findings = [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                for key in server.COVERAGE]
    next(finding for finding in findings if finding["key"] == "name").update(
        status="partial", answer=case["process_name"], evidence_turns=["context"])
    next(finding for finding in findings if finding["key"] == "lifecycle").update(
        status="partial", answer=participant["text"], evidence_turns=[participant["id"]])
    return {"question": case["candidate_question"], "summary": "A fictional account with unresolved detail.",
            "ready_for_draft": False, "focus": "Understand the reported action", "parking_lot": [],
            "closure": {"asked": False, "confirmed": False}, "memo_findings": findings,
            "coverage": [{"key": key, "label": label, "status": "partial"}
                         for key, label in server.COVERAGE.items()]}


class CuriosityPolicyContractTests(unittest.TestCase):
    def test_shared_policy_reaches_initial_interview_and_question_audit(self):
        case = CURIOSITY_CASES[2]
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-fictional-curiosity-contract"})
        client.structured = Mock(side_effect=[candidate_capture(case), {"question": case["contract_example"]}])
        client.interview(curiosity_payload(case))
        self.assertEqual(client.structured.call_count, 2)
        initial, audit = client.structured.call_args_list
        for call in (initial, audit):
            self.assertIn(server.CURIOSITY_POLICY, call.args[0])
            self.assertIn(server.QUESTIONING_POLICY, call.args[0])
            self.assertIn(server.CORRECTION_SCOPE_POLICY, call.args[0])
        self.assertEqual(initial.args[3], "process_interview")
        self.assertEqual(audit.args[3], "process_next_question_audit")
        self.assertEqual(set(audit.args[2]["properties"]), {"question"})
        self.assertEqual(initial.args[1]["turns"], audit.args[1]["turns"])

    def test_shared_policy_reaches_voice_and_its_delegation_without_bloating_top_level_foundation(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-fictional-curiosity-contract"})
        sdp = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        client.request = Mock(return_value={"session": {"id": "live_fictional_curiosity"}, "transport": {"sdp": sdp}})
        client.live_session({**curiosity_payload(CURIOSITY_CASES[0]), "sdp": sdp})
        session = client.request.call_args.args[1]["session"]
        top = session["instructions"]
        delegated = session["delegation"]["responses"]["instructions"]
        self.assertIn(server.CURIOSITY_POLICY, top)
        self.assertIn(server.CURIOSITY_POLICY, delegated)
        self.assertNotIn("SERVER-OWNED INTERVIEW FOUNDATION", top)
        self.assertIn("SERVER-OWNED INTERVIEW FOUNDATION", delegated)
        self.assertEqual(session["delegation"]["responses"]["tools"], [])

    def test_focused_deeper_or_respectful_pause_questions_preserve_the_validated_account(self):
        for case in CURIOSITY_CASES:
            with self.subTest(case=case["id"]):
                payload = curiosity_payload(case)
                original_payload = copy.deepcopy(payload)
                candidate = candidate_capture(case)
                expected = server.validate_interview(copy.deepcopy(candidate), payload["turns"])
                client = server.OpenAIClient({"OPENAI_API_KEY": "sk-fictional-curiosity-contract"})
                client.structured = Mock(side_effect=[candidate, {"question": case["contract_example"]}])
                result = client.interview(payload)
                if case["id"] == "explicit_stop":
                    self.assertIn("stop here", result["question"])
                    self.assertIn("partial capture", result["question"])
                    self.assertNotIn("?", result["question"])
                    self.assertEqual({**result, "question": expected["question"]}, expected)
                else:
                    self.assertEqual(result, {**expected, "question": case["contract_example"]})
                self.assertEqual(payload, original_payload)
                audited = client.structured.call_args_list[1].args[1]
                self.assertEqual(audited["memo_findings"], expected["memo_findings"])
                self.assertEqual(audited["closure"], expected["closure"])
                self.assertNotIn("coverage", audited)
                self.assertNotIn("ready_for_draft", audited)

    def test_named_action_does_not_answer_its_unexplained_mechanism(self):
        self.assertTrue(server.CURIOSITY_POLICY.strip())
        policy = server.CURIOSITY_POLICY.lower()
        self.assertIn("mechanism", policy)
        self.assertIn("unanswered", policy)
        self.assertIn(server.CURIOSITY_POLICY, server.NEXT_QUESTION_INSTRUCTIONS)
        self.assertIn("Preserve a final-check acknowledgment or the participant's choice to stop", server.NEXT_QUESTION_INSTRUCTIONS)

    def test_fictional_replays_are_detached_and_have_explicit_review_criteria(self):
        self.assertEqual(len({case["id"] for case in CURIOSITY_CASES}), len(CURIOSITY_CASES))
        for case in CURIOSITY_CASES:
            payload = curiosity_payload(case)
            self.assertTrue(case["expected_information_need"])
            self.assertTrue(case["avoid"])
            self.assertTrue(any(turn["role"] == "user" for turn in payload["turns"]))
            payload["turns"][0]["text"] = "Changed test copy"
            self.assertNotEqual(payload["turns"][0]["text"], case["turns"][0]["text"])


if __name__ == "__main__":
    unittest.main()
