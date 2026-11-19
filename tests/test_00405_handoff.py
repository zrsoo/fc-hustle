"""Reject incomplete verification, forged classifications, unsafe handoff and push claims."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import check_00405 as check
import check_00302_production as historical
from record_00405 import commands


class HandoffChecks(unittest.TestCase):
    def test_early_denial_fixture_sends_exact_body_once_and_never_hides_transport_error(self):
        from http_fixture import CompleteRequestConnection
        sent = []
        client = CompleteRequestConnection('127.0.0.1', 49152)
        body = b'{"operation":"search","operation":"buy"}'
        with patch.object(client, 'send', side_effect=sent.append):
            client.request('POST', '/run', body, {'Origin':'https://evil.invalid'})
        self.assertEqual(len(sent), 1)
        headers, actual = sent[0].split(b'\r\n\r\n', 1)
        self.assertEqual(actual, body)
        self.assertIn(b'POST /run HTTP/1.1', headers)
        self.assertIn(b'Origin: https://evil.invalid', headers)
        self.assertIn(('Content-Length: '+str(len(body))).encode(), headers)
        client = CompleteRequestConnection('127.0.0.1', 49152)
        with patch.object(client, 'send', side_effect=ConnectionAbortedError('fixture failure')) as send:
            with self.assertRaises(ConnectionAbortedError):client.request('POST', '/run', body)
        self.assertEqual(send.call_count, 1)

    def test_report_and_individual_contract_gates_reject_missing_evidence_or_live_promotions(self):
        # Small in-memory document exercises the gate; it is never saved as evidence.
        value = check.load(ROOT/'docs/research/004/004-05/handoff.json')
        report = '\n'.join([check.VERDICT, '60-second window retains expiry risk',
            'discarded uncertainty may create untracked participation',
            'Architecture Persistence Verification Failures Timings Probe Hands-on Limitations Publication',
            '--port 8784 --database private-captures/controller-v1/controller.sqlite',
            '--context private-captures/controller-v1/public-context.json',
            *[r['operation'] for r in value['contracts']],
            *['python -m fc_access.controller_v1 '+action+' ' for action in ('run','status','pause','stop')]])
        check.validate_handoff(value, report)
        for edit in (lambda r:r['coverage'].pop(), lambda r:r['coverage'][0].update(negative=''),
                     lambda r:r.update(new_live_windows=['unbudgeted']), lambda r:r.update(new_mutations=1),
                     lambda r:r.update(deferred=[]), lambda r:r['contracts'].pop(),
                     lambda r:r['contracts'][0].update(classification='PASS'),
                     lambda r:r['contracts'][0].update(limitation=''),
                     lambda r:r['contracts'][0].update(evidence=['docs/absent-evidence.json']),
                     lambda r:r['contracts'][0].update(actual_live_targets=11)):
            changed = deepcopy(value);edit(changed)
            with self.assertRaises(ValueError):check.validate_handoff(changed, report)
        for text in ('60-second window retains expiry risk', 'discarded uncertainty may create untracked participation',
                     'Architecture', 'python -m fc_access.controller_v1 run '):
            with self.assertRaises(ValueError):check.validate_handoff(value, report.replace(text, ''))
        from record_00403_offline import record
        trace = check.load(check.OUT/'synthetic-trace.json')
        # The stored trace is the sealed 004-05 synthetic snapshot; it is never
        # re-recorded. Its validator still rejects every tampered copy.
        check.validate_trace(trace, deepcopy(trace))
        for edit in (lambda r:r.update(classification='LIVE_VERIFIED'),
                     lambda r:r['requests'].update(balance=0),
                     lambda r:r['acquisition'][0].update(expiry_misses=99),
                     lambda r:r.update(global_ten_participation_guarantee=True)):
            changed = deepcopy(trace);edit(changed)
            with self.assertRaises(ValueError):check.validate_trace(changed, trace)
        # The MAINTENANCE phase intentionally changes request inventory and
        # timing, so current behavior is compared on the snapshot's invariants.
        recomputed = record(historical=True)
        for key in ('classification','initial_confirmed_members','terminal_lost','final',
                    'maximum_parallel_requests','global_ten_participation_guarantee'):
            self.assertEqual(recomputed[key], trace[key], key)
        for op in ('balance','search','caps','bid'):
            self.assertEqual(recomputed['requests'][op], trace['requests'][op], op)
        self.assertTrue(all(c['phase']=='ACQUIRING' for c in recomputed['trace'] if c['operation']=='balance'))
        self.assertNotIn(('bid','MAINTENANCE'),{(c['operation'],c['phase']) for c in recomputed['trace']})

    def receipt(self):
        return dict(task='004-05', evidence_class='OFFLINE_ONLY', group='python', status='PASS', results=[
            dict(command=['{python}', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], exit_code=0,
                 seconds=1.2, finished='2030-01-01T00:00:00+00:00', stdout='out', stderr='err', tests_run=1)])

    def test_full_suite_receipt_requires_actual_methods_success_and_complete_inventory(self):
        expected = self.receipt()['results'][0]['command']
        log = 'test_case (example.Case.test_case) ... ok\n\nRan 1 test in 1.200s\n\nOK\n'
        def validate(value, output=log, names=None):
            return check.validate_receipt(value, [expected], lambda n: output if n == 'err' else '',
                                          test_ids=['example.Case.test_case'] if names is None else names)
        validate(self.receipt())
        for edit in (lambda r:r.update(status='FAIL'), lambda r:r.update(results=[]),
                     lambda r:r.update(evidence_class='LIVE_VERIFIED'),
                     lambda r:r.update(group='node'),
                     lambda r:r['results'][0].update(exit_code=1),
                     lambda r:r['results'][0].update(tests_run=2),
                     lambda r:r['results'][0].update(command=['{python}', 'some_subset.py'])):
            r = self.receipt();edit(r)
            with self.assertRaises(ValueError):validate(r)
        for output in ('', log.replace('... ok', '... skipped'), log.replace('OK', 'FAILED (errors=1)'),
                       log.replace('example.Case.test_case', 'other.Case.test_case')):
            with self.assertRaises(ValueError):validate(self.receipt(), output)
        with self.assertRaises(ValueError):validate(self.receipt(), names=['example.Case.test_case', 'example.Case.untested'])
        check.validate_report_results('python', self.receipt()['results'], '| python | 1 | PASS | 1.200 |')
        for report in ('| python | 2 | PASS | 1.200 |', '| python | 1 | PASS | 0.200 |',
                       '| python | 1 | FAIL | 1.200 |'):
            with self.assertRaises(ValueError):check.validate_report_results('python', self.receipt()['results'], report)

    def test_stopped_requires_process_listener_scheduler_and_observation(self):
        clean = dict(observed_at='2030-01-01T00:00:00+00:00', production_workers=[],
                     production_listeners=[], scheduled_mutation_jobs=[])
        check.validate_stopped(clean)
        for key in ('production_workers', 'production_listeners', 'scheduled_mutation_jobs'):
            changed = deepcopy(clean);changed[key] = [dict(pid=42)]
            with self.assertRaisesRegex(ValueError, 'active_'):check.validate_stopped(changed)
        changed = dict(clean, observed_at='2030-01-01T00:00:00')
        with self.assertRaises(ValueError):check.validate_stopped(changed)

    def test_historical_catalog_is_fixed_while_current_node_discovery_includes_new_mode(self):
        base = ROOT/'docs/research/003/003-02'
        value = json.loads((base/'node-suites.json').read_text())
        historical.validate_receipt('node', value, lambda n:(base/n).read_text())
        for change in ('missing', 'extra', 'failed'):
            altered = deepcopy(value)
            if change == 'missing':altered['results'].pop()
            if change == 'extra':altered['results'].append(dict(altered['results'][0], command=['node', 'tests/controller_native_checks.cjs']))
            if change == 'failed':altered['results'][0]['exit_code'] = 1
            with self.assertRaises(ValueError):historical.validate_receipt('node', altered, lambda n:(base/n).read_text())
        current = commands('node')
        self.assertEqual(current, [['node', p.relative_to(ROOT).as_posix()] for p in sorted((ROOT/'tests').glob('*checks.cjs'))])
        for name in ('controller_native_checks.cjs', 'controller_policy_native_checks.cjs', 'controller_work_native_checks.cjs'):
            self.assertIn(['node', 'tests/'+name], current)

    def test_publication_requires_real_main_clean_tree_ancestry_and_pushed_commit(self):
        receipt = dict(implementation_commit='a'*40, push_exit_code=0, push_output='main -> main')
        for failure in (None, 'branch', 'dirty', 'remote', 'ancestry', 'paths'):
            def fake(*argv):
                if argv[0] == 'branch':return 'topic' if failure == 'branch' else 'main'
                if argv[0] == 'status':return ' M source' if failure == 'dirty' else ''
                if argv[0] == 'rev-parse':return 'b'*40
                if argv[0] == 'ls-remote':
                    if failure == 'remote':raise ValueError('remote unavailable')
                    return 'b'*40+' refs/heads/main'
                if argv[0] == 'merge-base':
                    if failure == 'ancestry':raise ValueError('not ancestor')
                    return ''
                if argv[0] == 'ls-files':return '' if failure == 'paths' else '\n'.join([
                    'docs/research/004/REPORT.md', 'fc_access/controller_v1/controller.py',
                    'browser/production-v1/controller.js', 'tests/check_00405.py'])
                raise AssertionError(argv)
            if failure:
                with self.subTest(failure=failure), self.assertRaises((ValueError, IndexError)):
                    check.validate_publication(receipt, fake)
            else:check.validate_publication(receipt, fake)
        for changed in (dict(receipt, push_exit_code=1), dict(receipt, push_output=''), dict(receipt, implementation_commit='')):
            with self.assertRaises(ValueError):check.validate_publication(changed, lambda *args:self.fail('must reject before Git'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
