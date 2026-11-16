"""Controller-owned resale and bulk work; persisted submissions never become work.

Native commands, classification, pricing and effect assessors are shared with
production_v1. Legacy global unresolved gates and its actor loops are not used.
"""
from copy import deepcopy
from datetime import timedelta
import json

from .store import encode
from .protocol import MAINTENANCE, delivery_response
from fc_access.production_v1.contracts import stamp
from fc_access.production_v1.bulk import parameters, classify, assess_effect as bulk_effect
from fc_access.production_v1.resale import assess_effect as resale_effect
from fc_access.production_v1.prices import CardKey


def shared_read(store, cid, op):
    saved=store.db.execute('SELECT body,state,result FROM c4_commands WHERE id=?',(cid,)).fetchone()
    if not saved or saved[1]!='DONE' or not saved[2]:raise ValueError('independent_read_required')
    c,v=json.loads(saved[0]),json.loads(saved[2])
    store.check_peer({k:c[k] for k in ('context','fences')})
    delivery_response(v,c,now=store.now())
    if c['schema']!=2 or c['operation']!=op or not v['result']['success']:raise ValueError('independent_read_required')
    return v


def action(c, before):
    op,p=c['operation'],c['params']
    if op in {'move','list'}:key=[p['trade_id'],p['item_id'],p['definition_id']]
    else:
        targets=set(p['expected_item_ids'])
        key=sorted((r['trade_id'],r['item']['item_id']) for r in before['result']['auctions'] if r['item']['item_id'] in targets)
    return encode([c['context']['account'],op,key])


def validate(store, c):
    """Trusted intent creation and dispatch both recheck independent evidence."""
    op,p=c['operation'],c['params']
    if not store.write_authority or op not in MAINTENANCE or not store.running():raise ValueError('work_authority_required')
    store.check_peer({k:c[k] for k in ('context','fences')})
    if op in {'clear_sold','relist_all'}:
        before=shared_read(store,p['before_read_id'],'transfer_list')
        if parameters(before,op)!=p:raise ValueError('bulk_membership_mismatch')
        targets=set(p['expected_item_ids'])
        generations={(r['item']['item_id'],r['trade_id']) for r in before['result']['auctions'] if r['item']['item_id'] in targets}
        for cid,body,prior in store.db.execute('SELECT id,body,before_read FROM c4_work WHERE id!=?',(c['id'],)):
            previous,observation=json.loads(body),json.loads(prior)
            if previous['operation']!=op:continue
            used=set(previous['params']['expected_item_ids'])
            if generations & {(r['item']['item_id'],r['trade_id']) for r in observation['result']['auctions'] if r['item']['item_id'] in used}:
                raise ValueError('consumed_bulk_generation')
        return before
    row=store.db.execute("SELECT body FROM c4_members WHERE trade_id=? AND state='PENDING_WIN'",(p['trade_id'],)).fetchone()
    if not row:raise ValueError('known_win_required')
    member=json.loads(row[0]);t=member['target']
    if t!={k:p[k] for k in ('trade_id','item_id','definition_id')} or p['buy_now_price']!=member['resale_price']:
        raise ValueError('stored_policy_required')
    # Re-establish terminal physical ownership and cost at dispatch. There is no
    # inference from HTTP success, a balance delta or a market comparable.
    win=shared_read(store,p['win_read_id'],'watched')
    wins=[r for r in win['result']['auctions'] if r['trade_id']==t['trade_id'] and r['item']['item_id']==t['item_id'] and r['item']['definition_id']==t['definition_id']]
    bids=[json.loads(r[0]) for r in store.db.execute('SELECT a.body FROM c4_attempts a JOIN c4_tombstones t ON t.command_id=a.id')]
    if len(wins)!=1 or wins[0]['trade_state']!='closed' or wins[0]['bid_state']!='highest' or wins[0]['native_is_won'] is not True or wins[0]['expires']>0 or wins[0]['current_bid']!=p['paid'] or not any(b['candidate']['target']==t and b['params']['amount']==p['paid'] for b in bids):
        raise ValueError('paid_terminal_win_required')
    before=shared_read(store,p['owned_read_id'],'owned_item' if op=='move' else 'transfer_list')
    items=before['result']['items'] if op=='move' else [r['item'] for r in before['result']['auctions'] if r['trade_state']=='inactive' and r['current_bid']==0]
    matches=[i for i in items if i['item_id']==t['item_id'] and i['definition_id']==t['definition_id'] and i['untradeable'] is False and i['last_sale_price']==p['paid']]
    if len(matches)!=1 or op=='list' and not before['coverage']['complete']:raise ValueError('physical_paid_ownership_required')
    if op=='move':
        inv=store.db.execute("SELECT id FROM c4_commands WHERE state='DONE' AND json_extract(body,'$.operation')='transfer_list' ORDER BY rowid DESC LIMIT 1").fetchone()
        pile=shared_read(store,inv[0],'transfer_list') if inv else None
        if not pile or not pile['coverage']['complete'] or len(pile['result']['auctions'])>=50 or any(r['item']['item_id']==p['item_id'] for r in pile['result']['auctions']):raise ValueError('move_capacity_required')
    caps=shared_read(store,p['caps_read_id'],'caps')['result']['caps']
    if caps['definition_id']!=t['definition_id'] or not caps['minimum']<=p['starting_bid']<p['buy_now_price']<=caps['maximum'] or p['duration']!=3600:raise ValueError('native_caps_required')
    probes={}
    for cid, in store.db.execute("SELECT id FROM c4_commands WHERE state='DONE' AND json_extract(body,'$.operation')='price_helpers'"):
        try:v=shared_read(store,cid,'price_helpers')
        except ValueError:continue
        probes.update(((r['direction'],r['value']),r['price']) for r in v['result']['probes'])
    start,price=p['starting_bid'],p['buy_now_price']
    if probes.get(('below',price))!=start or probes.get(('above',start))!=price or probes.get(('above',probes.get(('below',start))))!=start:
        raise ValueError('native_tick_required')
    return before


