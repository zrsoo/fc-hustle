"""Opt-in finite research transport over the reviewed production extension.

Default production-v1 server remains unchanged and rejects bulk commands.
"""
import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from fc_access.production_v1.server import Handler as ProductionHandler, EXTENSION_ID
from fc_access.production_v1.store import Store as ProductionStore
from fc_access.production_v1.contracts import fields, token, context, fences, integer, stamp
from .contracts import WRITES, PATHS, validate_row, preflight, reconcile

OPERATIONS = {'bulk_inspect', 'bulk_inventory'} | WRITES


def validate_command(c):
    fields(c, {'schema', 'id', 'operation', 'params', 'context', 'fences'})
    if type(c['schema']) is not int or c['schema'] != 2 or c['operation'] not in OPERATIONS:
        raise ValueError('unsupported_bulk_command')
    token(c['id']); context(c['context']); fences(c['fences'])
    if c['operation'] not in WRITES:
        fields(c['params'], set())
    else:
        p = fields(c['params'], {'before_read_id','expected_item_ids','expected_inventory_ids',
            'expected_sold_count','expected_expired_count'} | ({'duration_seconds'} if c['operation']=='bulk_relist_all' else set()))
        token(p['before_read_id'])
        for k in ('expected_item_ids','expected_inventory_ids'):
            if type(p[k]) is not list or not 1<=len(p[k])<=100 or len(set(p[k]))!=len(p[k]):
                raise ValueError('invalid_expected_identities')
            for item_id in p[k]: token(item_id, 'item')
        integer(p['expected_sold_count']); integer(p['expected_expired_count'])
        if c['operation']=='bulk_relist_all':
            integer(p['duration_seconds'],1)
            if p['duration_seconds'] != 3600: raise ValueError('one_hour_required')
    return c


