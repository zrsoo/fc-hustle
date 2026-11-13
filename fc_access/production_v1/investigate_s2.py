"""Explicit 001D-S2 one-shot read-only investigation. Never an acceptance test.

prepare activates a new labeled session; run requires the reviewed extension.
Reservations/deadline survive failure; rerunning run cannot replay the window.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import secrets
import time
from .executor import EdgeExecutor
from .adapter import NativeAdapter

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/research/001d/001d-03'
CHECKPOINT = OUT / 's2-checkpoint.json'


def save(state):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
        f.flush()
        import os
        os.fsync(f.fileno())
    tmp.replace(CHECKPOINT)


def prepare():
    if CHECKPOINT.exists():
        raise ValueError('existing_checkpoint_preserved')
    h = EdgeExecutor().request('/health')
    if h['service'] != 'fc-production-v1' or h['schema'] != 2 or h['mutations_enabled'] is not False or h['owner'] is not None:
        raise ValueError('existing_session_or_wrong_service')
    state = dict(task='001d-03', window='001D-S2', phase='PREPARED',
                 context=dict(account=secrets.token_hex(16), persona=secrets.token_hex(16),
                              identity_namespace=secrets.token_hex(16), game='fc27', platform='pc'),
                 owner=secrets.token_hex(16), epoch=1, definition_id=261855,
                 reserved_native_requests=0, reserved_helper_evaluations=0,
                 live_mutations=0, recurring_actors=0, observations=[])
    save(state)
    EdgeExecutor().request('/activate', {k: state[k] for k in ('context', 'owner', 'epoch')})
    print('PREPARED: click Attach production read-only bridge on official PC tab')


def run():
    state = json.loads(CHECKPOINT.read_text())
    if state['phase'] != 'PREPARED':
        raise ValueError('window_consumed_no_replay')
    a = NativeAdapter(EdgeExecutor(), context=state['context'], owner=state['owner'], epoch=state['epoch'])
    start = datetime.now(timezone.utc)
    state.update(phase='IN_FLIGHT', started_at=start.isoformat(), deadline=(start+timedelta(seconds=90)).isoformat())
    save(state)
    def read(operation, params, native=0, helpers=0):
        if datetime.now(timezone.utc) >= datetime.fromisoformat(state['deadline']):
            raise ValueError('deadline_exhausted')
        state['reserved_native_requests'] += native
        state['reserved_helper_evaluations'] += helpers
        if state['reserved_native_requests'] > 1 or state['reserved_helper_evaluations'] > 8:
            raise ValueError('budget_exhausted')
        cid = secrets.token_hex(16)
        state['pending_command'] = dict(id=cid, operation=operation)
        save(state)  # uncertain attempts consume budget; no automatic retry
        result = a.read(cid, operation, params)
        state['observations'].append(dict(command=a.commands[cid], response=result))
        state.pop('pending_command')
        save(state)
        return result['result']
    try:
        read('price_helpers', dict(version=1, probes=[]))
        caps = read('caps', dict(definition_id=state['definition_id']), native=1)['caps']
        probes = [dict(direction='above', value=v) for v in (750, 950, 1000, 9900)]
        probes += [dict(direction='below', value=v) for v in (1500, 1000, 10000, caps['minimum'])]
        prices = read('price_helpers', dict(version=1, probes=probes), helpers=8)['probes']
        lower = prices[4]['price']
        state.update(phase='COMPLETED', helper_availability='NATIVE_CLIENT_OBSERVED',
                     caps_evidence='AUTHENTICATED_EXACT_CARD_GET_OBSERVED',
                     pair=dict(buy_now_price=1500, starting_bid=lower,
                               status='PAIR_OBSERVED' if caps['minimum'] <= lower < 1500 <= caps['maximum'] else 'UNLISTABLE'),
                     transaction_verification='UNVERIFIED_NO_BID_OR_LISTING_EXECUTED')
    except (ValueError, TimeoutError):
        state.update(phase='STOPPED', reason='native_read_failed_no_retry',
                     transaction_verification='UNVERIFIED_NO_BID_OR_LISTING_EXECUTED')
        raise
    finally:
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        state['elapsed_seconds'] = (datetime.now(timezone.utc)-start).total_seconds()
        save(state)
    print(json.dumps({k: state[k] for k in ('phase', 'pair', 'reserved_native_requests', 'reserved_helper_evaluations', 'transaction_verification')}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'run'])
    args = p.parse_args()
    prepare() if args.action == 'prepare' else run()
