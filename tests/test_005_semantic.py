"""Semantic operational failures versus ordinary market outcomes; entirely offline."""
from copy import deepcopy
from dataclasses import replace
from argparse import Namespace
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from fc_access.controller_v1.semantic import SemanticHealth, SemanticLimits, native_summary
from fc_access.controller_v1.watchdog import Watchdog, Supervision, SupervisionLost, Limits, supervise
import time


def failed_operational_worker(connection, arguments, limits):
    supervision=Supervision(connection,limits)
    supervision.progress('LOCAL')
    for _ in range(3):
        supervision.report('native_result',**{k:v for k,v in event(success=False,status=401).items() if k!='kind'})
        supervision.progress('LOCAL')
    while True:
        try:supervision.require()
        except SupervisionLost:
            supervision.report('exit',reason='WATCHDOG_STOP',lifecycle='STOPPED');connection.close();return
        time.sleep(.01)


def event(operation='balance', *, success=True, status=200, wire=None, error=None, verdict=None, returned=1):
    return dict(kind='native_result',operation=operation,command_id='a'*32,local=operation=='price_helpers',
                read=operation in {'balance','watched','status_batch','search','caps','transfer_list','unassigned','owned_item'},
                success=success,error=error,service_status=status,wire_statuses=[status] if wire is None else wire,
                receipt_verdict=verdict,requested=1 if operation=='status_batch' else 0,returned=returned)


