"""Independent current-generation cleanup audit rejects forged functional proof."""
from copy import deepcopy
from pathlib import Path
import json,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from validate_005_lifecycle import Evidence,audit_lost_cleanup
class LostAudit(unittest.TestCase):
    def test_resolved_unknown_is_reported_without_becoming_native_success(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                def loss(i):
                    r=auction(123,15000,i);r.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False);return r
                h.ea.manual=[loss(8000)];h.ea.lost_mode='lost_reply';h.controller.work.clear_lost(h.controller._read('watched'))
                h.ea.manual=[loss(8001)];h.ea.lost_mode='ok';h.controller.work.clear_lost(h.controller._read('watched'))
                ids=[r[0] for r in h.store.db.execute('select id from c4_commands')];e=Evidence(h.store.db,ids,{},live=False);result=audit_lost_cleanup(e)
                self.assertEqual(len(result['confirmed']),1);self.assertEqual(len(result['resolved_unknown']),1)
            finally:h.close()
    def test_actual_controller_effect_and_negative_receipt_readback_targets(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                # Cleanup happens only in MAINTENANCE once the watch list is full (49 lost + 1 active).
                h.ea.manual=[]
                for i in range(49):
                    r=auction(123,15000,8000+i);r.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False);h.ea.manual.append(r)
                h.ea.manual.append(auction(123,15000,8100));h.controller.step();h.controller.step()
                ids=[r[0] for r in h.store.db.execute('select id from c4_commands')];e=Evidence(h.store.db,ids,{},live=False);result=audit_lost_cleanup(e);self.assertEqual(len(result['confirmed']),1)
                cid=result['confirmed'][0];c,v=e.get(cid);after=json.loads(h.store.db.execute('select proof from c4_work where id=?',(cid,)).fetchone()[0])['after']['command_id']
                for mode in ('wire','scope','target','effect'):
                    with self.subTest(mode=mode):
                        x=Evidence(h.store.db,ids,{},live=False);x.cache=deepcopy(e.cache)
                        if mode=='wire':x.cache[cid][1]['network'][0]['status']=403
                        elif mode=='scope':x.cache[cid][0]['fences']['owner']='9'*32
                        elif mode=='target':x.cache[cid][0]['params']['targets'][0]['definition_id']+=1
                        else:
                            av=x.cache[after][1];av['result']['auctions']=[]
                            for k in ('wire_count','callback_count','repository_count'):av['coverage']['watch_list'][k]=0
                        with self.assertRaises((ValueError,KeyError)):audit_lost_cleanup(x)
            finally:h.close()
if __name__=='__main__':unittest.main(verbosity=2)
