"""One unusable proposal no longer discards the usable ones (live-draft-knowledge-5).

A matching response is validated proposal by proposal: the valid ones are stored and the job completes;
a refused one is dropped (never stored) and counted with the validator's reason on the job row. A job
that does fail says whether the provider, the result or this app was the cause.
Temporary SQLite; the analyzer is injected, no provider or network.
"""
import knowledge_rows as rows
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_server import server
from test_knowledge_graph import kg, payload, proposal, wait

QUOTE_REASON = 'Evidence must quote an exact participant statement.'


class APIError(Exception):
    """Shaped like server.APIError: the name and an HTTP status."""
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class ProposalValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')
        self.events = []
        self.graph.diagnostic = lambda event, **fields: self.events.append((event, fields))
        self.others = [self.graph.submit(payload(name, f'We publish {name} to the next team.')) for name in ('NAV', 'fees', 'cash')]

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def run_job(self, analyzer):
        self.graph.analyzer = analyzer
        receipt = self.graph.submit(payload('Statements', 'We use approved NAV, fees and cash.'))
        return wait(self.graph, receipt['job_id'])

    def stored(self):
        return rows.proposals(self.graph)

    @staticmethod
    def one_per_candidate(current, candidates):
        return [proposal(current, [candidate])[0] for candidate in candidates]

    def test_the_valid_proposals_are_kept_when_one_quote_is_not_verbatim(self):
        def analyzer(current, candidates):
            items = self.one_per_candidate(current, candidates)
            items[1]['evidence'][0]['quote'] = items[1]['evidence'][0]['quote'][:12] + '…'  # Shortened with an ellipsis.
            return items
        row = self.run_job(analyzer)
        self.assertEqual((row['status'], row['error'], row['attempts']), ('completed', '', 1))
        metrics = {key: value for key, value in row['detail'].items() if key not in ('claim_token', 'claimed_at')}
        self.assertEqual(metrics, {'candidates': 3, 'candidates_omitted': 0, 'proposals_returned': 3, 'proposals_kept': 2,
                                         'proposals_dropped': 1, 'dropped_reasons': {QUOTE_REASON: 1}})
        self.assertEqual(len(self.stored()), 2)
        self.assertTrue(all('…' not in evidence['quote'] for item in self.stored() for evidence in item['evidence']), 'The refused proposal is not stored')
        self.assertEqual(self.events, [], 'A dropped proposal is not a failed job')

    def test_each_kind_of_refusal_drops_only_its_own_proposal_and_reasons_are_counted(self):
        def analyzer(current, candidates):
            good = self.one_per_candidate(current, candidates)
            paraphrased = copy.deepcopy(good[0]); paraphrased['evidence'][1]['quote'] = 'We use NAV.'
            one_sided = copy.deepcopy(good[1]); one_sided['evidence'] = [one_sided['evidence'][0], dict(one_sided['evidence'][0])]
            no_inference = copy.deepcopy(good[2]); no_inference['inference'] = ''
            wrong_revision = copy.deepcopy(good[2]); wrong_revision['source_revision'] = 7
            other_scope = copy.deepcopy(good[0]); other_scope['scope'] = 'Fund B'
            also_paraphrased = copy.deepcopy(good[1]); also_paraphrased['evidence'][0]['quote'] = 'They publish fees.'
            return good + [paraphrased, one_sided, no_inference, wrong_revision, other_scope, also_paraphrased, None, {'source_submission_id': ['unhashable']}]
        row = self.run_job(analyzer)
        self.assertEqual(row['status'], 'completed')
        self.assertEqual((row['detail']['proposals_returned'], row['detail']['proposals_kept'], row['detail']['proposals_dropped']), (11, 3, 8))
        self.assertEqual(row['detail']['dropped_reasons'], {
            QUOTE_REASON: 2, 'Proposal needs participant evidence from both processes.': 1, 'Proposal requires an explanation and inference.': 1,
            'Proposal references an unavailable revision.': 1, 'Proposal scope does not match its sources.': 1,
            'Invalid proposal.': 1, 'Malformed proposal.': 1})
        self.assertEqual(len(self.stored()), 3)

    def test_a_response_with_no_usable_proposal_completes_with_nothing_stored(self):
        def analyzer(current, candidates):
            items = self.one_per_candidate(current, candidates)
            for item in items:
                item['evidence'][0]['quote'] = 'Invented'
            return items
        row = self.run_job(analyzer)
        self.assertEqual((row['status'], row['detail']['proposals_kept'], row['detail']['dropped_reasons']), ('completed', 0, {QUOTE_REASON: 3}))
        self.assertEqual(self.stored(), [])

    def test_a_clean_response_records_no_reasons(self):
        row = self.run_job(self.one_per_candidate)
        metrics = {key: value for key, value in row['detail'].items() if key not in ('claim_token', 'claimed_at')}
        self.assertEqual(metrics, {'candidates': 3, 'candidates_omitted': 0, 'proposals_returned': 3, 'proposals_kept': 3, 'proposals_dropped': 0})

    def test_a_provider_error_is_named_as_such_with_its_own_sentence(self):
        def analyzer(current, candidates):
            raise APIError('PRIVATE-EXCEPTION-TEXT')
        row = self.run_job(analyzer)
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['error'], 'The AI provider did not complete the analysis.')
        self.assertEqual((row['detail']['error_kind'], row['detail']['error_class'], row['detail']['candidates']), ('provider', 'APIError', 3))
        self.assertEqual(self.events, [('knowledge_job_failed', {'error_category': 'provider', 'error_type': 'APIError'})])
        self.assertEqual(self.stored(), [])

    def test_the_servers_own_provider_error_is_recognised(self):
        def analyzer(current, candidates):
            raise server.APIError('OpenAI rate limit or quota reached. Check the account, then try again.', 429)
        row = self.run_job(analyzer)
        self.assertEqual(row['detail']['error_kind'], 'provider')
        self.assertIn('rate limit or quota', row['error'])

    def test_connection_result_and_internal_failures_are_told_apart(self):
        secret = 'ZQ-SECRET-IN-AN-EXCEPTION'
        cases = ((TimeoutError(secret), 'provider', 'The AI provider could not be reached.'),
                 (ConnectionResetError(secret), 'provider', 'The AI provider could not be reached.'),
                 (ValueError(secret), 'result', 'The analysis returned a result this app could not use.'),
                 (KeyError(secret), 'internal', 'Analysis stopped on an internal error in this app (KeyError).'),
                 (sqlite3.OperationalError(secret), 'internal', 'The analysis could not be saved in the knowledge store (OperationalError).'))
        for error, kind, sentence in cases:
            with self.subTest(error=type(error).__name__):
                def analyzer(current, candidates, error=error):
                    raise error
                row = self.run_job(analyzer)
                self.assertEqual((row['status'], row['error'], row['detail']['error_kind'], row['detail']['error_class']),
                                 ('failed', sentence, kind, type(error).__name__))
                self.assertEqual(self.events[-1], ('knowledge_job_failed', {'error_category': kind, 'error_type': type(error).__name__}))
        self.assertNotIn(secret, str(rows.jobs(self.graph)) + str(self.events), 'No exception text other than the provider class\'s own is kept')

    def test_an_exception_that_only_looks_like_a_provider_error_does_not_get_its_text_shown(self):
        class Lookalike(Exception):
            status = 502
        class APIErrorWithoutStatus(Exception):
            pass
        APIErrorWithoutStatus.__name__ = 'APIError'
        for error in (Lookalike('ZQ-LEAK'), APIErrorWithoutStatus('ZQ-LEAK')):
            with self.subTest(error=type(error).__name__):
                def analyzer(current, candidates, error=error):
                    raise error
                row = self.run_job(analyzer)
                self.assertEqual(row['detail']['error_kind'], 'internal')
                self.assertNotIn('ZQ-LEAK', row['error'])

    def test_an_unusable_response_as_a_whole_fails_as_a_result(self):
        for response in ({'proposals': []}, 'text', [{}] * 101):
            with self.subTest(response=type(response).__name__):
                row = self.run_job(lambda current, candidates, response=response: response)
                self.assertEqual((row['status'], row['detail']['error_kind']), ('failed', 'result'))


    def test_a_failing_diagnostics_writer_does_not_change_the_outcome(self):
        def broken(event, **fields):
            raise OSError('disk full')
        self.graph.diagnostic = broken
        row = self.run_job(lambda current, candidates: (_ for _ in ()).throw(RuntimeError('x')))
        self.assertEqual((row['status'], row['detail']['error_kind']), ('failed', 'internal'))


