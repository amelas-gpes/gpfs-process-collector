"""Which files reach a request when an interview holds more than six.

Cited files keep their evidence without using up the six document slots, a
file that has not been read yet can always be asked for, the remaining slots
go to matches and then to the newest files, and a confirmation replays the
selection its capture was built on. No provider and no network are used.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from test_server import server

spec = importlib.util.spec_from_file_location('collector_document_slots', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
from documents import DocumentError, DocumentStore


def review(chunks):
    source = [chunks[0]['id']]
    return {'summary': 'A synthetic reference file.', 'acknowledgement': 'Reviewed.', 'relevance': 'relevant',
            'relevance_reason': 'Synthetic relation.', 'question': '', 'queries': ['sharedreviewterm'],
            'observations': [{'text': 'The file lists one reference value.', 'sources': source}],
            'questions': [], 'extracted_text': ''}


class DocumentSlotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DocumentStore(Path(self.temp.name) / 'documents')
        self.scope = self.store.create_scope()
        self.service = service_module.DocumentService(self.store, lambda context, record, chunks, phase: review(chunks))

    def tearDown(self):
        self.service.close()
        self.service._worker.join(timeout=4)
        self.assertFalse(self.service._worker.is_alive())
        self.temp.cleanup()

    def reviewed(self, name, data):
        """Store one indexed file as a completed review leaves it, without the worker."""
        record = self.store.extract(self.scope, self.store.add(self.scope, name, data, {})['id'])
        # Every review stored the same search terms, which match every file: the
        # condition under which the oldest uploads used to be ranked first.
        self.store.update(self.scope, record['id'], {'analysis': {
            'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'relevance': 'relevant',
            'summary': 'A synthetic reference file.', 'queries': ['sharedreviewterm'], 'version': 2}})
        return record['id']

    def files(self, count, start=1):
        """`count` reviewed one-section files, oldest first."""
        return [self.reviewed(f'file-{index:02d}.csv', f'sharedreviewterm,value\nuniqueword{index:02d},{index}\n'.encode())
                for index in range(start, start + count)]

    def large(self, name, word):
        filler = 'x' * 930
        return self.reviewed(name, ('step,detail\n' + ''.join(f'{row},{word} handling detail {filler}\n' for row in range(18))).encode())

    def sources(self, identity):
        return self.store.chunks(self.scope, identity)['chunks']

    def selected(self, support):
        return {document['id'] for document in support['documents']}

    def excerpts(self, support):
        return {document['id']: sorted(chunk['id'] for chunk in document['excerpts']) for document in support['documents']}

    def test_seventh_file_is_read_when_six_files_are_already_cited(self):
        ids = self.files(7)
        pins = [self.sources(identity)[0]['id'] for identity in ids[:6]]
        support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=pins)
        self.assertIn(ids[6], self.selected(support))
        self.assertEqual(self.selected(support), set(ids))
        self.assertEqual(support['omitted_documents'], 0)
        self.assertEqual(support['omitted_prior_sources'], 0)
        by_id = {document['id']: document for document in support['documents']}
        for identity, pin in zip(ids[:6], pins):
            self.assertIn(pin, [chunk['id'] for chunk in by_id[identity]['excerpts']])
        seventh = by_id[ids[6]]
        self.assertIn('uniqueword07', '\n'.join(chunk['text'] for chunk in seventh['excerpts']))
        self.assertTrue(seventh['context_coverage']['complete_text'])
        self.assertLessEqual(support['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS)

    def test_twenty_files_uploaded_and_cited_one_at_a_time_all_reach_the_request(self):
        ids, pins = [], []
        for position in range(1, 21):
            ids += self.files(1, start=position)
            support = self.service.supporting_context(self.scope, 'What happens next?', source_ids=pins)
            self.assertIn(ids[-1], self.selected(support), f'upload {position} was not read')
            self.assertEqual(support['omitted_documents'], 0)
            # The reader cites every file it is shown, as the audit's scripted lead did.
            pins = [document['excerpts'][0]['id'] for document in support['documents']]
        final = self.service.supporting_context(self.scope, 'Please look at uniqueword20 again.', source_ids=pins)
        self.assertEqual(self.selected(final), set(ids))
        self.assertLessEqual(final['context_budget']['chunks'], service_module.MAX_SUPPORT_CHUNKS)
        self.assertLessEqual(final['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS)

    def test_uncited_files_take_the_six_slots_by_match_then_newest(self):
        ids = self.files(8)
        support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.')
        self.assertEqual(self.selected(support), set(ids[2:]))
        self.assertEqual(support['omitted_documents'], 2)
        named = self.service.supporting_context(self.scope, 'Please check uniqueword01 for the limit.')
        self.assertEqual(self.selected(named), {ids[0], *ids[3:]})
        self.assertEqual(named['omitted_documents'], 2)

    def test_a_file_asked_for_is_read_beyond_the_six_slots(self):
        ids = self.files(9)
        other_scope = self.store.create_scope()
        foreign = self.store.add(other_scope, 'foreign.csv', b'field,value\nprivate,other interview\n', {})
        self.store.extract(other_scope, foreign['id'])
        self.service.action(self.scope, ids[2], 'park')
        support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.',
                                                  required_documents=[ids[0], ids[1], ids[2], foreign['id'], 'doc_missing'])
        # The two oldest files are read because they were asked for; a parked, foreign or unknown ID is not.
        self.assertEqual(self.selected(support), {ids[0], ids[1], *ids[3:]})
        self.assertEqual(support['omitted_documents'], 0)
        self.assertNotIn(foreign['id'], str(support))
        for invalid in ('doc_one', [1], ['doc_x'] * 21):
            with self.assertRaises(DocumentError):
                self.service.supporting_context(self.scope, 'An ordinary answer.', required_documents=invalid)

    def test_a_file_asked_for_takes_its_turn_before_the_remaining_budget_is_used(self):
        cited = [self.large(f'cited-{index}.csv', f'cited{index}') for index in range(9)]
        asked = self.large('asked.csv', 'asked')
        pins = [self.sources(identity)[1] for identity in cited]
        opening = len(self.sources(asked)[0]['text'])
        remaining = service_module.MAX_SUPPORT_CHARS - sum(len(pin['text']) for pin in pins)
        # After the cited excerpts there is room for exactly one more opening section.
        self.assertLessEqual(opening, remaining)
        self.assertLess(remaining, opening + min(len(self.sources(identity)[0]['text']) for identity in cited))
        pin_ids = [pin['id'] for pin in pins]
        support = self.service.supporting_context(self.scope, 'An ordinary answer about the work.',
                                                  source_ids=pin_ids, required_documents=[asked])
        by_id = {document['id']: document for document in support['documents']}
        self.assertEqual([chunk['id'] for chunk in by_id[asked]['excerpts']], [self.sources(asked)[0]['id']])
        self.assertEqual(support['omitted_prior_sources'], 0)
        for identity, pin in zip(cited, pin_ids):
            self.assertEqual([chunk['id'] for chunk in by_id[identity]['excerpts']], [pin])
        self.assertLessEqual(support['context_budget']['characters'], service_module.MAX_SUPPORT_CHARS)

    def test_confirmation_replay_reproduces_a_selection_of_more_than_six_files(self):
        ids = self.files(10)
        context = {'process_name': 'Synthetic returns'}
        pins = [self.sources(ids[0])[0]['id'], self.sources(ids[1])[0]['id']]
        original = self.service.supporting_context(self.scope, 'An ordinary answer about the work.',
                                                   source_ids=pins, required_documents=[ids[2]])
        self.assertEqual(self.selected(original), {ids[0], ids[1], ids[2], *ids[4:]})
        self.assertEqual(original['omitted_documents'], 1)
        binding = server.interview_orchestrator.Coordinator._source_binding(context, original)
        shown = sorted(chunk['id'] for document in original['documents'] for chunk in document['excerpts'])
        # The confirmation pins every excerpt it was shown and words its turns differently.
        replay = self.service.supporting_context(self.scope, 'Yes uniqueword04 that is everything.',
                                                 source_ids=shown, frozen=True)
        self.assertEqual(server.interview_orchestrator.Coordinator._source_binding(context, replay), binding)
        still_asking = self.service.supporting_context(self.scope, 'Yes uniqueword04 that is everything.',
                                                       source_ids=shown, required_documents=[ids[2]], frozen=True)
        self.assertEqual(server.interview_orchestrator.Coordinator._source_binding(context, still_asking), binding)
        # Without the freeze the file left out would join and the capture would no longer match.
        unfrozen = self.service.supporting_context(self.scope, 'Yes uniqueword04 that is everything.', source_ids=shown)
        self.assertEqual(self.selected(unfrozen), set(ids))
        # A file reviewed since that capture is asked for by its own intake and does join the replay.
        asked = self.service.supporting_context(self.scope, 'Yes uniqueword04 that is everything.',
                                                source_ids=shown, required_documents=[ids[3]], frozen=True)
        self.assertEqual(self.selected(asked), set(ids))
        self.assertEqual(asked['omitted_documents'], 0)

    def test_confirmation_replay_keeps_a_selected_file_that_the_limit_left_without_an_excerpt(self):
        cited = [self.large(f'cited-{index}.csv', f'cited{index}') for index in range(2)]
        idle = [self.large(f'idle-{index}.csv', f'idle{index}') for index in range(6)]
        context = {'process_name': 'Synthetic returns'}
        binding = server.interview_orchestrator.Coordinator._source_binding
        pins = [chunk['id'] for identity in cited for chunk in self.sources(identity)[:3]]
        original = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=pins)
        files = [document['id'] for document in original['documents']]
        self.assertEqual(set(files), {*cited, *idle})
        self.assertEqual(original['omitted_documents'], 0)
        # The cited sections and one opening section per further file are more than one
        # request can read, so the last files are selected without an excerpt.
        starved = [document['id'] for document in original['documents'] if not document['excerpts']]
        self.assertTrue(starved)
        self.assertLess(set(starved), set(idle))
        shown = sorted(chunk['id'] for document in original['documents'] for chunk in document['excerpts'])
        # The confirmation pins every excerpt it was shown and is told the files of that selection.
        for query in ('An ordinary answer about the work.', 'Yes idle5 that is everything.'):
            replay = self.service.supporting_context(self.scope, query, source_ids=shown, frozen=True,
                                                     selected_documents=files)
            self.assertEqual(self.excerpts(replay), self.excerpts(original))
            self.assertEqual(binding(context, replay), binding(context, original))
        # The pins alone cannot name a file that has no excerpt: that replay is a different selection.
        from_pins = self.service.supporting_context(self.scope, 'An ordinary answer about the work.',
                                                    source_ids=shown, frozen=True)
        self.assertNotEqual(binding(context, from_pins), binding(context, original))
        # The list is a preference inside the scope. A parked, foreign or unknown ID selects nothing,
        # a pinned file is never cut, and a file asked for by name still joins.
        other_scope = self.store.create_scope()
        foreign = self.store.add(other_scope, 'foreign.csv', b'field,value\nprivate,other interview\n', {})
        self.store.extract(other_scope, foreign['id'])
        newer = self.large('newer.csv', 'newer')
        narrowed = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=shown,
                                                   frozen=True, selected_documents=[foreign['id'], 'doc_missing'])
        self.assertEqual(self.selected(narrowed), set(files) - set(starved))
        self.assertNotIn(foreign['id'], str(narrowed))
        joined = self.service.supporting_context(self.scope, 'An ordinary answer about the work.', source_ids=shown,
                                                 frozen=True, selected_documents=files, required_documents=[newer])
        self.assertEqual(self.selected(joined), {*files, newer})
        for invalid in ('doc_one', [1], {'doc_one'}):
            with self.assertRaises(DocumentError):
                self.service.supporting_context(self.scope, 'An ordinary answer.', frozen=True, selected_documents=invalid)

    def test_six_or_fewer_files_are_selected_exactly_as_before(self):
        ids = self.files(6)
        pins = [self.sources(ids[4])[0]['id'], self.sources(ids[1])[0]['id']]
        for query in ('An ordinary answer about the work.', 'uniqueword03 then uniqueword06'):
            plain = self.service.supporting_context(self.scope, query, source_ids=pins)
            self.assertEqual([document['id'] for document in plain['documents']][:2], [ids[4], ids[1]])
            self.assertEqual(self.selected(plain), set(ids))
            self.assertEqual(plain['omitted_documents'], 0)
            self.assertEqual(self.service.supporting_context(self.scope, query, source_ids=pins, frozen=True), plain)
            self.assertEqual(self.service.supporting_context(self.scope, query, source_ids=pins,
                                                             required_documents=ids), plain)


if __name__ == '__main__':
    unittest.main()
