"""Independent final-interval acceptance (criterion 1). No account requests/writes.

Samples come from the scheduler; native outcomes come from the separate watchdog
log and actual correlated controller envelopes. A heartbeat or helper loop fails.
"""
from bisect import bisect_right
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.operational import health,read
from fc_access.controller_v1.protocol import delivery_response

TASK='obj-cb39371c785a/operate'
REQUIRED=14400


def need(value,reason):
    if not value:raise ValueError(reason)


def validate_samples(samples,natives,verified,*,generation,epoch,gap_limit=90):
    need(len(samples)>=2,'insufficient_monitor_samples')
    ticks=[]
    successes=sorted((n['tick'],n['command_id']) for n in natives if n.get('kind')=='native_result' and
                     n.get('success') is True and n.get('local') is False and n.get('command_id') in verified)
    need(bool(successes),'no_genuine_native_successes')
    native_ticks=[v[0] for v in successes]
    for sample in samples:
        need(sample['status']=='healthy' and sample['generation']==generation and sample['epoch']==epoch,'monitor_discontinuity')
        tick=sample['published_mono'];healthy=sample['healthy_seconds']
        need(type(tick) in (int,float) and type(healthy) in (int,float) and math.isfinite(tick) and math.isfinite(healthy),'invalid_monotonic_sample')
        if ticks:need(0<tick-ticks[-1]<=gap_limit,'unmonitored_gap_or_clock_regression')
        ticks.append(tick)
        index=bisect_right(native_ticks,tick)-1
        need(index>=0 and 0<=tick-native_ticks[index]<=90,'life_only_or_no_fresh_native_success')
        need(abs((tick-samples[0]['published_mono'])-(healthy-samples[0]['healthy_seconds']))<=5,'scheduler_monotonic_counter_mismatch')
    span=ticks[-1]-ticks[0]
    need(span>=REQUIRED and samples[-1]['healthy_seconds']>=REQUIRED,'four_hour_interval_incomplete')
    return dict(seconds=span,samples=len(samples),generation=generation,epoch=epoch,
                first_mono=ticks[0],last_mono=ticks[-1],verified_native_commands=len(verified))


