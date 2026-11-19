"""Minimal local monitor for the fix loop. Never sends an EA request itself.

    launch   start a new operational service generation plus a detached watcher
    watch    (internal) health every --interval s; on fault: owned stop + incident
    status   compact view for a periodic check-in: health, runtime, incident, events
    follow   read-only live view for a terminal (closing it never stops anything)
    stop     operator stop of the current generation (labelled as such)

The watcher replaces the orchestrator's quota-free health check: it uses the same
`operational.health` and `operational.stop`, counts consecutive healthy seconds
the same way (same generation, gap <= 2*interval + timeout) and never restarts
anything. Diagnosis, fixes and the next `launch` are done by the person or agent
checking in. Every generation is new; launch intents are journaled before spawn
and never replayed. Files live in private-captures/controller-v1/local-monitor.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time

from fc_access.actors_v1.locking import process_lock
from .operational import health, held, identity, read, same_process, stop as owned_stop, token

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'private-captures'/'controller-v1'
TASK = 'fc-local-monitor'
CHECK_TIMEOUT = 10


def paths(base=BASE):
    m = Path(base)/'local-monitor'
    return dict(base=Path(base), monitor=m, runtime=Path(base)/'operational', launches=m/'launches.jsonl',
                incidents=m/'incidents.jsonl', watcher=m/'watcher.json', lock=m/'watcher.lock')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def append(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True)+'\n'); stream.flush(); os.fsync(stream.fileno())


def lines(path, limit=None):
    if not Path(path).exists(): return []
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        try: rows.append(json.loads(line))
        except ValueError: continue  # a partially written last line
    return rows[-limit:] if limit else rows


def latest_launch(p):
    rows = lines(p['launches'])
    return rows[-1] if rows else None


def watch(generation, *, interval=30, startup=90, p=None, check=None, stop=None,
          clock=time.monotonic, sleep=time.sleep, wall=now_iso):
    """Health loop for one generation. Returns the incident it recorded."""
    p = p or paths(); token(generation)
    check = check or (lambda: health(p['runtime'], TASK, generation))
    stop = stop or (lambda: owned_stop(p['runtime'], TASK, generation, timeout=50))
    samples = p['monitor']/f'samples-{generation}.jsonl'
    with process_lock(p['lock']):
        me = identity(os.getpid())
        p['watcher'].write_text(json.dumps(dict(generation=generation, process=me, interval=interval,
                                                started_at=wall())), encoding='utf-8')
        started = clock(); healthy = 0.; last = None
        while True:
            try: report = check()
            except Exception as error:  # health itself never raises; be safe anyway
                report = dict(status='repair', generation=generation, diagnostic='HEALTH_CHECK_FAILED',
                              evidence=[dict(exception=type(error).__name__)])
            tick = clock()
            if report.get('status') == 'starting' and tick-started > startup:
                report = dict(report, status='repair', diagnostic='STARTING_OUTSIDE_GRACE')
            if report.get('status') == 'healthy':
                gap = None if last is None else tick-last
                healthy = healthy+gap if gap is not None and 0 <= gap <= 2*interval+CHECK_TIMEOUT else 0.
                last = tick
            else:
                healthy = 0.; last = None
            append(samples, dict(at=wall(), mono=tick, status=report.get('status'), diagnostic=report.get('diagnostic'),
                                 healthy_seconds=round(healthy, 1), evidence=report.get('evidence')))
            if report.get('status') not in {'healthy', 'starting'}:
                operator = (p['monitor']/f'operator-stop-{generation}').exists()
                try: stopped = stop()
                except Exception as error: stopped = dict(status='failed', exception=type(error).__name__)
                incident = dict(at=wall(), generation=generation, kind='OPERATOR_STOP' if operator else 'FAULT',
                                diagnostic=report.get('diagnostic'), healthy_seconds=round(healthy, 1),
                                uptime_seconds=round(tick-started, 1), stop=stopped)
                append(p['incidents'], incident)
                return incident
            sleep(interval)


def in_job():
    if os.name != 'nt': return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    value = wintypes.BOOL()
    return bool(kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(value)) and value.value)


def spawn(argv, log):
    """Detached child; returns (process, outside_caller_job).

    A caller inside a Windows job (e.g. an agent tool sandbox that may kill its
    tree) tries CREATE_BREAKAWAY_FROM_JOB; False means the child may die with it.
    """
    if os.name != 'nt':
        with open(log, 'ab') as stream:
            return subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                    start_new_session=True), True
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    jobbed = in_job()
    with open(log, 'ab') as stream:
        for extra in ((0x01000000, 0) if jobbed else (0,)):  # CREATE_BREAKAWAY_FROM_JOB
            try:
                child = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                         creationflags=flags | extra)
                return child, not jobbed or bool(extra)
            except OSError:
                if not extra: raise
    raise OSError('spawn_failed')


def db_epoch(base):
    try:
        db = sqlite3.connect((Path(base)/'controller.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
        try:
            row = db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
            return json.loads(row[0])['fences']['epoch'] if row else 0
        finally: db.close()
    except (sqlite3.Error, OSError, KeyError, ValueError): return 0


def watcher_argv(base, generation, interval, startup):
    # --base is a top-level option: it must precede the subcommand.
    return [sys.executable, '-m', 'fc_access.controller_v1.local_monitor', '--base', str(base), 'watch',
            '--generation', generation, '--interval', str(interval), '--startup', str(startup)]


def launch(a, p=None):
    p = p or paths(a.base)
    if held(p['runtime']): raise SystemExit('refused: an operational runtime already owns the lock')
    current = watcher_alive(p)
    if current: raise SystemExit('refused: a watcher is still running for '+current['generation'])
    generation = secrets.token_hex(16)
    previous = max([r.get('epoch_floor', 0) for r in lines(p['launches'])] + [0])
    floor = max(a.epoch_floor or 0, db_epoch(p['base'])+1, previous+1)
    startup = 180 if a.refresh_on_start else 90
    service = [sys.executable, '-m', 'fc_access.controller_v1.operational', 'service',
               '--runtime-dir', str(p['runtime']), '--task-key', TASK, '--generation', generation,
               '--database', str(p['base']/'controller.sqlite'), '--cache', str(p['base']/'quotes.sqlite'),
               '--context', str(p['base']/'public-context.json'), '--port', '8784',
               '--epoch-floor', str(floor), '--write-denial-measure', a.measure,
               '--maintenance-gap', str(a.maintenance_gap), '--auth-failure-measure', a.auth_measure,
               '--margin', str(a.margin), '--list-markup', str(a.list_markup)]
    if a.recovery_config: service += ['--recovery-config', a.recovery_config]
    if a.refresh_on_start: service += ['--refresh-on-start']
    watcher = watcher_argv(p['base'], generation, a.interval, startup)
    intent = dict(at=now_iso(), generation=generation, epoch_floor=floor, measure=a.measure, maintenance_gap=a.maintenance_gap,
                  auth_measure=a.auth_measure, margin=a.margin, list_markup=a.list_markup,
                  refresh_on_start=a.refresh_on_start, interval=a.interval, note=a.note)
    append(p['launches'], dict(intent, state='intent'))  # before spawn; never replayed
    child, breakaway = spawn(service, p['monitor']/f'service-{generation}.log')
    time.sleep(1)
    guard, guard_breakaway = spawn(watcher, p['monitor']/f'watcher-{generation}.log')
    append(p['launches'], dict(intent, state='spawned', service_pid=child.pid, watcher_pid=guard.pid,
                               breakaway=breakaway and guard_breakaway))
    print(json.dumps(dict(generation=generation, epoch_floor=floor, measure=a.measure, maintenance_gap=a.maintenance_gap,
                          service_pid=child.pid,
                          watcher_pid=guard.pid, outside_caller_job=breakaway and guard_breakaway)))


def watcher_alive(p):
    try: value = json.loads(p['watcher'].read_text(encoding='utf-8'))
    except (OSError, ValueError): return None
    return value if same_process(value.get('process')) else None


EA_TAX = 0.05


def trading(base, since):
    """Controller-owned results only, from its own durable move/list/bulk work.

    Won = verified wins accounted by a confirmed listing; relisted = those items
    inside confirmed relist_all sets; sold/profit = those items closed with a
    price in a confirmed clear_sold pre-read, net of EA's 5% tax minus the paid
    price. Manual cards never appear in move/list work, so they are excluded.
    """
    try:
        db = sqlite3.connect((Path(base)/'controller.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = db.execute("SELECT body,before_read,state,at FROM c4_work WHERE state='CONFIRMED'").fetchall()
        members = dict(db.execute("SELECT state,count(*) FROM c4_members GROUP BY state").fetchall())
    except sqlite3.Error:
        return None
    finally:
        db.close()
    work = [(json.loads(b), json.loads(r), at) for b, r, _, at in rows]
    listed = {}
    for c, _, at in work:  # all-time ownership/paid map, independent of window
        if c['operation'] == 'list':
            listed[c['params']['item_id']] = dict(paid=c['params']['paid'], buy_now=c['params']['buy_now_price'], at=at)
    inside = lambda at: since is None or at >= since
    won = [i for i, v in listed.items() if inside(v['at'])]
    relisted = sum(1 for c, _, at in work if c['operation'] == 'relist_all' and inside(at)
                   for i in c['params'].get('expected_item_ids', []) if i in listed)
    sold, sold_ever = {}, set()
    for c, before, at in work:
        if c['operation'] != 'clear_sold':
            continue
        for row in (before.get('result') or {}).get('auctions') or []:
            item = row['item']['item_id']
            if item in listed and row.get('trade_state') == 'closed' and row.get('current_bid', 0) > 0:
                sold_ever.add(item)
                if inside(at): sold[item] = row['current_bid']
    profit = sum(int(price*(1-EA_TAX)) - listed[item]['paid'] for item, price in sold.items())
    open_items = [i for i in listed if i not in sold_ever]
    unrealized = sum(int(listed[i]['buy_now']*(1-EA_TAX)) - listed[i]['paid'] for i in open_items)
    return dict(won_listed=len(won), relisted=relisted, sold=len(sold), realized_profit=profit,
                unsold_listed_all_time=len(open_items), unrealized_at_buy_now=unrealized,
                pending_wins_now=members.get('PENDING_WIN', 0), active_auctions_now=members.get('ACTIVE', 0))


def summarize(p, events=15):
    launch_row = latest_launch(p)
    if not launch_row: return dict(launch=None)
    generation = launch_row['generation']
    samples = lines(p['monitor']/f'samples-{generation}.jsonl')
    incidents = [i for i in lines(p['incidents']) if i['generation'] == generation]
    first = lines(p['launches'])[0]['at']
    out = dict(launch={k: launch_row.get(k) for k in ('generation', 'at', 'epoch_floor', 'measure', 'auth_measure', 'maintenance_gap', 'margin', 'list_markup', 'state', 'breakaway', 'note')},
               trading=dict(this_run=trading(p['base'], launch_row['at']), since_first_launch=trading(p['base'], first),
                            all_time=trading(p['base'], None)),
               watcher_alive=bool(watcher_alive(p)), samples=len(samples),
               last_sample={k: samples[-1].get(k) for k in ('at', 'status', 'diagnostic', 'healthy_seconds')} if samples else None,
               max_healthy_seconds=max([s.get('healthy_seconds') or 0 for s in samples] + [0]),
               incident=incidents[-1] if incidents else None)
    try:
        state = read(p['runtime']/'runs'/generation/'state.json')
    except (OSError, ValueError):
        return dict(out, runtime=None)
    s = state.get('semantic') or {}
    out['runtime'] = dict(state=state.get('state'), operational_state=state.get('operational_state'),
                          reason=state.get('reason'), at=state.get('at'), log=state.get('log'),
                          recovery=state.get('recovery'),
                          semantic={k: s.get(k) for k in ('native_successes', 'confirmed', 'batches', 'read_failures',
                                                           'write_failures', 'auth_failures', 'batch_failures',
                                                           'unconfirmed_attempts', 'recoverable', 'denied_bids',
                                                           'denial_seconds')})
    if state.get('log'):
        rows = lines(state['log'])
        interesting = []
        for r in rows:
            m = r.get('message') or {}
            if r['kind'] != 'WORKER':
                interesting.append({k: v for k, v in r.items() if k not in ('limits', 'steps')})
            elif m.get('kind') in {'failure', 'exit', 'batch_result'} or (
                    m.get('kind') == 'native_result' and not m.get('local') and m.get('success') is not True):
                interesting.append(dict(at=r['at'], kind=m.get('kind'), operation=m.get('operation'),
                                        state=m.get('state'), reason=m.get('reason'), service_status=m.get('service_status'),
                                        wire=m.get('wire_statuses'), error=m.get('error'), confirmed=m.get('confirmed'),
                                        uncertain=m.get('uncertain')))
        bids = [r['message'] for r in rows if r['kind'] == 'WORKER' and (r.get('message') or {}).get('kind') == 'native_result'
                and r['message'].get('operation') == 'bid']
        out['bids'] = dict(total=len(bids), accepted=sum(1 for b in bids if b.get('success') is True),
                           denied_461=sum(1 for b in bids if 461 in (b.get('wire_statuses') or [])))
        out['events'] = [{k: v for k, v in e.items() if v is not None} for e in interesting[-events:]]
    return out


def describe(row):
    """One human line per watchdog event; routine progress and helpers are skipped."""
    kind, m = row.get('kind'), row.get('message') or {}
    at = str(row.get('at', ''))[11:19]
    if kind != 'WORKER':
        extra = ' '.join(f'{k}={row[k]}' for k in ('reason', 'cause', 'measure', 'outcome', 'pid', 'exit_code', 'forced')
                         if row.get(k) is not None)
        return f'{at} {kind} {extra}'.rstrip()
    if m.get('kind') == 'native_result' and not m.get('local'):
        ok = 'ok' if m.get('success') is True else 'FAILED'
        wire = ','.join(str(x) for x in m.get('wire_statuses') or [])
        return f"{at} {m.get('operation')} {ok} wire={wire or '-'} service={m.get('service_status')}" + (
            f" error={m['error']}" if m.get('error') else '')
    if m.get('kind') == 'batch_result':
        return f"{at} batch {m.get('state')} confirmed={m.get('confirmed')} uncertain={m.get('uncertain')}"
    if m.get('kind') in {'failure', 'exit'}:
        return f"{at} worker {m.get('kind')} reason={m.get('reason')}"
    return None


def follow(p, *, every=2, sleep=time.sleep, rounds=None, out=print):
    """Read-only live view for a terminal: health line plus new watchdog events."""
    seen = {}; last_health = None; count = 0
    while rounds is None or count < rounds:
        count += 1
        row = latest_launch(p)
        if row:
            generation = row['generation']
            samples = lines(p['monitor']/f'samples-{generation}.jsonl', 1)
            if samples and samples[-1].get('at') != last_health:
                s = samples[-1]; last_health = s.get('at')
                out(f"--- health {s.get('status')} {s.get('diagnostic')} healthy={s.get('healthy_seconds')}s "
                    f"gen={generation[:8]} watcher={'alive' if watcher_alive(p) else 'stopped'}")
            try: log = read(p['runtime']/'runs'/generation/'state.json').get('log')
            except (OSError, ValueError): log = None
            if log:
                rows = lines(log)
                for r in rows[seen.get(log, 0):]:
                    text = describe(r)
                    if text: out(text)
                seen[log] = len(rows)
            for incident in [i for i in lines(p['incidents']) if i['generation'] == generation][seen.get('incident', 0):]:
                out(f"*** INCIDENT {incident['kind']} {incident.get('diagnostic')} healthy={incident.get('healthy_seconds')}s")
            seen['incident'] = len([i for i in lines(p['incidents']) if i['generation'] == generation])
        sleep(every)


def parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', default=str(BASE))
    sub = parser.add_subparsers(dest='action', required=True)
    l = sub.add_parser('launch')
    l.add_argument('--measure', default='noop'); l.add_argument('--recovery-config')
    l.add_argument('--refresh-on-start', action='store_true'); l.add_argument('--interval', type=int, default=30)
    l.add_argument('--epoch-floor', type=int); l.add_argument('--note', default='')
    l.add_argument('--maintenance-gap', type=float, default=120.0, help='seconds without bids after a maintenance write')
    l.add_argument('--auth-measure', default='noop', help='measure after a 401 auth-failure stop: noop or relogin')
    l.add_argument('--margin', type=int, default=500, help='profit margin X in the bid cap')
    l.add_argument('--list-markup', type=int, default=0, help='list won items at resale + markup')
    w = sub.add_parser('watch')
    w.add_argument('--generation', required=True); w.add_argument('--interval', type=int, default=30)
    w.add_argument('--startup', type=int, default=90)
    s = sub.add_parser('status'); s.add_argument('--events', type=int, default=15)
    sub.add_parser('stop'); sub.add_parser('follow', help='read-only live view; Ctrl+C only closes the view')
    return parser


def main(argv=None):
    a = parser().parse_args(argv); p = paths(a.base)
    if a.action == 'launch':
        if not 5 <= a.interval <= 300: raise SystemExit('interval must be 5..300 seconds')
        return launch(a, p)
    if a.action == 'watch':
        print(json.dumps(watch(a.generation, interval=a.interval, startup=a.startup, p=p))); return
    if a.action == 'follow':
        try: follow(p)
        except KeyboardInterrupt: pass
        return
    if a.action == 'status':
        print(json.dumps(summarize(p, a.events), indent=1)); return
    row = latest_launch(p)
    if not row: raise SystemExit('no launch recorded')
    (p['monitor']/f"operator-stop-{row['generation']}").write_text(now_iso(), encoding='utf-8')
    print(json.dumps(owned_stop(p['runtime'], TASK, row['generation'], timeout=50)))


if __name__ == '__main__':
    raise SystemExit(main())
