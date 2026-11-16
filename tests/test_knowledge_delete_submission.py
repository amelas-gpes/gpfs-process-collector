"""An administrator can remove a submitted process where the owner enabled it (gap-privacy-3).

KnowledgeGraph.delete_submission removes every revision of one process and everything derived from it,
and keeps a record without content. The route is off unless KNOWLEDGE_ADMIN_DELETE=true.
Real server and store on temporary folders; the analyzer is injected, no provider or network.
"""
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server
from test_knowledge_graph import kg, payload, proposal, wait

NAME, TRANSCRIPT, EXCERPT = 'Odalys ZQNAME Brenneman', 'ZQTRANSCRIPT-5512 we wire account 00-ZQACCT-77.', 'ZQEXCERPT-9917 limits table'
DOC = 'doc_' + 'd' * 32
SOURCE = DOC + '_p1_c1'
SENTINELS = ('ZQNAME', 'ZQTRANSCRIPT', 'ZQACCT', 'ZQEXCERPT', 'ZQTEAM', 'private-scope-token')


def private_account(**extra):
    body = payload('Wire release', TRANSCRIPT)
    body.update(participant=NAME, team='ZQTEAM treasury', submission_key=str(uuid.uuid4()),
                documents={'documents': [{'id': DOC, 'name': 'limits.pdf', 'sources': [{'source_id': SOURCE}]}]})
    body['draft']['steps'][0]['evidence_turns'] = ['u1', SOURCE]
    body.update(extra)
    return body


def evidence():
    return [{'id': SOURCE, 'document_id': DOC, 'name': 'limits.pdf', 'label': 'limits.pdf · page 1', 'text': EXCERPT, 'location': {'page': 1}}]


class DeleteSubmissionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'graph.db'
        self.graph = kg.KnowledgeGraph(self.path, proposal)
        self.kept = self.graph.submit(payload('Statements', 'We use approved NAV.'))
        wait(self.graph, self.kept['job_id'])
        self.first = self.graph.submit(private_account(), document_scope='private-scope-token', document_evidence=evidence())
        wait(self.graph, self.first['job_id'])
        revised = private_account(process_id=self.first['process_id'])
        revised['turns'][0]['text'] = TRANSCRIPT + ' Corrected.'
        self.second = self.graph.submit(revised, document_scope='private-scope-token', document_evidence=evidence())
        wait(self.graph, self.second['job_id'])
        self.sid = self.first['submission_id']

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def count(self, sql, *args):
        with self.graph.lock:
            return self.graph.db.execute(sql, args).fetchone()[0]

    def group_with_a_member_of_each(self):
        with self.graph.lock:
            systems = [row[0] for row in self.graph.db.execute(
                "SELECT e.id FROM entities e WHERE e.type='system' AND e.revision=(SELECT MAX(revision) FROM revisions r WHERE r.submission_id=e.submission_id)")]
        return self.graph.canonical_create('Ledger', systems, 'reviewer', 'Same system')

    def test_everything_of_the_process_is_removed_and_the_rest_is_kept(self):
        proposals = self.graph.admin_snapshot()['proposals']
        self.assertTrue(proposals, 'The fixture has a connection that quotes the process')
        live = next(item for item in proposals if item['status'] == 'proposed')
        self.graph.review(live['id'], 'confirm', 'owner', 'Checked', live['review_version'])
        group = self.group_with_a_member_of_each()
        self.assertEqual(len(group['members']), 2)

        result = self.graph.delete_submission(self.sid, 'local-owner', 'Named a client by mistake', 2)
        self.assertEqual((result['deleted'], result['revisions'], result['groups_for_review']), (True, 2, 1))
        self.assertEqual(result['proposals'], len(proposals))

        for table in ('revisions', 'entities', 'edges', 'jobs', 'status_capabilities', 'private_documents'):
            self.assertEqual(self.count(f'SELECT COUNT(*) FROM {table} WHERE submission_id=?', self.sid), 0, table)
        self.assertEqual(self.count('SELECT COUNT(*) FROM submission_keys'), 0)
        self.assertEqual(self.count('SELECT COUNT(*) FROM proposals'), 0)
        self.assertEqual(self.count('SELECT COUNT(*) FROM review_history'), 0)
        # The other process is untouched, and the reviewed group it shared goes back for review with one member.
        snapshot = self.graph.admin_snapshot()
        self.assertEqual([item['submission_id'] for item in snapshot['submissions']], [self.kept['submission_id']])
        self.assertTrue(all(item['submission_id'] == self.kept['submission_id'] for item in snapshot['entities'] + snapshot['edges'] + snapshot['jobs']))
        after = snapshot['canonical_groups'][0]
        self.assertEqual((after['status'], len(after['members'])), ('stale', 1))
        self.assertEqual(after['history'][-1]['action'], 'stale')
        self.assertIn('deleted', after['stale_reason'])
        self.assertEqual(self.graph.admin_browse('overview')['counts']['submissions'], 1)

    def test_the_record_of_the_deletion_has_no_content_and_the_file_no_longer_holds_the_text(self):
        self.graph.delete_submission(self.sid, 'local-owner', 'Erasure request', 2)
        with self.graph.lock:
            record = dict(self.graph.db.execute('SELECT * FROM deletions').fetchone())
        self.assertEqual((record['submission_id'], record['process_id'], record['revisions'], record['reviewer'], record['reason']),
                         (self.sid, self.first['process_id'], 2, 'local-owner', 'Erasure request'))
        self.assertEqual(set(record), {'id', 'submission_id', 'process_id', 'revisions', 'proposals', 'reviewer', 'reason', 'created_at'})
        dumped = json.dumps(self.graph.admin_snapshot())
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, dumped)
        # secure_delete and the checkpoint: the bytes are gone from the database file and its write-ahead log.
        self.graph.close()
        stored = b''.join(path.read_bytes() for path in self.path.parent.iterdir() if path.name.startswith(self.path.name))
        self.graph = kg.KnowledgeGraph(self.path)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel.encode(), stored, sentinel)
        self.assertIn(b'We use approved NAV.', stored, 'The other process is still stored')

    def test_the_latest_revision_shown_must_be_named(self):
        for expected in (1, 3, None, True, '2'):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, 'refresh before deleting'):
                self.graph.delete_submission(self.sid, 'local-owner', 'Reason', expected)
        self.assertEqual(self.count('SELECT COUNT(*) FROM revisions WHERE submission_id=?', self.sid), 2)
        self.assertEqual(self.count('SELECT COUNT(*) FROM deletions'), 0)

    def test_reviewer_reason_and_a_known_submission_are_required(self):
        for reviewer, reason in (('', 'Reason'), ('local-owner', ''), ('local-owner', '   ')):
            with self.subTest(reviewer=reviewer, reason=reason), self.assertRaisesRegex(ValueError, 'reviewer and a reason'):
                self.graph.delete_submission(self.sid, reviewer, reason, 2)
        with self.assertRaisesRegex(ValueError, 'Submission is unavailable'):
            self.graph.delete_submission(str(uuid.uuid4()), 'local-owner', 'Reason', 1)
        with self.assertRaisesRegex(ValueError, 'valid submission'):
            self.graph.delete_submission('not-an-id', 'local-owner', 'Reason', 1)
        self.assertEqual(self.count('SELECT COUNT(*) FROM revisions'), 3)

    def test_the_submitter_is_told_and_the_process_cannot_be_revised(self):
        self.graph.delete_submission(self.sid, 'local-owner', 'Reason', 2)
        for receipt in (self.first, self.second):
            status = self.graph.status(receipt['submission_id'], receipt['revision'], receipt['status_token'])
            self.assertEqual((status['status'], status['job_id'], status['stalled']), ('deleted', None, False))
        for token in ('f' * 64, self.kept['status_token']):
            with self.assertRaises(PermissionError):
                self.graph.status(self.sid, 1, token)
        with self.assertRaises(PermissionError):
            self.graph.status(self.sid, 3, self.graph._status_token(self.sid, 3))  # No such revision was ever filed.
        with self.assertRaisesRegex(ValueError, 'Process does not exist'):
            self.graph.submit(private_account(process_id=self.first['process_id']))
        with self.assertRaisesRegex(ValueError, 'Submission is unavailable'):
            self.graph.delete_submission(self.sid, 'local-owner', 'Again', 2)

    def test_matching_that_was_running_stores_nothing_about_a_deleted_process(self):
        entered, release = threading.Event(), threading.Event()
        def slow(current, candidates):
            entered.set()
            release.wait(5)
            return proposal(current, [item for item in candidates if item['submission_id'] == self.sid])
        self.graph.analyzer = slow
        third = self.graph.submit(payload('Reporting', 'We report approved NAV.'))
        self.assertTrue(entered.wait(3))
        self.graph.delete_submission(self.sid, 'local-owner', 'Reason', 2)
        release.set()
        self.assertEqual(wait(self.graph, third['job_id'])['status'], 'completed')
        self.assertEqual(self.graph.admin_snapshot()['proposals'], [])


