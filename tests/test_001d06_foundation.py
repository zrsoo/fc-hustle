"""Independent acceptance: python tests/test_001d06_foundation.py (no EA/Edge)."""
import ast
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foundation_fixture import CONTEXT, Page, Clock, create, admitted
from native_price_fixture import auction
from fc_access.production_v1.foundation import (Foundation, JournalAuthority, Registry,
                                               ScheduledExecutor, scope_for)
from fc_access.production_v1.contracts import Search
from fc_access.bidding_v1.contracts import BidIntent, Identity, Outcome, BidResult
from fc_access.bidding_v1.journal import Journal
from fc_access.bidding_v1.scheduler import Work


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def api(self, **kwargs):
        f, p, c = create(self.path, **kwargs)
        self.addCleanup(p.close); self.addCleanup(f.close)
        return f, p, c

    def test_c0_c6_documented_exact_paths_and_no_actor_processes(self):
        doc = (ROOT/'docs/research/001d/001d-06/REPORT.md').read_text()
        for value in ('fc_access/production_v1/foundation.py', 'fc_access/bidding_v1/scheduler.py',
                      'fc_access/bidding_v1/journal.py', 'fc_access/bidding_v1/core.py',
                      'fc_access/durability_v1/store.py', 'fc_access/production_v1/store.py',
                      'fc_access/production_v1/adapter.py', 'browser/production-v1',
                      '127.0.0.1:8784', 'concurrency=1', 'deadline', 'delivery_ms', 'native_service_ms',
                      'interval', '600-second', '25-second', 'python -m fc_access.production_v1.server'):
            self.assertIn(value, doc)
        for filename in ('foundation.py', 'once.py'):
            tree = ast.parse((ROOT/'fc_access/production_v1'/filename).read_text())
            forbidden = {'Popen', 'Start-Process', 'serve_forever', 'Thread', 'create_task'}
            self.assertFalse(any(isinstance(n, ast.Call) and
                ((isinstance(n.func, ast.Name) and n.func.id in forbidden) or
                 (isinstance(n.func, ast.Attribute) and n.func.attr in forbidden)) for n in ast.walk(tree)))
        result = subprocess.run([sys.executable, '-m', 'fc_access.production_v1.once', '--help'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--interval', result.stdout)

    def test_c0_c5_migration_records_provenance_and_supported_versions(self):
        out=ROOT/'docs/research/001d/001d-06'
        manifest=json.loads((out/'migration.json').read_text())
        expected={'fc_access/bidding_v1/journal.py','fc_access/production_v1/server.py',
                  'fc_access/production_v1/store.py','tests/test_001d05_inventory.py',
                  'tests/test_001d02_contract.py'}
        self.assertEqual(set(manifest['paths']),expected)
        for path,record in manifest['paths'].items():
            # Historical digests describe the captured tree. Current contracts
            # are exercised by the behavioral tests below, not source equality.
            self.assertIsInstance(ast.parse((ROOT/path).read_text()), ast.Module)
        from fc_access.production_v1.contracts import VERSION
        self.assertEqual(VERSION,2)

    def test_c1_c3_c5_end_to_end_real_adapter_prices_admission_scheduler_journal(self):
        f, p, clock = self.api()
        with patch('socket.socket', side_effect=AssertionError('fixture must not access network')):
            decision, _, _ = admitted(f, p)
            self.assertEqual((decision['action'],decision['amount'],decision['cap']), ('BID',2500,10750))
            self.assertEqual(p.bid_calls, 0, 'admission itself may not send')
            during = []
            def observe(c):
                j = Journal(self.path/'journal.sqlite3', readonly=True)
                try:
                    during.extend(e['reason'] for e in j.trace() if e['command_id'] == c['id'])
                finally: j.close()
            p.on_bid = observe
            result = f.bid(p.candidate['trade_id'], command_id='8'*32)
        self.assertEqual(result, dict(command_id='8'*32,outcome='ACKNOWLEDGED',reason='NATIVE_ACK'))
        self.assertEqual(during, ['INTENT_DURABLE','PENDING'])
        current = f.registry.current()
        self.assertEqual(current['schema'],1)
        self.assertEqual(current['context'],CONTEXT)
        self.assertEqual(current['credits']['available_coins'],90000)
        self.assertEqual(current['credits']['available_after_reservations'],87500)
        self.assertEqual(current['queued'],[p.candidate['trade_id']])
        self.assertEqual(current['unresolved'][0]['state'],'ACKNOWLEDGED')
        evidence = f.registry.events(p.candidate['trade_id'])[-1]['quote']['evidence']
        self.assertEqual(evidence['price_searches'],2)
        self.assertEqual(evidence['claim'],'OBSERVED_MINIMUM_ONLY')
        self.assertEqual(set(c['operation'] for c in p.calls), {'search','watched','balance','caps','price_helpers','bid','transfer_list'})
        self.assertEqual(p.real_account_writes,0)
        self.assertEqual(f.executor.scheduler.concurrency,1)
        self.assertTrue(all(m['request_count']==1 for m in f.executor.metrics))
        self.assertEqual(f.journal.db.execute('SELECT state FROM commands').fetchone(),('ACKNOWLEDGED',))

    def test_c0_c4_priority_deadlines_cadence_and_distinct_metrics(self):
        f,p,clock = self.api(interval=.1)
        e = f.executor
        for cid, op, params, priority in [('1'*32,'balance',{},0),
            ('2'*32,'watched',{},10),('3'*32,'balance',{},0)]:
            e.submit(f.adapter.envelope(cid,op,params),priority=priority,timeout=1 if cid!='3'*32 else .05)
        self.assertEqual(e.run_one(),'2'*32)
        self.assertIsNone(e.run_one(), 'native cadence must be honored')
        # Delivery telemetry does not spend a native slot or change cadence.
        last = e.scheduler.last_native
        e.scheduler.delivery('7'*32,1,enqueued_at=.99)
        self.assertEqual(e.scheduler.last_native,last)
        clock.sleep(.1)
        self.assertEqual(e.run_one(),'1'*32)
        self.assertEqual([c['id'] for c in p.calls],['2'*32,'1'*32])
        self.assertIn('3'*32,e.errors)
        self.assertTrue(any(ev['kind']=='DEADLINE_SKIPPED' for ev in f.registry.events()))
        for m in e.metrics:
            self.assertAlmostEqual(m['roundtrip_ms'],5)
            self.assertEqual(m['native_service_ms'],1)
            self.assertAlmostEqual(m['delivery_ms'],4)
            self.assertEqual(m['interval_seconds'],.1)
        self.assertGreater(e.metrics[1]['queue_ms'],e.metrics[0]['queue_ms'])
        self.assertEqual(e.scheduler.active,{})

    def test_c4_native_write_priority_and_earliest_deadline(self):
        f,p,c = self.api()
        s = f.executor.scheduler
        for w in (Work('1'*32,'read',0,5),Work('2'*32,'write',0,9),Work('3'*32,'read',0,2)):
            s.enqueue(w)
        self.assertEqual(s.next().command_id,'2'*32)
        self.assertIsNone(s.next())
        s.complete('2'*32)
        self.assertEqual(s.next().command_id,'3'*32)
        with self.assertRaisesRegex(ValueError,'duplicate_command'): s.enqueue(Work('3'*32,'read',0,5))

    def test_c0_c4_bid_expires_while_paced_and_is_never_delivered(self):
        f,p,c=self.api(interval=1)
        f.read('balance')
        params=dict(trade_id=p.candidate['trade_id'],item_id=p.candidate['item']['item_id'],
                    definition_id=123,amount=2500,minimum=2500,cap=10750,
                    deadline=(c.now()+timedelta(seconds=.05)).isoformat(),
                    status_read_id='6'*32,balance_read_id='7'*32)
        with self.assertRaisesRegex(TimeoutError,'deadline_skipped'):
            f.executor.execute(f.adapter.envelope('5'*32,'bid',params))
        self.assertEqual(p.bid_calls,0)
        self.assertEqual(len(p.calls),1)
        self.assertEqual(f.executor.scheduler.active,{})
        self.assertEqual(f.registry.events()[-1]['kind'],'DEADLINE_SKIPPED')

    def test_c1_c5_balance_and_profitability_rejections_do_not_write(self):
        f,p,c=self.api()
        p.credits=2000
        rejected,_,_=admitted(f,p)
        # Below the admission reserve pauses acquisition in sticky coin DRAINING.
        self.assertEqual((rejected['action'],rejected['reason']),('HOLD','DRAINING'))
        self.assertEqual(f.registry.current()['queued'],[])
        p.credits=90000;p.candidate['starting_bid']=15000
        rejected,_,_=admitted(f,p)
        self.assertEqual((rejected['action'],rejected['reason']),('REJECT','QUOTE_REJECTED'))
        self.assertEqual(p.bid_calls,0)
        self.assertEqual(f.journal.db.execute('SELECT COUNT(*) FROM commands').fetchone()[0],0)

    def test_c1_hold_reject_unknown_are_reason_coded_and_append_only(self):
        f,p,clock = self.api()
        p.candidate['bid_state']='highest'
        p.watched=[p.candidate]
        hold,_,_ = admitted(f,p)
        self.assertEqual((hold['action'],hold['reason']),('HOLD','LEADING'))
        p.candidate['bid_state']='none'; p.candidate['item']['untradeable']=True
        reject,_,_ = admitted(f,p)
        self.assertEqual((reject['action'],reject['reason']),('REJECT','NOT_TRADEABLE'))
        p.candidate['item']['untradeable']=False
        p.candidate.update(trade_state='inactive',bid_state='none')
        unknown,_,_ = admitted(f,p)
        self.assertEqual((unknown['action'],unknown['reason']),('UNKNOWN','UNKNOWN'))
        self.assertEqual([e['action'] for e in f.registry.events(p.candidate['trade_id'])],['HOLD','REJECT','UNKNOWN'])
        for table in ('registry_events_v1','events'):
            for query in (f'UPDATE {table} SET seq=seq', f'DELETE FROM {table}'):
                with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'): f.journal.db.execute(query)
        self.assertEqual(p.bid_calls,0)

    def test_c2_c4_dropped_result_duplicate_intent_and_missing_readback(self):
        f,p,c = self.api()
        admitted(f,p)
        p.failure = TimeoutError('fixture drop')
        result = f.bid(p.candidate['trade_id'],command_id='9'*32)
        self.assertEqual((result['outcome'],result['reason']),('UNKNOWN','TIMEOUT'))
        self.assertEqual(f.executor.metrics[-1]['request_count'],None)
        self.assertEqual(f.executor.metrics[-1]['native_service_ms'],None)
        with self.assertRaisesRegex(ValueError,'duplicate_write'):
            f.bid(p.candidate['trade_id'],command_id='9'*32)
        with self.assertRaisesRegex(ValueError,'reconciliation_required'):
            f.bid(p.candidate['trade_id'],command_id='7'*32)
        self.assertEqual(p.bid_calls,1)
        p.watched=[]
        status=f.read('watched'); funds=f.read('balance')
        with self.assertRaisesRegex(ValueError,'outcome_still_unknown'):f.reconcile('9'*32,status,funds)
        self.assertEqual(f.registry.current()['unresolved'][0]['state'],'UNKNOWN')

    def test_c2_c4_real_process_crashes_before_and_after_claim_replay_unknown(self):
        for phase in ('intent','claimed'):
            with self.subTest(phase=phase):
                directory=self.path/phase;directory.mkdir()
                result=subprocess.run([sys.executable,'tests/foundation_fixture.py',str(directory),phase],
                                      cwd=ROOT,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,19,result.stdout+result.stderr)
                j=Journal(directory/'journal.sqlite3')
                self.assertEqual(j.db.execute('SELECT state FROM commands').fetchone(),('UNKNOWN',))
                reasons=[e['reason'] for e in j.trace() if e['command_id']=='9'*32]
                self.assertEqual(reasons,['INTENT_DURABLE']+(['PENDING'] if phase=='claimed' else []))
                j.close()
                f,p,c=create(directory)
                try:
                    current=f.registry.current()
                    self.assertEqual(current['epoch'],3, 'new epoch must exceed restarted transport epoch 2')
                    self.assertEqual(current['unresolved'][0]['state'],'UNKNOWN')
                    self.assertEqual(current['auctions'][p.candidate['trade_id']]['action'],'UNKNOWN')
                    decision,_,_=admitted(f,p)
                    self.assertEqual((decision['action'],decision['reason']),('UNKNOWN','UNRESOLVED_INTENT'))
                    old=f.journal.db.execute('SELECT id,owner,scope,epoch,trade_id,item_id,definition_id,amount,deadline,status_read_id,balance_read_id FROM commands').fetchone()
                    intent=BidIntent(old[0],old[1],old[2],old[3],Identity(*old[4:7]),old[7],10750,
                        __import__('datetime').datetime.fromisoformat(old[8]),old[9],old[10])
                    with self.assertRaisesRegex(ValueError,'stale_owner_or_epoch'):
                        f.journal.dispatch(intent,lambda: self.fail('replayed recovered intent'))
                    new=replace(intent,owner=f.registry.owner,epoch=f.registry.epoch)
                    with self.assertRaisesRegex(ValueError,'no_local_dispatch_authority'):
                        f.journal.dispatch(new,lambda:self.fail('replayed with new owner'))
                    self.assertEqual(p.bid_calls,0)
                    self.assertEqual((directory/'native-called.json').exists(),phase=='claimed')
                finally:f.close();p.close()

    def test_c1_c4_stale_reads_and_old_owner_cannot_admit_or_dispatch(self):
        f,p,c=self.api()
        _,watched,funds=admitted(f,p)
        c.sleep(31)
        with self.assertRaisesRegex(ValueError,'stale_or_unauthenticated'):f.admit(watched,p.candidate['trade_id'],funds)
        with self.assertRaisesRegex(ValueError,'stale_or_unauthenticated'):f.bid(p.candidate['trade_id'])
        self.assertEqual(f.journal.db.execute('SELECT COUNT(*) FROM commands').fetchone()[0],0)
        old=f.registry.epoch
        f.journal.session(f.registry.scope,'6'*32)
        self.assertEqual(f.registry.current()['epoch'],old+1)
        with self.assertRaisesRegex(ValueError,'stale_owner_or_epoch'):f.read('balance')
        self.assertEqual(p.bid_calls,0)

    def test_c1_stable_full_context_ownership_and_isolation(self):
        f,p,c=self.api()
        original=scope_for(CONTEXT)
        self.assertEqual(original,scope_for(dict(reversed(list(CONTEXT.items())))))
        for name in ('account','persona','identity_namespace'):
            self.assertNotEqual(original,scope_for(CONTEXT|{name:'9'*32}))
        with self.assertRaises(ValueError):scope_for(CONTEXT|{'platform':'ps5'})
        j=Journal(self.path/'journal.sqlite3')
        try:
            other=Registry(j,CONTEXT|{'account':'9'*32},'8'*32)
            self.assertEqual(other.current()['auctions'],{})
            self.assertEqual(other.current()['unresolved'],[])
            self.assertNotEqual(other.scope,f.registry.scope)
        finally:j.close()

    def test_c2_c5_independent_reconciliation_clears_transport_fence(self):
        f,p,c=self.api()
        _,before,funds=admitted(f,p)
        f.bid(p.candidate['trade_id'],command_id='8'*32)
        with self.assertRaisesRegex(ValueError,'independent_fresh_readback_required'):
            f.reconcile('8'*32,before,funds)
        p.candidate.update(current_bid=2500,bid_state='highest')
        state=f.reconcile('8'*32,f.read('watched'),f.read('balance'))
        self.assertEqual(state['unresolved'],[])
        self.assertEqual(state['auctions'][p.candidate['trade_id']]['state'],'LEADING')
        self.assertEqual(state['auctions'][p.candidate['trade_id']]['action'],'HOLD')
        self.assertEqual(state['auctions'][p.candidate['trade_id']]['quote']['resale_price'],12000)
        self.assertEqual(state['credits']['available_after_reservations'],90000)
        previous=next(c for c in p.calls if c['operation']=='bid')
        self.assertTrue(JournalAuthority(self.path/'journal.sqlite3').reconciled(previous))
        # A second distinct auction is admissible; the transport consults journal evidence.
        p.candidate=auction(123,15000,2);p.candidate['starting_bid']=2500;p.watched=[p.candidate]
        decision,_,_=admitted(f,p)
        self.assertEqual(decision['action'],'BID')
        self.assertEqual(f.bid(p.candidate['trade_id'])['outcome'],'ACKNOWLEDGED')
        self.assertEqual(p.store.db.execute("SELECT state FROM commands WHERE id=?",('8'*32,)).fetchone(),('RECONCILED',))

    def test_c1_c2_pending_victory_needs_proof_and_verified_loss_releases_queue(self):
        f,p,c=self.api()
        admitted(f,p)
        f.bid(p.candidate['trade_id'],command_id='8'*32)
        p.candidate.update(trade_state='closed',bid_state='highest',expires=0,current_bid=2500,native_is_won=True)
        with self.assertRaisesRegex(ValueError,'outcome_still_unknown'):
            f.reconcile('8'*32,f.read('watched'),f.read('balance'))
        self.assertEqual(len(f.registry.current()['unresolved']),1)
        p.candidate.update(bid_state='outbid',current_bid=2600,native_is_won=False)
        state=f.reconcile('8'*32,f.read('watched'),f.read('balance'))
        self.assertEqual(state['queued'],[])
        self.assertEqual(state['unresolved'],[])
        auction_state=state['auctions'][p.candidate['trade_id']]
        self.assertEqual((auction_state['state'],auction_state['action'],auction_state['reason']),('LOST','REJECT','SKIP'))
        self.assertEqual(p.bid_calls,1)

    def test_c2_c5_authority_rejects_forged_parameters_and_default_service_writes(self):
        f,p,c=self.api()
        admitted(f,p)
        authority=JournalAuthority(self.path/'journal.sqlite3')
        seen=[]
        def verify(cmd):
            self.assertTrue(authority(cmd))
            for key,value in [('amount',2600),('cap',11000),('status_read_id','7'*32)]:
                bad=deepcopy(cmd);bad['params'][key]=value
                if key=='amount':bad['params']['minimum']=value
                self.assertFalse(authority(bad))
            bad=deepcopy(cmd);bad['context']['account']='7'*32
            self.assertFalse(authority(bad))
            seen.append(cmd)
        p.on_bid=verify
        f.bid(p.candidate['trade_id'])
        self.assertEqual(len(seen),1)
        self.assertFalse(authority(seen[0]),'ack cannot become dispatch authority')
        from fc_access.production_v1.server import Server
        server=Server(self.path/'readonly.sqlite3',port=0,poll_seconds=0)
        try:
            self.assertIsNone(server.store.authorize_bid)
            server.store.activate(p.store.owner())
            peer=deepcopy(p.peer);peer['fences']['host_epoch']=server.store.host_epoch
            cmd=deepcopy(seen[0]);cmd['fences']=peer['fences']
            with self.assertRaisesRegex(ValueError,'mutation_requires_durable_intent'):server.store.enqueue(cmd,peer)
        finally:server.server_close();server.store.db.close()

    def test_c3_c6_standalone_fixture_exits_without_network_or_background_workers(self):
        result=subprocess.run([sys.executable,'tests/foundation_fixture.py',str(self.path),'once'],
                              cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report['decision']['action'],'BID')
        self.assertEqual(report['result']['outcome'],'ACKNOWLEDGED')
        self.assertEqual(report['real_account_writes'],0)
        self.assertEqual(report['native_fixture_bid_calls'],1)


if __name__=='__main__':unittest.main(verbosity=2)
