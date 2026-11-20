"""Strategy 1 acquisition: discovery bands, auction-length limit, search budget,
EA search throttle (429) and 461 handling (bounded retries, burst pause).
Offline synthetic EA; real store admission, tombstones and parsers."""
from dataclasses import replace
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]; sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from controller_policy_fixture import Harness
from native_price_fixture import auction
from fc_access.controller_v1.__main__ import parse_bands
from fc_access.controller_v1.config import ControllerConfig
from fc_access.controller_v1.controller import Controller
from fc_access.controller_v1.semantic import SemanticHealth, native_summary


def configured(h, **values):
    h.config = replace(h.config, **values)
    h.controller = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids, clock=h.clock.clock, sleep=h.clock.sleep)
    h.controller.resume()
    return h


def discoveries(h):
    return [c['command']['params'] for c in h.calls('search') if c['command']['params']['purpose'] == 'discovery']


def rebids(h):
    return [dict(state=r[0], result=json.loads(r[1]) if r[1] else None) for r in
            h.store.db.execute("SELECT state,result FROM c4_attempts WHERE kind='rebid' ORDER BY rowid")]


def initial(h):
    return [a for a in h.attempts() if a['body']['params'].get('batch_id') and a['body']['candidate'].get('target')]


class Base(unittest.TestCase):
    def make(self, count=3, **values):
        h = Harness(self.enterContext(tempfile.TemporaryDirectory()), count); self.addCleanup(h.close)
        return configured(h, **values) if values else h

    def reset_phase(self, h):
        h.controller.journal.checkpoint(phase='ACQUIRING')


class BandsAndLength(Base):
    def test_bands_rotate_one_per_batch(self):
        h = self.make(bands=((1000, 11000), (3000, 20000)))
        for _ in range(3):
            h.controller._acquire(); self.reset_phase(h)
        got = [(p['max_bid'], p['min_buy']) for p in discoveries(h)]
        self.assertEqual(got, [(1000, 11000), (3000, 20000), (1000, 11000)])
        batches = [b['band'] for b in h.controller.store.db.execute("SELECT json_extract(body,'$.band') AS band FROM c4_policy_batches").fetchall() for b in [dict(band=b[0])]]
        self.assertTrue(all(b for b in batches))

    def test_default_keeps_the_legacy_band(self):
        h = self.make()
        h.controller._acquire()
        self.assertEqual([(p['max_bid'], p['min_buy']) for p in discoveries(h)], [(1000, 11000)])

    def test_long_auctions_are_skipped(self):
        h = self.make(max_auction_seconds=200)  # fixture auctions have 300 s left
        h.controller._acquire()
        self.assertEqual(h.calls('bid'), [])
        self.assertEqual(h.metrics('ACQUISITION')[-1]['long_skips'], 3)
        h2 = self.make(max_auction_seconds=400)
        h2.controller._acquire()
        self.assertEqual(len(h2.calls('bid')), 3)

    def test_config_and_cli_parsing(self):
        self.assertEqual(parse_bands('1000:11000, 3000:20000'), ((1000, 11000), (3000, 20000)))
        for bad in (dict(bands=()), dict(bands=((1000,),)), dict(bands=((-1, 5),)), dict(max_auction_seconds=-1),
                    dict(search_budget=1.5), dict(denial_retries=6), dict(denial_pause=-1), dict(throttle_pause=10000)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)


class Denials(Base):
    def deny_all(self, h):
        for r in h.ea.rows: h.ea.bid_modes[r['trade_id']] = 'denied'

    def test_denied_auction_is_retried_and_can_still_be_won(self):
        h = self.make(denial_pause=0)
        self.deny_all(h)
        h.controller._acquire(); self.reset_phase(h)
        self.assertEqual([a['state'] for a in h.attempts()], ['DENIED']*3)
        self.assertEqual(h.controller.journal.members(), [])
        h.ea.bid_modes.clear()
        h.controller._acquire()
        states = [a['state'] for a in h.attempts()]
        self.assertEqual(states.count('ACKNOWLEDGED'), 3)
        self.assertEqual(len(h.controller.journal.members()), 3)
        retried = h.store.db.execute("SELECT body FROM c4_decisions").fetchall()
        self.assertEqual(sum('retry_of' in r[0] for r in retried), 3)
        self.assertEqual(h.metrics('ACQUISITION')[-1]['retries'], 3)

    def test_retries_are_bounded(self):
        h = self.make(denial_pause=0, denial_retries=2)
        self.deny_all(h)
        for _ in range(5):
            h.controller._acquire(); self.reset_phase(h)
        per_trade = {}
        for a in h.attempts():
            t = a['body']['params']['target']['trade_id']; per_trade[t] = per_trade.get(t, 0)+1
        self.assertEqual(set(per_trade.values()), {3})  # first try + 2 retries

    def test_no_retry_after_any_non_denied_outcome(self):
        h = self.make(denial_pause=0)
        h.ea.bid_modes[h.ea.rows[0]['trade_id']] = 'reject'
        h.controller._acquire(); self.reset_phase(h)
        h.ea.bid_modes.clear()
        before = len(h.attempts())
        h.controller._acquire()
        tried = [a['body']['params']['target']['trade_id'] for a in h.attempts()[before:]]
        self.assertNotIn(h.ea.rows[0]['trade_id'], tried)

    def test_store_refuses_a_retry_of_an_attempt_that_was_not_denied(self):
        h = self.make(denial_pause=0)
        h.controller._acquire()
        acked = h.attempts()[0]
        target = acked['body']['params']['target']
        self.assertFalse(h.store.denied_attempt(acked['id'], target))
        with self.assertRaises(ValueError):
            h.store.decide('f'*32, batch_id=acked['body']['params']['batch_id'], status_read_id=acked['body']['params']['status_read_id'],
                           identity=target, amount=acked['body']['params']['amount'], minimum=acked['body']['params']['amount'],
                           cap=acked['body']['params']['cap'], deadline=acked['body']['params']['deadline'], retry_of=acked['id'])

    def test_burst_skips_the_rest_and_pauses_acquisition(self):
        h = self.make(denial_pause=120)
        self.deny_all(h)
        h.controller._acquire(); self.reset_phase(h)
        self.assertEqual(len(h.calls('bid')), 2)  # third candidate kept for later
        self.assertEqual(h.metrics('DENIAL_BURST')[-1]['skipped'], 1)
        searches = len(h.calls('search'))
        h.controller.step()                         # held: no search, no bid
        self.assertEqual(len(h.calls('search')), searches)
        self.assertEqual(h.metrics('ACQUISITION_HOLD')[-1]['reason'], 'DENIAL_BURST')
        h.clock.value += 130; h.ea.bid_modes.clear(); self.reset_phase(h)
        h.controller.step()
        self.assertEqual(len(h.controller.journal.members()), 3)  # two retries + the untried one


