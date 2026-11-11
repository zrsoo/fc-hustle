"""Validate the retained live capture path; deterministic tests use temporary paths."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.capabilities import assess
from fc_access.harness import EVIDENCE

if __name__ == "__main__":
    try:
        record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        errors, facts = assess(record)
    except (OSError, ValueError, TypeError):
        errors, facts = ["missing_or_invalid_retained_live_evidence"], {}
    print(json.dumps({"status": "FAIL" if errors else "PASS", "errors": errors, "facts": facts,
                      "limitation": "Sanitized retained observations, not cryptographic proof; offline tests are not live evidence."}))
    sys.exit(bool(errors))
