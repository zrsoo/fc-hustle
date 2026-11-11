"""Deterministic, offline indicative pricing proof. No transport or order execution.

All prices are integer coins. A threshold match is a modeled opportunity, never
an authorization to buy or a promise that a listing will sell.
"""
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from statistics import median


@dataclass(frozen=True)
class MarketKey:
    definition_id: int                 # full card/version, NOT base asset ID
    platform: str
    game: str = "fc27"


@dataclass(frozen=True)
class Observation:
    trade_id: str
    item_id: str
    key: MarketKey
    buy_now_price: int
    observed_at: datetime              # network read time (or conservative lower bound)
    expires: int                       # seconds remaining at observed_at
    active: bool = True
    network_fresh: bool = True


@dataclass(frozen=True)
class Band:
    start: int
    stop: int                          # exclusive
    step: int


# Hypothesized full schedule. Only low-price examples are empirically observed.
# Supplying these rules never upgrades their empirical verification status.
DEFAULT_BANDS = (Band(150, 1000, 50), Band(1000, 10000, 100),
                 Band(10000, 50000, 250), Band(50000, 100000, 500),
                 Band(100000, 15000001, 1000))


@dataclass(frozen=True)
class Rules:
    key: MarketKey
    minimum: int
    maximum: int
    observed_at: datetime
    bands: tuple[Band, ...] = DEFAULT_BANDS


@dataclass(frozen=True)
class Policy:
    min_samples: int = 5
    max_age: int = 120
    min_remaining: int = 30
    rules_max_age: int = 300


