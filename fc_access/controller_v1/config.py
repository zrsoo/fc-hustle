"""Controller policy. Construction and import perform no account operations."""
from dataclasses import dataclass
import math
from fc_access.production_v1.contracts import integer


@dataclass(frozen=True)
class ControllerConfig:
    entry_threshold: int = 40000
    request_spacing: float = 2.0
    cycle_target: float = 5.0
    inventory_max_age: float = 30.0
    # Seconds without any bid after the last dispatched maintenance write
    # (clear_lost/clear_sold/relist_all/move/list). 0 disables the gap.
    maintenance_gap: float = 0.0
    # Profit margin X in the bid cap: resale - 5% tax - X (production pricing).
    margin: int = 500
    # Won items are listed at the greatest legal tick <= resale + list_markup
    # (bounded by the card's native price limits). 0 lists at the resale price.
    list_markup: int = 0
    # Discovery bands (max_bid, min_buy), rotated one per acquisition batch.
    bands: tuple = ((1000, 11000),)
    # Skip new bids on auctions with more seconds left than this (0 = no limit).
    max_auction_seconds: int = 0
    # Soft cap on transfer-market searches per rolling hour (0 = no cap).
    search_budget: int = 0
    # Seconds without acquisition after EA refuses a search (HTTP 429 throttle).
    throttle_pause: float = 900.0
    # A 461-denied initial bid placed nothing; the auction may be tried again
    # this many more times in later batches.
    denial_retries: int = 2
    # When the first two initial bids of a batch are both denied, the rest of
    # the batch is skipped and acquisition pauses this many seconds.
    denial_pause: float = 120.0
    # At or below entry_threshold credits: False halts the runtime (legacy);
    # True only holds acquisition while members are managed and wins listed.
    low_credit_hold: bool = False

    def __post_init__(self):
        integer(self.entry_threshold)
        if type(self.low_credit_hold) is not bool:
            raise ValueError('invalid_controller_config')
        if (not isinstance(self.bands, tuple) or not self.bands or len(self.bands) > 10 or
                any(not isinstance(b, tuple) or len(b) != 2 or any(type(v) is not int or not 0 <= v <= 15000000 for v in b) for b in self.bands)):
            raise ValueError('invalid_controller_config')
        for name in ('max_auction_seconds', 'search_budget', 'denial_retries'):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 1000000:
                raise ValueError('invalid_controller_config')
        if self.denial_retries > 5:
            raise ValueError('invalid_controller_config')
        for name in ('margin', 'list_markup'):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 100000:
                raise ValueError('invalid_controller_config')
        for name in ('request_spacing', 'cycle_target', 'inventory_max_age', 'maintenance_gap', 'throttle_pause', 'denial_pause'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid_controller_config')
        if (self.cycle_target <= 0 or not 0 < self.inventory_max_age <= 30 or self.maintenance_gap > 3600 or
                self.throttle_pause > 7200 or self.denial_pause > 3600):
            raise ValueError('invalid_controller_config')
