"""Real controller/store cleanup, restart and stop contracts; synthetic EA only."""
from copy import deepcopy
from pathlib import Path
import json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.lost_targets import parameters,effect
from fc_access.controller_v1.semantic import SemanticHealth,native_summary

class LostTargets(unittest.TestCase):
    def losses(self,h,count):
        h.ea.manual=[]
        for i in range(count):
            r=auction(123,15000,8000+i);r.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False);h.ea.manual.append(r)
    def test_losses_cleared_only_by_maintenance_at_capacity_and_other_cards_untouched(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,10)
            try:
                self.losses(h,48);active=auction(123,15000,9000);won=auction(123,15000,9001);won.update(trade_state='closed',bid_state='highest',expires=-1,native_is_won=True)
                h.ea.manual.extend([active,won]);original=deepcopy([active,won]);physical=auction(123,15000,9500);h.ea.inventory=[physical];before=deepcopy(h.ea.inventory)
                # 50/50: acquisition is a CAPACITY_FULL outcome and never cleans.
                h.controller.step();self.assertEqual(h.calls('clear_lost'),[]);self.assertEqual(h.calls('bid'),[])
                self.assertEqual(h.controller.status()['phase'],'MAINTENANCE')
                h.controller.step();self.assertEqual(len(h.calls('clear_lost')),1);self.assertEqual(h.calls('bid'),[])
                self.assertEqual(h.controller.status()['phase'],'ACQUIRING')
                h.controller.step();self.assertEqual(len(h.calls('bid')),10)
                self.assertEqual(h.ea.manual,original);self.assertEqual(h.ea.inventory,before)
                cmd=h.calls('clear_lost')[0]['command'];self.assertEqual(len(cmd['params']['targets']),48)
                state,proof=h.store.db.execute('select state,proof from c4_work where id=?',(cmd['id'],)).fetchone();self.assertEqual(state,'CONFIRMED');self.assertEqual(json.loads(proof)['mode'],'NATIVE_ACK_AND_READBACK')
                self.assertLess(h.calls('clear_lost')[0]['at'],h.calls('bid')[0]['at'])
            finally:h.close()
    def test_below_capacity_losses_are_never_cleared(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,10)
            try:
                self.losses(h,49)
                for _ in range(2):h.controller.step()
                self.assertEqual(h.calls('clear_lost'),[]);self.assertEqual(len(h.calls('bid')),1)
            finally:h.close()
    def test_no_eligible_target_never_dispatches_cleanup(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                for i,mode in enumerate(['active','won','unknown']):
                    r=auction(123,15000,9000+i)
                    if mode!='active':r.update(trade_state='closed',bid_state='highest' if mode=='won' else 'outbid',expires=-1,native_is_won=True if mode=='won' else None)
                    h.ea.manual.append(r)
                h.controller.step();self.assertEqual(h.calls('clear_lost'),[]);self.assertEqual(len(h.calls('bid')),1)
            finally:h.close()
    def test_lost_reply_resolves_actual_absence_without_replay_or_forged_ack(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                self.losses(h,2);h.ea.lost_mode='lost_reply';before=h.controller._read('watched');after=h.controller.work.clear_lost(before)
                self.assertIsNotNone(after);self.assertTrue(effect(h.calls('clear_lost')[0]['command'],before,after));self.assertEqual(len(h.calls('clear_lost')),1)
                state,proof=h.store.db.execute('select state,proof from c4_work').fetchone();self.assertEqual(state,'CONFIRMED');self.assertEqual(json.loads(proof)['mode'],'CURRENT_ABSENCE_AFTER_UNKNOWN')
                self.assertIsNone(h.controller.work.clear_lost(before));self.assertEqual(len(h.calls('clear_lost')),1)
            finally:h.close()
    def test_repeated_ack_without_effect_is_consumed_and_semantically_stops(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                self.losses(h,50);h.ea.lost_mode='no_effect';s=SemanticHealth(clock=h.clock.clock)
                h.executor.result=lambda c,v:s.observe(dict(kind='native_result',**native_summary(c,v)))
                h.store.semantic_report=lambda **fields:s.observe(dict(kind='batch_result',**fields))
                # ACQUIRING (full) -> MAINTENANCE (cleanup unconfirmed), three times.
                for _ in range(6):h.controller.step()
                self.assertEqual(len(h.calls('clear_lost')),1);self.assertEqual(h.calls('bid'),[]);self.assertEqual(s.check(),'PERSISTENT_ACQUISITION_FAILURE')
                self.assertEqual(h.store.db.execute('select state from c4_work').fetchone()[0],'UNKNOWN')
            finally:h.close()
    def test_intent_only_crash_is_not_replayed_after_restart(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                self.losses(h,50)
                def crash(stage):
                    if stage=='intent':raise RuntimeError('offline_fault')
                h.controller.work.checkpoint=crash;before=h.controller._read('watched')
                with self.assertRaises(RuntimeError):h.controller.work.clear_lost(before)
                self.assertEqual(h.calls('clear_lost'),[])
                h.controller=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
                h.controller.resume()
                for _ in range(2):h.controller.step()  # ACQUIRING (full) then MAINTENANCE
                self.assertEqual(h.calls('clear_lost'),[]);self.assertEqual(h.calls('bid'),[])
                self.assertEqual(h.store.db.execute('select state,dispatched_at from c4_work').fetchone(),('UNKNOWN',None))
            finally:h.close()
    def test_omitted_extra_or_stale_target_cannot_create_work_intent(self):
        for mode in ('subset','winner','stale'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as path:
                h=Harness(path,1)
                try:
                    self.losses(h,2);before=h.controller._read('watched');p=parameters(before)
                    if mode=='subset':p['targets'].pop()
                    elif mode=='winner':p['targets'][0]['definition_id']+=1
                    else:h.clock.value+=31
                    with self.assertRaises(ValueError):h.controller.work.dispatch('clear_lost',p)
                    self.assertEqual(h.store.db.execute('select count(*) from c4_work').fetchone()[0],0)
                    self.assertEqual(h.calls('clear_lost'),[])
                finally:h.close()
    def test_supervision_loss_during_burst_creates_no_later_intents(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,10)
            try:
                def lost():raise RuntimeError('SUPERVISION_LOST')
                def stop_after_first(c,v):
                    if c['operation']=='bid':h.store.supervision_guard=lost
                h.executor.result=stop_after_first;h.controller.step()
                self.assertEqual(len(h.calls('bid')),1);self.assertEqual(len(h.attempts()),1)
                self.assertEqual(h.store.db.execute('select count(*) from c4_decisions').fetchone()[0],1)
            finally:h.close()
    def test_supervision_loss_before_work_creates_no_intent(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                self.losses(h,1);before=h.controller._read('watched')
                def lost():raise RuntimeError('SUPERVISION_LOST')
                h.store.supervision_guard=lost
                with self.assertRaises(RuntimeError):h.controller.work.dispatch('clear_lost',parameters(before))
                self.assertEqual(h.store.db.execute('select count(*) from c4_work').fetchone()[0],0)
            finally:h.close()

if __name__=='__main__':unittest.main(verbosity=2)
