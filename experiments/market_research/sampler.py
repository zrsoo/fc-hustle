"""Read-only transfer-market research sampler (strategy study, 2026-11-19).

Uses the reviewed production extension bridge with a separate research database.
Operations: search (discovery/pricing), status_batch and balance. It never bids,
lists, moves, clears or relists. The controller must be stopped (shared locks).

Jobs, one paced EA request at a time:
  status     tracked auctions/listings shortly after their deadline (outcomes)
  discovery  rotating (max_bid, min_buy) bands, page 1 = auctions ending soonest
  pricing    lowest-BIN market price per definition (2-3 searches, 45 min cache)
  snipe      watch-list definitions searched with max_buy below market price
  hit        status re-read of a snipe hit a few seconds later (was it taken?)

Recovery: on repeated failures re-attach with a higher owner epoch; on auth
failures run the normal official sign-in recovery (recovery.DocumentRecovery).
A security challenge stops sampling and is left to the user.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import random
import secrets
import sqlite3
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = ROOT/'private-captures/market-research'
CONTROLLER_DB = ROOT/'private-captures/controller-v1/controller.sqlite'
CONTEXT = ROOT/'private-captures/controller-v1/public-context.json'
RECOVERY = ROOT/'private-captures/controller-v1/recovery.json'

# (name, max_bid, min_buy); page 1 = the 21 matching auctions ending soonest.
BANDS = [
    ('any', 10_000_000, 200),
    ('b1k_m11k', 1000, 11000),
    ('b3k_m20k', 3000, 20000),
    ('b5k_m30k', 5000, 30000),
    ('b8k_m40k', 8000, 40000),
    ('b15k_m60k', 15000, 60000),
    ('b20k_m100k', 20000, 100000),
    ('b40k_m150k', 40000, 150000),
]
# (b400_m3k and b200_m1k ran 13:13-17:25 UTC: sub-1k junk, zero profit at any margin.)
TRACK_HORIZON = 900        # track auctions ending within 15 minutes of discovery
STATUS_DELAY = 15          # seconds after the deadline before the outcome read
PRICE_TTL = 45*60
SNIPE_SET = 40


def utcnow():
    return datetime.now(timezone.utc)


def iso(v):
    return v.isoformat()


def tick(v):
    return 50 if v < 1000 else 100 if v < 10000 else 250 if v < 50000 else 500 if v < 100000 else 1000


def floor_tick(v):
    v = int(v)
    if v < 150: return 0
    return v - v % tick(v)


SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS reads(id TEXT PRIMARY KEY, at TEXT, job TEXT, op TEXT, params TEXT, ok INTEGER,
  error TEXT, network_at TEXT, n INTEGER, elapsed REAL, epoch INTEGER);
CREATE TABLE IF NOT EXISTS rows(read_id TEXT, trade_id TEXT, item_id TEXT, definition_id INTEGER,
  starting_bid INTEGER, current_bid INTEGER, bin INTEGER, expires INTEGER, bid_state TEXT, trade_state TEXT,
  last_sale INTEGER, network_at TEXT);
CREATE INDEX IF NOT EXISTS rows_trade ON rows(trade_id);
CREATE INDEX IF NOT EXISTS rows_def ON rows(definition_id);
CREATE INDEX IF NOT EXISTS rows_read ON rows(read_id);
CREATE TABLE IF NOT EXISTS track(trade_id TEXT PRIMARY KEY, item_id TEXT, definition_id INTEGER, kind TEXT,
  deadline TEXT, source_read TEXT, band TEXT, epoch INTEGER, done INTEGER DEFAULT 0, outcome TEXT);
CREATE TABLE IF NOT EXISTS market(definition_id INTEGER, at TEXT, price INTEGER, second INTEGER, count INTEGER,
  first_min INTEGER, searches INTEGER);
CREATE INDEX IF NOT EXISTS market_def ON market(definition_id, at);
CREATE TABLE IF NOT EXISTS hits(read_id TEXT, at TEXT, definition_id INTEGER, trade_id TEXT, bin INTEGER,
  market INTEGER, max_buy INTEGER, expires INTEGER, followup TEXT);
CREATE TABLE IF NOT EXISTS events(at TEXT, kind TEXT, body TEXT);
'''


class Throttled(Exception):
    pass


class Research:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def event(self, kind, **body):
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?)', (iso(utcnow()), kind, json.dumps(body, default=str)))
        print(iso(utcnow()), kind, json.dumps(body, default=str), flush=True)


class Bridge:
    """Owned read-only attachment to the reviewed extension (controller wiring)."""
    def __init__(self, port, spacing, epoch_floor):
        from fc_access.production_v1.contracts import context
        self.scope = context(json.loads(CONTEXT.read_text()))
        self.port, self.spacing, self.epoch_floor = port, spacing, epoch_floor
        self.stack = ExitStack()
        self.server = self.thread = self.adapter = None
        self.epoch = None

    def start(self):
        from fc_access.actors_v1.locking import process_lock
        from fc_access.controller_v1.__main__ import guard_paths
        from fc_access.controller_v1.server import Server
        BASE.mkdir(parents=True, exist_ok=True)
        database = BASE/'bridge.sqlite'
        for lock in guard_paths(ROOT, self.scope, database, self.port):
            self.stack.enter_context(process_lock(lock))
        self.server = Server(database, self.port, write_authority=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def previous_epoch(self):
        best = 0
        for path, db in ((CONTROLLER_DB, None), (BASE/'bridge.sqlite', self.server.store.db)):
            try:
                conn = db or sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
                row = conn.execute("SELECT value FROM c4_meta WHERE key='peer'").fetchone()
                if row: best = max(best, json.loads(row[0])['fences']['epoch'])
            except Exception:
                pass
        return best

    def attach(self):
        from fc_access.controller_v1.executor import ControllerExecutor, SerializedExecutor
        from fc_access.controller_v1.adapter import ControllerAdapter
        self.epoch = max(self.previous_epoch()+1, self.epoch_floor)
        executor = SerializedExecutor(ControllerExecutor(self.port), spacing=self.spacing)
        self.adapter = ControllerAdapter(executor, context=self.scope, owner=secrets.token_hex(16), epoch=self.epoch)
        return self.epoch

    def close(self):
        if self.server:
            self.server.shutdown(); self.thread.join(5); self.server.server_close()
        self.stack.close()


class Sampler:
    def __init__(self, a):
        self.a = a
        self.r = Research(BASE/'research.sqlite')
        self.bridge = Bridge(a.port, a.spacing, a.epoch_floor)
        self.prices = {}            # definition_id -> (at_epoch_seconds, price)
        self.second = {}            # definition_id -> second-lowest BIN (robust reference)
        for d, at, price, second in self.r.db.execute('SELECT definition_id, at, price, second FROM market ORDER BY at'):
            self.prices[d] = (datetime.fromisoformat(at).timestamp(), price)  # survives restarts
            self.second[d] = second
        self.price_queue = {}       # definition_id -> priority count
        self.band_i = 0
        self.last_discovery = 0
        self.snipe_i = 0
        self.failures = 0
        self.auth_failures = 0
        self.stop_at = time.time()+a.hours*3600
        self.pending_hits = []      # (due, row)
        self.counts = {}
        self.cooldown_until = 0     # EA search throttle (HTTP 429 -> service_failed)
        self.throttled_at = None

    # ---- I/O ---------------------------------------------------------------
    def record(self, cid, job, op, params, v=None, error=None, elapsed=None):
        rows = []
        net = None
        if v is not None:
            if op == 'search':
                net = v['freshness']['network_at']; rows = v['result']['auctions']
            else:
                net = v.get('network_at'); rows = v.get('auctions') or []
        with self.r.db:
            self.r.db.execute('INSERT INTO reads VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (cid, iso(utcnow()), job, op, json.dumps(params), int(error is None), error, net, len(rows), elapsed, self.bridge.epoch))
            self.r.db.executemany('INSERT INTO rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
                (cid, x['trade_id'], x['item']['item_id'], x['item']['definition_id'], x.get('starting_bid'),
                 x.get('current_bid'), x.get('buy_now_price'), x.get('expires'), x.get('bid_state'),
                 x.get('trade_state'), x['item'].get('last_sale_price'), net) for x in rows])
        self.counts[job] = self.counts.get(job, 0)+1
        return rows, net

    def search(self, job, query):
        cid = secrets.token_hex(16); t = time.monotonic()
        try:
            v = self.bridge.adapter.native.search(cid, query)
        except Exception as e:
            reason = self.reason(e)
            self.record(cid, job, 'search', query.params(), error=reason, elapsed=time.monotonic()-t)
            if reason == 'service_failed':
                # EA search throttle (429). Not a bridge fault: pause searches, no re-attach.
                if self.throttled_at is None:
                    self.throttled_at = time.time(); self.r.event('SEARCH_THROTTLED')
                self.cooldown_until = time.time()+900
                raise Throttled()
            raise
        if self.throttled_at is not None:
            self.r.event('SEARCH_THROTTLE_CLEARED', minutes=round((time.time()-self.throttled_at)/60, 1))
            self.throttled_at = None
        self.ok()
        return self.record(cid, job, 'search', query.params(), v, elapsed=time.monotonic()-t)

    def status(self, job, targets):
        cid = secrets.token_hex(16); t = time.monotonic()
        try:
            v = self.bridge.adapter.status_batch(cid, targets)
        except Exception as e:
            self.record(cid, job, 'status_batch', {'n': len(targets)}, error=self.reason(e), elapsed=time.monotonic()-t)
            raise
        if not v.get('success'):
            self.record(cid, job, 'status_batch', {'n': len(targets)}, error=str(v.get('error')), elapsed=time.monotonic()-t)
            if v.get('error') in {'unauthenticated', 'persona_unverified'} or 401 in [n.get('status') for n in v.get('network') or []]:
                self.auth_failures += 1
            return None, None
        self.ok()
        return self.record(cid, job, 'status_batch', {'n': len(targets)}, v, elapsed=time.monotonic()-t)

    def reason(self, e):
        text = str(e) if isinstance(e, ValueError) else type(e).__name__
        if text in {'unauthenticated', 'persona_unverified'}: self.auth_failures += 1
        return text[:80]

    def ok(self):
        self.failures = 0; self.auth_failures = 0
        n = self.bridge.adapter
        # Bound in-memory evidence maps; everything needed is in research.sqlite.
        if len(n.native.commands) > 200:
            n.native.commands.clear(); n.native.responses.clear(); n.commands.clear(); n.responses.clear()

    # ---- jobs --------------------------------------------------------------
    def due_status(self):
        cut = iso(utcnow()-timedelta(seconds=STATUS_DELAY))
        rows = self.r.db.execute('SELECT trade_id,item_id,definition_id,kind FROM track WHERE done=0 AND deadline<=? AND epoch=? '
                                 'ORDER BY deadline LIMIT 10', (cut, self.bridge.epoch)).fetchall()
        if len(rows) < 8:
            # Fill batches: outcomes are final, so waiting up to a minute costs nothing.
            oldest = self.r.db.execute('SELECT min(deadline) FROM track WHERE done=0 AND epoch=?', (self.bridge.epoch,)).fetchone()[0]
            if oldest and oldest > iso(utcnow()-timedelta(seconds=STATUS_DELAY+60)): return []
        return rows

    def job_status(self, rows):
        targets = [dict(trade_id=t, item_id=i, definition_id=d) for t, i, d, _ in rows]
        try:
            got, _ = self.status('status', targets)
        except Exception:
            with self.r.db:
                for t, *_ in rows:
                    self.r.db.execute("UPDATE track SET done=1, outcome='batch_error' WHERE trade_id=? AND done=0", (t,))
            raise
        with self.r.db:
            if got is None:
                # A failed batch can be one unknown/vanished identity; retry singly once.
                for t, *_ in rows:
                    self.r.db.execute('UPDATE track SET done=done+1, outcome=? WHERE trade_id=? AND done=0', ('batch_failed', t))
            else:
                seen = {x['trade_id']: x for x in got}
                for t, *_ in rows:
                    x = seen.get(t)
                    if x and x['trade_state'] == 'active' and 0 <= x['expires'] <= 120:
                        # A late bid extended the auction: read it again after the new end.
                        self.r.db.execute('UPDATE track SET deadline=?, outcome=? WHERE trade_id=?',
                            (iso(utcnow()+timedelta(seconds=x['expires']+5)), json.dumps(dict(extended=x['current_bid'])), t))
                        continue
                    self.r.db.execute('UPDATE track SET done=2, outcome=? WHERE trade_id=?',
                        (json.dumps(None if x is None else dict(ts=x['trade_state'], bs=x['bid_state'], cb=x['current_bid'], exp=x['expires'])), t))

    def job_retry_single(self):
        row = self.r.db.execute("SELECT trade_id,item_id,definition_id,kind FROM track WHERE done=1 AND epoch=? LIMIT 1",
                                (self.bridge.epoch,)).fetchone()
        if not row: return False
        try:
            got, _ = self.status('status_single', [dict(trade_id=row[0], item_id=row[1], definition_id=row[2])])
        except Exception:
            with self.r.db:
                self.r.db.execute("UPDATE track SET done=2, outcome='\"error\"' WHERE trade_id=?", (row[0],))
            raise
        with self.r.db:
            x = got[0] if got else None
            self.r.db.execute('UPDATE track SET done=2, outcome=? WHERE trade_id=?',
                (json.dumps('unavailable' if got is None else None if x is None else dict(ts=x['trade_state'], bs=x['bid_state'], cb=x['current_bid'], exp=x['expires'])), row[0]))
        return True

    def track(self, rows, net, kind, band, read_id, horizon):
        at = datetime.fromisoformat(net.replace('Z', '+00:00'))
        with self.r.db:
            for x in rows:
                if x['trade_state'] != 'active' or not 0 < x['expires'] <= horizon: continue
                self.r.db.execute('INSERT OR IGNORE INTO track(trade_id,item_id,definition_id,kind,deadline,source_read,band,epoch) VALUES (?,?,?,?,?,?,?,?)',
                    (x['trade_id'], x['item']['item_id'], x['item']['definition_id'], kind,
                     iso(at+timedelta(seconds=x['expires'])), read_id, band, self.bridge.epoch))

    def track_listings(self, rows, d):
        """Sell-through: re-read the 3 cheapest BIN listings ~10 minutes later
        (closed = bought; listings cannot be withdrawn)."""
        last = self.r.db.execute("SELECT network_at FROM rows WHERE definition_id=? ORDER BY rowid DESC LIMIT 1", (d,)).fetchone()
        if not last or not last[0]: return
        at = datetime.fromisoformat(last[0].replace('Z', '+00:00'))
        live = sorted((x for x in rows if x['trade_state'] == 'active' and x['buy_now_price'] and x['expires'] > 90
                       and (x['starting_bid'], x['buy_now_price']) != (600, 10000)), key=lambda x: x['buy_now_price'])[:3]
        read_id = self.r.db.execute('SELECT id FROM reads ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        with self.r.db:
            for x in live:
                wait = min(x['expires']-45, 600)
                self.r.db.execute('INSERT OR IGNORE INTO track(trade_id,item_id,definition_id,kind,deadline,source_read,band,epoch) VALUES (?,?,?,?,?,?,?,?)',
                    (x['trade_id'], x['item']['item_id'], d, 'listing', iso(at+timedelta(seconds=wait)), read_id, str(wait), self.bridge.epoch))

    def job_discovery(self):
        from fc_access.production_v1.contracts import Search
        name, max_bid, min_buy = BANDS[self.band_i % len(BANDS)]
        self.band_i += 1
        rows, net = self.search('discovery', Search.discovery(page=1, max_bid=max_bid, min_buy=min_buy))
        read_id = self.r.db.execute('SELECT id FROM reads ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        self.track(rows, net, 'auction', name, read_id, TRACK_HORIZON)
        now = time.time()
        for x in rows:
            d = x['item']['definition_id']
            if (d not in self.prices or now-self.prices[d][0] > PRICE_TTL):
                self.price_queue[d] = self.price_queue.get(d, 0)+1

    def job_price(self, d):
        from fc_access.production_v1.contracts import Search
        self.price_queue.pop(d, None)
        searches = 1
        rows, net = self.search('pricing', Search.pricing(d))
        bins = sorted(x['buy_now_price'] for x in rows if x['trade_state'] == 'active' and x['buy_now_price']
                      and (x['starting_bid'], x['buy_now_price']) != (600, 10000))
        if not bins:
            with self.r.db: self.r.db.execute('INSERT INTO market VALUES (?,?,?,?,?,?,?)', (d, iso(utcnow()), None, None, 0, None, searches))
            self.prices[d] = (time.time(), None); return
        first = bins[0]
        if first >= 1000:
            # Per-card auction outcomes: this card's listings ending within 5 minutes.
            self.track(rows, net, 'auction', 'card', self.r.db.execute('SELECT id FROM reads ORDER BY rowid DESC LIMIT 1').fetchone()[0], 300)
        if first <= 250:  # at the price floor; a second search adds nothing
            with self.r.db:
                self.r.db.execute('INSERT INTO market VALUES (?,?,?,?,?,?,?)', (d, iso(utcnow()), first, bins[1] if len(bins) > 1 else None, len(bins), first, searches))
            self.prices[d] = (time.time(), first); return
        rows2, _ = self.search('pricing', Search.pricing(d, first)); searches += 1
        b2 = sorted(x['buy_now_price'] for x in rows2 if x['trade_state'] == 'active' and x['buy_now_price']
                    and (x['starting_bid'], x['buy_now_price']) != (600, 10000))
        if len(rows2) >= 21 and b2 and b2[0] > 200:
            below = floor_tick(b2[0]-1)
            if below >= 200:
                rows3, _ = self.search('pricing', Search.pricing(d, below)); searches += 1
                b2 = sorted(set(b2) | {x['buy_now_price'] for x in rows3 if x['trade_state'] == 'active' and x['buy_now_price']})
        b2 = b2 or bins
        price, second = b2[0], (b2[1] if len(b2) > 1 else None)
        self.track_listings(rows2 or rows, d)
        with self.r.db:
            self.r.db.execute('INSERT INTO market VALUES (?,?,?,?,?,?,?)', (d, iso(utcnow()), price, second, len(b2), first, searches))
        self.prices[d] = (time.time(), price); self.second[d] = second

    def snipe_set(self):
        if time.time()-getattr(self, '_watch_at', 0) < 120: return self._watch
        self._watch, self._watch_at = self._snipe_set(), time.time()
        return self._watch

    def _snipe_set(self):
        # Most frequently listed definitions with a known market price in 1.5k..150k.
        rows = self.r.db.execute('''SELECT r.definition_id, count(DISTINCT r.trade_id) c FROM rows r JOIN reads x ON x.id=r.read_id
            WHERE x.job IN ('pricing','discovery') GROUP BY r.definition_id ORDER BY c DESC LIMIT 400''').fetchall()
        out = []
        for d, _ in rows:
            p = self.prices.get(d)
            # From 18:30 UTC: high-value cards only (fresh-underprice study).
            if p and p[1] and 10000 <= p[1] <= 200000: out.append(d)
            if len(out) >= SNIPE_SET: break
        return out

    def job_snipe(self, watch):
        from fc_access.production_v1.contracts import Search
        d = watch[self.snipe_i % len(watch)]; self.snipe_i += 1
        price = self.prices[d][1]
        second = self.second.get(d)
        # Robust reference: the second-lowest BIN (an underpriced lowest is the target, not the value).
        if second and price <= second <= price*1.1: price = second
        # Buy price at which a resale at market clears 5% tax plus >= ~4% / 200 margin.
        max_buy = floor_tick(price*0.95-max(300, price*0.03))
        if max_buy < 200: return
        rows, net = self.search('snipe', Search.pricing(d, max_buy))
        read_id = self.r.db.execute('SELECT id FROM reads ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        hits = [x for x in rows if x['trade_state'] == 'active' and x['buy_now_price'] and x['buy_now_price'] <= max_buy
                and (x['starting_bid'], x['buy_now_price']) != (600, 10000)]
        with self.r.db:
            for x in hits:
                self.r.db.execute('INSERT INTO hits VALUES (?,?,?,?,?,?,?,?,?)', (read_id, iso(utcnow()), d, x['trade_id'],
                    x['buy_now_price'], price, max_buy, x['expires'], None))
        for x in hits[:10]:
            self.pending_hits.append((time.time()+3, x))
        if hits:
            # The cheapest listings found below market usually mean the price moved: refresh it soon.
            self.prices[d] = (0, price)

    def job_hits(self):
        due = [h for h in self.pending_hits if h[0] <= time.time()][:10]
        if not due: return False
        self.pending_hits = [h for h in self.pending_hits if h not in due]
        targets = [dict(trade_id=x['trade_id'], item_id=x['item']['item_id'], definition_id=x['item']['definition_id']) for _, x in due]
        try:
            got, _ = self.status('hit', targets)
        except Exception:
            got = None
            raise
        finally:
            if got is None:
                with self.r.db:
                    for _, x in due:
                        self.r.db.execute("UPDATE hits SET followup='\"unavailable\"' WHERE trade_id=? AND followup IS NULL", (x['trade_id'],))
        seen = {x['trade_id']: x for x in got or []}
        with self.r.db:
            for _, x in due:
                y = seen.get(x['trade_id'])
                self.r.db.execute('UPDATE hits SET followup=? WHERE trade_id=? AND followup IS NULL', (json.dumps(
                    'unavailable' if got is None else None if y is None else dict(ts=y['trade_state'], bs=y['bid_state'], cb=y['current_bid'], exp=y['expires'])), x['trade_id']))
        return True

    def job_balance(self):
        cid = secrets.token_hex(16)
        v = self.bridge.adapter.read(cid, 'balance')
        self.r.event('BALANCE', credits=v.get('credits'), success=v.get('success'))

    # ---- loop --------------------------------------------------------------
    def probe(self):
        """--until-clear: one discovery search every 10 minutes; exit when EA accepts one."""
        from fc_access.production_v1.contracts import Search
        if time.time() < self.cooldown_until:
            time.sleep(min(30, self.cooldown_until-time.time())); return
        try:
            self.search('probe', Search.discovery(page=1, max_bid=1000, min_buy=11000))
        except Throttled:
            self.cooldown_until = time.time()+600; return
        self.r.event('SEARCH_OK'); raise SystemExit(0)

    def step(self):
        if self.a.until_clear: return self.probe()
        if self.job_hits(): return
        rows = self.due_status()
        if rows: return self.job_status(rows)
        if self.job_retry_single(): return
        now = time.time()
        if now < self.cooldown_until:
            time.sleep(min(30, self.cooldown_until-now)); return
        if self.throttled_at is not None:
            self.last_discovery = now; return self.job_discovery()   # single probe search
        if now-self.last_discovery >= self.a.discovery_every:
            self.last_discovery = now; return self.job_discovery()
        # Stale prices for the snipe set first, then queued discovery definitions.
        watch = self.snipe_set()
        stale = [d for d in watch if now-self.prices[d][0] > PRICE_TTL]
        if stale and random.random() < .6: return self.job_price(stale[0])
        if self.price_queue and (not watch or random.random() < .45):
            d = max(self.price_queue, key=self.price_queue.get); return self.job_price(d)
        if watch: return self.job_snipe(watch)
        if self.price_queue:
            d = max(self.price_queue, key=self.price_queue.get); return self.job_price(d)
        self.last_discovery = now; return self.job_discovery()

    def recover(self):
        from fc_access.controller_v1.recovery import DocumentRecovery
        from fc_access.controller_v1.measures import recovery_account
        if self.auth_failures:
            self.r.event('RELOGIN_STARTED', auth_failures=self.auth_failures)
            result = DocumentRecovery(recovery_account(RECOVERY)).run()
            self.r.event('RELOGIN_RESULT', outcome=result.get('outcome'), reason=result.get('reason'))
            if result.get('outcome') == 'CHALLENGE':
                self.r.event('USER_SECURITY_CHALLENGE'); raise SystemExit(3)
        for attempt in range(3):
            try:
                epoch = self.bridge.attach(); self.r.event('ATTACHED', epoch=epoch)
                self.failures = 0; self.auth_failures = 0
                with self.r.db:  # page reload forgets known trades; old tracks cannot be status-read
                    self.r.db.execute("UPDATE track SET done=3, outcome='epoch_lost' WHERE done<2 AND epoch<?", (epoch,))
                self.pending_hits = []
                return
            except Exception as e:
                self.r.event('ATTACH_FAILED', attempt=attempt, error=self.reason(e))
                time.sleep(30)
        # Detached extension or signed-out page: walk the normal sign-in once.
        self.auth_failures = max(self.auth_failures, 1)
        raise RuntimeError('attach_failed')

    def run(self):
        if sys.platform == 'win32':
            # Per-process request (like a media player); released when the process exits.
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # CONTINUOUS | SYSTEM_REQUIRED
        self.bridge.start()
        self.r.event('START', hours=self.a.hours, spacing=self.a.spacing)
        try:
            self.recover()
            try: self.job_balance()
            except Exception as e: self.r.event('BALANCE_FAILED', error=self.reason(e))
            last_report = time.time()
            while time.time() < self.stop_at and not (BASE/'STOP').exists():
                try:
                    self.step()
                except SystemExit:
                    raise
                except Throttled:
                    self.failures = 0
                except Exception as e:
                    self.failures += 1
                    if self.failures in (1, 3, 6) or self.failures % 20 == 0:
                        self.r.event('STEP_FAILED', failures=self.failures, auth=self.auth_failures, error=self.reason(e))
                    if self.failures >= 6 or self.auth_failures >= 2:
                        try: self.recover()
                        except SystemExit: raise
                        except Exception:
                            try: self.recover()
                            except SystemExit: raise
                            except Exception as e2:
                                self.r.event('RECOVERY_FAILED', error=self.reason(e2)); time.sleep(120)
                    else:
                        time.sleep(2)
                if time.time()-last_report > 300:
                    last_report = time.time()
                    self.r.event('PROGRESS', counts=self.counts, priced=len(self.prices), queue=len(self.price_queue),
                                 tracked=self.r.db.execute('SELECT count(*) FROM track').fetchone()[0])
        finally:
            self.r.event('STOP', counts=self.counts)
            self.bridge.close()


def summary():
    db = sqlite3.connect((BASE/'research.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
    q = lambda s, *a: db.execute(s, a).fetchall()
    out = dict(
        reads=q("SELECT job, count(*), sum(ok) FROM reads GROUP BY job"),
        last_read=q("SELECT max(at) FROM reads")[0][0],
        last_errors=q("SELECT at, job, error FROM reads WHERE ok=0 ORDER BY rowid DESC LIMIT 5"),
        tracked=q("SELECT kind, done, count(*) FROM track GROUP BY kind, done"),
        priced=q("SELECT count(DISTINCT definition_id) FROM market")[0][0],
        hits=q("SELECT count(*), count(DISTINCT trade_id) FROM hits")[0],
        events=q("SELECT at, kind, body FROM events ORDER BY rowid DESC LIMIT 6"),
    )
    print(json.dumps(out, indent=1, default=str))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--hours', type=float, default=18)
    r.add_argument('--spacing', type=float, default=4.0)
    r.add_argument('--discovery-every', type=float, default=75)
    r.add_argument('--port', type=int, default=8784)
    r.add_argument('--epoch-floor', type=int, default=1)
    r.add_argument('--until-clear', action='store_true', help='probe searches only; exit once EA accepts one')
    sub.add_parser('summary')
    a = p.parse_args()
    if a.cmd == 'summary': return summary()
    BASE.mkdir(parents=True, exist_ok=True)
    try: (BASE/'STOP').unlink()
    except FileNotFoundError: pass
    Sampler(a).run()


if __name__ == '__main__':
    main()
