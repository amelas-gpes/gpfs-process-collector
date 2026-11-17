"""Regression cases for docs/testing/runs/2026-11-16-process-capture that have no suite of their own.

Finding 1 (server side): a file whose text is indexed while no review has reported a phase.
Finding 5: a citation a model got wrong is settled internally; the map is not refused for it.
Findings 7 and 10: what the question model is given and told about stated unknowns and records.
Finding 13: indexed text, supplied sections, review progress and unread visuals as separate facts.
Everything here is synthetic: fictional processes, fake review callbacks, temporary stores.
"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock

from test_server import server
from test_workflow_updates import audit, edge, payload, step, update
import concurrent_interview
import gpfs_interview
from test_pdf_page_furniture import TABLE, pdf_bytes, text_commands

ROOT = Path(__file__).resolve().parents[1]
documents = server.documents
document_service = server.local_module("document_service", "document_service.py")
SAMPLES = ROOT / 'docs' / 'testing' / 'runs' / '2026-11-16-process-capture' / 'uploads' / 'inputs'
U1 = 'I prepare the discovery board, prioritize ideas, update them, then attach a Jira ticket or Confluence document.'
U2 = ('Sorry, the first step was not checking the discovery board. Change it to get water and put my mind at ease '
      'before I start.')


def detail(field, text, sources):
    return {'field': field, 'text': text, 'evidence_turns': list(sources)}


class OperatingDetailTests(unittest.TestCase):
    """A step's operating details keep what its own cited sources bear out."""

    def settle(self, details, sources=('u1',), accepted=None):
        item = {**step('S1', 'Prepare discovery board', list(sources)), 'operating_details': copy.deepcopy(details)}
        dropped = gpfs_interview.settle_operating_details([item], payload()['turns'], [], {}, accepted=accepted)
        return item['operating_details'], dropped

    def test_a_detail_its_own_source_bears_out_is_kept_unchanged(self):
        good = detail('responsible', 'I prepare the discovery board', ['u1'])
        self.assertEqual(self.settle([good]), ([good], 0))

    def test_a_detail_citing_another_steps_source_or_wording_no_source_holds_is_dropped(self):
        outside = detail('responsible', 'get water and put my mind at ease', ['u2'])   # u2 is not this step's source
        invented = detail('control', 'The manager signs the board every Friday', ['u1'])
        assistant = detail('system', 'How do you decide which idea comes first?', ['a1'])
        self.assertEqual(self.settle([outside, invented, assistant]), ([], 3))
        with self.assertRaisesRegex(ValueError, 'cite evidence from its own step'):
            gpfs_interview.validate_operating_details(
                [{**step('S1', 'Prepare discovery board'), 'operating_details': [outside]}], payload()['turns'], [], {})

    def test_a_detail_keeps_only_the_sources_that_hold_its_wording(self):
        mixed = detail('responsible', 'I prepare the discovery board', ['u2', 'u1', 'u1', 'missing'])
        kept, dropped = self.settle([mixed], sources=('u1', 'u2'))
        self.assertEqual((kept, dropped), ([detail('responsible', 'I prepare the discovery board', ['u1'])], 0))

    def test_rows_that_are_not_details_are_dropped_and_the_result_validates(self):
        rows = [detail('responsible', 'I prepare the discovery board', ['u1']), {'field': 'mood', 'text': 'x', 'evidence_turns': ['u1']},
                {'field': 'system', 'text': '', 'evidence_turns': ['u1']}, 'not a row', detail('system', 'x' * 501, ['u1']),
                {'field': 'system', 'text': 'attach a Jira ticket', 'evidence_turns': 'u1'}]
        kept, dropped = self.settle(rows)
        self.assertEqual((len(kept), dropped), (1, 5))
        gpfs_interview.validate_operating_details(
            [{**step('S1', 'Prepare discovery board'), 'operating_details': kept}], payload()['turns'], [], {})
        many, dropped = self.settle([detail('system', 'attach a Jira ticket', ['u1'])] * 40)
        self.assertEqual((len(many), dropped), (32, 8))

    def test_details_the_accepted_step_already_had_are_left_as_they_are(self):
        carried = detail('system', 'Wording of an excerpt this request could not read', ['doc_unread_p1_c1'])
        kept, dropped = self.settle([carried], accepted={'S1': [carried]})
        self.assertEqual((kept, dropped), ([carried], 0))
        self.assertEqual(self.settle([carried]), ([], 1), 'The same row as a new proposal has nothing to stand on')


