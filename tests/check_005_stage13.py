"""Independently audit complete stopped run and genuine native read renewal."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed
from fc_access.controller_v1.protocol import delivery_response
from fc_access.controller_v1.semantic import native_summary,SemanticHealth
OUT=ROOT/'docs/research/005/stage13'
def read(n):return json.loads((OUT/n).read_text())
def lines(n):return [json.loads(l) for l in (OUT/n).read_text().splitlines()]
CAPTURES={'commands.jsonl','events.jsonl','attempts.json','snapshot.json','targets.json'}|{folder+'/'+name for folder in ('read-stopped-targets','read-after-native-renewal') for name in ('checkpoint.jsonl','diagnostics.json','result.json')}

def audit(records,events,attempts,state,first,renewed,diagnostics):
    ids=[r['command']['id'] for r in records]
    delivered=[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(len(ids)==len(set(ids))==980 and ids==delivered,'complete_unique_run')
    need(state['state']=='STOPPED' and state['reason']=='PERSISTENT_WRITE_FAILURE' and events[-1]['kind']=='STOPPED' and events[-1]['forced'] is False and events[-1]['exit_code']==0,'cooperative_stop')
    for r in records:delivery_response(r['response'],r['command'],now=observed(r['command'],r['response']))
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        e=Evidence(db,ids,{})
        acknowledged=[a for a in attempts if a['state']=='ACKNOWLEDGED'];unknown=[a for a in attempts if a['state']=='UNKNOWN']
        need(len(acknowledged)==67 and len(unknown)==7,'original_unknowns_preserved')
        initials=rebids=0
        for a in acknowledged:
            c,v=e.get(a['id'],'bid');target=c['params']['target'];need(v['receipt']['verdict']=='ACCEPTED','receipt_missing')
            confirmations=[]
            for sid in e.statuses.get(target['trade_id'],[]):
                sc,sv,row=e.status(sid,target)
                if network_at(sc,sv)>observed(c,v) and row['bid_state'] in {'highest','outbid'} and row['current_bid']>=c['params']['amount']:confirmations.append(sid)
            need(confirmations,'independent_exact_bid_confirmation_missing')
            if a['kind']=='initial':initials+=1
            else:rebids+=1
        need((initials,rebids)==(18,49),'actual_confirmed_trading_counts')
        race=next(r for r in records if r['command']['id']=='16e5a43b1ce8e00ce3e87024c23a266e')
        c,v=race['command'],race['response'];p=c['params'];sc,sv,before=e.status(p['status_read_id'],p['target'])
        need(before['current_bid']==800 and p['amount']==850 and p['cap']==3800 and v['receipt']['auction']['current_bid']==4500 and native_summary(c,v)['market_race'],'captured_competitive_race')
        after=[e.status(sid,p['target']) for sid in e.statuses[p['target']['trade_id']] if sid!=p['status_read_id']]
        need(any(network_at(ac,av)>observed(c,v) and ar['current_bid']==4500 and ar['bid_state']=='outbid' for ac,av,ar in after),'independent_competitor_price')
        failed=[r for r in records if r['command']['operation']=='bid' and r['response']['status']==403]
        need(len(failed)==2 and all(r['response']['network'][0]['status']==461 and r['response']['receipt']['verdict']=='UNCONFIRMED' and r['response']['receipt']['native_error_code']==461 for r in failed),'unexplained_native_denials_retained')
        last=next(e for e in reversed(events) if e['kind']=='WORKER' and e['message'].get('command_id')==failed[-1]['command']['id']);stop=next(e for e in events if e['kind']=='STOP_REQUESTED')
        need(0<=(datetime.fromisoformat(stop['at'])-datetime.fromisoformat(last['at'])).total_seconds()<1,'prompt_stop')
        s=SemanticHealth(clock=lambda:0)
        for r in records:s.observe(dict(kind='native_result',**native_summary(r['command'],r['response'])))
        need(s.reason is None and s.write_failures==2 and s.confirmed==0,'race_does_not_mask_two_actual_faults_or_invent_members')
    finally:db.close()
    initial_reads=[r for r in first if r.get('kind')=='NATIVE_RESULT']
    need(len(initial_reads)==4 and all(r['command']['operation'] in {'balance','watched','transfer_list','unassigned'} for r in initial_reads),'initial_window_readonly')
    for folder,count,expected in [('read-stopped-targets',4,'FAILED'),('read-after-native-renewal',5,'READS_VERIFIED')]:
        result=read(folder+'/result.json');need(result['status']==expected and result['mutations']==0 and result['pending']==0 and result['service_stopped'] and result['reserved_commands']==count,'finite_window_closed')
    failed=[r for r in first if r.get('kind')=='NATIVE_RESULT' and r['command']['operation']=='unassigned']
    need(len(failed)==1,'one_failed_read')
    f=failed[0];r=f['response']['result'];need(r['status']==401 and r['success'] is False and len(r['network'])==1 and r['network'][0]['status']==401,'failed_401_never_replayed_or_forged')
    renewal=[r for g in diagnostics for r in g['records'] if r['stage']=='NATIVE_RENEWAL_RESULT']
    need(len(renewal)==1 and renewal[0]['detail']=={'success':True},'native_renewal_result')
    fresh=[r for r in renewed if r.get('kind')=='NATIVE_RESULT'];need(len(fresh)==5 and all(r['command']['operation'] in {'balance','watched','transfer_list','unassigned','status_batch'} for r in fresh),'fresh_finite_reads_only')
    need(all((r['response'] if r['command']['schema']==4 else r['response']['result'])['success'] for r in fresh),'renewal_did_not_recover_fresh_reads')
    u=next(r for r in fresh if r['command']['operation']=='unassigned');need(u['command']['id']!=f['command']['id'] and datetime.fromisoformat(u['response']['freshness']['network_at'])>datetime.fromisoformat(renewal[0]['at']),'new_read_after_successful_renewal')
    targets=read('targets.json');status=fresh[-1]['response'];need(status['success'] and not status['missing'] and len(status['auctions'])==3,'fresh_exact_status')
    need(all(any(a['trade_id']==t['trade_id'] and a['item']['item_id']==t['item_id'] and a['bid_state']=='outbid' and a['trade_state']=='closed' and not a['native_is_won'] for a in status['auctions']) for t in targets),'failed_targets_genuine_terminal_losses')
    return dict(initials=initials,rebids=rebids,unknowns=len(unknown),native_denials=2,native_read_renewal='LIVE_CONFIRMED',objective_complete=False)

def main():
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'captured_evidence_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),lines('events.jsonl'),read('attempts.json'),read('snapshot.json'),lines('read-stopped-targets/checkpoint.jsonl'),lines('read-after-native-renewal/checkpoint.jsonl'),read('read-stopped-targets/diagnostics.json')]
    result=audit(*args);negative=0
    for mode in ('receipt','permission','stop','renewal'):
        changed=deepcopy(args)
        if mode=='receipt':next(r for r in changed[0] if r['command']['operation']=='bid' and r['response']['success'])['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='permission':next(r for r in changed[0] if r['command']['operation']=='bid' and r['response']['status']==403)['response']['network'][0]['status']=200
        elif mode=='stop':changed[3]['reason']='HEARTBEAT_ONLY'
        else:next(r for g in changed[6] for r in g['records'] if r['stage']=='NATIVE_RENEWAL_RESULT')['detail']['success']=False
        try:audit(*changed)
        except (ValueError,KeyError,TypeError):negative+=1
        else:raise ValueError('negative_case_accepted_'+mode)
    return dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',**result,negative_cases=negative)

if __name__=='__main__':print(json.dumps(main()))
