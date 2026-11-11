"""Finite research scoring and read-only revalidation. Intents are inert JSON.

The baseline calculator is authoritative; alternative estimators are diagnostics.
There is no transaction client, scheduler, retry loop, or execution callback here.
"""
from collections import defaultdict
from dataclasses import asdict
from fractions import Fraction
from statistics import median
import time

from fc_access.pricing import MarketKey, Policy, evaluate, floor_price, profit
from .model import TIMINGS, fresh, reply, search, stamp, summary
from .discovery import observations

SCENARIOS = (100, 250, 500, 1000)
POLICY = Policy(min_remaining=60)
UNCERTAINTY = [
    'BOUNDED_EXPIRY_ORDERED_SAMPLE', 'FILTER_AND_PRICE_CEILING_BIAS_POSSIBLE',
    'ASKS_NOT_COMPLETED_SALES', 'LIQUIDITY_UNKNOWN', 'SELL_THROUGH_UNMEASURED',
    'ASSUMES_SALE_AT_TARGET_NO_RELIST_COST', 'CALLER_SUPPLIED_CAPS',
    'FULL_INCREMENT_SCHEDULE_UNVERIFIED', 'TAX_ROUNDING_EMPIRICALLY_UNVERIFIED',
]


def normalized(records):
    """Accept the existing sanitized FC27 PC boundary, never force a platform."""
    for record in records:
        if (record['game'] != 'fc27' or record['platform'] != 'pc' or
                record['mode'] not in ('SIMULATED', 'LIVE_READ_ONLY', 'HISTORICAL_REPLAY')):
            raise ValueError('market_or_lineage_mismatch')
        search(record['criteria'])
        reply({'result': record['result'], 'timing': {k: record['timing'].get(k) for k in TIMINGS}})
        if stamp(record['submitted_utc']) > stamp(record['completed_utc']):
            raise ValueError('reversed_read_time')
        if type(record['network_fresh']) is not bool or record['network_fresh'] != fresh(record['result']):
            raise ValueError('freshness_evidence_mismatch')
    return observations(records)


def external_comparison(snapshot, key, now, target):
    """Audit every supplied reference; none can replace EA comparables or rules."""
    reviews = []
    for q in snapshot.get('quotes', []):
        reasons = []
        if snapshot.get('status') != 'AVAILABLE': reasons.append('SOURCE_UNAVAILABLE')
        if q.get('sandbox') is not False: reasons.append('SANDBOX_OR_LINEAGE_UNKNOWN')
        if q.get('game') != key.game: reasons.append('GAME_MISMATCH')
        if q.get('platform') != key.platform: reasons.append('PLATFORM_MISMATCH')
        if type(q.get('definition_id')) is not int or q.get('definition_id') != key.definition_id:
            reasons.append('EXACT_VERSION_MISMATCH')
        if q.get('mapping_verified') is not True: reasons.append('MAPPING_UNVERIFIED')
        if q.get('meaning') != 'indicative_ask': reasons.append('PRICE_MEANING_UNSUPPORTED')
        if type(q.get('price')) is not int or q['price'] <= 0: reasons.append('INVALID_PRICE')
        try:
            age = (now-stamp(q['published_utc'])).total_seconds()
            if not 0 <= age <= 600: reasons.append('STALE_OR_FUTURE_QUOTE')
        except (ValueError, TypeError, KeyError):
            age = None
            reasons.append('MISSING_OR_INVALID_PUBLICATION_TIME')
        usable = not reasons
        reviews.append({'source': q.get('source'), 'price': q.get('price'), 'age_seconds': age,
                        'usable': usable, 'reasons': reasons,
                        'target_minus_reference': target-q['price'] if usable and target is not None else None})
    return {'status': snapshot.get('status', 'UNAVAILABLE'), 'evidence': snapshot.get('evidence'),
            'usable_references': sum(r['usable'] for r in reviews), 'reviews': reviews,
            'role': 'DIAGNOSTIC_ONLY_NEVER_FILLS_MISSING_EA_SAMPLES'}


