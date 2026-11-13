"""Independent 001c-04 evidence audit. No browser, auth or EA requests."""
from datetime import datetime
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from statistics import median
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.search_validation_v1.validation import assess,validate,availability,timestamp
from experiments.search_validation_v1.economics import coverage,evaluate,caps

D=ROOT/'docs/research/001c/001c-04'
def load(name):return json.loads((D/name).read_text(encoding='utf-8'))
def canonical(value):return json.dumps(value,sort_keys=True)


class Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=load('report.json');cls.e=cls.report['economics']
        cls.candidate=load(cls.report['candidate_capture']);cls.comps=load(cls.report['comparable_capture']);cls.rules=load(cls.report['rules_capture'])
        cls.now=timestamp(cls.report['evaluated_at'])

    def test_0_fresh_authenticated_pc_dto_query_wire_and_start_current_bin_contracts(self):
        for name in ('search-1.json','search-2.json','search-3.json'):
            v=load(name);a=assess(v)
            self.assertTrue(a['semantics_nonempty_verified'],name)
            self.assertEqual((v['criteria']['maxBid'],v['criteria']['minBuy']),(1000,10500))
            n=v['network'][0];self.assertEqual(n['method'],'GET');self.assertEqual(n['status'],200)
            self.assertEqual(n['query']['macr'],1000);self.assertEqual(n['query']['minb'],10500)
            self.assertEqual((v['persona']['platform_value'],v['persona']['native_pc_constant']),('PC','PC'))
            self.assertTrue(any(r['current_bid']==0 for r in v['rows']))
            self.assertTrue(any(r['current_bid']>0 for r in v['rows']))
            self.assertTrue(all(0<r['starting_bid']<=1000 and 0<=r['current_bid']<=1000 and r['buy_now_price']>=10500 for r in v['rows']))
        # A positive current bid need not equal the starting bid.
        self.assertTrue(any(r['current_bid']>r['starting_bid'] for r in load('search-1.json')['rows']))

    def test_1_real_paging_repeated_lookahead_changed_and_prebid_requirement(self):
        expected=coverage(*map(load,['search-1.json','search-2.json','search-3.json']))
        self.assertEqual(self.report['pagination'],expected)
        self.assertEqual(expected['requested_starts'],[0,20]);self.assertEqual(expected['page_rows'],[21,21])
        self.assertEqual(expected['unique_rows'],42);self.assertEqual(expected['page_overlap'],[])
        self.assertFalse(expected['lookahead_reappeared_on_page2'])
        self.assertEqual(len(expected['repeat_absent_from_first_page']),4)
        self.assertTrue(expected['repeat_changed']);self.assertFalse(expected['complete_market_coverage'])
        row=next(r for r in self.candidate['rows'] if r['trade_id']==self.e['trade_id'])
        self.assertEqual(availability(row,self.candidate,now=self.now),'AVAILABLE_READ_ONLY')
        self.assertTrue(self.e['fresh_prebid_availability_required'])
        self.assertGreaterEqual(len(self.report['required_before_any_bid']),4)

    def test_2_sample_version_item_trade_native_caps_and_client_server_separation(self):
        first=load('search-1.json');pairs=list(zip(first['rows'],first['wire_rows']))
        self.assertTrue(any(a['definition_id']==50573369 and b['asset_id']==241721 and b['resource_id']==50573369 for a,b in pairs))
        for a,b in pairs:
            self.assertEqual(a['trade_id'],b['trade_id']);self.assertEqual(a['item_id'],b['item_id']);self.assertEqual(a['definition_id'],b['resource_id'])
        cap=caps(self.rules,227323)
        self.assertEqual(cap,{'definition_id':227323,'minimum':700,'maximum':11000})
        self.assertLessEqual((self.now-timestamp(self.rules['observed_at'])).total_seconds(),300)
        self.assertEqual(self.rules['native_rules']['classification'],'NATIVE_CLIENT_OBSERVED_SERVER_LEGALITY_UNVERIFIED')
        self.assertEqual(self.e['server_bid_tick_acceptance'],'UNVERIFIED');self.assertEqual(self.e['server_listing_tick_acceptance'],'UNVERIFIED')

    def test_3_4_independent_fresh_ask_selection_robust_target_tax_cap_and_rounding(self):
        # Recompute the retained case without calling the implementation estimator.
        self.assertTrue(assess(self.comps)['semantics_nonempty_verified'])
        self.assertEqual(self.comps['params']['definition_id'],227323)
        self.assertNotIn('min_buy',self.comps['params'],'do not price from the inflated discovery BIN floor')
        at=timestamp(self.comps['network'][0]['started_at']);age=(self.now-at).total_seconds()
        self.assertTrue(0<=age<=120)
        selected=[];trades=set();items=set();rejected=0
        for r in self.comps['rows']:
            self.assertEqual(r['definition_id'],227323)
            if r['trade_id']==self.e['trade_id'] or r['item_id']==self.e['item_id']:continue
            self.assertNotIn(r['trade_id'],trades);self.assertNotIn(r['item_id'],items)
            trades.add(r['trade_id']);items.add(r['item_id'])
            if r['trade_state']!='active' or r['expires']-age<=30:
                rejected+=1;continue
            self.assertTrue(700<=r['buy_now_price']<=11000)
            selected.append(r['buy_now_price'])
        self.assertGreaterEqual(len(selected),5)
        center=median([Fraction(p) for p in selected]);mad=median([abs(p-center) for p in selected])
        radius=max(3*mad,center/5);robust=sorted(p for p in selected if abs(p-center)<=radius)
        self.assertGreaterEqual(len(robust),5)
        self.assertEqual(len(robust),self.e['estimate']['sample_count']);self.assertEqual(len(robust),12)
        self.assertEqual(rejected,9)
        quartile=robust[(len(robust)-1)//4]
        # All retained target/cap values lie in the observed 100-coin client band.
        self.assertTrue(1000<=quartile<10000)
        target=quartile//100*100-100;tax=target//20;raw=target-tax-500;rounded=raw//100*100
        self.assertEqual((target,tax,raw,rounded),(5900,295,5105,5100))
        self.assertEqual((self.e['target'],self.e['X'],self.e['tax'],self.e['unrounded_profitable_cap'],self.e['client_tick_rounded_cap']),(target,500,tax,raw,rounded))
        self.assertLessEqual(rounded,raw);self.assertEqual(self.e['search_maxBid'],1000);self.assertGreater(rounded,1000)
        self.assertEqual(self.e['projected_profit_at_minimum'],target-tax-700)

    def test_5_6_truthful_qualification_no_authorization_no_sales_and_reproducible_economics(self):
        e=evaluate(self.candidate,self.comps,self.rules,trade_id=self.e['trade_id'],now=self.now)
        self.assertEqual(canonical(e),canonical(self.e))
        self.assertTrue(self.report['strategy_qualified_candidate']);self.assertTrue(e['pricing_qualified_at_checkpoint'])
        self.assertFalse(self.report['candidate_authorized_for_bid']);self.assertFalse(e['bid_authorized'])
        self.assertEqual(self.report['account_mutations'],0)
        self.assertIsNone(self.report['integration_test_candidate']);self.assertIsNone(e['realized_sale_price']);self.assertIsNone(e['realized_profit'])
        self.assertEqual(e['classification'],'INDICATIVE_ASK_BASED_NOT_REALIZED')
        self.assertGreaterEqual(len(self.report['unavailable_evidence']),4)
        doc=(D/'REPORT.md').read_text(encoding='utf-8')
        for text in ('SOURCE_CONFIRMED_ONLY','UNVERIFIED','BIN purchase reference','not realized profit','maxBid=1000','65 seconds','No candidate was authorized'):
            self.assertIn(text,doc)

    def test_6_every_delivery_accounted_once_with_failed_read_not_promoted(self):
        captures={}
        for p in D.glob('*.json'):
            v=json.loads(p.read_text(encoding='utf-8'))
            if 'observed_at' not in v:continue
            validate(v);self.assertNotIn(v['command_id'],captures);captures[v['command_id']]=v
            self.assertEqual(self.report['search_assessments'][p.name],assess(v))
        budget=load('budget.json')
        self.assertEqual(budget['maximum'],12);self.assertEqual(budget['consumed'],9)
        self.assertEqual(len(captures),9);self.assertEqual({r['command_id'] for r in budget['commands']},set(captures))
        self.assertEqual(sum(len(v['network']) for v in captures.values()),9)
        self.assertEqual(sum(v['success'] for v in captures.values()),8)
        for c in budget['commands']:self.assertEqual(c['params'],captures[c['command_id']]['params'])
        failed=load('comparables-2.json');self.assertEqual(failed['error'],'experiment_pacing');self.assertEqual(failed['network'],[])
        self.assertFalse(assess(failed)['fresh_authenticated_pc'])
        # Successful native searches meet the experiment gap, excluding the
        # rejected local delivery and the extra price-limit GET in one command.
        starts=sorted(timestamp(n['started_at']) for v in captures.values() for n in v['network'] if n['route'].endswith('/transfermarket'))
        self.assertTrue(all((b-a).total_seconds()>=30 for a,b in zip(starts,starts[1:])))

    def test_6_reviewed_extension_preserved_history_and_complete_acceptance_mapping(self):
        for name in ('review-v3.json','manifest.json'):
            for path,digest in load(name)['files'].items():
                self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        for path,digest in load('entry.json')['preserve'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        page=(ROOT/'experiments/search_validation_v1/browser/page.js').read_text(encoding='utf-8')
        for forbidden in ('services.Item.bid(', 'services.Item.list(', 'document.cookie','getSelectedPersona().id','localStorage'):
            self.assertNotIn(forbidden,page)
        worker=(ROOT/'experiments/search_validation_v1/browser/worker.js').read_text(encoding='utf-8')
        self.assertIn('127.0.0.1:8778',worker)
        source=load('native-source-contract.json')
        self.assertEqual(len(source['excerpts']),3)
        for excerpt in source['excerpts']:
            self.assertEqual(excerpt['classification'],'SOURCE_CONFIRMED_ONLY')
            self.assertEqual(hashlib.sha256(excerpt['source'].encode()).hexdigest(),excerpt['excerpt_sha256'])
        self.assertIn('/marketdata/pricelimits',source['excerpts'][0]['source'])
        self.assertIn('getIncrementAboveVal',source['excerpts'][1]['source'])
        self.assertIn('setPriceLimits',source['excerpts'][2]['source'])
        for path in ('edge-preflight.txt','edge-attached-2.txt','attach-v3.txt'):
            text=(D/path).read_text(encoding='utf-8-sig')
            self.assertIn('"official_tab":true',text)
        plan=load('validation-plan.json')
        self.assertEqual(set(c for v in plan['validators'] for c in v['criteria']),set(range(7)))
        for v in plan['validators']:
            self.assertTrue((ROOT/v['command'][1]).is_file());self.assertEqual(v['command'][0],'{python}')


if __name__=='__main__':unittest.main(verbosity=2)
