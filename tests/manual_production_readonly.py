"""Explicit finite live verification. Requires the official production attachment.

Never called by test discovery. No mutations, actors, retries or historical
window reuse. Each stage reserves its own operations before delivery.
"""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1.contracts import Search, parse_response
from fc_access.production_v1.executor import EdgeExecutor
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.inventory import KnownTrade, compare_lite_identity
from fc_access.production_v1.price_cache import QuoteCache
from fc_access.production_v1.prices import CardKey

OUT = ROOT/'docs/research/001d/final-remediation'
CHECKPOINT = OUT/'live-checkpoint.json'
JOURNAL = ROOT/'private-captures/final-remediation/foundation.sqlite3'
CACHE = JOURNAL.with_name('completed-quotes.sqlite3')


def now():
    return datetime.now(timezone.utc)


def save(state):
    temp = CHECKPOINT.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(state, stream, indent=2); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    temp.replace(CHECKPOINT)


class ReadOnlyRecorder(EdgeExecutor):
    def __init__(self, state):
        super().__init__(); self.state = state

    def execute(self, command):
        state = self.state
        local = command['operation'] in {'status_support', 'price_helpers'}
        if command['operation'] not in {'search', 'watched', 'balance', 'caps', 'status',
                                        'price_helpers', 'status_support'}:
            raise ValueError('read_only_allowlist')
        if now() >= datetime.fromisoformat(state['deadline']):
            raise ValueError('new_window_deadline_exhausted')
        counter, limit = ('reserved_local', state['max_local']) if local else ('reserved_GETs', state['max_GETs'])
        if state[counter] >= limit:
            raise ValueError('new_window_budget_exhausted')
        state[counter] += 1
        entry = dict(command=command, state='RESERVED_BEFORE_DELIVERY', at=now().isoformat())
        state['operations'].append(entry); save(state)
        response = super().execute(command)
        response = parse_response(response, command, pricing_rows=command['operation'] == 'search'
                                  and command['params']['purpose'] == 'pricing')
        entry.update(state='RESPONSE_RECORDED', response=response)
        save(state)
        return response


def exact_status(foundation, known):
    response = foundation.adapter.known_status(foundation.ids(), **known)
    rows = response['result']['auctions']
    if len(rows) != 1:
        raise ValueError('one_exact_status_row_required')
    row = rows[0]
    outcome = compare_lite_identity(KnownTrade(**known), dict(trade_id=row['trade_id'],
        item_id=row['item']['item_id'], definition_id=row['item']['definition_id']))
    if not outcome.startswith('MATCH'):
        raise ValueError('status_identity_mismatch')
    return dict(response_id=response['command_id'], identity_check=outcome, row=row)


