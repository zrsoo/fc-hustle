"""Record actual T7 offline tests/replays in a NEW directory; never run live."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from audit_001b import (ROOT, SUITE, REPLAYS, MANIFEST, SUMMARY, ENTRY,
                       digest, load, replay_result, scoped_files, utc, validation_inputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = validation_inputs()
    checks = []
    with tempfile.TemporaryDirectory(prefix='fc-001b-audit-') as directory:
        commands = {'suite': SUITE, **{key: argv+['--output', '{output}'] for key, argv in REPLAYS.items()}}
        for key, command in commands.items():
            output = Path(directory)/(key+'.json')
            argv = [sys.executable if part == '{python}' else str(output) if part == '{output}' else part
                    for part in command]
            started = utc()
            result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=120)
            combined = result.stdout + result.stderr
            record = {'key': key, 'command': command, 'started_utc': started, 'ended_utc': utc(),
                      'exit_code': result.returncode, 'output_sha256': digest(combined)}
            text = combined.decode('utf-8', errors='replace')
            if key == 'suite':
                match = re.search(r'Ran (\d+) tests?', text)
                record['tests_run'] = int(match[1]) if match else 0
                record['skipped_tests'] = bool(re.search(r'skipped=|\.\.\. skipped', text))
                if record['skipped_tests'] or not match or 'FAILED' in text:
                    record['exit_code'] = 1
            elif result.returncode == 0:
                try:
                    record['artifact_checks'] = replay_result(key, json.loads(output.read_bytes()))
                except (AssertionError, ValueError, KeyError, OSError):
                    record['exit_code'] = 1
                    record['artifact_checks'] = {'status': 'SEMANTIC_CHECK_FAILED'}
            checks.append(record)
            print(json.dumps(record), flush=True)
            if record['exit_code']:
                # Failure details stay on the terminal, never in public artifacts.
                print(text, file=sys.stderr)
    summary = {'schema': 1, 'task': 'T7', 'recorded_utc': utc(),
               'status': 'PASS' if all(c['exit_code'] == 0 for c in checks) else 'FAIL',
               'environment': {'python': sys.version.split()[0],
                               'node': subprocess.check_output(['node', '--version'], text=True).strip()},
               'checks': checks, 'inputs_sha256': inputs, 'new_live_requests': 0, 'account_mutations': 0,
               'proof_boundary': 'Actual offline commands. Tests use fixtures and localhost only. No current authentication claim.'}
    (args.output/'validation.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    if summary['status'] != 'PASS':
        return 1
    if inputs != validation_inputs():
        raise RuntimeError('validation_inputs_changed_during_execution')
    # The final destination is deliberately fixed: alternative recordings are
    # useful diagnostics, but cannot silently replace the committed audit.
    if args.output.resolve() == (ROOT/SUMMARY).parent:
        manifest = {'schema': 1, 'task': 'T7', 'sealed_utc': utc(),
                    'baseline_head': load(ENTRY)['baseline_head'],
                    'sha256': {name: digest((ROOT/name).read_bytes()) for name in scoped_files() if name != MANIFEST}}
        (ROOT/MANIFEST).write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
