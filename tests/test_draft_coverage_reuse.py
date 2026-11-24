"""Identical, independently audited drafts can share coverage checks across requests."""
import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from test_server import server
from test_concurrent_interview import module as conversation


class DraftCoverageReuseTests(unittest.TestCase):
    def setUp(self):
        self.client = server.OpenAIClient({})
        self.client.assess_coverage = Mock(return_value=([{"key": "name"}], {"topics": [{"key": "name"}]}))
        self.args = [[{"key": "name"}], {"background": "Initial"}, [{"role": "user", "text": "Support closes it."}],
                     {"documents": [{"source_revision": "version one"}]}, {"allow_capture_repair": True, "split": True}]

    def test_matching_readers_share_work_and_receive_independent_results(self):
        entered, release = threading.Event(), threading.Event()
        def review(*args, **kwargs):
            entered.set()
            release.wait(5)
            return [{"key": "name"}], {"topics": [{"key": "name"}]}
        self.client.assess_coverage.side_effect = review
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.client._draft_coverage_review, *self.args)
            self.assertTrue(entered.wait(5))
            concurrent = pool.submit(self.client._draft_coverage_review, *copy.deepcopy(self.args))
            release.set()
            a, b = first.result(), concurrent.result()
        self.assertEqual(a, b)
        b[1]["topics"].clear()
        self.assertEqual(a, self.client._draft_coverage_review(*self.args))
        self.assertEqual(self.client.assess_coverage.call_count, 1)

    def test_a_changed_input_requires_new_coverage_and_an_unavailable_review_is_retried(self):
        self.client.assess_coverage.side_effect = [
            ([], {"review_available": False}), *[([], {"topics": ["reviewed"]}) for _ in range(7)]]
        self.assertFalse(self.client._draft_coverage_review(*self.args)[1]["review_available"])
        self.client._draft_coverage_review(*self.args)
        self.client._draft_coverage_review(*self.args)
        for position, changed in enumerate(([{"key": "rules"}], {"background": "Changed"},
                [{"role": "user", "text": "A correction."}], {"documents": [{"source_revision": "version two"}]},
                {"model_override": "new-reviewer", "split": True})):
            args = list(self.args)
            args[position] = changed
            self.client._draft_coverage_review(*args)
        self.client.model = "new-default"
        self.client._draft_coverage_review(*self.args)
        self.assertEqual(self.client.assess_coverage.call_count, 8)

    def test_specialized_question_keeps_its_rules_without_repeating_the_topic_rubric(self):
        rubric = server.interview_coverage.TOPIC_RUBRIC
        self.assertIn(rubric, conversation.question_policy(server))
        for specialized in (conversation.question_policy(server, True), conversation.question_policy(server, rebuild=True)):
            self.assertIn(conversation.QUESTION_POLICY, specialized)
            self.assertIn(server.CORRECTION_SCOPE_POLICY, specialized)
            self.assertIn(server.EXPERT_FOLLOW_UP_POLICY, specialized)
            self.assertNotIn(rubric, specialized)
        self.assertIn(conversation.FILE_QUESTION_POLICY, conversation.question_policy(server, True))
