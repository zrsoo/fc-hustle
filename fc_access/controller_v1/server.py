"""Explicit controller service; read-only unless trusted construction enables admission."""
import argparse
from copy import deepcopy
import sqlite3
import threading
import time
from http.server import ThreadingHTTPServer
from fc_access.production_v1.server import Handler as LegacyHandler, EXTENSION_ID
from fc_access.production_v1.contracts import fields, context, integer, token
from .store import ControllerStore


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, database, port=8784, *, write_authority=False, wait_seconds=22, poll_seconds=18):
        if not 0<wait_seconds<=25 or not 0<=poll_seconds<=20:raise ValueError('invalid_delivery_timeout')
        self.store = ControllerStore(database,write_authority=write_authority)
        self.condition = threading.Condition()
        self.extension_origin = 'chrome-extension://'+EXTENSION_ID
        self.owner = None
        self.attached_at = 0
        self.polling = False
        self.controller = None
        self.wait_seconds,self.poll_seconds = wait_seconds,poll_seconds
        super().__init__(('127.0.0.1',port),Handler)

    def handle_error(self,*args): pass

    def server_close(self):
        super().server_close(); self.store.close()


class Handler(LegacyHandler):
    def do_GET(self):
        if not self.origin(): return self.send(403,{'error':'origin_denied'})
        if self.path=='/status':
            return self.send(200,self.server.controller.status() if self.server.controller else {'lifecycle':'STOPPED','controller_attached':False})
        if self.path!='/health': return self.send(404,{'error':'not_found'})
        s=self.server
        with s.condition:
            self.send(200,dict(service='fc-controller-v1',schema=4,host_epoch=s.store.host_epoch,owner=s.owner,
                attached=s.store.peer is not None and time.monotonic()-s.attached_at<45,peer=s.store.peer,
                mutations_enabled=s.store.write_authority))

    def peer(self,p):
        s=self.server;s.store.check_peer(p)
        if time.monotonic()-s.attached_at>=45: raise ValueError('reattach_required')

    def do_POST(self):
        s=self.server
        try:
            if self.path not in {'/activate','/hello','/next','/run','/result','/diagnostic','/control'}: return self.send(404,{'error':'not_found'})
            if not self.origin(self.path in {'/hello','/next','/result','/diagnostic'}): return self.send(403,{'error':'origin_denied'})
            v=self.payload()
            if self.path=='/control':
                fields(v,{'action'})
                if v['action'] not in {'pause','stop'} or s.controller is None:raise ValueError('invalid_control')
                return self.send(200,getattr(s.controller,v['action'])())
            with s.condition:
                if self.path=='/activate':
                    fields(v,{'context','owner','epoch'});context(v['context']);token(v['owner']);integer(v['epoch'],1)
                    recorded=s.store.db.execute("SELECT value FROM c4_meta WHERE key='scope'").fetchone()
                    if recorded:
                        import json
                        if json.loads(recorded[0])!=v['context']:raise ValueError('account_mismatch')
                    old=s.owner
                    if old and v!=old and (v['context']!=old['context'] or v['epoch']<=old['epoch']): raise ValueError('owner_epoch_required')
                    if v!=old:
                        if s.store.peer:
                            with s.store.db:
                                s.store.db.execute("UPDATE c4_commands SET state='UNKNOWN' WHERE state IN ('WAITING','CLAIMED')")
                        s.store.peer=None
                    s.owner=deepcopy(v);return self.send(200,{'accepted':True})
                if self.path=='/hello':
                    # Shared reviewed worker bootstrap uses schema 2; commands are
                    # dialect 4 plus explicitly allowlisted legacy reads on this
                    # service. The marker selects read failure cleanup, never writes.
                    if v!={'schema':2}:
                        fields(v,{'schema','peer'})
                        if v['schema']!=2 or not s.owner or v['peer']['context']!=s.owner['context'] or any(v['peer']['fences'][k]!=s.owner[k] for k in ('owner','epoch')): raise ValueError('owner_mismatch')
                        s.store.attach(v['peer']);s.attached_at=time.monotonic()
                    return self.send(200,dict(schema=2,service='fc-controller-v1',host_epoch=s.store.host_epoch,owner=s.owner))
                if self.path=='/next':
                    self.peer(v)
                    if s.polling: raise ValueError('single_poll_owner')
                    s.polling=True;s.attached_at=time.monotonic()
                    try:
                        end=time.monotonic()+s.poll_seconds
                        while True:
                            self.peer(v);c=s.store.claim(v)
                            if c or time.monotonic()>=end:return self.send(200,c)
                            s.condition.wait(min(.25,end-time.monotonic()))
                    finally:s.polling=False
                if self.path=='/result':
                    fields(v,{'peer','id','result'});self.peer(v['peer']);s.store.finish(v['peer'],v['id'],v['result']);s.condition.notify_all()
                    return self.send(200,{'accepted':True})
                if self.path=='/diagnostic':
                    fields(v,{'peer','id','records'});self.peer(v['peer'])
                    s.store.diagnostic(v['peer'],v['id'],v['records'])
                    return self.send(200,{'accepted':True})
                self.peer(s.store.peer);s.store.enqueue(v,s.store.peer);s.condition.notify_all()
                end=time.monotonic()+s.wait_seconds
                while True:
                    r=s.store.result(v['id'])
                    if r is not None:return self.send(200,r)
                    if time.monotonic()>=end:
                        s.store.uncertain(v['id']);return self.send(504,{'error':'timeout_no_retry'})
                    s.condition.wait(min(.25,end-time.monotonic()))
        except (ValueError,TypeError,KeyError,OverflowError,OSError,sqlite3.IntegrityError):
            return self.send(409,{'error':'rejected'})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',required=True);p.add_argument('--port',type=int,default=8784)
    args=p.parse_args();server=Server(args.database,args.port)
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
