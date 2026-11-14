"""Automatic sold maintenance: real SQLite, process locks, crashes and broker.

Only synthetic native effects are exercised; no historical live run is replayed.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from actors_fixture import Clock, CONTEXT, RealClock
from test_00209_bulk import BulkPage, inventory
from fc_access.actors_v1.actors import Acquirer
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.maintenance import TransferMaintenance
from fc_access.actors_v1.native import Broker, Mailbox, QueueExecutor
from fc_access.actors_v1.sold import SoldClear
from fc_access.bidding_v1 import capacity
from fc_access.production_v1.bulk import BulkTransfer, pending
from fc_access.production_v1.contracts import stamp
from fc_access.production_v1.foundation import Foundation, JournalAuthority


class Acceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name); self.clock = Clock()
        self.page = BulkPage(self.path, self.clock); self.f = self.open()
        self.addCleanup(self.page.close); self.addCleanup(lambda: self.f.close())

    def open(self):
        return Foundation(self.page, context=CONTEXT, journal_path=self.path/'journal.sqlite3', fixture=True,
            now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)

    def restart(self):
        self.f.close(); self.f = self.open()

    def count(self):
        return capacity.status(self.f.journal, self.f.registry.scope, now=self.clock.now())

    def events(self, kind):
        return [e for e in self.f.registry.events() if e['kind'] == kind]

    def maintenance(self):
        return TransferMaintenance(self.f, clock=self.clock.monotonic, sleep=self.clock.sleep)

    def test_detection_one_durable_account_wide_clear_retains_expired_and_active_manual_cards(self):
        before = deepcopy(self.page.transfer_items)
        result = SoldClear(self.f).step()
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertEqual(self.page.transfer_items, before[2:])
        self.assertEqual([c['operation'] for c in self.page.calls], ['transfer_list', 'clear_sold', 'transfer_list'])
        self.assertEqual(len(self.page.writes), 1)
        c = self.page.writes[0]
        self.assertEqual(c['params']['expected_item_ids'], sorted(r['item']['item_id'] for r in before[:2]))
        self.assertTrue(JournalAuthority(self.f.journal_path).reconciled(c))
        detection = next(e for e in self.events('BULK_TRANSFER') if e['reason'] == 'SOLD_DETECTED')
        verified = next(e for e in self.events('BULK_TRANSFER') if e['reason'] == 'VERIFIED')
        self.assertEqual(c['params']['before_read_id'], detection['read_id'])
        self.assertLess(detection['seq'], next(e['seq'] for e in self.events('BULK_TRANSFER') if e['reason']=='INTENT_DURABLE'))
        self.assertNotIn(verified['read_id'], {c['id'], detection['read_id']})
        self.assertTrue(verified['readback']['coverage']['complete'])
        self.assertEqual(verified['readback']['result']['auctions'], before[2:])
        self.assertEqual(self.count()['occupied'], 4)
        self.assertFalse(self.events('ENROLLMENT'))
        self.assertEqual(SoldClear(self.f).step()['status'], 'SKIPPED')
        self.assertEqual(len(self.page.writes), 1)

    def test_polling_detects_new_sale_without_explicit_clear_command_and_relist_keeps_cadence(self):
        self.page.transfer_items = inventory()[4:]
        worker = self.maintenance()
        worker.run(cycles=1)
        self.assertFalse(self.page.writes)
        row = self.page.transfer_items[0]
        row.update(trade_state='closed', current_bid=1000, expires=-1)
        self.clock.sleep(25)
        worker.run(cycles=2)
        self.assertEqual([c['operation'] for c in self.page.writes], ['clear_sold'])
        self.assertEqual(len(self.page.transfer_items), 1)
        self.assertEqual(self.f.journal.db.execute('SELECT count(*) FROM relist_ticks_v1').fetchone(), (1,))
        starts = [stamp(e['at']) for e in self.events('ACTOR') if e['reason']=='CYCLE_STARTED']
        self.assertEqual(len(starts), 3)
        self.assertTrue(all((b-a).total_seconds() >= 25 for a,b in zip(starts, starts[1:])))

    def test_automatic_clear_precedes_due_relist_and_each_has_independent_fresh_reads(self):
        before = deepcopy(self.page.transfer_items)
        result = self.maintenance().cycle()
        self.assertEqual(result['clear']['status'], 'CONFIRMED')
        self.assertEqual(result['relist']['status'], 'CONFIRMED')
        self.assertEqual([c['operation'] for c in self.page.calls],
            ['transfer_list', 'clear_sold', 'transfer_list', 'transfer_list', 'relist_all', 'transfer_list'])
        self.assertEqual(self.page.transfer_items[2:], before[4:])
        for old,new in zip(before[2:4], self.page.transfer_items[:2]):
            self.assertEqual((old['starting_bid'],old['buy_now_price']), (new['starting_bid'],new['buy_now_price']))
            self.assertEqual(new['expires'],3600)

    def test_incomplete_stale_unowned_and_mismatched_predicates_never_dispatch(self):
        changes = [lambda v:v['coverage'].update(complete=False,has_more=True),
            lambda v:v['freshness'].update(network_at=(self.clock.now().replace(year=2020)).isoformat()),
            lambda v:v['coverage']['bulk'][0].update(trade_owner=False),
            lambda v:v['coverage']['bulk'][0].update(sold=False)]
        for change in changes:
            self.page.bad_proof = change
            with self.assertRaises((ValueError,TimeoutError)): SoldClear(self.f).step()
            self.assertFalse(self.page.writes)
            self.assertFalse(pending(self.f.journal,self.f.registry.scope))
        self.assertFalse(self.events('SOLD_SETTLEMENT'))

    def test_unknown_no_effect_and_missing_readback_block_relist_and_never_retry(self):
        self.page.effect = False
        self.assertEqual(self.maintenance().cycle()['status'], 'UNRESOLVED')
        self.assertEqual(self.count()['occupied'], 6)
        self.restart()
        for _ in range(3):
            self.assertEqual(self.maintenance().cycle()['status'], 'RECONCILIATION_ONLY')
        self.assertEqual([c['operation'] for c in self.page.writes], ['clear_sold'])
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)
        self.assertEqual(self.f.journal.db.execute("SELECT name FROM sqlite_master WHERE name='relist_ticks_v1'").fetchall(), [])

    def test_lost_ack_can_reconcile_without_replacement_write(self):
        self.page.timeout = True
        self.assertEqual(SoldClear(self.f).step()['status'], 'CONFIRMED')
        self.restart()
        self.assertEqual(SoldClear(self.f).step()['status'], 'SKIPPED')
        self.assertEqual(len(self.page.writes), 1)
        self.assertFalse(pending(self.f.journal,self.f.registry.scope))

    def test_ack_does_not_release_capacity_then_read_only_recovery_commits_release(self):
        original = deepcopy(self.page.transfer_items)
        service = BulkTransfer(self.f); service.observe(service.inventory())
        for r in original[:2]:
            self.f.journal.db.execute('INSERT INTO capacity_slots_v1 VALUES(?,?,?,?,?)',
                (self.f.registry.scope,r['trade_id'],r['item']['item_id'],r['item']['definition_id'],'OCCUPIED'))
        self.page.block_readback = True
        self.assertEqual(SoldClear(self.f).step()['status'], 'UNRESOLVED')
        self.assertEqual(self.count()['total'],6)
        self.assertEqual(self.f.journal.db.execute('SELECT DISTINCT phase FROM capacity_slots_v1').fetchall(),[('OCCUPIED',)])
        self.assertEqual(len(self.page.transfer_items),4,'native effect alone is insufficient')
        self.restart(); self.page.block_readback = False
        self.assertEqual(SoldClear(self.f).step()['status'],'RECONCILIATION_ONLY')
        self.assertEqual(self.count()['total'],4)
        self.assertEqual(self.f.journal.db.execute('SELECT DISTINCT phase FROM capacity_slots_v1').fetchall(),[('RELEASED',)])
        self.assertEqual(len(self.page.writes),1)

    def test_confirmed_capacity_release_resumes_acquirer_but_not_sticky_coin_draining(self):
        cfg = Config(max_transfer_list_occupied=6,max_total_pipeline_slots=6)
        acquirer = Acquirer(self.f,cfg)
        acquirer.cycle()
        self.assertFalse([c for c in self.page.calls if c['operation']=='search'])
        self.assertTrue(any(e['reason']=='CAPACITY_PAUSED' for e in self.events('ACTOR')))
        self.assertEqual(SoldClear(self.f).step()['status'],'CONFIRMED')
        acquirer.cycle()
        self.assertEqual(self.page.bid_calls,1)
        self.assertTrue(any(e['reason']=='CAPACITY_RESUMED' for e in self.events('ACTOR')))
        # An unresolved acquisition preserves DRAINING even when money and
        # physical capacity return. Maintenance does not touch coin policy.
        self.page.credits = 1000
        acquirer.cycle()
        self.assertTrue(self.f.queue.draining)
        self.page.credits = 100000
        self.page.transfer_items[0].update(trade_state='closed',current_bid=1000,expires=-1)
        # Outstanding bid must reconcile before any maintenance write.
        with self.assertRaisesRegex(ValueError,'reconciliation_required'): SoldClear(self.f).step()
        acquirer.cycle()
        self.assertTrue(self.f.queue.draining)
        self.assertEqual(self.page.bid_calls,1)
        self.assertEqual(self.events('ACTOR')[-1]['reason'],'DRAINING')

    def test_capacity_release_itself_never_clears_coin_draining(self):
        cfg=Config(max_total_pipeline_slots=6,max_transfer_list_occupied=6)
        acquirer=Acquirer(self.f,cfg)
        self.page.credits=1000; acquirer.cycle()
        self.assertTrue(self.f.queue.draining)
        self.assertEqual(SoldClear(self.f).step()['status'],'CONFIRMED')
        from fc_access.bidding_v1.core import AuctionQueue
        self.assertTrue(AuctionQueue(journal=self.f.journal,scope=self.f.registry.scope).draining)
        acquirer.cycle()
        self.assertTrue(self.f.queue.draining)
        self.assertEqual(self.page.bid_calls,0)

    def test_partial_clear_and_changed_survivor_never_claim_complete_clear(self):
        self.page.partial=True
        self.assertEqual(SoldClear(self.f).step()['status'],'UNRESOLVED')
        self.assertEqual(self.count()['occupied'],6)
        self.restart()
        self.page.transfer_items=inventory()[2:]
        self.page.transfer_items[-1]['buy_now_price']+=500
        self.assertEqual(SoldClear(self.f).step()['status'],'RECONCILIATION_ONLY')
        self.assertEqual(len(self.page.writes),1)
        self.assertEqual(self.f.journal.db.execute('SELECT incompatible FROM bulk_writes_v1').fetchone(),(1,))
        self.assertEqual(self.count()['occupied'],6)

    def test_sale_price_balance_deltas_manual_and_actor_cards_do_not_create_realized_profit(self):
        # Even a known cost and matching verified listing do not prove net
        # settled proceeds. A simultaneous manual sale makes a credits delta
        # especially unattributable; observed sale prices may differ from BIN.
        from fc_access.production_v1.resale import install
        install(self.f.journal)
        r=self.page.transfer_items[0]
        acquisition='trade:'+'a'*24
        self.f.journal.db.execute('INSERT INTO resales_v1 VALUES(?,?,?,?,?,?,?)',
            (self.f.registry.scope,acquisition,r['item']['item_id'],r['item']['definition_id'],800,17000,'LISTED'))
        self.f.registry._append(dict(kind='RESALE',reason='VERIFIED',operation='list',new_trade_id=r['trade_id']),acquisition)
        self.page.credits+=29000
        SoldClear(self.f).step()
        observations=self.events('SOLD_SETTLEMENT')
        self.assertEqual(len(observations),2)
        self.assertEqual({e['sale_trade_id'] for e in observations},{r['trade_id'] for r in inventory()[:2]})
        for e in observations:
            self.assertEqual(e['reason'],'ACTUAL_SETTLED_PROCEEDS_UNPROVEN')
            self.assertEqual(e['observed_gross_price'],15000)
            self.assertIsNone(e['actual_settled_proceeds']);self.assertIsNone(e['realized_profit'])
            self.assertEqual(e['trade_id'],e['sale_trade_id'])
        self.restart()
        self.assertEqual(len(self.events('SOLD_SETTLEMENT')),2)
        self.assertFalse([e for e in self.f.registry.events() if e.get('realized_profit') is not None])

    def test_diagnostic_persistence_failure_blocks_native_clear(self):
        original=self.f.registry._append
        def fail(body,trade=None):
            original(body,trade)
            if body['kind']=='SOLD_SETTLEMENT':raise OSError('disk failure')
        with patch.object(self.f.registry,'_append',side_effect=fail):
            with self.assertRaises(OSError):SoldClear(self.f).step()
        self.assertFalse(self.page.writes)
        self.assertFalse(self.events('SOLD_SETTLEMENT'))
        self.assertFalse(pending(self.f.journal,self.f.registry.scope))

    def test_crash_at_all_durable_boundaries_recovery_reads_without_dispatch(self):
        for stage in ('intent','claimed','sent','ack','readback'):
            directory=self.path/stage;directory.mkdir()
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--crash',str(directory),stage],
                cwd=ROOT,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,23,result.stdout+result.stderr)
            page=BulkPage(directory,self.clock)
            page.transfer_items=json.loads((directory/'effect.json').read_text())
            f=Foundation(page,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True,
                now=self.clock.now,clock=self.clock.monotonic,sleep=self.clock.sleep)
            try:
                self.clock.sleep(1)
                self.assertEqual(SoldClear(f).step()['status'],
                    'SKIPPED' if stage=='readback' else 'RECONCILIATION_ONLY')
                self.assertFalse(page.writes)
                self.assertEqual(f.journal.db.execute('SELECT state FROM bulk_writes_v1').fetchone(),
                    ('INTENT',) if stage=='intent' else ('UNKNOWN',) if stage=='claimed' else ('RECONCILED',))
            finally:f.close();page.close()

    def test_real_mailbox_urgent_work_preempts_clear_and_independent_readback(self):
        box=Mailbox(self.path/'native.sqlite3');self.addCleanup(box.close)
        broker=Broker(box,self.f,Config(native_interval_seconds=2),now=self.clock.now,
            clock=self.clock.monotonic,sleep=self.clock.sleep)
        broker.initialize()
        def pump(seconds):broker.run_one();self.clock.sleep(seconds)
        proxy=QueueExecutor(box.path,'maintenance',clock=self.clock.monotonic,sleep=pump)
        self.addCleanup(proxy.close)
        joined=Foundation(proxy,context=CONTEXT,owner=self.f.registry.owner,join_epoch=self.f.registry.epoch,
            journal_path=self.f.journal_path,fixture=True,now=self.clock.now,clock=self.clock.monotonic,sleep=pump)
        self.addCleanup(joined.close)
        def stage(s,where):
            if where in {'claimed','ack'}:
                box.enqueue(joined.adapter.envelope(joined.ids(),'watched',{}),'bidder',now=self.clock.now())
        with patch.object(BulkTransfer,'checkpoint',stage):
            self.assertEqual(SoldClear(joined).step()['status'],'CONFIRMED')
        self.assertEqual([c['operation'] for c in self.page.calls],
            ['transfer_list','watched','clear_sold','watched','transfer_list'])
        self.assertEqual(box.db.execute("SELECT DISTINCT role,priority FROM work ORDER BY priority").fetchall(),
            [('maintenance',0),('bidder',90)])
        rows=box.db.execute('SELECT started,finished FROM work ORDER BY seq').fetchall()
        # Queue insertion order differs from dispatch priority order.
        rows=sorted(rows,key=lambda r:stamp(r[0]))
        self.assertTrue(all((stamp(b[0])-stamp(a[1])).total_seconds()>=1.99 for a,b in zip(rows,rows[1:])))

    def test_two_process_observers_share_one_consumed_intent(self):
        (self.path/'physical.json').write_text(json.dumps(inventory()))
        meta=dict(owner=self.f.registry.owner,epoch=self.f.registry.epoch)
        (self.path/'session.json').write_text(json.dumps(meta))
        workers=[subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--observe',str(self.path),str(i)],
            cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(2)]
        try:
            end=time.monotonic()+15
            while not all((self.path/f'ready-{i}').exists() for i in range(2)) and time.monotonic()<end:
                time.sleep(.01)
            self.assertTrue(all((self.path/f'ready-{i}').exists() for i in range(2)))
            (self.path/'go').touch()
            for worker in workers:
                out,err=worker.communicate(timeout=20)
                self.assertEqual(worker.returncode,0,out+err)
        finally:
            for worker in workers:
                if worker.poll() is None:worker.kill();worker.communicate()
        effects=(self.path/'mutations.jsonl').read_text().splitlines()
        self.assertEqual(len(effects),1)
        self.assertEqual(json.loads(effects[0])['operation'],'clear_sold')
        self.assertEqual(json.loads((self.path/'physical.json').read_text()),inventory()[2:])
        self.assertEqual(self.f.journal.db.execute('SELECT state FROM bulk_writes_v1').fetchall(),[('RECONCILED',)])

    def test_imports_start_nothing_and_native_requires_maintenance_transport(self):
        with patch('socket.socket',side_effect=AssertionError('network forbidden')), \
             patch('threading.Thread.start',side_effect=AssertionError('background forbidden')):
            self.maintenance();SoldClear(self.f)
            self.assertFalse(self.page.calls)
        with patch.object(self.f.adapter,'source','native'):
            with self.assertRaisesRegex(ValueError,'prioritized_maintenance_executor_required'):SoldClear(self.f)
        result=subprocess.run([sys.executable,'-m','fc_access.actors_v1','maintenance','--help'],
            cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--cycles',result.stdout)

    def test_operator_status_export_and_retention_preserve_unknown_bulk_and_sale_evidence(self):
        from fc_access.actors_v1.operator import inspect, retain
        box=Mailbox(self.path/'native.sqlite3');self.addCleanup(box.close)
        Broker(box,self.f,Config(),now=self.clock.now).initialize()
        self.page.effect=False
        result=SoldClear(self.f).step()
        state=inspect(box.path)
        self.assertEqual([p['command_id'] for p in state['unresolved_intents']],[result['command_id']])
        self.assertEqual(state['unresolved_intents'][0]['operation'],'clear_sold')
        trace=inspect(box.path,'export')
        self.assertEqual(len([e for e in trace['registry'] if e['kind']=='SOLD_SETTLEMENT']),4)
        destination=self.path/'backup'
        self.assertEqual(retain(box.path,destination)['pruned_events'],0)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(destination/'journal.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT state FROM bulk_writes_v1').fetchall(),[('ACKNOWLEDGED',)])
            self.assertEqual(db.execute("SELECT count(*) FROM registry_events_v1 WHERE json_extract(body,'$.kind')='SOLD_SETTLEMENT'").fetchone(),(4,))

    def test_actual_bounded_cli_maintenance_automatically_clears_then_relists_through_broker(self):
        directory=self.path/'cli';directory.mkdir()
        broker=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--broker',str(directory)],
            cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            end=time.monotonic()+10
            while not (directory/'ready').exists() and time.monotonic()<end:
                if broker.poll() is not None:break
                time.sleep(.01)
            self.assertTrue((directory/'ready').exists())
            r=subprocess.run([sys.executable,'-m','fc_access.actors_v1','--state-dir',str(directory),
                'maintenance','--cycles','1'],cwd=ROOT,capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertEqual(json.loads(r.stdout),dict(stopped=True,actor='maintenance'))
        finally:
            (directory/'stop').touch()
            try:out,err=broker.communicate(timeout=5)
            except subprocess.TimeoutExpired:broker.kill();out,err=broker.communicate()
        self.assertEqual(broker.returncode,0,out+err)
        calls=json.loads((directory/'calls.json').read_text())
        self.assertEqual([c['operation'] for c in calls],
            ['transfer_list','clear_sold','transfer_list','transfer_list','relist_all','transfer_list'])
        box=Mailbox(directory/'native.sqlite3')
        try:
            self.assertEqual(box.db.execute('SELECT DISTINCT role,priority,state FROM work').fetchall(),[('maintenance',0,'DONE')])
        finally:box.close()


def crash_worker(directory,stage):
    import os
    directory=Path(directory);clock=RealClock();page=BulkPage(directory,clock)
    f=Foundation(page,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True)
    def checkpoint(s,where):
        if where==stage:
            (directory/'effect.json').write_text(json.dumps(page.transfer_items))
            os._exit(23)
    with patch.object(BulkTransfer,'checkpoint',checkpoint):SoldClear(f).step()
    raise AssertionError('crash seam not reached')


def observer_worker(directory,index):
    directory=Path(directory);local=directory/('observer-'+index);local.mkdir()
    clock=RealClock()
    class SharedPage(BulkPage):
        def project_response(self,c,v):
            if c['operation']=='transfer_list':
                self.transfer_items=json.loads((directory/'physical.json').read_text())
            value=super().project_response(c,v)
            if c['operation']=='clear_sold':
                (directory/'physical.json').write_text(json.dumps(self.transfer_items))
                with (directory/'mutations.jsonl').open('a') as handle:handle.write(json.dumps(c)+'\n')
            return value
    page=SharedPage(local,clock)
    page.directory=directory  # Authority checks use the common durable journal.
    page.store.authorize_bid=JournalAuthority(directory/'journal.sqlite3')
    meta=json.loads((directory/'session.json').read_text())
    f=Foundation(page,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True,
        owner=meta['owner'],join_epoch=meta['epoch'])
    try:
        (directory/f'ready-{index}').touch()
        end=time.monotonic()+15
        while not (directory/'go').exists():
            if time.monotonic()>end:raise TimeoutError('observer barrier')
            time.sleep(.01)
        result=SoldClear(f).step()
        assert result['status'] in {'CONFIRMED','SKIPPED'},result
    finally:f.close();page.close()


def broker_worker(directory):
    directory=Path(directory);page=BulkPage(directory,RealClock())
    f=Foundation(page,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True)
    box=Mailbox(directory/'native.sqlite3')
    broker=Broker(box,f,Config(native_interval_seconds=0))
    try:
        broker.initialize();(directory/'ready').touch()
        end=time.monotonic()+30
        while not (directory/'stop').exists() and time.monotonic()<end:
            if broker.run_one() is None:time.sleep(.005)
    finally:
        (directory/'calls.json').write_text(json.dumps(page.calls))
        box.close();f.close();page.close()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--crash':crash_worker(*sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='--observe':observer_worker(*sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='--broker':broker_worker(*sys.argv[2:])
    else:unittest.main(verbosity=2)
