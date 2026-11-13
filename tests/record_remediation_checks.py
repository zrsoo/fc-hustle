"""Record finite OFFLINE checks; no EA access, browser recovery or source pins."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/research/001d/final-remediation/offline-final'


def run():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-name', default='offline-final')
    args = parser.parse_args()
    if not re.fullmatch(r'offline-[a-z0-9-]+', args.output_name):
        raise ValueError('new_offline_receipt_name_required')
    OUT = OUT.parent/args.output_name
    OUT.mkdir()  # A completed receipt must never be overwritten.
    commands = [[sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']]
    commands += [['node', p.relative_to(ROOT).as_posix()] for p in sorted((ROOT/'tests').glob('*checks.cjs'))]
    commands += [[sys.executable, *args] for args in (
        ['tests/validate_001c06_complete.py'],
        ['-m', 'fc_access.release_audit_v1'],
        ['tests/test_001d07_handoff.py'],
        ['tests/check_bidding_v1_artifacts.py'],
        ['docs/research/001d/001d-07/consume_handoff.py'],
        ['tests/validate_remediation_live.py'])]
    commands += [['git', 'diff', '--check']]
    results = []
    for i, command in enumerate(commands):
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        ended = datetime.now(timezone.utc).isoformat()
        output = f'check-{i:02}.txt'
        (OUT/output).write_bytes(result.stdout)
        count = re.search(rb'Ran (\d+) tests?', result.stdout)
        row = dict(command=['{python}' if a == sys.executable else a for a in command],
                   started_utc=started, ended_utc=ended, exit_code=result.returncode,
                   tests_run=int(count[1]) if count else None, output=output,
                   output_sha256=hashlib.sha256(result.stdout).hexdigest())
        results.append(row)
        (OUT/'checks.json').write_text(json.dumps(dict(mode='OFFLINE', EA_requests=0,
            live_account_mutations=0, checks=results), indent=2)+'\n', encoding='utf-8')
        print(json.dumps(row), flush=True)
    return int(any(row['exit_code'] for row in results))


if __name__ == '__main__':
    raise SystemExit(run())
