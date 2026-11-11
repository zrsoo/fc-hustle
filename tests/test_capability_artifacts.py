"""Retained task_03 artifact coverage, traceability and privacy checks (no live claims)."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.capabilities import assess
from fc_access.harness import EVIDENCE, METHODS, validate_result


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        cls.doc = (ROOT/"docs/research/confirmed-capabilities.md").read_text(encoding="utf-8")

    def test_criterion_0_replaceable_read_transports_commands_and_no_trading_loop(self):
        tree = ast.parse((ROOT/"fc_access/harness.py").read_text(encoding="utf-8"))
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        for name in ["Transport", "EdgeTransport", "DirectHTTPTransport"]:
            self.assertIn("read", {n.name for n in classes[name].body if isinstance(n, ast.FunctionDef)})
        for n in ast.walk(tree):
            if isinstance(n, ast.While): self.fail("Harness may not contain continuous loops")
        self.assertIn("python -m fc_access.harness compare", self.doc)
        self.assertIn("python -m fc_access.read_server", self.doc)
        for file in ["browser/read-bridge/page.js", "browser/read-bridge/worker.js"]:
            script = (ROOT/file).read_text()
            self.assertNotRegex(script, r"\.(?:bid|move|list|relistExpiredAuctions)\s*\(")
        manifest = json.loads((ROOT/"browser/read-bridge/manifest.json").read_text())
        self.assertEqual(manifest["host_permissions"], ["http://127.0.0.1:8767/*"])
        self.assertEqual(set(manifest["permissions"]), {"activeTab", "scripting", "alarms", "storage"})

    def test_criteria_1_2_every_attempt_timestamp_request_status_error_and_measured_comparison(self):
        errors, facts = assess(self.record)
        self.assertNotIn("invalid_or_sensitive_attempt", errors)
        self.assertNotIn("invalid_live_record", errors)
        self.assertIn(self.record["captured_at"], self.doc)
        for transport in ["edge", "direct_http"]:
            attempts = [a for a in self.record["attempts"] if a["transport"] == transport]
            self.assertEqual({a["operation"] for a in attempts}, set(METHODS))
            self.assertEqual(facts[transport]["attempts"], len(attempts))
        for a in self.record["attempts"]:
            self.assertIn(a["observed_at"], self.doc)
            self.assertIn(json.dumps(a["request"], sort_keys=True), self.doc)
            self.assertIn(str(a["elapsed_ms"]), self.doc)
            r = a["result"]
            if r["error"]: self.assertIn(r["error"], self.doc)
            else: self.assertIsNotNone(r["status"])
        self.assertIn("comparative authenticated latency remains unverified", self.doc.lower())

    def test_criteria_3_6_market_identity_and_platform_are_not_silently_conflated(self):
        for word in ["tradeId", "itemData.id", "resourceId", "definitionId", "assetId", "starting_bid", "current_bid", "buy_now_price", "expires", "market_average", "last_sale_price"]:
            self.assertIn(word, self.doc)
        self.assertIn("False isPC does not imply PlayStation", self.doc)
        self.assertIn("cross-platform experiments are unverified", self.doc.lower())
        self.assertIn("Missing fields stay null", self.doc)
        self.assertIn("one auction", self.doc)
        self.assertIn("physical card", self.doc)
        self.assertIn("card/version", self.doc)

    def test_criterion_4_two_page_attempts_order_lookahead_cache_limits_explicit(self):
        for name in ["edge", "direct_http"]:
            pages = {a["request"].get("page") for a in self.record["attempts"] if a["transport"] == name and a["operation"] == "search"}
            self.assertTrue({1, 2} <= pages)
        facts = assess(self.record)[1]
        for label, key in [("Ordering", "ordering"), ("Lookahead", "lookahead"), ("Two relevant pages", "two_nonempty_pages")]:
            self.assertIn(label + ": **" + facts["pagination"][key] + "**", self.doc)
        self.assertIn("Caching and invalidation", self.doc)
        self.assertIn("cache hit, TTL", self.doc)
        self.assertIn("failed request never proves no next page", self.doc)
        self.assertIn("clearTransferMarketCache", self.doc)

    def test_criterion_5_account_piles_distinct_and_evidence_is_sanitized(self):
        for op in ["coins", "club", "unassigned", "purchased", "transfer_list"]:
            self.assertTrue(any(a["operation"] == op for a in self.record["attempts"]))
        self.assertIn("ItemPile.PURCHASED", self.doc)
        self.assertIn("requestPurchasedItems", self.doc)
        self.assertIn("shared queue", self.doc)
        self.assertIn("cache age and a fresh uncached club GET remain UNVERIFIED", self.doc)
        self.assertIn("not proof of the entire club inventory", self.doc)
        for a in self.record["attempts"]:
            validate_result(a["result"])
        retained = json.dumps(self.record)
        self.assertNotIn("synthetic-private-canary", retained)
        for forbidden in ['"sid"', '"cookie"', '"token"', '"email"', '"personaId"', '"headers"', '"body"']:
            self.assertNotIn(forbidden, retained)
        self.assertNotRegex(retained, r"https?://[^\s\"]+\?")

    def test_artifacts_pin_reviewed_sources_and_original_observer_preserved(self):
        review = json.loads((ROOT/"docs/research/capabilities/source-review.json").read_text())
        for relative, digest in review["local_files"].items():
            self.assertEqual(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(), digest, relative)
        self.assertTrue(review["public_sources"])
        self.assertIn("not live proof", self.doc)
        self.assertEqual(hashlib.sha256((ROOT/"docs/research/browser-access/live.json").read_bytes()).hexdigest(), "78e97e8a2ebf018cedb24ace045fd7411c1f18c613120b4534d92e782331d894")
        self.assertIn('"version": "0.2.0"', (ROOT/"browser/observer/manifest.json").read_text())
        self.assertTrue((ROOT/"tests/validate_capabilities_live.py").exists())

    def test_native_field_and_purchased_queue_claims_have_primary_source_provenance(self):
        mappings = json.loads((ROOT/"docs/research/capabilities/native-item-mappings.json").read_text())
        item = next(v for v in mappings if v["url"].endswith("compiled_2.js"))
        self.assertEqual(item["sha256"], "2cc8aec08628ea78c361b16456c93d672e1e80219ed246af0ace61f1b1018f83")
        self.assertTrue(any("l.id=t.id,l.definitionId=t.resourceId" in s["source"] for s in item["snippets"]))
        native = json.loads((ROOT/"docs/research/capabilities/native-source-shapes.json").read_text())
        self.assertEqual(native["sha256"], "90c120d41798623f756f1732010db21fd3c849e695abfce4e968700fd84fb9a2")
        pile = " ".join(native["sections"]['["getUnassignedPile"]=function'])
        for text in ['ItemPile["PURCHASED"]', '/purchased/items', '["itemData"]']:
            self.assertIn(text, pile)
        self.assertIn("no downloaded code executed", native["method"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
