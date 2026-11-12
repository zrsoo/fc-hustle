"""Finite-protocol regression fixtures. No live browser or EA requests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.market_discovery_live_v1.run import DurableRunner, VerifiedTransport, execute
from experiments.market_discovery.replay import FixtureClock, FixtureTransport
from experiments.market_discovery.model import PROTOCOL


class ProtocolTests(unittest.TestCase):
    def test_nine_full_windows_original_order_budgets_and_no_catch_up(self):
        clock = FixtureClock()
        transport = FixtureTransport(clock)
        before = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            runner = DurableRunner(transport, directory, clock=clock, mode='SIMULATED')
            with patch('builtins.print'):
                result = runner.complete_protocol()
            raw = [json.loads(line) for line in (Path(directory)/'records.jsonl').read_text().splitlines()]
        self.assertEqual(result['protocol_completion'], 'COMPLETED_NINE_WINDOWS')
        self.assertEqual(result['observation_interval']['monotonic_seconds'], 2700)
        self.assertEqual([w['strategy'] for w in result['window_intervals']], list('ABCBCACAB'))
        self.assertTrue(all(w['completed'] and w['observed_seconds'] == 300 for w in result['window_intervals']))
        self.assertTrue(all(w['EA_requests'] == 8 and w['commands'] == 8 for w in result['window_intervals']))
        self.assertEqual(len(raw), 72)
        self.assertTrue(all(result['by_strategy'][s]['EA_requests'] == 24 for s in 'ABC'))
        self.assertEqual(result['protocol_sha256'], before)
        self.assertEqual(hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(), before)
        self.assertEqual(result['account_mutations'], 0)

    def test_http_auth_rate_limit_and_server_failures_stop_without_retry(self):
        for code in (401, 403, 429, 503):
            clock = FixtureClock()
            class Failure(FixtureTransport):
                def search(self, params, key):
                    value = super().search(params, key)
                    value['result'].update(status=code, success=False, error='service_failed', auctions=None)
                    value['result']['network'][0]['status'] = code
                    return value
            transport = Failure(clock)
            with tempfile.TemporaryDirectory() as directory:
                with patch('builtins.print'):
                    result = DurableRunner(transport, directory, clock=clock, mode='SIMULATED').complete_protocol()
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(result['protocol_completion'], 'PARTIAL_STOPPED')
            self.assertFalse(result['window_intervals'][0]['completed'])

    def test_new_output_directory_required_before_any_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('experiments.market_discovery_live_v1.run.request') as network:
                with self.assertRaises(FileExistsError):
                    execute(directory)
                network.assert_not_called()

    def test_working_followup_protocol_and_independent_telemetry_are_reused(self):
        clock = FixtureClock()
        fixture = FixtureTransport(clock)
        params = {'definition_id': 233731, 'page': 1, 'count': 21, 'fresh': True, 'max_buy': 7000}
        native = fixture.search(params, 'a'*32)
        transport = VerifiedTransport()
        def response(base, route, value=None):
            self.assertEqual(base, 'http://127.0.0.1:8771')
            if route == '/run':
                self.assertEqual(value['operation'], 'search')
                self.assertEqual(value['params'], params)
                return native | {'delivery': {'queue_delivery_ms': .1, 'result_return_ms': 1}}
            return {'id': transport.last_id, 'worker_dispatch_to_page_return_ms': 45,
                    'result_post_round_trip_ms': 2, 'received_at': clock.utc()}
        with patch('experiments.market_discovery_live_v1.run.request', side_effect=response):
            value = transport.search(params, 'a'*32)
        self.assertTrue(value['result']['success'])
        self.assertEqual(transport.last_timing['result_post_round_trip_ms'], 2)
        self.assertEqual(transport.last_worker['id'], transport.last_id)

    def test_malformed_or_sensitive_reply_never_enters_record(self):
        params = {'definition_id': 233731, 'page': 1, 'count': 21, 'fresh': True}
        native = FixtureTransport(FixtureClock()).search(params, 'a'*32)
        native['result']['cookie'] = 'PRIVATE-CANARY'
        with patch('experiments.market_discovery_live_v1.run.request', return_value=native | {
                'delivery': {'queue_delivery_ms': .1, 'result_return_ms': 1}}):
            value = VerifiedTransport().search(params, 'a'*32)
        self.assertEqual(value['result']['error'], 'bridge_unavailable')
        self.assertNotIn('PRIVATE-CANARY', json.dumps(value))


if __name__ == '__main__':
    unittest.main(verbosity=2)
