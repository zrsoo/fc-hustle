"""Pinned loopback delivery service; no native work without an explicit /run.

Run: python -m fc_access.production_v1.server --database production.sqlite
The service has no lifetime/read-count/player ceiling and no write-enable flag.
"""
import argparse
import hashlib
import json
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .contracts import VERSION, fields
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
EXTENSION_PATH = str((ROOT/'browser/production-v1').resolve())
EXTENSION_PATH = EXTENSION_PATH[0].upper()+EXTENSION_PATH[1:]
EXTENSION_ID = ''.join(chr(97+int(n, 16)) for n in hashlib.sha256(EXTENSION_PATH.encode('utf-16-le')).hexdigest()[:32])


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, database, port=8784, *, wait_seconds=22, poll_seconds=18, intent_database=None):
        if not 0 < wait_seconds <= 25 or not 0 <= poll_seconds <= 20:
            raise ValueError('invalid_request_timeout')
        from .foundation import JournalAuthority
        self.store = Store(database, authorize_bid=JournalAuthority(intent_database) if intent_database else None)
        self.extension_origin = 'chrome-extension://'+EXTENSION_ID
        self.condition = threading.Condition()
        self.peer = None
        self.attached_at = 0
        self.polling = False
        self.wait_seconds, self.poll_seconds = wait_seconds, poll_seconds
        super().__init__(('127.0.0.1', port), Handler)

    def handle_error(self, *args):
        pass


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = 'FCProduction/2', ''

    def setup(self):
        super().setup(); self.connection.settimeout(3)

    def log_message(self, *args):
        pass

    def send(self, code, value):
        body = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
        try:
            self.send_response(code)
            for k, v in {'Content-Type': 'application/json', 'Content-Length': str(len(body)),
                         'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}.items():
                self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)
        except OSError:
            pass

    def origin(self, extension=False):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and (
            self.headers.get('Origin') == self.server.extension_origin if extension else
            self.headers.get('Origin') is None and self.headers.get('Sec-Fetch-Site') is None)

    def payload(self):
        if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
            raise ValueError('invalid_encoding')
        n = int(self.headers.get('Content-Length', '0'))
        if not 0 < n <= 262144:
            raise ValueError('invalid_size')
        def unique(pairs):
            d = {}
            for k, v in pairs:
                if k in d:
                    raise ValueError('duplicate_field')
                d[k] = v
            return d
        def invalid(_):
            raise ValueError('invalid_number')
        return json.loads(self.rfile.read(n), object_pairs_hook=unique, parse_constant=invalid)

    def do_GET(self):
        if not self.origin():
            return self.send(403, {'error': 'origin_denied'})
        if self.path != '/health':
            return self.send(404, {'error': 'not_found'})
        s = self.server
        with s.condition:
            return self.send(200, {'service': 'fc-production-v1', 'schema': VERSION, 'host_epoch': s.store.host_epoch,
                                   'owner': s.store.owner(), 'attached': s.peer is not None and time.monotonic()-s.attached_at < 45,
                                   'peer': s.peer, 'mutations_enabled': s.store.authorize_bid is not None})

    def peer(self, p):
        s = self.server
        s.store.check_peer(p)
        if p != s.peer or time.monotonic()-s.attached_at >= 45:
            raise ValueError('reattach_required')

    def do_POST(self):
        s = self.server
        try:
            v = self.payload()
            if self.path not in {'/activate', '/hello', '/next', '/result', '/run'}:
                return self.send(404, {'error': 'not_found'})
            if not self.origin(self.path in {'/hello', '/next', '/result'}):
                return self.send(403, {'error': 'origin_denied'})
            with s.condition:
                if self.path == '/activate':
                    old = s.store.owner()
                    s.store.activate(v)
                    if old != v:
                        s.peer = None; s.attached_at = 0
                    s.condition.notify_all()
                    return self.send(200, {'accepted': True})
                if self.path == '/hello':
                    if v != {'schema': VERSION}:
                        fields(v, {'schema', 'peer'})
                        if type(v['schema']) is not int or v['schema'] != VERSION:
                            raise ValueError('invalid_schema')
                        s.store.check_peer(v['peer'])
                        if s.peer and s.peer != v['peer']:
                            # A new worker/document needs an explicit higher owner
                            # epoch. Never silently transfer an in-flight command.
                            raise ValueError('explicit_epoch_required')
                        s.peer = v['peer']; s.attached_at = time.monotonic()
                    return self.send(200, {'schema': VERSION, 'host_epoch': s.store.host_epoch, 'owner': s.store.owner()})
                if self.path == '/next':
                    self.peer(v)
                    if s.polling:
                        raise ValueError('single_poll_owner')
                    s.polling = True
                    s.attached_at = time.monotonic()
                    try:
                        end = time.monotonic()+s.poll_seconds
                        while True:
                            self.peer(v)
                            c = s.store.claim(v)
                            if c is not None or time.monotonic() >= end:
                                return self.send(200, c)
                            s.condition.wait(min(.5, end-time.monotonic()))
                    finally:
                        s.polling = False
                if self.path == '/result':
                    fields(v, {'peer', 'id', 'result'}); self.peer(v['peer'])
                    s.store.finish(v['peer'], v['id'], v['result'])
                    s.condition.notify_all()
                    return self.send(200, {'accepted': True})
                if s.peer is None:
                    raise ValueError('attachment_required')
                self.peer(s.peer)
                s.store.enqueue(v, s.peer); s.condition.notify_all()
                end = time.monotonic()+s.wait_seconds
                while True:
                    r = s.store.result(v['id'])
                    if r is not None:
                        return self.send(200, r)
                    if time.monotonic() >= end:
                        s.store.uncertain(v['id'])
                        return self.send(504, {'error': 'timeout_no_retry'})
                    s.condition.wait(min(.5, end-time.monotonic()))
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            return self.send(409, {'error': 'rejected'})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--port', type=int, default=8784)
    a = p.parse_args()
    Server(a.database, a.port).serve_forever()


if __name__ == '__main__':
    main()
