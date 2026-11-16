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

    def __post_init__(self):
        integer(self.entry_threshold)
        for name in ('request_spacing', 'cycle_target', 'inventory_max_age'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid_controller_config')
        if self.cycle_target <= 0 or not 0 < self.inventory_max_age <= 30:
            raise ValueError('invalid_controller_config')
