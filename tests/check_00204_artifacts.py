"""Offline artifact/CLI contract checks for 002-04; no source-byte assertions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.config import Config


class Artifacts(unittest.TestCase):
    def cli(self,*args):
        r=subprocess.run([sys.executable,'-m','fc_access.actors_v1',*args],cwd=ROOT,
            capture_output=True,text=True,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr)
        return r.stdout

    def test_c0_defaults_artifact_and_config_override_contract(self):
        path=ROOT/'docs/research/002/002-04/defaults.json'
        self.assertEqual(json.loads(self.cli('config','--file',str(path))),Config().export())
        data=json.loads(path.read_text());data.update(max_search_bid=1500,target_check_interval_seconds=20)
        with tempfile.TemporaryDirectory() as temp:
            changed=Path(temp)/'config.json';changed.write_text(json.dumps(data))
            self.assertEqual(json.loads(self.cli('config','--file',str(changed))),Config(**data).export())
        with self.assertRaises(ValueError):Config(**(data|{'max_enrolled_auctions':51}))

    def test_c1_c5_reviewable_operator_interfaces_and_dependencies(self):
        top=self.cli('--help')
        for op in ('acquirer','bidder','executor','status','timeline','decisions','blocked','export','retain'):
            self.assertIn(op,top)
            help_text=self.cli(op,'--help')
            self.assertIn('usage:',help_text)
        self.assertIn('--cycles',self.cli('acquirer','--help'))
        self.assertIn('--since',self.cli('decisions','--help'))
        self.assertIn('--until',self.cli('decisions','--help'))
        self.assertIn('--trade-id',self.cli('timeline','--help'))
        report=(ROOT/'docs/research/002/002-04/REPORT.md').read_text()
        for path in ('fc_access/actors_v1','tests/test_00204_actors.py','tests/check_00204_artifacts.py',
            'tests/test_bidding_v1.py','tests/test_001d04_pricing.py'):
            self.assertTrue((ROOT/path).exists(),path);self.assertIn(path,report)
        for contract in ('UNKNOWN','WAL/FULL','600','25','5000','50','24-hour','macr','minb',
            'No sustained live actor','prunes zero events','002-05','002-11'):
            self.assertIn(contract,report)
        # The consumed dependency is read-only historical EA evidence, not
        # implementation provenance enforced against mutable source files.
        gate=json.loads((ROOT/'docs/research/002/002-03/attempts/20261114-adapter-repair-gate-06/gate.json').read_text())
        self.assertEqual(gate['status'],'PASS')
        self.assertTrue(gate['dependent_tasks_allowed'])
        self.assertLess(gate['elapsed_ns'],30_000_000_000)


if __name__=='__main__':unittest.main(verbosity=2)
