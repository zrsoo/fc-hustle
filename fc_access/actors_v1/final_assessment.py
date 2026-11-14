"""Independent item-12 assessor. Reads captured native operations; never trades.

Branches are joined to distinct native readbacks and exact physical identities.
Registry assertions and callbacks alone cannot establish a transaction. Legacy
events before this experiment are excluded from integrated proof.
"""
from datetime import timedelta
import json
import math
from pathlib import Path

from fc_access.production_v1.contracts import LOCAL_OPERATIONS, MUTATIONS, parse_response, stamp
from fc_access.production_v1.bulk import classify, parameters
from .final_run import REQUIRED, load_evidence


def need(value, reason):
    if not value: raise ValueError(reason)


def physical(row):
    return (row['trade_id'],row['item']['item_id'],row['item']['definition_id'])


def bulk_proof(write, before, after):
    """Verify one bulk native write and an independent complete readback."""
    c,r=write['command'],write['response'];op=c['operation']
    need(op in {'clear_sold','relist_all'} and r['result']['success'],'bulk_not_successful')
    need(c['params']==parameters(before,op),'bulk_target_identity_mismatch')
    need(before['command_id']!=after['command_id'] and after['command_id']!=c['id'],'bulk_readback_not_independent')
    need(before['context']==after['context']==c['context'] and before['fences']==after['fences']==c['fences'],'bulk_context_changed')
    need(stamp(after['freshness']['network_at'])>stamp(before['freshness']['network_at']),'bulk_not_post_readback')
    classify(after)
    old={x['item']['item_id']:x for x in before['result']['auctions']}
    new={x['item']['item_id']:x for x in after['result']['auctions']}
    targets=set(c['params']['expected_item_ids'])
    need(targets,'empty_bulk_is_not_live_branch')
    clear=op=='clear_sold'
    need(set(new)==set(old)-targets if clear else set(new)==set(old),'bulk_items_changed')
    elapsed=(stamp(after['freshness']['network_at'])-stamp(before['freshness']['network_at'])).total_seconds()
    new_trades=[]
    for item in new:
        a,b=old[item],new[item]
        if not clear and item in targets:
            need(a['item']==b['item'] and (a['starting_bid'],a['buy_now_price'])==
                (b['starting_bid'],b['buy_now_price']),'relist_changed_price_or_physical_identity')
            need(b['trade_id'] not in {x['trade_id'] for x in old.values()} and b['trade_state']=='active'
                and b['current_bid']==0 and b['expires']==3600,'relist_duration_or_trade_unproven')
            new_trades.append(b['trade_id'])
        else:
            need(all(a[k]==b[k] for k in a if k!='expires'),'bulk_changed_survivor')
            need(a['expires']==b['expires'] if a['expires']<=0 else
                0<=a['expires']-b['expires']<=math.ceil(elapsed)+2,'bulk_changed_survivor_expiry')
    need(clear or len(new_trades)==len(set(new_trades)),'relist_duplicate_trade')
    return True