def first():
    if CHECKPOINT.exists():
        raise ValueError('existing_live_checkpoint_no_replay')
    (ROOT/'AGENTS.md').read_text(encoding='utf-8')
    health = EdgeExecutor().request('/health')
    if not health['attached'] or health['mutations_enabled']:
        raise ValueError('attached_read_only_service_required')
    state = dict(task='001d-final-remediation', mode='LIVE_READ_ONLY', phase='IN_FLIGHT',
        started_at=now().isoformat(), deadline=(now()+timedelta(seconds=600)).isoformat(),
        max_GETs=16, max_local=512, reserved_GETs=0, reserved_local=0,
        account_mutations=0, operations=[], health_before=health)
    save(state)
    executor = ReadOnlyRecorder(state)
    owner = health['owner']
    f = Foundation(executor, context=owner['context'], owner=owner['owner'],
                   journal_path=JOURNAL, cache_path=CACHE, interval=2)
    try:
        state['fences_before_reconnect'] = f.adapter.fences
        support = f.adapter.status_support(f.ids())
        state['mapping_before_watched'] = support['result']['retained_count']; save(state)
        watched = f.read('watched')
        if watched['result']['auctions']:
            row = watched['result']['auctions'][0]
            state['known_identity'] = dict(trade_id=row['trade_id'], item_id=row['item']['item_id'],
                                          definition_id=row['item']['definition_id'])
            state['status_before_reconnect'] = exact_status(f, state['known_identity']); save(state)
        else:
            state['status_limitation'] = 'fresh_watched_empty_no_known_trade'
        # Finite exact-version discovery; no actor, pagination, or price probing.
        discovery = f.read('search', Search.discovery(233731).params())
        candidates = [r for r in discovery['result']['auctions'] if r['trade_state'] == 'active'
                      and r['expires'] > 60 and r['bid_state'] != 'highest'
                      and r['item']['untradeable'] is False]
        if not candidates:
            state['pricing_limitation'] = 'no_eligible_real_233731_discovery_candidate'
        else:
            candidate = min(candidates, key=lambda r: r['current_bid'] or r['starting_bid'])
            funds = f.read('balance')
            decision = f.admit(discovery, candidate['trade_id'], funds)
            state['decision'] = decision; save(state)
            quote = decision.get('quote')
            if quote and quote['completed']:
                prices = f.prices.loaded[f.prices.latest[CardKey(candidate['item']['definition_id'])]]
                state['cache_hit'] = asdict(f.pricing.quote(candidate, prices))
                reopened = QuoteCache(CACHE)
                try:
                    state['cache_reopened'] = reopened.get(f.adapter.context, prices.key.definition_id,
                                                          now=now(), source='native')
                finally:
                    reopened.close()
            else:
                state['pricing_limitation'] = 'quote_not_completed_two_samples'
        state['registry_before_close'] = f.registry.current()
        state['registry_events'] = f.registry.events()
        state['scheduler_metrics'] = f.executor.metrics
        state['phase'] = 'AWAITING_MANUAL_RECONNECT'
    except (ValueError, TimeoutError):
        state['phase'] = 'STOPPED_NO_RETRY'
        raise
    finally:
        f.close(); save(state)
    # Read a freshly opened connection; no Foundation startup or ownership change.
    db = sqlite3.connect(JOURNAL.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        state['restart_readable'] = dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            events=db.execute('SELECT COUNT(*) FROM registry_events_v1').fetchone()[0],
            bid_commands=db.execute('SELECT COUNT(*) FROM commands').fetchone()[0])
    finally:
        db.close(); save(state)
    print(json.dumps(dict(phase=state['phase'], reserved_GETs=state['reserved_GETs'],
                         pricing_limitation=state.get('pricing_limitation'),
                         status_limitation=state.get('status_limitation'))))


def after_reconnect():
    state = json.loads(CHECKPOINT.read_text(encoding='utf-8'))
    if state['phase'] != 'AWAITING_MANUAL_RECONNECT':
        raise ValueError('reconnect_stage_already_consumed_or_not_prepared')
    state['phase'] = 'RECONNECT_IN_FLIGHT'; save(state)
    executor = ReadOnlyRecorder(state)
    health = executor.request('/health'); old = state['fences_before_reconnect']
    if not health['attached'] or health['mutations_enabled'] or health['peer']['fences']['document'] == old['document']:
        state['phase'] = 'STOPPED_RECONNECT_MISSING'; save(state)
        raise ValueError('genuine_new_document_required')
    f = Foundation(executor, context=health['owner']['context'], owner=health['owner']['owner'],
                   journal_path=JOURNAL, cache_path=CACHE, interval=2)
    try:
        state['fences_after_reconnect'] = f.adapter.fences
        support = f.adapter.status_support(f.ids())
        state['mapping_after_reconnect_before_watched'] = support['result']['retained_count']; save(state)
        if support['result']['retained_count'] != 0:
            raise ValueError('previous_native_mapping_not_invalidated')
        watched = f.read('watched')
        known = state.get('known_identity')
        matches = [r for r in watched['result']['auctions'] if known and
                   (r['trade_id'], r['item']['item_id'], r['item']['definition_id']) ==
                   (known['trade_id'], known['item_id'], known['definition_id'])]
        if len(matches) == 1:
            state['status_after_reconnect'] = exact_status(f, known)
        else:
            state['status_limitation'] = 'same_exact_trade_item_version_not_reacquired'
        state['phase'] = 'COMPLETED_BOUNDED_OPERATIONS'
    finally:
        f.close(); state['finished_at'] = now().isoformat(); save(state)
    print(json.dumps(dict(phase=state['phase'], reserved_GETs=state['reserved_GETs'],
                         status_limitation=state.get('status_limitation'))))