class DeleteSubmissionRouteTests(unittest.TestCase):
    OWNER = {'COLLECTOR_DEPLOYMENT_MODE': 'local', 'KNOWLEDGE_LOCAL_OWNER': 'true'}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.running = []

    def tearDown(self):
        for httpd, worker in self.running:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=3)
        self.temp.cleanup()

    def serve(self, settings):
        root = Path(self.temp.name) / str(len(self.running))
        httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=server.OpenAIClient({}),
                                       documents_root=root / 'documents', knowledge_root=root / 'graph', knowledge_settings=settings)
        worker = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        self.running.append((httpd, worker))
        return httpd

    def call(self, httpd, path, body=None):
        request = Request(f'http://127.0.0.1:{httpd.server_port}{path}', data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'X-CSRF-Token': httpd.csrf_token})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def filed(self, httpd):
        status, receipt = self.call(httpd, '/api/knowledge/submit', private_account(documents=None, draft=None))
        self.assertEqual(status, 202)
        return receipt

    def request(self, receipt, **changes):
        return {'submission_id': receipt['submission_id'], 'expected_revision': 1, 'reason': 'Erasure request', 'confirm': 'DELETE', **changes}

    def total(self, httpd):
        return httpd.knowledge.admin_browse('submissions')['page']['total']

    def test_deleting_is_off_by_default_even_for_the_local_owner(self):
        httpd = self.serve(self.OWNER)
        receipt = self.filed(httpd)
        self.assertIs(self.call(httpd, '/api/config')[1]['knowledge_delete_enabled'], False)
        status, result = self.call(httpd, '/api/knowledge/admin/delete', self.request(receipt))
        self.assertEqual((status, result['error']), (403, 'Deleting a submitted process is not enabled on this computer.'))
        self.assertEqual(self.total(httpd), 1)

    def test_the_switch_alone_does_not_make_an_administrator(self):
        httpd = self.serve({'KNOWLEDGE_ADMIN_DELETE': 'true'})
        receipt = self.filed(httpd)
        status, result = self.call(httpd, '/api/knowledge/admin/delete', self.request(receipt))
        self.assertEqual((status, result['error']), (403, 'Administrator access is unavailable.'))
        self.assertEqual(self.total(httpd), 1)

    def test_an_administrator_deletes_with_the_switch_the_latest_revision_and_the_typed_word(self):
        httpd = self.serve({**self.OWNER, 'KNOWLEDGE_ADMIN_DELETE': 'true'})
        receipt = self.filed(httpd)
        self.assertIs(self.call(httpd, '/api/config')[1]['knowledge_delete_enabled'], True)
        detail = self.call(httpd, '/api/knowledge/admin/detail', {'kind': 'submission', 'id': receipt['submission_id'], 'revision': 1})[1]['item']
        self.assertEqual(detail['latest_revision'], 1)
        for changes, message in (({'confirm': 'delete'}, 'Type DELETE'), ({'confirm': None}, 'Type DELETE'), ({'reason': ' '}, 'Reason for the deletion'),
                                 ({'expected_revision': True}, 'latest revision you reviewed'), ({'expected_revision': 2}, 'refresh before deleting'),
                                 ({'example': True}, 'fictional example')):
            with self.subTest(changes=changes):
                status, result = self.call(httpd, '/api/knowledge/admin/delete', self.request(receipt, **changes))
                self.assertEqual(status, 400)
                self.assertIn(message, result['error'])
                self.assertEqual(self.total(httpd), 1)
        status, result = self.call(httpd, '/api/knowledge/admin/delete', self.request(receipt))
        self.assertEqual((status, result['deleted'], result['revisions']), (200, True, 1))
        self.assertEqual(self.total(httpd), 0)
        status, answer = self.call(httpd, '/api/knowledge/status', {key: receipt[key] for key in ('submission_id', 'revision', 'status_token')})
        self.assertEqual((status, answer['status']), (200, 'deleted'))
        with httpd.knowledge.lock:
            reviewer = httpd.knowledge.db.execute('SELECT reviewer FROM deletions').fetchone()[0]
        self.assertEqual(reviewer, 'local-owner', 'The reviewer is the server-side identity, not a browser field')


if __name__ == '__main__':
    unittest.main()
