"""Native price service v1 over production protocol 2; no modeled tick table.

Caps bound listings only. Loaded helper outputs are absolute prices. A local
helper result is client legality evidence, never transaction verification.
"""
from dataclasses import dataclass
from copy import deepcopy
from .contracts import integer

SERVICE_VERSION = 1
NATIVE_PATHS = {
    'caps': 'services.Item.transfersDao.getItemMarketDataByDefId',
    'above': 'UTCurrencyInputControl.getIncrementAboveVal',
    'below': 'UTCurrencyInputControl.getIncrementBelowVal',
}


@dataclass(frozen=True)
class CardKey:
    definition_id: int
    platform: str = 'pc'
    game: str = 'fc27'

    def __post_init__(self):
        integer(self.definition_id, 1)
        if (self.platform, self.game) != ('pc', 'fc27'):
            raise ValueError('rules_identity_mismatch')


@dataclass(frozen=True)
class ListingValidation:
    status: str
    reason: str
    buy_now_price: int
    starting_bid: int | None = None


@dataclass(frozen=True)
class NativePrices:
    service: object
    key: CardKey
    minimum: int
    maximum: int
    caps_read_id: str
    source: str
    context: dict
    fences: dict

    @property
    def prices(self):
        return self

    def check(self, key=None):
        a = self.service.adapter
        if self.context != a.context or self.fences != a.fences or self.source != a.source:
            raise ValueError('rules_context_changed')
        if key is not None and (key.definition_id, key.platform, key.game) != (self.key.definition_id, self.key.platform, self.key.game):
            raise ValueError('rules_identity_mismatch')
        if self.service.loaded.get(self.caps_read_id) is not self:
            raise ValueError('unrecognized_caps')
        if self.service.latest.get(self.key) != self.caps_read_id:
            raise ValueError('caps_changed_needs_reconciliation')
        return self

    def above(self, value):
        self.check()
        return self.service.helper('above', value)

    def below(self, value):
        self.check()
        return self.service.helper('below', value)

    def legal(self, value):
        integer(value, 1)
        lower = self.below(value)
        if lower >= value:
            raise ValueError('helper_disagreement')
        return self.above(lower) == value

    def legal_many(self, values):
        """Two dependency rounds, deduplicated and bounded by the wire limit."""
        self.check()
        values = list(dict.fromkeys(integer(v, 1) for v in values))
        lowers = self.service.helpers([('below', v) for v in values])
        if any(lower >= value for value, lower in zip(values, lowers)):
            raise ValueError('helper_disagreement')
        uppers = self.service.helpers([('above', v) for v in lowers])
        return dict(zip(values, (upper == value for value, upper in zip(values, uppers))))

    def floor(self, value):
        """Greatest native tick <= integer value; caps do not constrain bids.

        Native below(x) can round to a tick more than one below an off-grid x.
        Bracket with above(below(x)), then verify reciprocal legality and the
        immediate successor. Never infer an increment or round an economic cap up.
        """
        self.check()
        integer(value)
        if value == 0:
            return None
        lower = self.below(value)
        if lower >= value:
            raise ValueError('helper_disagreement')
        # Off-grid inputs immediately above the lowest tier can yield a
        # nonlegal seed (e.g. below(151)=100). Normalize through the loaded
        # helpers before walking legal successors; zero is only a sentinel.
        for _ in range(8):
            if lower == 0 or self.legal(lower):
                break
            lower = self.below(lower)
        else:
            raise ValueError('helper_disagreement')
        chosen = lower
        # Across a tier transition, below(off_grid) may land two smaller ticks
        # below the floor. Walk a bounded number of native successors, not a
        # guessed delta. Saturation is allowed only at an already legal value.
        for _ in range(8):
            upper = self.above(chosen)
            if upper < chosen or upper == chosen == 0:
                raise ValueError('helper_disagreement')
            if upper > value or upper == chosen:
                break
            chosen = upper
        else:
            raise ValueError('helper_disagreement')
        if chosen == 0:
            return None
        if not self.legal(chosen):
            raise ValueError('helper_disagreement')
        successor = self.above(chosen)
        if successor < chosen or chosen < successor <= value:
            raise ValueError('helper_disagreement')
        return chosen

    def minimum_bid(self, *, definition_id, platform, starting_bid, current_bid):
        self.check(CardKey(definition_id, platform))
        integer(current_bid)
        base = integer(starting_bid, 1) if current_bid == 0 else current_bid
        if not self.legal(base):
            raise ValueError('illegal_starting_bid' if current_bid == 0 else 'unsupported_current_bid')
        if current_bid == 0:
            return base
        value = self.above(current_bid)
        if value == current_bid:  # native global auction maximum saturation
            return None
        if value < current_bid or self.below(value) != current_bid or not self.legal(value):
            raise ValueError('helper_disagreement')
        return value

    def profitable_cap(self, resale_price, profit_threshold):
        integer(resale_price, 1); integer(profit_threshold)
        pair = self.validate_listing(resale_price)
        if pair.status != 'LISTABLE':
            raise ValueError(pair.reason)
        raw = resale_price - resale_price // 20 - profit_threshold
        return self.floor(raw) if raw > 0 else None

    def validate_listing(self, resale_price, *, key=None):
        """Standalone future plan; never adjusts BIN and never submits a listing."""
        integer(resale_price, 1)
        try:
            self.check(key)
            if not self.minimum <= resale_price <= self.maximum:
                return ListingValidation('UNLISTABLE', 'bin_outside_card_limits', resale_price)
            start = self.below(resale_price)
            if start == 0 or start < self.minimum:
                return ListingValidation('UNLISTABLE', 'no_legal_lower_start', resale_price)
            if start >= resale_price or start > self.maximum or not self.legal(start) or self.above(start) != resale_price:
                return ListingValidation('NEEDS_RECONCILIATION', 'helper_disagreement', resale_price)
            return ListingValidation('LISTABLE', 'native_pair_validated', resale_price, start)
        except (ValueError, TimeoutError) as e:
            reason = str(e) if str(e) in {
                'rules_identity_mismatch', 'rules_context_changed', 'unrecognized_caps',
                'helpers_unavailable', 'helper_disagreement', 'service_unavailable',
                'service_timeout', 'persona_unverified', 'caps_changed_needs_reconciliation'} else 'native_price_evidence_unavailable'
            return ListingValidation('NEEDS_RECONCILIATION', reason, resale_price)


