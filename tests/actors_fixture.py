"""Synthetic native page for actor tests and a finite subprocess broker fixture."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from foundation_fixture import Page,Clock,CONTEXT
from native_price_fixture import auction
from fc_access.production_v1.foundation import Foundation


class ActorPage(Page):
    def __init__(self,directory,clock):
        super().__init__(directory,clock)
        self.candidate['starting_bid']=800
        self.candidate['buy_now_price']=15000
        self.watched=[]
        self.pages=None
        self.owned=[]
        self.transfer_items=[]
        self.transfer_coverage=None
        self.on_bid=self.apply_bid

    def apply_bid(self,c):
        self.candidate.update(current_bid=c['params']['amount'],bid_state='highest')
        self.watched=[deepcopy(self.candidate)]
        self.credits-=c['params']['amount']

    def project_response(self,c,v):
        if c['operation']=='search':
            p = c['params']
            v['result']['network'][0]['query']['start']=(p['page']-1)*21
            if p['purpose']=='discovery' and self.pages is not None:
                v['result']['auctions']=deepcopy(self.pages.get(p['page'],[]))
                v['coverage']['has_more']=p['page']<max(self.pages)
        if c['operation']=='unassigned': v['result']['items']=deepcopy(self.owned)
        if c['operation']=='transfer_list':
            v['result']['auctions']=deepcopy(self.transfer_items)
            n=len(self.transfer_items)
            v['coverage']=deepcopy(self.transfer_coverage) if self.transfer_coverage is not None else dict(
                complete=True,has_more=False,transfer_list=dict(reason='TRANSFER_LIST_COMPLETE',
                    wire_count=n,callback_count=n,repository_count=n,repository_end_of_list=True))
        return v


def create(directory,**kwargs):
    clock=Clock()
    page=ActorPage(directory,clock)
    f=Foundation(page,context=CONTEXT,journal_path=Path(directory)/'journal.sqlite3',
        fixture=True,now=clock.now,clock=clock.monotonic,sleep=clock.sleep,**kwargs)
    return f,page,clock


class RealClock:
    def now(self):return datetime.now(timezone.utc)
    def sleep(self,s):time.sleep(s)


if __name__=='__main__':
    from fc_access.actors_v1.native import Mailbox,Broker
    from fc_access.actors_v1.config import Config
    from fc_access.actors_v1.locking import process_lock
    directory=Path(sys.argv[1])
    mode=sys.argv[2]
    if mode=='enqueue':
        from fc_access.production_v1.contracts import stamp
        box=Mailbox(directory/'native.sqlite3')
        try:
            jobs=json.loads(Path(sys.argv[3]).read_text())
            for job in jobs:box.enqueue(job['command'],job['role'],now=stamp(job['at']))
        finally:box.close()
    if mode=='broker':
        clock=RealClock()
        p=ActorPage(directory,clock)
        f=Foundation(p,context=CONTEXT,journal_path=directory/'journal.sqlite3',fixture=True)
        box=Mailbox(directory/'native.sqlite3')
        b=Broker(box,f,Config(native_interval_seconds=0))
        try:
            with process_lock(box.path.with_suffix('.executor.lock')):
                b.initialize()
                (directory/'ready').write_text('ready')
                end=time.monotonic()+45
                while not (directory/'stop').exists() and time.monotonic()<end:
                    b.run_one();time.sleep(.001)
            (directory/'calls.json').write_text(json.dumps(p.calls))
        finally:box.close();f.close();p.close()
