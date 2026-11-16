"""One supervisor, one watchdog, one broker and three independent actor processes.

No lifetime/request/cycle/enrollment budget belongs to this mode. Native commands
remain finite, fresh, fenced and single-use. Exceptions stop, never auto-repair.
"""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
import time

from .control import Control
from .watchdog import Watchdog
from .recovery import reconcile
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.locking import process_lock
from fc_access.actors_v1.native import Broker, Mailbox

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE = ROOT / 'private-captures/continuous-production'
DEFAULT_JOURNAL = ROOT / 'private-captures/final-remediation/foundation.sqlite3'


def account_locks(context):
    from fc_access.production_v1.foundation import scope_for
    base = ROOT/'private-captures/production-v1'/('continuous-' + scope_for(context))
    return Path(str(base) + '.owner.lock'), Path(str(base) + '.native.lock')


def require_journal(path, context):
    from fc_access.production_v1.foundation import scope_for
    if not path.is_file():
        raise ValueError('existing_scoped_journal_required')
    db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        row = db.execute('SELECT context FROM registry_context_v1 WHERE scope=?', (scope_for(context),)).fetchone()
        if not row or json.loads(row[0]) != context:
            raise ValueError('existing_scoped_journal_required')
    finally:
        db.close()


def now():
    return datetime.now(timezone.utc)


def production_config(value=None):
    config = Config(**(value or {}))
    # The research API remains configurable; this production policy is locked.
    if config != Config():
        raise ValueError('production_strategy_configuration_locked')
    return config


def require_service(health, context, fences, journal):
    if (health.get('service') != 'fc-production-v1' or health.get('schema') != 2 or
            health.get('attached') is not True or health.get('mutations_enabled') is not True or
            health.get('peer') != dict(context=context, fences=fences) or
            not health.get('intent_journal') or Path(health['intent_journal']).resolve() != Path(journal).resolve()):
        raise ValueError('reviewed_journal_backed_service_required')


@contextmanager
def heartbeat(path, run, role):
    finished = threading.Event()
    def pulse():
        control = Control(path)
        try:
            while not finished.is_set():
                control.beat(run, role, os.getpid())
                finished.wait(1)
        finally:
            control.close()
    thread = threading.Thread(target=pulse, name='production-heartbeat', daemon=True)
    thread.start()
    try:
        yield
    finally:
        finished.set()
        thread.join(timeout=6)


class ContinuousBroker(Broker):
    def __init__(self, *args, control, run, **kwargs):
        self.control, self.run_id = control, run
        super().__init__(*args, dispatch_gate=lambda c: control.gate(run, command=c), **kwargs)

    def initialize(self):
        super().initialize()
        self.start_seq = self.mailbox.db.execute('SELECT coalesce(max(seq),0) FROM work').fetchone()[0]

    def run_one(self):
        self.control.gate(self.run_id)
        if self.control.age(self.run_id, 'executor') >= 1:
            self.control.beat(self.run_id, 'executor', os.getpid())
        result = super().run_one()
        if result:
            c, response, state = self.mailbox.db.execute(
                'SELECT command,response,state FROM work WHERE id=?', (result['command_id'],)).fetchone()
            c, response = json.loads(c), json.loads(response) if response else None
            self.control.append(self.run_id, 'NATIVE_RESULT', command=c, response=response, state=state,
                                measured=result)
            from fc_access.production_v1.bid_receipt import ordinary_rejection
            if state == 'UNKNOWN' or (not response['result']['success'] and not ordinary_rejection(c,response)) or response['freshness']['request_count'] > 16:
                self.control.stop(self.run_id, 'AMBIGUOUS_OR_FAILED_NATIVE_COMMAND')
                raise ValueError('native_command_requires_reconciliation')
        # Expired queued commands also require a retained controlled stop.
        if self.mailbox.db.execute("SELECT 1 FROM work WHERE seq>? AND state='UNKNOWN' AND reason='DEADLINE_SKIPPED'",
                                   (self.start_seq,)).fetchone():
            self.control.stop(self.run_id, 'COMMAND_EXPIRED')
            raise ValueError('command_expired')
        return result


