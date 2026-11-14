"""Single consumed read-only 002-03 window. Never repair, retry, or dispatch bids.

Run explicitly with ``python -m fc_access.production_v1.gate_00203``. Unit tests
use temporary checkpoints; acceptance validators never invoke this entry point.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from .contracts import Search, parse_response, stamp
from .executor import EdgeExecutor
from .foundation import Foundation
from .prices import CardKey

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'docs/research/002/002-03'
CHECKPOINT = OUT/'gate.json'
AUTHORIZED_ATTEMPT = '20261114-preflight-remediation-01'
REMEDIATION_CHECKPOINT = OUT/'attempts'/AUTHORIZED_ATTEMPT/'gate.json'
AUTHORITY = 'explicit_user_one_additional_read_only_encoding_remediation_attempt'
THIRD_ATTEMPT = '20261114-bounded-discovery-03'
THIRD_CHECKPOINT = OUT/'attempts'/THIRD_ATTEMPT/'gate.json'
FOURTH_ATTEMPT = '20261114-authenticated-retry-04'
FOURTH_CHECKPOINT = OUT/'attempts'/FOURTH_ATTEMPT/'gate.json'
JOURNAL = ROOT/'private-captures/final-remediation/foundation.sqlite3'
CACHE = JOURNAL.with_name('completed-quotes.sqlite3')
LIMIT_NS = 30_000_000_000
DEFINITION_ID = 261855


def utc():
    return datetime.now(timezone.utc).isoformat()


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(value):
    # Captured responses and experiment evidence only; never implementation bytes.
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class Window:
    def __init__(self, path=None, *, clock=time.monotonic_ns, authorization=None, attempt_id=AUTHORIZED_ATTEMPT):
        self.path, self.clock = Path(path if path is not None else CHECKPOINT), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = dict(schema=1, task='002-03', mode='LIVE_READ_ONLY', status='RUNNING',
            attempt=1, started_at=utc(), operations=[], cache_reads=[],
            hard_stop=True, dependent_tasks_allowed=False, automatic_repairs=False,
            automatic_reruns=False, account_mutations=0, stage='PREPARATION')
        if authorization is not None:
            broad=attempt_id in {THIRD_ATTEMPT,FOURTH_ATTEMPT}
            fourth=attempt_id==FOURTH_ATTEMPT
            self.state.update(attempt=4 if fourth else 3 if broad else 2, attempt_id=attempt_id, authorization=authorization,
                              execution_budget=dict(attempts=1,ea_GETs=10 if fourth else 9 if broad else 7,pricing_GETs=2,local_helper_batches=64))
            if broad:self.state['execution_budget'].update(discovery_GETs=3,discovery_seconds=180)
            if fourth:self.state['execution_budget']['authentication_GETs']=1
            validate_attempt(self.state)
        # Exclusive creation consumes the attempt even if the process crashes.
        with self.path.open('x', encoding='utf-8') as f:
            json.dump(self.state, f); f.flush(); os.fsync(f.fileno())
        self.save()

    def save(self):
        temp = self.path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, allow_nan=False)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        temp.replace(self.path)

    def check(self):
        need(self.state['status'] == 'RUNNING', 'gate_stopped_no_more_work')
        start = self.state.get('valuation_start_ns')
        if start is None and self.state.get('discovery_deadline_ns') is not None:
            need(self.clock()<self.state['discovery_deadline_ns'], 'bounded_discovery_deadline')
        if start is not None and self.clock()-start >= LIMIT_NS:
            raise TimeoutError('hard_30_second_deadline')

    def stop(self, reason):
        self.state.update(status='FAILURE/BLOCKED', reason=reason, hard_stop=True,
                          dependent_tasks_allowed=False, stopped_ns=self.clock(), finished_at=utc())
        if 'valuation_start_ns' in self.state:
            self.state['elapsed_ns'] = self.state['stopped_ns']-self.state['valuation_start_ns']
        self.state['evidence_sha256'] = digest({k:v for k,v in self.state.items() if k != 'evidence_sha256'})
        self.save()


class ReadOnlyGateExecutor(EdgeExecutor):
    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.window = window

    def execute(self, c):
        w, s = self.window, self.window.state
        w.check()
        op = c['operation']
        need(op in {'search', 'balance', 'caps', 'price_helpers'}, 'gate_read_only_allowlist')
        local = op == 'price_helpers'
        previous = s['operations']
        need(sum(e['command']['operation'] == 'price_helpers' for e in previous) < 64 if local else
             sum(e['command']['operation'] != 'price_helpers' for e in previous) < s.get('execution_budget',{}).get('ea_GETs',7), 'finite_budget_exhausted')
        if s.get('attempt') in {3,4} and 'valuation_start_ns' not in s:
            if s['attempt']==4 and s['stage']=='AUTHENTICATION':
                need(op=='balance' and c['params']=={} and not previous,'one_authentication_read_required')
            else:
                need(s['stage']=='BOUNDED_DISCOVERY' and op=='search' and c['params']==Search.discovery().params(),
                     'no_valuation_warmup_during_discovery')
                need(sum(e['stage']=='BOUNDED_DISCOVERY' for e in previous)<3,'bounded_discovery_request_budget')
        if op == 'search' and c['params']['purpose'] == 'pricing':
            need(s['stage'] == 'UNCACHED_VALUATION', 'pricing_outside_single_valuation')
            need(sum(e['command']['operation'] == 'search' and
                     e['command']['params']['purpose'] == 'pricing' for e in previous) < 2,
                 'two_pricing_search_budget')
        entry = dict(command=deepcopy(c), stage=s['stage'], state='RESERVED_BEFORE_DELIVERY',
                     start_ns=w.clock())
        previous.append(entry); w.save(); w.check()
        raw = super().execute(c)
        # Persist sanitized protocol evidence, including unsuccessful EA responses.
        r = parse_response(raw, c, pricing_rows=op == 'search' and c['params']['purpose'] == 'pricing')
        entry.update(response=r, finish_ns=w.clock(), state='RESPONSE_RECORDED',
                     evidence_sha256=digest(dict(command=c, response=r)))
        w.save(); w.check()
        need(r['result']['success'], 'native_operation_failed')
        need(set(r['timing']) == {'native_service_ms', 'ea_rtt_ms', 'native_helper_ms'},
             'current_instrumented_page_required')
        return r


def cache_snapshot(root, context, definition_id):
    """Capture actual durable cache rows without deleting/expiring/rekeying any."""
    result = []
    for path in sorted(Path(root).rglob('completed-quotes.sqlite3')):
        db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
        try:
            rows = db.execute('SELECT account,game,platform,definition_id,observed_at FROM completed_quotes_v1').fetchall()
            matches = [r for r in rows if tuple(r[:4]) ==
                       (context['account'], context['game'], context['platform'], definition_id)]
            result.append(dict(path=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                               rows=[list(r) for r in rows], exact_key_rows=[list(r) for r in matches]))
        finally:
            db.close()
    return result


def evaluate_window(f, w, discovery, candidate):
    """One uncached quote followed by fresh real reads and Foundation.admit.

    The final admission's cache reuse is INSIDE the same measured window; the
    independently retained first quote must be a real miss with two actual GETs.
    No preliminary price/cap/helper warmup occurs before this timer.
    """
    s = w.state
    s.update(stage='UNCACHED_VALUATION', valuation_start_ns=w.clock(), valuation_start_at=f.now().isoformat(),
             candidate=deepcopy(candidate), discovery_read_id=discovery['command_id'])
    original_get = f.cache.get
    def observed_get(context, definition_id, **kwargs):
        w.check()
        value = original_get(context, definition_id, **kwargs)
        s['cache_reads'].append(dict(definition_id=definition_id, miss=value is None,
                                    at=f.now().isoformat(), monotonic_ns=w.clock(), stage=s['stage']))
        w.save(); w.check()
        return value
    f.cache.get = observed_get
    before = f.timing_summary()
    native_before, local_before = len(f.executor.metrics), len(f.executor.local_metrics)
    w.save(); w.check()
    try:
        prices = f.prices.load(key=CardKey(candidate['item']['definition_id']))
        quote = f.pricing.quote(candidate, prices)
        s['uncached_quote'] = asdict(quote); w.save(); w.check()
        need(quote.completed and quote.status == 'COMPLETE' and
             quote.evidence['cache_hit'] is False and quote.evidence['price_searches'] == 2,
             'real_uncached_eligible_quote_required')
        s['stage'] = 'FRESH_FINAL_ADMISSION'
        fresh = f.read('search', Search.discovery(candidate['item']['definition_id']).params())
        rows = [r for r in fresh['result']['auctions'] if r['trade_id'] == candidate['trade_id'] and
                r['item'] == candidate['item']]
        need(len(rows) == 1, 'real_candidate_missing_on_fresh_recheck')
        funds = f.read('balance')
        s.update(final_status_read_id=fresh['command_id'], final_balance_read_id=funds['command_id'])
        decision = f.admit(fresh, candidate['trade_id'], funds)
        # admit returns only AFTER its normal durable DECISION write.
        s.update(decision=decision, final_decision_at=f.now().isoformat())
        w.save()  # Include the ordinary final-decision checkpoint write too.
        w.check()
        s['final_decision_ns'] = w.clock()
        s['elapsed_ns'] = s['final_decision_ns']-s['valuation_start_ns']
        need(s['elapsed_ns'] < LIMIT_NS, 'hard_30_second_deadline')
        need((decision['action'], decision['reason']) == ('BID', 'ELIGIBLE'), 'fresh_BID_ELIGIBLE_required')
    finally:
        f.cache.get = original_get
        after = f.timing_summary()
        s['timing_breakdown'] = {k: after[k]-before[k] if after[k] is not None and before[k] is not None else None
                                 for k in after}
        s['executor_metrics'] = deepcopy(f.executor.metrics[native_before:]+f.executor.local_metrics[local_before:])
        s['registry_events'] = f.registry.events()
        s['journal_bid_commands'] = f.journal.db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]
        w.save()


def admission_proof(s, *, source='native'):
    """Independent recorded-response assessor. No browser/network/file mutation."""
    need(s['task'] == '002-03' and s['mode'] == 'LIVE_READ_ONLY', 'wrong_gate')
    validate_attempt(s)
    need(s['health_before']['service'] == 'fc-production-v1' and s['health_before']['attached'] and
         s['health_before']['mutations_enabled'] is False, 'read_only_attachment_required')
    need(s['context']['game'] == 'fc27' and s['context']['platform'] == 'pc', 'official_FC27_PC_required')
    need(s['desktop']['official_tab'] and s['desktop']['foreground_verified'] and
         s['desktop']['edge_control_verified'], 'official_Edge_tab_required')
    need(s['elapsed_ns'] == s['final_decision_ns']-s['valuation_start_ns'] and
         0 <= s['elapsed_ns'] < LIMIT_NS, 'hard_30_second_deadline')
    need(s['account_mutations'] == s['journal_bid_commands'] == 0, 'bid_dispatched')
    candidate = s['candidate']; definition = candidate['item']['definition_id']
    need(s['cache_inventory'] and any(c['path'] == str(CACHE.relative_to(ROOT)) for c in s['cache_inventory']) and
         all(not c['exact_key_rows'] for c in s['cache_inventory']), 'previously_cached_version')
    for c in s['cache_inventory']:
        matches = [r for r in c['rows'] if tuple(r[:4]) ==
                   (s['context']['account'], 'fc27', 'pc', definition)]
        need(matches == c['exact_key_rows'] == [], 'cache_inventory_contradiction')
    need(len(s['cache_reads']) == 2 and s['cache_reads'][0]['miss'] is True and
         s['cache_reads'][0]['stage'] == 'UNCACHED_VALUATION' and
         s['cache_reads'][1]['miss'] is False and
         s['cache_reads'][1]['stage'] == 'FRESH_FINAL_ADMISSION' and
         all(c['definition_id'] == definition and s['valuation_start_ns'] <= c['monotonic_ns'] <= s['final_decision_ns']
             for c in s['cache_reads']), 'independent_cache_miss_required')
    operations, helpers, queries = {}, {}, []
    last_end = 0
    for e in s['operations']:
        c, r = e['command'], e['response']
        need(e['state'] == 'RESPONSE_RECORDED' and c['id'] not in operations, 'ambiguous_duplicate_operation')
        need(e['evidence_sha256'] == digest(dict(command=c, response=r)), 'captured_response_integrity')
        need(c['operation'] in {'search', 'caps', 'balance', 'price_helpers'}, 'mutation_or_unbounded_operation')
        need(c['context'] == s['context'] and c['fences'] == s['fences'], 'context_fence_changed')
        need(last_end <= e['start_ns'] <= e['finish_ns'], 'transport_not_serialized')
        last_end = e['finish_ns']
        parse_response(r, c, now=stamp(r['freshness']['observed_at']), source=source,
                       pricing_rows=c['operation'] == 'search' and c['params']['purpose'] == 'pricing')
        need(r['result']['success'], 'failed_native_operation')
        need(set(r['timing']) == {'native_service_ms', 'ea_rtt_ms', 'native_helper_ms'}, 'timing_split_missing')
        for n in r['result']['network']:
            need(n['method'] == 'GET' and n['status'] == 200 and n['session_header_present'], 'actual_authenticated_GET_required')
        if c['operation'] == 'price_helpers':
            for p in r['result']['probes']:
                key = (p['direction'], p['value'])
                need(key not in helpers or helpers[key] == p['price'], 'conflicting_native_ticks')
                helpers[key] = p['price']
        if c['operation'] == 'search' and c['params']['purpose'] == 'pricing':
            queries.append(e)
        operations[c['id']] = e
    need(len(queries) == 2, 'two_real_pricing_GETs_required')
    if s['attempt'] in {3,4}:
        from .gate_00203_discovery import discovery_candidates
        initial=[e for e in s['operations'] if e['start_ns']<s['valuation_start_ns']]
        if s['attempt']==4:
            auth=[e for e in initial if e['stage']=='AUTHENTICATION']
            need(len(auth)==1 and auth[0]['command']['operation']=='balance' and
                 auth[0]['command']['id']==s['authenticated_read_id'] and
                 auth[0]['response']['result']['success'] is True and
                 auth[0]['response']['freshness']['source']=='native' and
                 auth[0]['response']['result']['network'][0]['path']=='/ut/game/fc27/user/credits',
                 'fresh_authenticated_EA_read_required')
            initial=[e for e in initial if e['stage']!='AUTHENTICATION']
            need(all(auth[0]['finish_ns']<=e['start_ns'] for e in initial),'authentication_must_precede_discovery')
        need(1<=len(initial)<=3 and all(e['stage']=='BOUNDED_DISCOVERY' and
             e['command']['operation']=='search' and e['command']['params']==Search.discovery().params() and
             e['finish_ns']<=s['valuation_start_ns'] for e in initial),'unbounded_discovery_or_valuation_warmup')
        selected=operations[s['discovery_read_id']]
        need(s['selection']['read_id']==s['discovery_read_id'] and
             any(r==candidate for r in discovery_candidates(selected['response'],now=stamp(s['valuation_start_at']))),
             'selected_auction_not_fresh_native_discovery')
        need(s['selection']['definition_id']==definition and s['selection']['trade_id']==candidate['trade_id'] and
             s['selection']['item_id']==candidate['item']['item_id'] and
             selected['finish_ns']<=s['selection']['selected_ns']<=s['valuation_start_ns']<s['discovery_deadline_ns'],
             'selected_identity_or_discovery_deadline')
        need(any(c['definition_id']==definition and c['read_id']==s['discovery_read_id'] and
             c['inventory']==s['cache_inventory'] for c in s['discovery_cache_checks']), 'selection_cache_evidence_missing')
        need(sum(e['command']['operation']!='price_helpers' for e in s['operations'])<=(10 if s['attempt']==4 else 9) and
             sum(e['command']['operation']=='price_helpers' for e in s['operations'])<=64,'finite_budget_exhausted')
    quote = s['uncached_quote']; qe = quote['evidence']
    need(quote['completed'] and quote['status'] == 'COMPLETE' and qe['cache_hit'] is False and
         qe['price_searches'] == 2 and qe['source'] == source, 'uncached_quote_required')
    need(quote['X'] == 500 and qe['definition_id'] == definition, 'policy_changed')
    caps_entries = [e for e in operations.values() if e['command']['operation'] == 'caps']
    need(len(caps_entries) == 2, 'fresh_native_caps_required')
    caps = caps_entries[0]['response']['result']['caps']
    need(caps['definition_id'] == definition and caps_entries[1]['response']['result']['caps'] == caps, 'caps_identity_or_range_changed')
    def legal(value):
        lower = helpers[('below', value)]
        return lower < value and helpers[('above', lower)] == value
    # Reconstruct both observed minima from recorded EA rows and native outputs.
    from .pricing import select_comparables
    class RecordedPrices:
        key = CardKey(definition)
        minimum, maximum = caps['minimum'], caps['maximum']
        def legal_many(self, values):
            return {v: legal(v) for v in values}
    wrapped = []
    for i, e in enumerate(queries):
        c, r = e['command'], e['response']
        need(c['params'] == Search.pricing(definition, qe['first_min'] if i else None).params(), 'wrong_pricing_parameters')
        need(e['stage'] == 'UNCACHED_VALUATION' and
             s['valuation_start_ns'] <= e['start_ns'] <= e['finish_ns'] <= s['final_decision_ns'], 'pricing_outside_timer')
        validated = stamp(qe['samples'][i]['network_at'])
        need(r['freshness']['network_at'] == qe['samples'][i]['network_at'], 'sample_not_actual_response')
        rows = [dict(row=row, network_at=r['freshness']['network_at'], validated_at=validated.isoformat(),
                     max_buy=c['params'].get('max_buy')) for row in r['result']['auctions']]
        own, _ = select_comparables(rows, candidate, RecordedPrices(), now=validated)
        if i == 0:
            need(own and min(x['row']['buy_now_price'] for x in own) == qe['first_min'], 'first_min_not_observed')
        wrapped.extend(rows)
    comparable, _ = select_comparables(wrapped, candidate, RecordedPrices(), now=stamp(s['final_decision_at']))
    resale = min(x['row']['buy_now_price'] for x in comparable)
    need(resale == quote['resale_price'] and len(comparable) == qe['sample_count'], 'wrong_observed_resale')
    need(quote['tax'] == resale//20 and legal(resale), 'invalid_native_resale_or_tax')
    raw_cap = resale-resale//20-500
    cap = quote['max_affordable_bid']
    need(legal(cap) and cap <= raw_cap < helpers[('above', cap)], 'cap_not_native_floor')
    decision = s['decision']
    need((decision['action'], decision['reason']) == ('BID', 'ELIGIBLE') and decision['cap'] == cap,
         'fresh_BID_ELIGIBLE_required')
    need(decision['quote']['completed'] and decision['quote']['evidence']['cache_hit'] is True and
         decision['quote']['evidence']['price_searches'] == 0 and
         decision['quote']['resale_price'] == resale, 'fresh_decision_detached_from_uncached_quote')
    status = operations[s['final_status_read_id']]; funds = operations[s['final_balance_read_id']]
    need(status['stage'] == funds['stage'] == 'FRESH_FINAL_ADMISSION' and
         status['command']['params'] == Search.discovery(definition).params() and
         funds['command']['operation'] == 'balance' and
         queries[-1]['finish_ns'] <= status['start_ns'] < funds['start_ns'] <= s['final_decision_ns'], 'fresh_rechecks_missing')
    for e in (status, funds, caps_entries[-1]):
        parse_response(e['response'], e['command'], now=stamp(s['final_decision_at']), source=source)
    matches = [r for r in status['response']['result']['auctions'] if r['trade_id'] == candidate['trade_id'] and r['item'] == candidate['item']]
    need(len(matches) == 1, 'fresh_exact_candidate_missing')
    row = matches[0]
    age = (stamp(s['final_decision_at'])-stamp(status['response']['freshness']['network_at'])).total_seconds()
    need(row['trade_state'] == 'active' and row['bid_state'] in {'none', 'outbid'} and row['expires'] > age and
         row['item']['untradeable'] is False and row['native_is_won'] is not True, 'candidate_not_eligible')
    amount = helpers[('above', row['current_bid'])] if row['current_bid'] else row['starting_bid']
    need(legal(amount) and amount == decision['amount'] <= cap and
         (not row['buy_now_price'] or amount < row['buy_now_price']), 'bid_not_minimum_legal_or_over_cap')
    need(funds['response']['result']['credits']-amount >= 5000, 'insufficient_actual_funds')
    from .foundation import status_from
    need(decision['identity'] == asdict(status_from(row, status['response']).identity), 'decision_identity_changed')
    need(any(e['kind'] == 'DECISION' and all(e.get(k) == decision[k] for k in decision)
             for e in s['registry_events']), 'ordinary_decision_write_missing')
    need(all(e['finish_ns'] <= s['final_decision_ns'] for e in s['operations']), 'work_after_final_decision')
    metrics = s['executor_metrics']; breakdown = s['timing_breakdown']
    measured = [e for e in s['operations'] if e['start_ns'] >= s['valuation_start_ns']]
    need(len(metrics) == len(measured) == breakdown['commands'], 'timing_commands_missing')
    need({m['command_id'] for m in metrics} == {e['command']['id'] for e in measured}, 'metrics_not_actual_commands')
    for k in ('ea_rtt_ms', 'executor_queue_ms', 'browser_bridge_ms', 'native_helper_ms', 'browser_other_ms',
              'transport_sqlite_ms', 'sqlite_ms', 'diagnostic_logging_ms', 'diagnostic_sqlite_ms', 'diagnostic_non_sqlite_ms'):
        need(type(breakdown[k]) in {int, float} and breakdown[k] >= 0, 'missing_timing_'+k)
    for out, key in [('ea_rtt_ms','ea_rtt_ms'),('executor_queue_ms','queue_ms'),('browser_bridge_ms','browser_bridge_ms'),
                     ('native_helper_ms','native_helper_ms'),('browser_other_ms','browser_other_ms'),('transport_sqlite_ms','transport_sqlite_ms')]:
        need(abs(breakdown[out]-sum(m[key] for m in metrics)) < .01, 'timing_breakdown_mismatch')
    need(breakdown['diagnostic_logging_ms'] > 0 and breakdown['sqlite_ms'] > 0, 'diagnostics_or_sqlite_skipped')
    return dict(status='PASS', elapsed_seconds=s['elapsed_ns']/1e9, pricing_GETs=2,
                definition_id=definition, decision='BID/ELIGIBLE', bid_dispatches=0)


def selected_checkpoint(attempt=None):
    if attempt is not None:
        if attempt==FOURTH_ATTEMPT:return FOURTH_CHECKPOINT
        if attempt==THIRD_ATTEMPT:return THIRD_CHECKPOINT
        need(attempt == AUTHORIZED_ATTEMPT, 'unknown_authorized_attempt')
        return REMEDIATION_CHECKPOINT
    # A new RUNNING/failed checkpoint blocks dependencies; never fall back.
    return FOURTH_CHECKPOINT if FOURTH_CHECKPOINT.exists() else THIRD_CHECKPOINT if THIRD_CHECKPOINT.exists() else REMEDIATION_CHECKPOINT if REMEDIATION_CHECKPOINT.exists() else CHECKPOINT


def original_failure():
    raw = CHECKPOINT.read_bytes()
    old = json.loads(raw.decode('utf-8'))
    need(old['attempt'] == 1 and old['status'] == 'FAILURE/BLOCKED' and
         old['stage'] == 'DESKTOP_PREFLIGHT' and old['operations'] == [] and
         old['cache_reads'] == [] and old['actual_pricing_GETs'] == 0 and
         old['preflight_failure']['encoding'] == 'cp1252' and
         old['preflight_failure']['byte'] == '0x81' and
         old['hard_stop'] is True and old['dependent_tasks_allowed'] is False,
         'original_encoding_failure_required')
    need(old['evidence_sha256'] == digest({k:v for k,v in old.items() if k != 'evidence_sha256'}),
         'original_failed_evidence_changed')
    return dict(authority=AUTHORITY, previous_checkpoint='docs/research/002/002-03/gate.json',
                previous_status='FAILURE/BLOCKED', previous_capture_sha256=hashlib.sha256(raw).hexdigest(),
                additional_attempts=1)


def validate_attempt(s):
    if type(s.get('attempt')) is int and s['attempt'] == 1:
        need('attempt_id' not in s and 'authorization' not in s, 'wrong_gate_attempt_identity')
        return
    if type(s.get('attempt')) is int and s['attempt']==3:
        need(s.get('attempt_id')==THIRD_ATTEMPT and s.get('authorization')==third_authorization(),
             'wrong_gate_attempt_authorization')
        return
    if type(s.get('attempt')) is int and s['attempt']==4:
        need(s.get('attempt_id')==FOURTH_ATTEMPT and s.get('authorization')==fourth_authorization(),
             'wrong_gate_attempt_authorization')
        return
    need(type(s.get('attempt')) is int and s['attempt'] == 2 and
         s.get('attempt_id') == AUTHORIZED_ATTEMPT and s.get('authorization') == original_failure(),
         'wrong_gate_attempt_authorization')


def third_authorization():
    original=original_failure()
    raw=REMEDIATION_CHECKPOINT.read_bytes();old=json.loads(raw.decode('utf8'))
    validate_attempt(old)
    need(old['status']=='FAILURE/BLOCKED' and old['reason']=='no_real_eligible_candidate_single_discovery' and
         'valuation_start_ns' not in old and old['hard_stop'] is True and old['dependent_tasks_allowed'] is False,
         'second_failed_prevaluation_checkpoint_required')
    need(old['evidence_sha256']==digest({k:v for k,v in old.items() if k!='evidence_sha256'}),'second_failed_evidence_changed')
    return dict(authority='explicit_user_third_attempt_with_bounded_cross_version_discovery',additional_attempts=1,
                original=original,second_checkpoint=REMEDIATION_CHECKPOINT.relative_to(ROOT).as_posix(),
                second_capture_sha256=hashlib.sha256(raw).hexdigest())


def fourth_authorization():
    raw=THIRD_CHECKPOINT.read_bytes();old=json.loads(raw.decode('utf8'))
    validate_attempt(old)
    need(old['status']=='FAILURE/BLOCKED' and old['hard_stop'] is True and old['dependent_tasks_allowed'] is False and
         'valuation_start_ns' not in old,'third_prevaluation_failure_required')
    need(old['evidence_sha256']==digest({k:v for k,v in old.items() if k!='evidence_sha256'}),'third_failed_evidence_changed')
    return dict(authority='explicit_user_try_again_after_normal_login_recovery',additional_attempts=1,
                previous=third_authorization(),third_checkpoint=THIRD_CHECKPOINT.relative_to(ROOT).as_posix(),
                third_capture_sha256=hashlib.sha256(raw).hexdigest())


def require_pass(path=None):
    s = json.loads(Path(path if path is not None else selected_checkpoint()).read_text(encoding='utf-8'))
    need(s['status'] == 'PASS' and s['dependent_tasks_allowed'] is True and
         s['hard_stop'] is False and s['automatic_reruns'] is False and s['automatic_repairs'] is False,
         'gate_not_PASS_items_4_through_12_blocked')
    need(s['evidence_sha256'] == digest({k:v for k,v in s.items() if k != 'evidence_sha256'}), 'sealed_gate_evidence_changed')
    return admission_proof(s)


def run(*, desktop, definition_id=DEFINITION_ID, window=None):
    # A prior RUNNING, failed, blocked, or passed window is never overwritten.
    w = window if window is not None else Window()
    f = None
    try:
        h = EdgeExecutor().request('/health')
        need(h['attached'] and h['mutations_enabled'] is False, 'read_only_attachment_required')
        s = w.state
        s.update(health_before=h, desktop=desktop, context=h['owner']['context'])
        s['cache_inventory'] = cache_snapshot(ROOT/'private-captures', s['context'], definition_id)
        need(s['cache_inventory'] and all(not c['exact_key_rows'] for c in s['cache_inventory']), 'previously_cached_version')
        f = Foundation(ReadOnlyGateExecutor(w), context=s['context'], owner=h['owner']['owner'],
                       journal_path=JOURNAL, cache_path=CACHE, interval=2)
        s['fences'] = deepcopy(f.adapter.fences)
        s['stage'] = 'DISCOVERY'; w.save()
        discovery = f.read('search', Search.discovery(definition_id).params())
        candidates = [r for r in discovery['result']['auctions'] if r['trade_state'] == 'active' and
                      r['expires'] > 60 and r['bid_state'] in {'none', 'outbid'} and
                      r['item']['definition_id'] == definition_id and r['item']['untradeable'] is False]
        need(candidates, 'no_real_eligible_candidate_single_discovery')
        candidate = min(candidates, key=lambda r: r['current_bid'] or r['starting_bid'])
        evaluate_window(f, w, discovery, candidate)
        admission_proof(s)
        s.update(status='PASS', hard_stop=False, dependent_tasks_allowed=True, finished_at=utc())
        s['evidence_sha256'] = digest(s)
        w.save()
    except Exception as error:
        # Only controlled error classes/reasons, never native payloads or auth data.
        reason = str(error) if type(error) in {ValueError, TimeoutError} and str(error).replace('_','').isalnum() else type(error).__name__
        w.stop(reason)
    finally:
        if f is not None:
            f.close()
    return {k:w.state.get(k) for k in ('status','reason','elapsed_ns','hard_stop','dependent_tasks_allowed')}


def desktop_preflight():
    """Strict UTF-8 JSON transport. Never parse or retain unrelated UI labels."""
    try:
        inspection = subprocess.run(['powershell','-NoProfile','-File',str(ROOT/'fc_access/production_v1/ui.ps1'),
                                     '-Action','preflight-json'], capture_output=True, text=False,
                                    check=False, timeout=20)
    except subprocess.TimeoutExpired:
        raise ValueError('desktop_subprocess_timeout') from None
    except OSError:
        raise ValueError('desktop_subprocess_unavailable') from None
    need(inspection.returncode == 0, 'desktop_subprocess_failed')
    raw = inspection.stdout
    need(type(raw) is bytes and 0 < len(raw) <= 16384, 'desktop_output_missing_or_unbounded')
    def unique_fields(pairs):
        result = {}
        for key,value in pairs:
            need(key not in result, 'duplicate_desktop_field')
            result[key] = value
        return result
    try:
        desktop = json.loads(raw.decode('utf-8-sig', errors='strict'), object_pairs_hook=unique_fields)
    except UnicodeDecodeError:
        raise ValueError('desktop_output_invalid_utf8') from None
    except (ValueError, RecursionError):
        raise ValueError('desktop_output_invalid_json') from None
    need(type(desktop) is dict and set(desktop) == {
        'observed_at','edge_control_verified','foreground_verified','official_tab','extensions_manager'},
        'desktop_output_invalid_schema')
    need(all(type(desktop[k]) is bool for k in ('edge_control_verified','foreground_verified','official_tab','extensions_manager')),
         'desktop_output_invalid_schema')
    try:
        need(isinstance(desktop['observed_at'], str), 'desktop_output_invalid_timestamp')
        observed = stamp(desktop['observed_at'])
        need(0 <= (datetime.now(timezone.utc)-observed).total_seconds() <= 30, 'desktop_output_stale')
    except (TypeError, ValueError, OverflowError):
        raise ValueError('desktop_output_invalid_or_stale_timestamp') from None
    need(desktop['official_tab'] and desktop['foreground_verified'] and desktop['edge_control_verified'] and
         not desktop['extensions_manager'], 'official_Edge_tab_required')
    return desktop


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', choices=[AUTHORIZED_ATTEMPT], required=True)
    args = parser.parse_args(argv)
    # Reread current recovery instructions and verify this worker's own UI access.
    (ROOT/'AGENTS.md').read_text(encoding='utf-8')
    # Consume the separate authorized slot BEFORE desktop/service/native work.
    w = Window(selected_checkpoint(args.attempt), authorization=original_failure())
    w.state.update(stage='DESKTOP_PREFLIGHT', live_command_attempted=True)
    w.save()
    try:
        desktop = desktop_preflight()
    except Exception as error:
        reason = str(error) if type(error) is ValueError and str(error).replace('_','').isalnum() else type(error).__name__
        w.stop(reason)
        return {k:w.state.get(k) for k in ('status','reason','elapsed_ns','hard_stop','dependent_tasks_allowed')}
    return run(desktop=desktop, window=w)


if __name__ == '__main__':
    print(json.dumps(main()))
