"""Validate current authenticated access and measured request lifecycle facts.

Archived observations remain privacy-checked, but cannot prove current access.
One typed authenticated read plus later successful same-configuration requests
establish the observed request lifecycle; they do not prove session renewal or
repeated authenticated readback. Those facts are reported separately.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.schema import validate_observation


def assess(record, *, now=None):
    now = now or datetime.now(timezone.utc)
    errors = []
    if not isinstance(record, dict) or set(record) != {"schema", "source", "received_at", "observations"}:
        return ["missing_live_evidence"], {}
    if record["schema"] != 1 or record["source"] != "edge-main-world-observer":
        errors.append("unrecognized_source")
    try:
        received = datetime.fromisoformat(record["received_at"])
        if received.tzinfo is None or not 0 <= (now - received).total_seconds() <= 86400:
            errors.append("stale_live_evidence")
    except (ValueError, TypeError):
        errors.append("invalid_receipt_time")
    observations = record.get("observations", [])
    if not isinstance(observations, list) or not observations:
        return errors + ["no_authenticated_observations"], {}
    current, archived = [], []
    for value in observations:
        try:
            value = validate_observation(value)
            observed = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
            age = (now - observed).total_seconds()
            if age < -120:
                errors.append("future_page_observation")
            elif age > 86400:
                archived.append(value)
            else:
                current.append(value)
        except (ValueError, TypeError):
            errors.append("invalid_or_sensitive_observation")
    if not current:
        errors.append("no_current_page_observations")
    authenticated = [v for v in current if v["event"] == "authenticated_read" and v["game_version"] == "fc27"]
    if not authenticated:
        errors.append("criterion_1_authenticated_fc27_page_not_reached")
    targets = {(v["host"], v["request_prefix"]) for v in authenticated}
    if len(targets) != 1:
        errors.append("criterion_3_current_host_prefix_unproven_or_ambiguous")
    matching = [v for v in current if (v["host"], v["request_prefix"]) in targets and v["game_version"] == "fc27"]
    complete = [v for v in authenticated if v["client_id"] is not None and v["sku"] is not None]
    if not complete:
        errors.append("criterion_3_current_client_identifiers_unobserved")
    configurations = {(v["client_id"], v["sku"]) for v in matching
                      if v["client_id"] is not None and v["sku"] is not None}
    if len(configurations) > 1:
        errors.append("criterion_3_ambiguous_client_identifiers")
    anchor = min(complete, key=lambda v: v["observed_at"]) if complete else None
    later = [v for v in matching if anchor and v["observed_at"] > anchor["observed_at"]
             and v["method"] == "GET" and 200 <= v["status"] < 300 and v["session_header_present"]
             and v["client_id"] == anchor["client_id"] and v["sku"] == anchor["sku"]]
    if not later:
        errors.append("criterion_3_request_lifecycle_unobserved")
    summary = {}
    if anchor:
        summary = {k: anchor[k] for k in ("game_version", "host", "request_prefix", "client_id", "sku")}
        summary.update({
            "current_observation_count": len(current), "archived_observation_count": len(archived),
            "authenticated_reads": [{k: v[k] for k in ("observed_at", "response_shape", "status")}
                                    | {"route": v.get("route", "unretained")} for v in authenticated],
            "session_lifecycle": {
                "first_current_request_at": min(v["observed_at"] for v in current),
                "last_current_request_at": max(v["observed_at"] for v in current),
                "authenticated_read_at": anchor["observed_at"],
                "later_successful_request_count": len(later),
                "last_later_successful_request_at": max((v["observed_at"] for v in later), default=None),
                "transport_activity_after_authenticated_read": "OBSERVED" if later else "UNVERIFIED",
                "repeat_authenticated_readback": "OBSERVED" if len({v["observed_at"] for v in authenticated}) >= 2 else "UNVERIFIED",
                "renewal": "UNVERIFIED", "expiry": "UNVERIFIED", "logout_reconnect": "UNVERIFIED",
                "historical_rejections": [{"observed_at": v["observed_at"], "status": v["status"]}
                                          for v in archived if v["event"] == "auth_rejected"],
                "current_rejection_count": sum(v["event"] == "auth_rejected" for v in current),
            },
        })
    return sorted(set(errors)), summary


def validate(record):
    return assess(record)[0]


if __name__ == "__main__":
    try:
        directory = ROOT / "docs/research/browser-access"
        evidence = directory / "live-v2.json"
        if not evidence.exists():
            evidence = directory / "live.json"
        record = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    errors, summary = assess(record)
    print(json.dumps({"status": "FAIL" if errors else "PASS", "errors": errors,
                      "summary": summary,
                      "limitation": "Sanitized page observations; not cryptographic proof. Later HTTP success is transport activity, not repeated authenticated readback or renewal."}))
    sys.exit(bool(errors))
