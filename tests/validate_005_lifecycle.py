"""Independent criterion 0 audit of genuine final-generation lifecycle evidence.

Read-only: never trades, repairs, starts, stops, or promotes ACKs into ownership.
Self-tests use isolated controller worlds and cannot produce a live PASS.
"""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import re
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from fc_access.controller_v1.protocol import delivery_command,delivery_response
from fc_access.controller_v1.operational import read,health
from fc_access.production_v1.bulk import classify,parameters,assess_effect as bulk_effect
from fc_access.production_v1.resale import assess_effect as resale_effect

TASK='obj-cb39371c785a/operate'


def need(value,reason):
    if not value:raise ValueError(reason)


def at(value):return datetime.fromisoformat(value)
def payload(c,v):return v if c['schema']==4 else v['result']
def network_at(c,v):return at(v['network_at'] if c['schema']==4 else v['freshness']['network_at'])
def observed(c,v):return at(v['observed_at'] if c['schema']==4 else v['freshness']['observed_at'])


class Evidence:
    def __init__(self,db,ids,phases,*,live=True):
        self.db,self.ids,self.phases,self.live=db,set(ids),phases,live
        self.cache={};self.validated=set();self.operations={};self.statuses={}
        for cid,op,targets in db.execute("SELECT id,json_extract(body,'$.operation'),json_extract(body,'$.params.targets') FROM c4_commands"):
            if cid not in self.ids:continue
            self.operations.setdefault(op,[]).append(cid)
            if op=='status_batch':
                for target in json.loads(targets):self.statuses.setdefault(target['trade_id'],[]).append(cid)

    def get(self,cid,operation=None):
        if cid not in self.cache:
            row=self.db.execute('SELECT body,state,result FROM c4_commands WHERE id=?',(cid,)).fetchone()
            need(row is not None and row[1]=='DONE' and row[2],'command_not_independently_retained')
            self.cache[cid]=(json.loads(row[0]),json.loads(row[2]))
        c,v=self.cache[cid]
        need(operation is None or c['operation']==operation,'wrong_read_operation')
        if cid in self.validated:return c,v
        delivery_command(c);delivery_response(v,c,now=observed(c,v))
        p=payload(c,v);need(p['success'] is True,'failed_operation_is_not_proof')
        if c['operation']!='price_helpers':
            need(p['network'] and all(n['status']==200 and n['session_header_present'] is True for n in p['network']),
                 'native_wire_authentication_required')
        if self.live:
            if c['schema']==2:need(v['freshness']['source']=='native','fixture_not_live_evidence')
            need(all('.test.' not in n['host'] and n['host'].endswith('.ea.com') for n in p['network']),
                 'synthetic_host_not_live_evidence')
            count=self.db.execute('SELECT coalesce(sum(json_array_length(body)),0) FROM c4_diagnostics WHERE command_id=?',(cid,)).fetchone()[0]
            need(count>0,'missing_native_diagnostics')
        self.validated.add(cid);return c,v

    def status(self,cid,target):
        c,v=self.get(cid,'status_batch')
        need(target in c['params']['targets'],'status_target_not_requested')
        links=[l for l in v['links'] if l['target']==target and l['current_dto_matches'] is True]
        need(len(links)==1,'full_version_link_missing')
        full_c,full=self.get(links[0]['full_read_id'])
        need(full_c['context']==c['context'] and full_c['fences']==c['fences'],'identity_epoch_mismatch')
        matches=[r for r in payload(full_c,full)['auctions'] if r['trade_id']==target['trade_id'] and
                 r['item']['item_id']==target['item_id'] and r['item']['definition_id']==target['definition_id']]
        need(len(matches)==1,'full_version_identity_not_observed')
        rows=[r for r in v['auctions'] if r['trade_id']==target['trade_id'] and r['item']['item_id']==target['item_id']]
        need(len(rows)==1,'exact_status_missing')
        return c,v,rows[0]


