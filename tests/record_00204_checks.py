"""Record actual offline subprocess results; never contacts EA or starts live actors."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CHECKS=[
    ['tests/test_00204_actors.py'],
    ['tests/check_00204_artifacts.py'],
    ['tests/test_bidding_v1.py'],
    ['tests/test_001d02_contract.py'],
    ['tests/test_001d03_native_prices.py'],
    ['tests/test_001d04_pricing.py'],
    ['tests/test_001d06_foundation.py'],
    ['tests/validate_00203_gate.py','--attempt','20261114-adapter-repair-gate-06'],
]


def main():
    destination=ROOT/'docs/research/002/002-04/verification'
    destination.mkdir(parents=True,exist_ok=True)
    def run(args):
        start=time.monotonic()
        result=subprocess.run([sys.executable,*args],cwd=ROOT,capture_output=True,text=True,timeout=120)
        name=Path(args[0]).stem+'.txt'
        (destination/name).write_text(result.stdout+result.stderr,encoding='utf8')
        return dict(command=['{python}',*args],exit_code=result.returncode,
            elapsed_seconds=time.monotonic()-start,output=name)
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(run,CHECKS))
    summary=dict(at=datetime.now(timezone.utc).isoformat(),source='offline_fixture_and_retained_evidence',
        live_actors_started=0,checks=results)
    (destination/'results.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(summary))
    return int(any(r['exit_code'] for r in results))


if __name__=='__main__':raise SystemExit(main())
