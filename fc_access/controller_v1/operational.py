"""Owned watchdog service and bounded local health/stop. Never invokes EA itself."""
import argparse
from contextlib import ExitStack,contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import secrets
import sys
import time

from fc_access.actors_v1.locking import process_lock
from .semantic import SemanticLimits
from .watchdog import Limits, supervise


def identity(pid):
    """Live process creation identity, not PID-only liveness or termination."""
    if type(pid) is not int or pid <= 0:return None
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        handle=kernel.OpenProcess(0x1000|0x100000,False,pid)
        if not handle:return None
        try:
            if kernel.WaitForSingleObject(handle,0)!=258:return None
            created,exited,system,user=(wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(system),ctypes.byref(user)):return None
            size=wintypes.DWORD(32768);image=ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(handle,0,image,ctypes.byref(size)):return None
            return dict(pid=pid,created=(created.dwHighDateTime<<32)|created.dwLowDateTime,image=image.value)
        finally:kernel.CloseHandle(handle)
    try:
        # Linux fixture/portability path. Start ticks distinguish PID reuse.
        stat=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()
        if stat[0]=='Z':return None
        return dict(pid=pid,created=int(stat[19]),image=os.readlink(f'/proc/{pid}/exe'))
    except (OSError,ValueError,IndexError):return None


def same_process(value):
    return type(value) is dict and identity(value.get('pid'))==value


def replace_snapshot(temporary,path):
    if os.name!='nt':os.replace(temporary,path);return
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.ReplaceFileW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,wintypes.LPVOID,wintypes.LPVOID]
    kernel.ReplaceFileW.restype=wintypes.BOOL
    # ReplaceFile preserves attributes/ACLs and supports existing shared readers.
    # https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-replacefilew
    if kernel.ReplaceFileW(str(Path(path).resolve()),str(Path(temporary).resolve()),None,0,None,None):return
    error=ctypes.get_last_error()
    if error==2 and not Path(path).exists():os.replace(temporary,path);return
    raise ctypes.WinError(error)


