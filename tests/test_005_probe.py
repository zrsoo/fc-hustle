"""Finite native experiment dispatch bounds; fake transport, no EA or browser."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from probe_005_bid import Bounded
from fc_access.controller_v1.semantic import SemanticHealth


class ProbeBounds(unittest.TestCase):
    def fixture(self):
        records=[]
        class Edge:
            def execute(self,c):records.append(('sent',c));return {'fixture':True}
        clock=[0.]
        probe=Bounded(Edge(),lambda kind,**fields:records.append((kind,fields)),SemanticHealth(clock=lambda:clock[0]),clock=lambda:clock[0])
        return probe,records,clock

    def test_one_mutation_is_reserved_before_delivery_and_cannot_be_replayed(self):
        probe,records,_=self.fixture();c={'operation':'bid','id':'a'*32}
        self.assertEqual(probe.execute(c),{'fixture':True})
        self.assertEqual(records[0][0],'RESERVED_BEFORE_DELIVERY');self.assertEqual(records[1],('sent',c))
        with self.assertRaises(ValueError):probe.execute(c)
        self.assertEqual(probe.mutations,1);self.assertEqual(len([x for x in records if x[0]=='sent']),1)

    def test_other_mutations_timeout_budget_and_semantic_fault_never_enter_transport(self):
        for operation in ('move','list','clear_sold','relist_all'):
            probe,records,_=self.fixture()
            with self.assertRaises(ValueError):probe.execute({'operation':operation})
            self.assertEqual(records,[])
        for mode in ('time','requests','commands','semantic'):
            probe,records,clock=self.fixture()
            if mode=='time':clock[0]=901
            elif mode=='requests':probe.reserved_ea=96
            elif mode=='commands':probe.commands=1024
            else:probe.semantic.reason='PERSISTENT_AUTH_FAILURE'
            with self.assertRaises(ValueError):probe.execute({'operation':'balance'})
            self.assertEqual(records,[])


if __name__=='__main__':unittest.main(verbosity=2)
