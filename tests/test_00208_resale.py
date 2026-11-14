"""Behavioral acceptance for exact-card ownership, durable movement and listing.

All EA services are synthetic. Each case uses a fresh SQLite journal/transport.
The companion VM suite executes the shipped native JavaScript, without Edge.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from actors_fixture import ActorPage, Clock, CONTEXT
from native_price_fixture import auction
from fc_access.actors_v1.actors import Acquirer, Bidder
from fc_access.actors_v1.occupancy import read as occupancy
from fc_access.bidding_v1 import capacity
from fc_access.bidding_v1.journal import Journal
from fc_access.production_v1.foundation import Foundation, JournalAuthority, status_from
from fc_access.production_v1.resale import Resale, pending, verify_win
from fc_access.production_v1.contracts import command, stamp

ARTIFACTS = {}


class ResalePage(ActorPage):
    def __init__(self, directory, clock):
        super().__init__(directory, clock)
        self.mutations = []
        self.effect = True
        self.timeout = False
        self.after_write = lambda c: None
        self.cap_min, self.cap_max = 150, 50000
        self.listed_at = None

    def project_response(self, c, v):
        v = super().project_response(c, v)
        op, p = c['operation'], c['params']
        if op == 'caps':
            v['result']['caps'].update(minimum=self.cap_min, maximum=self.cap_max)
        if op == 'transfer_list' and self.listed_at:
            for r in v['result']['auctions']:
                if r['trade_state'] == 'active' and r['trade_id'] == 'trade:'+'f'*24:
                    r['expires'] = max(0, r['expires']-int((self.clock.now()-stamp(self.listed_at)).total_seconds()))
        if op in {'move', 'list'}:
            # A separate connection must see committed intent/claim BEFORE the
            # synthetic native side effect, just as the real HTTP service does.
            authority = JournalAuthority(self.directory/'journal.sqlite3')
            assert authority(c), 'uncommitted or unfenced mutation'
            self.mutations.append(deepcopy(c))
            if self.effect:
                if op == 'move':
                    item = next(i for i in self.owned+getattr(self,'owned_by_id',[]) if i['item_id'] == p['item_id'])
                    row = deepcopy(self.candidate)
                    row.update(item=deepcopy(item), trade_id='trade:'+'0'*24, current_bid=0,
                        trade_state='inactive', bid_state='none', expires=-1, native_is_won=False)
                    self.transfer_items.append(row)
                    self.owned = [i for i in self.owned if i['item_id'] != p['item_id']]
                    if hasattr(self,'owned_by_id'):self.owned_by_id=[i for i in self.owned_by_id if i['item_id']!=p['item_id']]
                else:
                    self.listed_at = self.clock.now().isoformat()
                    row = next(r for r in self.transfer_items if r['item']['item_id'] == p['item_id'])
                    row.update(trade_id='trade:'+'f'*24, starting_bid=p['starting_bid'],
                        buy_now_price=p['buy_now_price'], expires=p['duration'], trade_state='active', bid_state='none')
            self.after_write(c)
            if self.timeout:
                self.store.uncertain(c['id'])
                raise TimeoutError('synthetic lost mutation response')
        return v


class Acceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.clock = Clock()
        self.page = ResalePage(self.path, self.clock)
        self.f = self.open()
        self.addCleanup(self.page.close)
        self.addCleanup(lambda: self.f.close())
        self.a, self.b = Acquirer(self.f), Bidder(self.f)

    def open(self):
        return Foundation(self.page, context=CONTEXT, journal_path=self.path/'journal.sqlite3',
            fixture=True, now=self.clock.now, clock=self.clock.monotonic, sleep=self.clock.sleep)

    def candidate_win(self, paid=800):
        self.a.cycle()
        self.page.candidate.update(trade_state='closed', expires=0, native_is_won=True, bid_state='highest')
        self.page.watched = [deepcopy(self.page.candidate)]
        self.page.owned = [deepcopy(self.page.candidate['item'])]
        self.page.owned[0]['last_sale_price'] = paid

    def state(self):
        return self.f.journal.db.execute('SELECT state FROM resales_v1').fetchone()[0]

    def counts(self):
        return capacity.status(self.f.journal, self.f.registry.scope, now=self.clock.now())

    def capture(self, name, snapshots):
        ARTIFACTS[name] = dict(source='synthetic', real_account_writes=self.page.real_account_writes,
            state=self.state(), capacity=snapshots, mutations=deepcopy(self.page.mutations),
            events=[e for e in self.f.registry.events() if e['kind'] in {'RESALE','ENROLLMENT'} or
                e.get('reason') == 'OWNED_WIN_VERIFIED'],
            reads=[dict(command=self.f.adapter.commands[cid], response=v) for cid,v in self.f.adapter.responses.items()
                if v['operation'] in {'unassigned','watched','caps','transfer_list','price_helpers'}],
            pending=pending(self.f.journal,self.f.registry.scope))

    def restart(self):
        self.f.close()
        self.f = self.open()
        self.a, self.b = Acquirer(self.f), Bidder(self.f)

    def test_c0_physical_definition_trade_and_paid_mismatches_never_move_or_list(self):
        self.candidate_win()
        original = deepcopy(self.page.owned)
        cases = [dict(item_id='item:'+'e'*24), dict(definition_id=124), dict(untradeable=True),
                 dict(last_sale_price=None), dict(last_sale_price=0), dict(last_sale_price=750)]
        for change in cases:
            with self.subTest(change=change):
                self.page.owned = deepcopy(original)
                self.page.owned[0].update(change)
                self.b.cycle()
                self.assertEqual(self.page.mutations, [])
                self.assertEqual(self.counts()['unresolved'], 1)
                self.assertFalse([e for e in self.f.journal.trace() if e['reason'] == 'WON_VERIFIED'])
        self.page.owned = original
        self.page.watched[0]['item']['item_id'] = 'item:'+'e'*24
        self.b.cycle()
        self.assertEqual(self.page.mutations, [])

    def test_c0_lost_never_lists_even_with_owned_same_definition(self):
        self.candidate_win()
        self.page.watched[0].update(bid_state='outbid', native_is_won=False)
        self.b.cycle(); self.b.cycle()
        self.assertEqual(self.page.mutations, [])
        self.assertEqual(self.counts()['unresolved'], 0)
        self.assertEqual(self.counts()['pending_resale'], 0)
        self.assertTrue([e for e in self.f.journal.trace() if e['reason'] == 'LOST_VERIFIED'])

    def test_c0_stale_foreign_or_reused_proof_rejected(self):
        self.candidate_win()
        watched, owned = self.f.read('watched'), self.f.read('unassigned')
        s = status_from(watched['result']['auctions'][0], watched)
        for value in ('stale', 'foreign', 'tampered'):
            with self.subTest(value=value):
                copy = deepcopy(owned)
                if value == 'foreign': copy['fences']['epoch'] += 1
                elif value == 'tampered': copy['result']['items'][0]['last_sale_price'] = 900
                else:
                    self.clock.sleep(31)
                with self.assertRaises(ValueError): verify_win(self.f, s, watched, copy)
        self.assertEqual(self.page.mutations, [])

    def test_c0_c1_c2_c4_exact_fixed_prices_hour_new_trade_and_atomic_handoff(self):
        self.candidate_win()
        before = self.counts()
        self.assertEqual((before['total'], before['unresolved']), (1, 1))
        observed = []
        def inspect(c):
            j = Journal(self.f.journal_path, readonly=True)
            try:
                value = capacity.status(j, self.f.registry.scope, now=self.clock.now())
                observed.append(value)
                self.assertEqual((value['total'], value['pending_resale']), (1, 1))
            finally: j.close()
        self.page.after_write = inspect
        self.b.cycle()
        self.assertEqual(self.state(), 'MOVED')
        moved = self.counts()
        self.assertEqual((moved['total'], moved['occupied'], moved['pending_resale']), (1, 1, 0))
        self.b.cycle()
        self.assertEqual(self.state(), 'LISTED')
        self.assertEqual([c['operation'] for c in self.page.mutations], ['move', 'list'])
        listing = self.page.mutations[-1]
        self.assertEqual({k: listing['params'][k] for k in ('starting_bid','buy_now_price','duration','paid')},
            dict(starting_bid=11750, buy_now_price=12000, duration=3600, paid=800))
        self.assertEqual(listing['params']['item_id'], self.page.candidate['item']['item_id'])
        self.assertEqual(self.counts()['total'], 1)
        events = [e for e in self.f.registry.events() if e['kind'] == 'RESALE']
        verified = [e for e in events if e['reason'] == 'VERIFIED']
        self.assertEqual([e['operation'] for e in verified], ['move', 'list'])
        self.assertEqual(verified[-1]['new_trade_id'], 'trade:'+'f'*24)
        for c in self.page.mutations:
            intent = next(e for e in events if e['reason'] == 'INTENT_DURABLE' and e['command_id'] == c['id'])
            claim = next(e for e in events if e['reason'] == 'DISPATCH_CLAIM' and e['command_id'] == c['id'])
            readback = next(e for e in verified if e['command_id'] == c['id'])
            self.assertLess(intent['seq'], claim['seq']); self.assertLess(claim['seq'], readback['seq'])
            self.assertTrue(set(readback['read_ids']).isdisjoint({c['id'], c['params']['owned_read_id']}))
            self.assertTrue(JournalAuthority(self.f.journal_path).reconciled(c))
        self.b.cycle(); self.assertEqual(len(self.page.mutations), 2)
        self.assertEqual(self.page.real_account_writes, 0)
        self.capture('exact_listing', [before, *observed, moved, self.counts()])

    def test_c1_c2_illegal_ticks_caps_and_minimum_preserve_policy_no_mutation(self):
        self.candidate_win()
        # Stop before resale, leaving actual Bidder ownership/paid proof durable.
        with patch.object(Resale, 'cycle'):
            self.b.cycle()
        policy = deepcopy(self.a.policy(self.page.candidate['trade_id']))
        for minimum, maximum, illegal in [(150,11000,False), (12000,50000,False), (150,50000,True)]:
            with self.subTest(minimum=minimum, maximum=maximum, illegal=illegal):
                service = Resale(self.f)
                service.seed()
                self.f.journal.db.execute('UPDATE resales_v1 SET state=?', ('READY',))
                self.page.cap_min, self.page.cap_max = minimum, maximum
                original = self.page.helper.price_helpers
                def helpers(cid, probes):
                    result = original(cid, probes)
                    for row in result['result']['probes']:
                        if illegal and row['value'] == 12000 and row['direction'] == 'below': row['price'] = 11751
                    return result
                with patch.object(self.page.helper, 'price_helpers', helpers): service.cycle()
                self.assertEqual(self.state(), 'UNLISTABLE')
                self.assertEqual(self.page.mutations, [])
                self.assertEqual(self.f.journal.db.execute('SELECT resale_price FROM resales_v1').fetchone(), (12000,))
                self.assertEqual(self.a.policy(self.page.candidate['trade_id']), policy)
                self.assertEqual(self.counts()['pending_resale'], 1)

    def test_c1_current_caps_rechecked_between_move_and_list(self):
        self.candidate_win(); self.b.cycle()
        self.page.cap_max = 11000
        self.b.cycle()
        self.assertEqual(self.state(), 'UNLISTABLE')
        self.assertEqual([c['operation'] for c in self.page.mutations], ['move'])
        self.assertEqual(self.counts()['total'], 1)

    def test_c2_c3_ack_is_not_proof_and_ambiguous_moves_never_retry(self):
        self.candidate_win()
        self.page.effect = False
        self.b.cycle()
        self.assertEqual(len(self.page.mutations), 1)
        self.assertEqual(pending(self.f.journal, self.f.registry.scope)[0]['state'], 'ACKNOWLEDGED')
        self.assertEqual(self.counts()['pending_resale'], 1)
        self.restart()
        for _ in range(3): self.b.cycle()
        self.assertEqual(len(self.page.mutations), 1)
        self.assertEqual(self.counts()['total'], 1)

    def test_c2_c3_unknown_listing_retains_reservation_even_after_pile_disappears(self):
        self.candidate_win(); self.b.cycle()
        self.page.effect, self.page.timeout = False, True
        self.b.cycle()
        self.assertEqual(self.counts()['pending_resale'], 1)
        self.page.transfer_items = []
        occupancy(self.f)
        self.assertEqual((self.counts()['total'], self.counts()['pending_resale']), (1, 1))
        self.restart()
        for _ in range(3): self.b.cycle()
        self.assertEqual([c['operation'] for c in self.page.mutations], ['move','list'])
        self.assertEqual(self.counts()['total'], 1)
        self.a.cycle()
        self.assertEqual(self.page.bid_calls, 1)
        self.capture('uncertain_listing', [self.counts()])

    def test_c3_successful_side_effect_with_lost_response_reconciles_without_retry(self):
        self.candidate_win(); self.page.timeout = True
        self.b.cycle(); self.assertEqual(self.state(), 'MOVED')
        self.b.cycle(); self.assertEqual(self.state(), 'LISTED')
        self.b.cycle()
        self.assertEqual([c['operation'] for c in self.page.mutations], ['move','list'])
        self.assertEqual(pending(self.f.journal, self.f.registry.scope), [])

    def test_c2_c4_intent_failure_and_readback_failure_roll_back_accounting(self):
        self.candidate_win()
        original = Resale.event
        def fail_intent(service, trade, reason, **data):
            original(service, trade, reason, **data)
            if reason == 'INTENT_DURABLE': raise OSError('synthetic checkpoint failure')
        with patch.object(Resale, 'event', fail_intent):
            with self.assertRaises(OSError): self.b.cycle()
        self.assertEqual(self.page.mutations, [])
        self.assertEqual(pending(self.f.journal, self.f.registry.scope), [])
        self.assertEqual((self.counts()['pending_resale'], self.counts()['total']), (1,1))
        def fail_readback(service, trade, reason, **data):
            original(service, trade, reason, **data)
            if reason == 'VERIFIED': raise OSError('synthetic readback commit failure')
        with patch.object(Resale, 'event', fail_readback):
            with self.assertRaises(OSError): self.b.cycle()
        self.assertEqual(len(self.page.mutations), 1)
        self.assertEqual(self.state(), 'READY')
        self.assertEqual((self.counts()['pending_resale'], self.counts()['total']), (1,1))
        self.assertNotEqual(pending(self.f.journal, self.f.registry.scope), [])
        self.b.cycle()
        self.assertEqual(self.state(), 'MOVED')
        self.assertEqual((self.counts()['pending_resale'], self.counts()['total']), (0,1))
        self.assertEqual(len(self.page.mutations), 1)

    def test_c2_c3_epoch_takeover_or_aged_dispatch_never_sends_and_never_retries(self):
        self.candidate_win()
        def age(service, stage):
            if stage == 'claimed': self.clock.sleep(31)
        with patch.object(Resale, 'checkpoint', age):
            with self.assertRaises(ValueError): self.b.cycle()
        self.assertEqual(self.page.mutations, [])
        self.assertEqual(self.counts()['pending_resale'], 1)
        self.restart()
        self.b.cycle()
        self.assertEqual(self.page.mutations, [])
        self.assertEqual(self.counts()['total'], 1)
        self.assertEqual(len(pending(self.f.journal, self.f.registry.scope)), 1)

    def test_c2_c3_incomplete_inventory_and_missing_caps_remain_reserved(self):
        self.candidate_win()
        with patch.object(Resale, 'cycle'): self.b.cycle()
        self.page.transfer_coverage = dict(complete=False, has_more=True, transfer_list=dict(
            reason='TRANSFER_LIST_TRUNCATED',wire_count=None,callback_count=0,repository_count=None,repository_end_of_list=False))
        self.b.cycle()
        self.assertEqual(self.page.mutations, [])
        self.assertEqual(self.counts()['pending_resale'], 1)
        self.page.transfer_coverage = None
        with patch.object(self.f.prices, 'load', side_effect=TimeoutError('unavailable')): self.b.cycle()
        self.assertEqual(self.page.mutations, [])
        self.assertEqual(self.state(), 'READY')
        self.assertEqual(self.counts()['pending_resale'], 1)

    def test_c4_move_waits_at_full_physical_pile_then_lists_at_fifty(self):
        self.candidate_win()
        self.page.transfer_items = [auction(123,15000,n+100) for n in range(50)]
        self.b.cycle()
        self.assertEqual(self.page.mutations, [])
        self.assertEqual((self.counts()['pending_resale'],self.counts()['physical_occupied']), (1,50))
        self.page.transfer_items.pop()
        seen=[]
        def inspect(c):
            seen.append(self.counts())
            self.assertEqual((seen[-1]['total'],seen[-1]['pending_resale']), (50,1))
        self.page.after_write=inspect
        self.b.cycle()
        self.assertEqual(self.state(),'MOVED')
        self.assertEqual((self.counts()['total'],self.counts()['occupied']), (50,50))
        self.b.cycle()
        self.assertEqual(self.state(),'LISTED')
        self.assertEqual(self.counts()['total'],50)
        self.assertEqual([c['operation'] for c in self.page.mutations],['move','list'])

    def test_c2_epoch_takeover_between_claim_and_send_has_no_dispatch_authority(self):
        self.candidate_win()
        def takeover(service, stage):
            if stage=='claimed':
                self.f.journal.session(self.f.registry.scope,'9'*32)
        with patch.object(Resale,'checkpoint',takeover):
            with self.assertRaisesRegex(ValueError,'stale_owner_or_epoch'): self.b.cycle()
        self.assertEqual(self.page.mutations,[])
        self.assertEqual((self.counts()['pending_resale'],self.counts()['total']),(1,1))
        self.restart()
        self.b.cycle()
        self.assertEqual(self.page.mutations,[])
        self.assertEqual(len(pending(self.f.journal,self.f.registry.scope)),1)

    def test_c2_c4_wrong_readback_trade_item_prices_duration_never_confirms(self):
        self.candidate_win(); self.b.cycle()
        def corrupt(c):
            row = self.page.transfer_items[0]
            row.update(starting_bid=11000, expires=7200)
        self.page.after_write = corrupt
        self.b.cycle()
        self.assertEqual(self.state(), 'MOVED')
        self.assertEqual(self.counts()['pending_resale'], 1)
        row = self.page.transfer_items[0]
        base = deepcopy(row)
        for change in [dict(trade_id='trade:'+'0'*24), dict(trade_id=self.page.candidate['trade_id']),
                       dict(item={**row['item'], 'item_id':'item:'+'e'*24}), dict(starting_bid=11500),
                       dict(buy_now_price=11750), dict(expires=7200), dict(trade_state='inactive')]:
            with self.subTest(change=change):
                self.page.transfer_items = [deepcopy(base)]
                self.page.transfer_items[0].update(starting_bid=11750, buy_now_price=12000, expires=3600)
                self.page.transfer_items[0].update(change)
                self.b.cycle()
                self.assertEqual(self.state(), 'MOVED')
                self.assertEqual(len(self.page.mutations), 2)
        self.page.transfer_items = [base]
        self.page.transfer_items[0].update(starting_bid=11750, buy_now_price=12000, expires=3600)
        self.b.cycle(); self.assertEqual(self.state(), 'LISTED')

    def test_c2_epoch_context_and_read_seam_cannot_authorize_mutations(self):
        self.candidate_win(); self.b.cycle()
        c = deepcopy(self.page.mutations[0])
        self.assertFalse(JournalAuthority(self.f.journal_path)(c), 'reconciled intent is consumed')
        with self.assertRaisesRegex(ValueError, 'read_cannot_write'): self.f.read('list', c['params'])
        for change in ('owner', 'context', 'prices', 'duration'):
            copy = deepcopy(c)
            if change == 'owner': copy['fences']['owner'] = '9'*32
            if change == 'context': copy['context']['persona'] = '9'*32
            if change == 'prices': copy['params']['buy_now_price'] = 12500
            if change == 'duration':
                copy['params']['duration'] = 7200
                with self.assertRaises(ValueError): command(copy)
                continue
            self.assertFalse(JournalAuthority(self.f.journal_path)(copy))
        old = Resale(self.f)
        self.restart()
        with self.assertRaises(Exception): old.cycle()
        self.assertEqual(len(self.page.mutations), 1)

    def test_c4_crashes_at_each_durable_boundary_both_operations(self):
        # Genuine abrupt process exits also exercise SQLite rollback/WAL recovery.
        for operation in ('move','list'):
            for stage in ('intent','claimed','sent','ack','readback'):
                with self.subTest(operation=operation, stage=stage):
                    directory = self.path/(operation+'-'+stage); directory.mkdir()
                    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--crash',
                        str(directory), operation, stage], cwd=ROOT, timeout=30, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 23, result.stdout+result.stderr)
                    clock = Clock(); page = ResalePage(directory, clock)
                    evidence_path = directory/'native-effect.json'
                    evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else None
                    if evidence:
                        page.transfer_items = evidence['transfer_items']
                        page.listed_at = evidence.get('listed_at')
                    # No owned inventory is sufficient to reconcile absence;
                    # it never authorizes retry of the uncertain operation.
                    f = Foundation(page, context=CONTEXT, journal_path=directory/'journal.sqlite3', fixture=True,
                        now=clock.now, clock=clock.monotonic, sleep=clock.sleep)
                    try:
                        # Child used simulated time; move parent forward for fresh readbacks.
                        clock.sleep(5)
                        service = Resale(f)
                        for write in pending(f.journal, f.registry.scope): service.reconcile(write['command_id'])
                        self.assertEqual(page.mutations, [])
                        current = f.journal.db.execute('SELECT state FROM resale_writes_v1 WHERE '
                            "json_extract(body,'$.operation')=?", (operation,)).fetchone()[0]
                        self.assertEqual(current, 'RECONCILED' if stage in {'sent','ack','readback'} else
                            'INTENT' if stage=='intent' else 'UNKNOWN')
                        self.assertEqual(capacity.status(f.journal, f.registry.scope, now=clock.now())['total'], 1)
                    finally: f.close(); page.close()

    def test_c1_c2_c4_real_native_page_parameters_and_negative_fences(self):
        result = subprocess.run(['node', 'tests/resale_native_checks.cjs'], cwd=ROOT, timeout=30,
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('PASS', result.stdout)


def crash_worker(directory, operation, stage):
    import os
    directory = Path(directory)
    clock = Clock(); p = ResalePage(directory, clock)
    f = Foundation(p, context=CONTEXT, journal_path=directory/'journal.sqlite3', fixture=True,
        now=clock.now, clock=clock.monotonic, sleep=clock.sleep)
    a, b = Acquirer(f), Bidder(f)
    a.cycle()
    p.candidate.update(trade_state='closed', expires=0, native_is_won=True, bid_state='highest')
    p.watched = [deepcopy(p.candidate)]
    p.owned = [deepcopy(p.candidate['item'])]; p.owned[0]['last_sale_price'] = 800
    if operation == 'list': b.cycle()
    def save(c):
        (directory/'native-effect.json').write_text(json.dumps(dict(transfer_items=p.transfer_items,listed_at=p.listed_at)))
    p.after_write = save
    original = Resale.reconcile
    def checkpoint(self, value):
        if value == stage: os._exit(23)
    def reconcile(self, cid):
        result = original(self, cid)
        if stage == 'readback': os._exit(23)
        return result
    with patch.object(Resale, 'checkpoint', checkpoint), patch.object(Resale, 'reconcile', reconcile):
        b.cycle()
    raise AssertionError('crash seam was not reached')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--crash': crash_worker(*sys.argv[2:])
    else:
        record = '--record' in sys.argv
        if record: sys.argv.remove('--record')
        result = unittest.main(verbosity=2, exit=False)
        if result.result.wasSuccessful() and record:
            target = ROOT/'docs/research/002/002-08/scenarios.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(dict(schema=1,source='synthetic',scenarios=ARTIFACTS),indent=2)+'\n',encoding='utf8')
        sys.exit(0 if result.result.wasSuccessful() else 1)
