"""Full market data collection (--collect) in the relist-only mode: price ladders,
listing outcomes, discovery without bids and the card universe. Offline synthetic EA."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.market_data import MarketData
from fc_access.controller_v1 import collector as col


class Ticks(unittest.TestCase):
    def test_steps_and_neighbours(self):
        self.assertEqual([col.step(p) for p in (900, 1000, 9900, 10000, 49750, 50000, 99500, 100000)],
                         [50, 100, 100, 250, 250, 500, 500, 1000])
        self.assertEqual([col.below(p) for p in (1000, 1100, 10000, 10250, 50000, 150)], [950, 1000, 9900, 10000, 49750, 150])
        self.assertEqual([col.floor_tick(p) for p in (1049, 10249, 52600)], [1000, 10000, 52500])


class Collect(unittest.TestCase):
    def make(self, **values):
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        h = Harness(path, 3); self.addCleanup(h.close)
        market = MarketData(path/'market.sqlite3'); self.addCleanup(market.close)
        h.config = replace(h.config, relist_only=True, collect=True, **values)
        h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids, clock=h.clock.clock,
                                  sleep=h.clock.sleep, market=market)
        h.controller.ids = h.controller.prices.command_ids = h.controller.pricing.command_ids = h.ids
        h.controller.resume()
        h.ea.offers = [auction(123, p, 2000+k) for k, p in enumerate((14000, 12500, 11750, 13000))]
        return h, market

    def rows(self, m, sql, *a):
        return list(m.db.execute(sql, a))

    def collect(self, h):
        self.assertTrue(h.controller._acquisition_hold())

    def test_discovery_ladder_and_follow_without_bids(self):
        h, m = self.make()
        self.collect(h); self.collect(h)  # relist-only maintains first, then collects
        self.assertEqual(h.calls('bid'), [])
        purposes = [c['command']['params']['purpose'] for c in h.calls('search')]
        self.assertIn('discovery', purposes)
        # Discovery: every auction it shows is followed, and its cards join the universe.
        disc = self.rows(m, "SELECT trade_id,status FROM followed_v1 WHERE source='discovery'")
        self.assertEqual(len(disc), 3); self.assertTrue(all(s == 'open' for _, s in disc))
        self.assertEqual(self.rows(m, 'SELECT definition_id FROM universe_v1'), [(123,)])
        # Ladder: the true cheapest buy-now below the first page's, and the depth above it.
        lad = self.rows(m, 'SELECT page_low,true_low,n5,n10 FROM ladder_v1 WHERE definition_id=123')
        self.assertEqual(len(lad), 1)
        self.assertEqual(lad[0][1], 11750)
        # +5%: max buy-now 12337 -> 12250, only 11750; +10%: 12925 -> 12750, 11750 and 12500.
        self.assertEqual(lad[0][2:], (1, 2))
        self.assertTrue(h.metrics('COLLECT'))

    def test_followed_listings_end_sold_expired_or_missing(self):
        h, m = self.make()
        self.collect(h); self.collect(h)
        # The auctions end: one sold, one expired; the ladder's offers are gone (missing).
        h.ea.rows[0].update(trade_state='closed', current_bid=14000, bid_state='outbid', expires=-1)
        h.ea.rows[1].update(trade_state='expired', expires=-1)
        h.ea.rows[2].update(expires=200)  # still running
        h.clock.value += 4000; h.ea.offers = []
        for _ in range(4): self.collect(h)
        out = dict(self.rows(m, "SELECT trade_id,status FROM followed_v1 WHERE source='discovery'"))
        self.assertEqual(out[h.ea.rows[0]['trade_id']], 'sold')
        self.assertEqual(out[h.ea.rows[1]['trade_id']], 'expired')
        self.assertIn(out[h.ea.rows[2]['trade_id']], ('open', 'sold', 'expired'))
        sold = self.rows(m, "SELECT final_bid FROM followed_v1 WHERE trade_id=?", h.ea.rows[0]['trade_id'])
        self.assertEqual(sold, [(14000,)])
        others = {s for (s,) in self.rows(m, "SELECT status FROM followed_v1 WHERE source!='discovery'")}
        self.assertTrue(others <= {'missing', 'open'})
        self.assertEqual(h.calls('bid'), [])

    def test_a_failed_batch_is_split_and_unknown_trades_are_lost(self):
        h, m = self.make()
        self.collect(h); self.collect(h)
        h.ea.unmapped = {h.ea.rows[0]['trade_id']}
        h.clock.value += 4000
        for _ in range(6): self.collect(h)
        st = dict(self.rows(m, "SELECT trade_id,status FROM followed_v1 WHERE source='discovery'"))
        self.assertEqual(st[h.ea.rows[0]['trade_id']], 'lost')
        self.assertNotEqual(st[h.ea.rows[1]['trade_id']], 'lost')

    def test_a_search_throttle_pauses_searches_but_not_status_reads(self):
        h, m = self.make()
        h.ea.search_throttle = True
        self.collect(h); self.collect(h)
        self.assertGreater(h.controller.search_hold_until, h.clock.clock())
        self.assertEqual(h.metrics('SEARCH_THROTTLED')[-1]['source'], 'collect')

    def test_off_by_default_and_flag(self):
        self.assertFalse(ControllerConfig().collect)
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        self.assertTrue(controller_config(lm.parser().parse_args(['launch', '--collect'])).collect)
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        h = Harness(path, 3); self.addCleanup(h.close)
        self.assertIsNone(h.controller.collector)


if __name__ == '__main__': unittest.main(verbosity=2)
