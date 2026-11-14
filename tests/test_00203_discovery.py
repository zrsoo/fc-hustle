"""Offline bounded cross-version discovery and third-attempt gate contracts."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1 import gate_00203 as gate
from fc_access.production_v1 import gate_00203_discovery as third
from fc_access.production_v1.contracts import Search,parse_response,command
from fc_access.production_v1.foundation import Foundation
from profile_00202 import TimedPage,Clock,CONTEXT


class ThirdAttempt(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        patcher=patch.object(gate,'FOURTH_CHECKPOINT',Path(temporary.name)/'absent-fourth.json')
        patcher.start();self.addCleanup(patcher.stop)
        fifth=patch.object(gate,'FIFTH_CHECKPOINT',Path(temporary.name)/'absent-fifth.json')
        fifth.start();self.addCleanup(fifth.stop)
        sixth=patch.object(gate,'SIXTH_CHECKPOINT',Path(temporary.name)/'absent-sixth.json')
        sixth.start();self.addCleanup(sixth.stop)

    def scenario(self,directory,*,slow=False,empty=False,fourth=False,fifth=False,sixth=False):
        clock=Clock();page=TimedPage(directory,clock);page.candidate['starting_bid']=150
        w=gate.Window(Path(directory)/'gate.json',clock=lambda:int(clock.monotonic()*1e9),
                      authorization=gate.sixth_authorization() if sixth else gate.fifth_authorization() if fifth else gate.fourth_authorization() if fourth else gate.third_authorization(),
                      attempt_id=gate.SIXTH_ATTEMPT if sixth else gate.FIFTH_ATTEMPT if fifth else gate.FOURTH_ATTEMPT if fourth else gate.THIRD_ATTEMPT)
        recorder=gate.ReadOnlyGateExecutor(w)
        recorder.attach,recorder.ownership_epoch=page.attach,page.ownership_epoch
        def deliver(c):
            r=page.execute(c);r['freshness']['source']='native'
            if empty and 'definition_id' not in c['params']:r['result']['auctions']=[]
            if slow and c['operation']=='search' and c['params']['purpose']=='pricing':clock.sleep(30)
            recorder.last_sqlite_ms=0
            return r
        cache=[dict(path=str(gate.CACHE.relative_to(gate.ROOT)),rows=[],exact_key_rows=[])]
        with patch.object(gate.EdgeExecutor,'execute',side_effect=deliver),\
             patch.object(gate,'parse_response',side_effect=lambda r,c,**kw:parse_response(r,c,**(dict(now=clock.now())|kw))),\
             patch.object(gate,'cache_snapshot',return_value=cache):
            f=Foundation(recorder,context=CONTEXT,journal_path=Path(directory)/'journal.sqlite3',now=clock.now,
                         clock=clock.monotonic,sleep=clock.sleep)
            try:
                w.state.update(health_before=dict(service='fc-production-v1',attached=True,mutations_enabled=False),
                    context=CONTEXT,fences=deepcopy(f.adapter.fences),desktop=dict(official_tab=True,foreground_verified=True,edge_control_verified=True))
                try:
                    if fourth or fifth or sixth:
                        w.state['stage']='AUTHENTICATION'
                        auth=f.read('balance');w.state['authenticated_read_id']=auth['command_id']
                    discovery,candidate=third.discover(f,w)
                    gate.evaluate_window(f,w,discovery,candidate);gate.admission_proof(w.state)
                    w.state.update(status='PASS',hard_stop=False,dependent_tasks_allowed=True)
                    w.state['evidence_sha256']=gate.digest(w.state);w.save()
                except Exception as e:w.stop(str(e))
                return deepcopy(w.state),page.bid_calls
            finally:f.close();page.close()

    def test_sixth_uses_separate_consumed_slot_and_preserves_prior_failure_chain(self):
        with patch.object(gate,'FOURTH_CHECKPOINT',gate.OUT/'attempts'/gate.FOURTH_ATTEMPT/'gate.json'),\
             patch.object(gate,'FIFTH_CHECKPOINT',gate.OUT/'attempts'/gate.FIFTH_ATTEMPT/'gate.json'):
            for slow in (False,True):
                with self.subTest(slow=slow),tempfile.TemporaryDirectory() as d:
                    s,bids=self.scenario(d,sixth=True,slow=slow)
                    self.assertEqual(s['attempt'],6);self.assertEqual(bids,0)
                    self.assertEqual(s['status'],'FAILURE/BLOCKED' if slow else 'PASS',s.get('reason'))
                    self.assertEqual(s['execution_budget']['ea_GETs'],16)
                    if not slow:self.assertEqual(gate.require_pass(Path(d)/'gate.json')['pricing_GETs'],2)
                    with self.assertRaises(FileExistsError):gate.Window(Path(d)/'gate.json')

    def test_fifth_single_authorized_gate_real_foundation_and_failure_stop(self):
        with patch.object(gate,'FOURTH_CHECKPOINT',gate.OUT/'attempts'/gate.FOURTH_ATTEMPT/'gate.json'):
            for slow in (False,True):
                with self.subTest(slow=slow),tempfile.TemporaryDirectory() as d:
                    s,bids=self.scenario(d,fifth=True,slow=slow)
                    self.assertEqual(s['attempt'],5);self.assertEqual(bids,0)
                    self.assertEqual(s['status'],'FAILURE/BLOCKED' if slow else 'PASS',s.get('reason'))
                    self.assertIn('valuation_start_ns',s)
                    if slow:
                        with self.assertRaises(ValueError):gate.require_pass(Path(d)/'gate.json')
                    else:self.assertEqual(gate.require_pass(Path(d)/'gate.json')['pricing_GETs'],2)
                    with self.assertRaises(FileExistsError):gate.Window(Path(d)/'gate.json')

    def test_fourth_requires_actual_authenticated_read_before_discovery_and_timed_valuation(self):
        with tempfile.TemporaryDirectory() as d:
            s,bids=self.scenario(d,fourth=True)
            self.assertEqual(s['status'],'PASS',s.get('reason'));self.assertEqual(bids,0)
            self.assertEqual(gate.require_pass(Path(d)/'gate.json')['pricing_GETs'],2)
            self.assertEqual(s['operations'][0]['command']['operation'],'balance')
            self.assertEqual(s['operations'][0]['stage'],'AUTHENTICATION')
            bad=deepcopy(s);bad['authenticated_read_id']=s['discovery_read_id']
            with self.assertRaises(ValueError):gate.admission_proof(bad)
            self.assertEqual(s['execution_budget']['ea_GETs'],10)

    def test_fourth_preserves_three_failures_and_dependency_selection(self):
        authority=gate.fourth_authorization()
        with tempfile.TemporaryDirectory() as d,patch.object(gate,'FOURTH_CHECKPOINT',Path(d)/'gate.json'):
            w=gate.Window(gate.FOURTH_CHECKPOINT,authorization=authority,attempt_id=gate.FOURTH_ATTEMPT)
            self.assertEqual(gate.selected_checkpoint(),w.path)
            with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'):gate.require_pass()
            with self.assertRaises(FileExistsError):gate.Window(w.path)
            bad=deepcopy(w.state);bad['authorization']['third_capture_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'wrong_gate_attempt_authorization'):gate.validate_attempt(bad)

    def test_offline_windows_selector_chooses_unique_intended_window_and_rejects_ambiguity(self):
        import subprocess
        result=subprocess.run(['powershell','-NoProfile','-File','tests/desktop_window_checks.ps1'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_foundation_third_attempt_pass_and_negative_discovery_proof(self):
        with tempfile.TemporaryDirectory() as d:
            state,bids=self.scenario(d)
            self.assertEqual(state['status'],'PASS',state.get('reason'));self.assertEqual(bids,0)
            self.assertEqual(gate.require_pass(Path(d)/'gate.json')['pricing_GETs'],2)
            self.assertEqual(state['operations'][0]['command']['params'],Search.discovery().params())
            self.assertEqual(state['operations'][0]['response']['result']['network'][0]['query'],dict(start=0,num=21,macr=1000,minb=11000))
            for change in (lambda s:s['selection'].update(trade_id='trade:'+'f'*24),
                           lambda s:s.update(discovery_cache_checks=[]),lambda s:s.update(discovery_deadline_ns=0),
                           lambda s:s['operations'][0].update(stage='WARMUP')):
                bad=deepcopy(state);change(bad)
                with self.assertRaises(ValueError):gate.admission_proof(bad)

    def test_no_candidate_three_searches_and_no_valuation_or_warmup(self):
        with tempfile.TemporaryDirectory() as d:
            s,bids=self.scenario(d,empty=True)
            self.assertEqual(s['reason'],'bounded_discovery_exhausted_no_uncached_eligible_auction')
            self.assertEqual(len(s['operations']),3);self.assertNotIn('valuation_start_ns',s)
            self.assertTrue(all(e['command']['params']==Search.discovery().params() for e in s['operations']))
            self.assertEqual(bids,0)

    def test_valuation_failure_stops_no_more_discovery_no_second_valuation_or_retry(self):
        with tempfile.TemporaryDirectory() as d:
            s,bids=self.scenario(d,slow=True)
            self.assertEqual(s['status'],'FAILURE/BLOCKED');self.assertIn('valuation_start_ns',s)
            self.assertGreaterEqual(s['elapsed_ns'],gate.LIMIT_NS);self.assertEqual(bids,0)
            self.assertEqual(sum(e['stage']=='BOUNDED_DISCOVERY' for e in s['operations']),1)
            self.assertEqual(sum(e['command']['operation']=='search' and e['command']['params']['purpose']=='pricing' for e in s['operations']),1)
            with self.assertRaises(FileExistsError):gate.Window(Path(d)/'gate.json')
            with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'):gate.require_pass(Path(d)/'gate.json')

    def test_cached_and_unavailable_versions_are_skipped_without_pricing(self):
        from types import SimpleNamespace
        from native_price_fixture import auction
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc)
        r1=auction(123,11000,1);r1['starting_bid']=150
        r2=auction(124,12000,2);r2['starting_bid']=200
        r3=auction(125,13000,3);r3.update(expires=1)
        response=dict(command_id='a'*32,freshness=dict(network_at=now.isoformat()),result=dict(auctions=[r1,r2,r3]))
        with tempfile.TemporaryDirectory() as d:
            w=gate.Window(Path(d)/'gate.json',authorization=gate.third_authorization(),attempt_id=gate.THIRD_ATTEMPT)
            w.state['context']=CONTEXT
            f=SimpleNamespace(now=lambda:now,read=lambda *args:response)
            def cache(root,ctx,definition):return [dict(path='fixture',rows=[],exact_key_rows=[[1]] if definition==123 else [])]
            with patch.object(gate,'cache_snapshot',side_effect=cache):
                _,chosen=third.discover(f,w)
            self.assertEqual(chosen['item']['definition_id'],124)
            self.assertEqual(len(w.state['discovery_reads']),1);self.assertNotIn('valuation_start_ns',w.state)

    def test_immutable_previous_failures_and_latest_dependency_selection(self):
        authority=gate.third_authorization();before=[p.read_bytes() for p in (gate.CHECKPOINT,gate.REMEDIATION_CHECKPOINT)]
        with tempfile.TemporaryDirectory() as d,patch.object(gate,'THIRD_CHECKPOINT',Path(d)/'gate.json'):
            w=gate.Window(gate.THIRD_CHECKPOINT,authorization=authority,attempt_id=gate.THIRD_ATTEMPT)
            self.assertEqual(gate.selected_checkpoint(),w.path);self.assertEqual(w.state['attempt'],3)
            with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'):gate.require_pass()
            bad=deepcopy(w.state);bad['authorization']['second_capture_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'wrong_gate_attempt_authorization'):gate.validate_attempt(bad)
        self.assertEqual(before,[p.read_bytes() for p in (gate.CHECKPOINT,gate.REMEDIATION_CHECKPOINT)])

    def test_discovery_filters_and_exact_pricing_identity_remain_strict(self):
        self.assertNotIn('definition_id',Search.discovery().params())
        for build in (lambda:Search.pricing(None),lambda:Search('discovery',None,max_bid=999,min_buy=11000),
                      lambda:Search('discovery',None,max_bid=1000,min_buy=10500),lambda:Search.discovery(0)):
            with self.assertRaises((ValueError,TypeError)):build()


if __name__=='__main__':unittest.main(verbosity=2)
