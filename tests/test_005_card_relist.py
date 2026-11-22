"""Card-by-card relisting (--card-relist) and the maintenance-only mode
(--relist-only). Offline synthetic EA."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_work_fixture import harness, effects
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1 import work as work_module
from fc_access.production_v1.contracts import ROUTES


class CardRelist(unittest.TestCase):
    def make(self, expired=3, sold=0):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        h = harness(tmp.name, 0); self.addCleanup(h.ea.world.close); self.addCleanup(h.close)
        rows = [auction(123, 15000, n+100) for n in range(sold+expired)]
        for n, r in enumerate(rows):
            r.update(trade_state='closed' if n < sold else 'expired', current_bid=15000 if n < sold else 0,
                     expires=-1, bid_state='none', native_is_won=False)
            r['item']['last_sale_price'] = 9000
        h.ea.inventory = rows; h.ea.save(); h.controller.work.inventory = h.controller.work.pile()
        h.controller.config = replace(h.controller.config, card_relist=True)
        return h

    def due(self, h, seconds=120):
        h.clock.value += seconds; h.ea.save()
        with h.store.db: h.store.db.execute('UPDATE c4_maintenance SET next_due=?', ('2000-01-01T00:00:00+00:00',))

    def work(self, h, table='c4_work'):
        return [(json.loads(b)['operation'], s) for b, s in h.store.db.execute(f'SELECT body,state FROM {table} ORDER BY rowid')]

    def refuse(self, h, status, times=1):
        original = h.ea.shared; left = [times]
        def shared(c, at):
            if c['operation'] == 'list' and left[0] > 0:
                left[0] -= 1
                method, path = ROUTES['list']
                return dict(command_id=c['id'], context=c['context'], fences=c['fences'], operation='list', schema=2,
                    coverage=dict(complete=False, has_more=None),
                    freshness=dict(network_at=None, observed_at=at, read_id=c['id'], request_count=1, source=h.adapter.native.source),
                    result=dict(auctions=None, cache_invalidated=False, caps=None, credits=None, error='service_failed', items=None,
                                status=status, success=False,
                                network=[dict(body_empty=True, host='utas.test.ea.com', method=method, path=path, query={},
                                              session_header_present=True, status=status)]),
                    timing=dict(ea_rtt_ms=90, native_helper_ms=0, native_service_ms=1000))
            return original(c, at)
        h.ea.shared = shared

    def test_each_expired_card_is_listed_again_once_at_its_price(self):
        h = self.make(expired=3)
        prices = {r['item']['item_id']: r['buy_now_price'] for r in h.ea.inventory}
        self.due(h); h.controller.work.maintenance()
        self.assertEqual(effects(h), [('list', 3)], 'one listing per card, no relist all')
        self.assertEqual(self.work(h), [('list', 'CONFIRMED')]*3)
        self.assertEqual([r['trade_state'] for r in h.ea.inventory], ['active']*3)
        self.assertEqual({r['item']['item_id']: r['buy_now_price'] for r in h.ea.inventory}, prices)
        self.assertEqual(len(h.metrics('RELIST_CARD')), 3)
        self.due(h); h.controller.work.maintenance()
        self.assertEqual(effects(h), [('list', 3)], 'active cards are not listed again')

    def test_a_pass_lists_at_most_the_bound(self):
        h = self.make(expired=work_module.RELIST_CARDS_PER_PASS+2)
        self.due(h); h.controller.work.maintenance()
        self.assertEqual(effects(h), [('list', work_module.RELIST_CARDS_PER_PASS)])
        self.due(h); h.controller.work.maintenance()
        self.assertEqual(effects(h), [('list', work_module.RELIST_CARDS_PER_PASS+2)])

    def test_a_refused_card_listing_waits_then_is_retried_once_proven_without_effect(self):
        h = self.make(expired=1)
        self.refuse(h, 521)
        self.due(h); h.controller.work.maintenance()
        self.assertEqual(self.work(h), [('list', 'UNKNOWN')])
        # Too soon after the write: no proof yet, the card waits (no second listing).
        h.clock.value += 5; h.ea.save()
        with h.store.db: h.store.db.execute('UPDATE c4_maintenance SET next_due=?', ('2000-01-01T00:00:00+00:00',))
        h.controller.work.maintenance()
        self.assertEqual(self.work(h), [('list', 'UNKNOWN')])
        self.due(h); h.controller.work.maintenance()
        self.assertEqual([op for op, _ in self.work(h, 'c4_work_rejected')], ['list'])
        self.assertEqual(self.work(h), [('list', 'CONFIRMED')])
        self.assertEqual(h.ea.inventory[0]['trade_state'], 'active')

    def test_cards_without_a_paid_price_are_skipped_and_won_card_listings_never_released(self):
        h = self.make(expired=1)
        h.ea.inventory[0]['item']['last_sale_price'] = 0; h.ea.save()
        self.due(h); h.controller.work.maintenance()
        self.assertEqual(effects(h), [])
        self.assertEqual(h.metrics('RELIST_CARD_SKIPPED')[-1]['reason'], 'NO_PAID_PRICE')

    def test_off_by_default_relist_all_is_used(self):
        h = self.make(expired=2)
        h.controller.config = replace(h.controller.config, card_relist=False)
        self.due(h); h.controller.work.maintenance()
        self.assertEqual(effects(h), [('relist_all', 1)])


class RelistOnly(unittest.TestCase):
    def test_relist_only_never_searches_or_bids_and_maintains(self):
        h = Harness(self.enterContext(tempfile.TemporaryDirectory()), 3); self.addCleanup(h.close)
        h.config = replace(h.config, relist_only=True)
        h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids, clock=h.clock.clock, sleep=h.clock.sleep)
        h.controller.resume()
        for _ in range(12): h.controller.step()
        self.assertEqual(h.calls('search'), []); self.assertEqual(h.calls('bid'), [])
        self.assertIn('RELIST_ONLY', {m['reason'] for m in h.metrics('ACQUISITION_HOLD')})
        self.assertTrue(h.calls('transfer_list'), 'maintenance reads the transfer list')
        self.assertEqual(h.controller._acquisition_blocked(), 'RELIST_ONLY')

    def test_config_and_launch_flags(self):
        self.assertEqual((ControllerConfig().card_relist, ControllerConfig().relist_only), (False, False))
        for bad in (dict(card_relist=1), dict(relist_only='yes')):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        c = controller_config(lm.parser().parse_args(['launch', '--card-relist', '--relist-only']))
        self.assertEqual((c.card_relist, c.relist_only), (True, True))
        c = controller_config(lm.parser().parse_args(['launch']))
        self.assertEqual((c.card_relist, c.relist_only), (False, False))


if __name__ == '__main__': unittest.main(verbosity=2)
