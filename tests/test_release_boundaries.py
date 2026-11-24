"""Release regressions covering source authority and the documented HTTP surface."""
import ast
from pathlib import Path
import re
import unittest
from unittest.mock import Mock

from test_server import server
from test_workflow_updates import payload, update, removal


class ReleaseBoundaries(unittest.TestCase):
    def test_public_route_inventory_matches_implementation(self):
        root = Path(__file__).resolve().parents[1]
        nodes = ast.walk(ast.parse((root / 'server.py').read_text('utf8')))
        paths = {node.value for node in nodes if isinstance(node, ast.Constant)
                 and isinstance(node.value, str) and re.fullmatch(r'/api/[\w/-]*[\w-]', node.value)}
        documented = set(re.findall(r'\x60(/api/[\w/-]+)\x60', (root / 'docs/API_CONTRACT.md').read_text('utf8')))
        self.assertEqual(paths, documented)

    def test_only_substantive_intake_can_support_a_fact(self):
        objective = {'objective': 'Explain how the work is done.'}
        self.assertEqual(server.evidence_sources([], context=objective), set())
        self.assertEqual(server.evidence_sources([], context={**objective, 'process_owner': 'Registrar'}), {'context'})
        client = server.OpenAIClient({})
        client.request = Mock(return_value={'output_text': '{}', 'output': [{'content': [{'type': 'output_text', 'text': '{}'}]}]})
        client.structured('Synthetic source check.', {'context': objective, 'turns': []}, server.DRAFT_SCHEMA, 'test', 100)
        wire = client.request.call_args.args[1]['text']['format']['schema']
        evidence = wire['properties']['steps']['items']['properties']['evidence_turns']
        self.assertEqual(evidence['maxItems'], 0)
        self.assertNotIn('enum', evidence['items'])

    def test_unrelated_participant_quote_cannot_authorize_whole_map_removal(self):
        snapshot = payload()
        previous, turns = snapshot['previous_capture'], snapshot['turns']
        removed = [removal(step['id'], source='u1', quote='I prepare the discovery board') for step in previous['workflow']['steps']]
        with self.assertRaisesRegex(ValueError, 'remove most'):
            server.apply_workflow_update(update(remove_steps=removed), previous, turns)

    def test_workflow_labels_match_across_renderers(self):
        web = Path(__file__).resolve().parents[1] / 'web'
        app = (web / 'app.js').read_text('utf8').split('const WORKFLOW_TYPES = {', 1)[1].split('};', 1)[0]
        graph = (web / 'workflow-graph.js').read_text('utf8').split('const TYPES={', 1)[1].split('};', 1)[0]
        labels = dict(re.findall(r'(\w+):\["([^"]+)"', app))
        self.assertEqual(set(labels), set(server.WORKFLOW_STEP_TYPES))
        self.assertEqual(labels, dict(re.findall(r'(\w+):\{label:"([^"]+)"', graph)))

    def test_turn_limits_use_the_published_numbers(self):
        base = {'context': {}, 'turns': [{'id': str(i), 'role': 'user', 'text': 'x' * 1000} for i in range(400)]}
        self.assertEqual(len(server.validate_payload(base)[1]), 400)
        with self.assertRaises(ValueError):
            server.validate_payload({**base, 'turns': base['turns'] + [{'role': 'user', 'id': 'more', 'text': 'x'}]})
        base['turns'][0]['text'] += 'x'
        with self.assertRaises(ValueError):
            server.validate_payload(base)
        self.assertEqual(server.request_body_limit('/api/transcribe'), 12 * 1024 * 1024)
        self.assertEqual(server.request_body_limit('/api/draft'), 2 * 1024 * 1024)
