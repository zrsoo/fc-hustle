"""Behavioral native seam and replayable artifact checks, without source hashes."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from record_00403_offline import record
import test_00403_controller as controller_tests


class Artifacts(unittest.TestCase):
    def test_shipped_javascript_discovery_bid_status_owned_and_local_change_seams(self):
        for suite in ['controller_policy_native_checks.cjs','controller_native_checks.cjs']:
            p=subprocess.run(['node','tests/'+suite],cwd=ROOT,capture_output=True,text=True,timeout=45)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_all_acceptance_criteria_have_executable_behavioral_checks(self):
        manifest=json.loads((ROOT/'docs/research/004/004-03/acceptance.json').read_text())
        self.assertEqual([r['criterion'] for r in manifest['coverage']],list(range(11)))
        available=set(unittest.defaultTestLoader.getTestCaseNames(controller_tests.ControllerAcceptance))
        for row in manifest['coverage']:
            self.assertTrue(row['tests']);self.assertTrue(set(row['tests'])<=available)
        self.assertEqual(manifest['classification'],'OFFLINE_VALIDATED_FULL_E2E_PENDING')
        self.assertTrue((ROOT/'docs/research/004/004-03/REPORT.md').is_file())

    def test_recorded_and_recomputed_complete_offline_lifecycle(self):
        stored=json.loads((ROOT/'docs/research/004/004-03/offline.json').read_text())
        for historical,result in ((True,stored),(False,record())):
            self.assertEqual(result['classification'],'SYNTHETIC_OFFLINE_ONLY')
            self.assertEqual(result['initial_confirmed_members'],10)
            self.assertEqual(result['terminal_lost'],10)
            self.assertEqual(result['maximum_parallel_requests'],1)
            self.assertEqual(result['final'],dict(phase='ACQUIRING',lifecycle='HALTED',reason='ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD'))
            # 004-04 adds one complete maintenance scan after each managed cycle.
            # The sealed 004-03 capture retains its original request inventory.
            self.assertEqual(result['requests'],dict(balance=2,search=3,caps=1,watched=1,transfer_list=1 if historical else 3,bid=20,status_batch=4 if historical else 5))
            self.assertEqual(len(result['cycles']),2)
            self.assertTrue(all(c['target']==5 and c['elapsed']>0 and c['missed_targets']>=0 for c in result['cycles']))
            self.assertGreater(result['acquisition'][0]['burst_elapsed'],0)
            self.assertGreater(result['acquisition'][0]['handoff_elapsed'],0)
            self.assertFalse(result['global_ten_participation_guarantee'])
            self.assertTrue(all(c['phase']=='ACQUIRING' for c in result['trace'] if c['operation']=='balance'))


if __name__=='__main__':
    # Importing a test class above is for manifest names, not double execution.
    unittest.main(defaultTest='Artifacts',verbosity=2)
