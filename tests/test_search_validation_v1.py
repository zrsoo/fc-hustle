"""001c-04 contracts: synthetic faults, price boundaries and actual JS probe."""
from copy import deepcopy
from datetime import timedelta
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
from experiments.search_validation_v1.validation import assess,validate,availability,timestamp
from experiments.search_validation_v1.economics import caps,client_rules,coverage,evaluate,observations
from experiments.search_validation_v1.server import Server,EXTENSION_ID
from fc_access import pricing

D=ROOT/'docs/research/001c/001c-04'
def load(name):return json.loads((D/name).read_text(encoding='utf-8'))


class Contracts(unittest.TestCase):
    def test_0_native_javascript_query_projection_empty_privacy_and_rejection(self):
        r=subprocess.run(['node','tests/search_validation_v1_checks.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_0_independent_wire_and_actual_fc27_query_names_required(self):
        v=load('search-1.json');a=assess(v)
        self.assertTrue(a['semantics_nonempty_verified'])
        for kind in ('current','start','bin','wire','auth','persona','query','cache'):
            p=deepcopy(v)
            if kind=='current':p['rows'][0]['current_bid']=1001
            if kind=='start':p['rows'][0]['starting_bid']=1001
            if kind=='bin':p['rows'][0]['buy_now_price']=10499
            if kind=='wire':p['wire_rows'][0]['current_bid']+=50
            if kind=='auth':p['network'][0]['session_header_present']=False
            if kind=='persona':p['persona']['accepted']=False
            if kind=='query':p['network'][0]['query']={'maxb':1000,'micr':10500}
            if kind=='cache':p['network']=[]
            try:verified=assess(p)['semantics_nonempty_verified']
            except ValueError:verified=False
            self.assertFalse(verified,kind)
        empty=deepcopy(v);empty['rows']=[];empty['wire_rows']=[]
        a=assess(empty)
        self.assertTrue(a['fresh_authenticated_pc'] and a['independent_wire_entity_match'] and a['zero_results'])
        self.assertFalse(a['semantics_nonempty_verified'])

    def test_1_pagination_coverage_and_live_changes_cannot_establish_global_absence(self):
        a,b,c=map(load,['search-1.json','search-2.json','search-3.json'])
        r=coverage(a,b,c)
        self.assertEqual(r['requested_starts'],[0,20]);self.assertLessEqual(r['unique_rows'],42)
        self.assertFalse(r['complete_market_coverage']);self.assertFalse(r['server_order_guaranteed'])
        duplicated=deepcopy(a);duplicated['rows'][1]=deepcopy(duplicated['rows'][0])
        self.assertEqual(coverage(duplicated,b,c)['within_page_duplicates'][0],1)

        overlap=deepcopy(b);overlap['rows'][0]=deepcopy(a['rows'][20])
        result=coverage(a,overlap,c)
        self.assertTrue(result['lookahead_reappeared_on_page2']);self.assertIn(a['rows'][20]['trade_id'],result['page_overlap'])

    def test_1_fresh_availability_identity_price_change_missing_and_staleness(self):
        v=load('rules-and-availability.json');r=v['rows'][0];now=timestamp(v['observed_at'])
        self.assertEqual(availability(r,v,now=now),'AVAILABLE_READ_ONLY')
        self.assertEqual(availability(r,v,now=now+timedelta(seconds=31)),'STALE')
        for field in ('item_id','definition_id','current_bid','buy_now_price'):
            candidate=deepcopy(r)
            candidate[field]=('item:'+'f'*24) if field=='item_id' else candidate[field]+1
            self.assertEqual(availability(candidate,v,now=now),'IDENTITY_CHANGED' if field in ('item_id','definition_id') else 'PRICE_CHANGED')
        p=deepcopy(v);p['rows']=[];p['wire_rows']=[]
        self.assertEqual(availability(r,p,now=now),'ABSENT_IN_BOUNDED_SEARCH')
        p=deepcopy(v);p['network'][0]['session_header_present']=False
        self.assertEqual(availability(r,p,now=now),'UNKNOWN')

        p=deepcopy(v);p['rows'][0]['expires']=0;p['wire_rows'][0]['expires']=0
        self.assertEqual(availability(r,p,now=now),'UNAVAILABLE')
        p=deepcopy(v);p['rows'].append(deepcopy(p['rows'][0]));p['wire_rows'].append(deepcopy(p['wire_rows'][0]))
        self.assertEqual(availability(r,p,now=now),'CONFLICTING_DUPLICATE')

    def test_2_exact_version_resource_id_not_asset_and_native_caps_authentication(self):
        v=load('search-1.json')
        special=[(a,b) for a,b in zip(v['rows'],v['wire_rows']) if b['resource_id']!=b['asset_id']]
        self.assertTrue(special,'must witness a non-base version, not just a base asset')
        for a,b in special:self.assertEqual(a['definition_id'],b['resource_id'])
        p=deepcopy(v);i=next(i for i,b in enumerate(p['wire_rows']) if b['resource_id']!=b['asset_id']);p['rows'][i]['definition_id']=p['wire_rows'][i]['asset_id']
        self.assertFalse(assess(p)['independent_wire_entity_match'])
        v=load('rules-and-availability.json');self.assertEqual(caps(v,227323),{'definition_id':227323,'minimum':700,'maximum':11000})
        for change in ('auth','identity','wire','route'):
            p=deepcopy(v)
            if change=='auth':p['network'][1]['session_header_present']=False
            if change=='identity':p['cap_read']['rows'][0]['definition_id']=1
            if change=='wire':p['cap_read']['wire'][0]['maximum']=99999
            if change=='route':p['network']=p['network'][:1]
            self.assertIsNone(caps(p,227323))

    def test_3_five_independent_pc_exact_comps_candidate_exclusion_and_outliers(self):
        v=load('rules-and-availability.json');rules=client_rules(v,227323);now=timestamp(v['observed_at']);key=rules.key
        candidate=pricing.Observation('candidate','owned',key,11000,now,600)
        rows=[pricing.Observation(str(i),str(i),key,p,now,600) for i,p in enumerate([5900,6000,6100,6200,6300,11000])]
        def price(rs):return pricing.evaluate(key,rs,candidate,rules,now=now,X=500)
        r=price(rows+[rows[0],candidate]);self.assertEqual(r.status,'OK');self.assertEqual(r.sample_count,5)
        rejected=dict(r.rejected);self.assertEqual(rejected['outlier'],1);self.assertEqual(rejected['duplicate'],1);self.assertEqual(rejected['acquisition_excluded'],1)
        self.assertEqual(price(rows[:4]).status,'INSUFFICIENT_SAMPLES')
        from dataclasses import replace
        for fault in ('version','platform','stale','cache','conflict','item'):
            p=list(rows[:5]);bad=p[-1]
            if fault=='version':bad=replace(bad,key=pricing.MarketKey(42,'pc'))
            if fault=='platform':bad=replace(bad,key=pricing.MarketKey(227323,'ps5'))
            if fault=='stale':bad=replace(bad,observed_at=now-timedelta(seconds=121))
            if fault=='cache':bad=replace(bad,network_fresh=False)
            if fault=='item':bad=replace(bad,item_id=p[0].item_id)
            p[-1]=bad
            if fault=='conflict':p.append(replace(p[-1],buy_now_price=6400))
            self.assertNotEqual(price(p).status,'OK',fault)

    def test_4_native_client_tick_boundaries_caps_floor_tax_and_search_vs_cap(self):
        v=load('rules-and-availability.json');rules=client_rules(v,227323)
        self.assertEqual(pricing.floor_price(5579,rules),5500)
        self.assertEqual(pricing.floor_price(699,rules),None)
        self.assertEqual(pricing.floor_price(999999,rules),11000)
        for target in (19,20,21,5999,6000,6001):self.assertEqual(pricing.profit(target,1),target-target//20-1)
        probes={r['value']:r for r in v['native_rules']['probes']}
        self.assertEqual(probes[1000]['above'],1100);self.assertEqual(probes[1000]['below'],950)
        self.assertEqual(probes[10000]['above'],10250);self.assertEqual(probes[10000]['below'],9900)
        self.assertEqual(probes[150]['below'],0,'actual native helper is not the generic price floor at minimum')

    def test_5_6_fail_closed_rules_estimates_no_bid_and_no_realized_sales(self):
        v=load('rules-and-availability.json');comp=load('comparables-3.json');now=timestamp(v['observed_at'])
        # Re-time copied evidence ONLY as a synthetic fixture for a stale-data branch.
        p=deepcopy(v);p['cap_read']=None
        result=evaluate(v,comp,p,trade_id=v['rows'][0]['trade_id'],now=now)
        self.assertEqual(result['estimate']['status'],'MISSING_CAPS');self.assertFalse(result['bid_authorized'])
        self.assertIsNone(result['realized_sale_price']);self.assertIsNone(result['realized_profit'])
        self.assertEqual(result['server_bid_tick_acceptance'],'UNVERIFIED')
        self.assertTrue(result['fresh_prebid_availability_required'])

    def test_6_schema_rejects_sensitive_extra_fields_and_raw_identities(self):
        v=load('search-1.json')
        for fault in ('auth','raw','cookies','header','boolean'):
            p=deepcopy(v)
            if fault=='auth':p['network'][0]['authorization']='secret'
            if fault=='raw':p['rows'][0]['trade_id']='12345678'
            if fault=='cookies':p['cookies']={}
            if fault=='header':p['network'][0]['query']['sid']=1
            if fault=='boolean':p['params']['max_bid']=True
            with self.assertRaises((TypeError,ValueError),msg=fault):validate(p)

    def test_6_transport_rejects_write_bad_origin_and_consumed_budget_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'budget.json';path.write_text(json.dumps({'task':'001c-04','consumed':12,'maximum':12,'commands':[]}))
            for _ in range(2):
                s=Server(0,path);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
                base=f'http://127.0.0.1:{s.server_port}'
                try:
                    for body,origin,code in [({'operation':'bid'},None,400),({'params':{'page':1,'count':21}},'https://ea.com',403),({'params':{'page':1,'count':21}},None,409)]:
                        h={'Content-Type':'application/json'}
                        if origin:h['Origin']=origin
                        req=urllib.request.Request(base+'/run',data=json.dumps(body).encode(),headers=h)
                        with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(req,timeout=3)
                        self.assertEqual(cm.exception.code,code)
                    self.assertEqual(s.budget['consumed'],12)
                finally:s.shutdown();s.server_close()


if __name__=='__main__':unittest.main(verbosity=2)
