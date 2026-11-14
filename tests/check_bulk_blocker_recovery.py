"""Independent passive acceptance of the blocker repair; zero native requests."""
from pathlib import Path
import json
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.actors_v1.final_run import load_evidence
from fc_access.production_v1.bulk_recovery import verify_effect
from fc_access.production_v1.bulk import mutation_authorized
from fc_access.production_v1.contracts import parse_response,stamp
from fc_access.production_v1 import gate_00203 as gate


def check():
    out=gate.ROOT/'docs/research/002/002-12/blocker-repair-02'
    rows=load_evidence(out/'recovery.jsonl')
    assert rows[-1]['kind']=='STOPPED' and rows[-1]['status']=='PASS'
    reads=[r for r in rows if r['kind']=='NATIVE_READ'];assert len(reads)==1
    read=reads[0];assert read['command']['operation']=='transfer_list' and read['command']['params']=={}
    parse_response(read['response'],read['command'],now=stamp(read['response']['freshness']['observed_at']))
    recovered=next(r for r in rows if r['kind']=='RECOVERY_VERIFIED');p=recovered['proof'];c=p['command']
    assert recovered['original_incompatible_preserved']==1 and recovered['pending_bulk']==[]
    assert recovered['original_state_now']=='RECONCILED' and recovered['no_redispatch_authority'] is True
    verify_effect(c,p['original_result'],p['before'],p['post'],started=p['started'],finished=p['finished'])
    assert p['current']==read['response'] and p['native_mutations']==0 and p['original_result']['result']['error']=='bulk_contract_changed'
    d=sqlite3.connect(gate.JOURNAL.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        state=d.execute('SELECT state,incompatible FROM bulk_writes_v1 WHERE id=?',(c['id'],)).fetchone()
        proof=d.execute('SELECT proof FROM bulk_recoveries_v1 WHERE id=?',(c['id'],)).fetchone()
    finally:d.close()
    assert state==('RECONCILED',1) and json.loads(proof[0])==p
    assert mutation_authorized(gate.JOURNAL,c,reconciled=True) and not mutation_authorized(gate.JOURNAL,c)
    assert recovered['supervisor_review']['context']==c['context']
    return dict(status='PASS',recovery='RECONCILED',fresh_inventory_reads=1,EA_mutations=0,
        original_failure_preserved=True,redispatch_authorized=False,supervisor_resume_review='PASS',
        full_item12_E2E='STILL_PARTIAL_REQUIRES_REMAINING_LIVE_BRANCHES')


if __name__=='__main__':print(json.dumps(check()))
