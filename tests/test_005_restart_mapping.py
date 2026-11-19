"""Restart with members whose auction left the watch list (2026-11-19 01:56Z).

The page can only map auctions present in the fresh watch list. Before the fix,
one such member made every status read fail (known_identity_unavailable) and the
runtime stopped on PERSISTENT_READ_FAILURE. Now the others are managed; the lost
one stays a member with an unknown outcome (never settled, listed or re-bid).
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.semantic import SemanticHealth, native_summary


class RestartMappingTests(unittest.TestCase):
    def restarted(self,lost):
        h=Harness(self.enterContext(tempfile.TemporaryDirectory()),3);self.addCleanup(h.close)
        h.controller.step();self.assertEqual(len(h.controller.journal.members()),3)
        gone=[h.ea.rows[i]['trade_id'] for i in lost]
        h.ea.unmapped=set(gone);h.ea.manual=[deepcopy(r) for r in h.ea.rows if r['trade_id'] not in gone]
        h.controller=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
        h.controller.mapping_refresh_needed=True;h.controller.resume()
        s=SemanticHealth(clock=h.clock.clock);h.executor.result=lambda c,v:s.observe(dict(kind='native_result',**native_summary(c,v)))
        return h,s,gone

    def test_lost_member_does_not_block_managing_the_others(self):
        h,s,gone=self.restarted([1]);before=len(h.calls('status_batch'))
        for _ in range(4):h.controller.step()
        self.assertIsNone(s.check(),'no persistent read failure');self.assertEqual(s.read_failures,0)
        statused=[t['trade_id'] for c in h.calls('status_batch')[before:] for t in c['command']['params']['targets']]
        self.assertNotIn(gone[0],statused);self.assertTrue(set(statused)>={h.ea.rows[0]['trade_id'],h.ea.rows[2]['trade_id']})
        state=dict(h.store.db.execute('SELECT trade_id,state FROM c4_members'))
        self.assertEqual(state[gone[0]],'ACTIVE','never settled or guessed')
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_metrics WHERE kind='MAPPING_LOST'").fetchone()[0],1)

    def test_all_members_lost_hands_off_and_trading_continues(self):
        h,s,gone=self.restarted([0,1,2]);before=len(h.calls('status_batch'))
        h.controller.step();self.assertEqual(h.controller.status()['phase'],'MAINTENANCE')
        h.ea.rows.append(__import__('native_price_fixture').auction(123,15000,4242))
        for _ in range(3):h.controller.step()
        self.assertIsNone(s.check());self.assertGreater(len(h.calls('bid')),3,'new acquisition proceeds')
        self.assertFalse(any(t['trade_id'] in gone for c in h.calls('status_batch')[before:] for t in c['command']['params']['targets']))
        # New members from a newer batch are managed alongside the old unresolved ones.
        batches={b for (b,) in h.store.db.execute("SELECT batch_id FROM c4_members WHERE state='ACTIVE'")}
        self.assertGreaterEqual(len(batches),2)
        # A rebid on the newer-batch member passes its own batch's authority.
        new=next(r for r in h.ea.rows if r['trade_id'] not in gone and r['trade_id'] in
                 {t for (t,) in h.store.db.execute("SELECT trade_id FROM c4_members WHERE state='ACTIVE'")})
        new.update(bid_state='outbid',current_bid=200);h.ea.manual=[r for r in h.ea.manual if r['trade_id']!=new['trade_id']]+[dict(new)]
        if h.controller.status()['phase']!='MANAGING':h.controller.step()
        h.controller.step()
        rebids=h.store.db.execute("SELECT state FROM c4_attempts WHERE kind='rebid' ORDER BY rowid").fetchall()
        self.assertTrue(rebids and rebids[-1][0]=='ACKNOWLEDGED',rebids)


if __name__=='__main__':unittest.main(verbosity=2)
