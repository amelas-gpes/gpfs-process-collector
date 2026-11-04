"""Spelling hints do not add another model call or mutate returned testimony."""
import unittest
from unittest.mock import Mock
from test_server import server


class TranscriptionContextTests(unittest.TestCase):
    def client(self, **settings):
        client = server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-only', **settings})
        client.request = Mock(return_value={'text': 'Andrea reviews it.'})
        return client

    def test_known_transcription_model_gets_bounded_spelling_hints_in_multipart(self):
        client = self.client()
        self.assertEqual(client.transcribe(b'synthetic-audio' * 12, 'audio/wav'), {'text': 'Andrea reviews it.'})
        self.assertEqual(client.request.call_count, 1)
        path, body, media_type = client.request.call_args.args
        self.assertEqual(path, 'audio/transcriptions')
        self.assertIn(b'name="keywords[]"\r\n\r\nEntrilia\r\n', body)
        self.assertIn(b'name="prompt"', body)
        self.assertIn(b'transcribe only what is spoken', body)
        self.assertIn(b'synthetic-audio', body)

    def test_empty_configuration_disables_hints(self):
        client = self.client(TRANSCRIPTION_KEYWORDS='')
        client.transcribe(b'x' * 200, 'audio/wav')
        self.assertNotIn(b'keywords', client.request.call_args.args[1])
        self.assertNotIn(b'name="prompt"', client.request.call_args.args[1])

    def test_other_model_contract_is_not_given_unsupported_keyword_fields(self):
        client = self.client(TRANSCRIPTION_MODEL='other-compatible-transcriber')
        client.transcribe(b'x' * 200, 'audio/wav')
        self.assertNotIn(b'keywords', client.request.call_args.args[1])

    def test_keyword_configuration_is_validated_without_provider_work(self):
        for value in ('unsafe\r\nheader', 'bad<term>', 'x' * 101, ','.join(str(n) for n in range(31)), [], 'x' * 2001):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                self.client(TRANSCRIPTION_KEYWORDS=value)

    def test_hints_are_distinct_trimmed_and_not_part_of_recorded_answer(self):
        client = self.client(TRANSCRIPTION_KEYWORDS=' Entrilia,Entrilia, Allvue ')
        self.assertEqual(client.transcription_keywords, ['Entrilia', 'Allvue'])
        self.assertEqual(client.transcribe(b'x' * 200, 'audio/wav')['text'], 'Andrea reviews it.')


if __name__ == '__main__': unittest.main()
