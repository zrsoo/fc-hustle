"""Durable completed observations, never candidate rejection or bid authority."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

TTL_SECONDS = 86400
DEFAULT_CACHE_PATH = Path('private-captures/production-v1/completed-quotes.sqlite3')


class QuoteCache:
    def __init__(self, path=DEFAULT_CACHE_PATH):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS completed_quotes_v1(
            account TEXT, game TEXT, platform TEXT, definition_id INTEGER,
            observed_at REAL NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(account,game,platform,definition_id))''')
        self.db.commit()

    @staticmethod
    def key(context, definition_id):
        from .contracts import context as validate_context, integer
        validate_context(context); integer(definition_id, 1)
        return context['account'], context['game'], context['platform'], definition_id

    def get(self, context, definition_id, *, now, source):
        row = self.db.execute('''SELECT observed_at,payload FROM completed_quotes_v1
            WHERE account=? AND game=? AND platform=? AND definition_id=?''',
            self.key(context, definition_id)).fetchone()
        if row is None or not 0 <= now.timestamp()-row[0] < TTL_SECONDS:
            return None
        try:
            value = json.loads(row[1])
            self._completed(value)
            from .contracts import stamp
            if (self.key(context, definition_id) != tuple(value[k] for k in ('account','game','platform','definition_id')) or
                    stamp(value['observed_at']).timestamp() != row[0] or
                    value['source'] != source or value['identity_namespace'] != context['identity_namespace']):
                return None
            return deepcopy(value)
        except (ValueError, TypeError, KeyError):
            return None

    @staticmethod
    def _completed(value):
        from .contracts import Search, stamp, auction
        if (type(value) is not dict or value.get('schema') != 1 or value.get('completed') is not True or
                len(value.get('samples', [])) != 2 or
                any(type(s) is not dict or s.get('success') is not True for s in value['samples']) or
                not value.get('comparables')):
            raise ValueError('completed_two_search_quote_required')
        first_min = value['first_min']
        for sample, query in zip(value['samples'], (Search.pricing(value['definition_id']),
                                                   Search.pricing(value['definition_id'], first_min))):
            if sample['params'] != query.params():
                raise ValueError('completed_two_search_quote_required')
            stamp(sample['network_at'])
        if value['observed_at'] != value['samples'][0]['network_at']:
            raise ValueError('invalid_quote_time')
        for c in value['comparables']:
            auction(c['row']); stamp(c['network_at'])

    def put(self, context, definition_id, value):
        from .contracts import stamp
        self._completed(value)
        if (self.key(context, definition_id) != tuple(value[k] for k in ('account','game','platform','definition_id')) or
                value['identity_namespace'] != context['identity_namespace'] or value['source'] not in {'native','fixture'}):
            raise ValueError('cache_context_mismatch')
        at = stamp(value['observed_at']).timestamp()
        body = json.dumps(value, sort_keys=True, allow_nan=False)
        with self.db:
            self.db.execute('''INSERT OR REPLACE INTO completed_quotes_v1
                VALUES(?,?,?,?,?,?)''', (*self.key(context, definition_id), at, body))

    def close(self):
        self.db.close()
