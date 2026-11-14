"""Independent behavioral replay of retained 002-05 synthetic native evidence."""
from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.config import Config
from fc_access.actors_v1.occupancy import assess
from fc_access.production_v1.contracts import stamp
OUT=ROOT/'docs/research/002/002-05'


class Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence=json.loads((OUT/'native-fixtures.json').read_text())
        cls.samples={s['name']:s for s in evidence}
        if len(cls.samples)!=len(evidence): raise AssertionError('duplicate fixture names')

    def replay(self,name):
        sample=self.samples[name]
        self.assertEqual(sample['command']['operation'],'transfer_list')
        return assess(sample['response'],sample['command'],now=stamp(sample['now']),source='native')

    def test_c0_c2_all_states_cardinality_over_cap_and_cli_policy(self):
        for n in [0,5,49,50,51,75,100]:
            e=self.replay(f'complete-{n}')
            self.assertEqual(e['occupied'],n)
            self.assertEqual(e['enrollment_allowed'],n<50)
            self.assertEqual(e['reason'],'TRANSFER_LIST_OVER_CAP' if n>50 else
                'TRANSFER_LIST_FULL' if n==50 else 'TRANSFER_LIST_AVAILABLE')
        states=[r['trade_state'] for r in self.samples['complete-5']['response']['result']['auctions']]
        self.assertEqual(states,['active','expired','closed','inactive',None])
        cfg=json.loads((OUT/'defaults.json').read_text())
        self.assertEqual(cfg['max_transfer_list_occupied'],50)
        self.assertEqual(cfg['max_enrolled_auctions'],50)
        result=subprocess.run([sys.executable,'-m','fc_access.actors_v1','config','--file',str(OUT/'defaults.json')],
            cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),Config(**cfg).export())

    def test_c1_c3_negative_artifacts_fail_closed_and_keep_reason(self):
        expected={
            'missing-wire':'UNKNOWN','missing-repository':'UNKNOWN','unknown-end':'UNKNOWN',
            'callback-more':'TRUNCATED','wire-more':'TRUNCATED','repository-more':'TRUNCATED',
            'callback-truncated':'CONFLICT','wire-truncated':'CONFLICT','repository-truncated':'CONFLICT',
            'wire-state-conflict':'CONFLICT','wire-item-conflict':'CONFLICT','wire-version-conflict':'CONFLICT',
            'repository-conflict':'CONFLICT','wire-duplicate':'CONFLICT','repository-duplicate':'CONFLICT',
            'callback-duplicate':'CONFLICT','stale':'STALE'}
        for name,suffix in expected.items():
            e=self.replay(name)
            self.assertFalse(e['enrollment_allowed'],name)
            self.assertIsNone(e['occupied'],name)
            self.assertEqual(e['reason'],'TRANSFER_LIST_'+suffix,name)
        for name in ['cache','noAuth','http401','fanout','malformed']:
            self.assertFalse(self.replay(name)['enrollment_allowed'])
        # Old complete evidence cannot become fresh just because artifacts persist.
        from datetime import timedelta
        s=self.samples['complete-5']
        self.assertFalse(assess(s['response'],s['command'],now=stamp(s['now'])+timedelta(seconds=31),source='native')['enrollment_allowed'])


if __name__=='__main__':unittest.main(verbosity=2)
