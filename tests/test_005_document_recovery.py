"""Bounded stale-document recovery; entirely offline (fake UI, fixture workers)."""
from argparse import Namespace
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from fc_access.controller_v1 import recovery as module
from fc_access.controller_v1.recovery import DocumentRecovery, UIStepFailed, powershell
from fc_access.controller_v1.semantic import SemanticHealth
from fc_access.controller_v1.watchdog import Limits, Supervision, SupervisionLost, Watchdog, supervise
from fc_access.controller_v1.operational import (Runtime, evaluate, read, RECOVERY_WINDOW,
                                                 STARTUP_REFRESH_SECONDS)

TASK='fixture-recovery-task'
GEN='d'*32
ACCOUNT='fixture.account'


def native(operation='balance',*,success=True,status=200,wire=None,verdict=None):
    return dict(operation=operation,command_id='a'*32,local=False,
                read=operation in {'balance','watched','status_batch','search'},market_race=False,
                success=success,error=None if success else 'ambiguous_network',service_status=status,
                wire_statuses=[status] if wire is None else wire,receipt_verdict=verdict,requested=0,returned=0)


DENIED=dict(operation='bid',success=False,status=403,wire=[461],verdict='UNCONFIRMED')


def denial_worker(connection,arguments,limits):
    """Fixture worker: first spawn (or every spawn when 'always') hits the stale signature."""
    counter=Path(arguments['fixture'])/'spawns.txt'
    spawn=int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(spawn))
    s=Supervision(connection,limits)
    try:
        s.progress('LOCAL');s.state(dict(phase='ACQUIRING',lifecycle='RUNNING',reason=None,members=[]))
        s.report('native_result',**native())
        if arguments['mode']=='always' or arguments['mode']=='once' and spawn==1:
            for _ in range(3):s.report('native_result',**native(**DENIED))
        else:
            s.report('native_result',**native('watched'))
            (Path(arguments['fixture'])/f'ready-{spawn}').write_text('1')
        while True:
            s.require();time.sleep(.01)
    except SupervisionLost:
        try:s.report('exit',lifecycle='STOPPED',reason=s.reason or 'WATCHDOG_STOP')
        except SupervisionLost:pass
    finally:connection.close()


def ambiguous_write_worker(connection,arguments,limits):
    s=Supervision(connection,limits)
    try:
        s.progress('LOCAL');s.state(dict(phase='ACQUIRING',lifecycle='RUNNING',reason=None,members=[]))
        s.report('native_result',**native())
        for _ in range(3):s.report('native_result',**native('bid',success=False,status=None,wire=[],verdict='UNCONFIRMED'))
        while True:s.require();time.sleep(.01)
    except SupervisionLost:
        try:s.report('exit',lifecycle='STOPPED',reason='WATCHDOG_STOP')
        except SupervisionLost:pass
    finally:connection.close()


class FakeUI:
    """Scripted official-page observations; records every requested UI action."""
    def __init__(self,screens):
        self.screens=list(screens);self.calls=[]
    def __call__(self,action,**fields):
        self.calls.append((action,fields.get('name')))
        if action=='observe':
            screen=self.screens.pop(0) if len(self.screens)>1 else self.screens[0]
            if isinstance(screen,Exception):raise screen
            return {'window':77,**screen}
        return dict(window=77,action=action)


def web(*actions,ready=False):return dict(kind='official_webapp',challenge=False,ready=ready,email_field=False,actions=list(actions))
def signin(*actions,email=False):return dict(kind='official_EA_signin',challenge=False,ready=False,email_field=email,actions=list(actions))


