"""Pinned loopback transport; SQLite intents precede every browser delivery.

This is a single finite integration window, never a periodic trading actor.
"""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from . import policy

ROOT=Path(__file__).resolve().parents[2]
DIRECTORY=ROOT/'docs/research/001c/001c-06-resume-02'
p=str((ROOT/'browser/e2e-live-v2').resolve());p=p[0].upper()+p[1:]
EXTENSION_ID=''.join(chr(97+int(n,16)) for n in hashlib.sha256(p.encode('utf-16-le')).hexdigest()[:32])
LIMITS={'seconds':900,'reads':40,'mutations':4,'bid_writes':2,'gross_coins':2000,'auctions':1,'individual_bid':1000,'reserve':5000}

class Ledger:
    def __init__(self,path,now=time.time):
        self.now=now;self.db=sqlite3.connect(path,isolation_level=None,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,stage TEXT UNIQUE,operation TEXT,body TEXT,state TEXT,created REAL,delivered REAL,result TEXT);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,at REAL,reason TEXT,data TEXT);
        CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
        CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;''')
        if self.get('limits') is None:
            self.set('limits',LIMITS);self.set('owner',secrets.token_hex(16));self.set('stopped',False)
            self.event('CREATED',{'limits':LIMITS})
        # Restarts do not extend time or redeliver any command.
        if self.db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','DELIVERED')").fetchone():
            self.db.execute("UPDATE commands SET state='UNKNOWN' WHERE state IN ('QUEUED','DELIVERED')")
            self.stop('RESTART_UNCERTAINTY')
    def get(self,k):
        r=self.db.execute('SELECT value FROM meta WHERE key=?',(k,)).fetchone();return json.loads(r[0]) if r else None
    def set(self,k,v):self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(k,json.dumps(v)))
    def event(self,r,d=None):self.db.execute('INSERT INTO events(at,reason,data) VALUES(?,?,?)',(self.now(),r,json.dumps(d or {})))
    def stop(self,reason):self.set('stopped',True);self.event(reason)
    def evidence(self):return {r[0]:json.loads(r[1]) for r in self.db.execute('SELECT id,result FROM commands WHERE result IS NOT NULL')}
    def health(self):
        rows=list(self.db.execute('SELECT operation,body FROM commands'));limit=self.get('limits');deadline=self.get('deadline')
        return {'limits':limit,'deadline':deadline,'expired':deadline is not None and self.now()>=deadline,'stopped':self.get('stopped'),
          'reads_reserved':sum(op not in policy.WRITES for op,_ in rows),'mutations_reserved':sum(op in policy.WRITES for op,_ in rows),
          'bid_writes_reserved':sum(op=='bid' for op,_ in rows),'gross_coins_reserved':sum(json.loads(b)['params']['amount'] for op,b in rows if op=='bid')}
    def reserve(self,c):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            h=self.health();op=c['operation'];p=c['params'];evidence=self.evidence()
            if h['stopped'] or h['expired']:raise ValueError('window_closed')
            if self.db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','DELIVERED')").fetchone():raise ValueError('serialized_busy')
            if op not in policy.ROUTES:raise ValueError('operation_denied')
            if op not in policy.WRITES:
                if h['reads_reserved']>=h['limits']['reads']:raise ValueError('read_limit')
                allowed={'page','count','max_bid','min_buy','max_buy','definition_id'} if op=='search' else {'definition_id'} if op=='caps' else set()
                if set(p)-allowed or any(type(v)is not int or v<0 for v in p.values()):raise ValueError('invalid_read')
                if op=='search' and (p.get('page',1) not in (1,2) or p.get('count',21)!=21):raise ValueError('invalid_search')
            else:
                if h['mutations_reserved']>=h['limits']['mutations']:raise ValueError('mutation_limit')
                if self.get('unreconciled'):raise ValueError('reconciliation_required')
                if op=='bid':
                    if h['bid_writes_reserved']>=h['limits']['bid_writes'] or h['gross_coins_reserved']+p['amount']>h['limits']['gross_coins']:raise ValueError('bid_limit')
                    enrollment=self.get('enrollment')
                    if enrollment and (enrollment['trade_id'],enrollment['item_id'],enrollment['definition_id'])!=(p['trade_id'],p['item_id'],p['definition_id']):raise ValueError('one_auction_limit')
                    enrollment=policy.bid_plan(p,evidence,enrollment,self.now());self.set('enrollment',enrollment);p['cap']=enrollment['cap']
                    self.event('OPENING_INTENT' if h['bid_writes_reserved']==0 else 'REBID_INTENT',{'command_id':c['id'],'pricing':enrollment,'amount':p['amount']})
                else:
                    self.won_preconditions(p,evidence)
                    if p['owned_operation']=='watched':
                        owned=policy.exact(evidence[p['owned_id']],self.get('enrollment')['trade_id'],p['item_id'],p['definition_id'])
                        if owned['native_is_won'] is not True:raise ValueError('native_won_ownership_required')
                    if self.db.execute('SELECT 1 FROM commands WHERE operation=?',(op,)).fetchone():raise ValueError('one_handoff_per_kind')
                    if op=='list':
                        rr=policy.rules(evidence[p['caps_id']],p['definition_id'],self.now())
                        if not p['starting_bid']<p['buy_now_price'] or any(policy.pricing.floor_price(p[k],rr)!=p[k] for k in ('starting_bid','buy_now_price')):raise ValueError('illegal_listing_prices')
                self.set('unreconciled',c['id'])
            self.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,NULL,NULL)',(c['id'],c['stage'],op,json.dumps(c),'QUEUED',self.now()))
            if self.get('deadline') is None:self.set('deadline',self.now()+h['limits']['seconds'])
            self.event('RESERVED_BEFORE_DELIVERY',{'id':c['id'],'operation':op});self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
    def won_preconditions(self,p,evidence):
        en=self.get('enrollment')
        if not en or (p['item_id'],p['definition_id'])!=(en['item_id'],en['definition_id']):raise ValueError('owned_identity_required')
        status=policy.fresh(evidence[p['won_status_id']],'watched',self.now())
        owned=policy.fresh(evidence[p['owned_id']],p['owned_operation'],self.now())
        if status['command_id']==owned['command_id']:raise ValueError('independent_ownership_required')
        state=policy.classify(status,owned,trade=en['trade_id'],item=en['item_id'],definition=en['definition_id'],paid=p['paid'])
        if state!='WON':raise ValueError('conclusive_win_required')
        balance=policy.fresh(evidence[p['balance_id']],'balance',self.now())
        if self.get('initial_balance')-balance['credits']!=p['paid']:raise ValueError('paid_cost_not_reconciled')
    def claim(self):
        h=self.health()
        if h['expired'] or h['stopped']:return None
        row=self.db.execute("SELECT id,body FROM commands WHERE state='QUEUED'").fetchone()
        if row:self.db.execute("UPDATE commands SET state='DELIVERED',delivered=? WHERE id=?",(self.now(),row[0]));self.event('DELIVERED',{'id':row[0]});return json.loads(row[1])
    def finish(self,cid,result):
        row=self.db.execute('SELECT operation,state,body FROM commands WHERE id=?',(cid,)).fetchone()
        if not row or row[1]!='DELIVERED' or result.get('command_id')!=cid or result.get('operation')!=row[0]:raise ValueError('result_correlation')
        # Positive allowlist: a compromised or stale extension cannot store raw fields.
        validate_result(result)
        if row[0]=='bid':
            command=json.loads(row[2])
            if len(result['network'])!=1 or result['network'][0].get('bid_amount')!=command['params']['amount']:
                self.stop('ACTUAL_BID_BODY_UNVERIFIED')
        self.db.execute('UPDATE commands SET state=?,result=? WHERE id=?',('ACKNOWLEDGED' if result['success'] else 'UNKNOWN',json.dumps(result),cid))
        self.event('RESULT',{'id':cid,'success':result['success'],'network_count':len(result['network'])})
        if any(n['status'] in (401,403,429,458,459,461) for n in result['network']) or row[0] in policy.WRITES and not result['success']:self.stop('ACCESS_OR_MUTATION_UNCERTAINTY')
        if result['success'] and row[0]=='balance' and self.get('initial_balance') is None:self.set('initial_balance',result['credits'])
    def reconcile(self,p):
        cid=self.get('unreconciled')
        if not cid:raise ValueError('no_pending_mutation')
        row=self.db.execute('SELECT operation,body,delivered,result FROM commands WHERE id=?',(cid,)).fetchone();op,body,delivered,ack=row
        if not ack or not json.loads(ack)['success']:raise ValueError('no_ack')
        cmd=json.loads(body);ev=self.evidence();status=ev[p['status_id']];balance=ev[p['balance_id']]
        policy.fresh(status,'watched' if op=='bid' else 'transfer_list',self.now());policy.fresh(balance,'balance',self.now())
        if any(policy.at(r['network'][0]['started_at']).timestamp()<=delivered for r in (status,balance)):raise ValueError('post_write_reads_required')
        if op=='bid':
            a=policy.exact(status,cmd['params']['trade_id'],cmd['params']['item_id'],cmd['params']['definition_id'])
            if a['bid_state'] not in ('highest','outbid') or a['current_bid']<cmd['params']['amount']:raise ValueError('bid_state_unverified')
        else:
            matches=[r for r in status['rows'] if r['item_id']==cmd['params']['item_id'] and r['definition_id']==cmd['params']['definition_id']]
            if len(matches)!=1:raise ValueError('handoff_not_read_back')
            if op=='list' and (matches[0]['trade_state']!='active' or matches[0]['expires']<=0 or any(matches[0][k]!=cmd['params'][k] for k in ('starting_bid','buy_now_price'))):raise ValueError('listing_not_verified')
        self.db.execute("UPDATE commands SET state='RECONCILED' WHERE id=?",(cid,));self.set('unreconciled',None);self.event('INDEPENDENT_READBACK',{'id':cid,**p})
    def hold(self,p):
        en=self.get('enrollment');r=policy.fresh(self.evidence()[p['status_id']],'watched',self.now())
        a=policy.exact(r,en['trade_id'],en['item_id'],en['definition_id'])
        if a['bid_state']!='highest' or a['trade_state']!='active':raise ValueError('leading_required')
        self.event('HOLD',{'status_id':p['status_id'],'trade_id':en['trade_id'],'bid_writes':self.health()['bid_writes_reserved'],'additional_write':False})

def validate_result(r):
    from fc_access.e2e_v1.server import validate_result as original
    for n in r['network']:
        if 'bid_amount' not in n or n['bid_amount'] is not None and (type(n['bid_amount']) is not int or n['bid_amount']<1):raise ValueError('invalid_bid_body_projection')
    for collection in ('rows','wire_rows'):
        for x in r[collection] or []:
            if 'native_is_won' not in x or type(x['native_is_won']) is not bool:raise ValueError('invalid_ownership_projection')
    original({**r,'network':[{k:v for k,v in n.items() if k!='bid_amount'} for n in r['network']],
      'rows':[{k:v for k,v in x.items() if k!='native_is_won'} for x in r['rows']] if r['rows'] is not None else None,
      'wire_rows':[{k:v for k,v in x.items() if k!='native_is_won'} for x in r['wire_rows']] if r['wire_rows'] is not None else None})

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,path):
        from fc_access.e2e_reconcile_v1.audit import inspect
        resolution=inspect()
        if resolution['status']!='NET_EFFECT_RECONCILED_NO_ACQUISITION' or resolution['current_unresolved_active_bid_exposure']!=0:
            raise ValueError('prior_mutation_not_reconciled')
        self.ledger=Ledger(path);self.boot=secrets.token_hex(16);self.condition=threading.Condition();self.peer=None;self.last=0
        super().__init__(('127.0.0.1',8782),Handler)
    def handle_error(self,*args):pass

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,code,v):
        b=json.dumps(v,allow_nan=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers()
        try:self.wfile.write(b)
        except OSError:pass
    def allowed(self,extension=False):return self.headers.get('Host')=='127.0.0.1:8782' and (self.headers.get('Origin')=='chrome-extension://'+EXTENSION_ID if extension else self.headers.get('Origin') is None and self.headers.get('Sec-Fetch-Site') is None)
    def health(self):
        s=self.server;return {**s.ledger.health(),'service':'fc-e2e-live-v2','boot':s.boot,'owner':s.ledger.get('owner'),'extension_id':EXTENSION_ID,'attached':time.monotonic()-s.last<45,'peer':s.peer}
    def do_GET(self):
        if not self.allowed():return self.reply(403,{'error':'origin_denied'})
        with self.server.condition:return self.reply(200,self.health())
    def do_POST(self):
        s=self.server
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=262144 or self.headers.get('Content-Type')!='application/json':raise ValueError('invalid_body')
            v=json.loads(self.rfile.read(size))
            if not self.allowed(self.path in ('/hello','/next','/result')):return self.reply(403,{'error':'origin_denied'})
            with s.condition:
                if self.path=='/hello':
                    if v=={'protocol':1}:return self.reply(200,self.health())
                    p=v['peer']
                    if p['boot']!=s.boot or p['owner']!=s.ledger.get('owner'):raise ValueError('wrong_owner')
                    from experiments.market_discovery_followup_v1.server import persona_projection
                    persona_projection(p['persona'])
                    if set(p)!={'boot','owner','worker','document','persona'}:raise ValueError('invalid_peer')
                    if s.peer and p!=s.peer and s.ledger.get('unreconciled'):s.ledger.stop('OWNERSHIP_CHANGED_WITH_PENDING_MUTATION')
                    s.peer=p;s.last=time.monotonic();return self.reply(200,self.health())
                if self.path=='/next':
                    if v!=s.peer:raise ValueError('stale_peer')
                    s.last=time.monotonic();end=time.monotonic()+18
                    while v==s.peer:
                        c=s.ledger.claim()
                        if c or time.monotonic()>=end:return self.reply(200,c)
                        s.condition.wait(.25)
                    raise ValueError('worker_replaced')
                if self.path=='/result':
                    if v['peer']!=s.peer:raise ValueError('stale_peer')
                    s.ledger.finish(v['id'],v['result']);s.condition.notify_all();return self.reply(200,{'accepted':True})
                if self.path=='/close':s.ledger.stop('WINDOW_CLOSED');return self.reply(200,{'closed':True})
                if self.path=='/reconcile':s.ledger.reconcile(v);return self.reply(200,{'verified':True})
                if self.path=='/hold':s.ledger.hold(v);return self.reply(200,{'hold':True})
                if self.path!='/run':raise ValueError('unknown_route')
                if not s.peer or time.monotonic()-s.last>=45 or not s.peer['persona']['accepted']:raise ValueError('attachment_or_persona_required')
                if set(v)!={'stage','operation','params'}:raise ValueError('invalid_command')
                c={**v,'id':hashlib.sha256(('001c-06:resume-02:'+v['stage']).encode()).hexdigest()[:32],'evidence_key':'06'*16,'boot':s.boot,'owner':s.ledger.get('owner')}
                s.ledger.reserve(c);s.condition.notify_all();end=time.monotonic()+23
                while True:
                    r=s.ledger.db.execute('SELECT result FROM commands WHERE id=?',(c['id'],)).fetchone()[0]
                    if r:return self.reply(200,json.loads(r))
                    if time.monotonic()>=end:
                        s.ledger.db.execute("UPDATE commands SET state='UNKNOWN' WHERE id=?",(c['id'],));s.ledger.stop('TIMEOUT_NO_RETRY');return self.reply(504,{'error':'timeout_no_retry'})
                    s.condition.wait(.25)
        except (ValueError,KeyError,TypeError,sqlite3.IntegrityError) as e:
            # Errors are authored reason codes; no arbitrary service/browser text.
            return self.reply(409,{'error':str(e) if isinstance(e,ValueError) else 'rejected'})

if __name__=='__main__':Server(DIRECTORY/'live.sqlite').serve_forever()
