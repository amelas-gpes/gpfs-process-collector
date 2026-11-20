"""A settings file that Windows tools saved in another encoding, and what the user is told.

Windows PowerShell 5.1 writes UTF-16 with a byte-order mark for `"KEY=value" > .env.local`
and Out-File; Notepad's ANSI writes one byte per accented letter. Only temporary files with
fictional values are read; no provider is contacted and no server is started.
"""
import importlib.util
import io
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


server = load_module("settings_encoding_collector_server", "server.py")
launcher = load_module("settings_encoding_collector_launcher", "launcher.py")

LINES = ("# Synthetic settings, not a real API credential.\r\n"
         "OPENAI_API_KEY=fictional-sentinel-value\r\n"
         "INTERVIEW_MODEL=fixture-interview-model\r\n")
EXPECTED = {"OPENAI_API_KEY": "fictional-sentinel-value", "INTERVIEW_MODEL": "fixture-interview-model"}


class SettingsFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-settings-")
        self.addCleanup(self.temporary.cleanup)
        self.app = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def load(self, raw):
        (self.app / ".env.local").write_bytes(raw)
        with patch.object(server, "APP_DIR", self.app):
            return server.load_settings()

    def refusal(self, raw):
        with self.assertRaises(server.SettingsError) as refused:
            self.load(raw)
        return refused.exception


class SettingsEncodingTests(SettingsFileTests):
    def test_utf8_with_and_without_a_byte_order_mark_is_read_as_before(self):
        for name, raw in (("plain", LINES.encode("utf-8")), ("with a mark", LINES.encode("utf-8-sig")),
                          ("line feeds only", LINES.replace("\r\n", "\n").encode("utf-8")),
                          ("accented comment", ("# clé de test\n" + LINES).encode("utf-8")),
                          ("empty", b"")):
            with self.subTest(file=name):
                self.assertEqual(self.load(raw), EXPECTED if raw else {})

    def test_utf16_with_a_byte_order_mark_is_read(self):
        # What `"OPENAI_API_KEY=..." > .env.local` writes in Windows PowerShell 5.1.
        for name, raw in (("little endian", b"\xff\xfe" + LINES.encode("utf-16-le")),
                          ("big endian", b"\xfe\xff" + LINES.encode("utf-16-be")),
                          ("accented comment", b"\xff\xfe" + ("# clé de test\r\n" + LINES).encode("utf-16-le"))):
            with self.subTest(file=name):
                self.assertEqual(self.load(raw), EXPECTED)

    def test_utf16_without_a_byte_order_mark_is_read_instead_of_silently_ignored(self):
        for name, raw in (("little endian", LINES.encode("utf-16-le")), ("big endian", LINES.encode("utf-16-be")),
                          ("one line, no line break", "OPENAI_API_KEY=fictional-sentinel-value".encode("utf-16-le"))):
            with self.subTest(file=name):
                self.assertEqual(self.load(raw)["OPENAI_API_KEY"], "fictional-sentinel-value")

    def test_an_ansi_file_with_an_accented_letter_is_refused_by_name(self):
        for name, raw in (("comment", ("# clé de test\r\n" + LINES).encode("cp1252")),
                          ("value", "INTERVIEW_MODEL=modèle\r\n".encode("cp1252")),
                          ("euro sign", "# 5 €\r\nOPENAI_API_KEY=fictional-sentinel-value\r\n".encode("cp1252"))):
            with self.subTest(where=name):
                error = self.refusal(raw)
                self.assertIn(".env.local", str(error))
                self.assertIn("UTF-8", str(error))
                self.assertNotIn("fictional-sentinel-value", str(error))
                self.assertNotIn("codec", str(error))

    def test_a_damaged_utf16_file_is_refused_by_name(self):
        error = self.refusal(b"\xff\xfe" + LINES.encode("utf-16-le") + b"\x00\xd8")  # an unpaired surrogate
        self.assertIn(".env.local", str(error))
        self.assertIn("UTF-8", str(error))

    def test_the_refusal_is_a_value_error_and_never_quotes_the_file(self):
        error = self.refusal(b"OPENAI_API_KEY=fictional-sentinel-\xe9\r\n")
        self.assertIsInstance(error, ValueError)
        self.assertNotIsInstance(error, UnicodeError)
        self.assertIsNone(error.__cause__)
        self.assertNotIn("fictional", str(error))

    def test_a_settings_file_that_cannot_be_opened_is_named_too(self):
        (self.app / ".env.local").write_bytes(LINES.encode("utf-8"))
        with patch.object(server, "APP_DIR", self.app), \
             patch.object(Path, "read_bytes", side_effect=PermissionError("synthetic")):
            with self.assertRaises(server.SettingsError) as refused:
                server.load_settings()
        self.assertIn(".env.local", str(refused.exception))
        self.assertNotIn("synthetic", str(refused.exception))


