"""Local-only evidence capture and independent structural assessment; never trades.

The bundle is a set of individually consistent SQLite snapshots, not an atomic
cross-database transaction. Business-case verification remains an independent
review against the live matrix. No structural check promotes live coverage.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from fc_access.production_v1.contracts import LOCAL_OPERATIONS, command, parse_response, stamp


def need(value, reason):
    if not value:
        raise ValueError(reason)


def read_db(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def records(db):
    return [dict(seq=s, run=r, kind=k, at=a, tick=t, body=json.loads(b))
            for s, r, k, a, t, b in db.execute(
                'SELECT seq,run,kind,at,tick,body FROM records ORDER BY seq')]


def digest(path):
    # Only sealed evidence copies are digested. Never mutable implementation.
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(state_dir, transport, output, *, revision):
    need(isinstance(revision,str) and revision.strip(), 'launch_revision_required')
    state, output = Path(state_dir).resolve(), Path(output).resolve()
    with closing(read_db(state / 'control.sqlite3')) as db:
        opened = [r for r in records(db) if r['kind'] == 'RUN_OPEN']
    need(opened, 'production_not_started')
    latest = opened[-1]
    manifest = latest['body']
    need(Path(manifest['state_dir']).resolve() == state, 'state_directory_mismatch')
    paths = dict(control=state/'control.sqlite3', native=state/'native.sqlite3',
                 journal=Path(manifest['journal']).resolve(), cache=Path(manifest['cache']).resolve(),
                 transport=Path(transport).resolve())
    need(all(p.is_file() for p in paths.values()), 'required_evidence_database_missing')
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    copies = {}
    for name, path in paths.items():
        target = output / (name + '.sqlite3')
        with closing(read_db(path)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst, pages=256, sleep=.01)
            need(dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'invalid_database')
            # Seal one self-contained file. Inheriting WAL mode would allow an
            # undigested sidecar to change what a later reader observes.
            dst.execute('PRAGMA journal_mode=DELETE')
        copies[name] = dict(file=target.name, source_path=str(path), sha256=digest(target))
    bundle = dict(schema=1, task='003-03', run=latest['run'], source=manifest['source'],
                  revision=revision, revision_scope='OPERATOR_DECLARED_LAUNCH_REVISION',
                  started_at=started, finished_at=datetime.now(timezone.utc).isoformat(),
                  consistency='INDIVIDUAL_SQLITE_SNAPSHOTS', databases=copies)
    # Written last; incomplete collections have no usable manifest. Never overwrite.
    (output/'manifest.json').write_text(json.dumps(bundle, indent=2)+'\n', encoding='utf8')
    return dict(status='CAPTURED', run=latest['run'], path=str(output))


def assess(directory):
    root = Path(directory).resolve()
    bundle = json.loads((root/'manifest.json').read_text(encoding='utf8'))
    need(bundle['schema'] == 1 and bundle['task'] == '003-03', 'wrong_bundle_scope')
    need(bundle['source'] in {'native', 'fixture'}, 'invalid_source')
    need(isinstance(bundle['revision'],str) and bundle['revision'].strip() and
         bundle['revision_scope']=='OPERATOR_DECLARED_LAUNCH_REVISION', 'launch_revision_required')
    need(stamp(bundle['finished_at']) >= stamp(bundle['started_at']), 'invalid_capture_interval')
    need(set(bundle['databases']) == {'control','native','journal','cache','transport'}, 'incomplete_bundle')
    paths = {}
    for name, entry in bundle['databases'].items():
        path = root/(name+'.sqlite3')
        need(entry['file'] == path.name and path.resolve().parent == root, 'unsafe_evidence_path')
        need(not any(Path(str(path)+suffix).exists() for suffix in ('-wal','-journal')),
             'unsealed_evidence_sidecar')
        need(digest(path) == entry['sha256'], 'sealed_evidence_changed')
        with closing(read_db(path)) as db:
            need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'invalid_database')
        paths[name] = path
    required_tables = dict(control={'records'}, native={'runtime','work','native_events'},
        journal={'events','commands','registry_events_v1'}, cache={'completed_quotes_v1'},
        transport={'commands','events','owner'})
    for name, required in required_tables.items():
        with closing(read_db(paths[name])) as db:
            actual = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            need(required <= actual, 'wrong_database_role:'+name)
    with closing(read_db(paths['control'])) as db:
        rows = records(db)
    opened = [r for r in rows if r['kind'] == 'RUN_OPEN']
    need(opened and opened[-1]['run'] == bundle['run'], 'capture_crossed_restart_repeat_capture')
    latest = opened[-1]
    need(latest['body']['source'] == bundle['source'], 'source_mismatch')
    run_rows = [r for r in rows if r['run'] == bundle['run']]
    attached = [r for r in run_rows if r['kind'] == 'ATTACHED']
    need(len(attached) == 1, 'attachment_evidence_missing_or_ambiguous')
    fences = attached[0]['body']['fences']
    context = latest['body']['context']
    problems, commands, independent, identities = [], [], [], set()

    def check(c, v, ref):
        command(c)
        need(c['id'] not in identities, 'duplicate_command_identity')
        identities.add(c['id'])
        need(c['context'] == context and c['fences'] == fences, 'command_identity_mismatch')
        if c['operation'] not in LOCAL_OPERATIONS:
            with closing(read_db(paths['transport'])) as db:
                retained = db.execute('SELECT body,result FROM commands WHERE id=?', (c['id'],)).fetchone()
            if retained is None:
                problems.append(dict(reference=ref, reason='TRANSPORT_NOT_YET_CAPTURED'))
            else:
                need(json.loads(retained[0]) == c, 'transport_command_mismatch')
                if v is not None:
                    need(retained[1] is not None and json.loads(retained[1]) == v,
                         'transport_response_mismatch')
        if v is None:
            problems.append(dict(reference=ref, reason='MISSING_RESPONSE_NO_RETRY'))
            return
        parse_response(v, c, source=bundle['source'], now=stamp(v['freshness']['observed_at']),
                       pricing_rows=c['operation']=='search' and c['params']['purpose']=='pricing')
        from fc_access.production_v1.bid_receipt import ordinary_rejection
        if not v['result']['success'] and not ordinary_rejection(c,v):
            problems.append(dict(reference=ref, reason='FAILED_CALLBACK_RETAINED'))

    with closing(read_db(paths['native'])) as db:
        runtime = json.loads(db.execute('SELECT body FROM runtime WHERE id=1').fetchone()[0])
        need(runtime['context'] == context and runtime['fences'] == fences and
             runtime['source'] == bundle['source'], 'runtime_identity_mismatch')
        for seq, cid, encoded, response, state in db.execute(
                'SELECT seq,id,command,response,state FROM work WHERE seq>? ORDER BY seq',
                (attached[0]['body'].get('work_start_seq', 0),)):
            c, v = json.loads(encoded), json.loads(response) if response else None
            need(cid == c['id'], 'mailbox_id_mismatch')
            ref = dict(database='native', table='work', seq=seq, command_id=cid)
            check(c, v, ref)
            commands.append(dict(**ref, operation=c['operation'], state=state,
                                 case_review_required=True))
            if state != 'DONE':
                problems.append(dict(reference=ref, reason='UNSETTLED_COMMAND'))
    for r in run_rows:
        if r['kind'] == 'RECOVERY_READ':
            b = r['body']; check(b['command'], b['response'], dict(database='control', seq=r['seq']))
        if r['kind'] in {'INCIDENT', 'SUPERVISION_GAP', 'RECOVERY_INTENT'}:
            independent.append(dict(database='control', seq=r['seq'], kind=r['kind']))
    # Independently reconstruct adjacent observed intervals; never add across runs,
    # READY boundaries, supervision gaps or stops. Runtime counters alone are insufficient.
    segments = []
    for start in opened:
        previous, seconds, ready, closed = None, 0, False, False
        for row in (r for r in rows if r['run'] == start['run']):
            tick = row['tick']
            need(type(tick) in (int,float) and math.isfinite(tick), 'invalid_monitor_tick')
            if row['kind'] == 'READY': ready = True
            if row['kind'] in {'SUPERVISION_GAP','STOP_REQUESTED','RUN_STOPPED','INCIDENT'}:
                closed, previous = True, None
            if row['kind'] == 'SNAPSHOT' and ready and not closed:
                if previous is not None:
                    delta = tick-previous
                    need(0 <= delta <= 10, 'unrecorded_monitor_gap')
                    seconds += delta
                previous = tick
                need(abs(row['body']['healthy_observed_seconds']-seconds) < .1,
                     'healthy_uptime_not_reproducible')
        segments.append(dict(run=start['run'], healthy_observed_seconds=seconds, closed=closed))
    return dict(status='STRUCTURALLY_VALID', evidence_class=(
        'NATIVE_CAPTURE_REQUIRES_CASE_REVIEW' if bundle['source']=='native' else 'OFFLINE_FIXTURE_ONLY'),
        run=bundle['run'], revision=bundle['revision'], commands=commands, findings=problems,
        incident_and_recovery_references=independent,
        healthy_segments=segments, live_coverage='LIVE-UNVERIFIED',
        realized_profit=dict(status='DEFERRED', acceptance_required=False),
        business_review='Apply matrix evidence requirements and independent-assessment.md; no automatic promotion')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    collect = sub.add_parser('capture')
    collect.add_argument('--state-dir', required=True)
    collect.add_argument('--transport', required=True)
    collect.add_argument('--output', required=True)
    collect.add_argument('--revision', required=True, help='Reviewed launch revision; independently verify provenance')
    audit = sub.add_parser('assess'); audit.add_argument('directory')
    args = parser.parse_args()
    try:
        value = capture(args.state_dir, args.transport, args.output, revision=args.revision) if args.action=='capture' else assess(args.directory)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        # No database bodies, credentials or arbitrary exception messages in console logs.
        print(json.dumps(dict(status='INVALID_EVIDENCE', error_type=type(error).__name__)))
        return 1
    print(json.dumps(value, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
