"""001c-03 behavior tests, isolated synthetic queues; never contacts EA."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.watched_bulk_v1.validation import assess,validate_projection
from experiments.watched_bulk_v1.contract import to_snapshot,refresh_cost
from experiments.watched_bulk_v1.server import Server,EXTENSION_ID
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.bidding_v1.contracts import Balance,State


def probe(count=0):
    v=json.loads((ROOT/'docs/research/001c/001c-03/watched-3.json').read_text())
    v['auctions']=[{'trade_id':f'trade:{n+1:024x}','item_id':f'item:{n+1:024x}','definition_id':123,
                   'starting_bid':150,'current_bid':150,'buy_now_price':20000,'expires':100-n,
                   'trade_state':'active','bid_state':'highest' if n%2 else 'outbid'} for n in range(count)]
    v['account']['cached_count_after']=count
    return v


class Behavior(unittest.TestCase):
    def test_native_JS_network_cache_privacy_schema_and_50_rows(self):
        r=subprocess.run(['node','tests/watched_bulk_v1_checks.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_fresh_empty_requires_network_persona_and_visible_comparison(self):
        v=probe()
        self.assertTrue(assess(v,0)['empty_verified'])
        self.assertFalse(assess(v)['empty_verified'])
        for change in ('cache','failure','route','auth','ended','persona','split','repo','timestamp'):
            p=deepcopy(v)
            if change=='cache':
                p.update(status=304,network=[],request_count=0,network_at=None)
            if change=='failure':p.update(success=False,error='service_failed')
            if change=='route':p['network'][0]['route']='/ut/game/fc27/:unrecognized'
            if change=='auth':p['network'][0]['session_header_present']=False
            if change=='ended':p['network'][0]['ended_at']=None
            if change=='persona':p['persona']=None
            if change=='split':p['account']['platform_split']=True
            if change=='repo':p['account']['cached_count_after']=3
            if change=='timestamp':p['network_at']='2020-01-01T00:00:00Z'
            self.assertFalse(assess(p,0)['empty_verified'],change)

    def test_schema_rejects_extra_fields_raw_identity_and_sensitive_metadata(self):
        v=probe(1)
        for change in ('extra','raw','header','count'):
            p=deepcopy(v)
            if change=='extra':p['cookies']='bad'
            if change=='raw':p['auctions'][0]['trade_id']='123456789'
            if change=='header':p['network'][0]['headers']={'Authorization':'bad'}
            if change=='count':p['request_count']=50
            with self.assertRaises(ValueError,msg=change):validate_projection(p)

    def test_50_queue_dedup_conflict_missing_expiry_and_deadline_order(self):
        fixture=json.loads((ROOT/'experiments/watched_bulk_v1/fixtures/watched-50.json').read_text())
        self.assertEqual(fixture['classification'],'OFFLINE_VALIDATED')
        v=fixture['sample'];snapshot=to_snapshot(v,'a'*32,fixture=True)
        now=datetime.fromisoformat(v['observed_at'])
        q=AuctionQueue()
        # Enrollment is an offline setup; observed statuses include leading/outbid.
        for row in snapshot.auctions:
            q.entries[row.identity.trade_id]=row;q.identities[row.identity.trade_id]=row.identity
        begin=time.perf_counter()
        result=q.refresh(snapshot,now=now)
        self.assertEqual(len(result),50)
        self.assertEqual(sum(state==State.LEADING for state in result.values()),25)
        self.assertEqual(sum(state==State.OUTBID for state in result.values()),25)
        ordered=q.deadlines()
        self.assertEqual(len(ordered),50)
        self.assertLess(ordered[0].deadline,ordered[-1].deadline)
        elapsed=time.perf_counter()-begin
        self.assertLess(elapsed,1,'local processing only, not EA latency')
        print(json.dumps({'fixture_rows':50,'local_ingestion_and_ordering_ms':round(elapsed*1000,4),'live_performance':False}))
        v['auctions']+=deepcopy(v['auctions'][:1])
        self.assertEqual(len(q.refresh(to_snapshot(v,'b'*32,fixture=True),now=now)),50)
        v['auctions'][-1]['current_bid']=200
        r=q.refresh(to_snapshot(v,'c'*32,fixture=True),now=now)
        self.assertEqual(r['trade:'+f'{1:024x}'],State.UNKNOWN)
        missing=probe()
        r=q.refresh(to_snapshot(missing,'d'*32,fixture=True),now=now)
        self.assertTrue(all(state==State.UNKNOWN for state in r.values()))
        self.assertEqual(len(q.entries),50)
        for a in v['auctions']:
            a['trade_state']='expired';a['expires']=-1
        r=q.refresh(to_snapshot(v,'e'*32,fixture=True),now=now)
        self.assertTrue(all(state in (State.UNKNOWN,State.PENDING) for state in r.values()))
        self.assertEqual(len(q.entries),50,'unverified terminal states cannot free slots')

    def test_capacity_is_independent_of_configured_queue_and_cached_status_unknown(self):
        v=probe(1);v['account'].update(inbox_capacity=30,server_setting_capacity=30)
        s=to_snapshot(v,'a'*32,fixture=True)
        self.assertEqual(s.coverage.account_capacity,30)
        self.assertFalse(s.coverage.complete)
        q=AuctionQueue();now=s.freshness.observed_at;b=Balance(50000,None,s.freshness)
        for n in range(31):
            p=probe(1);p['auctions'][0].update(trade_id=f'trade:{n+1:024x}',item_id=f'item:{n+1:024x}')
            row=to_snapshot(p,f'{n+1:032x}',fixture=True).auctions[0]
            self.assertEqual(q.admit(row,b,150,now=now,account_capacity=30),'ENROLLED' if n<30 else 'QUEUE_FULL')
        v.update(status=304,network=[],network_at=None,request_count=0)
        self.assertEqual(to_snapshot(v,'b'*32,fixture=True).auctions[0].state,State.UNKNOWN)

    def test_request_cost_and_25_seconds_remain_bounded_extrapolation(self):
        r=refresh_cost([probe()])
        self.assertEqual(r['native_requests_per_sample'],[1])
        self.assertEqual(r['observed_queue_sizes'],[0])
        self.assertFalse(r['live_50_verified'])
        self.assertFalse(r['sustained_25_second_cycle_verified'])
        self.assertEqual(r['configured_queue_size'],50)

    def test_pinned_loopback_server_denies_other_origins_writes_and_budget_reset(self):
        with tempfile.TemporaryDirectory() as d:
            budget=Path(d)/'budget.json';budget.write_text(json.dumps({'consumed':6}))
            s=Server(0,budget);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
            self.addCleanup(s.server_close);self.addCleanup(s.shutdown)
            base=f'http://127.0.0.1:{s.server_port}'
            def post(path,payload,origin=None):
                h={'Content-Type':'application/json'}
                if origin:h['Origin']=origin
                return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(payload).encode(),headers=h),timeout=3)
            for path,value,origin,code in [('/next',{},'chrome-extension://'+'a'*32,403),('/run',{'operation':'bid','evidence_key':'a'*32},None,400),('/run',{'operation':'watched','evidence_key':'a'*32},'https://ea.com',403)]:
                with self.assertRaises(urllib.error.HTTPError) as cm:post(path,value,origin)
                self.assertEqual(cm.exception.code,code)
            with post('/next',{},'chrome-extension://'+EXTENSION_ID) as r:self.assertIsNone(json.load(r))
            with self.assertRaises(urllib.error.HTTPError) as cm:post('/run',{'operation':'watched','evidence_key':'a'*32})
            self.assertEqual(cm.exception.code,409)
            self.assertIn('experiment_budget_exhausted',cm.exception.read().decode())
            self.assertEqual(s.calls,6)


if __name__=='__main__':
    unittest.main(verbosity=2)
