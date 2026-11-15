"""Current stopped item-12 evidence, including the post-repair continuation.

These checks validate real artifacts and honest coverage. Strict live acceptance
remains a separate nonzero command whenever a required natural event is absent.
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
from fc_access.production_v1.contracts import MUTATIONS,stamp
from record_final_series_00212 import actor_count


class CurrentContinuation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s=selected();cls.r=audit_series(ROOT/cls.s['latest'],ROOT/cls.s['checkpoint'])
        cls.saved=json.loads((ROOT/cls.s['outcome']).read_text(encoding='utf8'))
        cls.criteria={c['index']:c for c in cls.r['criteria']}
        cls.stop=load_evidence(ROOT/cls.s['checkpoint'])
        cls.export=next(r['data'] for r in cls.stop if r['kind']=='DURABLE_EXPORT')
        cls.captures=[]
        for window in cls.r['windows']:
            cls.captures += [r for r in load_evidence(Path(window['path'])/'native.jsonl') if r['kind']=='DISPATCH_RESULT']

    def test_criterion_0_resume_uses_original_history_one_executor_and_consumed_bounds(self):
        self.assertEqual(self.criteria[0]['status'],'PASS')
        latest=ROOT/self.s['latest'];rows=load_evidence(latest/'supervisor.jsonl')
        manifest=next(r['manifest'] for r in rows if r['kind']=='RUN_STARTED')
        self.assertIsNotNone(manifest.get('predecessor'))
        self.assertEqual(manifest['context']['platform'],'pc');self.assertEqual(manifest['context']['game'],'fc27')
        self.assertAlmostEqual(manifest['prior_active_wall_seconds'],sum(w['seconds'] for w in self.r['windows'][:-1]),places=5)
        self.assertLessEqual(self.r['metrics']['active_seconds'],7200)
        self.assertEqual(manifest['bounds']['max_enrollments'],12)
        self.assertGreater(manifest['preflight_request_charge'],0)
        spans=sorted((stamp(w['started']),stamp(w['finished'])) for w in self.export['native'] if w['started'] and w['finished'])
        self.assertTrue(all(b[0]>=a[1] for a,b in zip(spans,spans[1:])))

    def test_criterion_1_native_transactions_and_admission_coverage_never_promote_missing_branches(self):
        observed=self.criteria[1]['observed']
        self.assertTrue({'fresh_valuation','minimum_initial_bid','leading_hold','minimum_rebid',
            'terminal_won','terminal_lost','exact_owned_paid'}<=set(observed))
        for name in REQUIRED[1]:
            self.assertTrue(observed[name] if name in observed else name in self.r['unverified'])
        bids=[r for r in self.captures if r['command']['operation']=='bid' and r['response'] and r['response']['result']['success']]
        self.assertTrue(bids)
        for r in bids:
            p=r['command']['params'];self.assertEqual(p['amount'],p['minimum']);self.assertLessEqual(p['amount'],p['cap'])
            self.assertNotEqual(p['status_read_id'],p['balance_read_id'])

    def test_criterion_2_actual_sold_clear_and_expired_relist_have_complete_independent_readbacks(self):
        self.assertEqual(self.criteria[2]['status'],'PASS')
        self.assertEqual(set(self.criteria[2]['observed']),set(REQUIRED[2]))
        clear=[r for r in self.captures if r['command']['operation']=='clear_sold' and r['response'] and r['response']['result']['success']]
        self.assertTrue(clear)
        for r in clear:
            target=[n for n in r['response']['result']['network'] if n['method']=='DELETE']
            self.assertEqual(len(target),1);self.assertTrue(target[0]['body_empty'])
            self.assertTrue(r['command']['params']['expected_item_ids'])
        success=[r for r in self.captures if r['command']['operation']=='relist_all' and r['response'] and r['response']['result']['success']]
        self.assertTrue(success)
        self.assertTrue(all(r['command']['params']['expected_expired_count']>0 for r in success))

    def test_criterion_3_recovery_keeps_original_diagnostic_and_settlement_does_not_invent_net_proceeds(self):
        self.assertIn('unknown_reconciliation',self.criteria[3]['observed'])
        checkpoint=ROOT/self.s['checkpoint'];db=sqlite3.connect(checkpoint.parent.joinpath('state-backup/journal.sqlite3').resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
        try:
            self.assertEqual(db.execute('select state,incompatible from bulk_writes_v1 where id=?',
                ('869ed95434e70ea0d7ba599945751fd2',)).fetchone(),('RECONCILED',1))
            self.assertEqual(db.execute('select count(*) from bulk_recoveries_v1').fetchone()[0],1)
        finally:db.close()
        settlement=[e for e in self.export['registry'] if e.get('kind')=='SOLD_SETTLEMENT']
        self.assertTrue(settlement)
        self.assertTrue(any(e['observed_gross_price']==2000 and e['item']['definition_id']==246420 for e in settlement))
        for e in settlement:
            if e['reason']=='ACTUAL_SETTLED_PROCEEDS_UNPROVEN':
                self.assertIsNone(e['actual_settled_proceeds']);self.assertIsNone(e['realized_profit'])
        if 'attributable_realized_profit' not in self.criteria[3]['observed']:
            self.assertIn('attributable_realized_profit',self.r['unverified'])

    def test_criterion_4_actual_status_samples_and_natural_funds_do_not_fabricate_fifty_auctions_or_timer_reset(self):
        self.assertEqual(self.criteria[4]['status'],'PASS')
        self.assertGreaterEqual(self.r['metrics']['enrolled_in_experiment'],3)
        samples=[s for w in self.r['metrics']['per_window'] for v in w['metrics']['enrolled_status_samples'].values() for s in v]
        self.assertTrue(samples);self.assertTrue(all(s['read_id'] and isinstance(s['expires'],int) for s in samples))
        observed_counts=[len(r['response']['result']['auctions']) for r in self.captures if r['command']['operation']=='watched' and r['response'] and r['response']['result']['success']]
        if self.r['metrics']['actual_50_auction_sample']:self.assertGreaterEqual(max(observed_counts),50)
        else:self.assertLess(self.r['metrics']['enrolled_in_experiment'],50)

    def test_criterion_5_full_live_pass_requires_all_named_proofs_even_with_offline_success(self):
        missing=[n for c in self.r['criteria'] for n in c['missing']]
        expected='PARTIAL/NOT FULL PASS' if missing else 'FULL PASS'
        self.assertEqual(self.r['status'],expected)
        r=subprocess.run([sys.executable,'tests/check_final_series_00212.py'],cwd=ROOT,capture_output=True,text=True,timeout=40)
        self.assertEqual(r.returncode,1 if missing else 0,r.stdout+r.stderr)
        self.assertIn('offline_regressions',self.criteria[5]['observed'])

    def test_criterion_6_saved_report_preserves_every_failure_and_exact_missing_live_claim(self):
        self.assertEqual(self.saved['criteria'],self.r['criteria'])
        self.assertEqual(self.saved['unverified'],self.r['unverified']);self.assertEqual(self.saved['failures'],self.r['failures'])
        self.assertEqual(set(self.r['unverified']),{n for c in self.r['criteria'] for n in c['missing']})
        self.assertTrue({'schema_unrecognized','invalid_preconditions','ambiguous_network','bulk_contract_changed'}<=
            {f['error'] for f in self.r['failures']})

    def test_criterion_7_current_stop_and_append_only_captures_are_real_and_no_actor_is_left_running(self):
        self.assertEqual(self.criteria[7]['status'],'PASS');self.assertEqual(actor_count(),0)
        self.assertFalse(next(e for e in self.stop if e['kind']=='READ_ONLY_SERVICE_RESTORED')['mutations_enabled'])
        index=json.loads((ROOT/self.s['evidence_index']).read_text())
        for entry in index['files']:
            p=ROOT/entry['path'];self.assertTrue(p.suffix in {'.sqlite3','.jsonl'} or p.name.startswith('regressions'))
            data=p.read_bytes();self.assertEqual(len(data),entry['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'])
            if p.suffix=='.jsonl':load_evidence(p)
        ids=[r['command']['id'] for r in self.captures];self.assertEqual(len(ids),len(set(ids)))


if __name__=='__main__':unittest.main(verbosity=2)
