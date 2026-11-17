"""Genuine recovered listing/acquisition, native crash and cache experiment audit."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from validate_005_lifecycle import Evidence,need,network_at,observed,audit_maintenance
from fc_access.production_v1.resale import assess_effect

OUT=ROOT/'docs/research/005/stage08'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def lines(name):return [json.loads(l) for l in (OUT/name).read_text().splitlines()]


def audit(records,work,cohort):
    db=sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TABLE c4_commands(id,body,state,result); CREATE TABLE c4_diagnostics(command_id,body); CREATE TABLE c4_work(id,body,state,dispatched_at,completed_at,proof);')
        old=[json.loads(l) for l in (OUT.parent/'stage06/commands.jsonl').read_text().splitlines()]
        for r in old+records:
            c=r['command'];db.execute('INSERT INTO c4_commands VALUES(?,?,?,?)',(c['id'],json.dumps(c),r['state'],json.dumps(r['response'])))
            for group in r['diagnostics']:db.execute('INSERT INTO c4_diagnostics VALUES(?,?)',(c['id'],json.dumps(group)))
        for w in work:
            c=w['command'];db.execute('INSERT INTO c4_work VALUES(?,?,?,?,?,?)',(c['id'],json.dumps(c),w['state'],w['dispatched_at'],w['completed_at'],json.dumps(w['proof'])))
        ids=[r['command']['id'] for r in old+records];need(len(ids)==len(set(ids)),'unique_native_deliveries')
        e=Evidence(db,ids,{})
        listing=next(w for w in work if w['command']['operation']=='list');c=listing['command'];p=c['params'];t={k:p[k] for k in ('trade_id','item_id','definition_id')}
        lc,lv=e.get(c['id'],'list');need(lc==c and listing['state']=='CONFIRMED','genuine_native_listing_required')
        need((p['paid'],p['starting_bid'],p['buy_now_price'],p['duration'])==(3100,4200,4300,3600),'original_resale_policy_and_hour')
        need([n['method'] for n in lv['result']['network']]==['POST','GET'],'native_listing_and_owned_followup')
        wc,win=e.get(p['win_read_id'],'watched')
        terminal=[r for r in win['result']['auctions'] if r['trade_id']==t['trade_id'] and r['item']['item_id']==t['item_id'] and r['item']['definition_id']==t['definition_id']]
        need(len(terminal)==1 and terminal[0]['native_is_won'] is True and terminal[0]['bid_state']=='highest' and terminal[0]['current_bid']==p['paid'] and terminal[0]['expires']<=0,'exact_paid_terminal_win_required')
        oc,owned=e.get(p['owned_read_id'],'transfer_list');need(owned==listing['before'] and owned['coverage']['complete'],'fresh_complete_listing_inventory')
        need(sum(r['item']['item_id']==t['item_id'] and r['item']['definition_id']==t['definition_id'] and r['item']['last_sale_price']==p['paid'] and r['item']['untradeable'] is False and r['trade_state']=='inactive' for r in owned['result']['auctions'])==1,'exact_current_paid_ownership')
        cc,caps=e.get(p['caps_read_id'],'caps');limits=caps['result']['caps']
        need(limits['definition_id']==t['definition_id'] and limits['minimum']<=p['starting_bid']<p['buy_now_price']<=limits['maximum'],'current_native_caps')
        for rc,rv in ((oc,owned),(cc,caps)):
            need(rc['fences']==c['fences'] and rc['context']==c['context'] and 0<=(datetime.fromisoformat(listing['dispatched_at'])-network_at(rc,rv)).total_seconds()<=30,'current_dispatch_read_freshness')
        after=listing['proof']['after'];ac,av=e.get(after['command_id'],'transfer_list')
        need(av==after and av['coverage']['complete'] and network_at(ac,av)>=datetime.fromisoformat(listing['completed_at']),'independent_complete_listing_readback')
        before_trade=next(r['trade_id'] for r in owned['result']['auctions'] if r['item']['item_id']==t['item_id'])
        need(assess_effect(c,av,None,at=datetime.fromisoformat(listing['at']),claimed=datetime.fromisoformat(listing['dispatched_at']),completed=datetime.fromisoformat(listing['completed_at']),before=before_trade)[0],'real_native_listing_effect_required')
        maintenance=audit_maintenance(e);need(maintenance['confirmed']==['relist_all'],'eligible_maintenance_readback')
        initial=[a for a in cohort['attempts'] if a['kind']=='initial'];need(len(initial)==8,'eight_original_initial_attempts')
        accepted=[]
        for a in cohort['attempts']:
            bc,bv=e.get(a['id'],'bid');bp=bc['params'];target=bp['target'];receipt=bv['receipt']
            need(receipt['verdict']=='ACCEPTED' and receipt['wire_identity_matches'] and receipt['wire_amount_matches'] and receipt['wire_amount']==bp['amount'],'native_bid_receipt_required')
            sc,sv,before=e.status(bp['status_read_id'],target)
            need(before['trade_state']=='active' and network_at(sc,sv)<network_at(bc,bv),'fresh_status_for_bid')
            if a['kind']=='initial':
                candidate=a['body']['candidate'];q=candidate['quote'];batch=cohort['batches'][a['batch_id']]
                balance_c,balance=e.get(batch['balance_read_id'],'balance');discovery_c,discovery=e.get(batch['discovery']['command_id'],'search')
                need(balance['credits']>40000 and batch['config']['entry_threshold']==40000 and discovery_c['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000),'unchanged_batch_admission_and_filters')
                need(candidate['selection_remaining']>60 and q['completed'] is True and q['status']=='COMPLETE' and bp['amount']==bp['minimum']<=candidate['cap']==bp['cap']<=q['max_affordable_bid'],'original_eligible_profitable_initial')
            else:need(before['bid_state']=='outbid' and before['current_bid']<bp['amount']<=bp['cap'],'genuine_competitive_rebid')
            confirmations=[]
            for sid in e.statuses.get(target['trade_id'],[]):
                pc,pv=e.get(sid,'status_batch')
                if network_at(pc,pv)<=observed(bc,bv):continue
                _,_,r=e.status(sid,target)
                if r['bid_state'] in {'highest','outbid'}:confirmations.append(sid)
            need(confirmations,'independent_post_bid_participation')
            accepted.append(a['id'])
        uncertain=[a for a in cohort['attempts'] if a['state']=='UNKNOWN']
        need(len(uncertain)==1 and uncertain[0]['id'] in accepted,'unknown_history_preserved_despite_later_native_confirmation')
        return dict(initial_confirmed=len(initial),competitive_rebids=len(accepted)-len(initial),recovered_listing=True,maintenance=True,preserved_unknown_rebid=uncertain[0]['id'])
    finally:db.close()


def main():
    seal=read('sealed-evidence.json')
    need({r['path'] for r in seal['files']}==CAPTURES,'immutable_capture_scope')
    for r in seal['files']:
        need(hashlib.sha256((OUT.parent/r['path']).read_bytes()).hexdigest()==r['sha256'],'captured_evidence_changed')
    prefix=audit(lines('commands.jsonl'),read('work.json'),read('acquisition.json'))
    need(prefix['competitive_rebids']==3,'successful_prefix_retained')
    final_seal=read('final-sealed-evidence.json')
    need({r['path'] for r in final_seal['files']}=={'final-commands.jsonl','final-acquisition.json'},'final_capture_scope')
    for r in final_seal['files']:
        need(hashlib.sha256((OUT/r['path']).read_bytes()).hexdigest()==r['sha256'],'final_captured_evidence_changed')
    records,work,cohort=lines('final-commands.jsonl'),read('work.json'),read('final-acquisition.json');result=audit(records,work,cohort);negative=0
    need(result['competitive_rebids']==4,'complete_runtime_rebids_retained')
    delivered={r['command']['id'] for r in records}
    native_events=[e['message']['command_id'] for e in lines('stopped-events.jsonl') if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(len(delivered)==len(records)==len(native_events) and delivered==set(native_events),'full_native_delivery_inventory')
    for mode in ('ack_only','wrong_owner','wrong_price','wrong_hour'):
        rs,ws=deepcopy((records,work));w=next(w for w in ws if w['command']['operation']=='list')
        if mode=='ack_only':next(r for r in rs if r['command']['id']==w['command']['id'])['response']['result']['success']=False
        elif mode=='wrong_owner':w['before']['result']['auctions']=[]
        else:
            key='buy_now_price' if mode=='wrong_price' else 'expires'
            next(r for r in w['proof']['after']['result']['auctions'] if r['item']['item_id']==w['command']['params']['item_id'])[key]=1 if mode=='wrong_price' else 7200
        try:audit(rs,ws,cohort)
        except (ValueError,KeyError):negative+=1
        else:raise ValueError('corrupt_native_listing_accepted_'+mode)
    stopped=read('stopped-state.json');events=lines('stopped-events.jsonl');fault=read('windows-fault.json')
    need(stopped['state']=='STOPPED' and stopped['reason']=='PROCESS_EXIT' and events[-1]['exit_code']==3221225477 and events[-1]['forced'] is False,'real_crash_retained')
    need(fault['ProcessId']=='0x708' and int(fault['ProcessId'],16)==stopped['child']['pid'] and fault['ExceptionCode']=='c0000005' and fault['ModuleName']=='python313.dll','windows_fault_matches_owned_child')
    monitor=read('fault-monitor.json')
    need(monitor['operation']['generation']==stopped['generation'] and monitor['operation']['healthy']==0 and monitor['operation']['faulted']==1,'scheduler_resets_failed_generation')
    base=ROOT/'docs/research/005/checks/stage08'
    red=json.loads((base/'cache-reproduction/result.json').read_text());control=json.loads((base/'cache-control/result.json').read_text());green=json.loads((base/'cache-fixed/result.json').read_text())
    need(red['exit_code']!=0 and control['exit_code']!=0 and all('synthetic_read_mismatch' in (base/p/'stderr.txt').read_text() for p in ('cache-reproduction','cache-control')),'bad_shared_cache_reads_reproduced')
    stress=json.loads((base/'cache-fixed/stdout.txt').read_text());need(green['exit_code']==0 and stress['readers']==12 and stress['reads']>=100000 and stress['seconds']==30,'substantial_exact_controller_connection_stress')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',negative_checks=negative,healthy_seconds=0,crash='0xC0000005',cache_fixed_reads=stress['reads'],**result)))


CAPTURES={'stage08/'+p for p in ('commands.jsonl','runtime-events.jsonl','work.json','runtime-snapshot.json','scheduler-samples.json','acquisition.json','windows-fault.json','stopped-state.json','stopped-events.jsonl','fault-monitor.json')}
CAPTURES.update('checks/stage08/'+p+'/'+name for p in ('cache-reproduction','cache-control','cache-fixed') for name in ('stdout.txt','stderr.txt','result.json'))

if __name__=='__main__':main()
