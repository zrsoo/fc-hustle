"""Read-only assessment of the explicitly resumed item-12 experiment.

Only this experiment's sealed process windows and independent recovery reads
can contribute proof. Component research, fixtures and mutable source hashes
never contribute. Failures stay visible across successful continuations.
"""
from pathlib import Path
import json
import sqlite3

from .final_assessment import audit,need,physical,listing_proof,bulk_proof
from .final_run import REQUIRED,load_evidence
from fc_access.production_v1.contracts import MUTATIONS,parse_response,stamp


def verify_destinations(checkpoint,captures):
    """Join projected captures to two independently retained durable destinations."""
    root=Path(checkpoint).parent/'state-backup'
    box=sqlite3.connect((root/'native.sqlite3').resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    transport=sqlite3.connect((root/'transport.sqlite3').resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    checked=0
    try:
        for capture in captures:
            c,v=capture['command'],capture['response']
            if capture.get('kind')=='DISPATCH_RESULT':
                row=box.execute('SELECT command,response FROM work WHERE id=?',(c['id'],)).fetchone()
                need(row is not None and json.loads(row[0])==c,'independent_mailbox_command_missing')
                need((json.loads(row[1]) if row[1] is not None else None)==v,'independent_mailbox_response_disagrees')
            if v is None:continue # Unknown delivery is never affirmative proof.
            row=transport.execute('SELECT body,result FROM commands WHERE id=?',(c['id'],)).fetchone()
            need(row is not None and json.loads(row[0])==c and row[1] is not None and json.loads(row[1])==v,
                'independent_native_destination_disagrees')
            checked+=1
    finally:box.close();transport.close()
    return checked


def audit_series(latest,checkpoint=None):
    paths=[];cursor=Path(latest).resolve()
    while True:
        need(cursor not in paths,'cyclic_resume_history');paths.append(cursor)
        rows=load_evidence(cursor/'supervisor.jsonl')
        opened=next(r for r in rows if r['kind']=='RUN_STARTED')
        prior=opened['manifest'].get('predecessor')
        if not prior:break
        cursor=Path(prior).resolve()
    paths.reverse()
    reports=[audit(p) for p in paths]
    supervisors=[load_evidence(p/'supervisor.jsonl') for p in paths]
    exports=[next(r['data'] for r in reversed(s) if r['kind']=='DURABLE_EXPORT') for s in supervisors]
    context=exports[0]['context']
    need(all(e['context']==context for e in exports),'series_context_changed')
    first=next(r for r in supervisors[0] if r['kind']=='RUN_STARTED')['at']
    last=supervisors[-1][-1]['at']
    final_export=exports[-1]
    runtime_unresolved=next(r['data']['unresolved_intents'] for r in supervisors[-1] if r['kind']=='STATUS_SNAPSHOT')
    if checkpoint:
        retained=load_evidence(checkpoint)
        final_export=next(r['data'] for r in retained if r['kind']=='DURABLE_EXPORT')
        need(final_export['context']==context,'checkpoint_context_changed')
        need(final_export['native']==exports[-1]['native'],'post_run_native_dispatch_detected')
        ended=retained[-1]
        need(ended['kind']=='RUN_STOPPED' and ended['remaining_processes']==[] and
            ended['verified_process_exit'],'checkpoint_processes_not_stopped')
        need(stamp(ended['at'])>=stamp(last),'checkpoint_precedes_run')
        last=ended['at']
        runtime_unresolved=next(r['data']['unresolved_intents'] for r in retained if r['kind']=='STATUS_SNAPSHOT')
    active=sum(r['live_window']['seconds'] for r in reports)
    need(active<=7200,'series_active_budget_exceeded')
    proof={}
    for path,r in zip(paths,reports):
        for criterion in r['criteria']:
            for name,refs in criterion['observed'].items():
                proof.setdefault(name,[]).append(dict(window=str(path),references=refs))
    # Critical prerequisites and process termination apply to every cohort.
    for name in (*(n for n in REQUIRED[0] if n!='concurrent_python_actors'),
                 'all_run_processes_stopped','append_only_evidence','failure_reported'):
        if any(not any(name in c['observed'] for c in r['criteria']) for r in reports):proof.pop(name,None)
    captures=[];read_log_refs=[]
    for path in paths:
        captures += [r for r in load_evidence(path/'native.jsonl') if r['kind']=='DISPATCH_RESULT']
    experiment_root=paths[0].parent
    for log in sorted(experiment_root.rglob('*.jsonl')):
        if log.name in {'native.jsonl','supervisor.jsonl'}:continue
        records=load_evidence(log)
        intents={r['command']['id']:r['command'] for r in records if r['kind']=='READ_INTENT'}
        for r in records:
            if r['kind']!='NATIVE_READ' or not first<=r['at']<=last:continue
            c,v=r['command'],r['response']
            if c['context']!=context:continue
            need(c['operation'] not in MUTATIONS and intents.get(c['id'])==c,'recovery_read_intent_missing')
            parse_response(v,c,source='native',now=stamp(v['freshness']['observed_at']))
            captures.append(dict(command=c,response=v,at=r['at'],role='reconciliation'))
            read_log_refs.append(dict(path=str(log),command_id=c['id']))
    ids={}
    for r in captures:
        cid=r['command']['id'];need(cid not in ids,'series_native_replay');ids[cid]=r
    destination_checks=verify_destinations(checkpoint,captures) if checkpoint else 0
    good=[r for r in captures if r['response'] and r['response']['result']['success']]
    def native(cid,op=None):
        r=ids.get(cid)
        need(r and r['response'] and r['response']['result']['success'] and
            (op is None or r['command']['operation']==op),'series_native_read_missing')
        return r['response']
    def mark(name,*refs):proof[name]=list(refs)
    events=[e for e in final_export['registry'] if first<=e['at']<=last]
    journal=[e for e in final_export['journal'] if first<=e['at']<=last]
    enroll={e['trade_id']:e for e in events if e['kind']=='ENROLLMENT'}
    bid_trades={r['command']['params']['trade_id'] for r in good if r['command']['operation']=='bid'}
    won_trades=set()
    for e in events:
        trade=e.get('trade_id')
        if trade not in enroll:continue
        if e.get('reason')=='OWNED_WIN_VERIFIED':
            try:
                w=native(e['win_read_id'],'watched');o=native(e['owned_read_id'])
                need(o['operation'] in {'unassigned','owned_item'} and w['command_id']!=o['command_id'] and
                    w['context']==o['context'] and w['fences']==o['fences'],'ownership_not_independent')
                identity=enroll[trade]['identity'];key=(trade,identity['item_id'],identity['definition_id'])
                need(e['identity']==identity,'won_identity_changed')
                a=next(a for a in w['result']['auctions'] if physical(a)==key)
                item=next(i for i in o['result']['items'] if (i['item_id'],i['definition_id'])==key[1:])
                need(a['trade_state']=='closed' and a['bid_state']=='highest' and a['expires']<=0 and
                    a['current_bid']==item['last_sale_price']==e['paid']>0 and item['untradeable'] is False,'won_paid_not_proven')
                need(any(r['command']['operation']=='bid' and
                    (r['command']['params']['trade_id'],r['command']['params']['item_id'],r['command']['params']['definition_id'])==key
                    and r['command']['params']['amount']==e['paid'] for r in good),'won_actual_final_bid_missing')
                mark('terminal_won',w['command_id'],o['command_id']);mark('exact_owned_paid',o['command_id'],e['seq'])
                won_trades.add(trade)
            except (ValueError,StopIteration):pass
    for e in journal:
        if e['reason']!='LOST_VERIFIED' or e['trade_id'] not in enroll or e['trade_id'] not in bid_trades:continue
        for r in good:
            if r['command']['operation'] not in {'watched','status'}:continue
            identity=enroll[e['trade_id']]['identity'];key=(e['trade_id'],identity['item_id'],identity['definition_id'])
            if any(physical(a)==key and a['bid_state']=='outbid' and a['trade_state'] in {'closed','expired'}
                and a['expires']<=0 for a in r['response']['result']['auctions']):
                mark('terminal_lost',r['command']['id'],e['seq'])
    work={w['command_id']:w for w in exports[-1]['native']}
    effect_readbacks=[]
    for r in captures:
        c=r['command'];p=c['params']
        if c['operation'] not in {'relist_all','clear_sold'} or not r['response']:continue
        try:
            before=native(p['before_read_id'],'transfer_list');timing=work[c['id']]
            for q in good:
                if q['command']['operation']!='transfer_list' or stamp(q['at'])<=stamp(r['at']):continue
                try:
                    bulk_proof(r,before,q['response'],started_at=timing['started'],finished_at=timing['finished'],
                        recovery=True,effect_only=True)
                    mark('independent_maintenance_readbacks',c['id'],before['command_id'],q['command']['id'])
                    if c['operation']=='clear_sold':mark('sold_one_call_clear',c['id'],q['command']['id'])
                    else:
                        mark('expired_one_call_relist',c['id'],q['command']['id'])
                        mark('unchanged_relist_prices_duration',c['id'],q['command']['id'])
                    effect_readbacks.append(dict(command_id=c['id'],readback=q['command']['id'],
                        callback_success=r['response']['result']['success'],runtime_intent_may_remain_unresolved=True))
                    break
                except ValueError:pass
        except (ValueError,KeyError):pass
    for r in captures:
        c=r['command'];p=c['params']
        if c['operation']!='list' or p['trade_id'] not in enroll:continue
        try:
            policy=enroll[p['trade_id']]['quote']['resale_price']
            before=native(p['owned_read_id'],'transfer_list');caps=native(p['caps_read_id'],'caps')
            ticks=[probe['price'] for q in good if q['command']['operation']=='price_helpers' and
                0<=(stamp(r['at'])-stamp(q['at'])).total_seconds()<=300 for probe in q['response']['result']['probes']
                if probe['direction']=='below' and probe['value']==policy]
            need(ticks and len(set(ticks))==1,'stored_native_listing_tick_missing')
            verified=any(e.get('kind')=='RESALE' and e.get('reason')=='VERIFIED' and e.get('command_id')==c['id'] for e in events)
            need(p['trade_id'] in won_trades and verified,'listing_not_reconciled')
            for q in good:
                if q['command']['operation']!='transfer_list' or stamp(q['at'])<=stamp(r['at']):continue
                try:
                    listing_proof(r,before,caps,q['response'],stored_price=policy,previous_tick=ticks[0],
                        started_at=work[c['id']]['started'],reconciled=verified)
                    mark('stored_price_listing_3600',c['id'],q['command']['id']);break
                except ValueError:pass
        except (ValueError,KeyError):pass
    # A rejected/unknown mutation is reconciled only through an independently
    # captured terminal or exact ownership outcome, never from a missing row.
    for r in captures:
        c,v=r['command'],r['response']
        if c['operation'] not in MUTATIONS or v and v['result']['success']:continue
        if any(e.get('command_id')==c['id'] and e['reason'] in {'WON_VERIFIED','LOST_VERIFIED'} for e in journal):
            name='terminal_won' if any(e.get('command_id')==c['id'] and e['reason']=='WON_VERIFIED' for e in journal) else 'terminal_lost'
            if name in proof:mark('unknown_reconciliation',c['id'],proof[name])
        if c['operation']=='list' and 'stored_price_listing_3600' in proof and proof['stored_price_listing_3600'][0]==c['id']:
            mark('unknown_reconciliation',c['id'],proof['stored_price_listing_3600'][1])
    for event in events:
        if event.get('kind')!='BULK_TRANSFER' or event.get('reason')!='OBSERVED_EFFECT_RECOVERED':continue
        try:
            cid=event['command_id'];write=ids[cid];c=write['command']
            before=native(c['params']['before_read_id'],'transfer_list')
            historical=native(event['historical_read_id'],'transfer_list');current=native(event['read_id'],'transfer_list')
            from fc_access.production_v1.bulk_recovery import verify_effect
            from fc_access.production_v1.bulk import classify
            verify_effect(c,write['response'],before,historical,started=work[cid]['started'],finished=work[cid]['finished'])
            classify(current)
            old={a['item']['item_id']:a for a in historical['result']['auctions']}
            new={a['item']['item_id']:a for a in current['result']['auctions']}
            need(current['command_id'] not in {cid,historical['command_id'],before['command_id']} and
                current['context']==c['context'] and stamp(current['freshness']['network_at'])>stamp(historical['freshness']['network_at']) and
                set(old)==set(new) and all(old[i]['item']['definition_id']==new[i]['item']['definition_id'] and
                    all(old[i][k]==new[i][k] for k in ('trade_id','starting_bid','buy_now_price')) for i in old),
                'independent_recovery_current_inventory_missing')
            mark('unknown_reconciliation',cid,historical['command_id'],current['command_id'],event['seq'])
        except (ValueError,KeyError):pass
    if runtime_unresolved:proof.pop('unknown_reconciliation',None)
    if all(n in proof for i in (1,2,3,4) for n in REQUIRED[i]) and not runtime_unresolved and destination_checks:
        mark('all_transaction_and_maintenance_branches',str(paths[-1]))
    else:proof.pop('all_transaction_and_maintenance_branches',None)
    criteria=[dict(index=i,status='PASS' if all(n in proof for n in names) else 'LIVE-UNVERIFIED',
        observed={n:proof[n] for n in names if n in proof},missing=[n for n in names if n not in proof]) for i,names in REQUIRED.items()]
    missing={n:'No independent native evidence chain witnessed in the bounded item-12 experiment'
        for c in criteria for n in c['missing']}
    if 'attributable_realized_profit' in missing:
        missing['attributable_realized_profit']='No attributable per-sale net receipt in the native adapter; gross sale, projected tax and aggregate funds are insufficient'
    balances=[r['response']['result']['credits'] for r in good if r['command']['operation']=='balance']
    capacities=[e['capacity']['total'] for e in events if e.get('reason')=='CAPACITY_CHECKED' and 'capacity' in e]
    capacities += [e['data']['capacity']['total'] for rows in supervisors for e in rows if e['kind']=='STATUS_SNAPSHOT']
    if checkpoint:capacities += [e['data']['capacity']['total'] for e in retained if e['kind']=='STATUS_SNAPSHOT']
    sold_observations=[]
    for e in events:
        if e.get('kind')!='SOLD_SETTLEMENT':continue
        try:
            before=native(e['read_id'],'transfer_list')
            from fc_access.production_v1.bulk import classify
            need(e['item']['item_id'] in classify(before)['sold'],'sold_observation_not_independent')
            row=next(a for a in before['result']['auctions'] if a['item']==e['item'] and a['trade_id']==e['sale_trade_id'])
            need(row['current_bid']==e['observed_gross_price'],'sold_gross_disagrees')
            sold_observations.append(dict(read_id=e['read_id'],item_id=e['item']['item_id'],
                definition_id=e['item']['definition_id'],sale_trade_id=e['sale_trade_id'],
                observed_gross_price=row['current_bid'],actual_settled_proceeds=None,realized_profit=None))
        except (ValueError,KeyError,StopIteration):pass
    return dict(schema=1,task='002-12',status='FULL PASS' if not missing else 'PARTIAL/NOT FULL PASS',
        criteria=criteria,unverified=missing,windows=[dict(path=str(p),**r['live_window']) for p,r in zip(paths,reports)],
        metrics=dict(active_seconds=active,elapsed_seconds=(stamp(last)-stamp(first)).total_seconds(),
            native_commands=len(ids),mutations=sum(r['command']['operation'] in MUTATIONS for r in captures),
            enrolled_in_experiment=len(enroll),actual_50_auction_sample=any(
                len({a['trade_id'] for a in r['response']['result']['auctions'] if a['trade_id'] in bid_trades})>=50
                for r in good if r['command']['operation'] in {'watched','status'}),
            native_requests=sum(r['response']['freshness']['request_count'] for r in captures if r['response']),
            independent_recovery_reads=read_log_refs,
            effect_readbacks=effect_readbacks,runtime_unresolved_intents=runtime_unresolved,
            independently_matched_destination_records=destination_checks,
            observed_native_credit_range=[min(balances),max(balances)] if balances else None,
            maximum_observed_pipeline_slots=max(capacities) if capacities else None,
            observed_sales_without_net_receipt=sold_observations,
            per_window=[dict(window=str(p),metrics=r['metrics']) for p,r in zip(paths,reports)]),
        failures=[dict(window=str(p),**f) for p,r in zip(paths,reports) for f in r['failures']])
