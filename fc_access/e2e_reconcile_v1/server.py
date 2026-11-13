"""Existing objective continuation: four reads / 120 seconds / zero writes."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from experiments.market_discovery_followup_v1.server import persona_projection

ROOT=Path(__file__).resolve().parents[2];DIRECTORY=ROOT/'docs/research/001c/001c-06-resume-01'
p=str((ROOT/'browser/e2e-reconcile-v1').resolve());p=p[0].upper()+p[1:]
EXTENSION_ID=''.join(chr(97+int(c,16)) for c in hashlib.sha256(p.encode('utf-16-le')).hexdigest()[:32])
OPERATIONS=('status','watched','unassigned','balance')

class Ledger:
    def __init__(self,path,now=time.time):
        self.now=now;self.db=sqlite3.connect(path,isolation_level=None,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT);CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,operation TEXT UNIQUE,state TEXT,created REAL,delivered REAL,result TEXT);CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,at REAL,reason TEXT,id TEXT);')
        if self.get('owner') is None:self.set('owner',secrets.token_hex(16));self.set('stopped',False)
        if self.db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','DELIVERED')").fetchone():self.stop('RESTART_NO_RETRY')
    def get(self,k):
        r=self.db.execute('SELECT v FROM meta WHERE k=?',(k,)).fetchone();return json.loads(r[0]) if r else None
    def set(self,k,v):self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(k,json.dumps(v)))
    def event(self,r,cid=None):self.db.execute('INSERT INTO events(at,reason,id) VALUES(?,?,?)',(self.now(),r,cid))
    def stop(self,r):self.set('stopped',True);self.event(r)
    def health(self):return {'owner':self.get('owner'),'deadline':self.get('deadline'),'stopped':self.get('stopped'),'expired':self.get('deadline') is not None and self.now()>=self.get('deadline'),'commands_reserved':self.db.execute('SELECT COUNT(*) FROM commands').fetchone()[0],'command_limit':4,'seconds_limit':120,'mutation_limit':0}
    def reserve(self,operation):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            h=self.health()
            if operation not in OPERATIONS or h['stopped'] or h['expired'] or h['commands_reserved']>=4:raise ValueError('read_only_limit')
            if self.db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','DELIVERED')").fetchone():raise ValueError('serialized_busy')
            cid=hashlib.sha256(('001c-06:reconciliation-01:'+operation).encode()).hexdigest()[:32]
            self.db.execute("INSERT INTO commands VALUES(?,?,'QUEUED',?,NULL,NULL)",(cid,operation,self.now()))
            if h['deadline'] is None:self.set('deadline',self.now()+120)
            self.event('RESERVED',cid);self.db.execute('COMMIT');return cid
        except BaseException:self.db.execute('ROLLBACK');raise
    def claim(self):
        h=self.health()
        if h['stopped'] or h['expired']:return None
        r=self.db.execute("SELECT id,operation FROM commands WHERE state='QUEUED'").fetchone()
        if r:self.db.execute("UPDATE commands SET state='DELIVERED',delivered=? WHERE id=?",(self.now(),r[0]));self.event('DELIVERED',r[0]);return {'id':r[0],'operation':r[1],'params':{}}

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,path):
        self.ledger=Ledger(path);self.boot=secrets.token_hex(16);self.peer=None;self.last=0;self.condition=threading.Condition()
        super().__init__(('127.0.0.1',8781),Handler)
    def handle_error(self,*args):pass

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,code,v):
        b=json.dumps(v,allow_nan=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers()
        try:self.wfile.write(b)
        except OSError:pass
    def health(self):
        s=self.server;return {**s.ledger.health(),'service':'fc-e2e-reconciliation-v1','boot':s.boot,'attached':time.monotonic()-s.last<45,'extension_id':EXTENSION_ID,'peer':s.peer}
    def allowed(self,ext=False):return self.headers.get('Host')=='127.0.0.1:8781' and (self.headers.get('Origin')=='chrome-extension://'+EXTENSION_ID if ext else self.headers.get('Origin') is None and self.headers.get('Sec-Fetch-Site') is None)
    def do_GET(self):
        if not self.allowed():return self.reply(403,{'error':'origin_denied'})
        with self.server.condition:return self.reply(200,self.health())
    def do_POST(self):
        s=self.server
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=262144 or self.headers.get('Content-Type')!='application/json':raise ValueError('invalid_payload')
            v=json.loads(self.rfile.read(size))
            if not self.allowed(self.path in ('/hello','/next','/result')):return self.reply(403,{'error':'origin_denied'})
            with s.condition:
                if self.path=='/hello':
                    if v=={'protocol':1}:return self.reply(200,self.health())
                    p=v['peer']
                    if set(p)!={'boot','owner','worker','document','persona','source_match','original_trade_resource_match'} or p['boot']!=s.boot or p['owner']!=s.ledger.get('owner'):raise ValueError('wrong_peer')
                    persona_projection(p['persona']);s.peer=p;s.last=time.monotonic();return self.reply(200,self.health())
                if self.path=='/next':
                    if v!=s.peer:raise ValueError('stale_peer')
                    end=time.monotonic()+18;s.last=time.monotonic()
                    while v==s.peer:
                        c=s.ledger.claim()
                        if c:return self.reply(200,{**c,'boot':s.boot,'owner':s.ledger.get('owner')})
                        if time.monotonic()>=end:return self.reply(200,None)
                        s.condition.wait(.25)
                    raise ValueError('stale_peer')
                if self.path=='/result':
                    if v['peer']!=s.peer:raise ValueError('stale_peer')
                    cid=v['id'];r=v['result'];row=s.ledger.db.execute('SELECT operation,state FROM commands WHERE id=?',(cid,)).fetchone()
                    if not row or row[1]!='DELIVERED' or r['command_id']!=cid or r['operation']!=row[0]:raise ValueError('result_mismatch')
                    validate_result(r)
                    s.ledger.db.execute('UPDATE commands SET state=?,result=? WHERE id=?',('OBSERVED' if r['success'] else 'UNKNOWN',json.dumps(r),cid));s.ledger.event('RESULT',cid)
                    if not r['success'] or any(n['status'] in (401,403,429,458,459,461) for n in r['network']):s.ledger.stop('ACCESS_OR_READ_FAILURE')
                    s.condition.notify_all();return self.reply(200,{'accepted':True})
                if self.path=='/close':s.ledger.stop('CLOSED');return self.reply(200,{'closed':True})
                if self.path!='/run' or set(v)!={'operation'}:raise ValueError('read_only')
                if not s.peer or time.monotonic()-s.last>=45 or not s.peer['persona']['accepted']:raise ValueError('attachment_or_persona_required')
                cid=s.ledger.reserve(v['operation']);s.condition.notify_all();end=time.monotonic()+23
                while True:
                    r=s.ledger.db.execute('SELECT result FROM commands WHERE id=?',(cid,)).fetchone()[0]
                    if r:return self.reply(200,json.loads(r))
                    if time.monotonic()>=end:s.ledger.stop('TIMEOUT_NO_RETRY');return self.reply(504,{'error':'timeout_no_retry'})
                    s.condition.wait(.25)
        except (ValueError,TypeError,KeyError,sqlite3.IntegrityError):return self.reply(409,{'error':'rejected_no_retry'})

def validate_result(r):
    from fc_access.e2e_v1.server import validate_result as old_validate
    if r['operation'] not in OPERATIONS:raise ValueError('read_only')
    # Reuse the existing positive projection, substituting only the reviewed
    # additional GET route while validating. Retained bytes remain unchanged.
    if r['operation']=='status':
        replacement={**r,'operation':'watched','network':[{**n,'route':'/ut/game/fc27/watchlist'} for n in r['network']]}
        if any(n['route']!='/ut/game/fc27/trade/status/lite' or n['method']!='GET' for n in r['network']):raise ValueError('wrong_status_route')
        old_validate(replacement)
    else:old_validate(r)

if __name__=='__main__':Server(DIRECTORY/'live.sqlite').serve_forever()
