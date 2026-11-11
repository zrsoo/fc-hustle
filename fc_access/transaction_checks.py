"""Independent transaction evidence checks. Never sends EA or bridge commands."""
from datetime import datetime, timezone
import re

from .harness import validate_result, pseudonym
from .transaction import command, fresh, METHODS
from .harness import METHODS as READ_METHODS


def assess(record):
    errors = {i: [] for i in range(8)}
    summary = {"purchase": "UNVERIFIED", "movement": "UNVERIFIED", "listing": "UNVERIFIED", "status": "UNVERIFIED", "relist": "UNVERIFIED"}

    def need(index, ok, error):
        if not ok:
            errors[index].append(error)

    try:
        if record["schema"] != 1 or record["source"] != "fc-one-shot-transaction":
            raise ValueError()
        if not isinstance(record["evidence_key"], str) or not re.fullmatch(r"[a-f0-9]{32}", record["evidence_key"]):
            raise ValueError()
        created, updated = map(datetime.fromisoformat, [record["created_at"], record["updated_at"]])
        if created.tzinfo is None or updated.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-updated).total_seconds() <= 86400:
            raise ValueError()
        attempts, intents = record["attempts"], record["intents"]
        if not isinstance(attempts, list) or not isinstance(intents, dict):
            raise ValueError()
        last = created
        for a in attempts:
            command(a["operation"], a["request"])
            validate_result(a["result"])
            if a.get("method") != (METHODS[a["operation"]] if a["operation"] in METHODS else READ_METHODS[a["operation"]]):
                raise ValueError()
            at = datetime.fromisoformat(a["at"])
            if at.tzinfo is None or not last <= at <= updated:
                raise ValueError()
            last = at
            if a["operation"] in {"buy", "move", "list", "relist"}:
                intent = intents[a["operation"]]
                if intent["request"] != a["request"] or not created <= datetime.fromisoformat(intent["at"]) <= at:
                    raise ValueError()
        for op, intent in intents.items():
            command(op, intent["request"])
            if op not in {"buy", "move", "list", "relist"}:
                raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        return {i: ["missing_invalid_or_stale_transaction_record"] for i in range(8)}, summary

    def rows(op, phase=None):
        return [a for a in attempts if a["operation"] == op and (phase is None or a["phase"] == phase)]

    def one(op, phase=None):
        r = rows(op, phase)
        return r[0] if len(r) == 1 else None

    def good(a, op):
        return a is not None and fresh(a, op)

    chosen, listing = record.get("selection"), record.get("listing")
    platforms = {a["result"]["platform"] for a in attempts if a["result"]["success"]}
    need(0, len(platforms) == 1 and None not in platforms, "single_observed_platform_required")
    buy = one("buy")
    need(0, chosen is not None and buy is not None, "exactly_one_live_purchase_required")
    need(0, len(rows("buy")) == 1 and set(intents) <= {"buy", "move", "list", "relist"}, "extra_or_missing_purchase")
    for op in ("move", "list", "relist"):
        need(5, len(rows(op)) <= 1, "duplicate_" + op)
    need(5, len(rows("buy")) <= 1, "duplicate_buy")
    # Every acknowledged, failed or ambiguous write must have later independent
    # reads. An intent with no response is still a potentially executed write.
    for op, intent in intents.items():
        at = intent["at"]
        later = [a for a in attempts if a["at"] > at]
        required = {"unassigned", "transfer_list", "coins"} if op == "buy" else {"transfer_list"}
        need(5, required <= {a["operation"] for a in later if a["operation"] in required and fresh(a, a["operation"])}, "write_not_reconciled_" + op)
    need(5, bool(intents), "live_reconciliation_unverified_no_writes")

    before = {op: one(op, "before_buy") for op in ("unassigned", "transfer_list", "coins")}
    after = {op: one(op, "after_buy") for op in before}
    reconciled = {op: one(op, "restart_reconciliation") for op in before}
    if all(good(a, op) for op, a in reconciled.items()):
        after = reconciled
    owned_before, owned_after = [], []
    for snap, target in [(before, owned_before), (after, owned_after)]:
        if all(good(a, op) for op, a in snap.items()):
            target.extend(snap["unassigned"]["result"]["items"] or [])
            target.extend(r["item"] for r in snap["transfer_list"]["result"]["auctions"] or [])
    if chosen and buy:
        item = chosen["item"]
        target_id = item["item_id"]
        version = item["definition_id"]
        summary["identity"] = {"physical_item": target_id, "definition_id": version,
                               "purchase_trade": chosen["trade_id"], "acquisition_price": chosen["buy_now_price"]}
        zero_trade = pseudonym(0, "trade", record["evidence_key"])
        zero_item = pseudonym(0, "item", record["evidence_key"])
        need(0, target_id is not None and target_id != zero_item and chosen["trade_id"] is not None and chosen["trade_id"] != zero_trade,
             "positive_physical_item_and_auction_ids_required")
        need(0, item["untradeable"] is False and chosen["trade_state"] == "active" and
             (chosen["expires"] or 0) > 0 and 200 <= chosen["buy_now_price"] <= 500, "selected_card_not_inexpensive_tradeable_active")
        need(0, buy["request"] == {"item_id": target_id, "definition_id": version, "trade_id": chosen["trade_id"], "buy_now_price": chosen["buy_now_price"]}, "purchase_identity_mismatch")
        exact = one("search", "exact_match")
        need(0, good(exact, "search") and exact["at"] < buy["at"] and exact["request"].get("definition_id") == version and
             any(r["trade_id"] == chosen["trade_id"] and r["item"]["item_id"] == target_id and
                 r["item"]["definition_id"] == version and r["buy_now_price"] == chosen["buy_now_price"] and
                 r["item"]["untradeable"] is False and r["trade_state"] == "active" and (r["expires"] or 0) > 0 for r in exact["result"]["auctions"] or []), "fresh_exact_card_auction_match_unverified")
        complete = all(good(a, op) for op, a in before.items()) and all(good(a, op) for op, a in after.items())
        need(1, complete and all(a["at"] < buy["at"] for a in before.values()) and all(a["at"] > buy["at"] for a in after.values()), "independent_fresh_before_after_account_reads_missing")
        need(1, complete and before["coins"]["result"]["credits"] - after["coins"]["result"]["credits"] == chosen["buy_now_price"], "acquisition_coin_delta_unverified")
        if complete:
            summary["acquisition_readback"] = {"before_at": before["coins"]["at"], "after_at": after["coins"]["at"],
                                               "coin_debit": before["coins"]["result"]["credits"] - after["coins"]["result"]["credits"],
                                               "fresh_inventory_at": after["unassigned"]["at"]}
        need(1, target_id not in {i["item_id"] for i in owned_before} and any(i["item_id"] == target_id and i["definition_id"] == version and i["untradeable"] is False for i in owned_after), "new_physical_item_not_proven")
        moved = one("transfer_list", "after_move")
        move = one("move")
        need(2, good(moved, "transfer_list") and moved["at"] > max(a["at"] for a in after.values() if a) and
             (move is None or (move["request"] == {"item_id": target_id, "definition_id": version} and moved["at"] > move["at"])) and
             any(r["item"]["item_id"] == target_id and r["item"]["definition_id"] == version for r in moved["result"]["auctions"] or []), "destination_not_independently_verified")
        listing_write = one("list")
        listed = one("transfer_list", "after_list")
        active_trade = None
        if listing and listing_write and good(listed, "transfer_list"):
            elapsed = (datetime.fromisoformat(listed["at"])-datetime.fromisoformat(listing_write["at"])).total_seconds() + listed["elapsed_ms"] / 1000
            need(3, listing_write["request"] == listing and listing["item_id"] == target_id and listing["definition_id"] == version, "listing_request_identity_mismatch")
            matches = [r for r in listed["result"]["auctions"] or [] if r["item"]["item_id"] == target_id and
                       r["item"]["definition_id"] == version and r["trade_id"] and r["trade_id"] not in {chosen["trade_id"], zero_trade} and
                       r["starting_bid"] == listing["starting_bid"] and r["buy_now_price"] == listing["buy_now_price"] and
                       r["trade_state"] == "active" and r["expires"] is not None and
                       0 < r["expires"] <= listing["duration"] and abs(r["expires"] + elapsed - listing["duration"]) <= 90]
            need(3, len(matches) == 1 and elapsed >= 0 and moved is not None and moved["at"] < listing_write["at"], "live_listing_trade_prices_duration_state_unverified")
            if len(matches) == 1:
                active_trade = matches[0]["trade_id"]
                summary["listing_readback"] = {"read_at": listed["at"], "physical_item": target_id,
                    "definition_id": version, "trade_id": active_trade, "starting_bid": matches[0]["starting_bid"],
                    "buy_now_price": matches[0]["buy_now_price"], "requested_duration": listing["duration"],
                    "observed_seconds_remaining": matches[0]["expires"], "trade_state": matches[0]["trade_state"]}
        else:
            need(3, False, "independent_live_listing_readback_missing")
        status = one("status", "status")
        need(4, active_trade is not None and good(status, "status") and status["at"] > listed["at"] and
             any(r["trade_id"] == active_trade and r["item"]["item_id"] == target_id and r["trade_state"] == "active" for r in status["result"]["auctions"] or []), "fresh_status_read_unverified")
    else:
        for i in (1, 2, 3, 4):
            need(i, False, "live_purchase_to_list_path_unverified")

    relist = one("relist")
    status = one("status", "status")
    if relist:
        p = relist["request"]
        need(4, good(status, "status") and status["at"] < relist["at"] and any(r["item"]["item_id"] == p["item_id"] and
             r["item"]["definition_id"] == p["definition_id"] and r["trade_state"] == "expired" and r["expires"] == -1 and
             r["current_bid"] == 0 and r["item"]["untradeable"] is False for r in status["result"]["auctions"] or []), "relist_without_eligible_expired_listing")
        rb = one("transfer_list", "after_relist")
        old_trades = {r["trade_id"] for r in status["result"]["auctions"] or [] if r["item"]["item_id"] == p["item_id"]} if status else set()
        verified = good(rb, "transfer_list") and rb["at"] > relist["at"] and any(r["item"]["item_id"] == p["item_id"] and r["item"]["definition_id"] == p["definition_id"] and r["trade_id"] and r["trade_id"] not in old_trades and
             r["trade_state"] == "active" and r["starting_bid"] == p["starting_bid"] and r["buy_now_price"] == p["buy_now_price"] and
             3450 <= (r["expires"] or 0) <= 3600 for r in rb["result"]["auctions"] or [])
        need(4, verified, "relist_readback_unverified")
        if verified and not any("relist_" in e for e in errors[4]):
            summary["relist"] = "VERIFIED"
    else:
        need(4, record.get("relist") == "UNVERIFIED", "untested_relist_claimed_verified")
        eligible = good(status, "status") and any(r["trade_state"] == "expired" and r["expires"] == -1 and r["current_bid"] == 0 and
            r["item"]["untradeable"] is False and r["starting_bid"] is not None and r["buy_now_price"] is not None and
            150 <= r["starting_bid"] < r["buy_now_price"] <= 1000 and r["starting_bid"] % 50 == r["buy_now_price"] % 50 == 0 for r in status["result"]["auctions"] or [])
        need(4, not eligible, "eligible_expired_listing_relist_not_tested")
        if good(status, "status"):
            summary["eligible_expired_listing_present"] = bool(eligible)

    transport = record.get("transport", {})
    probe = record.get("direct_probe")
    need(6, transport.get("selected") == "edge" and transport.get("decision") == "FINAL" and
         probe is not None and probe.get("error") == "direct_session_provider_unavailable" and
         transport.get("direct_http") == "UNVERIFIED" and bool(transport.get("reason")), "transport_decision_missing_observed_comparison")
    successful = not any(errors[i] for i in range(7))
    if not successful:
        need(7, record.get("status") == "PARTIAL/BLOCKED" and bool(record.get("errors")) and
             bool(record.get("recovery")), "failed_validation_requires_exact_errors_and_recovery")
        need(7, all(record.get(k) != "VERIFIED" for k in ("purchase", "movement", "listing_status")), "unproven_success_claim")
    else:
        summary.update(purchase="VERIFIED", movement="VERIFIED", listing="VERIFIED", status="VERIFIED")
    return {i: e for i, e in errors.items() if e}, summary
