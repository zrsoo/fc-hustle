"""004-01 local baseline tools. No imports of live runtime constructors or HTTP.

Capture is explicit, exclusive and never rerun by acceptance validation. Application
SQLite sources below have reviewed sanitized schemas; the orchestrator is copied
only as a narrow control projection, excluding session and opaque payload columns.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/research/004/004-01'
DATABASES = [
    'private-captures/final-remediation/foundation.sqlite3',
    'private-captures/final-remediation/completed-quotes.sqlite3',
    'private-captures/final-remediation/native.sqlite3',
    'private-captures/final-remediation/transport.sqlite3',
    'private-captures/continuous-production/native.sqlite3',
    'private-captures/continuous-production/control.sqlite3',
    'private-captures/002-bulk-transfer-operations/production-readonly-after.sqlite3',
]
LEGACY = ('obj-29bea3b74eb3', 'obj-da182a175410')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode('utf-8').strip()


@contextmanager
def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    try:
        yield db
    finally:
        db.close()


def control_projection(db):
    """Never select orchestrator sessions, config, text, spec, result or data."""
    owners = "owner IN (?,?) OR owner LIKE ? OR owner LIKE ?"
    params = (*LEGACY, *(x + '/%' for x in LEGACY))
    result = {}
    for table, columns, where, values in [
        ('objective', 'id,state,control,infra_retries,created', 'id IN (?,?)', LEGACY),
        ('task', 'key,objective_id,id,state,control,attempts,infra_retries,accepted_stage,recheck',
         'objective_id IN (?,?)', LEGACY),
        ('turn', 'id,owner,kind,status,started,ended', owners, params),
        ('event', 'id,owner,turn_id,at,kind', owners, params),
        ('artifact', 'id,owner,at,kind', owners, params),
        ('validator', 'id,task_key,command,criteria,timeout,active',
         'task_key IN (SELECT key FROM task WHERE objective_id IN (?,?))', LEGACY),
        ('dependency', 'task_key,depends_key',
         'task_key IN (SELECT key FROM task WHERE objective_id IN (?,?))', LEGACY),
    ]:
        result[table] = dict(columns=columns.split(','), rows=[list(r) for r in db.execute(
            f'SELECT {columns} FROM {table} WHERE {where} ORDER BY 1', values)])
    return result


def processes():
    # Command lines are classified inside PowerShell and never returned/retained.
    script = r'''
      $rows=@(Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object { $_.Name -match '^(python(w)?|node|cmd|powershell|pwsh)\.exe$' } |
        ForEach-Object {
          $line=$_.CommandLine
          $module=[regex]::Match($line,'(?:^|\s)-m\s+(fc_access\.[\w.]+)').Groups[1].Value
          [pscustomobject]@{pid=$_.ProcessId; parent=$_.ParentProcessId; name=$_.Name;
            module=$module; command_visible=($null -ne $line);
            production_worker=($_.Name -match '^python(w)?\.exe$' -and
              $line -match 'fc_access[./\\](actors_v1|continuous_v1|production_v1|bulk_transfer_v1)|tests[\\/](manual_production|probe_00304)');
            orchestrator=($_.Name -match '^python(w)?\.exe$' -and $line -match 'orchestrat')}
        })
      $ports=@(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -ge 8780 -and $_.LocalPort -le 8799 } |
        ForEach-Object { [pscustomobject]@{port=$_.LocalPort; pid=$_.OwningProcess} })
      @{processes=$rows;listeners=$ports} | ConvertTo-Json -Depth 4 -Compress
    '''
    raw = subprocess.check_output(['powershell', '-NoProfile', '-Command', script], cwd=ROOT)
    value = json.loads(raw)
    if any(p['production_worker'] or (p['name'].startswith('python') and not p['command_visible'])
           for p in value['processes']) or value['listeners']:
        raise ValueError('competing_or_uninspectable_production_process')
    return value


def idle_locks():
    """Nonblocking checks of existing canonical guards; never create/reset one."""
    import os
    from contextlib import ExitStack
    paths = sorted((ROOT/'private-captures/production-v1').glob('*.lock'))
    if not paths:
        raise ValueError('canonical_lock_inventory_missing')
    with ExitStack() as stack:
        for path in paths:
            handle = stack.enter_context(path.open('r+b'))
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                def unlock(h=handle):
                    h.seek(0); msvcrt.locking(h.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                def unlock(h=handle):
                    fcntl.flock(h, fcntl.LOCK_UN)
            stack.callback(unlock)
    return [p.name for p in paths]


def inventory(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {n: dict(columns=[r[1] for r in db.execute(f'PRAGMA table_info("{n}")')],
                    rows=db.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0]) for n in names}


def capture():
    if (OUT/'baseline.json').exists():
        raise FileExistsError('baseline_already_captured_no_replay')
    OUT.mkdir(parents=True, exist_ok=True)
    target = ROOT.parent / 'fc-hustle-backups' / ('004-01-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    target.mkdir(parents=True, exist_ok=False)
    before = processes()
    status = git('status', '--porcelain=v1', '--untracked-files=all')
    files = [name for name in git('ls-files', '-z').split('\0') if name]
    with zipfile.ZipFile(target/'working-tree.zip', 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name in files:
            p = ROOT/name
            if p.is_file(): z.write(p, name)
    subprocess.run(['git', 'bundle', 'create', str(target/'repository.bundle'), '--all'], cwd=ROOT, check=True,
                   capture_output=True)
    (target/'working-tree.patch').write_text(git('diff', 'HEAD', '--binary'), encoding='utf-8')
    databases = []
    for index, name in enumerate(DATABASES):
        with readonly(ROOT/name) as src:
            copy = target/f'{index}-{Path(name).name}'
            dst = sqlite3.connect(copy)
            src.backup(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            databases.append(dict(source=name, backup=copy.name, tables=inventory(dst)))
            dst.close()
    with readonly(ROOT/'.orchestrator/state.db') as db:
        control = control_projection(db)
    (target/'legacy-control.json').write_text(json.dumps(control, indent=2)+'\n', encoding='utf-8')
    value = dict(schema=1, captured_at=datetime.now(timezone.utc).isoformat(), backup_directory=str(target),
                 git=dict(branch=git('branch','--show-current'), head=git('rev-parse','HEAD'), status=status),
                 tracked_entries=len(files), processes=before, databases=databases,
                 orchestrator_backup='legacy-control.json',
                 exclusions=['Edge profiles', 'credentials', 'cookies', 'headers', 'EA tokens/session IDs',
                             'raw orchestrator DB and session/payload columns', 'unreviewed private captures'],
                 initial_untracked_tool='tests/baseline_00401.py',
                 activity=dict(ea_requests=0, mutations=0, migrations=0, recovery=0))
    with (OUT/'baseline.json').open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2); f.write('\n')
    print(json.dumps(dict(backup_directory=str(target), databases=len(databases), tracked_entries=len(files))))


if __name__ == '__main__':
    capture()
