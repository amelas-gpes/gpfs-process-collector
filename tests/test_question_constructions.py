"""One labelled table for the wording check of a proposed next question, on both paths.

Every sentence that the audit finding, tests/test_question_wording.py and the reviews of
that fix name is listed once with its label: "A" (ask as written) or "R" (replace with a
deterministic question). The typed path (server.question_rejection) and the team path
(Coordinator._question_rejection) must give the same verdict for every row; the only
difference between them is the team path's one-question rule.

Offline: the real server module and the real typed and team paths with scripted replies.
"""
import json
import types
import unittest

from test_question_wording import (CLOSING, CLOSING_STATEMENTS, COMPLETION_CLAIMS, COMPLETION_COLLISIONS, ORDINARY,
                                   ScriptedQuestion, TeamPathTests, concurrent, orchestrator, server, typed_payload)

# Follow-up r1-closing-1: a restated answer or an acknowledgement before the question.
RESTATED = (
    "So the transfer agent closes the window at noon. Who handles late subscriptions?",
    "So that closes the call. Who reconciles the receipts afterwards?",
    "Got it, so this call is closed once the funds arrive. Who confirms receipt?",
    "So once the accruals are in, you are ready to close. Who signs off the close?",
    "So once it's posted you're done. Who reviews the posting?",
    "So the interview is complete before the file goes to compliance. What does compliance check?",
    "Let me check my notes. Yes, you said the administrator sends it. Who reviews it?",
    "Let me know if you'd like to come back to that. Who approves it?",
    "So all the sections are complete before the pack goes out. Who releases it?",
    "So you go ahead and submit it. Who receives the submission?",
    "That covers it. Who approves the notice?",
    # Named in the lane's reports as still refused on one path or on both.
    "You are done with that part of the reconciliation at that point. Who signs it off?",
    "So there is nothing more to add to the pack. Who sends it?",
    "When you are done, who do you tell?",
    "How do you tell your manager you are finished?",
    "What tells you the documentation is complete?",
    "How do you decide the account is ready?",
    "Explain how you review the draft notice before it is sent.",
    # Neighbours of the same constructions.
    "So the custodian ends the call once the trade is matched. Who books it?",
    "Understood, the account is ready for the auditor at that stage. Who hands it over?",
    "Right, so the notes are final once the partner signs. Who files them?",
    "So when the batch is posted, you are finished for the day. Who picks it up the next morning?",
    "Okay, so the summary is complete by Friday. Who receives it?",
    "The senior confirms the documentation is complete. Who files it?",
    "So you said the account is ready at that point. Who releases the payment?",
    "Got it, you are all set once the bank confirms. What happens if the bank does not confirm?",
    "So we are finished with intake before the allocation starts. Who starts the allocation?",
    "How do you tell the client we're done with the onboarding?",
    "I have everything I need on the approval step. What happens after the wire is released?",
    "That's all I need on the timing. Who signs the notice?",
    "The wire lands, which closes the call. Who reconciles the receipts afterwards?",
    "At that point, the account is ready. Who releases the payment?",
    "By then, you're done. Who reviews the posting?",
    "At month end the account is ready. Who signs it off?",
    "So by then we are finished with the allocation. Who checks it?",
    "So you're done with the reconciliation by noon. Can I ask who reviews it?",
    "So the account is ready, and then the wire goes out. Who releases the wire?",
    "Great, so you're all set for month end. What happens in the first week?",
    "Describe how you know you are done.",
    "So the draft is ready at that point. Would you say the senior always reviews it?",
)

