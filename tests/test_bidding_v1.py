"""001c-02 acceptance checks; isolated SQLite/temp files and fake native services.

Run independently: python tests/test_bidding_v1.py
No browser, network requests, account mutations, or actor service loops.
"""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.bidding_v1.contracts import *
from fc_access.bidding_v1.adapter import NativeAdapter, parse_response, snapshot
from fc_access.bidding_v1.core import AuctionQueue, decide
from fc_access.bidding_v1.journal import Journal
from fc_access.bidding_v1.rules import RulesProvider, estimate_cap, minimum_bid
from fc_access.bidding_v1.scheduler import Scheduler, Work
from fc_access.harness import empty_result, project_auction
from fc_access.pricing import MarketKey, Observation

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
SCOPE, OWNER, KEY = "a"*32, "b"*32, "c"*32


def cid(n):
    return f"{n:032x}"


def fresh(n=1, at=NOW, **kw):
    return Freshness(at, at, 1, cid(n), "fixture", **kw)


def status(n=1, state=State.ACTIVE, current=0, at=NOW, **kwargs):
    return AuctionStatus(Identity(f"trade:{n:024x}", f"item:{n:024x}", 123), state,
                         150, current, 20000, at+timedelta(seconds=100+n), fresh(n, at), **kwargs)


def balance(coins=50000, n=900, at=NOW):
    return Balance(coins, 0, fresh(n, at))


def intent(s=None, *, n=100, epoch=1, amount=150, cap=1000, b=None):
    s, b = s or status(), b or balance()
    return BidIntent(cid(n), OWNER, SCOPE, epoch, s.identity, amount, cap, s.deadline,
                     s.freshness.read_id, b.freshness.read_id)


class Fixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.clock = NOW
        self.rules_path = self.path / "rules.json"
        self.doc = {"schema": 1, "classification": "OFFLINE_VALIDATED", "source": "native_card_caps_and_increment_schedule",
                    "observed_at": NOW.isoformat(), "key": {"definition_id": 123, "platform": "pc", "game": "fc27"},
                    "minimum": 150, "maximum": 20000,
                    "bands": [{"start": 150, "stop": 1000, "step": 50}, {"start": 1000, "stop": 10000, "step": 100},
                              {"start": 10000, "stop": 20001, "step": 250}]}
        self.rules, self.provider = self.load_rules()

    def load_rules(self):
        raw = json.dumps(self.doc).encode()
        self.rules_path.write_bytes(raw)
        provider = RulesProvider([hashlib.sha256(raw).hexdigest()], allow_offline=True)
        return provider.load(self.rules_path, key=MarketKey(123, "pc"), now=NOW), provider

    def journal(self):
        j = Journal(self.path / "events.sqlite", now=lambda: self.clock)
        self.addCleanup(j.close)
        return j

    def observations(self):
        return [Observation(f"t{i}", f"i{i}", MarketKey(123, "pc"), price, NOW, 400)
                for i, price in enumerate((12000, 12250, 12500, 12750, 13000))]


