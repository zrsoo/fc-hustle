"""Offline evidence derivation. Never attaches a browser or issues an EA call."""
import hashlib
import json
from pathlib import Path
import sqlite3
from . import policy
from .server import DIRECTORY,ROOT,LIMITS,validate_result

def load(path):return json.loads(path.read_text())

def inspect(directory=DIRECTORY):
    directory=Path(directory)
    db=sqlite3.connect((directory/'live-final.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True)
    assert db.execute('PRAGMA integrity_check').fetchone()==('ok',),'SQLite integrity'
    meta={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM meta')}
    assert meta['limits']==LIMITS and meta['stopped'] is True,'closed immutable limits'
    rows=list(db.execute('SELECT id,stage,operation,body,state,created,delivered,result FROM commands ORDER BY created,id'))
    events=[dict(seq=s,at=t,reason=r,data=json.loads(d)) for s,t,r,d in db.execute('SELECT * FROM events ORDER BY seq')]
    db.close()
    assert len(rows)==len({r[0] for r in rows})==len({r[1] for r in rows})
    evidence={};timeline=[];previous=0
    for cid,stage,op,body,state,created,delivered,result in rows:
        c=json.loads(body);r=json.loads(result);artifact=load(directory/(stage+'.json'))
        assert artifact['http_status']==200 and artifact['response']==r
        assert artifact['argv'][:3]==['{python}','-m','fc_access.e2e_v1.capture'] and artifact['argv'][3:5]==[stage,op]
        assert json.loads(artifact['argv'][5])==artifact['request']['params']
        assert cid==hashlib.sha256(('001c-06:'+stage).encode()).hexdigest()[:32]
        assert c['id']==cid and c['stage']==stage and c['operation']==op
        assert all(c['params'][k]==v for k,v in artifact['request']['params'].items())
        assert r['command_id']==cid and r['operation']==op and state in ('ACKNOWLEDGED','RECONCILED')
        validate_result(r);now=policy.at(r['observed_at']).timestamp();policy.fresh(r,op,now,120)
        assert previous<=created<=delivered<=now<meta['deadline'],'serialized finite delivery'
        assert artifact['at']<=created and 0<artifact['elapsed_ms']<23000
        assert len([e for e in events if e['reason']=='RESERVED_BEFORE_DELIVERY' and e['data'].get('id')==cid])==1
        assert len([e for e in events if e['reason']=='DELIVERED' and e['data'].get('id')==cid])==1
        previous=now;evidence[cid]=r
        n=r['network'][0]
        timeline.append({'id':cid,'stage':stage,'operation':op,'state':state,'params':c['params'],'at':artifact['at'],'created':created,'delivered':delivered,
          'observed_at':r['observed_at'],'http_status':artifact['http_status'],'native_status':r['status'],'network':r['network'],
          'dispatch_ms':(policy.at(n['started_at']).timestamp()-delivered)*1000,'native_ms':n['duration_ms'],
          'page_ms':r['duration_ms'],'host_ms':artifact['elapsed_ms'],'rows':len(r['rows'] or []),'credits':r['credits']})
    assert len(rows)==18,'every actual command accounted'
    writes=[t for t in timeline if t['operation'] in policy.WRITES];bids=[t for t in writes if t['operation']=='bid']
    assert len(writes)==len(bids)==1 and bids[0]['params']['amount']==700
    assert len(rows)-len(writes)<=LIMITS['reads'] and len(writes)<=LIMITS['mutations']
    assert sum(t['params']['amount'] for t in bids)<=LIMITS['gross_coins']
    bid=bids[0];p=bid['params'];en=meta['enrollment']
    derived=policy.bid_plan({k:v for k,v in p.items() if k!='cap'},evidence,None,bid['created'])
    assert json.loads(json.dumps(derived))==en==load(directory/'pricing-plan.json')
    assert meta['unreconciled']==bid['id'],'missing coverage stays unresolved'
    watched=[t for t in timeline if t['operation']=='watched']
    assert all(t['rows']==0 for t in watched)
    funds=[t for t in timeline if t['operation']=='balance']
    assert [t['credits'] for t in funds]==[16268]*4
    identity={k:en[k] for k in ('trade_id','item_id','definition_id')}
    snapshots=[]
    for t in timeline:
        r=evidence[t['id']]
        for a in (r['rows'] or [])+(r['wire_rows'] or [] if t['operation']=='bid' else []):
            if a['trade_id']==identity['trade_id']:
                assert a['item_id']==identity['item_id'] and a['definition_id']==identity['definition_id']
                snapshots.append({'command_id':t['id'],'stage':t['stage'],'operation':t['operation'],'at':r['network'][0]['started_at'],
                  'expires':a['expires'],'expected_expiry_epoch':policy.at(r['network'][0]['started_at']).timestamp()+max(0,a['expires']),
                  'current_bid':a['current_bid'],'bid_state':a['bid_state'],'trade_state':a['trade_state']})
    # Actual competition is a witnessed price advance, not a proven personal outbid.
    assert next(s for s in snapshots if s['stage']=='availability-1')['current_bid']==0
    assert next(s for s in snapshots if s['stage']=='opening-1')['current_bid']==750
    assert next(s for s in snapshots if s['stage']=='availability-after-opening')['current_bid']==750
    tail=load(directory/'search-after-expiry.json')['response']
    assert identity['trade_id'] not in {r['trade_id'] for r in tail['rows']}
    assert policy.classify(load(directory/'watched-after-expiry.json')['response'],load(directory/'unassigned-after-expiry.json')['response'],
        trade=identity['trade_id'],item=identity['item_id'],definition=identity['definition_id'])=='UNKNOWN'
    assert not any(e['reason'] in ('HOLD','REBID_INTENT','INDEPENDENT_READBACK') for e in events)
    stopping=load(directory/'mutation-stop.json');assert stopping['unresolved_bid'] is True and stopping['additional_mutations_authorized'] is False
    assert len([t for t in timeline if t['at']>stopping['at']])==4
    assert not [t for t in writes if t['at']>stopping['at']]
    expected_min=max(s['expected_expiry_epoch'] for s in snapshots)
    assert policy.at(tail['network'][0]['started_at']).timestamp()>expected_min
    assert all(not any(r['item_id']==identity['item_id'] for r in evidence[t['id']]['rows']) for t in timeline if t['operation'] in ('unassigned','transfer_list'))
    entry=load(directory/'entry.json')
    for name,digest in entry['preserve'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,'historical alteration: '+name
    report={
      'task':'001c-06','status':'unresolved','release_decision':'CONDITIONAL_GO_WITH_BLOCKED_LIVE_ACCEPTANCE',
      'identity':identity,'bounds':LIMITS,'command_count':len(rows),'native_request_count':sum(len(t['network']) for t in timeline),
      'reads':len(rows)-len(writes),'mutations':len(writes),'bid_writes':len(bids),'gross_coin_reservations':700,
      'initial_spendable':funds[0]['credits'],'final_spendable':funds[-1]['credits'],'observed_spendable_delta':funds[-1]['credits']-funds[0]['credits'],
      'confirmed_paid_cost':None,'held_coins':None,'returned_coins':None,'transient_escrow':'UNVERIFIED_BETWEEN_SNAPSHOTS',
      'unresolved_bid_commands':[bid['id']],'verified_wins':[],'verified_losses':[],'new_verified_owned_cards':[],
      'transfer_mutations':0,'listing_mutations':0,'completed_sales':None,'realized_profit':None,
      'pricing':en,'opening':'NATIVE_PUT_200_ACK_EFFECT_UNRESOLVED','leading_hold':'UNVERIFIED_NO_LIVE_LEADING_STATE',
      'competition':'LIVE_PRICE_ADVANCE_0_TO_750;PERSONAL_OUTBID_UNVERIFIED','rebid':'UNVERIFIED_WITHHELD_PENDING_INDEPENDENT_RECONCILIATION',
      'terminal_outcome':'UNKNOWN_NOT_LOST','won_item_handoff':'UNVERIFIED_NO_CONCLUSIVE_WIN',
      'timer_extension':'UNVERIFIED_NO_BEFORE_AFTER_BID_NEAR_EXPIRY_OBSERVATION',
      'watchlist_coverage':'FRESH_AUTHENTICATED_EMPTY;NOT_PROOF_OF_TERMINAL_OUTCOME_OR_COMMAND_ACCEPTANCE',
      'watchlist_refresh_ms':[t['host_ms'] for t in watched],'bid_dispatch_ms':bid['dispatch_ms'],'bid_native_ms':bid['native_ms'],'bid_host_ms':bid['host_ms'],
      'opening_to_watch_readback_ms':(policy.at(evidence[watched[1]['id']]['network'][0]['ended_at']).timestamp()-policy.at(evidence[bid['id']]['network'][0]['ended_at']).timestamp())*1000,
      'queue_25_second_cycle':'UNVERIFIED_LIVE;EMPTY_BULK_SAMPLES_ONLY;NO_50_ENTRY_LIVE_CLAIM',
      'expiry_observations':snapshots,'timeline':timeline,'events':events,
      'missing_required_live_criteria':[1,2],
      'continuation':{
        'stage_1':{'reads_max':4,'seconds_max':120,'mutations_max':0,'purpose':'Review current native independent exact-trade status method, then exact auction status plus fresh watched/owned/balance readbacks. Reconcile the original 700 command or retain UNKNOWN. Never infer LOSS from absence. Do not replay the original PUT.'},
        'stage_2':{'prerequisite':'Original mutation independently reconciled; separate explicitly recorded window. Never reopen/reset this closed window.','auctions_max':1,'seconds_max':900,'reads_max':40,'bid_writes_max':2,'mutations_max':4,'gross_coins_max':2000,'individual_bid_max':1000,'reserve':5000,
          'purpose':'Fresh filtered opening with >=5 comparable asks and native caps; immediately obtain independent watched/balance confirmation, then journal leading HOLD with unchanged write count. Observe until expiry; rebid only on authoritative real outbid. If conclusively WON, independently prove paid cost and exact physical ownership before move/list and readbacks. Unwitnessed branches stay UNVERIFIED.'}},
      'proof_limits':['Native bid amount 700 is the invoked argument and durable intent; request body was not retained. HTTP 200 and bid-response outbid do not prove an accepted leading bid.',
        'Bid response outbid at 750 conflicts with empty watched coverage and subsequent search bidState none. No authoritative independent personal outbid, win, loss, refund or zero peak escrow is inferred.',
        'Indicative target 2200 and cap 1500 are projected economics. The separate run limits bids to 1000. BIN-reference estimate acquisition_price 10500 and expected_profit -8410 are not actual paid amounts.',
        'Server bid/list tick acceptance across the schedule remains unverified. This isolated empirical opening test does not upgrade bidding_v1 LIVE_VERIFIED rules or bypass that reusable adapter.',
        'Existing eight transfer-list cards are baseline account inventory, not cards acquired by this run. No owned item or resale listing was created.']}
    return report

def main():
    r=inspect()
    for name,value in [('report.json',r),('timeline.json',r['timeline'])]:
        with (DIRECTORY/name).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
    print(json.dumps({k:r[k] for k in ('status','command_count','native_request_count','mutations','observed_spendable_delta','missing_required_live_criteria')}))
if __name__=='__main__':main()
