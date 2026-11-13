"""Re-derive all 001c-06 outcomes from immutable command/account readbacks.

This audit never attaches, retries, restarts, or sends a browser/account command.
Historical checkpoints keep their original verdicts. New proof is supplemental.
"""
import hashlib
import json
from pathlib import Path
import sqlite3

from . import policy
from .server import ROOT,DIRECTORY,LIMITS,validate_result
from fc_access.e2e_v1.audit import inspect as original_inspect
from fc_access.e2e_reconcile_v1.audit import inspect as first_resolution
from fc_access.e2e_resolution_v2.server import validate_result as validate_resolution

RESOLUTION=ROOT/'docs/research/001c/001c-06-resume-03'
FINAL=ROOT/'docs/research/001c/001c-06-complete'

def load(p):return json.loads(Path(p).read_text())
def check(condition,reason):
    if not condition:raise ValueError(reason)
def normalized(v):return json.loads(json.dumps(v))
def preservation(directory):
    for name,digest in load(directory/'entry.json')['preserve'].items():
        check(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,'historical_bytes_changed:'+name)

def read_run(directory=DIRECTORY):
    directory=Path(directory)
    db=sqlite3.connect((directory/'live-final.sqlite').resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    check(db.execute('PRAGMA integrity_check').fetchone()==('ok',),'bad_sqlite')
    meta={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM meta')}
    rows=list(db.execute('SELECT id,stage,operation,body,state,created,delivered,result FROM commands ORDER BY created,id'))
    events=[{'seq':s,'at':t,'reason':r,'data':json.loads(v)} for s,t,r,v in db.execute('SELECT * FROM events ORDER BY seq')]
    db.close()
    check(meta['limits']==LIMITS and meta['stopped'] is True,'bounds_or_close_changed')
    check(meta['unreconciled'] is None,'unreconciled_mutation')
    check(len(rows)==18 and len({x[0] for x in rows})==18,'missing_or_duplicate_commands')
    previous=0;evidence={};timeline=[]
    for cid,stage,op,body,state,created,delivered,result in rows:
        c=json.loads(body);r=json.loads(result);a=load(directory/(stage+'.json'))
        check(a['http_status']==200 and a['response']==r,'capture_ledger_mismatch:'+stage)
        check(cid==hashlib.sha256(('001c-06:resume-02:'+stage).encode()).hexdigest()[:32],'wrong_command_id')
        check(a['argv'][:5]==['{python}','-m','fc_access.e2e_live_v2.capture',stage,op],'wrong_reproduction_argv')
        check(json.loads(a['argv'][5])==a['request']['params'],'wrong_params')
        check(all(c['params'][k]==v for k,v in a['request']['params'].items()),'intent_changed')
        check(r['command_id']==cid and r['operation']==op and c['operation']==op,'wrong_result_correlation')
        validate_result(r);observed=policy.at(r['observed_at']).timestamp();policy.fresh(r,op,observed)
        check(previous<=created<=delivered<=observed<meta['deadline'],'overlapping_or_expired_command')
        check(a['at']<=created and 0<a['elapsed_ms']<23000,'invalid_host_timing')
        for reason in ('RESERVED_BEFORE_DELIVERY','DELIVERED','RESULT'):
            check(len([e for e in events if e['reason']==reason and e['data'].get('id')==cid])==1,'delivery_not_exactly_once')
        check(state==('RECONCILED' if op in policy.WRITES else 'ACKNOWLEDGED'),'unverified_command')
        n=r['network'][0];previous=observed;evidence[cid]=r
        timeline.append({'window':'resume-02','command_id':cid,'stage':stage,'operation':op,'argv':a['argv'],'params':c['params'],
          'at':a['at'],'created':created,'delivered':delivered,'observed_at':r['observed_at'],'state':state,
          'network':r['network'],'host_ms':a['elapsed_ms'],'page_ms':r['duration_ms'],'native_ms':n['duration_ms'],
          'dispatch_ms':(policy.at(n['started_at']).timestamp()-delivered)*1000,'rows':r['rows'],'credits':r['credits']})
    bids=[t for t in timeline if t['operation']=='bid'];writes=[t for t in timeline if t['operation'] in policy.WRITES]
    check(len(bids)==len(writes)==1,'unexpected_mutation')
    bid=bids[0];p=bid['params'];check(p['amount']==800 and bid['network'][0]['bid_amount']==800,'actual_bid_amount_missing_or_wrong')
    check(p['amount']<=LIMITS['individual_bid'] and p['amount']<=LIMITS['gross_coins'],'exposure_exceeded')
    derived=normalized(policy.bid_plan(p,evidence,None,bid['created']))
    check(derived==meta['enrollment']==load(directory/'pricing-plan.json'),'unsupported_economics')
    check((derived['target'],derived['tax'],derived['cap'],derived['X'],derived['estimate']['sample_count'])==(2800,140,2100,500,12),'wrong_economics')
    en=meta['enrollment'];identity={k:en[k] for k in ('trade_id','item_id','definition_id')}
    rec=[e for e in events if e['reason']=='INDEPENDENT_READBACK'];check(len(rec)==1,'missing_readback_event')
    check(rec[0]['data']['id']==bid['command_id'],'wrong_reconciled_bid')
    status=evidence[rec[0]['data']['status_id']];balance=evidence[rec[0]['data']['balance_id']]
    check(status['command_id']!=balance['command_id'] and status['command_id']!=bid['command_id'],'readbacks_not_independent')
    for r in (status,balance):
        check(policy.at(r['network'][0]['started_at']).timestamp()>policy.at(evidence[bid['command_id']]['network'][0]['ended_at']).timestamp(),'readback_not_after_ack')
    leading=policy.exact(status,identity['trade_id'],identity['item_id'],identity['definition_id'])
    check(leading['bid_state']=='highest' and leading['trade_state']=='active' and leading['current_bid']==800,'leading_not_proved')
    check(balance['credits']==15468 and meta['initial_balance']==16268,'bid_debit_not_proved')
    holds=[e for e in events if e['reason']=='HOLD'];check(len(holds)==2,'live_hold_missing')
    for e in holds:
        r=evidence[e['data']['status_id']];policy.fresh(r,'watched',e['at'])
        a=policy.exact(r,identity['trade_id'],identity['item_id'],identity['definition_id'])
        check(a['bid_state']=='highest' and a['trade_state']=='active','hold_without_live_lead')
        check(e['data']['additional_write'] is False and e['data']['bid_writes']==1,'hold_wrote_bid')
        check(len([t for t in bids if t['at']<=e['at']])==1,'duplicate_bid_during_hold')
    for name in ('hold-opening','hold-cycle-2'):
        h=load(directory/(name+'.json'))
        check(h['http_status']==200 and h['response']=={'hold':True},'hold_request_failed')
        for field in ('reads_reserved','mutations_reserved','bid_writes_reserved','gross_coins_reserved'):
            check(h['before'][field]==h['after'][field],'hold_sent_additional_command')
    check(not [e for e in events if e['reason']=='REBID_INTENT'],'unexpected_rebid')
    check(not (directory/'watched-cycle-4.json').exists(),'interrupted_sample_replayed')
    closed=load(directory/'closed.json');check(closed['health']['expired'] and closed['health']['stopped'],'expired_window_reopened')
    check(closed['native_requests_after_deadline']==0,'late_native_request')
    # A genuine pre-write service restart preserved the first three reads/deadline.
    first=load(directory/'search-1.json');later=load(directory/'comparables-1.json')
    check(first['after']['boot']!=later['before']['boot'],'missing_prewrite_restart')
    check(first['after']['deadline']==later['before']['deadline']==meta['deadline'],'restart_reset_deadline')
    check(later['before']['reads_reserved']==3,'restart_reset_budget')
    skipped=load(directory/'availability-1.json')['response'];check(skipped['rows']==skipped['wire_rows']==[],'missing_unavailable_candidate')
    preservation(directory)
    watched=[t for t in timeline if t['operation']=='watched'];active=[t for t in watched if t['rows']]
    expiry=[{'stage':t['stage'],'network_at':t['network'][0]['started_at'],'expires':t['rows'][0]['expires'],
      'expected_expiry_epoch':policy.at(t['network'][0]['started_at']).timestamp()+t['rows'][0]['expires']} for t in active]
    return {'meta':meta,'identity':identity,'timeline':timeline,'events':events,'bid':bid,'holds':holds,'pricing':derived,
      'timing':{'bulk_refresh_host_ms':[t['host_ms'] for t in watched],'bulk_refresh_native_ms':[t['native_ms'] for t in watched],
        'bid_dispatch_ms':bid['dispatch_ms'],'bid_native_ms':bid['native_ms'],'bid_host_ms':bid['host_ms'],
        'ack_to_independent_watched_ms':(policy.at(status['network'][0]['ended_at']).timestamp()-policy.at(evidence[bid['command_id']]['network'][0]['ended_at']).timestamp())*1000,
        'active_refresh_start_intervals_seconds':[(policy.at(b['network'][0]['started_at'])-policy.at(a['network'][0]['started_at'])).total_seconds() for a,b in zip(active,active[1:])],
        'target_25s_cycle':'LIVE_UNVERIFIED_INTERRUPTED_SAMPLE;NO_CATCH_UP','timer_extension':'LIVE_UNVERIFIED','expiry':expiry}}

def read_resolution(identity,directory=RESOLUTION):
    directory=Path(directory)
    db=sqlite3.connect((directory/'live-final.sqlite').resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    check(db.execute('PRAGMA integrity_check').fetchone()==('ok',),'bad_resolution_sqlite')
    meta={k:json.loads(v) for k,v in db.execute('SELECT k,v FROM meta')}
    rows=list(db.execute('SELECT id,operation,state,created,delivered,result FROM commands ORDER BY created'))
    db.close();check(meta['stopped'] is True and len(rows)==4,'resolution_not_bounded_closed')
    captures={};timeline=[];previous=0
    for cid,op,state,created,delivered,result in rows:
        a=load(directory/(op+'.json'));r=json.loads(result);validate_resolution(r)
        check(a['response']==r and a['http_status']==200 and state=='OBSERVED','resolution_capture_mismatch')
        check(a['argv']==['{python}','-m','fc_access.e2e_resolution_v2.capture',op],'wrong_resolution_argv')
        check(r['success'] and r['command_id']==cid and r['operation']==op and r['persona']['accepted'],'bad_resolution_result')
        check(len(r['network'])==1,'resolution_native_count');n=r['network'][0]
        check(n['method']=='GET' and n['status']==200 and n['session_header_present'],'resolution_not_authenticated_read')
        check(previous<=created<=delivered<=policy.at(n['started_at']).timestamp()<=policy.at(n['ended_at']).timestamp()<=policy.at(r['observed_at']).timestamp()<meta['deadline'],'resolution_not_serialized_or_expired')
        previous=policy.at(r['observed_at']).timestamp();captures[op]=r
        timeline.append({'window':'resume-03','command_id':cid,'operation':op,'argv':a['argv'],'at':a['at'],
          'observed_at':r['observed_at'],'network':r['network'],'host_ms':a['elapsed_ms'],'rows':r['rows'],'credits':r['credits']})
    peer=load(directory/'status.json')['before']['peer']
    check(peer['source_match'] and peer['original_trade_resource_match'],'unreviewed_or_unmatched_exact_status')
    lite=captures['status'];watched=captures['watched'];owned=captures['unassigned'];balance=captures['balance']
    check(len(lite['rows'])==len(lite['wire_rows'])==len(watched['rows'])==len(watched['wire_rows'])==1,'terminal_independent_rows_missing')
    for r in (lite,watched):
        a=r['rows'][0];wire=r['wire_rows'][0]
        for k in ('trade_id','item_id','current_bid','bid_state','trade_state','expires'):check(a[k]==wire[k],'terminal_wire_mismatch')
        check(a['trade_id']==identity['trade_id'] and a['item_id']==identity['item_id'],'terminal_wrong_physical_item')
        check(a['trade_state']=='closed' and a['bid_state']=='outbid' and a['expires']==-1 and a['current_bid']==1200,'terminal_loss_not_witnessed')
    check(watched['rows'][0]['definition_id']==identity['definition_id'],'terminal_wrong_version')
    check(lite['rows'][0]['definition_id']==0,'lite_version_must_not_be_claimed')
    check(owned['rows']==[] and balance['credits']==16268,'ownership_or_refund_unreconciled')
    check(policy.classify(watched,owned,trade=identity['trade_id'],item=identity['item_id'],definition=identity['definition_id'])=='LOST','bad_loss_classification')
    check(policy.classify({'rows':[]},owned,trade=identity['trade_id'],item=identity['item_id'],definition=identity['definition_id'])=='UNKNOWN','missing_coverage_became_loss')
    preservation(directory)
    return {'timeline':timeline,'state':'LOST','available_coins':16268,'returned_available_coins':800,'current_held_coins_inferred':0,
      'paid_acquisition_cost':0,'won_items':[],'owned_items_created':[],'unsold_cards_created':[],
      'remaining_watchlist_entry':'EXPIRED_OUTBID_TARGET_LEFT_IN_PLACE;NO_REMOVAL_MUTATION','lite_definition_id':0,
      'terminal_observed_at':watched['observed_at'],'after_original_window':True}

def inspect(live_directory=DIRECTORY,resolution_directory=RESOLUTION):
    old=original_inspect();prior=first_resolution()
    check(prior==load(ROOT/'docs/research/001c/001c-06-resume-01/resolution.json'),'prior_resolution_changed')
    run=read_run(live_directory);resolution=read_resolution(run['identity'],resolution_directory)
    check(policy.at(resolution['terminal_observed_at']).timestamp()>run['meta']['deadline'],'mislabelled_in_window_terminal')
    history=[]
    for t in old['timeline']:
        a=load(ROOT/('docs/research/001c/001c-06/'+t['stage']+'.json'))
        history.append({'window':'original','command_id':t['id'],'operation':t['operation'],'stage':t['stage'],'at':t['at'],
          'observed_at':t['observed_at'],'argv':a['argv'],'params':t['params'],'network':t['network'],'host_ms':t['host_ms']})
    for a in prior['commands']:
        r=a['response'];history.append({'window':'resume-01','command_id':r['command_id'],'operation':r['operation'],
          'at':a['at'],'observed_at':r['observed_at'],'argv':a['argv'],'network':r['network'],'host_ms':a['elapsed_ms']})
    history=sorted(history+run['timeline']+resolution['timeline'],key=lambda t:t['at'])
    check(len(history)==len({t['command_id'] for t in history})==44,'aggregate_command_accounting')
    check(all(a['at']<b['at'] for a,b in zip(history,history[1:])),'aggregate_chronology')
    return {'task':'001c-06','status':'done','scope':'BOUNDED_E2E_COMPLETE_WITH_EXPLICIT_LIVE_UNVERIFIED_BRANCHES',
      'objective_002_release':'CONDITIONAL_GO;NOT_FULL_GO','original_checkpoint_status':old['status'],
      'original_700_bid':'HISTORICAL_ACCEPTANCE_UNVERIFIED;NO_CURRENT_EXPOSURE_OR_ACQUISITION_FROM_SEPARATE_EXACT_STATUS',
      'identity':run['identity'],'opening':'LIVE_VERIFIED_MINIMUM_FIRST_PARTICIPATION_800_ABOVE_EXISTING_750',
      'leading_hold':'LIVE_VERIFIED_TWO_HOLDS_WITH_ONE_BID_WRITE','competition':'LIVE_COMPETITIVE_PRICE_ADVANCE_AND_EVENTUAL_LOST_1200',
      'active_outbid_rebid':'LIVE_UNVERIFIED_INTERRUPTION;NO_REBID_SENT','won_resale_handoff':'LIVE_UNVERIFIED_NO_WON_ITEM',
      'timer_extension':'LIVE_UNVERIFIED','pricing':run['pricing'],'timing':run['timing'],
      'original_limits_preserved':True,'windows':[
        {'name':'original','commands':18,'mutations':1,'gross_coin_reservations':700,'closed':True},
        {'name':'resume-01','commands':4,'mutations':0,'seconds_limit':120,'closed':True},
        {'name':'resume-02','commands':18,'mutations':1,'limits':LIMITS,'gross_coin_reservations':800,'closed':True,'interrupted':True},
        {'name':'resume-03','commands':4,'mutations':0,'seconds_limit':120,'closed':True}],
      'native_requests_total':44,'read_commands_total':42,'actual_bid_writes_total':2,'gross_coin_reservations_total':1500,
      'initial_spendable':16268,'after_verified_opening_spendable':15468,'final_spendable':16268,
      'held_at_leading_inferred':800,'returned_available_coins':800,'current_held_coins_inferred':0,
      'net_spendable_change':0,'actual_paid_acquisition_cost':0,'unresolved_active_bids':[],
      'unresolved_historical_acceptance':[old['unresolved_bid_commands'][0]],'verified_wins':[],'verified_losses':[run['identity']],
      'new_owned_cards':[],'unsold_cards_created':[],'move_writes':0,'list_writes':0,'completed_sales':None,'realized_profit':None,
      'resolution':resolution,'timeline':run['timeline'],'command_timeline':history,'journal_events':run['events'],
      'proof_limits':[
        'Terminal LOST and 800 available-coin return were observed after a supervisor outage, in a separately bounded read-only window. Active outbid timing was not observed; no rebid was sent.',
        'Held values are inferred from independent leading status and the matching available-coin debit, not a separately exposed held-balance field. Peak original escrow and transient refund timing remain unverified.',
        'The original 700 request body was not retained. Its historical acceptance stays unverified; neither HTTP 200 nor later absence is labelled an enrolled loss.',
        'Lite status omits full definition ID. Exact trade/item hashes match, and a separate fresh full-version watched row supplies version 261855.',
        'Standalone capture argv are canonical reproducible invocations; some commands were coordinated by Python stdin calling capture.main sequentially. Decision artifacts retain actual stdin argv and local RPC parameters.',
        'No 25-second refresh pair completed after the requested sleep; no catch-up was dispatched. Individual bulk timings do not establish a live 50-auction cycle guarantee.',
        'The isolated empirical bridge proves only the observed bid price; it does not promote the whole tick schedule to LIVE_VERIFIED in the strict reusable rules provider.'],
      'bounded_continuation':{'needed_for_this_auction':'None: conclusively LOST with balance restored. Leave expired target untouched unless separately authorized.',
        'needed_for_remaining_branches':{'new_auctions_max':1,'seconds_max':900,'reads_max':40,'bid_writes_max':2,'mutations_max':4,'gross_coins_max':2000,'individual_bid_max':1000,'reserve':5000,
          'requirements':['Choose a freshly eligible auction whose expected expiry fits the remaining window. Recompute >=5 exact-PC comparables and native caps before first participation.',
            'After authoritative active outbid only, recheck fresh eligibility/balance/economics and send one minimum legal rebid within the stored cap. Never manufacture an opponent.',
            'Capture pre/post expiry around naturally occurring late traffic. Stop on ambiguity or limits; leave unwitnessed extension unverified.',
            'If conclusively WON, obtain independent full-version physical ownership and paid-cost proof, then reserve at most one move and one valid listing with independent readbacks. Do not infer a completed sale or profit.']}}}

def main():
    FINAL.mkdir(exist_ok=True);r=inspect()
    with (FINAL/'report.json').open('x') as f:json.dump(r,f,indent=2);f.write('\n')
    with (FINAL/'timeline.json').open('x') as f:json.dump({'historical':'../001c-06/timeline.json','first_resolution':'../001c-06-resume-01/resolution.json',
      'live':r['timeline'],'post_expiry':r['resolution']['timeline']},f,indent=2)
    print(json.dumps({k:r[k] for k in ('status','native_requests_total','actual_bid_writes_total','final_spendable','actual_paid_acquisition_cost')}))
if __name__=='__main__':main()
