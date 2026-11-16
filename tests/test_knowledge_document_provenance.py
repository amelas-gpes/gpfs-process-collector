"""A submission records how each cited file passage was read (gap-knowledge-documents-2).

A step may cite a model's reading of a screenshot or scanned page. The stored excerpt must say so
(origin 'ai_visual_transcription', verified False), so Admin does not present it as the file's own text.
The pair comes from the server-hydrated catalog only. Temporary SQLite; no analyzer, provider or network.
"""
import knowledge_rows as rows
import tempfile
import unittest
import uuid
from pathlib import Path

from test_server import server
from test_knowledge_graph import kg, payload

DOC = 'doc_' + 'c' * 32
IMAGE, PAGE = DOC + '_image_c1', DOC + '_p1_c1'
READING = 'Brindle Freight | Standard pallet | $2,375 | 14 days'
NATIVE = 'Claims above the carrier limit go to the insurer.'


def hydrated():
    """The catalog the submit route builds (document_evidence_catalog) for a PNG reading and a PDF page."""
    reading = {'image': True, 'requires_vision': False, 'origin': 'ai_visual_transcription', 'verified': False}
    image = {'id': IMAGE, 'label': 'carrier-claim-limits.png · image', 'text': READING, 'location': reading, **reading}
    page = {'id': PAGE, 'label': 'policy.pdf · page 1', 'text': NATIVE, 'location': {'page': 1}}
    return server.document_evidence_catalog({'documents': [{'id': DOC, 'name': 'claims', 'excerpts': [image, page]}]})


def submission(**changes):
    body = payload('Carrier claims', 'We check the carrier claim limit.')
    body['documents'] = {'documents': [{'id': DOC, 'name': 'claims', 'sources': [{'source_id': IMAGE}, {'source_id': PAGE}]}]}
    body['draft']['steps'][0]['evidence_turns'] = [IMAGE]
    body['draft']['steps'][1]['evidence_turns'] = [PAGE, 'u1']
    body.update(changes)
    return body


class DocumentProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def stored(self, receipt):
        item = self.graph._revision(receipt['submission_id'], receipt['revision'])
        return {source['id']: source for source in item['document_evidence']}

    def test_stored_excerpt_keeps_how_it_was_read(self):
        catalog = hydrated()
        self.assertEqual(catalog[0]['location']['origin'], 'ai_visual_transcription', 'The route catalog carries the reading in location')
        receipt = self.graph.submit(submission(), document_scope='private', document_evidence=catalog)
        saved = self.stored(receipt)
        self.assertEqual((saved[IMAGE]['origin'], saved[IMAGE]['verified']), ('ai_visual_transcription', False))
        self.assertEqual(saved[PAGE]['origin'], 'source_extraction')
        self.assertNotIn('verified', saved[PAGE], 'Native text is not claimed to be verified or unverified')
        self.assertNotIn('location', saved[IMAGE], 'Only the allow-listed pair is stored, not the whole location')


    def test_only_the_two_known_origins_are_stored(self):
        # Anything else the hydrated source says about itself is not carried into the stored record.
        catalog = hydrated()
        catalog[1]['location'] = {'origin': 'verified_by_owner', 'verified': True}
        catalog[1]['verified'] = True
        receipt = self.graph.submit(submission(), document_scope='private', document_evidence=catalog)
        saved = self.stored(receipt)
        self.assertEqual(saved[PAGE]['origin'], 'source_extraction')
        self.assertNotIn('verified', saved[PAGE])

    def test_browser_supplied_provenance_is_never_stored(self):
        # The submitted JSON's own catalog is dropped; the marker cannot be cleared from the browser.
        body = submission(document_evidence=[{'id': IMAGE, 'document_id': DOC, 'text': READING, 'origin': 'source_extraction', 'verified': True}])
        receipt = self.graph.submit(body, document_scope='private', document_evidence=hydrated())
        saved = self.stored(receipt)
        self.assertEqual((saved[IMAGE]['origin'], saved[IMAGE]['verified']), ('ai_visual_transcription', False))

    def test_saved_excerpt_of_a_removed_file_keeps_its_marker(self):
        first = self.graph.submit(submission(), document_scope='private', document_evidence=hydrated())
        revised = submission(process_id=first['process_id'])
        revised['documents'] = {'documents': [], 'retained': [{'id': DOC, 'name': 'claims', 'archived': True,
                                                               'sources': [{'source_id': IMAGE}, {'source_id': PAGE}]}]}
        kept = server.document_evidence_catalog({'retained_evidence': [
            {**item, 'retained_only': True, 'archived': True, 'disposition': 'relevant'} for item in hydrated()]})
        second = self.graph.submit(revised, document_scope='private', document_evidence=kept)
        saved = self.stored(second)
        self.assertTrue(saved[IMAGE]['retained_only'])
        self.assertEqual((saved[IMAGE]['origin'], saved[IMAGE]['verified']), ('ai_visual_transcription', False))
        self.assertEqual(saved[PAGE]['origin'], 'source_extraction')

    def test_a_key_first_used_before_the_marker_was_recorded_still_recovers_its_submission(self):
        # The content digest of an idempotency key leaves the marker out, so a retry across the upgrade is recognised.
        key = str(uuid.uuid4())
        receipt = self.graph.submit(submission(submission_key=key), document_scope='private', document_evidence=hydrated())
        legacy = [{k: v for k, v in item.items() if k != 'location'} for item in hydrated()]
        again = self.graph.submit(submission(submission_key=key), document_scope='private', document_evidence=legacy)
        self.assertEqual(again['submission_id'], receipt['submission_id'])
        self.assertEqual(len(rows.submissions(self.graph)), 1)


if __name__ == '__main__':
    unittest.main()
