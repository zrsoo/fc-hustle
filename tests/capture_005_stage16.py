"""One-time read-only capture of the scheduler-owned stage15 runtime prefix."""
from pathlib import Path
import hashlib,json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.operational import read,health,held,same_process

def main():
    out=ROOT/'docs/research/005/stage16'
    if out.exists():raise ValueError('capture_already_consumed')
    runtime=ROOT/'private-captures/controller-v1/operational';s=read(runtime/'state.json')
    if s['generation']!='6c2549d24df0b1155c3b8de951412965':raise ValueError('wrong_generation')
    raw=Path(s['log']).read_bytes();lines=raw.splitlines()
    if raw and not raw.endswith(b'\n'):lines=lines[:-1]
    events=[json.loads(line) for line in lines]
    ids=[e['message']['command_id'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    db=sqlite3.connect((ROOT/'private-captures/controller-v1/controller.sqlite').as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row;db.execute('BEGIN');records=[];attempts=[];batches={}
    try:
        for cid in ids:
            r=db.execute('SELECT body,state,result FROM c4_commands WHERE id=?',(cid,)).fetchone()
            records.append(dict(command=json.loads(r['body']),state=r['state'],response=json.loads(r['result']),diagnostics=[json.loads(g[0]) for g in db.execute('SELECT body FROM c4_diagnostics WHERE command_id=?',(cid,))]))
            a=db.execute('SELECT * FROM c4_attempts WHERE id=?',(cid,)).fetchone()
            if a:
                a=dict(a);a['body']=json.loads(a['body']);a['result']=json.loads(a['result']) if a['result'] else None;attempts.append(a)
                b=db.execute('SELECT state,body FROM c4_policy_batches WHERE id=?',(a['batch_id'],)).fetchone()
                batches[a['batch_id']]=dict(state=b['state'],body=json.loads(b['body']))
        prior=json.loads((ROOT/'docs/research/005/stage15/initial-unknowns.json').read_text())
        unknowns=[dict(db.execute('SELECT id,state FROM c4_attempts WHERE id=?',(r['id'],)).fetchone()) for r in prior]
    finally:db.close()
    snapshot=dict(runtime=s,health=health(runtime,s['task'],s['generation']),owner_held=held(runtime),supervisor_matches=same_process(s['supervisor']),child_matches=same_process(s['child']))
    if snapshot['health']['status']!='healthy':raise ValueError('not_semantically_healthy')
    od=sqlite3.connect((ROOT/'.orchestrator/state.db').as_uri()+'?mode=ro',uri=True)
    od.row_factory=sqlite3.Row
    try:
        row=dict(od.execute('SELECT generation,healthy,faulted,epoch FROM operation WHERE task_key=?',(s['task'],)).fetchone())
        row['legacy']=[dict(r) for r in od.execute('SELECT id,state,control FROM objective WHERE id IN (?,?)',('obj-da182a175410','obj-fefda5e912eb'))]
    finally:od.close()
    values={'snapshot.json':snapshot,'acquisition.json':dict(attempts=attempts,batches=batches,prior_unknowns=unknowns),'monitor-progress.json':row}
    out.mkdir(parents=True,exist_ok=False)
    for name,value in values.items():(out/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    (out/'commands.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf-8')
    (out/'events.jsonl').write_bytes(b'\n'.join(lines)+b'\n')
    seal=dict(scope='IMMUTABLE_CAPTURED_RUNTIME_AND_EA_EVIDENCE_ONLY',files=[dict(path=n,sha256=hashlib.sha256((out/n).read_bytes()).hexdigest()) for n in sorted([*values,'commands.jsonl','events.jsonl'])])
    (out/'sealed-evidence.json').write_text(json.dumps(seal,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(captured=len(ids),attempts=len(attempts),generation=s['generation'])))

if __name__=='__main__':main()
