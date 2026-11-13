"""Offline evidence/report checks for task_05; no network or account dependency."""
import ast
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.harness import validate_result
from fc_access.market_replay import replay
from fc_access.pricing import DEFAULT_BANDS, Policy
from fc_access.transaction import fresh

DIRECTORY = ROOT / "docs/research/market"
REPORT = (ROOT / "docs/research/market-strategy.md").read_text(encoding="utf-8")


def load(name):
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


class MarketArtifactTests(unittest.TestCase):
    def test_current_native_capture_is_real_shaped_exact_and_network_fresh(self):
        capture = load("availability.json")
        self.assertEqual(capture["source"], "bounded-market-research")
        self.assertEqual(len(capture["attempts"]), 3)
        captured = datetime.fromisoformat(capture["captured_at"])
        completed = datetime.fromisoformat(capture["completed_at"])
        self.assertGreater(completed, captured)
        self.assertLess((completed-captured).total_seconds(), 180)
        self.assertIn(captured.date().isoformat(), REPORT)
        for attempt in capture["attempts"]:
            result = validate_result(attempt["result"])
            self.assertTrue(result["success"])
            self.assertEqual(result["platform"], "pc")
            self.assertEqual(result["status"], 200)
            self.assertEqual(attempt["operation"], "search")
            self.assertEqual(attempt["method"], "services.Item.searchTransferMarket(criteria, page)")
            self.assertEqual(attempt["fresh_network"], fresh(attempt, "search"))
            self.assertTrue(attempt["fresh_network"])
            self.assertTrue(any(n["path"] == "/ut/game/fc27/transfermarket" and n["session_header_present"] for n in result["network"]))
            self.assertTrue(all(r["item"]["definition_id"] == attempt["request"]["definition_id"] for r in result["auctions"]))
            self.assertTrue(all(r["trade_state"] == "active" for r in result["auctions"]))
            self.assertIn(str(attempt["elapsed_ms"]), REPORT)
            self.assertGreater(attempt["elapsed_ms"], 0)
        self.assertEqual([a["request"]["fresh"] for a in capture["attempts"]], [True, False, True])
        self.assertEqual([a["request"]["page"] for a in capture["attempts"]], [1, 2, 1])

    def test_report_prices_samples_overlap_and_optional_price_fields(self):
        attempts = load("availability.json")["attempts"]
        pages = [a["result"]["auctions"] for a in attempts]
        self.assertEqual([len(p) for p in pages], [21, 21, 10])
        ids = [{r["trade_id"] for r in p} for p in pages]
        self.assertEqual(len(ids[0] & ids[1]), 1)
        self.assertEqual(len(ids[0] | ids[1]), 41)
        for collection, expected, text in [(pages[0]+pages[1], (6100, 7000), "6100–7000"), (pages[2], (200, 4000), "200–4000")]:
            prices = [r["buy_now_price"] for r in collection]
            self.assertEqual((min(prices), max(prices)), expected)
            self.assertIn(text, REPORT)
        self.assertFalse(all(r["buy_now_price"] <= s["buy_now_price"] for r, s in zip(pages[0], pages[0][1:])))
        all_rows = sum(pages, [])
        self.assertEqual(len(all_rows), 52)
        self.assertTrue(all(r["item"]["market_average"] is None for r in all_rows))
        self.assertEqual(sum(r["item"]["last_sale_price"] == 0 for r in all_rows), 24)
        self.assertEqual(sum(r["item"]["last_sale_price"] > 0 for r in all_rows), 28)
        for text in ("all 52", "24 rows", "28 rows", "41 distinct auctions", "not a completed sale", "Zero means unavailable"):
            self.assertIn(text, REPORT)

    def test_public_source_access_gaps_are_retained_and_not_faked_bulk_success(self):
        public = load("availability.json")["public"]
        self.assertEqual({p["name"] for p in public}, {"manifest", "catalog", "history_ui", "history_label", "price_ranges", "history_provider"})
        for p in public:
            self.assertIsNotNone(datetime.fromisoformat(p["at"]).tzinfo)
            self.assertGreater(p["elapsed_ms"], 0)
            self.assertIn(p["url"], REPORT)
            if p["name"] == "history_provider":
                self.assertEqual(p["status"], 200)
                self.assertGreater(p["bytes"], 1000)
                self.assertRegex(p["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(p["markers"]["price history"])
            else:
                self.assertEqual(p["status"], 403)
                self.assertEqual(p["error"], "http_error")
                self.assertNotIn("json", p)
        review = load("web-review.json")
        self.assertEqual(len(review["sources"]), 5)
        for source in review["sources"]:
            if "raw.githubusercontent.com" in source["url"]:
                parts = source["url"].split("/")
                # Convert the pinned raw URL to its equivalent source citation.
                citation = "https://github.com/"+"/".join(parts[3:5])+"/blob/"+"/".join(parts[5:])
                self.assertIn(citation, REPORT)
            else:
                self.assertIn(source["url"], REPORT)
            self.assertTrue(source["status"])
        for phrase in ("No bulk blob was fetched", "PC data is not established by PS5", "UNVERIFIED for numeric backfill", "not market-price history"):
            self.assertIn(phrase, REPORT)

    def test_retained_offline_proof_recomputes_from_capture(self):
        proof = load("offline-proof.json")
        # JSON normalization accounts only for tuples vs lists, not values.
        recomputed = json.loads(json.dumps(replay()))
        self.assertEqual(proof, recomputed)
        self.assertEqual(proof["source_sha256"], hashlib.sha256((DIRECTORY / "availability.json").read_bytes()).hexdigest())
        self.assertEqual(proof["kind"], "OFFLINE_REPLAY_INDICATIVE_NOT_GUARANTEED")
        self.assertEqual([m["hypothetical_caps_only"]["target_sale_price"] for m in proof["markets"]], [6200, 150])
        self.assertEqual([m["hypothetical_caps_only"]["expected_profit"] for m in proof["markets"]], [-210, -57])
        self.assertEqual([m["hypothetical_caps_only"]["sample_count"] for m in proof["markets"]], [40, 6])
        for market in proof["markets"]:
            self.assertEqual(market["without_observed_caps"]["status"], "MISSING_CAPS")
            self.assertFalse(market["without_observed_caps"]["meets_threshold"])
            self.assertFalse(market["hypothetical_caps_only"]["meets_threshold"])
            for p in (str(market["key"]["definition_id"]), str(market["hypothetical_caps_only"]["target_sale_price"]), str(market["hypothetical_caps_only"]["expected_profit"])):
                self.assertIn(p, REPORT)

    def test_empirical_points_come_from_actual_capture_and_transaction_readback(self):
        capture = load("availability.json")
        low = capture["attempts"][2]["result"]["auctions"]
        self.assertEqual({r["buy_now_price"] for r in low}, {200, 250, 4000})
        self.assertEqual({r["starting_bid"] for r in low}, {150, 200, 3900})
        journal = json.loads((ROOT / "docs/research/transaction/live.json").read_text())
        listed = next(a for a in journal["attempts"] if a["phase"] == "after_list")
        self.assertTrue(fresh(listed, "transfer_list"))
        self.assertTrue(any(r["trade_state"] == "active" and r["starting_bid"] == 200 and r["buy_now_price"] == 250 for r in listed["result"]["auctions"]))
        self.assertEqual([(b.start, b.stop, b.step) for b in DEFAULT_BANDS],
                         [(150, 1000, 50), (1000, 10000, 100), (10000, 50000, 250), (50000, 100000, 500), (100000, 15000001, 1000)])
        for phrase in ("complete interval and minimal increment **UNVERIFIED**", "Realized tax debit", "remain **UNVERIFIED**", "not a completed sale with coin settlement", "hypothetical"):
            self.assertIn(phrase, REPORT)

    def test_strategy_has_actionable_timing_cache_and_prebuy_contract(self):
        defaults = asdict(Policy())
        self.assertEqual(defaults, {"min_samples": 5, "max_age": 120, "min_remaining": 30, "rules_max_age": 300})
        for phrase in ("Every 300 seconds", "every 90 seconds", "120 seconds", "300 seconds",
                       "600 seconds", "30–60 seconds", "global minimum 30 seconds", "Policy(min_remaining=60)",
                       "two independently observed", "max_buy=7000", "same serialized request budget",
                       "filter signature", "network read time", "Duplicate", "unchanged executable BIN",
                       "fresh explicit minimum/maximum", "Retry-After", "No cached decision"):
            self.assertIn(phrase.lower(), REPORT.lower())
        self.assertIn("expected_profit = target_sale_price - floor(target_sale_price * 0.05) - acquisition_price", REPORT)
        self.assertIn("X=700 passes and X=701 fails", REPORT)
        self.assertIn("at least five distinct comparables", REPORT)

    def test_all_local_report_links_and_commands_resolve(self):
        base = ROOT / "docs/research"
        for target in re.findall(r"\]\(([^)]+)\)", REPORT):
            if not target.startswith("https:"):
                self.assertTrue((base / target.split("#")[0]).resolve().is_file(), target)
        for command in ("python tests/test_market_pricing.py", "python tests/test_market_artifacts.py", "python -m fc_access.market_replay"):
            self.assertIn(command, REPORT)
        fixture = json.loads((ROOT / "tests/fixtures/market-pricing.json").read_text())
        self.assertIn("SYNTHETIC", fixture["provenance"])

    def test_proof_has_no_network_orders_or_continuous_runner(self):
        pricing = ast.parse((ROOT / "fc_access/pricing.py").read_text())
        imports = {node.module for node in ast.walk(pricing) if isinstance(node, ast.ImportFrom)}
        self.assertTrue({'dataclasses', 'datetime', 'fractions', 'statistics'} <= imports)
        self.assertFalse(imports & {'requests', 'urllib.request', 'socket', 'subprocess'})
        self.assertFalse(any(isinstance(n, (ast.Import, ast.While, ast.AsyncFor)) for n in ast.walk(pricing)))
        probe = ast.parse((ROOT / "fc_access/market_probe.py").read_text())
        reads = [n for n in ast.walk(probe) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "read" and isinstance(n.func.value, ast.Name) and n.func.value.id == "transport"]
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0].args[0].value, "search")
        for file in ("market_probe.py", "market_replay.py"):
            tree = ast.parse((ROOT / "fc_access" / file).read_text())
            self.assertFalse(any(isinstance(n, ast.While) for n in ast.walk(tree)))
            self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"bid", "buy", "list", "move", "run", "relist"} for n in ast.walk(tree)))
        for phrase in ("no production continuous bot", "never guaranteed sale prices", "never an executable order"):
            self.assertIn(phrase, REPORT)


if __name__ == "__main__":
    unittest.main()
