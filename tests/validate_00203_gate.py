"""Read-only independent acceptance of the single retained live gate; no reruns."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1.gate_00203 import require_pass

if __name__ == '__main__':
    try:
        print(json.dumps(require_pass()))
    except (ValueError, KeyError, OSError, TypeError) as e:
        print(json.dumps(dict(status='FAILURE/BLOCKED', diagnostic=str(e))))
        sys.exit(1)
