"""Server behaviour added on 2026-11-18, each from a defect the final stress run left open.

One request per question, spelling hints for a recording, the head start for a draft, a draft
memo that starts from the interview's notes, reviewer notes in a reader's words, map rules for
start and end events and for rule sentences, and questions listed once. No provider here.
"""
import copy
import threading
import time
import types
import unittest
from unittest.mock import Mock
from urllib.parse import quote

from test_server import server, interview_payload, process_draft, fixture_draft_audit

concurrent_interview = server.concurrent_interview
draft_audit = server.draft_audit


class OneRequestTests(unittest.TestCase):
    def test_a_second_request_joined_with_and_is_left_for_a_later_turn(self):
        cases = {
            "What event prompts you to open the investment purchase, and how do you receive it?":
                "What event prompts you to open the investment purchase?",
            "After approval, how is the cash entry posted, and what tells the preparer it has posted successfully?":
                "After approval, how is the cash entry posted?",
            "Thanks. Which funds does this reconciliation cover, and does the same process apply across them?":
                "Thanks. Which funds does this reconciliation cover?",
            "The document describes the review. What happens to the schedule after that review, and who files it? Thank you.":
                "The document describes the review. What happens to the schedule after that review? Thank you.",
        }
        for asked, kept in cases.items():
            self.assertEqual(server.one_request(asked), kept)
            if kept.endswith("?"):
                self.assertEqual(server.question_rejection(kept, 1200, single=True), "")

    def test_a_single_question_is_never_cut(self):
        for question in ("Who approves the invoice?",
                         "Do you post it yourself, or does someone else post it?",
                         "What is the difference between a hold and what you call a soft reject?",
                         "Is it, and how?",                                      # too little would be left
                         # What would be left is not a question, or more than one clause would go.
                         "When the invoice arrives, and has been matched, what do you do next?",
                         "If the total does not reconcile, and is over the threshold, who do you tell?",
                         "The procedure says invoices over 5,000 need a second approver, and who is that today?",
                         "Talk me through the month-end close, and who signs it off?",
                         "When the invoice arrives, and who logs it?",
                         "You said “approve, and what next?” appears in the email; who sends it, and when is it sent?",
                         "Who checks the totals and the references before release?",
                         "Talk me through what happens after approval.", "", None, 7):
            self.assertEqual(server.one_request(question), question)

    def test_a_question_is_not_asked_twice_word_for_word(self):
        # Seen in the browser on 2026-11-18: an answer that spoke of something else was followed by
        # the previous question again, character for character.
        asked = concurrent_interview.ConcurrentInterview._asked_before
        turns = [{"id": "t1", "role": "assistant", "text": "What starts this work?"},
                 {"id": "t2", "role": "user", "text": "An email arrives. What does the supervisor check?"},
                 {"id": "t3", "role": "assistant", "text": "What does the AP supervisor check when approving the refund note?"},
                 {"id": "t4", "role": "user", "text": "Refunds above 5,000 pounds also need the finance manager."},
                 {"id": "t5", "role": "assistant", "document_event": True, "text": "Which file did you add?"}]
        self.assertTrue(asked("What does the AP supervisor check when approving the refund note?", turns))
        self.assertTrue(asked("what does the AP supervisor check, when approving the refund note", turns), "Punctuation and case aside")
        self.assertFalse(asked("What does the finance manager check before approving a large refund?", turns))
        self.assertFalse(asked("What does the supervisor check?", turns), "A participant's own words are not the interviewer's")
        self.assertFalse(asked("Which file did you add?", turns), "A file notice is not a question that was asked")
        # A question that a file notice displaced never had its answer: it may be asked again.
        displaced = [{"id": "t1", "role": "assistant", "text": "What can go wrong if this is late?"},
                     {"id": "t2", "role": "user", "document_event": True, "text": "Added checks.pdf"},
                     {"id": "t3", "role": "assistant", "text": "The file lists three checks. Is that how it is done today?"},
                     {"id": "t4", "role": "user", "text": "Yes."}]
        self.assertFalse(asked("What can go wrong if this is late?", displaced))
        self.assertTrue(asked("The file lists three checks. Is that how it is done today?", displaced))
        skipped = [{"id": "t1", "role": "assistant", "text": "Who approves it?"}, {"id": "t2", "role": "assistant", "text": "What starts it?"}]
        self.assertFalse(asked("Who approves it?", skipped), "skipped_questions keeps a skipped one away, not this guard")
        self.assertFalse(asked("", turns))
        self.assertIn("Never ask a question you have already asked, in the same words.", concurrent_interview.QUESTION_POLICY)

    def test_the_question_model_is_told_to_ask_one_thing_and_to_leave_a_thin_subject(self):
        policy = concurrent_interview.QUESTION_POLICY
        self.assertIn("One question asks for one thing.", policy)
        self.assertIn("do not ask a third question on that subject", policy)


