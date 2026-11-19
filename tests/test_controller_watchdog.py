"""Actual supervisor processes plus production-controller fixtures; no EA I/O."""
from argparse import Namespace
from dataclasses import replace
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from fc_access.controller_v1.watchdog import Limits,Supervision,SupervisionLost,Watchdog,supervise


class PipeFixture:
    def __init__(self):self.incoming=[];self.sent=[];self.eof=False
    def poll(self):return bool(self.incoming) or self.eof
    def recv(self):
        if self.eof:raise EOFError
        return self.incoming.pop(0)
    def send(self,value):self.sent.append(value)


def offline_worker(connection,arguments,limits):
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    supervision=Supervision(connection,limits)
    try:supervision.progress('STARTING')
    except SupervisionLost:connection.close();return
    mode=arguments['mode']
    if mode=='crash':os._exit(73)
    if mode=='cooperative':
        supervision.state(dict(phase='MANAGING',lifecycle='RUNNING',reason=None,members=[]))
        while True:
            try:supervision.require()
            except SupervisionLost:
                supervision.report('exit',lifecycle='STOPPED',reason='WATCHDOG_STOP');connection.close();return
            time.sleep(.02)
    if mode=='stall':
        supervision.state(dict(phase='MANAGING',lifecycle='RUNNING',reason=None,members=[]))
        time.sleep(60);return
    # Failure to construct *any* socket is intentional: fixture workers never
    # connect to a production port, attach a browser or use a live account.
    with patch('socket.socket',side_effect=AssertionError('offline_only')):
        h=Harness(arguments['fixture'],2)
        try:
            h.store.supervision_guard=supervision.require
            h.executor.progress=supervision.progress
            if mode=='halt':h.ea.credits=40000
            else:
                h.ea.bid_modes[h.ea.rows[0]['trade_id']]='timeout'
                h.ea.bid_modes[h.ea.rows[1]['trade_id']]='reject'
            h.controller.run(steps=1,progress=supervision.state)
            state=h.controller.status()
            if mode!='halt':h.controller.stop()
            supervision.report('exit',lifecycle=state['lifecycle'] if mode=='halt' else 'STOPPED',
                reason=state['reason'] if mode=='halt' else 'OPERATOR_STOPPED',
                attempts=[v['state'] for v in h.attempts()],ea_calls=len(h.ea.calls))
        finally:h.close();connection.close()


def orphan_worker(connection,path):
    # The child must refuse subsequent work even if its supervisor is killed
    # outright, with no opportunity to send a cooperative stop.
    supervision=Supervision(connection,replace(Limits(),lease=.5))
    supervision.require()
    Path(path,'ready').write_text('ready')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        try:supervision.require()
        except SupervisionLost:
            Path(path,'orphan-result.json').write_text(json.dumps(dict(reason=supervision.reason,dispatches=0)))
            connection.close();return
        time.sleep(.02)
    raise AssertionError('orphan guard never fired')


def orphan_parent(path):
    ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe()
    parent.send(dict(action='lease',tick=time.monotonic()))
    process=ctx.Process(target=orphan_worker,args=(child,path));process.start();child.close()
    deadline=time.monotonic()+10
    while not Path(path,'ready').exists() and time.monotonic()<deadline:
        parent.send(dict(action='lease',tick=time.monotonic()));time.sleep(.02)
    os._exit(74)


