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

    def __post_init__(self):
        integer(self.entry_threshold)
        for name in ('margin', 'list_markup'):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 100000:
                raise ValueError('invalid_controller_config')
        for name in ('request_spacing', 'cycle_target', 'inventory_max_age', 'maintenance_gap'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid_controller_config')
        if self.cycle_target <= 0 or not 0 < self.inventory_max_age <= 30 or self.maintenance_gap > 3600:
            raise ValueError('invalid_controller_config')
