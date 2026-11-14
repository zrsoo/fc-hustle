"""Explicit maintenance actor, sharing the low-priority native executor."""
from .actors import Actor
from .relist import BulkRelistScheduler
from .sold import SoldClear


class TransferMaintenance(Actor):
    role = 'maintenance'

    def cycle(self):
        self.f.registry.check()
        result = SoldClear(self.f).step()
        self.record('SOLD_CLEAR_CHECKED', result=result)
        if result['status'] not in {'CONFIRMED', 'SKIPPED'}:
            return result
        # Sold clearing has its own fresh snapshot, claim and readback. The
        # existing relist deadline survives restarts; uncertain clear outcomes
        # never authorize a relist or another clear in this cycle.
        relist = BulkRelistScheduler(self.f, self.config, sleep=self.sleep).step()
        self.record('RELIST_CHECKED', result=relist)
        return dict(clear=result, relist=relist)
