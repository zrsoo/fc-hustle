"""Audit native watch-slot boundary, true denial stop and protected intents."""
from copy import deepcopy
from datetime import datetime
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import need,observed,Evidence,network_at
from fc_access.controller_v1.protocol import delivery_response
from fc_access.controller_v1.watch_capacity import slots
OUT=ROOT/'docs/research/005/stage14'
def read(n):return json.loads((OUT/n).read_text())
def lines(n):return [json.loads(l) for l in (OUT/n).read_text().splitlines()]
CAPTURES={'commands.jsonl','events.jsonl','snapshot.json','attempts.json','undelivered-intents.json','public-watch-contract.json'}|{f+'/'+n for f in ('current-account','native-capacity','native-capacity-final') for n in ('checkpoint.jsonl','diagnostics.json','result.json')}

def audit(records,events,state,attempts,undelivered,live):
    ids=[r['command']['id'] for r in records];native=[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(len(ids)==len(set(ids))==2518 and ids==native,'entire_stopped_run')
    need(state['state']=='STOPPED' and state['reason']=='PERSISTENT_WRITE_FAILURE' and state['semantic']['native_successes']==1942 and state['semantic']['confirmed']==29 and events[-1]['kind']=='STOPPED' and events[-1]['forced'] is False and events[-1]['exit_code']==0,'real_cooperative_fault_stop')
    for r in records:delivery_response(r['response'],r['command'],now=observed(r['command'],r['response']))
    for r in records:
        value=r['response'] if r['command']['schema']==4 else r['response']['result']
        need(all('.test.' not in n['host'] and n['host'].endswith('.ea.com') for n in value['network']),'synthetic_not_live')
    db=sqlite3.connect(':memory:');db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);')
    try:
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        proof=Evidence(db,ids,{})
        future={}
        for r in records:
            c,v=r['command'],r['response']
            if c['operation']!='status_batch' or not v['success']:continue
            at=network_at(c,v)
            for row in v['auctions']:future.setdefault(row['trade_id'],[]).append((at,c['id'],row))
        for a in attempts:
            if a['state']!='ACKNOWLEDGED':continue
            c,v=proof.get(a['id'],'bid');target=c['params']['target'];confirmed=False
            need(v['receipt']['verdict']=='ACCEPTED','matching_receipt')
            for at,sid,row in future.get(target['trade_id'],[]):
                if at<=observed(c,v) or row['bid_state'] not in {'highest','outbid'} or row['current_bid']<c['params']['amount']:continue
                sc,sv,checked=proof.status(sid,target)
                need(checked==row,'post_bid_identity_link')
                confirmed=True;break
            need(confirmed,'independent_participation_required')
    finally:db.close()
    lookup={r['command']['id']:r for r in records};watch=[r for r in records if r['command']['operation']=='watched'][-1];rows=watch['response']['result']['auctions']
    need(len(rows)==47 and all(r['trade_state']=='closed' and r['bid_state']=='outbid' and r['native_is_won'] is False for r in rows),'47_occupied_closed_targets')
    following=[r for r in records if r['command']['operation']=='bid' and network_at(r['command'],r['response'])>network_at(watch['command'],watch['response'])]
    need(len(following)==6,'six_delivered_initials_at_boundary')
    for r in following[:3]:
        c,v=r['command'],r['response'];need(v['success'] and v['status']==200 and v['receipt']['verdict']=='ACCEPTED' and v['receipt']['before_bid_state']=='none','three_new_native_acceptances')
        need(next(a for a in attempts if a['id']==c['id'])['state']=='UNKNOWN','no_receipt_only_membership')
    for r in following[3:]:
        c,v=r['command'],r['response'];need(not v['success'] and v['status']==403 and len(v['network'])==1 and v['network'][0]['status']==461 and v['receipt']['native_error_code']==461 and v['receipt']['native_item_count']==0 and v['receipt']['verdict']=='UNCONFIRMED','three_real_native_denials')
    last=next(e for e in reversed(events) if e['kind']=='WORKER' and e['message'].get('command_id')==following[-1]['command']['id']);stop=next(e for e in events if e['kind']=='STOP_REQUESTED');need(0<=(datetime.fromisoformat(stop['at'])-datetime.fromisoformat(last['at'])).total_seconds()<1,'prompt_fault_stop')
    need(len(undelivered)==4 and all(r['state']=='UNKNOWN' and r['transport'] is None for r in undelivered),'unsent_intents_preserved')
    need(sum(a['state']=='UNKNOWN' for a in attempts)==9 and sum(a['state']=='ACKNOWLEDGED' and a['kind']=='initial' for a in attempts)==29 and sum(a['state']=='ACKNOWLEDGED' and a['kind']=='rebid' for a in attempts)==109,'truthful_attempt_counts')
    reads=[e for e in live if e['kind']=='NATIVE_RESULT'];need(len(reads)==6,'finite_readonly_window')
    need(all(e['command']['operation'] in {'balance','watched','transfer_list','unassigned','search','status_batch'} for e in reads),'no_live_probe_mutations')
    current=next(e for e in reads if e['command']['operation']=='watched');c,v=current['command'],current['response'];delivery_response(v,c,now=observed(c,v));need(c['schema']==2 and v['result']['success'] and slots(v)==50 and v['coverage']['watch_list']['capacity']==50,'current_native_capacity_not_guessed')
    need(c['context']==watch['command']['context'] and not v['result']['auctions'],'same_account_fresh_empty_watch')
    result=read('native-capacity-final/result.json');need(result['status']=='READS_VERIFIED' and result['mutations']==0 and result['pending']==0 and result['service_stopped'],'probe_closed')
    return dict(native_capacity=50,historical_occupied=47,new_receipts_without_confirmation=3,denials=3,accepted_initials_with_participation=29,accepted_rebids=109,protected_uncertain=13,healthy_seconds=0)

def main():
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),lines('events.jsonl'),read('snapshot.json'),read('attempts.json'),read('undelivered-intents.json'),lines('native-capacity-final/checkpoint.jsonl')];result=audit(*args);negative=0
    for mode in ('occupied','denial','promoted','capacity','unsent'):
        changed=deepcopy(args)
        if mode=='occupied':next(r for r in reversed(changed[0]) if r['command']['operation']=='watched')['response']['result']['auctions'].pop()
        elif mode=='denial':next(r for r in reversed(changed[0]) if r['command']['operation']=='bid')['response']['network'][0]['status']=200
        elif mode=='promoted':
            c=next(r for r in reversed(changed[0]) if r['command']['operation']=='bid' and r['response']['success'])['command'];next(a for a in changed[3] if a['id']==c['id'])['state']='ACKNOWLEDGED'
        elif mode=='capacity':next(e for e in changed[5] if e['kind']=='NATIVE_RESULT' and e['command']['operation']=='watched')['response']['coverage']['watch_list']['capacity']=100
        else:changed[4][0]['state']='ACKNOWLEDGED'
        try:audit(*changed)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('corrupt_evidence_accepted_'+mode)
    return dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_cases=negative,**result)
if __name__=='__main__':print(json.dumps(main()))