def comparable_prices(rows, candidate, rules, now):
    """Diagnostic cohort with eligibility delegated to pricing.evaluate itself.

    Passing each row as acquisition with no comparables exposes baseline validity
    without maintaining a second implementation of age/cap/increment checks.
    Duplicate/conflict handling and MAD follow the documented baseline contract.
    The caller checks the resulting sample count against the authoritative result.
    """
    trades, items = defaultdict(list), defaultdict(set)
    for r in rows:
        trades[r.trade_id].append(r)
        items[r.item_id].add(r.trade_id)
    prices = []
    for copies in trades.values():
        if any(r.trade_id == candidate.trade_id or r.item_id == candidate.item_id for r in copies):
            continue
        if len({(r.key, r.item_id, r.buy_now_price) for r in copies}) != 1 or any(len(items[r.item_id]) > 1 for r in copies):
            continue
        valid = [r for r in copies if evaluate(candidate.key, [], r, rules, now=now, X=0,
                                              policy=POLICY).status == 'INSUFFICIENT_SAMPLES']
        if valid:
            prices.append(max(valid, key=lambda r: (r.observed_at, r.expires)).buy_now_price)
    if not prices: return []
    center = median([Fraction(p) for p in prices])
    mad = median([abs(p-center) for p in prices])
    return sorted(p for p in prices if abs(p-center) <= max(3*mad, center/5))


