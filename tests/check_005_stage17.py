"""Audit stopped genuine trading and isolated sharing reproduction, no live PASS."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,observed,network_at,at,bulk_effect,parameters
from fc_access.controller_v1.protocol import delivery_response
OUT=ROOT/'docs/research/005/stage17'
CAPTURES={'stopped-state.json','events.jsonl','commands.jsonl','journal.json','maintenance.json','sharing-reproduction.json'}

def audit(records,events,state,journal,work,reproduction):
    need(state['state']=='STOPPED' and state['reason']=='RUNTIME_STATE_FAILED' and state['generation']=='6c2549d24df0b1155c3b8de951412965','genuine_runtime_failure')
    need(events[-1]['kind']=='STOPPED' and events[-1]['reason']=='RUNTIME_STATE_FAILED' and events[-1]['exit_code']==0 and events[-1]['forced'] is False,'cooperative_owned_stop')
    need(not any(e['kind']=='RUNTIME_PUBLISH_FAILED' for e in events),'original_errno_was_not_retained')
    semantic=state['semantic'];need(semantic['native_successes']==179 and semantic['confirmed']==10 and semantic['reason'] is None,'native_health_at_local_fault')
    need(all(semantic[k]==0 for k in ('auth_failures','write_failures','read_failures','batch_failures','diagnostic_failures','missing_statuses','unconfirmed_attempts')),'no_fabricated_market_failure')
    ids=[r['command']['id'] for r in records];native=[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(ids==native and len(ids)==len(set(ids))==319,'complete_stopped_delivery_history')
    db=sqlite3.connect(':memory:');db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);')
    try:
        for r in records:
            c,v=r['command'],r['response'];delivery_response(v,c,now=observed(c,v))
            db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(v)))
            for d in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(d)))
        e=Evidence(db,ids,{})
        initials=[];rebids=[]
        for attempt in journal['attempts']:
            c,v=e.get(attempt['id'],'bid');p=c['params'];receipt=v['receipt'];target=p['target']
            need(attempt['state']=='ACKNOWLEDGED' and receipt['verdict']=='ACCEPTED' and receipt['wire_identity_matches'] and receipt['wire_amount_matches'] and receipt['wire_amount']==p['amount'],'matching_actual_bid_receipt')
            sc,sv,before=e.status(p['status_read_id'],target)
            need(network_at(sc,sv)<network_at(c,v) and p['amount']==p['minimum']<=p['cap'],'fresh_profitable_bid_bound')
            if attempt['kind']=='rebid':need(before['trade_state']=='active' and before['bid_state']=='outbid' and before['current_bid']<p['amount'],'genuine_competition')
            confirmations=[]
            for sid in e.statuses.get(target['trade_id'],[]):
                ac,av,row=e.status(sid,target)
                if network_at(ac,av)>observed(c,v) and row['bid_state'] in {'highest','outbid'}:confirmations.append(sid)
            need(confirmations,'independent_participation_after_bid')
            (initials if attempt['kind']=='initial' else rebids).append(c['id'])
        need(len(initials)==len(rebids)==10,'ten_confirmed_initials_and_rebids')
        original=json.loads((OUT.parent/'stage16/acquisition.json').read_text())
        need(set(initials)=={a['id'] for a in original['attempts']},'same_proven_acquisition_cohort')
        need(len(work)==1 and work[0]['state']=='CONFIRMED','one_confirmed_maintenance')
        w=work[0];c,v=e.get(w['id'],'clear_sold');bc,before=e.get(c['params']['before_read_id'],'transfer_list');ac,after=e.get(w['proof']['after']['command_id'],'transfer_list')
        need(c==w['body'] and before==w['before_read'] and after==w['proof']['after'] and c['params']==parameters(before,'clear_sold'),'exact_native_bulk_inputs')
        proven,bad=bulk_effect(c,before,after,dispatched=at(w['dispatched_at']),completed=at(w['completed_at']))
        need(proven and not bad,'actual_bulk_readback_effect')
    finally:db.close()
    prior=json.loads((OUT.parent/'stage15/initial-unknowns.json').read_text())
    need({r['id'] for r in journal['prior_unknowns']}=={r['id'] for r in prior} and all(r['state']=='UNKNOWN' for r in journal['prior_unknowns']),'prior_unknown_ids_unchanged')
    need(journal['pending']==0 and journal['unknown_command_count']==77,'no_pending_dispatch_not_unknown_replay')
    need(reproduction['scope']=='ISOLATED_LOCAL_WINDOWS_FILE_SHARING_NOT_PRODUCTION_CAUSE_PROOF' and reproduction['winerror']==32 and reproduction['errno']==13 and .45<=reproduction['seconds']<1.5 and reproduction['original']==dict(version=1),'isolated_sharing_evidence_only')
    return dict(deliveries=len(ids),confirmed_initials=10,confirmed_rebids=10,maintenance='clear_sold',unknown_bids_preserved=len(prior),production_errno='NOT_RETAINED',healthy_seconds=0)

def main():
    read=lambda n:json.loads((OUT/n).read_text());lines=lambda n:[json.loads(l) for l in (OUT/n).read_text().splitlines()]
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),lines('events.jsonl'),read('stopped-state.json'),read('journal.json'),read('maintenance.json'),read('sharing-reproduction.json')]
    result=audit(*args);negative=0
    for mode in ('receipt','participation','stop','unknown','bulk_effect','production_cause'):
        x=deepcopy(args)
        if mode=='receipt':next(r for r in x[0] if r['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='participation':
            for r in x[0]:
                if r['command']['operation']=='status_batch':
                    for row in r['response']['auctions']:row['bid_state']='none'
        elif mode=='stop':x[1][-1]['forced']=True
        elif mode=='unknown':x[3]['prior_unknowns'][0]['state']='ACKNOWLEDGED'
        elif mode=='bulk_effect':x[4][0]['proof']['after']['result']['auctions']=[]
        else:x[5]['scope']='VERIFIED_PRODUCTION_CAUSE'
        try:audit(*x)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_evidence_accepted_'+mode)
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_cases=negative,**result)))

if __name__=='__main__':main()