class Throttle(Base):
    def test_429_pauses_acquisition_without_stopping(self):
        h = self.make(throttle_pause=900)
        s = SemanticHealth(clock=lambda: h.clock.value)
        h.executor.result = lambda c, v: s.observe(dict(kind='native_result', **native_summary(c, v)))
        h.ea.search_throttle = True
        h.controller.step()
        self.assertEqual(h.metrics('SEARCH_THROTTLED')[-1]['pause'], 900)
        state = h.store.db.execute("SELECT state FROM c4_policy_batches").fetchone()[0]
        self.assertEqual(state, 'THROTTLED')
        searches = len(h.calls('search'))
        for _ in range(3): h.controller.step()
        self.assertEqual(len(h.calls('search')), searches)
        self.assertEqual(s.search_throttles, 1); self.assertEqual(s.read_failures, 0); self.assertIsNone(s.check())
        h.clock.value += 901; h.ea.search_throttle = False; self.reset_phase(h)
        h.controller.step()
        self.assertEqual(len(h.controller.journal.members()), 3)

    def test_search_budget_holds_acquisition(self):
        # No live members (all denied): the hold waits in place and says why.
        h = self.make(search_budget=2, denial_pause=0)
        for r in h.ea.rows: h.ea.bid_modes[r['trade_id']] = 'denied'
        h.controller._acquire(); self.reset_phase(h)
        self.assertGreaterEqual(h.controller.searches_last_hour(), 2)
        searches = len(h.calls('search'))
        h.controller.step()
        self.assertEqual(len(h.calls('search')), searches)
        self.assertEqual(h.metrics('ACQUISITION_HOLD')[-1]['reason'], 'SEARCH_BUDGET')
        h.clock.value += 3700; h.ea.bid_modes.clear(); self.reset_phase(h)
        h.controller.step()                         # an hour later the budget is free
        self.assertGreater(len(h.calls('search')), searches)

    def test_hold_with_live_members_keeps_managing(self):
        h = self.make(search_budget=2)
        h.controller._acquire(); self.reset_phase(h)
        searches = len(h.calls('search'))
        h.controller.step()
        self.assertEqual(len(h.calls('search')), searches)
        self.assertEqual(h.controller.journal.state()['phase'], 'MANAGING')


class Credit(Base):
    """Live 03:14 incident: rebids above spendable coins got wire 470 / service 403
    NOT_ENOUGH_CREDIT, were filed UNKNOWN and stopped the runtime as write failures."""
    def outbid(self, h):
        h.controller.step()
        for r in h.ea.rows: r.update(bid_state='outbid', current_bid=200, expires=120)

    def test_470_is_a_no_effect_rejection_and_arms_the_credit_gate(self):
        h = self.make()
        self.outbid(h)
        h.ea.bid_modes[h.ea.rows[0]['trade_id']] = 'no_credit'
        h.ea.credits = 100                          # below every rebid amount
        balances = len(h.calls('balance'))
        h.controller.step()
        got = rebids(h)
        self.assertEqual(got[0]['state'], 'REJECTED')
        self.assertEqual(got[0]['result']['reason'], 'not_enough_credit')
        self.assertTrue(h.controller.credit_gate)
        # Later rebids in the same cycle are held locally after one balance read.
        self.assertEqual(len(got), 1)
        self.assertEqual(len(h.calls('balance')), balances+1)
        holds = [m for m in h.metrics('HOLD') if m.get('reason') == 'NOT_ENOUGH_CREDIT']
        self.assertEqual(len(holds), 2); self.assertEqual(holds[0]['credits'], 100)
        self.assertEqual(len(h.controller.journal.members()), 3)   # still managed

    def test_gate_reads_balance_at_most_every_30s_and_releases_when_coins_return(self):
        h = self.make()
        self.outbid(h)
        h.ea.bid_modes[h.ea.rows[0]['trade_id']] = 'no_credit'; h.ea.credits = 100
        h.controller.step()
        bids = len(h.calls('bid')); balances = len(h.calls('balance'))
        h.controller.step()                         # cached 100 coins: nothing sent
        self.assertEqual(len(h.calls('bid')), bids); self.assertEqual(len(h.calls('balance')), balances)
        h.ea.bid_modes.clear(); h.ea.credits = 50000; h.clock.value += 31
        h.controller.step()                         # fresh read shows coins again
        self.assertEqual(len(h.calls('balance')), balances+1)
        self.assertEqual(len(h.calls('bid')), bids+3)

    def test_no_gate_and_no_extra_balance_reads_without_a_470(self):
        h = self.make()
        self.outbid(h)
        balances = len(h.calls('balance'))
        h.controller.step()
        self.assertFalse(h.controller.credit_gate)
        self.assertEqual(len(h.calls('balance')), balances)
        self.assertEqual(len(rebids(h)), 3)

    def test_semantic_counts_470_as_account_outcome_not_write_failure(self):
        h = self.make()
        s = SemanticHealth(clock=lambda: h.clock.value)
        h.executor.result = lambda c, v: s.observe(dict(kind='native_result', **native_summary(c, v)))
        self.outbid(h)
        for r in h.ea.rows: h.ea.bid_modes[r['trade_id']] = 'no_credit'
        h.ea.credits = 10**9                        # gate never holds: every rebid reaches EA
        for _ in range(4):
            h.controller.step(); h.clock.value += 31
            for r in h.ea.rows: r.update(bid_state='outbid', expires=120)
        self.assertGreaterEqual(s.credit_rejections, 4)
        self.assertEqual(s.write_failures, 0); self.assertIsNone(s.check())

    def test_unmatched_470_shape_stays_unknown(self):
        from fc_access.controller_v1.adapter import no_credit
        good = dict(success=False, status=403, network=[dict(status=470)], receipt=dict(
            verdict='UNCONFIRMED', native_error_code=470, native_error_name='NOT_ENOUGH_CREDIT',
            native_item_count=0, matching_item_count=0, wire_identity_matches=True, wire_amount_matches=True))
        self.assertTrue(no_credit(good))
        for change in (dict(status=200), dict(network=[dict(status=461)]), dict(network=[])):
            self.assertFalse(no_credit({**good, **change}), change)
        for change in (dict(wire_amount_matches=False), dict(native_item_count=1), dict(native_error_name=None)):
            self.assertFalse(no_credit({**good, 'receipt': {**good['receipt'], **change}}), change)


