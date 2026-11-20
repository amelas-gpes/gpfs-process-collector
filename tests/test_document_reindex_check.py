"""A file indexed by an earlier version is compared with what this version reads, locally and free.

An unchanged index is current after all and keeps its review; a changed one is held back in
its own state, 'reindex_required', until the person chooses the paid re-index and review.
"""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_document_visual_boundaries as visual

spec = importlib.util.spec_from_file_location('collector_document_service_reindex_check', Path(__file__).resolve().parents[1] / 'document_service.py')
service_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_module)
import documents

ROOT = Path(__file__).resolve().parents[1]
OLD_NOTICE = 'Saved extraction predates the current completeness checks. Revisit this file to re-index it before claiming a full review.'
REVIEWED = {'phase': 'complete', 'review_complete': True, 'disposition': 'relevant', 'cursor': 1, 'reviewed_chunks': 1,
            'total_chunks': 1, 'version': 4, 'intent_version': 2, 'summary': 'A fictional stage list.',
            'observations': [{'id': 'o1', 'text': 'Intake is the first stage.', 'sources': []}]}


def png_bytes():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (66, 21), 'white').save(output, 'PNG')
    return output.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()
        self.calls = []

    def manager(self):
        def review(context, record, chunks, phase):
            self.calls.append((record['id'], phase))
            raise RuntimeError('No provider review is expected')
        manager = service_module.DocumentService(self.store, review)
        self.addCleanup(lambda: manager._worker.join(timeout=5))
        self.addCleanup(manager.close)
        return manager

    def indexed(self, name='stages.csv', data=b'stage\nFictionalIntake\n'):
        record = self.store.extract(self.scope, self.store.add(self.scope, name, data)['id'])
        self.assertIn(record['status'], ('ready', 'partial'), record.get('error'))
        return record

    def stored(self, document_id):
        with self.store._db() as db:
            return json.loads(db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()[0])

    def rewrite(self, document_id, change):
        with self.store._db() as db:
            saved = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()[0])
            change(saved)
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(saved), document_id))

    def outdate(self, document_id, analysis=REVIEWED, **fields):
        """The record as an earlier build left it: no version, its review finished and complete."""
        def change(saved):
            saved.pop('extraction_version', None)
            saved.pop('extraction_needs_reindex', None)
            saved.update(status='ready', analysis=json.loads(json.dumps(analysis)), **fields)
        self.rewrite(document_id, change)

    def rows(self, document_id):
        with self.store._db() as db:
            return [tuple(row) for row in db.execute('SELECT rowid,id,label,text,location FROM chunks WHERE document_id=? ORDER BY rowid',
                                                     (document_id,))]

    def settled(self, manager, document_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            record = manager.status(self.scope, {})[0]
            if (record.get('reindex_check') or {}).get('outcome') != 'pending':
                return record
            threading.Event().wait(.01)
        self.fail('The local comparison did not finish')


class ReadProjection(Case):
    def test_outdated_record_reads_as_its_own_state_and_an_earlier_error_stays_beside_it(self):
        record = self.indexed()
        self.outdate(record['id'], {**REVIEWED, 'phase': 'error', 'review_complete': False, 'error': 'The review service is unavailable.',
                                    'retry_required': True})
        read = self.store.get(self.scope, record['id'])
        self.assertTrue(read['extraction_needs_reindex'])
        self.assertEqual(read['reindex_check'], {'outcome': 'pending'})
        self.assertEqual(read['analysis']['phase'], 'reindex_required')
        self.assertFalse(read['analysis']['review_complete'])
        self.assertEqual(read['analysis']['error'], 'The review service is unavailable.', 'the earlier error was replaced')
        self.assertEqual(read['coverage']['indexed_units'], 0)
        self.assertEqual(read['coverage']['limitations'], [documents.REINDEX_NOTICE])
        for words in ('was updated', 'predates', 're-indexed'):
            self.assertIn(words, documents.REINDEX_NOTICE)
        # A record on which an earlier build saved its own projection: that sentence is not shown as an error twice.
        self.outdate(record['id'], {**REVIEWED, 'phase': 'error', 'review_complete': False, 'error': OLD_NOTICE},
                     coverage={'indexed_units': 0, 'total_units': 2, 'limitations': [OLD_NOTICE]})
        read = self.store.get(self.scope, record['id'])
        self.assertIsNone(read['analysis']['error'])
        self.assertEqual(read['coverage']['limitations'], [documents.REINDEX_NOTICE])

    def test_index_of_a_newer_build_is_left_alone_and_said_to_be_newer(self):
        record = self.indexed()
        self.rewrite(record['id'], lambda saved: saved.update(extraction_version=documents.EXTRACTION_VERSION + 1))
        read = self.store.get(self.scope, record['id'])
        self.assertIs(read['indexed_by_newer_build'], True)
        self.assertFalse(read.get('extraction_needs_reindex'))
        self.assertNotIn('reindex_check', read)
        self.assertEqual(self.store.check_extraction(self.scope, record['id'])['revision'], read['revision'])
        # The statement is made on each read: a saved copy of it does not outlive the difference.
        self.rewrite(record['id'], lambda saved: saved.update(extraction_version=documents.EXTRACTION_VERSION, indexed_by_newer_build=True))
        self.assertNotIn('indexed_by_newer_build', self.store.get(self.scope, record['id']))

    def test_file_that_could_not_be_read_by_the_earlier_version_has_nothing_to_compare(self):
        record = self.store.add(self.scope, 'broken.csv', b'\xff\xfe\x00broken')
        self.rewrite(record['id'], lambda saved: (saved.pop('extraction_version'), saved.update(status='error', error='Earlier failure.')))
        read = self.store.get(self.scope, record['id'])
        # Nothing of it was indexed, so it is not described as an earlier index to re-index: it keeps
        # its failure, and Retry review (which reads it with this version) is offered as for any failure.
        self.assertFalse(read['extraction_needs_reindex'])
        self.assertEqual((read['status'], read['error']), ('error', 'Earlier failure.'))
        self.assertNotIn('reindex_check', read)
        manager = self.manager()
        manager.status(self.scope, {})
        threading.Event().wait(.05)
        self.assertEqual(self.stored(record['id'])['status'], 'error')
        self.assertEqual(self.calls, [])


class LocalComparison(Case):
    def test_unchanged_index_becomes_current_and_keeps_its_review_without_any_provider_request(self):
        record = self.indexed()
        self.outdate(record['id'])
        rows = self.rows(record['id'])
        manager = self.manager()
        first = manager.status(self.scope, {})[0]
        self.assertTrue(first['extraction_needs_reindex'], 'the poll itself still answers cautiously')
        current = self.settled(manager, record['id'])
        self.assertFalse(current['extraction_needs_reindex'])
        self.assertNotIn('reindex_check', current)
        self.assertEqual((current['status'], current['extraction_version']), ('ready', documents.EXTRACTION_VERSION))
        self.assertEqual((current['coverage']['indexed_units'], current['coverage']['total_units']), (2, 2))
        self.assertEqual(current['coverage']['limitations'], [])
        analysis = current['analysis']
        self.assertEqual((analysis['phase'], analysis['review_complete'], analysis['summary']), ('complete', True, 'A fictional stage list.'))
        self.assertEqual(analysis['observations'], REVIEWED['observations'])
        self.assertEqual(analysis['intent_version'], 2, 'the comparison is not a new intent')
        self.assertGreater(analysis['version'], REVIEWED['version'], 'the interview is told that the file is usable again')
        self.assertEqual(self.rows(record['id']), rows, 'the index was rewritten')
        self.assertEqual(self.stored(record['id'])['extraction_version'], documents.EXTRACTION_VERSION)
        for _ in range(3):
            manager.status(self.scope, {})
        threading.Event().wait(.05)
        self.assertEqual(self.calls, [])
        review = manager.supporting_context(self.scope, 'FictionalIntake')['documents'][0]
        self.assertEqual((review['extraction_needs_reindex'], review['review']['phase'], review['review']['review_complete']),
                         (False, 'complete', True))

    def test_completeness_is_decided_again_from_the_coverage_this_version_counts(self):
        # The earlier version counted a page with text and a drawing as read. The sections are the
        # same now, but this version counts the drawing as unread: the review is kept, not its claim.
        record = self.indexed('manual.pdf', visual.pdf_bytes('vector'))
        self.assertEqual(record['chunk_count'], 2)
        self.outdate(record['id'], {**REVIEWED, 'cursor': 2, 'reviewed_chunks': 2, 'total_chunks': 2},
                     coverage={'indexed_units': 1, 'total_units': 1, 'limitations': []})
        manager = self.manager()
        current = self.settled(manager, record['id'])
        self.assertFalse(current['extraction_needs_reindex'])
        self.assertEqual(current['status'], 'partial')
        self.assertEqual((current['coverage']['indexed_units'], current['coverage']['total_units']), (0, 1))
        self.assertIn('native visual review', json.dumps(current['coverage']['limitations']))
        self.assertEqual(current['analysis']['phase'], 'complete')
        self.assertIs(current['analysis']['review_complete'], False)
        self.assertEqual(current['analysis']['summary'], 'A fictional stage list.')
        self.assertEqual(self.calls, [])

    def test_stored_transcription_is_kept_in_place_and_not_read_again(self):
        record = self.indexed('rates.png', png_bytes())
        source_id = record['id'] + '_image_c1'
        self.store.record_extracted_text(self.scope, record['id'], source_id, 'Carrier | Maximum claim\nNorthline | 250')
        before = self.store.get(self.scope, record['id'])
        self.outdate(record['id'])
        self.rewrite(record['id'], lambda saved: saved.pop('visual_transcription_hashes'))
        manager = self.manager()
        current = self.settled(manager, record['id'])
        self.assertFalse(current['extraction_needs_reindex'])
        self.assertEqual(self.store.source(self.scope, record['id'], source_id)['text'], 'Carrier | Maximum claim\nNorthline | 250')
        self.assertEqual(current['inventory']['visual_transcribed_units'], ['image'])
        self.assertEqual(current['visual_transcription_hashes'], before['visual_transcription_hashes'])
        self.assertNotIn('visual_reread_pending', current)
        self.assertEqual((current['coverage']['indexed_units'], current['analysis']['review_complete']), (1, True))
        self.assertEqual(self.calls, [])

    def test_comparing_an_unchanged_index_cannot_finish_a_pending_visual_reread(self):
        record = self.indexed('rates.png', png_bytes())
        source_id = record['id'] + '_image_c1'
        self.store.record_extracted_text(self.scope, record['id'], source_id, 'Carrier | Maximum claim')
        self.store.update(self.scope, record['id'], {'status': 'pending'})
        self.store.extract(self.scope, record['id'])
        self.outdate(record['id'])
        current = self.store.check_extraction(self.scope, record['id'])
        self.assertIn(source_id, current['visual_reread_pending'])
        self.assertFalse(current['extraction_needs_reindex'])
        self.assertFalse(current['analysis']['review_complete'])

    def test_changed_index_stays_held_back_untouched_until_the_explicit_reindex(self):
        record = self.indexed()
        self.outdate(record['id'])
        with self.store._db() as db:
            db.execute("UPDATE chunks SET text='A1=stage as an earlier parser wrote it' WHERE document_id=?", (record['id'],))
        rows = self.rows(record['id'])
        manager = self.manager()
        held = self.settled(manager, record['id'])
        self.assertEqual(held['reindex_check'], {'extraction_version': documents.EXTRACTION_VERSION, 'outcome': 'changed'})
        self.assertTrue(held['extraction_needs_reindex'])
        self.assertEqual((held['analysis']['phase'], held['analysis']['review_complete']), ('reindex_required', False))
        self.assertEqual(self.rows(record['id']), rows, 'a comparison must never replace the index a review cites')
        self.assertEqual(self.stored(record['id'])['analysis'], REVIEWED, 'the saved review was altered')
        review = manager.supporting_context(self.scope, 'stage')['documents'][0]
        self.assertEqual((review['extraction_needs_reindex'], review['review']['phase'], review['review']['review_complete']),
                         (True, 'reindex_required', False))
        with patch.object(self.store, 'check_extraction', side_effect=AssertionError('compared twice')):
            for _ in range(3):
                manager.status(self.scope, {})
            threading.Event().wait(.05)
        self.assertEqual(self.calls, [], 'only the explicit action may start the paid review')
        # The explicit action re-indexes with the current parser and starts that review.
        manager.action(self.scope, record['id'], 'revisit')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not self.calls:
            threading.Event().wait(.01)
        self.assertEqual(self.calls[0], (record['id'], 'quick'))
        after = self.store.get(self.scope, record['id'])
        self.assertFalse(after['extraction_needs_reindex'])
        self.assertNotIn('reindex_check', after)
        self.assertNotIn('reindex_check', self.stored(record['id']))
        self.assertNotEqual(self.rows(record['id'])[0][3], rows[0][3])

    def test_original_that_cannot_be_read_again_is_reported_and_nothing_is_lost(self):
        record = self.indexed()
        self.outdate(record['id'])
        rows = self.rows(record['id'])
        with patch.object(documents, '_csv', side_effect=RuntimeError('private parser detail')):
            held = self.store.check_extraction(self.scope, record['id'])
        self.assertEqual(held['reindex_check']['outcome'], 'failed')
        self.assertTrue(held['extraction_needs_reindex'])
        self.assertNotIn('private parser detail', json.dumps(held))
        self.assertEqual(self.rows(record['id']), rows)
        self.assertEqual(self.stored(record['id'])['analysis'], REVIEWED)
        self.assertEqual(self.store.check_extraction(self.scope, record['id'])['revision'], held['revision'], 'compared twice')

    def test_action_taken_while_the_file_is_read_again_decides_instead(self):
        record = self.indexed()
        self.outdate(record['id'])
        parse = documents._csv

        def removed_meanwhile(path, saved, chunks):
            self.store.archive(self.scope, record['id'])
            return parse(path, saved, chunks)
        with patch.object(documents, '_csv', side_effect=removed_meanwhile):
            result = self.store.check_extraction(self.scope, record['id'])
        self.assertTrue(result['archived'])
        stored = self.stored(record['id'])
        self.assertNotIn('extraction_version', stored)
        self.assertNotIn((stored.get('reindex_check') or {}).get('outcome'), ('changed', 'failed'), 'the abandoned comparison left a verdict')
        # Restored later, the file is compared afresh.
        self.assertEqual(self.store.archive(self.scope, record['id'], False)['reindex_check'], {'outcome': 'pending'})
        self.assertFalse(self.store.check_extraction(self.scope, record['id'])['extraction_needs_reindex'])

    def test_projection_an_earlier_action_saved_with_the_record_is_undone_when_the_index_is_current(self):
        record = self.indexed()
        # An earlier build parked this file: that saved its projection, error sentence included.
        self.outdate(record['id'], {**REVIEWED, 'phase': 'error', 'review_complete': False, 'error': OLD_NOTICE, 'disposition': 'parked',
                                    'parked_by_user': True, 'limitations': [OLD_NOTICE, 'A limit the review recorded.']},
                     coverage={'indexed_units': 0, 'total_units': 2, 'limitations': [OLD_NOTICE]}, extraction_needs_reindex=True)
        current = self.store.check_extraction(self.scope, record['id'])
        self.assertFalse(current['extraction_needs_reindex'])
        analysis = current['analysis']
        self.assertEqual((analysis['phase'], analysis['error'], analysis['review_complete'], analysis['disposition']),
                         ('complete', None, True, 'parked'))
        self.assertEqual(analysis['limitations'], ['A limit the review recorded.'])
        self.assertEqual(current['coverage'], {'indexed_units': 2, 'total_units': 2, 'limitations': []})

    def test_storage_failure_during_the_comparison_is_not_recorded_as_a_failed_review(self):
        record = self.indexed()
        self.outdate(record['id'])
        manager = self.manager()
        attempts = threading.Event()

        def failing(scope, document_id):
            attempts.set()
            raise OSError('the database is busy')
        with patch.object(self.store, 'check_extraction', side_effect=failing):
            manager.status(self.scope, {})
            self.assertTrue(attempts.wait(10))
            threading.Event().wait(.05)
            listed = manager.status(self.scope, {})[0]
        self.assertEqual(listed['reindex_check'], {'outcome': 'pending'})
        self.assertIsNone(listed['analysis'].get('error'))
        self.assertFalse(listed['analysis'].get('retry_required'))
        self.assertEqual(manager._failures, {})
        self.assertEqual(self.stored(record['id'])['analysis'], REVIEWED)
        # Once storage answers again, the next poll compares.
        self.assertFalse(self.settled(manager, record['id'])['extraction_needs_reindex'])
        self.assertEqual(self.calls, [])

    def test_saving_an_outdated_file_for_later_keeps_its_state_and_starts_no_review(self):
        record = self.indexed()
        self.outdate(record['id'])
        manager = self.manager()
        with patch.object(manager, '_schedule') as scheduled:
            parked = manager.action(self.scope, record['id'], 'park')
        self.assertEqual(scheduled.call_args_list, [])
        self.assertEqual((parked['analysis']['phase'], parked['analysis']['disposition']), ('reindex_required', 'parked'))
        self.assertIsNone(parked['analysis'].get('error'))
        current = self.settled(manager, record['id'])
        self.assertFalse(current['extraction_needs_reindex'])
        self.assertEqual((current['analysis']['phase'], current['analysis']['disposition'], current['analysis']['review_complete']),
                         ('complete', 'parked', True))
        self.assertEqual(self.calls, [])


class CompletionGate(unittest.TestCase):
    def test_gate_names_a_file_that_waits_for_its_reindex(self):
        spec = importlib.util.spec_from_file_location('interview_orchestrator', ROOT / 'interview_orchestrator.py')
        import sys
        sys.path.insert(0, str(ROOT))
        try:
            orchestrator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(orchestrator)
        finally:
            sys.path.remove(str(ROOT))
        coordinator = SimpleNamespace(api=SimpleNamespace(participant_requested_stop=lambda turns: False))
        run = SimpleNamespace(ledger=SimpleNamespace(revision=1, snapshot={'turns': []}), stop_answered=False)

        def permit(phases):
            allowed = {'allowed': True, 'ready_for_final_check': True, 'complete': True, 'partial': False, 'blockers': []}
            with patch.object(orchestrator.agent_team, 'completion_permit', return_value=allowed):
                return orchestrator.Coordinator._permit(coordinator, run, {}, {'documents': [{'review': {'phase': phase}} for phase in phases]})
        self.assertEqual(permit(['complete'])['blockers'], [])
        waiting = permit(['complete', 'reindex_required'])
        self.assertEqual(waiting['blockers'], ['documents_pending', 'documents_reindex_required'])
        self.assertFalse(waiting['allowed'] or waiting['complete'] or waiting['ready_for_final_check'])
        self.assertEqual(permit(['deep'])['blockers'], ['documents_pending'])
        self.assertEqual(permit(['error'])['blockers'], ['documents_pending'])


if __name__ == '__main__':
    unittest.main()
