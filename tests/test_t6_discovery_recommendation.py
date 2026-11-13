"""T6 acceptance checks: evidence arithmetic, document contracts and negative cases.

Run independently from the workspace using only supervisor Python's stdlib.
No login, browser, network or newly generated live artifacts are required.
"""
import ast
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import socket
from statistics import median
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.market_discovery.t6_analysis import INPUTS, OUTPUT, build_report, evidence_tables, stats

FILES = {
    'benchmarks': '001b-discovery-benchmarks.md', 'latency': '001b-latency.md',
    'flow': '001b-proposed-flow.md', 'addendum': '001b-obj002-addendum.md',
    'decision': '001b-discovery-decision.md',
}


from fc_access.evidence import evidence_hashes

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def docs():
    return {k: (ROOT/'docs/research'/v).read_text(encoding='utf-8') for k, v in FILES.items()}


def normalize(text):
    return ' '.join(text.split())


def defects(documents, report):
    """Return acceptance indexes whose reviewable artifact contracts are broken."""
    broken = set()
    tables = evidence_tables(build_report())
    for name, table in tables.items():
        key, criterion = ('benchmarks', 0) if name in ('budgets', 'live_coverage', 'historical') else (
            ('benchmarks', 1) if name == 'scenarios' else ('latency', 2))
        if table not in documents[key]:
            broken.add(criterion)
    required = {
        0: ('benchmarks', [
            'BLOCKED / NOT STARTED', 'zero authenticated observation seconds',
            '2026-11-11T22:00:49.736773+00:00', '2026-11-11T22:04:49.887092+00:00',
            '240.150319', '2026-11-11T19:10:03.139863+00:00',
            '2026-11-11T19:11:15.334878+00:00', '72.195015', 'A/B/C/B/C/A/C/A/B',
            'Club 9', 'league 13', 'max BIN 6500', 'pages 1/2', '30 seconds',
            'matched blocks', 'False-positive fraction is **unknown (0/0)**',
            'failed_qualifying_revalidations / completed_qualifying_revalidations',
            'Expiry-ordered offset pages', 'lookahead', 'price-ceiling',
            'background', 'not an empirically proven yield winner',
            'python -m experiments.market_discovery.t6_analysis',
        ]),
        1: ('benchmarks', [
            'UNOBSERVED at X=100, 250, 500 and 1000',
            '3600 * distinct_first_qualified_auctions / observed_strategy_seconds',
            'deduplicating repeated auctions', 'Synthetic success is separate',
            'four prepared intents are not four independent auctions',
            'Projected profit is not completed-sale evidence',
            'hypothetical rules', 'No observation interval supports estimation',
        ]),
        2: ('latency', [
            'UNVALIDATED', 'periodInMinutes: 0.5', '20 seconds server-side',
            'not a matched instrumented baseline', 'Python decision', 'First result',
            'Prepared intent', 'not isolated EA server latency',
            'unknown, n=0', 'median **29961.553 ms (n=3)**',
            'nearest rank `ceil(0.95*n)` only when n>=20',
            'different enqueue phases', 'medians do not sum',
            'cannot be compared', 'not network search latency',
            'independent 30-second EA submission gap', 'MV3 suspension',
            'live bottleneck', 'subtracting an assumed 30 seconds',
        ]),
        3: ('flow', [
            'exact-version native watchlist', 'bounded C exploration',
            'No third-party production source is enabled',
            'historical asks for offline replay only', 'synthetic fixtures for tests only',
            'preceding completed block only', 'replaces a scheduled scan',
            'target_sale_price - target_sale_price // 20 - X',
            'expected_profit >= X', 'X is the only mandatory profit threshold',
            'candidate/revalidation read <=30 seconds', 'comparables <=120 seconds',
            'rules <=300 seconds', 'external publication <=600 seconds',
            'strictly >60 seconds', 'five independent', 'provenance outside the pure calculator',
            'buy_intent', 'listing_intent', 'NOT_READY', 'Retry-After',
            'Unknown buy/list outcome', 'reconcile read-only', 'Keep HELD',
            'two-read broad-first demo', 'S1–S4', 'S5/S6 and L1–L8',
        ]),
        4: ('addendum', [
            'Apply only these changes', 'original handoff bytes',
            'Selected sources', 'Search approach', 'Latency solution', 'Exact modules/interfaces',
            'Dependencies', 'Open blockers', 'planned', 'fc_execution/providers.py',
            'fc_execution/strategy.py', 'fc_execution/rules.py', 'fc_execution/scheduler.py',
            'fc_execution/models.py', 'fc_execution/transport.py', 'browser/execution-bridge/worker.js',
            'SearchTransport.search(params, evidence_key)', 'bridge_server.SearchServer',
            'No new runtime package', 'Python 3.10+', 'Node 22+',
            'entitlement remains optional', 'S1', 'S2', 'S3', 'S4',
            'EA 401', 'schema_unrecognized', 'zero authenticated observation seconds',
            'at least 30 authenticated observation minutes', 'No production PC feed retrieval',
        ]),
        5: ('decision', [
            'CONDITIONAL GO', 'offline Objective 002', 'No third-party production feed is selected',
            'DataFluxor', 'first conditional feed candidate', 'start with A', 'bounded C hybrid',
            'not a measured yield winner', 'unknown for X=100/250/500/1000',
            'Projected profit is not completed-sale evidence', '24888.920100', '0.037200',
            'local bottleneck', 'live bottleneck remain unknown',
            'Exact unverified prerequisites', 'HTTP 200 search', 'persona projection',
            '30 authenticated minutes', 'caps', 'increments', 'MV3', 'entitlement', 'tax rounding',
        ]),
    }
    for criterion, (key, terms) in required.items():
        text = normalize(documents[key]).lower()
        if any(term.lower() not in text for term in terms):
            broken.add(criterion)
    if len(documents['decision'].split()) > 650:
        broken.add(5)
    # Keep the addendum a delta: no pasted baseline state/recovery/release spec.
    if any(h in documents['addendum'] for h in ('## Live acceptance conditions', '## Module and file plan',
                                               '## Reusable sources and license obligations')):
        broken.add(4)
    # The example must exactly match a retained inert fixture, not just a list
    # of plausible schema field names.
    blocks = re.findall(r'```json\s*(.*?)\s*```', documents['flow'], re.S)
    try:
        sample = json.loads(blocks[-1])
        f = load(ROOT/INPUTS['t5'])['demonstration']['flows'][0]
        if sample != {k: f[k] for k in ('buy_intent', 'listing_intent')}:
            broken.add(3)
    except (IndexError, ValueError, KeyError):
        broken.add(3)
    expected = build_report()
    # Changes to lineage, denominators or unsupported estimates must fail even
    # if the narrative still contains the expected cautionary language.
    for key, criteria in {
        'strategies': (0,), 'historical': (0, 1), 'live': (0, 1), 'X_scenarios': (1,),
        'qualifying_revalidations': (0,), 'failed_qualifying_revalidations': (0,),
        'false_positive_fraction': (0,), 'local_latency': (2,), 'live_latency': (2,),
        'fixture_latency': (2,), 'fixture_latency_scope': (2,),
        'decision': (5,), 'decision_scope': (5,), 'selected_source': (3, 4, 5),
        'third_party_production_source': (3, 4, 5), 'selected_search': (3, 4, 5),
        'latency_choice': (2, 4, 5), 'inputs_sha256': (0, 1, 2, 4),
    }.items():
        if report.get(key) != expected[key]:
            broken.update(criteria)
    for key, text in documents.items():
        path = ROOT/'docs/research'/FILES[key]
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith('https://'):
                continue
            resolved = (path.parent/target.split('#')[0]).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.is_file():
                broken.add({'benchmarks': 0, 'latency': 2, 'flow': 3, 'addendum': 4, 'decision': 5}[key])
    return sorted(broken)


class RecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = load(OUTPUT)
        cls.documents = docs()

    def test_all_six_document_contracts_and_links(self):
        self.assertEqual(defects(self.documents, self.report), [])

    def test_criterion_0_raw_budgets_periods_coverage_and_false_positive_denominators(self):
        p = load(ROOT/INPUTS['protocol'])
        self.assertEqual(p['timing']['order'], list('ABCBCACAB'))
        for s in self.report['strategies']:
            self.assertEqual(s['planned_windows'], p['timing']['order'].count(s['strategy']))
            self.assertEqual(s['planned_max_requests'], s['planned_discovery_requests']+s['planned_revalidation_requests'])
            self.assertEqual(s['planned_max_requests'], 24)
            self.assertEqual((s['actual_windows'], s['actual_requests'], s['authenticated_seconds']), (0, 0, 0))
        base = load(ROOT/INPUTS['baseline'])
        alt = load(ROOT/INPUTS['alternative'])['record']
        self.assertEqual(sum(len(r['result']['network']) for r in (base, alt)), 1)
        self.assertEqual(base['result']['network'][0]['status'], 401)
        self.assertEqual(alt['result']['error'], 'schema_unrecognized')
        self.assertFalse(alt['result']['network'])
        actual = load(ROOT/INPUTS['asks'])
        searches = [a for a in actual['attempts'] if a['operation'] == 'search']
        rows = [r for a in searches for r in a['result']['auctions']]
        h = self.report['historical']
        self.assertEqual((h['EA_requests'], h['rows'], h['unique_auctions'], h['unique_versions']), (3, 52, 51, 2))
        self.assertEqual(h['unique_auctions'], len({r['trade_id'] for r in rows}))
        self.assertEqual(h['unique_versions'], len({r['item']['definition_id'] for r in rows}))
        self.assertEqual(h['auctions_per_request'], 51/3)
        self.assertEqual(h['versions_per_request'], 2/3)
        self.assertEqual(h['auctions_per_minute'], 51*60/h['observed_seconds'])
        self.assertEqual(h['versions_per_minute'], 2*60/h['observed_seconds'])
        self.assertEqual(h['observed_seconds'], 72.195015)
        live = self.report['live']
        self.assertAlmostEqual((datetime.fromisoformat(live['ended_utc'])-datetime.fromisoformat(live['started_utc'])).total_seconds(), live['attempt_span_seconds'])
        self.assertEqual(live['authenticated_observation_seconds'], 0)
        self.assertIsNone(self.report['false_positive_fraction'])
        self.assertEqual(self.report['qualifying_revalidations'], 0)

    def test_criterion_1_independent_profit_counts_and_no_unsupported_hourly_estimates(self):
        t5 = load(ROOT/INPUTS['t5'])
        rows = t5['demonstration']['flows'][0]['ranked_candidates']
        profitable = []
        for r in rows:
            e = r['pricing']['estimate']
            if e['status'] == 'OK' and not r['identity_conflict']:
                self.assertEqual(e['expected_profit'], e['target_sale_price']-e['target_sale_price']//20-e['acquisition_price'])
                profitable.append(e['expected_profit'])
        for row in self.report['X_scenarios']:
            self.assertEqual(row['synthetic_candidates'], sum(p >= row['X'] for p in profitable))
            self.assertEqual(row['historical_modeled_candidates'], 0)
            self.assertEqual(row['live_candidates_observed'], 0)
            self.assertIsNone(row['live_opportunities_per_hour'])
            self.assertIsNone(row['synthetic_opportunities_per_hour'])
        self.assertEqual([s['synthetic_candidates'] for s in self.report['X_scenarios']], [2, 2, 2, 1])
        self.assertEqual(t5['live']['prepared_intents'], 0)
        self.assertTrue(all(f['buy_intent']['lineage'] == 'SIMULATED' for f in t5['demonstration']['flows']))
        self.assertEqual(len({f['buy_intent']['trade_id'] for f in t5['demonstration']['flows']}), 1)

    def test_criterion_2_recompute_latency_from_samples_and_enforce_p95_support(self):
        local = load(ROOT/INPUTS['local'])
        for raw, report in zip(local['arms'], self.report['local_latency']):
            self.assertEqual(report['scope'], 'LOCAL_SIMULATOR_ONLY')
            self.assertEqual(report['errors'], 0)
            self.assertEqual(report['end_to_end_ms']['median_ms'], median(r['end_to_end_ms'] for r in raw['records']))
            for key, result in report['components'].items():
                self.assertEqual(result['n'], len(raw['records']))
                self.assertEqual(result['median_ms'], median(r['timing'][key] for r in raw['records']))
                self.assertIsNone(result['p95_ms'])
        for n in (0, 1, 3, 4, 19):
            self.assertIsNone(stats(list(range(n)))['p95_ms'])
        self.assertEqual(stats(list(range(20)))['p95_ms'], 18)
        self.assertEqual(stats(list(range(21)))['p95_ms'], 19)
        self.assertEqual(stats([]), {'n': 0, 'median_ms': None, 'p95_ms': None})
        for arm in self.report['live_latency'].values():
            self.assertEqual(arm['command_round_trip_ms']['n'], 1)
            self.assertIsNone(arm['command_round_trip_ms']['p95_ms'])
            for key in ('native_service_ms', 'EA_server_latency_ms', 'time_to_first_successful_result_ms'):
                self.assertEqual(arm[key]['n'], 0)
                self.assertIsNone(arm[key]['median_ms'])
        t5 = load(ROOT/INPUTS['t5'])
        for stage, result in self.report['fixture_latency'].items():
            values = [f['metrics'][stage] if stage == 'search_to_prepared_intent_ms' else
                      next(e['elapsed_ms'] for e in f['events'] if e['state'] == stage)
                      for f in t5['demonstration']['flows']]
            self.assertEqual(result, {'n': 4, 'median_ms': median(values), 'p95_ms': None})

    def test_criteria_3_4_exact_reference_interfaces_and_no_invented_bridge_class(self):
        expected = {
            'opportunity.py': {'price_candidate': ['rows', 'candidate', 'rules'],
                               'rank_candidates': ['records', 'rules'],
                               'revalidate': ['candidate', 'record'], 'run_flow': ['read']},
            'discovery.py': {'rank': ['previous_block', 'external', 'now'], 'plan': ['strategy', 'ranking']},
        }
        for filename, signatures in expected.items():
            tree = ast.parse((ROOT/'experiments/market_discovery'/filename).read_text())
            functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
            for name, arguments in signatures.items():
                self.assertEqual([a.arg for a in functions[name].args.args], arguments)
                self.assertIn(name+'(', self.documents['addendum'])
        bridge = ast.parse((ROOT/'experiments/market_discovery/bridge_server.py').read_text())
        self.assertTrue({'SearchServer', 'Handler'} <= {n.name for n in bridge.body if isinstance(n, ast.ClassDef)})
        self.assertNotIn('bridge_server.Queue', self.documents['addendum'])
        # Every new execution path in the delta already belongs to the baseline
        # plan; T6 must not quietly create an execution implementation.
        baseline = (ROOT/'docs/research/obj002-handoff.md').read_text(encoding='utf-8')
        for path in re.findall(r'`((?:fc_execution|browser/execution-bridge)/[^`]+)`', self.documents['addendum']):
            self.assertIn(path.removesuffix('*'), baseline)
        preservation = load(ROOT/'docs/research/001b/preservation.json')['static_sha256']
        self.assertEqual(hashlib.sha256((ROOT/'docs/research/obj002-handoff.md').read_bytes()).hexdigest(),
                         preservation['docs/research/obj002-handoff.md'])

    def test_criterion_5_one_page_conclusion_tied_to_measured_evidence(self):
        self.assertLessEqual(len(self.documents['decision'].split()), 650)
        self.assertEqual(self.report['decision'], 'CONDITIONAL GO')
        self.assertEqual(self.report['decision_scope'], 'OFFLINE_ARCHITECTURE_IMPLEMENTATION_ONLY')
        self.assertIsNone(self.report['third_party_production_source'])
        providers = load(ROOT/INPUTS['providers'])
        self.assertIn('DOCUMENTED_PRODUCTION_AUTH_REQUIRED_SANDBOX_ONLY', json.dumps(providers))
        self.assertIn('DENIED_AND_AUTOMATION_PERMISSION_UNESTABLISHED', json.dumps(providers))
        a, b = self.report['local_latency']
        self.assertGreater(a['components']['queue_delivery_ms']['median_ms'],
                           1000*b['components']['queue_delivery_ms']['median_ms'])
        # This is evidence for local delivery only; no live speedup field exists.
        self.assertEqual(self.report['latency_choice'], 'LONG_POLL_PROPOSED_SUCCESSFUL_EDGE_PATH_UNVALIDATED')

    def test_every_criterion_rejects_missing_or_misleading_document_content(self):
        mutations = [
            ('benchmarks', 'False-positive fraction is\n**unknown (0/0)**', 'False-positive fraction is 0%', 0),
            ('benchmarks', evidence_tables(self.report)['scenarios'], 'Observed rate: 100/hour', 1),
            ('latency', evidence_tables(self.report)['local_latency'], 'p95=30ms; n=3', 2),
            ('flow', '"lineage": "SIMULATED"', '"lineage": "LIVE_READ_ONLY"', 3),
            ('addendum', '## Exact modules/interfaces', '## Other', 4),
            ('decision', 'CONDITIONAL GO', 'GO', 5),
        ]
        for key, old, new, criterion in mutations:
            with self.subTest(criterion=criterion):
                self.assertIn(old, self.documents[key])
                changed = deepcopy(self.documents)
                changed[key] = changed[key].replace(old, new)
                self.assertIn(criterion, defects(changed, self.report))
        changed = deepcopy(self.documents)
        changed['decision'] += '\n'+'extra '*651
        self.assertIn(5, defects(changed, self.report))
        changed = deepcopy(self.documents)
        changed['addendum'] += '\n## Live acceptance conditions\n'
        self.assertIn(4, defects(changed, self.report))

    def test_rejects_fabricated_yield_coverage_latency_and_unverified_source_promotion(self):
        changes = [
            (('strategies', 0, 'actual_windows'), 3, 0),
            (('false_positive_fraction',), 0, 0),
            (('X_scenarios', 0, 'live_opportunities_per_hour'), 0, 1),
            (('X_scenarios', 0, 'synthetic_opportunities_per_hour'), 120, 1),
            (('local_latency', 0, 'end_to_end_ms', 'p95_ms'), 30000, 2),
            (('fixture_latency_scope',), 'EA_LIVE', 2),
            (('third_party_production_source',), 'DataFluxor', 4),
            (('decision_scope',), 'PRODUCTION_READY', 5),
        ]
        for path, value, criterion in changes:
            with self.subTest(path=path):
                changed = deepcopy(self.report)
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertIn(criterion, defects(self.documents, changed))

    def test_reproducible_report_cli_exclusive_output_and_no_network(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('T6 must stay offline')):
            self.assertEqual(build_report(), self.report)
        for path, digest in evidence_hashes(self.report['inputs_sha256']).items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'report.json'
            command = [sys.executable, '-m', 'experiments.market_discovery.t6_analysis', '--output', str(output)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(load(output), self.report)
            before = output.read_bytes()
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), before)
        self.assertEqual(self.report['new_EA_requests'], 0)
        self.assertEqual(self.report['account_mutations'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
