"""Earlier citations when one request cannot carry the text of all of them.

A request reads at most 60,000 characters of reference files. Excerpts that
are already cited are placed first, in the order the caller gives them and
across all files; excerpts of parked or removed files follow. A cited excerpt
that does not fit is still reported as a known excerpt of this interview,
without its text. No provider and no network are used.
"""
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location('collector_document_prior_sources', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
from documents import DocumentStore

SECTION = 4800


class PriorSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DocumentStore(Path(self.temp.name) / 'documents')
        self.scope = self.store.create_scope()
        self.service = service_module.DocumentService(self.store, lambda context, record, chunks, phase: {
            'summary': 'A synthetic reference file.', 'acknowledgement': 'Reviewed.', 'relevance': 'relevant',
            'relevance_reason': 'Synthetic relation.', 'question': '', 'queries': [], 'observations': [],
            'questions': [], 'extracted_text': ''})

    def tearDown(self):
        self.service.close()
        self.service._worker.join(timeout=4)
        self.assertFalse(self.service._worker.is_alive())
        self.temp.cleanup()

    def sectioned(self, name, sections, scope=None):
        """One reviewed file whose rows are each one indexed section of about 4,800 characters."""
        scope = scope or self.scope
        word = name.split('.')[0]
        rows = ['section,detail']
        for index in range(sections):
            body = f'{word}sec{index} synthetic procedure text for section {index} of {name} '
            rows.append(f'{index},' + (body * (SECTION // len(body) + 1))[:SECTION - 12])
        record = self.store.extract(scope, self.store.add(scope, name, ('\n'.join(rows) + '\n').encode(), {})['id'])
        self.store.update(scope, record['id'], {'analysis': {
            'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'relevance': 'relevant',
            'summary': 'A synthetic reference file.', 'version': 2}})
        return record['id']

    def sections(self, identity, scope=None):
        chunks = self.store.chunks(scope or self.scope, identity, limit=200)['chunks']
        self.assertTrue(all(SECTION - 200 <= len(chunk['text']) <= SECTION + 200 for chunk in chunks))
        return [chunk['id'] for chunk in chunks]

    def shown(self, support):
        return [chunk['id'] for document in support['documents'] for chunk in document['excerpts']]

    def settled(self, identity):
        """Wait for the background review that Save for later starts."""
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            record = self.store.get(self.scope, identity)
            if record['archived'] or (record.get('analysis') or {}).get('phase') in ('complete', 'error'):
                return record
            time.sleep(.02)
        self.fail('The file review did not settle.')

    def test_cited_excerpts_are_placed_in_the_callers_order_across_files(self):
        first, second = self.sectioned('alpha.csv', 15), self.sectioned('beta.csv', 15)
        for notes_file, map_file in ((first, second), (second, first)):
            with self.subTest(map_file_sorts_first=map_file < notes_file):
                notes, drawing = self.sections(notes_file), self.sections(map_file)
                # The notes cite three sections of each file; the map alone cites ten more of one file.
                priority = [*drawing[:3], *notes[:3]]
                pins = [*priority, *drawing[3:13]]
                support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=pins)
                shown = self.shown(support)
                self.assertLessEqual(support['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS)
                # Twelve sections fit. The six cited first are all read, whichever file they belong to.
                self.assertEqual(len(shown), 12)
                self.assertTrue(set(priority) <= set(shown), 'an excerpt cited first was displaced by a later one')
                self.assertEqual(set(shown), set(pins[:12]))
                self.assertEqual(support['omitted_prior_sources'], 4)
                self.assertEqual([item['id'] for item in support['carried_sources']], pins[12:])

    def test_excerpts_of_a_parked_or_removed_file_do_not_displace_cited_excerpts_of_active_files(self):
        small, large = self.sectioned('checklist.csv', 3), self.sectioned('manual.csv', 40)
        pins = [*self.sections(large)[:18], *self.sections(small)]
        for action in ('park', 'remove'):
            with self.subTest(action=action):
                self.service.action(self.scope, large, action)
                self.settled(large)
                support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=pins)
                self.assertEqual(self.shown(support), self.sections(small))
                retained = [item['id'] for item in support['retained_evidence']]
                # The active file's three sections are read first; nine saved sections fill what is left.
                self.assertEqual(retained, pins[:9])
                self.assertTrue(all(item['retained_only'] for item in support['retained_evidence']))
                self.assertLessEqual(support['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS)
                carried = support['carried_sources']
                self.assertEqual([item['id'] for item in carried], pins[9:18])
                self.assertTrue(all(item['retained_only'] is True and item['document_id'] == large for item in carried))
                self.assertEqual(support['omitted_prior_sources'], 9)

    def test_a_cited_excerpt_that_does_not_fit_is_reported_without_its_text(self):
        manual = self.sectioned('manual.csv', 40)
        sections = self.sections(manual)
        other_scope = self.store.create_scope()
        foreign = self.sections(self.sectioned('foreign.csv', 2, other_scope), other_scope)
        pins = [*sections[:14], manual + '_row999_c1', foreign[0], 'doc_unknown_row1_c1', 'context', 7]
        support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=pins)
        self.assertEqual(self.shown(support), sections[:12])
        carried = support['carried_sources']
        # Only real excerpts of this interview's files are reported; unknown and foreign IDs are not.
        self.assertEqual([item['id'] for item in carried], sections[12:14])
        self.assertEqual(support['omitted_prior_sources'], 2)
        texts = {chunk['id']: chunk['text'] for chunk in self.store.chunks(self.scope, manual, limit=200)['chunks']}
        for item in carried:
            self.assertEqual(set(item), {'id', 'document_id', 'name', 'characters'})
            self.assertEqual((item['document_id'], item['name'], item['characters']),
                             (manual, 'manual.csv', len(texts[item['id']])))
            self.assertNotIn(texts[item['id']][:200], str(support))
        self.assertNotIn(foreign[0], str(support))

    def test_a_request_whose_citations_all_fit_is_unchanged(self):
        manual = self.sectioned('manual.csv', 40)
        pins = self.sections(manual)[5:11]
        support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=pins)
        self.assertEqual(self.shown(support)[:6], pins)
        self.assertEqual(support['omitted_prior_sources'], 0)
        self.assertNotIn('carried_sources', support)
        self.assertNotIn('carried_sources', self.service.supporting_context(self.scope, 'An ordinary answer.'))


if __name__ == '__main__':
    unittest.main()
