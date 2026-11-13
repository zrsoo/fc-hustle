"""Validate truthful retained evidence, including explicit missing live proof.

Passing this audit is NOT full live acceptance. The separate acceptance CLI
intentionally exits nonzero while the Acquirer/leading-HOLD proof is missing.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.e2e_v1.audit import inspect,load
from fc_access.e2e_v1.server import DIRECTORY,ROOT,validate_result

class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.report=inspect();cls.retained=load(DIRECTORY/'report.json')
    def test_all_actual_commands_reconciled_to_closed_ledger(self):
        self.assertEqual(self.report,self.retained)
        self.assertEqual(self.report['timeline'],load(DIRECTORY/'timeline.json'))
        self.assertEqual(self.report['command_count'],18);self.assertEqual(self.report['native_request_count'],18)
        self.assertEqual(self.report['bid_writes'],1);self.assertEqual(self.report['gross_coin_reservations'],700)
        self.assertTrue(load(DIRECTORY/'closed.json')['health']['stopped'])
    def test_real_filters_five_comparables_caps_and_opening_proof_boundary(self):
        r=self.report;p=r['pricing']
        self.assertEqual((p['target'],p['tax'],p['cap'],p['opening_minimum']),(2200,110,1500,700))
        self.assertEqual(p['estimate']['sample_count'],15)
        self.assertIn(['outlier',5],p['estimate']['rejected'])
        bid=next(x for x in r['timeline'] if x['operation']=='bid')
        self.assertEqual(bid['params']['amount'],700);self.assertEqual(bid['network'][0]['method'],'PUT')
        self.assertEqual(bid['state'],'ACKNOWLEDGED')
        self.assertIn('UNRESOLVED',r['opening']);self.assertEqual(r['unresolved_bid_commands'],[bid['id']])
    def test_no_false_live_hold_or_rebid(self):
        r=self.report
        self.assertTrue(r['leading_hold'].startswith('UNVERIFIED'));self.assertTrue(r['rebid'].startswith('UNVERIFIED'))
        self.assertFalse([x for x in r['events'] if x['reason'] in ('HOLD','REBID_INTENT')])
        self.assertIn('PERSONAL_OUTBID_UNVERIFIED',r['competition'])
        self.assertEqual(len([x for x in r['timeline'] if x['operation']=='bid']),1)
    def test_measured_timing_does_not_invent_timer_extension_or_queue_cycle(self):
        r=self.report
        self.assertEqual(len(r['watchlist_refresh_ms']),4)
        self.assertTrue(all(0<v<25000 for v in r['watchlist_refresh_ms']))
        self.assertGreater(r['bid_native_ms'],0);self.assertGreater(r['bid_host_ms'],r['bid_native_ms'])
        self.assertGreater(r['opening_to_watch_readback_ms'],0)
        self.assertTrue(r['timer_extension'].startswith('UNVERIFIED'));self.assertTrue(r['queue_25_second_cycle'].startswith('UNVERIFIED'))
        self.assertGreaterEqual(len(r['expiry_observations']),4)
    def test_account_reconciliation_and_missing_coverage_not_loss(self):
        r=self.report
        self.assertEqual((r['initial_spendable'],r['final_spendable'],r['observed_spendable_delta']),(16268,16268,0))
        for key in ('confirmed_paid_cost','held_coins','returned_coins','completed_sales','realized_profit'):self.assertIsNone(r[key])
        self.assertEqual(r['terminal_outcome'],'UNKNOWN_NOT_LOST');self.assertEqual(r['verified_losses'],[]);self.assertEqual(r['verified_wins'],[])
    def test_no_handoff_without_conclusive_win_and_physical_identity(self):
        r=self.report
        self.assertEqual(r['new_verified_owned_cards'],[]);self.assertEqual(r['transfer_mutations'],0);self.assertEqual(r['listing_mutations'],0)
        self.assertTrue(r['won_item_handoff'].startswith('UNVERIFIED'))
        self.assertFalse([x for x in r['timeline'] if x['operation'] in ('move','list')])
    def test_preservation_privacy_manifest_and_exact_continuation(self):
        for name,h in load(DIRECTORY/'entry.json')['preserve'].items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),h,name)
        for name,h in load(DIRECTORY/'manifest.json')['files'].items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),h,name)
        forbidden={'password','cookies','cookie','authorization','token','access_token','sid','account_id','persona_id','email','username','x-ut-sid'}
        def check(v):
            if isinstance(v,dict):
                self.assertFalse(set(k.lower() for k in v)&forbidden)
                for x in v.values():check(x)
            elif isinstance(v,list):
                for x in v:check(x)
        check(self.retained)
        for t in self.report['timeline']:validate_result(load(DIRECTORY/(t['stage']+'.json'))['response'])
        c=self.report['continuation'];self.assertEqual(c['stage_1']['mutations_max'],0);self.assertEqual(c['stage_1']['reads_max'],4)
        self.assertEqual(c['stage_2']['auctions_max'],1);self.assertEqual(c['stage_2']['bid_writes_max'],2)
        self.assertEqual(self.report['missing_required_live_criteria'],[1,2])
    def test_validator_detects_tampered_missing_readback_and_relabelled_history(self):
        with tempfile.TemporaryDirectory() as t:
            dest=Path(t)/'capture';shutil.copytree(DIRECTORY,dest,ignore=shutil.ignore_patterns('*-shm','*-wal','live.sqlite'))
            capture=dest/'watched-after-opening.json';r=load(capture);r['response']['rows']=[copy.deepcopy(load(DIRECTORY/'availability-1.json')['response']['rows'][0])]
            capture.write_text(json.dumps(r))
            with self.assertRaises(AssertionError):inspect(dest)
            shutil.copy2(DIRECTORY/'watched-after-opening.json',capture)
            capture=dest/'balance-before.json';r=load(capture);r['response']['network'][0]['started_at']='2026-11-12T00:00:00Z';capture.write_text(json.dumps(r))
            with self.assertRaises((AssertionError,ValueError)):inspect(dest)

if __name__=='__main__':unittest.main(verbosity=2)