def audit_chain(e,initial_id):
    c,v=e.get(initial_id,'bid');p=c['params'];target=p['target']
    need(initial_id in e.ids and e.phases.get(initial_id)=='ACQUIRING','initial_not_in_final_generation_acquisition')
    receipt=v['receipt']
    need(receipt and receipt['verdict']=='ACCEPTED' and receipt['wire_identity_matches'] is True and
         receipt['wire_amount_matches'] is True and receipt['matching_item_count']==1,'ack_without_matching_native_receipt')
    attempt=e.db.execute("SELECT batch_id,kind,body FROM c4_attempts WHERE id=?",(initial_id,)).fetchone()
    need(attempt is not None and attempt[1]=='initial','durable_initial_intent_missing')
    candidate=json.loads(attempt[2])['candidate']
    need(candidate['target']==target and candidate['read_id']==p['status_read_id'] and candidate['selection_remaining']>60 and
         p['amount']==p['minimum']==candidate['minimum'] and p['amount']<=candidate['cap']==p['cap'], 'initial_strategy_mismatch')
    quote=candidate['quote']
    need(quote['status']=='COMPLETE' and quote['completed'] is True and quote['resale_price']==candidate['resale_price'] and
         candidate['cap']<=quote['max_affordable_bid'],'completed_profitable_exact_quote_required')
    batch=json.loads(e.db.execute('SELECT body FROM c4_policy_batches WHERE id=?',(attempt[0],)).fetchone()[0])
    cfg=batch['config'];bc,balance=e.get(batch['balance_read_id'],'balance')
    need(cfg['entry_threshold']==40000 and cfg['request_spacing']==2 and cfg['cycle_target']==5 and balance['credits']>40000,
         'production_admission_policy_changed')
    need(bc['context']==c['context'] and bc['fences']==c['fences'],'batch_account_epoch_changed')
    discovery=batch['discovery'];dc,dv=e.get(discovery['command_id'],'search')
    need(dv==discovery and dc['params']==dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000),
         'discovery_filters_changed')
    need(e.db.execute("SELECT count(*) FROM c4_attempts WHERE batch_id=? AND kind='initial'",(attempt[0],)).fetchone()[0]<=10,
         'initial_attempt_limit_exceeded')
    sc,sv,before=e.status(p['status_read_id'],target)
    need(network_at(sc,sv)<network_at(c,v) and before['trade_state']=='active' and
         before['expires']-(network_at(c,v)-network_at(sc,sv)).total_seconds()>60,'fresh_eligible_prebid_status_required')
    confirmations=[];managed=[];competitive=[]
    for cid in e.statuses.get(target['trade_id'],[]):
        try:pc,pv=e.get(cid,'status_batch')
        except ValueError:continue # An ordinary failed read grants no proof.
        if target not in pc['params']['targets'] or network_at(pc,pv)<=observed(c,v):continue
        try:_,_,row=e.status(cid,target)
        except ValueError:continue
        if row['trade_state']=='active' and row['bid_state'] in {'highest','outbid'}:confirmations.append(cid)
        if e.phases.get(cid)=='MANAGING':
            managed.append(cid)
            if row['trade_state']=='active' and row['bid_state']=='outbid' and row['expires']>0 and row['current_bid']<p['cap'] and row['starting_bid']<=p['cap']:
                competitive.append(cid)
    need(confirmations,'independent_post_bid_participation_missing')
    need(managed,'genuine_management_status_missing')
    rebids=[]
    for rid,body in e.db.execute("SELECT id,body FROM c4_attempts WHERE kind='rebid' AND json_extract(body,'$.candidate.target.trade_id')=?",(target['trade_id'],)):
        if rid not in e.ids:continue
        try:rc,rv=e.get(rid,'bid')
        except ValueError:continue # Rejections/ambiguous results never prove a rebid.
        rp=rc['params'];rr=rv['receipt']
        need(rc['context']==c['context'] and rp['target']==target and rp['amount']==rp['minimum']<=p['cap']==rp['cap'],
             'rebid_changed_stored_policy')
        _,prior,prior_row=e.status(rp['status_read_id'],target)
        need(prior_row['bid_state']=='outbid' and prior_row['current_bid']<rp['amount'] and
             network_at(rc,rv)>at(prior['network_at']),'rebid_not_based_on_fresh_competition')
        if rr and rr['verdict']=='ACCEPTED' and rr['wire_identity_matches'] and rr['wire_amount_matches']:
            proven=[cid for cid in confirmations if network_at(*e.get(cid))>observed(rc,rv)]
            if proven:rebids.append(rid)
    need(not competitive or rebids,'competitive_rebid_not_yet_independently_confirmed')
    # WON_ACCOUNTED is a candidate to audit, never sufficient evidence itself.
    work=[]
    for row in e.db.execute("SELECT id,body,before_read,state,at,dispatched_at,completed_at,proof FROM c4_work WHERE json_extract(body,'$.params.item_id')=?",(target['item_id'],)):
        if row[0] not in e.ids:continue
        wc=json.loads(row[1]);op=wc['operation'];wp=wc['params']
        need(row[3]=='CONFIRMED' and row[5] and row[6] and row[7],'work_not_independently_confirmed')
        actual,_=e.get(row[0],op);need(actual==wc and wc['context']==c['context'],'work_target_context_mismatch')
        need({k:wp[k] for k in target}==target and wp['buy_now_price']==candidate['resale_price'] and wp['duration']==3600,
             'unrelated_or_mispriced_resale')
        win_c,win=e.get(wp['win_read_id'],'watched')
        wins=[r for r in win['result']['auctions'] if r['trade_id']==target['trade_id'] and
              r['item']['item_id']==target['item_id'] and r['item']['definition_id']==target['definition_id']]
        need(len(wins)==1 and wins[0]['trade_state']=='closed' and wins[0]['expires']<=0 and
             wins[0]['bid_state']=='highest' and wins[0]['native_is_won'] is True and wins[0]['current_bid']==wp['paid']>0,
             'terminal_paid_win_not_observed')
        amounts=[json.loads(b[0])['params']['amount'] for b in e.db.execute('SELECT a.body FROM c4_attempts a JOIN c4_tombstones t ON t.command_id=a.id')
                 if json.loads(b[0])['candidate']['target']==target]
        need(wp['paid'] in amounts,'paid_cost_not_our_bid')
        oc,owned=e.get(wp['owned_read_id'],'owned_item' if op=='move' else 'transfer_list')
        items=owned['result']['items'] if op=='move' else [r['item'] for r in owned['result']['auctions'] if r['trade_state']=='inactive' and r['current_bid']==0]
        need(sum(i['item_id']==target['item_id'] and i['definition_id']==target['definition_id'] and
                 i['last_sale_price']==wp['paid'] and i['untradeable'] is False for i in items)==1,'exact_paid_physical_ownership_missing')
        cc,caps=e.get(wp['caps_read_id'],'caps');limits=caps['result']['caps']
        need(limits['definition_id']==target['definition_id'] and limits['minimum']<=wp['starting_bid']<wp['buy_now_price']<=limits['maximum'],
             'native_listing_caps_missing')
        after=json.loads(row[7])['after'];ac,av=e.get(after['command_id'],'transfer_list')
        need(av==after and av['coverage']['complete'] is True and network_at(ac,av)>=at(row[6]),'fresh_complete_work_readback_missing')
        before_trade=next((r['trade_id'] for r in owned['result']['auctions'] or [] if r['item']['item_id']==target['item_id']),target['trade_id'])
        unassigned=None
        if op=='move':
            for cid in e.operations.get('unassigned',[]):
                uc,uv=e.get(cid,'unassigned')
                if wc['context']==uc['context'] and at(row[5])<=network_at(uc,uv)<=network_at(ac,av)+timedelta(seconds=30):
                    if not any(i['item_id']==target['item_id'] for i in uv['result']['items']):unassigned=uv;break
            need(unassigned is not None,'post_move_unassigned_read_missing')
        proven,_=resale_effect(wc,av,unassigned,at=at(row[4]),claimed=at(row[5]),completed=at(row[6]),before=before_trade)
        need(proven,'native_resale_effect_not_proven')
        work.append(op)
    need('move' in work and 'list' in work,'genuine_owned_win_move_and_hour_listing_missing')
    return dict(initial_command=initial_id,target=target,confirmations=confirmations,management_reads=managed,
                competitive_reads=competitive,confirmed_rebids=rebids,work=work)


