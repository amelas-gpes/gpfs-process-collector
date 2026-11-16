"""Submit accepts what the Review editor accepts, and a refusal names the field (ui-flows-review-admin-2).

The editor allows 6,000 characters for a step's Input and Output and for each Inputs / Outputs line;
the store refused anything above 1,000 with 'Invalid text field.' and reported more than 400 turns as a
missing participant statement. Temporary SQLite and the real route; no analyzer, provider or network.
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_server import server
from test_knowledge_graph import kg, payload

LONG = ('Supplier invoice with remittance advice and purchase order. ' * 30).strip()  # About 1,770 characters.


def account(**step):
    body = payload('Invoice intake', 'A supplier email starts a case.')
    body['draft']['steps'][0].update(step)
    return body


class FieldLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def entities(self):
        return self.graph.admin_snapshot()['entities']

    def refused(self, body, message):
        with self.assertRaises(ValueError) as caught:
            self.graph.submit(body)
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(self.graph.admin_snapshot()['submissions'], [], 'A refused submission stores nothing')

    def test_step_input_and_output_up_to_the_editor_limit_are_accepted(self):
        self.assertGreater(len(LONG), 1000)
        for value in (LONG, 'x' * 6000):
            with self.subTest(length=len(value)):
                receipt = self.graph.submit(account(input=value, output=value + ' Registered.' if len(value) < 5000 else 'Registered case'))
                self.assertEqual(receipt['status'], 'pending')
        stored = [e for e in self.entities() if e['type'] == 'business_object' and e['data'].get('full_label')]
        self.assertTrue(stored)
        for entity in stored:
            self.assertLessEqual(len(entity['label']), 1000, 'Lists and the graph show a bounded label')
            self.assertTrue(entity['label'].endswith('…'))
            self.assertTrue(entity['data']['full_label'].startswith(entity['label'][:-1]), 'The whole text is kept with the entity')
        self.assertIn(LONG, {e['data']['full_label'] for e in stored})

    def test_inputs_and_outputs_lines_up_to_the_editor_limit_are_accepted(self):
        body = account()
        body['draft']['inputs'] = ['Approved NAV', LONG]
        body['draft']['outputs'] = [LONG + ' Sent.']
        self.graph.submit(body)
        objects = [e for e in self.entities() if e['type'] == 'business_object']
        self.assertEqual(sorted(len(e['data'].get('full_label', '')) for e in objects), [0, len(LONG), len(LONG) + 6])

    def test_a_short_label_is_stored_as_before(self):
        self.graph.submit(account(input='y' * 1000))
        entity = next(e for e in self.entities() if e['label'].startswith('yyy'))
        self.assertEqual((len(entity['label']), entity['data']), (1000, {}))

    def test_long_values_that_differ_after_the_shown_part_stay_two_objects_and_equal_ones_are_one(self):
        body = account(input=LONG + ' A', output=LONG + ' B')
        body['draft']['steps'][1].update(input=(LONG + ' a').upper())
        self.graph.submit(body)
        long_objects = [e for e in self.entities() if e['data'].get('full_label')]
        self.assertEqual(len(long_objects), 2)

    def test_a_refusal_names_the_step_the_field_and_the_limit(self):
        cases = ((account(input='x' * 6001), 'Step s1: Input is longer than 6,000 characters.'),
                 (account(output='x' * 6001), 'Step s1: Output is longer than 6,000 characters.'),
                 (account(actor='x' * 1001), 'Step s1: Owner / role is longer than 1,000 characters.'),
                 (account(system='x' * 1001), 'Step s1: System / tool is longer than 1,000 characters.'),
                 (account(title='x' * 1001), 'Step s1: Title is longer than 1,000 characters.'))
        for body, message in cases:
            with self.subTest(message=message):
                self.refused(body, message)
        body = account()
        body['draft']['inputs'] = ['Approved NAV', 'Second', 'x' * 6001]
        self.refused(body, 'Inputs, line 3, is longer than 6,000 characters.')
        body = account()
        body['draft']['outputs'] = ['x' * 6001]
        self.refused(body, 'Outputs, line 1, is longer than 6,000 characters.')
        body = account()
        body['draft']['steps'][1]['id'] = 'x' * 81
        self.refused(body, 'A step ID is longer than 80 characters.')

    def test_submission_fields_and_turns_are_named_too(self):
        for field, name in (('participant', 'Participant'), ('team', 'Team'), ('department', 'Department'), ('scope', 'Business scope')):
            with self.subTest(field=field):
                self.refused({**account(), field: 'x' * 501}, f'{name} is longer than 500 characters.')
        body = account()
        body['turns'].append({'id': 'u2', 'role': 'user', 'text': 'x' * 6001})
        self.refused(body, 'Transcript turn u2 is longer than 6,000 characters.')
        body = account()
        body['turns'].append({'id': 'a1', 'role': 'assistant', 'text': None})
        self.refused(body, 'Transcript turn a1 must be text.')

    def test_too_many_turns_is_its_own_message(self):
        body = account()
        body['turns'] = [{'id': f'u{n}', 'role': 'user', 'text': 'An answer.'} for n in range(401)]
        for step in body['draft']['steps'] + body['draft']['connections']:
            step['evidence_turns'] = ['u1']
        self.refused(body, 'A submission holds at most 400 transcript turns; this interview has 401.')
        body['turns'] = body['turns'][:400]
        self.assertEqual(self.graph.submit(body)['revision'], 1)
        # The other half of the old combined check keeps its own message.
        empty = account()
        empty['turns'] = []
        empty['draft'] = None
        with self.assertRaisesRegex(ValueError, 'requires a participant statement or verified document evidence'):
            self.graph.submit(empty)


class FieldLimitRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.httpd = server.InterviewServer(('127.0.0.1', 0), server.Handler, client=server.OpenAIClient({}),
                                            documents_root=Path(self.temp.name) / 'documents', knowledge_root=Path(self.temp.name) / 'graph')
        self.worker = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def submit(self, body):
        request = Request(f'http://127.0.0.1:{self.httpd.server_port}/api/knowledge/submit', data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'X-CSRF-Token': self.httpd.csrf_token})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_the_dialog_receives_the_named_refusal_and_a_1200_character_input_is_filed(self):
        # The audit's case: 1,200 characters in "Input for step S1" answered 400 'Invalid text field.'
        status, receipt = self.submit(account(input='i' * 1200))
        self.assertEqual((status, receipt['revision']), (202, 1))
        status, refusal = self.submit(account(input='i' * 6001))
        self.assertEqual((status, refusal['error']), (400, 'Step s1: Input is longer than 6,000 characters.'))


if __name__ == '__main__':
    unittest.main()
