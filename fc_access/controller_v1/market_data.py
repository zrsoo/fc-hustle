"""Durable market price history for trend awareness.

One row per observation of a card's market:
- 'quote'  : a price search made while pricing a bid (no extra request);
- 'held'   : a price search for a card we hold (idle time, every held_interval);
- 'index'  : a price search for a recently priced card (idle time, every index_interval);
- 'final'  : the final price of an auction we bid on (no request).
Search rows store the cheapest and median buy-now of the first result page (the
21 listings EA returns), so samples from different sources are comparable.
"""
from pathlib import Path
import sqlite3
import statistics


class MarketData:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS samples_v1(definition_id INTEGER NOT NULL, at REAL NOT NULL,
                source TEXT NOT NULL, min_price INTEGER, median_price INTEGER, n INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS samples_v1_def_at ON samples_v1(definition_id, at);
            CREATE INDEX IF NOT EXISTS samples_v1_at ON samples_v1(at);''')
        self.db.commit()

    def record(self, definition_id, at, source, prices):
        prices = [p for p in prices if type(p) is int and p > 0]
        if source not in {'quote', 'held', 'index', 'final'} or type(definition_id) is not int:
            raise ValueError('invalid_market_sample')
        if not prices and source != 'held' and source != 'index':
            return
        with self.db:
            self.db.execute('INSERT INTO samples_v1 VALUES(?,?,?,?,?,?)',
                            (definition_id, at, source, min(prices) if prices else None,
                             int(statistics.median(prices)) if prices else None, len(prices)))

    def last_at(self, definition_id, sources):
        q = ','.join('?'*len(sources))
        row = self.db.execute(f'SELECT max(at) FROM samples_v1 WHERE definition_id=? AND source IN ({q})',
                              (definition_id, *sources)).fetchone()
        return row[0]

    def close(self):
        self.db.close()


def summarize(db, now, held=None):
    """Status view: sample counts, held cards against their market, and the index
    trend (median ratio of each card's latest price to its price ~6 h / ~24 h ago).
    ``db`` is an sqlite3 connection to the market data file; ``held`` maps
    definition_id -> list of our listing prices."""
    out = dict(samples_last_hour={s: n for s, n in db.execute(
        'SELECT source,count(*) FROM samples_v1 WHERE at>=? GROUP BY source', (now-3600,))},
        cards_last_day=db.execute('SELECT count(DISTINCT definition_id) FROM samples_v1 WHERE at>=?', (now-86400,)).fetchone()[0])

    def latest(d, before=None, sources=('quote', 'held', 'index')):
        q = ','.join('?'*len(sources))
        sql = f'SELECT at,min_price,median_price FROM samples_v1 WHERE definition_id=? AND min_price IS NOT NULL AND source IN ({q})'
        args = [d, *sources]
        if before is not None:
            sql += ' AND at<=?'; args.append(before)
        return db.execute(sql+' ORDER BY at DESC LIMIT 1', args).fetchone()

    trend = {}
    recent = [d for (d,) in db.execute('SELECT DISTINCT definition_id FROM samples_v1 WHERE at>=? AND min_price IS NOT NULL '
                                       "AND source IN ('quote','held','index')", (now-3600,))]
    for label, back in (('6h', 6*3600), ('24h', 24*3600)):
        ratios = []
        for d in recent:
            new = latest(d)
            old = latest(d, before=now-back)
            if new and old and now-back-old[0] <= 3*3600 and old[2]:
                ratios.append(new[2]/old[2])
        trend[label] = dict(cards=len(ratios), median_change_pct=round((statistics.median(ratios)-1)*100, 1) if ratios else None)
    out['index_trend_median_price'] = trend
    if held:
        rows = []
        for d, listed in sorted(held.items()):
            m = latest(d)
            rows.append(dict(definition_id=d, listed=sorted(listed), market_min=m[1] if m else None,
                             market_median=m[2] if m else None,
                             age_min=round((now-m[0])/60) if m else None,
                             premium_pct=round((max(listed)/m[1]-1)*100) if m and m[1] else None))
        out['held'] = rows
    return out
