"""003-03 acceptance: real artifact contracts and offline evidence failure cases."""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'))
from actors_fixture import create, CONTEXT
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.native import Mailbox, Broker
from fc_access.continuous_v1.control import Control
from fc_access.continuous_v1.evidence import capture, assess, digest, read_db, records
from check_00303_preparation import load, validate_artifacts, validate_matrix, validate_handoff, REQUIRED


@contextmanager
def edit_copy(path):
    db=sqlite3.connect(path)
    try:
        with db: yield db
    finally:
        db.close()


class PreparationContracts(unittest.TestCase):
    def test_all_seven_acceptance_contracts_and_real_behavior_references(self):
        self.assertGreaterEqual(len(validate_artifacts()), 20)

    def test_each_required_case_is_individually_enforced(self):
        matrix = load('live-coverage-matrix.json')
        for case in REQUIRED:
            with self.subTest(case=case):
                changed = deepcopy(matrix)
                changed['cases'] = [r for r in changed['cases'] if r['id']!=case]
                with self.assertRaisesRegex(ValueError,'missing_or_duplicate'): validate_matrix(changed)

    def test_duplicate_cases_cannot_hide_coverage_gaps(self):
        matrix = load('live-coverage-matrix.json'); matrix['cases'].append(deepcopy(matrix['cases'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'): validate_matrix(matrix)

    def test_missing_requirements_or_fabricated_test_reference_rejected(self):
        for key, value in [('evidence_requirements',[]), ('current_revision_behavioral_checks',
                dict(evidence_class='OFFLINE_REGRESSIONS_ONLY', tests=['test_00302_continuous.ContinuousBehavior.missing']))]:
            matrix=load('live-coverage-matrix.json'); matrix['cases'][0][key]=value
            with self.assertRaises((ValueError,AttributeError)): validate_matrix(matrix)

    def test_offline_and_historical_proof_never_promote_prelaunch_live_case(self):
        for key,value in [('status','LIVE-VERIFIED'),('run_id','old-run'),('evidence',['old callback'])]:
            matrix=load('live-coverage-matrix.json'); matrix['cases'][0]['current_run_live_proof'][key]=value
            with self.assertRaisesRegex(ValueError,'prelaunch_live_claim'): validate_matrix(matrix)
        for rule in ('failed_callback_is_new_success','offline_is_live_proof','prior_is_current_proof','unknown_edges_exhausted'):
            matrix=load('live-coverage-matrix.json'); matrix['rules'][rule]=True
            with self.assertRaisesRegex(ValueError,'dishonest_proof_rule'): validate_matrix(matrix)

    def test_profit_cannot_be_acceptance_gate_or_discard_cost_evidence(self):
        for key,value in [('status','REQUIRED'),('acceptance_required',True),('preserve',[])]:
            matrix=load('live-coverage-matrix.json'); matrix['realized_profit'][key]=value
            with self.assertRaisesRegex(ValueError,'profit_scope'): validate_matrix(matrix)

    def test_evidence_contract_retains_every_identity_and_incident_reference(self):
        matrix=load('live-coverage-matrix.json')
        for field in matrix['evidence_contract']:
            changed=deepcopy(matrix); changed['evidence_contract'].remove(field)
            with self.assertRaisesRegex(ValueError,'evidence_contract'): validate_matrix(changed)

    def test_each_read_only_lifecycle_gate_is_required(self):
        matrix=load('live-coverage-matrix.json')
        for gate in matrix['rules']['read_only_lifecycle']:
            changed=deepcopy(matrix); changed['rules']['read_only_lifecycle'][gate]=False
            with self.assertRaisesRegex(ValueError,'unsafe_lifecycle'): validate_matrix(changed)
        changed=deepcopy(matrix); changed['rules']['prohibited_manufacture'].remove('saturation')
        with self.assertRaisesRegex(ValueError,'manufactured_coverage'): validate_matrix(changed)

    def test_new_case_can_join_matrix_but_cannot_skip_evidence_and_repair_loop(self):
        matrix=load('live-coverage-matrix.json')
        new=deepcopy(matrix['cases'][0]); new['id']='newly_discovered_case'; matrix['cases'].append(new)
        validate_matrix(matrix)
        matrix['rules']['new_cases_join_repair_loop']=False
        with self.assertRaisesRegex(ValueError,'repair_loop'): validate_matrix(matrix)

    def test_monitor_owner_snapshot_and_loss_contracts_reject_unsafe_handoff(self):
        original=load('monitoring-handoff.json')
        mutations=[('owner','ai_turn_is_supervision',True),('owner','single_fenced_owner',False),
            ('owner','transfer_requires_acknowledgement',False),('watchdog','monitor_additional_ea_polls',1),
            ('snapshots','evidence_export_seconds',None),('lost_supervision','count_gap_as_healthy',True),
            ('lost_supervision','blind_replay',True),('lost_supervision','gate_new_dispatch',False),
            ('lost_supervision','await_all_child_exits',False)]
        for section,key,value in mutations:
            changed=deepcopy(original); changed[section][key]=value
            with self.assertRaises(ValueError): validate_handoff(changed)
        changed=deepcopy(original); changed['commands']['stop']=['{python}','-m','unsupported','stop']
        with self.assertRaisesRegex(ValueError,'unsupported_control'): validate_handoff(changed)


class NativeEvidence(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name); self.state=self.root/'state'; self.state.mkdir()
        self.f,self.page,self.clock=create(self.state)
        self.addCleanup(self.page.close); self.addCleanup(self.f.close)
        self.box=Mailbox(self.state/'native.sqlite3'); self.addCleanup(self.box.close)
        self.broker=Broker(self.box,self.f,Config(),now=self.clock.now,clock=self.clock.monotonic,sleep=self.clock.sleep)
        self.broker.initialize()
        self.control=Control(self.state/'control.sqlite3',clock=self.clock.monotonic); self.addCleanup(self.control.close)
        self.run='1'*32
        self.open_run(self.run)
        self.control.append(self.run,'READY')
        self.control.append(self.run,'SNAPSHOT',healthy_observed_seconds=0)
        self.clock.sleep(1); self.control.append(self.run,'SNAPSHOT',healthy_observed_seconds=1)
        self.command=self.f.adapter.envelope(self.f.ids(),'balance',{})
        self.box.enqueue(self.command,'bidder',now=self.clock.now()); self.broker.run_one()
        self.bundle=self.root/'capture'

    def open_run(self,run):
        self.control.append(run,'RUN_OPEN',source='fixture',context=CONTEXT,state_dir=str(self.state),
            journal=str(self.f.journal_path),cache=str(self.f.cache_path),config=Config().export())
        self.control.append(run,'ATTACHED',fences=self.f.adapter.fences,work_start_seq=0)

    def collect(self):
        return capture(self.state,self.state/'transport.sqlite3',self.bundle,revision='offline-fixture-revision')

    def reseal(self,name):
        path=self.bundle/'manifest.json'; value=json.loads(path.read_text())
        value['databases'][name]['sha256']=digest(self.bundle/(name+'.sqlite3'))
        path.write_text(json.dumps(value))

    def test_collects_wal_rows_all_five_databases_without_new_native_calls(self):
        before_calls=len(self.page.calls)
        before_count=self.control.db.execute('SELECT count(*) FROM records').fetchone()[0]
        self.collect(); result=assess(self.bundle)
        self.assertEqual(result['evidence_class'],'OFFLINE_FIXTURE_ONLY')
        self.assertEqual(result['live_coverage'],'LIVE-UNVERIFIED')
        self.assertEqual(result['revision'],'offline-fixture-revision')
        self.assertEqual(result['healthy_segments'][0]['healthy_observed_seconds'],1)
        self.assertEqual(result['commands'][0]['command_id'],self.command['id'])
        self.assertFalse(result['findings'])
        self.assertEqual(len(self.page.calls),before_calls)
        self.assertEqual(self.control.db.execute('SELECT count(*) FROM records').fetchone()[0],before_count)
        for name in ('journal','cache','native','transport','control'):
            self.assertTrue((self.bundle/(name+'.sqlite3')).is_file())

    def test_capture_preserves_incidents_and_unknown_effects_and_never_retries(self):
        self.control.append(self.run,'INCIDENT',incident_id='incident-01',command_id=self.command['id'],known_effects=[],unknown_effects=['bid callback'])
        self.box.db.execute("UPDATE work SET state='UNKNOWN',response=NULL WHERE id=?",(self.command['id'],))
        self.collect(); result=assess(self.bundle)
        self.assertEqual({r['reason'] for r in result['findings']},{'MISSING_RESPONSE_NO_RETRY','UNSETTLED_COMMAND'})
        self.assertEqual(result['incident_and_recovery_references'][0]['kind'],'INCIDENT')
        self.assertEqual(result['live_coverage'],'LIVE-UNVERIFIED')
        self.assertEqual(len(self.page.calls),1)

    def test_failed_callback_remains_failure_despite_retained_native_response(self):
        self.collect()
        with edit_copy(self.bundle/'native.sqlite3') as db:
            response=json.loads(db.execute('SELECT response FROM work').fetchone()[0])
            response['result'].update(success=False,error='service_failed')
            db.execute('UPDATE work SET response=?',(json.dumps(response),))
        with edit_copy(self.bundle/'transport.sqlite3') as db:
            db.execute('UPDATE commands SET result=? WHERE id=?',(json.dumps(response),self.command['id']))
        self.reseal('native'); self.reseal('transport')
        result=assess(self.bundle)
        self.assertEqual(result['findings'][0]['reason'],'FAILED_CALLBACK_RETAINED')
        self.assertEqual(result['live_coverage'],'LIVE-UNVERIFIED')

    def test_sealed_native_evidence_tamper_is_rejected(self):
        self.collect()
        with edit_copy(self.bundle/'native.sqlite3') as db: db.execute("UPDATE work SET reason='tamper'")
        with self.assertRaisesRegex(ValueError,'sealed_evidence_changed'): assess(self.bundle)

    def test_sealed_copy_has_no_wal_mode_and_undigested_sidecar_is_rejected(self):
        self.collect()
        with edit_copy(self.bundle/'native.sqlite3') as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
        (self.bundle/'native.sqlite3-wal').write_bytes(b'undigested WAL evidence')
        with self.assertRaisesRegex(ValueError,'unsealed_evidence_sidecar'): assess(self.bundle)

    def test_fixture_bundle_cannot_be_relabelled_native(self):
        self.collect(); path=self.bundle/'manifest.json'; value=json.loads(path.read_text())
        value['source']='native'; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'source_mismatch'): assess(self.bundle)

    def test_missing_launch_revision_is_rejected_before_collection(self):
        with self.assertRaisesRegex(ValueError,'launch_revision_required'):
            capture(self.state,self.state/'transport.sqlite3',self.bundle,revision='')
        self.assertFalse(self.bundle.exists())

    def test_response_identity_mismatch_rejected_even_with_updated_capture_digest(self):
        self.collect()
        with edit_copy(self.bundle/'native.sqlite3') as db:
            response=json.loads(db.execute('SELECT response FROM work').fetchone()[0]); response['command_id']='0'*32
            db.execute('UPDATE work SET response=?',(json.dumps(response),))
        self.reseal('native')
        with self.assertRaisesRegex(ValueError,'transport_response_mismatch'): assess(self.bundle)

    def test_wrong_mailbox_identity_rejected(self):
        self.collect()
        with edit_copy(self.bundle/'native.sqlite3') as db: db.execute("UPDATE work SET id=?",('0'*32,))
        self.reseal('native')
        with self.assertRaisesRegex(ValueError,'mailbox_id_mismatch'): assess(self.bundle)

    def test_falsified_uptime_and_unrecorded_monitor_gap_rejected(self):
        self.clock.sleep(20); self.control.append(self.run,'SNAPSHOT',healthy_observed_seconds=21)
        self.collect()
        with self.assertRaisesRegex(ValueError,'unrecorded_monitor_gap'): assess(self.bundle)

    def test_runtime_counter_alone_cannot_establish_healthy_uptime(self):
        self.clock.sleep(1); self.control.append(self.run,'SNAPSHOT',healthy_observed_seconds=14400)
        self.collect()
        with self.assertRaisesRegex(ValueError,'healthy_uptime_not_reproducible'): assess(self.bundle)

    def test_stopped_and_restarted_segments_never_sum_to_consecutive_uptime(self):
        self.control.append(self.run,'SUPERVISION_GAP',role='monitor')
        self.control.append(self.run,'STOP_REQUESTED',reason='SUPERVISION_LOST')
        self.clock.sleep(100)
        run2='2'*32; self.open_run(run2); self.control.append(run2,'READY')
        self.control.append(run2,'SNAPSHOT',healthy_observed_seconds=0)
        self.clock.sleep(2); self.control.append(run2,'SNAPSHOT',healthy_observed_seconds=2)
        self.collect(); result=assess(self.bundle)
        self.assertEqual([s['healthy_observed_seconds'] for s in result['healthy_segments']],[1,2])
        self.assertEqual([s['closed'] for s in result['healthy_segments']],[True,False])

    def test_missing_database_never_creates_empty_source_or_completed_bundle(self):
        with self.assertRaisesRegex(ValueError,'required_evidence_database_missing'):
            capture(self.state,self.root/'absent.sqlite3',self.bundle,revision='offline-fixture-revision')
        self.assertFalse((self.root/'absent.sqlite3').exists()); self.assertFalse(self.bundle.exists())

    def test_prelaunch_absent_runtime_is_read_only_failure(self):
        absent=self.root/'absent-state'
        with self.assertRaises(sqlite3.OperationalError):
            capture(absent,self.state/'transport.sqlite3',self.bundle,revision='offline-fixture-revision')
        self.assertFalse(absent.exists())

    def test_existing_capture_is_never_overwritten(self):
        self.collect()
        with self.assertRaises(FileExistsError): self.collect()

    def test_bundle_missing_database_or_unsafe_path_rejected(self):
        self.collect(); path=self.bundle/'manifest.json'; value=json.loads(path.read_text())
        value['databases']['native']['file']='../native.sqlite3'; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'unsafe_evidence_path'): assess(self.bundle)
        del value['databases']['native']; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'incomplete_bundle'): assess(self.bundle)

    def test_structural_assessment_cli_works_and_missing_inputs_fail_without_native_access(self):
        self.collect()
        r=subprocess.run([sys.executable,'-m','fc_access.continuous_v1.evidence','assess',str(self.bundle)],
                         cwd=ROOT,text=True,capture_output=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(json.loads(r.stdout)['live_coverage'],'LIVE-UNVERIFIED')
        r=subprocess.run([sys.executable,'-m','fc_access.continuous_v1.evidence','assess',str(self.root/'missing')],
                         cwd=ROOT,text=True,capture_output=True,timeout=20)
        self.assertNotEqual(r.returncode,0); self.assertEqual(json.loads(r.stdout)['status'],'INVALID_EVIDENCE')


if __name__=='__main__': unittest.main(verbosity=2)
