"""Synthetic strategy exercise and faithful historical page analysis; no sockets."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time

from fc_access.harness import empty_result, project_auction, validate_result
from .discovery import metrics, pagination
from .model import ROOT, fresh, search, sources


class Clock:
    def utc(self):
        return datetime.now(timezone.utc).isoformat()

    perf_counter = staticmethod(time.perf_counter)
    sleep = staticmethod(time.sleep)


class FixtureClock:
    def __init__(self):
        self.seconds = 0
        self.epoch = datetime(2026, 11, 11, 22, tzinfo=timezone.utc)

    def utc(self):
        return (self.epoch+timedelta(seconds=self.seconds)).isoformat()

    def perf_counter(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


class FixtureTransport:
    """Deterministic SIMULATED expiry-ordered listings. Not live evidence."""
    def __init__(self, clock, opportunity=False):
        self.clock, self.calls = clock, []
        self.opportunity = opportunity
        self.last_timing = {'queue_delivery_ms': 3, 'result_return_ms': 2}

    def search(self, params, evidence_key):
        search(params)
        self.calls.append(deepcopy(params))
        self.clock.sleep(.05)
        rows = []
        for version in (233731, 278230, 50596300):
            for i in range(45):
                price = (5000 if version == 233731 else 2500 if version == 278230 else 6500) + (i % 8)*100
                if self.opportunity and version == 233731:
                    price = 500 if i == 0 else 3000 + (i % 8)*100
                raw = {'tradeId': str(version*1000+i), 'buyNowPrice': price, 'startingBid': price-100,
                       'currentBid': 0, 'expires': 100+i*10, 'tradeState': 'active', 'bidState': 'none',
                       'itemData': {'id': str(version*10000+i), 'definitionId': version, 'assetId': 233731,
                                    'teamId': 9 if version == 233731 else 2, 'leagueId': 13}}
                row = project_auction(raw, evidence_key)
                item = row['item']
                if any(item[k] != params[k] for k in ('definition_id','club','league') if k in params):
                    continue
                if not params.get('min_buy', 0) <= price <= params.get('max_buy', 15000000):
                    continue
                rows.append(row)
        # Pseudonyms use a fresh per-run salt. Sorting equal-expiry fixtures by
        # those hashes changes page membership and adaptive coverage each run.
        # The public exact version is stable, and expiry is unique per version.
        rows.sort(key=lambda r: (r['expires'], r['item']['definition_id']))
        offset = (params['page']-1)*20
        result = empty_result(None)
        result.update(success=True, status=200, platform='pc', auctions=rows[offset:offset+21],
                      has_more=len(rows)>offset+20, cache_invalidated=params['fresh'], network=[{
                          'host':'utas.mob.v1.prd.futc-ext.gcp.ea.com', 'path':'/ut/game/fc27/transfermarket',
                          'status':200, 'session_header_present':True}])
        return {'result': validate_result(result), 'timing': {'worker_poll_to_native_ms': 4, 'native_service_ms': 40, 'page_total_ms': 41}}


def historical(path=ROOT/'docs/research/market/availability.json'):
    payload = path.read_bytes()
    evidence = json.loads(payload)
    records = []
    for a in evidence['attempts']:
        if a['operation'] != 'search':
            continue
        result = validate_result(a['result'])
        started = datetime.fromisoformat(a['at'])
        record = {'schema': 1, 'mode': 'HISTORICAL_REPLAY', 'strategy': 'HISTORICAL_UNMATCHED', 'window': None, 'slot': None,
                  'game':'fc27', 'platform':'pc', 'criteria': search(a['request']), 'submitted_utc': a['at'],
                  'completed_utc': (started+timedelta(milliseconds=a['elapsed_ms'])).isoformat(),
                  'elapsed_ms': a['elapsed_ms'], 'network_fresh': fresh(result), 'result': result,
                  'response_bytes':len(json.dumps(result, separators=(',', ':')).encode()),
                  'timing': {'time_to_first_result_ms':a['elapsed_ms']}}
        records.append(record)
    return {'schema':1, 'mode':'HISTORICAL_REPLAY', 'status':'DESCRIPTIVE_ONLY_UNMATCHED_BUDGETS',
            'source_path':str(path.relative_to(ROOT)).replace('\\','/'), 'source_sha256':hashlib.sha256(payload).hexdigest(),
            'source_availability':sources(), 'new_live_samples':0, 'account_mutations':0,
            'records':records, 'overall':metrics(records), 'pagination':pagination(records),
            'latency_note':'Historical end-to-end waiting only. Component times unmeasured, never inferred by subtracting 30s.'}
