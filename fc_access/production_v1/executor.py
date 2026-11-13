"""Explicit loopback executor for the reviewed production extension on port 8784."""
import json
import math
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from .contracts import VERSION, command


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class EdgeExecutor:
    def __init__(self, port=8784, attach_timeout=45):
        if type(port) is not int or not 1 <= port <= 65535 or not 0 < attach_timeout <= 60:
            raise ValueError('invalid_transport')
        self.base, self.attach_timeout = f'http://127.0.0.1:{port}', attach_timeout
        self.http = build_opener(ProxyHandler({}), NoRedirect())
        self.last_sqlite_ms = None

    def request(self, path, value=None):
        req = Request(self.base+path, data=json.dumps(value).encode() if value is not None else None,
                      headers={'Content-Type': 'application/json'} if value is not None else {})
        try:
            with self.http.open(req, timeout=30) as r:
                ms = r.headers.get('X-FC-SQLite-Ms')
                self.last_sqlite_ms = float(ms) if ms is not None else None
                if self.last_sqlite_ms is not None and (not math.isfinite(self.last_sqlite_ms) or self.last_sqlite_ms < 0):
                    raise ValueError('invalid_transport_timing')
                return json.loads(r.read(262145))
        except HTTPError as e:
            # Never propagate an HTTP body, URL or native exception text.
            if e.code == 504:
                raise TimeoutError('timeout_no_retry') from None
            raise ValueError('local_rejected') from None
        except OSError:
            raise TimeoutError('transport_unknown_no_retry') from None

    def attach(self, context, owner, epoch):
        expected = {'context': context, 'owner': owner, 'epoch': epoch}
        self.request('/activate', expected)
        end = time.monotonic()+self.attach_timeout
        while time.monotonic() < end:
            h = self.request('/health')
            if h.get('schema') != VERSION or h.get('service') != 'fc-production-v1':
                raise ValueError('wrong_service')
            if h['owner'] == expected and h['attached']:
                return h['peer']['fences']
            time.sleep(.25)
        raise ValueError('attachment_required_click_production_extension')

    def ownership_epoch(self, context):
        """Public fencing metadata only; synchronize a service restart without replay."""
        h = self.request('/health')
        if h.get('schema') != VERSION or h.get('service') != 'fc-production-v1':
            raise ValueError('wrong_service')
        owner = h['owner']
        if owner is not None and owner['context'] != context:
            raise ValueError('wrong_service_account')
        return owner['epoch'] if owner else 0

    def execute(self, c):
        command(c)
        self.last_sqlite_ms = None
        return self.request('/run', c)
