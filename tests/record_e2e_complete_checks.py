"""Record offline test/evidence checks. No bridge/session recovery or writes."""
import datetime
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'docs/research/001c/001c-06-complete'

def main():
    jobs=[(['tests/test_e2e_live_v2.py'],0),(['tests/test_e2e_reconcile_v1.py'],0),(['tests/test_e2e_complete_artifacts.py'],0),
      (['tests/test_durability_v1.py'],0),(['tests/test_bidding_v1.py'],0),(['tests/test_market_pricing.py'],0),
      (['tests/test_e2e_v1.py'],0),(['tests/test_e2e_artifacts.py'],0),
      (['tests/check_e2e_v1_acceptance.py'],1),(['tests/validate_001c06_complete.py'],0)]
    results=[]
    for i,(args,expected) in enumerate(jobs):
        r=subprocess.run([sys.executable,*args],cwd=ROOT,text=True,capture_output=True,timeout=120)
        log=f'check-{i:02d}.log'
        with (D/log).open('x') as f:f.write(r.stdout+r.stderr)
        results.append({'command':['{python}',*args],'exit_code':r.returncode,'expected_exit':expected,'expectation_met':r.returncode==expected,'output':log})
    with (D/'checks.json').open('x') as f:json.dump({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':results,
      'interpretation':'Historical original live gates remain nonzero; current bounded completion uses independent supplementary proof. Conditional live branches remain UNVERIFIED.'},f,indent=2)
    print(json.dumps(results,indent=2));raise SystemExit(0 if all(x['expectation_met'] for x in results) else 1)
if __name__=='__main__':main()
