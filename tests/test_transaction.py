"""Synthetic safety/assessor tests. Fixtures stay in TemporaryDirectory, never live.json."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.harness import empty_result, project_auction, project_item, pseudonym
from fc_access.transaction import Experiment, command
from fc_access.transaction_checks import assess


def raw_item(identity="123", definition=90001):
    return {"id": identity, "definitionId": definition, "resourceId": definition, "untradeable": False,
            "preferredPosition": "ST", "rating": 61}


def raw_auction(identity="123", definition=90001, trade="222", state="active", expires=600):
    return {"tradeId": trade, "startingBid": 150, "currentBid": 0, "buyNowPrice": 200,
            "expires": expires, "tradeState": state, "bidState": "none", "itemData": raw_item(identity, definition)}


class SimulatedNative:
    """Fault-injecting state machine, explicitly NOT a live transaction adapter."""
    def __init__(self, fault=None, apply=True, expired=False):
        self.fault, self.apply, self.expired = fault, apply, expired
        self.bought = self.moved = self.listed = self.relisted = False
        self.calls = []

    def read(self, op, params, key):
        self.calls.append((op, copy.deepcopy(params)))
        r = empty_result("internal_error")
        r.update(success=True, error=None, status=200, platform="pc")
        if op in {"buy", "move", "list", "relist"}:
            if op != self.fault or self.apply:
                setattr(self, {"buy": "bought", "move": "moved", "list": "listed", "relist": "relisted"}[op], True)
            if op == self.fault:
                return empty_result("bridge_timeout")
            return r
        route = {"coins": "user/credits", "unassigned": "purchased/items", "transfer_list": "tradepile", "status": "tradepile", "search": "transfermarket"}[op]
        r["network"] = [{"host": "utas.mob.v1.prd.futc-ext.gcp.ea.com", "path": "/ut/game/fc27/" + route, "status": 200, "session_header_present": True}]
        if op == "coins":
            r["credits"] = 10000 - (200 if self.bought else 0)
        if op == "unassigned":
            r["items"] = [project_item(raw_item(), key)] if self.bought and not self.moved else []
        if op == "search":
            r["auctions"] = [project_auction(raw_auction(), key)]
        if op in {"transfer_list", "status"}:
            r["auctions"] = []
            if self.moved:
                a = raw_auction(trade="333" if self.listed else "0", state="active" if self.listed else "inactive", expires=3600 if self.listed else -1)
                if self.listed:
                    a.update(startingBid=200, buyNowPrice=250)
                r["auctions"].append(project_auction(a, key))
            if self.expired:
                e = raw_auction("456", 90002, "445" if self.relisted else "444", "active" if self.relisted else "expired", 3600 if self.relisted else -1)
                r["auctions"].append(project_auction(e, key))
        return r


class TransactionTests(unittest.TestCase):
    def run_fixture(self, transport=None):
        adapter = transport or SimulatedNative()
        with tempfile.TemporaryDirectory() as d:
            r = Experiment(adapter, Path(d) / "fixture.json").run()
        return r, adapter

    def test_complete_fixture_and_no_eligible_relist(self):
        r, adapter = self.run_fixture()
        self.assertEqual(assess(r)[0], {})
        self.assertEqual(r["status"], "VERIFIED")
        self.assertEqual(r["relist"], "UNVERIFIED")
        writes = [op for op, _ in adapter.calls if op in {"buy", "move", "list", "relist"}]
        self.assertEqual(writes, ["buy", "move", "list"])

    def test_near_expiry_broad_row_seeds_exact_version_search_before_selecting_auction(self):
        adapter = SimulatedNative()
        original = adapter.read
        searches = []
        def read(op, params, key):
            result = original(op, params, key)
            if op == "search":
                searches.append(params)
                if len(searches) == 1:
                    result["auctions"] = [project_auction(raw_auction("456", expires=44), key)]
            return result
        adapter.read = read
        record, _ = self.run_fixture(adapter)
        self.assertEqual(record["status"], "VERIFIED")
        self.assertEqual(assess(record)[0], {})
        broad = next(a for a in record["attempts"] if a["operation"] == "search" and a["phase"] == "preflight")
        self.assertNotEqual(broad["result"]["auctions"][0]["item"]["item_id"], record["selection"]["item"]["item_id"])
        self.assertEqual(len(searches), 2)
        self.assertEqual([op for op, _ in adapter.calls].count("buy"), 1)

    def test_eligible_expired_relist_requires_readback(self):
        r, adapter = self.run_fixture(SimulatedNative(expired=True))
        self.assertEqual(assess(r)[0], {})
        self.assertEqual(r["relist"], "VERIFIED")
        self.assertEqual([op for op, _ in adapter.calls].count("relist"), 1)
        rb = next(a for a in r["attempts"] if a["phase"] == "after_relist")
        rb["result"]["auctions"] = []
        self.assertIn(4, assess(r)[0])

    def test_every_ambiguous_write_reconciled_without_retry(self):
        for op in ("buy", "move", "list", "relist"):
            with self.subTest(op=op):
                r, adapter = self.run_fixture(SimulatedNative(fault=op, expired=op == "relist"))
                self.assertEqual(assess(r)[0], {})
                self.assertEqual([o for o, _ in adapter.calls].count(op), 1)
                failed = next(a for a in r["attempts"] if a["operation"] == op)
                self.assertEqual(failed["result"]["error"], "bridge_timeout")

    def test_unapplied_buy_timeout_stops_and_rerun_only_reconciles(self):
        adapter = SimulatedNative(fault="buy", apply=False)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            r = Experiment(adapter, p).run()
            self.assertEqual(r["status"], "PARTIAL/BLOCKED")
            self.assertFalse(any(o in {"move", "list", "relist"} for o, _ in adapter.calls))
            count = len(adapter.calls)
            Experiment(adapter, p).run()
            self.assertEqual([o for o, _ in adapter.calls[count:]], ["unassigned", "transfer_list", "coins", "status"])
            self.assertEqual([o for o, _ in adapter.calls].count("buy"), 1)

    def test_crash_between_intent_and_response_survives_restart(self):
        adapter = SimulatedNative()
        original = adapter.read
        def crash(op, params, key):
            if op == "buy":
                original(op, params, key)
                raise KeyboardInterrupt()
            return original(op, params, key)
        adapter.read = crash
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            with self.assertRaises(KeyboardInterrupt):
                Experiment(adapter, p).run()
            persisted = json.loads(p.read_text())
            self.assertIn("buy", persisted["intents"])
            self.assertFalse(any(a["operation"] == "buy" for a in persisted["attempts"]))
            adapter.read = original
            result = Experiment(adapter, p).run()
            self.assertEqual(result["status"], "PARTIAL/BLOCKED")
            self.assertEqual([o for o, _ in adapter.calls].count("buy"), 1)

    def test_cached_postpurchase_readback_resumes_only_remaining_stages(self):
        adapter = SimulatedNative()
        original = adapter.read
        stale = True
        def read(op, params, key):
            result = original(op, params, key)
            if stale and adapter.bought and op in {"unassigned", "transfer_list"}:
                result.update(status=304, network=[])
            return result
        adapter.read = read
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            failed = Experiment(adapter, p).run()
            self.assertEqual(failed["status"], "PARTIAL/BLOCKED")
            self.assertEqual(set(failed["intents"]), {"buy"})
            stale = False
            completed = Experiment(adapter, p).run()
            self.assertEqual(completed["status"], "VERIFIED")
            self.assertEqual(assess(completed)[0], {})
            self.assertEqual([o for o, _ in adapter.calls].count("buy"), 1)
            self.assertEqual([o for o, _ in adapter.calls].count("move"), 1)
            self.assertEqual([o for o, _ in adapter.calls].count("list"), 1)
            self.assertEqual(sum(a["result"]["status"] == 304 for a in completed["attempts"]), 2)

    def test_unapplied_move_and_listing_never_retried(self):
        for op in ("move", "list"):
            with self.subTest(op=op):
                r, adapter = self.run_fixture(SimulatedNative(fault=op, apply=False))
                self.assertEqual(r["status"], "PARTIAL/BLOCKED")
                self.assertEqual([o for o, _ in adapter.calls].count(op), 1)
                self.assertFalse(any(o == "relist" for o, _ in adapter.calls))

    def test_low_cost_exact_match_and_typed_write_bounds(self):
        r, _ = self.run_fixture()
        buy = next(a for a in r["attempts"] if a["operation"] == "buy")
        for patch in ({"buy_now_price": 501}, {"buy_now_price": True}, {"trade_id": "123"}, {"definition_id": 0}, {"extra": 1}):
            with self.assertRaises(ValueError):
                command("buy", buy["request"] | patch)
        listing = r["listing"]
        for patch in ({"duration": 7200}, {"starting_bid": 199}, {"buy_now_price": 1500}, {"buy_now_price": listing["starting_bid"]}):
            with self.assertRaises(ValueError):
                command("list", listing | patch)
        for op in ("loop", "eval", "place_bid", "relist_all"):
            with self.assertRaises(ValueError):
                command(op, {})

    def test_assessor_rejects_mutations_for_every_criterion(self):
        valid, _ = self.run_fixture()
        cases = [
            (0, lambda r: r["selection"]["item"].update(untradeable=True)),
            (0, lambda r: self.at(r, "search", "exact_match")["result"]["auctions"][0]["item"].update(definition_id=1234)),
            (1, lambda r: self.at(r, "coins", "after_buy")["result"].update(credits=9999)),
            (1, lambda r: self.at(r, "unassigned", "after_buy")["result"].update(items=[])),
            (1, lambda r: self.at(r, "unassigned", "before_buy")["result"].update(items=copy.deepcopy(self.at(r, "unassigned", "after_buy")["result"]["items"]))),
            (2, lambda r: self.at(r, "transfer_list", "after_move")["result"].update(auctions=[])),
            (3, lambda r: self.at(r, "transfer_list", "after_list")["result"]["auctions"][0].update(expires=45)),
            (3, lambda r: self.at(r, "transfer_list", "after_list")["result"]["auctions"][0].update(buy_now_price=800)),
            (3, lambda r: self.at(r, "transfer_list", "after_list")["result"]["auctions"][0].update(trade_id=r["selection"]["trade_id"])),
            (3, lambda r: self.at(r, "transfer_list", "after_list")["result"]["auctions"][0].update(trade_id=pseudonym(0, "trade", r["evidence_key"]))),
            (4, lambda r: self.at(r, "status", "status")["result"].update(network=[])),
            (4, lambda r: r.update(relist="VERIFIED")),
            (5, lambda r: r["attempts"].append(copy.deepcopy(self.at(r, "buy", "buy")))),
            (6, lambda r: r.pop("direct_probe")),
            (6, lambda r: r["transport"].update(selected="direct_http")),
            (7, lambda r: (r.update(status="VERIFIED"), self.at(r, "coins", "after_buy")["result"].update(credits=9999))),
        ]
        for criterion, mutate in cases:
            with self.subTest(criterion=criterion, mutation=cases.index((criterion, mutate))):
                r = copy.deepcopy(valid)
                mutate(r)
                self.assertIn(criterion, assess(r)[0])

    @staticmethod
    def at(r, op, phase):
        return next(a for a in r["attempts"] if a["operation"] == op and a["phase"] == phase)

    def test_no_http_ack_or_code_only_evidence_counts_as_transaction(self):
        with tempfile.TemporaryDirectory() as d:
            adapter = SimulatedNative()
            adapter.read = lambda *args: empty_result("bridge_not_attached")
            r = Experiment(adapter, Path(d) / "fixture.json").run()
        errors, summary = assess(r)
        self.assertEqual(set(errors), {0, 1, 2, 3, 4, 5})
        self.assertEqual(set(summary.values()), {"UNVERIFIED"})
        self.assertFalse(r["intents"])
        self.assertTrue(r["errors"])
        self.assertTrue(r["recovery"])


if __name__ == "__main__":
    unittest.main()
