"""Actual actor/recovery paths with a native double; no live observations."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from actors_fixture import create
from fc_access.actors_v1.actors import Acquirer,Bidder
from fc_access.continuous_v1.recovery import reconcile
from fc_access.production_v1.known_status import observe
from fc_access.production_v1.resale import verify_win
from fc_access.bidding_v1.contracts import State


class StatusFallback(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.f,self.page,self.clock=create(self.temp.name)
        self.addCleanup(self.page.close);self.addCleanup(self.f.close)
        Acquirer(self.f).cycle()
        self.trade=self.page.candidate['trade_id'];self.identity=self.f.queue.identities[self.trade]
        self.bid=self.f.registry.current()['unresolved'][0]['command_id']
        self.original=self.page.project_response
        self.lite=deepcopy(self.page.candidate)
        self.lite.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False,current_bid=900)
        self.lite['item']['definition_id']=0
        self.status_rows=[self.lite]
        self.delay=0
        def project(c,v):
            value=v if c['operation']=='status' else self.original(c,v)
            if c['operation']=='status':
                value['result']['auctions']=deepcopy(self.status_rows)
                value['result']['network'][0]['query']=dict(trade_id=c['params']['trade_id'])
                self.clock.sleep(self.delay)
            return value
        self.page.project_response=project
        self.page.watched=[]

    def state(self):return self.f.journal.db.execute('SELECT state FROM commands WHERE id=?',(self.bid,)).fetchone()[0]

    def test_bidder_recovers_missing_watched_loss_with_one_exact_get_and_no_replay(self):
        Bidder(self.f).cycle()
        self.assertEqual(self.state(),'RECONCILED');self.assertNotIn(self.trade,self.f.queue.entries)
        self.assertEqual(self.page.bid_calls,1)
        calls=[c for c in self.page.calls if c['operation']=='status']
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['params'],dict(trade_id=self.identity.trade_id,item_id=self.identity.item_id,
                                               definition_id=self.identity.definition_id))
        raw=self.f.adapter.responses[calls[0]['id']]
        self.assertEqual(raw['result']['auctions'][0]['item']['definition_id'],0)
        proof=[e for e in self.f.registry.events() if e.get('reason')=='EXACT_STATUS_RECOVERED'][-1]
        self.assertFalse(proof['native_version_observed']);self.assertEqual(proof['read_id'],calls[0]['id'])

    def test_startup_recovers_exact_missing_trade_without_reusing_intent(self):
        result=reconcile(self.f)
        self.assertEqual(result['commitments'],0);self.assertEqual(len(result['read_ids']),4)
        self.assertEqual(self.state(),'RECONCILED');self.assertEqual(self.page.bid_calls,1)
        self.assertFalse(self.f.registry.current()['unresolved'])

    def test_leading_readback_holds_and_active_outbid_never_uses_lite_as_write_authority(self):
        self.lite.update(trade_state='active',bid_state='highest',expires=120,current_bid=800)
        Bidder(self.f).cycle();self.assertEqual(self.state(),'RECONCILED');self.assertEqual(self.page.bid_calls,1)
        self.lite.update(bid_state='outbid',current_bid=900)
        Bidder(self.f).cycle();self.assertEqual(self.page.bid_calls,1)
        self.assertTrue(any(e.get('reason')=='FULL_WATCHED_READ_REQUIRED_FOR_REBID' for e in self.f.registry.events()))
        self.page.watched=[deepcopy(self.page.candidate)];self.page.watched[0].update(bid_state='outbid',current_bid=900)
        Bidder(self.f).cycle();self.assertEqual(self.page.bid_calls,2)

    def rejected_status(self):
        with self.assertRaises(ValueError):reconcile(self.f)
        self.assertEqual(self.page.bid_calls,1);self.assertEqual(self.state(),'ACKNOWLEDGED')
        self.assertIn(self.trade,self.f.queue.entries)

    def test_empty_fallback_preserves_unknown_not_expiry_inference(self):
        self.status_rows=[];self.rejected_status()

    def test_wrong_physical_item_cannot_settle_bid(self):
        self.lite['item']['item_id']='item:'+'e'*24;self.rejected_status()

    def test_explicit_different_version_is_not_replaced_by_retained_identity(self):
        self.lite['item']['definition_id']=999;self.rejected_status()

    def test_stale_fallback_is_not_current_proof(self):
        self.delay=31;self.rejected_status()

    def test_missing_read_is_not_lost_by_expiry_and_conflicting_full_row_is_not_fallback_authority(self):
        self.lite.update(bid_state='none',expires=-1,trade_state='expired')
        with self.assertRaisesRegex(ValueError,'outcome_still_unknown'):reconcile(self.f)
        self.assertEqual(self.state(),'ACKNOWLEDGED')
        self.page.watched=[deepcopy(self.page.candidate)]
        self.page.watched[0]['item']['item_id']='item:'+'e'*24
        watched=self.f.read('watched');before=len([c for c in self.page.calls if c['operation']=='status'])
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):observe(self.f,self.identity,watched)
        self.assertEqual(len([c for c in self.page.calls if c['operation']=='status']),before)

    def test_exact_pending_win_requires_independent_full_owned_item_and_paid_cost(self):
        self.lite.update(trade_state='closed',bid_state='highest',expires=-1,current_bid=800,native_is_won=True)
        watched=self.f.read('watched');status,source,_=observe(self.f,self.identity,watched)
        self.assertEqual(status.state,State.PENDING)
        self.page.owned=[deepcopy(self.page.candidate['item'])];self.page.owned[0]['last_sale_price']=800
        owned=self.f.read('unassigned');won=verify_win(self.f,status,source,owned)
        self.assertEqual(won.state,State.WON);self.assertEqual(won.paid,800)
        self.page.owned[0]['last_sale_price']=0;bad=self.f.read('unassigned')
        with self.assertRaisesRegex(ValueError,'unproven'):verify_win(self.f,status,source,bad)
        self.assertEqual(self.page.bid_calls,1)


if __name__=='__main__':unittest.main(verbosity=2)
