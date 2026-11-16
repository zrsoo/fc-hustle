"""Explicit single-use read-only production bridge audit; never launched by tests."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime,timezone
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
from fc_access.controller_v1.__main__ import guard_paths
from fc_access.controller_v1.adapter import ControllerAdapter
from fc_access.controller_v1.executor import ControllerExecutor,SerializedExecutor
from fc_access.controller_v1.server import Server
from fc_access.production_v1.contracts import Search
from fc_access.production_v1.prices import PriceService,CardKey
from fc_access.production_v1.pricing import PricingService
from fc_access.production_v1.price_cache import QuoteCache


def probe(output, *, status_only=False):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    def record(kind,**value):
        with (output/'checkpoint.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**value),allow_nan=False)+'\n')
            f.flush();os.fsync(f.fileno())
    scope=json.loads((ROOT/'docs/research/003/003-04/bid-receipt-repair-01/context.json').read_text(encoding='utf-8'))
    result=dict(classification='READ_ONLY_CONTROLLER_BRIDGE_AUDIT',mode='STATUS_FROM_DISCOVERY' if status_only else 'READ_OPERATIONS',
        max_reserved_ea_requests=3 if status_only else 18,
        max_commands=2 if status_only else 80,max_mutations=0,reserved_ea_requests=0,actual_ea_requests=0,
        commands=0,mutations=0,controllers_started=0,checks=[],limitations=[])
    record('PREPARED',context=scope,budget=result,deadline_seconds=600,
           operations=['discovery','status_batch from discovery'] if status_only else ['balance','watched v4','status_batch v4','watched v2','status_batch from v2',
                       'owned_item if freshly known won','transfer_list','unassigned','discovery',
                       'caps','price_helpers','production two-sample pricing','completed cache reuse'])
    deadline=time.monotonic()+600
    server=None;thread=None;cache=None
    try:
        with ExitStack() as locks:
            for p in guard_paths(ROOT,scope,output/'transport.sqlite',8784):locks.enter_context(process_lock(p))
            server=Server(output/'transport.sqlite',8784,write_authority=False)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            edge=ControllerExecutor(8784,attach_timeout=60)
            class Bounded:
                def attach(self,*args):return edge.attach(*args)
                def execute(self,c):
                    op=c['operation'];cost=0 if op=='price_helpers' else 2 if op=='search' else 1
                    if (op not in {'balance','watched','status_batch','search','caps','price_helpers','transfer_list','unassigned','owned_item'}
                            or time.monotonic()>deadline or result['commands']>=result['max_commands'] or
                            result['reserved_ea_requests']+cost>result['max_reserved_ea_requests']):
                        raise ValueError('audit_budget_or_operation_denied')
                    result['commands']+=1;result['reserved_ea_requests']+=cost
                    record('RESERVED_BEFORE_DELIVERY',ordinal=result['commands'],reserved_ea=cost,command=c)
                    v=edge.execute(c);record('NATIVE_RESULT',command=c,response=v)
                    result['actual_ea_requests']+=len(v['network'] if c['schema']==4 else v['result']['network'])
                    return v
            print('READ_ONLY_AUDIT_SERVICE_READY; attach reviewed production extension',flush=True)
            a=ControllerAdapter(SerializedExecutor(Bounded()),context=scope,owner=secrets.token_hex(16),epoch=1)
            record('ATTACHED',peer=dict(context=a.context,fences=a.fences),mutations_enabled=False)
            ids=lambda:secrets.token_hex(16)
            def check(label,fn):
                try:
                    v=fn();r=v if v['schema']==4 else v['result']
                    summary=dict(label=label,schema=v['schema'],operation=v['operation'],success=r['success'],
                        error=r['error'],status=r['status'],network=r['network'],
                        network_at=v.get('network_at') if v['schema']==4 else v['freshness']['network_at'],
                        rows=len(r.get('auctions') or []),items=len(r.get('items') or []))
                    if v['schema']==4:summary['designated_account_verified']=v['designated_account_verified']
                    if v['operation']=='balance':summary['credits']=r['credits']
                    if 'coverage' in v:summary['coverage']=v['coverage']
                    result['checks'].append(summary);record('CHECK',**summary)
                    print(json.dumps(summary),flush=True)
                    return v if r['success'] else None
                except Exception as error:
                    summary=dict(label=label,success=False,exception_type=type(error).__name__)
                    result['checks'].append(summary);record('CHECK',**summary);print(json.dumps(summary),flush=True)
                    return None
            def targets(rows):
                return [dict(trade_id=r['trade_id'],item_id=r['item']['item_id'],definition_id=r['item']['definition_id']) for r in rows[:10]]
            if status_only:
                discovery=check('discovery',lambda:a.native.search(ids(),Search.discovery()))
                rows=discovery['result']['auctions'] if discovery else []
                if rows:
                    batch=check('status_batch_from_discovery',lambda:a.status_batch(ids(),targets(rows)))
                    if batch:
                        linked=[server.store.linked_row(batch['command_id'],t)[0] for t in targets(rows)
                                if t not in batch['missing']]
                        result['status_links']=dict(requested=len(targets(rows)),returned=len(batch['auctions']),
                            missing=len(batch['missing']),validated_full_version_links=len(linked))
                else:result['limitations'].append('no_fresh_discovery_rows_for_status')
                result['status']='READS_PASS_WITH_LIMITATIONS' if rows and all(c['success'] for c in result['checks']) else 'READ_FAILURES'
                return result
            balance=check('balance',lambda:a.read(ids(),'balance'))
            if balance is None:raise ValueError('balance_fix_not_verified')
            watched4=check('watched_v4',lambda:a.read(ids(),'watched'))
            if watched4 and watched4['auctions']:
                check('status_batch_from_v4',lambda:a.status_batch(ids(),targets(watched4['auctions'])))
            else:result['limitations'].append('no_v4_watched_targets_for_status')
            watched2=check('watched_v2',lambda:a.native.read(ids(),'watched'))
            if watched2 and watched2['result']['auctions']:
                rows=watched2['result']['auctions']
                check('status_batch_from_v2',lambda:a.status_batch(ids(),targets(rows)))
                won=next((r for r in rows if r['trade_state']=='closed' and r['bid_state']=='highest' and r['native_is_won'] is True and r['expires']<=0),None)
                if won:
                    check('owned_item',lambda:a.native.read(ids(),'owned_item',targets([won])[0]))
                else:result['limitations'].append('owned_item_not_live_exercised_no_fresh_closed_highest_won_target')
            else:result['limitations'].extend(['no_v2_watched_targets_for_status','owned_item_not_live_exercised_no_fresh_won_target'])
            pile=check('transfer_list',lambda:a.native.read(ids(),'transfer_list'))
            check('unassigned',lambda:a.native.read(ids(),'unassigned'))
            discovery=check('discovery',lambda:a.native.search(ids(),Search.discovery()))
            available=discovery['result']['auctions'] if discovery else []
            candidate=next((r for r in sorted(available,key=lambda r:(r['current_bid'] or r['starting_bid'])) if r['trade_state']=='active' and r['item']['untradeable'] is False),None)
            fallback=(watched2['result']['auctions'] if watched2 else [])+(pile['result']['auctions'] if pile else [])
            selected=candidate or next((r for r in fallback if r['item']['definition_id']>0),None)
            if selected:
                service=PriceService(a.native,ids)
                try:
                    rules=service.load(key=CardKey(selected['item']['definition_id']))
                    helper_values=service.helpers([('above',500),('below',11000)])
                    summary=dict(label='caps_and_helpers',success=True,definition_id=selected['item']['definition_id'],
                        minimum=rules.minimum,maximum=rules.maximum,helper_values=helper_values)
                    result['checks'].append(summary);record('CHECK',**summary);print(json.dumps(summary),flush=True)
                    if candidate:
                        cache=QuoteCache(output/'quotes.sqlite');pricing=PricingService(a.native,ids,cache)
                        quote=pricing.quote(candidate,rules,X=500)
                        result['pricing']=asdict(quote);record('PRICING',quote=asdict(quote))
                        if quote.completed:
                            before=result['actual_ea_requests'];again=pricing.quote(candidate,rules,X=500)
                            result['cache']=dict(hit=again.evidence['cache_hit'],extra_ea_requests=result['actual_ea_requests']-before,
                                resale_price=again.resale_price)
                            cache.close();cache=None
                            reopened=QuoteCache(output/'quotes.sqlite')
                            try:result['cache']['restart_readable']=reopened.get(scope,selected['item']['definition_id'],now=a.now(),source='native') is not None
                            finally:reopened.close()
                        else:result['limitations'].append('production_pricing_not_completed_for_selected_real_candidate')
                    else:result['limitations'].append('no_discovery_candidate_for_two_search_pricing')
                except Exception as error:
                    result['checks'].append(dict(label='caps_helpers_or_pricing',success=False,exception_type=type(error).__name__))
            else:result['limitations'].append('no_real_definition_for_caps_or_pricing')
            result['status']='READS_PASS_WITH_LIMITATIONS' if all(c['success'] for c in result['checks']) else 'READ_FAILURES'
    except Exception as error:
        result['status']='BLOCKED';result['exception_type']=type(error).__name__;record('STOPPED',exception_type=type(error).__name__)
    finally:
        if cache:cache.close()
        if server:
            server.shutdown()
            if thread:thread.join(5)
            result['pending_commands']=server.store.db.execute("SELECT count(*) FROM c4_commands WHERE state IN ('WAITING','CLAIMED')").fetchone()[0]
            server.server_close()
        result['service_stopped']=thread is None or not thread.is_alive()
        record('CLOSED',result=result)
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in {'checks','pricing'}}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--status-only',action='store_true')
    args=parser.parse_args();value=probe(args.output,status_only=args.status_only)
    raise SystemExit(0 if value.get('status')=='READS_PASS_WITH_LIMITATIONS' else 1)