class LowCredits(Base):
    """Live 04:30 incident: coins tied up in listings and highest bids fell under the
    entry threshold and the runtime halted, leaving held auctions unmanaged."""
    def test_legacy_default_still_halts(self):
        h = self.make(); h.ea.credits = 30000
        h.controller._acquire()
        self.assertEqual(h.controller.journal.state()['lifecycle'], 'HALTED')

    def test_hold_waits_without_searching_and_resumes_when_coins_return(self):
        h = self.make(low_credit_hold=True); h.ea.credits = 30000
        h.controller.step()
        self.assertEqual(h.controller.journal.state()['lifecycle'], 'RUNNING')
        self.assertEqual(h.calls('search'), [])
        self.assertEqual(h.metrics('LOW_CREDITS')[-1]['credits'], 30000)
        state = h.store.db.execute("SELECT state FROM c4_policy_batches").fetchone()[0]
        self.assertEqual(state, 'LOW_CREDITS')
        h.controller.step()                               # maintenance still runs
        h.clock.value += 31; h.controller.step()          # still low: hold, no search
        self.assertEqual(h.calls('search'), [])
        self.assertEqual(h.metrics('ACQUISITION_HOLD')[-1]['reason'], 'LOW_CREDITS')
        h.ea.credits = 50000; h.clock.value += 31; self.reset_phase(h)
        h.controller.step()
        self.assertGreater(len(h.calls('search')), 0)
        self.assertEqual(len(h.controller.journal.members()), 3)

    def test_hold_runs_maintenance_every_5_minutes(self):
        # Listings last an hour; without relisting, coins would never come back.
        h = self.make(low_credit_hold=True); h.ea.credits = 30000
        h.controller.step(); h.controller.step()          # LOW_CREDITS, then maintenance
        phases = []
        for _ in range(12):
            h.clock.value += 31; h.controller.step(); phases.append(h.controller.journal.state()['phase'])
        self.assertIn('MAINTENANCE', phases)                # one pass in ~6 minutes of holding
        self.assertLessEqual(phases.count('MAINTENANCE'), 2)
        self.assertEqual(h.calls('search'), [])
        self.assertEqual(h.controller.journal.state()['lifecycle'], 'RUNNING')

    def test_hold_with_live_members_keeps_managing(self):
        h = self.make(low_credit_hold=True)
        h.controller.step()                               # three members bid
        for r in h.ea.rows: r.update(bid_state='highest', expires=120)
        h.ea.credits = 30000; h.controller.credit_view = (30000, h.clock.value)
        self.reset_phase(h)
        h.controller.step()
        self.assertEqual(h.controller.journal.state()['phase'], 'MANAGING')
        self.assertEqual(h.controller.journal.state()['lifecycle'], 'RUNNING')

    def test_low_credit_batches_are_neutral_for_semantic_health(self):
        s = SemanticHealth(clock=lambda: 0)
        for _ in range(10):
            s.observe(dict(kind='batch_result', state='LOW_CREDITS', confirmed=0, uncertain=0))
        self.assertEqual(s.batch_failures, 0); self.assertIsNone(s.check())

    def test_flag_validation_and_cli(self):
        with self.assertRaises(ValueError): ControllerConfig(low_credit_hold=1)
        from fc_access.controller_v1.local_monitor import main  # noqa: F401  (argparse wiring imports)


def add_rows(h, start, count):
    rows = [auction(123, 15000, start+n) for n in range(count)]
    h.ea.rows.extend(rows); return rows


def members(h):
    return {t: s for t, s in h.store.db.execute('SELECT trade_id,state FROM c4_members')}


