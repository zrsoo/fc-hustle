"""Explicit finite read-only 004-02 window. Never invoked by acceptance validators."""
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.continuous_v1.runtime import account_locks
from fc_access.controller_v1.adapter import ControllerAdapter
from fc_access.controller_v1.executor import ControllerExecutor
from fc_access.controller_v1.server import Server


def utc():return datetime.now(timezone.utc)


def probe(output):
    # The caller must choose a new window; no existing path is ever resumed/replayed.
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    checkpoint=output/'checkpoint.jsonl'
    def record(kind,**values):
        with checkpoint.open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(at=utc().isoformat(),kind=kind,**values),sort_keys=True,allow_nan=False)+'\n')
            f.flush();os.fsync(f.fileno())
    scope=json.loads((ROOT/'docs/research/002/002-03/attempts/20261114-adapter-repair-gate-06/gate.json').read_text())['context']
    deadline=utc()+timedelta(seconds=180)
    result=dict(schema=1,task='004-02',mode='AUTHENTICATED_READ_ONLY',status='EXTERNAL_LIMITATION',
                max_requests=3,max_mutations=0,reserved_requests=0,account_mutations=0,actual_target_count=0,
                requested=[],returned=[],missing=[],untested_limits=[],cleanup={})
    record('PREPARED',question='One native array invocation, one exact multi-ID GET, no market discovery',
           window=output.name,scope=scope,account='zzorniss',deadline=deadline.isoformat(),max_requests=3,max_mutations=0,
           recipe=['watched','status_batch for up to ten retained exact targets','independent watched'])
    server=None;thread=None
    try:
        # Classify process lines in place; never export command lines or session material.
        from baseline_00401 import processes
        result['before']=processes()
        with ExitStack() as stack:
            for path in [*account_locks(scope),ROOT/'private-captures/production-v1/actors-executor-8784.lock']:
                stack.enter_context(process_lock(path))
            server=Server(output/'transport.sqlite',8784)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            edge=ControllerExecutor(attach_timeout=60)
            # Peer/document selection is a normal click on the reviewed extension.
            # The next owner is durable in this new service only, never in old state.
            class Bounded:
                def attach(self,*args):return edge.attach(*args)
                def execute(self,c):
                    if utc()>=deadline or result['reserved_requests']>=3 or c['operation'] not in {'watched','status_batch'}:
                        raise ValueError('bounded_window_exhausted')
                    expected=['watched','status_batch','watched'][result['reserved_requests']]
                    if c['operation']!=expected:raise ValueError('recipe_mismatch')
                    result['reserved_requests']+=1
                    record('RESERVED_BEFORE_DELIVERY',ordinal=result['reserved_requests'],command=c)
                    value=edge.execute(c)
                    record('NATIVE_RESULT',command=c,response=value)
                    return value
            adapter=ControllerAdapter(Bounded(),context=scope,owner=secrets.token_hex(16),epoch=1)
            result['attachment']=dict(service='fc-controller-v1',write_authority=False,peer=dict(context=adapter.context,fences=adapter.fences))
            record('ATTACHED',**result['attachment'])
            full=adapter.read(secrets.token_hex(16),'watched')
            if not full['success']:
                result['limitation']='fresh_watched_'+full['error'];return result
            targets=[dict(trade_id=r['trade_id'],item_id=r['item']['item_id'],definition_id=r['item']['definition_id']) for r in full['auctions'][:10]]
            result['actual_target_count']=len(targets);result['requested']=targets
            result['designated_account_verified']=full['designated_account_verified']
            if not targets:
                result['limitation']='authenticated_watchlist_empty_no_real_retained_targets'
                result['untested_limits']=['multi_id','ten_targets','live_interleaving','live_error_branches'];return result
            time.sleep(2)
            status=adapter.status_batch(secrets.token_hex(16),targets)
            result['batch_success']=status['success'];result['batch_error']=status['error'];result['network']=status['network']
            result['returned']=[dict(trade_id=r['trade_id'],item_id=r['item']['item_id'],definition_id=r['item']['definition_id'],
                trade_state=r['trade_state'],bid_state=r['bid_state'],current_bid=r['current_bid'],expires=r['expires']) for r in status['auctions']]
            result['missing']=status['missing'];result['links']=status['links']
            time.sleep(2)
            comparison=adapter.read(secrets.token_hex(16),'watched')
            result['comparison_success']=comparison['success'];result['comparison_count']=len(comparison['auctions'])
            result['untested_limits']=['live_interleaving','live_error_branches','live_mutations_new_authority']
            if len(targets)<10:result['untested_limits'].append('ten_targets')
            if len(targets)<2:result['untested_limits'].append('multi_id')
            if status['success'] and comparison['success'] and len(targets)>=2:
                result['status']='LIVE_VERIFIED_WITH_ACTUAL_LIMIT'
            else:result['limitation']='fewer_than_two_retained_targets' if len(targets)<2 else 'batch_or_comparison_failed'
    except Exception as e:
        result['limitation']=str(e) if isinstance(e,ValueError) and str(e).replace('_','').isalnum() else type(e).__name__
        record('STOPPED',limitation=result['limitation'])
    finally:
        if server:
            server.shutdown()
            if thread:thread.join(timeout=3)
            result['cleanup']['service_thread_stopped']=not thread.is_alive()
            result['cleanup']['pending_commands']=server.store.db.execute("SELECT count(*) FROM c4_commands WHERE state IN ('WAITING','CLAIMED')").fetchone()[0]
            server.server_close()
        else:result['cleanup']['service_thread_stopped']=True;result['cleanup']['pending_commands']=0
        result['cleanup']['controllers_started']=0
        result['cleanup']['mutations_enabled']=False
        record('CLOSED',result=result)
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    args=p.parse_args();result=probe(args.output);print(json.dumps({k:v for k,v in result.items() if k not in {'before','attachment'}}))
