"""Retain exact offline commands and truthful unresolved live-gate exits."""
import datetime
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'docs/research/001c/001c-06'

def main():
    jobs=[(['tests/test_e2e_v1.py'],0),(['tests/test_e2e_artifacts.py'],0),(['tests/test_durability_v1.py'],0),
      (['tests/test_bidding_v1.py'],0),(['tests/test_market_pricing.py'],0),(['tests/test_transaction.py'],0)]
    jobs.extend((['tests/check_e2e_v1_acceptance.py','--criterion',str(i)],1 if i in (1,2) else 0) for i in range(8))
    results=[]
    for i,(args,expected) in enumerate(jobs):
        run=subprocess.run([sys.executable,*args],cwd=ROOT,text=True,capture_output=True,timeout=120)
        logfile=f'check-{i:02d}.log'
        with (D/logfile).open('x') as f:f.write(run.stdout+run.stderr)
        results.append({'command':['{python}',*args],'exit_code':run.returncode,'expected_exit':expected,'expectation_met':run.returncode==expected,'output':logfile})
    with (D/'checks.json').open('x') as f:json.dump({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':results,
      'interpretation':'Unit/artifact checks passing do not satisfy missing live evidence. Live criteria 1 and 2 intentionally remain nonzero/unresolved.'},f,indent=2)
    print(json.dumps(results,indent=2));raise SystemExit(0 if all(x['expectation_met'] for x in results) else 1)
if __name__=='__main__':main()
