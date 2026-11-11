"""T3 criteria 0..3 and 5: executable boundary/strategy/artifact checks, no EA access."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.market_discovery.discovery import Budget, Runner, decision, metrics, observations, pagination, plan, rank
from experiments.market_discovery.flow import simulated_flow
from experiments.market_discovery.model import PROTOCOL, envelope, reply, search, sources, stamp, summary
from experiments.market_discovery.replay import FixtureClock, FixtureTransport, historical
from fc_access.harness import empty_result
from fc_access.pricing import MarketKey, Rules


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.clock = FixtureClock()
        self.transport = FixtureTransport(self.clock)
        self.runner = Runner(self.transport, mode='SIMULATED', clock=self.clock)

    def record(self, params=None):
        return self.runner.read(params or plan('A',[233731,278230])[0],Budget(),'A',0,0)

    def test_strict_search_identity_sanitization_and_unavailable_sources(self):
        record = self.record()
        self.assertEqual(record['game'],'fc27')
        self.assertEqual(record['platform'],'pc')
        row = record['result']['auctions'][0]
        self.assertEqual(row['item']['definition_id'],233731)
        self.assertRegex(row['trade_id'],r'^trade:[a-f0-9]{24}$')
        self.assertRegex(row['item']['item_id'],r'^item:[a-f0-9]{24}$')
        alternate = FixtureTransport(FixtureClock()).search(record['criteria'],'f'*32)
        self.assertNotEqual(alternate['result']['auctions'][0]['trade_id'],row['trade_id'])
        self.assertFalse(sources()['external']['production_feed_retrieved'])
        self.assertEqual(sources()['external']['status'],'UNAVAILABLE')
        self.assertEqual(sources()['external']['quotes'],[])
        base = {'id':'a'*32,'evidence_key':'b'*32,'operation':'search','params':record['criteria']}
        for operation in ('buy','buyNow','bid','move','list','relist','cancel','sold_cleanup','coins','club','transfer_list','eval'):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                envelope(base | {'operation':operation})
        for params in ({'nation':46},{'rarity':1},{'position':'ST'},{'token':'secret'},{'page':3},{'count':20},{'definition_id':True},{'fresh':1},{'max_buy':-1},{'min_buy':8000}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                search(base['params'] | params)
        for modify in ('top','item','timing','platform','identity','rows','wallet'):
            value = {'result':deepcopy(record['result']),'timing':{'worker_poll_to_native_ms':1,'native_service_ms':2,'page_total_ms':3}}
            if modify == 'top': value['cookie']='secret'
            if modify == 'item': value['result']['auctions'][0]['item']['token']='secret'
            if modify == 'timing': value['timing']['native_service_ms']=float('nan')
            if modify == 'platform': value['result']['platform']='ps5'
            if modify == 'identity': value['result']['auctions'][0]['trade_id']='123456789'
            if modify == 'rows': value['result']['auctions']*=2
            if modify == 'wallet': value['result']['credits']=1234
            with self.subTest(modify=modify), self.assertRaises(ValueError): reply(value)

    def test_equal_budgets_order_ranking_and_measured_metrics(self):
        result = self.runner.run(9,paced=True)
        self.assertEqual([w['strategy'] for w in result['windows']],list('ABCBCACAB'))
        self.assertEqual(result['overall']['commands'],72)
        self.assertEqual(result['overall']['EA_requests'],72)
        for strategy in 'ABC':
            self.assertEqual(result['by_strategy'][strategy]['commands'],24)
            self.assertEqual(result['by_strategy'][strategy]['EA_requests'],24)
        self.assertEqual(len(self.transport.calls),72)
        self.assertGreater(result['overall']['unique_versions'],1)
        self.assertGreater(result['overall']['duplicate_fraction'],0)
        self.assertGreater(result['overall']['observed_seconds'],1800)
        self.assertIsNone(result['live_opportunity_yield'])
        self.assertEqual(result['overall']['candidate_yield_by_X'],{str(x):None for x in (100,250,500,1000)})
        self.assertIsNone(result['overall']['background_EA_requests'])
        self.assertTrue(all(w['budget']['requests']==8 for w in result['windows']))
        # No current-window data enters the frozen hybrid plan.
        for w in result['windows'][:3]: self.assertEqual(w['ranking'],[233731,278230])
        self.assertEqual(plan('A',[50596300])[0]['definition_id'],233731)
        self.assertEqual(plan('B',[50596300])[0]['club'],9)
        self.assertEqual(plan('C',[50596300])[2]['definition_id'],50596300)

    def test_adaptive_rank_freshness_platform_mapping_and_no_future_peeking(self):
        a = self.record({'league':13,'page':1,'count':21,'fresh':True,'max_buy':7000})
        counts = {}
        for row in a['result']['auctions']:
            counts.setdefault(row['item']['definition_id'],set()).add(row['trade_id'])
        expected = sorted(counts,key=lambda d:(-len(counts[d]),d))
        self.assertEqual(rank([a],{'status':'UNAVAILABLE'},stamp(self.clock.utc())),expected)
        q = {'game':'fc27','platform':'pc','definition_id':50596300,'price':100,'mapping_verified':True,
             'meaning':'indicative_ask','published_utc':self.clock.utc()}
        self.assertEqual(rank([a],{'status':'AVAILABLE','quotes':[q]},stamp(self.clock.utc())),[50596300])
        for change in ({'platform':'ps5'},{'game':'fc26'},{'mapping_verified':False},{'meaning':'last_sold'},
                       {'published_utc':(stamp(self.clock.utc())-timedelta(seconds=601)).isoformat()},
                       {'published_utc':(stamp(self.clock.utc())+timedelta(seconds=1)).isoformat()}):
            self.assertEqual(rank([a],{'status':'AVAILABLE','quotes':[q|change]},stamp(self.clock.utc())),expected)
        self.clock.sleep(121)
        self.assertEqual(rank([a],{'status':'UNAVAILABLE'},stamp(self.clock.utc())),[233731,278230])

    def test_errors_cache_and_native_side_effects_spend_budget(self):
        budget = Budget(2)
        r = self.record()['result']
        budget.reserve(); budget.charge(empty_result('service_timeout'))
        budget.reserve(); budget.charge(r | {'network':[]})
        self.assertEqual((budget.commands,budget.requests),(2,0))
        with self.assertRaises(ValueError): budget.reserve()
        budget = Budget(1); budget.reserve(); budget.charge(r | {'network':r['network']*2})
        self.assertTrue(budget.overrun)
        self.assertEqual(budget.requests,2)
        with self.assertRaises(ValueError): budget.reserve()
        for status in (401,403,429,503):
            class Failing(FixtureTransport):
                def search(inner,p,k):
                    v = super().search(p,k)
                    v['result'].update(status=status,success=False,error='service_failed',auctions=None)
                    v['result']['network'][0]['status']=status
                    return v
            c = FixtureClock(); t = Failing(c)
            out = Runner(t,clock=c,mode='SIMULATED').run(9,paced=True)
            self.assertEqual(len(t.calls),1)
            self.assertEqual(out['status'],'PARTIAL')
            self.assertEqual(out['overall']['EA_requests'],1)

    def test_pagination_overlap_lookahead_expiry_and_truncation(self):
        pair = [self.record(p) for p in plan('A',[233731,278230])[:2]]
        report = pagination(pair)
        self.assertEqual(report['pairs'][0]['unique_in_pair'],41)
        self.assertEqual(len(report['pairs'][0]['overlap_trade_ids']),1)
        self.assertTrue(report['pairs'][0]['lookahead_reappeared'])
        self.assertTrue(report['pages'][0]['expiry_nondecreasing'])
        self.assertFalse(report['pages'][0]['BIN_nondecreasing'])
        self.assertTrue(report['pages'][1]['truncation_possible'])
        pair[1]['result']['auctions']=pair[1]['result']['auctions'][:20]
        pair[1]['result']['has_more']=False
        self.assertTrue(pagination(pair)['pages'][1]['truncation_possible'])
        self.assertFalse(pagination(pair)['pages'][1]['exhaustive'])
        pair[1]['result']['auctions']=[]
        self.assertFalse(pagination(pair)['pages'][1]['exhaustive'])
        self.assertAlmostEqual(metrics([pair[0],pair[0]])['duplicate_fraction'],.5)

    def test_response_filter_drift_and_raw_exceptions_stop_without_leaking(self):
        for kind in ('definition','club','league','price','exception','extra_field'):
            class Drift(FixtureTransport):
                def search(inner,p,k):
                    if kind=='exception':raise RuntimeError('PRIVATE-CANARY')
                    value=super().search(p,k)
                    row=value['result']['auctions'][0]
                    if kind=='definition':row['item']['definition_id']=999
                    if kind=='club':row['item']['club']=999
                    if kind=='league':row['item']['league']=999
                    if kind=='price':row['buy_now_price']=999999
                    if kind=='extra_field':value['token']='PRIVATE-CANARY'
                    return value
            c=FixtureClock();t=Drift(c);r=Runner(t,mode='SIMULATED',clock=c)
            params=plan('A',[233731,278230])[0]|{'club':9,'league':13}
            with self.subTest(kind=kind):
                record=r.read(params,Budget(), 'A',0,0)
                self.assertEqual(record['result']['error'],'schema_unrecognized')
                self.assertFalse(record['network_fresh'])
                self.assertNotIn('PRIVATE-CANARY',json.dumps(record))

    def test_historical_artifact_recomputes_actual_42_rows_41_auctions(self):
        replay = historical()
        self.assertEqual(replay['mode'],'HISTORICAL_REPLAY')
        self.assertEqual(replay['new_live_samples'],0)
        self.assertEqual(replay['overall']['response_rows'],52)
        self.assertEqual(replay['overall']['unique_auctions'],51)
        self.assertEqual(replay['pagination']['pairs'][0]['unique_in_pair'],41)
        self.assertTrue(replay['pagination']['pairs'][0]['lookahead_reappeared'])
        self.assertEqual(replay['overall']['latency']['native_service_ms']['n'],0)
        self.assertEqual(replay['overall']['latency']['time_to_first_result_ms']['n'],3)
        retained = json.loads((ROOT/'experiments/market_discovery/runs/t3-harness/historical.json').read_text())
        self.assertEqual(retained,replay)

    def test_complete_dry_flow_timing_and_fresh_revalidation(self):
        flow = simulated_flow()
        intent = flow['flow']['intent']
        self.assertIsNotNone(intent)
        self.assertEqual(intent['lineage'],'SIMULATED')
        self.assertEqual(intent['mode'],'DRY_RUN_ONLY')
        self.assertEqual(intent['expected_profit'],intent['target_sale_price']-intent['target_sale_price']//20-intent['buy_now_price'])
        self.assertGreaterEqual(intent['expected_profit'],intent['X'])
        self.assertGreaterEqual(flow['flow']['search_to_intent_ms'],100)
        self.assertEqual(flow['flow']['time_to_first_result_ms'],50)
        self.assertGreater(flow['flow']['python_total_ms'],0)
        self.assertEqual(flow['EA_live_requests'],0)
        self.assertEqual(flow['budget']['requests'],2)
        self.assertTrue(all(a['criteria']['fresh'] for a in flow['records']))
        candidate = min(observations([flow['records'][0]]),key=lambda o:o.buy_now_price)
        rules = {233731:Rules(MarketKey(233731,'pc'),150,15000000,stamp(flow['records'][1]['completed_utc']))}
        rec = deepcopy(flow['records'][1])
        for reason in ('changed_bin','changed_item','expired','cached','stale','missing'):
            r = deepcopy(rec)
            row = next(a for a in r['result']['auctions'] if a['trade_id']==candidate.trade_id)
            if reason=='changed_bin': row['buy_now_price']+=100
            if reason=='changed_item': row['item']['item_id']='item:'+'0'*24
            if reason=='expired': row['expires']=0
            if reason=='cached': r['network_fresh']=False
            if reason=='stale': r['submitted_utc']=(stamp(r['completed_utc'])-timedelta(seconds=31)).isoformat()
            if reason=='missing': r['result']['auctions'].remove(row)
            with self.subTest(reason=reason):
                out = decision([r],candidate,now=stamp(rec['completed_utc']),rules=rules,simulated=True)
                self.assertIsNone(out['intent'])
        real = decision([rec],candidate,now=stamp(rec['completed_utc']),rules=rules,simulated=False)
        self.assertEqual(real['state'],'RULES_NOT_VERIFIED')
        self.assertIsNone(real['intent'])
        self.assertEqual(summary(list(range(19)))['p95_ms'],None)
        self.assertEqual(summary(list(range(20)))['p95_ms'],18)

    def test_cli_reproducible_isolated_artifacts_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            for action in ('demo','replay','flow-demo'):
                dest = Path(directory)/(action+'.json')
                cmd = [sys.executable,'-m','experiments.market_discovery',action,'--output',str(dest)]
                p = subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                artifact = json.loads(dest.read_text())
                self.assertEqual(artifact['account_mutations'],0)
                before = dest.read_bytes()
                duplicate = subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=15)
                self.assertNotEqual(duplicate.returncode,0)
                self.assertEqual(dest.read_bytes(),before)
        with self.assertRaises(ValueError): Runner(self.transport,mode='LIVE_READ_ONLY',clock=self.clock).run(1)


if __name__=='__main__':
    unittest.main()
