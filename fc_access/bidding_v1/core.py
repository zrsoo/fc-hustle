"""Pure decisions and finite queue ingestion; deliberately no actor services."""
from dataclasses import dataclass
from .contracts import AuctionStatus, Balance, Identity, Snapshot, State, integer, token
from .rules import minimum_bid


@dataclass(frozen=True)
class Decision:
    reason: str
    amount: int | None = None


def decide(status, balance, rules, cap, *, now, pending=False, max_age=30):
    integer(cap, 1)
    if pending or status.state == State.PENDING:
        return Decision("PENDING")
    if not status.freshness.fresh(now, max_age) or not balance.freshness.fresh(now, max_age):
        return Decision("STALE")
    if status.state == State.LEADING:
        return Decision("HOLD")
    if status.state not in {State.ACTIVE, State.OUTBID}:
        return Decision("UNKNOWN" if status.state == State.UNKNOWN else "SKIP")
    if status.deadline <= now:
        return Decision("EXPIRED")
    amount = minimum_bid(status, rules)
    if amount is None or amount > cap or status.buy_now_price and amount >= status.buy_now_price:
        return Decision("OVER_CAP")
    # Spendable excludes held funds. Do not invent refunds from previous bids.
    if balance.spendable < amount:
        return Decision("INSUFFICIENT_BALANCE")
    return Decision("OPENING" if status.current_bid == 0 else "REBID", amount)


class AuctionQueue:
    def __init__(self, *, capacity=50, reserve=5000, journal=None, scope=None):
        self.capacity = integer(capacity, 1)
        if capacity > 50:
            raise ValueError("maximum_50")
        self.reserve = integer(reserve)
        self.journal, self.scope = journal, scope
        self.entries, self.draining = {}, False
        self.identities, self.reservations, self.invalid_balances = {}, {}, set()
        if journal is not None:
            token(scope)
            # Replay only policy events. Status snapshots are supplied afresh.
            for event in journal.trace(scope=scope):
                if event["reason"] == "ENROLLED":
                    trade, data = event["trade_id"], event["data"]
                    self.entries[trade] = None
                    self.identities[trade] = Identity(trade, data["item_id"], data["definition_id"])
                    self.reservations[trade] = (data["amount"], data["balance_read_id"], data["status_read_id"])
                elif event["reason"] in {"WON_VERIFIED", "LOST_VERIFIED"}:
                    self.entries.pop(event["trade_id"], None)
                    self.identities.pop(event["trade_id"], None)
                    self._release(event["trade_id"])
                elif event["reason"] == "RESERVATION_RELEASED":
                    self._release(event["trade_id"])
                elif event["reason"] in {"DRAINING", "DRAINED"}:
                    self.draining = event["reason"] == "DRAINING"

    def _record(self, reason, trade_id=None, data=None):
        if self.journal:
            self.journal.record(self.scope, reason, data, trade_id=trade_id)

    def _release(self, trade_id):
        reservation = self.reservations.pop(trade_id, None)
        if reservation:
            self.invalid_balances.add(reservation[1])

    def admit(self, status, balance, amount, *, now, account_capacity=None):
        integer(amount, 1)
        trade = status.identity.trade_id
        if trade in self.entries:
            return "PENDING"
        if not status.freshness.fresh(now) or not balance.freshness.fresh(now) or balance.freshness.read_id in self.invalid_balances or status.state not in {State.ACTIVE, State.OUTBID} or status.deadline <= now:
            return "STALE"
        if self.draining:
            return "DRAINING"
        available = balance.spendable-sum(v[0] for v in self.reservations.values())
        if available <= self.reserve or available-amount < self.reserve:
            self._record("DRAINING")
            self.draining = True
            return "DRAINING"
        if account_capacity is not None:
            integer(account_capacity, 1)
        limit = min(self.capacity, account_capacity) if account_capacity is not None else self.capacity
        if len(self.entries) >= limit:
            return "QUEUE_FULL"
        data = {"amount": amount, "balance_read_id": balance.freshness.read_id,
                "status_read_id": status.freshness.read_id, "item_id": status.identity.item_id,
                "definition_id": status.identity.definition_id}
        will_drain = available-amount == self.reserve
        if self.journal:
            events = [("ENROLLED", data, trade, None)]
            if will_drain:
                events.append(("DRAINING", {}, None, None))
            self.journal.record_batch(self.scope, events)
        self.entries[trade] = status
        self.identities[trade] = status.identity
        self.reservations[trade] = (amount, balance.freshness.read_id, status.freshness.read_id)
        if will_drain:
            self.draining = True
        return "ENROLLED"

    def refresh(self, snapshot: Snapshot, *, now):
        # Duplicates do not count as coverage; conflicting copies are UNKNOWN.
        groups = {}
        for row in snapshot.auctions:
            groups.setdefault(row.identity.trade_id, []).append(row)
        resolved = {}
        for trade in list(self.entries):
            rows = groups.get(trade, [])
            row = rows[0] if rows and all(r == rows[0] for r in rows) else None
            if (not row or not snapshot.freshness.fresh(now) or not row.freshness.fresh(now)
                    or row.identity != self.identities[trade]):
                resolved[trade] = State.UNKNOWN
                continue
            resolved[trade] = row.state
            if row.state in {State.WON, State.LOST}:
                self._record("WON_VERIFIED" if row.state == State.WON else "LOST_VERIFIED", trade)
                del self.entries[trade]
                del self.identities[trade]
                self._release(trade)
            else:
                self.entries[trade] = row
                reservation = self.reservations.get(trade)
                if reservation and row.state in {State.LEADING, State.OUTBID} and row.freshness.read_id != reservation[2]:
                    self._record("RESERVATION_RELEASED", trade)
                    self._release(trade)
        # Missing rows remain unresolved even if coverage claims complete.
        if self.draining and not self.entries:
            self._record("DRAINED")
            self.draining = False
        return resolved

    def deadlines(self):
        return sorted((s for s in self.entries.values() if s is not None), key=lambda s: (s.deadline, s.identity.trade_id))
