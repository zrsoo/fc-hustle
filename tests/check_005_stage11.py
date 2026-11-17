"""Complete stopped native run and read-renewal regression audit; no account I/O."""
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
OUT=ROOT/'docs/research/005/stage11'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def lines(name):return [json.loads(l) for l in (OUT/name).read_text().splitlines()]


def audit_recovery(name):
    directory=OUT/name;seal=json.loads((directory/'sealed-evidence.json').read_text())
    need({r['path'] for r in seal['files']}=={'checkpoint.jsonl','result.json','diagnostics.json'},'readonly_capture_scope')
    for r in seal['files']:need(hashlib.sha256((directory/r['path']).read_bytes()).hexdigest()==r['sha256'],'readonly_captured_evidence_changed')
    events=[json.loads(l) for l in (directory/'checkpoint.jsonl').read_text().splitlines()]
    rows=[e for e in events if e['kind']=='NATIVE_RESULT'];result=json.loads((directory/'result.json').read_text());diagnostics=json.loads((directory/'diagnostics.json').read_text())
    need(result['status']=='READS_VERIFIED' and result['mutations']==0 and result['service_stopped'] and result['pending']==0 and result['reserved_commands']==len(rows)==6 and result['status_targets']==result['status_returned']==10 and result['status_missing']==0,'finite_genuine_readonly_recovery')
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);')
        for r in rows:db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(r['command']['id'],json.dumps(r['command']),'DONE',json.dumps(r['response'])))
        for r in diagnostics:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(r['command_id'],json.dumps(r['records'])))
        e=Evidence(db,[r['command']['id'] for r in rows],{})
        for r in rows:
            c,v=e.get(r['command']['id']);need(c['operation'] in {'balance','watched','transfer_list','unassigned','search','status_batch'},'no_readonly_window_mutations')
        for target in rows[-1]['command']['params']['targets']:e.status(rows[-1]['command']['id'],target)
    finally:db.close()
    return len(rows)


