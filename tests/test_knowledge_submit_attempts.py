"""One process submission at the HTTP boundary and in the store.

What the Submit dialog relies on: a body that carries only file IDs, a size limit that matches the
store's and a refusal the browser can read (data-pipeline-2); a refusal that says when nothing was
saved under the submission key, and recovery that comes before the revision check (knowledge-frontend-3);
the same interview arriving again without a process ID (gap3-two-tabs-4).
Loopback HTTP and temporary SQLite only; no provider and no external network.
"""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server
import knowledge_rows as rows
from test_knowledge_graph import kg, wait

KEY = '11111111-1111-4111-8111-%012d'
INTERVIEW = '22222222-2222-4222-8222-%012d'


def submission(answers=1, text='Answer {} describes one part of the work.', **changes):
    turns = []
    for number in range(1, answers + 1):
        turns.append({'id': f't{2 * number - 1:03d}', 'role': 'assistant', 'text': f'Question {number}?'})
        turns.append({'id': f't{2 * number:03d}', 'role': 'user', 'text': text.format(number)})
    result = {'context': {'process_name': 'Invoice intake'}, 'turns': turns, 'draft': None,
              'workflow': {'title': 'Invoice intake', 'steps': [{'id': 'S1', 'title': 'Receive invoice', 'evidence_turns': ['t002']}],
                           'connections': []},
              'memo_findings': []}
    result.update(changes)
    return result


