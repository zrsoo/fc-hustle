"""quote_max_age: a cached market quote sets a bid cap (and the listing price locked
to it) only while younger than the setting; older quotes are priced again.
Offline synthetic EA."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller
from fc_access.production_v1.price_cache import QuoteCache, TTL_SECONDS


def pricing_searches(h):
    return [c for c in h.calls('search') if c['command']['params']['purpose'] == 'pricing']


class QuoteAge(unittest.TestCase):
    def make(self, **values):
        h = Harness(self.enterContext(tempfile.TemporaryDirectory()), 3); self.addCleanup(h.close)
        h.config = replace(h.config, **values)
        h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids,
                                  clock=h.clock.clock, sleep=h.clock.sleep)
        h.controller.resume()
        return h

    def new_auctions(self, h, start):
        h.ea.rows = [auction(123, 15000, n+start) for n in range(3)]
        h.controller.journal.checkpoint(phase='ACQUIRING')

    def test_a_quote_older_than_the_setting_is_priced_again(self):
        h = self.make(quote_max_age=1800)
        h.controller._acquire()
        first = len(pricing_searches(h)); self.assertGreater(first, 0)
        caps = {m['cap'] for m in h.controller.journal.members()}
        # 29 minutes on: the cached quote still sets the cap.
        h.clock.value += 1740; self.new_auctions(h, 50); h.controller._acquire()
        self.assertEqual(len(pricing_searches(h)), first)
        # Past 30 minutes: the card is priced again before any bid.
        h.clock.value += 120; self.new_auctions(h, 80); h.controller._acquire()
        self.assertGreater(len(pricing_searches(h)), first)
        newest = [m for m in h.controller.journal.members() if m['target']['trade_id'].endswith(f'{80:024x}'[-6:])]
        self.assertTrue(newest)
        for m in newest:
            self.assertLess((h.clock.now()-datetime.fromisoformat(m['quote']['evidence']['observed_at'].replace('Z', '+00:00'))).total_seconds(), 1800)
        self.assertEqual({m['cap'] for m in newest}, caps, 'same market, same cap')

    def test_the_default_keeps_a_day(self):
        h = self.make()
        self.assertEqual(h.controller.pricing.cache.ttl, TTL_SECONDS)
        h.controller._acquire(); first = len(pricing_searches(h))
        h.clock.value += 3*3600; self.new_auctions(h, 50); h.controller._acquire()
        self.assertEqual(len(pricing_searches(h)), first)

    def test_cache_ttl_bounds(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))/'q.sqlite'
        for bad in (0, -1, TTL_SECONDS+1, True, '1800'):
            with self.assertRaises(ValueError, msg=bad): QuoteCache(path, ttl=bad)
        c = QuoteCache(path, ttl=1800); self.addCleanup(c.close)
        self.assertEqual(c.ttl, 1800)

    def test_config_and_launch_flag(self):
        self.assertEqual(ControllerConfig().quote_max_age, 86400)
        for bad in (dict(quote_max_age=59), dict(quote_max_age=86401), dict(quote_max_age=1800.0)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        self.assertEqual(controller_config(lm.parser().parse_args(['launch', '--quote-max-age', '1800'])).quote_max_age, 1800)
        self.assertEqual(controller_config(lm.parser().parse_args(['launch'])).quote_max_age, 86400)


if __name__ == '__main__': unittest.main(verbosity=2)
