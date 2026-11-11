"""Task_07 negative evidence, privacy, reproduction and readiness checks."""
import copy
import contextlib
from datetime import datetime, timedelta, timezone
import json
import io
from pathlib import Path
import re
import shutil
import sys
import unittest
from unittest.mock import patch
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checkpoint import transaction_at_checkpoint
from final_audit import (REQUIRED, deliverables, evidence_assessment, load,
                         privacy_findings, readiness)
from fc_access import transaction_checks
from fc_access.readback import assess_listing, capture_listing, main as readback_main
from fc_access.transaction import fresh


class FinalAuditTests(unittest.TestCase):
    def setUp(self):
        self.journal = load("docs/research/transaction/live.json")

    def capture(self):
        attempt = next(a for a in self.journal["attempts"] if a["phase"] == "after_list")
        return {"source": "fc-acquired-listing-readback", "observed_at": attempt["at"],
                "result": copy.deepcopy(attempt["result"])}

    def assess(self, capture):
        return assess_listing(capture, self.journal, now=datetime.fromisoformat(capture["observed_at"]))

    def test_required_documents_harness_and_setup_are_present(self):
        self.assertIsNotNone(shutil.which("node"), "Node is required; skipped JavaScript checks cannot pass this audit")
        for name in REQUIRED:
            self.assertGreater((ROOT / name).stat().st_size, 50, name)
        self.assertTrue(all("__pycache__" not in p.parts for p in deliverables()))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for command in ("python -m unittest discover -s tests -p test_*.py",
                        "python tests/validate_final.py", "python tests/check_transaction_prerequisite.py",
                        "python -m fc_access.readback --output private-captures/listing.json"):
            self.assertIn(command, readme)
        self.assertIn("Do not replay", readme)
        self.assertIn("expired/sold/absent", readme)
        self.assertIn("secrets", readme)

    def test_all_final_report_and_setup_local_links_resolve(self):
        for name in ("README.md", "docs/research/final-report.md"):
            path = ROOT / name
            for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if link.startswith("https://"):
                    continue
                target = (path.parent / unquote(link.split("#")[0])).resolve()
                self.assertTrue(target.is_relative_to(ROOT), link)
                self.assertTrue(target.is_file(), link)

    def test_every_required_capability_has_supported_status_and_existing_evidence(self):
        assessment = evidence_assessment()
        self.assertFalse(assessment["browser_errors"])
        self.assertFalse(assessment["read_errors"])
        self.assertFalse(assessment["transaction_errors"])
        rows = {r["capability"]: r for r in assessment["capabilities"]}
        required = {"authenticated_session_configuration", "transfer_market_search", "exact_card_and_bin_filters",
                    "pagination_two_pages", "comparable_market_sample", "purchase", "purchase_verification",
                    "movement", "listing", "listing_verification", "status", "relist"}
        required.update("account_" + name for name in ("coins", "club", "unassigned", "purchased", "transfer_list"))
        self.assertTrue(required <= rows.keys())
        self.assertEqual(len(rows), len(assessment["capabilities"]))
        for row in rows.values():
            self.assertIn(row["status"], {"VERIFIED", "UNVERIFIED", "BLOCKED"})
            self.assertTrue((ROOT / row["evidence"]).is_file())
            self.assertTrue(row["detail"])
        for name in ("relist", "direct_http", "session_renewal", "exact_card_caps", "realized_tax_rounding",
                     "sold_settlement", "continuous_autonomous_repeat"):
            self.assertEqual(rows[name]["status"], "UNVERIFIED")
        self.assertEqual(rows["bulk_catalog_and_price_feed"]["status"], "BLOCKED")

    def test_every_claimed_mutation_links_independent_before_and_after_reads(self):
        mutations = evidence_assessment()["mutations"]
        self.assertEqual({m["operation"] for m in mutations}, {"buy", "move", "list"})
        for mutation in mutations:
            self.assertEqual(mutation["status"], "VERIFIED")
            def resolve(ref):
                filename, pointer = ref.split("#")
                value = load(filename)
                for part in pointer.strip("/").split("/"):
                    value = value[int(part)] if isinstance(value, list) else value[part]
                return value
            writes = [resolve(ref) for ref in mutation["write"]]
            before = [resolve(ref) for ref in mutation["before"]]
            after = [resolve(ref) for ref in mutation["after"]]
            self.assertEqual(len(writes), 1)
            self.assertTrue(before and after)
            self.assertTrue(all(a["at"] < writes[0]["at"] for a in before))
            self.assertTrue(all(a["at"] > writes[0]["at"] for a in after))
            self.assertTrue(all(a["operation"] not in {"buy", "move", "list", "relist"} for a in before + after))
            self.assertTrue(any(fresh(a, a["operation"]) for a in after))

    def test_missing_independent_readback_never_verifies_live_mutation(self):
        for phase, criterion in (("before_buy", 1), ("restart_reconciliation", 1), ("after_move", 2), ("after_list", 3)):
            record = copy.deepcopy(self.journal)
            record["attempts"] = [a for a in record["attempts"] if a["phase"] != phase]
            errors, facts = transaction_at_checkpoint(record)
            self.assertIn(criterion, errors, phase)
            self.assertNotEqual(facts["purchase"], "VERIFIED")
        record = copy.deepcopy(self.journal)
        for attempt in record["attempts"]:
            if attempt["phase"] in {"restart_reconciliation", "after_list"}:
                attempt["result"]["network"] = []
        self.assertTrue(transaction_at_checkpoint(record)[0])

    def test_checkpoint_replay_is_historical_and_current_freshness_is_preserved(self):
        class FarFuture(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2040, 1, 1, tzinfo=timezone.utc)
        with patch.object(transaction_checks, "datetime", FarFuture):
            self.assertTrue(transaction_checks.assess(self.journal)[0])
            self.assertFalse(transaction_at_checkpoint(self.journal)[0])
        for browser, purchase in ((False, False), (False, True), (True, False)):
            self.assertEqual(readiness(browser, purchase), {"verdict": "NO-GO", "objective_state": "PARTIAL/BLOCKED"})
        self.assertEqual(readiness(True, True)["verdict"], "CONDITIONAL GO")

    def test_privacy_scan_rejects_values_and_raw_ids_without_echoing_them(self):
        secret = "synthetic" + "A" * 40
        payloads = [json.dumps({field: secret}) for field in
                    ("cookie", "password", "access_token", "email", "personaId", "account_id")]
        payloads += [json.dumps({"item_id": "123456789012345"}),
                     json.dumps({"trade_id": "123456789012345"}),
                     "Bearer " + secret, "ghp_" + secret,
                     "someone" + "@" + "example.test"]
        for text in payloads:
            findings = privacy_findings("capture.json" if text.startswith("{") else "source.txt", text)
            self.assertTrue(findings)
            self.assertNotIn(secret, json.dumps(findings))
        self.assertFalse(privacy_findings("safe.json", json.dumps({"session_header_present": True,
            "evidence_key": "a" * 32, "item_id": "item:" + "a" * 24, "credits": 200})))
        self.assertTrue(privacy_findings("evidence.json", json.dumps({"cookie": "synthetic-private-canary"})))
        capture = self.capture()
        capture["result"]["unexpected_private_field"] = secret
        self.assertTrue(privacy_findings("bad.json", json.dumps(capture)))

    def test_readback_matches_original_item_version_trade_price_platform_and_active_state(self):
        capture = self.capture()
        self.assertEqual(self.assess(capture)["status"], "VERIFIED")
        mutations = [lambda r: r.update(platform="ps5"), lambda r: r.update(network=[]),
                     lambda r: r["auctions"][0].update(trade_state="expired", expires=-1),
                     lambda r: r["auctions"][0].update(buy_now_price=300),
                     lambda r: r["auctions"][0].update(trade_id="trade:" + "f" * 24),
                     lambda r: r["auctions"][0]["item"].update(definition_id=1),
                     lambda r: r["auctions"][0]["item"].update(item_id="item:" + "f" * 24),
                     lambda r: r.update(auctions=[])]
        # Limit each mutation to the acquired row so unrelated transfer items do not hide a defect.
        capture["result"]["auctions"] = [r for r in capture["result"]["auctions"]
            if r["item"]["item_id"] == self.journal["selection"]["item"]["item_id"]]
        for mutate in mutations:
            changed = copy.deepcopy(capture)
            mutate(changed["result"])
            self.assertEqual(self.assess(changed)["status"], "UNVERIFIED")
        stamp = datetime.fromisoformat(capture["observed_at"])
        for offset in (121, -1):
            result = assess_listing(capture, self.journal, now=stamp + timedelta(seconds=offset))
            self.assertIn("readback_stale_or_future", result["errors"])

    def test_readback_dispatches_one_read_and_preserves_journal(self):
        original = copy.deepcopy(self.journal)
        result = self.capture()["result"]
        class FakeTransport:
            def __init__(self):
                self.calls = []
            def read(inner, operation, params, key):
                inner.calls.append((operation, params, key))
                return result
        fake = FakeTransport()
        capture = capture_listing(self.journal, fake)
        self.assertEqual(fake.calls, [("transfer_list", {}, self.journal["evidence_key"])])
        self.assertEqual(self.journal, original)
        self.assertEqual(capture["result"], result)
        with patch.object(sys, "argv", ["readback", "--output", str(ROOT / "docs/research/transaction/live.json")]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                readback_main()
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(load("docs/research/transaction/live.json"), original)


if __name__ == "__main__":
    unittest.main()