class CoinReservation(Base):
    """Admit an auction only if spendable coins (free balance minus every live
    tracked auction's remaining claim) cover its cap. Fixture caps are 10750."""
    CAP = 10750

    def make_coins(self, count=3, **values):
        return self.make(count, coin_reservation=True, entry_threshold=0, **values)

    def test_admits_only_what_spendable_covers_and_keeps_going(self):
        h = self.make_coins(); h.ea.credits = 25000
        h.controller._acquire()
        self.assertEqual(len(h.calls('bid')), 2)
        self.assertEqual(h.metrics('ACQUISITION')[-1]['coin_skips'], 1)
        b = h.controller.journal.batch(h.controller.journal.state()['batch_id'])
        self.assertEqual((b['reserved'], b['spendable']), (0, 25000))

    def test_live_auctions_reserve_cap_minus_standing_top_bid(self):
        h = self.make_coins()
        h.controller._acquire()
        self.assertEqual(h.controller._reserved(), 3*(self.CAP-150))
        add_rows(h, 50, 3); self.reset_phase(h)
        h.ea.credits = 50000            # 50000 - 31800 = 18200: one more fits
        h.controller._acquire()
        self.assertEqual(len(h.calls('bid')), 4)

    def test_outbid_reserves_full_cap_and_terminal_states_release(self):
        h = self.make_coins()
        h.controller._acquire()
        r0, r1, r2 = h.ea.rows
        r0.update(bid_state='outbid', current_bid=200)
        h.ea.bid_modes[r0['trade_id']] = 'outbid'   # our rebid lands but is overtaken again
        h.controller.step()
        self.assertEqual(h.controller._reserved(), self.CAP + 2*(self.CAP-150))
        r1.update(trade_state='closed', bid_state='outbid', expires=0)                       # lost
        r2.update(trade_state='closed', bid_state='highest', expires=0, native_is_won=True)  # won, paid
        h.controller.step()
        st = members(h)
        self.assertEqual((st[r1['trade_id']], st[r2['trade_id']]), ('LOST', 'PENDING_WIN'))
        self.assertEqual(h.controller._reserved(), self.CAP)

    def test_denied_unknown_and_unmapped_reserve_nothing(self):
        h = self.make_coins()
        h.ea.bid_modes[h.ea.rows[0]['trade_id']] = 'denied'
        h.ea.bid_modes[h.ea.rows[1]['trade_id']] = 'timeout'   # UNKNOWN; readback shows no participation
        h.controller._acquire()
        states = sorted(a['state'] for a in h.attempts())
        self.assertEqual(states, ['ACKNOWLEDGED', 'DENIED', 'UNKNOWN'])
        self.assertEqual(h.controller._reserved(), self.CAP-150)
        h.controller.unmapped.add(h.ea.rows[2]['trade_id'])   # cannot be read: never rebid
        self.assertEqual(h.controller._reserved(), 0)

    def test_band_floor_skips_unaffordable_bands_and_holds_without_searching(self):
        h = self.make_coins(1, bands=((1000, 11000), (3000, 20000)))
        h.controller._acquire(); self.reset_phase(h)          # band A floor = 10750
        h.ea.rows.clear(); add_rows(h, 60, 1)
        h.ea.credits = 5000 + (self.CAP-150)                   # spendable 5000 < every cap
        h.controller._acquire(); self.reset_phase(h)          # band B: floor unknown, searched
        self.assertEqual([p['min_buy'] for p in discoveries(h)], [11000, 20000])
        h.controller._acquire(); self.reset_phase(h)          # both floors known: no search
        self.assertEqual(len(discoveries(h)), 2)
        self.assertEqual(h.metrics('COINS_RESERVED')[-1]['spendable'], 5000)
        self.assertTrue(h.controller.coins_short)
        h.controller.step()                                    # a live auction: the hold manages it
        self.assertEqual(h.controller.journal.state()['phase'], 'MANAGING')
        for m in h.controller.journal.members(): h.controller.unmapped.add(m['target']['trade_id'])
        h.ea.credits = 5000; h.clock.value += 31; self.reset_phase(h)
        h.controller.step()                                    # nothing live: held, balance read logged
        self.assertEqual(len(discoveries(h)), 2)
        self.assertEqual(h.metrics('ACQUISITION_HOLD')[-1]['reason'], 'COINS_RESERVED')
        self.assertTrue(h.metrics('BALANCE_READ'))
        h.ea.credits = 60000; h.clock.value += 31; self.reset_phase(h)
        h.controller.step()
        self.assertEqual(len(discoveries(h)), 3)

    def test_untracked_watch_list_participation_is_logged(self):
        h = self.make_coins()
        orphan = auction(123, 15000, 900); orphan.update(bid_state='highest', current_bid=400)
        h.ea.manual.append(orphan)
        h.controller._acquire()
        self.assertEqual(h.metrics('ORPHAN_PARTICIPATION')[-1]['trades'], [orphan['trade_id']])

    def test_flag_off_keeps_the_threshold_and_validation(self):
        h = self.make(); h.ea.credits = 30000
        h.controller._acquire()
        self.assertEqual(h.controller.journal.state()['lifecycle'], 'HALTED')
        for bad in (dict(coin_reservation=1), dict(interleave='yes'), dict(interleave_window=0), dict(maintenance_interval=-5)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)


