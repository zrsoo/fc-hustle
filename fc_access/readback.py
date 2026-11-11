"""Read the already acquired card's listing; never dispatch a mutation or change its journal."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .harness import ROOT, command, utc, validate_result
from .transaction import JOURNAL, TransactionTransport, fresh


def assess_listing(capture, journal, *, now=None):
    """Require fresh authenticated exact physical/version/trade/price/active-state evidence."""
    errors = []
    try:
        if set(capture) != {"source", "observed_at", "result"} or capture["source"] != "fc-acquired-listing-readback":
            raise ValueError()
        stamp = datetime.fromisoformat(capture["observed_at"])
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        if stamp.tzinfo is None or not 0 <= age <= 120:
            errors.append("readback_stale_or_future")
        result = validate_result(capture["result"])
        if not fresh({"result": result}, "transfer_list"):
            errors.append("fresh_authenticated_transfer_list_required")
        selected, listing = journal["selection"], journal["listing"]
        historical = [a for a in journal["attempts"] if a["phase"] == "after_list" and a["operation"] == "transfer_list"]
        old_trades = {r["trade_id"] for a in historical for r in a["result"]["auctions"] or []
                      if r["item"]["item_id"] == selected["item"]["item_id"]}
        platforms = {a["result"]["platform"] for a in historical}
        matches = [r for r in result["auctions"] or [] if
                   r["item"]["item_id"] == selected["item"]["item_id"] and
                   r["item"]["definition_id"] == selected["item"]["definition_id"] and
                   r["trade_id"] in old_trades and r["trade_id"] != selected["trade_id"] and
                   r["starting_bid"] == listing["starting_bid"] and
                   r["buy_now_price"] == listing["buy_now_price"] and
                   r["trade_state"] == "active" and (r["expires"] or 0) > 0]
        if len(matches) != 1 or result["platform"] not in platforms or result["platform"] is None:
            errors.append("original_acquired_card_active_listing_not_observed")
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append("invalid_readback_or_checkpoint")
    return {"status": "UNVERIFIED" if errors else "VERIFIED", "errors": errors,
            "scope": "Current listing only; acquisition proof stays in the historical journal. No mutations."}


def capture_listing(journal, transport):
    # The read-only schema rejects writes even though the underlying bridge also
    # supports them. Reuse the public correlation key to match the original item.
    request = command("transfer_list", {})
    stamp = utc()
    result = validate_result(transport.read(request["operation"], request["params"], journal["evidence_key"]))
    return {"source": "fc-acquired-listing-readback", "observed_at": stamp, "result": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    private = (ROOT / "private-captures").resolve()
    if not target.is_relative_to(private) or target.exists():
        parser.error("use a new output file under private-captures/; retained evidence is immutable")
    try:
        journal = json.loads(JOURNAL.read_text(encoding="utf-8"))
        capture = capture_listing(journal, TransactionTransport())
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(capture, indent=2) + "\n")
        result = assess_listing(capture, journal)
    except (OSError, ValueError, KeyError, TypeError):
        result = {"status": "UNVERIFIED", "errors": ["readback_unavailable_or_invalid"]}
    print(json.dumps(result))
    return int(result["status"] != "VERIFIED")


if __name__ == "__main__":
    raise SystemExit(main())