# The same words with the interview, the interviewer or the participant's assent as their object.
RESTATED_CLOSINGS = (
    "So that completes our session. Who should receive the memo?",
    "That closes the call. Would you like to review the notes?",
    "So we're done. Who reviews the posting?",
    "You're done. Who reviews the posting?",
    "So once you confirm, you're done. Do you confirm?",
    "Let me draft it. Who should receive it?",
    "Go ahead and submit it. Who receives the submission?",
    "That covers everything. Who approves the notice?",
    "So the documentation is complete. Shall I draft it?",
    "So the account is complete. Would you like to review it?",
    "Yes, the account is complete. Who should get a copy?",
    "The draft is ready. Who reviews it?",
    "So your account is complete. What happens next?",
    "I have everything I need. What happens after the wire is released?",
    "That's all I need. Who signs the notice?",
    "We are done with the questions. Shall I draft the memo?",
    "Got it, so we're done?",
    "Are we all done?",
    "Do you agree that we're done?",
    "So you're all set?",
    "This gives me a complete view of how the work runs. Shall we finish?",
    "Once you confirm, the account is complete. Do you confirm?",
    "At this point the account is complete. Would you like to review it?",
    "At this point we're done. Is that all right?",
    "Right now the account is complete. Would you like to see it?",
    "Now that I know who approves it, we're done. Is that okay?",
    "Thanks, we are finished here. What would you like to do with the notes?",
    "So you're done. Can I ask how it felt?",
    "The summary is ready. Would you like to read it?",
    "We've reached the end. How did that feel?",
    "I have no more questions. Is there something you want to ask me?",
    "Shall we wrap things up?",
    "Should we wrap this up here?",
)

# Follow-up r1-closing-2: a reply whose only request hands the next move to the participant.
DEFERRALS = (
    "Tell me when you would like to continue.",
    "Tell me if you need a break.",
    "Tell me when you need to stop the interview.",
    "Tell me if you need a quick minute.",
    "Tell me when you have read the draft.",
    "Tell me whenever you want to look at the draft.",
    "Tell me if you have nothing to add.",
    "Tell me when you feel we have enough.",
    "Tell me when you are ready.",
    "Tell me once the file arrives.",
    "Tell me if you would like me to slow down.",
    "Thanks. Tell me when you've had a chance to look.",
    "Tell me if anything comes to mind.",
    "Tell me about it another time.",
    "We can pick this up another time.",
)

# A request of the same shape that asks about the work.
INDIRECT_QUESTIONS = (
    "Tell me when you usually reconcile the cash account.",
    "Tell me if the senior reviews every allocation.",
    "Tell me when the bank file normally arrives.",
    "Tell me if you reconcile the account daily or weekly.",
    "Tell me whether you need a second approval for large wires.",
    "Tell me if you need a second approval for large wires.",
    "Tell me when you need to stop posting entries.",
    "Tell me if you need more time to reconcile the account.",
    "Can we wrap things up in a different file at month end?",
    "Tell me when you have to escalate a break to the manager.",
    "Tell me if you are reconciling against the custodian or the bank.",
    "Tell me what you do when you are ready to post.",
)

# Follow-up r1-closing-3: spoken requests that use closing words about the work.
REQUESTS = (
    "Tell me about another time a file arrived late.",
    "Describe another time the wire was rejected.",
    "So the draft is ready. Describe who reviews it.",
    "Right, so the draft is final. Walk me through the sign-off.",
    "Describe what happens when the auditor has no further questions.",
    "Tell me how you want the draft notice formatted.",
    "Describe a time the reconciliation was finished late.",
    "Walk me through what happens when the documentation is complete.",
    "So the summary is ready by Friday. Describe who receives it.",
    "You can come back to that. Describe what the reviewer checks first.",
    "Explain what the client does when they have nothing further to add to the subscription form.",
)

REQUEST_CLOSINGS = (
    "The memo is ready. Describe how you want it sent.",
    "I have no further questions. Tell me how it went.",
    "No further questions. Describe your day.",
    "Nothing further. Describe your day.",
    "That is my last question. Tell me how it went.",
)

# Follow-up r1-closing-4: questions about the work that the team path's completion check refused.
WORK_QUESTIONS = (
    "Do you check that the documentation is complete before release?",
    "So the documentation is complete before the audit starts. Who assembles it?",
    "Understood, the documentation is ready for the auditor. Who hands it over?",
    "So you are finished with the first pass. Who does the second?",
    "Is there anything not covered in the side letter record?",
    "Does the senior confirm the account is ready before the wire goes out?",
    "Is there anything not covered in the engagement letter?",
    "What is not mentioned in the fund's offering record?",
    "Do you sign off once you are finished with the first pass?",
    "What happens when the auditor has no further questions?",
    "Is the checklist signed when all sections are complete?",
    "What happens to trades the custodian has not yet covered?",
    "What do you do when a claim is not covered?",
    "Do you tell the client when the account is ready?",
    "Once the documentation is complete, where is it stored?",
    "Who tells you that the documentation is complete?",
)

