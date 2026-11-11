"""One purchase-to-list experiment. A persisted intent is never submitted twice.

The journal contains only allowlisted projections and stable per-run pseudonyms.
It is transaction evidence, not credentials. Unit fixtures never use its live path.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import secrets
import time
import urllib.request

from .harness import (ROOT, EdgeTransport, DirectHTTPTransport, command as read_command,
                      empty_result, integer, opener, utc, validate_result)

DIRECTORY = ROOT / "docs/research/transaction"
JOURNAL = DIRECTORY / "live.json"
WRITES = {"buy", "move", "list", "relist"}
METHODS = {"buy": "services.Item.bid(item, buyNowPrice)",
           "move": "services.Item.move([item], ItemPile.TRANSFER, false)",
           "list": "services.Item.list(item, startingBid, buyNowPrice, duration)",
           "relist": "services.Item.list(expiredItem, startingBid, buyNowPrice, duration)",
           "status": "services.Item.requestTransferItems()"}


def command(operation, params):
    if operation not in WRITES | {"status"}:
        return read_command(operation, params)
    fields = {"buy": {"item_id", "trade_id", "definition_id", "buy_now_price"},
              "move": {"item_id", "definition_id"},
              "list": {"item_id", "definition_id", "starting_bid", "buy_now_price", "duration"},
              "relist": {"item_id", "definition_id", "starting_bid", "buy_now_price", "duration"},
              "status": set()}[operation]
    if not isinstance(params, dict) or set(params) != fields:
        raise ValueError("invalid_command")
    for key, value in params.items():
        if key in {"item_id", "trade_id"}:
            if not isinstance(value, str) or not re.fullmatch(("item" if key == "item_id" else "trade") + r":[a-f0-9]{24}", value):
                raise ValueError("invalid_command")
        elif not integer(value, 1):
            raise ValueError("invalid_command")
    if operation == "buy" and not 200 <= params["buy_now_price"] <= 500:
        raise ValueError("invalid_command")
    if operation in {"list", "relist"} and not (params["duration"] == 3600 and
            150 <= params["starting_bid"] < params["buy_now_price"] <= 1000 and
            params["starting_bid"] % 50 == params["buy_now_price"] % 50 == 0):
        raise ValueError("invalid_command")
    return {"operation": operation, "params": params.copy()}


def fresh(attempt, op):
    r = attempt["result"]
    route = {"coins": "user/credits", "unassigned": "purchased/items", "transfer_list": "tradepile", "status": "tradepile", "search": "transfermarket"}[op]
    routes = {route} | ({"user/currencies", "usermassinfo"} if op == "coins" else set())
    return r["success"] and r["platform"] is not None and any(
        n["path"].removeprefix("/ut/game/fc27/") in routes and n["session_header_present"] and
        200 <= n["status"] < 300 for n in r["network"])


class TransactionTransport(EdgeTransport):
    def __init__(self):
        super().__init__(8768)

    def read(self, operation, params, evidence_key):
        body = command(operation, params) | {"evidence_key": evidence_key}
        try:
            with opener().open(self.base + "/health", timeout=3) as response:
                health = json.load(response)
            if health != {"service": "fc-transaction-bridge-v3", "protocol": 3, "bind": "127.0.0.1", "attached": True}:
                return empty_result("bridge_not_attached")
            request = urllib.request.Request(self.base + "/run", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with opener().open(request, timeout=70) as response:
                return validate_result(json.loads(response.read(262144)))
        except (OSError, ValueError, TypeError):
            # On writes this is ambiguous. The runner always reconciles it.
            return empty_result("bridge_unavailable")


class Experiment:
    def __init__(self, transport, path=JOURNAL):
        self.transport, self.path = transport, Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.record = json.loads(self.path.read_text(encoding="utf-8"))
            if not self.record["intents"] and self.record["attempts"]:
                previous = self.path.read_bytes()
                archive = self.path.with_name("preflight-" + hashlib.sha256(previous).hexdigest()[:12] + ".json")
                archive.write_bytes(previous)
                self.record = None
        else:
            self.record = None
        if self.record is None:
            self.record = {"schema": 1, "source": "fc-one-shot-transaction", "created_at": utc(),
                           "evidence_key": secrets.token_hex(16), "status": "PARTIAL/BLOCKED",
                           "attempts": [], "intents": {}, "selection": None, "listing": None,
                           "errors": [], "relist": "UNVERIFIED", "transport": {
                               "selected": "edge", "decision": "FINAL", "direct_http": "UNVERIFIED",
                               "reason": "Observed direct_session_provider_unavailable; prior authenticated native reads. Use the native bridge; essential writes remain UNVERIFIED pending live proof. No comparison purchase."},
                           "recovery": ["Start python -m fc_access.transaction_server and attach the reviewed browser/transaction-bridge extension to the existing official EA tab.",
                                        "Run python -m fc_access.transaction once. It buys at most one player for 200-500 coins and lists that physical item for one hour.",
                                        "Preserve every write intent; none is redispatched. Restarts first reconcile inventory, transfer list, coins and status. Only an acknowledged buy with fresh matching physical item and exact original debit may continue unwritten move/list stages. Missing buy responses or later-stage intents remain reconciliation-only. Never repeat a purchase or listing on timeout."]}
            self.save()

    def save(self):
        self.record["updated_at"] = utc()
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.record, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    def call(self, operation, params=None, phase="preflight"):
        params = {} if params is None else params
        command(operation, params)
        if operation in WRITES:
            if operation in self.record["intents"]:
                raise ValueError("write_already_intended_reconciliation_required")
            self.record["intents"][operation] = {"at": utc(), "request": params.copy(), "phase": phase}
            self.save()  # Durable intent precedes dispatch, even if no response arrives.
        start = time.perf_counter()
        attempt = {"at": utc(), "phase": phase, "operation": operation, "request": params.copy()}
        from .harness import METHODS as READ_METHODS
        attempt["method"] = METHODS[operation] if operation in METHODS else READ_METHODS[operation]
        try:
            attempt["result"] = validate_result(self.transport.read(operation, params, self.record["evidence_key"]))
        except Exception:
            attempt["result"] = empty_result("internal_error")
        attempt["elapsed_ms"] = round(1000 * (time.perf_counter() - start), 3)
        self.record["attempts"].append(attempt)
        self.save()
        return attempt

    def snapshot(self, phase):
        # These are separate service calls, never values echoed by a write response.
        return {op: self.call(op, phase=phase) for op in ("unassigned", "transfer_list", "coins")}

    def stop(self, error):
        self.record["errors"].append({"at": utc(), "error": error})
        self.record["status"] = "PARTIAL/BLOCKED"
        self.save()
        return self.record

    def run(self):
        if self.record["status"] == "VERIFIED":
            return self.record
        if "direct_probe" not in self.record:
            self.record["direct_probe"] = DirectHTTPTransport().read("coins", {}, self.record["evidence_key"])
            self.save()
        if self.record["intents"]:
            reconciled = self.snapshot("restart_reconciliation")
            self.call("status", phase="restart_reconciliation")
            # Continue only unwritten stages for the already acquired physical
            # item, after a full fresh readback and exact original coin delta.
            # A missing buy response remains reconciliation-only.
            buys = [a for a in self.record["attempts"] if a["operation"] == "buy"]
            if set(self.record["intents"]) == {"buy"} and len(buys) == 1 and self.record["selection"]:
                before = {op: next(a for a in self.record["attempts"] if a["phase"] == "before_buy" and a["operation"] == op) for op in reconciled}
                return self.complete_acquired(before, reconciled, self.record["selection"])
            return self.stop("prior_write_intent_reconciled_no_automatic_retry; inspect owned item and listing before recovery")
        before = self.snapshot("before_buy")
        if not all(fresh(a, op) for op, a in before.items()):
            return self.stop("prepurchase_fresh_account_reads_unavailable")
        market = self.call("search", {"max_buy": 500, "page": 1, "count": 21, "fresh": True})
        if not fresh(market, "search"):
            return self.stop("fresh_low_cost_market_search_unavailable")
        rows = market["result"]["auctions"] or []
        owned = {r["item_id"] for r in before["unassigned"]["result"]["items"] or []} | {
            r["item"]["item_id"] for r in before["transfer_list"]["result"]["auctions"] or []}
        def eligible(rows, expires):
            return [r for r in rows if r["item"]["item_id"] not in owned and r["item"]["untradeable"] is False
                    and r["item"]["definition_id"] and r["item"]["item_id"] and r["trade_id"] and
                    r["trade_state"] == "active" and (r["expires"] or 0) > expires and
                    200 <= (r["buy_now_price"] or 0) <= min(500, before["coins"]["result"]["credits"] or 0)]
        seeds = eligible(rows, 0)
        if not seeds:
            return self.stop("no_inexpensive_tradeable_player_with_complete_identity")
        seed = min(seeds, key=lambda r: (r["buy_now_price"], r["trade_id"]))
        exact = self.call("search", {"definition_id": seed["item"]["definition_id"], "max_buy": seed["buy_now_price"], "page": 1, "count": 21, "fresh": True}, "exact_match")
        matching = [r for r in eligible(exact["result"]["auctions"] or [], 90) if
                    r["item"]["definition_id"] == seed["item"]["definition_id"] and r["buy_now_price"] <= seed["buy_now_price"]]
        if not fresh(exact, "search") or not matching:
            return self.stop("exact_card_version_low_cost_auction_with_sufficient_expiry_unavailable")
        chosen = min(matching, key=lambda r: (r["buy_now_price"], r["trade_id"]))
        self.record["selection"] = chosen
        self.save()
        target = {"item_id": chosen["item"]["item_id"], "definition_id": chosen["item"]["definition_id"]}
        self.call("buy", target | {"trade_id": chosen["trade_id"], "buy_now_price": chosen["buy_now_price"]}, "buy")
        after = self.snapshot("after_buy")  # Also runs after timeout, error or malformed response.
        return self.complete_acquired(before, after, chosen)

    def complete_acquired(self, before, after, chosen):
        """Never submits a purchase; only completes unwritten move/list stages."""
        target = {"item_id": chosen["item"]["item_id"], "definition_id": chosen["item"]["definition_id"]}
        inventory = (after["unassigned"]["result"]["items"] or []) + [r["item"] for r in after["transfer_list"]["result"]["auctions"] or []]
        delta = (before["coins"]["result"]["credits"] or 0) - (after["coins"]["result"]["credits"] or 0)
        if not (all(fresh(a, op) for op, a in after.items()) and delta == chosen["buy_now_price"] and
                any(i["item_id"] == target["item_id"] and i["definition_id"] == target["definition_id"] and i["untradeable"] is False for i in inventory)):
            return self.stop("purchase_ambiguous_or_unreconciled; do not buy again; inspect coins and purchased/transfer piles")
        transferred = any(r["item"]["item_id"] == target["item_id"] for r in after["transfer_list"]["result"]["auctions"] or [])
        if not transferred:
            self.call("move", target, "move")
        moved = self.call("transfer_list", phase="after_move")
        if not fresh(moved, "transfer_list") or not any(r["item"]["item_id"] == target["item_id"] and r["item"]["definition_id"] == target["definition_id"] for r in moved["result"]["auctions"] or []):
            return self.stop("move_destination_unreconciled; inspect transfer list before retry")
        listing = target | {"starting_bid": chosen["buy_now_price"], "buy_now_price": chosen["buy_now_price"] + 50, "duration": 3600}
        self.record["listing"] = listing
        self.save()
        self.call("list", listing, "list")
        listed = self.call("transfer_list", phase="after_list")
        status = self.call("status", phase="status")
        def matching_live(a):
            return any(r["item"]["item_id"] == target["item_id"] and r["item"]["definition_id"] == target["definition_id"] and
                       r["trade_id"] and r["trade_id"] != chosen["trade_id"] and r["trade_state"] == "active" and
                       r["starting_bid"] == listing["starting_bid"] and r["buy_now_price"] == listing["buy_now_price"] and
                       3450 <= (r["expires"] or 0) <= 3600 for r in a["result"]["auctions"] or [])
        if not (fresh(listed, "transfer_list") and fresh(status, "status") and matching_live(listed) and matching_live(status)):
            return self.stop("listing_or_status_unreconciled; inspect physical item and active trade before any listing retry")
        # Relist only a single independently observed eligible expired item.
        expired = [r for r in status["result"]["auctions"] or [] if r["trade_state"] == "expired" and
                   r["expires"] == -1 and r["current_bid"] == 0 and r["item"]["untradeable"] is False and
                   r["item"]["item_id"] and r["item"]["definition_id"] and
                   integer(r["starting_bid"], 150, 950) and integer(r["buy_now_price"], 200, 1000) and
                   r["starting_bid"] < r["buy_now_price"] and r["starting_bid"] % 50 == r["buy_now_price"] % 50 == 0]
        if fresh(status, "status") and expired:
            e = expired[0]
            self.call("relist", {"item_id": e["item"]["item_id"], "definition_id": e["item"]["definition_id"],
                                "starting_bid": e["starting_bid"], "buy_now_price": e["buy_now_price"], "duration": 3600}, "relist")
            self.call("transfer_list", phase="after_relist")
        from .transaction_checks import assess
        errors, summary = assess(self.record)
        self.record["relist"] = summary.get("relist", "UNVERIFIED")
        self.record["status"] = "VERIFIED" if not errors else "PARTIAL/BLOCKED"
        self.record["transport"]["essential_operations"] = "VERIFIED" if not errors else "UNVERIFIED"
        if not errors:
            self.record["transport"]["reason"] = "Independent native purchase, inventory/coin, movement, listing and status readbacks verified. Direct HTTP has no trusted session provider; no additional comparison purchase."
        if errors:
            self.record["errors"].append({"at": utc(), "error": "; ".join(e for group in errors.values() for e in group)})
        self.save()
        return self.record


def main():
    # OS lock covers the complete experiment, including restart reconciliation.
    import msvcrt
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.with_suffix(".lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print(json.dumps({"status": "PARTIAL/BLOCKED", "error": "experiment_already_running"}))
            return 1
        try:
            result = Experiment(TransactionTransport()).run()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    print(json.dumps({"status": result["status"], "write_intents": sorted(result["intents"]), "errors": result["errors"]}))
    from .transaction_report import write_report
    write_report(result)
    return 0 if result["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
