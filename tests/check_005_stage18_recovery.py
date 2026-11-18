"""One genuinely new bid after ordinary login; no historical bid outcome guessed."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from check_005_stage15 import database
from validate_005_lifecycle import Evidence,need,network_at,observed
from fc_access.controller_v1.watch_capacity import slots
OUT=ROOT/'docs/research/005/stage18'
CAPTURES={'probe-commands.jsonl','probe-acquisition.json','after-normal-login-one-bid/checkpoint.jsonl','after-normal-login-one-bid/result.json'}

def audit(records,cohort,events,result):
    need(result['status']=='CONFIRMED_PARTICIPATION' and result['account_mutations']==result['confirmed_members']==1 and result['pending']==0 and result['service_stopped'],'one_finite_confirmed_new_bid')
    ids=[r['command']['id'] for r in records];need(len(ids)==len(set(ids))==result['commands']<=1024 and result['reserved_ea']<=96,'finite_unique_commands')
    need(ids==[r['command']['id'] for r in events if r['kind']=='NATIVE_RESULT'],'complete_captured_window')
    reserved=[r for r in events if r['kind']=='RESERVED_BEFORE_DELIVERY'];need([r['command']['id'] for r in reserved]==ids,'individual_intent_before_delivery')
    db=database(records)
    try:
        e=Evidence(db,ids,{});need(len(e.operations.get('bid',[]))==1 and not set(e.operations)&{'move','list','clear_sold','relist_all','clear_lost'},'only_one_allowed_mutation')
        c,v=e.get(e.operations['bid'][0],'bid');p=c['params'];target=p['target'];receipt=v['receipt']
        need(p['amount']==p['minimum']==800<=p['cap'] and receipt['verdict']=='ACCEPTED' and receipt['wire_identity_matches'] and receipt['wire_amount_matches'] and receipt['wire_amount']==800,'matching_native_bid')
        old=next(json.loads(l)['command'] for l in (OUT/'commands.jsonl').read_text().splitlines() if json.loads(l)['command']['operation']=='bid')
        need(c['context']==old['context'] and c['fences']['document']!=old['fences']['document'] and c['fences']['epoch']==35,'same_account_new_document')
        protected=cohort['protected_unknowns'];prior=json.loads((OUT/'journal.json').read_text())['all_unknowns']
        need({r['id'] for r in protected}=={r['id'] for r in prior} and len(protected)==66 and all(r['state']=='UNKNOWN' for r in protected) and target not in [r['target'] for r in protected],'no_unknown_replay_or_promotion')
        need(len(cohort['attempts'])==len(cohort['members'])==1 and cohort['attempts'][0]['id']==c['id'] and cohort['attempts'][0]['state']=='ACKNOWLEDGED','single_journaled_initial')
        b=cohort['batch']['body'];bc,balance=e.get(b['balance_read_id'],'balance');wc,watched=e.get(b['watch_read_id'],'watched');dc,discovery=e.get(b['discovery']['command_id'],'search')
        need(balance['credits']>b['config']['entry_threshold']==40000 and b['config']['request_spacing']==2 and b['config']['cycle_target']==5 and slots(watched)==b['watch_slots']==50,'original_entry_and_native_capacity')
        need(dc['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000),'original_discovery')
        q=cohort['attempts'][0]['body']['candidate'];need(q['target']==target and q['selection_remaining']>60 and q['quote']['completed'] and q['quote']['status']=='COMPLETE' and p['cap']==q['cap']<=q['quote']['max_affordable_bid'],'exact_profitable_version')
        sc,sv,before=e.status(p['status_read_id'],target);need(before['trade_state']=='active' and before['bid_state']=='none' and before['current_bid']<800 and network_at(sc,sv)<network_at(c,v),'fresh_unbid_prerequisite')
        confirmations=[]
        for sid in e.statuses.get(target['trade_id'],[]):
            ac,av,row=e.status(sid,target)
            if network_at(ac,av)>observed(c,v) and row['bid_state']=='highest' and row['current_bid']==800:confirmations.append(sid)
        need(confirmations,'independent_account_participation')
        final=next(r['response'] for r in events if r['kind']=='INDEPENDENT_ACCOUNT_READBACK');fc,fv=e.get(final['command_id'],'watched')
        need(final==fv and network_at(fc,fv)>observed(c,v) and any(r['trade_id']==target['trade_id'] and r['item']['item_id']==target['item_id'] and r['current_bid']==800 and r['bid_state']=='highest' for r in fv['auctions']),'separate_final_watched_confirmation')
        return dict(command_id=c['id'],amount=800,independent_status_reads=len(confirmations),protected_unknowns=66)
    finally:db.close()

def main():
    read=lambda n:json.loads((OUT/n).read_text());lines=lambda n:[json.loads(l) for l in (OUT/n).read_text().splitlines()]
    seal=read('probe-sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_probe_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_probe_changed')
    args=[lines('probe-commands.jsonl'),read('probe-acquisition.json'),lines('after-normal-login-one-bid/checkpoint.jsonl'),read('after-normal-login-one-bid/result.json')];result=audit(*args);negative=0
    for mode in ('receipt','participation','old_document','unknown','extra_mutation'):
        x=deepcopy(args)
        if mode in {'receipt','old_document'}:
            r=next(r for r in x[0] if r['command']['operation']=='bid')
            if mode=='receipt':r['response']['receipt']['verdict']='UNCONFIRMED'
            else:r['command']['fences']['document']='0'*32
        elif mode=='participation':
            for r in x[0]:
                if r['command']['operation']=='status_batch':
                    for row in r['response']['auctions']:row['bid_state']='none'
        elif mode=='unknown':x[1]['protected_unknowns'][0]['state']='ACKNOWLEDGED'
        else:x[3]['account_mutations']=2
        try:audit(*x)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_recovery_evidence_accepted_'+mode)
    print(json.dumps(dict(status='ONE_BID_RECOVERY_VERIFIED_OBJECTIVE_INCOMPLETE',negative_cases=negative,**result)))

if __name__=='__main__':main()
