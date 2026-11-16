"""A revision must come from a copy that is based on the latest one (gap3-reopen-continue-2).

Opening an older saved copy, or a stale tab, and pressing Submit made that older interview the newest
revision with no warning. The submit route now takes base_revision; the store refuses a revision whose
base is not the latest (409) until the submitter confirms it, naming the latest revision.
Real server and store on temporary folders, local-owner mode; no provider or network.
"""
import knowledge_rows as rows
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server
from test_knowledge_graph import kg, payload


def account(text, **extra):
    return {**payload('Registration', text), 'submission_key': str(uuid.uuid4()), **extra}


class BaseRevisionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')
        self.first = self.graph.submit(account('Registration is due by 10 a.m.'))
        self.revise = lambda text, **arguments: self.graph.submit(account(text, process_id=self.first['process_id']), **arguments)
        self.second = self.revise('Correction: registration is due by 11 a.m., not 10 a.m.', base_revision=1)

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def revisions(self):
        return sorted(row['revision'] for row in rows.submissions(self.graph))

    def test_a_copy_based_on_the_latest_revision_is_accepted(self):
        self.assertEqual(self.second['revision'], 2)
        self.assertEqual(self.revise('A later answer.', base_revision=2)['revision'], 3)

    def test_an_older_copy_is_refused_and_nothing_is_stored(self):
        with self.assertRaises(kg.RevisionConflict) as refused:
            self.revise('Registration is due by 10 a.m.', base_revision=1)
        self.assertEqual((refused.exception.base_revision, refused.exception.latest_revision), (1, 2))
        self.assertRegex(str(refused.exception), r'A newer revision \(2\) of this process exists\. This copy is based on revision 1\.')
        self.assertEqual(self.revisions(), [1, 2])
        self.assertEqual(len(rows.jobs(self.graph)), 2)

    def test_confirming_the_latest_revision_files_the_older_copy(self):
        third = self.revise('Registration is due by 10 a.m.', base_revision=1, acknowledged_revision=2)
        self.assertEqual(third['revision'], 3)
        self.assertEqual(self.revisions(), [1, 2, 3])

    def test_a_confirmation_of_an_outdated_revision_does_not_pass(self):
        # The submitter confirmed over revision 2; meanwhile revision 3 was filed.
        self.revise('Third account.', base_revision=2)
        with self.assertRaises(kg.RevisionConflict) as refused:
            self.revise('Registration is due by 10 a.m.', base_revision=1, acknowledged_revision=2)
        self.assertEqual(refused.exception.latest_revision, 3)
        self.assertEqual(self.revisions(), [1, 2, 3])

    def test_a_copy_that_does_not_know_its_revision_must_confirm(self):
        with self.assertRaisesRegex(kg.RevisionConflict, 'does not record which revision it is based on'):
            self.revise('Registration is due by 10 a.m.', base_revision=0)
        self.assertEqual(self.revise('Registration is due by 10 a.m.', base_revision=0, acknowledged_revision=2)['revision'], 3)

    def test_a_base_beyond_the_latest_revision_is_refused_without_calling_it_newer(self):
        with self.assertRaises(kg.RevisionConflict) as refused:
            self.revise('From another store.', base_revision=7)
        self.assertNotIn('newer revision', str(refused.exception))
        self.assertIn('latest stored revision of this process is 2', str(refused.exception))

    def test_callers_that_send_no_base_and_new_processes_are_unaffected(self):
        self.assertEqual(self.revise('An API client without a base.')['revision'], 3)
        fresh = self.graph.submit(account('A different process.'), base_revision=5)
        self.assertEqual(fresh['revision'], 1)

    def test_a_repeated_key_is_recovered_before_the_check(self):
        body = account('Late answer.', process_id=self.first['process_id'])
        third = self.graph.submit(dict(body), base_revision=2)
        again = self.graph.submit(dict(body), base_revision=2)  # The same attempt, resent after a lost response.
        self.assertEqual((again['revision'], again['job_id']), (third['revision'], third['job_id']))

    def test_invalid_revision_numbers_are_rejected(self):
        for value in (True, -1, '2', 2.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Invalid base revision'):
                self.revise('x', base_revision=value)
            with self.subTest(acknowledged=value), self.assertRaisesRegex(ValueError, 'Invalid base revision'):
                self.revise('x', base_revision=1, acknowledged_revision=value)

    def test_status_names_the_latest_revision_of_the_process(self):
        status = self.graph.status(self.first['submission_id'], 1, self.first['status_token'])
        self.assertEqual((status['revision'], status['latest_revision']), (1, 2))
        status = self.graph.status(self.second['submission_id'], 2, self.second['status_token'])
        self.assertEqual(status['latest_revision'], 2)


class BaseRevisionRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.httpd = server.InterviewServer(
            ('127.0.0.1', 0), server.Handler, client=server.OpenAIClient({}),
            documents_root=Path(self.temp.name) / 'documents', knowledge_root=Path(self.temp.name) / 'graph',
            knowledge_settings={'COLLECTOR_DEPLOYMENT_MODE': 'local', 'KNOWLEDGE_LOCAL_OWNER': 'true'})
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def post(self, path, body):
        request = Request(f'http://127.0.0.1:{self.httpd.server_port}{path}', data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_older_copy_gets_409_then_files_once_the_latest_revision_is_confirmed(self):
        status, first = self.post('/api/knowledge/submit', account('Registration is due by 10 a.m.'))
        self.assertEqual(status, 202)
        revision = lambda text, **extra: account(text, process_id=first['process_id'], **extra)
        status, second = self.post('/api/knowledge/submit', revision('Correction: due by 11 a.m.', base_revision=1))
        self.assertEqual((status, second['revision']), (202, 2))

        stale = revision('Registration is due by 10 a.m.', base_revision=1)
        status, refused = self.post('/api/knowledge/submit', stale)
        self.assertEqual(status, 409)
        self.assertEqual((refused['code'], refused['latest_revision'], refused['base_revision']), ('newer_revision_exists', 2, 1))
        self.assertIn('A newer revision (2) of this process exists', refused['error'])
        self.assertEqual(len(rows.submissions(self.httpd.knowledge)), 2, 'The refused copy was not stored')

        # The refusal stored nothing, so the same key may be resent with the confirmation.
        status, third = self.post('/api/knowledge/submit', {**stale, 'acknowledged_revision': 2})
        self.assertEqual((status, third['revision']), (202, 3))
        with self.httpd.knowledge.lock:
            detail = self.httpd.knowledge._revision(third['submission_id'], third['revision'])
        self.assertNotIn('base_revision', detail)
        self.assertNotIn('acknowledged_revision', detail)

        status, answer = self.post('/api/knowledge/status', {'submission_id': first['submission_id'], 'revision': 1, 'status_token': first['status_token']})
        self.assertEqual((status, answer['latest_revision']), (200, 3))

    def test_malformed_base_revision_is_a_plain_400(self):
        status, first = self.post('/api/knowledge/submit', account('Registration is due by 10 a.m.'))
        for value in (True, -1, '1', 1.5):
            with self.subTest(value=value):
                status, result = self.post('/api/knowledge/submit', account('x', process_id=first['process_id'], base_revision=value))
                self.assertEqual((status, result['error']), (400, 'Choose the revision this copy is based on.'))


if __name__ == '__main__':
    unittest.main()