class BreadthTests(unittest.TestCase):
    """Every third question turns to a topic that is still open, once the walkthrough is under way.

    Measured on 2026-11-18: a participant who answered everything in full was asked about one
    exception branch for some twenty questions; three topics stayed open through forty-five answers.
    """
    def due(self, answers, topics, untouched=()):
        turns = [{"role": "assistant" if n % 2 == 0 else "user", "text": "x"} for n in range(answers * 2)]
        fake = types.SimpleNamespace(api=server)
        return concurrent_interview.ConcurrentInterview._breadth_due(fake, topics, turns, untouched)

    def topics(self, **statuses):
        return [{"key": key, "status": statuses.get(key, "captured"), "gaps": [f"gap in {key}"], "participant_unavailable": False}
                for key in server.COVERAGE]

    def test_nothing_is_due_early_or_between_the_third_questions(self):
        open_three = self.topics(variations="partial", data_systems="partial", volume="unknown")
        for answers in (0, 1, 3, 5, 7, 8, 10):
            self.assertIsNone(self.due(answers, open_three), answers)
        self.assertIsNone(self.due(9, self.topics()), "Nothing is open")
        self.assertIsNone(self.due(9, self.topics(lifecycle="partial", checks="partial")), "The walkthrough covers the flow and its checks")
        unavailable = self.topics(volume="unknown")
        next(row for row in unavailable if row["key"] == "volume")["participant_unavailable"] = True
        self.assertIsNone(self.due(9, unavailable), "A topic the participant cannot speak to is not pressed")

    def test_each_open_topic_gets_its_turn_untouched_ones_first(self):
        open_three = self.topics(variations="partial", data_systems="partial", volume="unknown")
        chosen = [self.due(answers, open_three, untouched=("data_systems",))["topic"] for answers in (6, 9, 12, 15, 18, 21)]
        self.assertEqual(set(chosen[:3]), {"variations", "data_systems", "volume"}, "All three within three breadth questions")
        self.assertEqual(chosen[:3], chosen[3:], "And round again")
        first = self.due(6, open_three, untouched=("data_systems",))
        self.assertEqual(first["label"], server.COVERAGE[first["topic"]])
        self.assertEqual(first["gaps"], [f"gap in {first['topic']}"])
        order = [self.due(answers, open_three, untouched=("data_systems",))["topic"] for answers in (9, 12, 6)]
        self.assertEqual(order[0], "data_systems", "An untouched topic comes before a partly covered one")

    def test_the_topic_is_named_last_in_the_instructions_of_that_turn(self):
        directive = concurrent_interview.ConcurrentInterview._breadth_directive
        self.assertEqual(directive({"analysis_advice": {"available": True}}), "")
        self.assertEqual(directive({}), "")
        text = directive({"analysis_advice": {"breadth_due": {"topic": "volume", "label": server.COVERAGE["volume"], "gaps": []}}})
        self.assertIn("THIS TURN", text)
        self.assertIn(server.COVERAGE["volume"], text)
        self.assertIn(concurrent_interview.TOPIC_ASKS["volume"], text)
        self.assertEqual(set(concurrent_interview.TOPIC_ASKS) | {"lifecycle", "checks"}, set(server.COVERAGE),
                         "Every topic a breadth turn can name has its phrase")

    def test_the_question_model_is_told_what_breadth_due_means(self):
        policy = concurrent_interview.QUESTION_POLICY
        self.assertIn("breadth_due, when present, names one topic that is still open", policy)
        self.assertIn("Do not ask another question about the branch you were on.", policy)


