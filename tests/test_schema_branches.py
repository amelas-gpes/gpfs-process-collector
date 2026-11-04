"""Local validation enforces the same permitted branches as strict outputs."""
import unittest
from test_server import server


class SchemaBranchesTests(unittest.TestCase):
    def setUp(self):
        self.schema={'anyOf':[
            server.obj({'op':{'type':'string','enum':['add']},
                        'target':{'type':'string','enum':['']}}),
            server.obj({'op':{'type':'string','enum':['replace']},
                        'target':{'type':'string','enum':['fact_known']}}),
        ]}

    def test_each_allowed_combination_passes(self):
        for value in ({'op':'add','target':''},{'op':'replace','target':'fact_known'}):
            server.check_schema(value,self.schema)

    def test_crossed_combinations_or_unknown_targets_reject(self):
        for value in ({'op':'add','target':'fact_known'}, {'op':'replace','target':''},
                      {'op':'replace','target':'fabricated'}, {'op':'add'},
                      {'op':'add','target':'','extra':True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.check_schema(value,self.schema)

    def test_nested_branch_in_array_validates_every_item(self):
        schema=server.obj({'operations':{'type':'array','items':self.schema}})
        server.check_schema({'operations':[{'op':'add','target':''}]},schema)
        with self.assertRaises(ValueError):
            server.check_schema({'operations':[{'op':'add','target':''},
                                               {'op':'replace','target':'unknown'}]},schema)
