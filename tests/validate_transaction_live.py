"""All task_04 criteria; retained LIVE evidence only. Never buys or lists."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.transaction import JOURNAL
from fc_access.transaction_checks import assess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteria", type=int, nargs="+", default=list(range(8)), choices=range(8))
    args = parser.parse_args()
    try:
        record = json.loads(JOURNAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    errors, facts = assess(record)
    relevant = {i: e for i, e in errors.items() if i in args.criteria}
    print(json.dumps({"status": "PASS" if not relevant else "PARTIAL/BLOCKED", "checked_criteria": args.criteria,
                      "errors": relevant, "facts": facts, "evidence": str(JOURNAL.relative_to(ROOT))}))
    return 1 if relevant else 0


if __name__ == "__main__":
    raise SystemExit(main())