class SubmitRouteCase(unittest.TestCase):
    settings = {'COLLECTOR_DEPLOYMENT_MODE': 'local', 'KNOWLEDGE_LOCAL_OWNER': 'true'}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.httpd = server.InterviewServer(
            ('127.0.0.1', 0), server.Handler, client=server.OpenAIClient({}),
            documents_root=Path(self.temp.name) / 'documents', knowledge_root=Path(self.temp.name) / 'graph',
            knowledge_settings=dict(self.settings))
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.store = self.httpd.documents_store

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def post(self, path, body, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        request = Request(f'http://127.0.0.1:{self.httpd.server_port}' + path, data=data,
                          headers={'Content-Type': 'application/json', 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def submissions(self):
        return rows.submissions(self.httpd.knowledge)

    def detail(self, receipt):
        with self.httpd.knowledge.lock:
            return self.httpd.knowledge._revision(receipt['submission_id'], receipt['revision'])


class SubmissionSizeTests(SubmitRouteCase):
    """data-pipeline-2."""

    def reviewed_file(self, scope, number):
        """A file whose background review reached its cap: the record the browser holds is over 100 KB."""
        record = self.store.add(scope, f'procedure-{number}.csv', f'step,rule\n{number},Check invoice {number} against the order\n'.encode())
        self.store.extract(scope, record['id'])
        source = self.store.chunks(scope, record['id'])['chunks'][0]
        observations = [{'text': f'Observation {index} of file {number}: ' + 'detail ' * 90, 'source_ids': [source['id']]} for index in range(200)]
        self.store.update(scope, record['id'], {'analysis': {
            'phase': 'complete', 'disposition': 'relevant', 'intent_version': 1, 'version': 3, 'observations': observations,
            'sources': [{'source_id': source['id'], 'label': source['label']}]}})
        return record['id'], source

    def test_submission_with_several_fully_reviewed_files_needs_only_their_ids(self):
        scope = self.store.create_scope()
        files = [self.reviewed_file(scope, number) for number in range(1, 6)]
        records = [self.store.get(scope, document_id) for document_id, _ in files]
        steps = [{'id': f'S{index}', 'title': f'Check {index}', 'evidence_turns': [source['id'], 't002']} for index, (_, source) in enumerate(files, 1)]
        body = submission(workflow={'title': 'Invoice intake', 'steps': steps, 'connections': []})
        whole = {**body, 'documents': {'scope': scope, 'documents': records}}
        self.assertGreater(len(json.dumps(whole).encode()), 600_000, 'The fixture must reproduce the oversize body of the finding')
        slim = {**body, 'documents': {'scope': scope, 'documents': [{'id': document_id} for document_id, _ in files]}}
        self.assertLess(len(json.dumps(slim).encode()), 5_000)
        code, receipt = self.post('/api/knowledge/submit', slim)
        self.assertEqual(code, 202, receipt)
        stored = self.detail(receipt)
        # The server rebuilds every reference from its own store; nothing the browser left out is missing.
        self.assertEqual([(item['id'], item['name'], item['sha256']) for item in stored['documents']['documents']],
                         [(record['id'], record['name'], record['sha256']) for record in records])
        self.assertTrue(all(item['sources'] for item in stored['documents']['documents']))
        self.assertEqual({item['id'] for item in stored['document_evidence']}, {source['id'] for _, source in files})
        self.assertNotIn('observations', json.dumps(stored['documents']))
        # The body the old page built is no longer refused for its size either, and stores the same references.
        code, second = self.post('/api/knowledge/submit', {**whole, 'context': {'process_name': 'Invoice intake, whole records'}})
        self.assertEqual(code, 202, second)
        self.assertEqual(self.detail(second)['documents'], stored['documents'])

    def test_the_page_is_told_the_limit_and_it_is_the_stores_own(self):
        with urlopen(f'http://127.0.0.1:{self.httpd.server_port}/api/config', timeout=15) as response:
            config = json.loads(response.read())
        self.assertEqual(config['knowledge_submit_max_bytes'], server.MAX_KNOWLEDGE_SUBMIT)
        # The store refuses a stored submission over 1,000,000 bytes; the door must not be narrower or wider.
        self.assertEqual(server.MAX_KNOWLEDGE_SUBMIT, 1_000_000)
        graph = kg.KnowledgeGraph(Path(self.temp.name) / 'limit.db')
        try:
            padded = submission(context={'process_name': 'Invoice intake', 'background': 'b' * 1_000_000})
            with self.assertRaisesRegex(ValueError, 'local size limit'):
                graph.submit(padded)
        finally:
            graph.close()

    def test_a_long_interview_within_the_store_limit_is_accepted(self):
        # 150 answers of about 5,000 characters: more than the general 600,000-byte request limit,
        # less than the 1,000,000 bytes the knowledge store itself accepts.
        body = submission(150, 'Answer {} ' + 'word ' * 990)
        size = len(json.dumps(body).encode())
        self.assertTrue(server.MAX_JSON < size < server.MAX_KNOWLEDGE_SUBMIT, size)
        code, receipt = self.post('/api/knowledge/submit', body)
        self.assertEqual(code, 202, receipt)
        self.assertEqual(len(self.detail(receipt)['turns']), 300)

    def test_an_oversize_submission_gets_a_readable_refusal_and_stores_nothing(self):
        body = submission(240, 'Answer {} ' + 'word ' * 1100)
        raw = json.dumps(body).encode()
        self.assertGreater(len(raw), server.MAX_KNOWLEDGE_SUBMIT)
        # A raw client that sends the whole body before it reads, as a browser does: the reply must
        # arrive as a reply, not as a reset connection.
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=15)
        try:
            connection.request('POST', '/api/knowledge/submit', body=raw,
                               headers={'Content-Type': 'application/json', 'X-CSRF-Token': self.httpd.csrf_token})
            response = connection.getresponse()
            result = json.loads(response.read())
        finally:
            connection.close()
        self.assertEqual(response.status, 413, result)
        self.assertEqual(result['code'], 'submission_too_large')
        self.assertIs(result['not_saved'], True)
        self.assertEqual(result['limit'], server.MAX_KNOWLEDGE_SUBMIT)
        self.assertIn(f'{len(raw):,} bytes', result['error'])
        self.assertIn('1,000,000', result['error'])
        self.assertEqual(self.submissions(), [])

    def test_a_body_far_beyond_the_limit_is_not_read(self):
        size = server.MAX_REJECTED_DRAIN + 1
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=15)
        try:
            connection.putrequest('POST', '/api/knowledge/submit')
            for name, value in (('Content-Type', 'application/json'), ('X-CSRF-Token', self.httpd.csrf_token), ('Content-Length', str(size))):
                connection.putheader(name, value)
            connection.endheaders()
            connection.send(b'{"turns":')  # The rest never comes; the server must not wait for it.
            response = connection.getresponse()
            result = json.loads(response.read())
        finally:
            connection.close()
        self.assertEqual(response.status, 413, result)
        self.assertEqual(result['code'], 'submission_too_large')

    def test_other_knowledge_routes_keep_the_general_limit(self):
        padded = {'submission_id': 'x', 'revision': 1, 'status_token': 'y', 'padding': 'p' * (server.MAX_JSON + 10)}
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=15)
        try:
            connection.putrequest('POST', '/api/knowledge/status')
            raw = json.dumps(padded).encode()
            for name, value in (('Content-Type', 'application/json'), ('X-CSRF-Token', self.httpd.csrf_token), ('Content-Length', str(len(raw)))):
                connection.putheader(name, value)
            connection.endheaders()
            response = connection.getresponse()
            result = json.loads(response.read())
        finally:
            connection.close()
        self.assertEqual(response.status, 413)
        self.assertEqual(result, {'error': 'Knowledge request is empty or too large.'})
        self.assertEqual(self.post('/api/knowledge/submit', None, raw=b'')[0], 413, 'An empty submission is still refused')


