"""File review beside the interview: the first question after the first pass, and files side by side.

Finding 6 of docs/testing/runs/2026-11-17-stress: file review was serial and the first question
waited for all of it (161 seconds for an 85-page PDF). Real DocumentStore and DocumentService on a
temporary store with a scripted review callback. No provider or network access.
"""
import threading
import time

from test_document_review_outcomes import ReviewCase, answer, ledger, png_bytes, service_module


class QuestionAfterTheFirstPass(ReviewCase):
    def test_a_text_file_can_be_asked_about_while_its_in_depth_pass_runs(self):
        hold, deep_started = threading.Event(), threading.Event()
        self.addCleanup(hold.set)

        def review(context, record, chunks, phase):
            if phase == 'deep':
                deep_started.set()
                hold.wait(30)
            return answer(chunks)
        service = self.service(review)
        identity = service.upload(self.scope, 'ledger.csv', ledger(12))['id']
        try:
            self.assertTrue(deep_started.wait(30))
            record = self.store.get(self.scope, identity)
            analysis = record['analysis']
            # The first pass is in and the in-depth pass is running: the file's own question need not wait.
            self.assertEqual(analysis['phase'], 'deep')
            self.assertIs(analysis['question_ready'], True)
            self.assertNotIn(analysis['disposition'], ('needs_reason', 'parked'))
            # Nothing a question is bound to changes while the in-depth pass goes on.
            before = service_module.DocumentService._source_revision(record)
        finally:
            hold.set()
        self.wait(identity)
        done = self.store.get(self.scope, identity)
        self.assertEqual(service_module.DocumentService._source_revision(done), before)
        self.assertIs(done['analysis']['review_complete'], True)

    def test_a_file_with_an_unread_image_waits_for_its_reading(self):
        calls = []

        def review(context, record, chunks, phase):
            calls.append(phase)
            return answer(chunks)
        service = self.service(review)
        identity = service.upload(self.scope, 'scan.png', png_bytes())['id']
        self.wait(identity)
        analysis = self.store.get(self.scope, identity)['analysis']
        self.assertIsNot(analysis.get('question_ready'), True,
                         'A reading that arrives later changes what a question is bound to')

    def test_a_file_the_reviewer_cannot_place_is_not_asked_about(self):
        service = self.service(lambda context, record, chunks, phase: answer(chunks, relevance='unclear'))
        identity = service.upload(self.scope, 'ledger.csv', ledger(12))['id']
        self.wait(identity)
        analysis = self.store.get(self.scope, identity)['analysis']
        self.assertEqual(analysis['disposition'], 'needs_reason')
        self.assertIsNot(analysis.get('question_ready'), True)

    def test_a_new_first_pass_withdraws_the_earlier_answer(self):
        record = {'status': 'ready', 'inventory': {}, 'coverage': {'visual_pending_units': 0}}
        ready = service_module.DocumentService._question_ready
        self.assertIs(ready(record, {'disposition': 'use'}), True)
        self.assertIs(ready(record, {'disposition': 'parked'}), False)
        self.assertIs(ready(record, {'disposition': 'use', 'review_stopped': True}), False)
        self.assertIs(ready({**record, 'inventory': {'requires_vision': True}}, {'disposition': 'use'}), False)
        self.assertIs(ready({**record, 'coverage': {'visual_pending_units': 2}}, {'disposition': 'use'}), False)
        self.assertIs(ready({**record, 'visual_reread_pending': {'doc_x_p1': 'kept'}}, {'disposition': 'use'}), False)
        self.assertIs(ready({**record, 'status': 'error'}, {'disposition': 'use'}), False)


class FilesSideBySide(ReviewCase):
    def workers(self, callback, count):
        instance = service_module.DocumentService(self.store, callback, workers=count)
        self.services.append(instance)
        instance.session(self.scope, {'process_name': 'Synthetic intake'})
        return instance

    def tearDown(self):
        for service in self.services:
            service.close()
            for worker in service._workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
        self.services = []
        super().tearDown()

    def test_two_files_are_reviewed_at_once_and_one_file_s_requests_stay_in_order(self):
        lock, active, order = threading.Lock(), {}, []
        most = {'files': 0, 'per_file': 0}
        both = threading.Barrier(2, timeout=30)

        def review(context, record, chunks, phase):
            with lock:
                active[record['id']] = active.get(record['id'], 0) + 1
                most['files'] = max(most['files'], len([name for name, count in active.items() if count]))
                most['per_file'] = max(most['per_file'], active[record['id']])
                order.append((record['name'], phase, chunks[0]['id']))
            if phase == 'quick':
                both.wait()   # Each first pass waits for the other: with one worker this would never pass.
            time.sleep(.01)
            with lock:
                active[record['id']] -= 1
            return answer(chunks)
        service = self.workers(review, 2)
        # Different contents: the same bytes under another name are the same file to the store.
        first = service.upload(self.scope, 'first.csv', ledger(10))['id']
        second = service.upload(self.scope, 'second.csv', ledger(9, size=5100))['id']
        self.assertNotEqual(first, second)
        self.wait(first)
        self.wait(second)
        self.assertEqual(most['files'], 2, 'The two files were not reviewed side by side')
        self.assertEqual(most['per_file'], 1, 'Two requests of one file ran at once')
        for name in ('first.csv', 'second.csv'):
            phases = [phase for file, phase, _ in order if file == name]
            self.assertEqual(phases[0], 'quick')
            self.assertTrue(all(phase == 'deep' for phase in phases[1:]))
            starts = [start for file, phase, start in order if file == name and phase == 'deep']
            self.assertEqual(starts, sorted(starts, key=lambda identity: int(identity.rsplit('r', 1)[-1].split('_')[0])),
                             'The in-depth requests of a file follow the order of its sections')
        for identity in (first, second):
            self.assertIs(self.store.get(self.scope, identity)['analysis']['review_complete'], True)

    def test_one_worker_reviews_as_before(self):
        seen = []
        service = self.workers(lambda context, record, chunks, phase: seen.append(threading.current_thread().name) or answer(chunks), 1)
        identity = service.upload(self.scope, 'ledger.csv', ledger(6))['id']
        self.wait(identity)
        self.assertEqual(len(service._workers), 1)
        self.assertIs(service._worker, service._workers[0])
        self.assertEqual(set(seen), {'document-review'})

    def test_closing_stops_every_worker(self):
        service = self.workers(lambda context, record, chunks, phase: answer(chunks), 3)
        service.close()
        for worker in service._workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    import unittest
    unittest.main()
