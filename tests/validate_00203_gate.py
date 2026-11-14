"""Read-only independent acceptance of the single retained live gate; no reruns."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1.gate_00203 import require_pass, selected_checkpoint, CHECKPOINT, AUTHORIZED_ATTEMPT, THIRD_ATTEMPT, FOURTH_ATTEMPT

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--original',action='store_true')
    group.add_argument('--attempt',choices=[AUTHORIZED_ATTEMPT,THIRD_ATTEMPT,FOURTH_ATTEMPT])
    args=parser.parse_args()
    path=CHECKPOINT if args.original else selected_checkpoint(args.attempt)
    try:
        print(json.dumps(dict(checkpoint=str(path.relative_to(Path(__file__).resolve().parents[1])),**require_pass(path))))
    except (ValueError, KeyError, OSError, TypeError) as e:
        print(json.dumps(dict(status='FAILURE/BLOCKED', diagnostic=str(e))))
        sys.exit(1)
