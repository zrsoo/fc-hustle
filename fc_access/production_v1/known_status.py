"""Bounded read-only recovery of a retained exact auction, never write authority.

An omitted lite version is interpreted using the scoped journal identity. The
captured response is never edited, and an omission is never a terminal outcome.
The browser must possess the native selector in the current complete fence.
"""
from copy import deepcopy

from .foundation import status_from
from .inventory import KnownTrade, compare_lite_identity


def exact_row(response, identity):
    rows=[r for r in response['result']['auctions'] if r['trade_id']==identity.trade_id]
    if len(rows)!=1:raise ValueError('exact_status_row_required')
    row=rows[0]
    known=KnownTrade(identity.trade_id,identity.item_id,identity.definition_id)
    outcome=compare_lite_identity(known,dict(trade_id=row['trade_id'],item_id=row['item']['item_id'],
                                         definition_id=row['item']['definition_id']))
    if outcome not in {'MATCH','MATCH_RETAINED_VERSION_UNOBSERVED'}:
        raise ValueError('exact_status_identity_mismatch')
    if outcome!='MATCH' and response['operation']!='status':
        raise ValueError('full_identity_required')
    projected=deepcopy(row)
    projected['item']['definition_id']=identity.definition_id
    return projected


def observe(f, identity, watched):
    from .resale import fresh_read
    fresh_read(f,watched,'watched')
    matches=[r for r in watched['result']['auctions'] if r['trade_id']==identity.trade_id]
    if matches:
        row=exact_row(watched,identity)
        return status_from(row,watched),watched,row
    # Exactly one serialized, paced read. No retry/probe/bid/ID reconstruction.
    response=f.adapter.known_status(f.ids(),trade_id=identity.trade_id,item_id=identity.item_id,
                                    definition_id=identity.definition_id)
    fresh_read(f,response,'status')
    row=exact_row(response,identity)
    f.registry._append(dict(kind='EXACT_STATUS',reason='EXACT_STATUS_RECOVERED',epoch=f.registry.epoch,
        identity=vars(identity),watched_read_id=watched['command_id'],read_id=response['command_id'],
        native_version_observed=response['result']['auctions'][0]['item']['definition_id'] not in {None,0},
        source=response['freshness']['source']),identity.trade_id)
    return status_from(row,response),response,row