class NotSavedSignalTests(SubmitRouteCase):
    """knowledge-frontend-3: a refusal says when no record exists under the submission key."""

    def test_refusals_of_a_key_that_was_never_stored_say_not_saved(self):
        refused = {
            'contradictory capture marker': submission(2, submission_key=KEY % 1, capture={
                'in_progress': False, 'notes_current': True, 'map_current': True, 'notes_through_turn': 't002', 'map_through_turn': 't004'}),
            'no participant statement': {**submission(submission_key=KEY % 2), 'turns': []},
            'unknown process': submission(submission_key=KEY % 3, process_id='33333333-3333-4333-8333-333333333333'),
            'file that cannot be read': submission(submission_key=KEY % 4, workflow={
                'title': 'Invoice intake', 'steps': [{'id': 'S1', 'title': 'Check', 'evidence_turns': ['doc_gone_r1_c1', 't002']}], 'connections': []}),
        }
        for name, body in refused.items():
            code, result = self.post('/api/knowledge/submit', body)
            self.assertEqual(code, 400, (name, result))
            self.assertIs(result.get('not_saved'), True, (name, result))
        self.assertEqual(refused and self.submissions(), [])
        self.assertEqual(self.post('/api/knowledge/submit', submission(submission_key=KEY % 4, workflow={
            'title': 'Invoice intake', 'steps': [{'id': 'S1', 'title': 'Check', 'evidence_turns': ['doc_gone_r1_c1', 't002']}],
            'connections': []}))[1].get('code'), 'document_citations_unavailable', 'The structured refusal keeps its own fields')

    def test_a_key_that_holds_a_record_is_never_reported_as_not_saved(self):
        code, receipt = self.post('/api/knowledge/submit', submission(submission_key=KEY % 1))
        self.assertEqual(code, 202, receipt)
        # The same key with other content: a record exists, so the browser must not be told to let go.
        code, result = self.post('/api/knowledge/submit', submission(2, submission_key=KEY % 1))
        self.assertEqual(code, 400, result)
        self.assertIn('already used for different content', result['error'])
        self.assertNotIn('not_saved', result)
        # The exact request again is recovered, not refused.
        code, again = self.post('/api/knowledge/submit', submission(submission_key=KEY % 1))
        self.assertEqual((code, again['submission_id'], again['revision']), (202, receipt['submission_id'], 1))
        self.assertEqual(len(self.submissions()), 1)

    def test_refusals_without_a_usable_key_and_of_other_routes_carry_no_signal(self):
        code, result = self.post('/api/knowledge/submit', {**submission(), 'turns': []})
        self.assertEqual(code, 400, result)
        self.assertNotIn('not_saved', result, 'Without a key there is no attempt to release')
        code, result = self.post('/api/knowledge/submit', submission(submission_key='not-a-key'))
        self.assertEqual(code, 400, result)
        self.assertNotIn('not_saved', result)
        code, result = self.post('/api/knowledge/status', {'submission_id': 'x', 'revision': 1, 'status_token': 'y'})
        self.assertEqual(code, 403, result)
        self.assertNotIn('not_saved', result)
        code, result = self.post('/api/knowledge/submit', None, raw=b'{"turns": [')
        self.assertEqual(code, 400, result)
        self.assertNotIn('not_saved', result)

    def test_a_stored_revision_is_recovered_even_after_the_right_to_revise_is_gone(self):
        code, first = self.post('/api/knowledge/submit', submission(submission_key=KEY % 1))
        self.assertEqual(code, 202, first)
        revision = submission(2, submission_key=KEY % 2, process_id=first['process_id'])
        code, second = self.post('/api/knowledge/submit', revision)
        self.assertEqual((code, second['revision']), (202, 2))
        # The reply was lost and, before the retry, local-owner mode was switched off.
        self.httpd.knowledge_auth.local_owner = False
        code, recovered = self.post('/api/knowledge/submit', revision)
        self.assertEqual(code, 202, recovered)
        self.assertEqual((recovered['submission_id'], recovered['revision'], recovered['job_id']),
                         (second['submission_id'], 2, second['job_id']))
        # A revision that was never stored is still refused, and says so.
        code, result = self.post('/api/knowledge/submit', submission(3, submission_key=KEY % 3, process_id=first['process_id']))
        self.assertEqual(code, 403, result)
        self.assertEqual(result['error'], 'Revisions require a verified owner or administrator.')
        self.assertIs(result.get('not_saved'), True)
        # Recovery stays bound to the exact request: other content under the stored key is not a way in.
        code, result = self.post('/api/knowledge/submit', submission(4, submission_key=KEY % 2, process_id=first['process_id']))
        self.assertEqual(code, 400, result)
        self.assertNotIn('not_saved', result)
        self.assertEqual(sorted(row['revision'] for row in self.submissions()), [1, 2])


