"""Matching jobs left waiting are picked up again (knowledge-store-1).

A job stays 'pending' when the app stopped before it ran, when it was interrupted, or when no
provider was configured at Submit. The next start with an analyzer runs it. The submitter's
status shows whether analysis has started.
Temporary SQLite; the analyzer is injected, no provider or network.
"""
import knowledge_rows as rows
import os
import tempfile
import threading
import unittest
from pathlib import Path

from test_knowledge_graph import kg, payload, proposal, wait


class JobResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'graph.db'
        self.graph = kg.KnowledgeGraph(self.path)

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def reopen(self, analyzer=None):
        self.graph.close()
        self.graph = kg.KnowledgeGraph(self.path, analyzer)
        return self.graph

    def jobs(self):
        return {row['id']: row for row in rows.jobs(self.graph)}

    def test_jobs_submitted_without_a_provider_run_at_the_next_start_with_one(self):
        first = self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        second = self.graph.submit(payload('Statements', 'We use approved NAV.'))
        self.assertEqual({row['status'] for row in self.jobs().values()}, {'pending'})
        order = []
        def analyzer(current, candidates):
            order.append(current['submission_id'])
            return proposal(current, candidates)
        self.reopen(analyzer)
        self.assertEqual(wait(self.graph, first['job_id'])['status'], 'completed')
        self.assertEqual(wait(self.graph, second['job_id'])['status'], 'completed')
        # Oldest first; each job compared its process with the other and stored its proposal.
        self.assertEqual(order, [first['submission_id'], second['submission_id']])
        self.assertEqual(len(rows.proposals(self.graph)), 2)

    def test_a_job_interrupted_by_a_stopped_process_runs_again(self):
        self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        second = self.graph.submit(payload('Statements', 'We use approved NAV.'))
        with self.graph.db:  # As a process that was killed mid-analysis left it: claimed by a PID that is gone.
            self.graph.db.execute("UPDATE jobs SET status='processing',attempts=1,owner_pid=? WHERE id=?", (2 ** 31 - 2, second['job_id']))
        self.reopen(proposal)
        row = wait(self.graph, second['job_id'])
        self.assertEqual((row['status'], row['attempts'], row['error']), ('completed', 2, ''))

    def test_without_a_provider_nothing_is_scheduled_and_jobs_stay_pending(self):
        first = self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        self.reopen(None)
        self.assertEqual(self.jobs()[first['job_id']]['status'], 'pending')
        self.assertEqual(self.graph.queued_jobs, set())

    def test_a_job_that_keeps_being_interrupted_is_not_resumed_forever(self):
        first = self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        second = self.graph.submit(payload('Statements', 'We use approved NAV.'))
        with self.graph.db:
            self.graph.db.execute('UPDATE jobs SET attempts=? WHERE id=?', (kg.KnowledgeGraph.AUTO_RESUME_ATTEMPTS, second['job_id']))
        calls = []
        self.reopen(lambda current, candidates: calls.append(current['submission_id']) or [])
        self.assertEqual(wait(self.graph, first['job_id'])['status'], 'completed')
        self.graph.executor.submit(lambda: None).result(3)  # Everything that was scheduled has run.
        self.assertEqual(calls, [first['submission_id']])
        self.assertEqual(self.jobs()[second['job_id']]['status'], 'failed')

    def test_status_at_attempt_limit_settles_only_the_callers_pending_job(self):
        stopped = self.graph.submit(payload('Publishing', 'We publish NAV.'))
        active = self.graph.submit(payload('Statements', 'We receive NAV.'))
        with self.graph.db:
            self.graph.db.execute('UPDATE jobs SET attempts=?', (self.graph.AUTO_RESUME_ATTEMPTS,))
            self.graph.db.execute("UPDATE jobs SET status='processing',owner_pid=? WHERE id=?", (os.getpid(), active['job_id']))
        self.assertEqual(self.graph.status(stopped['submission_id'], 1, stopped['status_token'])['status'], 'failed')
        self.assertEqual(self.graph.status(active['submission_id'], 1, active['status_token'])['status'], 'processing')
        self.reopen(None)
        self.assertEqual(self.graph.status(active['submission_id'], 1, active['status_token'])['status'], 'processing')

    def test_an_outdated_pending_revision_is_superseded_not_analysed(self):
        first = self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        revised = dict(payload('Publishing', 'We publish corrected NAV.'), process_id=first['process_id'])
        second = self.graph.submit(revised)
        calls = []
        self.reopen(lambda current, candidates: calls.append(current['revision']) or [])
        self.assertEqual(wait(self.graph, first['job_id'])['status'], 'superseded')
        self.assertEqual(wait(self.graph, second['job_id'])['status'], 'completed')
        self.assertEqual(calls, [])  # The only other record is the same process: no candidates, no call.

    def test_two_instances_on_one_store_run_a_waiting_job_once(self):
        self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        second = self.graph.submit(payload('Statements', 'We use approved NAV.'))
        calls = []
        lock = threading.Lock()
        def analyzer(current, candidates):
            with lock:
                calls.append(current['submission_id'])
            return []
        self.reopen(analyzer)
        peer = kg.KnowledgeGraph(self.path, analyzer)
        try:
            wait(self.graph, second['job_id'])
            for graph in (self.graph, peer):
                graph.executor.submit(lambda: None).result(3)
        finally:
            peer.close()
        self.assertEqual(sorted(calls), sorted(set(calls)), 'No job was analysed twice')
        self.assertEqual(len(calls), 2)

    def test_status_shows_a_waiting_job_and_its_completion_with_a_provider(self):
        receipt = self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        status = self.graph.status(receipt['submission_id'], 1, receipt['status_token'])
        self.assertEqual((status['status'], status['stalled']), ('pending', True))
        # With a provider the same job is simply waiting its turn, or done.
        self.reopen(lambda current, candidates: [])
        wait(self.graph, receipt['job_id'])
        status = self.graph.status(receipt['submission_id'], 1, receipt['status_token'])
        self.assertEqual((status['status'], status['stalled']), ('completed', False))

    def test_status_requeues_the_callers_own_waiting_job(self):
        # A provider configured on a running instance (or a job whose worker entry was lost): the submitter's
        # status check starts it.
        receipt = self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        self.graph.analyzer = lambda current, candidates: []
        status = self.graph.status(receipt['submission_id'], 1, receipt['status_token'])
        self.assertEqual((status['status'], status['stalled']), ('pending', False))
        self.assertEqual(wait(self.graph, receipt['job_id'])['status'], 'completed')
        with self.assertRaises(PermissionError):
            self.graph.status(receipt['submission_id'], 1, 'f' * 64)

    def test_interrupted_text_reaches_the_submitter(self):
        receipt = self.graph.submit(payload('Publishing', 'We publish approved NAV.'))
        with self.graph.db:
            self.graph.db.execute("UPDATE jobs SET status='processing',attempts=?,owner_pid=?", (kg.KnowledgeGraph.AUTO_RESUME_ATTEMPTS, 2 ** 31 - 2))
        self.reopen(proposal)
        status = self.graph.status(receipt['submission_id'], 1, receipt['status_token'])
        self.assertEqual((status['status'], status['stalled']), ('failed', False))
        self.assertIn('reached its attempt limit', status['error'])
        self.assertEqual(status['latest_revision'], 1)


if __name__ == '__main__':
    unittest.main()
