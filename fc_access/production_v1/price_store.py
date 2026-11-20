"""Durable native price rules: the page's own tick answers and card price limits.

The tick ladder is a market rule per game and platform, so every answer the page
gave ("one tick above 7600 is 7700") is kept without expiry and reused across
sessions. Nothing here derives a tick: entries are only ever the page's answers.
Card price limits change rarely and are kept per card for CAPS_TTL_SECONDS.
"""
from pathlib import Path
import sqlite3

CAPS_TTL_SECONDS = 86400


class PriceRuleStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS ticks_v1(game TEXT, platform TEXT, direction TEXT, value INTEGER,
                price INTEGER NOT NULL, PRIMARY KEY(game,platform,direction,value));
            CREATE TABLE IF NOT EXISTS caps_v1(game TEXT, platform TEXT, definition_id INTEGER,
                minimum INTEGER NOT NULL, maximum INTEGER NOT NULL, read_id TEXT NOT NULL,
                observed_at REAL NOT NULL, PRIMARY KEY(game,platform,definition_id));''')
        self.db.commit()

    @staticmethod
    def _valid_tick(direction, value, price):
        return direction in {'above', 'below'} and all(type(v) is int and v >= 0 for v in (value, price))

    def ticks(self, game, platform, probes):
        """Stored answers for (direction, value) probes; missing probes are absent."""
        found = {}
        for direction, value in dict.fromkeys(probes):
            row = self.db.execute('SELECT price FROM ticks_v1 WHERE game=? AND platform=? AND direction=? AND value=?',
                                  (game, platform, direction, value)).fetchone()
            if row is not None:
                found[(direction, value)] = row[0]
        return found

    def put_ticks(self, game, platform, answers):
        rows = [(game, platform, d, v, p) for (d, v), p in answers.items() if self._valid_tick(d, v, p)]
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO ticks_v1 VALUES(?,?,?,?,?)', rows)

    def sample_ticks(self, game, platform, limit=8):
        """A spread of stored answers across the price range, for the startup check."""
        rows = self.db.execute('SELECT direction,value,price FROM ticks_v1 WHERE game=? AND platform=? ORDER BY value',
                               (game, platform)).fetchall()
        if len(rows) <= limit:
            return {(d, v): p for d, v, p in rows}
        step = (len(rows) - 1) / (limit - 1)
        return {(rows[round(i*step)][0], rows[round(i*step)][1]): rows[round(i*step)][2] for i in range(limit)}

    def tick_count(self, game, platform):
        return self.db.execute('SELECT count(*) FROM ticks_v1 WHERE game=? AND platform=?', (game, platform)).fetchone()[0]

    def clear_ticks(self, game, platform):
        with self.db:
            self.db.execute('DELETE FROM ticks_v1 WHERE game=? AND platform=?', (game, platform))

    def caps(self, game, platform, definition_id, *, now):
        """(minimum, maximum, read_id) if stored within CAPS_TTL_SECONDS, else None."""
        row = self.db.execute('''SELECT minimum,maximum,read_id,observed_at FROM caps_v1
            WHERE game=? AND platform=? AND definition_id=?''', (game, platform, definition_id)).fetchone()
        if row is None or not 0 <= now - row[3] < CAPS_TTL_SECONDS:
            return None
        return row[0], row[1], row[2]

    def put_caps(self, game, platform, definition_id, minimum, maximum, read_id, *, now):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO caps_v1 VALUES(?,?,?,?,?,?,?)',
                            (game, platform, definition_id, minimum, maximum, read_id, now))

    def forget_caps(self, game, platform, definition_id):
        with self.db:
            self.db.execute('DELETE FROM caps_v1 WHERE game=? AND platform=? AND definition_id=?',
                            (game, platform, definition_id))

    def close(self):
        self.db.close()
