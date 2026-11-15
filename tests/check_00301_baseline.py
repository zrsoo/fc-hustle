"""Independent 003-01 artifact checks; no browser commands or EA requests."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from baseline_00301 import (ROOT, OUT, BASELINE, REQUIRED, assess_reads, cache_state,
                           commitments, database, mutation_gate, need, stamp)
from fc_access.actors_v1.final_run import load_evidence

# Historical review boundary, not a pin on current implementation bytes. Later
# objectives must retain this ancestry while being free to evolve production.
BASELINE_REVIEW = 'fd43ec1b051611377d66735f67813d69c3c77338'


def reviewed_change_scope():
    git('merge-base', '--is-ancestor', BASELINE, BASELINE_REVIEW)
    git('merge-base', '--is-ancestor', BASELINE_REVIEW, 'HEAD')
    allowed = ('docs/research/003/003-01/', 'tests/baseline_00301.py',
               'tests/check_00301_baseline.py', 'tests/test_00301_baseline.py')
    need(all(f.startswith(allowed) for f in git('diff', '--name-only', BASELINE, BASELINE_REVIEW).splitlines()),
         'unrelated_baseline_changes')


def git(*args):
    r = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    need(r.returncode == 0, 'git_failed_' + args[0])
    return r.stdout.strip()


def load(name):
    return json.loads((OUT/name).read_text(encoding='utf8'))


def backup():
    return ROOT/load('provenance.json')['backup']


def historical_responses():
    with database(backup()/'3-production-readonly-after.sqlite3') as c:
        return [json.loads(r) for (r,) in c.execute('SELECT result FROM commands WHERE result IS NOT NULL')]


def read_assessment():
    with database(backup()/'2-native.sqlite3') as c:
        runtime = json.loads(c.execute('SELECT body FROM runtime WHERE id=1').fetchone()[0])
    return assess_reads(load_evidence(OUT/'native-opening.jsonl'), runtime['context'], historical_responses())


def criterion_0():
    p = load('provenance.json')
    read = {r['path']: r for r in p['context_reads']}
    need(set(REQUIRED) <= set(read), 'required_context_missing')
    need(all(r['notes'] and r['lines_read'] > 0 and (ROOT/f).is_file() for f, r in read.items()),
         'context_provenance_incomplete')
    need(p['context_read_before_runtime_changes'] is True, 'context_read_order_missing')
    need(any(f.startswith('fc_access/actors_v1/') for f in read) and any(
        f.startswith('fc_access/production_v1/') for f in read), 'production_context_missing')
    handoff = ROOT/p['handoff']
    m = json.loads((handoff/'manifest.json').read_text())
    inspection = json.loads((backup()/'handoff-inspection.json').read_text())
    need(m == inspection['manifest'] and len(m['databases']) == 5, 'handoff_manifest_disagrees')
    git('bundle', 'verify', str(handoff/'repository.bundle'))
    need(m['head'] in git('bundle', 'list-heads', str(handoff/'repository.bundle')), 'handoff_head_absent')
    need(git('apply', '--numstat', str(handoff/'working-tree.patch')) == inspection['patch_numstat'].strip()
         and 'browser/production-v1/page.js' in inspection['patch_numstat'], 'binary_patch_not_inspected')
    tracked = set(git('ls-tree', '-r', '--name-only', BASELINE).splitlines())
    with zipfile.ZipFile(handoff/'untracked-baseline.zip') as z:
        need(z.testzip() is None and len(z.namelist()) == m['untracked_files'] == 44,
             'handoff_archive_invalid')
        need(z.namelist() == inspection['archive_members'] and set(z.namelist()) <= tracked,
             'pending_archive_not_preserved_in_baseline')
    for d in m['databases']:
        with database(handoff/d['backup']) as c:
            need(c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'bad_handoff_database')


def criterion_1():
    p = load('provenance.json'); b = backup()
    m = json.loads((b/'manifest.json').read_text())
    need(m['head'] == BASELINE and m['branch'] == 'main', 'wrong_backup_branch')
    git('bundle', 'verify', str(b/'repository.bundle'))
    need(BASELINE in git('bundle', 'list-heads', str(b/'repository.bundle')), 'baseline_not_bundled')
    need((b/'working-tree.patch').is_file() and (b/'index.patch').is_file() and (b/'status.txt').is_file(),
         'working_tree_not_backed_up')
    with zipfile.ZipFile(b/'untracked.zip') as z:
        need(z.testzip() is None and z.namelist() == m['untracked_files'], 'untracked_not_backed_up')
    need(len(m['databases']) == 5, 'five_backups_required')
    for d in m['databases']:
        with database(b/d['backup']) as c:
            need(c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'bad_new_database_backup')
    need(stamp(p['backup_completed_at']) < stamp(p['first_runtime_change_at']), 'backup_after_modification')
    # Only sealed historical evidence is hashed. Never source, tests, instructions,
    # mutable selectors or current runtime configuration.
    need(len(m['sealed_evidence']) > 400, 'historical_evidence_inventory_missing')
    for e in m['sealed_evidence']:
        path = ROOT/e['path']
        need(path.suffix not in {'.py', '.js', '.cjs', '.ps1'} and path.name != 'series-selection.json',
             'mutable_implementation_integrity_gate_forbidden')
        need(hashlib.sha256(path.read_bytes()).hexdigest() == e['sha256'], 'sealed_historical_evidence_changed')
    # Audit the completed 003-01 review, not all future objective commits.
    # Evidence integrity and consumed-state checks still inspect their real data.
    reviewed_change_scope()


def criterion_2():
    p = load('process-ownership.json')
    need(p['before_scan'] and p['after_scan'], 'process_scan_missing')
    need(not any(r['role'] == 'actor-stack' for r in p['initial_before_tests_scan']) and
         not any(r['role'] == 'actor-stack' for r in p['after_scan']), 'actor_in_process_scan')
    need(any(r['pid'] == 12008 and r['role'] == 'discovery-service' for r in p['initial_before_tests_scan']),
         'old_service_not_identified')
    need(sum(r['role'] == 'production-service' for r in p['after_scan']) == 1,
         'production_service_owner_not_unique')
    need(not p['live_actor_owners_before'] and not p['live_actor_owners_after'], 'competing_actors')
    need(p['stopped_and_awaited'] == [12008], 'old_discovery_service_not_awaited')
    need(p['old_service_exit_verified'] is True, 'old_owner_exit_unproven')
    need(p['transition_order'] == ['STOP_12008', 'AWAIT_EXIT_12008', 'START_READ_ONLY_SERVICE'],
         'ownership_overlap')
    need(p['new_service_mutations_enabled'] is False and p['new_service_role'] == 'production-read-only',
         'unexpected_mutation_authority')
    # Corroborate this owner through captured bridge fences, not just a PASS flag.
    read = read_assessment()
    need(read['fences']['epoch'] == p['new_epoch'] and read['fences']['owner'] == p['new_owner'],
         'service_owner_not_captured')
    need(p['orchestrator_retained_for_current_objective'] is True, 'current_controller_removed')


def criterion_3():
    p = load('review.json')
    need(p['reviewed_commit'] == BASELINE and p['already_committed_before_task'] is True,
         'baseline_commit_provenance_missing')
    need(p['production_review'] and p['limitations'] and len(p['pending_paths_reviewed']) >= 9,
         'review_missing')
    need(git('branch', '--show-current') == 'main', 'not_main')
    git('merge-base', '--is-ancestor', BASELINE, 'HEAD')
    need(git('rev-parse', BASELINE+'^') == p['baseline_parent'], 'baseline_not_separate')
    remote = git('ls-remote', 'origin', 'refs/heads/main').split()[0]
    git('merge-base', '--is-ancestor', BASELINE, remote)
    py = load('python-baseline.json')
    need(py['command'] == ['{python}', '-m', 'unittest', 'discover', '-s', 'tests', '-v']
         and py['exit_code'] == 0 and py['tests_run'] == 744 and py['result'] == 'OK', 'python_baseline_failed')
    node = load('node-baseline.json')
    need(len(node) == 27 and all(r['exit_code'] == 0 and r['stdout'] for r in node), 'node_baseline_failed')
    need({r['command'][1] for r in node} == {f.relative_to(ROOT).as_posix() for f in (ROOT/'tests').glob('*checks.cjs')},
         'node_suite_omitted')
    independent = load('independent-baseline.json')
    need(len(independent) == 4 and all(r['exit_code'] == 0 and r['stdout'] for r in independent),
         'independent_baseline_check_failed')


def criterion_4():
    actual = read_assessment()
    saved = load('reconciliation.json')
    need(saved['native'] == actual, 'reconciliation_native_summary_disagrees')
    j = ROOT/'private-captures/final-remediation/foundation.sqlite3'
    durable = commitments(j, actual['context'])
    need(saved['commitments'] == durable, 'commitments_not_reconciled')
    need(saved['gate'] == mutation_gate(actual, durable) and saved['gate']['allowed'] is False,
         'ambiguous_mutation_bypass')
    need(saved['spendable_after_reservations'] == actual['credits']-durable['reserved_coins'], 'invented_spendable')
    cache = cache_state(ROOT/'private-captures/final-remediation/completed-quotes.sqlite3',
                        actual['context'], stamp(saved['cache']['assessed_at']))
    need(saved['cache'] == cache and len(cache['entries']) > 0, 'cache_freshness_not_assessed')
    # Join each actual captured read to the separately retained production database.
    with database(ROOT/'private-captures/002-bulk-transfer-operations/production-readonly-after.sqlite3') as c:
        for row in load_evidence(OUT/'native-opening.jsonl'):
            if row['kind'] != 'NATIVE_READ':
                continue
            stored = c.execute('SELECT body,result FROM commands WHERE id=?', (row['command']['id'],)).fetchone()
            need(stored and json.loads(stored[0]) == row['command'] and json.loads(stored[1]) == row['response'],
                 'independent_native_destination_disagrees')
    need(saved['fresh_at_capture_only'] is True and saved['requires_new_reads_before_future_mutations'] is True,
         'old_reads_promoted_to_current')


def criterion_5():
    with database(ROOT/'.orchestrator/state.db') as c:
        objective = c.execute('SELECT id,state FROM objective WHERE id=?', ('obj-29bea3b74eb3',)).fetchone()
        task = c.execute('SELECT key,state,attempts,recheck FROM task WHERE objective_id=? AND id=?',
                         ('obj-29bea3b74eb3', '002-12')).fetchone()
        original = json.loads((backup()/'objective002-before.json').read_text())
        need(list(objective) == original['objective'] and list(task) == original['task']
             and objective[1] == task[1] == 'BLOCKED' and task[3] is None, 'objective002_changed_or_rechecked')
        with database(backup()/'4-state.db') as old:
            # No new execution turns for the consumed objective or its tasks.
            owners = ('obj-29bea3b74eb3', 'obj-29bea3b74eb3/%')
            query = 'SELECT id,owner,kind,status,started,ended FROM turn WHERE owner=? OR owner LIKE ? ORDER BY id'
            need(c.execute(query, owners).fetchall() == old.execute(query, owners).fetchall(),
                 'objective002_execution_replayed')
    outcome = json.loads((ROOT/'docs/research/002/002-12/review-05/outcome.json').read_text())
    need(outcome['status'] == 'PARTIAL/NOT FULL PASS' and outcome['unverified'], 'historical_verdict_promoted')
    # Journal and actor mailbox are consumed evidence. This task only appends
    # fresh reads to the transport; no actor counters, budgets or intents change.
    for source, copied in [('private-captures/final-remediation/native.sqlite3', '2-native.sqlite3'),
                           ('private-captures/final-remediation/foundation.sqlite3', '0-foundation.sqlite3')]:
        with database(ROOT/source) as current, database(backup()/copied) as old:
            for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
                need(current.execute('SELECT * FROM '+table).fetchall() == old.execute('SELECT * FROM '+table).fetchall(),
                     'historical_actor_state_or_budget_changed')


CHECKS = [criterion_0, criterion_1, criterion_2, criterion_3, criterion_4, criterion_5]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--criterion', type=int, choices=range(6))
    a = p.parse_args()
    results = []
    for index in range(6) if a.criterion is None else [a.criterion]:
        try:
            CHECKS[index]()
            results.append(dict(criterion=index, status='PASS'))
        except Exception as e:
            results.append(dict(criterion=index, status='FAIL', diagnostic=str(e)))
    print(json.dumps(dict(task='003-01', evidence_class='OFFLINE_ARTIFACT_ASSESSMENT', results=results)))
    return int(any(r['status'] != 'PASS' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