class TranscriptionHintTests(unittest.TestCase):
    def test_hints_are_short_plain_terms(self):
        header = quote("Signatory A,AFC,Facility Tracker,<script>,x,FAN-SC-12,GP Fund Solutions,O’Brien & Co.,AFC, , " + "y" * 61)
        self.assertEqual(server.transcription_hints(header),
                         ["Signatory A", "AFC", "Facility Tracker", "FAN-SC-12", "GP Fund Solutions", "O’Brien & Co."])
        self.assertEqual(len(server.transcription_hints(quote(",".join(f"Term {n}" for n in range(60))))), server.MAX_TRANSCRIPTION_HINTS)

    def test_a_header_that_cannot_be_read_gives_no_hints(self):
        for header in (None, "", 7, "%ff%fe", "x" * 4001):
            self.assertEqual(server.transcription_hints(header), [])

    def test_a_recording_is_sent_with_the_configured_hints_and_the_interviews_own(self):
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional", "TRANSCRIPTION_KEYWORDS": "GPFS,Entrilia"})
        client.request = Mock(return_value={"text": "Signatory A signs it."})
        self.assertEqual(client.transcribe(b"x" * 200, "audio/wav", ["Signatory A", "Entrilia", "AFC"]), {"text": "Signatory A signs it."})
        body = client.request.call_args.args[1]
        sent = [part.split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0].decode() for part in body.split(b'name="keywords[]"')[1:]]
        self.assertEqual(sent, ["GPFS", "Entrilia", "Signatory A", "AFC"])
        # Without hints the request is what it was.
        client.transcribe(b"x" * 200, "audio/wav")
        body = client.request.call_args.args[1]
        self.assertEqual(body.count(b'name="keywords[]"'), 2)
        many = [f"Term {n}" for n in range(60)]
        client.transcribe(b"x" * 200, "audio/wav", many)
        self.assertEqual(client.request.call_args.args[1].count(b'name="keywords[]"'), server.MAX_TRANSCRIPTION_KEYWORDS)