class Interleave(Base):
    """Acquisition and maintenance in quiet windows while auctions are live."""
    def make_live(self, expires=300, **values):
        h = self.make(3, interleave=True, **values)
        for r in h.ea.rows: r['expires'] = expires
        h.controller._acquire()                     # three live auctions, we are highest
        self.assertEqual(h.controller.journal.state()['phase'], 'MANAGING')
        return h

    def test_quiet_window_runs_maintenance_first_then_acquires(self):
        h = self.make_live()
        add_rows(h, 70, 2)
        searches = len(discoveries(h))
        h.controller.step()                          # status read, no war -> maintenance
        self.assertEqual(h.controller.journal.state()['phase'], 'MAINTENANCE')
        h.controller.step()                          # maintenance pass -> ACQUIRING
        h.controller.step()                          # still > 3 min to the soonest end: acquire
        self.assertEqual(len(discoveries(h)), searches+1)
        self.assertEqual(len(h.controller.journal.members()), 5)
        self.assertEqual(h.metrics('INTERLEAVE')[0]['step'], 'MAINTENANCE')

    def test_no_acquisition_when_an_auction_ends_within_the_window(self):
        h = self.make_live(expires=150)              # > 60 s: maintenance; < 180 s: no acquisition
        searches = len(discoveries(h))
        for _ in range(4): h.controller.step()
        self.assertEqual(len(discoveries(h)), searches)
        self.assertEqual(h.controller.journal.state()['phase'], 'MANAGING')

    def test_a_rebid_cycle_never_hands_off(self):
        h = self.make_live()
        for r in h.ea.rows: r.update(bid_state='outbid', current_bid=200)
        h.controller.step()
        self.assertEqual(h.controller.journal.state()['phase'], 'MANAGING')
        self.assertEqual(h.metrics('INTERLEAVE'), [])

    def test_an_auction_outbid_beyond_cap_does_not_block_hand_off(self):
        # Live 10:50 finding: outbid at 2300 against a 2200 cap, no rebid possible,
        # yet every cycle counted as a rebid cycle and interleaving stalled.
        h = self.make_live()
        h.ea.rows[0].update(bid_state='outbid', current_bid=20000)   # far above the 10750 cap
        bids = len(h.calls('bid'))
        h.controller.step()
        self.assertEqual(len(h.calls('bid')), bids)
        self.assertEqual(h.metrics('INTERLEAVE')[-1]['step'], 'MAINTENANCE')
        self.assertEqual(h.metrics('INTERLEAVE_WAIT'), [])

    def test_a_priced_out_auction_neither_closes_the_window_nor_reserves_coins(self):
        # Live 14:23-14:27: outbid beyond our 5500 cap, the auction kept being
        # extended by others for 3 min; it held the window shut and kept its cap reserved.
        h = self.make(3, interleave=True, coin_reservation=True, entry_threshold=0)
        for r in h.ea.rows: r['expires'] = 600
        h.controller._acquire()
        r0 = h.ea.rows[0]
        r0.update(bid_state='outbid', current_bid=20000, expires=30)   # ending soon, beyond cap
        h.controller.step()
        self.assertEqual(h.metrics('PRICED_OUT')[-1]['target']['trade_id'], r0['trade_id'])
        self.assertGreater(h.controller._soonest_end(), 180)
        self.assertEqual(h.controller._reserved(), 2*(10750-150))
        self.assertEqual(h.metrics('INTERLEAVE')[-1]['step'], 'MAINTENANCE')
        add_rows(h, 400, 2); searches = len(discoveries(h))
        h.controller.step(); h.controller.step()                        # maintenance, then acquire
        self.assertEqual(len(discoveries(h)), searches+1)

    def test_all_live_auctions_priced_out_still_hands_off(self):
        # Nothing actionable live must open the window, not keep managing forever.
        h = self.make_live()
        for r in h.ea.rows: r.update(bid_state='outbid', current_bid=20000)
        h.controller.step()
        self.assertIsNone(h.controller._soonest_end())
        self.assertEqual(h.metrics('INTERLEAVE')[-1]['step'], 'MAINTENANCE')
        add_rows(h, 600, 2); searches = len(discoveries(h))
        h.controller.step(); h.controller.step()
        self.assertEqual(len(discoveries(h)), searches+1)

    def test_priced_out_is_recognised_after_a_restart_from_the_last_status(self):
        h = self.make_live()
        h.ea.rows[0].update(bid_state='outbid', current_bid=10750)      # at our cap: no further bid
        h.controller.step()
        fresh = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids, clock=h.clock.clock, sleep=h.clock.sleep)
        m = next(m for m in fresh.journal.members() if m['target']['trade_id'] == h.ea.rows[0]['trade_id'])
        self.assertTrue(fresh._is_priced_out(m))
        other = next(m for m in fresh.journal.members() if m['target']['trade_id'] == h.ea.rows[1]['trade_id'])
        self.assertFalse(fresh._is_priced_out(other))

    def test_maintenance_waits_for_its_interval(self):
        h = self.make_live()
        h.controller.step(); h.controller.step()     # maintenance ran
        h.controller.search_hold_until = h.clock.value + 10**6   # acquisition held
        for _ in range(3): h.controller.step()
        self.assertEqual([m['step'] for m in h.metrics('INTERLEAVE')], ['MAINTENANCE'])
        h.clock.value += 301
        for r in h.ea.rows: r['expires'] = 300
        h.controller.step()
        self.assertEqual([m['step'] for m in h.metrics('INTERLEAVE')], ['MAINTENANCE', 'MAINTENANCE'])

    def test_flag_off_never_acquires_while_auctions_are_live(self):
        h = self.make(3)
        h.controller._acquire(); add_rows(h, 80, 2)
        searches = len(discoveries(h))
        for _ in range(4): h.controller.step()
        self.assertEqual(len(discoveries(h)), searches)
        self.assertEqual(h.metrics('INTERLEAVE'), [])


