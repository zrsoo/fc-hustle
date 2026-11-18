"""Genuine native cleanup/relist followed by protected bid denial, not success."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from check_005_stage15 import database
from validate_005_lifecycle import Evidence,need,audit_lost_cleanup,audit_maintenance,observed,network_at
from fc_access.controller_v1.protocol import delivery_response
OUT=ROOT/'docs/research/005/stage18'
CAPTURES={'stopped-state.json','events.jsonl','commands.jsonl','work.json','journal.json','uncertain-targets.json'}

def audit(records,events,state,work,journal):
    need(state['state']=='STOPPED' and state['reason']=='PERSISTENT_WRITE_FAILURE' and state['semantic']['write_failures']==3 and state['semantic']['confirmed']==0,'prompt_semantic_stop')
    need(events[-1]['kind']=='STOPPED' and events[-1]['exit_code']==0 and events[-1]['forced'] is False and not any(e['kind']=='RUNTIME_PUBLISH_FAILED' for e in events),'cooperative_stop_not_snapshot_failure')
    ids=[r['command']['id'] for r in records];need(ids==[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result'] and len(ids)==len(set(ids)),'entire_unique_delivery_prefix')
    for r in records:delivery_response(r['response'],r['command'],now=observed(r['command'],r['response']))
    db=database(records,work)
    try:
        e=Evidence(db,ids,{})
        cleanup=audit_lost_cleanup(e);need(len(cleanup['confirmed'])==1 and not cleanup['resolved_unknown'],'genuine_native_cleanup_and_effect')
        cc,cv=e.get(cleanup['confirmed'][0],'clear_lost');original=json.loads((OUT.parent/'stage17/reconciliation-targets.json').read_text())
        key=lambda t:(t['trade_id'],t['item_id'],t['definition_id'])
        need({key(t) for t in cc['params']['targets']}=={key(t) for t in original},'exact_ten_original_lost_targets')
        maintenance=audit_maintenance(e);need('relist_all' in maintenance['confirmed'],'genuine_eligible_native_relist')
        after=next(w['proof']['after'] for w in work if w['body']['operation']=='clear_lost');ac,av=e.get(after['command_id'],'watched')
        need(av==after and av['result']['auctions']==[] and av['coverage']['watch_list']['capacity']==50,'empty_native_watchlist_before_denials')
        bids=[r for r in records if r['command']['operation']=='bid'];need(len(bids)==3,'three_delivered_denials')
        for r in bids:
            c,v=r['command'],r['response'];need(r['state']=='UNKNOWN' and v['success'] is False and v['status']==403 and v['error']=='ambiguous_network' and v['receipt']['native_error_code']==461 and v['receipt']['verdict']=='UNCONFIRMED' and [n['status'] for n in v['network']]==[461],'layer_specific_denial_not_fake_ack')
            need(network_at(ac,av)<network_at(c,v),'cleanup_before_bid')
            sc,sv,row=e.status(c['params']['status_read_id'],c['params']['target']);need(row['trade_state']=='active' and row['bid_state']=='none' and row['native_is_won'] is False and network_at(sc,sv)<network_at(c,v),'fresh_prebid_state_not_prior_membership')
    finally:db.close()
    attempts=journal['attempts'];need(len(attempts)==4 and all(a['state']=='UNKNOWN' for a in attempts),'all_uncertain_intents_consumed')
    need(len({a['id'] for a in attempts}-set(ids))==1,'fourth_intent_without_retained_transport_result')
    prior=json.loads((OUT.parent/'stage15/initial-unknowns.json').read_text())
    need({r['id'] for r in journal['prior_unknowns']}=={r['id'] for r in prior} and all(r['state']=='UNKNOWN' for r in journal['prior_unknowns']),'all_prior_unknowns_protected')
    need(len(journal['all_unknowns'])==66 and journal['pending']==0 and journal['members'].get('ACTIVE',0)==0 and journal['members']['LOST']==78,'no_unconfirmed_members_or_pending_dispatch')
    return dict(native_cleanup_targets=10,maintenance=maintenance['confirmed'],delivered_bid_denials=3,protected_unknown_bids=66,healthy_seconds=0)

def main():
    read=lambda n:json.loads((OUT/n).read_text());lines=lambda n:[json.loads(l) for l in (OUT/n).read_text().splitlines()]
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    args=[lines('commands.jsonl'),lines('events.jsonl'),read('stopped-state.json'),read('work.json'),read('journal.json')];result=audit(*args);negative=0
    for mode in ('wire','ack','cleanup','relist','unknown','stop'):
        x=deepcopy(args)
        if mode in {'wire','ack'}:
            r=next(r for r in x[0] if r['command']['operation']=='bid')
            if mode=='wire':r['response']['network'][0]['status']=200
            else:r['response']['receipt']['verdict']='ACCEPTED'
        elif mode=='cleanup':next(w for w in x[3] if w['body']['operation']=='clear_lost')['state']='UNKNOWN'
        elif mode=='relist':next(r for r in x[0] if r['command']['operation']=='relist_all')['command']['params']['duration']=7200
        elif mode=='unknown':x[4]['prior_unknowns'][0]['state']='ACKNOWLEDGED'
        else:x[2]['reason']='HEALTHY'
        try:audit(*x)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_incident_evidence_accepted_'+mode)
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_cases=negative,**result)))

if __name__=='__main__':main()
