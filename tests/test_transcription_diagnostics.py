"""Provider HTTP success and accepted speech are separate diagnostic events."""
import unittest
from test_server import server


class TranscriptionDiagnostics(unittest.TestCase):
    def client(self, response):
        events = []
        client = server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-not-a-key'},
            diagnostic_callback=lambda event, **fields: events.append((event, fields)))
        client.request = lambda *args, **kwargs: response
        return client, events

    def test_empty_provider_result_is_rejected_without_audio_or_text_logging(self):
        client, events = self.client({'text': ' '})
        with self.assertRaisesRegex(server.APIError, 'No speech'):
            client.transcribe(b'x' * 200, 'audio/webm')
        self.assertEqual(events, [('transcription_result', {'stage': 'transcription',
            'outcome': 'rejected', 'error_category': 'no_speech'})])

    def test_recognized_result_is_accepted_without_logging_testimony(self):
        client, events = self.client({'text': 'A private answer'})
        self.assertEqual(client.transcribe(b'x' * 200, 'audio/webm'), {'text': 'A private answer'})
        self.assertEqual(events[0][1]['outcome'], 'accepted')
        self.assertNotIn('private', str(events))

    def test_diagnostic_failure_does_not_break_recognized_speech(self):
        client, _ = self.client({'text': 'Recognized'})
        def fail(*args, **kwargs):
            raise OSError('test log failure')
        client.diagnostic_callback = fail
        self.assertEqual(client.transcribe(b'x' * 200, 'audio/webm')['text'], 'Recognized')
