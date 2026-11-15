"""Read-only baseline evidence assessment. Importing this module cannot call EA."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1.contracts import parse_response, stamp
from fc_access.production_v1.foundation import scope_for
from fc_access.production_v1.price_cache import QuoteCache, TTL_SECONDS
from fc_access.bidding_v1.journal import Journal
from fc_access.bidding_v1.core import AuctionQueue

OUT = ROOT / 'docs/research/003/003-01'
READS = {'balance', 'watched', 'transfer_list', 'unassigned'}
BASELINE = '413d21ad0a5d976572f2c488524f1a23d8a44340'
REQUIRED = [
    'AGENTS.md', 'objectives/002-two-actor-competitive-bidding.md',
    'objectives/003-production-actor-soak.md',
    'docs/research/002/002-12/review-05/REPORT.md',
    'docs/research/002/002-12/review-05/outcome.json',
    'docs/research/002/002-12/series-selection.json',
    'docs/research/002/002-12/blocker-repair-02/REPORT.md',
    'docs/research/002-bulk-transfer-operations/REPORT.md',
    'docs/research/002/002-03/attempts/20261114-adapter-repair-gate-06/REPORT.md',
]


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


@contextmanager
def database(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        yield connection
    finally:
        connection.close()


def assess_reads(rows, expected_context, historical_responses):
    """Validate freshness at capture time, never promote old reads to current.

    Existing account/persona pseudonyms alone are not account proof. Require
    matching physical/version/trade mappings in authenticated historical native
    responses in the same namespace, in addition to the native selected-object
    and PC fences checked by the production bridge.
    """
    services = [r for r in rows if r['kind'] == 'READ_ONLY_SERVICE']
    need(len(services) == 1, 'one_service_receipt_required')
    health = services[0]['health']
    need(health.get('service') == 'fc-production-v1' and health.get('schema') == 2
         and health.get('attached') is True and health.get('mutations_enabled') is False,
         'read_only_attached_service_required')
    peer = health['peer']
    need(peer['context'] == expected_context, 'wrong_account_persona_namespace')
    intents = [r['command'] for r in rows if r['kind'] == 'READ_INTENT']
    captured = [r for r in rows if r['kind'] == 'NATIVE_READ']
    need(len(intents) == len(captured) == 4 and {c['operation'] for c in intents} == READS,
         'four_distinct_native_reads_required')
    need(len({c['id'] for c in intents}) == 4, 'duplicate_read_id')
    need(all(c['operation'] in READS and c['params'] == {} for c in intents), 'read_only_allowlist')
    results, last = {}, None
    for intent, row in zip(intents, captured):
        c, v = row['command'], row['response']
        need(c == intent and c['context'] == expected_context and c['fences'] == peer['fences'],
             'identity_or_fence_changed')
        parse_response(v, c, source='native', now=stamp(row['at']))
        need(v['result']['success'] is True and v['freshness']['request_count'] == 1,
             'successful_single_native_get_required')
        net = v['result']['network']
        need(all(n['method'] == 'GET' for n in net), 'mutation_in_reconciliation')
        at = stamp(v['freshness']['network_at'])
        need(last is None or (at-last).total_seconds() >= 2, 'native_pacing_not_preserved')
        last = at
        results[c['operation']] = v
    inventory = results['transfer_list']
    need(inventory['coverage']['complete'] and inventory['coverage']['has_more'] is False,
         'complete_inventory_required')
    history_items, history_trades = set(), set()
    for v in historical_responses:
        if v['context'] != expected_context or not v['result']['success']:
            continue
        if not v['freshness']['network_at'] or not v['result']['network'] or not all(
                n['session_header_present'] and n['status'] == 200 for n in v['result']['network']):
            continue
        for a in v['result']['auctions'] or []:
            identity = a['item']['item_id'], a['item']['definition_id']
            history_items.add(identity)
            history_trades.add((a['trade_id'], *identity))
    current = inventory['result']['auctions']
    watched = results['watched']['result']['auctions']
    need(current and all((a['item']['item_id'], a['item']['definition_id']) in history_items
                        for a in current), 'physical_account_continuity_unproven')
    need(watched and all((a['trade_id'], a['item']['item_id'], a['item']['definition_id'])
                         in history_trades for a in watched), 'watched_mapping_continuity_unproven')
    return dict(context=expected_context, fences=peer['fences'],
                identity_basis='NATIVE_SELECTED_OBJECT_FENCING_AND_INDEPENDENT_PHYSICAL_HISTORY',
                credits=results['balance']['result']['credits'],
                inventory=current, watched=watched, unassigned=results['unassigned']['result']['items'],
                watched_complete=results['watched']['coverage']['complete'],
                read_ids={op: v['command_id'] for op, v in results.items()},
                network_at={op: v['freshness']['network_at'] for op, v in results.items()},
                mutations_enabled=False, native_requests=4)


def commitments(journal_path, context):
    scope = scope_for(context)
    j = Journal(journal_path, readonly=True)
    try:
        q = AuctionQueue(journal=j, scope=scope)
        pending = []
        for table in ('commands', 'bulk_writes_v1', 'resale_writes_v1'):
            pending += [dict(table=table, id=i, state=s) for i, s in j.db.execute(
                f"SELECT id,state FROM {table} WHERE scope=? AND state NOT IN ('RECONCILED','NOT_DISPATCHED')",
                (scope,))]
        slots = [dict(trade_id=t, item_id=i, definition_id=d, phase=p) for t, i, d, p in j.db.execute(
            'SELECT trade_id,item_id,definition_id,phase FROM capacity_slots_v1 WHERE scope=? ORDER BY trade_id',
            (scope,))]
        return dict(scope=scope, unresolved=[vars(q.identities[t]) for t in sorted(q.identities)],
                    reservations={t: list(v) for t, v in sorted(q.reservations.items())},
                    reserved_coins=sum(v[0] for v in q.reservations.values()),
                    draining=q.draining, slots=slots, pending_mutation_intents=pending,
                    other_scope_slots=j.db.execute(
                        'SELECT count(*) FROM capacity_slots_v1 WHERE scope!=?', (scope,)).fetchone()[0])
    finally:
        j.close()


def cache_state(cache_path, context, at):
    rows = []
    with database(cache_path) as c:
        for account, game, platform, definition, observed, payload in c.execute(
                'SELECT * FROM completed_quotes_v1 ORDER BY account,game,platform,definition_id'):
            v = json.loads(payload)
            age = (at-datetime.fromtimestamp(observed, timezone.utc)).total_seconds()
            reason = 'USABLE'
            try:
                QuoteCache._completed(v)
                if (account, game, platform) != tuple(context[k] for k in ('account', 'game', 'platform')) or (
                        v['identity_namespace'] != context['identity_namespace'] or v['source'] != 'native'):
                    reason = 'WRONG_SCOPE_OR_SOURCE'
                elif not 0 <= age < TTL_SECONDS:
                    reason = 'EXPIRED_OR_FUTURE'
            except (ValueError, KeyError, TypeError):
                reason = 'INVALID_COMPLETED_QUOTE'
            rows.append(dict(account=account, game=game, platform=platform, definition_id=definition,
                             observed_at=observed, age_seconds=age, status=reason))
    return dict(assessed_at=at.isoformat(), ttl_seconds=TTL_SECONDS, entries=rows)


def mutation_gate(reads, durable):
    # This baseline never grants dispatch authority, even after reconciliation.
    watched = {(a['trade_id'], a['item']['item_id'], a['item']['definition_id']) for a in reads['watched']}
    unmapped = [a for a in durable['unresolved'] if
               (a['trade_id'], a['item_id'], a['definition_id']) not in watched]
    return dict(allowed=False, reason='BASELINE_READ_ONLY',
                pending_intents=durable['pending_mutation_intents'],
                unmapped_commitments=unmapped,
                independent_reconciliation_required=bool(unmapped or durable['pending_mutation_intents']),
                absent_watched_is_terminal_proof=False)