class DraftHeadStartTests(unittest.TestCase):
    def client(self, seen, delay=0.0):
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        draft = process_draft()

        def structured(instructions, payload, schema, name, *args, **kwargs):
            seen.append(name)
            if name == "process_draft":
                if delay:
                    time.sleep(delay)
                return copy.deepcopy(draft)
            if name == "process_draft_audit":
                return fixture_draft_audit(draft, payload["turns"])
            raise server.APIError("No further scripted reply.", 503)
        client.structured = Mock(side_effect=structured)
        return client

    def test_the_first_half_is_written_once_and_the_draft_request_uses_it(self):
        seen = []
        client = self.client(seen)
        self.assertEqual(client.draft({**interview_payload(), "prepare_only": True}).get("prepared"), True)
        self.assertEqual(seen, ["process_draft"], "No audit runs for the head start")
        result = client.draft(interview_payload())
        self.assertIn("draft", result)
        self.assertEqual(seen.count("process_draft"), 1, "The draft is not written a second time")
        self.assertEqual(seen[1], "process_draft_audit")
        # A second head start for the same account costs nothing either.
        seen.clear()
        client.draft({**interview_payload(), "prepare_only": True})
        client.draft({**interview_payload(), "prepare_only": True})
        self.assertEqual(seen, ["process_draft"])

    def test_a_draft_requested_while_the_first_half_is_being_written_waits_for_it(self):
        seen = []
        client = self.client(seen, delay=0.3)
        results = {}
        head = threading.Thread(target=lambda: results.update(head=client.draft({**interview_payload(), "prepare_only": True})))
        head.start()
        time.sleep(0.05)
        results["draft"] = client.draft(interview_payload())
        head.join(5)
        self.assertEqual(results["head"].get("prepared"), True)
        self.assertIn("draft", results["draft"])
        self.assertEqual(seen.count("process_draft"), 1, "One candidate, not two")
        self.assertEqual(client._draft_pending, {})

    def test_a_head_start_that_fails_leaves_the_draft_request_to_write_its_own(self):
        seen = []
        client = self.client(seen)
        good = client.structured.side_effect
        client.structured.side_effect = server.APIError("The AI service is busy.", 503)
        with self.assertRaises(server.APIError):
            client.draft({**interview_payload(), "prepare_only": True})
        self.assertEqual(client._draft_pending, {}, "Nothing is left waiting on a request that failed")
        client.structured.side_effect = good
        self.assertIn("draft", client.draft(interview_payload()))

    def test_a_draft_waiting_on_a_head_start_that_fails_is_told_at_once(self):
        # Writing the candidate again after the first attempt failed doubled the wait for what
        # is most often the same outcome (a cut-off or a timeout).
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        calls = []

        def structured(instructions, payload, schema, name, *args, **kwargs):
            calls.append(name)
            time.sleep(0.3)
            raise server.OutputTruncated("The model's response was longer than this step allows.")
        client.structured = Mock(side_effect=structured)
        outcome = {}

        def head():
            try:
                client.draft({**interview_payload(), "prepare_only": True})
            except server.APIError as error:
                outcome["head"] = error
        thread = threading.Thread(target=head)
        thread.start()
        time.sleep(0.05)
        with self.assertRaises(server.OutputTruncated):
            client.draft(interview_payload())
        thread.join(5)
        self.assertIsInstance(outcome.get("head"), server.OutputTruncated)
        self.assertEqual(calls, ["process_draft"], "The waiting request did not write the draft a second time")
        self.assertEqual(client._draft_pending, {})

    def test_a_candidate_whose_draft_cannot_be_validated_is_not_kept_for_the_retry(self):
        seen = []
        client = self.client(seen)
        good = client.structured.side_effect

        def broken(instructions, payload, schema, name, *args, **kwargs):
            reply = good(instructions, payload, schema, name, *args, **kwargs)
            if name == "process_draft_audit":
                reply["steps"][0]["evidence_turns"] = ["no-such-turn"]
            return reply
        client.structured.side_effect = broken
        with self.assertRaises(server.APIError):
            client.draft(interview_payload())
        self.assertEqual(client._draft_candidates, {}, "The same candidate would fail the same way on every retry")
        client.structured.side_effect = good
        self.assertIn("draft", client.draft(interview_payload()))
        self.assertEqual(seen.count("process_draft"), 2, "The retry wrote a new candidate")

    def test_another_account_is_another_candidate(self):
        seen = []
        client = self.client(seen)
        client.draft({**interview_payload(), "prepare_only": True})
        changed = interview_payload()
        changed["turns"][-1]["text"] += " One more detail."
        client.draft(changed)
        self.assertEqual(seen.count("process_draft"), 2)

    def test_the_setting_reaches_the_page(self):
        self.assertTrue(server.OpenAIClient({"OPENAI_API_KEY": "fictional"}).draft_prepare)
        for value in ("off", "OFF", "false", "0", "no"):
            self.assertFalse(server.OpenAIClient({"OPENAI_API_KEY": "fictional", "DRAFT_PREPARE": value}).draft_prepare)
        self.assertTrue(server.OpenAIClient({"OPENAI_API_KEY": "fictional", "DRAFT_PREPARE": "on"}).draft_prepare)


