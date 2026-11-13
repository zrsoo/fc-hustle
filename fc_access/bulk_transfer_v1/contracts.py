"""Bulk state/economics contracts; independent of actors and source provenance."""
from fc_access.production_v1.contracts import fields, integer, token, stamp

WRITES = {'bulk_clear_sold', 'bulk_relist_all'}
PATHS = {'bulk_clear_sold': ('DELETE', '/ut/game/fc27/trade/sold'),
         'bulk_relist_all': ('PUT', '/ut/game/fc27/auctionhouse/relist')}
ROW = {'trade_id','item_id','definition_id','starting_bid','current_bid','buy_now_price',
       'expires','trade_state','bid_state','trade_owner'}


def validate_row(r):
    fields(r, ROW); token(r['trade_id'], 'trade'); token(r['item_id'], 'item')
    for k in ('definition_id','starting_bid','current_bid','buy_now_price'):
        integer(r[k],1 if k=='definition_id' else 0)
    integer(r['expires'], -1)
    if r['trade_state'] not in {'closed','expired','active','inactive',None} or r['bid_state'] not in {'none','highest','outbid','buyNow','sold',None}:
        raise ValueError('invalid_native_state')
    if r['trade_owner'] is not None and type(r['trade_owner']) is not bool:
        raise ValueError('invalid_trade_owner')
    return r


def groups(rows):
    for r in rows:
        validate_row(r)
    if len({r['item_id'] for r in rows}) != len(rows) or len({r['trade_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_identity')
    return {
        'sold': [r for r in rows if r['trade_owner'] is True and r['trade_state']=='closed' and r['current_bid']>0 and r['expires']<=0],
        'expired': [r for r in rows if r['trade_owner'] is True and r['trade_state']=='expired' and r['current_bid']==0 and r['expires']<=0],
        'other': [r for r in rows if not (r['trade_owner'] is True and
            (r['trade_state']=='closed' and r['current_bid']>0 and r['expires']<=0 or
             r['trade_state']=='expired' and r['current_bid']==0 and r['expires']<=0))]}


def preflight(operation, rows, *, authorized_sold=2, authorized_expired=1):
    g = groups(rows)
    wanted = (authorized_sold, authorized_expired) if operation=='bulk_clear_sold' else (0, authorized_expired)
    if (len(g['sold']),len(g['expired'])) != wanted:
        raise ValueError('eligible_account_state_exceeds_authorized_scope')
    return g['sold'] if operation=='bulk_clear_sold' else g['expired']


def reconcile(operation, before, after, *, mutation_started, mutation_ended, read_started, read_ended):
    delta = (stamp(read_ended)-stamp(mutation_started)).total_seconds()
    if stamp(read_started)<stamp(mutation_ended) or not 0<=delta<=30:
        raise ValueError('independent_fresh_readback_required')
    old, new = {r['item_id']: r for r in before}, {r['item_id']: r for r in after}
    g = groups(before); groups(after)
    target = g['sold'] if operation=='bulk_clear_sold' else g['expired']
    if not target:
        raise ValueError('no_eligible_targets')
    target_ids = {r['item_id'] for r in target}
    for item_id in old.keys()-target_ids:
        if item_id not in new:
            raise ValueError('unrelated_item_disappeared')
        a,b = old[item_id],new[item_id]
        if any(a[k]!=b[k] for k in ROW-{'expires'}):
            raise ValueError('unrelated_item_modified_or_external_change')
        if b['expires']>a['expires'] or a['expires']<=0 and b['expires']!=a['expires']:
            raise ValueError('unrelated_expiry_modified')
    if operation=='bulk_clear_sold':
        if target_ids & new.keys() or set(new) != set(old)-target_ids:
            raise ValueError('sold_removal_not_confirmed')
        return dict(outcome='CONFIRMED', removed=sorted(target_ids), occupancy_delta=-len(target))
    if set(new)!=set(old):
        raise ValueError('relist_physical_inventory_changed')
    relisted=[]
    for a in target:
        b=new[a['item_id']]
        if b['definition_id']!=a['definition_id'] or b['trade_owner'] is not True:
            raise ValueError('relist_identity_changed')
        if (a['starting_bid'],a['buy_now_price']) != (b['starting_bid'],b['buy_now_price']):
            raise ValueError('relist_prices_changed')
        if b['trade_state']!='active' or b['current_bid']!=0 or not 3600-delta-2<=b['expires']<=3600:
            raise ValueError('native_relist_not_one_hour_at_unchanged_prices')
        relisted.append(dict(item_id=a['item_id'],old_trade_id=a['trade_id'],new_trade_id=b['trade_id'],
                             starting_bid=b['starting_bid'],buy_now_price=b['buy_now_price'],expires=b['expires']))
    return dict(outcome='CONFIRMED',relisted=relisted,occupancy_delta=0,
                duration_contract='server_default_observed_one_hour_not_request_parameter')
