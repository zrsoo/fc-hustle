"""002-07 behavioral acceptance. Synthetic native responses; no EA operations.

Run normally to validate behavior. --record also exports the tested timelines.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from actors_fixture import create, auction
from test_bidding_v1 import NOW, SCOPE, status, balance, fresh, cid
from test_00206_capacity import observe, terminal
from fc_access.actors_v1.actors import Acquirer, Bidder
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.enrollment import projection
from fc_access.actors_v1.native import Mailbox, Broker
from fc_access.actors_v1.operator import inspect
from fc_access.actors_v1.occupancy import read as read_occupancy
from fc_access.bidding_v1 import capacity
from fc_access.bidding_v1.contracts import Coverage, Snapshot, State
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.bidding_v1.journal import Journal
from fc_access.bulk_transfer_v1.contracts import reconcile as reconcile_maintenance
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.contracts import Search

TIMELINES = {}


class EnrollmentAcceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)

    def api(self, **settings):
        f, p, c = create(self.path)
        self.addCleanup(p.close); self.addCleanup(f.close)
        cfg = Config(native_interval_seconds=0, **settings)
        return f, p, c, Acquirer(f, cfg), Bidder(f, cfg)

    def capture(self, name, f, p):
        self.assertEqual(p.real_account_writes, 0)
        TIMELINES[name] = dict(source='synthetic', registry=[e for e in f.registry.events()
            if e['kind'] in {'ACTOR', 'ENROLLMENT', 'DECISION', 'CREDITS'}],
            journal=[e for e in f.journal.trace(scope=f.registry.scope) if e['reason'] in {
                'ENROLLED', 'DRAINING', 'DRAINED', 'WON_VERIFIED', 'LOST_VERIFIED', 'CAPACITY_OBSERVED'}],
            bid_amounts=[v['params']['amount'] for v in p.calls if v['operation']=='bid'])

    @staticmethod
    def candidate(p, n):
        p.candidate = auction(123, 15000, n)
        p.candidate['starting_bid'] = 800

    @staticmethod
    def unknown(p):
        p.transfer_coverage = dict(complete=False, has_more=None, transfer_list=dict(
            reason='TRANSFER_LIST_UNKNOWN', wire_count=0, callback_count=0,
            repository_count=0, repository_end_of_list=False))

    def test_c0_c1_c3_lost_releases_capacity_missing_status_does_not(self):
        f,p,c,a,b = self.api(max_enrolled_auctions=1, max_total_pipeline_slots=1)
        a.cycle(); b.cycle()
        first = deepcopy(p.candidate)
        self.candidate(p, 2)
        a.cycle()
        self.assertEqual(p.bid_calls, 1)
        self.assertEqual(projection(f.registry)['capacity_reason'], 'QUEUE_FULL')
        p.watched = []; b.cycle(); a.cycle()
        self.assertEqual(p.bid_calls, 1, 'absence in watched does not release a slot')
        first.update(trade_state='closed', expires=0, bid_state='outbid')
        p.watched = [first]; b.cycle()
        self.assertFalse(f.queue.entries)
        self.assertTrue(projection(f.registry)['capacity_paused'], 'history changes at the next capacity check')
        a.cycle()
        self.assertEqual(p.bid_calls, 2)
        self.assertFalse(projection(f.registry)['capacity_paused'])
        self.assertEqual(capacity.status(f.journal, f.registry.scope, now=c.now())['total'], 1)
        self.capture('lost_release', f, p)

    def test_c0_c1_c3_sale_and_balance_increase_do_not_release_sold_present(self):
        f,p,c,a,b = self.api(max_total_pipeline_slots=1, max_transfer_list_occupied=1)
        sold = auction(123, 15000, 100)
        p.transfer_items = [sold]
        a.cycle(); self.assertEqual(p.bid_calls, 0)
        sold.update(trade_state='closed', bid_state='sold', current_bid=15000, expires=0)
        p.credits += 15000
        a.cycle(); self.assertEqual(p.bid_calls, 0)
        self.assertEqual(capacity.status(f.journal, f.registry.scope, now=c.now())['total'], 1)
        p.transfer_items = []
        self.unknown(p); a.cycle()
        self.assertEqual(p.bid_calls, 0, 'clear acknowledgement or incomplete absence is not release proof')
        self.assertTrue(projection(f.registry)['capacity_paused'])
        p.transfer_coverage = None
        a.cycle()
        self.assertEqual(p.bid_calls, 1)
        self.assertFalse(projection(f.registry)['capacity_paused'])
        self.capture('sold_clear_verified', f, p)

    def test_c0_c3_paused_acquirer_does_not_gate_reconciliation_rebids_or_maintenance(self):
        f,p,c,a,b = self.api(max_total_pipeline_slots=1)
        p.failure = TimeoutError('synthetic lost bid response')
        a.cycle()
        self.assertTrue(a.pending())
        p.failure = None
        self.unknown(p); a.cycle()
        self.assertEqual(p.bid_calls, 1)
        self.assertEqual(projection(f.registry)['capacity_reason'], 'TRANSFER_LIST_UNKNOWN')
        b.cycle()
        self.assertFalse(a.pending(), 'Bidder reconciles the ambiguous opening while capacity is unknown')
        p.candidate.update(current_bid=900, bid_state='outbid')
        p.watched = [deepcopy(p.candidate)]
        b.cycle()
        self.assertEqual([v['params']['amount'] for v in p.calls if v['operation']=='bid'], [800,950])
        b.cycle()
        p.transfer_coverage = None
        a.cycle()
        self.assertEqual(projection(f.registry)['capacity_reason'], 'PIPELINE_FULL')
        p.candidate.update(current_bid=1000, bid_state='outbid')
        p.watched = [deepcopy(p.candidate)]; b.cycle()
        self.assertEqual(p.bid_calls, 3, 'existing bids continue while combined capacity is full')
        # The same shared broker continues dispatching maintenance and urgent
        # reconciliation commands; no global pause flag or lock was installed.
        box = Mailbox(self.path/'native.sqlite3'); self.addCleanup(box.close)
        broker = Broker(box, f, a.config, now=c.now, clock=c.monotonic, sleep=c.sleep)
        broker.initialize()
        for cid,op,role in [('1'*32,'transfer_list','maintenance'),('2'*32,'watched','reconciliation')]:
            box.enqueue(f.adapter.envelope(cid,op,{}), role, now=c.now())
        self.assertEqual(broker.run_one()['command_id'], '2'*32)
        self.assertEqual(broker.run_one()['command_id'], '1'*32)
        self.assertEqual(box.db.execute("SELECT count(*) FROM work WHERE state='DONE'").fetchone(), (2,))
        self.assertTrue(projection(f.registry)['capacity_paused'])
        self.capture('independent_work', f, p)

    def test_c0_c1_selling_maintenance_contracts_continue_at_capacity(self):
        f,p,c,a,b = self.api(max_total_pipeline_slots=2)
        sold = auction(123,15000,100)
        sold.update(trade_state='closed',bid_state='sold',current_bid=15000,expires=0)
        expired = auction(123,15000,101)
        expired.update(trade_state='expired',current_bid=0,expires=0)
        p.transfer_items = [sold,expired]; a.cycle()
        self.assertTrue(projection(f.registry)['capacity_paused'])
        def bulk(row):
            return {k:row[k] for k in ('trade_id','starting_bid','current_bid','buy_now_price','expires','trade_state','bid_state')} | dict(
                item_id=row['item']['item_id'], definition_id=row['item']['definition_id'], trade_owner=True)
        before = [bulk(sold),bulk(expired)]
        relisted = deepcopy(before)
        relisted[1].update(trade_id='trade:'+'f'*24,trade_state='active',expires=3600)
        at=c.now(); times=dict(mutation_started=at.isoformat(),mutation_ended=at.isoformat(),
            read_started=(at+timedelta(seconds=1)).isoformat(),read_ended=(at+timedelta(seconds=1)).isoformat())
        result = reconcile_maintenance('bulk_relist_all', before, relisted, **times)
        self.assertEqual((result['outcome'],result['occupancy_delta']), ('CONFIRMED',0))
        p.transfer_items[1].update(trade_id=relisted[1]['trade_id'],trade_state='active',expires=3600)
        a.cycle(); self.assertEqual(p.bid_calls,0, 'relisting preserves physical occupancy')
        result = reconcile_maintenance('bulk_clear_sold', relisted, relisted[1:], **times)
        self.assertEqual((result['outcome'],result['occupancy_delta']), ('CONFIRMED',-1))
        # Bulk receipt itself cannot alter Acquirer's ledger or state. A fresh
        # complete Transfer List, through the existing read seam, is required.
        self.assertEqual(capacity.status(f.journal,f.registry.scope,now=c.now())['total'],2)
        p.transfer_items = p.transfer_items[1:]
        a.cycle(); self.assertEqual(p.bid_calls,1)
        self.capture('selling_maintenance',f,p)

    def test_c2_c3_simultaneous_limits_drain_precedence_capacity_release_is_independent(self):
        f,p,c,a,b = self.api(max_total_pipeline_slots=1)
        p.credits = 5800
        a.cycle(); b.cycle()
        self.assertTrue(f.queue.draining)
        self.candidate(p,2)
        a.cycle()
        checks = [e for e in f.registry.events() if e.get('reason')=='CAPACITY_CHECKED']
        self.assertEqual((checks[-1]['capacity_reason'], checks[-1]['effective_reason']), ('PIPELINE_FULL','DRAINING'))
        # An increase and confirmed freeing of physical capacity do not end the
        # coin drain while any enrolled auction is unresolved.
        p.credits = 90000
        p.transfer_items = [auction(123,15000,100)]
        a.cycle(); p.transfer_items = []; a.cycle()
        self.assertTrue(f.queue.draining)
        self.assertEqual(p.bid_calls,1)
        self.assertFalse([e for e in f.journal.trace() if e['reason']=='DRAINED'])
        first = p.watched[0]
        first.update(trade_state='closed',bid_state='outbid',expires=0)
        b.cycle()
        self.assertTrue(f.queue.draining)
        self.assertEqual(p.bid_calls,1)
        p.credits = 5000; a.cycle()
        self.assertFalse(projection(f.registry)['capacity_paused'])
        resumed = [e for e in f.registry.events() if e.get('reason')=='CAPACITY_RESUMED'][-1]
        self.assertEqual((resumed['draining'],resumed['effective_reason'],resumed['action']), (True,'DRAINING','HOLD'))
        self.assertTrue(f.queue.draining)
        p.credits = 90000
        a.cycle()
        self.assertEqual(p.bid_calls,2)
        self.assertFalse(f.queue.draining)
        self.capture('simultaneous_limits',f,p)

    def test_c2_c3_low_reserve_drain_is_detected_even_with_full_or_unknown_capacity(self):
        for unknown in (False,True):
            with self.subTest(unknown=unknown):
                directory = self.path/str(unknown); directory.mkdir()
                f,p,c = create(directory)
                try:
                    a=Acquirer(f,Config(max_total_pipeline_slots=1))
                    p.credits=5000
                    if unknown:self.unknown(p)
                    else:p.transfer_items=[auction(123,15000,100)]
                    a.cycle()
                    self.assertEqual(p.bid_calls,0)
                    self.assertTrue(AuctionQueue(journal=f.journal,scope=f.registry.scope).draining)
                    event=[e for e in f.registry.events() if e.get('reason')=='CAPACITY_PAUSED'][-1]
                    self.assertEqual(event['effective_reason'],'DRAINING')
                    self.assertIsNotNone(event['capacity_reason'])
                finally:f.close();p.close()

    def test_c2_c3_restart_persists_both_states_and_requires_fresh_evidence(self):
        f,p,c,a,b = self.api(max_total_pipeline_slots=1)
        p.credits = 5800; a.cycle(); b.cycle()
        self.candidate(p,2); a.cycle()
        epoch=f.registry.epoch
        restarted=Foundation(p,context=f.adapter.context,journal_path=f.journal_path,fixture=True,
            now=c.now,clock=c.monotonic,sleep=c.sleep)
        self.addCleanup(restarted.close)
        a2,b2=Acquirer(restarted,a.config),Bidder(restarted,a.config)
        self.assertGreater(restarted.registry.epoch,epoch)
        self.assertTrue(restarted.queue.draining)
        self.assertTrue(projection(restarted.registry)['capacity_paused'])
        p.credits=90000; a2.cycle()
        self.assertEqual(p.bid_calls,1)
        p.watched[0].update(trade_state='closed',expires=0,bid_state='outbid'); b2.cycle()
        self.assertTrue(restarted.queue.draining)
        self.unknown(p); a2.cycle()
        self.assertFalse(restarted.queue.draining, 'future cycle passed reserve, capacity is still independently unknown')
        self.assertTrue(projection(restarted.registry)['capacity_paused'])
        self.assertEqual(p.bid_calls,1)
        p.transfer_coverage=None; a2.cycle()
        self.assertEqual(p.bid_calls,2)
        self.assertFalse(projection(restarted.registry)['capacity_paused'])
        box=Mailbox(self.path/'native.sqlite3');self.addCleanup(box.close)
        Broker(box,restarted,a.config).initialize()
        self.assertFalse(inspect(box.path)['enrollment']['capacity_paused'])
        self.assertTrue(any(e.get('reason')=='CAPACITY_PAUSED' for e in inspect(box.path,'blocked')))
        self.capture('restart',restarted,p)

    def test_c2_c3_all_enrolled_must_be_terminal_and_only_future_fresh_cycle_can_reset(self):
        j=Journal(self.path/'journal.sqlite3',now=lambda:NOW);self.addCleanup(j.close)
        observe(j)
        q=AuctionQueue(journal=j,scope=SCOPE)
        self.assertEqual(q.admit(status(1),balance(5300),150,now=NOW),'ENROLLED')
        self.assertEqual(q.admit(status(2),balance(5300),150,now=NOW),'ENROLLED')
        self.assertTrue(q.draining)
        terminal(q,status(1),State.LOST)
        q.refresh(Snapshot((),fresh(801),Coverage(True,False,evidence_id=cid(801))),now=NOW,reset_draining=True)
        self.assertEqual(q.reserve_check(balance(90000,n=901),now=NOW,new_cycle=True),'DRAINING')
        terminal(q,status(2),State.WON,n=802)
        self.assertFalse(q.entries)
        self.assertTrue(q.draining, 'a WON counts as terminal for coins but retains a resale slot')
        self.assertEqual(capacity.status(j,SCOPE,now=NOW)['total'],1)
        self.assertEqual(q.admit(status(3),balance(90000,n=902),150,now=NOW),'DRAINING')
        self.assertEqual(q.reserve_check(balance(90000,n=903),now=NOW+timedelta(seconds=31),new_cycle=True),'DRAINING')
        self.assertEqual(q.reserve_check(balance(90000,n=900),now=NOW,new_cycle=True),'DRAINING','consumed balance cannot resume')
        self.assertEqual(q.reserve_check(balance(5000,n=904),now=NOW,new_cycle=True),'DRAINING')
        replay=AuctionQueue(journal=j,scope=SCOPE)
        self.assertTrue(replay.draining)
        self.assertIsNone(replay.reserve_check(balance(90000,n=905),now=NOW,new_cycle=True))
        self.assertEqual(replay.admit(status(3),balance(90000,n=906),150,now=NOW),'ENROLLED')

    def test_c2_candidate_reserve_failure_precedes_capacity_that_fills_during_pricing(self):
        f,p,c,a,b = self.api(max_total_pipeline_slots=1)
        p.credits=5500
        quote=f.pricing.quote
        def fill(*args,**kwargs):
            result=quote(*args,**kwargs)
            p.transfer_items=[auction(123,15000,100)]
            return result
        with patch.object(f.pricing,'quote',side_effect=fill): a.cycle()
        self.assertEqual(p.bid_calls,0)
        self.assertTrue(f.queue.draining)
        decision=[e for e in f.registry.events() if e['kind']=='DECISION'][-1]
        self.assertEqual(decision['reason'],'DRAINING')
        event=[e for e in f.registry.events() if e.get('reason')=='CAPACITY_PAUSED'][-1]
        self.assertEqual((event['capacity_reason'],event['effective_reason']),('PIPELINE_FULL','DRAINING'))
        self.capture('projected_reserve',f,p)

    def test_c2_one_shot_admission_cannot_bypass_sticky_drain_with_full_inventory(self):
        f,p,c,a,b = self.api()
        p.credits=5000
        p.transfer_items=[auction(123,15000,100+i) for i in range(50)]
        found=f.read('search',Search.discovery().params());funds=f.read('balance')
        result=f.admit(found,p.candidate['trade_id'],funds)
        self.assertEqual(result['reason'],'DRAINING')
        self.assertTrue(f.queue.draining)
        p.credits=90000;p.transfer_items=[]
        found=f.read('search',Search.discovery().params());funds=f.read('balance')
        self.assertEqual(f.admit(found,p.candidate['trade_id'],funds)['reason'],'DRAINING')
        self.assertEqual(p.bid_calls,0)

    def test_c2_reservations_exceeding_fresh_balance_still_enter_durable_draining(self):
        j=Journal(self.path/'journal.sqlite3',now=lambda:NOW);self.addCleanup(j.close)
        observe(j)
        q=AuctionQueue(journal=j,scope=SCOPE)
        self.assertEqual(q.admit(status(),balance(90000),800,now=NOW),'ENROLLED')
        self.assertEqual(q.reserve_check(balance(100,n=901),now=NOW),'DRAINING')
        self.assertTrue(AuctionQueue(journal=j,scope=SCOPE).draining)
        event=[e for e in j.trace() if e['reason']=='DRAINING'][-1]
        self.assertEqual(event['data']['spendable'],0)

    def test_c3_failed_pause_resume_or_coin_checkpoint_never_allows_unjournaled_enrollment(self):
        f,p,c,a,b=self.api(max_total_pipeline_slots=1)
        p.transfer_items=[auction(123,15000,100)]
        original=a.record
        def fail_pause(reason,**kw):
            original(reason,**kw)
            if reason=='CAPACITY_PAUSED':raise OSError('synthetic checkpoint failure')
        with patch.object(a,'record',side_effect=fail_pause):
            with self.assertRaises(OSError):a.cycle()
        self.assertIsNone(projection(f.registry),'transition and check rolled back together')
        self.assertEqual(p.bid_calls,0)
        a.cycle();self.assertTrue(projection(f.registry)['capacity_paused'])
        p.transfer_items=[]
        def fail_resume(reason,**kw):
            original(reason,**kw)
            if reason=='CAPACITY_RESUMED':raise OSError('synthetic checkpoint failure')
        with patch.object(a,'record',side_effect=fail_resume):
            with self.assertRaises(OSError):a.cycle()
        self.assertTrue(projection(f.registry)['capacity_paused'])
        self.assertEqual(p.bid_calls,0)
        a.cycle();self.assertEqual(p.bid_calls,1)
        b.cycle()
        p.credits=5000;a.cycle();self.assertTrue(f.queue.draining)
        p.watched[0].update(trade_state='closed',bid_state='outbid',expires=0);b.cycle()
        p.credits=90000
        event=f.journal._event
        def fail_drained(scope,reason,*args,**kwargs):
            event(scope,reason,*args,**kwargs)
            if reason=='DRAINED':raise OSError('synthetic coin checkpoint failure')
        with patch.object(f.journal,'_event',side_effect=fail_drained):
            with self.assertRaises(OSError):a.cycle()
        self.assertTrue(AuctionQueue(journal=f.journal,scope=f.registry.scope).draining)
        self.assertFalse([e for e in f.journal.trace() if e['reason']=='DRAINED'])
        self.assertEqual(p.bid_calls,1)


if __name__=='__main__':
    record='--record' in sys.argv
    if record:sys.argv.remove('--record')
    suite=unittest.main(verbosity=2,exit=False)
    if suite.result.wasSuccessful() and record:
        destination=ROOT/'docs/research/002/002-07/timelines.json'
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(dict(schema=1,source='synthetic',scenarios=TIMELINES),indent=2)+'\n',encoding='utf8')
    sys.exit(0 if suite.result.wasSuccessful() else 1)
