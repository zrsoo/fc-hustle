"""Offline admission withdrawal: real SQLite replay/fencing; no EA dispatch.

The tracked read-only gate is the certificate. Temporary modeled stores are
explicit offline fixtures, never written back into captured evidence.
"""
from copy import deepcopy
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.actors_v1.native import Mailbox
from fc_access.bidding_v1.core import AuctionQueue
from fc_access.bidding_v1.journal import Journal
from fc_access.production_v1.foundation import Registry
from fc_access.production_v1.store import Store
from fc_access.production_v1 import bulk, resale
from fc_access.continuous_v1 import withdrawal as w

GATE = ROOT/'docs/research/002/002-03/attempts/20261114-adapter-repair-gate-06/gate.json'


class Withdrawal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.gate = w.certificate(GATE)
        g = self.gate
        self.trade = g['decision']['identity']['trade_id']
        self.item = g['decision']['identity']['item_id']
        self.jpath, self.npath, self.tpath = [self.path/name for name in ('journal.db','native.db','transport.db')]
        self.j = Journal(self.jpath, now=lambda: datetime.fromisoformat(g['final_decision_at']))
        self.addCleanup(self.j.close)
        self.r = Registry(self.j, g['context'], g['decision']['owner'], after_epoch=g['decision']['epoch']-1)
        self.scope = self.r.scope
        bulk.install(self.j); resale.install(self.j)
        self.j.record(self.scope, 'ENROLLED', dict(amount=g['decision']['amount'], item_id=self.item,
            definition_id=g['decision']['identity']['definition_id'], status_read_id=g['final_status_read_id'],
            balance_read_id=g['final_balance_read_id']), trade_id=self.trade)
        self.r._append(g['decision'], self.trade)
        box = Mailbox(self.npath); box.close()
        store = Store(self.tpath)
        for e in g['operations']:
            store.db.execute('INSERT INTO commands VALUES(?,?,?,?)',
                (e['command']['id'], json.dumps(e['command']), 'ACKNOWLEDGED', json.dumps(e['response'])))
        store.db.close()
        self.args = dict(journal_path=self.jpath, gate_path=GATE, native_path=self.npath,
                         transport_path=self.tpath, state_dir=self.path, authority='offline fixture authorization')

    def queue(self, scope=None):
        return AuctionQueue(journal=self.j, scope=scope or self.scope)

    def call(self):
        return w.withdraw(**self.args)

    def assert_retained(self):
        self.assertIn(self.trade, self.queue().entries)
        self.assertEqual(self.queue().reservations[self.trade][0], 700)
        self.assertEqual(self.j.db.execute('SELECT phase FROM capacity_slots_v1 WHERE trade_id=?',
                                         (self.trade,)).fetchone(), ('UNRESOLVED',))
        self.assertEqual(len(self.j.trace(scope=self.scope, trade_id=self.trade)), 1)
        self.r.check()  # Failed repair must not change ownership.

    def mutation(self, operation='bid', same_item=True):
        command = deepcopy(self.gate['operations'][0]['command'])
        command.update(id='a'*32, operation=operation, params=dict(trade_id='trade:'+'b'*24,
            item_id=self.item if same_item else 'item:'+'c'*24, definition_id=278046, amount=700,
            minimum=700, cap=4100, deadline=self.gate['final_decision_at'],
            status_read_id='d'*32, balance_read_id='e'*32))
        if operation == 'relist_all':
            command['params'] = dict(before_read_id='d'*32, expected_item_ids=['item:'+'c'*24],
                expected_inventory_ids=['item:'+'c'*24], expected_sold_count=0, expected_expired_count=1)
        return command

    def insert_native(self, state='UNKNOWN', operation='bid', same_item=True):
        command = self.mutation(operation, same_item)
        with closing(sqlite3.connect(self.npath, isolation_level=None)) as db:
            db.execute('INSERT INTO work(id,role,priority,enqueued,deadline,state,command) VALUES(?,?,?,?,?,?,?)',
                       (command['id'], 'bidder', 90, 'offline', 'offline', state, json.dumps(command)))

    def test_withdraw_replay_idempotency_and_no_fabricated_terminal_state(self):
        before = self.j.trace()
        result = self.call()
        self.assertEqual(result['outcome'], 'WITHDRAWN')
        self.assertNotIn(self.trade, self.queue().entries)
        self.assertFalse(self.queue().reservations)
        self.assertFalse(self.queue().pending_resale)
        self.assertIn(self.gate['final_balance_read_id'], self.queue().invalid_balances)
        self.assertEqual(self.j.trace()[:len(before)], before)
        self.assertEqual([e['reason'] for e in self.j.trace(scope=self.scope, trade_id=self.trade)],
                         ['ENROLLED', 'ADMISSION_WITHDRAWN'])
        self.assertEqual(self.j.db.execute('SELECT phase FROM capacity_slots_v1').fetchone(), ('WITHDRAWN',))
        with self.assertRaisesRegex(ValueError, 'stale_owner'): self.r.check()
        new_owner, epoch = self.j.db.execute('SELECT owner,epoch FROM sessions').fetchone()
        reg = Registry(self.j, self.gate['context'], new_owner, join_epoch=epoch)
        view = reg.current()
        self.assertEqual(view['auctions'][self.trade]['action'], 'WITHDRAWN')
        self.assertEqual(view['auctions'][self.trade]['state'], 'UNKNOWN')
        self.assertEqual(view['capacity']['unresolved'], 0)
        events = self.j.trace()
        self.assertEqual(self.call()['outcome'], 'ALREADY_WITHDRAWN')
        self.assertEqual(self.j.trace(), events)
        reopened = Journal(self.jpath)
        try: self.assertNotIn(self.trade, AuctionQueue(journal=reopened, scope=self.scope).identities)
        finally: reopened.close()
        for sql in ('UPDATE admission_withdrawals_v1 SET proof=proof', 'DELETE FROM admission_withdrawals_v1'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'append_only'): self.j.db.execute(sql)

    def test_all_journal_command_states_veto_even_other_trade_same_item(self):
        for state in ('UNKNOWN','PENDING','RECONCILED','NOT_DISPATCHED'):
            with self.subTest(state=state):
                self.j.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('a'*32, 'other_scope', 'owner', 1, 'trade:other', self.item, 278046, 700, state,
                     'offline', 'status', 'balance', 'offline'))
                with self.assertRaisesRegex(ValueError, 'durable_bid_command'): self.call()
                self.assert_retained()
                self.j.db.execute('DELETE FROM commands')  # Fixture only.

    def test_every_mailbox_state_vetoes_a_matching_mutation(self):
        for state in ('QUEUED','STARTED','UNKNOWN','DONE','NOT_DISPATCHED'):
            with self.subTest(state=state):
                self.insert_native(state)
                with self.assertRaisesRegex(ValueError, 'native_mutation'): self.call()
                self.assert_retained()
                with closing(sqlite3.connect(self.npath, isolation_level=None)) as db: db.execute('DELETE FROM work')

    def test_transport_mutation_vetoes_even_without_journal_intent(self):
        c = self.mutation()
        with closing(sqlite3.connect(self.tpath, isolation_level=None)) as db:
            db.execute('INSERT INTO commands VALUES(?,?,?,NULL)', (c['id'], json.dumps(c), 'RECONCILED'))
        with self.assertRaisesRegex(ValueError, 'native_mutation'): self.call()
        self.assert_retained()

    def test_ambiguous_account_wide_operation_vetoes(self):
        self.insert_native(operation='relist_all', same_item=False)
        with self.assertRaisesRegex(ValueError, 'ambiguous_account_wide'): self.call()
        self.assert_retained()

    def test_unrelated_bulk_done_requires_actual_reconciled_journal_and_transport(self):
        self.insert_native(state='DONE', operation='relist_all', same_item=False)
        c = self.mutation('relist_all', False)
        with self.assertRaisesRegex(ValueError, 'ambiguous_account_wide'): self.call()
        self.j.db.execute('INSERT INTO bulk_writes_v1 VALUES(?,?,?,?,?,?,?,?)',
            (c['id'], self.scope, json.dumps(c), '{}', 'RECONCILED', 'offline', 'offline', 0))
        with self.assertRaisesRegex(ValueError, 'ambiguous_account_wide'): self.call()
        with closing(sqlite3.connect(self.tpath, isolation_level=None)) as db:
            db.execute('INSERT INTO commands VALUES(?,?,?,NULL)', (c['id'], json.dumps(c), 'RECONCILED'))
        self.assertEqual(self.call()['outcome'], 'WITHDRAWN')

    def test_missing_gate_transport_record_vetoes(self):
        with closing(sqlite3.connect(self.tpath, isolation_level=None)) as db:
            db.execute('DELETE FROM commands WHERE id=?', (self.gate['operations'][0]['command']['id'],))
        with self.assertRaisesRegex(ValueError, 'gate_transport_evidence'): self.call()
        self.assert_retained()

    def test_orphan_native_event_vetoes_incomplete_history(self):
        with closing(sqlite3.connect(self.npath, isolation_level=None)) as db:
            db.execute('INSERT INTO native_events(id,at,body) VALUES(?,?,?)', ('missing','offline','{}'))
        with self.assertRaisesRegex(ValueError, 'orphan_native'): self.call()
        self.assert_retained()

    def test_missing_or_changed_certificate_cannot_release_reservation(self):
        for field, value in (('status','FAILURE'), ('account_mutations',1)):
            with self.subTest(field=field):
                gate = deepcopy(self.gate); gate[field] = value
                p = self.path/'bad-gate.json'; p.write_text(json.dumps(gate), encoding='utf-8')
                with self.assertRaises(ValueError): w.withdraw(**dict(self.args, gate_path=p))
                self.assert_retained()

    def test_actual_trading_provenance_vetoes(self):
        self.r._append(dict(kind='ENROLLMENT', reason='ENROLLED'), self.trade)
        with self.assertRaisesRegex(ValueError, 'trading_provenance'): self.call()
        self.assert_retained()

    def test_duplicate_gate_decision_vetoes(self):
        self.r._append(self.gate['decision'], self.trade)
        with self.assertRaisesRegex(ValueError, 'decision_not_unique'): self.call()
        self.assert_retained()

    def test_other_journal_lifecycle_event_vetoes(self):
        self.j.record(self.scope, 'PENDING', trade_id=self.trade)
        with self.assertRaisesRegex(ValueError, 'provenance_mismatch'): self.call()
        self.assertIn(self.trade, self.queue().entries)

    def test_capacity_must_still_be_unresolved(self):
        self.j.db.execute("UPDATE capacity_slots_v1 SET phase='PENDING_RESALE'")
        with self.assertRaisesRegex(ValueError, 'capacity_conflict'): self.call()
        self.assertIn(self.trade, self.queue().pending_resale)

    def test_context_mismatch_vetoes(self):
        self.j.db.execute("UPDATE registry_context_v1 SET context='{}'")
        with self.assertRaisesRegex(ValueError, 'context_mismatch'): self.call()
        self.assert_retained()

    def test_failed_write_rolls_back_proof_owner_event_and_slot(self):
        original = Journal._event
        def fail(j, scope, reason, *args):
            if reason == 'ADMISSION_WITHDRAWN': raise RuntimeError('offline crash injection')
            return original(j, scope, reason, *args)
        with patch.object(Journal, '_event', fail):
            with self.assertRaisesRegex(RuntimeError, 'crash injection'): self.call()
        self.assert_retained()
        self.assertFalse(self.j.db.execute("SELECT 1 FROM sqlite_master WHERE name='admission_withdrawals_v1'").fetchone())

    def test_running_account_owner_prevents_repair(self):
        from fc_access.continuous_v1.runtime import account_locks
        with process_lock(account_locks(self.gate['context'])[0]):
            with self.assertRaisesRegex(ValueError, 'process_already_running'): self.call()
        self.assert_retained()

    def test_attached_database_lock_prevents_concurrent_mutation_enqueue(self):
        original = w._verify
        def verify(journal, gate):
            for path in (self.npath, self.tpath):
                with closing(sqlite3.connect(path, timeout=0)) as other:
                    with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                        other.execute('BEGIN IMMEDIATE')
            return original(journal, gate)
        with patch.object(w, '_verify', verify): self.call()

    def test_scope_isolation_and_sticky_draining_preserved(self):
        self.j.record(self.scope, 'DRAINING')
        self.j.record('c'*32, 'ENROLLED', dict(amount=900, item_id='item:'+'d'*24, definition_id=1,
            status_read_id='e'*32, balance_read_id='f'*32), trade_id='trade:'+'c'*24)
        self.call()
        self.assertTrue(self.queue().draining)
        self.assertEqual(self.queue('c'*32).reservations['trade:'+'c'*24][0], 900)

    def test_uncertified_unmapped_enrollment_remains_reserved(self):
        # Startup continues to gate all generic orphans. No blanket migration.
        self.args['gate_path'] = self.path/'missing.json'
        with self.assertRaises(FileNotFoundError): self.call()
        self.assert_retained()

    def test_capacity_migration_replays_withdrawal_without_reopening(self):
        self.call()
        from fc_access.bidding_v1.capacity import install
        self.j.db.execute('DELETE FROM capacity_migration_v1')  # Offline migration fixture.
        install(self.j)
        self.assertNotIn(self.trade, self.queue().entries)
        self.assertEqual(self.j.db.execute('SELECT phase FROM capacity_slots_v1').fetchone(), ('WITHDRAWN',))

    def test_terminal_record_does_not_substitute_for_withdrawal(self):
        self.j.record(self.scope, 'LOST_VERIFIED', trade_id=self.trade)
        with self.assertRaisesRegex(ValueError, 'provenance_mismatch'): self.call()
        self.assertFalse(self.j.db.execute("SELECT 1 FROM sqlite_master WHERE name='admission_withdrawals_v1'").fetchone())

    def test_wrong_enrollment_read_id_fails(self):
        # Alter the modeled enrollment via a second event, never captured evidence.
        self.j.record(self.scope, 'ENROLLED', dict(amount=700, item_id=self.item,
            definition_id=278046, status_read_id='f'*32, balance_read_id=self.gate['final_balance_read_id']),
            trade_id=self.trade)
        with self.assertRaisesRegex(ValueError, 'provenance_mismatch'): self.call()

    def test_resale_original_trade_reference_vetoes(self):
        self.j.db.execute('INSERT INTO resale_writes_v1 VALUES(?,?,?,?,?,?,?,?,?)',
            ('a'*32, self.scope, 'trade:'+'b'*24, '{}', 'RECONCILED', 'offline', self.trade, None, None))
        with self.assertRaisesRegex(ValueError, 'other_write_intent'): self.call()
        self.assert_retained()

    def test_independent_assessor_verifies_real_replay_and_rejects_unreleased_slot(self):
        from check_00304_withdrawal import assess
        def snapshot(path):
            with closing(sqlite3.connect(path)) as capture: self.j.db.backup(capture)
        before, after = self.path/'before.db', self.path/'after.db'
        snapshot(before); self.call(); snapshot(after)
        self.assertEqual(assess(before, after, GATE)['status'], 'PASS')
        with closing(sqlite3.connect(after, isolation_level=None)) as db:
            db.execute("UPDATE capacity_slots_v1 SET phase='UNRESOLVED'")
        with self.assertRaisesRegex(ValueError, 'capacity_not_exactly_one'): assess(before, after, GATE)


if __name__ == '__main__': unittest.main()