class DefaultConfigurationTests(SubmitRouteCase):
    """The shipped configuration: no administrator, no verified submitter."""
    settings = {}

    def test_refused_revision_says_nothing_was_saved(self):
        code, first = self.post('/api/knowledge/submit', submission(submission_key=KEY % 1, interview_id=INTERVIEW % 1))
        self.assertEqual(code, 202, first)
        code, result = self.post('/api/knowledge/submit', submission(2, submission_key=KEY % 2, interview_id=INTERVIEW % 1,
                                                                     process_id=first['process_id']))
        self.assertEqual(code, 403, result)
        self.assertIs(result.get('not_saved'), True)

    def test_same_interview_again_is_a_conflict_until_the_submitter_chooses_a_separate_process(self):
        code, first = self.post('/api/knowledge/submit', submission(submission_key=KEY % 1, interview_id=INTERVIEW % 1))
        self.assertEqual(code, 202, first)
        # A second tab, or a copy saved before the first Submit: no process ID, a new key, one more answer.
        again = submission(2, submission_key=KEY % 2, interview_id=INTERVIEW % 1)
        code, result = self.post('/api/knowledge/submit', again)
        self.assertEqual(code, 409, result)
        self.assertEqual(result['code'], 'interview_already_submitted')
        self.assertEqual((result['process_id'], result['revision']), (first['process_id'], 1))
        self.assertEqual(result['error'], 'This interview was already submitted as revision 1.')
        self.assertIs(result.get('not_saved'), True)
        code, page = self.post('/api/knowledge/status', {'submission_id': first['submission_id'], 'revision': 1, 'status_token': first['status_token']})
        self.assertEqual(code, 200, page)
        # Chosen on purpose, it is filed as its own process; the choice is not stored with the interview.
        code, separate = self.post('/api/knowledge/submit', {**again, 'submission_key': KEY % 3, 'separate_process': True})
        self.assertEqual(code, 202, separate)
        self.assertNotEqual(separate['process_id'], first['process_id'])
        self.assertEqual(separate['revision'], 1)