class OutputAllowanceTests(unittest.TestCase):
    """The number of proposals the instructions allow fits the output the request allows."""
    def test_the_output_limit_has_room_for_every_allowed_proposal(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('knowledge_ai', Path(__file__).resolve().parents[1] / 'knowledge_ai.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        asked = []
        class Client:
            def structured(self, instructions, body, schema, name, max_tokens):
                asked.append((instructions, max_tokens))
                return {'proposals': [{}] * adapter.MAX_PROPOSALS}
        current = {'submission_id': 'a', 'process_id': 'p', 'revision': 1, 'turns': []}
        other = {'submission_id': 'b', 'process_id': 'q', 'revision': 1, 'turns': []}
        self.assertEqual(len(adapter.build_analyzer(Client())(current, [other])), adapter.MAX_PROPOSALS)
        instructions, limit = asked[0]
        self.assertIn(f'Return at most {adapter.MAX_PROPOSALS} proposals.', instructions)
        self.assertGreaterEqual(limit, adapter.MAX_PROPOSALS * 500, 'About 500 output tokens for each allowed proposal')
        Client.structured = lambda self, *args: {'proposals': [{}] * (adapter.MAX_PROPOSALS + 1)}
        with self.assertRaisesRegex(ValueError, 'invalid proposals'):
            adapter.build_analyzer(Client())(current, [other])


class LifecycleLogTests(unittest.TestCase):
    """The server wires the store's failures to its lifecycle log, with the class and no content."""
    def test_a_failed_matching_job_is_written_to_the_lifecycle_log(self):
        import json
        import time
        with tempfile.TemporaryDirectory() as scratch:
            def analyzer(current, candidates):
                raise server.APIError('The model did not finish its response. Your session is retained; try again.')
            httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=server.OpenAIClient({}),
                                           documents_root=Path(scratch) / 'documents', knowledge_root=Path(scratch) / 'graph', knowledge_analyzer=analyzer)
            try:
                httpd.knowledge.submit(payload('NAV', 'We publish NAV.'))
                receipt = httpd.knowledge.submit(payload('Statements', 'We use approved NAV.'))
                for _ in range(500):
                    if httpd.knowledge.status(receipt['submission_id'], 1, receipt['status_token'])['status'] == 'failed':
                        break
                    time.sleep(.01)
                else:
                    self.fail('The matching job did not fail.')
                httpd.knowledge.executor.submit(lambda: None).result(3)
                log = [json.loads(line) for line in (Path(scratch) / 'server-lifecycle.jsonl').read_text(encoding='utf-8').splitlines()]
            finally:
                httpd.server_close()
            failed = [entry for entry in log if entry['event'] == 'knowledge_job_failed']
            self.assertEqual([(entry['error_category'], entry['error_type']) for entry in failed], [('provider', 'APIError')])
            self.assertNotIn('did not finish', json.dumps(log))


if __name__ == '__main__':
    unittest.main()