class RecoveryPolicyTests(unittest.TestCase):
    def run_recovery(self,screens,**kwargs):
        ui=FakeUI(screens);tick=[0.]
        def sleep(seconds):tick[0]+=seconds
        r=DocumentRecovery(ACCOUNT,ui=ui,clock=lambda:tick[0],sleep=sleep,**kwargs).run()
        return r,ui

    def test_reload_alone_restores_settled_web_app(self):
        r,ui=self.run_recovery([web(),web(),web(ready=True),web(ready=True)])
        self.assertEqual(r['outcome'],'READY')
        self.assertEqual([c for c in ui.calls if c[0]!='observe'],[('reload',None)])

    def test_full_normal_sign_in_uses_only_allowlisted_steps_in_order(self):
        r,ui=self.run_recovery([web(),web('Login'),signin('NEXT',email=True),signin('NEXT',email=True),
                                signin('SIGN IN'),web('Continue'),web(ready=True),web(ready=True)])
        self.assertEqual(r['outcome'],'READY',r)
        self.assertEqual([c for c in ui.calls if c[0]!='observe'],
                         [('reload',None),('click','Login'),('select-account',None),('click','NEXT'),('click','SIGN IN'),('click','Continue')])
        self.assertNotIn(ACCOUNT,json.dumps(r),'the account label is never retained in evidence')

    def test_live_sequence_with_login_before_and_after_sign_in_recovers(self):
        # Replay of the 2026-11-19 04:08Z live run, which failed on the old
        # whole-flow click budget although the sign-in itself succeeded.
        r,ui=self.run_recovery([web(),web('Login'),web(),web('Login'),signin('NEXT',email=True),signin('NEXT',email=True),
                                signin('SIGN IN'),web(),web('Login'),web('Login'),web(ready=True),web(ready=True)])
        self.assertEqual(r['outcome'],'READY',r)
        self.assertEqual(sum(1 for c in ui.calls if c==('click','Login')),4)
        # A Login that never makes progress on one visit still fails closed.
        r,_=self.run_recovery([web(),web('Login')])
        self.assertEqual((r['outcome'],r['reason']),('FAILED','normal_action_repeated'))

    def test_security_challenge_is_left_to_the_user(self):
        r,ui=self.run_recovery([web(),web('Login'),dict(signin('NEXT'),challenge=True)])
        self.assertEqual((r['outcome'],r['reason']),('CHALLENGE','USER_SECURITY_CHALLENGE'))
        self.assertEqual(ui.calls[-1][0],'observe','no input after a challenge is observed')
        r,_=self.run_recovery([web(),UIStepFailed('user_security_challenge_required')])
        self.assertEqual(r['outcome'],'CHALLENGE')

    def test_unknown_page_loops_deadline_and_cancellation_fail_closed(self):
        r,_=self.run_recovery([web(),dict(web(),kind='other')])
        self.assertEqual((r['outcome'],r['reason']),('FAILED','UNEXPECTED_PAGE'))
        r,ui=self.run_recovery([web(),web('Login')])
        self.assertEqual((r['outcome'],r['reason']),('FAILED','normal_action_repeated'))
        self.assertEqual(sum(1 for c in ui.calls if c==('click','Login')),3)
        r,_=self.run_recovery([web(),web()],deadline=10)
        self.assertEqual((r['outcome'],r['reason']),('FAILED','RECOVERY_TIMEOUT'))
        r,ui=self.run_recovery([web(),web(ready=True)],cancelled=lambda:True)
        self.assertEqual(r['outcome'],'CANCELLED');self.assertEqual([c[0] for c in ui.calls],['observe','reload'])
        r,_=self.run_recovery([dict(web(),window=None)])
        self.assertEqual((r['outcome'],r['reason']),('FAILED','ui_output_invalid'))

    def test_account_label_and_script_failures_are_finite(self):
        for bad in ('','a b','x'*65,'semi;colon',None):
            with self.assertRaises(ValueError):DocumentRecovery(bad)
        failed=subprocess.CompletedProcess([],1,stdout='',stderr='SECRET_CANARY foreground_changed C:/SECRET_CANARY')
        with patch.object(module.subprocess,'run',return_value=failed):
            with self.assertRaises(UIStepFailed) as caught:powershell('observe')
        self.assertEqual(caught.exception.reason,'foreground_changed')
        failed.stderr='SECRET_CANARY'
        with patch.object(module.subprocess,'run',return_value=failed):
            with self.assertRaises(UIStepFailed) as caught:powershell('observe')
        self.assertEqual(caught.exception.reason,'ui_step_failed')
        ok=subprocess.CompletedProcess([],0,stdout='noise\n{"window": 5, "kind": "official_webapp"}\n',stderr='')
        with patch.object(module.subprocess,'run',return_value=ok) as run:
            self.assertEqual(powershell('click',window=5,name='Login')['window'],5)
        argv=run.call_args.args[0]
        self.assertEqual(argv[argv.index('-Action')+1],'click');self.assertIn('-NonInteractive',argv)


