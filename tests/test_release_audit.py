"""Independent acceptance/adversarial checks for task 001c-07, criteria 0-6.

No browser or EA operations. Publication is checked separately against real Git.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fc_access import release_audit_v1 as a
from build_release_documents import matrix, e2e


from fc_access.evidence import evidence_hashes

class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timeline, cls.ledgers = a.collect()
        cls.facts = a.derive(cls.timeline, cls.ledgers)
        cls.doc = a.load(a.OUT + "release.json")

    def changed(self, window="001c-06-resume-02", stage="watched-after-opening"):
        t = copy.deepcopy(self.timeline)
        target = next(row for row in t if row["window"] == window and row["stage"] == stage)
        return t, target

    def test_0_independent_real_capture_ledger_and_wire_audit(self):
        result = a.audit()
        self.assertEqual(result, a.load(a.OUT + "independent-result.json"))
        self.assertEqual(self.timeline, a.load(a.OUT + "commands.json"))
        self.assertEqual((self.facts["commands"], self.facts["bid_attempts"], self.facts["holds"]), (44, 2, 2))
        source = a.read("fc_access/release_audit_v1.py").decode()
        self.assertNotIn("from fc_access.e2e", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("urlopen", source)

    def test_0_false_leading_even_with_matching_native_projections_is_rejected(self):
        t, target = self.changed()
        for k in ("rows", "wire_rows"):
            target["result"][k][0]["bid_state"] = "outbid"
        with self.assertRaisesRegex(ValueError, "unsupported_leading_claim"):
            a.derive(t, self.ledgers)

    def test_0_missing_authoritative_readback_rejected(self):
        t, target = self.changed()
        for k in ("rows", "wire_rows"):
            target["result"][k] = []
        with self.assertRaisesRegex(ValueError, "missing_authoritative_rows"):
            a.derive(t, self.ledgers)
        # Acknowledgment alone does not supply a readback event either.
        ledgers = copy.deepcopy(self.ledgers)
        ledgers["001c-06-resume-02"]["events"] = [e for e in ledgers["001c-06-resume-02"]["events"] if e["reason"] != "INDEPENDENT_READBACK"]
        with self.assertRaisesRegex(ValueError, "missing_independent_readback_event"):
            a.derive(self.timeline, ledgers)

    def test_0_readback_must_follow_ack_and_match_physical_identity(self):
        t, target = self.changed()
        target["network"]["started_at"] = "2026-11-13T03:27:00Z"
        with self.assertRaisesRegex(ValueError, "pre_ack_readback"):
            a.derive(t, self.ledgers)
        t, target = self.changed()
        for k in ("rows", "wire_rows"):
            target["result"][k][0]["item_id"] = "item:" + "0" * 24
        with self.assertRaisesRegex(ValueError, "wrong_bid_identity"):
            a.derive(t, self.ledgers)

    def test_0_actual_wire_amount_and_balance_debit_required(self):
        t, target = self.changed(stage="opening-1")
        target["network"]["bid_amount"] = 850
        with self.assertRaisesRegex(ValueError, "actual_bid_body_not_proved"):
            a.derive(t, self.ledgers)
        t, target = self.changed(stage="balance-after-opening")
        target["result"]["credits"] = 16268
        with self.assertRaisesRegex(ValueError, "unsupported_debit_claim"):
            a.derive(t, self.ledgers)

    def test_0_duplicate_mutations_with_same_or_different_command_ids_rejected(self):
        bid = next(t for t in self.timeline if t["window"] == "001c-06-resume-02" and t["operation"] == "bid")
        for new_id in (False, True):
            t = copy.deepcopy(self.timeline)
            duplicate = copy.deepcopy(bid)
            if new_id:
                duplicate["command_id"] = "0" * 32
                t.pop(next(i for i, r in enumerate(t) if r["operation"] == "balance"))
            t.append(duplicate)
            with self.subTest(new_id=new_id), self.assertRaisesRegex(ValueError, "duplicate_mutation_or_command|duplicate_or_unaccounted_mutation"):
                a.validate_mutations(t)

    def test_0_native_network_and_persona_are_required_even_for_200(self):
        valid = next(t["result"] for t in self.timeline if t["operation"] == "watched")
        for mode in ("fixture", "auth", "platform", "fanout"):
            r = copy.deepcopy(valid)
            if mode == "fixture": r["network"] = []
            if mode == "auth": r["network"][0]["session_header_present"] = False
            if mode == "platform": r["persona"]["platform_value"] = "ps5"
            if mode == "fanout": r["network"] *= 50
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                a.network(r, "watched")

    def test_0_duplicate_delivery_events_rejected_even_with_single_command_row(self):
        def ledger(window):
            meta, commands, events = a.read_ledger(window)
            if window == "001c-06-resume-02":
                events.append(copy.deepcopy(next(e for e in events if e["reason"] == "DELIVERED")))
            return meta, commands, events
        with self.assertRaisesRegex(ValueError, "missing_or_duplicate_dispatch_event"):
            a.collect(ledger=ledger)

    def test_0_capture_must_match_separate_ledger(self):
        def ledger(window):
            meta, commands, events = a.read_ledger(window)
            if window == "001c-06-resume-02":
                result = json.loads(commands[0]["result"])
                result["success"] = False
                commands[0]["result"] = json.dumps(result)
            return meta, commands, events
        with self.assertRaisesRegex(ValueError, "ledger_capture_mismatch"):
            a.collect(ledger=ledger)

    def test_0_fixtures_and_historical_transaction_cannot_be_labelled_live(self):
        for path in ("experiments/watched_bulk_v1/fixtures/watched-50.json", "docs/research/transaction/live.json"):
            doc = copy.deepcopy(self.doc)
            op = next(r for r in doc["operations"] if r["id"] == "opening_bid")
            op["evidence"] = [path]
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "fixture_or_historical_labelled_live"):
                a.validate_claims(doc, self.facts)
        doc = copy.deepcopy(self.doc)
        doc["current_evidence_scope"] = "Current authenticated account state checked now"
        with self.assertRaisesRegex(ValueError, "historical_relabelled_current"):
            a.validate_claims(doc, self.facts)

    def test_0_missing_operation_proof_cannot_borrow_unrelated_live_read(self):
        doc = copy.deepcopy(self.doc)
        op = next(r for r in doc["operations"] if r["id"] == "opening_bid")
        op["independent_proof"] = [a.BASE + "001c-04/search-3.json"]
        with self.assertRaisesRegex(ValueError, "operation_proof_missing"):
            a.validate_claims(doc, self.facts)

    def test_0_lost_is_not_missing_or_fabricated_won(self):
        for mode in ("missing", "won"):
            t, target = self.changed("001c-06-resume-03", "status")
            for k in ("rows", "wire_rows"):
                if mode == "missing": target["result"][k] = []
                else: target["result"][k][0]["bid_state"] = "highest"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                a.derive(t, self.ledgers)

    def test_0_separate_post_outage_window_cannot_be_relabelled_in_window(self):
        t, target = self.changed("001c-06-resume-03", "watched")
        target["result"]["observed_at"] = "2026-11-13T03:29:00Z"
        with self.assertRaisesRegex(ValueError, "historical_terminal_relabelled_in_window"):
            a.derive(t, self.ledgers)

    def test_1_matrix_contains_each_contract_evidence_class_and_dependency(self):
        content = a.read("docs/research/001c-capability-matrix.md").decode("utf-8")
        self.assertEqual(content.replace("\r\n", "\n"), matrix(self.doc))
        self.assertEqual(len(self.doc["operations"]), 20)
        for op in self.doc["operations"]:
            self.assertEqual(content.count("| " + op["id"] + " |"), 1)
            for field in ("implementation", "source_contract", "scope", "dependency"):
                self.assertTrue(op[field], (op["id"], field))
        a.validate_claims(self.doc, self.facts)

    def test_2_report_matches_all_native_commands_results_timestamps_and_amounts(self):
        content = a.read("docs/research/001c-e2e-report.md").decode("utf-8")
        self.assertEqual(content.replace("\r\n", "\n"), e2e(self.doc, self.timeline, self.facts, a.load(a.OUT + "checks.json")))
        for t in self.timeline:
            self.assertIn(t["command_id"], content)
            self.assertIn(t["network"]["started_at"], content)
            self.assertIn(t["network"]["ended_at"], content)
            self.assertTrue(t["argv"])
        for phrase in ("16268", "15468", "1500", "700+800", "No WON", "1200", "UNVERIFIED", "expired outbid"):
            self.assertIn(phrase.lower(), content.lower())
        self.assertEqual(self.facts["paid_acquisition_cost"], 0)
        self.assertEqual(self.facts["new_owned_items"], [])
        self.assertEqual(self.facts["unsold_test_cards"], [])
        self.assertEqual(self.facts["unresolved_active_bids"], [])
        self.assertIsNone(self.facts["realized_profit"])

    def test_3_handoff_has_resolvable_contracts_measured_timings_and_integration_gates(self):
        content = a.read("docs/research/001c-architecture-handoff.md").decode("utf-8")
        for phrase in ("PageExecutor.attach/execute/reconciled", "RulesProvider", "allow_offline", "FULL",
                       "one bulk GET", "50", "25-second", "1+3k", "concurrency=1", "319.945", "14.081",
                       "343.700", "377.398", "58.326", "dirty-inbox", "/user/credits", "getIncrementAboveVal",
                       "UNKNOWN", "sticky", "600-second", "5000", "900 seconds", "40 reads", "two bid writes",
                       "four mutations", "intent", "no autonomous", "hundreds", "current account refresh"):
            self.assertIn(phrase.lower(), content.lower(), phrase)
        for relative in ("docs/research/001c-capability-matrix.md", "docs/research/001c-e2e-report.md", "docs/research/001c-architecture-handoff.md"):
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", a.read(relative).decode("utf-8")):
                if target.startswith("https://"): continue
                path = (a.ROOT / relative).parent.joinpath(target).resolve()
                self.assertTrue(path.is_relative_to(a.ROOT) and path.is_file(), (relative, target))

    def test_4_only_five_capability_classes_and_unwitnessed_events_remain_explicit(self):
        for identifier in a.CONDITIONAL:
            doc = copy.deepcopy(self.doc)
            r = next(r for r in doc["operations"] if r["id"] == identifier)
            self.assertEqual((r["classification"], r["live_annotation"]), ("UNVERIFIED", "live-UNVERIFIED"))
            for change in ("LIVE_VERIFIED", "OFFLINE_VALIDATED", "LIVE_UNVERIFIED"):
                r["classification"] = change
                with self.subTest(identifier=identifier, change=change), self.assertRaises(ValueError):
                    a.validate_claims(doc, self.facts)

    def test_4_fifty_row_fixture_cannot_prove_live_capacity_or_cycle(self):
        self.assertEqual(self.facts["reported_capacity"], 50)
        self.assertFalse(self.facts["live_50_completeness"])
        self.assertFalse(self.facts["live_25s_cycle"])
        doc = copy.deepcopy(self.doc)
        next(r for r in doc["operations"] if r["id"] == "bulk_completeness_50")["classification"] = "LIVE_VERIFIED"
        with self.assertRaises(ValueError): a.validate_claims(doc, self.facts)

    def test_5_decision_requires_prerequisites_and_precise_finite_continuation(self):
        self.assertEqual(self.doc["decision"], "CONDITIONAL GO")
        self.assertFalse(self.doc["actor_execution_authorized"])
        self.assertEqual(len(self.doc["critical_prerequisites"]), 4)
        expected = {"new_auctions_max": 1, "seconds_max": 900, "reads_max": 40, "bid_writes_max": 2,
                    "mutations_max": 4, "gross_coins_max": 2000, "individual_bid_max": 1000, "reserve": 5000, "automatic_execution": False}
        self.assertEqual(self.doc["continuation"], expected)
        for decision in ("GO", "FULL GO"):
            doc = copy.deepcopy(self.doc); doc["decision"] = decision
            with self.assertRaisesRegex(ValueError, "unsupported_release_decision"):
                a.validate_claims(doc, self.facts)
        entry = a.load(a.OUT + "entry.json")
        strategy = "objectives/002-two-actor-competitive-bidding.md"
        self.assertIn('two_search_minimum_valid_bin', a.read(strategy).decode())

    def test_6_exact_executed_test_results_outputs_hashes_and_known_failures_retained(self):
        checks = a.load(a.OUT + "checks.json")["checks"]
        self.assertEqual(len(checks), 20)
        self.assertEqual([c["exit_code"] for c in checks], [0] * 18 + [1, 1])
        for c in checks:
            raw = a.read(a.OUT + c["output"])
            self.assertEqual(a.sha(raw), c["output_sha256"])
            self.assertLessEqual(a.stamp(c["started_at"]), a.stamp(c["ended_at"]))
            self.assertEqual(c["command"][0], "{python}")
        discover = a.read(a.OUT + checks[-1]["output"]).decode()
        self.assertIn("Ran 361 tests", discover)
        self.assertIn("FAILED (failures=2)", discover)
        self.assertEqual(discover.count("FAIL:"), 2)
        self.assertIn("stale_live_evidence", discover)
        self.assertIn("test_criterion_0_inspection_is_current_and_does_not_assume_cdp", discover)
        original = json.loads(a.read(a.OUT + checks[-2]["output"]))
        self.assertEqual(original["status"], "UNRESOLVED")
        self.assertEqual([r["criterion"] for r in original["checks"] if r["status"] == "UNRESOLVED"], [1, 2])
        git_checks = a.load(a.OUT + "git-checks.json")["checks"]
        self.assertEqual([r["exit_code"] for r in git_checks], [2, 0])
        for r in git_checks:
            self.assertEqual(a.sha(a.read(a.OUT + r["output"])), r["output_sha256"])
        self.assertIn("trailing whitespace", a.read(a.OUT + git_checks[0]["output"]).decode())

    def test_6_historical_seals_and_every_preexisting_file_intact(self):
        self.assertEqual(a.preserve(), 645)
        for path in ("docs/research/final/manifest.json", "docs/research/001b/t7/manifest.json", "docs/research/001c/001c-06/report.json"):
            def reader(p):
                return a.read(p) + (b"changed" if p == path else b"")
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "preexisting_bytes_changed"):
                a.preserve(reader)

    def test_6_payload_manifest_checks_all_versioned_artifacts_and_no_secrets(self):
        m = a.load(a.OUT + "payload-manifest.json")
        self.assertGreater(len(m["files"]), 300)
        for path, digest in evidence_hashes(m["files"]).items():
            raw = a.read(path)
            self.assertEqual(a.sha(raw), digest, path)
            self.assertFalse(any(part in path for part in ("private-captures/", ".orchestrator/", "__pycache__")))
            self.assertFalse(a.mutable_artifact(path))
            if path.endswith(".json"):
                a.private_fields(json.loads(raw))
        source = a.read("fc_access/release_audit_v1.py").decode()
        self.assertNotIn("while True", source)
        self.assertFalse(a.mutable_artifact(a.BASE + "001c-05/edge-wallet-attached.txt"))
        self.assertTrue(a.mutable_artifact(a.BASE + "001c-05/live.sqlite-wal"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
