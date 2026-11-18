"""Minimal process supervisor. Local IPC only; never sends an EA request."""
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import threading
import time
import traceback
from .semantic import SemanticHealth, native_summary


@dataclass(frozen=True)
class Limits:
    startup: float = 90
    native: float = 45
    local: float = 60
    lease: float = 10
    grace: float = 35
    poll: float = .5


def runtime_failure(error):
    """Finite local diagnostic projection; never exception values or paths."""
    kind=next((t.__name__ for t in (PermissionError,OSError,ValueError,TypeError) if isinstance(error,t)),'Error')
    value=dict(exception=kind)
    for name in ('errno','winerror'):
        code=getattr(error,name,None)
        if type(code) is int and 0<=code<=65535:value[name]=code
    for name,allowed in (('runtime_io_stage',{'write','replace','cleanup'}),('runtime_target',{'run_state','current_state'})):
        projected=getattr(error,name,None)
        if type(projected) is str and projected in allowed:value[name]=projected
    return value


class SupervisionLost(ValueError):
    pass


class Supervision:
    """Child-side lease. Checked at step, paced dispatch, enqueue and claim.

    There is no background heartbeat pretending the policy thread is progressing.
    The parent supplies leases; the policy thread reports actual work boundaries.
    """
    def __init__(self, connection, limits=Limits(), *, clock=time.monotonic):
        self.connection,self.limits,self.clock=connection,limits,clock
        self.last_lease=clock()
        self.reason=None
        self.lock=threading.RLock()
        self.snapshot=None

    def result(self, command, response, diagnostic_records=None):
        self.report('native_result',**native_summary(command,response),diagnostic_records=diagnostic_records)

    def policy_result(self, **fields):
        self.report('batch_result',**fields)

    def failure(self, exception_type):
        self.reason='RESULT_MONITOR_FAILED'
        self.report('failure',reason=self.reason,exception=exception_type)

    def require(self):
        with self.lock:
            try:
                while self.connection.poll():
                    message=self.connection.recv()
                    if message.get('action')=='stop':self.reason='WATCHDOG_STOP'
                    elif message.get('action')=='lease':self.last_lease=message['tick']
                    else:self.reason='SUPERVISION_LOST'
            except (EOFError,OSError):self.reason='SUPERVISION_LOST'
            if not 0<=self.clock()-self.last_lease<=self.limits.lease:
                self.reason='SUPERVISION_LOST'
            if self.reason:raise SupervisionLost(self.reason)

    def report(self, kind, **fields):
        with self.lock:
            try:self.connection.send(dict(kind=kind,tick=self.clock(),**fields))
            except (OSError,EOFError):raise SupervisionLost('SUPERVISION_LOST') from None

    def progress(self, stage, operation=None):
        self.require()
        fields=self.state_fields(self.snapshot()) if self.snapshot else {}
        self.report('progress',stage=stage,operation=operation,**fields)

    @staticmethod
    def state_fields(state):
        return dict(phase=state['phase'],lifecycle=state['lifecycle'],
                    reason=state['reason'],managed=len(state['members']))

    def state(self, state):
        self.require()
        self.report('progress',stage='LOCAL',operation=None,**self.state_fields(state))


@contextmanager
def fault_trace(path):
    """Native failure stacks only: no locals, exception values or memory dumps."""
    import faulthandler
    previous=faulthandler.is_enabled()
    with Path(path).open('x',encoding='utf-8') as stream:
        faulthandler.enable(file=stream,all_threads=True)
        try:yield stream
        finally:
            faulthandler.disable()
            if previous:faulthandler.enable(all_threads=True)


def worker(connection, arguments, limits):
    path=arguments.pop('_fault_trace',None)
    if path is None:return worker_body(connection,arguments,limits)
    with fault_trace(path):return worker_body(connection,arguments,limits)


