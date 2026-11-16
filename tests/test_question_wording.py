"""Ordinary process wording is not interview closure, and wording never fails a turn.

Offline: the real server patterns and the real typed, team and HTTP paths with scripted
model replies. No provider, microphone or credentials are used.
"""
import copy
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_interview_orchestrator import SyntheticTeamProvider, prepared_review
from test_server import server, interview_result

concurrent = server.local_module("concurrent_interview", "concurrent_interview.py")
orchestrator = server.interview_orchestrator

# Questions a lead interviewer may reasonably ask about the work itself. Each one was
# refused by the earlier closing-language or question-mark checks.
ORDINARY = (
    "What does the senior compare the amounts against?",
    "Do you round up or down to the nearest cent when you allocate the call?",
    "When an investor's share is rounded up, who absorbs the difference?",
    "Who signs off on rounding up the management fee?",
    "Who rounds out the last allocation so the total ties to the notice?",
    "Is there anything else the senior compares before the notice is released?",
    "Besides the bank statement, is there anything else you attach to the journal?",
    "How do you confirm nothing else is outstanding on the checklist?",
    "Who decides that the capital call notice is ready to draft?",
    "When is the pack ready for drafting the investor letter?",
    "What has to be reconciled before we can end the quarter in the ledger?",
    "What do you do once you have enough to finish the reconciliation?",
    "At what point do you wrap up the month-end close?",
    "Who decides when we can stop chasing the custodian?",
    "That gives me a clear picture of the trigger. What does the senior compare the amounts against?",
    "Talk me through how a capital call normally goes.",
    "What does the senior compare before release? Take your time.",
    "Does the reviewer confirm that nothing more is outstanding on the checklist before release?",
    "Do you round up or down when the investor amounts do not divide evenly?",
    "When allocations are rounded up, who absorbs the difference?",
    "Who rounds out the notice with the wire instructions?",
    "What do you do to wrap up the month-end close?",
    "Is anything else attached to the capital call notice before it goes out?",
    "When the bank has nothing more to confirm, what happens to the notice?",
    "Who decides the financial statements are ready for draft review?",
    "What must be approved before we finish month-end close?",
    "What has to be true before we end each quarter's allocation run?",
    "Thanks for sharing that. Who approves the notice after the senior checks the amounts?",
    "Thank you for sharing that detail - what does the senior compare the amounts against?",
    "At what point do you decide you have enough to finish the reconciliation?",
    "How do you know we can stop chasing the investor for the wire?",
    "Do you round up the fee to the nearest cent before it is posted?",
    "When you wrap up the month-end close, who signs off the reconciliation?",
    "Does anything else trigger this work besides the capital call notice?",
    "Is the batch ready to finish once both approvals are recorded?",
    "Please walk me through what the analyst does after logging the invoice.",
    "What do you round up to?",
    "How are the investor amounts rounded up?",
    "What do you do when you wrap up the till at the end of the day?",
    "What makes the pack ready to finish?",
    "Is there anything else you check before releasing the payment?",
    "What happens when nothing else is outstanding on the checklist?",
    "Thanks for sharing that. What does the manager check?",
    "Is there anything else the Senior Fund Accountant checks before the invoice is created?",
    "Do you round up, or to the nearest cent?",
    "What happens when nothing more is needed from the client?",
    "Please describe what the senior compares before the notice is released.",
    "Tell me what happens to the fund if the wire is sent late.",
    "Yes, that is enough for a baseline. When the client asks 'is it final?', who answers them?",
    # Closing vocabulary with the work as its object, and requests that mention finishing the work.
    "Is there anything else you need to add to the journal before it is posted?",
    "Is there anything else the reviewer should know before signing the reconciliation?",
    "Is there anything else important the senior checks on the wire instruction?",
    "When the custodian has nothing more to add, who closes the query?",
    "How do you know when you have enough to draft the report?",
    "How do you decide you are ready to draft the report?",
    "At what point are you ready to finish the account reconciliation?",
    "How do you record that you have captured all the trades for the day?",
    "How do you confirm you have covered all the investors in the allocation?",
    "When you wrap up, who signs off the reconciliation?",
    "After wrapping up the session in the portal, what gets exported?",
    "What has to be in place before we end the session with the client?",
    "Who signs off before we finish the capital call?",
    "Walk me through the review step.",
    "Describe the exception path when the bank file is late.",
    "Help me understand who releases the wire.",
    "Could you say more about the exception report.",
    "Yes, the notice comes first. Talk me through what happens next.",
    "Talk me through how the senior reviews the allocation. Take your time.",
    "Describe what you do once you are done with the reconciliation.",
    "Explain how the draft notice is reviewed before it goes to the client.",
    "Tell me when the notice goes out and who sends it.",
    # Brief answers and acknowledgements before the question. The closing-statement check
    # once refused each of them, although they were asked as written before it existed.
    "I have what I need on the trigger. What happens after the notice goes out?",
    "We have everything we need on timing. Who reviews the notice before release?",
    "That's everything for now on the trigger. What happens after the notice goes out?",
    "Feel free to estimate. Roughly how many invoices do you process each month?",
    "Feel free to check your notes. How many investors were in the last call?",
    "Yes, go ahead and use last month as the example. What triggered the capital call?",
    "You can come back to that. What does the reviewer check first?",
    "Sure, you can come back to the volumes later. Who approves the notice?",
    "Yes, you can tell me about the exception first. What went wrong?",
    "You can review the notes on the right at any time. What happens after the notice goes out?",
    "Yes, you can review the draft notice in the portal. Who signs it off?",
    "Yes, start with the draft notice. Who prepares it?",
    "Okay, let me check the notes I have on that. Was it the administrator who sends the notice?",
    "I will check the notes after this answer. Who reviews the notice before release?",
    "Got it, the KYC conversation is finished first. What happens next?",
    "So the onboarding interview is complete at that point. Who files the form?",
    "Right, the summary is ready for review. Who reviews it?",
    "So the notes are complete for the draft. Who writes the draft?",
    "Tell me if there is a threshold. Who approves above it?",
    "Let me know if you want me to rephrase. What triggers the capital call?",
    "Right, so the custodian has nothing further. Who closes the query?",
    "This is my last question on the trigger. What time does the file arrive?",
    # Spoken requests that use the same words about the work.
    "Please go ahead and walk me through the reconciliation.",
    "Go ahead and describe what the senior checks first.",
    "Tell me when you normally send the notice.",
    "Describe what you should check in the notes column.",
    "Tell me what you can read from the summary page.",
    "Explain what happens once the client conversation is finished.",
    "Describe who can close the conversation with the client in the portal.",
    "Describe what happens when the draft is ready.",
    "Tell me who should receive the draft notice.",
    "Who approves it? A rough answer is fine.",
)