class ContractRulesTests(Fixture, unittest.TestCase):
    def test_typed_contracts_and_search_filter_boundaries(self):
        q = Search(page=2, max_bid=1000, min_buy=10500)
        self.assertEqual(asdict(q)["max_bid"], 1000)
        for kwargs in ({"page": 3}, {"count": 50}, {"max_bid": True}, {"min_buy": -1},
                       {"fresh": 1}, {"definition_id": 0}, {"min_buy": 10, "max_buy": 9}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Search(**kwargs)
        with self.assertRaises(ValueError):
            Identity("123", "456", 123)
        with self.assertRaises(ValueError):
            replace(status().identity, platform="PC")
        with self.assertRaises(ValueError):
            replace(status(), state="LEADING")
        with self.assertRaises(ValueError):
            replace(status(), deadline=NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            Coverage(True, False)
        self.assertFalse(replace(fresh(), request_count=0).fresh(NOW))
        self.assertFalse(replace(fresh(), network_at=None).fresh(NOW))
        self.assertFalse(fresh().fresh(NOW-timedelta(seconds=1)))

    def test_provenance_fails_closed_and_artifact_tampering(self):
        key = MarketKey(123, "pc")
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            RulesProvider([]).load(self.rules_path, key=key, now=NOW)
        with self.assertRaisesRegex(ValueError, "provenance"):
            RulesProvider(self.provider.reviewed_hashes).load(self.rules_path, key=key, now=NOW)
        for key2, now in ((MarketKey(124, "pc"), NOW), (key, NOW+timedelta(seconds=301)), (key, NOW-timedelta(seconds=1))):
            with self.assertRaises(ValueError):
                self.provider.load(self.rules_path, key=key2, now=now)
        self.rules_path.write_text("{}")
        with self.assertRaises(ValueError):
            self.provider.validate(self.rules, key=key, now=NOW)

    def test_unsupported_caps_increment_gaps_and_boundaries(self):
        for change in (lambda: self.doc.update(maximum=19999),
                       lambda: self.doc["bands"][1].update(start=1100),
                       lambda: self.doc["bands"][0].update(step=60)):
            original = json.loads(json.dumps(self.doc))
            change()
            with self.assertRaises(ValueError):
                self.load_rules()
            self.doc = original
        rules, _ = self.load_rules()
        for current, expected in ((0, 150), (150, 200), (950, 1000), (1000, 1100),
                                  (9900, 10000), (10000, 10250), (19750, 20000), (20000, None)):
            self.assertEqual(minimum_bid(status(current=current), rules), expected)
        with self.assertRaises(ValueError):
            minimum_bid(status(current=151), rules)
        with self.assertRaises(ValueError):
            minimum_bid(replace(status(), identity=replace(status().identity, definition_id=999)), rules)

    def test_reuses_exact_version_five_comparable_outlier_pricing(self):
        key = MarketKey(123, "pc")
        observations = [Observation(f"t{i}", f"i{i}", key, price, NOW, 400) for i, price in enumerate((12000, 12250, 12500, 12750, 13000, 20000))]
        result, cap = estimate_cap(status(), observations, self.rules, self.provider, now=NOW)
        self.assertEqual((result.status, result.sample_count, result.target_sale_price, cap), ("OK", 5, 12000, 10750))
        self.assertIn(("outlier", 1), result.rejected)
        wrong = [replace(row, key=MarketKey(999, "pc")) for row in observations]
        self.assertIsNone(estimate_cap(status(), wrong, self.rules, self.provider, now=NOW)[1])
        self.assertIsNone(estimate_cap(status(), observations[:4]*2, self.rules, self.provider, now=NOW)[1])


class QueueDecisionTests(Fixture, unittest.TestCase):
    def test_50_auctions_deduplication_deadlines_capacity_pending_and_terminal_handoff(self):
        queue = AuctionQueue()
        rows = [status(i, State.PENDING if i % 2 else State.LEADING, 150) for i in range(1, 51)]
        for row in rows:
            self.assertEqual(queue.admit(replace(row, state=State.ACTIVE), balance(), 150, now=NOW), "ENROLLED")
        self.assertEqual(queue.admit(status(51), balance(), 150, now=NOW), "QUEUE_FULL")
        self.assertEqual(queue.admit(status(1), balance(), 150, now=NOW), "PENDING")
        snap = Snapshot(tuple(reversed(rows))+(rows[0],), fresh(), Coverage(False, None))
        states = queue.refresh(snap, now=NOW)
        self.assertEqual(len(states), 50)
        self.assertEqual(sum(s == State.PENDING for s in states.values()), 25)
        self.assertEqual([r.identity for r in queue.deadlines()], [r.identity for r in rows])
        # Missing, expired active, and conflicting rows never establish a loss.
        conflict = replace(rows[0], current_bid=200)
        states = queue.refresh(replace(snap, auctions=(rows[0], conflict)), now=NOW)
        self.assertEqual(set(states.values()), {State.UNKNOWN})
        self.assertEqual(len(queue.entries), 50)
        won = replace(rows[0], state=State.WON, owned_item_id=rows[0].identity.item_id, paid=150)
        lost = replace(rows[1], state=State.LOST)
        queue.refresh(replace(snap, auctions=(won, lost)), now=NOW)
        self.assertEqual(len(queue.entries), 48)
        self.assertNotIn(won.identity.trade_id, queue.entries)
        with self.assertRaises(ValueError):
            replace(won, paid=None)
        with self.assertRaises(ValueError):
            AuctionQueue(capacity=51)

    def test_sticky_5000_draining_survives_restart_until_all_confirmed_terminal(self):
        j = self.journal()
        queue = AuctionQueue(journal=j, scope=SCOPE)
        self.assertEqual(queue.admit(status(), balance(5150), 150, now=NOW), "ENROLLED")
        self.assertTrue(queue.draining)
        replay = AuctionQueue(journal=j, scope=SCOPE)
        self.assertTrue(replay.draining)
        self.assertEqual(replay.admit(status(2), balance(99999), 150, now=NOW), "DRAINING")
        replay.refresh(Snapshot((), fresh(), Coverage(True, False, evidence_id=cid(20))), now=NOW)
        self.assertTrue(replay.draining)
        replay.refresh(Snapshot((replace(status(), state=State.LOST),), fresh(), Coverage(False, None)), now=NOW)
        self.assertFalse(replay.draining)
        self.assertEqual(replay.admit(status(2), balance(5000, n=901), 150, now=NOW), "DRAINING")
        self.assertEqual(replay.admit(status(2), balance(99999, n=901), 150, now=NOW), "DRAINING")

    def test_account_cap_and_insufficient_reserve(self):
        q = AuctionQueue()
        self.assertEqual(q.admit(status(), balance(), 150, now=NOW, account_capacity=1), "ENROLLED")
        self.assertEqual(q.admit(status(2), balance(), 150, now=NOW, account_capacity=1), "QUEUE_FULL")
        q = AuctionQueue()
        self.assertEqual(q.admit(status(), balance(5100), 150, now=NOW), "DRAINING")
        self.assertFalse(q.entries)

    def test_multiple_pending_reservations_replay_and_identity_conflict(self):
        j = self.journal()
        q = AuctionQueue(journal=j, scope=SCOPE)
        self.assertEqual(q.admit(status(), balance(5300), 150, now=NOW), "ENROLLED")
        replay = AuctionQueue(journal=j, scope=SCOPE)
        self.assertEqual(replay.admit(status(2), balance(5300), 150, now=NOW), "ENROLLED")
        self.assertTrue(replay.draining)  # both pending bids consume one balance
        self.assertEqual(sum(v[0] for v in replay.reservations.values()), 300)
        self.assertEqual(replay.admit(status(3), balance(99999), 150, now=NOW), "DRAINING")
        wrong = replace(status(), identity=replace(status().identity, definition_id=999), state=State.LOST)
        resolved = replay.refresh(Snapshot((wrong,), fresh(), Coverage(False, None)), now=NOW)
        self.assertEqual(resolved[status().identity.trade_id], State.UNKNOWN)
        self.assertEqual(len(replay.entries), 2)
        leading = replace(status(state=State.LEADING, current=150), freshness=fresh(800))
        replay.refresh(Snapshot((leading,), fresh(800), Coverage(False, None)), now=NOW)
        self.assertEqual(len(replay.reservations), 1)
        replay2 = AuctionQueue(journal=j, scope=SCOPE)
        self.assertEqual(len(replay2.reservations), 1)
        self.assertIn(cid(900), replay2.invalid_balances)

    def test_admission_and_draining_are_one_atomic_checkpoint(self):
        j = self.journal()
        original = j._event
        def interrupted(scope, reason, *args):
            if reason == "DRAINING":
                raise RuntimeError("simulated checkpoint failure")
            return original(scope, reason, *args)
        j._event = interrupted
        queue = AuctionQueue(journal=j, scope=SCOPE)
        with self.assertRaises(RuntimeError):
            queue.admit(status(), balance(5150), 150, now=NOW)
        self.assertFalse(queue.entries)
        self.assertFalse(j.trace())
        replay = AuctionQueue(journal=j, scope=SCOPE)
        self.assertFalse(replay.entries)
        self.assertFalse(replay.draining)

    def test_hold_minimum_legal_rebid_caps_pending_deadlines_unknown(self):
        def decision(s, cap=1000, b=None, **kw):
            return decide(s, b or balance(), self.rules, cap, now=NOW, **kw)
        self.assertEqual(decision(status(state=State.LEADING, current=150)).reason, "HOLD")
        self.assertEqual(decision(status(state=State.OUTBID, current=950)).amount, 1000)
        self.assertEqual(decision(status(state=State.OUTBID, current=950), cap=999).reason, "OVER_CAP")
        self.assertEqual(decision(status(), cap=150).amount, 150)
        self.assertEqual(decision(status(), cap=149).reason, "OVER_CAP")
        self.assertEqual(decision(status(), b=balance(149)).reason, "INSUFFICIENT_BALANCE")
        self.assertEqual(decision(status(), pending=True).reason, "PENDING")
        self.assertEqual(decision(status(state=State.PENDING)).reason, "PENDING")
        self.assertEqual(decision(status(state=State.UNKNOWN)).reason, "UNKNOWN")
        self.assertEqual(decision(replace(status(), deadline=NOW)).reason, "EXPIRED")
        self.assertEqual(decision(replace(status(), freshness=replace(fresh(), network_at=None))).reason, "STALE")
        self.assertEqual(decision(replace(status(), buy_now_price=150)).reason, "OVER_CAP")


class JournalTests(Fixture, unittest.TestCase):
    def test_intent_precedes_send_ack_requires_reconciliation_no_blind_retries(self):
        j = self.journal()
        epoch = j.session(SCOPE, OWNER)
        i = intent(epoch=epoch)
        j.intend(i, {"spendable": 50000, "target": 12000, "tax": 600, "profit_threshold": 500, "samples": 5})
        calls = []
        def send():
            other = sqlite3.connect(self.path / "events.sqlite")
            self.assertEqual(other.execute("SELECT state FROM commands").fetchall(), [("UNKNOWN",)])
            self.assertEqual(other.execute("SELECT reason FROM events ORDER BY seq DESC LIMIT 1").fetchone()[0], "PENDING")
            other.close()
            calls.append(1)
            return BidResult(i.command_id, Outcome.ACKNOWLEDGED, "NATIVE_ACK")
        j.dispatch(i, send)
        with self.assertRaises(ValueError):
            j.dispatch(i, send)
        with self.assertRaises(ValueError):
            j.intend(intent(n=101))
        leading = status(state=State.LEADING, current=150)
        args = dict(scope=SCOPE, owner=OWNER, epoch=epoch)
        with self.assertRaises(ValueError):
            j.reconcile(i.command_id, status=leading, balance=balance(), **args)
        leading = replace(leading, freshness=fresh(800))
        j.reconcile(i.command_id, status=leading, balance=balance(n=901), **args)
        with self.assertRaises(ValueError):
            j.intend(i)
        j.intend(intent(replace(leading, state=State.OUTBID), n=101, amount=200, b=balance(n=901)))
        self.assertEqual(calls, [1])
        trace = j.trace(trade_id=i.identity.trade_id)
        self.assertEqual([e["reason"] for e in trace], ["INTENT_DURABLE", "PENDING", "NATIVE_ACK", "BID_VERIFIED", "INTENT_DURABLE"])
        self.assertTrue(all(e["version"] == 1 and datetime.fromisoformat(e["at"]).utcoffset() == timedelta(0) for e in trace))

    def test_ownership_epochs_unknown_and_independent_reconciliation(self):
        j = self.journal()
        epoch = j.session(SCOPE, OWNER)
        i = intent(epoch=epoch)
        j.intend(i)
        other = self.journal()
        next_epoch = other.session(SCOPE, OWNER)
        self.assertEqual(next_epoch, 2)
        with self.assertRaisesRegex(ValueError, "epoch"):
            j.dispatch(i, lambda: self.fail("stale owner sent"))
        with self.assertRaisesRegex(ValueError, "reconciliation"):
            other.intend(intent(n=101, epoch=2))
        args = dict(scope=SCOPE, owner=OWNER, epoch=next_epoch)
        for bad in (status(state=State.UNKNOWN), replace(status(), state=State.OUTBID, current_bid=100), status(2, State.LOST)):
            with self.assertRaises(ValueError):
                other.reconcile(i.command_id, status=replace(bad, freshness=fresh(800)), balance=balance(n=901), **args)
        other.reconcile(i.command_id, status=replace(status(), state=State.LOST, freshness=fresh(800)), balance=balance(n=901), **args)
        other.intend(intent(n=101, epoch=next_epoch))

    def test_unknown_on_invalid_response_exception_and_deadline_skip(self):
        for response in (None, RuntimeError("PRIVATE-CANARY"), BidResult(cid(999), Outcome.ACKNOWLEDGED, "NATIVE_ACK")):
            with tempfile.TemporaryDirectory() as directory:
                j = Journal(Path(directory)/"j.sqlite", now=lambda: self.clock)
                self.clock = NOW
                j.session(SCOPE, OWNER)
                i = intent()
                j.intend(i)
                def send():
                    if isinstance(response, Exception):
                        raise response
                    return response
                self.assertEqual(j.dispatch(i, send).outcome, Outcome.UNKNOWN)
                self.assertNotIn("PRIVATE-CANARY", json.dumps(j.trace()))
                with self.assertRaises(ValueError):
                    j.intend(intent(n=101))
                j.close()
        j = self.journal()
        j.session(SCOPE, OWNER)
        i = intent()
        j.intend(i)
        self.clock = i.deadline
        j.dispatch(i, lambda: self.fail("stale send"))
        self.assertEqual(j.trace()[-1]["reason"], "NOT_DISPATCHED")

    def test_transaction_rollback_append_only_privacy_and_cli_trace(self):
        j = self.journal()
        j.session(SCOPE, OWNER)
        with self.assertRaises(ValueError):
            j.intend(intent(), {"cookie": "PRIVATE-CANARY"})
        self.assertEqual(j.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0], 0)
        j.record(SCOPE, "LIFECYCLE_ERROR", {"epoch": 1})
        for sql in ("DELETE FROM events", "UPDATE events SET reason='HOLD'"):
            with self.assertRaises(sqlite3.IntegrityError):
                j.db.execute(sql)
        with self.assertRaises(ValueError):
            j.record(SCOPE, "PRIVATE-CANARY")
        run = subprocess.run([sys.executable, "-m", "fc_access.bidding_v1.journal", str(self.path/"events.sqlite"), "--scope", SCOPE], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual([e["reason"] for e in json.loads(run.stdout)], ["SESSION_STARTED", "LIFECYCLE_ERROR"])

    def test_process_crash_after_native_write_preserves_claim_and_prevents_replay(self):
        # Real process termination, not just a mocked exception/normal close.
        script = """
import os, sys
sys.path.insert(0, 'tests')
from test_bidding_v1 import *
j = Journal(sys.argv[1], now=lambda: NOW)
j.session(SCOPE, OWNER)
i = intent()
j.intend(i)
def send():
    with open(sys.argv[2], 'a') as f:
        f.write('native-write\\n'); f.flush(); os.fsync(f.fileno())
    os._exit(23)
j.dispatch(i, send)
"""
        db, writes = self.path/"events.sqlite", self.path/"writes.txt"
        run = subprocess.run([sys.executable, "-c", script, str(db), str(writes)], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 23, run.stderr)
        j = self.journal()
        self.assertEqual(j.db.execute("SELECT state FROM commands").fetchone()[0], "UNKNOWN")
        with self.assertRaises(ValueError):
            j.dispatch(intent(), lambda: self.fail("replayed write"))
        j.session(SCOPE, OWNER)
        with self.assertRaises(ValueError):
            j.intend(intent(n=101, epoch=2))
        self.assertEqual(writes.read_text().splitlines(), ["native-write"])

    def test_reopen_after_intent_only_never_gains_dispatch_authority(self):
        j = self.journal()
        j.session(SCOPE, OWNER)
        j.intend(intent())
        other = self.journal()
        with self.assertRaisesRegex(ValueError, "authority"):
            other.dispatch(intent(), lambda: self.fail("recovered intent replayed"))
        self.assertEqual(other.db.execute("SELECT state FROM commands").fetchone()[0], "UNKNOWN")
        with self.assertRaises(ValueError):
            j.dispatch(replace(intent(), amount=200), lambda: self.fail("changed intent sent"))

    def test_process_crash_before_send_never_replays_unknown_intent_or_claim(self):
        for phase in ("intent", "claim"):
            with self.subTest(phase=phase):
                db = self.path/(phase+".sqlite")
                script = """
import os, sys
sys.path.insert(0, 'tests')
from test_bidding_v1 import *
j = Journal(sys.argv[1], now=lambda: NOW)
j.session(SCOPE, OWNER)
j.intend(intent())
if sys.argv[2] == 'intent': os._exit(24)
original = j._owner
checks = 0
def owner_check(*args):
    global checks
    original(*args)
    checks += 1
    if checks == 2: os._exit(25)
j._owner = owner_check
j.dispatch(intent(), lambda: os._exit(99))
"""
                run = subprocess.run([sys.executable, "-c", script, str(db), phase], cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 24 if phase == "intent" else 25, run.stderr)
                recovered = Journal(db, now=lambda: NOW)
                try:
                    self.assertEqual(recovered.db.execute("SELECT state FROM commands").fetchone()[0], "UNKNOWN")
                    with self.assertRaises(ValueError):
                        recovered.dispatch(intent(), lambda: self.fail("replayed unknown"))
                    reasons = [e["reason"] for e in recovered.trace()]
                    self.assertEqual("PENDING" in reasons, phase == "claim")
                finally:
                    recovered.close()

    def test_stored_cap_cannot_increase_and_latency_is_durable(self):
        j = self.journal()
        j.session(SCOPE, OWNER)
        j.intend(intent())
        j.reconcile(cid(100), scope=SCOPE, owner=OWNER, epoch=1,
                    status=replace(status(state=State.OUTBID, current=150), freshness=fresh(800)), balance=balance(n=901))
        with self.assertRaisesRegex(ValueError, "cap_increase"):
            j.intend(replace(intent(n=101, amount=200), cap=1100))
        clock = [0]
        scheduler = Scheduler(lambda: clock[0], journal=j, scope=SCOPE)
        scheduler.enqueue(Work(cid(800), "read", 0, 10))
        scheduler.delivery(cid(800), .0025, enqueued_at=0)
        scheduler.next()
        clock[0] = .1235
        scheduler.complete(cid(800))
        events = j.trace()[-2:]
        self.assertEqual(events[0]["data"]["local_delivery_ms"], 2.5)
        self.assertEqual(events[1]["data"]["native_service_ms"], 123.5)


class SchedulerTests(unittest.TestCase):
    def test_configurable_cadence_local_latency_priority_bursts_concurrency_and_skips(self):
        clock = [0.0]
        s = Scheduler(lambda: clock[0], min_native_interval=2, concurrency=2, capacity=3)
        read, write = Work(cid(1), "read", 0, 20), Work(cid(2), "write", 0, 10)
        s.enqueue(read)
        s.enqueue(write)
        s.enqueue(Work(cid(3), "read", 0, 1))
        with self.assertRaises(ValueError):
            s.enqueue(Work(cid(4), "read", 0, 5))
        s.delivery(cid(2), .003, enqueued_at=0)
        self.assertEqual(s.next(), write)
        self.assertIsNone(s.next())
        clock[0] = 2
        self.assertEqual(s.next(), read)
        self.assertEqual(s.skipped, [(cid(3), "DEADLINE_SKIPPED")])
        s.enqueue(Work(cid(4), "write", 0, 20))
        clock[0] = 4
        self.assertIsNone(s.next())  # two active
        s.complete(write.command_id)
        self.assertEqual(s.next().command_id, cid(4))
        with self.assertRaises(ValueError):
            s.enqueue(write)
        self.assertEqual(s.metrics[0]["local_delivery_ms"], 3)
        self.assertEqual(s.metrics[1]["native_service_ms"], 4000)
        self.assertEqual(s.last_native, 4)

    def test_zero_gap_and_25_second_50_row_bulk_cycle_model(self):
        clock = [0]
        s = Scheduler(lambda: clock[0])
        for n in range(1, 4):
            s.enqueue(Work(cid(n), "read", 25*(n-1), 25*n))
        for n in range(1, 4):
            clock[0] = 25*(n-1)
            self.assertEqual(s.next().command_id, cid(n))
            clock[0] += .2  # synthetic one bulk call containing 50 rows
            s.complete(cid(n), request_count=1)
        self.assertEqual(sum(m["request_count"] for m in s.metrics), 3)
        self.assertTrue(all(m["native_service_ms"] < 25000 for m in s.metrics))
        burst = Scheduler(lambda: 0, concurrency=2)
        for n in range(1, 3):
            burst.enqueue(Work(cid(n), "read", 0, 1))
            self.assertIsNotNone(burst.next())  # no arbitrary 30s limit


def wire(command_id, operation, *, rows=(), success=True, network=True):
    r = empty_result(None if success else "service_timeout")
    r.update(success=success, status=200 if success else None, platform="pc")
    if operation in {"search", "watched"}:
        r["auctions"] = list(rows)
    if operation == "balance":
        r["credits"] = 50000
    route = {"search":"transfermarket", "watched":"watchlist", "balance":"user/currencies", "bid":"trade/:trade/bid"}[operation]
    if network:
        r["network"] = [{"host":"utas.test.ea.com", "path":"/ut/game/fc27/"+route, "status":200, "session_header_present":True}]
    return {"schema":1, "command_id":command_id, "operation":operation, "result":r,
            "freshness":{"observed_at":NOW.isoformat(), "network_at":NOW.isoformat() if network else None,
                         "request_count":int(network), "read_id":command_id, "source":"fixture"},
            "coverage":{"complete":False, "has_more":None, "account_capacity":None, "evidence_id":None},
            "timing":{"native_service_ms":12}}


class FakePage:
    def __init__(self):
        self.commands = []
        self.rows = []
        self.fail = False

    def attach(self, *args):
        return True

    def reconciled(self, *args):
        return True

    def execute(self, command):
        self.commands.append(command)
        return wire(command["id"], command["operation"], rows=self.rows, success=not self.fail)


class AdapterTests(Fixture, unittest.TestCase):
    def test_bulk_50_rows_paging_identity_freshness_coverage_and_balance(self):
        page = FakePage()
        page.rows = [project_auction({"tradeId":str(i), "startingBid":150, "currentBid":0, "buyNowPrice":10500,
                      "expires":300, "tradeState":"active", "bidState":"none",
                      "itemData":{"id":str(1000+i), "definitionId":123, "untradeable":False}}, KEY) for i in range(1, 51)]
        adapter = NativeAdapter(page, self.journal(), self.provider, scope=SCOPE, owner=OWNER, evidence_key=KEY, now=lambda: NOW, fixture=True)
        snap = adapter.watched(cid(70))
        self.assertEqual(len(snap.auctions), 50)
        self.assertEqual(len(page.commands), 1)
        self.assertEqual(snap.freshness.request_count, 1)
        self.assertFalse(snap.coverage.complete)
        self.assertIsNone(snap.coverage.account_capacity)
        self.assertEqual(adapter.balance(cid(71)).spendable, 50000)
        page.rows = page.rows[:21]
        adapter.search(cid(72), Search(page=2, max_bid=1000, min_buy=10500))
        self.assertEqual(page.commands[-1]["params"]["page"], 2)
        self.assertEqual(page.commands[-1]["params"]["max_bid"], 1000)
        page.rows[0].update(trade_state="closed", bid_state="highest")
        self.assertEqual(adapter.watched(cid(73)).auctions[0].state, State.PENDING)
        page.rows = []
        self.assertEqual(adapter.watched(cid(74)).auctions, ())
        page.fail = True
        with self.assertRaises(ValueError):
            adapter.watched(cid(75))

    def test_strict_result_schema_correlations_sanitization_and_cache_metadata(self):
        for mutate in (lambda v: v.update(command_id=cid(2)), lambda v: v["result"].update(cookie="PRIVATE"),
                       lambda v: v["freshness"].update(request_count=2), lambda v: v["result"].update(platform="ps5"),
                       lambda v: v["coverage"].update(complete=True), lambda v: v["timing"].update(native_service_ms=float("nan")),
                       lambda v: v["result"]["network"][0].update(path="/ut/game/fc27/trade/123/bid")):
            value = wire(cid(1), "watched")
            mutate(value)
            with self.assertRaises((ValueError, TypeError)):
                parse_response(value, command_id=cid(1), operation="watched")
        _, f, _ = parse_response(wire(cid(1), "watched", network=False), command_id=cid(1), operation="watched")
        self.assertFalse(f.fresh(NOW))

    def test_one_shot_bid_minimum_intent_first_unknown_and_no_duplicate_write(self):
        page, j = FakePage(), self.journal()
        adapter = NativeAdapter(page, j, self.provider, scope=SCOPE, owner=OWNER, evidence_key=KEY, now=lambda: NOW, fixture=True)
        i = intent()
        self.assertEqual(adapter.bid_once(i, status(), balance(), self.rules, observations=self.observations()).outcome, Outcome.ACKNOWLEDGED)
        self.assertEqual(page.commands[0]["operation"], "bid")
        self.assertEqual(page.commands[0]["params"]["amount"], 150)
        data = next(e["data"] for e in j.trace() if e["reason"] == "INTENT_DURABLE")
        self.assertEqual((data["samples"], data["target"], data["tax"], data["expected_profit"]), (5, 12000, 600, 11250))
        self.assertEqual([r["ask"] for r in data["comparables"]], [12000, 12250, 12500, 12750, 13000])
        self.assertEqual(hashlib.sha256(json.dumps(data["comparables"], sort_keys=True).encode()).hexdigest(), data["pricing_digest"])
        self.assertTrue(all(r["trade_id"].startswith("trade:") for r in data["comparables"]))
        with self.assertRaises(ValueError):
            adapter.bid_once(i, status(), balance(), self.rules, observations=self.observations())
        self.assertEqual(len(page.commands), 1)
        leading = replace(status(state=State.LEADING, current=150), freshness=fresh(800))
        adapter.reconcile(i.command_id, leading, balance(n=901))
        outbid = replace(leading, state=State.OUTBID)
        with self.assertRaises(ValueError):
            adapter.bid_once(intent(outbid, n=101, amount=250, b=balance(n=901)), outbid, balance(n=901), self.rules, observations=self.observations())
        page.fail = True
        result = adapter.bid_once(intent(outbid, n=102, amount=200, b=balance(n=901)), outbid, balance(n=901), self.rules, observations=self.observations())
        self.assertEqual(result.outcome, Outcome.UNKNOWN)
        with self.assertRaises(ValueError):
            adapter.bid_once(intent(outbid, n=103, amount=200, b=balance(n=901)), outbid, balance(n=901), self.rules, observations=self.observations())
        self.assertEqual(sum(c["operation"] == "bid" for c in page.commands), 2)

    def test_native_javascript_contracts_and_historical_persona_regression(self):
        self.assertEqual((ROOT/"browser/bidding-v1/persona.js").read_bytes(),
                         (ROOT/"experiments/market_discovery_followup_v1/browser/persona.js").read_bytes())
        run = subprocess.run(["node", "tests/bidding_v1_checks.cjs"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
        self.assertIn("PASS", run.stdout)

    def test_native_mode_rejects_offline_rules_and_unsupported_profit_caps(self):
        page, j = FakePage(), self.journal()
        adapter = NativeAdapter(page, j, self.provider, scope=SCOPE, owner=OWNER, evidence_key=KEY, now=lambda: NOW)
        with self.assertRaisesRegex(ValueError, "live_rules"):
            adapter.bid_once(intent(), status(), balance(), self.rules, observations=self.observations())
        with self.assertRaisesRegex(ValueError, "source"):
            adapter.balance(cid(40))
        adapter.fixture = True
        with self.assertRaisesRegex(ValueError, "profitable_cap"):
            adapter.bid_once(replace(intent(), cap=20000), status(), balance(), self.rules, observations=self.observations())
        with self.assertRaisesRegex(ValueError, "profitable_cap"):
            adapter.bid_once(intent(), status(), balance(), self.rules, observations=self.observations()[:4])
        self.assertFalse(any(c["operation"] == "bid" for c in page.commands))


if __name__ == "__main__":
    unittest.main(verbosity=2)
