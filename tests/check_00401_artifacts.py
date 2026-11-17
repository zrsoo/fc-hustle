"""Independent read-only 004-01 artifact checks; no capture, runtime or migration."""
import ast
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

from baseline_00401 import (ROOT, OUT, DATABASES, LEGACY, readonly,
                            control_projection, processes, idle_locks, inventory)
sys.path.insert(0, str(ROOT))

REQUIREMENTS = set('BASELINE BOUNDARIES TWO_PHASES ENTRY CREDIT_SCOPE DISCOVERY PRICING PROFIT SELECTION CAPACITY BURST HANDOFF REACQUIRE STATUS_BATCH LITE_VERSION ATTRIBUTION HOOK_CLEANUP MANAGEMENT REBID TERMINAL RESALE MAINTENANCE UNCERTAINTY REPLAY OWNER TRANSACTIONS PACING LIFECYCLE DIAGNOSTICS PROBES LEGACY HANDOFF_REPORT'.split())


def need(value, reason):
    if not value:
        raise ValueError(reason)


def load(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def validate_plan(plan):
    need(plan['task'] == '004-01' and plan['implementation_state'] == 'DESIGN_ONLY', 'scope')
    need(set(plan['phases']) == {'ACQUIRING','MANAGING'} and len(plan['phases']) == 2, 'phases')
    need(set(plan['lifecycle']) == {'STOPPED','RUNNING','PAUSED','HALTED'}, 'lifecycle')
    d = plan['defaults']
    need(d['entry_credits'] == 40000 and d['entry_comparison'] == '>', 'entry_rule')
    need(d['ea_request_spacing_seconds'] == 2 and d['spacing_centrally_configurable'] is True
         and d['local_helper_network_slots'] == 0, 'network_pacing')
    need(d['discovery'] == dict(page=1,count=21,platform='pc',type='player',maxBid=1000,minBuy=11000), 'discovery')
    expected = dict(selection_remaining_seconds_exclusive=60,max_initial_attempts=10,max_confirmed_members=10,
                    management_target_seconds=5,quote_cache_ttl_seconds=86400,profit_coins=500,tax_fraction=.05,
                    resale_duration_seconds=3600,relist_interval_seconds=3660,physical_capacity=50,known_pipeline_capacity=50)
    need(all(d[k] == v for k,v in expected.items()), 'policy_defaults')
    need(set(plan['forbidden_additions']) == {'sum_of_caps_funding_test','per_auction_budget_allocator','larger_lookahead',
         'acquisition_retry_timer','global_ambiguity_gate','parallel_ea_requests','pricing_strategy_change'}, 'forbidden_additions')
    rows = plan['requirements']
    need(len(rows) == len(REQUIREMENTS) and {r['id'] for r in rows} == REQUIREMENTS, 'policy_coverage')
    for r in rows:
        need(r['task'] in {'004-01','004-02','004-03','004-04','004-05'}, 'implementation_owner')
        need(r['criteria'] and set(r['criteria']) <= set(range(7)), 'criteria')
        for k in ['implementation','positive','negative']:
            need(isinstance(r[k],str) and len(r[k]) > 45, 'behavioral_cases')
    need(set().union(*(set(r['criteria']) for r in rows)) == set(range(7)), 'acceptance_coverage')
    need({r['criterion'] for r in plan['acceptance_map']} == set(range(7)) and len(plan['acceptance_map'])==7,
         'acceptance_artifacts')
    for r in plan['acceptance_map']:
        need(r['validator'] and r['artifacts'], 'artifact_link')
        for name in r['artifacts']: need((OUT/name).is_file(), 'missing_artifact')
    need(len(plan['inputs'])==9 and all((ROOT/p).is_file() for p in plan['inputs']), 'required_inputs')


def validate_probes(value):
    need(value['execution_state']=='PLANNED_NOT_EXECUTED', 'probe_state')
    need(value['activity_00401']==dict(ea_requests=0,mutations=0,browser_recovery=0), 'no_live_activity')
    need(set(value['prohibited'])=={'autonomous_controller','legacy_actors','scheduled_jobs','full_batch_lifecycle_e2e','soak'},
         'execution_boundary')
    common=value['common']
    for key in ['account','ownership','checkpoint_root','checkpoint_protocol','pre_mutation_intent',
                'independence','consumption','sanitization','recovery','cleanup','retest']:
        need(isinstance(common[key],str) and len(common[key])>50, 'probe_'+key)
    need('<exclusive-UTC-uuid>' in common['checkpoint_root'], 'exclusive_checkpoint')
    windows=value['windows']
    need(len(windows)==8 and len({w['id'] for w in windows})==len(windows), 'probe_windows')
    need(sum(w['required'] for w in windows)==1, 'mandatory_contract_probe')
    for w in windows:
        need(w['id'].startswith(('004-02-','004-04-')), 'future_window_scope')
        need(0<w['deadline_seconds']<=240 and 0<w['max_requests']<=12 and 0<=w['max_mutations']<=2, 'bounded_probe')
        need(sum(o['requests'] for o in w['operations'])==w['max_requests'], 'request_budget')
        need(sum(o['mutations'] for o in w['operations'])==w['max_mutations'], 'mutation_budget')
        need(all(type(o['requests']) is int and type(o['mutations']) is int and
                 0<=o['mutations']<=o['requests'] for o in w['operations']), 'operation_allocation')
        for k in ['question','trigger','outcome','cleanup']:
            need(isinstance(w[k],str) and len(w[k])>45, 'probe_'+k)
        if w['required']: need(w['max_mutations']==0 and '2..10' in w['operations'][1]['name'], 'read_only_multi_id')


def validate_reuse(value):
    need(len(value['imports'])>=17, 'reuse_inventory')
    for row in value['imports']:
        need(row['module'].startswith('fc_access.') and row['use'], 'reuse_boundary')
        module=importlib.import_module(row['module'])
        for symbol in row['symbols']: need(hasattr(module,symbol), 'missing_import:'+row['module']+'.'+symbol)
    need({r['seam'] for r in value['shared_changes']}=={
        'credits_freshness','uncertainty_gates','page_poisoning','supervisor_policy','protocol_and_executor'}, 'legacy_policy_seams')
    for row in value['shared_changes']:
        need(row['callers'] and len(row['new_mode'])>40 and len(row['legacy'])>30, 'caller_compatibility')
        for location in row['locations']:
            if ':' not in location:
                need((ROOT/location).is_file(), 'missing_shared_file'); continue
            mod, symbol=location.split(':')
            target=importlib.import_module(mod)
            for part in symbol.split('.'):
                need(hasattr(target,part), 'missing_shared_seam:'+location)
                target=getattr(target,part)


def baseline_and_backups():
    b=load('baseline.json'); directory=Path(b['backup_directory'])
    need(directory.is_dir() and directory.parent==ROOT.parent/'fc-hustle-backups', 'backup_location')
    need(b['git']['branch']=='main' and b['git']['status']=='?? tests/baseline_00401.py', 'baseline_status')
    need(b['activity']==dict(ea_requests=0,mutations=0,migrations=0,recovery=0), 'baseline_activity')
    need({r['source'] for r in b['databases']}==set(DATABASES), 'database_coverage')
    need(not b['processes']['listeners'] and not any(p['production_worker'] for p in b['processes']['processes']), 'baseline_workers')
    current=processes(); locks=idle_locks()
    need(not current['listeners'] and locks, 'current_workers')
    verify=subprocess.run(['git','bundle','verify',str(directory/'repository.bundle')],cwd=ROOT,capture_output=True,timeout=30)
    need(verify.returncode==0,'recoverable_git_bundle')
    with tempfile.TemporaryDirectory(prefix='00401-restore-') as temp:
        dest=Path(temp)
        with zipfile.ZipFile(directory/'working-tree.zip') as archive:
            names=archive.namelist()
            # Initial collector counted the trailing NUL's empty split entry.
            # Verify actual recoverable historical names, not that off-by-one.
            captured_names=subprocess.check_output(['git','ls-tree','-r','--name-only',b['git']['head']],cwd=ROOT).decode().splitlines()
            need(set(names)==set(captured_names), 'archive_inventory')
            need(not any(n.startswith(('.git/','.orchestrator/','private-captures/')) or '..' in Path(n).parts for n in names),
                 'archive_exclusions')
            # Recover and parse code; do not compare implementation bytes/hashes.
            for name in ['fc_access/production_v1/contracts.py','fc_access/bidding_v1/journal.py','AGENTS.md']:
                archive.extract(name,dest)
            for p in dest.rglob('*.py'): ast.parse(p.read_text(encoding='utf-8'))
            # Only sealed historical observations/verdicts/logs, never mutable code/configuration.
            evidence=[n for n in names if n.startswith('docs/research/') and
                      (n.endswith('.jsonl') or n.endswith('/REPORT.md') or n.endswith('/outcome.json') or
                       n.endswith('/incident.json') or n.endswith('/durable-ledger.json'))]
            need(len(evidence)>80,'historical_evidence_inventory')
            for name in evidence:
                need((ROOT/name).is_file() and archive.read(name)==(ROOT/name).read_bytes(), 'historical_evidence_changed:'+name)
        for row in b['databases']:
            source=directory/row['backup']
            with readonly(source) as old, readonly(ROOT/row['source']) as current_db:
                need(old.execute('PRAGMA integrity_check').fetchone()[0]=='ok', 'backup_integrity')
                need(inventory(old)==row['tables']==inventory(current_db), 'database_schema_or_counts_changed')
                restored=sqlite3.connect(dest/row['backup'])
                old.backup(restored)
                need(restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok','restored_database_integrity')
                restored.close()
                # Compare durable account records, not file bytes/WAL layouts or mutable source.
                for table in row['tables']:
                    left=old.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
                    right=current_db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
                    for record in left:
                        need(record==right.fetchone(), 'legacy_application_record_changed:'+table)
                    need(right.fetchone() is None,'legacy_application_record_added:'+table)
    return dict(databases=len(b['databases']),historical_evidence=len(evidence),idle_locks=len(locks))


def validate_preserved_control(old, current, transitions):
    """Preserve every historical row/checkpoint; permit audited scheduler no-ops.

    A paused task can acquire a same-state transition audit event on scheduler
    recovery. That adds no actor turn or state change. Every other addition and
    every alteration/removal of original records is still rejected.
    """
    added=[]
    need(set(old)==set(current),'legacy_control_tables')
    for table, value in old.items():
        need(value['columns']==current[table]['columns'],'legacy_control_columns')
        left={r[0]:r for r in value['rows']};right={r[0]:r for r in current[table]['rows']}
        need(len(left)==len(value['rows']) and len(right)==len(current[table]['rows']),'duplicate_control_record')
        need(all(key in right and right[key]==row for key,row in left.items()),'legacy_orchestration_records_changed')
        extra=[row for key,row in right.items() if key not in left]
        if table!='event':need(not extra,'legacy_control_record_added:'+table)
        else:added=extra
    need(set(transitions)=={row[0] for row in added},'unverified_transition_inventory')
    objectives={r[0]:r for r in current['objective']['rows']}
    tasks={r[0]:r for r in current['task']['rows']}
    for event in added:
        _,owner,turn_id,_,kind=event
        task=tasks.get(owner)
        need(task is not None and objectives[task[1]][1:3]==['PAUSED','pause'] and
             turn_id is None and kind=='transition','legacy_actor_activity')
        need(transitions[event[0]]==dict(previous=task[3],following=task[3],diagnostic=None,keys=['diagnostic','from','to']),
             'legacy_transition_changed_checkpoint')
    return len(added)


def legacy_preservation():
    b=load('baseline.json')
    old=json.loads((Path(b['backup_directory'])/b['orchestrator_backup']).read_text(encoding='utf-8'))
    with readonly(ROOT/'.orchestrator/state.db') as db:
        current=control_projection(db)
        original={r[0] for r in old['event']['rows']}
        transitions={}
        for row in current['event']['rows']:
            if row[0] in original:continue
            # Only explicit control-state fields, never provider/session payloads.
            before,after,diagnostic=db.execute("SELECT json_extract(data,'$.from'),json_extract(data,'$.to'),json_extract(data,'$.diagnostic') FROM event WHERE id=?",(row[0],)).fetchone()
            keys=sorted(r[0] for r in db.execute('SELECT j.key FROM event,json_each(event.data) j WHERE event.id=?',(row[0],)))
            transitions[row[0]]=dict(previous=before,following=after,diagnostic=diagnostic,keys=keys)
    noops=validate_preserved_control(old,current,transitions)
    objectives={r[0]:r for r in current['objective']['rows']}
    need(objectives[LEGACY[0]][1]=='BLOCKED','objective002_verdict')
    need(objectives[LEGACY[1]][1:3]==['PAUSED','pause'],'objective003_not_paused')
    task=next(r for r in current['task']['rows'] if r[1]==LEGACY[1] and r[2]=='003-04')
    # Parent pause is authoritative. Do not rewrite retained task RECONCILING.
    need(task[3:5]==['RECONCILING',None], 'paused_task_checkpoint_changed')
    verdict=json.loads((ROOT/'docs/research/002/002-12/review-05/outcome.json').read_text())
    need(verdict['status']=='PARTIAL/NOT FULL PASS','historical_partial_verdict')
    forbidden={'session','provider_turn','config','spec','text','result','data'}
    need(all(not forbidden.intersection(v['columns']) for v in old.values()), 'unsafe_orchestrator_projection')
    return dict(objective003='PAUSED',task00304='RECONCILING (preserved under paused parent)',objective002='BLOCKED/PARTIAL',appended_scheduler_noops=noops)


def main():
    validate_plan(load('plan.json')); validate_probes(load('probes.json')); validate_reuse(load('reuse.json'))
    report=(OUT/'REPORT.md').read_text(encoding='utf-8')
    design=(ROOT/'fc_access/controller_v1/DESIGN.md').read_text(encoding='utf-8')
    need(len(design)>12000 and len(report)>2500,'architecture_and_evidence_report')
    normalized=' '.join(design.lower().split())
    need(all(s.lower() in normalized for s in ['BatchAuthority','ControllerStore','ACQUIRING','MANAGING','short transaction',
                                  'no transaction or broad data lock','current-document','legacy','tombstone']), 'architecture_contract')
    result=dict(status='PASS',criteria=list(range(7)),baseline=baseline_and_backups(),legacy=legacy_preservation(),
                policies=len(REQUIREMENTS),planned_probes=8,live_requests=0)
    print(json.dumps(result))


if __name__=='__main__':
    main()