# Wording that closes, or offers to close, the whole interview. It must stay refused.
CLOSING = (
    "Anything else?",
    "Is there anything else?",
    "Is there anything else you would like to add?",
    "Is there anything else you'd like to add before we finish?",
    "Is there anything else we should cover?",
    "Do you have anything else to add about this process?",
    "Is there anything else that we have not captured?",
    "Is there anything else important that we haven't discussed?",
    "Is there anything else someone doing this work needs to know that we haven't captured?",
    "Is there anything else you can think of?",
    "Is there anything else that would be helpful for me to know?",
    "Is there anything else a new joiner should know?",
    "Is there anything else at this point?",
    "Do you have anything else for me?",
    "That helps round out the picture. Anything else before we pause?",
    "Anything else before we wrap up?",
    "Anything else before we finish?",
    "Before we finish, is there anything else someone doing this work needs to know that we haven't captured?",
    "If there is nothing else, would you like to see the notes?",
    "It sounds like there is nothing more to add. Is that right?",
    "Shall we wrap up?",
    "Can we wrap up the interview?",
    "I think we can stop here. Is that okay?",
    "We can end the interview now. Does that suit you?",
    "Let's pause. Would you like to continue later?",
    "I have enough to draft the memo. Would you like to see it?",
    "Are you ready to finish?",
    "That gives me a complete picture of the process. Would you like to review it?",
    "That gives me a clear picture. Would you like to review it?",
    "Thanks for your time. Is that all right?",
    "Thank you for your time today. Would you like a copy?",
    "We have covered everything. Would you like to review it?",
    "Your account is captured. Would you like to create the draft?",
    "You can create the draft now. Would you like to?",
    "That is helpful, thanks for sharing.",
    # The interview under another name, omission questions and readiness in other words.
    "Shall we wrap up our discussion?",
    "Can we wrap up the call?",
    "Should we wrap up this meeting?",
    "Shall we wrap up this call?",
    "Shall we wrap up our chat?",
    "We can end the call here. Is that OK?",
    "Let's finish our chat here. Okay?",
    "We can stop the recording now. Is that all right?",
    "We can stop if you'd like. Would you like to?",
    "We can stop if you would like. Is that okay?",
    "Is there anything else I should be asking you?",
    "Is there anything else I should be asking?",
    "Is there anything else you feel we left out?",
    "Is there anything else that I am not asking about?",
    "Is there anything else that springs to mind?",
    "Is there anything else in the process that we did not get to?",
    "Let me wrap up with one last question: is there something we missed?",
    "There is nothing else I need. Shall I draft?",
    "I think I've got enough to draft the memo. Shall I go ahead?",
    "I now have enough to draft the process memo. Would you like to see it?",
    "That should be enough to draft the memo. Shall I prepare it?",
    "I'm ready to draft whenever you are. Shall I start?",
    "Do you feel ready to finish?",
    "That gives me a clear and complete picture. Shall I draft?",
    "Thanks for sharing all of that. I will put the draft together, okay?",
    "You've covered everything I wanted. Shall I draft it?",
    "We've covered all the topics. Shall I draft it?",
    "I think we've covered all the key areas. Is there anything you'd like to add?",
    "I have enough to draft this now. Are you ready?",
    "Would you like to add anything else or shall we conclude here?",
    "Has anything else come to mind?",
    "Has anything else occurred to you that we should add?",
)

