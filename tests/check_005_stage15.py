"""Independent stopped-run, exact native cleanup and preserved-unknown audit."""
from copy import deepcopy
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,observed,network_at,audit_lost_cleanup,at
from fc_access.controller_v1.protocol import delivery_response
OUT=ROOT/'docs/research/005/stage15'
def read(n):return json.loads((OUT/n).read_text())
def lines(n):return [json.loads(l) for l in (OUT/n).read_text().splitlines()]

def database(records,work=()):
    db=sqlite3.connect(':memory:');db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);CREATE TABLE c4_work(id,state,dispatched_at,completed_at,proof);')
    for r in records:
        c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
        for g in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(g)))
    for w in work:db.execute('INSERT INTO c4_work VALUES(?,?,?,?,?)',(w['id'],w['state'],w['dispatched_at'],w['completed_at'],json.dumps(w['proof']) if w['proof'] else None))
    return db

def stopped(records,events,state,journal):
    ids=[r['command']['id'] for r in records];delivered=[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(ids==delivered and len(ids)==len(set(ids))==110,'entire_stopped_run')
    need(state['state']=='STOPPED' and state['reason']=='OPERATIONAL_STOP' and events[-1]['kind']=='STOPPED' and events[-1]['forced'] is False and events[-1]['exit_code']==0,'owned_cooperative_repair_stop')
    db=database(records)
    try:
        e=Evidence(db,ids,{})
        for r in records:e.get(r['command']['id'])
        target=dict(trade_id='trade:a2c4ba61fc42b8324ee9f1a4',item_id='item:8aef7859641834fa53d09a96',definition_id=246420)
        c,v,row=e.status('a5aa375426bd40e3778a95af1cee81ef',target)
        need(row['trade_state']=='closed' and row['bid_state']=='outbid' and row['native_is_won'] is False and row['current_bid']==1900 and row['expires']<=0,'genuine950_terminal_loss')
        need(dict(journal['attempts'])=={'ACKNOWLEDGED':244,'UNKNOWN':62} and dict(journal['members'])=={'LOST':68,'WON_ACCOUNTED':1} and journal['pending']==0,'unchanged_unknowns_and_settlement')
    finally:db.close()
    return dict(native_deliveries=110,terminal='LOST_AT_1900',healthy_seconds=0)

def cleanup(records,work,result,checkpoint,post):
    need({r['id'] for r in post['unknowns']}=={r['id'] for r in read('initial-unknowns.json')},'exact_prior_unknown_ids')
    need(len(post['unknowns'])==62 and all(v['state']=='UNKNOWN' for v in post['unknowns']) and post['pending']==0,'all_prior_unknowns_protected')
    ids=[r['command']['id'] for r in records];need(len(ids)==len(set(ids)),'no_duplicate_cleanup_dispatch')
    reserved=[e for e in checkpoint if e['kind']=='RESERVED_BEFORE_DELIVERY'];need(len(reserved)==len(records)<=4 and result['reserved_commands']==len(records) and result['pending']==0 and result['service_stopped'],'finite_cleanup_closed')
    need(all(r['command']['operation'] in {'watched','clear_lost'} for r in records),'no_other_account_operations')
    db=database(records,work)
    try:
        e=Evidence(db,ids,{})
        for r in records:e.get(r['command']['id'])
        deletes=e.operations.get('clear_lost',[])
        if result['status']=='NO_ELIGIBLE_TARGETS':
            need(not deletes and result['account_mutations']==0,'no_synthetic_cleanup_success')
            return dict(live_cleanup_observed=False)
        need(result['status']=='NATIVE_CLEANUP_CONFIRMED' and len(deletes)==result['account_mutations']==1,'exact_one_native_delete')
        proof=audit_lost_cleanup(e);need(proof['confirmed']==deletes and not proof['resolved_unknown'],'native_ack_and_actual_readback')
        c,v=e.get(deletes[0]);trace=read('cleanup-dispatch-proof.json');ts=trace['tombstones']
        need(trace['command_id']==c['id'] and len(ts)==1 and ts[0]['command_id']==c['id'] and json.loads(ts[0]['action'])==[c['context']['account'],'clear_lost',sorted([[t['trade_id'],t['item_id'],t['definition_id']] for t in c['params']['targets']])],'individual_tombstone_before_dispatch')
        events=trace['events'];wanted=[x for x in events if x['kind'] in {'INTENT','CLAIMED','RESULT'}];need([x['kind'] for x in wanted]==['INTENT','CLAIMED','RESULT'] and wanted[0]['body']==c and wanted[2]['body']==v and wanted[0]['seq']<wanted[1]['seq']<wanted[2]['seq'],'durable_individual_dispatch_chain')
        need(at(trace['intended_at'])<=at(trace['dispatched_at'])<=network_at(c,v)<=observed(c,v)<=at(trace['completed_at']),'intent_before_exact_native_send')
        last=next(x['response'] for x in checkpoint if x['kind']=='INDEPENDENT_FINAL_READBACK');ac,av=e.get(last['command_id'],'watched');need(last==av and network_at(ac,av)>observed(c,v),'separate_final_account_observation')
        before=e.get(c['params']['before_read_id'],'watched')[1];identity=lambda r:(r['trade_id'],r['item']['item_id'],r['item']['definition_id']);targets={(t['trade_id'],t['item_id'],t['definition_id']) for t in c['params']['targets']}
        need({identity(r) for r in last['result']['auctions']}=={identity(r) for r in before['result']['auctions']}-targets,'final_exact_effect_and_unrelated_preservation')
    finally:db.close()
    need(len(post['unknowns'])==62 and all(v['state']=='UNKNOWN' for v in post['unknowns']) and post['pending']==0,'all_prior_unknowns_protected')
    return dict(live_cleanup_observed=True,removed_targets=len(targets),native_command=deletes[0])

def main():
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    base=[lines('commands.jsonl'),lines('events.jsonl'),read('stopped-state.json'),read('journal.json')];a=stopped(*base)
    live=[lines('cleanup-commands.jsonl'),read('cleanup-work.json'),read('live-cleanup-after-regressions/result.json'),lines('live-cleanup-after-regressions/checkpoint.jsonl'),read('post-cleanup-state.json')];b=cleanup(*live);negative=0
    for mode in ('loss','stop','delete_wire','unrelated','unknown'):
        x=deepcopy(base);y=deepcopy(live)
        if mode=='loss':next(r for r in x[0] if r['command']['id']=='a5aa375426bd40e3778a95af1cee81ef')['response']['auctions'][0]['native_is_won']=True
        elif mode=='stop':x[2]['reason']='HEARTBEAT_ONLY'
        elif mode=='unknown':y[4]['unknowns'][0]['state']='ACKNOWLEDGED'
        elif mode=='delete_wire':
            d=next((r for r in y[0] if r['command']['operation']=='clear_lost'),None)
            if d:d['response']['network'][0]['status']=403
            else:y[2]['status']='NATIVE_CLEANUP_CONFIRMED'
        else:
            final=next((e for e in y[3] if e['kind']=='INDEPENDENT_FINAL_READBACK'),None)
            if final:final['response']['result']['auctions'].append(deepcopy(x[0][0]['response'].get('auctions',[{}])[0]) if x[0][0]['response'].get('auctions') else {})
            else:y[2]['account_mutations']=1
        try:stopped(*x);cleanup(*y)
        except (ValueError,KeyError,TypeError):negative+=1
        else:raise ValueError('bad_capture_accepted_'+mode)
    aborted=read('live-cleanup/result.json');need(aborted['account_mutations']==aborted['reserved_commands']==aborted['pending']==0 and aborted['service_stopped'],'aborted_window_no_side_effect')
    original=read('historical-watch-projection.json');need(len(original['observations'])==2 and all(o['success'] and o['service_status']==200 and o['watched_count']==0 for o in original['observations']),'no_false_historical_capacity_claim')
    return dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_cases=negative,stopped=a,cleanup=b)
CAPTURES={'commands.jsonl','events.jsonl','stopped-state.json','journal.json','historical-watch-projection.json','initial-unknowns.json','cleanup-dispatch-proof.json','live-cleanup/checkpoint.jsonl','live-cleanup/result.json','cleanup-commands.jsonl','cleanup-work.json','post-cleanup-state.json'}|{'live-cleanup-after-regressions/'+n for n in ('checkpoint.jsonl','result.json','diagnostics.json')}
if __name__=='__main__':print(json.dumps(main()))
