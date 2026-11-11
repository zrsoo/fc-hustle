"""Human attachment prerequisite only; no journal or EA/acceptance requests."""
import json
import sys
import urllib.request


def check():
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *args: None})())
    try:
        with http.open("http://127.0.0.1:8768/health", timeout=3) as response:
            health = json.loads(response.read(2048))
        ready = health == {"service": "fc-transaction-bridge-v3", "protocol": 3, "bind": "127.0.0.1", "attached": True}
    except (OSError, ValueError):
        ready = False
    return {"status": "READY" if ready else "BLOCKED", "prerequisite": "operator_attach_reviewed_FC_one_shot_transaction_bridge_to_existing_official_EA_tab",
            "instructions": "docs/research/purchase-to-list.md"}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "READY" else 1)
