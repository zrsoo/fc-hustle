"""Explicit read-only recovery of a recorded bulk effect. Never dispatch a write.

The original failed response and incompatibility flag remain historical facts.
An immutable proof record permits only reconciliation, never native redispatch.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import sqlite3
from .contracts import ROUTES, parse_response, stamp
from .bulk import BulkTransfer, parameters, classify


def need(value, reason):
    if not value:raise ValueError(reason)


def record(path, cid):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:row=db.execute('SELECT body,state,result FROM commands WHERE id=?',(cid,)).fetchone()
    finally:db.close()
    need(row is not None and row[1] in {'ACKNOWLEDGED','UNKNOWN'} and row[2] is not None,'recorded_native_result_required')
    command,response=json.loads(row[0]),json.loads(row[2])
    parse_response(response,command,now=stamp(response['freshness']['observed_at']))
    if row[1]=='UNKNOWN':
        need(command['operation'] in {'clear_sold','relist_all'} and response['result']['success'] is False and
            response['result']['error']=='bulk_contract_changed','unknown_read_not_evidence')
    return command,response


def verify_effect(c, result, before, after, *, started, finished):
    """Independent wire and full physical-inventory proof, including elapsed hour."""
    need(c['operation'] in {'clear_sold','relist_all'},'bulk_only_recovery')
    need(result['command_id']==c['id'] and result['context']==c['context'] and result['fences']==c['fences'] and
        result['result']['success'] is False and result['result']['error']=='bulk_contract_changed',
        'recorded_bulk_failure_required')
    net=result['result']['network'];targets=[n for n in net if n['method']!='GET']
    need(len(targets)==1 and (targets[0]['method'],targets[0]['path'])==ROUTES[c['operation']] and
        all(n['status']==200 and n['session_header_present'] and n.get('body_empty') is True and
            n['query']=={} and n['host']==targets[0]['host'] for n in net) and
        all(n is targets[0] or n['path']==ROUTES['transfer_list'][1] for n in net),
        'single_authenticated_bulk_write_required')
    need(before['command_id']==c['params']['before_read_id'] and parameters(before,c['operation'])==c['params'],
        'immutable_preconditions_disagree')
    need(after['operation']=='transfer_list' and after['result']['success'] and
        after['command_id'] not in {c['id'],before['command_id']} and
        after['context']==before['context']==c['context'] and before['fences']==c['fences'] and
        (after['fences']==c['fences'] or after['fences']['epoch']>c['fences']['epoch']), 'independent_same_scope_read_required')
    classify(after)
    start,end,at=map(stamp,(started,finished,after['freshness']['network_at']))
    need(stamp(before['freshness']['network_at'])<=start<=end<=at,'invalid_dispatch_or_readback_interval')
    old={a['item']['item_id']:a for a in before['result']['auctions']}
    new={a['item']['item_id']:a for a in after['result']['auctions']}
    targets=set(c['params']['expected_item_ids']);clear=c['operation']=='clear_sold'
    need(targets and set(new)==(set(old)-targets if clear else set(old)),'inventory_membership_changed')
    elapsed=(at-stamp(before['freshness']['network_at'])).total_seconds();trades=[]
    for identity,b in new.items():
        a=old[identity]
        if not clear and identity in targets:
            need(a['item']==b['item'] and a['starting_bid']==b['starting_bid'] and a['buy_now_price']==b['buy_now_price'] and
                b['trade_id'] not in {x['trade_id'] for x in old.values()} and b['trade_state']=='active' and
                b['current_bid']==0 and b['bid_state']=='none' and 0<b['expires']<=3600 and
                b['expires']+(at-start).total_seconds()>=3598 and b['expires']+(at-end).total_seconds()<=3602,
                'relist_identity_price_or_hour_not_proven')
            trades.append(b['trade_id'])
        else:
            need(all(a[k]==b[k] for k in a if k!='expires') and
                (a['expires']==b['expires'] if a['expires']<=0 else 0<=a['expires']-b['expires']<=math.ceil(elapsed)+2),
                'unrelated_inventory_changed')
    need(len(trades)==len(set(trades)),'duplicate_relisted_trade')
    return True


def recover(f, cid, *, transport_path, post_read_id, mailbox_path):
    with BulkTransfer(f).lock():
        f.registry.check();j=f.journal
        row=j.db.execute('SELECT body,before_read,state,incompatible,at,completed_at FROM bulk_writes_v1 '
            'WHERE id=? AND scope=?',(cid,f.registry.scope)).fetchone()
        need(row is not None,'known_bulk_intent_required')
        if row[2]=='RECONCILED':return dict(status='ALREADY_RECONCILED',command_id=cid,native_mutations=0)
        need(row[2]=='UNKNOWN' and row[3]==1,'explicit_incompatible_intent_required')
        c=json.loads(row[0]);need(c['context']==f.adapter.context,'wrong_recovery_context')
        stored,result=record(transport_path,cid);need(stored==c,'recorded_command_disagrees')
        before_command,before=record(transport_path,c['params']['before_read_id'])
        need(before==json.loads(row[1]),'recorded_before_disagrees')
        post_command,after=record(transport_path,post_read_id)
        db=sqlite3.connect(Path(mailbox_path).resolve().as_uri()+'?mode=ro',uri=True)
        try:work=db.execute('SELECT command,response,started,finished,state FROM work WHERE id=?',(cid,)).fetchone()
        finally:db.close()
        need(work is not None and work[4]=='DONE' and json.loads(work[0])==c and json.loads(work[1])==result,
            'independent_mailbox_result_disagrees')
        need(stamp(row[4])<=stamp(work[2])<=stamp(work[3])<=stamp(row[5]),'mailbox_dispatch_outside_intent')
        verify_effect(c,result,before,after,started=work[2],finished=work[3])
        # A new complete native read is mandatory even though the historical
        # post-read already proves the hour and original exact physical effect.
        service=BulkTransfer(f);current=service.inventory()
        old={a['item']['item_id']:a for a in after['result']['auctions']}
        new={a['item']['item_id']:a for a in current['result']['auctions']}
        # Sold entries legitimately change tradeability and lastSalePrice. Those
        # are status/ownership observations, not the physical item/version identity.
        need(set(old)==set(new) and all(
            all(old[i]['item'][k]==new[i]['item'][k] for k in ('item_id','definition_id')) and
            all(old[i][k]==new[i][k] for k in ('trade_id','starting_bid','buy_now_price'))
            for i in old),'current_inventory_identity_or_prices_changed')
        proof=dict(schema=1,command=c,original_result=result,before_command=before_command,before=before,
            post_command=post_command,post=after,current=current,started=work[2],finished=work[3],
            reason='RECORDED_EFFECT_AND_FRESH_INVENTORY_VERIFIED',native_mutations=0)
        with j.transaction():
            f.registry.check()
            j.db.execute('CREATE TABLE IF NOT EXISTS bulk_recoveries_v1(id TEXT PRIMARY KEY,scope TEXT NOT NULL,proof TEXT NOT NULL)')
            for action in ('UPDATE','DELETE'):
                j.db.execute('CREATE TRIGGER IF NOT EXISTS bulk_recovery_no_'+action.lower()+' BEFORE '+action+
                    " ON bulk_recoveries_v1 BEGIN SELECT RAISE(ABORT,'immutable_bulk_recovery'); END;")
            need(j.db.execute('SELECT state,incompatible FROM bulk_writes_v1 WHERE id=?',(cid,)).fetchone()==('UNKNOWN',1),
                'recovery_state_changed')
            j.db.execute('INSERT INTO bulk_recoveries_v1 VALUES(?,?,?)',(cid,f.registry.scope,json.dumps(proof,sort_keys=True)))
            # Preserve incompatible=1 as original diagnostic provenance.
            j.db.execute("UPDATE bulk_writes_v1 SET state='RECONCILED' WHERE id=?",(cid,))
            service.observe(current)
            service.event('OBSERVED_EFFECT_RECOVERED',command_id=cid,operation=c['operation'],
                original_error='bulk_contract_changed',historical_read_id=post_read_id,
                read_id=current['command_id'],readback=deepcopy(current),native_mutations=0)
        return dict(status='RECONCILED',command_id=cid,read_id=current['command_id'],native_mutations=0)