class WatchdogTests(unittest.TestCase):
    def test_deadlines_are_per_work_boundary_not_per_cycle_or_acquisition(self):
        tick=[0.];w=Watchdog(clock=lambda:tick[0])
        w.observe(dict(kind='progress',stage='LOCAL',tick=0,phase='MANAGING',lifecycle='RUNNING'))
        # Ten paced requests make a 26-second cycle, with no overlapping work.
        for n in range(10):
            tick[0]=2.6*n;w.observe(dict(kind='progress',stage='NATIVE',tick=tick[0],operation='bid'))
            tick[0]+=2.6;self.assertIsNone(w.check())
            w.observe(dict(kind='progress',stage='LOCAL',tick=tick[0]))
        self.assertAlmostEqual(tick[0],26);self.assertIsNone(w.check())
        # Even a long cold acquisition is healthy while finite requests finish.
        for _ in range(100):
            tick[0]+=10;w.observe(dict(kind='progress',stage='LOCAL',tick=tick[0]));self.assertIsNone(w.check())
        self.assertIn('MANAGING',w.line())

    def test_stalls_halts_failures_and_invalid_packets_have_explicit_reasons(self):
        for stage,seconds,reason in [('NATIVE',45,'NATIVE_STALLED'),('LOCAL',60,'PROGRESS_STALLED'),('ATTACHING',90,'PROGRESS_STALLED')]:
            tick=[0.];w=Watchdog(clock=lambda:tick[0]);w.observe(dict(kind='progress',stage=stage,tick=0))
            tick[0]=seconds;self.assertIsNone(w.check())
            tick[0]+=.01;self.assertEqual(w.check(),reason)
        for packet,reason in [
            (dict(kind='progress',stage='LOCAL',tick=0,lifecycle='HALTED',reason='ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD'),'ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD'),
            (dict(kind='failure',reason='CONTROLLER_EXCEPTION'),'CONTROLLER_EXCEPTION'),
            (dict(kind='exit',reason='OPERATOR_STOPPED'),'OPERATOR_STOPPED'),
            (None,'INVALID_MONITOR_MESSAGE'),
            (dict(kind='progress',stage='NATIVE',tick=float('nan')),'INVALID_MONITOR_MESSAGE')]:
            w=Watchdog(clock=lambda:0);w.observe(packet);self.assertEqual(w.check(),reason)

    def test_expired_lease_eof_and_stop_withdraw_before_paced_send_and_claim(self):
        for mode in ('expired','eof','stop'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as path:
                h=Harness(path,1);pipe=PipeFixture()
                try:
                    s=Supervision(pipe,clock=h.clock.clock)
                    h.store.supervision_guard=s.require
                    command=h.adapter.envelope(h.ids(),'balance',{})
                    h.store.enqueue(command,h.store.peer)
                    if mode=='expired':h.clock.value=11
                    elif mode=='eof':pipe.eof=True
                    else:pipe.incoming.append(dict(action='stop'))
                    with self.assertRaises(SupervisionLost):h.store.claim(h.store.peer)
                    self.assertEqual(h.ea.calls,[])
                    with self.assertRaises(SupervisionLost):h.controller.step()
                    with self.assertRaises(SupervisionLost):h.store.dispatch_guard(command)
                finally:h.close()
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1);pipe=PipeFixture();s=Supervision(pipe,clock=h.clock.clock)
            try:
                h.store.supervision_guard=s.require;h.executor.last_start=0
                # A stop arriving during the pacing wait must prevent this send.
                def during_pacing(seconds):h.clock.sleep(seconds);pipe.incoming.append(dict(action='stop'))
                h.executor.sleep=during_pacing
                c=h.adapter.envelope(h.ids(),'balance',{})
                with self.assertRaises(SupervisionLost):h.executor.execute(c)
                self.assertEqual(h.ea.calls,[])
            finally:h.close()

    def test_real_controller_unknown_missing_and_rejected_outcomes_keep_running(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,3);pipe=PipeFixture()
            try:
                s=Supervision(pipe,replace(Limits(),lease=10000),clock=h.clock.clock)
                h.store.supervision_guard=s.require;h.executor.progress=s.progress
                h.ea.bid_modes[h.ea.rows[0]['trade_id']]='timeout'
                h.ea.bid_modes[h.ea.rows[1]['trade_id']]='reject'
                def missing_after_dispatch(c):
                    if c['operation']=='status_batch' and len(h.calls('bid'))==3:
                        h.ea.missing.add(h.ea.rows[2]['trade_id'])
                h.ea.on_request=missing_after_dispatch
                h.controller.run(steps=2,progress=s.state)
                self.assertEqual(h.controller.status()['lifecycle'],'RUNNING')
                self.assertEqual(len(h.calls('bid')),3,'uncertainty must not block unrelated dispatch or replay old work')
                self.assertTrue(h.controller.status()['potentially_untracked_effects'])
                w=Watchdog(clock=h.clock.clock)
                for packet in pipe.sent:w.observe(packet)
                self.assertIsNone(w.check())
            finally:h.close()

    def test_status_phase_tracks_management_to_acquisition_handoff_within_one_step(self):
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1);pipe=PipeFixture()
            try:
                h.controller.step()
                for row in h.ea.rows:row.update(trade_state='closed',bid_state='outbid',expires=-1,native_is_won=False)
                s=Supervision(pipe,replace(Limits(),lease=10000),clock=h.clock.clock)
                s.snapshot=lambda:dict(h.controller.journal.state(),members=h.controller.journal.members())
                h.store.supervision_guard=s.require;h.executor.progress=s.progress
                phases=[]
                def inspect(c):
                    packet=pipe.sent[-1]
                    self.assertEqual(packet['phase'],h.controller.journal.state()['phase'])
                    phases.append(packet['phase'])
                h.ea.on_request=inspect
                h.controller.run(steps=3,progress=s.state)
                order=[p for i,p in enumerate(phases) if i==0 or phases[i-1]!=p]
                self.assertEqual(order[:3],['MANAGING','MAINTENANCE','ACQUIRING'])
            finally:h.close()

    def supervise_fixture(self,path,mode):
        args=Namespace(database=str(Path(path)/'fixture/controller.sqlite'),fixture=str(Path(path)/'fixture'),mode=mode)
        Path(args.fixture).mkdir()
        output=io.StringIO()
        limits=replace(Limits(),startup=10,local=.4 if mode=='stall' else 3,native=3,lease=2,grace=.3 if mode=='stall' else 3,poll=.02)
        code=supervise(args,target=offline_worker,limits=limits,output=output)
        log=next(Path(path).glob('fixture/watchdog-runs/*/events.jsonl'))
        rows=[json.loads(line) for line in log.read_text().splitlines()]
        self.assertIn('STOPPED',output.getvalue());self.assertNotIn('STOP_FAILED',output.getvalue())
        self.assertEqual(rows[-1]['kind'],'STOPPED')
        return code,rows

    def test_real_supervisor_detects_crash_halt_and_stall_without_restarting(self):
        for mode,reason in [('crash','PROCESS_EXIT'),('halt','ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD'),('stall','PROGRESS_STALLED')]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as path:
                code,rows=self.supervise_fixture(path,mode)
                self.assertEqual(code,1)
                self.assertEqual(rows[-1]['reason'],reason)
                self.assertEqual(rows[-1]['forced'],mode=='stall')
                self.assertEqual(sum(r['kind']=='STARTED' for r in rows),1)
                if mode=='crash':self.assertEqual(rows[-1]['exit_code'],73)

    def test_real_supervisor_ordinary_unknown_and_rejection_do_not_stop_worker(self):
        with tempfile.TemporaryDirectory() as path:
            code,rows=self.supervise_fixture(path,'ordinary')
            self.assertEqual(code,0)
            exits=[r['message'] for r in rows if r['kind']=='WORKER' and r['message']['kind']=='exit']
            self.assertEqual(exits[0]['attempts'],['UNKNOWN','REJECTED'])
            self.assertEqual(rows[-1]['reason'],'OPERATOR_STOPPED');self.assertFalse(rows[-1]['forced'])

    def test_real_supervisor_death_revokes_child_permission_without_a_stop_message(self):
        with tempfile.TemporaryDirectory() as path:
            p=subprocess.run([sys.executable,__file__,'orphan-parent',path],cwd=ROOT,capture_output=True,
                             encoding='utf-8',errors='replace',timeout=15)
            self.assertEqual(p.returncode,74,p.stdout+p.stderr)
            result=Path(path,'orphan-result.json');deadline=time.monotonic()+8
            value=None
            while time.monotonic()<deadline:
                try:value=json.loads(result.read_text());break
                except (FileNotFoundError,json.JSONDecodeError):time.sleep(.02)
            self.assertEqual(value,dict(reason='SUPERVISION_LOST',dispatches=0))

    def test_cli_run_uses_supervisor_and_retains_sanitized_fatal_diagnostic(self):
        with tempfile.TemporaryDirectory() as path:
            path=Path(path);context=path/'public-context.json';context.write_text('{}')
            # Scope validation fails before service construction/attachment.
            p=subprocess.run([sys.executable,'-m','fc_access.controller_v1','run',
                '--database',str(path/'controller.sqlite'),'--cache',str(path/'quotes.sqlite'),
                '--context',str(context),'--port','49152'],cwd=ROOT,capture_output=True,
                encoding='utf-8',errors='replace',timeout=15)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr);self.assertIn('STOPPED',p.stdout)
            self.assertFalse((path/'controller.sqlite').exists(),'invalid context must not start the service')
            rows=[json.loads(line) for line in next(path.glob('watchdog-runs/*/events.jsonl')).read_text().splitlines()]
            failure=next(r['message'] for r in rows if r['kind']=='WORKER' and r['message']['kind']=='failure')
            self.assertEqual(failure['exception'],'ValueError');self.assertTrue(failure['frames'])
            self.assertEqual(rows[-1]['reason'],'CONTROLLER_EXCEPTION')
            self.assertEqual(sum(r['kind']=='STARTED' for r in rows),1)

    def test_worker_never_logs_arbitrary_exception_text_or_locals(self):
        from fc_access.controller_v1.watchdog import worker
        pipe=PipeFixture();pipe.close=lambda:None
        with patch('fc_access.controller_v1.__main__.run_controller',side_effect=RuntimeError('SECRET_CANARY')):
            with self.assertRaises(SystemExit) as error:worker(pipe,{},Limits())
        self.assertEqual(error.exception.code,1)
        self.assertNotIn('SECRET_CANARY',json.dumps(pipe.sent))
        self.assertEqual(pipe.sent[-1]['exception'],'RuntimeError');self.assertTrue(pipe.sent[-1]['frames'])

    def test_lost_status_output_still_stops_and_joins_the_worker(self):
        class BrokenOutput(io.StringIO):
            def write(self,value):
                if '\r' in value:raise BrokenPipeError('fixture_terminal_closed')
                return super().write(value)
        with tempfile.TemporaryDirectory() as path:
            root=Path(path);fixture=root/'fixture';fixture.mkdir()
            args=Namespace(database=str(fixture/'controller.sqlite'),fixture=str(fixture),mode='stall')
            limits=replace(Limits(),startup=10,local=10,lease=2,grace=.2,poll=.02)
            self.assertEqual(supervise(args,target=offline_worker,limits=limits,output=BrokenOutput()),1)
            rows=[json.loads(line) for line in next(root.glob('fixture/watchdog-runs/*/events.jsonl')).read_text().splitlines()]
            self.assertEqual(rows[-1]['kind'],'STOPPED');self.assertEqual(rows[-1]['reason'],'WATCHDOG_OUTPUT_FAILED')

    def test_ctrl_c_cooperatively_drains_worker_and_preserves_operator_stop(self):
        with tempfile.TemporaryDirectory() as path:
            fixture=Path(path)/'fixture';fixture.mkdir()
            args=Namespace(database=str(fixture/'controller.sqlite'),fixture=str(fixture),mode='cooperative')
            check=Watchdog.check
            def interrupt_after_start(monitor):
                if monitor.latest.get('lifecycle')=='RUNNING':raise KeyboardInterrupt
                return check(monitor)
            limits=replace(Limits(),startup=10,lease=2,grace=2,poll=.02)
            with patch.object(Watchdog,'check',interrupt_after_start):
                code=supervise(args,target=offline_worker,limits=limits,output=io.StringIO())
            rows=[json.loads(line) for line in next(fixture.glob('watchdog-runs/*/events.jsonl')).read_text().splitlines()]
            self.assertEqual(code,0);self.assertFalse(rows[-1]['forced'])
            self.assertEqual(rows[-1]['reason'],'OPERATOR_STOP');self.assertEqual(rows[-1]['exit_code'],0)

    def test_watchdog_log_failure_still_withdraws_and_joins_worker(self):
        class FailingLog:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def write(self,value):raise OSError('fixture_disk_full')
        with tempfile.TemporaryDirectory() as path:
            fixture=Path(path)/'fixture';fixture.mkdir()
            args=Namespace(database=str(fixture/'controller.sqlite'),fixture=str(fixture),mode='cooperative')
            real_open=Path.open
            def open_log(p,*args,**kw):
                if p.name=='events.jsonl':return FailingLog()
                return real_open(p,*args,**kw)
            # The join itself is observable: no test fixture child remains alive.
            before={p.pid for p in multiprocessing.active_children()}
            output=io.StringIO()
            with patch.object(Path,'open',open_log):
                code=supervise(args,target=offline_worker,limits=replace(Limits(),grace=2),output=output)
            self.assertEqual(code,1);self.assertIn('STOPPED',output.getvalue())
            self.assertIn('WATCHDOG_LOG_FAILED',output.getvalue())
            self.assertEqual({p.pid for p in multiprocessing.active_children()},before)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='orphan-parent':orphan_parent(sys.argv[2])
    else:unittest.main(verbosity=2)
