"""Replay the retained T4 access failure. This command makes no live requests.

Only a proven authentication failure can produce this blocker report. The T3
runner remains the bounded observer to use after normal access is restored.
"""
import argparse
import hashlib
import json
from pathlib import Path

from fc_access.harness import validate_result
from .model import PROTOCOL, ROOT, stamp, summary

RUN = Path('experiments/market_discovery/runs/t4-live-20261111T220200Z')
INPUTS = ('access-inspection.json', 'preflight.json', 'baseline-preflight.json',
          'access-end.json', 'auth-stop-health.json')
SOURCES = ('docs/research/001b/protocol.json',
           'experiments/market_discovery/browser/page.js',
           'experiments/market_discovery/browser/worker.js',
           'experiments/market_discovery/browser/manifest.json',
           'browser/read-bridge/page.js', 'browser/read-bridge/worker.js',
           'browser/transaction-bridge/worker.js')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def build_blocker_report(run):
    access = load(run / 'access-inspection.json')
    alternative = load(run / 'preflight.json')['record']
    baseline = load(run / 'baseline-preflight.json')
    for result in (baseline['result'], alternative['result']):
        validate_result(result)
    auth_failures = [n for n in baseline['result']['network']
                     if n['path'] == '/ut/game/fc27/transfermarket'
                     and n['status'] == 401 and n['session_header_present'] is True]
    if not auth_failures or baseline['result']['success'] or alternative['result']['success']:
        raise ValueError('retained_authentication_blocker_not_proven')
    protocol = load(PROTOCOL)
    started = alternative['submitted_utc']
    ended = baseline['completed_utc']
    rows = [row for result in (baseline['result'], alternative['result'])
            for row in result['auctions'] or []]
    if rows:
        raise ValueError('candidate_evidence_requires_revalidation_analysis')
    arms = {}
    for name, record in (('alarm_30s', baseline), ('long_poll', alternative)):
        timing = record.get('timing', {})
        arms[name] = {
            'attempts': 1, 'fresh_authenticated_results': 0,
            'EA_requests': len(record['result']['network']),
            'command_round_trip_ms': summary([record['elapsed_ms']]),
            'time_to_first_successful_result_ms': summary([]),
            'queue_delivery_ms': summary([timing.get('queue_delivery_ms')]),
            'native_service_ms': summary([timing.get('native_service_ms')]),
            'local_result_return_ms': summary([timing.get('result_return_ms')]),
            'EA_server_latency_ms': summary([]),
            'sanitized_response_bytes': record['response_bytes'],
            'EA_wire_response_bytes': None,
            'outcome': record['result']['error'],
        }
    return {
        'schema': 1, 'task': 'T4', 'mode': 'LIVE_READ_ONLY', 'status': 'BLOCKED',
        'reason': 'EA_AUTHENTICATION_REJECTED_401',
        'started_utc': started, 'ended_utc': ended,
        'attempt_span_seconds': (stamp(ended) - stamp(started)).total_seconds(),
        'command_wait_seconds': (alternative['elapsed_ms'] + baseline['elapsed_ms']) / 1000,
        'authenticated_observation_seconds': 0,
        'target_observation_seconds': 1800,
        'attachment': {
            'normal_reattachment': access['normal_reattachment'],
            'health': access['search_bridge_health'],
            'authenticated': False,
            'proof': 'baseline-preflight.json#/result/network/0',
            'badge_or_health_establishes_authentication': False,
        },
        'alternative_guard': {
            'error': alternative['result']['error'],
            'native_started': alternative['timing']['native_service_ms'] is not None,
            'EA_requests': len(alternative['result']['network']),
            'source': 'experiments/market_discovery/browser/page.js',
            'inference': 'The pre-native schema failure is at the selected-persona PC guard; raw persona values were not exported. This is separate from the independently observed EA 401.',
            'guard': "persona.platform === 'pc' || (persona.platform == null && persona.isPC === true)",
        },
        'planned_observation': {
            'status': 'NOT_STARTED_PREFLIGHT_FAILED',
            'windows_requested': 9, 'windows_completed': 0,
            'order': protocol['timing']['order'],
            'window_seconds': protocol['timing']['window_seconds'],
            'minimum_gap_seconds': protocol['timing']['minimum_submission_gap_seconds'],
            'max_in_flight': 1,
            'EA_request_budget_per_window': protocol['budget']['per_window'],
            'EA_request_budget_per_strategy': protocol['budget']['per_strategy_maximum'],
            'filters_and_pages': {
                'strategies': protocol['strategies'], 'pages': protocol['search_pair']['pages'],
                'count': protocol['search_pair']['count'],
            },
            'actual_strategy_windows': [], 'actual_matched_blocks': 0,
            'preflight_budget_separate': True,
            'EA_request_budget_per_preflight_arm': 1,
            'comparison': 'UNAVAILABLE_NO_MATCHED_LIVE_WINDOWS',
        },
        'observed': {
            'commands': 2, 'EA_requests': sum(a['EA_requests'] for a in arms.values()),
            'fresh_authenticated_results': 0, 'rows': 0,
            'unique_auctions': 0, 'exact_versions': [],
            'duplicate_fraction': None, 'observation_age_seconds': [],
            'expiry_seconds': [], 'errors': {'schema_unrecognized': 1, 'HTTP_401': 1},
            'coverage': {'attempted': [alternative['criteria'], baseline['criteria']],
                         'successful_filter_page_combinations': [], 'market_denominator': None},
            'EA_wire_response_bytes': None,
            'sanitized_response_bytes': sum(a['sanitized_response_bytes'] for a in arms.values()),
            'account_mutations': 0,
        },
        'latency': {
            'arms': arms, 'p95_min_samples': 20,
            'p95_method': 'nearest_rank_ceil_0.95_n',
            'native_is_EA_server_latency': False,
            'subtract_assumed_alarm_delay': False,
            'live_speedup': None,
            'interpretation': 'Failed command round trips only. The long-poll queue delivery is local Edge evidence. No successful-result, native-service or EA-only latency was measured. Baseline includes an unseparated alarm wait and the failed native read.',
        },
        'revalidation': {
            'status': 'UNAVAILABLE_NO_FRESH_CANDIDATES', 'fresh_candidates': 0,
            'attempts': 0, 'results': [],
            'outcomes': {k: None for k in ('unchanged', 'BIN_changed', 'identity_changed',
                                          'expired', 'unavailable_auction')},
            'limitation': 'No auctions were returned; no changed-BIN, identity, expiry or unavailable-auction outcome was observed. Absence in bounded offset pages would not prove sale or market-wide absence.',
        },
        'prerequisites': [
            'Restore a valid EA session through normal Web App sign-in, completing any EA challenge normally; the stale rendered market UI and attached health are insufficient.',
            'Select the FC27 PC persona and normally reattach the separate discovery extension on the official HTTPS Web App. Verify a fresh authenticated HTTP 200 market GET before starting windows.',
            'Resolve the selected-persona schema guard through a reviewed read-only platform projection if normal PC selection still fails. Do not force or bypass the platform guard.',
            'For baseline/alternative comparison, use the reviewed instrumented alarm_30s and long_poll modes, reload/reattach normally, and retain identical EA request caps and minimum 30-second pacing.',
        ],
        'coverage_limitations': [
            'Zero seconds of authenticated live observation; the 30-minute target and all alternating A/B/C windows remain unobserved.',
            'Two preflight commands, one EA request returning 401; no retries after that authentication failure.',
            'The baseline is the existing read-only alarm bridge. Its native and local timing components cannot be separated. It is not a matched experiment against the instrumented alternative.',
            'Response sizes are sanitized projected JSON bytes, not EA wire bytes; EA wire sizes and server latency are unknown.',
            'Background EA traffic was not measured. Coverage denominators, auction yield, profitability, arrival rate and throughput are unavailable.',
            'Historical and synthetic T3 runs were not added to the live samples. No mocks substitute for live evidence.',
            'The two preflights use independent pseudonym keys and cannot establish cross-arm auction identity or deduplication.',
            'T3 preflight window -1 is an out-of-window marker, not a completed observation window.',
        ],
        'throughput_benchmark_success': False,
        'inputs_sha256': {name: digest(run / name) for name in INPUTS},
        'sources_sha256': {name: digest(ROOT / name) for name in SOURCES},
        'replay': ['{python}', '-m', 'experiments.market_discovery.t4_evidence',
                   '--run', str(run.relative_to(ROOT)).replace('\\', '/'),
                   '--output', 'private-captures/t4-report-replay.json'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=RUN)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build_blocker_report(args.run.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'reason': report['reason'],
                      'authenticated_observation_seconds': 0}))
    return 0  # Successful offline replay of a BLOCKED experiment, not live success.


if __name__ == '__main__':
    raise SystemExit(main())
