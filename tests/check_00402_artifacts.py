"""Offline independent checks of sealed live observations and bounded probe history."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.protocol import parse_response
from fc_access.production_v1.contracts import stamp

OUT=ROOT/'docs/research/004/004-02'


def need(value,reason):
    if not value:raise ValueError(reason)


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def window(path):
    events=[json.loads(line) for line in (path/'checkpoint.jsonl').read_text().splitlines()]
    result=load(path/'result.json')
    need(events[0]['kind']=='PREPARED' and events[-1]['kind']=='CLOSED','window_not_closed')
    prepared=events[0]
    need(prepared['window']==path.name and prepared['account']=='zzorniss','window_owner')
    need(prepared['max_requests']==result['max_requests']==3 and prepared['max_mutations']==result['max_mutations']==0,'budget_changed')
    need(result['mode']=='AUTHENTICATED_READ_ONLY' and result['account_mutations']==0,'read_only')
    need(all(stamp(a['at'])<=stamp(b['at']) for a,b in zip(events,events[1:])),'checkpoint_order')
    reserved={};responses=[];actual=0
    for e in events:
        if e['kind']=='RESERVED_BEFORE_DELIVERY':
            c=e['command'];need(c['id'] not in reserved,'replayed_command')
            need(e['ordinal']==len(reserved)+1<=3,'reservation_budget')
            need(c['operation']==['watched','status_batch','watched'][len(reserved)],'operation_recipe')
            need(stamp(e['at'])<stamp(prepared['deadline']),'window_expired')
            reserved[c['id']]=c
        elif e['kind']=='NATIVE_RESULT':
            c=e['command'];v=e['response']
            need(reserved.get(c['id'])==c,'result_without_prior_reservation')
            need(c['id'] not in [x['command']['id'] for x in responses],'duplicate_delivery')
            parse_response(v,c,now=stamp(v['observed_at']))
            actual+=len(v['network']);responses.append(e)
            need(all(n['method']=='GET' and '.test.' not in n['host'] for n in v['network']),'fixture_or_write_in_live_evidence')
    need(len(reserved)==result['reserved_requests'] and actual<=len(reserved)<=3,'consumption_mismatch')
    need(events[-1]['result']==result,'closed_projection_mismatch')
    cleanup=result['cleanup']
    need(cleanup==dict(service_thread_stopped=True,pending_commands=0,controllers_started=0,mutations_enabled=False),'temporary_activity_not_stopped')
    with closing(sqlite3.connect((path/'transport.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
        need(db.execute("SELECT count(*) FROM c4_commands WHERE state IN ('WAITING','CLAIMED')").fetchone()[0]==0,'pending_native_work')
        need(db.execute('SELECT count(*) FROM c4_tombstones').fetchone()[0]==0,'live_mutation_tombstone')
        for e in responses:
            row=db.execute('SELECT body,result FROM c4_commands WHERE id=?',(e['command']['id'],)).fetchone()
            need(row and json.loads(row[0])==e['command'] and json.loads(row[1])==e['response'],'database_evidence_mismatch')
    return result,responses,list(reserved)


def successful(result,responses):
    need(result['status']=='LIVE_VERIFIED_WITH_ACTUAL_LIMIT' and result['reserved_requests']==3,'not_live_verified')
    need(len(responses)==3,'three_native_results_required')
    full,batch,comparison=[e['response'] for e in responses]
    commands=[e['command'] for e in responses]
    need(all(v['success'] and v['designated_account_verified'] for v in (full,batch,comparison)),'authenticated_account_binding_required')
    need(all(v['context']==full['context'] and v['fences']==full['fences'] for v in (batch,comparison)),'live_scope_changed')
    requested=commands[1]['params']['targets']
    need(result['actual_target_count']==len(requested)==10,'ten_real_targets_required')
    need(result['requested']==requested and result['missing']==batch['missing']==[],'requested_or_omitted_projection_mismatch')
    need(len(batch['network'])==1 and batch['network'][0]['targets']==requested and batch['network'][0]['path']=='/ut/game/fc27/trade/status/lite','exact_one_get_required')
    need(len(full['network'])==len(comparison['network'])==1 and sum(len(v['network']) for v in (full,batch,comparison))==3,'actual_three_GET_budget')
    need(len(batch['auctions'])==10 and len({r['trade_id'] for r in batch['auctions']})==10,'returned_cardinality')
    projected=[dict(trade_id=r['trade_id'],item_id=r['item']['item_id'],definition_id=r['item']['definition_id'],trade_state=r['trade_state'],
        bid_state=r['bid_state'],current_bid=r['current_bid'],expires=r['expires']) for r in batch['auctions']]
    need(result['returned']==projected,'returned_projection_mismatch')
    need(result['network']==batch['network'] and result['links']==batch['links'],'summary_evidence_mismatch')
    need(result['comparison_count']==len(comparison['auctions']) and result['comparison_success'],'independent_comparison')
    need(stamp(full['observed_at'])<stamp(batch['network_at'])<stamp(comparison['network_at']),'reads_not_independent')
    for t,row,link in zip(requested,batch['auctions'],batch['links']):
        need((row['trade_id'],row['item']['item_id'])==(t['trade_id'],t['item_id']),'returned_wrong_pair')
        originals=[r for r in full['auctions'] if (r['trade_id'],r['item']['item_id'],r['item']['definition_id'])==(t['trade_id'],t['item_id'],t['definition_id'])]
        later=[r for r in comparison['auctions'] if (r['trade_id'],r['item']['item_id'],r['item']['definition_id'])==(t['trade_id'],t['item_id'],t['definition_id'])]
        need(len(originals)==len(later)==1,'retained_and_later_full_identity_required')
        need(row['item']['definition_id']==0 and link['version_observed'] is False,'original_lite_version_was_rewritten')
        need(link['target']==t and link['full_read_id']==commands[0]['id'] and link['status_read_id']==commands[1]['id'] and link['full_observed_at']==full['network_at'] and link['current_dto_matches'] is True,'full_version_DTO_link')
        need(row['trade_state']==later[0]['trade_state']=='closed' and row['bid_state']==later[0]['bid_state']=='outbid' and row['current_bid']==later[0]['current_bid'],'independent_status_comparison')
    need(set(result['untested_limits'])=={'live_interleaving','live_error_branches','live_mutations_new_authority'},'limits_must_be_explicit')


def validate():
    selection=load(OUT/('final-verification.json' if (OUT/'final-verification.json').exists() else 'verification.json'))
    # Only captured EA responses, finite experiment DBs/checkpoints and sealed
    # historical evidence are hashed. No mutable implementation/config/test files.
    sealed=set()
    for manifest_name in selection.get('evidence_manifests',['sealed-evidence.json']):
        manifest=load(OUT/manifest_name)
        for name,digest in manifest['sha256'].items():
            path=OUT/name
            need(path.suffix in {'.json','.jsonl','.sqlite'} and path.parent.name.startswith('status-array-'),'non_evidence_integrity_gate')
            need(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'captured_evidence_changed:'+name)
            sealed.add(name)
    need(selection['task']=='004-02' and selection['status']=='DONE_WITH_EXPLICIT_LIVE_LIMITS','task_verdict')
    paths=sorted(OUT.glob('status-array-*'))
    need(len(paths)==len(selection['windows']) and [p.name for p in paths]==[w['window'] for w in selection['windows']],'history_dropped')
    ids=set();selected=None;actual=0;reserved=0
    for path,entry in zip(paths,selection['windows']):
        result,responses,commands=window(path)
        need(all(path.name+'/'+name in sealed for name in ['checkpoint.jsonl','result.json','transport.sqlite']),'window_not_sealed')
        actual+=sum(len(e['response']['network']) for e in responses);reserved+=result['reserved_requests']
        need(entry['reserved_requests']==result['reserved_requests'] and entry['status']==result['status'],'historical_verdict_changed')
        need(not ids.intersection(commands),'commands_replayed_across_windows');ids.update(commands)
        if result['status']=='LIVE_VERIFIED_WITH_ACTUAL_LIMIT':successful(result,responses)
        if path.name==selection['selected_window']:selected=(result,responses)
    need(selected is not None,'selected_window_missing');successful(*selected)
    need(selection['total_actual_EA_GETs']==actual and selection['total_reserved_requests']==reserved and selection['total_mutations']==0,'total_budget_mismatch')
    account=load(OUT/'account-selection.json')
    need(account['credential_values_read_or_retained'] is False and any(e.get('saved_designated_suggestion') is True for e in account['events']),'designated_UI_selection_missing')
    need(any(e['action'].startswith('select unique visible zzorniss') and e['foreground_verified'] and e['official_login'] for e in account['events']),'saved_account_not_selected')
    need(any(e.get('official_app') and e['foreground_verified'] for e in account['events']),'login_return_not_verified')
    coverage=selection['contracts']
    need(len(coverage)==8 and {c['criterion'] for c in coverage}==set(range(8)),'acceptance_contract_coverage')
    for row in coverage:need(row['offline_evidence'] and row['live_evidence_or_limitation'],'unsubstantiated_contract')
    offline=load(OUT/selection['offline_results'])
    need(len(offline['results'])>=30 and all(r['exit']==0 for r in offline['results']),'offline_regression_failed')
    cleanup=load(OUT/selection.get('cleanup','cleanup.json'))
    need(not cleanup['processes']['listeners'] and not any(p['production_worker'] for p in cleanup['processes']['processes']),'production_activity_left_running')
    return dict(status='PASS',selected_window=selection['selected_window'],real_targets=10,omissions=0,mutations=0)


class EvidenceChecks(unittest.TestCase):
    def test_c6_c7_genuine_retained_projections_budgets_and_limits(self):self.assertEqual(validate()['status'],'PASS')

    def test_c6_negative_wrong_identity_omission_version_and_unsubstantiated_success(self):
        selection=load(OUT/('final-verification.json' if (OUT/'final-verification.json').exists() else 'verification.json'));result,responses,_=window(OUT/selection['selected_window'])
        for edit in [lambda r,e:r.update(actual_target_count=9),lambda r,e:r.update(missing=r['requested'][:1]),
                     lambda r,e:e[1]['response']['auctions'][0]['item'].update(definition_id=r['requested'][0]['definition_id']),
                     lambda r,e:e[1]['response']['auctions'][0]['item'].update(item_id='item:'+'e'*24),
                     lambda r,e:e[1]['response'].update(network=e[1]['response']['network']*2),
                     lambda r,e:r.update(untested_limits=[]),lambda r,e:e[2]['response']['fences'].update(epoch=99)]:
            r,e=deepcopy(result),deepcopy(responses);edit(r,e)
            with self.assertRaises(ValueError):successful(r,e)

    def test_c7_exclusive_probe_cannot_reset_a_consumed_window(self):
        import tempfile
        from probe_00402_status import probe
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileExistsError):probe(td)


if __name__=='__main__':unittest.main(verbosity=2)
