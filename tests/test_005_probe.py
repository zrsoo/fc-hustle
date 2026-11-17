"""Finite native experiment dispatch bounds; fake transport, no EA or browser."""
from pathlib import Path
import sys
import tempfile
import json
from copy import deepcopy
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from probe_005_bid import Bounded,FreshProbeController
from fc_access.controller_v1.semantic import SemanticHealth
from controller_policy_fixture import Harness


class ProbeBounds(unittest.TestCase):
    def test_pre_burst_missing_expired_and_over_cap_rows_do_not_authorize_writes(self):
        for mode in ('missing','expired','over_cap'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as path:
                h=Harness(path,2)
                try:
                    def change(c):
                        if c['operation']=='status_batch' and not h.calls('bid'):
                            if mode=='missing':h.ea.missing.add(h.ea.rows[0]['trade_id'])
                            elif mode=='expired':h.ea.rows[0]['expires']=60
                            else:h.ea.rows[0]['current_bid']=12000
                    h.ea.on_request=change;h.controller.step()
                    self.assertEqual(len(h.calls('bid')),1)
                    self.assertNotEqual(h.calls('bid')[0]['command']['params']['target']['trade_id'],h.ea.rows[0]['trade_id'])
                    self.assertEqual(len(h.calls('balance')),1)
                finally:h.close()

    def test_fresh_status_changes_only_the_minimum_and_keeps_quote_and_one_entry_read(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1);records=[]
            try:
                h.controller.__class__=FreshProbeController
                h.controller.probe_record=lambda kind,**fields:records.append((kind,deepcopy(fields)))
                def compete(c):
                    if c['operation']=='status_batch' and not h.calls('bid'):h.ea.rows[0]['current_bid']=800
                h.ea.on_request=compete
                h.controller.step()
                attempts=h.attempts();self.assertEqual(len(attempts),1)
                self.assertEqual(attempts[0]['body']['params']['amount'],850)
                selected=records[0][1];old,new=selected['before'][0],selected['after'][0]
                self.assertEqual(old['cap'],new['cap']);self.assertEqual(old['quote'],new['quote'])
                self.assertEqual(old['resale_price'],new['resale_price'])
                self.assertNotEqual(old['read_id'],new['read_id']);self.assertGreater(new['selection_remaining'],60)
                self.assertEqual(len(h.calls('balance')),1);self.assertEqual(len(h.calls('bid')),1)
                self.assertEqual(len([x for x in h.calls('search') if x['command']['params']['purpose']=='discovery']),1)
                self.assertEqual(len(h.controller.journal.members()),1)
            finally:h.close()

    def test_callback_failure_latches_admission_and_sends_only_exception_type(self):
        from test_controller_watchdog import PipeFixture
        from fc_access.controller_v1.watchdog import Supervision,SupervisionLost
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1);pipe=PipeFixture();s=Supervision(pipe,clock=h.clock.clock)
            try:
                def broken(*args):raise ValueError('SECRET_CANARY')
                h.executor.result=broken;h.executor.failure=s.failure
                with self.assertRaises(ValueError):h.adapter.read(h.ids(),'balance')
                with self.assertRaisesRegex(RuntimeError,'RESULT_MONITOR_FAILED'):h.adapter.read(h.ids(),'balance')
                with self.assertRaises(SupervisionLost):s.require()
                self.assertEqual(len(h.calls('balance')),1)
                self.assertEqual(pipe.sent[-1]['reason'],'RESULT_MONITOR_FAILED')
                self.assertNotIn('CANARY',json.dumps(pipe.sent))
            finally:h.close()

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
