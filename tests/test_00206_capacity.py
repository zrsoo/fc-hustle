"""002-06 behavioral acceptance; isolated SQLite and synthetic native responses.

Run independently: python tests/test_00206_capacity.py
Real process deaths exercise commit/rollback boundaries, without account access.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
from test_bidding_v1 import NOW, SCOPE, OWNER, cid, status, balance, fresh, intent
from native_price_fixture import auction
from actors_fixture import create
from fc_access.bidding_v1.contracts import State, Snapshot, Coverage, BidResult, Outcome
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.bidding_v1.journal import Journal
from fc_access.bidding_v1 import capacity
from fc_access.actors_v1.actors import Acquirer, Bidder
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.occupancy import read as read_occupancy
from fc_access.production_v1.contracts import Search


def inventory(n):
    return [auction(123, 15000, 1000+i) for i in range(n)]


def observe(j, rows=(), n=700, at=NOW, scope=SCOPE):
    return capacity.observe(j, scope, rows, read_id=cid(n), network_at=at, now=at)


def counters(j, scope=SCOPE, at=NOW):
    s = capacity.status(j, scope, now=at)
    return s['occupied'], s['pending_resale'], s['unresolved'], s['total']


def terminal(q, s, state=State.WON, n=800, at=NOW):
    row = replace(s, state=state, freshness=fresh(n, at), current_bid=150,
        owned_item_id=s.identity.item_id if state == State.WON else None,
        paid=150 if state == State.WON else None)
    return q.refresh(Snapshot((row,), fresh(n, at), Coverage(False, None)), now=at)


class CapacityAcceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.db = self.path/'journal.sqlite3'
        self.balance_read = 10000

    def journal(self, **kwargs):
        j = Journal(self.db, now=lambda: NOW, **kwargs)
        self.addCleanup(j.close)
        return j

    def queue(self, j, **kwargs):
        return AuctionQueue(journal=j, scope=SCOPE, reserve=0, **kwargs)

    def enroll(self, q, n):
        self.balance_read += 1
        snapshot = capacity._inventory(q.journal, SCOPE)
        at = max(NOW, snapshot[1]) if snapshot else NOW
        return q.admit(status(n,at=at), balance(1000000,n=self.balance_read,at=at), 150, now=at)

    def api(self, config=None):
        f, p, c = create(self.path)
        self.addCleanup(p.close); self.addCleanup(f.close)
        config = config or Config()
        return f, p, c, Acquirer(f, config), Bidder(f, config)

    def test_c0_c3_40_occupied_plus_ten_mixed_reservations_blocks_51st(self):
        j = self.journal(); observe(j, inventory(40))
        q = self.queue(j)
        for n in range(1, 11):
            self.assertEqual(self.enroll(q, n), 'ENROLLED')
        for n in range(1, 6):
            terminal(q, status(n), n=800+n)
        self.assertEqual(counters(j), (40, 5, 5, 50))
        self.assertEqual(len(q.entries), 5)
        self.assertEqual(self.enroll(q, 11), 'PIPELINE_FULL')
        self.assertEqual(counters(j), (40, 5, 5, 50))
        # Every accepted enrollment has a durable slot and event, every rejection
        # has neither. A fresh process-local queue cannot circumvent the limit.
        self.assertEqual(len([e for e in j.trace() if e['reason']=='ENROLLED']), 10)
        self.assertEqual(self.enroll(self.queue(j), 12), 'PIPELINE_FULL')

    def test_c0_separate_unresolved_limit_and_configured_pipeline_limit(self):
        j = self.journal(); observe(j)
        q = self.queue(j, capacity=2)
        self.assertEqual(self.enroll(q, 1), 'ENROLLED')
        self.assertEqual(self.enroll(q, 2), 'ENROLLED')
        self.assertEqual(self.enroll(q, 3), 'QUEUE_FULL')
        terminal(q, status(1))
        self.assertEqual(self.enroll(q, 3), 'ENROLLED')
        self.assertEqual(counters(j), (0, 1, 2, 3))
        self.assertEqual(self.enroll(self.queue(j, capacity=50, pipeline_capacity=3), 4), 'PIPELINE_FULL')
        for value in (51, 0, True, 1.5):
            with self.assertRaises(ValueError): Config(max_total_pipeline_slots=value)
            with self.assertRaises(ValueError): self.queue(j, pipeline_capacity=value)

    def test_c0_c3_concurrent_admission_uses_durable_counts_not_stale_instances(self):
        j = self.journal(); observe(j, inventory(49))
        barrier = threading.Barrier(12)
        def race(n):
            local = Journal(self.db, now=lambda: NOW)
            try:
                stale_queue = self.queue(local)
                barrier.wait(timeout=15)
                return self.enroll(stale_queue, n)
            finally: local.close()
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(race, range(1, 13)))
        self.assertEqual(results.count('ENROLLED'), 1, results)
        self.assertEqual(results.count('PIPELINE_FULL'), 11, results)
        self.assertEqual(counters(j), (49, 0, 1, 50))
        self.assertEqual(len([e for e in j.trace() if e['reason']=='ENROLLED']), 1)

    def test_c0_c3_concurrent_duplicate_identity_reserves_exactly_once(self):
        j = self.journal(); observe(j)
        barrier = threading.Barrier(6)
        def race(_):
            local = Journal(self.db, now=lambda: NOW)
            try:
                q = self.queue(local); barrier.wait(timeout=15)
                return self.enroll(q, 1)
            finally: local.close()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(race, range(6)))
        self.assertEqual(results.count('ENROLLED'), 1)
        self.assertEqual(results.count('PENDING'), 5)
        self.assertEqual(counters(j), (0, 0, 1, 1))

    def test_c0_c3_50_unresolved_saturation_is_independent_of_resale(self):
        j = self.journal(); observe(j)
        q = self.queue(j)
        for n in range(1, 51): self.assertEqual(self.enroll(q, n), 'ENROLLED')
        self.assertEqual(self.enroll(q, 51), 'QUEUE_FULL')
        terminal(q, status(1))
        self.assertEqual(len(q.entries), 49)
        self.assertEqual(self.enroll(q, 51), 'PIPELINE_FULL')
        terminal(q, status(2), State.LOST)
        self.assertEqual(self.enroll(q, 51), 'ENROLLED')
        self.assertEqual(counters(j), (0, 1, 49, 50))

    def test_c1_c2_unknown_missing_stale_conflict_and_coin_release_retain_slots(self):
        j = self.journal(); observe(j)
        q = self.queue(j); self.assertEqual(self.enroll(q, 1), 'ENROLLED')
        snapshots = [Snapshot((), fresh(800), Coverage(True, False, evidence_id=cid(899))),
            Snapshot((replace(status(), state=State.UNKNOWN),), fresh(801), Coverage(False, None)),
            Snapshot((replace(status(), state=State.LOST, freshness=fresh(802, NOW-timedelta(seconds=31))),), fresh(802), Coverage(False, None)),
            Snapshot((replace(status(2), state=State.LOST),), fresh(803), Coverage(False, None)),
            Snapshot((replace(status(), state=State.LOST),), fresh(804), Coverage(False, None)),
            Snapshot((replace(status(),state=State.LOST,freshness=fresh(806,NOW-timedelta(seconds=1))),),fresh(806),Coverage(False,None)),
            Snapshot((replace(status(), state=State.LOST), status()), fresh(804), Coverage(False, None))]
        for snapshot in snapshots:
            self.assertEqual(q.refresh(snapshot, now=NOW)[status().identity.trade_id], State.UNKNOWN)
            self.assertEqual(counters(j), (0, 0, 1, 1))
        leading = replace(status(), state=State.LEADING, current_bid=150, freshness=fresh(805))
        q.refresh(Snapshot((leading,), fresh(805), Coverage(False, None)), now=NOW)
        self.assertEqual(q.reservations, {}, 'coin escrow can be independently released')
        self.assertEqual(counters(j), (0, 0, 1, 1), 'slot must remain')
        terminal(q, status(), State.LOST, n=806)
        self.assertEqual(counters(j), (0, 0, 0, 0))

    def test_c1_c2_c3_win_pending_presence_and_duplicate_readbacks_never_double_count(self):
        j = self.journal(); observe(j, inventory(40))
        q = self.queue(j); self.assertEqual(self.enroll(q, 1), 'ENROLLED')
        terminal(q, status())
        self.assertEqual(counters(j), (40, 1, 0, 41))
        self.assertEqual(len(q.entries), 0)
        # Complete absence and a write ACK are insufficient to release pending.
        observe(j, inventory(40), n=701, at=NOW+timedelta(seconds=1))
        self.assertEqual(counters(j), (40, 1, 0, 41))
        present = inventory(40)+[auction(123, n=1)]
        observe(j, present, n=702, at=NOW+timedelta(seconds=2))
        self.assertEqual(counters(j), (41, 0, 0, 41))
        self.assertFalse(observe(j, present, n=702, at=NOW+timedelta(seconds=2)))
        terminal(q, status()); terminal(q, status(), State.LOST)
        self.assertEqual(counters(j), (41, 0, 0, 41))
        # Replay the terminal event itself, not only a now-empty queue refresh.
        j.record(SCOPE, 'WON_VERIFIED', {'state':'WON'}, trade_id=status().identity.trade_id)
        j.record(SCOPE, 'LOST_VERIFIED', {'state':'LOST'}, trade_id=status().identity.trade_id)
        self.assertEqual(counters(j), (41, 0, 0, 41))
        observe(j, inventory(40), n=703, at=NOW+timedelta(seconds=3))
        self.assertEqual(counters(j), (40, 0, 0, 40))
        j.record(SCOPE, 'WON_VERIFIED', {'state':'WON'}, trade_id=status().identity.trade_id)
        self.assertEqual(counters(j), (40, 0, 0, 40), 'late duplicate cannot resurrect a cleared slot')

    def test_c1_c2_inventory_before_terminal_uses_one_slot_and_exact_item_version(self):
        j = self.journal(); observe(j)
        q = self.queue(j); self.enroll(q, 1)
        observe(j, [auction(123, n=1)], n=701, at=NOW+timedelta(seconds=1))
        self.assertEqual(counters(j), (0, 0, 1, 1))
        self.assertEqual(capacity.status(j,SCOPE,now=NOW+timedelta(seconds=1))['physical_occupied'], 1)
        terminal(q, status())
        self.assertEqual(counters(j), (1, 0, 0, 1))
        self.assertEqual(self.queue(j).pending_resale, {})
        self.assertEqual(self.enroll(q, 2), 'ENROLLED')
        terminal(q, status(2), at=NOW+timedelta(seconds=1))
        observe(j, [auction(123,n=1), auction(999,n=2)], n=702, at=NOW+timedelta(seconds=2))
        self.assertEqual(counters(j), (2, 1, 0, 3), 'wrong definition cannot discharge the pending slot')
        observe(j, [auction(123,n=1), auction(123,n=2)], n=703, at=NOW+timedelta(seconds=3))
        self.assertEqual(counters(j), (2, 0, 0, 2))

    def test_c0_c2_old_duplicate_conflicting_inventory_cannot_free_current_presence(self):
        j = self.journal(); observe(j)
        q = self.queue(j); self.enroll(q, 1); terminal(q, status())
        observe(j, [auction(123,n=1)], n=701, at=NOW+timedelta(seconds=1))
        self.assertFalse(observe(j, [], n=700))
        with self.assertRaisesRegex(ValueError, 'stale'):
            capacity.observe(j,SCOPE,[],read_id=cid(702),network_at=NOW,now=NOW+timedelta(seconds=2))
        with self.assertRaisesRegex(ValueError, 'conflict'):
            observe(j, [], n=703, at=NOW+timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, 'conflict'):
            observe(j, [auction(123,n=1)]*2, n=704, at=NOW+timedelta(seconds=2))
        self.assertEqual(counters(j), (1, 0, 0, 1))

    def test_c0_no_inventory_unknown_inventory_and_restart_stale_fail_closed(self):
        j = self.journal(); q = self.queue(j)
        self.assertEqual(self.enroll(q, 1), 'CAPACITY_UNKNOWN')
        observe(j)
        later = NOW+timedelta(seconds=31)
        self.assertEqual(q.admit(status(1,at=later), balance(at=later),150,now=later), 'CAPACITY_UNKNOWN')
        self.assertFalse(capacity.status(j,SCOPE,now=later)['fresh'])
        self.assertEqual(counters(j), (0,0,0,0))

    def test_c1_c2_c3_pending_intents_unknown_dispatch_and_restart_retain_capacity(self):
        j = self.journal(); observe(j, inventory(49)); q = self.queue(j)
        epoch = j.session(SCOPE, OWNER)
        self.enroll(q, 1); i = intent(epoch=epoch)
        j.intend(i)
        during = []
        def uncertain_send():
            other = sqlite3.connect(self.db)
            try:
                during.extend(other.execute('SELECT phase FROM capacity_slots_v1 WHERE scope=?',(SCOPE,)).fetchall())
            finally: other.close()
            raise TimeoutError('synthetic uncertain dispatch')
        self.assertEqual(j.dispatch(i, uncertain_send).outcome, Outcome.UNKNOWN)
        self.assertEqual(during, [('UNRESOLVED',)])
        restarted = self.journal()
        self.assertEqual(self.enroll(self.queue(restarted), 2), 'PIPELINE_FULL')
        self.assertEqual(counters(restarted), (49, 0, 1, 50))
        with self.assertRaisesRegex(ValueError,'authority'):
            restarted.dispatch(i, lambda: self.fail('replayed uncertain bid'))
        # Reconciliation updates command, terminal evidence and capacity together.
        won = replace(status(),state=State.WON,current_bid=150,owned_item_id=status().identity.item_id,
            paid=150,freshness=fresh(800))
        restarted.reconcile(i.command_id,scope=SCOPE,owner=OWNER,epoch=epoch,status=won,balance=balance(n=901))
        self.assertEqual(counters(restarted), (49, 1, 0, 50))
        self.assertEqual(self.enroll(self.queue(restarted), 2), 'PIPELINE_FULL')

    def test_c1_c2_c3_terminal_and_presence_persistence_failures_rollback_all_changes(self):
        j = self.journal(); observe(j); q = self.queue(j)
        epoch = j.session(SCOPE, OWNER); self.enroll(q,1); i = intent(epoch=epoch); j.intend(i)
        original = capacity.apply_event
        def fail_terminal(journal,scope,reason,*args,**kw):
            original(journal,scope,reason,*args,**kw)
            if reason=='WON_VERIFIED': raise OSError('checkpoint failed')
        won = replace(status(),state=State.WON,current_bid=150,owned_item_id=status().identity.item_id,
            paid=150,freshness=fresh(800))
        with patch.object(capacity,'apply_event',side_effect=fail_terminal):
            with self.assertRaises(OSError):
                j.reconcile(i.command_id,scope=SCOPE,owner=OWNER,epoch=epoch,status=won,balance=balance(n=901))
        self.assertEqual(j.db.execute('SELECT state FROM commands').fetchone(), ('UNKNOWN',))
        self.assertEqual(counters(j), (0,0,1,1))
        self.assertFalse([e for e in j.trace() if e['reason']=='WON_VERIFIED'])
        j.reconcile(i.command_id,scope=SCOPE,owner=OWNER,epoch=epoch,status=won,balance=balance(n=901))
        def fail_presence(scope,reason,*args,**kw):
            if reason=='CAPACITY_OBSERVED': raise OSError('inventory checkpoint failed')
        with patch.object(j,'_event',side_effect=fail_presence):
            with self.assertRaises(OSError):observe(j,[auction(123,n=1)],n=701,at=NOW+timedelta(seconds=1))
        self.assertEqual(counters(j), (0,1,0,1))
        observe(j,[auction(123,n=1)],n=701,at=NOW+timedelta(seconds=1))
        self.assertEqual(counters(j), (1,0,0,1))

    def test_c0_c3_enrollment_failure_rolls_back_slot_and_event(self):
        j = self.journal(); observe(j)
        original = capacity.apply_event
        def interrupted(journal,scope,reason,*args,**kw):
            original(journal,scope,reason,*args,**kw)
            if reason=='ENROLLED': raise OSError('failed after slot insertion')
        q = self.queue(j)
        with patch.object(capacity,'apply_event',side_effect=interrupted):
            with self.assertRaises(OSError):self.enroll(q,1)
        self.assertEqual(counters(j), (0,0,0,0))
        self.assertFalse(q.entries)
        self.assertFalse([e for e in j.trace() if e['reason']=='ENROLLED'])
        self.assertEqual(self.enroll(q,1), 'ENROLLED')

    def test_c2_readers_never_mix_inventory_and_reservations_across_a_commit(self):
        j=self.journal(); observe(j); q=self.queue(j); self.enroll(q,1); terminal(q,status())
        reader=self.journal(readonly=True)
        original=capacity._inventory
        committed=[]
        def interleave(journal,scope):
            result=original(journal,scope)
            if journal is reader and not committed:
                committed.append(True)
                # Commit on another connection *between* the reader's inventory
                # SELECT and slot SELECT. WAL allows this while its read is open.
                observe(j,[auction(123,n=1)],n=701,at=NOW+timedelta(seconds=1))
            return result
        with patch.object(capacity,'_inventory',side_effect=interleave):
            self.assertEqual(counters(reader),(0,1,0,1))
        self.assertEqual(committed,[True])
        self.assertEqual(counters(reader),(1,0,0,1))

    def test_c0_c3_real_process_death_at_enrollment_intent_dispatch_win_and_presence(self):
        stages = {'before_enrollment_commit':(0,0,0,0), 'after_enrollment_commit':(0,0,1,1),
            'after_intent_commit':(0,0,1,1), 'after_dispatch_claim':(0,0,1,1),
            'after_send':(0,0,1,1), 'before_win_commit':(0,0,1,1),
            'after_win_commit':(0,1,0,1), 'before_presence_commit':(0,1,0,1),
            'after_presence_commit':(1,0,0,1)}
        for stage, expected in stages.items():
            with self.subTest(stage=stage):
                directory = self.path/stage; directory.mkdir()
                run = subprocess.run([sys.executable,str(Path(__file__).resolve()),'--crash',str(directory),stage],
                    cwd=ROOT,capture_output=True,text=True,timeout=15)
                self.assertEqual(run.returncode,23,run.stdout+run.stderr)
                j = Journal(directory/'journal.sqlite3',now=lambda:NOW)
                try:
                    self.assertEqual(counters(j), expected)
                    self.assertEqual(j.db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                    pending = j.db.execute("SELECT count(*) FROM commands WHERE state NOT IN ('RECONCILED','NOT_DISPATCHED')").fetchone()[0]
                    self.assertEqual(pending, int(stage in {'after_intent_commit','after_dispatch_claim','after_send','before_win_commit'}))
                    if stage != 'before_enrollment_commit':
                        at=NOW+timedelta(seconds=2)
                        self.assertEqual(self.queue(j).admit(status(2,at=at),balance(1000000,n=902,at=at),150,now=at), 'ENROLLED')
                        self.assertEqual(counters(j)[3], expected[3]+1)
                    self.assertEqual((directory/'sent').exists(), stage=='after_send')
                finally:j.close()

    def test_c0_c1_c2_real_actor_win_and_one_shot_admission_share_the_ledger(self):
        f,p,c,a,b = self.api()
        p.transfer_items = inventory(49)
        a.cycle(); self.assertEqual(p.bid_calls,1)
        p.candidate.update(trade_state='closed',expires=0,native_is_won=True)
        p.watched=[deepcopy(p.candidate)]
        b.cycle()
        self.assertEqual(counters(f.journal,f.registry.scope,c.now()), (49,0,1,50))
        p.owned=[deepcopy(p.candidate['item'])]
        p.owned[0]['last_sale_price']=800
        # Capacity verification stops before the new 002-08 mutation lifecycle.
        from unittest.mock import patch
        from fc_access.production_v1.resale import Resale
        with patch.object(Resale, 'cycle'):
            b.cycle()
        self.assertEqual(counters(f.journal,f.registry.scope,c.now()), (49,1,0,50))
        self.assertFalse(f.queue.entries)
        p.candidate = auction(123,15000,2); p.candidate['starting_bid']=800
        # Foundation.admit is the second public enrollment seam, independent of
        # Acquirer and its lock. It must not bypass pending-resale capacity.
        response=f.read('search',Search.discovery().params()); funds=f.read('balance')
        decision=f.admit(response,p.candidate['trade_id'],funds)
        self.assertEqual((decision['action'],decision['reason']), ('HOLD','PIPELINE_FULL'))
        self.assertEqual(p.bid_calls,1)
        a.cycle()
        self.assertEqual(p.bid_calls,1)
        self.assertEqual([e for e in f.registry.events() if e['kind']=='DECISION'][-1]['reason'], 'PIPELINE_FULL')
        # An exact fresh physical read converts pending -> occupied. No write ACK
        # or list command is needed or trusted as evidence by the capacity code.
        p.transfer_items += [auction(123,n=1)]
        read_occupancy(f)
        self.assertEqual(counters(f.journal,f.registry.scope,c.now()), (50,0,0,50))
        p.transfer_items = inventory(48)
        a.cycle()
        self.assertEqual(p.bid_calls,2)

    def test_c0_c2_scope_and_physical_identity_cannot_reuse_a_reserved_item(self):
        j = self.journal(); observe(j); q = self.queue(j); self.enroll(q,1)
        same_item = replace(status(2),identity=replace(status(2).identity,item_id=status().identity.item_id))
        self.assertEqual(q.admit(same_item,balance(),150,now=NOW),'CAPACITY_IDENTITY_CONFLICT')
        other = 'f'*32; observe(j,inventory(50),n=701,scope=other)
        self.assertEqual(counters(j),(0,0,1,1))
        self.assertEqual(counters(j,other),(50,0,0,50))

    def test_c1_c3_legacy_journal_migration_preserves_unknown_intents_and_wins(self):
        # Build the legacy schema as data, without running or hashing old source.
        db = sqlite3.connect(self.db)
        db.executescript('''
          CREATE TABLE metadata(version INTEGER NOT NULL);
          INSERT INTO metadata VALUES(1);
          CREATE TABLE sessions(scope TEXT PRIMARY KEY,owner TEXT,epoch INTEGER);
          CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,version INTEGER,
            at TEXT,scope TEXT,trade_id TEXT,command_id TEXT,reason TEXT,data TEXT);
          CREATE TABLE commands(id TEXT PRIMARY KEY,scope TEXT,owner TEXT,epoch INTEGER,
            trade_id TEXT,item_id TEXT,definition_id INTEGER,amount INTEGER,state TEXT,
            deadline TEXT,status_read_id TEXT,balance_read_id TEXT,intended_at TEXT);
        ''')
        events=[]
        for n in (1,2):
            events.append((f'trade:{n:024x}','ENROLLED',dict(amount=150,balance_read_id=cid(900),
                status_read_id=cid(n),item_id=f'item:{n:024x}',definition_id=123)))
        events.extend([(status().identity.trade_id,'WON_VERIFIED',dict(state='WON',paid=150)),
            (status(2).identity.trade_id,'RESERVATION_RELEASED',{}),
            (status(3).identity.trade_id,'INTENT_DURABLE',dict(amount=150,cap=1000,
                item_id=status(3).identity.item_id,definition_id=123))])
        for trade,reason,data in events:
            db.execute('INSERT INTO events(version,at,scope,trade_id,reason,data) VALUES(1,?,?,?,?,?)',
                (NOW.isoformat(),SCOPE,trade,reason,json.dumps(data)))
        db.commit(); db.close()
        old=Journal(self.db,readonly=True)
        try:
            self.assertFalse(capacity.installed(old))
            self.assertEqual(counters(old),(None,1,2,None))
            self.assertFalse(capacity.status(old,SCOPE,now=NOW)['fresh'])
        finally:old.close()
        j=self.journal()
        self.assertEqual(counters(j),(None,1,2,None))
        self.assertEqual(len(j.trace()),len(events),'migration preserves historical event chronology')
        q=self.queue(j)
        self.assertEqual(set(q.entries),{status(2).identity.trade_id,status(3).identity.trade_id})
        self.assertEqual(self.enroll(q,4),'CAPACITY_UNKNOWN')
        observe(j,inventory(40))
        self.assertEqual(counters(j),(40,1,2,43))
        reopened=self.journal()
        self.assertEqual(counters(reopened),(40,1,2,43))
        self.assertEqual(self.enroll(self.queue(reopened),4),'ENROLLED')


def crash(directory, stage):
    j = Journal(directory/'journal.sqlite3',now=lambda:NOW)
    observe(j)
    q = AuctionQueue(journal=j,scope=SCOPE,reserve=0)
    original = capacity.apply_event
    if stage in {'before_enrollment_commit','before_win_commit'}:
        def die(journal,scope,reason,*args,**kw):
            original(journal,scope,reason,*args,**kw)
            if reason == ('ENROLLED' if stage=='before_enrollment_commit' else 'WON_VERIFIED'):
                os._exit(23)
        capacity.apply_event = die
    q.admit(status(),balance(),150,now=NOW)
    if stage=='after_enrollment_commit':os._exit(23)
    epoch=j.session(SCOPE,OWNER); i=intent(epoch=epoch); j.intend(i)
    if stage=='after_intent_commit':os._exit(23)
    if stage in {'after_dispatch_claim','after_send'}:
        def send():
            if stage=='after_send':
                with open(directory/'sent','w') as output:
                    output.write('synthetic bid');output.flush();os.fsync(output.fileno())
            os._exit(23)
        j.dispatch(i,send)
    won=replace(status(),state=State.WON,current_bid=150,owned_item_id=status().identity.item_id,
        paid=150,freshness=fresh(800))
    j.reconcile(i.command_id,scope=SCOPE,owner=OWNER,epoch=epoch,status=won,balance=balance(n=901))
    if stage=='after_win_commit':os._exit(23)
    if stage=='before_presence_commit':
        j._event=lambda *args,**kw:os._exit(23)
    observe(j,[auction(123,n=1)],n=701,at=NOW+timedelta(seconds=1))
    os._exit(23)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--crash':crash(Path(sys.argv[2]),sys.argv[3])
    else:unittest.main(verbosity=2)
