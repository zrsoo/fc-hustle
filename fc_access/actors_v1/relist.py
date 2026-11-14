"""Explicit, restart-safe 61-minute relist ticks; no import-time/live launch.

The cadence is committed before inventory or dispatch. Missed windows collapse
to one tick; a consumed window is never replayed. BulkTransfer owns all native
write intent, ambiguity handling and exact per-item readback contracts.
"""
from datetime import timedelta
import json
import time

from fc_access.production_v1.bulk import BulkTransfer, pending
from fc_access.production_v1.contracts import stamp
from .config import Config
from .locking import process_lock
from .native import QueueExecutor


class BulkRelistScheduler:
    def __init__(self, foundation, config=None, *, sleep=time.sleep):
        self.f, self.config, self.sleep = foundation, config or Config(), sleep
        transport = foundation.executor.executor
        if foundation.adapter.source != 'fixture' and (
                not isinstance(transport, QueueExecutor) or transport.role != 'maintenance'):
            raise ValueError('prioritized_maintenance_executor_required')
        foundation.journal.db.executescript('''
          CREATE TABLE IF NOT EXISTS relist_schedule_v1(
            scope TEXT PRIMARY KEY, next_due TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS relist_ticks_v1(
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, started TEXT NOT NULL,
            state TEXT NOT NULL, result TEXT);
          CREATE TRIGGER IF NOT EXISTS relist_tick_identity_immutable BEFORE UPDATE OF
            id,scope,started ON relist_ticks_v1
            BEGIN SELECT RAISE(ABORT,'immutable_relist_tick'); END;
        ''')

    def checkpoint(self, stage):
        """Fault injection seam."""

    def event(self, reason, **data):
        self.f.registry._append(dict(kind='BULK_RELIST_SCHEDULE', reason=reason,
            epoch=self.f.registry.epoch, **data))

    def finish(self, tick, result):
        with self.f.journal.transaction():
            self.f.registry.check()
            self.f.journal.db.execute("UPDATE relist_ticks_v1 SET state='FINISHED',result=? WHERE id=?",
                (json.dumps(result, sort_keys=True), tick))
            self.event('NOOP' if result['status'] == 'SKIPPED' else 'TICK_FINISHED', tick_id=tick, result=result)
        return dict(tick_id=tick, **result)

    def step(self):
        """Run at most one due window, or recover one interrupted window by reads.

        UTC deadlines persist across process/executor epochs. Early calls do no
        account work. No catch-up loop or write retry follows an interrupted tick.
        """
        f, j = self.f, self.f.journal
        with process_lock(f.journal_path.with_suffix('.relist.lock')):
            f.registry.check()
            old = j.db.execute("SELECT id FROM relist_ticks_v1 WHERE scope=? AND state='RUNNING' ORDER BY started LIMIT 1",
                               (f.registry.scope,)).fetchone()
            if old:
                service = BulkTransfer(f)
                try:
                    inventory = service.inventory()
                    for write in pending(j, f.registry.scope):
                        service.reconcile(write['command_id'])
                    result = dict(status='INTERRUPTED_READ_ONLY', read_id=inventory['command_id'])
                except (ValueError, TimeoutError):
                    result = dict(status='RECOVERY_BLOCKED')
                    # Keep recovery pending; no new cadence or dispatch authority.
                    self.event('RECOVERY_BLOCKED', tick_id=old[0])
                    return dict(tick_id=old[0], **result)
                return self.finish(old[0], result)
            with j.transaction():
                f.registry.check()
                at = f.now()
                row = j.db.execute('SELECT next_due FROM relist_schedule_v1 WHERE scope=?',
                                   (f.registry.scope,)).fetchone()
                if row and at < stamp(row[0]):
                    return dict(status='NOT_DUE', next_due=row[0])
                tick = f.ids()
                due = (at+timedelta(seconds=self.config.bulk_relist_interval_seconds)).isoformat()
                j.db.execute('INSERT OR REPLACE INTO relist_schedule_v1 VALUES(?,?)', (f.registry.scope, due))
                j.db.execute("INSERT INTO relist_ticks_v1 VALUES(?,?,?,'RUNNING',NULL)",
                             (tick, f.registry.scope, at.isoformat()))
                self.event('TICK_STARTED', tick_id=tick, next_due=due,
                    interval_seconds=self.config.bulk_relist_interval_seconds)
            self.checkpoint('scheduled')
            try:
                result = BulkTransfer(f).execute('relist_all')
            except (ValueError, TimeoutError):
                # Store only a known reason. Native error text may contain secrets.
                result = dict(status='BLOCKED')
            self.checkpoint('completed')
            return self.finish(tick, result)

    def run(self, *, ticks, stop=lambda: False):
        """Explicit bounded runner. Recurring live launch belongs to item 12."""
        if type(ticks) is not int or ticks < 1:
            raise ValueError('positive_tick_limit_required')
        completed = 0
        while completed < ticks and not stop():
            result = self.step()
            if result['status'] == 'NOT_DUE':
                delay = (stamp(result['next_due'])-self.f.now()).total_seconds()
                self.sleep(max(.001, min(.25, delay)))
            elif result['status'] == 'RECOVERY_BLOCKED':
                return result
            else:
                completed += 1
        return dict(status='STOPPED', ticks=completed)
