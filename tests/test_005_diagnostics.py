"""Controller diagnostics retention, result rejection and local helper failures."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from fc_access.controller_v1.semantic import SemanticHealth,native_summary
from fc_access.controller_v1.server import Server,EXTENSION_ID
from fc_access.controller_v1.store import ControllerStore


class DiagnosticsTests(unittest.TestCase):
    def test_native_renewal_diagnostic_retains_only_success_metadata(self):
        from fc_access.production_v1.diagnostics import validate_records
        row=dict(stage='NATIVE_RENEWAL_RESULT',at=datetime.now(timezone.utc).isoformat(),detail=dict(success=True))
        self.assertEqual(validate_records([row]),[row])
        for key in ('token','session','headers','response'):
            changed=deepcopy(row);changed['detail'][key]='VALUE_CANARY'
            with self.assertRaises(ValueError):validate_records([changed])

    def test_wire_comparison_typed_fields_retained_but_raw_data_and_sensitive_keys_rejected(self):
        detail=dict(target_index=0,wire_ready=True,wire_target_found=True,wire_identity_matches=True,wire_callback_matches=False,
                    wire_current_bid=700,wire_starting_bid=500,wire_buy_now_price=11000,wire_expires=-1,
                    wire_bid_state='outbid',wire_trade_state='closed')
        record=dict(stage='WIRE_AUCTION',at=self.trace[0]['at'],detail=detail)
        self.assertEqual(self.post(records=[record]),(200,{'accepted':True}))
        for field,value in [('responseText','PRIVATE_CANARY'),('token','PRIVATE_CANARY'),('wire_current_bid',True),
                            ('wire_bid_state','PRIVATE_CANARY'),('wire_expires',-2),('target_index',10)]:
            bad=deepcopy(record);bad['detail'][field]=value
            self.assertEqual(self.post(records=[bad])[0],409)
        retained=[json.loads(r[0]) for r in self.server.store.db.execute('SELECT body FROM c4_diagnostics')]
        self.assertNotIn('PRIVATE_CANARY',json.dumps(retained))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'fixture.sqlite'
        self.server=Server(self.path,0,poll_seconds=0)
        self.peer=dict(context=dict(account='a'*32,persona='b'*32,identity_namespace='c'*32,game='fc27',platform='pc'),
                       fences=dict(owner='d'*32,epoch=1,host_epoch=self.server.store.host_epoch,worker_epoch='e'*32,document='f'*32))
        self.server.store.attach(self.peer);self.server.attached_at=time.monotonic()
        self.command=dict(schema=4,id='1'*32,operation='balance',params={},**deepcopy(self.peer))
        self.server.store.enqueue(self.command,self.peer);self.server.store.claim(self.peer)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        self.trace=[dict(stage='WORKER_EXECUTE',at=datetime.now(timezone.utc).isoformat(),detail={})]

    def close(self):
        self.server.shutdown();self.thread.join(3);self.server.server_close()

    def post(self,peer=None,cid=None,records=None):
        value=dict(peer=peer or self.peer,id=cid or self.command['id'],records=self.trace if records is None else records)
        req=Request(f'http://127.0.0.1:{self.server.server_port}/diagnostic',data=json.dumps(value).encode(),
                    headers={'Origin':'chrome-extension://'+EXTENSION_ID,'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as error:
            with error:return error.code,json.load(error)

    def test_http_records_retained_and_append_only_without_granting_dispatch(self):
        self.assertEqual(self.post(),(200,{'accepted':True}))
        db=self.server.store.db
        self.assertEqual(json.loads(db.execute('SELECT body FROM c4_diagnostics').fetchone()[0]),self.trace)
        self.assertEqual(db.execute('SELECT state,result FROM c4_commands').fetchone(),('CLAIMED',None))
        for sql in ('DELETE FROM c4_diagnostics',"UPDATE c4_diagnostics SET body='[]'"):
            with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)
        db.rollback()

    def test_sensitive_unknown_malformed_stale_and_unclaimed_records_rejected(self):
        invalid=[dict(stage='PAGE_ENTER',at=self.trace[0]['at'],detail={'token':'SECRET_CANARY'})]
        self.assertEqual(self.post(records=invalid)[0],409)
        self.assertEqual(self.post(cid='2'*32)[0],409)
        stale=deepcopy(self.peer);stale['fences']['document']='2'*32
        self.assertEqual(self.post(peer=stale)[0],409)
        c=deepcopy(self.command);c['id']='3'*32;self.server.store.enqueue(c,self.peer)
        self.assertEqual(self.post(cid=c['id'])[0],409)
        self.assertEqual(self.server.store.db.execute('SELECT count(*) FROM c4_diagnostics').fetchone()[0],0)

    def test_total_diagnostic_limit_cannot_be_bypassed_by_multiple_posts(self):
        for _ in range(4):self.assertEqual(self.post(records=self.trace*64)[0],200)
        self.assertEqual(self.post()[0],409)
        self.assertEqual(self.server.store.db.execute('SELECT sum(json_array_length(body)) FROM c4_diagnostics').fetchone()[0],256)

    def test_rejected_untrusted_result_leaves_typed_diagnostic_without_secret(self):
        bad=dict(command_id=self.command['id'],schema=4,operation='balance',context=self.peer['context'],
                 fences=self.peer['fences'],success=True,status=200,receipt={'verdict':['SECRET_CANARY']},password='SECRET_CANARY')
        with self.assertRaises(ValueError):self.server.store.finish(self.peer,self.command['id'],bad)
        kind,body=self.server.store.db.execute('SELECT kind,body FROM c4_events ORDER BY seq DESC LIMIT 1').fetchone()
        self.assertEqual(kind,'RESULT_REJECTED');self.assertNotIn('CANARY',body);self.assertNotIn('password',body)
        self.assertEqual(self.server.store.db.execute('SELECT state,result FROM c4_commands').fetchone(),('CLAIMED',None))


class HelperFailureTests(unittest.TestCase):
    def test_successful_local_helper_does_not_renew_native_freshness_and_failures_stop(self):
        tick=[0.];s=SemanticHealth(clock=lambda:tick[0])
        c=dict(schema=2,id='a'*32,operation='price_helpers',params={},context={},fences={})
        v=dict(schema=2,command_id=c['id'],operation=c['operation'],context={},fences={},result=dict(success=True,network=[]))
        summary=native_summary(c,v);self.assertTrue(summary['success'])
        s.observe(dict(kind='native_result',**summary));self.assertIsNone(s.last_native_success)
        for _ in range(3):s.observe(dict(kind='native_result',**native_summary(c,None)))
        self.assertEqual(s.check(),'PERSISTENT_HELPER_FAILURE')

    def test_actual_controller_caps_success_cannot_mask_failed_helpers_as_empty_batches(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1);s=SemanticHealth(clock=h.clock.clock)
            try:
                shared=h.ea.shared
                def broken(c,at):
                    if c['operation']=='price_helpers':raise TimeoutError('fixture_local_helper_failed')
                    return shared(c,at)
                h.ea.shared=broken
                h.executor.result=lambda c,v:s.observe(dict(kind='native_result',**native_summary(c,v)))
                h.controller.run(steps=5)  # three acquisitions with MAINTENANCE between
                self.assertEqual(s.check(),'PERSISTENT_HELPER_FAILURE');self.assertEqual(h.calls('bid'),[])
            finally:h.close()

    def test_missing_worker_diagnostics_stop_even_with_successful_native_reads(self):
        from test_005_semantic import event
        s=SemanticHealth(clock=lambda:0)
        for _ in range(3):s.observe(dict(event(),diagnostic_records=0))
        self.assertEqual(s.check(),'PERSISTENT_MISSING_DIAGNOSTICS')

    def test_foreground_policy_fixture_and_existing_window_selection(self):
        for script in ('desktop_focus_checks.ps1','desktop_window_checks.ps1'):
            p=subprocess.run(['powershell','-NoProfile','-File','tests/'+script],cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS',p.stdout)


if __name__=='__main__':unittest.main(verbosity=2)