def broker(control, run, manifest, *, executor_factory=None, fixture=False):
    from fc_access.production_v1.executor import EdgeExecutor
    from fc_access.production_v1.foundation import Foundation
    state, journal = Path(manifest['state_dir']), Path(manifest['journal'])
    config = production_config(manifest['config'])
    f = box = None
    # The port lock is shared with the finite and standalone executor. The
    # journal lock also prevents alternate state directories/ports owning it.
    with ExitStack() as stack:
        for lock in (ROOT / f"private-captures/production-v1/actors-executor-{manifest['port']}.lock",
                     account_locks(manifest['context'])[1],
                     journal.with_suffix('.continuous.executor.lock'), state/'native.executor.lock'):
            stack.enter_context(process_lock(lock))
        edge = (executor_factory or EdgeExecutor)(manifest['port'])
        class GuardedTransport:
            def ownership_epoch(self, context): return edge.ownership_epoch(context)
            def attach(self, context, owner, epoch): return edge.attach(context, owner, epoch)
            def execute(self, c):
                from fc_access.production_v1.contracts import parse_response
                control.gate(run, command=c, startup=not control.latest(run, 'READY'))
                control.beat(run, 'executor', os.getpid())
                startup = not control.latest(run, 'READY')
                if startup:
                    control.append(run, 'RECOVERY_INTENT', command=c)
                value = edge.execute(c)
                if startup:
                    value = parse_response(value, c, now=now(), source='fixture' if fixture else 'native')
                    control.append(run, 'RECOVERY_READ', command=c, response=value)
                return value
        try:
            f = Foundation(GuardedTransport(), context=manifest['context'], journal_path=journal,
                           cache_path=manifest['cache'], interval=config.native_interval_seconds, fixture=fixture)
            if not fixture:
                require_service(edge.request('/health'), f.adapter.context, f.adapter.fences, journal)
            box = Mailbox(state/'native.sqlite3')
            b = ContinuousBroker(box, f, config, control=control, run=run)
            b.initialize()
            control.beat(run, 'executor', os.getpid())
            control.append(run, 'ATTACHED', fences=f.adapter.fences, work_start_seq=b.start_seq)
            # Recovered deliveries are never queued again. Reconciliation uses
            # exact current mappings, independent reads, and the original journal.
            proof = reconcile(f)
            control.append(run, 'RECONCILED', **proof)
            # Set pacing after the final recovery read, including local helpers.
            b.last = b.clock()
            control.append(run, 'READY', fences=f.adapter.fences)
            while not control.latest(run, 'STOP_REQUESTED'):
                if b.run_one() is None:
                    time.sleep(.05)
        finally:
            if box: box.close()
            if f: f.close()


def worker(control, run, manifest, role):
    from fc_access.actors_v1.native import QueueExecutor
    from fc_access.actors_v1.actors import Acquirer, Bidder, connect
    from fc_access.actors_v1.maintenance import TransferMaintenance
    executor = QueueExecutor(Path(manifest['state_dir'])/'native.sqlite3', role)
    f = None
    try:
        control.gate(run)
        with heartbeat(control.path, run, role):
            f = connect(executor)
            actor = {'acquirer': Acquirer, 'bidder': Bidder, 'maintenance': TransferMaintenance}[role](
                f, production_config(manifest['config']))
            actor.record('PROCESS_READY')
            actor.run(stop=lambda: bool(control.latest(run, 'STOP_REQUESTED')))
    finally:
        if f: f.close()
        executor.close()


def monitor(control, run):
    monitor = Watchdog(control, run, now=now)
    while not control.latest(run, 'STOP_REQUESTED'):
        monitor.step()
        control.beat(run, 'monitor', os.getpid())
        time.sleep(1)


def child(path, run, role):
    control = Control(path)
    try:
        manifest = control.latest(run, 'RUN_OPEN')
        if not manifest or control.latest(None, 'RUN_OPEN')['run'] != run:
            raise ValueError('superseded_run')
        if role == 'monitor': monitor(control, run)
        elif role == 'executor': broker(control, run, manifest)
        else: worker(control, run, manifest, role)
        return 0
    except BaseException as error:
        if role == 'monitor' and not control.latest(run, 'STOP_REQUESTED'):
            control.append(run, 'SUPERVISION_GAP', role='monitor', reason='UNEXPECTED_EXCEPTION')
        safe = {'unmapped_commitment_requires_independent_reconciliation',
                'unresolved_write_requires_independent_reconciliation', 'fresh_complete_inventory_required',
                'reviewed_journal_backed_service_required', 'process_already_running', 'supervision_lost',
                'read_only_recovery', 'native_command_requires_reconciliation', 'command_expired'}
        control.append(run, 'EXCEPTION', role=role, exception_type=type(error).__name__,
                       reason=str(error) if str(error) in safe else 'UNCLASSIFIED_EXCEPTION')
        control.stop(run, 'PROCESS_EXCEPTION_' + role.upper())
        return 1
    finally:
        control.close()


def stop_children(children, control, run):
    # Gate first, then let a finite in-flight command/local waits settle. New
    # readbacks wait for recovery. Forced exits retain ambiguity in the journal.
    end = time.monotonic() + 40
    while any(p.poll() is None for _, p in children) and time.monotonic() < end:
        control.beat(run, 'supervisor', os.getpid())
        time.sleep(.1)
    for role, process in reversed(children):
        if process.poll() is None:
            control.append(run, 'FORCED_EXIT', role=role, pid=process.pid)
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        control.append(run, 'PROCESS_EXIT', role=role, pid=process.pid, exit_code=process.returncode)
    return [p.pid for _, p in children if p.poll() is None]


