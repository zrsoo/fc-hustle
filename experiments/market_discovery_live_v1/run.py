"""Run the frozen nine-window experiment through the verified follow-up bridge.

No browser implementation, authentication transport or strategy is replaced.
The inherited runner owns planning, pricing gates, budgets, pacing and stops.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import time

from fc_access.harness import empty_result
from experiments.market_discovery.discovery import Runner
from experiments.market_discovery.model import PROTOCOL, envelope, reply, stamp
from experiments.market_discovery.transport import SearchTransport
from experiments.market_discovery_followup_v1.__main__ import request
from experiments.market_discovery_followup_v1.server import persona_projection


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


class VerifiedTransport(SearchTransport):
    """Same /run protocol, with public command IDs and independent worker timing."""
    def __init__(self, port=8771):
        super().__init__(port)
        self.last_id = None
        self.last_worker = None

    def search(self, params, evidence_key):
        self.last_timing, self.last_worker = {}, None
        self.last_id = secrets.token_hex(16)
        body = envelope({'id': self.last_id, 'operation': 'search',
                         'params': params, 'evidence_key': evidence_key})
        try:
            began = time.perf_counter()
            value = request(self.base, '/run', body)
            elapsed = (time.perf_counter() - began)*1000
            if set(value) != {'result', 'timing', 'delivery'}:
                raise ValueError('invalid_delivery')
            projected = reply({'result': value['result'], 'timing': value['timing']})
            delivery = value['delivery']
            if not isinstance(delivery, dict) or set(delivery) != {'queue_delivery_ms', 'result_return_ms'}:
                raise ValueError('invalid_delivery')
            if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 120000)
                   for v in delivery.values()):
                raise ValueError('invalid_timing')
            self.last_timing = delivery | {'run_request_end_to_end_ms': elapsed}
            for _ in range(20):
                telemetry = request(self.base, '/telemetry/' + self.last_id)
                if telemetry is not None:
                    if set(telemetry) != {'id', 'worker_dispatch_to_page_return_ms', 'result_post_round_trip_ms', 'received_at'}:
                        raise ValueError('invalid_telemetry')
                    if telemetry['id'] != self.last_id:
                        raise ValueError('unmatched_telemetry')
                    stamp(telemetry['received_at'])
                    for key in ('worker_dispatch_to_page_return_ms', 'result_post_round_trip_ms'):
                        duration = telemetry[key]
                        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 120000:
                            raise ValueError('invalid_timing')
                    self.last_worker = telemetry
                    self.last_timing.update({k: telemetry[k] for k in
                                             ('worker_dispatch_to_page_return_ms', 'result_post_round_trip_ms')})
                    break
                time.sleep(.05)  # Local telemetry only; never another EA command.
            result = projected['result']
            if result['success'] and any(n['path'] == '/ut/game/fc27/transfermarket' and
                                         n['status'] == 200 and not n['session_header_present'] for n in result['network']):
                raise ValueError('authentication_evidence_missing')
            return projected
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return {'result': empty_result('bridge_unavailable'), 'timing': {
                'worker_poll_to_native_ms': None, 'native_service_ms': None, 'page_total_ms': None}}


class AuditClock:
    def __init__(self, delegate=None):
        if delegate is None:
            from experiments.market_discovery.replay import Clock
            delegate = Clock()
        self.delegate = delegate
        self.origin = self.origin_utc = None
        self.armed = False

    def arm(self):
        self.armed = True

    def perf_counter(self):
        value = self.delegate.perf_counter()
        if self.armed and self.origin is None:
            self.origin, self.origin_utc = value, self.delegate.utc()
        return value

    def utc(self):
        return self.delegate.utc()

    def sleep(self, seconds):
        self.delegate.sleep(seconds)


class DurableRunner(Runner):
    def __init__(self, transport, directory, *, clock=None, mode='LIVE_READ_ONLY'):
        self.directory = Path(directory)
        self.audit_clock = AuditClock(clock)
        super().__init__(transport, mode=mode, clock=self.audit_clock)

    def read(self, params, budget, strategy, window, slot):
        record = super().read(params, budget, strategy, window, slot)
        record['command_id'] = getattr(self.transport, 'last_id', None)
        record['scheduled_utc'] = (stamp(self.audit_clock.origin_utc) + timedelta(seconds=window*300+slot*30)).isoformat()
        record['submitted_monotonic_offset_seconds'] = self.clock.perf_counter() - self.audit_clock.origin - record['elapsed_ms']/1000
        if getattr(self.transport, 'last_worker', None) is not None:
            record['worker_telemetry'] = self.transport.last_worker
        with (self.directory/'records.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, separators=(',', ':'), allow_nan=False)+'\n')
            stream.flush()
            __import__('os').fsync(stream.fileno())
        progress = {'updated_utc': self.clock.utc(), 'mode': self.mode, 'window': window,
                    'strategy': strategy, 'slot': slot, 'commands_completed': len(self.records),
                    'EA_requests': sum(len(r['result']['network']) for r in self.records),
                    'last_status': record['result']['status'], 'last_error': record['result']['error'],
                    'auction_rows': len(record['result']['auctions'] or []), 'account_mutations': 0}
        temporary = self.directory/'progress.tmp'
        temporary.write_text(json.dumps(progress, indent=2)+'\n', encoding='utf-8')
        temporary.replace(self.directory/'progress.json')
        print(json.dumps(progress), flush=True)
        return record

    def complete_protocol(self):
        self.audit_clock.arm()
        result = super().run(9, paced=True)
        if result['stop_reason'] is None:
            remaining = self.audit_clock.origin + 9*300 - self.clock.perf_counter()
            while remaining > 0:
                self.clock.sleep(min(remaining, 1))
                remaining = self.audit_clock.origin + 9*300 - self.clock.perf_counter()
        elapsed = self.clock.perf_counter() - self.audit_clock.origin
        result['observation_interval'] = {'start_utc': self.audit_clock.origin_utc,
                                          'end_utc': self.clock.utc(), 'monotonic_seconds': elapsed}
        result['window_intervals'] = []
        for window in result['windows']:
            index = window['window']
            duration = max(0, min(300, elapsed-index*300))
            result['window_intervals'].append({'window': index, 'strategy': window['strategy'],
                'scheduled_start_utc': (stamp(self.audit_clock.origin_utc)+timedelta(seconds=index*300)).isoformat(),
                'scheduled_end_utc': (stamp(self.audit_clock.origin_utc)+timedelta(seconds=(index+1)*300)).isoformat(),
                'observed_seconds': duration, 'completed': duration >= 300,
                'commands': window['budget']['commands'], 'EA_requests': window['budget']['requests']})
        result['protocol_completion'] = ('COMPLETED_NINE_WINDOWS' if not result['stop_reason'] and elapsed >= 2700
                                          and len(result['windows']) == 9 else 'PARTIAL_STOPPED')
        result['background_measurement'] = {
            'between_native_calls': 'UNAVAILABLE',
            'during_native_calls': 'All allowlisted captured network requests charged to the foreground budget',
            'comparison': 'CONFOUNDED_BACKGROUND_UNMEASURED'}
        return result


def execute(directory, port=8771):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    protocol_bytes = PROTOCOL.read_bytes()
    protocol = json.loads(protocol_bytes)
    # Pin before preflight or the first benchmark observation. Never amend it.
    save_new(directory/'entry.json', {'created_utc': utc(), 'mode': 'LIVE_READ_ONLY',
        'protocol_path': PROTOCOL.as_posix(), 'protocol_sha256': hashlib.sha256(protocol_bytes).hexdigest(),
        'strategy_order': protocol['timing']['order'], 'source_revision': 'b17647c',
        'bridge': 'experiments/market_discovery_followup_v1', 'port': port,
        'protocol_amendment': None, 'account_mutations': 0,
        'capture_source_hashes': {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
            'experiments/market_discovery_live_v1/run.py',
            'experiments/market_discovery_live_v1/__main__.py',
            'experiments/market_discovery/discovery.py',
            'experiments/market_discovery/model.py',
            'experiments/market_discovery_followup_v1/server.py',
            'experiments/market_discovery_followup_v1/browser/page.js',
            'experiments/market_discovery_followup_v1/browser/persona.js',
            'experiments/market_discovery_followup_v1/browser/worker.js')}})
    base = f'http://127.0.0.1:{port}'
    try:
        health = request(base, '/health')
        persona = request(base, '/persona')
    except (OSError, ValueError, TypeError):
        save_new(directory/'blocked.json', {'status': 'BLOCKED', 'reason': 'local_bridge_unavailable',
            'operator_action': 'Start the verified follow-up server on port 8771 and click its extension on the existing EA tab.'})
        return 1
    if not health.get('attached') or not persona or not persona_projection(persona['projection'])['accepted']:
        save_new(directory/'blocked.json', {'status': 'BLOCKED', 'reason': 'bridge_attachment_or_pc_persona',
            'health': health, 'persona': persona, 'operator_action':
            'Click FC discovery integration follow-up READ ONLY on the existing official signed-in EA Web App tab.'})
        return 1
    transport = VerifiedTransport(port)
    params = {'definition_id': 233731, 'max_buy': 7000, 'page': 1, 'count': 21, 'fresh': True}
    started = utc()
    preflight = transport.search(params, secrets.token_hex(16))
    result = preflight['result']
    success = (result['success'] and result['platform'] == 'pc' and result['status'] == 200 and
               any(n['path'] == '/ut/game/fc27/transfermarket' and n['status'] == 200 and
                   n['session_header_present'] for n in result['network']))
    save_new(directory/'preflight.json', {'submitted_utc': started, 'completed_utc': utc(),
        'health': health, 'persona': persona, 'criteria': params, 'reply': preflight,
        'delivery': transport.last_timing, 'worker_telemetry': transport.last_worker,
        'status': 'PASS' if success else 'BLOCKED', 'budget': 'SEPARATE_PREFLIGHT', 'account_mutations': 0})
    if not success:
        save_new(directory/'blocked.json', {'status': 'BLOCKED', 'reason': result['error'] or 'preflight_not_authenticated',
            'HTTP_statuses': [n['status'] for n in result['network']], 'operator_action':
            'Sign in normally in the existing official EA Web App, complete any normal challenge, then click the follow-up extension again. No credentials should be copied.'})
        return 1
    print(json.dumps({'preflight': 'PASS', 'completed_utc': utc(), 'HTTP_statuses': [n['status'] for n in result['network']]}), flush=True)
    # Conservative initial gap from completion, in addition to the live page's
    # native-submission pacing. It is outside the nine benchmark windows.
    time.sleep(30)
    runner = DurableRunner(transport, directory)
    result = runner.complete_protocol()
    save_new(directory/'observations.json', result)
    print(json.dumps({'protocol_completion': result['protocol_completion'], 'stop_reason': result['stop_reason'],
                      'EA_requests': result['overall']['EA_requests'], 'windows': len(result['windows'])}), flush=True)
    return int(result['stop_reason'] is not None)
