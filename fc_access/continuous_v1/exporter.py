"""Persistent local evidence exports. No browser or EA polling and no runtime cap.

The production watchdog remains the dispatch authority. This separate operator
process captures evidence every five minutes and at a controlled stop. An export
failure requests stop rather than silently losing evidence. It never restarts or
replays work and never promotes a matrix case to verified.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import time

from .control import Control
from .evidence import capture, read_db
from fc_access.actors_v1.locking import process_lock


class Exporter:
    def __init__(self, state, transport, output, run, revision, *, clock=time.monotonic, collect=capture):
        self.state, self.transport, self.output = map(lambda p: Path(p).resolve(), (state,transport,output))
        self.run, self.revision, self.clock, self.collect = run,revision,clock,collect
        self.last_export = self.last_status = None
        self.output.mkdir(parents=True,exist_ok=False)
        self.events = (self.output/'events.jsonl').open('x',encoding='utf8')

    def close(self): self.events.close()

    def record(self,kind,**body):
        self.events.write(json.dumps(dict(kind=kind,run=self.run,at=datetime.now(timezone.utc).isoformat(),
                                         **body),sort_keys=True,allow_nan=False)+'\n')
        self.events.flush();os.fsync(self.events.fileno())

    def step(self):
        with closing(read_db(self.state/'control.sqlite3')) as db:
            view=object.__new__(Control);view.db=db;view.clock=self.clock
            status=view.status()
        if status.get('run')!=self.run:
            self.record('OWNER_CHANGED',observed_run=status.get('run'))
            return False
        now=self.clock();ended=status['status']=='STOPPED'
        snapshot=status.get('snapshot') or {}
        if self.last_status is None or now-self.last_status>=60 or ended:
            self.record('STATUS',status=status['status'],source=status['manifest']['source'],
                        healthy_observed_seconds=status['healthy_observed_seconds'],
                        commands=snapshot.get('commands_observed'),native_requests=snapshot.get('native_requests_observed'),
                        capacity=snapshot.get('capacity'),credits=snapshot.get('credits'),
                        intents=snapshot.get('intents'),actors=snapshot.get('actors'),
                        incident=status.get('incident'),stop=status.get('stop'),
                        live_coverage='LIVE-UNVERIFIED_UNTIL_INDEPENDENT_CASE_REVIEW')
            self.last_status=now
        if snapshot and (self.last_export is None or now-self.last_export>=300 or ended):
            target=self.output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4))
            result=self.collect(self.state,self.transport,target,revision=self.revision)
            self.record('CAPTURED',source=status['manifest']['source'],path=result['path'],revision=self.revision)
            self.last_export=now
        return not ended

    def fail(self,error):
        incident='export-'+secrets.token_hex(16)
        try:self.record('EXPORT_FAILURE',incident_id=incident,exception_type=type(error).__name__)
        finally:
            control=Control(self.state/'control.sqlite3')
            try:
                latest=control.latest(None,'RUN_OPEN')
                if latest and latest['run']==self.run and not control.latest(self.run,'RUN_STOPPED'):
                    control.append(self.run,'INCIDENT',incident_id=incident,reason='EVIDENCE_EXPORT_FAILED',
                                   exception_type=type(error).__name__)
                    control.stop(self.run,'EVIDENCE_EXPORT_FAILED')
            finally:control.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('state','transport','output','run','revision'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    exporter=Exporter(args.state,args.transport,args.output,args.run,args.revision)
    try:
        with process_lock(exporter.state/('exporter-'+args.run+'.lock')):
            while exporter.step():time.sleep(1)
        return 0
    except Exception as error:
        exporter.fail(error)
        return 1
    finally:exporter.close()


if __name__=='__main__':raise SystemExit(main())
