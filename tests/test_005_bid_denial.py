"""Bidding through EA 461 denials (`continue` measure) and 401 -> relogin.

Offline: synthetic EA, fake clocks and fixture workers. A denial is a no-effect
outcome; only a denial run with no accepted bid for the window stops, and an
auth-failure stop can be followed by an active measure and a fresh worker.
"""
from argparse import Namespace
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from fc_access.controller_v1.adapter import denied
from fc_access.controller_v1.measures import ContinueMeasure, measure
from fc_access.controller_v1.operational import Runtime, read
from fc_access.controller_v1.semantic import SemanticHealth, SemanticLimits, native_summary
from fc_access.controller_v1.watchdog import Limits, Supervision, SupervisionLost, supervise

GEN='f'*32


def result(*,success=True,status=200,wire=None,verdict=None,operation='balance'):
    return dict(kind='native_result',operation=operation,command_id='a'*32,local=False,
                read=operation in {'balance','watched','status_batch','search'},market_race=False,success=success,
                error=None if success else 'ambiguous_network',service_status=status,
                wire_statuses=[status] if wire is None else wire,receipt_verdict=verdict,requested=0,returned=0)


DENIAL=dict(operation='bid',success=False,status=403,wire=[461],verdict='UNCONFIRMED')
ACCEPTED=dict(operation='bid',success=True,verdict='ACCEPTED')


def denial_receipt(**overrides):
    v=dict(success=False,status=403,network=[dict(status=461)],receipt=dict(verdict='UNCONFIRMED',native_error_code=461,
           native_item_count=0,wire_identity_matches=True,wire_amount_matches=True))
    for k,val in overrides.items():
        if k.startswith('receipt_'):v['receipt'][k[8:]]=val
        else:v[k]=val
    return v


class DenialClassification(unittest.TestCase):
    def test_only_the_exact_permission_denial_shape_is_denied(self):
        self.assertTrue(denied(denial_receipt()))
        for change in (dict(status=200),dict(success=True),dict(network=[dict(status=401)]),dict(network=[]),
                       dict(network=[dict(status=461),dict(status=461)]),dict(receipt_verdict='REJECTED'),
                       dict(receipt_native_error_code=None),dict(receipt_native_item_count=1),
                       dict(receipt_wire_identity_matches=False),dict(receipt_wire_amount_matches=False)):
            with self.subTest(change=change):self.assertFalse(denied(denial_receipt(**change)))

    def test_controller_records_denied_bids_and_continues_the_batch(self):
        path=self.enterContext(tempfile.TemporaryDirectory());h=Harness(path,4);self.addCleanup(h.close)
        s=SemanticHealth(clock=h.clock.clock,tolerate_denials=True);reports=[]
        h.executor.result=lambda c,v:s.observe(dict(kind='native_result',**native_summary(c,v)))
        h.store.semantic_report=lambda **f:(reports.append(f),s.observe(dict(kind='batch_result',**f)))
        h.ea.bid_modes={h.ea.rows[0]['trade_id']:'denied',h.ea.rows[2]['trade_id']:'denied'}
        state=h.controller.step()
        self.assertEqual([a['state'] for a in h.attempts()],['DENIED','ACKNOWLEDGED','DENIED','ACKNOWLEDGED'])
        self.assertEqual((state['phase'],len(state['members'])),('MANAGING',2))
        self.assertEqual(state['potentially_untracked_effects'],[],'denials are no-effect, not unknown')
        # 'uncertain' counts accepted-but-unproven bids; denials are excluded (was 4).
        self.assertEqual((reports[-1]['confirmed'],reports[-1]['uncertain']),(2,2))
        self.assertIsNone(s.check());self.assertEqual(s.denied_bids,2)
        # A denied target is attempted once and never re-bid.
        before=len(h.calls('bid'));h.ea.bid_modes.clear();h.controller.step()
        rebid_targets={c['command']['params']['target']['trade_id'] for c in h.calls('bid')[before:]}
        self.assertFalse(rebid_targets&{h.ea.rows[0]['trade_id'],h.ea.rows[2]['trade_id']})


class TolerantSemantics(unittest.TestCase):
    def test_denials_never_stop_until_the_window_without_an_accepted_bid(self):
        tick=[0.];s=SemanticHealth(clock=lambda:tick[0],tolerate_denials=True);s.observe(result())
        for _ in range(20):s.observe(result(**DENIAL));s.observe(result());tick[0]+=10
        self.assertIsNone(s.check());self.assertEqual((s.denied_bids,s.write_failures),(20,0))
        s.observe(result(**ACCEPTED));self.assertIsNone(s.denial_since,'an accepted bid resets the window')
        s.observe(result(**DENIAL));tick[0]+=SemanticLimits().denial_window-1;s.observe(result())
        self.assertIsNone(s.check())
        tick[0]+=1;self.assertEqual(s.check(),'PERSISTENT_BID_DENIAL')
        self.assertEqual(s.snapshot()['reason'],'PERSISTENT_BID_DENIAL')

    def test_default_mode_and_other_write_faults_are_unchanged(self):
        s=SemanticHealth(clock=lambda:0);s.observe(result())
        for _ in range(3):s.observe(result(**DENIAL))
        self.assertEqual(s.check(),'PERSISTENT_WRITE_FAILURE')
        s=SemanticHealth(clock=lambda:0,tolerate_denials=True);s.observe(result())
        for _ in range(3):s.observe(result(operation='bid',success=False,status=None,wire=[],verdict='UNCONFIRMED'))
        self.assertEqual(s.check(),'PERSISTENT_WRITE_FAILURE','only the exact denial shape is tolerated')
        s=SemanticHealth(clock=lambda:0,tolerate_denials=True);s.observe(result())
        for _ in range(2):s.observe(result(success=False,status=401))
        self.assertEqual(s.check(),'PERSISTENT_AUTH_FAILURE')

    def test_measure_registry(self):
        self.assertIsInstance(measure('continue'),ContinueMeasure)
        self.assertFalse(measure('continue').active);self.assertTrue(measure('continue').tolerate_denials)