class GeneratedCitationTests(unittest.TestCase):
    """Finding 5: the participant is never handed a model's citation slip to resolve."""

    def setUp(self):
        self.value = payload()
        self.previous = self.value['previous_capture']
        self.turns = self.value['turns']

    def test_an_invalid_operating_detail_no_longer_fails_the_map(self):
        slipped = {**step('S5', 'Attach supporting ticket'), 'operating_details': [
            detail('system', 'attach a Jira ticket or Confluence document', ['u1']),
            detail('responsible', 'get water and put my mind at ease', ['u2'])]}   # cites outside its own step
        result = server.apply_workflow_update(update(upsert_steps=[slipped], upsert_connections=[edge('S4', 'S5')]),
                                              self.previous, self.turns)
        published = next(item for item in result['workflow']['steps'] if item['id'] == 'S5')
        self.assertEqual(published['operating_details'], [detail('system', 'attach a Jira ticket or Confluence document', ['u1'])])
        self.assertIn(('S4', 'S5', 'next'), {server.route_key(item) for item in result['workflow']['connections']})

    def test_a_source_that_is_not_one_is_taken_off_and_a_component_left_without_any_is_named(self):
        repaired = step('S5', 'Archive idea', ['u1', 'a1', 'made_up_reference'])
        unsupported = step('S6', 'Invented approval', ['made_up_reference'])
        candidate = update(upsert_steps=[repaired, unsupported, step('S2', 'Rank ideas', ['a1'])],
                           upsert_connections=[edge('S4', 'S5', 'Done', ['u1', 'a1']), edge('S5', 'S6', 'Approved', ['u1']),
                                               edge('S1', 'S3', 'Skip', ['a1'])])
        settled = server.settle_generated_citations(candidate, self.previous, self.turns)
        self.assertEqual([item['id'] for item in settled['upsert_steps']], ['S5'])
        self.assertEqual(settled['upsert_steps'][0]['evidence_turns'], ['u1'])
        self.assertEqual(settled['upsert_connections'], [edge('S4', 'S5', 'Done', ['u1'])],
                         'The route to the step left off the map goes with it; the unsupported route becomes a question')
        questions = settled['open_questions']
        self.assertTrue(any('Invented approval' in question and 'left off the map' in question for question in questions))
        self.assertTrue(any('Prioritize ideas' in question and 'its change was left out' in question for question in questions),
                        'An accepted step keeps its accepted form')
        self.assertTrue(any('handoff or prerequisite' in question and 'Skip' in question for question in questions))
        self.assertEqual(len(candidate['upsert_steps']), 3, 'The model output itself is never mutated')
        merged = server.apply_workflow_update(candidate, self.previous, self.turns)
        self.assertEqual([item['title'] for item in merged['workflow']['steps']][:4],
                         ['Prepare discovery board', 'Prioritize ideas', 'Update ideas', 'Attach ticket or document'])
        self.assertNotIn('made_up_reference', json.dumps(merged))
        # Settling twice changes nothing more, and a correct update passes through untouched.
        self.assertEqual(server.settle_generated_citations(settled, self.previous, self.turns), settled)
        correct = update(upsert_steps=[step('S5', 'Archive idea')], upsert_connections=[edge('S4', 'S5')])
        self.assertEqual(server.settle_generated_citations(correct, self.previous, self.turns), correct)

    def test_what_is_not_an_update_is_left_for_the_schema_check_to_refuse(self):
        self.assertEqual(server.settle_generated_citations('nonsense', self.previous, self.turns), 'nonsense')
        self.assertEqual(server.settle_generated_citations({'upsert_steps': 'x'}, self.previous, self.turns), {'upsert_steps': 'x'})
        with self.assertRaises(ValueError):
            server.apply_workflow_update({'upsert_steps': 'x'}, self.previous, self.turns)

    def test_a_forced_invalid_citation_on_a_file_keeps_the_file_and_publishes_the_map(self):
        original = payload()
        excerpt = {'id': 'doc_fixture_p1_c1', 'text': 'The analyst registers the invoice and the controller approves the register.',
                   'location': {'page': 1}}
        original['_supporting_documents'] = {'documents': [{'id': 'doc_fixture', 'name': 'Procedure.pdf', 'excerpts': [excerpt]}]}
        registered = {**step('S5', 'Register invoice', ['doc_fixture_p1_c1']), 'operating_details': [
            detail('responsible', 'The analyst registers the invoice', ['doc_fixture_p1_c1']),
            # The generated detail the November run tripped over: wording its cited excerpt does not contain.
            detail('control', 'The controller approves every register within two days', ['doc_fixture_p1_c1']),
            detail('accountable', 'the controller approves the register', ['u1'])]}
        client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-citation-repair'})
        client.structured = Mock(side_effect=[update(upsert_steps=[registered]), audit()])
        client.apply_coverage_review = lambda capture, *args, **kwargs: capture
        result = client.workflow(original)
        published = next(item for item in result['workflow']['steps'] if item['id'] == 'S5')
        self.assertEqual(published['operating_details'],
                         [detail('responsible', 'The analyst registers the invoice', ['doc_fixture_p1_c1'])])
        self.assertEqual([source['id'] for source in result['document_evidence']], ['doc_fixture_p1_c1'], 'The file stays attached')
        # The audit was shown the settled candidate, not the slip.
        audited = client.structured.call_args_list[1].args[1]['candidate_update']
        self.assertEqual(len(audited['upsert_steps'][0]['operating_details']), 1)


