from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class Config:
    search_interval_seconds: float = 600
    target_check_interval_seconds: float = 25
    max_search_bid: int = 1000
    min_search_buy_now: int = 11000
    min_available_coins: int = 5000
    max_enrolled_auctions: int = 50
    max_transfer_list_occupied: int = 50
    max_total_pipeline_slots: int = 50
    min_profit_coins: int = 500
    discovery_max_pages: int = 3
    native_interval_seconds: float = 2
    command_timeout_seconds: float = 30
    bulk_relist_interval_seconds: int = 3660
    bulk_relist_preserve_prices: bool = True
    bulk_relist_duration_seconds: int = 3600
    # Pricing strategy is the existing 001D implementation, not another estimator.
    estimated_sale_tax_rate: float = .05
    pricing_method: str = 'two_search_minimum_valid_bin'
    comparable_page_size: int = 21
    comparable_extra_searches: int = 1
    price_cache_ttl_seconds: int = 86400
    rebid_only_when_outbid: bool = True
    bid_smallest_legal_increment: bool = True

    def __post_init__(self):
        for key in ('search_interval_seconds', 'target_check_interval_seconds',
                    'native_interval_seconds', 'command_timeout_seconds'):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (key != 'native_interval_seconds' and value == 0):
                raise ValueError('invalid_interval')
        for key in ('max_search_bid', 'min_search_buy_now', 'min_available_coins', 'min_profit_coins'):
            if type(getattr(self, key)) is not int or not 0 <= getattr(self, key) <= 2**53-1:
                raise ValueError('invalid_setting')
        if type(self.max_enrolled_auctions) is not int or not 1 <= self.max_enrolled_auctions <= 50:
            raise ValueError('invalid_queue_limit')
        if type(self.max_transfer_list_occupied) is not int or not 1 <= self.max_transfer_list_occupied <= 50:
            raise ValueError('invalid_occupied_limit')
        if type(self.max_total_pipeline_slots) is not int or not 1 <= self.max_total_pipeline_slots <= 50:
            raise ValueError('invalid_pipeline_limit')
        if type(self.discovery_max_pages) is not int or not 1 <= self.discovery_max_pages <= 10:
            raise ValueError('invalid_page_limit')
        locked = dict(estimated_sale_tax_rate=.05, pricing_method='two_search_minimum_valid_bin',
            bulk_relist_interval_seconds=3660, bulk_relist_preserve_prices=True,
            bulk_relist_duration_seconds=3600,
            comparable_page_size=21, comparable_extra_searches=1, price_cache_ttl_seconds=86400,
            rebid_only_when_outbid=True, bid_smallest_legal_increment=True)
        if any(type(getattr(self, k)) is not type(v) or getattr(self, k) != v for k, v in locked.items()):
            raise ValueError('unsupported_strategy')

    def export(self):
        return asdict(self)

