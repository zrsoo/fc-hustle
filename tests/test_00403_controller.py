"""004-03 independent complete offline controller acceptance.

Real controller + durable authority + parsers + native pricing, synthetic EA only.
Run from the task workspace: python tests/test_00403_controller.py
"""
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
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller, identity
from fc_access.controller_v1.protocol import delivery_command
from fc_access.controller_v1.store import ControllerStore
from fc_access.production_v1.contracts import stamp
from fc_access.production_v1.price_cache import TTL_SECONDS


class ControllerAcceptance(unittest.TestCase):
    def harness(self,count=3,**kwargs):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        h=Harness(tmp.name,count,**kwargs);self.addCleanup(h.close)
        return h

    def test_0_threshold_boundaries_config_failed_read_and_durable_halt(self):
        for balance,threshold,admitted in [(39999,40000,False),(40000,40000,False),
                                           (40001,40000,True),(50000,50000,False),(50001,50000,True)]:
            with self.subTest(balance=balance,threshold=threshold):
                h=self.harness(1,threshold=threshold);h.ea.credits=balance
                state=h.controller.step()
                self.assertEqual(len(h.calls('balance')),1)
                self.assertEqual(len(h.calls('bid')),int(admitted))
                if not admitted:
                    self.assertEqual(state['lifecycle'],'HALTED');self.assertTrue(state['reason'])
                    # Reconstruct controller with the same durable state; no new read.
                    c=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
                    self.assertEqual(c.step()['reason'],state['reason']);self.assertEqual(len(h.calls('balance')),1)
        h=self.harness(1);h.ea.balance_fail=True;state=h.controller.step()
        self.assertEqual(state['lifecycle'],'RUNNING');self.assertFalse(h.calls('bid'))
        self.assertEqual(h.store.db.execute('SELECT state FROM c4_policy_batches').fetchone()[0],'READ_FAILED')
        self.assertEqual(h.store.db.execute('SELECT count(*) FROM c4_batches').fetchone()[0],0)
        self.assertEqual(state['phase'],'MAINTENANCE')
        h.ea.balance_fail=False;h.controller.step();h.controller.step();self.assertEqual(len(h.calls('balance')),2)
        self.assertEqual(len(h.calls('bid')),1)

    def test_1_discovery_filters_identity_fields_observation_ages_and_exact_counts(self):
        h=self.harness(10);state=h.controller.step()
        self.assertEqual(state['phase'],'MANAGING');self.assertEqual(len(state['members']),10)
        searches=h.calls('search');self.assertEqual(len(searches),3)
        discovery=[x for x in searches if x['command']['params']['purpose']=='discovery']
        self.assertEqual(len(discovery),1)
        self.assertEqual(discovery[0]['command']['params'],dict(purpose='discovery',page=1,count=21,fresh=True,max_bid=1000,min_buy=11000))
        self.assertEqual(discovery[0]['command']['context']['platform'],'pc')
        for op,n in [('balance',1),('watched',1),('transfer_list',1),('bid',10),('status_batch',2)]:
            self.assertEqual(len(h.calls(op)),n,op)
        batch=h.controller.journal.batch(state['batch_id'])
        self.assertEqual(batch['discovery']['result']['auctions'][0]['item'],h.ea.rows[0]['item'])
        selected=h.controller.journal.selected(state['batch_id'])
        for c in selected:
            self.assertEqual(c['selection_remaining'],c['row']['expires']-c['selection_age'])
            self.assertGreater(c['selection_age'],0);self.assertGreater(c['selection_remaining'],60)
            for k in ['starting_bid','current_bid','buy_now_price','expires']:self.assertIn(k,c['row'])
        bid_metrics=h.metrics('BID');self.assertEqual(len(bid_metrics),10)
        self.assertTrue(all(m['observation_age']>=selected[0]['selection_age'] for m in bid_metrics))
        self.assertGreater(bid_metrics[-1]['observation_age'],bid_metrics[0]['observation_age'])
        bids=h.calls('bid');burst=[c for c in h.ea.calls if bids[0]['at']<=c['at']<=bids[-1]['at']]
        self.assertEqual({c['command']['operation'] for c in burst},{'bid'})
        self.assertEqual(len(h.calls('status_batch')[0]['command']['params']['targets']),10)
        self.assertLess(h.calls('status_batch')[0]['at'],bids[0]['at'])
        self.assertGreater(h.calls('status_batch')[-1]['at'],bids[-1]['at'])
        self.assertTrue(all(c['read_id']==h.calls('status_batch')[0]['command']['id'] for c in selected))
        self.assertTrue(all(c['discovery_read_id']==discovery[0]['command']['id'] for c in selected))

    def test_2_imported_pricing_cache_version_ttl_tax_native_caps_and_no_funding_allocator(self):
        h=self.harness(10);h.ea.credits=40001;h.controller.step()
        members=h.controller.journal.members();self.assertEqual(len(members),10)
        self.assertGreater(sum(m['cap'] for m in members),h.ea.credits)
        self.assertEqual(TTL_SECONDS,86400)
        price_queries=[x['command']['params'] for x in h.calls('search') if x['command']['params']['purpose']=='pricing']
        self.assertEqual(len(price_queries),2);self.assertNotIn('max_buy',price_queries[0]);self.assertEqual(price_queries[1]['max_buy'],12000)
        for m in members:
            self.assertEqual((m['resale_price'],m['cap'],m['quote']['tax'],m['quote']['X']),(12000,10750,600,500))
        self.assertTrue(any(m['quote']['evidence']['cache_hit'] for m in members[1:]))
        a=h.adapter.native;cached=h.cache.get(a.context,123,now=h.clock.now(),source='fixture')
        self.assertIsNotNone(cached)
        observed=stamp(cached['observed_at'])
        self.assertIsNotNone(h.cache.get(a.context,123,now=observed+timedelta(seconds=86399.999),source='fixture'))
        self.assertIsNone(h.cache.get(a.context,123,now=observed+timedelta(seconds=86400),source='fixture'))
        self.assertIsNone(h.cache.get(a.context,124,now=h.clock.now(),source='fixture'))
        # A truly new trade of the same version reuses completed observations.
        before=len(h.calls('search'));rules=h.controller.prices.loaded[h.controller.prices.latest[next(iter(h.controller.prices.latest))]]
        row=auction(123,15000,111);row['item']['last_sale_price']=999999
        quote=h.controller.pricing.quote(row,rules)
        self.assertEqual(len(h.calls('search')),before);self.assertEqual(quote.max_affordable_bid,10750)
        # Copying a quote must not include the next candidate as its own comparable.
        other=h.controller.pricing.quote(h.ea.offers[0],rules)
        self.assertEqual(other.resale_price,12500);self.assertEqual(other.evidence['price_searches'],0)

    def test_2_exclusions_early_rejection_and_one_quote_per_exact_version(self):
        h=self.harness(1)
        template=auction(123,10000,1010);template['starting_bid']=600
        own=deepcopy(h.ea.rows[0]);wrong=auction(124,1500,1011)
        h.ea.offers=[own,template,wrong,auction(123,12000,1012)]
        h.controller.step();m=h.controller.journal.members()[0]
        self.assertEqual(m['resale_price'],12000)
        exclusions=m['quote']['evidence']['exclusions']
        self.assertGreater(exclusions['candidate_excluded'],0)
        self.assertGreater(exclusions['default_600_10000_template'],0)
        h=self.harness(1);h.ea.rows[0]['starting_bid']=900
        h.ea.offers=[auction(123,1000,1020)]
        h.controller.step()
        self.assertFalse(h.calls('bid'))
        self.assertEqual(len([x for x in h.calls('search') if x['command']['params']['purpose']=='pricing']),1)
        h=self.harness(2);h.ea.rows[1]['item']['definition_id']=124;h.ea.offers.append(auction(124,13000,1021))
        h.controller.step();self.assertEqual(len(h.controller.journal.members()),2)
        self.assertEqual(len([x for x in h.calls('search') if x['command']['params']['purpose']=='pricing']),4)

    def test_3_sixty_second_selection_boundary_after_actual_age(self):
        for age,expected in [(0.999,1),(1.,0),(1.001,0)]:
            h=self.harness(1,spacing=0);h.ea.rows[0]['expires']=61
            def adjust(c):
                if c['operation']=='transfer_list':
                    at=h.adapter.native.responses[next(x['command']['id'] for x in h.calls('search') if x['command']['params']['purpose']=='discovery')]['freshness']['network_at']
                    base=(stamp(at)-h.clock.now()).total_seconds()+h.clock.value
                    h.clock.value=base+age-h.ea.duration
            h.ea.on_request=adjust;h.controller.step()
            self.assertEqual(len(h.calls('bid')),expected,age)
            if not expected:self.assertEqual(h.metrics('ACQUISITION')[-1]['expiry_misses'],1)
        h=self.harness(1);h.ea.rows[0]['expires']=60;h.controller.step();self.assertFalse(h.calls('bid'))

    def test_3_invalid_identity_tradeability_illegal_prices_and_ten_distinct_attempts(self):
        h=self.harness(21);h.ea.rows[0]['item']['untradeable']=True
        h.ea.rows[1]['starting_bid']=151;h.ea.rows[2]['starting_bid']=12000
        h.ea.rows[3]['trade_state']='closed';h.ea.rows[4]['bid_state']='highest'
        h.controller.step();self.assertEqual(len(h.calls('bid')),10)
        targets=[v['command']['params']['target'] for v in h.calls('bid')]
        self.assertEqual(len({t['trade_id'] for t in targets}),10)
        self.assertTrue(all(t['trade_id'] not in {r['trade_id'] for r in h.ea.rows[:5]} for t in targets))
        self.assertEqual(len(h.controller.journal.members()),10)
        with self.assertRaisesRegex(ValueError,'membership_limit'):
            h.controller.journal.member(h.controller.status()['batch_id'],{'target':identity(h.ea.rows[-1])})
        # Management can make a new rebid after ten initial decisions.
        h.ea.rows[5].update(bid_state='outbid',current_bid=200)
        h.controller.step();self.assertEqual(len(h.calls('bid')),11)

    def test_4_physical_and_combined_capacity_include_manual_sold_expired_pending(self):
        for physical,pending,expected in [(50,0,0),(49,0,1),(47,2,1),(40,10,0)]:
            h=self.harness(10)
            h.ea.inventory=[auction(123,n=2000+i) for i in range(physical)]
            for i,r in enumerate(h.ea.inventory):
                r.update(trade_state='closed' if i%2 else 'expired',bid_state='sold' if i%2 else 'none')
            h.ea.manual=[auction(123,n=3000+i) for i in range(pending)]
            for i,r in enumerate(h.ea.manual):r.update(trade_state='closed' if i%2 else 'active',bid_state='highest')
            h.controller.step();self.assertEqual(len(h.calls('bid')),expected,(physical,pending))
        h=self.harness(3);h.ea.inventory_complete=False;h.controller.step();self.assertFalse(h.calls('bid'))
        h=self.harness(3);h.ea.watched_fail=True;h.controller.step();self.assertFalse(h.calls('bid'))
        # No double count for the same physical card in watched and Transfer List.
        h=self.harness(3);h.ea.inventory=[auction(123,n=2000+i) for i in range(49)]
        h.ea.manual=[deepcopy(h.ea.inventory[0])];h.ea.manual[0]['bid_state']='highest'
        h.controller.step();self.assertEqual(len(h.calls('bid')),1)

    def test_4_shared_inventory_validity_expiry_and_external_invalidation(self):
        h=self.harness(3,spacing=0)
        def invalidate(c):
            if c['operation']=='bid':h.controller.journal.invalidate_inventory()
        h.ea.on_request=invalidate;h.controller.step()
        self.assertEqual(len(h.calls('bid')),1);self.assertEqual(len(h.calls('transfer_list')),1)
        self.assertEqual(len(h.metrics('INITIAL_SKIPPED')),2)
        h=self.harness(3,spacing=0)
        def age(c):
            if c['operation']=='bid':h.clock.value+=31
        h.ea.on_request=age;h.controller.step()
        self.assertEqual(len(h.calls('bid')),1)
        self.assertTrue(all(x['reason']=='INVENTORY_INVALID' for x in h.metrics('INITIAL_SKIPPED')))

    def test_5_selection_and_individual_intent_committed_before_every_bid(self):
        h=self.harness(3)
        # Ensure the inspection connection closes on Windows.
        from contextlib import closing
        def inspect_closed(c):
            if c['operation']=='bid':
                with closing(sqlite3.connect(h.store.path)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM c4_candidates WHERE batch_id=?',(c['params']['batch_id'],)).fetchone()[0],3)
                    self.assertEqual(db.execute('SELECT state FROM c4_attempts WHERE id=?',(c['id'],)).fetchone()[0],'INTENT')
                    self.assertEqual(db.execute('SELECT state FROM c4_commands WHERE id=?',(c['id'],)).fetchone()[0],'CLAIMED')
                self.assertFalse(h.store.db.in_transaction)
        h.ea.on_request=inspect_closed;h.controller.step();self.assertEqual(len(h.calls('bid')),3)
        with self.assertRaises(sqlite3.IntegrityError),h.store.db:
            h.store.db.execute("UPDATE c4_candidates SET body='{}'")
        h=self.harness(2)
        with patch.object(h.controller.journal,'intend',side_effect=sqlite3.OperationalError('disk full')):
            h.controller.step()
        self.assertFalse(h.calls('bid'))

    def test_5_expiry_and_price_change_never_increase_or_retry_mutation(self):
        h=self.harness(3,spacing=0)
        for r in h.ea.rows:r['expires']=61
        def advance(c):
            if c['operation']=='bid':h.clock.value+=62
        h.ea.on_request=advance;h.controller.step()
        self.assertEqual(len(h.calls('bid')),1)
        self.assertEqual(h.metrics('ACQUISITION')[-1]['expiry_misses'],2)
        h=self.harness(3);h.ea.bid_modes[h.ea.rows[0]['trade_id']]='price_change'
        h.controller.step();self.assertEqual(len(h.calls('bid')),3)
        self.assertEqual(h.attempts()[0]['state'],'REJECTED')
        self.assertTrue(all(c['command']['params']['amount']==150 for c in h.calls('bid')))

    def test_6_mixed_confirmed_highest_outbid_rejected_uncertain_and_immediate_reacquisition(self):
        h=self.harness(4);rows=h.ea.rows
        h.ea.bid_modes.update({rows[1]['trade_id']:'outbid',rows[2]['trade_id']:'reject',rows[3]['trade_id']:'timeout'})
        state=h.controller.step();self.assertEqual(state['phase'],'MANAGING');self.assertEqual(len(state['members']),2)
        self.assertEqual([v['state'] for v in h.attempts()],['ACKNOWLEDGED','ACKNOWLEDGED','REJECTED','UNKNOWN'])
        self.assertEqual({m['proof']['row']['bid_state'] for m in state['members']},{'highest','outbid'})
        self.assertFalse(state['global_ten_participation_guarantee']);self.assertEqual(len(state['potentially_untracked_effects']),1)
        for mode in ['reject','timeout','missing','empty']:
            h=self.harness(2)
            if mode=='empty':h.ea.rows=[]
            elif mode=='missing':h.ea.missing={r['trade_id'] for r in h.ea.rows}
            else:h.ea.bid_modes={r['trade_id']:mode for r in h.ea.rows}
            h.controller.run(steps=3)  # ACQUIRING, MAINTENANCE (no-op), ACQUIRING
            self.assertEqual(len(h.calls('balance')),2,mode)
            self.assertEqual(h.controller.status()['phase'],'MAINTENANCE')
            self.assertLessEqual(len(h.calls('bid')),2)
            # Only central pacing; no acquisition-specific timer or backoff.
            self.assertTrue(all(s<=h.config.request_spacing for s in h.clock.sleeps))

    def test_7_lifecycle_deadline_order_minimum_rebids_holds_and_no_management_credits(self):
        h=self.harness(3);h.controller.step();n=len(h.ea.calls)
        h.ea.rows[0].update(bid_state='outbid',current_bid=200,expires=120)
        h.ea.rows[1].update(bid_state='outbid',current_bid=200,expires=70)
        h.ea.rows[2].update(bid_state='highest',expires=1)
        h.controller.step()
        rebids=h.calls('bid')[3:]
        self.assertEqual([v['command']['params']['target']['trade_id'] for v in rebids],
                         [h.ea.rows[1]['trade_id'],h.ea.rows[0]['trade_id']])
        self.assertEqual([v['command']['params']['amount'] for v in rebids],[250,250])
        self.assertEqual(len(h.calls('balance')),1)
        self.assertEqual([v['command']['operation'] for v in h.ea.calls[n:] if v['command']['schema']==4],
                         ['status_batch','bid','bid','status_batch'])
        self.assertEqual(len(h.controller.journal.members()),3)
        # Zero timer is not terminal loss; even cap-exhausted auctions stay watched.
        h.ea.rows[0].update(bid_state='outbid',current_bid=10750,expires=0)
        h.ea.rows[1].update(bid_state='outbid',current_bid=10750,expires=100)
        h.ea.missing={h.ea.rows[2]['trade_id']}
        before=len(h.calls('bid'));h.controller.step();self.assertEqual(len(h.calls('bid')),before)
        self.assertEqual(len(h.controller.journal.members()),3)
        targets=h.calls('status_batch')[-1]['command']['params']['targets']
        self.assertEqual(len(targets),3)
        # Independent terminal rows settle all three; MAINTENANCE then runs before
        # the next credits read. No false loss is inferred from the omission.
        h.ea.missing.clear()
        for r in h.ea.rows:r.update(trade_state='closed',bid_state='outbid',expires=0)
        h.controller.step();self.assertEqual(h.controller.status()['phase'],'MAINTENANCE')
        self.assertEqual(len(h.calls('balance')),1)
        h.controller.step();h.controller.step();self.assertEqual(len(h.calls('balance')),2)
        self.assertEqual(len(h.controller.journal.members()),0)
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_members WHERE state='LOST'").fetchone()[0],3)

    def test_7_won_requires_exact_physical_paid_cost_and_accounted_handoff(self):
        proofs=[];phases=[]
        def handler(member,proof):
            phases.append(h.controller.journal.state()['phase']);proofs.append(proof);return True
        h=self.harness(2,win_handler=handler)
        h.controller.step()
        h.ea.rows[0].update(trade_state='closed',bid_state='highest',native_is_won=True,expires=0)
        h.ea.rows[1].update(trade_state='closed',bid_state='outbid',expires=0)
        h.controller.step();self.assertEqual(len(h.controller.journal.members()),1)
        self.assertEqual(h.controller.journal.members()[0]['state'],'PENDING_WIN');self.assertFalse(proofs)
        item=deepcopy(h.ea.rows[0]['item']);item['last_sale_price']=999;h.ea.owned=[item]
        h.controller.step();self.assertFalse(proofs)
        item['last_sale_price']=150
        for _ in range(6):
            if proofs:break
            h.controller.step()
        self.assertEqual(len(proofs),1);self.assertEqual(proofs[0]['paid'],150)
        self.assertEqual(phases,['MAINTENANCE'],'win handoff only in MAINTENANCE')
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_members WHERE state='WON_ACCOUNTED'").fetchone()[0],1)

    def test_8_uncertain_rebid_preserves_membership_later_writes_and_fresh_decisions(self):
        h=self.harness(2);h.controller.step()
        for r in h.ea.rows:r.update(bid_state='outbid',current_bid=200)
        h.ea.bid_modes[h.ea.rows[0]['trade_id']]='timeout'
        h.controller.step();self.assertEqual(len(h.controller.journal.members()),2)
        self.assertEqual(len(h.calls('bid')),4)
        self.assertEqual(h.attempts()[2]['state'],'UNKNOWN');self.assertEqual(h.attempts()[3]['state'],'ACKNOWLEDGED')
        # Same old decision cannot be disguised as a new command.
        old=h.calls('bid')[2]['command'];copy=deepcopy(old);copy['id']=h.ids()
        with self.assertRaisesRegex(ValueError,'possibly_sent'):h.store.enqueue(copy,h.store.peer)
        # A later independent status can justify the same minimum, with a new ID.
        h.ea.bid_modes.clear();h.controller.step()
        self.assertEqual(len(h.calls('bid')),5)
        self.assertEqual(h.calls('bid')[-1]['command']['params']['amount'],250)
        self.assertNotEqual(h.calls('bid')[-1]['command']['params']['status_read_id'],old['params']['status_read_id'])
        self.assertEqual(len(h.controller.journal.members()),2)
        self.assertEqual(len(h.calls('balance')),1)

    def test_8_restart_and_late_callbacks_never_replay_or_restore_abandoned_action(self):
        h=self.harness(2);h.ea.bid_modes={r['trade_id']:'timeout' for r in h.ea.rows}
        h.controller.step();commands=[v['command'] for v in h.calls('bid')]
        self.assertEqual(len(commands),2)
        # Reopen the actual SQLite file; submitted tombstones survive process state.
        h.store.close();h.store=ControllerStore(h.path/'controller.sqlite',write_authority=True,now=h.clock.now)
        h.store.host_epoch=h.ea.fences['host_epoch'];h.ea.store=h.store
        h.store.attach(dict(context=h.ea.context,fences=h.ea.fences))
        h.controller=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
        h.ea.bid_modes.clear();h.controller.step();self.assertEqual(len(h.calls('bid')),2)
        for c in commands:
            v=h.ea.controller(c,h.clock.now().isoformat())
            h.store.finish(h.store.peer,c['id'],v)
            h.controller.journal.outcome(c['id'],dict(outcome='ACKNOWLEDGED'))
        self.assertTrue(all(v['state']=='UNKNOWN' for v in h.attempts()))
        self.assertFalse(h.controller.journal.members())
        h.ea.rows.append(auction(123,15000,80));h.controller.step();h.controller.step()
        self.assertEqual(len(h.calls('bid')),3)

    def test_9_insufficient_funds_is_ordinary_outcome_without_stop_or_retry(self):
        h=self.harness(3);h.ea.bid_modes[h.ea.rows[0]['trade_id']]='funds'
        h.controller.step();self.assertEqual(h.controller.status()['lifecycle'],'RUNNING')
        self.assertEqual(len(h.calls('bid')),3);self.assertEqual(h.attempts()[0]['state'],'REJECTED')
        for r in h.ea.rows[1:]:r.update(bid_state='outbid',current_bid=200)
        h.ea.bid_modes[h.ea.rows[1]['trade_id']]='funds';h.controller.step()
        self.assertEqual(len(h.calls('bid')),5);self.assertEqual(len(h.controller.journal.members()),2)
        self.assertEqual(len(h.calls('balance')),1);self.assertEqual(h.attempts()[3]['state'],'REJECTED')

    def test_10_no_overlap_catchup_actor_or_legacy_policy_and_metrics(self):
        h=self.harness(10)
        def reentrant(c):
            with self.assertRaisesRegex(RuntimeError,'already_running'):h.controller.step()
        h.ea.on_request=reentrant
        with (patch('subprocess.Popen',side_effect=AssertionError('actor launch')),
              patch('multiprocessing.Process.start',side_effect=AssertionError('actor launch'))):
            h.controller.step()
            for r in h.ea.rows:r.update(bid_state='outbid',current_bid=200)
            h.controller.step()
        self.assertEqual(h.ea.max_active,1);self.assertEqual(len(h.calls('bid')),20)
        elapsed=h.metrics('CYCLE')[-1];self.assertGreater(elapsed['elapsed'],5);self.assertGreater(elapsed['missed_targets'],0)
        self.assertEqual(elapsed['target'],5)
        for metric in h.metrics('ACQUISITION'):
            self.assertGreater(metric['elapsed'],0);self.assertGreater(metric['burst_elapsed'],0)
            self.assertGreater(metric['handoff_elapsed'],0);self.assertIn('expiry_misses',metric)
        ea_requests=[m for m in h.executor.metrics if not m['local']]
        self.assertTrue(all(b['started']-a['started']>=2-1e-8 for a,b in zip(ea_requests,ea_requests[1:])))
        # A long cycle does not schedule a burst of overdue ticks.
        h.ea.duration=12;before=len(h.calls('status_batch'));h.controller.step()
        self.assertEqual(len(h.calls('status_batch')),before+1)
        h.ea.duration=.01;h.controller.step();h.controller.step()
        starts=[v['at'] for v in h.calls('status_batch')]
        self.assertGreaterEqual(starts[-1]-starts[-2],5-1e-8)
        self.assertTrue(all(v['phase']=='ACQUIRING' for v in h.calls('balance')))
        # Structural absence complements the behavioral request/phase traces.
        tree=ast.parse((ROOT/'fc_access/controller_v1/controller.py').read_text())
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any(m and any(v in m for v in ['actors_v1.actors','continuous_v1.runtime']) for m in imports))
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        self.assertFalse(names & {'Acquirer','Bidder','Broker','Timer','Popen','DRAINING','budget_allocator'})
        self.assertEqual(set(h.config.__dataclass_fields__),{'entry_threshold','request_spacing','cycle_target','inventory_max_age','maintenance_gap','margin','list_markup',
            'bands','max_auction_seconds','search_budget','throttle_pause','denial_retries','denial_pause','low_credit_hold'})

    def test_10_serial_executor_prevents_parallel_requests_even_for_concurrent_callers(self):
        h=self.harness(0);entered=threading.Event();release=threading.Event();out=[]
        original=h.ea.execute
        def held(c):
            if not entered.is_set():entered.set();release.wait(2)
            return original(c)
        h.executor.executor.execute=held
        # Avoid wrapping the same bound object recursively.
        commands=[h.adapter.envelope(h.ids(),'balance',{}) for _ in range(2)]
        def call(c):out.append(h.executor.execute(c))
        a=threading.Thread(target=call,args=(commands[0],));b=threading.Thread(target=call,args=(commands[1],))
        a.start();self.assertTrue(entered.wait(1));b.start();self.assertFalse(h.ea.calls)
        release.set();a.join(3);b.join(3)
        self.assertFalse(a.is_alive() or b.is_alive());self.assertEqual(len(out),2);self.assertEqual(h.ea.max_active,1)

    def test_shared_seam_cannot_dispatch_legacy_mutations(self):
        h=self.harness(1);h.controller.step()
        bid=deepcopy(h.calls('bid')[0]['command']);bid['schema']=2
        with self.assertRaises(ValueError):delivery_command(bid)
        for value in [-1,True,float('nan')]:
            with self.assertRaises(ValueError):ControllerConfig(request_spacing=value)

    def test_6_independently_terminal_initial_results_are_processed(self):
        h=self.harness(2)
        def terminal(c):
            if c['operation']=='status_batch' and len(h.calls('bid'))==2:
                for r in h.ea.rows:r.update(trade_state='closed',bid_state='outbid',expires=0)
        h.ea.on_request=terminal;state=h.controller.step()
        self.assertEqual(state['phase'],'MAINTENANCE');self.assertFalse(state['members'])
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_members WHERE state='LOST'").fetchone()[0],2)

    def test_8_discarded_uncertainties_are_visible_but_no_global_ten_reservation_gate(self):
        h=self.harness(10)
        h.ea.bid_modes={r['trade_id']:'timeout' for r in h.ea.rows}
        h.controller.step();self.assertEqual(len(h.calls('bid')),10)
        # Unknown submissions could have registered, while incomplete watchlist
        # traffic does not establish those effects. New exact targets may proceed.
        h.ea.rows=[auction(123,15000,n+100) for n in range(10)]
        h.ea.bid_modes.clear();h.controller.step();state=h.controller.step()
        self.assertEqual(len(h.calls('bid')),20);self.assertEqual(len(state['members']),10)
        self.assertEqual(len(state['potentially_untracked_effects']),10)
        self.assertFalse(state['global_ten_participation_guarantee'])

    def test_3_server_binds_immutable_selection_membership_capacity_and_inventory(self):
        h=self.harness(1);h.controller.step();old=h.calls('bid')[0]['command']
        member=h.controller.journal.members()[0]
        # Admission cannot be used to raise the stored cap on a fresh decision.
        h.ea.rows[0].update(current_bid=200,bid_state='outbid')
        status=h.adapter.status_batch(h.ids(),[member['target']])
        dec=h.ids();deadline=(stamp(status['network_at'])+timedelta(seconds=200)).isoformat()
        h.store.decide(dec,batch_id=member['batch_id'],status_read_id=status['command_id'],identity=member['target'],
            amount=250,minimum=250,cap=20000,deadline=deadline,kind='rebid')
        params=dict(old['params'],decision_id=dec,status_read_id=status['command_id'],amount=250,minimum=250,cap=20000,deadline=deadline)
        with self.assertRaisesRegex(ValueError,'selected_authority'):h.store.enqueue(h.adapter.envelope(h.ids(),'bid',params),h.store.peer)
        valid_dec=h.ids();h.store.decide(valid_dec,batch_id=member['batch_id'],status_read_id=status['command_id'],identity=member['target'],
            amount=250,minimum=250,cap=member['cap'],deadline=deadline,kind='rebid')
        missing_intent=dict(params,decision_id=valid_dec,cap=member['cap'])
        with self.assertRaisesRegex(ValueError,'individual_intent'):
            h.store.enqueue(h.adapter.envelope(h.ids(),'bid',missing_intent),h.store.peer)
        h.controller.journal.settle(member['target']['trade_id'],'LOST',{'read_id':status['command_id']})
        dec=h.ids();h.store.decide(dec,batch_id=member['batch_id'],status_read_id=status['command_id'],identity=member['target'],
            amount=250,minimum=250,cap=member['cap'],deadline=deadline,kind='rebid')
        params.update(decision_id=dec,cap=member['cap'])
        with self.assertRaisesRegex(ValueError,'membership'):h.store.enqueue(h.adapter.envelope(h.ids(),'bid',params),h.store.peer)

    def test_8_restart_preserves_confirmed_membership_and_abandons_unfinished_intent(self):
        h=self.harness(1);h.controller.step();member=h.controller.journal.members()[0]
        h.ea.rows[0].update(current_bid=200,bid_state='outbid')
        status=h.adapter.status_batch(h.ids(),[member['target']]);params=dict(h.calls('bid')[0]['command']['params'])
        cid=h.ids();params.update(status_read_id=status['command_id'],amount=250,minimum=250)
        h.controller.journal.intend(cid,member['batch_id'],member,'rebid',params)
        c=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
        self.assertEqual(c.status()['phase'],'MANAGING');self.assertEqual(len(c.status()['members']),1)
        self.assertEqual(h.attempts()[-1]['state'],'UNKNOWN')
        c.step();self.assertEqual(len(h.calls('bid')),2)

    def test_8_new_document_restores_exact_mappings_before_new_confirmed_decision(self):
        from fc_access.controller_v1.adapter import ControllerAdapter
        h=self.harness(1);h.controller.step();old=h.calls('bid')[0]['command']
        h.ea.rows[0].update(bid_state='outbid',current_bid=200)
        h.store.close();h.store=ControllerStore(h.path/'controller.sqlite',write_authority=True,now=h.clock.now)
        h.ea.store=h.store;h.ea.full.clear()
        h.ea.fences.update(host_epoch=h.store.host_epoch,document=h.ids(),epoch=2)
        h.ea.manual=deepcopy(h.ea.rows)
        h.adapter=ControllerAdapter(h.executor,context=h.ea.context,owner=h.ea.fences['owner'],epoch=2,now=h.clock.now)
        h.adapter.native.source='fixture'
        h.controller=Controller(h.store,h.adapter,h.cache,config=h.config,ids=h.ids,clock=h.clock.clock,sleep=h.clock.sleep)
        h.controller.step()
        self.assertEqual(len(h.calls('bid')),2);self.assertEqual(len(h.calls('watched')),2)
        self.assertEqual(len(h.calls('balance')),1)
        self.assertEqual(h.calls('bid')[-1]['command']['fences']['epoch'],2)
        with self.assertRaises(ValueError):h.store.enqueue(old,h.store.peer)

    def test_8_fault_during_handoff_retains_prior_membership_and_exposes_remaining_effects(self):
        h=self.harness(2);original=h.controller.journal.member;calls=[]
        def partial(*args,**kwargs):
            calls.append(1)
            if len(calls)>1:raise ValueError('synthetic_confirmation_fault')
            return original(*args,**kwargs)
        with patch.object(h.controller.journal,'member',side_effect=partial):state=h.controller.step()
        self.assertEqual(state['phase'],'MANAGING');self.assertEqual(len(state['members']),1)
        self.assertEqual(len(state['potentially_untracked_effects']),1)
        self.assertEqual([v['state'] for v in h.attempts()],['ACKNOWLEDGED','UNKNOWN'])
        h.controller.step();self.assertEqual(len(h.calls('bid')),2)


if __name__=='__main__':unittest.main(verbosity=2)
