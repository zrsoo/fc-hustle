"""Independent offline acceptance checks for the 001c-01 audit, criteria 0..5.

No browser connection, live collector, network fetch or historical file writes.
Counterexamples mutate copies/injected bytes only. Historical results are read
at their checkpoints; an incomplete benchmark is not current human blockage.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checkpoint import transaction_at_checkpoint
from fc_access.capabilities import assess as assess_reads
from experiments.market_discovery_followup_v1.__main__ import assessment as assess_search
from experiments.market_discovery_live_v1.validate import validate as assess_benchmark
from validate_browser_live import assess as assess_browser_trace

DIRECTORY = "docs/research/001c/001c-01/"
DOCUMENT = "docs/research/001c-01-audit.md"
ACTORS = {"Bid Acquirer", "Bidder"}
ROW_IDS = (
    "search_filters", "pricing_cap", "opening_bid", "leading_hold", "bulk_watchlist",
    "queue_50", "outbid_rebid", "terminal_outcomes", "coins", "won_transfer_list",
    "extension_timing", "lifecycle_journal",
)
# Independent minimum content for each live obligation; labels alone cannot pass.
ROW_CONTENT = {
    "search_filters": ("maxBid", "minBuy", "1000", "10500", "paging", "recheck"),
    "pricing_cap": ("five", "exact-PC", "X=500", "floor", "caps", "down"),
    "opening_bid": ("minimum", "intent", "watched", "coin", "acknowledgement"),
    "leading_hold": ("HOLD", "zero", "fresh", "ledger"),
    "bulk_watchlist": ("requestWatchedItems", "coverage", "network", "Targets", "empty"),
    "queue_50": ("50", "5000", "DRAINING", "fixtures", "capacity"),
    "outbid_rebid": ("natural", "minimum", "cap", "STOP_COMPETING", "UNVERIFIED"),
    "terminal_outcomes": ("WON", "LOST", "UNKNOWN", "independent", "coverage"),
    "coins": ("spendable", "refund", "uncertain", "pre/post", "actual cost"),
    "won_transfer_list": ("win", "physical item", "cost", "destination", "reuse-only"),
    "extension_timing": ("expiry", "25", "whole-queue", "requests/refresh", "UNVERIFIED"),
    "lifecycle_journal": ("epoch", "append-only", "restart", "no blind", "CLI"),
}
READS = {
    "AGENTS.md", "objectives/001c-competitive-bidding-readiness.md",
    "objectives/002-two-actor-competitive-bidding.md", "docs/research/execution-architecture.md",
    "docs/research/obj002-handoff.md", "docs/research/001b-obj002-addendum.md",
    "fc_access/pricing.py", "fc_access/transaction.py", "fc_access/transaction_server.py",
    "browser/transaction-bridge/page.js", "browser/transaction-bridge/read-page.js",
    "browser/transaction-bridge/worker.js", "experiments/market_discovery/bridge_server.py",
    "experiments/market_discovery_followup_v1/server.py",
    "experiments/market_discovery_followup_v1/browser/persona.js",
    "experiments/market_discovery_followup_v1/browser/page.js",
    "experiments/market_discovery_followup_v1/browser/worker.js",
    "experiments/market_discovery_followup_v1/REPORT.md",
    "experiments/market_discovery_followup_v1/runs/20261112T062256Z/search.json",
    "experiments/market_discovery_live_v1/runs/20261112T064306Z/observations.json",
    "experiments/market_discovery_live_v1/runs/20261112T064306Z/REPORT.md",
    "docs/research/capabilities/verification.json", "docs/research/transaction/live.json",
    "docs/research/transaction/verification.json", "docs/research/capabilities/native-source-shapes.json",
    "tests/test_browser_access.py", "tests/test_market_discovery_followup_v1.py",
    "tests/test_market_pricing.py", "tests/test_transaction.py",
    "tests/test_transaction_bridge.py", "tests/test_execution_artifacts.py",
}
GATES = {
    "reviewed_versioned_adapter_and_fault_tests", "durable_intent_before_dispatch",
    "single_command_owner_and_account_epoch", "fresh_authenticated_fc27_pc_readbacks",
    "exact_trade_item_version_and_eligibility", "verified_native_caps_and_relevant_ticks",
    "five_fresh_independent_comparables_for_strategy", "spendable_reserve_and_exposure_ledger",
    "passive_aggregate_request_accounting", "independent_assessor_ready", "no_prior_unknown_intent",
}
STOPS = {
    "window_or_request_or_mutation_or_coin_budget_exhausted", "detached_or_wrong_tab_or_persona_or_account_scope",
    "auth_401_or_login_or_captcha_or_2fa_challenge", "restriction_or_access_denial",
    "rate_limit_429_or_retry_after", "server_5xx_or_timeout_or_unknown_write",
    "stale_or_conflicting_identity_or_incomplete_status", "missing_native_caps_ticks_or_comparables",
    "journal_failure_or_duplicate_intent_or_external_account_activity", "unavailable_candidate_or_no_eligible_opportunity",
}
ACCOUNTING = {
    "persistent_local_scope_and_stable_auction_item_command_ids", "utc_and_monotonic_times_process_epoch_actor_reason_codes",
    "fsync_or_transactional_intent_before_dispatch", "immutable_requested_acknowledged_independently_verified_events",
    "pricing_inputs_rejections_target_tax_X_and_cap", "fresh_before_after_watched_owned_coins_and_transfer_snapshots",
    "each_attempt_amount_and_gross_exposure_including_unknown", "held_refunded_spendable_actual_cost_separate_nullable",
    "network_route_count_status_freshness_bytes_and_component_latency", "expiry_before_after_and_coverage_metadata",
    "closing_unresolved_intents_holds_coins_owned_unsold_items_and_active_listings",
    "actual_sale_proceeds_and_tax_only_if_attributable_settlement", "sanitized_allowlist_no_auth_values",
    "checkpoint_budget_survives_restart_and_closing_read_only_continuation",
}
EXCLUSIONS = {
    "autonomous_actor_loops", "mass_enrollment", "fabricated_competition", "third_party_subscription_spending",
    "credential_export", "challenge_bypass", "repeat_completed_discovery_campaigns",
}


def raw(path):
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError("path_outside_workspace")
    return target.read_bytes()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def load(path):
    return json.loads(raw(path), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))


def artifact(name):
    return load(DIRECTORY + name + ".json")


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def stamp(value):
    parsed = datetime.fromisoformat(value)
    need(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0, "UTC timestamp required")
    return parsed


def preservation_defects(record, read=raw):
    errors = []
    for path, expected in record["sha256"].items():
        try:
            if digest(read(path)) != expected:
                errors.append(path)
        except (OSError, ValueError):
            errors.append(path)
    return errors


def check_baseline(baseline, read=raw):
    commands = {
        "regression": (["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], 1),
        "001b-precommit": (["{python}", "tests/validate_001b.py", "--precommit"], 0),
        "001b-historical-commit": (["{python}", "tests/validate_001b.py"], 1),
        "001-historical-final": (["{python}", "tests/validate_final.py"], 1),
        "followup-retained": (["{python}", "-m", "experiments.market_discovery_followup_v1", "validate", "--input",
                               "experiments/market_discovery_followup_v1/runs/20261112T062256Z/search.json"], 0),
        "partial-benchmark-retained": (["{python}", "-m", "experiments.market_discovery_live_v1.validate", "--run-dir",
                                        "experiments/market_discovery_live_v1/runs/20261112T064306Z"], 1),
    }
    need(len(baseline["checks"]) == len(commands), "missing/duplicate actual baseline command")
    need({c["id"] for c in baseline["checks"]} == set(commands), "baseline coverage")
    for row in baseline["checks"]:
        need((row["command"], row["exit_code"]) == commands[row["id"]], "command or pre-existing exit hidden")
        need(stamp(row["started_utc"]) <= stamp(row["ended_utc"]), "reversed baseline times")
        need(0 < row["duration_seconds"] < 120, "baseline duration")
        body = read(DIRECTORY + row["output"])
        need(digest(body) == row["output_sha256"], "actual output changed")
        text = body.decode("utf-8")
        if row["id"] == "regression":
            need("Ran 196 tests" in text and "FAILED (failures=1)" in text, "full baseline result")
            need(text.count("FAIL:") == 1 and "test_criterion_0_inspection_is_current_and_does_not_assume_cdp" in text,
                 "actual known failure missing")
            need("86400" in text and "line 112" in text, "aging failure cause missing")
        else:
            value = json.loads(text)
            if row["id"] == "partial-benchmark-retained":
                need(value["integrity_status"] == "PASS" and value["benchmark_completion"] == "BLOCKED",
                     "partial evidence mislabeled complete")
                need((value["completed_windows"], value["actual_EA_requests"]) == (1, 8), "partial counts")
            elif row["exit_code"] == 0:
                need(value["status"] == "PASS", "success output missing")
            else:
                need(value["status"] == "FAIL" and value["errors"], "historical gate failure hidden")
    need(baseline["new_EA_requests"] == baseline["account_mutations"] == 0, "not offline baseline")


def check_gaps(gaps):
    authority = raw(gaps["authority"]).decode("utf-8")
    section = authority.split("### Required live acceptance matrix")[1].split("## Work plan")[0]
    labels = [line.split("|")[1].strip() for line in section.splitlines() if line.startswith("| ")][2:]
    rows = gaps["rows"]
    need([r["id"] for r in rows] == list(ROW_IDS), "missing/duplicate live acceptance row")
    need([r["requirement"] for r in rows] == labels, "objective acceptance matrix not fully mapped")
    need(gaps["strategy_authority"] == "objectives/002-two-actor-competitive-bidding.md", "002 authority")
    need(gaps["current_live_status"] == "UNVERIFIED", "audit cannot grant live readiness")
    for row in rows:
        actors = set(row["actors"])
        required_actors = ACTORS if row["id"] in {"pricing_cap", "queue_50", "coins", "lifecycle_journal"} else (
            {"Bid Acquirer"} if row["id"] in {"search_filters", "opening_bid"} else {"Bidder"})
        need(actors == required_actors, "actor obligation dropped: " + row["id"])
        actions = set(row["dispositions"])
        need("PROVE" in actions and actions <= {"REUSE", "ADAPT", "IMPLEMENT", "PROVE"}, "gap dispositions")
        need(row["live_status"] == "UNVERIFIED" and row["new_live_evidence"] == [], "historical/source promotion")
        need(row["implementation_paths"] and all((ROOT / p).is_file() for p in row["implementation_paths"]), "missing source path")
        body = row["gap"] + " " + row["proof"]
        need(len(row["gap"]) > 60 and len(row["proof"]) > 60, "empty obligation")
        for term in ROW_CONTENT[row["id"]]:
            need(term.lower() in body.lower(), f"{row['id']}: missing {term}")
    need(set.union(*(set(r["dispositions"]) for r in rows)) == {"REUSE", "ADAPT", "IMPLEMENT", "PROVE"}, "four-way gap map")


def check_review(ledger, read=raw):
    rows = ledger["reads"]
    need(len(rows) == len(READS) and {r["path"] for r in rows} == READS, "required audit input omitted")
    for row in rows:
        need(digest(read(row["path"])) == row["sha256"], "read input changed: " + row["path"])
        need(len(row["finding"]) > 70, "no substantive read finding")
    need(ledger["sequence"] == ["inspect_entry_and_objectives", "inspect_implementations_and_retained_evidence",
         "run_offline_baselines", "inspect_current_pinned_public_source", "freeze_gap_map_and_bounded_plan",
         "author_independent_artifact_checks"], "audit before implementation sequence")
    need(ledger["new_EA_requests"] == ledger["new_account_mutations"] == 0, "audit expanded live scope")
    need(ledger["no_completed_discovery_replay"] is True, "completed discovery replay permitted")
    need(ledger["current_attachment"] == ledger["current_authentication"] == "NOT_CHECKED", "unobserved access claim")
    need(ledger["future_002_execution"] == "GATED_ON_001C", "002 prematurely released")


def check_source(source):
    retained = load("docs/research/transaction/source-review.json")["upstream"]
    need(source["revision"] == retained["revision"] and source["sha256"] == retained["sha256"], "source pin mismatch")
    need(source["url"] == retained["url"], "not inspected pinned file")
    need(source["revision_endpoint"] == "https://api.github.com/repos/liusihang/fc27-copilot/commits/main", "current ref lookup missing")
    need(source["line_count"] == 2157 and source["branch"] == "main", "source identity")
    need(source["executed_upstream_code"] is False and source["current_account_live_proof"] is False, "source promoted to live")
    stamp(source["checked_utc"])
    ranges = {"ordinary_bid": [1624, 1633], "bid_lookup": [1243, 1259], "watched": [1723, 1727],
              "status": [303, 321], "search": [1596, 1609], "rules": [1, 2157]}
    need(len(source["findings"]) == len(ranges), "source contracts missing")
    need({r["id"] for r in source["findings"]} == set(ranges), "source finding identity")
    for row in source["findings"]:
        need(row["lines"] == ranges[row["id"]], "unattributable source finding")
        need(re.fullmatch("[a-f0-9]{64}", row["span_sha256"]), "missing span hash")
        need(row["classification"] == ("UNVERIFIED" if row["id"] == "rules" else "SOURCE_CONFIRMED_ONLY"), "source/live category conflation")
    excerpts = {r["line"]: r["text"] for r in source["excerpts"]}
    need(set(excerpts) == {310, 1249, 1631, 1725}, "source anchor coverage")
    for line, snippet in {310: "['tradeState', 'bidState']", 1249: "criteria.maxBuy", 1631: "Item.bid(loaded.item, Number(params.bid))",
                          1725: "Item.requestWatchedItems()"}.items():
        need(snippet in excerpts[line], "source excerpt does not support finding")
    need(set(source["absent_symbols"]) >= {"maxBid", "priceRange", "getNextBid", "requestTradeStatus", "getPilesize"}, "rules/status inspection omitted")
    need(all(type(n) is int and n == 0 for n in source["absent_symbols"].values()), "unsupported rules claim")


def check_plan(plan):
    need(plan["phase"] == "AUDIT_ONLY" and plan["current_execution"] == {
        "EA_requests": 0, "account_mutations": 0, "browser_recovery": False}, "current task exceeded audit scope")
    run = plan["future_run"]
    need(run["status"] == "PLANNED_NOT_EXECUTED" and run["frozen_before_first_write"] is True, "not a prewrite plan")
    need(run["restart_or_recovery_resets_budgets"] is False, "budget reset on recovery")
    windows = run["windows"]
    need([w["id"] for w in windows] == ["R0", "R1", "R2", "E2E", "R3"], "finite named observation windows")
    for row in windows:
        for field in ("seconds", "max_native_requests", "max_mutations"):
            need(type(row[field]) is int and row[field] >= (0 if field == "max_mutations" else 1), "nonfinite/invalid window bound")
        need(len(row["purpose"]) > 50, "unscoped observation window")
        if row["id"] != "E2E":
            need(row["max_mutations"] == 0, "write outside E2E window")
    for field, aggregate, cap in [("seconds", "max_total_seconds", 2160),
                                  ("max_native_requests", "max_foreground_native_requests", 94)]:
        need(type(run[aggregate]) is int and sum(w[field] for w in windows) == run[aggregate] <= cap,
             "window/aggregate bound inconsistent")
    need(type(run["max_aggregate_EA_requests"]) is int and run["max_foreground_native_requests"] <= run["max_aggregate_EA_requests"] <= 120,
         "aggregate EA ceiling missing")
    need(run["count_service_fanout"] is True and run["background_traffic"] == "PASSIVELY_COUNT_OR_BLOCK_LIVE_WRITES", "network undercount")
    b = run["budgets"]
    for key in ("max_enrolled_auctions", "max_opening_bid_attempts", "max_rebid_attempts", "max_move_attempts", "max_listing_attempts"):
        need(type(b[key]) is int and b[key] == 1, "unbounded enrollment or mutation branch")
    total = sum(b[k] for k in ("max_opening_bid_attempts", "max_rebid_attempts", "max_move_attempts", "max_listing_attempts"))
    need(type(b["max_mutation_attempts"]) is int and b["max_mutation_attempts"] == total == sum(w["max_mutations"] for w in windows) == 4,
         "mutation count inconsistent")
    need(type(b["max_per_bid_coins"]) is int and 0 < b["max_per_bid_coins"] <= 500, "per-bid exposure missing")
    need(type(b["max_total_gross_bid_exposure_coins"]) is int and
         b["max_per_bid_coins"] * (b["max_opening_bid_attempts"] + b["max_rebid_attempts"]) <= b["max_total_gross_bid_exposure_coins"] <= 1000,
         "total attempted exposure inconsistent")
    need(type(b["max_simultaneous_liability_coins"]) is int and b["max_simultaneous_liability_coins"] == b["max_per_bid_coins"], "one-auction liability")
    need(b["reserve_new_entry_coins"] == 5000 and b["unknown_attempt_consumes_budget"] is True and
         b["refunds_replenish_test_budget"] is False, "accounting safety weakened")
    for key, expected in (("prewrite_gates", GATES), ("stop_conditions", STOPS), ("accounting_obligations", ACCOUNTING)):
        need(set(run[key]) >= expected, "missing " + key)
    for field, terms in {
        "stop_policy": ("Stop new writes", "UNKNOWN", "read-only", "Retry-After", "no catch-up", "blind"),
        "timing_policy": ("25-second", "whole-queue", "30-second", "local guard", "never"),
        "unobserved_policy": ("outbid", "UNVERIFIED", "no extra windows", "fabricated"),
    }.items():
        need(all(t in run[field] for t in terms), "incomplete " + field)
    need(all(t in b["bid_limit_rule"] for t in ("500", "verified", "spendable", "minimum legal", "reserve")), "bid economics incomplete")
    need(all(t in b["integration_fallback"] for t in ("INTEGRATION_ONLY", "same bounds", "no profitability claim", "never automatic")), "fallback weakens bounds")


def check_scope(plan):
    scope = plan["scope"]
    need(all(scope.get(k) is False for k in EXCLUSIONS), "forbidden implementation scope")
    need(set(scope["allowed_this_task"]) == {"repository_read", "public_source_inspection", "offline_tests", "new_audit_artifacts"}, "audit operation scope widened")
    need(set(scope["future_allowed_mutations"]) == {"ordinary_opening_bid", "conditional_minimum_rebid", "won_item_move", "won_item_list"}, "future mutations widened")
    need(set(scope["future_forbidden_mutations"]) >= {"buy_now", "cancel", "relist", "sold_cleanup", "watch_mass_enrollment"}, "forbidden mutations omitted")


class EntryAndBaselineTests(unittest.TestCase):
    def test_criterion_0_entry_matches_recorded_git_tree_and_preserves_user_file(self):
        entry, lock = artifact("entry"), artifact("preservation")
        self.assertEqual(entry["branch"], "main")
        self.assertEqual(entry["upstream"], "origin/main")
        self.assertEqual(entry["tracked_diff"], "")
        self.assertEqual(entry["initial_user_status"], ["?? AGENTS.md"])
        self.assertEqual(entry["status_porcelain"], ["?? AGENTS.md", "?? tests/record_001c01_audit.py"])
        self.assertEqual(entry["head"], lock["baseline_head"])
        tree = subprocess.check_output(["git", "ls-tree", "-r", entry["head"]], cwd=ROOT).decode()
        blobs = {line.split("\t", 1)[1]: line.split()[2] for line in tree.splitlines()}
        self.assertEqual(lock["git_blobs"], blobs)
        self.assertEqual(set(lock["sha256"]), set(blobs) | {"AGENTS.md"})
        self.assertFalse(preservation_defects(lock))
        self.assertEqual(entry["browser_attachment"], "NOT_CHECKED")
        self.assertEqual(entry["authentication"], "NOT_CHECKED")

    def test_criterion_0_all_historical_seals_and_followup_bytes_remain_unchanged(self):
        lock = artifact("preservation")
        for seal in ("docs/research/final/manifest.json", "docs/research/001b/preservation.json", "docs/research/001b/t7/manifest.json"):
            self.assertIn(seal, lock["historical_seals"])
        for path, expected in load("docs/research/001b/preservation.json")["static_sha256"].items():
            self.assertEqual(digest(raw(path)), expected, path)
        for path, expected in load("docs/research/001b/t7/manifest.json")["sha256"].items():
            self.assertEqual(digest(raw(path)), expected, path)

    def test_criterion_0_actual_baselines_include_unhidden_failures(self):
        check_baseline(artifact("baseline"))
        # Recovery crossed a date boundary. Prove the additional final-suite
        # failure is trace aging, using unchanged evidence and recorded clocks.
        final = artifact("verification")
        rows = {r["id"]: r for r in final["checks"]}
        self.assertEqual(set(rows), {"acceptance", "regression"})
        self.assertEqual((rows["acceptance"]["exit_code"], rows["acceptance"]["tests_run"]), (0, 18))
        self.assertEqual((rows["regression"]["exit_code"], rows["regression"]["tests_run"]), (1, 214))
        for row in rows.values():
            self.assertEqual(digest(raw(DIRECTORY + row["output"])), row["output_sha256"])
        output = raw(DIRECTORY + rows["regression"]["output"]).decode()
        self.assertIn("FAILED (failures=2)", output)
        self.assertEqual(output.count("FAIL:"), 2)
        self.assertIn("test_review_matches_executed_bridge_sources_and_retained_metadata", output)
        self.assertIn("stale_live_evidence", output)
        trace = load("docs/research/browser-access/live-v2.json")
        baseline_time = stamp(artifact("baseline")["checks"][0]["ended_utc"])
        self.assertFalse(assess_browser_trace(trace, now=baseline_time)[0])
        final_errors, _ = assess_browser_trace(trace, now=stamp(rows["regression"]["ended_utc"]))
        self.assertIn("stale_live_evidence", final_errors)
        self.assertIn("no_current_page_observations", final_errors)

    def test_criterion_0_changed_deleted_historical_evidence_is_rejected(self):
        lock = artifact("preservation")
        for path in ("docs/research/transaction/live.json", "browser/transaction-bridge/worker.js",
                     "docs/research/browser-access/inspection.json", "AGENTS.md"):
            self.assertIn(path, preservation_defects(lock, lambda p: raw(p) + b" " if p == path else raw(p)))
        def missing(path):
            if path == "docs/research/final/manifest.json":
                raise FileNotFoundError(path)
            return raw(path)
        self.assertIn("docs/research/final/manifest.json", preservation_defects(lock, missing))

    def test_criterion_0_baseline_failure_cannot_be_hidden_or_output_replaced(self):
        for mode in ("exit", "delete", "output"):
            bad = deepcopy(artifact("baseline"))
            if mode == "exit":
                bad["checks"][0]["exit_code"] = 0
            elif mode == "delete":
                del bad["checks"][0]
            else:
                bad["checks"][0]["output_sha256"] = digest(b"PASS")
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                check_baseline(bad)


class GapAndInspectionTests(unittest.TestCase):
    def test_criterion_1_exact_live_rows_both_actors_and_actionable_gap_map(self):
        check_gaps(artifact("gap-map"))

    def test_criterion_1_missing_row_actor_or_obligation_is_rejected(self):
        for index in range(12):
            bad = deepcopy(artifact("gap-map"))
            del bad["rows"][index]
            with self.subTest(row=index), self.assertRaises(AssertionError):
                check_gaps(bad)
        for actor in ACTORS:
            bad = deepcopy(artifact("gap-map"))
            for row in bad["rows"]:
                row["actors"] = [a for a in row["actors"] if a != actor]
            with self.subTest(actor=actor), self.assertRaises(AssertionError):
                check_gaps(bad)
        bad = deepcopy(artifact("gap-map"))
        bad["rows"][4]["proof"] = "HTTP 200 proves complete watchlist."
        with self.assertRaises(AssertionError):
            check_gaps(bad)

    def test_criterion_2_required_reads_hashes_and_no_completed_discovery_replay(self):
        check_review(artifact("review-ledger"))
        for path in READS:
            bad = deepcopy(artifact("review-ledger"))
            bad["reads"] = [r for r in bad["reads"] if r["path"] != path]
            with self.subTest(path=path), self.assertRaises(AssertionError):
                check_review(bad)

    def test_criterion_2_historical_transaction_and_native_reads_reassessed_independently(self):
        errors, facts = assess_reads(load("docs/research/capabilities/attempts.json"))
        self.assertFalse(errors, errors)
        self.assertEqual(facts["edge"]["authenticated_reads"], 14)
        self.assertEqual(facts["direct_http"]["authenticated_reads"], 0)
        journal = load("docs/research/transaction/live.json")
        errors, facts = transaction_at_checkpoint(journal)
        self.assertFalse(any(errors.values()), errors)
        self.assertEqual(facts["acquisition_readback"]["coin_debit"], 200)
        self.assertEqual(facts["listing_readback"]["buy_now_price"], 250)
        self.assertEqual(facts["listing_readback"]["physical_item"], facts["identity"]["physical_item"])
        self.assertEqual(facts["relist"], "UNVERIFIED")
        self.assertEqual(len([a for a in journal["attempts"] if a["operation"] == "buy"]), 1)
        self.assertFalse(assess_search(load("experiments/market_discovery_followup_v1/runs/20261112T062256Z/search.json")))

    def test_criterion_2_attachment_failure_budgets_and_partial_evidence_are_real(self):
        path = ROOT / "experiments/market_discovery_live_v1/runs/20261112T064306Z"
        result = assess_benchmark(path)
        self.assertEqual(result["integrity_status"], "PASS")
        self.assertEqual(result["benchmark_completion"], "BLOCKED")
        self.assertEqual(result["completed_windows"], 1)
        self.assertEqual(result["actual_EA_requests_by_strategy"], {"A": 8, "B": 0, "C": 0})
        record = load("experiments/market_discovery_live_v1/runs/20261112T064306Z/observations.json")
        self.assertEqual(record["stop_reason"], "bridge_not_attached")
        self.assertEqual(record["records"][-1]["result"]["network"], [])
        self.assertEqual(record["records"][-1]["result"]["error"], "bridge_not_attached")
        self.assertEqual({s: 24 - n for s, n in result["actual_EA_requests_by_strategy"].items()}, {"A": 16, "B": 24, "C": 24})

    def test_criterion_2_implementation_claims_match_source_without_research_replay(self):
        worker = raw("experiments/market_discovery_followup_v1/browser/worker.js").decode()
        persona = raw("experiments/market_discovery_followup_v1/browser/persona.js").decode()
        page = raw("experiments/market_discovery_followup_v1/browser/page.js").decode()
        queue = raw("experiments/market_discovery/bridge_server.py").decode()
        transaction = raw("fc_access/transaction.py").decode()
        self.assertIn('platform === "PC"', persona)
        self.assertIn('nativePC === "PC" && flag === true', persona)
        self.assertIn('min_buy:"minBuy"', page)
        self.assertNotIn("max_bid", page + worker)
        self.assertNotIn("onAlarm", worker)
        self.assertNotIn("onStartup", worker)
        self.assertIn('await badge("WAIT"', worker)
        self.assertIn("self.server.polling", queue)
        self.assertIn("unknown_or_expired_command", queue)
        self.assertIn("self.server.extension_origin", queue)
        self.assertIn("write_already_intended_reconciliation_required", transaction)
        self.assertIn("os.fsync", transaction)
        self.assertIn("DEFAULT_BANDS", raw("fc_access/pricing.py").decode())


class SourceAndPlanTests(unittest.TestCase):
    def test_criterion_3_current_pinned_source_findings_and_separate_live_classification(self):
        check_source(artifact("source-review"))
        self.assertLessEqual(stamp(artifact("baseline")["checks"][-1]["ended_utc"]), stamp(artifact("source-review")["checked_utc"]))

    def test_criterion_3_source_claims_cannot_be_promoted_or_rules_invented(self):
        for mode in ("live", "watched", "rules", "reference", "excerpt"):
            bad = deepcopy(artifact("source-review"))
            if mode == "live":
                bad["current_account_live_proof"] = True
            elif mode == "watched":
                bad["findings"][2]["classification"] = "LIVE_VERIFIED"
            elif mode == "rules":
                bad["findings"][-1]["classification"] = "SOURCE_CONFIRMED_ONLY"
            elif mode == "reference":
                bad["revision"] = "0" * 40
            else:
                bad["excerpts"][-1]["text"] = "getWatchlist exists"
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                check_source(bad)

    def test_criterion_4_finite_windows_coin_mutation_limits_stops_and_accounting(self):
        check_plan(artifact("validation-plan"))

    def test_criterion_4_every_gate_stop_and_accounting_obligation_is_required(self):
        for field in ("prewrite_gates", "stop_conditions", "accounting_obligations"):
            for value in artifact("validation-plan")["future_run"][field]:
                bad = deepcopy(artifact("validation-plan"))
                bad["future_run"][field].remove(value)
                with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                    check_plan(bad)

    def test_criterion_4_budget_increases_nonfinite_and_restart_reset_are_rejected(self):
        mutations = [
            ("max_per_bid_coins", 501), ("max_total_gross_bid_exposure_coins", 1001),
            ("max_total_gross_bid_exposure_coins", 500), ("max_mutation_attempts", 5),
            ("max_enrolled_auctions", 50), ("max_per_bid_coins", True),
            ("max_per_bid_coins", float("inf")), ("unknown_attempt_consumes_budget", False),
            ("refunds_replenish_test_budget", True),
        ]
        for key, value in mutations:
            bad = deepcopy(artifact("validation-plan"))
            bad["future_run"]["budgets"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                check_plan(bad)
        for field, value in [("restart_or_recovery_resets_budgets", True), ("max_total_seconds", None),
                             ("max_aggregate_EA_requests", 121), ("count_service_fanout", False)]:
            bad = deepcopy(artifact("validation-plan"))
            bad["future_run"][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                check_plan(bad)
        bad = deepcopy(artifact("validation-plan"))
        bad["future_run"]["windows"][0]["max_mutations"] = 1
        with self.assertRaises(AssertionError):
            check_plan(bad)

    def test_criterion_5_scope_excludes_all_forbidden_work_and_new_runtime_implementations(self):
        plan = artifact("validation-plan")
        check_scope(plan)
        self.assertFalse((ROOT / "fc_execution").exists(), "audit must not implement future actors")
        self.assertFalse((ROOT / "browser/execution-bridge").exists(), "audit must not implement future bridge")
        for flag in EXCLUSIONS:
            for mode in ("enable", "remove"):
                bad = deepcopy(plan)
                if mode == "enable":
                    bad["scope"][flag] = True
                else:
                    del bad["scope"][flag]
                with self.subTest(flag=flag, mode=mode), self.assertRaises(AssertionError):
                    check_scope(bad)
        bad = deepcopy(plan)
        bad["scope"]["allowed_this_task"].append("live_bid")
        with self.assertRaises(AssertionError):
            check_scope(bad)


class DocumentChecks(unittest.TestCase):
    def test_all_criteria_readable_report_has_resolvable_sources_and_no_missing_gap_rows(self):
        doc = raw(DOCUMENT).decode("utf-8")
        for row in artifact("gap-map")["rows"]:
            self.assertEqual(doc.count("| " + row["id"] + " —"), 1)
        for phrase in ("NOT_CHECKED", "196 tests", "pre-existing failure", "SOURCE_CONFIRMED_ONLY", "S1", "S2", "S3", "S4",
                       "A=16/B=24/C=24", "not a proven root cause", "1000 coins", "500 coins per bid", "four mutation attempts",
                       "2160", "autonomous actor loops", "mass enrollment", "fabricated competition", "third-party subscription spending"):
            self.assertIn(phrase, doc)
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", doc):
            if link.startswith("https://"):
                continue
            target = (ROOT / DOCUMENT).parent.joinpath(link).resolve()
            self.assertTrue(target.is_relative_to(ROOT) and target.is_file(), link)
        self.assertGreater(len(re.findall(r"\[[^\]]+\]\(([^)]+)\)", doc)), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
