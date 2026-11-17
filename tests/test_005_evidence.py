"""Actual retained envelopes plus negative tampering and quiescent backup checks."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import check_005_stage01 as check
from prepare_005_incident import backup


class EvidenceTests(unittest.TestCase):
    def test_retained_historical_status_layers_and_unknowns(self):
        value=json.loads(check.INCIDENT.read_text(encoding='utf-8'))
        self.assertEqual(check.validate_incident(value)['unknown'],19)
        for mutate in (lambda v:v.update(member_count=1),lambda v:v['attempts'][0].update(state='REJECTED'),
                       lambda v:v['commands'].pop(),lambda v:next(c for c in v['commands'] if c['operation']=='bid').update(service_status=461)):
            changed=deepcopy(value);mutate(changed)
            with self.assertRaises(ValueError):check.validate_incident(changed)

    def test_actual_native_read_envelopes_reject_forged_success_and_targets(self):
        rows=[json.loads(line) for line in (check.READ/'checkpoint.jsonl').read_text(encoding='utf-8').splitlines()]
        result=json.loads((check.READ/'result.json').read_text())
        self.assertEqual(check.validate_reads(rows,result)['actual_gets'],7)
        for mutate in (lambda r:next(x for x in r if x['kind']=='NATIVE_RESULT')['response']['network'][0].update(status=401),
                       lambda r:next(x for x in r if x['kind']=='NATIVE_RESULT')['response'].update(command_id='f'*32),
                       lambda r:r.pop(2)):
            changed=deepcopy(rows);mutate(changed)
            with self.assertRaises((ValueError,KeyError)):check.validate_reads(changed,result)

    def test_backup_preserves_all_rows_and_integrity_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as path:
            source=Path(path)/'source.sqlite';destination=Path(path)/'copy.sqlite'
            db=sqlite3.connect(source)
            db.executescript("CREATE TABLE parent(id PRIMARY KEY);CREATE TABLE child(id REFERENCES parent(id),value);INSERT INTO parent VALUES(1);INSERT INTO child VALUES(1,'unknown');")
            db.close()
            receipt=backup(source,destination)
            self.assertEqual(receipt['tables'],{'parent':1,'child':1})
            self.assertEqual(receipt['row_comparison'],'equal')
            with closing(sqlite3.connect(source)) as db:self.assertEqual(list(db.execute('SELECT * FROM child')),[(1,'unknown')])

    def test_captured_native_functions_explain_461_to_403_without_account_claim(self):
        p=subprocess.run(['node','tests/controller_status_translation_checks.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('synthetic responses only',p.stdout)

    def test_legacy_control_preservation_accepts_only_append_only_paused_scheduler_noop(self):
        from check_00401_artifacts import validate_preserved_control
        old=dict(objective=dict(columns=['id','state','control','infra_retries','created'],rows=[['obj','PAUSED','pause',0,1]]),
                 task=dict(columns=['key','objective_id','id','state','control','attempts','infra_retries','accepted_stage','recheck'],
                           rows=[['obj/task','obj','task','RECONCILING',None,1,0,None,0]]),
                 event=dict(columns=['id','owner','turn_id','at','kind'],rows=[[1,'obj/task',None,1,'transition']]))
        current=deepcopy(old);current['event']['rows'].append([2,'obj/task',None,2,'transition'])
        transitions={2:dict(previous='RECONCILING',following='RECONCILING',diagnostic=None,keys=['diagnostic','from','to'])}
        self.assertEqual(validate_preserved_control(old,current,transitions),1)
        for mutate in (lambda c:c['event']['rows'].pop(0),lambda c:c['task']['rows'][0].__setitem__(3,'RUNNING'),
                       lambda c:c['event']['rows'][-1].__setitem__(2,99),lambda c:c['event']['rows'][-1].__setitem__(4,'actor_started'),
                       lambda c:c['objective']['rows'][0].__setitem__(1,'RUNNING')):
            changed=deepcopy(current);mutate(changed)
            with self.assertRaises(ValueError):validate_preserved_control(old,changed,transitions)
        for following in ('RUNNING','STOPPED','COMPLETED'):
            changed=deepcopy(transitions);changed[2]['following']=following
            with self.assertRaises(ValueError):validate_preserved_control(old,current,changed)


if __name__=='__main__':unittest.main(verbosity=2)
