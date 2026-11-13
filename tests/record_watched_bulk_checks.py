"""Record real final offline validators once. No browser or EA operations."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'docs/research/001c/001c-03/checks.json'
if target.exists():
    raise SystemExit('retained checks already exist; use a new artifact for any later run')
checks=[]
for file in ['tests/test_watched_bulk_v1.py','tests/test_watched_bulk_artifacts.py']:
    start=time.perf_counter()
    p=subprocess.run([sys.executable,file],cwd=ROOT,capture_output=True,text=True,timeout=120)
    checks.append({'command':['{python}',file],'returncode':p.returncode,'duration_seconds':time.perf_counter()-start,
                   'stdout':p.stdout,'stderr':p.stderr})
target.write_text(json.dumps({'task':'001c-03','checks':checks,
    'earlier_regressions_observed_in_worker_tool_output':[
        {'command':['{python}','tests/test_bidding_v1.py'],'tests':25,'returncode':0},
        {'command':['{python}','tests/test_market_discovery_followup_v1.py'],'tests':9,'returncode':0},
        {'command':['{python}','tests/test_001c01_audit.py'],'tests':18,'returncode':0}]},indent=2))
print(json.dumps([{'command':x['command'],'returncode':x['returncode']} for x in checks]))
raise SystemExit(any(x['returncode'] for x in checks))
