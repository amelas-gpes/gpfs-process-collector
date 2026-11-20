"""The server reads each file in a separate Python process, with the same result as in its own.

Reading a 300-page PDF or a 200,000-row workbook is seconds of pure-Python work. Inside the
server it held the interpreter lock that every request thread needs: in the November 19 stress
test a typed interview's next question took 2.02 s instead of 1.86 s while five large files were
read in another interview, and status polls took up to 175 ms. The store the server opens now
runs the reader in its own process (documents._parse_apart) and publishes what it sends back.

These tests read the same files both ways and compare the results byte for byte, then check the
errors, the time limit, a reader process that dies, the fallback to the server's own process, the
bound on processes at once and a desktop release's folder. Local only; no provider.
"""
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parser_process_documents', APP / 'documents.py')
documents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(documents)

AUDIT = APP / 'tests' / 'fixtures' / 'document-audit'
UPLOADS = APP / 'docs' / 'testing' / 'runs' / '2026-11-16-process-capture' / 'uploads' / 'inputs'
GENERIC = 'The document could not be safely decoded. Its original is retained.'
STORAGE = 'Local storage could not publish the index. Check free disk space and access, then select Retry review.'
READERS = all(importlib.util.find_spec(name) for name in ('pypdf', 'openpyxl', 'PIL'))


