"""Finite production composition. No actors, retries, or implicit account writes."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from fc_access.bidding_v1.contracts import (AuctionStatus, Balance, BidIntent, BidResult,
    Coverage, Freshness, Identity, Outcome, Snapshot, State)
from fc_access.bidding_v1.core import AuctionQueue, decide
from fc_access.bidding_v1.journal import Journal
from fc_access.bidding_v1.scheduler import Scheduler, Work
from .contracts import LOCAL_OPERATIONS, MUTATIONS, command, context, parse_response, stamp, token
from .adapter import NativeAdapter
from .prices import CardKey, PriceService
from .pricing import PricingService
from .price_cache import QuoteCache

DEFAULT_JOURNAL = Path('private-captures/production-v1/foundation.sqlite3')


def scope_for(value):
    context(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:32]


class ScheduledExecutor:
    """One serialized native boundary, also usable with explicitly staged work.

    execute drains only the finite queue preceding its result. Local helpers do
    not consume an EA request slot. Failed deliveries are never resubmitted.
    """
    def __init__(self, executor, *, now, source, interval=0, clock=time.monotonic,
                 sleep=time.sleep, observe=lambda event: None):
        self.executor, self.now, self.source = executor, now, source
        self.clock, self.sleep, self.observe = clock, sleep, observe
        self.scheduler = Scheduler(clock, concurrency=1, min_native_interval=interval)
        self.pending, self.results, self.errors, self.metrics = {}, {}, {}, []
        self.local_metrics = []
        self.lock = threading.RLock()

    def attach(self, value, owner, epoch):
        return self.executor.attach(value, owner, epoch)

    def submit(self, c, *, priority=None, timeout=30):
        command(c)
        if priority is None:
            priority = 90 if c['operation'] in {'bid', 'watched', 'status'} else 0
        if c['operation'] in LOCAL_OPERATIONS:
            raise ValueError('local_operation_requires_execute')
        if timeout <= 0:
            raise ValueError('invalid_timeout')
        with self.lock:
            start = self.clock()
            deadline = start + timeout
            if c['operation'] == 'bid':
                deadline = min(deadline, start + (stamp(c['params']['deadline'])-self.now()).total_seconds())
            if deadline <= start:
                raise TimeoutError('deadline_skipped')
            self.scheduler.enqueue(Work(c['id'], 'write' if c['operation'] in MUTATIONS else 'read', start, deadline, priority))
            self.pending[c['id']] = (deepcopy(c), start)
        return c['id']

    def run_one(self):
        with self.lock:
            work = self.scheduler.next()
            for cid, reason in self.scheduler.skipped:
                if cid in self.pending:
                    del self.pending[cid]
                    self.errors[cid] = TimeoutError('deadline_skipped')
                    self.observe(dict(kind='DEADLINE_SKIPPED', command_id=cid))
            if work is None:
                return None
            c, enqueued = self.pending.pop(work.command_id)
            started = self.clock()
            metric = dict(kind='EXECUTOR_METRIC', command_id=c['id'],
                          operation=c['operation'],
                          interval_seconds=self.scheduler.interval,
                          queue_ms=(started-enqueued)*1000, delivery_ms=None,
                          native_service_ms=None, request_count=None)
            try:
                raw = self.executor.execute(c)
                delivered = self.clock()
                v = parse_response(raw, c, now=self.now(), source=self.source,
                                   pricing_rows=c['operation'] == 'search' and c['params']['purpose'] == 'pricing')
                metric.update(native_service_ms=v['timing']['native_service_ms'],
                              request_count=v['freshness']['request_count'])
                self.split_timing(metric, v, (delivered-started)*1000)
                self.results[c['id']] = v
            except Exception:
                self.errors[c['id']] = TimeoutError('delivery_unknown_no_retry')
            finally:
                elapsed = (self.clock()-started)*1000
                metric['roundtrip_ms'] = elapsed
                if metric['native_service_ms'] is not None:
                    metric['delivery_ms'] = max(0, elapsed-metric['native_service_ms'])
                self.scheduler.complete(c['id'], request_count=metric['request_count'] or 0)
                self.metrics.append(metric)
                self.observe(metric)
            return c['id']

    def split_timing(self, metric, response, delivered_ms):
        t = response['timing']
        sql = getattr(self.executor, 'last_sqlite_ms', None)
        metric.update(ea_rtt_ms=t.get('ea_rtt_ms'), native_helper_ms=t.get('native_helper_ms'),
                      transport_sqlite_ms=sql,
                      browser_bridge_ms=max(0, delivered_ms-t['native_service_ms']-(sql or 0)),
                      browser_other_ms=(t['native_service_ms']-t['ea_rtt_ms']-t['native_helper_ms'])
                          if 'ea_rtt_ms' in t else None)

    def execute(self, c):
        enqueued = self.clock()
        with self.lock:
            if c['operation'] in LOCAL_OPERATIONS:
                # Local client helpers use the same lock but no native cadence.
                started = self.clock()
                metric = dict(kind='EXECUTOR_METRIC', command_id=c['id'], operation=c['operation'],
                              queue_ms=(started-enqueued)*1000, request_count=None)
                try:
                    raw = self.executor.execute(c)
                    delivered = self.clock()
                    v = parse_response(raw, c, now=self.now(), source=self.source)
                    metric.update(native_service_ms=v['timing']['native_service_ms'], request_count=0)
                    self.split_timing(metric, v, (delivered-started)*1000)
                    return v
                finally:
                    metric['roundtrip_ms'] = (self.clock()-started)*1000
                    self.local_metrics.append(metric)
                    self.observe(metric)
            cid = self.submit(c)
            self.pending[cid] = (self.pending[cid][0], enqueued)
            while cid not in self.results and cid not in self.errors:
                if self.run_one() is None:
                    if cid in self.results or cid in self.errors:
                        continue
                    now = self.clock()
                    next_at = min(w.deadline for w in self.scheduler.queue.values())
                    next_at = min(next_at, max(now, self.scheduler.last_native+self.scheduler.interval))
                    self.sleep(max(.001, next_at-now))
            if cid in self.errors:
                raise self.errors.pop(cid)
            return self.results.pop(cid)


class Registry:
    """Version-1 scoped projections over immutable events and durable intents."""
    version = 1
    REASONS = {'ELIGIBLE', 'LEADING', 'PENDING', 'STALE', 'EXPIRED', 'OVER_CAP',
               'INSUFFICIENT_BALANCE', 'QUEUE_FULL', 'DRAINING', 'UNKNOWN', 'SKIP',
               'QUOTE_REJECTED', 'QUOTE_INCOMPLETE', 'ENROLLED', 'UNRESOLVED_INTENT',
               'NOT_TRADEABLE', 'NATIVE_ACK', 'TIMEOUT', 'INVALID_RESULT', 'SERVICE_ERROR',
               'CAPACITY_UNKNOWN', 'PIPELINE_FULL', 'CAPACITY_IDENTITY_CONFLICT',
               'TRANSFER_LIST_UNKNOWN', 'TRANSFER_LIST_STALE', 'TRANSFER_LIST_CONFLICT',
               'TRANSFER_LIST_TRUNCATED', 'TRANSFER_LIST_FULL', 'TRANSFER_LIST_OVER_CAP'}

    def __init__(self, journal, value, owner, *, after_epoch=0, join_epoch=None):
        self.diagnostic_logging_ms = 0.0
        self.diagnostic_sqlite_ms = 0.0
        self.journal, self.context, self.owner = journal, deepcopy(context(value)), token(owner)
        self.scope = scope_for(value)
        journal.db.executescript('''
          CREATE TABLE IF NOT EXISTS registry_context_v1(scope TEXT PRIMARY KEY, context TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS registry_events_v1(seq INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL, trade_id TEXT, at TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS registry_no_update BEFORE UPDATE ON registry_events_v1
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
          CREATE TRIGGER IF NOT EXISTS registry_no_delete BEFORE DELETE ON registry_events_v1
            BEGIN SELECT RAISE(ABORT,'append_only'); END;
        ''')
        encoded = json.dumps(value, sort_keys=True)
        with journal.transaction():
            journal.db.execute('INSERT OR IGNORE INTO registry_context_v1 VALUES(?,?)', (self.scope, encoded))
            if journal.db.execute('SELECT context FROM registry_context_v1 WHERE scope=?', (self.scope,)).fetchone() != (encoded,):
                raise ValueError('registry_context_mismatch')
        if join_epoch is None:
            self.epoch = journal.session(self.scope, owner, after_epoch=after_epoch)
        else:
            journal._owner(self.scope, owner, join_epoch)
            self.epoch = join_epoch

    def check(self):
        self.journal._owner(self.scope, self.owner, self.epoch)

    def _append(self, body, trade=None):
        start, sqlite_start = time.perf_counter(), self.journal.db.sqlite_ms
        try:
            return self._append_body(body, trade)
        finally:
            self.diagnostic_logging_ms += (time.perf_counter()-start)*1000
            self.diagnostic_sqlite_ms += self.journal.db.sqlite_ms-sqlite_start

    def _append_body(self, body, trade=None):
        if trade is not None:
            token(trade, 'trade')
        encoded = json.dumps(body, sort_keys=True, allow_nan=False)
        def insert():
            self.check()
            self.journal.db.execute('INSERT INTO registry_events_v1(scope,trade_id,at,body) VALUES(?,?,?,?)',
                (self.scope, trade, self.journal.now().isoformat(), encoded))
        if self.journal.db.in_transaction:
            insert()  # Dispatch already owns the journal transaction.
        else:
            with self.journal.transaction():
                insert()

    def metric(self, event):
        self._append(event)

    def credits(self, balance):
        self._append(dict(kind='CREDITS', available_coins=balance.spendable,
                          read_id=balance.freshness.read_id, network_at=balance.freshness.network_at.isoformat()))

    def decision(self, status, action, reason, *, quote=None, cap=None, amount=None):
        if action not in {'HOLD', 'REJECT', 'BID', 'UNKNOWN'} or reason not in self.REASONS:
            raise ValueError('invalid_decision')
        body = dict(kind='DECISION', action=action, reason=reason, state=status.state.value,
                    identity=asdict(status.identity), amount=amount, cap=cap,
                    owner=self.owner, epoch=self.epoch)
        if quote is not None:
            body['quote'] = asdict(quote)
        self._append(body, status.identity.trade_id)
        return deepcopy(body)

    def events(self, trade=None):
        if trade is not None:
            token(trade, 'trade')
        query = 'SELECT seq,trade_id,at,body FROM registry_events_v1 WHERE scope=?'
        args = [self.scope]
        if trade is not None:
            query += ' AND trade_id=?'; args.append(trade)
        return [dict(seq=r[0], trade_id=r[1], at=r[2], **json.loads(r[3]))
                for r in self.journal.db.execute(query+' ORDER BY seq', args)]

    def current(self):
        auctions, credits = {}, None
        owner = self.journal.db.execute('SELECT owner,epoch FROM sessions WHERE scope=?', (self.scope,)).fetchone()
        for e in self.events():
            if e['kind'] == 'CREDITS':
                credits = e
            elif e['kind'] == 'DECISION':
                auctions.setdefault(e['trade_id'], {}).update(e)
        unresolved = []
        for cid, trade, state in self.journal.db.execute(
                "SELECT id,trade_id,state FROM commands WHERE scope=? AND state NOT IN ('RECONCILED','NOT_DISPATCHED')", (self.scope,)):
            unresolved.append(dict(command_id=cid, trade_id=trade, state=state))
            auctions.setdefault(trade, {}).update(action='UNKNOWN', reason='UNRESOLVED_INTENT', state='UNKNOWN')
        from .resale import pending as pending_resales
        unresolved.extend(pending_resales(self.journal, self.scope))
        from .bulk import pending as pending_bulk
        unresolved.extend(pending_bulk(self.journal, self.scope))
        # Prior-epoch observations are retained evidence, never fresh state.
        for value in auctions.values():
            if value.get('epoch') != owner[1]:
                value.update(action='UNKNOWN', state='UNKNOWN')
        replay = AuctionQueue(journal=self.journal, scope=self.scope)
        if credits is not None:
            credits['fresh'] = 0 <= (self.journal.now()-stamp(credits['network_at'])).total_seconds() <= 30
            credits['available_after_reservations'] = max(0, credits['available_coins']-sum(v[0] for v in replay.reservations.values()))
        from fc_access.bidding_v1.capacity import status as capacity_status
        return dict(schema=self.version, context=deepcopy(self.context), scope=self.scope,
                    owner=owner[0], epoch=owner[1], auctions=auctions, queued=sorted(replay.entries),
                    unresolved=unresolved, credits=credits,
                    capacity=capacity_status(self.journal, self.scope, now=self.journal.now()))


def freshness(v):
    f = v['freshness']
    return Freshness(stamp(f['observed_at']), stamp(f['network_at']) if f['network_at'] else None,
                     f['request_count'], f['read_id'], f['source'])


def status_from(row, response):
    f = freshness(response)
    state = State.UNKNOWN
    if row['native_is_won'] is True or row['trade_state'] == 'closed' and row['bid_state'] == 'highest':
        state = State.PENDING
    elif row['trade_state'] == 'active' and row['expires'] > 0:
        state = {'none': State.ACTIVE, 'highest': State.LEADING, 'outbid': State.OUTBID}.get(row['bid_state'], State.UNKNOWN)
    elif row['trade_state'] in {'closed', 'expired'} and row['expires'] <= 0 and row['bid_state'] == 'outbid':
        state = State.LOST
    return AuctionStatus(Identity(row['trade_id'], row['item']['item_id'], row['item']['definition_id']),
                         state, row['starting_bid'], row['current_bid'], row['buy_now_price'],
                         f.network_at+timedelta(seconds=row['expires']), f)


class Foundation:
    """Explicit one-shot API for future actor callers; constructing it only attaches."""
    def __init__(self, executor, *, context, journal_path=DEFAULT_JOURNAL, cache_path=None,
                 owner=None, now=None, interval=0, reserve=5000, clock=time.monotonic, sleep=time.sleep,
                 fixture=False, join_epoch=None):
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ids = lambda: secrets.token_hex(16)
        path = Path(journal_path); path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path = path
        self.cache_path = Path(cache_path) if cache_path else path.with_name('completed-quotes.sqlite3')
        self.journal = Journal(path, now=self.now)
        try:
            floor = executor.ownership_epoch(context) if hasattr(executor, 'ownership_epoch') else 0
            self.registry = Registry(self.journal, context, owner or self.ids(), after_epoch=floor, join_epoch=join_epoch)
            self.executor = ScheduledExecutor(executor, now=self.now, source='fixture' if fixture else 'native',
                interval=interval, clock=clock, sleep=sleep, observe=self.registry.metric)
            self.adapter = NativeAdapter(self.executor, context=context, owner=self.registry.owner,
                                         epoch=self.registry.epoch, now=self.now, fixture=fixture)
            if (self.adapter.fences['owner'], self.adapter.fences['epoch']) != (self.registry.owner, self.registry.epoch):
                raise ValueError('attachment_owner_mismatch')
            self.cache = QuoteCache(cache_path or path.with_name('completed-quotes.sqlite3'))
            self.prices = PriceService(self.adapter, self.ids)
            self.pricing = PricingService(self.adapter, self.ids, self.cache)
            self.queue = AuctionQueue(journal=self.journal, scope=self.registry.scope, reserve=reserve)
            self.admissions = {}
        except BaseException:
            if hasattr(self, 'cache'):
                self.cache.close()
            self.journal.close()
            raise

    def close(self):
        self.cache.close(); self.journal.close()

    def timing_summary(self):
        """Cumulative actual observations; take deltas around the desired window.

        Diagnostic wall time includes its SQLite subset. Browser bridge is the
        measured transport residual (IPC, polling, HTTP and serialization), not
        EA RTT. Legacy responses leave unavailable split timings unknown.
        """
        metrics = self.executor.metrics+self.executor.local_metrics
        def total(key):
            values = [m.get(key) for m in metrics]
            return sum(values) if all(v is not None for v in values) else None
        return dict(commands=len(metrics), ea_rtt_ms=total('ea_rtt_ms'),
            executor_queue_ms=total('queue_ms'), browser_bridge_ms=total('browser_bridge_ms'),
            native_helper_ms=total('native_helper_ms'), browser_other_ms=total('browser_other_ms'),
            transport_sqlite_ms=total('transport_sqlite_ms'),
            sqlite_ms=self.journal.db.sqlite_ms+self.cache.db.sqlite_ms,
            diagnostic_logging_ms=self.registry.diagnostic_logging_ms,
            diagnostic_sqlite_ms=self.registry.diagnostic_sqlite_ms,
            diagnostic_non_sqlite_ms=max(0, self.registry.diagnostic_logging_ms-self.registry.diagnostic_sqlite_ms))

    def read(self, operation, params=None):
        self.registry.check()
        return self.adapter.read(self.ids(), operation, params)

    def bulk(self, operation):
        """Explicit account-wide maintenance, including eligible manual cards."""
        from .bulk import BulkTransfer
        return BulkTransfer(self).execute(operation)

    def admit(self, status_response, trade_id, balance_response, *, X=500):
        self.registry.check()
        a = self.adapter
        for v, ops in ((status_response, {'search', 'watched'}), (balance_response, {'balance'})):
            cid = v['command_id']
            if cid not in a.commands or v != a.responses.get(cid) or v['operation'] not in ops:
                raise ValueError('adapter_read_required')
            parse_response(v, a.commands[cid], now=self.now(), source=a.source)
        rows = [r for r in status_response['result']['auctions'] if r['trade_id'] == trade_id]
        if len(rows) != 1:
            raise ValueError('exact_candidate_required')
        row = rows[0]; status = status_from(row, status_response)
        balance = Balance(balance_response['result']['credits'], None, freshness(balance_response))
        self.registry.credits(balance)
        pending = self.registry.current()['unresolved']
        def finish(action, reason, quote=None, cap=None, amount=None):
            return self.registry.decision(status, action, reason, quote=quote, cap=cap, amount=amount)
        if pending:
            return finish('UNKNOWN', 'UNRESOLVED_INTENT')
        if row['item']['untradeable'] is not False:
            return finish('REJECT', 'NOT_TRADEABLE')
        if status.state in {State.LEADING, State.PENDING, State.UNKNOWN, State.LOST}:
            return finish('HOLD' if status.state in {State.LEADING, State.PENDING} else 'UNKNOWN',
                          'LEADING' if status.state == State.LEADING else 'PENDING' if status.state == State.PENDING else 'UNKNOWN')
        prices = self.prices.load(key=CardKey(status.identity.definition_id))
        quote = self.pricing.quote(row, prices, X=X)
        if quote.status != 'COMPLETE':
            return finish('REJECT' if quote.status == 'REJECT' else 'UNKNOWN',
                          'QUOTE_REJECTED' if quote.status == 'REJECT' else 'QUOTE_INCOMPLETE', quote)
        cap = quote.max_affordable_bid
        d = decide(status, balance, prices, cap, now=self.now())
        coin_reason = self.queue.reserve_check(balance, now=self.now(), amount=d.amount or 0)
        if coin_reason:
            return finish('HOLD', coin_reason, quote, cap)
        if d.amount is None:
            return finish('HOLD' if d.reason in {'STALE', 'HOLD', 'PENDING'} else 'REJECT',
                          'LEADING' if d.reason == 'HOLD' else d.reason, quote, cap)
        from fc_access.actors_v1.occupancy import read as read_occupancy
        occupancy = read_occupancy(self)
        if not occupancy['enrollment_allowed']:
            return finish('HOLD', occupancy['reason'], quote, cap)
        admitted = self.queue.admit(status, balance, d.amount, now=self.now())
        if admitted != 'ENROLLED':
            return finish('HOLD', admitted, quote, cap)
        self.admissions[trade_id] = (status, balance, prices, deepcopy(quote), d.amount)
        return finish('BID', 'ELIGIBLE', quote, cap, d.amount)

    def bid(self, trade_id, *, command_id=None):
        """Explicit write seam. Admission is necessary; ACK remains unresolved."""
        self.registry.check()
        status, balance, prices, quote, amount = self.admissions[trade_id]
        cid = token(command_id or self.ids())
        params = dict(trade_id=trade_id, item_id=status.identity.item_id,
                      definition_id=status.identity.definition_id, amount=amount, minimum=amount,
                      cap=quote.max_affordable_bid, deadline=status.deadline.isoformat(),
                      status_read_id=status.freshness.read_id, balance_read_id=balance.freshness.read_id)
        foundation = self
        class IntentBridge:
            def dispatch_once(self, c, send):
                foundation.registry.check()
                for read_id in (status.freshness.read_id, balance.freshness.read_id):
                    parse_response(foundation.adapter.responses[read_id], foundation.adapter.commands[read_id],
                                   now=foundation.now(), source=foundation.adapter.source)
                # Admission cannot be transplanted into a different envelope.
                if c != foundation.adapter.envelope(cid, 'bid', params):
                    raise ValueError('intent_envelope_mismatch')
                intent = BidIntent(cid, foundation.registry.owner, foundation.registry.scope,
                    foundation.registry.epoch, status.identity, amount, quote.max_affordable_bid,
                    status.deadline, status.freshness.read_id, balance.freshness.read_id)
                evidence = dict(target=quote.resale_price, tax=quote.tax, profit_threshold=quote.X,
                    samples=quote.evidence['sample_count'], spendable=balance.spendable,
                    pricing_digest=hashlib.sha256(json.dumps(asdict(quote), sort_keys=True).encode()).hexdigest())
                foundation.journal.intend(intent, evidence)
                def call():
                    result = send()
                    return BidResult(result['command_id'], Outcome(result['outcome']), result['reason'])
                result = foundation.journal.dispatch(intent, call)
                return dict(command_id=result.command_id, outcome=result.outcome.value, reason=result.reason)
        return self.adapter.dispatch_intent(cid, params, journal=IntentBridge(), prices=prices,
            resale_price=quote.resale_price, profit_threshold=quote.X)

    def reconcile(self, command_id, status_response, balance_response):
        """Independent fresh readbacks resolve evidence, never resend a command."""
        self.registry.check()
        a = self.adapter
        for v, op in ((status_response, 'watched'), (balance_response, 'balance')):
            cid = v['command_id']
            if cid not in a.commands or v != a.responses.get(cid) or v['operation'] != op:
                raise ValueError('adapter_read_required')
            parse_response(v, a.commands[cid], now=self.now(), source=a.source)
        row = self.journal.db.execute('SELECT trade_id FROM commands WHERE id=? AND scope=?',
                                     (token(command_id), self.registry.scope)).fetchone()
        matches = [r for r in status_response['result']['auctions'] if row and r['trade_id'] == row[0]]
        if len(matches) != 1:
            raise ValueError('outcome_still_unknown')
        status = status_from(matches[0], status_response)
        balance = Balance(balance_response['result']['credits'], None, freshness(balance_response))
        self.journal.reconcile(command_id, scope=self.registry.scope, owner=self.registry.owner,
                               epoch=self.registry.epoch, status=status, balance=balance)
        self.queue.refresh(Snapshot((status,), freshness(status_response), Coverage(False, None)), now=self.now())
        self.registry.credits(balance)
        self.registry.decision(status, 'REJECT' if status.state == State.LOST else 'HOLD',
                               'SKIP' if status.state == State.LOST else
                               'LEADING' if status.state == State.LEADING else 'ELIGIBLE')
        return self.registry.current()


class JournalAuthority:
    """Server-side matching of a committed, fenced journal dispatch claim.

    Install explicitly in the local service composition. This grants no retry
    authority and cannot authorize a command using an HTTP boolean.
    """
    def __init__(self, path):
        self.path = Path(path)

    def reconciled(self, c):
        """Transport may clear its fence only from independently verified journal evidence."""
        command(c)
        if c['operation'] in {'clear_sold', 'relist_all'}:
            from .bulk import mutation_authorized
            return mutation_authorized(self.path, c, reconciled=True)
        if c['operation'] in {'move', 'list'}:
            from .resale import mutation_authorized
            return mutation_authorized(self.path, c, reconciled=True)
        try:
            j = Journal(self.path, readonly=True)
        except (sqlite3.Error, OSError, ValueError):
            return False
        try:
            p = c['params']
            return j.db.execute('SELECT scope,trade_id,item_id,amount,state FROM commands WHERE id=?',
                (c['id'],)).fetchone() == (scope_for(c['context']), p['trade_id'], p['item_id'], p['amount'], 'RECONCILED')
        finally:
            j.close()

    def __call__(self, c):
        command(c)
        if c['operation'] in {'clear_sold', 'relist_all'}:
            from .bulk import mutation_authorized
            return mutation_authorized(self.path, c)
        if c['operation'] in {'move', 'list'}:
            from .resale import mutation_authorized
            return mutation_authorized(self.path, c)
        if c['operation'] != 'bid':
            return False
        try:
            j = Journal(self.path, readonly=True)
        except (sqlite3.Error, OSError, ValueError):
            return False
        try:
            p, f, scope = c['params'], c['fences'], scope_for(c['context'])
            j._owner(scope, f['owner'], f['epoch'])
            from .resale import pending as pending_resales
            from .bulk import pending as pending_bulk
            if pending_resales(j, scope) or pending_bulk(j, scope):
                return False
            expected = (scope, f['owner'], f['epoch'], p['trade_id'], p['item_id'], p['definition_id'],
                        p['amount'], 'UNKNOWN', stamp(p['deadline']).isoformat(), p['status_read_id'], p['balance_read_id'])
            row = j.db.execute('SELECT scope,owner,epoch,trade_id,item_id,definition_id,amount,state,deadline,status_read_id,balance_read_id FROM commands WHERE id=?', (c['id'],)).fetchone()
            events = j.trace(scope=scope, trade_id=p['trade_id'])
            intent = [e for e in events if e['command_id'] == c['id'] and e['reason'] == 'INTENT_DURABLE']
            claim = any(e['command_id'] == c['id'] and e['reason'] == 'PENDING' for e in events)
            return (row == expected and claim and len(intent) == 1 and intent[0]['data']['cap'] == p['cap']
                    and stamp(p['deadline']) > datetime.now(timezone.utc))
        except (ValueError, KeyError, sqlite3.Error):
            return False
        finally:
            j.close()