class EmptySpellingHintsTests(SettingsFileTests):
    """README and .env.example: an empty TRANSCRIPTION_KEYWORDS lists no names; leaving it out uses the built-in four."""
    BUILT_IN = ["GPFS", "GP Fund Solutions", "Entrilia", "Allvue"]

    def keywords(self, raw, **environment):
        with patch.dict(os.environ, environment):
            settings = self.load(raw)
        return server.OpenAIClient({**settings, "OPENAI_API_KEY": "fictional-sentinel-value"}).transcription_keywords

    def test_an_empty_list_lists_no_names_and_the_fund_terms_stay(self):
        for name, line in (("bare", b"TRANSCRIPTION_KEYWORDS=\n"), ("spaces", b"TRANSCRIPTION_KEYWORDS=   \n"),
                           ("quoted", b'TRANSCRIPTION_KEYWORDS=""\n'), ("quoted, then a comment", b'TRANSCRIPTION_KEYWORDS="" # none\n'),
                           ("one comma", b"TRANSCRIPTION_KEYWORDS=,\n")):
            with self.subTest(line=name):
                self.assertEqual(self.keywords(LINES.encode() + line), [])
        with self.subTest("an empty environment variable"):
            self.assertEqual(self.keywords(LINES.encode() + b"TRANSCRIPTION_KEYWORDS=Investran\n", TRANSCRIPTION_KEYWORDS=""), [])
        # Live voice still has the fund terms, and only them.
        terms = server.caption_check_terms(self.keywords(LINES.encode() + b"TRANSCRIPTION_KEYWORDS=\n"), [])
        self.assertEqual(terms, list(server.SPOKEN_FUND_TERMS)[:server.MAX_TRANSCRIPTION_KEYWORDS])
        self.assertFalse({"GP Fund Solutions", "Entrilia", "Allvue"} & set(terms))

    def test_a_setting_left_out_uses_the_built_in_names(self):
        self.assertEqual(self.keywords(LINES.encode()), self.BUILT_IN)
        self.assertEqual(self.keywords(LINES.encode() + b"# TRANSCRIPTION_KEYWORDS=\n"), self.BUILT_IN)
        self.assertEqual(self.keywords(LINES.encode() + b"TRANSCRIPTION_KEYWORDS=Investran\n"), ["Investran"])
        # Other settings left empty are still missing ones, as before.
        self.assertNotIn("INTERVIEW_MODEL", self.load(b"INTERVIEW_MODEL=\n"))
        with patch.dict(os.environ, {"INTERVIEW_MODEL": ""}):
            self.assertNotIn("INTERVIEW_MODEL", self.load(b""))


