"""One entity per role, system or business object named in a revision (live-draft-knowledge-7).

Every step used to create its own role, system, input and output entity, so a system appeared once
per step, a 16-step process could not be graphed at 'All entities', and a reviewed group needed one
selection per duplicate. Temporary SQLite; no analyzer, provider or network.
"""
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
        snapshot = self.graph.admin_snapshot()
        mine = lambda item: item['submission_id'] == receipt['submission_id'] and item['revision'] == receipt['revision']
        return [e for e in snapshot['entities'] if mine(e)], [e for e in snapshot['edges'] if mine(e)]

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
        systems = [e for e in self.graph.admin_snapshot()['entities'] if e['type'] == 'system']
        self.assertEqual(sorted((e['submission_id'] == other['submission_id'], e['revision']) for e in systems), [(False, 1), (False, 2), (True, 1)])
        self.assertEqual(revised['revision'], 2)

    def test_all_entities_of_a_16_step_process_can_be_graphed(self):
        receipt = self.graph.submit(process('Vendor onboarding'))
        graph = self.graph.admin_graph(level='all', submission_id=receipt['submission_id'])
        self.assertFalse(graph['too_large'], graph['message'])
        self.assertEqual(graph['counts']['nodes'], 41)
        self.assertEqual(len([e for e in graph['edges'] if e['type'] == 'uses_system']), 16)
        # Two such processes are still one view of at most 80 entities each; together they need a selection.
        self.graph.submit(process('Payment run'))
        self.assertTrue(self.graph.admin_graph(level='all')['too_large'])
        narrowed = self.graph.admin_graph({'type': 'system'}, level='all')
        self.assertEqual(sorted(e['label'] for e in narrowed['entities']), ['LedgerLoom', 'LedgerLoom'])
        named = self.graph.admin_graph({'query': 'payment run step 1'}, level='all')
        self.assertFalse(named['too_large'])
        self.assertTrue(named['entities'] and all('payment run step 1' in e['label'].lower() for e in named['entities']))

    def test_one_selection_per_process_groups_a_shared_system(self):
        self.graph.submit(process('Vendor onboarding', steps=12))
        self.graph.submit(process('Payment run', steps=10))
        systems = self.graph.admin_browse('entities', {'type': 'system', 'latest_only': True})['items']
        self.assertEqual(len(systems), 2, 'One LedgerLoom per process, not one per step')
        group = self.graph.canonical_create('LedgerLoom', [item['id'] for item in systems], 'reviewer', 'Same system in both processes')
        self.assertEqual(len(group['members']), 2)

    def test_entity_records_say_which_process_and_steps_they_come_from(self):
        self.graph.submit(process('Vendor onboarding', steps=12))
        self.graph.submit(process('Payment run', steps=1))
        systems = {item['process_name']: item for item in self.graph.admin_browse('entities', {'type': 'system'})['items']}
        self.assertEqual(set(systems), {'Vendor onboarding', 'Payment run'})
        self.assertEqual((systems['Vendor onboarding']['step_count'], systems['Payment run']['step_count']), (12, 1))
        self.assertEqual(systems['Payment run']['step_label'], 'Payment run step 1')
        step = self.graph.admin_browse('entities', {'type': 'step', 'query': 'Payment run step 1'})['items'][0]
        self.assertEqual((step['process_name'], step['step_count'], step['step_label']), ('Payment run', 0, None))
        group = self.graph.canonical_create('LedgerLoom', [item['id'] for item in systems.values()], 'reviewer', 'Same system')
        members = self.graph.admin_history('group_members', group['id'])['items']
        self.assertEqual({item['process_name'] for item in members}, {'Vendor onboarding', 'Payment run'})


class ReplaceOutdatedMembersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.graph = kg.KnowledgeGraph(Path(self.temp.name) / 'graph.db')
        self.first = self.graph.submit(process('Vendor onboarding', steps=4))
        self.other = self.graph.submit(process('Payment run', steps=3))
        self.group = self.graph.canonical_create('LedgerLoom', self.ids('system'), 'reviewer', 'Same system')

    def tearDown(self):
        self.graph.close()
        self.temp.cleanup()

    def ids(self, kind, **filters):
        return [item['id'] for item in self.graph.admin_browse('entities', {'type': kind, 'latest_only': True, **filters})['items']]

    def revise(self, **changes):
        return self.graph.submit(process('Vendor onboarding', steps=4, process_id=self.first['process_id'], **changes))

    def state(self):
        return next(g for g in self.graph.admin_snapshot()['canonical_groups'] if g['id'] == self.group['id'])

    def update(self, action, value='reviewed'):
        return self.graph.canonical_update(self.group['id'], action, value, 'reviewer', 'After the revision', self.state()['review_version'], bounded_result=True)

    def test_outdated_member_is_replaced_by_the_same_entity_of_the_latest_revision(self):
        before = set(self.state()['members'])
        self.revise()
        self.assertEqual(self.state()['status'], 'stale')
        with self.assertRaisesRegex(ValueError, 'Remove outdated members'):
            self.update('revalidate')
        result = self.update('replace_outdated')
        self.assertEqual((result['replaced'], result['left_outdated'], result['member_count']), (1, 0, 2))
        after = set(self.state()['members'])
        self.assertEqual(after, set(self.ids('system')), 'Both members are entities of the latest revisions')
        self.assertEqual(len(after & before), 1, 'The member of the unrevised process is untouched')
        state = self.state()
        self.assertEqual(state['status'], 'stale', 'Replacing prepares the review; revalidating is the review')
        self.assertEqual(state['history'][-1]['action'], 'replace_outdated')
        self.assertEqual(self.update('revalidate')['status'], 'active')

    def test_duplicates_from_a_revision_filed_before_this_fix_collapse_into_the_one_successor(self):
        # A revision stored by an earlier build: one system entity per step, all of them members.
        old = self.ids('system', submission_id=self.first['submission_id'])[0]
        with self.graph.db:
            for n in range(3):
                duplicate = kg.new_id()
                self.graph.db.execute('INSERT INTO entities VALUES (?,?,?,?,?,?)', (duplicate, self.first['submission_id'], 1, 'system', 'LedgerLoom', '{}'))
                self.graph.db.execute('INSERT INTO canonical_members VALUES (?,?)', (self.group['id'], duplicate))
        self.assertEqual(len(self.state()['members']), 5)
        self.revise()
        result = self.update('replace_outdated')
        self.assertEqual((result['replaced'], result['left_outdated'], result['member_count']), (4, 0, 2))
        self.assertNotIn(old, self.state()['members'])

    def test_a_member_without_one_clear_successor_is_left_for_the_administrator(self):
        self.revise(system='LedgerLoom Cloud')  # The revision names another system.
        with self.assertRaisesRegex(ValueError, 'No outdated member has exactly one entity'):
            self.update('replace_outdated')
        state = self.state()
        self.assertEqual(len(state['members']), 2, 'Nothing changed')
        self.assertNotEqual(state['history'][-1]['action'], 'replace_outdated')

    def test_a_successor_that_belongs_to_another_group_is_not_taken(self):
        self.revise()
        latest = self.ids('system', submission_id=self.first['submission_id'])
        roles = self.ids('role', submission_id=self.other['submission_id'])
        with self.graph.db:  # The latest LedgerLoom already sits in another reviewed group.
            self.graph.db.execute("INSERT INTO canonical_groups(id,label,type,review_version,created_at) VALUES ('other','Other','system',1,?)", (kg.now(),))
            self.graph.db.execute("INSERT INTO canonical_members VALUES ('other',?)", (latest[0],))
        self.assertTrue(roles)
        with self.assertRaisesRegex(ValueError, 'No outdated member'):
            self.update('replace_outdated')

    def test_steps_with_equal_titles_are_ambiguous_and_stay(self):
        steps = self.ids('step', submission_id=self.first['submission_id'])[:1] + self.ids('step', submission_id=self.other['submission_id'])[:1]
        group = self.graph.canonical_create('Shared step', steps, 'reviewer', 'Same activity')
        body = process('Vendor onboarding', steps=4, process_id=self.first['process_id'])
        for step in body['draft']['steps']:
            step['title'] = 'Vendor onboarding step 1'  # Four steps now carry the member's title.
        self.graph.submit(body)
        version = next(g for g in self.graph.admin_snapshot()['canonical_groups'] if g['id'] == group['id'])['review_version']
        with self.assertRaisesRegex(ValueError, 'No outdated member has exactly one entity'):
            self.graph.canonical_update(group['id'], 'replace_outdated', 'reviewed', 'reviewer', 'After the revision', version)


if __name__ == '__main__':
    unittest.main()