def validate_response(v, c):
    required = {'schema', 'command_id', 'operation', 'context', 'fences', 'observed_at', 'success',
                'error', 'status', 'network', 'sources', 'inventory', 'callback'}
    fields(v, required | ({'names'} if c['operation'] == 'bulk_inspect' and v.get('success') else set()))
    if any(v[k] != c[k] for k in ('schema', 'operation', 'context', 'fences')) or v['command_id'] != c['id']:
        raise ValueError('bulk_correlation_mismatch')
    if type(v['success']) is not bool or not isinstance(v['network'], list):
        raise ValueError('invalid_bulk_result')
    stamp(v['observed_at'])
    if v['status'] is not None: integer(v['status'])
    errors={'production_binding_required','single_native_owner_busy','persona_unverified','duplicate_command','wire_contract_mismatch','duplicate_native_mutation_blocked',
        'service_unavailable','native_timeout_no_retry','native_read_failed','inventory_schema','fresh_authenticated_GET_required',
        'complete_wire_inventory_required','unsafe_identity','fresh_authorized_snapshot_required','eligible_state_changed',
        'ambiguous_mutation_no_retry','native_mutation_failed_no_retry','unsupported_operation','internal_error'}
    if (v['success'] and v['error'] is not None) or (not v['success'] and v['error'] not in errors):
        raise ValueError('unsafe_error')
    if len(v['network'])>4 or type(v['sources']) is not list or len(v['sources'])>32:
        raise ValueError('unbounded_result')
    owners={'services.Item','services.Item.transfersDao','repositories.Item','UTTransferListViewController.prototype',
            'UTTransferSectionListViewModel.prototype','loaded transfer AuctionData'}
    for source in v['sources']:
        fields(source, {'owner','name','source'})
        if source['owner'] not in owners or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,60}',source['name']) or not isinstance(source['source'],str) or len(source['source'])>12000:
            raise ValueError('unsafe_source_inspection')
    if 'names' in v and (type(v['names']) is not list or any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,60}',n) for n in v['names'])):
        raise ValueError('unsafe_method_names')
    # Native output is a positive allowlist, never arbitrary server bodies.
    for n in v['network']:
        fields(n, {'host', 'method', 'path', 'query_empty', 'request_body', 'body_kind', 'status',
                   'session_header_present', 'started_at', 'ended_at', 'response'})
        if n['request_body'] is not None or n['body_kind'] != 'empty':
            raise ValueError('unsafe_request_body')
        if n['method'] not in {'GET','DELETE','PUT','OTHER'} or n['path'] not in {'/ut/game/fc27/tradepile','/ut/game/fc27/trade/sold','/ut/game/fc27/auctionhouse/relist','/unexpected'}:
            raise ValueError('unsafe_wire_projection')
        if n['host']!='unexpected' and not re.fullmatch(r'utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com',n['host']):
            raise ValueError('unsafe_wire_host')
        if type(n['query_empty']) is not bool or type(n['session_header_present']) is not bool:
            raise ValueError('invalid_wire_flags')
        if n['started_at'] is not None: stamp(n['started_at'])
        if n['ended_at'] is not None: stamp(n['ended_at'])
        if n['status'] is not None: integer(n['status'])
        body=n['response']
        if body is not None:
            if type(body) is not dict or set(body)-{'kind','keys','other_key_count','auctions','trade_ids','credits','code','errorCode'} or body.get('kind') not in {'json','empty','unparsed'}:
                raise ValueError('unsafe_EA_response')
            if any(k not in {'auctionInfo','tradeIdList','credits','dynamicObjectivesUpdates','errorCode','code'} for k in body.get('keys',[])):
                raise ValueError('unsafe_response_keys')
            for row in body.get('auctions',[]): validate_row(row)
            for trade in body.get('trade_ids',[]): token(trade,'trade')
            for k in ('other_key_count','credits','code','errorCode'):
                if k in body: integer(body[k])
    inventory=v['inventory']
    if inventory is not None:
        optional={'native_counts','repository_end_of_list'} & set(inventory)
        fields(inventory, {'rows','occupancy','capacity','complete'} | optional)
        if type(inventory['rows']) is not list or len(inventory['rows'])>100 or inventory['occupancy']!=len(inventory['rows']) or inventory['complete'] is not True:
            raise ValueError('incomplete_inventory')
        integer(inventory['capacity'],1)
        for row in inventory['rows']: validate_row(row)
        if 'native_counts' in inventory:
            fields(inventory['native_counts'], {'sold','expired','active'})
            for n in inventory['native_counts'].values(): integer(n)
        if 'repository_end_of_list' in inventory and inventory['repository_end_of_list'] is not True:
            raise ValueError('repository_not_complete')
        if len({r['item_id'] for r in inventory['rows']})!=len(inventory['rows']):
            raise ValueError('duplicate_physical_item')
    if v['callback'] is not None:
        callback=fields(v['callback'], {'success','status','error_code','item_ids'})
        if type(callback['success']) is not bool or type(callback['item_ids']) is not list:
            raise ValueError('unsafe_callback')
        for item_id in callback['item_ids']: token(item_id,'item')
        for k in ('status','error_code'):
            if callback[k] is not None: integer(callback[k])
    if v['success']:
        for n in v['network']:
            if n['status']!=200 or not n['session_header_present'] or not n['query_empty']:
                raise ValueError('successful_result_without_authenticated_wire')
        if c['operation']=='bulk_inspect' and (v['network'] or inventory is not None):
            raise ValueError('inspection_made_network_request')
        if c['operation']=='bulk_inventory' and (inventory is None or len(v['network'])!=1 or
                (v['network'][0]['method'],v['network'][0]['path'])!=('GET','/ut/game/fc27/tradepile')):
            raise ValueError('fresh_bulk_GET_required')
        if c['operation'] in WRITES:
            writes=[n for n in v['network'] if n['method']!='GET']
            if len(writes)!=1 or (writes[0]['method'],writes[0]['path'])!=PATHS[c['operation']] or not v['callback'] or not v['callback']['success']:
                raise ValueError('ambiguous_bulk_mutation')
    return v


