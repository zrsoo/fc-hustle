"""Exact physical-card resale. ACKs never advance the lifecycle.

Every write is consumed durably before dispatch. Recovery only reads; absence,
timeouts and even an intent-only crash never authorize a replacement write.
"""
from dataclasses import replace
import json
import sqlite3

from fc_access.bidding_v1 import capacity
from fc_access.bidding_v1.contracts import State
from .contracts import parse_response, stamp
from .prices import CardKey


def fresh_read(f, v, operation):
    a = f.adapter
    cid = v['command_id']
    if (v != a.responses.get(cid) or v['operation'] != operation or
            v['context'] != a.context or v['fences'] != a.fences):
        raise ValueError('independent_current_read_required')
    parse_response(v, a.commands[cid], now=f.now(), source=a.source)
    if not v['result']['success']:
        raise ValueError('successful_read_required')
    return v


def verify_win(f, status, watched, owned):
    """Owned-card lastSalePrice corroborates terminal trade cost, never valuation.

    A market comparable's lastSalePrice or a balance delta is not a paid receipt.
    The exact physical owned DTO, closed/highest trade and dispatched bid must
    agree. Missing/zero/disagreeing owned cost leaves the candidate PENDING.
    """
    fresh_read(f, watched, 'watched'); fresh_read(f, owned, 'unassigned')
    identity = status.identity
    rows = [r for r in watched['result']['auctions'] if r['trade_id'] == identity.trade_id and
            r['item']['item_id'] == identity.item_id and r['item']['definition_id'] == identity.definition_id]
    items = [i for i in owned['result']['items'] if i['item_id'] == identity.item_id and
             i['definition_id'] == identity.definition_id and i['untradeable'] is False]
    bid = f.journal.db.execute('SELECT id,amount,intended_at,status_read_id,state FROM commands '
        'WHERE scope=? AND trade_id=? AND item_id=? AND definition_id=? ORDER BY rowid DESC LIMIT 1',
        (f.registry.scope, identity.trade_id, identity.item_id, identity.definition_id)).fetchone()
    if (status.state != State.PENDING or len(rows) != 1 or len(items) != 1 or not bid or
            rows[0]['trade_state'] != 'closed' or rows[0]['bid_state'] != 'highest' or rows[0]['expires'] > 0 or
            rows[0]['current_bid'] != status.current_bid or rows[0]['native_is_won'] is False or
            not status.current_bid or items[0]['last_sale_price'] != status.current_bid or bid[1] != status.current_bid or
            bid[4] == 'NOT_DISPATCHED' or not any(e['command_id'] == bid[0] and e['reason'] == 'PENDING'
                for e in f.journal.trace(scope=f.registry.scope, trade_id=identity.trade_id)) or
            len({watched['command_id'], owned['command_id'], bid[0], bid[3]}) != 4 or
            any(stamp(v['freshness']['network_at']) < stamp(bid[2]) for v in (watched, owned))):
        raise ValueError('owned_physical_item_and_paid_cost_unproven')
    return replace(status, state=State.WON, owned_item_id=identity.item_id, paid=items[0]['last_sale_price'])


def install(j):
    j.db.executescript('''
      CREATE TABLE IF NOT EXISTS resales_v1(scope TEXT NOT NULL, trade_id TEXT NOT NULL,
        item_id TEXT NOT NULL, definition_id INTEGER NOT NULL, paid INTEGER NOT NULL,
        resale_price INTEGER NOT NULL, state TEXT NOT NULL, PRIMARY KEY(scope,trade_id));
      CREATE TABLE IF NOT EXISTS resale_writes_v1(id TEXT PRIMARY KEY, scope TEXT NOT NULL,
        trade_id TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL, at TEXT NOT NULL,
        before_trade TEXT NOT NULL);
      CREATE TRIGGER IF NOT EXISTS resale_policy_immutable BEFORE UPDATE OF
        scope,trade_id,item_id,definition_id,paid,resale_price ON resales_v1
        BEGIN SELECT RAISE(ABORT,'immutable_resale_policy'); END;
      CREATE TRIGGER IF NOT EXISTS resale_intent_immutable BEFORE UPDATE OF
        id,scope,trade_id,body,at,before_trade ON resale_writes_v1
        BEGIN SELECT RAISE(ABORT,'immutable_resale_intent'); END;
    ''')
    columns = {r[1] for r in j.db.execute('PRAGMA table_info(resale_writes_v1)')}
    for name in ('claimed_at', 'completed_at'):
        if name not in columns:
            j.db.execute('ALTER TABLE resale_writes_v1 ADD COLUMN '+name+' TEXT')


