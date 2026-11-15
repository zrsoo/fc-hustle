"""Explicit operator withdrawal of a certified read-only gate admission.

This is not auction reconciliation. A missing watched row alone never qualifies.
No EA call, refund, LOST or WON is inferred. All durable command states veto a
matching write, including NOT_DISPATCHED and already reconciled commands.
"""
from contextlib import ExitStack
from datetime import datetime
import json
from pathlib import Path
import secrets

from fc_access.actors_v1.locking import process_lock
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.bidding_v1.journal import Journal
from fc_access.production_v1.contracts import MUTATIONS, BULK, command as validate_command
from fc_access.production_v1.foundation import scope_for
from fc_access.production_v1.gate_00203 import admission_proof, digest


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def certificate(path):
    gate = json.loads(Path(path).read_text(encoding='utf-8'))
    need(gate['status'] == 'PASS' and gate['dependent_tasks_allowed'] is True and
         gate['hard_stop'] is False and gate['automatic_reruns'] is False and
         gate['automatic_repairs'] is False, 'read_only_gate_not_pass')
    need(gate['evidence_sha256'] == digest({k: v for k, v in gate.items() if k != 'evidence_sha256'}),
         'sealed_gate_evidence_changed')
    admission_proof(gate)  # Actual sealed native responses, not a PASS label.
    return gate


def references(value, labels):
    if isinstance(value, dict):
        return any(references(v, labels) for v in value.values())
    if isinstance(value, list):
        return any(references(v, labels) for v in value)
    return isinstance(value, str) and value in labels