WORK_QUESTION_CLOSINGS = (
    "Is there anything not covered in the record so far?",
    "Is there anything not covered in the interview notes?",
    "Is there anything you have not mentioned?",
    "Would you say we're done?",
    "Do we have everything we need?",
    "Is there anything in this process not yet covered?",
    "What do you think is not yet covered?",
    "Is there anything about the process that we have not covered?",
)

# Named in the reports as closure by design: the construction has no object, so it is
# decided by cost (a replaced question costs a turn; a spoken closing ends the interview).
DOUBTFUL_REPLACED = (
    "What do you check before we finish?",
    "What must be signed before we finish?",
    "How do you know you have enough to finish?",
    "Go on.",
    "Please continue.",
    "Who approves it? Thanks.",
)

# The team path keeps one question per turn; the typed path does not.
ONE_QUESTION = ("Who approves it? Where is the approval recorded?",)

# Rows whose label the shared check does not meet. They are reported, not asserted: each
# belongs to WRAP_UP_LANGUAGE (unchanged here) or to wording no rule names.
OPEN = (
    ("Does the reviewer check anything else?", "A"),
    ("What do you do to wrap up for the day?", "A"),
    ("When the client says thanks for your time, is the query closed?", "A"),
    ("Is there something more you would like to add before we close?", "R"),
    ("What else should we add?", "R"),
    ("To round up, have we got everything?", "R"),
    ("Let me round up what we have. Does that sound complete?", "R"),
    ("Is there anything else that you think matters?", "R"),
    ("Is there anything else I need to understand about how this works?", "R"),
    ("That gives me a complete account from start to finish. Shall I draft?", "R"),
    ("Good. Show me out.", "R"),
    ("Please tell me that this is the whole process.", "R"),
    ("This concludes our time. Tell me how you found it.", "R"),
)

TABLE = tuple(
    [(text, "A", "A", source) for source, rows in (
        ("tests ORDINARY", ORDINARY), ("tests COMPLETION_COLLISIONS", COMPLETION_COLLISIONS),
        ("r1-closing-1", RESTATED), ("r1-closing-2 neighbours", INDIRECT_QUESTIONS),
        ("r1-closing-3", REQUESTS), ("r1-closing-4", WORK_QUESTIONS)) for text in rows] +
    [(text, "R", "R", source) for source, rows in (
        ("tests CLOSING", CLOSING), ("tests CLOSING_STATEMENTS", CLOSING_STATEMENTS),
        ("tests COMPLETION_CLAIMS", COMPLETION_CLAIMS), ("r1-closing-1 neighbours", RESTATED_CLOSINGS),
        ("r1-closing-2", DEFERRALS), ("r1-closing-3 neighbours", REQUEST_CLOSINGS),
        ("r1-closing-4 neighbours", WORK_QUESTION_CLOSINGS), ("reports, decided by cost", DOUBTFUL_REPLACED)) for text in rows] +
    [(text, "A", "R", "one question per turn") for text in ONE_QUESTION])