class ReviewSchedulingTests(unittest.TestCase):
    """Finding 1, server side: an indexed file with no review phase is still owed its first assessment."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()
        self.calls = []

    def service(self):
        def review(context, record, chunks, phase):
            self.calls.append(phase)
            return {'summary': 'A fictional stage list.', 'acknowledgement': 'Read.', 'relevance': 'relevant',
                    'relevance_reason': 'It lists the stages.', 'question': '', 'queries': [], 'observations': [], 'questions': [],
                    'extracted_text': ''}
        manager = document_service.DocumentService(self.store, review)
        self.addCleanup(lambda: (manager.close(), manager._worker.join(timeout=2)))
        return manager

    def indexed(self, analysis):
        record = self.store.extract(self.scope, self.store.add(self.scope, 'stages.csv', b'stage\nFictionalIntake\n')['id'])
        self.assertEqual(record['status'], 'ready')
        return self.store.update(self.scope, record['id'], {'analysis': analysis})

    def wait(self, manager, done):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            record = manager.status(self.scope, {})[0]
            if done(record):
                return record
            threading.Event().wait(.01)
        self.fail('The file review did not reach the expected state')

    def test_an_indexed_file_whose_review_has_no_phase_is_reviewed_by_the_next_poll(self):
        # Indexed, with metadata but no phase: a file removed before its first review and added
        # again rested here for good while the page waited on "Reading your files".
        record = self.indexed({'intent_version': 0, 'version': 1})
        self.assertNotIn('phase', record['analysis'])
        manager = self.service()
        reviewed = self.wait(manager, lambda current: current['analysis'].get('phase') == 'complete')
        self.assertEqual(self.calls, ['quick'])
        self.assertEqual(reviewed['analysis']['disposition'], 'relevant')

    def test_a_stopped_review_without_a_phase_is_not_started_by_a_poll(self):
        self.indexed({'intent_version': 0, 'version': 1, 'review_stopped': True})
        manager = self.service()
        for _ in range(5):
            manager.status(self.scope, {})
            threading.Event().wait(.01)
        self.assertEqual(self.calls, [])


class CoverageFactTests(unittest.TestCase):
    """Finding 13: Assets and the notes are given the same four separate facts about a file."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()
        self.manager = document_service.DocumentService(self.store, lambda *args: None)
        self.addCleanup(lambda: (self.manager.close(), self.manager._worker.join(timeout=2)))

    def supplied(self, name, data, analysis):
        record = self.store.extract(self.scope, self.store.add(self.scope, name, data)['id'])
        self.store.update(self.scope, record['id'], {'analysis': {'disposition': 'relevant', 'intent_version': 0, **analysis}})
        return self.manager.supporting_context(self.scope, 'treasury payment release')

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing PDF runtime required')
    def test_indexed_text_supplied_sections_review_progress_and_unread_visuals_are_separate_facts(self):
        text = text_commands()
        data = pdf_bytes([{'text': text, 'drawn': TABLE}, {'text': text, 'image': (300, 200)}, {'text': text}])
        context = self.supplied('procedure.pdf', data, {'phase': 'complete', 'review_stopped': True, 'reviewed_chunks': 1,
                                                        'total_chunks': 4, 'review_complete': False})
        file = context['documents'][0]
        review, coverage = file['review'], file['context_coverage']
        # Every page has indexed text; one page also holds a graphic nobody has read; the review was paused.
        self.assertEqual((review['unit'], review['total_units'], review['native_text_units'], review['unread_visual_units']),
                         ('pages', 3, 3, 1))
        self.assertEqual((review['indexed_units'], review['reviewed_chunks'], review['review_stopped'], review['review_complete']),
                         (2, 1, True, False))
        self.assertEqual((coverage['included_chunks'], coverage['total_chunks'], coverage['all_indexed_sections_supplied'],
                          coverage['text_sections_supplied'], coverage['unread_visual_placeholders_supplied']), (4, 4, True, 3, 1))
        self.assertIs(coverage['complete_text'], False, 'A whole-file claim still needs the graphic to be read')
        self.assertIn('State four facts about a file separately', context['notice'])
        self.assertIn('do not call the text coverage incomplete', context['notice'])
        # The Live voice digest carries the same figures under the same names.
        digest, _ = server.live_document_context(context, 900)
        if digest and digest.get('documents'):
            self.assertEqual(digest['documents'][0]['review']['native_text_units'], 3)
            self.assertEqual(digest['documents'][0]['review']['unread_visual_units'], 1)
        self.assertIn('unread_visual_units', server.LIVE_DOCUMENT_POLICY)

    def test_a_file_without_pages_reports_its_own_unit_and_no_unread_visuals(self):
        context = self.supplied('stages.csv', b'stage,owner\nIntake,Analyst\nRelease,Treasury\n', {'phase': 'complete', 'review_complete': True})
        review = context['documents'][0]['review']
        self.assertEqual((review['unread_visual_units'], review['review_stopped']), (0, False))
        self.assertEqual(review['native_text_units'], review['total_units'])
        self.assertIs(context['documents'][0]['context_coverage']['all_indexed_sections_supplied'], True)

    @unittest.skipUnless((SAMPLES / 'U10 GP-03 Carry Vesting & Carry Point Reallocation.pdf').is_file(), 'Testing corpus not present')
    def test_the_complete_carry_vesting_upload_reports_24_text_pages_and_nothing_unread(self):
        data = (SAMPLES / 'U10 GP-03 Carry Vesting & Carry Point Reallocation.pdf').read_bytes()
        context = self.supplied('U10.pdf', data, {'phase': 'complete', 'review_complete': True, 'reviewed_chunks': 24, 'total_chunks': 24})
        file = context['documents'][0]
        self.assertEqual((file['review']['native_text_units'], file['review']['total_units'], file['review']['unread_visual_units']), (24, 24, 0))
        self.assertEqual((file['context_coverage']['included_chunks'], file['context_coverage']['total_chunks']), (24, 24))
        self.assertIs(file['context_coverage']['complete_text'], True)


