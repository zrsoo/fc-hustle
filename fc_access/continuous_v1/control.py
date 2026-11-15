"""Append-only local supervision records. This database holds no EA credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time


class Control:
    def __init__(self, path, *, clock=time.monotonic):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS records(seq INTEGER PRIMARY KEY AUTOINCREMENT,
            run TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL, tick REAL NOT NULL, body TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS records_latest ON records(run,kind,seq);
          CREATE INDEX IF NOT EXISTS records_global_latest ON records(kind,seq);
          CREATE TRIGGER IF NOT EXISTS records_immutable_update BEFORE UPDATE ON records
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS records_immutable_delete BEFORE DELETE ON records
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')

    def close(self):
        self.db.close()

    def append(self, run, kind, **body):
        self.db.execute('INSERT INTO records(run,kind,at,tick,body) VALUES(?,?,?,?,?)',
                        (run, kind, datetime.now(timezone.utc).isoformat(), self.clock(),
                         json.dumps(body, sort_keys=True, allow_nan=False)))

    def latest(self, run, kind):
        row = self.db.execute('SELECT seq,run,at,tick,body FROM records WHERE '
            + ('run=? AND ' if run is not None else '') + 'kind=? ORDER BY seq DESC LIMIT 1',
            (run, kind) if run is not None else (kind,)).fetchone()
        return dict(seq=row[0], run=row[1], at=row[2], tick=row[3], **json.loads(row[4])) if row else None

    def beat(self, run, role, pid):
        self.append(run, 'HEARTBEAT_' + role, pid=pid)

    def age(self, run, role):
        row = self.latest(run, 'HEARTBEAT_' + role)
        return self.clock() - row['tick'] if row else float('inf')

    def stop(self, run, reason):
        # Duplicate stop requests cannot reopen dispatch or overwrite a gap.
        self.append(run, 'STOP_REQUESTED', reason=reason)

    def gate(self, run, *, lease=10, command=None, startup=False):
        opened = self.latest(None, 'RUN_OPEN')
        if not opened or opened['run'] != run:
            raise ValueError('superseded_run')
        if self.latest(run, 'STOP_REQUESTED') or self.latest(run, 'RUN_STOPPED'):
            raise ValueError('production_stopped')
        for role in ('supervisor', 'monitor'):
            if not 0 <= self.age(run, role) <= lease:
                self.append(run, 'SUPERVISION_GAP', role=role)
                self.stop(run, 'SUPERVISION_LOST')
                raise ValueError('supervision_lost')
        ready = self.latest(run, 'READY')
        if not startup and not ready:
            raise ValueError('reconciliation_required')
        if command is not None:
            from fc_access.production_v1.contracts import MUTATIONS
            attached = self.latest(run, 'ATTACHED')
            if not attached or command['context'] != opened['context'] or command['fences'] != attached['fences']:
                raise ValueError('stale_identity')
            if command['operation'] in MUTATIONS and not ready:
                raise ValueError('read_only_recovery')

    def status(self):
        opened = self.latest(None, 'RUN_OPEN')
        if not opened:
            return dict(status='NOT_STARTED')
        run = opened['run']
        stop, ended = self.latest(run, 'STOP_REQUESTED'), self.latest(run, 'RUN_STOPPED')
        ready, snapshot = self.latest(run, 'READY'), self.latest(run, 'SNAPSHOT')
        fresh = all(0 <= self.age(run, r) <= 10 for r in ('supervisor', 'monitor'))
        healthy = bool(ready and fresh and not stop and not ended)
        return dict(run=run, context=opened['context'], manifest=opened, status=(
            'STOPPED' if ended else 'STOPPING' if stop else 'RUNNING' if healthy else 'GATED'),
            stop=stop, ended=ended, snapshot=snapshot, supervised=healthy,
            incident=self.latest(run, 'INCIDENT'), supervision_gap=self.latest(run, 'SUPERVISION_GAP'),
            healthy_observed_seconds=(snapshot or {}).get('healthy_observed_seconds', 0),
            heartbeat_age_seconds={r: (round(self.age(run, r), 3) if self.latest(run, 'HEARTBEAT_' + r) else None)
                                   for r in ('supervisor', 'monitor', 'executor', 'acquirer', 'bidder', 'maintenance')})