# First batch: sixty-four sentences written after the rules were first frozen and evaluated
# once: sixty-one got their label on both paths. A comparison with the earlier code on a
# generated corpus then changed two rules, and "you'd rather" (one of the three misses)
# joined the wishes of a deferral, so this batch is no longer held out. The two misses that
# remain are in HELD_OUT_MISSED.
FIRST_BATCH = tuple([(text, "A") for text in (
    "So the subscription is closed once the transfer agent confirms. Who updates the register?",
    "Got it, so the reconciliation is finished by ten. What happens to the breaks you could not clear?",
    "Understood, the checklist is complete before the manager signs. Where is the signed copy kept?",
    "So the notes are ready for the partner on Thursday. Who presents them?",
    "Right, so the memo is final when legal approves it. Who sends it to the investors?",
    "So the session in the portal ends after fifteen minutes. What do you do if you are logged out mid-entry?",
    "Tell me when the custodian usually sends the holdings file.",
    "Tell me if the administrator ever rejects a subscription.",
    "Tell me when you post the accrual and who reviews it.",
    "Describe what the controller checks once the close is finished.",
    "Walk me through another case where the notice had to be reissued.",
    "Explain how you decide the pack is complete.",
    "Does the reviewer check that the summary is complete before it goes to the client?",
    "How does the team know when the documentation is ready for the regulator?",
    "Is there anything not covered in the investor's side letter?",
    "What happens if the draft is ready but the senior is away?",
    "So you are done with the first review at that point. Who performs the second review?",
    "So you wrap up the reconciliation, and then the file is locked. Who can unlock it?",
    "Okay, so that ends the call with the client. Who writes up the call note?",
    "I have what I need about the wire limits. How are exceptions approved?",
    "That answers my question about timing. Who owns the calendar?",
    "So when everything is ready, the senior releases the batch. How long does the release take?",
    "You said the account is complete after the second sign-off. Who gives the second sign-off?",
    "Could you tell me who decides that the reconciliation is finished?",
    "Do you ever stop the allocation once it has started?",
    "What do you do if the client says they have nothing further to provide?",
    "So before you finish for the day, the batch has to be approved. Who approves it?",
    "Thanks, that is clear. Which system do you use to book the trade?",
    "Describe what you check when the auditor says the file is complete.",
    "Got it. Tell me what happens if nobody is ready to sign.",
    "So the investor is told that the call is closed. Who tells them?",
    "Is the account reconciled before you are finished, or afterwards?",
)] + [(text, "R") for text in (
    "Thanks, I think that's everything. Shall I write it up?",
    "Wonderful, we're all done here. Do you have any questions for me?",
    "I have all I need from you. Would you like to see the notes?",
    "Your account is now complete. Is there a colleague who should review it?",
    "This conversation is finished. What would you like to do next?",
    "Okay, I'm finished with my questions. Shall we stop?",
    "That is everything for today. Who else should I speak to?",
    "The memo is ready. Shall I show it to you?",
    "I will draft the memo now. Is there a deadline?",
    "Let me write this up. Who should receive a copy?",
    "You can open the draft whenever you are ready. Does that work?",
    "Feel free to stop here. Would that suit you?",
    "Tell me when you want to pick this up again.",
    "Tell me if you'd rather continue tomorrow.",
    "Let me know once you have had a look. Thanks.",
    "Tell me whenever something else occurs to you.",
    "What have we not covered yet?",
    "So we're finished?",
    "And you're all set now?",
    "Are we done for today?",
    "Would you like to stop here?",
    "Before we conclude, tell me about the exceptions.",
    "Who approves it? Then we can finish.",
    "Okay, the notes are complete. Do you want to read them?",
    "Great, everything is captured. Would you like a summary?",
    "That wraps things up. Who should I send the memo to?",
    "No more questions from me. How did you find it?",
    "You are finished. Could you tell me who else to interview?",
    "The interview is over. What happens to my notes?",
    "Goodbye for now. When shall we speak again?",
)])
# Held out: fifty-two sentences written after the rules were final and evaluated once; the
# rules were not changed afterwards. Fifty-one got their label on both paths and are asserted
# here; the one that did not is the last row of HELD_OUT_MISSED.
HELD_OUT = tuple([(text, "A") for text in (
    "Got it, so the payroll run is finished by Wednesday. Who approves it before it is released?",
    "So the file is ready for the bank at four. What happens if the bank rejects it?",
    "Understood, the draft is ready on day two. Who checks the figures in it?",
    "So the account is closed once the final distribution is paid. Who confirms the zero balance?",
    "Right, so you are finished once the batch posts. What tells you that it has posted?",
    "So the summary is ready, and then it goes to the board. Who presents it there?",
    "Okay, so the meeting ends when the committee has voted. Who records the vote?",
    "Tell me if the system lets you post without a second approval.",
    "Tell me when the valuation agent delivers the prices and what you do with them.",
    "Describe what happens after the investor says they have nothing more to send.",
    "Explain how the team decides that the documentation is ready for the regulator.",
    "Walk me through the day the reconciliation was not done on time.",
    "Could you describe what you do when the notes to the accounts are complete?",
    "Does anyone check that all sections are covered before the report is filed?",
    "How do you know the memo is ready to go to the credit committee?",
    "Is there anything not mentioned in the subscription agreement that you still have to collect?",
    "What do you do once you have everything you need from the transfer agent?",
    "When the interview with the client is finished, where do you store the recording?",
    "So at that stage you are all set to release the payment. Who releases it?",
    "You mentioned that the checklist is complete before sign-off. Who signs?",
    "That is clear on the trigger, thank you. What is the very first thing you do when the request arrives?",
    "I have enough detail on the approval. How do you record that the approval was given?",
    "So once the administrator has signed, the notes are final. Who distributes them?",
    "Do you close the period before or after the accruals are posted?",
    "Who decides that we are done chasing a missing statement?",
    "So the conversation with the custodian is over at that point. Who logs the outcome?",
)] + [(text, "R") for text in (
    "Excellent, I have everything I need now. Is there a good time to follow up?",
    "We are all finished. Do you want me to send you the summary?",
    "Okay, we're done for today. Is there anything you would like to ask me?",
    "Your account is complete, thank you. What would you like to do next?",
    "I'm going to draft the memo now. Is that okay with you?",
    "Let me go ahead and write it up. Shall I send it to you first?",
    "Go ahead and review the draft when you have a moment. Does Friday work?",
    "You may now create the draft. Would you like me to stay on the line?",
    "Tell me when you're back at your desk.",
    "Tell me if you feel like taking a break.",
    "Just tell me once you've finished reading.",
    "Thanks for all of this. Tell me later if you remember anything.",
    "So this interview is finished?",
    "And we're done now?",
    "Is there anything we have not yet discussed?",
    "Have we missed anything?",
    "Shall we end the session here?",
    "Who signs it off? That's everything from me.",
    "Who signs it off? Bye for now.",
    "The notes are final. Would you like to read them through?",
    "All sixteen sections are captured. Is that what you expected?",
    "That concludes my questions. Is there anything you want to add?",
    "I think we're finished with the interview. How was that for you?",
    "So I have the full picture. Can I ask who else I should speak to?",
    "Everything is documented now. Do you agree?",
)])
# Reported, not asserted: an omission verb and a "covered it all" outside the word classes the
# rules use (first batch), and a sufficiency claim with "that" as its subject (held-out batch).
HELD_OUT_MISSED = (
    ("Is there anything we haven't talked about?", "R"),
    ("I think we have covered it all. Is that fair?", "R"),
    ("Thank you, that gives me everything I need. Would you like to look over the notes?", "R"),
)