def atomic(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    phase='write'
    try:
        with temporary.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(value,stream,sort_keys=True,allow_nan=False);stream.write('\n')
            stream.flush();os.fsync(stream.fileno())
        # An ordinary Windows reader may temporarily deny delete sharing. Only
        # retry this local rename, boundedly; account requests are never retried.
        phase='replace';deadline=time.monotonic()+1
        while True:
            try:replace_snapshot(temporary,path);break
            except OSError as error:
                if os.name!='nt' or getattr(error,'winerror',None) not in {5,32,33} or time.monotonic()>=deadline:raise
                time.sleep(.01)
    except (OSError,ValueError,TypeError) as error:
        error.runtime_io_stage=phase
        raise
    finally:
        try:
            if temporary.exists():temporary.unlink()
        except OSError as error:
            error.runtime_io_stage='cleanup'
            raise


@contextmanager
def state_stream(path):
    """Read a complete atomic snapshot without blocking Windows replacement."""
    if os.name!='nt':
        with Path(path).open(encoding='utf-8') as stream:yield stream
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(Path(path).resolve()),0x80000000,0x7,None,3,0x80,None)
    if handle==wintypes.HANDLE(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:descriptor=msvcrt.open_osfhandle(int(handle),os.O_RDONLY|os.O_BINARY)
    except BaseException:kernel.CloseHandle(handle);raise
    with os.fdopen(descriptor,'r',encoding='utf-8') as stream:yield stream


def read(path):
    with state_stream(path) as stream:
        value=stream.read(65537)
    if len(value)>65536:raise ValueError('oversize_runtime_record')
    return json.loads(value)


def held(directory):
    try:
        with process_lock(Path(directory)/'owner.lock'):pass
        return False
    except ValueError:return True


def token(value):
    if type(value) is not str or len(value)!=32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('invalid_generation')
    return value


class Runtime:
    """One exclusive parent. Separate immutable run directory consumes each ID."""
    def __init__(self,directory,task,generation,*,clock=time.monotonic):
        self.directory=Path(directory).resolve();self.task=task;self.generation=token(generation);self.clock=clock
        self.stack=ExitStack();self.child=None;self.last_publish=None;self.recovery=None

    def __enter__(self):
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            self.stack.enter_context(process_lock(self.directory/'owner.lock'))
            self.run=self.directory/'runs'/self.generation
            self.run.mkdir(parents=True,exist_ok=False)
            self.supervisor=identity(os.getpid())
            if self.supervisor is None:raise ValueError('process_identity_unavailable')
            self.started=self.clock();self.log=None
            self.publish(None,'STARTING',force=True)
            atomic(self.run/'launch.json',dict(task=self.task,generation=self.generation,
                supervisor=self.supervisor,started_mono=self.started,at=datetime.now(timezone.utc).isoformat()))
            return self
        except BaseException:
            self.stack.close();raise

    def __exit__(self,*args):self.stack.close()

    def bind(self,pid,log):
        self.child=identity(pid);self.log=str(Path(log).resolve())
        if self.child is None:raise ValueError('child_identity_unavailable')

    def stop_reason(self):
        path=self.run/'stop.json'
        if not path.exists():return None
        try:value=read(path)
        except (OSError,ValueError):return 'INVALID_OWNED_STOP_REQUEST'
        if value==dict(task=self.task,generation=self.generation,supervisor=self.supervisor):return 'OPERATIONAL_STOP'
        # A stale/foreign request is never authority to stop this runtime.
        return None

    def publish(self,monitor,state,reason=None,*,force=False):
        tick=self.clock()
        if not force and self.last_publish is not None and tick-self.last_publish<1:return False
        semantics=monitor.semantic.snapshot() if monitor else None
        latest=dict(monitor.latest) if monitor else dict(stage='STARTING',tick=tick)
        recovering=semantics and any(semantics.get(k,0)>0 for k in
            ('read_failures','write_failures','auth_failures','helper_failures','diagnostic_failures','missing_statuses','batch_failures','unconfirmed_attempts'))
        operational_state=(state if state!='RUNNING' else 'DOCUMENT_RECOVERY' if self.recovery else 'RECOVERING' if recovering else latest.get('phase','STARTING'))
        value=dict(schema=1,task=self.task,generation=self.generation,supervisor=self.supervisor,child=self.child,
            started_mono=self.started,published_mono=tick,at=datetime.now(timezone.utc).isoformat(),
            state=state,operational_state=operational_state,reason=reason,latest=latest,semantic=semantics,
            recovery=dict(self.recovery) if self.recovery else None,
            limits=vars(monitor.limits) if monitor else vars(Limits()),semantic_limits=vars(SemanticLimits()),log=self.log)
        # Keep generation-specific state as well as the restart-readable pointer.
        for target,path in (('run_state',self.run/'state.json'),('current_state',self.directory/'state.json')):
            try:atomic(path,value)
            except (OSError,ValueError,TypeError) as error:
                error.runtime_target=target
                raise
        # Throttle only after a complete publication, so a failed one is
        # retried on the supervisor's next poll rather than a second later.
        self.last_publish=tick
        return True


# The supervisor publishes about once a second and tolerates a bounded local
# publication outage (Limits.publish_tolerance, 10s). Health must not report a
# fault the supervisor itself still tolerates; a hung supervisor exceeds both.
STATE_FRESHNESS=15
# Mirrors Limits.recovery_window. A launch with refresh-on-start needs the
# scheduler's startup_seconds to be at least STARTUP_REFRESH_SECONDS.
RECOVERY_WINDOW=240
STARTUP_REFRESH_SECONDS=180


def read_state(directory,generation,*,deadline_seconds=2):
    """Restart-readable pointer, else this generation's identical run copy.

    Both are written by the same publication. A transient sharing denial on one
    file is not runtime failure; absence never fabricates a state.
    """
    directory=Path(directory);deadline=time.monotonic()+deadline_seconds
    while True:
        error=other=None
        for path in (directory/'state.json',directory/'runs'/generation/'state.json'):
            try:value=read(path)
            except (FileNotFoundError,PermissionError) as caught:error=error or caught;continue
            if type(value) is not dict:raise ValueError('invalid_runtime_state')
            if value.get('generation')==generation:return value
            # The pointer may still name an older generation right after launch.
            other=other or value
        if time.monotonic()>=deadline:
            if other is not None:return other
            raise error
        time.sleep(.05)


def read_pointer(directory,*,deadline_seconds=2):
    """The restart-readable pointer itself, retrying only transient denial.

    Unlike read_state this never substitutes a run copy, so callers still see a
    newer generation that replaced the pointer.
    """
    deadline=time.monotonic()+deadline_seconds
    while True:
        try:return read(Path(directory)/'state.json')
        except PermissionError:
            if time.monotonic()>=deadline:raise
        time.sleep(.05)


def evaluate(value,*,task,generation,now,owner_held,supervisor_alive,child_alive):
    """Pure fail-closed health policy, independently recomputing the thresholds."""
    def result(status,diagnostic):
        semantic=value.get('semantic') or {}
        return dict(status=status,generation=generation,diagnostic=diagnostic,evidence=[dict(
            state=value.get('operational_state'),native_successes=semantic.get('native_successes',0),
            confirmed=semantic.get('confirmed',0),batches=semantic.get('batches',0),
            published_mono=value.get('published_mono'),log=value.get('log'))])
    try:
        if value['schema']!=1 or value['task']!=task or value['generation']!=generation:return result('repair','RUNTIME_OWNER_MISMATCH')
        if value['state'] not in {'STARTING','RUNNING'}:return result('repair',value.get('reason') or 'RUNTIME_STOPPED')
        if not owner_held or not supervisor_alive:return result('repair','SUPERVISOR_OWNERSHIP_LOST')
        age=now-value['published_mono'];uptime=now-value['started_mono']
        if not all(math.isfinite(v) for v in (age,uptime)) or not 0<=age<=STATE_FRESHNESS or uptime<0:return result('repair','RUNTIME_STATE_STALE')
        recovery=value.get('recovery')
        if recovery is not None:
            # Bounded supervisor-owned document recovery: the old worker stopped
            # cooperatively and a fresh one must prove a native success in time.
            elapsed=now-recovery['started_mono']
            if not math.isfinite(elapsed) or not 0<=elapsed<=RECOVERY_WINDOW:return result('repair','DOCUMENT_RECOVERY_TIMEOUT')
            if recovery['initial'] is True:
                return result('starting','STARTING_DOCUMENT_REFRESH') if uptime<=STARTUP_REFRESH_SECONDS else result('repair','STARTUP_REFRESH_TIMEOUT')
            return result('healthy','DOCUMENT_RECOVERY')
        if not child_alive:
            if value['child'] is None and uptime<=90:return result('starting','STARTING_OWNED_WORKER')
            return result('repair','WORKER_OWNERSHIP_LOST')
        latest=value['latest'];stage=latest['stage'];stage_age=now-latest['tick']
        limit={'STARTING':90,'ATTACHING':90,'LOCAL':60,'NATIVE':45}[stage]
        if not math.isfinite(stage_age) or not 0<=stage_age<=limit:return result('repair','NATIVE_STALLED' if stage=='NATIVE' else 'PROGRESS_STALLED')
        s=value['semantic']
        if not s:return result('starting','STARTING_SEMANTIC_MONITOR') if uptime<=90 else result('repair','MISSING_SEMANTIC_MONITOR')
        if s['reason']:return result('repair',s['reason'])
        limits=SemanticLimits()
        for key in ('auth_failures','read_failures','write_failures','helper_failures','diagnostic_failures','batch_failures','missing_statuses','unconfirmed_attempts'):
            observed=s[key]
            threshold=limits.unconfirmed_attempts if key=='unconfirmed_attempts' else getattr(limits,key)
            if type(observed) is not int or not 0<=observed<threshold:return result('repair','SEMANTIC_FAILURE_'+key.upper())
        native_age=s['native_success_age']
        if type(s['native_successes']) is not int or s['native_successes']<0:return result('repair','INVALID_NATIVE_SUCCESS_COUNT')
        if native_age is None or s['native_successes']==0:
            return result('starting','STARTING_NATIVE_VALIDATION') if uptime<=90 else result('repair','NO_FRESH_NATIVE_SUCCESS')
        if type(native_age) not in (int,float) or not math.isfinite(native_age) or native_age<0 or not 0<=native_age+age<=limits.native_freshness:return result('repair','NO_FRESH_NATIVE_SUCCESS')
        if latest.get('lifecycle')!='RUNNING' or latest.get('phase') not in {'ACQUIRING','MANAGING','MAINTENANCE'}:return result('repair','CONTROLLER_NOT_RUNNING')
        return result('healthy',value['operational_state'])
    except (KeyError,TypeError,ValueError,OverflowError):return result('repair','INVALID_RUNTIME_STATE')


def health(directory,task,generation):
    generation=token(generation)
    try:
        # The scheduler can poll immediately after spawning the service, before
        # Python has published its first manifest (or replaced an old pointer).
        # Wait only for actual state; absence never fabricates STARTING/health.
        value=read_state(directory,generation)
        return evaluate(value,task=task,generation=generation,now=time.monotonic(),owner_held=held(directory),
                        supervisor_alive=same_process(value.get('supervisor')),child_alive=same_process(value.get('child')))
    except (OSError,ValueError,TypeError) as error:
        # No exception messages/paths or arbitrary values enter diagnostics.
        evidence=dict(runtime_read_error=type(error).__name__ if type(error).__name__ in
            {'FileNotFoundError','PermissionError','OSError','ValueError','TypeError','JSONDecodeError'} else 'invalid_state')
        for name in ('errno','winerror'):
            code=getattr(error,name,None)
            if type(code) is int and 0<=code<=65535:evidence[name]=code
        return dict(status='repair',generation=generation,diagnostic='RUNTIME_STATE_UNAVAILABLE',evidence=[evidence])


def stop(directory,task,generation,*,timeout=50):
    """Cooperative generation-bound request, never kill/HTTP/account operations."""
    directory=Path(directory).resolve();generation=token(generation)
    try:value=read_pointer(directory)
    except FileNotFoundError:
        if held(directory):raise ValueError('unknown_runtime_owner')
        return dict(status='stopped',generation=generation,diagnostic='NO_RUNTIME')
    if value['task']!=task or value['generation']!=generation:raise ValueError('runtime_owner_mismatch')
    supervisor=value['supervisor'];child=value.get('child')
    if not same_process(supervisor):
        if same_process(child) or held(directory):raise ValueError('orphan_worker_requires_reconciliation')
        return dict(status='stopped',generation=generation,diagnostic='OWNED_RUNTIME_EXITED')
    if not held(directory):raise ValueError('runtime_ownership_lost')
    atomic(directory/'runs'/generation/'stop.json',dict(task=task,generation=generation,supervisor=supervisor))
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:current=read(directory/'state.json')
        except PermissionError:
            # Transient Windows sharing denial; the stop deadline still bounds it.
            time.sleep(.1);continue
        if current['generation']!=generation:raise ValueError('runtime_generation_changed_during_stop')
        if not same_process(supervisor) and not same_process(child) and not held(directory):
            return dict(status='stopped',generation=generation,diagnostic=current.get('reason') or 'OWNED_RUNTIME_EXITED')
        time.sleep(.1)
    raise TimeoutError('owned_runtime_stop_timeout')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('service','health','stop'))
    parser.add_argument('--runtime-dir',required=True);parser.add_argument('--task-key',required=True)
    parser.add_argument('--generation',required=True)
    parser.add_argument('--database');parser.add_argument('--cache');parser.add_argument('--context');parser.add_argument('--port',type=int)
    parser.add_argument('--epoch-floor',type=int,default=1)
    # Interchangeable response to the bid-denial signature (measures.py).
    parser.add_argument('--write-denial-measure',default='noop')
    parser.add_argument('--auth-failure-measure',default='noop',help='noop or relogin (needs --recovery-config)')
    # Private local JSON {"account_label": ...} outside Git, for sign-in measures.
    # The label only filters Edge's saved sign-ins.
    parser.add_argument('--recovery-config')
    parser.add_argument('--refresh-on-start',action='store_true')
    parser.add_argument('--maintenance-gap',type=float,default=0.0,help='seconds without bids after a maintenance write')
    parser.add_argument('--margin',type=int,default=500,help='profit margin X in the bid cap')
    parser.add_argument('--list-markup',type=int,default=0,help='list won items at resale + markup (legal tick)')
    parser.add_argument('--bands',default='1000:11000',help='discovery bands max_bid:min_buy, comma separated')
    parser.add_argument('--max-auction-seconds',type=int,default=0,help='skip new bids on longer auctions (0 = no limit)')
    parser.add_argument('--search-budget',type=int,default=0,help='max transfer-market searches per rolling hour (0 = no cap)')
    parser.add_argument('--low-credit-hold',action='store_true',help='hold acquisition instead of halting at low credits')
    parser.add_argument('--coin-reservation',action='store_true',help='admit auctions only if spendable coins cover their cap')
    parser.add_argument('--interleave',action='store_true',help='acquire and maintain in quiet windows while managing')
    a=parser.parse_args(argv);token(a.generation)
    try:
        if a.action=='health':print(json.dumps(health(a.runtime_dir,a.task_key,a.generation),allow_nan=False));return 0
        if a.action=='stop':print(json.dumps(stop(a.runtime_dir,a.task_key,a.generation)));return 0
        if not all((a.database,a.cache,a.context,a.port)) or not 1024<=a.port<=65535:raise ValueError('service_arguments_required')
        from .__main__ import next_owner_epoch
        next_owner_epoch(0,a.epoch_floor)
        from .measures import measure
        denial=measure(a.write_denial_measure,recovery_config=a.recovery_config)
        startup=measure('relogin',recovery_config=a.recovery_config) if a.refresh_on_start else None
        auth=measure(a.auth_failure_measure,recovery_config=a.recovery_config)
        if auth.name not in {'noop','relogin'}:raise ValueError('invalid_auth_failure_measure')
        with Runtime(a.runtime_dir,a.task_key,a.generation) as runtime:
            return supervise(a,runtime=runtime,denial_measure=denial,startup_refresh=startup,auth_measure=auth)
    except (OSError,ValueError,TimeoutError,KeyError,TypeError) as error:
        # Exception values may contain paths or OS/provider details. Only type
        # and a finite action outcome are emitted at this CLI boundary.
        print(json.dumps(dict(status='repair' if a.action=='health' else 'failed',generation=a.generation,
            diagnostic='OPERATIONAL_'+a.action.upper()+'_FAILED',exception_type=type(error).__name__,evidence=[])))
        return 0 if a.action=='health' else 1


if __name__=='__main__':raise SystemExit(main())
