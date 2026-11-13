"""001d-04 acceptance; offline real pricing API, protocol and durable SQLite.

Run independently from the workspace: python tests/test_001d04_pricing.py
"""
import ast
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1.pricing import (PricingService, Quote, select_comparables,
                                             affordable_cap)
from fc_access.production_v1.price_cache import QuoteCache, DEFAULT_CACHE_PATH, TTL_SECONDS
from fc_access.production_v1.prices import PriceService, CardKey
from fc_access.production_v1.adapter import NativeAdapter
from fc_access.production_v1.contracts import Search, stamp, parse_response
from native_price_fixture import FixturePriceAdapter, auction, search_response

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
RETAINED = 'docs/research/001c/001c-06-resume-02/comparables-2.json'


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'quotes.sqlite'
        self.clock = NOW

    def setup_api(self, first=None, second=None, *, definition=261855, account=None,
                  namespace=None, source='fixture', minimum=150, maximum=20000):
        a = FixturePriceAdapter(definition, minimum, maximum)
        a.source = source
        if account: a.context['account'] = account
        if namespace: a.context['identity_namespace'] = namespace
        a.now = lambda: self.clock
        ids = itertools.count(100)
        command_ids = lambda: f'{next(ids):032x}'
        provider = PriceService(a, command_ids)
        prices = provider.load(key=CardKey(definition))
        calls = []
        pages = [first if first is not None else [auction(definition, 1500, 100)],
                 second if second is not None else []]
        def fetch(cid, query):
            calls.append((cid, query.params()))
            self.assertLessEqual(len(calls), 2, 'third probe is forbidden')
            result = pages[len(calls)-1]
            if isinstance(result, Exception): raise result
            if callable(result): return result(a, cid, query)
            return search_response(a, cid, query, result)
        cache = QuoteCache(self.path)
        self.addCleanup(cache.close)
        service = PricingService(a, command_ids, cache, fetch=fetch)
        return service, prices, calls, cache

    def quote(self, service, prices, *, start=150, current=0, last=0, n=1, X=500):
        c = auction(prices.key.definition_id, 20000, n)
        c.update(starting_bid=start, current_bid=current)
        c['item']['last_sale_price'] = last
        return service.quote(c, prices, X=X)

    def cached_rows(self, cache):
        return cache.db.execute('SELECT COUNT(*) FROM completed_quotes_v1').fetchone()[0]

    def test_c0_documented_production_paths_and_legacy_coupling_removed(self):
        doc = (ROOT/'docs/research/001d/001d-04/REPORT.md').read_text()
        for path in ('fc_access/production_v1/pricing.py', 'fc_access/production_v1/price_cache.py',
                     'fc_access/production_v1/contracts.py', 'fc_access/production_v1/adapter.py',
                     'fc_access/production_v1/prices.py', str(DEFAULT_CACHE_PATH).replace('\\', '/')):
            self.assertIn(path, doc)
        self.assertEqual(TTL_SECONDS, 86400)
        for path in ('fc_access/bidding_v1/rules.py', 'fc_access/bidding_v1/adapter.py',
                     'fc_access/production_v1/pricing.py'):
            tree = ast.parse((ROOT/path).read_text())
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
            self.assertFalse(any(isinstance(n.func, ast.Attribute) and n.func.attr == 'evaluate' for n in calls))
            self.assertNotIn('median', (ROOT/path).read_text())
        from fc_access import pricing
        self.assertIs(pricing.PricingService, PricingService)
        self.assertEqual(pricing.profit(1500, 900), 525)
        # Original capture remains byte-for-byte the recorded immutable input.
        entry = json.loads((ROOT/'docs/research/001d/entry.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/RETAINED).read_bytes()).hexdigest(), entry['sha256'][RETAINED])

    def test_c1_c6_retained_unsorted_page_minimum_and_inclusive_second(self):
        retained = json.loads((ROOT/RETAINED).read_text())['response']
        self.clock = stamp(retained['observed_at'])
        first = []
        for r in retained['rows']:
            first.append({k: deepcopy(r[k]) for k in auction() if k != 'item'} |
                         {'item': {k: r[k] for k in ('item_id', 'definition_id', 'untradeable', 'last_sale_price')}})
        for mode, second in [('empty', []), ('equal', [auction(261855, 1500, 50)]),
                             ('lower', [auction(261855, 1200, 51)])]:
            with self.subTest(mode=mode):
                self.path = Path(self.tmp.name)/(mode+'.sqlite')
                api, prices, calls, cache = self.setup_api(first, second)
                q = self.quote(api, prices)
                self.assertEqual((q.completed, q.evidence['first_min']), (True, 1500))
                self.assertEqual((q.resale_price, q.max_affordable_bid), (1200, 600) if mode == 'lower' else (1500, 900))
                self.assertEqual([c[1] for c in calls], [Search.pricing(261855).params(), Search.pricing(261855,1500).params()])
                self.assertEqual(q.evidence['price_searches'], 2)
                self.assertEqual(q.evidence['samples'][0]['returned_count'], 21)
                self.assertIn(1700, [c['row']['buy_now_price'] for c in q.evidence['comparables']])
                self.assertNotIn('outlier', q.evidence['exclusions'])
                self.assertEqual(self.cached_rows(cache), 1)

    def test_c1_defaults_invalid_expired_mismatch_duplicates_and_candidate_excluded(self):
        good = auction(261855, 1500, 100)
        default = auction(261855, 10000, 101); default['starting_bid'] = 600
        expired = auction(261855, 900, 102); expired['expires'] = 0
        wrong = auction(999, 800, 103)
        illegal = auction(261855, 1510, 104)
        inactive = auction(261855, 800, 105); inactive['trade_state'] = 'closed'
        untradeable = auction(261855, 800, 106); untradeable['item']['untradeable'] = True
        conflict = auction(261855, 800, 107); conflict2 = deepcopy(conflict); conflict2['buy_now_price'] = 900
        candidate = auction(261855, 750, 1)
        shared_item = auction(261855, 800, 108); shared_item['item']['item_id'] = candidate['item']['item_id']
        malformed = auction(261855, 750, 109); malformed['buy_now_price'] = True
        genuine_10000 = auction(261855, 10000, 110)
        rows = [genuine_10000, default, expired, wrong, illegal, inactive, untradeable,
                conflict, conflict2, candidate, shared_item, malformed, good, deepcopy(good), None]
        api, prices, calls, _ = self.setup_api(rows)
        q = self.quote(api, prices)
        self.assertEqual(q.resale_price, 1500)
        self.assertEqual(q.evidence['sample_count'], 2)
        self.assertEqual(sorted(c['row']['buy_now_price'] for c in q.evidence['comparables']), [1500, 10000])
        for reason in ('default_600_10000_template','inactive_or_expired','exact_version_mismatch',
                       'illegal_bin','not_tradeable','conflicting_duplicate','candidate_excluded','invalid','duplicate'):
            self.assertGreater(q.evidence['exclusions'][reason], 0)
        # 600 by itself is a genuine cheap BIN, never the 600/10000 template.
        self.path = Path(self.tmp.name)/'cheap.sqlite'
        api, prices, calls, cache = self.setup_api([auction(261855, 600, 500)])
        q = self.quote(api, prices)
        self.assertEqual((q.status, q.resale_price, len(calls)), ('REJECT', 600, 1))
        self.assertNotIn('default_600_10000_template',q.evidence['exclusions'])
        self.assertEqual(self.cached_rows(cache),0)

    def test_c1_per_row_age_and_card_limits_are_validity_not_outlier_filters(self):
        _, prices, _, _ = self.setup_api()
        rows = [dict(row=auction(261855, p, 100+i), network_at=(NOW-timedelta(seconds=age)).isoformat())
                for i, (p, age) in enumerate([(1500,0),(1700,0),(800,31),(900,-1),(20100,0)])]
        valid, excluded = select_comparables(rows, auction(261855,n=1), prices, now=NOW)
        self.assertEqual([c['row']['buy_now_price'] for c in valid],[1500,1700])
        self.assertEqual(excluded,{'outside_card_limits':1,'stale_or_future':2})

    def test_c2_c5_early_reject_is_candidate_specific_never_completed_or_reused(self):
        api, prices, calls, cache = self.setup_api(second=[auction(261855, 1200, 101)])
        q = self.quote(api, prices, start=950)
        self.assertEqual((q.status, q.completed, q.resale_price, q.max_affordable_bid), ('REJECT',False,1500,900))
        self.assertEqual(len(calls),1)
        self.assertEqual(q.evidence['reasons'],['minimum_exceeds_first_page_cap'])
        self.assertEqual(self.cached_rows(cache),0)
        # A different candidate can qualify; no rejection-only price hit.
        api, prices, calls, _ = self.setup_api()
        self.assertTrue(self.quote(api, prices, start=900, n=2).completed)
        self.assertEqual(len(calls),2)

    def test_c2_current_bid_uses_next_native_absolute_minimum_and_equality_qualifies(self):
        api, prices, calls, _ = self.setup_api()
        q = self.quote(api, prices, current=900)
        self.assertEqual((q.evidence['minimum_legal_bid'],q.status,len(calls)),(950,'REJECT',1))
        api, prices, calls, _ = self.setup_api()
        q = self.quote(api, prices, current=850)
        self.assertEqual((q.evidence['minimum_legal_bid'],q.status,len(calls)),(900,'COMPLETE',2))

    def test_c3_c5_failed_ambiguous_second_never_cache_or_publish_completed_resale(self):
        def changed(change):
            def page(a,cid,q):
                v=search_response(a,cid,q,[]); change(v); return v
            return page
        faults = [TimeoutError('PRIVATE'), RuntimeError('PRIVATE'),
                  changed(lambda v:v['result'].update(success=False,error='service_failed')),
                  changed(lambda v:v['result']['network'].append(deepcopy(v['result']['network'][0]))),
                  changed(lambda v:v['result']['network'][0]['query'].update(maxb=1600)),
                  changed(lambda v:v['result'].update(cache_invalidated=False)),
                  changed(lambda v:v['freshness'].update(network_at=None)),
                  changed(lambda v:v['context'].update(account='0'*32)),
                  changed(lambda v:v['freshness'].update(network_at=(NOW-timedelta(seconds=31)).isoformat()))]
        for i,fault in enumerate(faults):
            with self.subTest(fault=i):
                self.path=Path(self.tmp.name)/(str(i)+'.sqlite')
                api, prices, calls, cache = self.setup_api(second=fault)
                q=self.quote(api,prices)
                self.assertEqual((q.status,q.completed,q.resale_price,len(calls)),('INCOMPLETE',False,None,2))
                self.assertEqual(q.evidence['reasons'],['second_search_incomplete'])
                self.assertEqual(self.cached_rows(cache),0)
                self.assertNotIn('PRIVATE',json.dumps(q.evidence))
        for i,first in enumerate(([],[None],TimeoutError())):
            self.path=Path(self.tmp.name)/('first'+str(i)+'.sqlite')
            api,prices,calls,cache=self.setup_api(first=first)
            q=self.quote(api,prices)
            self.assertEqual((q.status,q.completed,len(calls),self.cached_rows(cache)),('INCOMPLETE',False,1,0))

    def test_c3_second_minimum_and_duplicate_identity_handling_are_global(self):
        first=[auction(261855,1500,100),auction(261855,1700,101)]
        second=[auction(261855,1500,100),auction(261855,1200,102),auction(261855,1600,103)]
        api,prices,calls,_=self.setup_api(first,second)
        q=self.quote(api,prices)
        self.assertEqual((q.resale_price,q.evidence['sample_count']),(1200,3))
        self.assertEqual(q.evidence['exclusions'],{'duplicate':1,'outside_inclusive_max_buy':1})
        self.assertEqual(len(calls),2)

    def test_c3_c5_final_candidate_rejection_still_caches_completed_price(self):
        api,prices,calls,cache=self.setup_api(second=[auction(261855,1200,101)])
        q=self.quote(api,prices,start=900)
        self.assertEqual((q.status,q.completed,q.resale_price,q.max_affordable_bid),('REJECT',True,1200,600))
        self.assertEqual((len(calls),self.cached_rows(cache)),(2,1))
        hit=self.quote(api,prices,start=150,n=2)
        self.assertEqual((hit.status,hit.completed,hit.evidence['price_searches']),('COMPLETE',True,0))
        self.assertEqual(len(calls),2)

    def test_c3_successful_empty_second_preserves_first_observation_and_its_age(self):
        def slower_second(a,cid,q):
            self.clock=NOW+timedelta(seconds=35)
            return search_response(a,cid,q,[])
        api,prices,calls,_=self.setup_api(second=slower_second)
        q=self.quote(api,prices)
        self.assertEqual((q.completed,q.resale_price,len(calls)),(True,1500,2))
        self.assertEqual([s['age_seconds'] for s in q.evidence['samples']],[35,0])
        self.assertEqual(q.evidence['age_seconds'],35)

    def test_c1_c7_pricing_store_defers_exclusions_without_retaining_unsafe_rows(self):
        from fc_access.production_v1.store import Store
        a=FixturePriceAdapter(261855);a.source='native'
        a.now=lambda:datetime.now(timezone.utc)
        store=Store(Path(self.tmp.name)/'transport.sqlite');self.addCleanup(store.db.close)
        store.activate(dict(context=deepcopy(a.context),owner=a.fences['owner'],epoch=1))
        a.fences['host_epoch']=store.host_epoch
        peer=dict(context=deepcopy(a.context),fences=deepcopy(a.fences))
        c=a.envelope('7'*32,'search',Search.pricing(261855).params())
        good=auction(261855,1500,100)
        bad=auction(261855,800,101);bad['PRIVATE']='CANARY_MUST_NOT_PERSIST'
        v=search_response(a,c['id'],Search.pricing(261855),[good,bad,deepcopy(good),auction(123,900,102)])
        with self.assertRaises(ValueError):parse_response(v,c)
        store.enqueue(c,peer);self.assertEqual(store.claim(peer),c)
        store.finish(peer,c['id'],v)
        saved=store.result(c['id'])
        self.assertIsNone(saved['result']['auctions'][1])
        self.assertEqual(len(saved['result']['auctions']),4)
        self.assertNotIn('CANARY_MUST_NOT_PERSIST',store.db.execute('SELECT result FROM commands').fetchone()[0])
        self.assertIn('PRIVATE',v['result']['auctions'][1]) # pure projection, input unchanged

    def test_c4_tax_native_floor_X_and_last_sale_independence(self):
        api,prices,calls,_=self.setup_api()
        q=self.quote(api,prices,last=1)
        for last in (0,1500,999999):
            hit=self.quote(api,prices,last=last,n=2)
            self.assertEqual((hit.resale_price,hit.tax,hit.max_affordable_bid),(1500,75,900))
            self.assertEqual(hit.evidence['candidate']['last_sale_price'],last)
            self.assertEqual(hit.evidence['price_searches'],0)
        self.assertEqual(len(calls),2)
        self.assertEqual(self.quote(api,prices,X=600).max_affordable_bid,800)
        self.assertEqual(affordable_cap(prices,1700,500),1100) # raw 1115, floor 1100
        self.assertEqual(affordable_cap(prices,1000,0),950)
        self.assertIsNone(affordable_cap(prices,150,500))
        # Card listing minimum is not a minimum economic bid.
        self.path=Path(self.tmp.name)/'cardminimum.sqlite'
        api,prices,calls,_=self.setup_api(minimum=1500)
        self.assertEqual(self.quote(api,prices).max_affordable_bid,900)

    def test_c5_c6_cache_zero_requests_exact_expiry_and_restart(self):
        api,prices,calls,cache=self.setup_api()
        q=self.quote(api,prices)
        self.assertTrue(q.completed)
        self.clock=NOW+timedelta(seconds=86399,microseconds=999999)
        hit=self.quote(api,prices,n=2)
        self.assertTrue(hit.evidence['cache_hit'])
        self.assertEqual((hit.evidence['price_searches'],len(calls)),(0,2))
        self.assertEqual(hit.evidence['age_seconds'],86399.999999)
        # A separate interpreter opens the database: restart cannot depend on RAM.
        script='''import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'tests'))
from native_price_fixture import native_rules, auction
from fc_access.production_v1.pricing import PricingService
from fc_access.production_v1.price_cache import QuoteCache
from datetime import datetime, timezone
r,p=native_rules(261855)
a=p.adapter; a.now=lambda:datetime(2030,1,1,0,0,1,tzinfo=timezone.utc)
c=QuoteCache(sys.argv[1])
def forbidden(*args): raise AssertionError('cache restart searched')
q=PricingService(a,lambda:'9'*32,c,fetch=forbidden).quote(auction(261855,n=2),r)
assert q.completed and q.resale_price==1500 and q.evidence['price_searches']==0
c.close()
'''
        run=subprocess.run([sys.executable,'-c',script,str(self.path)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.clock=NOW+timedelta(seconds=86400)
        api,prices,calls,_=self.setup_api()
        expired=self.quote(api,prices,n=2)
        self.assertEqual((expired.evidence['cache_hit'],len(calls)),(False,2))

    def test_c5_cache_scope_account_version_namespace_source_and_backward_clock(self):
        api,prices,_,cache=self.setup_api()
        self.quote(api,prices)
        for kwargs in ({'account':'9'*32},{'definition':123},{'namespace':'8'*32},{'source':'native'}):
            with self.subTest(kwargs=kwargs):
                other,p,calls,_=self.setup_api(**kwargs)
                self.assertTrue(self.quote(other,p).completed)
                self.assertEqual(len(calls),2)
        context=dict(api.adapter.context)
        # Game/platform are validated, explicitly present in the primary key.
        self.assertEqual(cache.key(context,261855),(context['account'],'fc27','pc',261855))
        columns=cache.db.execute('PRAGMA table_info(completed_quotes_v1)').fetchall()
        self.assertEqual([c[1] for c in columns if c[5]],['account','game','platform','definition_id'])
        for change in ({'platform':'ps5'},{'game':'fc26'}):
            with self.assertRaises(ValueError):cache.get(context|change,261855,now=NOW,source='fixture')
        self.clock=NOW-timedelta(microseconds=1)
        self.assertIsNone(cache.get(context,261855,now=self.clock,source='fixture'))
        with self.assertRaisesRegex(ValueError,'completed_two_search'):
            cache.put(context,261855,{'schema':1,'completed':False})

    def test_c7_evidence_age_coverage_counts_exclusions_and_reasons(self):
        api,prices,calls,_=self.setup_api([auction(261855,1700,101),auction(261855,1500,100)])
        q=self.quote(api,prices,last=50000)
        e=q.evidence
        self.assertEqual((e['claim'],e['complete_market_coverage']),('OBSERVED_MINIMUM_ONLY',False))
        self.assertEqual((e['sample_count'],e['price_searches'],e['age_seconds']),(2,2,0))
        self.assertEqual([s['returned_count'] for s in e['samples']],[2,0])
        self.assertEqual([s['valid_unique_count'] for s in e['samples']],[2,0])
        self.assertEqual([s['age_seconds'] for s in e['samples']],[0,0])
        self.assertTrue(all(s['coverage']==dict(complete=False,has_more=True) for s in e['samples']))
        self.assertEqual(e['reasons'],['two_successful_samples'])
        self.assertEqual(e['candidate']['last_sale_price'],50000)
        self.assertTrue(all(c['row']['trade_id']!=e['candidate']['trade_id'] for c in e['comparables']))
        # Caller mutations to evidence cannot modify the already committed cache.
        q.evidence['comparables'][0]['row']['buy_now_price']=9999
        self.assertEqual(self.quote(api,prices,n=2).resale_price,1500)

    def test_c5_c7_cached_candidate_rows_remain_separate_and_missing_independents_do_not_search(self):
        api,prices,calls,cache=self.setup_api()
        self.quote(api,prices)
        q=self.quote(api,prices,n=100)
        self.assertEqual((q.status,q.completed,q.evidence['sample_count'],q.evidence['price_searches']),
                         ('INCOMPLETE',False,0,0))
        self.assertEqual(q.evidence['exclusions']['cache_candidate_excluded'],1)
        self.assertEqual(len(calls),2)
        # This per-candidate exclusion does not erase the durable complete quote.
        q=self.quote(api,prices,n=2)
        self.assertEqual((q.status,q.resale_price,q.evidence['price_searches']),('COMPLETE',1500,0))

    def test_c8_real_production_adapter_searches_only_no_actor_or_dispatch(self):
        from fc_access.production_v1.contracts import empty_result
        helper=FixturePriceAdapter(261855)
        class Page:
            def __init__(self):self.commands=[]
            def attach(self,context,owner,epoch):return deepcopy(helper.fences)
            def execute(self,c):
                self.commands.append(deepcopy(c))
                if c['operation'] == 'bid':raise AssertionError('pricing dispatched bid')
                if c['operation']=='search':
                    return search_response(adapter,c['id'],Search(**c['params']),
                                           [auction(261855,1500,100)] if 'max_buy' not in c['params'] else [])
                at=NOW.isoformat()
                r=empty_result(None)
                r.update(success=True,status=200,caps=dict(definition_id=261855,minimum=150,maximum=20000),
                         network=[dict(host='utas.test.ea.com',method='GET',path='/ut/game/fc27/marketdata/pricelimits',
                                       query=dict(defId=261855),status=200,session_header_present=True)])
                f=dict(observed_at=at,network_at=at,request_count=1,read_id=c['id'],source='fixture')
                if c['operation']=='price_helpers':
                    r=dict(success=True,error=None,version=1,above_available=True,below_available=True,
                           probes=helper.price_helpers(c['id'],c['params']['probes'])['result']['probes'],network=[])
                    f.update(network_at=None,request_count=0)
                return dict(schema=2,command_id=c['id'],operation=c['operation'],context=c['context'],fences=c['fences'],
                            result=r,freshness=f,coverage=dict(complete=False,has_more=None),timing=dict(native_service_ms=1))
        p=Page()
        adapter=NativeAdapter(p,context=helper.context,owner=helper.fences['owner'],epoch=1,now=lambda:NOW,fixture=True)
        ids=itertools.count(1); nextid=lambda:f'{next(ids):032x}'
        prices=PriceService(adapter,nextid).load(key=CardKey(261855))
        cache=QuoteCache(self.path);self.addCleanup(cache.close)
        with patch.object(adapter,'dispatch_intent',side_effect=AssertionError('write forbidden')):
            q=PricingService(adapter,nextid,cache).quote(auction(261855,n=1),prices)
        self.assertTrue(q.completed)
        self.assertEqual([c['params'] for c in p.commands if c['operation']=='search'],
                         [Search.pricing(261855).params(),Search.pricing(261855,1500).params()])
        self.assertEqual(set(c['operation'] for c in p.commands),{'caps','price_helpers','search'})
        tree=ast.parse((ROOT/'fc_access/production_v1/pricing.py').read_text())
        self.assertFalse(any(isinstance(n,(ast.While,ast.AsyncFor)) for n in ast.walk(tree)))
        self.assertNotIn('scheduler', (ROOT/'fc_access/production_v1/pricing.py').read_text().lower())


if __name__=='__main__':unittest.main(verbosity=2)
