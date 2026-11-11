"""Full task_07 artifact/commit validation. No browser access or purchases."""
import argparse
import json
from final_audit import validate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--precommit", action="store_true", help="skip HEAD assertions before the authorized commit")
    args = parser.parse_args()
    try:
        errors = validate(require_commit=not args.precommit)
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors = {0: ["missing_or_invalid_final_artifacts:" + type(error).__name__]}
    print(json.dumps({"status": "FAIL" if errors else "PASS", "criteria": list(range(7)), "errors": errors,
                      "scope": "Historical evidence, retained artifacts, privacy and commit; no new live transaction."}))
    raise SystemExit(bool(errors))
