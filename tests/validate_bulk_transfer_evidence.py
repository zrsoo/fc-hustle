"""Independent offline assessment of captured LIVE bulk transactions. No EA calls."""
import json
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.bulk_transfer_v1.server import validate_response
from fc_access.production_v1.contracts import stamp

OUT=ROOT/'docs/research/002-bulk-transfer-operations'


def need(value,reason):
    if not value:raise ValueError(reason)


def load(name):return json.loads((OUT/(name+'.json')).read_text(encoding='utf8'))


def validate():
    # Only sealed EA captures, journal/health snapshots and immutable check logs.
    # Never accept a source/config/implementation path from the manifest.
    captured={p.name for p in OUT.glob('*.json') if p.name!='evidence-manifest.json'}
    captured|={p.relative_to(OUT).as_posix() for p in (OUT/'checks').glob('check-*.txt')}
    captured.add('checks/results.json')
    manifest=load('evidence-manifest')
    need(manifest['scope']=='sealed_captures_and_verification_logs_only' and set(manifest['files'])==captured,'invalid_evidence_manifest_scope')
    for name,digest in manifest['files'].items():
        need(hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest,'captured_evidence_changed:'+name)
    ledger=load('durable-ledger');need(ledger['integrity']=='ok','journal_integrity')
    commands={r['id']:r for r in ledger['commands']}
    need(len(commands)==len(ledger['commands']),'duplicate_command')
    wire=[]
    for c in commands.values():
        need(c['state']=='ACKNOWLEDGED','unresolved_command')
        validate_response(c['result'],c['command'])
        need(c['result']['success'],'failed_native_operation')
        wire.extend(c['result']['network'])
    need(len(wire)==9,'native_request_count')
    for n in wire:
        need(n['status']==200 and n['session_header_present'] and n['query_empty'] and n['request_body'] is None and n['body_kind']=='empty','native_wire_not_verified')
    writes=[n for n in wire if n['method']!='GET']
    need(len(writes)==2 and [(n['method'],n['path']) for n in writes]==[
        ('DELETE','/ut/game/fc27/trade/sold'),('PUT','/ut/game/fc27/auctionhouse/relist')],'unexpected_or_duplicate_mutation')
    need(ledger['window']['reads']==6 and ledger['window']['inspections']==2,'budget_accounting')
    need(ledger['authorization']==dict(sold=5,expired=4),'expanded_authorization_not_recorded')
    need({i['operation']:i['state'] for i in ledger['intents']}=={'bulk_clear_sold':'CONFIRMED','bulk_relist_all':'CONFIRMED'},'durable_confirmation_missing')
    need(any('EXPLICIT_USER_AUTHORIZATION_REVISION' in e['event'] for e in ledger['events']),'user_revision_audit_missing')
    prior=load('initial-transfer-list');selected=load('selected-account-initial')
    need(prior['command']['context']!=selected['command']['context'],'prior_login_inventory_not_quarantined')
    outcomes={}
    for name,operation in [('clear-sold','bulk_clear_sold'),('relist-all','bulk_relist_all')]:
        before,mutation,after=load('before-'+name),load(name),load('after-'+name)
        for r in (before,mutation,after):
            need(commands[r['command']['id']]['result']==r['response'],'capture_vs_durable_journal_mismatch')
            need(r['command']['context']==selected['command']['context'],'wrong_selected_account')
            need(r['response']['success'],'unsuccessful_result')
        need(before['command']['fences']==mutation['command']['fences']==after['command']['fences'],'epoch_crossed_during_mutation')
        need(mutation['command']['operation']==operation,'wrong_operation')
        need(before['command']['id']!=after['command']['id'],'independent_read_missing')
        n=next(n for n in mutation['response']['network'] if n['method']!='GET')
        read=after['response']['network'][0]
        need(stamp(read['started_at'])>=stamp(n['ended_at']),'readback_not_after_mutation')
        need(stamp(n['started_at']).timestamp()<ledger['window']['deadline'],'expired_window_reused')
        old={r['item_id']:r for r in before['response']['inventory']['rows']}
        new={r['item_id']:r for r in after['response']['inventory']['rows']}
        for r in (before,after):
            inventory=r['response']['inventory']
            need(inventory['complete'] and inventory['repository_end_of_list'] and inventory['occupancy']==len(inventory['rows']),'incomplete_pile')
            raw={r['item_id']:r for r in r['response']['network'][0]['response']['auctions']}
            native={r['item_id']:r for r in inventory['rows']}
            need(raw==native,'native_vs_wire_inventory_mismatch')
        if operation=='bulk_clear_sold':
            target={r['item_id'] for r in old.values() if r['trade_state']=='closed' and r['current_bid']>0}
            need(len(target)==5 and set(new)==set(old)-target and len(old)==12 and len(new)==7,'sold_removal_not_verified')
            need(before['response']['inventory']['native_counts']==dict(sold=5,expired=4,active=3),'wrong_native_initial_states')
            need(after['response']['inventory']['native_counts']==dict(sold=0,expired=4,active=3),'unsold_entries_not_preserved')
            need(set(mutation['response']['callback']['item_ids'])==target,'native_clear_result_ids_disagree')
            need(len(mutation['response']['network'])==2,'unexpected_clear_fanout')
        else:
            target={r['item_id'] for r in old.values() if r['trade_state']=='expired' and r['current_bid']==0}
            need(len(target)==4 and set(new)==set(old) and len(new)==7,'relist_changed_physical_inventory')
            need(after['response']['inventory']['native_counts']==dict(sold=0,expired=0,active=7),'native_relist_states')
            for item_id in target:
                a,b=old[item_id],new[item_id]
                need(a['definition_id']==b['definition_id'] and a['trade_id']!=b['trade_id'],'identity_mapping_not_verified')
                need((a['starting_bid'],a['buy_now_price'])==(b['starting_bid'],b['buy_now_price']),'relist_changed_prices')
                need(b['expires']==3600 and b['trade_state']=='active' and b['current_bid']==0,'not_exactly_one_hour')
            need(set(n['response']['trade_ids'])=={new[i]['trade_id'] for i in target},'relist_wire_ids_disagree')
            need(len(mutation['response']['network'])==1,'relist_not_single_request')
        for item_id in set(old)-target:
            need(item_id in new and all(old[item_id][k]==new[item_id][k] for k in old[item_id] if k!='expires'),'unrelated_entry_modified')
            need(new[item_id]['expires']<=old[item_id]['expires'],'unrelated_expiry_increased')
        receipt=load(name+'-reconciliation')
        need(receipt['result']['outcome']=='CONFIRMED' and receipt['after_read_id']==after['command']['id'],'independent_confirmation_not_durable')
        outcomes[operation]='PASS'
    restored=load('restored-readonly-health')
    need(restored['service']=='fc-production-v1' and restored['mutations_enabled'] is False and restored['attached'],'normal_readonly_service_not_restored')
    return dict(status='PASS',capabilities=outcomes,explicit_EA_requests=9,GETs=7,mutation_requests=2,
        native_bulk_invocations=dict(clear_sold=1,relist_all=1),sold_removed=5,expired_relisted=4,
        prices_preserved=True,duration_seconds=3600,unrelated_active_preserved=3,
        scope='Actual four-item bulk relist after explicit expanded authorization; no scheduled jobs or actors.')


if __name__=='__main__':print(json.dumps(validate(),indent=2))
