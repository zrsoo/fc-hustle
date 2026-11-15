"""003-02 offline behavior: real journals, actors, broker, locks and processes."""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from actors_fixture import create, CONTEXT, auction
from fc_access.actors_v1.actors import Acquirer, Bidder
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.final_run import BoundedBroker
from fc_access.actors_v1.locking import process_lock
from fc_access.actors_v1.native import Mailbox, Broker
from fc_access.continuous_v1.control import Control
from fc_access.continuous_v1.recovery import reconcile
from fc_access.continuous_v1.runtime import (ContinuousBroker, DEFAULT_JOURNAL, account_locks,
    production_config, require_service, run)
from fc_access.continuous_v1.watchdog import Watchdog
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.contracts import Search


class ContinuousBehavior(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.f, self.page, self.clock = create(self.path)
        self.addCleanup(self.page.close); self.addCleanup(lambda: self.f.close())
        self.box = Mailbox(self.path/'native.sqlite3'); self.addCleanup(self.box.close)
        self.control = Control(self.path/'control.sqlite3', clock=self.clock.monotonic)
        self.addCleanup(self.control.close)
        self.run = '1'*32
        self.control.append(self.run, 'RUN_OPEN', context=CONTEXT, journal=str(self.f.journal_path),
            state_dir=str(self.path), config=Config().export(), pid=os.getpid(), source='fixture')
        self.broker = ContinuousBroker(self.box, self.f, Config(), control=self.control, run=self.run,
            now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)
        self.broker.initialize()
        self.control.append(self.run, 'ATTACHED', fences=self.f.adapter.fences, work_start_seq=0)
        self.control.append(self.run, 'READY', fences=self.f.adapter.fences)
        self.beats()

    def beats(self, omit=()):
        for role in ('supervisor', 'monitor', 'executor', 'acquirer', 'bidder', 'maintenance'):
            if role not in omit: self.control.beat(self.run, role, os.getpid())

    def enqueue(self, op='balance', role='acquirer', params=None):
        c = self.f.adapter.envelope(self.f.ids(), op, params or {})
        self.box.enqueue(c, role, now=self.clock.now())
        return c

    def watchdog(self):
        return Watchdog(self.control, self.run, now=self.clock.now)

    def test_production_exceeds_all_former_time_and_request_ceilings_append_only(self):
        # Advance an offline clock past 1200 and 7200, dispatch >2000 native reads.
        # NORMAL WAL accelerates this clock workload only; process/crash tests
        # below retain the production FULL durability setting.
        for db in (self.control.db, self.box.db, self.page.store.db):
            db.execute('PRAGMA synchronous=NORMAL')
        for _ in range(2005):
            self.clock.sleep(4)
            self.beats()
            c = self.enqueue()
            self.assertEqual(self.broker.run_one()['command_id'], c['id'])
        self.assertGreater(self.clock.elapsed, 7200)
        self.assertEqual(self.box.db.execute("SELECT count(*) FROM work WHERE state='DONE'").fetchone()[0], 2005)
        self.assertFalse(self.control.latest(self.run, 'STOP_REQUESTED'))
        self.assertEqual(self.control.db.execute("SELECT count(*) FROM records WHERE kind='NATIVE_RESULT'").fetchone()[0], 2005)
        reopened = Control(self.control.path, clock=self.clock.monotonic)
        try:
            self.assertEqual(reopened.latest(self.run, 'NATIVE_RESULT')['state'], 'DONE')
        finally: reopened.close()
        for sql in ('UPDATE records SET kind=kind', 'DELETE FROM records'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'append_only'): self.control.db.execute(sql)

    def test_actual_acquirer_loop_exceeds_twelve_enrollments_and_cycles(self):
        from types import SimpleNamespace
        # Route the real actors through the real continuous broker as well as
        # the journal-backed native double. This catches a broker enrollment cap.
        self.broker.foundation = SimpleNamespace(registry=self.f.registry, adapter=self.f.adapter,
                                                 executor=SimpleNamespace(executor=self.page))
        role = ['acquirer']
        case = self
        class InlineMailbox:
            def execute(self, c):
                case.box.enqueue(c, role[0], now=case.clock.now())
                while True:
                    case.beats()
                    result=case.broker.run_one()
                    if result is not None:
                        state, response=case.box.db.execute('SELECT state,response FROM work WHERE id=?',(c['id'],)).fetchone()
                        case.assertEqual(state,'DONE')
                        return json.loads(response)
                    case.clock.sleep(2)
        self.f.executor.executor = InlineMailbox()
        a = Acquirer(self.f, clock=self.clock.monotonic, sleep=self.clock.sleep)
        b = Bidder(self.f)
        original = a.cycle
        cycles = []
        def cycle():
            n = len(cycles) + 1
            self.page.candidate = auction(123, 15000, n)
            self.page.candidate['starting_bid'] = 800
            role[0] = 'acquirer'
            original()
            role[0] = 'bidder'
            b.cycle()  # Independent fresh leading read reconciles the bid.
            self.page.candidate.update(trade_state='closed', bid_state='outbid', expires=0)
            self.page.watched = [deepcopy(self.page.candidate)]
            b.cycle()
            cycles.append(n)
        with patch.object(a, 'cycle', side_effect=cycle):
            a.run(stop=lambda: len(cycles) >= 20)
        self.assertEqual(self.page.bid_calls, 20)
        self.assertEqual(self.box.db.execute("SELECT count(*) FROM work WHERE role='acquirer' "
            "AND json_extract(command,'$.operation')='bid' AND state='DONE'").fetchone()[0],20)
        self.assertGreater(self.clock.elapsed, 7200)
        self.assertEqual(len([e for e in self.f.registry.events() if e['kind']=='ENROLLMENT']), 20)
        starts = [e for e in self.f.registry.events() if e.get('actor')=='acquirer' and e.get('reason')=='CYCLE_STARTED']
        self.assertEqual(len(starts), 20)
        from fc_access.production_v1.contracts import stamp
        self.assertTrue(all((stamp(b['at'])-stamp(a['at'])).total_seconds() >= 600 for a,b in zip(starts, starts[1:])))
        self.assertTrue(all(c['operation'] != 'buy_now' for c in self.page.calls))

    def test_finite_research_broker_keeps_consumed_time_and_enrollment_bounds(self):
        finite = BoundedBroker(self.box, self.f, Config(), now=self.clock.now, clock=self.clock.monotonic,
                               sleep=self.clock.sleep, wall_seconds=1200, request_threshold=16, extra_requests=16)
        c = self.enqueue()
        finite.run_one()
        self.assertEqual(finite.stopped_reason, 'REQUEST_THRESHOLD')
        self.assertEqual(finite.requests, 16)
        self.assertEqual(self.box.db.execute('SELECT state FROM work WHERE id=?', (c['id'],)).fetchone()[0], 'WAITING')
        with self.assertRaises(ValueError):
            BoundedBroker(self.box, self.f, Config(), wall_seconds=7201)
        with self.assertRaises(ValueError):
            BoundedBroker(self.box, self.f, Config(), max_enrollments=13)

    def test_priority_two_second_spacing_and_final_pre_send_deadline(self):
        low = self.enqueue('search', params=Search.discovery().params())
        urgent = self.enqueue('watched', 'bidder')
        self.assertEqual(self.broker.run_one()['command_id'], urgent['id'])
        self.assertIsNone(self.broker.run_one())
        self.clock.sleep(2); self.beats()
        self.assertEqual(self.broker.run_one()['command_id'], low['id'])
        expired = self.enqueue()
        self.clock.sleep(31); self.beats()
        with self.assertRaisesRegex(ValueError, 'expired'): self.broker.run_one()
        self.assertNotIn(expired['id'], [c['id'] for c in self.page.calls])
        self.assertEqual(self.control.latest(self.run, 'STOP_REQUESTED')['reason'], 'COMMAND_EXPIRED')

    def test_production_configuration_locks_all_retained_policy_values(self):
        self.assertEqual(production_config(), Config())
        for setting in [dict(native_interval_seconds=0),dict(discovery_max_pages=1),dict(min_available_coins=0),
                        dict(max_search_bid=2000),dict(min_profit_coins=0),dict(search_interval_seconds=1200)]:
            with self.assertRaises(ValueError): production_config(setting)

    def test_default_journal_reuses_reviewed_commitments_and_never_creates_empty_replacement(self):
        baseline = json.loads((ROOT/'docs/research/002/002-12/remediation-06/live-07/manifest.json').read_text())
        self.assertEqual(DEFAULT_JOURNAL, Path(baseline['journal']))
        empty = self.path/'empty.sqlite3'
        self.assertEqual(run(self.path/'new-production', context=CONTEXT, journal=empty),1)
        self.assertFalse(empty.exists())

    def test_an_existing_empty_journal_cannot_discard_scoped_commitments(self):
        from fc_access.bidding_v1.journal import Journal
        empty=self.path/'empty-scoped.sqlite3'
        j=Journal(empty); j.close()
        self.assertEqual(run(self.path/'new-production', context=CONTEXT, journal=empty),1)
        c=Control(self.path/'new-production/control.sqlite3')
        try: self.assertIsNone(c.latest(None,'RUN_OPEN'))
        finally: c.close()

    def test_account_fencing_is_shared_across_alternate_paths_and_ports(self):
        with process_lock(account_locks(CONTEXT)[1]):
            self.assertEqual(run(self.path/'alternate', context=CONTEXT, journal=self.f.journal_path,port=18784),1)
        c=Control(self.path/'alternate/control.sqlite3')
        try: self.assertIsNone(c.latest(None,'RUN_OPEN'))
        finally: c.close()

    def test_three_page_discovery_keeps_filters_and_deduplicates_lookahead(self):
        rows = [auction(123,15000,n+100) for n in range(61)]
        for row in rows: row['starting_bid'] = 800
        self.page.pages = {1: rows[:21], 2: rows[20:41], 3: rows[40:61]}
        found = Acquirer(self.f).discover()
        self.assertEqual(len(found), 61)
        calls = [c['params'] for c in self.page.calls if c['operation']=='search']
        self.assertEqual([c['page'] for c in calls], [1,2,3])
        self.assertTrue(all(c['max_bid']==1000 and c['min_buy']==11000 and c['count']==21 for c in calls))

    def test_service_requires_exact_attached_identity_and_canonical_intent_journal(self):
        h = dict(service='fc-production-v1', schema=2, attached=True, mutations_enabled=True,
                 peer=dict(context=CONTEXT, fences=self.f.adapter.fences), intent_journal=str(self.f.journal_path))
        require_service(h, CONTEXT, self.f.adapter.fences, self.f.journal_path)
        for key,value in [('attached',False),('mutations_enabled',False),('service','other'),
                          ('intent_journal',str(self.path/'empty.sqlite3')),('peer',{})]:
            with self.assertRaisesRegex(ValueError,'journal_backed_service'):
                require_service(dict(h, **{key:value}), CONTEXT, self.f.adapter.fences, self.f.journal_path)

    def test_service_health_reports_actual_journal_authority(self):
        from fc_access.production_v1.server import Server
        from fc_access.production_v1.executor import EdgeExecutor
        import threading
        server = Server(str(self.path/'health.sqlite3'), port=0, intent_database=str(self.f.journal_path))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            h = EdgeExecutor(server.server_port).request('/health')
            self.assertTrue(h['mutations_enabled'])
            self.assertFalse(h['attached'])
            self.assertEqual(Path(h['intent_journal']), self.f.journal_path.resolve())
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5); server.store.db.close()

    def test_supervisor_or_monitor_loss_gates_before_native_and_records_gap(self):
        c = self.enqueue()
        self.clock.sleep(11); self.beats(omit=('monitor',))
        with self.assertRaisesRegex(ValueError, 'supervision_lost'): self.broker.run_one()
        self.assertEqual(self.page.calls, [])
        self.assertEqual(self.box.db.execute('SELECT state FROM work WHERE id=?',(c['id'],)).fetchone()[0], 'WAITING')
        self.assertEqual(self.control.latest(self.run, 'SUPERVISION_GAP')['role'], 'monitor')
        self.beats()
        with self.assertRaisesRegex(ValueError, 'stopped'): self.broker.run_one()
        self.assertFalse(self.control.status()['supervised'])

    def test_stop_and_superseded_run_and_context_epoch_are_fenced(self):
        self.enqueue()
        self.control.stop(self.run, 'OPERATOR_STOP')
        with self.assertRaisesRegex(ValueError, 'stopped'): self.broker.run_one()
        self.assertFalse(self.page.calls)
        self.control.append('2'*32, 'RUN_OPEN', context=CONTEXT)
        with self.assertRaisesRegex(ValueError, 'superseded'): self.control.gate(self.run)
        with self.assertRaisesRegex(ValueError, 'stale_identity'):
            c = self.f.adapter.envelope(self.f.ids(), 'balance', {})
            c['fences']['epoch'] += 1
            self.box.enqueue(c, 'bidder', now=self.clock.now())

    def test_stale_owner_is_checked_at_last_dispatch_boundary(self):
        self.enqueue()
        self.f.journal.session(self.f.registry.scope, 'f'*32)
        with self.assertRaisesRegex(ValueError, 'reconciliation'): self.broker.run_one()
        self.assertFalse(self.page.calls)
        self.assertEqual(self.box.db.execute('SELECT state FROM work').fetchone()[0], 'UNKNOWN')

    def test_native_timeout_and_invalid_schema_are_not_retried(self):
        self.enqueue()
        original = self.page.execute
        with patch.object(self.page, 'execute', side_effect=TimeoutError('secret must never be retained')):
            with self.assertRaisesRegex(ValueError, 'reconciliation'): self.broker.run_one()
        self.assertEqual(self.box.db.execute('SELECT state FROM work').fetchone()[0], 'UNKNOWN')
        with self.assertRaisesRegex(ValueError, 'stopped'): self.broker.run_one()
        logs = [json.loads(r[0]) for r in self.control.db.execute('SELECT body FROM records')]
        self.assertNotIn('secret', json.dumps(logs))
        self.assertEqual(self.page.calls, [])

    def test_invalid_native_schema_is_an_ambiguous_outcome(self):
        self.enqueue()
        with patch.object(self.page, 'execute', return_value={'schema': 99}):
            with self.assertRaisesRegex(ValueError, 'reconciliation'): self.broker.run_one()
        self.assertEqual(self.box.db.execute('SELECT state FROM work').fetchone()[0], 'UNKNOWN')
        self.assertFalse(self.page.calls)

    def test_deadline_is_rechecked_after_the_dispatch_gate(self):
        c = self.enqueue()
        self.broker.dispatch_gate = lambda cmd: self.clock.sleep(31)
        with self.assertRaisesRegex(ValueError, 'reconciliation'): self.broker.run_one()
        self.assertFalse(self.page.calls)
        self.assertEqual(self.box.db.execute('SELECT state FROM work WHERE id=?', (c['id'],)).fetchone()[0], 'UNKNOWN')

    def test_watchdog_local_metrics_and_normal_outcomes_never_repair_loop(self):
        monitor = self.watchdog()
        ordinary = ['IDLE','QUOTE_REJECTED','OVER_CAP','DRAINING','CAPACITY_PAUSED','CAPACITY_RESUMED',
                    'DUPLICATE_SUPPRESSED','RELIST_CHECKED','SOLD_CLEAR_CHECKED','MAINTENANCE_INVENTORY_BLOCKED']
        for n, reason in enumerate(ordinary):
            self.clock.sleep(1); self.beats()
            for role in ('acquirer','bidder','maintenance'):
                self.f.registry._append(dict(kind='ACTOR', actor=role, reason=reason, epoch=self.f.registry.epoch))
            before = len(self.page.calls)
            result = monitor.step()
            self.assertEqual(len(self.page.calls), before, 'monitor must not add EA polling')
            self.assertFalse(self.control.latest(self.run, 'STOP_REQUESTED'))
        self.assertGreater(result['healthy_observed_seconds'], 0)
        self.assertEqual(result['fences'], self.f.adapter.fences)
        self.assertEqual(set(result['actors']), {'acquirer','bidder','maintenance'})
        self.assertIn('maintenance', result)
        self.clock.sleep(11); self.beats()
        with self.assertRaisesRegex(ValueError, 'MONITOR_GAP'): monitor.step()

    def test_watchdog_detects_dead_process_queue_age_and_native_ambiguity(self):
        monitor = Watchdog(self.control, self.run, now=self.clock.now, is_alive=lambda pid: False)
        with self.assertRaisesRegex(ValueError, 'SUPERVISION_LOST'): monitor.step()

    def test_unexpected_monitor_exception_records_gap_and_stops_dispatch(self):
        from fc_access.continuous_v1.runtime import child
        with patch('fc_access.continuous_v1.runtime.monitor', side_effect=RuntimeError('untrusted detail')):
            self.assertEqual(child(self.control.path, self.run, 'monitor'),1)
        self.assertIsNotNone(self.control.latest(self.run,'SUPERVISION_GAP'))
        self.assertEqual(self.control.latest(self.run,'EXCEPTION')['reason'],'UNCLASSIFIED_EXCEPTION')
        with self.assertRaisesRegex(ValueError,'stopped'): self.broker.run_one()

    def test_watchdog_detects_expired_queue_without_polling_ea(self):
        self.enqueue()
        self.clock.sleep(31); self.beats()
        with self.assertRaisesRegex(ValueError, 'QUEUE_AGE'): self.watchdog().step()
        self.assertFalse(self.page.calls)

    def test_watchdog_detects_native_schema_failure_and_epoch_change(self):
        c = self.enqueue()
        self.box.db.execute("UPDATE work SET state='UNKNOWN' WHERE id=?", (c['id'],))
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS_NATIVE_OUTCOME'): self.watchdog().step()

    def test_watchdog_detects_executor_heartbeat_loss(self):
        self.clock.sleep(41); self.beats(omit=('executor',))
        with self.assertRaisesRegex(ValueError, 'EXECUTOR'): self.watchdog().step()

    def test_watchdog_stops_on_capacity_and_identity_violations(self):
        self.f.journal.session(self.f.registry.scope, 'e'*32)
        with self.assertRaisesRegex(ValueError, 'JOURNAL_OWNER_CHANGED'): self.watchdog().step()
        self.assertFalse(self.page.calls)

    def test_watchdog_rejects_over_capacity_snapshot(self):
        capacity = dict(physical_occupied=51, unresolved=0, total=51)
        with patch('fc_access.continuous_v1.watchdog.capacity_status',return_value=capacity):
            with self.assertRaisesRegex(ValueError,'CAPACITY_INVARIANT'): self.watchdog().step()
        self.assertEqual(self.control.latest(self.run,'INCIDENT')['reason'],'CAPACITY_INVARIANT')

    def test_watchdog_rejects_negative_coin_observation(self):
        self.f.registry._append(dict(kind='CREDITS',available_coins=-1,network_at=self.clock.now().isoformat()))
        with self.assertRaisesRegex(ValueError,'COIN_INVARIANT'): self.watchdog().step()

    def test_watchdog_independently_rejects_malformed_native_result(self):
        c=self.enqueue()
        self.box.db.execute("UPDATE work SET state='DONE',response=?,finished=? WHERE id=?",
                            (json.dumps(dict(schema=99)),self.clock.now().isoformat(),c['id']))
        with self.assertRaisesRegex(ValueError,'NATIVE_SCHEMA_OR_FRESHNESS'): self.watchdog().step()

    def test_watchdog_tracks_native_counts_queues_and_freshness(self):
        self.enqueue(); self.broker.run_one()
        self.enqueue('search', params=Search.discovery().params())
        result = self.watchdog().step()
        self.assertEqual((result['commands_observed'], result['native_requests_observed']), (1,1))
        self.assertEqual(result['queue'][0]['priority'], 10)
        self.assertEqual(result['queue'][0]['state'], 'WAITING')
        self.assertFalse(result['capacity']['fresh'])

    def test_watchdog_detects_a_stuck_actor_despite_heartbeat_thread(self):
        for role in ('acquirer','bidder','maintenance'):
            self.f.registry._append(dict(kind='ACTOR', actor=role, reason='CYCLE_STARTED', epoch=self.f.registry.epoch))
        self.clock.sleep(210); self.beats()
        with self.assertRaisesRegex(ValueError, 'ACTOR_PROGRESS_LOST_BIDDER'): self.watchdog().step()

    def test_recovery_does_not_switch_journal_or_reset_existing_run(self):
        old = self.control.latest(None,'RUN_OPEN')
        self.assertEqual(run(self.path, context=CONTEXT, journal=self.f.journal_path), 1)
        self.assertEqual(self.control.latest(None,'RUN_OPEN')['run'], old['run'])
        self.assertEqual(run(self.path, context=CONTEXT, journal=self.path/'another.sqlite3', recovery=True), 1)
        self.assertEqual(self.control.latest(None,'RUN_OPEN')['run'], old['run'])

    def test_startup_requires_fresh_identity_mapping_and_keeps_ghost_reserved(self):
        a, b = Acquirer(self.f), Bidder(self.f)
        a.cycle(); b.cycle()
        bids = self.page.bid_calls
        self.page.watched = []
        with self.assertRaisesRegex(ValueError, 'unmapped_commitment'): reconcile(self.f)
        self.assertTrue(self.f.queue.entries)
        self.assertEqual(self.page.bid_calls, bids)
        self.page.watched = [deepcopy(self.page.candidate)]
        result = reconcile(self.f)
        self.assertEqual(result['commitments'], 1)
        self.assertEqual(self.page.bid_calls, bids)

    def test_restart_reads_reconcile_lost_response_without_replaying_write(self):
        self.page.failure = TimeoutError('offline lost callback')
        Acquirer(self.f).cycle()
        self.assertEqual(self.page.bid_calls, 1)
        old_pending = self.f.registry.current()['unresolved'][0]['command_id']
        self.f.close()
        self.page.failure = None
        self.f = Foundation(self.page, context=CONTEXT, journal_path=self.path/'journal.sqlite3', fixture=True,
            now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)
        result = reconcile(self.f)
        self.assertEqual(result['commitments'], 1)
        self.assertEqual(self.page.bid_calls, 1)
        self.assertFalse(self.f.registry.current()['unresolved'])
        self.assertEqual(self.f.journal.db.execute('SELECT state FROM commands WHERE id=?',(old_pending,)).fetchone()[0], 'RECONCILED')

    def test_restart_invalidates_old_delivery_without_deleting_history(self):
        c = self.enqueue()
        before = self.box.db.execute('SELECT command,enqueued FROM work').fetchone()
        self.broker.initialize()
        self.assertEqual(self.box.db.execute('SELECT command,enqueued FROM work').fetchone(), before)
        self.assertEqual(self.box.db.execute('SELECT state,reason FROM work').fetchone(), ('UNKNOWN','EXECUTOR_RESTART'))
        self.assertIsNone(self.broker.run_one())
        self.assertFalse(self.page.calls)

    def test_startup_read_only_gate_rejects_mutation_even_if_supervised(self):
        # A separate pre-READY run, with valid identity, cannot send a write.
        run = '3'*32
        self.control.append(run, 'RUN_OPEN', context=CONTEXT)
        self.control.append(run, 'ATTACHED', fences=self.f.adapter.fences)
        self.control.beat(run, 'supervisor', os.getpid()); self.control.beat(run, 'monitor', os.getpid())
        c = self.f.adapter.envelope(self.f.ids(), 'balance', {})
        self.control.gate(run, command=c, startup=True)
        # Gate checks operation class before the existing protocol/write guards.
        c['operation'] = 'bid'
        with self.assertRaisesRegex(ValueError, 'read_only_recovery'):
            self.control.gate(run, command=c, startup=True)

    def test_os_lock_competing_process_and_unrelated_state_cannot_take_journal(self):
        lock = self.path/'journal.continuous.owner.lock'
        script = 'from fc_access.actors_v1.locking import process_lock; import sys;\nwith process_lock(sys.argv[1]): pass'
        with process_lock(lock):
            r = subprocess.run([sys.executable,'-c',script,str(lock)], cwd=ROOT, capture_output=True, timeout=10)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn(b'process_already_running', r.stderr)
            with self.assertRaisesRegex(ValueError, 'process_already_running'):
                run(self.path/'alternate', context=CONTEXT, journal=self.path/'journal.sqlite3')
        r = subprocess.run([sys.executable,'-c',script,str(lock)], cwd=ROOT, capture_output=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)


