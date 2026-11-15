"""Independent assessment of captured before/after local withdrawal databases.

Only captured state is compared. No source-file integrity enforcement, network,
schema migrations or account mutations. Actor runtime acceptance stays separate.
"""
from contextlib import closing
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.bidding_v1.journal import Journal
from fc_access.production_v1.foundation import scope_for
from fc_access.production_v1.gate_00203 import require_pass


def need(value, reason):
    if not value: raise ValueError(reason)


def assess(before, after, gate_path):
    require_pass(gate_path)
    gate = json.loads(Path(gate_path).read_text(encoding='utf-8'))
    scope = scope_for(gate['context'])
    trade = gate['decision']['identity']['trade_id']
    item = gate['decision']['identity']['item_id']
    def connect(path):
        return sqlite3.connect(Path(path).resolve().as_uri()+'?immutable=1', uri=True)
    with closing(connect(before)) as old, closing(connect(after)) as new:
        for db in (old, new):
            need(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'invalid_capture')
        for table in ('events', 'registry_events_v1'):
            rows = old.execute(f'SELECT * FROM {table} ORDER BY seq').fetchall()
            retained = new.execute(f'SELECT * FROM {table} WHERE seq<=? ORDER BY seq', (rows[-1][0],)).fetchall()
            need(retained == rows, 'historical_rows_changed')
        for table in ('commands','resale_writes_v1','bulk_writes_v1','registry_context_v1',
                      'capacity_inventory_v1','capacity_reads_v1'):
            need(old.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() ==
                 new.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall(), 'unrelated_state_changed')
        slots = old.execute('SELECT * FROM capacity_slots_v1 ORDER BY scope,trade_id').fetchall()
        expected = [(*row[:4], 'WITHDRAWN') if row[:2] == (scope, trade) else row for row in slots]
        need(new.execute('SELECT * FROM capacity_slots_v1 ORDER BY scope,trade_id').fetchall() == expected,
             'capacity_not_exactly_one_local_release')
        proof_row = new.execute('SELECT proof FROM admission_withdrawals_v1 WHERE scope=? AND trade_id=?',
                                (scope, trade)).fetchone()
        need(proof_row is not None, 'withdrawal_proof_missing')
        proof = json.loads(proof_row[0])
        need(proof['identity'] == gate['decision']['identity'] and proof['amount'] == gate['decision']['amount'] and
             proof['gate_evidence_sha256'] == gate['evidence_sha256'] and proof['authority'] and
             proof['verified_gate_commands'] == len(gate['operations']), 'withdrawal_proof_mismatch')
        sessions = old.execute('SELECT * FROM sessions ORDER BY scope').fetchall()
        expected_sessions = [(s, proof['owner'], proof['epoch']) if s == scope else (s, o, e) for s, o, e in sessions]
        need(new.execute('SELECT * FROM sessions ORDER BY scope').fetchall() == expected_sessions,
             'scope_or_owner_not_fenced')
        prior = next(row for row in sessions if row[0] == scope)
        need(proof['previous_owner'] == prior[1] and proof['previous_epoch'] == prior[2] and
             proof['owner'] != prior[1] and proof['epoch'] == prior[2]+1, 'invalid_owner_transition')
        need(not new.execute('SELECT 1 FROM commands WHERE trade_id=? OR item_id=?', (trade,item)).fetchone(),
             'actual_bid_must_not_be_withdrawn')
        trace = new.execute('SELECT reason FROM events WHERE scope=? AND trade_id=? ORDER BY seq', (scope,trade)).fetchall()
        need(trace == [('ENROLLED',), ('ADMISSION_WITHDRAWN',)], 'auction_terminal_outcome_invented')
        audit = [json.loads(r[0]) for r in new.execute('SELECT body FROM registry_events_v1 '
            'WHERE scope=? AND trade_id=? ORDER BY seq', (scope,trade))][-1]
        need(audit['kind'] == 'ADMISSION_WITHDRAWAL' and audit['state'] == 'UNKNOWN' and
             audit['action'] == 'WITHDRAWN', 'local_disposition_not_recorded')
    # Separately use the real restart projection, without installing/migrating it.
    old = Journal(before, readonly=True); new = Journal(after, readonly=True)
    try:
        before_queue, after_queue = [AuctionQueue(journal=j, scope=scope) for j in (old,new)]
        need(trade in before_queue.entries and before_queue.reservations[trade][0] == 700,
             'original_blocker_not_present')
        need(trade not in after_queue.entries and trade not in after_queue.identities and
             trade not in after_queue.reservations and trade not in after_queue.pending_resale,
             'restart_still_blocked_by_local_admission')
        need(after_queue.draining == before_queue.draining, 'draining_policy_reset')
        need(gate['final_balance_read_id'] in after_queue.invalid_balances, 'old_balance_not_invalidated')
    finally: old.close(); new.close()
    return dict(status='PASS', scope=scope, trade_id=trade, released_local_coins=700,
        released_local_capacity_slots=1, EA_requests=0, account_mutations=0,
        historical_rows_preserved=True, bid_commands_unchanged=True,
        restart_replay='WITHDRAWN; actual auction UNKNOWN', actor_soak_acceptance='STILL_REQUIRED')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', required=True); p.add_argument('--after', required=True)
    p.add_argument('--gate', default=str(ROOT/'docs/research/002/002-03/attempts/20261114-adapter-repair-gate-06/gate.json'))
    args = p.parse_args()
    print(json.dumps(assess(args.before, args.after, args.gate), indent=2))
