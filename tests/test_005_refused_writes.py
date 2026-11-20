"""A maintenance write EA refused with HTTP 401 (signed out) had no effect: it is
archived with EA's response and may be attempted again. Writes with an unknown
outcome (timeout, other or mixed statuses) are still never repeated.
Offline synthetic EA."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_work_fixture import harness, effects
from native_price_fixture import auction
from fc_access.controller_v1.work import Work, refused
from fc_access.production_v1.contracts import ROUTES


def response(status, statuses):
    return dict(result=dict(success=status == 200, status=status, error=None if status == 200 else 'service_failed',
                            network=[dict(method='DELETE', path='/ut/game/fc27/trade/sold', status=s) for s in statuses]))


class Classification(unittest.TestCase):
    def test_only_an_all_401_failure_is_refused(self):
        self.assertTrue(refused(response(401, [401])))
        for v in (response(401, []), response(401, [401, 200]), response(500, [500]), response(403, [403]),
                  response(200, [200]), None, {}, dict(result=dict(success=False, status=401))):
            self.assertFalse(refused(v), v)


class RefusedWrites(unittest.TestCase):
    def make(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        h = harness(tmp.name, 0); self.addCleanup(h.ea.world.close); self.addCleanup(h.close)
        return h

    def inventory(self, h, sold=1, expired=2):
        rows = [auction(123, 15000, n+100) for n in range(sold+expired)]
        for n, r in enumerate(rows):
            r.update(trade_state='closed' if n < sold else 'expired', current_bid=15000 if n < sold else 0,
                     expires=-1, bid_state='none', native_is_won=False)
        h.ea.inventory = rows; h.ea.save(); h.controller.work.inventory = h.controller.work.pile()

    def refuse(self, h, statuses=(401,), times=1):
        """EA answers the next ``times`` writes with these statuses and no effect."""
        original = h.ea.shared; left = [times]
        def shared(c, at):
            if c['operation'] in {'clear_sold', 'relist_all', 'move', 'list'} and left[0] > 0:
                left[0] -= 1
                # EA's live 401 answer to a clear (no effect, empty body), field for field.
                method, path = ROUTES[c['operation']]
                return dict(command_id=c['id'], context=c['context'], fences=c['fences'], operation=c['operation'],
                    schema=2, coverage=dict(complete=False, has_more=None),
                    freshness=dict(network_at=None, observed_at=at, read_id=c['id'], request_count=1,
                                   source=h.adapter.native.source),
                    result=dict(auctions=None, cache_invalidated=False, caps=None, credits=None, error='service_failed',
                                items=None, status=statuses[0], success=False,
                                network=[dict(body_empty=True, host='utas.test.ea.com', method=method, path=path,
                                              query={}, session_header_present=True, status=s) for s in statuses]),
                    timing=dict(ea_rtt_ms=93, native_helper_ms=0, native_service_ms=1000))
            return original(c, at)
        h.ea.shared = shared

    def work(self, h, table='c4_work'):
        return [(json.loads(b)['operation'], s) for b, s in h.store.db.execute(f'SELECT body,state FROM {table} ORDER BY rowid')]

    def test_a_refused_clear_is_archived_and_retried(self):
        h = self.make(); self.inventory(h)
        self.refuse(h)
        h.controller.work.maintenance()
        self.assertEqual(self.work(h), [], 'released from active work')
        self.assertEqual([op for op, _ in self.work(h, 'c4_work_rejected')], ['clear_sold'])
        self.assertEqual(h.store.db.execute('SELECT count(*) FROM c4_tombstones').fetchone()[0], 0)
        self.assertEqual(h.store.db.execute('SELECT count(*) FROM c4_tombstones_rejected').fetchone()[0], 1)
        stored = json.loads(h.store.db.execute('SELECT response FROM c4_work_rejected').fetchone()[0])
        self.assertTrue(refused(stored), 'EA response kept as evidence')
        self.assertEqual(h.metrics('WRITE_REFUSED')[-1]['operation'], 'clear_sold')
        # The next pass clears the sold card and the relist follows on its slot.
        h.controller.work.maintenance()
        self.assertEqual(self.work(h), [('clear_sold', 'CONFIRMED')])
        self.assertEqual([r['trade_state'] for r in h.ea.inventory], ['expired', 'expired'])

    def test_an_unknown_outcome_is_never_repeated(self):
        for statuses in ((401, 200), (500,), (403,)):
            with self.subTest(statuses=statuses):
                h = self.make(); self.inventory(h)
                self.refuse(h, statuses)
                h.controller.work.maintenance()
                self.assertEqual(self.work(h), [('clear_sold', 'UNKNOWN')])
                before = [op for op, _ in effects(h)]
                h.controller.work.maintenance()
                self.assertEqual([op for op, _ in effects(h)], before, 'no second clear_sold')
                self.assertEqual(self.work(h, 'c4_work_rejected'), [])

    def test_a_lost_reply_is_never_treated_as_refused(self):
        h = self.make(); self.inventory(h)
        h.ea.lose_reply = True  # the clear happened, its answer was lost
        h.controller.work.maintenance()
        h.ea.lose_reply = False
        self.assertEqual(self.work(h), [('clear_sold', 'CONFIRMED')], 'proven from the next transfer list read')
        self.assertEqual(self.work(h, 'c4_work_rejected'), [])
        self.assertEqual([op for op, _ in effects(h)].count('clear_sold'), 1)

    def test_an_already_stuck_refused_write_is_released_on_the_next_pass(self):
        h = self.make(); self.inventory(h)
        self.refuse(h)
        with patch.object(Work, 'release_refused', return_value=False):  # the previous version
            h.controller.work.maintenance()
        self.assertEqual(self.work(h), [('clear_sold', 'UNKNOWN')])
        h.controller.work.maintenance()
        self.assertEqual(self.work(h), [('clear_sold', 'CONFIRMED')])
        self.assertEqual([op for op, _ in self.work(h, 'c4_work_rejected')], ['clear_sold'])


if __name__ == '__main__': unittest.main(verbosity=2)
