"""T1 evidence and preregistration checks; no browser/provider/EA traffic.

Tests replay historical evidence at its own checkpoint and mutate protocol and
preservation inputs to prove rejection. They do not certify current attachment.
"""
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from checkpoint import transaction_at_checkpoint
from fc_access import pricing
from fc_access.capabilities import assess as assess_reads
from fc_access.harness import command as read_command

ARTIFACTS = ROOT / "docs/research/001b"
REQUIRED = {
    "docs/research/final-report.md",
    "docs/research/market-strategy.md",
    "docs/research/confirmed-capabilities.md",
    "docs/research/execution-architecture.md",
    "docs/research/obj002-handoff.md",
}
METRICS = {
    "unique_auctions_per_EA_request", "unique_versions_per_EA_request",
    "unique_auctions_per_wall_minute", "unique_versions_per_wall_minute",
    "duplicate_fraction", "conflict_fraction", "coverage_by_filter_page_version",
    "age_expiry_distribution", "errors_cache_empty_counts", "candidate_yield_by_X",
    "arrival_rate_per_hour", "qualifying_revalidation_false_positive_fraction",
    "diagnostic_revalidation_counts", "background_EA_requests",
}
HARD_STOPS = {
    "auth_401", "challenge_CAPTCHA", "EA_restriction", "unexpected_mutation",
    "credential_output", "identity_platform_schema_mismatch", "bridge_detached",
    "budget_overrun",
}
FORBIDDEN = {"buy", "bid", "move", "list", "relist", "cancel", "sold_cleanup"}
BOUNDARY_FLAGS = {
    "account_mutations", "production_bot", "objective_002_implementation",
    "credential_exports", "paid_subscriptions", "paid_account_registration",
    "access_control_bypasses", "unrelated_repository_cloning",
    "unreviewed_executable_installation", "per_trade_approval_policy_added",
    "portfolio_spend_policy_added",
}


from fc_access.evidence import evidence_hashes

def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def row_digest(rows):
    return digest(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())


def utc_stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timezone required")
    return stamp


def preservation_defects(lock, read_bytes):
    """Check bytes plus the retained append-only observer prefix independently."""
    errors = []
    for path, expected in evidence_hashes(lock["static_sha256"]).items():
        if digest(read_bytes(path)) != expected:
            errors.append(path)
    prefix = lock["observer_prefix"]
    trace = json.loads(read_bytes(prefix["path"]))
    rows = trace["observations"]
    if (trace["schema"] != prefix["schema"] or trace["source"] != prefix["source"]
            or len(rows) < prefix["count"]
            or row_digest(rows[:prefix["count"]]) != prefix["rows_sha256"]
            or utc_stamp(trace["received_at"]) < utc_stamp(prefix["received_at"])):
        errors.append("observer_prefix_changed")
    return errors


