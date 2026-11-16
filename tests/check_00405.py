"""Independent final handoff checks. Read-only: no EA, controller run or refresh."""
from collections import Counter
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
OUT = ROOT/'docs/research/004/004-05'
VERDICT = 'IMPLEMENTATION COMPLETE — FULL CONTROLLER E2E PENDING'


def need(value, reason):
    if not value:
        raise ValueError(reason)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def validate_receipt(receipt, expected, read, *, test_ids=None, expected_group=None):
    need(receipt['task'] == '004-05' and receipt['evidence_class'] == 'OFFLINE_ONLY', 'receipt_scope')
    group = expected_group or ('python' if expected == [['{python}', '-m', 'unittest', 'discover', '-s', 'tests', '-v']] else
                              'node' if expected and all(c[0] == 'node' for c in expected) else 'independent')
    need(receipt['group'] == group, 'receipt_group')
    rows = receipt['results']
    need([r['command'] for r in rows] == expected and bool(rows), 'suite_inventory')
    need(receipt['status'] == 'PASS', 'suite_failed')
    for row in rows:
        need(row['exit_code'] == 0 and row['seconds'] > 0 and row['finished'], 'execution_failed')
        stdout, stderr = read(row['stdout']), read(row['stderr'])
        need(bool((stdout+stderr).strip()), 'missing_output')
        need(not re.search(r'FAILED \(|Traceback \(most recent call last\)|\) \.\.\. skipped\b', stdout+stderr), 'failed_or_skipped')
        if receipt['group'] == 'python':
            count = re.search(r'Ran (\d+) tests? in ([\d.]+)s', stderr)
            need(count and int(count[1]) == row['tests_run'] and stderr.rstrip().endswith('\nOK'), 'python_summary')
            passed = re.findall(r'^\S+ \(([^)]+)\) \.\.\. ok$', stderr, re.M)
            need(test_ids is not None and Counter(passed) == Counter(test_ids) and len(passed) == int(count[1]), 'python_test_inventory')
    return rows


def validate_report_results(group, rows, report):
    count = sum(r['tests_run'] for r in rows) if group == 'python' else len(rows)
    seconds = sum(r['seconds'] for r in rows)
    need(f'| {group} | {count} | PASS | {seconds:.3f} |' in report, 'report_results_mismatch:'+group)


def validate_trace(value, recomputed):
    need(value['classification'] == 'SYNTHETIC_OFFLINE_ONLY', 'synthetic_promoted_to_live')
    need(value == recomputed, 'synthetic_behavior_or_metrics_changed')


def validate_stopped(value):
    need(datetime.fromisoformat(value['observed_at'].replace('Z', '+00:00')).tzinfo is not None, 'missing_observation_time')
    for key in ('production_workers', 'production_listeners', 'scheduled_mutation_jobs'):
        need(value[key] == [], 'active_'+key)


def current_state():
    p = subprocess.run(['powershell', '-NoProfile', '-File', 'tests/collect_00405_state.ps1'],
                       cwd=ROOT, capture_output=True, text=True, timeout=45)
    need(p.returncode == 0, 'state_inspection_failed:'+p.stderr[-300:])
    value = json.loads(p.stdout)
    validate_stopped(value)
    return value


def git(*argv):
    p = subprocess.run(['git', *argv], cwd=ROOT, capture_output=True, text=True, timeout=45)
    need(p.returncode == 0, 'git_failed:'+argv[0])
    return p.stdout.strip()


def validate_publication(receipt, run_git):
    need(receipt['push_exit_code'] == 0 and receipt['push_output'].strip(), 'push_failed')
    need(re.fullmatch('[0-9a-f]{40}', receipt['implementation_commit']), 'commit_missing')
    need(run_git('branch', '--show-current') == 'main', 'wrong_branch')
    need(not run_git('status', '--porcelain', '--untracked-files=normal'), 'uncommitted_changes')
    head = run_git('rev-parse', 'HEAD')
    remote = run_git('ls-remote', 'origin', 'refs/heads/main').split()[0]
    run_git('merge-base', '--is-ancestor', receipt['implementation_commit'], head)
    run_git('merge-base', '--is-ancestor', head, remote)
    paths = run_git('ls-files', '--', 'fc_access/controller_v1', 'browser/production-v1/controller.js',
                    'docs/research/004/REPORT.md', 'tests/check_00405.py').splitlines()
    need('docs/research/004/REPORT.md' in paths and 'fc_access/controller_v1/controller.py' in paths and
         'browser/production-v1/controller.js' in paths and 'tests/check_00405.py' in paths, 'publication_paths_missing')
    return dict(head=head, remote_main=remote, implementation_commit=receipt['implementation_commit'])