def pending(j, scope):
    if not j.db.execute("SELECT 1 FROM sqlite_master WHERE name='resale_writes_v1'").fetchone():
        return []
    return [dict(command_id=r[0], trade_id=r[1], state=r[2], operation=r[3]) for r in j.db.execute(
        "SELECT id,trade_id,state,json_extract(body,'$.operation') FROM resale_writes_v1 "
        "WHERE scope=? AND state!='RECONCILED'", (scope,))]


def mutation_authorized(path, c, *, reconciled=False):
    from .foundation import scope_for
    from fc_access.bidding_v1.journal import Journal
    try:
        j = Journal(path, readonly=True)
        try:
            scope, fences = scope_for(c['context']), c['fences']
            row = j.db.execute('SELECT scope,body,state FROM resale_writes_v1 WHERE id=?', (c['id'],)).fetchone()
            if not row or row[:2] != (scope, json.dumps(c, sort_keys=True)):
                return False
            if reconciled:
                return row[2] == 'RECONCILED'
            from .bulk import pending as pending_bulk
            if pending_bulk(j, scope):
                return False
            j._owner(scope, fences['owner'], fences['epoch'])
            return row[2] == 'UNKNOWN'
        finally:
            j.close()
    except (sqlite3.Error, OSError, ValueError, KeyError):
        return False


