"""Independent live evidence and adversarial tests for all eight criteria."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.e2e_live_v2.audit import inspect,read_run,read_resolution,load,ROOT,DIRECTORY,RESOLUTION,FINAL

from fc_access.evidence import evidence_hashes

class CompleteArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=inspect()
    def test_0_finite_serialization_ownership_and_preservation(self):
        r=self.r;self.assertTrue(all(w['closed'] for w in r['windows']));self.assertEqual(r['actual_bid_writes_total'],2)
        self.assertEqual(r['windows'][2]['limits']['reads'],40);self.assertEqual(r['windows'][3]['mutations'],0)
        self.assertEqual(r,load(FINAL/'report.json'))
        for name,digest in evidence_hashes(load(FINAL/'manifest.json')['files']).items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
    def test_1_acquirer_minimum_actual_body_and_independent_balance(self):
        r=self.r;p=r['pricing'];self.assertEqual((p['target'],p['tax'],p['X'],p['cap'],p['opening_minimum']),(2800,140,500,2100,800))
        self.assertEqual(p['estimate']['sample_count'],12);self.assertIn(['outlier',9],p['estimate']['rejected'])
        bid=next(t for t in r['timeline'] if t['operation']=='bid');self.assertEqual(bid['network'][0]['bid_amount'],800)
        self.assertEqual((r['initial_spendable'],r['after_verified_opening_spendable']),(16268,15468))
    def test_2_already_leading_holds_have_zero_additional_writes(self):
        holds=[e for e in self.r['journal_events'] if e['reason']=='HOLD'];self.assertEqual(len(holds),2)
        self.assertTrue(all(e['data']['additional_write'] is False and e['data']['bid_writes']==1 for e in holds))
        self.assertEqual(len([t for t in self.r['timeline'] if t['operation']=='bid']),1)
    def test_3_real_competition_and_unwitnessed_rebid_are_distinct(self):
        r=self.r;self.assertEqual(r['resolution']['timeline'][0]['rows'][0]['current_bid'],1200)
        self.assertTrue(r['active_outbid_rebid'].startswith('LIVE_UNVERIFIED'))
        self.assertFalse([e for e in r['journal_events'] if e['reason']=='REBID_INTENT'])
    def test_4_real_timings_expiry_and_interrupted_cycle_not_fabricated(self):
        r=self.r;t=r['timing'];self.assertEqual(len(t['bulk_refresh_native_ms']),5)
        self.assertTrue(all(0<x<25000 for x in t['bulk_refresh_native_ms']));self.assertGreater(t['bid_native_ms'],0)
        self.assertGreater(t['ack_to_independent_watched_ms'],0);self.assertEqual(len(t['expiry']),4)
        self.assertTrue(t['target_25s_cycle'].startswith('LIVE_UNVERIFIED'));self.assertEqual(r['timer_extension'],'LIVE_UNVERIFIED')
        self.assertFalse((DIRECTORY/'watched-cycle-4.json').exists())
    def test_5_exact_loss_and_coin_return_not_missing_coverage(self):
        r=self.r;self.assertEqual(r['resolution']['state'],'LOST');self.assertEqual(r['returned_available_coins'],800)
        self.assertEqual((r['final_spendable'],r['net_spendable_change'],r['actual_paid_acquisition_cost']),(16268,0,0))
        self.assertEqual(r['unresolved_active_bids'],[]);self.assertEqual(len(r['verified_losses']),1)
        self.assertEqual(r['resolution']['lite_definition_id'],0);self.assertTrue(r['resolution']['after_original_window'])
    def test_6_no_conclusive_won_item_means_no_handoff_or_profit_claim(self):
        r=self.r;self.assertEqual(r['verified_wins'],[]);self.assertEqual((r['move_writes'],r['list_writes']),(0,0))
        self.assertTrue(r['won_resale_handoff'].startswith('LIVE_UNVERIFIED'))
        self.assertIsNone(r['completed_sales']);self.assertIsNone(r['realized_profit'])
    def test_7_all_commands_privacy_and_bounded_remaining_work(self):
        r=self.r;self.assertEqual(len(r['command_timeline']),44);self.assertEqual(len({t['command_id'] for t in r['command_timeline']}),44)
        self.assertEqual(r['command_timeline'],load(FINAL/'timeline.json'));self.assertEqual(r['gross_coin_reservations_total'],1500)
        self.assertEqual(r['unsold_cards_created'],[]);self.assertEqual(len(r['unresolved_historical_acceptance']),1)
        c=r['bounded_continuation']['needed_for_remaining_branches'];self.assertEqual((c['new_auctions_max'],c['bid_writes_max'],c['seconds_max']),(1,2,900))
        forbidden={'password','cookie','cookies','token','access_token','authorization','sid','persona_id','email','username','x-ut-sid'}
        def walk(v):
            if isinstance(v,dict):
                self.assertFalse({k.lower() for k in v}&forbidden)
                for x in v.values():walk(x)
            elif isinstance(v,list):
                for x in v:walk(x)
        walk(r)
    def copy(self,source,dest):shutil.copytree(source,dest,ignore=shutil.ignore_patterns('live.sqlite','*-wal','*-shm'))
    def update_result(self,directory,stage,change):
        path=directory/(stage+'.json');a=load(path);change(a['response']);path.write_text(json.dumps(a))
        db=sqlite3.connect(directory/'live-final.sqlite')
        column='stage' if directory.name=='live' else 'operation'
        db.execute('UPDATE commands SET result=? WHERE '+column+'=?',(json.dumps(a['response']),stage));db.commit();db.close()
    def test_validator_rejects_fake_leading_even_if_capture_and_ledger_both_changed(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)/'live';self.copy(DIRECTORY,d)
            def change(r):
                for rows in ('rows','wire_rows'):r[rows][0]['bid_state']='outbid'
            self.update_result(d,'watched-after-opening',change)
            with self.assertRaisesRegex(ValueError,'leading_not_proved'):read_run(d)
    def test_validator_rejects_bid_body_amount_not_equal_to_actual_minimum(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)/'live';self.copy(DIRECTORY,d)
            self.update_result(d,'opening-1',lambda r:r['network'][0].update(bid_amount=850))
            with self.assertRaisesRegex(ValueError,'actual_bid_amount_missing_or_wrong'):read_run(d)
    def test_validator_rejects_invented_terminal_state_or_missing_coverage(self):
        for fake in ('missing','won'):
            with self.subTest(fake=fake),tempfile.TemporaryDirectory() as td:
                d=Path(td)/'resolution';self.copy(RESOLUTION,d)
                def change(r):
                    if fake=='missing':r['rows']=[];r['wire_rows']=[]
                    else:
                        for rows in ('rows','wire_rows'):r[rows][0]['bid_state']='highest'
                self.update_result(d,'status',change)
                with self.assertRaisesRegex(ValueError,'terminal_independent_rows_missing|terminal_loss_not_witnessed'):read_resolution(self.r['identity'],d)

if __name__=='__main__':unittest.main(verbosity=2)
