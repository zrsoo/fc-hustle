"""Explicit consumed read-only recovery window. No bulk execution or actors."""
import json
from pathlib import Path
import secrets
import sqlite3
import time
from fc_access.production_v1 import gate_00203 as gate
from fc_access.production_v1.executor import EdgeExecutor
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.bulk_recovery import recover
from fc_access.production_v1.bulk import pending,mutation_authorized

OUT=gate.ROOT/'docs/research/002/002-12/blocker-repair-01'
CID='869ed95434e70ea0d7ba599945751fd2'
POST='6e33cd4b3db2b17b52792740a1948701'
TRANSPORT=gate.ROOT/'private-captures/002-bulk-transfer-operations/production-readonly-after.sqlite3'
MAILBOX=gate.JOURNAL.parent/'native.sqlite3'


class ReadOnly(EdgeExecutor):
    def __init__(self,evidence):super().__init__();self.evidence=evidence;self.deadline=time.monotonic()+180;self.consumed=False
    def execute(self,c):
        if self.consumed or time.monotonic()>=self.deadline or c['operation']!='transfer_list' or c['params']!={}:raise ValueError('one_read_only_inventory_budget')
        self.consumed=True;self.evidence.append('READ_INTENT',command=c)
        v=super().execute(c);self.evidence.append('NATIVE_READ',command=c,response=v);return v


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window',choices=['blocker-repair-01','blocker-repair-02'],default='blocker-repair-01')
    args=parser.parse_args()
    out=OUT.parent/args.window
    from fc_access.actors_v1.final_run import Evidence
    from fc_access.actors_v1.final_supervisor import review_resume
    (gate.ROOT/'AGENTS.md').read_text(encoding='utf8')
    out.mkdir(parents=True,exist_ok=True)
    with (out/'consumed.json').open('x',encoding='utf8') as file:
        json.dump(dict(mode='READ_ONLY_BULK_RECOVERY',command_id=CID,inventory_GET_budget=1,native_mutations=0,
            authority='explicit_user_fix_blocker_confirm_then_orchestrator_recheck'),file,indent=2)
    evidence=Evidence(out/'recovery.jsonl');f=None
    try:
        health=EdgeExecutor().request('/health')
        if health['mutations_enabled'] is not False or not health['attached']:raise ValueError('attached_read_only_service_required')
        evidence.append('OPENED',health=health,original_command_id=CID)
        f=Foundation(ReadOnly(evidence),context=health['owner']['context'],owner=secrets.token_hex(16),
            journal_path=gate.JOURNAL,cache_path=gate.CACHE,interval=2)
        result=recover(f,CID,transport_path=TRANSPORT,post_read_id=POST,mailbox_path=MAILBOX)
        row=f.journal.db.execute('SELECT body,state,incompatible FROM bulk_writes_v1 WHERE id=?',(CID,)).fetchone()
        command=json.loads(row[0]);allowed=mutation_authorized(gate.JOURNAL,command,reconciled=True)
        if result['status']!='RECONCILED' or not allowed or mutation_authorized(gate.JOURNAL,command):raise ValueError('recovery_authority_not_proven')
        proof=json.loads(f.journal.db.execute('SELECT proof FROM bulk_recoveries_v1 WHERE id=?',(CID,)).fetchone()[0])
        remaining=pending(f.journal,f.registry.scope)
        if remaining:raise ValueError('unresolved_bulk_intents_remain')
        reviewed=review_resume(gate.ROOT/'docs/research/002/002-12/remediation-05/live-06',MAILBOX,120)
        evidence.append('RECOVERY_VERIFIED',result=result,original_state_now=row[1],original_incompatible_preserved=row[2],
            no_redispatch_authority=True,proof=proof,pending_bulk=remaining,supervisor_review=reviewed)
        evidence.append('STOPPED',native_mutations=0,actors_started=0,status='PASS')
        print(json.dumps(dict(status='PASS',recovery=result,pending_bulk=remaining,supervisor_can_resume=True)))
        return 0
    except Exception as error:
        reason=str(error) if type(error) in {ValueError,TimeoutError} and str(error).replace('_','').isalnum() else type(error).__name__
        evidence.append('STOPPED',status='BLOCKED',reason=reason,native_mutations=0,actors_started=0)
        print(json.dumps(dict(status='BLOCKED',reason=reason)));return 1
    finally:
        if f:f.close()
        evidence.close()


if __name__=='__main__':raise SystemExit(main())
