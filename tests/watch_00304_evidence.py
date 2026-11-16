"""Persistent local-only coverage review; missing natural events never stop actors.

Consumes only new exporter captures. No browser access, EA calls, controller
restart, synthetic live observation, coverage target or four-hour shutdown.
"""
from contextlib import closing
from datetime import datetime,timezone
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from check_00304_live import OUT,load,lines,assess_task
from review_00304_cases import review
from fc_access.actors_v1.locking import process_lock
from fc_access.continuous_v1.evidence import read_db


class ReviewWatch:
    def __init__(self,index,output,run,*,reviewer=review,assessor=assess_task):
        self.index,self.output=Path(index),Path(output)
        self.run,self.reviewer,self.assessor=run,reviewer,assessor
        self.output.mkdir(parents=True,exist_ok=False)
        self.last=None
        self.log=(self.output/'events.jsonl').open('x',encoding='utf8')

    def record(self,kind,**body):
        self.log.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,run=self.run,**body))+'\n')
        self.log.flush();os.fsync(self.log.fileno())

    def close(self):self.log.close()

    def step(self):
        index=load(self.index)
        if index['run']!=self.run:
            self.record('OWNER_CHANGED',observed_run=index['run']);return False
        exports=[r for r in lines(ROOT/index['export_events']) if r['kind']=='CAPTURED' and r['run']==self.run]
        if not exports:return True
        selected=exports[-1]['path']
        if selected==self.last:return True
        matrix,receipt=self.reviewer(index)
        matrix_path=self.index.parent/index['matrix']
        # The operational matrix is mutable; immutable numbered receipts retain each assessment.
        temporary=matrix_path.with_name(matrix_path.name+'.review.tmp')
        temporary.write_text(json.dumps(matrix,indent=2)+'\n',encoding='utf8');os.replace(temporary,matrix_path)
        acceptance=self.assessor(index,self.index.parent)
        number=len(list(self.output.glob('review-*.json')))+1
        path=self.output/f'review-{number:06d}.json'
        with path.open('x',encoding='utf8') as stream:
            stream.write(json.dumps(dict(coverage=receipt,acceptance=acceptance),indent=2)+'\n')
        self.record('REVIEWED',snapshot=selected,receipt=str(path),status=acceptance['status'],
                    verified_cases=receipt['verified_cases'],unverified_cases=receipt['unverified_cases'],
                    stop_for_missing_event=False,threshold_shutdown=False)
        self.last=selected
        # Termination follows a real sealed runtime stop, never coverage or elapsed hours.
        with closing(read_db(Path(selected)/'control.sqlite3')) as db:
            stopped=db.execute("SELECT 1 FROM records WHERE run=? AND kind='RUN_STOPPED'",(self.run,)).fetchone()
        return not stopped


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,default=OUT/'evidence-index.json')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--run',required=True)
    args=parser.parse_args()
    watch=ReviewWatch(args.index,args.output,args.run)
    try:
        with process_lock(args.output/'review.lock'):
            while True:
                try:
                    if not watch.step():return 0
                except Exception as error:
                    # The real watchdog still supervises actors. Failed audit attempts are
                    # visible and retried locally; no acceptance or healthy time is invented.
                    watch.record('REVIEW_FAILED',error_type=type(error).__name__)
                time.sleep(15)
    finally:watch.close()


if __name__=='__main__':raise SystemExit(main())
