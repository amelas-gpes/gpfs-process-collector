"""Real loopback/source retrieval across delayed review and cached confirmation."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from test_interview_orchestrator import REVIEW_CALLS, SyntheticTeamProvider
from test_server import server


class ReviewSourceHydrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='collector-review-source-')
        self.client = SyntheticTeamProvider()
        self.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=self.client,
            documents_root=Path(self.temp.name) / 'documents', knowledge_root=Path(self.temp.name) / 'knowledge')
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        store = self.httpd.documents_store
        self.scope = store.create_scope()
        rows = ['topic,detail'] + [f'row{i},Invoice evidence material risk reference {i} ' + 'documented facts ' * 20 for i in range(1000)]
        record = store.add(self.scope, 'fictional-large-reference.csv', '\n'.join(rows).encode())
        self.document_id = record['id']
        store.extract(self.scope, self.document_id)
        store.update(self.scope, self.document_id, {'analysis': {
            'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'summary': 'Fictional documentary reference.'}})
        self.hydrate = Mock(wraps=self.httpd.documents.supporting_context)
        self.httpd.documents.supporting_context = self.hydrate

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def post(self, route, payload):
        request = Request(self.url + route, data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json', 'Origin': self.url, 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def prepare(self):
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        code, prepared = self.post('/api/interview', payload)
        self.assertEqual(code, 200, prepared)
        self.assertEqual(prepared['speech_authorization']['kind'], 'review_pending')
        payload['turns'].append({'id': 'review_ack', 'role': 'assistant', 'text': prepared['question']})
        payload.update(capture_token=prepared['capture_token'], review_ticket=prepared['review_ticket'])
        return payload, prepared

    def test_large_source_selection_stays_bound_through_ack_and_zero_call_confirmation(self):
        payload, prepared = self.prepare()
        initial_query = self.hydrate.call_args.args[1]
        self.assertEqual(self.client.request.call_count, 1)
        code, reviewed = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 200, reviewed)
        self.assertEqual(reviewed['speech_authorization']['kind'], 'final_check')
        self.assertEqual(self.hydrate.call_args.args[1], initial_query)
        self.assertTrue(self.hydrate.call_args.kwargs['source_ids'])
        self.assertEqual(self.client.request.call_count, 1 + REVIEW_CALLS)
        payload.pop('review_ticket')
        payload['capture_token'] = reviewed['capture_token']
        payload['turns'] += [{'id': 'global_check', 'role': 'assistant', 'text': reviewed['question']},
                            {'id': 'confirmation', 'role': 'user', 'text': "No, that's everything."}]
        code, completed = self.post('/api/interview', payload)
        self.assertEqual(code, 200, completed)
        self.assertTrue(completed['completion']['complete'])
        self.assertEqual(self.client.request.call_count, 1 + REVIEW_CALLS)
        self.assertEqual(self.hydrate.call_args.args[1], initial_query)

    def test_selection_of_more_than_six_files_stays_bound_through_review_and_confirmation(self):
        store = self.httpd.documents_store
        extra = []
        for index in range(8):
            record = store.add(self.scope, f'fictional-extra-{index}.csv', f'field,value\nextraword{index},{index}\n'.encode())
            store.extract(self.scope, record['id'])
            store.update(self.scope, record['id'], {'analysis': {
                'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'summary': 'Fictional extra reference.'}})
            extra.append(record['id'])
        selections = []
        def recording(*args, **kwargs):
            value = self.hydrate(*args, **kwargs)
            selections.append((kwargs, sorted(item['id'] for item in value['documents']), value['omitted_documents']))
            return value
        self.httpd.documents.supporting_context = recording
        payload = self.client.payload()
        # The browser has not received the oldest extra file yet and asks for it.
        payload.update(document_scope=self.scope, document_required_ids=[extra[0]])
        code, prepared = self.post('/api/interview', payload)
        self.assertEqual(code, 200, prepared)
        self.assertEqual(prepared['speech_authorization']['kind'], 'review_pending')
        chosen = selections[0][1]
        # The file asked for, the large reference and the five newest extras: seven files, two left out.
        self.assertEqual(chosen, sorted([self.document_id, extra[0], *extra[3:]]))
        self.assertEqual(selections[0][2], 2)
        self.assertEqual(prepared['document_reading']['omitted_documents'], 2)
        self.assertEqual(sorted(item['id'] for item in prepared['document_reading']['documents']), chosen)
        self.assertTrue(all(kwargs.get('required_documents') == [extra[0]] and 'frozen' not in kwargs
                            for kwargs, _, _ in selections))
        payload['turns'].append({'id': 'review_ack', 'role': 'assistant', 'text': prepared['question']})
        payload.update(capture_token=prepared['capture_token'], review_ticket=prepared['review_ticket'])
        # Later requests no longer ask for the file: the browser has received it by now.
        payload.pop('document_required_ids')
        before = len(selections)
        code, reviewed = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 200, reviewed)
        self.assertEqual(reviewed['speech_authorization']['kind'], 'final_check')
        payload.pop('review_ticket')
        payload['capture_token'] = reviewed['capture_token']
        payload['turns'] += [{'id': 'global_check', 'role': 'assistant', 'text': reviewed['question']},
                            {'id': 'confirmation', 'role': 'user', 'text': "No, that's everything."}]
        calls = self.client.request.call_count
        code, completed = self.post('/api/interview', payload)
        self.assertEqual(code, 200, completed)
        self.assertTrue(completed['completion']['complete'])
        self.assertEqual(self.client.request.call_count, calls)
        # The review and the confirmation replayed the capture's seven files; the two left out did not join.
        self.assertGreater(len(selections), before)
        for kwargs, documents, omitted in selections[before:]:
            self.assertEqual((kwargs.get('frozen'), documents, omitted), (True, chosen, 2))
            self.assertNotIn('required_documents', kwargs)

    def test_followup_for_a_seventh_file_reads_it_although_the_earlier_capture_pinned_six(self):
        store = self.httpd.documents_store
        def add(index):
            record = store.add(self.scope, f'fictional-extra-{index}.csv', f'field,value\nextraword{index},{index}\n'.encode())
            store.extract(self.scope, record['id'])
            store.update(self.scope, record['id'], {'analysis': {
                'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'summary': 'Fictional extra reference.'}})
            return record['id']
        shown = []
        def record_documents(body):
            sent = json.loads(body['input'][0]['content'])
            shown.append(sorted(item['id'] for item in sent['supporting_documents']['documents']))
        self.client.hooks['team_interview_capture'] = record_documents
        earlier = [self.document_id, *(add(index) for index in range(5))]
        payload = self.client.payload()
        payload.update(document_scope=self.scope, action='document_followup', previous_capture={}, document_required_ids=earlier)
        code, first = self.post('/api/interview', payload)
        self.assertEqual(code, 200, first)
        self.assertEqual(shown[-1], sorted(earlier))
        # A seventh file is reviewed. Its intake asks for a follow-up on the same transcript, holding the
        # earlier capture, which was shown six files.
        seventh = add(5)
        payload.update(capture_token=first['capture_token'], document_required_ids=[seventh])
        self.assertIsNotNone(self.client.coordinator.retrieval_basis(payload))
        code, second = self.post('/api/interview', payload)
        self.assertEqual(code, 200, second)
        self.assertEqual(shown[-1], sorted([*earlier, seventh]))
        self.assertEqual(second['document_reading']['omitted_documents'], 0)
        self.assertIn(seventh, [item['id'] for item in second['document_reading']['documents']])
        self.assertTrue(any(item['document_id'] == seventh for item in second['document_evidence']))

    def large(self, name, word):
        """One reviewed file of three sections of about 5,800 characters each."""
        store = self.httpd.documents_store
        data = ('step,detail\n' + ''.join(f'{row},{word} handling detail {"x" * 930}\n' for row in range(18))).encode()
        record = store.add(self.scope, name, data)
        store.extract(self.scope, record['id'])
        store.update(self.scope, record['id'], {'analysis': {
            'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'summary': 'Fictional extra reference.'}})
        return record['id']

    def record_selections(self):
        selections = []
        def recording(*args, **kwargs):
            value = self.hydrate(*args, **kwargs)
            selections.append((kwargs, {item['id']: len(item['excerpts']) for item in value['documents']},
                               value['omitted_documents'], value['context_budget']))
            return value
        self.httpd.documents.supporting_context = recording
        return selections

    def test_review_and_confirmation_keep_a_selected_file_that_the_limit_left_without_an_excerpt(self):
        store = self.httpd.documents_store
        store.archive(self.scope, self.document_id)
        cited = [self.large(f'fictional-cited-{index}.csv', f'cited{index}') for index in range(2)]
        idle = [self.large(f'fictional-idle-{index}.csv', f'idle{index}') for index in range(6)]
        pins = [chunk['id'] for identity in cited for chunk in store.chunks(self.scope, identity)['chunks']]
        selections = self.record_selections()
        payload = self.client.payload()
        # Eight files. The browser has received all of them, so it asks for none by name; its notes
        # cite six sections of two files, about 35,000 of the 60,000 characters one request can read.
        payload.update(document_scope=self.scope, document_source_ids=pins)
        code, prepared = self.post('/api/interview', payload)
        self.assertEqual(code, 200, prepared)
        self.assertEqual(prepared['speech_authorization']['kind'], 'review_pending')
        files = selections[0][1]
        self.assertEqual(set(files), {*cited, *idle})
        self.assertEqual(selections[0][2], 0)
        # One opening section for each further file no longer fits: the last files were selected without text.
        starved = sorted(identity for identity, count in files.items() if not count)
        self.assertTrue(starved)
        self.assertEqual(sorted(item['id'] for item in prepared['document_reading']['documents']
                                if not item['included_chunks']), starved)
        payload['turns'].append({'id': 'review_ack', 'role': 'assistant', 'text': prepared['question']})
        payload.update(capture_token=prepared['capture_token'], review_ticket=prepared['review_ticket'])
        before = len(selections)
        code, reviewed = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 200, reviewed)
        self.assertEqual(reviewed['speech_authorization']['kind'], 'final_check')
        payload.pop('review_ticket')
        payload['capture_token'] = reviewed['capture_token']
        payload['turns'] += [{'id': 'global_check', 'role': 'assistant', 'text': reviewed['question']},
                             {'id': 'confirmation', 'role': 'user', 'text': "No, that's everything."}]
        calls = self.client.request.call_count
        code, completed = self.post('/api/interview', payload)
        self.assertEqual(code, 200, completed)
        self.assertTrue(completed['completion']['complete'])
        self.assertEqual(self.client.request.call_count, calls)
        # The review and the confirmation were given the capture's own files, also those without an excerpt.
        self.assertGreater(len(selections), before)
        for kwargs, replayed, omitted, _ in selections[before:]:
            self.assertEqual((kwargs.get('frozen'), replayed, omitted), (True, files, 0))
            self.assertEqual(sorted(kwargs['selected_documents']), sorted(files))

    def test_a_review_of_such_a_selection_is_still_refused_when_one_of_its_files_is_removed(self):
        store = self.httpd.documents_store
        store.archive(self.scope, self.document_id)
        cited = [self.large(f'fictional-cited-{index}.csv', f'cited{index}') for index in range(2)]
        for index in range(6):
            self.large(f'fictional-idle-{index}.csv', f'idle{index}')
        pins = [chunk['id'] for identity in cited for chunk in store.chunks(self.scope, identity)['chunks']]
        selections = self.record_selections()
        payload = self.client.payload()
        payload.update(document_scope=self.scope, document_source_ids=pins)
        code, prepared = self.post('/api/interview', payload)
        self.assertEqual(code, 200, prepared)
        starved = [identity for identity, count in selections[0][1].items() if not count]
        self.assertTrue(starved)
        payload['turns'].append({'id': 'review_ack', 'role': 'assistant', 'text': prepared['question']})
        payload.update(capture_token=prepared['capture_token'], review_ticket=prepared['review_ticket'])
        # The removed file gave the capture no excerpt; it was still one of the files of that account.
        store.archive(self.scope, starved[0])
        calls = self.client.request.call_count
        code, result = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, result)
        self.assertEqual(self.client.request.call_count, calls)
        self.assertNotIn('speech_authorization', result)

    def test_followup_for_a_new_file_reads_it_although_the_held_capture_filled_the_reading_limit(self):
        shown = []
        def record_documents(body):
            sent = json.loads(body['input'][0]['content'])
            shown.append({item['id']: len(item['excerpts']) for item in sent['supporting_documents']['documents']})
        self.client.hooks['team_interview_capture'] = record_documents
        selections = self.record_selections()
        payload = self.client.payload()
        payload.update(document_scope=self.scope, action='document_followup', previous_capture={},
                       document_required_ids=[self.document_id])
        code, first = self.post('/api/interview', payload)
        self.assertEqual(code, 200, first)
        # The long reference file filled what one request can read; none of it is cited yet.
        budget = selections[0][3]
        new = self.large('fictional-new-checklist.csv', 'checklist')
        sections = [len(chunk['text']) for chunk in self.httpd.documents_store.chunks(self.scope, new)['chunks']]
        self.assertLess(budget['max_characters'] - budget['characters'], min(sections))
        # The new file's intake asks for its follow-up on the same transcript, holding that capture.
        payload.update(capture_token=first['capture_token'], document_required_ids=[new])
        self.assertIsNotNone(self.client.coordinator.retrieval_basis(payload))
        before = len(selections)
        code, second = self.post('/api/interview', payload)
        self.assertEqual(code, 200, second)
        self.assertGreater(shown[-1][new], 0)
        reading = {item['id']: item for item in second['document_reading']['documents']}
        self.assertGreater(reading[new]['included_chunks'], 0)
        self.assertTrue(any(item['document_id'] == new for item in second['document_evidence']))
        self.assertGreater(shown[-1][self.document_id], 0)
        # It is a new reading that names the file, not a replay of the excerpts the capture was shown.
        self.assertGreater(len(selections), before)
        for kwargs, _, _, _ in selections[before:]:
            self.assertEqual(kwargs.get('required_documents'), [new])
            self.assertNotIn('frozen', kwargs)

    def test_archiving_source_invalidates_prepared_review_before_provider_work(self):
        payload, _ = self.prepare()
        self.httpd.documents_store.archive(self.scope, self.document_id)
        code, result = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, result)
        self.assertEqual(self.client.request.call_count, 1)
        self.assertNotIn('speech_authorization', result)

    def test_ticket_cannot_authorize_a_different_document_scope(self):
        payload, _ = self.prepare()
        payload['document_scope'] = self.httpd.documents_store.create_scope()
        code, result = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, result)
        self.assertEqual(self.client.request.call_count, 1)

    def test_ordinary_turn_pins_private_fact_sources_without_browser_memo(self):
        # The coordinator supplies only citation IDs; the current scoped store
        # still loads their content. Neither the browser nor private metadata
        # can inject an excerpt or evade the HTTP release recheck.
        inventory = self.httpd.documents_store.chunks(self.scope, self.document_id, limit=1)
        source = self.httpd.documents_store.chunks(
            self.scope, self.document_id, offset=max(0, inventory['total'] - 2), limit=1)['chunks'][0]
        self.client.coordinator.fact_source_ids = Mock(return_value=[source['id']])
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        self.assertNotIn('previous_capture', payload)
        code, result = self.post('/api/interview', payload)
        self.assertEqual(code, 200, result)
        self.client.coordinator.fact_source_ids.assert_called_once()
        self.assertGreaterEqual(self.hydrate.call_count, 2)
        for call in self.hydrate.call_args_list:
            self.assertEqual(call.kwargs['source_ids'][0], source['id'])
        self.assertTrue(any(item['id'] == source['id'] and item['text'] == source['text']
                            for item in result['document_evidence']))

    def test_private_fact_source_preference_cannot_cross_document_scopes(self):
        source = self.httpd.documents_store.chunks(self.scope, self.document_id, limit=1)['chunks'][0]
        self.client.coordinator.fact_source_ids = Mock(return_value=[source['id']])
        payload = self.client.payload()
        payload['document_scope'] = self.httpd.documents_store.create_scope()
        code, result = self.post('/api/interview', payload)
        self.assertEqual(code, 200, result)
        self.assertFalse(result.get('document_evidence'))

    def test_source_archived_during_review_cannot_release_final_check_or_cached_permit(self):
        payload, prepared = self.prepare()
        self.client.hooks['process_specialist_review'] = lambda body: self.httpd.documents_store.archive(self.scope, self.document_id)
        code, result = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, result)
        self.assertNotIn('speech_authorization', result)
        self.assertTrue(self.client.coordinator.status(prepared['agent_run_id'])['cancelled'])
        calls = self.client.request.call_count
        code, replay = self.post('/api/agent-team/review', payload)
        self.assertEqual(code, 409, replay)
        self.assertEqual(self.client.request.call_count, calls)

    def test_new_pending_document_during_capture_withholds_old_response(self):
        def add_source(body):
            self.httpd.documents_store.add(self.scope, 'new-reference.csv', b'event,status\nchanged,pending')
        self.client.hooks['team_interview_capture'] = add_source
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        code, result = self.post('/api/interview', payload)
        self.assertEqual(code, 409, result)
        self.assertNotIn('speech_authorization', result)

    def test_source_archived_during_draft_withholds_stale_export(self):
        def make_draft(payload):
            self.httpd.documents_store.archive(self.scope, self.document_id)
            return {'draft': {'title': 'Stale draft must never be released'}}
        self.client.draft = Mock(side_effect=make_draft)
        payload = self.client.payload()
        payload['document_scope'] = self.scope
        code, result = self.post('/api/draft', payload)
        self.assertEqual(code, 409, result)
        self.assertNotIn('draft', result)


if __name__ == '__main__':
    unittest.main()
