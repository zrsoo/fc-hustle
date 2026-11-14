"""Independent implementation regression runner; never launches a live actor.

Historical evidence validators only inspect sealed captures. Their provenance
checks neither replay native operations nor qualify as new live E2E evidence.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sorted({p.name for pattern in ('test_001d*.py', 'test_002*.py')
    for p in (ROOT/'tests').glob(pattern)} | {
    'test_bidding_v1.py', 'test_bulk_transfer_v1.py', 'test_watched_bulk_v1.py',
    'test_production_diagnostics.py', 'test_market_pricing.py',
    'test_integration_harness.py', 'test_durability_v1.py'})
NODE = sorted({p.name for pattern in ('production_*checks.cjs', '*native_checks.cjs')
    for p in (ROOT/'tests').glob(pattern)} | {
    'bidding_v1_checks.cjs', 'native_status_checks.cjs', 'pricing_timing_checks.cjs',
    'watched_bulk_v1_checks.cjs', 'bulk_transfer_checks.cjs'})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',action='store_true')
    parser.add_argument('--output',type=Path,help='Exclusive new evidence file; preserves historical recordings')
    args=parser.parse_args()
    rows=[]
    jobs=[([sys.executable,'tests/run_offline_suite.py','tests/'+name],['{python}','tests/run_offline_suite.py','tests/'+name])
          for name in PYTHON]
    jobs += [(['node','tests/'+name],['node','tests/'+name]) for name in NODE]
    for command,display in jobs:
        start=time.monotonic()
        try:
            r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=180)
            output=r.stdout+r.stderr
            row=dict(command=display,exit_code=r.returncode,seconds=round(time.monotonic()-start,3))
            counts=re.findall(r'Ran (\d+) tests? in',output)
            row['python_tests']=sum(map(int,counts))
            if r.returncode:row['failure']=output[-16000:]
            elif display[0]=='{python}' and not row['python_tests']:
                row.update(exit_code=1,failure='No Python tests executed')
        except (subprocess.TimeoutExpired,OSError) as error:
            row=dict(command=display,exit_code=1,failure=type(error).__name__)
        rows.append(row);print(json.dumps(row),flush=True)
    result=dict(schema=1,evidence_class='OFFLINE_IMPLEMENTATION_REGRESSION',
        live_requests=0,live_actor_launches=0,historical_windows_replayed=0,
        status='PASS' if all(r['exit_code']==0 for r in rows) else 'FAIL',checks=rows)
    if args.record:
        path=ROOT/'docs/research/002/002-11/regressions.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    if args.output:
        with args.output.open('x',encoding='utf8') as handle:
            json.dump(result,handle,indent=2)
            handle.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'}),flush=True)
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
