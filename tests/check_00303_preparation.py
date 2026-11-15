"""Offline artifact contracts and executed behavioral receipts for task 003-03."""
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
OUT = ROOT/'docs/research/003/003-03'
REQUIRED = {
    'discovery_pagination','fresh_pricing','cached_pricing','native_legality_admission',
    'minimum_initial_bid','leading_hold','natural_outbid_rebid','cap_stop','won','lost',
    'physical_ownership','stored_price_listing','sold_clear','expired_relist',
    'occupancy_reservations','capacity_pause_resume','sticky_draining','priority_cadence',
    'reconnect_restart','uncertain_reconciliation','unrelated_browser_activity',
    'lost_supervision','normal_noop_rejection','identity_freshness',
}
FIELDS = {'run_id','revision','context','fences','command_id','operation','params',
    'native_response','network_at','readback_command_ids','trade_id','physical_item_id',
    'definition_id','durable_database_table_key','incident_ids','healthy_segment_id','reviewer_decision'}


def need(value, reason):
    if not value: raise ValueError(reason)


def load(name):
    return json.loads((OUT/name).read_text(encoding='utf8'))


def validate_matrix(matrix):
    need(matrix['schema']==1 and matrix['task']=='003-03' and
         matrix['phase']=='PRELAUNCH_PREPARATION' and matrix['depends_on']=='003-02', 'wrong_scope')
    need(set(matrix['live_status_vocabulary'])=={'LIVE-UNVERIFIED','LIVE-VERIFIED','LIVE-FAILED'}, 'status_vocabulary')
    ids = [r['id'] for r in matrix['cases']]
    need(len(ids)==len(set(ids)) and REQUIRED <= set(ids), 'missing_or_duplicate_cases')
    need(FIELDS <= set(matrix['evidence_contract']), 'incomplete_evidence_contract')
    profit = matrix['realized_profit']
    need(profit['status']=='DEFERRED' and profit['acceptance_required'] is False and
         {'actual paid cost','transaction intents','ownership readbacks'} <= set(profit['preserve']), 'profit_scope')
    rules = matrix['rules']
    need(set(rules['prohibited_manufacture'])=={'wins','sales','outbids','reserve breaches','saturation'}, 'manufactured_coverage')
    for name in ('unknown_edges_exhausted','failed_callback_is_new_success','offline_is_live_proof','prior_is_current_proof'):
        need(rules[name] is False, 'dishonest_proof_rule:'+name)
    need(rules['new_cases_join_repair_loop'] is True and len(matrix['repair_loop'])>=7, 'missing_repair_loop')
    for name in ('gate_new_writes','settle_in_flight','retain_exact_identity_mappings',
                 'retain_current_commitments','no_guessed_historical_ids','no_blind_retries'):
        need(rules['read_only_lifecycle'][name] is True, 'unsafe_lifecycle:'+name)
    tests = []
    for row in matrix['cases']:
        need(row['acceptance_required'] is True and len(row['evidence_requirements'])>=2 and
             all(isinstance(v,str) and len(v)>35 for v in row['evidence_requirements']), 'case_evidence_missing')
        prior = row['prior_live_proof']
        need(prior['status'] in {'SCOPED-HISTORICAL','NO-PRIOR-PROOF'} and prior['scope'], 'prior_scope')
        for ref in prior['references']:
            need((ROOT/ref).is_file(), 'missing_historical_reference')
        need(len(prior['references'])>=2, 'historical_reference_missing')
        behavior = row['current_revision_behavioral_checks']
        need(behavior['evidence_class']=='OFFLINE_REGRESSIONS_ONLY' and behavior['tests'], 'offline_scope')
        for name in behavior['tests']:
            module, cls, method = name.split('.')
            obj = getattr(getattr(importlib.import_module(module), cls), method)
            need(callable(obj) and method.startswith('test_'), 'non_behavioral_reference')
            tests.append(name)
        live = row['current_run_live_proof']
        need(live['status']=='LIVE-UNVERIFIED' and live['run_id'] is None and live['revision'] is None and
             live['evidence']==[] and live['reason'], 'prelaunch_live_claim')
    return list(dict.fromkeys(tests))


