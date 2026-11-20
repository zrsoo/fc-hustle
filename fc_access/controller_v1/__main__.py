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


def controller_config(a):
    """Launch arguments -> ControllerConfig. The coin rule replaces the entry threshold."""
    from dataclasses import replace
    from .config import ControllerConfig
    config=replace(ControllerConfig(),maintenance_gap=float(getattr(a,'maintenance_gap',0) or 0),
                   margin=int(getattr(a,'margin',500)),list_markup=int(getattr(a,'list_markup',0) or 0),
                   bands=parse_bands(getattr(a,'bands',None) or '1000:11000'),
                   max_auction_seconds=int(getattr(a,'max_auction_seconds',0) or 0),
                   search_budget=int(getattr(a,'search_budget',0) or 0),
                   low_credit_hold=bool(getattr(a,'low_credit_hold',False)),
                   coin_reservation=bool(getattr(a,'coin_reservation',False)),
                   interleave=bool(getattr(a,'interleave',False)),
                   watch_reserve=int(getattr(a,'watch_reserve',1) or 1),
                   bid_at_cap=bool(getattr(a,'bid_at_cap',False)),
                   rank_bands=bool(getattr(a,'rank_bands',False)),
                   stored_price_rules=bool(getattr(a,'stored_price_rules',False)),
                   min_seconds_left=int(getattr(a,'min_seconds_left',60)))
    return replace(config,entry_threshold=0) if config.coin_reservation else config


def parse_bands(text):
    """'1000:11000,3000:20000' -> ((1000, 11000), (3000, 20000)); config validates ranges."""
    return tuple(tuple(int(v) for v in part.split(':')) for part in text.split(',') if part.strip())


def next_owner_epoch(previous, floor=1):
    """Public native fence recovery; cannot lower a persisted epoch or replay work."""
    if type(previous) is not int or not 0<=previous<2**53-1 or type(floor) is not int or not 1<=floor<=2**53-1:
        raise ValueError('invalid_owner_epoch_floor')
    return max(previous+1,floor)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    run=sub.add_parser('run',help='Supervised owned account activity; no automatic launch or restart')
    run.add_argument('--database',required=True);run.add_argument('--cache',required=True)
    run.add_argument('--context',required=True,help='JSON file containing public account/persona scope only')
    run.add_argument('--port',required=True,type=int)
    run.add_argument('--epoch-floor',type=int,default=1)
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
        cache=None;controller=None;rules=None
        try:
            previous=server.store.db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
            epoch=next_owner_epoch(json.loads(previous[0])['fences']['epoch'] if previous else 0,getattr(a,'epoch_floor',1))
            adapter=ControllerAdapter(SerializedExecutor(ControllerExecutor(a.port),progress=supervision.progress),context=scope,owner=secrets.token_hex(16),epoch=epoch)
            def report_result(c,v):
                with server.store.lock:
                    count=server.store.db.execute('SELECT coalesce(sum(json_array_length(body)),0) FROM c4_diagnostics WHERE command_id=?',(c['id'],)).fetchone()[0]
                supervision.result(c,v,diagnostic_records=count)
            adapter.executor.result=report_result
            adapter.executor.failure=supervision.failure
            server.store.semantic_report=supervision.policy_result
            cache=QuoteCache(a.cache)
            config=controller_config(a)
            if config.stored_price_rules:
                from fc_access.production_v1.price_store import PriceRuleStore
                rules=PriceRuleStore(Path(a.cache).resolve().parent/'price-rules.sqlite3')
            controller=Controller(server.store,adapter,cache,config=config,rules=rules);server.controller=controller
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
            if rules:rules.close()
    return state


if __name__=='__main__':raise SystemExit(main())