class SignatureTests(unittest.TestCase):
    def test_only_consecutive_denials_with_working_reads_are_recoverable(self):
        s=SemanticHealth(clock=lambda:0);s.observe(dict(kind='native_result',**native()))
        for _ in range(3):s.observe(dict(kind='native_result',**native(**DENIED)))
        self.assertEqual(s.check(),'PERSISTENT_WRITE_FAILURE');self.assertEqual(s.recoverable(),'STALE_DOCUMENT_WRITE_DENIAL')
        self.assertEqual(s.snapshot()['recoverable'],'STALE_DOCUMENT_WRITE_DENIAL')
        mixed=SemanticHealth(clock=lambda:0);mixed.observe(dict(kind='native_result',**native()))
        for value in (native(**DENIED),native('bid',success=False,status=None,wire=[],verdict='UNCONFIRMED'),native(**DENIED)):
            mixed.observe(dict(kind='native_result',**value))
        self.assertEqual(mixed.check(),'PERSISTENT_WRITE_FAILURE');self.assertIsNone(mixed.recoverable())
        no_reads=SemanticHealth(clock=lambda:0)
        for _ in range(3):no_reads.observe(dict(kind='native_result',**native(**DENIED)))
        self.assertIsNone(no_reads.recoverable(),'never recover without proven working native reads')
        auth=SemanticHealth(clock=lambda:0);auth.observe(dict(kind='native_result',**native()))
        auth.observe(dict(kind='native_result',**native(success=False,status=401)))
        for _ in range(3):auth.observe(dict(kind='native_result',**native(**DENIED)))
        self.assertIsNone(auth.recoverable())


class HealthTests(unittest.TestCase):
    def state(self,**recovery):
        tick=[100.];monitor=Watchdog(clock=lambda:tick[0],semantic=SemanticHealth(clock=lambda:tick[0]))
        monitor.latest=dict(stage='LOCAL',tick=0.,phase='ACQUIRING',lifecycle='RUNNING')
        return dict(schema=1,task=TASK,generation=GEN,supervisor={},child=None,state='RUNNING',operational_state='DOCUMENT_RECOVERY',
                    started_mono=0.,published_mono=100.,latest=monitor.latest,semantic=dict(monitor.semantic.snapshot(),reason='PERSISTENT_WRITE_FAILURE'),
                    reason=None,recovery=dict(dict(started_mono=50.,attempt=1,cause='STALE_DOCUMENT_WRITE_DENIAL',initial=False),**recovery))

    def check(self,value,child_alive=False,**kwargs):
        return evaluate(value,task=TASK,generation=GEN,now=100.,owner_held=True,supervisor_alive=True,child_alive=child_alive,**kwargs)

    def test_bounded_recovery_is_reported_explicitly_and_times_out(self):
        self.assertEqual((r:=self.check(self.state()))['status'],'healthy');self.assertEqual(r['diagnostic'],'DOCUMENT_RECOVERY')
        self.assertEqual(self.check(self.state(started_mono=100.-RECOVERY_WINDOW-1))['diagnostic'],'DOCUMENT_RECOVERY_TIMEOUT')
        self.assertEqual(self.check(self.state(started_mono=101.))['status'],'repair')
        stopped=self.state();stopped['state']='STOPPED';stopped['reason']='DOCUMENT_RECOVERY_FAILED'
        self.assertEqual(self.check(stopped)['diagnostic'],'DOCUMENT_RECOVERY_FAILED')
        stale=self.state();stale['published_mono']=50.
        self.assertEqual(self.check(stale)['diagnostic'],'RUNTIME_STATE_STALE')
        self.assertEqual(evaluate(self.state(),task=TASK,generation=GEN,now=100.,owner_held=True,supervisor_alive=False,child_alive=False)['status'],'repair')

    def test_startup_refresh_is_starting_never_healthy_and_bounded(self):
        initial=self.state(initial=True,started_mono=0.)
        self.assertEqual(self.check(initial)['status'],'starting')
        late=deepcopy(initial);late['published_mono']=STARTUP_REFRESH_SECONDS+1;late['recovery']['started_mono']=STARTUP_REFRESH_SECONDS-10
        self.assertEqual(evaluate(late,task=TASK,generation=GEN,now=STARTUP_REFRESH_SECONDS+1,owner_held=True,
                                  supervisor_alive=True,child_alive=True)['diagnostic'],'STARTUP_REFRESH_TIMEOUT')


