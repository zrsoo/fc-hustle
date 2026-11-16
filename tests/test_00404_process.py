"""Actual OS process interruption; synthetic server effects and real SQLite survive."""
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from controller_work_fixture import harness,won,effects
from native_price_fixture import auction


def close(h):h.ea.save();h.ea.world.close();h.close()


def worker(path,stage,operation):
    # The worker independently enforces isolation before constructing its scene.
    with patch('socket.socket',side_effect=AssertionError('offline_socket_forbidden')):
        h=harness(path)
        h.ea.lose_reply=stage=='reply'
        h.ea.lose_bid_reply=stage=='reply' and operation=='bid'
        def crash(at):
            if at==stage:os._exit(73)
        if stage=='claim':h.ea.after_claim=lambda c:crash('claim')
        elif stage=='effect':h.ea.after_effect=lambda c:crash('effect')
        elif stage.startswith('phase_') and operation!='bid':
            original=h.controller.journal.checkpoint
            def transition(**kw):
                if kw.get('phase')=='ACQUIRING':
                    crash('phase_before');original(**kw);crash('phase_after')
                else:original(**kw)
            h.controller.journal.checkpoint=transition
        else:h.controller.work.checkpoint=crash
        if operation=='bid':
            if stage in ('before_intent','intent'):
                original=h.controller.journal.intend
                def intend(*args,**kwargs):
                    crash('before_intent');original(*args,**kwargs);crash('intent')
                h.controller.journal.intend=intend
            if stage=='claim':h.ea.on_request=lambda c:crash('claim') if c['operation']=='bid' else None
            if stage=='reply':
                original=h.adapter.deliver
                def deliver(*args,**kwargs):
                    v=original(*args,**kwargs);crash('reply');return v
                h.adapter.deliver=deliver
            if stage=='confirmation':
                original=h.controller.journal.member
                def member(*args,**kwargs):
                    original(*args,**kwargs);crash('confirmation')
                h.controller.journal.member=member
            if stage.startswith('phase_'):
                original=h.controller.journal.checkpoint
                def phase(**kw):
                    if kw.get('phase')=='MANAGING':
                        crash('phase_before');original(**kw);crash('phase_after')
                    else:original(**kw)
                h.controller.journal.checkpoint=phase
        if operation in ('clear_sold','relist_all'):
            if operation=='relist_all':h.clock.value+=3660
            h.controller.work.inventory=h.controller.work.pile();h.controller.work.maintenance()
        else:h.controller.step()
        close(h)
    raise AssertionError('requested fault boundary was never reached')


class ProcessAcceptance(unittest.TestCase):
    def test_4_bid_crashes_never_replay_and_confirmed_membership_survives(self):
        for stage in ('before_intent','intent','claim','effect','reply','confirmation','phase_before','phase_after'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as path:
                h=harness(path,1);close(h)
                p=subprocess.run([sys.executable,__file__,'worker',path,stage,'bid'],cwd=ROOT,capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,73,p.stdout+p.stderr)
                with patch('socket.socket',side_effect=AssertionError('offline_socket_forbidden')):
                    h=harness(path,1)
                    try:
                        if stage in ('confirmation','phase_before','phase_after'):
                            self.assertEqual(len(h.controller.journal.members()),1)
                            self.assertEqual(h.controller.status()['phase'],'MANAGING')
                        h.controller.step();h.controller.step()
                        count=h.ea.world.execute('SELECT count(*) FROM bid_effects').fetchone()[0]
                        self.assertEqual(count,0 if stage in ('intent','claim') else 1)
                        if stage in ('effect','reply'):
                            self.assertTrue(h.controller.status()['potentially_untracked_effects'])
                    finally:close(h)

    def test_4_real_process_crashes_all_work_boundaries_and_phase_transitions(self):
        stages=['before_intent','intent','claim','effect','reply','readback','confirmation']
        for operation in ('move','list','clear_sold','relist_all'):
            for stage in stages+(['phase_before','phase_after'] if operation=='list' else []):
                with self.subTest(operation=operation,stage=stage),tempfile.TemporaryDirectory() as path:
                    with patch('socket.socket',side_effect=AssertionError('offline_socket_forbidden')):
                        h=harness(path);won(h)
                        if operation=='list':h.controller.step()
                        if operation in ('clear_sold','relist_all'):
                            r=auction(123,15000,100);r.update(trade_state='closed' if operation=='clear_sold' else 'expired',current_bid=15000 if operation=='clear_sold' else 0,expires=-1)
                            h.ea.inventory=[r]
                        before_members=len(h.controller.journal.members());price=h.controller.journal.members()[0]['resale_price'];close(h)
                    p=subprocess.run([sys.executable,__file__,'worker',path,stage,operation],cwd=ROOT,capture_output=True,text=True,timeout=15)
                    self.assertEqual(p.returncode,73,p.stdout+p.stderr)
                    with patch('socket.socket',side_effect=AssertionError('offline_socket_forbidden')):
                        h=harness(path)
                        try:
                            # Confirmed memberships survive every interruption;
                            # settlement is allowed only after the real list proof.
                            states=list(h.store.db.execute('SELECT state,body FROM c4_members'))
                            self.assertGreaterEqual(len(states),before_members)
                            self.assertEqual(json.loads(states[0][1])['resale_price'],price)
                            for _ in range(3):h.controller.step()
                            h.controller.work.inventory=h.controller.work.pile();h.controller.work.maintenance()
                            count=dict(effects(h)).get(operation,0)
                            if stage in ('intent','claim') or operation=='relist_all' and stage=='before_intent':self.assertEqual(count,0)
                            else:self.assertEqual(count,1)
                            # All sends have unique durable IDs. Intent-only and
                            # claimed commands never turn back into dispatch work.
                            sent=list(h.ea.world.execute('SELECT command_id FROM effects'))
                            self.assertEqual(len(sent),len(set(sent)))
                            unknown=h.store.db.execute("SELECT count(*) FROM c4_commands WHERE state IN ('WAITING','CLAIMED')").fetchone()[0]
                            self.assertEqual(unknown,0)
                            self.assertNotIn('CANARY',json.dumps(h.controller.status()))
                        finally:close(h)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='worker':worker(*sys.argv[2:])
    else:unittest.main(verbosity=2)
