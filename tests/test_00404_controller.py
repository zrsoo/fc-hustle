"""Independent behavioral lifecycle/resale/maintenance acceptance, entirely offline."""
from copy import deepcopy
from contextlib import closing
from datetime import timedelta
import importlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from controller_work_fixture import harness,won,effects,WorkEA
from native_price_fixture import auction
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.protocol import delivery_command
from fc_access.controller_v1.work import parameters


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        # Any attempt to attach a network service (including production loopback)
        # fails before socket construction. Native DTOs terminate in WorkEA.
        patch('socket.socket',side_effect=AssertionError('fixture_network_forbidden')).start()
        patch('subprocess.Popen',side_effect=AssertionError('fixture_process_forbidden')).start()

    def make(self,n=2):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        h=harness(tmp.name,n);self.addCleanup(h.ea.world.close);self.addCleanup(h.close)
        return h

    def work(self,h):return list(h.store.db.execute('SELECT id,state,body,proof FROM c4_work ORDER BY rowid'))

    def test_0_imports_and_new_controller_are_inert_until_explicit_run(self):
        for name in ('controller','work','server','__main__'):
            importlib.reload(importlib.import_module('fc_access.controller_v1.'+name))
        h=self.make();h.controller.stop()
        h.store.db.execute("DELETE FROM c4_controller");h.store.db.commit()
        c=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
        self.assertEqual(c.status()['lifecycle'],'STOPPED');c.step();self.assertEqual(h.ea.calls,[])
        c.run(steps=1);self.assertEqual(len(h.calls('bid')),2)
        self.assertEqual(c.status()['phase'],'MANAGING')

    def test_0_pause_stop_wait_for_dispatch_and_quiesce_every_operation(self):
        for action in ('pause','stop'):
            h=self.make();entered=threading.Event();release=threading.Event();returned=threading.Event();errors=[]
            def hold(c):
                if c['operation']=='balance':entered.set();release.wait(5)
            h.ea.on_request=hold
            def step():
                try:h.controller.step()
                except Exception as e:errors.append(type(e).__name__)
            runner=threading.Thread(target=step);runner.start();self.assertTrue(entered.wait(4))
            control=threading.Thread(target=lambda:(getattr(h.controller,action)(),returned.set()));control.start()
            self.assertFalse(returned.wait(.05),'control must drain in-flight work')
            release.set();runner.join(5);control.join(5)
            self.assertFalse(runner.is_alive() or control.is_alive());self.assertFalse(errors)
            self.assertEqual(len(h.calls('bid')),0)
            n=len(h.ea.calls)
            for _ in range(3):h.controller.step();h.controller.work.maintenance()
            self.assertEqual(len(h.ea.calls),n);self.assertEqual(h.controller.status()['phase'],'ACQUIRING')
            c=h.adapter.envelope(h.ids(),'balance',{})
            with self.assertRaisesRegex(ValueError,'quiesced'):h.store.enqueue(c,h.store.peer)
            self.assertIsNone(h.store.claim(h.store.peer))

    def test_0_queued_commands_withdrawn_and_stale_owners_cannot_control(self):
        h=self.make();c=h.adapter.envelope(h.ids(),'balance',{});h.store.enqueue(c,h.store.peer)
        h.controller.pause();self.assertEqual(h.store.db.execute('SELECT state FROM c4_commands WHERE id=?',(c['id'],)).fetchone()[0],'UNKNOWN')
        self.assertIsNone(h.store.claim(h.store.peer));h.controller.resume()
        peer=deepcopy(h.store.peer);peer['fences'].update(owner=h.ids(),document=h.ids(),epoch=2);h.store.attach(peer)
        for fn in (h.controller.step,h.controller.pause,h.controller.stop,h.controller.resume):
            with self.assertRaisesRegex(ValueError,'stale_peer'):fn()
        self.assertEqual(h.ea.calls,[])

    def test_3_separate_store_takeover_fences_surviving_old_process_connection(self):
        from fc_access.controller_v1.store import ControllerStore
        h=self.make();h.controller.step()
        other=ControllerStore(h.store.path,write_authority=True,now=h.clock.now)
        try:
            peer=deepcopy(h.store.peer);peer['fences'].update(owner=h.ids(),document=h.ids(),epoch=2,host_epoch=other.host_epoch)
            other.attach(peer)
            for fn in (h.controller.step,h.controller.resume,h.controller.pause,h.controller.stop):
                with self.assertRaisesRegex(ValueError,'stale_durable_owner'):fn()
            with self.assertRaisesRegex(ValueError,'stale_durable_owner'):h.store.claim(h.store.peer)
            with self.assertRaisesRegex(ValueError,'stale_durable_owner'):
                Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
        finally:other.close()

    def test_1_exact_paid_win_moves_then_lists_at_stored_native_pair_and_hour(self):
        h=self.make();won(h);price=h.controller.journal.members()[0]['resale_price']
        h.controller.step();self.assertEqual(effects(h),[],'MANAGING never writes resale/maintenance work')
        self.assertEqual(h.controller.status()['phase'],'MAINTENANCE')
        h.controller.step();self.assertEqual(effects(h),[('list',1),('move',1)])
        self.assertEqual(h.controller.status()['phase'],'ACQUIRING')
        self.assertEqual(len(h.calls('balance')),1,'no acquisition between move and list')
        resales=[];cleanups=[]
        for _,state,body,proof in self.work(h):
            c=json.loads(body);self.assertEqual(state,'CONFIRMED');self.assertIsNotNone(json.loads(proof)['after'])
            if c['operation']=='clear_lost':
                cleanups.append(c)
                before=h.store.result(c['params']['before_read_id'])
                self.assertEqual(before['operation'],'watched')
                expected={(r['trade_id'],r['item']['item_id'],r['item']['definition_id']) for r in before['result']['auctions']
                    if r['trade_state'] in {'closed','expired'} and r['expires']<=0 and r['bid_state'] in {'none','outbid'} and r['native_is_won'] is False}
                self.assertEqual({(t['trade_id'],t['item_id'],t['definition_id']) for t in c['params']['targets']},expected)
                self.assertEqual(len(expected),1)
            else:
                self.assertIn(c['operation'],{'move','list'});resales.append(c['operation'])
                self.assertEqual((c['params']['starting_bid'],c['params']['buy_now_price'],c['params']['duration']),(11750,price,3600))
        # One lost target is far below watch capacity: no clear_lost at all.
        self.assertEqual(sorted(resales),['list','move']);self.assertEqual(len(cleanups),0)
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_members WHERE state='WON_ACCOUNTED'").fetchone()[0],1)
        self.assertEqual(h.ea.max_active,1)

    def test_1_paid_identity_version_tradeability_terminal_cost_negatives(self):
        for mode in ('cost','zero','physical','version','untradeable','not_won','future_terminal'):
            h=self.make();won(h)
            if mode=='cost':h.ea.owned[0]['last_sale_price']=999
            if mode=='zero':h.ea.owned[0]['last_sale_price']=0
            if mode=='physical':h.ea.owned[0]['item_id']='item:'+'f'*24
            if mode=='version':h.ea.owned[0]['definition_id']=999
            if mode=='untradeable':h.ea.owned[0]['untradeable']=True
            if mode=='not_won':h.ea.rows[0]['native_is_won']=False
            if mode=='future_terminal':h.ea.rows[0]['expires']=50
            h.ea.manual=deepcopy(h.ea.rows)
            for _ in range(3):h.controller.step()
            self.assertEqual(effects(h),[],mode)
            # Unverified wins stay members (ACTIVE when EA denies the win), never accounted.
            self.assertEqual([m['state'] for m in h.controller.journal.members()],['ACTIVE' if mode=='not_won' else 'PENDING_WIN'],mode)
            self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_members WHERE state='WON_ACCOUNTED'").fetchone()[0],0,mode)

    def test_1_bad_listing_readbacks_cannot_account_for_win_or_replay(self):
        for mode in ('price','duration','physical','trade','state','missing'):
            h=self.make();won(h);h.controller.step()
            def corrupt(c):
                if c['operation']!='list':return
                r=h.ea.inventory[0]
                if mode=='price':r['buy_now_price']-=250
                if mode=='duration':r['expires']=7200
                if mode=='physical':r['item']['item_id']='item:'+'f'*24
                if mode=='trade':r['trade_id']=c['params']['trade_id']
                if mode=='state':r['trade_state']='inactive'
                if mode=='missing':h.ea.inventory=[]
            h.ea.bad_after=corrupt
            for _ in range(4):h.controller.step()
            self.assertEqual(effects(h),[('list',1),('move',1)],mode)
            self.assertEqual([m['state'] for m in h.controller.journal.members()],['PENDING_WIN'],mode)
            self.assertEqual(self.work(h)[1][1],'UNKNOWN')

    def inventory(self,h,sold=1,expired=1,active=1):
        rows=[auction(123,15000,n+100) for n in range(sold+expired+active)]
        for n,r in enumerate(rows):r.update(trade_state='closed' if n<sold else 'expired' if n<sold+expired else 'active',current_bid=15000 if n<sold else 0,expires=-1 if n<sold+expired else 9000,bid_state='none',native_is_won=False)
        h.ea.inventory=rows;h.ea.save();h.controller.work.inventory=h.controller.work.pile()

    def tick(self,h):
        due=h.store.db.execute('SELECT next_due FROM c4_maintenance').fetchone()[0]
        from fc_access.production_v1.contracts import stamp
        h.clock.value+=(stamp(due)-h.clock.now()).total_seconds()
        h.controller.work.maintenance()

    def test_1_bulk_clear_and_3660_relist_reuse_independent_readbacks_and_prices(self):
        h=self.make(0);self.inventory(h,sold=0);before=deepcopy(h.ea.inventory)
        h.controller.work.maintenance();self.assertFalse(effects(h))
        self.tick(h);self.assertEqual(effects(h),[('relist_all',1)])
        self.assertEqual(self.work(h)[0][1],'CONFIRMED')
        self.assertEqual([(r['starting_bid'],r['buy_now_price']) for r in h.ea.inventory],[(r['starting_bid'],r['buy_now_price']) for r in before])
        self.assertEqual(h.ea.inventory[0]['expires'],3600);self.assertEqual(h.ea.inventory[1],before[1])
        h.controller.work.maintenance();self.assertEqual(effects(h),[('relist_all',1)])
        # A genuinely new expired trade generation can relist on the next tick.
        h.ea.inventory[0].update(trade_state='expired',expires=-1)
        h.controller.work.inventory=h.controller.work.pile()
        h.controller.work.maintenance();self.assertEqual(effects(h),[('relist_all',1)])
        self.tick(h);self.assertEqual(effects(h),[('relist_all',2)])
        # Sold clearing includes manual rows and preserves the expired/active set.
        self.inventory(h,sold=2,expired=1,active=1);kept=deepcopy(h.ea.inventory[2:]);h.controller.work.maintenance()
        self.assertEqual(h.ea.inventory,kept);self.assertIn(('clear_sold',1),effects(h))
        h=self.make(0);self.inventory(h,sold=1,expired=1);self.tick(h)
        self.assertEqual(effects(h),[('clear_sold',1),('relist_all',1)])
        self.assertEqual([r[1] for r in self.work(h)],['CONFIRMED','CONFIRMED'])

    def test_2_urgent_rebid_precedes_resale_and_bulk_without_overlap_or_credits(self):
        h=self.make();h.controller.step();h.ea.rows[0].update(trade_state='closed',bid_state='highest',native_is_won=True,expires=0)
        h.ea.rows[1].update(bid_state='outbid',current_bid=200,expires=10);h.ea.owned=[dict(h.ea.rows[0]['item'],last_sale_price=150)];h.ea.manual=deepcopy(h.ea.rows)
        self.inventory(h,sold=1,expired=0);n=len(h.ea.calls)
        # While an auction is still active, MANAGING only reads and rebids.
        for _ in range(3):h.controller.step()
        ops=[v['command']['operation'] for v in h.ea.calls[n:]]
        self.assertIn('bid',ops);self.assertNotIn('move',ops);self.assertNotIn('clear_sold',ops)
        self.assertEqual(h.controller.status()['phase'],'MANAGING')
        h.ea.rows[1].update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False);h.ea.manual=deepcopy(h.ea.rows)
        for _ in range(2):h.controller.step()
        ops=[v['command']['operation'] for v in h.ea.calls[n:]]
        writes=[op for op in ops if op in {'move','list','clear_sold','relist_all','clear_lost'}]
        self.assertEqual(writes[:1],['move']);self.assertIn('clear_sold',writes)
        self.assertLess(max(i for i,op in enumerate(ops) if op=='bid'),ops.index('move'))
        self.assertEqual(h.ea.max_active,1);self.assertEqual(len(h.calls('balance')),1)

    def test_2_ambiguous_bulk_consumed_without_blocking_unrelated_work(self):
        h=self.make(1);self.inventory(h,sold=1,expired=0);h.ea.effect=False;h.ea.lose_reply=True
        h.controller.work.maintenance();self.assertEqual(effects(h),[('clear_sold',1)])
        self.assertEqual(self.work(h)[0][1],'UNKNOWN')
        h.controller.work.maintenance();h.controller.work.maintenance();self.assertEqual(effects(h),[('clear_sold',1)])
        h.ea.lose_reply=False;h.controller.step();self.assertEqual(len(h.calls('bid')),1)
        self.assertEqual(h.controller.status()['lifecycle'],'RUNNING')
        # A changed bulk set must not smuggle the same consumed generation back.
        h.ea.inventory.append(deepcopy(auction(123,15000,500)));h.ea.inventory[-1].update(trade_state='closed',expires=-1,current_bid=15000)
        h.controller.work.inventory=h.controller.work.pile();h.controller.work.maintenance()
        self.assertEqual(effects(h),[('clear_sold',1)])
        self.assertNotIn('CANARY',json.dumps(h.controller.status()))

    def test_5_bulk_negative_readbacks_and_incompatible_evidence_stay_consumed(self):
        for mode in ('price','duration','identity','missing_other','duplicate_trade'):
            h=self.make(0);self.inventory(h,sold=0,expired=2,active=1)
            def corrupt(c):
                if c['operation']!='relist_all':return
                if mode=='price':h.ea.inventory[0]['buy_now_price']-=250
                if mode=='duration':h.ea.inventory[0]['expires']=7200
                if mode=='identity':h.ea.inventory[0]['item']['definition_id']=999
                if mode=='missing_other':h.ea.inventory.pop()
                if mode=='duplicate_trade':h.ea.inventory[1]['trade_id']=h.ea.inventory[0]['trade_id']
            h.ea.bad_after=corrupt;self.tick(h)
            self.assertEqual(self.work(h)[0][1],'UNKNOWN',mode)
            h.controller.work.maintenance();h.controller.work.reconcile(self.work(h)[0][0])
            self.assertEqual(effects(h),[('relist_all',1)],mode)
            self.assertEqual(self.work(h)[0][1],'UNKNOWN')

    def test_5_current_caps_native_tick_duration_and_stored_policy_enforced_at_authority(self):
        h=self.make();won(h);h.controller.step();captured=[];real=h.controller.work.dispatch
        def capture(op,p):
            if op=='move':return real(op,p)
            captured.append((op,p))
        with patch.object(h.controller.work,'dispatch',side_effect=capture):h.controller.step()
        self.assertEqual(captured[0][0],'list');op,p=captured[0]
        for key,value in (('buy_now_price',11750),('starting_bid',11500),('paid',999),('duration',7200),('owned_read_id',p['caps_read_id'])):
            bad=dict(p,**{key:value})
            with self.assertRaises((ValueError,sqlite3.IntegrityError),msg=key):h.controller.work.dispatch(op,bad)
        self.assertEqual(effects(h),[('move',1)])

    def test_3_reconnect_mapping_loss_never_uses_old_selector_or_owner(self):
        h=self.make();h.controller.step();members=h.controller.journal.members();prices=[m['resale_price'] for m in members]
        from fc_access.controller_v1.adapter import ControllerAdapter
        old=h.adapter;h.ea.full.clear();h.ea.manual=[]
        h.ea.fences.update(owner=h.ids(),document=h.ids(),epoch=2)
        h.adapter=ControllerAdapter(h.executor,context=h.ea.context,owner=h.ea.fences['owner'],epoch=2,now=h.clock.now);h.adapter.native.source='fixture'
        h.controller=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
        h.controller.step();self.assertEqual(len(h.calls('bid')),2)
        self.assertEqual(len(h.controller.journal.members()),2);self.assertEqual([m['resale_price'] for m in h.controller.journal.members()],prices)
        with self.assertRaises(ValueError):h.executor.execute(old.envelope(h.ids(),'balance',{}))
        h.ea.manual=deepcopy(h.ea.rows)
        for r in h.ea.rows:r.update(bid_state='outbid',current_bid=200)
        h.ea.manual=deepcopy(h.ea.rows);h.controller.mapping_refresh_needed=True
        # The empty reconnect watch list left both unmappable (MAPPING_LOST), so the
        # cycle passes MAINTENANCE/ACQUIRING before MANAGING re-maps and rebids.
        for _ in range(3):
            if len(h.calls('bid'))==4:break
            h.controller.step()
        self.assertEqual(len(h.calls('bid')),4)

    def test_4_every_durable_persistence_failure_prevents_native_mutation(self):
        for table in ('c4_work','c4_commands','c4_tombstones'):
            h=self.make();won(h)
            with h.store.db:h.store.db.execute(f"CREATE TRIGGER fail_write BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'disk unavailable'); END")
            h.controller.step();self.assertEqual(effects(h),[],table)
            self.assertFalse(h.calls('move'));self.assertFalse(h.calls('list'))
        h=self.make(0);self.inventory(h,sold=0);h.ea.inventory_complete=False;self.tick(h);self.assertEqual(effects(h),[])

    def test_5_long_final_auction_and_unknown_full_low_inventory_never_fake_settlement(self):
        h=self.make();h.controller.step()
        h.ea.rows[0].update(trade_state='closed',bid_state='outbid',expires=0,native_is_won=False)
        h.ea.rows[1].update(bid_state='outbid',current_bid=20000,expires=100000)
        for _ in range(4):h.controller.step()
        self.assertEqual(h.controller.status()['phase'],'MANAGING');self.assertEqual(len(h.calls('balance')),1)
        h.ea.missing={h.ea.rows[1]['trade_id']};h.clock.value+=200000;h.controller.step()
        self.assertEqual(len(h.controller.journal.members()),1)
        for mode in ('low','unknown','full'):
            h=self.make(1)
            if mode=='low':h.ea.credits=40000
            if mode=='unknown':h.ea.inventory_complete=False
            if mode=='full':h.ea.inventory=[auction(123,15000,n+100) for n in range(50)]
            h.controller.step();self.assertFalse(h.calls('bid'),mode)

    def test_6_fixture_cannot_open_production_socket_or_state_or_owner(self):
        h=self.make()
        for port in (8783,8784,9999):
            with self.assertRaisesRegex(AssertionError,'fixture_network'):socket.create_connection(('127.0.0.1',port))
        self.assertEqual(h.adapter.context['account'],'f'*32)
        self.assertNotEqual(self.make().adapter.fences['owner'],h.adapter.fences['owner'])
        with self.assertRaisesRegex(ValueError,'temp_root'):WorkEA(type('S',(),{'path':ROOT/'private-captures/production-v1/native.sqlite'})(),h.clock,0)
        before=deepcopy(h.store.peer);wrong=deepcopy(before);wrong['context']['account']='a'*32;wrong['fences']['epoch']=9
        with self.assertRaisesRegex(ValueError,'account_mismatch'):h.store.attach(wrong)
        self.assertEqual(h.store.peer,before)
        from fc_access.controller_v1.store import ControllerStore
        path=h.path/'legacy-shaped.sqlite'
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE commands(id TEXT)')
        with self.assertRaisesRegex(ValueError,'isolated_controller_database'):ControllerStore(path,write_authority=True)

    def test_6_forged_maintenance_requests_have_no_durable_authority(self):
        h=self.make(0);self.inventory(h,sold=1,expired=0)
        c=h.controller.native.envelope(h.ids(),'clear_sold',parameters(h.controller.work.inventory,'clear_sold'))
        delivery_command(c)
        with self.assertRaisesRegex(ValueError,'durable_work_intent'):h.store.enqueue(c,h.store.peer)
        self.assertFalse(effects(h))


if __name__=='__main__':unittest.main(verbosity=2)
