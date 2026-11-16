"""Explicit operator-confirmed terminal loss; never inferred from absence/expiry.

This local operation records a user's assertion separately from native outcome
proof. It cannot submit/retry a bid, credit a refund or authorize another loss.
Call only under stopped controller/executor/bid locks and explicit authorization.
"""
from datetime import datetime
import json
import secrets

from fc_access.bidding_v1.contracts import Identity, integer, token
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.production_v1.foundation import scope_for


def need(value, reason):
    if not value: raise ValueError(reason)


def confirm(journal, *, context, command_id, identity, amount, attestation, authorization):
    need(isinstance(identity, Identity), 'exact_identity_required')
    token(command_id); integer(amount, 1)
    need(all(isinstance(v, str) and 0 < len(v) <= 2000 for v in (attestation, authorization)),
         'explicit_operator_loss_and_authorization_required')
    scope = scope_for(context)
    db = journal.db
    with journal.transaction():
        stored = db.execute('SELECT context FROM registry_context_v1 WHERE scope=?', (scope,)).fetchone()
        need(stored and json.loads(stored[0]) == context, 'operator_resolution_context_mismatch')
        row = db.execute('SELECT scope,trade_id,item_id,definition_id,amount,state,deadline FROM commands WHERE id=?',
                         (command_id,)).fetchone()
        need(row and row[:5] == (scope, identity.trade_id, identity.item_id, identity.definition_id, amount),
             'operator_resolution_identity_or_amount_mismatch')
        need(journal.now() > datetime.fromisoformat(row[6]), 'auction_not_expired')
        db.execute('CREATE TABLE IF NOT EXISTS operator_losses_v1('
            'command_id TEXT PRIMARY KEY,scope TEXT NOT NULL,proof TEXT NOT NULL)')
        for op in ('UPDATE','DELETE'):
            db.execute(f'CREATE TRIGGER IF NOT EXISTS operator_loss_no_{op.lower()} BEFORE {op} '
                "ON operator_losses_v1 BEGIN SELECT RAISE(ABORT,'append_only'); END")
        prior = db.execute('SELECT proof FROM operator_losses_v1 WHERE command_id=?', (command_id,)).fetchone()
        if prior:
            need(row[5] == 'RECONCILED', 'operator_resolution_audit_conflict')
            return dict(outcome='ALREADY_RESOLVED', proof=json.loads(prior[0]))
        need(row[5] not in {'RECONCILED','NOT_DISPATCHED'}, 'command_already_terminal_or_not_dispatched')
        need(db.execute("SELECT 1 FROM events WHERE scope=? AND trade_id=? AND command_id=? AND reason='PENDING'",
                        (scope,identity.trade_id,command_id)).fetchone(), 'dispatched_command_required')
        need(not db.execute('SELECT 1 FROM commands WHERE scope=? AND trade_id=? AND id!=? '
                            "AND state NOT IN ('RECONCILED','NOT_DISPATCHED')",
                            (scope,identity.trade_id,command_id)).fetchone(), 'other_unresolved_bid_on_trade')
        need(not db.execute("SELECT 1 FROM events WHERE scope=? AND trade_id=? AND reason IN ('WON_VERIFIED','LOST_VERIFIED')",
                            (scope,identity.trade_id)).fetchone(), 'conflicting_native_terminal_evidence')
        slot = db.execute('SELECT item_id,definition_id,phase FROM capacity_slots_v1 WHERE scope=? AND trade_id=?',
                          (scope,identity.trade_id)).fetchone()
        need(slot == (identity.item_id,identity.definition_id,'UNRESOLVED'), 'operator_resolution_slot_conflict')
        # A proven owned/resale item must never be disposed as a loss by this seam.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='resales_v1'").fetchone():
            need(not db.execute('SELECT 1 FROM resales_v1 WHERE scope=? AND (trade_id=? OR item_id=?)',
                                (scope,identity.trade_id,identity.item_id)).fetchone(), 'owned_resale_conflict')
        inventory = db.execute('SELECT items FROM capacity_inventory_v1 WHERE scope=?', (scope,)).fetchone()
        need(not inventory or identity.item_id not in {i[0] for i in json.loads(inventory[0])}, 'owned_inventory_conflict')
        old_owner = db.execute('SELECT owner,epoch FROM sessions WHERE scope=?', (scope,)).fetchone()
        need(old_owner is not None, 'operator_resolution_owner_missing')
        owner, epoch = secrets.token_hex(16), old_owner[1]+1
        proof = dict(schema=1,source='operator',outcome='LOST',native_outcome_verified=False,
                     command_id=command_id,scope=scope,identity=vars(identity),amount=amount,
                     attestation=attestation,authorization=authorization,previous_command_state=row[5],
                     previous_owner=old_owner[0],previous_epoch=old_owner[1],owner=owner,epoch=epoch,
                     at=journal.now().isoformat(),refund_claimed=False)
        db.execute('UPDATE sessions SET owner=?,epoch=? WHERE scope=?', (owner,epoch,scope))
        journal._event(scope,'SESSION_STARTED',dict(owner=owner,epoch=epoch))
        db.execute('INSERT INTO operator_losses_v1 VALUES(?,?,?)', (command_id,scope,json.dumps(proof,sort_keys=True)))
        db.execute("UPDATE commands SET state='RECONCILED' WHERE id=?", (command_id,))
        journal._event(scope,'OPERATOR_LOST_CONFIRMED',dict(item_id=identity.item_id,
            definition_id=identity.definition_id,amount=amount,owner=owner,epoch=epoch),identity.trade_id,command_id)
        audit = dict(kind='OPERATOR_RESOLUTION',source='operator',identity=vars(identity),
                     command_id=command_id,outcome='LOST',native_outcome_verified=False,owner=owner,epoch=epoch)
        db.execute('INSERT INTO registry_events_v1(scope,trade_id,at,body) VALUES(?,?,?,?)',
                   (scope,identity.trade_id,proof['at'],json.dumps(audit,sort_keys=True)))
        queue = AuctionQueue(journal=journal,scope=scope)
        need(identity.trade_id not in queue.entries and identity.trade_id not in queue.reservations and
             identity.trade_id not in queue.pending_resale, 'operator_resolution_replay_failed')
        return dict(outcome='RESOLVED',proof=proof)