REASONS = {"wrap_up_match", "closing_statement", "completion_speech", "no_question_mark", "several_questions"}


def typed_reason(text):
    return server.question_rejection(text, 1200)


def team_reason(text):
    return orchestrator.Coordinator._question_rejection(types.SimpleNamespace(api=server), text)


def verdicts(text):
    return ("R" if typed_reason(text) else "A"), ("R" if team_reason(text) else "A")


class LabelledTableTests(unittest.TestCase):
    def test_every_row_is_listed_once(self):
        texts = [row[0] for row in TABLE + OPEN + FIRST_BATCH + HELD_OUT + HELD_OUT_MISSED]
        repeated = sorted({text for text in texts if texts.count(text) > 1} -
                          # The lane's own lists share these sentences on purpose.
                          (set(CLOSING_STATEMENTS) & set(COMPLETION_CLAIMS)))
        self.assertEqual(repeated, [])

    def test_each_row_gets_its_label_on_both_paths(self):
        for text, typed, team, source in TABLE:
            with self.subTest(source=source, text=text):
                self.assertEqual(verdicts(text), (typed, team))

    def test_held_out_sentences_get_their_label_on_both_paths(self):
        self.assertGreaterEqual(len(HELD_OUT), 40)
        for text, label in FIRST_BATCH + HELD_OUT:
            with self.subTest(text=text):
                self.assertEqual(verdicts(text), (label, label))

    def test_both_paths_share_one_check(self):
        # The Coordinator has no wording pattern of its own: it differs only by one question per turn.
        self.assertFalse(hasattr(orchestrator, "_COMPLETION_SPEECH"))
        others = OPEN + FIRST_BATCH + HELD_OUT + HELD_OUT_MISSED
        for text, _, _, source in TABLE + tuple((text, label, label, "other") for text, label in others):
            with self.subTest(source=source, text=text):
                typed, team = typed_reason(text), team_reason(text)
                if text in ONE_QUESTION:
                    self.assertEqual((typed, team), ("", "several_questions"))
                else:
                    self.assertEqual(typed, team)
                self.assertIn(typed or "wrap_up_match", REASONS)

    def test_open_rows_are_replaced_or_asked_without_error(self):
        for text, _ in OPEN + HELD_OUT_MISSED:
            with self.subTest(text=text):
                self.assertIn(typed_reason(text), REASONS | {""})

    def test_reason_code_names_the_construction(self):
        cases = {"Tell me when you would like to continue.": "closing_statement",
                 "Tell me if you need a break.": "closing_statement",
                 "So we're done. Who reviews the posting?": "closing_statement",
                 "The memo is ready. Describe how you want it sent.": "closing_statement",
                 "Is there anything we have not covered?": "completion_speech",
                 "Got it, so we're done?": "completion_speech",
                 "Are we all done?": "completion_speech",
                 "Would you say we're done?": "completion_speech",
                 "Go on.": "no_question_mark",
                 "Is there anything else you would like to add?": "wrap_up_match"}
        for text, reason in cases.items():
            with self.subTest(text=text):
                self.assertEqual(typed_reason(text), reason)
                self.assertEqual(team_reason(text), reason)


