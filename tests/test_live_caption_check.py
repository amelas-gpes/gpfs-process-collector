"""Live voice caption check (LIVE_CAPTION_CHECK): the setting, the worklet file, and the recording route.

The page corrects fund terms and configured names in live captions using the participant's own audio:
it sends each final participant caption's audio, as a 16 kHz 16-bit mono PCM WAV, to /api/transcribe
marked as a caption check (X-Transcription-Purpose), which is hinted with the server's glossary alone and
answered with those terms (web/app.js checkLiveCaption and correctCaption, web/live-voice.js
captionAudio). Dictation and reviewed voice are read as before. Loopback sockets and a stubbed provider.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote
import wave

from test_server import server
from test_rejected_requests import exchange

KEY = "sk-test-caption-check-never-real"
runtime_build = server.local_module("collector_runtime_build", "runtime_build.py")


def page_wav(samples):
    """The file web/live-voice.js writes (function wav): a 44-byte RIFF header, then little-endian samples."""
    data = struct.pack("<%dh" % len(samples), *samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) + b"data" + struct.pack("<I", len(data)) + data)


class Setting(unittest.TestCase):
    def test_on_by_default_and_off_on_request(self):
        self.assertTrue(server.OpenAIClient({"OPENAI_API_KEY": KEY}).live_caption_check)
        for value in ("on", "ON", "1", "true", "yes", " on "):
            self.assertTrue(server.OpenAIClient({"OPENAI_API_KEY": KEY, "LIVE_CAPTION_CHECK": value}).live_caption_check, value)
        for value in ("off", "Off", "0", "false", "no"):
            self.assertFalse(server.OpenAIClient({"OPENAI_API_KEY": KEY, "LIVE_CAPTION_CHECK": value}).live_caption_check, value)
        with self.assertRaises(server.SettingsError):
            server.OpenAIClient({"OPENAI_API_KEY": KEY, "LIVE_CAPTION_CHECK": "of"})

    def test_the_page_is_told_in_live_voice_only(self):
        self.assertIs(server.OpenAIClient({"OPENAI_API_KEY": KEY}).public_config()["live"]["caption_check"], True)
        off = server.OpenAIClient({"OPENAI_API_KEY": KEY, "LIVE_CAPTION_CHECK": "off"}).public_config()
        self.assertIs(off["live"]["caption_check"], False)
        reviewed = server.OpenAIClient({"OPENAI_API_KEY": KEY, "VOICE_MODE": "reviewed"}).public_config()
        self.assertNotIn("caption_check", reviewed["live"])
        # The data notice says the audio of each answer is sent again; off, it is as before. ("Once more" was
        # not true: a check given up when its caption changed, and the padding of a grown caption, resend audio.)
        said = "Each finished answer's audio is also sent again, to correct fund terms and configured names in its caption."
        self.assertIn(said, server.OpenAIClient({"OPENAI_API_KEY": KEY}).public_config()["data_notice"])
        self.assertNotIn(said, off["data_notice"])
        self.assertNotIn(said, reviewed["data_notice"])

    def test_the_setting_is_read_from_env_local_and_the_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / ".env.local").write_text("LIVE_CAPTION_CHECK=off\n", encoding="utf-8")
            with patch.object(server, "APP_DIR", Path(folder)), patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LIVE_CAPTION_CHECK", None)
                self.assertEqual(server.load_settings().get("LIVE_CAPTION_CHECK"), "off")
                os.environ["LIVE_CAPTION_CHECK"] = "on"
                try:
                    self.assertEqual(server.load_settings().get("LIVE_CAPTION_CHECK"), "on")
                finally:
                    os.environ.pop("LIVE_CAPTION_CHECK", None)

    def test_env_example_documents_the_setting(self):
        example = (Path(server.__file__).resolve().parent / ".env.example").read_text(encoding="utf-8")
        self.assertIn("# LIVE_CAPTION_CHECK=on", example)


class WorkletFile(unittest.TestCase):
    def test_the_tap_is_served_from_this_origin_and_counts_towards_the_build(self):
        self.assertEqual(server.STATIC_FILES["/live-voice-tap.js"], ("live-voice-tap.js", "text/javascript; charset=utf-8"))
        self.assertIn("live-voice-tap.js", runtime_build.WEB_FILES)
        source = (server.WEB_DIR / "live-voice-tap.js").read_text(encoding="utf-8")
        self.assertIn('registerProcessor("live-voice-tap"', source)
        page = (server.WEB_DIR / "live-voice.js").read_text(encoding="utf-8")
        self.assertIn('TAP_MODULE = "/live-voice-tap.js"', page)
        self.assertIn('"live-voice-tap"', page)


class RecordingRoute(unittest.TestCase):
    """/api/transcribe accepts the WAV the page writes and sends it on with the hints."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="collector-caption-check-")
        self.addCleanup(self.temporary.cleanup)
        self.client = server.OpenAIClient({"OPENAI_API_KEY": KEY, "TRANSCRIPTION_KEYWORDS": "GPFS"})
        self.client.request = Mock(return_value={"text": "We run the KYC checks before the LPAC meets."})
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=self.client,
                                            documents_root=Path(self.temporary.name) / "documents", knowledge_settings={})
        self.addCleanup(self.httpd.server_close)
        worker = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_port

    def post(self, body, hints, purposes=()):
        marks = "".join(f"X-Transcription-Purpose: {purpose}\r\n" for purpose in purposes)
        head = (f"POST /api/transcribe HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: http://127.0.0.1:{self.port}\r\n"
                f"X-CSRF-Token: {self.httpd.csrf_token}\r\nContent-Type: audio/wav\r\nX-Transcription-Hints: {hints}\r\n"
                f"{marks}Content-Length: {len(body)}\r\n\r\n").encode()
        return exchange(self.port, head, body)

    def keywords(self):
        sent = self.client.request.call_args.args[1]
        return [part.split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0].decode() for part in sent.split(b'name="keywords[]"')[1:]]

    def test_the_page_wav_is_a_16_khz_mono_pcm_file(self):
        audio = page_wav([0, 1000, -1000, 32767, -32768] * 3200)
        with wave.open(io.BytesIO(audio)) as file:
            self.assertEqual((file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getnframes()), (1, 2, 16000, 16000))

    def test_the_route_accepts_it_and_sends_it_with_the_hints(self):
        audio = page_wav([(n * 37) % 2000 - 1000 for n in range(32000)])  # two seconds
        status, _, body, failure = self.post(audio, quote("Capital calls,NAV,GP Fund Solutions"))
        self.assertEqual((status, failure, body), (200, None, {"text": "We run the KYC checks before the LPAC meets."}))
        self.client.request.assert_called_once()
        path, sent, content_type = self.client.request.call_args.args[:3]
        self.assertEqual(path, "audio/transcriptions")
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'filename="answer.wav"\r\nContent-Type: audio/wav\r\n\r\n' + audio + b"\r\n", sent)
        keywords = [part.split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0].decode()
                    for part in sent.split(b'name="keywords[]"')[1:]]
        self.assertEqual(keywords, ["GPFS", "Capital calls", "NAV", "GP Fund Solutions"])

    def test_the_longest_caption_checked_fits_the_recording_limit(self):
        # 150 s of caption, 2 s before and 1 s after (web/live-voice.js TAP_MAX_MS and padding).
        page = (server.WEB_DIR / "live-voice.js").read_text(encoding="utf-8")
        self.assertIn("TAP_BEFORE_MS = 2000, TAP_AFTER_MS = 1000", page)
        self.assertIn("TAP_MAX_MS = 150000", page)
        self.assertLess(44 + (150 + 2 + 1) * 16000 * 2, server.request_body_limit("/api/transcribe"))

    # The glossary of a check with the default fund terms, the process name and the configured "GPFS", and the
    # mishearings SPOKEN_FUND_TERMS lists for them (the only acronyms in a caption a check may replace).
    GLOSSARY = ["KYC", "AML", "ACH", "IRR", "LPAC", "K-1", "NAV", "LPA", "GL", "DPI", "SWIFT", "PEP", "Capital calls", "GPFS"]
    MISHEARD = {"KYC": ["kite"], "IRR": ["DI"], "LPAC": ["CPAC"], "K-1": ["K one"]}

    def test_a_caption_check_is_hinted_with_the_glossary_alone_and_names_it(self):
        audio = page_wav([(n * 37) % 2000 - 1000 for n in range(32000)])
        # Whatever else the page sends, only its first hint (the process name) is used: the others could
        # be a caption's mishearings ("CPAC", "kite") or another check's errors ("HRSWIFT").
        status, _, body, failure = self.post(audio, quote("Capital calls,CPAC,kite,HRSWIFT"), ["live-caption-check"])
        self.assertEqual((status, failure), (200, None), body)
        self.assertEqual(self.keywords(), self.GLOSSARY)
        self.assertEqual(body, {"text": "We run the KYC checks before the LPAC meets.", "terms": self.GLOSSARY, "misheard": self.MISHEARD})
        sent = self.client.request.call_args.args[1]
        self.assertIn(b'filename="answer.wav"\r\nContent-Type: audio/wav\r\n\r\n' + audio + b"\r\n", sent)
        self.assertNotIn(b"CPAC", sent)
        self.assertNotIn(b"HRSWIFT", sent)
        # Without a process name (or with one that is not a short plain term) the glossary is the rest.
        status, _, body, _ = self.post(audio, "", ["live-caption-check"])
        self.assertEqual((status, body["terms"]), (200, [term for term in self.GLOSSARY if term != "Capital calls"]))
        self.assertEqual(self.keywords(), body["terms"])

    def test_dictation_and_reviewed_voice_are_read_as_before(self):
        audio = page_wav([(n * 37) % 2000 - 1000 for n in range(32000)])
        status, _, body, failure = self.post(audio, quote("Capital calls,CPAC,NAV"))
        self.assertEqual((status, failure, body), (200, None, {"text": "We run the KYC checks before the LPAC meets."}))
        self.assertEqual(self.keywords(), ["GPFS", "Capital calls", "CPAC", "NAV"], "The page's hints, as always")
        # The same request as before the check existed, byte for byte (the random boundary aside).
        with patch.object(server.secrets, "token_hex", return_value="0" * 32):
            self.client.request.reset_mock()
            self.post(audio, quote("Capital calls,CPAC,NAV"))
            routed = self.client.request.call_args.args[1]
            self.client.request.reset_mock()
            self.client.transcribe(audio, "audio/wav", ["Capital calls", "CPAC", "NAV"])
            self.assertEqual(routed, self.client.request.call_args.args[1])

    def test_the_mark_is_read_strictly(self):
        audio = page_wav([0] * 16000)
        for purposes in (["Live-Caption-Check"], ["live-caption-check2"], ["dictation"], [""], ["live-caption-check", "live-caption-check"]):
            self.client.request.reset_mock()
            status, _, body, failure = self.post(audio, quote("Capital calls"), purposes)
            self.assertEqual((status, failure), (400, None), purposes)
            self.assertIn("Refresh the page", body["error"])
            self.client.request.assert_not_called()

    def test_the_mark_is_refused_where_live_captions_are_not_checked(self):
        audio = page_wav([0] * 16000)
        for settings in ({"LIVE_CAPTION_CHECK": "off"}, {"VOICE_MODE": "reviewed"}):
            self.httpd.client = server.OpenAIClient({"OPENAI_API_KEY": KEY, "TRANSCRIPTION_KEYWORDS": "GPFS", **settings})
            self.httpd.client.request = Mock(return_value={"text": "We run the KYC checks."})
            status, _, body, _ = self.post(audio, "", ["live-caption-check"])
            self.assertEqual(status, 400, settings)
            self.httpd.client.request.assert_not_called()
            # Dictation itself goes on as before.
            status, _, body, _ = self.post(audio, quote("NAV"))
            self.assertEqual((status, body), (200, {"text": "We run the KYC checks."}))


