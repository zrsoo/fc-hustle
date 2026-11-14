"""Fresh sold detection through the existing one-shot durable bulk protocol.

Only an explicitly launched maintenance worker polls. There is no import-time
work, per-card delete, retry queue, or inference of settled proceeds from coins.
"""
from fc_access.production_v1.bulk import BulkTransfer, classify
from .native import QueueExecutor


class SoldClear(BulkTransfer):
    def __init__(self, foundation):
        transport = foundation.executor.executor
        if foundation.adapter.source != 'fixture' and (
                not isinstance(transport, QueueExecutor) or transport.role != 'maintenance'):
            raise ValueError('prioritized_maintenance_executor_required')
        super().__init__(foundation)

    def inventory(self):
        v = super().inventory()
        sold = set(classify(v)['sold'])
        if not sold:
            return v
        f = self.f
        # Retain the sold DTO's economics before clearing can remove it. These
        # are sale observations, not receipts: neither currentBid nor a balance
        # delta establishes the actual net credit for this physical card.
        with f.journal.transaction():
            f.registry.check()
            self.event('SOLD_DETECTED', read_id=v['command_id'], item_ids=sorted(sold))
            for row in v['result']['auctions']:
                if row['item']['item_id'] not in sold:
                    continue
                f.registry._append(dict(kind='SOLD_SETTLEMENT', reason='ACTUAL_SETTLED_PROCEEDS_UNPROVEN',
                    epoch=f.registry.epoch, read_id=v['command_id'], item=row['item'],
                    sale_trade_id=row['trade_id'], observed_gross_price=row['current_bid'],
                    actual_settled_proceeds=None, realized_profit=None), row['trade_id'])
        return v

    def step(self):
        # The shared account write lock covers the fresh detection, consumed
        # intent and independent readback. A competing observer must read again;
        # an outstanding write can only reconcile, even after an intent crash.
        return self.execute('clear_sold')
