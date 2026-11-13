"""Explicit 001d-05 R1 probe. Not a validator or recurring account process.

Uses the existing selected account/owner; never creates a replacement session.
Reserve before delivery, persist all responses, stop without retry on failure.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets

from .adapter import NativeAdapter
from .contracts import parse_response
from .executor import EdgeExecutor

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/research/001d/001d-05'
CHECKPOINT = OUT / 'r1-checkpoint.json'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    tmp.replace(path)


def run():
    if CHECKPOINT.exists():
        raise ValueError('existing_checkpoint_no_replay')
    agents = (ROOT / 'AGENTS.md').read_bytes()  # explicit reread before recovery
    executor = EdgeExecutor()
    h = executor.request('/health')
    if (h.get('service') != 'fc-production-v1' or h.get('schema') != 2 or
            h.get('mutations_enabled') is not False or not h.get('attached')):
        raise ValueError('read_only_attachment_required')
    old = json.loads((ROOT / 'docs/research/001d/001d-03/s2-checkpoint.json').read_text())
    if old['phase'] != 'COMPLETED' or h['owner'] != {k: old[k] for k in ('context', 'owner', 'epoch')}:
        raise ValueError('existing_context_must_be_preserved')
    a = NativeAdapter(executor, **h['owner'])
    start = datetime.now(timezone.utc)
    state = dict(task='001d-05', window='R1-fresh-reads', phase='IN_FLIGHT',
                 context=a.context, fences=a.fences, agents_sha256=hashlib.sha256(agents).hexdigest(),
                 started_at=start.isoformat(), deadline=(start+timedelta(seconds=60)).isoformat(),
                 max_native_requests=4, reserved_native_requests=0, actual_native_requests=0,
                 mutations=0, observations=[], health_before=h)
    save(CHECKPOINT, state)
    try:
        for op in ('watched', 'balance', 'unassigned', 'transfer_list'):
            if datetime.now(timezone.utc) >= datetime.fromisoformat(state['deadline']):
                raise ValueError('deadline_exhausted')
            c = a.envelope(secrets.token_hex(16), op, {})
            state['reserved_native_requests'] += 1
            state['pending_command'] = c
            save(CHECKPOINT, state)
            v = executor.execute(c)
            # Only schema-validated allowlisted telemetry is retained.
            v = parse_response(v, c)
            state['observations'].append(dict(command=c, response=v))
            state['actual_native_requests'] += len(v['result']['network'])
            state.pop('pending_command')
            save(CHECKPOINT, state)
            if not v['result']['success'] or state['actual_native_requests'] > 4:
                raise ValueError('native_read_failed_no_retry')
        state['phase'] = 'COMPLETED'
    except (ValueError, TimeoutError):
        state.update(phase='STOPPED', reason='read_failed_or_unknown_no_retry')
        raise
    finally:
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        state['elapsed_seconds'] = (datetime.now(timezone.utc)-start).total_seconds()
        save(CHECKPOINT, state)
    print(json.dumps({k: state[k] for k in ('phase', 'reserved_native_requests', 'actual_native_requests', 'mutations')}))


if __name__ == '__main__':
    run()
