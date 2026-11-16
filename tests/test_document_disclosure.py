"""The notices about uploaded files must describe what is actually sent to the provider.

The first tests record the behaviour with synthetic files and a recording stand-in for the
analysis call; the last ones check that every place that tells the user about it says so.
If the behaviour is changed, change the wording with it. No provider or network is used.
"""
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest

APP = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


service_module = load('collector_disclosure_document_service', 'document_service.py')
server = load('collector_disclosure_server', 'server.py')
from documents import DocumentStore

# Large enough for several background batches (a batch holds at most 24,000 characters).
ROWS = b'return_id,customer,note\n' + b''.join(
    b'RET-%05d,Customer %d,%s\n' % (number, number, b'x' * 180) for number in range(1, 201))


def response(chunks, relevance):
    return {'summary': 'A synthetic returns log.', 'acknowledgement': 'Received.',
            'relevance': relevance, 'relevance_reason': 'Synthetic verdict.',
            'question': 'Which column do you use?' if relevance == 'relevant' else 'How does this file relate?',
            'queries': ['returns'], 'observations': [], 'questions': [], 'extracted_text': ''}


class ReviewedContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DocumentStore(Path(self.temp.name) / 'documents')
        self.scope = self.store.create_scope()
        self.service = None
        self.calls = []

    def tearDown(self):
        if self.service:
            self.service.close()
            self.service._worker.join(timeout=4)
            self.assertFalse(self.service._worker.is_alive())
        self.temp.cleanup()

    def start(self, relevance='relevant', hold=None, entered=None, release=None):
        """Record every review call; optionally hold the first background call of one file."""
        def analyze(context, record, chunks, phase):
            self.calls.append((record['name'], phase, [chunk['id'] for chunk in chunks]))
            if phase == 'deep' and record['name'] == hold and not entered.is_set():
                entered.set()
                release.wait(10)
            return response(chunks, relevance)
        self.service = service_module.DocumentService(self.store, analyze)
        self.service.session(self.scope, {'process_name': 'Customer returns', 'latest_question': 'What starts a return?',
                                          'turns': [{'id': 'u1', 'role': 'user', 'text': 'A customer emails a form.'}]})
        return self.service

    def settled(self, identity, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.service._condition:
                idle = not self.service._queued and not self.service._running
            record = self.store.get(self.scope, identity)
            if idle and (record['archived'] or (record.get('analysis') or {}).get('phase') == 'complete'):
                return record
            time.sleep(.01)
        self.fail(f'Review did not settle: {self.store.get(self.scope, identity)}')

    def chunk_ids(self, identity):
        page = self.store.chunks(self.scope, identity, limit=500)
        self.assertIsNone(page['next_offset'])
        return [chunk['id'] for chunk in page['chunks']]

    def reviewed(self, name):
        return [source for file, phase, sources in self.calls if file == name and phase == 'deep' for source in sources]

    def test_a_file_judged_unrelated_stops_after_the_quick_sample(self):
        service = self.start(relevance='unrelated')
        record = service.upload(self.scope, 'returns-log.csv', ROWS)
        final = self.settled(record['id'])
        self.assertEqual(final['analysis']['disposition'], 'needs_reason')
        everything = self.chunk_ids(record['id'])
        self.assertFalse(any(call[1]=='deep' for call in self.calls))
        self.assertLess(len(set(self.reviewed('returns-log.csv'))),len(everything))
        self.assertTrue(final['analysis']['review_stopped'])
        self.assertEqual(service.supporting_context(self.scope,'returns customer')['documents'], [])

    def test_saving_for_later_and_removing_both_stop_background_review(self):
        entered, release = threading.Event(), threading.Event()
        service = self.start(hold='parked.csv', entered=entered, release=release)
        parked = service.upload(self.scope, 'parked.csv', ROWS)
        self.assertTrue(entered.wait(10))
        self.assertEqual(service.action(self.scope, parked['id'], 'park')['analysis']['disposition'], 'parked')
        release.set()
        final = self.settled(parked['id'])
        self.assertEqual(final['analysis']['disposition'], 'parked')
        self.assertTrue(final['analysis']['review_stopped'])
        self.assertLess(len(set(self.reviewed('parked.csv'))), len(self.chunk_ids(parked['id'])))
        self.assertEqual(service.supporting_context(self.scope, 'returns customer')['documents'], [],
                         'A file saved for later is left out of later interview calls')

        service.close()
        service._worker.join(timeout=4)
        self.calls.clear()
        entered, release = threading.Event(), threading.Event()
        service = self.start(hold='removed.csv', entered=entered, release=release)
        removed = service.upload(self.scope, 'removed.csv', ROWS + b'RET-extra,Customer 0,extra\n')
        self.assertTrue(entered.wait(10))
        before = len(self.reviewed('removed.csv'))
        service.action(self.scope, removed['id'], 'remove')
        release.set()
        self.assertTrue(self.settled(removed['id'])['archived'])
        self.assertEqual(len(self.reviewed('removed.csv')), before, 'Remove stops the background review')
        self.assertLess(before, len(self.chunk_ids(removed['id'])))


class NoticeWordingTests(unittest.TestCase):
    """Each notice states the facts recorded above; none repeats the old "relevant only" claim."""
    FACTS = {
        'the whole text is sent': r'full (?:extracted )?text',
        'hidden sheets are included': r'hidden (?:work)?sheets',
        'pages or images needing visual review are sent': r'visual review',
        'it goes to the AI service': r'(?i)AI service|OpenAI',
        'paused reviews are disclosed': r'(?i)pause|stop',
        'save for later is disclosed': r'saved for later|Save for later|parked',
        'Remove stops it': r'(?:Remove\W{0,4}|removal) stops',
        'interview requests are disclosed': r'(?i)interview requests',
    }
    OLD_CLAIMS = ('Relevant content is sent', 'relevant excerpts or page images', 'send relevant text chunks',
                  'Selected text and visual inputs')

    def check(self, label, text):
        # Plain truth assertions: a failure names the missing statement without printing the whole document.
        for fact, pattern in self.FACTS.items():
            self.assertTrue(re.search(pattern, text), f'{label} does not say that {fact}')
        for claim in self.OLD_CLAIMS:
            self.assertFalse(claim in text, f'{label} still says only selected content is sent: "{claim}"')

    def test_data_notice_states_what_the_review_sends(self):
        notice = server.OpenAIClient({}).public_config()['data_notice']
        self.check('The data notice', notice)
        self.assertNotIn('OpenAI', notice)
        self.assertIn('saved privately on this computer', notice)

    def test_file_tray_notice_states_what_the_review_sends(self):
        source = (APP / 'web' / 'documents.js').read_text(encoding='utf-8')
        notice = re.search(r'const FILE_NOTICE = "([^"]+)";', source)
        self.assertIsNotNone(notice, 'The file notice constant was not found')
        self.check('The file tray notice', notice.group(1))
        self.assertNotIn('OpenAI', notice.group(1))

    def test_readme_and_design_note_state_what_the_review_sends(self):
        self.check('README.md', (APP / 'README.md').read_text(encoding='utf-8'))
        self.check('docs/DOCUMENT_CONTEXT_DESIGN.md', (APP / 'docs' / 'DOCUMENT_CONTEXT_DESIGN.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
