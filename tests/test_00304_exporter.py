"""Exporter cadence and failure tests; fixtures provide no live coverage."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.continuous_v1.control import Control
from fc_access.continuous_v1.exporter import Exporter


class Exports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.tick=0
        self.control=Control(self.root/'state/control.sqlite3',clock=lambda:self.tick)
        self.addCleanup(self.control.close)
        self.control.append('fixture','RUN_OPEN',context={},source='fixture')
        self.calls=[]
        def collect(state,transport,output,*,revision):
            self.calls.append((str(output),revision));return dict(path=str(output))
        self.export=Exporter(self.root/'state',self.root/'transport',self.root/'exports','fixture','test-revision',
                             clock=lambda:self.tick,collect=collect)
        self.addCleanup(self.export.close)

    def snapshot(self):
        self.control.append('fixture','SNAPSHOT',healthy_observed_seconds=self.tick)

    def test_waits_for_real_snapshot_and_collects_at_300_seconds_without_a_lifetime_cap(self):
        self.assertTrue(self.export.step());self.assertEqual(self.calls,[])
        self.snapshot();self.export.step();self.assertEqual(len(self.calls),1)
        self.tick=299;self.snapshot();self.export.step();self.assertEqual(len(self.calls),1)
        for t in (300,600,14400,28800):
            self.tick=t;self.snapshot();self.assertTrue(self.export.step())
        self.assertEqual(len(self.calls),5)
        self.assertEqual(len({r[0] for r in self.calls}),5)

    def test_stopped_segment_gets_a_final_export_and_never_restarts(self):
        self.snapshot();self.export.step()
        self.control.append('fixture','RUN_STOPPED')
        self.assertFalse(self.export.step());self.assertEqual(len(self.calls),2)
        self.assertIsNone(self.control.latest('fixture','READY'))

    def test_exporter_refuses_to_follow_a_new_owner_or_replace_existing_outputs(self):
        self.control.append('other','RUN_OPEN',context={},source='fixture')
        self.assertFalse(self.export.step());self.assertEqual(self.calls,[])
        with self.assertRaises(FileExistsError):
            Exporter(self.root/'state',self.root/'transport',self.root/'exports','fixture','revision')

    def test_failed_collection_requests_controlled_stop_and_retains_incident_without_replay(self):
        self.snapshot()
        def fail(*args,**kwargs):raise OSError('offline disk failure')
        self.export.collect=fail
        with self.assertRaises(OSError):self.export.step()
        self.export.fail(OSError())
        self.assertEqual(self.control.latest('fixture','STOP_REQUESTED')['reason'],'EVIDENCE_EXPORT_FAILED')
        self.assertTrue(self.control.latest('fixture','INCIDENT')['incident_id'])
        self.assertIsNone(self.control.latest('fixture','READY'))

    def test_summary_does_not_promote_offline_or_native_captures_to_live_pass(self):
        self.snapshot();self.export.step()
        rows=[json.loads(r) for r in (self.root/'exports/events.jsonl').read_text().splitlines()]
        self.assertEqual(rows[0]['source'],'fixture')
        self.assertEqual(rows[0]['live_coverage'],'LIVE-UNVERIFIED_UNTIL_INDEPENDENT_CASE_REVIEW')
        self.assertNotIn('LIVE-VERIFIED',json.dumps(rows))


if __name__=='__main__':unittest.main(verbosity=2)