class DraftStartsFromTheNotesTests(unittest.TestCase):
    def requested(self, previous):
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        draft = process_draft()
        seen = []

        def structured(instructions, payload, schema, name, *args, **kwargs):
            seen.append((name, instructions, payload))
            if name == "process_draft":
                return copy.deepcopy(draft)
            return fixture_draft_audit(draft, payload["turns"])
        client.structured = Mock(side_effect=structured)
        client.draft({**interview_payload(), **({"previous_capture": previous} if previous else {})})
        return seen[0]

    def capture(self, status):
        return {"workflow": {"title": "", "steps": [], "connections": [], "open_questions": []},
                "memo_findings": [{"key": key, "status": status if key == "name" else "unknown",
                                   "answer": "Invoice approval." if key == "name" and status != "unknown" else "UNKNOWN",
                                   "evidence_turns": ["u1"] if key == "name" and status != "unknown" else []}
                                  for key in server.COVERAGE],
                "summary": "", "focus": "", "parking_lot": []}

    def test_the_draft_is_given_the_topic_notes_and_told_to_keep_their_statuses(self):
        name, instructions, payload = self.requested(self.capture("captured"))
        self.assertEqual(name, "process_draft")
        self.assertEqual(next(row for row in payload["working_notes"] if row["key"] == "name")["status"], "captured")
        self.assertEqual(instructions, server.draft_instructions(True))
        for wording in ("Write each memo_summary section from its note", "Do not lower a status",
                        "The notes are a working interpretation, never evidence"):
            self.assertIn(wording, instructions)

    def test_notes_that_say_nothing_are_not_sent(self):
        for previous in (None, self.capture("unknown")):
            name, instructions, payload = self.requested(previous)
            self.assertNotIn("working_notes", payload)
            self.assertEqual(instructions, server.draft_instructions())
            self.assertNotIn("working notes", instructions)


class ReviewerNoteTests(unittest.TestCase):
    def test_what_the_source_check_took_out_is_said_in_a_readers_words(self):
        candidate = {"steps": [{"id": "S1"}, {"id": "S2"}, {"id": "S3"}], "exceptions": ["Late invoice", "Missing order"],
                     "memo_summary": [{"key": "purpose", "evidence_turns": ["u1", "u2"]}]}
        reviewed = {"steps": [{"id": "S1"}], "exceptions": ["Missing order"], "memo_summary": [{"key": "purpose", "evidence_turns": ["u1"]}]}
        notes = draft_audit.removal_notes(candidate, reviewed, server.COVERAGE)
        self.assertEqual(notes, [
            "The source check removed 2 steps that the answers and files did not support.",
            "The source check reworded or removed 1 exception to match what was reported; confirm the exceptions listed.",
            "The source check removed a cited source from “Purpose & result” that did not support it."])
        self.assertFalse(any("independent audit" in note or "(s)" in note for note in notes))
        self.assertEqual(draft_audit.removal_notes(candidate, candidate), [])

    def test_a_draft_says_once_and_first_what_it_is(self):
        payload = interview_payload()
        draft = process_draft()
        standard = "AI-generated draft. Process-owner review is required; interview statements have not been independently verified."
        draft["validation_notes"] = [
            "AI-generated current-practice draft requiring process-owner review; participant confirmation and owner approval are pending.",
            "The approver for invoices above the limit was not named.",
            "Current-practice draft for process-owner review. Participant confirmation and owner approval are pending; coverage is incomplete.",
            standard]
        checked = server.validate_draft(draft, payload["turns"])
        self.assertEqual(checked["validation_notes"][0], standard)
        self.assertEqual(checked["validation_notes"].count(standard), 1)
        self.assertIn("The approver for invoices above the limit was not named.", checked["validation_notes"])
        self.assertFalse(any(note.startswith(("AI-generated current-practice", "Current-practice draft")) for note in checked["validation_notes"]))

    def test_a_note_about_a_draft_in_the_work_itself_is_kept(self):
        for note in ("Draft for investor notices requires approval, but the approver was not named.",
                     "Draft pending approval is sent to investors before the controller signs; confirm whether that is intended.",
                     "Review draft for the NAV pack is prepared before the pricing review is complete.",
                     "AI-generated reconciliation suggestions feed the draft journal, and nobody was named for their review.",
                     "The draft for review omits the cash-entry posting step because it was not reported."):
            self.assertIsNone(server._DRAFT_DISCLAIMER.match(note), note)
        # A note that begins like the disclaimer and goes on to report something is kept whole.
        for note in ("AI-generated draft requiring process-owner review; the approval limit in Answer 4 conflicts with the policy file.",
                     "Draft for process-owner review: the cut-off time was reported as both 3 pm and 5 pm and needs confirmation.",
                     "Draft pending confirmation of the escalation contact by the treasury team."):
            self.assertIsNone(server._DRAFT_DISCLAIMER.match(note), note)
        for note in ("AI-generated current-practice draft requiring process-owner review; participant confirmation and owner approval are pending.",
                     "Draft for participant and process-owner review. Participant confirmation and owner approval are UNKNOWN; this capture is not complete.",
                     "AI-generated current-practice draft requiring participant and process-owner review. It is not an independently verified or executable procedure."):
            self.assertIsNotNone(server._DRAFT_DISCLAIMER.match(note), note)

    def test_the_draft_is_told_to_write_notes_for_the_owner(self):
        instructions = server.draft_instructions()
        self.assertIn("Write validation_notes for the process owner who will review the draft", instructions)
        self.assertIn("Do not\ndescribe how this draft was produced", instructions)
        self.assertNotIn("Always include a note that this is an AI-generated draft", instructions)


