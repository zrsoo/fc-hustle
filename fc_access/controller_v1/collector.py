"""Market data collection for the relist-only mode (--collect). Read-only: searches
and trade status reads, never a bid or a listing.

Four streams, all in market-data.sqlite3, run in the idle time of each hold:
- scans:  the existing held/index page samples (samples_v1), without the hourly
          market budget, over the held cards, the priced cards and the universe;
- ladder: per card about hourly, the true cheapest buy-now (searches with a
          falling max buy-now until none is cheaper) and the listings within
          +5% and +10% of it (ladder_v1);
- follow: listings sampled from every search page, and every auction a
          discovery search shows, followed with trade status reads until they
          end: sold (at what price) or expired (followed_v1);
- shadow: the discovery searches acquisition would make in each band, without
          bidding; every card they show joins the universe (universe_v1).
Times are epoch seconds.
"""
import statistics

from fc_access.production_v1.contracts import Search, stamp

LADDER_INTERVAL = 3600.0
DISCOVERY_INTERVAL = 120.0
UNIVERSE_HOURS = 24
FOLLOW_PER_PAGE = 5
LADDER_STEPS = 6
FOLLOW_GRACE = 5.0
FOLLOW_MAX_CHECKS = 6

SCHEMA = '''
CREATE TABLE IF NOT EXISTS ladder_v1(definition_id INTEGER NOT NULL, at REAL NOT NULL, page_low INTEGER,
    true_low INTEGER, steps INTEGER NOT NULL, n5 INTEGER, more5 INTEGER, n10 INTEGER, more10 INTEGER, searches INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ladder_v1_def_at ON ladder_v1(definition_id, at);
CREATE TABLE IF NOT EXISTS followed_v1(trade_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, definition_id INTEGER NOT NULL,
    source TEXT NOT NULL, band TEXT, seen_at REAL NOT NULL, expires_at REAL NOT NULL, starting_bid INTEGER,
    buy_now INTEGER, current_bid INTEGER, bid_state TEXT, page_low INTEGER, rank INTEGER, page_n INTEGER,
    status TEXT NOT NULL, final_state TEXT, final_bid INTEGER, checked_at REAL, checks INTEGER NOT NULL DEFAULT 0,
    single INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE INDEX IF NOT EXISTS followed_v1_due ON followed_v1(status, expires_at);
CREATE TABLE IF NOT EXISTS universe_v1(definition_id INTEGER PRIMARY KEY, first_seen REAL NOT NULL,
    last_seen REAL NOT NULL, seen INTEGER NOT NULL);
'''


def step(price):
    """EA's price step at or above ``price``."""
    return 50 if price < 1000 else 100 if price < 10000 else 250 if price < 50000 else 500 if price < 100000 else 1000


def below(price):
    """The highest legal price under ``price``."""
    p = price - 1
    return max(150, p - p % step(p))


def floor_tick(price):
    return max(150, price - price % step(price))


def rows_of(v, definition_id=None):
    rows = (v.get('result') or {}).get('auctions') or []
    return [r for r in rows if r.get('trade_state') == 'active' and r.get('buy_now_price') and
            (definition_id is None or r['item']['definition_id'] == definition_id)]