def authorize(store,c):
    row=store.db.execute('SELECT body,action,state FROM c4_work WHERE id=?',(c['id'],)).fetchone()
    if not row or json.loads(row[0])!=c or row[2]!='INTENT':raise ValueError('durable_work_intent_required')
    before=validate(store,c)
    if row[1]!=action(c,before) or store.db.execute('SELECT 1 FROM c4_tombstones WHERE action=?',(row[1],)).fetchone():raise ValueError('possibly_sent_no_replay')
    return row[1]


class Work:
    def __init__(self,controller):
        self.c=controller;self.s=controller.store
        self.s.db.executescript('''
          CREATE TABLE IF NOT EXISTS c4_work(id TEXT PRIMARY KEY,action TEXT UNIQUE NOT NULL,
            body TEXT NOT NULL,before_read TEXT NOT NULL,state TEXT NOT NULL,at TEXT NOT NULL,
            dispatched_at TEXT,completed_at TEXT,proof TEXT);
          CREATE TABLE IF NOT EXISTS c4_maintenance(singleton INTEGER PRIMARY KEY CHECK(singleton=1),next_due TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS c4_work_immutable BEFORE UPDATE OF id,action,body,before_read,at ON c4_work
            BEGIN SELECT RAISE(ABORT,'immutable_work_intent'); END;
        ''')
        with self.s.lock,self.s.db:
            self.s.db.execute('INSERT OR IGNORE INTO c4_maintenance VALUES(1,?)',((self.s.now()+timedelta(seconds=3660)).isoformat(),))
            self.s.db.execute("UPDATE c4_work SET state='UNKNOWN' WHERE state IN ('INTENT','SUBMITTED','ACKNOWLEDGED')")
        self.inventory=None

    def checkpoint(self, stage):
        """Process-fault injection boundary; no runtime work."""

    def status(self):
        return dict(next_relist_due=self.s.db.execute('SELECT next_due FROM c4_maintenance').fetchone()[0],
            operations=[dict(command_id=cid,operation=json.loads(body)['operation'],state=state,
                intent=json.loads(body),proof=json.loads(proof) if proof else None)
                for cid,body,state,proof in self.s.db.execute('SELECT id,body,state,proof FROM c4_work')])

    def recover_bulk(self):
        # Submitted records supply read-only recovery inputs, never replay work.
        # Bound recovery to one operation; an unresolved effect is no write gate.
        row=self.s.db.execute("""SELECT id FROM c4_work WHERE state!='CONFIRMED'
            AND dispatched_at IS NOT NULL AND json_extract(body,'$.operation') IN ('clear_sold','relist_all')
            ORDER BY rowid LIMIT 1""").fetchone()
        if row:self.reconcile(row[0])

    def pile(self):
        v=self.c._read('transfer_list')
        if not v['coverage']['complete']:raise ValueError('complete_inventory_required')
        self.inventory=v
        return v

    def dispatch(self,op,params):
        c=self.c.native.envelope(self.c.ids(),op,params);s=self.s
        self.checkpoint('before_intent')
        with s.lock,s.db:
            before=validate(s,c);key=action(c,before)
            s.db.execute("INSERT INTO c4_work(id,action,body,before_read,state,at) VALUES(?,?,?,?,'INTENT',?)",
                (c['id'],key,encode(c),encode(before),s.now().isoformat()))
        self.checkpoint('intent')
        try:
            # The HTTP/native claim consumes a tombstone before dispatch. No
            # transaction or account data lock spans this synchronous I/O.
            v=delivery_response(self.c.adapter.executor.execute(c),c,now=s.now())
            outcome='ACKNOWLEDGED' if v['result']['success'] else 'UNKNOWN'
        except Exception:outcome='UNKNOWN'
        self.checkpoint('reply')
        with s.lock,s.db:
            s.db.execute('UPDATE c4_work SET state=?,completed_at=? WHERE id=?',(outcome,s.now().isoformat(),c['id']))
        self.c.journal.invalidate_inventory()
        self.reconcile(c['id'])
        return c['id']

    def reconcile(self,cid):
        s=self.s
        row=s.db.execute('SELECT body,before_read,state,at,dispatched_at,completed_at,proof FROM c4_work WHERE id=?',(cid,)).fetchone()
        if not row or row[2]=='CONFIRMED':return bool(row)
        c,before=json.loads(row[0]),json.loads(row[1]);op,p=c['operation'],json.loads(row[0])['params']
        if c['context']!=self.c.adapter.context:raise ValueError('wrong_recovery_context')
        if not row[4]:return False # Intent-only progress is never submitted work.
        try:
            after=self.pile();at=stamp(after['freshness']['network_at'])
            if after['command_id'] in {cid,before['command_id']} or at<stamp(row[5] or row[4]):return False
            if op in {'clear_sold','relist_all'}:
                classify(after)
                prior=json.loads(row[6]) if row[6] else {}
                proven,incompatible=bulk_effect(c,before,after,dispatched=stamp(row[4]),completed=stamp(row[5] or row[4]),incompatible=prior.get('incompatible',False))
            else:
                owned=self.c._read('unassigned') if op=='move' else None
                if owned and stamp(owned['freshness']['network_at'])<stamp(row[4]):return False
                prior=next((r['trade_id'] for r in before['result']['auctions'] or [] if r['item']['item_id']==p['item_id']),p['trade_id'])
                proven,_=resale_effect(c,after,owned,at=stamp(row[3]),claimed=stamp(row[4]),completed=stamp(row[5]) if row[5] else None,before=prior)
                incompatible=False
            self.checkpoint('readback')
            with s.lock,s.db:
                s.db.execute('UPDATE c4_work SET state=?,proof=? WHERE id=?',
                    ('CONFIRMED' if proven else 'UNKNOWN',encode(dict(after=after,incompatible=incompatible)),cid))
            self.checkpoint('confirmation')
            return proven
        except (ValueError,TimeoutError):return False

    def win(self,m,proof):
        t=m['target'];s=self.s
        writes=[(cid,json.loads(body)['operation'],state) for cid,body,state in s.db.execute('SELECT id,body,state FROM c4_work') if json.loads(body)['params'].get('item_id')==t['item_id']]
        for cid,op,state in writes:
            if state!='CONFIRMED':self.reconcile(cid)
        writes=[(cid,op,s.db.execute('SELECT state FROM c4_work WHERE id=?',(cid,)).fetchone()[0]) for cid,op,_ in writes]
        if any(op=='list' and state=='CONFIRMED' for _,op,state in writes):return True
        pile=self.pile();matches=[r for r in pile['result']['auctions'] if r['item']['item_id']==t['item_id']]
        op='list' if matches else 'move'
        if any(old==op for _,old,_ in writes):return False # Consumed, even if not sent.
        if matches and (len(matches)!=1 or matches[0]['trade_state']!='inactive' or matches[0]['current_bid']!=0):return False
        if not matches and len(pile['result']['auctions'])>=50:return False
        win=self.c._read('watched')
        owned=self.c._read('owned_item',**t) if op=='move' else self.pile()
        rules=self.c.prices.load(key=CardKey(t['definition_id']))
        pair=rules.validate_listing(m['resale_price'])
        if pair.status!='LISTABLE':
            self.c.journal.metric(m['batch_id'],'WIN_LISTING_PENDING',target=t,reason=pair.reason);return False
        params=dict(**t,paid=proof['paid'],owned_read_id=owned['command_id'],win_read_id=win['command_id'],
            caps_read_id=rules.caps_read_id,starting_bid=pair.starting_bid,buy_now_price=m['resale_price'],duration=3600)
        cid=self.dispatch(op,params)
        return op=='list' and s.db.execute('SELECT state FROM c4_work WHERE id=?',(cid,)).fetchone()[0]=='CONFIRMED'

    def maintenance(self, *, scan=False):
        """One bounded serialized pass, after urgent status/rebid readbacks.

        Sold detection uses the latest complete acquisition/resale observation;
        each relist tick also forces a new inventory. Uncertain target generations
        remain consumed, while disjoint later targets may proceed.
        """
        if not self.s.running():return
        self.recover_bulk()
        due=self.s.db.execute('SELECT next_due FROM c4_maintenance').fetchone()[0]
        tick=self.s.now()>=stamp(due)
        if not tick and not scan and self.inventory is None:return
        try:
            if tick:
                # Advance before any I/O; interruption cannot reset a tick budget.
                with self.s.lock,self.s.db:self.s.db.execute('UPDATE c4_maintenance SET next_due=?',((self.s.now()+timedelta(seconds=3660)).isoformat(),))
                before=self.pile()
            else:before=self.pile() if scan else self.inventory
            groups=classify(before)
            op='clear_sold' if groups['sold'] else 'relist_all' if tick and groups['expired'] else None
            if not op:return
            confirmed=self.bulk(op)
            if tick and op=='clear_sold' and confirmed:
                remaining=classify(self.pile())
                if not remaining['sold'] and remaining['expired']:self.bulk('relist_all')
        except Exception:
            self.c.journal.metric(None,'MAINTENANCE_UNKNOWN',reason='BOUNDED_WORK_UNCONFIRMED')

    def bulk(self, op):
        before=self.pile();params=parameters(before,op)
        if not params['expected_item_ids']:return False
        c=self.c.native.envelope(self.c.ids(),op,params);key=action(c,before)
        old=self.s.db.execute('SELECT id,state FROM c4_work WHERE action=?',(key,)).fetchone()
        if old:return old[1]=='CONFIRMED' or self.reconcile(old[0])
        cid=self.dispatch(op,params)
        return self.s.db.execute('SELECT state FROM c4_work WHERE id=?',(cid,)).fetchone()[0]=='CONFIRMED'