class MapRuleTests(unittest.TestCase):
    def test_a_stated_start_and_finish_are_drawn_and_a_rule_is_not_a_step(self):
        for instructions in (server.WORKFLOW_MAP_INSTRUCTIONS, server.WORKFLOW_INSTRUCTIONS, server.draft_instructions()):
            self.assertIn("draw it as the start node and connect it to the first action it sets off", instructions)
            self.assertIn("draw\n  it as an end node reached from the step that produces it", instructions)
            self.assertIn("never add a start or end node that no\n  statement supports", instructions)
            self.assertIn("A rule, limit, threshold, definition or policy\n  sentence is not a step", instructions)

    def test_a_question_is_listed_once_whatever_its_punctuation(self):
        existing = ["How does step S29, Track overdue cases, connect to the rest of this process, if at all?"]
        added = server.add_workflow_questions(existing, [
            "How does step S29 (Track overdue cases) connect to the rest of this process, if at all?",
            "how does step s29 track overdue cases connect to the rest of this process if at all",
            "How does step S30 (Review invoice risks monthly) connect to the rest of this process, if at all?",
            "How does step S30 (Review invoice risks monthly) connect to the rest of this process, if at all?"])
        self.assertEqual(added, [existing[0], "How does step S30 (Review invoice risks monthly) connect to the rest of this process, if at all?"])


class CompatibilityMapRouteTests(unittest.TestCase):
    def test_a_map_update_cut_off_at_its_allowance_is_asked_for_once_more_with_room(self):
        # /api/workflow, the route kept for callers without the managed team, had a fixed 12,000
        # tokens and no second attempt: it failed the map in four of six calls on 2026-11-17.
        client = server.OpenAIClient({"OPENAI_API_KEY": "fictional"})
        allowances = []

        def structured(instructions, payload, schema, name, max_tokens, *args, **kwargs):
            allowances.append((name, max_tokens, kwargs.get("request_timeout")))
            raise server.OutputTruncated("The model's response was longer than this step allows.")
        client.structured = Mock(side_effect=structured)
        with self.assertRaises(server.OutputTruncated):
            client.workflow(interview_payload())
        self.assertEqual(allowances, [("working_process_map", 12000, None),
                                      ("working_process_map", server.WORKFLOW_RETRY_OUTPUT_TOKENS, server.WORKFLOW_RETRY_TIMEOUT)])
        self.assertGreater(server.WORKFLOW_RETRY_OUTPUT_TOKENS, 22000)
        # The second attempt has the time its allowance takes to write.
        self.assertGreaterEqual(server.WORKFLOW_RETRY_TIMEOUT, 180)


if __name__ == "__main__":
    unittest.main()
