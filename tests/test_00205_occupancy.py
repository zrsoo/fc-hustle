"""002-05 behavioral acceptance. Synthetic native calls only; no account writes.

Run independently: python tests/test_00205_occupancy.py
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from actors_fixture import create, auction
from fc_access.actors_v1.actors import Acquirer, Bidder
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.occupancy import assess
from fc_access.actors_v1.native import Mailbox, Broker
from fc_access.actors_v1.operator import inspect
from fc_access.production_v1.contracts import stamp


class OccupancyAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'samples.json'
            run=subprocess.run(['node','tests/occupancy_native_checks.cjs',str(path)],
                cwd=ROOT,capture_output=True,text=True,timeout=40)
            if run.returncode: raise AssertionError(run.stdout+run.stderr)
            cls.samples=json.loads(path.read_text())

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)

    def api(self, **settings):
        f,p,c=create(self.path)
        self.addCleanup(p.close);self.addCleanup(f.close)
        cfg=Config(**settings)
        return f,p,c,Acquirer(f,cfg),Bidder(f,cfg)

    @staticmethod
    def entries(n):
        rows=[auction(123,15000,100+i) for i in range(n)]
        for i,row in enumerate(rows):
            row.update(trade_state=['active','expired','closed','inactive',None][i%5],
                bid_state='sold' if i%5==2 else 'none',expires=300 if i%5==0 else -1)
            if i%5==3: row['trade_id']='trade:'+'0'*24
        return rows

    @staticmethod
    def evidence(f):
        return [e for e in f.registry.events() if e['kind']=='ACTOR' and 'occupancy' in e][-1]

    def test_c0_c2_native_counts_every_physical_entry_and_separate_limit(self):
        for sample in self.samples:
            if not sample['name'].startswith('complete-'): continue
            n=int(sample['name'].split('-')[1])
            e=assess(sample['response'],sample['command'],now=stamp(sample['now']),source='native')
            self.assertEqual(e['occupied'],n,sample['name'])
            self.assertEqual(e['enrollment_allowed'],n<50)
            self.assertEqual(e['limit'],50)
            self.assertEqual(e['read_id'],sample['command']['id'])
        self.assertEqual(Config().max_transfer_list_occupied,50)
        self.assertEqual(Config(max_enrolled_auctions=1).max_transfer_list_occupied,50)
        self.assertEqual(Config(max_transfer_list_occupied=10).max_enrolled_auctions,50)
        for limit in [0,51,True,1.5]:
            with self.assertRaises(ValueError): Config(max_transfer_list_occupied=limit)

    def test_c1_native_incomplete_conflicting_and_unknown_reads_fail_closed(self):
        for sample in self.samples:
            if sample['name'].startswith('complete-'): continue
            with self.subTest(name=sample['name']):
                e=assess(sample['response'],sample['command'],now=stamp(sample['now']),source='native')
                self.assertFalse(e['enrollment_allowed'])
                self.assertIsNone(e['occupied'])
                self.assertIn(e['reason'],{'TRANSFER_LIST_UNKNOWN','TRANSFER_LIST_TRUNCATED',
                    'TRANSFER_LIST_CONFLICT','TRANSFER_LIST_STALE'})
                if sample['response']['result']['success']:
                    self.assertEqual(e['reason'],sample['response']['coverage']['transfer_list']['reason'])

    def test_c0_c1_inactive_sentinels_count_but_duplicate_physical_items_conflict(self):
        f,p,c,a,b=self.api()
        p.transfer_items=self.entries(5)
        for row in p.transfer_items:
            row.update(trade_state='inactive',trade_id='trade:'+'0'*24)
        from fc_access.actors_v1.occupancy import read
        self.assertEqual(read(f)['occupied'],5)
        p.transfer_items[0]['trade_state']=None
        self.assertEqual(read(f)['occupied'],5)
        p.transfer_items[1]['trade_state']='active'
        p.transfer_items[2]['trade_state']='active'
        self.assertEqual(read(f)['reason'],'TRANSFER_LIST_CONFLICT')
        self.assertFalse(read(f)['enrollment_allowed'])

    def test_c1_freshness_boundary_cache_only_forged_coverage_and_correlation(self):
        sample=next(x for x in self.samples if x['name']=='complete-5')
        v,c=sample['response'],sample['command']
        network=stamp(v['freshness']['network_at'])
        self.assertTrue(assess(v,c,now=network+timedelta(seconds=30),source='native')['enrollment_allowed'])
        for seconds in [-1,30.001,60]:
            e=assess(v,c,now=network+timedelta(seconds=seconds),source='native')
            self.assertFalse(e['enrollment_allowed']);self.assertEqual(e['reason'],'TRANSFER_LIST_STALE')
        changes=[lambda x:x['coverage']['transfer_list'].update(wire_count=6),
            lambda x:x['coverage'].update(has_more=True),
            lambda x:x['coverage']['transfer_list'].update(repository_end_of_list=False),
            lambda x:x.update(coverage=dict(complete=True,has_more=False)),
            lambda x:x['result'].update(cache_invalidated=False),
            lambda x:x['result']['network'][0].update(session_header_present=False),
            lambda x:x['fences'].update(epoch=2),
            lambda x:x['context'].update(account='f'*32),
            lambda x:x['result']['auctions'].append(deepcopy(x['result']['auctions'][0]))]
        for change in changes:
            bad=deepcopy(v);change(bad)
            self.assertFalse(assess(bad,c,now=stamp(sample['now']),source='native')['enrollment_allowed'])
        legacy=deepcopy(v);legacy['coverage']=dict(complete=False,has_more=False)
        self.assertEqual(assess(legacy,c,now=stamp(sample['now']),source='native')['reason'],'TRANSFER_LIST_UNKNOWN')

    def test_c0_c2_c3_acquirer_manual_all_states_full_and_over_cap_no_deletion(self):
        f,p,c,a,b=self.api()
        p.transfer_items=self.entries(75)  # None were enrolled by this system.
        original=deepcopy(p.transfer_items)
        for count,reason in [(75,'TRANSFER_LIST_OVER_CAP'),(50,'TRANSFER_LIST_FULL')]:
            p.transfer_items=original[:count]
            a.cycle()
            self.assertEqual(p.bid_calls,0);self.assertEqual(len(f.queue.entries),0)
            e=self.evidence(f)
            self.assertEqual((e['reason'],e['occupancy']['occupied']),(reason,count))
            self.assertEqual(p.transfer_items,original[:count])
            self.assertEqual(e['action'],'HOLD')
        p.transfer_items=original[:49]
        a.cycle();self.assertEqual(p.bid_calls,1)
        self.assertEqual(self.evidence(f)['occupancy']['occupied'],49)
        self.assertEqual(len([x for x in p.calls if x['operation']=='transfer_list']),4)
        self.assertEqual(set(x['operation'] for x in p.calls)-{'search','caps','price_helpers','balance','transfer_list','bid'},set())

    def test_c1_c3_acquirer_pauses_reason_coded_then_requires_new_read(self):
        f,p,c,a,b=self.api()
        p.transfer_items=self.entries(5)
        for reason in ['TRANSFER_LIST_UNKNOWN','TRANSFER_LIST_TRUNCATED','TRANSFER_LIST_CONFLICT']:
            p.transfer_coverage=dict(complete=False,has_more=None,transfer_list=dict(reason=reason,
                wire_count=5,callback_count=5,repository_count=5,repository_end_of_list=False))
            a.cycle();self.assertEqual(p.bid_calls,0)
            self.assertEqual(self.evidence(f)['reason'],reason)
            self.assertEqual(f.queue.entries,{})
        p.transfer_coverage=None
        a.cycle();self.assertEqual(p.bid_calls,1)
        self.assertEqual(len([x for x in p.calls if x['operation']=='transfer_list']),5)

    def test_c1_c3_stale_and_transport_failure_pause_with_durable_evidence(self):
        f,p,c,a,b=self.api()
        original=p.project_response
        def stale(command,value):
            value=original(command,value)
            if command['operation']=='transfer_list':
                value['result'].update(success=False,error='stale_source')
                value['coverage']=dict(complete=False,has_more=None)
            return value
        p.project_response=stale
        a.cycle();self.assertEqual(p.bid_calls,0)
        self.assertEqual(self.evidence(f)['reason'],'TRANSFER_LIST_STALE')
        original_read=f.read
        def missing(op,*args,**kwargs):
            if op=='transfer_list': raise TimeoutError('delivery_unknown_no_retry')
            return original_read(op,*args,**kwargs)
        with patch.object(f,'read',side_effect=missing):a.cycle()
        self.assertEqual(self.evidence(f)['reason'],'TRANSFER_LIST_UNKNOWN')
        self.assertEqual(p.bid_calls,0)

    def test_c2_c3_custom_occupied_limit_and_bidder_continues_at_over_cap(self):
        f,p,c,a,b=self.api(max_transfer_list_occupied=5,max_enrolled_auctions=1)
        p.transfer_items=self.entries(4)
        a.cycle();self.assertEqual(p.bid_calls,1)
        p.transfer_items=self.entries(75)
        b.cycle()  # Reconciliation and leading management do not use admission guard.
        p.candidate.update(current_bid=900,bid_state='outbid')
        p.watched=[deepcopy(p.candidate)]
        b.cycle();self.assertEqual(p.bid_calls,2)
        # Acquisition checks at cycle start and again after pricing. Bidder has
        # added no Transfer List request or capacity gate to its work.
        self.assertEqual(len([x for x in p.calls if x['operation']=='transfer_list']),2)

    def test_c1_c2_c3_operator_reports_over_cap_and_rejects_stale_restart_state(self):
        f,p,c,a,b=self.api()
        box=Mailbox(self.path/'native.sqlite3');self.addCleanup(box.close)
        Broker(box,f,a.config).initialize()
        p.transfer_items=self.entries(75);a.cycle()
        status=inspect(box.path)
        self.assertEqual(status['transfer_list_occupancy']['occupied'],75)
        self.assertFalse(status['transfer_list_occupancy']['enrollment_allowed'])
        blocked=inspect(box.path,'blocked')
        self.assertTrue(any(e.get('reason')=='TRANSFER_LIST_OVER_CAP' for e in blocked))
        with patch('fc_access.actors_v1.native.utc',return_value=c.now()+timedelta(seconds=31)):
            status=inspect(box.path)
        self.assertFalse(status['transfer_list_occupancy']['fresh'])
        self.assertEqual(status['transfer_list_occupancy']['current_reason'],'TRANSFER_LIST_STALE')
        # Operator replay is not admission authority: even a new actor needs a new read.
        a=Acquirer(f);p.transfer_items=[];a.cycle()
        self.assertEqual(p.bid_calls,1)
        self.assertEqual(len([x for x in p.calls if x['operation']=='transfer_list']),3)


if __name__=='__main__': unittest.main(verbosity=2)