def scripted_worker(connection,arguments,limits):
    counter=Path(arguments['fixture'])/'spawns.txt'
    spawn=int(counter.read_text())+1 if counter.exists() else 1;counter.write_text(str(spawn))
    s=Supervision(connection,limits)
    try:
        s.progress('LOCAL');s.state(dict(phase='ACQUIRING',lifecycle='RUNNING',reason=None,members=[]))
        s.report('native_result',**{k:v for k,v in result().items() if k!='kind'})
        script=arguments['script'] if spawn==1 else 'ok'
        if script=='denials':
            for _ in range(6):s.report('native_result',**{k:v for k,v in result(**DENIAL).items() if k!='kind'})
            s.report('native_result',**{k:v for k,v in result(**ACCEPTED).items() if k!='kind'})
        elif script=='auth':
            for _ in range(2):s.report('native_result',**{k:v for k,v in result(success=False,status=401).items() if k!='kind'})
        (Path(arguments['fixture'])/f'done-{spawn}').write_text('1')
        while True:s.require();time.sleep(.01)
    except SupervisionLost:
        try:s.report('exit',lifecycle='STOPPED',reason='WATCHDOG_STOP')
        except SupervisionLost:pass
    finally:connection.close()


class SupervisorTests(unittest.TestCase):
    def run_service(self,script,*,denial=None,auth=None,stop_after):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()));fixture=path/'fixture';fixture.mkdir()
        args=Namespace(database=str(fixture/'fixture.sqlite'),fixture=str(fixture),script=script)
        started=time.monotonic()
        with Runtime(path/'owner','t',GEN) as runtime:
            stop=lambda:'OPERATIONAL_STOP' if (fixture/stop_after).exists() or time.monotonic()-started>40 else None
            runtime.stop_reason=stop
            code=supervise(args,target=scripted_worker,runtime=runtime,output=io.StringIO(),denial_measure=denial,auth_measure=auth,
                           limits=replace(Limits(),poll=.01,grace=3,startup=15,local=15,native=15,lease=3))
            final=read(runtime.directory/'state.json')
        rows=[json.loads(l) for l in next(fixture.glob('watchdog-runs/*/events.jsonl')).read_text().splitlines()]
        return code,final,rows

    def test_continue_keeps_one_worker_running_through_denials(self):
        code,final,rows=self.run_service('denials',denial=ContinueMeasure(),stop_after='done-1')
        self.assertEqual((code,final['reason']),(0,'OPERATIONAL_STOP'))
        kinds=[r['kind'] for r in rows if r['kind']!='WORKER']
        # The wave's end is recorded; no refresh is attempted without --wave-refresh-after.
        self.assertEqual(kinds,['STARTED','DENIAL_WAVE_CLEARED','STOP_REQUESTED','STOPPED'])
        cleared=next(r for r in rows if r['kind']=='DENIAL_WAVE_CLEARED')
        self.assertEqual((cleared['refreshed'],cleared['denied']>0),(False,True))
        self.assertEqual(final['semantic']['denied_bids'],6)

    def test_auth_failure_runs_the_auth_measure_then_a_fresh_worker(self):
        calls=[]
        class FakeRelogin:
            name='relogin';active=True
            def attempt(self,cancelled):calls.append(1);time.sleep(1.2);return dict(outcome='READY',reason=None,steps=[])
        code,final,rows=self.run_service('auth',denial=ContinueMeasure(),auth=FakeRelogin(),stop_after='done-2')
        self.assertEqual((code,final['reason'],len(calls)),(0,'OPERATIONAL_STOP',1))
        started=next(r for r in rows if r['kind']=='DOCUMENT_RECOVERY_STARTED')
        self.assertEqual((started['cause'],started['measure']),('AUTH_FAILURE','relogin'))
        self.assertIn('WORKER_RESTARTED',[r['kind'] for r in rows])

    def test_auth_failure_without_an_auth_measure_still_stops(self):
        code,final,rows=self.run_service('auth',denial=ContinueMeasure(),stop_after='never')
        self.assertEqual((code,final['reason']),(1,'PERSISTENT_AUTH_FAILURE'))
        self.assertNotIn('WORKER_RESTARTED',[r['kind'] for r in rows])


if __name__=='__main__':unittest.main(verbosity=2)
