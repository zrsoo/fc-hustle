"""Acquirer-only capacity control. No executor or maintenance gate lives here."""
from fc_access.bidding_v1.capacity import status


def projection(registry):
    events = [e for e in registry.events() if e.get('actor') == 'acquirer' and
        e.get('reason') in {'CAPACITY_PAUSED', 'CAPACITY_RESUMED'}]
    if not events:
        return None
    e = events[-1]
    return dict(capacity_paused=e['reason'] == 'CAPACITY_PAUSED',
        capacity_reason=e['capacity_reason'], at=e['at'], epoch=e['epoch'])


def check(actor, occupancy):
    """Persist the counters, independent coin state and capacity transitions.

    Every check uses current inventory evidence and one durable ledger snapshot.
    The previous pause is explanatory history, never permission to use old reads.
    """
    f, cfg = actor.f, actor.config
    with f.journal.transaction():
        f.registry.check()
        counts = status(f.journal, f.registry.scope, now=f.now())
        reason = None
        if not occupancy['enrollment_allowed']:
            reason = occupancy['reason']
        elif not counts['fresh']:
            reason = 'CAPACITY_UNKNOWN'
        elif counts['unresolved'] >= cfg.max_enrolled_auctions:
            reason = 'QUEUE_FULL'
        elif counts['total'] >= cfg.max_total_pipeline_slots:
            reason = 'PIPELINE_FULL'
        draining = f.journal.db.execute("SELECT reason FROM events WHERE scope=? AND "
            "reason IN ('DRAINING','DRAINED') ORDER BY seq DESC LIMIT 1", (f.registry.scope,)).fetchone()
        draining = bool(draining and draining[0] == 'DRAINING')
        previous = projection(f.registry)
        paused = reason is not None
        details = dict(capacity_reason=reason, capacity=counts, occupancy=occupancy,
            limits=dict(unresolved=cfg.max_enrolled_auctions, total=cfg.max_total_pipeline_slots,
                occupied=cfg.max_transfer_list_occupied),
            draining=draining, effective_reason='DRAINING' if draining else reason,
            action='HOLD' if draining or paused else 'CONTINUE')
        actor.record('CAPACITY_CHECKED', **details)
        if paused and (not previous or not previous['capacity_paused'] or previous['capacity_reason'] != reason):
            actor.record('CAPACITY_PAUSED', **details)
        elif not paused and previous and previous['capacity_paused']:
            actor.record('CAPACITY_RESUMED', **details)
    return reason