class Store(ProductionStore):
    @classmethod
    def open_reconciler(cls,path):
        """Local journal reconciliation only; no host restart or ownership claim."""
        result=cls.__new__(cls)
        result.db=sqlite3.connect(path,isolation_level=None)
        result.now=lambda:datetime.now(timezone.utc)
        return result

    def __init__(self, path, *, authorized_sold=None, authorized_expired=None):
        super().__init__(path)
        with self.tx():
            self.db.execute('CREATE TABLE IF NOT EXISTS research_window(id INTEGER PRIMARY KEY, deadline REAL, reads INTEGER, inspections INTEGER)')
            self.db.execute('INSERT OR IGNORE INTO research_window VALUES(1,?,0,0)', (time.time()+1800,))
            self.db.execute('CREATE TABLE IF NOT EXISTS bulk_authorization(id INTEGER PRIMARY KEY, sold INTEGER, expired INTEGER)')
            existing=self.db.execute('SELECT sold,expired FROM bulk_authorization').fetchone()
            if authorized_sold is None: authorized_sold=existing[0] if existing else 2
            if authorized_expired is None: authorized_expired=existing[1] if existing else 1
            self.db.execute('INSERT OR IGNORE INTO bulk_authorization VALUES(1,?,?)',(authorized_sold,authorized_expired))
            if self.db.execute('SELECT sold,expired FROM bulk_authorization').fetchone() != (authorized_sold,authorized_expired):
                raise ValueError('persisted_authorization_changed')
            self.db.execute('CREATE TABLE IF NOT EXISTS bulk_intents(operation TEXT PRIMARY KEY,command_id TEXT UNIQUE,before_read_id TEXT,expected TEXT,state TEXT)')
            self.db.execute("UPDATE bulk_intents SET state='UNKNOWN' WHERE state!='CONFIRMED'")

    def enqueue(self, c, peer):
        validate_command(c); self.check_peer(peer)
        if c['context'] != peer['context'] or c['fences'] != peer['fences']:
            raise ValueError('wrong_peer')
        with self.tx():
            deadline, reads, inspections = self.db.execute('SELECT deadline,reads,inspections FROM research_window').fetchone()
            if time.time() >= deadline or c['operation']=='bulk_inventory' and reads>=8 or c['operation']=='bulk_inspect' and inspections>=8:
                raise ValueError('research_budget_exhausted')
            if self.db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','DELIVERED')").fetchone():
                raise ValueError('single_native_owner_busy')
            if self.db.execute('SELECT 1 FROM commands WHERE id=?', (c['id'],)).fetchone():
                raise ValueError('duplicate_command')
            if c['operation'] in WRITES:
                if self.db.execute('SELECT 1 FROM bulk_intents WHERE operation=?',(c['operation'],)).fetchone():
                    raise ValueError('bulk_operation_already_consumed_no_retry')
                if c['operation']=='bulk_relist_all' and self.db.execute("SELECT state FROM bulk_intents WHERE operation='bulk_clear_sold'").fetchone()!=('CONFIRMED',):
                    raise ValueError('clear_sold_must_be_independently_confirmed')
                p=c['params']; before=self.result(p['before_read_id'])
                if not before or not before['success'] or before['operation']!='bulk_inventory' or before['context']!=c['context'] or before['fences']!=c['fences']:
                    raise ValueError('fresh_same_context_inventory_required')
                if not 0<=(self.now()-stamp(before['observed_at'])).total_seconds()<=30:
                    raise ValueError('stale_prewrite_inventory')
                sold,expired=self.db.execute('SELECT sold,expired FROM bulk_authorization').fetchone()
                rows=before['inventory']['rows']; target=preflight(c['operation'],rows,authorized_sold=sold,authorized_expired=expired)
                if sorted(p['expected_item_ids'])!=sorted(r['item_id'] for r in target) or sorted(p['expected_inventory_ids'])!=sorted(r['item_id'] for r in rows):
                    raise ValueError('unexpected_target_identity')
                from .contracts import groups
                g=groups(rows)
                if (p['expected_sold_count'],p['expected_expired_count'])!=(len(g['sold']),len(g['expired'])):
                    raise ValueError('unexpected_eligible_counts')
                self.db.execute('INSERT INTO bulk_intents VALUES(?,?,?,?,?)',(c['operation'],c['id'],p['before_read_id'],json.dumps(p,sort_keys=True),'INTENT_DURABLE'))
            else:
                column = 'reads' if c['operation'] == 'bulk_inventory' else 'inspections'
                self.db.execute(f'UPDATE research_window SET {column}={column}+1 WHERE id=1')
            self.db.execute('INSERT INTO commands VALUES(?,?,?,NULL)', (c['id'], json.dumps(c, sort_keys=True), 'QUEUED'))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)', (c['id'], 'RESERVED_BEFORE_DELIVERY'))

    def authorize_revision(self, sold, expired):
        """Local operator records an explicit new user instruction, before writes.

        Does not renew the window, alter counters or reset any consumed intent.
        Never exposed as a browser/HTTP command.
        """
        integer(sold,1); integer(expired,1)
        with self.tx():
            if self.db.execute('SELECT 1 FROM bulk_intents').fetchone():
                raise ValueError('authorization_revision_after_intent_forbidden')
            previous=self.db.execute('SELECT sold,expired FROM bulk_authorization').fetchone()
            if previous==(sold,expired): return
            self.db.execute('UPDATE bulk_authorization SET sold=?,expired=? WHERE id=1',(sold,expired))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)',('0'*32,json.dumps(dict(
                event='EXPLICIT_USER_AUTHORIZATION_REVISION',previous=previous,authorized=[sold,expired],
                at=self.now().isoformat(),budgets_unchanged=True),sort_keys=True)))

    def select_account_context(self, value):
        """Explicit operator selection after the user chooses an EA login.

        Preserve prior evidence/counters, fence its mappings, and forbid switching
        after any mutation intent. No browser API can call this method.
        """
        fields(value,{'context','owner','epoch'}); context(value['context']); token(value['owner']); integer(value['epoch'],1)
        with self.tx():
            old=self.owner()
            if self.db.execute('SELECT 1 FROM bulk_intents').fetchone() or old and value['epoch']<=old['epoch']:
                raise ValueError('account_selection_after_intent_or_stale_epoch')
            self.db.execute('DELETE FROM owner')
            self.db.execute('INSERT INTO owner VALUES(?,?,?)',(json.dumps(value['context'],sort_keys=True),value['owner'],value['epoch']))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)',('0'*32,json.dumps(dict(
                event='USER_DESIGNATED_ACCOUNT_SELECTED',previous=old,selected=value,budgets_unchanged=True,
                prior_inventory_not_authority_for_new_context=True,at=self.now().isoformat()),sort_keys=True)))

    def finish(self, peer, cid, value):
        self.check_peer(peer); token(cid)
        with self.tx():
            row = self.db.execute('SELECT body,state FROM commands WHERE id=?', (cid,)).fetchone()
            if not row or row[1] != 'DELIVERED':
                raise ValueError('unknown_or_duplicate_result')
            c = json.loads(row[0]); validate_response(value, c)
            if c['context'] != peer['context'] or c['fences'] != peer['fences']:
                raise ValueError('wrong_peer')
            self.db.execute('UPDATE commands SET state=?,result=? WHERE id=?',
                ('ACKNOWLEDGED' if value['success'] else 'UNKNOWN', json.dumps(value, sort_keys=True), cid))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)', (cid, 'RESPONSE_RECORDED'))
            if c['operation'] in WRITES:
                self.db.execute('UPDATE bulk_intents SET state=? WHERE command_id=?',
                    ('ACKNOWLEDGED_UNRECONCILED' if value['success'] else 'UNKNOWN',cid))

    def reconcile(self, operation, after_read_id):
        with self.tx():
            intent=self.db.execute('SELECT command_id,before_read_id,state FROM bulk_intents WHERE operation=?',(operation,)).fetchone()
            if not intent or intent[2]=='CONFIRMED': raise ValueError('no_unreconciled_intent')
            write=self.result(intent[0]); before=self.result(intent[1]); after=self.result(after_read_id)
            if not write or not before or not after or not after['success'] or after['operation']!='bulk_inventory' or after['context']!=write['context'] or after['fences']!=write['fences']:
                raise ValueError('independent_readback_required')
            wire=next((n for n in write['network'] if n['method']!='GET'),None)
            if wire is None or wire['status']!=200: raise ValueError('no_successful_wire_mutation')
            read=after['network'][0]
            result=reconcile(operation,before['inventory']['rows'],after['inventory']['rows'],
                mutation_started=wire['started_at'],mutation_ended=wire['ended_at'],read_started=read['started_at'],read_ended=read['ended_at'])
            self.db.execute("UPDATE bulk_intents SET state='CONFIRMED' WHERE operation=?",(operation,))
            self.db.execute('INSERT INTO events(command_id,event) VALUES(?,?)',(intent[0],json.dumps(dict(event='INDEPENDENT_READBACK_CONFIRMED',read_id=after_read_id,result=result),sort_keys=True)))
            return result


