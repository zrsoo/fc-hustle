"""Record only offline 001d-02 acceptance/regressions in a new result directory."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/research/001d/001d-02'


def main():
    target = OUT/'validation.json'
    if target.exists():
        raise SystemExit('validation already recorded; preserve existing evidence')
    commands = [['{python}', 'tests/test_001d02_contract.py']]
    commands += [['{python}', 'tests/run_offline_suite.py', 'tests/test_'+name+'.py'] for name in
                 ('001d01_inventory', 'bidding_v1', 'durability_v1', 'e2e_live_v2', 'market_pricing',
                  'search_validation_v1', 'watched_bulk_v1', 'e2e_complete_artifacts')]
    results = []
    for n, argv in enumerate(commands):
        start = datetime.now(timezone.utc).isoformat(); mark = time.monotonic()
        r = subprocess.run([sys.executable if s == '{python}' else s for s in argv], cwd=ROOT,
                           capture_output=True, timeout=120)
        raw = r.stdout+r.stderr; name = f'validation-{n:02}.txt'
        with (OUT/name).open('xb') as f:
            f.write(raw)
        result = dict(command=argv, timeout=120, exit_code=r.returncode, started_utc=start,
                      ended_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=round(time.monotonic()-mark, 3),
                      output=name, output_sha256=hashlib.sha256(raw).hexdigest())
        results.append(result); print(json.dumps(result), flush=True)
    with target.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(dict(task='001d-02', new_EA_requests=0, live_mutations=0, recurring_actors=0, checks=results), f, indent=2)
        f.write('\n')
    raise SystemExit(1 if any(r['exit_code'] for r in results) else 0)


if __name__ == '__main__':
    main()
