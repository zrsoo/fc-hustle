"""Read-only audit of stopped generation, sold resale and finite refresh probe."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed,audit_maintenance

OUT=ROOT/'docs/research/005/stage09'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def lines(name):return [json.loads(l) for l in (OUT/name).read_text().splitlines()]


def audit(records,work,prior,probe,cohort):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_diagnostics(command_id,body); CREATE TABLE c4_work(id,state,dispatched_at,completed_at,proof);')
        for r in records+probe:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        for w in work:db.execute('INSERT INTO c4_work VALUES(?,?,?,?,?)',(w['command']['id'],w['state'],w['dispatched_at'],w['completed_at'],json.dumps(w['proof'])))
        ids=[r['command']['id'] for r in records+probe];need(len(ids)==len(set(ids)),'unique_deliveries')
        e=Evidence(db,ids,{})
        need(len(prior['targets'])==len(prior['members'])==8,'all_carried_members_required')
        for target,member in zip(prior['targets'],prior['members']):
            need(member['body']['target']==target and member['state']=='LOST','exact_durable_terminal_member')
            terminal=[e.status(cid,target)[2] for cid in e.statuses.get(target['trade_id'],[])]
            need(any(row['trade_state']=='closed' and row['expires']<=0 and row['bid_state']=='outbid' and row['native_is_won'] is False for row in terminal),'independent_terminal_loss')
        maintenance=audit_maintenance(e);need(maintenance['confirmed']==['clear_sold'],'genuine_eligible_sold_cleanup')
        clear=next(w['command'] for w in work if w['command']['operation']=='clear_sold')
        _,before=e.get(clear['params']['before_read_id'],'transfer_list')
        original=json.loads((OUT.parent/'stage08/work.json').read_text())
        listing=next(w for w in original if w['command']['operation']=='list');item=listing['command']['params']['item_id']
        listed=next(r for r in listing['proof']['after']['result']['auctions'] if r['item']['item_id']==item)
        sold=[r for r in before['result']['auctions'] if r['item']['item_id']==item]
        need(len(sold)==1 and sold[0]['trade_id']==listed['trade_id'] and sold[0]['trade_state']=='closed' and sold[0]['current_bid']==4300 and item in clear['params']['expected_item_ids'],'earlier_exact_resale_sold')
        denied=[r for r in records if r['command']['operation']=='bid'];need(len(denied)==3,'three_dispatched_failures')
        for r in denied:
            v=r['response'];receipt=v['receipt'];need(v['success'] is False and v['status']==403 and [n['status'] for n in v['network']]==[461] and receipt['native_error_code']==461 and receipt['verdict']=='UNCONFIRMED','layer_specific_denial_not_confirmation')
        bids=[r for r in probe if r['command']['operation']=='bid'];need(len(bids)==1,'finite_single_bid_probe')
        c,v=e.get(bids[0]['command']['id'],'bid');p=c['params'];t=p['target'];a=cohort['attempts'];need(len(a)==1 and a[0]['id']==c['id'] and a[0]['kind']=='initial','single_durable_initial')
        need(t not in [r['command']['params']['target'] for r in denied],'uncertain_target_not_replayed')
        need(v['receipt']['verdict']=='ACCEPTED' and v['receipt']['wire_identity_matches'] and v['receipt']['wire_amount_matches'] and v['receipt']['wire_amount']==p['amount']==700,'exact_native_receipt')
        batch=cohort['batches'][a[0]['batch_id']];bc,balance=e.get(batch['balance_read_id'],'balance');dc,discovery=e.get(batch['discovery']['command_id'],'search')
        cfg=batch['config'];candidate=a[0]['body']['candidate'];quote=candidate['quote']
        need(balance['credits']>cfg['entry_threshold']==40000 and cfg['request_spacing']==2 and cfg['cycle_target']==5 and dc['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000),'unchanged_admission_and_discovery')
        need(quote['completed'] and quote['status']=='COMPLETE' and p['amount']==p['minimum']<=p['cap']==candidate['cap']<=quote['max_affordable_bid'],'completed_profitable_pricing')
        sc,sv,row=e.status(p['status_read_id'],t)
        need(row['trade_state']=='active' and row['expires']-(network_at(c,v)-network_at(sc,sv)).total_seconds()>60,'fresh_eligible_bid')
        confirmed=[]
        for cid in e.statuses.get(t['trade_id'],[]):
            pc,pv,pr=e.status(cid,t)
            if network_at(pc,pv)>observed(c,v) and pr['bid_state'] in {'highest','outbid'}:confirmed.append(cid)
        need(confirmed,'independent_post_bid_participation')
        return dict(reconciled_losses=8,sold_resale_price=4300,maintenance='clear_sold',denied_bids=3,new_confirmed_bid=c['id'],amount=p['amount'])
    finally:db.close()


def main():
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),read('work.json'),read('prior-member-reconciliation.json'),lines('probe-commands.jsonl'),read('probe-acquisition.json')]
    result=audit(*args);negative=0
    for mode in ('loss','sold_price','receipt','confirmation'):
        changed=deepcopy(args)
        if mode=='loss':changed[2]['members'][0]['state']='WON_ACCOUNTED'
        elif mode=='sold_price':
            for r in changed[0]:
                if r['command']['operation']=='transfer_list':
                    for row in r['response']['result']['auctions']:
                        if row['item']['item_id']=='item:4fa51171b8d65f02a7e65198':row['current_bid']=1
        elif mode=='receipt':next(r for r in changed[3] if r['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        else:
            bid=next(r for r in changed[3] if r['command']['operation']=='bid')
            for r in changed[3]:
                if r['command']['operation']=='status_batch' and r['response']['network_at']>bid['response']['observed_at']:
                    for row in r['response']['auctions']:row['bid_state']='none'
        try:audit(*changed)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_evidence_accepted_'+mode)
    events=lines('events.jsonl');stopped=events[-1];need(stopped['kind']=='STOPPED' and stopped['reason']=='PERSISTENT_WRITE_FAILURE' and stopped['exit_code']==0 and stopped['forced'] is False,'prompt_cooperative_stop')
    failures=[e for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result' and e['message']['operation']=='bid']
    stop=next(e for e in events if e['kind']=='STOP_REQUESTED');need((observed_event(stop)-observed_event(failures[-1])).total_seconds()<=1,'stop_promptly_after_third_failure')
    state=read('post-probe-state.json');need(state['pending']==0 and len(state['prior_unknowns'])==9 and all(a['state']=='UNKNOWN' for a in state['prior_unknowns']),'failed_and_unsent_intents_preserved')
    probe=read('after-refresh-one-bid/result.json');need(probe['account_mutations']==1 and probe['service_stopped'] and probe['confirmed_members']==1,'finite_probe_closed')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_checks=negative,healthy_seconds=0,**result)))


def observed_event(event):
    from datetime import datetime
    return datetime.fromisoformat(event['at'])

CAPTURES={'commands.jsonl','events.jsonl','snapshot.json','work.json','prior-member-reconciliation.json','attempts.json','probe-commands.jsonl','probe-acquisition.json','post-probe-state.json','after-refresh-one-bid/checkpoint.jsonl','after-refresh-one-bid/result.json'}
if __name__=='__main__':main()
