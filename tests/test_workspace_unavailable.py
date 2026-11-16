"""Submit process for an interview whose file workspace is not on this computer (gap-uncommitted-diff-3).

Before "Start new file workspace" the submission still lists the files of the saved workspace: the
refusal says that the workspace is unavailable and what to do, not "not authorized". After it the
browser files the interview without the citations of those files (tests/test_workspace_switch.cjs);
this file pins the server side of that contract: such a payload is accepted, and an excerpt the
browser holds is still never taken as evidence. Loopback HTTP and temporary SQLite only.
"""
import copy
import json
import unittest

from test_server import server
from test_knowledge_graph import payload
from test_knowledge_retained_documents import RetainedDocumentCase

UNKNOWN_SCOPE = 'B' * 43
OLD_FILE = 'doc_0123456789abcdef'
OLD_SOURCE = OLD_FILE + '_p1_c1'
SECRET = 'Invoices above 5,000 need a second approval by the finance manager.'


def moved(first, second, notes, listed=(), scope=None):
    """A submission as the browser builds it: draft step s1 cites `first`, step s2 and the route cite `second`."""
    body = payload('Invoice approval', 'The finance manager gives the second approval above the limit.')
    body['draft']['steps'][0]['evidence_turns'] = list(first)
    body['draft']['steps'][1]['evidence_turns'] = list(second)
    body['draft']['connections'][0]['evidence_turns'] = list(second)
    body['memo_findings'] = [{'key': 'checks', 'status': 'partial', 'answer': 'A second approval applies above 5,000.',
                              'evidence_turns': list(notes)}]
    body['documents'] = {'scope': scope, 'documents': [{'id': identity} for identity in listed]}
    return body


class UnavailableWorkspaceSubmitTests(RetainedDocumentCase):
    def test_submit_before_the_switch_says_that_the_workspace_is_unavailable_and_what_to_do(self):
        for scope in (UNKNOWN_SCOPE, 'short', None, 7):
            with self.subTest(scope=scope):
                status, refused = self.post('/api/knowledge/submit',
                                            moved(['u1', OLD_SOURCE], ['u1'], ['u1'], listed=[OLD_FILE], scope=scope))
                self.assertEqual(status, 403, refused)
                self.assertEqual(refused.get('code'), 'document_scope_unavailable')
                self.assertIn('file workspace is unavailable on this computer', refused['error'])
                self.assertIn('Start new file workspace', refused['error'])
                self.assertNotIn('not authorized', refused['error'])
                self.assertLessEqual(len(refused['error']), 600, 'The browser refuses a longer error text')
                self.assertNotIn(UNKNOWN_SCOPE, json.dumps(refused))
        self.assertEqual(self.stored(), [])

    def test_a_file_that_is_not_in_a_known_workspace_is_still_an_ordinary_refusal(self):
        # The neighbouring case: the workspace exists, the listed file does not. Nothing about the
        # workspace is claimed, and nothing is stored.
        status, refused = self.post('/api/knowledge/submit',
                                    moved(['u1'], ['u1'], ['u1'], listed=[OLD_FILE], scope=self.scope))
        self.assertEqual(status, 403, refused)
        self.assertNotEqual(refused.get('code'), 'document_scope_unavailable')
        self.assertNotIn('workspace', refused['error'])
        self.assertEqual(self.stored(), [])

    def test_after_the_switch_the_interview_is_filed_without_the_old_citations(self):
        # What the browser sends once a new file workspace was started: no file list, no scope, and
        # the citations of the unavailable excerpts left out. A step may then have no source at all.
        status, receipt = self.post('/api/knowledge/submit', moved(['u1'], [], ['u1']))
        self.assertEqual(status, 202, receipt)
        saved = self.detail(receipt)
        self.assertFalse(saved.get('document_evidence'))
        self.assertEqual(saved['documents'], {'documents': []})
        self.assertEqual([step['evidence_turns'] for step in saved['draft']['steps']], [['u1'], []])
        # A revision of it is filed the same way.
        again = moved(['u1'], [], ['u1'])
        again['process_id'] = receipt['process_id']
        status, second = self.post('/api/knowledge/submit', again)
        self.assertEqual(status, 202, second)
        self.assertEqual(second['revision'], 2)

    def test_an_excerpt_the_browser_holds_is_never_taken_as_evidence(self):
        # The protection the fix must not weaken: a citation of the old workspace that is still sent
        # is refused, with or without the excerpt text the browser keeps for display.
        for extra in ({}, {'document_evidence': [{'id': OLD_SOURCE, 'document_id': OLD_FILE, 'name': 'Approval policy.pdf',
                                                   'label': 'Page 1', 'text': SECRET, 'retained_only': True,
                                                   'workspace_unavailable': True}]}):
            with self.subTest(extra=sorted(extra)):
                status, refused = self.post('/api/knowledge/submit', {**moved(['u1', OLD_SOURCE], ['u1'], ['u1']), **extra})
                self.assertEqual(status, 400, refused)
                self.assertEqual(refused.get('code'), 'document_citations_unavailable')
                self.assertEqual(refused['citations'][0]['source_ids'], [OLD_SOURCE])
                self.assertNotIn(SECRET, json.dumps(refused))
        self.assertEqual(self.stored(), [])
        # Accepted once the citation is left out, and the excerpt text the browser added is not stored.
        status, receipt = self.post('/api/knowledge/submit', {**moved(['u1'], ['u1'], ['u1']), **extra})
        self.assertEqual(status, 202, receipt)
        self.assertNotIn(SECRET, json.dumps(self.detail(receipt)))


