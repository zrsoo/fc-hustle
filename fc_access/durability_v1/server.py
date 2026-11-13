"""Pinned Edge transport. Only explicit finite commands invoke native services.

Long polling is local delivery, not an Acquirer or Bidder service loop.
The default live window permits zero mutations. Restart never resets a window.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from http.server import ThreadingHTTPServer

from experiments.market_discovery.bridge_server import Handler as BaseHandler
from experiments.market_discovery_followup_v1.server import persona_projection
from .store import Store

ROOT=Path(__file__).resolve().parents[2]
EXTENSION_PATH=str((ROOT/'browser/durability-v1').resolve())
EXTENSION_PATH=EXTENSION_PATH[0].upper()+EXTENSION_PATH[1:]
EXTENSION_ID=''.join(chr(97+int(n,16)) for n in hashlib.sha256(EXTENSION_PATH.encode('utf-16-le')).hexdigest()[:32])


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,path,port=8779,*,wait_seconds=22,poll_seconds=18,**limits):
        self.store=Store(path,**limits)
        self.condition=threading.Condition()
        self.boot=secrets.token_hex(16)  # Public process-generation fence, not authentication.
        self.peer=None; self.attached_at=0; self.polling=False
        self.wait_seconds=wait_seconds; self.poll_seconds=poll_seconds
        self.extension_origin='chrome-extension://'+EXTENSION_ID
        super().__init__(('127.0.0.1',port),Handler)
    def handle_error(self,*args): pass
    def server_close(self):
        super().server_close()
        # Handler threads are daemonized; callers shut down outstanding polls first.


class Handler(BaseHandler):
    def send(self,code,v):
        try: return super().send(code,v)
        except (BrokenPipeError,ConnectionResetError,OSError): return None

    def do_GET(self):
        if not self.origin(): return self.send(403,{'error':'origin_denied'})
        if self.path!='/health': return self.send(404,{'error':'not_found'})
        s=self.server
        with s.condition:
            return self.send(200,{'service':'fc-durability-v1','boot':s.boot,'extension_id':EXTENSION_ID,
                'owner':s.store.owner(),'attached':time.monotonic()-s.attached_at<45,
                'polling':bool(s.polling),'persona':s.peer['persona'] if s.peer else None,
                'document':s.peer['document'] if s.peer else None,
                'worker':s.peer['worker'] if s.peer else None,
                'page_checks':s.peer['fences'] if s.peer else None,'window':s.store.health()})

    def peer(self,v):
        s=self.server
        if not isinstance(v,dict) or set(v)!={'boot','scope','owner','epoch','document','worker','persona','fences'}:
            raise ValueError('invalid_peer')
        from fc_access.bidding_v1.contracts import token
        token(v['document']); token(v['worker']); persona_projection(v['persona']); self.fences(v['fences'])
        if v['boot']!=s.boot: raise ValueError('stale_process')
        s.store.check_owner(v)
        if v!=s.peer: raise ValueError('reattach_required')
        return v

    def fences(self,v):
        if not isinstance(v,dict) or set(v)!={'wrong_scope','wrong_owner','stale_epoch','bid_disabled'} or any(x is not True for x in v.values()):
            raise ValueError('page_fences_failed')

    def do_POST(self):
        s=self.server
        try:
            # Consume a bounded body before an early rejection. Otherwise a
            # split header/body client can receive a Windows reset instead of
            # the actual 403 response. Never log or retain rejected payloads.
            v=self.payload()
        except (ValueError,TypeError,KeyError,OverflowError,OSError):
            return self.send(400,{'error':'invalid_payload'})
        if self.path not in ('/activate','/run','/hello','/next','/result','/close'):
            return self.send(404,{'error':'not_found'})
        if not self.origin(self.path in ('/hello','/next','/result')):
            return self.send(403,{'error':'origin_denied'})
        try:
            with s.condition:
                if self.path=='/close':
                    if v!={}: raise ValueError('invalid_close')
                    with s.store.tx():
                        s.store.db.execute('UPDATE window SET stopped=1')
                        s.store.event('WINDOW_CLOSED')
                    s.condition.notify_all()
                    return self.send(200,{'closed':True})
                if self.path=='/activate':
                    s.store.activate(v); s.peer=None; s.attached_at=0
                    s.condition.notify_all()
                    return self.send(200,{'accepted':True})
                if self.path=='/hello':
                    if v!={'protocol':1} and (not isinstance(v,dict) or set(v)!={'protocol','peer'} or v['protocol']!=1):
                        raise ValueError('invalid_hello')
                    # First response tells Edge the current process and owner. Second
                    # confirms the installed page fence and public persona projection.
                    if 'peer' in v:
                        p=v['peer']
                        if not isinstance(p,dict) or set(p)!={'boot','scope','owner','epoch','document','worker','persona','fences'}:
                            raise ValueError('invalid_peer')
                        from fc_access.bidding_v1.contracts import token
                        token(p['document']); token(p['worker']); persona_projection(p['persona']); self.fences(p['fences'])
                        if p['boot']!=s.boot: raise ValueError('stale_process')
                        s.store.check_owner(p)
                        if p!=s.peer: s.store.event('DOCUMENT_ATTACHED')
                        s.peer=p; s.attached_at=time.monotonic();s.condition.notify_all()
                    return self.send(200,{'boot':s.boot,'owner':s.store.owner(),'window':s.store.health()})
                if self.path=='/next':
                    p=self.peer(v)
                    s.attached_at=time.monotonic()
                    if s.polling==p: raise ValueError('duplicate_poll')
                    # A reloaded worker supersedes its orphan long poll even if
                    # the page document and host epoch did not change.
                    s.polling=p
                    try:
                        end=time.monotonic()+s.poll_seconds
                        while True:
                            self.peer(p)
                            c=s.store.claim(p)
                            if c or time.monotonic()>=end: return self.send(200,c)
                            s.condition.wait(min(.5,end-time.monotonic()))
                    finally:
                        if s.polling==p:s.polling=False
                if self.path=='/result':
                    if not isinstance(v,dict) or set(v)!={'peer','id','result'}: raise ValueError('invalid_result')
                    p=self.peer(v['peer']); s.store.finish(p,v['id'],v['result'])
                    s.condition.notify_all(); return self.send(200,{'accepted':True})
                # A wrong persona can be attached but never authorize native work.
                if not s.peer or time.monotonic()-s.attached_at>=45: raise ValueError('bridge_not_attached')
                if not s.peer['persona']['accepted']: raise ValueError('persona_unverified')
                s.store.enqueue(v); s.condition.notify_all()
                cid=v['id']
                end=time.monotonic()+s.wait_seconds
                while True:
                    result=s.store.result(cid)
                    if result is not None: return self.send(200,result)
                    if time.monotonic()>=end:
                        s.store.uncertain(cid); return self.send(504,{'error':'timeout_no_retry'})
                    s.condition.wait(min(.5,end-time.monotonic()))
        except (ValueError,TypeError,KeyError,OverflowError):
            return self.send(409,{'error':'rejected'})


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--database',required=True)
    p.add_argument('--port',type=int,default=8779)
    p.add_argument('--seconds',type=int,default=900)
    p.add_argument('--reads',type=int,default=12)
    # Intentionally no HTTP write-enabling switch. Bid tests use the bounded
    # Python harness; this lifecycle campaign's live budget is immutable zero.
    a=p.parse_args()
    Server(a.database,a.port,seconds=a.seconds,reads=a.reads).serve_forever()


if __name__=='__main__': main()