class Glossary(unittest.TestCase):
    """The terms of a check: term_glossary's (fund terms, the process name, configured keywords), no more than are sent."""

    def test_the_fund_terms_come_first_and_the_list_fits_the_keywords(self):
        many = [f"System {number}" for number in range(30)]
        terms = server.caption_check_terms(many, ["Capital calls"])
        self.assertEqual(terms[:13], [*server.SPOKEN_FUND_TERMS, "Capital calls"])
        self.assertLessEqual(len(terms), server.MAX_TRANSCRIPTION_KEYWORDS)
        self.assertEqual(server.caption_check_terms((), []), list(server.SPOKEN_FUND_TERMS))
        # A name that is not a short plain term is left out, as in the live glossary.
        self.assertEqual(server.caption_check_terms((), ["<b>Calls</b>"]), list(server.SPOKEN_FUND_TERMS))
        # No term taken from what was misheard: the aliases are never terms.
        self.assertNotIn("CPAC", terms)
        self.assertNotIn("kite", terms)

    def test_as_many_configured_keywords_as_the_count_allows(self):
        # Only the count limits a check, as it limits dictation: not the size of the live glossary's
        # instructions. With 45-character names only 14 of them fitted that size.
        for size in (8, 45, 100):
            many = [f"System {number:02d} " + "x" * (size - 10) for number in range(30)]
            terms = server.caption_check_terms(many, ["Capital calls"])
            self.assertEqual(terms, [*server.SPOKEN_FUND_TERMS, "Capital calls", *many[:17]], size)
            self.assertEqual(server.caption_check_terms(many, []), [*server.SPOKEN_FUND_TERMS, *many[:18]], size)
        # The live glossary itself is as it was.
        long = [f"System {number:02d} " + "x" * 35 for number in range(30)]
        glossary = server.term_glossary(long, {"process_name": "Capital calls"})
        self.assertLessEqual(len(json.dumps(glossary, ensure_ascii=False)), 900)
        self.assertEqual(glossary["terms"][:13], [*server.SPOKEN_FUND_TERMS, "Capital calls"])
        self.assertEqual(glossary["often_misheard_as"], {"KYC": ["kite"], "IRR": ["DI"], "LPAC": ["CPAC"], "K-1": ["K one"]})

    def test_the_misheard_forms_are_named_for_the_terms_sent(self):
        self.assertEqual(server.caption_check_misheard(server.caption_check_terms((), [])),
                         {"KYC": ["kite"], "IRR": ["DI"], "LPAC": ["CPAC"], "K-1": ["K one"]})
        self.assertEqual(server.caption_check_misheard(["KYC", "NAV"]), {"KYC": ["kite"]})
        self.assertEqual(server.caption_check_misheard([]), {})

    def test_the_mark_itself(self):
        self.assertIsNone(server.transcription_purpose(None))
        self.assertIsNone(server.transcription_purpose([]))
        self.assertEqual(server.transcription_purpose(["live-caption-check"]), "live-caption-check")
        for values in (["live-caption-check "], ["LIVE-CAPTION-CHECK"], ["x"], ["live-caption-check"] * 2):
            with self.assertRaises(ValueError):
                server.transcription_purpose(values)