class Diagnostics(Base):
    """Logging overhaul: every decision point leaves an accurate, finite record."""
    def test_every_metric_carries_its_time(self):
        h = self.make()
        h.controller._acquire()
        rows = [json.loads(b) for (b,) in h.store.db.execute('SELECT body FROM c4_metrics')]
        self.assertTrue(rows and all(r.get('at', '').startswith('2030-01-01T') for r in rows))

    def test_bid_records_kind_reason_and_native_error(self):
        h = self.make(denial_pause=0)
        h.ea.bid_modes[h.ea.rows[0]['trade_id']] = 'denied'
        h.controller._acquire()
        bids = {b['target']['trade_id']: b for b in h.metrics('BID')}
        denied = bids[h.ea.rows[0]['trade_id']]
        self.assertEqual((denied['bid_kind'], denied['outcome'], denied['native_error']), ('initial', 'DENIED', 461))
        self.assertEqual(bids[h.ea.rows[1]['trade_id']]['outcome'], 'ACKNOWLEDGED')
        h.ea.bid_modes.clear(); self.reset_phase(h)
        h.controller._acquire()
        retry = [b for b in h.metrics('BID') if b.get('retry_of')]
        self.assertEqual(len(retry), 1)

    def test_auction_closed_once_per_outcome_with_price_against_cap(self):
        h = self.make()
        h.controller._acquire()
        r0, r1, _ = h.ea.rows
        r0.update(trade_state='closed', bid_state='outbid', current_bid=12000, expires=0)
        r1.update(trade_state='closed', bid_state='highest', expires=0, native_is_won=True)
        h.controller.step(); h.controller.step()
        closed = {c['target']['trade_id']: c for c in h.metrics('AUCTION_CLOSED')}
        self.assertEqual(len(h.metrics('AUCTION_CLOSED')), 2, 'a pending win is recorded once')
        lost = closed[r0['trade_id']]
        self.assertEqual((lost['outcome'], lost['cap'], lost['final_price'], lost['above_cap'], lost['bids']),
                         ('LOST', 10750, 12000, True, 1))
        self.assertEqual(closed[r1['trade_id']]['outcome'], 'WON')

    def test_holds_are_logged_only_when_they_change(self):
        h = self.make()
        h.controller._acquire()
        for _ in range(4): h.controller.step()       # we stay highest: same hold every cycle
        self.assertEqual(len(h.metrics('HOLD')), 3)
        h.ea.rows[0].update(bid_state='outbid', current_bid=200)
        h.ea.bid_modes[h.ea.rows[0]['trade_id']] = 'outbid'
        h.controller.step()                          # rebid clears the hold; next hold is new
        h.ea.rows[0].update(bid_state='highest')
        h.controller.step()
        self.assertEqual(len(h.metrics('HOLD')), 4)

    def test_coin_context_claims_balance_and_band_skips(self):
        h = self.make(1, coin_reservation=True, entry_threshold=0, bands=((1000, 11000), (3000, 20000)))
        h.controller._acquire(); self.reset_phase(h)
        h.ea.rows.clear(); h.ea.rows.append(auction(123, 15000, 61))
        h.ea.credits = 5000 + 10600
        h.controller._acquire(); self.reset_phase(h)
        b = h.controller.journal.batch(h.controller.journal.state()['batch_id'])
        self.assertEqual(len(b['claims']), 1)
        self.assertEqual(b['claims'][0][1:], [10750, 150, 10600])
        h.controller._acquire()
        self.assertEqual(h.metrics('BAND_SKIPPED')[0]['cheapest_cap'], 10750)
        h.clock.value += 31; h.controller._credits()
        read = h.metrics('BALANCE_READ')[-1]
        self.assertEqual((read['credits'], read['reserved'], read['spendable'], read['source']), (15600, 10600, 5000, 'CREDIT_CHECK'))
        acq = h.metrics('ACQUISITION')[1]
        self.assertEqual((acq['found'], acq['eligible'], acq['selected'], acq['min_skipped_cap'], acq['spendable_start']),
                         (1, 1, 0, 10750, 5000))

    def test_interleave_waits_steps_and_overrun_are_recorded(self):
        h = self.make(3, interleave=True)
        h.controller._acquire()
        h.controller.search_hold_until = h.clock.value + 10**6
        h.controller.step(); h.controller.step()     # maintenance pass (interleaved)
        for _ in range(3): h.controller.step()       # acquisition held: one wait record
        waits = h.metrics('INTERLEAVE_WAIT')
        self.assertEqual([w['reason'] for w in waits], ['ACQUISITION_HELD:SEARCH_THROTTLED'])
        steps = h.metrics('INTERLEAVE_STEP')
        self.assertEqual(steps[0]['step'], 'MAINTENANCE'); self.assertGreater(steps[0]['soonest_end_after'], 0)
        p = h.metrics('MAINTENANCE_PASS')[-1]
        self.assertTrue(p['interleaved']); self.assertIsNone(p['error'])
        # A slow acquisition that outlives the soonest auction is flagged.
        h.controller.search_hold_until = 0; add_rows(h, 90, 1)
        for r in h.ea.rows[:3]: r['expires'] = 200
        h.controller.step()                          # fresh proofs: 200 s left -> hand off
        h.controller.step()                          # interleaved acquisition
        acq = [x for x in h.metrics('INTERLEAVE_STEP') if x['step'] == 'ACQUIRING']
        self.assertEqual(len(acq), 1); self.assertGreater(acq[0]['soonest_end_after'], 0)
        self.assertEqual(h.metrics('INTERLEAVE_OVERRUN'), [])
        h.clock.value += 400                         # a step that outlived the soonest end
        h.controller._overrun_check('b'*32, 'ACQUIRING', 400.)
        self.assertLess(h.metrics('INTERLEAVE_OVERRUN')[-1]['soonest_end_after'], 0)

    def test_errors_carry_safe_codes(self):
        from fc_access.controller_v1.controller import error_code
        self.assertEqual(error_code(ValueError('membership_limit')), 'ValueError:membership_limit')
        self.assertEqual(error_code(ValueError('price 12000 for item 5')), 'ValueError')
        class Custom(Exception): pass
        self.assertEqual(error_code(Custom('x')), 'Exception:x')
        h = self.make()
        def boom(*a, **k): raise ValueError('synthetic_maintenance_fault')
        h.controller.work.maintenance = boom
        h.controller.journal.checkpoint(phase='MAINTENANCE'); h.controller.step()
        self.assertEqual(h.metrics('MAINTENANCE_UNKNOWN')[-1]['error'], 'ValueError:synthetic_maintenance_fault')
        self.assertEqual(h.metrics('MAINTENANCE_PASS')[-1]['error'], 'ValueError:synthetic_maintenance_fault')
        def deny(*a, **k): raise ValueError('synthetic_authority_fault')
        h.store.decide = deny; self.reset_phase(h)
        h.controller._acquire()
        self.assertEqual(h.metrics('DECISION_SKIPPED')[-1]['error'], 'ValueError:synthetic_authority_fault')

    def test_status_controller_view(self):
        from fc_access.controller_v1 import local_monitor as lm
        h = self.make(3, coin_reservation=True, entry_threshold=0)
        h.controller._acquire(); h.controller.step()
        view = lm.controller_view(h.path, '2000-01-01')
        self.assertEqual((view['phase'], view['live_auctions'], view['pending_wins']), ('MANAGING', 3, 0))
        self.assertEqual(view['last_round']['reserved'], 0)
        self.assertEqual(view['counts_since_launch']['BID'], 3)
        self.assertIn('ACQUISITION', view['latest'])
        self.assertGreater(view['soonest_end_seconds'] or 0, -10**9)
        self.assertEqual(lm.controller_view(h.path, '2999-01-01')['counts_since_launch'], {})
        h.ea.rows[0].update(bid_state='outbid', current_bid=20000)   # priced out
        h.controller.step()
        view = lm.controller_view(h.path, '2000-01-01')
        self.assertEqual((view['live_auctions'], view['priced_out']), (3, 1))


