"""Explicit offline regression recorder. Never an acceptance probe or EA caller."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    suites=['tests/test_00402_controller.py','tests/test_00201_native_status.py','tests/test_001d02_contract.py',
            'tests/test_00304_route_diagnostics.py','tests/test_00304_status_fallback.py','tests/test_00304_receipt_continuation.py',
            'tests/test_00401_design.py']
    commands=[[sys.executable,s] for s in suites]+[['node',str(p.relative_to(ROOT))] for p in sorted((ROOT/'tests').glob('*checks.cjs'))]
    def one(pair):
        index,argv=pair;start=time.monotonic()
        try:
            p=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=110)
            stdout,stderr,code=p.stdout,p.stderr,p.returncode
        except subprocess.TimeoutExpired as e:
            stdout,stderr,code=str(e.stdout or ''),str(e.stderr or ''),124
        (output/f'{index:02d}-stdout.txt').write_text(stdout,encoding='utf-8')
        (output/f'{index:02d}-stderr.txt').write_text(stderr,encoding='utf-8')
        return dict(command=argv,exit=code,seconds=round(time.monotonic()-start,3),stdout=f'{index:02d}-stdout.txt',stderr=f'{index:02d}-stderr.txt')
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(one,enumerate(commands)))
    value=dict(at=datetime.now(timezone.utc).isoformat(),mode='OFFLINE',results=results)
    (output/'results.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(commands=len(results),failed=[r for r in results if r['exit']])))
    return any(r['exit'] for r in results)


if __name__=='__main__':raise SystemExit(run(sys.argv[1]))
