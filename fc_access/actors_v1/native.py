"""Durable interprocess command mailbox and ONE native executor process.

Each command is a scheduling boundary, including local native helpers. No actor
owns Edge. The broker never retries a claimed command, including across crashes.
The bid journal remains the authority for writes in the production HTTP service.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import time

from fc_access.production_v1.contracts import LOCAL_OPERATIONS, command, parse_response, stamp
from .config import Config
from .locking import process_lock


def utc():
    return datetime.now(timezone.utc)


class Mailbox:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=35, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS runtime(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS work(seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE NOT NULL, role TEXT NOT NULL, priority INTEGER NOT NULL,
            enqueued TEXT NOT NULL, deadline TEXT NOT NULL, state TEXT NOT NULL,
            command TEXT NOT NULL, response TEXT, started TEXT, finished TEXT, reason TEXT,
            queue_ms REAL, roundtrip_ms REAL);
          CREATE TABLE IF NOT EXISTS native_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL, at TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS native_events_no_update BEFORE UPDATE ON native_events
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS native_events_no_delete BEFORE DELETE ON native_events
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')

    def close(self): self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def runtime(self):
        row = self.db.execute('SELECT body FROM runtime WHERE id=1').fetchone()
        if not row: raise ValueError('executor_not_initialized')
        return json.loads(row[0])

    def event(self, kind, c, *, at=None, **detail):
        command(c)
        body = dict(kind=kind,operation=c['operation'],epoch=c['fences']['epoch'],**detail)
        self.db.execute('INSERT INTO native_events(id,at,body) VALUES(?,?,?)',
            (c['id'],(at or utc()).isoformat(),json.dumps(body,sort_keys=True,allow_nan=False)))

    def enqueue(self, c, role, *, now=None):
        command(c)
        if role not in {'acquirer', 'bidder', 'maintenance', 'reconciliation'}:
            raise ValueError('invalid_actor')
        runtime = self.runtime()
        if c['context'] != runtime['context'] or c['fences'] != runtime['fences']:
            raise ValueError('stale_identity')
        at = now or utc()
        deadline = at+timedelta(seconds=runtime['config']['command_timeout_seconds'])
        if c['operation'] == 'bid': deadline = min(deadline, stamp(c['params']['deadline']))
        priority = {'maintenance': 0, 'acquirer': 10, 'bidder': 90, 'reconciliation': 100}[role]
        if c['operation'] in {'watched', 'status', 'bid'}: priority = max(priority, 90)
        # Canonical protocol validation rejects credentials and unknown parameters.
        with self.transaction():
            self.db.execute('INSERT INTO work(id,role,priority,enqueued,deadline,state,command) VALUES(?,?,?,?,?,?,?)',
                (c['id'], role, priority, at.isoformat(), deadline.isoformat(), 'WAITING', json.dumps(c, sort_keys=True)))
            self.event('ENQUEUED',c,at=at,role=role,priority=priority,params=c['params'])
        return c['id']


class QueueExecutor:
    """Synchronous actor-side transport; polling never resubmits a native call."""
    def __init__(self, path, role, *, clock=time.monotonic, sleep=time.sleep):
        self.mailbox, self.role = Mailbox(path), role
        self.clock, self.sleep = clock, sleep
        self.last_sqlite_ms = None

    def ownership_epoch(self, context):
        r = self.mailbox.runtime()
        if r['context'] != context: raise ValueError('stale_identity')
        return r['fences']['epoch']

    def attach(self, context, owner, epoch):
        r = self.mailbox.runtime()
        if r['context'] != context or (r['fences']['owner'], r['fences']['epoch']) != (owner, epoch):
            raise ValueError('stale_identity')
        return deepcopy(r['fences'])

    def execute(self, c):
        cid = self.mailbox.enqueue(c, self.role)
        end = self.clock()+self.mailbox.runtime()['config']['command_timeout_seconds']+1
        while self.clock() < end:
            state, response = self.mailbox.db.execute('SELECT state,response FROM work WHERE id=?', (cid,)).fetchone()
            if state == 'DONE': return json.loads(response)
            if state == 'UNKNOWN': raise TimeoutError('delivery_unknown_no_retry')
            self.sleep(.01)
        # A queued timeout is cancelled atomically; a claimed timeout is ambiguous.
        with self.mailbox.transaction():
            self.mailbox.db.execute("UPDATE work SET state='UNKNOWN',reason='CALLER_TIMEOUT' WHERE id=? AND state='WAITING'", (cid,))
            self.mailbox.event('CALLER_TIMEOUT',c)
        raise TimeoutError('delivery_unknown_no_retry')

    def close(self): self.mailbox.close()


class Broker:
    def __init__(self, mailbox, foundation, config, *, now=utc, clock=time.monotonic, sleep=time.sleep):
        self.mailbox, self.foundation, self.config = mailbox, foundation, config
        self.now, self.clock, self.sleep = now, clock, sleep
        self.last = float('-inf')

    def initialize(self):
        f = self.foundation
        with self.mailbox.transaction():
            # Restart invalidates every old delivery; bids never become replay work.
            for (encoded,) in self.mailbox.db.execute("SELECT command FROM work WHERE state IN ('WAITING','CLAIMED')").fetchall():
                self.mailbox.event('EXECUTOR_RESTART',json.loads(encoded),at=self.now())
            self.mailbox.db.execute("UPDATE work SET state='UNKNOWN',reason='EXECUTOR_RESTART' WHERE state IN ('WAITING','CLAIMED')")
            self.mailbox.db.execute('INSERT OR REPLACE INTO runtime VALUES(1,?)', (json.dumps(dict(
                context=f.adapter.context, fences=f.adapter.fences, config=self.config.export(), source=f.adapter.source,
                journal=str(Path(f.journal_path).resolve()), cache=str(Path(f.cache_path).resolve()))),))

    def run_one(self):
        db = self.mailbox.db
        with self.mailbox.transaction():
            at = self.now().isoformat()
            for (encoded,) in db.execute("SELECT command FROM work WHERE state='WAITING' AND deadline<=?",(at,)).fetchall():
                self.mailbox.event('DEADLINE_SKIPPED',json.loads(encoded),at=self.now())
            db.execute("UPDATE work SET state='UNKNOWN',reason='DEADLINE_SKIPPED' WHERE state='WAITING' AND deadline<=?", (at,))
            rows = db.execute("SELECT id,command,enqueued FROM work WHERE state='WAITING' ORDER BY priority DESC,deadline,seq").fetchall()
            row = next((r for r in rows if json.loads(r[1])['operation'] in LOCAL_OPERATIONS or
                self.clock()-self.last>=self.config.native_interval_seconds),None)
            if not row: return None
            cid, encoded, enqueued = row
            db.execute("UPDATE work SET state='CLAIMED',started=? WHERE id=?", (at, cid))
            self.mailbox.event('DISPATCH_CLAIM',json.loads(encoded),at=self.now())
        c = json.loads(encoded)
        start = self.clock()
        result, reason = None, 'DELIVERY_UNKNOWN'
        try:
            r = self.mailbox.runtime()
            if c['context'] != r['context'] or c['fences'] != r['fences']: raise ValueError('stale_identity')
            # The broker is the sole consumer and delegates to the reviewed boundary.
            raw = self.foundation.executor.executor.execute(c)
            result = parse_response(raw, c, now=self.now(), source=self.foundation.adapter.source,
                pricing_rows=c['operation'] == 'search' and c['params']['purpose'] == 'pricing')
            reason = 'NATIVE_RESPONSE'
        except Exception:
            pass  # Never retain arbitrary exception text, headers or bodies.
        finally:
            if c['operation'] not in LOCAL_OPERATIONS: self.last = self.clock()
        queue_ms = max(0,(stamp(at)-stamp(enqueued)).total_seconds()*1000)
        roundtrip_ms = (self.clock()-start)*1000
        with self.mailbox.transaction():
            db.execute('UPDATE work SET state=?,response=?,finished=?,reason=?,queue_ms=?,roundtrip_ms=? WHERE id=?',
                ('DONE' if result is not None else 'UNKNOWN', json.dumps(result) if result is not None else None,
                 self.now().isoformat(), reason, queue_ms, roundtrip_ms, cid))
            self.mailbox.event(reason,c,at=self.now(),queue_ms=queue_ms,roundtrip_ms=roundtrip_ms,
                native_service_ms=result['timing']['native_service_ms'] if result else None,
                request_count=result['freshness']['request_count'] if result else None)
        # Timings are persisted in work even if an actor dies before receiving them.
        return dict(command_id=cid, operation=c['operation'], reason=reason,
            queue_ms=queue_ms, roundtrip_ms=roundtrip_ms)

    def run(self, *, stop=lambda: False, max_commands=None, locked=False):
        from contextlib import nullcontext
        with nullcontext() if locked else process_lock(self.mailbox.path.with_suffix('.executor.lock')):
            self.initialize()
            count = 0
            while not stop() and (max_commands is None or count < max_commands):
                if self.run_one() is not None: count += 1
                else: self.sleep(.01)
