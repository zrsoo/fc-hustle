"""One-time content manifest; excludes mutable runtime SQLite sidecars/logs."""
import hashlib
import json
from pathlib import Path
from .server import DIRECTORY,ROOT

def main():
    files=[]
    for base in ('fc_access/e2e_v1','browser/e2e-v1','docs/research/001c/001c-06'):
        for p in (ROOT/base).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith(('-shm','-wal')) and p.name not in ('live.sqlite','manifest.json','checks.json') and not p.name.endswith('.log'):files.append(p)
    files.extend(ROOT/p for p in ('tests/test_e2e_v1.py','tests/e2e_page_checks.cjs','tests/test_e2e_artifacts.py','tests/check_e2e_v1_acceptance.py','tests/record_e2e_checks.py'))
    value={'schema':1,'task':'001c-06','proof_boundary':'Content consistency only; not independent third-party EA attestation.',
      'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    with (DIRECTORY/'manifest.json').open('x') as f:json.dump(value,f,indent=2);f.write('\n')
if __name__=='__main__':main()