@dataclass(frozen=True)
class Estimate:
    status: str
    target_sale_price: int | None
    acquisition_price: int | None
    tax: int | None
    expected_profit: int | None
    X: int
    meets_threshold: bool
    sample_count: int
    rejected: tuple[tuple[str, int], ...]
    assumptions: tuple[str, ...] = ("INDICATIVE_NOT_GUARANTEED", "TAX_ROUNDING_UNVERIFIED",
                                    "FULL_INCREMENT_SCHEDULE_UNVERIFIED", "CALLER_SUPPLIED_CAPS")


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def _date(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _key(value):
    return (isinstance(value, MarketKey) and _int(value.definition_id, 1) and
            isinstance(value.game, str) and value.game == "fc27" and isinstance(value.platform, str) and
            value.platform in {"pc", "ps5", "ps4", "xbox", "xboxone", "xbsx", "switch"})


def validate_rules(rules):
    if (not isinstance(rules, Rules) or not _key(rules.key) or
            not _int(rules.minimum, 1) or not _int(rules.maximum, rules.minimum) or
            not _date(rules.observed_at) or not isinstance(rules.bands, tuple) or not rules.bands):
        raise ValueError("invalid_rules")
    previous = 0
    for band in rules.bands:
        if (not isinstance(band, Band) or not _int(band.start, 1) or not _int(band.stop, band.start+1)
                or not _int(band.step, 1) or band.start < previous):
            raise ValueError("invalid_bands")
        previous = band.stop


def floor_price(price, rules):
    """Greatest legal modeled price <= price, bounded by exact-card caps.

    Return None rather than round UP above a conservative target/minimum.
    Works even if a supplied cap is between increments or bands have gaps.
    """
    validate_rules(rules)
    if not _int(price):
        raise ValueError("invalid_price")
    ceiling = min(price, rules.maximum)
    values = []
    for b in rules.bands:
        high = min(ceiling, b.stop-1)
        if high >= b.start:
            value = b.start + ((high-b.start)//b.step)*b.step
            if value >= rules.minimum:
                values.append(value)
    return max(values) if values else None


def profit(target_sale_price, acquisition_price):
    """target - floor(target * .05) - acquisition, without float rounding."""
    if not _int(target_sale_price, 1) or not _int(acquisition_price, 1):
        raise ValueError("invalid_price")
    return target_sale_price - target_sale_price//20 - acquisition_price


def evaluate(key, observations, acquisition, rules, *, now, X, policy=Policy()):
    """One finite evaluation of an already obtained set of comparable BIN asks.

    A fresh exact candidate must be supplied on every call. Repeated evaluations
    must supply new network observations; this module never refreshes anything.
    Rejected data cannot be replaced by marketAverage, lastSalePrice or bulk quotes.
    """
    if not _key(key) or not _date(now) or not _int(X):
        raise ValueError("invalid_input")
    if not isinstance(policy, Policy) or any(not _int(v, low) for v, low in (
            (policy.min_samples, 5), (policy.max_age, 1), (policy.min_remaining, 1), (policy.rules_max_age, 1))):
        raise ValueError("invalid_policy")
    if not isinstance(observations, (list, tuple)):
        raise ValueError("invalid_observations")
    rejected = {}

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0)+1

    def result(status, count=0, target=None):
        cost = acquisition.buy_now_price if isinstance(acquisition, Observation) and _int(acquisition.buy_now_price, 1) else None
        net = profit(target, cost) if target is not None and cost is not None else None
        return Estimate(status, target, cost, target//20 if target else None, net, X,
                        status == "OK" and net >= X, count, tuple(sorted(rejected.items())))

    if rules is None:
        return result("MISSING_CAPS")
    validate_rules(rules)
    if rules.key != key:
        return result("RULES_MARKET_MISMATCH")
    age = (now-rules.observed_at).total_seconds()
    if not 0 <= age <= policy.rules_max_age:
        return result("STALE_RULES")
    if floor_price(rules.maximum, rules) is None:
        return result("NO_LEGAL_PRICE")

    def invalid(row):
        if (not isinstance(row, Observation) or not isinstance(row.trade_id, str) or not row.trade_id
                or not isinstance(row.item_id, str) or not row.item_id or not _key(row.key)
                or not _date(row.observed_at) or not _int(row.buy_now_price, 1)
                or not _int(row.expires) or type(row.active) is not bool or type(row.network_fresh) is not bool):
            return "invalid"
        if row.key != key:
            return "market_mismatch"
        age = (now-row.observed_at).total_seconds()
        if age < 0:
            return "future"
        if age > policy.max_age:
            return "stale"
        if not row.network_fresh:
            return "cached"
        if not row.active or row.expires-age <= policy.min_remaining:
            return "inactive_or_expiring"
        if not rules.minimum <= row.buy_now_price <= rules.maximum:
            return "outside_caps"
        if floor_price(row.buy_now_price, rules) != row.buy_now_price:
            return "invalid_increment"
        return None

    error = invalid(acquisition)
    if error:
        return result("ACQUISITION_"+error.upper())

    # Reject conflicting identities/prices BEFORE validity filtering so an old or
    # malformed conflicting copy cannot silently become independent evidence.
    trades, items = {}, {}
    for row in observations:
        if isinstance(row, Observation) and isinstance(row.trade_id, str) and isinstance(row.item_id, str):
            trades.setdefault(row.trade_id, []).append(row)
            items.setdefault(row.item_id, set()).add(row.trade_id)
    accepted = []
    for trade, copies in sorted(trades.items()):
        if any(c.trade_id == acquisition.trade_id or c.item_id == acquisition.item_id for c in copies):
            reject("acquisition_excluded")
            continue
        # repr avoids hashing caller-supplied malformed values.
        if len({repr((c.key, c.item_id, c.buy_now_price)) for c in copies}) != 1 or any(len(items[c.item_id]) > 1 for c in copies):
            reject("conflicting_duplicate")
            continue
        valid = []
        for c in copies:
            error = invalid(c)
            if error:
                reject(error)
            else:
                valid.append(c)
        if valid:
            # Repeats do not increase n; freshest snapshot wins. Ties are stable.
            accepted.append(max(valid, key=lambda c: (c.observed_at, c.expires)))
            if len(valid) > 1:
                rejected["duplicate"] = rejected.get("duplicate", 0)+len(valid)-1
    for row in observations:
        if not isinstance(row, Observation) or not isinstance(row.trade_id, str) or not isinstance(row.item_id, str):
            reject("invalid")
    if len(accepted) < policy.min_samples:
        return result("INSUFFICIENT_SAMPLES", len(accepted))
    prices = [c.buy_now_price for c in accepted]
    center = median([Fraction(p) for p in prices])
    mad = median([abs(p-center) for p in prices])
    radius = max(3*mad, center/5)
    robust = sorted(p for p in prices if abs(p-center) <= radius)
    for _ in range(len(prices)-len(robust)):
        reject("outlier")
    if len(robust) < policy.min_samples:
        return result("INSUFFICIENT_AFTER_OUTLIERS", len(robust))
    # Nearest-rank lower quartile, then undercut by one legal price tick.
    reference = robust[(len(robust)-1)//4]
    target = floor_price(reference, rules)
    undercut = floor_price(target-1, rules)
    if undercut is not None:
        target = undercut
    return result("OK", len(robust), target)
