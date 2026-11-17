"""Historical move proof recovery audit; no current ownership or live resale claim."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import hashlib

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from fc_access.controller_v1.work import confirmed_move
from check_005_stage06 import main as verify_stage06
from fc_access.controller_v1.protocol import delivery_response


def audit(chain,records,attempts,mode=None):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_tombstones(command_id); CREATE TABLE c4_attempts(id,body); CREATE TABLE c4_work(body,before_read,state,at,dispatched_at,completed_at,proof);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
        for a in attempts['attempts']:
            db.execute('INSERT INTO c4_attempts VALUES(?,?)',(a['id'],json.dumps(a['body'])))
            if mode!='paid_bid':db.execute('INSERT INTO c4_tombstones VALUES(?)',(a['id'],))
        db.execute('INSERT INTO c4_tombstones VALUES(?)',(chain['body']['id'],))
        db.execute('INSERT INTO c4_work VALUES(?,?,?,?,?,?,?)',tuple(json.dumps(chain[k]) if k in {'body','before_read','proof'} else chain[k]
                   for k in ('body','before_read','state','at','dispatched_at','completed_at','proof')))
        c=chain['body'];target={k:c['params'][k] for k in ('trade_id','item_id','definition_id')};context=deepcopy(c['context'])
        if mode=='account':context['account']='f'*32
        result=confirmed_move(SimpleNamespace(db=db,peer=dict(context=context)),target)
        if result is None:raise ValueError('confirmed_move_not_recovered')
        if result['win']['command_id']!=c['params']['win_read_id']:raise ValueError('wrong_terminal_chain')
        return result
    finally:db.close()


def main():
    verify_stage06() # Immutable captured commands and native readbacks, not source integrity.
    root=ROOT/'docs/research/005'
    chain=json.loads((root/'stage07/retained-move-chain.json').read_text())
    records=[json.loads(l) for l in (root/'stage06/commands.jsonl').read_text().splitlines()]
    attempts=json.loads((root/'stage06/attempts.json').read_text());result=audit(chain,records,attempts);negatives=0
    for mode in ('account','paid_bid','unconfirmed','false_after','wrong_paid','chronology'):
        c=deepcopy(chain)
        if mode=='unconfirmed':c['state']='ACKNOWLEDGED'
        elif mode=='false_after':c['proof']['after']['result']['auctions']=[]
        elif mode=='wrong_paid':c['before_read']['result']['items'][0]['last_sale_price']+=50
        elif mode=='chronology':c['at']='2099-01-01T00:00:00Z'
        try:audit(c,records,attempts,mode)
        except ValueError:negatives+=1
        else:raise ValueError('invalid_retained_evidence_accepted_'+mode)
    out=root/'stage07';names={'retained-move-chain.json','public-selector-contract.json'}
    names.update(window+'/'+name for window in ('owned-read-01','owned-read-02','owned-read-03') for name in ('checkpoint.jsonl','result.json','diagnostics.json'))
    seal=json.loads((out/'sealed-evidence.json').read_text())
    if {r['path'] for r in seal['files']}!=names:raise ValueError('captured_scope_mismatch')
    for r in seal['files']:
        if hashlib.sha256((out/r['path']).read_bytes()).hexdigest()!=r['sha256']:raise ValueError('captured_evidence_changed')
    rows=[json.loads(l) for l in (out/'owned-read-03/checkpoint.jsonl').read_text().splitlines()]
    values=[r for r in rows if r['kind']=='NATIVE_RESULT'];closed=json.loads((out/'owned-read-03/result.json').read_text())
    if closed!={'status':'FAILED','mutations':0,'reason':'FAILED_NATIVE_READ','pending':0,'reserved_commands':5,'service_stopped':True}:
        raise ValueError('honest_read_window_result_required')
    if [r['command']['operation'] for r in values]!=['watched','transfer_list','unassigned','owned_item','status_batch']:
        raise ValueError('bounded_read_window_inventory_required')
    for r in values:
        c,v=r['command'],r['response'];at=v['observed_at'] if c['schema']==4 else v['freshness']['observed_at']
        delivery_response(v,c,now=datetime.fromisoformat(at))
        rvalue=v if c['schema']==4 else v['result']
        if c['schema']==2 and v['freshness']['source']!='native' or any(n['method']!='GET' or n['status']!=200 or n['session_header_present'] is not True or not n['host'].endswith('.ea.com') or '.test.' in n['host'] for n in rvalue['network']):
            raise ValueError('actual_native_reads_without_mutations_required')
    target={k:chain['body']['params'][k] for k in ('trade_id','item_id','definition_id')}
    pile,owned=values[1]['response'],values[3]['response']
    exact=lambda i:i['item_id']==target['item_id'] and i['definition_id']==target['definition_id'] and i['last_sale_price']==3100 and i['untradeable'] is False
    if not pile['coverage']['complete'] or sum(exact(r['item']) and r['trade_state']=='inactive' for r in pile['result']['auctions'])!=1 or not owned['result']['success'] or len(owned['result']['items'])!=1 or not exact(owned['result']['items'][0]):
        raise ValueError('fresh_exact_native_physical_ownership_required')
    if any(not r['response']['result']['success'] for r in values[1:4]) or not values[0]['response']['success']:
        raise ValueError('failed_read_cannot_establish_ownership')
    ds=json.loads((out/'owned-read-03/diagnostics.json').read_text())
    if not any(g['command_id']==values[3]['command']['id'] and any(r['detail'].get('item_pile')=='transfer' for r in g['records']) for g in ds):
        raise ValueError('native_transfer_pile_diagnostic_required')
    last=values[-1]['response']
    if last['success'] is not False or last['error']!='known_identity_unavailable' or last['network']:
        raise ValueError('old_auction_local_selector_failure_required')
    print(json.dumps(dict(status='RETAINED_MOVE_VERIFIED_OBJECTIVE_INCOMPLETE',paid=result['command']['params']['paid'],
        terminal_read_id=result['win']['command_id'],negative_checks=negatives,current_owned_location='NATIVE_TRANSFER_LIST_AND_ITEM_GET',
        live_listing=False,healthy_seconds=0)))


if __name__=='__main__':main()
