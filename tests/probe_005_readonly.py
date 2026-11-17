"""Single-use diagnostic window: six read commands, no account writes or controller."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.controller_v1.__main__ import guard_paths
from fc_access.controller_v1.adapter import ControllerAdapter
from fc_access.controller_v1.executor import ControllerExecutor, SerializedExecutor
from fc_access.controller_v1.server import Server
from fc_access.production_v1.contracts import Search


def run(output, *, epoch=1, idle_seconds=0, target=None, status_targets=None):
    if type(epoch) is not int or epoch<1 or not 0<=idle_seconds<=40:raise ValueError('invalid_probe_scope')
    if target is not None:
        from fc_access.controller_v1.protocol import target as validate_target
        validate_target(target)
    if status_targets is not None:
        from fc_access.controller_v1.protocol import target as validate_target
        if target is not None or type(status_targets) is not list or not 1<=len(status_targets)<=10:
            raise ValueError('invalid_status_probe_scope')
        for value in status_targets:validate_target(value)
        if len({v['trade_id'] for v in status_targets})!=len(status_targets):
            raise ValueError('duplicate_status_probe_target')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    def record(kind, **fields):
        with (output / 'checkpoint.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), kind=kind, **fields)) + '\n')
            stream.flush(); os.fsync(stream.fileno())
    scope = json.loads((ROOT / 'private-captures/controller-v1/public-context.json').read_text())
    record('PREPARED', question='Current native account/authentication, inventory and exact-target transport after ownership repair',
           owner_epoch=epoch,local_idle_seconds=idle_seconds,
           exact_owned_target=target,
           exact_status_targets=status_targets,
           max_commands=6, max_ea_requests=7, max_mutations=0, deadline_seconds=240, context=scope)
    deadline = time.monotonic() + 240
    reserved = 0
    with ExitStack() as stack:
        for path in guard_paths(ROOT, scope, output / 'transport.sqlite', 8784):
            stack.enter_context(process_lock(path))
        edge = ControllerExecutor(8784, attach_timeout=60)
        server = Server(output / 'transport.sqlite', 8784, write_authority=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        class Bounded:
            def attach(self, *args): return edge.attach(*args)
            def execute(self, command):
                nonlocal reserved
                if command['operation'] not in {'balance', 'watched', 'transfer_list', 'unassigned', 'search', 'status_batch','owned_item'} or reserved >= 6 or time.monotonic() >= deadline:
                    raise ValueError('window_exhausted_or_operation_denied')
                reserved += 1
                record('RESERVED_BEFORE_DELIVERY', ordinal=reserved, command=command)
                response = edge.execute(command)
                record('NATIVE_RESULT', command=command, response=response)
                return response
        result = dict(status='FAILED', mutations=0)
        try:
            print('READ_ONLY_SERVICE_READY', flush=True)
            adapter = ControllerAdapter(SerializedExecutor(Bounded()), context=scope, owner=secrets.token_hex(16), epoch=epoch)
            record('ATTACHED', context=adapter.context, fences=adapter.fences)
            commands = [lambda: adapter.read(secrets.token_hex(16), 'balance'),
                        lambda: adapter.read(secrets.token_hex(16), 'watched'),
                        lambda: adapter.native.read(secrets.token_hex(16), 'transfer_list'),
                        lambda: adapter.native.read(secrets.token_hex(16), 'unassigned'),
                        lambda: adapter.native.search(secrets.token_hex(16), Search.discovery())]
            if target is not None:
                commands=[lambda:adapter.read(secrets.token_hex(16),'watched'),
                          lambda:adapter.native.read(secrets.token_hex(16),'transfer_list'),
                          lambda:adapter.native.read(secrets.token_hex(16),'unassigned'),
                          lambda:adapter.native.read(secrets.token_hex(16),'owned_item',target),
                          lambda:adapter.status_batch(secrets.token_hex(16),[target])]
            if status_targets is not None:
                commands=commands[:4]+[lambda:adapter.status_batch(secrets.token_hex(16),status_targets)]
            responses = []
            for call in commands:
                v = call(); r = v if v['schema'] == 4 else v['result']
                responses.append(v)
                print(json.dumps(dict(operation=v['operation'], success=r['success'], status=r['status'], error=r['error'])), flush=True)
                if not r['success']:
                    result['reason'] = 'FAILED_NATIVE_READ'; break
            else:
                rows = [] if target is not None or status_targets is not None else responses[-1]['result']['auctions'][:10]
                if status_targets is not None:
                    result.update(status_targets=len(status_targets),status_returned=len(responses[-1]['auctions']),
                                  status_missing=len(responses[-1]['missing']))
                if rows:
                    targets = [dict(trade_id=r['trade_id'], item_id=r['item']['item_id'], definition_id=r['item']['definition_id']) for r in rows]
                    status = adapter.status_batch(secrets.token_hex(16), targets)
                    result['status_targets'] = len(targets)
                    result['status_returned'] = len(status['auctions'])
                    result['status_missing'] = len(status['missing'])
                    if not status['success']: raise ValueError('status_failed')
                result['status'] = 'READS_VERIFIED'
                if idle_seconds:
                    record('OBSERVING_LOCAL_POLLING',seconds=idle_seconds,ea_requests=0)
                    end=min(time.monotonic()+idle_seconds,deadline)
                    while time.monotonic()<end:time.sleep(min(.5,end-time.monotonic()))
        except Exception as error:
            result['exception_type'] = type(error).__name__
        finally:
            with server.store.lock:
                diagnostics=[dict(command_id=cid,records=json.loads(body)) for cid,body in server.store.db.execute('SELECT command_id,body FROM c4_diagnostics ORDER BY seq')]
            (output/'diagnostics.json').write_text(json.dumps(diagnostics,indent=2)+'\n',encoding='utf-8')
            server.shutdown(); thread.join(5)
            result['pending'] = server.store.db.execute("SELECT count(*) FROM c4_commands WHERE state IN ('WAITING','CLAIMED')").fetchone()[0]
            server.server_close()
            result.update(reserved_commands=reserved, service_stopped=not thread.is_alive())
            record('CLOSED', result=result)
            (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'READS_VERIFIED' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--epoch',type=int,default=1)
    parser.add_argument('--idle-seconds',type=float,default=0)
    parser.add_argument('--target-json')
    parser.add_argument('--status-targets-file')
    args=parser.parse_args()
    raise SystemExit(run(args.output,epoch=args.epoch,idle_seconds=args.idle_seconds,target=json.loads(args.target_json) if args.target_json else None,
                        status_targets=json.loads(Path(args.status_targets_file).read_text()) if args.status_targets_file else None))
