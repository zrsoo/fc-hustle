"""Offline encoding and exclusive additional-attempt regressions; no desktop/EA."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1 import gate_00203 as gate


class Desktop(unittest.TestCase):
    def valid(self):
        return dict(observed_at=datetime.now(timezone.utc).isoformat(),edge_control_verified=True,
                    foreground_verified=True,official_tab=True,extensions_manager=False)

    def result(self,raw,code=0):return SimpleNamespace(stdout=raw,returncode=code)

    def test_explicit_binary_transport_ignores_locale_and_unrelated_stderr(self):
        raw=json.dumps(self.valid()).encode()
        result=self.result(raw);result.stderr=b'not retained: \x81'
        with patch.object(gate.subprocess,'run',return_value=result) as run:
            self.assertTrue(gate.desktop_preflight()['official_tab'])
        args,kw=run.call_args
        self.assertIn('preflight-json',args[0]);self.assertFalse(kw['text'])
        self.assertFalse(kw['check']);self.assertEqual(kw['timeout'],20)
        with patch.object(gate.subprocess,'run',return_value=self.result(b'\xef\xbb\xbf'+raw)):
            self.assertTrue(gate.desktop_preflight()['edge_control_verified'])

    def test_original_undefined_cp1252_byte_never_becomes_missing_stdout_attribute_error(self):
        # A non-ASCII UI label from old mixed output: UTF-8 D0 81 is Cyrillic Yo.
        mixed=json.dumps(self.valid()).encode()+b'\nControlType.Button | \xd0\x81\n'
        with self.assertRaises(UnicodeDecodeError):mixed.decode('cp1252')
        with patch.object(gate.subprocess,'run',return_value=self.result(mixed)):
            with self.assertRaisesRegex(ValueError,'desktop_output_invalid_json'):gate.desktop_preflight()
        with patch.object(gate.subprocess,'run',return_value=self.result(b'\x81')):
            with self.assertRaisesRegex(ValueError,'desktop_output_invalid_utf8'):gate.desktop_preflight()

    def test_malformed_empty_missing_unbounded_wrong_schema_and_duplicate_documents(self):
        valid=self.valid()
        cases=[None,'text',b'',b'x'*16385,b'not JSON',b'{}',b'[]',b'null',b'{"x":',
               b'{"official_tab":false,"official_tab":true}',
               json.dumps(valid).encode()*2,json.dumps({**valid,'unrelated_label':'ignored?'}).encode(),
               json.dumps({**valid,'official_tab':'true'}).encode(),
               json.dumps({**valid,'observed_at':'not a timestamp'}).encode(),
               json.dumps({**valid,'observed_at':'2000-01-01T00:00:00Z'}).encode()]
        for raw in cases:
            with self.subTest(raw_type=type(raw).__name__),patch.object(gate.subprocess,'run',return_value=self.result(raw)):
                with self.assertRaises(ValueError):gate.desktop_preflight()

    def test_foreground_official_identity_and_control_checks_fail_closed(self):
        for field in ('foreground_verified','official_tab','edge_control_verified','extensions_manager'):
            value=self.valid();value[field]=not value[field]
            with self.subTest(field=field),patch.object(gate.subprocess,'run',return_value=self.result(json.dumps(value).encode())):
                with self.assertRaisesRegex(ValueError,'official_Edge_tab_required'):gate.desktop_preflight()

    def test_subprocess_failure_timeout_and_unavailable_are_controlled_without_output(self):
        with patch.object(gate.subprocess,'run',return_value=self.result(None,1)):
            with self.assertRaisesRegex(ValueError,'desktop_subprocess_failed'):gate.desktop_preflight()
        for error,reason in [(subprocess.TimeoutExpired('powershell',20),'timeout'),(OSError('private details'),'unavailable')]:
            with patch.object(gate.subprocess,'run',side_effect=error):
                with self.assertRaisesRegex(ValueError,'desktop_subprocess_'+reason):gate.desktop_preflight()


class AdditionalAttempt(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        patcher=patch.object(gate,'THIRD_CHECKPOINT',Path(temporary.name)/'absent-third.json')
        patcher.start();self.addCleanup(patcher.stop)
        fourth=patch.object(gate,'FOURTH_CHECKPOINT',Path(temporary.name)/'absent-fourth.json')
        fourth.start();self.addCleanup(fourth.stop)
        fifth=patch.object(gate,'FIFTH_CHECKPOINT',Path(temporary.name)/'absent-fifth.json')
        fifth.start();self.addCleanup(fifth.stop)

    def test_new_attempt_real_foundation_offline_proof_and_original_rejection(self):
        from test_00203_gate import Gate
        with tempfile.TemporaryDirectory() as d:
            state,_,bids=Gate().scenario(d,authorization=gate.original_failure())
            self.assertEqual(state['status'],'PASS',state.get('reason'));self.assertEqual(bids,0)
            self.assertEqual(gate.require_pass(Path(d)/'gate.json')['decision'],'BID/ELIGIBLE')
            bad=deepcopy(state);bad['authorization']['previous_capture_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'wrong_gate_attempt_authorization'):gate.admission_proof(bad)
        with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'):gate.require_pass(gate.CHECKPOINT)

    def test_original_failure_immutable_new_attempt_independent_budget_and_selection(self):
        original=gate.CHECKPOINT.read_bytes();authority=gate.original_failure()
        with tempfile.TemporaryDirectory() as d,patch.object(gate,'REMEDIATION_CHECKPOINT',Path(d)/'gate.json'):
            w=gate.Window(gate.selected_checkpoint(gate.AUTHORIZED_ATTEMPT),authorization=authority)
            self.assertEqual(w.state['attempt'],2);self.assertEqual(w.state['operations'],[])
            self.assertEqual(gate.selected_checkpoint(),w.path)
            gate.validate_attempt(w.state)
            for change in ({'attempt_id':'unapproved'},{'attempt':3},{'authorization':{}}):
                with self.assertRaises(ValueError):gate.validate_attempt({**w.state,**change})
            with self.assertRaises(FileExistsError):gate.Window(w.path,authorization=authority)
            w.stop('offline_fixture_failure')
            with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'):gate.require_pass()
        self.assertEqual(gate.CHECKPOINT.read_bytes(),original) # Immutable captured evidence only.
        with self.assertRaisesRegex(ValueError,'items_4_through_12_blocked'):gate.require_pass(gate.CHECKPOINT)

    def test_preflight_consumes_only_new_slot_failure_is_sealed_and_no_service_called_or_retry(self):
        with tempfile.TemporaryDirectory() as d,patch.object(gate,'REMEDIATION_CHECKPOINT',Path(d)/'gate.json'),\
             patch.object(gate,'desktop_preflight',side_effect=ValueError('desktop_output_invalid_utf8')) as preflight,\
             patch.object(gate.EdgeExecutor,'request',side_effect=AssertionError('must not contact service')):
            s=gate.main(['--attempt',gate.AUTHORIZED_ATTEMPT])
            self.assertEqual(s['status'],'FAILURE/BLOCKED');self.assertIsNone(s['elapsed_ns'])
            captured=json.loads(gate.REMEDIATION_CHECKPOINT.read_text())
            self.assertEqual(captured['reason'],'desktop_output_invalid_utf8')
            self.assertEqual(captured['operations'],[]);self.assertEqual(captured['cache_reads'],[])
            self.assertEqual(captured['evidence_sha256'],gate.digest({k:v for k,v in captured.items() if k!='evidence_sha256'}))
            with self.assertRaises(FileExistsError):gate.main(['--attempt',gate.AUTHORIZED_ATTEMPT])
            self.assertEqual(preflight.call_count,1)

    def test_successful_preflight_passes_same_consumed_window_to_existing_runner(self):
        with tempfile.TemporaryDirectory() as d,patch.object(gate,'REMEDIATION_CHECKPOINT',Path(d)/'gate.json'),\
             patch.object(gate,'desktop_preflight',return_value={'offline_fixture':True}),\
             patch.object(gate,'run',return_value={'offline_only':True}) as run:
            self.assertEqual(gate.main(['--attempt',gate.AUTHORIZED_ATTEMPT]),{'offline_only':True})
            self.assertEqual(run.call_args.kwargs['window'].state['attempt'],2)
            self.assertEqual(run.call_args.kwargs['window'].path,gate.REMEDIATION_CHECKPOINT)
            with self.assertRaises(FileExistsError):gate.main(['--attempt',gate.AUTHORIZED_ATTEMPT])


if __name__=='__main__':unittest.main(verbosity=2)
