"""Offline regression cases for the route review (audit finding live-workflow-accuracy-2).

A handoff the participant stated outright is published when the reviewer quotes it, even if the
reviewer quotes only the decisive answer, adds a further answer, or changes typography. A reviewer
whose passages cannot be verified is asked once more for those routes. Everything else stays an
open question, exactly as before. These tests never send model requests.
"""
import copy
import http.client
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from test_server import server, interview_payload, process_draft, fixture_draft_audit
from test_interview_orchestrator import SyntheticTeamProvider


DECISIVE = 'If the appliance is outside the warranty period, the claim is simply closed as rejected.'
T004 = ('Then the question is whether the appliance is still inside the two-year warranty period. '
        'If it is outside, I send the customer a rejection letter and the claim is closed as rejected.')
T012 = "Please remove the rejection letter step, because we don't send letters any more. " + DECISIVE
ROUTE = {'from': 'S3', 'to': 'S4', 'label': 'Outside warranty period', 'evidence_turns': ['t004', 't012']}
GAP = 'handoff or prerequisite'
# Typography a reviewer may substitute. Named so that no invisible character hides in this file.
NO_BREAK_SPACE, EN_DASH = chr(0x00A0), chr(0x2013)
OPEN_QUOTE, CLOSE_QUOTE = chr(0x201C), chr(0x201D)
CURLY_APOSTROPHE_QUOTE = 'because we don' + chr(0x2019) + 't send letters any more'


def turns():
    return [
        {'id': 'a1', 'role': 'assistant', 'text': 'What happens once the purchase date is known?'},
        {'id': 't004', 'role': 'user', 'text': T004},
        {'id': 't006', 'role': 'user', 'text': 'If it is inside the warranty period, I fill in a repair authorisation form.'},
        {'id': 'a2', 'role': 'assistant', 'text': 'Is there anything you would like to correct?'},
        {'id': 't012', 'role': 'user', 'text': T012},
    ]


def step(step_id, title, kind='activity', sources=('t004',)):
    return {'id': step_id, 'title': title, 'type': kind, 'actor': 'Claims handler', 'system': 'UNKNOWN',
            'description': title, 'input': 'UNKNOWN', 'output': 'UNKNOWN', 'completion_criteria': 'UNKNOWN',
            'handoff': 'UNKNOWN', 'evidence_turns': list(sources)}


STEPS = [step('S3', 'Is the appliance within warranty?', 'decision'),
         step('S5', 'Fill in repair authorisation', sources=('t006',)),
         step('S4', 'Close claim as rejected', sources=('t004', 't012'))]
INSIDE = {'from': 'S3', 'to': 'S5', 'label': 'Inside warranty period', 'evidence_turns': ['t006']}


def review(passages, route=ROUTE):
    return {'from': route['from'], 'to': route['to'], 'label': route['label'], 'passages': passages}


def quote(source, text):
    return {'source_id': source, 'quote': text}


def ground(passages, route=ROUTE, **options):
    return server.grounded_routes([route], [review(passages, route)], STEPS, {}, turns(), [], **options)


def workflow_payload():
    findings = [{'key': key, 'status': 'unknown', 'answer': 'UNKNOWN', 'evidence_turns': []} for key in server.COVERAGE]
    return {
        'context': {'process_name': 'Warranty claims', 'process_owner': '', 'objective': '', 'background': ''},
        'turns': turns(),
        'previous_capture': {
            'workflow': {'title': 'Warranty claims', 'steps': copy.deepcopy(STEPS[:2]),
                         'connections': [copy.deepcopy(INSIDE)], 'open_questions': []},
            'memo_findings': findings, 'summary': 'A claims handler described warranty claims.',
            'focus': 'Outcome outside the warranty period', 'parking_lot': [],
        },
    }


def candidate_update(**overrides):
    result = {'title': 'Warranty claims', 'upsert_steps': [copy.deepcopy(STEPS[2])], 'remove_steps': [],
              'upsert_connections': [copy.deepcopy(ROUTE)], 'remove_connections': [], 'open_questions': [],
              'memo_findings': [], 'summary': 'Claims outside the warranty period are closed as rejected.',
              'focus': 'Outcome outside the warranty period', 'parking_lot': []}
    result.update(overrides)
    return result


def workflow_audit(passages, **overrides):
    result = {'title': 'Warranty claims', 'summary': 'Claims outside the warranty period are closed as rejected.',
              'focus': 'Outcome outside the warranty period', 'open_questions': [], 'parking_lot': [],
              'route_support': [review(passages)], 'remove_connections': [], 'discard_step_upserts': [],
              'discard_connection_upserts': [], 'discard_step_removals': [], 'discard_connection_removals': [],
              'upsert_steps': [], 'upsert_connections': [], 'memo_findings': []}
    result.update(overrides)
    return result


def workflow_client(*replies):
    client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-route-grounding'})
    client.structured = Mock(side_effect=list(replies))
    return client


def published(result):
    return next((edge for edge in result['connections'] if server.route_key(edge) == server.route_key(ROUTE)), None)


class StubRecheck:
    """Stands in for the second review: records what was asked and what was logged."""

    def __init__(self, rows=None):
        self.rows, self.asked, self.records = rows, [], []

    def ask(self, routes):
        self.asked.append(copy.deepcopy(routes))
        return self.rows

    def record(self, reason, outcome):
        self.records.append((reason, outcome))


RESTATED = 'Yes, once it is outside warranty we close it as rejected, no letter.'


def restated_turns():
    """The same interview after the participant repeated the route in a later answer."""
    return turns() + [{'id': 'a3', 'role': 'assistant', 'text': 'Is there anything else?'},
                      {'id': 't014', 'role': 'user', 'text': RESTATED}]


class Clock:
    """Stands in for time.monotonic: it moves only when a scripted request says how long it took."""

    def __init__(self):
        self.now = 50000.0

    def __call__(self):
        return self.now

    def spend(self, seconds):
        self.now += seconds


def timed_replies(clock, *calls):
    """A structured() double: each (seconds, reply) pair takes that long on the clock."""
    queue = list(calls)

    def structured(*args, **kwargs):
        seconds, reply = queue.pop(0)
        clock.spend(seconds)
        return copy.deepcopy(reply)
    return Mock(side_effect=structured)