# Replies that ask nothing, or that close, defer or hand over to the draft in a statement.
# The question-mark rule used to refuse all of them; none may be spoken as the next question.
CLOSING_STATEMENTS = (
    "Got it. Consider this interview complete.",
    "Thank you, I have what I need. Let me know if you would like to review the notes.",
    "That covers it. Tell me if you think of something later.",
    "Okay. Go ahead and open the draft.",
    "Please go ahead and create the draft.",
    "Great. Go ahead and create the draft when you are ready.",
    "Thank you. Start the draft whenever you like.",
    "That completes the interview. Tell me if you want a copy.",
    "The notes are complete. Go ahead and submit them.",
    "Thanks, that covers it. Let me know if anything changes.",
    "Thanks, that's all I need. Let me know if you'd like to add anything.",
    "I have what I need for now. You can tell me more later.",
    "You can tell me later.",
    "Tell me when you would like to stop.",
    "Could you confirm we are done.",
    "Would you close the session now.",
    "I'd like to know whether you are happy to finish.",
    "Great, I have the full picture now. Can you review the notes on the right when you have a moment.",
    "Thanks. Share the notes with your manager when you are ready.",
    "Okay. Think that covers it.",
    "Name and date are captured.",
    "Share classes are allocated by the administrator.",
    "The senior can explain the rest.",
    "Is that everything? If so, you can press Create draft.",
    "Is that right? If so, the interview is complete.",
    "Is that correct? Your account is complete.",
    "Does that sound right? Then we're done.",
    "Who approves it? That's all I need.",
    "Who approves it? After that we are done.",
    "What else? Then I will close the interview.",
    "This interview is complete. Do you want to save it?",
    # Only a courtesy may follow the question; a reply without a question mark may not open
    # by declaring the draft ready or the interviewer finished, or ask about the draft itself.
    "Is that right? I'll draft it now.",
    "Is that right? Then the draft is ready.",
    "Who approves it? That is my last question.",
    "Who approves it? Then I can start writing.",
    "Is that right? Take care.",
    "The draft is ready. Tell me who should receive it.",
    "Great. I'd like to see the draft now.",
    "Thanks, I am finished. Tell me how you want the memo.",
    "Thanks. Tell me more later.",
    "I've finished my questions. Tell me how it went.",
    "Okay, I'll draft it now. Is that all right?",
    "Thanks, I am finished. Who should get the memo?",
)

# Ordinary questions that the team path's completion-speech check used to refuse.
COMPLETION_COLLISIONS = (
    "What happens to invoices that are not covered by a purchase order?",
    "What do you do with claims that are not mentioned in the policy schedule?",
    "What do you do once you're done with the reconciliation?",
    "How do you check that the documentation is complete before onboarding the investor?",
    "How do you know the account is ready for the auditor?",
    "How do you confirm all sections are complete before filing the return?",
)

# Completion claims and omission checks the team path must keep refusing.
COMPLETION_CLAIMS = (
    "Your account is complete. Would you like to review it?",
    "The documentation is ready for review. Shall I continue?",
    "The account is ready for process-owner review. Is that what you expected?",
    "This interview is complete. Do you want to save it?",
    "All sixteen sections are covered. Would you like a summary?",
    "We are done with the interview. Is that what you expected?",
    "You're all set. Do you have any questions for me?",
    "Is there anything we have not covered?",
    "What have I not asked about?",
    "Is there anything important about volunteer schedule packets that I haven't asked about?",
    # The same words as the collisions above, with the interview as their object.
    "We're done with the questions. Shall I create the draft?",
    "We are done with my questions. Would you like to review the notes?",
    "We are finished with everything I needed. Is that okay?",
    "We're done with your account. Would you like to review it?",
    "We're done with that. Shall I draft it?",
    "You're done with your part. Shall I prepare the memo?",
    "You're done with my questions. Would you like to see the notes?",
    "You're all set with this. Do you have any questions?",
    "Your account is ready when you are. Would you like to review it?",
    "Your account is complete once you confirm it. Do you confirm?",
    "Your account is ready for the process owner. Would you like to see it?",
    "Your account is complete for the purposes of the memo. Shall I draft it?",
    "The account is complete for our purposes. Shall I draft it?",
    "The account is ready for a first draft. Shall I create it?",
    "The account is ready for you to look over. Would you like to?",
    "The documentation is complete once you confirm. Do you confirm?",
    "The documentation is complete when you say so. Is it?",
    "All sections are covered once you confirm this. Do you confirm?",
    "All sections are covered once you confirm this last point. Do you confirm?",
    "All sixteen topics are covered after that answer. Would you like a summary?",
    "All required topics are complete when you agree. Do you agree?",
    "Is there anything not covered in the account so far?",
    "Is there anything important not mentioned in the account so far?",
    "Is there anything not covered in our conversation so far?",
    "Is there something not mentioned in the summary I gave?",
    "What is not covered by the notes we have taken?",
    "What is not captured by our discussion so far?",
    # A sentence that opens with the claim is a claim whatever follows it, and the
    # interview's own topics, questions and answers are not process documents.
    "The account is ready for the write-up. Shall I begin?",
    "The account is complete after your last answer. Would you like to review it?",
    "The account is complete for the final check. Are you ready?",
    "The documentation is complete before drafting. Shall I draft?",
    "You're finished with the process walkthrough. Shall I draft it?",
    "All sections are covered before the draft. Shall I create it?",
    "Is there anything not covered in the topics so far?",
    "Is there anything not covered by the questions so far?",
    "Is there anything not covered in your answers?",
    "Is there anything not mentioned in the transcript?",
)


