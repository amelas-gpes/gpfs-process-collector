"""Live voice caption check (LIVE_CAPTION_CHECK): the setting, the worklet file, and the recording route.

The page has each final participant caption transcribed again from the participant's own microphone
audio, as a 16 kHz 16-bit mono PCM WAV, through /api/transcribe with the dictation hints
(web/app.js checkLiveCaption, web/live-voice.js captionAudio). Loopback sockets and a stubbed provider.
"""
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
        # The data notice says the audio of each answer is sent once more; off, it is as before.
        said = "Each finished answer's audio is also sent once more for transcription with spelling hints."
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

    def post(self, body, hints):
        head = (f"POST /api/transcribe HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: http://127.0.0.1:{self.port}\r\n"
                f"X-CSRF-Token: {self.httpd.csrf_token}\r\nContent-Type: audio/wav\r\nX-Transcription-Hints: {hints}\r\n"
                f"Content-Length: {len(body)}\r\n\r\n").encode()
        return exchange(self.port, head, body)

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
        # 150 s of caption, 0.4 s before and 0.6 s after (web/live-voice.js TAP_MAX_MS and padding).
        self.assertLess(44 + (150 + 1) * 16000 * 2, server.request_body_limit("/api/transcribe"))


if __name__ == "__main__":
    unittest.main()
