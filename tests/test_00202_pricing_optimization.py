"""002-02 independent offline acceptance; no Edge/session/live gate required."""
from copy import deepcopy
from datetime import timedelta
import itertools
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
from fc_access.production_v1.contracts import parse_response, stamp, timing
from fc_access.production_v1.prices import PriceService, CardKey
from fc_access.production_v1.foundation import Foundation
from fc_access.sqlite_timing import TimedConnection
from native_price_fixture import FixturePriceAdapter, auction
from test_001d04_pricing import Acceptance as PricingRegressions
from profile_00202 import profile, scenario, TimedPage, Clock, CONTEXT, REPORT


class Optimization(unittest.TestCase):
    def service(self):
        adapter = FixturePriceAdapter(261855)
        adapter.calls = []
        original = adapter.price_helpers
        def helpers(cid, probes=()):
            adapter.calls.append(deepcopy(list(probes)))
            return original(cid, probes)
        adapter.price_helpers = helpers
        ids = itertools.count(1)
        service = PriceService(adapter, lambda:f'{next(ids):032x}')
        rules = service.load(key=CardKey(261855))
        adapter.calls.clear()
        return adapter, service, rules

    def test_c1_bulk_boundaries_dedup_and_repeated_ticks(self):
        a, s, rules = self.service()
        values = [1500+i*100 for i in range(70)]
        self.assertTrue(all(rules.legal_many(values+values).values()))
        self.assertEqual([len(batch) for batch in a.calls], [32,32,6,32,32,6])
        self.assertEqual(len([p for batch in a.calls for p in batch]),140)
        before = len(a.calls)
        for v in values:
            self.assertTrue(rules.legal(v))
            self.assertEqual(rules.below(v), v-100)
        self.assertEqual(len(a.calls),before)
        self.assertFalse(rules.legal_many([1510])[1510])
        self.assertEqual(rules.floor(1575),1500)
        with self.assertRaises(ValueError): rules.legal_many([True])

    def test_c1_memo_fenced_by_every_binding_component_and_cap_refresh(self):
        for section, name in [('context','account'),('context','persona'),('context','identity_namespace'),
                              ('context','game'),('context','platform'),('fences','owner'),('fences','epoch'),
                              ('fences','host_epoch'),('fences','worker_epoch'),('fences','document')]:
            with self.subTest(section=section,name=name):
                a,s,r = self.service()
                self.assertEqual(r.above(750),800)
                before = len(a.calls)
                original = deepcopy(getattr(a,section)[name])
                getattr(a,section)[name] = original+1 if type(original) is int else 'changed'
                with self.assertRaisesRegex(ValueError,'context_changed'): r.above(750)
                # Service itself also scopes cached helper outputs.
                self.assertEqual(s.helper('above',750),800)
                self.assertEqual(len(a.calls),before+1)
        a,s,r = self.service(); r.above(750)
        before = len(a.calls); a.source='native'
        self.assertEqual(s.helper('above',750),800)
        self.assertEqual(len(a.calls),before+1)
        a,s,r = self.service(); r.above(750)
        new = s.load(key=r.key)
        with self.assertRaisesRegex(ValueError,'caps_changed'): r.above(750)
        before=len(a.calls);new.above(750)
        self.assertEqual(len(a.calls),before+1)

    def test_c1_failed_helpers_do_not_seed_memo(self):
        a,s,r = self.service()
        with patch.object(a,'price_helpers',side_effect=TimeoutError('unavailable')):
            with self.assertRaises(TimeoutError):r.legal_many([1500,1600])
        self.assertEqual(s.memo,{})
        self.assertEqual(r.legal_many([1500,1600]),{1500:True,1600:True})
        self.assertTrue(all(len(batch)<=32 for batch in a.calls))

    def test_c1_binding_change_during_batch_discards_outputs(self):
        a,s,r=self.service()
        original=a.price_helpers
        def changed(cid,probes=()):
            response=original(cid,probes)
            a.fences['epoch']+=1
            return response
        with patch.object(a,'price_helpers',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'context_changed'):r.legal_many([1500,1600])
        self.assertEqual(s.memo,{})
        self.assertEqual(len(a.calls),1)

    def test_c1_illegal_duplicate_exclusion_counts_survive_batching(self):
        from fc_access.production_v1.pricing import select_comparables
        a,s,r=self.service()
        row=auction(261855,1510,100)
        rows=[dict(row=deepcopy(row),network_at=a.now().isoformat()) for _ in range(3)]
        accepted,excluded=select_comparables(rows,auction(261855,n=1),r,now=a.now())
        self.assertEqual(accepted,[])
        self.assertEqual(excluded,dict(illegal_bin=3))

    def test_c0_executed_page_distinguishes_wire_and_helper_timing_and_parser_negatives(self):
        run = subprocess.run(['node','tests/pricing_timing_checks.cjs'],cwd=ROOT,
                             capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)
        for record in json.loads(run.stdout):
            v,c=record['response'],record['command']
            self.assertIs(parse_response(v,c,now=stamp(v['freshness']['observed_at'])),v)
            for invalid in [dict(native_service_ms=True),dict(native_service_ms=-1),
                            dict(native_service_ms=1,ea_rtt_ms=2,native_helper_ms=0),
                            dict(native_service_ms=1,ea_rtt_ms=0),
                            dict(native_service_ms=1,ea_rtt_ms=0,native_helper_ms=float('nan'))]:
                bad=deepcopy(v);bad['timing']=invalid
                with self.assertRaisesRegex(ValueError,'invalid_timing'):
                    parse_response(bad,c,now=stamp(v['freshness']['observed_at']))
        # Historical responses are usable but never presented as measured EA RTT.
        self.assertEqual(timing(dict(native_service_ms=7)),dict(native_service_ms=7))

    def test_c0_sqlite_includes_fetch_commit_and_failures(self):
        db=sqlite3.connect(':memory:',factory=TimedConnection)
        self.addCleanup(db.close)
        with patch('fc_access.sqlite_timing.time.perf_counter',side_effect=itertools.count()):
            db.execute('CREATE TABLE probe(value)')
            with db: db.executemany('INSERT INTO probe VALUES(?)',[(1,),(2,)])
            self.assertEqual(db.sqlite_ms,3000)
            self.assertEqual(db.execute('SELECT * FROM probe').fetchall(),[(1,),(2,)])
            self.assertEqual(db.sqlite_ms,5000)
            with self.assertRaises(sqlite3.OperationalError):db.execute('invalid sql')
            self.assertEqual(db.sqlite_ms,6000)

    def test_c0_c4_foundation_persists_all_metrics_and_keeps_diagnostics_enabled(self):
        with patch('socket.socket',side_effect=AssertionError('offline only')):
            out=scenario()
        self.assertEqual(out['decision'],dict(action='BID',reason='ELIGIBLE',cap=900,amount=150))
        self.assertEqual(out['bid_calls'],0)
        m=out['metrics']
        self.assertEqual(out['persisted_executor_events'],m['commands'])
        self.assertEqual(m['ea_rtt_ms'],600)
        self.assertAlmostEqual(m['browser_bridge_ms'],m['commands']*50)
        self.assertAlmostEqual(m['native_helper_ms'],out['helper_probes']*.2)
        self.assertGreater(m['sqlite_ms'],0)
        self.assertGreater(m['diagnostic_logging_ms'],0)
        self.assertGreater(m['diagnostic_sqlite_ms'],0)
        self.assertGreaterEqual(m['diagnostic_logging_ms'],m['diagnostic_sqlite_ms'])

    def test_c4_slow_valuation_retains_freshness_and_never_admits_stale(self):
        class SlowPage(TimedPage):
            def execute(self,c):
                r=super().execute(c)
                if c['operation']=='search':self.clock.sleep(16)
                return r
        with tempfile.TemporaryDirectory() as directory:
            clock=Clock();page=SlowPage(directory,clock)
            f=Foundation(page,context=CONTEXT,journal_path=Path(directory)/'journal.sqlite3',
                         fixture=True,now=clock.now,clock=clock.monotonic,sleep=clock.sleep)
            try:
                page.candidate['starting_bid']=150;page.watched=[page.candidate]
                watched=f.read('watched');funds=f.read('balance')
                d=f.admit(watched,page.candidate['trade_id'],funds)
                self.assertEqual((d['action'],d['reason']),('HOLD','STALE'))
                self.assertTrue(d['quote']['completed'])
                self.assertEqual(f.registry.current()['queued'],[])
                self.assertEqual(page.bid_calls,0)
            finally:f.close();page.close()

    def test_c0_queue_wait_and_legacy_unknown_timings(self):
        from foundation_fixture import create
        with tempfile.TemporaryDirectory() as directory:
            f,page,clock=create(directory,interval=.2)
            try:
                f.read('balance');f.read('balance')
                self.assertGreater(f.executor.metrics[-1]['queue_ms'],100)
                summary=f.timing_summary()
                self.assertIsNone(summary['ea_rtt_ms'])
                self.assertIsNone(summary['native_helper_ms'])
                self.assertIsNone(summary['transport_sqlite_ms'])
            finally:f.close();page.close()

    def test_c0_real_loopback_service_reports_sqlite_separately(self):
        import threading
        import http.client
        from test_001d02_contract import make_command, reply
        from fc_access.production_v1.server import Server
        from fc_access.production_v1.executor import EdgeExecutor
        with tempfile.TemporaryDirectory() as directory:
            server=Server(Path(directory)/'transport.sqlite3',0,wait_seconds=2,poll_seconds=.5)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            executor=EdgeExecutor(server.server_port)
            c=make_command(host=server.store.host_epoch)
            peer=dict(context=c['context'],fences=c['fences'])
            def post(path,value):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                try:
                    conn.request('POST',path,json.dumps(value),{'Content-Type':'application/json','Origin':server.extension_origin})
                    r=conn.getresponse();data=json.loads(r.read())
                    self.assertEqual(r.status,200,data)
                    return data
                finally:conn.close()
            errors=[]
            def worker():
                try:
                    delivered=post('/next',peer)
                    self.assertEqual(delivered,c)
                    post('/result',dict(peer=peer,id=c['id'],result=reply(c)))
                except BaseException as e:errors.append(e)
            try:
                executor.request('/activate',dict(context=c['context'],owner=c['fences']['owner'],epoch=1))
                post('/hello',dict(schema=2,peer=peer))
                worker_thread=threading.Thread(target=worker);worker_thread.start()
                response=executor.execute(c)
                worker_thread.join(3)
                self.assertFalse(worker_thread.is_alive())
                self.assertEqual(errors,[])
                self.assertEqual(response['command_id'],c['id'])
                self.assertGreater(executor.last_sqlite_ms,0)
                self.assertLessEqual(executor.last_sqlite_ms,server.store.db.sqlite_ms)
                # Timing travels in a header; the validated EA response is intact.
                self.assertEqual(response['timing'],dict(native_service_ms=12))
            finally:
                server.shutdown();server.server_close();thread.join(3);server.store.db.close()

    def test_c0_c1_c2_c4_offline_artifact_recomputes_before_live_gate(self):
        stored=json.loads(REPORT.read_text())
        with patch('socket.socket',side_effect=AssertionError('no live gate')):
            actual=profile()
        for doc in (stored,actual):
            self.assertEqual((doc['task'],doc['mode'],doc['live_gate_executed'],doc['live_requests']),
                             ('002-02','OFFLINE_CONTROLLED_CLOCK',False,0))
            before,after=doc['baseline'],doc['optimized']
            self.assertEqual(before['decision'],after['decision'])
            self.assertEqual(before['resale_price'],after['resale_price'])
            self.assertEqual(before['pricing_queries'],after['pricing_queries'])
            self.assertEqual(len(after['pricing_queries']),2)
            self.assertEqual(after['pricing_queries'][1]['max_buy'],1500)
            self.assertLess(after['helper_commands'],before['helper_commands']/5)
            self.assertLess(after['elapsed_ms'],before['elapsed_ms']/5)
            self.assertGreater(after['max_batch'],1)
            self.assertLessEqual(after['max_batch'],32)
            self.assertEqual(doc['historical_live']['helper_commands'],220)
            self.assertIsNone(doc['historical_live']['ea_rtt_ms'])
        for key in ('helper_commands','helper_probes','pricing_queries','decision','resale_price'):
            self.assertEqual(stored['optimized'][key],actual['optimized'][key])


if __name__=='__main__':
    # Retain all estimator/cache policy regressions as independently executable
    # acceptance, including 261855/1500 and both second-page result branches.
    unittest.main(verbosity=2)
