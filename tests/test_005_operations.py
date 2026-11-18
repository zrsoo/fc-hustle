"""Isolated real service/health/stop processes. All trading terminates in fixtures."""
from argparse import Namespace
from copy import deepcopy
from dataclasses import replace
import io
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from fc_access.controller_v1.operational import Runtime,identity,same_process,evaluate,health,stop,read,state_stream,atomic
from fc_access.controller_v1.watchdog import Supervision,SupervisionLost,Watchdog,Limits,supervise
from fc_access.controller_v1.semantic import SemanticHealth

TASK='fixture-operational-task'
GEN='a'*32


def fixture_worker(connection,arguments,limits):
    s=Supervision(connection,limits);s.progress('STARTING')
    with patch('socket.socket',side_effect=AssertionError('fixture has no network')):
        h=Harness(arguments['fixture'],1)
        try:
            h.store.supervision_guard=s.require;h.executor.progress=s.progress;h.executor.result=s.result
            h.store.semantic_report=s.policy_result
            s.snapshot=lambda:dict(h.controller.journal.state(),members=h.controller.journal.members())
            if arguments['mode']=='auth':h.ea.balance_fail=True
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                s.require();h.controller.run(steps=1,progress=s.state);time.sleep(.05)
            h.controller.stop();s.report('exit',lifecycle='STOPPED',reason='FIXTURE_DEADLINE')
        except SupervisionLost:
            s.report('exit',lifecycle='STOPPED',reason='WATCHDOG_STOP')
        finally:h.close();connection.close()


def fixture_service(directory,generation,mode):
    if mode=='delayed':time.sleep(.35)
    directory=Path(directory);fixture=directory/'fixtures'/generation;fixture.mkdir(parents=True,exist_ok=True)
    args=Namespace(database=str(fixture/'fixture.sqlite'),fixture=str(fixture),mode=mode)
    with Runtime(directory/'owner',TASK,generation) as runtime:
        return supervise(args,target=fixture_worker,runtime=runtime,
                         limits=replace(Limits(),startup=5,local=3,native=3,lease=2,grace=2,poll=.01))


