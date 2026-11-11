"""All T4 criteria, including the documented live-access-blocker branch.

These are offline artifact checks, not a fresh authentication or throughput test.
No test dispatches EA requests. Removing or altering evidence must fail checks.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.harness import validate_result
from experiments.market_discovery.model import TIMINGS, reply, search
from experiments.market_discovery.t4_evidence import INPUTS, RUN, SOURCES, build_blocker_report


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset().total_seconds() != 0:
        raise ValueError('UTC required')
    return result


class T4EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence_dir = ROOT / RUN
        cls.report = load(cls.evidence_dir / 'report.json')
        cls.access = load(cls.evidence_dir / 'access-inspection.json')
        cls.alt_wrapper = load(cls.evidence_dir / 'preflight.json')
        cls.alt = cls.alt_wrapper['record']
        cls.base = load(cls.evidence_dir / 'baseline-preflight.json')
        cls.protocol = load(ROOT / 'docs/research/001b/protocol.json')

    def test_criterion_0_normal_attachment_and_actual_authenticated_read_failure(self):
        a = self.access
        self.assertGreater(a['edge_processes']['edge_process_count'], 0)
        self.assertEqual(a['search_bridge_health'], {
            'service': 'fc-search-research-v1', 'attached': True,
            'bind': '127.0.0.1', 'operations': ['search']})
        event = a['normal_reattachment']
        self.assertEqual(event['package'], 'experiments/market_discovery/browser')
        self.assertRegex(event['extension_id'], r'^[a-p]{32}$')
        self.assertIn('click separate discovery extension action', event['method'])
        self.assertTrue(event['UI_control_available'])
        self.assertFalse(event['credential_values_read'])
        self.assertLessEqual(timestamp(event['reported_at_utc']), timestamp(self.alt['submitted_utc']))
        b = validate_result(self.base['result'])
        self.assertEqual(b['platform'], 'pc')
        self.assertEqual(b['status'], 401)
        self.assertFalse(b['success'])
        self.assertEqual(b['network'], [{
            'host': 'utas.mob.v1.prd.futc-ext.gcp.ea.com',
            'path': '/ut/game/fc27/transfermarket',
            'session_header_present': True, 'status': 401}])
        self.assertFalse(self.report['attachment']['authenticated'])
        self.assertFalse(self.report['attachment']['badge_or_health_establishes_authentication'])
        self.assertEqual(self.report['reason'], 'EA_AUTHENTICATION_REJECTED_401')

    def test_criterion_1_planned_windows_budgets_pacing_and_no_fictitious_observation(self):
        plan = self.report['planned_observation']
        self.assertEqual(plan['order'], self.protocol['timing']['order'])
        self.assertEqual(Counter(plan['order']), {'A': 3, 'B': 3, 'C': 3})
        self.assertTrue(all(a != b for a, b in zip(plan['order'], plan['order'][1:])))
        self.assertEqual(plan['window_seconds'], 300)
        self.assertEqual(plan['minimum_gap_seconds'], 30)
        self.assertEqual(plan['max_in_flight'], 1)
        self.assertEqual(plan['EA_request_budget_per_window'], 8)
        self.assertEqual(plan['EA_request_budget_per_strategy'], 24)
        self.assertEqual(plan['filters_and_pages']['strategies'], self.protocol['strategies'])
        self.assertEqual(plan['filters_and_pages']['pages'], [1, 2])
        self.assertGreater(len(self.protocol['strategies']['B']['pairs']), 1)
        self.assertEqual(plan['windows_requested'], 9)
        self.assertEqual(plan['windows_completed'], 0)
        self.assertEqual(plan['actual_strategy_windows'], [])
        self.assertEqual(plan['actual_matched_blocks'], 0)
        self.assertEqual(plan['status'], 'NOT_STARTED_PREFLIGHT_FAILED')
        self.assertEqual(self.report['target_observation_seconds'], 1800)
        self.assertEqual(self.report['authenticated_observation_seconds'], 0)
        self.assertTrue(plan['preflight_budget_separate'])
        # Check actual spacing and budget use, not just intended settings.
        self.assertGreaterEqual((timestamp(self.base['submitted_utc']) -
                                timestamp(self.alt['submitted_utc'])).total_seconds(), 30)
        self.assertEqual(self.alt_wrapper['budget'],
                         {'limit': 1, 'commands': 1, 'requests': 0, 'overrun': False})
        self.assertEqual(self.base['EA_budget_limit'], 1)
        self.assertLessEqual(len(self.base['result']['network']), self.base['EA_budget_limit'])

    def test_criterion_2_raw_evidence_sizes_identity_counts_ages_errors_and_UTC(self):
        r = self.report
        self.assertEqual(r['started_utc'], self.alt['submitted_utc'])
        self.assertEqual(r['ended_utc'], self.base['completed_utc'])
        elapsed = (timestamp(r['ended_utc']) - timestamp(r['started_utc'])).total_seconds()
        self.assertAlmostEqual(r['attempt_span_seconds'], elapsed, places=6)
        waits = 0
        for capture in (self.alt, self.base):
            search(capture['criteria'])
            validate_result(capture['result'])
            delta = (timestamp(capture['completed_utc']) - timestamp(capture['submitted_utc'])).total_seconds()
            self.assertAlmostEqual(capture['elapsed_ms'] / 1000, delta, delta=0.005)
            waits += capture['elapsed_ms'] / 1000
            self.assertIsNone(capture['result']['auctions'])
            self.assertIsNone(capture['result']['items'])
            self.assertIsNone(capture['result']['credits'])
        self.assertAlmostEqual(r['command_wait_seconds'], waits)
        alt_reply = {'result': self.alt['result'],
                     'timing': {k: self.alt['timing'][k] for k in TIMINGS}}
        reply(alt_reply)
        self.assertEqual(self.alt['response_bytes'], len(json.dumps(alt_reply, separators=(',', ':')).encode()))
        self.assertEqual(self.base['response_bytes'], len(json.dumps(self.base['result'], separators=(',', ':')).encode()))
        measured = r['observed']
        self.assertEqual(measured['commands'], 2)
        self.assertEqual(measured['EA_requests'], sum(len(c['result']['network']) for c in (self.alt, self.base)))
        self.assertEqual(measured['sanitized_response_bytes'], self.alt['response_bytes'] + self.base['response_bytes'])
        self.assertIsNone(measured['EA_wire_response_bytes'])
        for field in ('fresh_authenticated_results', 'rows', 'unique_auctions', 'account_mutations'):
            self.assertEqual(measured[field], 0)
        self.assertEqual(measured['exact_versions'], [])
        self.assertIsNone(measured['duplicate_fraction'])
        self.assertEqual(measured['observation_age_seconds'], [])
        self.assertEqual(measured['expiry_seconds'], [])
        self.assertEqual(measured['errors'], {'schema_unrecognized': 1, 'HTTP_401': 1})
        self.assertEqual(measured['coverage']['successful_filter_page_combinations'], [])
        self.assertIsNone(measured['coverage']['market_denominator'])
        self.assertEqual(self.alt['window'], -1)  # explicitly a preflight marker
        self.assertEqual(self.alt['mode'], 'LIVE_READ_ONLY')

    def test_criterion_3_actual_arms_failure_latency_components_and_supported_percentiles(self):
        latency = self.report['latency']
        self.assertEqual(set(latency['arms']), {'alarm_30s', 'long_poll'})
        for name, capture in (('alarm_30s', self.base), ('long_poll', self.alt)):
            arm = latency['arms'][name]
            self.assertEqual(arm['attempts'], 1)
            self.assertEqual(arm['EA_requests'], len(capture['result']['network']))
            self.assertEqual(arm['fresh_authenticated_results'], 0)
            for field in ('time_to_first_successful_result_ms', 'native_service_ms', 'EA_server_latency_ms'):
                self.assertEqual(arm[field]['n'], 0)
                self.assertIsNone(arm[field]['median_ms'])
                self.assertIsNone(arm[field]['p95_ms'])
            rt = arm['command_round_trip_ms']
            self.assertEqual(rt['n'], 1)
            self.assertEqual(rt['median_ms'], statistics.median([capture['elapsed_ms']]))
            self.assertIsNone(rt['p95_ms'])
            self.assertIsNone(arm['EA_wire_response_bytes'])
        local = latency['arms']['long_poll']['queue_delivery_ms']
        self.assertEqual(local['n'], 1)
        self.assertEqual(local['median_ms'], self.alt['timing']['queue_delivery_ms'])
        self.assertIsNone(local['p95_ms'])
        self.assertEqual(latency['arms']['alarm_30s']['queue_delivery_ms']['n'], 0)
        self.assertIsNone(self.base['timing_components'])
        self.assertEqual(latency['p95_min_samples'], 20)
        self.assertFalse(latency['native_is_EA_server_latency'])
        self.assertFalse(latency['subtract_assumed_alarm_delay'])
        self.assertIsNone(latency['live_speedup'])
        # Verify the pre-native guard attribution against source and raw timing.
        self.assertEqual(self.alt['result']['error'], 'schema_unrecognized')
        self.assertEqual(self.alt['result']['network'], [])
        self.assertIsNone(self.alt['timing']['native_service_ms'])
        self.assertIsNone(self.alt['result']['cache_invalidated'])
        page = (ROOT / 'experiments/market_discovery/browser/page.js').read_text()
        guard = 'if (persona?.platform !== "pc" && !(persona?.platform == null && persona?.isPC === true)) throw new Error("schema_unrecognized");'
        self.assertIn(guard, page)
        self.assertLess(page.index(guard), page.index('const p = c.params, criteria'))
        self.assertIn('periodInMinutes: 0.5', (ROOT / 'browser/read-bridge/worker.js').read_text())
        self.assertIn('const TRANSPORT = "long_poll"', (ROOT / 'experiments/market_discovery/browser/worker.js').read_text())

    def test_criterion_4_revalidation_unavailable_has_no_manufactured_outcomes(self):
        count = sum(len(c['result']['auctions'] or []) for c in (self.alt, self.base))
        revalidation = self.report['revalidation']
        self.assertEqual(count, 0)
        self.assertEqual(revalidation['fresh_candidates'], count)
        self.assertEqual(revalidation['status'], 'UNAVAILABLE_NO_FRESH_CANDIDATES')
        self.assertEqual(revalidation['attempts'], 0)
        self.assertEqual(revalidation['results'], [])
        self.assertEqual(revalidation['outcomes'], {k: None for k in
            ('unchanged', 'BIN_changed', 'identity_changed', 'expired', 'unavailable_auction')})
        self.assertIn('would not prove sale', revalidation['limitation'])

    def test_criterion_5_blocked_prerequisites_actual_duration_no_benchmark_claim(self):
        r = self.report
        self.assertEqual(r['status'], 'BLOCKED')
        self.assertFalse(r['throughput_benchmark_success'])
        self.assertEqual(r['authenticated_observation_seconds'], 0)
        self.assertAlmostEqual(r['attempt_span_seconds'], 240.150319)
        self.assertEqual(len(r['prerequisites']), 4)
        prerequisites = ' '.join(r['prerequisites'])
        for phrase in ('normal Web App sign-in', 'FC27 PC persona', 'fresh authenticated HTTP 200',
                       'reviewed read-only platform projection', 'reload/reattach normally'):
            self.assertIn(phrase, prerequisites)
        limitations = ' '.join(r['coverage_limitations'])
        for phrase in ('no retries', 'not a matched experiment', 'not EA wire bytes',
                       'Background EA traffic', 'No mocks', 'independent pseudonym keys'):
            self.assertIn(phrase, limitations)
        final = load(self.evidence_dir / 'auth-stop-health.json')
        self.assertTrue(final['no_EA_requests'])
        self.assertTrue(all(timestamp(c['checked_at_utc']) > timestamp(r['ended_utc']) for c in final['checks']))

    def test_input_and_implementation_integrity_and_exact_offline_replay(self):
        self.assertEqual(set(self.report['inputs_sha256']), set(INPUTS))
        self.assertEqual(set(self.report['sources_sha256']), set(SOURCES))
        for name, digest in self.report['inputs_sha256'].items():
            self.assertEqual(hashlib.sha256((self.evidence_dir / name).read_bytes()).hexdigest(), digest)
        for name, digest in self.report['sources_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(build_blocker_report(self.evidence_dir), self.report)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'report.json'
            command = [sys.executable, '-m', 'experiments.market_discovery.t4_evidence',
                       '--run', str(self.evidence_dir), '--output', str(output)]
            process = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=15)
            self.assertEqual(process.returncode, 0, process.stderr.decode())
            self.assertEqual(load(output), self.report)
            # Replay must preserve existing evidence, even if explicitly targeted.
            original = output.read_bytes()
            repeated = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=15)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(output.read_bytes(), original)

    def test_report_builder_refuses_unproven_or_successful_blocker_evidence(self):
        # Deliberately corrupt only temporary copies; these are negative tests,
        # never additional live observations or benchmark samples.
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for name in INPUTS:
                (run / name).write_bytes((self.evidence_dir / name).read_bytes())
            changed = deepcopy(self.base)
            changed['result']['network'][0]['status'] = 200
            (run / 'baseline-preflight.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'not_proven'):
                build_blocker_report(run)
            changed = deepcopy(self.base)
            changed['result']['success'] = True
            (run / 'baseline-preflight.json').write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                build_blocker_report(run)

    def test_retained_boundary_contains_no_auth_values_raw_identifiers_or_replay_key(self):
        forbidden = {'evidence_key', 'cookies', 'authorization', 'access_token', 'refresh_token',
                     'password', 'email', 'persona_id', 'account_id', 'raw_error'}
        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & forbidden)
                for field, child in value.items():
                    if field == 'session_header_present':
                        self.assertIs(type(child), bool)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        for name in (*INPUTS, 'report.json'):
            walk(load(self.evidence_dir / name))


if __name__ == '__main__':
    unittest.main()
