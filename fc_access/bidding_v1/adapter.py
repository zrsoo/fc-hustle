"""Versioned host adapter over an injected reviewed page executor.

Executor.attach/execute/reconciled map directly to window.__fcBiddingV1. The
executor is supplied by the caller; no browser attachment or actor is started.
"""
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
import math
from typing import Protocol

from fc_access.harness import validate_result
from fc_access.pricing import MarketKey
from .contracts import (AuctionStatus, Balance, BidIntent, BidResult, Coverage, Freshness,
                        Identity, Outcome, Search, Snapshot, State, instant, token)
from .core import decide
from .rules import estimate_cap


class PageExecutor(Protocol):
    def attach(self, scope: str, owner: str, epoch: int) -> bool: ...
    def execute(self, command: dict) -> dict: ...
    def reconciled(self, scope: str, owner: str, epoch: int, evidence_key: str, trade_id: str) -> bool: ...


def parse_response(value, *, command_id, operation):
    if (not isinstance(value, dict) or set(value) != {"schema", "command_id", "operation", "result", "freshness", "coverage", "timing"}
            or type(value["schema"]) is not int or value["schema"] != 1 or value["command_id"] != command_id or value["operation"] != operation):
        raise ValueError("invalid_response_correlation")
    token(command_id)
    result = value["result"]
    # Reuse the historical strict projection; only two new sanitized routes.
    network = result.get("network") if isinstance(result, dict) else None
    if not isinstance(network, list):
        raise ValueError("invalid_network")
    compatible = []
    allowed = {"search": {"/ut/game/fc27/transfermarket"}, "watched": {"/ut/game/fc27/watchlist"},
               "balance": {"/ut/game/fc27/user/currencies"}, "bid": {"/ut/game/fc27/trade/:trade/bid"}}
    for row in network:
        if not isinstance(row, dict) or row.get("path") not in allowed[operation]:
            raise ValueError("wrong_network_operation")
        compatible.append(row | {"path": "/ut/game/fc27/transfermarket"})
    validate_result(result | {"network": compatible})
    fresh = value["freshness"]
    if not isinstance(fresh, dict) or set(fresh) != {"observed_at", "network_at", "request_count", "read_id", "source"}:
        raise ValueError("invalid_freshness")
    freshness = Freshness(datetime.fromisoformat(fresh["observed_at"]),
                          datetime.fromisoformat(fresh["network_at"]) if fresh["network_at"] else None,
                          fresh["request_count"], fresh["read_id"], fresh["source"])
    if freshness.read_id != command_id or freshness.request_count != len(network):
        raise ValueError("invalid_network_count")
    if freshness.network_at is not None and not any(n["session_header_present"] and 200 <= n["status"] < 300 for n in network):
        raise ValueError("unsupported_network_freshness")
    if not isinstance(value["coverage"], dict):
        raise ValueError("invalid_coverage")
    coverage = Coverage(**value["coverage"])
    timing = value["timing"]
    if not isinstance(timing, dict) or set(timing) != {"native_service_ms"} or type(timing["native_service_ms"]) not in (int, float) or not math.isfinite(timing["native_service_ms"]) or timing["native_service_ms"] < 0:
        raise ValueError("invalid_timing")
    if result["success"] and result["platform"] != "pc":
        raise ValueError("wrong_persona")
    return result, freshness, coverage


def snapshot(result, freshness, coverage):
    if not result["success"] or result["auctions"] is None:
        raise ValueError("read_failed")
    rows = []
    for row in result["auctions"]:
        identity = Identity(row["trade_id"], row["item"]["item_id"], row["item"]["definition_id"])
        state = State.UNKNOWN
        if row["trade_state"] == "active" and row["expires"] is not None and row["expires"] > 0:
            state = {"highest": State.LEADING, "outbid": State.OUTBID, "none": State.ACTIVE}.get(row["bid_state"], State.UNKNOWN)
        elif row["trade_state"] in {"closed", "expired"} and row["bid_state"] == "outbid":
            state = State.LOST
        # Closed/highest is pending independent owned-item and paid readbacks.
        elif row["trade_state"] in {"closed", "expired"} and row["bid_state"] == "highest":
            state = State.PENDING
        rows.append(AuctionStatus(identity, state, row["starting_bid"], row["current_bid"], row["buy_now_price"],
                                  (freshness.network_at or freshness.observed_at)+timedelta(seconds=max(0, row["expires"] or 0)), freshness))
    return Snapshot(tuple(rows), freshness, coverage)