class MapBudgetTests(unittest.TestCase):
    """A working map is not lost to its own source audit.

    In the November run 14 of 17 final maps ended in error. A live replay showed why: the map was
    drawn in under a minute, and its source audit then ran into a 120-second limit, or used up a
    12,000-token allowance on reasoning before it could answer.
    """

    def test_the_audit_has_room_to_answer_and_a_background_map_has_longer_limits(self):
        from test_interview_orchestrator import SyntheticTeamProvider
        orchestrator = server.interview_orchestrator
        self.assertEqual((orchestrator.MAP_GENERATION_SECONDS, orchestrator.MAP_AUDIT_SECONDS,
                          orchestrator.MAP_AUDIT_WITH_FILES_SECONDS), (120, 180, 240))
        self.assertEqual((orchestrator.BACKGROUND_MAP_GENERATION_SECONDS, orchestrator.BACKGROUND_MAP_AUDIT_SECONDS), (180, 240))
        self.assertEqual(orchestrator.MAP_AUDIT_OUTPUT_TOKENS, 24000)
        # A map the page waits for must still finish inside the page's own limit.
        self.assertLessEqual((orchestrator.MAP_GENERATION_SECONDS + orchestrator.MAP_AUDIT_SECONDS) * 1000,
                             server.REQUEST_TIMEOUTS_MS['workflow'])
        self.assertLessEqual((orchestrator.MAP_GENERATION_SECONDS + orchestrator.MAP_AUDIT_WITH_FILES_SECONDS) * 1000,
                             server.REQUEST_TIMEOUTS_MS['workflow_with_files'])
        for background in (False, True):
            with self.subTest(background=background):
                client = SyntheticTeamProvider()
                value = client.payload()
                if background:
                    value['_map_only'] = True   # set by the concurrent interview's own worker
                client.coordinator.workflow(value)
                calls = {call.args[1]['text']['format']['name']: call for call in client.request.call_args_list}
                drawn, audited = calls['team_working_process_map'], calls['team_working_map_source_audit']
                self.assertEqual(drawn.kwargs['timeout'], 180 if background else 120)
                self.assertEqual(audited.kwargs['timeout'], 240 if background else 180)
                self.assertEqual(audited.args[1]['max_output_tokens'], 24000)
                self.assertEqual(drawn.args[1]['max_output_tokens'], 12000)

    def test_the_route_repair_is_a_short_low_effort_request(self):
        client = Mock()
        client.structured = Mock(return_value={'connections': [], 'replaced_connections': []})
        repair = server.RouteRepair(client, {}, payload()['turns'], {}, 'team_working_map_source_audit', time.monotonic() + 300)
        workflow = payload()['previous_capture']['workflow']
        repair.ask({**workflow, 'steps': workflow['steps'] + [step('S9', 'Detached step')]},
                   [{'kind': 'detached', 'steps': ['S9'], 'gate': False}])
        options = client.structured.call_args.kwargs
        self.assertEqual(options['reasoning_effort'], 'low')
        self.assertLessEqual(options['request_timeout'], server.ROUTE_RECHECK_TIMEOUT)
        self.assertEqual(client.structured.call_args.args[4], server.ROUTE_REPAIR_OUTPUT_TOKENS)


