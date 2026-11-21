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
    # Local state publication may fail transiently (Windows sharing with an
    # ordinary reader). Trading safety does not depend on it: the semantic
    # monitor runs in this process. Stop only after a sustained outage.
    publish_tolerance: float = 10
    # Document recovery anti-loop limits only (see supervise). EA denials are
    # not respected as a reason to stop trading (account-risk policy); these only
    # stop a runtime that would otherwise just reload without ever trading.
    recovery_spacing: float = 60
    recovery_per_hour: int = 6
    # From recovery start until the fresh worker's first native success.
    recovery_window: float = 240


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


# A wave restart needs a denial this recent: a long hold after one 461 is no wave.
WAVE_RECENT_SECONDS=600


def supervise(arguments, *, target=worker, limits=Limits(), output=None, runtime=None,
              denial_measure=None, startup_refresh=None, auth_measure=None,
              wave_refresh_after=0, wave_recent=WAVE_RECENT_SECONDS):
    """Explicit run only. One worker at a time, one status line, one event log.

    No notification service, web dashboard, account probe or trading policy
    lives here. When the worker stops on the bid-denial signature, the
    interchangeable ``denial_measure`` (see measures.py; default no-op) decides
    what is attempted. An inactive measure only logs the signature and the
    runtime stops as before. An active one is attempted after the worker stops
    cooperatively; on success a fresh worker starts with a higher owner epoch
    and never replays uncertain work. ``startup_refresh``, an active measure,
    is attempted once before the first worker. ``auth_measure``, when active,
    is attempted the same way after a PERSISTENT_AUTH_FAILURE stop. A measure
    with ``tolerate_denials`` keeps bidding through 461 denials instead.
    With ``wave_refresh_after`` > 0, a 461 wave (native bids denied for that
    many seconds with no accepted bid, the latest denial recent) stops the
    runtime with DENIAL_WAVE_RESTART; the local monitor's watcher then starts a
    whole new generation behind a page refresh (local_monitor.restart_after_wave).
    Each fresh generation starts a new wave clock, so a lasting wave restarts
    again after the same time. An accepted bid ends the wave.
    Tests inject offline workers.
    """
    from .measures import NoOpMeasure
    denial_measure=denial_measure or NoOpMeasure()
    tolerant=bool(getattr(denial_measure,'tolerate_denials',False))
    output=output or sys.stdout
    root=Path(arguments.database).resolve().parent/'watchdog-runs'
    root.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    directory=Path(tempfile.mkdtemp(prefix=stamp,dir=root))
    log_path=directory/'events.jsonl'
    print(f'Watchdog log: {log_path}',file=output,flush=True)
    ctx=multiprocessing.get_context('spawn')
    parent=child=process=None
    monitor=Watchdog(limits,semantic=SemanticHealth(tolerate_denials=tolerant))
    reason=None;forced=False;started=False;width=0;log_failed=False;output_failed=False;exit_code=None;alive=False
    runtime_failed=False;process_open=False
    published_at=time.monotonic();publish_failures=0
    workers=0;recoveries=[]
    # Spans worker restarts within this runtime.
    wave=dict(since=None,last=None,denied=0)
    if runtime is not None:runtime.recovery=None

    def publish(state,reason=None,*,force=False,strict=None):
        nonlocal runtime_failed,published_at,publish_failures
        if not runtime:return
        strict=force if strict is None else strict
        try:written=runtime.publish(monitor,state,reason,force=force)
        except (OSError,ValueError,TypeError) as error:
            # Record the first failure of each outage with its finite identity.
            if not publish_failures and not runtime_failed:record('RUNTIME_PUBLISH_FAILED',state=state,**runtime_failure(error))
            publish_failures+=1
            outage=time.monotonic()-published_at
            if strict or not 0<=outage<=limits.publish_tolerance:runtime_failed=True
        else:
            if written is False:return  # throttled; nothing new was written
            if publish_failures:
                record('RUNTIME_PUBLISH_RECOVERED',failures=publish_failures,outage_seconds=round(time.monotonic()-published_at,3))
            published_at=time.monotonic();publish_failures=0

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
                if kind in {'STARTED','STOP_REQUESTED','STOPPED','STOP_FAILED','WORKER_RESTARTED','DOCUMENT_RECOVERY_STARTED'}:os.fsync(log.fileno())
            except OSError:log_failed=True

        def drain():
            try:
                while parent.poll():
                    message=parent.recv()
                    record('WORKER',message=message);monitor.observe(message);track(message)
            except (EOFError,OSError):return False
            return True

        def track(message):
            if (not isinstance(message,dict) or message.get('kind')!='native_result' or message.get('local')
                    or message.get('operation')!='bid'):return
            now=time.monotonic()
            if message.get('success') is True:
                if wave['since'] is not None:
                    record('DENIAL_WAVE_CLEARED',seconds=round(now-wave['since'],1),denied=wave['denied'])
                wave.update(since=None,last=None,denied=0)
            elif message.get('wire_statuses')==[461]:
                if wave['since'] is None:wave['since']=now
                wave['last']=now;wave['denied']+=1

        def wave_due():
            if not wave_refresh_after>0 or wave['since'] is None or runtime.recovery:return None
            now=time.monotonic();seconds=now-wave['since']
            # A hold with no bids is not a wave; only restart while EA still denies.
            if seconds<wave_refresh_after or now-wave['last']>wave_recent:return None
            record('WAVE_RESTART',seconds=round(seconds,1),denied=wave['denied'])
            return 'DENIAL_WAVE_RESTART'

        def local_reason():
            return ('WATCHDOG_LOG_FAILED' if log_failed else 'WATCHDOG_OUTPUT_FAILED' if output_failed else
                    'RUNTIME_STATE_FAILED' if runtime_failed else None)

        def spawn():
            nonlocal parent,child,process,monitor,started,workers,process_open
            parent,child=ctx.Pipe()
            trace=directory/('python-fault.txt' if not workers else f'python-fault-{workers}.txt')
            process=ctx.Process(target=target,args=(child,dict(vars(arguments),_fault_trace=str(trace)),limits),name='fc-controller-v1')
            # A fresh worker gets fresh semantic streaks; recovery stays published
            # until it proves a new native success.
            monitor=Watchdog(limits,semantic=SemanticHealth(tolerate_denials=tolerant))
            parent.send(dict(action='lease',tick=time.monotonic()))
            process.start();started=True;process_open=True;child.close()
            if runtime:runtime.bind(process.pid,log_path)
            if not workers:record('STARTED',pid=process.pid,limits=vars(limits),generation=runtime.generation if runtime else None)
            else:record('WORKER_RESTARTED',pid=process.pid,worker=workers,generation=runtime.generation if runtime else None,mono=time.monotonic())
            workers+=1

        def watch():
            while True:
                connected=drain()
                if runtime and runtime.recovery and monitor.semantic.native_successes>0:
                    record('DOCUMENT_RECOVERY_COMPLETED',attempt=runtime.recovery['attempt'],native_successes=monitor.semantic.native_successes,mono=time.monotonic())
                    runtime.recovery=None
                reason=local_reason() or monitor.check()
                if not reason and runtime and runtime.recovery and not 0<=time.monotonic()-runtime.recovery['started_mono']<=limits.recovery_window:
                    reason='DOCUMENT_RECOVERY_TIMEOUT'
                cause=None
                if runtime:
                    reason=reason or runtime.stop_reason() or wave_due()
                    cause=recoverable(reason)
                    # Publish recovery before stopping the worker so a health
                    # check never observes the recoverable fault as a stop.
                    if cause:begin(*cause)
                    publish('RUNNING' if monitor.latest.get('lifecycle')=='RUNNING' or runtime.recovery else 'STARTING',
                            None if cause else reason,force=bool(cause),strict=False)
                    if runtime_failed:reason='RUNTIME_STATE_FAILED';cause=None
                if reason:return reason,cause
                if not connected or not process.is_alive():return 'PROCESS_EXIT',None
                try:parent.send(dict(action='lease',tick=time.monotonic()))
                except OSError:
                    # The worker can exit between the drain and this send.
                    # Keep its final diagnostic instead of blaming the supervisor.
                    drain()
                    return monitor.check() or 'PROCESS_EXIT',None
                display('RUNNING')
                time.sleep(limits.poll)

        def stop_worker(reason,final):
            nonlocal forced,alive,exit_code,process_open
            display('STOPPING',reason)
            record('STOP_REQUESTED' if final else 'WORKER_STOP_REQUESTED',reason=reason,**({} if final else dict(mono=time.monotonic())))
            if final:publish('STOPPING',reason,force=True)
            try:parent.send(dict(action='stop'))
            except (OSError,EOFError):pass
            # Stop takes effect at the dispatch/claim guards. Let the one
            # already-issued request return; killing cannot undo an EA write.
            process.join(limits.grace)
            if process.is_alive():
                forced=True;process.terminate();process.join(5)
            if process.is_alive():process.kill();process.join(5)
            drain()
            alive=process.is_alive();exit_code=process.exitcode
            if not final:record('WORKER_STOPPED' if not alive else 'STOP_FAILED',reason=reason,exit_code=exit_code,forced=forced,mono=time.monotonic())
            parent.close()
            if not alive:process.close();process_open=False

        def recoverable(reason):
            """(cause, measure) when an active measure should be attempted."""
            if runtime is None:return None
            if reason=='PERSISTENT_AUTH_FAILURE' and auth_measure is not None and auth_measure.active:
                cause,measure='AUTH_FAILURE',auth_measure
            elif reason=='PERSISTENT_WRITE_FAILURE':
                cause,measure=monitor.semantic.recoverable(),denial_measure
                if cause is None:return None
                if not measure.active:
                    record('WRITE_DENIAL_SIGNATURE',cause=cause,measure=measure.name);return None
            else:return None
            now=time.monotonic()
            if sum(1 for t in recoveries if 0<=now-t<3600)>=limits.recovery_per_hour:refused='RECOVERY_BUDGET_EXHAUSTED'
            elif recoveries and now-recoveries[-1]<limits.recovery_spacing:refused='DENIAL_PERSISTS_AFTER_RECOVERY'
            else:return cause,measure
            record('DOCUMENT_RECOVERY_REFUSED',cause=cause,refused=refused,recoveries=len(recoveries),measure=measure.name)
            return None

        def begin(cause,measure,*,initial=False):
            recoveries.append(time.monotonic())
            runtime.recovery=dict(started_mono=recoveries[-1],attempt=len(recoveries),cause=cause,initial=initial)
            record('DOCUMENT_RECOVERY_STARTED',attempt=len(recoveries),cause=cause,initial=initial,
                   measure=measure.name,mono=recoveries[-1])
            return measure

        def recover(measure):
            """Attempts the begun measure while publishing it; returns a stop reason or None."""
            cancel=threading.Event();box={}
            def body():
                try:box['result']=measure.attempt(cancel.is_set)
                except Exception as error:box['result']=dict(outcome='FAILED',reason='RECOVERY_EXCEPTION',exception=type(error).__name__,steps=[])
            thread=threading.Thread(target=body,name='fc-document-recovery',daemon=True);thread.start()
            stop=None
            try:
                while thread.is_alive():
                    stop=stop or local_reason() or runtime.stop_reason()
                    if stop:cancel.set()
                    publish('RUNNING',stop)
                    display('RECOVERING',stop)
                    thread.join(limits.poll)
            except KeyboardInterrupt:
                cancel.set();thread.join(60);stop='OPERATOR_STOP'
            result=box.get('result') if type(box.get('result')) is dict else dict(outcome='FAILED',reason='RECOVERY_INCOMPLETE',steps=[])
            outcome=result.get('outcome') if result.get('outcome') in {'READY','CHALLENGE','FAILED','CANCELLED'} else 'FAILED'
            record('DOCUMENT_RECOVERY_RESULT',attempt=len(recoveries),outcome=outcome,mono=time.monotonic(),
                   reason=result.get('reason') if type(result.get('reason')) is str else None,
                   steps=result.get('steps') if type(result.get('steps')) is list else [])
            if stop:return stop
            if outcome=='READY':return None
            return 'USER_SECURITY_CHALLENGE' if outcome=='CHALLENGE' else 'DOCUMENT_RECOVERY_FAILED'

        try:
            if startup_refresh is not None and runtime is not None:
                reason=recover(begin('STARTUP_REFRESH',startup_refresh,initial=True))
            if reason is None:spawn()
            while reason is None:
                reason,cause=watch()
                if cause is None:break
                stop_worker(reason,final=False)
                if alive:break
                reason=recover(cause[1])
                if reason is None:spawn()
        except KeyboardInterrupt:reason='OPERATOR_STOP'
        except BaseException as error:
            reason='SUPERVISOR_EXCEPTION'
            record('EXCEPTION',exception=type(error).__name__)
        finally:
            if runtime is not None:runtime.recovery=None
            if process_open:
                stop_worker(reason,final=True)
            elif started:
                # The last worker already stopped for recovery that did not succeed.
                display('STOPPING',reason)
                record('STOP_REQUESTED',reason=reason)
                publish('STOPPING',reason,force=True)
            if started:
                record('STOPPED' if not alive else 'STOP_FAILED',reason=reason,
                       exit_code=exit_code,forced=forced)
            else:
                record('STOPPED',reason=reason,worker_started=False)
            publish('STOPPED' if not alive else 'STOP_FAILED',reason,force=True)
            display('STOPPED' if not alive else 'STOP_FAILED',reason)
            try:print(file=output,flush=True)
            except OSError:pass
            if parent is not None:parent.close()
            if child is not None:child.close()
    return 0 if (not log_failed and not output_failed and not runtime_failed and not forced and not alive and
                 started and exit_code==0 and
                 reason in {'OPERATOR_STOP','OPERATOR_STOPPED','OPERATOR_PAUSED','OPERATIONAL_STOP','DENIAL_WAVE_RESTART'}) else 1
