"""Run the item-12 behavioral/artifact checks. Never dispatch native operations."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
TESTS=['test_final_run_00212.py','test_final_artifacts_00212.py','test_final_remediation_00212.py',
       'test_final_owned_00212.py','test_final_listing_assessor.py','test_final_timed_relist.py',
       'test_final_series_00212.py','test_final_reconciled_effects_00212.py']


def check(name):
    r=subprocess.run([sys.executable,str(ROOT/'tests'/name)],cwd=ROOT,capture_output=True,text=True,timeout=60)
    output=r.stdout+r.stderr
    result=dict(command=['{python}','tests/'+name],exit_code=r.returncode,
        python_tests=sum(map(int,re.findall(r'Ran (\d+) tests? in',output))))
    if r.returncode:result['failure']=output[-12000:]
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);args=p.parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(check,TESTS))
    passed=all(r['exit_code']==0 and r['python_tests']>0 for r in rows)
    result=dict(schema=1,evidence_class='OFFLINE_ITEM12_BEHAVIOR_AND_ARTIFACT_CHECKS',
        status='PASS' if passed else 'FAIL',live_requests=0,checks=rows)
    if args.output:
        with args.output.open('x',encoding='utf8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result));return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
