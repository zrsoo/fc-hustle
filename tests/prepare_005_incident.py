"""Explicit quiescent FC backup and allowlisted incident projection, no EA I/O."""
from collections import Counter
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.controller_v1.__main__ import guard_paths


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def backup(source, destination):
    with closing(connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if list(dst.execute('PRAGMA integrity_check')) != [('ok',)] or list(dst.execute('PRAGMA foreign_key_check')):
            raise ValueError('backup_integrity_failed')
        counts = {}
        for (table,) in src.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            # Names originate in the local SQLite schema, never shell interpolation.
            quoted = '"' + table.replace('"', '""') + '"'
            left = list(src.execute('SELECT * FROM ' + quoted))
            right = list(dst.execute('SELECT * FROM ' + quoted))
            if Counter(left) != Counter(right):
                raise ValueError('backup_rows_differ')
            counts[table] = len(left)
        return dict(integrity='ok', foreign_key_errors=0, row_comparison='equal', tables=counts)


def project(db):
    """Never retain arbitrary payloads, native selectors, exception strings or headers."""
    commands = []
    for cid, body, state, result in db.execute('SELECT id,body,state,result FROM c4_commands ORDER BY rowid'):
        c = json.loads(body)
        v = json.loads(result) if result else None
        r = (v if c['schema'] == 4 else v['result']) if v else {}
        n = r.get('network', [])
        commands.append(dict(command_id=cid, operation=c['operation'], schema=c['schema'], state=state,
            context=c['context'], fences=c['fences'], success=r.get('success'), error=r.get('error'),
            service_status=r.get('status'), observed_at=v.get('observed_at') if v else None,
            credits=r.get('credits'), designated_account_verified=r.get('designated_account_verified'),
            network_at=(v.get('network_at') if c['schema'] == 4 else v.get('freshness', {}).get('network_at')) if v else None,
            network=[{k: request.get(k) for k in ('method', 'path', 'status', 'targets', 'session_header_present')}
                     for request in n],
            receipt=r.get('receipt') if c['schema'] == 4 else r.get('bid_receipt'),
            target=c['params'].get('target'), amount=c['params'].get('amount')))
    return dict(classification='HISTORICAL_INCIDENT_PROJECTION_NOT_LIVE_PROOF',
        commands=commands,
        batches=[dict(batch_id=bid, state=state, started_at=json.loads(body).get('started_at'),
                      reason=json.loads(body).get('reason'))
                 for bid, state, body in db.execute('SELECT id,state,body FROM c4_policy_batches ORDER BY rowid')],
        attempts=[dict(command_id=cid, batch_id=bid, kind=kind, state=state)
                  for cid, bid, kind, state in db.execute('SELECT id,batch_id,kind,state FROM c4_attempts ORDER BY rowid')],
        member_count=db.execute('SELECT count(*) FROM c4_members').fetchone()[0],
        event_counts=dict(db.execute('SELECT kind,count(*) FROM c4_events GROUP BY kind')))


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    database = ROOT / 'private-captures/controller-v1/controller.sqlite'
    cache = database.with_name('quotes.sqlite')
    scope = json.loads(database.with_name('public-context.json').read_text())
    # No persistent processes are launched. Listeners plus canonical owner locks
    # establish quiescence before taking a new runtime-state backup.
    result = subprocess.run(['powershell', '-NoProfile', '-Command',
        "@(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in 8783,8784 } | ForEach-Object { @{port=$_.LocalPort;pid=$_.OwningProcess} }) | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=30, check=True)
    if result.stdout.strip():
        raise ValueError('production_listener_present')
    output = ROOT / 'docs/research/005' / ('incident-' + stamp)
    destination = Path('C:/hustle/orchestrator-migration-evidence') / ('005-' + stamp)
    with ExitStack() as stack:
        for path in guard_paths(ROOT, scope, database, 8784):
            stack.enter_context(process_lock(path))
        output.mkdir(parents=True, exist_ok=False)
        destination.mkdir(parents=True, exist_ok=False)
        receipt = dict(at=datetime.now(timezone.utc).isoformat(), backup_directory=str(destination),
                       canonical_locks_held=True, production_listeners=[], databases={})
        for path in (database, cache):
            receipt['databases'][path.name] = backup(path, destination / path.name)
        with closing(connect(database)) as db:
            projection = project(db)
        (output / 'incident.json').write_text(json.dumps(projection, indent=2) + '\n', encoding='utf-8')
        (output / 'backup.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status='PRESERVED', evidence=str(output), backup=str(destination))))


if __name__ == '__main__':
    main()
