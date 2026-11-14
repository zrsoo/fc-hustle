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


def listing_proof(write,before,caps,after,*,stored_price,previous_tick,started_at,reconciled=False):
    """Actual owned DTO, native cap/tick, and independently anchored expiry."""
    c,v=write['command'],write['response'];p=c['params']
    target=[n for n in v['result']['network'] if n['method']=='POST' and n['path']=='/ut/game/fc27/auctionhouse'] if v else []
    observed_post=(reconciled and v and v['result']['error']=='ambiguous_network' and len(target)==1 and
        target[0]['status']==200 and target[0]['session_header_present'] and
        all(n['method']=='GET' or n is target[0] for n in v['result']['network']))
    need(c['operation']=='list' and v and (v['result']['success'] or observed_post),'listing_not_successful')
    need(p['buy_now_price']==stored_price and p['starting_bid']==previous_tick and p['duration']==3600,
         'listing_changed_stored_policy')
    need(before['command_id']==p['owned_read_id'] and before['coverage']['complete'] and
         caps['command_id']==p['caps_read_id'],'listing_native_preconditions_missing')
    recovered_fence=(reconciled and after['fences']['epoch']>c['fences']['epoch'])
    need(before['context']==caps['context']==after['context']==c['context'] and
         before['fences']==caps['fences']==c['fences'] and
         (after['fences']==c['fences'] or recovered_fence),'listing_context_changed')
    bounds=caps['result']['caps']
    need(bounds['definition_id']==p['definition_id'] and bounds['minimum']<=p['starting_bid']<
         p['buy_now_price']<=bounds['maximum'],'listing_native_caps_violated')
    owned=[a for a in before['result']['auctions'] if a['item']['item_id']==p['item_id'] and
           a['item']['definition_id']==p['definition_id'] and a['item']['untradeable'] is False and
           a['item']['last_sale_price']==p['paid'] and a['trade_state']=='inactive' and a['current_bid']==0]
    need(len(owned)==1,'listing_exact_owned_paid_missing')
    need(after['command_id'] not in {c['id'],before['command_id'],caps['command_id'],p['win_read_id']} and
         after['coverage']['complete'],'listing_independent_readback_missing')
    rows=[a for a in after['result']['auctions'] if a['item']['item_id']==p['item_id'] and
          a['item']['definition_id']==p['definition_id']]
    need(len(rows)==1,'listing_physical_identity_missing');a=rows[0]
    elapsed=(stamp(after['freshness']['network_at'])-stamp(started_at)).total_seconds()
    duration=a['expires']+elapsed
    need(a['trade_id'] not in {owned[0]['trade_id'],p['trade_id']} and a['trade_state']=='active' and
         a['starting_bid']==previous_tick and a['buy_now_price']==stored_price and 0<a['expires']<=3600 and
         elapsed>=0 and 3598<=duration<=3602+v['timing']['native_service_ms']/1000,'listing_duration_or_prices_unproven')
    return True


