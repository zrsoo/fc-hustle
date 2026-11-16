"""Finite live harness with real production actors and explicitly synthetic EA."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from actors_fixture import create
from fc_access.actors_v1.verify_bid_receipt import Attempt,BoundedExecutor,verify


class FiniteVerification(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.path=Path(t.name)
        self.f,self.page,self.clock=create(self.path)
        self.addCleanup(self.page.close);self.addCleanup(self.f.close)
        self.attempt=Attempt(self.path/'attempt.json',source='fixture')
        self.bounded=BoundedExecutor(self.page,self.attempt,now=self.clock.now)
        self.f.executor.executor=self.bounded

    def test_real_acquirer_foundation_receipt_and_independent_readback_one_bid(self):
        verify(self.f,self.attempt)
        v=json.loads(self.attempt.path.read_text())
        self.assertEqual(v['status'],'OFFLINE_PASS');self.assertEqual(v['bids_consumed'],1)
        self.assertLessEqual(v['ea_consumed'],16);self.assertEqual(v['ea_reserved'],0)
        self.assertEqual(v['readback']['bid_state'],'highest');self.assertTrue(v['reconciled'])
        bids=[r for r in v['operations'] if r['command']['operation']=='bid']
        self.assertEqual(len(bids),1);self.assertEqual(bids[0]['response']['result']['bid_receipt']['verdict'],'ACCEPTED')
        self.assertEqual(self.page.bid_calls,1)
        self.assertFalse(any(r['command']['operation'] in {'move','list','clear_sold','relist_all'} for r in v['operations']))
        with self.assertRaises(FileExistsError):Attempt(self.attempt.path,source='fixture')
        with self.assertRaisesRegex(ValueError,'attempt_stopped'):self.bounded.execute(self.f.adapter.envelope(self.f.ids(),'balance',{}))

    def test_reserved_interrupted_operation_and_duplicate_never_replay(self):
        c=self.f.adapter.envelope(self.f.ids(),'balance',{})
        self.bounded.execute(c)
        with self.assertRaisesRegex(ValueError,'duplicate_operation'):self.bounded.execute(c)
        self.attempt.value['ea_reserved']=1;self.attempt.save()
        with self.assertRaisesRegex(ValueError,'interrupted_operation'):self.bounded.execute(self.f.adapter.envelope(self.f.ids(),'balance',{}))
        self.assertEqual(len(self.page.calls),1)

    def test_no_extra_mutations_or_budget_overrun(self):
        c=self.f.adapter.envelope(self.f.ids(),'balance',{})
        self.attempt.value['ea_consumed']=16
        with self.assertRaisesRegex(ValueError,'ea_budget_exhausted'):self.bounded.execute(c)
        self.assertFalse(self.page.calls)
        self.attempt.value['ea_consumed']=0
        c['operation']='list'
        with self.assertRaisesRegex(ValueError,'only_one_bid_authorized'):self.bounded.execute(c)
        self.assertFalse(self.page.calls)


if __name__=='__main__':unittest.main()
