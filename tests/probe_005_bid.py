"""Explicit one-initial-bid diagnostic, using real production admission and journal.

Never invoked by discovery. A consumed directory cannot be reopened. Trading
strategy is unchanged; only this experiment's number of initial attempts is one.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.controller_v1.__main__ import guard_paths
from fc_access.controller_v1.adapter import ControllerAdapter
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.executor import ControllerExecutor,SerializedExecutor
from fc_access.controller_v1.semantic import SemanticHealth,native_summary
from fc_access.controller_v1.server import Server
from fc_access.production_v1.price_cache import QuoteCache


class ProbeController(Controller):
    def _bid(self,*args,**kwargs):
        # Limiting this explicit experiment grants no authority that the normal
        # controller/store/adapter would reject. Later candidates are unsent.
        if getattr(self,'probe_attempted',False):return None
        self.probe_attempted=True
        return super()._bid(*args,**kwargs)


class Bounded:
    def __init__(self,edge,record,semantic,*,clock=time.monotonic):
        self.edge,self.record,self.semantic,self.clock=edge,record,semantic,clock
        self.deadline=clock()+900;self.commands=self.reserved_ea=self.mutations=0

    def attach(self,*args):return self.edge.attach(*args)

    def execute(self,c):
        op=c['operation'];cost=0 if op=='price_helpers' else 2 if op=='search' else 1
        if op not in {'balance','watched','status_batch','search','caps','price_helpers','transfer_list','unassigned','bid'}:
            raise ValueError('probe_operation_denied')
        if self.clock()>self.deadline or self.commands>=1024 or self.reserved_ea+cost>96 or op=='bid' and self.mutations>=1 or self.semantic.check():
            raise ValueError('probe_exhausted_or_semantic_fault')
        self.commands+=1;self.reserved_ea+=cost
        if op=='bid':self.mutations+=1
        self.record('RESERVED_BEFORE_DELIVERY',command=c,reserved_ea=cost,ordinal=self.commands)
        try:
            v=self.edge.execute(c);self.record('NATIVE_RESULT',command=c,response=v);return v
        except Exception as error:
            self.record('DELIVERY_UNCERTAIN',command_id=c['id'],exception_type=type(error).__name__);raise


def run(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    def record(kind,**fields):
        with (output/'checkpoint.jsonl').open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**fields))+'\n')
            stream.flush();os.fsync(stream.fileno())
    base=ROOT/'private-captures/controller-v1';scope=json.loads((base/'public-context.json').read_text())
    record('PREPARED',question='Does a current-document controller bid still return461/403 or401; what does independent account evidence show?',
           max_initial_mutations=1,max_other_mutations=0,max_reserved_ea=96,max_commands=1024,deadline_seconds=900,context=scope)
    result=dict(status='NOT_VERIFIED',account_mutations=0)
    with ExitStack() as stack:
        for path in guard_paths(ROOT,scope,base/'controller.sqlite',8784):stack.enter_context(process_lock(path))
        server=Server(base/'controller.sqlite',8784,write_authority=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        cache=None;controller=None;bounded=None
        try:
            previous=server.store.db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
            epoch=json.loads(previous[0])['fences']['epoch']+1 if previous else 1
            semantic=SemanticHealth()
            bounded=Bounded(ControllerExecutor(8784,attach_timeout=60),record,semantic)
            executor=SerializedExecutor(bounded)
            def native(c,v):
                with server.store.lock:
                    count=server.store.db.execute('SELECT coalesce(sum(json_array_length(body)),0) FROM c4_diagnostics WHERE command_id=?',(c['id'],)).fetchone()[0]
                message=dict(kind='native_result',**native_summary(c,v),diagnostic_records=count)
                semantic.observe(message);record('SEMANTIC_RESULT',message=message)
            executor.result=native
            server.store.semantic_report=lambda **fields:semantic.observe(dict(kind='batch_result',**fields))
            print('ONE_BID_PROBE_SERVICE_READY',flush=True)
            adapter=ControllerAdapter(executor,context=scope,owner=secrets.token_hex(16),epoch=epoch)
            record('ATTACHED',context=scope,fences=adapter.fences)
            cache=QuoteCache(base/'quotes.sqlite')
            controller=ProbeController(server.store,adapter,cache);server.controller=controller
            controller.resume();controller._acquire()
            state=controller.journal.state();batch=state['batch_id']
            attempts=[dict(command_id=cid,state=state,result=json.loads(value) if value else None)
                      for cid,state,value in server.store.db.execute('SELECT id,state,result FROM c4_attempts WHERE batch_id=?',(batch,))]
            members=[m for m in controller.journal.members() if m['batch_id']==batch]
            record('POLICY_RESULT',batch_id=batch,attempts=attempts,members=members)
            # Independent actual account read, even after an uncertain bid. This
            # is a new read intent; no mutation is retried or inferred to fail.
            if not semantic.check():
                watched=adapter.read(secrets.token_hex(16),'watched')
                record('INDEPENDENT_ACCOUNT_READBACK',response=watched)
            result.update(status='CONFIRMED_PARTICIPATION' if members else 'NO_CONFIRMED_PARTICIPATION',
                          batch_id=batch,attempts=attempts,confirmed_members=len(members),semantic=semantic.snapshot())
        except Exception as error:
            result['exception_type']=type(error).__name__
        finally:
            if controller:controller.stop()
            server.shutdown();thread.join(5)
            result['pending']=server.store.db.execute("SELECT count(*) FROM c4_commands WHERE state IN ('WAITING','CLAIMED')").fetchone()[0]
            if cache:cache.close()
            server.server_close()
            if bounded:result.update(account_mutations=bounded.mutations,reserved_ea=bounded.reserved_ea,commands=bounded.commands)
            result['service_stopped']=not thread.is_alive()
            record('CLOSED',result=result)
            (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result),flush=True)
    return 0 if result['status']=='CONFIRMED_PARTICIPATION' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    raise SystemExit(run(parser.parse_args().output))