class PriceService:
    version = SERVICE_VERSION

    def __init__(self, adapter, command_ids):
        self.adapter, self.command_ids = adapter, command_ids
        self.loaded, self.latest = {}, {}
        self.memo, self.memo_context = {}, None

    def helpers(self, probes):
        probes = list(probes)
        for direction, value in probes:
            if direction not in {'above', 'below'}:
                raise ValueError('invalid_helper_direction')
            integer(value)
        a = self.adapter
        binding = (deepcopy(a.context), deepcopy(a.fences), a.source)
        if binding != self.memo_context:
            self.memo.clear()
            self.memo_context = binding
        missing = list(dict.fromkeys(p for p in probes if p not in self.memo))
        for offset in range(0, len(missing), 32):
            batch = missing[offset:offset+32]
            response = a.price_helpers(self.command_ids(),
                [dict(direction=d, value=v) for d, v in batch])
            if binding != (a.context, a.fences, a.source):
                self.memo.clear()
                raise ValueError('rules_context_changed')
            # Publish only a fully validated successful batch, never failures.
            self.memo.update((p, r['price']) for p, r in zip(batch, response['result']['probes']))
        return [self.memo[p] for p in probes]

    def helper(self, direction, value):
        return self.helpers([(direction, value)])[0]

    def load(self, *, key, now=None):
        key = CardKey(key.definition_id, key.platform, key.game)
        # A fresh cap snapshot is a new native legality context.
        self.memo.clear()
        # Availability is independent of cap authentication and persona validation.
        self.adapter.price_helpers(self.command_ids())
        response = self.adapter.caps(self.command_ids(), key.definition_id)
        caps = response['result']['caps']
        if caps is None or caps['definition_id'] != key.definition_id:
            raise ValueError('rules_identity_mismatch')
        integer(caps['minimum'], 1); integer(caps['maximum'], caps['minimum'])
        rules = NativePrices(self, key, caps['minimum'], caps['maximum'], response['command_id'],
                             self.adapter.source, deepcopy(self.adapter.context), deepcopy(self.adapter.fences))
        self.loaded[rules.caps_read_id] = rules
        self.latest[key] = rules.caps_read_id
        return rules

    def validate(self, rules, *, key, now=None):
        if not isinstance(rules, NativePrices) or rules.service is not self:
            raise ValueError('unrecognized_caps')
        return rules.check(key)

    def validate_future_listing(self, *, key, resale_price):
        """Also returns a typed result when services/caps are unavailable."""
        try:
            return self.load(key=key).validate_listing(resale_price, key=key)
        except (ValueError, TimeoutError):
            integer(resale_price, 1)
            return ListingValidation('NEEDS_RECONCILIATION', 'native_price_evidence_unavailable', resale_price)