class SameInterviewTests(SubmitRouteCase):
    """gap3-two-tabs-4, with an administrator present (local-owner mode)."""

    def test_same_interview_twice_creates_one_process_unless_a_separate_one_is_chosen(self):
        code, first = self.post('/api/knowledge/submit', submission(submission_key=KEY % 1, interview_id=INTERVIEW % 1))
        self.assertEqual(code, 202, first)
        again = submission(2, submission_key=KEY % 2, interview_id=INTERVIEW % 1)
        code, result = self.post('/api/knowledge/submit', again)
        self.assertEqual(code, 409, result)
        self.assertEqual(len(self.submissions()), 1, 'Nothing is stored for the refused copy')
        # The dialog's first choice: a revision of the process the server named.
        code, revision = self.post('/api/knowledge/submit', {**again, 'submission_key': KEY % 3, 'process_id': result['process_id']})
        self.assertEqual(code, 202, revision)
        self.assertEqual((revision['process_id'], revision['submission_id'], revision['revision']), (first['process_id'], first['submission_id'], 2))
        # The conflict then names the latest revision that came from this interview.
        code, result = self.post('/api/knowledge/submit', submission(3, submission_key=KEY % 4, interview_id=INTERVIEW % 1))
        self.assertEqual((code, result.get('revision')), (409, 2), result)
        # A retry of the stored first request is still recovered, not treated as a second copy.
        code, recovered = self.post('/api/knowledge/submit', submission(submission_key=KEY % 1, interview_id=INTERVIEW % 1))
        self.assertEqual((code, recovered['revision'], recovered['submission_id']), (202, 1, first['submission_id']))
        self.assertEqual(sorted(row['revision'] for row in self.submissions()), [1, 2])

    def test_other_interviews_and_interviews_without_an_identity_are_new_processes_as_before(self):
        code, first = self.post('/api/knowledge/submit', submission(interview_id=INTERVIEW % 1))
        code, other = self.post('/api/knowledge/submit', submission(interview_id=INTERVIEW % 2))
        self.assertEqual(code, 202, other)
        # Saved before interviews had an identity, or in a browser that could not make one (null): nothing to compare.
        for without in ({}, {'interview_id': None}):
            code, legacy = self.post('/api/knowledge/submit', submission(**without))
            self.assertEqual(code, 202, legacy)
        self.assertEqual(len({row['process_id'] for row in self.submissions()}), 4)
        self.assertEqual(self.detail(first)['interview_id'], INTERVIEW % 1)
        self.assertNotIn('interview_id', self.detail(legacy))

    def test_malformed_identity_or_choice_is_refused(self):
        for bad in ({'interview_id': 'not-an-id'}, {'interview_id': 7}, {'interview_id': ['x']}, {'separate_process': 'yes'}, {'separate_process': 1}):
            code, result = self.post('/api/knowledge/submit', submission(**bad))
            self.assertEqual(code, 400, (bad, result))
        self.assertEqual(self.submissions(), [])
        # separate_process False is the same as leaving it out, and the flag is not stored.
        code, first = self.post('/api/knowledge/submit', submission(interview_id=INTERVIEW % 1, separate_process=True))
        self.assertEqual(code, 202, first)
        self.assertNotIn('separate_process', self.detail(first))
        code, result = self.post('/api/knowledge/submit', submission(interview_id=INTERVIEW % 1, separate_process=False))
        self.assertEqual(code, 409, result)


class SameInterviewMatchingTests(unittest.TestCase):
    """A copy of the same interview filed as a separate process is not offered to the matcher as a counterpart."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.seen = []
        def analyzer(current, candidates):
            self.seen.append((current['submission_id'], [item['submission_id'] for item in candidates]))
            return []
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db', analyzer=analyzer)

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def test_twin_of_the_same_interview_is_not_a_matcher_candidate(self):
        first = self.graph.submit(submission(interview_id=INTERVIEW % 1))
        wait(self.graph, first['job_id'])
        other = self.graph.submit(submission(context={'process_name': 'Payment run'}, interview_id=INTERVIEW % 2))
        wait(self.graph, other['job_id'])
        with self.assertRaises(kg.InterviewAlreadySubmitted) as refused:
            self.graph.submit(submission(2, interview_id=INTERVIEW % 1))
        self.assertEqual((refused.exception.process_id, refused.exception.revision), (first['process_id'], 1))
        twin = self.graph.submit(submission(2, interview_id=INTERVIEW % 1, separate_process=True))
        wait(self.graph, twin['job_id'])
        by_current = dict(self.seen)
        self.assertEqual(by_current[other['submission_id']], [first['submission_id']], 'Different interviews are compared as before')
        self.assertEqual(by_current[twin['submission_id']], [other['submission_id']],
                         'The matcher must not be asked whether the interview connects to its own copy')
        legacy = self.graph.submit(submission(context={'process_name': 'Legacy'}))
        wait(self.graph, legacy['job_id'])
        self.assertEqual(sorted(dict(self.seen)[legacy['submission_id']]),
                         sorted([first['submission_id'], other['submission_id'], twin['submission_id']]))


if __name__ == '__main__':
    unittest.main()
