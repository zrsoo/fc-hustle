"""Pinned loopback search-only delivery, durable finite budget, no retries."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time

from fc_access.bidding_v1.contracts import Search
from .validation import validate,search_params

ROOT=Path(__file__).resolve().parents[2]
DIRECTORY=ROOT/'docs/research/001c/001c-04'
p=str((ROOT/'experiments/search_validation_v1/browser').resolve())
p=p[0].upper()+p[1:]
EXTENSION_ID=''.join(chr(ord('a')+int(n,16)) for n in hashlib.sha256(p.encode('utf-16-le')).hexdigest()[:32])


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,port=8778,budget_path=None):
        self.condition=threading.Condition();self.pending=None;self.attached_at=0
        self.budget_path=Path(budget_path or DIRECTORY/'budget.json')
        self.budget=json.loads(self.budget_path.read_text())
        super().__init__(('127.0.0.1',port),Handler)
    def handle_error(self,*args):pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,code,v):
        b=json.dumps(v,allow_nan=False).encode();self.send_response(code)
        self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def allowed(self,extension=False):
        return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and (self.headers.get('Origin')=='chrome-extension://'+EXTENSION_ID if extension else self.headers.get('Origin') is None and self.headers.get('Sec-Fetch-Site') is None)
    def do_GET(self):
        if not self.allowed():return self.reply(403,{'error':'origin_denied'})
        if self.path!='/health':return self.reply(404,{'error':'not_found'})
        return self.reply(200,{'service':'fc-search-validation-v1','extension_id':EXTENSION_ID,'attached':time.monotonic()-self.server.attached_at<65,'pending':self.server.pending is not None,'consumed':self.server.budget['consumed'],'maximum':self.server.budget['maximum']})
    def do_POST(self):
        if self.path not in ('/next','/result','/run'):return self.reply(404,{'error':'not_found'})
        if not self.allowed(self.path!='/run'):return self.reply(403,{'error':'origin_denied'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=262144 or self.headers.get('Content-Type')!='application/json' or self.headers.get('Transfer-Encoding'):raise ValueError()
            v=json.loads(self.rfile.read(size))
            with self.server.condition:
                s=self.server
                if self.path=='/next':
                    if v!={}:raise ValueError()
                    s.attached_at=time.monotonic();p=s.pending
                    if p and not p['delivered']:
                        b=s.budget;b['consumed']+=1;b['commands'].append({'command_id':p['command']['id'],'params':p['command']['params'],'delivered_at':time.time()})
                        # Commit consumption before returning a command to Edge.
                        temp=s.budget_path.with_suffix('.tmp');temp.write_text(json.dumps(b,indent=2));temp.replace(s.budget_path)
                        p['delivered']=True;return self.reply(200,p['command'])
                    return self.reply(200,None)
                if self.path=='/result':
                    if not isinstance(v,dict) or set(v)!={'id','result'}:raise ValueError()
                    validate(v['result']);p=s.pending
                    if not p or not p['delivered'] or p['result'] is not None or v['id']!=p['command']['id'] or v['result']['command_id']!=v['id'] or v['result']['params']!=p['command']['params']:return self.reply(409,{'error':'expired'})
                    p['result']=v['result'];s.condition.notify_all();return self.reply(200,{'accepted':True})
                if not isinstance(v,dict) or set(v)!={'params'}:raise ValueError()
                search_params(v['params'])
                if not set(v['params'])<={'page','count','max_bid','min_buy','max_buy','definition_id','with_caps'}:raise ValueError()
                if s.pending:return self.reply(409,{'error':'busy'})
                if s.budget['consumed']>=s.budget['maximum']:return self.reply(409,{'error':'budget_exhausted'})
                if s.budget['commands'] and time.time()-s.budget['commands'][-1]['delivered_at']<31:return self.reply(409,{'error':'experiment_pacing'})
                if time.monotonic()-s.attached_at>=65:return self.reply(409,{'error':'not_attached'})
                p={'command':{'id':secrets.token_hex(16),'evidence_key':'001c0400000000000000000000000001','params':v['params']},'delivered':False,'result':None};s.pending=p
                try:
                    s.condition.wait_for(lambda:p['result'] is not None,timeout=55)
                    return self.reply(200 if p['result'] else 504,p['result'] or {'error':'timeout_no_retry'})
                finally:s.pending=None
        except (TypeError,ValueError,KeyError):return self.reply(400,{'error':'invalid_payload'})


if __name__=='__main__':Server().serve_forever()
