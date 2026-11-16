"""Company knowledge never takes the placeholder of an unread page or image for file content.

A scanned page or an image holds a sentence such as "Image contents require native visual review"
until a visual review transcribes it (and again when a re-read loses the transcription). That sentence
is not an excerpt for matching and cannot be quoted as document-supported evidence.
Temporary SQLite and stores only; the analyzer is injected, no provider or network.
"""
import knowledge_rows as rows
import importlib.util
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from test_server import server
from test_knowledge_graph import kg, payload, proposal, wait

PLACEHOLDER = 'PNG image 660 by 215 pixels. Image contents require native visual review; no OCR was performed.'
TRANSCRIPTION = 'Carrier | Service | Maximum claim per consignment\nBrindle Freight | Standard pallet | $2,375'


def placeholder():
    return {'text': PLACEHOLDER, 'label': 'carrier-claims.png · image', 'image': True, 'requires_vision': True, 'origin': 'visual_placeholder',
            'location': {'image': True, 'requires_vision': True, 'origin': 'visual_placeholder'}}


def transcription():
    return {'text': TRANSCRIPTION, 'label': 'carrier-claims.png · image', 'image': True, 'requires_vision': False,
            'origin': 'ai_visual_transcription', 'verified': False,
            'location': {'image': True, 'requires_vision': False, 'origin': 'ai_visual_transcription', 'verified': False}}


def quoting(document_id, source_id, quote):
    """An analyzer that quotes the file as document-supported evidence of the submission that lists it."""
    def analyze(current, candidates):
        other = next(item for item in candidates
                     if any(doc.get('id') == document_id for doc in (item.get('documents') or {}).get('documents', [])))
        result = proposal(current, [other])
        result[0]['evidence'][0] = {'type': 'document_supported', 'submission_id': other['submission_id'],
                                    'revision': other['revision'], 'document_id': document_id, 'source_id': source_id, 'quote': quote}
        return result
    return analyze


class PlaceholderEvidenceGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db', proposal)
        self.sources = {'image': placeholder(), 'page5': {'text': 'Approved NAV is published for Fund A.', 'label': 'Page 5', 'origin': 'source_extraction'}}
        self.graph.document_resolver = lambda scope, document_id, source_id: self.sources[source_id]

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def submit_with_file(self, sources=('image', 'page5')):
        body = payload('A', 'We prepare NAV.')
        body['documents'] = {'documents': [{'id': 'doc1', 'sources': [{'source_id': source, 'label': source} for source in sources]}]}
        receipt = self.graph.submit(body, document_scope='private')
        wait(self.graph, receipt['job_id'])
        return receipt

    def test_unread_visual_source_is_not_offered_to_matching(self):
        self.submit_with_file()
        seen = []
        def analyze(current, candidates):
            seen.append(candidates[0]['document_excerpts'])
            return []
        self.graph.analyzer = analyze
        second = self.graph.submit(payload('B', 'We receive approved NAV.'))
        self.assertEqual(wait(self.graph, second['job_id'])['status'], 'completed')
        self.assertEqual([excerpt['source_id'] for excerpt in seen[0]], ['page5'], 'The placeholder is skipped and the read page still offered')
        self.assertNotIn('require native visual review', json.dumps(seen))

    def test_unread_visual_source_cannot_back_a_document_supported_quote(self):
        self.submit_with_file(sources=('image',))
        self.graph.analyzer = quoting('doc1', 'image', 'Image contents require native visual review')
        second = self.graph.submit(payload('B', 'We receive approved NAV.'))
        # live-draft-knowledge-5: the refused proposal is dropped on its own; the job completes without it.
        row = wait(self.graph, second['job_id'])
        self.assertEqual((row['status'], row['detail']['dropped_reasons']), ('completed', {'Document source has not been read.': 1}))
        self.assertEqual(rows.proposals(self.graph), [])

    def test_location_alone_marks_a_placeholder(self):
        # A resolver that reports the chunk location without spreading it over the source.
        self.sources['image'] = {'text': PLACEHOLDER, 'label': 'image', 'location': {'requires_vision': True, 'origin': 'visual_placeholder'}}
        receipt = self.submit_with_file(sources=('image',))
        with self.assertRaisesRegex(ValueError, 'has not been read'):
            self.graph._document_source(receipt['submission_id'], 1, 'doc1', 'image')
        self.sources['image'] = {'text': PLACEHOLDER, 'label': 'image', 'origin': 'visual_placeholder'}
        with self.assertRaisesRegex(ValueError, 'has not been read'):
            self.graph._document_source(receipt['submission_id'], 1, 'doc1', 'image')

    def test_visual_transcription_stays_eligible_and_marked_unverified(self):
        self.sources['image'] = transcription()
        self.submit_with_file(sources=('image',))
        seen = []
        def analyze(current, candidates):
            seen.append(candidates[0]['document_excerpts'])
            return quoting('doc1', 'image', 'Brindle Freight | Standard pallet | $2,375')(current, candidates)
        self.graph.analyzer = analyze
        second = self.graph.submit(payload('B', 'We receive approved NAV.'))
        self.assertEqual(wait(self.graph, second['job_id'])['status'], 'completed')
        self.assertEqual((seen[0][0]['origin'], seen[0][0]['verified']), ('ai_visual_transcription', False))
        evidence = rows.proposals(self.graph)[0]['evidence'][0]
        self.assertEqual((evidence['type'], evidence['origin'], evidence['verified']), ('document_supported', 'ai_visual_transcription', False))