def worker_body(connection, arguments, limits):
    # The visible supervisor handles Ctrl+C and withdraws the worker's lease.
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    supervision=Supervision(connection,limits)
    try:
        supervision.progress('STARTING')
        from argparse import Namespace
        from .__main__ import run_controller
        state=run_controller(Namespace(**arguments),supervision)
        supervision.report('exit',lifecycle=state['lifecycle'],reason=state['reason'])
    except SupervisionLost:
        try:supervision.report('exit',lifecycle='STOPPED',reason=supervision.reason or 'SUPERVISION_LOST')
        except SupervisionLost:pass
        raise SystemExit(0 if supervision.reason=='WATCHDOG_STOP' else 1)
    except BaseException as error:
        # Keep stack locations for diagnosis, never arbitrary exception values,
        # frame locals, credentials or native response bodies.
        try:
            supervision.report('failure',exception=type(error).__name__,
                reason=supervision.reason or 'CONTROLLER_EXCEPTION',
                frames=[dict(file=f.filename,line=f.lineno,function=f.name)
                        for f in traceback.extract_tb(error.__traceback__)])
        except SupervisionLost:pass
        raise SystemExit(1)
    finally:connection.close()


class Watchdog:
    """Progress deadlines plus optional semantic policy over actual outcomes."""
    def __init__(self, limits=Limits(), *, clock=time.monotonic, semantic=None):
        self.limits,self.clock=limits,clock
        self.latest=dict(stage='STARTING',operation=None,tick=clock())
        self.reason=None
        self.semantic=semantic

    def observe(self, message):
        if self.reason:return
        if not isinstance(message,dict) or message.get('kind') not in {'progress','failure','exit','native_result','batch_result'}:
            self.reason='INVALID_MONITOR_MESSAGE';return
        kind=message['kind']
        if kind in {'native_result','batch_result'}:
            if self.semantic:self.semantic.observe(message)
            return
        if kind=='failure':
            self.reason=message.get('reason') or 'CONTROLLER_EXCEPTION'
        elif kind=='exit':
            self.reason=message.get('reason') or 'CONTROLLER_EXIT'
        elif (message.get('stage') not in {'STARTING','ATTACHING','NATIVE','LOCAL'}
              or type(message.get('tick')) not in (int,float) or not math.isfinite(message['tick'])):
            self.reason='INVALID_MONITOR_MESSAGE'
        else:
            self.latest.update(message)
            if message.get('lifecycle') in {'HALTED','STOPPED','PAUSED'}:
                self.reason=message.get('reason') or 'CONTROLLER_'+message['lifecycle']

    def check(self):
        if self.reason:return self.reason
        if self.semantic:
            reason=self.semantic.check()
            if reason:return reason
        age=self.clock()-self.latest['tick']
        limit={'STARTING':self.limits.startup,'ATTACHING':self.limits.startup,
               'NATIVE':self.limits.native,'LOCAL':self.limits.local}[self.latest['stage']]
        if not 0<=age<=limit:
            return 'NATIVE_STALLED' if self.latest['stage']=='NATIVE' else 'PROGRESS_STALLED'
        return None

    def line(self, state='RUNNING', reason=None):
        v=self.latest
        # Only small enumerated labels reach the terminal; full evidence stays local.
        def label(value):
            return str(value) if re.fullmatch(r'[A-Za-z0-9_]{1,100}',str(value)) else '-'
        if state=='RUNNING' and 'lifecycle' not in v:state='STARTING'
        return (f"{state} | {label(v.get('phase'))} | {label(v.get('operation') or v['stage'])}"
                f" | managed={v.get('managed',0)} | "
                + (label(reason) if reason else f"stage {max(0,self.clock()-v['tick']):.0f}s"))


