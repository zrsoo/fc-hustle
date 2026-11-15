"""Independently assess witnessed branches in sealed native/transport captures.

Explicit --write updates the mutable current-run matrix and creates a new review
receipt. Historical reports/captures are never changed. This does not poll EA,
manufacture an event, promote an offline fixture, or stop for missing coverage.
"""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from check_00304_live import semantic_case,load,lines,need
from fc_access.continuous_v1.evidence import assess,read_db,records
from fc_access.production_v1.contracts import stamp


def review(index):
    run=index['run']
    exports=[r for r in lines(ROOT/index['export_events']) if r['kind']=='CAPTURED' and r['run']==run]
    snapshot=Path(exports[-1]['path'])
    report=assess(snapshot)
    need(report['evidence_class']=='NATIVE_CAPTURE_REQUIRES_CASE_REVIEW','fixture_is_not_live')
    need(report['revision']==index['run_revisions'][run],'wrong_runtime_revision')
    with closing(read_db(snapshot/'control.sqlite3')) as db:control=records(db)
    fences=next(r['body']['fences'] for r in control if r['kind']=='ATTACHED' and r['run']==run)
    with closing(read_db(snapshot/'journal.sqlite3')) as db:
        registry=[dict(seq=s,at=a,trade_id=t,**json.loads(b)) for s,a,t,b in db.execute(
            "SELECT seq,at,trade_id,body FROM registry_events_v1 WHERE json_extract(body,'$.epoch')=?",(fences['epoch'],))]
    values=[]
    with closing(read_db(snapshot/'native.sqlite3')) as db:
        for seq,c,v,a,b in db.execute("SELECT seq,command,response,started,finished FROM work WHERE state='DONE' AND response IS NOT NULL"):
            c,v=json.loads(c),json.loads(v)
            if c['fences']==fences and v['result']['success']:
                values.append(dict(seq=seq,run=run,command=c,response=v,started=a,finished=b))
    observations=dict(registry=registry,health=[r['body'] for r in control if r['run']==run and r['kind']=='SNAPSHOT'],controls=control)
    matrix=load(ROOT/'docs/research/003/003-04'/index['matrix'])
    references=[dict(command_id=v['command']['id'],database='native',table='work',key=v['seq']) for v in values]
    witnessed=[];missing=[]
    for row in matrix['cases']:
        try:observed=semantic_case(row['id'],values,observations)
        except (KeyError,TypeError,ValueError):observed=False
        live=row['current_run_live_proof']
        live.update(run_id=run,revision=report['revision'],evidence=[],status='LIVE-UNVERIFIED')
        if not observed:
            live['reason']='No complete native branch proof in this current-run capture. Continue supervised strategy operation.'
            missing.append(row['id']);continue
        live.update(status='LIVE-VERIFIED',reviewer='Independent retained SQLite/native/transport semantic assessor',
            semantic_assessment='Sealed capture integrity, production protocol and independent transport correlation checked. '
            'Case-specific predicates applied to the captured native rows and journal events; scope is this observed branch.',
            evidence=references,snapshot=str(snapshot),context=values[0]['command']['context'],fences=fences,
            healthy_segment_id=run,incident_ids=['00304-20261115T171217Z-unmapped-commitment'],
            registry_keys=[r['seq'] for r in registry if r.get('kind') in {'ENROLLMENT','DECISION'}])
        if row['id'] in {'minimum_initial_bid','natural_outbid_rebid'}:
            writes=[v for v in values if v['command']['operation']=='bid']
            after=max(stamp(v['response']['freshness']['network_at']) for v in writes)
            live['readback_command_ids']=[v['command']['id'] for v in values if v['command']['operation']=='watched' and
                stamp(v['response']['freshness']['network_at'])>after][-1:]
        witnessed.append(row['id'])
    receipt=dict(at=datetime.now(timezone.utc).isoformat(),run=run,snapshot=str(snapshot),
                 verified_cases=witnessed,unverified_cases=missing,structural_findings=report['findings'],
                 healthy_seconds=report['healthy_segments'][-1]['healthy_observed_seconds'],
                 source='ACTUAL_NATIVE_CAPTURE_AND_INDEPENDENT_TRANSPORT',stop_for_missing_event=False)
    return matrix,receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--write',action='store_true');args=parser.parse_args()
    out=ROOT/'docs/research/003/003-04';index=load(out/'evidence-index.json');matrix,receipt=review(index)
    if args.write:
        (out/index['matrix']).write_text(json.dumps(matrix,indent=2)+'\n',encoding='utf8')
        target=out/'production-02'/('coverage-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
        with target.open('x',encoding='utf8') as f:f.write(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
