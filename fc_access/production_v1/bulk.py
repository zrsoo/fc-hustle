"""One-shot native bulk maintenance. Recovery reads evidence; it never retries.

The sealed finite research campaign is provenance, never runtime dispatch work.
All eligible account items, including manual listings, belong to each intent.
"""
from copy import deepcopy
import json
import math
import sqlite3

from fc_access.bidding_v1 import capacity
from .contracts import BULK, parse_response, stamp
from .resale import fresh_read


def install(j):
    j.db.executescript('''
      CREATE TABLE IF NOT EXISTS bulk_writes_v1(id TEXT PRIMARY KEY, scope TEXT NOT NULL,
        body TEXT NOT NULL, before_read TEXT NOT NULL, state TEXT NOT NULL,
        at TEXT NOT NULL, completed_at TEXT, incompatible INTEGER NOT NULL DEFAULT 0);
      CREATE TRIGGER IF NOT EXISTS bulk_intent_immutable BEFORE UPDATE OF
        id,scope,body,before_read,at ON bulk_writes_v1
        BEGIN SELECT RAISE(ABORT,'immutable_bulk_intent'); END;
    ''')


def pending(j, scope):
    if not j.db.execute("SELECT 1 FROM sqlite_master WHERE name='bulk_writes_v1'").fetchone():
        return []
    return [dict(command_id=r[0], trade_id=None, state=r[1], operation=r[2]) for r in j.db.execute(
        "SELECT id,state,json_extract(body,'$.operation') FROM bulk_writes_v1 "
        "WHERE scope=? AND state!='RECONCILED'", (scope,))]


def classify(v):
    """Cross-check native predicates and ownership for the entire account pile."""
    rows, proofs = v['result']['auctions'], v['coverage'].get('bulk')
    if not v['coverage']['complete'] or proofs is None or len(proofs) != len(rows):
        raise ValueError('complete_native_bulk_inventory_required')
    groups = dict(sold=[], expired=[], active=[])
    for row, proof in zip(rows, proofs):
        sold = row['trade_state'] == 'closed' and row['current_bid'] > 0 and row['expires'] <= 0
        expired = row['trade_state'] == 'expired' and row['current_bid'] == 0 and row['expires'] == -1
        active = row['trade_state'] == 'active' and row['expires'] > 0
        if (proof['item_id'] != row['item']['item_id'] or proof['trade_owner'] is not True or
                row['bid_state'] != 'none' or sum((sold, expired, active)) != 1 or
                [proof[k] for k in ('sold', 'expired', 'active')] != [sold, expired, active]):
            raise ValueError('unproven_native_bulk_semantics')
        groups['sold' if sold else 'expired' if expired else 'active'].append(row['item']['item_id'])
    return groups


def parameters(v, op):
    if op not in BULK:
        raise ValueError('unsupported_bulk_operation')
    groups = classify(v)
    # An empty expired set is a no-op even when sold cards remain. A mixed
    # sold/expired mutation still requires the existing native safety guard.
    if op == 'relist_all' and groups['expired'] and groups['sold']:
        raise ValueError('relist_with_sold_unproven')
    return dict(before_read_id=v['command_id'], expected_item_ids=sorted(groups[
        'sold' if op == 'clear_sold' else 'expired']), expected_inventory_ids=sorted(
            r['item']['item_id'] for r in v['result']['auctions']),
        expected_sold_count=len(groups['sold']), expected_expired_count=len(groups['expired']))


def mutation_authorized(path, c, *, reconciled=False):
    from .foundation import scope_for
    from fc_access.bidding_v1.journal import Journal
    try:
        j = Journal(path, readonly=True)
        try:
            scope = scope_for(c['context'])
            row = j.db.execute('SELECT scope,body,state,before_read,incompatible FROM bulk_writes_v1 WHERE id=?',
                               (c['id'],)).fetchone()
            if not row or row[:2] != (scope, json.dumps(c, sort_keys=True)) or row[4]:
                return False
            if reconciled:
                return row[2] == 'RECONCILED'
            j._owner(scope, c['fences']['owner'], c['fences']['epoch'])
            before = json.loads(row[3])
            return (row[2] == 'UNKNOWN' and before['context'] == c['context'] and
                    before['fences'] == c['fences'] and parameters(before, c['operation']) == c['params'])
        finally:
            j.close()
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        return False


