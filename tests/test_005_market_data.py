"""Market price history: pricing searches and auction results are recorded at no
request cost; while acquisition waits, cards we hold and recently priced cards
are searched within an hourly market budget. Offline synthetic EA."""
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_policy_fixture import Harness
from controller_work_fixture import harness
from native_price_fixture import auction
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.market_data import MarketData, summarize


def pricing(h):
    return [c for c in h.calls('search') if c['command']['params']['purpose'] == 'pricing']


def rebuild(h, market, **values):
    h.config = replace(h.config, **values)
    h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids, clock=h.clock.clock,
                              sleep=h.clock.sleep, market=market)
    h.controller.ids = h.controller.prices.command_ids = h.controller.pricing.command_ids = h.ids
    h.controller.resume()
    return h


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def market(self):
        self.count = getattr(self, 'count', 0)+1
        m = MarketData(self.dir/f'market{self.count}.sqlite3'); self.addCleanup(m.close)
        return m

    def rows(self, m, source=None):
        sql = 'SELECT definition_id,source,min_price,median_price,n FROM samples_v1'
        return list(m.db.execute(sql+(' WHERE source=?' if source else ''), (source,) if source else ()))

    def policy(self, **values):
        (self.dir/'p').mkdir(exist_ok=True)
        h = Harness(self.dir/'p', 3); self.addCleanup(h.close)
        return rebuild(h, self.market(), **values)

    def work(self, held=(123,), **values):
        path = self.dir/f'w{len(list(self.dir.iterdir()))}'; path.mkdir()
        h = harness(path, 0); self.addCleanup(h.ea.world.close); self.addCleanup(h.close)
        rebuild(h, self.market(), **values)
        rows = [auction(d, 15000, k+100) for k, d in enumerate(held)]
        for r in rows: r.update(trade_state='active', current_bid=0, expires=3000, bid_state='none')
        h.ea.inventory = rows; h.ea.save(); h.controller.work.pile()  # a transfer-list read
        return h


class Passive(Base):
    def test_pricing_searches_are_recorded_without_extra_requests(self):
        h = self.policy()
        h.controller._acquire()
        searches = pricing(h)
        self.assertGreater(len(searches), 0)
        quotes = self.rows(h.controller.market_data, 'quote')
        self.assertEqual(len(quotes), len(searches), 'one sample per pricing search, no extra searches')
        self.assertTrue(all(q[0] == 123 and q[2] and q[3] >= q[2] for q in quotes))
        self.assertEqual(len(h.calls('bid')), 3, 'trading is unchanged')

    def test_auction_results_are_recorded(self):
        h = self.policy()
        h.controller._closed(None, dict(target=dict(trade_id='t', item_id='i', definition_id=777), cap=5000),
                             dict(current_bid=5600), 'LOST')
        self.assertEqual(self.rows(h.controller.market_data, 'final'), [(777, 'final', 5600, 5600, 1)])