@unittest.skipUnless(importlib.util.find_spec('PIL'), 'Existing Pillow runtime required')
class PlaceholderEvidenceStoreTests(unittest.TestCase):
    """The same rule through the real document store and the server's resolver."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.requests = []
        def analyze(current, candidates):
            self.requests.append([excerpt for item in candidates for excerpt in item['document_excerpts']])
            return self.reply(current, candidates)
        self.reply = lambda current, candidates: []
        self.httpd = server.InterviewServer(
            ('127.0.0.1', 0), server.Handler, client=server.OpenAIClient({}),
            documents_root=Path(self.temp.name) / 'documents', knowledge_root=Path(self.temp.name) / 'graph',
            knowledge_settings={'COLLECTOR_DEPLOYMENT_MODE': 'local', 'KNOWLEDGE_LOCAL_OWNER': 'true'}, knowledge_analyzer=analyze)

    def tearDown(self):
        self.httpd.server_close()
        self.temp.cleanup()

    def finished(self, receipt):
        for _ in range(1500):
            job = self.httpd.knowledge.status(receipt['submission_id'], receipt['revision'], receipt['status_token'])
            if job['status'] not in ('pending', 'processing'):
                return job['status']
            time.sleep(.01)
        self.fail('The matching job did not finish.')

    def test_image_is_evidence_only_once_it_has_been_transcribed(self):
        from PIL import Image
        picture = io.BytesIO()
        Image.new('RGB', (66, 21), 'white').save(picture, format='PNG')
        store, graph = self.httpd.documents_store, self.httpd.knowledge
        scope = store.create_scope()
        record = store.add(scope, 'carrier-claims.png', picture.getvalue())
        store.extract(scope, record['id'])
        source = store.chunks(scope, record['id'])['chunks'][0]
        self.assertEqual(source['origin'], 'visual_placeholder')
        # The submission manifest as the submit route writes it for a file whose review cites its image.
        first = payload('Claims', 'We check the carrier claim limit.')
        first['documents'] = {'documents': [{'id': record['id'], 'name': 'carrier-claims.png',
                                             'sources': [{'source_id': source['id'], 'label': source['label']}]}]}
        a = graph.submit(first, document_scope=scope)
        self.finished(a)
        self.reply = quoting(record['id'], source['id'], 'Image contents require native visual review')
        b = graph.submit(payload('Returns', 'We raise a carrier claim for damaged returns.'))
        self.assertEqual(self.finished(b), 'completed', 'The job completes; the proposal that quotes the placeholder is dropped')
        self.assertEqual(next(job for job in rows.jobs(graph) if job['id'] == b['job_id'])['detail']['dropped_reasons'],
                         {'Document source has not been read.': 1}, 'The placeholder sentence is not document-supported evidence')
        self.assertEqual(self.requests[-1], [], 'The placeholder sentence is not sent to matching as an excerpt')
        self.assertEqual(rows.proposals(graph), [])
        store.record_extracted_text(scope, record['id'], source['id'], TRANSCRIPTION)
        self.reply = quoting(record['id'], source['id'], 'Brindle Freight | Standard pallet | $2,375')
        c = graph.submit(payload('Freight', 'We book standard pallets with the carrier.'))
        self.assertEqual(self.finished(c), 'completed')
        self.assertEqual([(excerpt['text'], excerpt['origin'], excerpt['verified']) for excerpt in self.requests[-1]],
                         [(TRANSCRIPTION, 'ai_visual_transcription', False)])
        self.assertEqual(len(rows.proposals(graph)), 1)


if __name__ == '__main__':
    unittest.main()