def typed_payload():
    return {"context": {"process_name": "Capital call allocation (fictional)", "process_owner": "",
                        "objective": "", "background": "Fictional training example."},
            "turns": [{"id": "a1", "role": "assistant", "text": "Could you walk me through how this work normally goes?"},
                      {"id": "u1", "role": "user", "text": "I split the call across investors by commitment share and the senior reviews it."}],
            "_supporting_documents": {}, "action": "answer"}


class ScriptedQuestion:
    """structured() returns the scripted reply; background capture returns a fixed capture."""
    agent_models = {"lead_interviewer": "offline-model"}

    def __init__(self, question, capture=None, gate=None):
        self.question, self.calls, self.events, self.captures, self.gate = question, 0, [], 0, gate
        self.capture = capture if capture is not None else {"question": "Not spoken.", "marker": "stub"}
        self.diagnostic_callback = lambda event, **fields: self.events.append((event, fields))
        self.coordinator = types.SimpleNamespace(interview=self.interview, workflow=lambda value: {"workflow": {"steps": []}})

    def structured(self, instructions, data, schema, name, tokens, **kwargs):
        assert name == "conversation_question"
        self.calls += 1
        return {"question": self.question, "request_review": False}

    def interview(self, value):
        self.captures += 1
        if self.gate and self.captures > 1:
            self.gate.wait(5)
        return copy.deepcopy(self.capture)


class ClosingLanguageTests(unittest.TestCase):
    def test_process_vocabulary_is_not_interview_closure(self):
        for question in ORDINARY + COMPLETION_COLLISIONS:
            with self.subTest(question=question):
                self.assertIsNone(server.WRAP_UP_LANGUAGE.search(question))

    def test_anything_else_about_one_topic_is_not_the_final_omissions_question(self):
        for question in ("Anything else about late edits?", "Anything else about that step?",
                         "Is there anything else before we close the books?",
                         "Is there anything else you add to the journal when the bank statement is late?"):
            with self.subTest(question=question):
                self.assertIsNone(server.WRAP_UP_LANGUAGE.search(question))

    def test_whole_interview_closure_is_still_recognised(self):
        for question in CLOSING:
            with self.subTest(question=question):
                self.assertIsNotNone(server.WRAP_UP_LANGUAGE.search(question))

    def test_server_closing_messages_remain_closing_language(self):
        for text in (server.FINAL_CHECK_PREFIX + " someone doing this work needs to know that we haven't captured?",
                     "Thank you. Your account is captured for review. You can create or update the draft now;"):
            self.assertIsNotNone(server.WRAP_UP_LANGUAGE.search(text))

    def test_completion_speech_ignores_process_objects_and_keeps_completion_claims(self):
        # The completion check is part of the shared wording check: the Coordinator has no
        # pattern of its own, and the typed path refuses the same claims.
        team = types.SimpleNamespace(api=server)
        for question in ORDINARY + COMPLETION_COLLISIONS:
            with self.subTest(question=question):
                self.assertEqual(orchestrator.Coordinator._question_rejection(team, question), "")
        for question in COMPLETION_CLAIMS:
            with self.subTest(question=question):
                self.assertIn(orchestrator.Coordinator._question_rejection(team, question), ("completion_speech", "closing_statement"))
                self.assertIn(server.question_rejection(question, 1200), ("completion_speech", "closing_statement"))


