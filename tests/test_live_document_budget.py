"""A Live voice start keeps its composed instructions inside a stated budget.

The document context comes from a real DocumentService over a temporary store.
Offline: the provider request is a Mock and no analysis callback may run.
"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from test_server import server, interview_payload

KEY = 'sk-test-private-budget-sentinel'
SDP = 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'
TOP_LABEL = '\nSUPPORTING DOCUMENT CONTEXT (UNTRUSTED, UNCONFIRMED)\n'
BACKEND_LABEL = '\nINITIAL SUPPORTING DOCUMENT CONTEXT (UNTRUSTED; latest live snapshots may supersede this)\n'
service_module = server.local_module('document_service', 'document_service.py')


def large_csv(rows=1000):
    return ('step,description\n' + ''.join(f'{index},common handling detail {index} ' + 'x' * 200 + '\n'
                                           for index in range(rows))).encode()


def procedure_csv():
    """About 30,000 characters: inside the retrieval cap, so the store returns it whole in document order.
    The rows the conversation is about are at the end."""
    rows = ''.join(f'{index},ordinary handling detail {index} ' + 'x' * 200 + '\n' for index in range(120))
    rows += ''.join(f'{900 + index},ESCALATIONSENTINEL goes to the controller {index} ' + 'y' * 150 + '\n' for index in range(5))
    return ('step,description\n' + rows).encode()


def live_payload(supporting=None, **context):
    payload = interview_payload()
    payload['sdp'] = SDP
    payload['context'].update(context)
    if supporting is not None:
        payload['_supporting_documents'] = supporting
    return payload


def synthetic_context(documents=6, observations=12, excerpts=20):
    files = []
    for number in range(documents):
        identity = f'doc_{number:024d}'
        chunks = [{'id': f'{identity}_r{index}', 'source_id': f'{identity}_r{index}', 'document_id': identity,
                   'name': f'procedure-{number}.csv', 'label': f'procedure-{number}.csv · rows {index}',
                   'text': f'File {number} row {index}: ' + 'documented handling detail ' * 18,
                   'location': {'row': index}, 'row': index} for index in range(excerpts)]
        files.append({'id': identity, 'name': f'procedure-{number}.csv', 'summary': f'Summary of file {number}. ' + 's' * 660,
                      'summary_basis': 'initial_review', 'disposition': 'relevant',
                      'review': {'phase': 'complete', 'review_complete': False, 'reviewed_chunks': excerpts, 'total_chunks': 300,
                                 'indexed_units': 300, 'total_units': 300, 'limitations': ['Two chart sheets were not reviewed.']},
                      'context_coverage': {'included_chunks': excerpts, 'total_chunks': 300, 'complete_text': False,
                                           'selection': 'selected excerpts'},
                      'questions': [],
                      'observations': [{'text': f'File {number} observation {index}: ' + 'o' * 1400,
                                        'sources': [{'source_id': chunks[index]['id'], 'label': chunks[index]['label']}]}
                                       for index in range(observations)],
                      'excerpts': chunks})
    return {'unconfirmed': True, 'notice': 'UNCONFIRMED DOCUMENT CLAIMS. Do not ask the participant to repeat information.',
            'omitted_documents': 2, 'source_versions': [], 'retained_evidence': [], 'omitted_prior_sources': 0,
            'pending_documents': [{'id': 'doc_pending', 'name': 'scan.png', 'status': 'processing', 'source_revision': 'r', 'error': None}],
            'context_budget': {'characters': 60000, 'max_characters': 60000, 'chunks': 120, 'max_chunks': 120}, 'documents': files}


class LiveDocumentBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = server.documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.service = service_module.DocumentService(
            self.store, lambda *args: self.fail('Supporting context must not require a provider request.'))
        self.scope = self.store.create_scope()
        self.client = server.OpenAIClient({'OPENAI_API_KEY': KEY})
        self.client.request = Mock(return_value={'session': {'id': 'live_budget'}, 'transport': {'type': 'webrtc', 'sdp': SDP}})

    def tearDown(self):
        self.service.close()
        self.service._worker.join(timeout=4)
        self.temporary.cleanup()

    def supporting(self, data, name='procedure.csv', query='common handling'):
        record = self.store.add(self.scope, name, data, {})
        self.store.extract(self.scope, record['id'])
        return self.service.supporting_context(self.scope, query)

    def start(self, payload):
        result = self.client.live_session(payload)
        self.client.request.assert_called_once()
        session = self.client.request.call_args.args[1]['session']
        top, delegated = session['instructions'], session['delegation']['responses']['instructions']
        return result, top, delegated, top.split(TOP_LABEL, 1)[1]

    def test_a_file_at_the_retrieval_cap_starts_voice_inside_the_stated_instruction_budget(self):
        supporting = self.supporting(large_csv())
        retrieved = supporting['documents'][0]['excerpts']
        # The store selects whole chunks, so the retrieved text sits just under MAX_SUPPORT_CHARS.
        self.assertGreater(supporting['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS - 6000)
        self.assertFalse(supporting['documents'][0]['context_coverage']['complete_text'])
        self.assertGreater(len(json.dumps(supporting, ensure_ascii=False)), server.LIVE_INSTRUCTION_CHARS)
        result, top, delegated, block = self.start(live_payload(supporting))
        self.assertLessEqual(len(top), server.LIVE_INSTRUCTION_CHARS)
        digest = json.loads(block)
        document = digest['documents'][0]
        originals = {chunk['id']: chunk['text'] for chunk in retrieved}
        self.assertTrue(document['excerpts'], 'The digest keeps exact excerpts, not only a summary')
        for excerpt in document['excerpts']:
            self.assertEqual(excerpt['text'], originals[excerpt['id']], 'Excerpts are whole, never clipped')
        ids = [excerpt['id'] for excerpt in document['excerpts']]
        self.assertEqual(ids, [chunk['id'] for chunk in retrieved if chunk['id'] in ids], 'Retrieval rank order is kept')
        self.assertEqual(ids[0], retrieved[0]['id'])
        self.assertLessEqual(sum(len(excerpt['text']) for excerpt in document['excerpts']), server.LIVE_DOCUMENT_EXCERPT_CHARS)
        self.assertLess(len(ids), len(retrieved))
        coverage = document['context_coverage']
        self.assertEqual((coverage['included_chunks'], coverage['complete_text']), (len(ids), False))
        self.assertIn('live voice digest', coverage['selection'])
        self.assertEqual(coverage['total_chunks'], supporting['documents'][0]['context_coverage']['total_chunks'])
        self.assertEqual(digest['live_voice_digest']['included_excerpts'], len(ids))
        self.assertEqual(digest['live_voice_digest']['retrieved_excerpts'], len(retrieved))
        self.assertEqual(result['document_context'],
                         {'condensed': True, 'included_excerpts': len(ids), 'retrieved_excerpts': len(retrieved)})
        self.assertEqual(len(result['document_evidence']), len(retrieved), 'The browser still receives the full source catalog')

    def test_a_file_read_up_to_a_row_limit_never_reaches_voice_as_complete_text(self):
        # Rows past the limit were never indexed: all of the index is not all of the file.
        with patch.object(server.documents, 'MAX_ROWS', 20):
            supporting = self.supporting(procedure_csv(), query='How is the ESCALATIONSENTINEL handled?')
        coverage = supporting['documents'][0]['context_coverage']
        self.assertTrue(coverage['all_indexed_sections_supplied'])
        self.assertEqual((coverage['complete_text'], coverage['selection']), (False, 'selected excerpts'))
        # Just too large to be sent whole, so it becomes a digest, which has room for every excerpt.
        whole = len(json.dumps({key: value for key, value in supporting.items() if key != 'notice'}, ensure_ascii=False))
        digest, _ = server.live_document_context(supporting, whole - 1)
        entry = digest['documents'][0]
        self.assertEqual(len(entry['excerpts']), len(supporting['documents'][0]['excerpts']), 'Every excerpt fits the digest')
        self.assertEqual((entry['context_coverage']['complete_text'], entry['context_coverage']['selection']),
                         (False, 'live voice digest: selected excerpts only'))

    def test_a_file_inside_the_retrieval_cap_reaches_voice_by_relevance_not_from_its_head(self):
        question = 'How is the ESCALATIONSENTINEL handled?'
        supporting = self.supporting(procedure_csv(), query=question)
        retrieved = supporting['documents'][0]['excerpts']
        self.assertTrue(supporting['documents'][0]['context_coverage']['complete_text'], 'The store returns this file whole')
        self.assertGreater(len(json.dumps(supporting, ensure_ascii=False)), server.LIVE_INSTRUCTION_CHARS)
        matching = [chunk['id'] for chunk in retrieved if 'ESCALATIONSENTINEL' in chunk['text']]
        self.assertEqual(matching, [retrieved[-1]['id']], 'Document order puts the matching rows last')
        payload = live_payload(supporting)
        payload['_document_retrieval'] = {'query': question, 'source_ids': []}
        result, top, delegated, block = self.start(payload)
        ids = [excerpt['id'] for excerpt in json.loads(block)['documents'][0]['excerpts']]
        self.assertLess(len(ids), len(retrieved))
        self.assertEqual(ids[0], matching[0], 'The excerpt that answers the conversation comes first')
        self.assertEqual(ids[1:], [chunk['id'] for chunk in retrieved if chunk['id'] in ids[1:]],
                         'Equally ranked excerpts keep document order')
        self.assertIn('ESCALATIONSENTINEL goes to the controller', top)
        self.assertIn('ESCALATIONSENTINEL goes to the controller', delegated)
        self.assertLessEqual(len(top), server.LIVE_INSTRUCTION_CHARS)
        self.assertEqual(result['document_context']['included_excerpts'], len(ids))
        self.assertEqual([chunk['id'] for chunk in supporting['documents'][0]['excerpts']], [chunk['id'] for chunk in retrieved],
                         'Ranking a digest does not reorder the retrieved context')

    def test_ranking_prefers_cited_sources_then_rare_query_terms_then_retrieval_order(self):
        supporting = synthetic_context(documents=1, observations=0)
        chunks = supporting['documents'][0]['excerpts']
        chunks[17]['text'] = chunks[17]['text'] + ' Escalation goes to the controller.'
        budget = len(json.dumps({key: value for key, value in supporting.items() if key != 'notice'}, ensure_ascii=False)) - 1
        order = lambda retrieval: [excerpt['id'] for excerpt in
                                   server.live_document_context(supporting, budget, retrieval)[0]['documents'][0]['excerpts']]
        plain = order(None)
        self.assertEqual(plain, [chunk['id'] for chunk in chunks][:len(plain)], 'Without a query the retrieval order stands')
        # Every excerpt holds the common words, so they decide nothing; the rare term does.
        ranked = order({'query': 'Which documented handling detail covers ESCALATION?', 'source_ids': []})
        self.assertEqual(ranked, [chunks[17]['id']] + [chunk['id'] for chunk in chunks if chunk is not chunks[17]][:len(ranked) - 1])
        cited = order({'query': 'Which documented handling detail covers escalation?', 'source_ids': [chunks[9]['id'], 'doc_unknown']})
        self.assertEqual(cited[:3], [chunks[9]['id'], chunks[17]['id'], chunks[0]['id']])
        for retrieval in ('escalation', {'query': 17, 'source_ids': 'doc'}, {'query': None, 'source_ids': [3]}, {}):
            self.assertEqual(order(retrieval), plain, 'Anything but the handler\'s own retrieval record is ignored')

    def test_a_digest_without_file_text_does_not_tell_the_interviewer_to_read_the_files(self):
        document = {'id': 'doc_' + '0' * 24, 'name': 'scan-notes.pdf', 'disposition': 'awaiting_review', 'review': {},
                    'context_coverage': {'included_chunks': 2, 'total_chunks': 2, 'complete_text': True, 'selection': 'complete indexed text'},
                    'observations': [],
                    'excerpts': [{'id': f'doc_{"0" * 24}_p{page}', 'label': f'page {page}', 'text': letter * 20000}
                                 for page, letter in ((1, 'A'), (2, 'B'))]}
        supporting = {'unconfirmed': True, 'notice': 'n', 'omitted_documents': 0, 'retained_evidence': [], 'omitted_prior_sources': 0,
                      'pending_documents': [], 'documents': [document]}
        payload = live_payload(supporting)
        payload['turns'] = []
        result = self.client.live_session(payload)
        session = self.client.request.call_args.args[1]['session']
        self.assertEqual(result['document_context'], {'condensed': True, 'included_excerpts': 0, 'retrieved_excerpts': 2})
        greeting = session['input'][-1]['content'][0]['text']
        self.assertEqual((len(session['input']), session['input'][-1]['role']), (1, 'developer'))
        self.assertNotIn('read the supplied document context', greeting)
        self.assertIn('none of their text is in this voice session', greeting)
        self.assertIn('do not say or imply that you have read them', greeting)
        # A digest that holds a summary or an excerpt keeps the document greeting.
        for change in ({'summary': 'The scan describes invoice intake.'}, {'excerpts': [{'id': document['excerpts'][0]['id'], 'label': 'page 1', 'text': 'A' * 20000},
                                                                                         {'id': document['excerpts'][1]['id'], 'label': 'page 2', 'text': 'Short page.'}]}):
            with self.subTest(change=sorted(change)):
                self.client.request.reset_mock()
                payload = live_payload({**supporting, 'documents': [{**document, **change}]})
                payload['turns'] = []
                self.assertTrue(self.client.live_session(payload)['document_context']['condensed'])
                greeting = self.client.request.call_args.args[1]['session']['input'][-1]['content'][0]['text']
                self.assertIn('read the supplied document context', greeting)

    def test_a_first_start_without_files_keeps_the_plain_greeting(self):
        payload = live_payload()
        payload['turns'] = []
        self.client.live_session(payload)
        greeting = self.client.request.call_args.args[1]['session']['input'][-1]['content'][0]['text']
        # The plain greeting names the work when the participant has typed its name.
        self.assertEqual(greeting, server.live_opening(payload['context']))
        self.assertNotIn('Reference files', greeting)
        payload['context'] = {**payload['context'], 'process_name': ''}
        self.client.live_session(payload)
        greeting = self.client.request.call_args.args[1]['session']['input'][-1]['content'][0]['text']
        self.assertIn('What work would you like to walk through together?', greeting)

    def test_the_delegate_receives_the_same_bounded_block_not_the_full_context(self):
        supporting = self.supporting(large_csv())
        _, top, delegated, block = self.start(live_payload(supporting))
        static = server.LIVE_BACKEND_INSTRUCTIONS + server.foundation_instructions()
        self.assertEqual(delegated, static + BACKEND_LABEL + block)
        self.assertEqual(top.count(block), 1)
        sent = {excerpt['id'] for excerpt in json.loads(block)['documents'][0]['excerpts']}
        unsent = [chunk for chunk in supporting['documents'][0]['excerpts'] if chunk['id'] not in sent]
        self.assertTrue(sent and unsent)
        for chunk in unsent:
            self.assertNotIn(json.dumps(chunk['text'], ensure_ascii=False), delegated)
            self.assertNotIn(json.dumps(chunk['text'], ensure_ascii=False), top)
        self.assertLessEqual(len(delegated), len(static) + len(BACKEND_LABEL) + server.LIVE_INSTRUCTION_CHARS)

    def test_a_modest_file_is_sent_whole_with_its_complete_text_coverage(self):
        data = b'topic,account\nidentity,DocumentIdentitySentinel\nclosing,DocumentClosingSentinel\n'
        supporting = self.supporting(data, 'reference.csv', 'identity')
        result, top, delegated, block = self.start(live_payload(supporting))
        self.assertEqual(json.loads(block), {key: value for key, value in supporting.items() if key != 'notice'})
        self.assertTrue(json.loads(block)['documents'][0]['context_coverage']['complete_text'])
        self.assertNotIn('document_context', result)
        self.assertNotIn('live_voice_digest', block)
        self.assertEqual((top.count('DocumentClosingSentinel'), delegated.count('DocumentClosingSentinel')), (1, 1))
        self.assertLessEqual(len(top), server.LIVE_INSTRUCTION_CHARS)

    def test_handling_rules_are_static_instructions_and_the_untrusted_block_holds_only_data(self):
        supporting = self.supporting(large_csv())
        notice = supporting['notice']
        for phrase in ('Do not ask the participant to repeat information already in', 'Never claim full review when coverage is incomplete',
                       'initial_review', 'Retained-only evidence'):
            self.assertIn(phrase, notice, 'The document service notice changed; review LIVE_DOCUMENT_POLICY with it')
            self.assertIn(phrase, ' '.join(server.LIVE_DOCUMENT_POLICY.split()))
        self.assertIn(server.LIVE_DOCUMENT_POLICY, server.LIVE_BASE_INSTRUCTIONS)
        self.assertIn(server.LIVE_DOCUMENT_POLICY, server.LIVE_BACKEND_INSTRUCTIONS)
        self.assertLess(len(server.LIVE_INSTRUCTIONS), 17000)
        _, top, delegated, block = self.start(live_payload(supporting))
        self.assertTrue(top.startswith(server.LIVE_INSTRUCTIONS + '\nPROCESS CONTEXT (UNTRUSTED JSON)\n'))
        untrusted = top[len(server.LIVE_INSTRUCTIONS):]
        for instructions in (untrusted, delegated.split(BACKEND_LABEL, 1)[1]):
            self.assertNotIn('notice', json.loads(instructions.split(TOP_LABEL, 1)[-1]))
            self.assertNotIn('UNCONFIRMED DOCUMENT CLAIMS', instructions)
            self.assertNotIn('Do not ask the participant to repeat', instructions)

    def test_the_longest_plain_intake_context_and_six_reviewed_files_still_fit(self):
        supporting = synthetic_context()
        result, top, delegated, block = self.start(live_payload(
            supporting, process_name='p' * 500, process_owner='o' * 500, objective='j' * 500, background='b' * 8000))
        self.assertLessEqual(len(top), server.LIVE_INSTRUCTION_CHARS)
        digest = json.loads(block)
        self.assertNotIn('notice', digest)
        self.assertEqual(len(digest['documents']) + digest['omitted_documents'] - supporting['omitted_documents'], 6)
        self.assertTrue(digest['documents'])
        observations = {item['text'] for file in supporting['documents'] for item in file['observations']}
        excerpts = {chunk['id']: chunk['text'] for file in supporting['documents'] for chunk in file['excerpts']}
        seen_observations = [item for file in digest['documents'] for item in file['observations']]
        seen_excerpts = [chunk for file in digest['documents'] for chunk in file['excerpts']]
        for item in seen_observations:
            self.assertIn(item['text'], observations, 'Observations are whole')
            self.assertTrue(item['sources'][0]['source_id'].startswith('doc_'), 'Observations keep their source IDs')
        for chunk in seen_excerpts:
            self.assertEqual(chunk['text'], excerpts[chunk['id']])
        self.assertLessEqual(sum(len(item['text']) for item in seen_observations), server.LIVE_DOCUMENT_OBSERVATION_CHARS)
        self.assertLessEqual(sum(len(chunk['text']) for chunk in seen_excerpts), server.LIVE_DOCUMENT_EXCERPT_CHARS)
        for file in digest['documents']:
            self.assertFalse(file['context_coverage']['complete_text'])
            self.assertEqual(file['context_coverage']['included_chunks'], len(file['excerpts']))
        self.assertEqual(digest['pending_documents'], [{'id': 'doc_pending', 'name': 'scan.png', 'status': 'processing'}])
        self.assertTrue(result['document_context']['condensed'])

    def test_generous_room_keeps_every_file_with_summary_observations_and_excerpts(self):
        supporting = synthetic_context()
        _, top, _, block = self.start(live_payload(supporting))
        self.assertLessEqual(len(top), server.LIVE_INSTRUCTION_CHARS)
        digest = json.loads(block)
        self.assertEqual([file['id'] for file in digest['documents']], [file['id'] for file in supporting['documents']])
        self.assertEqual(digest['omitted_documents'], supporting['omitted_documents'])
        for file, original in zip(digest['documents'], supporting['documents']):
            self.assertEqual(file['summary'], original['summary'])
            self.assertEqual(file['summary_basis'], 'initial_review')
            self.assertEqual(file['review']['limitations'], ['Two chart sheets were not reviewed.'])
        self.assertTrue(any(file['observations'] for file in digest['documents']))
        self.assertTrue(any(file['excerpts'] for file in digest['documents']))
        first = [file['excerpts'][0]['id'] for file in digest['documents'] if file['excerpts']]
        self.assertEqual(first, [file['excerpts'][0]['id'] for file in supporting['documents']][:len(first)],
                         'Excerpts are shared across files in turn, best-ranked first')

    def test_every_plain_intake_length_and_file_count_stays_inside_the_budget_without_a_refusal(self):
        for files in (1, 3, 6):
            supporting = synthetic_context(documents=files)
            for background in range(0, 8001, 500):
                with self.subTest(files=files, background=background):
                    self.client.request.reset_mock()
                    result = self.client.live_session(live_payload(supporting, background='b' * background))
                    session = self.client.request.call_args.args[1]['session']
                    self.assertLessEqual(len(session['instructions']), server.LIVE_INSTRUCTION_CHARS)
                    digest = json.loads(session['instructions'].split(TOP_LABEL, 1)[1])
                    self.assertEqual(len(digest['documents']) + digest['omitted_documents'], files + supporting['omitted_documents'])
                    self.assertEqual(digest['live_voice_digest']['included_excerpts'],
                                     sum(len(file['excerpts']) for file in digest['documents']))
                    self.assertEqual(result['document_context']['included_excerpts'], digest['live_voice_digest']['included_excerpts'])

    def test_no_documents_keeps_the_empty_block_and_reports_nothing_condensed(self):
        result, top, delegated, block = self.start(live_payload())
        self.assertEqual(block, '{}')
        self.assertTrue(delegated.endswith(BACKEND_LABEL + '{}'))
        self.assertNotIn('document_context', result)
        self.assertNotIn('document_evidence', result)

    def test_intake_context_that_cannot_fit_is_refused_clearly_before_provider_access(self):
        with self.assertRaisesRegex(ValueError, 'background') as caught:
            self.client.live_session(live_payload(synthetic_context(), background='\x01' * 8000))
        self.assertIn('typing', str(caught.exception))
        self.client.request.assert_not_called()


class LiveDocumentBudgetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.client = server.OpenAIClient({'OPENAI_API_KEY': KEY})
        self.client.request = Mock(return_value={'session': {'id': 'live_http_budget'}, 'transport': {'sdp': SDP}})
        self.client.analyze_document = Mock(side_effect=AssertionError('No document review is requested here.'))
        self.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / 'documents', knowledge_settings={})
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.scope = self.httpd.documents_store.create_scope()
        record = self.httpd.documents_store.add(self.scope, 'procedure.csv', large_csv(), {})
        self.httpd.documents_store.extract(self.scope, record['id'])

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temporary.cleanup()

    def post(self, payload):
        request = urllib.request.Request(f'http://127.0.0.1:{self.httpd.server_port}/api/live-session',
                                         data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json', 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_the_scoped_route_ranks_the_digest_by_its_own_retrieval_query(self):
        store = self.httpd.documents_store
        scope = store.create_scope()
        record = store.add(scope, 'procedure.csv', procedure_csv(), {})
        store.extract(scope, record['id'])
        head = self.httpd.documents.supporting_context(scope, '')['documents'][0]['excerpts'][0]
        self.assertNotIn('ESCALATIONSENTINEL', head['text'])
        payload = live_payload()
        payload['document_scope'] = scope
        payload['turns'] = [{'id': 'a1', 'role': 'assistant', 'text': 'What would you like to cover?'},
                            {'id': 'u1', 'role': 'user', 'text': 'How is the ESCALATIONSENTINEL handled?'}]
        # A client cannot steer the selection: this field is server-owned and dropped from the request.
        payload['_document_retrieval'] = {'query': 'nothing', 'source_ids': [head['id']]}
        status, result = self.post(payload)
        self.assertEqual(status, 200, result)
        self.assertTrue(result['document_context']['condensed'])
        session = self.client.request.call_args.args[1]['session']
        excerpts = json.loads(session['instructions'].split(TOP_LABEL, 1)[1])['documents'][0]['excerpts']
        self.assertIn('ESCALATIONSENTINEL goes to the controller', excerpts[0]['text'])
        self.assertNotEqual(excerpts[0]['id'], head['id'])
        self.assertIn('ESCALATIONSENTINEL goes to the controller', session['delegation']['responses']['instructions'])

    def test_the_scoped_route_bounds_what_the_server_itself_retrieved(self):
        payload = live_payload()
        payload['document_scope'] = self.scope
        status, result = self.post(payload)
        self.assertEqual(status, 200, result)
        self.assertTrue(result['document_context']['condensed'])
        session = self.client.request.call_args.args[1]['session']
        self.assertLessEqual(len(session['instructions']), server.LIVE_INSTRUCTION_CHARS)
        self.assertNotIn(self.scope, json.dumps(session))
        self.assertNotIn(KEY, json.dumps(result))


if __name__ == '__main__':
    unittest.main()
