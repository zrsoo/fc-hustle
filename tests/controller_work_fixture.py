"""Offline world: no sockets, production paths, browser, or session owners.

The separate world database is a synthetic server side-effect ledger and survives
abrupt worker termination independently of the controller's SQLite transactions.
"""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import uuid

from controller_policy_fixture import SyntheticEA, Harness
from fc_access.production_v1.contracts import ROUTES


class WorkEA(SyntheticEA):
    def __init__(self,store,clock,count):
        if not Path(store.path).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):raise ValueError('fixture_temp_root_required')
        super().__init__(store,clock,count)
        self.fences.update(owner=uuid.uuid4().hex,document=uuid.uuid4().hex)
        old=store.db.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
        if old:self.fences['epoch']=json.loads(old[0])['fences']['epoch']+1
        self.context.update(account='f'*32,persona='e'*32,identity_namespace='d'*32)
        self.effect=True;self.lose_reply=False;self.lose_bid_reply=False;self.bad_after=None;self.after_claim=None;self.after_effect=None
        self.world=sqlite3.connect(store.path.with_name('synthetic-world.sqlite'))
        self.world.executescript('CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY,body TEXT); CREATE TABLE IF NOT EXISTS effects(seq INTEGER PRIMARY KEY,command_id TEXT UNIQUE,operation TEXT);')
        self.world.execute('CREATE TABLE IF NOT EXISTS bid_effects(command_id TEXT PRIMARY KEY,trade_id TEXT,amount INTEGER)')
        old=self.world.execute('SELECT body FROM snapshot WHERE id=1').fetchone()
        if old:
            state=json.loads(old[0]);self.inventory=state['inventory'];self.owned=state['owned'];self.rows=state['rows'];clock.value=state['clock']
        self.save()

    def controller(self,c,at):
        v=super().controller(c,at)
        if c['operation']=='bid':
            with self.world:self.world.execute('INSERT INTO bid_effects VALUES(?,?,?)',(c['id'],c['params']['target']['trade_id'],c['params']['amount']))
            self.save()
            if self.after_effect:self.after_effect(c)
            if self.lose_bid_reply:raise TimeoutError('CANARY lost bid response')
        return v

    def attach(self,context,owner,epoch):
        # Harness uses epoch=1 for the first scene only; the returned fence is
        # always this isolated world's new current peer on process restoration.
        assert context==self.context and owner==self.fences['owner']
        self.store.attach(dict(context=context,fences=self.fences));return deepcopy(self.fences)

    def save(self):
        with self.world:self.world.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)',(json.dumps(dict(inventory=self.inventory,owned=self.owned,rows=self.rows,clock=self.clock.value)),))

    def shared(self,c,at):
        op,p=c['operation'],c['params']
        if op in {'move','list','clear_sold','relist_all'}:
            # An independent reader must see the committed claim and tombstone.
            with closing(sqlite3.connect(self.store.path)) as db,db:
                assert db.execute('SELECT state FROM c4_work WHERE id=?',(c['id'],)).fetchone()[0]=='SUBMITTED'
                assert db.execute('SELECT command_id FROM c4_tombstones WHERE command_id=?',(c['id'],)).fetchone()
                db.execute("INSERT INTO c4_events(kind,body) VALUES('NETWORK_UNLOCKED','{}')")
            if self.after_claim:self.after_claim(c)
            with self.world:self.world.execute('INSERT INTO effects(command_id,operation) VALUES(?,?)',(c['id'],op))
            if self.effect:
                if op=='move':
                    item=next(i for i in self.owned if i['item_id']==p['item_id'])
                    row=deepcopy(next(r for r in self.rows if r['item']['item_id']==p['item_id']))
                    row.update(item=deepcopy(item),trade_id='trade:'+'0'*24,current_bid=0,bid_state='none',trade_state='inactive',expires=-1,native_is_won=False)
                    self.inventory.append(row);self.owned=[i for i in self.owned if i['item_id']!=p['item_id']]
                elif op=='list':
                    row=next(r for r in self.inventory if r['item']['item_id']==p['item_id'])
                    row.update(trade_id='trade:'+uuid.uuid4().hex[:24],trade_state='active',starting_bid=p['starting_bid'],buy_now_price=p['buy_now_price'],expires=3600,bid_state='none')
                elif op=='clear_sold':self.inventory=[r for r in self.inventory if r['item']['item_id'] not in p['expected_item_ids']]
                else:
                    for r in self.inventory:
                        if r['item']['item_id'] in p['expected_item_ids']:r.update(trade_id='trade:'+uuid.uuid4().hex[:24],trade_state='active',expires=3600)
            if self.bad_after:self.bad_after(c)
            self.save()
            if self.after_effect:self.after_effect(c)
            if self.lose_reply:raise TimeoutError('CANARY credential exception must never persist')
            v=super().shared(c,at)
            method,path=ROUTES[op]
            v['result']['network']=[dict(method=method,path=path,host='utas.test.ea.com',query={},status=200,session_header_present=True)]
            return v
        v=super().shared(c,at)
        if op=='transfer_list':
            v['coverage']['bulk']=[dict(item_id=r['item']['item_id'],trade_owner=True,sold=r['trade_state']=='closed',expired=r['trade_state']=='expired',active=r['trade_state']=='active') for r in self.inventory]
        return v


def harness(path,count=2):
    h=Harness(path,count,ea_factory=WorkEA)
    h.ids=lambda:uuid.uuid4().hex
    h.controller.ids=h.controller.prices.command_ids=h.controller.pricing.command_ids=h.ids
    # Reconnect deliberately loses every full native mapping. An ordinary new
    # watched read is the only way to regain an existing confirmed target.
    h.ea.manual=deepcopy(h.ea.rows)
    return h


def won(h):
    h.controller.step()
    h.ea.rows[0].update(trade_state='closed',bid_state='highest',native_is_won=True,expires=0)
    h.ea.owned=[dict(h.ea.rows[0]['item'],last_sale_price=h.ea.rows[0]['current_bid'])]
    for row in h.ea.rows[1:]:row.update(trade_state='closed',bid_state='outbid',native_is_won=False,expires=0)
    h.ea.manual=deepcopy(h.ea.rows);h.ea.save()


def effects(h):return list(h.ea.world.execute('SELECT operation,count(*) FROM effects GROUP BY operation ORDER BY operation'))
