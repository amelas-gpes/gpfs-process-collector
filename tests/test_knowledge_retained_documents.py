"""Submit process when notes or steps still cite a file that was removed or saved for later.

The interview keeps such citations as saved excerpts. Company knowledge stores them as flagged
provenance, never reads those files again for matching or proposals, refuses them as the only basis
of a part of a new process, and says which file and which parts are affected when it refuses.
Loopback HTTP and temporary SQLite only; the matching provider is a recording stand-in.
"""
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server
from test_knowledge_graph import kg, payload

spec = importlib.util.spec_from_file_location('knowledge_ai', Path(__file__).resolve().parents[1] / 'knowledge_ai.py')
knowledge_ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(knowledge_ai)

CODE = 'document_citations_unavailable'


class Matcher:
    """Stands in for the provider behind the real matching adapter and records every request body."""
    def __init__(self):
        self.sent = []
        self.reply = lambda body: {'proposals': []}

    def structured(self, instructions, body, schema, name, maximum):
        self.sent.append(body)
        return self.reply(body)


class RetainedDocumentCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.matcher = Matcher()
        self.httpd = server.InterviewServer(
            ('127.0.0.1', 0), server.Handler, client=server.OpenAIClient({}),
            documents_root=Path(self.temp.name) / 'documents', knowledge_root=Path(self.temp.name) / 'graph',
            knowledge_settings={'COLLECTOR_DEPLOYMENT_MODE': 'local', 'KNOWLEDGE_LOCAL_OWNER': 'true'},
            knowledge_analyzer=knowledge_ai.build_analyzer(self.matcher))
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.store = self.httpd.documents_store
        self.scope = self.store.create_scope()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def post(self, path, body):
        request = Request(f'http://127.0.0.1:{self.httpd.server_port}' + path, data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=15) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def file(self, name='returns-log.csv', data=b'return,reason\nRET-2025-0003,damaged in transit\n', scope=None):
        """A read file whose review finished, as the Assets tab holds it after intake."""
        scope = scope or self.scope
        record = self.store.add(scope, name, data)
        self.store.extract(scope, record['id'])
        source = self.store.chunks(scope, record['id'])['chunks'][0]
        self.store.update(scope, record['id'], {'analysis': {
            'phase': 'complete', 'disposition': 'relevant', 'intent_version': 1, 'version': 3,
            'sources': [{'source_id': source['id'], 'label': source['label']}]}})
        return record['id'], source

    def park(self, document_id):
        # The state document_service.action('park') writes; the store is updated directly so that no
        # background review of the parked file starts in this test.
        analysis = self.store.get(self.scope, document_id)['analysis']
        self.store.update(self.scope, document_id, {'analysis': {**analysis, 'disposition': 'parked', 'parked_by_user': True, 'question': ''}})

    def action(self, document_id, action):
        status, result = self.post('/api/documents/action', {'scope': self.scope, 'id': document_id, 'action': action})
        self.assertEqual(status, 200, result)
        return result['document']

    def submission(self, name, first, second=('u1',), listed=(), notes=None, scope=None):
        """Step s1 cites `first`, step s2 and the connection cite `second`; `listed` is the browser's file list."""
        body = payload(name, 'I check each return against the returns log before I raise the credit note.')
        body['draft']['steps'][0]['evidence_turns'] = list(first)
        body['draft']['steps'][1]['evidence_turns'] = list(second)
        body['draft']['connections'][0]['evidence_turns'] = list(second)
        body['memo_findings'] = [{'key': 'checks', 'status': 'known', 'answer': 'Each return is checked against the log.',
                                  'evidence_turns': list(notes if notes is not None else second)}]
        body['documents'] = {'scope': scope or self.scope, 'documents': [{'id': identity} for identity in listed]}
        return body

    def detail(self, receipt):
        return self.httpd.knowledge.admin_detail('submission', receipt['submission_id'], receipt['revision'])['item']

    def stored(self):
        return self.httpd.knowledge.admin_browse('submissions')['items']

    def finished(self, receipt):
        for _ in range(1500):
            job = self.httpd.knowledge.status(receipt['submission_id'], receipt['revision'], receipt['status_token'])
            if job['status'] not in ('pending', 'processing'):
                return job
            time.sleep(.01)
        self.fail('The matching job did not finish.')

    def dropped(self, receipt):
        """How many proposals of that job the validator refused (they are dropped, the job completes)."""
        job = next(item for item in self.httpd.knowledge.admin_browse('jobs')['items'] if item['id'] == receipt['job_id'])
        return job['detail'].get('proposals_dropped')