def valuation_followup():
    """One independent quote after the first returned INCOMPLETE, never a retry
    of any original command or a third search within either quote. The original
    checkpoint is read only; its consumed budget remains part of the total 16.
    """
    global CHECKPOINT
    prior = json.loads(CHECKPOINT.read_text(encoding='utf-8'))
    if prior['phase'] != 'COMPLETED_BOUNDED_OPERATIONS':
        raise ValueError('original_run_must_be_terminal')
    remaining = 16-prior['reserved_GETs']
    CHECKPOINT = OUT/'valuation-followup.json'
    if CHECKPOINT.exists() or remaining < 5:
        raise ValueError('followup_already_consumed_or_budget_unavailable')
    health = EdgeExecutor().request('/health')
    if not health['attached'] or health['mutations_enabled']:
        raise ValueError('attached_read_only_service_required')
    state = dict(task='001d-final-remediation-valuation-followup', mode='LIVE_READ_ONLY',
        phase='IN_FLIGHT', started_at=now().isoformat(), deadline=(now()+timedelta(seconds=300)).isoformat(),
        max_GETs=remaining, max_local=512, reserved_GETs=0, reserved_local=0,
        previous_GETs=prior['reserved_GETs'], aggregate_GET_limit=16,
        account_mutations=0, operations=[], health_before=health,
        diagnostic_exceptions=[])
    save(state)
    def trace(frame, event, arg):
        if event == 'exception' and Path(frame.f_code.co_filename).name in {'pricing.py', 'prices.py',
                'adapter.py', 'contracts.py', 'executor.py', 'manual_production_readonly.py'}:
            if arg[0] not in {StopIteration, GeneratorExit} and len(state['diagnostic_exceptions']) < 64:
                state['diagnostic_exceptions'].append(dict(module=Path(frame.f_code.co_filename).name,
                    function=frame.f_code.co_name, line=frame.f_lineno, exception_class=arg[0].__name__))
        return trace
    executor = ReadOnlyRecorder(state); owner = health['owner']
    f = Foundation(executor, context=owner['context'], owner=owner['owner'],
                   journal_path=JOURNAL, cache_path=CACHE, interval=2)
    try:
        discovery = f.read('search', Search.discovery(233731).params())
        candidates = [r for r in discovery['result']['auctions'] if r['trade_state'] == 'active'
                      and r['expires'] > 60 and r['bid_state'] != 'highest'
                      and r['item']['untradeable'] is False]
        if not candidates:
            raise ValueError('no_eligible_real_candidate')
        candidate = min(candidates, key=lambda r: r['current_bid'] or r['starting_bid'])
        funds = f.read('balance')
        sys.settrace(trace)
        try:
            state['decision'] = f.admit(discovery, candidate['trade_id'], funds)
        finally:
            sys.settrace(None)
        quote = state['decision'].get('quote')
        if quote and quote['completed']:
            prices = f.prices.loaded[f.prices.latest[CardKey(candidate['item']['definition_id'])]]
            state['cache_hit'] = asdict(f.pricing.quote(candidate, prices))
            reopened = QuoteCache(CACHE)
            try:
                state['cache_reopened'] = reopened.get(f.adapter.context, prices.key.definition_id,
                                                      now=now(), source='native')
            finally:
                reopened.close()
        state['registry_before_close'] = f.registry.current()
        state['registry_events'] = f.registry.events()
        state['scheduler_metrics'] = f.executor.metrics
        state['phase'] = 'COMPLETED_BOUNDED_OPERATIONS'
    finally:
        f.close(); sys.settrace(None); state['finished_at'] = now().isoformat(); save(state)
    db = sqlite3.connect(JOURNAL.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        state['restart_readable'] = dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            events=db.execute('SELECT COUNT(*) FROM registry_events_v1').fetchone()[0],
            bid_commands=db.execute('SELECT COUNT(*) FROM commands').fetchone()[0])
    finally:
        db.close(); save(state)
    print(json.dumps(dict(phase=state['phase'], reserved_GETs=state['reserved_GETs'],
        quote_status=state.get('decision', {}).get('quote', {}).get('status'),
        diagnostic_exceptions=state['diagnostic_exceptions'])))


