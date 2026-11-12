"""Add public persona diagnostics and measured POST timing to the sealed queue.

The original search command, identity validation, exact Origin pin, deadlines,
one-command ownership and bounded 20-second long poll are inherited unchanged.
"""
import math
import re
from datetime import datetime, timezone

from experiments.market_discovery.bridge_server import Handler, SearchServer


PUBLIC_PLATFORMS = {'PC', 'pc', 'PSN', 'XBL', 'SWI', 'ps3', 'ps4', 'ps5',
                    'xbox', 'xbox360', 'xboxone', 'xbsx', 'switch', ''}
PERSONA_FIELDS = {'schema', 'persona_present', 'platform_type', 'platform_value',
                  'is_pc_type', 'is_pc', 'native_pc_constant', 'accepted', 'read_error'}
TELEMETRY_FIELDS = {'id', 'worker_dispatch_to_page_return_ms', 'result_post_round_trip_ms'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def persona_projection(value):
    if not isinstance(value, dict) or set(value) != PERSONA_FIELDS:
        raise ValueError('invalid_persona_projection')
    if type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('invalid_persona_schema')
    if any(type(value[k]) is not bool for k in ('persona_present', 'accepted', 'read_error')):
        raise ValueError('invalid_persona_flag')
    if value['platform_type'] not in ('missing', 'null', 'string', 'invalid'):
        raise ValueError('invalid_platform_type')
    if value['platform_value'] is not None and (not isinstance(value['platform_value'], str) or value['platform_value'] not in PUBLIC_PLATFORMS):
        raise ValueError('unknown_public_platform')
    if value['platform_type'] != 'string' and value['platform_value'] is not None:
        raise ValueError('inconsistent_platform_type')
    if value['is_pc_type'] not in ('missing', 'boolean', 'invalid'):
        raise ValueError('invalid_pc_type')
    if (value['is_pc_type'] == 'boolean') != (type(value['is_pc']) is bool):
        raise ValueError('inconsistent_pc_type')
    if value['is_pc'] is not None and type(value['is_pc']) is not bool:
        raise ValueError('invalid_pc_flag')
    if value['native_pc_constant'] not in (None, 'PC'):
        raise ValueError('unknown_native_pc_constant')
    platform, flag = value['platform_value'], value['is_pc']
    accepted = (value['persona_present'] and not value['read_error'] and
                value['is_pc_type'] != 'invalid' and (
                    platform == 'PC' and flag is True and value['native_pc_constant'] == 'PC' or
                    platform == 'pc' and flag is not False or
                    value['platform_type'] in ('missing', 'null') and flag is True))
    if value['accepted'] != accepted:
        raise ValueError('inconsistent_persona_acceptance')
    return dict(value)


class FollowupServer(SearchServer):
    def __init__(self, extension_id, port=8771, **kwargs):
        super().__init__(extension_id, port=port, **kwargs)
        self.RequestHandlerClass = FollowupHandler
        self.persona = None
        self.accepted_ids = set()
        self.telemetry = {}


class FollowupHandler(Handler):
    def payload(self):
        value = super().payload()
        self.current_payload = value
        return value

    def send(self, code, value):
        if self.path == '/result' and code == 200:
            with self.server.condition:
                # Retain only bounded public command IDs, never command keys.
                if len(self.server.accepted_ids) >= 64:
                    self.server.accepted_ids.clear()
                    self.server.telemetry.clear()
                self.server.accepted_ids.add(self.current_payload['id'])
        if self.path == '/health' and code == 200:
            value = value | {'service': 'fc-search-followup-v1', 'revision': '0.2.0',
                             'long_poll_active': self.server.polling,
                             'persona_observed': self.server.persona is not None}
        return super().send(code, value)

    def do_GET(self):
        if self.path == '/persona' or self.path.startswith('/telemetry/'):
            if not self.origin():
                return self.send(403, {'error': 'origin_denied'})
            if self.path == '/persona':
                return self.send(200, self.server.persona)
            identifier = self.path.removeprefix('/telemetry/')
            if not re.fullmatch('[a-f0-9]{32}', identifier):
                return self.send(400, {'error': 'invalid_id'})
            return self.send(200, self.server.telemetry.get(identifier))
        return super().do_GET()

    def do_POST(self):
        if self.path not in ('/persona', '/telemetry'):
            return super().do_POST()
        if not self.origin(extension=True):
            return self.send(403, {'error': 'origin_denied'})
        try:
            value = self.payload()
            if self.path == '/persona':
                projection = persona_projection(value)
                self.server.persona = {'received_at': utc(), 'projection': projection}
            else:
                if not isinstance(value, dict) or set(value) != TELEMETRY_FIELDS:
                    raise ValueError('invalid_telemetry')
                if not isinstance(value['id'], str) or not re.fullmatch('[a-f0-9]{32}', value['id']):
                    raise ValueError('invalid_id')
                for key in TELEMETRY_FIELDS - {'id'}:
                    duration = value[key]
                    if type(duration) not in (float, int) or not math.isfinite(duration) or not 0 <= duration <= 120000:
                        raise ValueError('invalid_duration')
                with self.server.condition:
                    if value['id'] not in self.server.accepted_ids or value['id'] in self.server.telemetry:
                        return self.send(409, {'error': 'unknown_or_duplicate_telemetry'})
                    self.server.telemetry[value['id']] = value | {'received_at': utc()}
            return self.send(200, {'accepted': True})
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return self.send(400, {'error': 'invalid_payload'})
