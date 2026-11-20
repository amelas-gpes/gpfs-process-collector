"""HTTP and provider boundaries for scoped document uploads; no external calls."""
import base64
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from unittest.mock import Mock

from test_server import server, interview_payload, interview_result, fixture_workflow_audit
from test_live import workflow_update_result

KEY = 'sk-synthetic-document-api-sentinel-never-a-real-credential'


def document_result(chunks):
    return {'summary': 'Reference material describes a spreadsheet.', 'acknowledgement': 'I have reviewed the supplied sections.',
            'relevance': 'relevant', 'relevance_reason': 'It relates to intake.', 'question': 'Do you use these fields?',
            'queries': ['invoices'], 'observations': [{'text': 'The file describes invoice fields.', 'sources': [chunks[0]['id']]}],
            'questions': [], 'extracted_text': ''}


class FakeProvider(server.OpenAIClient):
    def __init__(self):
        super().__init__({'OPENAI_API_KEY': KEY})
        self.analysis_calls = []
        self.request = Mock(side_effect=self.upstream)
        # This suite isolates scoped document hydration with its existing fake
        # interviewer. Real coordinator closure is covered by its integration suite.
        self.coordinator.interview = self.interview

    def analyze_document(self, context, record, chunks, phase, store):
        self.analysis_calls.append((context, record['id'], phase))
        return document_result(chunks)

    def upstream(self, path, body, *args, **kwargs):
        name = body['text']['format']['name']
        if name == 'process_next_question_audit':
            value = {'question': json.loads(body['input'][0]['content'])['candidate_question']}
        elif name == 'working_process_map':
            value = workflow_update_result()
            value['title'] = 'Invoice intake'
        elif name == 'working_process_map_audit':
            supplied = json.loads(body['input'][0]['content'])
            value = fixture_workflow_audit(supplied['candidate_update'], supplied['turns'])
        else:
            value = interview_result()
            value['memo_findings'] = [{'key': key, 'status': 'unknown', 'answer': 'UNKNOWN', 'evidence_turns': []} for key in server.COVERAGE]
            value['question'] = 'What work would you like to walk through?' if not json.loads(body['input'][0]['content'])['turns'] else 'What happens after the mailbox check?'
        return {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}


class DocumentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.client = FakeProvider()
        self.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / 'documents')
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, payload=None, headers=None, csrf=True, method=None):
        sent = {'Origin': self.url}
        if csrf:
            sent['X-CSRF-Token'] = self.httpd.csrf_token
        if payload is not None:
            sent['Content-Type'] = 'application/octet-stream' if isinstance(payload, bytes) else 'application/json'
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        else:
            raw = None
        sent.update(headers or {})
        try:
            with urlopen(Request(self.url + path, data=raw, headers=sent, method=method), timeout=3) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def session(self):
        status, _, raw = self.request('/api/documents/session', {'context': {}, 'turns': [], 'current_question': 'Which spreadsheet fields matter?'})
        self.assertEqual(status, 200, raw)
        return json.loads(raw)['scope']

    def upload(self, scope, name='invoice.csv', data=b'invoices,spreadsheet\ninvoices,ReferenceNeedle\n'):
        status, _, raw = self.request('/api/documents/upload', data,
                                     {'X-Document-Scope': scope, 'X-Document-Filename': quote(name, safe='')})
        self.assertEqual(status, 202, raw)
        return json.loads(raw)['document']

    def ready(self, scope, identity):
        # The test exercises the resulting document, not the time taken by
        # the background worker and local SQLite transactions on a busy host.
        end = time.monotonic() + 15
        phase = None
        while time.monotonic() < end:
            record = self.httpd.documents_store.get(scope, identity)
            phase = (record.get('analysis') or {}).get('phase')
            if phase == 'complete':
                return record
            if record.get('status') == 'error' or phase == 'error':
                self.fail('Synthetic background review reported an error.')
            time.sleep(.05)
        self.fail(f'Synthetic background review did not complete. Last phase: {phase!r}.')

    def test_context_endpoint_selects_only_scoped_sources(self):
        scope = self.session()
        record = self.upload(scope)
        self.ready(scope, record['id'])
        code, headers, raw = self.request('/api/documents/context', {'scope': scope, 'query': 'ReferenceNeedle'})
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        catalog = json.loads(raw)['document_evidence']
        self.assertTrue(catalog)
        self.assertTrue(all(row['document_id'] == record['id'] for row in catalog))
        self.assertNotIn(scope, raw.decode())

    def test_every_document_endpoint_requires_current_csrf_and_same_origin(self):
        for endpoint in ('session', 'upload', 'status', 'action', 'source', 'context'):
            for kwargs in ({'csrf': False}, {'headers': {'Origin': 'https://other.example'}},
                           {'headers': {'Host': 'attacker.example'}}):
                with self.subTest(endpoint=endpoint, kwargs=kwargs):
                    status, _, raw = self.request('/api/documents/' + endpoint, {}, **kwargs)
                    self.assertEqual(status, 403)
                    self.assertNotIn(KEY.encode(), raw)
        self.assertEqual(self.client.analysis_calls, [])
        self.client.request.assert_not_called()

    def test_scoped_upload_status_sources_and_encoded_filename_stay_private(self):
        scope = self.session()
        name = 'façade 100% 流程.csv'
        record = self.upload(scope, name)
        self.assertEqual(record['name'], name)
        ready = self.ready(scope, record['id'])
        self.assertEqual(ready['analysis']['disposition'], 'relevant')
        source_id = self.httpd.documents_store.chunks(scope, record['id'])['chunks'][0]['id']
        status, headers, raw = self.request('/api/documents/source', {'scope': scope, 'id': record['id'], 'source_id': source_id})
        self.assertEqual(status, 200)
        self.assertIn('ReferenceNeedle', json.loads(raw)['source']['text'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        for value in (KEY, scope, str(self.temporary.name), '_scope', 'original_path'):
            self.assertNotIn(value, raw.decode())
        status, _, raw = self.request('/api/documents/status', {'scope': scope, 'context': {}, 'turns': []})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['documents'][0]['name'], name)
        for path in ('/documents.sqlite3', '/documents.py', '/work/documents/' + record['id'], '/api/documents/source'):
            self.assertEqual(self.request(path, method='GET')[0], 404)

    def test_cross_scope_status_action_source_and_unknown_scope_cannot_read_originals(self):
        scope, other = self.session(), self.session()
        record = self.upload(scope)
        self.ready(scope, record['id'])
        source = self.httpd.documents_store.chunks(scope, record['id'])['chunks'][0]['id']
        for path, payload in (
            ('/api/documents/action', {'scope': other, 'id': record['id'], 'action': 'remove'}),
            ('/api/documents/source', {'scope': other, 'id': record['id'], 'source_id': source}),
            ('/api/documents/status', {'scope': 'unknown', 'context': {}})):
            status, _, raw = self.request(path, payload)
            self.assertEqual(status, 403)
            if path.endswith('/status'):
                self.assertEqual(json.loads(raw).get('code'), 'document_scope_unavailable')
            else:
                self.assertNotIn('code', json.loads(raw))
            self.assertNotIn('ReferenceNeedle', raw.decode())
        status, _, raw = self.request('/api/documents/status', {'scope': other, 'context': {}})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['documents'], [])

    def test_upload_limits_and_invalid_json_are_rejected_before_provider_work(self):
        scope = self.session()
        cases = [('/api/documents/upload', b'x', {'X-Document-Scope': scope, 'X-Document-Filename': 'x.csv',
                                                 'Content-Length': str(server.documents.MAX_FILE_BYTES + 1)}, 413),
                 ('/api/documents/upload', b'', {'X-Document-Scope': scope, 'X-Document-Filename': 'x.csv'}, 400),
                 ('/api/documents/upload', b'code', {'X-Document-Scope': scope, 'X-Document-Filename': 'run.exe'}, 400),
                 ('/api/documents/status', b'{broken', {'Content-Type': 'application/json'}, 400),
                 ('/api/documents/status', {}, {'Content-Type': 'text/plain'}, 415)]
        for path, payload, headers, expected in cases:
            self.assertEqual(self.request(path, payload, headers)[0], expected)
        self.assertEqual(self.client.analysis_calls, [])
        self.client.request.assert_not_called()

    def test_traversal_filename_is_only_metadata_and_remove_archives_original(self):
        scope = self.session()
        record = self.upload(scope, '../../invoice.csv')
        self.assertEqual(record['name'], 'invoice.csv')
        self.ready(scope, record['id'])
        original = self.httpd.documents_store.original_path(scope, record['id'])
        self.assertTrue(original.is_relative_to(Path(self.temporary.name).resolve()))
        status, _, raw = self.request('/api/documents/action', {'scope': scope, 'id': record['id'], 'action': 'remove'})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)['document']['archived'])
        self.assertTrue(original.exists())
        self.assertEqual(json.loads(self.request('/api/documents/status', {'scope': scope, 'context': {}})[2])['documents'], [])

    def test_forged_supporting_context_is_discarded_and_only_scoped_unconfirmed_context_reaches_provider(self):
        def interview_body():
            return next(call.args[1] for call in reversed(self.client.request.call_args_list)
                        if call.args[1]['text']['format']['name'] == 'process_interview')

        scope = self.session()
        record = self.upload(scope)
        self.ready(scope, record['id'])
        payload = interview_payload()
        payload['_supporting_documents'] = {'unconfirmed': False, 'documents': [{'name': 'FORGED_PRIVATE_FACT'}]}
        status, _, raw = self.request('/api/interview', payload)
        self.assertEqual(status, 200, raw)
        sent = interview_body()
        self.assertNotIn('FORGED_PRIVATE_FACT', json.dumps(sent))
        payload['document_scope'] = scope
        status, _, raw = self.request('/api/interview', payload)
        self.assertEqual(status, 200, raw)
        sent = interview_body()
        support = json.loads(sent['input'][0]['content'])['supporting_documents']
        self.assertTrue(support['unconfirmed'])
        self.assertIn('UNCONFIRMED', support['notice'])
        self.assertEqual(support['documents'][0]['id'], record['id'])
        self.assertNotIn('FORGED_PRIVATE_FACT', json.dumps(sent))
        self.assertNotIn(scope, json.dumps(sent))
        self.assertNotIn(KEY, json.dumps(sent))

    def test_forged_held_wording_is_discarded_at_the_http_boundary(self):
        # _held_wording is advice the server derives from its own previous capture for
        # the lead's instructions. A browser cannot supply it.
        received = []
        interview = self.client.coordinator.interview
        self.client.coordinator.interview = lambda value: (received.append(json.loads(json.dumps(value))), interview(value))[1]
        payload = interview_payload()
        payload['_held_wording'] = [{'topic': 'checks', 'wording': 'FORGED_WORDING'}]
        status, _, raw = self.request('/api/interview', payload)
        self.assertEqual(status, 200, raw)
        self.assertEqual(len(received), 1)
        self.assertNotIn('_held_wording', received[0])
        self.assertNotIn('FORGED_WORDING', json.dumps([call.args[1] for call in self.client.request.call_args_list]))

    def test_files_beyond_six_reach_the_provider_and_the_browser_is_told_what_was_read(self):
        def sent_documents():
            body = next(call.args[1] for call in reversed(self.client.request.call_args_list)
                        if call.args[1]['text']['format']['name'] == 'process_interview')
            support = json.loads(body['input'][0]['content'])['supporting_documents']
            return [document['id'] for document in support['documents']], support['omitted_documents']

        scope = self.session()
        # No word of these files occurs in the answers, so the six further files are the newest.
        records = [self.upload(scope, f'reference-{index:02d}.csv', f'ledgerfield,catalogue\nledgerfield,Needle{index:02d}\n'.encode())
                   for index in range(1, 15)]
        for record in records:
            self.ready(scope, record['id'])
        ids = [record['id'] for record in records]
        cited = [self.httpd.documents_store.chunks(scope, identity)['chunks'][0]['id'] for identity in ids[:6]]
        payload = interview_payload()
        payload.update(document_scope=scope, document_source_ids=cited)
        # Six cited files no longer keep the newest uploads away from the model.
        status, _, raw = self.request('/api/interview', payload)
        self.assertEqual(status, 200, raw)
        sent, omitted = sent_documents()
        self.assertEqual(set(sent), {*ids[:6], *ids[8:]})
        self.assertEqual(omitted, 2)
        reading = json.loads(raw)['document_reading']
        self.assertEqual(reading['omitted_documents'], 2)
        self.assertEqual({item['id'] for item in reading['documents']}, set(sent))
        for item in reading['documents']:
            self.assertEqual((item['included_chunks'], item['total_chunks']), (1, 1))
        self.assertNotIn('Needle', json.dumps(reading))
        # The browser names the two files it has not received yet; they are read as well.
        payload['document_required_ids'] = [ids[6], ids[7], 'doc_unknown', 'not-a-document']
        status, _, raw = self.request('/api/interview', payload)
        self.assertEqual(status, 200, raw)
        sent, omitted = sent_documents()
        self.assertEqual((set(sent), omitted), (set(ids), 0))
        reading = json.loads(raw)['document_reading']
        self.assertEqual((len(reading['documents']), reading['omitted_documents']), (14, 0))
        status, _, raw = self.request('/api/documents/context', {'scope': scope, 'query': 'An ordinary answer.',
                                                                 'document_source_ids': cited, 'document_required_ids': [ids[6]]})
        self.assertEqual(status, 200, raw)
        self.assertEqual({item['id'] for item in json.loads(raw)['documents']}, {*ids[:7], *ids[8:]})
        calls = self.client.request.call_count
        for invalid in ('doc_one', ['doc_x'] * 21):
            payload['document_required_ids'] = invalid
            status, _, raw = self.request('/api/interview', payload)
            self.assertEqual(status, 400, raw)
        self.assertEqual(self.client.request.call_count, calls)
        # A request without a file scope carries no reading disclosure.
        status, _, raw = self.request('/api/interview', interview_payload())
        self.assertEqual(status, 200, raw)
        self.assertNotIn('document_reading', json.loads(raw))

    def test_long_interview_answer_with_document_scope_does_not_exceed_retrieval_query_bound(self):
        scope = self.session()
        record = self.upload(scope)
        self.ready(scope, record['id'])
        payload = interview_payload()
        payload['document_scope'] = scope
        payload['turns'][-1]['text'] = 'invoices ' * 400
        status, _, raw = self.request('/api/interview', payload)
        self.assertEqual(status, 200, raw)

    def test_unnamed_interview_and_generated_workflow_title_are_accepted_without_form_gate(self):
        status, _, raw = self.request('/api/interview', {'context': {}, 'turns': [], 'action': 'start'})
        self.assertEqual(status, 200, raw)
        sent = self.client.request.call_args.args[1]
        self.assertEqual(json.loads(sent['input'][0]['content'])['context']['process_name'], '')
        self.assertIn('infer a concise name', sent['instructions'])
        payload = interview_payload()
        payload['context']['process_name'] = ''
        status, _, raw = self.request('/api/workflow', payload)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['workflow']['title'], 'Invoice intake')


class NativeDocumentProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = server.documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()
        self.client = server.OpenAIClient({'OPENAI_API_KEY': KEY})
        self.client.request = Mock(side_effect=self.response)

    def tearDown(self):
        self.temporary.cleanup()

    def response(self, path, body, *args, **kwargs):
        content = body['input'][0]['content']
        payload = json.loads(content[0]['text'] if isinstance(content, list) else content)
        result = document_result(payload['chunks'])
        return {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(result)}]}]}

    def analyze(self, name, data, purpose=None):
        record = self.store.add(self.scope, name, data)
        record = self.store.extract(self.scope, record['id'])
        if purpose:
            record['analysis'] = {'purpose': purpose, 'purpose_attempted': True}
        record['_scope'] = self.scope
        chunks = self.store.chunks(self.scope, record['id'])['chunks']
        result = self.client.analyze_document({'current_question': 'What happens next?'}, record, chunks, 'quick', self.store)
        path, body = self.client.request.call_args.args
        self.assertEqual(path, 'responses')
        self.assertFalse(body['store'])
        self.assertNotIn('tools', body)
        self.assertNotIn(KEY, json.dumps(body))
        self.assertNotIn(self.scope, json.dumps(body))
        self.assertNotIn(str(self.temporary.name), json.dumps(body))
        self.assertNotIn('file_id', json.dumps(body))
        return record, chunks, result, body

    def test_plain_spreadsheet_context_uses_exact_source_enums_and_supplied_purpose(self):
        purpose = 'This is the currently used invoice intake tracker.'
        record, chunks, result, body = self.analyze('intake.csv', b'invoices,field\na,1\n', purpose)
        self.assertIsInstance(body['input'][0]['content'], str)
        payload = json.loads(body['input'][0]['content'])
        self.assertEqual(payload['file']['purpose'], purpose)
        for field in ('observations', 'questions'):
            allowed = body['text']['format']['schema']['properties'][field]['items']['properties']['sources']['items']['enum']
            self.assertEqual(allowed, [chunk['id'] for chunk in chunks])
        self.assertEqual(body['text']['format']['schema']['properties']['queries']['items'], {'type': 'string'})

    def test_text_only_batches_forbid_visual_transcription_and_bound_cited_sources(self):
        _, chunks, _, body = self.analyze('text-only.csv', b'invoices,field\na,1\n')
        schema = body['text']['format']['schema']
        self.assertEqual(schema['properties']['extracted_text'], {'type': 'string', 'enum': ['']})
        for name in ('observations', 'questions'):
            sources = schema['properties'][name]['items']['properties']['sources']
            self.assertEqual(sources['minItems'], 1)
            self.assertEqual(sources['maxItems'], 8)
            self.assertEqual(sources['items']['enum'], [chunk['id'] for chunk in chunks])
        self.assertEqual(server.DOCUMENT_ANALYSIS_SCHEMA['properties']['extracted_text'], {'type': 'string'})

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Existing Pillow runtime required')
    def test_png_uses_inline_native_image_only_and_no_private_capability_or_remote_upload(self):
        from PIL import Image
        data = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(data, format='PNG')
        _, chunks, _, body = self.analyze('diagram.png', data.getvalue())
        content = body['input'][0]['content']
        image = next(item for item in content if item['type'] == 'input_image')
        self.assertTrue(image['image_url'].startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(image['image_url'].split(',', 1)[1]), data.getvalue())
        self.assertEqual(json.loads(content[0]['text'])['visual_source_id'], chunks[0]['id'])
        self.client.request.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing PDF runtime required')
    def test_pdf_native_input_is_only_the_requested_page_with_its_exact_source(self):
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=100, height=100)
        data = io.BytesIO()
        writer.write(data)
        record = self.store.add(self.scope, 'scan.pdf', data.getvalue())
        record = self.store.extract(self.scope, record['id'])
        record['_scope'] = self.scope
        chunk = self.store.chunks(self.scope, record['id'], offset=2, limit=1)['chunks'][0]
        self.client.analyze_document({}, record, [chunk], 'deep', self.store)
        body = self.client.request.call_args.args[1]
        native = [item for item in body['input'][0]['content'] if item['type'] == 'input_file']
        self.assertEqual(len(native), 1)
        raw = base64.b64decode(native[0]['file_data'].split(',', 1)[1])
        self.assertEqual(len(PdfReader(io.BytesIO(raw)).pages), 1)
        self.assertEqual(json.loads(body['input'][0]['content'][0]['text'])['visual_source_id'], chunk['id'])
        self.assertFalse(body['store'])
        self.assertNotIn(KEY, json.dumps(body))
        self.assertNotIn(self.scope, json.dumps(body))
        self.client.request.assert_called_once()

    def test_empty_chunk_review_never_calls_provider_or_claims_readable_content(self):
        result = self.client.analyze_document({}, {}, [], 'quick', self.store)
        self.assertEqual(result['relevance'], 'unclear')
        self.assertEqual(result['observations'], [])
        self.client.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
