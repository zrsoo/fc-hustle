"""002-10 offline acceptance. Real durable journals, mailbox and native VM.

No browser attachment, EA requests, source hashes or recurring live execution.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from actors_fixture import Clock, CONTEXT
from test_00209_bulk import BulkPage, inventory
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.native import Broker, Mailbox, QueueExecutor
from fc_access.actors_v1.relist import BulkRelistScheduler
from fc_access.bidding_v1 import capacity
from fc_access.production_v1.bulk import BulkTransfer, pending
from fc_access.production_v1.contracts import stamp
from fc_access.production_v1.foundation import Foundation, JournalAuthority


class Acceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.clock = Clock()
        self.page = BulkPage(self.path, self.clock)
        self.page.transfer_items = self.page.transfer_items[2:]
        self.f = self.open()
        self.addCleanup(self.page.close); self.addCleanup(lambda: self.f.close())
        self.scheduler = self.new_scheduler()

    def open(self):
        return Foundation(self.page, context=CONTEXT, journal_path=self.path/'journal.sqlite3',
            fixture=True, now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)

    def new_scheduler(self):
        return BulkRelistScheduler(self.f, sleep=self.clock.sleep)

    def restart(self):
        self.f.close(); self.f = self.open(); self.scheduler = self.new_scheduler()

    def due(self):
        value = self.f.journal.db.execute('SELECT next_due FROM relist_schedule_v1').fetchone()[0]
        self.clock.sleep(max(0, (stamp(value)-self.clock.now()).total_seconds()))

    def events(self, kind='BULK_RELIST_SCHEDULE'):
        return [e for e in self.f.registry.events() if e['kind'] == kind]

    def test_c0_noop_each_tick_reads_fresh_complete_inventory_and_persists_reason(self):
        # Empty, all active, and sold-only inventories have no eligible expired.
        examples = [[], deepcopy(self.page.transfer_items[2:])]
        sold = deepcopy(self.page.transfer_items[0]); sold.update(trade_state='closed', current_bid=500, expires=-1)
        examples.append([sold])
        read_ids = []
        for rows in examples:
            self.page.transfer_items = rows
            result = self.scheduler.step()
            self.assertEqual(result['status'], 'SKIPPED')
            read_ids.append(result['read_id'])
            self.assertEqual(self.events()[-1]['reason'], 'NOOP')
            read = self.f.adapter.responses[result['read_id']]
            self.assertTrue(read['coverage']['complete'])
            self.assertEqual(read['result']['auctions'], rows)
            self.assertEqual(self.scheduler.step()['status'], 'NOT_DUE')
            self.due()
        self.assertEqual(len(set(read_ids)), 3)
        self.assertEqual([c['operation'] for c in self.page.calls], ['transfer_list']*3)
        self.assertEqual(self.page.writes, [])
        self.assertEqual(self.f.journal.db.execute('SELECT count(*) FROM relist_ticks_v1 WHERE state=?', ('FINISHED',)).fetchone(), (3,))

    def test_c0_incomplete_stale_failed_and_unowned_inventory_never_noop_or_write(self):
        changes = [
            lambda v: v['coverage'].update(complete=False, has_more=True),
            lambda v: v['freshness'].update(network_at=(self.clock.now()-timedelta(seconds=31)).isoformat()),
            lambda v: v['result'].update(success=False, error='service_failed'),
            lambda v: v['coverage']['bulk'][0].update(trade_owner=False),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.page.bad_proof = change
                self.assertEqual(self.scheduler.step()['status'], 'BLOCKED')
                self.assertNotEqual(self.events()[-1]['reason'], 'NOOP')
                self.assertEqual(self.page.writes, [])
                self.assertEqual(pending(self.f.journal, self.f.registry.scope), [])
                self.due()

    def test_c1_c2_all_manual_items_one_durable_native_write_independent_item_trade_proof(self):
        before = deepcopy(self.page.transfer_items)
        service = BulkTransfer(self.f); service.observe(service.inventory())
        for row in before[:2]:
            self.f.journal.db.execute('INSERT INTO capacity_slots_v1 VALUES(?,?,?,?,?)',
                (self.f.registry.scope, row['trade_id'], row['item']['item_id'], row['item']['definition_id'], 'OCCUPIED'))
        previous_capacity = capacity.status(self.f.journal, self.f.registry.scope, now=self.clock.now())
        result = self.scheduler.step()
        self.assertEqual(result['status'], 'CONFIRMED')
        self.assertEqual(len(self.page.writes), 1)
        c = self.page.writes[0]
        self.assertEqual(c['operation'], 'relist_all')
        self.assertTrue(JournalAuthority(self.f.journal_path).reconciled(c))
        self.assertEqual(set(c['params']['expected_item_ids']), {r['item']['item_id'] for r in before[:2]})
        self.assertFalse([e for e in self.f.registry.events() if e['kind'] == 'ENROLLMENT'])
        verified = [e for e in self.events('BULK_TRANSFER') if e['reason'] == 'VERIFIED'][0]
        self.assertNotIn(verified['read_id'], {c['id'], c['params']['before_read_id']})
        after = {r['item']['item_id']: r for r in verified['readback']['result']['auctions']}
        for a in before[:2]:
            b = after[a['item']['item_id']]
            self.assertEqual(a['item'], b['item'])
            self.assertNotEqual(a['trade_id'], b['trade_id'])
            self.assertEqual((a['starting_bid'], a['buy_now_price']), (b['starting_bid'], b['buy_now_price']))
            self.assertEqual((b['expires'], b['trade_state']), (3600, 'active'))
        self.assertEqual(self.page.transfer_items[2:], before[2:])
        self.assertEqual({c['operation'] for c in self.page.calls}, {'transfer_list', 'relist_all'})
        status = capacity.status(self.f.journal, self.f.registry.scope, now=self.clock.now())
        self.assertEqual(status['occupied'], len(before))
        self.assertEqual(status['total'], previous_capacity['total'])
        self.assertEqual(self.f.journal.db.execute('SELECT phase FROM capacity_slots_v1').fetchall(), [('OCCUPIED',)]*2)
        self.assertNotIn('duration', c['params'])  # native default must be read back

    def test_c0_noop_is_allowed_during_unresolved_acquisition_but_relist_is_blocked(self):
        self.page.transfer_items = []
        with patch.object(self.f.registry, 'current', return_value=dict(unresolved=[dict(command_id='f'*32)])):
            self.assertEqual(self.scheduler.step()['status'], 'SKIPPED')
            self.due()
            self.page.transfer_items = inventory()[2:]
            self.assertEqual(self.scheduler.step()['status'], 'BLOCKED')
        self.assertEqual(self.page.writes, [])

    def test_c2_c3_each_wrong_duration_or_changed_price_is_sticky_no_retry(self):
        for field, value in [('expires', 1800), ('expires', 7200), ('starting_bid', 1000), ('buy_now_price', 99999)]:
            with self.subTest(field=field):
                # Independent database per incompatibility; every item, including
                # the final target, must be validated, not just the first match.
                directory = self.path/(field+str(value)); directory.mkdir()
                page = BulkPage(directory, self.clock); page.transfer_items = page.transfer_items[2:]
                f = Foundation(page, context=CONTEXT, journal_path=directory/'journal.sqlite3', fixture=True,
                    now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)
                try:
                    original = deepcopy(page.transfer_items)
                    page.corrupt = lambda c: page.transfer_items[1].update(**{field: value})
                    self.assertEqual(BulkRelistScheduler(f).step()['status'], 'UNRESOLVED')
                    self.assertEqual(f.journal.db.execute('SELECT incompatible FROM bulk_writes_v1').fetchone(), (1,))
                    page.transfer_items[1].update(**{field: 3600 if field == 'expires' else original[1][field]})
                    f.close()
                    f = Foundation(page, context=CONTEXT, journal_path=directory/'journal.sqlite3', fixture=True,
                        now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)
                    self.clock.sleep(3660)
                    self.assertEqual(BulkRelistScheduler(f).step()['status'], 'RECONCILIATION_ONLY')
                    self.assertEqual(len(page.writes), 1)
                    self.assertEqual(len(pending(f.journal, f.registry.scope)), 1)
                    self.assertEqual(capacity.status(f.journal, f.registry.scope, now=self.clock.now())['occupied'], len(original))
                finally: f.close(); page.close()

    def test_c3_restart_3660_deadline_no_early_dispatch_and_no_catchup_burst(self):
        self.page.transfer_items = []
        started = self.clock.now()
        self.scheduler.step()
        due = stamp(self.f.journal.db.execute('SELECT next_due FROM relist_schedule_v1').fetchone()[0])
        self.assertEqual((due-started).total_seconds(), 3660)
        self.clock.sleep(100); self.restart()
        self.assertEqual(self.scheduler.step()['status'], 'NOT_DUE')
        self.clock.sleep((due-self.clock.now()).total_seconds()-.001)
        self.assertEqual(self.scheduler.step()['status'], 'NOT_DUE')
        self.clock.sleep(.001)
        self.assertEqual(self.scheduler.step()['status'], 'SKIPPED')
        self.clock.sleep(3660*10); self.restart()
        self.assertEqual(self.scheduler.step()['status'], 'SKIPPED')
        self.assertEqual(self.scheduler.step()['status'], 'NOT_DUE')
        self.assertEqual(len([e for e in self.events() if e['reason'] == 'TICK_STARTED']), 3)

    def test_c3_bounded_runner_and_long_tick_do_not_catch_up(self):
        self.page.transfer_items = []
        result = self.scheduler.run(ticks=2)
        self.assertEqual(result, dict(status='STOPPED', ticks=2))
        starts = [stamp(e['at']) for e in self.events() if e['reason'] == 'TICK_STARTED']
        self.assertEqual((starts[1]-starts[0]).total_seconds(), 3660)
        for ticks in (None, 0, -1, True):
            with self.assertRaises(ValueError): self.scheduler.run(ticks=ticks)
        self.due()
        with patch.object(BulkRelistScheduler, 'checkpoint', lambda s, stage: self.clock.sleep(8000) if stage=='completed' else None):
            self.scheduler.step()
        self.assertEqual(self.scheduler.step()['status'], 'SKIPPED')
        self.assertEqual(self.scheduler.step()['status'], 'NOT_DUE')

    def test_c3_crash_after_scheduling_consumes_window_and_recovers_only_by_reads(self):
        def crash(s, stage):
            if stage == 'scheduled': raise SystemExit(23)
        with patch.object(BulkRelistScheduler, 'checkpoint', crash):
            with self.assertRaises(SystemExit): self.scheduler.step()
        self.assertEqual(self.page.calls, [])
        self.restart()
        self.assertEqual(self.scheduler.step()['status'], 'INTERRUPTED_READ_ONLY')
        self.assertEqual(self.page.writes, [])
        self.assertEqual(self.scheduler.step()['status'], 'NOT_DUE')
        self.due()
        self.assertEqual(self.scheduler.step()['status'], 'CONFIRMED')

    def test_c3_ambiguous_no_effect_partial_and_lost_ack_never_blindly_retry(self):
        self.page.effect = False; self.page.timeout = True
        self.assertEqual(self.scheduler.step()['status'], 'UNRESOLVED')
        self.restart()
        for _ in range(3):
            self.due()
            self.assertEqual(self.scheduler.step()['status'], 'RECONCILIATION_ONLY')
        self.assertEqual(len(self.page.writes), 1)
        self.assertEqual(len(pending(self.f.journal, self.f.registry.scope)), 1)
        reads = [c for c in self.page.calls if c['operation'] == 'transfer_list']
        self.assertGreaterEqual(len(reads), 5)
        self.assertEqual(len({c['id'] for c in reads}), len(reads))

    def test_c3_lost_ack_with_exact_independent_readback_can_confirm(self):
        self.page.timeout = True
        self.assertEqual(self.scheduler.step()['status'], 'CONFIRMED')
        self.restart(); self.due()
        self.assertEqual(self.scheduler.step()['status'], 'SKIPPED')
        self.assertEqual(len(self.page.writes), 1)

    def test_c3_partial_effect_keeps_all_targets_reserved_without_replacement_write(self):
        self.page.partial = True; self.page.timeout = True
        self.assertEqual(self.scheduler.step()['status'], 'UNRESOLVED')
        self.restart(); self.due()
        self.assertEqual(self.scheduler.step()['status'], 'RECONCILIATION_ONLY')
        self.assertEqual(len(self.page.writes), 1)
        self.assertEqual(len(pending(self.f.journal, self.f.registry.scope)), 1)
        self.assertEqual(capacity.status(self.f.journal, self.f.registry.scope, now=self.clock.now())['occupied'], 4)

    def test_c3_schedule_and_finish_commit_failures_cannot_duplicate_native_work(self):
        original = BulkRelistScheduler.event
        def fail_start(s, reason, **data):
            original(s, reason, **data)
            if reason == 'TICK_STARTED': raise OSError('disk failure')
        with patch.object(BulkRelistScheduler, 'event', fail_start):
            with self.assertRaises(OSError): self.scheduler.step()
        self.assertEqual(self.page.calls, [])
        self.assertEqual(self.f.journal.db.execute('SELECT count(*) FROM relist_ticks_v1').fetchone(), (0,))
        self.assertEqual(self.f.journal.db.execute('SELECT count(*) FROM relist_schedule_v1').fetchone(), (0,))
        def fail_finish(s, reason, **data):
            original(s, reason, **data)
            if reason == 'TICK_FINISHED': raise OSError('finish failure')
        with patch.object(BulkRelistScheduler, 'event', fail_finish):
            with self.assertRaises(OSError): self.scheduler.step()
        self.assertEqual(len(self.page.writes), 1)
        self.assertEqual(self.f.journal.db.execute('SELECT state FROM relist_ticks_v1').fetchone(), ('RUNNING',))
        self.restart()
        self.assertEqual(self.scheduler.step()['status'], 'INTERRUPTED_READ_ONLY')
        self.assertEqual(len(self.page.writes), 1)

    def test_c3_recovery_read_failure_retains_consumed_window(self):
        def crash(s, stage):
            if stage == 'completed': raise SystemExit(23)
        with patch.object(BulkRelistScheduler, 'checkpoint', crash):
            with self.assertRaises(SystemExit): self.scheduler.step()
        self.restart(); self.page.block_readback = True
        self.assertEqual(self.scheduler.step()['status'], 'RECOVERY_BLOCKED')
        self.assertEqual(self.f.journal.db.execute('SELECT state FROM relist_ticks_v1').fetchone(), ('RUNNING',))
        self.assertEqual(len(self.page.writes), 1)
        self.page.block_readback = False
        self.assertEqual(self.scheduler.step()['status'], 'INTERRUPTED_READ_ONLY')
        self.assertEqual(self.scheduler.step()['status'], 'NOT_DUE')

    def test_c3_real_process_death_at_every_schedule_and_bulk_boundary(self):
        for stage in ('scheduled', 'intent', 'claimed', 'sent', 'ack', 'readback', 'completed'):
            with self.subTest(stage=stage):
                directory = self.path/stage; directory.mkdir()
                r = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--crash', str(directory), stage],
                                   cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(r.returncode, 23, r.stdout+r.stderr)
                meta = json.loads((directory/'clock.json').read_text())
                clock = Clock(); clock.wall = stamp(meta['wall']); clock.elapsed = meta['elapsed']+1
                page = BulkPage(directory, clock)
                page.transfer_items = json.loads((directory/'effect.json').read_text())
                f = Foundation(page, context=CONTEXT, journal_path=directory/'journal.sqlite3', fixture=True,
                    now=clock.now, clock=clock.monotonic, sleep=clock.sleep)
                try:
                    scheduler = BulkRelistScheduler(f)
                    self.assertEqual(scheduler.step()['status'], 'INTERRUPTED_READ_ONLY')
                    self.assertEqual(page.writes, [])
                    self.assertEqual(scheduler.step()['status'], 'NOT_DUE')
                    row = f.journal.db.execute('SELECT state FROM bulk_writes_v1').fetchone()
                    self.assertEqual(row, None if stage == 'scheduled' else
                        ('INTENT',) if stage == 'intent' else ('UNKNOWN',) if stage == 'claimed' else ('RECONCILED',))
                finally: f.close(); page.close()

    def test_c3_real_mailbox_urgent_bidder_preempts_relist_and_readback(self):
        box = Mailbox(self.path/'native.sqlite3'); self.addCleanup(box.close)
        broker = Broker(box, self.f, Config(native_interval_seconds=0), now=self.clock.now,
            clock=self.clock.monotonic, sleep=self.clock.sleep)
        broker.initialize()
        def pump(seconds):
            broker.run_one(); self.clock.sleep(seconds)
        proxy = QueueExecutor(box.path, 'maintenance', clock=self.clock.monotonic, sleep=pump)
        self.addCleanup(proxy.close)
        joined = Foundation(proxy, context=CONTEXT, owner=self.f.registry.owner, join_epoch=self.f.registry.epoch,
            journal_path=self.f.journal_path, fixture=True, now=self.clock.now,
            clock=self.clock.monotonic, sleep=pump)
        self.addCleanup(joined.close)
        urgent_ids = []
        def stage(s, where):
            if where in {'claimed', 'ack'}:
                urgent = joined.adapter.envelope(joined.ids(), 'watched', {})
                urgent_ids.append(urgent['id']); box.enqueue(urgent, 'bidder', now=self.clock.now())
        with patch.object(BulkTransfer, 'checkpoint', stage):
            self.assertEqual(BulkRelistScheduler(joined).step()['status'], 'CONFIRMED')
        self.assertEqual([c['operation'] for c in self.page.calls],
                         ['transfer_list', 'watched', 'relist_all', 'watched', 'transfer_list'])
        self.assertEqual([r[0] for r in box.db.execute("SELECT priority FROM work WHERE role='maintenance'")], [0, 0, 0])
        self.assertEqual([r[0] for r in box.db.execute("SELECT state FROM work")], ['DONE']*5)
        self.assertEqual(len(self.page.writes), 1)
        self.assertEqual(len(urgent_ids), 2)

    def test_c3_locked_settings_and_no_implicit_live_execution(self):
        self.assertEqual((Config().bulk_relist_interval_seconds, Config().bulk_relist_duration_seconds,
                          Config().bulk_relist_preserve_prices), (3660, 3600, True))
        for change in [dict(bulk_relist_interval_seconds=3600), dict(bulk_relist_duration_seconds=7200),
                       dict(bulk_relist_preserve_prices=False), dict(bulk_relist_interval_seconds=True)]:
            with self.assertRaises(ValueError): Config(**change)
        with patch('socket.socket', side_effect=AssertionError('live access forbidden')), \
             patch('threading.Thread.start', side_effect=AssertionError('background work forbidden')):
            self.new_scheduler()
            self.clock.sleep(10000)
            self.assertEqual(self.page.calls, [])
        result = subprocess.run([sys.executable, '-m', 'fc_access.actors_v1', 'bulk-relist', '--help'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--ticks', result.stdout)
        with patch.object(self.f.adapter, 'source', 'native'):
            with self.assertRaisesRegex(ValueError, 'prioritized_maintenance_executor_required'):
                self.new_scheduler()

    def test_c3_actual_bounded_cli_worker_uses_one_separate_broker_process(self):
        import time
        directory = self.path/'cli'; directory.mkdir()
        broker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--broker', str(directory)],
                                  cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            end = time.monotonic()+10
            while not (directory/'ready').exists() and time.monotonic() < end:
                if broker.poll() is not None: break
                time.sleep(.01)
            self.assertTrue((directory/'ready').exists(), 'fixture broker failed to initialize')
            result = subprocess.run([sys.executable, '-m', 'fc_access.actors_v1', '--state-dir', str(directory),
                'bulk-relist', '--ticks', '1'], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(status='STOPPED', ticks=1))
        finally:
            (directory/'stop').touch()
            try: out, err = broker.communicate(timeout=5)
            except subprocess.TimeoutExpired: broker.kill(); out, err = broker.communicate()
        self.assertEqual(broker.returncode, 0, out+err)
        calls = json.loads((directory/'calls.json').read_text())
        self.assertEqual([c['operation'] for c in calls], ['transfer_list', 'relist_all', 'transfer_list'])
        box = Mailbox(directory/'native.sqlite3')
        try:
            self.assertEqual(box.db.execute('SELECT DISTINCT role,priority,state FROM work').fetchall(), [('maintenance', 0, 'DONE')])
        finally: box.close()


def crash_worker(directory, stage):
    import os
    directory = Path(directory); clock = Clock(); page = BulkPage(directory, clock)
    page.transfer_items = page.transfer_items[2:]
    f = Foundation(page, context=CONTEXT, journal_path=directory/'journal.sqlite3', fixture=True,
                   now=clock.now, clock=clock.monotonic, sleep=clock.sleep)
    def checkpoint(s, where):
        if where == stage:
            (directory/'effect.json').write_text(json.dumps(page.transfer_items))
            (directory/'clock.json').write_text(json.dumps(dict(wall=clock.wall.isoformat(), elapsed=clock.elapsed)))
            os._exit(23)
    with patch.object(BulkRelistScheduler, 'checkpoint', checkpoint), patch.object(BulkTransfer, 'checkpoint', checkpoint):
        BulkRelistScheduler(f).step()
    raise AssertionError('crash seam not reached')


def broker_worker(directory):
    import time
    from actors_fixture import RealClock
    directory = Path(directory); page = BulkPage(directory, RealClock())
    page.transfer_items = page.transfer_items[2:]
    f = Foundation(page, context=CONTEXT, journal_path=directory/'journal.sqlite3', fixture=True)
    box = Mailbox(directory/'native.sqlite3')
    broker = Broker(box, f, Config(native_interval_seconds=0))
    try:
        broker.initialize(); (directory/'ready').touch()
        while not (directory/'stop').exists():
            if broker.run_one() is None: time.sleep(.005)
    finally:
        (directory/'calls.json').write_text(json.dumps(page.calls))
        box.close(); f.close(); page.close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--crash': crash_worker(*sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == '--broker': broker_worker(*sys.argv[2:])
    else: unittest.main(verbosity=2)
