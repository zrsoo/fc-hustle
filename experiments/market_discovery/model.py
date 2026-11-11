"""Strict sanitized boundary shared by replay, strategies and localhost transport."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from fc_access.harness import command, integer, validate_result

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / 'docs/research/001b/protocol.json'
PROVIDERS = ROOT / 'experiments/market_discovery/runs/t2-providers-20261111T212333Z/providers.json'
TIMINGS = {'worker_poll_to_native_ms', 'native_service_ms', 'page_total_ms'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result


def search(params):
    command('search', params)
    if set(params) - {'definition_id', 'club', 'league', 'min_buy', 'max_buy', 'page', 'count', 'fresh'}:
        raise ValueError('unverified_filter')
    if params.get('count') != 21 or params.get('page') not in (1, 2) or type(params.get('fresh')) is not bool:
        raise ValueError('bounded_pages_required')
    return dict(params)


def envelope(value):
    if not isinstance(value, dict) or set(value) != {'id', 'evidence_key', 'operation', 'params'}:
        raise ValueError('invalid_command')
    if value['operation'] != 'search':
        raise ValueError('search_only')
    for key in ('id', 'evidence_key'):
        if not isinstance(value[key], str) or not re.fullmatch('[a-f0-9]{32}', value[key]):
            raise ValueError('invalid_id')
    search(value['params'])
    return value


def timing(value):
    if not isinstance(value, dict) or set(value) != TIMINGS:
        raise ValueError('invalid_timing')
    for duration in value.values():
        if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 120000):
            raise ValueError('invalid_timing')
    return dict(value)


def reply(value):
    if not isinstance(value, dict) or set(value) != {'result', 'timing'}:
        raise ValueError('invalid_reply')
    validate_result(value['result'])
    timing(value['timing'])
    result = value['result']
    if result['platform'] not in ('pc', None) or result['auctions'] and result['platform'] != 'pc':
        raise ValueError('market_mismatch')
    if result['success'] and (result['platform'] != 'pc' or result['auctions'] is None or result['items'] is not None or result['credits'] is not None):
        raise ValueError('market_mismatch')
    if len(result['auctions'] or []) > 21:
        raise ValueError('page_limit')
    for row in result['auctions'] or []:
        if row['trade_id'] is None or row['item']['item_id'] is None or not integer(row['item']['definition_id'], 1):
            raise ValueError('identity_required')
    return value


def sources():
    providers = json.loads(PROVIDERS.read_text(encoding='utf-8'))
    return {'EA': {'status': 'NOT_CHECKED', 'game': 'fc27', 'platform': 'pc', 'live_samples': 0},
            'external': {'status': 'UNAVAILABLE', 'quotes': [], 'evidence': str(PROVIDERS.relative_to(ROOT)).replace('\\', '/'),
                         'production_feed_retrieved': providers['measured']['usable_broad_fc27_pc_feed_retrieved'],
                         'providers': [{'id': p['id'], 'status': p['status']} for p in providers['providers']]}}


def network_count(result):
    return len(result['network'])


def fresh(result):
    return result['success'] and any(n['path'] == '/ut/game/fc27/transfermarket' and n['status'] == 200 for n in result['network'])


def summary(values):
    values = sorted(v for v in values if v is not None)
    n = len(values)
    return {'n': n, 'median_ms': (values[(n-1)//2] + values[n//2])/2 if n else None,
            'p95_ms': values[math.ceil(.95*n)-1] if n >= 20 else None,
            'p95_method': 'nearest_rank_ceil_0.95_n; n>=20'}
