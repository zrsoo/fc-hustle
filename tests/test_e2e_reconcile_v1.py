"""Read-only continuation guards; never dispatches account commands."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.e2e_reconcile_v1.server import Ledger,validate_result
from fc_access.e2e_resolution_v2.server import Ledger as ResolutionLedger

class LedgerTests(unittest.TestCase):
    ledger_type=Ledger
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'run.sqlite';self.now=[1000.];self.l=self.ledger_type(self.path,now=lambda:self.now[0])
    def tearDown(self):self.l.db.close();self.temp.cleanup()
    def test_all_mutations_denied_and_not_reserved(self):
        for op in ('bid','move','list','relist','buy','unknown'):
            with self.subTest(op=op),self.assertRaises(ValueError):self.l.reserve(op)
        self.assertEqual(self.l.health()['commands_reserved'],0)
    def test_serialization_once_only_and_restart_does_not_reset(self):
        self.l.reserve('status')
        with self.assertRaises(ValueError):self.l.reserve('watched')
        self.assertEqual(self.l.claim()['operation'],'status');self.assertIsNone(self.l.claim())
        deadline=self.l.health()['deadline'];self.l.db.close();self.l=self.ledger_type(self.path,now=lambda:self.now[0])
        self.assertTrue(self.l.health()['stopped']);self.assertEqual(self.l.health()['deadline'],deadline)
        self.assertIsNone(self.l.claim())
    def test_four_reads_and_deadline_are_finite(self):
        for op in ('status','watched','unassigned','balance'):
            self.l.reserve(op);self.l.claim();self.l.db.execute("UPDATE commands SET state='OBSERVED'")
        with self.assertRaises(ValueError):self.l.reserve('watched')
        self.assertEqual(self.l.health()['commands_reserved'],4)
        self.now[0]+=121;self.assertTrue(self.l.health()['expired'])

class ResolutionLedgerTests(LedgerTests):
    ledger_type=ResolutionLedger

if __name__=='__main__':unittest.main(verbosity=2)
