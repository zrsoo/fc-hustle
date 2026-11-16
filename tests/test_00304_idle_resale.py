"""Real interprocess lock contention with offline account/native fixtures only."""
from contextlib import contextmanager
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from actors_fixture import create
from fc_access.actors_v1.actors import Bidder
from fc_access.actors_v1.locking import process_lock
from fc_access.production_v1.resale import Resale
import test_00208_resale as resale_cases


class IdleResale(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.f,self.page,self.clock=create(temp.name)
        self.addCleanup(self.page.close);self.addCleanup(self.f.close)

    @contextmanager
    def foreign_mutation_lock(self,path):
        code="from pathlib import Path\nimport sys\nfrom fc_access.actors_v1.locking import process_lock\nwith process_lock(Path(sys.argv[1])):\n print('LOCKED',flush=True)\n sys.stdin.buffer.read(1)\n"
        child=subprocess.Popen([sys.executable,'-c',code,str(path)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            self.assertEqual(child.stdout.readline().strip(),b'LOCKED')
            yield child
        finally:
            if child.poll() is None:
                try:child.communicate(input=b'x',timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.communicate()
            else:child.communicate()

    def won_case(self):
        case=resale_cases.Acceptance('test_c0_physical_definition_trade_and_paid_mismatches_never_move_or_list')
        self.addCleanup(case.doCleanups);case.setUp();case.candidate_win()
        with patch.object(Resale,'cycle',return_value=None):case.b.cycle()
        self.assertTrue(any(e['reason']=='WON_VERIFIED' for e in case.f.journal.trace(scope=case.f.registry.scope)))
        return case

    def test_idle_bidder_finishes_while_other_process_retains_mutation_lock(self):
        with self.foreign_mutation_lock(self.f.journal_path.with_suffix('.bid.lock')) as child:
            before=len(self.page.calls)
            Bidder(self.f,clock=self.clock.monotonic,sleep=self.clock.sleep).run(cycles=1)
            self.assertIsNone(child.poll())
            self.assertEqual(len(self.page.calls),before)
            events=self.f.registry.events()
            self.assertTrue(any(e.get('reason')=='IDLE' for e in events))
            self.assertTrue(any(e.get('reason')=='CYCLE_FINISHED' for e in events))
            self.assertFalse(any(e.get('reason')=='CYCLE_BLOCKED' for e in events))

    def test_duplicate_bidder_role_and_stale_owner_still_fail_closed(self):
        with process_lock(self.f.journal_path.with_suffix('.bidder.lock')):
            with self.assertRaisesRegex(ValueError,'process_already_running'):
                Bidder(self.f).run(cycles=1)
        self.f.journal.session(self.f.registry.scope,'e'*32)
        with self.assertRaises(ValueError):Resale(self.f).cycle()
        self.assertFalse(self.page.calls)

    def test_unseeded_verified_win_still_requires_lock_then_moves_only_under_existing_guards(self):
        case=self.won_case();service=Resale(case.f)
        self.assertIsNone(case.f.journal.db.execute('SELECT 1 FROM resales_v1 WHERE scope=?',(case.f.registry.scope,)).fetchone())
        @contextmanager
        def unavailable(*args,**kwargs):raise ValueError('required_mutation_guard');yield
        before=len(case.page.calls)
        with patch('fc_access.actors_v1.locking.process_lock',unavailable):
            with self.assertRaisesRegex(ValueError,'required_mutation_guard'):service.cycle()
        self.assertEqual(len(case.page.calls),before);self.assertFalse(case.page.mutations)
        service.cycle()
        self.assertEqual([c['operation'] for c in case.page.mutations],['move'])
        self.assertEqual(case.state(),'MOVED')

    def test_active_and_pending_resale_work_never_takes_idle_shortcut(self):
        case=self.won_case();service=Resale(case.f);service.seed()
        @contextmanager
        def unavailable(*args,**kwargs):raise ValueError('required_mutation_guard');yield
        with patch('fc_access.actors_v1.locking.process_lock',unavailable):
            with self.assertRaisesRegex(ValueError,'required_mutation_guard'):service.cycle()
        case.page.effect=False;case.page.timeout=True;service.cycle()
        self.assertTrue(case.f.journal.db.execute("SELECT 1 FROM resale_writes_v1 WHERE state!='RECONCILED'").fetchone())
        # A contradictory terminal row cannot hide a consumed unresolved write.
        case.f.journal.db.execute("UPDATE resales_v1 SET state='LISTED'")
        with patch('fc_access.actors_v1.locking.process_lock',unavailable):
            with self.assertRaisesRegex(ValueError,'required_mutation_guard'):service.cycle()

    def test_completed_historical_win_does_not_block_idle_bidder_again(self):
        case=self.won_case();service=Resale(case.f);service.cycle();service.cycle()
        self.assertEqual(case.state(),'LISTED')
        with self.foreign_mutation_lock(case.f.journal_path.with_suffix('.bid.lock')) as child:
            before=len(case.page.calls);service.cycle()
            self.assertIsNone(child.poll());self.assertEqual(len(case.page.calls),before)


if __name__=='__main__':unittest.main(verbosity=2)
