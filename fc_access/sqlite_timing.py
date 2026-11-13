"""Statement/transaction wall time only; never records SQL or parameter values."""
import sqlite3
import time


class TimedCursor(sqlite3.Cursor):
    def execute(self, *args, **kwargs):
        return self.connection._timed(super().execute, *args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self.connection._timed(super().executemany, *args, **kwargs)

    def fetchone(self):
        return self.connection._timed(super().fetchone)

    def fetchall(self):
        return self.connection._timed(super().fetchall)

    def fetchmany(self, *args):
        return self.connection._timed(super().fetchmany, *args)

    def __next__(self):
        return self.connection._timed(super().__next__)


class TimedConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        self.sqlite_ms = 0.0
        super().__init__(*args, **kwargs)

    def _timed(self, method, *args, **kwargs):
        start = time.perf_counter()
        try:
            return method(*args, **kwargs)
        finally:
            self.sqlite_ms += (time.perf_counter()-start)*1000

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self.cursor().executemany(*args, **kwargs)

    def cursor(self, factory=TimedCursor):
        return super().cursor(factory)

    def executescript(self, *args, **kwargs):
        return self._timed(super().executescript, *args, **kwargs)

    def commit(self):
        return self._timed(super().commit)

    def rollback(self):
        return self._timed(super().rollback)

    def __exit__(self, *args):
        return self._timed(super().__exit__, *args)
