"""Meaningful integrated artifact checks, including rejection of false live proof.

These checks establish the retained PARTIAL outcome. The separate strict live
validator fails acceptance for missing transactions. Test doubles never write
live evidence or contact EA.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_assessment import audit,bulk_proof
from fc_access.actors_v1.final_run import Evidence,load_evidence,REQUIRED
from check_00211_artifacts import regression_check
from test_00209_bulk import BulkPage,Clock,CONTEXT
from fc_access.production_v1.foundation import Foundation

OUT=ROOT/'docs/research/002/002-12'
LIVE=OUT/'live-01'


class CapturedFinalRun(unittest.TestCase):
    def test_c0_prerequisites_real_concurrent_processes_and_native_single_broker(self):
        r=audit(LIVE);self.assertEqual(r['criteria'][0]['status'],'PASS')
        rows=load_evidence(LIVE/'supervisor.jsonl')
        prerequisite=next(x for x in rows if x['kind']=='PREREQUISITES')
        regression_check(prerequisite['regression'])
        self.assertEqual(prerequisite['gate']['bid_dispatches'],0)
        self.assertLess(prerequisite['gate']['elapsed_seconds'],30)
        self.assertEqual({x['role'] for x in rows if x['kind']=='PROCESS_STARTED'},
            {'broker','acquirer','bidder','maintenance'})

    def test_c1_native_filters_and_failure_are_actual_wire_evidence(self):
        r=audit(LIVE);self.assertIn('discovery_filters',r['criteria'][1]['observed'])
        failure=r['failures'][0]
        self.assertEqual(failure['error'],'schema_unrecognized')
        self.assertEqual((failure['params']['page'],failure['params']['count']),(2,21))
        self.assertEqual(failure['network'][0]['query'],dict(macr=1000,minb=11000,num=21,start=20))
        self.assertEqual(failure['network'][0]['status'],200)
        self.assertEqual(r['metrics']['mutations'],0)
        self.assertIn('minimum_initial_bid',r['criteria'][1]['missing'])
        self.assertIn('terminal_won',r['criteria'][1]['missing'])

    def test_c2_historical_bulk_research_never_counts_as_integrated_maintenance(self):
        r=audit(LIVE)
        self.assertEqual(set(r['criteria'][2]['missing']),set(REQUIRED[2]))
        self.assertEqual(r['criteria'][2]['observed'],{})
        commands=[x['command']['operation'] for x in load_evidence(LIVE/'native.jsonl') if 'command' in x]
        self.assertFalse(set(commands)&{'clear_sold','relist_all','list','move'})

    def test_c3_capacity_actual_fanout_and_exact_unmeasured_load_are_distinguished(self):
        r=audit(LIVE);c=r['criteria'][3]
        self.assertIn('capacity_accounting',c['observed'])
        self.assertEqual((r['metrics']['native_commands'],r['metrics']['actual_native_requests']),(6,7))
        self.assertEqual(r['metrics']['completed_bidder_cycles'],0)
        for name in ('capacity_pause_resume','sticky_draining','whole_queue_intervals','priority_under_load',
                     'restart_reconnect','unknown_reconciliation','attributable_realized_profit'):
            self.assertIn(name,c['missing'])
        self.assertEqual(len(r['metrics']['stopped_pending_work']),1)
        self.assertEqual(r['metrics']['stopped_pending_work'][0]['operation'],'transfer_list')
        self.assertEqual(r['metrics']['stopped_pending_work'][0]['state'],'WAITING')

    def test_c4_no_fabricated_enrollment_expiry_timer_or_50_auction_sample(self):
        r=audit(LIVE)
        self.assertEqual(r['metrics']['enrolled_this_run'],0)
        self.assertEqual(r['metrics']['watched_rows'],0)
        self.assertIn('enrolled_status_coverage',r['criteria'][4]['missing'])
        self.assertIn('natural_expiry_observations',r['criteria'][4]['missing'])
        self.assertIn('natural_funds_observations',r['criteria'][4]['observed'])

    def test_c5_c6_http_success_and_offline_pass_cannot_make_full_e2e_pass(self):
        r=audit(LIVE)
        self.assertEqual(r['status'],'PARTIAL/NOT FULL PASS')
        self.assertEqual(r['criteria'][5]['status'],'LIVE-UNVERIFIED')
        self.assertIn('offline_regressions',r['criteria'][5]['observed'])
        self.assertIn('all_transaction_and_maintenance_branches',r['criteria'][5]['missing'])
        self.assertEqual(r['criteria'][6]['status'],'PASS')
        self.assertEqual(set(r['unverified']),{n for c in r['criteria'] for n in c['missing']})
        outcome=json.loads((OUT/'outcome.json').read_text())
        # Preserve the sealed historical report while permitting additional
        # diagnostics in a newer assessor. Verify its actual contracts/results.
        for key in ('schema','task','status','live_window','criteria','unverified','failures'):
            self.assertEqual(outcome[key],r[key],key)
        for key,value in outcome['metrics'].items():self.assertEqual(value,r['metrics'][key],key)

    def test_c7_sealed_captures_failure_and_all_process_exit_evidence(self):
        r=audit(LIVE);self.assertEqual(r['criteria'][7]['status'],'PASS')
        index=json.loads((OUT/'evidence-index.json').read_text())
        self.assertEqual(index['kind'],'SEALED_EXPERIMENT_EVIDENCE')
        for row in index['files']:
            p=(ROOT/row['path']).resolve();self.assertTrue(p.is_relative_to(OUT.resolve()))
            self.assertNotIn(p.suffix,{'.py','.js','.cjs','.md'})
            self.assertEqual(p.stat().st_size,row['bytes'])
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),row['sha256'])
        shutdown=load_evidence(OUT/'shutdown.jsonl')
        self.assertIs(shutdown[0]['mutations_enabled'],False)
        self.assertEqual(shutdown[0]['native_requests'],0)
        self.assertEqual(shutdown[1]['actor_or_maintenance_processes'],0)

    def test_strict_full_acceptance_exits_nonzero_and_lists_missing_evidence(self):
        p=subprocess.run([sys.executable,'tests/check_final_live_00212.py'],cwd=ROOT,
            capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,1,p.stderr)
        r=json.loads(p.stdout);self.assertEqual(r['status'],'PARTIAL/NOT FULL PASS')
        self.assertEqual({c['index'] for c in r['criteria']},set(range(8)))
        self.assertTrue(any(c['missing'] for c in r['criteria']))

    def corrupt(self,change):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        shutil.copy2(LIVE/'supervisor.jsonl',root/'supervisor.jsonl')
        rows=load_evidence(LIVE/'native.jsonl');change(rows)
        e=Evidence(root/'native.jsonl')
        try:
            for row in rows:e.append(row['kind'],**{k:v for k,v in row.items() if k not in
                {'kind','seq','previous','evidence_sha256','at'}})
        finally:e.close()
        return root

    def test_reject_fixtures_wrong_filters_duplicate_commands_even_when_resealed(self):
        def fixture(rows):next(x for x in rows if x.get('response'))['response']['freshness']['source']='fixture'
        def duplicate(rows):rows.append(deepcopy(next(x for x in rows if x.get('response'))))
        def wrong_wire(rows):
            r=next(x for x in rows if x.get('command',{}).get('operation')=='search')
            r['response']['result']['network'][0]['query']['macr']=9999
        for change in (fixture,duplicate,wrong_wire):
            with self.subTest(change=change),self.assertRaises(ValueError):audit(self.corrupt(change))


class IndependentBulkAssessment(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name);self.clock=Clock();self.page=BulkPage(self.path,self.clock)
        self.f=Foundation(self.page,context=CONTEXT,journal_path=self.path/'journal.sqlite3',fixture=True,
            now=self.clock.now,clock=self.clock.monotonic,sleep=self.clock.sleep)
        self.addCleanup(self.page.close);self.addCleanup(self.f.close)

    def capture(self,op):
        self.assertEqual(self.f.bulk(op)['status'],'CONFIRMED')
        c=self.page.writes[-1];before=self.f.adapter.responses[c['params']['before_read_id']]
        e=next(e for e in reversed(self.f.registry.events()) if e.get('command_id')==c['id'] and e.get('reason')=='VERIFIED')
        return dict(command=c,response=self.page.store.result(c['id'])),before,e['readback']

    def test_bulk_clear_requires_actual_targets_absent_and_unsold_survivors_retained(self):
        w,b,a=self.capture('clear_sold');self.assertTrue(bulk_proof(w,b,a))
        for changed in ('target_present','survivor_missing','not_independent','not_complete'):
            v=deepcopy(a)
            if changed=='target_present':v['result']['auctions'].append(deepcopy(b['result']['auctions'][0]))
            if changed=='survivor_missing':v['result']['auctions'].pop()
            if changed=='not_independent':v['command_id']=b['command_id']
            if changed=='not_complete':v['coverage']['complete']=False
            with self.subTest(changed=changed),self.assertRaises(ValueError):bulk_proof(w,b,v)

    def test_relist_requires_unchanged_stored_prices_new_trade_and_actual_one_hour(self):
        self.page.transfer_items=self.page.transfer_items[2:]
        w,b,a=self.capture('relist_all');self.assertTrue(bulk_proof(w,b,a))
        target=w['command']['params']['expected_item_ids'][0]
        for field,value in [('expires',3599),('starting_bid',151),('buy_now_price',500),
                            ('trade_id',b['result']['auctions'][0]['trade_id'])]:
            v=deepcopy(a);row=next(x for x in v['result']['auctions'] if x['item']['item_id']==target);row[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):bulk_proof(w,b,v)


if __name__=='__main__':unittest.main(verbosity=2)
