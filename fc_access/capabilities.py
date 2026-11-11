"""Independent field/readback assessment; fixtures are never stored as live evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path

from .harness import METHODS, ROOT, command, validate_result


def authenticated(a):
    r = a["result"]
    routes = {"coins": {"user/credits", "user/currencies", "usermassinfo"}, "club": {"club"},
              "unassigned": {"unassigned", "purchased/items"}, "purchased": {"purchased/items"}, "transfer_list": {"tradepile"}, "search": {"transfermarket"}}
    return r["success"] and any(n["path"].removeprefix("/ut/game/fc27/") in routes[a["operation"]] and n["session_header_present"] and 200 <= n["status"] < 300 for n in r["network"])


def assess(record):
    errors = []
    if not isinstance(record, dict) or set(record) != {"schema", "source", "captured_at", "attempts"} or record["schema"] != 1 or record["source"] != "fc-read-harness":
        return ["invalid_live_record"], {}
    try:
        stamp = datetime.fromisoformat(record["captured_at"])
        if stamp.tzinfo is None:
            raise ValueError()
        attempts = record["attempts"]
        if not isinstance(attempts, list) or not attempts:
            raise ValueError()
        for a in attempts:
            if set(a) != {"observed_at", "transport", "operation", "request", "method", "elapsed_ms", "result"} or a["transport"] not in {"edge", "direct_http"}:
                raise ValueError()
            when = datetime.fromisoformat(a["observed_at"])
            if when.tzinfo is None or not 0 <= (stamp-when).total_seconds() <= 86400:
                raise ValueError()
            if type(a["elapsed_ms"]) not in {float, int} or not 0 <= a["elapsed_ms"] <= 90000:
                raise ValueError()
            command(a["operation"], a["request"])
            validate_result(a["result"])
            if a["method"] != (METHODS[a["operation"]] if a["transport"] == "edge" else "GET (candidate REST mapping)"):
                raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        return ["invalid_or_sensitive_attempt"], {}
    summary = {}
    for name in ["edge", "direct_http"]:
        rows = [a for a in attempts if a["transport"] == name]
        good = [a for a in rows if authenticated(a)]
        summary[name] = {"attempts": len(rows), "authenticated_reads": len(good),
                         "elapsed_ms": [a["elapsed_ms"] for a in good],
                         "unavailable_reasons": sorted({a["result"]["error"] for a in rows if a["result"]["error"]})}
        if {a["operation"] for a in rows} != set(METHODS):
            errors.append("criterion_1_comparison_missing_operations_" + name)
    # Direct HTTP may be unavailable, but the selected architecture must actually read.
    good = [a for a in attempts if authenticated(a)]
    search = [a for a in good if a["operation"] == "search" and a["result"]["auctions"]]
    complete = []
    for a in search:
        for r in a["result"]["auctions"]:
            # Native definitionId is constructed from wire resourceId by EA's
            # reviewed item factory. Do not require absent wire-only properties
            # or invent assetId values on native entities.
            if (r["trade_id"] and r["item"]["item_id"] and r["item"]["definition_id"]
                    and all(r[k] is not None for k in ["starting_bid", "current_bid", "buy_now_price", "expires"])
                    and r["trade_state"] == "active" and r["expires"] > 0 and r["buy_now_price"] > 0):
                complete.append((a, r))
    if not complete:
        errors.append("criterion_3_live_listing_identity_prices_expiry_unverified")
    # Exact version + ceiling must hold for every returned row, not just a selected example.
    filtered = [a for a in search if "definition_id" in a["request"] and "max_buy" in a["request"]]
    matching = [a for a in filtered if all(r["item"]["definition_id"] == a["request"]["definition_id"] and r["buy_now_price"] is not None and 0 < r["buy_now_price"] <= a["request"]["max_buy"] for r in a["result"]["auctions"])]
    if not matching:
        errors.append("criterion_3_card_version_or_buy_now_ceiling_unverified")
    if not any(a["result"]["platform"] is not None for a in search):
        errors.append("criterion_3_platform_separation_unverified")
    filter_facts = {}
    for f in ["nation", "league", "club", "rarity", "position"]:
        probes = [a for a in search if f in a["request"] and "definition_id" not in a["request"]]
        filter_facts[f] = "VERIFIED" if any(all(r["item"][f] == a["request"][f] for r in a["result"]["auctions"]) for a in probes) else "UNVERIFIED"
    if not any(v == "VERIFIED" for v in filter_facts.values()):
        errors.append("criterion_3_supported_filters_unverified")
    summary["filters"] = filter_facts
    summary["market_average"] = "OBSERVED" if any(r["item"]["market_average"] is not None for _, r in complete) else "UNVERIFIED"
    summary["last_sale_price"] = "OBSERVED" if any(r["item"]["last_sale_price"] is not None for _, r in complete) else "UNVERIFIED"
    groups = {}
    for a,r in complete:
        platform = a["result"]["platform"]
        if platform is None:
            continue
        key = platform + ":" + str(r["item"]["definition_id"])
        groups.setdefault(key,set()).add(r["trade_id"])
    summary["comparable_groups"] = {key:{"platform":key.split(":")[0], "definition_id":int(key.split(":")[1]), "distinct_auction_pseudonyms":len(ids)} for key,ids in sorted(groups.items())}
    # Relevant pages must use exactly the same filters, transport and observed platform.
    pairs = []
    for a in search:
        if a["request"].get("page") != 1:
            continue
        for b in search:
            if b["observed_at"] > a["observed_at"] and b["transport"] == a["transport"] and b["result"]["platform"] == a["result"]["platform"] and b["request"].get("page") == 2 and {k: v for k, v in a["request"].items() if k not in {"page", "fresh"}} == {k: v for k, v in b["request"].items() if k not in {"page", "fresh"}}:
                pairs.append((a, b))
    summary["pagination"] = {"two_nonempty_pages": "OBSERVED" if pairs else "UNVERIFIED",
                             "page_pairs": len(pairs), "ordering": "UNVERIFIED", "lookahead": "UNVERIFIED", "caching": "UNVERIFIED", "invalidation": "UNVERIFIED"}
    summary["pagination"]["observations"] = []
    for a, b in pairs:
        left, right = a["result"]["auctions"], b["result"]["auctions"]
        overlap = set(r["trade_id"] for r in left if r["trade_id"]) & set(r["trade_id"] for r in right if r["trade_id"])
        summary["pagination"]["observations"].append({
            "page_1_at": a["observed_at"], "page_2_at": b["observed_at"],
            "page_1_count": len(left), "page_2_count": len(right), "overlap_count": len(overlap),
            "lookahead_row_matches_next_page": bool(len(left) == 21 and right and left[20]["trade_id"] is not None and left[20]["trade_id"] == right[0]["trade_id"]),
            "page_1_bin_nondecreasing": all(x["buy_now_price"] is not None and y["buy_now_price"] is not None and x["buy_now_price"] <= y["buy_now_price"] for x,y in zip(left,left[1:])),
            "page_1_expiry_nondecreasing": all(x["expires"] is not None and y["expires"] is not None and x["expires"] <= y["expires"] for x,y in zip(left,left[1:]))})
    # Repeated page calls may refresh known auctions instead of issuing a new
    # transfermarket query. Describe evidence rather than inferring cache use
    # from identical row IDs alone.
    summary["pagination"]["fresh_network_reads"] = sum(a["request"].get("fresh") is True and a["result"]["cache_invalidated"] is True for a in search)
    summary["pagination"]["cached_native_reads"] = sum(a["operation"] == "search" and a["result"]["success"] and a["request"].get("fresh") is False and not a["result"]["network"] for a in attempts)
    if any(o["lookahead_row_matches_next_page"] for o in summary["pagination"]["observations"]):
        summary["pagination"]["lookahead"] = "OBSERVED_ONE_ROW_OVERLAP"
    if any(o["page_1_expiry_nondecreasing"] and not o["page_1_bin_nondecreasing"] for o in summary["pagination"]["observations"]):
        summary["pagination"]["ordering"] = "OBSERVED_EXPIRY_ASCENDING_BIN_UNSORTED"
    if summary["pagination"]["fresh_network_reads"]:
        summary["pagination"]["invalidation"] = "OBSERVED_NATIVE_RESET_AND_NETWORK_READ"
    expiry_checks = []
    for i, a in enumerate(search):
        for b in search[i+1:]:
            if a["transport"] != b["transport"] or a["result"]["platform"] != b["result"]["platform"] or {k:v for k,v in a["request"].items() if k != "fresh"} != {k:v for k,v in b["request"].items() if k != "fresh"}:
                continue
            dt = (datetime.fromisoformat(b["observed_at"])-datetime.fromisoformat(a["observed_at"])).total_seconds() + (b["elapsed_ms"]-a["elapsed_ms"])/1000
            left = {r["trade_id"]:r for r in a["result"]["auctions"] if r["trade_id"]}
            matches = [(left[r["trade_id"]],r) for r in b["result"]["auctions"] if r["trade_id"] in left]
            if dt < 5 or not matches:
                continue
            checked = [(x,y) for x,y in matches if x["expires"] is not None and y["expires"] is not None and x["expires"] > 0 and y["expires"] > 0]
            expiry_checks.append({"first_at":a["observed_at"], "second_at":b["observed_at"], "elapsed_seconds":round(dt,3), "matched_auctions":len(matches), "countdowns_matching_elapsed_seconds":sum(abs((x["expires"]-y["expires"])-dt) <= 3 for x,y in checked)})
    summary["expiry_readbacks"] = expiry_checks
    summary["expiry_units"] = "OBSERVED_SECONDS_REMAINING" if any(x["countdowns_matching_elapsed_seconds"] for x in expiry_checks) else "UNVERIFIED"
    if not pairs:
        # Acceptance permits unavailable pagination, provided explicitly documented.
        summary["pagination"]["reason"] = "No two authenticated nonempty pages retained; do not infer end-of-market from failed reads."
    for op in ["coins", "club", "unassigned", "purchased", "transfer_list"]:
        rows = [a for a in good if a["operation"] == op]
        field = "credits" if op == "coins" else "auctions" if op == "transfer_list" else "items"
        observed = any(a["result"][field] is not None for a in rows)
        mode = "NETWORK_READ"
        if not observed and op == "purchased":
            # Observed requestUnassignedItems -> purchased/items, independently
            # corroborated by getUnassignedPile using ItemPile.PURCHASED.
            observed = any(a["operation"] == "unassigned" and a["result"]["items"] is not None and any(n["path"] == "/ut/game/fc27/purchased/items" for n in a["result"]["network"]) for a in good)
            mode = "SHARED_PURCHASED_UNASSIGNED_ENDPOINT"
        if not observed and op == "club":
            for a in attempts:
                r = a["result"]
                if a["operation"] != "club" or a["transport"] != "edge" or not r["success"] or r["status"] not in {200,304} or r["items"] is None or not r["platform"]:
                    continue
                at = datetime.fromisoformat(a["observed_at"])
                # A typed account snapshot on the same attached native page,
                # immediately after an authenticated read. This establishes
                # available native state, not freshness of an uncached GET.
                if any(x["transport"] == "edge" and x["result"]["platform"] == r["platform"] and 0 <= (at-datetime.fromisoformat(x["observed_at"])).total_seconds() <= 90 for x in good):
                    observed = True
                    mode = "NATIVE_SNAPSHOT_NETWORK_FRESHNESS_UNVERIFIED"
        summary[op] = "VERIFIED" if observed else "UNVERIFIED"
        summary[op + "_readback_mode"] = mode if observed else "UNVERIFIED"
        if not observed:
            errors.append("criterion_5_live_" + op + "_unverified")
    return errors, summary


def write_report(record, destination=None):
    from .research_report import write_report as render
    return render(record, destination)
