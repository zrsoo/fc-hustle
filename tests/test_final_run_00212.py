"""Final-run behavioral checks. All synthetic state stays in temporary directories."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from actors_fixture import create
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.native import Mailbox
from fc_access.actors_v1.final_run import BoundedBroker,Evidence,load_evidence,assess,REQUIRED,preflight
from fc_access.actors_v1.final_supervisor import stop_children,run
from fc_access.production_v1.contracts import Search


class FinalRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def evidence(self,name='events.jsonl'):
        e=Evidence(self.root/name);self.addCleanup(e.close);return e

    def broker(self,**kw):
        f,page,clock=create(self.root)
        self.addCleanup(page.close);self.addCleanup(f.close)
        box=Mailbox(self.root/'native.sqlite3');self.addCleanup(box.close)
        b=BoundedBroker(box,f,Config(native_interval_seconds=0),now=clock.now,
            clock=clock.monotonic,sleep=clock.sleep,**kw)
        b.initialize()
        return f,page,clock,box,b

    def test_exclusive_window_and_captured_response_chain(self):
        e=self.evidence();e.append('BEGIN');e.append('END',value=7)
        self.assertEqual(len(load_evidence(e.path)),2)
        with self.assertRaises(FileExistsError):Evidence(e.path)
        rows=e.path.read_text().splitlines();v=json.loads(rows[1]);v['value']=8
        e.close();e.path.write_text(rows[0]+'\n'+json.dumps(v)+'\n')
        with self.assertRaisesRegex(ValueError,'integrity'):load_evidence(e.path)

    def test_reorder_drop_middle_duplicate_and_partial_lines_rejected(self):
        e=self.evidence()
        for i in range(3):e.append('N',i=i)
        lines=e.path.read_text().splitlines();e.close()
        for changed in ([lines[1],lines[0],lines[2]],[lines[0],lines[2]],lines+[lines[-1]],lines+['{']):
            e.path.write_text('\n'.join(changed)+'\n')
            with self.assertRaises((ValueError,json.JSONDecodeError)):load_evidence(e.path)

    def test_declarative_success_and_historical_events_cannot_prove_any_branch(self):
        e=self.evidence();e.append('CLAIM',status='FULL PASS',proofs={n:True for names in REQUIRED.values() for n in names})
        r=assess(e.path)
        self.assertEqual(r['status'],'PARTIAL/NOT FULL PASS')
        self.assertEqual({c['index'] for c in r['criteria']},set(range(8)))
        for c in r['criteria']:
            self.assertTrue(c['missing']);self.assertEqual(c['status'],'LIVE-UNVERIFIED')

    def test_each_named_transaction_and_maintenance_branch_is_required(self):
        self.assertTrue({'active_outbid','minimum_rebid','cap_stop','terminal_won','terminal_lost','exact_owned_paid'}<=set(REQUIRED[1]))
        self.assertTrue({'stored_price_listing_3600','expired_one_call_relist','sold_one_call_clear','independent_maintenance_readbacks'}<=set(REQUIRED[2]))
        self.assertTrue({'capacity_pause_resume','sticky_draining','whole_queue_intervals','restart_reconnect',
            'unknown_reconciliation','attributable_realized_profit'}<=set(REQUIRED[3]))
        self.assertEqual(len(set(n for names in REQUIRED.values() for n in names)),sum(map(len,REQUIRED.values())))

    def test_fixture_response_is_rejected_as_live_proof(self):
        f,p,c,box,b=self.broker();cmd=f.adapter.envelope('1'*32,'balance',{})
        box.enqueue(cmd,'bidder',now=c.now());b.run_one()
        response=json.loads(box.db.execute('select response from work').fetchone()[0])
        e=self.evidence();e.append('NATIVE_READ',command=cmd,response=response)
        with self.assertRaises(ValueError):assess(e.path)

    def test_wall_deadline_stops_before_native_dispatch(self):
        f,p,c,box,b=self.broker(wall_seconds=1)
        box.enqueue(f.adapter.envelope('1'*32,'balance',{}),'acquirer',now=c.now())
        c.sleep(1);self.assertIsNone(b.run_one())
        self.assertEqual(b.stopped_reason,'WALL_DEADLINE');self.assertEqual(p.calls,[])
        self.assertEqual(box.db.execute('select state from work').fetchone()[0],'WAITING')

    def test_request_budget_uses_actual_fanout_and_reserves_next_dispatch(self):
        f,p,c,box,b=self.broker(request_threshold=17)
        for n in (1,2,3):box.enqueue(f.adapter.envelope(str(n)*32,'balance',{}),'acquirer',now=c.now())
        b.run_one();b.run_one();self.assertEqual(b.requests,2)
        self.assertIsNone(b.run_one());self.assertEqual(b.stopped_reason,'REQUEST_THRESHOLD')
        self.assertEqual(len(p.calls),2)

    def test_priority_is_real_mailbox_selection_with_both_roles_pending(self):
        f,p,c,box,b=self.broker()
        box.enqueue(f.adapter.envelope('1'*32,'search',Search.pricing(123).params()),'acquirer',now=c.now())
        box.enqueue(f.adapter.envelope('2'*32,'watched',{}),'bidder',now=c.now())
        self.assertEqual(b.run_one()['command_id'],'2'*32)
        self.assertEqual(b.run_one()['command_id'],'1'*32)

    def test_unknown_delivery_halts_and_never_repeats_command(self):
        f,p,c,box,b=self.broker()
        box.enqueue(f.adapter.envelope('1'*32,'balance',{}),'bidder',now=c.now())
        with patch.object(p,'execute',side_effect=TimeoutError('synthetic secret not retained')) as execute:
            b.run_one();self.assertIsNone(b.run_one());self.assertEqual(execute.call_count,1)
        self.assertEqual(b.stopped_reason,'UNKNOWN_READ');self.assertEqual(b.requests,16)
        self.assertEqual(box.db.execute('select state from work').fetchone()[0],'UNKNOWN')

    def test_local_helpers_count_no_network_requests(self):
        f,p,c,box,b=self.broker()
        box.enqueue(f.adapter.envelope('1'*32,'status_support',{}),'bidder',now=c.now())
        b.run_one();self.assertEqual(b.requests,0)

    def test_enrollment_limit_does_not_dispatch_another_initial_bid(self):
        f,p,c,box,b=self.broker(max_enrollments=1)
        # A consumed, prior initial write remains counted even when UNKNOWN.
        cmd=f.adapter.envelope('1'*32,'balance',{})
        box.enqueue(cmd,'acquirer',now=c.now())
        encoded=deepcopy(cmd);encoded['operation']='bid'
        box.db.execute("update work set command=?,state='UNKNOWN'",(json.dumps(encoded),))
        self.assertIsNone(b.run_one());self.assertEqual(b.stopped_reason,'ENROLLMENT_BOUND')
        self.assertEqual(p.calls,[])

    def test_unsafe_bounds_rejected(self):
        f,p,c,box,b=self.broker()
        for values in ({'wall_seconds':0},{'wall_seconds':True},{'wall_seconds':7201},
                       {'request_threshold':15},{'request_threshold':1801},{'max_enrollments':13}):
            with self.subTest(values=values),self.assertRaises(ValueError):BoundedBroker(box,f,Config(),**values)

    def test_all_owned_real_child_processes_are_stopped_and_waited(self):
        children=[];e=self.evidence()
        try:
            for role in ('broker','acquirer','bidder','maintenance'):
                children.append((role,subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)))
            self.assertEqual(stop_children(children,e),[])
            self.assertTrue(all(p.poll() is not None for _,p in children))
            self.assertEqual({r['role'] for r in load_evidence(e.path)},set(r for r,_ in children))
        finally:
            for _,p in children:
                if p.poll() is None:p.kill();p.wait(timeout=10)

    def test_existing_native_state_refuses_reopening_consumed_budget(self):
        state=self.root/'private-captures/final-remediation';state.mkdir(parents=True)
        (state/'native.sqlite3').touch()
        with patch('fc_access.actors_v1.final_supervisor.ROOT',self.root),patch('subprocess.Popen') as launch:
            self.assertEqual(run(self.root/'rejected-run'),1);launch.assert_not_called()
        rows=load_evidence(self.root/'rejected-run/supervisor.jsonl')
        self.assertEqual(rows[0]['reason'],'PREFLIGHT_OR_SUPERVISION_FAILURE')
        self.assertEqual(rows[-1]['launched_roles'],[])


if __name__=='__main__':unittest.main(verbosity=2)
