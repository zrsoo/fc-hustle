"""T5 artifact/provenance/metrics/preservation checks for all seven criteria."""
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.pricing import Policy, Rules, evaluate
from experiments.market_discovery.model import stamp
from experiments.market_discovery.opportunity import normalized, revalidate
from experiments.market_discovery.t5_pricing import OUTPUT, T2, T4, build_report, historical_comparison, source_snapshot


from fc_access.evidence import evidence_hashes, research_semantics

def load(path): return json.loads(path.read_text(encoding='utf-8'))


def semantic(report):
    result = research_semantics(json.loads(json.dumps(report)))
    for f in result['demonstration']['flows']:
        f['events'] = [e['state'] for e in f['events']]
        for key in ('latency', 'search_to_prepared_intent_ms', 'full_flow_ms'):
            del f['metrics'][key]
    return result


class T5ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.report = load(OUTPUT)

    def test_criterion_0_preserved_calculator_and_recomputable_historical_comparison(self):
        report = self.report
        self.assertEqual(report['task'], 'T5')
        self.assertEqual(report['historical'], json.loads(json.dumps(historical_comparison(source_snapshot()))))
        self.assertEqual(len(report['historical']['markets']), 2)
        a, b = report['historical']['markets']
        self.assertEqual(a['key'], {'definition_id': 233731, 'platform': 'pc', 'game': 'fc27'})
        p = a['hypothetical_rules_only']
        self.assertEqual((p['estimate']['target_sale_price'], p['estimate']['expected_profit']), (6200, -210))
        self.assertEqual(p['estimators']['robust_median']['target_sale_price'], 6500)
        self.assertEqual(p['estimators']['robust_mean']['expected_profit'], 75)
        self.assertEqual(b['hypothetical_rules_only']['estimate']['expected_profit'], -57)
        self.assertTrue(all(m['missing_observed_rules']['estimate']['status'] == 'MISSING_CAPS'
                            for m in report['historical']['markets']))
        for path, digest in evidence_hashes(report['inputs_sha256']).items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)

    def test_criteria_0_1_rejected_accessible_sandbox_never_becomes_PC_production_price(self):
        external = self.report['external']
        sandbox = load(T2/'sandbox-prices.json')
        self.assertTrue(sandbox['success']); self.assertTrue(sandbox['sandbox'])
        self.assertIn('Fixed illustrative data', sandbox['warning'])
        self.assertEqual(external['status'], 'UNAVAILABLE')
        self.assertFalse(external['production_feed_retrieved'])
        self.assertEqual(len(external['quotes']), len(sandbox['data']['items']))
        for market in self.report['historical']['markets']:
            q = market['hypothetical_rules_only']['external']
            self.assertEqual(q['usable_references'], 0)
            self.assertEqual(len(q['reviews']), 2)
            for row in q['reviews']:
                self.assertTrue({'SOURCE_UNAVAILABLE', 'PLATFORM_MISMATCH', 'SANDBOX_OR_LINEAGE_UNKNOWN',
                                 'STALE_OR_FUTURE_QUOTE', 'MAPPING_UNVERIFIED'} <= set(row['reasons']))
                self.assertIsNone(row['target_minus_reference'])

    def test_criteria_1_2_3_independently_recompute_candidate_signals_and_intent_fields(self):
        for f in self.report['demonstration']['flows']:
            rows = normalized([f['records'][0]])
            now = stamp(f['records'][0]['completed_utc'])
            actual = {r.trade_id: r for r in rows}
            for ranked in f['ranked_candidates']:
                c = actual[ranked['candidate']['trade_id']]
                rules = Rules(c.key, 150, 15000000, stamp('2026-11-12T12:00:00+00:00'))
                estimate = evaluate(c.key, rows, c, rules, now=now, X=f['X'],
                                    policy=Policy(min_remaining=60))
                p = ranked['pricing']['estimate']
                self.assertEqual((p['target_sale_price'], p['expected_profit'], p['sample_count'], ranked['eligible']),
                                 (estimate.target_sale_price, estimate.expected_profit, estimate.sample_count, estimate.meets_threshold))
                self.assertIn('acquisition_excluded', dict(p['rejected']))
                self.assertIn('LIQUIDITY_UNKNOWN', ranked['pricing']['uncertainty'])
                self.assertIn('SELL_THROUGH_UNMEASURED', ranked['pricing']['uncertainty'])
                for X, value in ranked['pricing']['scenarios'].items():
                    self.assertEqual(value, p['status'] == 'OK' and p['expected_profit'] >= int(X))
            b = f['buy_intent']
            self.assertEqual(b['mode'], 'DRY_RUN_ONLY')
            self.assertEqual(b['expected_profit'], b['target_sale_price']-b['target_sale_price']//20-b['buy_now_price'])
            self.assertGreaterEqual(b['expected_profit'], b['X'])
            self.assertEqual(b['X'], f['X'])
            current = next(r for r in normalized([f['records'][0]]) if r.trade_id == b['trade_id'])
            validation, fresh_candidate = revalidate(current, f['records'][1], now=stamp(f['records'][1]['completed_utc']),
                                       scan_completed=stamp(f['records'][0]['completed_utc']))
            self.assertEqual(validation, f['revalidation'])
            self.assertIsNotNone(fresh_candidate)
            self.assertEqual(f['listing_intent']['item_id'], b['item_id'])
            self.assertEqual(f['listing_intent']['buy_now_price'], b['target_sale_price'])
            self.assertIn('INVENTORY_READBACK', f['listing_intent']['precondition'])

    def test_criterion_4_live_yield_matches_raw_failure_and_simulation_is_separate(self):
        live = self.report['live']
        base = load(T4/'baseline-preflight.json')
        alternative = load(T4/'preflight.json')['record']
        self.assertFalse(base['result']['success']); self.assertFalse(alternative['result']['success'])
        self.assertEqual(base['result']['network'][0]['status'], 401)
        self.assertTrue(base['result']['network'][0]['session_header_present'])
        self.assertEqual(sum(len(r['result']['auctions'] or []) for r in (base, alternative)), 0)
        self.assertEqual(live['status'], 'UNOBSERVED')
        self.assertEqual(live['fresh_auctions'], 0)
        self.assertEqual(live['prepared_intents'], 0)
        self.assertEqual(live['qualifying_candidates_observed'], 0)
        self.assertIsNone(live['opportunities_per_hour'])
        self.assertEqual(live['new_EA_requests'], 0)
        self.assertEqual(self.report['historical']['new_live_samples'], 0)
        demo = self.report['demonstration']
        self.assertEqual(demo['mode'], 'SIMULATED')
        self.assertEqual(demo['lineage'], 'DETERMINISTIC_SYNTHETIC_NOT_LIVE')
        self.assertEqual([f['X'] for f in demo['flows']], [100, 250, 500, 1000])
        for f in demo['flows']:
            self.assertEqual(f['mode'], 'SIMULATED')
            self.assertTrue(all(r['mode'] == 'SIMULATED' for r in f['records']))
            self.assertEqual(f['buy_intent']['lineage'], 'SIMULATED')
            self.assertEqual(f['listing_intent']['lineage'], 'SIMULATED')

    def test_criterion_5_exported_metrics_match_records_events_and_clock_scope(self):
        for f in self.report['demonstration']['flows']:
            m = f['metrics']
            rows = normalized([f['records'][0]])
            self.assertEqual(m['discovery']['rows'], len(rows))
            self.assertEqual(m['discovery']['unique_auctions'], len({r.trade_id for r in rows}))
            self.assertEqual(m['discovery']['eligible_by_X'], {'100': 2, '250': 2, '500': 2, '1000': 1})
            self.assertEqual(m['pricing']['evaluated'], len(f['ranked_candidates']))
            self.assertEqual(m['pricing']['priced'], sum(r['pricing']['estimate']['status'] == 'OK' for r in f['ranked_candidates']))
            self.assertEqual(m['revalidation'], {'attempts': 1, 'passed': 1})
            self.assertEqual(m['latency_scope'], 'IN_PROCESS_FIXTURE_REPLAY_NOT_EA')
            previous = 0
            for e in f['events']:
                self.assertTrue(math.isfinite(e['elapsed_ms']))
                self.assertGreaterEqual(e['start_offset_ms'], previous)
                self.assertGreaterEqual(e['end_offset_ms'], e['start_offset_ms'])
                self.assertAlmostEqual(e['end_offset_ms']-e['start_offset_ms'], e['elapsed_ms'])
                previous = e['end_offset_ms']
                a = m['latency'][e['state']]
                self.assertEqual((a['n'], a['median_ms'], a['p95_ms']), (1, e['elapsed_ms'], None))
            buy_event = next(e for e in f['events'] if e['state'] == 'DRY_RUN_BUY_INTENT')
            self.assertEqual(m['search_to_prepared_intent_ms'], buy_event['end_offset_ms'])
            self.assertGreaterEqual(m['search_to_prepared_intent_ms'], sum(e['elapsed_ms'] for e in f['events'][:-1]))
            self.assertEqual(m['full_flow_ms'], previous)
            self.assertGreater(m['full_flow_ms'], 0)

    def test_criteria_4_5_reproduce_cli_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'replay.json'
            command = [sys.executable, '-m', 'experiments.market_discovery.t5_pricing', '--output', str(out)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(semantic(load(out)), semantic(self.report))
            before = out.read_bytes()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(out.read_bytes(), before)

    def test_criterion_6_no_network_in_offline_report_no_mutator_or_scheduler_dependency(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('unexpected socket')):
            self.assertEqual(semantic(build_report()), semantic(self.report))
        for relative in ('experiments/market_discovery/opportunity.py', 'experiments/market_discovery/t5_pricing.py'):
            tree = ast.parse((ROOT/relative).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse(any(t in (node.module or '') for t in ('transaction', 'fc_execution', 'schedule', 'transport', 'server')))
                if isinstance(node, ast.Import):
                    self.assertFalse(any(t in a.name for a in node.names for t in ('transaction', 'fc_execution', 'schedule', 'requests', 'urllib')))
                self.assertNotIsInstance(node, ast.While)
        preservation = load(ROOT/'docs/research/001b/preservation.json')['static_sha256']
        for name, digest in evidence_hashes(preservation).items():
            if name.startswith(('browser/', 'fc_access/', 'objectives/')):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), digest, name)
        self.assertEqual(self.report['account_mutations'], 0)
        self.assertFalse(self.report['production_executor'])

    def test_documentation_links_and_executable_reproduction_commands_exist(self):
        path = ROOT/'docs/research/001b-proposed-flow.md'
        text = path.read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if not target.startswith('https://'):
                self.assertTrue((path.parent/target.split('#')[0]).resolve().exists(), target)
        self.assertIn('python tests/test_t5_pricing.py', text)
        self.assertIn('python tests/test_t5_pricing_artifacts.py', text)
        self.assertIn('UNOBSERVED', text)
        self.assertIn('SIMULATED', text)


if __name__ == '__main__': unittest.main()
