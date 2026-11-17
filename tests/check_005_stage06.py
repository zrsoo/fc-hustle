"""Audit captured real bidding, win/move and monitor stop; never claim completion."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,payload
from fc_access.controller_v1.protocol import delivery_response
from fc_access.production_v1.resale import assess_effect
OUT=ROOT/'docs/research/005/stage06'


def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def lines(name):return [json.loads(l) for l in (OUT/name).read_text(encoding='utf-8').splitlines()]


def audit(records,attempts,move,stopped,scheduler):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_diagnostics(command_id,body);')
        for r in records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        need(len(records)==len({r['command']['id'] for r in records})==305,'unique_actual_deliveries')
        e=Evidence(db,[r['command']['id'] for r in records],{})
        for r in records:e.get(r['command']['id'])
        bids=[];rebids=[]
        for a in attempts['attempts']:
            c,v=e.get(a['id'],'bid');p=c['params'];rr=v['receipt'];t=p['target']
            need(a['body']['candidate']['target']==t and rr['verdict']=='ACCEPTED' and
                 rr['wire_identity_matches'] is True and rr['wire_amount_matches'] is True and
                 rr['wire_amount']==p['amount'] and rr['wire_trade_id']==t['trade_id'] and
                 p['amount']==p['minimum']<=p['cap'],'receipt_not_confirmation')
            pre_c,pre,row=e.status(p['status_read_id'],t)
            need(network_at(pre_c,pre)<network_at(c,v) and row['trade_state']=='active','fresh_status_before_dispatch')
            confirmations=[]
            for cid in e.statuses.get(t['trade_id'],[]):
                sc,sv=e.get(cid,'status_batch')
                if network_at(sc,sv)<=datetime.fromisoformat(v['observed_at']):continue
                _,_,r=e.status(cid,t)
                if r['bid_state'] in {'highest','outbid'}:confirmations.append(cid)
            need(confirmations,'independent_account_participation_missing')
            if a['kind']=='rebid':
                need(row['bid_state']=='outbid' and row['current_bid']<p['amount'],'genuine_competition_required')
                rebids.append(c['id'])
            else:
                need(a['kind']=='initial' and a['body']['candidate']['selection_remaining']>60,'original_initial_eligibility')
                bids.append(c['id'])
        need(len(bids)==len(rebids)==10,'ten_initial_and_ten_genuine_rebids')
        c=move['command'];p=c['params'];t={k:p[k] for k in ('trade_id','item_id','definition_id')}
        _,v=e.get(c['id'],'move')
        need(c==e.get(c['id'])[0] and move['state']=='CONFIRMED','actual_move_required')
        wc,win=e.get(p['win_read_id'],'watched')
        wins=[r for r in win['result']['auctions'] if r['trade_id']==t['trade_id'] and
              r['item']['item_id']==t['item_id'] and r['item']['definition_id']==t['definition_id']]
        need(len(wins)==1 and wins[0]['native_is_won'] is True and wins[0]['trade_state']=='closed' and
             wins[0]['bid_state']=='highest' and wins[0]['current_bid']==p['paid']==3100 and wins[0]['expires']<=0,'real_paid_terminal_win')
        need(any(a['id'] in rebids and a['body']['candidate']['target']==t and a['body']['params']['amount']==p['paid'] for a in attempts['attempts']),
             'paid_cost_must_be_our_native_bid')
        _,owned=e.get(p['owned_read_id'],'owned_item')
        need(owned==move['before'] and any(i['item_id']==t['item_id'] and i['definition_id']==t['definition_id'] and
             i['last_sale_price']==p['paid'] and i['untradeable'] is False for i in owned['result']['items']),'exact_current_physical_ownership')
        after=move['proof']['after'];ac,av=e.get(after['command_id'],'transfer_list');need(av==after,'independent_move_inventory')
        unassigned=[uv for cid in e.operations.get('unassigned',[]) for uc,uv in [e.get(cid,'unassigned')]
                    if datetime.fromisoformat(move['completed_at'])<=network_at(uc,uv) and
                    network_at(uc,uv)<=network_at(ac,av)+timedelta(seconds=30)]
        need(any(assess_effect(c,after,uv,at=datetime.fromisoformat(move['dispatched_at']),
                 claimed=datetime.fromisoformat(move['dispatched_at']),completed=datetime.fromisoformat(move['completed_at']),
                 before=t['trade_id'])[0] for uv in unassigned),'native_move_effect_not_ack')
        later=[pv for cid in e.operations.get('transfer_list',[]) for pc,pv in [e.get(cid)]
               if network_at(pc,pv)>network_at(ac,av) and pv['coverage']['complete'] is True and
               not any(r['item']['item_id']==t['item_id'] for r in pv['result']['auctions'])]
        need(later and not e.operations.get('list') and len(e.operations.get('move',[]))==1,'missing_item_never_replayed_or_listed')
        need(stopped['state']=='STOPPED' and stopped['reason']=='OPERATIONAL_STOP' and
             stopped['semantic']['native_successes']==166 and all(stopped['semantic'][k]==0 for k in
             ('auth_failures','read_failures','write_failures','helper_failures','diagnostic_failures')),'honest_runtime_stop')
        reports=[r['data'] for r in scheduler if r['kind']=='operational_health']
        need([r['report']['status'] for r in reports]==['healthy','repair'] and
             reports[-1]['report']['diagnostic']=='RUNTIME_STATE_UNAVAILABLE' and reports[-1]['healthy_seconds']==0,'fault_resets_interval')
        stop=next(r['data']['result'] for r in scheduler if r['kind']=='operational_stop')
        need(stop['exit_code']==0 and json.loads(stop['stdout'])['status']=='stopped' and stop['seconds']<60,'bounded_scheduler_stop')
        return dict(initial_confirmed=len(bids),genuine_rebids=len(rebids),paid_win=3100,move_confirmed=True,
                    later_inventory_missing=True,resale_unproven=True,healthy_seconds=0)
    finally:db.close()


def main():
    seal=read('sealed-evidence.json')
    for r in seal['files']:
        need(r['path'] in CAPTURES and hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'immutable_capture_changed')
    need({r['path'] for r in seal['files']}==CAPTURES,'sealed_capture_scope')
    records,attempts,move,stopped,scheduler=lines('commands.jsonl'),read('attempts.json'),read('confirmed-move.json'),read('stopped-state.json'),read('scheduler-stop.json')
    result=audit(records,attempts,move,stopped,scheduler);negatives=0
    for mode in ('ack_only','wrong_paid_owner','false_move_readback','fault_counted_as_healthy'):
        r,a,m,s,q=deepcopy((records,attempts,move,stopped,scheduler))
        if mode=='ack_only':next(x for x in r if x['command']['operation']=='bid')['response']['receipt']['verdict']='UNCONFIRMED'
        elif mode=='wrong_paid_owner':m['before']['result']['items'][0]['last_sale_price']+=50
        elif mode=='false_move_readback':m['proof']['after']['result']['auctions']=[x for x in m['proof']['after']['result']['auctions'] if x['item']['item_id']!=m['command']['params']['item_id']]
        else:next(x for x in q if x['kind']=='operational_health' and x['data']['report']['status']=='repair')['data']['healthy_seconds']=14400
        try:audit(r,a,m,s,q)
        except (ValueError,KeyError):negatives+=1
        else:raise ValueError('corrupt_evidence_accepted_'+mode)
    rows=lines('win-read-01/checkpoint.jsonl');closed=read('win-read-01/result.json')
    need(rows[0]['max_mutations']==0 and closed['mutations']==closed['pending']==0 and closed['service_stopped'] is True and
         closed['reserved_commands']==4 and closed['reason']=='FAILED_NATIVE_READ','consumed_readonly_scope')
    native=[x for x in rows if x['kind']=='NATIVE_RESULT']
    for r in native:
        c,v=r['command'],r['response'];delivery_response(v,c,now=datetime.fromisoformat(v['observed_at'] if c['schema']==4 else v['freshness']['observed_at']))
    need([r['command']['operation'] for r in native]==['watched','transfer_list','unassigned','status_batch'] and
         sum(len(payload(r['command'],r['response'])['network']) for r in native)==3 and
         native[-1]['response']['error']=='known_identity_unavailable','local_selector_refusal_not_ea_failure')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_checks=negatives,**result)))


CAPTURES={'commands.jsonl','attempts.json','policy-batch.json','confirmed-acquisition.json','confirmed-move.json',
          'startup-reconciliation.json','startup-monitor.json','stopped-state.json','stopped-events.jsonl',
          'scheduler-stop.json','post-move-projection.json','file-sharing-experiment.json','native-move-contract.json',
          'native-inventory-contract.json','win-read-01/checkpoint.jsonl','win-read-01/result.json','win-read-01/diagnostics.json'}

if __name__=='__main__':main()