def retained_interval(runtime_dir=None,orchestrator=None):
    runtime_dir=Path(runtime_dir or ROOT/'private-captures/controller-v1/operational')
    value=read(runtime_dir/'state.json');generation=value['generation']
    current=health(runtime_dir,TASK,generation)
    need(current['status']=='healthy','required_owned_service_not_healthy')
    path=Path(orchestrator or ROOT/'.orchestrator/state.db').resolve()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        row=db.execute('SELECT generation,epoch,healthy,monitor,last_mono,faulted FROM operation WHERE task_key=?',(TASK,)).fetchone()
        need(row is not None and row[0]==generation and row[2]>=REQUIRED and row[5]==0,'scheduler_interval_incomplete')
        epoch=row[1];spec=json.loads(row[3]);interval=spec['interval'];timeout=spec['check']['timeout']
        need(0<interval<=60 and 0<timeout<=60,'monitor_policy_not_bounded')
        samples=[];before=2**63-1;done=False
        while not done:
            rows=db.execute("SELECT id,json_extract(data,'$.report'),json_extract(data,'$.epoch'),json_extract(data,'$.healthy_seconds'),json_extract(data,'$.result.exit_code') FROM event WHERE owner=? AND kind='operational_health' AND id<? ORDER BY id DESC LIMIT 512",(TASK,before)).fetchall()
            need(bool(rows),'monitor_history_missing')
            for event_id,report,observed_epoch,healthy,exit_code in rows:
                before=event_id;report=json.loads(report)
                need(exit_code==0,'failed_health_command_inside_interval')
                need(report['status']=='healthy' and report['generation']==generation and observed_epoch==epoch,'final_interval_contains_restart_or_fault')
                evidence=report['evidence'][0]
                samples.append(dict(status=report['status'],generation=generation,epoch=observed_epoch,
                    healthy_seconds=healthy,published_mono=evidence['published_mono']))
                if len(samples)>1 and samples[0]['published_mono']-samples[-1]['published_mono']>=REQUIRED:
                    done=True;break
        samples.reverse()
        need(0<=row[4]-samples[-1]['published_mono']<=5,'scheduler_sample_not_current')
    finally:db.close()
    # Snapshot only complete log lines; the healthy service continues running.
    path=Path(value['log']);size=path.stat().st_size
    with path.open('rb') as stream:raw=stream.read(size)
    lines=raw.splitlines()
    if raw and not raw.endswith(b'\n'):lines=lines[:-1]
    events=[json.loads(line) for line in lines]
    started=[e for e in events if e['kind']=='STARTED']
    need(len(started)==1 and started[0]['generation']==generation,'watchdog_generation_not_bound')
    need(not any(e['kind'] in {'STOP_REQUESTED','STOPPED','STOP_FAILED','EXCEPTION'} for e in events),'final_watchdog_generation_faulted')
    natives=[e['message'] for e in events if e['kind']=='WORKER' and e['message']['kind']=='native_result']
    need(len({n['command_id'] for n in natives})==len(natives),'duplicate_native_dispatch')
    # Independently parse actual source envelopes at their original timestamps.
    db=sqlite3.connect((ROOT/'private-captures/controller-v1/controller.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    verified=set()
    try:
        for n in natives:
            if n.get('success') is not True or n.get('local') is not False:continue
            stored=db.execute('SELECT body,state,result FROM c4_commands WHERE id=?',(n['command_id'],)).fetchone()
            need(stored is not None and stored[1]=='DONE' and stored[2],'native_command_evidence_missing')
            c,v=json.loads(stored[0]),json.loads(stored[2])
            at=v['observed_at'] if c['schema']==4 else v['freshness']['observed_at']
            delivery_response(v,c,now=datetime.fromisoformat(at))
            payload=v if c['schema']==4 else v['result']
            need(payload['success'] is True and payload['network'] and
                 all(r['status']==200 and r['session_header_present'] is True for r in payload['network']),'native_success_not_bound_to_wire')
            if c['schema']==2:need(v['freshness']['source']=='native','fixture_cannot_prove_live_operation')
            need(n.get('diagnostic_records',0)>0,'missing_native_diagnostic_evidence')
            verified.add(c['id'])
    finally:db.close()
    summary=validate_samples(samples,natives,verified,generation=generation,epoch=epoch,gap_limit=2*interval+timeout)
    # Recheck actual ownership/freshness after auditing retained evidence.
    need(health(runtime_dir,TASK,generation)['status']=='healthy','required_service_stopped_during_audit')
    return summary


def self_test():
    samples=[dict(status='healthy',generation='a'*32,epoch='fixture-epoch',healthy_seconds=n,published_mono=1000+n) for n in range(0,REQUIRED+1,30)]
    natives=[dict(kind='native_result',success=True,local=False,tick=s['published_mono']-1,command_id=f'{i:032x}') for i,s in enumerate(samples)]
    verified={n['command_id'] for n in natives}
    run=lambda s,n,v:validate_samples(s,n,v,generation='a'*32,epoch='fixture-epoch')
    need(run(samples,natives,verified)['seconds']==REQUIRED,'positive_fixture')
    rejected=0
    for mode in ('short','gap','generation','epoch','repair','helper_only','unverified','stale_native'):
        s,n,v=deepcopy(samples),deepcopy(natives),set(verified)
        if mode=='short':s=s[:-1]
        elif mode=='gap':del s[10:20]
        elif mode=='generation':s[20]['generation']='b'*32
        elif mode=='epoch':s[20]['epoch']='other-epoch'
        elif mode=='repair':s[20]['status']='repair'
        elif mode=='helper_only':
            for record in n:record['local']=True
        elif mode=='unverified':v.clear()
        else:n=n[:1]
        try:run(s,n,v)
        except ValueError:rejected+=1
        else:raise ValueError('invalid_interval_accepted')
    return dict(status='OFFLINE_SELF_TEST_PASS_NOT_OPERATIONAL_EVIDENCE',negative_cases=rejected)


if __name__=='__main__':
    try:print(json.dumps(self_test() if '--self-test' in sys.argv else dict(status='PASS',criterion=1,interval=retained_interval())))
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as error:
        print(json.dumps(dict(status='INCOMPLETE',criterion=1,diagnostic=str(error) if type(error) is ValueError else type(error).__name__)))
        raise SystemExit(1)
