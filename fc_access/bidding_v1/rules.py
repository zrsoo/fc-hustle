"""No implicit FC27 increments/caps. Rules must match reviewed artifact bytes."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from fc_access import pricing
from .contracts import integer, instant


@dataclass(frozen=True)
class Provenance:
    path: Path
    sha256: str
    classification: str


@dataclass(frozen=True)
class NativeRules:
    prices: pricing.Rules
    provenance: Provenance


class RulesProvider:
    def __init__(self, reviewed_hashes, *, allow_offline=False, max_age=300):
        self.reviewed_hashes = frozenset(reviewed_hashes)
        self.allow_offline = allow_offline
        self.max_age = integer(max_age, 1)

    def load(self, path, *, key, now):
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in self.reviewed_hashes:
            raise ValueError("unreviewed_rules_artifact")
        doc = json.loads(raw)
        if not isinstance(doc, dict) or set(doc) != {"schema", "classification", "source", "observed_at", "key", "minimum", "maximum", "bands"} or type(doc["schema"]) is not int or doc["schema"] != 1:
            raise ValueError("invalid_rules_artifact")
        allowed = {"LIVE_VERIFIED"} | ({"OFFLINE_VALIDATED", "SOURCE_CONFIRMED_ONLY"} if self.allow_offline else set())
        if doc["classification"] not in allowed or doc["source"] != "native_card_caps_and_increment_schedule":
            raise ValueError("unsupported_rules_provenance")
        rules = pricing.Rules(pricing.MarketKey(**doc["key"]), doc["minimum"], doc["maximum"],
                              datetime.fromisoformat(doc["observed_at"]), tuple(pricing.Band(**b) for b in doc["bands"]))
        pricing.validate_rules(rules)
        if rules.key != key or key.platform != "pc" or not 0 <= (instant(now)-instant(rules.observed_at)).total_seconds() <= self.max_age:
            raise ValueError("stale_or_mismatched_rules")
        # Unsupported gaps, overlaps and caps between ticks cannot authorize bids.
        if rules.bands[0].start > rules.minimum or rules.bands[-1].stop <= rules.maximum or any(
                a.stop != b.start for a, b in zip(rules.bands, rules.bands[1:])):
            raise ValueError("unsupported_increment_coverage")
        if any((b.stop-b.start) % b.step for b in rules.bands[:-1]):
            raise ValueError("unsupported_increment_boundary")
        if any(pricing.floor_price(p, rules) != p for p in (rules.minimum, rules.maximum)):
            raise ValueError("unsupported_cap")
        return NativeRules(rules, Provenance(Path(path), digest, doc["classification"]))

    def validate(self, rules, *, key, now):
        if not isinstance(rules, NativeRules) or self.load(rules.provenance.path, key=key, now=now) != rules:
            raise ValueError("rules_changed")
        return rules.prices


def minimum_bid(status, rules):
    """Opening bid is startingBid; a rebid is the first supported tick above currentBid."""
    prices = rules.prices
    if status.identity.definition_id != prices.key.definition_id or status.identity.platform != prices.key.platform:
        raise ValueError("rules_identity_mismatch")
    if status.current_bid == 0:
        value = status.starting_bid
        if pricing.floor_price(value, prices) != value:
            raise ValueError("illegal_starting_bid")
        return value
    if pricing.floor_price(status.current_bid, prices) != status.current_bid:
        raise ValueError("unsupported_current_bid")
    values = []
    for band in prices.bands:
        low = max(status.current_bid+1, prices.minimum, band.start)
        value = band.start + max(0, (low-band.start+band.step-1)//band.step)*band.step
        if value < band.stop and value <= prices.maximum:
            values.append(value)
    return min(values) if values else None


def estimate_cap(status, observations, rules, provider, *, now, X=500):
    key = pricing.MarketKey(status.identity.definition_id, status.identity.platform)
    prices = provider.validate(rules, key=key, now=now)
    age = (instant(now)-instant(status.freshness.network_at)).total_seconds() if status.freshness.network_at else -1
    observed = status.freshness.network_at or status.freshness.observed_at
    candidate = pricing.Observation(status.identity.trade_id, status.identity.item_id, key,
                                    status.buy_now_price, observed,
                                    max(0, int((status.deadline-observed).total_seconds())),
                                    status.state.value in {"ACTIVE", "OUTBID", "LEADING"},
                                    status.freshness.fresh(now) and age >= 0)
    result = pricing.evaluate(key, observations, candidate, prices, now=now, X=X)
    cap = pricing.floor_price(result.target_sale_price-result.target_sale_price//20-X, prices) if result.status == "OK" else None
    return result, cap
