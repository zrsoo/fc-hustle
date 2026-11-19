"""Durable phase/batch policy, separate from native command delivery.

All methods commit before returning. Callers never hold a transaction across I/O.
Only public identity projections and enumerated diagnostics are stored here.
"""
from copy import deepcopy
import json
from .store import encode


class BatchJournal:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self._migrate_phase_check()
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS c4_controller(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            phase TEXT NOT NULL CHECK(phase IN ('ACQUIRING','MANAGING','MAINTENANCE')),
            lifecycle TEXT NOT NULL, reason TEXT, batch_id TEXT);
          INSERT OR IGNORE INTO c4_controller VALUES(1,'ACQUIRING','STOPPED',NULL,NULL);
          CREATE TABLE IF NOT EXISTS c4_policy_batches(id TEXT PRIMARY KEY, state TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_candidates(batch_id TEXT NOT NULL, trade_id TEXT NOT NULL,
            body TEXT NOT NULL, PRIMARY KEY(batch_id,trade_id));
          CREATE TABLE IF NOT EXISTS c4_attempts(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
            action TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL, result TEXT);
          CREATE TABLE IF NOT EXISTS c4_members(trade_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
            state TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_metrics(seq INTEGER PRIMARY KEY, batch_id TEXT, kind TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_inventory(singleton INTEGER PRIMARY KEY CHECK(singleton=1), valid INTEGER NOT NULL);
          INSERT OR IGNORE INTO c4_inventory VALUES(1,0);
          CREATE TRIGGER IF NOT EXISTS c4_candidate_immutable BEFORE UPDATE ON c4_candidates
            BEGIN SELECT RAISE(ABORT,'immutable_candidate'); END;
          CREATE TRIGGER IF NOT EXISTS c4_attempt_immutable BEFORE UPDATE OF id,batch_id,action,kind,body ON c4_attempts
            BEGIN SELECT RAISE(ABORT,'immutable_intent'); END;
        ''')

    def _migrate_phase_check(self):
        """Rebuild the singleton once so its CHECK admits MAINTENANCE; row kept."""
        row=self.db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='c4_controller'").fetchone()
        if not row or 'MAINTENANCE' in row[0]:return
        with self.store.lock, self.db:
            self.db.execute("""CREATE TABLE c4_controller_v2(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                phase TEXT NOT NULL CHECK(phase IN ('ACQUIRING','MANAGING','MAINTENANCE')),
                lifecycle TEXT NOT NULL, reason TEXT, batch_id TEXT)""")
            self.db.execute('INSERT INTO c4_controller_v2 SELECT singleton,phase,lifecycle,reason,batch_id FROM c4_controller')
            self.db.execute('DROP TABLE c4_controller')
            self.db.execute('ALTER TABLE c4_controller_v2 RENAME TO c4_controller')

    def state(self):
        row = self.db.execute('SELECT phase,lifecycle,reason,batch_id FROM c4_controller').fetchone()
        return dict(zip(('phase','lifecycle','reason','batch_id'), row))

    def checkpoint(self, *, phase=None, lifecycle=None, reason=None, batch_id=None):
        value = self.state()
        value.update({k:v for k,v in dict(phase=phase,lifecycle=lifecycle,batch_id=batch_id).items() if v is not None})
        value['reason'] = reason
        with self.store.lock, self.db:
            self.db.execute('UPDATE c4_controller SET phase=?,lifecycle=?,reason=?,batch_id=? WHERE singleton=1',
                            tuple(value[k] for k in ('phase','lifecycle','reason','batch_id')))
            self.store.event(batch_id,'CHECKPOINT',value)

    def begin(self, bid, config, at):
        with self.store.lock, self.db:
            self.db.execute('INSERT INTO c4_policy_batches VALUES (?,?,?)',
                            (bid,'ACQUIRING',encode(dict(config=config,started_at=at))))
            self.db.execute('UPDATE c4_controller SET batch_id=? WHERE singleton=1',(bid,))

    def update_batch(self, bid, **values):
        with self.store.lock, self.db:
            state, body = self.db.execute('SELECT state,body FROM c4_policy_batches WHERE id=?',(bid,)).fetchone()
            body=json.loads(body); body.update(values)
            self.db.execute('UPDATE c4_policy_batches SET state=?,body=? WHERE id=?',
                            (values.get('state',state),encode(body),bid))

    def batch(self, bid):
        row=self.db.execute('SELECT body FROM c4_policy_batches WHERE id=?',(bid,)).fetchone()
        return json.loads(row[0]) if row else None

    def select(self, bid, candidates):
        if len(candidates)>10: raise ValueError('batch_attempt_limit')
        with self.store.lock, self.db:
            for c in candidates:
                self.db.execute('INSERT INTO c4_candidates VALUES (?,?,?)',(bid,c['target']['trade_id'],encode(c)))

    def selected(self, bid):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM c4_candidates WHERE batch_id=? ORDER BY rowid',(bid,))]

    def members(self):
        return [dict(json.loads(body),state=state,batch_id=bid) for bid,state,body in self.db.execute(
            "SELECT batch_id,state,body FROM c4_members WHERE state IN ('ACTIVE','PENDING_WIN')")]

    def member(self, bid, candidate, *, state='ACTIVE', proof=None):
        trade=candidate['target']['trade_id']
        with self.store.lock, self.db:
            old=self.db.execute('SELECT batch_id FROM c4_members WHERE trade_id=?',(trade,)).fetchone()
            count=self.db.execute("SELECT count(*) FROM c4_members WHERE batch_id=?",(bid,)).fetchone()[0]
            if old and old[0]!=bid or not old and count>=10:raise ValueError('membership_limit')
            body=deepcopy(candidate);body['proof']=proof
            self.db.execute('INSERT OR REPLACE INTO c4_members VALUES (?,?,?,?)',(trade,bid,state,encode(body)))

    def settle(self, trade, state, proof):
        if state not in {'LOST','WON_ACCOUNTED'}:raise ValueError('terminal_proof_required')
        with self.store.lock, self.db:
            self.db.execute('UPDATE c4_members SET state=? WHERE trade_id=?',(state,trade))
            self.store.event(trade,state,proof)

    def action(self, target, kind, *, amount=None, read_id=None):
        value=[self.store.peer['context']['account'], target['trade_id'],target['item_id'],target['definition_id'],kind]
        if kind=='rebid':value.extend([amount,read_id])
        return encode(value)

    def attempted(self, target, kind='initial', **kwargs):
        return self.db.execute('SELECT 1 FROM c4_attempts WHERE action=?',(self.action(target,kind,**kwargs),)).fetchone() is not None

    def intend(self, cid, bid, candidate, kind, params):
        action=self.action(candidate['target'],kind,amount=params['amount'],read_id=params['status_read_id'])
        with self.store.lock, self.db:
            if kind=='initial' and self.db.execute("SELECT count(*) FROM c4_attempts WHERE batch_id=? AND kind='initial'",(bid,)).fetchone()[0]>=10:
                raise ValueError('batch_attempt_limit')
            self.db.execute('INSERT INTO c4_attempts VALUES (?,?,?,?,?,?,NULL)',
                (cid,bid,action,kind,'INTENT',encode(dict(candidate=candidate,params=params))))

    def outcome(self, cid, result):
        with self.store.lock, self.db:
            row=self.db.execute('SELECT state FROM c4_attempts WHERE id=?',(cid,)).fetchone()
            if not row:raise ValueError('unknown_intent')
            if row[0]!='INTENT':
                self.store.event(cid,'IGNORED_LATE_POLICY_RESULT',result);return
            self.db.execute('UPDATE c4_attempts SET state=?,result=? WHERE id=?',(result['outcome'],encode(result),cid))

    def abandon(self, cid):
        with self.store.lock,self.db:
            self.db.execute("UPDATE c4_attempts SET state='UNKNOWN',result=? WHERE id=? AND state='ACKNOWLEDGED'",
                (encode(dict(outcome='UNKNOWN',reason='PARTICIPATION_UNCONFIRMED')),cid))

    def metric(self, bid, kind, **values):
        with self.store.lock, self.db:
            self.db.execute('INSERT INTO c4_metrics(batch_id,kind,body) VALUES (?,?,?)',(bid,kind,encode(values)))

    def inventory_valid(self):
        return bool(self.db.execute('SELECT valid FROM c4_inventory WHERE singleton=1').fetchone()[0])

    def invalidate_inventory(self):
        with self.store.lock, self.db:self.db.execute('UPDATE c4_inventory SET valid=0 WHERE singleton=1')

    def recover(self):
        with self.store.lock, self.db:
            self.db.execute("UPDATE c4_attempts SET state='UNKNOWN',result=? WHERE state='INTENT'",
                            (encode(dict(outcome='UNKNOWN',reason='RESTART_ABANDONED')),))
            self.db.execute("""UPDATE c4_attempts SET state='UNKNOWN',result=? WHERE state='ACKNOWLEDGED'
                AND NOT EXISTS(SELECT 1 FROM c4_members m WHERE m.trade_id=json_extract(c4_attempts.body,'$.candidate.target.trade_id'))""",
                (encode(dict(outcome='UNKNOWN',reason='RESTART_PARTICIPATION_UNCONFIRMED')),))
            self.db.execute("UPDATE c4_policy_batches SET state='ABANDONED' WHERE state='ACQUIRING'")
            self.db.execute('UPDATE c4_inventory SET valid=0 WHERE singleton=1')
        self.checkpoint(phase='MANAGING' if self.members() else 'ACQUIRING',reason=self.state()['reason'])

    def uncertainty(self):
        rows=self.db.execute("SELECT id,batch_id,kind,body,result FROM c4_attempts WHERE state='UNKNOWN'")
        return dict(global_ten_participation_guarantee=False,potentially_untracked_effects=[
            dict(command_id=r[0],batch_id=r[1],kind=r[2],intent=json.loads(r[3]),result=json.loads(r[4]) if r[4] else None) for r in rows])
