"""Finite offline regression recorder; never contacts EA or controls Edge.

Capture entry once before publication. Re-running checks writes only this task's
new logs, never preceding evidence. Acceptance validation is a separate script.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/research/001d/001d-07'
CHANGED = [f'tests/test_001d{i:02}_{name}.py' for i, name in (
    (1, 'inventory'), (2, 'contract'), (3, 'native_prices'),
    (4, 'pricing'), (5, 'inventory'), (6, 'foundation'))]
BASELINE = [
    ['tests/run_offline_suite.py', 'tests/test_'+name+'.py'] for name in (
        'bidding_v1', 'durability_v1', 'market_pricing', 'search_validation_v1',
        'watched_bulk_v1', 'e2e_live_v2', 'e2e_reconcile_v1',
        'e2e_complete_artifacts', 'release_audit')
] + [['tests/validate_001c06_complete.py'], ['tests/check_e2e_v1_acceptance.py'],
     ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py']]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def capture():
    if (OUT/'entry.json').exists():
        raise SystemExit('entry already captured; refusing to reset preservation')
    files = set()
    for base in ('docs', 'objectives', 'fc_access', 'browser', 'tests'):
        files.update(p for p in (ROOT/base).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and OUT not in p.parents)
    files.add(ROOT/'AGENTS.md')
    save('entry.json', dict(task='001d-07', captured_at=stamp(),
        git_status=subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True).splitlines(),
        sha256={p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in sorted(files)}))


def run():
    if not (OUT/'entry.json').exists():
        raise SystemExit('capture task entry first')
    records = []
    for i, args in enumerate([[p] for p in CHANGED] + BASELINE):
        started = stamp()
        start = time.monotonic()
        result = subprocess.run([sys.executable, *args], cwd=ROOT,
                                capture_output=True, timeout=120)
        # Retain stdout and stderr verbatim as separate byte streams.
        streams = {}
        for name, raw in (('stdout', result.stdout), ('stderr', result.stderr)):
            path = f'regression-{i:02}.{name}.txt'
            (OUT/path).write_bytes(raw)
            streams[name] = dict(path=path, sha256=sha(raw))
        combined = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        records.append(dict(command=['{python}', *args], exit_code=result.returncode,
            started_at=started, ended_at=stamp(), elapsed_seconds=time.monotonic()-start,
            tests_run=[int(n) for n in re.findall(r'Ran (\d+) tests?', combined)],
            streams=streams))
        print(f'{i:02} {args}: exit {result.returncode}', flush=True)
    save('regressions.json', dict(schema=1, task='001d-07', checks=records,
        new_EA_requests=0, live_mutations=0, recurring_actors=0,
        assertion_changes=[], historical_capture_changes=[]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture-entry', 'run'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    capture() if args.action == 'capture-entry' else run()
