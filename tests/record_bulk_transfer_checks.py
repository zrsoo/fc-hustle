"""Finite offline verification receipt. Never starts a native operation or job."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/research/002-bulk-transfer-operations/checks'


if __name__=='__main__':
    OUT.mkdir()
    commands=[[sys.executable,'-m','unittest','discover','-s','tests','-v'],
              [sys.executable,'tests/test_bulk_transfer_v1.py']]
    commands += [['node',p.relative_to(ROOT).as_posix()] for p in sorted((ROOT/'tests').glob('*checks.cjs'))]
    commands += [[sys.executable,*args] for args in (['tests/validate_bulk_transfer_evidence.py'],
        ['-m','fc_access.release_audit_v1'],['tests/test_001d07_handoff.py'])]
    commands += [['git','diff','--check']]
    results=[]
    for index,command in enumerate(commands):
        started=datetime.now(timezone.utc).isoformat()
        r=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
        ended=datetime.now(timezone.utc).isoformat();name=f'check-{index:02}.txt';(OUT/name).write_bytes(r.stdout)
        count=re.search(rb'Ran (\d+) tests?',r.stdout)
        row=dict(command=['{python}' if v==sys.executable else v for v in command],started_utc=started,
            ended_utc=ended,exit_code=r.returncode,tests_run=int(count[1]) if count else None,
            output=name,output_sha256=hashlib.sha256(r.stdout).hexdigest())
        results.append(row)
        (OUT/'results.json').write_text(json.dumps(dict(mode='OFFLINE',EA_requests=0,account_mutations=0,checks=results),indent=2)+'\n',encoding='utf8')
        print(json.dumps(row),flush=True)
    raise SystemExit(any(r['exit_code'] for r in results))