class QuestionShapeTests(unittest.TestCase):
    def test_ordinary_questions_and_spoken_requests_are_usable(self):
        for question in ORDINARY + COMPLETION_COLLISIONS:
            with self.subTest(question=question):
                self.assertEqual(server.question_rejection(question, 1200, single=True), "")

    def test_rejections_carry_a_metadata_only_reason_code(self):
        cases = {"": "empty", "   ": "empty", "Please explain " + "detail " * 200 + "?": "too_long",
                 "Thanks, that is clear.": "no_question_mark", "Understood.": "no_question_mark",
                 "The senior reviews the allocation before release.": "no_question_mark",
                 "What does the senior compare? I will note that the reviewer signs every page of the pack before it leaves.": "no_question_mark",
                 "Is there anything else you would like to add?": "wrap_up_match",
                 "I think we can stop here.": "wrap_up_match",
                 "Name and date are captured.": "no_question_mark",
                 "Describe the review. The senior can explain the rest.": "no_question_mark",
                 "Got it. Consider this interview complete.": "closing_statement",
                 "Tell me when you would like to stop.": "closing_statement",
                 "Is that correct? Your account is complete.": "closing_statement",
                 "Is that everything? If so, you can press Create draft.": "closing_statement"}
        for text, reason in cases.items():
            with self.subTest(text=text[:60]):
                self.assertEqual(server.question_rejection(text, 1200), reason)
        self.assertEqual(server.question_rejection(None, 1200), "empty")

    def test_reply_that_asks_nothing_or_closes_in_a_statement_is_refused(self):
        # A request phrase somewhere in the reply is not a request: it has to be the last
        # sentence, and no statement beside it may close, defer or hand over to the draft.
        for text in CLOSING_STATEMENTS:
            with self.subTest(text=text):
                self.assertIn(server.question_rejection(text, 1200), ("closing_statement", "no_question_mark"))
                self.assertNotEqual(server.question_rejection(text, 1600, single=True), "")

    def test_only_a_courtesy_may_follow_the_question(self):
        for remark in ("Take your time.", "No rush.", "An example would help.", "A rough answer is fine.", "Feel free to estimate."):
            with self.subTest(remark=remark):
                self.assertEqual(server.question_rejection("Who approves it? " + remark, 1200, single=True), "")
        for remark in ("I'll draft it now.", "Then the draft is ready.", "That is my last question.", "Then I am finished.", "Bye."):
            with self.subTest(remark=remark):
                self.assertEqual(server.question_rejection("Who approves it? " + remark, 1200), "closing_statement")
        self.assertEqual(server.question_rejection("Who approves it? The senior signs every page.", 1200), "no_question_mark")

    def test_claim_that_opens_a_sentence_differs_from_a_restated_answer(self):
        for claim in ("The documentation is complete. Would you like a copy?", "The account is ready for review. Shall I continue?"):
            self.assertEqual(server.question_rejection(claim, 1200), "closing_statement")
        for restated in ("Understood, the documentation is complete. Who checks it?",
                         "Understood, the account is ready. Who releases the payment?",
                         "So once you are done, the file goes to the senior. What does the senior check?",
                         "Okay, we are finished with intake by then, as you said. What is the first allocation step?"):
            self.assertEqual(server.question_rejection(restated, 1200), "")

    def test_bundled_questions_are_refused_only_where_one_question_is_required(self):
        bundled = "Who approves it? Where is the approval recorded?"
        self.assertEqual(server.question_rejection(bundled, 1200), "")
        self.assertEqual(server.question_rejection(bundled, 1200, single=True), "several_questions")
        quoted = 'When the client asks "is it final?", who answers them?'
        self.assertEqual(server.question_rejection(quoted, 1200, single=True), "")

    def test_canned_fallback_questions_pass_the_same_check(self):
        result = interview_result()
        for status in ("unknown", "partial"):
            for finding in result["memo_findings"]:
                finding["status"] = status
            question = server.next_uncovered_question(result)
            self.assertEqual(server.question_rejection(question, 1600, single=True), "")

    def test_rejection_record_is_reason_only_and_cannot_fail_the_turn(self):
        events = []
        client = types.SimpleNamespace(diagnostic_callback=lambda event, **fields: events.append((event, fields)))
        server.record_question_rejection(client, "fast_question", "wrap_up_match")
        self.assertEqual(events, [("question_rejected", {"stage": "fast_question", "reason": "wrap_up_match"})])

        def fail(event, **fields):
            raise RuntimeError("diagnostics unavailable")
        server.record_question_rejection(types.SimpleNamespace(diagnostic_callback=fail), "fast_question", "empty")
        server.record_question_rejection(types.SimpleNamespace(), "fast_question", "empty")


