"""Release-provided PDF reading works in isolated Python without installed packages."""
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PDFReaderDelivery(unittest.TestCase):
    def isolated(self, body):
        setup = """
            import hashlib, importlib.util, sys, tempfile
            from pathlib import Path
            root = Path(sys.argv[1])
            spec = importlib.util.spec_from_file_location("documents", root / "documents.py")
            documents = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(documents)
        """
        run = subprocess.run([sys.executable, "-I", "-B", "-S", "-c",
                              textwrap.dedent(setup) + textwrap.dedent(body), str(ROOT)],
                             capture_output=True, text=True, timeout=90)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_verified_reader_opens_a_file_and_exports_a_page_without_site_packages(self):
        self.isolated("""
            assert 'pdf' not in documents.unavailable_readers()
            with tempfile.TemporaryDirectory() as work:
                store = documents.DocumentStore(work, parser_processes=1)
                try:
                    scope = store.create_scope()
                    data = (root / 'tests/fixtures/document-audit/settlement-intake.pdf').read_bytes()
                    record = store.add(scope, 'intake.pdf', data)
                    result = store.extract(scope, record['id'])
                    assert result['status'] in ('ready', 'partial'), result.get('error')
                    store.page_input(scope, record['id'], 1)
                    reader = sys.modules['pypdf']
                    assert reader.__version__ == '6.21.4'
                    assert str(root / 'vendor') in reader.__file__
                finally:
                    store.stop_readers()
        """)

    def test_already_loaded_other_version_keeps_its_namespace_while_an_isolated_reader_handles_pdfs(self):
        self.isolated("""
            from types import ModuleType
            existing = ModuleType('pypdf')
            existing.__version__ = '6.10.0'
            sys.modules['pypdf'] = existing
            assert 'pdf' not in documents.unavailable_readers()
            with tempfile.TemporaryDirectory() as work:
                store = documents.DocumentStore(work)
                try:
                    scope = store.create_scope()
                    data = (root / 'tests/fixtures/document-audit/settlement-intake.pdf').read_bytes()
                    record = store.add(scope, 'intake.pdf', data)
                    result = store.extract(scope, record['id'])
                    assert result['status'] in ('ready', 'partial'), result.get('error')
                    assert store.page_input(scope, record['id'], 1).startswith(b'%PDF')
                    assert sys.modules['pypdf'] is existing
                finally:
                    store.stop_readers()
        """)

    def test_unverified_wheel_is_refused_before_import(self):
        self.isolated("""
            with tempfile.TemporaryDirectory() as work:
                altered = Path(work) / 'pypdf-6.21.4-py3-none-any.whl'
                altered.write_bytes(b'wrong contents')
                documents.PDF_WHEEL = altered
                assert 'pdf' in documents.unavailable_readers()
                assert str(altered) not in sys.path
                assert 'pypdf' not in sys.modules
        """)
