"""Durable, conservative transport accounting; never a retry queue.

Public correlation IDs below are generated locally, never EA session material.
Each delivery is claimed in FULL synchronous SQLite before Edge can see it.
"""
from contextlib import contextmanager
import json
import sqlite3
import time

from fc_access.bidding_v1.contracts import Search, token, integer


def envelope(c):
    if not isinstance(c, dict) or set(c) != {'schema','id','operation','params','scope','owner','epoch','evidence_key'}:
        raise ValueError('invalid_command')
    if type(c['schema']) is not int or c['schema'] != 1:
        raise ValueError('invalid_schema')
    for k in ('id','scope','owner','evidence_key'):
        token(c[k])
    integer(c['epoch'], 1)
    p = c['params']
    if not isinstance(p, dict):
        raise ValueError('invalid_params')
    if c['operation'] in ('balance','watched'):
        if p:
            raise ValueError('invalid_params')
    elif c['operation'] == 'search':
        Search(**p)
    elif c['operation'] == 'bid':
        if set(p) != {'trade_id','item_id','definition_id','amount','minimum','cap','deadline'}:
            raise ValueError('invalid_bid')
        token(p['trade_id'], 'trade'); token(p['item_id'], 'item')
        for k in ('definition_id','amount','minimum','cap'):
            integer(p[k], 1)
        if p['amount'] != p['minimum'] or p['amount'] > p['cap']:
            raise ValueError('invalid_bid')
        from datetime import datetime
        from fc_access.bidding_v1.contracts import instant
        instant(datetime.fromisoformat(p['deadline']))
    else:
        raise ValueError('unsupported_operation')
    return c


