"""Strict, read-only FULL live acceptance. PARTIAL always exits nonzero.

No login, native call, actor, replay, fixture generation or mutable-source hash.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_assessment import audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,default=ROOT/'docs/research/002/002-12/live-01')
    p.add_argument('--criterion',type=int,choices=range(8))
    args=p.parse_args()
    try:
        report=audit(args.run)
        selected=[c for c in report['criteria'] if args.criterion is None or c['index']==args.criterion]
        passed=all(c['status']=='PASS' for c in selected)
        print(json.dumps(dict(task='002-12',status='PASS' if passed else 'PARTIAL/NOT FULL PASS',
            criteria=selected,failures=report['failures'],metrics=report['metrics']),indent=2))
        return 0 if passed else 1
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as error:
        # Fixed local error class only, never arbitrary account exception data.
        print(json.dumps(dict(status='NOT FULL PASS',diagnostic=type(error).__name__)))
        return 1


if __name__=='__main__':raise SystemExit(main())
