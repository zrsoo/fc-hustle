"""Operator resolutions remain distinct from independently observed EA outcomes."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.bidding_v1.contracts import Identity
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.bidding_v1.journal import Journal
from fc_access.production_v1.foundation import Registry
from fc_access.continuous_v1.operator_loss import confirm
from foundation_fixture import CONTEXT


class OperatorLoss(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.path=Path(tmp.name)/'journal.db'
        self.now=datetime.now(timezone.utc);self.j=Journal(self.path,now=lambda:self.now);self.addCleanup(self.j.close)
        self.r=Registry(self.j,CONTEXT,'a'*32);self.scope=self.r.scope
        self.identity=Identity('trade:'+'b'*24,'item:'+'c'*24,271421);self.cid='d'*32
        self.args=dict(context=CONTEXT,command_id=self.cid,identity=self.identity,amount=950,
                       attestation='User confirmed this exact auction was lost.',authorization='Resolve this loss and resume.')
        self.j.record(self.scope,'ENROLLED',dict(amount=950,item_id=self.identity.item_id,
            definition_id=271421,status_read_id='e'*32,balance_read_id='f'*32),trade_id=self.identity.trade_id)
        self.j.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (self.cid,self.scope,self.r.owner,self.r.epoch,self.identity.trade_id,self.identity.item_id,271421,
             950,'ACKNOWLEDGED',(self.now-timedelta(minutes=1)).isoformat(),'e'*32,'f'*32,
             (self.now-timedelta(minutes=2)).isoformat()))
        self.j.record(self.scope,'PENDING',trade_id=self.identity.trade_id,command_id=self.cid)

    def call(self,**kwargs): return confirm(self.j,**dict(self.args,**kwargs))
    def queue(self): return AuctionQueue(journal=self.j,scope=self.scope)

    def test_local_release_is_audited_idempotent_restart_readable_and_not_native_proof(self):
        before=self.j.trace();result=self.call();proof=result['proof']
        self.assertFalse(proof['native_outcome_verified']);self.assertFalse(proof['refund_claimed'])
        self.assertEqual(proof['source'],'operator');self.assertEqual(self.j.trace()[:len(before)],before)
        self.assertNotIn(self.identity.trade_id,self.queue().entries);self.assertFalse(self.queue().reservations)
        self.assertFalse(self.queue().pending_resale);self.assertIn('f'*32,self.queue().invalid_balances)
        self.assertEqual(self.j.db.execute('SELECT phase FROM capacity_slots_v1').fetchone(),('OPERATOR_LOST',))
        self.assertEqual(self.j.db.execute('SELECT state FROM commands').fetchone(),('RECONCILED',))
        self.assertNotIn('LOST_VERIFIED',[e['reason'] for e in self.j.trace()])
        with self.assertRaisesRegex(ValueError,'stale_owner'): self.r.check()
        registry=Registry(self.j,CONTEXT,proof['owner'],join_epoch=proof['epoch'])
        view=registry.current();self.assertFalse(view['unresolved']);self.assertFalse(view['queued'])
        self.assertFalse(view['auctions'][self.identity.trade_id]['native_outcome_verified'])
        self.assertEqual(view['auctions'][self.identity.trade_id]['source'],'operator')
        events=self.j.trace();self.assertEqual(self.call()['outcome'],'ALREADY_RESOLVED');self.assertEqual(events,self.j.trace())
        with closing(Journal(self.path,readonly=True).db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operator_losses_v1').fetchone(),(1,))
        for sql in ('UPDATE operator_losses_v1 SET proof=proof','DELETE FROM operator_losses_v1'):
            with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):self.j.db.execute(sql)

    def test_exact_identity_amount_context_and_explicit_authorization_required(self):
        cases=[dict(amount=900),dict(identity=Identity(self.identity.trade_id,'item:'+'a'*24,271421)),
               dict(command_id='0'*32),dict(attestation=''),dict(authorization=''),
               dict(context=dict(CONTEXT,account='0'*32))]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ValueError):self.call(**change)
        self.assertIn(self.identity.trade_id,self.queue().entries);self.r.check()

    def test_expiry_alone_never_resolves_and_live_auction_is_rejected(self):
        self.assertIn(self.identity.trade_id,self.queue().entries)
        self.j.db.execute('UPDATE commands SET deadline=?',((self.now+timedelta(hours=1)).isoformat(),))
        with self.assertRaisesRegex(ValueError,'not_expired'):self.call()

    def test_confirmed_won_or_owned_inventory_cannot_be_disposed_as_lost(self):
        self.j.record(self.scope,'WON_VERIFIED',trade_id=self.identity.trade_id)
        with self.assertRaisesRegex(ValueError,'conflicting_native_terminal'):self.call()

    def test_inventory_presence_vetoes_resolution(self):
        self.j.db.execute('INSERT INTO capacity_inventory_v1 VALUES(?,?,?,?)',
            (self.scope,'1'*32,self.now.isoformat(),json.dumps([[self.identity.item_id,271421]])))
        with self.assertRaisesRegex(ValueError,'owned_inventory_conflict'):self.call()

    def test_not_dispatched_or_already_terminal_is_rejected(self):
        for state in ('NOT_DISPATCHED','RECONCILED'):
            self.j.db.execute('UPDATE commands SET state=?',(state,))
            with self.assertRaisesRegex(ValueError,'already_terminal'):self.call()

    def test_atomic_rollback_preserves_command_slot_owner_and_reservation(self):
        original=Journal._event
        def fail(j,scope,reason,*args):
            if reason=='OPERATOR_LOST_CONFIRMED':raise RuntimeError('fixture crash')
            return original(j,scope,reason,*args)
        with patch.object(Journal,'_event',fail),self.assertRaisesRegex(RuntimeError,'fixture crash'):self.call()
        self.r.check();self.assertIn(self.identity.trade_id,self.queue().entries)
        self.assertEqual(self.j.db.execute('SELECT state FROM commands').fetchone(),('ACKNOWLEDGED',))

    def test_scope_isolation_draining_and_capacity_migration(self):
        self.j.record(self.scope,'DRAINING');self.j.record('1'*32,'ENROLLED',dict(amount=800,item_id='item:'+'2'*24,
            definition_id=1,status_read_id='3'*32,balance_read_id='4'*32),trade_id='trade:'+'5'*24)
        self.call();self.assertTrue(self.queue().draining)
        self.assertEqual(AuctionQueue(journal=self.j,scope='1'*32).reservations['trade:'+'5'*24][0],800)
        from fc_access.bidding_v1.capacity import install
        self.j.db.execute('DELETE FROM capacity_migration_v1');install(self.j)
        self.assertNotIn(self.identity.trade_id,self.queue().entries)

    def test_real_foundation_startup_with_missing_watched_trade_after_operator_resolution(self):
        from actors_fixture import create
        from fc_access.actors_v1.actors import Acquirer
        from fc_access.continuous_v1.recovery import reconcile
        from fc_access.production_v1.foundation import Foundation
        with tempfile.TemporaryDirectory() as directory:
            f,page,clock=create(directory)
            try:
                Acquirer(f,clock=clock.monotonic,sleep=clock.sleep).cycle()
                cid,trade,item,definition,amount=f.journal.db.execute('SELECT id,trade_id,item_id,definition_id,amount FROM commands').fetchone()
                clock.sleep(7200);page.watched=[]
                confirm(f.journal,context=CONTEXT,command_id=cid,identity=Identity(trade,item,definition),amount=amount,
                        attestation='Offline fixture operator confirms loss',authorization='Offline fixture')
                f.close()
                f=Foundation(page,context=CONTEXT,journal_path=Path(directory)/'journal.sqlite3',fixture=True,
                    now=clock.now,clock=clock.monotonic,sleep=clock.sleep)
                self.assertEqual(reconcile(f)['commitments'],0)
            finally:f.close();page.close()


if __name__=='__main__':unittest.main()