class Store:
    def __init__(self, path, *, seconds=900, reads=12, mutations=0, exposure=0, now=time.time):
        if type(seconds) is not int or not 1 <= seconds <= 1800 or type(reads) is not int or not 1 <= reads <= 100:
            raise ValueError('invalid_window')
        if type(mutations) is not int or not 0 <= mutations <= 3 or type(exposure) is not int or not 0 <= exposure <= 10000:
            raise ValueError('invalid_limits')
        self.now = now
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS window(deadline REAL, reads INTEGER, mutations INTEGER, exposure INTEGER, stopped INTEGER);
          CREATE TABLE IF NOT EXISTS owner(scope TEXT, owner TEXT, epoch INTEGER);
          CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, operation TEXT, body TEXT, state TEXT, amount INTEGER, created REAL, delivered REAL, result TEXT);
          CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY, at REAL, event TEXT, command_id TEXT);
          CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')
        with self.tx():
            if self.db.execute('SELECT 1 FROM window').fetchone() is None:
                self.db.execute('INSERT INTO window VALUES(?,?,?,?,0)', (now()+seconds,reads,mutations,exposure))
            # Restart fences every old process/document. Budget and wall deadline persist.
            self.db.execute('UPDATE owner SET epoch=epoch+1')
            if self.db.execute("SELECT 1 FROM commands WHERE operation='bid' AND state IN ('QUEUED','DELIVERED','UNKNOWN')").fetchone():
                self.db.execute('UPDATE window SET stopped=1')
            self.db.execute("UPDATE commands SET state='UNKNOWN' WHERE state IN ('QUEUED','DELIVERED')")
            self.event('PROCESS_STARTED')

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK'); raise

    def event(self, name, cid=None):
        self.db.execute('INSERT INTO audit(at,event,command_id) VALUES(?,?,?)', (self.now(),name,cid))

    def owner(self):
        row = self.db.execute('SELECT scope,owner,epoch FROM owner').fetchone()
        return dict(zip(('scope','owner','epoch'), row)) if row else None

    def activate(self, v):
        if not isinstance(v,dict) or set(v) != {'scope','owner','epoch'}:
            raise ValueError('invalid_owner')
        token(v['scope']); token(v['owner']); integer(v['epoch'],1)
        with self.tx():
            old = self.owner()
            if old and old != v and (old['scope'] != v['scope'] or v['epoch'] <= old['epoch']):
                raise ValueError('stale_owner_or_epoch')
            if old != v:
                self.db.execute('DELETE FROM owner')
                self.db.execute('INSERT INTO owner VALUES(?,?,?)', (v['scope'],v['owner'],v['epoch']))
                self.event('OWNER_CHANGED')
        return True

    def check_owner(self, v):
        if {k:v.get(k) for k in ('scope','owner','epoch')} != self.owner() or self.owner() is None:
            raise ValueError('stale_owner_or_epoch')

    def health(self):
        deadline,reads,mutations,exposure,stopped = self.db.execute('SELECT * FROM window').fetchone()
        counts = dict(self.db.execute('SELECT operation,count(*) FROM commands GROUP BY operation'))
        spent = self.db.execute("SELECT COALESCE(SUM(amount),0) FROM commands WHERE operation='bid'").fetchone()[0]
        return {'deadline':deadline,'read_limit':reads,'mutation_limit':mutations,'exposure_limit':exposure,
                'reads_reserved':sum(n for op,n in counts.items() if op != 'bid'), 'mutations_reserved':counts.get('bid',0),
                'exposure_reserved':spent,'stopped':bool(stopped),'expired':self.now()>=deadline}

    def enqueue(self, c):
        envelope(c)
        with self.tx():
            self.check_owner(c)
            h=self.health()
            if h['stopped'] or h['expired']:
                raise ValueError('window_stopped_or_expired')
            if self.db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','DELIVERED')").fetchone():
                raise ValueError('busy')
            if self.db.execute('SELECT 1 FROM commands WHERE id=?',(c['id'],)).fetchone():
                raise ValueError('duplicate_command')
            write=c['operation']=='bid'; amount=c['params']['amount'] if write else 0
            if write:
                if h['mutations_reserved'] >= h['mutation_limit'] or h['exposure_reserved']+amount > h['exposure_limit']:
                    raise ValueError('mutation_or_exposure_limit')
                if self.db.execute("SELECT 1 FROM commands WHERE operation='bid' AND state!='RECONCILED'").fetchone():
                    raise ValueError('reconciliation_required')
            elif h['reads_reserved'] >= h['read_limit']:
                raise ValueError('read_limit')
            self.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,NULL,NULL)',
                (c['id'],c['operation'],json.dumps(c,sort_keys=True),'QUEUED',amount,self.now()))
            self.event('RESERVED',c['id'])

    def claim(self, peer):
        with self.tx():
            self.check_owner(peer)
            h=self.health()
            if h['stopped'] or h['expired']:
                return None
            row=self.db.execute("SELECT id,body FROM commands WHERE state='QUEUED' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            c=json.loads(row[1]); self.check_owner(c)
            if c['operation']=='bid':
                from datetime import datetime
                if self.now() >= datetime.fromisoformat(c['params']['deadline']).timestamp():
                    self.db.execute("UPDATE commands SET state='NOT_DISPATCHED' WHERE id=?",(row[0],))
                    self.event('DEADLINE_SKIPPED',row[0]); return None
            self.db.execute("UPDATE commands SET state='DELIVERED',delivered=? WHERE id=?",(self.now(),row[0]))
            self.event('DELIVERED',row[0]); return c

    def finish(self, peer, cid, result):
        from .adapter import parse_durable_response as parse_response
        with self.tx():
            self.check_owner(peer)
            row=self.db.execute('SELECT operation,state,body FROM commands WHERE id=?',(token(cid),)).fetchone()
            if not row or row[1]!='DELIVERED':
                raise ValueError('expired_or_duplicate_result')
            self.check_owner(json.loads(row[2]))
            r,f,_=parse_response(result,command_id=cid,operation=row[0])
            if f.source!='native':
                raise ValueError('wrong_source')
            state='ACKNOWLEDGED' if r['success'] else 'UNKNOWN'
            self.db.execute('UPDATE commands SET state=?,result=? WHERE id=?',(state,json.dumps(result,sort_keys=True),cid))
            if row[0]=='bid' and state=='UNKNOWN':
                self.db.execute('UPDATE window SET stopped=1')
            self.event(state,cid)

    def uncertain(self, cid):
        with self.tx():
            row=self.db.execute('SELECT operation,state FROM commands WHERE id=?',(cid,)).fetchone()
            if row and row[1] in ('QUEUED','DELIVERED'):
                self.db.execute("UPDATE commands SET state='UNKNOWN' WHERE id=?",(cid,))
                if row[0]=='bid': self.db.execute('UPDATE window SET stopped=1')
                self.event('TIMEOUT_NO_RETRY',cid)

    def result(self, cid):
        row=self.db.execute('SELECT result FROM commands WHERE id=?',(cid,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None
