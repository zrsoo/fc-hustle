"""Genuine restarted acquisition/management prefix, including isolated uncertainty."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed,audit_maintenance
OUT=ROOT/'docs/research/005/stage12'
def read(name):return json.loads((OUT/name).read_text())
def lines(name):return [json.loads(l) for l in (OUT/name).read_text().splitlines()]


def audit(records,cohort,work):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_diagnostics(command_id,body); CREATE TABLE c4_work(id,state,dispatched_at,completed_at,proof);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        for w in work:db.execute('INSERT INTO c4_work VALUES(?,?,?,?,?)',(w['command']['id'],w['state'],w['dispatched_at'],w['completed_at'],json.dumps(w['proof'])))
        ids=[r['command']['id'] for r in records];need(len(ids)==len(set(ids)),'unique_native_deliveries')
        e=Evidence(db,ids,{})
        initials=[a for a in cohort['attempts'] if a['kind']=='initial'];need(len(initials)==9<=10,'original_attempt_bound')
        confirmed=[];uncertain=[];rebids=[]
        for a in cohort['attempts']:
            c,v=e.get(a['id'],'bid');p=c['params'];target=p['target'];receipt=v['receipt']
            need(receipt['verdict']=='ACCEPTED' and receipt['wire_identity_matches'] and receipt['wire_amount_matches'] and receipt['wire_amount']==p['amount'],'native_receipt_required')
            sc,sv,before=e.status(p['status_read_id'],target)
            need(network_at(sc,sv)<network_at(c,v) and before['trade_state']=='active','fresh_bid_prerequisite')
            if a['kind']=='initial':
                batch=cohort['batches'][a['batch_id']];cfg=batch['config'];bc,balance=e.get(batch['balance_read_id'],'balance');dc,discovery=e.get(batch['discovery']['command_id'],'search')
                need(balance['credits']>cfg['entry_threshold']==40000 and cfg['request_spacing']==2 and cfg['cycle_target']==5 and dc['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000),'unchanged_admission_and_discovery')
                candidate=a['body']['candidate'];q=candidate['quote'];need(candidate['selection_remaining']>60 and before['expires']-(network_at(c,v)-network_at(sc,sv)).total_seconds()>60 and q['status']=='COMPLETE' and q['completed'] and p['amount']==p['minimum']<=p['cap']==candidate['cap']<=q['max_affordable_bid'],'unchanged_profitable_initial_policy')
            else:need(before['bid_state']=='outbid' and before['current_bid']<p['amount']==p['minimum']<=p['cap'],'genuine_profitable_competition')
            participation=[];none=[]
            for sid in e.statuses.get(target['trade_id'],[]):
                try:pc,pv,row=e.status(sid,target)
                except ValueError:continue # Failed reads grant no participation proof.
                if network_at(pc,pv)<=observed(c,v):continue
                if row['bid_state'] in {'highest','outbid'}:participation.append(sid)
                if row['bid_state']=='none':none.append(sid)
            if a['state']=='UNKNOWN':
                need(a['kind']=='initial' and not participation and none,'accepted_receipt_is_not_account_participation');uncertain.append(a['id'])
            else:
                need(a['state']=='ACKNOWLEDGED' and participation,'independent_confirmed_participation')
                (confirmed if a['kind']=='initial' else rebids).append(a['id'])
        need(len(confirmed)==8 and len(uncertain)==1 and rebids,'genuine_eight_confirmed_and_isolated_unknown')
        maintenance=audit_maintenance(e);need(maintenance['confirmed']==['relist_all'],'native_eligible_maintenance')
        return dict(confirmed_initials=8,unknown_initials=uncertain,confirmed_rebids=len(rebids),maintenance=maintenance['confirmed'])
    finally:db.close()


def main():
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),read('acquisition.json'),read('work.json')];result=audit(*args);negative=0
    for mode in ('receipt','confirmation','unknown_promoted','entry'):
        changed=deepcopy(args)
        if mode=='receipt':next(r for r in changed[0] if r['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='unknown_promoted':next(a for a in changed[1]['attempts'] if a['state']=='UNKNOWN')['state']='ACKNOWLEDGED'
        elif mode=='entry':
            for b in changed[1]['batches'].values():b['config']['entry_threshold']=0
        else:
            for r in changed[0]:
                if r['command']['operation']=='status_batch':
                    for row in r['response']['auctions']:row['bid_state']='none'
        try:audit(*changed)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('corrupt_evidence_accepted_'+mode)
    s=read('snapshot.json');events=lines('events.jsonl');gen=s['runtime']['generation']
    need(s['health']['status']=='healthy' and s['health']['generation']==gen and s['owner_held'] and s['supervisor_matches'] and s['child_matches'],'owned_semantic_health_snapshot')
    need(events[0]['kind']=='STARTED' and events[0]['generation']==gen and not any(e['kind'] in {'STOPPED','STOP_REQUESTED','STOP_FAILED','EXCEPTION'} for e in events),'uninterrupted_captured_runtime_prefix')
    phases={e['message'].get('phase') for e in events if e['kind']=='WORKER' and e['message']['kind']=='progress'}
    need({'ACQUIRING','MANAGING'}<=phases,'real_sequential_acquisition_handoff')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_checks=negative,generation=gen,**result)))


CAPTURES={'snapshot.json','commands.jsonl','events.jsonl','acquisition.json','work.json'}
if __name__=='__main__':main()