class RouteQuotationTests(unittest.TestCase):
    """The gate itself: which reviewer passages establish a route."""

    def test_a_quote_from_every_cited_answer_publishes_the_route_unchanged(self):
        accepted, gaps = ground([quote('t004', 'whether the appliance is still inside the two-year warranty period'),
                                 quote('t012', DECISIVE)])
        self.assertEqual(accepted, [ROUTE])
        self.assertEqual(gaps, [])

    def test_the_decisive_answer_alone_publishes_the_route_with_its_citations_narrowed(self):
        accepted, gaps = ground([quote('t012', DECISIVE)])
        self.assertEqual(accepted, [{**ROUTE, 'evidence_turns': ['t012']}])
        self.assertEqual(gaps, [])
        self.assertEqual(ROUTE['evidence_turns'], ['t004', 't012'], 'The proposal itself is never mutated')

    def test_an_extra_verbatim_participant_answer_does_not_cost_the_route(self):
        accepted, gaps = ground([quote('t004', 'the claim is closed as rejected'), quote('t012', DECISIVE),
                                 quote('t006', 'I fill in a repair authorisation form')])
        self.assertEqual(accepted, [ROUTE])
        self.assertEqual(gaps, [])
        accepted, gaps = ground([quote('t012', DECISIVE), quote('t006', 'I fill in a repair authorisation form')])
        self.assertEqual(accepted, [{**ROUTE, 'evidence_turns': ['t012']}],
                         'An uncited answer never becomes a citation of the published route')
        self.assertEqual(gaps, [])

    def test_typography_and_letter_case_do_not_turn_a_quotation_into_a_fabrication(self):
        variants = {
            'capital letter': DECISIVE.replace('If the', 'if the'),
            'upper case': DECISIVE.upper(),
            'doubled space': DECISIVE.replace(' outside ', '  outside '),
            'line break': DECISIVE.replace(', the claim', ',\n the claim'),
            'no-break space': DECISIVE.replace('warranty period', 'warranty' + NO_BREAK_SPACE + 'period'),
            'typographic apostrophe': CURLY_APOSTROPHE_QUOTE,
        }
        for name, text in variants.items():
            with self.subTest(variant=name):
                accepted, gaps = ground([quote('t012', text)])
                self.assertEqual(accepted, [{**ROUTE, 'evidence_turns': ['t012']}])
                self.assertEqual(gaps, [])
        edge = {**ROUTE, 'evidence_turns': ['u1']}
        for name, said, quoted in (
                ('typographic quotation marks', 'We mark the claim "closed as rejected" in the log.',
                 'We mark the claim ' + OPEN_QUOTE + 'closed as rejected' + CLOSE_QUOTE + ' in the log.'),
                ('straightened quotation marks', 'We mark the claim ' + OPEN_QUOTE + 'closed as rejected' + CLOSE_QUOTE + ' in the log.',
                 'We mark the claim "closed as rejected" in the log.'),
                ('dash', 'Claims outside warranty ' + EN_DASH + ' they are closed as rejected.',
                 'Claims outside warranty - they are closed as rejected.')):
            with self.subTest(variant=name):
                accepted, gaps = server.grounded_routes(
                    [edge], [review([quote('u1', quoted)])], STEPS, {}, [{'id': 'u1', 'role': 'user', 'text': said}], [])
                self.assertEqual((accepted, gaps), ([edge], []))

    def test_passages_that_are_not_the_cited_participant_words_still_leave_the_route_open(self):
        cases = {
            'no passage': [],
            'empty quotation': [quote('t012', '   ')],
            'fabricated wording': [quote('t012', 'Claims outside the warranty period are rejected and closed.')],
            'fabricated beside a real quotation': [quote('t012', DECISIVE), quote('t004', 'The claim is then rejected.')],
            'fragments joined by an ellipsis': [quote('t012', 'If the appliance is outside the warranty period ... closed as rejected.')],
            'assistant question': [quote('a2', 'Is there anything you would like to correct?')],
            'unknown source': [quote('t999', DECISIVE)],
            'verbatim answer the route does not cite': [quote('t006', 'I fill in a repair authorisation form')],
            'quotation attributed to the wrong cited answer': [quote('t004', DECISIVE)],
        }
        for name, passages in cases.items():
            with self.subTest(case=name):
                accepted, gaps = ground(passages)
                self.assertEqual(accepted, [])
                self.assertEqual(len(gaps), 1)
                self.assertIn(GAP, gaps[0])
                self.assertIn('Close claim as rejected', gaps[0])

    def test_objective_and_inactive_files_still_cannot_support_a_route(self):
        text = 'Rejected claims are closed by the claims handler.'
        docs = [{'id': 'doc_ref', 'text': text, 'retained_only': True}]
        for source in ('context', 'doc_ref'):
            with self.subTest(source=source):
                edge = {**ROUTE, 'evidence_turns': [source, 't012']}
                accepted, gaps = server.grounded_routes(
                    [edge], [review([quote(source, text)])], STEPS, {'objective': text}, turns(), docs)
                self.assertEqual(accepted, [])
                self.assertTrue(gaps)
                # The same proposal survives on the participant's own words, without the unusable source.
                accepted, gaps = server.grounded_routes(
                    [edge], [review([quote('t012', DECISIVE)])], STEPS, {'objective': text}, turns(), docs)
                self.assertEqual(accepted, [{**edge, 'evidence_turns': ['t012']}])
                self.assertEqual(gaps, [])


