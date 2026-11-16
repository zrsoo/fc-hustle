"""Exclusive offline verification receipts; never starts an account worker."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
INDEPENDENT = [
    ['tests/check_00401_artifacts.py'], ['tests/check_00402_artifacts.py'],
    ['tests/validate_00203_gate.py', '--attempt', '20261114-adapter-repair-gate-06'],
    ['tests/validate_00203_stop.py', '--attempt', '20261114-adapter-repair-gate-06'],
    ['tests/validate_adapter_repair.py'], ['tests/check_bulk_blocker_recovery.py'],
    ['tests/check_00301_baseline.py'], ['tests/check_00302_production.py', '--prepublication'],
    ['tests/validate_bulk_transfer_evidence.py'],
]
TARGETED = [
    ['tests/test_00405_handoff.py'], ['tests/test_market_discovery_transport.py'],
    ['tests/check_00401_artifacts.py'], ['tests/check_00402_artifacts.py'],
]


def commands(group):
    if group == 'python':
        return [[sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']]
    if group == 'node':
        return [['node', p.relative_to(ROOT).as_posix()] for p in sorted((ROOT/'tests').glob('*checks.cjs'))]
    if group == 'independent':
        return [[sys.executable, *argv] for argv in INDEPENDENT]
    if group == 'targeted':
        return [[sys.executable, *argv] for argv in TARGETED]
    raise ValueError('unknown_suite_group')


def run(group, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, argv in enumerate(commands(group)):
        start = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=900)
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, code = str(error.stdout or ''), str(error.stderr or ''), 124
        out, err = f'{index:02d}-stdout.txt', f'{index:02d}-stderr.txt'
        (output/out).write_text(stdout, encoding='utf-8')
        (output/err).write_text(stderr, encoding='utf-8')
        counts = re.findall(r'Ran (\d+) tests? in', stderr)
        row = dict(command=['{python}' if a == sys.executable else a for a in argv],
                   exit_code=code, seconds=round(time.monotonic()-start, 3),
                   stdout=out, stderr=err, tests_run=sum(map(int, counts)),
                   finished=datetime.now(timezone.utc).isoformat())
        rows.append(row)
        print(json.dumps(row), flush=True)
    value = dict(task='004-05', evidence_class='OFFLINE_ONLY', group=group,
                 status='PASS' if all(r['exit_code'] == 0 for r in rows) else 'FAIL', results=rows)
    (output/'results.json').write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return int(value['status'] != 'PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=('python', 'node', 'independent', 'targeted'))
    parser.add_argument('output')
    args = parser.parse_args()
    raise SystemExit(run(args.group, args.output))
