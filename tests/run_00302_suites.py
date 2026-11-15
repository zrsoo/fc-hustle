"""Run complete offline inventories and retain actual commands/output receipts."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/research/003/003-02'
INDEPENDENT = [
    ['tests/validate_00203_gate.py','--attempt','20261114-adapter-repair-gate-06'],
    ['tests/validate_00203_stop.py','--attempt','20261114-adapter-repair-gate-06'],
    ['tests/validate_adapter_repair.py'],
    ['tests/check_bulk_blocker_recovery.py'],
    ['tests/check_00301_baseline.py'],
]


def run(group):
    OUT.mkdir(parents=True, exist_ok=True)
    if group == 'python':
        commands = [[sys.executable,'-m','unittest','discover','-s','tests','-v']]
    elif group == 'node':
        commands = [['node',str(p.relative_to(ROOT)).replace('\\','/')] for p in sorted((ROOT/'tests').glob('*checks.cjs'))]
    else:
        commands = [[sys.executable,*argv] for argv in INDEPENDENT]
    results = []
    for n, argv in enumerate(commands):
        start = time.monotonic()
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=600)
        stdout, stderr = f'{group}-{n:02d}-stdout.txt', f'{group}-{n:02d}-stderr.txt'
        (OUT/stdout).write_text(r.stdout, encoding='utf8'); (OUT/stderr).write_text(r.stderr, encoding='utf8')
        summary = re.search(r'Ran (\d+) tests? in ([\d.]+)s', r.stderr) if group == 'python' else None
        result = dict(command=['{python}' if v == sys.executable else v for v in argv], exit_code=r.returncode,
            stdout=stdout, stderr=stderr, elapsed_seconds=round(time.monotonic()-start,3),
            finished=datetime.now(timezone.utc).isoformat())
        if summary: result['tests_run'] = int(summary[1])
        results.append(result)
        print(json.dumps(result), flush=True)
    receipt = dict(task='003-02', evidence_class='OFFLINE_REGRESSIONS_ONLY', group=group, results=results,
                   status='PASS' if all(r['exit_code']==0 for r in results) else 'FAIL')
    (OUT/(group+'-suites.json')).write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    return 0 if receipt['status']=='PASS' else 1


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('group', choices=('python','node','independent'))
    raise SystemExit(run(p.parse_args().group))