def audit(records,attempts,events,state):
    ids=[r['command']['id'] for r in records]
    delivered=[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(len(ids)==len(set(ids))==len(delivered) and set(ids)==set(delivered),'entire_run_unique_deliveries')
    need(state['state']=='STOPPED' and state['reason']=='PERSISTENT_AUTH_FAILURE' and events[-1]['kind']=='STOPPED' and events[-1]['exit_code']==0 and events[-1]['forced'] is False,'cooperative_auth_stop_required')
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_diagnostics(command_id,body);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        e=Evidence(db,ids,{});need(len(attempts)==4 and all(a['kind']=='rebid' and a['state']=='ACKNOWLEDGED' for a in attempts),'four_preserved_rebids')
        for a in attempts:
            c,v=e.get(a['id'],'bid');p=c['params'];r=v['receipt'];need(p['amount']==p['minimum']<=p['cap']==4300 and r['verdict']=='ACCEPTED' and r['wire_identity_matches'] and r['wire_amount_matches'],'native_receipt_and_original_ceiling')
            sc,sv,before=e.status(p['status_read_id'],p['target']);need(before['bid_state']=='outbid' and before['current_bid']<p['amount'] and network_at(sc,sv)<network_at(c,v),'fresh_native_competition')
            confirmed=[];lost=[]
            for sid in e.statuses.get(p['target']['trade_id'],[]):
                try:pc,pv,row=e.status(sid,p['target'])
                except ValueError:continue # Failed reads grant no participation or settlement proof.
                if network_at(pc,pv)>observed(c,v) and row['bid_state']=='highest' and row['current_bid']==p['amount']:confirmed.append(sid)
                if row['trade_state']=='closed' and row['bid_state']=='outbid' and row['expires']<=0 and row['native_is_won'] is False:lost.append(sid)
            need(confirmed and lost,'independent_rebid_and_terminal_loss')
        native=[r for r in records if r['command']['operation']!='price_helpers'];failed=[];unowned=[]
        for r in native:
            c,v=r['command'],r['response'];p=v if c['schema']==4 else v['result']
            delivery_response(v,c,now=observed(c,v))
            if p['success']:e.get(c['id'])
            else:
                if p['error']=='ambiguous_network' and not p['network']:
                    need(c['operation']=='status_batch' and r['state']=='UNKNOWN' and p['status']==200,'unowned_callback_is_not_fresh_proof')
                    unowned.append(c['id']);continue
                need(p['status']==401 and p['error']=='service_failed' and [n['status'] for n in p['network']]==[401] and all(n['session_header_present'] for n in p['network']),'coherent_owned_auth_failure')
                failed.append(r)
        need([r['command']['operation'] for r in failed]==['search','balance'],'exact_auth_transition')
        index=native.index(failed[0]);prior=native[index-1];need(prior['command']['operation']=='balance' and prior['response']['success'] and prior['response']['status']==200,'successful_balance_before_failure')
        # Failed legacy reads intentionally lack a successful-read network_at.
        # Correlate the owned response diagnostic, never invent freshness.
        response_times=[datetime.fromisoformat(d['at']) for group in failed[0]['diagnostics'] for d in group if d['stage']=='EA_RESPONSE' and d['detail'].get('status')==401]
        need(len(response_times)==1 and 0<(response_times[0]-network_at(prior['command'],prior['response'])).total_seconds()<5,'narrow_real_auth_transition')
        scope=prior['command'];need(all(r['command']['context']==scope['context'] and r['command']['fences']==scope['fences'] for r in failed),'no_account_document_or_owner_change_at_failure')
        last_failure=next(e for e in reversed(events) if e['kind']=='WORKER' and e['message'].get('command_id')==failed[-1]['command']['id'])
        stop=next(e for e in events if e['kind']=='STOP_REQUESTED');need(0<=(datetime.fromisoformat(stop['at'])-datetime.fromisoformat(last_failure['at'])).total_seconds()<1,'prompt_auth_stop')
        need(state['semantic']['auth_failures']==2 and state['semantic']['native_successes']==274,'semantic_failure_not_life_only')
        need(len(unowned)==1,'unusable_unowned_callback_retained')
        return dict(confirmed_rebids=4,terminal='LOST',failed_operations=['search','balance'],successful_native_operations=274,unowned_callbacks=unowned)
    finally:db.close()


def main():
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_evidence_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),read('attempts.json'),lines('events.jsonl'),read('stopped-state.json')];result=audit(*args);negative=0
    for mode in ('receipt','auth','stop','unowned_success'):
        changed=deepcopy(args)
        if mode=='receipt':next(r for r in changed[0] if r['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='auth':next(r for r in changed[0] if r['command']['operation']=='balance' and r['response']['status']==401)['response']['network'][0]['status']=200
        elif mode=='stop':changed[3]['reason']='HEARTBEAT_ONLY'
        else:
            row=next(r for r in changed[0] if r['response'].get('error')=='ambiguous_network')
            row['response']['success']=True;row['response']['error']=None;row['state']='DONE'
        try:audit(*changed)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('corrupt_evidence_accepted_'+mode)
    journal=read('safe-journal.json');need(journal['pending']==0 and dict(journal['attempts'])=={'ACKNOWLEDGED':38,'UNKNOWN':41} and dict(journal['members'])=={'LOST':20,'WON_ACCOUNTED':1},'safe_consumed_journal')
    red=json.loads((ROOT/'docs/research/005/checks/stage11/renewal-red/result.json').read_text());green=json.loads((ROOT/'docs/research/005/checks/stage11/renewal-green/result.json').read_text())
    need(red['exit_code']==1 and green['exit_code']==0,'renewal_red_green_required')
    need('renewals: 0' in (ROOT/'docs/research/005/checks/stage11/renewal-red/stderr.txt').read_text() and 'PASS 10 native renewal cases' in (ROOT/'docs/research/005/checks/stage11/renewal-green/stdout.txt').read_text(),'behavioral_renewal_evidence_required')
    baselines={name:audit_recovery(name) for name in ('read-after-repair','read-final')}
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_checks=negative,healthy_seconds=0,live_renewal_not_yet_proven=True,baseline_native_reads=baselines,**result)))


CAPTURES={'commands.jsonl','events.jsonl','stopped-state.json','attempts.json','safe-journal.json','public-native-renewal-contract.json','current-public-native-renewal-contract.json'}
if __name__=='__main__':main()
