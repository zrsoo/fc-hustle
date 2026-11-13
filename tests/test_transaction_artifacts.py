"""Report/review consistency, never a replacement for live transaction validation."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checkpoint import transaction_at_checkpoint as assess
from fc_access.transaction_report import CRITERIA




class ArtifactTests(unittest.TestCase):
    def test_current_checkpoint_matches_report_and_full_assessment(self):
        directory = ROOT / "docs/research/transaction"
        journal = directory / "live.json"
        record = json.loads(journal.read_text(encoding="utf-8"))
        verification = json.loads((directory / "verification.json").read_text(encoding="utf-8"))
        errors, facts = assess(record)
        self.assertEqual(verification["evidence_sha256"], hashlib.sha256(journal.read_bytes()).hexdigest())
        self.assertEqual(verification["criteria_errors"], {str(i): e for i, e in errors.items()})
        self.assertEqual(verification["facts"], facts)
        self.assertEqual(verification["status"], "PARTIAL/BLOCKED" if errors else "VERIFIED")
        report = (ROOT / "docs/research/purchase-to-list.md").read_text(encoding="utf-8")
        self.assertIn("**" + verification["status"] + "**", report)
        for i, description in enumerate(CRITERIA):
            self.assertIn(f"| {i} | {description} |", report)
            for error in errors.get(i, []):
                self.assertIn(error, report)
        if errors:
            self.assertEqual(record["status"], "PARTIAL/BLOCKED")
            self.assertTrue(record["recovery"])
            self.assertTrue(record["errors"])
            self.assertNotIn(7, errors, "failure must be honestly reported with recovery")
        for a in record["attempts"]:
            self.assertIn(a["method"], report)
            if a["result"]["error"]:
                self.assertIn(a["result"]["error"], report)
        for phrase in ("Preserve the journal", "source-level contracts", "Direct HTTP remains **UNVERIFIED**", "No second purchase", "127.0.0.1:8768", "3600 seconds"):
            self.assertIn(phrase, report)

    def test_review_hashes_match_actual_bounded_implementation(self):
        review = json.loads((ROOT / "docs/research/transaction/source-review.json").read_text(encoding="utf-8"))
        required = {"fc_access/transaction.py", "fc_access/transaction_checks.py", "fc_access/transaction_server.py",
                    "fc_access/transaction_report.py", "browser/transaction-bridge/manifest.json",
                    "browser/transaction-bridge/worker.js", "browser/transaction-bridge/page.js", "browser/transaction-bridge/read-page.js"}
        self.assertEqual(set(review["local_sha256"]), required)
        from js_contract import check_js
        check_js(self, 'transaction_bridge_checks.cjs')
        self.assertEqual(review["live_write_proof"], "UNVERIFIED_AT_SOURCE_REVIEW")
        self.assertEqual(review["upstream"]["revision"], "fa0fdde132715b2c09a4cff1e51736a1794d635e")

    def test_separate_bridge_permissions_and_existing_read_bridge_stays_read_only(self):
        manifest = json.loads((ROOT / "browser/transaction-bridge/manifest.json").read_text())
        self.assertEqual(manifest["host_permissions"], ["http://127.0.0.1:8768/*"])
        self.assertEqual(set(manifest["permissions"]), {"activeTab", "scripting", "alarms", "storage"})
        original = (ROOT / "browser/read-bridge/page.js").read_text()
        for forbidden in ("services.Item.bid(", "services.Item.move(", "services.Item.list("):
            self.assertNotIn(forbidden, original)
        self.assertIn('"search"', original)


if __name__ == "__main__":
    unittest.main()
