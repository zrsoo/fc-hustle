"""Pinned-extension, loopback search queue with bounded long polling.

Origin is pinned rather than trusting every installed extension. No CORS, GET
dispatch, proxy, redirect, generic native command, eval, auth or transaction route.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
import time

from fc_access.harness import empty_result
from .model import envelope, reply


def unavailable(error):
    return {'result': empty_result(error), 'timing': {'worker_poll_to_native_ms': None, 'native_service_ms': None, 'page_total_ms': None},
            'delivery': {'queue_delivery_ms': None, 'result_return_ms': None}}


class SearchServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, extension_id, port=8770, wait_seconds=60, poll_seconds=20):
        if not re.fullmatch('[a-p]{32}', extension_id):
            raise ValueError('extension_id_required')
        if not 0 < wait_seconds <= 60 or not 0 <= poll_seconds <= 20:
            raise ValueError('invalid_deadline')
        self.extension_origin = 'chrome-extension://' + extension_id
        self.wait_seconds, self.poll_seconds = wait_seconds, poll_seconds
        self.condition = threading.Condition()
        self.pending, self.last_attached, self.polling = None, 0, False
        super().__init__(('127.0.0.1', port), Handler)

    def handle_error(self, *args):
        pass  # no raw payloads or exception strings in logs


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = 'FCSearchResearch/1', ''

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass

    def send(self, code, value):
        body = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def origin(self, extension=False):
        return (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
                and (self.headers.get('Origin') == self.server.extension_origin if extension else
                     self.headers.get('Origin') is None and self.headers.get('Sec-Fetch-Site') is None))

    def payload(self):
        if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
            raise ValueError('invalid_encoding')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 262144:
            raise ValueError('invalid_size')
        def unique(pairs):
            value = {}
            for k,v in pairs:
                if k in value:
                    raise ValueError('duplicate_field')
                value[k] = v
            return value
        return json.loads(self.rfile.read(length), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')))

    def do_GET(self):
        if not self.origin():
            return self.send(403, {'error': 'origin_denied'})
        if self.path != '/health':
            return self.send(404, {'error': 'not_found'})
        return self.send(200, {'service': 'fc-search-research-v1', 'attached': time.monotonic()-self.server.last_attached < 45,
                               'bind': '127.0.0.1', 'operations': ['search']})

    def do_POST(self):
        if self.path not in {'/run', '/next', '/result'}:
            return self.send(404, {'error': 'not_found'})
        if not self.origin(self.path != '/run'):
            return self.send(403, {'error': 'origin_denied'})
        try:
            value = self.payload()
            if self.path == '/next':
                if value != {'protocol': 1}:
                    raise ValueError('invalid_protocol')
                return self.next()
            if self.path == '/result':
                if not isinstance(value, dict) or set(value) != {'id', 'result', 'timing'}:
                    raise ValueError('invalid_result')
                result = reply({'result': value['result'], 'timing': value['timing']})
                with self.server.condition:
                    pending = self.server.pending
                    if not pending or pending['delivered'] is None or pending['result'] is not None or pending['deadline'] <= time.monotonic() or pending['command']['id'] != value['id']:
                        return self.send(409, {'error': 'unknown_or_expired_command'})
                    pending['received'] = time.monotonic()
                    pending['result'] = result
                    self.server.condition.notify_all()
                return self.send(200, {'accepted': True})
            envelope(value)
            with self.server.condition:
                if self.server.pending is not None:
                    return self.send(409, {'error': 'bridge_busy'})
                if time.monotonic()-self.server.last_attached >= 45:
                    return self.send(200, unavailable('bridge_not_attached'))
                now = time.monotonic()
                pending = {'command': value, 'submitted': now, 'deadline': now+self.server.wait_seconds,
                           'delivered': None, 'received': None, 'result': None}
                self.server.pending = pending
                self.server.condition.notify_all()
                try:
                    self.server.condition.wait_for(lambda: pending['result'] is not None, timeout=self.server.wait_seconds)
                    if pending['result'] is None:
                        result = unavailable('bridge_timeout')
                    else:
                        result = pending['result'] | {'delivery': {
                            'queue_delivery_ms': (pending['delivered']-pending['submitted'])*1000,
                            # worker/native/page measured using durations, no cross-clock subtraction
                            'result_return_ms': None}}
                        page = result['timing']['page_total_ms']
                        worker = result['timing']['worker_poll_to_native_ms']
                        if page is not None and worker is not None:
                            result['delivery']['result_return_ms'] = max(0, (pending['received']-pending['delivered'])*1000-page-worker)
                finally:
                    self.server.pending = None
                    self.server.condition.notify_all()
            return self.send(200, result)
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return self.send(400, {'error': 'invalid_payload'})

    def next(self):
        with self.server.condition:
            if self.server.polling:
                return self.send(409, {'error': 'poll_busy'})
            self.server.polling = True
            self.server.last_attached = time.monotonic()
            try:
                def ready():
                    p = self.server.pending
                    return p is not None and p['delivered'] is None and p['deadline'] > time.monotonic()
                self.server.condition.wait_for(ready, timeout=self.server.poll_seconds)
                if ready():
                    pending = self.server.pending
                    pending['delivered'] = time.monotonic()
                    return self.send(200, pending['command'])
                return self.send(200, None)
            finally:
                self.server.last_attached = time.monotonic()
                self.server.polling = False
