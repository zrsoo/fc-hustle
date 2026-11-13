"""Seal new sanitized delivery evidence; read-only SQLite, no EA/browser calls.

Writes only previously absent 001d-05 artifacts. Never runs native probes.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/research/001d/001d-05'


def record():
    if (OUT/'evidence.json').exists() or (OUT/'transport-evidence.json').exists():
        raise ValueError('existing_evidence_preserved')
    r1 = json.loads((OUT/'r1-checkpoint.json').read_text())
    s1 = json.loads((OUT/'s1-checkpoint.json').read_text())
    captures = r1['observations'] + s1['observations'] + s1['source_inspections']
    ids = {x['command']['id'] for x in captures}
    if len(ids) != 9:
        raise ValueError('unexpected_command_count')
    db = sqlite3.connect('file:'+str(ROOT/'private-captures/001d03-production.sqlite')+'?mode=ro', uri=True)
    try:
        commands = []
        for x in captures:
            cid = x['command']['id']
            row = db.execute('SELECT body,state,result FROM commands WHERE id=?', (cid,)).fetchone()
            if not row or row[1] != 'ACKNOWLEDGED' or json.loads(row[0]) != x['command'] or json.loads(row[2]) != x['response']:
                raise ValueError('transport_capture_mismatch')
            events = [dict(seq=n, event=e) for n,e in db.execute('SELECT seq,event FROM events WHERE command_id=? ORDER BY seq',(cid,))]
            if [e['event'] for e in events] != ['RESERVED','DELIVERED','ACKNOWLEDGED']:
                raise ValueError('unexpected_delivery_events')
            commands.append(dict(command=x['command'], state=row[1], response=x['response'], events=events))
        # Account for all stored commands in this persistent service, including S2.
        inventory = [dict(id=cid, operation=json.loads(body)['operation'], state=state)
                     for cid,body,state in db.execute('SELECT id,body,state FROM commands ORDER BY rowid')]
    finally:
        db.close()
    (OUT/'transport-evidence.json').write_text(json.dumps(dict(task='001d-05', commands=commands, service_command_inventory=inventory),indent=2)+'\n')
    paths = [
        'browser/production-v1/page.js:execute', 'browser/production-v1/page.js:auction',
        'fc_access/production_v1/contracts.py:parse_response',
        'fc_access/production_v1/contracts.py:parse_status_support',
        'fc_access/production_v1/adapter.py:NativeAdapter',
        'fc_access/production_v1/adapter.py:NativeAdapter.known_status',
        'fc_access/production_v1/inventory.py:watched_status',
        'fc_access/production_v1/inventory.py:compare_lite_identity',
        'fc_access/production_v1/server.py:Server', 'fc_access/production_v1/store.py:Store']
    code = {p.split(':')[0] for p in paths} | {
        'fc_access/production_v1/investigate_reads.py', 'fc_access/production_v1/investigate_status.py',
        'tests/production_inventory_checks.cjs', 'tests/production_page_checks.cjs',
        'tests/test_001d05_inventory.py', 'tests/test_001d02_contract.py',
        'tests/record_001d05_evidence.py', 'AGENTS.md'}
    artifacts = {str(p.relative_to(ROOT)).replace('\\','/') for p in OUT.iterdir() if p.is_file()}
    # Existing task checkpoints are fingerprinted, never modified/replayed.
    artifacts |= {'docs/research/001d/001d-03/s2-checkpoint.json',
                  'docs/research/001d/001d-02/protocol.json',
                  'docs/research/001d/execution-plan.json',
                  'docs/research/001c/001c-06-resume-01/source-contract.json'}
    dependencies = [
        dict(id='002-STATUS-RECONNECT', prerequisite='A real enrolled exact native trade mapping reacquired after document/epoch change.',
             validation='Fresh full-identity read followed by independently correlated status GET under Objective 002 budget; absent mapping remains UNKNOWN.'),
        dict(id='002-STATUS-HISTORY', prerequisite='An available native ID plus retained exact identity in the same identity namespace, not an unrelated historical pseudonym.',
             validation='Read-only known-ID lookup with exact physical item and full-version proof, or explicit UNKNOWN when no native mapping is recoverable.'),
        dict(id='002-NATURAL-OUTCOMES', prerequisite='Naturally occurring enrolled outcomes and independent exact owned-item/paid-cost evidence.',
             validation='Verify missing rows stay UNKNOWN and closed/highest stays PENDING until independent ownership/cost proof; never create trades in 001D.')]
    value = dict(task='001d-05', recorded_at=datetime.now(timezone.utc).isoformat(),
                 new_native_requests=6, local_source_inspections=3, live_mutations=0,
                 objective_001d_native_requests_including_prior_s2=7,
                 prior_s2_helpers_consumed=8, r2_probes=0, production_paths=paths,
                 objective_002_dependencies=dependencies,
                 sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(code | artifacts)})
    (OUT/'evidence.json').write_text(json.dumps(value,indent=2)+'\n')
    print('Recorded nine acknowledged commands: six EA reads, three local inspections, zero mutations')


if __name__ == '__main__':
    record()
