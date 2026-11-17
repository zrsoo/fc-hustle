"""Transfer targets occupy native slots even after terminal losses."""
from copy import deepcopy
from pathlib import Path
import json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.watch_capacity import slots

class WatchCapacityTests(unittest.TestCase):
    def occupied(self,h,count):
        h.ea.manual=[]
        for i in range(count):
            r=auction(123,15000,8000+i);r.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False)
            h.ea.manual.append(r)
    def test_closed_targets_limit_initials_to_actual_free_native_slots(self):
        for capacity,count,expected in [(50,47,3),(36,35,1),(50,50,0)]:
            with self.subTest(capacity=capacity),tempfile.TemporaryDirectory() as path:
                h=Harness(path,10)
                try:
                    h.ea.watch_capacity=capacity;self.occupied(h,count);h.controller.step()
                    self.assertEqual(len(h.calls('bid')),expected)
                    self.assertEqual(len(h.calls('balance')),1)
                    self.assertEqual(len(h.calls('search'))>=1,True)
                    self.assertTrue(all(c['command']['params']['amount']<=c['command']['params']['cap'] for c in h.calls('bid')))
                    b=json.loads(h.store.db.execute('select body from c4_policy_batches').fetchone()[0]);self.assertEqual(b['watch_slots'],capacity-count)
                finally:h.close()
    def test_full_list_is_capacity_outcome_and_new_fresh_read_can_recover(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,10)
            try:
                self.occupied(h,50);h.controller.step();self.assertEqual(h.calls('bid'),[])
                self.assertEqual(h.controller.journal.state()['lifecycle'],'RUNNING')
                self.occupied(h,0);h.controller.step();self.assertEqual(len(h.calls('bid')),10)
            finally:h.close()
    def test_absent_capacity_and_corrupt_count_grant_no_write_authority(self):
        for mode in ('missing','count','scope'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as path:
                h=Harness(path,10)
                try:
                    original=h.ea.shared
                    def damaged(c,at):
                        v=original(c,at)
                        if c['operation']=='watched':
                            if mode=='missing':v['coverage'].pop('watch_list')
                            elif mode=='count':v['coverage']['watch_list']['wire_count']=1
                            else:v['fences']['owner']='9'*32
                        return v
                    h.ea.shared=damaged;h.controller.step();self.assertEqual(h.calls('bid'),[])
                finally:h.close()
    def test_dispatch_rechecks_immutable_read_instead_of_trusting_batch_count(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,10)
            try:
                self.occupied(h,47)
                def changed(c):
                    if c['operation']=='status_batch':
                        batch=h.controller.journal.state()['batch_id'];h.controller.journal.update_batch(batch,watch_slots=50)
                h.ea.on_request=changed;h.controller.step();self.assertEqual(h.calls('bid'),[])
            finally:h.close()

if __name__=='__main__':unittest.main(verbosity=2)