def validate_handoff(value, report):
    need(value['verdict'] == VERDICT and VERDICT in report, 'verdict')
    need(value['new_live_windows'] == [] and value['new_ea_requests'] == value['new_mutations'] == 0, 'unbudgeted_probe')
    need(value['deferred'] == ['full_controller_e2e', 'production_cutover', 'soak', 'tuning', 'orchestrator_work'], 'deferred_boundary')
    need([r['criterion'] for r in value['coverage']] == list(range(9)), 'acceptance_coverage')
    for row in value['coverage']:
        need(row['checks'] and row['negative'], 'missing_behavior_or_negative_case')
    operations = {r['operation']: r for r in value['contracts']}
    need(set(operations) == {'status_batch', 'attribution', 'inventory', 'initial_bid', 'rebid', 'move', 'list', 'clear_sold', 'relist_all'}, 'contract_inventory')
    for row in operations.values():
        need(row['classification'] in {'LIVE_VERIFIED_WITH_ACTUAL_LIMIT', 'NOT_NEEDED_UNCHANGED_CONTRACT', 'OFFLINE_VERIFIED_LIVE_LIMITATION'}, 'unsupported_contract_verdict')
        need(row['evidence'] and row['limitation'] and row['rationale'] and row['offline_checks'], 'missing_contract_evidence')
        for name in row['evidence']:
            need((ROOT/name).is_file(), 'missing_evidence:'+name)
        need(row['operation'] in report, 'undocumented_contract')
    need(operations['status_batch']['actual_live_targets'] == 10, 'actual_limit_missing')
    need('60-second window retains expiry risk' in report and
         'discarded uncertainty may create untracked participation' in report, 'required_risks')
    for term in ('Architecture', 'Persistence', 'Verification', 'Failures', 'Timings', 'Probe', 'Hands-on', 'Limitations', 'Publication'):
        need(term in report, 'report_section:'+term)
    for action in ('run', 'status', 'pause', 'stop'):
        need('python -m fc_access.controller_v1 '+action+' ' in report, 'missing_future_cli:'+action)
    need('--port 8784' in report and '--database private-captures/controller-v1/controller.sqlite' in report and
         '--context private-captures/controller-v1/public-context.json' in report, 'future_cli_parameters')


def preservation():
    from fc_access.evidence import is_evidence
    baseline = load(OUT/'preservation.json')
    for name, digest in baseline['evidence'].items():
        need(is_evidence(name) and Path(name).suffix not in {'.sql', '.md'}, 'mutable_integrity_pin')
        need(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, 'evidence_changed:'+name)
    changed = git('diff', '--name-only', baseline['initial_head'], '--', 'docs/research/003', 'objectives/003-production-actor-soak.md')
    need(not changed, 'objective003_records_changed')
    from check_00401_artifacts import legacy_preservation
    return dict(evidence_files=len(baseline['evidence']), legacy=legacy_preservation())


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepublication', action='store_true', help='Verify all gates except the still-pending Git publication')
    args = parser.parse_args()
    manifest = load(OUT/'handoff.json')
    report = (ROOT/'docs/research/004/REPORT.md').read_text(encoding='utf-8')
    validate_handoff(manifest, report)
    from record_00405 import commands
    test_ids = list(ids(unittest.defaultTestLoader.discover(str(ROOT/'tests'))))
    counts = {}
    for group, directory in manifest['verification'].items():
        base = OUT/directory
        expected = [['{python}' if a == sys.executable else a for a in c] for c in commands(group)]
        rows = validate_receipt(load(base/'results.json'), expected,
                                lambda name: (base/name).read_text(encoding='utf-8'), test_ids=test_ids, expected_group=group)
        validate_report_results(group, rows, report)
        counts[group] = sum(r['tests_run'] for r in rows) if group == 'python' else len(rows)
    from check_00402_artifacts import validate as live_artifacts
    live_artifacts()  # Independently parse sealed native GET evidence; no EA requests.
    from record_00403_offline import record
    validate_trace(load(OUT/'synthetic-trace.json'), record())
    historical = preservation()
    validate_stopped(load(OUT/'final-state.json'))
    state = current_state()
    publication = ({'status':'PENDING'} if args.prepublication else
                   validate_publication(load(OUT/'publication.json'), git))
    print(json.dumps(dict(status='REVIEW_READY' if args.prepublication else 'PASS',
                          criteria=[0,1,2,3,4,5,6,8] if args.prepublication else list(range(9)), verdict=VERDICT, counts=counts,
                          preservation=historical, stopped=state, publication=publication)))


if __name__ == '__main__':
    main()
