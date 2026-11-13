"""Hash the final source and immutable lifecycle checkpoints for offline audit."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'docs/research/001c/001c-05'


def sources():
    files=list((ROOT/'browser/durability-v1').glob('*'))
    files+=list((ROOT/'fc_access/durability_v1').glob('*.py'))
    files+=list((ROOT/'fc_access/durability_v1').glob('*.ps1'))
    files+=list((ROOT/'tests').glob('*durability*'))
    files+=[ROOT/'tests/test_readiness_regressions.py',ROOT/'tests/run_offline_suite.py']
    return {p for p in files if p.is_file()}


def main():
    checkpoints={p for p in D.glob('*.json') if p.name not in ('manifest.json','checks.json','server-process.json')}
    checkpoints.add(D/'live-final.sqlite')
    files=sources()|checkpoints
    (D/'manifest.json').write_text(json.dumps({'task':'001c-05','files':{
        p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}},indent=2)+'\n')


if __name__=='__main__':main()