class DenialWave(Base):
    """461 waves are waited out in-process: escalating acquisition pause, no stop."""
    def fresh_denied_round(self, h, n):
        rows = add_rows(h, 200+10*n, 2)
        for r in rows: h.ea.bid_modes[r['trade_id']] = 'denied'
        for r in h.ea.rows:
            if r not in rows: r.update(trade_state='closed', expires=0)   # old ones leave discovery
        h.ea.discovery = rows

    def test_pause_doubles_per_denied_round_up_to_the_cap(self):
        h = self.make(0, denial_pause=120, denial_pause_max=900)
        pauses = []
        for n in range(5):
            self.fresh_denied_round(h, n); self.reset_phase(h)
            h.controller._acquire()
            pauses.append(h.metrics('DENIAL_WAVE')[-1]['pause'])
            h.clock.value = h.controller.denial_hold_until + 1
        self.assertEqual(pauses, [120, 240, 480, 900, 900])
        w = h.metrics('DENIAL_WAVE')[-1]
        self.assertEqual((w['state'], w['rounds'], w['denials']), ('ONGOING', 5, 10))

    def test_first_accepted_opening_bid_ends_the_wave(self):
        h = self.make(0, denial_pause=120)
        self.fresh_denied_round(h, 0); h.controller._acquire()
        h.clock.value = h.controller.denial_hold_until + 1
        rows = add_rows(h, 300, 1); h.ea.discovery = rows; self.reset_phase(h)
        h.controller._acquire()
        end = h.metrics('DENIAL_WAVE')[-1]
        self.assertEqual((end['state'], end['rounds'], end['denials']), ('ENDED', 1, 2))
        self.assertIsNone(h.controller.denial_wave)
        self.fresh_denied_round(h, 1); self.reset_phase(h)
        h.clock.value = h.controller.denial_hold_until + 1
        h.controller._acquire()
        self.assertEqual(h.metrics('DENIAL_WAVE')[-1]['pause'], 120, 'a new wave starts from the base pause')

    def test_live_auctions_keep_being_managed_during_a_wave(self):
        h = self.make(3, denial_pause=120)
        h.controller._acquire()                                  # three live auctions
        self.fresh_denied_round(h, 0)
        for r in h.ea.rows[:3]: r.update(trade_state='active', expires=600)
        h.controller.journal.checkpoint(phase='ACQUIRING'); h.controller._acquire()
        self.assertTrue(h.controller.denial_wave)
        reads = len(h.calls('status_batch'))
        h.ea.rows[0].update(bid_state='outbid', current_bid=200)
        h.controller.step(); h.controller.step()               # hold hands to managing; rebid goes out
        self.assertGreater(len(h.calls('status_batch')), reads)
        self.assertTrue(any(c['command']['params']['target']['trade_id'] == h.ea.rows[0]['trade_id']
                            for c in h.calls('bid')[-2:]))

    def test_semantic_stop_only_after_two_hours_of_denials(self):
        from fc_access.controller_v1.semantic import SemanticLimits
        self.assertEqual(SemanticLimits().denial_window, 7200)
        with self.assertRaises(ValueError): ControllerConfig(denial_pause_max=7201)


class BidAtCap(Base):
    """One bid at our cap per auction; once outbid it is priced out (no wars)."""
    def test_opening_bid_is_the_cap_on_a_legal_tick_with_the_native_minimum(self):
        h = self.make(3, bid_at_cap=True)
        h.controller._acquire()
        sent = [c['command']['params'] for c in h.calls('bid')]
        self.assertEqual(len(sent), 3)
        for p in sent:
            self.assertEqual(p['amount'], p['cap'])                    # fixture cap 10750 is a legal tick
            self.assertLess(p['minimum'], p['amount'])                 # minimum stays EA's own minimum
        self.assertEqual(h.controller._reserved(), 0, 'highest at our cap: nothing left to claim')

    def test_outbid_means_priced_out_and_no_rebid(self):
        h = self.make(3, bid_at_cap=True, interleave=True)
        for r in h.ea.rows: r['expires'] = 600
        h.controller._acquire()
        bids = len(h.calls('bid'))
        h.ea.rows[0].update(bid_state='outbid', current_bid=11000)   # a legal tick above our cap
        h.controller.step()
        self.assertEqual(len(h.calls('bid')), bids)
        self.assertEqual(h.metrics('PRICED_OUT')[-1]['target']['trade_id'], h.ea.rows[0]['trade_id'])

    def test_acquisition_is_continuous_with_auctions_about_to_end(self):
        # Holding our cap, an auction ending in 30 s needs no protection: no rebid
        # is ever possible, so the window stays open.
        h = self.make(3, bid_at_cap=True, interleave=True)
        for r in h.ea.rows: r['expires'] = 30
        h.controller._acquire()
        self.assertIsNone(h.controller._soonest_end())
        add_rows(h, 500, 2); searches = len(discoveries(h))
        h.controller.step(); h.controller.step(); h.controller.step()   # manage -> maintenance -> acquire
        self.assertEqual(len(discoveries(h)), searches+1)
        self.assertEqual(h.metrics('INTERLEAVE_WAIT'), [])

    def test_flag_off_bids_the_minimum(self):
        h = self.make(3)
        h.controller._acquire()
        self.assertTrue(all(c['command']['params']['amount'] == c['command']['params']['minimum'] for c in h.calls('bid')))

    def test_every_layer_still_refuses_above_cap_or_below_minimum(self):
        from fc_access.controller_v1.protocol import command
        h = self.make(3)
        h.controller._acquire()
        a = h.attempts()[0]['body']['params']
        base = dict(batch_id=a['batch_id'], status_read_id=a['status_read_id'], identity=a['target'], deadline=a['deadline'])
        for amount, minimum in ((a['cap']+50, a['minimum']), (a['minimum']-50, a['minimum'])):
            with self.assertRaises(ValueError):
                h.store.decide('e'*32, amount=amount, minimum=minimum, cap=a['cap'], **base)
        c = h.calls('bid')[0]['command']
        for amount in (c['params']['cap']+50, c['params']['minimum']-50):
            bad = json.loads(json.dumps(c)); bad['params']['amount'] = amount
            with self.assertRaises(ValueError): command(bad)


