"""Captured genuine management/rebid proof; never claims the four-hour interval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed
OUT=ROOT/'docs/research/005/stage10'
def read(name):return json.loads((OUT/name).read_text())
def lines(name):return [json.loads(l) for l in (OUT/name).read_text().splitlines()]


def audit(records,attempts,members):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_diagnostics(command_id,body);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        ids=[r['command']['id'] for r in records];need(len(ids)==len(set(ids)),'unique_native_deliveries')
        e=Evidence(db,ids,{})
        need(len(attempts)==len(members)==1 and attempts[0]['kind']=='rebid' and attempts[0]['state']=='ACKNOWLEDGED','one_current_management_intent')
        c,v=e.get(attempts[0]['id'],'bid');p=c['params'];target=p['target'];member=members[0]
        original=json.loads((OUT.parent/'stage09/probe-acquisition.json').read_text())['attempts'][0]
        need(original['body']['candidate']['target']==target==member['body']['target'] and member['state']=='ACTIVE','original_confirmed_member_only')
        need(p['amount']==p['minimum']==1600 and p['cap']==member['body']['cap']==original['body']['candidate']['cap']==4300,'unchanged_stored_bid_ceiling')
        receipt=v['receipt'];need(receipt['verdict']=='ACCEPTED' and receipt['wire_identity_matches'] and receipt['wire_amount_matches'] and receipt['wire_amount']==p['amount'],'matching_native_rebid_receipt')
        bc,bv,before=e.status(p['status_read_id'],target)
        need(before['trade_state']=='active' and before['bid_state']=='outbid' and before['current_bid']<p['amount'] and network_at(bc,bv)<network_at(c,v),'fresh_competition_required')
        confirmations=[]
        for cid in e.statuses.get(target['trade_id'],[]):
            sc,sv,row=e.status(cid,target)
            if network_at(sc,sv)>observed(c,v) and row['bid_state']=='highest' and row['current_bid']==p['amount']:confirmations.append(cid)
        need(confirmations,'independent_post_rebid_highest_read')
        return dict(rebid=c['id'],amount=p['amount'],cap=p['cap'],independent_confirmations=len(confirmations))
    finally:db.close()


def main():
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),read('attempts.json'),read('members.json')];result=audit(*args);negative=0
    for mode in ('receipt','ceiling','participation'):
        changed=deepcopy(args)
        if mode=='receipt':next(r for r in changed[0] if r['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='ceiling':changed[2][0]['body']['cap']=1500
        else:
            bid=next(r for r in changed[0] if r['command']['operation']=='bid')
            for r in changed[0]:
                if r['command']['operation']=='status_batch' and r['response']['network_at']>bid['response']['observed_at']:
                    for row in r['response']['auctions']:row['bid_state']='none'
        try:audit(*changed)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_management_proof_accepted_'+mode)
    s=read('snapshot.json');gen=s['runtime']['generation'];events=lines('events.jsonl')
    need(s['health']['status']=='healthy' and s['health']['generation']==gen and s['owner_held'] and s['supervisor_matches'] and s['child_matches'],'owned_semantic_snapshot')
    need(events[0]['kind']=='STARTED' and events[0]['generation']==gen and not any(e['kind'] in {'STOPPED','STOP_REQUESTED','STOP_FAILED','EXCEPTION'} for e in events),'uninterrupted_captured_runtime_prefix')
    phases=[]
    for e in events:
        if e['kind']=='WORKER' and e['message']['kind']=='progress':phases.append(e['message'].get('phase'))
    need('MANAGING' in phases and 'ACQUIRING' not in phases,'sequential_management_prefix')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_checks=negative,generation=gen,**result)))


CAPTURES={'snapshot.json','commands.jsonl','events.jsonl','attempts.json','members.json'}
if __name__=='__main__':main()
