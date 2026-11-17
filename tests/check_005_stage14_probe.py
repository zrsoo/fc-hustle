"""Retained one-bid integration proof; zero live operations."""
from copy import deepcopy
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed
from fc_access.controller_v1.watch_capacity import slots
OUT=ROOT/'docs/research/005/stage14'
CAPTURES={'probe-commands.jsonl','probe-acquisition.json','post-probe-state.json','one-bid-after-capacity-guard/checkpoint.jsonl','one-bid-after-capacity-guard/result.json'}
def audit(records,cohort):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for g in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(g)))
        ids=[r['command']['id'] for r in records];e=Evidence(db,ids,{})
        bids=e.operations.get('bid',[]);need(len(ids)==len(set(ids))==129 and len(bids)==1,'one_finite_new_bid')
        c,v=e.get(bids[0],'bid');p=c['params'];t=p['target'];need(p['amount']==950 and p['minimum']==950 and p['amount']<=p['cap'] and v['receipt']['verdict']=='ACCEPTED' and v['receipt']['wire_amount_matches'] and v['receipt']['wire_identity_matches'],'actual_profitable_native_receipt')
        b=cohort['batch'];cfg=b['config'];bc,balance=e.get(b['balance_read_id'],'balance');need(balance['credits']>cfg['entry_threshold']==40000 and cfg['request_spacing']==2 and cfg['cycle_target']==5,'unchanged_entry_policy')
        wc,w=e.get(b['watch_read_id'],'watched');need(slots(w)==b['watch_slots']==50,'live_watch_capacity_admission')
        need(len(cohort['attempts'])==1 and cohort['attempts'][0]['state']=='ACKNOWLEDGED','single_consumed_intent')
        dc,discovery=e.get(b['discovery']['command_id'],'search');need(dc['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000),'unchanged_discovery')
        a=cohort['attempts'][0]['body']['candidate'];need(a['selection_remaining']>60 and a['quote']['completed'] and a['quote']['status']=='COMPLETE' and a['cap']<=a['quote']['max_affordable_bid'],'fresh_exact_completed_profitable_quote')
        sc,sv,before=e.status(p['status_read_id'],t);need(before['trade_state']=='active' and before['current_bid']<p['amount'] and network_at(sc,sv)<network_at(c,v),'fresh_minimum_prerequisite')
        confirmed=[]
        for sid in e.statuses.get(t['trade_id'],[]):
            sc,sv,row=e.status(sid,t)
            if network_at(sc,sv)>observed(c,v) and row['bid_state']=='highest' and row['current_bid']==p['amount']:confirmed.append(sid)
        need(confirmed,'independent_exact_price_participation')
        return dict(command_id=c['id'],amount=p['amount'],target=t,confirmation=confirmed)
    finally:db.close()
def main():
    seal=json.loads((OUT/'probe-sealed-evidence.json').read_text());need({r['path'] for r in seal['files']}==CAPTURES,'probe_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'probe_capture_changed')
    args=[[json.loads(l) for l in (OUT/'probe-commands.jsonl').read_text().splitlines()],json.loads((OUT/'probe-acquisition.json').read_text())];result=audit(*args);negative=0
    for mode in ('receipt','confirmation','capacity'):
        changed=deepcopy(args)
        if mode=='receipt':next(r for r in changed[0] if r['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='capacity':changed[1]['batch']['watch_slots']=100
        else:
            for r in changed[0]:
                if r['command']['operation']=='status_batch':
                    for row in r['response']['auctions']:row['bid_state']='none'
        try:audit(*changed)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_probe_proof_accepted_'+mode)
    state=json.loads((OUT/'post-probe-state.json').read_text());need(state['pending']==0 and len(state['unknowns'])==62 and all(a['state']=='UNKNOWN' for a in state['unknowns']),'prior_unknowns_consumed')
    closed=json.loads((OUT/'one-bid-after-capacity-guard/result.json').read_text());need(closed['account_mutations']==1 and closed['confirmed_members']==1 and closed['pending']==0 and closed['service_stopped'],'finite_probe_safely_closed')
    return dict(status='ONE_BID_VERIFIED_OBJECTIVE_INCOMPLETE',negative_cases=negative,**result)
if __name__=='__main__':print(json.dumps(main()))