def workbook_bytes():
    """Formulas, a comment, dates and flags, text in several scripts, a row wider than one section, a hidden tab."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    book = Workbook()
    sheet = book.active
    sheet.title = 'Approvals'
    sheet.append(['Step', 'Owner', 'Amount', 'Approved', 'Due', 'Note'])
    for row in range(2, 302):
        sheet.append([f'Step {row} – rapprochement', 'Zoë Åström', row * 1.25, row % 2 == 0,
                      datetime.date(2026, 11, row % 28 + 1), '数据 ✓ ½ line break 😀'])
    sheet['G2'] = '=C2*2'
    sheet['A1'].comment = Comment('Checked by treasury', 'Analyst')
    sheet.append(['wide'] + ['x' * 900] * 9)
    hidden = book.create_sheet('Rates')
    hidden.sheet_state = 'hidden'
    hidden.append(['EUR', 1.0842, None, 'überweisung'])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def png_bytes():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (40, 20), 'white').save(output, 'PNG')
    return output.getvalue()


CSV = ('Étape;Rôle;Montant\nVérifier ✓;Trésorerie;1 250,00\n"deux\nlignes";Contrôle 😀; \n'
       + ''.join(f'Step {row};Analyst {row % 7};{row}\n' for row in range(400))).encode('utf-8-sig')


def boot(setup):
    """The reader process, with `setup` run after it loads the reader (`module` is the reader's module)."""
    return documents._PARSER_BOOT.replace('module._parse_apart_main()', setup + '\nmodule._parse_apart_main()')


def read_here(path, record):
    chunks = documents._Chunks(record)
    inventory, coverage = getattr(documents, documents.PARSERS[record['kind']])(path, record, chunks)
    return inventory, coverage, chunks


def exact(parsed):
    inventory, coverage, chunks = parsed
    return json.dumps([inventory, coverage, chunks.items, chunks.characters],
                      ensure_ascii=False).encode('utf-8', 'surrogatepass')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='collector-parser-process-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.events = []
        self.store = self.open_store('apart', parser_processes=2)

    def open_store(self, name, **options):
        store = documents.DocumentStore(self.folder / name, **options)
        store.diagnostic = lambda event, **fields: self.events.append((event, fields))
        return store

    def extract(self, name, data, store=None):
        store = store or self.store
        scope = store.create_scope()
        return store, scope, store.extract(scope, store.add(scope, name, data)['id'])

    def file(self, name, data):
        path = self.folder / name
        path.write_bytes(data)
        return path

    def files(self):
        made = [self.file('procedure.csv', CSV)]
        if READERS:
            made += [self.file('register.xlsx', workbook_bytes()), self.file('chart.png', png_bytes()),
                     AUDIT / 'settlement-intake.pdf', AUDIT / 'settlement-checks.xlsx']
            made += sorted(UPLOADS.glob('*.pdf'))
        return made + sorted(UPLOADS.glob('*.csv'))

    def children(self):
        """Every reader process started while the patch is active, in start order."""
        started, real, self.options = [], subprocess.Popen, []

        def start(*arguments, **options):
            self.options.append(options)
            started.append(real(*arguments, **options))
            return started[-1]
        return started, patch.object(documents.subprocess, 'Popen', side_effect=start)


class SameResult(Fixture):
    def test_every_kind_reads_byte_for_byte_the_same_in_its_own_process(self):
        for path in self.files():
            kind = path.suffix[1:].lower()
            record = {'id': 'doc_' + 'ab' * 12, 'name': path.name, 'kind': kind}
            with self.subTest(file=path.name):
                here = read_here(path, record)
                # The reader of this process fails: only the separate process can read the file.
                with patch.object(documents, documents.PARSERS[kind], side_effect=AssertionError('read in the server')):
                    apart = documents._parse_apart(path, record, threading.BoundedSemaphore(1),
                                                   lambda event, **fields: self.events.append(event))
                self.assertIsNotNone(apart, self.events)
                self.assertEqual(apart[0], here[0])
                self.assertEqual(apart[1], here[1])
                self.assertEqual(apart[2].items, here[2].items)
                self.assertEqual(exact(apart), exact(here))
                self.assertTrue(here[2].items)
        self.assertEqual(self.events, [])

    def test_the_published_index_and_record_are_the_ones_the_server_process_publishes(self):
        here_store = self.open_store('here')
        for path in self.files():
            with self.subTest(file=path.name):
                data = path.read_bytes()
                _, here_scope, here = self.extract(path.name, data, here_store)
                with patch.object(documents, documents.PARSERS[path.suffix[1:].lower()],
                                  side_effect=AssertionError('read in the server')):
                    _, scope, apart = self.extract(path.name, data)
                for key in ('status', 'error', 'error_code', 'inventory', 'coverage', 'chunk_count', 'extraction_version'):
                    self.assertEqual(json.dumps(apart.get(key)).replace(apart['id'], 'ID'),
                                     json.dumps(here.get(key)).replace(here['id'], 'ID'), key)
                if here['status'] == 'error':
                    continue
                rows = [self.store.chunks(scope, apart['id'], offset, 500)['chunks'] for offset in range(0, apart['chunk_count'], 500)]
                here_rows = [here_store.chunks(here_scope, here['id'], offset, 500)['chunks']
                             for offset in range(0, here['chunk_count'], 500)]
                self.assertEqual(json.dumps(rows, ensure_ascii=False).replace(apart['id'], 'ID'),
                                 json.dumps(here_rows, ensure_ascii=False).replace(here['id'], 'ID'))
        self.assertEqual(self.events, [])

    def test_a_library_that_prints_does_not_disturb_the_result(self):
        record = {'id': 'doc_' + 'cd' * 12, 'name': 'procedure.csv', 'kind': 'csv'}
        path = self.file('procedure.csv', CSV)
        noisy = boot('real = module._csv\n'
                     'def noisy(*arguments):\n'
                     '    print("a library talking", flush=True)\n'
                     '    return real(*arguments)\n'
                     'module._csv = noisy')
        with patch.object(documents, '_PARSER_BOOT', noisy):
            apart = documents._parse_apart(path, record, threading.BoundedSemaphore(1), lambda *_, **__: None)
        self.assertEqual(exact(apart), exact(read_here(path, record)))


class Errors(Fixture):
    def failing(self, error):
        return boot('def failing(*arguments):\n'
                    f'    raise {error}\n'
                    'module._csv = module._png = failing')

    def test_a_reader_message_written_for_the_participant_passes_through(self):
        here = self.extract('log.csv', (AUDIT / 'settlement-log.csv').read_bytes(), self.open_store('here'))[2]
        apart = self.extract('log.csv', (AUDIT / 'settlement-log.csv').read_bytes())[2]
        self.assertIn('CSV must be UTF-8', apart['error'])
        self.assertEqual([apart[key] for key in ('status', 'error', 'error_code', 'retryable')],
                         [here[key] for key in ('status', 'error', 'error_code', 'retryable')])

    def test_what_a_parser_says_never_reaches_the_record(self):
        with patch.object(documents, '_PARSER_BOOT', self.failing("RuntimeError('PRIVATE CELL TEXT from row 12')")):
            store, scope, record = self.extract('log.csv', CSV)
        self.assertEqual((record['status'], record['error'], record['error_code']), ('error', GENERIC, 'invalid_file'))
        self.assertNotIn('PRIVATE', json.dumps(store.get(scope, record['id'])))
        self.assertNotIn('PRIVATE', json.dumps(self.events))

    def test_a_missing_reader_package_is_named_as_before(self):
        with patch.object(documents, '_PARSER_BOOT', self.failing("ModuleNotFoundError('No module named PIL', name='PIL')")):
            record = self.extract('chart.png', png_bytes() if READERS else b'\x89PNG\r\n\x1a\n')[2]
        self.assertEqual((record['error'], record['error_code']), (documents.missing_reader_message('png', 'PIL'), 'dependency_missing'))
        self.assertEqual(self.events, [('dependency_missing', {'reason': 'PIL', 'stage': 'png', 'error_type': 'ImportError'})])

    def test_an_os_error_keeps_its_wording_and_its_class_name_in_the_log(self):
        with patch.object(documents, '_PARSER_BOOT', self.failing("PermissionError(13, 'PRIVATE path')")):
            record = self.extract('log.csv', CSV)[2]
        self.assertEqual((record['error'], record['error_code'], record['retryable']), (STORAGE, 'storage_unavailable', True))
        self.assertEqual(self.events, [('document_storage_unavailable', {'stage': 'publish', 'error_type': 'PermissionError'})])

    def test_a_reader_that_runs_past_its_limit_is_ended_with_its_kinds_message(self):
        sleeping = boot('import time\n'
                        'def sleeping(*arguments):\n'
                        '    time.sleep(60)\n'
                        'module._csv = module._workbook = sleeping')
        started, popen = self.children()
        limits = {**documents.PARSER_SECONDS, 'csv': .3, 'xlsx': .3}
        with patch.object(documents, '_PARSER_BOOT', sleeping), popen, \
                patch.object(documents, 'PARSER_SECONDS', limits), patch.object(documents, 'PARSER_MARGIN_SECONDS', .5):
            began = time.monotonic()
            workbook = self.extract('register.xlsx', b'PK\x03\x04 not read')[2]
            table = self.extract('log.csv', CSV)[2]
        self.assertLess(time.monotonic() - began, 20)
        self.assertEqual(workbook['error'], documents.WORKBOOK_TIME_MESSAGE)
        self.assertEqual(table['error'], GENERIC)
        self.assertEqual([child.poll() is None for child in started], [False, False], 'Both processes were ended')
        self.assertEqual([fields['outcome'] for event, fields in self.events], ['time_limit', 'time_limit'])
        # Each limit leaves a reader its own budget plus the time to start.
        self.assertEqual(documents.PARSER_SECONDS['pdf'], 45 + documents.PDF_DRAWING_SECONDS)
        self.assertEqual(documents.PARSER_SECONDS['xlsx'], 90)

    def test_a_reader_process_that_dies_leaves_a_clean_error_and_a_working_store(self):
        ways = ['os._exit(3)']
        if hasattr(signal, 'SIGKILL'):
            ways.append('os.kill(os.getpid(), signal.SIGKILL)')  # What the system does to a process using too much memory.
        for way in ways:
            self.events.clear()
            dying = boot('import os, signal\n'
                         'def dying(*arguments):\n'
                         f'    {way}\n'
                         'module._csv = dying')
            with self.subTest(way=way), patch.object(documents, '_PARSER_BOOT', dying):
                record = self.extract('log.csv', CSV)[2]
                self.assertEqual((record['status'], record['error'], record['error_code']), ('error', GENERIC, 'invalid_file'))
                self.assertEqual([(event, fields['outcome']) for event, fields in self.events], [('document_parser_process', 'ended')])
        self.assertEqual(self.extract('log.csv', CSV)[2]['status'], 'ready')


class Fallback(Fixture):
    def assert_read_here(self, record):
        self.assertEqual(record['status'], 'ready', record.get('error'))
        self.assertEqual([fields['outcome'] for event, fields in self.events], ['unavailable'])

    def test_a_computer_that_refuses_to_start_python_reads_the_file_in_the_server(self):
        with patch.object(documents.subprocess, 'Popen', side_effect=PermissionError(13, 'blocked by policy')):
            self.assert_read_here(self.extract('log.csv', CSV)[2])
        self.assertEqual(self.events[0][1]['error_type'], 'PermissionError')

    def test_a_python_that_cannot_load_the_reader_falls_back_as_well(self):
        with patch.object(documents, '_PARSER_BOOT', 'import sys\nsys.exit(1)\n'):
            self.assert_read_here(self.extract('log.csv', CSV)[2])

    def test_a_python_embedded_in_another_program_is_not_started(self):
        started, popen = self.children()
        with patch.object(documents.sys, 'executable', ''), popen:
            record = self.extract('log.csv', CSV)[2]
        self.assertEqual((record['status'], started), ('ready', []))

    def test_a_store_without_parser_processes_reads_in_its_own_process(self):
        started, popen = self.children()
        with popen:
            record = self.extract('log.csv', CSV, self.open_store('here'))[2]
        self.assertEqual((record['status'], started, self.events), ('ready', [], []))


class Processes(Fixture):
    def test_no_more_readers_run_at_once_than_the_store_allows(self):
        running, started, real = [], [], subprocess.Popen

        def start(*arguments, **options):
            child = real(*arguments, **options)
            started.append(child)
            running.append(sum(other.poll() is None for other in started))
            return child
        slow = boot('import time\n'
                    'real = module._csv\n'
                    'def slow(*arguments):\n'
                    '    time.sleep(.4)\n'
                    '    return real(*arguments)\n'
                    'module._csv = slow')
        results = []
        with patch.object(documents, '_PARSER_BOOT', slow), patch.object(documents.subprocess, 'Popen', side_effect=start):
            threads = [threading.Thread(target=lambda: results.append(self.extract('log.csv', CSV)[2]['status']))
                       for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
        self.assertEqual(results, ['ready'] * 5)
        self.assertEqual(len(started), 5)
        self.assertEqual(max(running), 2, running)

    def test_a_desktop_release_folder_is_found_without_the_checkout_on_sys_path(self):
        # A release is a folder of its own (desktop/manage.py) whose server loads documents.py by path.
        release = self.folder / 'Process Collector ünïcode' / 'releases' / 'abc123'
        release.mkdir(parents=True)
        shutil.copy2(APP / 'documents.py', release / 'documents.py')
        loader = importlib.util.spec_from_file_location('collector_release_documents', release / 'documents.py')
        copy = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(copy)
        path = self.file('procedure.csv', CSV)
        record = {'id': 'doc_' + 'ef' * 12, 'name': path.name, 'kind': 'csv'}
        started, popen = self.children()
        with popen:
            apart = copy._parse_apart(path, record, threading.BoundedSemaphore(1), lambda *_, **__: self.fail('fell back'))
        self.assertEqual(exact(apart), exact(read_here(path, record)))
        command = started[0].args
        self.assertEqual(command[:3], [sys.executable, '-I', '-B'])
        self.assertEqual(Path(command[-1]), (release / 'documents.py').resolve())
        # Its own session: Ctrl+C in the server's terminal stops the server, not this reader.
        self.assertIs(self.options[0]['start_new_session'], True)

    def test_the_reader_process_finds_packages_where_the_server_does(self):
        # A folder only this process searches: put on sys.path by a launcher, or by a Python started without -I.
        packages = self.folder / 'packages'
        packages.mkdir()
        (packages / 'collector_probe_package.py').write_text('FOUND = True\n', encoding='utf-8')
        sys.path.insert(0, str(packages))
        self.addCleanup(sys.path.remove, str(packages))
        probing = boot('real = module._csv\n'
                       'def probing(*arguments):\n'
                       '    import collector_probe_package\n'
                       '    return real(*arguments)\n'
                       'module._csv = probing')
        with patch.object(documents, '_PARSER_BOOT', probing):
            record = self.extract('log.csv', CSV)[2]
        self.assertEqual((record['status'], record.get('error')), ('ready', None))
        self.assertEqual(self.events, [])

    def test_the_server_reads_files_in_one_process_per_review_worker(self):
        server_spec = importlib.util.spec_from_file_location('parser_process_server', APP / 'server.py')
        server = importlib.util.module_from_spec(server_spec)
        sys.modules[server_spec.name] = server
        self.addCleanup(sys.modules.pop, server_spec.name, None)
        server_spec.loader.exec_module(server)

        class Quiet:
            def public_config(self):
                return {'api_configured': True}

            def browser_connect_sources(self):
                return ()

        httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=Quiet(),
                                       documents_root=self.folder / 'server' / 'documents', knowledge_settings={})
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.documents.close)
        store = httpd.documents_store
        self.assertEqual(store._parser_slots._initial_value, server.DOCUMENT_REVIEW_WORKERS)
        started, real = [], subprocess.Popen

        def start(*arguments, **options):
            started.append(real(*arguments, **options))
            return started[-1]
        scope = store.create_scope()
        with patch.object(server.documents.subprocess, 'Popen', side_effect=start):
            record = store.extract(scope, store.add(scope, 'procedure.csv', CSV)['id'])
        self.assertEqual((record['status'], len(started)), ('ready', 1))


if __name__ == '__main__':
    unittest.main()
