"""What one request reads of the reference files when not everything fits.

Real DocumentStore and DocumentService on a temporary SQLite store; the review
callback is never used. Each fixture row is one indexed section of about 4,800
characters and carries a word of its own, so a query can name a section.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('context_budget_document_service', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
from documents import DocumentStore

SECTION = 4800


class ContextBudgetCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='collector-context-budget-')
        self.store = DocumentStore(Path(self.temp.name) / 'documents')
        self.service = service_module.DocumentService(self.store, lambda *args: self.fail('No review is expected'))
        self.scope = self.store.create_scope()

    def tearDown(self):
        self.service.close()
        self.service._worker.join(timeout=4)
        self.temp.cleanup()

    def file(self, name, sections):
        word = name.split('.')[0]
        rows = ['section,detail']
        for index in range(sections):
            body = f'{word}sec{index} ordinary procedure wording for step {index} of {name} '
            rows.append(f'{index},' + (body * (SECTION // len(body) + 1))[:SECTION - 12])
        record = self.store.add(self.scope, name, ('\n'.join(rows) + '\n').encode())
        self.store.extract(self.scope, record['id'])
        self.store.update(self.scope, record['id'], {'analysis': {
            'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'summary': 'Synthetic reference.'}})
        chunks = self.store.chunks(self.scope, record['id'], limit=200)['chunks']
        self.assertEqual(len(chunks), sections)
        self.assertTrue(all(SECTION - 200 <= len(chunk['text']) <= SECTION + 200 for chunk in chunks))
        return record['id'], [chunk['id'] for chunk in chunks]

    def read(self, query, **options):
        support = self.service.supporting_context(self.scope, query, **options)
        self.assertLessEqual(support['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS)
        self.assertLessEqual(support['context_budget']['chunks'], service_module.MAX_SUPPORT_CHUNKS)
        return support, {item['id']: [excerpt['id'] for excerpt in item['excerpts']] for item in support['documents']}


class SeveralFilesTogetherTests(ContextBudgetCase):
    """document-service-3: 'small' is judged for the selection, not for each file."""

    def test_the_matched_section_is_read_when_two_files_that_each_fit_do_not_fit_together(self):
        first, first_ids = self.file('approvals.csv', 7)
        second, second_ids = self.file('escalation.csv', 7)
        for needle, owner in ((first_ids[-1], first), (second_ids[-1], second)):
            word = ('approvals' if owner == first else 'escalation') + 'sec6'
            with self.subTest(matched_section_of=word):
                support, read = self.read(f'What happens in {word}?')
                self.assertIn(needle, read[owner], 'The section the question matches was dropped for the opening of each file')
                self.assertEqual(read[owner][0], needle, 'A match is read before the rest of its file')
                # The rest is shared between the files: neither is starved by the other.
                self.assertGreaterEqual(min(len(read[first]), len(read[second])), 5)
                self.assertEqual(len(read[first]) + len(read[second]), 12)
                for document in support['documents']:
                    self.assertFalse(document['context_coverage']['complete_text'])
                    self.assertEqual(document['context_coverage']['selection'], 'selected excerpts')
                self.assertNotIn('omitted_query_matches', support, 'The only match was read')

    def test_a_question_that_matches_nothing_still_reads_the_start_and_the_end_of_each_file(self):
        first, first_ids = self.file('approvals.csv', 7)
        second, second_ids = self.file('escalation.csv', 7)
        support, read = self.read('zzzunmatched')
        for identity, ids in ((first, first_ids), (second, second_ids)):
            self.assertEqual(read[identity][:3], [ids[0], ids[3], ids[-1]], 'Opening, middle and end come before the rest')

    def test_files_that_fit_together_are_read_whole_in_their_own_order(self):
        first, first_ids = self.file('approvals.csv', 6)
        second, second_ids = self.file('escalation.csv', 6)
        support, read = self.read('What happens in approvalssec5 and escalationsec4?')
        self.assertEqual((read[first], read[second]), (first_ids, second_ids), 'A file read whole is not reordered by the query')
        self.assertTrue(all(document['context_coverage']['complete_text'] for document in support['documents']))
        self.assertNotIn('omitted_query_matches', support)

    def test_one_file_that_fits_alone_is_read_whole_in_its_own_order(self):
        only, ids = self.file('approvals.csv', 12)
        support, read = self.read('What happens in approvalssec11?')
        self.assertEqual(read[only], ids)
        self.assertTrue(support['documents'][0]['context_coverage']['complete_text'])


class SavedExcerptAllowanceTests(ContextBudgetCase):
    """document-service-4: saved excerpts of a removed or parked file must not crowd out its replacement."""

    def replaced(self, action):
        old, old_ids = self.file('procedure-v1.csv', 9)
        self.service.action(self.scope, old, action)
        if action == 'park':
            self.settle(old)
        new, new_ids = self.file('procedure-v2.csv', 9)
        return old, old_ids, new, new_ids

    def settle(self, identity):
        import time
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (self.store.get(self.scope, identity).get('analysis') or {}).get('phase') in ('complete', 'error'):
                return
            time.sleep(.02)
        self.fail('The parked file did not settle.')

    def test_a_replacement_file_is_read_although_the_removed_version_is_cited_in_full(self):
        for action in ('remove', 'park'):
            with self.subTest(action=action):
                self.tearDown()
                self.setUp()
                # A parked file's review goes on in the background; here it has nothing to say.
                self.service.analyze = lambda context, record, chunks, phase: {
                    'summary': 'Synthetic.', 'acknowledgement': '', 'relevance': 'relevant', 'relevance_reason': '',
                    'question': '', 'queries': [], 'observations': [], 'questions': [], 'extracted_text': ''}
                old, old_ids, new, new_ids = self.replaced(action)
                support, read = self.read('An ordinary answer about the work.', source_ids=old_ids)
                saved = support['retained_evidence']
                self.assertTrue(all(item['retained_only'] for item in saved))
                self.assertEqual([item['id'] for item in saved], old_ids[:4], 'Saved excerpts keep the order of the citations')
                self.assertLessEqual(sum(len(item['text']) for item in saved), service_module.MAX_RETAINED_CHARS)
                self.assertGreaterEqual(len(read[new]), 8, 'The current version gets the room the removed one no longer takes')
                # What did not fit is reported as known, without its text, and flagged as saved.
                carried = support['carried_sources']
                self.assertEqual([item['id'] for item in carried], old_ids[4:])
                self.assertTrue(all(item['retained_only'] and 'text' not in item for item in carried))
                self.assertEqual(support['omitted_prior_sources'], 5)

    def test_saved_excerpts_use_free_room_when_the_active_files_leave_some(self):
        old, old_ids = self.file('procedure-v1.csv', 9)
        self.service.action(self.scope, old, 'remove')
        new, new_ids = self.file('note.csv', 2)
        support, read = self.read('An ordinary answer about the work.', source_ids=old_ids)
        self.assertEqual(read[new], new_ids, 'The active file is read whole')
        self.assertEqual(sorted(item['id'] for item in support['retained_evidence']), sorted(old_ids),
                         'Nothing is withheld while there is room for it')
        self.assertEqual(support['omitted_prior_sources'], 0)
        self.assertNotIn('carried_sources', support)

    def test_cited_excerpts_of_active_files_come_before_any_saved_excerpt(self):
        old, old_ids = self.file('procedure-v1.csv', 9)
        self.service.action(self.scope, old, 'remove')
        new, new_ids = self.file('procedure-v2.csv', 20)
        # The removed version is cited first; twelve sections of the current file follow.
        support, read = self.read('zzzunmatched', source_ids=[*old_ids, *new_ids[:12]])
        self.assertEqual(read[new], new_ids[:12], 'Every cited excerpt of the active file is read')
        self.assertEqual(support['retained_evidence'], [])
        self.assertEqual([item['id'] for item in support['carried_sources']], old_ids)


class RoomForMatchesTests(ContextBudgetCase):
    """document-service-5: prior citations must not shut out the sections the current turns match."""

    def setUp(self):
        super().setUp()
        self.manual, self.ids = self.file('manual.csv', 40)

    def test_a_cited_file_can_still_supply_the_section_the_conversation_moved_to(self):
        cited = self.ids[:12]
        support, read = self.read('How does manualsec30 work?', source_ids=cited)
        self.assertIn(self.ids[30], read[self.manual], 'Twelve cited sections kept the matching section out')
        self.assertEqual(read[self.manual], [*cited[:11], self.ids[30]], 'Cited excerpts come first and keep their order')
        self.assertEqual([item['id'] for item in support['carried_sources']], cited[11:])
        self.assertEqual(support['omitted_prior_sources'], 1)
        self.assertNotIn('omitted_query_matches', support)

    def test_at_most_four_matches_are_given_room_and_the_rest_are_counted(self):
        cited = self.ids[:12]
        words = ' '.join(f'manualsec{index}' for index in range(30, 36))
        support, read = self.read(words, source_ids=cited)
        matched = [identity for identity in read[self.manual] if identity in self.ids[30:36]]
        self.assertEqual(len(matched), service_module.MAX_QUERY_MATCHES)
        self.assertEqual(read[self.manual][:8], cited[:8], 'Cited excerpts keep at least the room the matches leave')
        self.assertEqual(support['omitted_query_matches'], 2, 'The request says how many matches it found and did not read')
        self.assertEqual(support['omitted_prior_sources'], 4)

    def test_without_a_match_every_cited_excerpt_is_read_as_before(self):
        cited = self.ids[:12]
        for query in ('zzzunmatched', ''):
            with self.subTest(query=query):
                support, read = self.read(query, source_ids=cited)
                self.assertEqual(read[self.manual], cited)
                self.assertEqual(support['omitted_prior_sources'], 0)
                self.assertNotIn('omitted_query_matches', support)

    def test_a_match_that_is_already_cited_displaces_nothing(self):
        cited = self.ids[:12]
        support, read = self.read('How does manualsec3 work?', source_ids=cited)
        self.assertEqual(read[self.manual], cited)
        self.assertEqual(support['omitted_prior_sources'], 0)

    def test_citations_named_as_pinned_first_never_wait_for_a_match(self):
        cited = self.ids[:12]
        support, read = self.read('How does manualsec30 work?', source_ids=cited, pinned_first=12)
        self.assertEqual(read[self.manual], cited)
        self.assertEqual(support['omitted_query_matches'], 1, 'The match that found no room is reported')
        # Only the leading entries are pinned; a later citation still makes room.
        support, read = self.read('How does manualsec30 work?', source_ids=cited, pinned_first=6)
        self.assertEqual(read[self.manual], [*cited[:11], self.ids[30]])
        for wrong in (-1, 1.5, True, '2', None):
            with self.assertRaises(ValueError):
                self.service.supporting_context(self.scope, 'manualsec30', source_ids=cited, pinned_first=wrong)

    def test_a_replay_of_a_selection_reads_exactly_that_selection_whatever_the_wording(self):
        cited = self.ids[:12]
        first, read = self.read('How does manualsec30 work?', source_ids=cited)
        shown = read[self.manual]
        for query in ('How does manualsec30 work?', 'Yes, that is right. manualsec36 manualsec37', ''):
            with self.subTest(query=query):
                replay, again = self.read(query, source_ids=shown, frozen=True, selected_documents=[self.manual])
                self.assertEqual(again[self.manual], shown)
                self.assertEqual(replay['context_budget'], first['context_budget'])
                self.assertEqual(replay['omitted_prior_sources'], 0)

    def test_a_replay_keeps_no_room_for_matches(self):
        cited = self.ids[:12]
        support, read = self.read('How does manualsec30 work?', source_ids=cited, frozen=True)
        self.assertEqual(read[self.manual], cited)

    def test_the_number_of_matches_given_room_is_one_setting(self):
        with patch.object(service_module, 'MAX_QUERY_MATCHES', 0):
            support, read = self.read('How does manualsec30 work?', source_ids=self.ids[:12])
        self.assertEqual(read[self.manual], self.ids[:12])
        self.assertEqual(support['omitted_query_matches'], 1)


if __name__ == '__main__':
    unittest.main()