def fresh_admission():
    """A separate three-GET window after interruption, with zero price searches.

    Never reopens the expired quote/status windows or their counters. Uses the
    genuinely completed persisted quote, plus new discovery, credits and caps.
    """
    global CHECKPOINT
    CHECKPOINT = OUT/'fresh-admission.json'
    if CHECKPOINT.exists():
        raise ValueError('fresh_admission_window_consumed')
    (ROOT/'AGENTS.md').read_text(encoding='utf-8')
    health = EdgeExecutor().request('/health')
    if not health['attached'] or health['mutations_enabled']:
        raise ValueError('attached_read_only_service_required')
    state = dict(task='001d-final-remediation-fresh-cache-admission', mode='LIVE_READ_ONLY',
        phase='IN_FLIGHT', started_at=now().isoformat(), deadline=(now()+timedelta(seconds=120)).isoformat(),
        max_GETs=3, max_local=128, reserved_GETs=0, reserved_local=0,
        account_mutations=0, operations=[], health_before=health,
        previous_windows='Closed unchanged: live-checkpoint.json and valuation-followup.json')
    save(state)
    class CacheAdmissionRecorder(ReadOnlyRecorder):
        def execute(self, command):
            if command['operation'] == 'search' and command['params']['purpose'] != 'discovery':
                raise ValueError('no_new_pricing_search_authorized')
            return super().execute(command)
    executor = CacheAdmissionRecorder(state); owner = health['owner']
    f = Foundation(executor, context=owner['context'], owner=owner['owner'],
                   journal_path=JOURNAL, cache_path=CACHE, interval=2)
    try:
        discovery = f.read('search', Search.discovery(233731).params())
        candidates = [r for r in discovery['result']['auctions'] if r['trade_state'] == 'active'
                      and r['expires'] > 60 and r['bid_state'] != 'highest'
                      and r['item']['untradeable'] is False]
        if not candidates:
            raise ValueError('no_eligible_real_candidate')
        candidate = min(candidates, key=lambda r: r['current_bid'] or r['starting_bid'])
        funds = f.read('balance')
        state['decision'] = f.admit(discovery, candidate['trade_id'], funds)
        state['registry_before_close'] = f.registry.current()
        state['registry_events'] = f.registry.events()
        state['scheduler_metrics'] = f.executor.metrics
        state['phase'] = 'COMPLETED_BOUNDED_OPERATIONS'
    finally:
        f.close(); state['finished_at'] = now().isoformat(); save(state)
    db = sqlite3.connect(JOURNAL.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        state['restart_readable'] = dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            events=db.execute('SELECT COUNT(*) FROM registry_events_v1').fetchone()[0],
            bid_commands=db.execute('SELECT COUNT(*) FROM commands').fetchone()[0])
    finally:
        db.close(); save(state)
    print(json.dumps(dict(phase=state['phase'], reserved_GETs=state['reserved_GETs'],
        action=state.get('decision', {}).get('action'), reason=state.get('decision', {}).get('reason'),
        pricing_searches=state.get('decision', {}).get('quote', {}).get('evidence', {}).get('price_searches'))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['first', 'after-reconnect', 'valuation-followup', 'fresh-admission'])
    args = parser.parse_args()
    {'first': first, 'after-reconnect': after_reconnect, 'valuation-followup': valuation_followup,
     'fresh-admission': fresh_admission}[args.stage]()
