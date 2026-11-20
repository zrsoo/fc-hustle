"""Configurable relist slot: expired cards are relisted once per relist_interval
instead of once an hour; a shorter interval pulls a later stored slot in, never
earlier than one interval from now. Offline synthetic EA."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_work_fixture import harness, effects
from native_price_fixture import auction
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller
from fc_access.production_v1.contracts import stamp


class RelistInterval(unittest.TestCase):
    def make(self, **values):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        h = harness(tmp.name, 0); self.addCleanup(h.ea.world.close); self.addCleanup(h.close)
        if values:
            h.config = replace(h.config, **values)
            h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids,
                                      clock=h.clock.clock, sleep=h.clock.sleep)
            h.controller.ids = h.controller.prices.command_ids = h.controller.pricing.command_ids = h.ids
            h.controller.resume()
        return h

    def expired(self, h, n=2):
        rows = [auction(123, 15000, k+100) for k in range(n)]
        for r in rows: r.update(trade_state='expired', current_bid=0, expires=-1, bid_state='none', native_is_won=False)
        h.ea.inventory = rows; h.ea.save(); h.controller.work.inventory = h.controller.work.pile()

    def due(self, h):
        return stamp(h.store.db.execute('SELECT next_due FROM c4_maintenance').fetchone()[0])

    def test_expired_cards_are_relisted_every_interval(self):
        h = self.make(relist_interval=300)
        self.assertTrue(290 <= (self.due(h)-h.clock.now()).total_seconds() <= 300)
        self.expired(h)
        to_slot = (self.due(h)-h.clock.now()).total_seconds()
        h.clock.value += to_slot-1; h.controller.work.maintenance()
        self.assertEqual(effects(h), [], 'not before the slot')
        h.clock.value += 1; h.controller.work.maintenance()
        self.assertEqual(effects(h), [('relist_all', 1)])
        self.assertTrue(290 <= (self.due(h)-h.clock.now()).total_seconds() <= 300, 'next slot one interval on')
        # The relisted cards expire again: the next slot, 5 minutes on, relists them.
        for r in h.ea.inventory: r.update(trade_state='expired', expires=-1)
        h.ea.save(); h.controller.work.inventory = h.controller.work.pile()
        h.clock.value += 300; h.controller.work.maintenance()
        self.assertEqual(effects(h), [('relist_all', 2)])

    def test_a_shorter_interval_pulls_a_stored_hourly_slot_in(self):
        h = self.make()  # legacy hourly slot stored
        self.assertEqual((self.due(h)-h.clock.now()).total_seconds(), 3660)
        h.clock.value += 600
        h.config = replace(h.config, relist_interval=300)
        h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids,
                                  clock=h.clock.clock, sleep=h.clock.sleep)
        self.assertEqual((self.due(h)-h.clock.now()).total_seconds(), 300, 'pulled in, not made due at once')

    def test_a_longer_interval_keeps_the_stored_slot(self):
        h = self.make(relist_interval=300)
        before = self.due(h)
        h.config = replace(h.config, relist_interval=3660)
        h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids,
                                  clock=h.clock.clock, sleep=h.clock.sleep)
        self.assertEqual(self.due(h), before)

    def test_default_and_bounds(self):
        self.assertEqual(ControllerConfig().relist_interval, 3660)
        for bad in (dict(relist_interval=59), dict(relist_interval=86401), dict(relist_interval=300.0)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)

    def test_launch_flag_reaches_the_config(self):
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        self.assertEqual(controller_config(lm.parser().parse_args(['launch', '--relist-interval', '300'])).relist_interval, 300)
        self.assertEqual(controller_config(lm.parser().parse_args(['launch'])).relist_interval, 3660)


if __name__ == '__main__': unittest.main(verbosity=2)