class RouteRecheckGateTests(unittest.TestCase):
    """One second request for routes whose passages could not be verified."""

    JOINED = [quote('t012', 'If the appliance is outside the warranty period ... closed as rejected.')]

    def test_unverifiable_passages_are_asked_about_once_and_a_verified_answer_publishes_the_route(self):
        recheck = StubRecheck([review([quote('t012', DECISIVE)])])
        accepted, gaps = ground(self.JOINED, recheck=recheck)
        self.assertEqual(accepted, [{**ROUTE, 'evidence_turns': ['t012']}])
        self.assertEqual(gaps, [])
        self.assertEqual(len(recheck.asked), 1)
        row, = recheck.asked[0]
        self.assertEqual({key: row[key] for key in ('from', 'to', 'label', 'evidence_turns')}, ROUTE)
        self.assertEqual((row['from_title'], row['to_title']), ('Is the appliance within warranty?', 'Close claim as rejected'))
        self.assertEqual(row['first_passages'], self.JOINED)
        self.assertIn('does not occur', row['problem'])
        self.assertEqual(recheck.records, [('quote_not_found', 'recheck_verified')])

    def test_a_second_answer_that_still_cannot_be_verified_leaves_the_route_open(self):
        for name, rows in {'same unverifiable quotation': [review(self.JOINED)],
                           'withdrawn': [review([])],
                           'uncited answer': [review([quote('t006', 'I fill in a repair authorisation form')])],
                           'row missing': [],
                           'another route': [review([quote('t006', 'I fill in a repair authorisation form')], INSIDE)]}.items():
            with self.subTest(second=name):
                recheck = StubRecheck(rows)
                accepted, gaps = ground(self.JOINED, recheck=recheck)
                self.assertEqual(accepted, [])
                self.assertTrue(gaps and GAP in gaps[0])
                self.assertEqual(len(recheck.asked), 1, 'Never more than one second request')
                self.assertEqual(recheck.records, [('quote_not_found', 'recheck_rejected')])

    def test_an_unavailable_second_review_keeps_the_first_decision(self):
        recheck = StubRecheck(None)
        accepted, gaps = ground(self.JOINED, recheck=recheck)
        self.assertEqual(accepted, [])
        self.assertTrue(gaps and GAP in gaps[0])
        self.assertEqual(recheck.records, [('quote_not_found', 'recheck_unavailable')])

    def test_a_route_returned_without_any_passage_is_the_reviewers_decision_and_is_not_asked_again(self):
        recheck = StubRecheck([review([quote('t012', DECISIVE)])])
        accepted, gaps = ground([], recheck=recheck)
        self.assertEqual(accepted, [])
        self.assertTrue(gaps and GAP in gaps[0])
        self.assertEqual(recheck.asked, [])
        self.assertEqual(recheck.records, [('no_passage', 'open_question')])

    def test_each_failure_is_recorded_by_category_and_verified_routes_are_not(self):
        cases = {'wrong_source': [quote('t006', 'I fill in a repair authorisation form')],
                 'quote_not_found': [quote('t012', 'Claims outside the warranty period are rejected and closed.')]}
        for reason, passages in cases.items():
            with self.subTest(reason=reason):
                recheck = StubRecheck([review(passages)])
                ground(passages, recheck=recheck)
                self.assertEqual(recheck.records, [(reason, 'recheck_rejected')])
        recheck = StubRecheck()
        ground([quote('t012', DECISIVE)], recheck=recheck)
        self.assertEqual((recheck.asked, recheck.records), ([], []))

    def test_one_request_covers_every_unverified_route_and_keeps_the_map_order(self):
        second = {'from': 'S3', 'to': 'S5', 'label': 'Inside warranty period', 'evidence_turns': ['t006']}
        third = {'from': 'S5', 'to': 'S4', 'label': 'Repair refused', 'evidence_turns': ['t006']}
        reviews = [review(self.JOINED), review([quote('t006', 'I fill in a repair authorisation form.')], second),
                   review([quote('t006', 'the repair is refused')], third)]
        recheck = StubRecheck([review([quote('t012', DECISIVE)]), review([], third)])
        accepted, gaps = server.grounded_routes([ROUTE, second, third], reviews, STEPS, {}, turns(), [], recheck=recheck)
        self.assertEqual(accepted, [{**ROUTE, 'evidence_turns': ['t012']}, second])
        self.assertEqual(len(gaps), 1)
        self.assertIn('Repair refused', gaps[0])
        self.assertEqual([[row['label'] for row in rows] for rows in recheck.asked],
                         [['Outside warranty period', 'Repair refused']])

    def test_asking_again_about_a_route_without_any_passage_is_one_explicit_switch(self):
        recheck = StubRecheck([review([quote('t012', DECISIVE)])])
        with patch.object(server, 'ROUTE_RECHECK_REASONS', server.ROUTE_RECHECK_REASONS | {'no_passage'}):
            accepted, gaps = ground([], recheck=recheck)
        self.assertEqual(accepted, [{**ROUTE, 'evidence_turns': ['t012']}])
        self.assertIn('no passage', recheck.asked[0][0]['problem'])
        self.assertEqual(recheck.records, [('no_passage', 'recheck_verified')])
        self.assertEqual(server.ROUTE_RECHECK_REASONS, {'wrong_source', 'quote_not_found'})

    def test_a_route_to_a_step_leaving_the_map_is_not_asked_about_again(self):
        recheck = StubRecheck([review([quote('t012', DECISIVE)])])
        accepted, gaps = ground(self.JOINED, recheck=recheck, removed={'S4'})
        self.assertEqual(accepted, [])
        self.assertTrue(gaps)
        self.assertEqual(recheck.asked, [])
        self.assertEqual(recheck.records, [('quote_not_found', 'open_question')])
        # The map update passes the steps it removes: a rescued route to one of them would
        # make the whole update fail where it used to succeed without that route.
        payload = workflow_payload()
        previous = server.workflow_previous_capture(payload['previous_capture'], payload['turns'])
        leaving = {'id': 'S5', 'reason': 'Participant removed the form step.', 'source_quote': 'remove', 'evidence_turns': ['t012']}
        to_leaving = {'from': 'S3', 'to': 'S5', 'label': 'Form requested', 'evidence_turns': ['t006']}
        candidate = candidate_update(upsert_steps=[], upsert_connections=[to_leaving], remove_steps=[leaving])
        reviewed = workflow_audit([], route_support=[review([quote('t006', 'inside the warranty period ... a form')], to_leaving)])
        recheck = StubRecheck([review([quote('t006', 'I fill in a repair authorisation form.')], to_leaving)])
        merged = server.apply_workflow_audit(candidate, reviewed, previous, context=payload['context'],
                                             turns=payload['turns'], documents=[], recheck=recheck)
        self.assertEqual((recheck.asked, merged['upsert_connections']), ([], []))


