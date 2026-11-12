"""Replay genuine retained records; no sockets, account operations or new reads."""
from collections import Counter
from dataclasses import asdict
from statistics import median

from fc_access.pricing import MarketKey, Rules
from experiments.market_discovery.discovery import observations, pagination
from experiments.market_discovery.model import stamp, summary
from experiments.market_discovery.opportunity import price_candidate

XS = (100, 250, 500, 1000)
LATENCIES = ('queue_delivery_ms', 'worker_poll_to_native_ms', 'native_service_ms',
             'page_total_ms', 'result_return_ms', 'result_post_round_trip_ms',
             'run_request_end_to_end_ms', 'time_to_first_result_ms')


def distribution(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'min': None, 'q25': None, 'median': None, 'q75': None, 'max': None}
    return {'n': len(values), 'min': values[0], 'q25': values[(len(values)-1)//4],
            'median': median(values), 'q75': values[3*(len(values)-1)//4], 'max': values[-1]}


def indicative(records):
    """Existing conservative calculator on LIVE asks with explicitly assumed rules.

    Hypothetical rule timestamps are evaluation times, never native observations.
    These diagnostics cannot become verified executable opportunities.
    """
    hits = {str(x): set() for x in XS}
    under_reference = set()
    priced, seen = set(), set()
    statuses = Counter()
    traces = []
    prefix = []
    for record in records:
        if record['slot'] >= 6:
            continue
        prefix.append(record)
        cohort = observations(prefix)
        now = stamp(record['completed_utc'])
        current = observations([record])
        for candidate in current:
            seen.add(candidate.trade_id)
            # This is the existing T5 sensitivity scenario, NOT discovered caps
            # or empirically verified ticks. Both lineage and limits stay explicit.
            hypothetical = Rules(candidate.key, 150, 15000000, now)
            priced_candidate = price_candidate(cohort, candidate, hypothetical, now=now, X=100)
            estimate = priced_candidate['estimate']
            statuses[estimate['status']] += 1
            if estimate['status'] != 'OK':
                continue
            priced.add(candidate.trade_id)
            for x in XS:
                if estimate['expected_profit'] >= x:
                    hits[str(x)].add(candidate.trade_id)
            reference = priced_candidate['estimators']['lower_quartile']['reference']
            if candidate.buy_now_price * reference['denominator'] < reference['numerator']:
                under_reference.add(candidate.trade_id)
            traces.append({'observed_utc': record['submitted_utc'], 'window': record['window'],
                'slot': record['slot'], 'definition_id': candidate.key.definition_id,
                'trade_id': candidate.trade_id, 'item_id': candidate.item_id,
                'acquisition_price': candidate.buy_now_price,
                'target_sale_price': estimate['target_sale_price'], 'expected_profit': estimate['expected_profit'],
                'comparables_excluding_candidate': estimate['sample_count'],
                'scenario_hits': [x for x in XS if estimate['expected_profit'] >= x],
                'rule_lineage': 'HYPOTHETICAL_CAPS_AND_INCREMENT_SCHEDULE_NOT_EXECUTABLE'})
    return {'data_lineage': records[0]['mode'] if records else None,
            'rule_lineage': 'HYPOTHETICAL_NOT_EXECUTABLE',
            'rule_timestamp_lineage': 'MODEL_EVALUATION_TIME_NOT_NATIVE_RULE_OBSERVATION',
            'candidate_excluded_from_own_comparables': True,
            'cohort_scope': 'same strategy window, observed prefix only; exact PC version; age <=120s; >=5 comparables',
            'minimum_remaining_seconds': 60, 'candidate_age_upper_bound_seconds': 30,
            'unique_discovery_auctions': len(seen), 'unique_priceable_auctions': len(priced),
            'observed_BIN_below_sample_quartile_after_hypothetical_rule_filter': len(under_reference),
            'indicative_modeled_candidates_by_X': {x: len(v) for x, v in hits.items()},
            'evaluation_status_counts': dict(statuses), 'successful_evaluation_traces': traces,
            'fully_validated_executable_opportunities_by_X': {str(x): None for x in XS},
            'verified_executable_opportunities_observed': 0,
            'verified_native_caps': False, 'verified_legal_increments': False,
            'our_completed_sales': 0, 'realized_profit': None}


def diagnostic_revalidation(records):
    discovery = [r for r in records if r['slot'] < 6]
    reads = [r for r in records if r['slot'] >= 6]
    eligible = [o for o in observations(discovery) if o.active and o.buy_now_price and o.network_fresh
                and o.expires is not None and o.expires > 60]
    if not eligible:
        return {'status': 'UNUSED_NO_VALID_ROWS', 'reason': 'No diagnostic candidate', 'requests': len(reads),
                'counts_as_profitable_opportunity': False, 'absence_means_sold': False}
    candidate = min(eligible, key=lambda o: (o.buy_now_price, o.trade_id))
    matches, reasons = [], []
    for record in reads:
        for row in observations([record]):
            if row.trade_id == candidate.trade_id or row.item_id == candidate.item_id:
                age = (stamp(record['completed_utc'])-row.observed_at).total_seconds()
                row_reasons = []
                if (row.key, row.trade_id, row.item_id) != (candidate.key, candidate.trade_id, candidate.item_id):
                    row_reasons.append('IDENTITY_CHANGED')
                if row.buy_now_price != candidate.buy_now_price:
                    row_reasons.append('BIN_CHANGED')
                if not row.network_fresh or not 0 <= age <= 30:
                    row_reasons.append('STALE_OR_CACHED')
                if not row.active or row.expires is None or row.expires-age <= 60:
                    row_reasons.append('INACTIVE_OR_EXPIRING')
                matches.append({'slot': record['slot'], 'observed_utc': record['submitted_utc'],
                                'reasons': row_reasons, 'age_at_response_seconds': age})
                reasons.extend(row_reasons)
    if not matches:
        reasons.append('NOT_OBSERVED_IN_BOUNDED_PAGES')
    passed = bool(matches) and any(not row['reasons'] for row in matches) and not any(
        reason in ('IDENTITY_CHANGED', 'BIN_CHANGED') for reason in reasons)
    return {'status': 'MATCH_ON_FRESH_PAGE' if passed else 'NOT_REVALIDATED',
            'selection': 'LOWEST_POSITIVE_BIN_DIAGNOSTIC_ONLY_RULES_UNAVAILABLE',
            'candidate': {'definition_id': candidate.key.definition_id, 'trade_id': candidate.trade_id,
                          'item_id': candidate.item_id, 'BIN': candidate.buy_now_price,
                          'original_observed_utc': candidate.observed_at.isoformat()},
            'requests': len(reads), 'matches': matches, 'reasons': sorted(set(reasons)),
            'counts_as_profitable_opportunity': False, 'absence_means_sold': False,
            'executable_revalidation_rate': None}


def arm(records, intervals):
    rows = [row for r in records for row in r['result']['auctions'] or []]
    discovery = [r for r in records if r['slot'] < 6]
    discovery_rows = [row for r in discovery for row in r['result']['auctions'] or []]
    auctions = {r['trade_id'] for r in rows}
    versions = {r['item']['definition_id'] for r in rows}
    requests = sum(len(r['result']['network']) for r in records)
    seconds = sum(w['observed_seconds'] for w in intervals)
    scenario_hits = {str(x): set() for x in XS}
    priced, status_counts, traces, revalidations = set(), Counter(), [], []
    for interval in intervals:
        window_records = [r for r in records if r['window'] == interval['window']]
        scenario = indicative(window_records)
        for trace in scenario['successful_evaluation_traces']:
            priced.add(trace['trade_id'])
            for x in trace['scenario_hits']:
                scenario_hits[str(x)].add(trace['trade_id'])
        traces.extend(scenario['successful_evaluation_traces'])
        status_counts.update(scenario['evaluation_status_counts'])
        revalidations.append(diagnostic_revalidation(window_records) | {'window': interval['window']})
    used = [r for r in revalidations if r['status'] != 'UNUSED_NO_VALID_ROWS']
    matched = sum(r['status'] == 'MATCH_ON_FRESH_PAGE' for r in used)
    observed = any(r['network_fresh'] for r in discovery)
    return {'commands': len(records), 'EA_requests': requests,
        'completed_windows': sum(w['completed'] for w in intervals), 'allocated_observation_seconds': seconds,
        'unique_auctions': len(auctions), 'unique_exact_versions': len(versions), 'response_rows': len(rows),
        'discovery_only_unique_auctions': len({r['trade_id'] for r in discovery_rows}),
        'discovery_only_unique_versions': len({r['item']['definition_id'] for r in discovery_rows}),
        'auctions_per_EA_request': len(auctions)/requests if requests else None,
        'versions_per_EA_request': len(versions)/requests if requests else None,
        'auctions_per_observation_minute': len(auctions)*60/seconds if seconds else None,
        'versions_per_observation_minute': len(versions)*60/seconds if seconds else None,
        'duplicate_fraction': 1-len(auctions)/len(rows) if rows else None,
        'BIN_distribution_all_response_rows': distribution([r['buy_now_price'] for r in rows if r['buy_now_price']]),
        'BIN_distribution_distinct_auctions_latest': distribution(list({r['trade_id']:r['buy_now_price'] for r in rows if r['buy_now_price']}.values())),
        'HTTP_status_counts': dict(Counter(str(n['status']) for r in records for n in r['result']['network'])),
        'native_error_counts': dict(Counter(r['result']['error'] for r in records if r['result']['error'])),
        'fresh_network_responses': sum(r['network_fresh'] for r in records),
        'cache_only_responses': sum(r['result']['success'] and not r['network_fresh'] for r in records),
        'empty_responses': sum(r['result']['success'] and not r['result']['auctions'] for r in records),
        'latency': {key: summary([r['timing'].get(key) for r in records]) for key in LATENCIES},
        'pagination': pagination(records), 'unique_priceable_discovery_auctions_with_assumed_rules': len(priced),
        'indicative_modeled_candidates_by_X': {x:len(v) if observed else None for x,v in scenario_hits.items()},
        'indicative_candidates_per_EA_request_by_X': {x:len(v)/requests if requests else None for x,v in scenario_hits.items()},
        'indicative_candidates_per_observation_minute_by_X': {x:len(v)*60/seconds if seconds else None for x,v in scenario_hits.items()},
        'fully_validated_executable_opportunities_by_X': {str(x):None for x in XS},
        'verified_executable_opportunities_observed': 0, 'native_caps_and_ticks': 'UNVERIFIED',
        'model_evaluation_status_counts': dict(status_counts), 'modeled_candidate_trace': traces,
        'revalidations': revalidations, 'diagnostic_revalidation_attempts': len(used),
        'diagnostic_revalidation_matches': matched,
        'diagnostic_revalidation_match_fraction': matched/len(used) if used else None,
        'profitable_executable_revalidation_rate': None, 'realized_profit': None}


def passive_summary(directory, run):
    path = directory/'passive-observations.jsonl'
    heartbeats = directory/'passive-heartbeats.jsonl'
    rows = [__import__('json').loads(line)['observation'] for line in path.read_text().splitlines()] if path.exists() else []
    beats = [__import__('json').loads(line) for line in heartbeats.read_text().splitlines()] if heartbeats.exists() else []
    start = stamp(run['observation_interval']['start_utc'])
    end = stamp(run['observation_interval']['end_utc'])
    scoped = [r for r in rows if start <= stamp(r['observed_at'].replace('Z','+00:00')) <= end]
    active = [b for b in beats if b['attached']]
    return {'status': 'PARTIAL_PASSIVE_METADATA_AVAILABLE' if active else 'UNAVAILABLE_OBSERVER_NOT_ATTACHED',
            'events_in_observation_interval': len(scoped) if active else None,
            'connected_heartbeat_samples': len(active), 'total_heartbeat_samples': len(beats),
            'earliest_buffered_event': min((r['observed_at'] for r in rows), default=None),
            'latest_buffered_event': max((r['observed_at'] for r in rows), default=None),
            'HTTP_status_counts': dict(Counter(str(r['status']) for r in scoped)) if active else None,
            'coverage': 'Allowlisted game-request metadata only; no sequence numbers; identical metadata deduplicated; gaps and other EA traffic remain unknown',
            'zero_background_assumed': False,
            'comparison': 'CONFOUNDED_BACKGROUND_UNMEASURED' if not active else 'DESCRIPTIVE_PASSIVE_COVERAGE_LIMITED'}


def analyze(run, directory=None):
    arms = {s:arm([r for r in run['records'] if r['strategy']==s],
                  [w for w in run['window_intervals'] if w['strategy']==s]) for s in 'ABC'}
    auction_sets = {s:{a['trade_id'] for r in run['records'] if r['strategy']==s for a in r['result']['auctions'] or []} for s in 'ABC'}
    overlaps = {}
    for a,b in [('A','B'),('A','C'),('B','C')]:
        union = auction_sets[a] | auction_sets[b]
        overlaps[a+b] = {'shared_auctions':len(auction_sets[a]&auction_sets[b]),
                        'jaccard':len(auction_sets[a]&auction_sets[b])/len(union) if union else None}
    return {'schema':1, 'data_lineage':run['mode'], 'protocol_completion':run['protocol_completion'],
            'protocol_sha256':run['protocol_sha256'], 'observation_interval':run['observation_interval'],
            'window_intervals':run['window_intervals'], 'arms':arms, 'cross_strategy_overlap':overlaps,
            'ranking_by_window':[{'window':w['window'],'strategy':w['strategy'],'ranking':w['ranking']} for w in run['windows']],
            'background':passive_summary(directory,run) if directory else {'status':'UNAVAILABLE','zero_background_assumed':False},
            'pricing_lineage':{'observations':run['mode'],'rules':'HYPOTHETICAL_NOT_EXECUTABLE',
                'verified_native_caps':False,'verified_legal_increments':False,
                'formula':'target_sale_price - target_sale_price // 20 - acquisition_price',
                'candidate_self_excluded':True,'no_future_observations':True,'minimum_comparables':5,
                'sample_max_age_seconds':120,'minimum_remaining_seconds':60},
            'hourly_yield_extrapolation':None,'completed_sales_or_realized_profits_claimed':False,
            'third_party_production_feed':'UNAVAILABLE_NOT_RETESTED_NO_PAID_ACCESS',
            'account_mutations':run['account_mutations']}
