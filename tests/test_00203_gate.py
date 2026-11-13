"""Offline behavioral tests for every gate contract; never consumes a live gate."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1 import gate_00203 as gate
from fc_access.production_v1.contracts import Search, parse_response
from fc_access.production_v1.foundation import Foundation
from profile_00202 import TimedPage, Clock, CONTEXT


class Gate(unittest.TestCase):
    def scenario(self, directory, *, slow=False, missing=False, stale=False, failure=False, authorization=None):
        clock = Clock(); page = TimedPage(directory, clock)
        page.candidate['starting_bid'] = 150
        path = Path(directory)/'gate.json'
        w = gate.Window(path, clock=lambda: int(clock.monotonic()*1e9), authorization=authorization)
        recorder = gate.ReadOnlyGateExecutor(w)
        recorder.attach, recorder.ownership_epoch = page.attach, page.ownership_epoch
        def deliver(c):
            if failure and c['operation'] == 'caps':
                raise TimeoutError('test_native_failure')
            r = page.execute(c)
            r['freshness']['source'] = 'native'
            if slow and c['operation'] == 'search' and c['params']['purpose'] == 'pricing':
                clock.sleep(15)
            if missing and w.state['stage'] == 'FRESH_FINAL_ADMISSION' and c['operation'] == 'search':
                r['result']['auctions'] = []
            if stale and w.state['stage'] == 'FRESH_FINAL_ADMISSION' and c['operation'] == 'balance':
                clock.sleep(31)
            recorder.last_sqlite_ms = 0
            return r
        with patch.object(gate.EdgeExecutor, 'execute', side_effect=deliver), patch.object(gate, 'parse_response',
                side_effect=lambda r,c,**kw: parse_response(r,c,**(dict(now=clock.now()) | kw))):
            f = Foundation(recorder, context=CONTEXT, journal_path=Path(directory)/'journal.sqlite3',
                           now=clock.now, clock=clock.monotonic, sleep=clock.sleep)
            try:
                s = w.state
                s.update(health_before=dict(service='fc-production-v1',attached=True,mutations_enabled=False),
                    context=CONTEXT, fences=deepcopy(f.adapter.fences),
                    desktop=dict(official_tab=True,foreground_verified=True,edge_control_verified=True),
                    cache_inventory=[dict(path=str(gate.CACHE.relative_to(ROOT)), rows=[],exact_key_rows=[])], stage='DISCOVERY')
                discovery = f.read('search', Search.discovery(123).params())
                try:
                    gate.evaluate_window(f,w,discovery,page.candidate)
                    gate.admission_proof(s)
                    s.update(status='PASS',hard_stop=False,dependent_tasks_allowed=True)
                    s['evidence_sha256'] = gate.digest(s); w.save()
                except Exception as e:
                    w.stop(type(e).__name__)
                return deepcopy(s), len(page.calls), page.bid_calls
            finally:
                f.close(); page.close()

    def test_c0_c1_c2_real_foundation_contract_and_independent_assessor(self):
        with tempfile.TemporaryDirectory() as d:
            s, calls, bids = self.scenario(d)
            self.assertEqual(s['status'], 'PASS', s.get('reason'))
            self.assertEqual(gate.require_pass(Path(d)/'gate.json')['decision'], 'BID/ELIGIBLE')
            self.assertLess(s['elapsed_ns'],gate.LIMIT_NS)
            self.assertEqual(bids,0)
            self.assertEqual(s['uncached_quote']['evidence']['price_searches'],2)
            self.assertFalse(s['uncached_quote']['evidence']['cache_hit'])
            self.assertTrue(s['decision']['quote']['evidence']['cache_hit'])
            self.assertEqual([e['miss'] for e in s['cache_reads']],[True,False])
            self.assertGreater(calls,7)
            self.assertGreater(s['timing_breakdown']['diagnostic_logging_ms'],0)

    def test_c0_c1_c2_independent_evidence_negative_cases(self):
        with tempfile.TemporaryDirectory() as d:
            good,_,_ = self.scenario(d)
            self.assertEqual(good['status'],'PASS',good.get('reason'))
            def network(s):
                e=next(e for e in s['operations'] if e['command']['operation']=='search' and e['command']['params']['purpose']=='pricing')
                e['response']['result']['network'][0]['query']['maxb']=1
                e['evidence_sha256']=gate.digest(dict(command=e['command'],response=e['response']))
            mutations = {
                'exact_30_seconds':lambda s:s.update(final_decision_ns=s['valuation_start_ns']+gate.LIMIT_NS,elapsed_ns=gate.LIMIT_NS),
                'over_30_seconds':lambda s:s.update(final_decision_ns=s['valuation_start_ns']+gate.LIMIT_NS+1,elapsed_ns=gate.LIMIT_NS+1),
                'warm_cache':lambda s:s['cache_reads'][0].update(miss=False),
                'cached_before_gate':lambda s:s['cache_inventory'][0].update(exact_key_rows=[[1]]),
                'missing_pricing_get':lambda s:s['operations'].pop(next(i for i,e in enumerate(s['operations']) if e['command']['operation']=='search' and e['command']['params']['purpose']=='pricing')),
                'wrong_actual_wire_query':network,
                'stale_hold':lambda s:s['decision'].update(action='HOLD',reason='STALE'),
                'unknown_decision':lambda s:s['decision'].update(action='UNKNOWN',reason='UNKNOWN'),
                'simulated_source':lambda s:s['uncached_quote']['evidence'].update(source='fixture'),
                'not_eligible':lambda s:s['decision'].update(amount=10000),
                'wrong_exact_version':lambda s:s['candidate']['item'].update(definition_id=321),
                'missing_fresh_recheck':lambda s:s.update(final_status_read_id=s['discovery_read_id']),
                'stale_final_time':lambda s:s.update(final_decision_at='2040-01-01T00:00:00+00:00'),
                'missing_diagnostics':lambda s:s['registry_events'].clear(),
                'missing_split':lambda s:s['timing_breakdown'].update(ea_rtt_ms=None),
                'missing_metrics':lambda s:s['executor_metrics'].pop(),
                'bid_dispatched':lambda s:s.update(journal_bid_commands=1),
                'response_tampered':lambda s:s['operations'][0]['response']['result'].update(success=False),
                'wrong_platform':lambda s:s['context'].update(platform='ps5'),
                'not_official':lambda s:s['desktop'].update(official_tab=False),
            }
            for name,change in mutations.items():
                with self.subTest(name=name):
                    s=deepcopy(good); change(s)
                    with self.assertRaises((ValueError,KeyError,TypeError)):
                        gate.admission_proof(s)

    def test_c3_c4_failures_stop_without_more_dispatches_and_no_rerun(self):
        for fault in ('slow','missing','stale','failure'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as d:
                s, count, bids = self.scenario(d,**{fault:True})
                self.assertEqual(s['status'],'FAILURE/BLOCKED')
                self.assertTrue(s['hard_stop']); self.assertFalse(s['dependent_tasks_allowed'])
                self.assertFalse(s['automatic_repairs']); self.assertFalse(s['automatic_reruns'])
                self.assertEqual(bids,0)
                w=object.__new__(gate.Window); w.state=s; w.clock=lambda:s['stopped_ns']
                with self.assertRaisesRegex(ValueError,'gate_stopped'):
                    w.check()
                path=Path(d)/'gate.json'
                with self.assertRaises(FileExistsError): gate.Window(path)
                with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'): gate.require_pass(path)
                pricing=[e for e in s['operations'] if e['command']['operation']=='search' and e['command']['params']['purpose']=='pricing']
                self.assertLessEqual(len(pricing),2)
                if fault=='slow':
                    self.assertEqual(len(pricing),2)
                    self.assertFalse(any(e['stage']=='FRESH_FINAL_ADMISSION' for e in s['operations']))
                if fault=='missing':
                    self.assertFalse(any(e['command']['operation']=='balance' for e in s['operations']))
                if fault=='failure':
                    self.assertFalse(any(e['command']['operation']=='search' and e['command']['params']['purpose']=='pricing'
                                         for e in s['operations']))

    def test_c1_c3_strict_monotonic_deadline_checked_before_any_delivery(self):
        with tempfile.TemporaryDirectory() as d:
            instant=[100]
            w=gate.Window(Path(d)/'gate.json',clock=lambda:instant[0])
            w.state['valuation_start_ns']=100
            instant[0]=100+gate.LIMIT_NS-1; w.check()
            instant[0]+=1
            with self.assertRaisesRegex(TimeoutError,'hard_30_second'): w.check()
            recorder=gate.ReadOnlyGateExecutor(w)
            with patch.object(gate.EdgeExecutor,'execute',side_effect=AssertionError('must not dispatch')):
                with self.assertRaises(TimeoutError): recorder.execute({'operation':'balance'})

    def test_c2_read_only_allowlist_and_finite_pricing_budget(self):
        with tempfile.TemporaryDirectory() as d:
            w=gate.Window(Path(d)/'gate.json')
            recorder=gate.ReadOnlyGateExecutor(w)
            for op in ('bid','bulk_clear_sold','bulk_relist','transfer_list','watched'):
                with self.assertRaisesRegex(ValueError,'read_only_allowlist'):
                    recorder.execute(dict(operation=op))
            w.state['stage']='UNCACHED_VALUATION'
            c=dict(operation='search',params=Search.pricing(123).params())
            w.state['operations']=[dict(command=c),dict(command=c)]
            with self.assertRaisesRegex(ValueError,'two_pricing_search_budget'): recorder.execute(c)

    def test_c4_only_evidenced_pass_permits_dependencies_and_crash_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'gate.json'; gate.Window(path)
            with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'): gate.require_pass(path)
            with patch.object(gate,'CHECKPOINT',path), patch.object(gate.EdgeExecutor,'request',side_effect=AssertionError('no replay')):
                with self.assertRaises(FileExistsError): gate.run(desktop={})
        with tempfile.TemporaryDirectory() as d:
            s,_,_=self.scenario(d); path=Path(d)/'gate.json'
            s['decision']['amount']+=50
            path.write_text(json.dumps(s))
            with self.assertRaisesRegex(ValueError,'sealed_gate_evidence_changed'): gate.require_pass(path)

    def test_c3_initial_empty_discovery_stops_and_top_level_never_retries(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'gate.json'
            reads=[]
            def read(*args):
                reads.append(args)
                return dict(result=dict(auctions=[]))
            fake=SimpleNamespace(adapter=SimpleNamespace(fences={}),read=read,close=lambda:None)
            health=dict(attached=True,mutations_enabled=False,owner=dict(context=CONTEXT,owner='e'*32))
            with patch.object(gate,'CHECKPOINT',path), patch.object(gate.EdgeExecutor,'request',return_value=health),\
                    patch.object(gate,'Foundation',return_value=fake),\
                    patch.object(gate,'cache_snapshot',return_value=[dict(rows=[],exact_key_rows=[])]):
                result=gate.run(desktop={})
                self.assertEqual(result['status'],'FAILURE/BLOCKED')
                self.assertEqual(result['reason'],'no_real_eligible_candidate_single_discovery')
                self.assertEqual(len(reads),1)
                with self.assertRaises(FileExistsError): gate.run(desktop={})
                self.assertEqual(len(reads),1)


if __name__=='__main__':
    unittest.main()
