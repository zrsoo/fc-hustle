"""Discovery page stepping: when a page holds no auction with more than
min_seconds_left left (a busy market), the round searches the next page, up to
discovery_pages. Offline synthetic EA."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller


def discoveries(h):
    return [c['command']['params'] for c in h.calls('search') if c['command']['params']['purpose'] == 'discovery']


def rows(n, start, expires):
    out = [auction(123, 15000, k+start) for k in range(n)]
    for r in out: r['expires'] = expires
    return out


class Pages(unittest.TestCase):
    def make(self, pages, **values):
        h = Harness(self.enterContext(tempfile.TemporaryDirectory()), 3); self.addCleanup(h.close)
        h.ea.pages = pages
        h.ea.rows = [r for v in pages.values() for r in v]  # status reads find every row
        h.config = replace(h.config, min_seconds_left=60, **values)
        h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids,
                                  clock=h.clock.clock, sleep=h.clock.sleep)
        h.controller.resume()
        return h

    def test_a_page_in_its_last_seconds_steps_to_the_next(self):
        h = self.make({1: rows(21, 100, 30), 2: rows(3, 200, 300)}, discovery_pages=3)
        h.controller._acquire()
        self.assertEqual([p['page'] for p in discoveries(h)], [1, 2])
        bids = h.calls('bid')
        self.assertEqual(len(bids), 3)
        self.assertTrue(all(b['command']['params']['target']['trade_id'].endswith(f'{k:024x}'[-6:])
                            for b, k in zip(bids, range(200, 203))))
        m = h.metrics('ACQUISITION')[-1]
        self.assertEqual((m['page'], m['pages_skipped']), (2, 1))

    def test_default_searches_page_one_only(self):
        h = self.make({1: rows(21, 100, 30), 2: rows(3, 200, 300)})
        h.controller._acquire()
        self.assertEqual([p['page'] for p in discoveries(h)], [1])
        self.assertEqual(h.calls('bid'), [])
        self.assertEqual(h.metrics('ACQUISITION')[-1]['expiry_misses'], 21)

    def test_a_page_with_time_left_is_used_without_stepping(self):
        page1 = rows(20, 100, 30) + rows(1, 150, 300)
        h = self.make({1: page1, 2: rows(3, 200, 300)}, discovery_pages=3)
        h.controller._acquire()
        self.assertEqual([p['page'] for p in discoveries(h)], [1])
        self.assertEqual(len(h.calls('bid')), 1)

    def test_stepping_stops_at_the_page_limit_and_at_a_short_page(self):
        h = self.make({1: rows(21, 100, 30), 2: rows(21, 200, 30), 3: rows(21, 300, 30), 4: rows(3, 400, 300)},
                      discovery_pages=3)
        h.controller._acquire()
        self.assertEqual([p['page'] for p in discoveries(h)], [1, 2, 3])
        self.assertEqual(h.calls('bid'), [])
        h2 = self.make({1: rows(21, 100, 30), 2: rows(5, 200, 30)}, discovery_pages=5)
        h2.controller._acquire()
        self.assertEqual([p['page'] for p in discoveries(h2)], [1, 2], 'a page under 21 rows is the last')

    def test_config_and_launch_flag(self):
        self.assertEqual(ControllerConfig().discovery_pages, 1)
        for bad in (dict(discovery_pages=0), dict(discovery_pages=11), dict(discovery_pages=2.0)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        self.assertEqual(controller_config(lm.parser().parse_args(['launch', '--discovery-pages', '3'])).discovery_pages, 3)


if __name__ == '__main__': unittest.main(verbosity=2)
