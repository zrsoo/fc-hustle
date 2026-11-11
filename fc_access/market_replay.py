"""Replay retained asks offline once; never contacts EA or submits an order."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path

from .pricing import MarketKey, Observation, Rules, evaluate

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/research/market/availability.json"


def replay(path=EVIDENCE):
    payload = Path(path).read_bytes()
    evidence = json.loads(payload)
    now = datetime.fromisoformat(evidence["completed_at"])
    groups = {}
    for attempt in evidence["attempts"]:
        # Treat dispatch-to-return delay as part of the observation time. The
        # retained expiry was read inside that interval, so use its START for
        # countdown decay and freshness (conservative).
        start = datetime.fromisoformat(attempt["at"])
        for row in attempt["result"]["auctions"] or []:
            key = MarketKey(row["item"]["definition_id"], attempt["result"]["platform"])
            groups.setdefault(key, []).append(Observation(
                row["trade_id"], row["item"]["item_id"], key, row["buy_now_price"], start,
                row["expires"], row["trade_state"] == "active", attempt["fresh_network"]))
    output = {"kind": "OFFLINE_REPLAY_INDICATIVE_NOT_GUARANTEED", "source_sha256": hashlib.sha256(payload).hexdigest(),
              "evaluated_at": now.isoformat(), "X": 0, "markets": []}
    for key, rows in sorted(groups.items(), key=lambda p: p[0].definition_id):
        candidate = min(rows, key=lambda r: (r.buy_now_price, r.trade_id))
        # Hypothetical bounds for demonstration, NOT observed card-specific caps.
        hypothetical = Rules(key, 150, 15000000, now)
        missing_caps = evaluate(key, rows, candidate, None, now=now, X=0)
        indicative = evaluate(key, rows, candidate, hypothetical, now=now, X=0)
        output["markets"].append({"key": asdict(key), "captured_rows": len(rows),
                                  "distinct_auctions": len({r.trade_id for r in rows}),
                                  "observed_bin_min": min(r.buy_now_price for r in rows),
                                  "observed_bin_max": max(r.buy_now_price for r in rows),
                                  "without_observed_caps": asdict(missing_caps),
                                  "hypothetical_caps_only": asdict(indicative)})
    return output


if __name__ == "__main__":
    print(json.dumps(replay(), indent=2))
