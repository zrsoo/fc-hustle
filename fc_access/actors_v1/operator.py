"""Read-only diagnostics and lossless evidence retention. Never attaches Edge."""
import json
from pathlib import Path
import sqlite3

from fc_access.bidding_v1.journal import Journal
from fc_access.production_v1.contracts import stamp, token
from fc_access.production_v1.foundation import scope_for


def inspect(path, view='status', *, trade=None, since=None, until=None):
    path = Path(path)
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        runtime = json.loads(db.execute('SELECT body FROM runtime WHERE id=1').fetchone()[0])
        counts = dict(db.execute('SELECT state,count(*) FROM work GROUP BY state'))
        native = [dict(zip(('command_id','role','state','operation','enqueued','started','finished','reason','queue_ms','roundtrip_ms'),
            (r[0],r[1],r[2],json.loads(r[3])['operation'],*r[4:]))) for r in db.execute(
                'SELECT id,role,state,command,enqueued,started,finished,reason,queue_ms,roundtrip_ms FROM work ORDER BY seq')]
        native_events = [dict(seq=r[0],command_id=r[1],at=r[2],**json.loads(r[3])) for r in db.execute(
            'SELECT seq,id,at,body FROM native_events ORDER BY seq')]
    finally: db.close()
    if view=='config': return runtime['config']
    journal = Journal(runtime['journal'],readonly=True)
    try:
        scope = scope_for(runtime['context'])
        sql = 'SELECT seq,trade_id,at,body FROM registry_events_v1 WHERE scope=?'
        args = [scope]
        if trade is not None: sql+=' AND trade_id=?'; args.append(token(trade,'trade'))
        events = [dict(seq=r[0],trade_id=r[1],at=r[2],**json.loads(r[3])) for r in journal.db.execute(sql+' ORDER BY seq',args)]
        journal_events = journal.trace(scope=scope,trade_id=trade)
        def inside(e):
            at = stamp(e['at'])
            return (since is None or at>=stamp(since)) and (until is None or at<=stamp(until))
        if since is not None and until is not None and stamp(since)>stamp(until): raise ValueError('invalid_time_window')
        selected = [e for e in events if inside(e)]
        if view=='timeline': return dict(registry=selected,journal=[e for e in journal_events if inside(e)])
        if view=='decisions': return [e for e in selected if e['kind']=='DECISION']
        if view=='blocked': return [e for e in selected if e.get('action') in {'HOLD','UNKNOWN','REJECT'} or
            e.get('reason') in {'CYCLE_BLOCKED','DRAINING','RECONCILIATION_REQUIRED','MISSING_OR_STALE_IDENTITY','OUTCOME_STILL_UNKNOWN','STALE_STATUS'}]
        if view=='export': return dict(schema=1,context=runtime['context'],config=runtime['config'],
            registry=selected,journal=[e for e in journal_events if inside(e)],native=native,
            native_events=[e for e in native_events if inside(e)])
        if view!='status': raise ValueError('unknown_view')
        from fc_access.bidding_v1.core import AuctionQueue
        queue = AuctionQueue(journal=journal,scope=scope,reserve=runtime['config']['min_available_coins'])
        actors, decisions, coins, occupancy = {}, {}, None, None
        for e in events:
            if e['kind']=='ACTOR': actors[e['actor']]=e
            if e['kind']=='DECISION': decisions[e['trade_id']]=e
            if e['kind']=='CREDITS': coins=e
            if e['kind']=='ACTOR' and 'occupancy' in e:
                occupancy=dict(e['occupancy'],at=e['at'],epoch=e['epoch'])
        from .native import utc
        for role,value in actors.items():
            value['heartbeat_age_seconds'] = max(0,(utc()-stamp(value['at'])).total_seconds())
            interval = runtime['config']['search_interval_seconds' if role=='acquirer' else 'target_check_interval_seconds']
            value['fresh'] = value['epoch']==runtime['fences']['epoch'] and value['heartbeat_age_seconds']<=interval+runtime['config']['command_timeout_seconds']
        if coins:
            coins['available_after_reservations']=max(0,coins['available_coins']-sum(v[0] for v in queue.reservations.values()))
            from .native import utc
            coins['fresh']=0<=(utc()-stamp(coins['network_at'])).total_seconds()<=30
        if occupancy:
            occupancy['fresh']=occupancy['epoch']==runtime['fences']['epoch'] and occupancy['network_at'] is not None and 0<=(utc()-stamp(occupancy['network_at'])).total_seconds()<=30
            if not occupancy['fresh']:
                occupancy.update(enrollment_allowed=False,current_reason='TRANSFER_LIST_STALE' if occupancy['network_at'] else 'TRANSFER_LIST_UNKNOWN')
        from fc_access.bidding_v1.capacity import status as capacity_status
        pauses = [e for e in events if e.get('actor')=='acquirer' and
            e.get('reason') in {'CAPACITY_PAUSED','CAPACITY_RESUMED'}]
        enrollment = None if not pauses else dict(capacity_paused=pauses[-1]['reason']=='CAPACITY_PAUSED',
            capacity_reason=pauses[-1]['capacity_reason'], at=pauses[-1]['at'], epoch=pauses[-1]['epoch'])
        from fc_access.production_v1.bulk import pending as pending_bulk
        from fc_access.production_v1.resale import pending as pending_resale
        unresolved = [dict(command_id=r[0],trade_id=r[1],state=r[2]) for r in journal.db.execute(
            "SELECT id,trade_id,state FROM commands WHERE scope=? AND state NOT IN ('RECONCILED','NOT_DISPATCHED')",(scope,))]
        unresolved.extend(pending_bulk(journal, scope))
        unresolved.extend(pending_resale(journal, scope))
        return dict(context=runtime['context'],epoch=runtime['fences']['epoch'],actors=actors,coins=coins,
            enrollment=enrollment,
            transfer_list_occupancy=occupancy,
            capacity=capacity_status(journal,scope,now=utc()),
            unresolved_auctions=sorted(queue.entries),draining=queue.draining,native_queue=counts,
            unresolved_intents=unresolved,
            decisions=decisions)
    finally: journal.close()


def retain(mailbox_path, destination):
    """Lossless SQLite backups, including all unresolved and settlement evidence.

    No event pruning is implemented. A failed backup leaves the source untouched.
    Stop actors for a cross-file restore point; per-file backups are transactional.
    """
    root = Path(destination)
    root.mkdir(parents=True,exist_ok=False)
    source = sqlite3.connect(Path(mailbox_path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        runtime = json.loads(source.execute('SELECT body FROM runtime WHERE id=1').fetchone()[0])
        for name,path in [('native.sqlite3',mailbox_path),('journal.sqlite3',runtime['journal']),('completed-quotes.sqlite3',runtime['cache'])]:
            src = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
            dst = sqlite3.connect(root/name)
            try: src.backup(dst)
            finally: dst.close();src.close()
        (root/'restore.json').write_text(json.dumps(dict(schema=1,context=runtime['context'],
            note='Restore requires a new executor epoch and independent read-only reconciliation.')),encoding='utf8')
    finally: source.close()
    return dict(retained=True,destination=str(root.resolve()),pruned_events=0)

