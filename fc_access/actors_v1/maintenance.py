"""Explicit maintenance actor, sharing the low-priority native executor."""
from .actors import Actor
from .relist import BulkRelistScheduler
from .sold import SoldClear


class TransferMaintenance(Actor):
    role = 'maintenance'

    def cycle(self):
        self.f.registry.check()
        try:
            result = SoldClear(self.f).step()
        except ValueError as error:
            if str(error) not in {'complete_native_bulk_inventory_required','unproven_native_bulk_semantics',
                                  'complete_transfer_list_required'}:
                raise
            # An owned, not-yet-listed card cannot authorize a bulk mutation.
            # Keep this tick read-only so the Bidder can finish its resale.
            self.record('MAINTENANCE_INVENTORY_BLOCKED')
            return dict(status='BLOCKED_NATIVE_INVENTORY')
        self.record('SOLD_CLEAR_CHECKED', result=result)
        if result['status'] not in {'CONFIRMED', 'SKIPPED'}:
            return result
        # Sold clearing has its own fresh snapshot, claim and readback. The
        # existing relist deadline survives restarts; uncertain clear outcomes
        # never authorize a relist or another clear in this cycle.
        relist = BulkRelistScheduler(self.f, self.config, sleep=self.sleep).step()
        self.record('RELIST_CHECKED', result=relist)
        return dict(clear=result, relist=relist)
