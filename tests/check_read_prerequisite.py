"""Human prerequisite only. No evidence files, EA requests or acceptance checks."""
import json
import sys
import urllib.request


def check():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *args: None})())
    try:
        with opener.open("http://127.0.0.1:8767/health", timeout=3) as response:
            health = json.loads(response.read(1024))
        ready = health == {"service": "fc-read-bridge-v1", "protocol": 1, "bind": "127.0.0.1", "attached": True}
    except (OSError, ValueError):
        ready = False
    return {"status": "READY" if ready else "BLOCKED", "prerequisite": "operator_load_and_click_separate_FC_read_capability_bridge_on_existing_EA_tab", "instructions": "docs/research/confirmed-capabilities.md"}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result))
    sys.exit(0 if result["status"] == "READY" else 1)
