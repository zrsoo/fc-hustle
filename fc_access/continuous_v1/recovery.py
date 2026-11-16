"""Fresh read-only startup reconciliation. Missing identities keep reservations."""
from fc_access.actors_v1.occupancy import read as read_occupancy
from fc_access.bidding_v1.contracts import Balance, Snapshot, Coverage, State
from fc_access.production_v1.foundation import freshness


def reconcile(f):
    # Every restart obtains new command IDs/native reads in the new fenced epoch.
    watched = f.read('watched')
    funds = f.read('balance')
    balance = Balance(funds['result']['credits'], None, freshness(funds))
    f.registry.credits(balance)
    occupied = read_occupancy(f)
    if occupied['occupied'] is None:
        raise ValueError('fresh_complete_inventory_required')
    from fc_access.production_v1.resale import Resale, pending as resale_pending, verify_win, win_inventory
    from fc_access.production_v1.bulk import BulkTransfer, pending as bulk_pending
    for p in resale_pending(f.journal, f.registry.scope):
        Resale(f).reconcile(p['command_id'])
    for p in bulk_pending(f.journal, f.registry.scope):
        BulkTransfer(f).reconcile(p['command_id'])
    read_ids=[watched['command_id'],funds['command_id'],occupied['read_id']]
    for trade, identity in list(f.queue.identities.items()):
        from fc_access.production_v1.known_status import observe
        try:
            status,source,_=observe(f,identity,watched)
        except (ValueError,TimeoutError):
            raise ValueError('unmapped_commitment_requires_independent_reconciliation') from None
        if source['command_id'] not in read_ids:read_ids.append(source['command_id'])
        if not balance.freshness.fresh(f.now()):
            funds=f.read('balance');read_ids.append(funds['command_id'])
            balance=Balance(funds['result']['credits'],None,freshness(funds));f.registry.credits(balance)
        if status.state == State.PENDING:
            owned = win_inventory(f, status, source)
            status = verify_win(f, status, source, owned)
            f.registry._append(dict(kind='ACTOR', actor='bidder', reason='OWNED_WIN_VERIFIED',
                epoch=f.registry.epoch, paid=status.paid, identity=vars(status.identity),
                owned_read_id=owned['command_id'], win_read_id=source['command_id']), trade)
        for p in f.registry.current()['unresolved']:
            if p['trade_id'] == trade and p.get('operation', 'bid') == 'bid':
                f.journal.reconcile(p['command_id'], scope=f.registry.scope, owner=f.registry.owner,
                                    epoch=f.registry.epoch, status=status, balance=balance)
        f.queue.refresh(Snapshot((status,), freshness(source), Coverage(False,None)),now=f.now(),reset_draining=False)
    if f.registry.current()['unresolved']:
        raise ValueError('unresolved_write_requires_independent_reconciliation')
    return dict(read_ids=read_ids,
                occupied=occupied['occupied'], commitments=len(f.queue.entries))