class TypedPathTests(unittest.TestCase):
    """ConcurrentInterview.turn with the real server module, as /api/conversation/turn uses it."""

    def service(self, client):
        instance = concurrent.ConcurrentInterview(client, server)
        self.addCleanup(instance.close)
        return instance

    def test_ordinary_question_or_request_is_asked_as_written(self):
        for question in ORDINARY:
            with self.subTest(question=question):
                client = ScriptedQuestion(question)
                result = self.service(client).turn(typed_payload())
                self.assertEqual(result["question"], question)
                self.assertEqual(result["speech_authorization"]["text"], question)
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertFalse(result["sync_required"])
                self.assertEqual([event for event in client.events if event[0] == "question_rejected"], [])

    def test_unusable_reply_becomes_a_neutral_question_instead_of_an_error(self):
        cases = {"Is there anything else you would like to add before we finish?": "wrap_up_match",
                 "I think we can stop here. Is that okay?": "wrap_up_match",
                 "Thanks, that is clear.": "no_question_mark",
                 "": "empty",
                 "Please explain " + "detail " * 200 + "?": "too_long"}
        for question, reason in cases.items():
            with self.subTest(reason=reason, question=question[:50]):
                client = ScriptedQuestion(question)
                result = self.service(client).turn(typed_payload())
                self.assertEqual(result["question"], "What happens next in this work?")
                self.assertEqual(result["speech_authorization"],
                                 {"approved": True, "text": "What happens next in this work?", "kind": "question",
                                  "revision": result["revision"], "completion_allowed": False})
                self.assertFalse(result["sync_required"])
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual(len(result["conversation_token"]), 64)
                # One provider call: wording is repaired locally, never by a hidden paid retry.
                self.assertEqual(client.calls, 1)
                self.assertEqual([event for event in client.events if event[0] == "question_rejected"],
                                 [("question_rejected", {"stage": "fast_question", "reason": reason})])
                if question:
                    self.assertNotIn(question, json.dumps(client.events))

    def test_closing_wording_is_never_spoken_as_the_next_question(self):
        for reply in CLOSING + CLOSING_STATEMENTS:
            with self.subTest(reply=reply):
                client = ScriptedQuestion(reply)
                result = self.service(client).turn(typed_payload())
                self.assertEqual(result["question"], "What happens next in this work?")
                self.assertEqual(result["speech_authorization"]["text"], "What happens next in this work?")
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual(len([event for event in client.events if event[0] == "question_rejected"]), 1)
                self.assertNotIn(reply, json.dumps(client.events))

    def test_fallback_does_not_repeat_the_question_just_asked(self):
        client = ScriptedQuestion("Thanks, that is clear.")
        payload = typed_payload()
        payload["turns"] += [{"id": "a2", "role": "assistant", "text": "What happens next in this work?"},
                             {"id": "u2", "role": "user", "text": "The manager approves the notice."}]
        result = self.service(client).turn(payload)
        self.assertEqual(result["question"], "Which part of this work should we go through next?")

    def test_model_that_keeps_closing_never_gets_the_same_question_twice_in_a_row(self):
        client = ScriptedQuestion("Is there anything else you would like to add before we finish?")
        service = self.service(client)
        payload = typed_payload()
        asked = []
        for number in range(2, 9):
            result = service.turn(copy.deepcopy(payload))
            self.assertFalse(result["sync_required"])
            asked.append(result["question"])
            payload["conversation_token"] = result["conversation_token"]
            payload["turns"] += [{"id": f"a{number}", "role": "assistant", "text": result["question"]},
                                 {"id": f"u{number}", "role": "user", "text": f"No, that is everything ({number})."}]
        self.assertEqual(asked[:3], ["What happens next in this work?", "Which part of this work should we go through next?",
                                     "What is a part of this work that you have not described yet?"])
        self.assertTrue(all(first != second for first, second in zip(asked, asked[1:])), asked)
        self.assertEqual(len([event for event in client.events if event[0] == "question_rejected"]), 7)
        self.assertEqual(client.calls, 7)

    def test_document_opening_fallback_does_not_ask_what_happens_next(self):
        client = ScriptedQuestion("Thanks for the file.")
        payload = typed_payload()
        payload["turns"] = []
        payload["_supporting_documents"] = {"documents": [{"name": "Procedure"}]}
        result = self.service(client).turn(payload)
        self.assertEqual(result["question"], "What starts this work?")
        self.assertEqual(client.calls, 1)
        # Without a process name there is no "this work" yet: the ordinary unnamed opening is used.
        payload["context"]["process_name"] = ""
        payload.pop("conversation_token", None)
        unnamed = self.service(ScriptedQuestion("Thanks for the file.")).turn(payload)
        self.assertEqual(unnamed["question"], "What work would you like to walk through?")

    def caught_up(self, capture, reply):
        """A service whose stored capture reflects every answer, and the payload of the next turn."""
        release = threading.Event()
        self.addCleanup(release.set)
        client = ScriptedQuestion("What does the senior compare the amounts against?", capture=capture, gate=release)
        service = self.service(client)
        payload = typed_payload()
        first = service.turn(payload)
        payload["conversation_token"] = first["conversation_token"]
        for _ in range(400):
            if service.status(payload)["state"] == "ready":
                break
            threading.Event().wait(.005)
        self.assertEqual(service.status(payload)["state"], "ready")
        payload["turns"].append({"id": "a2", "role": "assistant", "text": first["question"]})
        client.question = reply
        return service, client, payload

    def complete_capture(self):
        capture = interview_result()
        for finding in capture["memo_findings"]:
            finding["status"] = "captured"
        return capture

    def test_closing_reply_on_a_complete_account_hands_over_to_the_coordinator(self):
        # Nothing is open, so no canned question may say that sections still need clarification;
        # the closing transition belongs to the coordinator, as when the model requests a review.
        unavailable = interview_result()
        unavailable["coverage_assessment"] = {"topics": [
            {"key": finding["key"], "next_question": "", "participant_unavailable": True}
            for finding in unavailable["memo_findings"] if finding["status"] not in ("captured", "not_applicable")]}
        self.assertTrue(unavailable["coverage_assessment"]["topics"])
        for label, capture in (("every topic captured", self.complete_capture()), ("only unavailable topics open", unavailable)):
            for reply, reason in (("That covers everything I needed. Is there anything else you would like to add?", "wrap_up_match"),
                                  ("Got it. Consider this interview complete.", "closing_statement")):
                with self.subTest(capture=label, reason=reason):
                    service, client, payload = self.caught_up(capture, reply)
                    result = service.turn(copy.deepcopy(payload))
                    self.assertTrue(result["sync_required"])
                    self.assertEqual(result["question"], "")
                    self.assertNotIn("speech_authorization", result)
                    self.assertFalse(result["completion"]["complete"])
                    self.assertEqual([event for event in client.events if event[0] == "question_rejected"],
                                     [("question_rejected", {"stage": "fast_question", "reason": reason})])
                    self.assertEqual(client.calls, 2)

    def test_fallback_never_claims_open_sections_on_a_complete_account(self):
        service, client, payload = self.caught_up(self.complete_capture(), "Thanks, that is clear.")
        result = service.turn(copy.deepcopy(payload))
        self.assertFalse(result["sync_required"])
        self.assertEqual(result["question"], "What happens next in this work?")
        self.assertNotIn("still need clarification", result["question"])

    def test_malformed_stored_capture_cannot_fail_the_turn(self):
        no_assessment = interview_result()
        no_assessment["coverage_assessment"] = None
        no_question = interview_result()
        for finding in no_question["memo_findings"]:
            finding["status"] = "partial"
        no_question["coverage_assessment"] = {"topics": [{"key": finding["key"], "next_question": None}
                                                         for finding in no_question["memo_findings"]]}
        for label, capture in (("assessment is null", no_assessment), ("next question is null", no_question)):
            with self.subTest(capture=label):
                service, client, payload = self.caught_up(capture, "Is there anything else you would like to add?")
                result = service.turn(copy.deepcopy(payload))
                self.assertEqual(result["question"], "What happens next in this work?")
                self.assertEqual(result["speech_authorization"]["kind"], "question")

    def test_topic_question_is_used_only_when_the_capture_reflects_every_answer(self):
        capture = interview_result()
        service, client, payload = self.caught_up(capture, "Is there anything else you would like to add?")
        # The capture already reflects every answer: its first open topic is a safe question.
        current = service.turn(copy.deepcopy(payload))
        self.assertEqual(current["question"], server.next_uncovered_question(capture))
        self.assertEqual(current["question"], "What starts this work?")
        # A new answer is outside that capture, so a topic it may just have covered is not asked.
        payload["turns"].append({"id": "u2", "role": "user", "text": "The administrator's notice starts it."})
        lagging = service.turn(copy.deepcopy(payload))
        self.assertEqual(lagging["question"], "What happens next in this work?")

    def test_request_for_review_is_unchanged(self):
        client = ScriptedQuestion("")
        client.structured = lambda *args, **kwargs: {"question": "", "request_review": True}
        result = self.service(client).turn(typed_payload())
        self.assertTrue(result["sync_required"])
        self.assertNotIn("speech_authorization", result)
        self.assertEqual(client.events, [])

    def test_prompt_allows_the_spoken_request_its_shared_guidance_models(self):
        # The shared guidance models a walkthrough invitation; the fast-question policy must
        # not demand a question mark in the same prompt, and the check must accept that form.
        self.assertRegex(concurrent.question_policy(server), r"(?i)talk me through")
        self.assertNotIn("a single question ending in '?'", concurrent.QUESTION_POLICY)
        self.assertIn("one short request", concurrent.QUESTION_POLICY)
        self.assertIn("Do not ask a final omissions/confirmation question yourself.", concurrent.QUESTION_POLICY)
        self.assertEqual(server.question_rejection("Talk me through how a capital call normally goes.", 1200), "")


