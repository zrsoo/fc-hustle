"""Read-only Transfer List admission guard. No ownership/state filtering.

The native pile's size is not the policy limit. Count physical entries, including
manual entries and sold cards until a complete read proves they are absent.
The validated inventory is committed to the combined-capacity ledger (002-06).
"""
from fc_access.production_v1.contracts import parse_response


def assess(response, command, *, now, source, limit=50):
    evidence = dict(limit=limit, occupied=None, observed_entries=None,
        read_id=command['id'], network_at=None, coverage=None,
        enrollment_allowed=False, reason='TRANSFER_LIST_UNKNOWN')
    try:
        if command['operation'] != 'transfer_list':
            return evidence
        v = parse_response(response, command, now=now, source=source)
    except ValueError as error:
        reason = str(error)
        if reason in {'stale_or_unauthenticated_source', 'stale_source', 'unsupported_freshness'}:
            evidence['reason'] = 'TRANSFER_LIST_STALE'
        elif reason in {'duplicate_identity', 'inventory_count_conflict', 'response_correlation_mismatch'}:
            evidence['reason'] = 'TRANSFER_LIST_CONFLICT'
        return evidence
    evidence.update(network_at=v['freshness']['network_at'], coverage=v['coverage'],
        observed_entries=len(v['result']['auctions'] or []))
    if not v['result']['success']:
        if v['result']['error'] in {'stale_source', 'cache_only_source'}:
            evidence['reason'] = 'TRANSFER_LIST_STALE'
        elif v['result']['error'] == 'transfer_list_conflict':
            evidence['reason'] = 'TRANSFER_LIST_CONFLICT'
        return evidence
    proof = v['coverage'].get('transfer_list')
    if not proof:
        return evidence  # Legacy fresh reads never established completeness.
    evidence['reason'] = proof['reason']
    if not v['coverage']['complete']:
        return evidence
    rows = v['result']['auctions']
    # Distinct physical items cannot share a live auction. Multiple inactive
    # entries can legitimately use the native no-auction sentinel trade ID.
    trades = [r['trade_id'] for r in rows if r['trade_state'] == 'active']
    if len(set(trades)) != len(trades):
        evidence['reason'] = 'TRANSFER_LIST_CONFLICT'
        return evidence
    occupied = len(rows)
    evidence.update(occupied=occupied, enrollment_allowed=occupied < limit,
        reason='TRANSFER_LIST_OVER_CAP' if occupied > limit else
            'TRANSFER_LIST_FULL' if occupied == limit else 'TRANSFER_LIST_AVAILABLE')
    return evidence


def read(foundation, *, limit=50):
    """Always request a new TRANSFER-dirty read; never reuse a prior count."""
    try:
        response = foundation.read('transfer_list')
    except (ValueError, TimeoutError) as error:
        # Transport deliberately hides untrusted exception details. Retain an
        # explicit unknown pause without echoing arbitrary native error text.
        reason = ('TRANSFER_LIST_STALE' if str(error) in {'stale_source', 'stale_or_unauthenticated_source'} else
            'TRANSFER_LIST_CONFLICT' if str(error)=='transfer_list_conflict' else 'TRANSFER_LIST_UNKNOWN')
        return dict(limit=limit, occupied=None, observed_entries=None, read_id=None,
            network_at=None, coverage=None, enrollment_allowed=False, reason=reason)
    evidence = assess(response, foundation.adapter.commands[response['command_id']],
        now=foundation.now(), source=foundation.adapter.source, limit=limit)
    if evidence['occupied'] is not None:
        from fc_access.bidding_v1 import capacity
        from fc_access.production_v1.contracts import stamp
        try:
            capacity.observe(foundation.journal, foundation.registry.scope, response['result']['auctions'],
                read_id=response['command_id'], network_at=stamp(evidence['network_at']), now=foundation.now())
        except ValueError as error:
            evidence.update(enrollment_allowed=False, reason='TRANSFER_LIST_STALE' if str(error)==
                'capacity_inventory_stale' else 'TRANSFER_LIST_CONFLICT')
            return evidence
        evidence['pipeline'] = capacity.status(foundation.journal, foundation.registry.scope, now=foundation.now())
    return evidence
