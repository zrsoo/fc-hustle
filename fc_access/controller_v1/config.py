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
    # A 461 wave (rounds whose opening bids are all denied) waits in-process:
    # the acquisition pause doubles per such round, up to this many seconds,
    # and resets on the first accepted opening bid. Managing never pauses.
    denial_pause_max: float = 900.0
    # Maintenance clears lost auctions from the native watch list while fewer
    # than this many slots are free (1 = only when full, the legacy rule). A
    # round can add up to 10 auctions, so 10 keeps rounds from being starved.
    watch_reserve: int = 1
    # Bid our cap (greatest legal tick <= cap, below Buy Now) at once instead of
    # the minimum: one bid per auction; once outbid it is priced out. Wins pay the cap.
    bid_at_cap: bool = False
    # Order bands by measured profit per coin (smoothed win rate / median cap of
    # their settled auctions) instead of a fixed rotation; every explore_every-th
    # round still follows the rotation so every band keeps producing data.
    rank_bands: bool = False
    explore_every: int = 5
    # A band whose remembered cheapest cap exceeds spendable coins is searched
    # again at most this often (its prices may have dropped).
    band_recheck: float = 3600.0
    # Ranking model: hours a bid holds its cap (bid at cap: until outbid or the
    # end) and hours a win holds it until the card sells (live 2026-11-20).
    rank_bid_hours: float = 0.1
    rank_sell_hours: float = 6.0
    # At or below entry_threshold credits: False halts the runtime (legacy);
    # True only holds acquisition while members are managed and wins listed.
    low_credit_hold: bool = False
    # Admit a new auction only if spendable coins cover its cap: free balance minus
    # every live tracked auction's remaining claim (cap - our standing top bid).
    # Launches with this on use entry_threshold 0; the rule replaces the threshold.
    coin_reservation: bool = False
    # Allow acquisition (and maintenance) while auctions are live, in quiet
    # windows: no live auction ends within interleave_window (acquisition) or
    # maintenance_window seconds, and no rebid was needed in the last cycle.
    interleave: bool = False
    interleave_window: float = 180.0
    maintenance_window: float = 60.0
    maintenance_interval: float = 300.0

    def __post_init__(self):
        integer(self.entry_threshold)
        for name in ('low_credit_hold', 'coin_reservation', 'interleave', 'bid_at_cap', 'rank_bands'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('invalid_controller_config')
        for name in ('interleave_window', 'maintenance_window', 'maintenance_interval'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 3600:
                raise ValueError('invalid_controller_config')
        if (not isinstance(self.bands, tuple) or not self.bands or len(self.bands) > 10 or
                any(not isinstance(b, tuple) or len(b) != 2 or any(type(v) is not int or not 0 <= v <= 15000000 for v in b) for b in self.bands)):
            raise ValueError('invalid_controller_config')
        for name in ('max_auction_seconds', 'search_budget', 'denial_retries'):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 1000000:
                raise ValueError('invalid_controller_config')
        if type(self.watch_reserve) is not int or not 1 <= self.watch_reserve <= 50:
            raise ValueError('invalid_controller_config')
        if type(self.explore_every) is not int or not 1 <= self.explore_every <= 100:
            raise ValueError('invalid_controller_config')
        if isinstance(self.band_recheck, bool) or not isinstance(self.band_recheck, (int, float)) or not 60 <= self.band_recheck <= 86400:
            raise ValueError('invalid_controller_config')
        for name in ('rank_bid_hours', 'rank_sell_hours'):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 168:
                raise ValueError('invalid_controller_config')
        if self.denial_retries > 5:
            raise ValueError('invalid_controller_config')
        for name in ('margin', 'list_markup'):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 100000:
                raise ValueError('invalid_controller_config')
        for name in ('request_spacing', 'cycle_target', 'inventory_max_age', 'maintenance_gap', 'throttle_pause', 'denial_pause', 'denial_pause_max'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid_controller_config')
        if (self.cycle_target <= 0 or not 0 < self.inventory_max_age <= 30 or self.maintenance_gap > 3600 or
                self.throttle_pause > 7200 or self.denial_pause > 3600 or self.denial_pause_max > 7200):
            raise ValueError('invalid_controller_config')
