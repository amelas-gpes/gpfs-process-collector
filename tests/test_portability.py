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
from unittest.mock import MagicMock, patch


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

    def test_launcher_reports_when_shutdown_does_not_complete(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(sys, "argv", ["launcher.py", "--stop"]), \
             patch.object(launcher, "config", return_value={"csrf_token": "synthetic"}), \
             patch.object(launcher, "build_opener", return_value=opener), \
             patch.object(launcher.time, "sleep"):
            with self.assertRaisesRegex(SystemExit, "still responding"):
                launcher.main()

    def test_failed_startup_terminates_only_the_child_this_launcher_created(self):
        work = self.app / "work"
        child = MagicMock()
        child.poll.return_value = None
        with patch.object(sys, "argv", ["launcher.py", "--no-browser"]), \
             patch.object(launcher, "WORK_DIR", work), \
             patch.object(launcher, "config", return_value=None), \
             patch.object(launcher.subprocess, "Popen", return_value=child), \
             patch.object(launcher.time, "sleep"):
            with self.assertRaisesRegex(SystemExit, "Could not start"):
                launcher.main()
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=3)
        child.kill.assert_not_called()

    def test_failed_startup_kills_the_owned_child_if_graceful_termination_times_out(self):
        child = MagicMock()
        child.poll.return_value = None
        child.wait.side_effect = [launcher.subprocess.TimeoutExpired("synthetic-child", 3), 0]
        with patch.object(sys, "argv", ["launcher.py", "--no-browser"]), \
             patch.object(launcher, "WORK_DIR", self.app / "work"), \
             patch.object(launcher, "config", return_value=None), \
             patch.object(launcher.subprocess, "Popen", return_value=child), \
             patch.object(launcher.time, "sleep"):
            with self.assertRaisesRegex(SystemExit, "Could not start"):
                launcher.main()
        child.terminate.assert_called_once_with()
        child.kill.assert_called_once_with()
        self.assertEqual(child.wait.call_count, 2)

    def test_build_identity_ignores_private_data_and_changes_with_public_source(self):
        identity=launcher._build_module.build_id
        (self.app/'web').mkdir();source=self.app/'web'/'app.js';source.write_text('public source')
        initial=identity(self.app)
        (self.app/'.env.local').write_text('private-settings-sentinel')
        (self.app/'work').mkdir();(self.app/'work'/'session.json').write_text('private-session-sentinel')
        self.assertEqual(identity(self.app),initial)
        source.write_text('updated public source');self.assertNotEqual(identity(self.app),initial)

    def test_launcher_refuses_to_reuse_older_backend_without_stopping_it(self):
        for current in ({'app_id':'voice-interviewer','version':'0.11.0'},
                        {'app_id':'voice-interviewer','version':'0.11.0','build_id':'old-source'}):
            with self.subTest(current=current),patch.object(sys,'argv',['launcher.py','--no-browser']), \
                 patch.object(launcher,'config',return_value=current), \
                 patch.object(launcher._build_module,'build_id',return_value='new-source'), \
                 patch.object(launcher.subprocess,'Popen') as spawn,patch.object(launcher,'build_opener') as network:
                with self.assertRaisesRegex(SystemExit,'older app build'):
                    launcher.main()
                spawn.assert_not_called();network.assert_not_called()

    def test_launcher_reuses_identical_build_without_starting_another_server(self):
        with patch.object(sys,'argv',['launcher.py','--no-browser']), \
             patch.object(launcher,'config',return_value={'app_id':'voice-interviewer','build_id':'same-source'}), \
             patch.object(launcher._build_module,'build_id',return_value='same-source'), \
             patch.object(launcher.subprocess,'Popen') as spawn:
            launcher.main();spawn.assert_not_called()

    def test_startup_does_not_accept_another_stale_server_on_the_port(self):
        child=MagicMock();child.poll.return_value=None
        replies=[None]+[{'app_id':'voice-interviewer','build_id':'other-source'}]*40
        with patch.object(sys,'argv',['launcher.py','--no-browser']),patch.object(launcher,'WORK_DIR',self.app/'work'), \
             patch.object(launcher,'config',side_effect=replies),patch.object(launcher._build_module,'build_id',return_value='new-source'), \
             patch.object(launcher.subprocess,'Popen',return_value=child),patch.object(launcher.time,'sleep'):
            with self.assertRaisesRegex(SystemExit,'Could not start'):launcher.main()
        child.terminate.assert_called_once_with()

    def test_launcher_rejects_unreachable_or_invalid_ports_before_starting(self):
        for port in ("0", "-1", "65536"):
            with self.subTest(port=port), \
                 patch.object(sys, "argv", ["launcher.py", "--port", port]), \
                 patch.object(launcher, "config") as config:
                with self.assertRaises(SystemExit):
                    launcher.main()
                config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