class TeamPathTests(unittest.TestCase):
    """Coordinator.interview and review, through the repository's schema-routed provider."""

    def lead(self, question, action="answer"):
        client = SyntheticTeamProvider()
        client.incomplete()
        client.result_changes["team_interview_capture"] = lambda result: result.update(question=question)
        events = []
        client.diagnostic_callback = lambda event, **fields: events.append((event, fields))
        payload = client.payload()
        payload["action"] = action
        return client.coordinator.interview(payload), events

    def test_lead_question_or_request_is_kept(self):
        for question in ORDINARY + COMPLETION_COLLISIONS:
            with self.subTest(question=question):
                result, events = self.lead(question)
                self.assertEqual(result["question"], question)
                self.assertEqual(result["speech_authorization"]["text"], question)
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertEqual(events, [])

    def test_closing_or_shapeless_lead_question_is_replaced_and_counted(self):
        cases = {"Is there anything else you would like to add?": "wrap_up_match",
                 "I think we can stop here. Is that okay?": "wrap_up_match",
                 "Thanks, that is clear.": "no_question_mark",
                 "Who approves it? Where is the approval recorded?": "several_questions",
                 "Your account is complete. Would you like to review it?": "closing_statement",
                 "Is there anything we have not covered?": "completion_speech"}
        for question, reason in cases.items():
            with self.subTest(question=question):
                result, events = self.lead(question)
                self.assertEqual(result["question"], "Some sections still need clarification: Consequences of failure. "
                                                     "Which of these can you help explain next?")
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual(events, [("question_rejected", {"stage": "team_question", "reason": reason})])
                self.assertNotIn(question, json.dumps(events))

    def test_completion_claims_are_still_never_spoken(self):
        for question in CLOSING + COMPLETION_CLAIMS + CLOSING_STATEMENTS:
            with self.subTest(question=question):
                result, events = self.lead(question)
                self.assertNotEqual(result["question"], question)
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertEqual(result["question"].count("?"), 1)
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual([event[1]["stage"] for event in events], ["team_question"])

    def reviewed(self, next_question):
        client = SyntheticTeamProvider()
        payload, _ = prepared_review(client)
        topic = next(item for item in client.assessment["topics"] if item["key"] == "risk")
        topic["gaps"] = ["A reported failure has no established consequence."]
        topic["dimensions"][0]["status"] = "unresolved"
        topic["next_question"] = next_question
        events = []
        client.diagnostic_callback = lambda event, **fields: events.append((event, fields))
        result = client.coordinator.review(payload)
        self.assertFalse(result["completion"]["ready_for_final_check"])
        self.assertEqual(result["speech_authorization"]["kind"], "question")
        return result, events

    def test_reviewer_question_or_request_is_kept(self):
        for question in ("Tell me what happens to the fund if the wire is sent late.",
                         "Do you round up or down when the allocation does not divide evenly?",
                         "Is there anything else the senior compares before the notice is released?"):
            with self.subTest(question=question):
                result, events = self.reviewed(question)
                self.assertEqual(result["question"], question)
                self.assertEqual(events, [])

    def test_closing_reviewer_question_is_replaced_and_counted(self):
        question = "Is there anything else you would like to add?"
        result, events = self.reviewed(question)
        self.assertNotEqual(result["question"], question)
        self.assertEqual(result["question"].count("?"), 1)
        self.assertEqual(events, [("question_rejected", {"stage": "review_question", "reason": "wrap_up_match"})])

    def test_refused_reviewer_question_is_counted_once_under_its_own_stage(self):
        # Each of these passed the reviewer check and was then counted as a team question.
        cases = {"Who approves it? Where is the approval recorded?": "several_questions",
                 "Is there anything we have not covered?": "completion_speech",
                 "Is that correct? Your account is complete.": "closing_statement",
                 "The senior reviews the allocation before release.": "no_question_mark"}
        for question, reason in cases.items():
            with self.subTest(question=question):
                result, events = self.reviewed(question)
                self.assertNotEqual(result["question"], question)
                self.assertEqual(result["question"].count("?"), 1)
                self.assertEqual(events, [("question_rejected", {"stage": "review_question", "reason": reason})])


