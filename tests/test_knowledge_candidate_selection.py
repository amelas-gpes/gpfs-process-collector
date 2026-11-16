"""Matching finds a compatible process behind any number of newer other-scope ones (knowledge-store-3).

Candidates were the 30 most recent submissions, filtered by scope afterwards: a same-scope process older
than 30 other-scope submissions was never compared and the job still said 'completed'.
Temporary SQLite; the analyzer is injected, no provider or network.
"""
import knowledge_rows as rows
import tempfile
import unittest
from pathlib import Path

from test_knowledge_graph import kg, payload, wait

import importlib.util
spec = importlib.util.spec_from_file_location('knowledge_ai', Path(__file__).resolve().parents[1] / 'knowledge_ai.py')
knowledge_ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(knowledge_ai)


def wait_pending(graph, job):
    return next(row for row in rows.jobs(graph) if row['id'] == job)


class CandidateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')
        self.seen = []

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def file(self, name, scope):
        return self.graph.submit(payload(name, 'We report an input and an output.', scope))

    def match(self, name, scope):
        def analyzer(current, candidates):
            self.seen.append(candidates)
            return []
        self.graph.analyzer = analyzer
        receipt = self.graph.submit(payload(name, 'We receive approved data.', scope))
        row = wait(self.graph, receipt['job_id'])
        self.assertEqual(row['status'], 'completed')
        return row

    def scopes(self):
        return [item['scope'] for item in self.seen[-1]] if self.seen else None

    def test_same_scope_process_older_than_thirty_other_scope_submissions_is_compared(self):
        old = self.file('Fund A valuation', 'Fund A')
        for index in range(35):
            self.file(f'Fund B process {index}', 'Fund B')
        row = self.match('Fund A statements', 'Fund A')
        self.assertEqual(len(self.seen), 1, 'The analyzer is invoked: a compatible process is stored')
        self.assertEqual([item['submission_id'] for item in self.seen[0]], [old['submission_id']])
        self.assertEqual((row['detail']['candidates'], row['detail']['candidates_omitted']), (1, 0))

    def test_scope_is_compared_without_case_and_an_unscoped_process_is_compatible(self):
        self.file('Upper', 'FUND A')
        self.file('Unscoped', '')
        for index in range(31):
            self.file(f'Other {index}', 'Fund B')
        self.match('Lower', 'fund a')
        self.assertEqual(sorted(self.scopes()), ['', 'FUND A'])

    def test_an_unscoped_submission_is_compared_with_the_most_recent_of_any_scope(self):
        for index in range(10):
            self.file(f'Process {index}', 'Fund A' if index % 2 else 'Fund B')
        row = self.match('Unscoped', '')
        self.assertEqual(len(self.seen[0]), 8)
        self.assertEqual([item['context']['process_name'] for item in self.seen[0]], [f'Process {index}' for index in range(9, 1, -1)], 'The eight most recent')
        self.assertEqual((row['detail']['candidates'], row['detail']['candidates_omitted']), (8, 2))

    def test_only_incompatible_processes_means_no_call_and_says_so(self):
        for index in range(3):
            self.file(f'Other {index}', 'Fund B')
        row = self.match('Alone', 'Fund A')
        self.assertEqual(self.seen, [])
        self.assertEqual((row['detail']['candidates'], row['detail']['candidates_omitted']), (0, 0))

    def test_the_latest_revision_decides_a_process_scope_and_each_process_is_one_candidate(self):
        moved = self.file('Moved', 'Fund A')
        self.graph.submit({**payload('Moved', 'We moved to another fund.', 'Fund B'), 'process_id': moved['process_id']})
        stays = self.file('Stays', 'Fund B')
        self.graph.submit({**payload('Stays', 'A correction.', 'Fund B'), 'process_id': stays['process_id']})
        self.match('Fund A statements', 'Fund A')
        self.assertEqual(self.seen, [], 'Revision 1 of a process that has left the scope is not a candidate')
        self.match('Fund B statements', 'Fund B')
        self.assertEqual(sorted((item['context']['process_name'], item['revision']) for item in self.seen[-1]), [('Moved', 2), ('Stays', 2)])

    def test_a_store_written_before_the_job_detail_column_is_upgraded_in_place(self):
        receipt = self.file('Fund A valuation', 'Fund A')
        with self.graph.db:
            self.graph.db.execute('ALTER TABLE jobs DROP COLUMN detail')  # The jobs table as an earlier build left it.
        path = Path(self.temp.name) / 'graph.db'
        self.graph.close()
        self.graph = kg.KnowledgeGraph(path)
        self.assertEqual(wait_pending(self.graph, receipt['job_id'])['detail'], {})
        row = self.match('Fund A statements', 'Fund A')
        self.assertEqual((row['detail']['candidates'], row['detail']['candidates_omitted']), (1, 0))

    def test_the_compatible_processes_left_out_are_counted_and_reach_the_provider_request(self):
        for index in range(11):
            self.file(f'Fund A process {index}', 'Fund A')
        for index in range(31):
            self.file(f'Fund B process {index}', 'Fund B')
        row = self.match('Fund A statements', 'Fund A')
        self.assertEqual(len(self.seen[0]), 8)
        self.assertEqual(set(self.scopes()), {'Fund A'})
        self.assertEqual(self.seen[0].omitted, 3)
        self.assertEqual((row['detail']['candidates'], row['detail']['candidates_omitted']), (8, 3))
        # The real adapter tells the model: before, the count came from the already trimmed list and was always 0.
        sent = []
        class Client:
            def structured(self, instructions, body, schema, name, max_tokens):
                sent.append(body)
                return {'proposals': []}
        current = self.graph._revision(row['submission_id'], row['revision'])
        self.assertEqual(knowledge_ai.build_analyzer(Client())(current, self.seen[0]), [])
        self.assertEqual((len(sent[0]['candidates']), sent[0]['candidates_omitted']), (8, 3))
        self.assertEqual(knowledge_ai.build_analyzer(Client())(current, list(self.seen[0])), [])
        self.assertEqual(sent[1]['candidates_omitted'], 0, 'A plain list, as other callers pass, counts as nothing omitted')


if __name__ == '__main__':
    unittest.main()
