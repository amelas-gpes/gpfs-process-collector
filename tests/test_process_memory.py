"""Source selection, independent of the voice model and of interview completion."""
import unittest
from test_server import server
from test_live_resume import live_payload, exchanges, SDP, history_bytes
from unittest.mock import Mock


def answer(number, text):
    return {"id": f"t{number:03}", "role": "user", "text": text}


class InterviewMemoryTests(unittest.TestCase):
    def test_route_has_priority_and_carries_an_actual_participant_sentence(self):
        turns = [answer(1, "The division director examines complex awards before release."),
                 answer(2, "We usually discuss spreadsheet formatting in chat.")]
        leads = ["Which chat is used for spreadsheet formatting?",
                 "After the division director examines complex awards, where does the file go for release?",
                 "Who authorizes a wire transfer?"]
        result = server.gpfs_interview.question_candidates(turns, leads)
        self.assertEqual([r["gap"] for r in result], [leads[1], leads[0]])
        self.assertEqual(result[0]["source"], "t001")
        self.assertIn(result[0]["quote"], turns[0]["text"])
        self.assertEqual(result, server.gpfs_interview.question_candidates(turns, leads))
        turns += [{"role": "assistant", "id": "t003", "text": leads[1]}, answer(4, "It goes to the client.")]
        self.assertNotIn(leads[1], [r["gap"] for r in server.gpfs_interview.question_candidates(turns, leads)])

    def test_no_question_can_be_grounded_in_the_interviewers_own_assertion(self):
        result = server.gpfs_interview.question_candidates([
            {"role": "assistant", "id": "a", "text": "Does the division director authorize awards?"},
            answer(2, "I do not know.")], ["Where does the division director send awards?"])
        self.assertEqual(result, [])

    def test_resume_uses_original_words_and_a_scoped_recall_tool_within_the_budget(self):
        turns = [answer(0, "The work starts when Treasury receives a signed request."),
                 answer(1, "If the fund suspends payment, the director holds the release."), *exchanges(48)]
        client=server.OpenAIClient({"OPENAI_API_KEY":"sk-test-synthetic"})
        client.request=Mock(return_value={"session":{"id":"test"}, "transport":{"sdp":SDP}})
        payload=live_payload(turns)
        client.live_session({**payload,"interview_memory":True})
        session=client.request.call_args.args[1]["session"]
        note=session["input"][0]["content"][0]["text"]
        self.assertIn("Treasury receives a signed request",note)
        self.assertIn("director holds the release",note)
        self.assertLessEqual(history_bytes(session["input"]),server.LIVE_HISTORY_BYTES)
        self.assertEqual(session["delegation"]["responses"]["tools"][0]["name"],"lookup_interview")
        self.assertFalse(session["store"])
        client.interview_memory_enabled=False
        client.live_session({**payload,"interview_memory":True})
        self.assertEqual(client.request.call_args.args[1]["session"]["delegation"]["responses"]["tools"],[])

    def test_incremental_capture_keeps_all_new_answers_and_expands_for_a_correction(self):
        parts=[answer(i,"We archive the old paper tickets in storage.") for i in range(15)]
        parts[0]=answer(0,"The director approves the signed release.")
        new=[answer(16,"The director approves the signed release after a queue entry arrives."),
             answer(17,"The operator now files the confirmation in the register.")]
        turns=parts+new
        focus=server.capture_facts.turn_focus(turns,parts)
        kept=server.capture_facts.incremental_turns(turns,parts,{"facts":[]},focus)
        self.assertIn(parts[0],kept)
        self.assertEqual(kept[-2:],new)
        self.assertLess(len(kept),len(turns))
        self.assertEqual(server.capture_facts.incremental_turns(turns,parts,{"facts":[]},{"question":"","answer":"Actually the director does not approve the release."}),turns)

if __name__=="__main__":
    unittest.main()