def audit_maintenance(e):
    eligible=dict(clear_sold=False,relist_all=False);confirmed=set()
    for cid in e.ids:
        op=e.db.execute("SELECT json_extract(body,'$.operation') FROM c4_commands WHERE id=?",(cid,)).fetchone()[0]
        if op=='transfer_list':
            try:
                c,v=e.get(cid,op);groups=classify(v)
            except ValueError:continue # Inactive resale rows are not native bulk eligibility.
            eligible['clear_sold']|=bool(groups['sold']);eligible['relist_all']|=bool(groups['expired'])
        elif op in {'clear_sold','relist_all'}:
            c,v=e.get(cid,op);p=c['params'];bc,before=e.get(p['before_read_id'],'transfer_list')
            need(parameters(before,op)==p,'bulk_exact_all_eligible_membership')
            row=e.db.execute('SELECT state,dispatched_at,completed_at,proof FROM c4_work WHERE id=?',(cid,)).fetchone()
            need(row and row[0]=='CONFIRMED' and row[1] and row[2] and row[3],'bulk_readback_missing')
            after=json.loads(row[3])['after'];ac,av=e.get(after['command_id'],'transfer_list')
            need(after==av and ac['context']==bc['context']==c['context'],'bulk_account_or_readback_changed')
            proven,bad=bulk_effect(c,before,av,dispatched=at(row[1]),completed=at(row[2]))
            need(proven and not bad,'bulk_effect_prices_duration_or_identity_unproven');confirmed.add(op)
    need(all(not observed or op in confirmed for op,observed in eligible.items()),'eligible_maintenance_not_yet_proven')
    return dict(eligible=eligible,confirmed=sorted(confirmed))


