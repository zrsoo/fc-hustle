"""Business receipts are mandatory at active boundaries, archives stay readable."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from foundation_fixture import create, admitted, historical_gate_inventory
from fc_access.production_v1.contracts import parse_response, stamp
from fc_access.bidding_v1.contracts import AuctionStatus, Balance, Freshness, State
from fc_access.bidding_v1.core import AuctionQueue


class ReceiptContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples=json.loads(subprocess.check_output(['node','tests/production_bid_receipt_checks.cjs','--samples'],cwd=ROOT,encoding='utf-8'))

    def parse(self,s,**kw):
        return parse_response(s['r'],s['c'],now=stamp(s['r']['freshness']['observed_at']),require_bid_receipt=True,**kw)

    def test_actual_page_accepted_and_rejected_outputs_parse(self):
        for s in self.samples:self.parse(s)

    def test_old_ack_is_archival_only_and_empty_success_is_not_accepted(self):
        s=deepcopy(self.samples[0]);del s['r']['result']['bid_receipt']
        parse_response(s['r'],s['c'],now=stamp(s['r']['freshness']['observed_at']))
        with self.assertRaisesRegex(ValueError,'receipt_required'):self.parse(s)
        s=deepcopy(self.samples[0]);s['r']['result']['bid_receipt']['native_item_count']=0
        with self.assertRaisesRegex(ValueError,'unproven_bid_acceptance'):self.parse(s)

    def test_corrupted_or_contradictory_receipts_are_rejected(self):
        changes=[('wire_amount',1),('wire_trade_id','trade:'+'0'*24),('input_stale',True),
                 ('native_error_code',123),('native_success',False),('matching_item_count',0),
                 ('wire_item_count',0),('schema',True),('unexpected','credential-canary')]
        for key,value in changes:
            s=deepcopy(self.samples[0]);s['r']['result']['bid_receipt'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.parse(s)
        s=deepcopy(self.samples[0]);r=s['r']['result']['bid_receipt'];r['auction']['bid_state']='outbid';r['before_bid_state']='outbid'
        with self.assertRaisesRegex(ValueError,'unproven_bid_acceptance'):self.parse(s)

    def test_unknown_error_and_success_with_rejection_cannot_be_retired(self):
        for key,value in [('native_error_name',None),('wire_error_code',456),('native_item_count',1)]:
            s=deepcopy(self.samples[1]);s['r']['result']['bid_receipt'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.parse(s)


class JournalReceipts(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.f,self.page,self.clock=create(t.name)
        self.addCleanup(self.page.close);self.addCleanup(self.f.close)

    def bid(self,rejected=False,rebid=False):
        if rejected:
            def reject(c,v):
                if c['operation']=='bid':
                    r=v['result'];r.update(success=False,error='bid_rejected',status=409)
                    r['network'][0]['status']=409;v['freshness']['network_at']=None
                    r['bid_receipt'].update(verdict='REJECTED',reason='EXPLICIT_NATIVE_REJECTION',
                        wire_item_count=0,wire_error_code=123,native_success=False,native_error_code=123,
                        native_error_name='STATE_INVALID',native_item_count=0,matching_item_count=0,auction=None)
                return v
            self.page.project_response=reject
        if rebid:
            from fc_access.production_v1.foundation import status_from, freshness
            from fc_access.production_v1.prices import CardKey
            trade=self.page.candidate['trade_id'];quote=self.f.admissions[trade][3]
            prices=self.f.prices.load(key=CardKey(self.page.candidate['item']['definition_id']))
            watched=self.f.read('watched');funds=self.f.read('balance')
            status=status_from(watched['result']['auctions'][0],watched)
            balance=Balance(funds['result']['credits'],None,freshness(funds))
            self.f.admissions[trade]=(status,balance,prices,quote,2700)
        else:
            with historical_gate_inventory(self.f,self.page,self.clock):
                d,_,_=admitted(self.f,self.page)
        return self.f.bid(self.page.candidate['trade_id'])

    def reconcile(self,cid,state):
        f=self.f;trade=self.page.candidate['trade_id'];identity=f.queue.identities[trade]
        at=self.clock.now();self.clock.sleep(.01)
        fresh=Freshness(self.clock.now(),self.clock.now(),1,'1'*32,'fixture')
        balance=Balance(self.page.credits,None,Freshness(self.clock.now(),self.clock.now(),1,'2'*32,'fixture'))
        status=AuctionStatus(identity,state,2500,0 if state==State.ACTIVE else 2500,15000,at+timedelta(seconds=100),fresh)
        f.journal.reconcile(cid,scope=f.registry.scope,owner=f.registry.owner,epoch=f.registry.epoch,status=status,balance=balance)

    def test_positive_receipt_is_durable_immutable_and_needs_readback(self):
        r=self.bid();cid=r['command_id'];j=self.f.journal
        self.assertEqual(r['outcome'],'ACKNOWLEDGED')
        self.assertEqual(j.db.execute('SELECT state FROM commands').fetchone(),('ACKNOWLEDGED',))
        self.assertEqual(json.loads(j.db.execute('SELECT receipt FROM bid_receipts_v1').fetchone()[0])['verdict'],'ACCEPTED')
        for sql in ('UPDATE bid_receipts_v1 SET receipt=receipt','DELETE FROM bid_receipts_v1'):
            with self.assertRaises(sqlite3.IntegrityError):j.db.execute(sql)
        self.reconcile(cid,State.LEADING)
        self.assertEqual(j.db.execute('SELECT state FROM commands').fetchone(),('RECONCILED',))
        self.assertEqual(self.page.bid_calls,1)

    def test_opening_rejection_waits_for_fresh_state_then_releases_without_lost(self):
        r=self.bid(True);j=self.f.journal
        self.assertEqual(r['outcome'],'REJECTED')
        self.assertEqual(j.db.execute('SELECT state FROM commands').fetchone(),('REJECTED',))
        self.assertTrue(AuctionQueue(journal=j,scope=self.f.registry.scope).entries)
        with self.assertRaisesRegex(ValueError,'rejection_account_state_conflict'):self.reconcile(r['command_id'],State.LEADING)
        self.reconcile(r['command_id'],State.ACTIVE)
        q=AuctionQueue(journal=j,scope=self.f.registry.scope)
        self.assertFalse(q.entries);self.assertFalse(q.reservations)
        reasons=[e['reason'] for e in j.trace()]
        self.assertIn('OPENING_REJECTED',reasons);self.assertNotIn('LOST_VERIFIED',reasons)
        self.assertEqual(self.page.bid_calls,1)

    def test_missing_or_empty_live_receipt_never_persists_ack(self):
        def omit(c,v):
            if c['operation']=='bid':del v['result']['bid_receipt']
            return v
        self.page.project_response=omit
        r=self.bid();self.assertEqual(r['outcome'],'UNKNOWN')
        self.assertEqual(self.f.journal.db.execute('SELECT state FROM commands').fetchone(),('UNKNOWN',))
        self.assertTrue(AuctionQueue(journal=self.f.journal,scope=self.f.registry.scope).entries)
        self.assertEqual(self.page.bid_calls,1)

    def test_old_injected_bridge_is_detected_before_intent_or_dispatch(self):
        def old(c,v):
            if c['operation']=='status_support':v['result'].pop('bid_receipt_schema',None)
            return v
        self.page.project_response=old
        with self.assertRaisesRegex(ValueError,'reviewed_bid_receipt_bridge_required'):self.bid()
        self.assertEqual(self.page.bid_calls,0)
        self.assertEqual(self.f.journal.db.execute('SELECT count(*) FROM commands').fetchone(),(0,))

    def test_rejected_rebid_preserves_previously_verified_participation(self):
        r=self.bid();self.reconcile(r['command_id'],State.OUTBID)
        self.page.candidate.update(current_bid=2600,bid_state='outbid')
        self.page.watched=[self.page.candidate]
        r=self.bid(True,rebid=True)
        self.assertEqual(r['outcome'],'REJECTED')
        self.reconcile(r['command_id'],State.OUTBID)
        q=AuctionQueue(journal=self.f.journal,scope=self.f.registry.scope)
        self.assertIn(self.page.candidate['trade_id'],q.entries)
        self.assertEqual(self.f.journal.db.execute('SELECT phase FROM capacity_slots_v1').fetchone(),('UNRESOLVED',))
        self.assertEqual(self.page.bid_calls,2)


class NonRegistration(unittest.TestCase):
    def test_operator_clarification_preserves_old_loss_and_never_claims_native_proof(self):
        # Reuse the historical-loss fixture to exercise precisely the amendment
        # case; its original assertion and all journal events must remain intact.
        from test_operator_loss import OperatorLoss
        from fc_access.continuous_v1.operator_nonregistration import confirm
        case=OperatorLoss();case.setUp()
        try:
            case.call();before=case.j.trace();old=case.j.db.execute('SELECT proof FROM operator_losses_v1').fetchone()
            args=dict(case.args,attestation='Operator clarifies this exact bid never registered.',authorization='Approved non-registration repair.')
            result=confirm(case.j,**args)
            self.assertEqual(case.j.trace()[:len(before)],before)
            self.assertEqual(case.j.db.execute('SELECT proof FROM operator_losses_v1').fetchone(),old)
            self.assertFalse(result['proof']['native_outcome_verified']);self.assertFalse(result['proof']['refund_claimed'])
            self.assertTrue(result['proof']['previous_operator_loss_retained'])
            self.assertEqual(result['proof']['outcome'],'NOT_REGISTERED')
            self.assertFalse(case.queue().entries);self.assertFalse(case.queue().reservations)
            self.assertEqual(confirm(case.j,**args)['outcome'],'ALREADY_RESOLVED')
            for sql in ('UPDATE operator_nonregistrations_v1 SET proof=proof','DELETE FROM operator_nonregistrations_v1'):
                with self.assertRaises(sqlite3.IntegrityError):case.j.db.execute(sql)
        finally:case.doCleanups()

    def test_operator_assertion_cannot_override_verified_participation(self):
        from test_operator_loss import OperatorLoss
        from fc_access.continuous_v1.operator_nonregistration import confirm
        case=OperatorLoss();case.setUp()
        try:
            case.j.record(case.scope,'BID_VERIFIED',trade_id=case.identity.trade_id)
            with self.assertRaisesRegex(ValueError,'conflicting_native_participation'):
                confirm(case.j,**case.args)
            self.assertTrue(case.queue().entries);case.r.check()
        finally:case.doCleanups()


if __name__=='__main__':unittest.main()
