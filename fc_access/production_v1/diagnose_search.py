"""One authorized diagnostic broad search; no pricing, gate, retry or fix."""
from copy import deepcopy
import hashlib,json,os,secrets,sqlite3,time
from pathlib import Path
from . import gate_00203 as gate
from .contracts import Search,parse_response
from .executor import EdgeExecutor
from .foundation import Foundation

OUT=gate.OUT/'adapter-diagnosis/20261114-01'
CHECKPOINT=OUT/'checkpoint.json'
TRANSPORT=gate.ROOT/'private-captures/002-bulk-transfer-operations/production-readonly-after.sqlite3'


def save(state):
    temp=CHECKPOINT.with_suffix('.tmp')
    with temp.open('w',encoding='utf8') as f:json.dump(state,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    temp.replace(CHECKPOINT)


class DiagnosticExecutor(EdgeExecutor):
    def __init__(self,state):super().__init__();self.state=state
    def execute(self,c):
        s=self.state
        if s['status']!='RUNNING' or time.monotonic_ns()>=s['deadline_ns']:raise ValueError('diagnostic_window_stopped')
        sequence=[('balance',{}),('search',Search.discovery().params())]
        index=len(s['operations'])
        if index>=2 or (c['operation'],c['params'])!=sequence[index]:raise ValueError('diagnostic_read_only_budget')
        e=dict(command=deepcopy(c),start_ns=time.monotonic_ns(),state='RESERVED_BEFORE_DELIVERY')
        s['operations'].append(e);save(s)
        try:
            value=parse_response(super().execute(c),c)
            e.update(state='RESPONSE_RECORDED',response=value,finish_ns=time.monotonic_ns())
            save(s)
            if not value['result']['success']:raise ValueError('native_read_failed_no_retry')
            return value
        except Exception:
            e.update(finish_ns=time.monotonic_ns());save(s);raise


def run():
    (gate.ROOT/'AGENTS.md').read_text(encoding='utf8')
    OUT.mkdir(parents=True,exist_ok=True)
    previous=[gate.CHECKPOINT,gate.REMEDIATION_CHECKPOINT,gate.THIRD_CHECKPOINT,gate.FOURTH_CHECKPOINT]
    s=dict(mode='READ_ONLY_ADAPTER_DIAGNOSIS_NOT_PERFORMANCE_GATE',status='RUNNING',started_at=gate.utc(),
        deadline_ns=time.monotonic_ns()+180_000_000_000,operations=[],account_mutations=0,
        authority='explicit_user_do_steps_1_2_3_report_root_cause_and_proposed_fix_before_execution',
        budget=dict(authentication_GETs=1,broad_discovery_GETs=1,pricing_GETs=0,helpers=0,valuations=0,retries=0),
        preserved_checkpoints={p.relative_to(gate.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in previous})
    with CHECKPOINT.open('x',encoding='utf8') as f:json.dump(s,f);f.flush();os.fsync(f.fileno())
    f=None
    try:
        s['desktop']=gate.desktop_preflight();h=EdgeExecutor().request('/health')
        if not h['attached'] or h['mutations_enabled'] is not False:raise ValueError('read_only_attachment_required')
        s.update(health_before=h,context=h['owner']['context']);save(s)
        f=Foundation(DiagnosticExecutor(s),context=s['context'],owner=h['owner']['owner'],
                     journal_path=gate.JOURNAL,cache_path=gate.CACHE,interval=2)
        s['fences']=deepcopy(f.adapter.fences);save(s)
        auth=f.read('balance');s['authentication_read_id']=auth['command_id'];save(s)
        search=f.read('search',Search.discovery().params());s['search_read_id']=search['command_id']
        s['status']='SEARCH_ACKNOWLEDGED'
    except Exception as error:
        s.update(status='DIAGNOSTIC_STOPPED_NO_RETRY',reason=str(error) if type(error) in {ValueError,TimeoutError} and str(error).replace('_','').isalnum() else type(error).__name__)
    finally:
        if f is not None:
            s['metrics']=deepcopy(f.executor.metrics+f.executor.local_metrics);f.close()
        s.update(finished_at=gate.utc(),finished_ns=time.monotonic_ns());save(s)
    # Passive local-only retention; no new browser/native command or retry.
    time.sleep(.5)
    db=sqlite3.connect(TRANSPORT.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        captures=[]
        for e in s['operations']:
            cid=e['command']['id'];r=db.execute('SELECT body,state,result FROM commands WHERE id=?',(cid,)).fetchone()
            if r:
                captures.append(dict(command=json.loads(r[0]),state=r[1],result=json.loads(r[2]) if r[2] else None,
                    events=[dict(sequence=a,event=json.loads(b) if b.startswith('{') else b) for a,b in db.execute('SELECT seq,event FROM events WHERE command_id=? ORDER BY seq',(cid,))]))
    finally:db.close()
    with (OUT/'transport.json').open('x',encoding='utf8') as f:json.dump(captures,f,indent=2)
    for p in previous:
        if hashlib.sha256(p.read_bytes()).hexdigest()!=s['preserved_checkpoints'][p.relative_to(gate.ROOT).as_posix()]:raise ValueError('previous_checkpoint_changed')
    return dict(status=s['status'],reason=s.get('reason'),commands=len(s['operations']),transport_records=len(captures))


if __name__=='__main__':print(json.dumps(run()))
