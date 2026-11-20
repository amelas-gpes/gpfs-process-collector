"""The server reads each file in a separate Python process, with the same result as in its own.

Reading a 300-page PDF or a 200,000-row workbook is seconds of pure-Python work. Inside the
server it held the interpreter lock that every request thread needs: in the November 19 stress
test a typed interview's next question took 2.02 s instead of 1.86 s while five large files were
read in another interview, and status polls took up to 175 ms. The store the server opens now
runs the reader in its own process (documents._parse_apart) and publishes what it sends back.

These tests read the same files both ways and compare the results byte for byte, then check the
errors, the time limit (counted from when the reader is ready, and again from when its own budget
starts), a reader process ended from outside, the fallback to the server's own process (also when
documents.py changed on disk after the server loaded it), readers ending with the server and when
the app closes, their priority, the bound on processes at once and a desktop release's folder.
Local only; no provider.
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
import types
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('parser_process_documents', APP / 'documents.py')
documents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(documents)
launcher_spec = importlib.util.spec_from_file_location('parser_process_launcher', APP / 'launcher.py')
launcher = importlib.util.module_from_spec(launcher_spec)
launcher_spec.loader.exec_module(launcher)

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

    def waiting(self, marker, seconds=60):
        """A reader process that says when it is reading, then reads for `seconds` (as a large or hung file does)."""
        return boot('import time\n'
                    'def waiting(*arguments):\n'
                    f'    open({str(marker)!r}, "w").close()\n'
                    f'    time.sleep({seconds})\n'
                    'module._csv = waiting')

    def wait_for(self, marker, seconds=20):
        until = time.monotonic() + seconds
        while not marker.exists():
            self.assertLess(time.monotonic(), until, 'The reader process never started reading')
            time.sleep(.02)


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

    def test_a_reader_process_that_dies_leaves_the_file_to_retry_and_a_working_store(self):
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
                self.assertEqual([record[key] for key in ('status', 'error', 'error_code', 'retryable')],
                                 ['error', documents.READING_STOPPED_MESSAGE, 'reading_stopped', True])
                self.assertEqual([(event, fields['outcome']) for event, fields in self.events], [('document_parser_process', 'ended')])
        self.assertEqual(self.extract('log.csv', CSV)[2]['status'], 'ready')

    def test_a_reader_that_sends_something_out_of_place_fails_the_file_as_before(self):
        garbling = boot('import sys\n'
                        'def garbling(*arguments):\n'
                        "    sys.__stdout__.buffer.write(b'{PRIVATE CELL TEXT\\n')\n"
                        '    sys.__stdout__.buffer.flush()\n'
                        '    import time\n'
                        '    time.sleep(60)\n'
                        'module._csv = garbling')
        started, popen = self.children()
        with patch.object(documents, '_PARSER_BOOT', garbling), popen:
            record = self.extract('log.csv', CSV)[2]
        self.assertEqual([record[key] for key in ('status', 'error', 'error_code', 'retryable')],
                         ['error', GENERIC, 'invalid_file', False])
        self.assertIsNotNone(started[0].poll())
        self.assertEqual(self.events, [('document_parser_process', {'stage': 'csv', 'outcome': 'ended', 'reason': 'protocol'})])

    def test_a_reader_ended_from_outside_leaves_the_file_to_retry(self):
        # Task Manager's End task on the busy python.exe, a log-off, an antivirus, the system short of memory.
        marker = self.folder / 'reading'
        started, popen = self.children()
        records = []
        scope = self.store.create_scope()
        document_id = self.store.add(scope, 'log.csv', CSV)['id']
        with patch.object(documents, '_PARSER_BOOT', self.waiting(marker)), popen:
            reading = threading.Thread(target=lambda: records.append(self.store.extract(scope, document_id)))
            reading.start()
            self.wait_for(marker)
            started[0].kill()
            reading.join(20)
        record = records[0]
        self.assertEqual([record[key] for key in ('status', 'error', 'error_code', 'retryable')],
                         ['error', 'Reading this file stopped before it finished. Select Retry review.', 'reading_stopped', True])
        self.assertEqual(self.store.get(scope, document_id)['retryable'], True)
        self.assertEqual([(event, fields['outcome']) for event, fields in self.events], [('document_parser_process', 'ended')])
        # Retry review reads it again.
        self.assertEqual(self.store.extract(scope, document_id)['status'], 'ready')

    def outdated(self):
        """A file indexed by the previous version: the free comparison (check_extraction) is owed."""
        scope = self.store.create_scope()
        document_id = self.store.add(scope, 'log.csv', CSV)['id']
        self.assertEqual(self.store.extract(scope, document_id)['status'], 'ready')
        with self.store._db() as db:
            saved = json.loads(db.execute('SELECT record FROM documents WHERE id=?', (document_id,)).fetchone()[0])
            saved['extraction_version'] = documents.EXTRACTION_VERSION - 1
            db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(saved), document_id))
        self.assertEqual(self.store.get(scope, document_id)['reindex_check'], {'outcome': 'pending'})
        return scope, document_id

    def check_ended_from_outside(self, scope, document_id):
        marker = self.folder / 'reading'
        if marker.exists():
            marker.unlink()
        started, popen = self.children()
        records = []
        with patch.object(documents, '_PARSER_BOOT', self.waiting(marker)), popen:
            reading = threading.Thread(target=lambda: records.append(self.store.check_extraction(scope, document_id)))
            reading.start()
            self.wait_for(marker)
            started[0].kill()
            reading.join(20)
        return records[0]

    def test_a_reader_ended_from_outside_during_the_free_check_leaves_the_check_owed(self):
        # Ending the reader says nothing about the file: no paid re-index is asked for, and the
        # next status poll (DocumentService.list schedules every 'pending' check) compares it again.
        scope, document_id = self.outdated()
        record = self.check_ended_from_outside(scope, document_id)
        self.assertEqual((record['status'], record['reindex_check'], record['extraction_needs_reindex']),
                         ('partial', {'outcome': 'pending'}, True))
        self.assertEqual(self.store.get(scope, document_id)['reindex_check'], {'outcome': 'pending'})
        self.assertEqual([(event, fields['outcome']) for event, fields in self.events], [('document_parser_process', 'ended')])
        record = self.store.check_extraction(scope, document_id)
        self.assertEqual((record['status'], record.get('reindex_check'), record['extraction_needs_reindex']),
                         ('ready', None, False))

    def test_a_free_check_whose_reader_is_ended_again_counts_as_failed_without_looping(self):
        # A reader the system ends every time (short of memory) is not started on every poll.
        scope, document_id = self.outdated()
        self.assertEqual(self.check_ended_from_outside(scope, document_id)['reindex_check'], {'outcome': 'pending'})
        record = self.check_ended_from_outside(scope, document_id)
        self.assertEqual(record['reindex_check'], {'extraction_version': documents.EXTRACTION_VERSION, 'outcome': 'failed'})
        started, popen = self.children()
        with popen:
            self.assertEqual(self.store.check_extraction(scope, document_id)['reindex_check']['outcome'], 'failed')
        self.assertEqual(started, [])


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


class Timing(Fixture):
    def test_the_time_python_takes_to_start_does_not_count_against_the_reading(self):
        # An antivirus scan of python.exe or a cold disk: the reader is ready only after 1.5 s.
        slow_start = 'import time\ntime.sleep(1.5)\n' + documents._PARSER_BOOT
        limits = {**documents.PARSER_SECONDS, 'csv': .5}
        with patch.object(documents, '_PARSER_BOOT', slow_start), patch.object(documents, 'PARSER_SECONDS', limits), \
                patch.object(documents, 'PARSER_MARGIN_SECONDS', .5), \
                patch.object(documents, '_csv', side_effect=AssertionError('read in the server')):
            record = self.extract('log.csv', CSV)[2]
        self.assertEqual((record['status'], record.get('error')), ('ready', None))
        self.assertEqual(self.events, [])

    def test_a_reader_not_ready_in_time_is_ended_and_the_file_read_in_the_server(self):
        never_ready = 'import time\ntime.sleep(30)\n' + documents._PARSER_BOOT
        started, popen = self.children()
        with patch.object(documents, '_PARSER_BOOT', never_ready), patch.object(documents, 'PARSER_START_SECONDS', .5), popen:
            began = time.monotonic()
            record = self.extract('log.csv', CSV)[2]
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual(record['status'], 'ready')
        self.assertEqual(self.events, [('document_parser_process', {'stage': 'csv', 'outcome': 'unavailable',
                                                                    'reason': 'start_time_limit'})])
        self.assertIsNotNone(started[0].poll())
        # The limit for the reading itself is separate and generous.
        self.assertEqual(documents.PARSER_START_SECONDS, 30)

    def test_the_limit_counts_again_from_when_the_readers_own_budget_starts(self):
        # Opening a workbook (its shared strings) or a PDF comes before the reader's own budget starts.
        # It does not use up the margin that lets the reader's own message come first.
        opening = boot('import time\n'
                       'real = module._csv\n'
                       'def opening(*arguments):\n'
                       '    time.sleep(1.5)\n'
                       '    module._budget_started()\n'
                       '    time.sleep(1.5)\n'
                       '    return real(*arguments)\n'
                       'module._csv = opening')
        limits = {**documents.PARSER_SECONDS, 'csv': 2}
        with patch.object(documents, '_PARSER_BOOT', opening), patch.object(documents, 'PARSER_SECONDS', limits), \
                patch.object(documents, 'PARSER_MARGIN_SECONDS', .5), \
                patch.object(documents, '_csv', side_effect=AssertionError('read in the server')):
            record = self.extract('log.csv', CSV)[2]
        self.assertEqual((record['status'], record.get('error')), ('ready', None))
        self.assertEqual(self.events, [])

    def test_the_legacy_workbook_reader_says_when_its_workbook_is_open(self):
        # Opening a large .xls (its shared strings) does not count against its limit either.
        said = []
        xlrd = types.ModuleType('xlrd')
        xlrd.__version__ = '2.0.1'

        class Book:
            nsheets = 0

            def release_resources(self):
                said.append('closed')

        def open_workbook(*arguments, **options):
            said.append('opened')
            return Book()
        xlrd.open_workbook = open_workbook
        path = self.file('ledger.xls', bytes.fromhex('D0CF11E0A1B11AE1') + bytes(504))
        record = {'id': 'doc_' + 'cd' * 12, 'kind': 'xls', 'name': path.name}
        with patch.dict(sys.modules, {'xlrd': xlrd}), \
                patch.object(documents, '_budget_started', side_effect=lambda: said.append('budget')):
            read_here(path, record)
        self.assertEqual(said, ['opened', 'budget', 'closed'])

    @unittest.skipUnless(READERS, 'pypdf, openpyxl and Pillow are not installed')
    def test_the_pdf_and_workbook_readers_say_when_their_own_budget_starts(self):
        record = {'id': 'doc_' + 'ab' * 12, 'kind': 'xlsx', 'name': 'register.xlsx'}
        for path, kind in ((self.file('register.xlsx', workbook_bytes()), 'xlsx'), (AUDIT / 'settlement-intake.pdf', 'pdf')):
            with self.subTest(kind=kind), patch.object(documents, '_budget_started') as started:
                read_here(path, {**record, 'kind': kind, 'name': path.name})
                started.assert_called_once_with()


class Lifetime(Fixture):
    def test_a_reader_ends_when_the_server_process_ends(self):
        # The server is killed (or the desktop window's drain gives up and calls os._exit) while a
        # reader is busy with a file that would keep it busy for a minute.
        marker = self.folder / 'reading'
        server = self.folder / 'server.py'
        server.write_text(
            'import importlib.util, sys, threading\n'
            'from pathlib import Path\n'
            "spec = importlib.util.spec_from_file_location('documents', sys.argv[1])\n"
            'documents = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(documents)\n'
            'documents._PARSER_BOOT = sys.argv[2]\n'
            'real = documents.subprocess.Popen\n'
            'def start(*arguments, **options):\n'
            '    child = real(*arguments, **options)\n'
            '    print(child.pid, flush=True)\n'
            '    return child\n'
            'documents.subprocess.Popen = start\n'
            "documents._parse_apart(Path(sys.argv[3]), {'id': 'doc_' + 'aa' * 12, 'name': 'log.csv', 'kind': 'csv'},\n"
            '                       threading.BoundedSemaphore(1), lambda *_, **__: None)\n', encoding='utf-8')
        host = subprocess.Popen([sys.executable, '-I', '-B', str(server), str(APP / 'documents.py'), self.waiting(marker),
                                 str(self.file('log.csv', CSV))], stdout=subprocess.PIPE)
        self.addCleanup(host.stdout.close)
        reader = int(host.stdout.readline())

        def end_reader():
            if not launcher.exited(reader, .2):
                os.kill(reader, getattr(signal, 'SIGKILL', signal.SIGTERM))  # TerminateProcess on Windows.
        self.addCleanup(end_reader)
        self.wait_for(marker)
        host.kill()
        host.wait()
        # By its process ID: OpenProcess and WaitForSingleObject on Windows, signal 0 elsewhere.
        self.assertTrue(launcher.exited(reader, 10), 'The reader process outlived the server')

    def test_a_reader_still_watches_the_server_when_the_windows_pipe_calls_fail(self):
        # The watch for the server's end is what ends a reader whose server was killed. If the
        # Windows pipe calls failed in a way it did not expect, it waits the portable way instead.
        watcher = self.folder / 'watcher.py'
        watcher.write_text(
            'import importlib.util, os, sys, threading, time, types\n'
            "spec = importlib.util.spec_from_file_location('documents', sys.argv[1])\n"
            'documents = importlib.util.module_from_spec(spec)\n'
            'spec.loader.exec_module(documents)\n'
            "if sys.argv[2] == 'failing':\n"
            "    sys.modules['_winapi'] = sys.modules['msvcrt'] = None  # Importing either now fails.\n"
            "    documents.os = types.SimpleNamespace(name='nt', read=os.read, _exit=os._exit)\n"
            "threading.Thread(target=documents._end_with_server, args=(sys.stdin.fileno(),), daemon=True).start()\n"
            "print('watching', flush=True)\n"
            'time.sleep(60)\n', encoding='utf-8')
        for mode in ('as built', 'failing'):
            with self.subTest(mode=mode):
                child = subprocess.Popen([sys.executable, '-I', '-B', str(watcher), str(APP / 'documents.py'), mode],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                self.addCleanup(child.stdout.close)
                self.addCleanup(lambda child=child: child.poll() is None and child.kill())
                self.assertEqual(child.stdout.readline().strip(), b'watching')
                time.sleep(.2)
                self.assertIsNone(child.poll(), 'The watch ended while the server was still there')
                child.stdin.close()  # The server has ended.
                self.assertEqual(child.wait(10), 1)

    def test_closing_the_store_ends_its_readers_and_leaves_the_file_to_read_again(self):
        marker = self.folder / 'reading'
        started, popen = self.children()
        scope = self.store.create_scope()
        document_id = self.store.add(scope, 'log.csv', CSV)['id']
        raised = []

        def read():
            try:
                self.store.extract(scope, document_id)
            except BaseException as error:
                raised.append(error)
        with patch.object(documents, '_PARSER_BOOT', self.waiting(marker)), popen:
            reading = threading.Thread(target=read)
            reading.start()
            self.wait_for(marker)
            began = time.monotonic()
            self.store.stop_readers()
            self.assertIsNotNone(started[0].poll(), 'stop_readers returned before the reader ended')
            reading.join(10)
            self.assertLess(time.monotonic() - began, 5)
            # Nothing more is read by a closing store, and no process is started for it.
            with self.assertRaises(documents.ReadingStopped):
                self.store.extract(scope, self.store.add(scope, 'other.csv', CSV + b'x;y;z\n')['id'])
        self.assertEqual([type(error) for error in raised], [documents.ReadingStopped])
        self.assertEqual(len(started), 1)
        record = self.store.get(scope, document_id)
        self.assertEqual((record['status'], record.get('error'), record.get('error_code')), ('indexing', None, None))
        self.assertEqual(self.events, [])
        # At the next start the file is read again.
        self.assertEqual(self.open_store('apart', parser_processes=2).extract(scope, document_id)['status'], 'ready')

    def test_the_review_service_ends_running_readers_when_it_closes(self):
        service_spec = importlib.util.spec_from_file_location('parser_process_service', APP / 'document_service.py')
        service = importlib.util.module_from_spec(service_spec)
        service_spec.loader.exec_module(service)
        marker = self.folder / 'reading'
        started, popen = self.children()
        reviews = []
        with patch.object(documents, '_PARSER_BOOT', self.waiting(marker)), popen:
            reviewer = service.DocumentService(self.store, lambda *arguments, **options: reviews.append(arguments), workers=2)
            scope = reviewer.session()['scope']
            document_id = reviewer.upload(scope, 'log.csv', CSV)['id']
            self.wait_for(marker)
            began = time.monotonic()
            reviewer.close()  # What the server does as it closes (InterviewServer.server_close).
            self.assertLess(time.monotonic() - began, 5)
            self.assertIsNotNone(started[0].poll())
            for worker in reviewer._workers:
                worker.join(5)
        record = self.store.get(scope, document_id)
        self.assertEqual((record['status'], record.get('error')), ('indexing', None))
        self.assertFalse((record.get('analysis') or {}).get('error'))
        self.assertEqual(reviews, [])


class SameCode(Fixture):
    def release(self):
        release = self.folder / 'release'
        release.mkdir()
        shutil.copy2(APP / 'documents.py', release / 'documents.py')
        loader = importlib.util.spec_from_file_location('collector_changed_documents', release / 'documents.py')
        copy = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(copy)
        return release / 'documents.py', copy

    def test_a_reader_runs_the_code_the_server_loaded(self):
        source, copy = self.release()
        path = self.file('procedure.csv', CSV)
        record = {'id': 'doc_' + 'ef' * 12, 'name': path.name, 'kind': 'csv'}
        unchanged = copy._parse_apart(path, record, threading.BoundedSemaphore(1),
                                      lambda event, **fields: self.events.append((event, fields)))
        self.assertEqual(exact(unchanged), exact(read_here(path, record)))
        self.assertEqual(self.events, [])
        # A half-finished edit, or a git pull, after the server started.
        text = source.read_text(encoding='utf-8')
        edited = text.replace('def _csv(path, record, chunks):\n', 'def _csv(path, record, chunks):\n    half_finished_edit\n', 1)
        self.assertNotEqual(edited, text)
        source.write_text(edited, encoding='utf-8')
        started, popen = self.children()
        with popen:
            self.assertIsNone(copy._parse_apart(path, record, threading.BoundedSemaphore(1),
                                                lambda event, **fields: self.events.append((event, fields))))
        self.assertEqual(self.events, [('document_parser_process', {'stage': 'csv', 'outcome': 'unavailable',
                                                                    'reason': 'source_changed'})])
        self.assertIsNotNone(started[0].poll(), 'The reader that loaded the edited code was ended')
        # The store reads the file in the server, with the code the server loaded.
        self.events.clear()
        saved = []
        for name, options in (('changed', {'parser_processes': 2}), ('here', {})):
            store = copy.DocumentStore(self.folder / name, **options)
            store.diagnostic = lambda event, **fields: self.events.append((event, fields))
            scope = store.create_scope()
            record = store.extract(scope, store.add(scope, 'procedure.csv', CSV)['id'])
            self.assertEqual((record['status'], record.get('error')), ('ready', None))
            saved.append(json.dumps(store.chunks(scope, record['id'], 0, 500)['chunks'], ensure_ascii=False)
                         .replace(record['id'], 'ID'))
        self.assertEqual(saved[0], saved[1])
        self.assertEqual([fields.get('reason') for event, fields in self.events], ['source_changed'])


class Priority(Fixture):
    def test_a_store_reads_as_many_files_at_once_as_it_is_given_on_any_computer(self):
        # A reader runs below normal priority; fewer slots would only keep files waiting.
        for processors in (1, 2, 4, 16, None):
            with self.subTest(processors=processors), patch.object(documents.os, 'cpu_count', return_value=processors):
                self.assertEqual(self.open_store(f'cpu{processors}', parser_processes=4)._parser_slots._initial_value, 4)
        self.assertIsNone(self.open_store('here')._parser_slots)

    def test_a_small_file_is_not_kept_waiting_behind_large_ones_on_a_two_processor_computer(self):
        # Three large uploads in one interview, then a small CSV in another (a 2-vCPU virtual desktop).
        marks = self.folder / 'marks'
        marks.mkdir()
        large = boot('import time\n'
                     'real = module._csv\n'
                     'def large(path, record, chunks):\n'
                     "    if record['name'].startswith('large'):\n"
                     f'        open({str(marks)!r} + "/" + record["name"], "w").close()\n'
                     '        time.sleep(60)\n'
                     '    return real(path, record, chunks)\n'
                     'module._csv = large')
        with patch.object(documents.os, 'cpu_count', return_value=2):
            store = self.open_store('two', parser_processes=4)
        self.addCleanup(store.stop_readers)
        busy = store.create_scope()
        names = [f'large-{number}.csv' for number in range(3)]
        ids = [store.add(busy, name, CSV + name.encode())['id'] for name in names]
        readings = [threading.Thread(target=self.reading_until_stopped, args=(store, busy, document_id)) for document_id in ids]
        with patch.object(documents, '_PARSER_BOOT', large):
            for reading in readings:
                reading.start()
            for name in names:
                self.wait_for(marks / name)
            began = time.monotonic()
            small = self.extract('small.csv', b'Step;Owner\nIntake;Operations\n', store)[2]
            waited = time.monotonic() - began
            store.stop_readers()
            for reading in readings:
                reading.join(10)
        self.assertEqual(small['status'], 'ready')
        self.assertLess(waited, 15, 'The small file waited for a large one to finish')

    @staticmethod
    def reading_until_stopped(store, scope, document_id):
        try:
            store.extract(scope, document_id)
        except documents.ReadingStopped:
            pass

    @unittest.skipUnless(hasattr(os, 'nice'), 'POSIX priority')
    def test_a_reader_runs_below_normal_priority(self):
        marker = self.folder / 'priority'
        probing = boot('import os\n'
                       'real = module._csv\n'
                       'def probing(*arguments):\n'
                       f'    open({str(marker)!r}, "w").write(str(os.nice(0)))\n'
                       '    return real(*arguments)\n'
                       'module._csv = probing')
        server = os.nice(0)
        if server > 9:
            self.skipTest('This test already runs at the lowest priority')
        with patch.object(documents, '_PARSER_BOOT', probing):
            self.assertEqual(self.extract('log.csv', CSV)[2]['status'], 'ready')
        self.assertEqual(int(marker.read_text()), server + 10)

    def test_on_windows_a_reader_starts_below_normal_priority_without_a_window(self):
        options = []

        def start(*arguments, **given):
            options.append(given)
            raise OSError('not started in this test')
        with patch.object(documents.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
                patch.object(documents.subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0x00004000, create=True), \
                patch.object(documents.subprocess, 'Popen', side_effect=start):
            self.assertEqual(self.extract('log.csv', CSV)[2]['status'], 'ready')
        self.assertEqual(options[0]['creationflags'], 0x08000000 | 0x00004000)


if __name__ == '__main__':
    unittest.main()
