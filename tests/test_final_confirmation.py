"""Which replies to the final omissions check confirm it, and which replies add nothing.

A confirmation is a negative without content, however it is hedged or thanked for.
A reply "adds nothing" when it is short and made only of conversational words: it
may be answered without a new review, but it never confirms anything by itself.
Pure wording rules: no provider, no server.
"""
from pathlib import Path
import re
import time
import unittest

from test_server import server

WEB = Path(__file__).resolve().parents[1] / "web"
# The module the coordinator and server.enforce_closure use.
team_module = server.agent_team
CHECK = team_module.FINAL_CHECK_PREFIX + " someone doing this work needs to know that we haven't captured?"


def confirms(answer, question=CHECK):
    ledger = team_module.build_evidence_ledger(
        {"process_name": "Invoice intake"},
        [{"id": "u1", "role": "user", "text": "An analyst registers each invoice."},
         {"id": "a1", "role": "assistant", "text": question},
         {"id": "u2", "role": "user", "text": answer}])
    return team_module.explicit_final_confirmation(ledger)


# The audit's list (server-validation-2 and the reports folded into it).
REPORTED = (
    "No, I think that's everything.", "No, I think that's it.", "I think that's it.", "No, that's it, thanks.",
    "No, nothing.", "Nothing.", "No thanks.", "No, thank you.", "Nope, we're good.", "No, we've covered everything.",
    "No, I don't think so.", "Not that I can think of.", "I don't think so.", "No, that covers all of it.",
    "That's all, thank you.", "No, nothing else. Thanks!", "No, all good.", "Not really.", "That's about it.",
    "That should be everything.", "You've got everything.", "Um, no.", "Uh, no, that's it.", "Yeah, no, that's everything.",
    "No, no, nothing else.", "No - nothing else.", "No... that's it.", "No. Nothing else.")

# Sentences of the same kinds that no report names.
CONFIRMING = (
    "No.", "Nope.", "Nah.", "no", "NO.", "No!", "Nothing else.", "Nothing more.", "Nothing further.",
    "Nothing at all.", "Nothing from me.", "Nothing further from my side.", "Nothing else comes to mind, thanks.",
    "There's nothing else.", "There is nothing more to add.", "I have nothing else.", "I've got nothing else to add.",
    "I can think of nothing else.", "No, I can't think of anything else.", "I cannot think of anything.",
    "That's all.", "That is everything.", "That’s it.", "Thats it.", "That's pretty much it.", "That's basically everything.",
    "That would be all.", "That will be all, thank you.", "I believe that's all for now.", "I guess that's it.",
    "I suppose that is everything.", "That's it, I think.", "That's everything, I believe.", "That's all I have.",
    "That's all I can think of.", "That covers it.", "That about covers it.", "I think that covers everything.",
    "This captures my account.", "No, nothing else. This captures my account.", "We've covered everything.",
    "We covered everything.", "I think we've covered it all.", "You have captured everything.", "You've got it all.",
    "We've been through everything.", "No, I don't believe so.", "I do not think so.", "Don't think so.",
    "I don't think there's anything else.", "No, I don't think we've missed anything.", "I don't think anything is missing.",
    "Not that I'm aware of.", "Not that I know of.", "Not that comes to mind.", "Not right now.", "Not at the moment.",
    "Not from me.", "Not from my side.", "No, not really.", "No, not at all.", "None.", "None that I can think of.",
    "We're good.", "We are all set.", "I'm good.", "I think we're good.", "All good.", "It's all good, thanks.",
    "Correct.", "Okay, no, that's everything.", "Well, no.", "Hmm, no, nothing else.", "Oh, no, that's all.",
    "Right, that's it.", "Alright, nothing else.", "Sorry, no, nothing more.", "No no, that's it.", "No, nope, nothing.",
    "No — that's everything.", "No; nothing else.", "No, thanks.", "No, thank you very much.", "Nope, thanks a lot.",
    "No, that's all, thank you so much.", "No, that's it. Thanks. Bye.", "Nothing else, goodbye.",
    "Nothing else, no.", "That's it from my end.", "Nope. All set.", "No, sorry.", "No, that's all from my side, cheers.",
    "No, I'm fine, thanks.", "I'm happy with that.", "No, we're happy.", "That's all good.",
    "  No,   nothing else.  ", "No nothing else thanks", "no i think thats everything")

