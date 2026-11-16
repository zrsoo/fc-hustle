"""004-01 design contracts, negative artifact tests and isolated SQLite fixtures.

These prove the proposed storage constraints/reused mechanisms, not an implemented
controller or live EA behavior. No production DB constructors, HTTP or browser.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_00401_artifacts import (ROOT, OUT, load, validate_plan, validate_probes, validate_reuse)


class DesignArtifacts(unittest.TestCase):
    def test_policy_defaults_and_all_acceptance_mapped(self):
        validate_plan(load('plan.json'))

    def test_missing_policy_or_negative_case_is_detected(self):
        for mode in ['missing','duplicate','empty_case','unassigned','missing_acceptance']:
            value=load('plan.json')
            if mode=='missing': value['requirements'].pop()
            elif mode=='duplicate': value['requirements'][-1]=value['requirements'][0]
            elif mode=='empty_case': value['requirements'][4]['negative']=''
            elif mode=='unassigned': value['requirements'][4]['task']='future'
            else: value['acceptance_map'].pop()
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_plan(value)

    def test_wrong_strategy_spacing_and_local_slot_defaults_are_detected(self):
        for key,value in [('ea_request_spacing_seconds',0),('local_helper_network_slots',1),
                          ('entry_comparison','>='),('selection_remaining_seconds_exclusive',90),
                          ('max_initial_attempts',11),('management_target_seconds',25),
                          ('quote_cache_ttl_seconds',3600),('tax_fraction',.04),('profit_coins',0),
                          ('relist_interval_seconds',3600),('known_pipeline_capacity',51)]:
            plan=load('plan.json'); plan['defaults'][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_plan(plan)

    def test_lifecycle_is_separate_from_exactly_two_phases(self):
        for phase in ['PAUSED','DRAINING','STOPPED']:
            p=load('plan.json'); p['phases'].append(phase)
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError,'phases'): validate_plan(p)

    def test_exact_imports_and_named_shared_call_sites_exist(self):
        validate_reuse(load('reuse.json'))

    def test_missing_import_or_legacy_separation_is_detected(self):
        p=load('reuse.json'); p['imports'][0]['symbols'].append('invented_symbol')
        with self.assertRaisesRegex(ValueError,'missing_import'): validate_reuse(p)
        p=load('reuse.json'); p['shared_changes'][0]['legacy']=''
        with self.assertRaisesRegex(ValueError,'caller_compatibility'): validate_reuse(p)

    def test_future_probes_are_individually_bounded_and_unexecuted(self):
        validate_probes(load('probes.json'))

    def test_unbounded_mutating_required_probe_missing_checkpoint_or_cleanup_rejected(self):
        for mode in ['overrun','duplicate','mutation','cleanup','intent','checkpoint','boundary','executed']:
            p=load('probes.json')
            if mode=='overrun': p['windows'][0]['max_requests']=100
            elif mode=='duplicate': p['windows'][1]['id']=p['windows'][0]['id']
            elif mode=='mutation': p['windows'][0]['max_mutations']=1
            elif mode=='cleanup': p['common']['cleanup']=''
            elif mode=='intent': p['common']['pre_mutation_intent']=''
            elif mode=='checkpoint': p['common']['checkpoint_root']='reused-window'
            elif mode=='boundary': p['prohibited'].remove('soak')
            else: p['execution_state']='LIVE_PASS'
            with self.subTest(mode=mode), self.assertRaises(ValueError): validate_probes(p)


class StorageFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='00401-schema-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'fixture.sqlite3'
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.addCleanup(lambda: self.db.close())
        self.db.executescript((OUT/'storage.sql').read_text(encoding='utf-8'))
        self.db.execute("INSERT INTO c1_controllers VALUES('scope','owner',1,'ACQUIRING','STOPPED',NULL,'{}')")
        self.observe('entry')
        self.observe('proof')
        self.db.execute("INSERT INTO c1_batches VALUES('batch','scope','at',NULL,'SELECTED','entry','entry','entry','{}')")
        self.db.execute("INSERT INTO c1_quotes VALUES('quote','batch',123,'at',12000,10750,'{}')")

    def observe(self, identity):
        self.db.execute("INSERT INTO c1_observations VALUES(?,'scope','status','at','network','document','fixture',1,'{}')",(identity,))

    def candidate(self, ordinal=1):
        self.db.execute("INSERT INTO c1_candidates VALUES('batch',?,?,?,123,'quote','entry','at','deadline',2500)",
                        (ordinal,f'trade:{ordinal}',f'item:{ordinal}'))

    def command(self, identity='cmd', action='action', batch='batch', observation='entry'):
        self.db.execute("INSERT INTO c1_commands VALUES(?,'scope',?,'bid','trade:1','item:1',123,2500,?,?,1,'at','deadline',NULL,'INTENDED')",
                        (identity,batch,action,observation))

    def claim(self):
        self.db.execute('BEGIN IMMEDIATE')
        self.db.execute("UPDATE c1_commands SET state='CLAIMED',claimed_at='at' WHERE id='cmd' AND state='INTENDED'")
        self.db.execute("INSERT INTO c1_tombstones VALUES('action','cmd','at','DISPATCH_CLAIM')")
        self.db.execute('COMMIT')

    def test_all_durable_entities_and_foreign_keys(self):
        tables={r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'c1_controllers','c1_batches','c1_candidates','c1_quotes','c1_membership','c1_deadlines',
                         'c1_commands','c1_results','c1_tombstones','c1_transitions','c1_resales','c1_probe_windows'}<=tables)
        self.assertEqual(self.db.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO c1_results VALUES(1,'missing-command','at','ACCEPTED',NULL,'{}')")

    def test_exact_phases_owner_uniqueness_and_lifecycle_controls(self):
        for phase in ['ACQUIRING','MANAGING']:
            for lifecycle in ['RUNNING','PAUSED','STOPPED','HALTED']:
                self.db.execute('UPDATE c1_controllers SET phase=?,lifecycle=?',(phase,lifecycle))
        for phase in ['DRAINING','STOPPED','PAUSED']:
            with self.subTest(phase=phase),self.assertRaises(sqlite3.IntegrityError):
                self.db.execute('UPDATE c1_controllers SET phase=?',(phase,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO c1_controllers VALUES('scope','competitor',2,'ACQUIRING','RUNNING',NULL,'{}')")

    def test_ten_distinct_selected_candidates_and_confirmed_members(self):
        for n in range(1,11):
            self.candidate(n)
            self.db.execute("INSERT INTO c1_membership VALUES('batch',?,'scope',?,'proof','outbid',NULL,'deadline')",(f'trade:{n}',n))
        with self.assertRaises(sqlite3.IntegrityError): self.candidate(11)
        with self.assertRaises(sqlite3.IntegrityError): self.candidate(1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM c1_membership').fetchone()[0],10)

    def test_unconfirmed_membership_or_missing_proof_not_storable(self):
        self.candidate()
        for state, proof in [('ACKNOWLEDGED','proof'),('highest','missing'),('UNKNOWN','proof')]:
            with self.subTest(state=state,proof=proof),self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("INSERT INTO c1_membership VALUES('batch','trade:1','scope',1,?,?,NULL,'deadline')",(proof,state))

    def test_stored_quote_and_intent_cannot_be_repriced_or_retargeted(self):
        self.command()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('UPDATE c1_quotes SET cap=11000')
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('UPDATE c1_commands SET amount=3000')
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE c1_commands SET item_id='other'")

    def test_claim_and_tombstone_survive_interruption_without_replay(self):
        self.command(); self.claim()
        self.db.close(); self.db=sqlite3.connect(self.path,isolation_level=None)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.assertEqual(self.db.execute('SELECT state FROM c1_commands').fetchone()[0],'CLAIMED')
        with self.assertRaisesRegex(sqlite3.IntegrityError,'consumed_command'):
            self.db.execute("UPDATE c1_commands SET state='INTENDED'")
        self.db.execute("INSERT INTO c1_batches VALUES('next','scope','at',NULL,'SELECTED',NULL,NULL,NULL,'{}')")
        with self.assertRaises(sqlite3.IntegrityError): self.command('disguised','action','next')
        # New independent observation/decision may be a distinct later action.
        self.observe('later'); self.command('new','new-observation-decision','next','later')
        self.assertEqual(self.db.execute('SELECT count(*) FROM c1_commands').fetchone()[0],2)

    def test_tombstones_results_and_transitions_are_append_only(self):
        self.command(); self.claim()
        self.db.execute("INSERT INTO c1_results VALUES(1,'cmd','at','UNCONFIRMED',NULL,'{}')")
        self.db.execute("INSERT INTO c1_transitions VALUES(1,'scope','batch','at','ACQUIRING','MANAGING','confirmed')")
        for table in ['c1_tombstones','c1_results','c1_transitions','c1_observations']:
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError): self.db.execute(f'DELETE FROM {table}')
        self.assertEqual(self.db.execute('SELECT outcome FROM c1_results').fetchone()[0],'UNCONFIRMED')

    def test_probe_budget_is_bounded_consumed_and_cannot_reset(self):
        self.db.execute("INSERT INTO c1_probe_windows VALUES('window','scope','question','expiry',3,1,0,0,'PREPARED',NULL)")
        self.db.execute('UPDATE c1_probe_windows SET consumed_requests=3,consumed_mutations=1')
        for sql in ["UPDATE c1_probe_windows SET consumed_requests=4", "UPDATE c1_probe_windows SET consumed_mutations=2",
                    "UPDATE c1_probe_windows SET consumed_requests=0", "UPDATE c1_probe_windows SET max_requests=10",
                    "DELETE FROM c1_probe_windows"]:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)

    def test_short_committed_claim_allows_another_writer_while_network_is_awaited(self):
        self.command(); self.claim()
        async def scenario():
            waiting=asyncio.Event(); release=asyncio.Event()
            async def native_fixture():
                self.assertFalse(self.db.in_transaction)
                waiting.set(); await release.wait()
            task=asyncio.create_task(native_fixture()); await waiting.wait()
            other=sqlite3.connect(self.path,isolation_level=None,timeout=.1)
            try:
                other.execute('BEGIN IMMEDIATE')
                other.execute("INSERT INTO c1_deadlines VALUES('scope','management','batch','next',NULL)")
                other.execute('COMMIT')
            finally: other.close(); release.set()
            await task
        asyncio.run(scenario())
        self.assertEqual(self.db.execute('SELECT count(*) FROM c1_deadlines').fetchone()[0],1)


class ReusedMechanisms(unittest.TestCase):
    def test_actual_scheduled_executor_helpers_consume_no_ea_slot(self):
        from foundation_fixture import create
        for interval in [2,3]:
            with self.subTest(interval=interval),tempfile.TemporaryDirectory(prefix='00401-pacing-') as tmp:
                with patch('socket.socket',side_effect=AssertionError('offline fixtures must not use sockets')):
                    f,page,clock=create(tmp,interval=interval)
                    try:
                        f.read('balance')
                        last=f.executor.scheduler.last_native
                        f.read('price_helpers',{'version':1,'probes':[]})
                        f.read('status_support')
                        self.assertEqual(f.executor.scheduler.last_native,last)
                        self.assertLess(clock.elapsed,interval)
                        f.read('watched')
                        self.assertGreaterEqual(f.executor.scheduler.last_native-last,interval)
                        self.assertLess(f.executor.scheduler.last_native-last,interval+.01)
                        self.assertEqual([m['request_count'] for m in f.executor.local_metrics],[0,0])
                        self.assertEqual([c['operation'] for c in page.calls],['balance','price_helpers','status_support','watched'])
                        self.assertEqual(page.real_account_writes,0)
                    finally: f.close(); page.close()

    def test_canonical_process_lock_excludes_competitor_and_releases(self):
        from fc_access.actors_v1.locking import process_lock
        script="from fc_access.actors_v1.locking import process_lock\nimport sys\ntry:\n with process_lock(sys.argv[1]): pass\nexcept ValueError: sys.exit(9)\n"
        with tempfile.TemporaryDirectory(prefix='00401-lock-') as tmp:
            path=Path(tmp)/'fixture-owner.lock'
            with process_lock(path):
                result=subprocess.run([sys.executable,'-c',script,str(path)],cwd=ROOT,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,9,result.stderr)
            result=subprocess.run([sys.executable,'-c',script,str(path)],cwd=ROOT,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':
    unittest.main(verbosity=2)