class RouteRecheckRequestTests(unittest.TestCase):
    """The second request itself: bounded, private and never able to fail a publication."""

    ROWS = [{'from': 'S3', 'from_title': 'Is the appliance within warranty?', 'to': 'S4',
             'to_title': 'Close claim as rejected', 'label': 'Outside warranty period',
             'evidence_turns': ['t004', 't012'], 'first_passages': [], 'problem': 'x'}]

    def recheck(self, client, seconds=600, **options):
        return server.RouteRecheck(client, {'background': ''}, turns(), {}, 'working_process_map_audit',
                                   time.monotonic() + seconds, **options)

    def test_request_names_the_routes_and_reuses_the_reviewing_model_within_a_bounded_time(self):
        client = Mock()
        client.structured.return_value = {'route_support': [review([quote('t012', DECISIVE)])]}
        rows = self.recheck(client, model_override='reviewing-model').ask(self.ROWS)
        self.assertEqual(rows, [review([quote('t012', DECISIVE)])])
        instructions, sent, schema, name = client.structured.call_args.args[:4]
        self.assertEqual(name, 'route_support_recheck')
        self.assertEqual(sent['routes_to_recheck'], self.ROWS)
        self.assertEqual(sent['turns'], turns())
        self.assertEqual(schema['properties']['route_support']['minItems'], 1)
        self.assertEqual(list(schema['properties']), ['route_support'])
        self.assertIn('passages=[]', instructions)
        self.assertIn('character for character', instructions)
        self.assertIn('untrusted DATA', instructions)
        self.assertIn(server.REQUIRED_DEPENDENCY_POLICY, instructions)
        self.assertEqual(client.structured.call_args.kwargs['model_override'], 'reviewing-model')
        self.assertLessEqual(client.structured.call_args.kwargs['request_timeout'], server.ROUTE_RECHECK_TIMEOUT)

    def test_no_request_is_made_once_the_first_two_requests_used_their_time(self):
        client = Mock()
        self.assertIsNone(self.recheck(client, seconds=5).ask(self.ROWS))
        client.structured.assert_not_called()
        client.structured.return_value = {'route_support': []}
        self.recheck(client, seconds=40).ask(self.ROWS)
        self.assertLessEqual(client.structured.call_args.kwargs['request_timeout'], 40)

    def test_provider_failure_or_malformed_answer_is_no_second_review(self):
        for failure in (server.APIError('The request to the AI service timed out.', 504), ValueError('bad'),
                        http.client.IncompleteRead(b'{"route_sup'), AttributeError("'list' object has no attribute 'get'"),
                        TypeError("'NoneType' object is not iterable"), KeyError('route_support_recheck'),
                        StopIteration()):
            with self.subTest(failure=type(failure).__name__):
                client = Mock()
                client.structured.side_effect = failure
                self.assertIsNone(self.recheck(client).ask(self.ROWS))
        for malformed in (None, {}, {'route_support': [{'from': 'S3'}]}, {'route_support': 'none'}):
            with self.subTest(malformed=malformed):
                client = Mock()
                client.structured.return_value = malformed
                self.assertIsNone(self.recheck(client).ask(self.ROWS))

    def test_a_provider_answer_of_an_unexpected_shape_is_no_second_review(self):
        # The real client, with only the HTTP call replaced: a 200 answer that is JSON but not
        # the expected envelope must not escape as an AttributeError or TypeError.
        for name, answer in {'a list instead of an object': [],
                             'no output list': {'status': 'completed', 'output': None},
                             'a string as content item': {'status': 'completed', 'output': [{'content': ['text']}]},
                             'incomplete': {'status': 'incomplete', 'output': []}}.items():
            with self.subTest(answer=name):
                client = server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-key'})
                with patch.object(server.openai_transport, 'urlopen', return_value=io.BytesIO(json.dumps(answer).encode())) as sent:
                    self.assertIsNone(self.recheck(client).ask(self.ROWS))
                sent.assert_called_once()

    def test_record_is_category_only_and_survives_a_failing_or_absent_log(self):
        client = Mock()
        self.recheck(client).record('quote_not_found', 'recheck_verified')
        client.diagnostic_callback.assert_called_once_with(
            'route_support_rejected', stage='working_process_map_audit', reason='quote_not_found', outcome='recheck_verified')
        client.diagnostic_callback.side_effect = OSError('PRIVATE_DIAGNOSTIC_SENTINEL')
        self.recheck(client).record('no_passage', 'open_question')
        client.diagnostic_callback = None
        self.recheck(client).record('no_passage', 'open_question')
        with tempfile.TemporaryDirectory(prefix='collector-route-log-') as temporary:
            path = Path(temporary) / 'server-lifecycle.jsonl'
            server.record_diagnostic(path, 'route_support_rejected', stage='process_draft_audit',
                                     reason='wrong_source', outcome='recheck_rejected')
            line = json.loads(path.read_text())
        self.assertEqual((line['event'], line['stage'], line['reason'], line['outcome']),
                         ('route_support_rejected', 'process_draft_audit', 'wrong_source', 'recheck_rejected'))

    def test_second_request_is_a_known_provider_stage(self):
        diagnostics = Mock()
        client = server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-key'}, diagnostics)
        answer = {'status': 'completed', 'output': []}
        with patch.object(server.openai_transport, 'urlopen', return_value=io.BytesIO(json.dumps(answer).encode())):
            client.request('responses', {'text': {'format': {'name': 'route_support_recheck'}}})
        self.assertEqual(diagnostics.call_args.kwargs['stage'], 'route_support_recheck')


class WorkingMapRouteTests(unittest.TestCase):
    """The on-demand working map (the voice path)."""

    def test_stated_route_survives_when_the_reviewer_quotes_only_the_decisive_answer(self):
        client = workflow_client(candidate_update(), workflow_audit([quote('t012', DECISIVE)]))
        result = client.workflow(workflow_payload())['workflow']
        self.assertEqual(published(result), {**ROUTE, 'evidence_turns': ['t012']})
        self.assertEqual(result['connections'][0], INSIDE)
        self.assertFalse(any(GAP in question or 'S4' in question for question in result['open_questions']),
                         result['open_questions'])
        self.assertEqual(client.structured.call_count, 2, 'A verified first review needs no second request')

    def test_near_verbatim_or_surplus_quotations_publish_the_route_without_a_second_request(self):
        for passages in ([quote('t004', 'the claim is closed as rejected'), quote('t012', DECISIVE.replace('If the', 'if the'))],
                         [quote('t004', 'the claim is closed as rejected'), quote('t012', DECISIVE),
                          quote('t006', 'I fill in a repair authorisation form')],
                         [quote('t004', 'the claim is closed as rejected'), quote('t012', CURLY_APOSTROPHE_QUOTE)]):
            with self.subTest(passages=passages):
                client = workflow_client(candidate_update(), workflow_audit(passages))
                result = client.workflow(workflow_payload())['workflow']
                self.assertEqual(published(result), ROUTE)
                self.assertEqual(client.structured.call_count, 2)

    def test_unverifiable_quotation_is_rechecked_once_instead_of_publishing_an_orphan(self):
        joined = [quote('t012', 'If the appliance is outside the warranty period ... closed as rejected.')]
        client = workflow_client(candidate_update(), workflow_audit(joined),
                                 {'route_support': [review([quote('t012', DECISIVE)])]})
        client.diagnostic_callback = Mock()
        result = client.workflow(workflow_payload())['workflow']
        self.assertEqual(published(result), {**ROUTE, 'evidence_turns': ['t012']})
        self.assertFalse(any(GAP in question for question in result['open_questions']))
        self.assertEqual([call.args[3] for call in client.structured.call_args_list],
                         ['working_process_map', 'working_process_map_audit', 'route_support_recheck'])
        second = client.structured.call_args
        self.assertEqual([row['label'] for row in second.args[1]['routes_to_recheck']], ['Outside warranty period'])
        self.assertEqual(second.kwargs['model_override'], client.workflow_audit_model)
        client.diagnostic_callback.assert_called_once_with(
            'route_support_rejected', stage='working_process_map_audit', reason='quote_not_found', outcome='recheck_verified')

    def test_failed_recheck_publishes_the_map_with_the_route_left_open(self):
        joined = [quote('t012', 'If the appliance is outside the warranty period ... closed as rejected.')]
        for third in ({'route_support': [review(joined)]}, {'route_support': [review([])]},
                      server.APIError('The request to the AI service timed out.', 504),
                      http.client.IncompleteRead(b'{"route_sup'), AttributeError("'list' object has no attribute 'get'")):
            with self.subTest(third=type(third).__name__):
                client = workflow_client(candidate_update(), workflow_audit(joined), third)
                result = client.workflow(workflow_payload())['workflow']
                self.assertIsNone(published(result))
                self.assertIn('S4', [item['id'] for item in result['steps']])
                self.assertTrue(any(GAP in question and 'Close claim as rejected' in question
                                    for question in result['open_questions']))
                self.assertEqual(client.structured.call_count, 3, 'Exactly one second request, never a loop')

    def test_revised_step_keeps_a_handoff_whose_first_quotation_could_not_be_verified(self):
        payload = workflow_payload()
        payload['turns'].append({'id': 't014', 'role': 'user',
                                 'text': 'Call the form step issuing the repair authorisation; it still follows the warranty decision.'})
        renamed = step('S5', 'Issue repair authorisation', sources=('t006', 't014'))
        inherited = review([quote('t006', 'If it is inside the warranty period ... a repair authorisation form.')], INSIDE)
        verbatim = review([quote('t006', 'If it is inside the warranty period, I fill in a repair authorisation form.')], INSIDE)
        change = candidate_update(upsert_steps=[renamed], upsert_connections=[])
        client = workflow_client(change, workflow_audit([], route_support=[inherited]), {'route_support': [verbatim]})
        result = client.workflow(payload)['workflow']
        self.assertEqual(result['steps'][1]['title'], 'Issue repair authorisation')
        self.assertEqual(result['connections'], [INSIDE])
        client = workflow_client(change, workflow_audit([], route_support=[inherited]), {'route_support': [inherited]})
        with self.assertRaisesRegex(server.APIError, 'handoff S3 to S5 unverified'):
            client.workflow(payload)


