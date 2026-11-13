"""Relevant offline suites, independently executable from the task workspace."""
from pathlib import Path
import sys
import subprocess
import json

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
MODULES=['test_bidding_v1','test_watched_bulk_v1','test_watched_bulk_artifacts',
    'test_search_validation_v1','test_search_validation_artifacts','test_market_pricing',
    'test_integration_harness','test_market_discovery_transport','test_market_discovery_followup_v1',
    'test_transaction','test_transaction_bridge','test_durability_v1']

if __name__=='__main__':
    failures=[]
    # Existing HTTP suites own daemon handlers/global browser fixtures. Run
    # each independently, as their documented reproduction commands require.
    # Never retry a failure or reinterpret a connection abort as HTTP success.
    for module in MODULES:
        command=[sys.executable,'tests/run_offline_suite.py','tests/'+module+'.py']
        r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=90)
        print(json.dumps({'command':['{python}',*command[1:]],'returncode':r.returncode}),flush=True)
        print(r.stdout+r.stderr,flush=True)
        if r.returncode:failures.append(module)
    raise SystemExit(bool(failures))
