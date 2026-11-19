"""Source selection, independent of the voice model and of interview completion."""
import unittest
from test_server import server
from test_live_resume import live_payload, exchanges, SDP, history_bytes
from unittest.mock import Mock
from test_server import interview_payload


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
        self.assertEqual(server.gpfs_interview.question_candidates([
            answer(1, "I do not know which director releases the authorization.")],
            ["Which director releases the authorization?"]), [])

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

    def test_fast_capture_keeps_qualifiers_and_never_promotes_a_topic_to_complete(self):
        state=server.capture_facts.empty_state()
        source=answer(1,"Only the controller releases domestic payments.")
        def transaction(quote):
            reply={"needs_full_capture":False,"facts":[{"topic":"checks","source_id":source["id"],"quote":quote}],
                   "open_relationship":"","gap_source_id":""}
            return server.capture_facts.excerpt_transaction(reply,state,[source])
        self.assertIsNone(transaction("the controller releases domestic payments."))
        self.assertIsNone(transaction("The director releases payments."))
        change=transaction(source["text"])
        self.assertEqual(change["fact_operations"][0]["support"],[{"source_id":"t001","quote":source["text"]}])
        self.assertEqual(next(r["status"] for r in change["topic_states"] if r["key"]=="checks"),"partial")
        self.assertEqual(len(change["topic_states"]),16)
        source["text"]="Only the controller logs, checks , and releases domestic payments"
        normalized=transaction("Only the controller logs, checks, and releases domestic payments.")
        self.assertEqual(normalized["fact_operations"][0]["text"],source["text"])
        self.assertEqual(normalized["summary"],source["text"])
        self.assertIsNone(transaction("The controller logs, checks, and releases domestic payments."))

    def test_compact_capture_falls_back_when_a_merged_answer_or_material_clause_is_missing(self):
        state=server.capture_facts.empty_state()
        quote="The operator logs invoices."
        reply={"needs_full_capture":False,"facts":[{"topic":"lifecycle","source_id":"t001","quote":quote}]}
        self.assertIsNone(server.capture_facts.excerpt_transaction(reply,state,[
            answer(1,quote),answer(2,"The director authorizes the journal entry.")]))
        self.assertIsNone(server.capture_facts.excerpt_transaction(reply,state,[
            answer(1,quote+" All rejected requests require separate controller sign-off before release.")]))

    def test_map_editor_identifiers_stay_out_of_spoken_guidance(self):
        turns=[answer(1,"The controller checks the cash position.")]
        self.assertEqual(server.gpfs_interview.question_candidates(turns,[
            "Does the branch containing S1 (Check cash position) have its own trigger?"]),[])

    def test_live_capture_commits_exact_evidence_and_returns_to_full_review_after_two_excerpts(self):
        client=server.OpenAIClient({"OPENAI_API_KEY":"sk-test-synthetic"})
        payload=interview_payload()
        payload.update(live_notes=True,interview_memory=True,action="answer")
        payload["turns"]=[]
        modes=[]
        def reply(instructions,model_input,schema,*args,**kwargs):
            if "needs_full_capture" in schema["properties"]:
                modes.append("excerpt")
                turn=model_input["new_exchange"][-1]
                return {"needs_full_capture":False,"facts":[{"topic":"lifecycle","source_id":turn["id"],"quote":turn["text"]}],
                        "open_relationship":"","gap_source_id":""}
            modes.append("full")
            self.assertEqual([t["id"] for t in model_input["turns"] if t["role"]=="user"],["t000","t001","t002"])
            return {"base_revision":model_input["fact_state"]["base_revision"],"topic_states":[],"fact_operations":[],
                    "fact_reconciliations":[],"summary":"The operator records and reviews incoming invoices.",
                    "focus":"lifecycle","parking_lot":[]}
        client.structured=reply
        for i,detail in enumerate(["The operator logs each invoice in the register.","The controller reviews the batch every afternoon.",
                                   "The operator sends the signed register to Treasury."]):
            payload["turns"]+= [{"id":f"q{i}","role":"assistant","text":"What work follows?"},answer(i,detail)]
            capture=client.coordinator.interview(payload)
            self.assertFalse(capture.get("closure",{}).get("confirmed"))
            payload["capture_token"]=capture["capture_token"]
        self.assertEqual(modes,["excerpt","excerpt","full"])

if __name__=="__main__":
    unittest.main()
