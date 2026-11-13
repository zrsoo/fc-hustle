"""Synthetic follow-up regression checks; no account or historical evidence writes."""
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.market_discovery_followup_v1.server import FollowupServer, persona_projection
from experiments.market_discovery_followup_v1.__main__ import assessment, one_search
from experiments.market_discovery.replay import FixtureClock, FixtureTransport




def projection(**changes):
    return dict(schema=1, persona_present=True, platform_type='string', platform_value='PC',
                is_pc_type='boolean', is_pc=True, native_pc_constant='PC', accepted=True,
                read_error=False) | changes


class PersonaTests(unittest.TestCase):
    def test_native_and_valid_alternative_projections(self):
        for value in [projection(), projection(platform_value='pc'),
                      projection(platform_value='pc', is_pc_type='missing', is_pc=None),
                      projection(platform_type='missing', platform_value=None),
                      projection(platform_type='null', platform_value=None)]:
            self.assertEqual(persona_projection(value), value)

    def test_reject_console_unknown_conflicting_malformed_and_private_projection(self):
        for platform in ['PSN', 'XBL', 'SWI', 'ps5', 'xboxone', '', 'unknown', [], {}]:
            with self.subTest(platform=platform), self.assertRaises((ValueError, TypeError)):
                persona_projection(projection(platform_value=platform))
        for changes in [dict(is_pc=False), dict(native_pc_constant=None), dict(is_pc='true'),
                        dict(schema=True), dict(platform_type='null'), dict(persona_present=False),
                        dict(read_error=True), dict(cookie='PRIVATE-CANARY')]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                persona_projection(projection(**changes))
        value = projection(platform_value='PSN', is_pc=False, accepted=False)
        self.assertFalse(persona_projection(value)['accepted'])
        value = projection(platform_value=None, accepted=False)
        self.assertFalse(persona_projection(value)['accepted'], 'unknown string plus a true flag stays unknown')

    def test_javascript_persona_pacing_identity_and_worker(self):
        result = subprocess.run(['node', 'tests/market_discovery_followup_v1_checks.cjs'],
                                cwd=ROOT, text=True, capture_output=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('synthetic only', result.stdout)

    def test_sealed_source_hashes_and_followup_extension_permissions(self):
        review = json.loads((ROOT/'experiments/market_discovery/source-review.json').read_text())
        from js_contract import check_js
        check_js(self, 'market_discovery_followup_v1_checks.cjs')
        manifest = json.loads((ROOT/'experiments/market_discovery_followup_v1/browser/manifest.json').read_text())
        self.assertEqual(manifest['version'], '0.2.0')
        self.assertEqual(manifest['host_permissions'], ['http://127.0.0.1:8771/*'])
        self.assertEqual(set(manifest['permissions']), {'activeTab', 'scripting', 'alarms', 'storage'})

    def test_existing_output_fails_before_any_browser_or_ea_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'existing.json'
            path.write_text('preserve')
            with patch('experiments.market_discovery_followup_v1.__main__.request') as network:
                with self.assertRaisesRegex(ValueError, 'new_output_path_required'):
                    one_search(8771, path)
                network.assert_not_called()
            self.assertEqual(path.read_text(), 'preserve')

    def test_malformed_native_reply_is_rejected_before_any_persistence(self):
        params = {'definition_id': 233731, 'max_buy': 7000, 'page': 1, 'count': 21, 'fresh': True}
        value = FixtureTransport(FixtureClock()).search(params, 'd'*32)
        value['result']['cookie'] = 'PRIVATE-CANARY'
        value['delivery'] = {'queue_delivery_ms': 1, 'result_return_ms': 2}
        replies = [{'attached': True, 'long_poll_active': True}, {'projection': projection()}, value]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'never-written.json'
            with patch('experiments.market_discovery_followup_v1.__main__.request', side_effect=replies):
                with self.assertRaises(ValueError):
                    one_search(8771, path)
            self.assertFalse(path.exists())


class FollowupHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = FollowupServer('a'*32, port=0, wait_seconds=.5, poll_seconds=.03)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, route, value=None, extension=False, extra=None):
        headers = {'Content-Type': 'application/json'}
        if extension:
            headers['Origin'] = 'chrome-extension://' + 'a'*32
        headers.update(extra or {})
        con = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        con.request(method, route, None if value is None else json.dumps(value), headers)
        response = con.getresponse()
        self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
        result = response.status, json.loads(response.read())
        con.close()
        return result

    def test_diagnostics_are_origin_pinned_schema_limited_and_not_authentication(self):
        self.assertEqual(self.request('POST', '/persona', projection())[0], 403)
        self.assertEqual(self.request('POST', '/persona', projection(), True,
                                      {'Origin': 'chrome-extension://'+'b'*32})[0], 403)
        self.assertEqual(self.request('POST', '/persona', projection(cookie='PRIVATE-CANARY'), True)[0], 400)
        self.assertIsNone(self.request('GET', '/persona')[1])
        self.assertEqual(self.request('POST', '/persona', projection(), True)[0], 200)
        self.assertEqual(self.request('GET', '/persona')[1]['projection'], projection())
        health = self.request('GET', '/health')[1]
        self.assertEqual(health['service'], 'fc-search-followup-v1')
        self.assertTrue(health['persona_observed'])
        self.assertFalse(health['attached'], 'persona projection alone never proves a live poll or EA authentication')
        self.assertEqual(self.request('POST', '/next', {'protocol': 1}, True), (200, None))
        self.assertTrue(self.request('GET', '/health')[1]['attached'])

    def test_real_queue_roundtrip_and_independent_telemetry_reject_unknown_duplicate(self):
        self.request('POST', '/next', {'protocol': 1}, True)
        params = {'definition_id': 233731, 'max_buy': 7000, 'page': 1, 'count': 21, 'fresh': True}
        command = {'operation': 'search', 'params': params, 'id': 'c'*32, 'evidence_key': 'd'*32}
        value = FixtureTransport(FixtureClock()).search(params, 'd'*32)
        result = []
        caller = threading.Thread(target=lambda: result.append(self.request('POST', '/run', command)))
        caller.start()
        delivered = self.request('POST', '/next', {'protocol': 1}, True)[1]
        self.assertEqual(delivered, command)
        self.assertEqual(self.request('POST', '/result', {'id': command['id']} | value, True)[0], 200)
        caller.join(2)
        self.assertFalse(caller.is_alive())
        self.assertTrue(result[0][1]['result']['success'])
        self.assertGreaterEqual(result[0][1]['delivery']['queue_delivery_ms'], 0)
        telemetry = {'id': command['id'], 'worker_dispatch_to_page_return_ms': 50, 'result_post_round_trip_ms': 2}
        self.assertEqual(self.request('POST', '/telemetry', telemetry | {'id': 'e'*32}, True)[0], 409)
        self.assertEqual(self.request('POST', '/telemetry', telemetry | {'result_post_round_trip_ms': True}, True)[0], 400)
        self.assertEqual(self.request('POST', '/telemetry', telemetry | {'cookie': 'PRIVATE-CANARY'}, True)[0], 400)
        self.assertEqual(self.request('POST', '/telemetry', telemetry, True)[0], 200)
        self.assertEqual(self.request('POST', '/telemetry', telemetry, True)[0], 409)
        self.assertEqual(self.request('GET', '/telemetry/'+command['id'])[1]['result_post_round_trip_ms'], 2)
        self.assertEqual(self.request('POST', '/buy', {})[0], 404)
        for op in ('buy', 'bid', 'move', 'list', 'relist', 'eval'):
            self.assertEqual(self.request('POST', '/run', command | {'operation': op})[0], 400)

    def test_live_assessment_requires_each_independent_layer(self):
        params = {'definition_id': 233731, 'max_buy': 7000, 'page': 1, 'count': 21, 'fresh': True}
        value = FixtureTransport(FixtureClock()).search(params, 'd'*32)
        record = dict(schema=1, source='fc-discovery-followup-v1', result=value['result'], timing=value['timing'], persona={'projection': projection()},
                      request=params, health_before={'attached': True, 'long_poll_active': True},
                      delivery={'queue_delivery_ms': .1, 'result_return_ms': 2}, command_id='a'*32,
                      worker_telemetry={'id': 'a'*32, 'worker_dispatch_to_page_return_ms': 45,
                                        'result_post_round_trip_ms': 3}, account_mutations=0)
        self.assertEqual(assessment(record), [])
        changes = [
            ('source', lambda r: r.update(source='synthetic'), 'unrecognized_followup_source'),
            ('attachment', lambda r: r['health_before'].update(attached=False), 'attachment_unverified'),
            ('poll', lambda r: r['health_before'].update(long_poll_active=False), 'active_long_poll_unverified'),
            ('http', lambda r: r['result']['network'][0].update(status=401), 'fresh_authenticated_http_200_unverified'),
            ('auth', lambda r: r['result']['network'][0].update(session_header_present=False), 'fresh_authenticated_http_200_unverified'),
            ('version', lambda r: r['result']['auctions'][0]['item'].update(definition_id=42), 'wrong_card_version'),
            ('queue', lambda r: r['delivery'].update(queue_delivery_ms=None), 'missing_delivery_timing'),
            ('worker', lambda r: r['worker_telemetry'].update(id='e'*32), 'unmatched_worker_telemetry')]
        for label, mutate, expected in changes:
            changed = deepcopy(record)
            mutate(changed)
            with self.subTest(layer=label):
                self.assertIn(expected, assessment(changed))


if __name__ == '__main__':
    unittest.main(verbosity=2)