class SemanticTests(unittest.TestCase):
    def test_two_auth_failures_stop_even_while_progress_packets_continue(self):
        tick=[0.];s=SemanticHealth(clock=lambda:tick[0]);w=Watchdog(clock=lambda:tick[0],semantic=s)
        for i in range(2):
            tick[0]+=2
            w.observe(event(success=False,status=401,error='service_failed'))
            w.observe(dict(kind='progress',stage='LOCAL',tick=tick[0],lifecycle='RUNNING'))
            self.assertEqual(w.check(),None if i==0 else 'PERSISTENT_AUTH_FAILURE')

    def test_successful_native_read_allows_transient_auth_recovery(self):
        s=SemanticHealth(clock=lambda:0)
        s.observe(event(success=False,status=401));s.observe(event());s.observe(event(success=False,status=401))
        self.assertIsNone(s.check());self.assertEqual(s.auth_failures,1)

    def test_failed_reads_do_not_become_healthy_from_local_helpers(self):
        s=SemanticHealth(clock=lambda:0)
        for _ in range(3):
            s.observe(event(success=False,status=None,wire=[],error='ambiguous_network'))
            s.observe(event('price_helpers'))
        self.assertEqual(s.check(),'PERSISTENT_READ_FAILURE');self.assertEqual(s.native_successes,0)

    def test_repeated_owned_or_inventory_failure_is_not_masked_by_other_read_success(self):
        for operation in ('owned_item','transfer_list'):
            s=SemanticHealth(clock=lambda:0)
            for _ in range(3):
                s.observe(event(operation,success=False,status=None,wire=[],error='service_timeout'))
                s.observe(event('status_batch'))
            self.assertEqual(s.check(),'PERSISTENT_READ_FAILURE')

    def test_repeated_handled_acquisition_exceptions_cannot_be_empty_market_success(self):
        s=SemanticHealth(clock=lambda:0)
        for _ in range(3):
            s.observe(event('search'))
            s.observe(dict(kind='batch_result',batch_id='b'*32,state='OPERATION_FAILED',confirmed=0,uncertain=0))
        self.assertEqual(s.check(),'PERSISTENT_ACQUISITION_FAILURE')

    def test_wire_permission_failures_persist_across_successful_readbacks(self):
        s=SemanticHealth(clock=lambda:0)
        for _ in range(3):
            s.observe(event('bid',success=False,status=403,wire=[461],error='ambiguous_network',verdict='UNCONFIRMED'))
            s.observe(event('watched'))
        self.assertEqual(s.check(),'PERSISTENT_WRITE_FAILURE')

    def test_retained_incident_would_stop_at_third_failed_write_before_later_auth_storm(self):
        import check_005_stage01 as check
        incident=json.loads(check.INCIDENT.read_text(encoding='utf-8'))
        s=SemanticHealth(clock=lambda:0);failed_bids=0;auth_errors=0
        for c in incident['commands']:
            if c['operation']=='bid':failed_bids+=1
            if c['service_status']==401:auth_errors+=1
            s.observe(event(c['operation'],success=c['success'] is True,status=c['service_status'],
                wire=[n['status'] for n in c['network']],error=c['error'],
                verdict=(c['receipt'] or {}).get('verdict')))
            if s.check():break
        self.assertEqual(s.check(),'PERSISTENT_WRITE_FAILURE')
        self.assertEqual(failed_bids,3);self.assertEqual(auth_errors,0)

    def test_single_uncertain_action_and_proven_rejections_are_not_global_stops(self):
        s=SemanticHealth(clock=lambda:0)
        s.observe(event('bid',success=False,status=None,wire=[],verdict='UNCONFIRMED'))
        for _ in range(20):
            s.observe(event('bid',success=False,status=409,verdict='REJECTED',error='bid_rejected'))
            s.observe(event('status_batch'))
        self.assertIsNone(s.check());self.assertEqual(s.write_failures,1)

    def test_acks_wait_for_batch_confirmation_and_never_count_as_membership(self):
        s=SemanticHealth(clock=lambda:0)
        for _ in range(10):s.observe(event('bid',verdict='ACCEPTED'))
        self.assertIsNone(s.check());self.assertEqual(s.confirmed,0)
        s.observe(dict(kind='batch_result',batch_id='b'*32,confirmed=0,uncertain=10))
        self.assertEqual(s.check(),'PERSISTENT_UNCONFIRMED_ACQUISITION')

    def test_empty_market_batches_and_partial_missing_results_allow_waiting(self):
        tick=[0.];s=SemanticHealth(clock=lambda:tick[0])
        for _ in range(500):
            tick[0]+=5;s.observe(event('search',returned=0))
            s.observe(dict(kind='batch_result',batch_id='b'*32,confirmed=0,uncertain=0))
            self.assertIsNone(s.check())
        self.assertEqual(s.confirmed,0,'elapsed time and empty discovery confer no trading proof')
        s.observe(event('status_batch',returned=1));self.assertIsNone(s.check())

    def test_repeated_all_missing_management_rows_stop_without_inventing_loss(self):
        s=SemanticHealth(clock=lambda:0)
        for _ in range(3):s.observe(event('status_batch',returned=0))
        self.assertEqual(s.check(),'PERSISTENT_EMPTY_MANAGED_STATUS');self.assertEqual(s.confirmed,0)

    def test_fresh_native_success_required_despite_indefinite_local_progress(self):
        tick=[0.];s=SemanticHealth(clock=lambda:tick[0])
        s.observe(event());tick[0]=90
        self.assertIsNone(s.check())
        s.observe(event('price_helpers'));tick[0]=90.001
        self.assertEqual(s.check(),'NO_FRESH_NATIVE_SUCCESS')
        s.observe(event());self.assertEqual(s.check(),'NO_FRESH_NATIVE_SUCCESS','fault latches until a new runtime')

    def test_no_native_success_startup_has_finite_grace(self):
        tick=[0.];s=SemanticHealth(clock=lambda:tick[0]);tick[0]=91
        self.assertEqual(s.check(),'NO_FRESH_NATIVE_SUCCESS')
        s=SemanticHealth(clock=lambda:tick[0]);self.assertIsNone(s.check())

    def test_real_controller_reports_confirmed_membership_after_independent_status(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,3);messages=[]
            try:
                s=SemanticHealth(clock=h.clock.clock)
                def native(c,v):
                    m=dict(kind='native_result',**native_summary(c,v));messages.append(m);s.observe(m)
                h.executor.result=native
                h.store.semantic_report=lambda **fields:s.observe(dict(kind='batch_result',**fields))
                h.controller.step()
                self.assertEqual(s.confirmed,3);self.assertIsNone(s.check())
                self.assertEqual(len(h.controller.journal.members()),3)
                status=[i for i,m in enumerate(messages) if m['operation']=='status_batch']
                bids=[i for i,m in enumerate(messages) if m['operation']=='bid']
                self.assertLess(min(status),min(bids),'fresh exact status must precede the bid burst')
                self.assertGreater(max(status),max(bids),'independent confirmation must follow the bid burst')
                last_status=[m['command_id'] for m in messages if m['operation']=='status_batch'][-1]
                self.assertTrue(all(m['proof']['read_id']==last_status for m in h.controller.journal.members()))
            finally:h.close()

    def test_real_read_failure_batches_trigger_semantic_stop_without_replay(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                s=SemanticHealth(clock=h.clock.clock)
                h.executor.result=lambda c,v:s.observe(dict(kind='native_result',**native_summary(c,v)))
                h.ea.balance_fail=True
                h.controller.run(steps=3)
                self.assertEqual(s.check(),'PERSISTENT_READ_FAILURE')
                self.assertEqual(h.calls('bid'),[])
            finally:h.close()

    def test_summary_omits_unknown_fields_and_unbound_success(self):
        c=dict(schema=4,id='a'*32,operation='balance',params={},context={},fences={})
        v=dict(schema=4,command_id=c['id'],operation='balance',context={},fences={},success=True,status=200,
               error='CREDENTIAL_CANARY',network=[dict(status=200,session_header_present=True,secret='CREDENTIAL_CANARY')],
               arbitrary='CREDENTIAL_CANARY')
        summary=native_summary(c,v)
        self.assertNotIn('CANARY',json.dumps(summary));self.assertTrue(summary['success'])
        v['command_id']='b'*32;self.assertFalse(native_summary(c,v)['success'])
        v['command_id']=c['id'];v['network'][0]['status']=401
        self.assertFalse(native_summary(c,v)['success'])

    def test_actual_parent_stops_failed_but_progressing_worker_without_restart(self):
        with tempfile.TemporaryDirectory() as path:
            args=Namespace(database=str(Path(path)/'fixture.sqlite'))
            result=supervise(args,target=failed_operational_worker,limits=replace(Limits(),poll=.01,grace=2),output=io.StringIO())
            self.assertEqual(result,1)
            log=next(Path(path).glob('watchdog-runs/*/events.jsonl'))
            rows=[json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(rows[-1]['kind'],'STOPPED')
            self.assertEqual(rows[-1]['reason'],'PERSISTENT_AUTH_FAILURE')
            self.assertFalse(rows[-1]['forced'])
            self.assertEqual(sum(r['kind']=='STARTED' for r in rows),1)


if __name__=='__main__':unittest.main(verbosity=2)