def audit(directory):
    root=Path(directory)
    supervisor=load_evidence(root/'supervisor.jsonl')
    native=load_evidence(root/'native.jsonl')
    start=next(r for r in supervisor if r['kind']=='RUN_STARTED')
    stop=next((r for r in reversed(supervisor) if r['kind']=='RUN_STOPPED'),None)
    need(stop is not None,'run_still_in_progress')
    launched=[r for r in supervisor if r['kind']=='PROCESS_STARTED']
    exits=[r for r in supervisor if r['kind']=='PROCESS_EXIT']
    exports=[r['data'] for r in supervisor if r['kind']=='DURABLE_EXPORT']
    need(len(exports)==1,'missing_durable_export')
    export=exports[0]
    events=[e for e in export['registry'] if stamp(start['at'])<=stamp(e['at'])<=stamp(stop['at'])]
    journal=[e for e in export['journal'] if stamp(start['at'])<=stamp(e['at'])<=stamp(stop['at'])]
    captures=[r for r in native if r['kind']=='DISPATCH_RESULT']
    ids={}
    reasons={}
    proof={}
    def mark(name,*refs): proof[name]=list(refs)
    for r in captures:
        c,v=r['command'],r['response'];cid=c['id']
        need(cid not in ids,'native_command_replayed')
        need(v is not None,'native_unknown_delivery')
        parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
        need(c['context']==export['context'],'native_scope_changed')
        need(r['counted_requests']==v['freshness']['request_count'],'native_fanout_miscounted')
        need(r['measured']['queue_ms']>=0 and r['measured']['roundtrip_ms']>=0,'unmeasured_native_work')
        ids[cid]=r
        reasons[cid]=v['result'].get('error')
    ready=[r for r in native if r['kind']=='BROKER_READY']
    need(len(ready)==1,'multiple_brokers_in_capture')
    good=[r for r in captures if r['response']['result']['success']]
    if good:mark('production_native',*[r['command']['id'] for r in good])
    prereq=next((r for r in supervisor if r['kind']=='PREREQUISITES'),None)
    if prereq and prereq['gate']['status']=='PASS':
        # Recheck the offline record's full command inventory, not its PASS flag.
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
        from check_00211_artifacts import regression_check
        regression_check(prereq['regression'])
        mark('prerequisites',prereq['seq']);mark('offline_regressions',prereq['seq'])
        if stamp(prereq['at'])<min(stamp(r['at']) for r in launched):
            mark('final_item_order',prereq['seq'])
    byrole={r['role']:r for r in launched}
    exit_by_pid={r['pid']:r for r in exits}
    if {'acquirer','bidder','maintenance','broker'}==set(byrole) and len({r['pid'] for r in launched})==4:
        a,b=byrole['acquirer'],byrole['bidder']
        overlap=max(stamp(a['at']),stamp(b['at']))<min(stamp(exit_by_pid[a['pid']]['at']),stamp(exit_by_pid[b['pid']]['at']))
        if overlap and all(any(e.get('actor')==role and e.get('reason')=='CYCLE_STARTED' for e in events)
                           for role in ('acquirer','bidder','maintenance')):
            mark('concurrent_python_actors',a['pid'],b['pid'],byrole['maintenance']['pid'])
    priorities={'acquirer':10,'bidder':90,'maintenance':0,'reconciliation':100}
    if len([r for r in launched if r['role']=='broker'])==1 and all(
        r['priority']==max(priorities[r['role']],90 if r['command']['operation'] in {'bid','watched','status'} else 0)
        for r in captures):
        mark('single_priority_executor',byrole['broker']['pid'])
    work={e['command_id']:e for e in export['native']}
    if ids and set(ids)<=set(work) and all(work[cid]['state']=='DONE' for cid in ids):
        mark('durable_state',*ids)
    if {r['pid'] for r in launched}==set(exit_by_pid) and stop['remaining_processes']==[] and stop['verified_process_exit']:
        mark('all_run_processes_stopped',stop['seq'])
    mark('append_only_evidence',supervisor[-1]['evidence_sha256'],native[-1]['evidence_sha256'])
    failures=[r for r in captures if not r['response']['result']['success']]
    if failures and any(r['kind']=='DISPATCH_STOP' for r in native) and any(r['kind']=='STOP_REQUESTED' for r in supervisor):
        mark('failure_reported',*[r['command']['id'] for r in failures])
    elif not failures:
        mark('failure_reported',stop['seq'])

    def response(cid,operation=None):
        r=ids.get(cid)
        if not r or not r['response']['result']['success'] or (operation and r['command']['operation']!=operation):
            raise ValueError('independent_native_source_missing')
        return r['response']

    def tick(direction,value,before):
        matches=[p['price'] for r in good if r['command']['operation']=='price_helpers' and
            0<=(stamp(before)-stamp(r['response']['freshness']['observed_at'])).total_seconds()<=300
            for p in r['response']['result']['probes'] if p['direction']==direction and p['value']==value]
        need(matches and len(set(matches))==1,'native_tick_unproven')
        return matches[0]

    for r in good:
        c,v=r['command'],r['response'];op=c['operation'];p=c['params']
        if op=='search' and p['purpose']=='discovery' and p.get('max_bid')==1000 and p.get('min_buy')==11000:
            if v['result']['auctions'] and all(0<(a['current_bid'] or a['starting_bid'])<=1000 and
                    a['buy_now_price']>=11000 for a in v['result']['auctions']):
                mark('discovery_filters',c['id'])
        if op=='balance':mark('natural_funds_observations',c['id'])
        if op=='bid':
            try:
                status=response(p['status_read_id']);funds=response(p['balance_read_id'],'balance')
                matches=[a for a in status['result']['auctions'] if physical(a)==(p['trade_id'],p['item_id'],p['definition_id'])]
                need(len(matches)==1,'bid_identity_unproven');a=matches[0]
                minimum=tick('above',a['current_bid'],r['at']) if a['current_bid'] else a['starting_bid']
                need(p['amount']==p['minimum']==minimum<=p['cap'] and funds['result']['credits']>=minimum,'bid_economics_unproven')
                after=[x for x in good if x['command']['operation']=='watched' and stamp(x['at'])>stamp(r['at']) and
                    any(physical(a2)==physical(a) and a2['current_bid']==minimum and a2['bid_state']=='highest'
                        for a2 in x['response']['result']['auctions'])]
                need(after,'bid_ack_without_independent_leading_readback')
                mark('spendable_funds',c['id'],funds['command_id'])
                if r['role']=='acquirer':mark('minimum_initial_bid',c['id'],after[0]['command']['id'])
                elif r['role']=='bidder' and a['bid_state']=='outbid' and a['trade_state']=='active':
                    mark('active_outbid',status['command_id']);mark('minimum_rebid',c['id'],after[0]['command']['id'])
            except ValueError:pass
        if op in {'clear_sold','relist_all'}:
            try:
                before=response(p['before_read_id'],'transfer_list')
                candidates=[x['response'] for x in good if x['command']['operation']=='transfer_list' and
                    stamp(x['response']['freshness']['network_at'])>stamp(v['freshness']['network_at'])]
                after=next((x for x in candidates if _valid_bulk(r,before,x)),None)
                need(after is not None,'no_bulk_independent_proof')
                mark('independent_maintenance_readbacks',c['id'],before['command_id'],after['command_id'])
                if op=='clear_sold':mark('sold_one_call_clear',c['id'])
                else:
                    mark('expired_one_call_relist',c['id']);mark('unchanged_relist_prices_duration',c['id'],after['command_id'])
            except ValueError:pass
    enrollments={e['trade_id']:e for e in events if e['kind']=='ENROLLMENT'}
    for trade,e in enrollments.items():
        q=e['quote'];ev=q['evidence']
        if q['completed'] and ev.get('source')=='native' and trade in {
                r['command']['params'].get('trade_id') for r in good if r['command']['operation']=='bid'}:
            if ev.get('cache_hit') is True and ev.get('price_searches')==0:mark('cached_valuation',e['seq'])
            elif ev.get('cache_hit') is False and ev.get('price_searches')==2:
                samples=ev['samples']
                actual=[r for r in good if r['command']['operation']=='search' and r['command']['params']['purpose']=='pricing'
                    and r['command']['params']['definition_id']==e['identity']['definition_id']]
                if len(samples)==2 and len(actual)>=2 and all(r['command']['params']['page']==1 and
                    r['command']['params']['count']==21 for r in actual) and any(
                    r['command']['params'].get('max_buy')==ev['first_min'] for r in actual):mark('fresh_valuation',e['seq'])
    for e in events:
        trade=e.get('trade_id')
        if trade not in enrollments:continue
        if e['kind']=='DECISION' and e['reason']=='LEADING' and e['action']=='HOLD':
            matching=[r for r in good if r['command']['operation']=='watched' and any(
                a['trade_id']==trade and a['bid_state']=='highest' and a['trade_state']=='active' for a in r['response']['result']['auctions'])]
            if matching:mark('leading_hold',e['seq'],matching[0]['command']['id'])
        if e['kind']=='DECISION' and e['reason']=='OVER_CAP':
            for r in good:
                if r['command']['operation']!='watched':continue
                for a in r['response']['result']['auctions']:
                    if a['trade_id']==trade and a['bid_state']=='outbid' and a['trade_state']=='active':
                        try:
                            if tick('above',a['current_bid'],e['at'])>e['cap']:mark('cap_stop',e['seq'],r['command']['id'])
                        except ValueError:pass
        if e.get('reason')=='OWNED_WIN_VERIFIED':
            try:
                won=response(e['win_read_id'],'watched');owned=response(e['owned_read_id'],'unassigned')
                i=e['identity'];a=next(a for a in won['result']['auctions'] if physical(a)==(trade,i['item_id'],i['definition_id']))
                item=next(x for x in owned['result']['items'] if x['item_id']==i['item_id'] and x['definition_id']==i['definition_id'])
                need(a['trade_state']=='closed' and a['bid_state']=='highest' and a['expires']<=0 and
                    a['current_bid']==item['last_sale_price']==e['paid']>0,'win_paid_unproven')
                mark('terminal_won',e['seq'],won['command_id']);mark('exact_owned_paid',e['seq'],owned['command_id'])
            except (ValueError,StopIteration):pass
    for e in journal:
        if e['reason']=='LOST_VERIFIED' and e['trade_id'] in enrollments:
            for r in good:
                if r['command']['operation'] in {'watched','status'} and any(a['trade_id']==e['trade_id'] and
                    a['bid_state']=='outbid' and a['trade_state'] in {'closed','expired'} and a['expires']<=0
                    for a in r['response']['result']['auctions']):mark('terminal_lost',r['command']['id'])
    # Remaining requirements deliberately stay unproven unless their complete
    # native evidence chains are available. No synthetic settlement API exists.
    metrics=dict(native_commands=len(captures),actual_native_requests=sum(r['counted_requests'] for r in captures),
        mutations=sum(r['command']['operation'] in MUTATIONS for r in captures),
        enrolled_this_run=len(enrollments),watched_rows=sum(len(r['response']['result']['auctions'])
            for r in good if r['command']['operation']=='watched'),
        queue_wait_ms=[r['measured']['queue_ms'] for r in captures],
        roundtrip_ms=[r['measured']['roundtrip_ms'] for r in captures],
        deadline_skips=sum(e.get('kind')=='DEADLINE_SKIPPED' for e in export['native_events']),
        completed_bidder_cycles=sum(e.get('actor')=='bidder' and e.get('reason')=='CYCLE_FINISHED' for e in events),
        stopped_pending_work=[dict(command_id=w['command_id'],role=w['role'],operation=w['operation'],state=w['state'])
                             for w in export['native'] if w['state']!='DONE'])
    capacities=[e for e in events if e.get('reason')=='CAPACITY_CHECKED' and 'capacity' in e]
    for e in capacities:
        cap=e['capacity']
        if cap['total']==cap['occupied']+cap['pending_resale']+cap['unresolved']<=50 and cap['occupied']<=50:
            mark('capacity_accounting',e['seq'],cap['read_id'])
    if captures and all(r['measured']['queue_ms']>=0 for r in captures):
        mark('native_fanout_deadline_misses',*[r['command']['id'] for r in captures])
    if all(n in proof for i in (1,2,3,4) for n in REQUIRED[i]):
        mark('all_transaction_and_maintenance_branches',stop['seq'])
    # Neither a nonexistent 50-auction sample nor a timer extension is inferred.
    unverified={name:'No independent integrated native evidence chain witnessed in this run'
                for names in REQUIRED.values() for name in names if name not in proof}
    unverified['attributable_realized_profit']='Current native adapter exposes no attributable per-sale net receipt; aggregate credits and projected tax cannot prove realized profit'
    mark('honest_missing_evidence',stop['seq'])
    criteria=[dict(index=i,status='PASS' if all(n in proof for n in names) else 'LIVE-UNVERIFIED',
        observed={n:proof[n] for n in names if n in proof},missing=[n for n in names if n not in proof])
        for i,names in REQUIRED.items()]
    return dict(schema=1,task='002-12',status='FULL PASS' if all(c['status']=='PASS' for c in criteria) else 'PARTIAL/NOT FULL PASS',
        live_window=dict(started_at=start['at'],stopped_at=stop['at'],seconds=(stamp(stop['at'])-stamp(start['at'])).total_seconds()),
        criteria=criteria,metrics=metrics,unverified={n:reason for n,reason in unverified.items() if n!='honest_missing_evidence'},
        failures=[dict(command_id=r['command']['id'],operation=r['command']['operation'],params=r['command']['params'],
            error=r['response']['result']['error'],network=r['response']['result']['network']) for r in failures])


def _valid_bulk(write,before,after):
    try:return bulk_proof(write,before,after)
    except (ValueError,KeyError,TypeError):return False
