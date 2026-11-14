"""Behavioral pagination and continuation checks; no EA requests or live writes."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from actors_fixture import create
from fc_access.actors_v1.native import Mailbox
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.final_run import BoundedBroker,load_evidence
from fc_access.actors_v1.final_supervisor import review_resume
from fc_access.production_v1.contracts import Search,parse_response

OUT=ROOT/'docs/research/002/002-12'


class Repair(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)

    def test_twenty_row_stride_twenty_one_lookahead_and_reject_incorrect_offsets(self):
        f,p,c=create(self.path);self.addCleanup(p.close);self.addCleanup(f.close)
        response=f.read('search',Search.discovery(page=2).params());cmd=p.calls[-1]
        self.assertEqual(response['result']['network'][0]['query']['start'],20)
        self.assertEqual(response['result']['network'][0]['query']['num'],21)
        parse_response(response,cmd,source='fixture',now=c.now())
        for offset in (0,19,21,40):
            wrong=deepcopy(response);wrong['result']['network'][0]['query']['start']=offset
            with self.subTest(offset=offset),self.assertRaises(ValueError):
                parse_response(wrong,cmd,source='fixture',now=c.now())
        pricing=f.read('search',Search.pricing(123).params())
        self.assertEqual(pricing['result']['network'][0]['query']['start'],0)
        self.assertEqual(pricing['result']['network'][0]['query']['num'],21)

    def test_reconnect_keeps_consumed_request_count_and_does_not_resubmit(self):
        f,p,c=create(self.path);self.addCleanup(p.close);self.addCleanup(f.close)
        box=Mailbox(self.path/'native.sqlite3');self.addCleanup(box.close)
        cfg=Config(native_interval_seconds=0)
        b=BoundedBroker(box,f,cfg,now=c.now,clock=c.monotonic,sleep=c.sleep)
        b.initialize();box.enqueue(f.adapter.envelope('1'*32,'balance',{}),'bidder',now=c.now())
        b.run_one();self.assertEqual(b.requests,1)
        second=BoundedBroker(box,f,cfg,extra_requests=24,now=c.now,clock=c.monotonic,sleep=c.sleep)
        self.assertEqual(second.requests,25)
        second.initialize();self.assertIsNone(second.run_one())
        self.assertEqual(len(p.calls),1)

    def copy_mailbox(self):
        path=self.path/'native.sqlite3'
        shutil.copy2(OUT/'live-01/state-backup/native.sqlite3',path)
        return path

    def test_stopped_checkpoint_review_preserves_original_scope_and_consumed_wall(self):
        path=self.copy_mailbox()
        result=review_resume(OUT/'live-01',path,1800)
        self.assertGreater(result['prior_active_wall_seconds'],35)
        self.assertLess(result['prior_active_wall_seconds'],36)
        self.assertEqual(result['context']['platform'],'pc')
        self.assertEqual(load_evidence(OUT/'live-01/supervisor.jsonl')[-1]['kind'],'RUN_STOPPED')
        with self.assertRaisesRegex(ValueError,'cumulative_wall'):review_resume(OUT/'live-01',path,7200)

    def test_existing_mutation_or_lost_history_cannot_use_the_read_only_continuation(self):
        path=self.copy_mailbox();db=sqlite3.connect(path)
        cid,encoded=db.execute('select id,command from work limit 1').fetchone()
        changed=json.loads(encoded);changed['operation']='bid'
        db.execute('update work set command=? where id=?',(json.dumps(changed),cid));db.commit()
        with self.assertRaisesRegex(ValueError,'mutation_checkpoint'):review_resume(OUT/'live-01',path,1800)
        db.execute('update work set command=? where id=?',(encoded,cid));db.execute('delete from work where id=?',(cid,));db.commit();db.close()
        with self.assertRaisesRegex(ValueError,'history_missing'):review_resume(OUT/'live-01',path,1800)

    def test_resale_ack_cannot_resume_until_immutable_intent_and_independent_readback_are_reconciled(self):
        prior=OUT/'remediation-03/live-04'
        box=self.path/'native.sqlite3';journal=self.path/'journal.sqlite3'
        shutil.copy2(prior/'state-backup/native.sqlite3',box)
        shutil.copy2(prior/'state-backup/journal.sqlite3',journal)
        db=sqlite3.connect(box);runtime=json.loads(db.execute('select body from runtime where id=1').fetchone()[0])
        runtime['journal']=str(journal);db.execute('update runtime set body=? where id=1',(json.dumps(runtime),));db.commit();db.close()
        with self.assertRaisesRegex(ValueError,'mutation_checkpoint'):review_resume(prior,box,120)
        j=sqlite3.connect(journal)
        cid,scope,trade=j.execute("select id,scope,trade_id from resale_writes_v1 where state='ACKNOWLEDGED'").fetchone()
        j.execute("update resale_writes_v1 set state='RECONCILED' where id=?",(cid,));j.commit()
        with self.assertRaisesRegex(ValueError,'independent_readback'):review_resume(prior,box,120)
        event=dict(kind='RESALE',reason='VERIFIED',command_id=cid,read_ids=['offline-read-only-proof'])
        j.execute('insert into registry_events_v1(scope,trade_id,at,body) values(?,?,?,?)',
            (scope,trade,'2026-11-14T12:00:11+00:00',json.dumps(event)));j.commit();j.close()
        self.assertGreater(review_resume(prior,box,120)['prior_active_wall_seconds'],700)


if __name__=='__main__':unittest.main(verbosity=2)