class UnavailableWorkspaceCaptureTests(unittest.TestCase):
    """The working-map update: what server.workflow_previous_capture accepts without a file scope."""

    TURNS = [{'id': 't001', 'role': 'user', 'text': 'I check each invoice against the purchase order.'},
             {'id': 't002', 'role': 'assistant', 'text': 'Who approves above the limit?'},
             {'id': 't003', 'role': 'user', 'text': 'The finance manager gives the second approval.'}]

    def capture(self):
        previous = copy.deepcopy(server.workflow_previous_capture(None, []))
        step = lambda identity, title, sources: {
            'id': identity, 'title': title, 'type': 'activity', 'actor': 'Clerk', 'system': 'UNKNOWN', 'description': title,
            'input': 'UNKNOWN', 'output': 'UNKNOWN', 'completion_criteria': 'UNKNOWN', 'handoff': 'UNKNOWN',
            'evidence_turns': sources}
        previous['workflow'] = {'title': 'Invoice approval', 'open_questions': [],
                                'steps': [step('S1', 'Receive and check invoice', ['t001']),
                                          step('S2', 'Second approval above 5,000', ['t003'])],
                                'connections': [{'from': 'S1', 'to': 'S2', 'label': 'Above limit', 'evidence_turns': ['t003']}]}
        next(item for item in previous['memo_findings'] if item['key'] == 'checks').update(
            status='partial', answer='A second approval applies above 5,000.', evidence_turns=['t003'])
        return previous

    def test_the_capture_the_browser_sends_after_the_switch_is_accepted(self):
        accepted = server.workflow_previous_capture(self.capture(), self.TURNS)
        self.assertEqual([step['id'] for step in accepted['workflow']['steps']], ['S1', 'S2'])
        self.assertEqual(next(item for item in accepted['memo_findings'] if item['key'] == 'rules')['status'], 'unknown')

    def test_a_capture_that_still_cites_the_old_workspace_is_refused(self):
        # Why the browser must hold back, not merely thin out: without a file scope the server has
        # no excerpt to check, and a step, route or reported note without evidence is refused too.
        cited = self.capture()
        cited['workflow']['steps'][1]['evidence_turns'] = ['t003', OLD_SOURCE]
        with self.assertRaisesRegex(ValueError, 'working map cites missing'):
            server.workflow_previous_capture(cited, self.TURNS)
        emptied = self.capture()
        emptied['workflow']['steps'][1]['evidence_turns'] = []
        with self.assertRaisesRegex(ValueError, 'working map cites missing'):
            server.workflow_previous_capture(emptied, self.TURNS)
        note = self.capture()
        next(item for item in note['memo_findings'] if item['key'] == 'checks')['evidence_turns'] = []
        with self.assertRaisesRegex(ValueError, 'must identify its interview evidence'):
            server.workflow_previous_capture(note, self.TURNS)
        held = self.capture()
        next(item for item in held['memo_findings'] if item['key'] == 'checks').update(
            status='unknown', answer='UNKNOWN / TBD — not established in the interview.', evidence_turns=[])
        server.workflow_previous_capture(held, self.TURNS)


if __name__ == '__main__':
    unittest.main()
