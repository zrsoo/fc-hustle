"""Behavior and retained-artifact checks; passing is not live task completion."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from check_00304_live import (OUT, load, lines, assess_task, browser_contract, segment_contract,
                             stopped_contract, incident_contract, repair_contract, coverage_contract, semantic_case,
                             sealed_artifacts, REQUIRED)
from fc_access.continuous_v1.evidence import read_db, records, assess
from fc_access.production_v1.contracts import parse_response, stamp


def sample_rows(seconds=14400):
    """Small accelerated fixture for assessor arithmetic, never written as evidence."""
    start=datetime(2030,1,1,tzinfo=timezone.utc)
    rows=[dict(seq=1,run='fixture',kind='READY',tick=0,at=start.isoformat(),body={})]
    for tick in range(0,seconds+1,10):
        rows.append(dict(seq=len(rows)+1,run='fixture',kind='SNAPSHOT',tick=tick,
            at=(start+timedelta(seconds=tick)).isoformat(),body=dict(source='native',intents=[],
            actors={r:{} for r in ('bidder','acquirer','maintenance')},maintenance={'reason':'NO_ELIGIBLE_ITEMS'},
            capacity=dict(physical_occupied=5,occupied=5,unresolved=1,pending_resale=0,total=6),
            credits=dict(available_coins=62827),healthy_observed_seconds=tick)))
    return rows


class OperationalAcceptance(unittest.TestCase):
    def setUp(self):
        self.index=load(OUT/'startup-evidence-index.json')
        self.bundle=ROOT/self.index['snapshot']
        with closing(read_db(self.bundle/'control.sqlite3')) as db: self.rows=records(db)
        self.run=self.index['diagnostic_run']
        self.commands={}
        for row in self.rows:
            if row['kind']=='RECOVERY_READ':
                v=row['body'];self.commands[v['command']['id']]=dict(run=row['run'],**v)
        d=next(r for r in lines(OUT/'ghost-status-diagnostic.jsonl') if r['kind']=='NATIVE_READ')
        self.commands[d['command']['id']]=dict(run=self.run,command=d['command'],response=d['response'])
        self.incident=load(OUT/self.index['incidents'][0])

    def test_all_ten_criteria_are_evaluated_and_live_requirements_remain_unfulfilled(self):
        result=assess_task(self.index)
        self.assertEqual({r['criterion'] for r in result['results']},set(range(10)))
        self.assertEqual(result['status'],'INCOMPLETE')
        unmet={r['criterion'] for r in result['results'] if r['status']=='UNFULFILLED'}
        self.assertTrue({0,2,3,5,7,8}<=unmet)
        self.assertTrue(all(r.get('reason') for r in result['results'] if r['status']=='UNFULFILLED'))

    def test_acceptance_cli_exits_nonzero_and_never_starts_work(self):
        r=subprocess.run([sys.executable,'tests/check_00304_live.py','--index',
                          'docs/research/003/003-04/startup-evidence-index.json'],
                         cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,1,r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'],'INCOMPLETE')

    def test_genuine_native_startup_is_independently_retained_without_strategy_claim(self):
        result=assess(self.bundle)
        self.assertEqual(result['evidence_class'],'NATIVE_CAPTURE_REQUIRES_CASE_REVIEW')
        self.assertEqual(result['findings'],[])
        self.assertEqual(result['commands'],[])
        self.assertEqual(result['healthy_segments'][0]['healthy_observed_seconds'],0)
        self.assertEqual({v['command']['operation'] for v in self.commands.values()},
                         {'watched','balance','transfer_list','status'})
        for v in self.commands.values():
            parse_response(v['response'],v['command'],source='native',now=stamp(v['response']['freshness']['observed_at']))

    def test_captured_native_evidence_tampering_is_detected_and_source_pins_are_forbidden(self):
        sealed_artifacts(OUT)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=load(OUT/'captured-evidence-manifest.json')
            for name in [*manifest['captures'],'captured-evidence-manifest.json']:
                shutil.copyfile(OUT/name,root/name)
            native=root/'ghost-status-diagnostic.jsonl'
            original=native.read_text(encoding='utf8')
            native.write_text(original+'\n',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'sealed_capture_changed'):sealed_artifacts(root)
            native.write_text(original,encoding='utf8')
            # No source bytes or source digest are read, generated, or asserted.
            manifest['captures']['AGENTS.md']='forbidden source pin'
            (root/'captured-evidence-manifest.json').write_text(json.dumps(manifest),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'mutable_implementation_digest_forbidden'):sealed_artifacts(root)

    def test_ui_evidence_requires_fresh_instructions_and_own_official_foreground(self):
        rows=lines(OUT/'browser-recovery.jsonl');browser_contract(rows)
        with self.assertRaisesRegex(ValueError,'instructions_not_freshly_read'):
            browser_contract([r for r in rows if r['kind']!='AGENTS_READ'])
        for key in ('official_tab','foreground_verified','edge_control_verified'):
            changed=deepcopy(rows)
            for row in changed:
                if row['kind']=='VERIFIED_UI' and 'official_tab' in row['result']:row['result'][key]=False
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'unverified_official_foreground'):
                browser_contract(changed)

    def test_recovery_cannot_export_credentials_or_substitute_another_saved_account(self):
        for key,val in [('credentials_accessed',True),('session_material_accessed',True),('designated_saved_account','different')]:
            rows=deepcopy(lines(OUT/'browser-recovery.jsonl'))
            next(r for r in rows if r['kind']=='RECOVERY_SCOPE')[key]=val
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'recovery_scope_or_privacy_missing'):
                browser_contract(rows)

    def test_native_restriction_is_exact_and_not_an_authentication_or_market_failure(self):
        c=next(v for v in self.commands.values() if v['command']['operation']=='status')
        self.assertFalse(c['response']['result']['success'])
        self.assertEqual(c['response']['result']['error'],'known_identity_unavailable')
        self.assertEqual(c['response']['freshness']['request_count'],0)
        self.assertEqual(c['response']['result']['network'],[])
        self.assertEqual(c['command']['params']['trade_id'],'trade:057aeb82a3b167642da7aeee')
        # This is a historical identity, not a source-file integrity assertion.
        before=load(OUT/'prelaunch-reconciliation.json')
        with closing(read_db(self.bundle/'journal.sqlite3')) as db:
            for identity in before['durable']['unresolved']:
                row=db.execute('SELECT phase FROM capacity_slots_v1 WHERE trade_id=? AND item_id=?',
                    (identity['trade_id'],identity['item_id'])).fetchone()
                self.assertEqual(row,('UNRESOLVED',))
                self.assertIsNone(db.execute('SELECT id FROM commands WHERE trade_id=?',(identity['trade_id'],)).fetchone())

    def test_incident_requires_diagnosis_account_effects_evidence_and_restart_disposition(self):
        incident_contract(self.incident,self.rows,self.commands)
        for field in ('root_cause','known_account_effects','unknown_account_effects','fix','regression_results','restart_reconciliation'):
            changed=deepcopy(self.incident);changed[field]={}
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'incident_diagnosis_incomplete'):
                incident_contract(changed,self.rows,self.commands)

    def test_missing_native_identity_cannot_become_resolved_or_restarted(self):
        changed=deepcopy(self.incident);changed['restart_reconciliation']['status']='READY'
        with self.assertRaisesRegex(ValueError,'unresolved_incident_restarted'):
            incident_contract(changed,self.rows,self.commands)
        changed=deepcopy(self.incident);changed['evidence_command_ids'].append('missing-command')
        with self.assertRaisesRegex(ValueError,'incident_native_evidence_missing'):
            incident_contract(changed,self.rows,self.commands)

    def test_stop_is_sealed_only_after_each_owned_process_exits(self):
        stopped_contract(self.rows,self.run)
        for kind in ('PROCESS_EXIT','RUN_STOPPED'):
            changed=[r for r in self.rows if r['kind']!=kind]
            with self.subTest(kind=kind),self.assertRaises(ValueError):stopped_contract(changed,self.run)

    def test_repair_requires_awaited_exits_regressions_published_revision_and_fresh_reconciled_owner(self):
        start=datetime(2030,1,1,tzinfo=timezone.utc)
        def row(seq,run,kind,seconds,**body):
            return dict(seq=seq,run=run,kind=kind,at=(start+timedelta(seconds=seconds)).isoformat(),body=body)
        rows=[row(1,'old','RUN_OPEN',0),row(2,'old','ATTACHED',1,fences=dict(owner='old',epoch=1)),
              row(3,'old','PROCESS_STARTED',2,pid=123),row(4,'old','STOP_REQUESTED',3),
              row(5,'old','PROCESS_EXIT',9,pid=123),row(6,'old','RUN_STOPPED',10,
              verified_process_exit=True,healthy_segment_closed=True,remaining_processes=[]),
              row(7,'new','RUN_OPEN',30),row(8,'new','ATTACHED',31,fences=dict(owner='new',epoch=2)),
              row(9,'new','RECONCILED',32,read_ids=['fresh-watched','fresh-balance','fresh-complete-inventory']),
              row(10,'new','READY',33)]
        fix=dict(stopped_run='old',restart_run='new',published_at=(start+timedelta(seconds=25)).isoformat())
        regression=dict(exit_code=0,tests_run=3,failures=0,errors=0,finished_at=(start+timedelta(seconds=21)).isoformat())
        commit=start+timedelta(seconds=20)
        repair_contract(fix,rows,commit_time=commit,published=True,regression=regression)
        for fault in ('exit','early-change','late-push','unpublished','failed-regression','empty-regression','owner','epoch','readbacks'):
            changed=deepcopy(rows);f=deepcopy(fix);r=deepcopy(regression);c=commit;pushed=True
            if fault=='exit':changed=[r for r in changed if r['kind']!='PROCESS_EXIT']
            if fault=='early-change':c=start+timedelta(seconds=5)
            if fault=='late-push':f['published_at']=(start+timedelta(seconds=35)).isoformat()
            if fault=='unpublished':pushed=False
            if fault=='failed-regression':r['exit_code']=1
            if fault=='empty-regression':r['tests_run']=0
            if fault=='owner':changed[7]['body']['fences']['owner']='old'
            if fault=='epoch':changed[7]['body']['fences']['epoch']=1
            if fault=='readbacks':changed[8]['body']['read_ids']=['same-read']*3
            with self.subTest(fault=fault),self.assertRaises(ValueError):
                repair_contract(f,changed,commit_time=c,published=pushed,regression=r)

    def test_stopped_segment_cannot_be_reopened_or_counted_as_healthy(self):
        changed=deepcopy(self.rows)
        changed.append(dict(run=self.run,seq=max(r['seq'] for r in changed)+1,kind='READY',body={}))
        with self.assertRaisesRegex(ValueError,'sealed_segment_reopened'):stopped_contract(changed,self.run)
        with self.assertRaisesRegex(ValueError,'production_never_ready'):segment_contract(self.rows,self.run)

    def test_four_hours_is_a_minimum_from_adjacent_samples_and_not_a_shutdown(self):
        rows=sample_rows();self.assertEqual(segment_contract(rows,'fixture'),14400)
        rows=sample_rows(14410);self.assertEqual(segment_contract(rows,'fixture'),14410)
        with self.assertRaisesRegex(ValueError,'four_consecutive_healthy_hours_missing'):
            segment_contract(sample_rows(14390),'fixture')

    def test_gap_stop_fix_exception_and_restart_never_sum_to_four_hours(self):
        for kind in ('STOP_REQUESTED','RUN_STOPPED','SUPERVISION_GAP','INCIDENT','EXCEPTION'):
            rows=sample_rows();rows.append(dict(run='fixture',kind=kind,seq=len(rows)+1,body={}))
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'healthy_segment_interrupted'):
                segment_contract(rows,'fixture')
        first=sample_rows(7200)
        second=sample_rows(7200)
        for row in second:row['run']='new-fixture'
        with self.assertRaisesRegex(ValueError,'four_consecutive_healthy_hours_missing'):
            segment_contract(first+second,'new-fixture')

    def test_uptime_counter_without_wall_monitor_process_and_account_evidence_is_rejected(self):
        for mutation in ('counter','clock','gap','actors','credits','capacity','intent','source'):
            rows=sample_rows();row=rows[4]
            if mutation=='counter':row['body']['healthy_observed_seconds']=14400
            if mutation=='clock':row['at']=rows[3]['at']
            if mutation=='gap':rows.pop(3)
            if mutation=='actors':row['body']['actors']={}
            if mutation=='credits':row['body']['credits']['available_coins']=-1
            if mutation=='capacity':row['body']['capacity']['total']=51
            if mutation=='intent':row['body']['intents']=[{'state':'UNKNOWN'}]
            if mutation=='source':row['body']['source']='fixture'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):segment_contract(rows,'fixture')

    def test_each_required_case_must_remain_unverified_without_a_witness(self):
        matrix=load(OUT/'live-coverage-matrix.json')
        self.assertEqual({r['id'] for r in matrix['cases']},REQUIRED)
        for case in REQUIRED:
            changed=deepcopy(matrix)
            changed['cases'].sort(key=lambda r:r['id']!=case)
            with self.subTest(case=case),self.assertRaisesRegex(ValueError,'LIVE-UNVERIFIED:'+case):
                coverage_contract(changed,self.commands,self.run,'revision')

    def test_generic_native_get_or_prose_review_cannot_prove_any_required_branch(self):
        balance=[v for v in self.commands.values() if v['command']['operation']=='balance']
        for case in REQUIRED:
            with self.subTest(case=case):self.assertFalse(semantic_case(case,balance,{}))

    def test_no_matrix_case_can_be_removed_duplicated_or_replaced_by_profit_accounting(self):
        matrix=load(OUT/'live-coverage-matrix.json')
        for case in REQUIRED:
            changed=deepcopy(matrix);changed['cases']=[r for r in changed['cases'] if r['id']!=case]
            with self.subTest(case=case),self.assertRaisesRegex(ValueError,'missing_required_matrix_case'):
                coverage_contract(changed,self.commands,self.run,'revision')
        matrix['realized_profit']['acceptance_required']=True
        with self.assertRaisesRegex(ValueError,'profit_scope_changed'):
            coverage_contract(matrix,self.commands,self.run,'revision')

    def test_falsely_promoted_historical_failed_callback_is_rejected(self):
        matrix=load(OUT/'live-coverage-matrix.json');row=matrix['cases'][0]
        failed=next(v for v in self.commands.values() if not v['response']['result']['success'])
        row['current_run_live_proof']=dict(status='LIVE-VERIFIED',run_id=self.run,revision='rev',reviewer='offline-test',
            semantic_assessment='A successful-looking statement cannot replace the failed response',
            evidence=[dict(command_id=failed['command']['id'],database='control',table='records',key=35)])
        with self.assertRaisesRegex(ValueError,'failed_or_historical_callback_promoted'):
            coverage_contract(matrix,self.commands,self.run,'rev')

    def test_restored_service_has_no_mutation_authority_and_original_gate_stays_closed(self):
        h=load(OUT/'restored-health.json')['health']
        self.assertTrue(h['attached']);self.assertFalse(h['mutations_enabled']);self.assertIsNone(h['intent_journal'])
        self.assertFalse(any(r['kind']=='READY' for r in self.rows))
        self.assertFalse(any(r['kind']=='PROCESS_STARTED' and r['body']['role'] in {'acquirer','bidder','maintenance'}
                             for r in self.rows))


if __name__=='__main__':unittest.main(verbosity=2)