def audit_lost_cleanup(e):
    """Current controller contract only; sealed older maintenance is unchanged."""
    eligible=False;confirmed=[];resolved_unknown=[]
    key=lambda r:(r['trade_id'],r['item']['item_id'],r['item']['definition_id'])
    for cid in e.operations.get('watched',[]):
        try:c,v=e.get(cid,'watched')
        except ValueError:continue
        rows=v['result']['auctions'] if c['schema']==2 else v['auctions']
        eligible|=any(r['trade_state'] in {'closed','expired'} and r['expires']<=0 and r['bid_state'] in {'none','outbid'} and r['native_is_won'] is False for r in rows)
    for cid in e.operations.get('clear_lost',[]):
        acknowledged=True
        try:c,v=e.get(cid,'clear_lost')
        except ValueError:
            raw=e.db.execute('SELECT body FROM c4_commands WHERE id=?',(cid,)).fetchone()
            need(raw is not None,'cleanup_unknown_intent_missing')
            c=json.loads(raw[0]);delivery_command(c);acknowledged=False;v=None
        p=c['params'];bc,before=e.get(p['before_read_id'],'watched')
        need(bc['schema']==2 and bc['context']==c['context'] and bc['fences']==c['fences'],'cleanup_native_before_scope')
        rows=before['result']['auctions'];expected={key(r) for r in rows if r['trade_state'] in {'closed','expired'} and r['expires']<=0 and r['bid_state'] in {'none','outbid'} and r['native_is_won'] is False}
        targets={(t['trade_id'],t['item_id'],t['definition_id']) for t in p['targets']}
        need(targets==expected and targets,'cleanup_exact_all_eligible')
        row=e.db.execute('SELECT state,dispatched_at,completed_at,proof FROM c4_work WHERE id=?',(cid,)).fetchone()
        need(row and row[0]=='CONFIRMED' and row[1] and row[2] and row[3],'cleanup_durable_readback_required')
        proof=json.loads(row[3]);after=proof['after'];ac,av=e.get(after['command_id'],'watched')
        boundary=observed(c,v) if acknowledged else at(row[2])
        need(ac['schema']==2 and after==av and ac['context']==c['context'] and ac['fences']==c['fences'] and after['command_id']!=before['command_id'] and network_at(ac,av)>=boundary,'cleanup_independent_fresh_readback')
        need({key(r) for r in av['result']['auctions']}=={key(r) for r in rows}-targets,'cleanup_unrelated_identity_preservation')
        need(proof.get('mode')==('NATIVE_ACK_AND_READBACK' if acknowledged else 'CURRENT_ABSENCE_AFTER_UNKNOWN'),'absence_is_not_native_ack')
        (confirmed if acknowledged else resolved_unknown).append(cid)
    need(not eligible or confirmed,'eligible_native_lost_cleanup_not_yet_proven')
    return dict(eligible=eligible,confirmed=confirmed,resolved_unknown=resolved_unknown)


