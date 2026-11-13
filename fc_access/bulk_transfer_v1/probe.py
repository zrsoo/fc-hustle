"""One explicitly named finite bulk research command. Never retries a command."""
import argparse
import json
import os
from pathlib import Path
import secrets
from datetime import datetime, timezone
from fc_access.production_v1.executor import EdgeExecutor
from .server import validate_command, validate_response

OUT = Path('docs/research/002-bulk-transfer-operations')


def save(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    temp.replace(path)


def run(operation, name, params=None):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT/(name+'.json')
    if path.exists():
        raise ValueError('existing_command_record_no_replay')
    e = EdgeExecutor(); h = e.request('/health')
    if h.get('profile') != 'finite-bulk-transfer-research' or not h['attached']:
        raise ValueError('finite_research_attachment_required')
    c = dict(schema=2, id=secrets.token_hex(16), operation=operation, params=params or {},
             context=h['peer']['context'], fences=h['peer']['fences'])
    validate_command(c)
    record = dict(started_at=datetime.now(timezone.utc).isoformat(), command=c,
                  phase='RESERVED_BEFORE_DELIVERY', health_before=h)
    save(path, record)
    try:
        result = validate_response(e.request('/run', c), c)
        record.update(phase='RESPONSE_RECORDED', response=result)
    except (ValueError, TimeoutError):
        record.update(phase='UNKNOWN_NO_RETRY')
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat(); save(path, record)
    print(json.dumps(dict(phase=record['phase'], success=result['success'], error=result['error'],
                         network_requests=len(result['network']), inventory=result.get('inventory'))))
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation'); p.add_argument('name'); p.add_argument('--params', type=Path)
    a = p.parse_args()
    if not a.name.replace('-', '').replace('_', '').isalnum():
        raise ValueError('simple_record_name_required')
    run(a.operation, a.name, json.loads(a.params.read_text()) if a.params else None)