class Trace(unittest.TestCase):
    """The page traces each check's outcome with counts and no text (web/app.js traceCaptionCheck)."""

    def test_the_metadata_trace_keeps_the_names_of_the_counts(self):
        path = Path(__file__).resolve().parents[1] / "raw_trace.py"
        spec = importlib.util.spec_from_file_location("caption_check_trace_under_test", path)
        raw_trace = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(raw_trace)
        payloads = [
            {"caption_id": "live_1_user_3", "turn_id": "t012", "outcome": "sent", "audio_ms": 4100, "bytes": 131244},
            {"caption_id": "live_1_user_3", "turn_id": "t012", "outcome": "replaced", "words_before": 12, "words_after": 14,
             "count": 2, "chars_before": 60, "chars_after": 58},
            {"caption_id": "live_1_user_3", "turn_id": "t012", "outcome": "kept", "reason": "no_correction", "words_before": 12, "words_after": 9},
            {"caption_id": "live_1_user_3", "turn_id": "t012", "outcome": "kept", "reason": "misaligned", "words_before": 12, "words_after": 30},
            {"count": 2},
        ]
        for payload in payloads:
            recorded = raw_trace._Snapshot(False, ()).copy(payload)
            self.assertFalse([key for key in recorded if key.startswith("_trace_field")], recorded)
            # The turn identifies the check's caption (one turn each); the counts and the outcome are kept as sent.
            self.assertEqual(recorded.get("turn_id"), "t012" if "turn_id" in payload else None)
            for key, value in payload.items():
                if key != "caption_id":
                    self.assertEqual(recorded[key], value, key)


if __name__ == "__main__":
    unittest.main()
