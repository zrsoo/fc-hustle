"""Deterministic, local-only monitor. No executor or network client is imported."""
import json
import os
from pathlib import Path
import sqlite3

from fc_access.production_v1.contracts import parse_response, stamp
from fc_access.production_v1.foundation import scope_for
from fc_access.bidding_v1.journal import Journal
from fc_access.bidding_v1.capacity import status as capacity_status


def alive(pid):
    if os.name == 'nt':
        import ctypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        handle = k.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259
        finally:
            k.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Watchdog:
    def __init__(self, control, run, *, now, is_alive=alive):
        self.control, self.run, self.now, self.is_alive = control, run, now, is_alive
        self.work_cursor = self.registry_cursor = 0
        self.requests = self.commands = 0
        self.previous_tick = None
        self.healthy = 0

    def fail(self, reason):
        self.control.append(self.run, 'INCIDENT', reason=reason)
        self.control.stop(self.run, reason)
        raise ValueError(reason)

    def step(self):
        c, run = self.control, self.run
        opened = c.latest(run, 'RUN_OPEN')
        for role in ('supervisor',):
            beat = c.latest(run, 'HEARTBEAT_' + role)
            if not beat or not 0 <= c.age(run, role) <= 10 or not self.is_alive(beat['pid']):
                c.append(run, 'SUPERVISION_GAP', role=role)
                self.fail('SUPERVISION_LOST')
        if c.latest(run, 'STOP_REQUESTED'):
            return None
        attached, ready = c.latest(run, 'ATTACHED'), c.latest(run, 'READY')
        if not attached:
            if c.clock() - opened['tick'] > 90:
                self.fail('ATTACHMENT_TIMEOUT')
            return None
        self.work_cursor = max(self.work_cursor, attached.get('work_start_seq', 0))
        if not ready and c.clock() - attached['tick'] > 180:
            self.fail('RECONCILIATION_TIMEOUT')
        grace = opened['config']['command_timeout_seconds'] + 10
        roles = ('executor', 'acquirer', 'bidder', 'maintenance') if ready else ('executor',)
        for role in roles:
            beat = c.latest(run, 'HEARTBEAT_' + role)
            if not beat and ready and c.clock() - ready['tick'] < 10:
                continue
            limit = grace if role == 'executor' else 10
            if not beat or not 0 <= c.age(run, role) <= limit or not self.is_alive(beat['pid']):
                self.fail('PROCESS_OR_HEARTBEAT_LOST_' + role.upper())
        path = Path(opened['state_dir']) / 'native.sqlite3'
        if not path.exists():
            return None
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            runtime = json.loads(db.execute('SELECT body FROM runtime WHERE id=1').fetchone()[0])
            if runtime['context'] != opened['context'] or runtime['fences'] != attached['fences']:
                self.fail('RUNTIME_IDENTITY_CHANGED')
            queue = []
            for role, priority, enqueued, deadline, state in db.execute(
                    "SELECT role,priority,enqueued,deadline,state FROM work WHERE seq>? AND state IN ('WAITING','CLAIMED')",
                    (attached.get('work_start_seq', 0),)):
                age = (self.now() - stamp(enqueued)).total_seconds()
                queue.append(dict(role=role, priority=priority, age_seconds=age, state=state))
                if age < 0 or age > grace or (state == 'WAITING' and stamp(deadline) <= self.now()):
                    self.fail('COMMAND_DEADLINE_OR_QUEUE_AGE')
            # A CLAIMED command can be the lowest outstanding sequence. Do not
            # advance past it and miss its eventual completion under priority scheduling.
            rows = db.execute('SELECT seq,command,response,state,finished FROM work WHERE seq>? ORDER BY seq',
                              (self.work_cursor,)).fetchall()
            for seq, encoded, response, state, finished in rows:
                if state in {'WAITING', 'CLAIMED'}:
                    break
                command = json.loads(encoded)
                if state != 'DONE' or not response:
                    self.fail('AMBIGUOUS_NATIVE_OUTCOME')
                try:
                    value = parse_response(json.loads(response), command, source=runtime['source'], now=stamp(finished),
                        pricing_rows=command['operation'] == 'search' and command['params']['purpose'] == 'pricing')
                except (ValueError, KeyError, TypeError):
                    self.fail('NATIVE_SCHEMA_OR_FRESHNESS')
                if command['context'] != opened['context'] or command['fences'] != attached['fences']:
                    self.fail('COMMAND_IDENTITY_CHANGED')
                if not value['result']['success'] or value['freshness']['request_count'] > 16:
                    self.fail('NATIVE_RESPONSE_FAILURE')
                self.commands += 1
                self.requests += value['freshness']['request_count']
                self.work_cursor = seq
            # Even if an earlier command is waiting, any later ambiguous result
            # must gate immediately, rather than wait for sequence chronology.
            if db.execute("SELECT 1 FROM work WHERE seq>? AND state='UNKNOWN'", (self.work_cursor,)).fetchone():
                self.fail('AMBIGUOUS_NATIVE_OUTCOME')
        finally:
            db.close()
        journal = Journal(opened['journal'], readonly=True)
        try:
            scope = scope_for(opened['context'])
            try:
                journal._owner(scope, attached['fences']['owner'], attached['fences']['epoch'])
            except ValueError:
                self.fail('JOURNAL_OWNER_CHANGED')
            capacity = capacity_status(journal, scope, now=self.now())
            if any(capacity[k] is not None and capacity[k] > 50 for k in ('physical_occupied', 'unresolved', 'total')):
                self.fail('CAPACITY_INVARIANT')
            intents = [dict(command_id=r[0], state=r[1], age_seconds=(self.now()-stamp(r[2])).total_seconds())
                for r in journal.db.execute("SELECT id,state,intended_at FROM commands WHERE scope=? "
                    "AND state NOT IN ('RECONCILED','NOT_DISPATCHED')", (scope,))]
            from fc_access.production_v1.bulk import pending as pending_bulk
            from fc_access.production_v1.resale import pending as pending_resale
            intents.extend(pending_bulk(journal, scope)); intents.extend(pending_resale(journal, scope))
            for intent in intents:
                if 'age_seconds' not in intent:
                    table = 'bulk_writes_v1' if intent['operation'] in {'clear_sold','relist_all'} else 'resale_writes_v1'
                    at = journal.db.execute('SELECT at FROM ' + table + ' WHERE id=?', (intent['command_id'],)).fetchone()[0]
                    intent['age_seconds'] = (self.now()-stamp(at)).total_seconds()
            if ready and any(i.get('age_seconds', 0) > 120 for i in intents):
                self.fail('RECONCILIATION_OVERDUE')
            progress, maintenance, credits = {}, {}, None
            # Latest role events plus cycle starts/finishes make sleeping actors
            # distinct from stuck cycles. Ordinary strategy outcomes are data.
            for role in ('acquirer', 'bidder', 'maintenance'):
                row = journal.db.execute("SELECT at,body FROM registry_events_v1 WHERE scope=? "
                    "AND json_extract(body,'$.actor')=? AND json_extract(body,'$.epoch')=? "
                    "ORDER BY seq DESC LIMIT 1", (scope, role, attached['fences']['epoch'])).fetchone()
                if row:
                    progress[role] = dict(at=row[0], **json.loads(row[1]))
                    if role == 'maintenance':
                        maintenance = progress[role]
                    age = (self.now()-stamp(row[0])).total_seconds()
                    interval = opened['config']['search_interval_seconds' if role == 'acquirer' else 'target_check_interval_seconds']
                    allowance = 600 if role == 'acquirer' else max(180, capacity['unresolved'] * 120)
                    if age < 0 or age > interval + allowance:
                        self.fail('ACTOR_PROGRESS_LOST_' + role.upper())
                elif ready and c.clock() - ready['tick'] > 10:
                    self.fail('ACTOR_PROGRESS_MISSING_' + role.upper())
            for seq, body in journal.db.execute('SELECT seq,body FROM registry_events_v1 WHERE scope=? AND seq>? ORDER BY seq',
                                               (scope, self.registry_cursor)):
                event = json.loads(body)
                if event.get('epoch') == attached['fences']['epoch'] and event.get('reason') in {
                        'CYCLE_BLOCKED', 'MISSING_OR_STALE_IDENTITY', 'OUTCOME_STILL_UNKNOWN', 'PHYSICAL_ITEM_MISMATCH',
                        'PAID_COST_UNPROVEN', 'INCOMPATIBLE'}:
                    self.fail('ACTOR_INVARIANT_' + event['reason'])
                self.registry_cursor = seq
            row = journal.db.execute("SELECT body FROM registry_events_v1 WHERE scope=? "
                "AND json_extract(body,'$.kind')='CREDITS' ORDER BY seq DESC LIMIT 1", (scope,)).fetchone()
            if row:
                credits = json.loads(row[0])
                credits['age_seconds'] = (self.now()-stamp(credits['network_at'])).total_seconds()
                if type(credits['available_coins']) is not int or credits['available_coins'] < 0:
                    self.fail('COIN_INVARIANT')
            row = journal.db.execute("SELECT reason FROM events WHERE scope=? AND reason IN ('DRAINING','DRAINED') "
                                     'ORDER BY seq DESC LIMIT 1', (scope,)).fetchone()
            draining = bool(row and row[0] == 'DRAINING')
        finally:
            journal.close()
        # Uptime counts only adjacent successful observations in this new segment.
        if ready and self.previous_tick is not None:
            delta = c.clock() - self.previous_tick
            if not 0 <= delta <= 10:
                c.append(run, 'SUPERVISION_GAP', role='monitor')
                self.fail('MONITOR_GAP')
            self.healthy += delta
        self.previous_tick = c.clock() if ready else None
        recovery_commands, recovery_requests = c.db.execute("SELECT count(*),coalesce(sum("
            "json_extract(body,'$.response.freshness.request_count')),0) FROM records WHERE run=? AND kind='RECOVERY_READ'",
            (run,)).fetchone()
        recovery_intents = c.db.execute("SELECT count(*) FROM records WHERE run=? AND kind='RECOVERY_INTENT'", (run,)).fetchone()[0]
        result = dict(context=runtime['context'], fences=runtime['fences'], queue=queue, capacity=capacity,
            credits=credits, draining=draining, intents=intents, actors=progress, maintenance=maintenance,
            commands_observed=self.commands + recovery_commands, native_requests_observed=self.requests + recovery_requests,
            recovery_commands=recovery_commands, recovery_native_requests=recovery_requests,
            recovery_commands_without_response=recovery_intents - recovery_commands,
            healthy_observed_seconds=self.healthy, source=runtime['source'])
        c.append(run, 'SNAPSHOT', **result)
        return result
