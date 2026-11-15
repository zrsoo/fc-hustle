"""A re-sealed assertion cannot replace independent durable native evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_series import verify_destinations
from fc_access.actors_v1.final_run import load_evidence


class IndependentDestinations(unittest.TestCase):
    def test_mailbox_and_native_destination_must_both_agree_and_unknown_never_counts_as_proof(self):
        capture=next(r for r in load_evidence(ROOT/'docs/research/002/002-12/live-01/native.jsonl')
            if r['kind']=='DISPATCH_RESULT' and r['command']['operation']=='balance')
        cid=capture['command']['id'];command=json.dumps(capture['command']);response=json.dumps(capture['response'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'state-backup').mkdir()
            with self.assertRaises(sqlite3.OperationalError):verify_destinations(root/'checkpoint.jsonl',[capture])
            self.assertFalse((root/'state-backup/native.sqlite3').exists())
            box=sqlite3.connect(root/'state-backup/native.sqlite3');native=sqlite3.connect(root/'state-backup/transport.sqlite3')
            try:
                box.execute('create table work(id text,command text,response text)')
                native.execute('create table commands(id text,body text,result text)')
                box.execute('insert into work values(?,?,?)',(cid,command,response))
                native.execute('insert into commands values(?,?,?)',(cid,command,response));box.commit();native.commit()
                self.assertEqual(verify_destinations(root/'checkpoint.jsonl',[capture]),1)
                changed=deepcopy(capture['response']);changed['result']['credits']+=1
                box.execute('update work set response=?',(json.dumps(changed),));box.commit()
                with self.assertRaisesRegex(ValueError,'mailbox_response'):verify_destinations(root/'checkpoint.jsonl',[capture])
                box.execute('update work set response=?',(response,));box.commit()
                native.execute('update commands set result=?',(json.dumps(changed),));native.commit()
                with self.assertRaisesRegex(ValueError,'native_destination'):verify_destinations(root/'checkpoint.jsonl',[capture])
                native.execute('delete from commands');native.commit()
                with self.assertRaisesRegex(ValueError,'native_destination'):verify_destinations(root/'checkpoint.jsonl',[capture])
                unknown=deepcopy(capture);unknown['response']=None
                box.execute('update work set response=null');box.commit()
                self.assertEqual(verify_destinations(root/'checkpoint.jsonl',[unknown]),0)
            finally:box.close();native.close()


if __name__=='__main__':unittest.main(verbosity=2)
