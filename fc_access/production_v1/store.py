"""Single-delivery durable transport, without experimental campaign budgets.

QUEUED/DELIVERED become UNKNOWN on restart. IDs never replay; ambiguous results
are never treated as an empty response or a rejected write. Payload validation
happens before SQLite retention, including before rejected result logging.
"""
from contextlib import contextmanager
import json
import secrets
import sqlite3
from fc_access.sqlite_timing import TimedConnection
from datetime import datetime, timezone
from .contracts import command, context, fields, fences, integer, parse_response, token


class Store:
    def __init__(self, path, *, authorize_bid=None, source='native', now=None):
        if source not in {'native', 'fixture'}:
            raise ValueError('invalid_source')
        self.source = source
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.authorize_bid = authorize_bid
        self.host_epoch = secrets.token_hex(16)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, factory=TimedConnection)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS owner(context TEXT, owner TEXT, epoch INTEGER);
          CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, body TEXT, state TEXT, result TEXT);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, command_id TEXT, event TEXT);
          CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')
        with self.tx():
            self.db.execute("INSERT INTO events(command_id,event) SELECT id,'RESTART_UNKNOWN' FROM commands WHERE state IN ('QUEUED','DELIVERED')")
            self.db.execute("UPDATE commands SET state='UNKNOWN' WHERE state IN ('QUEUED','DELIVERED')")
            self.db.execute('UPDATE owner SET epoch=epoch+1')

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def owner(self):
        row = self.db.execute('SELECT * FROM owner').fetchone()
        return {'context': json.loads(row[0]), 'owner': row[1], 'epoch': row[2]} if row else None

    def activate(self, v):
        fields(v, {'context', 'owner', 'epoch'}); context(v['context']); token(v['owner']); integer(v['epoch'], 1)
        old = self.owner()
        if old and v != old and (v['context'] != old['context'] or v['epoch'] <= old['epoch']):
            raise ValueError('stale_owner')
        with self.tx():
            self.db.execute('DELETE FROM owner')
            self.db.execute('INSERT INTO owner VALUES(?,?,?)', (json.dumps(v['context'], sort_keys=True), v['owner'], v['epoch']))

    def check_peer(self, peer):
        fields(peer, {'context', 'fences'}); context(peer['context']); fences(peer['fences'])
        f = peer['fences']
        if f['host_epoch'] != self.host_epoch or self.owner() != {'context': peer['context'], 'owner': f['owner'], 'epoch': f['epoch']}:
            raise ValueError('stale_peer')

    def enqueue(self, c, peer):
        command(c); self.check_peer(peer)
        if c['context'] != peer['context'] or c['fences'] != peer['fences']:
            raise ValueError('wrong_peer')
        # No HTTP flag enables writes. This hook must check a durable authorized
        # intent; the shipped read-only server never installs one.
        if c['operation'] == 'bid' and (self.authorize_bid is None or self.authorize_bid(c) is not True):
            raise ValueError('mutation_requires_durable_intent')
        with self.tx():
            if c['operation'] == 'bid' and hasattr(self.authorize_bid, 'reconciled'):
                previous = self.db.execute("SELECT id,body FROM commands WHERE json_extract(body,'$.operation')='bid' AND state!='RECONCILED'").fetchall()
                for cid, body in previous:
                    if self.authorize_bid.reconciled(json.loads(body)):
                        self.db.execute("UPDATE commands SET state='RECONCILED' WHERE id=?", (cid,))
                        self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)', (cid, 'JOURNAL_RECONCILED'))
            if self.db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','DELIVERED')").fetchone():
                raise ValueError('native_owner_busy')
            if self.db.execute('SELECT 1 FROM commands WHERE id=?', (c['id'],)).fetchone():
                raise ValueError('duplicate_command')
            if c['operation'] == 'bid' and self.db.execute("SELECT 1 FROM commands WHERE json_extract(body,'$.operation')='bid' AND state!='RECONCILED'").fetchone():
                raise ValueError('reconciliation_required')
            self.db.execute('INSERT INTO commands VALUES(?,?,?,NULL)', (c['id'], json.dumps(c, sort_keys=True), 'QUEUED'))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)', (c['id'], 'RESERVED'))

    def claim(self, peer):
        self.check_peer(peer)
        with self.tx():
            row = self.db.execute("SELECT id,body FROM commands WHERE state='QUEUED' LIMIT 1").fetchone()
            if not row:
                return None
            c = json.loads(row[1])
            if c['context'] != peer['context'] or c['fences'] != peer['fences']:
                self.db.execute("UPDATE commands SET state='UNKNOWN' WHERE id=?", (row[0],))
                return None
            if c['operation'] == 'bid':
                from .contracts import stamp
                if stamp(c['params']['deadline']) <= self.now():
                    self.db.execute("UPDATE commands SET state='NOT_DISPATCHED' WHERE id=?", (row[0],))
                    return None
            self.db.execute("UPDATE commands SET state='DELIVERED' WHERE id=?", (row[0],))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)', (row[0], 'DELIVERED'))
            return c

    def finish(self, peer, cid, value):
        self.check_peer(peer); token(cid)
        with self.tx():
            row = self.db.execute('SELECT body,state FROM commands WHERE id=?', (cid,)).fetchone()
            if not row or row[1] != 'DELIVERED':
                raise ValueError('unknown_or_duplicate_result')
            c = json.loads(row[0])
            if c['context'] != peer['context'] or c['fences'] != peer['fences']:
                raise ValueError('wrong_result_peer')
            value = parse_response(value, c, source=self.source, now=self.now(), pricing_rows=c['operation'] == 'search' and
                                   c['params']['purpose'] == 'pricing')
            state = 'ACKNOWLEDGED' if value['result']['success'] else 'UNKNOWN'
            self.db.execute('UPDATE commands SET state=?,result=? WHERE id=?', (state, json.dumps(value, sort_keys=True), cid))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)', (cid, state))

    def uncertain(self, cid):
        token(cid)
        with self.tx():
            self.db.execute("UPDATE commands SET state='UNKNOWN' WHERE id=? AND state IN ('QUEUED','DELIVERED')", (cid,))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)', (cid, 'TIMEOUT_NO_RETRY'))

    def result(self, cid):
        row = self.db.execute('SELECT result FROM commands WHERE id=?', (token(cid),)).fetchone()
        return json.loads(row[0]) if row and row[0] else None
