"""Read-only T7 acceptance audit, including committed bytes. Run from repo root."""
import argparse
import json
import subprocess
from audit_001b import validate

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--precommit', action='store_true')
    args = parser.parse_args()
    try:
        errors = validate(require_commit=not args.precommit)
    except (OSError, ValueError, KeyError, TypeError, AssertionError, subprocess.CalledProcessError) as error:
        errors = {0: ['audit_cannot_complete:' + type(error).__name__]}
    print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'criteria': list(range(5)),
                      'errors': errors, 'scope': 'Offline retained evidence and scoped commit; current live access unverified.'}))
    raise SystemExit(bool(errors))
