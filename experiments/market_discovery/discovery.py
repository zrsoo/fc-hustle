"""Finite A/B/C plans, shared request accounting, and conservative page analysis."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
import time

from fc_access.harness import empty_result
from fc_access.pricing import MarketKey, Observation, Policy, Rules, evaluate
from .model import PROTOCOL, fresh, network_count, reply, search, sources, stamp, summary, utc


class Budget:
    """Bound both deliveries and actual foreground requests, including failed reads.

    Native side effects >1 cannot be predicted: charge all, flag overrun and stop.
    A cache/error response still spends its command slot; never makes a free retry.
    """
    def __init__(self, limit=8):
        self.limit, self.commands, self.requests, self.overrun = limit, 0, 0, False

    def reserve(self):
        if max(self.commands, self.requests) >= self.limit or self.overrun:
            raise ValueError('budget_exhausted')
        self.commands += 1

    def charge(self, result):
        self.requests += network_count(result)
        self.overrun = self.requests > self.limit


def rank(previous_block, external, now):
    """Only preceding completed block, or verified exact-PC fresh external quotes."""
    quotes = []
    if external.get('status') == 'AVAILABLE':
        for q in external.get('quotes', []):
            if (q.get('game') == 'fc27' and q.get('platform') == 'pc' and q.get('mapping_verified') is True
                    and q.get('meaning') == 'indicative_ask' and type(q.get('definition_id')) is int and q['definition_id'] > 0
                    and type(q.get('price')) is int and q['price'] > 0
                    and 0 <= (now-stamp(q['published_utc'])).total_seconds() <= 600):
                quotes.append(q)
    if quotes:
        return list(dict.fromkeys(q['definition_id'] for q in sorted(quotes, key=lambda q: (q['price'], q['definition_id']))))
    versions = {}
    for record in previous_block:
        if record['network_fresh'] and 0 <= (now-stamp(record['submitted_utc'])).total_seconds() <= 120:
            for row in record['result']['auctions'] or []:
                versions.setdefault(row['item']['definition_id'], set()).add(row['trade_id'])
    return sorted(versions, key=lambda d: (-len(versions[d]), d)) or [233731, 278230]


def plan(strategy, ranking):
    protocol = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    pairs = deepcopy(protocol['strategies'][strategy]['pairs'])
    ranking = list(dict.fromkeys(ranking + [233731, 278230]))
    for pair in pairs:
        for i in (1, 2):
            if pair.get('definition_id') == f'rank_{i}':
                pair['definition_id'] = ranking[i-1]
    return [search(pair | {'page': page, 'count': 21, 'fresh': page == 1}) for pair in pairs for page in (1, 2)]


def pagination(records):
    pages, pairs = [], []
    previous = None
    for record in records:
        rows = record['result']['auctions'] or []
        expiries = [r['expires'] for r in rows if r['expires'] is not None and r['expires'] >= 0]
        bins = [r['buy_now_price'] for r in rows if r['buy_now_price'] is not None]
        pages.append({'page': record['criteria']['page'], 'returned_rows': len(rows), 'visible_rows': min(20, len(rows)),
                      'lookahead_trade_id': rows[20]['trade_id'] if len(rows) == 21 else None,
                      'expiry_nondecreasing': all(a <= b for a, b in zip(expiries, expiries[1:])) if expiries else None,
                      'BIN_nondecreasing': all(a <= b for a, b in zip(bins, bins[1:])) if bins else None,
                      'native_has_more': record['result']['has_more'],
                      'truncation_possible': len(rows) >= 20 or record['result']['has_more'] is True,
                      'exhaustive': False})
        if previous and record['criteria']['page'] == 2 and {k:v for k,v in previous['criteria'].items() if k not in {'page','fresh'}} == {k:v for k,v in record['criteria'].items() if k not in {'page','fresh'}}:
            old = previous['result']['auctions'] or []
            overlap = sorted({r['trade_id'] for r in old} & {r['trade_id'] for r in rows})
            pairs.append({'overlap_trade_ids': overlap, 'unique_in_pair': len({r['trade_id'] for r in old + rows}),
                          'lookahead_reappeared': bool(len(old) == 21 and old[20]['trade_id'] in {r['trade_id'] for r in rows}),
                          'offset_instability_possible': True, 'exhaustive': False})
        previous = record
    return {'pages': pages, 'pairs': pairs, 'coverage_limit': 'bounded expiry-ordered offset pages; no market denominator'}


def observations(records):
    return [Observation(r['trade_id'], r['item']['item_id'], MarketKey(r['item']['definition_id'], 'pc'),
                        r['buy_now_price'], stamp(a['submitted_utc']), r['expires'], r['trade_state'] == 'active', a['network_fresh'])
            for a in records for r in (a['result']['auctions'] or [])]


def decision(records, candidate, *, now, rules=None, X=100, simulated=False):
    """No execution API. Hypothetical rules can only produce SIMULATED intents."""
    begin = time.perf_counter()
    if candidate is None:
        return {'state': 'NO_CANDIDATE', 'intent': None, 'python_compute_ms': (time.perf_counter()-begin)*1000}
    obs = observations(records)
    rule = rules.get(candidate.key.definition_id) if rules else None
    estimate = evaluate(candidate.key, obs, candidate, rule, now=now, X=X, policy=Policy(min_remaining=60))
    state = estimate.status
    if rule and not simulated:
        # T3 has no verified caps/increment capture contract. Never promote caller-supplied rules.
        state = 'RULES_NOT_VERIFIED'
    exact = [o for o in obs if o.key == candidate.key and o.trade_id == candidate.trade_id and o.item_id == candidate.item_id
             and o.buy_now_price == candidate.buy_now_price and o.active and o.network_fresh
             and 0 <= (now-o.observed_at).total_seconds() <= 30 and o.expires-(now-o.observed_at).total_seconds() > 60]
    intent = None
    same_trade = [o for o in obs if o.trade_id == candidate.trade_id]
    mismatch = any(o.key != candidate.key or o.item_id != candidate.item_id or o.buy_now_price != candidate.buy_now_price for o in same_trade)
    if mismatch:
        state = 'REVALIDATION_IDENTITY_OR_BIN_CHANGED'
    elif not exact:
        state = 'REVALIDATION_MISSING_STALE_OR_EXPIRED'
    if simulated and estimate.meets_threshold and exact and not mismatch:
        state = 'SIMULATED_INTENT_PREPARED'
        intent = {'mode': 'DRY_RUN_ONLY', 'lineage': 'SIMULATED', 'game': candidate.key.game, 'platform': candidate.key.platform,
                  'definition_id': candidate.key.definition_id, 'trade_id': candidate.trade_id, 'item_id': candidate.item_id,
                  'buy_now_price': candidate.buy_now_price, 'target_sale_price': estimate.target_sale_price,
                  'expected_profit': estimate.expected_profit, 'X': X, 'subsequent_listing': 'PROPOSED_ONLY'}
    return {'state': state, 'estimate': asdict(estimate), 'intent': intent, 'python_compute_ms': (time.perf_counter()-begin)*1000}


def metrics(records):
    rows = [(a, r) for a in records for r in (a['result']['auctions'] or [])]
    auctions = {r['trade_id'] for _, r in rows}
    versions = {('fc27', 'pc', r['item']['definition_id']) for _, r in rows}
    identities = {}
    items = {}
    for _, row in rows:
        identities.setdefault(row['trade_id'], set()).add((row['item']['item_id'], row['item']['definition_id'], row['buy_now_price']))
        items.setdefault(row['item']['item_id'], set()).add(row['trade_id'])
    requests = sum(network_count(a['result']) for a in records)
    elapsed = (stamp(records[-1]['completed_utc'])-stamp(records[0]['submitted_utc'])).total_seconds() if records else 0
    coverage = Counter(json.dumps({k:v for k,v in a['criteria'].items() if k != 'fresh'}, sort_keys=True) for a in records)
    return {'commands': len(records), 'EA_requests': requests, 'responses': sum(a['result']['status'] is not None for a in records),
            'response_rows': len(rows), 'response_bytes': sum(a['response_bytes'] for a in records),
            'unique_auctions': len(auctions), 'unique_versions': len(versions),
            'unique_auctions_per_EA_request': len(auctions)/requests if requests else None,
            'unique_versions_per_EA_request': len(versions)/requests if requests else None,
            'observed_seconds': elapsed, 'unique_auctions_per_wall_minute': 60*len(auctions)/elapsed if elapsed else None,
            'unique_versions_per_wall_minute': 60*len(versions)/elapsed if elapsed else None,
            'duplicate_fraction': 1-len(auctions)/len(rows) if rows else None,
            'conflicting_auctions': sum(len(v)>1 for v in identities.values()),
            'physical_items_with_multiple_auctions': sum(len(v)>1 for v in items.values()),
            'errors': dict(Counter(a['result']['error'] for a in records if a['result']['error'])),
            'cache_only': sum(a['result']['success'] and not a['network_fresh'] for a in records),
            'empty_success': sum(a['result']['success'] and not a['result']['auctions'] for a in records),
            'fresh_network_responses': sum(a['network_fresh'] for a in records),
            'freshness_age_upper_bound_seconds': [(stamp(a['completed_utc'])-stamp(a['submitted_utc'])).total_seconds() for a in records],
            'remaining_expiry_lower_bound_seconds': [r['expires']-(stamp(a['completed_utc'])-stamp(a['submitted_utc'])).total_seconds() for a,r in rows if r['expires'] is not None],
            'coverage_by_filter_page': dict(coverage),
            'coverage_by_version': dict(Counter(str(r['item']['definition_id']) for _,r in rows)),
            'native_status_counts': dict(Counter(str(a['result']['status']) for a in records)),
            'HTTP_status_counts': dict(Counter(str(n['status']) for a in records for n in a['result']['network'])),
            'background_EA_requests': None, 'comparison_status': 'CONFOUNDED_BACKGROUND_UNMEASURED',
            'candidate_yield_by_X': {str(x): None for x in (100,250,500,1000)}, 'live_arrival_rate_per_hour': None,
            'latency': {k: summary([a['timing'].get(k) for a in records]) for k in
                        ('queue_delivery_ms','worker_poll_to_native_ms','native_service_ms','result_return_ms','python_compute_ms','time_to_first_result_ms','search_to_intent_ms')}}


class Runner:
    def __init__(self, transport, *, mode, clock=None, availability=None):
        if mode not in {'SIMULATED', 'LIVE_READ_ONLY'}:
            raise ValueError('invalid_mode')
        from .replay import Clock
        self.transport, self.mode, self.clock = transport, mode, clock or Clock()
        self.availability = availability or sources()
        self.key = __import__('secrets').token_hex(16)
        self.records = []

    def read(self, params, budget, strategy, window, slot):
        search(params)
        budget.reserve()
        submitted, start = self.clock.utc(), self.clock.perf_counter()
        try:
            value = reply(self.transport.search(params, self.key))
        except Exception:
            # Malformed responses/exception text may contain secrets. Retain only a
            # fixed error; its delivered slot is still spent and the run will stop.
            value = {'result': empty_result('schema_unrecognized'), 'timing': {
                'worker_poll_to_native_ms': None, 'native_service_ms': None, 'page_total_ms': None}}
        result = value['result']
        for row in result['auctions'] or []:
            item, price = row['item'], row['buy_now_price']
            if (any(item[k] != params[k] for k in ('definition_id','club','league') if k in params)
                    or price is None or not params.get('min_buy', 0) <= price <= params.get('max_buy', 2**53-1)):
                # A previously verified DTO filter can drift. Do not score such rows.
                result.update(success=False, error='schema_unrecognized', auctions=None)
                break
        elapsed = (self.clock.perf_counter()-start)*1000
        result, timing = value['result'], dict(value['timing'])
        budget.charge(result)
        timing.update(getattr(self.transport, 'last_timing', {}))
        timing.update(python_compute_ms=None, search_to_intent_ms=None, time_to_first_result_ms=elapsed)
        record = {'schema': 1, 'mode': self.mode, 'strategy': strategy, 'window': window, 'slot': slot,
                  'game': 'fc27', 'platform': 'pc', 'criteria': params, 'submitted_utc': submitted,
                  'completed_utc': self.clock.utc(), 'elapsed_ms': elapsed, 'network_fresh': fresh(result),
                  'response_bytes': len(json.dumps(value, separators=(',', ':')).encode()), 'result': result, 'timing': timing}
        self.records.append(record)
        return record

    def run(self, windows=9, paced=False):
        protocol = json.loads(PROTOCOL.read_text(encoding='utf-8'))
        if not 1 <= windows <= 9 or self.mode == 'LIVE_READ_ONLY' and not paced:
            raise ValueError('live_requires_protocol_pacing')
        previous_block, current_block, window_summaries = [], [], []
        origin = self.clock.perf_counter()
        stop = None
        for w, strategy in enumerate(protocol['timing']['order'][:windows]):
            if w and w % 3 == 0:
                previous_block, current_block = current_block, []
            ranking = rank(previous_block, self.availability['external'], stamp(self.clock.utc()))
            params = plan(strategy, ranking)
            budget, window_records = Budget(), []
            candidate, first_start = None, None
            for slot in range(8):
                if paced:
                    due = origin + w*300 + slot*30
                    remaining = due-self.clock.perf_counter()
                    if remaining < -1:  # skip missed slots; never catch up
                        continue
                    while remaining > 0:
                        self.clock.sleep(min(remaining, 1))
                        remaining = due-self.clock.perf_counter()
                if slot >= 6:
                    if candidate is None:
                        continue
                    request = {'definition_id': candidate.key.definition_id, 'max_buy': candidate.buy_now_price,
                               'page': slot-5, 'count': 21, 'fresh': slot == 6}
                else:
                    request = params[slot]
                record = self.read(request, budget, strategy, w, slot)
                window_records.append(record)
                rows = observations([record])
                if first_start is None:
                    first_start = record['submitted_utc']
                if slot < 6:
                    valid = [o for o in rows if o.active and o.buy_now_price and o.network_fresh and o.expires is not None and o.expires > 60]
                    if valid:
                        candidate = min(([candidate] if candidate else []) + valid, key=lambda o: (o.buy_now_price, o.trade_id))
                else:
                    decision_result = decision([r for r in window_records if r['slot'] >= 6], candidate, now=stamp(record['completed_utc']))
                    record['decision'] = decision_result
                    record['timing']['python_compute_ms'] = decision_result['python_compute_ms']
                    # Never fill complete intent timing when no intent was prepared.
                    record['timing']['search_to_intent_ms'] = None
                status = record['result']['status']
                network_stop = any(n['status'] in (401,403,429) or n['status'] >= 500 for n in record['result']['network'])
                if budget.overrun or network_stop or not record['result']['success'] or status in (401,403,429) or status and status >= 500:
                    stop = 'budget_overrun' if budget.overrun else record['result']['error'] or 'native_status_stop'
                    break
            current_block.extend(window_records)
            window_summaries.append({'strategy': strategy, 'window': w, 'ranking': ranking, 'budget': vars(budget),
                                     'metrics': metrics(window_records), 'pagination': pagination(window_records),
                                     'revalidation': 'DIAGNOSTIC_ONLY_RULES_UNAVAILABLE'})
            if stop:
                break
        availability = deepcopy(self.availability)
        availability['EA']['status'] = ('SIMULATED_NOT_LIVE' if self.mode == 'SIMULATED' else
                                        'OBSERVED_READ_ONLY' if any(r['network_fresh'] for r in self.records) else 'UNAVAILABLE')
        availability['EA']['live_samples'] = sum(r['network_fresh'] for r in self.records) if self.mode == 'LIVE_READ_ONLY' else 0
        result = {'schema': 1, 'mode': self.mode, 'status': 'PARTIAL' if stop or windows < 9 else 'BOUNDED_REPLAY' if self.mode == 'SIMULATED' else 'PARTIAL_DESCRIPTIVE_ONLY',
                  'stop_reason': stop, 'protocol_sha256': hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
                  'source_availability': availability, 'records': self.records, 'windows': window_summaries,
                  'overall': metrics(self.records), 'live_opportunity_yield': None, 'account_mutations': 0}
        result['by_strategy'] = {s: metrics([r for r in self.records if r['strategy'] == s]) for s in 'ABC'}
        return result