class ServerStartMessageTests(SettingsFileTests):
    def start(self, **patches):
        output = io.StringIO()
        with patch.object(sys, "argv", ["server.py", "--port", "8791"]), patch.object(sys, "stdout", output), \
             patch.multiple(server, **patches):
            with self.assertRaises(SystemExit) as stopped:
                server.main()
        return str(stopped.exception.code)

    def test_an_unreadable_settings_file_stops_the_server_with_its_reason_in_one_line(self):
        def construct(*_):
            # What InterviewServer does first: read the settings of its own folder.
            return self.load(("# clé de test\r\n" + LINES).encode("cp1252"))
        message = self.start(InterviewServer=construct)
        self.assertIn(".env.local", message)
        self.assertIn("UTF-8", message)
        self.assertNotIn("busy", message)
        self.assertNotIn("\n", message)

    def test_too_many_spelling_hints_stop_the_server_with_their_reason(self):
        hints = ",".join(f"Name{index}" for index in range(31))
        message = self.start(load_settings=lambda: {"TRANSCRIPTION_KEYWORDS": hints})
        self.assertIn("at most 30 short transcription spelling hints", message)
        self.assertNotIn("busy", message)
        self.assertNotIn("Name30", message)

    def test_a_busy_port_is_still_reported_as_a_busy_port(self):
        message = self.start(InterviewServer=MagicMock(side_effect=server.PortUnavailable(10048, "synthetic address in use")))
        self.assertIn("Port 8791 is busy", message)

    def test_an_error_this_application_did_not_word_keeps_its_traceback(self):
        def unexpected(*_):
            return int("not a number")  # a library's ValueError, not a settings problem
        with patch.object(sys, "argv", ["server.py", "--port", "8791"]), \
             patch.object(server, "InterviewServer", side_effect=unexpected):
            with self.assertRaises(ValueError):
                server.main()


class LauncherStartFailureTests(SettingsFileTests):
    def launch(self, child_output, exit_code, previous=b"Traceback of an earlier attempt\nOSError: older failure\n"):
        work = self.app / "work"
        work.mkdir()
        log = work / "voice-interviewer-server.log"
        log.write_bytes(previous)
        child = MagicMock()

        def spawn(*_, stdout, **__):
            stdout.write(child_output)
            stdout.flush()
            return child
        child.poll.return_value = exit_code
        with patch.object(sys, "argv", ["launcher.py", "--no-browser", "--port", "8792"]), \
             patch.object(launcher, "WORK_DIR", work), patch.object(launcher, "config", return_value=None), \
             patch.object(launcher.subprocess, "Popen", side_effect=spawn), patch.object(launcher.time, "sleep"):
            with self.assertRaises(SystemExit) as stopped:
                launcher.main()
        return str(stopped.exception.code), child, log

    def test_the_launcher_reports_what_the_server_said_instead_of_a_busy_port(self):
        said = b"AI Process Collector could not start: .env.local must be saved as UTF-8.\r\n"
        message, child, log = self.launch(said, 1)
        self.assertIn("Could not start", message)
        self.assertIn("exit code 1", message)
        self.assertIn(".env.local must be saved as UTF-8", message)
        self.assertNotIn("may be busy", message)
        self.assertNotIn("older failure", message, "Only what this attempt wrote is shown")
        self.assertIn(str(log), message)
        child.terminate.assert_not_called()

    def test_a_busy_port_is_reported_in_the_servers_own_words(self):
        message, _, _ = self.launch(b"Port 8792 is busy. Stop the existing prototype or choose another --port.\n", 1)
        self.assertIn("Port 8792 is busy", message)
        self.assertNotIn("may be busy", message)

    def test_a_long_traceback_is_shortened_to_its_last_lines(self):
        lines = [f"  File \"module{index}.py\", line {index}".encode() for index in range(200)]
        message, _, _ = self.launch(b"\n".join([b"Traceback (most recent call last):", *lines, b"RuntimeError: last line"]), 1)
        self.assertIn("RuntimeError: last line", message)
        self.assertNotIn("module0.py", message)
        self.assertLess(len(message), 5000)

    def test_a_server_that_never_answers_is_stopped_and_described_as_that(self):
        message, child, log = self.launch(b"", None)
        self.assertIn("Could not start", message)
        self.assertIn("did not answer", message)
        self.assertNotIn("exit code", message)
        self.assertNotIn("may be busy", message)
        self.assertIn(str(log), message)
        child.terminate.assert_called_once_with()

    def test_text_that_is_not_utf8_in_the_log_cannot_break_the_report(self):
        message, _, _ = self.launch(b"caf\xe9 failure\n", 3)
        self.assertIn("exit code 3", message)
        self.assertIn("failure", message)


if __name__ == "__main__":
    unittest.main()