class RetainedCitationTests(RetainedDocumentCase):
    def test_revision_keeps_a_citation_to_a_removed_file_as_a_flagged_saved_excerpt(self):
        document_id, source = self.file()
        status, first = self.post('/api/knowledge/submit', self.submission('Returns intake', [source['id'], 'u1'], listed=[document_id]))
        self.assertEqual(status, 202, first)
        self.assertTrue(self.action(document_id, 'remove')['archived'])
        # The browser's file list is now empty; the draft, the working map and the notes still cite the file.
        revision = self.submission('Returns intake', [source['id'], 'u1'], second=[source['id']])
        revision['process_id'] = first['process_id']
        status, second = self.post('/api/knowledge/submit', revision)
        self.assertEqual(status, 202, second)
        self.assertEqual(second['revision'], 2)
        saved = self.detail(second)
        entry = next(item for item in saved['document_evidence'] if item['id'] == source['id'])
        self.assertIs(entry['retained_only'], True)
        self.assertIs(entry['archived'], True)
        self.assertEqual(entry['text'], source['text'])
        self.assertEqual(entry['name'], 'returns-log.csv')
        self.assertEqual(saved['documents']['documents'], [], 'A removed file is not one of the revision\'s files')
        self.assertEqual([(item['id'], item['name'], item['archived']) for item in saved['documents']['retained']],
                         [(document_id, 'returns-log.csv', True)])
        self.assertEqual(saved['documents']['retained'][0]['sources'], [{'source_id': source['id'], 'label': source['label']}])
        self.assertNotIn(self.scope, json.dumps(saved))
        # A step that rests on the saved excerpt alone is provenance for the existing capture in a revision.
        self.assertEqual(saved['draft']['steps'][1]['evidence_turns'], [source['id']])
        # Admin cannot read the removed file through this revision.
        status, _ = self.post('/api/knowledge/admin/document-source', {'submission_id': second['submission_id'], 'revision': 2,
                                                                      'document_id': document_id, 'source_id': source['id']})
        self.assertEqual(status, 403)

    def test_one_removed_file_citation_beside_an_answer_does_not_block_a_new_process(self):
        document_id, source = self.file()
        self.action(document_id, 'remove')
        status, receipt = self.post('/api/knowledge/submit', self.submission('Returns intake', [source['id'], 'u1']))
        self.assertEqual(status, 202, receipt)
        saved = self.detail(receipt)
        self.assertIs(saved['document_evidence'][0]['retained_only'], True)
        step = next(item for item in self.httpd.knowledge.admin_browse('entities', {'type': 'step'})['items'] if item['label'] == 'Start')
        self.assertEqual(self.httpd.knowledge.admin_detail('entity', step['id'])['item']['data']['source_kind'], 'mixed')

    def test_new_process_resting_only_on_a_removed_file_is_refused_by_name_and_accepted_once_restored(self):
        document_id, source = self.file()
        self.action(document_id, 'remove')
        body = self.submission('Returns intake', [source['id']], notes=[source['id']])
        status, refused = self.post('/api/knowledge/submit', body)
        self.assertEqual(status, 400, refused)
        self.assertEqual(refused['code'], CODE)
        for expected in ('returns-log.csv', 'removed', 'draft step s1 “Start”', 'Checks, approvals & proof', 'Restore', 'submit without these citations'):
            self.assertIn(expected, refused['error'])
        self.assertLessEqual(len(refused['error']), 600, 'The browser refuses a longer error text')
        self.assertEqual(len(refused['citations']), 1)
        entry = refused['citations'][0]
        self.assertEqual((entry['document_id'], entry['name'], entry['state'], entry['source_ids']),
                         (document_id, 'returns-log.csv', 'removed', [source['id']]))
        self.assertEqual(entry['cited_by'], ['draft step s1 “Start”', 'the “Checks, approvals & proof” note'])
        self.assertNotIn(self.scope, json.dumps(refused))
        self.assertNotIn(source['text'], json.dumps(refused), 'A refusal names the file, it does not quote it')
        self.assertEqual(self.stored(), [])
        restored = self.action(document_id, 'restore')
        self.assertIs(restored['archived'], False)
        body['documents']['documents'] = [{'id': document_id}]
        status, receipt = self.post('/api/knowledge/submit', body)
        self.assertEqual(status, 202, receipt)
        entry = self.detail(receipt)['document_evidence'][0]
        self.assertNotIn('retained_only', entry)
        self.assertEqual(entry['text'], source['text'])

    def test_citation_of_a_file_saved_for_later_is_kept_for_a_revision_and_explained_for_a_new_process(self):
        document_id, source = self.file('returns-procedure.csv')
        status, first = self.post('/api/knowledge/submit', self.submission('Returns intake', [source['id'], 'u1'], listed=[document_id]))
        self.assertEqual(status, 202, first)
        self.park(document_id)
        # A parked file stays in the browser's list.
        revision = self.submission('Returns intake', [source['id'], 'u1'], second=[source['id']], listed=[document_id])
        revision['process_id'] = first['process_id']
        status, second = self.post('/api/knowledge/submit', revision)
        self.assertEqual(status, 202, second)
        saved = self.detail(second)
        entry = saved['document_evidence'][0]
        self.assertEqual((entry['retained_only'], entry['archived'], entry['disposition']), (True, False, 'parked'))
        self.assertEqual(saved['documents']['documents'], [])
        self.assertEqual(saved['documents']['retained'][0]['disposition'], 'parked')
        status, refused = self.post('/api/knowledge/submit', self.submission('Returns intake copy', [source['id']], listed=[document_id]))
        self.assertEqual(status, 400, refused)
        self.assertEqual(refused['code'], CODE)
        self.assertEqual(refused['citations'][0]['state'], 'parked')
        for expected in ('returns-procedure.csv', 'saved for later', 'draft step s1 “Start”', 'Revisit this file', 'submit without these citations'):
            self.assertIn(expected, refused['error'])
        self.assertNotIn('not authorized', refused['error'])

    def test_revision_cannot_file_what_submit_without_these_citations_left_out(self):
        # Repair round 1, issue 1: the revision exception is for passages an earlier revision holds,
        # not for every revision. The dialog's next ordinary Submit is a revision by default.
        document_id, source = self.file('salary-bands.csv', b'grade,band\nDirector,CONFIDENTIAL 240000\n')
        self.action(document_id, 'remove')
        status, refused = self.post('/api/knowledge/submit', self.submission('Payroll', [source['id']]))
        self.assertEqual((status, refused.get('code')), (400, CODE), refused)
        # "Submit without these citations": the same snapshot without the named source IDs.
        status, first = self.post('/api/knowledge/submit', self.submission('Payroll', []))
        self.assertEqual(status, 202, first)
        self.assertNotIn('document_evidence', self.detail(first))
        # The interview kept its citation, so the next Submit sends it again, now as a revision.
        again = self.submission('Payroll', [source['id']])
        again['process_id'] = first['process_id']
        status, refused = self.post('/api/knowledge/submit', again)
        self.assertEqual(status, 400, refused)
        self.assertEqual(refused['code'], CODE)
        for expected in ('salary-bands.csv', 'removed', 'no earlier revision of this process filed', 'draft step s1 “Start”',
                         'Restore', 'submit without these citations'):
            self.assertIn(expected, refused['error'])
        self.assertNotIn('new process', refused['error'])
        self.assertLessEqual(len(refused['error']), 600)
        entry = refused['citations'][0]
        self.assertEqual((entry['document_id'], entry['state'], entry['source_ids'], entry['cited_by']),
                         (document_id, 'removed', [source['id']], ['draft step s1 “Start”']))
        self.assertNotIn('CONFIDENTIAL', json.dumps(refused))
        self.assertEqual([item['revision'] for item in self.stored()], [1], 'Nothing is stored by the refused revision')
        self.assertNotIn('CONFIDENTIAL', json.dumps(self.detail(first)))
        # The same revision without that citation is filed, and so is one that cites it beside an answer.
        without = self.submission('Payroll', [])
        without['process_id'] = first['process_id']
        status, second = self.post('/api/knowledge/submit', without)
        self.assertEqual((status, second.get('revision')), (202, 2), second)
        beside = self.submission('Payroll', [source['id'], 'u1'])
        beside['process_id'] = first['process_id']
        status, third = self.post('/api/knowledge/submit', beside)
        self.assertEqual((status, third.get('revision')), (202, 3), third)
        self.assertIs(self.detail(third)['document_evidence'][0]['retained_only'], True)
        # Revision 3 holds the passage now, so a later revision may keep a part that rests on it alone.
        status, fourth = self.post('/api/knowledge/submit', again)
        self.assertEqual((status, fourth.get('revision')), (202, 4), fourth)

    def test_revision_cannot_first_cite_a_parked_or_removed_file_as_the_only_basis_of_a_part(self):
        document_id, source = self.file('returns-procedure.csv')
        other_id, other = self.file('returns-log.csv', b'return,reason\nRET-2025-0009,wrong item\n')
        status, first = self.post('/api/knowledge/submit', self.submission('Returns intake', [other['id'], 'u1'], listed=[document_id, other_id]))
        self.assertEqual(status, 202, first)
        self.assertEqual(self.httpd.knowledge.filed_document_sources(first['process_id']), {other['id']})
        self.park(document_id)
        self.action(other_id, 'remove')
        # The parked file was attached to revision 1 but never cited in it: its passage is new to this process.
        revision = self.submission('Returns intake', [source['id']], notes=[other['id']], listed=[document_id])
        revision['process_id'] = first['process_id']
        status, refused = self.post('/api/knowledge/submit', revision)
        self.assertEqual((status, refused.get('code')), (400, CODE), refused)
        self.assertEqual([(entry['name'], entry['state'], entry['source_ids']) for entry in refused['citations']],
                         [('returns-procedure.csv', 'parked', [source['id']])],
                         'Only the passage no earlier revision holds is refused; the removed file revision 1 cited may stay')
        for expected in ('saved for later', 'no earlier revision of this process filed', 'Revisit this file'):
            self.assertIn(expected, refused['error'])
        self.assertEqual([item['revision'] for item in self.stored()], [1])
        # Another process's revisions do not make the passage this process's own.
        status, elsewhere = self.post('/api/knowledge/submit', self.submission('Returns audit', [source['id'], 'u1'], listed=[document_id]))
        self.assertEqual(status, 202, elsewhere)
        status, refused = self.post('/api/knowledge/submit', revision)
        self.assertEqual((status, refused.get('code')), (400, CODE), refused)
        self.assertEqual(self.httpd.knowledge.filed_document_sources('not-a-process'), set())

    def test_removed_file_the_browser_still_lists_is_a_removed_file_not_an_authorization_failure(self):
        document_id, source = self.file()
        self.action(document_id, 'remove')
        status, receipt = self.post('/api/knowledge/submit', self.submission('Returns intake', [source['id'], 'u1'], listed=[document_id]))
        self.assertEqual(status, 202, receipt)
        saved = self.detail(receipt)
        self.assertEqual(saved['documents']['documents'], [])
        self.assertIs(saved['document_evidence'][0]['retained_only'], True)

    def test_citation_that_cannot_be_read_is_refused_with_the_parts_that_cite_it(self):
        document_id, source = self.file()
        missing = document_id + '_r99_c1'
        forged = 'doc_' + 'f' * 24 + '_r1_c1'
        # Beside an answer as well: a citation without readable text cannot be stored as evidence.
        status, refused = self.post('/api/knowledge/submit', self.submission('Returns intake', [missing, 'u1'], notes=[forged, 'u1'], listed=[document_id]))
        self.assertEqual(status, 400, refused)
        self.assertEqual(refused['code'], CODE)
        entries = {entry['name']: entry for entry in refused['citations']}
        self.assertEqual(set(entries), {'returns-log.csv', ''})
        self.assertEqual((entries['returns-log.csv']['state'], entries['returns-log.csv']['source_ids'], entries['returns-log.csv']['cited_by']),
                         ('unavailable', [missing], ['draft step s1 “Start”']))
        self.assertEqual((entries['']['state'], entries['']['source_ids'], entries['']['cited_by']),
                         ('unavailable', [forged], ['the “Checks, approvals & proof” note']))
        self.assertIn('submit without these citations', refused['error'])
        self.assertIn('1 other file is also affected', refused['error'])
        self.assertEqual(self.stored(), [])

    def test_saved_excerpts_come_only_from_the_interviews_own_file_scope(self):
        document_id, source = self.file()
        self.action(document_id, 'remove')
        other = self.store.create_scope()
        for scope in (other, 'A' * 43, None, 7):
            with self.subTest(scope=scope):
                body = self.submission('Returns intake', [source['id'], 'u1'])
                body['documents']['scope'] = scope
                status, refused = self.post('/api/knowledge/submit', body)
                self.assertEqual(status, 400, refused)
                self.assertEqual(refused['code'], CODE)
                self.assertEqual(refused['citations'][0]['name'], '', 'A file of another scope is not named')
                self.assertNotIn('returns-log.csv', json.dumps(refused))
        self.assertEqual(self.stored(), [])

    def test_removed_file_text_never_reaches_a_matching_request(self):
        document_id, source = self.file(data=b'grade,band\nDirector,CONFIDENTIAL 240000\n')
        self.action(document_id, 'remove')
        status, first = self.post('/api/knowledge/submit', self.submission('Payroll', [source['id'], 'u1']))
        self.assertEqual(status, 202, first)
        self.finished(first)
        other = payload('Budgeting', 'We prepare the staffing budget each quarter.')
        other['documents'] = None
        status, second = self.post('/api/knowledge/submit', other)
        self.assertEqual(status, 202, second)
        self.assertEqual(self.finished(second)['status'], 'completed')
        self.assertEqual(len(self.matcher.sent), 1)
        self.assertEqual(self.matcher.sent[0]['candidates'][0]['document_excerpts'], [])
        self.assertNotIn('CONFIDENTIAL', json.dumps(self.matcher.sent))


