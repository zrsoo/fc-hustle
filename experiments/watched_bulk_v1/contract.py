"""Observed native cache behavior and cautious bulk-status ingestion.

No capacity default; 50 is an application queue choice. Terminal native states
remain pending/unknown until the caller supplies independent outcome evidence.
"""
from datetime import datetime, timedelta
from fc_access.bidding_v1.contracts import AuctionStatus, Coverage, Freshness, Identity, Snapshot, State
from .validation import assess


def to_snapshot(probe, read_id, *, fixture=False):
    assessment=assess(probe)
    if not probe['success'] or probe['auctions'] is None or probe['operation']!='watched':
        raise ValueError('watched_read_failed')
    at=datetime.fromisoformat(probe['observed_at'])
    network=datetime.fromisoformat(probe['network_at']) if assessment['fresh'] else None
    freshness=Freshness(at,network,probe['request_count'],read_id,'fixture' if fixture else 'native')
    rows=[]
    for a in probe['auctions']:
        state=State.UNKNOWN
        if network and a['trade_state']=='active' and (a['expires'] or 0)>0:
            state={'highest':State.LEADING,'outbid':State.OUTBID,'none':State.ACTIVE}.get(a['bid_state'],State.UNKNOWN)
        elif network and a['trade_state'] in ('closed','expired') and a['bid_state']=='highest':
            state=State.PENDING
        rows.append(AuctionStatus(Identity(a['trade_id'],a['item_id'],a['definition_id']),state,
            a['starting_bid'],a['current_bid'],a['buy_now_price'],
            (network or at)+timedelta(seconds=max(0,a['expires'] or 0)),freshness))
    return Snapshot(tuple(rows),freshness,Coverage(False,probe['has_more'],assessment['account_capacity'],None))


def refresh_cost(probes):
    """Measured samples only. No inferred 50-auction latency or EA rate limit."""
    samples=[p for p in probes if assess(p)['fresh']]
    return {'samples':len(samples),'observed_queue_sizes':sorted({len(p['auctions']) for p in samples}),
            'native_requests_per_sample':[p['request_count'] for p in samples],
            'native_service_ms':[p['duration_ms'] for p in samples],
            'configured_queue_size':50,'live_50_verified':False,'sustained_25_second_cycle_verified':False}
