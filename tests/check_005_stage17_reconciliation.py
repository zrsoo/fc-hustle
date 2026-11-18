"""Fresh finite account readback only; missing rows never manufacture settlement."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed,payload
OUT=ROOT/'docs/research/005/stage17/read-only-reconciliation'
CAPTURES={'checkpoint.jsonl','result.json','diagnostics.json'}

def audit(events,result,diagnostics):
    records=[r for r in events if r['kind']=='NATIVE_RESULT'];reserved=[r for r in events if r['kind']=='RESERVED_BEFORE_DELIVERY']
    need(result['status']=='READS_VERIFIED' and result['mutations']==0 and result['pending']==0 and result['service_stopped'],'finite_readonly_service_closed')
    need(len(records)==len(reserved)==result['reserved_commands']==5 and [r['command']['id'] for r in reserved]==[r['command']['id'] for r in records],'finite_individual_read_intents')
    need([r['command']['operation'] for r in records]==['balance','watched','transfer_list','unassigned','status_batch'],'no_account_mutations')
    targets=json.loads((OUT.parent/'reconciliation-targets.json').read_text())
    need(len(targets)==10 and records[-1]['command']['params']['targets']==targets,'exact_original_cohort')
    db=sqlite3.connect(':memory:');db.executescript('CREATE TABLE c4_commands(id,body,state,result);CREATE TABLE c4_diagnostics(command_id,body);')
    try:
        ids=[r['command']['id'] for r in records];need(len(ids)==len(set(ids)),'unique_native_reads')
        for r in records:db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(r['command']['id'],json.dumps(r['command']),'DONE',json.dumps(r['response'])))
        for r in diagnostics:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(r['command_id'],json.dumps(r['records'])))
        e=Evidence(db,ids,{})
        for r in records:
            c,v=e.get(r['command']['id']);need(c['fences']['epoch']==32,'new_probe_epoch')
        c,v=e.get(ids[-1],'status_batch');wc,wv=e.get(ids[1],'watched')
        need(wc['schema']==2 and wv['coverage']['watch_list']['capacity']==50 and network_at(wc,wv)<network_at(c,v),'fresh_native_watched_authority')
        result_rows=[]
        for target in targets:
            if target in v['missing']:result_rows.append(dict(target=target,outcome='MISSING_UNRESOLVED'));continue
            sc,sv,row=e.status(c['id'],target)
            loss=row['trade_state'] in {'closed','expired'} and row['expires']<=0 and row['bid_state'] in {'none','outbid'} and row['native_is_won'] is False
            outcome='TERMINAL_LOSS' if loss else 'WON_CLAIM_REQUIRES_PHYSICAL_PROOF' if row['native_is_won'] is True else 'ACTIVE_OR_UNRESOLVED'
            result_rows.append(dict(target=target,outcome=outcome,current_bid=row['current_bid'],trade_state=row['trade_state'],bid_state=row['bid_state']))
        need(result['status_returned']==len(v['auctions']) and result['status_missing']==len(v['missing']) and len(v['auctions'])+len(v['missing'])==10,'honest_complete_target_projection')
        return dict(read_commands=5,mutations=0,outcomes=result_rows)
    finally:db.close()

def main():
    read=lambda n:json.loads((OUT/n).read_text());events=[json.loads(l) for l in (OUT/'checkpoint.jsonl').read_text().splitlines()]
    seal=read('sealed-evidence.json');need({r['path'] for r in seal['files']}==CAPTURES,'captured_native_evidence_scope')
    for r in seal['files']:need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_readback_changed')
    args=[events,read('result.json'),read('diagnostics.json')];result=audit(*args);negative=0
    for mode in ('mutation','wire','target','diagnostics','pending'):
        x=deepcopy(args)
        if mode=='mutation':x[1]['mutations']=1
        elif mode=='pending':x[1]['pending']=1
        elif mode=='diagnostics':x[2]=[]
        else:
            r=next(r for r in x[0] if r['kind']=='NATIVE_RESULT' and r['command']['operation']=='status_batch')
            if mode=='target':r['command']['params']['targets'][0]['item_id']='item:'+'0'*24
            else:r['response']['network'][0]['status']=401
        try:audit(*x)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('invalid_reconciliation_accepted_'+mode)
    print(json.dumps(dict(status='READ_ONLY_ACCOUNT_EVIDENCE_NOT_OBJECTIVE_COMPLETION',negative_cases=negative,**result)))

if __name__=='__main__':main()
