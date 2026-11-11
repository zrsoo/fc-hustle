"""Independent offline estimator checks. Run: python tests/test_market_pricing.py"""
from dataclasses import replace
from datetime import datetime, timedelta
from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.pricing import Band, MarketKey, Observation, Policy, Rules, evaluate, floor_price, profit

FIXTURE = json.loads((ROOT / "tests/fixtures/market-pricing.json").read_text())
NOW = datetime.fromisoformat(FIXTURE["now"])
KEY = MarketKey(**FIXTURE["key"])
RULES = Rules(KEY, *FIXTURE["caps"], NOW)


def quote(price=5000, trade="candidate", item="candidate-item", **kwargs):
    return Observation(trade, item, KEY, price, NOW, 3600, **kwargs)


def rows(prices=(6000, 6100, 6200, 6300, 6400)):
    return [quote(p, f"trade-{i}", f"item-{i}") for i, p in enumerate(prices)]


def calc(observations=None, candidate=None, rules=RULES, **kwargs):
    return evaluate(KEY, rows() if observations is None else observations,
                    quote() if candidate is None else candidate, rules,
                    now=kwargs.pop("now", NOW), X=kwargs.pop("X", 700), **kwargs)


class PricingTests(unittest.TestCase):
    def test_fixture_expected_targets_tax_and_thresholds(self):
        for case in FIXTURE["scenarios"]:
            with self.subTest(case["name"]):
                result = calc(rows(case["prices"]), quote(case["acquisition"]), X=case["X"])
                self.assertEqual(result.status, case.get("status", "OK"))
                if "target" in case:
                    self.assertEqual((result.target_sale_price, result.tax, result.expected_profit, result.meets_threshold),
                                     (case["target"], case["tax"], case["profit"], case["meets"]))
                else:
                    self.assertIsNone(result.target_sale_price)
                    self.assertFalse(result.meets_threshold)

    def test_tax_uses_floor_not_bankers_rounding_or_floating_point(self):
        for target, cost, expected in [(150, 150, -7), (250, 200, 38), (950, 800, 103), (19, 1, 18), (20, 1, 18), (21, 1, 19), (39, 1, 37), (40, 1, 37)]:
            self.assertEqual(profit(target, cost), expected)
        for target in range(1, 2001):
            self.assertEqual(profit(target, 1), target-int(Fraction(target, 20))-1)
        large = 10**25+19
        self.assertEqual(profit(large, 1), large-large//20-1)

    def test_both_sides_of_every_band_and_caps(self):
        for price, expected in FIXTURE["rounding"]:
            self.assertEqual(floor_price(price, RULES), expected)
        cap = replace(RULES, minimum=6010, maximum=6377)
        self.assertEqual(floor_price(10000, cap), 6300)
        self.assertIsNone(floor_price(6099, cap))
        self.assertEqual(calc(rows([6100, 6200, 6300, 6300, 6300]), quote(6100), rules=cap, X=0).target_sale_price, 6100)
        self.assertEqual(calc(rules=replace(RULES, minimum=151, maximum=199)).status, "NO_LEGAL_PRICE")

    def test_variant_platform_game_and_base_id_must_not_be_combined(self):
        for key in (replace(KEY, definition_id=233732), replace(KEY, platform="ps5"), replace(KEY, game="fc26"), replace(KEY, platform="unknown")):
            mixed = rows()[:4]+[replace(rows()[4], key=key)]
            self.assertEqual(calc(mixed).status, "INSUFFICIENT_SAMPLES")
            self.assertTrue(calc(candidate=replace(quote(), key=key)).status.startswith("ACQUISITION_"))
        self.assertEqual(calc(rules=replace(RULES, key=replace(KEY, platform="ps5"))).status, "RULES_MARKET_MISMATCH")

    def test_invalid_observations_cannot_supply_missing_fifth_sample(self):
        invalid = [None, {}, replace(rows()[4], buy_now_price=None), replace(rows()[4], buy_now_price=True),
                   replace(rows()[4], buy_now_price=0), replace(rows()[4], buy_now_price=-1),
                   replace(rows()[4], buy_now_price=6301), replace(rows()[4], buy_now_price=float("nan")),
                   replace(rows()[4], buy_now_price=15001000), replace(rows()[4], trade_id=""),
                   replace(rows()[4], item_id=None), replace(rows()[4], expires=True),
                   replace(rows()[4], active=1), replace(rows()[4], network_fresh=None),
                   replace(rows()[4], key=replace(KEY, platform=[])),
                   replace(rows()[4], observed_at=NOW.replace(tzinfo=None))]
        for bad in invalid:
            with self.subTest(bad=bad):
                result = calc(rows()[:4]+[bad])
                self.assertEqual(result.status, "INSUFFICIENT_SAMPLES")
                self.assertFalse(result.meets_threshold)

    def test_stale_future_cached_expired_closed_and_exact_boundaries(self):
        for changes in ({"observed_at": NOW-timedelta(seconds=121)}, {"observed_at": NOW+timedelta(seconds=1)},
                        {"network_fresh": False}, {"expires": 30}, {"active": False}):
            self.assertEqual(calc(rows()[:4]+[replace(rows()[4], **changes)]).status, "INSUFFICIENT_SAMPLES")
        boundary = replace(rows()[4], observed_at=NOW-timedelta(seconds=120), expires=151)
        self.assertEqual(calc(rows()[:4]+[boundary]).status, "OK")
        self.assertEqual(calc(rules=None).status, "MISSING_CAPS")
        self.assertEqual(calc(rules=replace(RULES, observed_at=NOW-timedelta(seconds=301))).status, "STALE_RULES")
        self.assertEqual(calc(rules=replace(RULES, observed_at=NOW+timedelta(seconds=1))).status, "STALE_RULES")

    def test_revalidate_candidate_price_expiry_and_snapshot(self):
        self.assertTrue(calc().meets_threshold)
        changed = calc(candidate=quote(5100))
        self.assertEqual(changed.expected_profit, 600)
        self.assertFalse(changed.meets_threshold)
        for candidate in (replace(quote(), expires=30), replace(quote(), network_fresh=False),
                          replace(quote(), observed_at=NOW-timedelta(seconds=121))):
            self.assertFalse(calc(candidate=candidate).meets_threshold)
        self.assertFalse(calc(now=NOW+timedelta(seconds=121)).meets_threshold)

    def test_duplicate_pages_and_candidate_cannot_inflate_sample_size(self):
        self.assertEqual(calc([rows()[0]]*30).sample_count, 1)
        self.assertEqual(calc(rows()[:4]+[quote()]).sample_count, 4)
        self.assertEqual(calc(rows()[:4]+[replace(quote(), trade_id="other")]).sample_count, 4)
        self.assertEqual(calc(rows()+rows()).sample_count, 5)
        conflict = rows()+[replace(rows()[4], buy_now_price=6500)]
        self.assertEqual(calc(conflict).status, "INSUFFICIENT_SAMPLES")
        physical = rows()+[replace(rows()[4], trade_id="another-auction")]
        self.assertEqual(calc(physical).status, "INSUFFICIENT_SAMPLES")

    def test_order_invariance_including_conflicting_and_repeated_samples(self):
        base = rows()+[rows()[0], replace(rows()[4], buy_now_price=6500)]
        expected = calc(base)
        for shift in range(len(base)):
            rotated = base[shift:]+base[:shift]
            self.assertEqual(calc(rotated), expected)
            self.assertEqual(calc(list(reversed(rotated))), expected)

    def test_exact_threshold_equality_one_coin_each_side_and_break_even(self):
        for X, expected in [(699, True), (700, True), (701, False)]:
            self.assertEqual(calc(X=X).meets_threshold, expected)
        even = calc(candidate=quote(5700), X=0)
        self.assertEqual(even.expected_profit, 0)
        self.assertTrue(even.meets_threshold)
        self.assertFalse(calc(candidate=quote(5800), X=0).meets_threshold)

    def test_explicit_validation_errors(self):
        for X in (-1, True, 1.0, None):
            with self.assertRaises(ValueError):
                calc(X=X)
        for value in (None, -1, True, 1.5):
            with self.assertRaises(ValueError):
                profit(value, 200)
        for rules in (replace(RULES, minimum=0), replace(RULES, maximum=100),
                      replace(RULES, bands=(Band(150, 1000, 0),)),
                      replace(RULES, bands=(Band(150, 1000, 50), Band(500, 2000, 100)))):
            with self.assertRaises(ValueError):
                calc(rules=rules)
        with self.assertRaises(ValueError):
            calc(policy=Policy(min_samples=4))
        with self.assertRaises(ValueError):
            calc(observations="indicative average")


if __name__ == "__main__":
    unittest.main()