class IdleCollection(Base):
    def until(self, h, seconds=100):
        return h.clock.clock()+seconds

    def test_off_by_default(self):
        h = self.work()
        before = len(pricing(h))
        h.controller._collect_market(None, self.until(h))
        self.assertEqual(len(pricing(h)), before)

    def test_held_cards_are_searched_then_not_again_until_due(self):
        h = self.work(held=(123, 456), market_budget=50)
        h.controller._collect_market(None, self.until(h))
        held = self.rows(h.controller.market_data, 'held')
        self.assertEqual(sorted(r[0] for r in held), [123, 456])
        n = len(pricing(h))
        h.controller._collect_market(None, self.until(h))
        self.assertEqual(len(pricing(h)), n, 'not due again yet')
        h.clock.value += 901
        h.controller._collect_market(None, self.until(h))
        self.assertEqual(len(pricing(h)), n+2)
        metric = h.metrics('MARKET_DATA')[-1]
        self.assertEqual((metric['held'], metric['held_due']), (2, 2))

    def test_the_hourly_budget_and_the_deadline_bound_searches(self):
        h = self.work(held=(123, 456, 789), market_budget=2)
        h.controller._collect_market(None, self.until(h))
        self.assertEqual(len(self.rows(h.controller.market_data, 'held')), 2)
        h.clock.value += 901
        h.controller._collect_market(None, self.until(h))
        self.assertEqual(len(self.rows(h.controller.market_data, 'held')), 2, 'budget spent for this hour')
        h2 = self.work(held=(123, 456), market_budget=50)
        h2.controller._collect_market(None, h2.clock.clock())  # no time left
        self.assertEqual(self.rows(h2.controller.market_data, 'held'), [])

    def test_recently_priced_cards_form_the_index(self):
        h = self.work(held=(), market_budget=50)
        c = h.adapter.context
        h.cache.db.execute('INSERT INTO completed_quotes_v1 VALUES(?,?,?,?,?,?)',
                           (c['account'], c['game'], c['platform'], 321, h.clock.now().timestamp(), '{}'))
        h.cache.db.commit()
        h.controller._collect_market(None, self.until(h))
        self.assertEqual([r[0] for r in self.rows(h.controller.market_data, 'index')], [321])

    def test_a_throttled_search_pauses_market_and_acquisition_searches(self):
        h = self.work(held=(123, 456), market_budget=50)
        original = h.controller.native.search
        def refused(cid, query): raise ValueError('service_failed')
        h.controller.native.search = refused
        h.controller._collect_market(None, self.until(h))
        h.controller.native.search = original
        self.assertGreater(h.controller.search_hold_until, h.clock.clock())
        self.assertEqual(h.metrics('SEARCH_THROTTLED')[-1]['source'], 'market')
        self.assertEqual(h.metrics('MARKET_DATA')[-1]['error'], 'ValueError:service_failed')

    def test_collection_runs_in_a_hold_but_not_when_searches_are_throttled(self):
        h = self.work(held=(123,), market_budget=50)
        h.controller.denial_hold_until = h.clock.clock()+100
        self.assertTrue(h.controller._acquisition_hold())
        self.assertEqual(len(self.rows(h.controller.market_data, 'held')), 1)
        h2 = self.work(held=(123,), market_budget=50)
        h2.controller.search_hold_until = h2.clock.clock()+100
        self.assertTrue(h2.controller._acquisition_hold())
        self.assertEqual(self.rows(h2.controller.market_data, 'held'), [])


class Summary(Base):
    def test_trend_and_held_premium(self):
        m = self.market(); now = 100000.0
        for d, old, new in ((1, 1000, 900), (2, 2000, 1800), (3, 3000, 3300)):
            m.record(d, now-24*3600, 'index', [old, old])
            m.record(d, now-6*3600, 'index', [old, old])
            m.record(d, now-600, 'held' if d == 1 else 'index', [new, new+100])
        db = sqlite3.connect(self.dir/f'market{self.count}.sqlite3'); self.addCleanup(db.close)
        out = summarize(db, now, {1: [1500]})
        self.assertEqual(out['index_trend_median_price']['24h']['cards'], 3)
        self.assertEqual(out['index_trend_median_price']['24h']['median_change_pct'], -5.0)  # 950/1000, 1900/2000, 3350/3000
        self.assertEqual(out['held'][0]['premium_pct'], 67)  # 1500 vs market 900
        self.assertEqual(out['samples_last_hour'], {'held': 1, 'index': 2})

    def test_config_and_launch_flag(self):
        self.assertEqual(ControllerConfig().market_budget, 0)
        for bad in (dict(market_budget=-1), dict(market_budget=2001), dict(market_held_interval=30),
                    dict(market_index_size=501)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        self.assertEqual(controller_config(lm.parser().parse_args(['launch', '--market-budget', '300'])).market_budget, 300)


if __name__ == '__main__': unittest.main(verbosity=2)