class OperationsTests(unittest.TestCase):
    def test_atomic_snapshot_reader_allows_replacement_and_keeps_old_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as path:
            target=Path(path)/'state.json';atomic(target,dict(version=1,rows=list(range(100))))
            with state_stream(target) as opened:
                atomic(target,dict(version=2,rows=list(range(200))))
                self.assertEqual(json.load(opened),dict(version=1,rows=list(range(100))))
            self.assertEqual(read(target),dict(version=2,rows=list(range(200))))

    @unittest.skipUnless(sys.platform=='win32','Windows sharing contract')
    def test_legacy_windows_reader_contention_is_bounded_and_never_exposes_partial_state(self):
        import threading
        with tempfile.TemporaryDirectory() as path:
            target=Path(path)/'state.json';atomic(target,dict(version=1));opened=target.open()
            errors=[]
            def replace():
                try:atomic(target,dict(version=2))
                except OSError as error:errors.append(type(error).__name__)
            writer=threading.Thread(target=replace);writer.start();time.sleep(.1)
            self.assertTrue(writer.is_alive());opened.close();writer.join(2)
            self.assertFalse(writer.is_alive());self.assertEqual(errors,[]);self.assertEqual(read(target),dict(version=2))
            with target.open():
                started=time.monotonic()
                with self.assertRaises(OSError):atomic(target,dict(version=3))
                self.assertLess(time.monotonic()-started,1.5)
            self.assertEqual(read(target),dict(version=2));self.assertEqual(list(Path(path).glob('*.tmp')),[])

    @unittest.skipUnless(sys.platform=='win32','Windows sharing contract')
    def test_reader_released_after_old_half_second_budget_recovers_locally(self):
        import threading
        with tempfile.TemporaryDirectory() as path:
            target=Path(path)/'state.json';atomic(target,dict(version=1));opened=target.open();errors=[]
            def writer():
                try:atomic(target,dict(version=2))
                except OSError as error:errors.append(error)
            thread=threading.Thread(target=writer);thread.start()
            try:
                time.sleep(.7);self.assertTrue(thread.is_alive());self.assertEqual(json.load(opened),dict(version=1))
            finally:opened.close();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            self.assertEqual(read(target),dict(version=2));self.assertEqual(list(Path(path).glob('*.tmp')),[])

    def test_runtime_failure_projection_keeps_only_finite_error_identity(self):
        from fc_access.controller_v1.watchdog import runtime_failure
        error=PermissionError(13,'SECRET_CANARY','C:/SECRET_CANARY');error.winerror=32
        error.runtime_io_stage='replace';error.runtime_target='current_state'
        self.assertEqual(runtime_failure(error),dict(exception='PermissionError',errno=13,winerror=32,runtime_io_stage='replace',runtime_target='current_state'))
        error.errno=True;error.winerror=-1;error.runtime_io_stage='SECRET_CANARY';error.runtime_target='SECRET_CANARY'
        self.assertEqual(runtime_failure(error),dict(exception='PermissionError'))
        class SECRET_CANARY(ValueError):pass
        self.assertEqual(runtime_failure(SECRET_CANARY('SECRET_CANARY')),dict(exception='ValueError'))

    def test_snapshot_failure_identifies_io_stage_and_target_without_partial_success(self):
        from fc_access.controller_v1 import operational as module
        with tempfile.TemporaryDirectory() as path:
            target=Path(path)/'state.json';atomic(target,dict(version=1))
            with patch.object(module,'replace_snapshot',side_effect=OSError(28,'SECRET_CANARY')):
                with self.assertRaises(OSError) as caught:atomic(target,dict(version=2))
            self.assertEqual(caught.exception.runtime_io_stage,'replace');self.assertEqual(read(target),dict(version=1))
            self.assertEqual(list(Path(path).glob('*.tmp')),[])
            with Runtime(Path(path)/'owner',TASK,GEN) as runtime:
                original=module.atomic
                def failing_current(destination,value):
                    if Path(destination)==runtime.directory/'state.json':raise OSError(28,'SECRET_CANARY')
                    return original(destination,value)
                with patch.object(module,'atomic',side_effect=failing_current):
                    with self.assertRaises(OSError) as caught:runtime.publish(None,'STARTING',force=True)
                self.assertEqual(caught.exception.runtime_target,'current_state')

    def test_transient_and_persistent_read_denial_do_not_fabricate_health_or_leak_error_values(self):
        from fc_access.controller_v1 import operational as module
        base=self.fixture_state()
        with patch.object(module,'read',side_effect=[PermissionError('SECRET_CANARY'),base]),patch.object(module,'held',return_value=True),patch.object(module,'same_process',return_value=True),patch.object(module.time,'monotonic',return_value=100):
            self.assertEqual(health('unused',TASK,GEN)['status'],'healthy')
        with patch.object(module,'read',side_effect=PermissionError('SECRET_CANARY')):
            started=time.monotonic();result=health('unused',TASK,GEN)
            self.assertLess(time.monotonic()-started,3)
            self.assertEqual(result['status'],'repair');self.assertEqual(result['evidence'][0]['runtime_read_error'],'PermissionError')
            self.assertNotIn('CANARY',json.dumps(result))
    def start(self,directory,generation=GEN,mode='healthy'):
        return subprocess.Popen([sys.executable,__file__,'fixture',str(directory),generation,mode],
                                cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)

    def wait_health(self,directory,process,generation=GEN):
        deadline=time.monotonic()+10;last=None
        while time.monotonic()<deadline:
            last=health(Path(directory)/'owner',TASK,generation)
            if last['status']=='healthy':return last
            if process.poll() is not None:self.fail('fixture exited: '+process.communicate()[1])
            time.sleep(.05)
        self.fail('no semantic health: '+json.dumps(last))

    def cleanup_process(self,p):
        if p.poll() is None:p.terminate()
        try:
            if p.stderr and not p.stderr.closed:p.communicate(timeout=5)
            else:p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill();p.wait(5)

    def test_real_service_excludes_duplicate_and_stop_is_idempotent_with_generation_binding(self):
        with tempfile.TemporaryDirectory() as path:
            p=self.start(path);self.addCleanup(self.cleanup_process,p)
            self.wait_health(path,p)
            health_command=[sys.executable,'-m','fc_access.controller_v1.operational','health','--runtime-dir',str(Path(path)/'owner'),'--task-key',TASK,'--generation',GEN]
            for _ in range(2):
                checked=subprocess.run(health_command,cwd=ROOT,capture_output=True,text=True,timeout=5)
                self.assertEqual(checked.returncode,0,checked.stderr)
                payload=json.loads(checked.stdout)
                self.assertEqual(set(payload),{'status','generation','diagnostic','evidence'})
                self.assertEqual(payload['status'],'healthy');self.assertEqual(payload['generation'],GEN)
                self.assertGreater(payload['evidence'][0]['native_successes'],0)
            duplicate=self.start(path,'b'*32)
            self.assertEqual(duplicate.wait(5),1);duplicate.communicate()
            self.assertEqual(len(list((Path(path)/'owner/runs').iterdir())),1)
            before=read(Path(path)/'owner/state.json')
            with self.assertRaises(ValueError):stop(Path(path)/'owner','other-task',GEN,timeout=2)
            self.assertTrue(same_process(before['child']))
            command=[sys.executable,'-m','fc_access.controller_v1.operational','stop','--runtime-dir',str(Path(path)/'owner'),'--task-key',TASK,'--generation',GEN]
            first=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(first.returncode,0,first.stdout+first.stderr);self.assertEqual(json.loads(first.stdout)['status'],'stopped')
            self.assertEqual(p.wait(5),0);p.communicate()
            self.assertEqual(stop(Path(path)/'owner',TASK,GEN,timeout=1)['status'],'stopped')
            reused=self.start(path);self.assertEqual(reused.wait(5),1);reused.communicate()
            newer=self.start(path,'c'*32);self.addCleanup(self.cleanup_process,newer)
            self.wait_health(path,newer,'c'*32)
            with self.assertRaises(ValueError):stop(Path(path)/'owner',TASK,GEN,timeout=1)
            self.assertIsNone(newer.poll())
            self.assertEqual(stop(Path(path)/'owner',TASK,'c'*32,timeout=5)['status'],'stopped')
            self.assertEqual(newer.wait(5),0);newer.communicate()

    def test_immediate_health_waits_for_real_manifest_and_absence_never_extends_startup(self):
        with tempfile.TemporaryDirectory() as path:
            p=self.start(path,mode='delayed');self.addCleanup(self.cleanup_process,p)
            # No readiness wait before the scheduler-style first health check.
            first=health(Path(path)/'owner',TASK,GEN)
            self.assertIn(first['status'],{'starting','healthy'},first)
            actual=read(Path(path)/'owner/state.json')
            self.assertEqual(actual['generation'],GEN)
            self.assertTrue(same_process(actual['supervisor']))
            self.wait_health(path,p)
            self.assertEqual(stop(Path(path)/'owner',TASK,GEN,timeout=5)['status'],'stopped')
            self.assertEqual(p.wait(5),0);p.communicate()
        with tempfile.TemporaryDirectory() as path:
            started=time.monotonic()
            for _ in range(2):
                result=health(Path(path)/'absent',TASK,GEN)
                self.assertEqual(result['status'],'repair')
                self.assertEqual(result['diagnostic'],'RUNTIME_STATE_UNAVAILABLE')
            self.assertLess(time.monotonic()-started,6)

    def test_real_semantic_fault_stops_without_restart_and_preserves_stop_reason(self):
        with tempfile.TemporaryDirectory() as path:
            p=self.start(path,mode='auth');self.addCleanup(self.cleanup_process,p)
            self.assertEqual(p.wait(10),1);p.communicate()
            value=read(Path(path)/'owner/state.json')
            self.assertEqual(value['state'],'STOPPED');self.assertEqual(value['reason'],'PERSISTENT_READ_FAILURE')
            self.assertFalse(same_process(value['child']))
            stopped=health(Path(path)/'owner',TASK,GEN)
            self.assertEqual(stopped['status'],'repair');self.assertEqual(stopped['diagnostic'],'PERSISTENT_READ_FAILURE')
            self.assertEqual(len(list((Path(path)/'owner/runs').iterdir())),1)

    def test_parent_death_releases_ownership_and_child_loses_dispatch_lease(self):
        with tempfile.TemporaryDirectory() as path:
            p=self.start(path);self.addCleanup(self.cleanup_process,p);self.wait_health(path,p)
            value=read(Path(path)/'owner/state.json');p.kill();p.wait(5);p.communicate()
            self.assertEqual(health(Path(path)/'owner',TASK,GEN)['status'],'repair')
            deadline=time.monotonic()+5
            while same_process(value['child']) and time.monotonic()<deadline:time.sleep(.05)
            self.assertFalse(same_process(value['child']))
            self.assertEqual(stop(Path(path)/'owner',TASK,GEN,timeout=1)['status'],'stopped')

    def fixture_state(self):
        tick=[100.];monitor=Watchdog(clock=lambda:tick[0],semantic=SemanticHealth(clock=lambda:tick[0]))
        monitor.latest=dict(stage='LOCAL',tick=100.,phase='MANAGING',lifecycle='RUNNING')
        monitor.semantic.last_native_success=99.;monitor.semantic.native_successes=10
        return dict(schema=1,task=TASK,generation=GEN,supervisor={},child={},state='RUNNING',operational_state='MANAGING',
                    started_mono=0.,published_mono=100.,latest=monitor.latest,semantic=monitor.semantic.snapshot(),reason=None)

    def test_health_rejects_life_only_failed_reads_gaps_and_unbounded_startup(self):
        base=self.fixture_state()
        def check(v,**kwargs):return evaluate(v,task=TASK,generation=GEN,now=100.,owner_held=True,supervisor_alive=True,child_alive=True,**kwargs)
        self.assertEqual(check(base)['status'],'healthy')
        for mutate in (lambda v:v.update(published_mono=90),lambda v:v.update(generation='b'*32),
                       lambda v:v['semantic'].update(read_failures=3),lambda v:v['semantic'].update(helper_failures=3),
                       lambda v:v['semantic'].update(native_success_age=91),lambda v:v['semantic'].update(native_success_age=-1),
                       lambda v:v['semantic'].update(native_successes=True),lambda v:v['semantic'].update(native_successes=0,native_success_age=None),
                       lambda v:v['latest'].update(tick=0),lambda v:v['latest'].update(lifecycle='STOPPED')):
            changed=deepcopy(base);mutate(changed);self.assertEqual(check(changed)['status'],'repair')
        starting=deepcopy(base);starting.update(started_mono=95);starting['semantic'].update(native_successes=0,native_success_age=None)
        self.assertEqual(check(starting)['status'],'starting')
        missing=deepcopy(base);missing.pop('semantic');self.assertEqual(check(missing)['status'],'repair')
        stale=identity(__import__('os').getpid());stale['created']+=1;self.assertFalse(same_process(stale))

    def test_runtime_state_write_failure_still_joins_owned_worker(self):
        from test_controller_watchdog import offline_worker
        with tempfile.TemporaryDirectory() as path:
            fixture=Path(path)/'fixture';fixture.mkdir()
            args=Namespace(database=str(fixture/'fixture.sqlite'),fixture=str(fixture),mode='cooperative')
            before={p.pid for p in multiprocessing.active_children()}
            with Runtime(Path(path)/'owner',TASK,GEN) as runtime:
                with patch.object(runtime,'publish',side_effect=OSError('fixture_disk_full')):
                    code=supervise(args,target=offline_worker,runtime=runtime,limits=replace(Limits(),poll=.01,grace=2),output=io.StringIO())
            self.assertEqual(code,1);self.assertEqual({p.pid for p in multiprocessing.active_children()},before)
            rows=[json.loads(line) for line in next(fixture.glob('watchdog-runs/*/events.jsonl')).read_text().splitlines()]
            self.assertEqual(rows[-1]['kind'],'STOPPED');self.assertEqual(rows[-1]['reason'],'RUNTIME_STATE_FAILED')
            failures=[row for row in rows if row['kind']=='RUNTIME_PUBLISH_FAILED']
            self.assertEqual(len(failures),1);self.assertEqual(failures[0]['exception'],'OSError')
            self.assertNotIn('fixture_disk_full',json.dumps(rows))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='fixture':raise SystemExit(fixture_service(*sys.argv[2:]))
    unittest.main(verbosity=2)
