"""Reproduce T5 evidence offline: python -m experiments.market_discovery.t5_pricing.

No connection or browser attachment is attempted. T4's retained authentication
failure supplies the live availability branch; synthetic success stays separate.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from fc_access.harness import empty_result, project_auction
from fc_access.pricing import MarketKey, Rules
from .discovery import Budget, Runner
from .model import ROOT, sources, stamp
from .opportunity import SCENARIOS, normalized, price_candidate, rank_candidates, run_flow
from .replay import FixtureClock, historical
from .t4_evidence import build_blocker_report

FIXTURE = ROOT/'experiments/market_discovery/fixtures/t5-opportunities.json'
T4 = ROOT/'experiments/market_discovery/runs/t4-live-20261111T220200Z'
T2 = ROOT/'experiments/market_discovery/runs/t2-providers-20261111T212333Z'
OUTPUT = ROOT/'experiments/market_discovery/runs/t5-pricing/report.json'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def simulated_reader():
    fixture = load(FIXTURE)
    if fixture['mode'] != 'SIMULATED' or fixture['lineage'] != 'DETERMINISTIC_SYNTHETIC_NOT_LIVE':
        raise ValueError('fixture_lineage')
    clock = FixtureClock()
    clock.epoch = stamp(fixture['now'])
    class Transport:
        def search(self, params, evidence_key):
            clock.sleep(.05)  # deterministic modeled service delay; no wall-clock wait
            rows = []
            for market in fixture['markets']:
                version = market['definition_id']
                if params.get('definition_id', version) != version: continue
                for i, price in enumerate([market['acquisition']]+market['asks']):
                    rows.append(project_auction({
                        'tradeId': str(version*100+i), 'buyNowPrice': price, 'startingBid': price,
                        'currentBid': 0, 'expires': 180+i-int(clock.seconds), 'tradeState': 'active', 'bidState': 'none',
                        'itemData': {'id': str(version*1000+i), 'definitionId': version, 'leagueId': 13}}, evidence_key))
            r = empty_result(None)
            r.update(success=True, status=200, platform='pc', auctions=rows, has_more=False,
                     cache_invalidated=True, network=[{'host': 'utas.mob.v1.prd.futc-ext.gcp.ea.com',
                         'path': '/ut/game/fc27/transfermarket', 'status': 200, 'session_header_present': True}])
            return {'result': r, 'timing': {'worker_poll_to_native_ms': 4, 'native_service_ms': 40, 'page_total_ms': 41}}
    runner = Runner(Transport(), mode='SIMULATED', clock=clock)
    runner.key = '5'*32  # fixed pseudonyms ONLY for these explicitly synthetic fixtures
    budget = Budget(2)
    def read(params):
        return runner.read(params, budget, 'B' if not runner.records else 'A', 0, len(runner.records))
    rules = {MarketKey(m['definition_id'], 'pc'): Rules(MarketKey(m['definition_id'], 'pc'),
             150, 15000000, clock.epoch) for m in fixture['markets']}
    return read, clock, rules


def source_snapshot():
    """Include actually accessible sandbox rows as REJECTED diagnostics only."""
    external = deepcopy(sources()['external'])
    sandbox = load(T2/'sandbox-prices.json')
    external['quotes'] = [{'source': 'datafluxor_retained_sandbox', 'sandbox': sandbox['sandbox'],
        'game': q['game'], 'platform': q['platform'], 'definition_id': q['ea_id'],
        'mapping_verified': False, 'meaning': 'indicative_ask', 'price': q['price'],
        'published_utc': q['observed_at']} for q in sandbox['data']['items']]
    return external


def historical_comparison(external):
    replay = historical()
    records = replay['records']
    # Evaluate at retained time, never relabel historical asks as fresh today.
    now = max(stamp(r['completed_utc']) for r in records)
    keys = {r.key for r in normalized(records)}
    rules = {key: Rules(key, 150, 15000000, now) for key in keys}
    markets = []
    rows = normalized(records)
    for key in sorted(keys, key=lambda k: k.definition_id):
        candidate = min((r for r in rows if r.key == key), key=lambda r: (r.buy_now_price, r.trade_id))
        markets.append({'key': asdict(key), 'candidate_trade_id': candidate.trade_id,
                        'missing_observed_rules': price_candidate(rows, candidate, None, now=now, X=100, external=external),
                        'hypothetical_rules_only': price_candidate(rows, candidate, rules[key], now=now, X=100, external=external)})
    return {'mode': 'HISTORICAL_REPLAY', 'evaluated_at': now.isoformat(), 'new_live_samples': 0,
            'rules_status': 'HYPOTHETICAL_NOT_OBSERVED', 'markets': markets,
            'ranked_candidates': rank_candidates(records, rules, now=now, X=100, external=external),
            'discovery': replay['overall'], 'live_yield_contribution': 0}


def build_report():
    # This recomputes T4 against raw preflights and verifies the retained blocker.
    live = build_blocker_report(T4)
    if live['observed']['rows'] or live['observed']['fresh_authenticated_results']:
        raise ValueError('live_evidence_changed_review_candidates_before_simulated_fallback')
    external = source_snapshot()
    flows = []
    for X in SCENARIOS:
        read, clock, rules = simulated_reader()
        flows.append(run_flow(read, mode='SIMULATED', rules=rules, clock=clock, X=X, external=external))
    paths = [FIXTURE, ROOT/'fc_access/pricing.py', ROOT/'docs/research/market/availability.json',
             ROOT/'experiments/market_discovery/opportunity.py', Path(__file__),
             T2/'providers.json', T2/'sandbox-prices.json', T4/'report.json', T4/'preflight.json',
             T4/'baseline-preflight.json']
    return {'schema': 1, 'task': 'T5', 'status': 'RESEARCH_PROTOTYPE_COMPLETE',
            'live': {'status': 'UNOBSERVED', 'qualifying_candidates_observed': 0, 'opportunities_per_hour': None,
                     'authenticated_observation_seconds': live['authenticated_observation_seconds'],
                     'fresh_auctions': live['observed']['rows'], 'prepared_intents': 0,
                     'reason': live['reason'], 'evidence': str((T4/'report.json').relative_to(ROOT)).replace('\\', '/'),
                     'current_authentication': 'NOT_RECHECKED_T5', 'new_EA_requests': 0},
            'external': external, 'historical': historical_comparison(external),
            'demonstration': {'mode': 'SIMULATED', 'lineage': 'DETERMINISTIC_SYNTHETIC_NOT_LIVE',
                              'rules': 'HYPOTHETICAL_NOT_EA_VERIFIED', 'flows': flows,
                              'latency_note': 'Actual local Python replay wall time. Record service timings are modeled fixture values, not EA or live latency.'},
            'account_mutations': 0, 'production_executor': False,
            'inputs_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New JSON path; exclusive creation')
    args = parser.parse_args()
    # Fail before computation and never overwrite a retained run.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(build_report(), out, indent=2, allow_nan=False)
        out.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
