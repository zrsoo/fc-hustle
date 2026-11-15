"""Behavioral rejection tests for baseline reconciliation and artifact contracts."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from baseline_00301 import ROOT, OUT, assess_reads, commitments, mutation_gate
import check_00301_baseline as checker
from check_00301_baseline import historical_responses, backup, database
from fc_access.actors_v1.final_run import load_evidence
from fc_access.production_v1.store import Store


class ReconciliationBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_evidence(OUT/'native-opening.jsonl')
        cls.context = next(r['health']['peer']['context'] for r in cls.rows if r['kind'] == 'READ_ONLY_SERVICE')
        cls.history = historical_responses()

    def assess(self, rows=None, context=None, history=None):
        return assess_reads(rows if rows is not None else self.rows,
                            context if context is not None else self.context,
                            history if history is not None else self.history)

    def test_real_native_capture_and_independent_history_establish_exact_mappings(self):
        r = self.assess()
        self.assertEqual(r['credits'], 62827)
        self.assertEqual(len(r['inventory']), 5)
        self.assertEqual(len(r['watched']), 2)
        self.assertFalse(r['watched_complete'])
        self.assertEqual(r['native_requests'], 4)
        self.assertFalse(r['mutations_enabled'])

    def test_unattached_write_enabled_and_wrong_persona_fail_closed(self):
        for key, value in [('attached', False), ('mutations_enabled', True), ('service', 'other')]:
            rows = deepcopy(self.rows)
            next(r for r in rows if r['kind'] == 'READ_ONLY_SERVICE')['health'][key] = value
            with self.assertRaises(ValueError):
                self.assess(rows)
        context = dict(self.context, persona='0'*32)
        with self.assertRaisesRegex(ValueError, 'wrong_account'):
            self.assess(context=context)

    def test_missing_duplicate_mutation_and_epoch_change_reject(self):
        rows = deepcopy(self.rows)
        rows = [r for r in rows if not (r['kind'] == 'NATIVE_READ' and r['command']['operation'] == 'balance')]
        with self.assertRaises(ValueError): self.assess(rows)
        for mode in ['duplicate', 'mutation', 'epoch']:
            rows = deepcopy(self.rows)
            intents = [r for r in rows if r['kind'] == 'READ_INTENT']
            captured = [r for r in rows if r['kind'] == 'NATIVE_READ']
            if mode == 'duplicate':
                intents[1]['command']['id'] = intents[0]['command']['id']
            elif mode == 'mutation':
                intents[0]['command']['operation'] = 'clear_sold'
            else:
                captured[0]['command']['fences']['epoch'] += 1
            with self.assertRaises(ValueError): self.assess(rows)

    def test_cached_stale_unauthenticated_and_incomplete_reads_reject(self):
        for mode in ['cached', 'stale', 'unauthenticated', 'incomplete']:
            rows = deepcopy(self.rows)
            r = next(r for r in rows if r['kind'] == 'NATIVE_READ' and r['command']['operation'] == 'transfer_list')
            if mode == 'cached': r['response']['freshness']['request_count'] = 0
            elif mode == 'stale': r['at'] = '2026-11-16T00:00:00+00:00'
            elif mode == 'unauthenticated': r['response']['result']['network'][0]['session_header_present'] = False
            else: r['response']['coverage']['complete'] = False
            with self.assertRaises(ValueError): self.assess(rows)

    def test_arbitrary_operator_labels_and_wrong_physical_identity_are_insufficient(self):
        with self.assertRaisesRegex(ValueError, 'continuity_unproven'):
            self.assess(history=[])
        rows = deepcopy(self.rows)
        r = next(r for r in rows if r['kind'] == 'NATIVE_READ' and r['command']['operation'] == 'watched')
        r['response']['result']['auctions'][0]['item']['definition_id'] += 1
        with self.assertRaisesRegex(ValueError, 'watched_mapping'):
            self.assess(rows)

    def test_absent_ghost_reservation_never_becomes_loss_or_write_permission(self):
        native = self.assess()
        durable = commitments(backup()/'0-foundation.sqlite3', self.context)
        gate = mutation_gate(native, durable)
        self.assertEqual(durable['reserved_coins'], 700)
        self.assertEqual(len(gate['unmapped_commitments']), 1)
        self.assertTrue(gate['independent_reconciliation_required'])
        self.assertFalse(gate['absent_watched_is_terminal_proof'])
        self.assertFalse(gate['allowed'])
        # Even an otherwise fully reconciled baseline grants no dispatch authority.
        durable['unresolved'] = []; durable['pending_mutation_intents'] = []
        self.assertFalse(mutation_gate(native, durable)['allowed'])

    def test_real_production_transport_rejects_mutation_without_journal_authority(self):
        # Use a retained valid historical command against a temporary store only.
        with database(backup()/'3-production-readonly-after.sqlite3') as old:
            commands = [json.loads(b) for (b,) in old.execute('SELECT body FROM commands')]
        c = next(c for c in commands if c['operation'] == 'bid')
        with tempfile.TemporaryDirectory() as d:
            s = Store(str(Path(d)/'transport.sqlite3'))
            try:
                owner = dict(context=c['context'], owner=c['fences']['owner'], epoch=c['fences']['epoch'])
                s.activate(owner)
                c['fences']['host_epoch'] = s.host_epoch
                peer = {k: c[k] for k in ('context', 'fences')}
                with self.assertRaisesRegex(ValueError, 'mutation_requires_durable_intent'):
                    s.enqueue(c, peer)
                self.assertEqual(s.db.execute('SELECT count(*) FROM commands').fetchone()[0], 0)
            finally:
                s.db.close()

    def test_all_criteria_artifacts_are_independently_checked(self):
        # Offline subprocess: no native operation, actor launch or objective recheck.
        r = subprocess.run([sys.executable, str(ROOT/'tests/check_00301_baseline.py')],
                           cwd=ROOT, capture_output=True, text=True, timeout=100)
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual([x['criterion'] for x in result['results']], list(range(6)))
        self.assertTrue(all(x['status'] == 'PASS' for x in result['results']))


class ConsumedStatePreservation(unittest.TestCase):
    def setUp(self):
        self.old, self.new = [sqlite3.connect(':memory:') for _ in range(2)]
        for db in (self.old, self.new):
            self.addCleanup(db.close)
            db.executescript('''
              CREATE TABLE sessions(scope TEXT PRIMARY KEY,owner TEXT,epoch INTEGER);
              INSERT INTO sessions VALUES('scope','old',1);
              CREATE TABLE events(seq INTEGER PRIMARY KEY,data TEXT);
              INSERT INTO events VALUES(1,'original consumed evidence');
              CREATE TABLE commands(id TEXT PRIMARY KEY,state TEXT,amount INTEGER);
              INSERT INTO commands VALUES('consumed','RECONCILED',700);
              CREATE TABLE relist_schedule_v1(scope TEXT,next_due REAL);
              INSERT INTO relist_schedule_v1 VALUES('scope',3660);
            ''')

    def test_later_fenced_session_and_append_only_work_preserve_completed_baseline(self):
        self.new.executescript("UPDATE sessions SET owner='next',epoch=2; INSERT INTO events VALUES(2,'new work');")
        checker.preserved_consumed_state(self.new,self.old)

    def test_deleted_or_rewritten_historical_event_is_rejected(self):
        self.new.execute("UPDATE events SET data='rewritten'")
        with self.assertRaisesRegex(ValueError,'historical_actor_state'): checker.preserved_consumed_state(self.new,self.old)

    def test_consumed_command_reset_is_rejected(self):
        self.new.execute("UPDATE commands SET state='QUEUED'")
        with self.assertRaisesRegex(ValueError,'historical_actor_state'): checker.preserved_consumed_state(self.new,self.old)

    def test_owner_change_without_new_epoch_is_rejected(self):
        self.new.execute("UPDATE sessions SET owner='next'")
        with self.assertRaisesRegex(ValueError,'owner_fence_regressed'): checker.preserved_consumed_state(self.new,self.old)

    def test_consumed_maintenance_schedule_cannot_be_reset(self):
        self.new.execute('UPDATE relist_schedule_v1 SET next_due=0')
        with self.assertRaisesRegex(ValueError,'consumed_relist_schedule_reset'): checker.preserved_consumed_state(self.new,self.old)


class ArtifactRejections(unittest.TestCase):
    def test_review_scope_survives_later_production_commits(self):
        calls = []
        def git(*args):
            calls.append(args)
            if args[0] == 'diff':
                # HEAD includes production changes; the historical review does not.
                return ('fc_access/continuous_v1/runtime.py' if args[-1] == 'HEAD' else
                        'docs/research/003/003-01/REPORT.md\ntests/check_00301_baseline.py')
            return ''
        with patch.object(checker, 'git', side_effect=git): checker.reviewed_change_scope()
        self.assertIn(('diff','--name-only',checker.BASELINE,checker.BASELINE_REVIEW),calls)
        self.assertIn(('merge-base','--is-ancestor',checker.BASELINE_REVIEW,'HEAD'),calls)

    def test_unrelated_changes_inside_original_review_are_still_rejected(self):
        def git(*args):
            return 'fc_access/production_v1/foundation.py' if args[0] == 'diff' else ''
        with patch.object(checker,'git',side_effect=git):
            with self.assertRaisesRegex(ValueError,'unrelated_baseline_changes'): checker.reviewed_change_scope()

    def test_missing_or_rewritten_review_ancestry_is_rejected(self):
        for broken in ((checker.BASELINE,checker.BASELINE_REVIEW),(checker.BASELINE_REVIEW,'HEAD')):
            def git(*args):
                if args[0] == 'merge-base' and args[-2:] == broken:
                    raise ValueError('git_failed_merge-base')
                return ''
            with self.subTest(boundary=broken), patch.object(checker,'git',side_effect=git):
                with self.assertRaisesRegex(ValueError,'git_failed_merge-base'): checker.reviewed_change_scope()

    def test_actual_committed_review_scope_is_valid_after_00302_publication(self):
        checker.reviewed_change_scope()

    def altered(self, name, change):
        original = checker.load
        def load(path):
            value = original(path)
            if path == name:
                change(value)
            return value
        return patch.object(checker, 'load', side_effect=load)

    def test_criterion0_missing_instruction_receipt_is_rejected(self):
        with self.altered('provenance.json', lambda v: v['context_reads'].pop(0)):
            with self.assertRaisesRegex(ValueError, 'required_context_missing'):
                checker.criterion_0()

    def test_criterion1_missing_database_backup_is_rejected(self):
        actual = backup()
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)
            for name in ['repository.bundle', 'working-tree.patch', 'index.patch', 'status.txt', 'untracked.zip']:
                shutil.copyfile(actual/name, target/name)
            m = json.loads((actual/'manifest.json').read_text())
            m['databases'].pop()
            (target/'manifest.json').write_text(json.dumps(m))
            with patch.object(checker, 'backup', return_value=target):
                with self.assertRaisesRegex(ValueError, 'five_backups_required'):
                    checker.criterion_1()

    def test_criterion2_competing_owner_and_unawaited_stop_are_rejected(self):
        with self.altered('process-ownership.json', lambda v: v['after_scan'].append(
                dict(pid=999999, parent=0, role='actor-stack'))):
            with self.assertRaisesRegex(ValueError, 'actor_in_process_scan'):
                checker.criterion_2()
        with self.altered('process-ownership.json', lambda v: v.update(
                transition_order=['STOP_12008', 'START_READ_ONLY_SERVICE', 'AWAIT_EXIT_12008'])):
            with self.assertRaisesRegex(ValueError, 'ownership_overlap'):
                checker.criterion_2()

    def test_criterion3_failed_regressions_cannot_be_claimed_as_reviewed_baseline(self):
        # Keep real local Git ancestry and simulate only an unavailable remote.
        original_git = checker.git
        def local_git(*args):
            if args[0] == 'ls-remote':
                return checker.BASELINE + '\trefs/heads/main'
            return original_git(*args)
        with patch.object(checker, 'git', side_effect=local_git):
            with self.altered('python-baseline.json', lambda v: v.update(exit_code=1)):
                with self.assertRaisesRegex(ValueError, 'python_baseline_failed'):
                    checker.criterion_3()

    def test_criterion5_objective_unblock_or_recheck_is_rejected(self):
        actual_backup = backup()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'.orchestrator').mkdir()
            c = sqlite3.connect(root/'.orchestrator/state.db')
            c.executescript('CREATE TABLE objective(id,state); CREATE TABLE task(key,objective_id,id,state,attempts,recheck);')
            before = json.loads((backup()/'objective002-before.json').read_text())
            c.execute('INSERT INTO objective VALUES(?,?)', ('obj-29bea3b74eb3', 'RUNNING'))
            t = before['task']
            c.execute('INSERT INTO task VALUES(?,?,?,?,?,?)',
                      (t[0], 'obj-29bea3b74eb3', '002-12', t[1], t[2], t[3]))
            c.commit(); c.close()
            with patch.object(checker, 'ROOT', root):
                with patch.object(checker, 'backup', return_value=actual_backup):
                    with self.assertRaisesRegex(ValueError, 'objective002_changed_or_rechecked'):
                        checker.criterion_5()


if __name__ == '__main__':
    unittest.main(verbosity=2)