# A 'yes', or anything that goes on to say something about the work, confirms nothing.
NOT_CONFIRMING = (
    "No, that covers it. Actually, there is another exception.", "Nothing else, unless the client rejects it.",
    "Yes, that's all.", "Correct, but one route is missing.", "That's it for the approval step.",
    "Yes.", "Yes, that's everything.", "Yeah.", "Yeah, that's it.", "Yep, that's everything.", "Sure, that's all.",
    "No, yes, there is one more thing.", "Yes, no, the bank confirms receipt.",
    "No, but the controller also signs the batch.", "No, I think the controller also signs it.",
    "No, actually there is one more step.", "No... actually, one more thing.", "No, except for year-end.",
    "Nothing changes at quarter end.", "Nothing is released until the controller signs.", "Nothing I can share.",
    "No one checks the register.", "No one else is involved.", "No approval is needed below ten thousand.",
    "Nope, the controller does that.", "None of the invoices are checked twice.", "No invoices are skipped.",
    "That's all handled by treasury.", "That's everything I do on Mondays.", "That's it for the monthly run.",
    "That should be everything for the monthly run; the quarterly run differs.", "That covers the approval step.",
    "That's all I have time for.", "This captures my account of the wire process only.",
    "We've covered everything except the refunds.", "You've got everything but the escalation path.",
    "We've covered the main route.", "I don't think so, but check with treasury.",
    "I don't think the bank confirms receipt.", "I don't think so; the auditors see it too.",
    "Not really, but the bank confirms receipt.", "Not really sure about the approval step.",
    "Not that I can think of, apart from audits.", "Not yet.", "Not sure.", "Not always.", "Not for refunds.",
    "We're good at catching duplicates.", "We're good once the bank confirms.", "All good until quarter end.",
    "No thanks, just add the wire step.", "No, thank you. The refunds go to treasury though.",
    "Sorry.", "Cheers.", "I'm happy with the approval step.", "We're fine once the bank confirms.",
    "No, sorry, the controller signs too.", "That's all good practice.",
    "Thanks.", "Thank you.", "Okay.", "Sounds good.", "Maybe.", "I think so.", "I guess.", "Hmm.", "What do you mean?",
    "Let's finish.", "I'm done.", "That's wrong.", "No, that's wrong.", "No, that's not right.", "", "   ", "?")


class FinalConfirmationWording(unittest.TestCase):
    def test_reported_closing_replies_confirm_the_final_check(self):
        for answer in REPORTED:
            with self.subTest(answer=answer):
                self.assertTrue(confirms(answer))

    def test_neighbouring_negatives_without_content_confirm_the_final_check(self):
        for answer in CONFIRMING:
            with self.subTest(answer=answer):
                self.assertTrue(confirms(answer))

    def test_a_yes_or_any_continuation_with_content_does_not_confirm(self):
        for answer in NOT_CONFIRMING:
            with self.subTest(answer=answer):
                self.assertFalse(confirms(answer))

    def test_every_confirmation_also_counts_as_a_reply_that_adds_nothing(self):
        # The coordinator answers both kinds without a review; a confirmation that the
        # second rule called "content" would start one for the plainest "no".
        for answer in REPORTED + CONFIRMING:
            with self.subTest(answer=answer):
                self.assertTrue(team_module.reply_adds_nothing(answer))

    def test_only_a_reply_to_the_actual_final_check_confirms(self):
        self.assertTrue(confirms("No, I think that's everything."))
        self.assertFalse(confirms("No, I think that's everything.", "Does anyone else approve the batch?"))
        self.assertFalse(confirms("Not that I can think of.", "Is there anything else the bank needs?"))

    def test_the_patterns_stay_fast_on_long_and_awkward_input(self):
        awkward = ["no, " * 3000 + "x", "no " * 3000, "nothing else " * 2000 + "but", "um, " * 4000 + "no",
                   "that's all, " * 2000, "thanks " * 3000 + "controller", "i think " * 3000 + "that's it",
                   "no" + " ," * 4000, "no... " * 3000 + "?", "not that i can think of " * 1500,
                   "No, " + "thank you " * 3000 + "the bank"]
        for text in awkward:
            with self.subTest(length=len(text), start=text[:20]):
                started = time.perf_counter()
                team_module.FINAL_CONFIRMATION.fullmatch(text[:6000])
                team_module.reply_adds_nothing(text[:6000])
                self.assertLess(time.perf_counter() - started, 0.5)


# Replies with nothing in them about the work: a courtesy, a goodbye, an acknowledgement,
# a hesitation, a question back, an announcement that more is coming.
NOTHING_ADDED = (
    "Thank you.", "Thanks.", "Thanks!", "Thank you, bye.", "Bye.", "Bye bye!", "Goodbye.", "Great, thanks.",
    "Okay.", "OK", "Ok, thanks.", "Okay, thank you very much.", "Alright, thanks a lot.", "Perfect, thank you so much.",
    "Sounds good.", "Sounds good, thanks.", "Great.", "Cool, thanks.", "Wonderful, thank you.", "Lovely, cheers.",
    "Thanks for your help.", "Thank you for your time.", "Thanks, that was helpful.", "Thanks, have a good day.",
    "Have a nice evening, bye.", "Take care.", "See you later.", "Talk soon.", "Nice talking to you.", "You too.",
    "You're welcome.", "No problem.", "Understood.", "Got it.", "Right.", "Sure.", "Fine.", "Yes.", "Yeah.", "Yep.",
    "Mm-hmm.", "Uh-huh.", "Hmm.", "Um.", "Maybe.", "I think so.", "I guess so.", "I'm not sure.", "I don't know.",
    "Let me think.", "Give me a second.", "Hold on.", "Wait.", "One moment.", "What do you mean?", "Sorry?",
    "Could you repeat that, please?", "Like what?", "Actually, yes.", "One more thing.",
    "There is something else.", "Yes, there is more.", "I'm done.", "We're done.", "That was it.",
    "No, that's not right.", "That's wrong.", "Oh, okay then.", "Well, I think that is all I have, so thank you.",
    "No, nothing else. This captures my account.", "THANK YOU!", "OK", "", "  ", "...", "?", "👍")

