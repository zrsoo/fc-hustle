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
        # Under a page within +10%: that one search gives the true low and both depths.
        self.assertEqual(self.rows(m, 'SELECT steps,searches,more5,more10 FROM ladder_v1'), [(0, 2, 0, 0)])
        self.assertTrue(h.metrics('COLLECT'))

    def test_a_crowded_card_walks_down_and_counts_its_depth(self):
        h, m = self.make()
        h.ea.offers = [auction(123, 11500+250*(k % 2), 3000+k) for k in range(20)] + [auction(123, 11000, 2999)]
        self.collect(h); self.collect(h)
        # A full page (21) within +10% of the first page's low: walk down (none cheaper),
        # count +5% (11550 -> 11500: 11 listings) and reuse the +10% search.
        lad = self.rows(m, 'SELECT page_low,true_low,steps,n5,more5,n10,more10,searches FROM ladder_v1')
        self.assertEqual(lad, [(11000, 11000, 1, 11, 0, 21, 1, 4)])

    def test_ladder_pages_feed_up_to_ten_follows_each_and_depth_pages_too(self):
        h, m = self.make()
        h.ea.offers = [auction(123, 11500+250*(k % 2), 3000+k) for k in range(20)] + [auction(123, 11000, 2999)]
        self.collect(h); self.collect(h)
        by = dict(self.rows(m, "SELECT source,count(*) FROM followed_v1 WHERE source!='discovery' GROUP BY source"))
        self.assertEqual(by['index'], col.FOLLOW_PER_PAGE, 'ten from the first page')
        self.assertGreater(by.get('depth', 0), 0, 'more from the depth pages, at no extra search')
        self.assertLessEqual(by['index']+by['depth'], 21, 'each listing followed once')
        cheapest = self.rows(m, "SELECT 1 FROM followed_v1 WHERE trade_id=?", f'trade:{2999:024x}')
        self.assertEqual(cheapest, [(1,)], 'the cheapest listing is always among those followed')

    def test_every_card_gets_one_ladder_an_hour_and_no_scans_between(self):
        h, m = self.make()
        self.collect(h); self.collect(h)
        c = h.controller.collector
        self.assertEqual(c.targets(), [])
        h.clock.value += 3700
        self.assertEqual(c.targets(), [(123, 'ladder', 'index')])
        self.assertEqual({s for (s,) in self.rows(m, 'SELECT source FROM samples_v1')}, {'index'})
        self.assertEqual(len(self.rows(m, 'SELECT 1 FROM samples_v1')), 1, 'one page sample, from the ladder')

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

    def test_a_bidding_war_is_followed_until_it_ends(self):
        # Live 2026-11-23: bids near the end kept pushing auctions' end back; after
        # 6 checks they were marked stale and their final price was never seen.
        h, m = self.make()
        self.collect(h); self.collect(h)
        war = h.ea.rows[0]; tid = war['trade_id']
        h.clock.value += 400; self.collect(h); self.collect(h)
        for k in range(16):
            war.update(expires=20, current_bid=1000+100*k, bid_state='outbid')
            h.clock.value += 60; self.collect(h)
        row = self.rows(m, 'SELECT status,checks FROM followed_v1 WHERE trade_id=?', tid)[0]
        self.assertEqual(row[0], 'open'); self.assertGreater(row[1], 6)
        war.update(trade_state='closed', expires=-1, current_bid=2500)
        for _ in range(3): h.clock.value += 60; self.collect(h)
        self.assertEqual(self.rows(m, 'SELECT status,final_bid FROM followed_v1 WHERE trade_id=?', tid), [('sold', 2500)])

    def test_a_failed_batch_is_split_and_unknown_trades_are_lost(self):
        h, m = self.make()
        self.collect(h); self.collect(h)
        h.ea.unmapped = {h.ea.rows[0]['trade_id']}
        h.clock.value += 4000
        for _ in range(6): self.collect(h)
        st = dict(self.rows(m, "SELECT trade_id,status FROM followed_v1 WHERE source='discovery'"))
        self.assertEqual(st[h.ea.rows[0]['trade_id']], 'lost')
        self.assertNotEqual(st[h.ea.rows[1]['trade_id']], 'lost')

    def test_a_new_collector_drops_listings_an_earlier_page_load_followed(self):
        # Live 2026-11-22: after a restart behind a page refresh, status reads of the
        # previous run's listings failed (unknown to the new page) and stopped the bot.
        h, m = self.make()
        self.collect(h); self.collect(h)
        self.assertTrue(self.rows(m, "SELECT 1 FROM followed_v1 WHERE status='open'"))
        col.Collector(h.controller)
        self.assertEqual(self.rows(m, "SELECT count(*) FROM followed_v1 WHERE status='open'"), [(0,)])
        self.assertTrue(self.rows(m, "SELECT 1 FROM followed_v1 WHERE status='lost' AND error='restart'"))

    def test_a_watchdog_stop_is_not_swallowed(self):
        h, m = self.make()
        from fc_access.controller_v1.watchdog import SupervisionLost
        def stop(): raise SupervisionLost('WATCHDOG_STOP')
        h.controller.collector.search = lambda q: stop()
        h.controller.collector.next_discovery = 0
        with self.assertRaises(SupervisionLost):
            h.controller.collector.run(None, h.clock.clock()+20)

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
