"""Loopback/pinned-extension bounded read queue. No arbitrary evaluation or writes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time

PORT = 8775
ROOT = Path(__file__).resolve().parents[2]
path = str((ROOT / 'experiments/watched_bulk_v1/browser').resolve())
# Chromium's unpacked path ID uses upper-case drive letter on Windows.
path = path[0].upper() + path[1:]
EXTENSION_ID = ''.join(chr(ord('a') + int(n, 16)) for n in hashlib.sha256(path.encode('utf-16-le')).hexdigest()[:32])


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=PORT, budget_path=None):
        self.condition = threading.Condition()
        self.pending = None
        self.attached_at = 0
        self.budget_path = budget_path or ROOT / 'docs/research/001c/001c-03/budget.json'
        budget=json.loads(self.budget_path.read_text())
        self.calls = budget['consumed']
        super().__init__(('127.0.0.1', port), Handler)

    def handle_error(self, *args):
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, value):
        body = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, extension=False):
        return (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and
                (self.headers.get('Origin') == 'chrome-extension://' + EXTENSION_ID if extension
                 else self.headers.get('Origin') is None and self.headers.get('Sec-Fetch-Site') is None))

    def do_GET(self):
        if not self.allowed():
            return self.reply(403, {'error': 'origin_denied'})
        if self.path != '/health':
            return self.reply(404, {'error': 'not_found'})
        return self.reply(200, {'service': 'fc-watched-bulk-v1', 'bind': '127.0.0.1',
                              'extension_id': EXTENSION_ID,
                              'attached': time.monotonic() - self.server.attached_at < 65,
                              'pending': self.server.pending is not None,
                              'delivered_reads': self.server.calls})

    def do_POST(self):
        if self.path not in ('/next', '/result', '/run'):
            return self.reply(404, {'error': 'not_found'})
        if not self.allowed(self.path != '/run'):
            return self.reply(403, {'error': 'origin_denied'})
        try:
            if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise ValueError()
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 262144:
                raise ValueError()
            v = json.loads(self.rfile.read(length))
            with self.server.condition:
                if self.path == '/next':
                    if v != {}:
                        raise ValueError()
                    self.server.attached_at = time.monotonic()
                    p = self.server.pending
                    if p and not p['delivered']:
                        p['delivered'] = True
                        self.server.calls += p['command']['operation'] == 'watched'
                        self.server.budget_path.write_text(json.dumps({'task':'001c-03','maximum':6,'consumed':self.server.calls}))
                        return self.reply(200, p['command'])
                    return self.reply(200, None)
                if self.path == '/result':
                    from .validation import validate_projection
                    if not isinstance(v, dict) or set(v) != {'id', 'result'}:
                        raise ValueError()
                    validate_projection(v['result'])
                    p = self.server.pending
                    if not p or not p['delivered'] or p['result'] is not None or p['command']['id'] != v['id']:
                        return self.reply(409, {'error': 'expired'})
                    p['result'] = v['result']
                    self.server.condition.notify_all()
                    return self.reply(200, {'accepted': True})
                if not isinstance(v, dict) or set(v) != {'operation', 'evidence_key'} or v['operation'] not in ('inspect', 'watched') or not re.fullmatch('[a-f0-9]{32}', v['evidence_key']):
                    raise ValueError()
                if self.server.pending:
                    return self.reply(409, {'error': 'busy'})
                if time.monotonic() - self.server.attached_at >= 65:
                    return self.reply(409, {'error': 'not_attached'})
                if self.server.calls >= 6 and v['operation'] == 'watched':
                    return self.reply(409, {'error': 'experiment_budget_exhausted'})
                p = {'command': v | {'id': secrets.token_hex(16)}, 'delivered': False, 'result': None}
                self.server.pending = p
                try:
                    self.server.condition.wait_for(lambda: p['result'] is not None, timeout=55)
                    return self.reply(200 if p['result'] else 504, p['result'] or {'error': 'timeout_no_retry'})
                finally:
                    self.server.pending = None
        except (ValueError, TypeError, KeyError):
            return self.reply(400, {'error': 'invalid_payload'})


if __name__ == '__main__':
    Server().serve_forever()
