"""Finite synthetic shared-connection stress. No network or production database."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import faulthandler
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run(mode,seconds):
    if not 0<seconds<=60:raise ValueError('finite_seconds_required')
    faulthandler.enable(all_threads=True)
    with tempfile.TemporaryDirectory() as path:
        store=None
        if mode=='controller':
            from fc_access.controller_v1.store import ControllerStore
            store=ControllerStore(Path(path)/'synthetic.sqlite');db=store.db
        else:db=sqlite3.connect(':memory:',check_same_thread=False,cached_statements=0 if mode=='uncached' else 128)
        values={i:bytes([i+1])*262144 for i in range(8)}
        db.execute('CREATE TABLE synthetic_values(id INTEGER PRIMARY KEY,value BLOB NOT NULL)')
        db.executemany('INSERT INTO synthetic_values VALUES(?,?)',values.items());db.commit()
        barrier=threading.Barrier(12);deadline=time.monotonic()+seconds;stop=threading.Event()
        def query(worker):
            count=0;barrier.wait()
            try:
                while time.monotonic()<deadline and not stop.is_set():
                    key=(worker+count)%len(values)
                    row=db.execute('SELECT id,value FROM synthetic_values WHERE id=?',(key,)).fetchone()
                    if row!=(key,values[key]):raise AssertionError('synthetic_read_mismatch')
                    count+=1
                return count
            except BaseException:stop.set();raise
        try:
            with ThreadPoolExecutor(max_workers=12) as pool:counts=list(pool.map(query,range(12)))
            if min(counts)<1:raise AssertionError('all_readers_must_run')
            print(json.dumps(dict(status='SYNTHETIC_STRESS_PASS',mode=mode,readers=len(counts),reads=sum(counts),seconds=seconds,
                python=sys.version.split()[0],sqlite=sqlite3.sqlite_version,threadsafety=sqlite3.threadsafety)),flush=True)
        finally:
            if store:store.close()
            else:db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=('shared','uncached','controller'),required=True);p.add_argument('--seconds',type=float,default=15)
    a=p.parse_args();run(a.mode,a.seconds)