class SupervisorTests(unittest.TestCase):
    limits=replace(Limits(),poll=.01,grace=3,startup=15,local=15,native=15,lease=3)

    def run_service(self,mode,*,recovery,target=denial_worker,refresh=False,limits=None,stop_after=None):
        path=Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixture=path/'fixture';fixture.mkdir()
        args=Namespace(database=str(fixture/'fixture.sqlite'),fixture=str(fixture),mode=mode)
        states=[];calls=[]
        class FakeMeasure:
            name='fake';active=True
            def attempt(self,cancelled):
                # Long enough for at least one throttled (1/s) state publication.
                calls.append(time.monotonic());time.sleep(1.2);return recovery()
        measure=FakeMeasure() if recovery else None
        with Runtime(path/'owner',TASK,GEN) as runtime:
            original=runtime.publish
            def publish(*a,**k):
                written=original(*a,**k)
                if written:states.append(read(runtime.directory/'state.json'))
                return written
            started=time.monotonic()
            def stop():
                if (fixture/(stop_after or 'never')).exists():return 'OPERATIONAL_STOP'
                return 'OPERATIONAL_STOP' if time.monotonic()-started>40 else None
            with patch.object(runtime,'publish',side_effect=publish),patch.object(runtime,'stop_reason',side_effect=stop):
                code=supervise(args,target=target,runtime=runtime,limits=limits or self.limits,output=io.StringIO(),
                               denial_measure=None if refresh else measure,startup_refresh=measure if refresh else None)
            final=read(runtime.directory/'state.json')
        rows=[json.loads(l) for l in next(fixture.glob('watchdog-runs/*/events.jsonl')).read_text().splitlines()]
        return code,final,rows,states,calls

    def test_stale_signature_recovers_once_and_fresh_worker_resumes(self):
        code,final,rows,states,calls=self.run_service('once',recovery=lambda:dict(outcome='READY',reason=None,steps=[{'action':'reload'}]),stop_after='ready-2')
        kinds=[r['kind'] for r in rows if r['kind']!='WORKER']
        self.assertEqual(code,0,kinds);self.assertEqual(len(calls),1)
        # Recovery is marked and published before the worker is stopped.
        self.assertEqual(kinds,['STARTED','DOCUMENT_RECOVERY_STARTED','WORKER_STOP_REQUESTED','WORKER_STOPPED','DOCUMENT_RECOVERY_RESULT',
                                'WORKER_RESTARTED','DOCUMENT_RECOVERY_COMPLETED','STOP_REQUESTED','STOPPED'])
        stop=next(r for r in rows if r['kind']=='WORKER_STOP_REQUESTED');self.assertEqual(stop['reason'],'PERSISTENT_WRITE_FAILURE')
        self.assertEqual(next(r for r in rows if r['kind']=='DOCUMENT_RECOVERY_STARTED')['cause'],'STALE_DOCUMENT_WRITE_DENIAL')
        self.assertTrue(all(type(r.get('mono')) is float for r in rows if r['kind'].startswith(('WORKER_','DOCUMENT_'))))
        self.assertIn('DOCUMENT_RECOVERY',{s['operational_state'] for s in states})
        first=next(i for i,s in enumerate(states) if s['semantic'] and s['semantic']['reason']=='PERSISTENT_WRITE_FAILURE')
        self.assertIsNotNone(states[first]['recovery'],'the fault is never published without its recovery marker')
        self.assertEqual((final['state'],final['reason'],final['recovery']),('STOPPED','OPERATIONAL_STOP',None))
        self.assertEqual(len([r for r in rows if r['kind']=='WORKER' and r['message'].get('operation')=='bid']),3,'no bid replayed by recovery')

    def test_denial_again_after_recovery_is_a_genuine_persistent_failure(self):
        code,final,rows,_,calls=self.run_service('always',recovery=lambda:dict(outcome='READY',reason=None,steps=[]))
        self.assertEqual(code,1);self.assertEqual(len(calls),1)
        self.assertEqual(final['reason'],'PERSISTENT_WRITE_FAILURE')
        refused=[r for r in rows if r['kind']=='DOCUMENT_RECOVERY_REFUSED']
        self.assertEqual([r['refused'] for r in refused],['DENIAL_PERSISTS_AFTER_RECOVERY'])

    def test_challenge_or_failed_recovery_stops_without_new_worker(self):
        for outcome,reason in (('CHALLENGE','USER_SECURITY_CHALLENGE'),('FAILED','DOCUMENT_RECOVERY_FAILED')):
            code,final,rows,_,_=self.run_service('once',recovery=lambda:dict(outcome=outcome,reason='x',steps=[]))
            self.assertEqual(code,1);self.assertEqual(final['reason'],reason)
            self.assertNotIn('WORKER_RESTARTED',[r['kind'] for r in rows])
            self.assertEqual([r['kind'] for r in rows][-2:],['STOP_REQUESTED','STOPPED'])

    def test_other_write_faults_and_missing_recovery_never_restart(self):
        code,final,rows,_,calls=self.run_service('once',recovery=lambda:dict(outcome='READY',steps=[]),target=ambiguous_write_worker)
        self.assertEqual((code,final['reason'],calls),(1,'PERSISTENT_WRITE_FAILURE',[]))

    def test_noop_measure_logs_the_signature_and_stops_exactly_as_before(self):
        code,final,rows,states,_=self.run_service('once',recovery=None)
        self.assertEqual((code,final['reason']),(1,'PERSISTENT_WRITE_FAILURE'))
        self.assertFalse(any(r['kind'].startswith(('DOCUMENT_','WORKER_')) for r in rows))
        signature=[r for r in rows if r['kind']=='WRITE_DENIAL_SIGNATURE']
        self.assertEqual([(r['cause'],r['measure']) for r in signature],[('STALE_DOCUMENT_WRITE_DENIAL','noop')])
        self.assertTrue(all(s['recovery'] is None for s in states))

    def test_measures_are_selected_by_name_and_validated(self):
        from fc_access.controller_v1.measures import measure, NoOpMeasure, ReloginMeasure
        self.assertIsInstance(measure('noop'),NoOpMeasure);self.assertFalse(measure('noop').active)
        with tempfile.TemporaryDirectory() as path:
            config=Path(path)/'recovery.json';config.write_text(json.dumps({'account_label':ACCOUNT}))
            relogin=measure('relogin',recovery_config=config)
            self.assertIsInstance(relogin,ReloginMeasure);self.assertTrue(relogin.active)
            config.write_text(json.dumps({'account_label':'bad label'}))
            with self.assertRaises(ValueError):measure('relogin',recovery_config=config)
            config.write_text(json.dumps({'account_label':ACCOUNT,'password':'x'}))
            with self.assertRaises(ValueError):measure('relogin',recovery_config=config)
        for name,config in (('relogin',None),('unknown',None)):
            with self.assertRaises(ValueError):measure(name,recovery_config=config)

    def test_budget_limits_recoveries(self):
        limits=replace(self.limits,recovery_per_hour=0)
        code,final,rows,_,calls=self.run_service('once',recovery=lambda:dict(outcome='READY',steps=[]),limits=limits)
        self.assertEqual((code,final['reason'],calls),(1,'PERSISTENT_WRITE_FAILURE',[]))
        self.assertEqual([r['refused'] for r in rows if r['kind']=='DOCUMENT_RECOVERY_REFUSED'],['RECOVERY_BUDGET_EXHAUSTED'])

    def test_refresh_on_start_runs_before_the_first_worker(self):
        code,final,rows,states,calls=self.run_service('fresh',recovery=lambda:dict(outcome='READY',steps=[]),refresh=True,stop_after='ready-1')
        kinds=[r['kind'] for r in rows if r['kind']!='WORKER']
        self.assertEqual(code,0,kinds);self.assertEqual(len(calls),1)
        self.assertEqual(kinds[:3],['DOCUMENT_RECOVERY_STARTED','DOCUMENT_RECOVERY_RESULT','STARTED'])
        self.assertTrue(any(s['recovery'] and s['recovery']['initial'] for s in states))
        code,final,rows,_,_=self.run_service('fresh',recovery=lambda:dict(outcome='FAILED',reason='x',steps=[]),refresh=True)
        self.assertEqual((code,final['reason']),(1,'DOCUMENT_RECOVERY_FAILED'))
        self.assertEqual(rows[-1],dict(rows[-1],kind='STOPPED',worker_started=False))


if __name__=='__main__':unittest.main(verbosity=2)