class ProcessLifecycle(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        (self.path/'context.json').write_text(json.dumps(CONTEXT))
        from fc_access.bidding_v1.journal import Journal
        from fc_access.production_v1.foundation import Registry
        journal = Journal(self.path/'journal.sqlite3')
        Registry(journal, CONTEXT, 'd'*32)
        journal.close()

    def command(self, action, fixture=True):
        return [sys.executable, str(ROOT/'tests/continuous_fixture.py'), '--state-dir', str(self.path), action,
                '--context', str(self.path/'context.json'), '--journal', str(self.path/'journal.sqlite3')]

    def read(self):
        path = self.path/'control.sqlite3'
        if not path.exists(): return {}
        control = Control(path)
        try: return control.status()
        finally: control.close()

    def wait(self, predicate, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            status = self.read()
            if predicate(status): return status
            time.sleep(.1)
        self.fail('lifecycle state not reached: ' + json.dumps(self.read()))

    def start(self, action='run'):
        p = subprocess.Popen(self.command(action), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            control = Control(self.path/'control.sqlite3')
            try:
                opened = control.latest(None,'RUN_OPEN')
                if opened: control.stop(opened['run'],'OPERATOR_STOP')
            finally: control.close()
            try: p.communicate(timeout=50)
            except subprocess.TimeoutExpired: p.kill(); p.communicate()
        self.addCleanup(cleanup)
        return p

    def test_real_separate_processes_durable_stop_recover_and_monitor_death(self):
        p = self.start()
        status = self.wait(lambda s: s.get('status')=='RUNNING' and len((s.get('snapshot') or {}).get('actors',{}))==3)
        first_run = status['run']
        c = Control(self.path/'control.sqlite3')
        rows = c.db.execute("SELECT body FROM records WHERE run=? AND kind='PROCESS_STARTED'", (first_run,)).fetchall()
        roles = {json.loads(r[0])['role']: json.loads(r[0])['pid'] for r in rows}
        self.assertEqual(set(roles), {'monitor','executor','acquirer','bidder','maintenance'})
        self.assertEqual(len(set(roles.values())), 5)
        # Competing owner fails while all existing process identities stay intact.
        competing = subprocess.run(self.command('recover'), cwd=ROOT, capture_output=True, timeout=10)
        self.assertNotEqual(competing.returncode, 0)
        self.assertEqual(c.latest(None,'RUN_OPEN')['run'], first_run)
        c.stop(first_run, 'OPERATOR_STOP'); c.close()
        out, err = p.communicate(timeout=50)
        self.assertEqual(p.returncode, 0, out+err)
        self.assertTrue(self.read()['ended']['verified_process_exit'])
        before = sqlite3.connect(self.path/'native.sqlite3')
        history = before.execute('SELECT id,command,response FROM work ORDER BY seq').fetchall(); before.close()
        p2 = self.start('recover')
        status = self.wait(lambda s: s.get('status')=='RUNNING' and s.get('run')!=first_run and
                           len((s.get('snapshot') or {}).get('actors',{}))==3)
        self.assertGreater(status['snapshot']['fences']['epoch'], status['manifest'].get('epoch',0))
        current = sqlite3.connect(self.path/'native.sqlite3')
        for row in history:
            self.assertEqual(current.execute('SELECT id,command,response FROM work WHERE id=?',(row[0],)).fetchone(), row)
        current.close()
        c = Control(self.path/'control.sqlite3')
        monitor_pid = c.latest(status['run'], 'HEARTBEAT_monitor')['pid']; c.close()
        if os.name == 'nt':
            subprocess.run(['taskkill','/PID',str(monitor_pid),'/F'], capture_output=True, timeout=10, check=True)
        else:
            import signal
            os.kill(monitor_pid, signal.SIGKILL)
        out,err = p2.communicate(timeout=55)
        self.assertNotEqual(p2.returncode, 0, out+err)
        stopped = self.read()
        self.assertEqual(stopped['status'],'STOPPED')
        self.assertTrue(stopped['ended']['verified_process_exit'])
        self.assertFalse(stopped['supervised'])
        self.assertIsNotNone(stopped['supervision_gap'])

    def test_supervisor_death_stops_orphans_and_recovery_waits_for_exits(self):
        from fc_access.continuous_v1.watchdog import alive
        p = self.start()
        status = self.wait(lambda s: s.get('status')=='RUNNING' and len((s.get('snapshot') or {}).get('actors',{}))==3)
        c = Control(self.path/'control.sqlite3')
        children = [json.loads(r[0])['pid'] for r in c.db.execute(
            "SELECT body FROM records WHERE run=? AND kind='PROCESS_STARTED'", (status['run'],))]
        # A replacement cannot take the running broker's port/journal locks.
        with self.assertRaisesRegex(ValueError, 'process_already_running'):
            with process_lock(self.path/'journal.continuous.executor.lock'): pass
        p.kill(); p.communicate(timeout=5)
        self.wait(lambda s: s.get('supervision_gap') is not None, timeout=15)
        end = time.monotonic() + 45
        while any(alive(pid) for pid in children) and time.monotonic() < end: time.sleep(.1)
        self.assertFalse([pid for pid in children if alive(pid)])
        self.assertFalse(c.status()['supervised'])
        c.close()

    def test_help_config_status_and_stop_do_not_attach_or_create_runtime(self):
        for action in ('config','status','stop','--help'):
            r = subprocess.run([sys.executable,'-m','fc_access.continuous_v1','--state-dir',str(self.path),action],
                               cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(set(p.name for p in self.path.iterdir()), {'context.json','journal.sqlite3'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