def price_candidate(rows, candidate, rules, *, now, X, external=None):
    # The experiment distinguishes absent increment evidence without changing the
    # preserved calculator's invalid-rules exception contract.
    missing_increments = rules is not None and not rules.bands
    estimate = evaluate(candidate.key, rows, candidate, None if missing_increments else rules,
                        now=now, X=X, policy=POLICY)
    encoded = asdict(estimate)
    if missing_increments: encoded['status'] = 'MISSING_INCREMENTS'
    comparisons = {}
    if estimate.status == 'OK':
        prices = comparable_prices(rows, candidate, rules, now)
        if len(prices) != estimate.sample_count:
            raise ValueError('diagnostic_cohort_drift')
        mean = sum(prices, Fraction())/len(prices)
        references = {'lower_quartile': Fraction(prices[(len(prices)-1)//4]),
                      'robust_median': median([Fraction(p) for p in prices]), 'robust_mean': mean}
        for name, ref in references.items():
            target = floor_price(ref.numerator//ref.denominator, rules)
            comparisons[name] = {'reference': {'numerator': ref.numerator, 'denominator': ref.denominator},
                                 'target_sale_price': target, 'expected_profit': profit(target, candidate.buy_now_price)}
        comparisons['lower_quartile_undercut'] = {'target_sale_price': estimate.target_sale_price,
                                                 'expected_profit': estimate.expected_profit}
    return {'estimate': encoded, 'estimators': comparisons, 'selected_estimator': 'lower_quartile_undercut',
            'external': external_comparison(external or {}, candidate.key, now, estimate.target_sale_price),
            'uncertainty': UNCERTAINTY.copy(),
            'liquidity': {'completed_sales': None, 'sale_probability': None, 'time_to_sale_seconds': None},
            'scenarios': {str(x): estimate.status == 'OK' and estimate.expected_profit >= x for x in SCENARIOS}}


def rank_candidates(records, rules, *, now, X, external=None):
    rows = normalized(records)
    trades, items = defaultdict(list), defaultdict(set)
    for r in rows:
        trades[r.trade_id].append(r)
        items[r.item_id].add(r.trade_id)
    ranked = []
    for trade, copies in sorted(trades.items()):
        c = max(copies, key=lambda r: (r.observed_at, r.expires if type(r.expires) is int else -1))
        report = price_candidate(rows, c, rules.get(c.key), now=now, X=X, external=external)
        conflict = len({(r.key, r.item_id, r.buy_now_price) for r in copies}) != 1 or len(items[c.item_id]) > 1
        eligible = report['estimate']['meets_threshold'] and not conflict
        ranked.append({'candidate': {**asdict(c), 'observed_at': c.observed_at.isoformat()}, 'pricing': report,
                       'eligible': eligible, 'identity_conflict': conflict,
                       'freshness': {'age_upper_bound_seconds': (now-c.observed_at).total_seconds(),
                                     'remaining_expiry_lower_bound_seconds': c.expires-(now-c.observed_at).total_seconds()
                                         if type(c.expires) is int else None,
                                     'network_fresh': c.network_fresh}})
    ranked.sort(key=lambda r: (not r['eligible'], -(r['pricing']['estimate']['expected_profit']
                     if r['pricing']['estimate']['expected_profit'] is not None else -10**30),
                     r['freshness']['age_upper_bound_seconds'], r['candidate']['trade_id']))
    return ranked


def revalidate(candidate, record, *, now, scan_completed):
    try:
        rows = normalized([record])
    except (ValueError, TypeError, KeyError):
        return {'status': 'FAILED', 'reasons': ['MARKET_OR_SCHEMA_MISMATCH'], 'absence_means_sold': False}, None
    reasons = []
    if not record['result']['success']: reasons.append('READ_FAILED')
    if record['result']['status'] != 200 or any(n['status'] >= 400 for n in record['result']['network']):
        reasons.append('HTTP_ERROR')
    if not record['network_fresh']: reasons.append('NO_FRESH_NETWORK_GET')
    if record['criteria'].get('fresh') is not True: reasons.append('FRESH_RESET_NOT_REQUESTED')
    start = stamp(record['submitted_utc'])
    if start < scan_completed or start <= candidate.observed_at: reasons.append('READ_NOT_AFTER_SCAN')
    if not 0 <= (now-start).total_seconds() <= 30: reasons.append('STALE_OR_FUTURE_READ')
    if now < stamp(record['completed_utc']): reasons.append('FUTURE_COMPLETION')
    matches = [r for r in rows if r.trade_id == candidate.trade_id or r.item_id == candidate.item_id]
    if not matches: reasons.append('NOT_OBSERVED_IN_BOUNDED_PAGE')
    for r in matches:
        if (r.key, r.trade_id, r.item_id) != (candidate.key, candidate.trade_id, candidate.item_id):
            reasons.append('IDENTITY_CHANGED')
        if r.buy_now_price != candidate.buy_now_price: reasons.append('BIN_CHANGED')
        if not r.active or type(r.expires) is not int or r.expires-(now-r.observed_at).total_seconds() <= 60:
            reasons.append('INACTIVE_OR_EXPIRING')
    return {'status': 'PASSED' if not reasons else 'FAILED', 'reasons': sorted(set(reasons)),
            'identity_checked': ['game', 'platform', 'definition_id', 'trade_id', 'item_id'],
            'BIN_unchanged': bool(matches) and all(r.buy_now_price == candidate.buy_now_price for r in matches),
            'observed_utc': record['submitted_utc'], 'completed_utc': record['completed_utc'],
            'absence_means_sold': False}, matches[0] if matches and not reasons else None


def run_flow(read, *, mode, rules, clock, X=100, external=None):
    """Same finite state machine for a read-only live reader or fixture reader.

    `read(params)` returns the existing Runner record. It is invoked at most twice.
    No buy/list interface exists. A listing intent is conditional on a future
    independently confirmed purchase and physical-item inventory readback.
    """
    if mode not in ('SIMULATED', 'LIVE_READ_ONLY'): raise ValueError('invalid_mode')
    if type(X) is not int or X < 0: raise ValueError('invalid_X')
    events, records = [], []
    flow_begin = time.perf_counter()
    def stage(name, action):
        begin = time.perf_counter()
        value = action()
        end = time.perf_counter()
        events.append({'state': name, 'elapsed_ms': (end-begin)*1000,
                       'start_offset_ms': (begin-flow_begin)*1000, 'end_offset_ms': (end-flow_begin)*1000})
        return value

    scan = stage('SCAN', lambda: read({'league': 13, 'max_buy': 7000, 'page': 1, 'count': 21, 'fresh': True}))
    records.append(scan)
    if scan['mode'] != mode: raise ValueError('lineage_mismatch')
    now = stamp(clock.utc())
    ranked = stage('PRICE', lambda: rank_candidates([scan], rules, now=now, X=X, external=external))
    selected = stage('EVALUATE', lambda: next((r for r in ranked if r['eligible']), None))
    result = {'schema': 1, 'mode': mode, 'X': X, 'ranked_candidates': ranked, 'records': records,
              'revalidation': None, 'final_pricing': None, 'buy_intent': None, 'listing_intent': None,
              'account_mutations': 0, 'events': events}
    if selected:
        raw = selected['candidate']
        candidate = next(o for o in normalized([scan]) if o.trade_id == raw['trade_id'])
        def refresh():
            r = read({'definition_id': candidate.key.definition_id, 'page': 1, 'count': 21, 'fresh': True})
            if r['mode'] != mode: raise ValueError('lineage_mismatch')
            records.append(r)
            return revalidate(candidate, r, now=stamp(clock.utc()), scan_completed=stamp(scan['completed_utc']))
        validation, current = stage('REVALIDATE_READ_ONLY', refresh)
        result['revalidation'] = validation
        if current:
            final = stage('REPRICE_AND_EVALUATE', lambda: price_candidate(normalized([records[-1]]), current,
                            rules.get(current.key), now=stamp(clock.utc()), X=X, external=external))
            result['final_pricing'] = final
            if final['estimate']['meets_threshold']:
                estimate = final['estimate']
                result['buy_intent'] = stage('DRY_RUN_BUY_INTENT', lambda: {
                    'mode': 'DRY_RUN_ONLY', 'lineage': mode, 'operation': 'buy_now', 'key': asdict(current.key),
                    'trade_id': current.trade_id, 'item_id': current.item_id, 'buy_now_price': current.buy_now_price,
                    'target_sale_price': estimate['target_sale_price'], 'tax': estimate['tax'],
                    'expected_profit': estimate['expected_profit'], 'X': X,
                    'revalidated_utc': clock.utc(), 'assumptions': final['uncertainty']})
                result['listing_intent'] = stage('PROPOSED_LISTING_INTENT', lambda: {
                    'mode': 'PROPOSED_ONLY', 'lineage': mode, 'key': asdict(current.key), 'item_id': current.item_id,
                    'starting_bid': estimate['target_sale_price'], 'buy_now_price': estimate['target_sale_price'],
                    'duration_seconds': 3600,
                    'precondition': 'CONFIRMED_PURCHASE_AND_SAME_PHYSICAL_ITEM_INVENTORY_READBACK'})
    result['status'] = ('INTENTS_PREPARED' if result['buy_intent'] else 'NO_QUALIFYING_CANDIDATE' if not selected
                        else 'REVALIDATION_FAILED' if result['revalidation']['status'] == 'FAILED'
                        else 'REPRICE_REJECTED')
    buy_index = next((i for i, e in enumerate(events) if e['state'] == 'DRY_RUN_BUY_INTENT'), None)
    result['metrics'] = {
        'latency_clock': 'MEASURED_LOCAL_MONOTONIC_WALL_TIME_INCLUDING_PYTHON',
        'latency_scope': 'IN_PROCESS_FIXTURE_REPLAY_NOT_EA' if mode == 'SIMULATED' else 'READ_ONLY_TRANSPORT_AND_PYTHON',
        'latency': {e['state']: summary([e['elapsed_ms']]) for e in events},
        'search_to_prepared_intent_ms': events[buy_index]['end_offset_ms'] if buy_index is not None else None,
        'full_flow_ms': events[-1]['end_offset_ms'],
        'discovery': {'rows': len(normalized([scan])), 'unique_auctions': len(ranked),
                      'eligible_by_X': {str(x): sum(not r['identity_conflict'] and r['pricing']['scenarios'][str(x)]
                                                       for r in ranked) for x in SCENARIOS}},
        'pricing': {'evaluated': len(ranked), 'priced': sum(r['pricing']['estimate']['status'] == 'OK' for r in ranked)},
        'revalidation': {'attempts': int(selected is not None),
                         'passed': int(result['revalidation'] is not None and result['revalidation']['status'] == 'PASSED')},
    }
    return result
