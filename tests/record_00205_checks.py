"""Refresh synthetic evidence and real offline command results for 002-05."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.config import Config


def main():
    out=ROOT/'docs/research/002/002-05'
    out.mkdir(parents=True,exist_ok=True)
    run=subprocess.run(['node','tests/occupancy_native_checks.cjs',str(out/'native-fixtures.json')],
        cwd=ROOT,capture_output=True,text=True,timeout=40)
    if run.returncode: raise RuntimeError(run.stdout+run.stderr)
    (out/'defaults.json').write_text(json.dumps(Config().export(),indent=2)+'\n')
    results=[]
    for file in ['tests/test_00205_occupancy.py','tests/check_00205_artifacts.py',
            'tests/test_00204_actors.py','tests/check_00204_artifacts.py',
            'tests/test_001d02_contract.py','tests/test_001d05_inventory.py','tests/test_001d06_foundation.py']:
        r=subprocess.run([sys.executable,file],cwd=ROOT,capture_output=True,text=True,timeout=120)
        results.append(dict(command=['{python}',file],returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        print(file,r.returncode,flush=True)
    report=dict(task='002-05',source='synthetic_native_fixtures',live_requests=0,
        recorded_at=datetime.now(timezone.utc).isoformat(),results=results)
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return 1 if any(r['returncode'] for r in results) else 0


if __name__=='__main__':sys.exit(main())
