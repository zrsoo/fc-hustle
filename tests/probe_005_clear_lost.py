"""Explicit finite cleanup experiment: one journaled DELETE, up to three fresh reads."""
from contextlib import ExitStack
from datetime import datetime,timezone
import argparse,json,os,secrets,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.controller_v1.__main__ import guard_paths
from fc_access.controller_v1.adapter import ControllerAdapter
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.executor import ControllerExecutor,SerializedExecutor
from fc_access.controller_v1.server import Server
from fc_access.controller_v1.semantic import SemanticHealth,native_summary
from fc_access.controller_v1.lost_targets import parameters,effect
from fc_access.production_v1.price_cache import QuoteCache

class Bounded:
    def __init__(self,edge,record,semantic,clock=time.monotonic):
        self.edge,self.record,self.semantic,self.clock=edge,record,semantic,clock
        self.deadline=clock()+180;self.commands=self.mutations=0
    def attach(self,*args):return self.edge.attach(*args)
    def execute(self,c):
        if c['operation'] not in {'watched','clear_lost'} or self.commands>=4 or self.clock()>=self.deadline or self.semantic.check() or c['operation']=='clear_lost' and self.mutations>=1:
            raise ValueError('finite_cleanup_scope_exhausted')
        self.commands+=1
        if c['operation']=='clear_lost':self.mutations+=1
        self.record('RESERVED_BEFORE_DELIVERY',command=c,ordinal=self.commands)
        v=self.edge.execute(c);self.record('NATIVE_RESULT',command=c,response=v);return v

def run(output,epoch_floor):
    if type(epoch_floor) is not int or epoch_floor<1:raise ValueError('invalid_epoch_floor')
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    def record(kind,**fields):
        with (out/'checkpoint.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**fields))+'\n');f.flush();os.fsync(f.fileno())
    record('PREPARED',question='Does exact native lost-target cleanup free observed INBOX slots while preserving non-target identities?',max_owned_ea_commands=4,max_clear_lost_commands=1,max_other_mutations=0,deadline_seconds=180,epoch_floor=epoch_floor)
    base=ROOT/'private-captures/controller-v1';scope=json.loads((base/'public-context.json').read_text());result=dict(status='UNCONFIRMED',account_mutations=0)
    with ExitStack() as stack:
        for lock in guard_paths(ROOT,scope,base/'controller.sqlite',8784):stack.enter_context(process_lock(lock))
        server=Server(base/'controller.sqlite',8784,write_authority=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();cache=None;controller=None;bounded=None
        try:
            old=server.store.db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone();epoch=max(epoch_floor,json.loads(old[0])['fences']['epoch']+1 if old else 1)
            semantic=SemanticHealth();bounded=Bounded(ControllerExecutor(8784,attach_timeout=60),record,semantic);executor=SerializedExecutor(bounded)
            def native(c,v):
                with server.store.lock:count=server.store.db.execute('SELECT coalesce(sum(json_array_length(body)),0) FROM c4_diagnostics WHERE command_id=?',(c['id'],)).fetchone()[0]
                m=dict(kind='native_result',**native_summary(c,v),diagnostic_records=count);semantic.observe(m);record('SEMANTIC_RESULT',message=m)
            executor.result=native
            print('FINITE_CLEANUP_SERVICE_READY',flush=True)
            adapter=ControllerAdapter(executor,context=scope,owner=secrets.token_hex(16),epoch=epoch);cache=QuoteCache(base/'quotes.sqlite');controller=Controller(server.store,adapter,cache);server.controller=controller;controller.resume()
            before=controller._read('watched');planned=parameters(before);record('OBSERVED_ELIGIBLE_SET',before=before,params=planned)
            if not planned['targets']:result['status']='NO_ELIGIBLE_TARGETS'
            else:
                after=controller.work.clear_lost(before)
                row=server.store.db.execute("SELECT id,body,state,proof FROM c4_work WHERE json_extract(body,'$.operation')='clear_lost' AND json_extract(body,'$.fences.owner')=? ORDER BY rowid DESC LIMIT 1",(adapter.fences['owner'],)).fetchone()
                if row:
                    c=json.loads(row[1]);proof=json.loads(row[3]) if row[3] else None
                    result.update(command_id=row[0],work_state=row[2],mode=proof.get('mode') if proof else None,targets=planned['targets'])
                    if after is not None and not semantic.check():
                        final=controller._read('watched');record('INDEPENDENT_FINAL_READBACK',response=final)
                        if row[2]=='CONFIRMED' and effect(c,before,final):result['status']='NATIVE_CLEANUP_CONFIRMED' if proof.get('mode')=='NATIVE_ACK_AND_READBACK' else 'CURRENT_ABSENCE_AFTER_UNKNOWN'
            result['semantic']=semantic.snapshot()
        except Exception as error:result['exception_type']=type(error).__name__
        finally:
            if controller:controller.stop()
            server.shutdown();thread.join(5)
            result.update(pending=server.store.db.execute("SELECT count(*) FROM c4_commands WHERE state IN ('WAITING','CLAIMED')").fetchone()[0],service_stopped=not thread.is_alive())
            if bounded:result.update(account_mutations=bounded.mutations,reserved_commands=bounded.commands)
            with server.store.lock:diagnostics=[dict(command_id=cid,records=json.loads(b)) for cid,b in server.store.db.execute("SELECT command_id,body FROM c4_diagnostics WHERE command_id IN (SELECT id FROM c4_commands WHERE json_extract(body,'$.fences.epoch')=?) ORDER BY seq",(epoch if 'epoch' in locals() else -1,))]
            (out/'diagnostics.json').write_text(json.dumps(diagnostics,indent=2)+'\n',encoding='utf-8')
            if cache:cache.close()
            server.server_close();record('CLOSED',result=result);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result),flush=True)
    return 0 if result['status'] in {'NATIVE_CLEANUP_CONFIRMED','NO_ELIGIBLE_TARGETS'} else 1
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--epoch-floor',type=int,required=True);a=p.parse_args();raise SystemExit(run(a.output,a.epoch_floor))
