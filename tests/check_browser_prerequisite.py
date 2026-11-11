"""Human prerequisite only: is the observer attached to the operator's EA tab?

Does not depend on live.json, FC configuration, authentication or acceptance results.
"""
import json
import sys
import urllib.request


def check():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *args: None})())
    try:
        with opener.open("http://127.0.0.1:8766/health", timeout=3) as response:
            value = json.loads(response.read(1024))
        attached = value == {"service": "fc-config-observer-v1", "bind": "127.0.0.1", "attached": True, "observer_version": 2}
    except (OSError, ValueError):
        attached = False
    return {"status": "READY" if attached else "BLOCKED",
            "prerequisite": "operator_reload_observer_0_2_0_and_click_it_on_existing_EA_tab",
            "instructions": "docs/research/browser-access.md"}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result))
    sys.exit(0 if result["status"] == "READY" else 1)