class Collector:
    def __init__(self, controller):
        self.c = controller
        self.db = controller.market_data.db
        self.db.executescript(SCHEMA)
        # Status reads work only for trades this page load has seen in a search; a
        # new worker may run on a reloaded page, so earlier open listings are lost
        # (reading them would fail and count as persistent read failures).
        self.db.execute("UPDATE followed_v1 SET status='lost',error='restart' WHERE status='open'")
        self.db.commit()
        self.next_discovery = 0.0
        self.band_index = 0
        self.stats = {}

    # -- helpers -------------------------------------------------------------
    def now(self):
        return self.c.now().timestamp()

    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0)+n

    def search(self, query):
        self.c.store.require_supervision()
        self.count('searches')
        return self.c.native.search(self.c.ids(), query)

    def follow(self, v, source, *, band=None, rows=None):
        """Store listings from a search page to follow until they end."""
        rows = rows if rows is not None else rows_of(v)
        if not rows: return 0
        at = stamp(v['freshness']['network_at']).timestamp() if v['freshness'].get('network_at') else self.now()
        low = min(r['buy_now_price'] for r in rows)
        ordered = sorted(rows, key=lambda r: r['buy_now_price'])
        if source != 'discovery' and len(ordered) > FOLLOW_PER_PAGE:
            k = len(ordered)-1
            ordered = [ordered[round(k*i/(FOLLOW_PER_PAGE-1))] for i in range(FOLLOW_PER_PAGE)]
        added = 0
        with self.db:
            for rank, r in enumerate(ordered):
                if r.get('expires', 0) <= 0: continue
                cur = self.db.execute('''INSERT OR IGNORE INTO followed_v1(trade_id,item_id,definition_id,source,band,seen_at,
                    expires_at,starting_bid,buy_now,current_bid,bid_state,page_low,rank,page_n,status)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open')''',
                    (r['trade_id'], r['item']['item_id'], r['item']['definition_id'], source, band, at, at+r['expires'],
                     r.get('starting_bid'), r['buy_now_price'], r.get('current_bid'), r.get('bid_state'), low,
                     sorted(x['buy_now_price'] for x in rows).index(r['buy_now_price']), len(rows)))
                added += cur.rowcount
        self.count('followed', added)
        return added

    def universe(self, definition_ids):
        now = self.now()
        with self.db:
            for d in set(definition_ids):
                self.db.execute('''INSERT INTO universe_v1 VALUES(?,?,?,1) ON CONFLICT(definition_id)
                    DO UPDATE SET last_seen=excluded.last_seen, seen=seen+1''', (d, now, now))

    # -- streams -------------------------------------------------------------
    def follow_due(self):
        """One status read for the listings that have ended. True if it read."""
        now = self.now()
        rows = self.db.execute('''SELECT trade_id,item_id,definition_id,single,checks FROM followed_v1
            WHERE status='open' AND expires_at+?<=? ORDER BY expires_at LIMIT 10''', (FOLLOW_GRACE, now)).fetchall()
        if not rows: return False
        if any(r[3] for r in rows): rows = [next(r for r in rows if r[3])]
        targets = [dict(trade_id=t, item_id=i, definition_id=d) for t, i, d, _, _ in rows]
        self.c.store.require_supervision()
        self.count('status_reads')
        try:
            v = self.c.adapter.status_batch(self.c.ids(), targets)
            ok = v['success']
        except Exception as error:
            v, ok = None, False; err = type(error).__name__
        else:
            err = v.get('error') if not ok else None
        with self.db:
            if not ok:
                if len(targets) > 1:
                    # One trade the page no longer knows fails the batch: read singly.
                    self.db.executemany('UPDATE followed_v1 SET single=1 WHERE trade_id=?', [(t['trade_id'],) for t in targets])
                else:
                    self.db.execute("UPDATE followed_v1 SET status='lost',error=?,checked_at=? WHERE trade_id=?",
                                    (str(err)[:60], now, targets[0]['trade_id']))
                    self.count('lost')
                return True
            seen = {r['trade_id']: r for r in v['auctions']}
            for t, _, _, _, checks in rows:
                r = seen.get(t)
                if r is None:
                    self.db.execute("UPDATE followed_v1 SET status='missing',checked_at=?,checks=checks+1 WHERE trade_id=?", (now, t))
                    self.count('missing')
                elif r['trade_state'] == 'closed' and (r.get('current_bid') or 0) > 0:
                    self.db.execute('''UPDATE followed_v1 SET status='sold',final_state='closed',final_bid=?,checked_at=?,
                        checks=checks+1 WHERE trade_id=?''', (r['current_bid'], now, t))
                    self.count('sold')
                elif r['trade_state'] in ('expired', 'closed'):
                    self.db.execute('''UPDATE followed_v1 SET status='expired',final_state=?,final_bid=?,checked_at=?,
                        checks=checks+1 WHERE trade_id=?''', (r['trade_state'], r.get('current_bid'), now, t))
                    self.count('expired')
                elif checks+1 >= FOLLOW_MAX_CHECKS:
                    self.db.execute("UPDATE followed_v1 SET status='stale',checked_at=?,checks=checks+1 WHERE trade_id=?", (now, t))
                else:
                    left = r.get('expires') if (r.get('expires') or 0) > 0 else 15
                    self.db.execute('UPDATE followed_v1 SET expires_at=?,checked_at=?,checks=checks+1 WHERE trade_id=?',
                                    (now+left, now, t))
        return True

    def discovery(self):
        """One band's discovery search, as acquisition would make it, without bidding."""
        bands = list(self.c.config.bands)
        band = bands[self.band_index % len(bands)]; self.band_index += 1
        if self.band_index % len(bands) == 0: self.next_discovery = self.c.clock()+DISCOVERY_INTERVAL
        page = 0
        while True:
            page += 1
            v = self.search(Search.discovery(page=page, max_bid=band[0], min_buy=band[1]))
            rows = rows_of(v)
            self.follow(v, 'discovery', band=f'{band[0]}:{band[1]}', rows=rows)
            self.universe(r['item']['definition_id'] for r in rows)
            if (any(r['expires'] > self.c.config.min_seconds_left for r in rows) or
                    page >= self.c.config.discovery_pages or len(rows) < 21): break

    def targets(self):
        """Due scans and ladders: held cards, priced cards and the universe."""
        now = self.now(); held = set()
        row = self.c.store.db.execute("SELECT result FROM c4_commands WHERE state='DONE' AND "
            "json_extract(body,'$.operation')='transfer_list' ORDER BY rowid DESC LIMIT 1").fetchone()
        if row and row[0]:
            import json
            held = {r['item']['definition_id'] for r in (json.loads(row[0]).get('result') or {}).get('auctions') or []}
        cards = set()
        ctx = self.c.adapter.context
        cards |= {d for (d,) in self.c.pricing.cache.db.execute(
            'SELECT definition_id FROM completed_quotes_v1 WHERE account=? AND game=? AND platform=?',
            (ctx['account'], ctx['game'], ctx['platform']))}
        cards |= {d for (d,) in self.db.execute('SELECT definition_id FROM universe_v1 WHERE last_seen>=?', (now-UNIVERSE_HOURS*3600,))}
        md = self.c.market_data
        due = []
        for d in sorted(held | cards):
            last_ladder = self.db.execute('SELECT max(at) FROM ladder_v1 WHERE definition_id=?', (d,)).fetchone()[0]
            if last_ladder is None or now-last_ladder >= LADDER_INTERVAL:
                due.append((last_ladder or 0, d, 'ladder', 'held' if d in held else 'index'))
                continue
            src = 'held' if d in held else 'index'
            last = md.last_at(d, ('held',) if src == 'held' else ('quote', 'held', 'index'))
            interval = self.c.config.market_held_interval if src == 'held' else self.c.config.market_index_interval
            if last is None or now-last >= interval: due.append((last or 0, d, 'scan', src))
        due.sort()
        return [(d, kind, src) for _, d, kind, src in due]

    def scan(self, d, source):
        v = self.search(Search.pricing(d))
        self.c._record_search(d, v, source)
        self.follow(v, source, rows=rows_of(v, d))
        self.count('scans')

    def ladder(self, d, source):
        """True cheapest buy-now of a card, and how many listings sit within +5%/+10%."""
        searches = self.stats.get('searches', 0)
        v = self.search(Search.pricing(d))
        self.c._record_search(d, v, source)
        rows = rows_of(v, d); self.follow(v, source, rows=rows)
        page_low = min((r['buy_now_price'] for r in rows), default=None)
        low, steps = page_low, 0
        while low is not None and steps < LADDER_STEPS and low > 150:
            steps += 1
            cheaper = rows_of(self.search(Search.pricing(d, max_buy=below(low))), d)
            if not cheaper: break
            low = min(r['buy_now_price'] for r in cheaper)
        depth = {}
        for pct in (5, 10):
            if low is None: depth[pct] = (None, None); continue
            w = self.search(Search.pricing(d, max_buy=floor_tick(int(low*(100+pct)/100))))
            n = len(rows_of(w, d))
            depth[pct] = (n, 1 if (w.get('coverage') or {}).get('has_more') or n >= 21 else 0)
        with self.db:
            self.db.execute('INSERT INTO ladder_v1 VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (d, self.now(), page_low, low, steps, depth[5][0], depth[5][1], depth[10][0], depth[10][1],
                             self.stats.get('searches', 0)-searches))
        self.count('ladders')

    # -- loop ----------------------------------------------------------------
    def run(self, bid, until, *, searches=True):
        """Collect until ``until`` (monotonic clock). Status reads always; searches
        only when allowed (not throttled). Stops searching on an EA refusal."""
        self.stats = {}
        error = None; queue = None
        try:
            while self.c.clock() < until:
                self.c.store.require_supervision()
                if self.follow_due(): continue
                if not searches: break
                if self.c.clock() >= self.next_discovery:
                    self.discovery(); continue
                if queue is None: queue = self.targets()
                if not queue: break
                d, kind, src = queue.pop(0)
                if kind == 'ladder': self.ladder(d, src)
                else: self.scan(d, src)
        except ValueError as e:
            if type(e).__name__ == 'SupervisionLost': raise
            if str(e) == 'service_failed':
                # EA refused a search (429): the usual search pause applies.
                self.c.search_hold_until = self.c.clock()+self.c.config.throttle_pause
                self.c.journal.metric(bid, 'SEARCH_THROTTLED', pause=self.c.config.throttle_pause, source='collect')
            error = 'ValueError:'+str(e)[:40]
        except Exception as e:
            if type(e).__name__ == 'SupervisionLost': raise
            error = type(e).__name__
        if self.stats or error:
            self.c.journal.metric(bid, 'COLLECT', error=error, **self.stats)
        return self.stats
