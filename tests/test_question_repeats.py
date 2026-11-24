"""What keeps the next question from repeating: skipped questions and supplied files.

Found in the 2026-11-17 final stress run with the real provider. A participant pressed Skip on
"What event normally prompts the preparer to start this work?"; two answers later the interviewer
asked "What event usually prompts the preparer to begin this work?". Skip adds no turn, so the
question model was never told. And after a complete written procedure was uploaded, five of six
questions asked the participant to explain a step the file states. No provider here.
"""
import types
import unittest

from test_server import server

concurrent_interview = server.concurrent_interview


def turns_with_a_skip():
    return [
        {"id": "t1", "role": "assistant", "text": "What starts this work?"},
        {"id": "t2", "role": "user", "text": "The preparer confirms the trigger and the approved model."},
        {"id": "t3", "role": "assistant", "text": "What event normally prompts the preparer to start this work?"},
        {"id": "t4", "role": "assistant", "text": "What result is the waterfall work intended to produce?"},
        {"id": "t5", "role": "user", "text": "I'm not sure. The Controller would be the person to ask."},
        {"id": "t6", "role": "assistant", "text": "Which entities does this work cover?"},
    ]


class SkippedQuestionTests(unittest.TestCase):
    def service(self):
        api = types.SimpleNamespace(interview_coverage=server.interview_coverage, question_rejection=server.question_rejection)
        service = concurrent_interview.ConcurrentInterview(types.SimpleNamespace(coordinator=types.SimpleNamespace()), api)
        self.addCleanup(service.close)
        return service

    def test_a_question_followed_by_another_question_was_skipped(self):
        found = self.service()._skipped_questions(turns_with_a_skip())
        self.assertEqual([row["turn_id"] for row in found], ["t3"])
        self.assertEqual(found[0]["question"], "What event normally prompts the preparer to start this work?")

    def test_the_question_being_skipped_now_is_listed_first(self):
        service = self.service()
        self.assertEqual([row["turn_id"] for row in service._skipped_questions(turns_with_a_skip(), "skip")], ["t6", "t3"])
        # An answered question is never listed, and an unanswered last question is only pending.
        self.assertEqual(service._skipped_questions(turns_with_a_skip()[:2]), [])
        self.assertEqual(service._skipped_questions(turns_with_a_skip()[:3]), [])

    FILE_TURNS = [
        {"id": "t1", "role": "assistant", "text": "What can go wrong if this is late?"},
        {"id": "t2", "role": "assistant", "text": "Thanks for sharing. Give me a moment to digest the file.", "document_event": True},
        {"id": "t3", "role": "assistant", "text": "The file lists three checks. Is that how it is done today?"},
        {"id": "t4", "role": "user", "text": "Yes."},
    ]

    def test_a_file_notice_between_two_questions_is_not_a_skip(self):
        self.assertEqual(self.service()._skipped_questions(self.FILE_TURNS), [])

    def test_the_question_open_when_a_file_was_added_is_not_banned_after_validation(self):
        # Validation drops file notices before the question model's input is built, so the
        # displaced question and the file's question arrive side by side. The page's own turns
        # still carry the notice, and those are the ones read.
        service = self.service()
        payload = {"context": {"process_name": "Billing", "objective": "Document billing."},
                   "turns": [dict(turn) for turn in self.FILE_TURNS], "action": "answer"}
        context, validated = server.validate_payload(payload)
        self.assertEqual([turn["id"] for turn in validated], ["t1", "t3", "t4"], "The notice is gone after validation")
        session = {"capture": None, "capture_basis": None, "workflow_capture": None, "workflow_turns": None}
        self.assertEqual(service._question_input(session, payload, context, validated)["skipped_questions"], [])
        # A question a participant picked from a file in Assets carries the file's id and no notice.
        picked = [dict(self.FILE_TURNS[0]), {"id": "t2", "role": "assistant", "text": "From returns.csv: who signs the log?", "document_id": "doc_1"}]
        self.assertEqual(service._skipped_questions(picked), [])

    def test_a_wrap_up_reply_or_an_acknowledgement_is_neither_skipped_nor_a_skip(self):
        service = self.service()
        turns = [
            {"id": "t1", "role": "assistant", "text": "Who approves the invoice?"},
            {"id": "t2", "role": "assistant", "text": "Your account so far is captured. 2 of 16 topics are complete and 14 are partly covered; the Notes list shows what is missing. You can create a draft from what is here, or keep answering."},
            {"id": "t3", "role": "assistant", "text": "Let me check that I have everything before we finish."},
            {"id": "t4", "role": "assistant", "text": "Before we finish, is there anything else needed to understand this process?"},
            {"id": "t5", "role": "user", "text": "One more thing: the analyst files the approval email."},
        ]
        self.assertEqual(service._skipped_questions(turns), [], "The question open at Wrap up may be asked again")
        # Two interviewer lines in a row where the second is not a question (a voice caption).
        captions = [{"id": "c1", "role": "assistant", "text": "What starts this work?"},
                    {"id": "c2", "role": "assistant", "text": "Take your time."},
                    {"id": "c3", "role": "user", "text": "A request form."}]
        self.assertEqual(service._skipped_questions(captions), [])
        # Malformed entries are ignored.
        self.assertEqual(service._skipped_questions(["x", None, {"role": "assistant"}], "skip"), [])

    def test_only_the_most_recent_skips_are_listed_and_long_questions_are_cut(self):
        turns = []
        for index in range(12):
            turns.append({"id": f"q{index}", "role": "assistant",
                          "text": f"For case {index}, " + "and the related ledger entry, " * 12 + "what happens next?"})
        found = self.service()._skipped_questions(turns)
        self.assertEqual(len(found), concurrent_interview.MAX_SKIPPED_QUESTIONS)
        self.assertEqual(found[0]["turn_id"], "q10")
        self.assertTrue(all(len(row["question"]) <= 300 for row in found))

    def test_the_question_model_is_given_the_skipped_questions_and_told_not_to_repeat_them(self):
        service = self.service()
        session = {"capture": None, "capture_basis": None, "workflow_capture": None, "workflow_turns": None}
        turns = turns_with_a_skip()
        model_input = service._question_input(session, {"turns": turns, "action": "answer"}, {"process_name": "Waterfall"}, turns)
        self.assertEqual([row["turn_id"] for row in model_input["skipped_questions"]], ["t3"])
        policy = concurrent_interview.question_policy(server)
        for wording in ("skipped_questions lists, newest first", "Never ask one of them again"):
            self.assertIn(wording, policy)