class ParkedFileTests(RetainedDocumentCase):
    """knowledge-store-5: Save for later applies on the manifest and matching paths, not only to citations."""
    def proposal(self, document_id, source_id, quote):
        def reply(body):
            current, other = body['submission'], body['candidates'][0]
            return {'proposals': [{
                'source_submission_id': other['submission_id'], 'destination_submission_id': current['submission_id'],
                'source_revision': other['revision'], 'destination_revision': current['revision'],
                'relationship_type': 'provides_input_to', 'scope': '', 'condition': '',
                'explanation': 'The file lists the bands.', 'inference': 'Possible input.', 'missing_evidence': [], 'contradictions': [],
                'evidence': [{'type': 'document_supported', 'submission_id': other['submission_id'], 'revision': other['revision'],
                              'turn_id': '', 'document_id': document_id, 'source_id': source_id, 'quote': quote},
                             {'type': 'employee_reported', 'submission_id': current['submission_id'], 'revision': current['revision'],
                              'turn_id': 'u1', 'document_id': '', 'source_id': '', 'quote': current['participant_turns'][0]['text'][:20]}]}]}
        return reply

    def pair(self, document_id, before_second=lambda: None):
        """One process with the file attached but not cited, then an unrelated one that triggers matching."""
        first = payload('Payroll', 'We run payroll on the 25th.', scope='')
        first['documents'] = {'scope': self.scope, 'documents': [{'id': document_id}]}
        status, a = self.post('/api/knowledge/submit', first)
        self.assertEqual(status, 202, a)
        self.finished(a)
        before_second()
        second = payload('Budgeting', 'We prepare the staffing budget each quarter.', scope='')
        second['documents'] = None
        status, b = self.post('/api/knowledge/submit', second)
        self.assertEqual(status, 202, b)
        return a, b

    def test_parked_file_attached_but_not_cited_stays_out_of_the_manifest_and_of_matching(self):
        document_id, source = self.file('salary-bands.csv', b'grade,band\nDirector,CONFIDENTIAL 240000\nAnalyst,CONFIDENTIAL 70000\n')
        self.park(document_id)
        self.matcher.reply = self.proposal(document_id, source['id'], 'CONFIDENTIAL 240000')
        a, b = self.pair(document_id)
        self.assertEqual(self.detail(a)['documents'], {'documents': []})
        # live-draft-knowledge-5: the job completes; the refused proposal is dropped and recorded on the job.
        self.assertEqual(self.finished(b)['status'], 'completed')
        self.assertEqual(self.dropped(b), 1, 'A proposal that quotes the parked file is not accepted')
        self.assertEqual(len(self.matcher.sent), 1)
        self.assertEqual(self.matcher.sent[0]['candidates'][0]['document_excerpts'], [])
        self.assertNotIn('CONFIDENTIAL', json.dumps(self.matcher.sent))
        self.assertEqual(self.httpd.knowledge.admin_browse('connections')['items'], [])

    def test_file_parked_after_it_was_submitted_no_longer_feeds_matching_or_proposals(self):
        document_id, source = self.file('salary-bands.csv', b'grade,band\nDirector,CONFIDENTIAL 240000\nAnalyst,CONFIDENTIAL 70000\n')
        self.matcher.reply = self.proposal(document_id, source['id'], 'CONFIDENTIAL 240000')
        a, b = self.pair(document_id, before_second=lambda: self.park(document_id))
        self.assertEqual(self.detail(a)['documents']['documents'][0]['sources'], [{'source_id': source['id'], 'label': source['label']}],
                         'The file was in use when the first process was submitted')
        self.assertEqual(self.finished(b)['status'], 'completed')
        self.assertEqual(self.dropped(b), 1)
        self.assertEqual(self.matcher.sent[0]['candidates'][0]['document_excerpts'], [])
        self.assertNotIn('CONFIDENTIAL', json.dumps(self.matcher.sent))
        self.assertEqual(self.httpd.knowledge.admin_browse('connections')['items'], [])

    def test_confirmed_file_evidence_goes_back_for_review_when_the_file_is_saved_for_later(self):
        document_id, source = self.file('support.csv', b'field,value\nnav,approved\n')
        self.matcher.reply = self.proposal(document_id, source['id'], 'B2=approved')
        a, b = self.pair(document_id)
        self.assertEqual(self.finished(b)['status'], 'completed')
        self.assertIn('approved', json.dumps(self.matcher.sent[0]['candidates'][0]['document_excerpts']), 'An active file still feeds matching')
        item = self.httpd.knowledge.admin_browse('connections')['items'][0]
        confirmed = self.httpd.knowledge.review(item['id'], 'confirm', 'local-owner', 'Reviewed fixture', item['review_version'])
        self.assertEqual(confirmed['status'], 'confirmed')
        self.park(document_id)
        changed = self.httpd.knowledge.admin_detail('proposal', item['id'])['item']
        self.assertEqual(changed['status'], 'stale')
        self.assertIn('Document source changed or became unavailable', changed['stale_reason'])

    def test_company_knowledge_reads_a_file_only_while_the_interview_uses_it(self):
        document_id, source = self.file()
        resolve = self.httpd.knowledge.document_resolver
        self.assertEqual(resolve(self.scope, document_id, source['id'])['text'], source['text'])
        self.park(document_id)
        with self.assertRaises(PermissionError):
            resolve(self.scope, document_id, source['id'])
        # Assets still shows a parked file's own sources to the participant who holds its scope.
        status, shown = self.post('/api/documents/source', {'scope': self.scope, 'id': document_id, 'source_id': source['id']})
        self.assertEqual((status, shown['source']['text']), (200, source['text']))
        self.action(document_id, 'remove')
        with self.assertRaises(PermissionError):
            resolve(self.scope, document_id, source['id'])


