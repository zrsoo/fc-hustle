"""T5 criteria 0..6: deterministic behavioral tests. No network or account writes."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.pricing import Band, MarketKey, Observation, Rules, floor_price, profit
from experiments.market_discovery.model import stamp
from experiments.market_discovery.opportunity import (
    UNCERTAINTY, external_comparison, normalized, price_candidate, rank_candidates, revalidate, run_flow)
from experiments.market_discovery.t5_pricing import simulated_reader

NOW = stamp('2026-11-12T12:00:00+00:00')
KEY = MarketKey(233731, 'pc')
RULES = Rules(KEY, 150, 15000000, NOW)


def quote(price=5000, trade='candidate', item='candidate-item', **changes):
    return replace(Observation(trade, item, KEY, price, NOW, 180), **changes)


def asks(prices=(6000, 6100, 6200, 6300, 6400)):
    return [quote(p, f'trade-{i}', f'item-{i}') for i, p in enumerate(prices)]


def calc(rows=None, candidate=None, rules=RULES, **kwargs):
    return price_candidate(asks() if rows is None else rows, quote() if candidate is None else candidate,
                           rules, now=kwargs.pop('now', NOW), X=kwargs.pop('X', 100), **kwargs)


class PricingBehaviorTests(unittest.TestCase):
    def test_authoritative_baseline_and_alternative_estimators(self):
        p = calc(asks()+[quote()])
        self.assertEqual(p['estimate']['sample_count'], 5)
        self.assertEqual(dict(p['estimate']['rejected']), {'acquisition_excluded': 1})
        expected = {'lower_quartile': (6100, 795), 'lower_quartile_undercut': (6000, 700),
                    'robust_median': (6200, 890), 'robust_mean': (6200, 890)}
        self.assertEqual({k: (v['target_sale_price'], v['expected_profit']) for k, v in p['estimators'].items()}, expected)
        self.assertEqual(p['selected_estimator'], 'lower_quartile_undercut')
        p = calc(asks((200, 6000, 6100, 6200, 6300, 6400, 1000000)))
        self.assertEqual(p['estimate']['sample_count'], 5)
        self.assertEqual(dict(p['estimate']['rejected'])['outlier'], 2)
        self.assertEqual(p['estimators']['robust_mean']['reference'], {'numerator': 6200, 'denominator': 1})
        p = calc(asks((6000, 6000, 6100, 6200, 6300)))
        self.assertEqual(p['estimators']['robust_mean']['reference'], {'numerator': 6120, 'denominator': 1})
        self.assertEqual(p['estimators']['robust_mean']['target_sale_price'], 6100)

    def test_candidate_auction_and_physical_item_excluded_and_conflicts_rejected(self):
        for extra in ([quote()], [replace(quote(), trade_id='other-trade')], [quote(), quote()]):
            p = calc(asks()+extra)
            self.assertEqual(p['estimate']['sample_count'], 5)
            self.assertEqual(p['estimate']['target_sale_price'], 6000)
        for extra in ([replace(asks()[0], buy_now_price=6500)], [replace(asks()[0], trade_id='second-auction')]):
            p = calc(asks()+extra)
            self.assertEqual(p['estimate']['status'], 'INSUFFICIENT_SAMPLES')
            self.assertFalse(p['estimate']['meets_threshold'])
        self.assertEqual(calc(asks()*5)['estimate']['sample_count'], 5)

    def test_exact_version_game_platform_and_rules_identity(self):
        for key in (replace(KEY, definition_id=123), replace(KEY, platform='ps5'), replace(KEY, game='fc26')):
            p = calc(asks()[:4]+[replace(asks()[4], key=key)])
            self.assertFalse(p['estimate']['meets_threshold'])
            self.assertIn(p['estimate']['status'], ('INSUFFICIENT_SAMPLES',))
            if key.game != 'fc27':
                with self.assertRaises(ValueError): calc(candidate=replace(quote(), key=key))
            else:
                self.assertNotEqual(calc(candidate=replace(quote(), key=key))['estimate']['status'], 'OK')
        self.assertEqual(calc(rules=replace(RULES, key=replace(KEY, platform='ps5')))['estimate']['status'], 'RULES_MARKET_MISMATCH')

    def test_tax_floor_and_only_integer_X_profit_threshold(self):
        for target in range(1, 3000):
            self.assertEqual(profit(target, 1), target-int(Fraction(target, 20))-1)
        self.assertEqual(profit(250, 200), 38)
        self.assertEqual(profit(10**30+19, 1), 10**30+19-(10**30+19)//20-1)
        for X, expected in ((0, True), (100, True), (250, True), (500, True), (699, True),
                            (700, True), (701, False), (1000, False)):
            self.assertEqual(calc(X=X)['estimate']['meets_threshold'], expected)
        # No ROI, portfolio, liquidity or separate profit floor can veto equality.
        self.assertTrue(calc(candidate=quote(5700), X=0)['estimate']['meets_threshold'])
        self.assertFalse(calc(candidate=quote(5800), X=0)['estimate']['meets_threshold'])
        for X in (-1, True, 1.5, None):
            with self.assertRaises(ValueError): calc(X=X)
            read, clock, rules = simulated_reader()
            with self.assertRaises(ValueError): run_flow(read, mode='SIMULATED', rules=rules, clock=clock, X=X)

    def test_caps_increments_minimum_and_transition_boundaries(self):
        cases = [(149, None), (150, 150), (999, 950), (1000, 1000), (1001, 1000),
                 (9999, 9900), (10000, 10000), (10249, 10000), (10250, 10250),
                 (49999, 49750), (50000, 50000), (99999, 99500), (100000, 100000),
                 (15000099, 15000000)]
        for value, expected in cases: self.assertEqual(floor_price(value, RULES), expected)
        self.assertEqual(calc(rules=None)['estimate']['status'], 'MISSING_CAPS')
        self.assertEqual(calc(rules=replace(RULES, bands=()))['estimate']['status'], 'MISSING_INCREMENTS')
        self.assertEqual(calc(rules=replace(RULES, minimum=151, maximum=199))['estimate']['status'], 'NO_LEGAL_PRICE')
        self.assertEqual(calc(asks((150,)*5), quote(150), X=0)['estimate']['target_sale_price'], 150)
        cap = replace(RULES, minimum=6010, maximum=6377)
        p = calc(asks((6100, 6200, 6300, 6300, 6300)), quote(6100), cap, X=0)
        self.assertEqual(p['estimate']['target_sale_price'], 6100)
        gap = replace(RULES, bands=(Band(150, 1000, 50), Band(2000, 3000, 100)))
        self.assertEqual(floor_price(1999, gap), 950)

    def test_stale_cached_future_inputs_and_unknown_liquidity_are_exposed(self):
        for changes in ({'observed_at': NOW-timedelta(seconds=121)}, {'observed_at': NOW+timedelta(seconds=1)},
                        {'network_fresh': False}, {'expires': 60}, {'active': False}):
            p = calc(asks()[:4]+[replace(asks()[4], **changes)])
            self.assertFalse(p['estimate']['meets_threshold'])
            self.assertTrue(p['estimate']['rejected'])
            self.assertFalse(calc(candidate=replace(quote(), **changes))['estimate']['meets_threshold'])
        self.assertEqual(calc(rules=replace(RULES, observed_at=NOW-timedelta(seconds=301)))['estimate']['status'], 'STALE_RULES')
        boundary = replace(asks()[4], observed_at=NOW-timedelta(seconds=120), expires=181)
        self.assertTrue(calc(asks()[:4]+[boundary])['estimate']['meets_threshold'])
        p = calc()
        self.assertTrue(set(('BOUNDED_EXPIRY_ORDERED_SAMPLE', 'FILTER_AND_PRICE_CEILING_BIAS_POSSIBLE',
                             'LIQUIDITY_UNKNOWN', 'SELL_THROUGH_UNMEASURED', 'ASKS_NOT_COMPLETED_SALES')) <= set(p['uncertainty']))
        self.assertTrue(all(v is None for v in p['liquidity'].values()))

    def test_external_references_accept_only_fresh_exact_production_quotes(self):
        q = {'source': 'UNIT_TEST_SYNTHETIC_REFERENCE', 'sandbox': False, 'game': 'fc27', 'platform': 'pc',
             'definition_id': KEY.definition_id, 'mapping_verified': True, 'meaning': 'indicative_ask',
             'price': 6200, 'published_utc': NOW.isoformat()}
        out = external_comparison({'status': 'AVAILABLE', 'quotes': [q]}, KEY, NOW, 6000)
        self.assertEqual(out['usable_references'], 1)
        self.assertEqual(out['reviews'][0]['target_minus_reference'], -200)
        cases = [({'platform': 'ps5'}, 'PLATFORM_MISMATCH'), ({'definition_id': 123}, 'EXACT_VERSION_MISMATCH'),
                 ({'game': 'fc26'}, 'GAME_MISMATCH'), ({'mapping_verified': False}, 'MAPPING_UNVERIFIED'),
                 ({'sandbox': True}, 'SANDBOX_OR_LINEAGE_UNKNOWN'), ({'meaning': 'last_sold'}, 'PRICE_MEANING_UNSUPPORTED'),
                 ({'published_utc': (NOW-timedelta(seconds=601)).isoformat()}, 'STALE_OR_FUTURE_QUOTE'),
                 ({'published_utc': (NOW+timedelta(seconds=1)).isoformat()}, 'STALE_OR_FUTURE_QUOTE'),
                 ({'published_utc': None}, 'MISSING_OR_INVALID_PUBLICATION_TIME'), ({'price': True}, 'INVALID_PRICE')]
        for changes, reason in cases:
            out = external_comparison({'status': 'AVAILABLE', 'quotes': [q | changes]}, KEY, NOW, 6000)
            self.assertEqual(out['usable_references'], 0)
            self.assertIn(reason, out['reviews'][0]['reasons'])
        p = calc(asks()[:4], external={'status': 'AVAILABLE', 'quotes': [q]})
        self.assertEqual(p['estimate']['status'], 'INSUFFICIENT_SAMPLES')


class FlowBehaviorTests(unittest.TestCase):
    def flow(self, change=None, X=100, live_interface=False):
        read, clock, rules = simulated_reader()
        calls = []
        def reader(params):
            r = read(params)
            calls.append(deepcopy(params))
            if len(calls) == 2 and change: change(r, clock)
            if live_interface: r['mode'] = 'LIVE_READ_ONLY'  # synthetic interface test, never live evidence
            return r
        out = run_flow(reader, mode='LIVE_READ_ONLY' if live_interface else 'SIMULATED', rules=rules, clock=clock, X=X)
        return out, calls

    def test_rank_freshness_determinism_and_all_X_scenarios(self):
        read, clock, rules = simulated_reader()
        scan = read({'league': 13, 'max_buy': 7000, 'page': 1, 'count': 21, 'fresh': True})
        ranked = rank_candidates([scan], rules, now=stamp(clock.utc()), X=100)
        self.assertEqual([r['pricing']['estimate']['expected_profit'] for r in ranked[:2]], [1300, 700])
        self.assertEqual(sum(r['eligible'] for r in ranked), 2)
        self.assertEqual(ranked[0]['freshness']['age_upper_bound_seconds'], .05)
        self.assertAlmostEqual(ranked[0]['freshness']['remaining_expiry_lower_bound_seconds'], 179.95)
        other = deepcopy(scan); other['result']['auctions'].reverse()
        self.assertEqual(rank_candidates([other], rules, now=stamp(clock.utc()), X=100), ranked)
        for field in ('buy_now_price', 'expires'):
            bad = deepcopy(scan); bad['result']['auctions'][0][field] = None
            # A nullable native field must fail closed, not crash the ranker.
            result = rank_candidates([bad], rules, now=stamp(clock.utc()), X=100)
            row = next(r for r in result if r['candidate']['trade_id'] == bad['result']['auctions'][0]['trade_id'])
            self.assertFalse(row['eligible'])
        bad = deepcopy(scan); bad['result']['auctions'].append(deepcopy(bad['result']['auctions'][6]))
        bad['result']['auctions'][-1]['buy_now_price'] = 2600
        ranked = rank_candidates([bad], rules, now=stamp(clock.utc()), X=100)
        self.assertTrue(next(r for r in ranked if r['candidate']['key']['definition_id'] == 278230 and r['candidate']['buy_now_price'] == 2500)['identity_conflict'])

    def test_full_state_machine_uses_fresh_price_and_proposes_same_physical_listing(self):
        out, calls = self.flow()
        self.assertEqual(out['status'], 'INTENTS_PREPARED')
        self.assertEqual([e['state'] for e in out['events']], ['SCAN', 'PRICE', 'EVALUATE', 'REVALIDATE_READ_ONLY',
                          'REPRICE_AND_EVALUATE', 'DRY_RUN_BUY_INTENT', 'PROPOSED_LISTING_INTENT'])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1]['fresh'])
        self.assertEqual(calls[1]['definition_id'], 278230)
        b, listing = out['buy_intent'], out['listing_intent']
        self.assertEqual((b['buy_now_price'], b['target_sale_price'], b['tax'], b['expected_profit']), (2500, 4000, 200, 1300))
        self.assertEqual((b['mode'], b['lineage'], listing['mode']), ('DRY_RUN_ONLY', 'SIMULATED', 'PROPOSED_ONLY'))
        self.assertEqual((b['key'], b['item_id']), (listing['key'], listing['item_id']))
        self.assertEqual(listing['buy_now_price'], out['final_pricing']['estimate']['target_sale_price'])
        self.assertIn('CONFIRMED_PURCHASE', listing['precondition'])
        self.assertEqual(out['account_mutations'], 0)
        self.assertEqual(out['metrics']['discovery']['eligible_by_X'], {'100': 2, '250': 2, '500': 2, '1000': 1})
        self.assertEqual(out['metrics']['revalidation'], {'attempts': 1, 'passed': 1})
        live, _ = self.flow(live_interface=True)
        self.assertEqual(live['buy_intent']['expected_profit'], b['expected_profit'])
        self.assertEqual(live['buy_intent']['lineage'], 'LIVE_READ_ONLY')

    def test_fresh_revalidation_failures_never_prepare_either_intent(self):
        def row_change(field, value):
            return lambda r, c: r['result']['auctions'][0].update({field: value})
        cases = [
            (row_change('buy_now_price', 2600), 'BIN_CHANGED'),
            (row_change('expires', 60), 'INACTIVE_OR_EXPIRING'),
            (row_change('trade_state', 'closed'), 'INACTIVE_OR_EXPIRING'),
            (row_change('expires', None), 'INACTIVE_OR_EXPIRING'),
            (row_change('trade_id', 'trade:'+'a'*24), 'IDENTITY_CHANGED'),
            (lambda r, c: r['result']['auctions'][0]['item'].update(item_id='item:'+'a'*24), 'IDENTITY_CHANGED'),
            (lambda r, c: r['result']['auctions'][0]['item'].update(definition_id=123), 'IDENTITY_CHANGED'),
            (lambda r, c: r['result']['auctions'].pop(0), 'NOT_OBSERVED_IN_BOUNDED_PAGE'),
            (lambda r, c: r['criteria'].update(fresh=False), 'FRESH_RESET_NOT_REQUESTED'),
            (lambda r, c: c.sleep(31), 'STALE_OR_FUTURE_READ'),
            (lambda r, c: r.update(submitted_utc=NOW.isoformat()), 'READ_NOT_AFTER_SCAN'),
            (lambda r, c: r.update(platform='ps5'), 'MARKET_OR_SCHEMA_MISMATCH'),
            (lambda r, c: (r['result'].update(network=[]), r.update(network_fresh=False)), 'NO_FRESH_NETWORK_GET'),
            (lambda r, c: (r['result'].update(success=False, status=401, auctions=None, error='service_failed'),
                           r['result']['network'][0].update(status=401), r.update(network_fresh=False)), 'READ_FAILED'),
        ]
        for change, reason in cases:
            with self.subTest(reason=reason):
                out, calls = self.flow(change)
                self.assertEqual(len(calls), 2)
                self.assertIsNone(out['buy_intent']); self.assertIsNone(out['listing_intent'])
                self.assertEqual(out['status'], 'REVALIDATION_FAILED')
                self.assertIn(reason, out['revalidation']['reasons'])
                self.assertIsNone(out['metrics']['search_to_prepared_intent_ms'])

    def test_reprice_threshold_failure_and_missing_comparables_stop_intents(self):
        for kind in ('lower_asks', 'thin'):
            def change(r, c):
                if kind == 'thin': r['result']['auctions'].pop()
                else:
                    for row in r['result']['auctions'][1:]: row['buy_now_price'] = 2600
            out, calls = self.flow(change, X=1000)
            self.assertEqual(out['revalidation']['status'], 'PASSED')
            self.assertEqual(out['status'], 'REPRICE_REJECTED')
            self.assertFalse(out['final_pricing']['estimate']['meets_threshold'])
            self.assertIsNone(out['buy_intent']); self.assertIsNone(out['listing_intent'])
        out, calls = self.flow(X=1301)
        self.assertEqual(out['status'], 'NO_QUALIFYING_CANDIDATE')
        self.assertEqual(len(calls), 1)

    def test_missing_or_stale_rules_never_prepare_intent_in_either_stage(self):
        for kind in ('missing', 'increments', 'stale'):
            read, clock, rules = simulated_reader()
            rules = {k: None if kind == 'missing' else replace(r, bands=()) if kind == 'increments'
                     else replace(r, observed_at=NOW-timedelta(seconds=301)) for k, r in rules.items()}
            out = run_flow(read, mode='SIMULATED', rules=rules, clock=clock)
            self.assertEqual(out['status'], 'NO_QUALIFYING_CANDIDATE')
            self.assertIsNone(out['buy_intent']); self.assertIsNone(out['listing_intent'])
            self.assertEqual(len(out['records']), 1)
        read, clock, rules = simulated_reader()
        calls = []
        def reader(params):
            r = read(params); calls.append(params)
            if len(calls) == 2:
                for k in rules: rules[k] = replace(rules[k], observed_at=NOW-timedelta(seconds=301))
            return r
        out = run_flow(reader, mode='SIMULATED', rules=rules, clock=clock)
        self.assertEqual(out['revalidation']['status'], 'PASSED')
        self.assertEqual(out['final_pricing']['estimate']['status'], 'STALE_RULES')
        self.assertEqual(out['status'], 'REPRICE_REJECTED')
        self.assertIsNone(out['buy_intent']); self.assertIsNone(out['listing_intent'])


if __name__ == '__main__': unittest.main()
