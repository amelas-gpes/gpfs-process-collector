"""A Python without a document reader must say which package is missing, not call the file damaged."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

import test_document_api as api
import test_document_visual_boundaries as visual
from test_documents import workbook_bytes
from test_server import server

documents = server.documents
GENERIC = 'The document could not be safely decoded. Its original is retained.'


def png_bytes():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (40, 20), 'white').save(output, 'PNG')
    return output.getvalue()


def without(*modules):
    """An interpreter in which these modules cannot be found or imported."""
    find = importlib.util.find_spec
    return (patch.dict(sys.modules, {module: None for module in modules}),
            patch.object(documents.importlib.util, 'find_spec', side_effect=lambda name, *rest: None if name in modules else find(name, *rest)))


class MissingReader(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()
        self.events = []
        self.store.diagnostic = lambda event, **fields: self.events.append((event, fields))

    def test_probe_names_exactly_the_kinds_whose_reader_is_absent(self):
        self.assertEqual(documents.unavailable_readers(), {}, 'this runtime has the three readers')
        for modules, kinds in ((('pypdf',), {'pdf'}), (('PIL',), {'png'}), (('openpyxl',), {'xlsx', 'xlsm'}),
                               (('pypdf', 'PIL', 'openpyxl'), {'pdf', 'png', 'xlsx', 'xlsm'})):
            with self.subTest(missing=modules):
                blocked, unfound = without(*modules)
                with blocked, unfound:
                    missing = documents.unavailable_readers()
                self.assertEqual(set(missing), kinds)
                self.assertNotIn('csv', missing)
                for kind, message in missing.items():
                    self.assertEqual(message, documents.missing_reader_message(kind))
                    self.assertIn(documents.READERS[kind][2], message)
        with patch.object(documents.importlib.util, 'find_spec', side_effect=ValueError('a half-installed package')):
            self.assertEqual(set(documents.unavailable_readers()), {'png', 'xlsx', 'xlsm'})

    def test_upload_of_a_kind_without_its_reader_names_the_package_and_recovers_once_it_is_there(self):
        files = (('procedure.pdf', visual.pdf_bytes('text'), 'pypdf', 'pypdf', 'PDF files'),
                 ('rates.png', png_bytes(), 'PIL', 'Pillow', 'PNG image files'),
                 ('ledger.xlsx', workbook_bytes(), 'openpyxl', 'openpyxl', 'Excel workbook files'))
        for name, data, module, package, called in files:
            with self.subTest(file=name):
                record = self.store.add(self.scope, name, data)
                self.events.clear()
                blocked, unfound = without(module)
                with blocked, unfound:
                    failed = self.store.extract(self.scope, record['id'])
                self.assertEqual(failed['status'], 'error')
                self.assertNotEqual(failed['error'], GENERIC, 'a missing package was reported as a damaged file')
                remedy = ('approved release', 'verified PDF reader') if module == 'pypdf' else (
                    'requirements-documents.txt', 'own site-packages', 'isolated mode', 'restart the app')
                for words in (f'cannot read {called}', f'no usable {package} package', *remedy, 'The original is retained.'):
                    self.assertIn(words, failed['error'])
                self.assertEqual(self.events, [('dependency_missing', {'reason': module, 'stage': record['kind'], 'error_type': 'ImportError'})])
                self.assertEqual(self.store.original_bytes(self.scope, record['id']), data)
                # With the package present, the same file is read by a retry.
                self.assertIn(self.store.extract(self.scope, record['id'])['status'], ('ready', 'partial'))

    def test_a_reader_that_lacks_one_of_its_own_modules_is_named_with_that_module(self):
        record = self.store.add(self.scope, 'procedure.pdf', visual.pdf_bytes('text'))
        with patch.object(documents, '_pdf', side_effect=ModuleNotFoundError("No module named 'cryptography.hazmat'", name='cryptography.hazmat')):
            failed = self.store.extract(self.scope, record['id'])
        self.assertIn('no usable pypdf package (module cryptography is missing)', failed['error'])
        self.assertEqual(self.events[-1], ('dependency_missing', {'reason': 'cryptography', 'stage': 'pdf', 'error_type': 'ImportError'}))
        # Only a module name is ever repeated: nothing else an import error says reaches the card.
        with patch.object(documents, '_pdf', side_effect=ImportError('cannot import name SECRET-TEXT from a private path', name='not a module/..')):
            failed = self.store.extract(self.scope, record['id'])
        self.assertEqual(failed['error'], documents.missing_reader_message('pdf'))
        self.assertNotIn('SECRET-TEXT', json.dumps(failed))

    def test_other_failures_and_files_that_need_no_reader_are_unchanged(self):
        record = self.store.add(self.scope, 'procedure.pdf', b'%PDF-1.4 not a pdf at all')
        self.assertEqual(self.store.extract(self.scope, record['id'])['error'], GENERIC)
        blocked, unfound = without('pypdf', 'PIL', 'openpyxl')
        with blocked, unfound:
            listed = self.store.extract(self.scope, self.store.add(self.scope, 'stages.csv', b'stage\nintake\n')['id'])
        self.assertEqual(listed['status'], 'ready')
        self.assertEqual(self.events, [])
        # A diagnostic that fails never fails the file operation.
        self.store.diagnostic = lambda *arguments, **fields: 1 / 0
        again = self.store.add(self.scope, 'rates.png', png_bytes())
        blocked, unfound = without('PIL')
        with blocked, unfound:
            self.assertIn('Pillow', self.store.extract(self.scope, again['id'])['error'])


class ServerSaysWhatItCannotRead(unittest.TestCase):
    def serve(self, *missing):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        blocked, unfound = without(*missing)
        with blocked, unfound:
            httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=api.FakeProvider(),
                                           documents_root=Path(temporary.name) / 'documents')
        worker = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=2)
            for document_worker in httpd.documents._workers:
                document_worker.join(timeout=10)
        self.addCleanup(stop)
        url = f'http://127.0.0.1:{httpd.server_port}'
        with urlopen(Request(url + '/api/config', headers={'Origin': url}), timeout=10) as response:
            config = json.loads(response.read())
        log = Path(temporary.name) / 'server-lifecycle.jsonl'
        events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []
        return config['documents'], [event for event in events if event['event'] == 'dependency_missing']

    def test_config_and_the_event_log_name_the_missing_reader_at_start(self):
        offered, events = self.serve()
        self.assertEqual(offered['types'], ['pdf', 'png', 'xlsx', 'xlsm', 'csv'])
        self.assertEqual(offered['unavailable'], {})
        self.assertEqual(offered['pdf_reader_version'], '6.21.4')
        self.assertEqual(events, [])
        offered, events = self.serve('pypdf')
        self.assertEqual(offered['types'], ['png', 'xlsx', 'xlsm', 'csv'])
        self.assertEqual(offered['unavailable'], {'pdf': documents.missing_reader_message('pdf')})
        self.assertIsNone(offered['pdf_reader_version'])
        self.assertEqual([(event['reason'], event['stage']) for event in events], [('pypdf', 'pdf')])
        offered, events = self.serve('pypdf', 'PIL', 'openpyxl')
        self.assertEqual(offered['types'], ['csv'])
        self.assertEqual(set(offered['unavailable']), {'pdf', 'png', 'xlsx', 'xlsm'})
        self.assertEqual(sorted((event['reason'], event['stage']) for event in events),
                         [('PIL', 'png'), ('openpyxl', 'xlsm'), ('openpyxl', 'xlsx'), ('pypdf', 'pdf')])


if __name__ == '__main__':
    unittest.main()
