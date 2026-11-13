"""001D-S1 two-request investigation; no retries and no trade creation.

run: local source inspection, one watched read to retain exact native identity,
then one known status read. Reconnect inspection performs zero EA requests.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import secrets
from .adapter import NativeAdapter
from .contracts import parse_response
from .executor import EdgeExecutor
from .investigate_reads import ROOT, OUT, save

CHECKPOINT = OUT / 's1-checkpoint.json'


def prepare():
    if CHECKPOINT.exists():
        raise ValueError('existing_checkpoint_no_replay')
    agents = (ROOT / 'AGENTS.md').read_bytes()
    r1 = json.loads((OUT / 'r1-checkpoint.json').read_text())
    if r1['phase'] != 'COMPLETED':
        raise ValueError('r1_must_be_completed')
    h = EdgeExecutor().request('/health')
    if h['service'] != 'fc-production-v1' or h['schema'] != 2 or h['mutations_enabled'] is not False or h['owner']['context'] != r1['context']:
        raise ValueError('existing_read_only_context_required')
    state = dict(task='001d-05', window='S1-known-status', phase='PREPARED',
                 context=h['owner']['context'], owner=h['owner']['owner'], epoch=h['owner']['epoch'],
                 agents_sha256=hashlib.sha256(agents).hexdigest(), health_before=h,
                 max_native_requests=2, reserved_native_requests=0, actual_native_requests=0,
                 mutations=0, observations=[], source_inspections=[])
    save(CHECKPOINT, state)
    print('PREPARED: existing identity context retained, two read-only requests maximum')


def local_read(a, state):
    c = a.envelope(secrets.token_hex(16), 'status_support', {})
    r = parse_response(a.executor.execute(c), c)
    state['source_inspections'].append(dict(command=c, response=r))
    save(CHECKPOINT, state)
    if not r['result']['success'] or not r['result']['source_match']:
        raise ValueError('source_unsupported_no_native_request')
    return r


def run():
    state = json.loads(CHECKPOINT.read_text())
    if state['phase'] != 'PREPARED':
        raise ValueError('window_consumed_no_replay')
    a = NativeAdapter(EdgeExecutor(), **{k: state[k] for k in ('context', 'owner', 'epoch')})
    start = datetime.now(timezone.utc)
    state.update(phase='IN_FLIGHT', started_at=start.isoformat(), deadline=(start+timedelta(seconds=60)).isoformat())
    save(CHECKPOINT, state)
    def read(op, params):
        if datetime.now(timezone.utc) >= datetime.fromisoformat(state['deadline']) or state['reserved_native_requests'] >= 2:
            raise ValueError('budget_or_deadline_exhausted')
        c = a.envelope(secrets.token_hex(16), op, params)
        state['reserved_native_requests'] += 1
        state['pending_command'] = c
        save(CHECKPOINT, state)
        r = parse_response(a.executor.execute(c), c)
        state['observations'].append(dict(command=c, response=r))
        state['actual_native_requests'] += len(r['result']['network'])
        state.pop('pending_command')
        save(CHECKPOINT, state)
        if not r['result']['success'] or state['actual_native_requests'] > 2:
            raise ValueError('native_failure_no_retry')
        return r
    try:
        local_read(a, state)
        watched = read('watched', {})
        # Select the retained historical full-version row from the R1 observation,
        # never an arbitrary trade, raw input ID, or a cross-namespace hash.
        r1 = json.loads((OUT / 'r1-checkpoint.json').read_text())
        prior = r1['observations'][0]['response']['result']['auctions']
        eligible = [r for r in watched['result']['auctions'] if r in prior]
        if len(eligible) != 1:
            raise ValueError('eligible_known_historical_identity_unavailable')
        row = eligible[0]
        params = dict(trade_id=row['trade_id'], item_id=row['item']['item_id'], definition_id=row['item']['definition_id'])
        state['known_identity'] = params
        save(CHECKPOINT, state)
        read('status', params)
        local_read(a, state)
        state.update(phase='COMPLETED', current_context='EXACT_RETAINED_TRADE_LOOKUP_OBSERVED',
                     reconnect='UNVERIFIED_PENDING_LOCAL_INSPECTION')
    except (ValueError, TimeoutError):
        state.update(phase='STOPPED', reason='source_identity_or_read_failed_no_retry')
        raise
    finally:
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        state['elapsed_seconds'] = (datetime.now(timezone.utc)-start).total_seconds()
        save(CHECKPOINT, state)
    print(json.dumps({k: state[k] for k in ('phase', 'reserved_native_requests', 'actual_native_requests', 'current_context')}))


def reconnect_inspection():
    state = json.loads(CHECKPOINT.read_text())
    if state['phase'] != 'COMPLETED' or 'reconnect_inspection' in state:
        raise ValueError('completed_inspection_no_replay')
    (ROOT / 'AGENTS.md').read_bytes()
    h = EdgeExecutor().request('/health')
    if h['owner']['context'] != state['context'] or h['owner']['epoch'] <= state['epoch']:
        raise ValueError('explicit_new_epoch_same_context_required')
    old_document = state['observations'][0]['command']['fences']['document']
    if not h['attached'] or h['peer']['fences']['document'] == old_document:
        raise ValueError('new_document_attachment_required')
    # Reservation before local delivery prevents replay if its result is lost.
    state['reconnect_inspection'] = dict(phase='IN_FLIGHT', health=h, native_requests=0)
    save(CHECKPOINT, state)
    a = NativeAdapter(EdgeExecutor(), **h['owner'])
    result = local_read(a, state)
    count = result['result']['retained_count']
    state['reconnect_inspection'].update(phase='COMPLETED', retained_count=count)
    state['reconnect'] = 'NATIVE_MAPPING_UNAVAILABLE_AFTER_RECONNECT' if count == 0 else 'MAPPING_PRESENT_LOOKUP_UNVERIFIED'
    save(CHECKPOINT, state)
    print(json.dumps(dict(reconnect=state['reconnect'], new_native_requests=0)))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'run', 'reconnect-inspection'])
    args = p.parse_args()
    {'prepare': prepare, 'run': run, 'reconnect-inspection': reconnect_inspection}[args.action]()
