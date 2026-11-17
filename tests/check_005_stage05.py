"""Audit real stopped-run failures, relist and fresh confirmed probe; no completion."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import hashlib
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.protocol import delivery_response
from validate_005_lifecycle import Evidence,audit_maintenance
OUT=ROOT/'docs/research/005/stage05'


def need(value,reason):
    if not value:raise ValueError(reason)


def read(name):return json.loads((OUT/name).read_text())
def lines(name):return [json.loads(s) for s in (OUT/name).read_text().splitlines()]
def content(c,v):return v if c['schema']==4 else v['result']
def tick(v):return datetime.fromisoformat(v['network_at'] if v['schema']==4 else v['freshness']['network_at'])


def maintenance(records,work):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_diagnostics(command_id,body); CREATE TABLE c4_work(id,body,state,dispatched_at,completed_at,proof);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        db.execute('INSERT INTO c4_work VALUES(?,?,?,?,?,?)',(work['command']['id'],json.dumps(work['command']),work['state'],work['dispatched_at'],work['completed_at'],json.dumps(work['proof'])))
        return audit_maintenance(Evidence(db,[r['command']['id'] for r in records],{}))
    finally:db.close()


def validate_probe(rows,result,diagnostics):
    need(rows[0]['max_initial_mutations']==1 and rows[0]['max_other_mutations']==0 and rows[-1]['kind']=='CLOSED' and rows[-1]['result']==result,'finite_consumed_scope')
    reserved=[r for r in rows if r['kind']=='RESERVED_BEFORE_DELIVERY'];results=[r for r in rows if r['kind']=='NATIVE_RESULT']
    need(len(reserved)==len(results)==len([r for r in rows if r['kind']=='SEMANTIC_RESULT'])==120 and len({r['command']['id'] for r in results})==120,'unique_complete_deliveries_and_monitoring')
    need(len([r for r in rows if r['kind']=='SEMANTIC_RESULT'])==120,'complete_monitor_callbacks')
    by_id={};ops={};network=[]
    for intent,outcome in zip(reserved,results):
        c,v=outcome['command'],outcome['response'];need(intent['command']==c and rows.index(intent)<rows.index(outcome),'intent_precedes_delivery')
        at=v['observed_at'] if c['schema']==4 else v['freshness']['observed_at'];delivery_response(v,c,now=datetime.fromisoformat(at))
        need(content(c,v)['success'] is True,'unsuccessful_operation_cannot_prove_success')
        need(c['context']==rows[0]['context'],'same_account_context')
        if c['schema']==2:need(v['freshness']['source']=='native','fixture_not_live')
        network+=content(c,v)['network'];by_id[c['id']]=outcome;ops.setdefault(c['operation'],[]).append(outcome)
    need(Counter(n['method'] for n in network)=={'GET':19,'PUT':1} and all(n['status']==200 and n['session_header_present'] is True for n in network),'actual_native_request_inventory')
    need(len(ops['balance'])==len(ops['bid'])==1 and ops['balance'][0]['response']['credits']>40000,'one_entry_balance_and_initial_bid')
    need(result['reserved_ea']==sum(r['reserved_ea'] for r in reserved)==21,'reservation_accounting')
    write=ops['bid'][0];c,v=write['command'],write['response'];p=c['params'];t=p['target'];receipt=v['receipt']
    need(receipt['verdict']=='ACCEPTED' and receipt['native_success'] and receipt['wire_identity_matches'] and receipt['wire_amount_matches'] and
         receipt['wire_amount']==p['amount']==p['minimum']==750 and receipt['wire_trade_id']==t['trade_id'],'matching_wire_native_receipt')
    selected=next(r for r in rows if r['kind']=='FRESH_SELECTION');candidate=next(a for a in selected['after'] if a['target']==t)
    need(candidate['selection_remaining']>60 and candidate['cap']==p['cap']==4200 and candidate['quote']['status']=='COMPLETE' and candidate['quote']['completed'],
         'unchanged_eligible_profitable_selection')
    pre=by_id[p['status_read_id']]['response'];index=next(i for i,x in enumerate(by_id[p['status_read_id']]['command']['params']['targets']) if x==t)
    ds=[r for group in diagnostics if group['command_id']==p['status_read_id'] for r in group['records'] if r['stage']=='WIRE_AUCTION' and r['detail']['target_index']==index]
    need(len(ds)==1 and all(ds[0]['detail'][k] is True for k in ('wire_ready','wire_target_found','wire_identity_matches','wire_callback_matches')) and
         ds[0]['detail']['wire_current_bid']==700,'owned_wire_and_callback_agree')
    post=ops['status_batch'][-1]['response']
    need(post['command_id']!=pre['command_id'] and tick(post)>datetime.fromisoformat(v['observed_at']) and
         any(r['trade_id']==t['trade_id'] and r['item']['item_id']==t['item_id'] and r['bid_state']=='highest' and r['current_bid']==750 for r in post['auctions']) and
         any(l['target']==t for l in post['links']),'independent_post_bid_confirmation')
    watch=next(r for r in rows if r['kind']=='INDEPENDENT_ACCOUNT_READBACK')['response']
    need(tick(watch)>tick(post) and any(r['trade_id']==t['trade_id'] and r['item']['item_id']==t['item_id'] and r['item']['definition_id']==t['definition_id'] and
         r['bid_state']=='highest' and r['current_bid']==750 for r in watch['auctions']),'personal_account_participation')
    need(result['confirmed_members']==1 and result['pending']==0 and result['service_stopped'] is True and result['semantic']['reason'] is None,'honest_stopped_probe_result')


def main():
    capture_names={'runtime-state.json','runtime-events.jsonl','commands.jsonl','maintenance-work.json','terminal-loss.json','failed-runtime-attempts.json','scheduler-run.json'}
    for window,extras in {'wire-read-01':[],'wire-read-02':['diagnostics-projection.json'],
        'wire-bid-01':['diagnostics-projection.json','unclaimed-proof.json'],'poll-read-01':['diagnostics.json'],
        'poll-read-02':['diagnostics.json'],'poll-bid-01':['diagnostics-projection.json']}.items():
        capture_names.update(window+'/'+name for name in ['checkpoint.jsonl','result.json',*extras])
    seal=read('sealed-evidence.json')
    need({r['path'] for r in seal['files']}==capture_names and len(seal['files'])==len(capture_names),'immutable_capture_seal_scope')
    for record in seal['files']:need(hashlib.sha256((OUT/record['path']).read_bytes()).hexdigest()==record['sha256'],'captured_evidence_changed')
    records=lines('commands.jsonl');state=read('runtime-state.json')
    need(state['state']=='STOPPED' and state['reason']=='PERSISTENT_WRITE_FAILURE' and state['semantic']['write_failures']==3,'semantic_failure_stopped_runtime')
    writes=[r for r in records if r['command']['operation']=='bid'];need(len(writes)==3,'stop_before_fourth_native_bid')
    for r in writes:
        v=r['response'];need(r['state']=='UNKNOWN' and v['success'] is False and v['status']==403 and v['network'][0]['status']==461 and v['receipt']['verdict']=='UNCONFIRMED','failures_not_promoted')
    attempts=read('failed-runtime-attempts.json');need(len(attempts)==10 and all(r['state']=='UNKNOWN' for r in attempts) and sum(r['native_command_present'] for r in attempts)==3 and sum(r['tombstone_count'] for r in attempts)==3,'three_dispatches_seven_unsent_consumed_intents')
    bulk=maintenance(records,read('maintenance-work.json'));need(bulk['confirmed']==['relist_all'],'genuine_native_relist')
    loss=read('terminal-loss.json');need(len(loss)==1 and loss[0]['body']['row']['trade_state']=='closed' and loss[0]['body']['row']['bid_state']=='outbid' and loss[0]['body']['row']['native_is_won'] is False,'old_confirmed_bid_terminal_loss')
    unclaimed=read('wire-bid-01/unclaimed-proof.json')
    need(unclaimed['command_state']=='UNKNOWN' and unclaimed['result_present']==unclaimed['tombstone_count']==unclaimed['diagnostic_records']==0 and {r['kind'] for r in unclaimed['events']}=={'INTENT','UNCERTAIN'},'unclaimed_is_not_a_native_bid_failure_or_success')
    rows,result,diags=lines('poll-bid-01/checkpoint.jsonl'),read('poll-bid-01/result.json'),read('poll-bid-01/diagnostics-projection.json')
    validate_probe(rows,result,diags);negatives=0
    for mode in ('ack_only','wire_mismatch','missing_callback','false_confirmation'):
        r,v,d=deepcopy(rows),deepcopy(result),deepcopy(diags)
        if mode=='ack_only':next(x for x in r if x['kind']=='NATIVE_RESULT' and x['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='wire_mismatch':
            for group in d:
                for record in group['records']:
                    if record['stage']=='WIRE_AUCTION':record['detail']['wire_callback_matches']=False
        elif mode=='missing_callback':r.remove(next(x for x in r if x['kind']=='SEMANTIC_RESULT'))
        else:v['confirmed_members']=0;r[-1]['result']=v
        try:validate_probe(r,v,d)
        except (ValueError,KeyError,IndexError):negatives+=1
        else:raise ValueError('negative_probe_accepted')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',failed_native_bids=3,unsent_consumed_intents=7,
        genuine_relist=True,old_confirmed_auction='LOST',new_confirmed_bid=750,negative_checks=negatives,healthy_seconds=0)))


if __name__=='__main__':main()
