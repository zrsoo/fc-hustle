"""Claimed-auction disappearance and restart recovery in a socket-free world."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_work_fixture import harness,won,effects


class WinRecovery(unittest.TestCase):
    def test_owner_epoch_floor_never_lowers_persisted_fences_or_accepts_invalid_control(self):
        from fc_access.controller_v1.__main__ import next_owner_epoch
        self.assertEqual(next_owner_epoch(9,14),14)
        self.assertEqual(next_owner_epoch(14,1),15)
        self.assertEqual(next_owner_epoch(0),1)
        for old,floor in [(9,0),(9,-1),(9,True),(True,14),(9,2**53),(2**53-1,1)]:
            with self.assertRaises(ValueError):next_owner_epoch(old,floor)

    def test_item_location_diagnostics_accept_only_public_pile_categories(self):
        from fc_access.production_v1.diagnostics import validate_records
        row=dict(stage='NATIVE_DATA',at='2030-01-01T00:00:00Z',detail={})
        for pile in ('club','transfer','purchased','inbox','storage','other'):
            row['detail']={'item_pile':pile};self.assertEqual(validate_records([row]),[row])
        for value in ('SECRET_CANARY',False,None,123):
            row['detail']={'item_pile':value}
            with self.assertRaises(ValueError):validate_records([row])

    def setUp(self):
        self.addCleanup(patch.stopall)
        patch('socket.socket',side_effect=AssertionError('offline_world_no_network')).start()
        patch('subprocess.Popen',side_effect=AssertionError('offline_world_no_processes')).start()

    def directory(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);return tmp.name

    def make(self,path):
        h=harness(path,1);self.addCleanup(h.ea.world.close);self.addCleanup(h.close);return h

    def claimed(self,h):
        won(h);target=deepcopy(h.controller.journal.members()[0]['target'])
        def withdraw(c):
            if c['operation']=='move':
                h.ea.manual=[];h.ea.rows=[];h.ea.full.clear()
        h.ea.after_effect=withdraw;h.controller.step()
        self.assertEqual(effects(h),[('move',1)])
        h.clock.value+=45;h.ea.save();return target

    def test_claimed_auction_lists_after_watch_disappears_and_terminal_read_ages(self):
        path=self.directory()
        h=self.make(path);target=self.claimed(h);count=len(h.ea.calls)
        h.controller.step()
        self.assertEqual(effects(h),[('list',1),('move',1)])
        self.assertFalse(any(c['command']['operation']=='status_batch' and target in c['command']['params']['targets'] for c in h.ea.calls[count:]))
        move=h.calls('move')[0]['command'];listing=h.calls('list')[0]['command']
        self.assertEqual(move['params']['win_read_id'],listing['params']['win_read_id'])
        self.assertNotEqual(move['params']['owned_read_id'],listing['params']['owned_read_id'])
        self.assertEqual(listing['params']['duration'],3600)
        self.assertEqual(h.store.db.execute("SELECT state FROM c4_members WHERE trade_id=?",(target['trade_id'],)).fetchone()[0],'WON_ACCOUNTED')

    def test_claimed_auction_recovers_across_epoch_without_replaying_move(self):
        path=self.directory()
        h=self.make(path);target=self.claimed(h);old_fences=deepcopy(h.adapter.fences)
        # Close this world before reopening the same durable fixture.
        h.close();h.ea.world.close()
        new=self.make(path);self.assertNotEqual(new.adapter.fences,old_fences)
        new.controller.step();new.controller.step()
        self.assertEqual(effects(new),[('list',1),('move',1)])
        self.assertEqual(len(new.calls('move')),0)
        self.assertEqual(new.calls('list')[0]['command']['fences'],new.adapter.fences)

    def test_current_physical_identity_cost_tradability_and_caps_still_gate_listing(self):
        for mode in ('absent','identity','version','paid','untradeable','active','incomplete','caps'):
            with self.subTest(mode=mode):
                path=self.directory()
                h=self.make(path);self.claimed(h);row=h.ea.inventory[0]
                if mode=='absent':h.ea.inventory=[]
                elif mode=='identity':row['item']['item_id']='item:'+'f'*24
                elif mode=='version':row['item']['definition_id']+=1
                elif mode=='paid':row['item']['last_sale_price']+=50
                elif mode=='untradeable':row['item']['untradeable']=True
                elif mode=='active':row['trade_state']='active'
                elif mode=='incomplete':h.ea.inventory_complete=False
                else:h.ea.caps_max=100 # Fixture price service limit override below.
                if mode=='caps':
                    original=h.ea.shared
                    def limited(c,at):
                        v=original(c,at)
                        if c['operation']=='caps':v['result']['caps']['maximum']=100
                        return v
                    h.ea.shared=limited
                h.controller.step();h.controller.step()
                self.assertEqual(effects(h),[('move',1)])
                self.assertFalse(h.calls('list'))

    def test_unconfirmed_move_and_corrupt_retained_proof_never_authorize_listing(self):
        for mode in ('unknown','after','terminal','paid_bid'):
            with self.subTest(mode=mode):
                path=self.directory()
                h=self.make(path);self.claimed(h)
                cid,body,proof=h.store.db.execute('SELECT id,body,proof FROM c4_work').fetchone();c=json.loads(body)
                if mode=='unknown':
                    with h.store.db:h.store.db.execute("UPDATE c4_work SET state='UNKNOWN',proof=NULL WHERE id=?",(cid,))
                    # No fresh recovery read can establish this effect now.
                    h.ea.inventory_complete=False
                elif mode=='after':
                    p=json.loads(proof);p['after']['result']['auctions']=[]
                    with h.store.db:h.store.db.execute('UPDATE c4_work SET proof=? WHERE id=?',(json.dumps(p),cid))
                elif mode=='terminal':
                    rid=c['params']['win_read_id'];v=json.loads(h.store.db.execute('SELECT result FROM c4_commands WHERE id=?',(rid,)).fetchone()[0]);v['result']['auctions'][0]['native_is_won']=False
                    with h.store.db:h.store.db.execute('UPDATE c4_commands SET result=? WHERE id=?',(json.dumps(v),rid))
                else:
                    # Simulate absent dispatch lineage, not an ACK-based win.
                    with h.store.db:h.store.db.execute('DELETE FROM c4_tombstones')
                h.controller.step()
                self.assertEqual(effects(h),[('move',1)]);self.assertFalse(h.calls('list'))


if __name__=='__main__':unittest.main(verbosity=2)