def regression_evidence():
    from record_00405 import commands
    summary={}
    for group,pattern in [('python','python*'),('node','node*'),('independent','independent*')]:
        paths=list((ROOT/'docs/research/005/checks').glob('stage*/'+pattern+'/results.json'))
        need(paths,'full_regression_receipt_missing_'+group)
        # Latest completed run, including failures: never hide a red run by
        # selecting an older passing receipt.
        path=max(paths,key=lambda p:max(r['finished'] for r in json.loads(p.read_text())['results']))
        value=json.loads(path.read_text());rows=value['results']
        expected=[['{python}' if a==sys.executable else a for a in argv] for argv in commands(group)]
        need(value['status']=='PASS' and [r['command'] for r in rows]==expected,'latest_full_inventory_not_passed_'+group)
        count=0
        for row in rows:
            need(row['exit_code']==0 and row['seconds']>0,'regression_command_failed')
            for name in ('stdout','stderr'):
                target=(path.parent/row[name]).resolve()
                need(target.is_relative_to(path.parent.resolve()) and target.is_file(),'regression_output_missing')
            stderr=(path.parent/row['stderr']).read_text()
            if group=='python':
                parsed=re.findall(r'Ran (\d+) tests? in',stderr)
                need(parsed and sum(map(int,parsed))==row['tests_run']>=1107 and stderr.rstrip().endswith('OK') and
                     '... skipped' not in stderr,'python_result_does_not_match_receipt')
            count+=row['tests_run']
        summary[group]=dict(receipt=path.relative_to(ROOT).as_posix(),commands=len(rows),python_executions=count)
    for script in ('check_005_stage01.py','check_005_stage02.py','check_005_stage03.py','check_005_stage04.py','check_005_stage05.py','check_005_stage06.py','check_005_stage07.py','check_005_stage08.py','check_005_stage09.py','check_005_stage10.py','check_005_stage11.py','check_005_stage12.py','check_005_stage13.py','check_005_stage14.py','check_005_stage14_probe.py','check_005_stage15.py','check_005_cleanup_probe_bounds.py','check_005_stage16.py','check_005_stage17.py','check_005_stage17_reconciliation.py'):
        result=subprocess.run([sys.executable,str(ROOT/'tests'/script)],cwd=ROOT,capture_output=True,text=True,timeout=30 if script=='check_005_stage14.py' else 15)
        need(result.returncode==0,'incident_or_consumed_window_audit_failed_'+script)
    return summary


def published():
    def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=15).strip()
    need(git('branch','--show-current')=='main' and not git('status','--porcelain'),'final_tree_not_clean_main')
    revision=git('rev-parse','HEAD');remote=git('ls-remote','origin','refs/heads/main').split()
    need(len(remote)==2 and remote[0]==revision,'final_commit_not_pushed_to_main')
    need((ROOT/'docs/research/005/REPORT.md').is_file(),'final_report_missing')
    return revision


