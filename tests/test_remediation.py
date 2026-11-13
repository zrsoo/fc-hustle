"""Behavioral replacements for mixed source/evidence preservation gates."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.evidence import evidence_hashes, is_evidence, research_semantics
from fc_access import release_audit_v1
from experiments.search_validation_v1.server import Server as SearchServer
from experiments.watched_bulk_v1.server import Server as WatchedServer


class EvidencePolicy(unittest.TestCase):
    def test_current_implementation_is_not_an_evidence_pin(self):
        for path in ('AGENTS.md', 'README.md', '.gitattributes',
                     'objectives/002-two-actor-competitive-bidding.md',
                     'fc_access/production_v1/pricing.py', 'tests/test_remediation.py',
                     'browser/production-v1/page.js', 'browser/production-v1/manifest.json',
                     'experiments/market_discovery/observation.schema.json',
                     'docs/research/001d/001d-07/consume_handoff.py'):
            with self.subTest(path=path):
                self.assertFalse(is_evidence(path))
                self.assertEqual(evidence_hashes({path: 'descriptive provenance'}), {})

    def test_captures_transactions_and_sealed_snapshots_still_have_integrity(self):
        for path in ('docs/research/transaction/live.json',
                     'docs/research/001c/001c-06-resume-02/live-final.sqlite',
                     'docs/research/001d/001d-06/before/tests/test_001d02_contract.py',
                     'experiments/market_discovery/runs/t6-analysis/report.json'):
            self.assertTrue(is_evidence(path))
            self.assertEqual(evidence_hashes({path: 'pin'}), {path: 'pin'})
        for path in ('../docs/research/escape.json', 'C:/elsewhere/evidence.json'):
            self.assertFalse(is_evidence(path))

    def test_real_auditor_allows_source_evolution_but_rejects_changed_EA_evidence(self):
        def evolved(path):
            data = release_audit_v1.read(path)
            return data if is_evidence(path) else data+b'\n# implementation evolves\n'
        self.assertEqual(release_audit_v1.preserve(evolved), release_audit_v1.preserve())
        target = 'docs/research/001c/001c-06-resume-02/comparables-2.json'
        def altered(path):
            data = evolved(path)
            return data+b' ' if path == target else data
        with self.assertRaisesRegex(ValueError, 'preexisting_bytes_changed|sealed_bytes_changed'):
            release_audit_v1.preserve(altered)

    def test_replay_ignores_only_source_provenance_keeps_economics_and_evidence(self):
        original = dict(resale_price=1500, cap=900, samples=[1500, 1700],
                        sources_sha256={'fc_access/pricing.py': 'old'},
                        inputs_sha256={'fc_access/pricing.py': 'old',
                                       'docs/research/captured-response.json': 'evidence'})
        evolved = deepcopy(original)
        evolved['sources_sha256']['fc_access/pricing.py'] = 'new'
        evolved['inputs_sha256']['fc_access/pricing.py'] = 'new'
        self.assertEqual(research_semantics(original), research_semantics(evolved))
        for field, value in (('resale_price', 1700), ('cap', 1000), ('samples', [1700])):
            altered = deepcopy(evolved); altered[field] = value
            self.assertNotEqual(research_semantics(original), research_semantics(altered))
        evolved['inputs_sha256']['docs/research/captured-response.json'] = 'changed'
        self.assertNotEqual(research_semantics(original), research_semantics(evolved))


class SplitHTTPRejection(unittest.TestCase):
    def test_search_and_watched_origin_rejection_wait_for_the_actual_body(self):
        # A real split TCP request deterministically exercises the Windows reset
        # race. No global urllib patch, coalescing, retry or synthetic response.
        with tempfile.TemporaryDirectory() as td:
            budget = Path(td)/'budget.json'
            budget.write_text(json.dumps(dict(task='001c-04', consumed=12, maximum=12, commands=[])))
            for server in (SearchServer(0, budget), WatchedServer(0, budget)):
                with self.subTest(server=type(server).__module__):
                    worker = threading.Thread(target=server.serve_forever, daemon=True)
                    worker.start()
                    try:
                        with socket.create_connection(server.server_address, timeout=3) as client:
                            body = b'{"params":{}}'
                            headers = (f'POST /run HTTP/1.0\r\nHost: 127.0.0.1:{server.server_port}\r\n'
                                       'Origin: https://example.invalid\r\nContent-Type: application/json\r\n'
                                       f'Content-Length: {len(body)}\r\n\r\n').encode()
                            client.sendall(headers)
                            client.settimeout(.05)
                            with self.assertRaises(socket.timeout):
                                client.recv(1)
                            client.settimeout(3); client.sendall(body)
                            received = b''
                            while chunk := client.recv(4096):
                                received += chunk
                            status, payload = received.split(b'\r\n\r\n', 1)
                            self.assertTrue(status.startswith(b'HTTP/1.0 403'))
                            self.assertEqual(json.loads(payload), {'error': 'origin_denied'})
                        if isinstance(server, SearchServer):
                            self.assertEqual(server.budget['consumed'], 12)
                        else:
                            self.assertEqual(server.calls, 12)
                        self.assertIsNone(server.pending)
                    finally:
                        server.shutdown(); server.server_close(); worker.join(3)


class ManualLiveBounds(unittest.TestCase):
    def test_recorder_blocks_mutations_expired_windows_and_consumed_budgets(self):
        from manual_production_readonly import ReadOnlyRecorder
        state = dict(deadline='2099-01-01T00:00:00+00:00', max_local=1, max_GETs=1,
                     reserved_local=1, reserved_GETs=1, operations=[])
        recorder = ReadOnlyRecorder(state)
        with patch('fc_access.production_v1.executor.EdgeExecutor.execute',
                   side_effect=AssertionError('no browser delivery')):
            for operation in ('bid', 'move', 'purchase', 'list'):
                with self.assertRaisesRegex(ValueError, 'read_only_allowlist'):
                    recorder.execute({'operation': operation})
            for operation in ('search', 'status', 'price_helpers'):
                with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
                    recorder.execute({'operation': operation})
            state['deadline'] = '2000-01-01T00:00:00+00:00'
            with self.assertRaisesRegex(ValueError, 'deadline_exhausted'):
                recorder.execute({'operation': 'watched'})
        self.assertEqual(state['operations'], [])
        self.assertEqual((state['reserved_GETs'], state['reserved_local']), (1, 1))

    def test_consumed_live_stages_refuse_replay_before_contacting_localhost(self):
        import manual_production_readonly as live
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'live-checkpoint.json'
            path.write_text(json.dumps(dict(phase='COMPLETED_BOUNDED_OPERATIONS', reserved_GETs=9)))
            (Path(td)/'valuation-followup.json').write_text('{}')
            (Path(td)/'fresh-admission.json').write_text('{}')
            with patch.object(live, 'CHECKPOINT', path), patch.object(live, 'OUT', Path(td)), \
                    patch.object(live, 'EdgeExecutor', side_effect=AssertionError('no localhost')):
                with self.assertRaisesRegex(ValueError, 'existing_live_checkpoint_no_replay'):
                    live.first()
                with self.assertRaisesRegex(ValueError, 'already_consumed_or_not_prepared'):
                    live.after_reconnect()
                with self.assertRaisesRegex(ValueError, 'already_consumed_or_budget_unavailable'):
                    live.valuation_followup()
                with self.assertRaisesRegex(ValueError, 'fresh_admission_window_consumed'):
                    live.fresh_admission()
            self.assertEqual(json.loads(path.read_text()), dict(phase='COMPLETED_BOUNDED_OPERATIONS', reserved_GETs=9))


if __name__ == '__main__':
    unittest.main(verbosity=2)
