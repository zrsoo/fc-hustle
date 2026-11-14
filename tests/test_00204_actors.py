"""002-04 acceptance, synthetic only: python tests/test_00204_actors.py.

Each test checks contracts/negative cases. Real subprocesses use only ActorPage;
there is no Edge attachment, EA request, sustained actor or mutable-source hash.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from actors_fixture import create,ActorPage,Clock,CONTEXT,auction
from fc_access.actors_v1.actors import Acquirer,Bidder,connect
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.native import Mailbox,Broker,QueueExecutor
from fc_access.actors_v1.operator import inspect,retain
from fc_access.actors_v1.locking import process_lock
from fc_access.bidding_v1.contracts import Balance,BidIntent,Identity,Snapshot,Coverage,State
from fc_access.bidding_v1.core import AuctionQueue,decide
from fc_access.bidding_v1.journal import Journal
from fc_access.production_v1.contracts import Search,command,parse_response
from fc_access.production_v1.foundation import Foundation,Registry,scope_for,status_from,freshness,JournalAuthority
from fc_access.production_v1.prices import CardKey


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)

    def api(self,config=None):
        f,p,c=create(self.path)
        self.addCleanup(p.close);self.addCleanup(f.close)
        cfg=config or Config(native_interval_seconds=0)
        return f,p,c,Acquirer(f,cfg,clock=c.monotonic,sleep=c.sleep),Bidder(f,cfg,clock=c.monotonic,sleep=c.sleep)

    def box(self,f,cfg=None,clock=None):
        box=Mailbox(self.path/'native.sqlite3');self.addCleanup(box.close)
        b=Broker(box,f,cfg or Config(native_interval_seconds=0),**(
            dict(now=clock.now,clock=clock.monotonic,sleep=clock.sleep) if clock else {}))
        b.initialize()
        return box,b

    def test_c0_defaults_configuration_cli_import_and_no_implicit_work(self):
        cfg=Config()
        self.assertEqual((cfg.search_interval_seconds,cfg.target_check_interval_seconds,cfg.max_search_bid,
            cfg.min_search_buy_now,cfg.min_available_coins,cfg.max_enrolled_auctions),(600,25,1000,11000,5000,50))
        self.assertEqual((cfg.min_profit_coins,cfg.estimated_sale_tax_rate,cfg.price_cache_ttl_seconds),(500,.05,86400))
        changed=Config(search_interval_seconds=300,target_check_interval_seconds=15,max_search_bid=1200,
            min_search_buy_now=13000,min_available_coins=6000,max_enrolled_auctions=20,min_profit_coins=700)
        self.assertEqual(changed.export()['max_enrolled_auctions'],20)
        for kw in [dict(max_enrolled_auctions=51),dict(max_enrolled_auctions=True),dict(search_interval_seconds=0),
            dict(target_check_interval_seconds=float('nan')),dict(min_profit_coins=-1),dict(rebid_only_when_outbid=False)]:
            with self.assertRaises(ValueError):Config(**kw)
        for argv in [[],['config']]:
            args=argv or ['--help']
            r=subprocess.run([sys.executable,'-m','fc_access.actors_v1',*args],cwd=self.path,
                env=self.env(),capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(list(self.path.iterdir()),[])

    @staticmethod
    def env():
        import os
        return dict(os.environ,PYTHONPATH=str(ROOT))

    def test_c1_priority_yield_between_commands_and_deadline_pacing(self):
        f,p,c,a,b=self.api()
        box,broker=self.box(f,Config(native_interval_seconds=2),c)
        staged=[('1'*32,'search',Search.pricing(123).params(),'acquirer'),
                ('2'*32,'watched',{},'bidder'),('3'*32,'balance',{},'maintenance'),
                ('4'*32,'status_support',{},'reconciliation')]
        # A local reconciliation helper wins priority without spending a native
        # request slot; the watched read can follow immediately.
        producers=[]
        try:
            for index in (0,1):
                jobs=[dict(command=f.adapter.envelope(cid,op,params),role=role,at=c.now().isoformat())
                    for cid,op,params,role in staged[index::2]]
                path=self.path/f'producer-{index}.json';path.write_text(json.dumps(jobs))
                producers.append(subprocess.Popen([sys.executable,'tests/actors_fixture.py',str(self.path),
                    'enqueue',str(path)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
            for producer in producers:
                out,err=producer.communicate(timeout=10)
                self.assertEqual(producer.returncode,0,out+err)
        finally:
            for producer in producers:
                if producer.poll() is None:producer.kill();producer.communicate()
        self.assertEqual(box.db.execute("SELECT count(*) FROM work WHERE state='WAITING'").fetchone(),(4,))
        self.assertEqual(broker.run_one()['command_id'],'4'*32)
        self.assertEqual(broker.run_one()['command_id'],'2'*32)
        self.assertIsNone(broker.run_one())
        c.sleep(2.01)
        self.assertEqual(broker.run_one()['command_id'],'1'*32)
        # New urgent work preempts the next pricing page or maintenance command.
        box.enqueue(f.adapter.envelope('5'*32,'watched',{}),'bidder',now=c.now())
        c.sleep(2.01)
        self.assertEqual(broker.run_one()['command_id'],'5'*32)
        native_events=[json.loads(r[0]) for r in box.db.execute('SELECT body FROM native_events')]
        metric=[e for e in native_events if e['kind']=='NATIVE_RESPONSE'][-1]
        self.assertGreaterEqual(metric['queue_ms'],0)
        self.assertAlmostEqual(metric['roundtrip_ms'],5)
        self.assertEqual(metric['epoch'],f.registry.epoch)
        for query in ('UPDATE native_events SET seq=seq','DELETE FROM native_events'):
            with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):box.db.execute(query)
        c.sleep(31)
        self.assertIsNone(broker.run_one())
        self.assertEqual(box.db.execute('SELECT state,reason FROM work WHERE id=?',('3'*32,)).fetchone(),('UNKNOWN','DEADLINE_SKIPPED'))
        self.assertEqual([v['id'] for v in p.calls],['4'*32,'2'*32,'1'*32,'5'*32])

    def test_c2_discovery_actual_wire_filters_pagination_and_duplicates(self):
        f,p,c,a,b=self.api()
        first=[auction(123,15000,10+i) for i in range(21)]
        for row in first:row['starting_bid']=800
        p.pages={1:first,2:[deepcopy(first[0]),auction(123,16000,99)]}
        p.pages[2][1]['starting_bid']=900
        rows=a.discover()
        self.assertEqual(len(rows),22)
        searches=[x for x in p.calls if x['operation']=='search']
        self.assertEqual([x['params']['page'] for x in searches],[1,2])
        p.pages[2][0]['item']['item_id']='item:'+'f'*24
        self.assertEqual(len(a.discover()),21,'conflicting duplicates poison the trade')
        mismatch=f.adapter.envelope('5'*32,'search',Search.discovery(page=2).params())
        v=p.execute(mismatch)
        v['result']['network'][0]['query']['macr']=11000
        with self.assertRaisesRegex(ValueError,'wire_criteria_mismatch'):parse_response(v,mismatch,now=c.now(),source='fixture')
        for row in (dict(first[0],current_bid=1100),dict(first[0],buy_now_price=10000)):
            self.assertFalse(a.matches(row))
        # Pricing remains strictly page 1 even after discovery pagination is added.
        with self.assertRaises(ValueError):Search('pricing',123,page=2)

    def test_c2_minimum_initial_native_bid_pricing_reuse_and_no_buy_now(self):
        f,p,c,a,b=self.api()
        a.cycle()
        bids=[x for x in p.calls if x['operation']=='bid']
        self.assertEqual([x['params']['amount'] for x in bids],[800])
        self.assertEqual(len([x for x in p.calls if x['operation']=='search' and x['params']['purpose']=='pricing']),2)
        policy=a.policy(p.candidate['trade_id'])
        self.assertEqual((policy['quote']['resale_price'],policy['quote']['max_affordable_bid']),(12000,10750))
        self.assertLess(bids[0]['params']['amount'],policy['quote']['max_affordable_bid'])
        self.assertEqual(bids[0]['params']['minimum'],800)
        before=p.bid_calls
        a.cycle();self.assertEqual(p.bid_calls,before)
        for op in ('buy_now','buyNow','acquire'):
            with self.assertRaises(ValueError):f.adapter.envelope('7'*32,op,{})
        self.assertEqual(p.real_account_writes,0)

    def test_c3_leading_hold_outbid_absolute_tick_and_stored_cap(self):
        f,p,c,a,b=self.api()
        a.cycle();b.cycle()
        self.assertEqual(p.bid_calls,1)
        last=[e for e in f.registry.events() if e['kind']=='DECISION'][-1]
        self.assertEqual((last['action'],last['reason']),('HOLD','LEADING'))
        p.candidate.update(current_bid=900,bid_state='outbid');p.watched=[deepcopy(p.candidate)]
        p.credits=90000
        a.cycle()
        self.assertEqual(p.bid_calls,1,'Acquirer cannot reenroll an existing unresolved auction')
        self.assertTrue([e for e in f.registry.events() if e.get('reason')=='DUPLICATE_SUPPRESSED'])
        b.cycle()
        self.assertEqual([v['params']['amount'] for v in p.calls if v['operation']=='bid'],[800,950])
        # No repricing in Bidder, no adding old held bids to spendable credits.
        self.assertEqual(len([v for v in p.calls if v['operation']=='search' and v['params']['purpose']=='pricing']),2)
        b.cycle();self.assertEqual(p.bid_calls,2)
        p.candidate.update(current_bid=10750,bid_state='outbid');p.watched=[deepcopy(p.candidate)]
        b.cycle()
        self.assertEqual(p.bid_calls,2)
        self.assertIn(p.candidate['trade_id'],f.queue.entries)
        last=[e for e in f.registry.events() if e['kind']=='DECISION'][-1]
        self.assertEqual((last['reason'],last['cap']),('OVER_CAP',10750))
        p.watched=[];b.cycle()
        self.assertIn(p.candidate['trade_id'],f.queue.entries,'absence is not a loss')
        p.candidate.update(trade_state='closed',expires=0,bid_state='outbid');p.watched=[deepcopy(p.candidate)]
        b.cycle();self.assertNotIn(p.candidate['trade_id'],f.queue.entries)

    def test_c3_insufficient_spendable_never_assumes_escrow_refund(self):
        f,p,c,a,b=self.api()
        a.cycle();b.cycle()
        p.candidate.update(current_bid=900,bid_state='outbid');p.watched=[deepcopy(p.candidate)]
        p.credits=949
        b.cycle()
        self.assertEqual(p.bid_calls,1)
        self.assertEqual([e for e in f.registry.events() if e['kind']=='DECISION'][-1]['reason'],'INSUFFICIENT_BALANCE')

    def test_c3_independent_owned_win_proof_and_no_false_terminal(self):
        f,p,c,a,b=self.api()
        a.cycle()
        p.candidate.update(trade_state='closed',expires=0,native_is_won=True)
        p.watched=[deepcopy(p.candidate)]
        b.cycle()
        self.assertIn(p.candidate['trade_id'],f.queue.entries)
        p.owned=[deepcopy(p.candidate['item'])]
        p.owned[0]['last_sale_price']=800
        b.cycle()
        self.assertNotIn(p.candidate['trade_id'],f.queue.entries)
        self.assertEqual([e for e in f.journal.trace() if e['reason']=='WON_VERIFIED'][-1]['data']['paid'],800)
        self.assertEqual(p.bid_calls,1)
        box,_=self.box(f)
        backup=self.path/'settlement-retained'
        retain(box.path,backup)
        restored=Journal(backup/'journal.sqlite3',readonly=True)
        try:
            wins=[e for e in restored.trace() if e['reason']=='WON_VERIFIED']
            self.assertEqual(wins[-1]['data']['paid'],800)
        finally:restored.close()

    def test_c4_intent_before_send_persistence_failure_ambiguity_and_cap_never_increases(self):
        f,p,c,a,b=self.api()
        observed=[]
        original=p.on_bid
        def observe(cmd):
            j=Journal(f.journal_path,readonly=True)
            try:observed.extend(e['reason'] for e in j.trace() if e['command_id']==cmd['id'])
            finally:j.close()
            self.assertTrue(JournalAuthority(f.journal_path)(cmd))
            original(cmd)
        p.on_bid=observe
        a.cycle()
        self.assertEqual(observed,['INTENT_DURABLE','PENDING'])
        b.cycle()
        params=[v for v in p.calls if v['operation']=='bid'][0]['params']
        identity=Identity(params['trade_id'],params['item_id'],params['definition_id'])
        intent=BidIntent('5'*32,f.registry.owner,f.registry.scope,f.registry.epoch,identity,900,11000,
            c.now()+timedelta(seconds=300),'6'*32,'7'*32)
        with self.assertRaisesRegex(ValueError,'stored_cap_increase'):f.journal.intend(intent)
        p.candidate.update(current_bid=900,bid_state='outbid');p.watched=[deepcopy(p.candidate)]
        before=p.bid_calls
        with patch.object(f.journal,'intend',side_effect=sqlite3.OperationalError('disk_full')):
            with self.assertRaises(sqlite3.OperationalError):b.cycle()
        self.assertEqual(p.bid_calls,before)
        p.failure=TimeoutError('SECRET must never enter evidence')
        b.cycle()
        self.assertEqual(p.bid_calls,before+1)
        p.watched=[]
        b.cycle();a.cycle()
        self.assertEqual(p.bid_calls,before+1)
        self.assertNotIn('SECRET',json.dumps(f.journal.trace())+json.dumps(f.registry.events()))

    def test_c4_recovered_intent_never_gets_dispatch_authority(self):
        f,p,c,a,b=self.api()
        # Simulate process death just after intent commit, before dispatch claim.
        with patch.object(f.journal,'dispatch',side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):a.cycle()
        self.assertEqual(p.bid_calls,0)
        old=f.journal.db.execute('SELECT id,owner,scope,epoch,trade_id,item_id,definition_id,amount,deadline,status_read_id,balance_read_id FROM commands').fetchone()
        j=Journal(f.journal_path,now=c.now);self.addCleanup(j.close)
        from datetime import datetime
        intent=BidIntent(old[0],old[1],old[2],old[3],Identity(*old[4:7]),old[7],10750,datetime.fromisoformat(old[8]),old[9],old[10])
        with self.assertRaisesRegex(ValueError,'no_local_dispatch_authority'):j.dispatch(intent,lambda:self.fail('blind retry'))
        b.cycle();a.cycle()
        self.assertEqual(p.bid_calls,0)
        self.assertTrue(a.pending())

    def test_c4_mailbox_journal_failure_blocks_native_dispatch(self):
        f,p,c,a,b=self.api()
        box,broker=self.box(f,clock=c)
        cmd=f.adapter.envelope('4'*32,'balance',{})
        box.enqueue(cmd,'bidder',now=c.now())
        box.db.execute("CREATE TRIGGER fail_claim BEFORE INSERT ON native_events WHEN json_extract(NEW.body,'$.kind')='DISPATCH_CLAIM' BEGIN SELECT RAISE(ABORT,'disk_full'); END")
        with self.assertRaises(sqlite3.IntegrityError):broker.run_one()
        self.assertEqual(p.calls,[])
        self.assertEqual(box.db.execute('SELECT state FROM work').fetchone(),('WAITING',))
        box.db.execute('DROP TRIGGER fail_claim')
        broker.run_one()
        self.assertEqual(len(p.calls),1)

    def test_c5_operator_views_windows_retention_and_append_only_reconstruction(self):
        f,p,c,a,b=self.api()
        box,broker=self.box(f)
        a.run(cycles=1);b.run(cycles=1)
        trade=p.candidate['trade_id']
        status=inspect(box.path)
        self.assertEqual(set(status['actors']),{'acquirer','bidder'})
        self.assertEqual(status['unresolved_auctions'],[trade])
        self.assertEqual(status['coins']['available_after_reservations'],p.credits)
        self.assertTrue(inspect(box.path,'blocked',trade=trade))
        decisions=inspect(box.path,'decisions',trade=trade)
        self.assertEqual(decisions[-1]['reason'],'LEADING')
        since=(c.now()+timedelta(seconds=1)).isoformat()
        self.assertEqual(inspect(box.path,'decisions',since=since),[])
        self.assertTrue(inspect(box.path,'timeline',trade=trade)['journal'])
        trace=inspect(box.path,'export')
        for key in ('cookie','authorization','token','session_identifier','SECRET'):
            self.assertNotIn(key,json.dumps(trace).lower())
        for table in ('events','registry_events_v1'):
            for statement in (f'UPDATE {table} SET seq=seq',f'DELETE FROM {table}'):
                with self.assertRaisesRegex(sqlite3.IntegrityError,'append_only'):f.journal.db.execute(statement)
        queue=AuctionQueue(journal=f.journal,scope=f.registry.scope)
        self.assertEqual(set(queue.entries),{trade})
        self.assertEqual(queue.identities[trade].item_id,p.candidate['item']['item_id'])
        p.candidate.update(current_bid=900,bid_state='outbid');p.watched=[deepcopy(p.candidate)]
        p.failure=TimeoutError('synthetic lost acknowledgement')
        b.cycle()
        self.assertTrue(inspect(box.path)['unresolved_intents'])
        backup=self.path/'retained'
        self.assertEqual(retain(box.path,backup)['pruned_events'],0)
        restored=Journal(backup/'journal.sqlite3',readonly=True)
        try:
            self.assertEqual(restored.trace(),f.journal.trace())
            self.assertEqual(restored.db.execute("SELECT count(*) FROM commands WHERE state='UNKNOWN'").fetchone(),(1,))
        finally:restored.close()
        r=subprocess.run([sys.executable,'-m','fc_access.actors_v1','--state-dir',str(self.path),'export',
            '--output',str(self.path/'export.json')],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads((self.path/'export.json').read_text())['schema'],1)

    def test_c6_native_cap_equality_and_rounding_at_boundaries(self):
        f,p,c,a,b=self.api()
        prices=f.prices.load(key=CardKey(123))
        # floor(12000 - 600 - 500)=10750, never 11000. Both native
        # helper directions must agree; the absolute next tick is the bid.
        self.assertEqual(prices.profitable_cap(12000,500),10750)
        self.assertEqual(prices.floor(999),950)
        self.assertEqual(prices.floor(1000),1000)
        self.assertEqual(prices.floor(10999),10750)
        response=f.read('search',Search.discovery().params())
        row=deepcopy(response['result']['auctions'][0]);row.update(current_bid=10500,bid_state='outbid')
        status=status_from(row,response)
        funds=f.read('balance');balance=Balance(90000,None,freshness(funds))
        self.assertEqual(decide(status,balance,prices,10750,now=c.now()).amount,10750)
        self.assertEqual(decide(status,balance,prices,10749,now=c.now()).reason,'OVER_CAP')

    def test_c6_reserve_escrow_limit_and_sticky_draining_replay(self):
        f,p,c,a,b=self.api()
        p.credits=5800
        a.cycle()
        self.assertEqual(p.bid_calls,1)
        self.assertTrue(f.queue.draining)
        b.cycle()
        p.credits=90000
        a.cycle();self.assertEqual(p.bid_calls,1,'reserve draining sticks while an auction is unresolved')
        queue=AuctionQueue(journal=f.journal,scope=f.registry.scope)
        self.assertTrue(queue.draining)
        p.candidate.update(trade_state='closed',expires=0,bid_state='outbid');p.watched=[deepcopy(p.candidate)]
        b.cycle()
        self.assertTrue(f.queue.draining,'terminal outcome alone cannot reset coin draining')
        a.cycle()
        self.assertFalse(f.queue.draining)
        # Separate capacity registry with 50 unresolved reservations.
        q=AuctionQueue(capacity=50,reserve=5000)
        response=f.read('search',Search.discovery().params())
        funds=f.read('balance');balance=Balance(100000,None,freshness(funds))
        for i in range(51):
            row=auction(123,15000,100+i);row['starting_bid']=800
            s=status_from(row,response)
            self.assertEqual(q.admit(s,balance,800,now=c.now()),'ENROLLED' if i<50 else 'QUEUE_FULL')
        self.assertEqual(len(q.entries),50)

    def test_c6_stale_identity_epoch_and_shared_scoped_session(self):
        f,p,c,a,b=self.api()
        box,broker=self.box(f)
        proxy=QueueExecutor(box.path,'bidder');self.addCleanup(proxy.close)
        joined=connect(proxy);self.addCleanup(joined.close)
        self.assertEqual(joined.registry.epoch,f.registry.epoch)
        self.assertEqual(joined.registry.scope,f.registry.scope)
        a.cycle()
        p.watched[0]['item']['item_id']='item:'+'f'*24
        b.cycle();self.assertEqual(p.bid_calls,1)
        self.assertIn(p.candidate['trade_id'],f.queue.entries)
        snapshot=f.read('watched');funds=f.read('balance');c.sleep(31)
        with self.assertRaises(ValueError):f.admit(snapshot,p.candidate['trade_id'],funds)
        original=f.adapter.envelope('8'*32,'balance',{})
        bad=deepcopy(original);bad['context']['account']='9'*32
        with self.assertRaisesRegex(ValueError,'stale_identity'):box.enqueue(bad,'bidder')
        f.journal.session(f.registry.scope,'8'*32)
        with self.assertRaisesRegex(ValueError,'stale_owner_or_epoch'):a.cycle()
        self.assertNotEqual(scope_for(CONTEXT),scope_for(CONTEXT|{'account':'d'*32}))

    def test_c6_scheduler_no_catchup_and_restart_cadence(self):
        f,p,c,a,b=self.api(Config(search_interval_seconds=10,target_check_interval_seconds=5,native_interval_seconds=0))
        starts=[]
        def cycle():starts.append(c.monotonic());c.sleep(12 if len(starts)==1 else 1)
        a.cycle=cycle
        a.run(cycles=3)
        self.assertAlmostEqual(starts[1],12.001,places=3)
        self.assertAlmostEqual(starts[2]-starts[1],10,places=3)
        previous=starts[-1]
        a.run(cycles=1)
        self.assertAlmostEqual(starts[-1]-previous,10,places=3)
        self.assertTrue([e for e in f.registry.events() if e.get('missed_target')])

    def test_c6_bidder_cannot_settle_from_an_aged_watched_snapshot(self):
        f,p,c,a,b=self.api()
        a.cycle()
        p.candidate.update(trade_state='closed',expires=0,bid_state='outbid')
        p.watched=[deepcopy(p.candidate)]
        original=f.read
        def delayed(operation,params=None):
            value=original(operation,params)
            if operation=='watched':c.sleep(31)
            return value
        with patch.object(f,'read',side_effect=delayed):b.cycle()
        self.assertIn(p.candidate['trade_id'],f.queue.entries)
        self.assertTrue(a.pending())
        self.assertFalse([e for e in f.journal.trace() if e['reason']=='LOST_VERIFIED'])
        self.assertEqual(f.registry.events()[-1]['reason'],'STALE_STATUS')

    def test_c6_mailbox_restart_duplicate_and_unknown_do_not_redispatch(self):
        f,p,c,a,b=self.api()
        box,broker=self.box(f,clock=c)
        cmd=f.adapter.envelope('6'*32,'balance',{})
        box.enqueue(cmd,'bidder',now=c.now())
        with self.assertRaises(sqlite3.IntegrityError):box.enqueue(cmd,'bidder',now=c.now())
        box.db.execute("UPDATE work SET state='CLAIMED'")
        broker.initialize()
        self.assertIsNone(broker.run_one())
        self.assertEqual(box.db.execute('SELECT state,reason FROM work').fetchone(),('UNKNOWN','EXECUTOR_RESTART'))
        self.assertEqual(p.calls,[])
        with process_lock(self.path/'same.lock'):
            with self.assertRaisesRegex(ValueError,'process_already_running'):
                with process_lock(self.path/'same.lock'):self.fail('second executor')

    def test_c1_c6_real_independent_actor_processes_share_one_executor(self):
        broker=subprocess.Popen([sys.executable,'tests/actors_fixture.py',str(self.path),'broker'],cwd=ROOT,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        workers=[]
        try:
            end=time.monotonic()+10
            while not (self.path/'ready').exists() and time.monotonic()<end:
                if broker.poll() is not None:break
                time.sleep(.01)
            self.assertTrue((self.path/'ready').exists(),'fixture broker did not initialize')
            # Both actors are actual separate Python entry points, bounded to one
            # cycle. No test or worker attaches to a browser or live service.
            for role in ('acquirer','bidder'):
                workers.append(subprocess.Popen([sys.executable,'-m','fc_access.actors_v1','--state-dir',str(self.path),
                    role,'--cycles','1'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
            for worker in workers:
                out,err=worker.communicate(timeout=20)
                self.assertEqual(worker.returncode,0,out+err)
            # A fresh second bidder cycle independently reconciles any enrollment
            # that occurred after the concurrent bidder's empty initial read.
            r=subprocess.run([sys.executable,'-m','fc_access.actors_v1','--state-dir',str(self.path),'bidder','--cycles','1'],
                cwd=ROOT,capture_output=True,text=True,timeout=35)
            self.assertEqual(r.returncode,0,r.stderr)
            status=inspect(self.path/'native.sqlite3')
            self.assertEqual(set(status['actors']),{'acquirer','bidder'})
            self.assertEqual(status['unresolved_intents'],[])
            self.assertEqual(len(status['unresolved_auctions']),1)
        finally:
            for worker in workers:
                if worker.poll() is None:worker.kill();worker.communicate()
            (self.path/'stop').touch()
            try:out,err=broker.communicate(timeout=5)
            except subprocess.TimeoutExpired:broker.kill();out,err=broker.communicate()
        self.assertEqual(broker.returncode,0,out+err)
        calls=json.loads((self.path/'calls.json').read_text())
        self.assertEqual(len([c for c in calls if c['operation']=='bid']),1)
        self.assertEqual(len(set((c['fences']['owner'],c['fences']['epoch']) for c in calls)),1)


if __name__=='__main__':unittest.main(verbosity=2)
