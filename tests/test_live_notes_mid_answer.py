"""Live voice notes taken while an answer is still being spoken (web/app.js captureMidAnswer).

The page sends the transcript as it stands, with the open answer cut off mid-sentence, and later
sends the whole answer. The capability it sends then is either the one it held before (the answer
grew while the first capture was on its way) or the mid-answer capture's own (it had not grown
yet). Either way the server accepts the capture of the whole answer: the private fact ledger is
continued from the mid-answer capture (a live caption that grew by words added at its end is the
same answer, see InterviewCoordinator._fact_record), facts from other answers are kept, and the
grown answer is read whole by the full capture (capture_facts.rebase retires the facts quoted
from its shorter text, whose source changed; the quick excerpt path needs unchanged earlier
turns). The provider is a local stand-in; no network.
"""
import json
import unittest

from test_server import server, interview_payload


def answer(number, text):
    return {"id": f"t{number:03}", "role": "user", "text": text}


FIRST = "The operator logs each invoice in the register."
PART = "The controller reviews the batch every afternoon."
WHOLE = PART + " Then the operator sends the signed register to Treasury."


class MidAnswerCaptureTests(unittest.TestCase):
    def capture(self, client, payload, turns, token):
        body = {**payload, "turns": turns}
        if token:
            body["capture_token"] = token
        return client.coordinator.interview(body)

    def run_three(self, continue_from_mid_answer):
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-test-synthetic"})
        payload = interview_payload()
        payload.update(live_notes=True, interview_memory=True, action="answer")
        calls = []

        def reply(instructions, model_input, schema, *args, **kwargs):
            if "needs_full_capture" in schema["properties"]:
                calls.append(("excerpt", model_input))
                turn = model_input["new_exchange"][-1]
                return {"needs_full_capture": False, "facts": [{"topic": "lifecycle", "source_id": turn["id"], "quote": turn["text"]}],
                        "open_relationship": "", "gap_source_id": ""}
            calls.append(("full", model_input))
            return {"base_revision": model_input["fact_state"]["base_revision"], "topic_states": [], "fact_operations": [],
                    "fact_reconciliations": [], "summary": "The operator logs invoices and the controller reviews them.",
                    "focus": "lifecycle", "parking_lot": []}

        client.structured = reply
        start = [{"id": "q0", "role": "assistant", "text": "What starts the work?"}, answer(0, FIRST)]
        first = self.capture(client, payload, start, None)
        # The answer that follows, read while it is still being spoken.
        mid_turns = start + [{"id": "q1", "role": "assistant", "text": "What happens next?"}, answer(1, PART)]
        mid = self.capture(client, payload, mid_turns, first["capture_token"])
        # The same answer once it has ended: its caption only grew.
        whole_turns = start + [mid_turns[2], answer(1, WHOLE)]
        token = mid["capture_token"] if continue_from_mid_answer else first["capture_token"]
        whole = self.capture(client, payload, whole_turns, token)
        return calls, mid, whole

    def test_the_capture_of_the_whole_answer_continues_the_mid_answer_ledger(self):
        for continue_from_mid_answer in (False, True):
            with self.subTest(continue_from_mid_answer=continue_from_mid_answer):
                calls, mid, whole = self.run_three(continue_from_mid_answer)
                self.assertTrue(any(fact["text"] == PART for fact in mid["fact_provenance"]))
                # Accepted as a new capture (not refused, not a replay of the mid-answer one).
                self.assertTrue(whole["capture_token"])
                self.assertNotEqual(whole["capture_token"], mid["capture_token"])
                self.assertIsNot(whole.get("no_new_run"), True)
                self.assertFalse(whole.get("closure", {}).get("confirmed"))
                # The model reads the whole answer, with the ledger continued.
                kind, model_input = calls[-1]
                self.assertEqual([name for name, _ in calls], ["excerpt", "excerpt", "full"])
                self.assertEqual([turn["text"] for turn in model_input["turns"] if turn["role"] == "user"], [FIRST, WHOLE])
                self.assertIn(FIRST, json.dumps(model_input["fact_state"]))
                self.assertTrue(any(fact["text"] == FIRST and fact["evidence_turns"] == ["t000"] for fact in whole["fact_provenance"]))
                # The ledger it continued is the mid-answer capture's: the fact quoted from the
                # shorter text is in its history, retired because its source has grown.
                self.assertEqual([(row["topic"], row["state"]) for row in whole["fact_history"]], [("lifecycle", "retired_source")])


if __name__ == "__main__":
    unittest.main()
