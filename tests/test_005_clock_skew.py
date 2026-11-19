"""Browser-vs-controller clock skew (2026-11-19 01:42:17Z incident); offline.

Windows stepped the system clock back 1.241s while Edge kept its JavaScript time,
so genuine EA results looked slightly in the future and were rejected three
times, stopping the runtime on PERSISTENT_READ_FAILURE. Small leads are fresh;
large ones and old results still fail closed.
"""
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from controller_policy_fixture import Harness
from fc_access.controller_v1.protocol import parse_response
from fc_access.production_v1.contracts import CLOCK_SKEW, fresh


def ahead(h,c,lead):
    # Both browser timestamps lead together, as in the incident (network <= observed).
    v=h.ea.controller(c,(h.clock.now()+timedelta(seconds=lead)).isoformat())
    v['observed_at']=(h.clock.now()+timedelta(seconds=lead+.1)).isoformat()
    return v


class ClockSkewTests(unittest.TestCase):
    def test_bounds(self):
        self.assertTrue(fresh(-1.241,30));self.assertTrue(fresh(-CLOCK_SKEW,30));self.assertTrue(fresh(30,30))
        self.assertFalse(fresh(-CLOCK_SKEW-.001,30));self.assertFalse(fresh(30.001,30))

    def test_result_from_a_slightly_ahead_browser_clock_is_accepted(self):
        h=Harness(self.enterContext(tempfile.TemporaryDirectory()),1);self.addCleanup(h.close)
        for lead,ok in ((1.241,True),(CLOCK_SKEW-.2,True),(CLOCK_SKEW+1,False),(-31,False)):
            with self.subTest(lead=lead):
                c=h.adapter.envelope(h.ids(),'balance',{})
                v=ahead(h,c,lead)
                if ok:self.assertEqual(parse_response(v,c,now=h.clock.now())['credits'],h.ea.credits)
                else:
                    with self.assertRaises(ValueError):parse_response(v,c,now=h.clock.now())

    def test_store_accepts_the_incident_result_and_marks_it_done(self):
        h=Harness(self.enterContext(tempfile.TemporaryDirectory()),1);self.addCleanup(h.close)
        c=h.adapter.envelope(h.ids(),'balance',{});h.store.enqueue(c,h.store.peer)
        self.assertEqual(h.store.claim(h.store.peer)['id'],c['id'])
        h.store.finish(h.store.peer,c['id'],ahead(h,c,1.241))
        self.assertEqual(h.store.db.execute('SELECT state FROM c4_commands WHERE id=?',(c['id'],)).fetchone()[0],'DONE')
        self.assertEqual(h.store.db.execute("SELECT count(*) FROM c4_events WHERE kind='RESULT_REJECTED'").fetchone()[0],0)


if __name__=='__main__':unittest.main(verbosity=2)