def bulk_proof(write, before, after, *, started_at=None,finished_at=None,recovery=False,effect_only=False):
    """Verify one bulk native write and an independent complete readback."""
    c,r=write['command'],write['response'];op=c['operation']
    target_path='/ut/game/fc27/trade/sold' if op=='clear_sold' else '/ut/game/fc27/auctionhouse/relist'
    targets=[n for n in r['result']['network'] if n['method'] in {'PUT','DELETE'}]
    observed_write=(effect_only and r['result']['error']=='bulk_contract_changed' and len(targets)==1 and
        targets[0]['method']==('DELETE' if op=='clear_sold' else 'PUT') and targets[0]['path']==target_path and
        targets[0]['status']==200 and targets[0].get('body_empty') is True and targets[0]['query']=={} and
        targets[0]['session_header_present'] and all(n['method']=='GET' or n is targets[0] for n in r['result']['network']))
    need(op in {'clear_sold','relist_all'} and (r['result']['success'] or observed_write),'bulk_not_successful')
    need(c['params']==parameters(before,op),'bulk_target_identity_mismatch')
    need(before['command_id']!=after['command_id'] and after['command_id']!=c['id'],'bulk_readback_not_independent')
    need(before['context']==after['context']==c['context'] and before['fences']==c['fences'] and
        (after['fences']==c['fences'] or recovery and after['fences']['epoch']>c['fences']['epoch']),'bulk_context_changed')
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
            observed_hour=b['expires']==3600
            if started_at and finished_at:
                at=stamp(after['freshness']['network_at'])
                observed_hour=(0<b['expires']<=3600 and at>=stamp(finished_at) and
                    b['expires']+(at-stamp(started_at)).total_seconds()>=3598 and
                    b['expires']+(at-stamp(finished_at)).total_seconds()<=3602)
            need(b['trade_id'] not in {x['trade_id'] for x in old.values()} and b['trade_state']=='active'
                and b['current_bid']==0 and observed_hour,'relist_duration_or_trade_unproven')
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
        if v is not None:
            parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
            need(r['counted_requests']==v['freshness']['request_count'],'native_fanout_miscounted')
        else:
            need(r['state']=='UNKNOWN' and r['counted_requests']>=(0 if c['operation'] in LOCAL_OPERATIONS else 16),
                 'unaccounted_unknown_delivery')
        need(c['context']==export['context'],'native_scope_changed')
        need(r['measured']['queue_ms']>=0 and r['measured']['roundtrip_ms']>=0,'unmeasured_native_work')
        ids[cid]=r
        reasons[cid]=v['result'].get('error') if v else 'UNKNOWN_DELIVERY'
    ready=[r for r in native if r['kind']=='BROKER_READY']
    need(len(ready)==1,'multiple_brokers_in_capture')
    good=[r for r in captures if r['response'] and r['response']['result']['success']]
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
    if ids and set(ids)<=set(work) and all(work[cid]['state'] in {'DONE','UNKNOWN'} for cid in ids):
        mark('durable_state',*ids)
    if {r['pid'] for r in launched}==set(exit_by_pid) and stop['remaining_processes']==[] and stop['verified_process_exit']:
        mark('all_run_processes_stopped',stop['seq'])
    mark('append_only_evidence',supervisor[-1]['evidence_sha256'],native[-1]['evidence_sha256'])
    failures=[r for r in captures if not r['response'] or not r['response']['result']['success']]
    if failures and any(r['kind']=='DISPATCH_STOP' for r in native) and any(r['kind']=='STOP_REQUESTED' for r in supervisor):
        mark('failure_reported',*[r['command']['id'] for r in failures])
    elif not failures:
        mark('failure_reported',stop['seq'])

    def response(cid,operation=None):
        r=ids.get(cid)
        if not r or not r['response'] or not r['response']['result']['success'] or (operation and r['command']['operation']!=operation):
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
                timing=work[c['id']]
                after=next((x for x in candidates if _valid_bulk(r,before,x,started_at=timing['started'],
                    finished_at=timing['finished'])),None)
                need(after is not None,'no_bulk_independent_proof')
                mark('independent_maintenance_readbacks',c['id'],before['command_id'],after['command_id'])
                if op=='clear_sold':mark('sold_one_call_clear',c['id'])
                else:
                    mark('expired_one_call_relist',c['id']);mark('unchanged_relist_prices_duration',c['id'],after['command_id'])
            except ValueError:pass
    enrollments={e['trade_id']:e for e in events if e['kind']=='ENROLLMENT'}
    status_samples={}
    for trade,e in enrollments.items():
        identity=e['identity']
        samples=[(r,a) for r in good if r['command']['operation'] in {'watched','status'} and
            stamp(r['at'])>=stamp(e['at']) for a in r['response']['result']['auctions'] if
            physical(a)==(trade,identity['item_id'],identity['definition_id'])]
        status_samples[trade]=[dict(read_id=r['command']['id'],network_at=r['response']['freshness']['network_at'],
            state=a['trade_state'],bid_state=a['bid_state'],current_bid=a['current_bid'],expires=a['expires']) for r,a in samples]
        for r,a in samples:
            if a['trade_state']=='active' and a['bid_state']=='outbid' and a['expires']>0:
                mark('active_outbid',r['command']['id'])
        if len(samples)>=2:
            mark('natural_expiry_observations',*[r['command']['id'] for r,a in samples])
    if status_samples and all(status_samples.values()):
        mark('enrolled_status_coverage',*[s['read_id'] for samples in status_samples.values() for s in samples])
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
    for r in good:
        c=r['command'];p=c['params']
        if c['operation']!='list' or p['trade_id'] not in enrollments:continue
        try:
            policy=enrollments[p['trade_id']]
            owned=response(p['owned_read_id'],'transfer_list');caps=response(p['caps_read_id'],'caps')
            won=[e for e in events if e.get('reason')=='OWNED_WIN_VERIFIED' and e['trade_id']==p['trade_id'] and e['paid']==p['paid']]
            need(won,'listing_actual_win_missing')
            previous=tick('below',policy['quote']['resale_price'],r['at'])
            for candidate in good:
                if candidate['command']['operation']!='transfer_list' or stamp(candidate['at'])<=stamp(r['at']):continue
                after=candidate['response']
                if listing_proof(r,owned,caps,after,stored_price=policy['quote']['resale_price'],
                    previous_tick=previous,started_at=work[c['id']]['started']):
                    mark('stored_price_listing_3600',c['id'],after['command_id']);break
        except ValueError:pass
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
                won=response(e['win_read_id'],'watched');owned=response(e['owned_read_id'])
                need(owned['operation'] in {'unassigned','owned_item'},'independent_owned_source_missing')
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
    metrics['enrolled_status_samples']=status_samples
    starts=[e for e in events if e.get('actor')=='bidder' and e.get('reason')=='CYCLE_STARTED']
    metrics['bidder_start_intervals_seconds']=[(stamp(b['at'])-stamp(a['at'])).total_seconds() for a,b in zip(starts,starts[1:])]
    metrics['bidder_cycles_exceeding_25_seconds']=[e['elapsed_seconds'] for e in events if
        e.get('actor')=='bidder' and e.get('reason')=='CYCLE_FINISHED' and e.get('elapsed_seconds',0)>25]
    if metrics['bidder_start_intervals_seconds']:
        mark('whole_queue_intervals',*[e['seq'] for e in starts])
    for urgent in export['native']:
        if urgent['role']!='bidder' or not urgent['started']:continue
        for waiting in export['native']:
            if waiting['role']=='acquirer' and waiting['operation'] in {'search','caps','price_helpers'} and waiting['started'] and \
                    stamp(start['at'])<=stamp(waiting['enqueued'])<stamp(urgent['started'])<stamp(waiting['started']):
                mark('priority_under_load',urgent['command_id'],waiting['command_id'])
    predecessor=start['manifest'].get('predecessor')
    if predecessor and good:
        prior=load_evidence(Path(predecessor)/'native.jsonl')
        old=next((r for r in prior if r['kind']=='BROKER_READY'),None)
        if old and old['context']==ready[0]['context'] and old['fences']!=ready[0]['fences']:
            mark('restart_reconnect',str(predecessor),good[0]['command']['id'])
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
            error=r['response']['result']['error'] if r['response'] else 'UNKNOWN_DELIVERY',
            network=r['response']['result']['network'] if r['response'] else []) for r in failures])


def _valid_bulk(write,before,after,**timing):
    try:return bulk_proof(write,before,after,**timing)
    except (ValueError,KeyError,TypeError):return False
