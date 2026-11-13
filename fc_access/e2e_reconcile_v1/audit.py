"""Independent terminal-status supplement; never rewrites the original ledger."""
import hashlib
import json
import sqlite3
from .server import DIRECTORY,ROOT,OPERATIONS,validate_result
from fc_access.e2e_v1.policy import at

from fc_access.evidence import evidence_hashes

def inspect():
    db=sqlite3.connect((DIRECTORY/'live-final.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True)
    assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
    meta={k:json.loads(v) for k,v in db.execute('SELECT k,v FROM meta')}
    commands=list(db.execute('SELECT id,operation,state,created,delivered,result FROM commands ORDER BY created'))
    db.close();assert meta['stopped'] is True and len(commands)==4
    captures={};previous=0
    for cid,op,state,created,delivered,result in commands:
        capture=json.loads((DIRECTORY/(op+'.json')).read_text());r=json.loads(result);validate_result(r)
        assert capture['response']==r and capture['http_status']==200 and state=='OBSERVED'
        assert capture['argv']==['{python}','-m','fc_access.e2e_reconcile_v1.capture',op]
        assert r['success'] is True and r['command_id']==cid and r['operation']==op and r['persona']['accepted'] is True
        assert len(r['network'])==1;n=r['network'][0]
        assert n['method']=='GET' and n['status']==200 and n['session_header_present'] is True
        assert previous<=created<=delivered<=at(n['started_at']).timestamp()<=at(n['ended_at']).timestamp()<=at(r['observed_at']).timestamp()<meta['deadline']
        previous=at(r['observed_at']).timestamp();captures[op]=capture
    peer=captures['status']['before']['peer']
    assert peer['source_match'] is True and peer['original_trade_resource_match'] is True
    original=json.loads((ROOT/'docs/research/001c/001c-06/report.json').read_text());identity=original['identity']
    status=captures['status']['response'];assert len(status['rows'])==len(status['wire_rows'])==1
    row=status['rows'][0];wire=status['wire_rows'][0]
    for field in ('trade_id','item_id','current_bid','trade_state','bid_state','expires'):assert row[field]==wire[field]
    assert (row['trade_id'],row['item_id'])==(identity['trade_id'],identity['item_id'])
    assert row['trade_state']=='closed' and row['expires']==-1 and row['bid_state']=='none' and row['current_bid']==800
    assert captures['watched']['response']['rows']==captures['watched']['response']['wire_rows']==[]
    assert captures['unassigned']['response']['rows']==[]
    assert captures['balance']['response']['credits']==original['initial_spendable']==original['final_spendable']==16268
    entry=json.loads((DIRECTORY/'entry.json').read_text())
    for name,digest in evidence_hashes(entry['preserve']).items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    return {'task':'001c-06','status':'NET_EFFECT_RECONCILED_NO_ACQUISITION','original_command_id':original['unresolved_bid_commands'][0],
      'original_checkpoint_unchanged':True,'historical_bid_acceptance':'UNVERIFIED','not_a_verified_enrolled_loss':True,
      'current_exact_trade_status':row,'exact_identity_basis':{'trade_id':identity['trade_id'],'item_id':identity['item_id'],'definition_id':identity['definition_id'],
        'definition_id_in_fresh_lite_read':row['definition_id'],'note':'Lite status omits full version (0); trade and physical-item hashes match the prior full-version search. No new full-version claim from the lite payload.'},
      'current_unresolved_active_bid_exposure':0,'available_coins':16268,'observed_net_paid_cost':0,
      'peak_escrow_and_historical_refunds':'UNVERIFIED_BETWEEN_SNAPSHOTS','new_owned_item_found':False,
      'reason':'Independent exact trade is terminal, not leading; fresh watchlist and unassigned are empty; unchanged independent available balance. No remaining live exposure/acquisition from original command; never replay it.',
      'commands':[{k:c[k] for k in ('argv','at','elapsed_ms','response')} for c in captures.values()],
      'native_requests':4,'mutations':0,'closed':True,
      'next_window_limits':{'auctions':1,'seconds':900,'reads':40,'bid_writes':2,'mutations':4,'gross_coins':2000,'individual_bid':1000,'reserve':5000}}

def main():
    r=inspect()
    with (DIRECTORY/'resolution.json').open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps({k:r[k] for k in ('status','historical_bid_acceptance','available_coins','observed_net_paid_cost','current_unresolved_active_bid_exposure')}))
if __name__=='__main__':main()
