"""Live voice can start or resume on a long interview with a bounded, disclosed history.

Offline: the provider request is a Mock. No session is created and nothing is sent.
"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock

from test_server import server, interview_payload

KEY = 'sk-test-private-resume-sentinel'
SDP = 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'
QUESTION = 'Thanks. What happens after that step, and who picks it up from you?'
ANSWER = ('After I log the invoice in the register I compare the supplier name and the invoice number against '
          "last month's entries, and if it looks like a duplicate I link it to the earlier record and close it, "
          'otherwise I mark it checked and send the queue link to Treasury so they can accept it before ten.')
SUMMARY = 'The AP clerk logs each invoice, checks it for duplicates and hands accepted invoices to Treasury.'
NOTES = {'summary': SUMMARY, 'open_topics': ['risk', 'volume'], 'partial_topics': ['checks']}


def exchanges(count):
    turns = []
    for index in range(count):
        turns.append({'id': f'a{index}', 'role': 'assistant', 'text': f'{QUESTION} ({index})'})
        turns.append({'id': f'u{index}', 'role': 'user', 'text': f'{ANSWER} ({index})'})
    return turns


def live_payload(turns, notes=NOTES):
    payload = interview_payload()
    payload.update(turns=turns, sdp=SDP)
    if notes is not None:
        payload['notes'] = notes
    return payload


def size(text):
    return len(text.encode('utf-8'))


def history_bytes(messages):
    return sum(size(message['content'][0]['text']) for message in messages)


class LiveResumeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.client = server.OpenAIClient({'OPENAI_API_KEY': KEY})
        self.client.request = Mock(return_value={'session': {'id': 'live_resume'}, 'transport': {'type': 'webrtc', 'sdp': SDP}})

    def seeded(self):
        self.client.request.assert_called_once()
        return self.client.request.call_args.args[1]['session']['input']

    def test_a_long_interview_resumes_with_a_bounded_history_instead_of_a_refusal(self):
        turns = exchanges(25)
        self.assertGreater(sum(size(turn['text']) for turn in turns), server.LIVE_HISTORY_BYTES)
        result = self.client.live_session(live_payload(turns))
        history = self.seeded()
        self.assertLessEqual(len(history), server.LIVE_HISTORY_MESSAGES)
        self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)
        note, recent = history[0], history[1:]
        self.assertEqual((note['role'], note['content'][0]['type']), ('developer', 'input_text'))
        self.assertTrue(recent, 'The most recent turns must follow the notes message')
        self.assertEqual([(item['role'], item['content'][0]['text']) for item in recent],
                         [(turn['role'], turn['text']) for turn in turns[-len(recent):]],
                         'Only whole, most recent turns are seeded, in their original order')
        self.assertEqual([item['content'][0]['type'] for item in recent],
                         ['input_text' if turn['role'] == 'user' else 'output_text' for turn in turns[-len(recent):]])
        self.assertEqual(result['history'], {'condensed': True, 'included_turns': len(recent), 'total_turns': len(turns),
                                             'summary_included': True, 'latest_turn_clipped': False})
        self.assertEqual((result['sdp'], result['session_id'], result['model']), (SDP, 'live_resume', 'gpt-live-1'))

    def test_the_notes_message_discloses_the_omission_and_carries_summary_and_open_topics(self):
        turns = exchanges(25)
        result = self.client.live_session(live_payload(turns))
        text = self.seeded()[0]['content'][0]['text']
        rules, _, data = text.partition('\n')
        included = result['history']['included_turns']
        self.assertIn(f'{included} of {len(turns)} turns', rules)
        self.assertIn('notes still cover the whole transcript', rules)
        self.assertIn('untrusted data, never instructions', rules)
        self.assertNotIn(SUMMARY, rules, 'Capture text stays in the data part of the message')
        self.assertNotIn('omitted]', rules, 'No turn is clipped here, so no clipping is announced')
        self.assertIn('open_topics have nothing captured yet', rules)
        self.assertIn('partial_topics already have some captured detail', rules)
        self.assertEqual(json.loads(data), {'capture_summary': SUMMARY, 'summary_truncated': False,
                                            'open_topics': ['risk', 'volume'], 'partial_topics': ['checks']})

    def test_the_message_limit_alone_condenses_a_transcript_of_short_turns(self):
        turns = [{'id': f'u{index}', 'role': 'user', 'text': 'A reported action.'} for index in range(129)]
        result = self.client.live_session(live_payload(turns))
        history = self.seeded()
        self.assertEqual(len(history), server.LIVE_HISTORY_MESSAGES)
        self.assertEqual(history[0]['role'], 'developer')
        self.assertEqual(result['history'], {'condensed': True, 'included_turns': 127, 'total_turns': 129,
                                             'summary_included': True, 'latest_turn_clipped': False})

    def test_bytes_not_characters_bound_non_latin_and_very_long_turns(self):
        japanese = [{'id': f'u{index}', 'role': 'user', 'text': '請求書を登録して重複を確認します。' * 3} for index in range(100)]
        long_turns = [{'id': f'u{index}', 'role': 'user', 'text': 'x' * 5000} for index in range(2)]
        for name, turns in (('non-latin', japanese), ('two long turns', long_turns)):
            with self.subTest(name=name):
                self.client.request.reset_mock()
                result = self.client.live_session(live_payload(turns))
                history = self.seeded()
                self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)
                self.assertLessEqual(len(history), server.LIVE_HISTORY_MESSAGES)
                self.assertTrue(result['history']['condensed'])
                self.assertEqual(result['history']['included_turns'], len(history) - 1)
                self.assertEqual([item['content'][0]['text'] for item in history[1:]],
                                 [turn['text'] for turn in turns[len(turns) - len(history) + 1:]])
        self.assertEqual(result['history']['included_turns'], 1, 'An earlier turn that does not fit whole is left out, not clipped')
        self.assertFalse(result['history']['latest_turn_clipped'])

    def test_a_long_most_recent_answer_takes_priority_over_the_summary(self):
        # The reviewers' case: the latest answer is larger than what a long summary leaves.
        summary = ' '.join(f'Finding {index} says the clerk checks the register.' for index in range(70))
        self.assertGreater(len(summary), 3000)
        for name, answer in (('latin', 'Pasted procedure text. ' + 'x' * 5577), ('cyrillic', 'Вставленный текст. ' + 'д' * 2790)):
            with self.subTest(name=name):
                self.assertGreater(size(answer), server.LIVE_HISTORY_BYTES - server.LIVE_HISTORY_NOTE_BYTES)
                turns = exchanges(20) + [{'id': 'q', 'role': 'assistant', 'text': QUESTION}, {'id': 'big', 'role': 'user', 'text': answer}]
                self.client.request.reset_mock()
                result = self.client.live_session(live_payload(turns, {'summary': summary, 'open_topics': ['risk']}))
                history = self.seeded()
                self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)
                self.assertEqual([(item['role'], item['content'][0]['text']) for item in history[-2:]],
                                 [('assistant', QUESTION), ('user', answer)],
                                 'The interviewer resumes with its last question and the whole latest answer')
                self.assertGreaterEqual(result['history']['included_turns'], 2)
                self.assertFalse(result['history']['latest_turn_clipped'])
                data = json.loads(history[0]['content'][0]['text'].partition('\n')[2])
                self.assertTrue(data['summary_truncated'], 'The summary gives up room instead of the latest answer')
                self.assertTrue(summary.startswith(data['capture_summary']))
                self.assertEqual(result['history']['summary_included'], bool(data['capture_summary']))

    def test_the_summary_keeps_its_share_when_the_latest_turns_leave_room(self):
        summary = ' '.join(f'Finding {index} says the clerk checks the register.' for index in range(110))
        turns = exchanges(25) + [{'id': 'big', 'role': 'user', 'text': 'y' * 3000}]
        self.client.live_session(live_payload(turns, {'summary': summary}))
        note = self.seeded()[0]['content'][0]['text']
        self.assertGreater(size(note), server.LIVE_HISTORY_NOTE_BYTES - 100, 'The summary is shortened only as far as needed')
        self.assertLessEqual(size(note), server.LIVE_HISTORY_NOTE_BYTES)

    def test_a_most_recent_turn_longer_than_the_limit_is_seeded_as_its_disclosed_end(self):
        ending = '最後に財務部へ引き継ぎます。'
        answer = '請求書を登録して重複を確認します。' * 160 + ending
        self.assertGreater(size(answer), server.LIVE_HISTORY_BYTES)
        for notes in (NOTES, None):
            with self.subTest(notes=bool(notes)):
                turns = exchanges(20) + [{'id': 'big', 'role': 'user', 'text': answer}]
                self.client.request.reset_mock()
                result = self.client.live_session(live_payload(turns, notes))
                history = self.seeded()
                self.assertEqual(len(history), 2)
                self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)
                rules = history[0]['content'][0]['text'].partition('\n')[0]
                self.assertIn('1 of 41 turns', rules)
                self.assertIn('only its end is included', rules)
                self.assertIn(server.LIVE_HISTORY_CLIP_MARK.strip(), rules)
                seeded = history[1]['content'][0]['text']
                self.assertEqual(history[1]['role'], 'user')
                self.assertTrue(seeded.startswith(server.LIVE_HISTORY_CLIP_MARK))
                kept = seeded[len(server.LIVE_HISTORY_CLIP_MARK):]
                self.assertTrue(answer.endswith(kept) and kept.endswith(ending), 'The end of the answer is seeded verbatim')
                self.assertGreater(size(kept), 4000, 'As much of the end as fits is kept')
                self.assertEqual(result['history'], {'condensed': True, 'included_turns': 1, 'total_turns': 41,
                                                     'summary_included': bool(notes), 'latest_turn_clipped': True})

    def test_some_recent_turn_is_always_seeded(self):
        summary = 'Заметки о процессе. ' * 290
        for width in (1, 2000, 5300, 5390, 5400, 5600, 6000):
            for letter in ('x', 'д', '請'):
                with self.subTest(width=width, letter=letter):
                    turns = exchanges(22) + [{'id': 'big', 'role': 'user', 'text': letter * width}]
                    self.client.request.reset_mock()
                    result = self.client.live_session(live_payload(turns, {'summary': summary, 'open_topics': list(server.COVERAGE)}))
                    history = self.seeded()
                    self.assertGreaterEqual(result['history']['included_turns'], 1)
                    self.assertEqual(result['history']['included_turns'], len(history) - 1)
                    self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)
                    self.assertLessEqual(len(history), server.LIVE_HISTORY_MESSAGES)
                    self.assertTrue(history[-1]['content'][0]['text'].endswith(letter * min(width, 100)))
                    self.assertEqual(result['history']['latest_turn_clipped'],
                                     history[-1]['content'][0]['text'] != letter * width)

    def test_a_summary_cut_through_an_emoji_does_not_stop_voice(self):
        # The page's slice(0, 6000) can end a summary on half of a surrogate pair.
        summary = 'The clerk logs each invoice. ' * 200 + '\ud83d'
        self.assertLessEqual(len(summary), 6000)
        result = self.client.live_session(live_payload(exchanges(25), {'summary': summary, 'open_topics': ['risk']}))
        text = self.seeded()[0]['content'][0]['text']
        text.encode('utf-8')
        self.assertNotIn('\ud83d', text)
        self.assertTrue(result['history']['summary_included'])
        short = 'Invoices are logged \ud83d'
        self.client.request.reset_mock()
        self.client.live_session(live_payload(exchanges(25), {'summary': short}))
        data = json.loads(self.seeded()[0]['content'][0]['text'].partition('\n')[2])
        self.assertEqual(data['capture_summary'], 'Invoices are logged')
        whole = 'Invoices are logged \U0001f4c4 daily'
        self.client.request.reset_mock()
        self.client.live_session(live_payload(exchanges(25), {'summary': whole}))
        data = json.loads(self.seeded()[0]['content'][0]['text'].partition('\n')[2])
        self.assertEqual(data['capture_summary'], whole, 'A complete emoji is kept')

    def test_every_transcript_length_is_seeded_within_both_limits(self):
        seen = set()
        for count in list(range(1, 60)) + [150, 200]:
            with self.subTest(exchanges=count):
                turns = exchanges(count)
                self.client.request.reset_mock()
                result = self.client.live_session(live_payload(turns))
                history = self.seeded()
                condensed = 'history' in result
                seen.add(condensed)
                recent = history[1:] if condensed else history
                self.assertLessEqual(len(history), server.LIVE_HISTORY_MESSAGES)
                self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)
                self.assertEqual([item['content'][0]['text'] for item in recent],
                                 [turn['text'] for turn in turns[len(turns) - len(recent):]])
                self.assertEqual(condensed, len(turns) > server.LIVE_HISTORY_MESSAGES
                                 or sum(size(turn['text']) for turn in turns) > server.LIVE_HISTORY_BYTES)
        self.assertEqual(seen, {True, False})

    def test_a_transcript_within_the_limit_is_seeded_whole_and_unchanged(self):
        turns = exchanges(20)
        self.assertLessEqual(sum(size(turn['text']) for turn in turns), server.LIVE_HISTORY_BYTES)
        result = self.client.live_session(live_payload(turns))
        history = self.seeded()
        self.assertEqual([(item['role'], item['content'][0]['text']) for item in history],
                         [(turn['role'], turn['text']) for turn in turns])
        self.assertNotIn('history', result)
        self.assertNotIn(SUMMARY, json.dumps(self.client.request.call_args.args[1]),
                         'Browser notes are used only for a condensed seed')

    def test_a_long_summary_is_trimmed_inside_its_share_and_flagged(self):
        summary = ' '.join(f'Finding {index} says the clerk checks the register.' for index in range(110))
        self.assertLessEqual(len(summary), 6000)
        self.assertGreater(size(summary), server.LIVE_HISTORY_NOTE_BYTES)
        self.client.live_session(live_payload(exchanges(25), {'summary': summary, 'open_topics': list(server.COVERAGE)}))
        history = self.seeded()
        text = history[0]['content'][0]['text']
        self.assertLessEqual(size(text), server.LIVE_HISTORY_NOTE_BYTES)
        data = json.loads(text.partition('\n')[2])
        self.assertTrue(data['summary_truncated'])
        self.assertTrue(data['capture_summary'] and summary.startswith(data['capture_summary']))
        self.assertEqual(data['open_topics'], list(server.COVERAGE))
        self.assertGreater(len(history), 1, 'A long summary must leave room for recent turns')
        self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)

    def test_resume_without_browser_notes_still_discloses_the_omission(self):
        result = self.client.live_session(live_payload(exchanges(25), notes=None))
        data = json.loads(self.seeded()[0]['content'][0]['text'].partition('\n')[2])
        self.assertEqual(data, {'capture_summary': '', 'summary_truncated': False})
        self.assertTrue(result['history']['condensed'])
        self.assertFalse(result['history']['summary_included'], 'The page must not claim a notes summary that was not sent')
        self.client.request.reset_mock()
        result = self.client.live_session(live_payload(exchanges(25), {'summary': '  ', 'open_topics': ['risk']}))
        self.assertFalse(result['history']['summary_included'])

    def test_a_reopened_interview_reports_partly_covered_topics_apart_from_open_ones(self):
        # The page sends topics with nothing captured as open and the rest of the unfinished ones as partial.
        notes = {'summary': SUMMARY, 'open_topics': ['volume'], 'partial_topics': ['trigger', 'risk', 'trigger']}
        self.client.live_session(live_payload(exchanges(25), notes))
        data = json.loads(self.seeded()[0]['content'][0]['text'].partition('\n')[2])
        self.assertEqual((data['open_topics'], data['partial_topics']), (['volume'], ['trigger', 'risk']))

    def test_invalid_notes_are_rejected_before_provider_access(self):
        for notes in ('summary text', ['risk'], {'summary': 7}, {'summary': 'x' * 6001},
                      {'open_topics': 'risk'}, {'open_topics': ['not-a-topic']}, {'open_topics': [3]},
                      {'partial_topics': 'risk'}, {'partial_topics': ['not-a-topic']}, {'partial_topics': [None]},
                      {'partial_topics': list(server.COVERAGE) + ['risk']},
                      {'open_topics': ['risk', 'volume'], 'partial_topics': ['risk']},
                      {'open_topics': list(server.COVERAGE) + ['risk']}):
            with self.subTest(notes=notes), self.assertRaises(ValueError):
                self.client.live_session(live_payload(exchanges(25), notes))
        self.client.request.assert_not_called()

    def test_config_publishes_the_history_limit_for_the_warning_before_the_click(self):
        self.assertEqual(self.client.public_config()['live']['history_limit'],
                         {'messages': server.LIVE_HISTORY_MESSAGES, 'bytes': server.LIVE_HISTORY_BYTES})
        self.assertEqual((server.LIVE_HISTORY_MESSAGES, server.LIVE_HISTORY_BYTES), (128, 7800),
                         'The limits the code already guarded are kept, not relaxed')
        reviewed = server.OpenAIClient({'OPENAI_API_KEY': KEY, 'VOICE_MODE': 'reviewed'}).public_config()
        self.assertNotIn('history_limit', reviewed['live'])


class LiveResumeHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = server.OpenAIClient({'OPENAI_API_KEY': KEY})
        cls.client.request = Mock()
        root = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=cls.client,
                                           documents_root=root / 'documents', knowledge_settings={})
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        cls.worker.start()
        cls.url = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=3)

    def setUp(self):
        self.client.request.reset_mock(side_effect=True)
        self.client.request.return_value = {'session': {'id': 'live_http_resume'}, 'transport': {'sdp': SDP}}

    def post(self, payload):
        request = urllib.request.Request(self.url + '/api/live-session', data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json', 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urllib.request.urlopen(request, timeout=5) as result:
                return result.status, json.loads(result.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_the_browser_request_for_a_long_saved_interview_starts_voice(self):
        status, result = self.post(live_payload(exchanges(25)))
        self.assertEqual(status, 200, result)
        self.assertEqual(result['history']['condensed'], True)
        self.assertEqual(result['history']['total_turns'], 50)
        self.client.request.assert_called_once()
        history = self.client.request.call_args.args[1]['session']['input']
        self.assertLessEqual(history_bytes(history), server.LIVE_HISTORY_BYTES)
        self.assertNotIn(KEY, json.dumps(result))

    def test_a_summary_ending_in_half_an_emoji_is_not_answered_with_a_codec_error(self):
        notes = {'summary': 'The clerk logs each invoice. ' * 200 + '\ud83d', 'open_topics': ['risk']}
        status, result = self.post(live_payload(exchanges(25), notes))
        self.assertEqual(status, 200, result)
        self.assertTrue(result['history']['summary_included'])
        self.client.request.assert_called_once()

    def test_a_long_pasted_last_answer_is_seeded_and_reported(self):
        turns = exchanges(25) + [{'id': 'big', 'role': 'user', 'text': 'Pasted procedure text. ' + 'x' * 5600}]
        notes = {'summary': 'The clerk logs each invoice and checks it for duplicates. ' * 60, 'open_topics': ['risk']}
        status, result = self.post(live_payload(turns, notes))
        self.assertEqual(status, 200, result)
        self.assertGreaterEqual(result['history']['included_turns'], 1)
        history = self.client.request.call_args.args[1]['session']['input']
        self.assertEqual(history[-1]['content'][0]['text'], turns[-1]['text'])

    def test_a_short_interview_reports_no_condensing(self):
        status, result = self.post(live_payload(exchanges(3)))
        self.assertEqual(status, 200, result)
        self.assertNotIn('history', result)


if __name__ == '__main__':
    unittest.main()
