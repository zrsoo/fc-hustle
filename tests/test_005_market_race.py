"""Native competitive races stay uncertain; actual permission faults still stop."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from fc_access.controller_v1.semantic import native_summary,SemanticHealth
from test_005_semantic import event
from probe_005_readonly import run

class MarketRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows=[json.loads(l) for l in (ROOT/'docs/research/005/stage13/commands.jsonl').read_text().splitlines()]
        cls.race=next(r for r in rows if r['command']['id']=='16e5a43b1ce8e00ce3e87024c23a266e')
        cls.denied=next(r for r in rows if r['command']['id']=='5e52ce34012c95812c5caf3799a543cf')
    def test_captured_native_race_is_neither_ack_nor_operational_failure(self):
        r=self.race;m=native_summary(r['command'],r['response'])
        self.assertTrue(m['market_race']);self.assertFalse(m['success'])
        self.assertEqual(m['receipt_verdict'],'UNCONFIRMED')
        s=SemanticHealth(clock=lambda:0)
        for _ in range(20):s.observe(dict(kind='native_result',**m))
        self.assertIsNone(s.check());self.assertEqual(s.write_failures,0)
        self.assertEqual(s.confirmed,0);self.assertEqual(s.native_successes,0)
    def test_tie_at_our_amount_is_a_race_not_a_write_failure(self):
        # Live 2026-11-20 13:28: three rebids (3200, 3300, 3400) each answered
        # native 200 with the auction outbid at exactly our amount; they were
        # counted as write failures and stopped the runtime.
        r=deepcopy(self.race);amount=r['command']['params']['amount']
        r['response']['receipt']['auction']['current_bid']=amount
        m=native_summary(r['command'],r['response'])
        self.assertTrue(m['market_race'])
        s=SemanticHealth(clock=lambda:0)
        for _ in range(5):s.observe(dict(kind='native_result',**m))
        self.assertEqual(s.write_failures,0);self.assertIsNone(s.check())
    def test_race_never_resets_permission_failure_streak(self):
        s=SemanticHealth(clock=lambda:0)
        denied=dict(kind='native_result',**native_summary(self.denied['command'],self.denied['response']))
        self.assertFalse(denied['market_race'])
        for i in range(3):
            s.observe(denied)
            s.observe(dict(kind='native_result',**native_summary(self.race['command'],self.race['response'])))
            s.observe(event('watched'))
            self.assertEqual(s.write_failures,i+1)
        self.assertEqual(s.check(),'PERSISTENT_WRITE_FAILURE');self.assertEqual(s.confirmed,0)
    def test_incoherent_stale_wrong_identity_or_noncompetitive_receipts_are_faults(self):
        cases=[('command_id','b'*32),('status',403),('success',True),('error','ambiguous_network'),
               ('receipt.native_success',False),('receipt.native_error_code',461),
               ('receipt.wire_identity_matches',False),('receipt.wire_amount_matches',False),
               ('receipt.wire_amount',900),('receipt.wire_item_count',0),('receipt.native_item_count',2),
               ('receipt.matching_item_count',0),('receipt.input_stale',True),
               ('receipt.wire_trade_id','trade:'+'0'*24),('receipt.auction.current_bid',800),
               ('receipt.auction.bid_state','highest'),('receipt.auction.trade_state','closed'),
               ('receipt.auction.item.item_id','item:'+'0'*24),('receipt.auction.item.definition_id',999),
               ('network.0.status',461),('network.0.session_header_present',False)]
        for field,value in cases:
            with self.subTest(field=field):
                r=deepcopy(self.race);v=r['response'];parts=field.split('.')
                for k in parts[:-1]:v=v[int(k)] if isinstance(v,list) else v[k]
                v[int(parts[-1]) if isinstance(v,list) else parts[-1]]=value
                self.assertFalse(native_summary(r['command'],r['response'])['market_race'])
    def test_probe_rejects_invalid_or_duplicate_targets_before_creating_artifacts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'must-not-exist';t=self.race['command']['params']['target']
            for targets in ([t,t],[dict(t,definition_id=-1)]):
                with self.assertRaises(ValueError):run(p,epoch=1,status_targets=targets)
                self.assertFalse(p.exists())

if __name__=='__main__':unittest.main(verbosity=2)
