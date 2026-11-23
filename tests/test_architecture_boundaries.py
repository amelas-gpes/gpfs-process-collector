"""Executable dependency and release identity rules for the desktop application."""
import ast
import unittest
from pathlib import Path

from test_server import server


ROOT = Path(server.__file__).resolve().parent


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split(".")[0]


class ArchitectureBoundaries(unittest.TestCase):
    def test_interview_rules_do_not_depend_on_io_adapters(self):
        rules = ("interview_stop", "gpfs_interview", "interview_coverage", "capture_facts", "draft_audit", "provider_schema")
        adapters = {"server", "openai_transport", "recovery_store", "knowledge_graph", "documents",
                    "document_service", "collector_settings", "sqlite3", "http", "urllib", "socket", "subprocess"}
        for name in rules:
            with self.subTest(module=name):
                tree = ast.parse((ROOT / (name + ".py")).read_text(encoding="utf-8"))
                self.assertEqual(set(imports(tree)) & adapters, set())

    def test_every_module_the_server_loads_by_filename_changes_the_build_identity(self):
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
        modules = {node.args[1].value for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == "local_module"
                   and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)}
        included = {path.relative_to(ROOT).as_posix() for path in server.runtime_build.source_files(ROOT)}
        self.assertTrue(modules)
        self.assertEqual(modules - included, set())