def validate_handoff(handoff):
    need(handoff['task']=='003-03' and handoff['state']=='PRELAUNCH_NOT_RUNNING', 'handoff_scope')
    owner = handoff['owner']
    need(owner['role'] and owner['responsibility'] and owner['transfer_requires_acknowledgement'] is True and
         owner['single_fenced_owner'] is True and owner['ai_turn_is_supervision'] is False, 'persistent_owner')
    watch = handoff['watchdog']
    need(watch['local_sample_seconds']==1 and watch['supervisor_monitor_lease_seconds']==10 and
         watch['native_timeout_seconds']==30 and watch['executor_grace_seconds']==10 and
         watch['monitor_additional_ea_polls']==0 and len(watch['metrics'])>=13, 'watchdog_contract')
    snap = handoff['snapshots']
    need(snap['durable_health_seconds']==1 and snap['evidence_export_seconds']==300 and
         snap['cross_database_atomic'] is False and snap['export_failure'] and
         {'incident','stop','before repair','after recovery','ownership handoff'}<=set(snap['also_on']), 'snapshot_contract')
    lost = handoff['lost_supervision']
    for key in ('gate_new_dispatch','preserve_unknown_in_flight_effects','await_all_child_exits',
                'record_gap','recover_requires_fresh_read_only_reconciliation','replacement_requires_old_owner_exit'):
        need(lost[key] is True, 'unsafe_supervision_loss:'+key)
    need(lost['count_gap_as_healthy'] is False and lost['blind_replay'] is False, 'supervision_gap_or_replay')
    commands = handoff['commands']
    for action in ('config','status','stop','recover'):
        need(commands[action][:4]==['{python}','-m','fc_access.continuous_v1',action], 'unsupported_control')
    for action in ('capture','assess'):
        need(commands[action][:4]==['{python}','-m','fc_access.continuous_v1.evidence',action], 'unsupported_evidence_command')
    need('--context' in commands['recover'] and len(handoff['launch_gates'])>=8 and
         handoff['known_unresolved_live_prerequisite'], 'launch_gates_missing')


def validate_artifacts():
    tests = validate_matrix(load('live-coverage-matrix.json'))
    validate_handoff(load('monitoring-handoff.json'))
    # Procedure requirements are human-review contracts, supplemented by executable
    # collector/assessor negative tests; no file hashes or byte identity gates.
    procedure = (OUT/'independent-assessment.md').read_text(encoding='utf8')
    for term in ('reviewer identity','RECOVERY_READ','native_events','readbacks','physical-item',
                 'actual paid cost','INCIDENT','SUPERVISION_GAP','SNAPSHOT','DEFERRED',
                 'LIVE-UNVERIFIED','LIVE-FAILED','unknown edge case','repair'):
        need(term in procedure, 'assessment_procedure_missing:'+term)
    report = (OUT/'REPORT.md').read_text(encoding='utf8')
    need('5000' in json.dumps(load('live-coverage-matrix.json')) and 'UNKNOWN' in report and
         'ghost' in report and 'PARTIAL/NOT FULL PASS' in report, 'handoff_safety_context_missing')
    return tests


def execute_behavior(tests):
    start = time.monotonic()
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames(tests)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    receipt = dict(task='003-03', evidence_class='OFFLINE_REGRESSIONS_ONLY',
        command=['{python}','tests/check_00303_preparation.py'], tests=tests,
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), elapsed_seconds=time.monotonic()-start,
        status='PASS' if result.wasSuccessful() and not result.skipped else 'FAIL', output=stream.getvalue(), node=[])
    for script in ('tests/bulk_background_checks.cjs','tests/list_refresh_checks.cjs'):
        completed = subprocess.run(['node',script], cwd=ROOT, text=True, capture_output=True, timeout=60)
        receipt['node'].append(dict(command=['node',script],exit_code=completed.returncode,
                                    stdout=completed.stdout,stderr=completed.stderr))
        if completed.returncode: receipt['status']='FAIL'
    revision = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True,timeout=10)
    receipt['revision_provenance'] = revision.stdout.strip() if revision.returncode==0 else 'UNAVAILABLE'
    dirty = subprocess.run(['git','status','--porcelain'],cwd=ROOT,text=True,capture_output=True,timeout=10)
    receipt['working_tree_provenance'] = dirty.stdout.splitlines()
    (OUT/'behavioral-results.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    need(receipt['status']=='PASS' and result.testsRun==len(tests), 'behavioral_checks_failed')
    return receipt


if __name__ == '__main__':
    try:
        receipt = execute_behavior(validate_artifacts())
        print(json.dumps(dict(status='PASS',task='003-03',criteria=list(range(7)),
            behavior_tests=receipt['tests_run'],node_suites=len(receipt['node']),
            live_coverage='LIVE-UNVERIFIED',scope='PRELAUNCH_PREPARATION_ONLY')))
    except (ValueError,KeyError,TypeError,ImportError,AttributeError,OSError,subprocess.SubprocessError) as error:
        print(json.dumps(dict(status='FAIL',error=str(error))))
        raise SystemExit(1)