def run(state, *, context, journal=DEFAULT_JOURNAL, cache=None, port=8784, recovery=False):
    from fc_access.production_v1.contracts import context as validate_context
    validate_context(context)
    if context['platform'] != 'pc' or context['game'] != 'fc27':
        raise ValueError('fc27_pc_required')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid_port')
    state, journal = Path(state).resolve(), Path(journal).resolve()
    cache = Path(cache).resolve() if cache else journal.with_name('completed-quotes.sqlite3')
    state.mkdir(parents=True, exist_ok=True)
    with process_lock(account_locks(context)[0]), process_lock(state/'supervisor.lock'), process_lock(journal.with_suffix('.continuous.owner.lock')):
        control = Control(state/'control.sqlite3')
        children, run_id = [], secrets.token_hex(16)
        failed = False
        try:
            require_journal(journal, context)
            previous = control.latest(None, 'RUN_OPEN')
            if previous and not recovery:
                raise ValueError('existing_production_requires_recover')
            if previous and previous['context'] != context:
                raise ValueError('production_context_change_forbidden')
            if previous and (Path(previous['journal']) != journal or Path(previous['cache']) != cache):
                raise ValueError('recovery_must_preserve_durable_paths')
            # Probe every runtime lock before opening a replacement segment or
            # changing a journal/session epoch. An orphan must finish exiting.
            with ExitStack() as probes:
                for lock in (ROOT / f'private-captures/production-v1/actors-executor-{port}.lock',
                             account_locks(context)[1],
                             journal.with_suffix('.continuous.executor.lock'), state/'native.executor.lock',
                             *(journal.with_suffix('.' + r + '.lock') for r in ('acquirer','bidder','maintenance'))):
                    probes.enter_context(process_lock(lock))
            if previous and not control.latest(previous['run'], 'RUN_STOPPED'):
                control.append(previous['run'], 'SUPERVISION_GAP', role='supervisor', reason='CRASH_RECOVERY')
                control.stop(previous['run'], 'CRASH_RECOVERY')
            control.append(run_id, 'RUN_OPEN', context=context, state_dir=str(state), journal=str(journal),
                cache=str(cache),
                port=port, config=production_config().export(), predecessor=previous['run'] if previous else None,
                pid=os.getpid(), source='native')
            def launch(role):
                p = subprocess.Popen([sys.executable, '-m', 'fc_access.continuous_v1', '--state-dir', str(state),
                    '_child', '--run', run_id, '--role', role], cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                children.append((role, p))
                control.append(run_id, 'PROCESS_STARTED', role=role, pid=p.pid)
            control.beat(run_id, 'supervisor', os.getpid())
            launch('monitor')
            launched_executor = launched_actors = False
            while not control.latest(run_id, 'STOP_REQUESTED'):
                if control.age(run_id, 'supervisor') >= 1:
                    control.beat(run_id, 'supervisor', os.getpid())
                if any(p.poll() is not None for _, p in children):
                    if any(role == 'monitor' and p.poll() is not None for role, p in children):
                        control.append(run_id, 'SUPERVISION_GAP', role='monitor', reason='PROCESS_EXIT')
                    control.stop(run_id, 'CHILD_EXIT'); failed = True; break
                if not launched_executor and control.latest(run_id, 'HEARTBEAT_monitor'):
                    launch('executor'); launched_executor = True
                if launched_executor and not launched_actors and control.latest(run_id, 'READY'):
                    for role in ('bidder', 'maintenance', 'acquirer'): launch(role)
                    launched_actors = True
                if not 0 <= control.age(run_id, 'monitor') <= 10:
                    if time.monotonic() - control.latest(run_id, 'RUN_OPEN')['tick'] > 10:
                        control.append(run_id, 'SUPERVISION_GAP', role='monitor')
                        control.stop(run_id, 'MONITOR_LOST'); failed = True; break
                time.sleep(.25)
            stop = control.latest(run_id, 'STOP_REQUESTED')
            failed |= bool(stop and stop['reason'] != 'OPERATOR_STOP')
        except BaseException as error:
            # Errors before RUN_OPEN must not create a spurious new run/stop.
            if control.latest(run_id, 'RUN_OPEN'):
                control.append(run_id, 'EXCEPTION', role='supervisor', exception_type=type(error).__name__)
                control.stop(run_id, 'SUPERVISOR_EXCEPTION')
            failed = True
        finally:
            if control.latest(run_id, 'RUN_OPEN'):
                remaining = stop_children(children, control, run_id)
                control.append(run_id, 'RUN_STOPPED', remaining_processes=remaining,
                    verified_process_exit=not remaining, healthy_segment_closed=True)
            control.close()
        return 1 if failed else 0