class DraftRouteTests(unittest.TestCase):
    """The review draft: its map must not lose a route its own text states."""

    STATED = 'Invoices that do not match the purchase order go to the buyer.'

    def draft(self):
        draft = process_draft()
        buyer = copy.deepcopy(draft['steps'][1])
        buyer.update(id='s3', title='Refer invoice to buyer', actor='Buyer', evidence_turns=['u2'])
        draft['steps'].append(buyer)
        draft['connections'].append({'from': 's1', 'to': 's3', 'label': 'Does not match the purchase order',
                                     'evidence_turns': ['u1', 'u2']})
        return draft

    def client(self, passages, *more):
        payload, draft = interview_payload(), self.draft()
        reviewed = fixture_draft_audit(draft, payload['turns'])
        reviewed['route_support'][1]['passages'] = passages
        client = server.OpenAIClient({'OPENAI_API_KEY': 'fictional'})
        client.structured = Mock(side_effect=[copy.deepcopy(draft), reviewed, *more])
        return client, payload, draft

    def test_draft_keeps_the_route_its_exceptions_text_states(self):
        for passages in ([quote('u2', self.STATED)], [quote('u2', self.STATED.lower())],
                         [quote('u2', self.STATED), quote('u1', 'logs invoices in a spreadsheet')]):
            with self.subTest(passages=passages):
                client, payload, draft = self.client(passages)
                result = client.draft(payload)['draft']
                cited = ['u1', 'u2'] if len(passages) > 1 else ['u2']
                self.assertEqual(result['connections'], [draft['connections'][0], {**draft['connections'][1], 'evidence_turns': cited}])
                self.assertIn(self.STATED, result['exceptions'])
                self.assertFalse(any(GAP in question or 's3' in question for question in result['open_questions']),
                                 result['open_questions'])
                self.assertNotIn('route_support', result)
                self.assertEqual(client.structured.call_count, 2)

    def test_draft_rechecks_an_unverifiable_quotation_once(self):
        joined = [quote('u2', 'Invoices that do not match ... go to the buyer.')]
        row = {'from': 's1', 'to': 's3', 'label': 'Does not match the purchase order'}
        client, payload, draft = self.client(joined, {'route_support': [{**row, 'passages': [quote('u2', self.STATED)]}]})
        client.diagnostic_callback = Mock()
        result = client.draft(payload)['draft']
        self.assertEqual(result['connections'][1], {**draft['connections'][1], 'evidence_turns': ['u2']})
        self.assertEqual([call.args[3] for call in client.structured.call_args_list],
                         ['process_draft', 'process_draft_audit', 'route_support_recheck'])
        self.assertEqual(client.structured.call_args.kwargs['model_override'], client.draft_model)
        client.diagnostic_callback.assert_called_once_with(
            'route_support_rejected', stage='process_draft_audit', reason='quote_not_found', outcome='recheck_verified')
        client, payload, draft = self.client(joined, {'route_support': [{**row, 'passages': joined}]})
        result = client.draft(payload)['draft']
        self.assertEqual(result['connections'], draft['connections'][:1])
        self.assertTrue(any(GAP in question and 'Refer invoice to buyer' in question for question in result['open_questions']))
        self.assertEqual(client.structured.call_count, 3)

    def test_draft_survives_a_second_request_that_breaks_in_an_unforeseen_way(self):
        joined = [quote('u2', 'Invoices that do not match ... go to the buyer.')]
        for failure in (http.client.IncompleteRead(b'{"route_sup'), AttributeError("'list' object has no attribute 'get'")):
            with self.subTest(failure=type(failure).__name__):
                client, payload, draft = self.client(joined, failure)
                result = client.draft(payload)['draft']
                self.assertEqual(result['connections'], draft['connections'][:1])
                self.assertTrue(any(GAP in question and 'Refer invoice to buyer' in question
                                    for question in result['open_questions']))
                self.assertEqual(client.structured.call_count, 3)


class RecheckingTeamProvider(SyntheticTeamProvider):
    def __init__(self, first, second=None):
        super().__init__()
        self.first, self.second = first, second
        self.turns.append({'id': 'u_treasury', 'role': 'user', 'text': 'Treasury works its queue every afternoon.'})
        self.result_changes['team_working_process_map'] = self.propose
        self.result_changes['team_working_map_source_audit'] = lambda result: result['route_support'].append(
            {**self.row, 'passages': self.first})

    row = {'from': 's1', 'to': 'treasury', 'label': 'Queue link'}
    stated = 'Other invoices go by queue link to Treasury, which records Accepted.'

    def propose(self, update):
        accept = copy.deepcopy(update['upsert_steps'][0])
        accept.update(id='treasury', title='Treasury records acceptance', evidence_turns=['u_lifecycle'])
        update['upsert_steps'].append(accept)
        update['upsert_connections'].append({**self.row, 'evidence_turns': ['u_lifecycle', 'u_treasury']})

    def reply(self, path, body, *args, **kwargs):
        if path == 'responses' and body['text']['format']['name'] == 'route_support_recheck':
            if isinstance(self.second, Exception):
                raise self.second
            answer = {'route_support': [{**self.row, 'passages': self.second}]}
            return {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(answer)}]}]}
        return super().reply(path, body, *args, **kwargs)


