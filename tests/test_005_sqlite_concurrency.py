"""Concurrent synthetic row identity and safe native-fault diagnostics."""
import faulthandler
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.watchdog import fault_trace
from unittest.mock import patch


class SQLiteConcurrency(unittest.TestCase):
    def test_pretransport_status_failure_retains_invocation_type_without_values(self):
        sys.path.insert(0,str(ROOT/'tests'))
        from controller_policy_fixture import Harness
        with tempfile.TemporaryDirectory() as path:
            h=Harness(path,1)
            try:
                with patch.object(h.adapter,'status_batch',side_effect=ValueError('VALUE_CANARY_SHOULD_NOT_BE_RETAINED')):
                    self.assertIsNone(h.controller._status([],h.ids()))
                value=h.metrics('STATUS_UNKNOWN')[-1]
                self.assertEqual(value['exception_type'],'ValueError');self.assertEqual(len(value['read_id']),32)
                self.assertNotIn('CANARY',json.dumps(value));self.assertEqual(h.ea.calls,[])
            finally:h.close()

    def test_actual_controller_connection_preserves_all_concurrent_blob_results(self):
        p=subprocess.run([sys.executable,str(ROOT/'tests/stress_005_sqlite.py'),'--mode','controller','--seconds','2'],
                         cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        value=json.loads(p.stdout);self.assertEqual(value['status'],'SYNTHETIC_STRESS_PASS')
        self.assertEqual(value['readers'],12);self.assertGreater(value['reads'],12)

    def test_fault_trace_contains_stack_metadata_without_local_values(self):
        with tempfile.TemporaryDirectory() as path:
            log=Path(path)/'python-fault.txt';was_enabled=faulthandler.is_enabled()
            sensitive_local='VALUE_CANARY_SHOULD_NEVER_ENTER_FAULT_TRACE'
            with fault_trace(log) as stream:
                self.assertTrue(faulthandler.is_enabled())
                faulthandler.dump_traceback(file=stream,all_threads=True)
            self.assertEqual(faulthandler.is_enabled(),was_enabled)
            value=log.read_text();self.assertIn('test_fault_trace_contains_stack_metadata',value)
            self.assertNotIn(sensitive_local,value)
            with self.assertRaises(FileExistsError):
                with fault_trace(log):pass


if __name__=='__main__':unittest.main(verbosity=2)
