"""Explicit one-shot research capture. Three native searches, public GETs, no writes.

Run manually with python -m fc_access.market_probe. This is not a scheduler.
Existing transaction/read journals are never modified.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import secrets
import time
import urllib.error
import urllib.request

from .harness import ROOT, utc
from .transaction import TransactionTransport, fresh

DEST = ROOT / "docs/research/market"
URLS = {
    "manifest": "https://r2.fut.gg/27/manifest.json",
    "catalog": "https://www.fut.gg/api/fut/players/v2/27/?pageSize=1",
    "history_ui": "https://www.fut.gg/players/momentum/",
    "history_label": "https://www.fut.gg/players/history/",
    "price_ranges": "https://www.fut.gg/price-ranges/",
    "history_provider": "https://www.futgenie.gg/posts/view-on-futgenie",
}


def public_get(pair):
    name, url = pair
    row = {"name": name, "url": url, "at": utc(), "status": None}
    start = time.perf_counter()
    request = urllib.request.Request(url, headers={"Accept": "application/json,text/html", "User-Agent": "fc-hustle-research/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read(4_000_001)
            row.update(status=response.status, content_type=response.headers.get("Content-Type"),
                       bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            if len(body) > 4_000_000:
                row["error"] = "response_limit"
            elif "json" in row["content_type"]:
                row["json"] = json.loads(body)
            else:
                # Record only bounded public phrases, not full copyrighted pages.
                decoded = body.decode("utf-8", errors="replace").lower()
                row["markers"] = {s: s in decoded for s in ("6h", "12h", "24h", "price history", "console", "pc", "without an ea fc 27 card")}
    except urllib.error.HTTPError as error:
        row.update(status=error.code, error="http_error")
    except (OSError, ValueError, TypeError):
        row["error"] = "transport_or_schema_error"
    row["elapsed_ms"] = round((time.perf_counter()-start)*1000, 3)
    return row


def capture():
    record = {"schema": 1, "source": "bounded-market-research", "captured_at": utc(), "attempts": []}
    key = secrets.token_hex(16)
    transport = TransactionTransport()
    # Small fixed universe: exact-version comparables, then one follow-up page.
    for params in ({"definition_id": 233731, "max_buy": 7000, "page": 1, "count": 21, "fresh": True},
                   {"definition_id": 233731, "max_buy": 7000, "page": 2, "count": 21, "fresh": False},
                   {"definition_id": 278230, "page": 1, "count": 21, "fresh": True}):
        start = time.perf_counter()
        attempt = {"at": utc(), "operation": "search", "request": params,
                   "method": "services.Item.searchTransferMarket(criteria, page)"}
        attempt["result"] = transport.read("search", params, key)
        attempt["elapsed_ms"] = round((time.perf_counter()-start)*1000, 3)
        attempt["fresh_network"] = fresh(attempt, "search")
        record["attempts"].append(attempt)
    with ThreadPoolExecutor(max_workers=3) as pool:
        record["public"] = list(pool.map(public_get, URLS.items()))
    manifest = record["public"][0]
    if isinstance(manifest.get("json"), dict):
        data = manifest["json"]
        # Only follow the manifest's advertised filenames; never invent hashes.
        import re
        version = data.get("_version")
        for name in ("player-prices-index", "player-prices-ps5-dyn", "player-prices-pc-dyn", "streamlined-pool"):
            digest = data.get(name)
            if type(version) is int and isinstance(digest, str) and re.fullmatch(r"[a-fA-F0-9]{6,128}", digest):
                row = public_get((name, f"https://r2.fut.gg/27/{name}.v{version}.{digest}.json"))
                # Bound retained bulk evidence to shape and sample; public payload hash remains.
                blob = row.pop("json", None)
                if isinstance(blob, dict):
                    row["shape"] = {k: len(v) if isinstance(v, list) else v for k, v in blob.items()}
                    row["sample"] = {k: v[:5] for k, v in blob.items() if isinstance(v, list)}
                record["public"].append(row)
    record["completed_at"] = utc()
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "availability.json").write_text(json.dumps(record, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"native": [(a["result"]["status"], len(a["result"]["auctions"] or [])) for a in record["attempts"]],
                      "public": [(r["name"], r["status"]) for r in record["public"]]}))


if __name__ == "__main__":
    capture()
