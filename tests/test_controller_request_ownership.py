"""Shared ownership regression, including actual captured native follow-up methods."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RequestOwnership(unittest.TestCase):
    def run_node(self,name):
        result=subprocess.run(['node','tests/'+name],cwd=ROOT,capture_output=True,
            encoding='utf-8',errors='strict',timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout

    def test_read_background_auxiliary_timeout_and_mutation_ownership(self):
        self.assertIn('PASS 33 shared ownership cases',self.run_node('controller_shared_ownership_checks.cjs'))

    def test_captured_clear_and_list_native_followups_use_owned_requests(self):
        self.assertIn('PASS controller maintenance',self.run_node('controller_work_native_checks.cjs'))


if __name__=='__main__':unittest.main(verbosity=2)