def _verify(journal, gate):
    """Runs with journal, transport and mailbox write-locked in one transaction."""
    db = journal.db
    scope, identity = scope_for(gate['context']), gate['decision']['identity']
    trade, item = identity['trade_id'], identity['item_id']
    labels = {trade, item}
    row = db.execute('SELECT context FROM registry_context_v1 WHERE scope=?', (scope,)).fetchone()
    need(row and json.loads(row[0]) == gate['context'], 'withdrawal_context_mismatch')
    for schema in ('native', 'transport'):
        need(db.execute(f'PRAGMA {schema}.integrity_check').fetchall() == [('ok',)],
             'withdrawal_evidence_database_invalid')
    need(not db.execute('SELECT 1 FROM native.native_events e LEFT JOIN native.work w ON e.id=w.id '
                        'WHERE w.id IS NULL LIMIT 1').fetchone(), 'orphan_native_evidence')
    need(not db.execute('SELECT 1 FROM transport.events e LEFT JOIN transport.commands c ON e.command_id=c.id '
                        'WHERE c.id IS NULL LIMIT 1').fetchone(), 'orphan_transport_evidence')
    # The whole gate timeline must still be present and agree with its seal.
    for operation in gate['operations']:
        c = operation['command']
        retained = db.execute('SELECT body,result FROM transport.commands WHERE id=?', (c['id'],)).fetchone()
        need(retained and json.loads(retained[0]) == c and retained[1] and
             json.loads(retained[1]) == operation['response'], 'gate_transport_evidence_missing_or_changed')
    # An INTENT is already ambiguous. Never limit this check to pending rows.
    need(not db.execute('SELECT 1 FROM commands WHERE trade_id=? OR item_id=? LIMIT 1',
                        (trade, item)).fetchone(), 'admission_has_durable_bid_command')
    checked = {}
    for schema, table, column, response in (
            ('native', 'work', 'command', 'response'),
            ('transport', 'commands', 'body', 'result')):
        count = 0
        for encoded, raw_result, state in db.execute(f'SELECT {column},{response},state FROM {schema}.{table}'):
            command = json.loads(encoded)
            validate_command(command)
            if command['operation'] not in MUTATIONS:
                continue
            count += 1
            result = json.loads(raw_result) if raw_result else None
            need(not references([command, result], labels), 'admission_has_native_mutation')
            if command['operation'] in BULK and command['context'] == gate['context']:
                # Mailbox DONE is delivery, not reconciliation. Join the actual
                # independently reconciled bulk intent and transport record.
                intent = db.execute('SELECT body,state FROM bulk_writes_v1 WHERE id=?', (command['id'],)).fetchone()
                wire = db.execute('SELECT body,state FROM transport.commands WHERE id=?', (command['id'],)).fetchone()
                need(intent and wire and intent[1] == wire[1] == 'RECONCILED' and
                     json.loads(intent[0]) == json.loads(wire[0]) == command, 'ambiguous_account_wide_mutation')
        checked[schema + '_mutations_examined'] = count
    for table, before in (('resale_writes_v1', 'before_trade'), ('bulk_writes_v1', 'before_read')):
        for encoded, snapshot in db.execute(f'SELECT body,{before} FROM {table}'):
            prior = json.loads(snapshot) if table == 'bulk_writes_v1' else snapshot
            need(not references([json.loads(encoded), prior], labels),
                 'admission_has_other_write_intent')
    expected = dict(amount=gate['decision']['amount'], item_id=item,
                    definition_id=identity['definition_id'],
                    status_read_id=gate['final_status_read_id'],
                    balance_read_id=gate['final_balance_read_id'])
    trace = journal.trace(scope=scope, trade_id=trade)
    for event in journal.trace():
        if event['trade_id'] == trade or references(event['data'], labels):
            need(event['scope'] == scope and event['trade_id'] == trade, 'admission_identity_conflict')
    existing = db.execute('SELECT proof FROM admission_withdrawals_v1 WHERE scope=? AND trade_id=?',
                          (scope, trade)).fetchone()
    originals = [e for e in trace if e['reason'] != 'ADMISSION_WITHDRAWN']
    need(len(originals) == 1 and originals[0]['reason'] == 'ENROLLED' and
         originals[0]['data'] == expected and
         datetime.fromisoformat(gate['valuation_start_at']) <= datetime.fromisoformat(originals[0]['at']) <=
         datetime.fromisoformat(gate['final_decision_at']), 'admission_provenance_mismatch')
    # A second decision or actor enrollment is not this read-only gate admission.
    decisions = 0
    for seq, row_scope, row_trade, at, encoded in db.execute(
            'SELECT seq,scope,trade_id,at,body FROM registry_events_v1'):
        body = json.loads(encoded)
        if row_trade != trade and not references(body, labels):
            continue
        need(row_scope == scope and row_trade == trade, 'admission_identity_conflict')
        if body == gate['decision']:
            decisions += 1
            need(datetime.fromisoformat(gate['valuation_start_at']) <= datetime.fromisoformat(at) <=
                 datetime.fromisoformat(gate['final_decision_at']), 'decision_outside_gate')
        else:
            allowed = (body.get('kind') == 'ACTOR' and body.get('reason') == 'MISSING_OR_STALE_IDENTITY')
            allowed |= bool(existing and body.get('kind') == 'ADMISSION_WITHDRAWAL' and
                            body.get('gate_evidence_sha256') == gate['evidence_sha256'])
            need(allowed, 'admission_has_trading_provenance')
    need(decisions == 1, 'admission_decision_not_unique')
    slot = db.execute('SELECT item_id,definition_id,phase FROM capacity_slots_v1 WHERE scope=? AND trade_id=?',
                      (scope, trade)).fetchone()
    need(slot == (item, identity['definition_id'], 'WITHDRAWN' if existing else 'UNRESOLVED'),
         'admission_capacity_conflict')
    if existing:
        proof = json.loads(existing[0])
        need(proof['gate_evidence_sha256'] == gate['evidence_sha256'] and
             len(trace) == 2 and trace[-1]['reason'] == 'ADMISSION_WITHDRAWN', 'withdrawal_audit_conflict')
        return proof, True
    need(len(trace) == 1, 'withdrawal_audit_conflict')
    return dict(schema=1, scope=scope, identity=identity, amount=expected['amount'],
                enrollment_seq=originals[0]['seq'], gate_evidence_sha256=gate['evidence_sha256'],
                verified_gate_commands=len(gate['operations']), **checked), False


