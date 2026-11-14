"""Pure decisions and finite queue ingestion; deliberately no actor services."""
from dataclasses import dataclass
from .contracts import AuctionStatus, Balance, Identity, Snapshot, State, integer, token
from .rules import minimum_bid
from . import capacity as slots


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
    def __init__(self, *, capacity=50, reserve=5000, journal=None, scope=None, pipeline_capacity=50):
        self.capacity = integer(capacity, 1)
        if capacity > 50:
            raise ValueError("maximum_50")
        self.pipeline_capacity = integer(pipeline_capacity, 1)
        if pipeline_capacity > 50:
            raise ValueError("maximum_50")
        self.reserve = integer(reserve)
        self.journal, self.scope = journal, scope
        self.entries, self.draining = {}, False
        self.identities, self.reservations, self.invalid_balances = {}, {}, set()
        self.pending_resale = {}
        if journal is not None:
            token(scope)
            # Replay only policy events. Status snapshots are supplied afresh.
            for event in journal.trace(scope=scope):
                if event["reason"] == "ENROLLED":
                    trade, data = event["trade_id"], event["data"]
                    self.entries[trade] = None
                    self.identities[trade] = Identity(trade, data["item_id"], data["definition_id"])
                    self.reservations[trade] = (data["amount"], data["balance_read_id"], data["status_read_id"])
                elif event['reason'] == 'INTENT_DURABLE' and event['trade_id'] not in self.entries:
                    trade, data = event['trade_id'], event['data']
                    self.entries[trade] = None
                    self.identities[trade] = Identity(trade, data['item_id'], data['definition_id'])
                elif event["reason"] in {"WON_VERIFIED", "LOST_VERIFIED"}:
                    identity = self.identities.get(event['trade_id'])
                    if event['reason'] == 'WON_VERIFIED' and identity:
                        self.pending_resale[event['trade_id']] = identity
                    self.entries.pop(event["trade_id"], None)
                    self.identities.pop(event["trade_id"], None)
                    self._release(event["trade_id"])
                elif event["reason"] == "RESERVATION_RELEASED":
                    self._release(event["trade_id"])
                elif event["reason"] in {"DRAINING", "DRAINED"}:
                    self.draining = event["reason"] == "DRAINING"
            # Include durable orphan intents recovered from pre-ledger journals.
            if slots.installed(journal):
                self.pending_resale = {}
                for trade, item, definition, phase in journal.db.execute(
                        'SELECT trade_id,item_id,definition_id,phase FROM capacity_slots_v1 WHERE scope=?', (scope,)):
                    if phase == 'UNRESOLVED':
                        self.entries.setdefault(trade, None)
                        self.identities[trade] = Identity(trade, item, definition)
                    elif phase in {'PENDING_RESALE', 'RESALE_UNKNOWN'}:
                        self.pending_resale[trade] = Identity(trade, item, definition)

    def _record(self, reason, trade_id=None, data=None):
        if self.journal:
            if self.journal.db.in_transaction:
                self.journal._event(self.scope, reason, data, trade_id)
            else:
                self.journal.record(self.scope, reason, data, trade_id=trade_id)

    def _release(self, trade_id):
        reservation = self.reservations.pop(trade_id, None)
        if reservation:
            self.invalid_balances.add(reservation[1])

    def reserve_check(self, balance, *, now, amount=0, new_cycle=False):
        """Coin gate, independent of capacity. Only a future cycle may reset it.

        Terminal readback never resets DRAINING. Replay and the reserve decision
        share a transaction so another process cannot enroll between them.
        """
        integer(amount)
        if self.journal:
            with self.journal.transaction():
                current = AuctionQueue(capacity=self.capacity, reserve=self.reserve,
                    journal=self.journal, scope=self.scope, pipeline_capacity=self.pipeline_capacity)
                reason = current._reserve_check(balance, now=now, amount=amount, new_cycle=new_cycle)
            self.__dict__.update(current.__dict__)
            return reason
        return self._reserve_check(balance, now=now, amount=amount, new_cycle=new_cycle)

    def _reserve_check(self, balance, *, now, amount=0, new_cycle=False):
        if not balance.freshness.fresh(now) or balance.freshness.read_id in self.invalid_balances:
            return 'DRAINING' if self.draining else 'STALE'
        available = balance.spendable-sum(v[0] for v in self.reservations.values())
        evidence = dict(spendable=max(0, available), amount=amount, target=self.reserve,
            balance_read_id=balance.freshness.read_id)
        if self.draining:
            if not new_cycle or self.entries or available <= self.reserve:
                return 'DRAINING'
            self._record('DRAINED', data=evidence)
            self.draining = False
        if available <= self.reserve or available-amount < self.reserve:
            self._record('DRAINING', data=evidence)
            self.draining = True
            return 'DRAINING'
        return None

    def admit(self, status, balance, amount, *, now, account_capacity=None):
        if self.journal:
            # Never trust a process-local queue/count while admitting. Serialize
            # replay, both prospective limits, ENROLLED and the slot in one commit.
            with self.journal.transaction():
                current = AuctionQueue(capacity=self.capacity, reserve=self.reserve,
                    journal=self.journal, scope=self.scope, pipeline_capacity=self.pipeline_capacity)
                reason = current._admit(status, balance, amount, now=now, account_capacity=account_capacity)
            self.__dict__.update(current.__dict__)
            return reason
        return self._admit(status, balance, amount, now=now, account_capacity=account_capacity)

    def _admit(self, status, balance, amount, *, now, account_capacity=None):
        integer(amount, 1)
        trade = status.identity.trade_id
        if trade in self.entries or trade in self.pending_resale:
            return "PENDING"
        if not status.freshness.fresh(now) or not balance.freshness.fresh(now) or balance.freshness.read_id in self.invalid_balances or status.state not in {State.ACTIVE, State.OUTBID} or status.deadline <= now:
            return "STALE"
        reserve_reason = self._reserve_check(balance, now=now, amount=amount)
        if reserve_reason:
            return reserve_reason
        available = balance.spendable-sum(v[0] for v in self.reservations.values())
        if account_capacity is not None:
            integer(account_capacity, 1)
        limit = min(self.capacity, account_capacity) if account_capacity is not None else self.capacity
        if len(self.entries) >= limit:
            return "QUEUE_FULL"
        if self.journal:
            if self.journal.db.execute('SELECT 1 FROM capacity_slots_v1 WHERE scope=? AND trade_id=?',
                    (self.scope, trade)).fetchone():
                return 'PENDING'
            capacity = slots.status(self.journal, self.scope, now=now)
            if not capacity['fresh']:
                return 'CAPACITY_UNKNOWN'
            if capacity['unresolved'] + 1 > limit:
                return 'QUEUE_FULL'
            if capacity['total'] + 1 > self.pipeline_capacity:
                return 'PIPELINE_FULL'
            if self.journal.db.execute("SELECT 1 FROM capacity_slots_v1 WHERE scope=? AND item_id=? "
                    "AND phase NOT IN ('LOST','RELEASED')", (self.scope, status.identity.item_id)).fetchone():
                return 'CAPACITY_IDENTITY_CONFLICT'
            inventory = slots._inventory(self.journal, self.scope)
            if any(i[0] == status.identity.item_id for i in inventory[2]):
                return 'CAPACITY_IDENTITY_CONFLICT'
        elif len(self.entries)+len(self.pending_resale)+1 > self.pipeline_capacity:
            return 'PIPELINE_FULL'
        data = {"amount": amount, "balance_read_id": balance.freshness.read_id,
                "status_read_id": status.freshness.read_id, "item_id": status.identity.item_id,
                "definition_id": status.identity.definition_id}
        will_drain = available-amount == self.reserve
        if self.journal:
            events = [("ENROLLED", data, trade, None)]
            if will_drain:
                events.append(("DRAINING", dict(spendable=available, amount=amount,
                    target=self.reserve, balance_read_id=balance.freshness.read_id), None, None))
            for reason, value, tid, cid in events:
                self.journal._event(self.scope, reason, value, tid, cid)
        self.entries[trade] = status
        self.identities[trade] = status.identity
        self.reservations[trade] = (amount, balance.freshness.read_id, status.freshness.read_id)
        if will_drain:
            self.draining = True
        return "ENROLLED"

    def refresh(self, snapshot: Snapshot, *, now, reset_draining=False):
        if self.journal:
            with self.journal.transaction():
                current = AuctionQueue(capacity=self.capacity, reserve=self.reserve,
                    journal=self.journal, scope=self.scope, pipeline_capacity=self.pipeline_capacity)
                result = current._refresh(snapshot, now=now, reset_draining=reset_draining)
            self.__dict__.update(current.__dict__)
            return result
        return self._refresh(snapshot, now=now, reset_draining=reset_draining)

    def _refresh(self, snapshot: Snapshot, *, now, reset_draining=False):
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
            if self.journal and row.state in {State.WON, State.LOST}:
                # Terminal proof must follow the admission/latest possible bid;
                # a still-fresh pre-dispatch read cannot settle a later write.
                checkpoint = self.journal.db.execute('SELECT intended_at,status_read_id FROM commands '
                    'WHERE scope=? AND trade_id=? ORDER BY rowid DESC LIMIT 1', (self.scope, trade)).fetchone()
                if not checkpoint:
                    checkpoint = self.journal.db.execute("SELECT at,json_extract(data,'$.status_read_id') FROM events "
                        "WHERE scope=? AND trade_id=? AND reason='ENROLLED' ORDER BY seq DESC LIMIT 1", (self.scope, trade)).fetchone()
                if checkpoint:
                    from datetime import datetime
                    if row.freshness.read_id == checkpoint[1] or row.freshness.network_at < datetime.fromisoformat(checkpoint[0]):
                        resolved[trade] = State.UNKNOWN
                        continue
            resolved[trade] = row.state
            if row.state in {State.WON, State.LOST}:
                self._record("WON_VERIFIED" if row.state == State.WON else "LOST_VERIFIED", trade,
                    {"state": row.state.value, "paid": row.paid, "item_id": row.identity.item_id,
                     "definition_id": row.identity.definition_id, "read_id": row.freshness.read_id})
                del self.entries[trade]
                del self.identities[trade]
                self._release(trade)
                if row.state == State.WON:
                    if not self.journal or self.journal.db.execute("SELECT phase FROM capacity_slots_v1 WHERE scope=? AND trade_id=?",
                            (self.scope, trade)).fetchone() == ('PENDING_RESALE',):
                        self.pending_resale[trade] = row.identity
            else:
                self.entries[trade] = row
                reservation = self.reservations.get(trade)
                if reservation and row.state in {State.LEADING, State.OUTBID} and row.freshness.read_id != reservation[2]:
                    self._record("RESERVATION_RELEASED", trade)
                    self._release(trade)
        # Missing rows remain unresolved even if coverage claims complete.
        # Kept as a compatibility keyword; even an explicit reset_draining=True
        # cannot replace a subsequent cycle's fresh reserve check.
        return resolved

    def deadlines(self):
        return sorted((s for s in self.entries.values() if s is not None), key=lambda s: (s.deadline, s.identity.trade_id))