class BulkTransfer:
    def __init__(self, foundation):
        self.f = foundation
        install(foundation.journal)

    def checkpoint(self, stage):
        """Fault injection seam."""

    def event(self, reason, **data):
        self.f.registry._append(dict(kind='BULK_TRANSFER', reason=reason,
            epoch=self.f.registry.epoch, **data))

    def inventory(self):
        from fc_access.actors_v1.occupancy import assess
        f = self.f
        v = f.read('transfer_list')
        fresh_read(f, v, 'transfer_list')
        proof = assess(v, f.adapter.commands[v['command_id']], now=f.now(), source=f.adapter.source)
        if proof['occupied'] is None:
            raise ValueError('complete_transfer_list_required')
        classify(v)
        return v

    def observe(self, v):
        f = self.f
        capacity.observe(f.journal, f.registry.scope, v['result']['auctions'],
            read_id=v['command_id'], network_at=stamp(v['freshness']['network_at']), now=f.now())

    def execute(self, operation):
        from fc_access.actors_v1.locking import process_lock
        if operation not in BULK:
            raise ValueError('unsupported_bulk_operation')
        f, j = self.f, self.f.journal
        with process_lock(f.journal_path.with_suffix('.bid.lock'), wait_seconds=35):
            f.registry.check()
            outstanding = pending(j, f.registry.scope)
            if outstanding:
                # Resuming a consumed operation can only reconcile it.
                for write in outstanding: self.reconcile(write['command_id'])
                return dict(status='RECONCILIATION_ONLY')
            # Blocked acquisition intents still require a fresh inventory on
            # each maintenance tick. Pending bulk writes read via reconcile.
            before = self.inventory()
            p = parameters(before, operation)
            if not p['expected_item_ids']:
                with j.transaction():
                    f.registry.check()
                    self.observe(before)
                    self.event('EMPTY_SKIP', operation=operation, read_id=before['command_id'])
                return dict(status='SKIPPED', read_id=before['command_id'])
            if f.registry.current()['unresolved']:
                raise ValueError('reconciliation_required')
            c = f.adapter.envelope(f.ids(), operation, p)
            with j.transaction():
                f.registry.check()
                fresh_read(f, before, 'transfer_list')
                self.observe(before)
                j.db.execute('INSERT INTO bulk_writes_v1(id,scope,body,before_read,state,at) VALUES(?,?,?,?,?,?)',
                    (c['id'], f.registry.scope, json.dumps(c, sort_keys=True),
                     json.dumps(before, sort_keys=True), 'INTENT', f.now().isoformat()))
                self.event('INTENT_DURABLE', command_id=c['id'], operation=operation,
                    account_wide=True, includes_manual_items=True, params=p)
            self.checkpoint('intent')
            with j.transaction():
                f.registry.check()
                fresh_read(f, before, 'transfer_list')
                j.db.execute("UPDATE bulk_writes_v1 SET state='UNKNOWN' WHERE id=?", (c['id'],))
                self.event('DISPATCH_CLAIM', command_id=c['id'])
            self.checkpoint('claimed')
            with j.transaction():
                f.registry.check()
                fresh_read(f, before, 'transfer_list')
                state = 'UNKNOWN'
                incompatible = False
                try:
                    v = parse_response(f.executor.execute(c), c, now=f.now(), source=f.adapter.source)
                    if v['result']['success']: state = 'ACKNOWLEDGED'
                    incompatible = v['result']['error'] == 'bulk_contract_changed'
                except Exception:
                    pass  # No native exception text or automatic replay.
                self.checkpoint('sent')
                j.db.execute('UPDATE bulk_writes_v1 SET state=?,completed_at=?,incompatible=? WHERE id=?',
                             (state, f.now().isoformat(), int(incompatible), c['id']))
                self.event(state, command_id=c['id'])
            self.checkpoint('ack')
            proven = self.reconcile(c['id'])
            return dict(status='CONFIRMED' if proven else 'UNRESOLVED', command_id=c['id'])

    def reconcile(self, cid):
        f, j = self.f, self.f.journal
        f.registry.check()
        row = j.db.execute('SELECT body,before_read,state,at,completed_at,incompatible FROM bulk_writes_v1 '
                           'WHERE id=? AND scope=?', (cid, f.registry.scope)).fetchone()
        if not row or row[2] == 'RECONCILED': return False
        c, before = json.loads(row[0]), json.loads(row[1])
        # A different account/namespace cannot supply recovery evidence.
        if c['context'] != f.adapter.context: raise ValueError('wrong_reconciliation_context')
        try:
            after = self.inventory()
        except (ValueError, TimeoutError):
            self.event('INVENTORY_UNAVAILABLE', command_id=cid)
            return False
        if (after['command_id'] in {cid, before['command_id']} or
                stamp(after['freshness']['network_at']) < stamp(row[4] or row[3])):
            raise ValueError('independent_post_mutation_read_required')
        old = {r['item']['item_id']: r for r in before['result']['auctions']}
        new = {r['item']['item_id']: r for r in after['result']['auctions']}
        targets = set(c['params']['expected_item_ids'])
        clear = c['operation'] == 'clear_sold'
        expected = set(old)-targets if clear else set(old)
        proven, incompatible = set(new) == expected, bool(row[5])
        elapsed = max(0, (stamp(after['freshness']['network_at'])-stamp(before['freshness']['network_at'])).total_seconds())
        # Expiry is a remaining-seconds counter, not an immutable duration field.
        # Anchor the independent read to the actual serialized dispatch interval.
        dispatched,completed=stamp(row[3]),stamp(row[4] or row[3])
        mailbox=getattr(f.executor.executor,'mailbox',None)
        if mailbox is not None:
            timing=mailbox.db.execute('SELECT started,finished FROM work WHERE id=?',(cid,)).fetchone()
            if timing and all(timing):dispatched,completed=map(stamp,timing)
        read_at=stamp(after['freshness']['network_at'])
        for identity in set(old) & set(new):
            a, b = old[identity], new[identity]
            if not clear and identity in targets:
                valid = (a['item'] == b['item'] and a['starting_bid'] == b['starting_bid'] and
                    a['buy_now_price'] == b['buy_now_price'] and b['trade_id'] != a['trade_id'] and
                    b['trade_id'] not in {r['trade_id'] for r in old.values()} and
                    b['current_bid'] == 0 and b['bid_state'] == 'none' and b['trade_state'] == 'active' and
                    0 < b['expires'] <= 3600 and read_at >= completed and
                    3598 <= b['expires']+(read_at-dispatched).total_seconds() and
                    b['expires']+(read_at-completed).total_seconds() <= 3602)
                # An expired unchanged row is partial/unknown; changed prices,
                # identity or non-hour active listing is incompatible and sticky.
                incompatible |= (b['item'] != a['item'] or b['starting_bid'] != a['starting_bid'] or
                    b['buy_now_price'] != a['buy_now_price'] or b['trade_state'] == 'active' and not valid)
            else:
                valid = all(a[k] == b[k] for k in a if k != 'expires') and (
                    a['expires'] == b['expires'] if a['expires'] <= 0 else
                    0 <= a['expires']-b['expires'] <= math.ceil(elapsed)+2)
                incompatible |= not valid
            proven &= valid
        if not clear:
            trades = [new[i]['trade_id'] for i in targets & set(new)]
            proven &= len(trades) == len(set(trades)) == len(targets)
        incompatible |= bool(set(new)-expected) or bool((set(old)-targets)-set(new))
        proven &= row[2] != 'INTENT' and not incompatible
        with j.transaction():
            f.registry.check()
            j.db.execute('UPDATE bulk_writes_v1 SET state=?,incompatible=? WHERE id=?',
                ('RECONCILED' if proven else row[2], int(incompatible), cid))
            if proven:
                capacity.observe(j, f.registry.scope, after['result']['auctions'],
                    read_id=after['command_id'], network_at=stamp(after['freshness']['network_at']), now=f.now())
            self.event('VERIFIED' if proven else 'INCOMPATIBLE' if incompatible else 'RECONCILIATION_REQUIRED',
                command_id=cid, operation=c['operation'], before_read_id=before['command_id'],
                read_id=after['command_id'], readback=deepcopy(after))
        self.checkpoint('readback')
        return bool(proven)
