"""Explicit lifecycle entry point. Importing this module performs no I/O."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import threading
from urllib.request import Request, urlopen


def guard_paths(root, scope, database, port):
    """Canonical account/native guards shared with the legacy runtime."""
    from fc_access.production_v1.foundation import scope_for
    root,database=Path(root),Path(database)
    base=root/'private-captures/production-v1'/('continuous-'+scope_for(scope))
    return (Path(str(base)+'.owner.lock'),Path(str(base)+'.native.lock'),
            root/f'private-captures/production-v1/actors-executor-{port}.lock',
            database.with_suffix('.controller.lock'))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    run=sub.add_parser('run',help='Supervised owned account activity; no automatic launch or restart')
    run.add_argument('--database',required=True);run.add_argument('--cache',required=True)
    run.add_argument('--context',required=True,help='JSON file containing public account/persona scope only')
    run.add_argument('--port',required=True,type=int)
    for action in ('status','pause','stop'):
        c=sub.add_parser(action)
        if action=='status':
            group=c.add_mutually_exclusive_group(required=True)
            group.add_argument('--port',type=int);group.add_argument('--database')
        else:c.add_argument('--port',required=True,type=int)
    a=p.parse_args(argv)
    if a.action=='status' and a.database:
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(Path(a.database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            phase,lifecycle,reason,batch_id=db.execute('SELECT phase,lifecycle,reason,batch_id FROM c4_controller').fetchone()
            print(json.dumps(dict(phase=phase,lifecycle=lifecycle,reason=reason,batch_id=batch_id,
                members=[dict(trade_id=t,state=s) for t,s in db.execute('SELECT trade_id,state FROM c4_members')],
                work=[dict(command_id=cid,state=s) for cid,s in db.execute('SELECT id,state FROM c4_work')]),sort_keys=True))
        return
    if not 1024<=a.port<=65535:p.error('port must be 1024..65535')
    if a.action!='run':
        payload=json.dumps({'action':a.action}).encode() if a.action!='status' else None
        request=Request(f'http://127.0.0.1:{a.port}/'+('status' if payload is None else 'control'),
            data=payload,headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=60) as response:print(response.read().decode())
        return
    from .watchdog import supervise
    return supervise(a)


def run_controller(a, supervision):
    """Worker entry, called only by the supervisor after an explicit CLI run."""
    from fc_access.production_v1.contracts import context
    from fc_access.production_v1.price_cache import QuoteCache
    from fc_access.actors_v1.locking import process_lock
    from .server import Server
    from .executor import ControllerExecutor,SerializedExecutor
    from .adapter import ControllerAdapter
    from .controller import Controller
    scope=context(json.loads(Path(a.context).read_text()))
    root=Path(__file__).resolve().parents[2]
    database=Path(a.database).resolve();database.parent.mkdir(parents=True,exist_ok=True)
    # Canonical locks match both the legacy continuous runtime and finite probes.
    with ExitStack() as stack:
        for lock in guard_paths(root,scope,database,a.port):
            stack.enter_context(process_lock(lock))
        server=Server(database,a.port,write_authority=True)
        server.store.supervision_guard=supervision.require
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        cache=None;controller=None
        try:
            previous=server.store.db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
            epoch=json.loads(previous[0])['fences']['epoch']+1 if previous else 1
            adapter=ControllerAdapter(SerializedExecutor(ControllerExecutor(a.port),progress=supervision.progress),context=scope,owner=secrets.token_hex(16),epoch=epoch)
            cache=QuoteCache(a.cache)
            controller=Controller(server.store,adapter,cache);server.controller=controller
            supervision.snapshot=lambda:dict(controller.journal.state(),members=controller.journal.members())
            # run is the sole CLI operation that grants RUNNING lifecycle.
            controller.run(progress=supervision.state)
        except KeyboardInterrupt:
            if controller:controller.stop()
        finally:
            if controller and controller.status()['lifecycle']=='RUNNING':controller.stop()
            state=controller.status() if controller else None
            server.shutdown();thread.join(5);server.server_close()
            if cache:cache.close()
    return state


if __name__=='__main__':raise SystemExit(main())