class TeamWorkingMapRouteTests(unittest.TestCase):
    """The background map of a typed interview (the coordinator path)."""

    def names(self, client):
        return [call.args[1]['text']['format']['name'] for call in client.request.call_args_list]

    def test_typed_interview_map_keeps_the_stated_route_on_the_decisive_answer(self):
        client = RecheckingTeamProvider([quote('u_lifecycle', RecheckingTeamProvider.stated)])
        result = client.coordinator.workflow(client.payload())
        self.assertEqual(result['workflow']['connections'], [{**client.row, 'evidence_turns': ['u_lifecycle']}])
        self.assertFalse(any(GAP in question for question in result['workflow']['open_questions']))
        self.assertEqual(self.names(client), ['team_working_process_map', 'team_working_map_source_audit'])

    def test_typed_interview_map_rechecks_once_inside_the_source_audit_step(self):
        joined = [quote('u_lifecycle', 'Other invoices go ... to Treasury')]
        client = RecheckingTeamProvider(joined, [quote('u_lifecycle', RecheckingTeamProvider.stated)])
        result = client.coordinator.workflow(client.payload())
        self.assertEqual(result['workflow']['connections'], [{**client.row, 'evidence_turns': ['u_lifecycle']}])
        self.assertEqual(self.names(client), ['team_working_process_map', 'team_working_map_source_audit', 'route_support_recheck'])
        self.assertEqual(client.request.call_args.args[1]['model'], client.agent_models['process_reviewer'])
        lead = next(row for row in result['agent_team']['agents'] if row['role'] == 'lead_interviewer')
        self.assertEqual((lead['status'], lead['calls']), ('completed', 2))
        for second in (joined, server.APIError('The request to the AI service timed out.', 504)):
            with self.subTest(second=type(second).__name__):
                client = RecheckingTeamProvider(joined, second)
                graph = client.coordinator.workflow(client.payload())['workflow']
                self.assertEqual(graph['connections'], [])
                self.assertEqual([item['id'] for item in graph['steps']], ['s1', 'treasury'])
                self.assertTrue(any(GAP in question and 'Treasury records acceptance' in question
                                    for question in graph['open_questions']))
                self.assertEqual(len(client.request.call_args_list), 3)

    def test_cancelled_or_replaced_map_run_does_not_pay_for_a_second_request(self):
        for reason in ('cancelled', 'stale'):
            with self.subTest(reason=reason):
                client = RecheckingTeamProvider([quote('u_lifecycle', 'Other invoices go ... to Treasury')],
                                                [quote('u_lifecycle', RecheckingTeamProvider.stated)])
                payload = client.payload()
                payload['agent_run_id'] = 'route-recheck-' + reason + '-123456789'

                def block(body):
                    run = client.coordinator._runs[payload['agent_run_id']][1]
                    run.cancel() if reason == 'cancelled' else run.invalidate('new-source')
                client.hooks['team_working_map_source_audit'] = block
                with self.assertRaises(server.APIError) as refused:
                    client.coordinator.workflow(payload)
                self.assertEqual(refused.exception.status, 409)
                self.assertEqual(self.names(client), ['team_working_process_map', 'team_working_map_source_audit'])


class PublishedRouteReproposalTests(unittest.TestCase):
    """A new proposal for a route that is already on the map (same from, to and label).

    Publishing a route with only its quoted citations makes this ordinary: the map model can
    propose the same route again with the wider list it first had, or with one more answer.
    """

    WOULD_VERIFY = [review([quote('t012', DECISIVE)])]

    def ground(self, published_sources, proposed_sources, passages, recheck=None, documents=()):
        on_map = {**ROUTE, 'evidence_turns': list(published_sources)}
        proposal = {**ROUTE, 'evidence_turns': list(proposed_sources)}
        accepted, gaps = server.grounded_routes([proposal], [review(passages)], STEPS, {}, restated_turns(),
                                                list(documents), baseline=[INSIDE, on_map], recheck=recheck)
        return [edge['evidence_turns'] for edge in accepted], gaps

    def test_a_newly_quoted_answer_extends_the_citations_an_earlier_review_verified(self):
        again = quote('t014', 'once it is outside warranty we close it as rejected')
        for name, on_map, proposed, passages, expected in (
                ('only the added answer is quoted', ['t004', 't012'], ['t004', 't012', 't014'], [again], ['t004', 't012', 't014']),
                ('only an earlier answer is quoted', ['t004', 't012'], ['t004', 't012', 't014'], [quote('t012', DECISIVE)], ['t004', 't012']),
                ('the proposal drops a citation', ['t004', 't012'], ['t014', 't012'], [again], ['t012', 't014']),
                ('the wider list returns and is quoted', ['t012'], ['t004', 't012'],
                 [quote('t004', 'the claim is closed as rejected')], ['t012', 't004']),
                ('the wider list returns, decisive answer quoted', ['t012'], ['t004', 't012'], [quote('t012', DECISIVE)], ['t012'])):
            with self.subTest(case=name):
                self.assertEqual(self.ground(on_map, proposed, passages), ([expected], []))

    def test_a_citation_that_can_no_longer_be_quoted_is_not_carried_into_a_changed_route(self):
        retired = [{'id': 'doc_old', 'text': 'Rejected claims are closed.', 'retained_only': True}]
        cited, gaps = self.ground(['doc_old', 't012'], ['doc_old', 't012', 't014'],
                                  [quote('t014', 'once it is outside warranty we close it as rejected')], documents=retired)
        self.assertEqual((cited, gaps), ([['t012', 't014']], []))

    def test_a_failed_new_proposal_leaves_the_published_route_as_it_was_and_asks_nothing(self):
        cases = {'no_passage': [],
                 'quote_not_found': [quote('t012', 'Outside warranty the claim gets closed as rejected.')],
                 'wrong_source': [quote('t006', 'I fill in a repair authorisation form')]}
        for reason, passages in cases.items():
            with self.subTest(reason=reason):
                recheck = StubRecheck(self.WOULD_VERIFY)
                cited, gaps = self.ground(['t012'], ['t004', 't012'], passages, recheck=recheck)
                self.assertEqual(cited, [['t012']], 'The route stays on the map with the citations it had')
                self.assertEqual(gaps, [], 'No question may contradict an arrow that stays drawn')
                self.assertEqual(recheck.asked, [], 'A route that cannot become an orphan earns no second request')
                self.assertEqual(recheck.records, [(reason, 'route_kept')])
                self.assertEqual(self.ground(['t012'], ['t004', 't012'], passages), ([['t012']], []))

    def test_a_failed_proposal_that_replaces_the_route_s_evidence_is_still_an_open_question(self):
        # Unchanged behaviour, pinned for the whole map update by
        # test_workflow_updates.test_revised_evidence_without_support_leaves_the_accepted_route_intact:
        # nothing is published for the route, so the map keeps it, and the doubt is asked about.
        fabricated = [quote('t014', 'Outside warranty the claim gets closed as rejected.')]
        recheck = StubRecheck([review(fabricated)])
        cited, gaps = self.ground(['t004', 't012'], ['t014'], fabricated, recheck=recheck)
        self.assertEqual(cited, [])
        self.assertTrue(gaps and GAP in gaps[0])
        self.assertEqual(len(recheck.asked), 1)
        self.assertEqual(recheck.records, [('quote_not_found', 'recheck_rejected')])
        recheck = StubRecheck([review([quote('t014', 'once it is outside warranty we close it as rejected')])])
        self.assertEqual(self.ground(['t004', 't012'], ['t014'], fabricated, recheck=recheck), ([['t014']], []))
        self.assertEqual(recheck.records, [('quote_not_found', 'recheck_verified')])
        # One dropped citation is enough to make it a replacement.
        cited, gaps = self.ground(['t004', 't012'], ['t012', 't014'], [])
        self.assertEqual(cited, [])
        self.assertTrue(gaps and GAP in gaps[0])

    def second_update(self, audit_passages):
        payload = workflow_payload()
        first = workflow_client(candidate_update(), workflow_audit([quote('t012', DECISIVE)])).workflow(copy.deepcopy(payload))
        self.assertEqual(published(first['workflow']), {**ROUTE, 'evidence_turns': ['t012']})
        payload['turns'] += [{'id': 'a3', 'role': 'assistant', 'text': 'Who signs the repair form?'},
                             {'id': 't014', 'role': 'user', 'text': 'The workshop lead signs the repair form.'}]
        payload['previous_capture'] = {key: first[key] for key in ('workflow', 'memo_findings', 'summary', 'focus', 'parking_lot')}
        # The map model issues the route again exactly as it first proposed it; no step changes.
        client = workflow_client(candidate_update(upsert_steps=[]), workflow_audit(audit_passages),
                                 {'route_support': self.WOULD_VERIFY})
        return client, client.workflow(payload)['workflow']

    def test_the_next_update_neither_drops_nor_questions_a_route_proposed_again_with_its_wider_citations(self):
        for name, passages in {'fabricated quotation': [quote('t012', 'Outside warranty the claim gets closed as rejected.')],
                               'no passage': []}.items():
            with self.subTest(second_review=name):
                client, graph = self.second_update(passages)
                self.assertEqual(published(graph), {**ROUTE, 'evidence_turns': ['t012']})
                self.assertEqual([item['id'] for item in graph['steps']], ['S3', 'S5', 'S4'])
                self.assertFalse(any(GAP in question for question in graph['open_questions']), graph['open_questions'])
                self.assertEqual([call.args[3] for call in client.structured.call_args_list],
                                 ['working_process_map', 'working_process_map_audit'])

    def test_the_next_update_adds_the_earlier_answer_once_the_reviewer_quotes_it(self):
        client, graph = self.second_update([quote('t004', 'the claim is closed as rejected')])
        self.assertEqual(published(graph), {**ROUTE, 'evidence_turns': ['t012', 't004']})
        self.assertEqual(client.structured.call_count, 2)

    def test_a_route_the_same_update_takes_off_the_map_is_not_kept_by_a_failed_proposal(self):
        # Keeping it would turn the failed proposal into an edit of a component that the same
        # update removes, and fail an update that used to succeed without the route.
        payload = workflow_payload()
        payload['previous_capture']['workflow']['steps'] = copy.deepcopy(STEPS)
        payload['previous_capture']['workflow']['connections'].append({**ROUTE, 'evidence_turns': ['t012']})
        previous = server.workflow_previous_capture(payload['previous_capture'], payload['turns'])
        removal = {'reason': 'The participant withdrew it.', 'source_quote': 'Please remove the rejection letter step',
                   'evidence_turns': ['t012']}
        for name, edits in {'its step is removed': {'remove_steps': [{'id': 'S4', **removal}]},
                            'the route is removed': {'remove_connections': [
                                {'from': 'S3', 'to': 'S4', 'label': 'Outside warranty period', **removal}]}}.items():
            with self.subTest(case=name):
                recheck = StubRecheck(self.WOULD_VERIFY)
                merged = server.apply_workflow_audit(candidate_update(upsert_steps=[], **edits), workflow_audit([]), previous,
                                                     context=payload['context'], turns=payload['turns'], documents=[],
                                                     recheck=recheck)
                self.assertEqual(merged['upsert_connections'], [])
                self.assertEqual(recheck.records, [('no_passage', 'open_question')])
                graph = server.apply_workflow_update(merged, previous, payload['turns'])['workflow']
                self.assertIsNone(published(graph))

    def test_an_existing_handoff_of_a_renamed_step_is_still_reviewed_in_full(self):
        # Not a route "already on the map" in the sense above: the step it touches changed, so
        # it keeps its place only on verified passages (and an unverified one fails the update).
        payload = workflow_payload()
        renamed = step('S5', 'Issue repair authorisation', sources=('t006',))
        client = workflow_client(candidate_update(upsert_steps=[renamed], upsert_connections=[]),
                                 workflow_audit([], route_support=[review([], INSIDE)]))
        with self.assertRaisesRegex(server.APIError, 'handoff S3 to S5 unverified'):
            client.workflow(payload)