class BandChoice(Base):
    """Remembered band caps (no blind re-search) and profit-per-coin band ranking."""
    BANDS = ((1000, 11000), (3000, 20000), (5000, 30000))

    def history(self, h, band, wins, losses, cap):
        """Settled auctions in a band, as the ranking reads them."""
        import secrets
        bid = secrets.token_hex(16)
        h.store.db.execute('INSERT INTO c4_policy_batches VALUES (?,?,?)', (bid, 'SETTLED', json.dumps(dict(band=list(band)))))
        for i in range(wins+losses):
            h.store.db.execute('INSERT INTO c4_members VALUES (?,?,?,?)', (f'trade:{secrets.token_hex(12)}', bid,
                'WON_ACCOUNTED' if i < wins else 'LOST', json.dumps(dict(cap=cap, target={}))))
        h.store.db.commit()

    def test_unaffordable_band_is_not_searched_again_within_the_hour(self):
        h = self.make(1, coin_reservation=True, entry_threshold=0, bands=self.BANDS[1:])
        h.controller._acquire(); self.reset_phase(h)               # 3k:20k cheapest cap 10750 remembered
        h.controller.band_floor[(5000, 30000)] = (17000, h.clock.value)
        h.ea.credits = 10750 - 1 + (10750-150)                       # spendable just below every cap
        searches = len(discoveries(h))
        h.clock.value += 1200                                        # 20 min: the old memory expired at 15
        h.controller._acquire(); self.reset_phase(h)
        self.assertEqual(len(discoveries(h)), searches)
        self.assertEqual(h.metrics('COINS_RESERVED')[-1]['spendable'], 10749)
        h.clock.value += 3600                                        # an hour later: one re-check
        h.controller._acquire()
        self.assertEqual(len(discoveries(h)), searches+1)

    def test_band_memory_survives_a_restart(self):
        h = self.make(1, coin_reservation=True, entry_threshold=0)
        h.controller._acquire()
        self.assertEqual(h.metrics('ACQUISITION')[-1]['cheapest_cap'], 10750)
        fresh = Controller(h.store, h.adapter, h.cache, config=h.config, ids=h.ids, clock=h.clock.clock, sleep=h.clock.sleep)
        self.assertEqual(fresh.band_floor[(1000, 11000)][0], 10750)

    def test_ranking_orders_by_profit_per_coin_and_explores(self):
        h = self.make(1, coin_reservation=True, entry_threshold=0, rank_bands=True, bands=self.BANDS)
        self.history(h, self.BANDS[0], 2, 90, 5100)                  # live today: 2.2% at 5.1k
        self.history(h, self.BANDS[1], 4, 21, 7300)                  # 16% at 7.3k
        self.history(h, self.BANDS[2], 4, 30, 17750)                 # 11.8% at 17.75k
        order = h.controller._band_order()
        self.assertEqual(order, [self.BANDS[1], self.BANDS[0], self.BANDS[2]])
        self.assertEqual(h.metrics('BAND_RANK')[-1]['order'], [list(b) for b in order])
        picks = []
        for _ in range(5):
            picks.append(h.controller._fitting_band(10**6))
        self.assertEqual(picks[0], self.BANDS[0], 'round 0 explores (rotation)')
        self.assertEqual(picks[1:], [self.BANDS[1]]*4, 'then the best band')

    def test_ranking_falls_back_to_the_next_affordable_band(self):
        h = self.make(1, coin_reservation=True, entry_threshold=0, rank_bands=True, bands=self.BANDS)
        self.history(h, self.BANDS[1], 4, 21, 7300); self.history(h, self.BANDS[0], 2, 90, 5100)
        h.controller.rounds = 1                                      # not an exploration round
        h.controller.band_floor[self.BANDS[1]] = (7300, h.clock.value)
        h.controller.band_floor[self.BANDS[0]] = (3900, h.clock.value)
        self.assertEqual(h.controller._fitting_band(5000), self.BANDS[0])

    def test_flag_off_keeps_the_rotation(self):
        h = self.make(1, coin_reservation=True, entry_threshold=0, bands=self.BANDS)
        self.history(h, self.BANDS[1], 4, 21, 7300)
        self.assertEqual([h.controller._fitting_band(10**6) for _ in range(4)], list(self.BANDS)+[self.BANDS[0]])
        for bad in (dict(rank_bands=1), dict(explore_every=0), dict(band_recheck=10)):
            with self.assertRaises(ValueError, msg=bad): ControllerConfig(**bad)


class LaunchFlags(unittest.TestCase):
    def test_flags_reach_the_controller_config(self):
        from fc_access.controller_v1 import local_monitor as lm
        from fc_access.controller_v1.__main__ import controller_config
        a = lm.parser().parse_args(['launch', '--coin-reservation', '--interleave', '--low-credit-hold'])
        self.assertTrue(a.coin_reservation and a.interleave and a.low_credit_hold)
        c = controller_config(a)
        self.assertEqual((c.coin_reservation, c.interleave, c.entry_threshold), (True, True, 0))
        plain = controller_config(lm.parser().parse_args(['launch']))
        self.assertEqual((plain.coin_reservation, plain.interleave, plain.entry_threshold), (False, False, 40000))
        self.assertEqual(plain.watch_reserve, 1)
        self.assertEqual(controller_config(lm.parser().parse_args(['launch', '--watch-reserve', '10'])).watch_reserve, 10)


if __name__ == '__main__': unittest.main(verbosity=2)
