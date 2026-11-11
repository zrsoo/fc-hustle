"""Regenerate the point-in-time research report from sanitized retained attempts."""
import json
from .harness import EVIDENCE
from .capabilities import write_report

if __name__ == "__main__":
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    errors, _ = write_report(record)
    print(json.dumps({"status": "UNVERIFIED" if errors else "PASS", "errors": errors}))