class RetainedCatalogGraphTests(unittest.TestCase):
    """The store binds saved excerpts to their own manifest and never treats them as active file evidence."""
    DOCUMENT = 'doc_' + 'a' * 24
    SOURCE = DOCUMENT + '_r1_c1'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def evidence(self, **flags):
        return {'id': self.SOURCE, 'document_id': self.DOCUMENT, 'name': 'returns-log.csv', 'label': 'rows 1-2',
                'text': 'A1=return | B1=reason', **flags}

    def submission(self, first, retained=True, turns=True):
        body = payload('Returns intake', 'I check each return against the returns log.')
        if not turns:
            body['turns'] = []
        body['draft']['steps'][0]['evidence_turns'] = list(first)
        entry = {'id': self.DOCUMENT, 'name': 'returns-log.csv', 'sources': [{'source_id': self.SOURCE, 'label': 'rows 1-2'}]}
        body['documents'] = {'documents': [], 'retained': [{**entry, 'archived': True}]} if retained else {'documents': [entry]}
        return body

    def test_saved_excerpt_is_stored_with_its_flags_beside_other_evidence(self):
        receipt = self.graph.submit(self.submission([self.SOURCE, 'u1']), document_scope='private-scope',
                                    document_evidence=[self.evidence(retained_only=True, archived=True, disposition='relevant')])
        saved = self.graph.admin_detail('submission', receipt['submission_id'], 1)['item']
        entry = saved['document_evidence'][0]
        self.assertEqual((entry['retained_only'], entry['archived'], entry['disposition']), (True, True, 'relevant'))
        self.assertEqual(entry['text'], 'A1=return | B1=reason')
        self.assertNotIn('private-scope', kg.dumps(saved))

    def test_saved_and_active_sources_are_bound_to_their_own_manifests(self):
        cases = ((self.submission([self.SOURCE, 'u1'], retained=False), self.evidence(retained_only=True, archived=True)),
                 (self.submission([self.SOURCE, 'u1'], retained=False), self.evidence(disposition='parked')),
                 (self.submission([self.SOURCE, 'u1'], retained=True), self.evidence()))
        for body, evidence in cases:
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, 'unavailable or not authorized'):
                self.graph.submit(body, document_scope='private-scope', document_evidence=[evidence])
        self.assertEqual(self.graph.admin_browse('submissions')['items'], [])

    def test_new_process_cannot_rest_on_a_saved_excerpt_alone_but_a_revision_may_keep_it(self):
        saved = self.evidence(retained_only=True, archived=True, disposition='relevant')
        with self.assertRaisesRegex(ValueError, 'new process cannot rest'):
            self.graph.submit(self.submission([self.SOURCE]), document_scope='private-scope', document_evidence=[saved])
        self.assertEqual(self.graph.admin_browse('submissions')['items'], [])
        # Revision 1 holds the passage, filed while the file was in use.
        first = self.graph.submit(self.submission([self.SOURCE, 'u1'], retained=False), document_scope='private-scope',
                                  document_evidence=[self.evidence()])
        self.assertEqual(self.graph.filed_document_sources(first['process_id']), {self.SOURCE})
        revision = self.submission([self.SOURCE])
        revision['process_id'] = first['process_id']
        second = self.graph.submit(revision, document_scope='private-scope', document_evidence=[saved])
        self.assertEqual(second['revision'], 2)
        step = self.graph.admin_detail('submission', second['submission_id'], 2)['item']['draft']['steps'][0]
        self.assertEqual(step['evidence_turns'], [self.SOURCE])

    def test_revision_may_keep_only_a_saved_excerpt_that_an_earlier_revision_of_the_same_process_holds(self):
        saved = self.evidence(retained_only=True, archived=True, disposition='relevant')
        other = self.DOCUMENT + '_r2_c1'
        unfiled = {**saved, 'id': other, 'text': 'A2=RET-1 | B2=damaged'}

        def revision_of(receipt, first, sources=(self.SOURCE,)):
            body = self.submission(first)
            body['documents']['retained'][0]['sources'] = [{'source_id': source, 'label': 'rows'} for source in sources]
            body['process_id'] = receipt['process_id']
            return body

        # A process that never filed the passage: its revision is judged like a new process.
        plain = self.graph.submit(payload('Returns intake', 'I check each return against the returns log.'))
        self.assertEqual(self.graph.filed_document_sources(plain['process_id']), set())
        with self.assertRaisesRegex(ValueError, 'no earlier revision of this process holds'):
            self.graph.submit(revision_of(plain, [self.SOURCE]), document_scope='private-scope', document_evidence=[saved])
        # Beside an answer it is stored, flagged; from then on this process holds it.
        second = self.graph.submit(revision_of(plain, [self.SOURCE, 'u1']), document_scope='private-scope', document_evidence=[saved])
        self.assertEqual(second['revision'], 2)
        third = self.graph.submit(revision_of(plain, [self.SOURCE]), document_scope='private-scope', document_evidence=[saved])
        self.assertEqual(third['revision'], 3)
        # A held passage does not carry a new one from the removed file in with it.
        with self.assertRaisesRegex(ValueError, 'no earlier revision of this process holds'):
            self.graph.submit(revision_of(plain, [self.SOURCE, other], sources=(self.SOURCE, other)),
                              document_scope='private-scope', document_evidence=[saved, unfiled])
        # What another process holds does not count.
        elsewhere = self.graph.submit(payload('Returns audit', 'I audit the returns log each month.'))
        with self.assertRaisesRegex(ValueError, 'no earlier revision of this process holds'):
            self.graph.submit(revision_of(elsewhere, [self.SOURCE]), document_scope='private-scope', document_evidence=[saved])
        self.assertEqual(sorted(item['revision'] for item in self.graph.admin_browse('submissions')['items']), [1, 1, 2, 3],
                         'The three refused revisions stored nothing')

    def test_saved_excerpts_do_not_count_as_document_evidence_for_a_capture_without_answers(self):
        first = self.graph.submit(payload('Returns intake', 'I check each return against the returns log.'))
        revision = self.submission([self.SOURCE], turns=False)
        for item in [*revision['draft']['steps'], *revision['draft']['connections']]:
            item['evidence_turns'] = [self.SOURCE]
        revision['process_id'] = first['process_id']
        with self.assertRaisesRegex(ValueError, 'participant statement or verified document evidence'):
            self.graph.submit(revision, document_scope='private-scope',
                              document_evidence=[self.evidence(retained_only=True, archived=True, disposition='relevant')])

    def test_file_behind_a_saved_excerpt_is_never_resolved_again(self):
        reads = []
        self.graph.document_resolver = lambda scope, document_id, source_id: reads.append(source_id) or {'text': 'A1=return | B1=reason'}
        receipt = self.graph.submit(self.submission([self.SOURCE, 'u1']), document_scope='private-scope',
                                    document_evidence=[self.evidence(retained_only=True, archived=True, disposition='relevant')])
        with self.graph.lock:
            record = self.graph._revision(receipt['submission_id'], 1)
        self.assertEqual(self.graph._with_document_excerpts(record)['document_excerpts'], [])
        with self.assertRaises(ValueError):
            self.graph._document_source(receipt['submission_id'], 1, self.DOCUMENT, self.SOURCE)
        with self.assertRaises(PermissionError):
            self.graph.document_scope(receipt['submission_id'], 1, self.DOCUMENT)
        self.assertEqual(reads, [])


if __name__ == '__main__':
    unittest.main()