def supervise(arguments, *, target=worker, limits=Limits(), output=None, runtime=None):
    """Explicit run only. One worker, one status line, one retained event log.

    No restart, notification service, web dashboard, account probe or trading
    policy lives here. Tests inject a separate offline worker, never CLI flags.
    """
    output=output or sys.stdout
    root=Path(arguments.database).resolve().parent/'watchdog-runs'
    root.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    directory=Path(tempfile.mkdtemp(prefix=stamp,dir=root))
    log_path=directory/'events.jsonl'
    print(f'Watchdog log: {log_path}',file=output,flush=True)
    ctx=multiprocessing.get_context('spawn')
    parent,child=ctx.Pipe()
    worker_arguments=dict(vars(arguments),_fault_trace=str(directory/'python-fault.txt'))
    process=ctx.Process(target=target,args=(child,worker_arguments,limits),name='fc-controller-v1')
    monitor=Watchdog(limits,semantic=SemanticHealth())
    reason=None;forced=False;started=False;width=0;log_failed=False;output_failed=False;exit_code=None;alive=False
    runtime_failed=False

    def publish(state,reason=None,*,force=False):
        nonlocal runtime_failed
        if runtime:
            try:runtime.publish(monitor,state,reason,force=force)
            except (OSError,ValueError,TypeError) as error:
                if not runtime_failed:record('RUNTIME_PUBLISH_FAILED',state=state,**runtime_failure(error))
                runtime_failed=True

    def display(state, reason=None):
        nonlocal width,output_failed
        line=monitor.line(state,reason);width=max(width,len(line))
        try:print('\r'+line.ljust(width),end='',file=output,flush=True)
        except OSError:output_failed=True

    with log_path.open('x',encoding='utf-8') as log:
        def record(kind, **fields):
            nonlocal log_failed
            try:
                log.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**fields))+'\n')
                log.flush()
                if kind in {'STARTED','STOP_REQUESTED','STOPPED','STOP_FAILED'}:os.fsync(log.fileno())
            except OSError:log_failed=True

        def drain():
            try:
                while parent.poll():
                    message=parent.recv()
                    record('WORKER',message=message);monitor.observe(message)
            except (EOFError,OSError):return False
            return True

        try:
            parent.send(dict(action='lease',tick=time.monotonic()))
            process.start();started=True;child.close()
            if runtime:runtime.bind(process.pid,log_path)
            record('STARTED',pid=process.pid,limits=vars(limits),generation=runtime.generation if runtime else None)
            while True:
                connected=drain()
                reason=('WATCHDOG_LOG_FAILED' if log_failed else 'WATCHDOG_OUTPUT_FAILED' if output_failed else 'RUNTIME_STATE_FAILED' if runtime_failed else monitor.check())
                if runtime:
                    reason=reason or runtime.stop_reason()
                    publish('RUNNING' if monitor.latest.get('lifecycle')=='RUNNING' else 'STARTING',reason)
                    if runtime_failed:reason='RUNTIME_STATE_FAILED'
                if reason:break
                if not connected or not process.is_alive():
                    reason='PROCESS_EXIT';break
                try:parent.send(dict(action='lease',tick=time.monotonic()))
                except OSError:
                    # The worker can exit between the drain and this send.
                    # Keep its final diagnostic instead of blaming the supervisor.
                    drain()
                    reason=monitor.check() or 'PROCESS_EXIT';break
                display('RUNNING')
                time.sleep(limits.poll)
        except KeyboardInterrupt:reason='OPERATOR_STOP'
        except BaseException as error:
            reason='SUPERVISOR_EXCEPTION'
            record('EXCEPTION',exception=type(error).__name__)
        finally:
            if started:
                display('STOPPING',reason)
                record('STOP_REQUESTED',reason=reason)
                publish('STOPPING',reason,force=True)
                try:parent.send(dict(action='stop'))
                except (OSError,EOFError):pass
                # Stop takes effect at the dispatch/claim guards. Let the one
                # already-issued request return; killing cannot undo an EA write.
                process.join(limits.grace)
                if process.is_alive():
                    forced=True;process.terminate();process.join(5)
                if process.is_alive():process.kill();process.join(5)
                drain()
                alive=process.is_alive()
                exit_code=process.exitcode
                record('STOPPED' if not alive else 'STOP_FAILED',reason=reason,
                       exit_code=exit_code,forced=forced)
                publish('STOPPED' if not alive else 'STOP_FAILED',reason,force=True)
                display('STOPPED' if not alive else 'STOP_FAILED',reason)
            else:
                record('STOPPED',reason=reason,worker_started=False)
                publish('STOPPED',reason,force=True)
                display('STOPPED',reason)
            try:print(file=output,flush=True)
            except OSError:pass
            parent.close();child.close()
            if started and not process.is_alive():process.close()
    return 0 if (not log_failed and not output_failed and not runtime_failed and not forced and not alive and exit_code==0 and
                 reason in {'OPERATOR_STOP','OPERATOR_STOPPED','OPERATOR_PAUSED','OPERATIONAL_STOP'}) else 1
