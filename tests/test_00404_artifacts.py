"""Local control IPC, restart-readable evidence, native and historical contracts."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from controller_work_fixture import harness,won
from fc_access.controller_v1.server import Server
from validate_bulk_transfer_evidence import validate as historical_bulk


class Artifacts(unittest.TestCase):
    def test_0_6_canonical_process_guards_exclude_competing_owner_and_native_executor(self):
        from fc_access.controller_v1.__main__ import guard_paths
        from fc_access.continuous_v1.runtime import account_locks
        from fc_access.actors_v1.locking import process_lock
        with tempfile.TemporaryDirectory() as path:
            h=harness(path)
            try:
                canonical=guard_paths(ROOT,h.adapter.context,h.store.path,8784)
                self.assertEqual(canonical[:2],account_locks(h.adapter.context))
                isolated=guard_paths(path,h.adapter.context,h.store.path,49152)
                for lock in isolated:
                    self.assertTrue(lock.resolve().is_relative_to(Path(path).resolve()))
                    with process_lock(lock):
                        code="from fc_access.actors_v1.locking import process_lock; import sys; guard=process_lock(sys.argv[1]); guard.__enter__()"
                        p=subprocess.run([sys.executable,'-c',code,str(lock)],cwd=ROOT,capture_output=True,text=True,timeout=5)
                        self.assertNotEqual(p.returncode,0);self.assertIn('process_already_running',p.stderr)
                    with process_lock(lock):pass
            finally:h.ea.world.close();h.close()

    def test_0_6_actual_ephemeral_http_status_pause_stop_and_account_rejection(self):
        with tempfile.TemporaryDirectory() as path:
            h=harness(path)
            server=Server(Path(path)/'empty.sqlite',port=0,poll_seconds=0)
            server.store.close();server.store=h.store;server.controller=h.controller
            port=server.server_port;self.assertNotIn(port,(8783,8784))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            opener=build_opener(ProxyHandler({}));original=socket.create_connection
            def only_fixture(address,*a,**kw):
                if address!=('127.0.0.1',port):raise AssertionError('fixture_transport_escape')
                return original(address,*a,**kw)
            def request(route,payload=None):
                req=Request(f'http://127.0.0.1:{port}'+route,data=json.dumps(payload).encode() if payload else None,headers={'Content-Type':'application/json'})
                with opener.open(req,timeout=3) as response:return json.load(response)
            try:
                with patch('socket.create_connection',side_effect=only_fixture):
                    self.assertEqual(request('/status')['lifecycle'],'RUNNING')
                    self.assertEqual(request('/control',{'action':'pause'})['lifecycle'],'PAUSED')
                    self.assertEqual(request('/status')['phase'],'ACQUIRING')
                    self.assertEqual(request('/control',{'action':'stop'})['lifecycle'],'STOPPED')
                    with self.assertRaises(HTTPError):request('/control',{'action':'run'})
                    bad=dict(context=dict(h.adapter.context,account='a'*32),owner='b'*32,epoch=99)
                    with self.assertRaises(HTTPError):request('/activate',bad)
                    with self.assertRaisesRegex(AssertionError,'escape'):socket.create_connection(('127.0.0.1',8784))
                    self.assertFalse(h.ea.calls)
            finally:
                server.shutdown();thread.join(3);server.server_close();h.cache.close();h.ea.world.close()
            self.assertFalse(thread.is_alive())

    def test_0_3_6_cli_has_explicit_controls_and_readonly_persisted_status(self):
        p=subprocess.run([sys.executable,'-m','fc_access.controller_v1','--help'],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        for name in ('run','status','pause','stop'):self.assertIn(name,p.stdout)
        with tempfile.TemporaryDirectory() as path:
            h=harness(path);won(h);h.controller.step();h.controller.step();h.controller.pause()
            database=h.store.path;h.ea.world.close();h.close()
            p=subprocess.run([sys.executable,'-m','fc_access.controller_v1','status','--database',str(database)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr);s=json.loads(p.stdout)
            self.assertEqual((s['phase'],s['lifecycle']),('ACQUIRING','PAUSED'))
            self.assertEqual(s['work'][0]['state'],'CONFIRMED');self.assertTrue(s['members'])

    def test_1_6_7_shipped_native_calls_and_legacy_entry_points(self):
        for script in ('controller_work_native_checks.cjs','controller_policy_native_checks.cjs','controller_native_checks.cjs','production_page_checks.cjs','production_worker_checks.cjs'):
            with self.subTest(script=script):
                p=subprocess.run(['node','tests/'+script],cwd=ROOT,capture_output=True,text=True,timeout=30)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_6_7_historical_evidence_consumption_and_new_probe_decision(self):
        historical_bulk() # Only sealed captures/logs are hashed by this reader.
        plan=json.loads((ROOT/'docs/research/004/004-04/live-contract-review.json').read_text())
        self.assertEqual(plan['new_window_budget'],dict(ea_requests=0,mutations=0))
        self.assertEqual(plan['new_live_windows'],[])
        self.assertEqual(plan['classification'],'REUSE_VERIFIED_NATIVE_CONTRACTS')
        self.assertFalse(plan['full_controller_lifecycle_launched'])
        cleanup=json.loads((ROOT/'docs/research/004/004-04/final-cleanup.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(cleanup['production_workers'],[])
        self.assertEqual(cleanup['production_listeners'],[])
        self.assertEqual(cleanup['new_live_windows'],0)
        self.assertEqual(cleanup['full_controller_lifecycles_started'],0)
        self.assertEqual({r['operation'] for r in plan['contracts']},{'bid','move','list','clear_sold','relist_all'})
        for row in plan['contracts']:
            self.assertFalse(row['native_invocation_changed']);self.assertFalse(row['additional_live_probe_required'])
            self.assertTrue(row['reason']);self.assertTrue(row['offline_validator'])
            for evidence in row['evidence']:self.assertTrue((ROOT/evidence).is_file())
        # Independently check both historical bulk outcomes and consumed intents.
        base=ROOT/'docs/research/002-bulk-transfer-operations'
        ledger=json.loads((base/'durable-ledger.json').read_text())
        self.assertEqual([(r['operation'],r['state']) for r in ledger['intents']],[('bulk_clear_sold','CONFIRMED'),('bulk_relist_all','CONFIRMED')])
        for name in ('clear-sold','relist-all'):
            result=json.loads((base/(name+'-reconciliation.json')).read_text())
            self.assertEqual(result['result']['outcome'],'CONFIRMED')
            self.assertEqual(len({result[k] for k in ('mutation_command_id','before_read_id','after_read_id')}),3)
        relist=json.loads((base/'relist-all-reconciliation.json').read_text())['result']['relisted']
        self.assertEqual(len(relist),4);self.assertTrue(all(r['expires']==3600 and r['new_trade_id']!=r['old_trade_id'] for r in relist))

    def test_all_criteria_have_reviewable_artifacts_and_named_behavioral_checks(self):
        base=ROOT/'docs/research/004/004-04';manifest=json.loads((base/'acceptance.json').read_text())
        self.assertEqual([r['criterion'] for r in manifest['coverage']],list(range(8)))
        self.assertEqual(manifest['classification'],'IMPLEMENTED_OFFLINE_VERIFIED_NATIVE_CONTRACTS_REUSED')
        import test_00404_controller as behavior
        import test_00404_process as process
        available={**{name:behavior.Acceptance for name in unittest.defaultTestLoader.getTestCaseNames(behavior.Acceptance)},
                   **{name:process.ProcessAcceptance for name in unittest.defaultTestLoader.getTestCaseNames(process.ProcessAcceptance)},
                   **{name:Artifacts for name in unittest.defaultTestLoader.getTestCaseNames(Artifacts)}}
        for row in manifest['coverage']:
            self.assertTrue(row['tests']);self.assertTrue(set(row['tests'])<=set(available))
        self.assertTrue((base/'REPORT.md').is_file())


if __name__=='__main__':unittest.main(verbosity=2)
