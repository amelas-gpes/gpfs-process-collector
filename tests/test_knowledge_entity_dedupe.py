"""One entity per role, system or business object named in a revision (live-draft-knowledge-7).

A role or system mentioned by several steps keeps one entity in its revision and an edge for each mention. Temporary SQLite; no analyzer, provider or network.
"""
import knowledge_rows as rows
import tempfile
import unittest
from pathlib import Path

from test_knowledge_graph import kg

ROLES = ('Vendor master coordinator', 'Accounts payable specialist', 'Controller')


def process(name, steps=16, system='LedgerLoom', statement='We onboard a vendor.', **extra):
    """A fully described process: every step names a role, the system, an input and an output."""
    listed = [{'id': f'S{n}', 'title': f'{name} step {n}', 'type': 'decision' if n % 5 == 0 else 'activity',
               'actor': ROLES[n % 3], 'system': system, 'input': f'Work item {n}', 'output': f'Work item {n + 1}',
               'evidence_turns': [f'u{n}']} for n in range(1, steps + 1)]
    return {'context': {'process_name': name}, 'team': 'Finance operations', 'scope': 'Fund A',
            'turns': [{'id': f'u{n}', 'role': 'user', 'text': f'{statement} Step {n}.'} for n in range(1, steps + 1)],
            'draft': {'title': name, 'inputs': ['Work item 1'], 'outputs': [f'Work item {steps + 1}'], 'steps': listed,
                      'connections': [{'from': f'S{n}', 'to': f'S{n + 1}', 'evidence_turns': [f'u{n}']} for n in range(1, steps)]}, **extra}


class EntityDedupeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def records(self, receipt):
        mine = lambda item: item['submission_id'] == receipt['submission_id'] and item['revision'] == receipt['revision']
        return [e for e in rows.entities(self.graph) if mine(e)], [e for e in rows.edges(self.graph) if mine(e)]

    def labels(self, entities, kind):
        return sorted(e['label'] for e in entities if e['type'] == kind)

    def test_a_system_and_a_role_named_by_many_steps_are_one_entity_each(self):
        entities, edges = self.records(self.graph.submit(process('Vendor onboarding')))
        self.assertEqual(self.labels(entities, 'system'), ['LedgerLoom'])
        self.assertEqual(self.labels(entities, 'role'), sorted(ROLES))
        # The output of one step is the input of the next: 17 work items, not 32.
        self.assertEqual(len(self.labels(entities, 'business_object')), 17)
        self.assertEqual(len(entities), 2 + 1 + 1 + 16 + 3 + 1 + 17)

    def test_each_mention_keeps_its_own_edge_and_evidence(self):
        entities, edges = self.records(self.graph.submit(process('Vendor onboarding')))
        system = next(e for e in entities if e['type'] == 'system')
        uses = [e for e in edges if e['target'] == system['id']]
        self.assertEqual({e['type'] for e in uses}, {'uses_system'})
        self.assertEqual(sorted((e['evidence']['step_id'], tuple(e['evidence']['evidence_turns'])) for e in uses),
                         sorted((f'S{n}', (f'u{n}',)) for n in range(1, 17)))
        steps = {e['id'] for e in entities if e['type'] in ('step', 'decision')}
        self.assertEqual({e['source'] for e in uses}, steps, 'Every step keeps its own link to the shared system')
        # A work item that one step produces and the next consumes: one entity, both relationships.
        item = next(e for e in entities if e['label'] == 'Work item 2')
        self.assertEqual(sorted(e['type'] for e in edges if e['target'] == item['id']), ['consumes', 'produces'])
        # The process-level input is the same object as the first step's input.
        first = next(e for e in entities if e['label'] == 'Work item 1')
        version = next(e for e in entities if e['type'] == 'process_version')
        self.assertEqual(sorted(e['source'] in steps for e in edges if e['target'] == first['id']), [False, True])
        self.assertTrue(any(e['source'] == version['id'] and e['target'] == first['id'] for e in edges))

    def test_mentions_match_on_type_and_case_folded_label_only(self):
        body = process('Reconciliation', steps=4)
        for step, (actor, system) in zip(body['draft']['steps'], (('Analyst', 'Ledger'), (' analyst ', 'LEDGER'), ('Ledger', 'ledger'), ('Senior analyst', 'Ledger 2'))):
            step.update(actor=actor, system=system)
        entities, edges = self.records(self.graph.submit(body))
        self.assertEqual(self.labels(entities, 'role'), ['Analyst', 'Ledger', 'Senior analyst'], 'The first spelling is kept; a longer name is another role')
        self.assertEqual(self.labels(entities, 'system'), ['Ledger', 'Ledger 2'], 'A role and a system of the same name stay apart')
        ledger = next(e for e in entities if e['type'] == 'system' and e['label'] == 'Ledger')
        self.assertEqual(len([e for e in edges if e['target'] == ledger['id']]), 3)

    def test_placeholders_still_create_nothing(self):
        body = process('Reconciliation', steps=3)
        for step, value in zip(body['draft']['steps'], ('UNKNOWN', 'n/a', '')):
            step.update(actor=value, system=value)
        entities, _ = self.records(self.graph.submit(body))
        self.assertEqual(self.labels(entities, 'role') + self.labels(entities, 'system'), [])

    def test_revisions_and_processes_keep_their_own_entities(self):
        first = self.graph.submit(process('Vendor onboarding'))
        other = self.graph.submit(process('Payment run', steps=10))
        revised = self.graph.submit(process('Vendor onboarding', process_id=first['process_id']))
        systems = [e for e in rows.entities(self.graph) if e['type'] == 'system']
        self.assertEqual(sorted((e['submission_id'] == other['submission_id'], e['revision']) for e in systems), [(False, 1), (False, 2), (True, 1)])
        self.assertEqual(revised['revision'], 2)

if __name__ == '__main__':
    unittest.main()
