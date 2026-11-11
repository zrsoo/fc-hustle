"""T7 audit negative controls, real artifact lineage and safe commit checks."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit_001b import (DOCS, REPLAYS, SUITE, commit_defects, in_scope, lineage_defects,
                       link_defects, load, mutation_defects, privacy, record_defects, scoped_files)


class T7Tests(unittest.TestCase):
    def test_criterion_0_fixture_pages_and_adaptive_metrics_ignore_random_pseudonym_salt(self):
        from experiments.market_discovery.discovery import Runner
        from experiments.market_discovery.replay import FixtureClock, FixtureTransport
        results = []
        for salt in ('a'*32, 'b'*32):
            clock = FixtureClock()
            runner = Runner(FixtureTransport(clock), mode='SIMULATED', clock=clock)
            runner.key = salt
            result = runner.run(9, paced=True)
            # Compare every page, selected version, modeled clock and coverage
            # metric. Only privacy pseudonyms and measured Python time vary.
            rows = [(r['criteria'], r['submitted_utc'],
                     [(a['item']['definition_id'], a['buy_now_price'], a['expires'])
                      for a in r['result']['auctions']]) for r in result['records']]
            metrics = deepcopy(result['by_strategy'])
            for strategy in metrics.values():
                del strategy['latency']['python_compute_ms']
            results.append((rows, metrics))
        self.assertEqual(results[0], results[1])

    def test_criterion_0_command_record_failures_missing_replays_skips_and_bad_times(self):
        commands = {'suite': SUITE, **{k: argv+['--output', '{output}'] for k, argv in REPLAYS.items()}}
        checks = [{'key': k, 'command': argv, 'exit_code': 0, 'started_utc': '2026-11-12T12:00:00+00:00',
                   'ended_utc': '2026-11-12T12:00:01+00:00', 'output_sha256': 'a'*64,
                   'tests_run': 168, 'skipped_tests': False, 'artifact_checks': {'checked': True}}
                  for k, argv in commands.items()]
        summary = {'checks': checks, 'status': 'PASS', 'new_live_requests': 0, 'account_mutations': 0}
        self.assertEqual(record_defects(summary), [])
        for mutation in (
            lambda s: s['checks'].pop(),
            lambda s: s['checks'][0].update(exit_code=1),
            lambda s: s['checks'][0].update(tests_run=0),
            lambda s: s['checks'][0].update(skipped_tests=True),
            lambda s: s['checks'][0].update(ended_utc='2026-11-12T11:00:00+00:00'),
            lambda s: s['checks'][1].update(command=['{python}', '-m', 'fc_access.transaction']),
            lambda s: s['checks'][1].pop('artifact_checks'),
            lambda s: s.update(new_live_requests=1),
        ):
            changed = deepcopy(summary)
            mutation(changed)
            self.assertTrue(record_defects(changed))

    def test_criterion_1_all_required_docs_fixtures_commands_and_links(self):
        names = scoped_files()
        self.assertTrue(set(DOCS) <= set(names))
        self.assertIn('experiments/market_discovery/fixtures/t5-opportunities.json', names)
        for name in DOCS+('experiments/market_discovery/README.md',):
            self.assertGreater((ROOT/name).stat().st_size, 50)
            self.assertEqual(link_defects(name, (ROOT/name).read_text(encoding='utf-8')), [])
        self.assertTrue(link_defects(DOCS[0], '[lost](missing-evidence.json)'))
        self.assertTrue(link_defects(DOCS[0], '[escape](../../../../private.json)'))

    def test_criterion_2_recompute_real_claims_reject_live_yield_and_source_promotion(self):
        self.assertEqual(lineage_defects(), [])
        report = load('experiments/market_discovery/runs/t6-analysis/report.json')
        for mutation in (
            lambda r: r.update(third_party_production_source='DataFluxor'),
            lambda r: r.update(latency_choice='BENCHMARKED_LIVE_EDGE'),
            lambda r: r['X_scenarios'][0].update(live_opportunities_per_hour=100),
            lambda r: r['X_scenarios'][0].update(synthetic_opportunities_per_hour=100),
            lambda r: r['live'].update(authenticated_observation_seconds=1800),
        ):
            changed = deepcopy(report)
            mutation(changed)
            self.assertTrue(lineage_defects(changed))

    def test_criterion_3_secrets_schema_context_and_unsafe_mutation_claims(self):
        secret = 'private'+'A'*40
        for field in ('api_key', 'token', 'client_secret', 'cookie', 'account_id', 'x-ut-sid', 'evidence_key'):
            findings = privacy('capture.json', json.dumps({field: secret}))
            self.assertTrue(findings, field)
            self.assertNotIn(secret, json.dumps(findings))
        self.assertTrue(privacy('capture.json', json.dumps({'trade_id': '1234567890'})))
        schema = (ROOT/'experiments/market_discovery/observation.schema.json').read_text()
        self.assertEqual(privacy('observation.schema.json', schema), [])
        self.assertTrue(privacy('bad.schema.json', schema+'\nBearer '+secret))
        self.assertEqual(privacy('contract.json', json.dumps({'security': [{'ApiKey': []}]})), [])
        self.assertTrue(privacy('contract.json', json.dumps({'ApiKey': secret})))
        self.assertEqual(mutation_defects({'account_mutations': 0}), [])
        self.assertTrue(mutation_defects({'account_mutations': 1}))
        self.assertTrue(mutation_defects({'account_mutations': False}))
        self.assertEqual(mutation_defects({'boundary': {'account_mutations': False}}), [])
        self.assertTrue(mutation_defects({'boundary': {'account_mutations': True}}))
        self.assertTrue(mutation_defects({'buy_intent': {'mode': 'LIVE', 'lineage': 'SIMULATED'}}))

    def test_criterion_4_commit_gate_rejects_unrelated_changes_missing_commit_or_dirty_bytes(self):
        name = 'docs/research/001b-latency.md'
        def fake_git(changed, content=b'committed'):
            def call(*args):
                if args[0] == 'merge-base':
                    return b''
                if args[0] == 'diff':
                    return changed.encode()
                if args[0] == 'show':
                    return content
                raise AssertionError(args)
            return call
        read = lambda _: b'committed'
        self.assertEqual(commit_defects('baseline', [name], fake_git(name), read), [])
        for changed in ('', name+'\nfc_execution/scheduler.py', name+'\nREADME.md',
                        name+'\ndocs/research/browser-access/live-v2.json'):
            self.assertTrue(commit_defects('baseline', [name], fake_git(changed), read))
        self.assertTrue(commit_defects('baseline', [name], fake_git(name, b'old'), read))
        for path in ('fc_execution/strategy.py', 'browser/execution-bridge/worker.js',
                     '../outside.py', 'experiments/market_discovery/../../outside.py',
                     'private-captures/key.json', '.orchestrator/state.json'):
            self.assertFalse(in_scope(path), path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
