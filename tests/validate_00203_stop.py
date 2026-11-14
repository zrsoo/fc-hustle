"""Offline assessment of the retained outcome and dependent-work hard stop."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1.gate_00203 import CHECKPOINT, digest, need, require_pass, Window, selected_checkpoint, validate_attempt, AUTHORIZED_ATTEMPT, THIRD_ATTEMPT, FOURTH_ATTEMPT, FIFTH_ATTEMPT, SIXTH_ATTEMPT
from unittest.mock import patch


def validate(path=None):
    path=Path(path if path is not None else selected_checkpoint())
    s=json.loads(path.read_text(encoding='utf-8'))
    validate_attempt(s)
    need(s['automatic_repairs'] is False and s['automatic_reruns'] is False,'automatic_repair_or_rerun')
    need(s['evidence_sha256']==digest({k:v for k,v in s.items() if k!='evidence_sha256'}),'sealed_experiment_changed')
    # The exclusive open must reject before any state can be reset.
    # mkdir exists already and opening with x fails without modifying the file.
    try:
        Window(path)
    except FileExistsError:
        pass
    else:
        raise ValueError('consumed_gate_reopened')
    if s['status']=='PASS':
        require_pass(path)
        return dict(status='PASS',attempt=s['attempt'],outcome='PASS',dependent_tasks_allowed=True,rerun_rejected=True)
    need(s['status']=='FAILURE/BLOCKED' and s['hard_stop'] is True and
         s['dependent_tasks_allowed'] is False and s.get('reason'),'missing_failure_stop')
    need(all(e.get('finish_ns',e['start_ns'])<=s['stopped_ns'] for e in s['operations']),'operation_after_stop')
    try:
        require_pass(path)
    except ValueError as e:
        need(str(e)=='gate_not_PASS_items_4_through_12_blocked','wrong_dependency_rejection')
    else:
        raise ValueError('failed_gate_allowed_dependent_work')
    return dict(status='PASS',attempt=s['attempt'],outcome='FAILURE/BLOCKED',dependent_tasks_allowed=False,rerun_rejected=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--original',action='store_true')
    group.add_argument('--attempt',choices=[AUTHORIZED_ATTEMPT,THIRD_ATTEMPT,FOURTH_ATTEMPT,FIFTH_ATTEMPT,SIXTH_ATTEMPT])
    args=parser.parse_args()
    print(json.dumps(validate(CHECKPOINT if args.original else selected_checkpoint(args.attempt))))
