"""Bounded, read-only capability harness. No login, transactions, or scheduler."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import time
from typing import Callable, Protocol
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/research/capabilities/attempts.json"
OPERATIONS = {"coins", "club", "unassigned", "purchased", "transfer_list", "search"}
METHODS = {"coins": "services.User.requestCurrencies()",
           "club": "services.Club.search(criteria)",
           "unassigned": "services.Item.requestUnassignedItems()",
           "purchased": "services.Item.requestPurchasedItems()",
           "transfer_list": "services.Item.requestTransferItems()",
           "search": "services.Item.searchTransferMarket(criteria, page)"}
ERRORS = {"direct_session_provider_unavailable", "bridge_unavailable", "bridge_not_attached",
          "bridge_timeout", "bridge_busy", "service_unavailable", "service_timeout",
          "service_failed", "schema_unrecognized", "unsafe_integer", "network_error",
          "wrong_page", "invalid_command", "internal_error", "http_error"}
PLATFORMS = {None, "pc", "ps3", "ps4", "ps5", "xbox", "xbox360", "xboxone", "xbsx", "switch"}
ITEM_FIELDS = {"item_id", "resource_id", "definition_id", "asset_id", "rating", "rarity",
               "nation", "league", "club", "position", "untradeable", "market_average", "last_sale_price"}
AUCTION_FIELDS = {"trade_id", "starting_bid", "current_bid", "buy_now_price", "expires",
                  "trade_state", "bid_state", "item"}
NUMERIC_ITEM_FIELDS = ITEM_FIELDS - {"item_id", "position", "untradeable"}


def utc():
    return datetime.now(timezone.utc).isoformat()


def integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high


def command(operation, params):
    """Fail closed on writes, unsupported filters and platform overrides."""
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError("invalid_command")
    allowed = {"page", "count", "definition_id", "max_buy", "min_buy", "nation", "league", "club", "rarity", "position", "fresh"} if operation == "search" else {"start", "count"} if operation == "club" else set()
    if set(params) - allowed:
        raise ValueError("invalid_command")
    out = params.copy()
    for key, value in out.items():
        if key == "fresh":
            valid = type(value) is bool
        elif key == "position":
            valid = value in {"GK", "CB", "LB", "RB", "LWB", "RWB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "CF", "ST"}
        else:
            valid = integer(value, 1 if key in {"definition_id", "page", "count"} else 0)
        if not valid:
            raise ValueError("invalid_command")
    if out.get("count", 1) > (21 if operation == "search" else 100) or out.get("page", 1) > 2 or out.get("start", 0) > 10000:
        raise ValueError("invalid_command")
    if out.get("min_buy", 0) > out.get("max_buy", 2**53-1):
        raise ValueError("invalid_command")
    return {"operation": operation, "params": out}


def pseudonym(value, namespace, key):
    if value is None:
        return None
    if not ((type(value) is str and re.fullmatch(r"[0-9]{1,24}", value)) or integer(value)):
        raise ValueError("unsafe_integer")
    return namespace + ":" + hashlib.sha256(f"{key}|{namespace}|{value}".encode()).hexdigest()[:24]


def project_item(raw, key):
    if not isinstance(raw, dict):
        raise ValueError("schema_unrecognized")
    return {"item_id": pseudonym(raw.get("id"), "item", key),
            **{target: raw.get(source) if integer(raw.get(source)) else None for target, source in
               [("resource_id", "resourceId"), ("definition_id", "definitionId"), ("asset_id", "assetId"),
                ("rating", "rating"), ("rarity", "rareflag"), ("nation", "nationId"), ("league", "leagueId"),
                ("club", "teamId"), ("market_average", "marketAverage"), ("last_sale_price", "lastSalePrice")]},
            "position": raw.get("preferredPosition") if raw.get("preferredPosition") in {"GK", "CB", "LB", "RB", "LWB", "RWB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "CF", "ST"} else None,
            "untradeable": raw.get("untradeable") if type(raw.get("untradeable")) is bool else None}


def project_auction(raw, key):
    return {"trade_id": pseudonym(raw.get("tradeId"), "trade", key),
            **{target: raw.get(source) if integer(raw.get(source), -1 if target == "expires" else 0) else None for target, source in
               [("starting_bid", "startingBid"), ("current_bid", "currentBid"), ("buy_now_price", "buyNowPrice"), ("expires", "expires")]},
            "trade_state": raw.get("tradeState") if raw.get("tradeState") in {"active", "closed", "expired", "inactive"} else None,
            "bid_state": raw.get("bidState") if raw.get("bidState") in {"none", "highest", "outbid", "buyNow", "sold"} else None,
            "item": project_item(raw.get("itemData", {}), key)}


def empty_result(error):
    return {"status": None, "success": False, "error": error, "ea_error_code": None,
            "platform": None, "credits": None, "items": None, "auctions": None,
            "has_more": None, "cache_invalidated": None, "network": []}


def validate_result(value):
    """Positive retention boundary; never save arbitrary service messages or account objects."""
    if not isinstance(value, dict) or set(value) != set(empty_result("internal_error")):
        raise ValueError("schema_unrecognized")
    if value["status"] is not None and not integer(value["status"], 100, 599):
        raise ValueError("schema_unrecognized")
    if type(value["success"]) is not bool or value["error"] not in ERRORS | {None}:
        raise ValueError("schema_unrecognized")
    if value["success"] != (value["error"] is None):
        raise ValueError("schema_unrecognized")
    if value["ea_error_code"] is not None and not integer(value["ea_error_code"]):
        raise ValueError("schema_unrecognized")
    if value["platform"] not in PLATFORMS or value["credits"] is not None and not integer(value["credits"]):
        raise ValueError("schema_unrecognized")
    for k in ["has_more", "cache_invalidated"]:
        if value[k] is not None and type(value[k]) is not bool:
            raise ValueError("schema_unrecognized")
    def item(v):
        if not isinstance(v, dict) or set(v) != ITEM_FIELDS:
            raise ValueError("schema_unrecognized")
        if v["item_id"] is not None and not (isinstance(v["item_id"], str) and re.fullmatch(r"item:[a-f0-9]{24}", v["item_id"])):
            raise ValueError("schema_unrecognized")
        for k in NUMERIC_ITEM_FIELDS:
            if v[k] is not None and not integer(v[k]):
                raise ValueError("schema_unrecognized")
        if v["position"] is not None:
            command("search", {"position": v["position"]})
        if v["untradeable"] is not None and type(v["untradeable"]) is not bool:
            raise ValueError("schema_unrecognized")
    for field in ["items", "auctions"]:
        rows = value[field]
        if rows is None:
            continue
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("schema_unrecognized")
        for row in rows:
            if field == "items":
                item(row)
                continue
            if not isinstance(row, dict) or set(row) != AUCTION_FIELDS:
                raise ValueError("schema_unrecognized")
            if row["trade_id"] is not None and not (isinstance(row["trade_id"], str) and re.fullmatch(r"trade:[a-f0-9]{24}", row["trade_id"])):
                raise ValueError("schema_unrecognized")
            for k in ["starting_bid", "current_bid", "buy_now_price", "expires"]:
                if row[k] is not None and not integer(row[k], -1 if k == "expires" else 0):
                    raise ValueError("schema_unrecognized")
            if row["trade_state"] not in {None, "active", "closed", "expired", "inactive"} or row["bid_state"] not in {None, "none", "highest", "outbid", "buyNow", "sold"}:
                raise ValueError("schema_unrecognized")
            item(row["item"])
    if not isinstance(value["network"], list) or len(value["network"]) > 30:
        raise ValueError("schema_unrecognized")
    for n in value["network"]:
        if not isinstance(n, dict) or set(n) != {"host", "path", "status", "session_header_present"}:
            raise ValueError("schema_unrecognized")
        if not isinstance(n["host"], str) or not re.fullmatch(r"utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com", n["host"]) or not re.fullmatch(r"/ut/game/fc27/(?:user/credits|user/currencies|transfermarket|club|purchased/items|unassigned|tradepile|usermassinfo)", n["path"]):
            raise ValueError("schema_unrecognized")
        if not integer(n["status"], 100, 599) or type(n["session_header_present"]) is not bool:
            raise ValueError("schema_unrecognized")
    return value


class Transport(Protocol):
    name: str
    def read(self, operation: str, params: dict, evidence_key: str) -> dict: ...


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


class EdgeTransport:
    name = "edge"
    def __init__(self, port=8767):
        self.base = f"http://127.0.0.1:{port}"

    def read(self, operation, params, evidence_key):
        body = command(operation, params) | {"evidence_key": evidence_key}
        try:
            with opener().open(self.base + "/health", timeout=3) as response:
                health = json.loads(response.read(2048))
            if health.get("service") != "fc-read-bridge-v1" or health.get("protocol") != 1 or health.get("attached") is not True:
                return empty_result("bridge_not_attached")
            request = urllib.request.Request(self.base + "/run", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with opener().open(request, timeout=70) as response:
                return validate_result(json.loads(response.read(262144)))
        except urllib.error.HTTPError as e:
            return empty_result("bridge_busy" if e.code == 409 else "bridge_unavailable")
        except (OSError, ValueError, TypeError):
            return empty_result("bridge_unavailable")


@dataclass(frozen=True)
class Session:
    """Injected in memory by a trusted owner. Never logged, serialized or scraped from Edge."""
    host: str
    sid: str
    platform: str | None = None

    def __repr__(self):
        return "Session(<redacted>)"


class DirectHTTPTransport:
    name = "direct_http"
    def __init__(self, session_provider: Callable[[], Session | None] = lambda: None, http=None):
        self.provider, self.http = session_provider, http or opener()

    def read(self, operation, params, evidence_key):
        command(operation, params)
        session = self.provider()
        if session is None:
            return empty_result("direct_session_provider_unavailable")
        if not re.fullmatch(r"utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com", session.host) or session.platform not in PLATFORMS:
            return empty_result("schema_unrecognized")
        routes = {"coins": "user/credits", "club": "club", "unassigned": "unassigned",
                  "purchased": "purchased/items", "transfer_list": "tradepile", "search": "transfermarket"}
        query = {}
        if operation in {"club", "search"}:
            query = {"type": "player", "start": params.get("start", (params.get("page", 1)-1)*20), "num": params.get("count", 21 if operation == "search" else 20)}
        for key, target in {"definition_id": "definitionId", "max_buy": "maxb", "min_buy": "minb", "nation": "nat", "league": "leag", "club": "team", "rarity": "rarityIds", "position": "pos"}.items():
            if key in params:
                query[target] = params[key]
        path = "/ut/game/fc27/" + routes[operation]
        request = urllib.request.Request("https://" + session.host + path + ("?" + urllib.parse.urlencode(query) if query else ""), headers={"X-UT-SID": session.sid, "Accept": "application/json"}, method="GET")
        out = empty_result("network_error")
        try:
            with self.http.open(request, timeout=15) as response:
                out["status"] = response.status
                raw = response.read(2000001)
                if len(raw) > 2000000:
                    raise ValueError("schema_unrecognized")
                body = json.loads(raw)
            out.update(platform=session.platform, network=[{"host": session.host, "path": path, "status": out["status"], "session_header_present": True}])
            if operation == "coins":
                if not integer(body.get("credits")):
                    raise ValueError("schema_unrecognized")
                out["credits"] = body["credits"]
            else:
                field = "auctionInfo" if operation in {"search", "transfer_list"} else "itemData"
                rows = body.get(field)
                if not isinstance(rows, list) or len(rows) > 100:
                    raise ValueError("schema_unrecognized")
                out["auctions" if field == "auctionInfo" else "items"] = [(project_auction if field == "auctionInfo" else project_item)(r, evidence_key) for r in rows]
            out.update(success=True, error=None)
        except urllib.error.HTTPError as e:
            out.update(status=e.code, error="http_error")
        except (OSError, ValueError, TypeError, AttributeError):
            out["error"] = "schema_unrecognized" if out["status"] else "network_error"
        return validate_result(out)


class Harness:
    def __init__(self, transports, evidence_key=None):
        self.transports = transports
        self.key = evidence_key or secrets.token_hex(16)
        self.attempts = []

    def read(self, transport, operation, params=None):
        params = {} if params is None else params
        request = command(operation, params)
        began = time.perf_counter()
        stamp = utc()
        try:
            result = validate_result(self.transports[transport].read(operation, params, self.key))
        except Exception:
            # No exception text crosses the retention boundary.
            result = empty_result("internal_error")
        attempt = {"observed_at": stamp, "transport": transport, "operation": operation,
                   "request": request["params"], "method": METHODS[operation] if transport == "edge" else "GET (candidate REST mapping)",
                   "elapsed_ms": round((time.perf_counter()-began)*1000, 3), "result": result}
        self.attempts.append(attempt)
        return attempt

    def suite(self):
        """Finite read plan; no automatic retries. A live result supplies the target card."""
        for name in self.transports:
            for op in ["coins", "club", "unassigned", "purchased", "transfer_list"]:
                self.read(name, op, {"count": 20, "start": 0} if op == "club" else {})
            first = self.read(name, "search", {"page": 1, "count": 21, "fresh": True})
            rows = first["result"]["auctions"] or []
            # Probe page 2 even if page 1 could not be read: record the exact unavailable path.
            self.read(name, "search", {"page": 2, "count": 21, "fresh": False})
            target = next((r for r in rows if r["item"]["definition_id"] and r["buy_now_price"]), None)
            if target:
                base = {"definition_id": target["item"]["definition_id"], "max_buy": target["buy_now_price"], "page": 1, "count": 21, "fresh": True}
                self.read(name, "search", base)
                self.read(name, "search", base | {"page": 2, "fresh": False})
                self.read(name, "search", base | {"fresh": False})
                self.read(name, "search", base | {"fresh": True})
                for f in ["nation", "league", "club", "rarity", "position"]:
                    if target["item"][f] is not None:
                        # A fixed card already implies its club/nation/etc.
                        # Test filters on a broader population so ignored DTO
                        # properties cannot look supported just by coincidence.
                        self.read(name, "search", {k:v for k,v in base.items() if k != "definition_id"} | {f: target["item"][f]})

    def save(self, path=EVIDENCE):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Caller timestamps/methods are internal, all external responses validated again.
        for a in self.attempts:
            command(a["operation"], a["request"])
            validate_result(a["result"])
        record = {"schema": 1, "source": "fc-read-harness", "captured_at": utc(), "attempts": self.attempts}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("compare", help="Run a finite read plan on both adapters; retain sanitized results")
    read = sub.add_parser("read", help="Exactly one read")
    read.add_argument("transport", choices=["edge", "direct_http"])
    read.add_argument("operation", choices=sorted(OPERATIONS))
    read.add_argument("--params", default="{}", help="JSON of allowlisted numeric/filter parameters")
    parser.add_argument("--output", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    harness = Harness({"edge": EdgeTransport(), "direct_http": DirectHTTPTransport()})
    if args.action == "compare":
        harness.suite()
    else:
        try:
            params = json.loads(args.params)
            harness.read(args.transport, args.operation, params)
        except (ValueError, TypeError):
            parser.exit(2, "invalid_command\n")
    record = harness.save(args.output)
    print(json.dumps({"attempt_count": len(record["attempts"]), "successful_reads": sum(a["result"]["success"] for a in record["attempts"]), "errors": sorted({a["result"]["error"] for a in record["attempts"] if a["result"]["error"]})}))
    return 0 if all(a["result"]["success"] for a in record["attempts"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