class NativeAdapter:
    def __init__(self, executor, journal, provider, *, scope, owner, evidence_key, now, fixture=False):
        if type(fixture) is not bool:
            raise ValueError("invalid_fixture_mode")
        self.fixture = fixture
        self.executor, self.journal, self.provider, self.now = executor, journal, provider, now
        self.scope, self.owner, self.evidence_key = token(scope), token(owner), token(evidence_key)
        self.epoch = journal.session(scope, owner)
        if executor.attach(scope, owner, self.epoch) is not True:
            journal.record(scope, "LIFECYCLE_ERROR", {"epoch": self.epoch})
            raise ValueError("attachment_failed")

    def envelope(self, command_id, operation, params):
        return {"schema": 1, "id": token(command_id), "operation": operation, "params": params,
                "scope": self.scope, "owner": self.owner, "epoch": self.epoch, "evidence_key": self.evidence_key}

    def _read(self, command_id, operation, params):
        try:
            response = self.executor.execute(self.envelope(command_id, operation, params))
            result = parse_response(response, command_id=command_id, operation=operation)
            if result[1].source != ("fixture" if self.fixture else "native"):
                raise ValueError("wrong_evidence_source")
            self.journal.record(self.scope, "READ_OBSERVED", {"read_id": command_id,
                "source": result[1].source, "request_count": result[1].request_count,
                "native_service_ms": response["timing"]["native_service_ms"]}, command_id=command_id)
            return result
        except Exception:
            self.journal.record(self.scope, "LIFECYCLE_ERROR", {"epoch": self.epoch}, command_id=command_id)
            raise

    def search(self, command_id, query: Search):
        if not isinstance(query, Search):
            raise ValueError("invalid_search")
        return snapshot(*self._read(command_id, "search", {k: v for k, v in asdict(query).items() if v is not None}))

    def watched(self, command_id):
        # Exactly one native bulk invocation; missing entries are never LOST.
        return snapshot(*self._read(command_id, "watched", {}))

    def balance(self, command_id):
        result, freshness, _ = self._read(command_id, "balance", {})
        if not result["success"] or result["credits"] is None:
            raise ValueError("balance_unavailable")
        value = Balance(result["credits"], None, freshness)
        self.journal.record(self.scope, "BALANCE_OBSERVED", {"read_id": command_id, "spendable": value.spendable, "held": value.held})
        return value

    def bid_once(self, intent, status, balance, rules, *, observations, X=500):
        if not isinstance(intent, BidIntent) or (intent.scope, intent.owner, intent.epoch) != (self.scope, self.owner, self.epoch):
            raise ValueError("unowned_intent")
        self.provider.validate(rules, key=MarketKey(intent.identity.definition_id, intent.identity.platform), now=self.now())
        if not self.fixture and (rules.provenance.classification != "LIVE_VERIFIED" or
                status.freshness.source != "native" or balance.freshness.source != "native"):
            raise ValueError("native_write_requires_live_rules_and_reads")
        if (intent.identity != status.identity or intent.status_read_id != status.freshness.read_id
                or intent.balance_read_id != balance.freshness.read_id or instant(intent.deadline) > instant(status.deadline)):
            raise ValueError("intent_snapshot_mismatch")
        decision = decide(status, balance, rules, intent.cap, now=self.now())
        if decision.amount != intent.amount:
            self.journal.record(self.scope, decision.reason, trade_id=status.identity.trade_id)
            raise ValueError("bid_not_eligible")
        if not isinstance(observations, (list, tuple)) or len(observations) > 100:
            raise ValueError("bounded_comparables_required")
        estimate, cap = estimate_cap(status, observations, rules, self.provider, now=self.now(), X=X)
        if cap is None or intent.cap > cap:
            raise ValueError("unsupported_profitable_cap")
        def pseudonym(value, namespace):
            try:
                return token(value, namespace)
            except ValueError:
                return namespace+":"+hashlib.sha256(f"{self.evidence_key}|{namespace}|{value}".encode()).hexdigest()[:24]

        inputs = [{"trade_id": pseudonym(o.trade_id, "trade"), "item_id": pseudonym(o.item_id, "item"),
                   "definition_id": o.key.definition_id, "platform": o.key.platform, "ask": o.buy_now_price,
                   "at": instant(o.observed_at).isoformat(), "expires": o.expires, "active": o.active,
                   "network_fresh": o.network_fresh} for o in observations]
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        data = {"spendable": balance.spendable, "held": balance.held, "rules_digest": rules.provenance.sha256,
                "pricing_digest": digest, "target": estimate.target_sale_price, "tax": estimate.tax,
                "profit_threshold": X, "samples": estimate.sample_count,
                "expected_profit": estimate.target_sale_price-estimate.tax-intent.amount, "comparables": inputs}
        self.journal.record(self.scope, decision.reason, {"amount": intent.amount, "cap": intent.cap}, trade_id=status.identity.trade_id)
        self.journal.intend(intent, data)

        def send():
            p = {"trade_id": intent.identity.trade_id, "item_id": intent.identity.item_id,
                 "definition_id": intent.identity.definition_id, "amount": intent.amount, "minimum": intent.amount,
                 "cap": intent.cap, "deadline": instant(intent.deadline).isoformat()}
            try:
                response = self.executor.execute(self.envelope(intent.command_id, "bid", p))
                result, freshness, _ = parse_response(response, command_id=intent.command_id, operation="bid")
                if freshness.source != ("fixture" if self.fixture else "native"):
                    raise ValueError("wrong_evidence_source")
                # Already inside dispatch's transaction: retain latency and ACK
                # atomically. A crash rolls these back, preserving UNKNOWN.
                self.journal._event(self.scope, "NATIVE_TIMING", {"native_service_ms": response["timing"]["native_service_ms"],
                    "request_count": freshness.request_count, "source": freshness.source}, intent.identity.trade_id, intent.command_id)
            except (ValueError, TypeError, KeyError):
                return BidResult(intent.command_id, Outcome.UNKNOWN, "INVALID_RESULT")
            return BidResult(intent.command_id, Outcome.ACKNOWLEDGED if result["success"] else Outcome.UNKNOWN,
                             "NATIVE_ACK" if result["success"] else "TIMEOUT" if result["error"] == "service_timeout" else "SERVICE_ERROR")

        return self.journal.dispatch(intent, send)

    def reconcile(self, command_id, status, balance):
        self.journal.reconcile(command_id, scope=self.scope, owner=self.owner, epoch=self.epoch,
                               status=status, balance=balance)
        if self.executor.reconciled(self.scope, self.owner, self.epoch, self.evidence_key, status.identity.trade_id) is not True:
            self.journal.record(self.scope, "LIFECYCLE_ERROR", {"epoch": self.epoch})
            raise ValueError("page_reconciliation_unlock_failed")
