"""MAINTENANCE phase, capacity-only lost cleanup and post-maintenance bid gap.

Offline: synthetic EA and a fake clock. Each phase owns its writes; after an
actual maintenance write no bid is sent for the configured gap, measured from
the durable work record so a restart cannot shorten it.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.journal import BatchJournal
from fc_access.controller_v1.semantic import SemanticHealth, native_summary

WRITES={'clear_lost','clear_sold','relist_all','move','list'}


def losses(h,count):
    h.ea.manual=[]
    for i in range(count):
        r=auction(123,15000,8000+i);r.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False);h.ea.manual.append(r)


def with_gap(h,gap):
    h.config=replace(h.config,maintenance_gap=gap)
    h.controller=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
    h.controller.resume()


class MaintenancePhaseTests(unittest.TestCase):
    def harness(self,count=10,gap=0):
        path=self.enterContext(tempfile.TemporaryDirectory());h=Harness(path,count);self.addCleanup(h.close)
        if gap:with_gap(h,gap)
        return h

    def test_gap_holds_bids_after_a_maintenance_write_with_read_only_keepalive(self):
        h=self.harness(gap=120);losses(h,50)
        h.controller.step();self.assertEqual(h.controller.status()['phase'],'MAINTENANCE')
        h.controller.step();self.assertEqual(len(h.calls('clear_lost')),1)
        written=h.clock.value;n=len(h.ea.calls)
        while not h.calls('bid'):h.controller.step()
        first_bid=next(c for c in h.ea.calls if c['command']['operation']=='bid')
        held=[c['command']['operation'] for c in h.ea.calls[n:h.ea.calls.index(first_bid)]]
        self.assertGreaterEqual(h.clock.value-written,120,'no bid inside the gap')
        self.assertTrue({'balance'}<=set(held));self.assertFalse(WRITES&set(held),'the gap never writes')
        gaps=[r for r in h.store.db.execute("SELECT kind FROM c4_metrics WHERE kind='MAINTENANCE_GAP'")]
        self.assertGreaterEqual(len(gaps),4,'at most 30s per held step')
        self.assertTrue(all(s<=h.config.request_spacing for s in h.clock.sleeps),'only short supervised slices and pacing')

    def test_noop_maintenance_starts_no_gap(self):
        h=self.harness(count=1,gap=300)
        h.controller.step()  # one bid; the synthetic market then settles it lost
        for row in h.ea.rows:row.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False)
        h.ea.manual=deepcopy(h.ea.rows);h.ea.rows=[auction(123,15000,7777)]
        steps=0;bids=len(h.calls('bid'))
        while len(h.calls('bid'))==bids and steps<8:h.controller.step();steps+=1
        self.assertEqual(h.store.db.execute('SELECT count(*) FROM c4_work').fetchone()[0],0)
        self.assertGreater(len(h.calls('bid')),bids,'no write, so no gap')
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_metrics WHERE kind='MAINTENANCE_GAP'").fetchone()[0],0)

    def test_gap_is_measured_from_the_durable_write_across_restart(self):
        h=self.harness(gap=120);losses(h,50)
        h.controller.step();h.controller.step();self.assertEqual(len(h.calls('clear_lost')),1)
        h.clock.value+=60
        with_gap(h,120)  # new worker/controller, same durable store
        self.assertAlmostEqual(h.controller.gap_remaining(),60,delta=5)
        h.controller.step();self.assertEqual(h.calls('bid'),[])
        h.clock.value+=120;self.assertEqual(h.controller.gap_remaining(),0)

    def test_disabled_gap_and_invalid_config(self):
        h=self.harness();losses(h,50)
        for _ in range(3):h.controller.step()
        self.assertEqual(len(h.calls('clear_lost')),1);self.assertEqual(len(h.calls('bid')),10)
        for bad in (-1,3601,float('nan'),True):
            with self.assertRaises(ValueError):ControllerConfig(maintenance_gap=bad)

    def test_capacity_full_is_neutral_and_unconfirmed_cleanup_stops(self):
        s=SemanticHealth(clock=lambda:0)
        for state in ('READ_FAILED','CAPACITY_FULL','READ_FAILED','CAPACITY_FULL','READ_FAILED'):
            s.observe(dict(kind='batch_result',batch_id='b',state=state,confirmed=0,uncertain=0))
        self.assertEqual(s.check(),'PERSISTENT_ACQUISITION_FAILURE')
        s=SemanticHealth(clock=lambda:0)
        for state in ('CAPACITY_FULL',)*10:s.observe(dict(kind='batch_result',batch_id='b',state=state,confirmed=0,uncertain=0))
        self.assertIsNone(s.check(),'a full list alone is not a fault')
        s=SemanticHealth(clock=lambda:0)
        for state in ('MAINTENANCE_FAILED','CAPACITY_FULL')*3:s.observe(dict(kind='batch_result',batch_id=None,state=state,confirmed=0,uncertain=0))
        self.assertEqual(s.check(),'PERSISTENT_ACQUISITION_FAILURE');self.assertEqual(s.batches,2,'cleanup failures are not batches')

    def test_rebids_and_maintenance_never_interleave(self):
        h=self.harness(count=2);h.controller.step()
        h.ea.rows[0].update(bid_state='outbid',current_bid=200,expires=600);h.ea.manual=deepcopy(h.ea.rows)
        h.ea.inventory=[auction(123,15000,555)];h.ea.inventory[0].update(trade_state='closed',current_bid=15000,expires=-1,bid_state='none',native_is_won=False)
        n=len(h.ea.calls)
        for _ in range(4):h.controller.step()
        ops=[c['command']['operation'] for c in h.ea.calls[n:]]
        self.assertIn('bid',ops);self.assertFalse(WRITES&set(ops),'MANAGING with an active auction never writes maintenance')

    def test_old_schema_migrates_in_place_keeping_the_row(self):
        h=self.harness();store=h.store
        with store.db:
            store.db.execute('DROP TABLE c4_controller')
            store.db.execute("""CREATE TABLE c4_controller(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                phase TEXT NOT NULL CHECK(phase IN ('ACQUIRING','MANAGING')),lifecycle TEXT NOT NULL, reason TEXT, batch_id TEXT)""")
            store.db.execute("INSERT INTO c4_controller VALUES(1,'MANAGING','STOPPED','PERSISTENT_WRITE_FAILURE','b1')")
        with self.assertRaises(sqlite3.IntegrityError):
            with store.db:store.db.execute("UPDATE c4_controller SET phase='MAINTENANCE'")
        j=BatchJournal(store)
        self.assertEqual(j.state(),dict(phase='MANAGING',lifecycle='STOPPED',reason='PERSISTENT_WRITE_FAILURE',batch_id='b1'))
        j.checkpoint(phase='MAINTENANCE');self.assertEqual(j.state()['phase'],'MAINTENANCE')
        with self.assertRaises(sqlite3.IntegrityError):
            with store.db:store.db.execute("UPDATE c4_controller SET phase='BOGUS'")
        BatchJournal(store)  # idempotent

    def test_health_accepts_maintenance_phase(self):
        from fc_access.controller_v1.operational import evaluate
        from fc_access.controller_v1.watchdog import Watchdog
        tick=[100.];w=Watchdog(clock=lambda:tick[0],semantic=SemanticHealth(clock=lambda:tick[0]))
        w.semantic.last_native_success=99.;w.semantic.native_successes=3
        for phase,status in (('MAINTENANCE','healthy'),('BOGUS','repair')):
            latest=dict(stage='LOCAL',tick=100.,phase=phase,lifecycle='RUNNING')
            v=dict(schema=1,task='t',generation='a'*32,supervisor={},child={},state='RUNNING',operational_state=phase,
                   started_mono=0.,published_mono=100.,latest=latest,semantic=w.semantic.snapshot(),reason=None)
            self.assertEqual(evaluate(v,task='t',generation='a'*32,now=100.,owner_held=True,supervisor_alive=True,child_alive=True)['status'],status)


if __name__=='__main__':unittest.main(verbosity=2)
