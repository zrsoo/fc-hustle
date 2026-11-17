"""Durable admission and delivery. No network call occurs inside a transaction."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from .protocol import parse_response, READS, target, delivery_command, delivery_response, MAINTENANCE
from fc_access.production_v1.contracts import context, fences, stamp, token, integer


def encode(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ControllerStore:
    def __init__(self, path, *, write_authority=False, now=None):
        self.path = Path(path)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.controller_lock = threading.Lock()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.write_authority = write_authority is True
        self.supervision_guard = None
        names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if names and 'c4_meta' not in names:
            self.db.close(); raise ValueError('isolated_controller_database_required')
        self.db.executescript('''
          PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS c4_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_commands(id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL, result TEXT);
          CREATE TABLE IF NOT EXISTS c4_events(seq INTEGER PRIMARY KEY, id TEXT, kind TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_batches(id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_decisions(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_tombstones(action TEXT PRIMARY KEY, command_id TEXT UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS c4_diagnostics(seq INTEGER PRIMARY KEY,
            command_id TEXT NOT NULL REFERENCES c4_commands(id), at TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS c4_diagnostic_no_update BEFORE UPDATE ON c4_diagnostics
            BEGIN SELECT RAISE(ABORT,'immutable_diagnostic'); END;
          CREATE TRIGGER IF NOT EXISTS c4_diagnostic_no_delete BEFORE DELETE ON c4_diagnostics
            BEGIN SELECT RAISE(ABORT,'immutable_diagnostic'); END;
        ''')
        self.host_epoch = secrets.token_hex(16)
        with self.db:
            self.db.execute("UPDATE c4_commands SET state='UNKNOWN' WHERE state IN ('WAITING','CLAIMED')")
        self.peer = None

    def close(self): self.db.close()

    def attach(self, peer):
        from fc_access.production_v1.contracts import fields
        fields(peer, {'context','fences'}); context(peer['context']); fences(peer['fences'])
        if peer['fences']['host_epoch'] != self.host_epoch:
            raise ValueError('wrong_host_epoch')
        with self.lock, self.db:
            row = self.db.execute("SELECT value FROM c4_meta WHERE key='scope'").fetchone()
            if row and json.loads(row[0]) != peer['context']:
                raise ValueError('account_mismatch')
            old = self.db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
            if old:
                previous = json.loads(old[0])
                if previous != peer and peer['fences']['epoch'] <= previous['fences']['epoch']:
                    raise ValueError('higher_owner_epoch_required')
            if self.peer and self.peer != peer:
                self.db.execute("UPDATE c4_commands SET state='UNKNOWN' WHERE state IN ('WAITING','CLAIMED')")
            for key, value in [('scope',peer['context']),('peer',peer)]:
                self.db.execute('INSERT OR REPLACE INTO c4_meta VALUES (?,?)', (key,encode(value)))
            self.peer = deepcopy(peer)

    def check_peer(self, peer):
        if self.peer is None or peer != self.peer: raise ValueError('stale_peer')
        durable=self.db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
        if not durable or json.loads(durable[0])!=peer:raise ValueError('stale_durable_owner')

    def require_supervision(self):
        if self.supervision_guard:self.supervision_guard()

    def running(self):
        self.require_supervision()
        table=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='c4_controller'").fetchone()
        return not table or self.db.execute('SELECT lifecycle FROM c4_controller').fetchone()[0]=='RUNNING'

    def dispatch_guard(self, c):
        with self.lock:
            self.check_peer({k:c[k] for k in ('context','fences')})
            if not self.running():raise ValueError('controller_quiesced')

    def event(self, cid, kind, value):
        self.db.execute('INSERT INTO c4_events(id,kind,body) VALUES (?,?,?)', (cid,kind,encode(value)))

    def diagnostic(self, peer, cid, records):
        from fc_access.production_v1.diagnostics import validate_records
        token(cid);validate_records(records)
        with self.lock,self.db:
            self.check_peer(peer)
            row=self.db.execute('SELECT body,state FROM c4_commands WHERE id=?',(cid,)).fetchone()
            if not row or row[1] not in {'CLAIMED','DONE','UNKNOWN'}:
                raise ValueError('diagnostic_command_required')
            c=json.loads(row[0])
            if any(c[k]!=peer[k] for k in ('context','fences')):raise ValueError('diagnostic_scope_mismatch')
            count=self.db.execute('SELECT coalesce(sum(json_array_length(body)),0) FROM c4_diagnostics WHERE command_id=?',(cid,)).fetchone()[0]
            if count+len(records)>256:raise ValueError('diagnostic_limit')
            if records:self.db.execute('INSERT INTO c4_diagnostics(command_id,at,body) VALUES (?,?,?)',
                (cid,self.now().isoformat(),encode(records)))

    def observation(self, cid, operation=None):
        row = self.db.execute('SELECT body,state,result FROM c4_commands WHERE id=?', (cid,)).fetchone()
        if not row or row[1] != 'DONE' or not row[2]: raise ValueError('independent_observation_required')
        c, v = json.loads(row[0]), json.loads(row[2])
        self.check_peer({'context':c['context'],'fences':c['fences']})
        parse_response(v,c,now=self.now())
        if not v['success'] or c['operation'] not in READS or operation and c['operation'] != operation:
            raise ValueError('independent_observation_required')
        return c,v

    def linked_row(self, read_id, t):
        saved=self.db.execute('SELECT body,state,result FROM c4_commands WHERE id=?',(read_id,)).fetchone()
        if saved and json.loads(saved[0])['schema']==2:
            c=json.loads(saved[0]);v=json.loads(saved[2]) if saved[2] else None
            self.check_peer({k:c[k] for k in ('context','fences')})
            if saved[1]!='DONE' or c['operation'] not in {'search','watched'} or not v or not v['result']['success']:
                raise ValueError('independent_observation_required')
            # Validated at receipt. Initial batch decisions retain the real age,
            # and are bounded by inventory validity and absolute auction expiry.
            delivery_response(v,c,now=stamp(v['freshness']['observed_at']))
            rows=[r for r in v['result']['auctions'] if r and r['trade_id']==t['trade_id'] and r['item']['item_id']==t['item_id']]
            if len(rows)!=1 or rows[0]['item']['definition_id']!=t['definition_id']:raise ValueError('wrong_version')
            return deepcopy(rows[0]),dict(network_at=v['freshness']['network_at'])
        c,v = self.observation(read_id)
        rows = [r for r in v['auctions'] if r['trade_id'] == t['trade_id'] and r['item']['item_id'] == t['item_id']]
        if len(rows) != 1: raise ValueError('missing_target')
        row = deepcopy(rows[0])
        if c['operation'] == 'status_batch':
            links = [l for l in v['links'] if l['target'] == t]
            if len(links) != 1: raise ValueError('full_version_link_required')
            # Full observation may be older than status. Its original timestamp
            # remains evidence provenance, never relabeled as a new full read.
            full = self.db.execute('SELECT body,result FROM c4_commands WHERE id=?', (links[0]['full_read_id'],)).fetchone()
            if not full or not all(full): raise ValueError('full_version_evidence_required')
            fc,fv = map(json.loads, full)
            full_success=fv['success'] if fc['schema']==4 else fv['result']['success']
            full_at=fv['network_at'] if fc['schema']==4 else fv['freshness']['network_at']
            full_rows=fv['auctions'] if fc['schema']==4 else fv['result']['auctions']
            if fc['operation'] not in {'watched','search'} or fc['context'] != c['context'] or fc['fences'] != c['fences'] or not full_success or full_at != links[0]['full_observed_at']:
                raise ValueError('full_version_evidence_required')
            matches = [r for r in full_rows if r and r['trade_id'] == t['trade_id'] and r['item']['item_id'] == t['item_id'] and r['item']['definition_id'] == t['definition_id']]
            if len(matches) != 1: raise ValueError('full_version_conflict')
            row['item']['definition_id'] = t['definition_id']
            row['item']['untradeable'] = matches[0]['item']['untradeable']
        if row['item']['definition_id'] != t['definition_id']: raise ValueError('wrong_version')
        return row,v

    def admit_batch(self, batch_id, *, balance_read_id, inventory_command, inventory_response, threshold=40000):
        """Trusted server API, deliberately absent from all HTTP routes.

        Selection/quotes belong to controller policy. This boundary requires an
        authenticated entry read and complete independently parsed physical inventory.
        """
        from fc_access.production_v1.contracts import parse_response as legacy_parse
        token(batch_id)
        with self.lock, self.db:
            # Entry authority is a single validated batch observation, not a
            # per-bid balance freshness gate. Its real timestamp remains stored.
            policy=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='c4_policy_batches'").fetchone()
            recorded=self.db.execute('SELECT body FROM c4_policy_batches WHERE id=?',(batch_id,)).fetchone() if policy else None
            if recorded:
                b=json.loads(recorded[0])
                saved=self.db.execute('SELECT body,state,result FROM c4_commands WHERE id=?',(balance_read_id,)).fetchone()
                if not saved or saved[1]!='DONE' or not saved[2] or b.get('balance_read_id')!=balance_read_id:raise ValueError('entry_observation_required')
                bc,balance=json.loads(saved[0]),json.loads(saved[2])
                self.check_peer({k:bc[k] for k in ('context','fences')})
                parse_response(balance,bc,now=stamp(balance['observed_at']))
                if bc['operation']!='balance' or not balance['success'] or b['config']['entry_threshold']!=threshold:raise ValueError('entry_observation_required')
                if stamp(balance['network_at'])<stamp(b['started_at']) or any(json.loads(r[0])['balance_read_id']==balance_read_id for r in self.db.execute('SELECT body FROM c4_batches')):
                    raise ValueError('one_entry_observation_per_batch')
            else:
                _,balance = self.observation(balance_read_id, 'balance')
            inventory = legacy_parse(inventory_response,inventory_command,now=self.now(),source=inventory_response['freshness']['source'])
            integer(threshold)
            if not self.write_authority or balance['credits'] <= threshold or inventory_command['operation'] != 'transfer_list' or not inventory['result']['success'] or not inventory['coverage']['complete'] or inventory['context'] != self.peer['context'] or inventory['fences'] != self.peer['fences'] or len(inventory['result']['auctions']) >= 50:
                raise ValueError('batch_admission_denied')
            value = dict(peer=self.peer,balance_read_id=balance_read_id,inventory_command=inventory_command,inventory=inventory)
            self.db.execute('INSERT INTO c4_batches VALUES (?,?)', (batch_id,encode(value)))

    def decide(self, decision_id, *, batch_id, status_read_id, identity, amount, minimum, cap, deadline, kind='initial'):
        token(decision_id); token(batch_id); token(status_read_id); target(identity)
        for n in (amount,minimum,cap): integer(n,1)
        if amount != minimum or amount > cap or kind not in {'initial','rebid'} or stamp(deadline) <= self.now():
            raise ValueError('invalid_decision')
        with self.lock, self.db:
            row,v = self.linked_row(status_read_id,identity)
            batch = self.db.execute('SELECT body FROM c4_batches WHERE id=?',(batch_id,)).fetchone()
            if batch and json.loads(batch[0])['peer'] != self.peer and kind=='rebid':
                # A new document/host may make a new decision only after an
                # independent current-peer full/lite link reestablishes this
                # already-confirmed exact member. Old commands stay fenced out.
                members=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='c4_members'").fetchone()
                member=self.db.execute("SELECT body FROM c4_members WHERE trade_id=? AND batch_id=? AND state='ACTIVE'",(identity['trade_id'],batch_id)).fetchone() if members else None
                prior=json.loads(batch[0])
                if member and json.loads(member[0])['target']==identity and prior['peer']['context']==self.peer['context']:
                    prior['peer']=deepcopy(self.peer)
                    self.db.execute('UPDATE c4_batches SET body=? WHERE id=?',(encode(prior),batch_id))
                    batch=(encode(prior),)
            if not self.write_authority or not batch or json.loads(batch[0])['peer'] != self.peer or row['trade_state'] != 'active' or row['bid_state'] not in {'none','outbid'} or row['item']['untradeable'] is not False or stamp(deadline).timestamp() > stamp(v['network_at']).timestamp()+row['expires'] or row['buy_now_price'] and amount >= row['buy_now_price']:
                raise ValueError('decision_denied')
            count = sum(json.loads(r[0])['kind']=='initial' for r in self.db.execute('SELECT body FROM c4_decisions WHERE batch_id=?',(batch_id,)))
            if kind == 'initial' and count >= 10: raise ValueError('batch_attempt_limit')
            p = dict(target=identity,amount=amount,minimum=minimum,cap=cap,deadline=deadline,status_read_id=status_read_id,batch_id=batch_id,decision_id=decision_id)
            self.db.execute('INSERT INTO c4_decisions VALUES (?,?,?)',(decision_id,batch_id,encode(dict(params=p,kind=kind,peer=self.peer))))

    def authorize(self, c):
        p = c['params']
        decision = self.db.execute('SELECT body FROM c4_decisions WHERE id=?',(p['decision_id'],)).fetchone()
        if not self.write_authority or not decision: raise ValueError('durable_authority_required')
        d = json.loads(decision[0])
        if d['params'] != p or d['peer'] != self.peer or stamp(p['deadline']) <= self.now(): raise ValueError('authority_mismatch')
        self.linked_row(p['status_read_id'],p['target'])
        # Policy-created batches bind dispatch to the immutable selected quote,
        # membership, capacity and inventory generation. Low-level transport
        # contract fixtures (004-02) retain their original admission API.
        policy=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='c4_policy_batches'").fetchone()
        policy_batch=policy and self.db.execute('SELECT 1 FROM c4_policy_batches WHERE id=?',(p['batch_id'],)).fetchone()
        t = p['target']
        action = [c['context']['account'],t['trade_id'],t['item_id'],t['definition_id'],d['kind']]
        if d['kind'] == 'rebid': action += [p['amount'],p['status_read_id']]
        if self.db.execute('SELECT 1 FROM c4_tombstones WHERE action=?',(encode(action),)).fetchone():
            raise ValueError('possibly_sent_no_replay')
        if policy_batch:self.policy_authority(d,c['id'])
        return encode(action)

    def enqueue(self, c, peer):
        c = delivery_command(c)
        with self.lock, self.db:
            self.check_peer(peer)
            if c['context'] != peer['context'] or c['fences'] != peer['fences']: raise ValueError('scope_mismatch')
            if not self.running():raise ValueError('controller_quiesced')
            if c['operation'] == 'bid': self.authorize(c)
            if c['operation'] in MAINTENANCE:
                from .work import authorize
                authorize(self,c)
            self.db.execute('INSERT INTO c4_commands VALUES (?,?,?,NULL)',(c['id'],encode(c),'WAITING'))
            self.event(c['id'],'INTENT',c)

    def claim(self, peer):
        with self.lock, self.db:
            self.check_peer(peer)
            if not self.running():return None
            if self.db.execute("SELECT 1 FROM c4_commands WHERE state='CLAIMED'").fetchone(): return None
            row = self.db.execute("SELECT id,body FROM c4_commands WHERE state='WAITING' ORDER BY rowid LIMIT 1").fetchone()
            if not row: return None
            c = json.loads(row[1])
            if c['operation'] == 'bid' or c['operation'] in MAINTENANCE:
                try:
                    if c['operation']=='bid':action=self.authorize(c)
                    else:
                        from .work import authorize
                        action=authorize(self,c)
                except ValueError:
                    # A stale/duplicate intent cannot become a queue-wide gate.
                    self.db.execute("UPDATE c4_commands SET state='UNKNOWN' WHERE id=?",(c['id'],))
                    self.event(c['id'],'ADMISSION_WITHDRAWN',{})
                    return None
                self.db.execute('INSERT INTO c4_tombstones VALUES (?,?)',(action,c['id']))
                if c['operation'] in MAINTENANCE:
                    self.db.execute("UPDATE c4_work SET dispatched_at=?,state='SUBMITTED' WHERE id=?",(self.now().isoformat(),c['id']))
            self.db.execute("UPDATE c4_commands SET state='CLAIMED' WHERE id=?",(c['id'],))
            self.event(c['id'],'CLAIMED',{})
            return c

    def uncertain(self, cid):
        with self.lock, self.db:
            self.db.execute("UPDATE c4_commands SET state='UNKNOWN' WHERE id=? AND state IN ('WAITING','CLAIMED')",(cid,))
            self.event(cid,'UNCERTAIN',{})

    def finish(self, peer, cid, value):
        with self.lock:
            self.check_peer(peer)
            row = self.db.execute('SELECT body,state FROM c4_commands WHERE id=?',(cid,)).fetchone()
            if not row or row[1] not in {'CLAIMED','UNKNOWN'}: raise ValueError('unclaimed_result')
            c = json.loads(row[0])
            try:parsed = delivery_response(value,c,now=self.now())
            except (ValueError,TypeError,KeyError,OverflowError) as error:
                from .semantic import native_summary
                from fc_access.production_v1.diagnostics import result_summary
                with self.db:self.event(cid,'RESULT_REJECTED',dict(exception_type=type(error).__name__,
                    summary=native_summary(c,value) if c['schema']==4 else result_summary(value,c)))
                raise
            with self.db:
                self.event(cid,'LATE_RESULT' if row[1]=='UNKNOWN' else 'RESULT',parsed)
                if row[1] == 'CLAIMED':
                    success=parsed['success'] if c['schema']==4 else parsed['result']['success']
                    self.db.execute('UPDATE c4_commands SET state=?,result=? WHERE id=?',('DONE' if success else 'UNKNOWN',encode(parsed),cid))

    def policy_authority(self, decision, command_id):
        from .journal import BatchJournal
        j=BatchJournal.__new__(BatchJournal);j.store,j.db=self,self.db
        p=decision['params'];batch=j.batch(p['batch_id']);state=j.state()
        selected=[c for c in j.selected(p['batch_id']) if c['target']==p['target']]
        if state['lifecycle']!='RUNNING' or len(selected)!=1 or p['cap']!=selected[0]['cap']:
            raise ValueError('selected_authority_required')
        if decision['kind']=='initial':
            age=(self.now()-stamp(batch['inventory_at'])).total_seconds()
            if state['phase']!='ACQUIRING' or not j.inventory_valid() or not 0<=age<=batch['config']['inventory_max_age']:
                raise ValueError('inventory_authority_expired')
            if p['amount']!=selected[0]['minimum'] or p['status_read_id']!=selected[0]['read_id']:
                raise ValueError('selected_authority_mismatch')
            if batch['known_pipeline']+len(j.selected(p['batch_id']))>50:
                raise ValueError('pipeline_full')
        elif state['phase']!='MANAGING' or not any(m['target']==p['target'] and m['batch_id']==p['batch_id'] and m['state']=='ACTIVE' for m in j.members()):
            raise ValueError('confirmed_membership_required')
        intent=self.db.execute('SELECT batch_id,state,body FROM c4_attempts WHERE id=?',(command_id,)).fetchone()
        if not intent or intent[0]!=p['batch_id'] or intent[1]!='INTENT' or json.loads(intent[2])['params']!=p:
            raise ValueError('durable_individual_intent_required')

    def result(self, cid):
        with self.lock:
            row = self.db.execute('SELECT result FROM c4_commands WHERE id=?',(cid,)).fetchone()
            return json.loads(row[0]) if row and row[0] else None
