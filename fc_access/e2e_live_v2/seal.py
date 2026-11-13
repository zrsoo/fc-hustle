"""Seal this completed supplement without changing any historical checkpoint."""
import hashlib
import json
from .audit import ROOT,FINAL,inspect,load

def main():
    report=inspect()
    if report!=load(FINAL/'report.json'):raise ValueError('summary_disagrees_with_evidence')
    files=[]
    for base in ('fc_access/e2e_reconcile_v1','fc_access/e2e_resolution_v2','fc_access/e2e_live_v2',
      'browser/e2e-reconcile-v1','browser/e2e-resolution-v2','browser/e2e-live-v2',
      'docs/research/001c/001c-06','docs/research/001c/001c-06-resume-01','docs/research/001c/001c-06-resume-02',
      'docs/research/001c/001c-06-resume-03','docs/research/001c/001c-06-complete'):
        for p in (ROOT/base).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith(('-shm','-wal','.log')) and p.name not in ('live.sqlite','checks.json') and p!=FINAL/'manifest.json':files.append(p)
    files.extend(ROOT/p for p in ('tests/test_e2e_live_v2.py','tests/e2e_live_v2_page_checks.cjs','tests/test_e2e_reconcile_v1.py',
      'tests/test_e2e_complete_artifacts.py','tests/validate_001c06_complete.py','tests/record_e2e_complete_checks.py'))
    value={'schema':1,'task':'001c-06','scope':'COMPLETION_SUPPLEMENT_WITH_UNCHANGED_HISTORICAL_CHECKPOINTS',
      'proof_boundary':'Content consistency, not a third-party EA attestation. Readbacks are genuine locally retained native observations.',
      'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    with (FINAL/'manifest.json').open('x') as f:json.dump(value,f,indent=2);f.write('\n')
if __name__=='__main__':main()
