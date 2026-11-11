"""Only search may cross this client. Never uses the transaction server."""
import json
import secrets
import urllib.error
import urllib.request

from fc_access.harness import empty_result, opener
from .model import envelope, reply


class SearchTransport:
    def __init__(self, port=8770):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('invalid_port')
        self.base = f'http://127.0.0.1:{port}'
        self.last_timing = {}

    def search(self, params, evidence_key):
        body = envelope({'id': secrets.token_hex(16), 'operation': 'search', 'params': params, 'evidence_key': evidence_key})
        self.last_timing = {}
        try:
            request = urllib.request.Request(self.base+'/run', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with opener().open(request, timeout=65) as response:
                value = json.loads(response.read(262145))
            if set(value) != {'result', 'timing', 'delivery'}:
                raise ValueError('invalid_delivery')
            delivery = value.pop('delivery')
            if set(delivery) != {'queue_delivery_ms', 'result_return_ms'} or any(v is not None and (type(v) not in (float,int) or not 0 <= v <= 120000) for v in delivery.values()):
                raise ValueError('invalid_delivery')
            self.last_timing = delivery
            return reply(value)
        except (OSError, ValueError, TypeError, urllib.error.URLError):
            return {'result': empty_result('bridge_unavailable'), 'timing': {'worker_poll_to_native_ms': None, 'native_service_ms': None, 'page_total_ms': None}}