class QuestionGuardTests(unittest.TestCase):
    """Findings 7 and 10: the question is checked against the answers, also the one just given."""

    FA07 = [
        {'id': 't7', 'role': 'user', 'text': 'The lead checks the completed package and approval records. We send completion confirmation '
         'to the client, record the date and lock the package. The exact form of the lead\'s approval record and escalation path '
         'still need confirmation.'},
        {'id': 't8', 'role': 'assistant', 'text': 'What record, if any, shows the approval?'},
        {'id': 't9', 'role': 'user', 'text': 'The write-up lists the signed checklist and completion correspondence. I can\'t give a particular '
         'form name, field or location. I\'d leave that item open for the process owner.'},
    ]

    def service(self, with_gate=True):
        api = types.SimpleNamespace(interview_coverage=server.interview_coverage) if with_gate else types.SimpleNamespace()
        return concurrent_interview.ConcurrentInterview(types.SimpleNamespace(coordinator=types.SimpleNamespace()), api)

    def test_stated_unknowns_are_listed_from_the_answers_themselves_newest_first(self):
        service = self.service()
        self.addCleanup(service.close)
        found = service._known_unknowns(self.FA07)
        self.assertEqual([row['turn_id'] for row in found], ['t9', 't9', 't7'])
        self.assertEqual(found[0]['statement'], "I can't give a particular form name, field or location.")
        self.assertEqual(found[1]['statement'], "I'd leave that item open for the process owner.")
        self.assertIn('still need confirmation', found[2]['statement'])
        # What was explained is not listed, nor are assistant questions or file notices.
        self.assertFalse(any('lock the package' in row['statement'] for row in found))
        notice = {'id': 'n1', 'role': 'user', 'text': 'The owner is unknown.', 'document_event': True}
        self.assertEqual(service._known_unknowns([notice, {'id': 'a', 'role': 'assistant', 'text': 'Is it unknown?'}]), [])
        many = [{'id': f'u{index}', 'role': 'user', 'text': 'The owner is unconfirmed. ' * 5} for index in range(9)]
        self.assertEqual(len(service._known_unknowns(many)), concurrent_interview.MAX_KNOWN_UNKNOWNS)
        self.assertLessEqual({row['turn_id'] for row in service._known_unknowns(many)}, {f'u{index}' for index in range(3, 9)},
                             'Only the recent answers are read')

    def test_the_participants_own_wording_is_recognised_without_the_notes_gate(self):
        service = self.service(with_gate=False)
        self.addCleanup(service.close)
        self.assertEqual([row['turn_id'] for row in service._known_unknowns(self.FA07)], ['t9', 't9'])
        for sentence in ("I don't have a narrower list of qualifying changes.", 'The procedure leaves the escalation owner unspecified.',
                         "I cannot tell you the executable formula.", 'There is no documented deadline.'):
            self.assertTrue(concurrent_interview._SPEAKER_LIMIT.search(sentence), sentence)
        for sentence in ('Treasury monitors the final bank status.', 'We put it on hold.', 'The client does not pay the fee.'):
            self.assertIsNone(concurrent_interview._SPEAKER_LIMIT.search(sentence), sentence)

    def test_the_question_model_is_given_the_unknowns_and_commits_to_one_need_first(self):
        service = self.service()
        self.addCleanup(service.close)
        session = {'capture': None, 'capture_basis': None, 'workflow_capture': None, 'workflow_turns': None}
        model_input = service._question_input(session, {'turns': self.FA07, 'action': 'answer'}, {'process_name': 'Onboarding'}, self.FA07)
        self.assertEqual([row['turn_id'] for row in model_input['known_unknowns']], ['t9', 't9', 't7'])
        schema = concurrent_interview.QUESTION_SCHEMA
        self.assertEqual(list(schema['properties']), ['need', 'question', 'request_review'], 'The need is written before the question')
        self.assertEqual(schema['required'], ['need', 'question', 'request_review'])
        self.assertEqual(concurrent_interview.QUESTION_REPLY_SCHEMA['required'], ['question', 'request_review'])
        policy = concurrent_interview.question_policy(server)
        for wording in ('known_unknowns lists, newest first', 'Fill in need first', 'including the answer just',
                        'is a recorded gap, not a question', 'Never make the records the actor',
                        'names a receiving process, not a person'):
            self.assertIn(wording, policy)

    def test_the_need_is_a_working_note_that_is_neither_spoken_nor_returned(self):
        asked = []
        client = types.SimpleNamespace(agent_models={'lead_interviewer': 'offline-model'},
                                       coordinator=types.SimpleNamespace(interview=lambda value: {'question': 'unused'},
                                                                         workflow=lambda value: {'workflow': {'steps': []}}))
        client.structured = lambda instructions, data, schema, *rest, **options: asked.append((data, schema)) or {
            'need': 'who files the completion record', 'question': 'Who files the completion record?', 'request_review': False}
        api = types.SimpleNamespace(
            APIError=server.APIError, interview_coverage=server.interview_coverage, check_schema=server.check_schema,
            question_rejection=server.question_rejection, record_question_rejection=server.record_question_rejection,
            next_uncovered_question=server.next_uncovered_question, participant_requested_stop=lambda turns, action='answer': False,
            document_reading_summary=server.document_reading_summary,
            validate_payload=lambda value: (value['context'], value['turns']))
        service = concurrent_interview.ConcurrentInterview(client, api)
        self.addCleanup(service.close)
        result = service.turn({'context': {'process_name': 'Onboarding'}, 'turns': copy.deepcopy(self.FA07),
                               '_supporting_documents': {}, 'action': 'answer'})
        self.assertEqual(result['question'], 'Who files the completion record?')
        self.assertNotIn('need', result)
        self.assertNotIn('who files the completion record', json.dumps(result).replace(result['question'], ''))
        self.assertIs(asked[0][1], concurrent_interview.QUESTION_SCHEMA)
        self.assertEqual(len(asked[0][0]['known_unknowns']), 3)


if __name__ == '__main__':
    unittest.main()