class ReviewerReissueTests(unittest.TestCase):
    """The reviewer corrects only the citations of a candidate route (same from, to and label)."""

    def audited(self, **edits):
        proposed = {**ROUTE, 'evidence_turns': ['t004']}
        client = workflow_client(candidate_update(upsert_connections=[proposed]),
                                 workflow_audit([quote('t012', DECISIVE)], **edits), {'route_support': [review([])]})
        return client, client.workflow(workflow_payload())['workflow']

    def test_discarding_the_candidate_route_and_supplying_it_again_replaces_it(self):
        corrected = {**ROUTE, 'evidence_turns': ['t012']}
        identity = {key: ROUTE[key] for key in ('from', 'to', 'label')}
        for name, edits in {'re-issued only': {'upsert_connections': [corrected]},
                            'discarded and re-issued': {'upsert_connections': [corrected],
                                                        'discard_connection_upserts': [identity]}}.items():
            with self.subTest(reviewer=name):
                client, graph = self.audited(**edits)
                self.assertEqual(published(graph), corrected)
                self.assertFalse(any(GAP in question for question in graph['open_questions']))
                self.assertEqual(client.structured.call_count, 2)

    def test_a_reissued_route_still_needs_verified_passages_and_a_discard_alone_still_discards(self):
        identity = {key: ROUTE[key] for key in ('from', 'to', 'label')}
        uncited = {**ROUTE, 'evidence_turns': ['t006']}
        client, graph = self.audited(upsert_connections=[uncited], discard_connection_upserts=[identity])
        self.assertIsNone(published(graph), 'The replacement cites an answer the passages do not come from')
        self.assertTrue(any(GAP in question for question in graph['open_questions']))
        client, graph = self.audited(discard_connection_upserts=[identity], route_support=[])
        self.assertIsNone(published(graph))

    def test_a_step_discarded_and_supplied_again_in_one_review_is_replaced(self):
        # Discarding a candidate step and supplying it again says one thing, as it does for a
        # route: replace it. It changes nothing that was accepted and is no reason to refuse the map.
        replacement = {**copy.deepcopy(STEPS[2]), 'description': 'The reviewer restated this step.'}
        client = workflow_client(candidate_update(), workflow_audit(
            [quote('t012', DECISIVE)], discard_step_upserts=['S4'], upsert_steps=[replacement]))
        graph = client.workflow(workflow_payload())['workflow']
        self.assertEqual(next(step for step in graph['steps'] if step['id'] == 'S4')['description'],
                         'The reviewer restated this step.')
        self.assertIsNotNone(published(graph))