class Handler(ProductionHandler):
    def do_GET(self):
        if not self.origin() or self.path != '/health':
            return super().do_GET()
        s = self.server
        with s.condition:
            self.send(200, dict(service='fc-production-v1', schema=2, profile='finite-bulk-transfer-research',
                host_epoch=s.store.host_epoch, owner=s.store.owner(), peer=s.peer,
                attached=s.peer is not None and time.monotonic()-s.attached_at < 45,
                mutations_enabled=True, bid_enabled=False,bulk_only_once_each=True,
                authorization=dict(zip(('sold','expired'),s.store.db.execute('SELECT sold,expired FROM bulk_authorization').fetchone())),
                consumed_bulk_operations=[r[0] for r in s.store.db.execute('SELECT operation FROM bulk_intents')],
                budget=dict(zip(('deadline','reads','inspections'),s.store.db.execute('SELECT deadline,reads,inspections FROM research_window').fetchone()))))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, database, port=8784, *, authorization_revision=None,account_selection=None):
        self.store = Store(database)
        if account_selection is not None:self.store.select_account_context(account_selection)
        if authorization_revision is not None:
            self.store.authorize_revision(*authorization_revision)
        self.extension_origin = 'chrome-extension://'+EXTENSION_ID
        self.condition = threading.Condition(); self.peer = None; self.attached_at = 0; self.polling = False
        self.wait_seconds, self.poll_seconds = 24, 18
        super().__init__(('127.0.0.1', port), Handler)
    def handle_error(self, *args):
        pass


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--database', required=True)
    p.add_argument('--revise-sold-count',type=int); p.add_argument('--revise-expired-count',type=int)
    p.add_argument('--select-account-context',type=Path)
    a = p.parse_args(); Path(a.database).parent.mkdir(parents=True, exist_ok=True)
    if (a.revise_sold_count is None)!=(a.revise_expired_count is None):p.error('both explicit authorization counts required')
    revision=(a.revise_sold_count,a.revise_expired_count) if a.revise_sold_count is not None else None
    selection=json.loads(a.select_account_context.read_text(encoding='utf8')) if a.select_account_context else None
    Server(a.database,authorization_revision=revision,account_selection=selection).serve_forever()
