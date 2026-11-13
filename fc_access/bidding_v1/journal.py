"""SQLite append-only journal and single-dispatch fencing, not a retry queue.

INTENT is already ambiguous after a crash. No claim is ever redelivered, even
after ownership/epoch changes. Independent fresh reconciliation gates all writes.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import json
import math
import sqlite3

from .contracts import BidIntent, BidResult, Outcome, State, instant, integer, token

REASONS = {"SESSION_STARTED", "INTENT_DURABLE", "NATIVE_ACK", "TIMEOUT", "INVALID_RESULT", "SERVICE_ERROR",
           "BID_VERIFIED", "WON_VERIFIED", "LOST_VERIFIED", "HOLD", "SKIP", "PENDING", "UNKNOWN",
           "ENROLLED", "QUEUE_FULL", "DRAINING", "DRAINED", "STALE", "OVER_CAP", "INSUFFICIENT_BALANCE",
           "EXPIRED", "REBID", "OPENING", "LIFECYCLE_ERROR", "DEADLINE_SKIPPED", "NOT_DISPATCHED", "RESERVATION_RELEASED",
           "READ_OBSERVED", "NATIVE_TIMING", "BALANCE_OBSERVED", "DELIVERY_OBSERVED"}
NUMBERS = {"amount", "cap", "target", "tax", "profit_threshold", "samples", "spendable", "held", "paid",
           "epoch", "local_delivery_ms", "native_service_ms", "request_count", "definition_id", "expected_profit"}
IDS = {"owner", "scope", "read_id", "status_read_id", "balance_read_id"}


def comparables(rows):
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("unsafe_comparables")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"trade_id", "item_id", "definition_id", "platform", "ask", "at", "expires", "active", "network_fresh"}:
            raise ValueError("unsafe_comparable")
        token(row["trade_id"], "trade")
        token(row["item_id"], "item")
        integer(row["definition_id"], 1)
        integer(row["ask"], 1)
        integer(row["expires"])
        if row["platform"] not in {"pc", "ps5", "ps4", "xbox", "xboxone", "xbsx", "switch"} or any(type(row[k]) is not bool for k in ("active", "network_fresh")):
            raise ValueError("unsafe_comparable_market")
        if instant(datetime.fromisoformat(row["at"])).isoformat() != row["at"]:
            raise ValueError("comparable_utc_required")
    return rows


def payload(value):
    if not isinstance(value, dict) or set(value) - NUMBERS - IDS - {"item_id", "state", "pricing_digest", "rules_digest", "source", "comparables"}:
        raise ValueError("unsafe_event_payload")
    for key, val in value.items():
        if key in NUMBERS:
            if val is not None:
                if key in {"local_delivery_ms", "native_service_ms"}:
                    if type(val) not in (int, float) or not math.isfinite(val) or val < 0:
                        raise ValueError("invalid_latency")
                else:
                    integer(val)
        elif key in IDS:
            token(val)
        elif key == "item_id":
            token(val, "item")
        elif key == "state":
            State(val)
        elif key == "source":
            if val not in {"native", "fixture"}:
                raise ValueError("invalid_source")
        elif key == "comparables":
            comparables(val)
        elif key in {"pricing_digest", "rules_digest"}:
            if not isinstance(val, str) or len(val) != 64 or any(c not in "0123456789abcdef" for c in val):
                raise ValueError("invalid_pricing_digest")
    return value


class Journal:
    def __init__(self, path, *, now=lambda: datetime.now(timezone.utc), readonly=False):
        self.now = now
        self._tickets = {}
        if readonly:
            from pathlib import Path
            self.db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=5, isolation_level=None)
        else:
            self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
          CREATE TABLE IF NOT EXISTS metadata(version INTEGER NOT NULL);
          INSERT INTO metadata SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM metadata);
          CREATE TABLE IF NOT EXISTS sessions(scope TEXT PRIMARY KEY, owner TEXT NOT NULL, epoch INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, version INTEGER NOT NULL,
            at TEXT NOT NULL, scope TEXT NOT NULL, trade_id TEXT, command_id TEXT, reason TEXT NOT NULL, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, scope TEXT NOT NULL, owner TEXT NOT NULL,
            epoch INTEGER NOT NULL, trade_id TEXT NOT NULL, item_id TEXT NOT NULL, definition_id INTEGER NOT NULL,
            amount INTEGER NOT NULL, state TEXT NOT NULL, deadline TEXT NOT NULL, status_read_id TEXT NOT NULL,
            balance_read_id TEXT NOT NULL, intended_at TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'append_only'); END;
        """)
        if self.db.execute("SELECT version FROM metadata").fetchall() != [(1,)]:
            self.close()
            raise ValueError("unsupported_journal_version")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _event(self, scope, reason, data=None, trade_id=None, command_id=None):
        token(scope)
        if reason not in REASONS:
            raise ValueError("unsafe_event_reason")
        if trade_id is not None:
            token(trade_id, "trade")
        if command_id is not None:
            token(command_id)
        self.db.execute("INSERT INTO events(version,at,scope,trade_id,command_id,reason,data) VALUES(1,?,?,?,?,?,?)",
                        (instant(self.now()).isoformat(), scope, trade_id, command_id, reason, json.dumps(payload(data or {}), sort_keys=True)))

    def record(self, scope, reason, data=None, *, trade_id=None, command_id=None):
        self.record_batch(scope, [(reason, data, trade_id, command_id)])

    def record_batch(self, scope, events):
        with self.transaction():
            for reason, data, trade_id, command_id in events:
                self._event(scope, reason, data, trade_id, command_id)

    def session(self, scope, owner, *, after_epoch=0):
        token(scope)
        token(owner)
        integer(after_epoch)
        with self.transaction():
            row = self.db.execute("SELECT epoch FROM sessions WHERE scope=?", (scope,)).fetchone()
            epoch = max(row[0] if row else 0, after_epoch)+1
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)", (scope, owner, epoch))
            self._event(scope, "SESSION_STARTED", {"owner": owner, "epoch": epoch})
        return epoch

    def _owner(self, scope, owner, epoch):
        if self.db.execute("SELECT owner,epoch FROM sessions WHERE scope=?", (scope,)).fetchone() != (owner, epoch):
            raise ValueError("stale_owner_or_epoch")

    def intend(self, intent: BidIntent, pricing_data=None):
        if not isinstance(intent, BidIntent):
            raise ValueError("invalid_intent")
        with self.transaction():
            self._owner(intent.scope, intent.owner, intent.epoch)
            if self.db.execute("SELECT 1 FROM commands WHERE id=?", (intent.command_id,)).fetchone():
                raise ValueError("duplicate_write")
            if self.db.execute("SELECT 1 FROM commands WHERE scope=? AND state NOT IN ('RECONCILED','NOT_DISPATCHED')", (intent.scope,)).fetchone():
                raise ValueError("reconciliation_required")
            earlier = self.db.execute("SELECT data FROM events WHERE scope=? AND trade_id=? AND reason='INTENT_DURABLE' ORDER BY seq LIMIT 1",
                                      (intent.scope, intent.identity.trade_id)).fetchone()
            if earlier and intent.cap > json.loads(earlier[0])["cap"]:
                raise ValueError("stored_cap_increase")
            if instant(self.now()) >= instant(intent.deadline):
                raise ValueError("expired_intent")
            i = intent.identity
            self.db.execute("INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (intent.command_id, intent.scope, intent.owner, intent.epoch, i.trade_id, i.item_id,
                             i.definition_id, intent.amount, "UNKNOWN", instant(intent.deadline).isoformat(),
                             intent.status_read_id, intent.balance_read_id, instant(self.now()).isoformat()))
            data = {"amount": intent.amount, "cap": intent.cap, "owner": intent.owner, "epoch": intent.epoch,
                    "item_id": i.item_id, "definition_id": i.definition_id,
                    "status_read_id": intent.status_read_id, "balance_read_id": intent.balance_read_id}
            permitted = {"target", "tax", "profit_threshold", "samples", "spendable", "held", "pricing_digest", "rules_digest", "expected_profit", "comparables"}
            if pricing_data is not None and (not isinstance(pricing_data, dict) or set(pricing_data)-permitted):
                raise ValueError("unsafe_pricing_payload")
            data.update(pricing_data or {})
            self._event(intent.scope, "INTENT_DURABLE", data, i.trade_id, intent.command_id)
        # Dispatch authority is local and one-use. Reopening a journal cannot
        # turn a recovered UNKNOWN intent into work to replay.
        self._tickets[intent.command_id] = intent

    def dispatch(self, intent, call):
        # Commit the dispatch claim BEFORE send; rollback/crash after send must
        # never erase it. A claim with no send is conservatively UNKNOWN too.
        with self.transaction():
            self._owner(intent.scope, intent.owner, intent.epoch)
            if self._tickets.get(intent.command_id) != intent:
                raise ValueError("no_local_dispatch_authority")
            row = self.db.execute("SELECT state FROM commands WHERE id=? AND scope=? AND owner=? AND epoch=?",
                                  (intent.command_id, intent.scope, intent.owner, intent.epoch)).fetchone()
            if row != ("UNKNOWN",) or self.db.execute("SELECT 1 FROM events WHERE command_id=? AND reason='PENDING'", (intent.command_id,)).fetchone():
                raise ValueError("duplicate_or_unowned_dispatch")
            if instant(self.now()) >= instant(intent.deadline):
                self.db.execute("UPDATE commands SET state='NOT_DISPATCHED' WHERE id=?", (intent.command_id,))
                self._event(intent.scope, "NOT_DISPATCHED", {}, intent.identity.trade_id, intent.command_id)
                self._tickets.pop(intent.command_id, None)
                return BidResult(intent.command_id, Outcome.UNKNOWN, "TIMEOUT")
            self._event(intent.scope, "PENDING", {}, intent.identity.trade_id, intent.command_id)
        self._tickets.pop(intent.command_id, None)
        # The final ownership check and synchronous send share the DB write lock.
        # Session takeover cannot pass the fence while a send is executing.
        with self.transaction():
            self._owner(intent.scope, intent.owner, intent.epoch)
            try:
                result = call()
                if not isinstance(result, BidResult) or result.command_id != intent.command_id:
                    result = BidResult(intent.command_id, Outcome.UNKNOWN, "INVALID_RESULT")
            except Exception:
                result = BidResult(intent.command_id, Outcome.UNKNOWN, "SERVICE_ERROR")
            self.db.execute("UPDATE commands SET state=? WHERE id=?", (result.outcome.value, intent.command_id))
            self._event(intent.scope, result.reason, {}, intent.identity.trade_id, intent.command_id)
            return result

    def reconcile(self, command_id, *, scope, owner, epoch, status, balance, max_age=30):
        with self.transaction():
            self._owner(scope, owner, epoch)
            row = self.db.execute("SELECT trade_id,item_id,definition_id,amount,state,status_read_id,balance_read_id,intended_at FROM commands WHERE id=? AND scope=?", (command_id, scope)).fetchone()
            if not row or row[4] in {"RECONCILED", "NOT_DISPATCHED"}:
                raise ValueError("not_pending")
            identity = status.identity
            if (identity.trade_id, identity.item_id, identity.definition_id) != row[:3]:
                raise ValueError("reconciliation_identity_mismatch")
            at = datetime.fromisoformat(row[7])
            if (not status.freshness.fresh(self.now(), max_age) or not balance.freshness.fresh(self.now(), max_age)
                    or status.freshness.read_id == row[5] or balance.freshness.read_id == row[6]
                    or status.freshness.read_id == command_id or balance.freshness.read_id == command_id
                    or status.freshness.network_at < at or balance.freshness.network_at < at):
                raise ValueError("independent_fresh_readback_required")
            reason = {State.LEADING: "BID_VERIFIED", State.OUTBID: "BID_VERIFIED", State.WON: "WON_VERIFIED", State.LOST: "LOST_VERIFIED"}.get(status.state)
            if not reason or status.state in {State.LEADING, State.OUTBID, State.WON} and status.current_bid < row[3]:
                raise ValueError("outcome_still_unknown")
            # A later outbid/terminal state permits a NEW intent; never retry the
            # previous amount or infer held/refunded coins from the write ACK.
            self.db.execute("UPDATE commands SET state='RECONCILED' WHERE id=?", (command_id,))
            self._event(scope, reason, {"state": status.state.value, "spendable": balance.spendable,
                        "held": balance.held, "paid": status.paid, "read_id": status.freshness.read_id}, identity.trade_id, command_id)

    def trace(self, *, scope=None, trade_id=None):
        clauses, args = [], []
        if scope is not None:
            clauses.append("scope=?")
            args.append(token(scope))
        if trade_id is not None:
            clauses.append("trade_id=?")
            args.append(token(trade_id, "trade"))
        query = "SELECT seq,version,at,scope,trade_id,command_id,reason,data FROM events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        # Sequence is authoritative chronology even when wall time moves back.
        return [dict(zip(("seq", "version", "at", "scope", "trade_id", "command_id", "reason", "data"),
                         (*row[:-1], payload(json.loads(row[-1]))))) for row in self.db.execute(query+" ORDER BY seq", args)]


def main():
    parser = argparse.ArgumentParser(description="Sanitized chronological bidding-v1 trace")
    parser.add_argument("database")
    parser.add_argument("--scope")
    parser.add_argument("--trade-id")
    args = parser.parse_args()
    journal = Journal(args.database, readonly=True)
    try:
        print(json.dumps(journal.trace(scope=args.scope, trade_id=args.trade_id)))
    finally:
        journal.close()


if __name__ == "__main__":
    main()
