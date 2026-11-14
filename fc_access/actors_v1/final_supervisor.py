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


def review_resume(predecessor, mailbox_path, proposed_seconds):
    """Review a stopped checkpoint without reopening its window.

    A separately requested continuation retains all mailbox rows, reservations
    and consumed requests. An ambiguous mutation requires a different read-only
    reconciliation procedure and cannot be bypassed by this entry point.
    """
    import sqlite3
    from .final_run import load_evidence
    from fc_access.production_v1.contracts import stamp, MUTATIONS
    prior=Path(predecessor).resolve()
    rows=load_evidence(prior/'supervisor.jsonl')
    native=load_evidence(prior/'native.jsonl')
    opened=next(r for r in rows if r['kind']=='RUN_STARTED')
    stopped=rows[-1]
    if stopped['kind']!='RUN_STOPPED' or not stopped['verified_process_exit'] or stopped['remaining_processes']:
        raise ValueError('predecessor_not_stopped')
    elapsed=(stamp(stopped['at'])-stamp(opened['at'])).total_seconds()
    elapsed+=opened['manifest'].get('prior_active_wall_seconds',0)
    if elapsed<0 or elapsed+proposed_seconds>7200:
        raise ValueError('cumulative_wall_budget_exceeded')
    db=sqlite3.connect(Path(mailbox_path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        runtime=json.loads(db.execute('SELECT body FROM runtime WHERE id=1').fetchone()[0])
        if runtime['context']!=opened['manifest']['context']:
            raise ValueError('resume_context_mismatch')
        records=db.execute('SELECT id,command FROM work').fetchall()
        mutations=[json.loads(c) for _,c in records if json.loads(c)['operation'] in MUTATIONS]
        if mutations:
            journal=sqlite3.connect(Path(runtime['journal']).resolve().as_uri()+'?mode=ro',uri=True)
            try:
                for c in mutations:
                    p=c['params']
                    if c['operation'] in {'move','list'}:
                        from fc_access.production_v1.resale import mutation_authorized
                        if not mutation_authorized(runtime['journal'],c,reconciled=True):
                            raise ValueError('mutation_checkpoint_requires_read_only_reconciliation')
                        verified=journal.execute("SELECT body FROM registry_events_v1 WHERE "
                            "json_extract(body,'$.command_id')=? AND json_extract(body,'$.kind')='RESALE' "
                            "AND json_extract(body,'$.reason')='VERIFIED'",(c['id'],)).fetchone()
                        if not verified or not json.loads(verified[0]).get('read_ids'):
                            raise ValueError('mutation_checkpoint_requires_independent_readback')
                        continue
                    row=journal.execute('SELECT trade_id,item_id,definition_id,amount,state FROM commands WHERE id=?',
                        (c['id'],)).fetchone() if c['operation']=='bid' else None
                    if row!=(p.get('trade_id'),p.get('item_id'),p.get('definition_id'),p.get('amount'),'RECONCILED'):
                        raise ValueError('mutation_checkpoint_requires_read_only_reconciliation')
                    verified=journal.execute("SELECT 1 FROM events WHERE command_id=? AND reason IN "
                        "('BID_VERIFIED','WON_VERIFIED','LOST_VERIFIED')",(c['id'],)).fetchone()
                    if not verified:raise ValueError('mutation_checkpoint_requires_independent_readback')
            finally:journal.close()
        captured={r['command']['id'] for r in native if r['kind']=='DISPATCH_RESULT'}
        if not captured.issubset({cid for cid,c in records}):
            raise ValueError('mailbox_history_missing')
    finally:db.close()
    return dict(predecessor=str(prior),prior_active_wall_seconds=elapsed,
        authorization='Explicit FIXING_PERSISTENT_FAILURE instruction in the same worker',
        context=runtime['context'])


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
            config=Config(**m.get('config',{}))
            b = BoundedBroker(box, f, config, wall_seconds=seconds, evidence=evidence,
                extra_requests=m.get('preflight_request_charge',0))
            b.initialize()
            evidence.append('BROKER_READY', context=f.adapter.context, fences=f.adapter.fences,
                config=config.export(), journal=m['journal'], cache=m['cache'],
                initial_request_charge=b.requests)
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


def run(output, *, wall_seconds=7200, resume_from=None, preflight_path=None, regression_path=None, config=None,
        acquirer_cycles=12):
    from fc_access.production_v1.executor import EdgeExecutor
    from fc_access.production_v1.gate_00203 import require_pass, selected_checkpoint
    from .operator import inspect, retain
    from .config import Config
    if type(wall_seconds) is not int or not 60 <= wall_seconds <= 7200:
        raise ValueError('invalid_wall_bound')
    if type(acquirer_cycles) is not int or not 1<=acquirer_cycles<=12:
        raise ValueError('invalid_acquirer_cycle_bound')
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    evidence = Evidence(out/'supervisor.jsonl')
    children = []
    failed = False
    state = ROOT/'private-captures/final-remediation'
    box = state/'native.sqlite3'
    try:
        continuation=None
        if box.exists() and resume_from is not None:
            continuation=review_resume(resume_from,box,wall_seconds)
            evidence.append('CONTINUATION_REVIEW',**continuation)
        elif box.exists():
            raise ValueError('existing_run_requires_checkpoint_review_not_budget_reset')
        regression = json.loads(Path(regression_path or ROOT/'docs/research/002/002-12/regressions.json').read_text())
        sys.path.insert(0, str(ROOT/'tests'))
        from check_00211_artifacts import regression_check
        regression_check(regression)
        gate = require_pass(selected_checkpoint())
        health = EdgeExecutor().request('/health')
        if not health['attached'] or not health['mutations_enabled']:
            raise ValueError('production_attachment_and_journal_authority_required')
        ready = Path(preflight_path or ROOT/'docs/research/002/002-12/preflight-05.jsonl')
        from .final_run import load_evidence
        observations = load_evidence(ready)
        if not any(r['kind']=='PREFLIGHT_READY' and r['context']==health['peer']['context'] for r in observations):
            raise ValueError('native_preflight_required')
        if continuation:
            from fc_access.production_v1.contracts import stamp
            ready_at=next(r['at'] for r in observations if r['kind']=='PREFLIGHT_READY')
            if not 0<=(datetime.now(timezone.utc)-stamp(ready_at)).total_seconds()<=180:
                raise ValueError('fresh_resume_preflight_required')
            if continuation['context']!=health['peer']['context']:
                raise ValueError('resume_account_changed')
        evidence.append('PREREQUISITES', gate=gate, regression=regression,
            native_preflight=str(ready), context=health['peer']['context'])
        deadline = datetime.now(timezone.utc)+timedelta(seconds=wall_seconds)
        manifest = dict(task='002-12', state_dir=str(state), journal=str(state/'foundation.sqlite3'),
            cache=str(state/'completed-quotes.sqlite3'), context=health['peer']['context'],
            output=str(out), started_at=utc(), deadline=deadline.isoformat(),
            bounds=dict(wall_seconds=wall_seconds,native_requests=2000,stop_threshold=1800,reserve=200,max_enrollments=12))
        manifest['actor_cycles']=dict(acquirer=acquirer_cycles,bidder=280,maintenance=280)
        if continuation:
            manifest.update(continuation)
            manifest['config']=(config or Config()).export()
            # Charge every old/new preflight intent. Missing responses reserve
            # conservative fanout; no consumed count is reset or replayed.
            paths=set((ROOT/'docs/research/002/002-12').rglob('*.jsonl'))|{ready}
            charge=0
            for path in paths:
                events=load_evidence(path)
                responses={r['command']['id']:r['response'] for r in events if r['kind']=='NATIVE_READ'}
                for r in events:
                    if r['kind']=='READ_INTENT':
                        v=responses.get(r['command']['id'])
                        charge+=v['freshness']['request_count'] if v else 16
            manifest['preflight_request_charge']=charge
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
        for role,cycles in manifest['actor_cycles'].items():
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
    r.add_argument('--resume-from');r.add_argument('--preflight');r.add_argument('--regression');r.add_argument('--config')
    r.add_argument('--acquirer-cycles',type=int,default=12)
    b=sub.add_parser('broker');b.add_argument('--manifest',required=True)
    args=p.parse_args()
    if args.action=='broker':return broker(args.manifest)
    from .config import Config
    config=Config(**json.loads(Path(args.config).read_text())) if args.config else Config()
    return run(args.output,wall_seconds=args.wall_seconds,resume_from=args.resume_from,
        preflight_path=args.preflight,regression_path=args.regression,config=config,
        acquirer_cycles=args.acquirer_cycles)


if __name__=='__main__':raise SystemExit(main())
