"""Positive allowlists at the retention boundary. Never echo rejected input."""
from datetime import datetime, timezone
import re

EVENTS = {"configured_request", "authenticated_read", "auth_rejected"}
SHAPES = {"none", "credits", "auctionInfo", "itemData"}
FIELDS = {"event", "observed_at", "game_version", "host", "request_prefix",
          "client_id", "sku", "method", "status", "session_header_present", "response_shape"}
V2_FIELDS = {"observer_version", "route", "response_type"}
ROUTES = {"user/credits", "user/currencies", "usermassinfo", "transfermarket", "club", "other"}


def validate_observation(value, *, now=None):
    if not isinstance(value, dict) or set(value) not in (FIELDS, FIELDS | V2_FIELDS):
        raise ValueError("invalid_fields")
    v = value.copy()
    if "observer_version" in v and (type(v["observer_version"]) is not int or v["observer_version"] != 2
            or v["route"] not in ROUTES or v["response_type"] not in {"json", "text", "arraybuffer", "blob", "document", "unknown"}):
        raise ValueError("invalid_observer_metadata")
    if v["event"] not in EVENTS or v["response_shape"] not in SHAPES:
        raise ValueError("invalid_event")
    if not isinstance(v["game_version"], str) or not re.fullmatch(r"fc[0-9]{2}", v["game_version"]):
        raise ValueError("invalid_version")
    # Narrow EA service host grammar; no user-controlled subdomain or URL suffix.
    if not isinstance(v["host"], str) or not re.fullmatch(r"utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com(?::443)?", v["host"]):
        raise ValueError("invalid_host")
    if v["request_prefix"] != "/ut/game/" + v["game_version"] + "/":
        raise ValueError("invalid_prefix")
    year = v["game_version"][2:]
    if v["client_id"] not in (None, "FC" + year + "_JS_WEB_APP") or v["sku"] not in (None, "FUT" + year + "WEB"):
        raise ValueError("invalid_client")
    if v["method"] not in {"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH"}:
        raise ValueError("invalid_method")
    if type(v["status"]) is not int or not 100 <= v["status"] <= 599 or type(v["session_header_present"]) is not bool:
        raise ValueError("invalid_status")
    if not isinstance(v["observed_at"], str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", v["observed_at"]):
        raise ValueError("invalid_time")
    observed = datetime.fromisoformat(v["observed_at"].replace("Z", "+00:00"))
    if now is not None and abs((now - observed).total_seconds()) > 120:
        raise ValueError("stale_observation")
    if v["event"] == "authenticated_read" and not (
        v["method"] == "GET" and 200 <= v["status"] < 300
        and v["session_header_present"] and v["response_shape"] != "none"
    ):
        raise ValueError("unproven_authentication")
    if "observer_version" in v and v["response_shape"] != "none":
        compatible = {"credits": {"user/credits", "user/currencies", "usermassinfo"},
                      "auctionInfo": {"transfermarket"}, "itemData": {"club"}}
        if v["route"] not in compatible[v["response_shape"]]:
            raise ValueError("route_shape_mismatch")
    if v["event"] == "auth_rejected" and v["status"] not in (401, 403, 440, 460, 461):
        raise ValueError("unproven_rejection")
    return v


def utc_now():
    return datetime.now(timezone.utc)
