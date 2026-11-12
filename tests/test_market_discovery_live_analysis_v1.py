"""Offline analysis regressions. Fixture results are never promoted to live data."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
import json
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.market_discovery_live_v1.run import DurableRunner
from experiments.market_discovery_live_v1.analysis import analyze, indicative, diagnostic_revalidation
from experiments.market_discovery_live_v1.passive import unseen
from experiments.market_discovery.replay import FixtureClock, FixtureTransport
from experiments.market_discovery_live_v1.validate import validate
from experiments.market_discovery_live_v1.report import write


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clock=FixtureClock()
        with tempfile.TemporaryDirectory() as directory:
            with patch('builtins.print'):
                cls.benchmark=DurableRunner(FixtureTransport(clock,opportunity=True),directory,
                    clock=clock,mode='SIMULATED').complete_protocol()

    def test_observation_minutes_use_allocated_windows_not_interleaved_wall_span(self):
        result=analyze(self.benchmark)
        self.assertEqual(result['data_lineage'],'SIMULATED')
        for arm in result['arms'].values():
            self.assertEqual(arm['allocated_observation_seconds'],900)
            self.assertEqual(arm['EA_requests'],24)
            self.assertAlmostEqual(arm['auctions_per_observation_minute'],arm['unique_auctions']/15)
            self.assertIsNotNone(arm['latency']['native_service_ms']['p95_ms'])

    def test_no_observation_is_unknown_yield_and_small_samples_have_no_latency_p95(self):
        run=deepcopy(self.benchmark)
        run['records']=[r for r in run['records'] if r['window']==0]
        run['window_intervals']=run['window_intervals'][:1]
        run['windows']=run['windows'][:1]
        result=analyze(run)
        self.assertTrue(all(v is None for v in result['arms']['C']['indicative_modeled_candidates_by_X'].values()))
        self.assertIsNone(result['arms']['A']['latency']['native_service_ms']['p95_ms'])
        self.assertIsNone(result['hourly_yield_extrapolation'])

    def test_hypothetical_rules_never_become_executable_or_realized_profits(self):
        result=analyze(self.benchmark)
        self.assertEqual(result['pricing_lineage']['rules'],'HYPOTHETICAL_NOT_EXECUTABLE')
        for arm in result['arms'].values():
            self.assertEqual(arm['verified_executable_opportunities_observed'],0)
            self.assertTrue(all(v is None for v in arm['fully_validated_executable_opportunities_by_X'].values()))
            self.assertIsNone(arm['realized_profit'])
            self.assertIsNone(arm['profitable_executable_revalidation_rate'])

    def test_candidate_is_excluded_and_future_records_cannot_price_old_observation(self):
        record=deepcopy(self.benchmark['records'][0])
        record['result']['auctions']=record['result']['auctions'][:5]
        scenario=indicative([record])
        self.assertEqual(scenario['unique_priceable_auctions'],0,'five rows contain only four independent comparables')
        future=deepcopy(self.benchmark['records'][1])
        combined=indicative([record,future])
        self.assertTrue(all(t['observed_utc']!=record['submitted_utc'] for t in combined['successful_evaluation_traces']))

    def test_diagnostic_revalidation_is_not_a_profitable_execution_proof(self):
        records=[r for r in self.benchmark['records'] if r['window']==0]
        result=diagnostic_revalidation(records)
        self.assertFalse(result['counts_as_profitable_opportunity'])
        self.assertFalse(result['absence_means_sold'])
        changed=deepcopy(records)
        for r in changed:
            if r['slot']>=6:r['result']['auctions']=[]
        self.assertIn('NOT_OBSERVED_IN_BOUNDED_PAGES',diagnostic_revalidation(changed)['reasons'])

    def test_passive_metadata_deduplication_does_not_generate_requests(self):
        seen=set()
        row={'status':200,'observed_at':'2026-11-12T00:00:00Z'}
        self.assertEqual(list(unseen([row,row],seen)),[row])
        self.assertEqual(list(unseen([row],seen)),[])

    def test_live_partial_evidence_integrity_does_not_pass_completion(self):
        result=validate(ROOT/'experiments/market_discovery_live_v1/runs/20261112T064306Z')
        self.assertEqual(result['integrity_status'],'PASS')
        self.assertEqual(result['benchmark_completion'],'BLOCKED')
        self.assertEqual(result['actual_EA_requests_by_strategy'],{'A':8,'B':0,'C':0})
        self.assertEqual(result['completed_windows'],1)

    def test_report_writer_rejects_synthetic_lineage_before_writing_any_report(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            (p/'observations.json').write_text(json.dumps({'mode':'SIMULATED'}))
            with self.assertRaisesRegex(ValueError,'live_report_requires_live_lineage'):
                write(p)
            self.assertFalse((p/'REPORT.md').exists())


if __name__=='__main__':unittest.main(verbosity=2)