class RouteRecheckDeadlineTests(unittest.TestCase):
    """Each caller gives the second request only the time its first two requests left unused.

    The clock is scripted, so these tests pin the deadline at the three call sites: measured
    from the start of the map or draft request, never from the end of the review before it.
    """

    JOINED = [quote('t012', 'If the appliance is outside the warranty period ... closed as rejected.')]
    SECOND = {'route_support': [review([quote('t012', DECISIVE)])]}
    DOCUMENTS = {'documents': [{'id': 'file1', 'name': 'Warranty procedure', 'excerpts': [
        {'id': 'doc_p1', 'text': 'Claims are assessed against the two-year warranty period.'}]}]}

    def test_working_map_gives_the_second_request_only_the_unused_time(self):
        slow, review_slow = server.DOCUMENT_WORKFLOW_TIMEOUT, server.DOCUMENT_WORKFLOW_AUDIT_TIMEOUT
        for name, supporting, first, second, left in (
                ('transcript only, time used up', None, 85, 85, None),
                ('transcript only, 40 seconds left', None, 70, 70, 40),
                ('with a reference file, time used up', self.DOCUMENTS, slow - 5, review_slow - 5, None),
                ('with a reference file, 30 seconds left', self.DOCUMENTS, slow - 10, review_slow - 20, 30)):
            with self.subTest(case=name):
                clock = Clock()
                client = server.OpenAIClient({'OPENAI_API_KEY': 'sk-synthetic-route-grounding'})
                client.structured = timed_replies(clock, (first, candidate_update()), (second, workflow_audit(self.JOINED)),
                                                  (1, self.SECOND))
                payload = workflow_payload()
                if supporting:
                    payload['_supporting_documents'] = copy.deepcopy(supporting)
                with patch.object(server.time, 'monotonic', clock):
                    graph = client.workflow(payload)['workflow']
                names = [call.args[3] for call in client.structured.call_args_list]
                if left is None:
                    self.assertEqual(names, ['working_process_map', 'working_process_map_audit'])
                    self.assertIsNone(published(graph))
                    self.assertTrue(any(GAP in question and 'Close claim as rejected' in question
                                        for question in graph['open_questions']))
                else:
                    self.assertEqual(names, ['working_process_map', 'working_process_map_audit', 'route_support_recheck'])
                    self.assertEqual(client.structured.call_args.kwargs['request_timeout'], left)
                    self.assertEqual(published(graph), {**ROUTE, 'evidence_turns': ['t012']})

    def test_draft_gives_the_second_request_only_the_unused_time(self):
        joined = [quote('u2', 'Invoices that do not match ... go to the buyer.')]
        row = {'from': 's1', 'to': 's3', 'label': 'Does not match the purchase order'}
        answer = {'route_support': [{**row, 'passages': [quote('u2', DraftRouteTests.STATED)]}]}
        for name, first, second, left in (
                ('time used up', server.DRAFT_GENERATION_TIMEOUT - 5, server.DRAFT_AUDIT_TIMEOUT - 5, None),
                ('45 seconds left', server.DRAFT_GENERATION_TIMEOUT - 25, server.DRAFT_AUDIT_TIMEOUT - 20, 45)):
            with self.subTest(case=name):
                clock = Clock()
                payload, draft = interview_payload(), DraftRouteTests.draft(self)
                reviewed = fixture_draft_audit(draft, payload['turns'])
                reviewed['route_support'][1]['passages'] = joined
                client = server.OpenAIClient({'OPENAI_API_KEY': 'fictional'})
                client.structured = timed_replies(clock, (first, draft), (second, reviewed), (1, answer))
                with patch.object(server.time, 'monotonic', clock):
                    result = client.draft(payload)['draft']
                names = [call.args[3] for call in client.structured.call_args_list]
                if left is None:
                    self.assertEqual(names, ['process_draft', 'process_draft_audit'])
                    self.assertEqual(result['connections'], draft['connections'][:1])
                    self.assertTrue(any(GAP in question and 'Refer invoice to buyer' in question
                                        for question in result['open_questions']))
                else:
                    self.assertEqual(names, ['process_draft', 'process_draft_audit', 'route_support_recheck'])
                    self.assertEqual(client.structured.call_args.kwargs['request_timeout'], left)
                    self.assertEqual(result['connections'][1], {**draft['connections'][1], 'evidence_turns': ['u2']})

    def test_typed_interview_map_gives_the_second_request_only_the_unused_time(self):
        joined = [quote('u_lifecycle', 'Other invoices go ... to Treasury')]
        # A map a browser request waits for: 120 seconds to draw it and 180 for its source audit
        # (the audit of a transcript-only map ran into the earlier 120-second limit).
        drawing, audit = server.interview_orchestrator.MAP_GENERATION_SECONDS, server.interview_orchestrator.MAP_AUDIT_SECONDS
        self.assertEqual((drawing, audit), (120, 180))
        self.assertLessEqual((drawing + audit) * 1000, server.REQUEST_TIMEOUTS_MS['workflow'])
        self.assertLessEqual((drawing + server.interview_orchestrator.MAP_AUDIT_WITH_FILES_SECONDS) * 1000,
                             server.REQUEST_TIMEOUTS_MS['workflow_with_files'])
        for name, first, second, left in (('time used up', drawing - 5, audit - 5, None),
                                          ('40 seconds left', drawing - 20, audit - 20, 40)):
            with self.subTest(case=name):
                clock = Clock()
                client = RecheckingTeamProvider(joined, [quote('u_lifecycle', RecheckingTeamProvider.stated)])
                client.hooks['team_working_process_map'] = lambda body, seconds=first: clock.spend(seconds)
                client.hooks['team_working_map_source_audit'] = lambda body, seconds=second: clock.spend(seconds)
                with patch.object(server.time, 'monotonic', clock):
                    graph = client.coordinator.workflow(client.payload())['workflow']
                names = [call.args[1]['text']['format']['name'] for call in client.request.call_args_list]
                if left is None:
                    self.assertEqual(names, ['team_working_process_map', 'team_working_map_source_audit'])
                    self.assertEqual(graph['connections'], [])
                    self.assertTrue(any(GAP in question and 'Treasury records acceptance' in question
                                        for question in graph['open_questions']))
                else:
                    self.assertEqual(names, ['team_working_process_map', 'team_working_map_source_audit', 'route_support_recheck'])
                    self.assertEqual(client.request.call_args.kwargs['timeout'], left)
                    self.assertEqual(graph['connections'], [{**client.row, 'evidence_turns': ['u_lifecycle']}])


class RouteReviewContractTests(unittest.TestCase):
    def test_a_citation_correction_is_reissued_without_discarding_the_candidate_route(self):
        text = ' '.join(server.WORKFLOW_AUDIT_INSTRUCTIONS.split())
        self.assertIn("When only a candidate edge's evidence_turns change (same from, to and label), supply it in "
                      'upsert_connections alone', text)
        self.assertIn('do not also list it in discard_connection_upserts', text)

    def test_reviewer_is_told_which_passages_count(self):
        text = server.ROUTE_SUPPORT_INSTRUCTIONS
        self.assertIn('need not quote every cited source', text)
        self.assertIn('character for character', text)
        self.assertIn('corrected evidence_turns', text)
        self.assertNotIn('from each cited source', text)
        self.assertIn(text, server.WORKFLOW_AUDIT_INSTRUCTIONS)
        self.assertIn('passages=[]', text)


if __name__ == '__main__':
    unittest.main()