class SuppliedFileQuestionTests(unittest.TestCase):
    def test_the_fast_question_policy_forbids_reciting_a_supplied_file(self):
        # BASE_INSTRUCTIONS already told reviewed turns never to ask for a retelling of a supplied
        # file; the fast question policy, which asks most questions, did not carry the rule.
        self.assertIn("Never ask the person to retell", server.BASE_INSTRUCTIONS)
        for followup in (False, True):
            policy = concurrent_interview.question_policy(server, followup)
            for wording in ("Never ask them to\ndescribe or explain a step, check, role or rule that a supplied excerpt already states",
                            "do not\nwalk through a written procedure one step per question",
                            "Ask once, at most, whether the written\nprocedure is what happens today"):
                self.assertIn(wording, policy)


class QuestionLeadTests(unittest.TestCase):
    def test_the_question_model_is_shown_both_ends_of_a_long_register(self):
        # The reviewer's questions come first and the generated routing questions last (see
        # test_open_question_order.py). The first twelve alone would never reach the routing ones.
        owner = [f"Owner question {index}?" for index in range(18)]
        routing = [f"Does any incoming route start S{index} (Step), or must all prerequisites finish?" for index in range(6)]
        leads = concurrent_interview.ConcurrentInterview._question_leads(owner + routing)
        self.assertEqual(leads, owner[:8] + routing[-4:])
        self.assertEqual(len(leads), 12)
        short = owner[:5] + routing[:2]
        self.assertEqual(concurrent_interview.ConcurrentInterview._question_leads(short), short)
        self.assertEqual(concurrent_interview.ConcurrentInterview._question_leads(owner[:12]), owner[:12])
        self.assertEqual(concurrent_interview.ConcurrentInterview._question_leads(None), [])