def protocol_defects(p):
    """Semantic artifact checks, grouped by the user's acceptance indices."""
    errors = {2: [], 3: []}

    def need(ok, reason, criterion=2):
        if not ok:
            errors[criterion].append(reason)

    try:
        need(p["status"] == "PREREGISTERED_NOT_RUN" and p["results"] is None
             and p["new_live_observations"] == 0
             and p["actual_start_utc"] is None and p["actual_end_utc"] is None,
             "no new outcomes may be claimed by T1")
        run = p["run_contract"]
        need(run["pin_protocol_sha256_before_first_observation"] is True
             and run["amendments_require_new_revision_and_run"] is True
             and run["historical_data_counts_as_live"] is False,
             "freeze before observing; do not reuse historical yield")
        need(run["current_attachment"] == run["current_authentication"] == "NOT_CHECKED"
             and run["preflight_budget_separate"] is True
             and run["preflight"] == ["attachment_only_check", "fresh_authenticated_fc27_pc_search_network_get"],
             "attachment and authenticated preflight are separate")
        need(run["output_root"] == "experiments/market_discovery/runs/<run_id>/",
             "new captures must not overwrite prior evidence")
        market, timing, budget = p["market"], p["timing"], p["budget"]
        need(market["game"] == "fc27" and market["platform"] == "pc"
             and market["watchlist"] == [233731, 278230]
             and set(market["identity"]) == {"game", "platform", "definition_id", "trade_id", "item_id"},
             "exact market and distinct physical/auction identities")
        order = timing["order"]
        counts = Counter(order)
        need(len(order) == 9 and counts == {"A": 3, "B": 3, "C": 3}
             and all(a != b for a, b in zip(order, order[1:]))
             and all(set(order[i:i + 3]) == {"A", "B", "C"} for i in range(0, 9, 3))
             and all(set(order[i::3]) == {"A", "B", "C"} for i in range(3)),
             "balanced alternating blocks and positions")
        need(order == ["A", "B", "C", "B", "C", "A", "C", "A", "B"], "frozen window order")
        need(timing["window_seconds"] == 300 and len(order) * timing["window_seconds"] >= 1800,
             "bounded observation period at least thirty minutes")
        offsets = timing["slot_offsets_seconds"]
        need(offsets == list(range(0, 211, 30))
             and timing["minimum_submission_gap_seconds"] == 30
             and timing["max_in_flight"] == 1
             and timing["command_deadline_seconds"] == 60
             and timing["native_timeout_seconds"] == 15
             and offsets[-1] + timing["command_deadline_seconds"] <= timing["window_seconds"],
             "serialized pacing and completion allowance")
        need(timing["clock"] == "timezone_aware_UTC" and timing["elapsed_clock"] == "monotonic",
             "UTC records and elapsed deadlines")
        need(timing["skip_missed_slots"] is True and timing["catch_up"] is False
             and timing["carry_unused_budget"] is False and timing["late_read_counts_in_next_window"] is False,
             "no catch-up or carryover bias")
        need(budget["unit"] == "actual_foreground_EA_network_requests"
             and budget["per_window"] == len(offsets) == 8
             and budget["discovery_slots"] == 6 and budget["revalidation_slots"] == 2
             and budget["total_maximum"] == len(order) * len(offsets) == 72
             and all(counts[s] * budget["per_window"] == budget["per_strategy_maximum"] == 24 for s in counts),
             "equal EA budgets including reserved revalidation")
        for flag in ("errors_and_safe_retries_consume_budget", "native_side_effects_consume_budget",
                     "background_counted_separately", "complete_matched_blocks_only"):
            need(budget[flag] is True, flag)
        need(budget["local_polls_consume_EA_budget"] is False
             and budget["cache_only_counts_as_fresh"] is False
             and budget["unequal_actual_budgets"] == "PARTIAL_DESCRIPTIVE_ONLY"
             and budget["missing_background_measurement"] == "CONFOUNDED"
             and budget["background_max_rate_difference_fraction"] == 0.25,
             "actual requests and background confounding")
        pair = p["search_pair"]
        need(pair == {"operation": "search", "pages": [1, 2], "count": 21, "fresh": [True, False],
                      "same_criteria": True, "reset_between_pages": False, "deduplicate_lookahead": True,
                      "bin_order_assumed": False, "exhaustive_coverage_assumed": False},
             "native page/cache/lookahead semantics")
        strategies = p["strategies"]
        need(set(strategies) == {"A", "B", "C"}, "three strategies")
        for name, strategy in strategies.items():
            need(len(strategy["pairs"]) * len(pair["pages"]) == budget["discovery_slots"], name + " read count")
            for criteria in strategy["pairs"]:
                need(not set(criteria) & {"nation", "rarity", "position", "platform"}, "unverified filter")
                resolved = dict(criteria)
                if isinstance(resolved.get("definition_id"), str):
                    need(name == "C" and resolved["definition_id"] in {"rank_1", "rank_2"}, "bounded adaptive selector")
                    resolved["definition_id"] = market["watchlist"][int(resolved["definition_id"][-1]) - 1]
                for page, fresh in zip(pair["pages"], pair["fresh"]):
                    read_command("search", resolved | {"page": page, "fresh": fresh, "count": pair["count"]})
        need(all("definition_id" in c for c in strategies["A"]["pairs"]), "A exact versions")
        need(all("definition_id" not in c and ("club" in c or "league" in c) for c in strategies["B"]["pairs"]), "B broad validated filters")
        need(sum("definition_id" in c for c in strategies["C"]["pairs"]) == 2
             and "league" in strategies["C"]["pairs"][0], "C exploration plus targets")
        hybrid = strategies["C"]
        need(hybrid["rank_scope"] == "preceding_completed_block_only"
             and hybrid["initial_fallback"] == market["watchlist"]
             and hybrid["valid_external_rank"] == "exact_pc_indicative_ask_ascending_then_definition_id"
             and hybrid["native_fallback_rank"] == "fresh_distinct_auction_count_descending_then_definition_id",
             "adaptive ranking cannot inspect current-window outcomes")
        provider = p["provider"]
        need(provider == {"same_snapshot_for_all_strategies_per_block": True,
                          "retrieval_outside_EA_windows": True, "max_age_seconds": 600,
                          "missing_feed": "UNAVAILABLE", "cross_platform_substitution": False,
                          "unavailable_feed_counts_as_working": False}, "equal external data availability")
        reval = p["revalidation"]
        need(reval["slots"] == [6, 7] and reval["operation"] == "search"
             and reval["pages"] == [1, 2] and reval["fresh"] == [True, False]
             and reval["selection"] == "highest_modeled_profit_at_X_100_then_trade_id_lexical"
             and reval["no_evaluable_candidate"] == "lowest_positive_BIN_then_trade_id_lexical_DIAGNOSTIC_ONLY"
             and reval["no_valid_rows"] == "UNUSED" and reval["diagnostic_counts_as_opportunity"] is False,
             "bounded deterministic read-only revalidation selection")
        need(set(reval["checks"]) == {"exact_game_platform_version_trade_item", "unchanged_BIN",
             "active_and_age_decayed_expiry", "fresh_network_comparables", "verified_fresh_caps_and_relevant_ticks",
             "recomputed_profit_at_X"}, "independent candidate revalidation")
        price = p["pricing"]
        need(price["source"] == "fc_access/pricing.py"
             and price["formula"] == "target_sale_price - target_sale_price // 20 - acquisition_price"
             and price["threshold_operator"] == ">=" and price["X_scenarios"] == [100, 250, 500, 1000]
             and set(price["exclude_candidate"]) == {"trade_id", "item_id"}
             and price["minimum_comparables"] == 5, "locked P0 arithmetic and independent comparables")
        need([price[k] for k in ("sample_max_age_seconds", "candidate_max_age_seconds", "rules_max_age_seconds",
                                "remaining_lifetime_strictly_greater_seconds")] == [120, 30, 300, 60]
             and price["verified_caps_and_relevant_ticks_required"] is True
             and price["missing_rules_executable_yield"] is None
             and price["hypothetical_rules_label"] == "SIMULATED_MODELED"
             and price["actual_sale_claim_from_ask"] is False, "freshness, legal rules and honest yield")
        need(set(p["record_fields"]) >= {"run_id", "protocol_sha256", "block", "window", "strategy", "slot",
             "command_id", "criteria", "page", "fresh", "game", "platform", "submitted_utc", "completed_utc",
             "elapsed_ms", "http_status", "native_status", "error_code", "returned_rows", "visible_rows",
             "cache_invalidated", "network_fresh", "network_at_utc", "expires", "definition_id", "item_id", "trade_id"},
             "replayable per-request observations")
        metrics = p["metrics"]
        need(set(metrics["required"]) >= METRICS
             and metrics["arrival_rate"] == "3600 * distinct_first_qualified_auctions / observed_strategy_seconds"
             and metrics["false_positive_fraction"] == "failed_qualifying_revalidations / completed_qualifying_revalidations"
             and metrics["zero_revalidation_denominator"] is None
             and metrics["no_run_metrics"] is None and metrics["unknown_prerequisites_yield"] is None
             and metrics["dedup_scope"] == "per_strategy_and_overall_with_cross_window_overlap",
             "metrics denominators, deduplication and unobserved values")
        latency = p["latency"]
        need(latency["alternative_status"] == "PROPOSED_UNVALIDATED"
             and latency["same_EA_budget_and_pacing"] is True
             and latency["missing_component"] is None
             and latency["native_service_is_EA_server_latency"] is False
             and latency["subtract_assumed_alarm_delay"] is False
             and latency["median_requires_sample_count"] is True
             and latency["p95_min_samples"] == 20 and latency["p95_method"] == "nearest_rank_ceil_0.95_n"
             and set(latency["components"]) >= {"queue_delivery", "native_service", "result_return",
                 "python_compute", "time_to_first_result", "search_evaluate_fresh_revalidate_prepared_intent"}
             and set(latency["timestamps"]) >= {"scheduled", "submitted", "delivered", "native_start", "native_end",
                 "result_received", "evaluated", "revalidation_complete", "intent_prepared"},
             "latency decomposition and limited quantiles")
        stop = p["stop"]
        need(set(stop["hard"]) >= HARD_STOPS and set(stop["suspend"]) == {"rate_limit_429", "server_5xx", "timeout"}
             and stop["backoff_seconds"] == [30, 60, 120, 240, 300]
             and stop["honor_retry_after_even_above_cap"] is True
             and stop["retry_outside_budget"] is False
             and stop["third_party_403"] == "DISABLE_SOURCE_UNTIL_LEGITIMATE_ACCESS"
             and stop["insufficient_window_time"] == "PARTIAL"
             and stop["normal_end_after_windows"] == len(order)
             and stop["rate_threshold_probing"] is False, "bounded stop/backoff conditions")
        boundary = p["boundary"]
        for flag in BOUNDARY_FLAGS:
            need(boundary[flag] is False, "forbidden: " + flag, 3)
        need(boundary["allowed_operations"] == ["search"] and boundary["intent_mode"] == "DRY_RUN_ONLY"
             and set(boundary["forbidden_operations"]) >= FORBIDDEN
             and boundary["retention"] == "allowlisted_fields_and_per_run_namespaced_pseudonyms_only",
             "read-only and privacy boundary", 3)
    except (KeyError, TypeError, ValueError, IndexError) as error:
        # Malformed contracts must fail closed, not skip acceptance checks.
        errors[2].append("invalid protocol: " + type(error).__name__)
        errors[3].append("cannot establish complete boundary")
    return {i: reasons for i, reasons in errors.items() if reasons}


class ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = load("docs/research/001b/protocol.json")
        cls.ledger = load("docs/research/001b/review-ledger.json")
        cls.lock = load("docs/research/001b/preservation.json")
        cls.scope = (ROOT / "docs/research/001b-scope.md").read_text(encoding="utf-8")

    def test_criterion_0_five_required_reads_completed_before_protocol(self):
        reads = self.ledger["required_reads"]
        self.assertEqual(len(reads), 5)
        self.assertEqual({r["path"] for r in reads}, REQUIRED)
        for row in reads:
            self.assertEqual(digest((ROOT / row["path"]).read_bytes()), row["sha256"])
            self.assertGreater(len(row["finding"]), 100)
        self.assertEqual(self.ledger["sequence"], ["read_all_five_documents",
                         "inspect_existing_contracts_and_evidence", "author_T1_scope_protocol_and_tests"])
        reviewed = utc_stamp(self.ledger["review_completed_at_utc"])
        self.assertLessEqual(reviewed, utc_stamp(self.protocol["frozen_at_utc"]))
        self.assertLessEqual(utc_stamp(self.protocol["frozen_at_utc"]), datetime.now(timezone.utc))
        for phrase in ("14 authenticated", "zero", "-210/-57", "S1-S6", "30-second"):
            self.assertIn(phrase, json.dumps(reads))

    def test_criterion_0_existing_models_commands_and_native_samples(self):
        for symbol in ("MarketKey", "Observation", "Band", "Rules", "Policy", "Estimate", "evaluate", "profit"):
            self.assertTrue(hasattr(pricing, symbol), symbol)
            self.assertIn("`" + symbol + "`", self.scope)
        samples = load("docs/research/market/availability.json")["attempts"]
        self.assertEqual(len(samples), 3)
        self.assertEqual([a["request"]["page"] for a in samples], [1, 2, 1])
        self.assertEqual([a["request"]["definition_id"] for a in samples], [233731, 233731, 278230])
        self.assertEqual([len(a["result"]["auctions"]) for a in samples], [21, 21, 10])
        both_pages = [r for a in samples[:2] for r in a["result"]["auctions"]]
        self.assertEqual(len({r["trade_id"] for r in both_pages}), 41)
        errors, facts = assess_reads(load("docs/research/capabilities/attempts.json"))
        self.assertFalse(errors, errors)
        self.assertEqual(facts["edge"]["authenticated_reads"], 14)
        self.assertEqual(facts["direct_http"]["authenticated_reads"], 0)
        self.assertEqual(facts["filters"], {"club": "VERIFIED", "league": "VERIFIED",
                                         "nation": "UNVERIFIED", "rarity": "UNVERIFIED", "position": "UNVERIFIED"})

    def test_criteria_0_1_purchase_proof_replays_and_rejects_missing_debit_or_identity(self):
        journal = load("docs/research/transaction/live.json")
        errors, facts = transaction_at_checkpoint(journal)
        self.assertFalse(any(errors.values()), errors)
        self.assertEqual({k: facts[k] for k in ("purchase", "movement", "listing", "status", "relist")},
                         {"purchase": "VERIFIED", "movement": "VERIFIED", "listing": "VERIFIED",
                          "status": "VERIFIED", "relist": "UNVERIFIED"})
        self.assertEqual(facts["identity"]["definition_id"], 278230)
        self.assertEqual(facts["acquisition_readback"]["coin_debit"], 200)
        listing = facts["listing_readback"]
        self.assertEqual([listing[k] for k in ("starting_bid", "buy_now_price", "requested_duration",
                                              "observed_seconds_remaining")], [200, 250, 3600, 3570])
        self.assertEqual(listing["physical_item"], facts["identity"]["physical_item"])
        self.assertNotEqual(listing["trade_id"], facts["identity"]["purchase_trade"])
        for phase, op, change in [("restart_reconciliation", "coins", "debit"), ("after_list", "transfer_list", "item")]:
            bad = copy.deepcopy(journal)
            attempt = next(a for a in bad["attempts"] if a["phase"] == phase and a["operation"] == op)
            if change == "debit":
                attempt["result"]["credits"] += 1
            else:
                for auction in attempt["result"]["auctions"]:
                    if auction["item"]["item_id"] == facts["identity"]["physical_item"]:
                        auction["item"]["item_id"] = "item:" + "f" * 24
            failures, _ = transaction_at_checkpoint(bad)
            self.assertTrue(any(failures.values()), change)

    def test_criterion_1_immutable_files_match_historical_manifest_and_entry_lock(self):
        manifest = load("docs/research/final/manifest.json")
        trace = "docs/research/browser-access/live-v2.json"
        hashes = self.lock["static_sha256"]
        self.assertTrue(set(manifest["sha256"]) - {trace} <= set(hashes))
        for path, expected in manifest["sha256"].items():
            if path != trace:
                self.assertEqual(hashes[path], expected, path)
        self.assertIn("objectives/001-fc27-api-research.md", hashes)
        self.assertIn("objectives/001b-market-discovery-benchmark.md", hashes)
        self.assertEqual(hashes["docs/research/final/manifest.json"], self.lock["historical_manifest_sha256"])
        self.assertFalse(preservation_defects(self.lock, lambda p: (ROOT / p).read_bytes()))

    def test_criterion_1_changed_objective_bridge_evidence_and_deleted_observer_rows_fail(self):
        # Mutate in memory, never touch retained evidence, contracts or user files.
        for path in ('docs/research/transaction/live.json', 'docs/research/final/assessment.json'):
            def read(p):
                raw = (ROOT / p).read_bytes()
                return raw + b" " if p == path else raw
            self.assertIn(path, preservation_defects(self.lock, read))
        prefix = self.lock["observer_prefix"]
        observer = load(prefix["path"])
        for mode in ("delete", "change", "reorder", "append"):
            bad = copy.deepcopy(observer)
            if mode == "delete":
                del bad["observations"][0]
            elif mode == "change":
                bad["observations"][0]["status"] = 599
            elif mode == "reorder":
                bad["observations"][0], bad["observations"][1] = bad["observations"][1], bad["observations"][0]
            else:
                bad["observations"].append(copy.deepcopy(bad["observations"][-1]))
            def read(p):
                return json.dumps(bad).encode() if p == prefix["path"] else (ROOT / p).read_bytes()
            errors = preservation_defects(self.lock, read)
            if mode == "append":
                self.assertFalse(errors, errors)
            else:
                self.assertIn("observer_prefix_changed", errors, mode)

    def test_criterion_1_current_access_and_outcomes_are_explicitly_unobserved(self):
        self.assertEqual(self.ledger["current_browser_attachment"], "NOT_CHECKED")
        self.assertEqual(self.ledger["new_live_observations"], 0)
        self.assertEqual(self.ledger["new_account_mutations"], 0)
        self.assertIn("Current browser attachment is **NOT_CHECKED**", self.scope)
        self.assertIn("current authenticated FC27 PC\naccess is **NOT_CHECKED**", self.scope)
        self.assertIn("does not block T1", self.scope)

    def test_criterion_2_protocol_covers_every_benchmark_dimension(self):
        self.assertFalse(protocol_defects(self.protocol))
        # All nine windows can be derived before any outcome exists.
        timing = self.protocol["timing"]
        windows = [(i * timing["window_seconds"], (i + 1) * timing["window_seconds"], s)
                   for i, s in enumerate(timing["order"])]
        self.assertEqual(windows[-1][1], 2700)
        for strategy in "ABC":
            self.assertEqual(sum(end - start for start, end, s in windows if s == strategy), 900)
        self.assertEqual(pricing.profit(6000, 5000), 700)
        self.assertEqual(pricing.profit(250, 200), 38)

    def test_criterion_2_missing_or_biased_protocol_dimensions_are_rejected(self):
        changes = [
            ("status", "MEASURED"), ("actual_start_utc", "2026-11-11T21:00:00Z"),
            ("run_contract.pin_protocol_sha256_before_first_observation", False),
            ("run_contract.current_attachment", "VERIFIED"),
            ("timing.order", ["A"] * 9), ("timing.window_seconds", 60),
            ("timing.minimum_submission_gap_seconds", 1), ("timing.catch_up", True),
            ("timing.slot_offsets_seconds", [0, 299]), ("budget.per_window", 7),
            ("budget.native_side_effects_consume_budget", False),
            ("budget.background_counted_separately", False),
            ("budget.unequal_actual_budgets", "COMPARABLE"),
            ("search_pair.reset_between_pages", True), ("search_pair.pages", [1, 3]),
            ("strategies.C.rank_scope", "current_window"),
            ("provider.same_snapshot_for_all_strategies_per_block", False),
            ("revalidation.diagnostic_counts_as_opportunity", True),
            ("revalidation.checks", []), ("pricing.exclude_candidate", ["trade_id"]),
            ("pricing.X_scenarios", [0]), ("pricing.threshold_operator", ">"),
            ("pricing.candidate_max_age_seconds", 120),
            ("pricing.missing_rules_executable_yield", 0),
            ("metrics.required", []), ("metrics.zero_revalidation_denominator", 0),
            ("latency.alternative_status", "BENCHMARKED"),
            ("latency.native_service_is_EA_server_latency", True),
            ("latency.p95_min_samples", 1), ("stop.hard", []),
            ("stop.honor_retry_after_even_above_cap", False),
        ]
        for path, value in changes:
            with self.subTest(path=path):
                bad = copy.deepcopy(self.protocol)
                target = bad
                keys = path.split(".")
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.assertIn(2, protocol_defects(bad), path)
        bad = copy.deepcopy(self.protocol)
        bad["strategies"]["B"]["pairs"][0]["nation"] = 46
        self.assertIn(2, protocol_defects(bad))

    def test_criterion_3_each_research_boundary_rejects_mutation_or_removal(self):
        self.assertFalse(protocol_defects(self.protocol))
        for flag in BOUNDARY_FLAGS:
            for mode in ("enable", "remove"):
                bad = copy.deepcopy(self.protocol)
                if mode == "enable":
                    bad["boundary"][flag] = True
                else:
                    del bad["boundary"][flag]
                self.assertIn(3, protocol_defects(bad), (flag, mode))
        for operation in FORBIDDEN:
            bad = copy.deepcopy(self.protocol)
            bad["boundary"]["allowed_operations"].append(operation)
            self.assertIn(3, protocol_defects(bad), operation)
            with self.assertRaises(ValueError):
                read_command(operation, {})
        for term in ("No purchases, bids, moves, listings, relists, cancellations, sold cleanup",
                     "No production bot", "credential/cookie/token exports", "paid subscriptions",
                     "access-control bypasses", "unrelated repository cloning"):
            # Markdown line wraps do not change the boundary language.
            self.assertIn(term, " ".join(self.scope.split()))

    def test_scope_inventory_links_resolve_without_remote_fetches(self):
        path = ROOT / "docs/research/001b-scope.md"
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", self.scope)
        self.assertGreaterEqual(len(links), 25)
        for link in links:
            target = (path.parent / link).resolve()
            self.assertTrue(target.is_relative_to(ROOT), link)
            self.assertTrue(target.is_file(), link)
        for name in ("worker.js", "pricing.py", "native-item-mappings.json", "native-source-shapes.json",
                     "availability.json", "live.json", "verification.json"):
            self.assertTrue(any(name in link for link in links), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
