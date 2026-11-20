"""Stored price rules and the seconds-left setting; offline synthetic EA.

Acquisition pricing may answer from a durable store of the page's own tick answers
(no expiry) and card price limits (a day), checked and warmed at startup and
rechecked after a rejected bid. Listing always asks the page. min_seconds_left
replaces the fixed 60 s cutoff."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_policy_fixture import Harness
from controller_work_fixture import harness, won, effects
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller
from fc_access.production_v1.price_store import PriceRuleStore, CAPS_TTL_SECONDS
from fc_access.production_v1.prices import PriceService, CardKey


def configured(h, rules=None, **values):
    h.config = replace(h.config, **values)
    h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids, clock=h.clock.clock,
                              sleep=h.clock.sleep, rules=rules)
    h.controller.resume()
    return h


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def store(self, name='rules.sqlite3'):
        s = PriceRuleStore(self.dir/name); self.addCleanup(s.close)
        return s

    def make(self, count=3, rules=None, **values):
        path = self.dir/f'h{len(list(self.dir.iterdir()))}'; path.mkdir()
        h = Harness(path, count); self.addCleanup(h.close)
        return configured(h, rules=rules, **values)

    def service(self, h, rules, now=lambda: 1000.0, use_rules=True):
        return PriceService(h.controller.native, h.ids, rules=rules, use_rules=use_rules, clock=now)

    def helper_calls(self, h):
        return len(h.calls('price_helpers'))

    def reset_phase(self, h):
        h.controller.journal.checkpoint(phase='ACQUIRING')


class StoreService(Base):
    def test_stored_ticks_answer_without_asking_the_page_and_survive_a_restart(self):
        h = self.make(); rules = self.store()
        first = self.service(h, rules)
        values = [1500, 7685, 12345]
        cap = first.load(key=CardKey(123))
        expected = [cap.floor(v) for v in values]
        self.assertGreater(first.stats['helper_calls'], 0)
        before = self.helper_calls(h)
        second = self.service(h, PriceRuleStore(self.dir/'rules.sqlite3'))  # a new process
        self.addCleanup(second.rules.close)
        again = second.load(key=CardKey(123))
        self.assertEqual([again.floor(v) for v in values], expected)
        self.assertEqual(self.helper_calls(h), before, 'every tick came from the store')
        self.assertEqual(second.stats['helper_calls'], 0)
        self.assertGreater(second.stats['tick_hits'], 0)

    def test_card_limits_are_reused_for_a_day_then_asked_again(self):
        h = self.make(); rules = self.store(); now = [1000.0]
        s = self.service(h, rules, now=lambda: now[0])
        s.load(key=CardKey(123)); calls = len(h.calls('caps'))
        s2 = self.service(h, rules, now=lambda: now[0])
        r = s2.load(key=CardKey(123))
        self.assertEqual((len(h.calls('caps')), r.minimum, r.maximum, s2.stats['caps_hits']), (calls, 150, 20000, 1))
        now[0] += CAPS_TTL_SECONDS
        s2.load(key=CardKey(123))
        self.assertEqual(len(h.calls('caps')), calls+1, 'expired limits are read again')

    def test_without_the_store_mode_a_cap_load_still_resets_tick_answers(self):
        h = self.make(); rules = self.store()
        s = self.service(h, rules, use_rules=False)
        r = s.load(key=CardKey(123)); r.above(750)
        new = s.load(key=CardKey(123))
        before = self.helper_calls(h); new.above(750)
        self.assertEqual(self.helper_calls(h), before+1)
        self.assertEqual(rules.ticks('fc27', 'pc', [('above', 750)]), {('above', 750): 800}, 'native answers are still written')

    def test_store_mode_keeps_tick_answers_across_cap_loads_and_new_page_bindings(self):
        h = self.make(); rules = self.store()
        s = self.service(h, rules)
        s.load(key=CardKey(123)).above(750)
        context, fences, source = s.memo_context
        s.memo_context = (context, dict(fences, epoch=fences['epoch']-1), source)  # answers from an earlier page binding
        before = self.helper_calls(h)
        self.assertEqual(s.load(key=CardKey(456)).above(750), 800)
        self.assertEqual(self.helper_calls(h), before, 'no tick asked again; caps for a new card only')

    def test_recheck_drops_the_stored_ladder_on_any_disagreement(self):
        h = self.make(); rules = self.store()
        s = self.service(h, rules)
        s.helpers([('above', 750), ('below', 1600)])
        self.assertEqual(s.recheck([('above', 750), ('below', 1600)]), 0)
        self.assertEqual(rules.tick_count('fc27', 'pc'), 2)
        rules.put_ticks('fc27', 'pc', {('above', 750): 850}); s.memo.clear()
        self.assertEqual(s.recheck([('above', 750), ('below', 1600)]), 1)
        self.assertEqual(rules.tick_count('fc27', 'pc'), 0)
        self.assertEqual(s.memo, {})

    def test_prepare_checks_then_warms_in_bounded_batches(self):
        h = self.make(); rules = self.store()
        s = self.service(h, rules)
        values = list(range(150, 3001, 50))  # 58 values -> 116 probes
        first = s.prepare(values, max_calls=2)
        self.assertEqual((first['checked'], first['warmed'], first['remaining']), (0, 64, 52))
        self.assertTrue(all(len(c['command']['params']['probes']) <= 32 for c in h.calls('price_helpers')))
        second = s.prepare(values, max_calls=5, check=False)
        self.assertEqual((second['warmed'], second['remaining'], second['stored']), (52, 0, 116))
        # Startup check of a later process: a wrong stored answer drops the ladder.
        rules.put_ticks('fc27', 'pc', {('above', 150): 999})
        fresh = self.service(h, rules)
        third = fresh.prepare(values, max_calls=0)
        self.assertEqual((third['checked'], third['disagreements'] > 0), (8, True))
        self.assertEqual(rules.tick_count('fc27', 'pc'), 0)

    def test_store_mode_requires_a_store(self):
        h = self.make()
        with self.assertRaises(ValueError): PriceService(h.controller.native, h.ids, use_rules=True)
        with self.assertRaises(ValueError): configured(h, stored_price_rules=True)


class ControllerRules(Base):
    def test_rounds_use_the_store_and_record_price_calls(self):
        rules = self.store()
        h = self.make(rules=rules, stored_price_rules=True)
        h.controller.WARM_VALUES = tuple(range(150, 3001, 50))
        h.controller._acquire(); self.reset_phase(h)
        self.assertEqual(len(h.calls('bid')), 3)
        warm = h.metrics('PRICE_RULES')
        self.assertTrue(warm[0]['startup']); self.assertEqual(warm[0]['remaining'], 0)
        first = h.metrics('ACQUISITION')[-1]
        # A later process prices the same cards from the store alone.
        h2 = self.make(rules=PriceRuleStore(self.dir/'rules.sqlite3'), stored_price_rules=True)
        self.addCleanup(h2.controller.rules.close)
        h2.controller.WARM_VALUES = tuple(range(150, 3001, 50))
        h2.controller._acquire()
        second = h2.metrics('ACQUISITION')[-1]
        self.assertEqual(len(h2.calls('bid')), 3)
        self.assertGreater(first['price_calls'], 0)
        self.assertEqual(second['price_calls'], 0, second)
        self.assertGreater(second['tick_hits'], 0); self.assertGreater(second['caps_hits'], 0)
        self.assertEqual(h2.metrics('PRICE_RULES')[0]['disagreements'], 0)

    def test_warm_up_is_spread_over_rounds(self):
        h = self.make(rules=self.store(), stored_price_rules=True)
        h.controller.WARM_CALLS_PER_ROUND = 2
        h.controller.WARM_VALUES = tuple(range(150, 5001, 50))  # 98 values -> 196 probes
        for _ in range(5):
            h.controller._acquire(); self.reset_phase(h)
        rounds = h.metrics('PRICE_RULES')
        self.assertEqual([r['startup'] for r in rounds][:2], [True, False])
        self.assertEqual(rounds[-1]['remaining'], 0)
        self.assertLessEqual(len(rounds), 4, 'no warm-up once complete')

    def test_a_rejected_bid_rechecks_the_ticks_it_used(self):
        h = self.make(rules=self.store(), stored_price_rules=True, denial_pause=0)
        h.controller.WARM_VALUES = ()
        h.ea.bid_modes[h.ea.rows[0]['trade_id']] = 'reject'
        h.controller._acquire()
        checks = h.metrics('PRICE_RULES_RECHECK')
        self.assertEqual([c['target']['trade_id'] for c in checks], [h.ea.rows[0]['trade_id']])
        self.assertEqual(checks[0]['disagreements'], 0)

    def test_without_the_flag_no_store_is_used(self):
        h = self.make()
        self.assertIs(h.controller.market, h.controller.prices)
        h.controller._acquire()
        self.assertEqual(h.metrics('PRICE_RULES'), [])
        self.assertEqual(len(h.calls('bid')), 3)

    def test_listing_always_asks_the_page_even_with_a_wrong_store(self):
        rules = self.store()
        # Every stored answer is wrong: listing must not use them.
        rules.put_ticks('fc27', 'pc', {(d, v): 1 for v in range(150, 40001, 50) for d in ('above', 'below')})
        (self.dir/'work').mkdir(); h = harness(self.dir/'work'); self.addCleanup(h.ea.world.close); self.addCleanup(h.close)
        configured(h, rules=rules, stored_price_rules=True, list_markup=500)
        h.controller.ids = h.controller.prices.command_ids = h.controller.pricing.command_ids = h.ids
        self.assertFalse(h.controller.prices.use_rules)
        won(h)
        for _ in range(2): h.controller.step()
        self.assertEqual(effects(h), [('list', 1), ('move', 1)])
        listing = h.calls('list')[0]['command']['params']
        self.assertLess(listing['starting_bid'], listing['buy_now_price'])


class SecondsLeft(Base):
    def test_auctions_at_or_below_the_setting_are_skipped(self):
        h = self.make(min_seconds_left=300)  # fixture auctions have 300 s left
        h.controller._acquire()
        self.assertEqual(h.calls('bid'), [])
        self.assertEqual(h.metrics('ACQUISITION')[-1]['expiry_misses'], 3)
        h2 = self.make(min_seconds_left=10)
        h2.controller._acquire()
        self.assertEqual(len(h2.calls('bid')), 3)

    def test_default_and_bounds(self):
        self.assertEqual(ControllerConfig().min_seconds_left, 60)
        self.assertFalse(ControllerConfig().stored_price_rules)
        for bad in (dict(min_seconds_left=-1), dict(min_seconds_left=601), dict(min_seconds_left=1.5),
                    dict(stored_price_rules=1)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)

    def test_launch_flags_reach_the_config(self):
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        c = controller_config(lm.parser().parse_args(['launch', '--stored-price-rules', '--min-seconds-left', '10']))
        self.assertEqual((c.stored_price_rules, c.min_seconds_left), (True, 10))
        plain = controller_config(lm.parser().parse_args(['launch']))
        self.assertEqual((plain.stored_price_rules, plain.min_seconds_left), (False, 60))


if __name__ == '__main__': unittest.main(verbosity=2)
