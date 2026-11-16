"""Scoped operator-incident evidence check; never overall live task acceptance."""
from contextlib import closing
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from check_00304_live import load,assess_task,need
from fc_access.continuous_v1.evidence import read_db,records,assess
from fc_access.production_v1.contracts import stamp


def check():
    p=ROOT/'docs/research/003/003-04/production-05'
    d=load(p/'incident-export-label-01.json');launch=load(p/'launch.json');fixed=load(p/'exporter-launch.json')
    need(d['root_cause'] and d['triggering_command'] and d['evidence'] and d['unknown_account_effects'],
         'operator_incident_incomplete')
    need(d['known_account_effects']['exporter_EA_requests']==0 and
         d['known_account_effects']['exporter_account_mutations']==0 and d['fix']['old_exited'],
         'unsafe_exporter_correction')
    need(d['fix']['old_pid']!=d['fix']['replacement_pid'] and d['fix']['correct_revision']==launch['revision'],
         'incorrect_replacement_identity')
    bad_events=[json.loads(line) for line in (ROOT/d['fix']['invalid_output_preserved']/'events.jsonl').read_text().splitlines()]
    bad=Path(next(r['path'] for r in reversed(bad_events) if r['kind']=='CAPTURED'))
    valid=Path(d['restart_reconciliation']['corrected_capture'])
    old=load(bad/'manifest.json');good=load(valid/'manifest.json')
    need(old['run']==good['run']==d['run'] and old['revision']!=launch['revision'] and
         good['revision']==launch['revision'],'invalid_capture_was_not_isolated')
    report=assess(valid)
    need(report['evidence_class']=='NATIVE_CAPTURE_REQUIRES_CASE_REVIEW','not_native_capture')
    with closing(read_db(valid/'control.sqlite3')) as db:rows=records(db)
    first=next(r for r in rows if r['run']==d['run'] and r['kind']=='STOP_REQUESTED')
    need(stamp(first['at'])<stamp(fixed['at']),'operator_correction_stop_chronology_wrong')
    index=load(p/'stopped-evidence-index.json')
    index['export_events']=str(ROOT/d['fix']['invalid_output_preserved']/'events.jsonl')
    try:assess_task(index)
    except ValueError as error:need(str(error)=='wrong_current_run','wrong_invalid_export_rejection')
    else:raise ValueError('invalid_revision_capture_accepted')
    return dict(status='PASS',scope='OPERATOR_EXPORT_METADATA_CORRECTION_ONLY',invalid_capture_rejected=True,
                earlier_runtime_stop_preserved=True,task_completion_claimed=False)


if __name__=='__main__':
    try:result=check()
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as error:
        print(json.dumps(dict(status='FAIL',scope='OPERATOR_EXPORT_METADATA_CORRECTION_ONLY',error_type=type(error).__name__)))
        raise SystemExit(1)
    print(json.dumps(result))
