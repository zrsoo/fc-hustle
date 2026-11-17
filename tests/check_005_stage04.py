"""Independent audit of the stopped first launch; never a completion verdict."""
from copy import deepcopy
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/research/005/stage04'


def need(value,reason):
    if not value:raise ValueError(reason)


def validate(state,events,scheduler,before,backup):
    generation=state['generation']
    need(state['state']=='STOPPED' and state['reason']=='OPERATIONAL_STOP','owned_stop_not_retained')
    need(events[0]['kind']=='STARTED' and events[0]['generation']==generation,'actual_generation_missing')
    messages=[r['message'] for r in events if r['kind']=='WORKER']
    need(not any(m['kind']=='native_result' for m in messages),'account_dispatch_occurred')
    stopped=events[-1]
    need(stopped['kind']=='STOPPED' and stopped['reason']=='OPERATIONAL_STOP' and stopped['forced'] is False,
         'cooperative_stop_missing')
    checks=[r['data'] for r in scheduler if r['kind']=='operational_health']
    need(len(checks)==1 and checks[0]['report']['status']=='repair' and
         checks[0]['report']['diagnostic']=='RUNTIME_STATE_UNAVAILABLE' and checks[0]['healthy_seconds']==0,
         'early_manifest_failure_not_honestly_preserved')
    stops=[r['data'] for r in scheduler if r['kind']=='operational_stop']
    need(len(stops)==1 and stops[0]['result']['exit_code']==0 and
         json.loads(stops[0]['result']['stdout'])==dict(status='stopped',generation=generation,diagnostic='OPERATIONAL_STOP'),
         'scheduler_stop_acknowledgement_missing')
    need(before['databases']['controller.sqlite']['tables']['c4_commands']==backup['safe_state']['commands']==530,
         'journal_changed_during_failed_startup')
    need(backup['safe_state']['pending_commands']==0 and backup['safe_state']['attempts']=={'ACKNOWLEDGED':1,'UNKNOWN':20} and
         backup['safe_state']['members']=={'ACTIVE':1},'uncertain_outcomes_or_confirmed_member_changed')
    need(backup['canonical_locks_held'] is True and all(v['integrity']=='ok' and v['row_comparison']=='equal' and
         v['foreign_key_errors']==0 for v in backup['databases'].values()),'fresh_quiescent_runtime_backup_missing')


def main():
    state=json.loads((OUT/'first-runtime-state.json').read_text())
    events=[json.loads(s) for s in (OUT/'first-runtime-events.jsonl').read_text().splitlines()]
    scheduler=json.loads((OUT/'first-runtime-scheduler.json').read_text())
    before=json.loads((ROOT/'docs/research/005/stage03/pre-service-backup.json').read_text())
    backup=json.loads((OUT/'backup.json').read_text())
    validate(state,events,scheduler,before,backup);negatives=0
    for mode in ('native_dispatch','false_health','forced_stop','lost_unknown'):
        s,e,q,b=deepcopy(state),deepcopy(events),deepcopy(scheduler),deepcopy(backup)
        if mode=='native_dispatch':e.insert(1,dict(kind='WORKER',message=dict(kind='native_result')))
        elif mode=='false_health':next(r for r in q if r['kind']=='operational_health')['data']['report']['status']='healthy'
        elif mode=='forced_stop':e[-1]['forced']=True
        else:b['safe_state']['attempts']['UNKNOWN']-=1
        try:validate(s,e,q,before,b)
        except ValueError:negatives+=1
        else:raise ValueError('negative_incident_accepted')
    print(json.dumps(dict(status='STAGE_VERIFIED_OBJECTIVE_INCOMPLETE',native_commands=0,unknowns_preserved=20,
                         healthy_seconds=0,negative_checks=negatives)))


if __name__=='__main__':main()