def withdraw(*, journal_path, gate_path, native_path, transport_path, state_dir, authority):
    """Finite explicit local repair. Refuses running owners; never auto-runs at startup.

    All input databases must already exist. Explicit zero-row updates acquire
    attached WAL write locks, closing the verify/enqueue race even for a producer
    that does not hold the account process lock. Only main's rows are changed.
    """
    from .runtime import ROOT, account_locks
    need(isinstance(authority, str) and 1 <= len(authority) <= 1000, 'explicit_withdrawal_authority_required')
    gate = certificate(gate_path)
    paths = [Path(p).resolve() for p in (journal_path, native_path, transport_path)]
    need(len(set(paths)) == 3 and all(p.is_file() for p in paths), 'existing_distinct_evidence_required')
    journal_path, native_path, transport_path = paths
    state_dir = Path(state_dir).resolve()
    locks = [*account_locks(gate['context']), state_dir/'supervisor.lock',
             ROOT/'private-captures/production-v1/actors-executor-8784.lock',
             journal_path.with_suffix('.continuous.owner.lock'),
             journal_path.with_suffix('.continuous.executor.lock'),
             journal_path.with_suffix('.bid.lock'), state_dir/'native.executor.lock',
             native_path.with_suffix('.executor.lock')]
    with ExitStack() as stack:
        for path in dict.fromkeys(p.resolve() for p in locks):
            stack.enter_context(process_lock(path))
        journal = Journal(journal_path)
        stack.callback(journal.close)
        journal.db.execute('ATTACH DATABASE ? AS native', (str(native_path),))
        journal.db.execute('ATTACH DATABASE ? AS transport', (str(transport_path),))
        with journal.transaction():
            # SQLite may lazily open attached WAL write transactions. Touch the
            # write paths without changing any mailbox/transport row or evidence.
            journal.db.execute('UPDATE native.work SET state=state WHERE 0')
            journal.db.execute('UPDATE transport.commands SET state=state WHERE 0')
            journal.db.execute('CREATE TABLE IF NOT EXISTS admission_withdrawals_v1('
                'scope TEXT NOT NULL,trade_id TEXT NOT NULL,proof TEXT NOT NULL,PRIMARY KEY(scope,trade_id))')
            for op in ('UPDATE', 'DELETE'):
                journal.db.execute(f'CREATE TRIGGER IF NOT EXISTS withdrawal_no_{op.lower()} BEFORE {op} '
                    "ON admission_withdrawals_v1 BEGIN SELECT RAISE(ABORT,'append_only'); END")
            proof, exists = _verify(journal, gate)
            if exists:
                return dict(outcome='ALREADY_WITHDRAWN', proof=proof)
            scope, trade = proof['scope'], proof['identity']['trade_id']
            owner = secrets.token_hex(16)
            prior = journal.db.execute('SELECT owner,epoch FROM sessions WHERE scope=?', (scope,)).fetchone()
            need(prior is not None, 'withdrawal_scope_has_no_owner')
            epoch = prior[1] + 1
            # Fence every in-memory admission from an earlier process/epoch.
            journal.db.execute('UPDATE sessions SET owner=?,epoch=? WHERE scope=?', (owner, epoch, scope))
            journal._event(scope, 'SESSION_STARTED', dict(owner=owner, epoch=epoch))
            proof.update(authority=authority, withdrawn_at=journal.now().isoformat(),
                         previous_owner=prior[0], previous_epoch=prior[1], owner=owner, epoch=epoch)
            journal.db.execute('INSERT INTO admission_withdrawals_v1 VALUES(?,?,?)',
                               (scope, trade, json.dumps(proof, sort_keys=True)))
            journal._event(scope, 'ADMISSION_WITHDRAWN', dict(item_id=proof['identity']['item_id'],
                definition_id=proof['identity']['definition_id'], amount=proof['amount'], owner=owner, epoch=epoch), trade)
            audit = dict(kind='ADMISSION_WITHDRAWAL', action='WITHDRAWN', reason='NEVER_DISPATCHED',
                         state='UNKNOWN', identity=proof['identity'], amount=proof['amount'],
                         owner=owner, epoch=epoch, gate_evidence_sha256=proof['gate_evidence_sha256'])
            journal.db.execute('INSERT INTO registry_events_v1(scope,trade_id,at,body) VALUES(?,?,?,?)',
                               (scope, trade, proof['withdrawn_at'], json.dumps(audit, sort_keys=True)))
            queue = AuctionQueue(journal=journal, scope=scope)
            need(trade not in queue.entries and trade not in queue.reservations and
                 trade not in queue.pending_resale, 'withdrawal_projection_failed')
            return dict(outcome='WITHDRAWN', proof=proof)
