"""Independent, read-only release audit. No runtime adapters or earlier auditors.

Evidence authenticity is bounded by the retained, pinned browser captures, not
cryptographic attestation by EA. Hashes protect provenance; semantic checks
separately reconcile native wire projections, command ledgers and account reads.
This module never imports an execution server, opens a browser or sends EA calls.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = "docs/research/001c/"
OUT = BASE + "001c-07/"
CLASSES = {"LIVE_VERIFIED", "SOURCE_CONFIRMED_ONLY", "OFFLINE_VALIDATED", "BLOCKED", "UNVERIFIED"}
WINDOWS = {"001c-06": 18, "001c-06-resume-01": 4,
           "001c-06-resume-02": 18, "001c-06-resume-03": 4}
CONDITIONAL = {"active_outbid_rebid", "timer_extension", "cycle_25s", "won_transfer_list", "sale_profit"}
LIVE_REFERENCES = {
    "search_filters": ("001c-06-resume-02/search-2.json", "001c-06-resume-02/availability-2.json"),
    "comparables": ("001c-06-resume-02/comparables-2.json", "001c-06-resume-02/pricing-plan.json"),
    "card_caps": ("001c-06-resume-02/caps-2.json", "001c-06-resume-02/availability-2.json"),
    "opening_bid": ("001c-06-resume-02/opening-1.json", "001c-06-resume-02/watched-after-opening.json",
                    "001c-06-resume-02/balance-after-opening.json", "001c-06-resume-02/live-final.sqlite"),
    "leading_hold": ("001c-06-resume-02/hold-opening.json", "001c-06-resume-02/hold-cycle-2.json"),
    "bulk_watchlist": ("001c-03/watched-4.json", "001c-06-resume-02/watched-cycle-2.json"),
    "watchlist_capacity": ("001c-03/watched-4.json", "001c-03/inspect-3.json"),
    "loss": ("001c-06-resume-03/status.json", "001c-06-resume-03/watched.json", "001c-06-resume-03/unassigned.json"),
    "held_coins_refunds": ("001c-06-resume-02/balance-prebid-2.json", "001c-06-resume-02/balance-after-opening.json",
                          "001c-06-resume-03/balance.json", "001c-06-resume-03/status.json"),
    "bridge_resilience": ("001c-05/idle.json", "001c-05/server-restart-verified.json", "001c-05/extension-reload-verified.json")}


def require(ok, why):
    if not ok:
        raise ValueError(why)


def stamp(value):
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value, timezone.utc)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.utcoffset() is not None, "missing_timezone")
    return result


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return (ROOT / path).read_bytes()


def load(path, reader=read):
    return json.loads(reader(path))


def private_fields(value):
    forbidden = {"password", "cookies", "cookie", "authorization", "x-ut-sid", "sid",
                 "token", "access_token", "refresh_token", "email", "username", "persona_id"}
    if isinstance(value, dict):
        require(not forbidden.intersection(k.lower() for k in value), "private_field")
        for child in value.values():
            private_fields(child)
    elif isinstance(value, list):
        for child in value:
            private_fields(child)


def preserve(reader=read):
    entry = load(OUT + "entry.json", reader)
    for path, expected in entry["sha256"].items():
        require(sha(reader(path)) == expected, "preexisting_bytes_changed:" + path)
    # Independently re-read the actual historical seal maps, not just the new entry.
    for path, key in (("docs/research/001b/preservation.json", "static_sha256"),
                      ("docs/research/001b/t7/manifest.json", "sha256"),
                      ("docs/research/001c/001c-06-complete/manifest.json", "files")):
        for target, expected in load(path, reader)[key].items():
            require(sha(reader(target)) == expected, "sealed_bytes_changed:" + target)
    return len(entry["sha256"])


def network(result, operation):
    require(result.get("success") is True and result.get("status") == 200, "native_not_successful")
    p = result["persona"]
    require(p["accepted"] is True and p["platform_value"] == "PC" and p["is_pc"] is True,
            "wrong_persona")
    require(len(result["network"]) == 1, "missing_live_network_or_fanout")
    n = result["network"][0]
    route = {"search": "/ut/game/fc27/transfermarket", "comparables": "/ut/game/fc27/transfermarket",
             "availability": "/ut/game/fc27/transfermarket", "caps": "/ut/game/fc27/marketdata/pricelimits",
             "watched": "/ut/game/fc27/watchlist", "balance": "/ut/game/fc27/user/credits",
             "bid": "/ut/game/fc27/trade/:trade/bid", "status": "/ut/game/fc27/trade/status/lite",
             "unassigned": "/ut/game/fc27/purchased/items", "transfer_list": "/ut/game/fc27/tradepile"}
    require(n["route"] == route[operation], "wrong_native_route:" + operation)
    require(n["method"] == ("PUT" if operation == "bid" else "GET") and
            n["status"] == 200 and n["session_header_present"] is True, "not_authenticated_native_evidence")
    require(0 < n["duration_ms"] < 23000 and n["payload_bytes"] > 0 and
            stamp(n["started_at"]) <= stamp(n["ended_at"]) <= stamp(result["observed_at"]), "bad_native_timing")
    private_fields(result)
    return n


def read_ledger(window):
    # immutable=1 prevents WAL/shm creation and ignores mutable working databases.
    path = ROOT / BASE / window / "live-final.sqlite"
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    try:
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "bad_ledger")
        meta = {r[0]: json.loads(r[1]) for r in db.execute("SELECT * FROM meta")}
        commands = [dict(r) for r in db.execute("SELECT * FROM commands ORDER BY created,id")]
        events = [dict(r) for r in db.execute("SELECT * FROM events ORDER BY seq")]
    finally:
        db.close()
    return meta, commands, events


def collect(reader=read, ledger=read_ledger):
    """Reconcile captures with a second persistent record and network projections."""
    timeline = []
    ledgers = {}
    for window, count in WINDOWS.items():
        meta, commands, events = ledger(window)
        require(meta["stopped"] is True and len(commands) == count, "unclosed_or_wrong_window_size")
        previous = None
        for command in commands:
            correlated_events = []
            for event in events:
                event_id = json.loads(event["data"]).get("id") if "data" in event else event.get("id")
                if event_id == command["id"]:
                    correlated_events.append(event)
            for reason in (("RESERVED_BEFORE_DELIVERY" if "body" in command else "RESERVED"), "DELIVERED", "RESULT"):
                require(len([e for e in correlated_events if e["reason"] == reason]) == 1,
                        "missing_or_duplicate_dispatch_event")
            stage = command.get("stage", command["operation"])
            path = BASE + window + "/" + stage + ".json"
            cap = load(path, reader)
            r = cap["response"]
            require(cap["http_status"] == 200 and json.loads(command["result"]) == r, "ledger_capture_mismatch")
            require(command["id"] == r["command_id"] and command["operation"] == r["operation"], "correlation_mismatch")
            op = command["operation"]
            n = network(r, op)
            if "body" in command:
                body = json.loads(command["body"])
                require(body["operation"] == op and all(body["params"][k] == v for k, v in cap["request"]["params"].items()), "intent_mismatch")
                params = body["params"]
            else:
                params = {}
            require(stamp(command["created"]) <= stamp(command["delivered"]) <= stamp(n["started_at"]) <=
                    stamp(r["observed_at"]) < stamp(meta["deadline"]), "expired_or_reordered_command")
            if previous:
                require(previous <= stamp(command["created"]), "overlapping_commands")
            previous = stamp(r["observed_at"])
            require(cap["argv"][0] == "{python}" and 0 < cap["elapsed_ms"] < 23000, "missing_reproduction_or_duration")
            timeline.append({"window": window, "capture": path, "command_id": command["id"], "stage": stage,
                             "operation": op, "state": command["state"], "params": params, "argv": cap["argv"],
                             "at": cap["at"], "host_ms": cap["elapsed_ms"], "network": n, "result": r})
        ledgers[window] = {"meta": meta, "events": events}
    timeline.sort(key=lambda t: t["at"])
    validate_mutations(timeline)
    return timeline, ledgers


def validate_mutations(timeline):
    require(len({t["command_id"] for t in timeline}) == len(timeline) == 44, "duplicate_mutation_or_command")
    writes = [t for t in timeline if t["network"]["method"] != "GET"]
    require([(t["window"], t["operation"], t["params"].get("amount")) for t in writes] ==
            [("001c-06", "bid", 700), ("001c-06-resume-02", "bid", 800)], "duplicate_or_unaccounted_mutation")


def row(t, trade=None):
    r = t["result"]
    entities = [a for a in r["rows"] if trade is None or a["trade_id"] == trade]
    wires = [a for a in r["wire_rows"] if trade is None or a["trade_id"] == trade]
    require(len(entities) == len(wires) == 1, "missing_authoritative_rows")
    entity, wire = entities[0], wires[0]
    for field in ("trade_id", "item_id", "definition_id", "current_bid", "bid_state", "trade_state", "expires"):
        observed = wire.get(field)
        if field == "definition_id" and observed is None:
            observed = wire.get("resource_id")
        require(entity[field] == observed, "wire_entity_disagrees:" + field)
    return entity


def derive(timeline, ledgers, reader=read):
    validate_mutations(timeline)
    def get(window, stage):
        matches = [t for t in timeline if t["window"] == window and t["stage"] == stage]
        require(len(matches) == 1, "missing_independent_readback:" + stage)
        return matches[0]

    w = "001c-06-resume-02"
    bid = get(w, "opening-1")
    require(bid["network"].get("bid_amount") == bid["params"]["amount"] == 800, "actual_bid_body_not_proved")
    require(bid["state"] == "RECONCILED", "opening_not_reconciled")
    status = get(w, "watched-after-opening")
    balance = get(w, "balance-after-opening")
    before = get(w, "balance-prebid-2")
    require(len({t["command_id"] for t in (bid, status, balance)}) == 3, "readbacks_not_independent")
    for readback in (status, balance):
        require(stamp(readback["network"]["started_at"]) > stamp(bid["network"]["ended_at"]), "pre_ack_readback")
    a = row(status)
    identity = {k: a[k] for k in ("trade_id", "item_id", "definition_id")}
    require(identity == {k: bid["params"][k] for k in identity}, "wrong_bid_identity")
    require(a["current_bid"] == 800 and a["bid_state"] == "highest" and a["trade_state"] == "active", "unsupported_leading_claim")
    require(before["result"]["credits"] == 16268 and balance["result"]["credits"] == 15468, "unsupported_debit_claim")
    pre = row(get(w, "availability-2"), identity["trade_id"])
    require(pre["current_bid"] == 750 and pre["trade_id"] == identity["trade_id"], "wrong_prebid_state")
    events = [{**e, "data": json.loads(e["data"])} for e in ledgers[w]["events"]]
    reconcile = [e for e in events if e["reason"] == "INDEPENDENT_READBACK"]
    require(len(reconcile) == 1 and reconcile[0]["data"]["id"] == bid["command_id"] and
            reconcile[0]["data"]["status_id"] == status["command_id"] and
            reconcile[0]["data"]["balance_id"] == balance["command_id"], "missing_independent_readback_event")
    holds = [e for e in events if e["reason"] == "HOLD"]
    require(len(holds) == 2, "missing_hold_proof")
    for e in holds:
        observed = next(t for t in timeline if t["command_id"] == e["data"]["status_id"])
        ar = row(observed)
        require(ar["bid_state"] == "highest" and ar["trade_state"] == "active" and
                ar["trade_id"] == identity["trade_id"] and ar["item_id"] == identity["item_id"], "hold_without_lead")
        require(e["data"]["additional_write"] is False and e["data"]["bid_writes"] == 1, "hold_wrote_again")
    for stage in ("hold-opening", "hold-cycle-2"):
        h = load(BASE + w + "/" + stage + ".json", reader)
        require(h["response"] == {"hold": True} and all(h["before"][k] == h["after"][k] for k in
                ("reads_reserved", "mutations_reserved", "bid_writes_reserved", "gross_coins_reserved")), "hold_sent_command")
    end = "001c-06-resume-03"
    terminal = get(end, "status")
    full = get(end, "watched")
    for t in (terminal, full):
        ar = row(t)
        require(ar["trade_id"] == identity["trade_id"] and ar["item_id"] == identity["item_id"] and
                ar["trade_state"] == "closed" and ar["bid_state"] == "outbid" and
                ar["current_bid"] == 1200 and ar["expires"] == -1, "unsupported_terminal_claim")
    require(row(terminal)["definition_id"] == 0 and row(full)["definition_id"] == identity["definition_id"], "lite_version_invented")
    require(stamp(full["result"]["observed_at"]) > stamp(ledgers[w]["meta"]["deadline"]), "historical_terminal_relabelled_in_window")
    require(get(end, "unassigned")["result"]["rows"] == [] and get(end, "balance")["result"]["credits"] == 16268, "accounting_unresolved")
    original = get("001c-06", "opening-1")
    first_resolution = row(get("001c-06-resume-01", "status"))
    require(all(first_resolution[k] == original["params"][k] for k in ("trade_id", "item_id")) and
            first_resolution["definition_id"] == 0 and first_resolution["trade_state"] == "closed" and
            first_resolution["bid_state"] == "none" and first_resolution["current_bid"] == 800 and
            get("001c-06-resume-01", "unassigned")["result"]["rows"] == [] and
            get("001c-06-resume-01", "balance")["result"]["credits"] == 16268, "original_exposure_not_reconciled")
    require(original["network"].get("bid_amount") is None, "historical_request_body_fabricated")
    plan = load(BASE + w + "/pricing-plan.json", reader)
    require((plan["target"], plan["tax"], plan["X"], plan["cap"], plan["opening_minimum"], plan["estimate"]["sample_count"]) ==
            (2800, 140, 500, 2100, 800, 12), "wrong_pricing_plan")
    require(plan["target"] - plan["target"] // 20 - plan["X"] >= plan["cap"], "cap_rounded_up")
    filtered = get(w, "search-2")["result"]
    require(filtered["network"][0]["query"]["macr"] == 1000 and filtered["network"][0]["query"]["minb"] == 10500, "wrong_search_filters")
    watched = [t for t in timeline if t["window"] == w and t["operation"] == "watched"]
    active = [t for t in watched if t["result"]["rows"]]
    capacity = load(BASE + "001c-03/watched-4.json", reader)
    network(capacity, "watched")
    require(capacity["account"]["inbox_capacity"] == capacity["account"]["server_setting_capacity"] == 50,
            "unsupported_capacity")
    for stage in ("idle", "server-restart-verified", "extension-reload-verified", "owner-change-verified", "final-verified"):
        c = load(BASE + "001c-05/" + stage + ".json", reader)
        r = c["response"]
        require(c["http_status"] == 200 and r["freshness"]["source"] == "native" and
                r["freshness"]["request_count"] == 1 and r["result"]["success"] is True and
                r["result"]["network"][0]["session_header_present"] is True and
                r["result"]["network"][0]["status"] == 200, "unsupported_lifecycle_readback")
    return {"identity": identity, "commands": len(timeline), "bid_attempts": 2, "requested_amounts": [700, 800],
            "verified_opening": 800, "original_700_acceptance": "UNVERIFIED", "holds": 2,
            "initial_spendable": 16268, "after_opening_spendable": 15468, "final_spendable": 16268,
            "returned_available_coins": 800, "gross_reservations": 1500, "paid_acquisition_cost": 0,
            "new_owned_items": [], "unsold_test_cards": [], "unresolved_active_bids": [],
            "remaining_target": "EXPIRED_OUTBID;LEFT_IN_PLACE", "terminal": "LOST", "terminal_price": 1200,
            "held_balance_direct": None, "sale_proceeds": None, "realized_profit": None,
            "reported_capacity": 50, "live_50_completeness": False, "live_25s_cycle": False,
            "watched_native_ms": [t["network"]["duration_ms"] for t in watched],
            "bid_native_ms": bid["network"]["duration_ms"], "bid_host_ms": bid["host_ms"],
            "refresh_intervals_s": [(stamp(b["network"]["started_at"]) - stamp(a["network"]["started_at"])).total_seconds()
                                    for a, b in zip(active, active[1:])],
            "pricing": {k: plan[k] for k in ("target", "tax", "X", "cap", "opening_minimum")},
            "expiry": [{"capture": t["capture"], "at": t["network"]["started_at"], "expires": row(t)["expires"]} for t in active]}


def validate_claims(doc, facts, reader=read):
    require(doc["decision"] == "CONDITIONAL GO" and doc["actor_execution_authorized"] is False, "unsupported_release_decision")
    require(doc["current_evidence_scope"] == "Objective 001C retained observations; not a current account refresh", "historical_relabelled_current")
    rows = doc["operations"]
    expected = {"search_filters", "comparables", "card_caps", "legal_bid_ticks", "opening_bid", "leading_hold",
                "bulk_watchlist", "watchlist_capacity", "bulk_completeness_50", "loss", "held_coins_refunds",
                "bridge_resilience", "durable_journal", "queue_draining", "strict_rules_integration"} | CONDITIONAL
    require(len(rows) == len(expected) and {r["id"] for r in rows} == expected, "missing_or_duplicate_operation")
    allowed_live = {"search_filters", "comparables", "card_caps", "opening_bid", "leading_hold", "bulk_watchlist",
                    "watchlist_capacity", "loss", "held_coins_refunds", "bridge_resilience"}
    for r in rows:
        require(r["classification"] in CLASSES, "invalid_capability_classification")
        require(all(r[k] for k in ("implementation", "source_contract", "scope", "dependency")), "missing_operation_contract")
        for p in r["implementation"] + r["source_contract"] + r["evidence"] + r["independent_proof"]:
            require(bool(reader(p)), "missing_source_or_evidence:" + p)
        if r["id"] in CONDITIONAL:
            require(r["classification"] == "UNVERIFIED" and r["live_annotation"] == "live-UNVERIFIED", "unwitnessed_event_promoted")
        if r["classification"] == "LIVE_VERIFIED":
            require(r["id"] in allowed_live and r["evidence"] and r["independent_proof"], "unsupported_live_claim")
            require(r["provenance"] == "retained_001c_live" and all(p.startswith(BASE) and
                    "/001c-07/" not in p and "fixture" not in p for p in r["evidence"]), "fixture_or_historical_labelled_live")
            references = set(r["evidence"] + r["independent_proof"])
            require({BASE + p for p in LIVE_REFERENCES[r["id"]]} <= references, "operation_proof_missing")
        if r["id"] == "strict_rules_integration":
            require(r["classification"] == "BLOCKED", "rules_gap_hidden")
        if r["id"] in {"bulk_completeness_50", "cycle_25s"}:
            require(r["classification"] == "UNVERIFIED", "small_sample_promoted_to_50")
    require(facts["terminal"] == "LOST" and facts["verified_opening"] == 800, "unsupported_release_facts")
    private_fields(doc)


def audit(reader=read, ledger=read_ledger, check_preservation=True):
    preserved = preserve(reader) if check_preservation else None
    timeline, ledgers = collect(reader, ledger)
    facts = derive(timeline, ledgers, reader)
    doc = load(OUT + "release.json", reader)
    validate_claims(doc, facts, reader)
    return {"status": "PASS", "decision": doc["decision"], "preserved_files": preserved, "facts": facts}


if __name__ == "__main__":
    try:
        print(json.dumps(audit(), indent=2))
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}))
        sys.exit(1)
