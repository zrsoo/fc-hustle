"""Strict read-only full acceptance for the actual item-12 continuation series."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_series import audit_series


def selected():
    s=json.loads((ROOT/'docs/research/002/002-12/series-selection.json').read_text())
    for key in ('latest','checkpoint','outcome','evidence_index'):
        path=(ROOT/s[key]).resolve()
        if not path.is_relative_to(ROOT/'docs/research/002/002-12'):raise ValueError('selection_outside_experiment')
    return s


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--criterion',type=int,choices=range(8))
    p.add_argument('--details',action='store_true');args=p.parse_args()
    try:
        s=selected();r=audit_series(ROOT/s['latest'],ROOT/s['checkpoint'])
        criteria=[c for c in r['criteria'] if args.criterion is None or c['index']==args.criterion]
        passed=all(c['status']=='PASS' for c in criteria)
        display=criteria if args.details else [dict(c,observed=sorted(c['observed'])) for c in criteria]
        print(json.dumps(dict(status='PASS' if passed else 'PARTIAL/NOT FULL PASS',criteria=display,evidence_outcome=s['outcome'],
            native_failures=len(r['failures']),runtime_unresolved_intents=r['metrics']['runtime_unresolved_intents']),indent=2))
        return 0 if passed else 1
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as error:
        print(json.dumps(dict(status='NOT FULL PASS',diagnostic=type(error).__name__)));return 1


if __name__=='__main__':raise SystemExit(main())
