"""Independent genuine acquisition/management prefix; no four-hour PASS."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed,payload
from fc_access.controller_v1.protocol import delivery_response
OUT=ROOT/'docs/research/005/stage16'
CAPTURES={'snapshot.json','acquisition.json','monitor-progress.json','commands.jsonl','events.jsonl'}

def audit(records,cohort,snapshot,events,monitor):
    s=snapshot;gen=s['runtime']['generation']
    need(s['health']['status']=='healthy' and s['health']['generation']==gen and s['owner_held'] and s['supervisor_matches'] and s['child_matches'],'owned_semantic_health')
    need(s['runtime']['semantic']['reason'] is None and s['runtime']['semantic']['batches']>=1,'successful_batch_not_heartbeat')
    need(events[0]['kind']=='STARTED' and events[0]['generation']==gen and not any(e['kind'] in {'STOPPED','STOP_REQUESTED','STOP_FAILED','EXCEPTION'} for e in events),'uninterrupted_prefix')
    ids=[r['command']['id'] for r in records]
    native=[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(ids==native and len(ids)==len(set(ids)),'complete_unique_native_delivery_prefix')
    phases={};phase=None
    for event in events:
        if event['kind']!='WORKER':continue
        m=event['message'];phase=m.get('phase',phase)
        if m['kind']=='native_result':phases[m['command_id']]=phase
    need({'ACQUIRING','MANAGING'}<=set(phases.values()),'sequential_handoff_not_observed')
    db=sqlite3.connect(':memory:');db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);')
    try:
        for r in records:
            c,v=r['command'],r['response'];delivery_response(v,c,now=observed(c,v))
            db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(v)))
            for d in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(d)))
        e=Evidence(db,ids,phases);initials=[];rebids=[];unknown=[]
        for batch_id,bid in cohort['batches'].items():
            b=bid['body'];need(b['config']['entry_threshold']==40000 and b['config']['request_spacing']==2 and b['config']['cycle_target']==5,'production_policy')
            bc,bv=e.get(b['balance_read_id'],'balance');dc,dv=e.get(b['discovery']['command_id'],'search')
            need(payload(bc,bv)['credits']>40000 and dc['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000),'real_batch_admission')
            count=sum(a['kind']=='initial' and a['batch_id']==batch_id for a in cohort['attempts'])
            need(0<count<=10 and b['selected_count']<=10 and b['watch_slots']>=count,'finite_capacity_admission')
        for a in cohort['attempts']:
            c,v=e.get(a['id'],'bid');p=c['params'];target=p['target'];receipt=v['receipt']
            need(receipt['verdict']=='ACCEPTED' and receipt['wire_identity_matches'] and receipt['wire_amount_matches'] and receipt['wire_amount']==p['amount'],'matching_native_receipt')
            sc,sv,before=e.status(p['status_read_id'],target)
            need(network_at(sc,sv)<network_at(c,v) and before['trade_state']=='active' and p['amount']==p['minimum']<=p['cap'],'fresh_bid_policy')
            if a['kind']=='initial':
                q=a['body']['candidate'];need(phases[a['id']]=='ACQUIRING' and q['selection_remaining']>60 and before['expires']-(network_at(c,v)-network_at(sc,sv)).total_seconds()>60 and q['quote']['completed'] is True and q['quote']['status']=='COMPLETE' and p['cap']==q['cap']<=q['quote']['max_affordable_bid'],'exact_profitable_initial')
            else:need(phases[a['id']]=='MANAGING' and before['bid_state']=='outbid' and before['current_bid']<p['amount'],'genuine_management_competition')
            confirmations=[]
            for sid in e.statuses.get(target['trade_id'],[]):
                try:ac,av,row=e.status(sid,target)
                except ValueError:continue
                if network_at(ac,av)>observed(c,v) and row['bid_state'] in {'highest','outbid'}:confirmations.append(sid)
            if a['state']=='UNKNOWN':unknown.append(a['id']);continue
            need(a['state']=='ACKNOWLEDGED' and confirmations,'independent_account_participation_required')
            (initials if a['kind']=='initial' else rebids).append(a['id'])
        need(initials,'confirmed_acquisition_required')
        management_reads=[cid for cid in e.operations.get('status_batch',[]) if phases[cid]=='MANAGING']
        need(management_reads,'independent_management_cycle_required')
        for cid in management_reads:e.get(cid,'status_batch')
        prior=json.loads((OUT.parent/'stage15/initial-unknowns.json').read_text())
        need({x['id'] for x in cohort['prior_unknowns']}=={x['id'] for x in prior} and all(x['state']=='UNKNOWN' for x in cohort['prior_unknowns']),'prior_unknowns_never_promoted')
        need(monitor['generation']==gen and monitor['faulted']==0,'scheduler_generation')
        states={r['id']:(r['state'],r['control']) for r in monitor['legacy']}
        need(states=={'obj-da182a175410':('PAUSED','pause'),'obj-fefda5e912eb':('COMPLETED',None)},'legacy_objectives_preserved')
        return dict(generation=gen,confirmed_initials=len(initials),confirmed_rebids=len(rebids),unknown_attempts=unknown,native_deliveries=len(ids),captured_healthy_seconds=monitor['healthy'])
    finally:db.close()

def main():
    read=lambda n:json.loads((OUT/n).read_text())
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'captured_only_seal_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'immutable_evidence_changed')
    lines=lambda n:[json.loads(l) for l in (OUT/n).read_text().splitlines()]
    args=[lines('commands.jsonl'),read('acquisition.json'),read('snapshot.json'),lines('events.jsonl'),read('monitor-progress.json')]
    result=audit(*args);negative=0
    for mode in ('receipt','confirmation','strategy','unknown','owner','stop'):
        x=deepcopy(args)
        if mode=='receipt':next(r for r in x[0] if r['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='confirmation':
            for r in x[0]:
                if r['command']['operation']=='status_batch':
                    for row in r['response']['auctions']:row['bid_state']='none'
        elif mode=='strategy':next(iter(x[1]['batches'].values()))['body']['config']['entry_threshold']=0
        elif mode=='unknown':x[1]['prior_unknowns'][0]['state']='ACKNOWLEDGED'
        elif mode=='owner':x[2]['owner_held']=False
        else:x[3].append(dict(kind='STOPPED'))
        try:audit(*x)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_prefix_accepted_'+mode)
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_cases=negative,**result)))

if __name__=='__main__':main()