class Resale:
    def __init__(self, foundation):
        self.f = foundation
        install(foundation.journal)

    def event(self, trade, reason, **data):
        self.f.registry._append(dict(kind='RESALE', reason=reason, epoch=self.f.registry.epoch, **data), trade)

    def inventory(self):
        from fc_access.actors_v1.occupancy import assess
        f = self.f
        v = f.read('transfer_list')
        proof = assess(v, f.adapter.commands[v['command_id']], now=f.now(), source=f.adapter.source)
        if proof['occupied'] is None:
            raise ValueError('complete_transfer_list_required')
        return v

    def observe(self, v):
        f = self.f
        capacity.observe(f.journal, f.registry.scope, v['result']['auctions'], read_id=v['command_id'],
            network_at=stamp(v['freshness']['network_at']), now=f.now())

    def seed(self):
        """Use only independently verified terminal events and the stored quote."""
        f = self.f
        for event in f.journal.trace(scope=f.registry.scope):
            if event['reason'] != 'WON_VERIFIED':
                continue
            trade, data = event['trade_id'], event['data']
            # Legacy terminal events without complete proof remain reserved.
            if not data.get('item_id') or not data.get('paid'):
                continue
            policies = [e for e in f.registry.events(trade) if e['kind'] == 'ENROLLMENT']
            if not policies:
                continue
            policy = policies[0]
            proofs = [e for e in f.registry.events(trade) if e.get('reason') == 'OWNED_WIN_VERIFIED' and
                e.get('paid') == data['paid'] and e.get('identity') == policy['identity'] and
                e.get('win_read_id') == data['read_id']]
            if not proofs:
                continue
            if policy['identity'] != dict(trade_id=trade, item_id=data['item_id'], definition_id=data['definition_id'],
                    platform=f.adapter.context['platform'], game=f.adapter.context['game']):
                raise ValueError('resale_policy_identity_conflict')
            with f.journal.transaction():
                f.registry.check()
                f.journal.db.execute('INSERT OR IGNORE INTO resales_v1 VALUES(?,?,?,?,?,?,?)',
                    (f.registry.scope, trade, data['item_id'], data['definition_id'], data['paid'],
                     policy['quote']['resale_price'], 'READY'))

    def cycle(self):
        from fc_access.actors_v1.locking import process_lock
        f = self.f
        with process_lock(f.journal_path.with_suffix('.bid.lock'), wait_seconds=35):
            f.registry.check()
            self.seed()
            unresolved = pending(f.journal, f.registry.scope)
            if unresolved:
                for write in unresolved:
                    self.reconcile(write['command_id'])
                return  # Reconciliation and a new mutation are separate cycles.
            # Any unresolved acquisition blocks resale writes too.
            if f.registry.current()['unresolved']:
                return
            rows = f.journal.db.execute("SELECT trade_id,item_id,definition_id,paid,resale_price,state "
                "FROM resales_v1 WHERE scope=? AND state NOT IN ('LISTED','UNLISTABLE') ORDER BY rowid",
                (f.registry.scope,)).fetchall()
            for trade, item, definition, paid, price, state in rows:
                try:
                    pile = self.inventory()
                except (ValueError, TimeoutError):
                    self.event(trade, 'INVENTORY_UNAVAILABLE'); return
                self.observe(pile)
                matches = [r for r in pile['result']['auctions'] if r['item']['item_id'] == item]
                if matches and (len(matches) != 1 or matches[0]['item']['definition_id'] != definition):
                    self.event(trade, 'PHYSICAL_ITEM_MISMATCH'); continue
                if matches:
                    row = matches[0]
                    if row['trade_state'] != 'inactive' or row['current_bid'] != 0:
                        self.event(trade, 'UNEXPECTED_TRANSFER_STATE'); continue
                    owned, owned_item, op = pile, row['item'], 'list'
                    win_id = next(e['data']['read_id'] for e in reversed(f.journal.trace(scope=f.registry.scope, trade_id=trade))
                        if e['reason'] == 'WON_VERIFIED' and e['data'].get('item_id'))
                    before_trade = row['trade_id']
                else:
                    if len(pile['result']['auctions']) >= 50:
                        self.event(trade, 'TRANSFER_LIST_FULL'); continue
                    if state == 'MOVED':
                        self.event(trade, 'MOVED_ITEM_MISSING'); continue
                    watched, owned = f.read('watched'), f.read('unassigned')
                    from .foundation import status_from
                    candidates = [r for r in watched['result']['auctions'] if r['trade_id'] == trade]
                    if len(candidates) != 1:
                        self.event(trade, 'WIN_UNPROVEN'); continue
                    try:
                        verified = verify_win(f, status_from(candidates[0], watched), watched, owned)
                    except ValueError:
                        self.event(trade, 'WIN_UNPROVEN'); continue
                    if (verified.identity.item_id, verified.identity.definition_id, verified.paid) != (item, definition, paid):
                        self.event(trade, 'PHYSICAL_ITEM_MISMATCH'); continue
                    owned_item = next(i for i in owned['result']['items'] if i['item_id'] == item)
                    op, win_id, before_trade = 'move', watched['command_id'], trade
                if owned_item['untradeable'] is not False or owned_item['last_sale_price'] != paid:
                    self.event(trade, 'PAID_COST_UNPROVEN'); continue
                try:
                    rules = f.prices.load(key=CardKey(definition))
                except (ValueError, TimeoutError):
                    self.event(trade, 'PRICE_EVIDENCE_UNAVAILABLE'); continue
                pair = rules.validate_listing(price)
                if pair.status != 'LISTABLE':
                    # Unavailable evidence is recoverable; a proven illegal pair is terminal.
                    invalid = pair.status == 'UNLISTABLE' or pair.reason == 'helper_disagreement'
                    with f.journal.transaction():
                        f.registry.check()
                        if invalid:
                            f.journal.db.execute("UPDATE resales_v1 SET state='UNLISTABLE' WHERE scope=? AND trade_id=?",
                                (f.registry.scope, trade))
                        self.event(trade, 'UNLISTABLE' if invalid else 'PRICE_EVIDENCE_UNAVAILABLE',
                            resale_price=price, detail=pair.reason)
                    continue
                params = dict(trade_id=trade, item_id=item, definition_id=definition, paid=paid,
                    owned_read_id=owned['command_id'], win_read_id=win_id, caps_read_id=rules.caps_read_id,
                    starting_bid=pair.starting_bid, buy_now_price=price, duration=3600)
                self.dispatch(op, params, owned, before_trade)
                return

    def checkpoint(self, stage):
        """Fault-injection seam; no runtime behavior."""

    def dispatch(self, op, params, owned, before_trade):
        f, j = self.f, self.f.journal
        c = f.adapter.envelope(f.ids(), op, params)
        # Both commits precede the native call. A fresh process cannot dispatch
        # an old INTENT or UNKNOWN record, even if nothing reached the browser.
        with j.transaction():
            f.registry.check()
            fresh_read(f, owned, 'unassigned' if op == 'move' else 'transfer_list')
            caps = f.adapter.responses[params['caps_read_id']]
            fresh_read(f, caps, 'caps')
            if owned['command_id'] != params['owned_read_id']:
                raise ValueError('ownership_read_mismatch')
            if pending(j, f.registry.scope) or f.registry.current()['unresolved']:
                raise ValueError('reconciliation_required')
            plan = j.db.execute('SELECT item_id,definition_id,paid,resale_price,state FROM resales_v1 '
                'WHERE scope=? AND trade_id=?', (f.registry.scope, params['trade_id'])).fetchone()
            if not plan or plan[:4] != (params['item_id'], params['definition_id'], params['paid'], params['buy_now_price']) or plan[4] not in {'READY','MOVED'}:
                raise ValueError('immutable_resale_policy_required')
            rules = f.prices.loaded[params['caps_read_id']]
            pair = rules.validate_listing(plan[3], key=CardKey(plan[1]))
            if pair.status != 'LISTABLE' or pair.starting_bid != params['starting_bid']:
                raise ValueError('native_listing_pair_required')
            if op == 'move':
                from .foundation import status_from
                win = f.adapter.responses[params['win_read_id']]
                candidates = [r for r in win['result']['auctions'] if r['trade_id'] == params['trade_id']]
                if len(candidates) != 1 or plan[4] != 'READY':
                    raise ValueError('fresh_win_required')
                verified = verify_win(f, status_from(candidates[0], win), win, owned)
                if (verified.identity.item_id, verified.identity.definition_id, verified.paid) != plan[:3]:
                    raise ValueError('owned_physical_item_and_paid_cost_unproven')
            else:
                from fc_access.actors_v1.occupancy import assess
                proof = assess(owned, f.adapter.commands[owned['command_id']], now=f.now(), source=f.adapter.source)
                matches = [r for r in owned['result']['auctions'] if r['item']['item_id'] == plan[0] and
                    r['item']['definition_id'] == plan[1] and r['item']['last_sale_price'] == plan[2] and
                    r['item']['untradeable'] is False and r['trade_state'] == 'inactive' and
                    r['current_bid'] == 0 and r['trade_id'] == before_trade]
                if proof['occupied'] is None or len(matches) != 1:
                    raise ValueError('exact_inactive_owned_item_required')
            j.db.execute('INSERT INTO resale_writes_v1(id,scope,trade_id,body,state,at,before_trade) VALUES(?,?,?,?,?,?,?)', (c['id'], f.registry.scope,
                params['trade_id'], json.dumps(c, sort_keys=True), 'INTENT', f.now().isoformat(), before_trade))
            j.db.execute("UPDATE capacity_slots_v1 SET phase='RESALE_UNKNOWN' WHERE scope=? AND trade_id=?",
                (f.registry.scope, params['trade_id']))
            self.event(params['trade_id'], 'INTENT_DURABLE', command_id=c['id'], operation=op, params=params)
        self.checkpoint('intent')
        with j.transaction():
            f.registry.check()
            j.db.execute("UPDATE resale_writes_v1 SET state='UNKNOWN',claimed_at=? WHERE id=?", (f.now().isoformat(),c['id']))
            self.event(params['trade_id'], 'DISPATCH_CLAIM', command_id=c['id'], operation=op)
        self.checkpoint('claimed')
        # Keep ownership stable across the synchronous native handoff, just as
        # acquisition dispatch does. The independently committed claim survives.
        with j.transaction():
            f.registry.check()
            fresh_read(f, owned, 'unassigned' if op == 'move' else 'transfer_list')
            fresh_read(f, caps, 'caps')
            try:
                v = parse_response(f.executor.execute(c), c, now=f.now(), source=f.adapter.source)
                outcome = 'ACKNOWLEDGED' if v['result']['success'] else 'UNKNOWN'
            except Exception:
                outcome = 'UNKNOWN'
            self.checkpoint('sent')
            j.db.execute('UPDATE resale_writes_v1 SET state=?,completed_at=? WHERE id=?', (outcome, f.now().isoformat(),c['id']))
            self.event(params['trade_id'], outcome, command_id=c['id'], operation=op)
        self.checkpoint('ack')
        self.reconcile(c['id'])

    def reconcile(self, cid):
        f, j = self.f, self.f.journal
        row = j.db.execute('SELECT body,state,at,before_trade,claimed_at,completed_at FROM resale_writes_v1 WHERE id=? AND scope=?',
            (cid, f.registry.scope)).fetchone()
        if not row or row[1] == 'RECONCILED':
            return False
        c, at, before = json.loads(row[0]), stamp(row[2]), row[3]
        p, op = c['params'], c['operation']
        try:
            pile = self.inventory()
        except (ValueError, TimeoutError):
            self.event(p['trade_id'], 'INVENTORY_UNAVAILABLE', command_id=cid); return False
        reads = [pile]
        if op == 'move':
            owned = f.read('unassigned'); reads.append(owned)
        for v in reads:
            fresh_read(f, v, v['operation'])
            if (stamp(v['freshness']['network_at']) < at or
                    v['command_id'] in {cid, p['owned_read_id'], p['win_read_id'], p['caps_read_id']}):
                raise ValueError('independent_post_mutation_read_required')
        matches = [r for r in pile['result']['auctions'] if r['item']['item_id'] == p['item_id'] and
            r['item']['definition_id'] == p['definition_id'] and r['item']['untradeable'] is False]
        proven = len(matches) == 1
        if proven and op == 'move':
            proven = (not any(i['item_id'] == p['item_id'] for i in owned['result']['items']) and
                matches[0]['trade_state'] == 'inactive' and matches[0]['item']['last_sale_price'] == p['paid'])
        elif proven:
            r = matches[0]
            claimed = stamp(row[4]) if row[4] else at
            elapsed = (stamp(pile['freshness']['network_at'])-claimed).total_seconds()
            # Anchor expiry to the dispatch interval, including on restart.
            # An unrelated later relist at the same prices is not our readback.
            latency = (stamp(row[5])-claimed).total_seconds() if row[5] else 30
            duration = r['expires']+elapsed
            proven = (r['trade_id'] not in {before, p['trade_id']} and r['trade_state'] == 'active' and
                r['bid_state'] in {'none','highest','outbid'} and r['starting_bid'] == p['starting_bid'] and
                r['buy_now_price'] == p['buy_now_price'] and 0 < r['expires'] <= 3600 and
                elapsed >= 0 and 3598 <= duration <= 3602+latency and
                not any(other['trade_id'] == r['trade_id'] and other['item']['item_id'] != p['item_id']
                    for other in pile['result']['auctions']))
        with j.transaction():
            f.registry.check()
            # Complete inventory and pending->occupied handoff share this commit
            # with mutation reconciliation. Readers cannot see an unreserved gap.
            if proven:
                j.db.execute("UPDATE resale_writes_v1 SET state='RECONCILED' WHERE id=?", (cid,))
                j.db.execute('UPDATE resales_v1 SET state=? WHERE scope=? AND trade_id=?',
                    ('MOVED' if op == 'move' else 'LISTED', f.registry.scope, p['trade_id']))
                j.db.execute("UPDATE capacity_slots_v1 SET phase='PENDING_RESALE' WHERE scope=? AND trade_id=?",
                    (f.registry.scope, p['trade_id']))
                self.observe(pile)
            self.event(p['trade_id'], 'VERIFIED' if proven else 'RECONCILIATION_REQUIRED',
                command_id=cid, operation=op, read_ids=[v['command_id'] for v in reads],
                new_trade_id=matches[0]['trade_id'] if proven and op == 'list' else None)
        return proven