def retained_lifecycle():
    directory=ROOT/'private-captures/controller-v1/operational';state=read(directory/'state.json');gen=state['generation']
    need(health(directory,TASK,gen)['status']=='healthy','required_final_runtime_not_healthy')
    events=[json.loads(s) for s in Path(state['log']).read_text().splitlines()]
    need(events[0]['kind']=='STARTED' and events[0]['generation']==gen,'runtime_generation_unbound')
    ids=[];phases={};phase=None
    for event in events:
        need(event['kind'] not in {'STOPPED','STOP_REQUESTED','STOP_FAILED','EXCEPTION'},'final_generation_stopped')
        if event['kind']!='WORKER':continue
        m=event['message'];phase=m.get('phase',phase)
        if m['kind']=='native_result':ids.append(m['command_id']);phases[m['command_id']]=phase
    need(len(ids)==len(set(ids)),'duplicate_dispatch')
    db=sqlite3.connect((ROOT/'private-captures/controller-v1/controller.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        e=Evidence(db,ids,phases);results=[];failures=[]
        for cid in ids:
            row=db.execute("SELECT json_extract(body,'$.operation') FROM c4_commands WHERE id=?",(cid,)).fetchone()
            if not row or row[0]!='bid' or phases[cid]!='ACQUIRING':continue
            try:results.append(audit_chain(e,cid))
            except ValueError as error:failures.append(str(error))
        need(results,'full_genuine_lifecycle_not_observed: '+','.join(sorted(set(failures))))
        maintenance=audit_maintenance(e)
        lost_cleanup=audit_lost_cleanup(e)
    finally:db.close()
    need(health(directory,TASK,gen)['status']=='healthy','runtime_not_healthy_after_audit')
    return dict(generation=gen,lifecycles=results,maintenance=maintenance,lost_cleanup=lost_cleanup,
                regressions=regression_evidence(),published_commit=published())


def self_test():
    from controller_work_fixture import harness,won,WorkEA
    from controller_policy_fixture import SyntheticEA,auction
    from fc_access.production_v1.contracts import empty_result,ROUTES
    from unittest.mock import patch
    original=SyntheticEA.shared
    def fixture_reply(world,c,when):
        # The historical WorkEA fixture deliberately tolerates missing write
        # replies. This audit's positive scene additionally needs an explicit
        # valid synthetic wire/service reply, while preserving actual effects.
        if c['operation'] not in {'move','list','clear_sold','relist_all'}:return original(world,c,when)
        result=empty_result(None);method,route=ROUTES[c['operation']]
        result.update(success=True,status=200,network=[dict(method=method,path=route,host='utas.test.ea.com',query={},status=200,session_header_present=True)])
        return dict(schema=2,command_id=c['id'],operation=c['operation'],context=deepcopy(c['context']),fences=deepcopy(c['fences']),
            result=result,freshness=dict(observed_at=world.clock.now().isoformat(),network_at=when,request_count=1,read_id=c['id'],source='fixture'),
            coverage=dict(complete=False,has_more=None),timing=dict(native_service_ms=0))
    work_shared=WorkEA.shared
    def fixture_bulk_reply(world,c,when):
        value=work_shared(world,c,when)
        if c['operation'] in {'clear_sold','relist_all'}:
            for request in value['result']['network']:request['body_empty']=True
        return value
    with tempfile.TemporaryDirectory() as path,patch('socket.socket',side_effect=AssertionError('offline audit has no network')),patch.object(SyntheticEA,'shared',fixture_reply),patch.object(WorkEA,'shared',fixture_bulk_reply):
        h=harness(path,2)
        try:
            h.controller.step()
            h.ea.rows[0].update(bid_state='outbid',current_bid=200)
            h.controller.step()
            won(h);h.controller.step();h.controller.step()
            for n,state in enumerate(('closed','expired')):
                row=auction(123,15000,9000+n)
                row.update(trade_state=state,bid_state='none',expires=-1,current_bid=15000 if state=='closed' else 0,native_is_won=False)
                h.ea.inventory.append(row)
            h.ea.save();h.clock.value+=3661;h.controller.work.maintenance()
            ids=[r[0] for r in h.store.db.execute('SELECT id FROM c4_commands')]
            phases={call['command']['id']:call['phase'] for call in h.ea.calls}
            initial=h.calls('bid')[0]['command']['id'];e=Evidence(h.store.db,ids,phases,live=False)
            need(audit_chain(e,initial)['work']==['move','list'],'positive_offline_lifecycle')
            need(audit_chain(e,initial)['confirmed_rebids'],'positive_offline_rebid')
            need(audit_maintenance(e)['confirmed']==['clear_sold','relist_all'],'positive_offline_bulk_maintenance')
            failures=0
            for mode in ('receipt','confirmation','ownership','duration','listing','fixture_live_gate','bulk_targets','bulk_prices'):
                changed=Evidence(h.store.db,ids,dict(phases),live=mode=='fixture_live_gate')
                changed.cache=deepcopy(e.cache)
                if mode=='receipt':changed.cache[initial][1]['receipt']['verdict']='UNCONFIRMED'
                elif mode=='confirmation':
                    for cid,(c,v) in changed.cache.items():
                        if c['operation']=='status_batch' and network_at(c,v)>observed(*changed.cache[initial]):
                            for r in v['auctions']:r['bid_state']='none'
                elif mode=='ownership':
                    for c,v in changed.cache.values():
                        if c['operation']=='owned_item':v['result']['items'][0]['last_sale_price']+=50
                elif mode=='duration':
                    for c,v in changed.cache.values():
                        if c['operation']=='list':c['params']['duration']=7200
                elif mode=='listing':
                    for c,v in changed.cache.values():
                        if c['operation']=='transfer_list':
                            for r in v['result']['auctions']:
                                if r['trade_state']=='active':r['buy_now_price']+=250
                elif mode=='bulk_targets':
                    for c,v in changed.cache.values():
                        if c['operation']=='clear_sold':c['params']['expected_item_ids'].clear()
                elif mode=='bulk_prices':
                    for c,v in changed.cache.values():
                        if c['operation']=='transfer_list':
                            for r in v['result']['auctions']:r['buy_now_price']+=250
                try:
                    if mode.startswith('bulk_'):audit_maintenance(changed)
                    else:audit_chain(changed,initial)
                except (ValueError,KeyError,IndexError):failures+=1
                else:raise ValueError('negative_lifecycle_accepted_'+mode)
            return dict(status='OFFLINE_SELF_TEST_PASS_NOT_OPERATIONAL_EVIDENCE',negative_cases=failures)
        finally:h.ea.world.close();h.close()


if __name__=='__main__':
    try:print(json.dumps(self_test() if '--self-test' in sys.argv else dict(status='PASS',criterion=0,lifecycle=retained_lifecycle())))
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as error:
        print(json.dumps(dict(status='INCOMPLETE',criterion=0,diagnostic=str(error) if type(error) is ValueError else type(error).__name__)))
        raise SystemExit(1)
