"""Explicit finite item-12 process supervisor. No implicit native work.

The existing canonical foundation journal/cache are retained. This process owns
one broker and three separate Python worker processes, and waits for their exits
in finally. Service recovery remains an ordinary explicit operator action.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import sys
import time

from .final_run import BoundedBroker, Evidence, utc

ROOT = Path(__file__).resolve().parents[2]


def broker(manifest_path):
    from .config import Config
    from .locking import process_lock
    from .native import Mailbox
    from fc_access.production_v1.executor import EdgeExecutor
    from fc_access.production_v1.foundation import Foundation
    from fc_access.production_v1.contracts import stamp
    m = json.loads(Path(manifest_path).read_text())
    state = Path(m['state_dir'])
    evidence = Evidence(Path(m['output'])/'native.jsonl')
    f = box = None
    try:
        with process_lock(state/'native.executor.lock'), process_lock(ROOT/'private-captures/production-v1/actors-executor-8784.lock'):
            f = Foundation(EdgeExecutor(), context=m['context'], journal_path=m['journal'], cache_path=m['cache'])
            box = Mailbox(state/'native.sqlite3')
            seconds = int((stamp(m['deadline'])-datetime.now(timezone.utc)).total_seconds())
            b = BoundedBroker(box, f, Config(), wall_seconds=seconds, evidence=evidence)
            b.initialize()
            evidence.append('BROKER_READY', context=f.adapter.context, fences=f.adapter.fences,
                config=Config().export(), journal=m['journal'], cache=m['cache'])
            (Path(m['output'])/'broker-ready').open('x').close()
            while not b.stopped_reason:
                if b.run_one() is None:
                    time.sleep(.01)
            return 1
    except Exception:
        # Arbitrary native exception text must not enter retained logs.
        evidence.append('BROKER_STOP', reason='INITIALIZATION_OR_JOURNAL_FAILURE')
        return 1
    finally:
        if box: box.close()
        if f: f.close()
        evidence.close()


def stop_children(children, evidence):
    """Stop admissions/management first, then native dispatch. No native retries."""
    for role, process in reversed(children):
        if process.poll() is None:
            process.terminate()
    remaining = []
    for role, process in reversed(children):
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        evidence.append('PROCESS_EXIT', role=role, pid=process.pid, exit_code=process.returncode)
        if process.poll() is None:
            remaining.append(process.pid)
    return remaining


def run(output, *, wall_seconds=7200):
    from fc_access.production_v1.executor import EdgeExecutor
    from fc_access.production_v1.gate_00203 import require_pass, selected_checkpoint
    from .operator import inspect, retain
    if type(wall_seconds) is not int or not 60 <= wall_seconds <= 7200:
        raise ValueError('invalid_wall_bound')
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    evidence = Evidence(out/'supervisor.jsonl')
    children = []
    failed = False
    state = ROOT/'private-captures/final-remediation'
    box = state/'native.sqlite3'
    try:
        if box.exists():
            raise ValueError('existing_run_requires_checkpoint_review_not_budget_reset')
        regression = json.loads((ROOT/'docs/research/002/002-12/regressions.json').read_text())
        sys.path.insert(0, str(ROOT/'tests'))
        from check_00211_artifacts import regression_check
        regression_check(regression)
        gate = require_pass(selected_checkpoint())
        health = EdgeExecutor().request('/health')
        if not health['attached'] or not health['mutations_enabled']:
            raise ValueError('production_attachment_and_journal_authority_required')
        ready = ROOT/'docs/research/002/002-12/preflight-05.jsonl'
        from .final_run import load_evidence
        observations = load_evidence(ready)
        if not any(r['kind']=='PREFLIGHT_READY' and r['context']==health['peer']['context'] for r in observations):
            raise ValueError('native_preflight_required')
        evidence.append('PREREQUISITES', gate=gate, regression=regression,
            native_preflight=str(ready), context=health['peer']['context'])
        deadline = datetime.now(timezone.utc)+timedelta(seconds=wall_seconds)
        manifest = dict(task='002-12', state_dir=str(state), journal=str(state/'foundation.sqlite3'),
            cache=str(state/'completed-quotes.sqlite3'), context=health['peer']['context'],
            output=str(out), started_at=utc(), deadline=deadline.isoformat(),
            bounds=dict(wall_seconds=wall_seconds,native_requests=2000,stop_threshold=1800,reserve=200,max_enrollments=12))
        manifest_path = out/'manifest.json'
        with manifest_path.open('x',encoding='utf8') as handle: json.dump(manifest,handle,indent=2)
        evidence.append('RUN_STARTED', manifest=manifest)
        end = time.monotonic()+wall_seconds

        def launch(role, argv):
            process = subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            children.append((role,process))
            evidence.append('PROCESS_STARTED', role=role,pid=process.pid,argv=['{python}',*argv[1:]])
            return process

        native = launch('broker',[sys.executable,'-m','fc_access.actors_v1.final_supervisor',
            'broker','--manifest',str(manifest_path)])
        wait_until = min(end,time.monotonic()+55)
        while not (out/'broker-ready').exists() and native.poll() is None and time.monotonic()<wait_until:
            time.sleep(.1)
        if not (out/'broker-ready').exists():
            raise ValueError('broker_initialization_failed')
        for role,cycles in [('acquirer',12),('bidder',280),('maintenance',280)]:
            launch(role,[sys.executable,'-m','fc_access.actors_v1','--state-dir',str(state),role,'--cycles',str(cycles)])
        reason='WALL_DEADLINE'
        while time.monotonic()<end:
            exited=[(r,p) for r,p in children if p.poll() is not None]
            if any(p.returncode!=0 or r=='broker' for r,p in exited):
                reason='WORKER_OR_BROKER_FAILURE'
                failed=True
                break
            if len(exited)==len(children)-1:
                reason='ACTOR_CYCLE_LIMIT'
                break
            time.sleep(.1)
        evidence.append('STOP_REQUESTED', reason=reason)
    except Exception:
        failed=True
        evidence.append('STOP_REQUESTED',reason='PREFLIGHT_OR_SUPERVISION_FAILURE')
    finally:
        remaining=stop_children(children,evidence)
        if children and box.exists():
            try:
                evidence.append('DURABLE_EXPORT',data=inspect(box,'export'))
                evidence.append('STATUS_SNAPSHOT',data=inspect(box))
                retain(box,out/'state-backup')
            except Exception:
                evidence.append('RETENTION_FAILURE',reason='RETAIN_OR_EXPORT_FAILED')
        evidence.append('RUN_STOPPED',remaining_processes=remaining,verified_process_exit=not remaining,
            launched_roles=[r for r,p in children])
        evidence.close()
    return 0 if not remaining and not failed else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    r=sub.add_parser('run');r.add_argument('--output',required=True);r.add_argument('--wall-seconds',type=int,default=7200)
    b=sub.add_parser('broker');b.add_argument('--manifest',required=True)
    args=p.parse_args()
    return broker(args.manifest) if args.action=='broker' else run(args.output,wall_seconds=args.wall_seconds)


if __name__=='__main__':raise SystemExit(main())
