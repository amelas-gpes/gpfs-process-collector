"""Offline regressions for repository-local configuration and runtime output.

Only temporary fake settings are read. These tests never inspect a developer's
real environment file, contact a provider, or start the application server.
"""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server = load_module("portable_collector_server", "server.py")
launcher = load_module("portable_collector_launcher", "launcher.py")


class RepositoryPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-portability-")
        self.addCleanup(self.temporary.cleanup)
        self.ancestor = Path(self.temporary.name)
        self.app = self.ancestor / "unrelated-parent" / "cloned-repository"
        self.app.mkdir(parents=True)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app_patch = patch.object(server, "APP_DIR", self.app)
        self.app_patch.start()
        self.addCleanup(self.app_patch.stop)

    def test_unrelated_ancestor_settings_are_not_loaded(self):
        (self.ancestor / ".env.local").write_text(
            "OPENAI_API_KEY=ancestor-fake-sentinel\nINTERVIEW_MODEL=ancestor-model\n",
            encoding="utf-8",
        )
        (self.app.parent / ".env.local").write_text(
            "OPENAI_API_KEY=parent-fake-sentinel\n", encoding="utf-8"
        )

        self.assertEqual(server.load_settings(), {})

    def test_own_settings_are_read_without_accepting_unrelated_variables(self):
        (self.app / ".env.local").write_text(
            "# Synthetic settings, not a real API credential.\n"
            "export OPENAI_API_KEY='repository-fake-sentinel'\n"
            'INTERVIEW_MODEL="fixture-interview-model"\n'
            "TRANSCRIPTION_MODEL=fixture-transcription-model\n"
            "UNRELATED_SETTING=must-not-be-imported\n",
            encoding="utf-8",
        )

        self.assertEqual(
            server.load_settings(),
            {
                "OPENAI_API_KEY": "repository-fake-sentinel",
                "INTERVIEW_MODEL": "fixture-interview-model",
                "TRANSCRIPTION_MODEL": "fixture-transcription-model",
            },
        )
        self.assertNotIn("UNRELATED_SETTING", os.environ)

    def test_process_environment_overrides_repository_settings_without_rewriting_file(self):
        settings_file = self.app / ".env.local"
        settings_text = (
            "OPENAI_API_KEY=repository-fake-sentinel\n"
            "INTERVIEW_MODEL=repository-model\n"
            "TRANSCRIPTION_MODEL=repository-transcription\n"
        )
        settings_file.write_text(settings_text, encoding="utf-8")
        overrides = {
            "OPENAI_API_KEY": "process-fake-sentinel",
            "INTERVIEW_MODEL": "process-model",
            "TRANSCRIPTION_MODEL": "process-transcription",
        }

        with patch.dict(os.environ, overrides):
            self.assertEqual(server.load_settings(), overrides)

        self.assertEqual(settings_file.read_text(encoding="utf-8"), settings_text)

    def test_launcher_runtime_output_directory_stays_inside_repository(self):
        app_dir = launcher.APP_DIR.resolve()
        work_dir = launcher.WORK_DIR.resolve()

        self.assertTrue(work_dir.is_relative_to(app_dir))
        self.assertNotEqual(work_dir, app_dir)
        self.assertEqual(work_dir.parent, app_dir)


if __name__ == "__main__":
    unittest.main()
