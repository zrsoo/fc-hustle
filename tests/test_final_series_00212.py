"""Independent artifact checks for every item-12 criterion; no EA requests.

Passing these tests validates evidence integrity and honest PARTIAL reporting.
The separate strict acceptance command still fails for unwitnessed branches.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from check_final_series_00212 import selected
from fc_access.actors_v1.final_series import audit_series
from fc_access.actors_v1.final_run import REQUIRED,load_evidence
from record_final_series_00212 import actor_count


class FinalSeries(unittest.TestCase):
    def assert_sanitized(self,value):
        if isinstance(value,dict):
            for key,data in value.items():
                self.assertNotIn(key.lower(),{'cookie','cookies','x-ut-sid','access_token','refresh_token','authentication_headers'})
                if key.lower()=='authorization':
                    self.assertEqual(data,'Explicit FIXING_PERSISTENT_FAILURE instruction in the same worker')
                self.assert_sanitized(data)
        elif isinstance(value,list):
            for data in value:self.assert_sanitized(data)
    @classmethod
    def setUpClass(cls):
        cls.selection=selected();s=cls.selection
        cls.report=audit_series(ROOT/s['latest'],ROOT/s['checkpoint'])
        cls.saved=json.loads((ROOT/s['outcome']).read_text(encoding='utf8'))
        cls.criteria={c['index']:c for c in cls.report['criteria']}
        cls.checkpoint=load_evidence(ROOT/s['checkpoint'])
        cls.native=[]
        for window in cls.report['windows']:
            cls.native += [r for r in load_evidence(Path(window['path'])/'native.jsonl') if r['kind']=='DISPATCH_RESULT']

    def test_criterion_0_actual_concurrent_actors_follow_gates_and_keep_one_durable_executor(self):
        self.assertEqual(self.criteria[0]['status'],'PASS')
        self.assertEqual(set(self.criteria[0]['observed']),set(REQUIRED[0]))
        for window in self.report['windows']:
            rows=load_evidence(Path(window['path'])/'supervisor.jsonl')
            prereq=next(r for r in rows if r['kind']=='PREREQUISITES')
            self.assertEqual(prereq['gate']['status'],'PASS')
            launches=[r for r in rows if r['kind']=='PROCESS_STARTED']
            self.assertEqual({r['role'] for r in launches},{'broker','acquirer','bidder','maintenance'})
            self.assertTrue(all(prereq['seq']<r['seq'] for r in launches))
        self.assertLessEqual(self.report['metrics']['active_seconds'],7200)
        self.assertGreater(self.report['metrics']['elapsed_seconds'],self.report['metrics']['active_seconds'])

    def test_criterion_1_native_bids_rebids_terminal_identity_and_actual_paid(self):
        observed=self.criteria[1]['observed']
        for name in ('discovery_filters','fresh_valuation','spendable_funds','minimum_initial_bid','leading_hold',
                     'active_outbid','minimum_rebid','terminal_won','terminal_lost','exact_owned_paid'):
            self.assertIn(name,observed)
        self.assertEqual(set(self.criteria[1]['missing']),{'cached_valuation','cap_stop'})
        export=next(r['data'] for r in self.checkpoint if r['kind']=='DURABLE_EXPORT')
        enrolled=[e for e in export['registry'] if e['kind']=='ENROLLMENT' and e['at']>=self.report['windows'][0]['started_at']]
        self.assertEqual(len(enrolled),3)
        won=[e for e in export['registry'] if e.get('reason')=='OWNED_WIN_VERIFIED' and e['trade_id'] in {a['trade_id'] for a in enrolled}]
        self.assertTrue(any(e['paid']==1200 for e in won))
        bids=[r['command']['params']['amount'] for r in self.native if r['command']['operation']=='bid' and r['response'] and r['response']['result']['success']]
        self.assertTrue({700,900,1000,1200}<=set(bids))

    def test_criterion_2_listing_and_actual_expired_bulk_effect_have_independent_readbacks(self):
        observed=self.criteria[2]['observed']
        self.assertTrue({'stored_price_listing_3600','expired_one_call_relist','unchanged_relist_prices_duration',
            'independent_maintenance_readbacks'}<=set(observed))
        self.assertEqual(self.criteria[2]['missing'],['sold_one_call_clear'])
        lists=[r for r in self.native if r['command']['operation']=='list']
        self.assertEqual(len(lists),1)
        p=lists[0]['command']['params']
        self.assertEqual((p['paid'],p['starting_bid'],p['buy_now_price'],p['duration']),(1200,1900,2000,3600))
        relists=[r for r in self.native if r['command']['operation']=='relist_all']
        self.assertEqual(len(relists),1)
        self.assertEqual(relists[0]['command']['params']['expected_expired_count'],2)
        self.assertFalse(relists[0]['response']['result']['success'])
        self.assertTrue(self.report['metrics']['effect_readbacks'])
        self.assertFalse(any(r['command']['operation']=='clear_sold' for r in self.native))

    def test_criterion_3_measured_queue_and_sticky_unknown_never_become_synthetic_success(self):
        observed=self.criteria[3]['observed']
        self.assertTrue({'capacity_accounting','whole_queue_intervals','native_fanout_deadline_misses','restart_reconnect'}<=set(observed))
        self.assertTrue({'capacity_pause_resume','sticky_draining','priority_under_load','unknown_reconciliation',
            'attributable_realized_profit'}<=set(self.criteria[3]['missing']))
        metrics=self.report['metrics']
        self.assertTrue(any(w['metrics']['bidder_start_intervals_seconds'] for w in metrics['per_window']))
        for row in self.native:
            self.assertGreaterEqual(row['measured']['queue_ms'],0)
            if row['response']:self.assertEqual(row['counted_requests'],row['response']['freshness']['request_count'])
        pending=metrics['runtime_unresolved_intents'];self.assertEqual(len(pending),1)
        self.assertEqual((pending[0]['operation'],pending[0]['state']),('relist_all','UNKNOWN'))
        db=sqlite3.connect((ROOT/self.selection['checkpoint']).parent.joinpath('state-backup/journal.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
        try:self.assertEqual(db.execute('select state,incompatible from bulk_writes_v1 where id=?',(pending[0]['command_id'],)).fetchone(),('UNKNOWN',1))
        finally:db.close()

    def test_criterion_4_real_enrollments_and_natural_observations_do_not_invent_fifty_auctions(self):
        self.assertEqual(self.criteria[4]['status'],'PASS')
        self.assertEqual(self.report['metrics']['enrolled_in_experiment'],3)
        self.assertIs(self.report['metrics']['actual_50_auction_sample'],False)
        watched=[r['response'] for r in self.native if r['command']['operation']=='watched' and r['response'] and r['response']['result']['success']]
        self.assertTrue(watched);self.assertLess(max(len(v['result']['auctions']) for v in watched),50)
        self.assertTrue(any(w['metrics']['enrolled_status_samples'] for w in self.report['metrics']['per_window']))

    def test_criterion_5_strict_live_acceptance_fails_despite_http200_and_offline_pass(self):
        self.assertEqual(self.report['status'],'PARTIAL/NOT FULL PASS')
        self.assertIn('all_transaction_and_maintenance_branches',self.criteria[5]['missing'])
        self.assertIn('offline_regressions',self.criteria[5]['observed'])
        self.assertTrue(any(any(n['status']==200 for n in f['network']) for f in self.report['failures']))
        p=subprocess.run([sys.executable,'tests/check_final_series_00212.py'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,1,p.stdout+p.stderr)
        self.assertEqual(json.loads(p.stdout)['status'],'PARTIAL/NOT FULL PASS')

    def test_criterion_6_exact_missing_claims_and_captured_failures_are_preserved(self):
        self.assertEqual(self.criteria[6]['status'],'PASS')
        missing={name for c in self.report['criteria'] for name in c['missing']}
        self.assertEqual(set(self.report['unverified']),missing)
        self.assertEqual(self.saved['status'],self.report['status'])
        self.assertEqual(self.saved['criteria'],self.report['criteria'])
        self.assertEqual(self.saved['unverified'],self.report['unverified'])
        self.assertEqual(self.saved['failures'],self.report['failures'])
        errors={f['error'] for f in self.report['failures']}
        self.assertTrue({'schema_unrecognized','invalid_preconditions','ambiguous_network','bulk_contract_changed'}<=errors)
        self.assertIn('per-sale net receipt',self.report['unverified']['attributable_realized_profit'])

    def test_criterion_7_sealed_sanitized_append_only_captures_and_actual_process_shutdown(self):
        self.assertEqual(self.criteria[7]['status'],'PASS')
        index=json.loads((ROOT/self.selection['evidence_index']).read_text())
        self.assertGreater(len(index['files']),50)
        for record in index['files']:
            path=ROOT/record['path']
            self.assertTrue(path.suffix in {'.jsonl','.sqlite3'} or path.name.startswith('regressions'))
            data=path.read_bytes();self.assertEqual(len(data),record['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'])
            if path.suffix=='.jsonl':
                rows=load_evidence(path)
                self.assert_sanitized(rows)
        service=next(r for r in self.checkpoint if r['kind']=='READ_ONLY_SERVICE_RESTORED')
        self.assertFalse(service['mutations_enabled'])
        self.assertEqual(actor_count(),0)
        ids=[r['command']['id'] for r in self.native];self.assertEqual(len(ids),len(set(ids)))
        with self.assertRaises(AssertionError):self.assert_sanitized({'Authorization':'Bearer offline-negative-example'})


if __name__=='__main__':unittest.main(verbosity=2)