class FollowUpPathTests(unittest.TestCase):
    """The follow-up sentences through the real typed turn and the real Coordinator."""

    ASKED = RESTATED + INDIRECT_QUESTIONS + REQUESTS + WORK_QUESTIONS
    REPLACED = RESTATED_CLOSINGS + DEFERRALS + REQUEST_CLOSINGS + WORK_QUESTION_CLOSINGS

    def typed(self, reply):
        client = ScriptedQuestion(reply)
        service = concurrent.ConcurrentInterview(client, server)
        self.addCleanup(service.close)
        return service.turn(typed_payload()), [event for event in client.events if event[0] == "question_rejected"]

    def test_typed_turn_asks_the_work_question_as_written(self):
        for reply in self.ASKED:
            with self.subTest(reply=reply):
                result, rejected = self.typed(reply)
                self.assertEqual(result["question"], reply)
                self.assertEqual(result["speech_authorization"]["text"], reply)
                self.assertEqual(rejected, [])

    def test_typed_turn_replaces_the_closing_or_deferring_reply(self):
        for reply in self.REPLACED:
            with self.subTest(reply=reply):
                result, rejected = self.typed(reply)
                self.assertEqual(result["question"], "What happens next in this work?")
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual([event[1]["stage"] for event in rejected], ["fast_question"])
                self.assertIn(rejected[0][1]["reason"], REASONS)
                self.assertNotIn(reply, json.dumps(rejected))

    def test_coordinator_asks_the_work_question_as_written(self):
        lead = TeamPathTests.lead
        for question in self.ASKED:
            with self.subTest(question=question):
                result, events = lead(self, question)
                self.assertEqual(result["question"], question)
                self.assertEqual(result["speech_authorization"]["kind"], "question")
                self.assertEqual(events, [])

    def test_coordinator_replaces_the_closing_or_deferring_reply(self):
        lead = TeamPathTests.lead
        for question in self.REPLACED:
            with self.subTest(question=question):
                result, events = lead(self, question)
                self.assertNotEqual(result["question"], question)
                self.assertEqual(result["question"].count("?"), 1)
                self.assertFalse(result["completion"]["complete"])
                self.assertEqual([event[1]["stage"] for event in events], ["team_question"])
                self.assertIn(events[0][1]["reason"], REASONS)


if __name__ == "__main__":
    unittest.main()
