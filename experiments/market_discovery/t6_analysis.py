"""Offline T6 synthesis of retained observations, with no browser or network calls."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
RUNS = 'experiments/market_discovery/runs/'
INPUTS = {
    'protocol': 'docs/research/001b/protocol.json',
    'providers': RUNS+'t2-providers-20261111T212333Z/providers.json',
    'historical': RUNS+'t3-harness/historical.json',
    'local': RUNS+'t3-harness/local-latency.json',
    't4': RUNS+'t4-live-20261111T220200Z/report.json',
    'baseline': RUNS+'t4-live-20261111T220200Z/baseline-preflight.json',
    'alternative': RUNS+'t4-live-20261111T220200Z/preflight.json',
    't5': RUNS+'t5-pricing/report.json',
    'asks': 'docs/research/market/availability.json',
    'handoff': 'docs/research/obj002-handoff.md',
}
OUTPUT = ROOT / (RUNS+'t6-analysis/report.json')


def stats(values):
    values = sorted(values)
    return {'n': len(values), 'median_ms': median(values) if values else None,
            'p95_ms': values[math.ceil(.95*len(values))-1] if len(values) >= 20 else None}


def build_report():
    blobs = {key: (ROOT/path).read_bytes() for key, path in INPUTS.items()}
    d = {key: json.loads(value) for key, value in blobs.items() if key != 'handoff'}
    p, t4, t5 = d['protocol'], d['t4'], d['t5']
    # This analysis describes the retained blocked run only. Changed evidence
    # requires a fresh analysis rather than silently reusing the recommendation.
    base, alt = d['baseline'], d['alternative']['record']
    if (base['result']['network'][0]['status'] != 401 or base['result']['success']
            or alt['result']['error'] != 'schema_unrecognized'
            or t4['authenticated_observation_seconds'] != 0
            or t4['planned_observation']['windows_completed'] != 0
            or any(r['result']['auctions'] for r in (base, alt))):
        raise ValueError('Retained preflight assumptions changed; reassess live results')
    h = d['historical']
    records = h['records']
    # Recalculate coverage from rows, never from a claimed aggregate.
    rows = [a for r in records for a in r['result']['auctions']]
    auctions = {a['trade_id'] for a in rows}
    versions = {('fc27', 'pc', a['item']['definition_id']) for a in rows}
    from datetime import datetime
    seconds = (datetime.fromisoformat(records[-1]['completed_utc']) -
               datetime.fromisoformat(records[0]['submitted_utc'])).total_seconds()
    requests = sum(len(r['result']['network']) for r in records)
    historical = {
        'mode': 'HISTORICAL_REPLAY', 'started_utc': records[0]['submitted_utc'],
        'ended_utc': records[-1]['completed_utc'], 'observed_seconds': seconds,
        'EA_requests': requests, 'rows': len(rows), 'unique_auctions': len(auctions),
        'unique_versions': len(versions), 'duplicate_rows': len(rows)-len(auctions),
        'auctions_per_request': len(auctions)/requests, 'versions_per_request': len(versions)/requests,
        'auctions_per_minute': len(auctions)*60/seconds, 'versions_per_minute': len(versions)*60/seconds,
        'opportunities_per_hour': None,
    }
    strategies = [{
        'strategy': s, 'planned_windows': p['timing']['order'].count(s),
        'planned_discovery_requests': p['timing']['order'].count(s)*p['budget']['discovery_slots'],
        'planned_revalidation_requests': p['timing']['order'].count(s)*p['budget']['revalidation_slots'],
        'planned_max_requests': p['budget']['per_strategy_maximum'],
        'actual_windows': 0, 'actual_requests': 0, 'authenticated_seconds': 0,
        'unique_auctions': 0, 'unique_versions': 0,
        'auctions_per_request': None, 'versions_per_request': None,
        'auctions_per_minute': None, 'versions_per_minute': None,
        'candidate_yield': None, 'false_positive_fraction': None,
    } for s in ('A', 'B', 'C')]
    scenarios = []
    for X in p['pricing']['X_scenarios']:
        # Count unique fixture candidates, not four repeated scenario successes.
        fixture = t5['demonstration']['flows'][0]['ranked_candidates']
        count = sum(not r['identity_conflict'] and r['pricing']['scenarios'][str(X)] for r in fixture)
        replay_count = sum(not r['identity_conflict'] and r['pricing']['scenarios'][str(X)]
                           for r in t5['historical']['ranked_candidates'])
        scenarios.append({'X': X, 'live_candidates_observed': 0, 'live_opportunities_per_hour': None,
                          'historical_modeled_candidates': replay_count, 'synthetic_candidates': count,
                          'synthetic_opportunities_per_hour': None})
    local = []
    for arm in d['local']['arms']:
        local.append({'transport': arm['transport'], 'scope': 'LOCAL_SIMULATOR_ONLY',
                      'end_to_end_ms': stats([r['end_to_end_ms'] for r in arm['records']]),
                      'components': {k: stats([r['timing'][k] for r in arm['records']])
                                     for k in arm['records'][0]['timing']},
                      'errors': sum(r['error'] is not None for r in arm['records'])})
    flows = t5['demonstration']['flows']
    fixture_latency = {state: stats([next(e['elapsed_ms'] for e in f['events'] if e['state'] == state)
                                    for f in flows]) for state in [e['state'] for e in flows[0]['events']]}
    fixture_latency['search_to_prepared_intent_ms'] = stats([f['metrics']['search_to_prepared_intent_ms'] for f in flows])
    return {
        'schema': 1, 'task': 'T6', 'status': 'ANALYSIS_COMPLETE_LIVE_BENCHMARK_BLOCKED',
        'decision': 'CONDITIONAL GO', 'decision_scope': 'OFFLINE_ARCHITECTURE_IMPLEMENTATION_ONLY',
        'selected_source': 'EA_NATIVE_EXACT_FC27_PC_ASKS',
        'third_party_production_source': None, 'commercial_candidate': 'DataFluxor',
        'selected_search': 'A_TARGETED_WATCHLIST_WITH_BOUNDED_C_EXPLORATION_PROPOSED',
        'latency_choice': 'LONG_POLL_PROPOSED_SUCCESSFUL_EDGE_PATH_UNVALIDATED',
        'strategies': strategies, 'historical': historical, 'X_scenarios': scenarios,
        'live': {k: t4[k] for k in ('started_utc', 'ended_utc', 'attempt_span_seconds',
                                  'authenticated_observation_seconds', 'reason')},
        'qualifying_revalidations': 0, 'failed_qualifying_revalidations': 0,
        'false_positive_fraction': None, 'local_latency': local,
        'live_latency': t4['latency']['arms'],
        'fixture_latency_scope': 'IN_PROCESS_FIXTURE_REPLAY_NOT_EA',
        'fixture_latency': fixture_latency,
        'new_EA_requests': 0, 'account_mutations': 0,
        'inputs_sha256': {INPUTS[k]: hashlib.sha256(v).hexdigest() for k, v in blobs.items()},
    }


def cell(value):
    if value is None:
        return 'unknown'
    return f'{value:.6f}' if isinstance(value, float) else str(value)


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |'] +
                     ['| '+' | '.join(cell(v) for v in row)+' |' for row in rows])


def evidence_tables(r):
    """Exact numeric fragments checked against prose artifacts by the validator."""
    h = r['historical']
    result = {
        'budgets': table(['Strategy', 'Planned windows', 'Discovery requests', 'Revalidation requests', 'Maximum requests',
                          'Actual windows / requests / authenticated seconds'],
                         [[s['strategy'], s['planned_windows'], s['planned_discovery_requests'], s['planned_revalidation_requests'],
                           s['planned_max_requests'], '0 / 0 / 0'] for s in r['strategies']]),
        'live_coverage': table(['Strategy', 'Auctions / versions', 'Auctions/request', 'Versions/request',
                               'Auctions/minute', 'Versions/minute', 'Candidate yield', 'False positives'],
                              [[s['strategy'], '0 / 0']+[s[k] for k in ('auctions_per_request', 'versions_per_request',
                                'auctions_per_minute', 'versions_per_minute', 'candidate_yield', 'false_positive_fraction')]
                               for s in r['strategies']]),
        'historical': table(['Evidence', 'EA requests', 'Rows', 'Unique auctions', 'Unique versions',
                            'Auctions/request', 'Versions/request', 'Auctions/minute', 'Versions/minute'],
                           [['Historical only']+[h[k] for k in ('EA_requests', 'rows', 'unique_auctions', 'unique_versions',
                            'auctions_per_request', 'versions_per_request', 'auctions_per_minute', 'versions_per_minute')]]),
        'scenarios': table(['X coins', 'Live candidates observed', 'Live opportunities/hour',
                           'Historical modeled candidates', 'Synthetic candidates', 'Synthetic opportunities/hour'],
                          [[s[k] for k in ('X', 'live_candidates_observed', 'live_opportunities_per_hour',
                            'historical_modeled_candidates', 'synthetic_candidates', 'synthetic_opportunities_per_hour')]
                           for s in r['X_scenarios']]),
    }
    names = ['end_to_end_ms', 'queue_delivery_ms', 'worker_poll_to_native_ms', 'native_service_ms',
             'page_total_ms', 'result_return_ms']
    result['local_latency'] = table(['Local simulator component', 'Alarm n', 'Alarm median ms', 'Alarm p95 ms',
                                     'Long poll n', 'Long poll median ms', 'Long poll p95 ms'],
        [[name]+[value for arm in r['local_latency'] for value in
          ((arm['end_to_end_ms'] if name == 'end_to_end_ms' else arm['components'][name])[k]
           for k in ('n', 'median_ms', 'p95_ms'))] for name in names])
    result['live_latency'] = table(['Failed live arm', 'Attempts', 'EA requests', 'Round trip n / median ms / p95 ms',
                                    'Queue n / median ms / p95 ms', 'Outcome'],
        [[name, a['attempts'], a['EA_requests'],
          ' / '.join(cell(a['command_round_trip_ms'][k]) for k in ('n', 'median_ms', 'p95_ms')),
          ' / '.join(cell(a['queue_delivery_ms'][k]) for k in ('n', 'median_ms', 'p95_ms')), a['outcome']]
         for name, a in r['live_latency'].items()])
    result['fixture_latency'] = table(['Fixture stage (local Python wall time)', 'n', 'Median ms', 'p95 ms'],
        [[name]+[s[k] for k in ('n', 'median_ms', 'p95_ms')] for name, s in r['fixture_latency'].items()])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New path; exclusive creation')
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')


if __name__ == '__main__':
    main()