class TypedHTTPTests(unittest.TestCase):
    """The status and body the browser receives from /api/conversation/turn."""

    class Provider(SyntheticTeamProvider):
        fast_question = ""

        def reply(self, path, body, *args, **kwargs):
            if path == "responses" and body["text"]["format"]["name"] == "conversation_question":
                value = {"question": self.fast_question, "request_review": False}
                return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(value)}]}]}
            return super().reply(path, body, *args, **kwargs)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="question-wording-")
        self.client = self.Provider()
        self.client.incomplete()
        # Background capture stays behind the fast question, as it does with a real provider.
        self.release = threading.Event()
        self.client.hooks["team_interview_capture"] = lambda body: self.release.wait(6)
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / "documents")
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temporary.cleanup()

    def turn(self):
        request = Request(f"http://127.0.0.1:{self.httpd.server_port}/api/conversation/turn",
                          data=json.dumps(self.client.payload()).encode(),
                          headers={"Content-Type": "application/json", "X-CSRF-Token": self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=8) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_process_question_with_closing_vocabulary_is_returned(self):
        for question in ("Do you round up or down to the nearest cent when you allocate the call?",
                         "Talk me through how a capital call normally goes."):
            with self.subTest(question=question):
                self.client.fast_question = question
                status, body = self.turn()
                self.assertEqual(status, 200, body)
                self.assertEqual(body["question"], question)
                self.assertEqual(body["speech_authorization"]["text"], question)

    def test_closing_reply_returns_a_question_and_logs_only_a_reason(self):
        self.client.fast_question = "Is there anything else you would like to add before we finish?"
        status, body = self.turn()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["question"], "What happens next in this work?")
        self.assertEqual(body["speech_authorization"]["kind"], "question")
        self.assertNotIn("error", body)
        logged = self.httpd.diagnostics_path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in logged.splitlines()]
        rejected = [record for record in records if record["event"] == "question_rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual((rejected[0]["stage"], rejected[0]["reason"]), ("fast_question", "wrap_up_match"))
        self.assertNotIn("anything else", logged)


if __name__ == "__main__":
    unittest.main()