class CutOffQuestionTests(unittest.TestCase):
    """A question reply that reaches its output allowance never fails the participant's turn.

    On 2026-11-17 a question about an uploaded procedure spent its whole 600-token allowance on
    reasoning; the turn returned HTTP 502 although the answer had been retained.
    """
    TURNS = [{"id": "t1", "role": "assistant", "text": "What starts this work?"},
             {"id": "t2", "role": "user", "text": "A payment request starts it and the preparer logs it."}]

    def service(self, replies):
        allowances = []

        def structured(instructions, data, schema, name, allowance, **options):
            allowances.append(allowance)
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        client = types.SimpleNamespace(agent_models={"lead_interviewer": "offline-model"}, structured=structured,
                                       coordinator=types.SimpleNamespace(interview=lambda value: {"question": "unused"},
                                                                         workflow=lambda value: {"workflow": {"steps": []}}))
        api = types.SimpleNamespace(
            APIError=server.APIError, OutputTruncated=server.OutputTruncated, interview_coverage=server.interview_coverage,
            check_schema=server.check_schema, question_rejection=server.question_rejection,
            record_question_rejection=server.record_question_rejection, next_uncovered_question=server.next_uncovered_question,
            participant_requested_stop=lambda turns, action="answer": False,
            document_reading_summary=server.document_reading_summary, validate_payload=lambda value: (value["context"], value["turns"]))
        service = concurrent_interview.ConcurrentInterview(client, api)
        self.addCleanup(service.close)
        return service, allowances

    def turn(self, service):
        return service.turn({"context": {"process_name": "Payments"}, "turns": [dict(turn) for turn in self.TURNS],
                             "_supporting_documents": {}, "action": "answer"})

    def test_the_allowance_leaves_room_for_reasoning(self):
        self.assertGreaterEqual(concurrent_interview.QUESTION_OUTPUT_TOKENS, 1000)
        self.assertGreater(concurrent_interview.QUESTION_RETRY_OUTPUT_TOKENS, concurrent_interview.QUESTION_OUTPUT_TOKENS)
        service, allowances = self.service([{"need": "who releases", "question": "Who releases the payment?", "request_review": False}])
        self.assertEqual(self.turn(service)["question"], "Who releases the payment?")
        self.assertEqual(allowances, [concurrent_interview.QUESTION_OUTPUT_TOKENS])

    def test_a_cut_off_reply_is_asked_once_more_with_more_room(self):
        service, allowances = self.service([server.OutputTruncated("cut off"),
                                            {"need": "who releases", "question": "Who releases the payment?", "request_review": False}])
        self.assertEqual(self.turn(service)["question"], "Who releases the payment?")
        self.assertEqual(allowances, [concurrent_interview.QUESTION_OUTPUT_TOKENS, concurrent_interview.QUESTION_RETRY_OUTPUT_TOKENS])

    def test_a_reply_cut_off_twice_still_asks_a_question(self):
        service, allowances = self.service([server.OutputTruncated("cut off"), server.OutputTruncated("cut off again")])
        result = self.turn(service)
        self.assertEqual(len(allowances), 2)
        self.assertTrue(result["question"].endswith("?"))
        self.assertNotEqual(result["question"], "What starts this work?", "Never the question just asked")
        self.assertFalse(result["sync_required"])

    def test_any_other_provider_failure_is_still_reported(self):
        service, allowances = self.service([server.APIError("The AI service is unavailable.", 503)])
        with self.assertRaises(server.APIError):
            self.turn(service)
        self.assertEqual(len(allowances), 1)


class SameQuestionTwiceTests(CutOffQuestionTests):
    """The model's question is replaced when it is the previous question again, word for word.

    Seen in the browser on 2026-11-18: the participant answered Question 3 with other facts and
    Question 4 was Question 3, character for character.
    """
    def test_the_same_question_again_is_replaced_and_a_new_one_passes(self):
        service, _ = self.service([{"need": "start", "question": "What starts this work?", "request_review": False}])
        replaced = self.turn(service)["question"]
        self.assertNotEqual(replaced, "What starts this work?")
        self.assertTrue(replaced.endswith("?"))
        service, _ = self.service([{"need": "who releases", "question": "Who releases the payment?", "request_review": False}])
        self.assertEqual(self.turn(service)["question"], "Who releases the payment?")

    def test_a_second_request_joined_on_is_left_out_of_the_turn(self):
        service, _ = self.service([{"need": "release", "question": "Who releases the payment, and how is the bank told?",
                                    "request_review": False}])
        service.api.one_request = server.one_request
        self.assertEqual(self.turn(service)["question"], "Who releases the payment?")


if __name__ == "__main__":
    unittest.main()