# Anything that names a thing, a person, an action, an amount, a time or a condition of the
# work, in however few words, has content; so does a long reply, whatever it is made of.
CONTENT = (
    "The bank also confirms receipt.", "Treasury signs too.", "Refunds.", "The controller.", "Audits.",
    "Year-end is different.", "She approves it.", "They do.", "He does it again.", "Someone checks it.",
    "It depends.", "It depends on the client.", "Only on Mondays.", "Twice.", "Always.", "Not always.",
    "Sometimes we skip it.", "Every month.", "Before release.", "After the review.", "Unless it is urgent.",
    "It has to be done again.", "We do it twice.", "We send it.", "I approve it.", "We check everything again.",
    "Yes, the wire step.", "Yes, refunds go to treasury.", "No, the controller does that.", "Okay, but refunds differ.",
    "Thanks, and the bank confirms receipt.", "Thank you. One thing: the register is updated on Fridays.",
    "Actually the coordinator never reviews these.", "There is another route.", "One more thing about approvals.",
    "3 days.", "About 40 a month.", "10k.", "SAP.", "Jane.", "The portal.", "Email.", "Invoices.",
    "IT.", "In the US.", "A day later.", "In the morning.", "No, the answer is no.",
    "Nein, danke.", "Merci beaucoup.", "Gracias.",
    "No one checks the register.", "Nothing is released until the controller signs.", "Stop the merge on an error.",
    "I think that you have got it all and I really do not have anything more that I would like to say to you about this now so thank you")


class RepliesThatAddNothing(unittest.TestCase):
    def test_courtesies_acknowledgements_and_hesitations_add_nothing(self):
        for answer in NOTHING_ADDED:
            with self.subTest(answer=answer):
                self.assertTrue(team_module.reply_adds_nothing(answer))

    def test_any_word_about_the_work_is_content(self):
        for answer in CONTENT:
            with self.subTest(answer=answer):
                self.assertFalse(team_module.reply_adds_nothing(answer))

    def test_content_never_confirms(self):
        for answer in CONTENT:
            with self.subTest(answer=answer):
                self.assertFalse(confirms(answer))

    def test_only_text_is_judged(self):
        for value in (None, 7, ["No."], {"text": "No."}):
            with self.subTest(value=value):
                self.assertFalse(team_module.reply_adds_nothing(value))


class TheNothingToAddControl(unittest.TestCase):
    """The page offers the accepted reply as a control; the two must stay in step."""

    def test_the_reply_it_sends_confirms_the_final_check(self):
        source = (WEB / "app.js").read_text(encoding="utf-8")
        replies = re.findall(r'const NOTHING_TO_ADD="([^"]+)";', source)
        self.assertEqual(len(replies), 1, "web/app.js defines the reply of the Nothing to add control once")
        self.assertTrue(confirms(replies[0]), replies[0])
        self.assertIn("sendAnswer(null,NOTHING_TO_ADD)", source)

    def test_the_control_stands_beside_the_closure_line(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        row = re.search(r'<div class="closure-row">(.*?)</div>', page, re.S)
        self.assertIsNotNone(row)
        self.assertIn('id="closure-status"', row.group(1))
        self.assertRegex(row.group(1), r'<button[^>]*id="confirm-nothing"[^>]*hidden>Nothing to add</button>')

    def test_the_repeated_check_tells_both_ways_to_answer_it_and_is_still_the_check(self):
        hint = team_module.FINAL_CHECK_HINT
        self.assertRegex(hint, r"\bno\b")
        self.assertRegex(hint, r"\badd\b")
        repeated = CHECK + " " + hint
        self.assertTrue(confirms("No.", repeated))
        self.assertTrue(confirms("No, nothing to add.", repeated))
        self.assertFalse(confirms("Treasury signs too.", repeated))
        # Like the check itself, it is a line only the application may issue.
        self.assertEqual(server.question_rejection(repeated, 1200), server.question_rejection(CHECK, 1200))


if __name__ == "__main__":
    unittest.main()
